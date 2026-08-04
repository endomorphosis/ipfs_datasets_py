# Patent Legal Intelligence — USPTO Guidance PDF Acquisition

**Task:** `PATLAW-185`  
**Goal:** `PATLAW-G217`  
**Track:** hub-full-authority-uspto-guidance  
**Depends on:** `PATLAW-184` (inventory contracts + schema)  
**CLI:** `scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py`  
**Contracts:** `ipfs_datasets_py/processors/domains/patent/uspto_guidance_pdf_contracts.py`  
**Schema:** `data/release/patent_legal_intelligence/uspto_guidance_pdfs.manifest.schema.json`  
**Tests:** `tests/integration/processors/patent/test_acquire_uspto_guidance_pdfs.py`

This runbook is the operator surface for **acquiring and pinning USPTO
examination guidance PDFs** as public corpus sources. It materializes a pinned
inventory of official guidance PDFs, hash-verifies PDF bytes, extracts
deterministic indexable text, and emits an acquisition receipt with digests.

It does **not** upload to Hugging Face Hub, open publication PRs, or elevate
guidance to binding law. Prior / superseded editions are **retained as
evidence** (never silently deleted).

## Standing rules (fail-closed)

1. **Pinned document identity only.** Every PDF binds a concrete
   `document_id` **and** `version` (or dated edition token). The hard-coded
   token `latest` is rejected on selection fields and URIs.
2. **Required bindings.** Each inventory row binds `uri`, `sha256` (of PDF
   bytes), `publication_date`, `cutoff`, page metadata, and a reviewed public
   `rights_review`.
3. **Hash verification.** Acquired PDF bytes must match the pinned `sha256`
   when an expected digest is supplied; offline catalog digests are computed
   from the materialized bytes and rebound into the inventory.
4. **Deterministic text extraction.** Identical PDF bytes under the pinned
   method (`pdf-text-v1`) and normalization profile
   (`unicode-nfc-ws-collapse-v1`) always yield the same `text_sha256`.
5. **Guidance is never law.** `authority_tier=guidance`, `is_binding=false`.
   Supersession edges retain both endpoints as guidance evidence.
6. **Public-only admission.** Non-public classifications, non-`public`
   partitions, and failed-auth packages fail closed.
7. **No Hub upload.** This CLI stages local artifacts only. Republication is a
   later task under the Hub track.
8. **Offline CI path.** Validation uses the offline required catalog
   (deterministic synthetic PDFs). Live USPTO download is optional and not
   required for the pytest gate.

## What acquisition answers

> For a pinned set of USPTO examination guidance PDFs, do we have an inventory
> where every required document is present with hash-verified PDF bytes and
> deterministic extracted text digests, without admitting non-public or
> failed-auth packages?

| Surface | Role |
| --- | --- |
| `acquire_uspto_guidance_pdfs.py` | Offline (default) or staged acquisition CLI |
| `uspto_guidance_pdf_contracts.py` | Inventory schema / builders (PATLAW-184) |
| `uspto_guidance_pdfs.manifest.schema.json` | Release JSON Schema for inventory manifests |
| `test_acquire_uspto_guidance_pdfs.py` | Integration acceptance (this task) |

## Prerequisites

1. **PATLAW-184 contracts** are present on the tree (inventory types, required
   document catalog, JSON Schema, text-extraction contracts).
2. Optional: a writable local staging directory for `--stage` output (not under
   protected architecture paths).
3. Optional: `pypdf` for PDF text extraction. When unavailable, the CLI falls
   back to a pure-Python content-stream harvester so CI remains offline-usable.

## Operator commands

### Offline dry-run (default / CI)

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py \
  --default-catalog
```

Prints inventory pin, package digests, CID, present/extraction counts, and
hash-verification status. No files are written.

### Stage local PDFs + extracted texts

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py \
  --default-catalog \
  --stage \
  --output-dir /var/tmp/uspto-guidance-pdfs
```

Staging layout:

```text
/var/tmp/uspto-guidance-pdfs/
  uspto-guidance-pdfs.manifest.json
  uspto-guidance-pdfs.acquisition.receipt.json
  package_meta.json
  pdfs/
    sme-2019-peg-v2019-01-07.pdf
    ...
  texts/
    sme-2019-peg-v2019-01-07.txt
    ...
```

### Validate a staged inventory manifest

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py \
  --validate-manifest /var/tmp/uspto-guidance-pdfs/uspto-guidance-pdfs.manifest.json
```

### Package recipe (optional offline fixture)

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py \
  --fixture /path/to/uspto_guidance_pdfs_package.json \
  --stage \
  --output-dir /var/tmp/uspto-guidance-pdfs
```

