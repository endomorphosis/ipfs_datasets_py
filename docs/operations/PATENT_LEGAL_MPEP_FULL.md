# Patent Legal Intelligence — Full MPEP Section-Level Acquisition

**Task:** `PATLAW-183`  
**Goal:** `PATLAW-G216`  
**Track:** hub-full-authority-mpep  
**Depends on:** `PATLAW-182` (section inventory + edition pin contracts)  
**CLI:** `scripts/ops/legal_data/acquire_mpep_full_sections.py`  
**Contracts:** `ipfs_datasets_py/processors/domains/patent/mpep_full_section_contracts.py`  
**Schema:** `data/release/patent_legal_intelligence/mpep_full.manifest.schema.json`  
**Tests:** `tests/integration/processors/patent/test_acquire_mpep_full_sections.py`

This runbook is the operator surface for **acquiring full MPEP section-level
texts** (and form-paragraph / appendix / index anchors) for a **pinned**
edition/revision as a public corpus source. It materializes stable section
identities, SHA-256 content digests, supersession edges, and a content-addressed
acquisition receipt.

It does **not** upload to Hugging Face Hub, open publication PRs, or treat
chapter landing pages as a complete inventory.

## Standing rules (fail-closed)

1. **Pinned edition + revision only.** Identity is always concrete
   (`edition` + `revision` + `cutoff`), for example MPEP 9 r07.2022. The
   hard-coded token `latest` is rejected on edition and revision pins.
2. **Section-level inventory.** Every required MPEP chapter must contribute at
   least one **section-level** anchor (or an explicit gap). Chapter-landing
   pages alone (for example `700` for chapter 700) fail acceptance.
3. **Count = inventory − gaps.** Acquired present section count must equal
   inventory present entries (inventory total minus explicit gaps). Silent
   omission is a failure; missing text is an explicit gap.
4. **Stable identity + SHA-256.** Each acquired section binds
   `stable_identity` (`mpep:{jurisdiction}:{kind}:{anchor}`) and
   `content_sha256` (and a derived CIDv1 when present).
5. **Supersession edges retained.** Inventory supersession records are copied
   onto the acquisition receipt unchanged. Both ends remain **guidance**;
   supersession never elevates guidance to binding law.
6. **Guidance never elevates.** Authority tier is always `guidance` and
   `is_binding` is always `false` on inventory entries, acquisition rows, and
   supersession edges.
7. **No Hub upload.** This CLI stages local artifacts only. Republication is a
   later Hub-track task.
8. **Offline CI path.** Validation uses the PATLAW-182 compact full-chapter
   fixture with deterministic section bodies. Live USPTO HTML fetch is opt-in
   (`--live`) and not required for the pytest gate.

## What acquisition answers

> For a pinned MPEP edition/revision, do we have section-level texts (or
> explicit gaps) for every inventoried anchor, with stable identities and
> SHA-256 digests, while retaining supersession edges as non-binding guidance?

| Surface | Role |
| --- | --- |
| `acquire_mpep_full_sections.py` | Offline (default) or staged acquisition CLI |
| `mpep_full_section_contracts.py` | Inventory schema / builders (PATLAW-182) |
| `mpep_full.manifest.schema.json` | Release JSON Schema for inventory manifests |
| `test_acquire_mpep_full_sections.py` | Integration acceptance (this task) |

## Prerequisites

1. **PATLAW-182 contracts** are present on the tree (edition pins, section
   inventory types, supersession records, compact fixture, JSON Schema).
2. Optional: a PATLAW-182 inventory manifest JSON produced by
   `--write-default-inventory` or a fuller production inventory.
3. Optional: a writable local staging directory for `--stage` output (not under
   protected architecture paths).

## Operator commands

### Offline dry-run (default / CI)

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --default-fixture
```

Prints inventory/present/gap counts, package SHA-256, CIDv1, and supersession
edge count. No files are written. Uses deterministic fixture bodies that match
the PATLAW-182 compact inventory digests.

### Write the compact inventory fixture

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --write-default-inventory /var/tmp/mpep-full.manifest.json
```

### Stage local package + section texts

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --default-fixture \
  --stage \
  --output-dir /var/tmp/mpep-full-sections
```

Staging layout:

```text
/var/tmp/mpep-full-sections/
  acquisition-receipt.json
  inventory-manifest.json
  supersessions.json
  sections/
    mpep-100-101.txt
    mpep-2100-2106.txt
    fp-7.05.txt
    ...
```

### Acquire from an explicit inventory path

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --inventory /var/tmp/mpep-full.manifest.json \
  --stage \
  --output-dir /var/tmp/mpep-full-sections
```

