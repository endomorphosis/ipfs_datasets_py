# Patent Legal Intelligence — Hub Index Package Staging

**Task:** `PATLAW-176`  
**Goal:** `PATLAW-G212`  
**Track:** hub-index-package  
**Depends on:** `PATLAW-159`, `PATLAW-175`  
**Code:** `scripts/ops/legal_data/stage_patent_legal_hub_indexes.py`  
**Tests:** `tests/integration/processors/patent/test_stage_patent_legal_hub_indexes.py`

This runbook is the operator surface for **authenticated Hub PR staging** of
multi-artifact corpus + BM25 + vector + knowledge-graph Hub index packages.
It projects a PATLAW-174 package (after PATLAW-175 admission) into an add-only
stage plan, opens staged pull requests against exact base revisions, and
requires a separate operator-signed approval before promote. It does **not**
upload to Hub `main` by default, auto-approve, move runtime pointers, or
embed Hub tokens in receipts.

## Standing rules (fail-closed)

1. **Default is dry-run.** Planning never contacts the live Hub for
   publication and never mutates remote default branches.
2. **No direct-main upload.** Stage branches are add-only
   (`stage/patent-legal/…`); `main` / `master` are prohibited as stage branch
   names.
3. **Exact operator approval is mandatory.** Promote consumes an external
   HMAC-signed approval that binds `plan_digest`, `staged_diff_digest`, and
   `package_root_cid` (as `release_root_cid`). The publisher cannot generate
   the approval it consumes.
4. **Missing or wrong approval cannot publish.** Fake-service tests prove
   empty approvals, wrong signatures, foreign keys, agent self-approval,
   base races, artifact drift, conflicts, partial uploads, and auth failures
   leave `main` unchanged.
5. **Credentials never appear in receipts.** Plan digests, stage receipts,
   approvals, and promote receipts are content-free of Hub tokens and bearer
   material.
6. **No unattended promote.** Supervisor / agent approver identities are
   rejected. Sign and promote require an operator key file (or
   `PATENT_HF_OPERATOR_APPROVAL_KEY`).
7. **Live Hub is operator-invoked only.** Stage/promote without
   `--fake-service` refuses implicit `HfApi` construction; CI uses the
   in-memory fake Hub service.

## What staging answers

> Does this admitted hub index package produce a multi-repo add-only stage
> plan that enumerates corpus / BM25 / vector / graph artifacts, yield a
> staged commit/diff identity for exact operator approval, and refuse to
> publish `main` without that approval — without leaking credentials?

| Surface | Role |
| --- | --- |
| `stage_patent_legal_hub_indexes.py` | Stage CLI (dry-run / stage / sign / promote) |
| `tests/integration/processors/patent/test_stage_patent_legal_hub_indexes.py` | Fake-service contract tests |
| `package_patent_legal_hub_indexes.py` | Package builder (PATLAW-174) |
| `admit_patent_legal_hub_indexes.py` | DLP/rights/Viewer admission (PATLAW-175) |
| `hf_publisher_v2.py` | Publisher contracts (PATLAW-159) |

## Prerequisites

1. A **staged hub index package** from PATLAW-174:

   ```bash
   python scripts/ops/legal_data/package_patent_legal_hub_indexes.py \
     --default-fixture \
     --stage \
     --output-dir /var/tmp/patent-hub-index-package
   ```

   The tree must include at least:

   * `hub-index-package.manifest.json`
   * `package-root.json`
   * `artifacts-inventory.json`
   * `indexes/{corpus,bm25,vectors,knowledge_graph}/…`
   * `repos/patent-legal-{corpus,bm25,vectors,knowledge-graph}/…`

2. An **admission receipt** from PATLAW-175 (recommended / required with
   `--require-admission`):

   ```bash
   python scripts/ops/legal_data/admit_patent_legal_hub_indexes.py \
     --package-dir /var/tmp/patent-hub-index-package \
     --receipt-out /var/tmp/patent-hub-index-package/hub-index-admission-receipt.json
   ```

