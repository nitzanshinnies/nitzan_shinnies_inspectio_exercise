"""Named timeouts and policy for in-process E2E (plans/TESTS.md §6)."""

from __future__ import annotations

# Wall-clock epoch (seconds) for monkeypatched time — UTC paths derive from this instant.
E2E_BASE_TIME_SEC: float = 1_704_915_200.0

E2E_POLL_INTERVAL_SEC: float = 0.05
E2E_POLL_TIMEOUT_SEC: float = 15.0

E2E_SHARD_COUNT: int = 256
E2E_SHARDS_PER_POD: int = 256
E2E_WORKER_HOSTNAME: str = "worker-0"
E2E_WORKER_TICK_SEC: float = 0.05
