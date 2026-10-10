# Build smoke for the workspace: proves locked installs and checks work in a clean image.
# This is not a deployable service image (T10).
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY . .
RUN uv sync --frozen && scripts/install-torch-cpu.sh && npm ci
CMD ["bash", "scripts/check.sh"]
