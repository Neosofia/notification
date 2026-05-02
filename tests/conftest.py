import os

import pytest

# Set required env vars before the app module is imported.
os.environ.setdefault("RESEND_API_KEY", "test_key")
os.environ.setdefault("NOTIFICATION_FROM", "noreply@example.com")
os.environ.setdefault("NOTIFICATION_TO", "inbox@example.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENV", "test")


@pytest.fixture()
def app(monkeypatch):
    """Return a Flask test-mode app with Resend stubbed out."""
    import resend

    monkeypatch.setattr(resend.Emails, "send", lambda params: {"id": "stub"})

    from src.main import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
