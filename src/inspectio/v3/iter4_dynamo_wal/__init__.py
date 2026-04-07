"""Iteration 4: DynamoDB hot state + S3 append-only WAL (event-sourced recovery).

- **DynamoDB** ``sms_messages``: PK ``messageId``; GSI ``SchedulingIndex`` (``shard_id``, ``nextDueAt``).
- **S3** ``wal/<writer_id>/<epoch_ms>.jsonl``: JSON Lines, one PUT per flush interval (no object edits).
- **API** ``POST /messages``: idempotent put, immediate ``send`` attempt 1, WAL events, retry +500ms on failure.
- **Worker** (StatefulSet): ``HOSTNAME`` → shard ownership; 500ms monotonic tick; heap + ``asyncio.gather`` sends;
  recovery loads pending rows from the GSI into the heap at boot.

This package is **parallel** to the default v3 SQS pipeline until explicitly wired to L2.

Public helpers: ``batch_put_messages``, ``botocore_high_throughput_config``.
"""

from inspectio.v3.iter4_dynamo_wal.aws_clients import botocore_high_throughput_config
from inspectio.v3.iter4_dynamo_wal.batch_write import batch_put_messages

__all__ = [
    "batch_put_messages",
    "botocore_high_throughput_config",
]
