# Kubernetes (EKS) deployment

Apply from the repo root:

```bash
kubectl apply -k deploy/kubernetes
```

## Required configuration

1. **Image** — `kustomization.yaml` sets `images.newTag` (or patch `REPLACE_WITH_APP_IMAGE` in manifests before apply). Build and push to your registry (e.g. ECR `linux/amd64` for x86 nodes).

2. **ConfigMap** `inspectio-config` — set **`INSPECTIO_INGEST_QUEUE_URL`** to your **SQS FIFO** queue URL (name must end with `.fifo`).

3. **Secret** `inspectio-secrets` — create from **`secrets.example.yaml`** (copy to a file not committed to git). Set at least:
   - **`INSPECTIO_S3_BUCKET`** — real bucket for journal/snapshots
   - **`INSPECTIO_REDIS_URL`** — e.g. `redis://redis.inspectio.svc.cluster.local:6379/0` if using in-cluster Redis
   - **`INSPECTIO_SMS_URL`** — e.g. `http://mock-sms.inspectio.svc.cluster.local:8080` if using in-cluster mock SMS

4. **AWS credentials** — prefer **IRSA**: create an IAM role with trust policy for `inspectio-app` in namespace `inspectio`, attach policies for **S3** (journal bucket) and **SQS** (ingest FIFO queue: `SendMessage`, `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes`). Set **`eks.amazonaws.com/role-arn`** on the ServiceAccount to that role and **omit** static `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the Secret. If you leave the placeholder `REPLACE_WITH_IRSA_ROLE_ARN`, static keys in the Secret are used instead (not recommended for production).

5. **`enableServiceLinks: false`** — pod specs disable Kubernetes service link env injection so names like `REDIS_PORT` do not collide with app configuration.

## SQS IAM (example)

Allow the task principal to use the ingest FIFO queue and (optionally) a matching FIFO dead-letter queue:

- `sqs:SendMessage`, `sqs:SendMessageBatch`
- `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes`

Scope **`Resource`** to the queue ARN(s).

## Multi-replica workers

The worker uses **logical shard ownership** (§16 range) and **SQS** `ChangeMessageVisibility(0)` for messages not owned by this pod. **`INSPECTIO_WORKER_REPLICAS` > 1** is only safe if handlers remain **idempotent** and ordering expectations per `MessageGroupId` are understood. The locked default remains **`INSPECTIO_WORKER_REPLICAS=1`**.

## Dead-letter queue

For this exercise environment, a FIFO DLQ **`inspectio-ingest-dlq.fifo`** uses **`maxReceiveCount: 5`** on the main **`inspectio-ingest.fifo`** queue. Re-create in another account with:

```bash
aws sqs create-queue --queue-name inspectio-ingest-dlq.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false --region us-east-1
# Then set-queue-attributes RedrivePolicy on the main queue (deadLetterTargetArn = DLQ ARN).
```

Application code does not reference the DLQ; failed messages surface in AWS after repeated receive failures.
