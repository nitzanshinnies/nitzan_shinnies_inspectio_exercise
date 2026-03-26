"""Domain models (§4, §25). Extend per IMPLEMENTATION_PHASES.md P1."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    """Payload required to invoke SMS send (§19)."""

    message_id: str
    to: str
    body: str
