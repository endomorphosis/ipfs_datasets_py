# Patent Legal Intelligence — Full Annual CFR Title 37 Acquisition

**Task:** `PATLAW-181`  
**Goal:** `PATLAW-G215`  
**Track:** hub-full-authority-cfr  
**Depends on:** `PATLAW-180` (inventory contracts + schema)  
**CLI:** `scripts/ops/legal_data/acquire_cfr_title37_full.py`  
**Contracts:** `ipfs_datasets_py/processors/domains/patent/cfr_title37_full_contracts.py`  
**Schema:** `data/release/patent_legal_intelligence/cfr_title37_full.manifest.schema.json`  
**Tests:** `tests/integration/processors/patent/test_acquire_cfr_title37_full.py`  
**Fixture:** `tests/fixtures/legal_data/patent_authorities/cfr/cfr_annual_recipe.json`

This runbook is the operator surface for **acquiring and pinning the complete
annual CFR Title 37 package** as a public corpus source. It enumerates the full
part/section catalog for a concrete GovInfo edition, binds package digests/CID,
and records first-class gaps when section text is not present in the acquired
materialization.

It does **not** upload to Hugging Face Hub, open publication PRs, or treat eCFR
as a substitute for the official annual package.

## Standing rules (fail-closed)

1. **Pinned annual edition only.** Identity is always `year` +
   `CFR-YYYY-title37` (for example `CFR-2024-title37`). The hard-coded token
   `latest` is rejected on year, package id, and edition fields.
2. **Full inventory.** Every Title 37 catalog section from PATLAW-180 must appear
   in the inventory. Omission is a failure; missing text is an explicit gap.
3. **Text or gap, never silence.** Each inventory row is `presence=present`
   (with content digest when text is bound) or `presence=gap` with a matching
   gap record (`reason`, `stable_id`, optional `granule_id` / note).
4. **Official annual package bindings.** Package `sha256` and CIDv1 bind the
   GovInfo annual package (`authority_tier=official-base`). eCFR presentation
   identity, when linked, remains separate and **never** completes this task.
5. **eCFR-only / eCFR-partial crawls fail closed.** Unofficial eCFR HTML/XML
   alone does not satisfy annual CFR Title 37 completion.
6. **No Hub upload.** This CLI stages local artifacts only. Republication is a
   later task under the Hub track.
7. **Offline CI path.** Validation uses the bounded official annual fixture;
   live GovInfo download is optional and not required for the pytest gate.

## What acquisition answers

> For a pinned GovInfo annual Title 37 package, do we have a full catalog
> inventory where every section is present with text digests or an explicit
> gap, and do package sha256/CID bind the official annual acquisition (not
> eCFR)?

| Surface | Role |
| --- | --- |
| `acquire_cfr_title37_full.py` | Offline (default) or staged acquisition CLI |
| `cfr_title37_full_contracts.py` | Inventory schema / builders (PATLAW-180) |
| `cfr_title37_full.manifest.schema.json` | Release JSON Schema for inventory manifests |
| `test_acquire_cfr_title37_full.py` | Integration acceptance (this task) |

## Prerequisites

1. **PATLAW-180 contracts** are present on the tree (inventory catalog, manifest
   types, JSON Schema).
2. **Bounded Title 37 fixture** at:

   ```text
   tests/fixtures/legal_data/patent_authorities/cfr/cfr_annual_recipe.json
   ```

   The fixture is an **official annual GovInfo** recipe (`provider=govinfo`,
   concrete `package_id`). It may include only a subset of section granules for
   CI size; the CLI still enumerates the **full** catalog and records gaps for
   missing granules.
3. Optional: a writable local staging directory for `--stage` output (not under
   protected architecture paths).

## Operator commands

### Offline dry-run (default / CI)

```bash
python scripts/ops/legal_data/acquire_cfr_title37_full.py \
  --default-fixture \
  --year 2024
```

Prints package id, digests, CID, present/gap counts. No files are written.

### Stage local package + section texts

```bash
python scripts/ops/legal_data/acquire_cfr_title37_full.py \
  --default-fixture \
  --year 2024 \
  --stage \
  --output-dir /var/tmp/cfr-title37-full-2024
```

