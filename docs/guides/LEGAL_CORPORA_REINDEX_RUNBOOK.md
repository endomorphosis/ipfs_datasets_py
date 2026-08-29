# Dual-release legal corpora operations runbook (LCR-068)

Operator runbook for scraping, building, resuming, querying, monitoring,
refilling, updating, and rolling back the **two** sealed public releases:

| Corpus | Repository | Default Viewer / release profile |
|---|---|---|
| State laws | `justicedao/ipfs_state_laws` | `state-laws-ir-graphrag/v2` |
| Federal Register | `justicedao/ipfs_federal_register` | `federal-register-ir-graphrag/v2` |

This document is the combined operations surface for LCR-068 / LCR-G140.
It depends on the sealed LCR-047 state-law final receipt and the LCR-067
cross-corpus canary. Corpus-specific depth remains in:

| Document | Purpose |
|---|---|
| [STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md](STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md) | State-law scrape / Viewer / exact-51 rollback |
| [STATE_LAWS_SPARSE_GRAPHRAG_MIGRATION.md](STATE_LAWS_SPARSE_GRAPHRAG_MIGRATION.md) | Legacy state-law config map |
| [legal_corpora_reindex README](../../scripts/ops/legal_corpora_reindex/README.md) | Four-lane board preflight, launch, and health |

All check and rehearsal commands in this runbook are read-only. Fixture and
dry-run results exercise software mechanics but are never accepted as live
staging or publication evidence. Protected writes run only through the shared
canonical publication runtime, with a fresh payload-bound authorization for
each individual branch or commit mutation. Dual-release rollback rehearsal
never deletes remote artifacts and never changes public advertisement.

Dual-release rollback rehearsal (this task):

```bash
python scripts/ops/legal_data/rehearse_legal_corpora_release_rollback.py --check
```

That command is credential-free, contacts no Hub, does not change public
advertisement, and does not delete remote artifacts.

---

## 1. Scope and non-goals

### In scope

- Fixture / receipt-check builds, scrapes, resumes, and offline queries
- Independent query of **all four pins** (state new, state previous,
  Federal new, Federal previous)
- Bounded, reversible rollback (re-advertise a prior immutable pin)
- **daily versus jurisdictional** update semantics (never conflated)
- Objective / codebase / corpus **refill closure**
- Board diagnosis for **blocked**, **idle**, and **stale** lanes
- Legal-currentness caveats for both corpora

### Out of scope (fail closed)

- Public mutation of either Hub repository on `main` / `master`
- Deletion, force-push, history rewrite, visibility change, or credential rotation
- Inferring Hugging Face publication authority from token presence
- Treating acquisition or publication timestamps as wall-clock legal currentness
- Mixing a state-law subset into the sealed exact-51 release
- Treating a Federal daily increment as a jurisdictional rebuild, or the reverse

Publication of either corpus remains a separate human-sealed additive
upload. Implementation lanes may only build, validate, stage under
explicit non-production authorization, redownload, canary, and rehearse
rollback **without deleting** history.

---

## 2. Sealed coordinates (All four pins)

| Coordinate | State laws | Federal Register |
|---|---|---|
| Dataset repository | `justicedao/ipfs_state_laws` | `justicedao/ipfs_federal_register` |
| Previous public pin (rollback target) | `42f0546acc7c6cd55627eaf51fb820d5613b9021` | `720668ae016cc400916dda884c9005e03618edfa` |
| New public pin (current advertisement) | Read `public_sha` from the sealed live state publication receipt | Read `public_sha` from the sealed live Federal publication receipt |
| Staging branch (non-production) | `stage/state-laws-sparse-graphrag-v2` | `stage/federal-register-ir-graphrag-v2` |
| Public branch | `main` (never a live query revision) | `main` (never a live query revision) |
| Official `release_point` | `state-laws/v2/2026-08-10` | `federal-register/v2/2026-08-10` |
| Release profile / default Viewer | `state-laws-ir-graphrag/v2` | `federal-register-ir-graphrag/v2` |
| Default primary key | `entry_cid` | `entry_cid` |
| Observation cutoff | n/a (source-frontier) | `2026-08-10T00:00:00Z` |
| Update unit | jurisdictional (exact 51, includes DC) | daily / `year_month` partition |

Mutable revisions (`main`, `master`, `latest`, empty, `HEAD`) are rejected
for live Hub use. Always pin a 40-hex commit SHA. The rehearsal gate passes
only after live receipts/canaries prove that all four pins are independently
queryable; rollback only moves the advertised pointer.

Producer receipts this runbook binds (read-only inputs):

