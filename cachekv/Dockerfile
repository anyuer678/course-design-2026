# CacheKV (P3) - self-hosted KV cache (TTL + snapshot persistence).
# Engine subclasses the real B38 mini-redis Store.
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY cachekv/ cachekv/
COPY projects/B38-mini-redis/ projects/B38-mini-redis/
EXPOSE 8021
CMD ["python", "cachekv/server.py", "--host", "0.0.0.0"]
