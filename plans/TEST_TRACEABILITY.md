# TEST_TRACEABILITY.md — `TC-*` → pytest mapping

Companion to [`TEST_LIST.md`](TEST_LIST.md). Each row maps one enumerated case to the **current** automated suite under `tests/`. This is a **review artifact**: it is updated when tests or the checklist change.

## How to read the status column

| Status | Meaning |
|--------|---------|
| **Full** | Behavior is asserted in pytest with a clear, direct match. |
| **Partial** | Related tests exist (same subsystem) but the exact edge in `TEST_LIST` is not fully exercised, or only domain/reference parity covers it. |
| **None** | No targeted automated test found; treat as a gap unless intentionally out of scope. |
| **Doc** | `TEST_LIST` marks **doc** / **manual** / **optional**; no CI expectation. |
| **N/A** | Not implemented by design (e.g. rate limiting off) or observability-only (**L** layer). |

Test IDs use pytest node style: `tests/<path>::<function>`.

**Sweep:** 2026-03-22 — worker config validation, REST limits/methods/concurrency, worker↔SMS matrix, bootstrap foreign-shard/null/negative cases, mock SMS RNG/latency/concurrency, notification duplicate publish + Redis-down startup, E2E SMS outage, hot-store + sharding + UTC key tests.

---

## 1) Sharding and ownership

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-SH-01 | Full | `tests/unit/test_sharding.py::test_shard_id_matches_spec_stable` | Stable hash vs `reference_spec`. |
| TC-SH-02 | Full | `tests/unit/test_sharding.py::test_shard_id_in_range_matches_spec` | Parametrized `TOTAL_SHARDS`. |
| TC-SH-03 | Doc | — | Migration / different `TOTAL_SHARDS` mapping is optional per checklist. |
| TC-SH-04 | Full | `tests/unit/test_sharding.py::test_owned_shard_range_matches_spec` | |
| TC-SH-05 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_does_not_ingest_foreign_shard_pending` | With `tests/unit/test_sharding.py::test_is_shard_owned_matches_spec`. |
| TC-SH-06 | Full | `tests/unit/test_sharding.py::test_pod_index_matches_spec`, `::test_pod_index_invalid_hostname` | |
| TC-SH-07 | Partial | `tests/integration/test_persistence_service.py::test_list_prefix_http_scoped_to_pending_shard_prefix`, worker bootstrap tests | Owned-prefix listing implied; no single named “no full-bucket scan” assertion beyond scoped list contract. |
| TC-SH-08 | Full | `tests/unit/test_worker_config.py` | `load_worker_settings()` rejects non-positive `TOTAL_SHARDS` / `SHARDS_PER_POD`. |
| TC-SH-09 | Doc | — | Pod/shard topology mismatch documented only. |
| TC-SH-10 | Partial | `tests/unit/test_rest_handlers.py` (202 + `messageId`), `tests/integration/test_api_activation.py::test_post_messages_creates_pending_under_shard_prefix` | UUID shape; **path-injection** / empty-id rejection not separately asserted. |
| TC-SH-11 | Partial | `tests/integration/test_worker_bootstrap.py::test_bootstrap_rebuilds_scheduler_from_pending` | Two pendings same shard; not “many” / stress. |
| TC-SH-12 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_completes_with_no_pending_objects` | |
| TC-SH-13 | N/A | — | Public API always server-generates UUID `messageId` (no client-supplied id). |

---

