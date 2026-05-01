# Deterministic Legal Parser Improvement Plan

Date: 2026-04-28
Baseline reviewed: `b3437217c6c983bab6a2169fe8275b9f900b50b3`
Baseline file: `ipfs_datasets_py/logic/deontic/utils/deontic_parser.py`
Reviewed URL: https://github.com/endomorphosis/ipfs_datasets_py/blob/b3437217c6c983bab6a2169fe8275b9f900b50b3/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py

## Purpose

Improve the deterministic legal parser so legal text can be converted into structured formal-logic artifacts without relying on language model calls as the primary parser.

The desired end state is not "parse every clause no matter what." The desired end state is:

- parse common legal text deterministically into stable, source-grounded slots;
- support a deterministic encoder/decoder quality loop: `text -> encoder -> LegalNormIR -> decoder -> reconstructed text`;
- emit formal logic only from structured slots with provenance;
- refuse, downgrade, or queue uncertain clauses instead of fabricating formalizations;
- reserve LLM calls for optional repair or review of explicitly blocked clauses;
- measure coverage, precision, proof-readiness, repair-rate, reconstruction similarity, and reconstruction loss over a legal corpus.

## Current Baseline

The strongest deterministic legal parser is `logic/deontic/utils/deontic_parser.py`. It is already more capable than a simple regex pass:

- schema versioning via `PARSER_SCHEMA_VERSION = "deterministic_deontic_v12"`;
- a stable parser element contract in `PARSER_REQUIRED_FIELDS`;
- statute-aware segmentation with section and hierarchy metadata;
- modal norm detection for obligations, permissions, prohibitions, definitions, penalties, violations, passive clauses, and impersonal norms;
- extraction of actors, actions, action verbs, objects, recipients, conditions, exceptions, override clauses, temporal constraints, cross references, monetary amounts, penalties, procedure details, ontology terms, and KG hints;
- deterministic source IDs, canonical citations, field spans, and support spans;
- cross-reference and definition context propagation;
- export records for canonical rows, formal logic rows, proof obligations, KG triples, clause records, reference records, procedure events, sanctions, ontology entities, and repair queue rows;
- scaffold quality scoring and `promotable_to_theorem` gating;
- `llm_repair` payloads that make optional repair auditable and source-grounded.

Important surrounding modules:

- `logic/deontic/converter.py` wraps this parser through `DeonticConverter`.
- `logic/CEC/native/nl_converter.py` is a smaller DCEC pattern converter and should not be the legal-text source of truth.
- `logic/CEC/native/dcec_english_grammar.py` contains grammar machinery but has incomplete deontic/cognitive/temporal semantic-to-formula conversion.
- `logic/CEC/nl/grammar_nl_policy_compiler.py` maps NL to policy clauses but only preserves `(actor, action, clause_type)` style structure.
- `logic/TDFOL/nl/tdfol_nl_api.py` and related files provide a separate spaCy/pattern TDFOL path; that should consume legal parser IR for legal texts instead of independently parsing statutes.

## Design Principle

The deterministic legal parser should become the canonical front door for legal text. Downstream CEC, TDFOL, FOL, frame-logic, KG, proof, and ZKP artifacts should consume parser elements or a typed legal-logic IR, not re-parse natural language independently.

Language model calls may remain available, but only as an optional repair lane:

- proof-ready deterministic clauses must not call an LLM;
- medium-quality clauses may export KG and scaffold records but should not be theorem-promoted without validation;
- low-quality or blocked clauses should enter a repair queue;
- any LLM repair must validate back against the schema and source spans before it can affect formal artifacts.

## Target Architecture

```text
Legal text
  |
  v
Document segmentation
  - hierarchy headers
  - sections and headings
  - paragraphs and enumerations
  - stable source spans
  |
  v
Clause parser
  - modal/norm detection
  - actor/action/object/recipient extraction
  - condition/exception/override extraction
  - temporal/procedure/sanction extraction
  - definition and cross-reference resolution
  |
  v
LegalNormIR
  - typed deterministic intermediate representation
  - provenance on every major slot
  - quality gates and blockers
  |
  +--> decoder / reconstruction text
  |    - source-grounded paraphrase from IR slots
  |    - no opaque LLM generation
  |    - reconstruction metrics against original support text
  +--> canonical parquet / KG records
  +--> deontic / FOL / TDFOL / frame-logic exporters
  +--> proof obligation records
  +--> event-calculus rows
  +--> repair queue rows
```

