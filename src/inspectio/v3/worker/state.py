"""In-memory active unit (per SQS receipt) for the send scheduler."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ActiveSendUnit:
    message_id: str
    body: str
    received_at_ms: int
    batch_correlation_id: str
    trace_id: str
    shard: int
    receipt_handle: str
    completed_try_sends: int = 0
