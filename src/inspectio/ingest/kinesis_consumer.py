"""Deprecated module name — use `inspectio.ingest.ingest_consumer` instead."""

from __future__ import annotations

from inspectio.ingest.ingest_consumer import (
    CheckpointStore,
    IngestConsumer,
    IngestRawRecord,
    JournalWriter,
    KinesisIngestConsumer,
    KinesisRawRecord,
    S3CheckpointStore,
    partition_key_for_shard,
)

__all__ = [
    "CheckpointStore",
    "IngestConsumer",
    "IngestRawRecord",
    "JournalWriter",
    "KinesisIngestConsumer",
    "KinesisRawRecord",
    "S3CheckpointStore",
    "partition_key_for_shard",
]