## Proposed `LegalNormIR`

Add a typed intermediate representation that is built from parser elements and consumed by all formal exporters.

Candidate fields:

- `schema_version`
- `source_id`
- `canonical_citation`
- `source_text`
- `support_text`
- `source_span`
- `support_span`
- `modality`
- `norm_type`
- `actor`
- `actor_type`
- `action`
- `action_verb`
- `action_object`
- `recipient`
- `conditions`
- `exceptions`
- `overrides`
- `temporal_constraints`
- `cross_references`
- `resolved_cross_references`
- `defined_terms`
- `penalty`
- `procedure`
- `ontology_terms`
- `kg_relationship_hints`
- `field_spans`
- `quality`
- `blockers`
- `export_readiness`

The IR should be immutable or treated as immutable once built. All generated formulas and export rows should be derived from the IR, not raw text.

## Encoder/Decoder Quality Loop

Add a deterministic encoder/decoder pass as a first-class parser quality goal:

```text
source legal text
  -> deterministic encoder
  -> LegalNormIR
  -> formal exporters / prover syntax targets
  -> theorem-prover syntax checks
  -> deterministic decoder
  -> reconstructed legal text
```

The encoder is the parser path that maps source text into `LegalNormIR`. The decoder is a source-grounded rendering layer that maps `LegalNormIR` back into normalized legal text. The decoder is not a language model and should not add facts that are absent from the IR. Its job is to expose whether the IR preserved the legally salient content needed to reconstruct the clause.

Quality metrics:

- embedding cosine similarity between original support text and decoded reconstruction;
- token-level or sequence-level cross-entropy loss of the reconstruction under a fixed local/legal language model or deterministic scorer;
- theorem-prover syntax-check pass rate across exported deontic/FOL/TDFOL/CEC targets;
- slot coverage delta: which source tokens or semantic spans were not represented in the IR;
- hallucination delta: which decoded tokens or slots were not grounded in source spans;
- reconstruction exactness for controlled fixture clauses where canonical normalized text is known.

Operational rules:

- These metrics are diagnostic quality gates, not a replacement for reviewed gold fixtures.
- Embedding and loss models must be pinned, local or reproducible, and never used to modify parser output directly.
- Low reconstruction similarity should create an explicit parser coverage gap or repair item.
- High reconstruction similarity must not automatically promote a clause to proof-ready; proof promotion still depends on deterministic slots, provenance, and blockers.
- Encoder/decoder records must be able to feed the same `LegalNormIR` through formal exporters into theorem-prover syntax validators. A syntax failure is a formalization/export defect even when the natural-language reconstruction looks good.
- Prover access should start with parser/syntax validation and well-formedness checks. Full theorem proving can be layered on later, but Phase 8 must at least prove that the generated formulas are accepted by the target prover front ends.
- The encoder/decoder report should store the original support text, decoded text, metric values, and per-slot provenance so regressions are auditable.

## Workstream 1: Stabilize And Measure

1. Freeze the v12 schema as the baseline contract.
2. Add golden fixtures under `tests/fixtures/legal_parser/`.
3. Capture representative examples from:
   - Portland municipal code;
   - Oregon statutes;
   - US Code;
   - administrative regulations;
   - contracts and policy language.
4. Store expected parser elements as JSON snapshots with stable IDs normalized for deterministic comparison.
5. Add corpus metrics:
   - norm detection precision and recall;
   - actor/action/object/recipient extraction accuracy;
   - condition, exception, temporal, cross-reference, and definition accuracy;
   - proof-ready false positive rate;
   - LLM-repair rate;
   - schema-valid rate;
   - source-span correctness.

Acceptance criteria:

- Existing `tests/unit_tests/logic/deontic/test_deontic_converter.py` tests keep passing.
- Golden fixtures can be regenerated intentionally, but fail on accidental output drift.
- Metrics report current coverage before any broad refactor.

## Workstream 2: Modularize Without Behavior Change

Split `deontic_parser.py` into focused modules while preserving public APIs:

