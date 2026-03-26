"""P6 scheduler_surface contract smoke tests (§25)."""

from __future__ import annotations

import pytest

import inspectio.scheduler_surface as scheduler_surface
from inspectio.models import Message


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send_once(self, message: Message, *, attempt_index: int) -> bool:
        _ = message
        _ = attempt_index
        self.calls.append("send")
        return True

    async def new_message(self, message: Message) -> None:
        _ = message
        self.calls.append("new_message")

    async def wakeup(self) -> None:
        self.calls.append("wakeup")


@pytest.mark.unit
def test_surface_exports_send_new_message_wakeup() -> None:
    fake = _FakeRuntime()
    original = scheduler_surface._runtime
    scheduler_surface._runtime = fake
    try:
        msg = Message(message_id="m-1", to="+1", body="x")
        assert scheduler_surface.send(msg)
        scheduler_surface.new_message(msg)
        scheduler_surface.wakeup()
        assert fake.calls == ["send", "new_message", "wakeup"]
    finally:
        scheduler_surface._runtime = original
