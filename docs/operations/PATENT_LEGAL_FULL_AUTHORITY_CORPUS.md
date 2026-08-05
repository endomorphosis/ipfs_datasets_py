# Patent Legal Intelligence — Full-Authority Corpus Integrate, Publish, and Hub Republication

**Tasks:** `PATLAW-186` … `PATLAW-191`  
**Goal:** `PATLAW-G218`  
**Track:** hub-full-authority-integrate-publish  
**Depends on:** `PATLAW-181` (full annual CFR Title 37), `PATLAW-183` (full MPEP sections), `PATLAW-185` (USPTO guidance PDFs), `PATLAW-174`–`177` / `PATLAW-179` (package / admit / stage / verify / seal)  
**CLIs:**

| Surface | Script |
| --- | --- |
| Full-authority recipe | `scripts/ops/legal_data/build_public_legal_production_recipe.py` |
| Materialize corpus | `scripts/ops/legal_data/materialize_public_legal_corpus.py` |
| BM25 / vector / graph rebuilds | `build_public_legal_{bm25_index,vector_index,knowledge_graph}.py` |
| **Hub republication (PATLAW-191)** | `scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py` |

**Tests:**

* Recipe: `tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py`
* **Republication:** `tests/release/test_full_authority_hub_republication.py`

**Upstream acquisitions:**

| Source | Task | CLI |
| --- | --- | --- |
| Annual CFR Title 37 | PATLAW-181 | `acquire_cfr_title37_full.py` |
| MPEP section-level | PATLAW-183 | `acquire_mpep_full_sections.py` |
| USPTO guidance PDFs | PATLAW-185 | `acquire_uspto_guidance_pdfs.py` |

This runbook is the operator surface for **integrating full-authority public
sources into the production public-legal recipe**, rebuilding BM25 / vector /
knowledge-graph indexes, and **packaging, admitting, staging, verifying, and
sealing a JusticeDAO Hub republication** without unattended `main` promote.

Chapter-only MPEP HTML and eCFR-only crawls are never treated as full-authority
completion. CI remains offline **fake-service** by default.

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
7. **Offline CI path.** Default `--full-authority` / republication
   `--fake-service` consumes offline acquisition fixtures/catalogs (no network,
   no Hub upload). Live Title 35 / eCFR / chapter MPEP remain optional
   supplements.
8. **No unattended Hub main promote.** Package → admit → stage → verify → seal
   may complete offline. `disposition=promoted` requires a **real promote
   evidence blob** (operator-signed fake-service drill or live promote). The
   receipt cannot claim promoted without that evidence.
9. **Credentials never appear in receipts.** Admission runs with Hub tokens
   unset. Tokens are never embedded in stage / verify / publication receipts.

## What full-authority acceptance answers

> Do recipe **document counts** and **by-family tallies** prove that full annual
> CFR Title 37, full MPEP sections, and USPTO guidance PDFs are present, with
> source receipts — while rejecting chapter-only MPEP and eCFR-only substitutes?

> For Hub republication: do **package counts** match that corpus, does
> **admission** pass, does **verification bind expanded artifact digests**, and
> does the **publication receipt** refuse fabricated promote claims while CI
> stays on **fake-service**?

| Surface | Role |
| --- | --- |
| `build_public_legal_production_recipe.py` | Full-authority recipe builder + CLI |
| `assert_full_authority_complete` | Fail-closed recipe acceptance gate |
| `publish_patent_legal_hub_indexes_live.py` | PATLAW-191 package/admit/stage/verify/seal |
| `test_full_authority_hub_republication.py` | Republication release acceptance |
| PATLAW-181 / 183 / 185 CLIs | Offline full-authority acquisitions |

## Prerequisites

1. PATLAW-181, PATLAW-183, and PATLAW-185 acquisition scripts and contracts are
   on the tree.
2. Offline fixtures / catalogs used by those acquisitions remain available
   (GovInfo annual Title 37 fixture, compact MPEP inventory, required guidance
   PDF catalog).
