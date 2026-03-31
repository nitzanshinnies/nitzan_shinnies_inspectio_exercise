# P10: EKS 10k/s E2E Execution Plan and Run Record

## Goal

Reach and document sustained v3 throughput at or above 10k messages/sec end-to-end proxy metric on AWS EKS using real SQS.

Primary e2e proxy metric for this phase:

- Sum CloudWatch `AWS/SQS -> NumberOfMessagesDeleted` across all active send queues.
- Convert 60s bucket sum to deletes/sec (`sum / 60`).

## Branch and Images

- Branch: `feat/v3-eks-throughput-scale`
- Commits used for performance passes:
  - `c80d059` - shared L2 SQS client + expander/worker parallelism and sustain harness tuning
  - `53c9481` - configurable worker receive pollers
  - `f0d5169` - worker no-op outcomes toggle for high-throughput runs
- ECR images used:
  - `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:eks-10k`
  - `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:eks-10k2`
  - `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:eks-10k3`

## Cluster Setup Used for Final Run

Cluster:

- EKS cluster: `nitzan-inspectio`
- Nodegroup: `ng-main`
- Scaled config during perf run: `min=2, desired=16, max=24`

Workloads (final successful run shape):

- `inspectio-api`: 12 replicas
- `inspectio-l1`: 4 replicas
- `inspectio-expander`: 16 replicas
- `inspectio-worker-shard-0..7`: 24 replicas each
- `redis`: 1 replica

Send sharding:

- `INSPECTIO_V3_SEND_SHARD_COUNT=8`
- `INSPECTIO_V3_SEND_QUEUE_URLS` configured as JSON array for:
  - `inspectio-v3-send-0` .. `inspectio-v3-send-7`

## Perf ConfigMap Tunables Applied

These settings were applied in `inspectio-v3-config` for high-throughput runs:

- `INSPECTIO_V3_WORKER_RECORD_OUTCOMES=false`
- `INSPECTIO_V3_WORKER_RECEIVE_POLLERS=3`
- `INSPECTIO_V3_WORKER_WAKEUP_SEC=0.03`
- `INSPECTIO_V3_EXPANDER_PUBLISH_CONCURRENCY=96`
- `INSPECTIO_V3_EXPANDER_BULK_RECEIVE_MAX=10`

Note: Disabling worker outcome writes avoids Redis write-path collapse under extreme load and was necessary for this phase's throughput target.

## Sustained Load Job Configuration

Driver script:

- `scripts/v3_sustained_admit.py`

Final successful 10k+ e2e run:

- Duration: 55 sec
- Concurrency: 150
- Batch (`count` per repeat call): 500
- In-cluster base URL: `http://inspectio-l1:8080`

## Measured Results

### Before K=8 expansion

- Example run (K=4 tuned):
  - Admit: `~8654.55 msg/s`
  - E2E proxy peak deletes: `~1503.17 msg/s`

### K=8 tuned run (near target)

- Admit: `947000 / 55 = 17218.18 msg/s`
- CloudWatch peak combined deletes:
  - `CW_PEAK_1M_SUM=570583`
  - `CW_PEAK_DELETES_PER_SEC=9509.72`

### K=8 tuned run (target exceeded)

- Admit: `1013000 / 55 = 18418.18 msg/s`
- CloudWatch peak combined deletes:
  - `CW_PEAK_1M_SUM=689745`
  - `CW_PEAK_DELETES_PER_SEC=11495.75`
- CloudWatch window total deletes: `1389417`

Conclusion: phase target (10k/s e2e proxy metric) exceeded on this setup.

## Known Trade-offs

- With `INSPECTIO_V3_WORKER_RECORD_OUTCOMES=false`, Redis outcome rings are not updated by workers during these throughput runs.
- Metric reported here is SQS delete throughput proxy (send queue drain), not durable business completion accounting.
- EKS control plane cost remains even if compute nodes are scaled to zero.

## Remaining Items

1. Reintroduce durable/observable completion path without collapsing throughput.
2. Add dashboards/alerts for L1/L2 error rates, SQS lag, worker crash loops, and Redis health.
3. Establish repeatable benchmark profiles (smoke, baseline, max-throughput).
4. Validate cost/perf curve for K=4/8/16 and worker poller values.
5. Define production-safe defaults separate from benchmark overrides.

## Cost Control / Pause Procedure

To minimize cost after a run:

1. Scale namespace workloads to zero replicas.
2. Scale nodegroup desired/min to zero.

To eliminate EKS cost entirely, delete the cluster.
