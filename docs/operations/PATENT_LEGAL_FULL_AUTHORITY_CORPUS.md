# Patent Legal Intelligence — Full-Authority Production Public-Legal Recipe

**Task:** `PATLAW-186`  
**Goal:** `PATLAW-G218`  
**Track:** hub-full-authority-integrate-publish  
**Depends on:** `PATLAW-181` (full annual CFR Title 37), `PATLAW-183` (full MPEP sections), `PATLAW-185` (USPTO guidance PDFs)  
**CLI:** `scripts/ops/legal_data/build_public_legal_production_recipe.py`  
**Tests:** `tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py`  
**Upstream acquisitions:**

| Source | Task | CLI |
| --- | --- | --- |
| Annual CFR Title 37 | PATLAW-181 | `acquire_cfr_title37_full.py` |
| MPEP section-level | PATLAW-183 | `acquire_mpep_full_sections.py` |
| USPTO guidance PDFs | PATLAW-185 | `acquire_uspto_guidance_pdfs.py` |

This runbook is the operator surface for **integrating full-authority public
sources into the production public-legal recipe**. The recipe binds document
counts, by-family tallies, source receipts, rights reviews, and current-through
pins so downstream corpus materialization / BM25 / vector / graph rebuilds
(PATLAW-187+) share one expanded authority root.

It does **not** upload to Hugging Face Hub, open publication PRs, or treat
chapter-only MPEP HTML or eCFR-only crawls as full-authority completion.

## Standing rules (fail-closed)

1. **Full annual CFR Title 37 required.** Family `cfr` must bind the official
   GovInfo annual package inventory (full catalog size = Title 37 section count).
   Package `sha256` / CIDv1 and acquisition receipts are required.
2. **eCFR-only does not complete.** Family `ecfr` may appear only as a
   non-completing supplement. Completing full authority with eCFR and no annual
   `cfr` root fails closed.
3. **Full MPEP section-level required.** Family `mpep` documents must be
   section-level (or form-paragraph / appendix / index anchors) from
   PATLAW-183. Chapter-landing-page-only crawls fail closed.
4. **USPTO guidance PDFs required.** Family `guidance` must cover the pinned
   required PDF catalog from PATLAW-185 with hash-verified text extraction.
5. **Guidance never elevates.** MPEP and guidance rows remain
   `authority_kind=guidance` / non-binding.
6. **Rights + current-through + receipts.** Every full-authority source root
   and document carries reviewed redistribution rights, a concrete
   current-through watermark, and a content-addressed source receipt.
7. **Offline CI path.** Default `--full-authority` consumes offline acquisition
   fixtures/catalogs (no network, no Hub upload). Live Title 35 / eCFR /
   chapter MPEP remain optional supplements.
8. **No Hub upload in this task.** Recipe JSON is a local packaging input for
   later Hub-track republication.

## What full-authority acceptance answers

> Do recipe **document counts** and **by-family tallies** prove that full annual
> CFR Title 37, full MPEP sections, and USPTO guidance PDFs are present, with
> source receipts — while rejecting chapter-only MPEP and eCFR-only substitutes?

| Surface | Role |
| --- | --- |
| `build_public_legal_production_recipe.py` | Full-authority recipe builder + CLI |
| `assert_full_authority_complete` | Fail-closed acceptance gate |
| `test_build_public_legal_production_recipe_full_authority.py` | Integration acceptance |
| PATLAW-181 / 183 / 185 CLIs | Offline full-authority acquisitions consumed here |

## Prerequisites

1. PATLAW-181, PATLAW-183, and PATLAW-185 acquisition scripts and contracts are
   on the tree.
2. Offline fixtures / catalogs used by those acquisitions remain available
   (GovInfo annual Title 37 fixture, compact MPEP inventory, required guidance
   PDF catalog).
3. Optional: writable output path for the recipe JSON (not under protected
   architecture paths).

## Operator commands

### Offline full-authority recipe (default / CI)

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /var/tmp/patlaw-full-authority-recipe.json
```

`--full-authority` is the default. The builder:

1. Acquires annual CFR Title 37 via PATLAW-181 (offline fixture).
2. Acquires MPEP section texts via PATLAW-183 (offline fixture).
3. Acquires USPTO guidance PDF texts via PATLAW-185 (offline catalog).
4. Emits `source_roots`, `documents`, `source_receipts`, and
   `counts.by_family` / `counts.full_authority` tallies.
5. Runs `assert_full_authority_complete` before writing.

Example tallies (offline fixture magnitudes; production live packages differ):

| Family | Documents (offline) | Full-authority proof |
| --- | --- | --- |
| `cfr` | present granules (≥1) | `cfr_inventory_total` = full Title 37 catalog |
| `mpep` | section-level acquired | `mpep_section_level` ≥ required chapters; not chapter-only |
| `guidance` | required PDF catalog | `guidance_pdfs` = required document count |

### Validate an existing recipe

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /tmp/noop.json \
  --validate-recipe /var/tmp/patlaw-full-authority-recipe.json
```

### Demonstrate eCFR-only rejection

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /tmp/noop.json \
  --reject-ecfr-only
# exits non-zero; prints ecfr_only_rejected
```

### Demonstrate chapter-only MPEP rejection

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /tmp/noop.json \
  --reject-chapter-only-mpep
# exits non-zero; prints chapter_only_mpep_rejected
```

### Optional live supplements (do not replace full-authority sources)

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /var/tmp/patlaw-full-authority-recipe.json \
  --include-uscode \
  --include-ecfr-supplement
