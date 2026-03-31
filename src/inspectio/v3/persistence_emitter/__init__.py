"""Persistence event emitter interfaces (P12.1)."""

from inspectio.v3.persistence_emitter.noop import NoopPersistenceEventEmitter
from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter

__all__ = ["NoopPersistenceEventEmitter", "PersistenceEventEmitter"]
