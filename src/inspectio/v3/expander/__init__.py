"""L3 expander: bulk queue → sharded send queues (P3)."""

from inspectio.v3.expander.consumer import (
    expand_one_bulk_message,
    receive_and_expand_once,
)
from inspectio.v3.expander.dedupe import ExpandedBulkDedupe
from inspectio.v3.expander.fanout import bulk_to_send_units, chunk_fixed_size
from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.expander.sharding import shard_for_message_id

__all__ = [
    "ExpandedBulkDedupe",
    "ExpansionMetrics",
    "bulk_to_send_units",
    "chunk_fixed_size",
    "expand_one_bulk_message",
    "receive_and_expand_once",
    "shard_for_message_id",
]