```

Title 35 (Hugging Face) and live eCFR may be merged as **supplements**. eCFR
still never replaces the annual `cfr` family for completion.

### Legacy live path (not full-authority)

```bash
python scripts/ops/legal_data/build_public_legal_production_recipe.py \
  --output /var/tmp/patlaw-legacy-live-recipe.json \
  --legacy-live
```

This path fetches Title 35 + eCFR + MPEP chapter pages over the network and
sets `full_authority.complete=false`. It does **not** pass PATLAW-186 acceptance.

## Flags

| Flag | Meaning |
| --- | --- |
| `--output PATH` | Write recipe JSON here (required) |
| `--full-authority` | Full-authority build (default on) |
| `--legacy-live` | Legacy Title 35 / eCFR / chapter MPEP path |
| `--include-uscode` | Also pull 35 U.S.C. from Hugging Face |
| `--include-ecfr-supplement` | Also include live eCFR (non-completing) |
| `--cfr-fixture PATH` | Explicit GovInfo annual Title 37 fixture |
| `--cfr-year YYYY` | Pin annual CFR year |
| `--ecfr-as-of YYYY-MM-DD` | eCFR as-of for legacy/supplement paths |
| `--skip-mpep` | Legacy only: skip chapter MPEP fetch |
| `--reject-ecfr-only` | Fail-closed demo for eCFR-only completion |
| `--reject-chapter-only-mpep` | Fail-closed demo for chapter-only MPEP |
| `--validate-recipe PATH` | Validate existing recipe for full-authority acceptance |

## Recipe shape (full authority)

```json
{
  "recipe_id": "patlaw-full-authority-public-legal-corpus",
  "schema_version": "patent.public_legal_corpus.v1",
  "task_id": "PATLAW-186",
  "goal_id": "PATLAW-G218",
  "source_roots": [
    {"family": "cfr", "full_authority": true, "package_id": "CFR-YYYY-title37", "...": "..."},
    {"family": "mpep", "full_authority": true, "edition_key": "mpep-9-r…", "...": "..."},
    {"family": "guidance", "full_authority": true, "...": "..."}
  ],
  "documents": ["… family=cfr|mpep|guidance rows with rights + current_through …"],
  "source_receipts": [
    {"family": "cfr", "package_digest_sha256": "…", "receipt": {"…": "…"}},
    {"family": "mpep", "package_digest_sha256": "…", "receipt": {"…": "…"}},
    {"family": "guidance", "package_digest_sha256": "…", "receipt": {"…": "…"}}
  ],
  "full_authority": {
    "complete": true,
    "sources": {
      "cfr_title37": {
        "inventory_total": 1265,
        "not_ecfr_only": true,
        "package_digest_sha256": "…"
      },
      "mpep_sections": {
        "section_level_acquired": 38,
        "chapter_only": false
      },
      "uspto_guidance_pdfs": {
        "documents_present": 7,
        "document_ids": ["…"]
      }
    },
    "reject_ecfr_only_completion": true,
    "reject_chapter_only_mpep_completion": true
  },
  "counts": {
    "documents": 50,
    "by_family": {"cfr": 5, "mpep": 38, "guidance": 7},
    "full_authority": {
      "cfr_inventory_total": 1265,
      "mpep_section_level": 38,
      "guidance_pdfs": 7
    }
  }
}
```

Document counts for offline CI use **present** annual CFR granules (bounded
fixture) plus the full MPEP section acquisition and full guidance PDF catalog.
Full CFR Title 37 is proven by `counts.full_authority.cfr_inventory_total`
matching the complete Title 37 section catalog (present + explicit gaps), not by
eCFR HTML alone.

## Artifacts

| Artifact | Description |
| --- | --- |
| Production recipe JSON | PATLAW-170-compatible `source_roots` + `documents` with full-authority tallies |
| Source receipts | Per-family package digests / CIDs from PATLAW-181/183/185 |
| `full_authority.sources` | Structured proof block for inventory / section / PDF completeness |

## Acceptance checklist

| Check | Evidence |
| --- | --- |
| Full CFR Title 37 | `counts.full_authority.cfr_inventory_total == title37_section_count()`; family `cfr` docs ≥ 1; `not_ecfr_only` |
| Full MPEP sections | `by_family.mpep` and `mpep_section_level` ≥ required chapters; no `mpep:chapter:*` completion |
| Guidance PDFs | `by_family.guidance` covers `REQUIRED_GUIDANCE_DOCUMENTS` |
| Rights / current-through / receipts | Present on every full-authority root and document |
| eCFR-only rejected | `--reject-ecfr-only` non-zero; assert gate rejects missing annual `cfr` |
| Chapter-only MPEP rejected | `--reject-chapter-only-mpep` non-zero; assert gate rejects chapter landings |
| Offline CI | `pytest tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py -q` |

## Validation

```bash
python -m pytest tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py -q
```

## Downstream

- **PATLAW-187** — materialize public legal corpus from this full-authority recipe
- **PATLAW-188 / 189 / 190** — rebuild BM25 / vector / knowledge graph indexes
- **PATLAW-191** — Hub republication with expanded artifact digests

## Related runbooks

- `docs/operations/PATENT_LEGAL_CFR_TITLE37_FULL.md` (PATLAW-181)
- `docs/operations/PATENT_LEGAL_MPEP_FULL.md` (PATLAW-183)
- `docs/operations/PATENT_LEGAL_USPTO_GUIDANCE_PDFS.md` (PATLAW-185)
