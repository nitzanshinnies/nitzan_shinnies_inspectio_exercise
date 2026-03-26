"""Assignment scheduler surface (§25): send, new_message, wakeup."""

from __future__ import annotations

import asyncio
import time

from inspectio.models import Message
from inspectio.settings import get_settings
from inspectio.sms.client import SmsClient
from inspectio.worker.runtime import InMemorySchedulerRuntime


def _now_ms() -> int:
    return int(time.time() * 1000)


_runtime = InMemorySchedulerRuntime(
    now_ms=_now_ms,
    sms_sender=SmsClient(
        base_url=get_settings().inspectio_sms_url,
        timeout_sec=get_settings().inspectio_sms_http_timeout_sec,
    ),
)


def send(message: Message) -> bool:
    """PDF `send(Message)` mapping; calls SMS adapter once with attemptIndex=0."""
    return asyncio.run(_runtime.send_once(message, attempt_index=0))


def new_message(message: Message) -> None:
    """PDF `newMessage(Message)` mapping; immediate first-attempt path."""
    asyncio.run(_runtime.new_message(message))


def wakeup() -> None:
    """PDF `wakeup()` mapping; dispatches all due retries."""
    asyncio.run(_runtime.wakeup())
