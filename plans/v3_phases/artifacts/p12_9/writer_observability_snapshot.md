# P12.9 WS2 Writer Observability Snapshot

## Scope

This artifact records the per-shard writer observability fields added in WS2 and the parse format emitted by `inspectio-v3-persistence-writer`.

## Evidence outputs

- Raw on-run snapshots:
  `plans/v3_phases/artifacts/p12_9/ws2_observability_evidence/writer_snapshots_on_run.log`
- Parsed summary table:
  `plans/v3_phases/artifacts/p12_9/ws2_observability_evidence/completeness_summary.md`
- Machine-readable pass/fail report:
  `plans/v3_phases/artifacts/p12_9/ws2_observability_evidence/completeness_report.json`

## Snapshot log format

Writer emits structured snapshots at cadence:

- env: `INSPECTIO_V3_WRITER_OBS_SNAPSHOT_INTERVAL_SEC`
- queue-age sampling envs:
  `INSPECTIO_V3_WRITER_QUEUE_AGE_SAMPLE_INTERVAL_SEC`,
  `INSPECTIO_V3_WRITER_QUEUE_AGE_TIMEOUT_SEC`
- log prefix: `writer_snapshot `
- payload: JSON object

Example payload shape:

```json
{
  "snapshot_emitted_at_ms": 1711917600000,
  "queue_polling_idle_ratio": 0.42,
  "ingest_events_per_sec": 1885.123,
  "polls_total": 250,
  "polls_idle": 105,
  "s3_put_retries": 3,
  "checkpoint_write_retries": 1,
  "ack_retries": 0,
  "events_buffered": 12345,
  "events_flushed": 12297,
  "flush_failures": 0,
  "s3_errors": 0,
  "shards": {
    "0": {
      "receive_batches": 115,
      "receive_events_total": 3589,
      "receive_events_last_batch": 10,
      "flush_batches": 22,
      "flush_events_total": 3589,
      "flush_events_last_batch": 180,
      "flush_payload_bytes_last": 52344,
      "flush_duration_ms_last": 54,
      "flush_duration_ms_max": 81,
      "lag_to_durable_commit_ms_last": 640,
      "lag_to_durable_commit_ms_max": 1500,
      "ack_batches": 22,
      "ack_events_total": 3589,
      "ack_events_last_batch": 180,
      "ack_latency_ms_last": 18,
      "ack_latency_ms_max": 42,
      "s3_put_retries": 2,
      "checkpoint_write_retries": 1,
      "ack_retries": 0,
      "transport_oldest_age_ms_last": 420,
      "transport_oldest_age_ms_max": 1100,
      "transport_oldest_age_sampled_at_ms": 1711917600000,
      "buffered_events": 0,
      "oldest_buffer_age_ms": 0,
      "ingest_events_per_sec": 910.4
    }
  }
}
```

## Field mapping to WS2 requirements

- receive batch size/events: `receive_events_last_batch`, `receive_events_total`
- ingest rate: `ingest_events_per_sec` (global and per-shard)
- flush batch size/events: `flush_events_last_batch`, `flush_events_total`
- flush payload bytes: `flush_payload_bytes_last`
- flush duration: `flush_duration_ms_last`, `flush_duration_ms_max`
- ack batch size/latency: `ack_events_last_batch`, `ack_latency_ms_last`, `ack_latency_ms_max`
- retry counts by op: `s3_put_retries`, `checkpoint_write_retries`, `ack_retries`
- queue polling idle ratio: `queue_polling_idle_ratio`
- lag and buffered gauges: `transport_oldest_age_ms_last|max`, `lag_to_durable_commit_ms_last|max`, `buffered_events`, `oldest_buffer_age_ms`

## Queue-age semantics

- `transport_oldest_age_ms_last|max` is sampled from the queue-level SQS attribute
  `ApproximateAgeOfOldestMessage` (seconds -> milliseconds), not inferred from event payload timestamps.
- `transport_oldest_age_sampled_at_ms` records the sample timestamp.
- If sampling fails or times out, writer keeps last-known value and last-known sample timestamp.
