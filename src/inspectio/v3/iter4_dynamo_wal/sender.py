"""SMS transport abstraction (inject real provider in production)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class SmsSendResult:
    __slots__ = ("ok", "detail")

    def __init__(self, *, ok: bool, detail: str | None = None) -> None:
        self.ok = ok
        self.detail = detail


class SmsSender(Protocol):
    async def send(self, message_id: str, payload: dict[str, Any]) -> SmsSendResult:
        """Attempt delivery for one message."""


SmsSendFn = Callable[[str, dict[str, Any]], Awaitable[SmsSendResult]]


class MockSmsSender:
    """Deterministic stub: fails when ``payload[\"fail\"]`` is truthy."""

    async def send(self, message_id: str, payload: dict[str, Any]) -> SmsSendResult:
        if payload.get("fail"):
            return SmsSendResult(ok=False, detail="mock_failure")
        return SmsSendResult(ok=True)
