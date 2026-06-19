# Operations

## Routes

- `POST /api/emails` is the public corporate contact-form relay. It requires only the existing CORS and IP-based rate limits and always delivers to `NOTIFICATION_TO`.
- `POST /api/v1/emails` is the protected platform relay. It requires a valid platform JWT and only delivers to caller-specified destinations whose domains are listed in `PLATFORM_EMAIL_ALLOWED_DOMAINS`.

## Protected relay configuration

Set all of the following variables before enabling `POST /api/v1/emails`:

| Variable | Purpose |
|---|---|
| `PLATFORM_JWT_ISSUER` | Exact `iss` claim required on service tokens. |
| `PLATFORM_JWT_AUDIENCE` | Exact `aud` claim required on service tokens. |
| `PLATFORM_JWT_ALLOWED_SUBJECTS` | Comma-separated allowlist of service-token `sub` values permitted to call the protected relay. |
| `PLATFORM_JWT_JWKS_JSON` | JWKS document used for offline JWT verification. Rotate this whenever Authentication rotates service-token signing keys. |
| `PLATFORM_EMAIL_ALLOWED_DOMAINS` | Comma-separated allowlist of recipient domains permitted in `to_email`. |

## Destination policy

v1 uses an env-configured domain allowlist. Requests are rejected unless `to_email` ends in a domain listed in `PLATFORM_EMAIL_ALLOWED_DOMAINS`.

This keeps the protected route from becoming a general-purpose open relay while still allowing per-clinic aliases, distribution lists, and tenant-specific monitored inboxes within approved domains.

## Rollout notes

- Keep the public corporate site on `POST /api/emails`; that route is intentionally unchanged.
- Platform services should mint service JWTs from Authentication and call `POST /api/v1/emails`.
- Protected-route logs include the authenticated subject, `message_type`, and destination domain only; routine logs do not include full message bodies.
