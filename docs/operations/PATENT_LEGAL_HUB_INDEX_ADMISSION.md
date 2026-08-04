# Patent Legal Intelligence — Hub Index Package Admission

**Task:** `PATLAW-175`  
**Goal:** `PATLAW-G212`  
**Track:** hub-index-package  
**Depends on:** `PATLAW-158`, `PATLAW-174`  
**Code:** `scripts/ops/legal_data/admit_patent_legal_hub_indexes.py`  
**Tests:** `tests/security/test_patent_legal_hub_index_admission.py`

This runbook is the operator surface for **fail-closed DLP, rights, and Dataset
Viewer admission** of multi-artifact corpus + BM25 + vector + knowledge-graph
Hub index packages produced by PATLAW-174. It emits an admission receipt that
binds the package root and every gate outcome. It does **not** authenticate to
Hugging Face, upload artifacts, open pull requests, or move runtime pointers.

## Standing rules (fail-closed)

1. **Credentials stay unresolved during admission.** DLP/rights/viewer gates run
   before any Hub token is required. Premature `HF_TOKEN` (and aliases) fails
   closed.
2. **Tokens never appear in receipts.** Findings and admission receipts are
   content-free of secrets and bearer material (value digests only).
3. **Private / mixed / unknown rights never admit.** Package rights/privacy
   summaries and every artifact descriptor are checked; private classification
   or non-public privacy classes block.
4. **Secret-like leakage never admits.** Plaintext Hub-token shapes, private
   markers, and adversarial encoded payloads in package files block.
5. **Orphan rows never admit.** Graph snapshot `orphan_check` failures and
   quality-report orphan joins block.
6. **Invalid Parquet never admits.** Corrupt or unreadable Parquet shards
   projected into the inventory fail the Parquet gate.
7. **A bare Viewer “valid” flag is never enough.** Every Dataset Viewer endpoint
   must agree with the projected inventory (offline fake gateway).
8. **No Hub upload.** This command never contacts the live Hub for publication.

## What admission answers

> Does this local hub index package pass public-release DLP/rights gates and
> Viewer contracts, and yield a receipt that binds `package_root_cid` and gate
> outcomes — without resolving credentials or publishing?

| Surface | Role |
| --- | --- |
| `admit_patent_legal_hub_indexes.py` | Package + DLP/rights/Viewer admission CLI |
| `tests/security/test_patent_legal_hub_index_admission.py` | Security contract tests |
| `package_patent_legal_hub_indexes.py` | Package builder (PATLAW-174) |
| `verify_patent_hf_viewer.py` | Standalone release-tree DLP/Viewer (PATLAW-158) |

## Prerequisites

1. A **staged hub index package** from PATLAW-174, for example:

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
     (README cards, `dataset_configs.json`, `coverage.json`)

2. Hub tokens **unset** while running admission:

   ```bash
   unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACE_HUB_TOKEN HUGGINGFACE_TOKEN
   ```

## Operator command (authoritative)

```bash
python scripts/ops/legal_data/admit_patent_legal_hub_indexes.py \
  --package-dir /var/tmp/patent-hub-index-package \
  --receipt-out /var/tmp/patent-hub-index-admission.json
```

Or materialize the built-in multi-family fixture and admit in one step:

```bash
python scripts/ops/legal_data/admit_patent_legal_hub_indexes.py \
  --default-fixture \
  --stage-dir /var/tmp/patent-hub-index-package \
  --receipt-out /var/tmp/patent-hub-index-admission.json \
  --json
```

### Flags

| Flag | Meaning |
| --- | --- |
| `--package-dir PATH` | Staged hub index package (PATLAW-174 output) |
| `--default-fixture` | Build the CI multi-family package and admit it |
| `--stage-dir PATH` | Staging directory for `--default-fixture` |
| `--as-of YYYY-MM-DD` | Freshness reference for mandatory sources |
| `--max-source-age-days N` | Maximum age of mandatory sources (default 400) |
| `--skip-viewer-gate` | Skip Dataset Viewer contracts (not recommended) |
| `--force-viewer-invalid` | Negative test: force Viewer `is-valid=false` |
| `--allow-reject` | Do not raise on refusal (still non-zero exit when rejected) |
| `--receipt-out PATH` | Write the admission receipt JSON |
| `--json` | Print the full receipt to stdout |

### Validation (supervisor / CI)

```bash
python -m pytest tests/security/test_patent_legal_hub_index_admission.py -q
```

## Gates

Admission runs **package-level** gates first, then projects the package into a
release-policy inventory and runs PATLAW-158 inventory gates offline.

### Package gates

| Gate | Blocks when |
| --- | --- |
| `package_integrity` | Missing manifest/repos/index trees, non-public partition, missing index families |
| `package_rights_privacy` | Unreviewed rights, redistribution denied, non-public privacy, private/mixed/unknown classifications on artifacts |
| `package_dlp` | Secret-like or private-marker leakage in package JSON/text artifacts |
| `package_orphans` | Graph snapshot `orphan_check` not pass, positive orphan joins |

