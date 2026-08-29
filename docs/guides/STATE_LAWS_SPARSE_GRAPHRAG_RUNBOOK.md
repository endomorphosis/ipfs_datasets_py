# State Laws Sparse GraphRAG Operations Runbook (LCR-045)

Operator runbook for building, scraping, resuming, querying, monitoring,
refilling, publishing, updating, and rolling back the sealed state-law sparse
GraphRAG release (`state-laws-ir-graphrag/v2`) on `justicedao/ipfs_state_laws`.

Companion documents:

| Document | Purpose |
|---|---|
| [STATE_LAWS_SPARSE_GRAPHRAG_MIGRATION.md](STATE_LAWS_SPARSE_GRAPHRAG_MIGRATION.md) | Legacy layout → v2 client migration, explicit config map, dual-pin query, rollback targets |
| [IR_FAMILY_OPERATIONS.md](IR_FAMILY_OPERATIONS.md) | Shared IR-family operator conventions |
| [legal_corpora_reindex README](../../scripts/ops/legal_corpora_reindex/README.md) | Four-lane board preflight, launch, and health |

Receipt checks and rehearsals in this runbook are read-only. Planning is a
dry-run unless an operator supplies every explicit live flag, two distinct
staging approvals where required, and environment-only credentials. A missing
live receipt is a failed prerequisite; no command fabricates or refreshes one
during `--check`. Publication remains a separate human-sealed additive upload
(LCR-042).

Rollback rehearsal (this task):

```bash
python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check
```

That command is credential-free, contacts no Hub, does not change public
advertisement, and does not delete remote artifacts.

---

## 1. Scope and non-goals

### In scope

- Fixture / receipt-check builds, scrapes, resumes, and offline queries
- Dual-pin query of the **new public SHA** and the **previous public pin**
- Explicit legacy Dataset Viewer configuration (`legacy-state-laws-parquet/v1`)
- Bounded, recoverable rollback (re-advertise a prior immutable pin)
- Board diagnosis for **blocked**, **idle**, and **stale** lanes
- Resource sizing, exact release provenance, and legal-currentness caveats

### Out of scope (fail closed)

- Public mutation of `justicedao/ipfs_state_laws` on `main` / `master`
- Deletion, force-push, history rewrite, visibility change, or credential rotation
- Inferring Hugging Face publication authority from token presence
- Treating acquisition or publication timestamps as wall-clock legal currentness
- Promoting a subset combined Parquet or an Iowa-only Viewer as “all 51”

Publication requires the LCR-072 prepublication seal, the LCR-074
`state_main` gate, and a human-authorized additive upload. Implementation lanes
may only build, validate, stage under explicit non-production authorization,
redownload, canary, and rehearse rollback.

---

## 2. Sealed coordinates

| Coordinate | Value |
|---|---|
| Dataset repository | `justicedao/ipfs_state_laws` |
| Previous public pin (rollback target) | `42f0546acc7c6cd55627eaf51fb820d5613b9021` |
| New public pin (current advertisement) | Read `public_revision` from the checked LCR-042 receipt |
| Staging revision | Read `staging_revision` from the checked LCR-041 canary |
| Staging branch (non-production) | `stage/state-laws-sparse-graphrag-v2` |
| Public branch | `main` (never pass as a live query revision) |
| Official release point | `state-laws/v2/2026-08-10` |
| Release profile / default Viewer config | `state-laws-ir-graphrag/v2` |
| Legacy Viewer config | `legacy-state-laws-parquet/v1` |
| Recovery Viewer config | `recovery-quarantine/v1` |
| Default primary key (v2) | `entry_cid` |
| Legacy primary key | `ipfs_cid` |
| Exact jurisdiction set | 50 postal state codes + `DC` (51) |
| Embedding model | `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd` |
| Task | `LCR-045` |
| Goal | `LCR-G090` |

Mutable revisions (`main`, `master`, `latest`, empty) are rejected for live Hub
use. Always pin a 40-hex commit SHA. Both the new pin and the previous pin
remain independently queryable; rollback only moves the advertised pointer.

Producer receipts this runbook binds (read-only inputs):

