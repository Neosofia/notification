# Product Installation Plan

Per-version deploy and verification steps for operators.

## notification v0.2.3

**Build identifiers:** **notification v0.2.3**.

**Prerequisites:**

- `CORS_ORIGINS` must include every UI origin that probes `/health` (e.g. `https://staging.neosofia.tech` for CDP staging, `https://neosofia.tech` for corporate).

**Deploy:**

1. Pull `ghcr.io/neosofia/notification:v0.2.3` (tag `notification/v0.2.3`).
2. Ensure `CORS_ORIGINS` lists CDP and corporate UI origins (comma-separated, no wildcard).
3. Redeploy.

**Post-deploy verification:**

1. `GET /health` returns `"status": "ok"` and `"version": "0.2.3"`.
2. From the CDP operator dashboard (or `curl -H 'Origin: https://staging.neosofia.tech' -I https://<notification-host>/health`), response includes `Access-Control-Allow-Origin: https://staging.neosofia.tech`.
3. CDP service health panel shows notification as **Healthy**.

**Evidence:**

- Health version matches **0.2.3**.
- Browser health probe succeeds (no CORS failure).

## notification v0.2.2

**Build identifiers:** **notification v0.2.2**; SDK **`logenvelope/v0.3.4`**.

**Prerequisites:**

- None beyond the prior release.

**Deploy:**

1. Pull `ghcr.io/neosofia/notification:v0.2.2` (tag `notification/v0.2.2`).
2. Redeploy with existing env unchanged.

**Post-deploy verification:**

1. `GET /health` returns `"status": "ok"` and `"version": "0.2.2"`.
2. With `LOG_LEVEL=warning`, relay success logs (`email.relayed`) do not appear at info; warnings and errors still emit.

**Evidence:**

- Health version matches **0.2.2**.
- Log level behavior matches the configured `LOG_LEVEL`.