### Policy / Viewer gates (PATLAW-158)

| Gate | Blocks when |
| --- | --- |
| `cards_configs` | Missing README / dataset_configs / coverage / support files |
| `parquet` | Invalid magic, unreadable, empty, or row-count-mismatched Parquet |
| `rights_dlp` | Policy receipt not admitted, private classification summary, secret findings |
| `orphans` | Quality-report orphan joins / failed orphan_check / structural orphans |
| `count_parity` | Manifest vs quality vs inventory count drift |
| `stale_sources` | Stale or missing mandatory sources |
| `dataset_viewer` | Any Viewer endpoint contract mismatch (`is-valid`, `splits`, `rows`, `parquet`, `size`, `statistics`) |

## Admission receipt fields

Successful receipts include (non-exhaustive):

| Field | Meaning |
| --- | --- |
| `receipt_schema` | `patent-legal-hub-index-admission-receipt/v1` |
| `task_id` / `goal_id` | `PATLAW-175` / `PATLAW-G212` |
| `admitted` | Whether public admission passed |
| `package_root_cid` | Content-addressed package root (bound) |
| `package_digest_sha256` | Package content digest |
| `corpus_root_cid` / `bm25_root_cid` / `vector_root_cid` / `graph_root_cid` | Family pins |
| `index_families_present` | `bm25`, `vectors`, `knowledge_graph` |
| `gate_results` | Ordered gate outcomes (name, passed, reason_codes, details) |
| `reason_codes` | Sorted union of blocking reasons (empty when admitted) |
| `findings` | DLP findings (value digests only; no secret plaintext) |
| `policy_version` / `policy_sha256` | Release policy v2 pin |
| `viewer_contracts` | Viewer pass/fail + endpoints checked |
| `receipt_digest_sha256` | Digest over bound receipt body |
| `credentials_resolved` | Always `false` |
| `tokens_used` | Always `false` |
| `hub_upload` | Always `false` |

The receipt **binds** `package_root_cid` to the same gate outcomes operators
review before any authenticated stage (PATLAW-176).

## Interpreting outcomes

| Outcome | Meaning | Operator action |
| --- | --- | --- |
| `admitted=true`, exit 0 | Package + DLP/rights/Viewer passed | Review digests; proceed to human stage only if intentional |
| `admitted=false`, exit 1 | Admission refused | Fix package (rights, leakage, orphans, Viewer, …); re-run |
| Exit 2 / ERROR | Unusable input or premature credentials | Restore package tree or `unset` token env vars |
| Premature credentials | Hub token present during admission | Unset tokens; re-run |

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `package.missing_*` | Incomplete package stage | Re-run PATLAW-174 packager with `--stage` |
| `rights.*` / `privacy.*` / `classification.*` | Private/mixed/unknown rights | Remove non-public artifacts; re-package |
| `content.secret_or_encoded_leakage` | Token/private marker in package files | Scrub content; re-package; never force-admit |
| `orphan.*` | Graph orphan check failed | Rebuild knowledge graph; re-package |
| `parquet.*` | Corrupt Parquet in inventory | Rebuild data shards; re-admit |
| `viewer.not_valid` / `viewer.*` | Inventory/Viewer contract drift | Fix cards/configs; re-run with offline gateway |
| Premature credentials | Token env set too early | Unset tokens; re-run admission |

## After a successful admission (human path only)

Admission **never** performs these steps. Operators do them intentionally with
scoped credentials and external approval (PATLAW-176+):

1. Stage an add-only Hub branch/PR enumerating corpus/BM25/vector/graph artifacts.
2. Obtain operator-signed approval binding the package root and staged diff.
3. Promote only when digests still match.
4. Verify pinned Hub redownload and Viewer contracts after promote.

See `docs/operations/PATENT_LEGAL_HUB_DRY_RUN.md` and
`docs/operations/PATENT_HF_RELEASE_V2.md` for the related release dry-run and
full publish path.

## Related surfaces

| Surface | Role |
| --- | --- |
| `scripts/ops/legal_data/package_patent_legal_hub_indexes.py` | Multi-artifact package (PATLAW-174) |
| `scripts/ops/legal_data/verify_patent_hf_viewer.py` | Standalone DLP/Viewer gate CLI (PATLAW-158) |
| `scripts/ops/legal_data/stage_patent_hf_release.py` | HF release dry-run / stage (PATLAW-159/168) |
| `ipfs_datasets_py/processors/domains/patent/hf_release_policy_v2.py` | Release policy v2 gates |
| `ipfs_datasets_py/processors/domains/patent/hub_index_package.py` | Package builder module |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | Post-completion parent runbook |

## What this is not

* Not a live Hub main publication
* Not an unattended approve/publish path
* Not a substitute for pinned redownload verification after promote
* Not a legal opinion or rights determination beyond automated gates
* Not satisfied by board drained status alone
* Not allowed to weaken DLP or auto-pass private leakage
