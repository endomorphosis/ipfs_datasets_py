# Patent Legal Intelligence — Production Completion Gate

**Task:** `PATLAW-164`  
**Goal:** `PATLAW-G192`  
**Track:** production-assurance  
**CLI:** `scripts/ops/uspto/validate_production_release.py`  
**Schema:** `data/release/patent_legal_intelligence/production_receipt.schema.json`  
**Tests:** `tests/release/test_patent_legal_production_release.py`

This runbook is the operator surface for the **exact-tree production completion
gate**. It answers a single fail-closed question:

> Does one content-free immutable receipt prove every mandatory production gate
> on the current tree?

The gate does **not** issue legal opinions, patentability guarantees, filing
acknowledgements, or publication claims. It binds digests, child receipts, and
policy invariants only.

## Standing rules (fail-closed)

1. **Content-free receipts.** Validation receipts, child receipts, and CLI
   summaries must never include document bodies, extracted text, embeddings,
   API keys, bearer tokens, cookies, or raw provider payloads.
2. **Evidence over status.** Task status, backlog completion, goal status, or a
   drained supervisor board **cannot** satisfy acceptance.
3. **Unknown / stale / missing / mismatched block.** Every mandatory gate must
   pass. Blocked, unknown, missing, stale, or mismatched evidence fails closed.
4. **Reviewed claims only.** No legal opinion, patentability guarantee, filing
   claim, or publication claim may appear on a receipt without corresponding
   reviewed evidence.
5. **Root goal stays active.** `PATLAW-G192` remains active until **this**
   receipt and **every child receipt** validate. Completion eligibility is
   recorded separately from taskboard status.
6. **Receipts outside source.** Fresh receipts are written under
   `$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/production_release/`
   by default (not under tracked `data/`).

## Child receipts (required)

The production gate depends on these prior tasks being present on the exact
target tree. Each contributes a content-free child receipt:

| Task | Surface |
| --- | --- |
| `PATLAW-143` | V2 adversarial / migration / release evidence |
| `PATLAW-151` | Source-quoted claim charts and IDS review queue |
| `PATLAW-155` | Official filing receipt reconciliation |
| `PATLAW-160` | Pinned Hub verification and rollback |
| `PATLAW-163` | Content-free production status observability |

Missing outputs, digest mismatches against the parent tree, or unknown child
status block the parent receipt.

## Mandatory gates

| Gate | What it proves |
| --- | --- |
| `git_tree_binding` | Exact `head_sha` / `tree_sha` on the current repository |
| `config_digest` | Production + v2 + paired-revision schemas hashed |
| `source_roots_current_through` | Official source roots / current-through watermarks bound |
| `corpus_index_model_qrels_roots` | Corpus, index, model, and qrels roots bound |
| `retrieval_metrics` | Retrieval evaluation surfaces bound by digest |
| `private_isolation_provider_calls` | Isolation incidents = 0; provider calls = 0 offline; no disclosure |
| `filing_handoff_receipts` | Filing reconciler present; no unreviewed filing claim |
| `hub_commit_viewer_verification` | Hub verifier + Viewer runbook present; no unreviewed publication claim |
| `paired_repository_shas` | Paired integrator + revision receipt schema present |
| `supervisor_merge_receipts` | Content-free merge receipts for required prior tasks |
| `child_receipts_validated` | Every required child receipt validates |
| `production_status_surface` | PATLAW-163 status surface present and content-free |
| `no_unreviewed_legal_claims` | Legal/patentability/filing/publication claims require reviewed evidence |
| `stale_missing_mismatch_blocks` | Stale, missing, mismatched, or unknown evidence blocks |
| `root_goal_active_until_validated` | Root goal stays active until receipt + children validate |
| `prior_tasks_on_branch` | All required prior-task outputs exist on the tree |
| `no_blocked_unknown_gates` | No blocked/unknown/stale/mismatched gate remains |
| `task_status_alone_rejected` | Task/goal/drained substitutes are rejected |

## Operator commands

### Offline gate (authoritative validation command)

```bash
python -m pytest tests/release/test_patent_legal_production_release.py -q
python scripts/ops/uspto/validate_production_release.py --offline
```

Offline mode:

* inventories prior-task and supporting outputs
* binds production digests and workflow surfaces
* synthesizes content-free child and supervisor merge receipts
* evaluates claim-surface and root-goal policy
* emits a digested immutable receipt (unless `--no-write`)

