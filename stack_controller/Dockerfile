FROM docker:27-cli

RUN apk add --no-cache python3 py3-pip

WORKDIR /app
COPY stack_controller/requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY stack_controller ./stack_controller

EXPOSE 8080
CMD ["uvicorn", "stack_controller.main:app", "--host", "0.0.0.0", "--port", "8080"]
