# Structured Text/IR Round-Trip Composition and Canonical Compiler Taskboard

This board is directly consumable by
`ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor`
with task prefix `## SRT-`.

The immediate objective is deliberately narrow: determine which composition
of available tools has the lowest semantic reconstruction loss for
structured text through the source-withheld cycle

`T0 text -> constructor -> L1 canonical IR -> realizer -> T1 text -> same constructor -> L2 canonical IR`.

The primary loss is `1 - S(gold IR, L2)`, where `S` is the benchmark's
maximum-weight structural rule score. Failed, missing, or empty results have
loss `1.0`. Forward loss and `L1`/`L2` cycle loss remain separate diagnostics.
Latency, resource use, and model calls are reported separately and are not
folded into reconstruction loss.

Every composition must use the same canonical `{"rules": [...]}` bottleneck.
A realizer may receive `L1` and the case's closed atom vocabulary, but never
the source text, gold IR, native compiler record, or hidden fields. Validators
may reject or annotate a candidate under a preregistered policy, but proof
success does not substitute for semantic fidelity.

The current five-case native-pipeline pilot is preliminary evidence only:
typed deontic has mean end-to-end loss `0.085`, modal plus full spaCy `0.217`,
direct Leanstral `0.393`, and spaCy evidence plus Leanstral `0.515`. The
deterministic native arms currently carry richer unscored records into their
realizers, so this board first constructs a fair constructor-by-realizer
matrix before selecting a canonical implementation.

Supervisor compatibility validation (read-only apart from the temporary
pytest cache):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ipfs_accelerate_py:. python -m pytest \
  -o cache_dir=/var/tmp/srt-taskboard-pytest-cache \
  tests/unit/benchmarks/test_semantic_roundtrip_compiler_taskboard.py -q
