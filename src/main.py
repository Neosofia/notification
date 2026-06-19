import json
from collections.abc import Callable
from functools import lru_cache, wraps

from authentication_in_the_middle.decorators import with_authentication
from authentication_in_the_middle.logging import log_authentication_failed
import jwt
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

from src.config import settings
from src.models import ContactRequest, PlatformEmailRequest
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


@lru_cache
def _platform_jwk_keys() -> dict[str, object]:
    if not settings.platform_jwt_jwks_json:
        return {}

    jwks = json.loads(settings.platform_jwt_jwks_json)
    keys: dict[str, object] = {}
    for jwk in jwks.get("keys", []):
        kid = jwk.get("kid")
        if isinstance(kid, str) and kid:
            keys[kid] = jwt.PyJWK.from_dict(jwk).key
    return keys


def _platform_jwt_configured() -> bool:
    return bool(
        settings.platform_jwt_issuer
        and settings.platform_jwt_audience
        and settings.platform_jwt_allowed_subjects
        and settings.platform_email_allowed_domains
        and _platform_jwk_keys()
    )


def _platform_signing_kid(token: str) -> str:
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise jwt.InvalidTokenError("JWT is missing a kid header")

    if _platform_jwk_keys().get(kid) is None:
        raise jwt.InvalidTokenError("JWT signing key is not trusted")
    return kid


@lru_cache(maxsize=16)
def _platform_authenticated_view(view: Callable, kid: str | None):
    public_key = _platform_jwk_keys().get(kid) if kid else None
    return with_authentication(
        public_key=public_key,
        audience=settings.platform_jwt_audience,
        enforce_active_actor=False,
    )(view)


def _platform_rate_limit_key() -> str:
    return getattr(g, "platform_subject", get_remote_address())


def _authorize_platform_subject(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        claims = getattr(g, "jwt_claims", {})
        issuer = claims.get("iss")
        if issuer != settings.platform_jwt_issuer:
            log_authentication_failed(
                reason="issuer_invalid",
                status_code=401,
                route=view.__name__,
                error_type="InvalidIssuerError",
            )
            return jsonify({"error": "unauthenticated", "detail": "Invalid token"}), 401
        subject = claims.get("sub")
        if not isinstance(subject, str) or subject not in settings.platform_jwt_allowed_subjects:
            return jsonify({"error": "forbidden", "detail": "JWT subject is not permitted"}), 403
        g.platform_subject = subject
        g.platform_claims = claims
        return view(*args, **kwargs)

    return wrapped


def _authenticate_platform_request(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _platform_jwt_configured():
            return jsonify({"error": "Protected relay is not configured"}), 503

        platform_kid = None
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
            try:
                platform_kid = _platform_signing_kid(token)
            except jwt.InvalidTokenError as exc:
                log_authentication_failed(
                    reason="token_invalid",
                    status_code=401,
                    route=view.__name__,
                    error_type=type(exc).__name__,
                )
                return jsonify({"error": "unauthenticated", "detail": "Invalid token"}), 401

        authenticated_view = _platform_authenticated_view(view, platform_kid)
        return authenticated_view(*args, **kwargs)

    return wrapped


def _require_platform_jwt(view):
    return _authenticate_platform_request(_authorize_platform_subject(view))


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
@_require_platform_jwt
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
            jwt_subject=g.platform_subject,
            message_type=body.message_type,
            to_email_domain=_email_domain(body.to_email),
        )
        return jsonify({"status": "sent"}), 200
    except Exception as exc:
        log_event(
            "platform_email.relay_failed",
            message="Failed to relay protected platform email via Resend",
            exception_type=type(exc).__name__,
            jwt_subject=getattr(g, "platform_subject", "unknown"),
            message_type=body.message_type,
            to_email_domain=_email_domain(body.to_email),
        )
        return jsonify({"error": "Failed to relay message. Please try again later."}), 502


if __name__ == "__main__":
    # Bind to loopback in dev — never expose the Werkzeug debugger to the network.
    host = "127.0.0.1" if is_development else "0.0.0.0"
    app.run(host=host, port=settings.port, debug=is_development)
