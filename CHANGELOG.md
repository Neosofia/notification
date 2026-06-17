# Changelog

What changed for notification service consumers. Deploy: [INSTALLATION_PLAN.md](INSTALLATION_PLAN.md).

## [Unreleased]

## [0.2.3] - 2026-06-17

### Fixed

- Allow cross-origin `GET /health` for configured `CORS_ORIGINS` so the CDP operator service-health panel can probe notification from the browser.

## [0.2.2] - 2026-06-10

### Fixed

- Structured logs now honor `LOG_LEVEL` — pinned **`logenvelope/v0.3.4`** so handler level matches the service setting before events emit.
