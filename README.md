# Notification Service

Tiny Flask service that receives contact form submissions from the Neosofia corporate site and relays them to the configured inbox via [Resend](https://resend.com).

## API contract

Defined in [`openapi.json`](./openapi.json) (OpenAPI 3.0).

## Architecture

```
GitHub Pages (static site)
  → POST /api/emails
    → Notification Service (Railway)
      → Resend API
        → inquiry@neosofia.tech
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `RESEND_API_KEY` | yes | — | Resend secret API key |
| `NOTIFICATION_FROM` | yes | — | Sender address (must be a verified Resend domain) |
| `NOTIFICATION_TO` | yes | — | Destination inbox |
| `CORS_ORIGINS` | yes | — | Comma-separated allowed origins |
| `PORT` | no | `8005` | HTTP port |
| `ENV` | no | `production` | Set to `development` to disable HTTPS redirect and enable debug mode. This service uses an auth-style env loader that resolves `ENV_FILE` or `ENV` to a configured env file, but direct environment variables are also accepted if neither is provided. |
| `ENV_FILE` | no | — | Optional explicit env file path. If set, it takes precedence over `ENV`. |
| `RATELIMIT_STORAGE_URI` | no | `memory://` | Rate-limit backend for local development. In production, using `memory://` is allowed but not recommended; prefer a durable backend such as `redis://...`. |

## Local development

```bash
cp .env.example .env
# fill in RESEND_API_KEY in .env

uv sync
uv run python -m src.main
```

The service listens on `http://localhost:8005`. `.env.example` ships with
`ENV=development` which disables the HTTPS redirect and enables Flask debug mode.

Set `CORS_ORIGINS` in `.env` to include the corporate dev server so the
browser allows the cross-origin request:

```
CORS_ORIGINS=http://localhost:4173,https://neosofia.tech
```

Set the matching var in the corporate site's `.env`:

```
VITE_EMAIL_API_URL=http://localhost:8005
```

Smoke-test with curl:

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://localhost:8005/api/emails \
  -H "Content-Type: application/json" \
  -d '{"from_email":"you@example.com","subject":"Test","message":"Hello."}'
```

## Resend setup

1. Create an account at <https://resend.com>.
2. Add and verify your sending domain (`neosofia.tech`) under **Domains**.
3. Create an API key under **API Keys** with **Sending access** only.
4. Set the key as `RESEND_API_KEY` in Railway (and locally in `.env`).
5. Confirm your notification destination (`inquiry@neosofia.tech`) is a valid inbox.

## Railway setup

1. Create a new project at <https://railway.app>.
2. Add a new service → **Deploy from GitHub repo** → select this repo.
3. Set the root directory to `notification/` if this is a monorepo.
4. Add environment variables under **Variables**:
   - `RESEND_API_KEY` — your Resend API key
   - `NOTIFICATION_TO` — destination email (e.g. `inquiry@neosofia.tech`)
   - `NOTIFICATION_FROM` — verified sender (e.g. `noreply@neosofia.tech`)
   - `CORS_ORIGINS` — allowed origins (e.g. `https://neosofia.tech`)
   - `RATELIMIT_STORAGE_URI` — durable rate-limit backend in production (e.g. `redis://...`)
5. Railway auto-detects the `Dockerfile` and sets `PORT` automatically.

The service exposes a built-in health endpoint at `/health`. Railway can use this endpoint to verify container readiness and liveness when configuring service probes.

