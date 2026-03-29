"""P0: PDF-shaped assignment surface (master plan §4.6; P0_PACKAGE_AND_SURFACE)."""

from __future__ import annotations

import pytest

from inspectio.v3.assignment_surface import Message, send, try_send


@pytest.mark.unit
def test_try_send_stub_raises_not_implemented() -> None:
    msg = Message(message_id="m1", body="b")
    with pytest.raises(NotImplementedError):
        try_send(msg)


@pytest.mark.unit
def test_send_void_wrapper_delegates_try_send(monkeypatch: pytest.MonkeyPatch) -> None:
    msg = Message(message_id="m1", body="b")
    seen: list[Message] = []

    def fake_try_send(m: Message) -> bool:
        seen.append(m)
        return False

    monkeypatch.setattr("inspectio.v3.assignment_surface.try_send", fake_try_send)
    send(msg)
    assert seen == [msg]
