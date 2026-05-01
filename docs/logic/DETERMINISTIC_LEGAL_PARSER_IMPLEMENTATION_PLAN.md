# Deterministic Legal Parser Implementation Plan

Date: 2026-04-28
Parent roadmap: `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md`
Baseline parser: `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`
Baseline commit: `b3437217c6c983bab6a2169fe8275b9f900b50b3`

## Objective

Move legal-text formalization from "deterministic scaffold plus optional LLM repair" to "deterministic parser as the canonical formalization path, with optional LLM repair only for blocked clauses."

This plan is organized as PR-sized implementation units. Each unit should preserve backward compatibility unless the unit explicitly declares a migration.

## Phase 0: Baseline Lock

### Task 0.1: Add Parser Snapshot Fixtures

Files:

- `tests/fixtures/legal_parser/`
- `tests/unit_tests/logic/deontic/test_deontic_parser_snapshots.py`
- `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`

Implementation:

- Add JSON fixtures for 20 to 40 representative clauses.
- Normalize nondeterministic values if any appear.
- Compare full parser elements for stable fields.
- Compare selected key fields separately for readable failures.

Fixture categories:

- simple obligation;
- simple permission;
- simple prohibition;
- `no person shall`;
- passive duty;
- impersonal unlawful clause;
- definition;
- section-scoped definition;
- chapter-scoped definition;
- exception;
- override;
- temporal deadline;
- procedure timeline;
- monetary penalty;
- cross reference;
- resolved cross reference;
- unresolved cross reference;
- enumerated clause;
- applicability clause;
- exemption clause.

Acceptance:

- Snapshot test passes on the current baseline.
- Snapshot failures show field-level diffs for `deontic_operator`, `subject`, `action`, `conditions`, `exceptions`, `temporal_constraints`, `cross_references`, `parser_warnings`, and `export_readiness`.

### Task 0.2: Add No-LLM Baseline Test

Files:

- `tests/unit_tests/logic/deontic/test_deontic_converter.py`
- possibly `tests/unit_tests/logic/deontic/test_no_llm_parser_contract.py`

Implementation:

- Monkeypatch any known `llm_router` import path to raise if called.
- Parse proof-ready clauses through `DeonticConverter`.
- Assert conversion succeeds and no router path is touched.

Acceptance:

- Simple proof-ready legal clauses run with no model access and no API keys.

## Phase 1: Typed IR

### Task 1.1: Add `LegalNormIR`

Files:

- `ipfs_datasets_py/logic/deontic/ir.py`
- `ipfs_datasets_py/logic/deontic/__init__.py`
- `tests/unit_tests/logic/deontic/test_legal_norm_ir.py`

Implementation:

- Add frozen dataclasses or pydantic-free stdlib dataclasses.
- Include provenance fields directly on the IR.
- Add `from_parser_element(element: Dict[str, Any]) -> LegalNormIR`.
- Add `to_dict()` for stable export and snapshot testing.

Initial dataclasses:

- `SourceSpan`
- `LegalSlot`
- `LegalTemporalConstraint`
- `LegalReference`
- `LegalNormQuality`
- `LegalNormIR`

Acceptance:

- All required parser fields needed by formula/export code map into IR.
- Unknown or missing slots become explicit empty values, not exceptions, unless schema validation already failed.
- Round-trip `from_parser_element(...).to_dict()` is deterministic.

### Task 1.2: Attach IR To Converter Results

Files:

- `ipfs_datasets_py/logic/deontic/converter.py`
- `tests/unit_tests/logic/deontic/test_deontic_converter.py`

Implementation:

- Store the parser element and IR in conversion metadata.
- Preserve existing `ConversionResult.output` behavior.
- For now, keep first-element conversion semantics to avoid broad API churn.

Acceptance:

- Existing converter tests pass.
- New tests can inspect `result.metadata["parser_element"]` and `result.metadata["legal_norm_ir"]`.

## Phase 2: Deterministic Exporters

