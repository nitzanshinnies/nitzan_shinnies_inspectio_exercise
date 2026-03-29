"""In-process dedupe for expanded bulk SQS messages (single expander replica; P3).

After a bulk is fully published to send queues, we record its SQS ``MessageId``. If the
same message is redelivered before ``DeleteMessage`` completes, we skip re-publish and only
delete (see P3 pitfalls: partial failure → visibility retry; crash after publish → dedupe).
"""

from __future__ import annotations

from collections import OrderedDict


class ExpandedBulkDedupe:
    """LRU of SQS message IDs that finished fan-out (publish OK, before or after delete)."""

    def __init__(self, max_size: int = 10_000) -> None:
        self._max_size = max_size
        self._order: OrderedDict[str, None] = OrderedDict()

    def is_expanded(self, sqs_message_id: str) -> bool:
        return sqs_message_id in self._order

    def mark_expanded(self, sqs_message_id: str) -> None:
        if sqs_message_id in self._order:
            self._order.move_to_end(sqs_message_id)
        else:
            self._order[sqs_message_id] = None
            while len(self._order) > self._max_size:
                self._order.popitem(last=False)
