# Container smoke: proves the locked install works in a clean image and the API boots/imports.
# Container-specific only (no lint, no torch, no node); generic checks live in the PR gate.
# This is not a deployable service image (T10).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /repo
COPY . .
RUN uv sync --frozen
ENV CHECK_PART=smoke
CMD ["bash", "scripts/check.sh"]
