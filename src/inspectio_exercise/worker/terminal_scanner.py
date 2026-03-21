"""Scan recent UTC hourly prefixes for an existing terminal row (idempotency)."""

from __future__ import annotations

import json
import logging
from typing import Any

from inspectio_exercise.worker.retrying_persistence import RetryingPersistence
from inspectio_exercise.worker.terminal_lookup import (
    key_matches_message_terminal,
    terminal_prefixes_for_lookback,
)

logger = logging.getLogger(__name__)


class TerminalScanner:
    def __init__(self, persistence: RetryingPersistence, lookback_hours: int) -> None:
        self._lookback_hours = lookback_hours
        self._persistence = persistence

    async def find_existing(
        self, message_id: str, now_ms: int
    ) -> tuple[str, str, dict[str, Any]] | None:
        for tree_root, outcome in (("state/success", "success"), ("state/failed", "failed")):
            for scan_prefix in terminal_prefixes_for_lookback(
                lookback_hours=self._lookback_hours,
                now_ms=now_ms,
                tree_root=tree_root,
            ):
                try:
                    rows = await self._persistence.list_prefix(scan_prefix)
                except Exception:
                    logger.exception("terminal scan list_prefix failed prefix=%s", scan_prefix)
                    continue
                for row in rows:
                    tkey = row["Key"]
                    if not key_matches_message_terminal(tkey, message_id):
                        continue
                    try:
                        raw = await self._persistence.get_object(tkey)
                    except KeyError:
                        continue
                    except Exception:
                        logger.exception("terminal scan get_object failed key=%s", tkey)
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("messageId") != message_id:
                        continue
                    if data.get("status") != outcome:
                        continue
                    return outcome, tkey, data
        return None
