# Plan D — EKS benchmark execution and artifact hygiene (AI SE)

## Purpose

Run a **repeatable, gate-comparable** persist-off / persist-on benchmark on **EKS** and produce a **complete evidence bundle**. **Operations and discipline**; no feature code unless fixing the **driver** or **hygiene script**.

## Preconditions

- **`kubectl`** context correct (e.g. `tzanshinnies@nitzan-inspectio.us-east-1.eksctl.io`); verify with `kubectl config current-context`.
- Namespace **`inspectio`**.
- **AWS CLI** credentials: **CloudWatch** metrics + **SQS** (queue attributes if used).
- Nodegroup **desired capacity > 0**: `eksctl get nodegroup --cluster nitzan-inspectio --region us-east-1`.
- **`export IMG=...`** matches the **tag every app Deployment uses** before starting Jobs (`kubectl -n inspectio get deploy -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'` — exclude **`redis`**).

## Canonical spec (normative)

Follow **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** for:

- ConfigMap toggle, recycle, Job command args, wait timeout (**≥920s** for 240s duration), hygiene CLI.

This plan adds **SE checklist**, **`iter-N` naming**, and **edge cases**.

## Invariants (invalidate results if violated)

1. **Same `IMG`** for **off Job**, **on Job**, and **all** non-redis Deployments during that **`iter-N`** run.
2. **Off leg before on leg** (persist emit **false** then **true**), each preceded by **full stack recycle** after CM patch.
3. **`off_start.txt` / `off_end.txt` / `on_start.txt` / `on_end.txt`** are **UTC** and bracket the Job runtime (hygiene uses them for CW windows).
4. Hygiene output **`measurement_valid: true`** before **PROMOTE** claims.

## Task D.1 — Preflight checklist

- [ ] **Nodes Ready** (`kubectl get nodes`).
- [ ] **Deployments Ready**: api, l1, expander, **worker shards 0–7**, **writer shards 0–7**, redis.
- [ ] **`inspectio-persistence-writer`** (non-shard) may be **0 replicas** by design — **do not** fail preflight; **shard** writers must be **1/1**.
- [ ] **`inspectio-v3-secrets`**: optional; absence is OK if workloads mount **`optional: true`**.
- [ ] **ConfigMap** contains target **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`** before each leg (patch + recycle).
- [ ] **Full stack recycle** after **every** ConfigMap change affecting behavior.

## Task D.2 — Artifact directory and Job names

1. Pick next free folder: **`plans/v3_phases/artifacts/p12_9/iter-N/`** (e.g. `iter-7`).
2. Set **`ART`** to that path in your shell for **all** commands.
3. **Job names must be unique** per iteration **or** delete previous Jobs: e.g. **`inspectio-v3-p12-9-iter7-off`** / **`inspectio-v3-p12-9-iter7-on`** (update YAML from spec’s `iter6` names).

## Task D.3 — Job manifest hardening (recommended)

Include in every Job:

- **`serviceAccountName: inspectio-app`**
- **`imagePullPolicy: Always`**

Document in **`ITERn_RESULTS.md`** if you **omit** these for an A/B control.

## Task D.4 — Execute off leg

1. **`INSPECTIO_V3_PERSIST_EMIT_ENABLED=false`** + recycle + rollouts complete.
2. `date -u` → **`off_start.txt`**.
3. Apply Job; **`kubectl wait --for=condition=complete`** timeout **≥920s**.
4. **`kubectl logs job/... --all-pods=true`** → **`off-allpods.log`**.
5. **`kubectl get job ... -o json`** → **`off_job_status.json`**.
6. `date -u` → **`off_end.txt`**.
7. Assert **`succeeded=1`**, **`failed=0`**.

## Task D.5 — Execute on leg

Repeat D.4 with **`true`**, **`on_*`** files, and **`on` Job name**.

## Task D.6 — Hygiene script

From repo root (adjust **`${ART}`**):

```bash
python scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir "${ART}" \
  --image "${IMG}" \
  --cluster-context "$(kubectl config current-context)" \
  --namespace inspectio \
  --region us-east-1 \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum
