# DataScope (P4) - CSV profiling / cleaning / Apriori / K-means workbench.
# Mining engine imports the real B26 implementation (no second copy).
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY datascope/ datascope/
COPY projects/B26-datamining/ projects/B26-datamining/
EXPOSE 8020
CMD ["python", "datascope/server.py", "--host", "0.0.0.0"]
