"""In-memory audit ring + stdout JSONL (plans/MOCK_SMS.md §8)."""

from __future__ import annotations

import json
import sys
from collections import deque
from threading import Lock
from typing import Any

from inspectio_exercise.mock_sms import config

_lock = Lock()
_ring: deque[dict[str, Any]] = deque(maxlen=config.AUDIT_LOG_MAX_ENTRIES)


def append_audit_row(row: dict[str, Any]) -> None:
    line = json.dumps({"event": "mock_sms_audit", **row}, separators=(",", ":"))
    print(line, file=sys.stdout, flush=True)
    with _lock:
        _ring.append(row)


def recent_audit_rows(limit: int) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_ring)
    rows.reverse()
    return rows[:limit]
