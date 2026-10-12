# SensorHub (P6) - IoT monitoring: simulated sensors -> MQTT broker -> SQLite.
# MQTT broker imports the real B35 implementation (hand-written protocol).
FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY sensorhub/ sensorhub/
COPY projects/B35-iot-mqtt/ projects/B35-iot-mqtt/
COPY webframe/ webframe/
EXPOSE 8022
CMD ["python", "sensorhub/server.py", "--host", "0.0.0.0"]
