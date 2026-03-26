"""P7 outcomes store tests (TC-OUT-001/002 core semantics)."""

from __future__ import annotations

import json

import pytest

from inspectio.notification.outcomes_store import (
    RedisOutcomesStore,
    terminal_key_for_status,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}

    async def lpush(self, key: str, value: str) -> int:
        self.data.setdefault(key, [])
        self.data[key].insert(0, value)
        return len(self.data[key])

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        values = self.data.get(key, [])
        self.data[key] = values[start : end + 1]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.data.get(key, [])
        return values[start : end + 1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_out_001_lpush_ltrim_and_newest_first() -> None:
    store = RedisOutcomesStore(redis_client=_FakeRedis(), max_items=100)
    await store.add_terminal(
        {
            "messageId": "m-1",
            "terminalStatus": "success",
            "attemptCount": 1,
            "finalTimestampMs": 1000,
            "reason": None,
        }
    )
    await store.add_terminal(
        {
            "messageId": "m-2",
            "terminalStatus": "success",
            "attemptCount": 2,
            "finalTimestampMs": 2000,
            "reason": None,
        }
    )

    items = await store.get_success(limit=10)
    assert [item["messageId"] for item in items] == ["m-2", "m-1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_out_002_trims_to_max_items_cap() -> None:
    fake = _FakeRedis()
    store = RedisOutcomesStore(redis_client=fake, max_items=100)
    for idx in range(150):
        await store.add_terminal(
            {
                "messageId": f"m-{idx}",
                "terminalStatus": "success",
                "attemptCount": 1,
                "finalTimestampMs": 1000 + idx,
                "reason": None,
            }
        )

    raw = fake.data[terminal_key_for_status("success")]
    assert len(raw) == 100
    # newest first
    first = json.loads(raw[0])
    assert first["messageId"] == "m-149"


@pytest.mark.unit
def test_terminal_key_for_status_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        terminal_key_for_status("weird")
