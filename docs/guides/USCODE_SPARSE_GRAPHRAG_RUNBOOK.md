# US Code Sparse GraphRAG Operations Runbook (USCIR-037)

Operator runbook for building, querying, diagnosing, updating, and recovering
the sealed US Code sparse GraphRAG release (`publicus-ir-graphrag/v2`).

Companion documents:

| Document | Purpose |
|---|---|
| [USCODE_SPARSE_GRAPHRAG_MIGRATION.md](USCODE_SPARSE_GRAPHRAG_MIGRATION.md) | Legacy layout → v2 client migration, config mapping, rollback targets |
| [USCODE_SPARSE_QUERY_CLI.md](USCODE_SPARSE_QUERY_CLI.md) | Query CLI subcommand reference |
| [uscode_dataset_card.md](../../tests/fixtures/legal_ir/uscode_dataset_card.md) | Sealed dataset card / viewer configs |
| [USCODE_SPARSE_GRAPHRAG_PLAN.md](../architecture/USCODE_SPARSE_GRAPHRAG_PLAN.md) | Program plan (read-only control plane) |

All operator commands in this runbook default to **offline fixture or dry-run
modes**. They never embed credentials, never mutate production, and never
require a live Hub token.

---

## 1. Scope and non-goals

### In scope

- Fixture builds and offline query against a local release root
- Sparse-fetch diagnosis from credential-safe `fetch_trace` output
- Staging dry-run planning and rollback rehearsal against prior advertised pins
- Resource sizing guidance for fixture vs full-title work
- Exact release provenance and legal-currentness caveats

### Out of scope (fail closed)

- Public mutation of `justicedao/ipfs_uscode` on `main` / `master`
- Deletion, force-push, visibility change, or credential rotation
- Inferring Hugging Face publication authority from token presence
- Treating acquisition or publication timestamps as wall-clock legal currentness

Publication requires a separate human seal (USCIR-040). Implementation lanes may
only build, validate, stage under explicit non-production authorization,
redownload, canary, and prepare a seal request.

---

## 2. Sealed coordinates

| Coordinate | Value |
|---|---|
| Dataset repository | `justicedao/ipfs_uscode` |
| Pinned baseline revision | `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8` |
| Official release point | `us/pl/118/45` |
| Edition | `olrc-us-pl-118-45` |
| Release profile | `publicus-ir-graphrag/v2` |
| Default primary key | `entry_cid` |
| Staging branch (non-production) | `stage/uscode-sparse-graphrag-v2` |
| Task | `USCIR-037` |
| Goal | `USCIR-G100` |

Mutable revisions (`main`, `master`, `latest`, empty) are rejected for live Hub
use. Always pin a 40-hex commit SHA.

---

## 3. Prerequisites

```bash
# From the repository root
export REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Python 3.12+ with the package importable (editable install or PYTHONPATH)
python -c "import ipfs_datasets_py; print('ok')"
```

Optional environment (never pass as CLI flags):

| Variable | Use |
|---|---|
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | Live Hub read only when an operator opts into network canaries |
| `USCODE_STAGING_AUTHORIZATION` | Required with `--authorize-mutation` for staging opt-in (still no production publish) |

Secrets must never appear in argv, prompts, logs, manifests, or fetch traces.
CLI entry points reject token-like command-line values.

---

## 4. Resource sizing

Performance numbers are **reference machine guidance**, not universal SLOs.
Record actual p50/p95 latency, bytes fetched, cache hit ratio, shards, peak
memory, and build throughput in evaluation receipts.

| Workload | Titles | Disk (approx) | Memory class | Network |
|---|---|---|---|---|
| Fixture plan / validation-only | 1–2 | < 50 MB scratch | `cpu-small` | none |
| Fixture sealed build | 1–2 | < 200 MB | `memory-medium` | none |
| Full title rebuild (production planner) | ≤ 53 | multi-GB working set; baseline repo ~1.0 GB | `memory-large` | source acquisition only when authorized |
| Offline query (local root) | n/a | release tree + optional cache | `cpu-small` | none |
| Sparse remote query (pinned revision) | n/a | control plane + routed shards only | `network-bounded` | bounded by `--max-bytes` / `--max-shards` |

Default CLI resource caps for builds:

- `--max-titles 53`
- `--max-work-units 512`
- `--resource-class memory-large`

Default query budgets (override as needed):

- `--max-bytes 50000000`
- `--max-shards 64`
- `--max-rows 50000`
- `--max-nodes 256`
- `--max-edges 1024`
- `--max-depth 8`
- `--max-time-ms 60000`

Remote queries must download **control-plane indexes plus routed shards only**.
A full-repository clone is never required for sparse GraphRAG query.

---

## 5. Build fixtures (offline)

