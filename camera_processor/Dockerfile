# camera-processor: ArUco detection + pose for every camera Pi, off the Pis.
# Built from the repo root (it needs common/ for the shared log format):
#   docker compose build camera-processor
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_NAME=camera-processor

WORKDIR /app
COPY camera_processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY camera_processor ./camera_processor

CMD ["python", "-m", "camera_processor"]
