# Semantic Round-Trip Evaluation Harness Repair Taskboard

This board is consumable by
`ipfs_accelerate_py.agent_supervisor` via
`benchmarks.semantic_roundtrip_scheduler` with task prefix `## EVAL-`.

## Objective

The replacement matrix shell runs (670/670 terminals), but most optional
methods were **not fairly measured**:

- 260 coordinates: `post_schedule_capability_unavailable` (all guided/autoencoder)
- 210 coordinates: `retry_exhausted` (mostly Leanstral routes)
- selective-repair arms succeeded with `model_calls=0` (never triggered)
- Leanstral/SyMAI capability smokes did not perform live model inference
- loss=1.0 for unsupported arms polluted "beats baseline" conclusions

Repair the harness so the next matrix can answer: which compositions of
autoencoder, SyMAI, spaCy, Leanstral, Hammer, and selective repair can
**improve** the deterministic typed-deontic → IR → deterministic realizer
path (especially **forward** loss), rather than only freeze the baseline.

Do not weaken fail-closed selection for production promotion. Research
modes may score stage-local metrics; promotion still requires full gates.

## EVAL-001 Classification and launch preflight

- Status: completed
- Completion: auto
- Priority: P0
- Track: harness
- Depends on:
- Outputs: benchmarks/semantic_roundtrip/evaluation_status.py, tests/unit/benchmarks/semantic_roundtrip/test_evaluation_status.py, docs/benchmarks/semantic_roundtrip_eval_status_contract.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_evaluation_status.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-status
- Parallel lane: eval-status
- Resource class: cpu-small
- Implementation timeout seconds: 3600
- Predicted files: benchmarks/semantic_roundtrip/evaluation_status.py, tests/unit/benchmarks/semantic_roundtrip/test_evaluation_status.py, docs/benchmarks/semantic_roundtrip_eval_status_contract.md
- Interfaces: SemanticRoundTripEvaluationStatus@1
- Conflict policy: Own only evaluation status taxonomy and contract tests; do not change constructor semantics or fixtures.
- Preconditions: Review replacement report failure reason counts.
- Effects: Coordinates classify as not_measured, runtime_failed, or semantic_scored; unsupported no longer looks like semantic loss 1.0 on leaderboards.
- Evidence subset: evaluation-status contract receipt
- Acceptance: Define disjoint statuses `not_measured` (terminal_unsupported / preflight_blocked), `runtime_failed` (retry_exhausted, provider error), and `semantic_scored` (success with defined gates). Default leaderboard and paired baseline comparisons use only `semantic_scored` plus the deterministic baseline. Matrix launch fails closed if any scheduled arm lacks required preflight (live smoke or causal qualification). Document the contract and cover it with unit tests including the guided-arm and retry_exhausted cases from the 2026-07-27 replacement run.

## EVAL-002 Live model and route smokes before schedule

- Status: completed
- Completion: auto
- Priority: P0
- Track: harness
- Depends on: EVAL-001
- Outputs: benchmarks/semantic_roundtrip_capabilities.py, tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py, workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-live-smoke
- Parallel lane: eval-live-smoke
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip_capabilities.py, tests/unit/benchmarks/test_semantic_roundtrip_capabilities.py, workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json
- Interfaces: SemanticRoundTripCapabilityInventory@1
- Conflict policy: Extend capability probes without substituting models or weakening identity binding; own smoke extensions and tests.
- Preconditions: EVAL-001 status taxonomy exists; Leanstral endpoint remains the configured one-slot service.
- Effects: Model-backed arms cannot enter scored execution on health-only checks.
- Evidence subset: live-model-smoke capability receipt
- Acceptance: Leanstral direct and SyMAI route capability records set `model_inference_performed: true` after a real construct-or-realize smoke using the same schema as matrix execution. Health-only probes alone mark the arm non-schedulable for scored matrix cells. Persist accept/reject reason on the smoke receipt. Unit tests cover forced failure of live smoke and identity mismatch.

## EVAL-003 Causal autoencoder guidance measurement path

- Status: completed
- Completion: auto
- Priority: P0
- Track: harness
- Depends on: EVAL-001
- Outputs: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-causal-guidance
- Parallel lane: eval-causal-guidance
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Interfaces: CausalGuidanceQualification@1
- Conflict policy: Own causal guidance qualification and tests; do not invent gold-dependent interventions; keep fail-closed forbidden inputs.
- Preconditions: Autoencoder state remains readable; current qualification status is unavailable_no_reviewed_causal_l1_adapter.
- Effects: Guided arms are either truly scored or explicitly excluded from the schedule.
- Evidence subset: causal-guidance qualification receipt
- Acceptance: Either (a) supply a reviewed causal L1 adapter contract (feature→field map, change receipt, disabled-guidance negative control, no gold/sample memory) and mark guided arms `scored_supported`, or (b) keep terminal unsupported but update the matrix planner so guided cells are not scheduled for semantic scoring and appear only as `not_measured`. Refresh the qualification JSON CID. Tests cover missing-contract fail-closed behavior and negative control zero-change.