Resumable full/delta orchestration lives in
`scripts/ops/legal_data/build_uscode_sparse_graphrag.py` (USCIR-030).

### 5.1 Plan only (no writes)

```bash
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --plan-only \
  --titles 1,35 \
  --mode full \
  --json
```

Expect JSON with `plan.build_id`, `plan.config_digest`, `plan.unit_count`, and
`task_id` = `USCIR-030`.

### 5.2 Validation-only (dry-run producers)

```bash
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --validation-only \
  --titles 1,35 \
  --mode full \
  --json
```

Validation-only never seals partial output. Global BM25/cluster rebuild
decisions remain explicit via `--bm25-rebuild` / `--cluster-rebuild`
(`auto|full_rebuild|delta_refresh|unchanged`).

### 5.3 Sealed fixture build with resume

```bash
OUT="${TMPDIR:-/tmp}/uscode-fixture-build"
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --output-dir "$OUT" \
  --titles 1,35 \
  --mode full \
  --json

# After interrupt, resume without duplicating verified work units:
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --output-dir "$OUT" \
  --titles 1,35 \
  --mode full \
  --resume \
  --json
```

Stale or config-mismatched checkpoints fail closed. Partial trees cannot be
sealed.

### 5.4 Delta planning

```bash
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --plan-only \
  --mode delta \
  --titles 1,35 \
  --current-salt fixture \
  --prior-salt prior-fixture \
  --json
```

---

## 6. Query fixtures (offline)

Query CLI: `scripts/ops/legal_data/query_uscode_hf.py` (USCIR-028).
See also [USCODE_SPARSE_QUERY_CLI.md](USCODE_SPARSE_QUERY_CLI.md).

### 6.1 Offline BM25 against a local release root

```bash
# LOCAL_ROOT must be a validated release tree (manifest + descriptors + shards).
# In CI/tests, materialize via the sealed mini-release builders.
python scripts/ops/legal_data/query_uscode_hf.py \
  --local-root "$LOCAL_ROOT" \
  --revision 75cfc5982dc3a6808614cd4eb9b4238f8f9308b8 \
  --fixture-mode \
  --json \
  --trace \
  bm25 "5 U.S.C. § 552" \
  --top-k 5
```

`--local-root` uses `LocalRootTransport` (no network). `--fixture-mode` keeps
optional accelerators offline.

### 6.2 Other subcommands

| Command | Purpose |
|---|---|
| `bm25` | Field-weighted sparse search |
| `vector` | Centroid-routed dense search |
| `hybrid` | Weighted or RRF fusion of BM25 + vector |
| `neighbors` | Bounded adjacency neighbors |
| `graph-walk` | Structural BFS walk |
| `semantic-graph-walk` | Embedding-guided beam walk |

Shared legal filters: `--title`, `--section`, `--citation`, `--version`,
`--legal-id`.

### 6.3 Live Hub (operator only)

```bash
# Requires network + immutable 40-hex revision. Mutable pins fail closed.
python scripts/ops/legal_data/query_uscode_hf.py \
  --repo-id justicedao/ipfs_uscode \
  --revision 75cfc5982dc3a6808614cd4eb9b4238f8f9308b8 \
  --json --trace \
  bm25 "foia agency records" \
  --top-k 5 \
  --max-bytes 50000000 \
  --max-shards 64
```

Do not pass `HF_TOKEN` on the command line. Export it in the environment if the
Hub requires authentication for private staging mirrors.

---

## 7. Diagnose sparse fetches

Every successful query with `--trace` / `--json` can emit a credential-safe
`fetch_trace`. Use it to prove sparse routing and to triage over-fetch.

### 7.1 What a healthy trace contains

| Field | Healthy expectation |
|---|---|
| `repo_id` | `justicedao/ipfs_uscode` (or local equivalent) |
| `revision` | Immutable 40-hex pin |
| `route_justified` | `true` — every file has a route reason |
| `verification_state` | `verified` |
| `total_file_bytes` | Within `--max-bytes` |
| `file_count` / `files[]` | Control plane + **routed** shards only |
| `cache_hits` | Increases on repeat query against warm cache |
| `budget_usage` | Below configured limits |
| `stop_reason` | Normal completion (not silent truncation) |

Paths in the trace are **relative**. Absolute local paths, tokens, and
authorization headers must never appear.

### 7.2 Diagnostic workflow

