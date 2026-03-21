"""Shared object-key and list-prefix rules (plans/LOCAL_S3.md §2, §4)."""

from __future__ import annotations


def validate_list_prefix(prefix: str) -> None:
    if not prefix:
        raise ValueError("list_prefix prefix must be non-empty (see LOCAL_S3.md §4.4)")


def validate_max_keys(max_keys: int | None) -> None:
    if max_keys is not None and max_keys < 1:
        raise ValueError("max_keys must be >= 1 when set")


def validate_object_key(key: str) -> None:
    if not key:
        raise ValueError("object key must be non-empty")
    if key.startswith("/"):
        raise ValueError("object key must not start with '/'")
    if any(part == ".." for part in key.split("/")):
        raise ValueError("object key must not contain '..' path segments")