- `schema.py`: schema version, required fields, defaults, export table specs.
- `segmentation.py`: legal sentence, section, hierarchy, and enumeration segmentation.
- `patterns.py`: compiled regexes and vocabulary sets.
- `norm_detection.py`: modal, impersonal, violation, penalty, and definition detection.
- `slot_extraction.py`: actors, actions, verbs, objects, recipients, conditions, exceptions, overrides, temporal constraints.
- `context.py`: definition context, cross-reference resolution, enforcement links, conflict links.
- `quality.py`: scaffold quality, parser warnings, theorem promotion, export readiness.
- `ir.py`: `LegalNormIR` dataclasses and conversion from parser elements.
- `formula_builder.py`: formal logic, proof obligation, and logic-frame generation.
- `exports.py`: parquet-safe records, manifests, validation, serialization.

Acceptance criteria:

- `extract_normative_elements()`, `build_deontic_formula()`, `build_document_export_tables()`, and existing imports remain backward compatible.
- Snapshot tests prove no behavior change during modularization.
- Each module has focused unit tests.

## Workstream 3: Expand Deterministic Coverage

Priority coverage additions:

1. Enumerated duties:
   - emit one child norm per item when a leading modal governs a list;
   - preserve parent norm for provenance;
   - model shared actor, modality, conditions, exceptions, and references.
2. Applicability and exemption clauses:
   - "This section applies to..."
   - "This chapter does not apply to..."
   - "Except as provided..."
3. Procedural timelines:
   - "upon receipt";
   - "after notice and hearing";
   - "before approval";
   - "within N days after X";
   - "whichever is earlier/later".
4. Sanctions and fees:
   - minimum/maximum amounts;
   - per-day recurrence;
   - civil/criminal sanction classification;
   - imprisonment duration;
   - links from violation clauses to sanction clauses.
5. Definitions:
   - `includes`, `does not include`, `means`, `has the meaning given`;
   - section, chapter, title, and document scope;
   - defined-term aliasing in later norms.
6. Authority and delegation:
   - "The Director may adopt rules";
   - "The Bureau is authorized to...";
   - "The Council shall establish by ordinance...".
7. Cross references:
   - section ranges;
   - relative references such as "this subsection";
   - external references such as ORS, CFR, USC, city code.
8. Negation and prohibitions:
   - "No person shall";
   - "It is unlawful for X to Y";
   - "X may not Y";
   - "X is prohibited from Y";
   - double-negative edge cases.

Acceptance criteria:

- Each pattern family has positive tests, negative tests, span tests, and formula export tests.
- New warnings are documented and mapped to deterministic repair or proof-blocking behavior.
- Proof-ready status is conservative: precision is more important than aggressive promotion.

## Workstream 4: Formal Logic Exporters

Upgrade formula generation from string scaffolds into explicit target exporters.

Targets:

- deontic logic: `O`, `P`, `F`, `DEF`;
- FOL: quantified actor and action predicates;
- TDFOL: modality plus temporal constraints;
- event calculus: procedural events, initiates/terminates/happens-before/deadline relations;
- frame logic: definitions, class membership, instruments, actors, regulated objects;
- proof obligations: theorem-candidate records with blockers and provenance.

Rules:

- Exporters consume `LegalNormIR`.
- Exporters never inspect raw source text except for provenance.
- Missing required slots produce blocked records, not guessed formulas.
- Every formula must carry `source_id`, `support_span`, `field_spans`, and `requires_validation`.

Acceptance criteria:

- Formula outputs are deterministic and stable under repeated runs.
- Export validation catches missing primary keys, missing source IDs, and dangling references.
- Clean simple clauses produce proof candidates without LLM repair.
- Complex clauses produce scaffold/repair records without theorem promotion unless deterministic blockers are cleared.

## Workstream 5: CEC, TDFOL, And Policy Integration

Refactor integration points so legal text uses the deterministic legal parser first.

1. `DeonticConverter`
   - keep as the main public API;
   - expose parser elements and IR in result metadata;
   - support multi-formula output for enumerated clauses.
2. `NLToDCECCompiler`
   - call legal parser first for legal-looking text;
   - map `LegalNormIR` to DCEC formulas and `PolicyClause` records;
   - keep grammar fallback for short non-legal policy text.
3. `TDFOLGrammarBridge`
   - add a path from `LegalNormIR` to TDFOL;
   - reserve grammar/pattern fallback for examples or non-legal text.