Staging layout:

```text
/var/tmp/cfr-title37-full-2024/
  cfr-title37-full.manifest.json
  cfr-title37-full.acquisition.receipt.json
  package_meta.json
  sections/
    1-56.txt
    1-97.txt
    ...
```

### Validate a staged inventory manifest

```bash
python scripts/ops/legal_data/acquire_cfr_title37_full.py \
  --validate-manifest /var/tmp/cfr-title37-full-2024/cfr-title37-full.manifest.json
```

### Demonstrate eCFR-only rejection

```bash
python scripts/ops/legal_data/acquire_cfr_title37_full.py --reject-ecfr-only
# exits non-zero; prints ecfr_only_rejected
```

### Live GovInfo (not enabled for unattended CI)

```bash
python scripts/ops/legal_data/acquire_cfr_title37_full.py \
  --default-fixture \
  --live
# fails closed: use fixtures offline; live full-package download is operator-gated
```

## Flags

| Flag | Meaning |
| --- | --- |
| `--default-fixture` | Use the repository bounded official annual Title 37 fixture |
| `--fixture PATH` | Explicit GovInfo annual fixture recipe JSON |
| `--year YYYY` | Require fixture package year to match the pin |
| `--stage` | Write manifest, receipt, package meta, and section texts |
| `--output-dir PATH` | Staging root (required with `--stage`) |
| `--mode acquire\|stage\|dry_run` | Materialization mode recorded on the inventory manifest |
| `--validate-manifest PATH` | Validate an existing full inventory manifest |
| `--reject-ecfr-only` | Fail-closed demo that eCFR-only cannot complete the task |
| `--live` | Request live acquisition (currently fails closed) |
| `--print-manifest` | Emit inventory manifest JSON on stdout |
| `--print-receipt` | Emit acquisition receipt JSON on stdout |
| `--no-print-summary` | Suppress human-readable summary lines |

## Artifacts

### Inventory manifest (`cfr-title37-full.manifest.json`)

Bound by PATLAW-180 schema `patent.cfr_title37_full.v1`:

* `edition_identity` — year, `package_id`, `authority_tier=official-base`
* `inventory[]` — every catalog section with `presence`, optional `content_sha256`
* `gaps[]` — one record per `presence=gap` row
* `package_binding` — `package_digest_sha256`, optional `package_root_cid`, format digests
* `counts` — total / present / gap / by_part / by_chapter
* `inventory_digest_sha256` — content address of the inventory rows

### Acquisition receipt (`cfr-title37-full.acquisition.receipt.json`)

PATLAW-181 surface (`patent.cfr_title37_full.acquisition.v1`):

* `task_id=PATLAW-181`, `goal_id=PATLAW-G215`
* package digest + CID echo
* present/gap tallies and `full_inventory=true`
* `ecfr_only_rejected=true`, `hub_upload=false`
* `source_kind` (for example `govinfo-annual-fixture`)

## Acceptance checklist

| Check | Evidence |
| --- | --- |
| Full inventory for pinned edition | `counts.total_sections` ≥ catalog size; `assert_full_catalog_coverage` |
| Text or explicit gap | every row `present` with digest/text **or** matching gap record |
| Package sha256 / CID | `package_binding.package_digest_sha256` + `package_root_cid` |
| Not eCFR-only | `source_kind` is GovInfo annual; eCFR-only path exits non-zero |
| No Hub upload | CLI has no upload/push path; receipt `hub_upload=false` |

## Authoritative validation

```bash
python -m pytest tests/integration/processors/patent/test_acquire_cfr_title37_full.py -q
```

Related unit contracts (dependency, not this task’s gate):

```bash
python -m pytest tests/unit/processors/domains/patent/test_cfr_title37_full_contracts.py -q
```

## Non-goals

* eCFR enhanced-renderer crawls as a completion substitute
* Hub dataset upload / republication (later Hub track tasks)
* Elevating guidance or eCFR presentation to binding law
* Treating taskboard status alone as acquisition evidence