| Receipt | Path | Role |
|---|---|---|
| Publication | `docs/reports/legal_corpora_reindex/publication_receipt.json` | New public SHA + previous pin |
| Public canary | `docs/reports/legal_corpora_reindex/public_canary.json` | New-pin query / Viewer proof |
| Baseline | `docs/reports/legal_corpora_reindex/baseline.json` | Previous-pin inventory |
| Rollback rehearsal | `docs/reports/legal_corpora_reindex/rollback_rehearsal.json` | Dual-pin + rollback contract |

---

## 3. Prerequisites

```bash
# From the repository root
export REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Python 3.12+ with the package importable (editable install or PYTHONPATH)
python -c "import ipfs_datasets_py; print('ok')"
```

After the corresponding checks pass, set `STATE_LAWS_PUBLIC_SHA` and
`STATE_LAWS_STAGING_SHA` to the exact 40-hex values in those receipts. Never
substitute `main`, `latest`, or an unverified operator-supplied revision.

Optional environment (never pass as CLI flags):

| Variable | Use |
|---|---|
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | Live Hub **read** only when an operator opts into network canaries |
| `STATE_LAWS_STAGING_AUTHORIZATION` | Required with `--authorize-mutation` for staging opt-in |
| `STATE_LAWS_PUBLICATION_AUTHORIZATION` | Required for authorized additive main upload (not this rehearsal) |

Secrets must never appear in argv, prompts, logs, manifests, fetch traces, or
Git. CLI entry points reject token-like command-line values.

---

## 4. Resource sizing

Performance numbers are **reference machine guidance**, not universal SLOs.
Record actual p50/p95 latency, bytes fetched, cache hit ratio, shards, peak
memory, and build throughput in evaluation receipts.

| Workload | Scope | Disk (approx) | Memory class | Network |
|---|---|---|---|---|
| Fixture plan / validation-only | 1–4 jurisdictions or receipt check | < 50 MB scratch | `cpu-small` | none |
| Cohort fixture scrape | one sealed cohort (A–M) | < 200 MB isolated root | `cpu-small` | none in `--fixture-only` |
| Full 51-jurisdiction local build | exact 51 including DC | multi-GB working set | `memory-large` | source acquisition only when authorized |
| Offline query (local root) | n/a | release tree + optional cache | `cpu-small` | none |
| Sparse remote query (pinned revision) | n/a | control plane + routed shards only | `network-bounded` | bounded by `--max-bytes` / `--max-shards` |
| Rollback rehearsal `--check` | both pins, docs, board cases | none beyond the repo | `cpu-small` | none |

Default query budgets (override as needed):

- `--max-bytes 50000000`
- `--max-shards 64`
- `--max-rows 50000`
- `--max-nodes 256`
- `--max-edges 1024`
- `--max-depth 8`
- `--max-time-ms 60000`

Physical artifact bounds remain 4,096 rows/pointers per shard (centroid rows
≤ 8,192 / two shards). Remote queries must download **control-plane indexes
plus routed shards only**. A full-repository clone is never required for
sparse GraphRAG query.

---

## 5. Build fixtures (offline)

Resumable local orchestration lives in
`scripts/ops/legal_data/build_state_laws_sparse_graphrag.py` (LCR-038 / LCR-100).

### 5.1 Admission self-check (no writes)

```bash
python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py \
  --validation-only \
  --check
```

Validation-only never seals partial output and never writes checkpoints.

### 5.2 Full 51-jurisdiction local build self-check

```bash
python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py \
  --full \
  --check
```

`--full --check` binds every input digest, required family, model/tool
revision, and local retrieval canary, then compares the sealed E2E receipt
`docs/reports/legal_corpora_reindex/local_e2e.json`. Partial checkpoints
cannot promote.

### 5.3 HF package (legacy retained)

Packaging (`ipfs_datasets_py.processors.legal_data.state_laws_hf_release`)
emits compact `manifest.json` + `release_metadata.json`, explicit Viewer
configs (default v2, **named** legacy, recovery quarantine), descriptors,
and admission / quality / reproducibility reports.

