"""Assignment PDF **given API** — names preserved for review (Java-style on a Protocol).

Python services map these hooks as follows:

- ``send(Message)`` → HTTP ``POST`` to mock SMS (``worker.mock_sms_client.post_mock_send``).
- ``newMessage(Message)`` → durable pending put (``api.use_cases.submit_message``) plus
  best-effort ``request_immediate_activation`` (worker ``activate_pending_now``) for attempt #1
  at 0s; otherwise the 500ms ``wakeup`` tick picks up due work.
- ``wakeup()`` → ``WorkerRuntime.run_tick`` driven by ``run_forever_with_tick_interval``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AssignmentSchedulerHooks(Protocol):
    """Exercise scheduler surface from the architect brief (method spellings unchanged)."""

    def send(self, message: object) -> bool:
        """Return True when the provider accepts the SMS."""
        ...

    def newMessage(self, message: object) -> None:
        """Arrival hook: persist and run attempt #1 immediately."""
        ...

    def wakeup(self) -> None:
        """Scheduler tick (~500ms): process due retries."""
        ...
