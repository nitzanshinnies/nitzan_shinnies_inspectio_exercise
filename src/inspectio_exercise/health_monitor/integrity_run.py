"""One-shot integrity check orchestration (HEALTH_MONITOR.md 4.2).

Audit rows are a **bounded window**: at most ``AUDIT_SENDS_MAX_LIMIT`` most-recent
sends from the mock (see ``HealthMonitorSettings.audit_fetch_limit``). Lifecycle
keys older than that window can produce false ``terminal_success_missing_audit`` /
``terminal_failed_missing_audit_sends`` violations even when the system behaved
correctly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from inspectio_exercise.health_monitor.config import HealthMonitorSettings
from inspectio_exercise.health_monitor.fetch import fetch_audit_rows, load_json_objects_under_prefix
from inspectio_exercise.health_monitor.reconcile import (
    Violation,
    build_lifecycle_snapshot,
    reconcile_integrity,
)
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient

logger = logging.getLogger(__name__)

LIFECYCLE_PENDING_PREFIX: str = "state/pending/"
LIFECYCLE_SUCCESS_PREFIX: str = "state/success/"
LIFECYCLE_FAILED_PREFIX: str = "state/failed/"


@dataclass(frozen=True)
class IntegrityRunResult:
    audit_row_count: int
    # grace_ms: HEALTH_MONITOR.md 3.5 LIVENESS_GRACE_MS (POST body / env default).
    grace_ms: int
    lifecycle_json_keys_examined: int
    # Parsed lifecycle dicts included in the snapshot (HTTP summary: lifecycleObjectsParsed).
    lifecycle_object_count: int
    violations: list[Violation]


async def run_integrity_check(
    *,
    persistence: PersistenceHttpClient,
    mock_sms: httpx.AsyncClient,
    settings: HealthMonitorSettings,
    grace_ms: int,
) -> IntegrityRunResult:
    """Fetch audit + lifecycle prefixes, build views, return blocking violations.

    See module docstring: audit history is capped. ``grace_ms`` applies to §3.5 pending
    lag and §1 phantom-audit race windows in ``reconcile_integrity``.
    """
    t0 = time.perf_counter()
    now_ms = int(time.time() * 1000)
    audit_rows = await fetch_audit_rows(mock_sms, settings.audit_fetch_limit)
    pending, pv, pn = await load_json_objects_under_prefix(persistence, LIFECYCLE_PENDING_PREFIX)
    success, sv, sn = await load_json_objects_under_prefix(persistence, LIFECYCLE_SUCCESS_PREFIX)
    failed, fv, fn = await load_json_objects_under_prefix(persistence, LIFECYCLE_FAILED_PREFIX)
    load_violations = pv + sv + fv
    keys_examined = pn + sn + fn
    snapshot, structural = build_lifecycle_snapshot(
        pending_keys_and_bodies=pending,
        success_keys_and_bodies=success,
        failed_keys_and_bodies=failed,
    )
    logical = reconcile_integrity(
        snapshot,
        audit_rows,
        now_ms=now_ms,
        grace_ms=grace_ms,
    )
    violations = load_violations + structural + logical
    lifecycle_count = len(pending) + len(success) + len(failed)
    elapsed = time.perf_counter() - t0
    logger.info(
        "health_monitor integrity_check audit_rows=%s lifecycle_json_keys=%s lifecycle_parsed=%s "
        "violations=%s grace_ms=%s duration_s=%.3f",
        len(audit_rows),
        keys_examined,
        lifecycle_count,
        len(violations),
        grace_ms,
        elapsed,
    )
    return IntegrityRunResult(
        audit_row_count=len(audit_rows),
        grace_ms=grace_ms,
        lifecycle_json_keys_examined=keys_examined,
        lifecycle_object_count=lifecycle_count,
        violations=violations,
    )
