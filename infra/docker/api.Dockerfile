# Run API image. Build context: repo root. NOT RUN: never built (Docker daemon unavailable).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY services/api services/api
COPY packages/contracts packages/contracts
COPY packages/storage packages/storage
# Locked, production-only install of the API workspace member (no dev group).
RUN uv sync --frozen --no-dev --package archipelago-api

FROM python:3.12-slim
RUN useradd --system --uid 10001 --create-home app && mkdir -p /data && chown app /data
WORKDIR /repo
COPY --from=build /repo /repo
ENV PATH="/repo/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    ARCHIPELAGO_DATA_DIR=/data \
    ARCHIPELAGO_FIXTURE_DIR=/repo/packages/contracts/fixtures/good
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"
# ARCHIPELAGO_API_TOKEN (>=16 chars) is required at start and is injected by Compose, never baked in.
CMD ["uvicorn", "archipelago_api.app:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
