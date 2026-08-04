# Patent / Legal Hugging Face Release v2 — Operator Runbook

**Tasks:** `PATLAW-156` … `PATLAW-160`  
**Goal:** `PATLAW-G182`  
**Track:** hub-publication  
**Code:**

| Concern | Module / script |
| --- | --- |
| Layout contracts | `ipfs_datasets_py/processors/domains/patent/hf_layout_v2.py` |
| Deterministic multi-repo build | `ipfs_datasets_py/processors/domains/patent/hf_release_v2.py` |
| DLP / rights / Viewer admission | `ipfs_datasets_py/processors/domains/patent/hf_release_policy_v2.py` |
| Staged PR + exact operator approval | `ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py` |
| Build (dry-run / stage local) | `scripts/ops/legal_data/build_patent_hf_release_v2.py` |
| Stage / sign / promote | `scripts/ops/legal_data/stage_patent_hf_release.py` |
| Viewer / DLP gate | `scripts/ops/legal_data/verify_patent_hf_viewer.py` |
| **Pinned redownload + rollback** | `scripts/ops/legal_data/verify_patent_hf_release_v2.py` |

This document is the **operator-facing** runbook for JusticeDAO multi-repository
public patent/legal releases. Live Hub publication is always an **explicit
operator action**. Implementation agents and the supervisor must never upload,
self-approve, move runtime pointers, or select a floating tip.

---

## Principles (fail-closed)

1. **Default is dry-run.** Planning never contacts the Hub, never reads
   `HF_TOKEN`, and never moves pointers.
2. **No direct-main upload.** Artifacts land on add-only stage branches; main
   advances only after exact operator approval of the plan + staged-diff
   digests (`PATLAW-159`).
3. **Credentials are scoped references.** Tokens never appear in plans,
   approvals, receipts, logs, or pointer documents.
4. **Pointer promotion waits for pinned redownload.** Floating revisions
   (`main`, `latest`, `HEAD`, empty) are refused for verification downloads.
5. **Viewer contracts are mandatory before canary.** A bare `viewer: true`
   HTTP response is never sufficient; every Dataset Viewer endpoint must agree
   with the staged inventory.
6. **Rollback changes only the reviewed pointer.** Release commits and audit
   evidence are retained; the rollback receipt is itself content-addressed and
   verifiable.
7. **`upload_file` is prohibited.** Publication uses `create_commit` only.

---

## End-to-end pipeline

```text
rows / sources
    │
    ▼
build_patent_hf_release_v2.py --stage     (local multi-repo tree + manifest)
    │
    ▼
verify_patent_hf_viewer.py                (DLP / rights / Viewer admission)
    │
    ▼
stage_patent_hf_release.py --mode dry-run (plan digests, no Hub)
    │
    ▼
stage_patent_hf_release.py --mode stage   (add-only branch + PR per repo)
    │
    ▼
stage_patent_hf_release.py --mode sign    (external operator key HMAC)
    │
    ▼
stage_patent_hf_release.py --mode promote (merge after re-check bases/artifacts)
    │
    ▼
verify_patent_hf_release_v2.py            (pinned redownload → Viewer → canary)
    │
    ▼
verify_patent_hf_release_v2.py            (approval-bound rollback drill)
```

Repository roles (lowercase Hub ids under `justicedao/`):

| Role | Repository |
| --- | --- |
| Corpus | `patent-legal-corpus` |
| Vectors | `patent-legal-vectors` |
| BM25 | `patent-legal-bm25` |
| Knowledge graph | `patent-legal-knowledge-graph` |

Support files (manifest companions, policy receipts) stage to the **corpus**
repository by default.

---

## 1. Build a local release candidate

```bash
python scripts/ops/legal_data/build_patent_hf_release_v2.py \
  --input path/to/public_rows.json \
  --stage \
  --output-dir /var/tmp/patent-hf-v2-release \
  --print-manifest
```

Without `--stage` the builder is dry-run only (no filesystem staging, no
upload). Private or mixed classification batches fail before staging.

The staged tree must contain at least:

* `release-manifest.json` — artifact digests, `release_root_cid`, repositories
* per-repo content under `repos/<name>/…`
* quality / policy support files as produced by the builder

---

## 2. Admit public-release gates (credentials unresolved)

```bash
# Ensure Hub tokens are NOT set before admission.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACE_HUB_TOKEN HUGGINGFACE_TOKEN

python scripts/ops/legal_data/verify_patent_hf_viewer.py \
  --release-dir /var/tmp/patent-hf-v2-release \
  --json
```

Admission must pass with credentials still unresolved. Premature token
presence fails closed.

---

## 3. Stage an authenticated Hub PR (exact human approval)

Declare **exact base revisions** per dataset (audited parents). Never stage
against an implicit “latest”.

```bash
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode dry-run \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --receipt-out /var/tmp/patent-hf-v2-plan.json
```

Operator workflow after reviewing the plan digest and staged-diff digest:

1. `--mode stage` — create add-only branches + PRs (operator-held token).
2. `--mode sign` — HMAC-sign with an **external** operator key file
   (`--operator-key-file` or `$PATENT_HF_OPERATOR_APPROVAL_KEY`).
3. `--mode promote` — merge only when approval binds the same digests and
   bases/artifacts have not drifted.

Fail-closed conditions (main and pointers stay untouched):

* missing / wrong / self-generated approval
* base revision advanced after audit (race)
* local or remote artifact digest/size change
* branch / path / merge conflict
* partial multi-repo upload
* auth error
* direct write to `main` / `master`

