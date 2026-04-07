# Iter4 DynamoDB + S3 WAL — EKS performance (2026-04-06)

## Stack

- **Branch / image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:iter4-wal-20260406131256`
- **API:** `Deployment` + `Service` `inspectio-v3-iter4-api:8000` (`deploy/kubernetes/iter4-api-deployment.yaml`)
- **DynamoDB:** `sms_messages` (PK `messageId`, GSI `SchedulingIndex`)
- **S3 WAL:** `s3://inspectio-a074c6e4-59b9-4dd5-ad86-3f5c1ef7c994/state/iter4_wal/<writer_id>/<ts>.jsonl`
- **Driver (in-cluster Job):** `scripts/v4_iter4_sustained_new_message.py` (`deploy/kubernetes/load-test-job-iter4-wal.yaml`)

## IAM

Pods use IRSA role **`eksctl-inspectio-v3-app`**. Initial load run failed with **`AccessDeniedException`** on `dynamodb:GetItem`.  
**Fix applied:** inline policy **`InspectioIter4DynamoWal20260406`** on that role — `GetItem` / `PutItem` / `UpdateItem` / `Query` / `BatchWriteItem` on `table/sms_messages` + indexes, and `s3:PutObject` on `state/iter4_wal/*`.

## Load shape

| Parameter | Value |
|-----------|--------|
| Duration | **90 s** |
| Concurrent senders | **80** |
| Request | `POST /messages` with unique `messageId`, empty `payload` |
| Replicas (API) | **3** |

## Result (driver)

```
ITER4_WAL_SUSTAIN_SUMMARY accepted_total=19008 duration_sec=90.0 offered_new_message_rps=211.20 concurrency=80 transient_errors=0
```

- **Accepted new messages:** **19,008**
- **Offered throughput:** **~211** successful `POST /messages` / s (aggregate across 3 API pods)
- **Transient errors:** **0** (after IAM fix)

## Comparison note

This is **not** comparable to P12.9 **R** (SQS `NumberOfMessagesDeleted`): Iter4 does **not** use the v3 send queues. It is **per-message** DynamoDB + optional immediate send + asynchronous S3 WAL flush.

## Artifacts / manifests

- `deploy/kubernetes/iter4-api-deployment.yaml`
- `deploy/kubernetes/load-test-job-iter4-wal.yaml`
- `scripts/v4_iter4_sustained_new_message.py`
