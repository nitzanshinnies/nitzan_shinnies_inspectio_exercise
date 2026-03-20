# LOCAL_S3.md — Local / in-process mock S3 provider

This document specifies the **file-backed mock S3** called for in [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) §1.3 and §7: an in-process implementation of the same **logical** object operations as the dedicated persistence service, for **local development** and **fast automated tests** without AWS or LocalStack.

**Aligns with:** [`persistence/interface.py`](../src/inspectio_exercise/persistence/interface.py) **`PersistencePort`**, S3 key layout in [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) §2, [`TESTS.md`](TESTS.md) §3 / §5.1.

---

## 1) Purpose and scope

**Purpose**

- Provide **`put_object` / `get_object` / `delete_object` / `list_prefix`** semantics keyed by **S3 object keys** (strings like `state/pending/shard-0/msg.json`).
- Store content as **files under a configurable root directory** so integration tests and local runs can inspect or wipe state without cloud credentials.

**In scope**

- Async **`PersistencePort`** implementation (or adapter used **inside** the persistence microservice when `USE_LOCAL_S3=1` or equivalent).
- Deterministic mapping **S3 key → relative file path**; **prefix listing** compatible with worker bootstrap (`list_prefix("state/pending/shard-7/")`).
- Clear **validation** rules (reject path traversal, reject empty keys where invalid).
- **Own test suite** (see §7): unit tests for the provider module; optional integration tests against the persistence HTTP surface once wired.

**Out of scope**

- **HTTP** surface of the persistence service (see persistence app — this doc is the **backend** behind it).
- **S3** features we do not use: ACLs, versioning, multipart uploads, bucket policies, cross-region replication.
- **Production** AWS S3 (use **aioboto3** in the real code path — separate implementation).

**Non-goals**

- Bit-for-bit compatibility with AWS edge cases (eventual consistency, 404 after delete races). Behavior should be **strongly consistent** in-process (single writer per key for tests unless documented otherwise).

### 1.1 Relationship to `tests/fakes.RecordingPersistence`

[`tests/fakes.py`](../tests/fakes.py) **`RecordingPersistence`** is already a **`PersistencePort`** fake: in-memory **`dict[str, bytes]`**, plus **spy lists** (`puts`, `gotten`, `deleted`, `listed`) for assertions.

| | **`RecordingPersistence`** | **Local S3 provider** (this doc) |
|---|-----------------------------|-----------------------------------|
| **Storage** | In-process dict | Files under `LOCAL_S3_ROOT` |
| **Package** | `tests/` only (test double) | `src/` (or behind persistence service) — usable for **local dev** and CI |
| **Spies** | Yes — explicit call recording | Optional; can add debug logging, not required for contract |
| **Semantics** | Same `PersistencePort` methods | Same — **list_prefix** sorted by `Key`, **`max_keys` = first N after sort** (§4.1), **KeyError** on missing get |

So: **same contract**, different **backing store** and **shipping location**. The file-backed provider is **not** a replacement for **`RecordingPersistence`** in tests that only need a spy — keep the fake for **lightweight** unit tests. Use **local S3** when you need **real paths**, **survival across restarts** (same root), or **integration** with the persistence HTTP layer talking to a real backend.

---

## 2) Interface contract

The provider **must** implement **`PersistencePort`**:

| Method | Expected behavior |
|--------|-------------------|
| `put_object(key, body, content_type=...)` | Create or overwrite object at `key`; create parent directories as needed. |
| `get_object(key)` | Return **bytes**; if missing, raise **`KeyError`** (match existing test/fake conventions). |
| `delete_object(key)` | Remove object if present; **idempotent** (no error if already absent). |
| `list_prefix(prefix, max_keys=None)` | Return **`[{"Key": str}, ...]`** sorted by **`Key`** ascending, only keys that **start with** `prefix`, then truncated to the first **`max_keys`** (see §4.1). If **`max_keys`** is set and **`< 1`**, **`ValueError`**. Same row shape as S3 list v2 style used in tests. |

**Key rules**

- Keys are **opaque** strings except: **no** leading `/`; use **`/`** as separator (match architect paths in plans).
- **Reject** keys containing **`..`** or **Windows reserved** segments if you support Windows; minimum bar: reject **`..`** and absolute paths.

---

## 3) On-disk layout

**Root:** configurable base directory `root` (e.g. `Path` from env `LOCAL_S3_ROOT` or a `tempfile.TemporaryDirectory` in tests).

**Mapping:** `key` → file path **`root / key`** with path segments split on **`/`** (use **`pathlib.Path`** so POSIX keys like `state/pending/...` map correctly on Windows dev machines).

