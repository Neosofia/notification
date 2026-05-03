"""Container integration tests.

Runs against a live HTTP server to verify the image builds cleanly,
Gunicorn starts and serves correctly, and key endpoints respond as expected.

Set BASE_URL to target a specific instance (default: http://localhost:8005).

Coverage is not collected here. src/gunicorn_logger.py is exercised by this
suite and is therefore excluded from the unit-test coverage report.
"""

import os

import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8005").rstrip("/")

VALID_PAYLOAD = {
    "from_email": "visitor@example.com",
    "subject": "Integration test",
    "message": "Hello from the integration test suite.",
}


def test_health():
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_valid_payload_returns_200_or_502():
    """Valid payload returns 200 (live Resend key) or 502 (stub/invalid key).
    Either outcome proves the request traversed the full application stack.
    """
    resp = requests.post(f"{BASE_URL}/api/emails", json=VALID_PAYLOAD, timeout=15)
    assert resp.status_code in (200, 502)
