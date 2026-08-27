FROM python:3.13

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client chrony \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /fast_server
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fast_server ./fast_server
COPY db ./db

EXPOSE 8000
CMD ["uvicorn", "fast_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
