# Patent Legal Intelligence — Hub Release Dry-Run Staging

**Task:** `PATLAW-168`  
**Goal:** `PATLAW-G202`  
**Track:** post-completion-ops  
**Depends on:** `PATLAW-165`, `PATLAW-157`, `PATLAW-158`  
**Code:** `scripts/ops/legal_data/stage_patent_hf_release.py`  
**Tests:** `tests/release/test_patent_hf_release_dry_run.py`

This runbook is the operator surface for **Hub release dry-run staging
verification**. It proves the publication path offline: manifests, DLP/rights
gates, and Dataset Viewer contracts are checked, and a staging receipt is
written for human approval. It does **not** upload to Hub `main`, open live
pull requests against production without an explicit operator stage step, or
mutate remote default branches.

## Standing rules (fail-closed)

1. **Default is dry-run.** Planning and gate verification never contact the Hub
   for publication and never move runtime pointers.
2. **No direct-main upload.** Stage branches are add-only (`stage/patent-legal/…`);
   `main` / `master` are prohibited as stage branch names.
3. **Credentials stay unresolved during admission.** DLP/rights/viewer gates run
   before any Hub token is required. Premature `HF_TOKEN` (and aliases) fails
   closed for gate verification.
4. **Tokens never appear in receipts.** Plan digests, gate results, and staging
   receipts are content-free of secrets and bearer material.
5. **Human approval is mandatory.** Dry-run records a receipt for review; it
   does not auto-stage, auto-sign, or auto-promote.
6. **A bare Viewer “valid” flag is never enough.** Every Dataset Viewer endpoint
   must agree with the staged inventory (offline fake gateway in dry-run).

## What dry-run answers

> Does this local multi-repo release tree have a consistent manifest, pass
> public-release DLP/rights gates and Viewer contracts, and yield a bound
> stage plan — without publishing to main or mutating remote defaults?

| Surface | Role |
| --- | --- |
| `stage_patent_hf_release.py --mode dry-run` | Manifest + plan + DLP/rights/viewer receipt |
| `tests/release/test_patent_hf_release_dry_run.py` | Contract tests (this task) |
| `docs/operations/PATENT_HF_RELEASE_V2.md` | Full build → stage → verify → rollback runbook |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | Post-completion catalog parent |

## Prerequisites

1. A **local staged release tree** from the v2 builder (PATLAW-157), for example:

   ```bash
   python scripts/ops/legal_data/build_patent_hf_release_v2.py \
     --input path/to/public_rows.json \
     --stage \
     --output-dir /var/tmp/patent-hf-v2-release
   ```

   The tree must include at least `release-manifest.json`, per-repo content under
   `repos/<name>/…`, quality/policy support files, README cards, dataset configs,
   and coverage metadata as required by DLP admission (PATLAW-158).

2. **Exact base revisions** per dataset id (audited parents). Never stage against
   an implicit “latest”.

   Example `base-revisions.json`:

   ```json
   {
     "justicedao/patent-legal-corpus": "<40-char-sha>",
     "justicedao/patent-legal-vectors": "<40-char-sha>",
     "justicedao/patent-legal-bm25": "<40-char-sha>",
     "justicedao/patent-legal-knowledge-graph": "<40-char-sha>"
   }
   ```

3. Hub tokens **unset** while running admission:

   ```bash
   unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACE_HUB_TOKEN HUGGINGFACE_TOKEN
   ```

## Operator command (authoritative dry-run)

```bash
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode dry-run \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --receipt-out /var/tmp/patent-hf-v2-dry-run-receipt.json \
  --require-admitted
```

Default `--mode` is already `dry-run`. Flags of interest:

| Flag | Meaning |
| --- | --- |
| `--require-admitted` | Exit `1` when DLP/rights/viewer admission is refused |
| `--skip-admission-gates` | Plan + manifest only (not recommended for production readiness) |
| `--as-of YYYY-MM-DD` | Freshness reference for mandatory sources |
| `--force-viewer-invalid` | Negative test: force Viewer gate failure |
| `--receipt-out PATH` | Write the staging receipt JSON |

### Validation (supervisor / CI)

```bash
python -m pytest tests/release/test_patent_hf_release_dry_run.py -q
```

## Receipt fields (staging receipt for human approval)

Successful dry-run receipts include (non-exhaustive):

