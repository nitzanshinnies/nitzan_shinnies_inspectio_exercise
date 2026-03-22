"""Outbound reads: mock SMS audit + persistence lifecycle objects."""

from __future__ import annotations

import binascii
import json
import logging
from typing import Any

import httpx

from inspectio_exercise.health_monitor.reconcile import Violation
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient

logger = logging.getLogger(__name__)


async def fetch_audit_rows(mock_sms: httpx.AsyncClient, limit: int) -> list[dict[str, Any]]:
    """GET /audit/sends?limit=… (MOCK_SMS.md 8.2).

    Raises ``httpx.HTTPStatusError`` on non-success HTTP (including 404 when
    ``EXPOSE_AUDIT_ENDPOINT`` is false on the mock).

    Raises ``TypeError`` if the JSON payload is not an array of objects (each row must be a dict).
    """
    response = await mock_sms.get("/audit/sends", params={"limit": limit})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("mock audit response must be a JSON array")
    for i, row in enumerate(payload):
        if not isinstance(row, dict):
            raise TypeError(
                f"mock audit row at index {i} must be a JSON object, got {type(row).__name__}"
            )
    return payload


async def load_json_objects_under_prefix(
    persistence: PersistenceHttpClient,
    prefix: str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[Violation], int]:
    """List keys under prefix and fetch each ``*.json`` body (read-only).

    Malformed objects are reported as violations (fail-closed) instead of being dropped,
    so terminal lifecycle keys cannot disappear from reconciliation silently.

    Returns:
        Parsed (key, body) pairs, structural violations, and count of ``*.json`` keys examined
        (including those that failed to load or parse). Each list row must provide a string
        ``Key`` (persistence service contract). ``get_object``: HTTP 404 is
        ``lifecycle_object_disappeared``; other ``KeyError`` / invalid base64 from the client
        are ``lifecycle_get_response_malformed`` / ``lifecycle_object_body_b64_invalid``.

    Raises ``TypeError`` if ``list_prefix`` returns a non-list (persistence contract break).
    """
    rows = await persistence.list_prefix(prefix, max_keys=None)
    if not isinstance(rows, list):
        raise TypeError(
            f"list_prefix keys must be a JSON array, got {type(rows).__name__} for prefix {prefix!r}"
        )
    out: list[tuple[str, dict[str, Any]]] = []
    violations: list[Violation] = []
    json_keys_examined = 0
    for row in rows:
        if not isinstance(row, dict):
            violations.append(
                Violation(
                    kind="lifecycle_list_entry_invalid",
                    message_id=None,
                    detail=f"list_prefix row must be a JSON object, got {type(row).__name__}: {row!r}",
                )
            )
            continue
        key = row.get("Key")
        if not isinstance(key, str) or not key:
            violations.append(
                Violation(
                    kind="lifecycle_list_entry_invalid",
                    message_id=None,
                    detail=f"list_prefix row missing non-empty string Key: {row!r}",
                )
            )
            continue
        if not key.endswith(".json"):
            continue
        json_keys_examined += 1
        try:
            raw = await persistence.get_object(key)
        except KeyError as exc:
            # PersistenceHttpClient raises KeyError(key) only for HTTP 404; other KeyErrors
            # come from malformed JSON (e.g. missing body_b64).
            if exc.args == (key,):
                violations.append(
                    Violation(
                        kind="lifecycle_object_disappeared",
                        message_id=None,
                        detail=(
                            f"key {key!r} was listed but get_object returned not found "
                            "(concurrent delete or storage inconsistency)"
                        ),
                    )
                )
            else:
                violations.append(
                    Violation(
                        kind="lifecycle_get_response_malformed",
                        message_id=None,
                        detail=f"get_object for {key!r}: unexpected KeyError {exc!r}",
                    )
                )
            continue
        except binascii.Error as exc:
            violations.append(
                Violation(
                    kind="lifecycle_object_body_b64_invalid",
                    message_id=None,
                    detail=f"get_object for {key!r}: invalid base64 in persistence response ({exc})",
                )
            )
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.warning("lifecycle object not valid UTF-8 key=%s", key)
            violations.append(
                Violation(
                    kind="lifecycle_object_invalid_utf8",
                    message_id=None,
                    detail=f"key {key!r}: {exc}",
                )
            )
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("lifecycle object not valid JSON key=%s", key)
            violations.append(
                Violation(
                    kind="lifecycle_object_invalid_json",
                    message_id=None,
                    detail=f"key {key!r}: {exc}",
                )
            )
            continue
        if not isinstance(parsed, dict):
            violations.append(
                Violation(
                    kind="lifecycle_object_not_object",
                    message_id=None,
                    detail=f"key {key!r}: JSON root must be an object",
                )
            )
            continue
        out.append((key, parsed))
    return out, violations, json_keys_examined
