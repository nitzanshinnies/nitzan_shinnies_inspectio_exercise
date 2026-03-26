"""Compatibility module: ingest producer types and SQS FIFO implementation."""

from __future__ import annotations

from inspectio.ingest.ingest_producer import (
    IngestBufferOverflowError,
    IngestProducer,
    IngestPutInput,
    IngestPutResult,
    IngestUnavailableError,
    partition_key_for_shard,
)
from inspectio.ingest.sqs_fifo_producer import SqsFifoIngestProducer

__all__ = [
    "IngestBufferOverflowError",
    "IngestProducer",
    "IngestPutInput",
    "IngestPutResult",
    "IngestUnavailableError",
    "SqsFifoIngestProducer",
    "partition_key_for_shard",
]