4. `grammar_nl_policy_compiler.py`
   - preserve clause compilation but add optional legal-parser mode to avoid losing conditions, exceptions, temporal constraints, and references.

Acceptance criteria:

- There is one legal parsing path for legal text.
- CEC/TDFOL/policy outputs agree on source IDs and modalities.
- Existing grammar tests continue passing.

## Workstream 6: LLM Independence And Repair Lane

Change the operational contract from "LLM repairs parser uncertainty" to "LLM may optionally review blocked deterministic parses."

Implementation tasks:

- Add a parser option such as `allow_llm_repair=False` and keep it false by default.
- Add tests that monkeypatch the router and assert proof-ready clauses do not call it.
- Preserve `llm_repair` queue rows as deterministic artifacts.
- Add validator for repaired outputs:
  - schema version must match or migrate;
  - source spans must point into source text;
  - every modified slot must include a rationale;
  - formula outputs must be regenerated from repaired slots, not accepted as opaque model text.

Acceptance criteria:

- The parser can run end to end offline.
- Formal logic and proof candidate generation do not require API keys.
- LLM repair never bypasses deterministic validation.

## Workstream 7: Quality Gates And Metrics

Add a report command or test helper that emits:

- element count;
- schema-valid count;
- proof-candidate count;
- repair-required count;
- warning distribution;
- parse failure categories;
- formula target distribution;
- cross-reference resolution rate;
- average scaffold quality;
- source-span validity rate.
- encoder/decoder reconstruction cosine similarity;
- encoder/decoder reconstruction cross-entropy loss;
- theorem-prover syntax-check pass rate;
- prover-target parse error distribution;
- ungrounded decoded-token rate;
- unreconstructed source-span rate.

Suggested thresholds for initial production gating:

- `schema_valid_rate >= 0.99`
- `source_span_valid_rate >= 0.99`
- `proof_ready_false_positive_rate <= 0.02` on reviewed gold corpus
- `llm_repair_required_rate` tracked by corpus/domain, not globally forced low at first
- `mean_reconstruction_cosine >= 0.85` on reviewed fixture clauses after the decoder baseline exists
- reconstruction cross-entropy tracked by corpus/domain with regressions failing CI once a stable baseline is established
- `prover_syntax_valid_rate >= 0.99` for proof-ready fixture clauses once prover adapters are wired
- zero ungrounded decoded legal facts in proof-ready clauses
- zero LLM calls in deterministic parser tests

## First Implementation Slice

The first slice should be deliberately small:

1. Add golden fixture infrastructure for the current parser.
2. Add `LegalNormIR` dataclasses and conversion from one parser element.
3. Add a deterministic IR-to-deontic formula exporter.
4. Update `DeonticConverter` metadata to include parser element and IR.
5. Add no-LLM regression tests for proof-ready simple clauses.
6. Add enumerated-clause child norm extraction behind an option or in a narrowly tested path.
7. Add a minimal encoder/decoder fixture harness for a few simple clauses, with metrics recorded but not yet used as a hard gate.

This gives the project a typed spine and a measurable baseline before any broad parser surgery.

## Risks

- Regex expansion can become brittle if not tied to corpus fixtures.
- Modularization can cause accidental schema drift unless snapshot tests are introduced first.
- Aggressive proof promotion is more dangerous than repair queue growth.
- Independent CEC/TDFOL parsers can produce inconsistent outputs unless legal text is routed through one canonical IR.
- Reconstruction metrics can reward fluent but legally incomplete text unless paired with slot/provenance audits.
- Prover syntax checks can become too target-specific unless each exported dialect records the target, version, and parse diagnostics.
- LLM repair can silently become a dependency unless tests explicitly forbid router calls in deterministic paths.

## Definition Of Done

The deterministic parser improvement is complete when:

- legal text parsing works offline without model calls;
- proof-ready clauses are generated only from high-quality deterministic slots;
- complex clauses are exported as KG/scaffold/repair records with clear blockers;
- CEC, TDFOL, FOL, KG, and proof exports share stable source IDs and provenance;
- proof-ready formulas from encoder/decoder fixtures pass theorem-prover syntax checks before they are counted as formally valid;
- the gold corpus reports parser quality, repair-rate, and encoder/decoder reconstruction metrics;
- any optional LLM repair is auditable, schema-validated, and never accepted as opaque formal logic.
