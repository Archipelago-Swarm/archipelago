# Mission simulator server (stdlib only, no deps). Build context: repo root.
FROM python:3.12-slim
RUN useradd --system --uid 10004 --create-home mission
WORKDIR /repo
COPY packages/mission packages/mission
COPY packages/sim packages/sim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/repo/packages/mission:/repo/packages/sim
USER mission
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/mission/health',timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "archipelago_mission.serve", "--host", "0.0.0.0", "--port", "8765"]
