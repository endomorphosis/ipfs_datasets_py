# Deterministic Modal Legal Parser Improvement Plan

## Goal

Evolve `logic_theorem_optimizer` from a mostly deontic/temporal-deontic extractor into a deterministic legal parser and training pipeline that supports multiple modal logics, uses BM25 to guide frame/ontology selection, and learns encoder/decoder representations from U.S. Code samples.

The target system should:

- Parse legal text into deterministic intermediate representations rather than relying on prompt-only extraction.
- Represent modal families explicitly: alethic, deontic, temporal, epistemic, doxastic, dynamic/action, conditional/normative, and frame logic.
- Use BM25 over candidate ontology frames to choose or rank frame logic interpretations before neural scoring.
- Treat U.S. Code sections as reproducible samples with text, citation metadata, embedding vectors, intermediate logic IR, decoded embeddings, and losses.
- Optimize an encoder/decoder pair with cross entropy, cosine similarity, reconstruction loss, and symbolic validity checks.
- Keep the existing optimizer contract usable through `LogicTheoremOptimizer`, `LogicExtractor`, `LogicCritic`, `LogicHarness`, and `TheoremSession`.

## Current State

Relevant modules already present:

- `ipfs_datasets_py/optimizers/logic_theorem_optimizer/logic_extractor.py`
  - LLM-oriented extraction agent.
  - Uses `LogicExtractionConfig`.
  - Supports RAG, KG integration, and formula translation hooks.
- `ipfs_datasets_py/optimizers/common/extraction_contexts.py`
  - Defines `ExtractionMode` as `TDFOL`, `FOL`, `CEC`, `MODAL`, `DEONTIC`, and `AUTO`.
  - Modal logic is currently one coarse bucket.
- `ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_translation.py`
  - Defines `FormulaFormalism` with the same coarse modal/deontic split.
  - TDFOL fallback logic is pattern based and strongest for obligation, permission, and prohibition.
- `ipfs_datasets_py/logic/integration/converters/modal_logic_extension.py`
  - Provides modal/deontic/temporal/epistemic/doxastic conversion primitives.
  - This is useful but should be made parser/registry driven for deterministic use.
- `ipfs_datasets_py/logic/TDFOL/*` and `ipfs_datasets_py/logic/CEC/*`
  - Existing theorem/prover strategy surface for temporal, deontic, and modal tableaux work.
- `ipfs_datasets_py/optimizers/graphrag/*`
  - Existing ontology generation, critic, search, learning, validation, and pipeline infrastructure.
- `ipfs_datasets_py/utils/embedding_adapter.py`
  - Existing embedding adapter surface that can be reused for sample vectors.

Primary gaps:

- Modal family semantics are not first-class configuration values.
- Parser behavior is not deterministic enough for legal reproducibility.
- Frame logic does not yet use a lexical retrieval stage for ontology framing.
- There is no legal sample autoencoder dataset contract.
- Critic scoring does not yet combine symbolic validity with embedding reconstruction losses.

## Architecture

### 1. Modal Logic Registry

Add a registry module, tentatively:

`ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py`

Core types:

- `ModalLogicFamily`
  - `ALETHIC`
  - `DEONTIC`
  - `TEMPORAL`
  - `EPISTEMIC`
  - `DOXASTIC`
  - `DYNAMIC`
  - `CONDITIONAL_NORMATIVE`
  - `FRAME`
  - `HYBRID`
- `ModalSystem`
  - Examples: `K`, `T`, `D`, `K4`, `S4`, `S5`, `KD`, `KD45`, `CTL`, `LTL`, `PDL`, `STIT`.
- `ModalOperatorSpec`
  - Symbol, aliases, arity, scope rules, legal cue terms, and allowed systems.
- `ModalSemanticsSpec`
  - Frame constraints such as reflexive, transitive, serial, symmetric, Euclidean, tree-time, action-transition, or ontology-frame grounded.
- `ModalParseProfile`
  - Family, system, grammar, normalizer, parser, prover adapters, and serialization rules.

Design rule: `ExtractionMode.MODAL` remains backward-compatible, but new code should prefer `formalism_hint` or a new `modal_profile` field to choose a precise modal family/system.

