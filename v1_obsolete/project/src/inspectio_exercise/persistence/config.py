"""Environment-driven persistence backend selection (plans/LOCAL_S3.md §5, SYSTEM_OVERVIEW)."""

from __future__ import annotations

import os

BACKEND_AWS = "aws"
BACKEND_LOCAL = "local"

LOCAL_S3_STORAGE_FILE = "file"
LOCAL_S3_STORAGE_MEMORY = "memory"

ENV_AWS_ENDPOINT_URL = "AWS_ENDPOINT_URL"
ENV_AWS_REGION = "AWS_REGION"
ENV_AWS_REGION_LEGACY = "AWS_DEFAULT_REGION"
ENV_LOCAL_S3_ROOT = "LOCAL_S3_ROOT"
ENV_LOCAL_S3_STORAGE = "INSPECTIO_LOCAL_S3_STORAGE"
ENV_PERSISTENCE_BACKEND = "INSPECTIO_PERSISTENCE_BACKEND"
ENV_S3_BUCKET = "INSPECTIO_S3_BUCKET"
ENV_S3_BUCKET_FALLBACK = "S3_BUCKET"

S3_BOTOCORE_CONNECT_TIMEOUT_SEC: float = float(
    os.environ.get("INSPECTIO_S3_CONNECT_TIMEOUT_SEC", "10")
)
S3_BOTOCORE_MAX_RETRY_ATTEMPTS: int = int(os.environ.get("INSPECTIO_S3_MAX_RETRY_ATTEMPTS", "5"))
S3_BOTOCORE_READ_TIMEOUT_SEC: float = float(os.environ.get("INSPECTIO_S3_READ_TIMEOUT_SEC", "60"))

# Thread pool size for parallel ``put_objects`` (AWS S3 and optional local file writes).
PERSISTENCE_PUT_MAX_WORKERS: int = max(
    1,
    int(
        os.environ.get(
            "INSPECTIO_PERSISTENCE_PUT_MAX_WORKERS",
            os.environ.get("INSPECTIO_S3_PUT_MAX_WORKERS", "32"),
        )
    ),
)

# Max objects per ``POST /internal/v1/put-objects`` (request body size / fairness).
HTTP_PUT_OBJECTS_MAX_ITEMS: int = max(
    1, int(os.environ.get("INSPECTIO_HTTP_PUT_OBJECTS_MAX_ITEMS", "512"))
)


def aws_region_name() -> str | None:
    """Explicit region for the S3 client, or ``None`` to use the default resolver chain."""
    return os.environ.get(ENV_AWS_REGION) or os.environ.get(ENV_AWS_REGION_LEGACY) or None


def aws_endpoint_url() -> str | None:
    url = os.environ.get(ENV_AWS_ENDPOINT_URL)
    return url if url else None


def s3_bucket_name() -> str | None:
    return os.environ.get(ENV_S3_BUCKET) or os.environ.get(ENV_S3_BUCKET_FALLBACK) or None
