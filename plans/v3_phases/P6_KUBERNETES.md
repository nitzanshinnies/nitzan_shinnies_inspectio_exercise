# P6 — Kubernetes (v3 topology)

**Goal:** Root **`deploy/kubernetes/`** again: run L2, expander, workers, redis on **EKS** (or **ECS/EC2** — master traceability **AWS** row, section **0**). **LocalStack** is dev-only; AWS uses real **SQS**. **Optional** SNS/Lambda/DynamoDB **only** after human approves quotas (master **9**). Satisfies **AC6** with **P7** evidence (section **7.1**).

**Needs:** **P4** minimum. **P5** before **P6** per master phase table if the cluster should include **L1**; otherwise add **L1** in a follow-up deploy.

**Refs:** workspace **`inspectio-eks-agent-executes-deploy`**; master **P6** row, **4.8** (≥2 L2 replicas to validate Redis outcomes).

## Done when

- [x] Namespace, Services, Deployments (or StatefulSet for workers): **api** **replicas ≥ 2**, **expander** (1 replica unless P3 multi-replica dedupe), **worker(s)** aligned with **K** shards, **redis** (or **ElastiCache** endpoint via env—**9**).
- [x] **L1** Deployment if P5 produced a separate image.
- [x] ConfigMap for queue URLs, **K**, redis URL; **Secrets** or **IRSA** for AWS—no secrets in git.
- [x] **`deploy/kubernetes/README.md`**: apply order, **`kubectl set image`**, **`rollout status`**, immutable **selector** pitfalls (prefer patterns from workspace rules).
- [x] Probes: L2 **`/healthz`**; non-HTTP workers—**exec**/TCP or document none.

## Out of scope

HPA, Terraform (optional follow-ups).

**Next:** P7 Job + driver; image must include **`scripts/`** if driver lives there.