### 2. Deterministic Legal Parse Pipeline

Add a deterministic parser layer before LLM extraction:

`legal_modal_parser.py`

Pipeline:

1. Normalize legal text.
   - Preserve section numbers, citations, definitions, exceptions, enumerated clauses, deadlines, and cross references.
2. Segment text into legal units.
   - Section, subsection, paragraph, clause, exception, definition, rule, condition, remedy, penalty.
3. Extract cue spans.
   - Deontic: shall, must, may, may not, prohibited, required.
   - Temporal: before, after, within, until, annually, effective date.
   - Epistemic/doxastic: knows, finds, determines, believes, has reason to know.
   - Dynamic/action: files, serves, transfers, terminates, enforces, authorizes.
   - Conditional/normative: if, unless, except, provided that, subject to.
4. Build typed AST.
   - `LegalRule`, `Condition`, `Actor`, `Action`, `Object`, `TemporalConstraint`, `Exception`, `CrossReference`, `Authority`.
5. Compile AST to modal IR.
6. Validate IR against the selected modal profile.
7. Emit traceable provenance.
   - Every predicate/operator should point back to text spans and citations.

This parser should be deterministic and seed independent. Any LLM use should be optional fallback or annotation, never the first source of truth for legal samples.

### 3. Intermediate Representation

Add a shared IR module:

`modal_ir.py`

IR requirements:

- Stable JSON serialization.
- Hashable/canonical representation for cache keys.
- Span provenance for every extracted unit.
- Operator family and modal system labels.
- Frame candidates and BM25 evidence.
- Prover target metadata.
- Training target metadata.

Suggested objects:

- `ModalIRDocument`
- `ModalIRStatement`
- `ModalIRFormula`
- `ModalIROperator`
- `ModalIRPredicate`
- `ModalIRFrame`
- `ModalIRProvenance`
- `ModalIRTrainingView`

Canonicalization should sort unordered fields, normalize whitespace, preserve citation strings, and generate deterministic IDs from content hashes.

### 4. BM25-Guided Frame Logic

Add a frame selector:

`frame_bm25_selector.py`

Inputs:

- Parsed legal unit text.
- Extracted cue spans.
- Candidate ontology frames from GraphRAG ontology templates/search.
- Optional domain labels such as criminal, tax, housing, civil rights, administrative, benefits, immigration.

Outputs:

- Ranked frame candidates.
- BM25 score.
- Matched terms.
- Frame explanation.
- Selected frame ID or top-k frame set.

Candidate frames can come from:

- `optimizers/graphrag/ontology_search.py`
- `optimizers/graphrag/ontology_templates.py`
- `optimizers/graphrag/ontology_generator.py`
- U.S. Code-derived frame inventories.

Scoring:

```text
frame_score =
  w_bm25 * normalized_bm25
  + w_cue * modal_cue_coverage
  + w_citation * citation_context_match
  + w_ontology * ontology_consistency
  + w_symbolic * parse_validity
```

Keep BM25 as the first-stage deterministic ranker. Neural embeddings may rerank, but should not replace the lexical explanation.

### 5. U.S. Code Sample Dataset

Create a reproducible dataset contract:

`legal_samples.py`

Sample schema:

- `sample_id`
- `source`: `us_code`
- `title`
- `section`
- `subsection`
- `citation`
- `effective_date`, when available
- `text`
- `normalized_text`
- `embedding_model`
- `embedding_vector`
- `modal_profile`
- `modal_ir`
- `frame_candidates`
- `selected_frame`
- `parser_trace`
- `prover_results`
- `encoder_state`
- `decoder_output_embedding`
- `losses`

Data splits:

- Train: broad statutory coverage.
- Validation: same titles, unseen sections.
- Test: held-out titles and hard cases.
- Golden set: manually inspected samples covering every modal family.

Hard cases to include:

- Nested exceptions.
- Definitions that alter rule scope.
- Cross-references.
- Duties with deadlines.
- Permissions with conditions.
- Agency findings/knowledge requirements.
- Sanctions and remedies.
- Retroactivity/effective-date language.

### 6. Encoder/Decoder Training Path