3. **Exact base revisions** per dataset id (audited parents). Never stage
   against an implicit “latest”.

   Example `base-revisions.json`:

   ```json
   {
     "justicedao/patent-legal-corpus": "<40-char-sha>",
     "justicedao/patent-legal-vectors": "<40-char-sha>",
     "justicedao/patent-legal-bm25": "<40-char-sha>",
     "justicedao/patent-legal-knowledge-graph": "<40-char-sha>"
   }
   ```

## Operator command (authoritative dry-run)

Default mode never contacts the Hub:

```bash
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode dry-run \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --admission-receipt /var/tmp/patent-hub-index-package/hub-index-admission-receipt.json \
  --require-admission \
  --receipt-out /var/tmp/patent-hub-index-dry-run-receipt.json
```

Or materialize the built-in multi-family fixture and dry-run in one step:

```bash
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode dry-run \
  --default-fixture \
  --stage-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --receipt-out /var/tmp/patent-hub-index-dry-run-receipt.json
```

### Flags

| Flag | Meaning |
| --- | --- |
| `--mode dry-run\|stage\|sign\|promote` | Workflow mode (default: `dry-run`) |
| `--package-dir PATH` | Staged hub index package (PATLAW-174) |
| `--default-fixture` | Build the CI multi-family package then operate |
| `--stage-dir PATH` | Staging directory for `--default-fixture` |
| `--base-revisions-file PATH` | Dataset id → audited base commit SHA |
| `--base-revisions JSON` | Inline base revision map |
| `--admission-receipt PATH` | PATLAW-175 admission receipt binding package root |
| `--require-admission` | Fail closed without a valid admitted receipt |
| `--branch-name NAME` | Override stage branch (must not be `main`/`master`) |
| `--receipt-out PATH` | Write dry-run / stage / promote receipt JSON |
| `--fake-service` | In-memory FakeHubService (no network; CI-safe) |
| `--operator-key-file PATH` | External operator HMAC key (sign/promote) |
| `--approval-out PATH` | Write operator approval JSON (sign) |
| `--approval-file PATH` | Consume operator approval (promote) |
| `--staged-receipt-file PATH` | Staged PR receipt from stage mode (promote) |
| `--no-create-pr` | Stage commits without opening pull requests |
| `--write-release-manifest-only` | Project package → `release-manifest.json` and exit |
| `--list-index-families` | Print required index family names and exit |

### Validation (supervisor / CI)

```bash
python -m pytest tests/integration/processors/patent/test_stage_patent_legal_hub_indexes.py -q
```

## Workflow

### 1. Dry-run (default)

1. Load package pins and verify corpus + three index families on disk.
2. Optionally bind a PATLAW-175 admission receipt to `package_root_cid`.
3. Project package artifacts into a publisher-compatible release manifest
   (written as `release-manifest.json` under the package dir).
4. Build an offline stage plan with `plan_digest` and `staged_diff_digest`.
5. Emit a dry-run receipt (`status=dry_run_only`) for human review.

Dry-run never sets `tokens_used`, never contacts the Hub, and never mutates
`main`.

### 2. Stage (add-only branch + PR)

Offline / CI:

```bash
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode stage \
  --fake-service \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --receipt-out /var/tmp/patent-hub-index-staged.json
```

Live Hub stage requires an **operator-injected** authenticated API client
(this CLI refuses to construct `HfApi` implicitly). Use an operator-controlled
process that wraps `PatentHFPublisherV2` with a reviewed client.

Stage effects:

* Creates add-only branches from audited bases.
* Uploads only manifest-enumerated artifacts via `create_commit`.
* Opens pull requests (unless `--no-create-pr`).
* Leaves `main` at the audited base commit.
* Returns staged commit SHAs and PR numbers for approval.

### 3. Sign (external operator key)

```bash
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode sign \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --operator-key-file /etc/patent-hf/operator-approval.key \
  --approver "patent-legal-operator" \
  --approval-id "ops-2026-08-04-1" \
  --approval-out /var/tmp/patent-hub-index-approval.json
```

Approver identities matching implementation-agent / agent-supervisor /
auto-approve / unattended markers are rejected.

### 4. Promote (only after exact approval)

