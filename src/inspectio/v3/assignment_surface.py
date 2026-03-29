"""PDF-shaped `Message` + `send` / `try_send` boundary. Master plan §4.6; scheduler uses try_send bool."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """In-process message passed to send/try_send (assignment API shape; fields are adapters)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1)
    body: str = Field(min_length=1)


def try_send(message: Message) -> bool:
    """Provider attempt; scheduler branches on the bool. Stub until P4 injects a real implementation."""
    raise NotImplementedError(
        "Default try_send is unset; inject a callable or subclass for tests and workers.",
    )


def send(message: Message) -> None:
    """Thin void wrapper: delegates to try_send and discards the bool (PDF-compatible)."""
    _ = try_send(message)
