"""
Assignment-mandated surface (§25). Implement per IMPLEMENTATION_PHASES.md P6.

PDF mapping (README must duplicate):
  send          <- boolean send(Message)
  new_message   <- void newMessage(Message)
  wakeup        <- void wakeup()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspectio.models import Message


def send(message: Message) -> bool:
    raise NotImplementedError("§25 send — implement per plans/")


def new_message(message: Message) -> None:
    raise NotImplementedError("§25 new_message")


def wakeup() -> None:
    raise NotImplementedError("§25 wakeup")
