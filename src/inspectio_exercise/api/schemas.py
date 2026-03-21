"""Request models for the public REST API (plans/REST_API.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from inspectio_exercise.api import config


class MessageCreate(BaseModel):
    """Single message submission — ``to`` defaults for minimal clients.

    Same shape is used as the JSON body for ``POST /messages/repeat`` (template reused ``count`` times).
    """

    to: str = Field(default=config.DEFAULT_MESSAGE_TO, min_length=1)
    body: str = Field(min_length=1)