### Task 2.1: Add IR-To-Deontic Exporter

Status: implemented for deontic/frame formula generation.

Files:

- `ipfs_datasets_py/logic/deontic/formula_builder.py`
- `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`
- `tests/unit_tests/logic/deontic/test_deontic_formula_builder.py`

Implementation:

- Move formula-generation logic behind an IR-aware function.
- Keep `build_deontic_formula(element)` as a compatibility wrapper.
- Generate formulas only from IR slots.
- Carry blockers into proof/readiness metadata.
- Current implementation exposes `build_deontic_formula_from_ir(norm)` and `parser_element_to_formula(element)`.
- The legacy `build_deontic_formula(element)` wrapper delegates to the IR formula path.

Acceptance:

- Current formula strings remain unchanged for existing tests unless a test intentionally documents a bug fix.
- Missing actor/action produces a blocked scaffold, not a fabricated theorem candidate.
- Current verification compares parser-dictionary formulas and typed-IR formulas across obligations, definitions, exemptions, applicability, temporal clauses, exceptions, and instrument lifecycle clauses.

### Task 2.2: Add IR-To-Export Records

Files:

- `ipfs_datasets_py/logic/deontic/exports.py`
- `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`
- `tests/unit_tests/logic/deontic/test_deontic_exports.py`

Implementation:

- Move export row builders to `exports.py`.
- Keep compatibility wrappers in `deontic_parser.py`.
- Add tests for primary keys, source IDs, and dangling references.

Acceptance:

- `build_document_export_tables()` and `validate_document_export_tables()` remain backward compatible.
- Export rows can be derived from IR without re-reading raw text.

## Phase 3: Enumerated Clause Expansion

### Task 3.1: Child Norms For Enumerated Duties

Files:

- `ipfs_datasets_py/logic/deontic/slot_extraction.py` or current parser during pre-modular phase
- `tests/unit_tests/logic/deontic/test_deontic_converter.py`
- `tests/fixtures/legal_parser/enumerations.json`

Implementation:

- Detect modal-governed enumerations such as:
  - `The Secretary shall (1) establish procedures; (2) submit reports; and (3) maintain records.`
- Emit one child parser element per item.
- Preserve parent source ID in a field such as `parent_source_id`.
- Preserve shared actor, modality, conditions, exceptions, temporal constraints, and citation context.
- Add warning only when item-level extraction is uncertain.

Acceptance:

- Each enumerated item can become its own formal logic row.
- Parent/child provenance is stable.
- Clean enumerated items no longer require LLM repair solely because they are enumerated.

## Phase 4: Coverage Expansion

### Task 4.1: Applicability And Exemptions

Status: partially implemented in the current parser.

Implementation:

- Add `norm_type` values or legal-frame categories for applicability and exemption.
- Parse:
  - `This section applies to food carts.`
  - `This chapter does not apply to temporary events.`
  - `A permit is not required for emergency work.`
- Current implementation covers direct applicability, non-applicability, `exempt from`, and not-required permit/license/certificate/registration/approval clauses.

Acceptance:

- Applicability/exemption clauses produce KG and frame-logic records.
- They do not become ordinary obligations unless a clear deontic duty is present.
- Current verification includes proof-ready exemption formulas such as `ExemptFrom(EmergencyWork, Permit)` without LLM repair.

### Task 4.2: Procedural Event Ordering

Status: partially implemented in the current parser.

Implementation:

- Improve `procedure.event_chain`.
- Parse triggers such as `upon receipt`, `after notice and hearing`, `before approval`, and `within N days after X`.
- Generate event-calculus rows from structured procedure details.
- Current implementation adds deterministic event mentions and event-ordering relations for `upon receipt of`, `after ...`, and `before ...` connectors.

Acceptance:

- Event records include stable event IDs, order, anchor event, deadline/duration, and source spans.
- Current event records include mention spans, relation types, and anchor events while preserving the existing `event_chain` contract.

### Task 4.3: Sanction Semantics