3. PATLAW-174…177 / 179 package, admit, stage, verify, and seal tooling exist.
4. Optional: writable work directory for package + receipts (not under protected
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

## Recipe flags

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

---

## PATLAW-191 — Hub republication (package / admit / stage / verify / seal)

### What republication does

`publish_patent_legal_hub_indexes_live.py` orchestrates:

1. **Package** — materialize full-authority corpus (PATLAW-187) and rebuild
   BM25 / vector / graph (PATLAW-188/189/190); assemble multi-repo Hub package
   with shared corpus root pins.
2. **Admit** — DLP / rights / Viewer gates (PATLAW-175) with Hub tokens
   **unset**.
3. **Stage** — authenticated branch + PR plan (PATLAW-176). **CI default:
   `--fake-service`** (in-memory Hub; no network).
4. **Verify** — pinned redownload of every projection (PATLAW-177); binds
   **expanded per-artifact digests** (path → sha256) for corpus / BM25 /
   vectors / knowledge_graph.
5. **Seal** — staged-vs-promoted publication receipt (PATLAW-179). Default
   disposition is `staged_not_promoted`. Claiming `promoted` without a real
   promote evidence blob **fails closed**.

### CI / supervisor command (authoritative offline)

```bash
python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \
  --work-dir /var/tmp/patlaw-191-ci \
  --fake-service
```

Defaults:

| Control | CI default |
| --- | --- |
| Full-authority package | on |
| `fake-service` stage / verify | on |
| Live Hub network | off |
| Promote to `main` | off (`--skip-promote`) |
| Publication disposition | `staged_not_promoted` |
| Auto-promote | always `false` |

Receipts under `--work-dir`:

| Path | Content |
| --- | --- |
| `package/` | Staged multi-artifact package + admission receipt |
| `receipts/stage-receipt.json` | Stage plan digests + SHAs (`fake_service=true`) |
| `receipts/verify-receipt.json` | Expanded projection digests + pin proof |
| `receipts/publication-receipt.json` | Sealed staged-vs-promoted receipt |
| `receipts/republication-summary.json` | PATLAW-191 summary (counts, digests, paths) |
| `receipts/package-count-proof.json` | Package vs recipe count parity |
| `receipts/expanded-digest-proof.json` | Verification expansion proof |

### Optional offline promote drill (still fake-service)

```bash
python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \
  --work-dir /var/tmp/patlaw-191-promote-drill \
  --fake-service \
  --promote \
  --no-skip-promote \
  --claim-promoted
```

This signs an operator approval with an ephemeral key under the work directory,
runs PATLAW-176 `--mode promote --fake-service`, and seals
`disposition=promoted` **only** because a real promote evidence blob exists.
It still does not contact the live Hub.

### Fabricated promote is refused

```bash
# claim promoted without --promote evidence → non-zero
python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \
  --work-dir /var/tmp/patlaw-191-bad \
  --fake-service \
  --claim-promoted
# ERROR: fabricated promote claim: ...
```

### Operator live Hub path (explicit)

```bash
# Requires HF_TOKEN / ~/.cache/huggingface/token with write access
python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \
  --work-dir /var/tmp/patlaw-191-live \
  --live-hub \
  --approver "operator@example.com" \
  --skip-promote
```

Live promote remains operator-invoked (`--promote --no-skip-promote`) with an
operator-held approval key. Never unattended; tokens never appear in receipts.

### Republication flags

| Flag | Meaning |
| --- | --- |
| `--work-dir PATH` | Package + receipts root |
| `--recipe PATH` | Optional pre-built full-authority recipe JSON |
| `--fake-service` | Offline FakeHubService (CI default: on) |
| `--no-fake-service` | Disable fake-service (requires `--live-hub`) |
| `--live-hub` | Operator live Hub stage/promote |
| `--skip-promote` | Do not promote (default) |
| `--promote` / `--no-skip-promote` | Run sign+promote after stage |
| `--claim-promoted` | Seal promoted disposition (requires promote evidence) |
| `--approver ID` | Approver identity on HMAC approval |
| `--organization ORG` | Hub org (default `justicedao`) |
| `--legacy-default-fixture` | Pre-full-authority multi-family fixture path |
| `--dry-run-only` | Legacy dry-run stage plan only |

### Acceptance checklist (PATLAW-191)

| Check | Evidence |
| --- | --- |
| Package counts = full-authority corpus | `package_counts.corpus_documents == recipe.counts.documents`; BM25/vector parity; `by_family` has cfr/mpep/guidance |
| Admission passes | `admission.admitted=true`; gates pass with tokens unset |
| Verification binds expanded digests | `verify-receipt.projection_digests.{corpus,bm25,vectors,knowledge_graph}` multi-path sha256 maps |
| No fabricated promote | Default `disposition=staged_not_promoted`; `--claim-promoted` without evidence fails |
| CI fake-service default | `stage.fake_service=true`; `live_network=false`; `auto_promote=false` |
| Offline release tests | `pytest tests/release/test_full_authority_hub_republication.py -q` |

## Artifacts

| Artifact | Description |
| --- | --- |
| Production recipe JSON | PATLAW-170-compatible `source_roots` + `documents` with full-authority tallies |
| Source receipts | Per-family package digests / CIDs from PATLAW-181/183/185 |
| `full_authority.sources` | Structured proof block for inventory / section / PDF completeness |
| Hub package directory | Corpus + BM25 + vector + graph pins, Viewer layouts, rights/privacy |
| Admission / stage / verify / publication receipts | Content-free, credential-free, digest-bound |
| `republication-summary.json` | PATLAW-191 operator summary |

## Recipe acceptance checklist

| Check | Evidence |
| --- | --- |
| Full CFR Title 37 | `counts.full_authority.cfr_inventory_total == title37_section_count()`; family `cfr` docs ≥ 1; `not_ecfr_only` |
| Full MPEP sections | `by_family.mpep` and `mpep_section_level` ≥ required chapters; no `mpep:chapter:*` completion |
| Guidance PDFs | `by_family.guidance` covers `REQUIRED_GUIDANCE_DOCUMENTS` |
| Rights / current-through / receipts | Present on every full-authority root and document |
| eCFR-only rejected | `--reject-ecfr-only` non-zero; assert gate rejects missing annual `cfr` |
| Chapter-only MPEP rejected | `--reject-chapter-only-mpep` non-zero; assert gate rejects chapter landings |
| Offline CI (recipe) | `pytest tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py -q` |
| Offline CI (republication) | `pytest tests/release/test_full_authority_hub_republication.py -q` |

## Validation

```bash
# Full-authority recipe
python -m pytest tests/integration/processors/patent/test_build_public_legal_production_recipe_full_authority.py -q

# Full-authority Hub republication (PATLAW-191)
python -m pytest tests/release/test_full_authority_hub_republication.py -q
```

## Policy summary

| Control | Value |
| --- | --- |
| Full-authority recipe complete | Required for republication package |
| Package count parity | Corpus = BM25 = vectors = recipe documents |
| Admission | Fail-closed DLP/rights/Viewer; no premature tokens |
| CI Hub service | `fake-service` default |
| Live Hub | Operator-only (`--live-hub`) |
| Auto-promote | Always `false` |
| Promoted disposition | Requires real promote evidence blob |
| Tokens in receipts | Forbidden |

## Downstream / related

- **PATLAW-187** — materialize public legal corpus from the full-authority recipe
- **PATLAW-188 / 189 / 190** — rebuild BM25 / vector / knowledge graph indexes
- **PATLAW-191** — this republication surface (package/admit/stage/verify/seal)
- `docs/operations/PATENT_LEGAL_CFR_TITLE37_FULL.md` (PATLAW-181)
- `docs/operations/PATENT_LEGAL_MPEP_FULL.md` (PATLAW-183)
- `docs/operations/PATENT_LEGAL_USPTO_GUIDANCE_PDFS.md` (PATLAW-185)
- `docs/operations/PATENT_LEGAL_HUB_INDEX_ADMISSION.md` (PATLAW-175)
- `docs/operations/PATENT_LEGAL_HUB_INDEX_STAGE.md` (PATLAW-176)
- `docs/operations/PATENT_LEGAL_HUB_INDEX_PUBLICATION.md` (PATLAW-178/179)
