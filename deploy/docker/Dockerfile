# v3 app image (scaffold). Replaces archived v2 image at v2_obsolete/archive/deploy/docker/Dockerfile.
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

CMD ["python", "-c", "print('inspectio v3: no long-running entrypoint yet')"]