Status: partially implemented in the current parser.

Implementation:

- Distinguish civil fine, criminal fine, imprisonment, revocation, suspension, per-day recurrence, minimum, maximum, and discretionary ranges.
- Link sanction clauses to violation clauses when section context or cross references support it.
- Current implementation classifies civil/criminal/administrative sanctions, mandatory/discretionary modality, fine ranges, imprisonment duration, and recurrence.

Acceptance:

- Sanction rows can support proof questions such as "is violation X subject to maximum fine Y?"
- Current sanction rows carry sanction class, modality, range status, recurrence, and enforcement links.

### Task 4.4: Instrument Lifecycle Clauses

Status: partially implemented in the current parser.

Implementation:

- Parse permit/license/certificate/registration/approval/variance validity and expiration clauses.
- Emit `norm_type="instrument_lifecycle"` and frame formulas such as `ValidFor(License, 30Days)` and `ExpiresAfter(Permit, OneYearAfterIssuance)`.
- Preserve KG lifecycle hints for downstream graph queries.

Acceptance:

- Lifecycle clauses do not fall through as non-normative text.
- Converter metadata exposes typed IR and proof-ready lifecycle formulas without LLM repair.

## Phase 5: Parser Modularization

### Task 5.1: Extract Schema And Patterns

Files:

- `ipfs_datasets_py/logic/deontic/schema.py`
- `ipfs_datasets_py/logic/deontic/patterns.py`
- `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`

Acceptance:

- No snapshot changes.
- Public imports keep working.

### Task 5.2: Extract Segmentation And Context

Files:

- `ipfs_datasets_py/logic/deontic/segmentation.py`
- `ipfs_datasets_py/logic/deontic/context.py`

Acceptance:

- Segment spans and hierarchy paths remain byte-for-byte stable in snapshots.

### Task 5.3: Extract Quality And Repair Queue

Files:

- `ipfs_datasets_py/logic/deontic/quality.py`
- `ipfs_datasets_py/logic/deontic/repair.py`

Acceptance:

- `llm_repair.prompt_hash` remains stable for unchanged prompt context.
- `promotable_to_theorem` remains conservative.

## Phase 6: CEC/TDFOL Integration

### Task 6.1: Legal Parser First In Policy Compiler

Files:

- `ipfs_datasets_py/logic/CEC/nl/nl_to_policy_compiler.py`
- `ipfs_datasets_py/logic/CEC/nl/grammar_nl_policy_compiler.py`
- `tests/unit_tests/logic/test_nl_ucan_policy_compiler.py`

Implementation:

- Try legal parser for legal-looking text.
- Convert `LegalNormIR` into policy clauses.
- Preserve grammar fallback for short policy examples.

Acceptance:

- Legal clauses retain conditions, exceptions, and source IDs in metadata.

### Task 6.2: TDFOL From Legal IR

Files:

- `ipfs_datasets_py/logic/integration/bridges/tdfol_grammar_bridge.py`
- `ipfs_datasets_py/logic/TDFOL/nl/`
- `tests/unit_tests/logic/integration/test_tdfol_grammar_bridge.py`

Implementation:

- Add `parse_legal_norm_ir()` or equivalent bridge method.
- Route legal text through parser elements before grammar fallback.

Acceptance:

- Legal text gives the same modality and actor/action slots in Deontic and TDFOL outputs.

## Phase 7: Metrics And CLI

### Task 7.1: Parser Metrics Helper

Files:

- `ipfs_datasets_py/logic/deontic/metrics.py`
- `tests/unit_tests/logic/deontic/test_deontic_parser_metrics.py`

Metrics:

- `element_count`
- `schema_valid_rate`
- `source_span_valid_rate`
- `proof_ready_count`
- `repair_required_count`
- `warning_distribution`
- `cross_reference_resolution_rate`
- `average_scaffold_quality`
- `formal_logic_target_distribution`
- `mean_reconstruction_cosine`
- `mean_reconstruction_cross_entropy`
- `prover_syntax_valid_rate`
- `prover_parse_error_distribution`
- `ungrounded_decoded_token_rate`
- `unreconstructed_source_span_rate`

