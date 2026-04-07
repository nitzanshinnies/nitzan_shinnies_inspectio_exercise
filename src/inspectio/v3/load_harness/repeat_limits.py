"""Limits for ``POST /messages/repeat`` (must stay aligned with L2 ``Query(le=...)``)."""

from __future__ import annotations

# Keep in sync with ``src/inspectio/v3/l2/routes.py`` post_messages_repeat count bound.
L2_REPEAT_COUNT_MAX = 100_000


def validated_repeat_count(n: int) -> int:
    """Return ``n`` if it is a legal repeat count; raise ``ValueError`` otherwise."""
    if n < 1:
        msg = "count must be >= 1"
        raise ValueError(msg)
    if n > L2_REPEAT_COUNT_MAX:
        msg = f"count must be <= {L2_REPEAT_COUNT_MAX} (L2 /messages/repeat)"
        raise ValueError(msg)
    return n
