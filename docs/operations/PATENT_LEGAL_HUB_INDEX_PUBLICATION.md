# Patent Legal Intelligence — Hub Index Publication (Promote Checklist)

**Task:** `PATLAW-178`  
**Goal:** `PATLAW-G213`  
**Track:** hub-index-verify  
**Depends on:** `PATLAW-176` (stage), pairs with `PATLAW-177` (pin-verify)  
**Code:** `scripts/ops/legal_data/prepare_patent_legal_hub_promote_checklist.py`  
**Tests:** `tests/unit/scripts/ops/legal_data/test_prepare_patent_legal_hub_promote_checklist.py`

This runbook is the **operator promote checklist** surface for multi-artifact
corpus + BM25 + vector + knowledge-graph Hub index packages. It binds exact
digests from a staged receipt into a content-free checklist of natural-person
actions. It does **not** promote, merge, pin, canary, contact the live Hub, or
store operator approval secrets in git.

## Standing rules (fail-closed)

1. **Checklist only.** `prepare_patent_legal_hub_promote_checklist.py` never
   performs promote, pointer moves, or Hub network I/O.
2. **No auto-promote path.** Every checklist step has
   `requires_human=true`, `automated_by_this_tool=false`, and
   `auto_promote=false`.
3. **Exact digests only.** The checklist binds `package_root_cid`,
   `plan_digest`, `staged_diff_digest`, per-projection digests, and staged
   commit SHAs. Floating revisions (`main`, `latest`, `HEAD`) are rejected.
4. **Credentials never appear.** Inputs and outputs are scanned for
   credential-shaped keys/values and fail closed.
5. **Evidence gaps are explicit.** Missing verification receipts or projection
   digests are listed; they are never invented as success.
6. **Natural-person approval is mandatory.** Supervisors and agents cannot
   self-approve promote. Sign and promote use operator-held keys outside git.

## What the checklist answers

> Given a PATLAW-176 stage (or dry-run) receipt — and optional admission /
> package / pin-verify receipts — what exact-digest human steps remain before
> corpus / BM25 / vector / graph artifacts may be promoted, pinned, canaried,
> or rolled back?

| Surface | Role |
| --- | --- |
| `prepare_patent_legal_hub_promote_checklist.py` | Checklist builder (this task) |
| `stage_patent_legal_hub_indexes.py` | Stage / sign / promote CLI (PATLAW-176) |
| `verify_patent_legal_hub_indexes.py` | Pinned redownload verify (PATLAW-177) |
| `admit_patent_legal_hub_indexes.py` | DLP/rights/Viewer admission (PATLAW-175) |
| `package_patent_legal_hub_indexes.py` | Multi-artifact package (PATLAW-174) |

## Prerequisites

1. A **stage or dry-run receipt** from PATLAW-176 that includes at least:

   * `package_root_cid` (or `release_root_cid`)
   * `plan_digest`
   * `staged_diff_digest`
   * preferably `repositories[].staged_commit_sha` and projection root CIDs

2. Recommended (reduces checklist gaps):

   * PATLAW-175 admission receipt (same `package_root_cid`)
   * PATLAW-174 package manifest
   * PATLAW-177 verification receipt (post-stage pin drill or post-promote)

## Operator command (authoritative)

```bash
python scripts/ops/legal_data/prepare_patent_legal_hub_promote_checklist.py \
  --stage-receipt /var/tmp/patent-hub-index-stage-receipt.json \
  --verification-receipt /var/tmp/patent-hub-index-verify-receipt.json \
  --admission-receipt /var/tmp/patent-hub-index-admission-receipt.json \
  --package-manifest /var/tmp/patent-hub-index-package/hub-index-package.manifest.json \
  --output /var/tmp/patent-hub-index-promote-checklist.json
```

Require a gap-free checklist (non-zero exit if gaps remain):

```bash
python scripts/ops/legal_data/prepare_patent_legal_hub_promote_checklist.py \
  --stage-receipt /var/tmp/patent-hub-index-stage-receipt.json \
  --verification-receipt /var/tmp/patent-hub-index-verify-receipt.json \
  --output /var/tmp/patent-hub-index-promote-checklist.json \
  --require-no-gaps
```

## Human steps encoded by the checklist

| step_id | Action | Automated by this tool? |
| --- | --- | --- |
| `review-evidence` | Confirm digests and staged SHAs | **No** |
| `sign-approval` | Sign exact-digest HMAC approval | **No** |
| `promote` | Run stage CLI `--mode promote` with approval | **No** |
| `pin-verify` | Pin promoted SHAs and redownload-verify | **No** |
| `canary` | Viewer/retrieval canary on **pinned** revisions only | **No** |
| `rollback` | Move approved pointer back if needed; never delete evidence | **No** |

## Promote path (outside this tool)

After the checklist is reviewed and signed off by a natural person, promote
remains on the **stage CLI** (not this checklist tool):

```bash
# 1) Sign (operator key file — never commit the key)
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode sign \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --operator-key-file /etc/patent-hf/operator-approval.key \
  --approver "operator@example.com" \
  --approval-id "approval-$(date -u +%Y%m%dT%H%M%SZ)" \
  --receipt-out /var/tmp/patent-hub-index-approval.json

# 2) Promote only with that exact approval + staged receipt
# Offline drill:
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode promote \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --approval-file /var/tmp/patent-hub-index-approval.json \
  --staged-receipt /var/tmp/patent-hub-index-stage-receipt.json \
  --operator-key-file /etc/patent-hf/operator-approval.key \
  --fake-service \
  --receipt-out /var/tmp/patent-hub-index-promote-receipt.json
```

Live Hub promote still requires an injected API client and operator credentials;
missing or wrong approval leaves default branches unchanged.

## Pin, canary, rollback

1. **Pin** each promoted commit SHA (never `main` / `latest` / `HEAD`).
2. **Redownload-verify** with `verify_patent_legal_hub_indexes.py` against the
   package digests bound in the checklist.
3. **Canary** on pinned revisions only.
4. **Rollback** moves only an approved pointer; audit evidence is retained.

## Validation

```bash
python -m pytest tests/unit/scripts/ops/legal_data/test_prepare_patent_legal_hub_promote_checklist.py -q
```

## Policy summary

| Control | Value |
| --- | --- |
| Auto-promote | Always `false` |
| Live network from checklist tool | Always `false` |
| Tokens in checklist | Forbidden |
| Unpinned revisions | Rejected |
| Human approval | Required for every step |
| Staged vs promoted disposition | Checklist remains `staged_not_promoted` until a separate promote receipt exists (PATLAW-179) |

## Related receipts

| Receipt | Producer |
| --- | --- |
| Stage / dry-run | PATLAW-176 `stage_patent_legal_hub_indexes.py` |
| Admission | PATLAW-175 `admit_patent_legal_hub_indexes.py` |
| Pin-verify | PATLAW-177 `verify_patent_legal_hub_indexes.py` |
| Promote checklist | **PATLAW-178** (this document) |
| Publication receipt (staged vs promoted) | PATLAW-179 |
