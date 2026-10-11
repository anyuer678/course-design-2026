# SimLab (P5) - algorithm/system simulation player. Engines import the real
# B12 (Dijkstra / knapsack DP) and B34 (A*) implementations, never rewritten.
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY simlab/ simlab/
COPY projects/B12-algo-arena/ projects/B12-algo-arena/
COPY projects/B34-path-planner/ projects/B34-path-planner/
EXPOSE 8019
CMD ["python", "simlab/server.py", "--host", "0.0.0.0"]
