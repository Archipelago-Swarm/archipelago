# Drone node image (one container per node, own volume): python -m archipelago_noderuntime.
# Build context: repo root. CPU torch wheel (download.pytorch.org/whl/cpu), pinned to the version in
# pyproject.toml dependency group "torch" (tests/infra/test_images.py checks they agree).
# The packages are not installed wheels; they are copied and put on PYTHONPATH.
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Pins mirror uv.lock for the pure dependencies of contracts/learning/sim (checked by tests).
RUN uv pip install --system --no-cache --torch-backend cpu \
    "torch==2.14.1" "numpy==2.5.3" "pydantic==2.14.0" "pydantic-core==2.50.0" \
    "annotated-types==0.8.0" "typing-extensions==4.16.0" "typing-inspection==0.4.4"

FROM python:3.12-slim
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
RUN useradd --system --uid 10002 --create-home node && mkdir -p /node-data && chown node /node-data
WORKDIR /repo
COPY packages/contracts packages/contracts
COPY packages/learning packages/learning
COPY packages/sim packages/sim
COPY packages/node/peer packages/node/peer
COPY packages/node/learner packages/node/learner
COPY packages/node/runtime packages/node/runtime
COPY packages/transport packages/transport
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TORCH_THREADS=1 \
    NODE_CHECKPOINT_DIR=/node-data BIND_HOST=0.0.0.0 CONTROL_PORT=8080 PEER_PORT=9000 \
    PYTHONPATH=/repo/packages/node/runtime:/repo/packages/node/peer:/repo/packages/node/learner:/repo/packages/transport:/repo/packages/contracts/src:/repo/packages/learning:/repo/packages/sim
USER node
EXPOSE 8080 9000
# /healthz is the node's only unauthenticated route (packages/node/runtime README).
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "archipelago_noderuntime"]