```bash
python scripts/ops/legal_data/stage_patent_legal_hub_indexes.py \
  --mode promote \
  --fake-service \
  --package-dir /var/tmp/patent-hub-index-package \
  --base-revisions-file /etc/patent-hf/base-revisions.json \
  --operator-key-file /etc/patent-hf/operator-approval.key \
  --approval-file /var/tmp/patent-hub-index-approval.json \
  --staged-receipt-file /var/tmp/patent-hub-index-staged.json \
  --receipt-out /var/tmp/patent-hub-index-promoted.json
```

Promote re-checks bases, artifact digests, and the operator signature. Any
mismatch fails closed without publishing. Runtime pointer promotion remains
owned by later verify/promote-checklist tasks (PATLAW-177 / PATLAW-178 /
PATLAW-160).

## Receipt fields (dry-run / stage)

| Field | Meaning |
| --- | --- |
| `task_id` / `goal_id` | `PATLAW-176` / `PATLAW-G212` |
| `package_root_cid` | Bound package content identity |
| `plan_digest` / `staged_diff_digest` | Content-addressed stage plan pins |
| `index_families_present` | `bm25`, `vectors`, `knowledge_graph` |
| `projection_artifact_counts` | Per-family artifact counts in the plan |
| `repository_ids` | Canonical multi-repo dataset ids |
| `main_published` | Always `false` until successful promote |
| `pointers_moved` | Always `false` (not owned by this task) |
| `tokens_used` | Always `false` in receipts |
| `live_network` / `fake_service` | Network posture of the run |
| `human_approval_required` | Always `true` for stage path |
| `admission_bound` | Whether a valid admission receipt was bound |

## Projection mapping

| Local package path | Hub repository |
| --- | --- |
| `repos/patent-legal-corpus/…` | `justicedao/patent-legal-corpus` |
| `repos/patent-legal-bm25/…` | `justicedao/patent-legal-bm25` |
| `repos/patent-legal-vectors/…` | `justicedao/patent-legal-vectors` |
| `repos/patent-legal-knowledge-graph/…` | `justicedao/patent-legal-knowledge-graph` |
| `indexes/corpus/…` | corpus |
| `indexes/bm25/…` | bm25 |
| `indexes/vectors/…` | vectors |
| `indexes/knowledge_graph/…` | knowledge_graph |
| Package support pins (`hub-index-package.manifest.json`, …) | corpus |

## Failure modes (must not publish main)

| Condition | Outcome |
| --- | --- |
| Missing / wrong operator approval | `ApprovalError`; main unchanged |
| Foreign operator key | `ApprovalError`; main unchanged |
| Agent / supervisor approver | Rejected at sign |
| Base revision advanced after audit | `BaseRevisionError`; stage/promote aborted |
| Local artifact digest drift | `ArtifactChangedError` |
| Branch conflict | `ConflictError` |
| Partial multi-repo upload | `PartialUploadError`; main unchanged |
| Auth failure | `AuthError` |
| Direct `main` branch name | `DirectMainUploadError` |
| Missing index family / repo tree | Stage plan refused |
| Admission not bound when required | `AdmissionRequiredError` |
| Admission CID mismatch | `AdmissionMismatchError` |
| Live stage without injected API | Fail closed (use `--fake-service` in CI) |

## Related surfaces

| Surface | Role |
| --- | --- |
| `scripts/ops/legal_data/package_patent_legal_hub_indexes.py` | Multi-artifact package (PATLAW-174) |
| `scripts/ops/legal_data/admit_patent_legal_hub_indexes.py` | Admission gates (PATLAW-175) |
| `scripts/ops/legal_data/stage_patent_hf_release.py` | HF release dry-run / stage (PATLAW-159/168) |
| `ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py` | Publisher + FakeHubService |
| `ipfs_datasets_py/processors/domains/patent/hub_index_package.py` | Package builder module |
| `docs/operations/PATENT_LEGAL_HUB_INDEX_ADMISSION.md` | Admission runbook |
| `docs/operations/PATENT_HF_RELEASE_V2.md` | Full HF v2 publication runbook |

## What this is not

* Not a live Hub main publication without exact operator approval
* Not an unattended approve/publish path
* Not a substitute for pinned redownload verification after promote (PATLAW-177)
* Not a pointer canary / rollback workflow (PATLAW-160 / PATLAW-178)
* Not allowed to embed Hub tokens or operator keys in git or receipts
* Not allowed to weaken DLP or skip admission when `--require-admission` is set