## EVAL-004 Leanstral reliability and rejection taxonomy

- Status: completed
- Completion: auto
- Priority: P0
- Track: harness
- Depends on: EVAL-002
- Outputs: benchmarks/semantic_roundtrip/model_output_recovery.py, benchmarks/semantic_roundtrip/constructors/leanstral.py, benchmarks/semantic_roundtrip/realizers/leanstral.py, tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py, tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-leanstral-reliability
- Parallel lane: eval-leanstral-reliability
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/model_output_recovery.py, benchmarks/semantic_roundtrip/constructors/leanstral.py, benchmarks/semantic_roundtrip/realizers/leanstral.py, tests/unit/benchmarks/semantic_roundtrip/test_model_output_recovery.py, tests/unit/benchmarks/semantic_roundtrip/test_leanstral_adapters.py
- Interfaces: ModelOutputRecovery@1, LeanstralRoundTripAdapters@1
- Conflict policy: Improve recovery and adapters without silent route substitution or source recovery; keep promotion policy at most one retry unless a separate research policy is explicitly named.
- Preconditions: Live smoke from EVAL-002 can reach the model.
- Effects: retry_exhausted becomes diagnosable and reduced; research can use stricter intermediate schemas.
- Evidence subset: leanstral-reliability receipt
- Acceptance: Every model call records a typed rejection reason (blank, schema, polarity, empty_rules, timeout, other). Expose `accept_rate` and `retry_exhausted_rate` per arm separate from end-to-end loss. Provide an optional research recovery policy with preregistered retry budget greater than one without changing the promotion default. Add a single-rule research schema path usable by hybrid repair experiments. Tests cover rejection taxonomy and policy separation.

## EVAL-005 Selective repair activation harness

- Status: completed
- Completion: auto
- Priority: P0
- Track: harness
- Depends on: EVAL-001
- Outputs: benchmarks/semantic_roundtrip/selective_repair.py, tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py, benchmarks/semantic_roundtrip/constructors/typed_deontic.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-selective-repair
- Parallel lane: eval-selective-repair
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/selective_repair.py, tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py, benchmarks/semantic_roundtrip/constructors/typed_deontic.py
- Interfaces: SelectiveRepair@1
- Conflict policy: Own repair triggers and activation metrics; do not change gold fixtures; keep repair fail-closed and field-scoped.
- Preconditions: Current selective deterministic arm can succeed with zero model calls.
- Effects: Selective arms prove repair was attempted when triggers exist.
- Evidence subset: selective-repair-activation receipt
- Acceptance: Fixture pack forces missing temporal / low-confidence / contradictory slots and asserts repair triggers fire, model or structural repair is attempted, and only triggered fields change. Coordinate receipts report `repair_triggered`, `repair_applied`, and `model_calls`. A selective arm with zero triggers on the fixture pack fails validation. Typed-deontic can emit triggers from diagnostics without breaking the no-repair baseline arm.

## EVAL-006 Modal-spaCy polarity preflight and constructor-only scoring

- Status: completed
- Completion: auto
- Priority: P1
- Track: harness
- Depends on: EVAL-001
- Outputs: benchmarks/semantic_roundtrip/constructors/modal_spacy.py, benchmarks/semantic_roundtrip/stage_metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py, tests/unit/benchmarks/semantic_roundtrip/test_stage_metrics.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py tests/unit/benchmarks/semantic_roundtrip/test_stage_metrics.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-modal-spacy
- Parallel lane: eval-modal-spacy
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/constructors/modal_spacy.py, benchmarks/semantic_roundtrip/stage_metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py, tests/unit/benchmarks/semantic_roundtrip/test_stage_metrics.py
- Interfaces: ModalSpacyConstructor@1, StageMetrics@1
- Conflict policy: Own modal_spacy polarity fixes and stage metrics; do not alter gold IR; keep full-matrix gates for promotion.
- Preconditions: Modal-spaCy currently fails polarity on most pilot cases while still emitting IR.
- Effects: Constructor quality can be scored without requiring full round-trip eligibility.
- Evidence subset: modal-spacy-stage-metrics receipt
- Acceptance: Add polarity inversion unit fixtures that fail closed. Provide `constructor_only` stage metrics (forward loss, modality/conditions/exceptions/temporal survival) exportable from matrix records. Document that promotion still requires full gates. Improve modal_spacy polarity enough that the exception_with_window case remains eligible and at least one additional pilot case preserves polarity, or document residual inversions with case IDs.

