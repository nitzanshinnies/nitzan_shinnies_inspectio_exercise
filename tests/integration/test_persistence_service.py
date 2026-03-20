"""Persistence service boundary (TESTS.md §5.1)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from inspectio_exercise.persistence.app import create_app

pytestmark = pytest.mark.integration


def test_persistence_readiness_not_ready_until_backend_wired() -> None:
    """GET /internal/v1/ready returns 503 until S3/backend is implemented (skeleton)."""
    client = TestClient(create_app())
    response = client.get("/internal/v1/ready")
    assert response.status_code == 503


def test_persistence_put_object_stub_returns_501() -> None:
    """HTTP surface exists; handler not implemented yet."""
    client = TestClient(create_app())
    response = client.post("/internal/v1/put-object")
    assert response.status_code == 501


@pytest.mark.skip(reason="TESTS.md §5.1: moto/LocalStack + real handlers; spy no ad-hoc S3 in app code")
def test_reads_writes_via_persistence_service() -> None:
    """All I/O through persistence service; no ad-hoc S3 client in code under test."""


@pytest.mark.skip(reason="TESTS.md §5.1: worker bootstrap + owned shard list_prefix")
def test_bootstrap_lists_only_owned_pending_prefixes() -> None:
    """List/get in bootstrap only target owned state/pending/shard-<id>/ prefixes."""
