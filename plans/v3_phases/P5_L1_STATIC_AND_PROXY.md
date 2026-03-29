# P5 — L1 static + proxy to L2

**Goal:** Master plan **L1**: one deployable serves **static** UI; **all** browser API calls go **L1 → L2** (CORS/TLS at L1); **one** **`POST /messages/repeat?count=N`** from the page (coalescing, master plan **2** and **L1** bullets).

**Needs:** P4 (L2 + outcomes working).

**Refs:** PDF optional UI.

## Done when

- [ ] Static assets + **nginx** **or** **FastAPI** static + reverse proxy to **`INSPECTIO_L2_BASE_URL`** (internal **Service** URL in compose/k8s).
- [ ] Demo UI: send once + repeat N via **single** **`fetch`** for repeat.
- [ ] Compose/README: browser uses **L1 port only**, not raw L2.
- [ ] Light **integration** tests: GET `/` HTML; POST via L1 proxy → **202** from L2.

## Out of scope

Auth, CDN, rate limits (unless ASSIGNMENT requires).

**Next:** P6 packages **L1** + L2 + workers for cluster.
