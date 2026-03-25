"""Pure reconciliation: mock audit rows vs lifecycle objects (HEALTH_MONITOR.md §3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from inspectio_exercise.worker.pending_record import (
    is_valid_pending_row,
    message_id_from_pending_key,
)

HTTP_STATUS_MIN_SUCCESS: Final[int] = 200
HTTP_STATUS_MAX_SUCCESS: Final[int] = 299
HTTP_STATUS_MIN_SERVER_ERROR: Final[int] = 500
HTTP_STATUS_MAX_SERVER_ERROR: Final[int] = 599
TERMINAL_FAILED_ATTEMPT_COUNT: Final[int] = 6
OUTCOME_KIND_VALIDATION_ERROR: Final[str] = "validation_error"
OUTCOME_KIND_SUCCESS: Final[str] = "success"

_TERMINAL_KEY_RE = re.compile(r"^state/(success|failed)/\d{4}/\d{2}/\d{2}/\d{2}/([^/]+)\.json$")


@dataclass(frozen=True)
class Violation:
    kind: str
    message_id: str | None
    detail: str

    def as_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "messageId": self.message_id, "detail": self.detail}


@dataclass(frozen=True)
class LifecycleSnapshot:
    """Lifecycle keys and parsed bodies indexed by message id."""

    failed_bodies: dict[str, dict[str, Any]]
    failed_keys_by_mid: dict[str, tuple[str, ...]]
    pending_bodies: dict[str, dict[str, Any]]
    success_keys_by_mid: dict[str, tuple[str, ...]]


def message_id_from_terminal_key(key: str) -> str | None:
    m = _TERMINAL_KEY_RE.match(key)
    if m is None:
        return None
    return m.group(2)


def build_lifecycle_snapshot(
    *,
    pending_keys_and_bodies: list[tuple[str, dict[str, Any]]],
    success_keys_and_bodies: list[tuple[str, dict[str, Any]]],
    failed_keys_and_bodies: list[tuple[str, dict[str, Any]]],
) -> tuple[LifecycleSnapshot, list[Violation]]:
    """Parse listed objects into a snapshot; emit structural violations."""
    violations: list[Violation] = []
    pending_bodies: dict[str, dict[str, Any]] = {}
    success_by_mid: dict[str, list[str]] = {}
    failed_by_mid: dict[str, list[str]] = {}
    failed_bodies: dict[str, dict[str, Any]] = {}

    for key, body in pending_keys_and_bodies:
        mid = message_id_from_pending_key(key)
        if mid is None:
            violations.append(
                Violation(
                    kind="invalid_pending_key",
                    message_id=None,
                    detail=f"could not parse message id from key {key!r}",
                )
            )
            continue
        if not is_valid_pending_row(mid, body):
            violations.append(
                Violation(
                    kind="invalid_pending_document",
                    message_id=mid,
                    detail="pending JSON failed worker validation (status/messageId/attemptCount/nextDueAt/payload)",
                )
            )
            continue
        pending_bodies[mid] = body

    for key, body in success_keys_and_bodies:
        mid = message_id_from_terminal_key(key)
        if mid is None:
            violations.append(
                Violation(
                    kind="invalid_success_key",
                    message_id=None,
                    detail=f"key does not match state/success/yyyy/MM/dd/hh/<id>.json: {key!r}",
                )
            )
            continue
        st = body.get("status")
        if st is not None and st != "success":
            violations.append(
                Violation(
                    kind="terminal_success_invalid_status",
                    message_id=mid,
                    detail=(
                        "terminal success JSON must have status 'success' when status is present "
                        "(missing status is not flagged; PLAN.md 3)"
                    ),
                )
            )
        success_by_mid.setdefault(mid, []).append(key)

    for key, body in failed_keys_and_bodies:
        mid = message_id_from_terminal_key(key)
        if mid is None:
            violations.append(
                Violation(
                    kind="invalid_failed_key",
                    message_id=None,
                    detail=f"key does not match state/failed/yyyy/MM/dd/hh/<id>.json: {key!r}",
                )
            )
            continue
        failed_by_mid.setdefault(mid, []).append(key)
        failed_bodies[mid] = body

    for mid, keys in success_by_mid.items():
        if len(keys) > 1:
            violations.append(
                Violation(
                    kind="duplicate_success_terminal_keys",
                    message_id=mid,
                    detail=(
                        f"multiple state/success objects for the same message id ({len(keys)} keys) - "
                        "ambiguous lifecycle; skipping per-message audit rules for this id"
                    ),
                )
            )

    for mid, keys in failed_by_mid.items():
        if len(keys) > 1:
            violations.append(
                Violation(
                    kind="duplicate_failed_terminal_keys",
                    message_id=mid,
                    detail=(
                        f"multiple state/failed objects for the same message id ({len(keys)} keys) - "
                        "ambiguous lifecycle; skipping per-message audit rules for this id"
                    ),
                )
            )

    duplicate = set(success_by_mid) & set(failed_by_mid)
    for mid in sorted(duplicate):
        violations.append(
            Violation(
                kind="duplicate_terminal",
                message_id=mid,
                detail="message id appears under both state/success and state/failed",
            )
        )

    snap = LifecycleSnapshot(
        pending_bodies=pending_bodies,
        success_keys_by_mid={k: tuple(v) for k, v in success_by_mid.items()},
        failed_keys_by_mid={k: tuple(v) for k, v in failed_by_mid.items()},
        failed_bodies=failed_bodies,
    )
    return snap, violations


def _is_validation_audit_row(row: dict[str, Any]) -> bool:
    """MOCK_SMS.md 3.3: simulated outcomes are 2xx/5xx; 4xx is invalid-request path, not a send result."""
    if row.get("outcome_kind") == OUTCOME_KIND_VALIDATION_ERROR:
        return True
    st = row.get("http_status")
    return isinstance(st, int) and 400 <= st < 500


def _audit_has_success_for_message(audit_rows: list[dict[str, Any]], message_id: str) -> bool:
    # Mock SMS uses outcome_kind "success" for all simulated 2xx sends (MOCK_SMS.md 3.2, 8.1).
    for row in audit_rows:
        if row.get("messageId") != message_id:
            continue
        st = row.get("http_status")
        if not isinstance(st, int):
            continue
        if not (HTTP_STATUS_MIN_SUCCESS <= st <= HTTP_STATUS_MAX_SUCCESS):
            continue
        if row.get("outcome_kind") != OUTCOME_KIND_SUCCESS:
            continue
        return True
    return False


def _audit_has_mock_send_attempt(audit_rows: list[dict[str, Any]], message_id: str) -> bool:
    """True if mock recorded at least one simulated send (2xx or 5xx), excluding validation rows."""
    for row in audit_rows:
        if row.get("messageId") != message_id:
            continue
        if _is_validation_audit_row(row):
            continue
        st = row.get("http_status")
        if not isinstance(st, int):
            continue
        if HTTP_STATUS_MIN_SUCCESS <= st <= HTTP_STATUS_MAX_SUCCESS:
            return True
        if HTTP_STATUS_MIN_SERVER_ERROR <= st <= HTTP_STATUS_MAX_SERVER_ERROR:
            return True
    return False


def _lifecycle_message_ids(snapshot: LifecycleSnapshot) -> set[str]:
    return (
        set(snapshot.pending_bodies)
        | set(snapshot.success_keys_by_mid)
        | set(snapshot.failed_keys_by_mid)
    )


def _pending_grace_violations(
    snapshot: LifecycleSnapshot,
    audit_rows: list[dict[str, Any]],
    *,
    now_ms: int,
    grace_ms: int,
) -> list[Violation]:
    """HEALTH_MONITOR.md 3.5: future-due pendings skipped; due pendings get grace_ms slack."""
    violations: list[Violation] = []
    for mid, body in snapshot.pending_bodies.items():
        nd = body.get("nextDueAt")
        if not isinstance(nd, int):
            continue
        if nd > now_ms:
            continue
        if _audit_has_mock_send_attempt(audit_rows, mid):
            continue
        overdue_by = now_ms - nd
        if overdue_by <= grace_ms:
            continue
        violations.append(
            Violation(
                kind="pending_due_without_mock_send_audit",
                message_id=mid,
                detail=(
                    f"pending is due (nextDueAt={nd} <= now_ms={now_ms}) but no mock send audit row "
                    f"found after grace_ms={grace_ms} (overdue_by={overdue_by} ms; HEALTH_MONITOR.md 3.5)"
                ),
            )
        )
    return violations


def _phantom_audit_violations(
    audit_rows: list[dict[str, Any]],
    lifecycle_mids: set[str],
    *,
    now_ms: int,
    grace_ms: int,
) -> list[Violation]:
    """HEALTH_MONITOR.md 1: audit send without lifecycle object (with race grace on receivedAt_ms)."""
    violations: list[Violation] = []
    seen: set[str] = set()
    for row in audit_rows:
        mid = row.get("messageId")
        if not isinstance(mid, str) or not mid:
            continue
        if _is_validation_audit_row(row):
            continue
        st = row.get("http_status")
        if not isinstance(st, int):
            continue
        if not (
            HTTP_STATUS_MIN_SUCCESS <= st <= HTTP_STATUS_MAX_SUCCESS
            or HTTP_STATUS_MIN_SERVER_ERROR <= st <= HTTP_STATUS_MAX_SERVER_ERROR
        ):
            continue
        received = row.get("receivedAt_ms")
        if not isinstance(received, int):
            received = now_ms
        if now_ms - received < grace_ms:
            continue
        if mid in lifecycle_mids:
            continue
        if mid in seen:
            continue
        seen.add(mid)
        violations.append(
            Violation(
                kind="audit_send_without_lifecycle",
                message_id=mid,
                detail=(
                    "mock send audit references messageId with no pending/success/failed object in "
                    f"this snapshot (receivedAt_ms={received}, grace_ms={grace_ms}; HEALTH_MONITOR.md 1)"
                ),
            )
        )
    return violations


def _audit_rows_for_terminal_failed_analysis(
    audit_rows: list[dict[str, Any]], message_id: str
) -> list[dict[str, Any]]:
    """Send attempts for a message id (excludes mock validation-only rows)."""
    out: list[dict[str, Any]] = []
    for row in audit_rows:
        if row.get("messageId") != message_id:
            continue
        if _is_validation_audit_row(row):
            continue
        out.append(row)
    return out


def _terminal_failed_body_violations(mid: str, body: dict[str, Any]) -> list[Violation]:
    violations: list[Violation] = []
    if body.get("status") != "failed":
        violations.append(
            Violation(
                kind="terminal_failed_invalid_status",
                message_id=mid,
                detail="state/failed object must have status 'failed'",
            )
        )
    ac = body.get("attemptCount")
    if ac != TERMINAL_FAILED_ATTEMPT_COUNT:
        violations.append(
            Violation(
                kind="terminal_failed_invalid_attempt_count",
                message_id=mid,
                detail=f"terminal failed record must have attemptCount=={TERMINAL_FAILED_ATTEMPT_COUNT}, got {ac!r}",
            )
        )
    return violations


def _terminal_failed_audit_violations(mid: str, rows: list[dict[str, Any]]) -> list[Violation]:
    """HEALTH_MONITOR.md 3.3.2: terminal failed implies send audit rows are only 5xx (MOCK_SMS.md 3.3)."""
    violations: list[Violation] = []
    if not rows:
        return [
            Violation(
                kind="terminal_failed_missing_audit_sends",
                message_id=mid,
                detail=(
                    "terminal failed in lifecycle but no mock send audit rows for this messageId "
                    "(validation-only rows excluded; HEALTH_MONITOR.md 3.3). Audit fetch is bounded "
                    "- absence can be a false positive if sends fell out of the ring buffer."
                ),
            )
        ]

    for row in rows:
        st = row.get("http_status")
        if not isinstance(st, int):
            violations.append(
                Violation(
                    kind="terminal_failed_audit_send_not_5xx",
                    message_id=mid,
                    detail="terminal failed path requires integer 5xx http_status on each send audit row",
                )
            )
            return violations
        if HTTP_STATUS_MIN_SUCCESS <= st <= HTTP_STATUS_MAX_SUCCESS:
            violations.append(
                Violation(
                    kind="terminal_failed_audit_has_success",
                    message_id=mid,
                    detail="terminal failed in lifecycle but audit contains a 2xx send for this message id",
                )
            )
            return violations
        if st < HTTP_STATUS_MIN_SERVER_ERROR or st > HTTP_STATUS_MAX_SERVER_ERROR:
            violations.append(
                Violation(
                    kind="terminal_failed_audit_send_not_5xx",
                    message_id=mid,
                    detail=(
                        f"terminal failed path requires only 5xx send outcomes per HEALTH_MONITOR.md 3.3.2; "
                        f"got http_status={st}"
                    ),
                )
            )
            return violations

    if all(isinstance(row.get("attemptIndex"), int) for row in rows):
        indices = [row["attemptIndex"] for row in rows]
        if len(indices) != TERMINAL_FAILED_ATTEMPT_COUNT or sorted(indices) != list(
            range(TERMINAL_FAILED_ATTEMPT_COUNT)
        ):
            violations.append(
                Violation(
                    kind="terminal_failed_audit_attempt_indices",
                    message_id=mid,
                    detail=(
                        "when every send row carries attemptIndex, terminal failed requires exactly six "
                        f"rows with attemptIndex 0..{TERMINAL_FAILED_ATTEMPT_COUNT - 1} (HEALTH_MONITOR.md 3.4; "
                        "history-based match not implemented - audit rows only)"
                    ),
                )
            )
    return violations


def reconcile_integrity(
    snapshot: LifecycleSnapshot,
    audit_rows: list[dict[str, Any]],
    *,
    now_ms: int,
    grace_ms: int,
) -> list[Violation]:
    """Apply HEALTH_MONITOR.md 1, 3.3-3.5 logical invariants.

    Structural violations (invalid keys, duplicate terminals, load-time fetch/parse issues, etc.)
    are produced in ``fetch.load_json_objects_under_prefix`` and ``build_lifecycle_snapshot``.

    ``grace_ms`` is HEALTH_MONITOR.md 3.5 ``LIVENESS_GRACE_MS`` (POST body / env default).
    """
    violations: list[Violation] = []
    duplicate_mids = set(snapshot.success_keys_by_mid) & set(snapshot.failed_keys_by_mid)
    ambiguous_success = {mid for mid, keys in snapshot.success_keys_by_mid.items() if len(keys) > 1}
    ambiguous_failed = {mid for mid, keys in snapshot.failed_keys_by_mid.items() if len(keys) > 1}
    lifecycle_mids = _lifecycle_message_ids(snapshot)

    for mid in snapshot.success_keys_by_mid:
        if mid in duplicate_mids or mid in ambiguous_success:
            continue
        if not _audit_has_success_for_message(audit_rows, mid):
            violations.append(
                Violation(
                    kind="terminal_success_missing_audit",
                    message_id=mid,
                    detail=(
                        "terminal success in lifecycle requires at least one audit row with 2xx and "
                        "outcome_kind success (MOCK_SMS.md 8.1). Audit fetch is a bounded recent window "
                        "- absence can be a false positive if sends fell out of the ring buffer."
                    ),
                )
            )

    for mid in snapshot.failed_keys_by_mid:
        if mid in duplicate_mids or mid in ambiguous_failed:
            continue
        body = snapshot.failed_bodies.get(mid, {})
        violations.extend(_terminal_failed_body_violations(mid, body))
        send_rows = _audit_rows_for_terminal_failed_analysis(audit_rows, mid)
        violations.extend(_terminal_failed_audit_violations(mid, send_rows))

    violations.extend(
        _pending_grace_violations(
            snapshot,
            audit_rows,
            now_ms=now_ms,
            grace_ms=grace_ms,
        )
    )
    violations.extend(
        _phantom_audit_violations(
            audit_rows,
            lifecycle_mids,
            now_ms=now_ms,
            grace_ms=grace_ms,
        )
    )

    return violations
