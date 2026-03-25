"""Redis keys / stream names for optional pending-ingest buffering (API → S3 flusher)."""

from __future__ import annotations

# Consumer group for the persistence flusher (API process).
PENDING_STREAM_CONSUMER_GROUP: str = "inspectio-persist-flush"

# Stream field names (binary-safe values).
PENDING_STREAM_FIELD_BODY: str = "body"
PENDING_STREAM_FIELD_KEY: str = "pending_key"

# Single stream; entries reference ``pending_key`` and carry ``body`` bytes.
PENDING_STREAM_KEY: str = "inspectio:pending:ingest"

# ``GET``/``SET`` staging prefix before S3 flush (worker read-through).
PENDING_STAGE_KEY_PREFIX: str = "inspectio:pending:stage:"
