# Security

## Public vs protected relay paths

- `POST /api/emails` remains the unprotected corporate contact path. It is constrained to `NOTIFICATION_TO` and protected by CORS and existing IP-based rate limits.
- `POST /api/v1/emails` is reserved for platform services. It requires a bearer JWT, validates that token offline against configured JWKS keys, and checks `iss`, `aud`, and allowlisted `sub` claims before relaying mail.

## Destination controls

The protected route accepts caller-specified `to_email` values only when the destination domain is present in `PLATFORM_EMAIL_ALLOWED_DOMAINS`. Requests outside that policy are rejected with `400`.

## Logging and PHI handling

Routine relay logs avoid full message content. Protected-route events record only opaque operational correlators needed for debugging and audit:

- authenticated JWT subject
- `message_type`
- destination email domain
- success/failure outcome

The service does not log the full email body for normal relay success/failure events.
