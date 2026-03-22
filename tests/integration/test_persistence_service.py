"""Persistence service HTTP boundary (plans/TESTS.md §5.1).

Exercises ``POST /internal/v1/*`` against a real ``LocalS3Provider`` backend via env;
no direct S3 client in tests.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from inspectio_exercise.persistence.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def persistence_local_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def persistence_memory_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "memory")
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_reads_writes_via_persistence_service_only(
    persistence_local_client: TestClient,
) -> None:
    """Put/get/list/delete only through persistence HTTP (file-backed backend)."""
    client = persistence_local_client
    key = "state/pending/shard-0/msg.json"
    body = b'{"messageId":"abc","status":"pending"}'
    put = client.post(
        "/internal/v1/put-object",
        json={
            "key": key,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "content_type": "application/json",
        },
    )
    assert put.status_code == 200
    assert put.json() == {"status": "ok"}

    got = client.post("/internal/v1/get-object", json={"key": key})
    assert got.status_code == 200
    assert base64.b64decode(got.json()["body_b64"]) == body

    listed = client.post(
        "/internal/v1/list-prefix",
        json={"prefix": "state/pending/shard-0/", "max_keys": None},
    )
    assert listed.status_code == 200
    assert listed.json()["keys"] == [{"Key": key}]

    deleted = client.post("/internal/v1/delete-object", json={"key": key})
    assert deleted.status_code == 200

    missing = client.post("/internal/v1/get-object", json={"key": key})
    assert missing.status_code == 404


def test_list_prefix_http_scoped_to_pending_shard_prefix(
    persistence_local_client: TestClient,
) -> None:
    """Primitive for worker bootstrap: ``list_prefix`` under one shard prefix excludes others."""
    client = persistence_local_client
    k7 = "state/pending/shard-7/a.json"
    k8 = "state/pending/shard-8/b.json"
    for key, payload in (
        (k7, b"1"),
        (k8, b"2"),
    ):
        r = client.post(
            "/internal/v1/put-object",
            json={
                "key": key,
                "body_b64": base64.b64encode(payload).decode("ascii"),
            },
        )
        assert r.status_code == 200

    r = client.post(
        "/internal/v1/list-prefix",
        json={"prefix": "state/pending/shard-7/", "max_keys": None},
    )
    assert r.status_code == 200
    assert r.json()["keys"] == [{"Key": k7}]


def test_put_object_rejects_invalid_key_and_malformed_base64(
    persistence_local_client: TestClient,
) -> None:
    client = persistence_local_client
    bad_key = client.post(
        "/internal/v1/put-object",
        json={
            "key": "a/../b",
            "body_b64": base64.b64encode(b"x").decode("ascii"),
        },
    )
    assert bad_key.status_code == 422

    bad_b64 = client.post(
        "/internal/v1/put-object",
        json={
            "key": "ok.json",
            "body_b64": "not-valid-base64!!!",
        },
    )
    assert bad_b64.status_code == 422


def test_flush_to_disk_writes_snapshot(
    persistence_memory_client: TestClient,
    tmp_path,
) -> None:
    client = persistence_memory_client
    key = "state/pending/shard-0/msg.json"
    body = b'{"messageId":"abc"}'
    put = client.post(
        "/internal/v1/put-object",
        json={
            "key": key,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "content_type": "application/json",
        },
    )
    assert put.status_code == 200

    flush = client.post(
        "/internal/v1/flush-to-disk",
        json={"root": str(tmp_path)},
    )
    assert flush.status_code == 200
    assert flush.json() == {"status": "ok", "root": str(tmp_path)}
    written = tmp_path / key
    assert written.read_bytes() == body


def test_flush_to_disk_uses_local_s3_root_env_when_body_omits_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.setenv("INSPECTIO_LOCAL_S3_STORAGE", "memory")
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    app = create_app()
    key = "k.json"
    payload = b"hello"
    with TestClient(app) as client:
        assert (
            client.post(
                "/internal/v1/put-object",
                json={
                    "key": key,
                    "body_b64": base64.b64encode(payload).decode("ascii"),
                },
            ).status_code
            == 200
        )
        flush = client.post("/internal/v1/flush-to-disk", json={})
        assert flush.status_code == 200
        assert flush.json()["root"] == str(tmp_path)
    assert (tmp_path / key).read_bytes() == payload


def test_flush_to_disk_422_without_root(
    persistence_memory_client: TestClient,
) -> None:
    r = persistence_memory_client.post("/internal/v1/flush-to-disk", json={})
    assert r.status_code == 422


def test_flush_to_disk_501_for_file_backend(
    persistence_local_client: TestClient,
) -> None:
    r = persistence_local_client.post("/internal/v1/flush-to-disk", json={})
    assert r.status_code == 501


def test_ready_and_routes_503_when_backend_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCAL_S3_ROOT", raising=False)
    monkeypatch.delenv("INSPECTIO_PERSISTENCE_BACKEND", raising=False)
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("INSPECTIO_LOCAL_S3_STORAGE", raising=False)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/internal/v1/ready").status_code == 503
        put = client.post(
            "/internal/v1/put-object",
            json={
                "key": "x",
                "body_b64": base64.b64encode(b"y").decode("ascii"),
            },
        )
        assert put.status_code == 503