**Example**

| S3 key | File path (POSIX) |
|--------|---------------------|
| `state/pending/shard-0/a.json` | `{root}/state/pending/shard-0/a.json` |

**Encoding:** store **`body`** as raw bytes (write in binary mode). **`content_type`** may be ignored on disk or stored in a sidecar **only if** tests require it — default: **ignore** for parity with “bytes only” contract.

---

## 4) Semantics and edge cases

### 4.1 `list_prefix`

- **Prefix match:** include key **`k`** iff **`k.startswith(prefix)`**.
- **Sort:** return rows sorted by **`Key`** lexicographically (stable ordering for deterministic tests).
- **`max_keys`:** **sort matching keys first**, then if **`len(keys) > max_keys`**, return only the **first** `max_keys` (lexicographic / S3-style cap). **Do not** cap before sort (that order is nondeterministic relative to key order).
- **`max_keys` invalid:** if **`max_keys` is not `None`** and **`max_keys < 1`**, raise **`ValueError`** (explicit; avoids ambiguous “return nothing” vs “ignore cap”).

### 4.2 `delete_object`

- Missing key: **no exception** (idempotent delete).

### 4.3 Concurrency

- **Tests:** assume **single-threaded async** or document **file locking** if workers hit the same root concurrently. Minimum for **CI:** sequential test processes each with **isolated** `root`.

### 4.4 Empty prefix

- **`prefix == ""`**: either **reject** (`ValueError`) or list **all** keys under `root` — **pick one** and test it (recommend **reject** empty prefix to avoid accidental full scans).

---

## 5) Wiring and configuration

- **Env / settings:** `LOCAL_S3_ROOT` (path), optional flag to select local vs AWS in persistence service factory.
- **Lifecycle:** on test teardown, delete `root` tree or use **`TemporaryDirectory`**.
- **Docker:** mount a volume at `LOCAL_S3_ROOT` if you run persistence in a container with local backend.

---

## 6) Relationship to persistence HTTP service

- The **persistence microservice** remains the **only** boundary for API/worker I/O in architecture.
- **Local S3 provider** lives **inside** (or behind) that service’s implementation: same **`/internal/v1/*`** routes, different backend.
- **Health:** **`GET /internal/v1/ready`** may return **200** when `root` is writable (local mode) vs **503** when AWS credentials missing (AWS mode).

---

## 7) Testing plan (local S3 provider)

**Goal:** prove the file-backed implementation matches **`PersistencePort`** as defined in **§2–§4** of this doc (canonical contract). [`tests/fakes.RecordingPersistence`](../tests/fakes.py) should stay aligned for shared semantics; add **filesystem-specific** checks (paths on disk, traversal rejection, idempotent delete removes the file).

**Where tests live:** e.g. `tests/unit/test_local_s3_provider.py` (or next to package per repo convention). **In addition** to [`TESTS.md`](TESTS.md) persistence integration tests — this section scopes **only** the local provider and optional **thin** persistence-stack checks.

### 7.1 Test levels

| Level | What it exercises | When |
|-------|-------------------|------|
| **Unit** | Provider class/module only: async methods against an **isolated** `root` (`tmp_path`) | **Always** — primary suite for this component |
| **Integration** | Persistence HTTP (or factory) + local backend + same `LOCAL_S3_ROOT` | After routes/factory wire local backend; proves **no drift** between HTTP and direct provider |

**Prefer** small, deterministic **unit** tests; integration tests should be **few** and focused on wiring, not re-proving every U-row.

### 7.2 Fixtures and isolation

- **`tmp_path` / `tmp_path_factory`:** each test (or class) gets a **fresh** directory tree — no shared mutable disk state between tests.
- **`pytest-asyncio`:** project uses **`asyncio_mode = auto`** in [`pyproject.toml`](../pyproject.toml) — async tests run without extra config; keep **`@pytest.mark.asyncio`** where the suite already uses it for clarity.
- **No real AWS / LocalStack** for this component.
- **Concurrency:** default assumption is **sequential** tests; if two tests ever share a root (avoid), document ordering — normally **never** share `root` across parallel workers.

### 7.3 Contract matrix (unit) — required behaviors

These map 1:1 to **automated** unit cases; implement **red → green** against [`PersistencePort`](../src/inspectio_exercise/persistence/interface.py).