## 2) Retry timeline and `attemptCount`

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-RT-01 | Full | `tests/unit/test_retry_timeline.py`, `tests/unit/test_worker_runtime.py::test_run_tick_failed_send_schedules_retry` | Golden delays + integration bump. |
| TC-RT-02 | Full | `tests/unit/test_retry_timeline.py::test_delay_ms_matches_spec_for_each_failure_index` | |
| TC-RT-03 | Full | `tests/unit/test_retry_timeline.py::test_attempt_count_terminal_matches_spec` | |
| TC-RT-04 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_failed_send_schedules_retry` | In-place pending update. |
| TC-RT-05 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_success_writes_terminal_and_notifies` | |
| TC-RT-06 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_attempt_count_above_six`, `::test_bootstrap_skips_pending_negative_attempt_count` | |
| TC-RT-07 | Partial | — | Integer ms implied by JSON round-trips; **no** float-in-JSON negative test. |
| TC-RT-08 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_status_not_pending` | Aligns with TC-RQ-12. |
| TC-RT-09 | None | — | `history[]` not implemented / not tested. |
| TC-RT-10 | None | — | Double-increment / race not modeled in pytest. |

---

## 3) Wakeup loop and due selection

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-WU-01 | Full | `tests/unit/test_wakeup_cadence.py::test_select_due_matches_spec` | Inclusive `<=`. |
| TC-WU-02 | Full | `tests/unit/test_wakeup_cadence.py::test_select_due_matches_spec` | |
| TC-WU-03 | Full | `tests/unit/test_wakeup_cadence.py::test_heap_pop_order_matches_spec` | Tie-break via heap ordering. |
| TC-WU-04 | Full | `tests/unit/test_wakeup_cadence.py::test_tick_and_elapsed_round_trip_matches_spec` | |
| TC-WU-05 | Partial | `tests/unit/test_worker_runtime.py::test_run_tick_success_writes_terminal_and_notifies` | **Concurrent** multi-send same tick not stressed. |
| TC-WU-06 | Partial | `tests/unit/test_worker_runtime.py::test_run_tick_success_writes_terminal_and_notifies` | Drop from scheduler implied. |
| TC-WU-07 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_rebuilds_scheduler_from_pending` | |
| TC-WU-08 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_empty_persistence_does_not_call_sms` | |
| TC-WU-09 | Partial | `tests/unit/test_wakeup_cadence.py` | Via reference parity, not full worker tick count. |
| TC-WU-10 | None | — | Bootstrap ordering vs first tick not isolated. |
| TC-WU-11 | None | — | Clock jump forward / idempotent drain (partially implied by retry E2E). |
| TC-WU-12 | Full | `tests/unit/test_wakeup_cadence.py::test_select_due_excludes_messages_when_now_moves_backward` | Domain-level `select_due` semantics. |

---

## 4) Persistence keys and moves

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-PV-01 | Full | `tests/integration/test_api_activation.py::test_post_messages_creates_pending_under_shard_prefix`, `tests/unit/test_sharding.py::test_pending_prefix_matches_spec` | |
| TC-PV-02 | Full | `tests/unit/test_terminal_keys_utc.py` | Midnight / rollover segments. |
| TC-PV-03 | Full | `tests/unit/test_terminal_keys_utc.py::test_failed_terminal_key_shares_partition_shape_with_success` | |
| TC-PV-04 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_success_writes_terminal_and_notifies` | Pending removed. |
| TC-PV-05 | Partial | `tests/unit/test_idempotency.py`, `tests/unit/test_worker_runtime.py::test_existing_terminal_skips_sms_reconciles_pending` | Ledger + reconcile; not HTTP client “retry put” only. |
| TC-PV-06 | Full | `tests/unit/test_worker_runtime.py::test_success_path_retries_pending_delete_after_transient_503` | Simulated **503** on first pending `delete_object`; retries converge. |
| TC-PV-07 | None | — | Concurrent read during move. |
| TC-PV-08 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_message_id_mismatch_filename` | |
| TC-PV-09 | Partial | `tests/integration/test_api_activation.py::test_post_messages_does_not_invoke_list_prefix`, `tests/integration/test_notification_outcomes.py::test_api_get_outcomes_uses_notification_service_not_terminal_listing` | POST + GET outcomes; not every list call site. |

---

