import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate_platform_test_keys() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-kid",
                "use": "sig",
                "alg": "RS256",
                "n": _base64url_uint(public_key.n),
                "e": _base64url_uint(public_key.e),
            }
        ]
    }
    return (
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
        json.dumps(jwks),
    )


TEST_PLATFORM_PRIVATE_KEY, TEST_PLATFORM_JWKS_JSON = _generate_platform_test_keys()

# Set required env vars before the app module is imported.
os.environ.setdefault("RESEND_API_KEY", "test_key")
os.environ.setdefault("NOTIFICATION_FROM", "noreply@example.com")
os.environ.setdefault("NOTIFICATION_TO", "inbox@example.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("PLATFORM_JWT_ISSUER", "https://auth.test.neosofia")
os.environ.setdefault("PLATFORM_JWT_AUDIENCE", "notification")
os.environ.setdefault("PLATFORM_JWT_ALLOWED_SUBJECTS", "care-episode,ops-bot")
os.environ.setdefault("PLATFORM_JWT_JWKS_JSON", TEST_PLATFORM_JWKS_JSON)
os.environ.setdefault("PLATFORM_EMAIL_ALLOWED_DOMAINS", "example.com,clinic.example.org")


@pytest.fixture()
def app(monkeypatch):
    """Return a Flask test-mode app with Resend stubbed out."""
    import resend

    sent_messages = []

    def fake_send(params):
        sent_messages.append(params)
        return {"id": "stub"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)

    from src.main import app as flask_app

    flask_app.config["TESTING"] = True
    flask_app.extensions["resend_messages"] = sent_messages
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def resend_messages(app):
    return app.extensions["resend_messages"]


@pytest.fixture()
def platform_private_key():
    return TEST_PLATFORM_PRIVATE_KEY
