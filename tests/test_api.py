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
from pathlib import Path

import pytest

VALID_PAYLOAD = {
    "from_email": "visitor@example.com",
    "subject": "General inquiry",
    "message": "Hello, I would like to learn more.",
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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_payload_returns_200(client):
    resp = post_email(client, VALID_PAYLOAD)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent"}


# ---------------------------------------------------------------------------
# Contract: Pydantic schema matches openapi.json EmailRequest
# ---------------------------------------------------------------------------

def test_schema_matches_openapi():
    from src.models import ContactRequest

    openapi = json.loads(
        (Path(__file__).parent.parent / "openapi.json").read_text()
    )
    email_request = openapi["components"]["schemas"]["EmailRequest"]

    model_schema = ContactRequest.model_json_schema()

    # Required fields must match exactly
    assert set(email_request["required"]) == set(model_schema.get("required", [])), (
        "openapi.json EmailRequest.required does not match ContactRequest fields"
    )

    # Every property in the OpenAPI schema must exist in the Pydantic model
    for field in email_request["properties"]:
        assert field in model_schema["properties"], (
            f"openapi.json field '{field}' is missing from ContactRequest"
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