Acceptance:

- Metrics can run on parser elements without external services.
- Reconstruction metrics are optional until Phase 8 lands, then included when decoder records are supplied.
- Prover syntax metrics are optional until Phase 8 prover adapters land, then included when syntax-check records are supplied.

### Task 7.2: CLI/Report Hook

Files:

- `ipfs_datasets_py/logic/cli.py`
- relevant CLI tests

Implementation:

- Add a report command for a text file or directory.
- Output JSON and optionally markdown.

Acceptance:

- A local legal corpus can be parsed and summarized offline.

## Phase 8: Deterministic Encoder/Decoder Quality Loop

### Task 8.1: Add IR Decoder

Files:

- `ipfs_datasets_py/logic/deontic/decoder.py`
- `ipfs_datasets_py/logic/deontic/ir.py`
- `tests/unit_tests/logic/deontic/test_deontic_decoder.py`

Implementation:

- Add a deterministic `decode_legal_norm_ir(norm: LegalNormIR) -> DecodedLegalText` function.
- Render normalized legal text from IR slots only: actor, modality, action, recipient, conditions, exceptions, overrides, temporal constraints, references, penalties, procedures, and lifecycle details.
- Preserve source grounding by carrying the source slot names and spans used for every decoded phrase.
- Avoid free-form generation. The decoder may normalize grammar and ordering, but it must not invent legal facts.

Acceptance:

- Simple obligations, permissions, prohibitions, definitions, applicability, exemptions, and lifecycle clauses round-trip into readable normalized text.
- Decoded text changes when an important IR slot is removed, making lossy encodings visible.
- Each decoded phrase can be traced back to one or more IR slots or marked as a fixed grammatical connective.

### Task 8.2: Add Encoder/Decoder Metrics

Files:

- `ipfs_datasets_py/logic/deontic/reconstruction_metrics.py`
- `ipfs_datasets_py/logic/deontic/metrics.py`
- `tests/unit_tests/logic/deontic/test_deontic_reconstruction_metrics.py`

Implementation:

- Add `evaluate_ir_reconstruction(source_text, norm, decoded_text, scorer=...)`.
- Compute embedding cosine similarity between source/support text and decoded text.
- Compute token or sequence cross-entropy loss with a pinned scorer. Prefer a local deterministic scorer for CI; allow heavier model-backed scoring only behind an explicit optional dependency flag.
- Include theorem-prover syntax-check status when prover validation records are available.
- Compute ungrounded decoded-token rate by comparing decoded phrase provenance against IR field spans.
- Compute unreconstructed source-span rate by checking which legally salient source spans were not represented in decoded provenance.

Acceptance:

- Metrics run offline in the default unit-test path.
- Optional embedding/language-model scorers are pinned and reported with model/version metadata.
- Low similarity or high loss produces diagnostics listing missing or ungrounded slots.
- Metrics are diagnostic at first and do not promote proof readiness.

### Task 8.3: Add Prover Syntax Validation Bridge

Files:

- `ipfs_datasets_py/logic/deontic/prover_syntax.py`
- `ipfs_datasets_py/logic/deontic/formula_builder.py`
- `ipfs_datasets_py/logic/deontic/exports.py`
- `tests/unit_tests/logic/deontic/test_deontic_prover_syntax.py`

Implementation:

- Add a `validate_ir_with_provers(norm: LegalNormIR, targets=...) -> ProverSyntaxReport` helper.
- Feed the same `LegalNormIR` used by the encoder/decoder through formal exporters before validation.
- Support syntax-only validation targets first:
  - deontic/FOL internal formula parser;
  - TDFOL bridge/parser where available;
  - CEC formula/proof-obligation parser where available;
  - optional external prover front ends such as Z3, CVC5, SPASS, Vampire, E, Lean, Coq, or Isabelle only behind explicit availability checks.
