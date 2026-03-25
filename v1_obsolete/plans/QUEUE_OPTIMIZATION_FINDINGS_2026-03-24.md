# QUEUE_OPTIMIZATION_FINDINGS_2026-03-24.md

## Purpose

Capture the latest queue optimization findings from live EKS debugging and load validation on 2026-03-24.

## Findings

1. **Primary stall culprit**
   - Remaining terminal scan in worker lifecycle transitions (`find_existing`) blocked hot-path completion under load.
   - Signature: messages reached `sms_send_done` and `transition_success_start`, but did not complete transition reliably.

2. **Fix outcome**
   - Removed transition-time terminal scans from both success and failure paths.
   - `dispatch done` resumed in high volume on both workers.

3. **Load behavior after fix**
   - Submit path is fast and stable:
     - 100 in 0.482s
     - 1000 in 0.842s
     - 10000 in 1.847s
   - Large-batch drain still long (~299s for 10k) due to downstream terminalization throughput and measurement semantics.

4. **Measurement caveat**
   - Current drain probe waits for global pending zero.
   - This mixes old backlog with current run and overstates run-local drain time.

5. **Health monitor behavior**
   - Integrity check is on-demand in current deployment (`ENABLE_PERIODIC_RECONCILE` not set).
   - Timeouts observed are tied to heavy on-demand scan load, not periodic background scans.

## Hypothesis

With hot-path scan removed, the next dominant bottleneck is terminal persistence throughput (S3 write capacity and writer parallelism), not API ingest or mock SMS dispatch.

## Next actions

1. Switch load validation to run-scoped completion metrics (batch-id scoped success/failed terminal counts).
2. Increase persistence write concurrency gradually (`INSPECTIO_PERSISTENCE_PUT_MAX_WORKERS` step test: 32 -> 64 -> 96 -> 128).
3. Add worker-side terminal micro-batching (`put_objects`) to reduce per-object round-trip cost.
4. Re-run 100 / 1000 / 10000 and compare run-scoped submit+drain before/after.