| Field | Meaning |
| --- | --- |
| `status` | Always `dry_run_only` for this mode (no publish) |
| `verification_status` | `verified` \| `rejected` \| `plan_only` |
| `receipt_schema` | `patent-legal-hf-dry-run-staging-receipt/v1` |
| `task_id` / `goal_id` | `PATLAW-168` / `PATLAW-G202` |
| `plan_digest` / `staged_diff_digest` | Content-addressed plan bindings |
| `release_root_cid` | Release root CID from the manifest |
| `manifest_verified` | Local artifact digests matched the manifest |
| `dlp_rights_gates` | Full admission object (gate_results, reason_codes, …) |
| `viewer_contracts` | Viewer pass/fail + endpoints checked |
| `admitted` | Whether public-release admission passed |
| `main_published` | Always `false` in dry-run |
| `remote_default_branches_mutated` | Always `false` in dry-run |
| `remote_write_contacted` | Always `false` in dry-run |
| `tokens_used` | Always `false` in dry-run |
| `human_approval_required` | Always `true` |
| `next_operator_actions` | Ordered human steps before any live stage |

Gates expected under `dlp_rights_gates.gate_results`:

* `cards_configs`
* `parquet`
* `rights_dlp`
* `orphans`
* `count_parity`
* `stale_sources`
* `dataset_viewer`

## Interpreting outcomes

| Outcome | Meaning | Operator action |
| --- | --- | --- |
| `verification_status=verified`, exit 0 | Manifest + plan + admission passed | Review digests; proceed to human stage only if intentional |
| `verification_status=rejected` | Plan OK; admission refused | Fix tree (cards, rights, orphans, Viewer, …); re-run dry-run |
| Manifest / digest error | Local tree drifted from manifest | Rebuild or restore artifacts; never force-upload |
| Premature credentials error | Hub token present during admission | `unset` token env vars; re-run |
| `plan_only` (`--skip-admission-gates`) | Digests only | Not sufficient for production readiness |

## After a verified dry-run (human path only)

Dry-run **never** performs these steps. Operators do them intentionally with
scoped credentials and external approval keys:

```bash
# 1. Authenticated add-only stage (operator-held token; prefer --fake-service in drills)
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode stage \
  --fake-service \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --receipt-out /var/tmp/patent-hf-v2-staged.json

# 2. External operator HMAC approval (never a Hub token)
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode sign \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --operator-key-file /etc/patent-hf/operator.key \
  --approval-out /var/tmp/patent-hf-v2-approval.json

# 3. Promote only when digests still match
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode promote \
  --fake-service \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --approval-file /var/tmp/patent-hf-v2-approval.json \
  --staged-receipt-file /var/tmp/patent-hf-v2-staged.json \
  --operator-key-file /etc/patent-hf/operator.key \
  --receipt-out /var/tmp/patent-hf-v2-promoted.json
```

Pinned redownload, Viewer re-check, canary, and rollback remain
`verify_patent_hf_release_v2.py` (PATLAW-160). See
`docs/operations/PATENT_HF_RELEASE_V2.md`.

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Digest mismatch | Artifact edited after build | Rebuild staged tree |
| `card.missing_*` / `config.missing_*` | Incomplete builder output | Re-run build with full public coverage |
| `rights_dlp` fail | Private/mixed/unknown rights | Remove non-public rows; re-admit |
| `dataset_viewer` fail | Inventory/Viewer contract drift | Fix configs/shards; re-run with offline gateway |
| Premature credentials | Token env set too early | Unset tokens; re-run dry-run |
| Exit 1 with `--require-admitted` | Admission refused | Inspect `reason_codes` on the receipt |

## Related surfaces

| Surface | Role |
| --- | --- |
| `scripts/ops/legal_data/build_patent_hf_release_v2.py` | Local multi-repo build (PATLAW-157) |
| `scripts/ops/legal_data/verify_patent_hf_viewer.py` | Standalone DLP/Viewer gate CLI (PATLAW-158) |
| `scripts/ops/legal_data/verify_patent_hf_release_v2.py` | Pinned redownload + rollback (PATLAW-160) |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | Post-completion parent runbook |
| `docs/operations/PATENT_LEGAL_OPERATOR_HANDOFF.md` | Handoff receipt (PATLAW-169; binds this dry-run) |

## What this is not

* Not a live Hub main publication
* Not an unattended approve/publish path
* Not a substitute for pinned redownload verification after promote
* Not a legal opinion or rights determination beyond automated gates
* Not satisfied by board drained status alone
