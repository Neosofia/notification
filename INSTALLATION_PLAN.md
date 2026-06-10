# Product Installation Plan

Per-version deploy and verification steps for operators.

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
