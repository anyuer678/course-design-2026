# Studio portal (P0) - stdlib-only, runs on self-made webframe.
# Build from repo root: docker build -f studio/Dockerfile -t kcsuite-studio .
# Container note: the status panel probes 127.0.0.1 inside this container,
# so sibling containers show as offline and one-click start/stop is a
# local-mode feature. Directory and per-product pages work as-is.
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY studio/ studio/
EXPOSE 8017
CMD ["python", "studio/server.py", "--host", "0.0.0.0"]