Add an experimental trainer package, or keep it under the optimizer until stable:

`modal_autoencoder.py`

Flow:

```text
U.S. Code text
  -> embedding vector x
  -> deterministic modal parser
  -> modal IR y
  -> encoder z = Encoder(x, y features)
  -> intermediate representation h
  -> decoder x_hat = Decoder(h, y/frame constraints)
  -> reconstructed embedding vector
  -> losses and critic score
```

Losses:

- `cosine_loss = 1 - cosine_similarity(x, x_hat)`
- `mse_reconstruction_loss = MSE(x, x_hat)`
- `cross_entropy_loss`
  - For discrete targets such as modal family, modal system, operator class, frame ID, predicate class, and clause role.
- `symbolic_validity_penalty`
  - Penalize unparseable or prover-invalid decoded structures.
- `frame_ranking_loss`
  - Pairwise or listwise loss over BM25-positive frame candidates.
- `provenance_loss`
  - Optional classification loss for matching formula nodes back to spans.

Composite objective:

```text
total_loss =
  alpha * cross_entropy_loss
  + beta * cosine_loss
  + gamma * mse_reconstruction_loss
  + delta * symbolic_validity_penalty
  + epsilon * frame_ranking_loss
```

Training should be deterministic by default:

- Fixed seed.
- Stable splits.
- Stable sample ordering.
- Frozen embedding model for baseline experiments.
- Versioned ontology/frame inventory.

### 7. Critic and Optimizer Updates

Extend `LogicCritic` dimensions:

- `modal_profile_accuracy`
- `operator_scope_accuracy`
- `frame_selection_quality`
- `symbolic_validity`
- `provenance_coverage`
- `embedding_reconstruction`
- `decoder_consistency`

Extend `ExtractionMetrics`:

- `modal_family_accuracy`
- `modal_system_accuracy`
- `bm25_frame_top1`
- `bm25_frame_top3`
- `embedding_cosine_similarity`
- `cross_entropy_loss`
- `reconstruction_loss`
- `symbolic_validity_rate`

Extend `LogicOptimizer` recommendations:

- Bad modal family classification.
- Bad frame selection.
- Overbroad obligation extraction.
- Missed condition/exception.
- Cross-reference not resolved.
- Embedding reconstruction drift.
- Decoder produces non-canonical IR.

## Implementation Phases

### Phase 0: Baseline Audit

Deliverables:

- Inventory current modal/deontic parser behavior.
- Add smoke tests showing current `MODAL` behavior across alethic, temporal, epistemic, doxastic, dynamic, and frame examples.
- Record baseline scores for deontic-heavy samples versus non-deontic modal samples.

Acceptance criteria:

- A failing or xfail test matrix documents what is currently unsupported.
- Baseline metric report exists for at least 50 legal snippets.

### Phase 0.5: Supervised Test Harness

Deliverables:

- A deterministic test profile that can be run by a todo daemon, supervisor, CI job, or local shell without network access.
- A small legal fixture pack that covers:
  - U.S. Code-style obligations, permissions, prohibitions, exceptions, definitions, and effective dates.
  - Non-deontic modal examples for alethic, temporal, epistemic, doxastic, dynamic/action, conditional/normative, and frame logic.
  - Frame-selection examples with known top-1 and top-3 ontology frame expectations.
- A supervised test command set with explicit fast, integration, golden, and slow profiles.
- Machine-readable test output (`junitxml` and JSON summary when available) so the daemon can mark TODO items as pass/fail without asking an LLM to interpret logs.

Acceptance criteria:

- Fast profile runs without external LLM calls.
- Failures are traceable to a specific modal family, source fixture, and parser stage.
- Supervisor can rerun only impacted tests after changes to parser, IR, BM25 selector, critic, or autoencoder code.
- The test profile is documented in this plan and in the optimizer TODO backlog.

### Phase 1: Modal Registry and Contracts

Deliverables:

- `modal_registry.py`
- `modal_ir.py`
- Backward-compatible config extension.
- Serialization tests for all modal families.

Acceptance criteria:

- `ExtractionMode.MODAL` still works.
- New modal profile selection is explicit and deterministic.
- IR round trips through JSON without loss.

