"""Pending object key parsing and JSON validation for worker ingest."""

from __future__ import annotations

from typing import Any


def is_valid_pending_row(message_id: str, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("messageId") != message_id:
        return False
    if data.get("status") != "pending":
        return False
    ac = data.get("attemptCount")
    if not isinstance(ac, int) or ac < 0 or ac > 6:
        return False
    nd = data.get("nextDueAt")
    if not isinstance(nd, int):
        return False
    pl = data.get("payload")
    if not isinstance(pl, dict):
        return False
    return isinstance(pl.get("to"), str) and isinstance(pl.get("body"), str)


def message_id_from_pending_key(key: str) -> str | None:
    base = key.rsplit("/", maxsplit=1)[-1]
    if not base.endswith(".json") or len(base) < 6:
        return None
    return base[:-5]