The publisher **never** generates the operator approval it consumes and
**never** moves runtime release pointers (`PATLAW-160`).

Offline supervisor drill:

```bash
python scripts/ops/legal_data/stage_patent_hf_release.py \
  --mode stage \
  --fake-service \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json
```

---

## 4. Verify pinned Hub downloads (blocks promotion on failure)

After promotion, redownload **every** manifest file at the **exact Hub commit
SHA** for its repository. Floating tips are refused.

### Dry-run (default — no Hub contact)

```bash
python scripts/ops/legal_data/verify_patent_hf_release_v2.py \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --print-receipt
```

### Full offline gate sequence (supervisor / CI)

```bash
python scripts/ops/legal_data/verify_patent_hf_release_v2.py \
  --local-root /var/tmp/patent-hf-v2-release \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --fake-live \
  --canary-percent 10 \
  --receipt-path /var/tmp/patent-hf-v2-verify-receipt.json
```

Gates (all required; any failure blocks canary / promotion readiness):

| Gate | Requirement |
| --- | --- |
| `dry_run_plan` | Local plan digests; local artifact integrity |
| `stage_and_promote` | Fake/live promote with exact operator approval |
| `pointer_blocked_before_pin` | Canary refused without pinned redownload |
| `pinned_redownload` | Every artifact redownloaded at exact commit SHA; SHA/size/CID bind |
| `unpinned_request_blocked` | `main` / `latest` / empty / wrong SHA refused |
| `viewer_contracts` | All Viewer endpoints agree with staged inventory |
| `canary_promotion` | Reviewed pointer advanced under canary % |
| `rollback` | Previous pointer restored; only pointer changed |
| `rollback_verifiable` | Rollback receipt digest pin-able; failed commits retained |

### What a successful receipt binds

* `repository_ids` and per-repo `repository_commits` (Hub SHAs)
* `release_root_cid` and `release_id`
* `plan_digest` / `staged_diff_digest` / `approval_id`
* `artifact_hashes` and full `artifact_pins` (path, sha256, size, commit)
* `pinned_redownload_digest`
* Viewer results (`viewer_endpoints`, reason codes if any)
* canary pointer document + digest
* rollback pointer + `rollback_receipt_digest`

Any **missing artifact**, **changed digest/size**, **unpinned request**,
**Viewer failure**, or **manifest mismatch** blocks promotion.

Reviewed runtime pointer path (default):

```text
runtime/patent_legal_release_pointer_v2.json
```

The pointer is a multi-repo document: each `dataset_id` maps to a pinned
commit SHA, plus previous release identity for rollback.

---

## 5. Rollback procedure

Rollback is an operator-reviewed pointer move. It:

* restores the previous release id, release root CID, and repository commits;
* retains the failed candidate as `previous_*` on the new pointer;
* **does not** delete Hub commits, artifacts, stage branches, or audit
  receipts;
* emits a content-addressed rollback receipt (`rollback_receipt_digest`) that
  is itself pin-able and verifiable.

The fake-live path exercises rollback automatically after canary. For an
operator drill after a real canary:

1. Confirm the current reviewed pointer document and its `pointer_digest`.
2. Confirm previous repository commits still resolve on the Hub.
3. Apply rollback only to the reviewed pointer (never rewrite release trees).
4. Re-run pinned redownload against the **restored** commit SHAs before
   returning traffic to 100%.
5. Archive the rollback receipt digest with the incident record.

If rollback would require deleting commits or artifacts, **stop** — that is
out of policy.

---

## 6. Validation commands

```bash
# Layout / build / DLP (prior tasks)
python -m pytest \
  tests/unit/processors/patent/test_hf_layout_v2.py \
  tests/unit/processors/patent/test_hf_release_v2.py \
  tests/security/test_patent_hf_release_v2.py -q

# Staged PR + exact approval (PATLAW-159)
python -m pytest tests/integration/processors/patent/test_hf_publication_v2.py -q

# Pinned redownload + rollback (PATLAW-160)
python -m pytest tests/release/test_patent_hf_release_v2.py -q
```

---

## 7. Explicit non-goals / prohibited actions

| Prohibited | Why |
| --- | --- |
| Direct upload to `main` / `master` | Bypasses staged PR + approval |
| `HfApi.upload_file` | Non-append path; not auditable as create_commit |
| Unattended / agent self-approval | Approval key is external operator material |
| Selecting `latest` or floating `main` for verify | Pin gate fails closed |
| Promoting pointer before pin + Viewer | Canary refuses |
| Deleting release commits on rollback | Audit evidence must remain |
| Embedding `HF_TOKEN` in receipts | Credential leak |

---

## 8. Incident checklist

When verification fails after promote:

1. **Do not** canary-promote the runtime pointer.
2. Capture the verification receipt (or error) and plan digests.
3. Diff local manifest digests against Hub paths at the **promoted** SHAs.
4. If any artifact drifted, treat the promotion as non-authoritative for
   runtime traffic; open a new stage from a repaired local tree.
5. If Viewer contracts fail, fix inventory / cards / parquet projections
   offline and re-admit via `verify_patent_hf_viewer.py` before re-staging.
6. If a bad canary already moved the pointer, execute §5 rollback and keep
   both pointer digests.

---

## Related documents

* Architecture goal `PATLAW-G182` (stage, approve, publish, verify, roll back)
* `docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md` — separate filing gate
* v1 append-only publisher profile (legacy single-repo path) remains available
  via `scripts/ops/legal_data/verify_patent_hf_release.py` and must not weaken
  v2 multi-repo pin/Viewer/rollback obligations above