Minimal public recipe shape:

```json
{
  "classification": "public_official",
  "partition": "public",
  "auth_required": false,
  "cutoff": "2024-07-17",
  "documents": [
    {
      "document_id": "sme-2019-peg",
      "version": "2019-01-07",
      "expected_sha256": "<optional pin>"
    }
  ]
}
```

When `documents` is omitted, the full required catalog is used.

### Demonstrate non-public / failed-auth rejection

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py --reject-non-public
# exits non-zero; prints non_public_rejected

python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py --reject-failed-auth
# exits non-zero; prints failed_auth_rejected
```

### Live USPTO (not enabled for unattended CI)

```bash
python scripts/ops/legal_data/acquire_uspto_guidance_pdfs.py \
  --default-catalog \
  --live
# fails closed: use offline catalog / fixtures; live download is operator-gated
```

## Flags

| Flag | Meaning |
| --- | --- |
| `--default-catalog` | Materialize the required offline USPTO guidance PDF catalog |
| `--fixture PATH` | Explicit offline package recipe JSON |
| `--cutoff YYYY-MM-DD` | Inventory-level cutoff pin (never `latest`) |
| `--stage` | Write manifest, receipt, package meta, PDFs, and texts |
| `--output-dir PATH` | Staging root (required with `--stage`) |
| `--mode acquire\|stage\|dry_run` | Materialization mode recorded on the inventory manifest |
| `--validate-manifest PATH` | Validate an existing guidance PDF inventory manifest |
| `--reject-non-public` | Fail-closed demo that non-public packages cannot complete |
| `--reject-failed-auth` | Fail-closed demo that failed-auth packages cannot complete |
| `--live` | Request live acquisition (currently fails closed) |
| `--print-manifest` | Emit inventory manifest JSON on stdout |
| `--print-receipt` | Emit acquisition receipt JSON on stdout |
| `--no-print-summary` | Suppress human-readable summary lines |

## Artifacts

### Inventory manifest (`uspto-guidance-pdfs.manifest.json`)

Bound by PATLAW-184 schema `patent.uspto_guidance_pdfs.v1`:

* `edition_pin` — concrete inventory pin (`document_id` + `version` + `cutoff`)
* `inventory[]` — each PDF with `uri`, `sha256`, `publication_date`, `cutoff`,
  `rights_review`, `page_count`, optional `extraction`
* `supersessions[]` — prior editions retained as evidence
* `gaps[]` — explicit incompleteness (when used)
* `package_digest_sha256` / `package_root_cid` — package content address
* `inventory_digest_sha256` — content address of inventory rows
* `counts` — required / present / extraction / page totals
* `authority_tier=guidance`, `is_binding=false`, `partition=public`

### Acquisition receipt (`uspto-guidance-pdfs.acquisition.receipt.json`)

PATLAW-185 surface (`patent.uspto_guidance_pdfs.acquisition.v1`):

* `task_id=PATLAW-185`, `goal_id=PATLAW-G217`
* package digest + CID echo
* `hash_verified`, `hash_verified_ok`, `extraction_deterministic`
* `non_public_rejected=true`, `failed_auth_rejected=true`
* `hub_upload=false`
* `source_kind` (for example `uspto-guidance-offline-catalog`)

## Acceptance checklist

| Check | Evidence |
| --- | --- |
| Inventory PDFs hash-verify | every present `sha256` equals `sha256(pdf_bytes)` |
| Text extraction stable | two extraction passes share `text_sha256` for identical bytes |
| Non-public fail closed | `--reject-non-public` / private recipe exits non-zero |
| Failed-auth fail closed | `--reject-failed-auth` / `auth_required` without `auth_ok` exits non-zero |
| Guidance not law | `authority_tier=guidance`, `is_binding=false` |
| Superseded editions retained | 2019 PEG + 2024 AI examples both present; supersession edges exist |
| No Hub upload | CLI has no upload/push path; receipt `hub_upload=false` |

## Authoritative validation

```bash
python -m pytest tests/integration/processors/patent/test_acquire_uspto_guidance_pdfs.py -q
```

Related unit contracts (dependency, not this task’s gate):

```bash
python -m pytest tests/unit/processors/domains/patent/test_uspto_guidance_pdf_contracts.py -q
```

## Non-goals

* Live unattended USPTO bulk download as the CI gate
* Hub dataset upload / republication (later Hub track tasks)
* Elevating guidance PDFs to statute or regulation
* Deleting superseded editions when newer guidance is admitted
* Treating taskboard status alone as acquisition evidence