### Phase 2: Deterministic Legal Parser

Deliverables:

- `legal_modal_parser.py`
- Legal segmentation and cue-span extraction.
- AST-to-IR compiler.
- Golden tests for legal rules, exceptions, definitions, and deadlines.

Acceptance criteria:

- Parser output is stable across repeated runs.
- Every emitted formula has provenance spans.
- Deontic samples match or improve current behavior.

### Phase 3: BM25 Frame Selector

Deliverables:

- `frame_bm25_selector.py`
- Frame candidate schema.
- GraphRAG ontology search/template integration.
- Top-k frame explanation output.

Acceptance criteria:

- BM25 top-k is deterministic.
- Top-3 frame recall is measured on a small golden legal frame set.
- Selected frame and matched terms appear in parser trace.

### Phase 4: U.S. Code Sample Builder

Deliverables:

- `legal_samples.py`
- Dataset builder CLI.
- Stable JSONL/Parquet output.
- Sample validation tests.

Acceptance criteria:

- Each sample has citation metadata, text, embedding vector, modal IR, and frame candidates.
- Samples can be regenerated deterministically.
- Corrupt or empty sections are rejected with typed errors.

### Phase 5: Encoder/Decoder Baseline

Deliverables:

- `modal_autoencoder.py`
- Baseline encoder/decoder training loop.
- Loss metric reporting.
- Integration with optimizer metrics.

Acceptance criteria:

- Runs on a small fixture dataset in CI or marked slow.
- Reports cross entropy, cosine similarity, and reconstruction loss.
- Saves model metadata and training config.

### Phase 6: Critic Integration

Deliverables:

- New critic dimensions.
- Optimizer recommendations from symbolic and neural metrics.
- Session result serialization updates.

Acceptance criteria:

- `LogicTheoremOptimizer.run_session` can return modal/frame/embedding metrics.
- Existing logic theorem optimizer tests continue to pass.
- New tests cover bad frame selection, bad operator scope, and poor embedding reconstruction.

### Phase 7: Prover and Semantics Expansion

Deliverables:

- Modal tableaux routing by modal system.
- Frame condition validation.
- Optional integrations for additional provers where useful.

Acceptance criteria:

- K/T/D/S4/S5/KD45-style examples route to correct semantics.
- Frame constraints are validated before prover calls.
- Unavailable provers degrade with explicit `UNAVAILABLE` results.

## Modal Coverage Matrix

| Family | Legal cues | Target systems | Initial deterministic output | Golden examples |
| --- | --- | --- | --- | --- |
| Alethic | necessary, impossible, required by law, cannot | K, T, S4, S5 | necessity/possibility formulas plus frame constraints | legal impossibility, statutory necessity |
| Deontic | shall, must, may, may not, prohibited, required | D, KD, SDL | obligation, permission, prohibition, violation conditions | duties, rights, exemptions |
| Temporal | before, after, within, until, effective, expires | LTL, CTL, TDFOL | time-indexed rule scopes and deadlines | effective dates, limitations periods |
| Epistemic | knows, finds, determines, has reason to know | S4, S5 variants | knowledge/finding operators over actors and agencies | agency findings, notice rules |
| Doxastic | believes, intends, suspects, reasonably believes | KD45 | belief operators with actor provenance | mens rea, good-faith belief |
| Dynamic/action | files, serves, transfers, terminates, authorizes | PDL, action logic, STIT | action transitions and pre/postconditions | service, filing, enforcement |
| Conditional/normative | if, unless, except, provided that, subject to | conditional obligation profiles | condition/exception scoped rule graph | nested exceptions, provisos |
| Frame logic | is-a, part-of, role, authority, jurisdiction | ontology-grounded frames | top-k BM25 frame candidates with explanations | tax/criminal/housing/benefits frames |
| Hybrid | mixed statutory clauses | profile composition | typed multi-family IR with per-node provenance | sections mixing duties, deadlines, findings |

Minimum viable support means the parser can identify the family, emit a canonical IR node, preserve text spans, and either route to a prover/validator or return an explicit `UNAVAILABLE` semantics result.

## LLM Reduction Strategy

