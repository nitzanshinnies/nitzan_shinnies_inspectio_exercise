"""Unit fixtures for persistence replay tests (P12.0)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class DeterministicClock:
    now: int = 1_700_000_000_000

    def now_ms(self) -> int:
        return self.now

    def advance_ms(self, delta_ms: int) -> int:
        self.now += delta_ms
        return self.now


class FakePersistenceTransport:
    """Deterministic fake producer/consumer transport used by replay tests."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self._events.append(event)

    def drain_in_order(self) -> list[dict[str, Any]]:
        return list(self._events)

    def drain_unordered(self, *, seed: int = 7) -> list[dict[str, Any]]:
        out = list(self._events)
        rnd = random.Random(seed)
        rnd.shuffle(out)
        return out


@pytest.fixture
def deterministic_clock() -> DeterministicClock:
    return DeterministicClock()


@pytest.fixture
def fake_persistence_transport() -> FakePersistenceTransport:
    return FakePersistenceTransport()
