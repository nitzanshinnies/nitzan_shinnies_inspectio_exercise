"""HTTP request/response shapes aligned with plans/openapi.yaml (v3 L2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PostMessageRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str = Field(min_length=1)
    to: str | None = None

    @field_validator("body")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("body must be non-empty after trim")
        return trimmed
