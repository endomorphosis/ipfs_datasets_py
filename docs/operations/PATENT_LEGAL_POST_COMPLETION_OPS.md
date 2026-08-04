# Patent Legal Intelligence — Post-Completion Ops

**Task:** `PATLAW-165`  
**Goal:** `PATLAW-G201`  
**Track:** post-completion-ops  
**Depends on:** `PATLAW-164` (exact-tree production completion gate)

This runbook is the operator surface for **offline validation of production
completion-gate artifacts and the evidence-bundle inventory** after the reviewed
`PATLAW-000..164` board drains. It does **not** publish to Hub main, open Patent
Center sessions, process payments, capture signatures, or auto-push remotes.

## Standing rules (fail-closed)

1. **Content-free only.** Offline gate receipts, production-status snapshots,
   gap lists, and CLI summaries must never include document bodies, extracted
   text, embeddings, API keys, bearer tokens, cookies, or raw provider payloads.
2. **Evidence over status.** Task status, backlog completion, goal status, or a
   drained supervisor board **cannot** alone satisfy production acceptance.
3. **Gaps must be explicit.** Required evidence paths are either present or
   listed under `evidence_gaps` / inventory `gaps`. Silent omission is forbidden.
4. **Offline ≠ live readiness.** An offline `drained` / `completed` projection
   with gap-listed live receipts does **not** authorize Hub publish, filing, or
   legal sign-off.
5. **No unattended publish.** Post-completion catalog tasks package, canary,
   dry-run, and handoff only; humans perform push / PR / filing / payment.

## What offline validation answers

> Do the completion-gate and production-status surfaces report a **coherent
> drained-or-completed projection** for the current tree, with every required
> evidence path present or explicitly gap-listed, without printing private data?

| Surface | Role |
| --- | --- |
| `scripts/ops/uspto/validate_production_release.py --offline` | PATLAW-164 gate + PATLAW-165 projection |
| `scripts/ops/patent_legal_intelligence/production_status.py --json` | Live health **or** offline tree projection |
| `tests/release/test_patent_legal_production_release.py` | Contract for gate, projection, content-free policy |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | Full production gate runbook (PATLAW-164) |

## Operator commands

### Authoritative offline validation (PATLAW-165)

```bash
python -m pytest tests/release/test_patent_legal_production_release.py -q
python scripts/ops/uspto/validate_production_release.py --offline
python scripts/ops/patent_legal_intelligence/production_status.py --json \
  >/tmp/patlaw-production-status.json
```

Both CLIs emit JSON that includes:

* `projection` / `overall_state` ∈ `{drained, completed}` when coherent
* `evidence_gaps` (or inventory gaps) listing missing live receipts / artifacts
* `required_paths_present_or_gap_listed: true`
* `content_free: true` (or content-free assert before emit)

### Interpreting the offline projection

| Projection | Meaning |
| --- | --- |
| `completed` | Offline production receipt accepted; child receipts validated; tree gate artifacts bind digests. Live production receipts may still be gap-listed. |
| `drained` | Prior-task outputs / board foundation present; no active blocking receipt failure; remaining work is operator post-completion (PR package, canary, Hub dry-run, handoff). |
| `blocked` | Prior tasks missing, offline receipt rejected/blocked, or projection incoherent. |

Live evidence gaps (authority freshness, index evaluation, isolation, filing
handoff, Hub verification, paired sync, completion receipt) are **non-blocking
for the offline projection** when explicitly listed. They **do** keep
`live_readiness` / live `readiness` false until present and valid.

### Force offline tree projection

```bash
python scripts/ops/patent_legal_intelligence/production_status.py \
  --offline-tree --json
```

Use this when a partial live evidence root exists but the operator wants the
tree-bound drained/completed view for post-completion handoff packaging.

### Offline gate without writing a receipt

```bash
python scripts/ops/uspto/validate_production_release.py --offline --no-write
```

Default receipt location (when write enabled):

`$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/production_release/`

## Evidence inventory

### Tree-bound gate artifacts

| Path | Role |
| --- | --- |
| `scripts/ops/uspto/validate_production_release.py` | Completion gate CLI |
| `scripts/ops/patent_legal_intelligence/production_status.py` | Status / projection CLI |
| `tests/release/test_patent_legal_production_release.py` | Release contract tests |
| `data/release/patent_legal_intelligence/production_receipt.schema.json` | Receipt schema |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | Gate runbook |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | This post-completion runbook |

### Live evidence receipts (under evidence root)

Convention root: `$XDG_STATE_HOME/.../production` or `--evidence-root`.

| Relative path | Kind |
| --- | --- |
| `authority/freshness.json` | Authority freshness (mandatory) |
| `indexes/evaluation_receipt.json` | Index evaluation (mandatory) |
| `isolation/status.json` | Isolation status (mandatory) |
| `filing/handoff_status.json` | Filing handoff (mandatory) |
| `hub/verification_receipt.json` | Hub verification (mandatory) |
| `sync/paired_revision_receipt.json` | Paired revision sync (mandatory) |
| `completion/receipt.json` | Completion receipt (optional for drained; required for live completed) |

Missing entries appear as gap objects with `path`, `kind`, and `gap` reason only.

## Post-completion catalog (bounded)

After board drain, the supervisor may refill these operator tasks (see
`data/agent_supervisor/patent_legal_intelligence/bundles/post_completion_ops_catalog.json`):

| Task | Title |
| --- | --- |
| `PATLAW-165` | Offline completion-gate + evidence inventory (this runbook) |
| `PATLAW-166` | Feature-branch PR package (no auto-push) |
| `PATLAW-167` | Live canary (defaults offline fixtures) |
| `PATLAW-168` | Hub dry-run (no main publish) |
| `PATLAW-169` | Operator handoff receipt + completed status projection |

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Offline gate `ok: false` | Mandatory gate failed on tree | Repair prior-task outputs; re-run `--offline` |
| Projection `blocked` | Receipt rejected or prior tasks missing | Inspect `projection.reason` and inventory gaps |
| Status exit 1 with empty evidence | Incoherent offline projection | Ensure gate scripts + prior outputs exist on tree |
| Content-free error | Secret/document marker in payload | Strip private fields; re-emit |
| Live readiness false, projection completed | Expected offline | Collect live receipts before production traffic |

## Related surfaces

| Surface | Role |
| --- | --- |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | PATLAW-164 gate policy and child receipts |
| `scripts/ops/uspto/validate_v2_release.py` | V2 release child (PATLAW-143) |
| `scripts/ops/legal_data/verify_patent_hf_release_v2.py` | Hub verify child (PATLAW-160) |
| `docs/operations/PATENT_HF_RELEASE_V2.md` | Hub / Viewer / rollback |

## What this is not

* Not a legal opinion or patentability determination
* Not a Patent Center filing acknowledgement
* Not a Hub main publication approval
* Not satisfied by taskboard drained status alone
* Not a license to skip human review for push, PR, filing, or payment
