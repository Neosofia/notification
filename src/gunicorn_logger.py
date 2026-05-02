"""Gunicorn logger that emits all log lines as JSON to stdout."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from gunicorn.glogging import Logger


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }
        )


def _stdout_json_handler() -> logging.StreamHandler:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_JSONFormatter())
    return h


class JSONLogger(Logger):
    """Drop-in Gunicorn logger that writes JSON to stdout for all streams."""

    def setup(self, cfg) -> None:  # type: ignore[override]
        super().setup(cfg)
        for log in (self.error_log, self.access_log):
            log.handlers.clear()
            log.addHandler(_stdout_json_handler())
            log.propagate = False

    def access(self, resp, req, environ, request_time) -> None:  # type: ignore[override]
        if not self.access_log_enabled:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "event_type": "http_request",
            "method": environ.get("REQUEST_METHOD"),
            "path": environ.get("PATH_INFO"),
            "status": resp.status_code,
            "duration_ms": round(request_time.total_seconds() * 1000, 2),
            "remote_addr": environ.get("REMOTE_ADDR"),
            "content_length": resp.headers.get("Content-Length"),
        }
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()
