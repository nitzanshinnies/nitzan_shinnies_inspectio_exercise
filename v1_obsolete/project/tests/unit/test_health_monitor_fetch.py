"""Lifecycle fetch edge cases (health_monitor.fetch)."""

from __future__ import annotations

import binascii

import pytest

from inspectio_exercise.health_monitor.fetch import fetch_audit_rows, load_json_objects_under_prefix

pytestmark = pytest.mark.unit


class _OkResponse:
    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_fetch_audit_rows_rejects_non_object_elements() -> None:
    class BadAuditClient:
        async def get(self, path: str, params: dict) -> _OkResponse:
            r = _OkResponse()

            def _json() -> list:
                return [{"messageId": "a"}, "not-an-object"]

            r.json = _json  # type: ignore[method-assign]
            return r

    with pytest.raises(TypeError, match="index 1"):
        await fetch_audit_rows(BadAuditClient(), 10)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_load_json_objects_list_prefix_must_return_list() -> None:
    class NotListPersistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> object:
            return {"keys": "nope"}

        async def get_object(self, key: str) -> bytes:
            return b"{}"

    with pytest.raises(TypeError, match="JSON array"):
        await load_json_objects_under_prefix(
            NotListPersistence(),  # type: ignore[arg-type]
            "state/pending/",
        )


@pytest.mark.asyncio
async def test_load_json_objects_non_dict_list_row() -> None:
    class WeirdRowPersistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list:
            return [42]

        async def get_object(self, key: str) -> bytes:
            return b"{}"

    out, viol, examined = await load_json_objects_under_prefix(
        WeirdRowPersistence(),  # type: ignore[arg-type]
        "state/pending/",
    )
    assert out == []
    assert examined == 0
    assert any(v.kind == "lifecycle_list_entry_invalid" for v in viol)


@pytest.mark.asyncio
async def test_load_json_objects_keyerror_not_404_is_malformed() -> None:
    class WrongKeyErrorPersistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict]:
            return [{"Key": "state/success/2020/01/01/12/x.json"}]

        async def get_object(self, key: str) -> bytes:
            raise KeyError("body_b64")

    out, viol, examined = await load_json_objects_under_prefix(
        WrongKeyErrorPersistence(),  # type: ignore[arg-type]
        "state/success/",
    )
    assert out == []
    assert examined == 1
    assert any(v.kind == "lifecycle_get_response_malformed" for v in viol)


@pytest.mark.asyncio
async def test_load_json_objects_binascii_error_from_get() -> None:
    class BadB64Persistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict]:
            return [{"Key": "state/success/2020/01/01/12/x.json"}]

        async def get_object(self, key: str) -> bytes:
            raise binascii.Error("corrupt base64")

    out, viol, examined = await load_json_objects_under_prefix(
        BadB64Persistence(),  # type: ignore[arg-type]
        "state/success/",
    )
    assert out == []
    assert examined == 1
    assert any(v.kind == "lifecycle_object_body_b64_invalid" for v in viol)


@pytest.mark.asyncio
async def test_load_json_objects_flags_empty_key_in_list_row() -> None:
    class EmptyKeyPersistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict]:
            return [{"Key": ""}]

        async def get_object(self, key: str) -> bytes:
            return b"{}"

    out, viol, examined = await load_json_objects_under_prefix(
        EmptyKeyPersistence(),  # type: ignore[arg-type]
        "state/pending/",
    )
    assert out == []
    assert examined == 0
    assert any(v.kind == "lifecycle_list_entry_invalid" for v in viol)


@pytest.mark.asyncio
async def test_load_json_objects_keyerror_becomes_violation() -> None:
    class MissingObjectPersistence:
        async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict]:
            return [{"Key": "state/success/2020/01/01/12/x.json"}]

        async def get_object(self, key: str) -> bytes:
            raise KeyError(key)

    out, viol, examined = await load_json_objects_under_prefix(
        MissingObjectPersistence(),  # type: ignore[arg-type]
        "state/success/",
    )
    assert out == []
    assert examined == 1
    assert any(v.kind == "lifecycle_object_disappeared" for v in viol)