| ID | Behavior | Notes |
|----|----------|--------|
| **U1** | `put_object` then `get_object` returns **identical** `bytes` | Include non-UTF8 bytes (e.g. `\xff\x00`) to ensure binary write/read |
| **U2** | `get_object` on missing key → **`KeyError`** | Match `RecordingPersistence` / existing conventions |
| **U3** | `delete_object` then `get_object` → **`KeyError`** | Proves file removed, not just hidden |
| **U4** | `delete_object` on missing key → **no exception** | Idempotent |
| **U5** | `list_prefix` returns `[{"Key": str}, ...]` **sorted** by `Key` ascending; **`max_keys`** truncates **after** sort to first *N* | Align with §4.1 |
| **U6** | Prefix isolation: keys under `a/b/` not listed for prefix `a/c/` | Also cover `list_prefix("state/pending/shard-7/")`-style paths from [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) |
| **U7** | Reject unsafe keys: at minimum **`..`** in key; document any other rejects (empty key, leading `/`, absolute path) | Assert **consistent exception type** (e.g. `ValueError`) once chosen |
| **U8** | **`content_type`:** if no sidecar — assert **ignored** (second `put` with different type still returns same bytes); if sidecar added later — optional round-trip test | Keeps doc §3 “ignore by default” honest |

**Additional unit cases (recommended)**

| ID | Behavior |
|----|----------|
| **U9** | **Overwrite:** second `put_object` same key replaces bytes; `get_object` returns new body |
| **U10** | **Empty prefix** (§4.4): assert chosen behavior — **reject** with clear exception *or* list all keys — and test the opposite branch does not accidentally full-scan |
| **U11** | **`list_prefix` + `max_keys`:** total keys > `max_keys`; assert returned length and keys equal **lexicographic first** *N* after sort (not insertion/discovery order) |
| **U13** | **`max_keys < 1`:** raises **`ValueError`** (§4.1) |
| **U12** | **Nested directories:** `put` creates parent dirs; `list_prefix` only returns **files** / registered keys (not stray empty dirs if implementation skips them) |

### 7.4 Edge cases and failure modes (checklist)

Use this as a **review** list before calling the provider “done”; not every row needs its own test if covered by a broader case.

- **Path traversal:** `..`, absolute paths, Windows-style separators if you claim support — **must** fail safe (U7).
- **Key normalization:** if leading `/` is stripped vs rejected — **one** policy, **tested** (tie to U7).
- **Empty body:** `put_object(..., body=b"")` then `get` returns `b""`.
- **Very long key / deep nesting:** at least one smoke test if OS limits matter on CI.
- **Disk full / permission denied:** **optional** — unit tests usually skip unless you add explicit error translation; document “surfaces `OSError`” if so.

### 7.5 Integration tests (persistence service + local backend)

Run **after** the persistence service can select the local backend (env or factory).

| ID | Behavior |
|----|----------|
| **I1** | End-to-end: write via **service boundary** (HTTP or documented in-proc client), read again — bytes match; file exists under `LOCAL_S3_ROOT` if you assert path (optional). |
| **I2** | **Parity:** for the same `root`, `list_prefix` (or equivalent service call) **matches** direct provider listing for a small fixed set of keys — catches mapping bugs in the HTTP layer. |

Scope: **does not** replace worker/SMS flows — see [`TESTS.md`](TESTS.md) §5.1.

### 7.6 What not to duplicate

- **Domain** lifecycle and **reference_spec** scenarios — stay in their existing suites.
- **`RecordingPersistence`** tests — do not re-test **generic** `PersistencePort` consumers here unless a regression needs a **file-specific** duplicate.
- **Full** persistence integration matrix — belongs in [`TESTS.md`](TESTS.md); local provider tests stay **narrow**.

### 7.7 Done criteria (this component)

- **U1–U8** green (required). **U9–U12** green if you implement those cases on the branch. **U13** green when the provider enforces §4.1 (**`max_keys < 1` → `ValueError`**).
- **I1–I2** green once persistence wiring exists, or explicitly **skipped** with reason until then.
- No flaky disk assumptions (always isolated `tmp_path` unless testing explicit `LOCAL_S3_ROOT` integration).

---

## 8) Validation checklist

Before considering the local mock S3 “done” for the exercise:

1. **`PersistencePort`** fully implemented with async methods.
2. §7.7 done criteria satisfied (unit + integration as applicable) — **green** in CI.
3. Documented **`LOCAL_S3_ROOT`** (or equivalent) in **README** / compose for local runs.
4. No ad-hoc file I/O from API/worker packages — only through persistence boundary ([`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) §1.3).

---

## 9) References

- [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) §1.3, §7, §8 (testing bullets)
- [`TESTS.md`](TESTS.md) §3 (tooling), §5.1 (persistence integration)
- [`TEST_LIST.md`](TEST_LIST.md) (moto/file-backend row)