Packaging **never deletes** `STATE-*.parquet` or `state_laws.parquet`.
Migration is additive.

---

## 6. Scrape and resume

Resumable isolated cohort runner: `scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py`
(LCR-007).

### 6.1 Fixture scrape (one cohort)

```bash
python scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py \
  --fixture-only \
  --cohort A \
  --check
```

Cohorts A–L are four jurisdictions each; cohort M is `WI`, `WY`, `DC`.
Each cohort uses an isolated output/checkpoint root. A cohort with a failed
jurisdiction does not report success.

### 6.2 Resume after interrupt

Re-invoke the same cohort command against the same isolated root. The runner
replays durable per-state checkpoints and refuses stale or config-mismatched
work. Do **not** reuse the unsafe skip-completed baseline and do **not**
write a subset combined release.

Certify a finished cohort:

```bash
python scripts/ops/legal_data/certify_state_laws_cohort.py --check
```

`refresh_state_laws_corpus.py` is a hardened legacy entry point. Treat
filename presence as **not** completion. Prefer the cohort runner +
completeness oracle.

---

## 7. Query fixtures and dual-pin query

Query CLI: `scripts/ops/legal_data/query_state_laws_hf.py` (LCR-034).

### 7.1 Offline BM25 against a local release root

```bash
python scripts/ops/legal_data/query_state_laws_hf.py \
  --local-root "$LOCAL_ROOT" \
  --revision "$STATE_LAWS_PUBLIC_SHA" \
  --fixture-mode \
  --json \
  --trace \
  bm25 "disclosure" \
  --top-k 5 \
  --jurisdiction DC
```

`--local-root` uses `LocalRootTransport` (no network). `--fixture-mode` keeps
optional accelerators offline.

### 7.2 Both pins remain queryable

The previous pin is not deleted when the new pin is advertised. Query each
revision independently:

```bash
# New public pin (current advertisement; default Viewer is v2 / all 51)
python scripts/ops/legal_data/query_state_laws_hf.py \
  --repo-id justicedao/ipfs_state_laws \
  --revision "$STATE_LAWS_PUBLIC_SHA" \
  --json --trace \
  bm25 "disclosure" --top-k 5 --jurisdiction DC

# Previous public pin (rollback target; still independently queryable)
python scripts/ops/legal_data/query_state_laws_hf.py \
  --repo-id justicedao/ipfs_state_laws \
  --revision 42f0546acc7c6cd55627eaf51fb820d5613b9021 \
  --json --trace \
  bm25 "disclosure" --top-k 5
```

Do not pass `revision=main` or `revision=latest`. Do not pass `HF_TOKEN` on
the command line.

### 7.3 Other subcommands

| Command | Purpose |
|---|---|
| `bm25` | Field-weighted sparse search |
| `vector` | Centroid-routed dense search |
| `hybrid` | Weighted or RRF fusion of BM25 + vector |
| `neighbors` | Bounded adjacency neighbors |
| `graph-walk` | Structural BFS walk |
| `semantic-graph-walk` | Embedding-guided beam walk |

Shared legal filters: `--jurisdiction`, `--code`, `--citation`, `--legal-id`,
`--title`, `--chapter`, `--section`, `--edition`, `--kind`.

### 7.4 Diagnose sparse fetches

Every successful query with `--trace` / `--json` can emit a credential-safe
`fetch_trace`. Use it to prove sparse routing and to triage over-fetch.

| Field | Healthy expectation |
|---|---|
| `repo_id` | `justicedao/ipfs_state_laws` (or local equivalent) |
| `revision` | Immutable 40-hex pin (new **or** previous) |
| `route_justified` | `true` — every file has a route reason |
| `verification_state` | `verified` |
| `total_file_bytes` | Within `--max-bytes` |
| `file_count` / `files[]` | Control plane + **routed** shards only |
| `cache_hits` | Increases on repeat query against warm cache |

Paths in the trace are **relative**. Absolute local paths, tokens, and
authorization headers must never appear.

### 7.5 Failure triage matrix

