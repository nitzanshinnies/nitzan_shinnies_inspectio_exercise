"""Request models for the public REST API (plans/REST_API.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    to: str = Field(min_length=1)
    body: str = Field(min_length=1)
