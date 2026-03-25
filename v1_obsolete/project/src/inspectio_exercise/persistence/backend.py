"""Select ``PersistencePort`` implementation from environment (plugin wiring)."""

from __future__ import annotations

import os
from pathlib import Path

from inspectio_exercise.persistence import config
from inspectio_exercise.persistence.interface import PersistencePort
from inspectio_exercise.persistence.local_s3 import LocalS3Provider
from inspectio_exercise.persistence.memory_s3 import MemoryLocalS3Provider


def build_persistence_backend() -> PersistencePort | None:
    """Return the configured backend, or ``None`` if configuration is incomplete or invalid."""
    mode = _resolve_backend_mode()
    if mode == config.BACKEND_LOCAL:
        storage = _normalize_local_s3_storage()
        if storage is None:
            return None
        if storage == config.LOCAL_S3_STORAGE_MEMORY:
            return MemoryLocalS3Provider()
        root = os.environ.get(config.ENV_LOCAL_S3_ROOT)
        if not root:
            return None
        return LocalS3Provider(Path(root))
    if mode == config.BACKEND_AWS:
        if _memory_local_storage_requested():
            return None
        bucket = config.s3_bucket_name()
        if not bucket:
            return None
        from inspectio_exercise.persistence.aws_s3 import AwsS3Provider

        return AwsS3Provider(
            bucket,
            endpoint_url=config.aws_endpoint_url(),
            region_name=config.aws_region_name(),
        )
    return None


def _memory_local_storage_requested() -> bool:
    raw = os.environ.get(config.ENV_LOCAL_S3_STORAGE, "").strip().lower()
    return raw == config.LOCAL_S3_STORAGE_MEMORY


def _normalize_local_s3_storage() -> str | None:
    """Return ``file`` or ``memory`` for local mode; ``None`` if env token is invalid."""
    raw = os.environ.get(config.ENV_LOCAL_S3_STORAGE, "").strip().lower()
    if not raw or raw == config.LOCAL_S3_STORAGE_FILE:
        return config.LOCAL_S3_STORAGE_FILE
    if raw == config.LOCAL_S3_STORAGE_MEMORY:
        return config.LOCAL_S3_STORAGE_MEMORY
    return None


def _normalize_backend_token(raw: str) -> str | None:
    token = raw.strip().lower()
    if token in (config.BACKEND_LOCAL, config.BACKEND_AWS):
        return token
    if token:
        return "__invalid__"
    return None


def _resolve_backend_mode() -> str | None:
    explicit = _normalize_backend_token(os.environ.get(config.ENV_PERSISTENCE_BACKEND, ""))
    if explicit == "__invalid__":
        return None
    if explicit in (config.BACKEND_LOCAL, config.BACKEND_AWS):
        return explicit
    if os.environ.get(config.ENV_LOCAL_S3_ROOT):
        return config.BACKEND_LOCAL
    if config.s3_bucket_name():
        return config.BACKEND_AWS
    return None
