# LinkBox (P2) - short URL + text stash + QR. Reuses B31 engine + B11 netlab.
# Build from repo root: docker build -f linkbox/Dockerfile -t kcsuite-linkbox .
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY linkbox/ linkbox/
COPY projects/B11-net-lab/ projects/B11-net-lab/
COPY projects/B31-shorturl/ projects/B31-shorturl/
EXPOSE 8018
CMD ["python", "linkbox/server.py", "--host", "0.0.0.0"]
