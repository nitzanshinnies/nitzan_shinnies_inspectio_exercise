"""Pure reconciliation rules (plans/HEALTH_MONITOR.md §3)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.utc_paths import terminal_failed_key, terminal_success_key
from inspectio_exercise.health_monitor.reconcile import (
    build_lifecycle_snapshot,
    reconcile_integrity,
)

pytestmark = pytest.mark.unit

_NOW_MS = 1_850_000_000_000


def _pending_key(mid: str) -> str:
    return f"state/pending/shard-0/{mid}.json"


def _valid_pending(mid: str, *, next_due: int) -> dict[str, object]:
    return {
        "messageId": mid,
        "status": "pending",
        "attemptCount": 0,
        "nextDueAt": next_due,
        "payload": {"to": "+1", "body": "b"},
    }


def test_duplicate_terminal_emits_violation() -> None:
    mid = "dup-1"
    sk = terminal_success_key(mid, 1_700_000_000_000)
    fk = terminal_failed_key(mid, 1_700_000_100_000)
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[(sk, {"status": "success", "messageId": mid})],
        failed_keys_and_bodies=[(fk, {"status": "failed", "messageId": mid, "attemptCount": 6})],
    )
    kinds = {v.kind for v in structural}
    assert "duplicate_terminal" in kinds
    assert reconcile_integrity(snap, [], now_ms=_NOW_MS, grace_ms=0) == []


def test_terminal_success_requires_audit_2xx_success_kind() -> None:
    mid = "ok-1"
    sk = terminal_success_key(mid, 1_700_000_000_000)
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[(sk, {"status": "success", "messageId": mid})],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    v = reconcile_integrity(snap, [], now_ms=_NOW_MS, grace_ms=0)
    assert len(v) == 1
    assert v[0].kind == "terminal_success_missing_audit"

    audit = [
        {
            "messageId": mid,
            "http_status": 200,
            "outcome_kind": "success",
            "attemptIndex": 0,
        }
    ]
    assert reconcile_integrity(snap, audit, now_ms=_NOW_MS, grace_ms=0) == []


def test_terminal_failed_missing_audit_sends() -> None:
    mid = "fail-empty-audit"
    fk = terminal_failed_key(mid, 1_700_000_000_000)
    body = {
        "messageId": mid,
        "status": "failed",
        "attemptCount": 6,
        "nextDueAt": 0,
        "payload": {"to": "+1", "body": "b"},
        "recordedAt": 1_700_000_000_000,
    }
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[(fk, body)],
    )
    assert structural == []
    v = reconcile_integrity(snap, [], now_ms=_NOW_MS, grace_ms=0)
    kinds = {x.kind for x in v}
    assert "terminal_failed_missing_audit_sends" in kinds


def test_terminal_failed_rejects_non_5xx_audit_row() -> None:
    mid = "fail-not-5xx"
    fk = terminal_failed_key(mid, 1_700_000_000_000)
    body = {
        "messageId": mid,
        "status": "failed",
        "attemptCount": 6,
        "nextDueAt": 0,
        "payload": {"to": "+1", "body": "b"},
        "recordedAt": 1_700_000_000_000,
    }
    snap, _ = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[(fk, body)],
    )
    # 4xx rows are treated as mock validation/client errors and excluded from send analysis.
    audit = [{"messageId": mid, "http_status": 100, "outcome_kind": "weird", "attemptIndex": 0}]
    v = reconcile_integrity(snap, audit, now_ms=_NOW_MS, grace_ms=0)
    assert any(x.kind == "terminal_failed_audit_send_not_5xx" for x in v)


def test_terminal_failed_rejects_success_audit_row() -> None:
    mid = "fail-1"
    fk = terminal_failed_key(mid, 1_700_000_000_000)
    body = {
        "messageId": mid,
        "status": "failed",
        "attemptCount": 6,
        "nextDueAt": 0,
        "payload": {"to": "+1", "body": "b"},
        "recordedAt": 1_700_000_000_000,
    }
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[(fk, body)],
    )
    assert structural == []
    bad_audit = [
        {"messageId": mid, "http_status": 200, "outcome_kind": "success", "attemptIndex": 5},
    ]
    v = reconcile_integrity(snap, bad_audit, now_ms=_NOW_MS, grace_ms=0)
    assert any(x.kind == "terminal_failed_audit_has_success" for x in v)


def test_terminal_failed_attempt_indices_when_all_present() -> None:
    mid = "fail-2"
    fk = terminal_failed_key(mid, 1_700_000_000_000)
    body = {
        "messageId": mid,
        "status": "failed",
        "attemptCount": 6,
        "nextDueAt": 0,
        "payload": {"to": "+1", "body": "b"},
        "recordedAt": 1_700_000_000_000,
    }
    snap, _ = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[(fk, body)],
    )
    five_xx = [
        {
            "messageId": mid,
            "http_status": 503,
            "outcome_kind": "service_unavailable",
            "attemptIndex": i,
        }
        for i in range(5)
    ]
    v = reconcile_integrity(snap, five_xx, now_ms=_NOW_MS, grace_ms=0)
    assert any(x.kind == "terminal_failed_audit_attempt_indices" for x in v)

    six = [
        {
            "messageId": mid,
            "http_status": 503,
            "outcome_kind": "service_unavailable",
            "attemptIndex": i,
        }
        for i in range(6)
    ]
    assert reconcile_integrity(snap, six, now_ms=_NOW_MS, grace_ms=0) == []


def test_duplicate_success_terminal_keys_structural_skips_audit_rules() -> None:
    mid = "two-success"
    k1 = terminal_success_key(mid, 1_700_000_000_000)
    k2 = terminal_success_key(mid, 1_701_000_000_000)
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[
            (k1, {"status": "success", "messageId": mid}),
            (k2, {"status": "success", "messageId": mid}),
        ],
        failed_keys_and_bodies=[],
    )
    assert any(v.kind == "duplicate_success_terminal_keys" for v in structural)
    assert reconcile_integrity(snap, [], now_ms=_NOW_MS, grace_ms=0) == []


def test_terminal_success_wrong_status_is_structural() -> None:
    mid = "bad-success-doc"
    sk = terminal_success_key(mid, 1_700_000_000_000)
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[(sk, {"status": "pending", "messageId": mid})],
        failed_keys_and_bodies=[],
    )
    assert any(v.kind == "terminal_success_invalid_status" for v in structural)


def test_invalid_pending_document_is_structural() -> None:
    mid = "bad-pend"
    key = _pending_key(mid)
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, {"messageId": mid, "status": "wrong"})],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert snap.pending_bodies == {}
    assert any(v.kind == "invalid_pending_document" for v in structural)


def test_pending_future_next_due_skips_missing_send_check() -> None:
    mid = "pend-future"
    key = _pending_key(mid)
    now_ms = 2_000_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, _valid_pending(mid, next_due=now_ms + 60_000))],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    assert reconcile_integrity(snap, [], now_ms=now_ms, grace_ms=0) == []


def test_pending_due_without_send_after_grace_violates() -> None:
    mid = "pend-late"
    key = _pending_key(mid)
    nd = 1_000_000
    now_ms = nd + 10_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, _valid_pending(mid, next_due=nd))],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    v = reconcile_integrity(snap, [], now_ms=now_ms, grace_ms=5_000)
    assert any(x.kind == "pending_due_without_mock_send_audit" for x in v)


def test_pending_due_within_grace_no_violation() -> None:
    mid = "pend-grace"
    key = _pending_key(mid)
    nd = 1_000_000
    now_ms = nd + 3_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, _valid_pending(mid, next_due=nd))],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    assert reconcile_integrity(snap, [], now_ms=now_ms, grace_ms=5_000) == []


def test_pending_due_with_mock_5xx_audit_ok() -> None:
    mid = "pend-5xx"
    key = _pending_key(mid)
    nd = 1_000_000
    now_ms = nd + 20_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, _valid_pending(mid, next_due=nd))],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    audit = [
        {
            "messageId": mid,
            "http_status": 503,
            "outcome_kind": "service_unavailable",
            "attemptIndex": 0,
        },
    ]
    kinds = {x.kind for x in reconcile_integrity(snap, audit, now_ms=now_ms, grace_ms=0)}
    assert "pending_due_without_mock_send_audit" not in kinds


def test_phantom_audit_recent_inside_grace_skipped() -> None:
    mid = "phantom-fresh"
    now_ms = 5_000_000
    snap, _ = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    audit = [
        {
            "messageId": mid,
            "http_status": 200,
            "outcome_kind": "success",
            "attemptIndex": 0,
            "receivedAt_ms": now_ms - 1_000,
        },
    ]
    assert reconcile_integrity(snap, audit, now_ms=now_ms, grace_ms=5_000) == []


def test_phantom_audit_stale_outside_grace() -> None:
    mid = "phantom-1"
    now_ms = 5_000_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    audit = [
        {
            "messageId": mid,
            "http_status": 200,
            "outcome_kind": "success",
            "attemptIndex": 0,
            "receivedAt_ms": now_ms - 20_000,
        },
    ]
    v = reconcile_integrity(snap, audit, now_ms=now_ms, grace_ms=5_000)
    assert any(x.kind == "audit_send_without_lifecycle" for x in v)


def test_phantom_suppressed_when_mid_in_pending() -> None:
    mid = "pend-covers-audit"
    key = _pending_key(mid)
    now_ms = 5_000_000
    snap, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=[(key, _valid_pending(mid, next_due=now_ms + 60_000))],
        success_keys_and_bodies=[],
        failed_keys_and_bodies=[],
    )
    assert structural == []
    audit = [
        {
            "messageId": mid,
            "http_status": 200,
            "outcome_kind": "success",
            "attemptIndex": 0,
            "receivedAt_ms": now_ms - 20_000,
        },
    ]
    kinds = {x.kind for x in reconcile_integrity(snap, audit, now_ms=now_ms, grace_ms=5_000)}
    assert "audit_send_without_lifecycle" not in kinds
