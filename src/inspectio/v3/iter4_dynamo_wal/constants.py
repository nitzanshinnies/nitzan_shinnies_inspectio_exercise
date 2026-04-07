"""Named policy values for SMS retry scheduler (Iteration 4).

Event-sourcing pivot: DynamoDB holds mutable hot state; S3 stores append-only JSONL WAL.
"""

from __future__ import annotations

# DynamoDB / throughput
BATCH_WRITE_ITEM_MAX_ITEMS = 25
BATCH_WRITE_RETRY_SLEEP_SEC = 0.05
MAX_POOL_CONNECTIONS = 500

# Retry policy
MAX_SEND_ATTEMPTS = 6
RETRY_DELAY_MS = 500
TICK_INTERVAL_SEC = 0.5

# WAL
WAL_FLUSH_INTERVAL_SEC = 1.0

# Worker: merge DynamoDB into heap between ticks (new rows from API / other writers).
DEFAULT_RECONCILE_INTERVAL_MS = 250

# Defaults when env not set
DEFAULT_TOTAL_SHARDS = 16
DEFAULT_TOTAL_WORKERS = 4

# Status strings (DynamoDB)
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"

# GSI
GSI_SCHEDULING_INDEX_DEFAULT_NAME = "SchedulingIndex"