```

The script **writes** to **`${ART}`**: **`sustain_summaries.json`**, **`cw_metrics.json`**, **`measurement_manifest.json`** (see `scripts/v3_p12_9_iter3_rerun_hygiene.py` near `_write_json`).

## Task D.7 — Writer evidence

```bash
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##' | grep inspectio-persistence-writer); do
  kubectl -n inspectio logs deploy/${d} --since=45m > "${ART}/${d}.log" 2>/dev/null || true
done
if command -v rg >/dev/null; then
  rg "writer_snapshot" "${ART}"/inspectio-persistence-writer*.log > "${ART}/writer_snapshot_extract.json" || true
else
  grep "writer_snapshot" "${ART}"/inspectio-persistence-writer*.log > "${ART}/writer_snapshot_extract.json" || true
fi
```

**Note:** **`inspectio-persistence-writer.log`** may be **empty** at **0 replicas**; **shards** carry the evidence.

## Task D.8 — Results markdown

Write **`ITERn_RESULTS.md`** (copy structure from **`iter-6/ITER6_RESULTS.md`**): image, branch, config, admit table, CW table, **R** and **(R−44.84)**, hygiene validity, pipeline evidence, **PROMOTE/NO-GO**, rollback note.

## Task D.9 — Artifact completeness (parameterized)

Set **`ART`** and **`RESULTS`** (e.g. **`ITER7_RESULTS.md`**) to match your iteration:

```bash
export ART="plans/v3_phases/artifacts/p12_9/iter-7"
export RESULTS="ITER7_RESULTS.md"
python -c "
from pathlib import Path
import os, sys
art = Path(os.environ['ART'])
results = os.environ['RESULTS']
required = [
  'off_start.txt','off_end.txt','on_start.txt','on_end.txt',
  'off-allpods.log','on-allpods.log',
  'off_job_status.json','on_job_status.json',
  'sustain_summaries.json','cw_metrics.json','measurement_manifest.json',
  'writer_snapshot_extract.json', results,
]
missing = [p for p in required if not (art / p).exists()]
print({'missing': missing, 'ok': not missing})
sys.exit(1 if missing else 0)
"
```

## Task D.10 — Cost safety (optional)

```bash
eksctl scale nodegroup --cluster nitzan-inspectio --region us-east-1 --name ng-main --nodes 0 --nodes-min 0
```

Document in results if executed.

## Failure modes (SE triage)

| Symptom | Likely cause | Action |
|---------|----------------|--------|
| Job **`BackoffLimitExceeded`** | Driver exception, L1/L2 **5xx** | Read **`*-allpods.log`**; fix harness or scale cluster |
| **`measurement_valid: false`** | Bad timestamps, short CW window, queue list mismatch | Re-check **`off_*`/`on_*`** files; re-run hygiene; use script overrides **only** if spec allows |
| Hygiene **`datapoint_count_diff`** fail | Off/on window asymmetry | Ensure **240s** jobs + correct **start/end** files |
| **`transient_errors`** high | Load or connection pressure | Record in results; compare to prior **`iter-*`** |

## Definition of done

- **`iter-N/`** passes completeness check with correct **`ITERn_RESULTS.md`** name.
- Gates evaluated per **`P12_9_AI_SE_HANDOFF_INDEX.md`**.

## References

- **This repo:** `.cursor/rules/inspectio-testing-and-performance.mdc` (in-cluster load / timeout discipline).
- **Antigravity workspace (if mounted):** `../.cursor/rules/restart-containers-before-inspectio-tests.mdc`, `../.cursor/rules/inspectio-full-flow-load-test-aws-in-cluster.mdc`, `../.cursor/rules/inspectio-eks-agent-executes-deploy.mdc` (paths relative to `nitzan_shinnies_inspectio_exercise/`).
- `scripts/v3_sustained_admit.py`
- `plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md`
- `scripts/v3_p12_9_iter3_rerun_hygiene.py` — **`decision` field is gate 1 only**; compute gate 2 manually (see **`P12_9_AI_SE_HANDOFF_INDEX.md`**).
