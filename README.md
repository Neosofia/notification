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
| `ENV` | no | `production` | Set to `development` to disable HTTPS redirect and enable debug mode. |
| `LOG_LEVEL` | no | `info` | Log level for this service and Gunicorn; set to `debug`, `info`, `warning`, or `error` as needed. |
| `RATELIMIT_STORAGE_URI` | no | `memory://` | Rate-limit backend. Defaults to in-memory, which is fine for a single-instance deployment. A shared backend (e.g. `redis://...`) will be required when scaling to multiple instances or regions — tracked as future work. |
| `TRUSTED_PROXY_HOPS` | no | `1` | Number of trusted upstream reverse-proxy hops. Set to match your deployment topology: `1` for a single load balancer (Railway, single Traefik), `2` for CDN + LB (Cloudflare + ALB), `0` to disable proxy header trust entirely (direct exposure or Netbird mesh with no LB). |

## Testing

### Unit tests

```bash
uv run pytest
```

Covers the full application stack via Flask's test client. `src/gunicorn_logger.py` is excluded from the coverage report — it is exercised by the container integration tests below.

### Integration tests

Run integration tests locally with uv. These tests exercise the real Flask application and its endpoints.

```bash
uv run pytest tests/integration/ -v --no-cov
```

A valid-payload test may return `502` when Resend rejects the stub API key; that is expected and confirms the request reached the full stack.

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

