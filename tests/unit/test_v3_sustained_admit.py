from __future__ import annotations

import time
from collections.abc import Sequence
import importlib.util
from pathlib import Path
from typing import Any

import httpx
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "v3_sustained_admit.py"
_SPEC = importlib.util.spec_from_file_location("v3_sustained_admit", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"failed to load script module at {_SCRIPT_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_is_transient_load_error = _MODULE._is_transient_load_error
_sender = _MODULE._sender


class _FakeResponse:
    def __init__(self, *, accepted: int = 0, error: Exception | None = None) -> None:
        self._accepted = accepted
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict[str, int]:
        return {"accepted": self._accepted}


class _FakeClient:
    def __init__(self, outcomes: Sequence[Exception | int]) -> None:
        self._outcomes = list(outcomes)

    async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        if not self._outcomes:
            return _FakeResponse(accepted=0)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            return _FakeResponse(error=outcome)
        return _FakeResponse(accepted=int(outcome))


def _http_500_error() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://inspectio-l1/messages/repeat")
    resp = httpx.Response(status_code=500, request=req)
    return httpx.HTTPStatusError("500", request=req, response=resp)


@pytest.mark.unit
def test_transient_error_classifier() -> None:
    assert _is_transient_load_error(_http_500_error())
    assert _is_transient_load_error(httpx.TransportError("boom"))
    assert _is_transient_load_error(
        RuntimeError("Cannot send a request, as the client has been closed.")
    )
    assert not _is_transient_load_error(ValueError("bad payload"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sender_recovers_from_transient_error() -> None:
    client = _FakeClient([_http_500_error()])
    admitted, transient_errors = await _sender(
        client=client,  # type: ignore[arg-type]
        base="http://inspectio-l1:8080",
        body="x",
        batch=200,
        stop_at=time.monotonic() + 0.001,
    )
    assert admitted >= 0
    assert transient_errors >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sender_raises_on_non_transient_error() -> None:
    client = _FakeClient([ValueError("non-transient")])
    with pytest.raises(ValueError, match="non-transient"):
        await _sender(
            client=client,  # type: ignore[arg-type]
            base="http://inspectio-l1:8080",
            body="x",
            batch=200,
            stop_at=time.monotonic() + 0.01,
        )