### Live inventory mode

```bash
python scripts/ops/uspto/validate_production_release.py
```

Live mode inventories declared suite paths on the current tree. Full suite
execution remains with CI or an explicit operator action.

### Validate an existing receipt

```bash
python scripts/ops/uspto/validate_production_release.py \
  --receipt /path/to/production_receipt.json
```

### Optional receipt output path

```bash
python scripts/ops/uspto/validate_production_release.py --offline \
  --output "$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/production_release/manual.json"
```

Default receipt directory:

`$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/production_release/`  
(or `~/.local/state/...` when `XDG_STATE_HOME` is unset).

## Interpreting the receipt

| Field | Meaning |
| --- | --- |
| `status` | `accepted` only when every mandatory gate passes |
| `receipt_digest_sha256` | Canonical SHA-256 of the receipt body (immutable) |
| `git.head_sha` / `git.tree_sha` | Exact tree binding |
| `digests.aggregate_sha256` | Aggregate of code/config/source/index/model/qrels/metrics/filing/hub/sync/test |
| `child_receipts.all_validated` | All five dependency child receipts validated |
| `claim_surface.any_unreviewed_asserted` | Must be `false` for acceptance |
| `root_goal.status` | `active` until receipt + children validate; then `completion_eligible` |
| `root_goal.completion_eligible` | `true` only after both this receipt and children validate |
| `policy.*` | Hard-coded fail-closed constants; never relaxed by task status |

## Claim surface (non-legal)

The receipt may record whether any of the following were **asserted**:

* legal opinion
* patentability guarantee
* filing claim
* publication claim

If asserted, the corresponding `reviewed_evidence_present` flag must be `true`
and an opaque `evidence_ref` may identify the independent review packet. The
gate **never** invents those claims from the mere presence of filing or Hub
modules. Offline tree inventory leaves all four claims unasserted.

## Root goal lifecycle

```
active ──(receipt accepted AND children validated)──► completion_eligible
```

* A drained board does **not** move the goal.
* Task completion on the supervisor board does **not** move the goal.
* Only a content-free accepted production receipt with validated children makes
  the goal completion-eligible. Operator close of `PATLAW-G192` is a separate
  reviewed action.

## Related surfaces

| Surface | Role |
| --- | --- |
| `scripts/ops/patent_legal_intelligence/production_status.py` | Content-free freshness / health (PATLAW-163) |
| `scripts/ops/uspto/validate_v2_release.py` | V2 adversarial/migration release (PATLAW-143) |
| `scripts/ops/legal_data/verify_patent_hf_release_v2.py` | Pinned Hub verification (PATLAW-160) |
| `scripts/ops/uspto/integrate_upstreams.py` | Paired repository integration (PATLAW-161) |
| `docs/operations/PATENT_HF_RELEASE_V2.md` | Hub release / Viewer / rollback runbook |
| `docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md` | Scheduler recovery (not a production close) |

## What this gate is not

* Not a legal opinion or patentability determination
* Not a Patent Center filing acknowledgement
* Not a Hub publication approval by itself
* Not a substitute for independent human legal or publication review
* Not satisfied by pytest green alone when mandatory evidence is missing
  (pytest validates the gate implementation; the gate validates the tree)

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `prior_tasks_on_branch` failed | Missing dependency output | Merge the listed PATLAW child outputs onto the target tree |
| `child_receipts_validated` failed | Missing or incomplete child | Repair child task outputs; re-run offline gate |
| `no_unreviewed_legal_claims` blocked | Asserted claim without review | Attach reviewed evidence or clear the claim assertion |
| `stale_missing_mismatch_blocks` blocked | Stale/missing binding | Refresh evidence receipts; rebind digests on current tree |
| `task_status_alone_rejected` failed | Policy regression | Do not relax substitutes; restore fail-closed constants |
| `receipt_digest_sha256 mismatch` | Body mutated after digest | Regenerate receipt; never hand-edit digests |
| Content-free error | Secret/document marker in payload | Strip private fields; re-emit content-free receipt |

## Validation matrix

| Command | Purpose |
| --- | --- |
| `python -m pytest tests/release/test_patent_legal_production_release.py -q` | Unit/release contract for gate + schema + CLI |
| `python scripts/ops/uspto/validate_production_release.py --offline` | Offline production completion self-check + receipt |

Both commands must exit zero for PATLAW-164 acceptance on the exact tree.