| Receipt | Path | Role |
|---|---|---|
| State publication | `docs/reports/legal_corpora_reindex/publication_receipt.json` | State new SHA + previous pin |
| State public canary | `docs/reports/legal_corpora_reindex/public_canary.json` | State new-pin query proof |
| State baseline | `docs/reports/legal_corpora_reindex/baseline.json` | State previous-pin inventory |
| State rollback | `docs/reports/legal_corpora_reindex/rollback_rehearsal.json` | LCR-045 dual-pin contract |
| State post-publication audit | `docs/reports/legal_corpora_reindex/post_publication_audit.json` | Jurisdictional update checkpoints |
| State final receipt (LCR-047) | `docs/reports/legal_corpora_reindex/state_final_release_receipt.json` | State gate closure |
| Federal publication | `docs/reports/legal_corpora_reindex/federal_publication_receipt.json` | Federal new SHA + previous pin |
| Federal public canary | `docs/reports/legal_corpora_reindex/federal_public_canary.json` | Federal new-pin query proof |
| Federal baseline | `docs/reports/legal_corpora_reindex/federal_baseline.json` | Federal previous-pin inventory |
| Cross-corpus canary (LCR-067) | `docs/reports/legal_corpora_reindex/cross_corpus_canary.json` | Shared substrate / fusion |
| Dual rollback rehearsal | `docs/reports/legal_corpora_reindex/dual_rollback_rehearsal.json` | This task |

---

## 3. Prerequisites

```bash
# From the repository root
export REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

python -c "import ipfs_datasets_py; print('ok')"
```

Optional environment (never pass as CLI flags):

| Variable | Use |
|---|---|
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | Live Hub **read** only when an operator opts into network canaries |
| Shared runtime identity/credential variables | Consumed only inside the canonical runtime after identity, policy, plan, payload, and parent-pin checks |

Secrets must never appear in argv, prompts, logs, manifests, fetch traces, or
Git. Token presence is never publication authority. CLI entry points reject
token-like command-line values.

---

## 4. Scrape, build, and resume

Default behavior is **offline receipt-check**. Live acquisition is a
different authorization contract.

```bash
# State-law fixture scrape + resume (jurisdictional cohorts)
python scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py --fixture-only --cohort A --check

# State-law sparse GraphRAG build
python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --validation-only --check

# Federal Register acquisition (daily / cutoff-relative)
python scripts/ops/legal_data/acquire_federal_register_full.py --check

# Federal Register sparse GraphRAG build
python scripts/ops/legal_data/build_federal_register_sparse_graphrag.py --check
```

Resume rules:

1. State-law resume is **atomic per-jurisdiction**. A failed state does not
   promote a subset combined Parquet.
2. Federal Register resume is **daily / `year_month` partition**. A failed
   day does not rewrite earlier sealed partitions.
3. Never resume by passing `main`, `latest`, or an empty revision.
4. Rebuild required families only after the official `release_point` or
   observation cutoff is approved.

---

## 5. Query (all four pins must remain queryable)

Load `STATE_PUBLIC_SHA` and `FEDERAL_PUBLIC_SHA` from their sealed live
publication receipts and verify that each is exactly 40 lowercase hex
characters before using these commands. Never substitute a predicted or
fixture revision.

```bash
# State new pin
python scripts/ops/legal_data/query_state_laws_hf.py \
  --repo-id justicedao/ipfs_state_laws \
  --revision "$STATE_PUBLIC_SHA" \
  --json --trace bm25 "disclosure" --top-k 5 --jurisdiction DC

# State previous pin
python scripts/ops/legal_data/query_state_laws_hf.py \
  --repo-id justicedao/ipfs_state_laws \
  --revision 42f0546acc7c6cd55627eaf51fb820d5613b9021 \
  --json --trace bm25 "disclosure" --top-k 5 --jurisdiction DC

# Federal new pin
python scripts/ops/legal_data/query_federal_register_hf.py \
  --repo-id justicedao/ipfs_federal_register \
  --revision "$FEDERAL_PUBLIC_SHA" \
  --json --trace bm25 "airworthiness" --top-k 3

# Federal previous pin
python scripts/ops/legal_data/query_federal_register_hf.py \
  --repo-id justicedao/ipfs_federal_register \
  --revision 720668ae016cc400916dda884c9005e03618edfa \
  --json --trace bm25 "airworthiness" --top-k 3

# Cross-corpus substrate / fusion (LCR-067)
python scripts/ops/legal_data/canary_legal_corpora_public_releases.py --check
```

The rehearsal must prove that all four pins remain independently queryable
after rollback and after the forward restore. Advertisement is a pointer,
not a delete.

