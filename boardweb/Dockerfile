# BoardWeb (P8) - browser whiteboard: shapes / selection / paste / undo.
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY boardweb/ boardweb/
EXPOSE 8025
CMD ["python", "boardweb/server.py", "--host", "0.0.0.0"]
