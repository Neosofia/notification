FROM python:3.12-alpine AS builder

RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /repo

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv lock && uv sync --no-dev --no-editable

COPY src ./src

FROM python:3.12-alpine

RUN apk add --no-cache libffi

RUN addgroup -S app && adduser -S -G app app

WORKDIR /app

COPY --from=builder /repo/.venv /repo/.venv
COPY src ./src
COPY gunicorn_conf.py ./gunicorn_conf.py

ENV PATH="/repo/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request, sys; \
resp=urllib.request.urlopen('http://127.0.0.1:8005/health', timeout=5); \
sys.exit(0 if resp.status == 200 else 1)" || exit 1

USER app

CMD ["gunicorn", "-c", "gunicorn_conf.py", "src.main:app"]