The deterministic parser should be the default path. LLM calls are allowed only as explicitly flagged fallbacks:

1. Use normalization, segmentation, cue extraction, grammar rules, and BM25 frame ranking first.
2. Use LLM annotation only for unresolved spans, ambiguous actor/action/object triples, or missing ontology candidates.
3. Cache fallback outputs by canonical text hash, modal profile, ontology inventory version, and prompt/template version.
4. Track `llm_call_count`, `llm_fallback_reason`, and `deterministic_coverage_ratio` in every run.
5. Fail tests if fast/golden deterministic profiles require LLM calls.

Success metric: reduce LLM calls per 1,000 statutory clauses over time while keeping or improving modal-family accuracy, frame top-k recall, symbolic validity, and provenance coverage.

## Supervised Test Commands

These commands define the initial daemon/supervisor contract. The exact supervisor can be a shell loop, CI job, or agentic todo worker, but it should run these profiles and persist outputs.

Fast parser and optimizer contract:

```bash
pytest tests/unit/optimizers/logic_theorem_optimizer tests/test_temporal_deontic_rag.py -q
```

GraphRAG frame-selection adjacency:

```bash
pytest tests/unit/optimizers/graphrag/test_logic_validator_tdfol_conversion.py \
  tests/unit/optimizers/graphrag/test_logic_validator_dag_fraction.py \
  tests/unit/optimizers/graphrag/test_ontology_schema_invariants.py -q
```

Future modal parser suite:

```bash
pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_registry.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_modal_ir.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_legal_modal_parser.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_frame_bm25_selector.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_legal_samples.py \
  tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py -q
```

Recommended supervised loop:

```bash
while true; do
  pytest tests/unit/optimizers/logic_theorem_optimizer tests/test_temporal_deontic_rag.py \
    --junitxml=workspace/test-reports/logic-theorem-fast.xml -q
  sleep 300
done
```

The supervisor should treat missing future test files as pending implementation tasks, not as runtime failures, until the corresponding phase starts.

## Testing Plan

Unit tests:

- Modal registry validation.
- IR serialization and canonical hashes.
- Legal segmentation and clause classification.
- Cue-span extraction.
- AST-to-IR compilation.
- BM25 ranking.
- Dataset sample validation.
- Loss function calculations.

Integration tests:

- `LogicExtractor` deterministic parser path.
- GraphRAG ontology frame retrieval.
- RAG context plus deterministic parse interaction.
- `LogicCritic` with new metrics.
- `LogicTheoremOptimizer.run_session` with modal profile configs.

Golden tests:

- 10 samples per modal family.
- 25 U.S. Code samples with manually reviewed IR.
- 25 U.S. Code samples with manually reviewed frame candidates.

Performance tests:

- Parser throughput per 1,000 legal clauses.
- BM25 frame ranking latency.
- Embedding reconstruction batch throughput.
- Cache hit rate for canonical IR and prover calls.

## Observability

Add structured log fields:

- `modal_family`
- `modal_system`
- `frame_top1`
- `frame_top3`
- `bm25_score`
- `embedding_model`
- `cosine_similarity`
- `cross_entropy_loss`
- `symbolic_validity_rate`
- `sample_id`
- `citation`

Add dashboards or report tables:

- Modal family confusion matrix.
- Frame top-k accuracy.
- Reconstruction loss over time.
- Parser failure reason distribution.
- Prover availability and timeout rates.

## Risks and Mitigations

- Risk: Modal logic scope grows too broad.
  - Mitigation: registry-driven profiles and staged family support.
- Risk: BM25 picks lexically plausible but legally wrong frames.
  - Mitigation: keep top-k candidates, add ontology consistency and golden frame labels.
- Risk: Embedding reconstruction optimizes semantic closeness but loses legal structure.
  - Mitigation: combine reconstruction losses with symbolic validity and provenance metrics.
- Risk: U.S. Code data changes or citations drift.
  - Mitigation: version sample manifests and source snapshots.
- Risk: LLM fallback introduces nondeterminism.
  - Mitigation: deterministic parser is primary; fallback output must be traced and separately flagged.

## Actionable TODO List