```

Implementation should use an isolated worktree or a reviewed snapshot that
contains the benchmark branch changes. Tasks may execute concurrently only
when their declared parallel lanes and predicted files are disjoint. The
single Leanstral model slot serializes all model-backed executions even when
CPU preparation and result analysis run concurrently.

## SRT-001 Freeze the fair composition protocol

- Status: completed
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: docs/benchmarks/semantic_roundtrip_composition_protocol.md, tests/unit/benchmarks/test_semantic_roundtrip_composition_protocol.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/test_semantic_roundtrip_composition_protocol.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/protocol
- Parallel lane: protocol
- Resource class: cpu-small
- Predicted files: docs/benchmarks/semantic_roundtrip_composition_protocol.md, tests/unit/benchmarks/test_semantic_roundtrip_composition_protocol.py
- Interfaces: SemanticRoundTripCompositionProtocol@1
- Conflict policy: Own only the composition protocol and its contract test; do not change constructors, realizers, fixtures, scores, or existing pilot artifacts.
- Preconditions: Review the current pilot report and runner.
- Effects: The canonical bottleneck, loss, coverage, failure, source-withholding, repeat, and selection rules become executable.
- Evidence subset: composition-protocol contract receipt
- Acceptance: Freeze the constructor-by-realizer experiment, primary end-to-end loss, per-case-first repeat aggregation, failure-equals-one policy, source/native-record exclusion, no gold-derived budgets, polarity/copy/full-coverage gates, identical model settings, balanced stochastic order, and the distinction between semantic scoring and post-hoc proof validation.

## SRT-020 Capture exact runnable tool and service identities

- Status: completed
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on:
- Outputs: benchmarks/semantic_roundtrip_capabilities.py, tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py, workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/capabilities
- Parallel lane: capability-probe
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip_capabilities.py, tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py, workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json
- Interfaces: SemanticRoundTripCapabilityInventory@1
- Conflict policy: Probe existing installations and services without installing, starting, stopping, replacing, or reconfiguring them; own only the new probe, test, and run-scoped receipt.
- Preconditions: None.
- Effects: Every scored arm can bind exact spaCy, autoencoder, SyMAI, Leanstral, Hammer/cvc5, Lean, Python, and multiformats identities.
- Evidence subset: runnable-capability identity receipt
- Acceptance: Record requested and effective versions and identities, require the full spaCy pipeline, bind the exact Leanstral endpoint/model/backend and one-slot capacity, distinguish direct Leanstral from SyMAI routing to the same model, load the frozen autoencoder state read-only, exercise bounded cvc5 and Lean smokes, and report unavailable capabilities explicitly without substitutes.

## SRT-002 Factor canonical IR, constructor, realizer, and result contracts

- Status: completed
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-001
- Outputs: benchmarks/semantic_roundtrip/__init__.py, benchmarks/semantic_roundtrip/contracts.py, benchmarks/semantic_roundtrip/metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_contracts_metrics.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_contracts_metrics.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/core
- Parallel lane: contracts
- Resource class: cpu-small
- Predicted files: benchmarks/semantic_roundtrip/__init__.py, benchmarks/semantic_roundtrip/contracts.py, benchmarks/semantic_roundtrip/metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_contracts_metrics.py
- Interfaces: CanonicalRuleIR@1, RoundTripConstructor@1, RoundTripRealizer@1, RoundTripResult@1
- Conflict policy: Extract behavior without changing the existing pilot's outputs; own only the new package contract and metric files.
- Preconditions: SRT-001 freezes the experiment.
- Effects: Constructors and realizers become independently crossable over one canonical IR.
- Evidence subset: canonical-component contract receipt
- Acceptance: Add immutable canonical rule IR and bounded constructor/realizer protocols, preserve the existing weighted exact-assignment score, distinguish forward/cycle/end-to-end loss, assign loss one to failures and empty results, and reject undeclared source or native payload fields at the realizer boundary.

## SRT-003 Implement the common deterministic canonical-IR realizer

- Status: todo
- Completion: manual
- Priority: P0
- Track: decompiler
- Depends on: SRT-002
- Outputs: benchmarks/semantic_roundtrip/realizers/deterministic.py, tests/unit/benchmarks/semantic_roundtrip/test_deterministic_realizer.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_deterministic_realizer.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/deterministic-realizer
- Parallel lane: deterministic-realizer
- Resource class: cpu-small
- Predicted files: benchmarks/semantic_roundtrip/realizers/deterministic.py, tests/unit/benchmarks/semantic_roundtrip/test_deterministic_realizer.py
- Interfaces: CanonicalDeterministicRealizer@1
- Conflict policy: Consume only CanonicalRuleIR and allowed atom labels; do not read source text, gold IR, LegalNormIR, modal records, caches, or model services.
- Preconditions: SRT-002 defines the boundary.
- Effects: Every constructor can be evaluated with the same auditable source-withheld decompiler.
- Evidence subset: deterministic-realizer anti-leakage receipt
- Acceptance: Realize obligation, permission, prohibition, actor, action, object, conditions, exceptions, and temporal facets from canonical IR alone; produce deterministic output; preserve polarity; and pass adversarial tests proving source and native records are unavailable.

## SRT-004 Add the typed-deontic canonical constructor adapter

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-002
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/test_typed_constructor.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_typed_constructor.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/typed-deontic-constructor
- Parallel lane: typed-constructor
- Resource class: cpu-small
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/test_typed_constructor.py
- Interfaces: TypedDeonticCanonicalConstructor@1
- Conflict policy: Adapt the reviewed deontic converter into CanonicalRuleIR without changing production converter or decoder behavior.
- Preconditions: SRT-002 defines CanonicalRuleIR.
- Effects: Typed deontic can be crossed with either deterministic or model realizers.
- Evidence subset: typed-constructor projection receipt
- Acceptance: Project every supported LegalNormIR rule into the exact canonical fields with explicit missingness, stable ordering, no hidden native payload, and parity with the existing typed pilot's L1 projection.

## SRT-005 Add the modal plus full-spaCy canonical constructor adapter

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-002
- Outputs: benchmarks/semantic_roundtrip/constructors/modal_spacy.py, tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/modal-spacy-constructor
- Parallel lane: modal-spacy-constructor
- Resource class: cpu-medium
- Predicted files: benchmarks/semantic_roundtrip/constructors/modal_spacy.py, tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py
- Interfaces: ModalSpacyCanonicalConstructor@1
- Conflict policy: Reuse the pinned full spaCy frontend and modal codec through an adapter; do not change model fallback behavior or production modal semantics.
- Preconditions: SRT-002 defines CanonicalRuleIR.
- Effects: Modal plus spaCy can be crossed with the common deterministic and Leanstral realizers.
- Evidence subset: modal-spacy projection receipt
- Acceptance: Require the requested full spaCy pipeline, project only scored canonical fields, report unavailable/degraded frontends explicitly, preserve source-span diagnostics outside the realizer payload, and match the existing modal-spaCy L1 projection.

## SRT-006 Add fair Leanstral constructor and realizer adapters

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-002, SRT-020
- Outputs: benchmarks/semantic_roundtrip/constructors/leanstral.py, benchmarks/semantic_roundtrip/realizers/leanstral.py, tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/model-adapters
- Parallel lane: leanstral-adapters
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/constructors/leanstral.py, benchmarks/semantic_roundtrip/realizers/leanstral.py, tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py
- Interfaces: LeanstralCanonicalConstructor@1, LeanstralCanonicalRealizer@1
- Conflict policy: Own only benchmark adapters and their tests; reuse the pinned existing service and never start, replace, or duplicate the model.
- Preconditions: SRT-002 defines bounded requests and results.
- Effects: Direct Leanstral and spaCy-evidence Leanstral constructors can be crossed with both realizers.
- Evidence subset: Leanstral canonical-contract receipt
- Acceptance: Bind the exact endpoint/model identity, use the same bounded schema and token policy for all cases without consulting gold rule counts, source-withhold the realizer, expose full-spaCy evidence only to the declared constructor arm, disable cross-arm memory, and record timeout/malformed/unavailable outcomes as loss-one failures.

## SRT-007 Build the eight-cell constructor-by-realizer runner

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-003, SRT-004, SRT-005, SRT-006
- Outputs: benchmarks/semantic_roundtrip/matrix.py, benchmarks/bench_semantic_roundtrip_compositions.py, tests/unit/benchmarks/semantic_roundtrip/test_matrix_runner.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_matrix_runner.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/core-matrix
- Parallel lane: core-matrix
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/matrix.py, benchmarks/bench_semantic_roundtrip_compositions.py, tests/unit/benchmarks/semantic_roundtrip/test_matrix_runner.py
- Interfaces: SemanticRoundTripMatrix@1
- Conflict policy: Compose registered adapters without modifying them; retain the existing pilot runner as a historical reproduction path.
- Preconditions: All four constructor/realizer adapters validate.
- Effects: Typed, modal-spaCy, direct Leanstral, and spaCy-Leanstral constructors are each crossed with deterministic and Leanstral realizers.
- Evidence subset: eight-cell matrix execution receipt
- Acceptance: Run all eight cells through identical canonical L1 payloads, apply the same constructor again to T1, preserve failures in denominators, attach copy and polarity diagnostics, attach Hammer/cvc5 and Lean results post hoc without changing candidates, and emit per-case CID-addressed records.

## SRT-008 Add oracle-reverse calibration and anti-leakage controls

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-003, SRT-004, SRT-006
- Outputs: benchmarks/semantic_roundtrip/calibration.py, tests/unit/benchmarks/semantic_roundtrip/test_oracle_calibration.py, tests/unit/benchmarks/semantic_roundtrip/test_realizer_source_withholding.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_oracle_calibration.py tests/unit/benchmarks/semantic_roundtrip/test_realizer_source_withholding.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/calibration
- Parallel lane: calibration
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/calibration.py, tests/unit/benchmarks/semantic_roundtrip/test_oracle_calibration.py, tests/unit/benchmarks/semantic_roundtrip/test_realizer_source_withholding.py
- Interfaces: OracleReverseCalibration@1, RealizerLeakageGuard@1
- Conflict policy: Add non-ranking calibration and adversarial tests only; do not modify candidate scores or gold fixtures.
- Preconditions: Both common realizers and the fixed typed recompiler exist.
- Effects: Reverse-stage loss is isolated from constructor loss and hidden-channel leakage fails closed.
- Evidence subset: oracle-reverse and anti-leakage receipt
- Acceptance: Measure gold IR through each realizer into the same typed recompiler, mark the arms non-ranking, reject source/native/gold access and gold-derived budgets, detect vacuous empty identity, and prove the common deterministic realizer does not rely on its originating constructor.

## SRT-009 Add repeat scheduling and paired composition statistics

- Status: todo
- Completion: manual
- Priority: P1
- Track: benchmark
- Depends on: SRT-007
- Outputs: benchmarks/semantic_roundtrip/statistics.py, tests/unit/benchmarks/semantic_roundtrip/test_statistics.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_statistics.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/analysis
- Parallel lane: statistics
- Resource class: cpu-small
- Predicted files: benchmarks/semantic_roundtrip/statistics.py, tests/unit/benchmarks/semantic_roundtrip/test_statistics.py
- Interfaces: RoundTripPairedStatistics@1
- Conflict policy: Consume immutable case results only; do not call constructors, realizers, validators, or services.
- Preconditions: SRT-007 defines case-result records.
- Effects: Stochastic arms become comparable without allowing fast failures or repeated easy cases to dominate.
- Evidence subset: paired-statistics contract receipt
- Acceptance: Aggregate repeats within each case before macro-averaging cases, support at least five uncached model repeats, randomize balanced arm order reproducibly, compute paired deltas and case-cluster bootstrap intervals, keep failure loss one, and report exact-rule/facet/coverage/cost metrics separately.

## SRT-010 Make autoencoder guidance a scoreable composition

- Status: todo
- Completion: manual
- Priority: P1
- Track: compiler
- Depends on: SRT-002, SRT-004, SRT-005, SRT-020
- Outputs: benchmarks/semantic_roundtrip/constructors/autoencoder_guided.py, tests/unit/benchmarks/semantic_roundtrip/test_autoencoder_guided_constructor.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_autoencoder_guided_constructor.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/learned-adapters
- Parallel lane: autoencoder-guidance
- Resource class: cpu-medium
- Predicted files: benchmarks/semantic_roundtrip/constructors/autoencoder_guided.py, tests/unit/benchmarks/semantic_roundtrip/test_autoencoder_guided_constructor.py
- Interfaces: AutoencoderGuidedCanonicalConstructor@1
- Conflict policy: Benchmark the existing reviewed state as bounded guidance over a declared deterministic constructor; do not relabel the current post-compiler advisor as an independent text-to-IR model and do not mutate its state.
- Preconditions: Canonical typed and modal adapters exist.
- Effects: The incremental effect of frozen autoencoder frame/slot guidance becomes measurable.
- Evidence subset: autoencoder-guidance attribution receipt
- Acceptance: Pin the state CID and architecture, expose guidance/no-guidance paired arms, forbid sample-memory and target-embedding selection, record which canonical fields changed, use the same common realizers, and report unsupported composition explicitly if guidance cannot causally affect canonical L1.

## SRT-011 Add a canonical SyMAI round-trip contract

- Status: todo
- Completion: manual
- Priority: P1
- Track: benchmark
- Depends on: SRT-002, SRT-006, SRT-020
- Outputs: benchmarks/semantic_roundtrip/constructors/symai.py, benchmarks/semantic_roundtrip/realizers/symai.py, tests/unit/benchmarks/semantic_roundtrip/test_symai_roundtrip_adapters.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_symai_roundtrip_adapters.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/symai-adapters
- Parallel lane: symai-adapters
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/constructors/symai.py, benchmarks/semantic_roundtrip/realizers/symai.py, tests/unit/benchmarks/semantic_roundtrip/test_symai_roundtrip_adapters.py
- Interfaces: SyMAICanonicalConstructor@1, SyMAICanonicalRealizer@1
- Conflict policy: Extend only the benchmark-facing SyMAI contract; preserve the exact inner Leanstral identity so orchestration is not counted as independent model evidence.
- Preconditions: Canonical model adapter contracts exist.
- Effects: Direct Leanstral and the same model routed through SyMAI can be compared fairly.
- Evidence subset: SyMAI incremental-orchestration receipt
- Acceptance: Return canonical rules in both directions, bind the same endpoint/model/settings as direct Leanstral, source-withhold reverse calls, report routing/retry/cache behavior, reject coarse forward-only responses from ranking, and measure only the incremental effect of SyMAI orchestration.

## SRT-012 Add selective Leanstral repair and Hammer candidate selection

- Status: todo
- Completion: manual
- Priority: P1
- Track: compiler
- Depends on: SRT-004, SRT-005, SRT-006, SRT-010
- Outputs: benchmarks/semantic_roundtrip/selective_repair.py, tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/selective-repair
- Parallel lane: selective-repair
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/selective_repair.py, tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py
- Interfaces: SelectiveLeanstralRepair@1, HammerCandidateSelector@1
- Conflict policy: Operate only on bounded missing, contradictory, or low-confidence canonical slots; do not silently rewrite confident fields or let proof validity establish source semantics.
- Preconditions: Deterministic constructors, Leanstral, and autoencoder guidance are scoreable.
- Effects: A selective learned-repair composition can be compared against always-on Leanstral and no-repair baselines.
- Evidence subset: selective-repair causal receipt
- Acceptance: Preregister repair triggers and candidate-selection rules, record every changed field and model call, accept only schema-valid nonempty candidates, use Hammer/cvc5/Lean solely for declared structural constraints, retain the unrepaired baseline, and score rejected or failed repair attempts without hiding them.

## SRT-013 Extend the matrix with autoencoder, SyMAI, and selective repair

- Status: todo
- Completion: manual
- Priority: P1
- Track: benchmark
- Depends on: SRT-009, SRT-010, SRT-011, SRT-012
- Outputs: benchmarks/semantic_roundtrip/extended_matrix.py, tests/unit/benchmarks/semantic_roundtrip/test_extended_matrix.py
- Validation: PYTHONPATH=ipfs_accelerate_py:. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_extended_matrix.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/extended-matrix
- Parallel lane: extended-matrix
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: benchmarks/semantic_roundtrip/extended_matrix.py, tests/unit/benchmarks/semantic_roundtrip/test_extended_matrix.py
- Interfaces: ExtendedSemanticRoundTripMatrix@1
- Conflict policy: Register validated adapters and policies without changing their internals; serialize all users of the one physical Leanstral slot.
- Preconditions: Core matrix statistics and optional component contracts pass.
- Effects: All scoreable tool compositions enter one comparable result schema.
- Evidence subset: extended composition-matrix receipt
- Acceptance: Include no-guidance/guided, no-repair/selective/always-on, direct/SyMAI, deterministic/model realizer, and validation-only overlays where meaningful; omit impossible Cartesian products with typed reasons; preserve identical cases and scoring; and expose every fallback, model call, validation action, and resource identity.

## SRT-014 Execute the pilot composition matrix and freeze the winner

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-008, SRT-013, SRT-020
- Outputs: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json, docs/benchmarks/semantic_roundtrip_composition_results.md, workspace/benchmarks/semantic-roundtrip-compositions/run_manifest.json
- Validation: PYTHONPATH=. python benchmarks/bench_semantic_roundtrip_compositions.py --validate-report docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/execution
- Parallel lane: pilot-execution
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: docs/performance_snapshots/2026-07-26_semantic_roundtrip_composition_pilot.json, docs/benchmarks/semantic_roundtrip_composition_results.md, workspace/benchmarks/semantic-roundtrip-compositions/run_manifest.json
- Interfaces: SemanticRoundTripCompositionDecision@1
- Conflict policy: Write a new run namespace and immutable report only; do not overwrite the historical pilot or promote production code.
- Preconditions: Core, calibration, extended matrix, and statistics tests pass.
- Effects: The lowest-loss full-coverage composition becomes an evidence-bound implementation input.
- Evidence subset: composition-pilot decision receipt
- Acceptance: Run all deterministic cells once and every model-backed cell for at least five uncached repeats in balanced order, score the unchanged pilot cases, enforce source-copy/polarity/full-coverage gates, report per-case and aggregate losses with uncertainty and costs, identify a winner only when evidence distinguishes it, and otherwise record a tie or insufficient evidence without manufacturing a selection.

## SRT-021 Freeze the no-eligible failure and remediation manifest

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-014
- Outputs: benchmarks/semantic_roundtrip/no_eligible_remediation.py, tests/unit/benchmarks/semantic_roundtrip/test_no_eligible_remediation.py, workspace/benchmarks/semantic-roundtrip-compositions/no_eligible_remediation_manifest.json
- Validation: PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py remediation-gate --repo-root .; PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py manifest-gate --repo-root .; PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_no_eligible_remediation.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/no-eligible-manifest
- Parallel lane: remediation-manifest
- Resource class: cpu-small
- Implementation timeout seconds: 3600
- Predicted files: benchmarks/semantic_roundtrip/no_eligible_remediation.py, tests/unit/benchmarks/semantic_roundtrip/test_no_eligible_remediation.py, workspace/benchmarks/semantic-roundtrip-compositions/no_eligible_remediation_manifest.json
- Interfaces: SRT014NoEligibleRemediationManifest@1
- Conflict policy: Read the immutable SRT-014 report and gate receipt without changing the report, protocol, fixture, scores, gates, or historical run manifest; own only the remediation manifest builder, contract test, and new CID-bound manifest.
- Preconditions: The authoritative SRT-014 validator passes, its outcome is exactly `no_eligible_composition`, and `SRT014DownstreamGate@1` classifies every preregistered arm's failed gates and terminal failures.
- Effects: Exact frozen failure evidence becomes bounded, queryable inputs for three disjoint repair lanes.
- Evidence subset: no-eligible remediation manifest receipt
- Acceptance: Emit interface `SRT014NoEligibleRemediationManifest@1` and schema `ipfs-datasets.semantic-roundtrip-no-eligible-remediation.v1`; recompute and bind the exact SRT-014 report path, report CID, report raw CID, and SRT-014 gate CID; retain the gate's exact remediation object with all 30 arm IDs, per-gate affected-arm and coordinate counts, affected case IDs, sampled coordinate keys, terminal failure reason and stage counts, systemic versus component-local classification, and exact recommended remediation inputs. Set status `frozen_no_eligible` and booleans `protocol_immutable`, `replacement_run_required`, and `srt015_fenced` true. Compute the manifest CID over the payload without `manifest_cid` using cid_for_dag_json, reject missing or contradictory evidence, and prescribe a new immutable replacement run rather than mutating SRT-014 or its frozen protocol.

## SRT-022 Repair deterministic source-copy and polarity behavior

- Status: todo
- Completion: manual
- Priority: P0
- Track: decompiler
- Depends on: SRT-021
- Outputs: benchmarks/semantic_roundtrip/realizers/source_withheld_paraphrase.py, tests/unit/benchmarks/semantic_roundtrip/test_source_withheld_paraphrase.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_source_withheld_paraphrase.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/deterministic-remediation
- Parallel lane: deterministic-remediation
- Resource class: cpu-medium
- Implementation timeout seconds: 3600
- Predicted files: benchmarks/semantic_roundtrip/realizers/source_withheld_paraphrase.py, tests/unit/benchmarks/semantic_roundtrip/test_source_withheld_paraphrase.py
- Interfaces: SourceWithheldCanonicalParaphraser@1
- Conflict policy: Add one replacement-experiment deterministic realizer and its tests without modifying the frozen deterministic realizer, constructors, protocol, fixture, report, scorer, or gates.
- Preconditions: SRT-021 identifies deterministic source-copy or polarity failures from immutable coordinate evidence.
- Effects: Canonical L1 can be rendered through a source-withheld deterministic paraphrase that preserves explicit polarity while avoiding source copying.
- Evidence subset: deterministic paraphrase repair receipt
- Acceptance: Accept only canonical L1, the public closed vocabulary, and frozen replacement configuration; forbid T0, gold IR, native records, source-bearing caches, and hidden case fields. Render obligation, permission, and prohibition with distinct explicit constructions; cover conditions, exceptions, and temporal qualifiers; remain deterministic and schema bounded; pass exact normalized-copy and eight-token-overlap negative controls; and emit CIDs and attribution sufficient to prove that no source text entered the realizer. Include the concrete `exception_with_window` obligation regression in which the parser-supported canonical surface `must` replaces `shall`, reparses through `TypedDeonticCanonicalConstructor` to the exact gold CanonicalRuleIR, and reduces shared source eight-gram precision from 1.0 to 0.25 so the frozen source-copy gate passes. Reproduce the five-case typed-constructor round trip with nonempty L1/T1/L2, copy and polarity gates passing on every case, shared eight-gram precisions `[0.25, 0.0, 0.148, 0.0, 0.051]`, and mean primary loss `0.0883333334`, identical to the current baseline semantic score.

## SRT-023 Repair model and SyMAI empty-output and polarity paths

- Status: todo
- Completion: manual
- Priority: P0
- Track: model-adapter
- Depends on: SRT-021
- Outputs: benchmarks/semantic_roundtrip/model_output_recovery.py, tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/model-remediation
- Parallel lane: model-remediation
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/model_output_recovery.py, tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py
- Interfaces: BoundedModelOutputRecovery@1, SyMAIPolarityContract@1
- Conflict policy: Add replacement-experiment wrappers and tests around the already pinned direct and SyMAI routes; do not change provider identity, physical-slot capacity, frozen SRT-014 prompts/results, shared semantic scores, or fallback policy.
- Preconditions: SRT-021 binds empty-L1, blank-T1, empty-L2, route-contract, and polarity failures to exact arm and coordinate identities, including the `legal_doc` model and modal-plus-spaCy polarity failures.
- Effects: Direct and SyMAI model paths receive bounded nonempty/schema/polarity enforcement suitable for a new experiment.
- Evidence subset: model-output remediation receipt
- Acceptance: Preserve the exact Leanstral endpoint, backend, model, tokenizer, one-slot serialization, direct-versus-SyMAI route identity, source-withholding boundary, and no-cache identity. Use role-specific bounded schemas and explicit O/P/F polarity instructions; reject blank, empty, malformed, or polarity-ambiguous outputs; allow only a preregistered bounded retry within the replacement experiment; prohibit silent route substitution, unrecorded fallback, source recovery, or result reuse; and retain every call, rejection, retry, and terminal typed failure in receipts.

## SRT-024 Implement and qualify causal autoencoder guidance

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-021
- Outputs: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/causal-guidance-remediation
- Parallel lane: causal-guidance-remediation
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Interfaces: CausalAutoencoderGuidance@1, CausalGuidanceQualification@1
- Conflict policy: Add a replacement-experiment causal applicator, qualification test, and receipt without retraining or mutating the frozen autoencoder state, changing baseline constructors, using target embeddings, or rewriting SRT-010/SRT-014 evidence.
- Preconditions: SRT-021 identifies guided arms as unsupported or ineligible and binds the exact frozen autoencoder state and architecture identities.
- Effects: The frozen feature representation either causally changes declared L1 fields under a reviewed bounded applicator or receives the evidence-backed classification `unavailable_no_reviewed_causal_l1_adapter`.
- Evidence subset: causal-guidance qualification receipt
- Acceptance: Load the frozen state read-only by CID and verify that the pinned stable export is global and sample-free. If a reviewed feature-to-canonical-field intervention exists, preregister it and produce paired no-guidance/guided outputs under identical non-guidance inputs, requiring a nonempty causal change receipt naming every changed field and feature while preserving schema and source grounding. Otherwise emit `unavailable_no_reviewed_causal_l1_adapter` with the missing causal contract and keep guided coordinates explicit terminal unsupported evidence. In both paths forbid sample memory, gold labels, gold rule counts, target embeddings, outcome-dependent selection, or fabricated L1 mutations; include negative controls proving zero change when guidance is disabled; and never relabel advisory diagnostics as causal guidance.

## SRT-025 Qualify every replacement arm and capability

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-022, SRT-023, SRT-024
- Outputs: benchmarks/semantic_roundtrip/replacement_matrix.py, tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py, workspace/benchmarks/semantic-roundtrip-compositions/replacement_capabilities.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/replacement-qualification
- Parallel lane: replacement-qualification
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/replacement_matrix.py, tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py, workspace/benchmarks/semantic-roundtrip-compositions/replacement_capabilities.json
- Interfaces: QualifiedReplacementSemanticRoundTripMatrix@1
- Conflict policy: Register the three reviewed repair adapters in a new replacement plan without altering their modules, the original 30-arm plan, frozen protocol, fixture, historical reports, scorer, or gate definitions.
- Preconditions: SRT-022 and SRT-023 provide complete repair tests, while SRT-024 provides either a qualified causal applicator or the CID-bound `unavailable_no_reviewed_causal_l1_adapter` receipt.
- Effects: All 30 replacement arms have exact runnable identities and bounded preflight evidence before scored execution.
- Evidence subset: replacement matrix qualification receipt
- Acceptance: Preserve exactly four deterministic and 26 model-backed cells, the same constructor-by-realizer comparison intent, unchanged five pilot cases, per-case-first loss, source-copy/polarity/full-coverage gates, and one physical model slot. Bind every adapter, prompt, schema, autoencoder state, spaCy pipeline, SyMAI route, Leanstral service, Hammer/cvc5 validator, Lean validator, Python environment, and multiformats implementation by version and CID; run non-scored positive and negative smokes for nonempty L1/T1/L2 and O/P/F preservation; reject degraded, fallback, ambiguous, or duplicate identities; preserve honestly unavailable guided arms as explicit typed unsupported paths rather than substituting another component; require at least one fully qualified candidate arm but do not require every arm to be selection-eligible; and freeze the replacement plan and balanced schedule before SRT-026.

## SRT-026 Execute the complete replacement composition matrix

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-025
- Outputs: docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json, docs/benchmarks/semantic_roundtrip_composition_replacement_results.md, workspace/benchmarks/semantic-roundtrip-compositions/replacement_run_manifest.json
- Validation: PYTHONPATH=. python benchmarks/bench_semantic_roundtrip_compositions.py --validate-report docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/replacement-execution
- Parallel lane: replacement-execution
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 21600
- Proposal artifact envelope: {"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@1","paths":["docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json","docs/benchmarks/semantic_roundtrip_composition_replacement_results.md","workspace/benchmarks/semantic-roundtrip-compositions/replacement_run_manifest.json"],"max_file_bytes":12000000,"max_patch_bytes":14000000,"max_output_bytes":24000000}
- Predicted files: docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json, docs/benchmarks/semantic_roundtrip_composition_replacement_results.md, workspace/benchmarks/semantic-roundtrip-compositions/replacement_run_manifest.json
- Interfaces: SemanticRoundTripCompositionDecision@1
- Conflict policy: Execute and publish only in a fresh immutable replacement namespace; never overwrite, amend, pool with, or relabel the SRT-014 report, raw checkpoint, run manifest, protocol, fixture, or decision.
- Preconditions: SRT-025 validates all 30 exact replacement arms and freezes complete identities, prompts, schemas, budgets, one-slot resource policy, and balanced schedule before any scored coordinate.
- Effects: Repaired components receive one complete, directly comparable replacement measurement under the unchanged frozen protocol.
- Evidence subset: replacement composition decision receipt
- Acceptance: Execute exactly 20 deterministic coordinates and 650 model-backed coordinates for 670 total terminal observations, using every deterministic cell once and every model-backed cell in five unique uncached namespaces per unchanged case. Preserve balanced outcome-independent order, source withholding, failure-equals-one denominators, all three gates, per-case-first statistics, uncertainty and cost evidence, post-hoc proof annotations, raw coordinate CIDs, and complete capability lineage. Publish selected, exact_tie, or no_eligible_composition solely from independently recomputable evidence without changing SRT-014.

## SRT-027 Validate the replacement selection gate

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-026
- Outputs: workspace/benchmarks/semantic-roundtrip-compositions/replacement_selection_gate.json, docs/benchmarks/semantic_roundtrip_replacement_selection_gate.md
- Validation: PYTHONPATH=. python benchmarks/semantic_roundtrip_scheduler.py gate --repo-root . --require-authorized --validate-artifact workspace/benchmarks/semantic-roundtrip-compositions/replacement_selection_gate.json
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/replacement-selection-gate
- Parallel lane: replacement-selection-gate
- Resource class: cpu-small
- Implementation timeout seconds: 3600
- Predicted files: workspace/benchmarks/semantic-roundtrip-compositions/replacement_selection_gate.json, docs/benchmarks/semantic_roundtrip_replacement_selection_gate.md
- Interfaces: ReplacementSelectionGate@1, CanonicalDesignGate@1
- Conflict policy: Revalidate and summarize immutable original and replacement evidence without executing inference, changing either report, changing the protocol/gates, manufacturing a winner, or editing canonical implementation files.
- Preconditions: SRT-026 publishes all 670 terminal coordinates and passes the authoritative report validator; refuse authorization for missing, incomplete, invalid, unbounded, or no-eligible replacement evidence.
- Effects: Only a CID-bound replacement unique winner or exact bounded co-winner set can authorize SRT-015.
- Evidence subset: replacement-to-canonical launch receipt
- Acceptance: Independently recompute report and raw CIDs, terminal coverage, every per-case-first loss, all-coordinate gate eligibility, eligible and ranked arm IDs, exact co-winners, and selected or exact-tie outcome. Bind the SRT-014 gate CID, SRT-014 report CID, remediation manifest CID, replacement report CID, replacement gate CID, complete selectable-arm set, and implementation representative; use frozen preregistered order only to choose a tie representative without calling it a semantic winner; emit `launch_authorized: true` only for selected or bounded exact_tie, and leave SRT-015 fenced for no_eligible_composition or any malformed evidence. Write replacement_selection_gate.json as the exact recomputed CanonicalDesignGate@1 receipt, including its self-validating DAG-JSON gate CID; completion validation must reject a missing, stale, extended, truncated, or forged JSON gate artifact rather than trusting its filename or self-asserted status.

## SRT-015 Specify the canonical compiler/decompiler from measured evidence

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-027
- Outputs: docs/architecture/semantic_roundtrip_canonical_compiler.md, docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json, ipfs_datasets_py/logic/legal_ir/canonical_contracts.py, ipfs_datasets_py/logic/legal_ir/schemas/canonical_roundtrip_ir.schema.json, tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py, setup.py, pyproject.toml, MANIFEST.in
- Validation: PYTHONPATH=. python -m pytest tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/canonical-design
- Parallel lane: canonical-design
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Predicted files: docs/architecture/semantic_roundtrip_canonical_compiler.md, docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json, ipfs_datasets_py/logic/legal_ir/canonical_contracts.py, ipfs_datasets_py/logic/legal_ir/schemas/canonical_roundtrip_ir.schema.json, tests/unit/logic/legal_ir/test_canonical_roundtrip_schema.py, setup.py, pyproject.toml, MANIFEST.in
- Interfaces: CanonicalStructuredTextCompiler@1, CanonicalStructuredTextDecompiler@1, CanonicalRoundTripContracts@1, CanonicalRoundTripParityPolicy@1
- Conflict policy: Derive the specification, shared compiler/decompiler contracts, packaged schema, and machine-readable parity policy from the frozen SRT-014 decision; do not select unmeasured tools or copy benchmark-only closed vocabularies into the production API. SRT-016 and SRT-017 consume canonical_contracts.py but do not modify it.
- Preconditions: Require a CID-bound `CanonicalDesignGate@1` receipt from SRT-027 with `launch_authorized: true`, binding the immutable no-eligible SRT-014 report and remediation manifest to an independently validated complete replacement report. Proceed only when the replacement names a full-coverage unique winner or an explicit tie bounded by the frozen 30-arm preregistration. For an exact tie, retain every co-winner and use the first co-winner in frozen preregistered arm order only as the implementation representative with selection basis `replacement_bounded_tie_policy`; do not rewrite either benchmark as a unique-winner result. For missing, incomplete, invalid, unbounded, or no-eligible replacement evidence, retain the machine-readable gate reasons and leave SRT-015 incomplete so implementation tasks remain dependency-blocked without consuming an implementation attempt.
- Effects: The measured composition becomes a stable production-facing interface plan.
- Evidence subset: benchmark-to-canonical-design lineage receipt
- Acceptance: Bind the exact SRT-014 report and gate CIDs, remediation-manifest CID, replacement report and gate CIDs, complete selectable-arm set, implementation representative, and replacement unique-winner or bounded-tie selection basis without claiming that a tie representative is semantically superior. Define canonical CID-addressed IR, compiler/decompiler inputs and outputs, source maps, unsupported semantics, deterministic core, any evidence-supported optional learned stages, versioning, error/abstention behavior, and exact traceability from each chosen component to the replacement measured result while preserving SRT-014 as negative evidence. Freeze a canonical DAG-JSON parity policy at docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json using cid_for_dag_json; bind its policy CID to both immutable benchmark report CIDs and the canonical-design gate CID; declare end-to-end loss direction, per-case-first aggregation, paired case-cluster bootstrap method and confidence level, bootstrap count, and a numeric noninferiority margin before SRT-018 runs. Put shared immutable request/result/error and policy-CID contracts in canonical_contracts.py, and package the JSON schema through setup.py, pyproject.toml, and MANIFEST.in so the parallel compiler and decompiler import one contract rather than redefining it.

## SRT-016 Implement the selected canonical compiler

- Status: todo
- Completion: manual
- Priority: P0
- Track: compiler
- Depends on: SRT-015
- Outputs: ipfs_datasets_py/logic/legal_ir/canonical_compiler.py, tests/unit/logic/legal_ir/test_canonical_compiler.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/logic/legal_ir/test_canonical_compiler.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/canonical-compiler
- Parallel lane: canonical-compiler
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: ipfs_datasets_py/logic/legal_ir/canonical_compiler.py, tests/unit/logic/legal_ir/test_canonical_compiler.py
- Interfaces: CanonicalStructuredTextCompiler@1
- Conflict policy: Own only the new canonical compiler module and test; reuse selected reviewed components through explicit adapters and do not change their public behavior.
- Preconditions: SRT-015 freezes the interface and selected composition.
- Effects: Structured text compiles to the measured canonical IR with CID and source-map receipts.
- Evidence subset: canonical-compiler conformance receipt
- Acceptance: Implement exactly the selected constructor composition, retain deterministic behavior wherever the winner permits it, make optional learned calls explicit and bounded, emit canonical CIDv1 identities and source-grounded diagnostics, reject silent fallback, and reproduce the benchmark adapter's L1 outputs on frozen cases.

## SRT-017 Implement the selected canonical decompiler

- Status: todo
- Completion: manual
- Priority: P0
- Track: decompiler
- Depends on: SRT-015
- Outputs: ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py, tests/unit/logic/legal_ir/test_canonical_decompiler.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/logic/legal_ir/test_canonical_decompiler.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/canonical-decompiler
- Parallel lane: canonical-decompiler
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Predicted files: ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py, tests/unit/logic/legal_ir/test_canonical_decompiler.py
- Interfaces: CanonicalStructuredTextDecompiler@1
- Conflict policy: Own only the new canonical decompiler module and test; consume canonical IR only and never recover or query the original source.
- Preconditions: SRT-015 freezes the interface and selected composition.
- Effects: Canonical IR has one auditable source-withheld natural-language realization path.
- Evidence subset: canonical-decompiler conformance receipt
- Acceptance: Implement exactly the selected realizer composition, preserve modality/polarity/roles/conditions/exceptions/time, remain source-withheld, expose optional model use and failure, emit stable attribution, and reproduce the benchmark adapter's T1 outputs under pinned configuration.

## SRT-018 Integrate and rebenchmark the canonical round-trip

- Status: todo
- Completion: manual
- Priority: P0
- Track: benchmark
- Depends on: SRT-016, SRT-017
- Outputs: ipfs_datasets_py/logic/legal_ir/__init__.py, ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py, tests/integration/logic/test_canonical_semantic_roundtrip.py, docs/performance_snapshots/2026-07-26_canonical_semantic_roundtrip.json
- Validation: PYTHONPATH=. python -m pytest tests/integration/logic/test_canonical_semantic_roundtrip.py -q
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/canonical-validation
- Parallel lane: canonical-integration
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 14400
- Predicted files: ipfs_datasets_py/logic/legal_ir/__init__.py, ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py, tests/integration/logic/test_canonical_semantic_roundtrip.py, docs/performance_snapshots/2026-07-26_canonical_semantic_roundtrip.json
- Interfaces: CanonicalSemanticRoundTrip@1
- Conflict policy: Integrate the two new modules without altering benchmark fixtures, gold IR, score weights, or selected component implementations.
- Preconditions: Canonical compiler and decompiler independently conform, and the exact canonical DAG-JSON parity-policy CID frozen by SRT-015 is available through canonical_contracts.py. Refuse execution if the policy is missing, changed, or not bound to the immutable SRT-014 report CID, replacement report CID, and canonical-design gate CID.
- Effects: The production-facing implementation is compared directly with the frozen winning benchmark composition.
- Evidence subset: canonical-roundtrip parity receipt
- Acceptance: Run source text through canonical compiler, source-withheld canonical decompiler, and canonical compiler again; require full nonempty coverage, no polarity hard failures, no source-copy violation, and result parity against the exact selected replacement arm under the SRT-015 policy CID without estimating or changing a tolerance after seeing SRT-018 results. Recompute the per-case deltas and the frozen upper-confidence-bound noninferiority rule, preserve every case-level L1/text/L2 CID, require passing Hammer/cvc5 and Lean structural checks where applicable, expose the integrated API through legal_ir/__init__.py, and record complete implementation/config/model lineage plus both immutable benchmark report CIDs.

## SRT-019 Publish the canonical selection and supervisor handoff

- Status: todo
- Completion: manual
- Priority: P1
- Track: benchmark
- Depends on: SRT-018
- Outputs: benchmarks/semantic_roundtrip/canonical_decision.py, benchmarks/bench_semantic_roundtrip_compositions.py, tests/unit/benchmarks/semantic_roundtrip/test_canonical_decision.py, docs/benchmarks/semantic_roundtrip_canonical_compiler_decision.md, docs/performance_snapshots/semantic_roundtrip_canonical_compiler_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_canonical_decision.py -q; PYTHONPATH=. python benchmarks/bench_semantic_roundtrip_compositions.py --validate-canonical-decision docs/performance_snapshots/semantic_roundtrip_canonical_compiler_decision.json
- Board namespace: semantic-roundtrip-canonical-compiler-v1
- Bundle: semantic-roundtrip/handoff
- Parallel lane: final-handoff
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/canonical_decision.py, benchmarks/bench_semantic_roundtrip_compositions.py, tests/unit/benchmarks/semantic_roundtrip/test_canonical_decision.py, docs/benchmarks/semantic_roundtrip_canonical_compiler_decision.md, docs/performance_snapshots/semantic_roundtrip_canonical_compiler_decision.json
- Interfaces: CanonicalCompilerDecision@1
- Conflict policy: Own the canonical-decision validator module, its CLI dispatch and contract tests, and the two handoff artifacts. Preserve the SRT-014 report validator and benchmark execution behavior; summarize immutable measured and conformance artifacts without rewriting task statuses or making deployment changes.
- Preconditions: Revalidate the immutable no-eligible SRT-014 report and remediation manifest, the replacement report and canonical-design gate, and the source-bound SRT-018 parity receipt. Publish a selected decision only for a replacement unique winner or SRT-015 bounded replacement co-winner whose exact frozen-policy parity passes; otherwise publish an explicit declined decision and no canonical selection.
- Effects: Operators receive the selected tool composition, reconstruction loss, limitations, reproducible commands, and implementation identities.
- Evidence subset: final canonical-compiler decision receipt
- Acceptance: State the replacement winning composition and unchanged replacement uncertainty while preserving SRT-014 as no-eligible negative evidence; distinguish deterministic and bounded optional learned stages; classify typed deontic, modal, spaCy, the deterministic realizer, autoencoder, SyMAI, Leanstral, selective repair, Hammer, cvc5, Lean, and multiformats exactly once as scored, unavailable, or unscored; bind the raw CIDs of every original, remediation, replacement, gate, and implementation artifact; and include exact reproduction and supervisor plan/launch commands. The validator must recompute file CIDs, original and replacement selectability, per-case SRT-018 deltas, the exact SRT-015 policy CID and upper-confidence-bound tolerance decision, implementation/config/model lineage, coverage/polarity/source-copy gates, and structural-check disposition; malformed, incomplete, drifted, or self-asserted evidence fails closed, while nonselectable replacement evidence can only produce an explicit declined decision.
