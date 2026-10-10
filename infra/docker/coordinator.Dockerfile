# World coordinator image (single instance): python -m archipelago_coordinator. No torch.
# Build context: repo root. Packages are copied and put on PYTHONPATH (not installed wheels).
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN uv pip install --system --no-cache \
    "numpy==2.5.3" "pydantic==2.14.0" "pydantic-core==2.50.0" \
    "annotated-types==0.8.0" "typing-extensions==4.16.0" "typing-inspection==0.4.4"

FROM python:3.12-slim
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
RUN useradd --system --uid 10003 --create-home coordinator \
    && mkdir -p /data/coordinator && chown coordinator /data/coordinator
WORKDIR /repo
COPY packages/contracts packages/contracts
COPY packages/sim packages/sim
COPY packages/adapters/sim2d packages/adapters/sim2d
COPY services/coordinator services/coordinator
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ARCHIPELAGO_ENV=production COORDINATOR_DATA_DIR=/data/coordinator \
    COORDINATOR_HOST=0.0.0.0 COORDINATOR_PORT=8800 \
    PYTHONPATH=/repo/services/coordinator:/repo/packages/sim:/repo/packages/adapters/sim2d:/repo/packages/contracts/src
USER coordinator
EXPOSE 8800
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/healthz',timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "archipelago_coordinator"]