### Live USPTO HTML (operator-gated, not for unattended CI)

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --inventory /var/tmp/mpep-full.manifest.json \
  --live \
  --live-delay-seconds 0.75 \
  --stage \
  --output-dir /var/tmp/mpep-full-live
```

Live mode is polite (default User-Agent identifies the acquisition task; delay
between fetches). Without `--live`, live mode fails closed.

### Partial acquisition (non-acceptance diagnostics only)

```bash
python scripts/ops/legal_data/acquire_mpep_full_sections.py \
  --default-fixture \
  --allow-partial
```

`--allow-partial` records acquisition gaps when bodies fail; it does **not**
satisfy acceptance. Strict count (`acquired == inventory_present`) remains the
default for production and CI.

## Flags

| Flag | Meaning |
| --- | --- |
| `--default-fixture` | Use the PATLAW-182 compact full-chapter inventory fixture |
| `--inventory PATH` | Explicit inventory manifest JSON |
| `--write-default-inventory PATH` | Emit the compact inventory fixture and exit |
| `--stage` | Write receipt, section bodies, inventory, supersessions |
| `--output-dir PATH` | Staging root (required with `--stage`) |
| `--live` | Opt-in polite live HTTP fetch of USPTO MPEP HTML |
| `--live-delay-seconds N` | Polite delay between live fetches (default `0.75`) |
| `--include-text-in-receipt` | Embed section text in receipt JSON (default: disk only) |
| `--print-receipt` | Emit acquisition receipt JSON on stdout |
| `--strict-count` | Require `acquired == inventory_present` (default: on) |
| `--allow-partial` | Allow acquired &lt; inventory present (diagnostics only) |
| `--no-print-summary` | Suppress human-readable summary lines |

## Artifacts

### Acquisition receipt (`acquisition-receipt.json`)

Content-addressed receipt for one acquisition run:

* `schema_version`: `patent.mpep_full.acquisition.v1`
* `task_id` / `goal_id`: `PATLAW-183` / `PATLAW-G216`
* `edition_pin`: concrete edition + revision + cutoff (never `latest`)
* `sections[]`: per-anchor rows with `stable_identity`, `content_sha256`,
  `status` (`acquired` / `gap` / `hash_mismatch` / `retrieval_failed`)
* `counts`: `inventory_entries`, `inventory_present`, `inventory_gaps`,
  `acquired`, `acquisition_gaps`, `supersession_edges`, chapter tallies
* `inventory_digest_sha256`: binds the PATLAW-182 inventory payload
* `package_digest_sha256` / `package_root_cid`: bind the acquisition package
  (section identities + digests + supersessions; free text bodies excluded)
* `supersessions[]`: retained guidance-only edges
* `authority_tier=guidance`, `is_binding=false`, no Hub upload

### Section bodies (`sections/*.txt`)

One UTF-8 text file per acquired present section. File digest of the body
bytes matches `content_sha256` on the corresponding receipt row.

### Supersessions (`supersessions.json`)

Copy of inventory supersession edges. Each edge has `remains_guidance=true`
and `elevates_to_law=false`.

## Acceptance criteria (PATLAW-183)

| Criterion | How it is enforced |
| --- | --- |
| Section count matches inventory minus explicit gaps | `counts.acquired == counts.inventory_present == inventory_entries − inventory_gaps`; `AcquisitionCountMismatchError` when strict |
| Each section has stable identity and sha256 | Every present row has `stable_identity` starting with `mpep:` and a 64-char `content_sha256` |
| Supersession edges retained when present | Receipt supersession edge set equals inventory edge set; guidance flags preserved |
| Chapter-landing-only fails closed | `ChapterLandingCrawlError` / inventory contract rejects landing-only inventories |
| Guidance never elevates | `assert_guidance_not_elevated` on rows, receipt, and supersession edges |

## Validation

```bash
python -m pytest tests/integration/processors/patent/test_acquire_mpep_full_sections.py -q
```

Unit inventory contracts (PATLAW-182):

```bash
python -m pytest tests/unit/processors/domains/patent/test_mpep_full_section_contracts.py -q
```

## Notes for operators

* Prefer USPTO official HTML/PDF sources for live acquisition. Chapter-only
  crawls of the MPEP index are insufficient for completion.
* The compact fixture covers every required chapter with one section-level
  anchor plus form-paragraph samples. Production inventories should expand
  section density without dropping chapter coverage or edition pins.
* MPEP text is examination guidance, not binding law. Downstream products must
  keep `authority_tier=guidance` and never elevate supersession successors to
  statute or regulation rank.
