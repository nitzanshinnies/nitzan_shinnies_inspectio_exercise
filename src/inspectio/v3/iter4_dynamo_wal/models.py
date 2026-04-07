"""HTTP and internal payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NewMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: str = Field(..., min_length=1, alias="messageId")
    payload: dict[str, Any] = Field(default_factory=dict)


class NewMessageResponse(BaseModel):
    accepted: bool
    duplicate: bool = False
    detail: str | None = None
