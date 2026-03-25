"""Batch persistence writes (key + body + optional content type)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectWrite:
    """One S3-style object to persist (same semantics as ``put_object``)."""

    key: str
    body: bytes
    content_type: str = "application/json"