| Symptom | Likely cause | Action |
|---|---|---|
| `MutableRevisionError` / refused `main` | Mutable pin | Re-pin 40-hex SHA |
| Digest / size mismatch | Tamper or wrong revision | Fail closed; redownload from pin; do not soft-warn |
| Budget exhausted (`max-bytes` / `max-shards`) | Route explosion or budget too tight | Inspect `files[]` routes; raise budget only with justification |
| `route_justified=false` | Unjustified path fetch | Treat as security incident; reject result |
| Empty hits on a known gold citation | Wrong config, filter, or pin | Check `--jurisdiction` / Viewer config; compare both pins |
| Default Viewer looks Iowa-only | Querying the previous pin’s default config | Use the new pin, or the named legacy config on purpose |
| Absolute path or token in output | Redaction failure | Abort; never paste logs into tickets with secrets |

---

## 8. Monitor the four-lane board (blocked / idle / stale)

The state-law program shares four SHA-256 lanes with the Federal Register
work. Process liveness alone is never healthy. Operators diagnose boards with
the sealed status entry points (read-only):

```bash
scripts/ops/legal_corpora_reindex/status.sh
scripts/ops/legal_corpora_reindex/status.sh --json
scripts/ops/legal_corpora_reindex/status.py --json --observe-seconds 20
```

Exit status is zero only for `starting`, `healthy`, or
cryptographically/current-board-proven `completed`.

### 8.1 How to classify a lane

Read `blocked_count`, `ready_count`, `active_task_id`, live worker PIDs,
`selection_idle_reason`, heartbeat age, and implementation-log age.

| Condition | Observable | Operator meaning |
|---|---|---|
| **blocked** | `blocked_count > 0` (even if PIDs are alive) | A task cannot proceed; inspect dependency / external-requirement receipts. Do not treat the board as healthy. |
| **idle** | `ready_count > 0`, no `active_task_id`, no live worker, progress older than grace | Ready work with no worker past grace (the prior US Code stall). Inspect merge/result, then refill, split, or retry. |
| **stale** | heartbeat age > 120s (after startup grace), **or** active implementation log stall, **or** active task past hard timeout | Progress stopped even if a provider PID remains live. Do not infer health from the PID. |
| **healthy** | exact process identity, fresh heartbeats, `blocked_count == 0`, no ready-without-worker stall, no protected-path incident | Safe to leave running. |
| **starting** | within startup grace and no fatal reasons yet | Wait; do not launch a second namespace. |

The monitor also declares the board unhealthy when the master/lane supervisor
or managed daemon PID is dead or mismatched, a protected-path incident is
latched, a merge-queue or provider error is present, or the branch tip and
board state stop progressing beyond the configured threshold.

### 8.2 Response order for a nonterminal idle board

1. Inspect evidence and dependency state (do not kill a live namespace).
2. Reconcile an already-produced merge/result.
3. Run objective/codebase refill (below).
4. Split an oversized or repeatedly failing task.
5. Retry within budget.
6. Create a typed operator task for genuine external requirements.

Never start another copy when preflight reports an existing namespace.
Never delete a runtime tree while a matching process is live.

The rehearsal script encodes the blocked / idle / stale classifier and
executes sealed diagnostic cases during `--check`.

---

## 9. Refill

Refill is triggered when open work drops below the configured floor, a cohort
receipt contains a gap, an acceptance command exposes missing evidence, or a
live remote canary differs from the candidate.

```bash
# Acquisition-gap refill / full-scrape acceptance (LCR-023)
python scripts/ops/legal_data/state_laws_acquisition_gap_refill.py --check

# Coverage / gap reports (never treat a requested subset as the exact 51)
python scripts/ops/legal_data/check_state_law_coverage.py --check
python scripts/ops/legal_data/report_state_law_corpus_gaps.py --check
```

Generated work must use the next `LCR-NNN` identifier, content-address the
discovering receipt, and never edit the protected plan/config/initial-board
contract from an implementation worktree.

---

## 10. Stage, canary, and publish (additive only)

Checks are read-only and fail closed if their canonical evidence is absent.
The two staging writes are separately authorized canonical-runtime calls: a
branch authorization never covers the commit. Main publication performs one
separately authorized canonical commit only after the strict prepublication
seal check.