---

## 6. Monitor the board (blocked / idle / stale)

```bash
scripts/ops/legal_corpora_reindex/status.sh --json
python scripts/ops/legal_corpora_reindex/status.py --json
python scripts/ops/legal_corpora_reindex/status.py --json --observe-seconds 20
```

| Kind | Meaning | First response |
|---|---|---|
| **blocked** | One or more tasks cannot proceed | Inspect evidence and dependencies |
| **idle** | Eligible work is ready without a live worker past grace | Reconcile an existing result, then refill |
| **stale** | Heartbeat or implementation log has stopped | Do not start a second copy; diagnose the live namespace |

Response order for a nonterminal idle board:

1. Inspect evidence and dependency state.
2. Reconcile an already-produced merge/result.
3. Run objective/codebase refill.
4. Split an oversized or repeatedly failing task.
5. Retry within budget.
6. Create a typed operator task for genuine external requirements.

Never start another copy when preflight reports an existing namespace.
Never delete a runtime tree while a matching process is live.

---

## 7. Refill closure

Refill is triggered when open work drops below the configured floor, a
cohort receipt contains a gap, an acceptance command exposes missing
evidence, or a live remote canary differs from the candidate.

```bash
# State-law acquisition-gap refill
python scripts/ops/legal_data/state_laws_acquisition_gap_refill.py --check

# Federal daily / cutoff refill is an acquisition increment, not a
# jurisdictional rebuild:
python scripts/ops/legal_data/acquire_federal_register_full.py --check
```

LCR-068 requires **refill closure**: no unresolved objective, codebase, or
corpus refill finding remains in the bound publication receipts, the
state post-publication audit, or the LCR-047 final receipt. Generated
work must use the next `LCR-NNN` identifier, content-address the
discovering receipt, and never edit the protected plan/config/initial-board
contract from an implementation worktree.

A closed refill ledger is a precondition for the dual-release rollback
rehearsal `--check` gate.

---

## 8. Daily versus jurisdictional update semantics

**These two update units are explicit and must not be conflated.**

| | State laws | Federal Register |
|---|---|---|
| Kind | **jurisdictional** | **daily** |
| Unit | official package / postal code + DC | publication date / `year_month` partition |
| Completeness | exact-51 source frontier | cutoff-relative through the observation cutoff |
| Checkpoint grain | atomic per-jurisdiction | daily partition, never a silent mix |
| What changed work looks like | official code edition changed for one or more jurisdictions | new daily issues after the sealed observation cutoff |
| What it is not | a daily scrape of all 51 | a per-state rebuild |

State-law incremental update:

1. Resolve and approve an official `release_point` (exact pin, not `latest`).
2. Diff stable `legal_id` / content hashes; classify upstream change as
   **delta work**.
3. Re-run cohort scrape/resume only for jurisdictions whose official
   source changed; refuse subset combined promotion.
4. Rebuild required families with **atomic per-jurisdiction** checkpoints.
5. Package the HF release **without deleting** legacy paths.
6. Stage dry-run; canary; assemble a new publication seal.
7. Upload additively; keep the previous SHA as the new rollback target.
8. Rehearse dual-pin query and rollback (`--check`).

Federal Register incremental update:

1. Keep the sealed **observation cutoff**; do not treat wall-clock time as
   legal currentness of the daily register.
2. Diff `year_month` partitions and document numbers against the cutoff.
3. Acquire only the changed daily issues; never rewrite earlier sealed
   partitions in place.
4. Rebuild required families for the changed partitions.
5. Package additively **without deleting** the previous public pin.
6. Stage dry-run; canary; assemble a new publication seal.
7. Upload additively; keep `720668ae016cc400916dda884c9005e03618edfa` (or
   the then-current previous pin) as the rollback target.
8. Rehearse four-pin query and rollback (`--check`).

---

## 9. Dual-release rollback (bounded and reversible)

Rollback restores the **prior advertised revision/config mapping** for one
corpus. It does **not** delete the failed or succeeding candidate tree,
delete legacy files, force-push history, or change visibility. Forward
restore is the reverse pointer move. Both directions are **bounded** and
**reversible**.

Offline rehearsal (authoritative for LCR-068):

```bash
python scripts/ops/legal_data/rehearse_legal_corpora_release_rollback.py --check
```

### 9.1 Procedure

1. Record the four advertised/rollback pins in section 2.
2. Confirm all four pins remain independently queryable **before** any
   advertisement change.
3. Confirm forbidden operations are impossible: only pointer
   re-advertisement is scheduled; `delete` / `force_push` /
   `visibility_change` stay forbidden.
