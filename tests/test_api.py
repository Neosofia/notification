"""Integration tests for the notification service API.

Covers:
- Happy path: valid payload relayed successfully
- Contract drift: ContactRequest schema matches openapi.json EmailRequest
- Validation: every required field missing individually and in combination
- Email format: invalid from_email rejected
- Whitespace-only fields rejected (min_length=1)
- Health endpoint liveness
"""

import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

import jwt
import pytest

VALID_PAYLOAD = {
    "from_email": "visitor@example.com",
    "subject": "General inquiry",
    "message": "Hello, I would like to learn more.",
}

VALID_PLATFORM_PAYLOAD = {
    "to_email": "alerts@example.com",
    "from_email": "workflow@example.com",
    "reply_to": "oncall@example.com",
    "subject": "Escalation",
    "message": "Open the dashboard for details.",
    "message_type": "clinical-alert",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_email(client, payload):
    return client.post(
        "/api/emails",
        data=json.dumps(payload),
        content_type="application/json",
    )


def post_platform_email(client, payload, token=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    return client.post(
        "/api/v1/emails",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )


def build_platform_token(private_key, subject="care-episode", **claims):
    now = datetime.now(UTC)
    payload = {
        "iss": "https://auth.test.neosofia",
        "aud": "notification",
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "status": "ok",
        "version": version("neosofia-notification"),
    }


def test_health_allows_configured_cors_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_payload_returns_200(client, resend_messages):
    resp = post_email(client, VALID_PAYLOAD)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent"}
    assert resend_messages == [
        {
            "from": "noreply@example.com",
            "to": ["inbox@example.com"],
            "reply_to": "visitor@example.com",
            "subject": "[Contact] General inquiry",
            "text": "From: visitor@example.com\n\nHello, I would like to learn more.",
        }
    ]


# ---------------------------------------------------------------------------
# Contract: Pydantic schema matches openapi.json EmailRequest
# ---------------------------------------------------------------------------

def test_schema_matches_openapi():
    from src.models import ContactRequest, PlatformEmailRequest

    openapi = json.loads(
        (Path(__file__).parent.parent / "openapi.json").read_text()
    )
    email_request = openapi["components"]["schemas"]["EmailRequest"]
    platform_email_request = openapi["components"]["schemas"]["PlatformEmailRequest"]

    model_schema = ContactRequest.model_json_schema()
    platform_model_schema = PlatformEmailRequest.model_json_schema()

    # Required fields must match exactly
    assert set(email_request["required"]) == set(model_schema.get("required", [])), (
        "openapi.json EmailRequest.required does not match ContactRequest fields"
    )
    assert set(platform_email_request["required"]) == set(platform_model_schema.get("required", [])), (
        "openapi.json PlatformEmailRequest.required does not match PlatformEmailRequest fields"
    )

    # Every property in the OpenAPI schema must exist in the Pydantic model
    for field in email_request["properties"]:
        assert field in model_schema["properties"], (
            f"openapi.json field '{field}' is missing from ContactRequest"
        )
    for field in platform_email_request["properties"]:
        assert field in platform_model_schema["properties"], (
            f"openapi.json field '{field}' is missing from PlatformEmailRequest"
        )


# ---------------------------------------------------------------------------
# Missing fields — each individually
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", ["from_email", "subject", "message"])
def test_missing_field_returns_400(client, missing_field):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing_field}
    resp = post_email(client, payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# Missing fields — all combinations of 2
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("keep_field", ["from_email", "subject", "message"])
def test_two_missing_fields_returns_400(client, keep_field):
    payload = {keep_field: VALID_PAYLOAD[keep_field]}
    resp = post_email(client, payload)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Completely empty body
# ---------------------------------------------------------------------------

def test_empty_body_returns_400(client):
    resp = post_email(client, {})
    assert resp.status_code == 400


def test_non_json_body_returns_400(client):
    resp = client.post("/api/emails", data="not json", content_type="text/plain")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Field format validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_email", ["notanemail", "missing@", "@nodomain", ""])
def test_invalid_from_email_returns_400(client, bad_email):
    resp = post_email(client, {**VALID_PAYLOAD, "from_email": bad_email})
    assert resp.status_code == 400


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_subject_returns_400(client, blank):
    resp = post_email(client, {**VALID_PAYLOAD, "subject": blank})
    assert resp.status_code == 400


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_message_returns_400(client, blank):
    resp = post_email(client, {**VALID_PAYLOAD, "message": blank})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Extra / unknown fields are rejected
# ---------------------------------------------------------------------------

def test_extra_fields_returns_400(client):
    resp = post_email(client, {**VALID_PAYLOAD, "unexpected": "value"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Request size limit
# ---------------------------------------------------------------------------

def test_oversized_body_returns_413(client):
    # Exceeds MAX_CONTENT_LENGTH (16 KiB); Flask rejects before Pydantic runs.
    oversized = "x" * 20_000
    resp = client.post(
        "/api/emails",
        data=oversized,
        content_type="application/json",
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Protected platform relay
# ---------------------------------------------------------------------------

def test_platform_email_requires_bearer_token(client):
    resp = post_platform_email(client, VALID_PLATFORM_PAYLOAD)
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Missing bearer token"}


def test_platform_email_rejects_invalid_token(client):
    resp = post_platform_email(client, VALID_PLATFORM_PAYLOAD, token="not-a-jwt")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_platform_email_rejects_unpermitted_subject(client, platform_private_key):
    token = build_platform_token(platform_private_key, subject="frontend-app")
    resp = post_platform_email(client, VALID_PLATFORM_PAYLOAD, token=token)
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "JWT subject is not permitted"}


def test_platform_email_rejects_disallowed_destination(client, platform_private_key):
    token = build_platform_token(platform_private_key)
    resp = post_platform_email(
        client,
        {**VALID_PLATFORM_PAYLOAD, "to_email": "alerts@outside.example.net"},
        token=token,
    )
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Destination email is not permitted"}


def test_platform_email_relays_to_caller_supplied_destination(client, platform_private_key, resend_messages):
    token = build_platform_token(platform_private_key, subject="ops-bot")
    resp = post_platform_email(client, VALID_PLATFORM_PAYLOAD, token=token)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent"}
    assert resend_messages == [
        {
            "from": "noreply@example.com",
            "to": ["alerts@example.com"],
            "reply_to": "oncall@example.com",
            "subject": "[clinical-alert] Escalation",
            "text": "From: workflow@example.com\nReply-To: oncall@example.com\n\nOpen the dashboard for details.",
        }
    ]