```bash
# 1) Run once cold with JSON + trace
python scripts/ops/legal_data/query_uscode_hf.py \
  --local-root "$LOCAL_ROOT" \
  --revision 75cfc5982dc3a6808614cd4eb9b4238f8f9308b8 \
  --fixture-mode \
  --json --trace \
  bm25 "agency" --top-k 3 \
  > /tmp/uscode-query-1.json

# 2) Inspect routed paths and byte totals (example with python)
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/uscode-query-1.json").read_text())
trace = payload.get("fetch_trace") or payload
files = trace.get("files") or []
print("revision:", trace.get("revision"))
print("route_justified:", trace.get("route_justified"))
print("verification_state:", trace.get("verification_state"))
print("total_file_bytes:", trace.get("total_file_bytes"))
print("file_count:", trace.get("file_count"))
for f in files:
    print(f"  {f.get('relative_path')} route={f.get('route')} verified={f.get('verified')} bytes={f.get('size_bytes')}")
PY

# 3) Repeat to confirm cache hits rise without new unjustified paths
python scripts/ops/legal_data/query_uscode_hf.py \
  --local-root "$LOCAL_ROOT" \
  --revision 75cfc5982dc3a6808614cd4eb9b4238f8f9308b8 \
  --fixture-mode \
  --json --trace \
  bm25 "agency" --top-k 3 \
  > /tmp/uscode-query-2.json
```

### 7.3 Failure triage matrix

| Symptom | Likely cause | Action |
|---|---|---|
| `MutableRevisionError` / refused `main` | Mutable pin | Re-pin 40-hex SHA |
| Digest / size mismatch | Tamper or wrong revision | Fail closed; redownload from pin; do not soft-warn |
| Budget exhausted (`max-bytes` / `max-shards`) | Route explosion or budget too tight | Inspect `files[]` routes; raise budget only with justification |
| `route_justified=false` | Unjustified path fetch | Treat as security incident; reject result |
| Empty hits on known gold citation | Wrong config, filter, or release point | Check `--title` / release point; compare gold fixtures |
| Absolute path or token in output | Redaction failure | Abort; never paste logs into tickets with secrets |
| Viewer schema errors | Recovery JSON mixed into default config | Ensure default config is `publicus-ir-graphrag/v2` only |

Offline unit tests never enable network. Marked remote canaries
(`canary_uscode_hf_release.py`, USCIR-036) are opt-in and still require an
immutable staging revision.

---

## 8. Stage dry-run and rollback rehearsal

Staging planner: `scripts/ops/legal_data/stage_uscode_sparse_graphrag.py`
(USCIR-032). Default behavior is **offline dry-run**.

### 8.1 Fixture dry-run (credential-free)

```bash
python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py \
  --fixture-only \
  --dry-run
```

Expect a redacted receipt with:

- `status` = `dry_run_only`
- `dry_run` = `true`
- `live_network` = `false`
- `mutation_executed` = `false`
- `remote_write_contacted` = `false`
- `target_repo` = `justicedao/ipfs_uscode`
- `staging_branch` = `stage/uscode-sparse-graphrag-v2`
- `base_revision` = `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`
- `operations` = `["add_only_upload"]`
- non-empty `plan_digest` and `manifest_digest`
- no `hf_token` / bearer material in JSON

### 8.2 Check sealed stage-plan fixture

```bash
python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py \
  --fixture-only \
  --check
```

Compares `tests/fixtures/legal_ir/uscode_stage_plan.json` to a fresh fixture
plan.

### 8.3 Rollback rehearsal procedure

Rollback restores the **prior advertised revision/config mapping**. It does
**not** delete legacy data, force-push history, or remove failed candidate
artifacts.

Rehearsal checklist (fixture / dry-run):

1. Record current advertised pin (production baseline):
   - revision `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`
   - default config `publicus-ir-graphrag/v2`
2. Produce candidate staging plan (section 8.1) and capture `manifest_digest`,
   `plan_digest`, and staging branch name.
3. Confirm forbidden operations are impossible: `delete`, `force_push`,
   `visibility_change` appear in the plan’s forbidden set; only
   `add_only_upload` is scheduled.
4. Simulate rollback target selection:
   - **promotion path** → keep staging branch pin as candidate for human seal
   - **rollback path** → re-advertise the prior baseline revision and default
     config without deleting the failed candidate tree
5. Re-query the rollback target offline (section 6) and confirm hits + fetch
   traces still verify.
6. Record both digests and the rollback target in the release-candidate receipt
   (USCIR-038 / USCIR-039 handoff). Do not publish.

Operator invariant:

> Rollback rehearsal restores the prior advertised revision/config mapping
> without deleting legacy data.

Full handoff automation is owned by `rehearse_uscode_release_handoff.py`
(USCIR-039). Until that script is present, the dry-run staging receipt plus
offline re-query above is the authoritative local rehearsal.

---

## 9. Update and recovery workflow

### 9.1 Incremental update

1. Resolve and approve an official release point (exact pin, not `latest`).
2. Diff stable `legal_id` / content hashes; plan full vs delta rebuild
   (`build_uscode_sparse_graphrag.py --mode delta|full`).
