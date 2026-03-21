"""Request models for the public REST API (plans/REST_API.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from inspectio_exercise.api import config


class MessageCreate(BaseModel):
    """Single message submission — ``to`` defaults for minimal clients."""

    to: str = Field(default=config.DEFAULT_MESSAGE_TO, min_length=1)
    body: str = Field(min_length=1)


class RepeatMessagesCreate(BaseModel):
    """Load-test batch — JSON body includes ``count`` and optional ``to`` / ``body``."""

    count: int = Field(ge=1, le=config.REPEAT_COUNT_MAX)
    to: str = Field(default=config.DEFAULT_MESSAGE_TO, min_length=1)
    body: str = Field(default=config.DEFAULT_REPEAT_MESSAGE_BODY, min_length=1)
