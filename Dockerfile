FROM python:3.12-alpine AS builder

RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /repo

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv lock && uv sync --no-dev --no-editable

COPY src ./src

FROM python:3.12-alpine

RUN apk add --no-cache libffi

WORKDIR /app

COPY --from=builder /repo/.venv /app/.venv
COPY src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

EXPOSE 8005

CMD ["python", "-m", "src.main"]
