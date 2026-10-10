# Drone node image (one container per node, own volume). NOT RUN: never built.
# PLACEHOLDER: packages/node has learner/peer libraries but no node entrypoint and is not a
# uv workspace member yet. CMD names the intended module; whoever adds the node service must
# provide it and update uv.lock before this image can build or start.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY packages/contracts packages/contracts
COPY packages/node packages/node
COPY packages/transport packages/transport
COPY packages/learning packages/learning
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --system --uid 10002 --create-home node && mkdir -p /node-data && chown node /node-data
WORKDIR /repo
COPY --from=build /repo /repo
ENV PATH="/repo/.venv/bin:$PATH" PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 \
    NODE_CHECKPOINT_DIR=/node-data PEER_PORT=9000
USER node
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1',9000),2)"
CMD ["python", "-m", "archipelago_node"]
