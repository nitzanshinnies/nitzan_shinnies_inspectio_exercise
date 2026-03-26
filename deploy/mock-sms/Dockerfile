# Greenfield mock SMS (plans/openapi.yaml POST /send, §19).
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY deploy/mock-sms/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY deploy/mock-sms/app.py ./

EXPOSE 8080
ENV INSPECTIO_MOCK_SMS_PORT=8080

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${INSPECTIO_MOCK_SMS_PORT:-8080}"]
