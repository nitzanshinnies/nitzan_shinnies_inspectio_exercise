"""`MessageIngestedV1` ingest stream record (§17.2, §29.5 `bodyHash`)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_BODY_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def body_hash_for_text(body: str) -> str:
    """Lowercase hex SHA-256 of UTF-8 bytes of `body` (§29.5)."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class MessageIngestPayload(BaseModel):
    """`payload` object inside `MessageIngestedV1` (§17.2)."""

    model_config = ConfigDict(frozen=True)

    body: str
    to: str | None = None


class MessageIngestedV1(BaseModel):
    """UTF-8 JSON record written to the ingest stream (§17.2) plus `bodyHash` (§29.5)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema: Literal["MessageIngestedV1"] = "MessageIngestedV1"
    message_id: str = Field(alias="messageId")
    payload: MessageIngestPayload
    received_at_ms: int = Field(alias="receivedAtMs")
    shard_id: int = Field(alias="shardId")
    idempotency_key: str = Field(alias="idempotencyKey")
    body_hash: str = Field(alias="bodyHash")

    @model_validator(mode="before")
    @classmethod
    def _inject_or_check_body_hash(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = data.get("payload")
        body: str | None = None
        if isinstance(payload, dict):
            raw = payload.get("body")
            if raw is not None:
                body = str(raw)
        elif isinstance(payload, MessageIngestPayload):
            body = payload.body
        if body is None:
            return data
        expected = body_hash_for_text(body)
        existing = data.get("bodyHash", data.get("body_hash"))
        if existing is None:
            return {**data, "bodyHash": expected}
        if str(existing).lower() != expected:
            raise ValueError("bodyHash does not match payload.body")
        return {**data, "bodyHash": expected}

    @model_validator(mode="after")
    def _normalize_body_hash_format(self) -> Self:
        if not _BODY_HASH_PATTERN.fullmatch(self.body_hash):
            raise ValueError("bodyHash must be 64 lowercase hex chars")
        return self

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> MessageIngestedV1:
        return cls.model_validate(data)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