- [x] (P0) Add baseline tests proving current deontic behavior still works and documenting unsupported non-deontic modal families with xfail markers.
- [x] (P0) Add the supervised fast test command to the todo daemon or CI runner with `junitxml` output.
- [x] (P1) Add `modal_registry.py` with modal families, systems, operators, cue terms, frame constraints, and parser profile metadata.
- [x] (P1) Add `modal_ir.py` with stable JSON serialization, canonical hashes, and span provenance.
- [x] (P1) Extend `LogicExtractionConfig` with optional `modal_profile` while preserving existing `ExtractionMode.MODAL` behavior.
- [x] (P1) Add deterministic parser smoke tests for all modal families in the coverage matrix.
- [x] (P1) Implement legal text normalization and segmentation for sections, subsections, definitions, exceptions, conditions, remedies, penalties, and cross-references.
- [x] (P1) Implement modal cue-span extraction with deterministic actor/action/object and condition/exception scoping.
- [x] (P1) Implement AST-to-IR compilation with every formula node tied to citation and text-span provenance.
- [x] (P1) Implement `frame_bm25_selector.py` over a small in-repo frame fixture before integrating GraphRAG ontology search.
- [x] (P1) Add frame selector tests for top-1/top-3 BM25 ranking, matched terms, deterministic tie-breaking, and explanation output.
- [x] (P1) Build a 25-sample U.S. Code fixture with stable mocked embeddings and manually reviewed modal IR/frame labels.
- [x] (P2) Add `legal_samples.py` and sample validators for citation metadata, embeddings, modal IR, frame candidates, and parser trace.
- [x] (P2) Wire deterministic parser metadata and frame candidates into `LogicExtractor` without increasing default LLM calls.
- [x] (P2) Add `llm_call_count`, `deterministic_coverage_ratio`, and fallback-reason metrics to extraction/session results.
- [x] (P2) Add critic metrics for modal-family accuracy, modal-system accuracy, operator-scope accuracy, frame top-k quality, symbolic validity, provenance coverage, cosine similarity, and cross entropy.
- [x] (P2) Add `modal_autoencoder.py` with a tiny deterministic fixture training loop and loss reporting.
- [x] (P2) Add tests for cosine loss, MSE reconstruction loss, cross entropy over discrete modal targets, frame ranking loss, and symbolic validity penalty.
- [x] (P2) Add loss-driven TODO generation and batch claiming so the daemon can create multiple work items from cross entropy, cosine, reconstruction, frame ranking, and symbolic parser signals.
- [x] (P2) Add an adaptive encoder/IR/decoder state and supervisor optimization loop that applies claimed TODOs, re-evaluates metrics, and completes TODOs only when cross entropy drops, reconstruction loss drops, or cosine similarity increases.
- [x] (P2) Add a Python/spaCy encoder, modal IR compiler, and deterministic vector decoder so legal text can be parsed and optimized locally before any LLM fallback is considered.
- [x] (P2) Add `justicedao/ipfs_uscode` parquet dataset adapters and tests so the daemon can optimize over U.S. Code `laws.parquet` rows and optional embedding vectors from `laws_embeddings.parquet`.
- [x] (P2) Route K/T/D/S4/S5/KD45-style examples to modal tableaux/prover adapters where available; return typed `UNAVAILABLE` results otherwise.
- [ ] (P2) Add golden tests for 10 examples per modal family and 25 U.S. Code samples with reviewed frame candidates.
- [x] (P3) Add dashboard/report output for modal confusion matrix, frame top-k accuracy, reconstruction loss, parser failure reasons, and prover availability.
- [x] (P3) Promote successful APIs and examples into `QUICK_START.md`, `ARCHITECTURE.md`, and optimizer public docs.

## First Sprint Definition of Done

The first sprint should stop before neural training. It is complete when:

- The existing logic theorem optimizer and temporal-deontic tests are green.
- A new modal registry and IR exist with serialization tests.
- Deterministic parser smoke tests cover all modal families, even if non-core families begin as xfail.
- BM25 frame selection works against a local fixture with deterministic top-k explanations.
- The supervised fast test command can run unattended and produce machine-readable reports.
