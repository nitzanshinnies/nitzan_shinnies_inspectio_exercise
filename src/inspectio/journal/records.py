"""`JournalRecordV1` NDJSON line codec and gzip segment parsing (§18.1–18.2)."""

from __future__ import annotations

import gzip
import json
import re
from typing import Any, Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, ValidationError

JournalRecordType = Literal[
    "INGEST_APPLIED",
    "DISPATCH_SCHEDULED",
    "SEND_ATTEMPTED",
    "SEND_RESULT",
    "NEXT_DUE",
    "TERMINAL",
]

_REASONS = frozenset({"immediate", "tick", "replay"})
_BODY_HASH = re.compile(r"^[0-9a-f]{64}$")


class JournalError(Exception):
    """Base class for journal codec errors."""


class JournalDecodeError(JournalError):
    """Invalid JSON line or unsupported envelope (`v`)."""


class JournalValidationError(JournalError):
    """Parsed line failed §18.2 payload rules."""


class JournalRecordIndexError(JournalError):
    """`recordIndex` is not strictly greater than the shard high-water mark."""


class JournalRecordV1(BaseModel):
    """One NDJSON line in a gzip journal segment (§18.2)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    v: Literal[1]
    type: JournalRecordType
    shard_id: int = Field(alias="shardId")
    message_id: str = Field(alias="messageId")
    ts_ms: int = Field(alias="tsMs")
    record_index: int = Field(alias="recordIndex")
    payload: dict[str, Any]


def _is_int(x: Any) -> TypeGuard[int]:
    return isinstance(x, int) and not isinstance(x, bool)


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in payload:
            raise JournalValidationError(f"missing payload key {key!r}")


def _forbid_extra_keys(payload: dict[str, Any], allowed: frozenset[str]) -> None:
    extra = set(payload.keys()) - allowed
    if extra:
        names = ", ".join(sorted(extra))
        raise JournalValidationError(f"unexpected payload keys: {names}")


def _validate_ingest_applied(payload: dict[str, Any]) -> None:
    allowed = frozenset({"receivedAtMs", "idempotencyKey", "bodyHash"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("receivedAtMs", "idempotencyKey", "bodyHash"))
    if not _is_int(payload["receivedAtMs"]):
        raise JournalValidationError("receivedAtMs must be int")
    if not isinstance(payload["idempotencyKey"], str):
        raise JournalValidationError("idempotencyKey must be str")
    bh = payload["bodyHash"]
    if not isinstance(bh, str) or not _BODY_HASH.fullmatch(bh):
        raise JournalValidationError("bodyHash must be 64 lowercase hex chars")


def _validate_dispatch_scheduled(payload: dict[str, Any]) -> None:
    allowed = frozenset({"reason"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("reason",))
    reason = payload["reason"]
    if reason not in _REASONS:
        raise JournalValidationError("reason must be immediate|tick|replay")


def _validate_send_attempted(payload: dict[str, Any]) -> None:
    allowed = frozenset({"attemptIndex"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("attemptIndex",))
    ai = payload["attemptIndex"]
    if not _is_int(ai) or ai < 0 or ai > 5:
        raise JournalValidationError("attemptIndex must be int in 0..5")


def _validate_send_result(payload: dict[str, Any]) -> None:
    allowed = frozenset({"attemptIndex", "ok", "httpStatus", "errorClass"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("attemptIndex", "ok", "httpStatus", "errorClass"))
    ai = payload["attemptIndex"]
    if not _is_int(ai) or ai < 0 or ai > 5:
        raise JournalValidationError("attemptIndex must be int in 0..5")
    if not isinstance(payload["ok"], bool):
        raise JournalValidationError("ok must be bool")
    hs = payload["httpStatus"]
    if hs is not None and not _is_int(hs):
        raise JournalValidationError("httpStatus must be int or null")
    ec = payload["errorClass"]
    if ec is not None and not isinstance(ec, str):
        raise JournalValidationError("errorClass must be str or null")


def _validate_next_due(payload: dict[str, Any]) -> None:
    allowed = frozenset({"attemptCount", "nextDueAtMs"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("attemptCount", "nextDueAtMs"))
    ac = payload["attemptCount"]
    if not _is_int(ac) or ac < 1 or ac > 5:
        raise JournalValidationError("attemptCount must be int in 1..5")
    if not _is_int(payload["nextDueAtMs"]):
        raise JournalValidationError("nextDueAtMs must be int")


def _validate_terminal(payload: dict[str, Any]) -> None:
    allowed = frozenset({"status", "attemptCount", "reason"})
    _forbid_extra_keys(payload, allowed)
    _require_keys(payload, ("status", "attemptCount"))
    status = payload["status"]
    if status not in ("success", "failed"):
        raise JournalValidationError("status must be success or failed")
    ac = payload["attemptCount"]
    if not _is_int(ac) or ac < 1 or ac > 6:
        raise JournalValidationError("attemptCount must be int in 1..6")
    if status == "failed":
        if "reason" not in payload or not isinstance(payload["reason"], str):
            raise JournalValidationError("reason is required when status is failed")
    elif "reason" in payload:
        raise JournalValidationError("reason must be absent when status is success")


def validate_payload_for_type(
    record_type: JournalRecordType, payload: dict[str, Any]
) -> None:
    """Validate §18.2 payload keys and types for `record_type`."""
    if record_type == "INGEST_APPLIED":
        _validate_ingest_applied(payload)
    elif record_type == "DISPATCH_SCHEDULED":
        _validate_dispatch_scheduled(payload)
    elif record_type == "SEND_ATTEMPTED":
        _validate_send_attempted(payload)
    elif record_type == "SEND_RESULT":
        _validate_send_result(payload)
    elif record_type == "NEXT_DUE":
        _validate_next_due(payload)
    else:
        _validate_terminal(payload)


def decode_line(line: str) -> JournalRecordV1:
    """Parse one UTF-8 JSON object; enforce `v` and §18.2 payload rules."""
    stripped = line.strip()
    if not stripped:
        raise JournalDecodeError("empty journal line")
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise JournalDecodeError(str(exc)) from exc
    if not isinstance(obj, dict):
        raise JournalDecodeError("journal line must be a JSON object")
    if obj.get("v") != 1:
        raise JournalDecodeError("v must be 1")
    try:
        record = JournalRecordV1.model_validate(obj)
    except ValidationError as exc:
        raise JournalValidationError(str(exc)) from exc
    validate_payload_for_type(record.type, record.payload)
    return record


def encode_line(record: JournalRecordV1) -> str:
    """Serialize to compact JSON with sorted keys (deterministic NDJSON line)."""
    validate_payload_for_type(record.type, record.payload)
    data = record.model_dump(mode="json", by_alias=True)
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def validate_monotonic_record_index(
    shard_last_record_index: int | None,
    record: JournalRecordV1,
) -> None:
    """Reject appends that are not strictly greater than the shard high-water mark."""
    if shard_last_record_index is None:
        return
    if record.record_index <= shard_last_record_index:
        raise JournalRecordIndexError(
            "recordIndex must be strictly increasing per shard "
            f"(got {record.record_index}, last {shard_last_record_index})"
        )


def parse_gzip_ndjson_segment(segment: bytes) -> list[JournalRecordV1]:
    """Decompress a gzip blob and parse NDJSON lines (§18.1)."""
    try:
        text = gzip.decompress(segment).decode("utf-8")
    except OSError as exc:
        raise JournalDecodeError(f"invalid gzip segment: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise JournalDecodeError(f"invalid UTF-8 in journal segment: {exc}") from exc
    out: list[JournalRecordV1] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        out.append(decode_line(raw_line))
    return out