- Record target name, target version when known, exported formula, parse status, diagnostics, and whether validation was skipped because a prover is unavailable.
- Treat parser/syntax failures as quality failures for the encoder/exporter path, not as proof failures. Full theorem proving is a later layer.

Acceptance:

- Proof-ready fixture clauses produce syntax-valid formulas for every enabled local target.
- Unavailable external provers are reported as skipped, not failed, in default unit tests.
- Malformed formulas produce structured parse diagnostics with source IDs and target names.
- A clause cannot be counted as formally valid in encoder/decoder reports unless its exported formula passes syntax validation for at least one enabled target.

### Task 8.4: Add Round-Trip Fixtures

Files:

- `tests/fixtures/legal_parser/reconstruction_roundtrip.json`
- `tests/unit_tests/logic/deontic/test_deontic_reconstruction_fixtures.py`

Implementation:

- Add reviewed fixtures for representative clauses:
  - simple obligation;
  - simple prohibition;
  - permission;
  - definition;
  - applicability;
  - exemption;
  - temporal deadline;
  - exception;
  - cross reference;
  - penalty or lifecycle clause.
- Store source text, expected key IR slots, expected decoded normalized text, and expected metric bands.
- Store expected prover syntax targets and whether each target must pass, skip, or fail with a known diagnostic.

Acceptance:

- Fixture tests prove that `text -> encoder -> IR -> decoder -> text` is deterministic.
- Exact decoded text is stable for controlled examples.
- Proof-ready fixture formulas pass enabled prover syntax checks.
- Metric bands catch lossy parser changes without requiring LLM calls.

### Task 8.5: Wire Reconstruction And Prover Syntax Into Reports

Files:

- `ipfs_datasets_py/logic/deontic/metrics.py`
- `ipfs_datasets_py/logic/cli.py`
- relevant CLI tests

Implementation:

- Add reconstruction summaries to parser metric reports:
  - mean and median cosine similarity;
  - mean cross-entropy;
  - prover syntax-check pass rate;
  - prover parse error distribution;
  - worst examples by similarity and loss;
  - ungrounded decoded-token rate;
  - unreconstructed source-span rate.
- Store per-clause reconstruction and prover syntax records alongside parser/export records.

Acceptance:

- A local legal corpus report shows both formalization quality and reconstruction quality.
- The report makes it clear whether poor quality comes from failed encoding, lossy IR, decoder limitations, scorer limitations, exporter syntax errors, or unavailable prover targets.
- CI can later turn stable reconstruction baselines into regression gates.

## Testing Policy

Every parser behavior change should include:

- at least one positive test;
- at least one negative or ambiguity test;
- a source-span assertion;
- a parser-warning/export-readiness assertion;
- a formula/export assertion if the behavior affects formal output.
- an encoder/decoder reconstruction assertion when the behavior changes legally salient IR slots.
- a prover syntax assertion when the behavior changes a proof-ready formula, exporter target, or formal-logic syntax.

Any change that increases `promotable_to_theorem` coverage must include reviewed fixture examples. Raising proof-readiness is a correctness-sensitive change.

## Backward Compatibility

Do not remove these functions until downstream users have migrated:

- `extract_normative_elements`
- `analyze_normative_sentence`
- `build_deontic_formula`
- `build_formal_logic_record`
- `build_proof_obligation_record`
- `build_document_export_tables`
- `validate_document_export_tables`
- `write_document_export_parquet`

Compatibility wrappers are acceptable while implementation moves into smaller modules.

## Immediate Next PR

Recommended first PR:

1. Add `tests/fixtures/legal_parser/`.
2. Add `test_deontic_parser_snapshots.py`.
3. Add 10 baseline fixtures from existing unit-test examples.
4. Add `ir.py` with `LegalNormIR`.
5. Add `test_legal_norm_ir.py`.
6. Attach IR to `DeonticConverter` metadata.

This PR creates the safety rail and typed spine needed for the later parser improvements.
