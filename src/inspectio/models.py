"""Pure data contracts for ingest/retry state (§4.1–§4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RetryStatus = Literal["pending", "success", "failed"]

MAX_ATTEMPT_COUNT = 6
MIN_ATTEMPT_COUNT = 0
MIN_PENDING_ATTEMPT_COUNT = 0
MAX_PENDING_ATTEMPT_COUNT = 5
MIN_SUCCESS_ATTEMPT_COUNT = 1
MAX_SUCCESS_ATTEMPT_COUNT = 6
FAILED_ATTEMPT_COUNT = 6


@dataclass(frozen=True, slots=True)
class Message:
    """Payload required to invoke SMS send (§19)."""

    message_id: str
    to: str
    body: str


@dataclass(frozen=True, slots=True)
class RetryStateV1:
    """Retry state contract for scheduler runtime/recovery (§4.2)."""

    message_id: str
    attempt_count: int
    next_due_at_ms: int
    status: RetryStatus
    last_error: str | None
    payload: dict[str, Any]
    updated_at_ms: int

    def __post_init__(self) -> None:
        if (
            self.attempt_count < MIN_ATTEMPT_COUNT
            or self.attempt_count > MAX_ATTEMPT_COUNT
        ):
            msg = (
                "attempt_count must be within "
                f"[{MIN_ATTEMPT_COUNT}, {MAX_ATTEMPT_COUNT}]"
            )
            raise ValueError(msg)

        if self.status == "pending":
            if self.attempt_count < MIN_PENDING_ATTEMPT_COUNT:
                msg = f"pending attempt_count must be >= {MIN_PENDING_ATTEMPT_COUNT}"
                raise ValueError(msg)
            if self.attempt_count > MAX_PENDING_ATTEMPT_COUNT:
                msg = f"pending attempt_count must be <= {MAX_PENDING_ATTEMPT_COUNT}"
                raise ValueError(msg)
            return

        if self.status == "success":
            if self.attempt_count < MIN_SUCCESS_ATTEMPT_COUNT:
                msg = f"success attempt_count must be >= {MIN_SUCCESS_ATTEMPT_COUNT}"
                raise ValueError(msg)
            if self.attempt_count > MAX_SUCCESS_ATTEMPT_COUNT:
                msg = f"success attempt_count must be <= {MAX_SUCCESS_ATTEMPT_COUNT}"
                raise ValueError(msg)
            return

        if self.attempt_count != FAILED_ATTEMPT_COUNT:
            msg = f"failed attempt_count must be == {FAILED_ATTEMPT_COUNT}"
            raise ValueError(msg)