## 5) Activation / API-first

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-NM-01 | Full | `tests/integration/test_api_activation.py::test_post_messages_creates_pending_under_shard_prefix` + E2E | Ordering vs worker. |
| TC-NM-02 | Partial | E2E / worker tick | “0s delay after activation” not a single named unit. |
| TC-NM-03 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_malformed_pending_json`, `tests/unit/test_worker_runtime.py::test_invalid_payload_deletes_pending_and_drops_scheduler_state` | |
| TC-NM-04 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_success_terminal_and_recent_outcome` | |
| TC-NM-05 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_rejects_non_json_content_type` | |
| TC-NM-06 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_extra_json_fields_ignored` | |
| TC-NM-07 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_rejects_oversized_body`, `::test_post_messages_repeat_rejects_oversized_body` | `413` from `MESSAGE_BODY_MAX_CHARS` (env `INSPECTIO_MESSAGE_BODY_MAX_CHARS`). |
| TC-NM-08 | Partial | `tests/unit/test_rest_handlers.py::test_post_messages_repeat_returns_summary` | `count=1` only in unit; integration mirrors. |
| TC-NM-09 | Partial | — | Implicit (worker never creates pending); no negative test proving absence. |

---

## 6) Idempotency

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-ID-01 | Full | `tests/unit/test_idempotency.py::test_duplicate_activation_rejected_matches_ref` | |
| TC-ID-02 | Partial | `tests/unit/test_idempotency.py::test_replay_after_terminal_rejected_matches_ref`, `tests/unit/test_worker_runtime.py::test_existing_terminal_skips_sms_reconciles_pending` | Ledger + reconcile; second **S3** success key not always asserted in one test. |
| TC-ID-03 | Partial | Same as TC-ID-02 | Failed terminal replay symmetry not isolated. |
| TC-ID-04 | Full | `tests/unit/test_worker_runtime.py::test_concurrent_handle_one_same_message_single_terminal` | Pinned `now_ms`; two parallel `handle_one` calls. |
| TC-ID-05 | Partial | `tests/e2e/test_multi_component_flow.py::test_e2e_repeat_distinct_message_ids` | Same body → new ids (implicit policy). |
| TC-ID-06 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_does_not_ingest_foreign_shard_pending` | Non-owner never lists foreign pending prefix. |
| TC-ID-07 | N/A | — | Optional CAS / ETag pattern. |

---

## 7) Bootstrap / malformed queue rows

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-RQ-01 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_rebuilds_scheduler_from_pending` | |
| TC-RQ-02 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_malformed_pending_json` | Truncated / `null` body not every variant. |
| TC-RQ-03 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_attempt_count_above_six`, `::test_bootstrap_skips_pending_negative_attempt_count` | |
| TC-RQ-04 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_rebuilds_scheduler_from_pending` | `nextDueAt` in the past (e.g. `100_000` vs `now` `250_000`). |
| TC-RQ-05 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_retries_transient_persistence_errors` | |
| TC-RQ-06 | None | — | Optional degraded signal. |
| TC-RQ-07 | None | — | Idempotency cache across restart. |
| TC-RQ-08 | Full | `tests/unit/test_worker_runtime.py::test_existing_terminal_skips_sms_reconciles_pending` | |
| TC-RQ-09 | None | — | Duplicate keys same `messageId`. |
| TC-RQ-10 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_missing_next_due_at`, `::test_bootstrap_skips_pending_null_next_due_at` | |
| TC-RQ-11 | Partial | Bootstrap with `TOTAL_SHARDS=16` | All shards scanned; **order-independence** not asserted across permutations. |
| TC-RQ-12 | Full | `tests/integration/test_worker_bootstrap.py::test_bootstrap_skips_pending_status_not_pending` | |
| TC-RQ-13 | None | — | Partial file / CRC. |

---

