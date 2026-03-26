# Normative image for inspectio-api | inspectio-worker | inspectio-notification (§29).
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Overridden per process in compose / k8s (plans/IMPLEMENTATION_PHASES P9, §29.3).
CMD ["python", "-c", "import inspectio"]
