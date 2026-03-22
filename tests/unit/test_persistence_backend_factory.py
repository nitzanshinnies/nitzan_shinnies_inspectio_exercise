"""Persistence backend selection (``persistence/backend.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspectio_exercise.persistence.aws_s3 import AwsS3Provider
from inspectio_exercise.persistence.backend import build_persistence_backend
from inspectio_exercise.persistence.local_s3 import LocalS3Provider
from inspectio_exercise.persistence.memory_s3 import MemoryLocalS3Provider


@pytest.mark.unit
def test_factory_implicit_local_when_local_s3_root_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("INSPECTIO_PERSISTENCE_BACKEND", raising=False)
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    backend = build_persistence_backend()
    assert isinstance(backend, LocalS3Provider)


@pytest.mark.unit
def test_factory_explicit_local_requires_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    assert build_persistence_backend() is None


@pytest.mark.unit
def test_factory_explicit_local_memory_without_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "memory")
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    backend = build_persistence_backend()
    assert isinstance(backend, MemoryLocalS3Provider)


@pytest.mark.unit
def test_factory_implicit_local_with_memory_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("INSPECTIO_PERSISTENCE_BACKEND", raising=False)
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "memory")
    backend = build_persistence_backend()
    assert isinstance(backend, MemoryLocalS3Provider)


@pytest.mark.unit
def test_factory_invalid_local_s3_storage_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "noodles")
    assert build_persistence_backend() is None


@pytest.mark.unit
def test_factory_aws_rejects_memory_storage_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "aws")
    monkeypatch.setenv("INSPECTIO_S3_BUCKET", "b")
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "memory")
    assert build_persistence_backend() is None


@pytest.mark.unit
def test_factory_explicit_aws_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "aws")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    assert build_persistence_backend() is None


@pytest.mark.unit
def test_factory_explicit_aws_with_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "aws")
    monkeypatch.setenv("INSPECTIO_S3_BUCKET", "my-bucket")
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    backend = build_persistence_backend()
    assert isinstance(backend, AwsS3Provider)


@pytest.mark.unit
def test_factory_invalid_explicit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "sqlite")
    monkeypatch.setenv("LOCAL_S3_ROOT", "/tmp/x")
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    assert build_persistence_backend() is None


@pytest.mark.unit
def test_factory_explicit_local_overrides_bucket_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_S3_BUCKET", "should-not-use")
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    backend = build_persistence_backend()
    assert isinstance(backend, LocalS3Provider)