## 8) REST API

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-API-01 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_missing_required_fields_rejected`, `::test_post_messages_empty_to_rejected` | Whitespace-only **body** not explicit. |
| TC-API-02 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_body_wrong_json_type_rejected` | |
| TC-API-03 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_valid_body_returns_accepted_metadata` | |
| TC-API-04 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_repeat_returns_summary` | |
| TC-API-05 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_repeat_invalid_count_rejected`, `::test_post_messages_repeat_float_count_rejected`, `::test_post_messages_repeat_count_above_cap_rejected` | |
| TC-API-06 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_success_forwards_default_limit_to_notification` | |
| TC-API-07 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_failed_forwards_default_limit_to_notification` | |
| TC-API-08 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_success_limit_at_max_allowed`, `::test_get_messages_success_limit_above_max_rejected` | FastAPI rejects above max (not clamp). |
| TC-API-09 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_success_invalid_limit_rejected`, `::test_get_messages_failed_invalid_limit_rejected` | Non-numeric query may be framework-default. |
| TC-API-10 | Full | `tests/unit/test_healthz.py`, `tests/integration/test_integration_stack_liveness.py` | Per-service `healthz`. |
| TC-API-11 | Partial | `tests/unit/test_rest_handlers.py::test_validation_error_json_has_no_traceback_strings` | FastAPI `detail` shape; no stack traces in 422 JSON. |
| TC-API-12 | Full | `tests/integration/test_api_activation.py::test_post_messages_does_not_invoke_list_prefix` | |
| TC-API-13 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_success_accepts_unknown_query_params` | |
| TC-API-14 | Full | `tests/unit/test_rest_handlers.py::test_delete_messages_method_not_allowed` | |
| TC-API-15 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_repeat_missing_count_rejected` | |
| TC-API-16 | Full | `tests/unit/test_rest_handlers.py::test_post_messages_unicode_body_round_trip_on_put`, `::test_post_messages_unicode_to_round_trip_on_put` | |
| TC-API-17 | Full | `tests/unit/test_rest_handlers.py::test_get_messages_success_accepts_accept_header` | |
| TC-API-18 | Full | `tests/unit/test_rest_handlers.py::test_concurrent_post_messages_yield_distinct_ids` | |

---

## 9) Outcomes cache / hot store

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-CA-01 | Full | `tests/unit/test_outcomes_hot_store.py::test_outcomes_stream_max_covers_default_api_query_limit` | |
| TC-CA-02 | Partial | `tests/unit/test_outcomes_hot_store.py::test_memory_store_prepend_trim_newest_first` | Eviction semantics. |
| TC-CA-03 | Partial | `tests/integration/test_notification_service.py` | Success vs failed streams. |
| TC-CA-04 | Full | `tests/unit/test_outcomes_hot_store.py`, `tests/e2e/test_multi_component_flow.py::test_e2e_limit_returns_at_most_requested_rows` | |
| TC-CA-05 | Full | `tests/unit/test_outcomes_hot_store.py::test_memory_store_empty_success_stream`, `tests/unit/test_rest_handlers.py` (mock empty list) | |
| TC-CA-06 | Full | `tests/integration/test_notification_outcomes.py::test_api_get_outcomes_uses_notification_service_not_terminal_listing` | |
| TC-CA-07 | Full | `tests/unit/test_outcomes_hot_store.py::test_memory_store_returns_all_rows_when_limit_exceeds_length` | |
| TC-CA-08 | Full | `tests/unit/test_outcomes_hot_store.py::test_memory_store_allows_duplicate_message_ids_in_stream` | Documents current policy. |
| TC-CA-09 | Full | `tests/integration/test_notification_service.py::test_hydration_reloads_redis_after_second_stack`, `::test_hydration_two_success_records_newest_first` | API-only restart slice not separated. |
| TC-CA-10 | Partial | E2E + notification integration | Ordering vs terminal commit time documented elsewhere. |

---

## 10) Mock SMS

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-SMS-01 | Full | `tests/unit/test_mock_sms_send.py::test_send_success_200` | |
| TC-SMS-02 | Full | `tests/unit/test_mock_sms_send.py::test_send_rejects_empty_to` | |
| TC-SMS-03 | Full | `tests/unit/test_mock_sms_send.py::test_send_should_fail_is_5xx` | |
| TC-SMS-04 | Full | `tests/unit/test_mock_sms_send.py::test_rng_seed_produces_repeatable_status_sequence` | Patched in-module RNG. |
| TC-SMS-05 | Full | `tests/unit/test_mock_sms_send.py::test_mixed_failure_and_unavailable_can_emit_500_and_503` | |
| TC-SMS-06 | Full | `tests/unit/test_mock_sms_send.py::test_send_valid_payload_never_4xx_on_simulate_path` | |
| TC-SMS-07 | Full | `tests/unit/test_mock_sms_send.py::test_latency_ms_waits_before_outcome` | Asserts `asyncio.sleep` path. |
| TC-SMS-08 | Full | `tests/unit/test_mock_sms_send.py::test_send_success_200` (with `FAILURE_RATE` patch) | |
| TC-SMS-09 | Full | `tests/unit/test_mock_sms_send.py::test_failure_rate_one_always_5xx_without_should_fail` | |
| TC-SMS-10 | Full | `tests/unit/test_mock_sms_send.py::test_unavailable_fraction_zero_uses_500_class_not_503`, `::test_unavailable_fraction_one_yields_503_on_random_failure` | |
| TC-SMS-11 | Full | `tests/unit/test_mock_sms_send.py::test_concurrent_send_requests` | |
| TC-SMS-12 | Partial | `tests/unit/test_mock_sms_send.py::test_audit_sends_returns_newest_first`, `tests/e2e/test_multi_component_flow.py::test_e2e_mock_audit_reflects_send` | Stdout JSONL not always asserted in pytest. |

---

## 11) Worker ↔ SMS

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-WS-01 | Full | `tests/unit/test_worker_mock_sms_client.py::test_post_mock_send_includes_message_id_and_attempt_index` | |
| TC-WS-02 | Full | `tests/unit/test_worker_mock_sms_client.py::test_post_mock_send_propagates_connect_error` | |
| TC-WS-03 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_http_not_implemented_schedules_retry`, `::test_run_tick_http_599_schedules_retry` | |
| TC-WS-04 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_http_204_counts_as_success` | |
| TC-WS-05 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_http_302_triggers_retry_schedule` | |
| TC-WS-06 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_http_200_with_error_shaped_json_still_success` | |
| TC-WS-07 | Full | `tests/unit/test_worker_runtime.py::test_run_tick_http_429_schedules_retry` | **408** not isolated (same non-2xx path). |

---

## 12) End-to-end

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-E2E-01 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_success_terminal_and_recent_outcome` | |
| TC-E2E-02 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_retry_then_success` | |
| TC-E2E-03 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_terminal_failed_should_fail_payload` | |
| TC-E2E-04 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_worker_restart_resumes_retry` | |
| TC-E2E-05 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_repeat_distinct_message_ids` | Moderate N, not 100. |
| TC-E2E-06 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_limit_returns_at_most_requested_rows` | |
| TC-E2E-07 | Full | `tests/integration/test_api_activation.py::test_post_messages_pending_without_worker_has_no_success_outcome` | Integration-level “no worker”. |
| TC-E2E-08 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_sms_outage_then_recovery` | Simulated extended 503 then recovery. |
| TC-E2E-09 | Partial | E2E `shouldFail` / activation tests | Explicit “every attempt fails until terminal” narrative varies by scenario. |
| TC-E2E-10 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_mock_audit_reflects_send` | |

---

## 13) Scaling / ops

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-SC-01 | Full | `tests/unit/test_sharding.py::test_owned_shard_sets_vary_with_pod_index` | |
| TC-SC-02 | Doc | — | Manual migration. |
| TC-SC-03 | Doc | — | Zero workers. |
| TC-SC-04 | Doc | — | Duplicate `HOSTNAME`. |

---

## 14) Observability

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-OB-01 | N/A | — | **L** — log fields; manual. |
| TC-OB-02 | N/A | — | **L** — manual. |
| TC-OB-03 | N/A | — | **L** — metrics; manual. |

---

## 15) Security / abuse

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-SE-01 | Partial | `tests/unit/test_rest_handlers.py::test_validation_error_json_has_no_traceback_strings` | Focuses on 422 JSON; 503 peer errors may echo upstream text. |
| TC-SE-02 | N/A | — | Rate limiting not in baseline spec. |

---

## 17) Health monitor

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-HM-01 | Full | `tests/unit/test_health_monitor_reconcile.py` (success + audit 2xx cases) | Several functions; see file. |
| TC-HM-02 | Full | `tests/unit/test_health_monitor_reconcile.py` (failed terminal + attempt index cases) | |
| TC-HM-03 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_health_monitor_healthz` | |
| TC-HM-04 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_health_monitor_integrity_ok_after_success` | |
| TC-HM-05 | Full | `tests/e2e/test_multi_component_flow.py::test_e2e_health_monitor_integrity_fails_on_induced_drift` | |
| — | Partial | `tests/integration/test_health_monitor_reconcile.py`, `tests/unit/test_health_monitor_fetch.py` | Extra HTTP / malformed-object coverage beyond numbered TCs. |

---

## 19.1) Notification service (`TC-NTF-*`)

| ID | Status | Primary test(s) | Notes |
|----|--------|-----------------|-------|
| TC-NTF-01 | Full | `tests/integration/test_notification_outcomes.py::test_publish_after_durable_terminal_write` | |
| TC-NTF-02 | Full | `tests/integration/test_notification_service.py::test_hydration_reloads_redis_after_second_stack`, `tests/e2e/test_multi_component_flow.py::test_e2e_terminal_failed_should_fail_payload` | Failed outcomes via notification internal API + E2E. |
| TC-NTF-03 | Full | `tests/unit/test_worker_outcome_notifier.py::test_publish_retries_after_transient_notification_failures` | |
| TC-NTF-04 | Full | `tests/integration/test_notification_service.py::test_hydration_reloads_redis_after_second_stack` | |
| TC-NTF-05 | Full | `tests/integration/test_notification_service.py::test_duplicate_publish_same_notification_record_twice` | Current policy: duplicate rows in hot stream. |
| TC-NTF-06 | Full | `tests/integration/test_notification_outcomes.py::test_notification_service_hydration_order_and_cap` | |
| TC-NTF-07 | Full | `tests/integration/test_notification_service.py::test_notification_app_startup_fails_when_redis_unreachable` | Lifespan fails; API-readiness 503 not separately asserted. |

---

## Other automated suites (cross-cutting)

These support many `TC-*` rows but are not tied to a single ID:

- **Domain parity:** `tests/reference_spec.py` (imported / mirrored by `test_sharding`, `test_retry_timeline`, `test_wakeup_cadence`, `test_idempotency`, etc.).
- **Persistence HTTP surface:** `tests/integration/test_persistence_service.py`, `tests/unit/test_local_s3_provider.py`, `tests/unit/test_aws_s3_provider.py`, `tests/unit/test_persistence_port.py`.
- **Persistence retry:** `tests/unit/test_persistence_retry.py`.
- **Worker runtime (lifecycle):** `tests/unit/test_worker_runtime.py` (remaining tests not listed per-row above).
- **Worker env validation:** `tests/unit/test_worker_config.py`.

---

## Count snapshot (manual)

`TEST_LIST.md` §18 totals **134** enumerated rows in sections 1–17; §19.1 adds **7** `TC-NTF-*` rows. This matrix lists **those 141** IDs plus **N/A** / **Doc** rows.

**Still typically None / Partial / N/A (examples):** TC-PV-07 (concurrent read during move), TC-RT-09/10, TC-WU-10/11, TC-RQ-06/07/09/13, TC-API-01 whitespace-only body nuance, TC-SE-01 for non-422 errors, TC-OB-*, TC-SC-02–04 (doc), TC-NTF-07 API-layer 503 when notify is down (separate from Redis startup).

When a new pytest is added for a gap, update the corresponding row here (and optionally add the `TC-*` id to the test docstring).
