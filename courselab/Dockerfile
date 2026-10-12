# CourseLab (P1) - course workshop: courses / tasks / review / dashboard.
# Ships the full projects/ + showcase/ trees so the read-only content proxy
# (whitelisted to those two subtrees) works in-container.
# Known boundary: the online lab runner executes run.bat via cmd.exe, which
# does not exist on Linux - use the local run.bat mode for live experiments.
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY courselab/ courselab/
COPY projects/ projects/
COPY showcase/ showcase/
COPY g2/cards.json g2/cards.json
EXPOSE 8024
CMD ["python", "courselab/server.py", "--host", "0.0.0.0", "--port", "8024"]
