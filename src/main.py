from functools import wraps

from authorization_in_the_middle import CedarEvaluator, FilesystemPolicySetSource
from authorization_in_the_middle.security import with_security
import resend
from resend.http_client_requests import RequestsClient
from flask import Flask, g, jsonify, request
from pydantic import ValidationError
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from logenvelope.events import log_event
from logenvelope.setup import setup_logging
from werkzeug.middleware.proxy_fix import ProxyFix

from src.authorization.entities import platform_email_relay_entities, platform_email_relay_resource_uid
from src.config import settings
from src.models import ContactRequest, PlatformEmailRequest
from src.version import service_version

setup_logging("notification", settings.log_level)

resend.api_key = settings.resend_api_key
resend.default_http_client = RequestsClient(timeout=10)

app = Flask(__name__)
if settings.platform_jwt_verification_key is not None:
    app.config.setdefault("JWT_PUBLIC_KEY", settings.platform_jwt_verification_key)
if settings.platform_jwt_jwks_uri:
    app.config.setdefault("JWT_JWKS_URI", settings.platform_jwt_jwks_uri)
app.config.setdefault("JWT_AUDIENCE", settings.platform_jwt_audience)
app.extensions["cedar_evaluator"] = CedarEvaluator(
    policy_source=FilesystemPolicySetSource(
        settings.authorization_policies_dir,
        cache_ttl=settings.authorization_policy_cache_ttl,
    )
)

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

# /health is probed cross-origin by the CDP operator dashboard; /api/* by corporate contact forms.
CORS(
    app,
    resources={
        r"/api/*": {"origins": settings.cors_origins},
        r"/health": {"origins": settings.cors_origins},
    },
    max_age=86400,
)

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


def _email_domain(address: str) -> str:
    return address.rsplit("@", 1)[1].lower()


def _platform_jwt_configured() -> bool:
    return bool(
        settings.platform_jwt_issuer
        and settings.platform_jwt_audience
        and settings.platform_jwt_allowed_subjects
        and settings.platform_email_allowed_domains
        and (settings.platform_jwt_verification_key or settings.platform_jwt_jwks_uri)
    )


def _platform_rate_limit_key() -> str:
    claims = getattr(g, "jwt_claims", {}) or {}
    subject = claims.get("sub")
    if isinstance(subject, str) and subject:
        return subject
    return get_remote_address()


def _platform_security_context():
    claims = getattr(g, "jwt_claims", {}) or {}
    return {"issuer": str(claims.get("iss") or "")}


def _platform_subject() -> str:
    claims = getattr(g, "jwt_claims", {}) or {}
    return str(claims.get("sub", "unknown"))


def _require_platform_relay_config(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _platform_jwt_configured():
            return jsonify({"error": "Protected relay is not configured"}), 503
        return view(*args, **kwargs)

    return wrapped


def _send_email(to_email: str, subject: str, message: str, reply_to: str | None = None):
    payload = {
        "from": settings.notification_from,
        "to": [to_email],
        "subject": subject,
        "text": message,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    resend.Emails.send(payload)


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
        _send_email(
            to_email=settings.notification_to,
            reply_to=body.from_email,
            subject=f"[Contact] {body.subject}",
            message=f"From: {body.from_email}\n\n{body.message}",
        )
        log_event("email.relayed", message="Email relayed successfully")
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "email.relay_failed",
            message="Failed to relay email via Resend",
            exception_type=type(exc).__name__,
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


@app.route("/api/v1/emails", methods=["POST"])
@_require_platform_relay_config
@with_security(
    action='Action::"platform-email:send"',
    resource_fn=platform_email_relay_resource_uid,
    entities_fn=platform_email_relay_entities,
    context_fn=_platform_security_context,
    enforce_active_actor=False,
)
@limiter.limit("30 per minute", key_func=_platform_rate_limit_key)
@limiter.limit("120 per hour", key_func=_platform_rate_limit_key)
def platform_email():
    try:
        body = PlatformEmailRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        errors = "; ".join(e["msg"] for e in exc.errors())
        return jsonify({"error": errors}), 400

    if _email_domain(body.to_email) not in settings.platform_email_allowed_domains:
        return jsonify({"error": "Destination email is not permitted"}), 400

    reply_to = body.reply_to or body.from_email
    preamble = []
    if body.from_email:
        preamble.append(f"From: {body.from_email}")
    if body.from_email and reply_to and reply_to != body.from_email:
        preamble.append(f"Reply-To: {reply_to}")
    if preamble:
        preamble.append("")

    try:
        _send_email(
            to_email=body.to_email,
            reply_to=reply_to,
            subject=f"[{body.message_type}] {body.subject}",
            message="\n".join([*preamble, body.message]),
        )
        log_event(
            "platform_email.relayed",
            message="Protected platform email relayed successfully",
            jwt_subject=_platform_subject(),
            message_type=body.message_type,
            to_email_domain=_email_domain(body.to_email),
        )
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "platform_email.relay_failed",
            message="Failed to relay protected platform email via Resend",
            exception_type=type(exc).__name__,
            jwt_subject=_platform_subject(),
            message_type=body.message_type,
            to_email_domain=_email_domain(body.to_email),
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    # Bind to loopback in dev — never expose the Werkzeug debugger to the network.
    host = "127.0.0.1" if is_development else "0.0.0.0"
    app.run(host=host, port=settings.port, debug=is_development)