```bash
# Staging planner / receipt (LCR-040) — dry-run / check
python scripts/ops/legal_data/stage_state_laws_hf_release.py \
  --dry-run --release-root "$STATE_LAWS_RELEASE_ROOT"
python scripts/ops/legal_data/stage_state_laws_hf_release.py --check-receipt

# Live staging only after reviewing the dry-run plan. These approval JSON
# files bind the same plan but carry distinct approval_id values.
python scripts/ops/legal_data/stage_state_laws_hf_release.py \
  --authorize-mutation --release-root "$STATE_LAWS_RELEASE_ROOT" \
  --branch-approval /secure/path/branch-approval.json \
  --commit-approval /secure/path/commit-approval.json \
  --write-receipt

# Immutable staging canary (LCR-041)
python scripts/ops/legal_data/canary_state_laws_hf_release.py --require-live-staging --check

# Additive public upload receipt (LCR-042) — does not run from this rehearsal
python scripts/ops/legal_data/publish_state_laws_hf_release.py \
  --dry-run --release-root "$STATE_LAWS_RELEASE_ROOT"
python scripts/ops/legal_data/publish_state_laws_hf_release.py --check-receipt

# Public pin + Dataset Viewer (LCR-043)
python scripts/ops/legal_data/check_state_laws_public_release.py --require-public-pin --check

# Downstream read-only evidence checks
python scripts/ops/legal_data/benchmark_state_laws_public_release.py --check
python scripts/ops/legal_data/audit_state_laws_post_publication.py --check
```

Forbidden on every path: `delete`, `force_push`, `visibility_change`,
`history_rewrite`, `overwrite_legacy`, `rotate_credentials`,
`direct_main_upload` without the human seal. Staging targets
`stage/state-laws-sparse-graphrag-v2` forked from the previous public pin.

---

## 11. Rollback rehearsal (bounded and recoverable)

Rollback restores the **prior advertised revision/config mapping**. It does
**not** delete the failed or succeeding candidate tree, delete legacy files,
force-push history, or change visibility.

Offline rehearsal (authoritative for LCR-045):

```bash
python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check
```

### 11.1 Procedure

1. Record the current advertised pin:
   - exact revision from checked `publication_receipt.json`
   - default config `state-laws-ir-graphrag/v2`
   - explicit legacy config `legacy-state-laws-parquet/v1`
2. Record the rollback target:
   - revision `42f0546acc7c6cd55627eaf51fb820d5613b9021`
3. Confirm both pins remain independently queryable (section 7.2) **before**
   any advertisement change.
4. Confirm forbidden operations are impossible: only pointer re-advertisement
   is scheduled; `delete` / `force_push` / `visibility_change` stay forbidden.
5. **Rollback path:** re-advertise the previous pin + documented default
   config for that pin. Keep the new pin tree. Re-query **both** pins.
6. **Forward path:** re-advertise the new pin + `state-laws-ir-graphrag/v2`.
   Keep the previous pin tree. Re-query **both** pins.
7. Record both pins, both configs, and the forbidden set in
   `docs/reports/legal_corpora_reindex/rollback_rehearsal.json`.

Operator invariant:

> Rollback rehearsal restores the prior advertised revision/config mapping
> without deleting legacy data. Both pins remain queryable. Recovery is the
> reverse pointer move.

This rehearsal **never** changes public advertisement. A live rollback still
requires a human seal and the publication gate; the rehearsal only proves
the mapping is bounded and recoverable.

---

## 12. Incremental update

1. Resolve and approve an official release point (exact pin, not `latest`).
2. Diff stable `legal_id` / content hashes; plan full vs incremental rebuild.
3. Re-run cohort scrape/resume only for jurisdictions whose official source
   changed; refuse subset combined promotion.
4. Rebuild required families with atomic per-jurisdiction checkpoints.
5. Package the HF release **without deleting** legacy paths.
6. Stage dry-run; canary; assemble a new publication seal.
7. Upload additively; resolve the new public SHA; keep the previous SHA as
   the new rollback target.
