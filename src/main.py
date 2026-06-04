import resend
from resend.http_client_requests import RequestsClient
from flask import Flask, jsonify, request
from pydantic import ValidationError
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from logenvelope.events import log_event
from logenvelope.setup import setup_logging
from werkzeug.middleware.proxy_fix import ProxyFix

from src.config import settings
from src.models import ContactRequest
from src.version import service_version

setup_logging("notification", settings.log_level)

resend.api_key = settings.resend_api_key
resend.default_http_client = RequestsClient(timeout=10)

app = Flask(__name__)

# Reject request bodies larger than 16 KiB to prevent body-flood DoS.
app.config["MAX_CONTENT_LENGTH"] = settings.max_content_length

ENV = settings.env.lower()
is_development = ENV in ("development", "test")

if not is_development:
    # Number of trusted upstream proxy hops — set TRUSTED_PROXY_HOPS to match your
    # deployment topology (e.g. 1 for Railway/single LB, 2 for CDN+LB, 0 to disable).
    # Without this, get_remote_address returns the proxy IP and rate limiting is per-proxy.
    _hops = settings.trusted_proxy_hops
    if _hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_hops, x_proto=_hops, x_host=_hops, x_prefix=_hops)

# Talisman runs in all environments so CSP/HSTS regressions are caught by tests.
# force_https and HSTS are only meaningful in production.
Talisman(
    app,
    force_https=not is_development,
    strict_transport_security=not is_development,
    strict_transport_security_max_age=31536000,
    strict_transport_security_include_subdomains=True,
    content_security_policy={"default-src": ["'none'"], "frame-ancestors": ["'none'"]},
    referrer_policy="strict-origin-when-cross-origin",
)

# Restrict CORS to API routes only; /health needs no cross-origin access.
CORS(app, resources={r"/api/*": {"origins": settings.cors_origins}})

rate_limit_storage = settings.rate_limit_storage_uri
if not is_development and rate_limit_storage == "memory://":
    log_event(
        "rate_limit.weak_storage",
        message="In-memory rate limit storage is not suitable for production",
    )

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[] if is_development else ["200 per day", "30 per hour"],
    storage_uri=rate_limit_storage,
    enabled=not is_development,
)


@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "Request payload too large"}), 413


@app.route("/health")
@limiter.exempt
def health():
    return jsonify({"status": "ok", "version": service_version()})


@app.route("/api/emails", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def contact():
    try:
        body = ContactRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        errors = "; ".join(e["msg"] for e in exc.errors())
        return jsonify({"error": errors}), 400

    try:
        resend.Emails.send({
            "from": settings.notification_from,
            "to": [settings.notification_to],
            "reply_to": body.from_email,
            "subject": f"[Contact] {body.subject}",
            "text": f"From: {body.from_email}\n\n{body.message}",
        })
        log_event("email.relayed", message="Email relayed successfully")
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "email.relay_failed",
            message="Failed to relay email via Resend",
            exception_type=type(exc).__name__,
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    # Bind to loopback in dev — never expose the Werkzeug debugger to the network.
    host = "127.0.0.1" if is_development else "0.0.0.0"
    app.run(host=host, port=settings.port, debug=is_development)
