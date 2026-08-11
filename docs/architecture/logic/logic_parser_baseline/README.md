# Logic parser baseline (Wave 0 join)

This directory holds the **joined current-state baseline** for the IPFS
Datasets logic-family parser program (`ipfs-datasets-logic-family-parser-v1`).

Task **LFP-005** seals the four independent Wave-0 inventory artifacts under
the interface **`LogicParserBaselineReceipt@1`**. The join is fail-closed:
revision, digest, and schema drift are rejected, and every unknown label is
listed explicitly. The receipt records **zero** hidden or silently
normalized unknown labels.

## Owned artifacts

| File | Interface | Owner task | Role |
| --- | --- | --- | --- |
| `parser_inventory.json` | `LogicSurfaceInventory@1` | LFP-001 | Parser, AST, formula/term, printer, compiler, decoder, and formula-boundary census under explicit logic roots |
| `family_label_audit.json` | `LogicFamilyAudit@1` | LFP-003 | Deterministic classification of every observed family-like string (canonical, alias, profile, property, view, notation, provider, lane, evidence kind, or unknown) |
| `capability_matrix.json` | `LogicCapabilityMatrix@1` | LFP-004 | Domain × formal-view × family/profile × provider capability seal (support, availability, and authority are independent axes) |
| `README.md` (this file) | documentation | LFP-005 | Join contract, gap surface, and UI boundary |

Companion corpus (outside this directory, still bound by the join):

| File | Interface | Owner task | Role |
| --- | --- | --- | --- |
| `tests/fixtures/logic_conformance/manifest.json` | `LogicConformanceCorpus@1` | LFP-002 | Content-addressed positive/negative/ambiguous/adversarial/translation/model/proof/trace fixtures |

## `LogicParserBaselineReceipt@1`

Schema version: `logic-parser-baseline-receipt/v1`

The join constructs one content-addressed receipt that binds:

1. **Revisions** — task/goal/program identifiers and per-artifact version fields
   (`task_id` / `task`, `goal_id` / `objective`, `report_version`, matrix
   `version`).
2. **Roots** — logic package path, baseline directory, audit scan roots, and
   inventory policy profile.
3. **Inventories** — parser surface counts and digests from
   `parser_inventory.json`.
4. **Corpus** — fixture count and digest of the frozen conformance manifest.
5. **Matrix** — cell counts, unknown/unimplemented/refill coordinates, and
   seal digest from `capability_matrix.json`.
6. **Gaps** — unresolved audit drift, corpus unknown labels, matrix refill
   cells, and inventory evidence coverage.
7. **Active UI work** — `ui_ux_ir` remains **declaration-only** with
   **source_missing** availability until LFP-038 and a reviewed source import.
   The join never invents or writes `ui_ux_ir` package files.

### Content identity

Each artifact contributes a digest:

| Artifact | Digest source |
| --- | --- |
| Parser inventory | `content_digest` of the inventory body |
| Conformance corpus | `LogicConformanceCorpus.content_digest()` |
| Family-label audit | SHA-256 of the canonical JSON report body |
| Capability matrix | `content_digest_sha256` of the full matrix body |

The receipt body (without `content_digest`) is itself hashed as
`sha256:<hex>` so the join is replayable and side-effect free.

### Fail-closed drift rules

Join **rejects** (raises) when any of the following hold:

| Drift class | Trigger |
| --- | --- |
| **Schema drift** | `schema_version` ≠ the Wave-0 constant for that interface |
| **Interface drift** | `interface` ≠ the declared Wave-0 interface |
| **Revision drift** | task/goal/report/matrix version fields disagree with the sealed contract |
| **Digest / content drift** | sealed report body or digest disagrees with live re-materialization |

Live re-materialization uses the same pure builders as LFP-001–LFP-004
(`inventory_logic_surfaces`, `load_corpus`, `baseline_audit_dict`,
`build_default_matrix`). Import success, documentation, mocks, and old
receipts do **not** prove live semantics.

### Unknown labels (zero hidden, zero silent normalization)

Unknown labels are first-class evidence for later taxonomy work (LFP-006 /
LFP-010), never dropouts.

The receipt field `unknown_labels` always includes:

| Field | Meaning |
| --- | --- |
| `corpus` | Explicit list of fixture `family_label` values with `label_disposition=unknown` |
| `audit` | Explicit list of audit classifications with `kind=unknown` |
| `all` | Stable unique union of corpus and audit unknowns |
| `hidden_or_silently_normalized` | Must be **`[]`** |
| `hidden_or_silently_normalized_count` | Must be **`0`** |

Fail-closed guarantees:

- Every corpus fixture with `label_disposition=unknown` appears in
  `unknown_labels.corpus` with its **original** `family_label` string and
  `family_id=null` (no rewrite to a registry family).
- Every audit row with `kind=unknown` appears in `unknown_labels.audit`,
  keeps `is_semantic_family=false`, and has no `canonical_family_id`.
- Audit `summary.kind_counts.unknown` must equal the listed classification
  count (no hidden rows).
- The join never silently normalizes free-form labels into semantic families.

Current corpus unknowns retained for LFP-003/LFP-010 closure include at least
`typed_first_order` and `workflow_temporal`.

## Gap surface

Unresolved gaps remain visible after the join; sealing does **not** mean the
matrix or taxonomy is closed.

| Gap class | Source | Downstream |
| --- | --- | --- |
| Matrix unknown / unimplemented / refill cells | LFP-004 seal | Refill / provider / domain tasks |
| Audit drift (non-family labels in family-like fields) | LFP-003 | LFP-G020 taxonomy |
| Corpus unknown labels | LFP-002 | LFP-006 / LFP-010 |
| UI source missing | matrix `ui_ux_ir` cells | LFP-038 source gate |

Discovered production defects become G020/G030 tasks; LFP-005 owns only this
documentation and the join conformance test.

## Validation

```bash
cd ipfs_datasets_py && python -m pytest -q tests/unit/logic/conformance/test_baseline_join.py
```

The test module implements the join, seals a `LogicParserBaselineReceipt@1`
against the checked-in artifacts, asserts zero hidden or silently normalized
unknown labels, and injects schema/revision/digest drift cases that must
fail closed.

## Non-goals

- Does not rename production family strings (LFP-003 / LFP-006).
- Does not implement parsers, elaborators, or provider execution.
- Does not create, copy, or overwrite `ui_ux_ir`.
- Does not claim live solver/kernel availability; matrix availability remains
  declaration posture only.
