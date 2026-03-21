"""HTTP JSON shapes for the persistence microservice."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeleteObjectRequest(BaseModel):
    key: str


class GetObjectRequest(BaseModel):
    key: str


class GetObjectResponse(BaseModel):
    body_b64: str


class ListPrefixRequest(BaseModel):
    prefix: str
    max_keys: int | None = None


class ListPrefixResponse(BaseModel):
    keys: list[dict[str, Any]]


class PutObjectRequest(BaseModel):
    key: str
    body_b64: str = Field(..., description="Standard base64-encoded object bytes")
    content_type: str = "application/json"
