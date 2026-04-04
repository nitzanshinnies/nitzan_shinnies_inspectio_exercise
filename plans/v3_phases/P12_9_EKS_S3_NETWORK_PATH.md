# P12.9 — EKS ↔ S3 network path (Phase D checklist)

**Purpose:** Record the **data-plane path** from worker/writer pods to **S3** for **`nitzan-inspectio`** so architects can reason about latency, cost, and hardening (gateway endpoint, cross-region mistakes).

**Captured:** **2026-04-04** (AWS CLI against account hosting the exercise cluster). Re-run after VPC or endpoint changes.

---

## Cluster and bucket facts

| Item | Value |
|------|--------|
| EKS cluster | `nitzan-inspectio` |
| Cluster / CLI region | **`us-east-1`** |
| Cluster **VPC** | `vpc-0caf3ad198a12638f` |
| Persistence bucket (live ConfigMap) | `inspectio-a074c6e4-59b9-4dd5-ad86-3f5c1ef7c994` |
| Bucket **LocationConstraint** (`get-bucket-location`) | **`null`** → **US East (N. Virginia)** / *us-east-1* (legacy region encoding) |

**Conclusion:** Bucket and cluster are **same AWS region** (`us-east-1`). No cross-region S3 hop for this bucket.

---

## VPC endpoints

Command:

```bash
aws ec2 describe-vpc-endpoints --region us-east-1 \
  --filters "Name=vpc-id,Values=vpc-0caf3ad198a12638f"
```

**Result at capture time:** **No VPC endpoints** attached to this VPC (empty list).

Implication: **no S3 Gateway Endpoint** on the cluster VPC. Traffic from **private** subnets to **S3 public endpoints** typically leaves via **NAT gateway** (unless replaced by other routing).

---

## Route table sample (same VPC)

Observed routes included:

- **`0.0.0.0/0` → NAT** (`nat-040c5979dc616fd16`) on private-style route tables.
- **`0.0.0.0/0` → Internet Gateway** (`igw-051cb88dd8569bcda`) on at least one route table (public subnet pattern).

**Architectural note:** S3 **Gateway** endpoints are **free** and keep S3 traffic off the NAT for supported prefixes; absence here means **NAT bandwidth/charge** and **extra hop** for private pods talking to S3. Adding a gateway endpoint is a common cost/latency hygiene step (validate with network team + route tables).

---

## Follow-ups (optional)

1. Add **`com.amazonaws.us-east-1.s3` Gateway** endpoint to **`vpc-0caf3ad198a12638f`**, associate with **private** route tables used by worker/writer subnets, and re-measure **persistence writer** PUT p99 if needed.
2. Confirm **subnet → route table** mapping for **EKS node subnets** (ensures the above statement applies to pod egress).
3. If buckets ever move to **SSE-KMS**, add **VPC interface endpoints** for KMS where required by policy (separate from S3 gateway).

### Creating the S3 gateway endpoint (example CLI)

Replace **`vpc-0caf3ad198a12638f`** / **`rtb-…`** if your VPC differs. Associate the endpoint with **every private route table** that EKS **worker** subnets use.

```bash
REGION=us-east-1
VPC_ID=vpc-0caf3ad198a12638f
EP_ID=$(aws ec2 create-vpc-endpoint --region "$REGION" --vpc-id "$VPC_ID" \
  --service-name com.amazonaws.us-east-1.s3 \
  --vpc-endpoint-type Gateway \
  --query 'VpcEndpoint.VpcEndpointId' --output text)
# Repeat for each private route table used by node subnets:
aws ec2 modify-vpc-endpoint --region "$REGION" --vpc-endpoint-id "$EP_ID" \
  --add-route-table-ids rtb-07aa93f931078123a
```

Then re-run **`describe-vpc-endpoints`** and update the **“VPC endpoints”** section above.

---

*This document satisfies **`ARCHITECT_PLAN_PERSISTENCE_AND_PLATFORM.md` §5 Phase D** “documented network path” for the captured environment.*
