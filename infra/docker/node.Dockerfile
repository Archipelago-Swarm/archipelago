# Drone node image (one container per node, own volume). Runs infra/node/entrypoint.py.
# Peer and transport packages are stdlib-only, so no uv sync; they are put on PYTHONPATH.
FROM python:3.12-slim
RUN useradd --system --uid 10002 --create-home node && mkdir -p /node-data && chown node /node-data
WORKDIR /repo
COPY packages/node/peer packages/node/peer
COPY packages/transport packages/transport
COPY infra/node/entrypoint.py entrypoint.py
ENV PYTHONUNBUFFERED=1 NODE_CHECKPOINT_DIR=/node-data PEER_PORT=9000 \
    PYTHONPATH=/repo/packages/node/peer:/repo/packages/transport
USER node
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1',9000),2)"
CMD ["python", "/repo/entrypoint.py"]
