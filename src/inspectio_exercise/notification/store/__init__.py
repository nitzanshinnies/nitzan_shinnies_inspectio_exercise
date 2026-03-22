"""Pluggable hot outcomes storage for the notification service."""

from inspectio_exercise.notification.store.factory import create_outcomes_store
from inspectio_exercise.notification.store.interface import OutcomesHotStore, OutcomesStoreError
from inspectio_exercise.notification.store.memory_store import MemoryOutcomesHotStore
from inspectio_exercise.notification.store.redis_store import RedisOutcomesHotStore

__all__ = [
    "MemoryOutcomesHotStore",
    "OutcomesHotStore",
    "OutcomesStoreError",
    "RedisOutcomesHotStore",
    "create_outcomes_store",
]
