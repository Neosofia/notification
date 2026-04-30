import os
from pathlib import Path

import resend
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from logenvelope.events import log_event
from logenvelope.setup import setup_logging
from werkzeug.middleware.proxy_fix import ProxyFix

_ENV_FILE = Path(__file__).parent.parent / ".local.env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)

setup_logging("notification")

def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


RESEND_API_KEY = _require("RESEND_API_KEY")
NOTIFICATION_FROM = _require("NOTIFICATION_FROM")
NOTIFICATION_TO = _require("NOTIFICATION_TO")
CORS_ORIGINS = _require("CORS_ORIGINS")

resend.api_key = RESEND_API_KEY

app = Flask(__name__)

# Reject request bodies larger than 16 KiB to prevent body-flood DoS.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", 16_384))

is_development = os.environ.get("ENV", "production").lower() in ("development", "test")

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
        content_security_policy=False,
        referrer_policy="strict-origin-when-cross-origin",
    )

CORS(app, origins=CORS_ORIGINS.split(","))

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "30 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)


@app.route("/health")
@limiter.exempt
def health():
    return jsonify({"status": "ok"})


@app.route("/api/emails", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def contact():
    data = request.get_json(silent=True) or {}

    from_email = (data.get("from_email") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

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
        log_event("contact_relay_failed", error=str(exc))
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8005))
    app.run(host="0.0.0.0", port=port, debug=is_development)