8. Rehearse dual-pin query and rollback (`--check`) before asking a human to
   change advertisement.

---

## 13. Exact release provenance

Every admitted row and every sealed candidate must bind:

| Field | Meaning |
|---|---|
| `release_point` | Exact official package pin (`state-laws/v2/2026-08-10`) |
| Hub revision | Immutable dataset commit (new **or** previous pin) |
| `entry_cid` | Content-addressed primary key for v2 |
| `legal_id` | Durable statutory identity |
| `source_cid` / `source_checksum` | Upstream artifact identity |
| `admission_status` / `admission_reason` | Admitted, replaced, or excluded |
| `acquisition_time` | When the package was retrieved (not legal currentness) |
| `manifest_digest` | Sealed candidate integrity |

Mixed official vintages must not masquerade as one current code. Per-jurisdiction
receipts and fail-closed admission enforce this. Recovery JSON is advertised
only under `recovery-quarantine/v1` and stays outside the default Viewer.

---

## 14. Legal caveats: publication date vs legal currentness

**Critical operator distinction:**

| Concept | What it is | What it is not |
|---|---|---|
| **Publication date** | When a Hub revision or local candidate was sealed/uploaded | Proof the text is the law “today” |
| **Acquisition time** | When the official package was fetched | A live codification guarantee |
| **Release point / edition** | Exact official package identity bound into the corpus | Automatically the latest legislative session |
| **Legal currentness** | Whether the provision is operative law for a fact pattern at a wall-clock moment | Something this retrieval system asserts |

Rules operators must follow:

1. Acquisition and publication timestamps are **not** legal-currentness claims.
2. Time-sensitive answers must expose the **release point** and **edition**, not
   only a Hub `last_modified` stamp.
3. Retrieval output is a **research aid**, not a substitute for the official
   legislature / reviser / DC Council source.
4. Individualized “what is the law for my case today” questions may require
   **abstention** rather than a forced exact hit.
5. Historical/version-ambiguous queries must surface version metadata; never
   collapse mixed vintages into a single unlabeled “current” answer.

---

## 15. Publication boundary checklist

Before any human is asked to seal production or change advertisement:

- [ ] Fixture build + query succeed offline
- [ ] Fetch traces show only routed shards + verified digests
- [ ] Staging receipt is redacted and add-only
- [ ] Rollback target (prior revision + config mapping) is named
- [ ] Both the new pin and the previous pin remain independently queryable
- [ ] Legacy config `legacy-state-laws-parquet/v1` is explicit and not default
- [ ] Evaluation, security, determinism, and viewer gates pass
- [ ] Board status is not blocked / idle-without-worker / stale
- [ ] Rollback rehearsal `--check` passes
- [ ] No agent treats `HF_TOKEN` as publication authority

---

## 16. Quick command index

| Goal | Command |
|---|---|
| Rollback rehearsal (this task) | `python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check` |
| Admission self-check | `python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --validation-only --check` |
| Full local build check | `python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --full --check` |
| Fixture scrape + resume | `python scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py --fixture-only --cohort A --check` |
| Query new pin (offline) | `python scripts/ops/legal_data/query_state_laws_hf.py --local-root PATH --revision "$STATE_LAWS_PUBLIC_SHA" --fixture-mode --json --trace bm25 "query"` |
| Query previous pin | `python scripts/ops/legal_data/query_state_laws_hf.py --repo-id justicedao/ipfs_state_laws --revision 42f0546acc7c6cd55627eaf51fb820d5613b9021 --json --trace bm25 "query"` |
| Board health | `scripts/ops/legal_corpora_reindex/status.sh --json` |
| Board observation | `python scripts/ops/legal_corpora_reindex/status.py --json --observe-seconds 20` |
| Gap refill | `python scripts/ops/legal_data/state_laws_acquisition_gap_refill.py --check` |
| Staging receipt | `python scripts/ops/legal_data/stage_state_laws_hf_release.py --check-receipt` |
| Public canary | `python scripts/ops/legal_data/check_state_laws_public_release.py --require-public-pin --check` |
