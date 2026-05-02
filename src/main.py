import logging
import sys
import traceback

import resend
from flask import Flask, jsonify, request
from pydantic import ValidationError
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from logenvelope.events import log_event
from logenvelope.formatter import JSONFormatter
from logenvelope.setup import setup_logging
from werkzeug.middleware.proxy_fix import ProxyFix

from src.config import settings
from src.models import ContactRequest

setup_logging("notification")

# Route all framework loggers to stdout with the same JSON formatter
# so every log line from every part of the process is parseable.
_json_handler = logging.StreamHandler(sys.stdout)
_json_handler.setFormatter(JSONFormatter())
for _name in ("notification", "werkzeug", "flask.app"):
    _log = logging.getLogger(_name)
    _log.handlers = [_json_handler]
    _log.propagate = False

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
    return jsonify({"status": "ok"})


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
            "from": NOTIFICATION_FROM,
            "to": [NOTIFICATION_TO],
            "reply_to": body.from_email,
            "subject": f"[Contact] {body.subject}",
            "text": f"From: {body.from_email}\n\n{body.message}",
        })
        log_event("email_relayed", subject=body.subject)
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "email_relay_failed",
            error=str(exc),
            exception_type=type(exc).__name__,
            traceback=traceback.format_exc(),
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port, debug=is_development)