4. **State rollback path:** re-advertise
   `42f0546acc7c6cd55627eaf51fb820d5613b9021`. Keep the new state pin.
   Re-query **all four** pins.
5. **State forward path:** re-advertise the exact `STATE_PUBLIC_SHA` from the
   sealed live receipt. Keep the previous state pin.
6. **Federal rollback path:** re-advertise
   `720668ae016cc400916dda884c9005e03618edfa`. Keep the new Federal pin.
   Re-query **all four** pins.
7. **Federal forward path:** re-advertise the exact `FEDERAL_PUBLIC_SHA` from
   the sealed live receipt. Keep the previous Federal pin.
8. Record both corpora, both directions, refill closure, and
   daily versus jurisdictional update semantics in
   `docs/reports/legal_corpora_reindex/dual_rollback_rehearsal.json`.

Operator invariant:

> Dual-release rollback rehearsal restores the prior advertised
> revision/config mapping on each corpus without deleting legacy data.
> All four pins remain queryable. Recovery is the reverse pointer move.
> Forward and rollback operations are bounded and reversible.

This rehearsal **never** changes public advertisement. A live rollback
still requires a human seal and the publication gate; the rehearsal only
proves the mapping is bounded and recoverable.

---

## 10. Legal caveats: publication date vs legal currentness

**Critical operator distinction:**

| Concept | What it is | What it is not |
|---|---|---|
| **Publication date** | When a Hub revision or local candidate was sealed/uploaded | Proof the text is the law “today” |
| **Acquisition time** | When the official package or daily issue was fetched | A live codification guarantee |
| **Release point / edition** | Exact official package identity bound into the corpus | Automatically the latest legislative session |
| **Observation cutoff** | Inclusive Federal daily bound for this sealed release | Wall-clock currentness of the daily register |
| **Legal currentness** | Whether the provision is operative law for a fact pattern at a wall-clock moment | Something this retrieval system asserts |

Rules operators must follow:

1. Acquisition and publication timestamps are **not** legal-currentness claims.
2. Time-sensitive answers must expose the `release_point`, edition, and
   (for Federal) the observation cutoff — not only a Hub `last_modified`.
3. Retrieval output is a **research aid**, not a substitute for the official
   legislature / reviser / DC Council / FederalRegister.gov source.
4. Individualized “what is the law for my case today” questions may require
   **abstention** rather than a forced exact hit.
5. Historical/version-ambiguous queries must surface version metadata; never
   collapse mixed vintages into a single unlabeled “current” answer.
6. Graph and federated retrieval output is never legal authority or advice.

---

## 11. Publication boundary checklist

Before any human is asked to seal production or change advertisement:

- [ ] Fixture build + query succeed offline for both corpora
- [ ] Fetch traces show only routed shards + verified digests
- [ ] Staging receipts are redacted and add-only
- [ ] Rollback targets (prior revision + config mapping) are named for both corpora
- [ ] All four pins remain independently queryable
- [ ] Forward/rollback operations are bounded and reversible
- [ ] No unresolved refill finding remains
- [ ] Daily versus jurisdictional update semantics are explicit
- [ ] Board status is not blocked / idle-without-worker / stale
- [ ] Dual rollback rehearsal `--check` passes
- [ ] No agent treats `HF_TOKEN` as publication authority

---

## 12. Quick command index

| Goal | Command |
|---|---|
| Dual rollback rehearsal (this task) | `python scripts/ops/legal_data/rehearse_legal_corpora_release_rollback.py --check` |
| State fixture scrape + resume | `python scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py --fixture-only --cohort A --check` |
| State build check | `python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --validation-only --check` |
| Federal acquire check | `python scripts/ops/legal_data/acquire_federal_register_full.py --check` |
| Federal build check | `python scripts/ops/legal_data/build_federal_register_sparse_graphrag.py --check` |
| Query state pin | `python scripts/ops/legal_data/query_state_laws_hf.py --repo-id justicedao/ipfs_state_laws --revision PIN --json --trace bm25 "query"` |
| Query Federal pin | `python scripts/ops/legal_data/query_federal_register_hf.py --repo-id justicedao/ipfs_federal_register --revision PIN --json --trace bm25 "query"` |
| Cross-corpus canary | `python scripts/ops/legal_data/canary_legal_corpora_public_releases.py --check` |
| Board health | `scripts/ops/legal_corpora_reindex/status.sh --json` |
| Board observation | `python scripts/ops/legal_corpora_reindex/status.py --json --observe-seconds 20` |
| State gap refill | `python scripts/ops/legal_data/state_laws_acquisition_gap_refill.py --check` |