## EVAL-007 Hybrid and stage-local evaluation modes

- Status: completed
- Completion: auto
- Priority: P1
- Track: harness
- Depends on: EVAL-001, EVAL-004, EVAL-005
- Outputs: benchmarks/semantic_roundtrip/replacement_matrix.py, benchmarks/semantic_roundtrip/hybrid_arms.py, tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py, tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-hybrid-modes
- Parallel lane: eval-hybrid-modes
- Resource class: cpu-medium
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/replacement_matrix.py, benchmarks/semantic_roundtrip/hybrid_arms.py, tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py, tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py
- Interfaces: HybridRoundTripArms@1
- Conflict policy: Add research evaluation modes without changing the frozen promotion arm set unless preregistered; own hybrid arm definitions and matrix hooks.
- Preconditions: Status taxonomy, selective activation, and Leanstral recovery taxonomy exist.
- Effects: Harness can measure det+optional-repair without requiring full arm replacement.
- Evidence subset: hybrid-eval-mode receipt
- Acceptance: Preregister at least: (1) constructor_only baseline vs candidates, (2) realizer_only on fixed L1, (3) hybrid `typed_deontic → optional selective/model repair → deterministic realizer` with fail-closed abstention. Report forward, cycle, and end-to-end separately. Paired bootstrap vs deterministic baseline required for hybrid success claims. Unit tests cover mode selection and fail-closed missing-preflight.

## EVAL-008 Hammer/cvc5/Lean as repair admission gates

- Status: completed
- Completion: auto
- Priority: P1
- Track: harness
- Depends on: EVAL-007
- Outputs: benchmarks/semantic_roundtrip/structural_admission.py, tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-structural-gates
- Parallel lane: eval-structural-gates
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/structural_admission.py, tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py
- Interfaces: StructuralAdmission@1
- Conflict policy: Use existing Hammer/cvc5/Lean capabilities as admit/reject only; never score proof success as semantic fidelity.
- Preconditions: Capability inventory marks hammer_cvc5 and lean available.
- Effects: Optional repairs can be rejected before affecting T1/L2 scores.
- Evidence subset: structural-admission receipt
- Acceptance: Hybrid repair path can invoke bounded Hammer/cvc5 and/or Lean checks; reject leaves prior L1 unchanged and records `validator_reject`. Metrics include reject rate and accepted-repair delta. Tests cover accept, reject, and timeout fail-closed behavior without treating proof pass as lower end-to-end loss by itself.

## EVAL-009 Research matrix re-run and improvement report

- Status: completed
- Completion: auto
- Priority: P1
- Track: harness
- Depends on: EVAL-002, EVAL-003, EVAL-004, EVAL-005, EVAL-006, EVAL-007, EVAL-008
- Outputs: docs/performance_snapshots/2026-07-27_semantic_roundtrip_eval_repair_matrix.json, docs/benchmarks/semantic_roundtrip_eval_repair_results.md, docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py -q
- Board namespace: semantic-roundtrip-eval-harness-v1
- Bundle: semantic-roundtrip/eval-rerun-report
- Parallel lane: eval-rerun-report
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 14400
- Predicted files: docs/performance_snapshots/2026-07-27_semantic_roundtrip_eval_repair_matrix.json, docs/benchmarks/semantic_roundtrip_eval_repair_results.md, docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md
- Interfaces: EvalRepairMatrixReport@1
- Conflict policy: Own only the research matrix receipt and markdown reports; do not rewrite the immutable 2026-07-27 replacement promotion report.
- Preconditions: Harness repairs EVAL-001 through EVAL-008 are complete enough to run a research matrix without health-only or unguided scheduled failures.
- Effects: Operators receive a fair comparison of optional methods against the deterministic plateau.
- Evidence subset: eval-repair-matrix receipt
- Acceptance: Produce a CID-bound research report that (1) excludes not_measured from semantic rankings, (2) reports accept_rate for model arms, (3) reports repair activation for selective arms, (4) ranks hybrid and constructor_only improvements vs typed_deontic deterministic baseline with paired bootstrap, and (5) writes an improvement plan naming which methods earned composition into the production path. Validation reuses matrix contract tests and checks the report schema fields for status taxonomy and baseline delta tables.
