"""HTTP JSON shapes for the persistence microservice."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from inspectio_exercise.persistence.key_policy import (
    validate_list_prefix,
    validate_max_keys,
    validate_object_key,
)


class DeleteObjectRequest(BaseModel):
    key: str

    @field_validator("key")
    @classmethod
    def key_shape(cls, value: str) -> str:
        validate_object_key(value)
        return value


class GetObjectRequest(BaseModel):
    key: str

    @field_validator("key")
    @classmethod
    def key_shape(cls, value: str) -> str:
        validate_object_key(value)
        return value


class GetObjectResponse(BaseModel):
    body_b64: str


class ListPrefixRequest(BaseModel):
    prefix: str
    max_keys: int | None = None

    @field_validator("prefix")
    @classmethod
    def prefix_shape(cls, value: str) -> str:
        validate_list_prefix(value)
        return value

    @field_validator("max_keys")
    @classmethod
    def max_keys_shape(cls, value: int | None) -> int | None:
        validate_max_keys(value)
        return value


class ListPrefixResponse(BaseModel):
    keys: list[dict[str, Any]]


class PutObjectRequest(BaseModel):
    key: str
    body_b64: str = Field(..., description="Standard base64-encoded object bytes")
    content_type: str = "application/json"

    @field_validator("key")
    @classmethod
    def key_shape(cls, value: str) -> str:
        validate_object_key(value)
        return value