3. Explicitly choose global BM25 and cluster decisions.
4. Build with atomic per-title / per-family checkpoints.
5. Package HF release (`uscode_hf_release` builders; never delete legacy paths).
6. Stage dry-run; canary; assemble release-candidate receipt.
7. Stop at the human publication-seal gate.

### 9.2 Recovery quarantine

Recovery JSON is **not** part of canonical corpus/BM25/vector/graph counts.
It is advertised only under config `recovery-quarantine/v1` and remains outside
the default Dataset Viewer schema until rows are normalized and admitted with
full provenance (`admission_status`, `source_cid`, `release_point`,
`source_checksum`, `verification_result`, `acquisition_time`).

Never promote recovery rows by soft-warning missing admission fields.

---

## 10. Exact release provenance

Every admitted row and every sealed candidate must bind:

| Field | Meaning |
|---|---|
| `release_point` | Exact official package pin (e.g. `us/pl/118/45`) |
| `source_revision` / Hub revision | Immutable dataset commit |
| `entry_cid` | Content-addressed primary key for v2 |
| `legal_id` | Durable statutory identity |
| `source_cid` / `source_checksum` | Upstream artifact identity |
| `admission_status` / `admission_reason` | Admitted, replaced, or excluded |
| `acquisition_time` | When the package was retrieved (not legal currentness) |
| `manifest_digest` | Sealed candidate integrity |

Mixed official vintages must not masquerade as one current Code. Per-title
receipts and fail-closed admission enforce this.

---

## 11. Legal caveats: publication date vs legal currentness

**Critical operator distinction:**

| Concept | What it is | What it is not |
|---|---|---|
| **Publication date** | When a Hub revision or local candidate was sealed/uploaded | Proof the text is the law “today” |
| **Acquisition time** | When the official package was fetched | A live codification guarantee |
| **Release point / edition** | Exact official OLRC (or approved) package identity bound into the corpus | Automatically the latest Congress/session |
| **Legal currentness** | Whether the provision is operative law for a fact pattern at a wall-clock moment | Something this retrieval system asserts |

Rules operators must follow:

1. Acquisition and publication timestamps are **not** legal-currentness claims.
2. Time-sensitive answers must expose the **release point** and **edition**, not
   only a Hub `last_modified` stamp.
3. Retrieval output is a **research aid**, not a substitute for the official
   U.S. Code source (House Office of the Law Revision Counsel).
4. Individualized “what is the law for my case today” questions may require
   **abstention** rather than a forced exact hit.
5. Historical/version-ambiguous queries must surface version metadata; never
   collapse mixed vintages into a single unlabeled “current” answer.

Gold-set policy and label taxonomy:
`docs/reports/uscode_goldset_rationale.md`.

---

## 12. Evaluation and security smoke (fixture)

```bash
# Family evaluators (offline gold)
python scripts/ops/legal_data/evaluate_uscode_bm25.py --fixture-only --check
python scripts/ops/legal_data/evaluate_uscode_vectors.py --fixture-only --check
python scripts/ops/legal_data/evaluate_uscode_graph.py --fixture-only --check

# Security suite (tamper / budgets / redaction)
python -m pytest tests/security/test_uscode_hf_release.py -q

# Local E2E pipeline proof
python -m pytest tests/integration/legal_data/test_uscode_sparse_graphrag.py -q
```

---

## 13. Publication boundary checklist

Before any human is asked to seal production:

- [ ] Fixture build + query succeed offline
- [ ] Fetch traces show only routed shards + verified digests
- [ ] Staging dry-run receipt is redacted and add-only
- [ ] Rollback target (prior revision + default config) is named
- [ ] Evaluation, security, determinism, and viewer gates pass
- [ ] Release-candidate receipt binds all digests (USCIR-038)
- [ ] Publication seal is pending or approved by a human (USCIR-040)
- [ ] No agent treats `HF_TOKEN` as publication authority

---

## 14. Quick command index

| Goal | Command |
|---|---|
| Plan fixture build | `python scripts/ops/legal_data/build_uscode_sparse_graphrag.py --fixture-only --plan-only --titles 1,35 --json` |
| Validate fixture build | `python scripts/ops/legal_data/build_uscode_sparse_graphrag.py --fixture-only --validation-only --titles 1,35 --json` |
| Query offline + trace | `python scripts/ops/legal_data/query_uscode_hf.py --local-root PATH --fixture-mode --json --trace bm25 "query"` |
| Stage dry-run | `python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py --fixture-only --dry-run` |
| Check stage plan fixture | `python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py --fixture-only --check` |
| BM25 gold check | `python scripts/ops/legal_data/evaluate_uscode_bm25.py --fixture-only --check` |

Validate this runbook:

```bash
python -m pytest tests/unit/docs/test_uscode_sparse_runbook.py -q
```
