import traceback

import resend
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from logenvelope.events import log_event
from logenvelope.setup import setup_logging
from werkzeug.middleware.proxy_fix import ProxyFix

from src.config import settings

setup_logging("notification")

RESEND_API_KEY = settings.resend_api_key
NOTIFICATION_FROM = settings.notification_from
NOTIFICATION_TO = settings.notification_to
CORS_ORIGINS = settings.cors_origins

resend.api_key = RESEND_API_KEY

app = Flask(__name__)

# Reject request bodies larger than 16 KiB to prevent body-flood DoS.
app.config["MAX_CONTENT_LENGTH"] = settings.max_content_length

ENV = settings.env.lower()
is_development = ENV in ("development", "test")

if not is_development:
    # Trust exactly one upstream proxy hop (Railway's load balancer).
    # Without this, get_remote_address returns the proxy IP and rate limiting is per-proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    Talisman(
        app,
        force_https=True,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        content_security_policy={"default-src": ["'none'"], "frame-ancestors": ["'none'"]},
        referrer_policy="strict-origin-when-cross-origin",
    )

allowed_origins = settings.cors_origins
if not allowed_origins:
    raise RuntimeError("CORS_ORIGINS must contain at least one allowed origin")
if "*" in allowed_origins:
    raise RuntimeError("CORS_ORIGINS must not include wildcard '*'")

CORS(app, origins=allowed_origins)

rate_limit_storage = settings.rate_limit_storage_uri
if not is_development and rate_limit_storage == "memory://":
    log_event(
        "rate_limit_weak_storage",
        warning="Using in-memory rate limit storage in production",
    )

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "30 per hour"],
    storage_uri=rate_limit_storage,
)


@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"error": "Request payload too large"}), 413


@app.route("/health")
@limiter.exempt
def health():
    return jsonify({"status": "ok"})


@app.route("/api/emails", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def contact():
    payload = request.get_json(silent=True) or {}

    from_email = (payload.get("from_email") or "").strip()
    subject = (payload.get("subject") or "").strip()
    message = (payload.get("message") or "").strip()

    errors = []
    if not from_email:
        errors.append("from_email is required")
    if not subject:
        errors.append("subject is required")
    if not message:
        errors.append("message is required")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    try:
        resend.Emails.send({
            "from": NOTIFICATION_FROM,
            "to": [NOTIFICATION_TO],
            "reply_to": from_email,
            "subject": f"[Contact] {subject}",
            "text": f"From: {from_email}\n\n{message}",
        })
        log_event("contact_relayed", subject=subject)
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "contact_relay_failed",
            error=str(exc),
            exception_type=type(exc).__name__,
            traceback=traceback.format_exc(),
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port, debug=is_development)
