# Legal IR Hammer Leanstral Agent TODO Board

This file is formatted for the `ipfs_accelerate_py` agent supervisor implementation daemon.

Parser contract:

- Task headers start with `## PORTAL-`.
- Required parsed fields are `Status`, `Completion`, `Priority`, `Track`, `Depends on`, `Outputs`, `Validation`, and `Acceptance`.
- Dependencies are comma-separated task IDs.
- Validation commands are semicolon-separated shell commands.
- JSON blocks are advisory metadata for implementation agents.

Objective: integrate a hammer-style theorem proving bridge and Leanstral guidance into the legal text compiler/decompiler, autoencoder, and Codex loop without treating unverified language-model output as trusted reward signal.

Operator contract:

- This board is the supervisor's dependency source of truth. A dependency must name another task in this file; task lifecycle values are limited to `todo`, `in_progress`, `blocked`, and `completed`.
- `Outputs` names the concrete implementation or documentation artifacts owned by a task. `Validation` is the executable, semicolon-delimited command set the supervisor must pass before merge. Do not infer completion from advisory JSON or from an artifact merely being present.
- The representation targets, PORTAL-LIR-HAMMER-019 through PORTAL-LIR-HAMMER-033, retain focused output and validation contracts; PORTAL-LIR-HAMMER-034 records their operator handoff. Runtime and proof-feedback targets PORTAL-LIR-HAMMER-035 through PORTAL-LIR-HAMMER-052 form the first performance wave, and PORTAL-LIR-HAMMER-053 is its rollout handoff. The evidence-driven follow-up in `docs/implementation/plans/HAMMER_LEANSTRAL_LEGAL_IR_NEXT_OPTIMIZATION_PLAN.md` is tracked by PORTAL-LIR-HAMMER-054 through PORTAL-LIR-HAMMER-100.
- A generated patch, learned export, or model draft is never promoted merely because its producer task completed. Runtime trust and rollout evidence remain mandatory.

Artifact and authority lanes:

| Lane | Task families | Operator classification |
| --- | --- | --- |
| Deterministic compiler/decompiler repairs | PORTAL-LIR-HAMMER-012/013, 019-025, 030/031 | Version-controlled implementation candidates. They become deployable only after their focused validation and fixed-canary rollout gates pass. |
| Trusted hammer/Leanstral guidance | PORTAL-LIR-HAMMER-001-011, 014-016, 022-026 | Structured facts accepted by deterministic validators and configured proof/reconstruction policy. Only these verified facts may reach the feature bus or bounded repair projection. |
| Autoencoder-learned representation exports | PORTAL-LIR-HAMMER-009/010, 026/027, 032/033 | Source-free, sample-memory-free stable feature summaries. Exports are inert until a supervised promotion report passes per-view fixed-canary and rollback checks. |
| Untrusted Leanstral drafts | PORTAL-LIR-HAMMER-006/007, 015, 024/025 | Proposals only. Raw drafts, free-form proof text, and rejected candidates are never proof, ground truth, compiler repairs, or direct training targets. |
| Runtime infrastructure | PORTAL-LIR-HAMMER-035-044, 048-050, 052 | Scheduling, caching, batching, telemetry, validation, and recovery machinery. These tasks may change throughput but may not weaken proof trust, allowed paths, holdout isolation, or rollout gates. |
| Verified proof-feedback supervision | PORTAL-LIR-HAMMER-045-047, 051 | Content-addressed labels and bounded learned updates derived from trusted receipts. Feedback remains version-bound and cannot directly mutate canonical IR. |
| Parallel production rollout | PORTAL-LIR-HAMMER-053 | Reversible smoke, hparam, canary, and production evidence. Passing implementation tests alone does not authorize production promotion. |
| Evidence-driven optimization | PORTAL-LIR-HAMMER-054-072 | Metric causality, formal-supervision efficacy, CUDA/runtime optimization, adaptive parallelism, and a second fail-closed rollout. |
| Evaluation integrity | PORTAL-LIR-HAMMER-073-084 | Leakage-resistant evaluation, semantic-equivalence metrics, uncertainty, fuzzing, hard negatives, multi-seed promotion, schema compatibility, poisoning defenses, external benchmarks, and drift rollback. |
| Compiler productization | PORTAL-LIR-HAMMER-085-100 | Source maps, symbol tables, citations, temporal authority, ambiguity, pass manager, backend conformance, reproducibility, incremental compilation, semantic diffs, proof-carrying outputs, diagnostics, APIs, interoperability, and final conformance. |

Expanded optimization target manifest:

| Target | Concrete output focus | Focused validation |
| --- | --- | --- |
| 019 canonical contracts | Contract registry and contract tests | `test_legal_ir_view_contracts.py` |
| 020 obligation coverage | Contract-derived obligations | `test_legal_ir_obligation_contract_coverage.py` |
| 021 contract telemetry | Per-view deterministic telemetry and daemon summary integration | `test_legal_ir_contract_telemetry.py` |
| 022 premise ranking | Contract/failure-aware deterministic selector | `test_legal_ir_premise_selection.py` |
| 023 translation receipts | Typed SMT/TPTP/Lean translation and reconstruction receipts | `test_legal_ir_hammer_translation.py` plus pipeline regression |
| 024 candidate sanitizer | Failure-branch prompts and strict rejection paths | `test_leanstral_failure_branch_candidates.py` plus schema regression |
| 025 bounded subgoals | Deterministic failed-obligation decomposition | `test_legal_ir_subgoal_decomposition.py` |
| 026 trusted feature bus | Bounded verified guidance ingestion | `test_modal_autoencoder_trusted_feature_bus.py` plus hammer guidance regression |
| 027 per-view metrics | Seven-family IR, learned, proof, reconstruction, and copy metrics | `test_legal_ir_view_family_metrics.py` plus objective regression |
| 028 adversarial guardrails | Source-copy fixtures and deterministic/learned rejection tests | Both `test_source_copy_reward_hack_*` suites |
| 029 repair clustering | Recurrence-aware bounded Codex TODOs | `test_hammer_failure_clustering_todos.py` plus projection regression |
| 030 compiler repairs | Clustered deterministic compiler lane fixes | Clustered and baseline verified-gap repair tests |
| 031 decompiler repairs | Deterministic round-trip preservation fixes | Clustered and baseline decompiler round-trip tests |
| 032 learned export promotion | Stable feature export and deterministic guidance promotion | Learned-guidance promotion plus per-view metric tests |
| 033 supervised rollout | Fail-closed smoke, hparam, and 24-hour promotion gates | Representation rollout plus baseline rollout-gate tests |

Next execution wave:

| Targets | Concrete output focus | Parallelization boundary |
| --- | --- | --- |
| 035-037 | Phase/resource telemetry, immutable evaluation reuse, and correct state-to-patch lag | Establish measurements and cache keys before changing worker counts |
| 038-044 | Global leases, snapshot/family workers, proof cache/routing, Leanstral batching, and child-process cleanup | Share one global process budget; count nested solver children |
| 045-047 | Trusted proof-feedback records, proof-aware heads, and guarded weight updates | Train asynchronously from verified receipts, never live prover calls |
| 048-050 | Incremental validation, failure rescue, and conflict-aware Codex scheduling | Validate concurrently; serialize overlapping writes and merges |
| 051-052 | Learned-rule distillation, pipeline benchmark, and adaptive tuning | Optimize held-out compiler quality and useful throughput together |
| 053 | Short smoke, one-hour hparam, eight-hour canary, and 24-hour production rollout | Fail closed and preserve rollback evidence at every stage |

Evidence-driven follow-up wave:

| Targets | Concrete output focus | Parallelization boundary |
| --- | --- | --- |
| 054-058 | Responsive learned/compiler metrics, promotion evidence, causal proof feedback, and per-family objectives | Establish causal quality signals before optimizing throughput |
| 059-061 | Hammer coverage, selective Leanstral routing, and end-to-end repair attribution | Leanstral proposes; deterministic checks and Hammer establish trust |
| 062-067 | CUDA projection optimization, asynchronous snapshots, shared artifacts, nonblocking persistence, and trustworthy GPU telemetry | One canonical trainer; parallel immutable consumers |
| 068-071 | Adaptive worker allocation, resource-aware hparam search, continuous Leanstral batching, and Codex/validation flow control | Global resource leases and downstream capacity bound every lane |
| 072 | Rebenchmark, smoke, hparam, eight-hour canary, and 24-hour promotion | Fail closed on non-responsive metrics or incomplete lineage |
| 073-084 | Evaluation integrity and external validity | Do not optimize learned or compiler metrics that can be explained by leakage, shallow similarity, unstable schemas, or canary overfitting |
| 085-100 | Compiler-grade IR infrastructure and final conformance | Make the compiler/decompiler inspectable, reproducible, incrementally runnable, standards-aware, and proof-carrying |

The manifest is an operator index. The full paths and commands in each task's `Outputs` and `Validation` fields are authoritative for the supervisor.

## PORTAL-LIR-HAMMER-001 Define hammer guidance artifact schema

- Status: completed
- Completion: 100
- Priority: P0
- Track: legal-ir-hammer
- Depends on:
- Outputs: ipfs_datasets_py/logic/integration/reasoning/hammer_guidance.py, tests/unit/logic/integration/test_hammer_guidance_artifact.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_hammer_guidance_artifact.py -q
- Acceptance: Adds a stable HammerGuidanceArtifact schema that serializes HammerResult, Leanstral candidate metadata, proof obligation IDs, trust status, selected premises, backend statuses, reconstruction status, metric deltas, and Codex projection hints without storing copied legal text as a training target.

```json
{
  "phase": "foundation",
  "scope": "schema",
  "guardrails": [
    "raw Leanstral text is guidance only",
    "trusted=true requires deterministic validation or proof reconstruction",
    "source spans may be referenced by hash/provenance ID but not copied into learned targets"
  ]
}
```

## PORTAL-LIR-HAMMER-002 Generate typed legal IR proof obligations

- Status: completed
- Completion: 100
- Priority: P0
- Track: legal-ir-hammer
- Depends on: PORTAL-LIR-HAMMER-001
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_obligations.py, tests/unit/logic/integration/test_legal_ir_obligations.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_obligations.py -q
- Acceptance: Adds deterministic obligation generation for modal well-formedness, deontic polarity, exception scope, temporal/event consistency, frame roles, KG edge typing, provenance preservation, and decompiler round-trip claims with stable obligation IDs.

```json
{
  "phase": "foundation",
  "scope": "proof_obligation_generation",
  "views": [
    "modal.frame_logic",
    "deontic.ir",
    "TDFOL.prover",
    "CEC.native",
    "knowledge_graphs.neo4j_compat",
    "external_provers.router",
    "modal.decompiler"
  ]
}
```

## PORTAL-LIR-HAMMER-003 Export premise library from deterministic compiler state

- Status: completed
- Completion: 100
- Priority: P0
- Track: legal-ir-hammer
- Depends on: PORTAL-LIR-HAMMER-001
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_premises.py, tests/unit/logic/integration/test_legal_ir_premises.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_premises.py -q
- Acceptance: Builds a premise registry adapter that exports reusable compiler facts, legal IR theorem templates, Leanstral theorem registry entries, bridge facts, and sample-local assumptions as HammerPremise records with deterministic names and metadata for premise selection.

```json
{
  "phase": "foundation",
  "scope": "premise_selection_inputs",
  "required_metadata": [
    "logic_family",
    "legal_ir_view",
    "formalism",
    "source_module",
    "provenance_hash"
  ]
}
```

## PORTAL-LIR-HAMMER-004 Connect obligations and premises to the hammer pipeline

- Status: completed
- Completion: 100
- Priority: P0
- Track: legal-ir-hammer
- Depends on: PORTAL-LIR-HAMMER-002, PORTAL-LIR-HAMMER-003
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py, tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py tests/unit/logic/integration/test_hammer.py -q
- Acceptance: Provides a LegalIRHammerRunner that converts generated obligations and premise registries into HammerGoal calls, runs parallel SMT/TPTP backends, reconstructs native proof scripts when available, and returns HammerGuidanceArtifact-compatible records.

```json
{
  "phase": "foundation",
  "scope": "hammer_execution",
  "failure_outputs": [
    "translation_failed",
    "no_backend_proof",
    "reconstruction_failed",
    "backend_unavailable"
  ]
}
```

## PORTAL-LIR-HAMMER-005 Add production backend availability and installer checks

- Status: completed
- Completion: 100
- Priority: P1
- Track: external-provers
- Depends on: PORTAL-LIR-HAMMER-004
- Outputs: ipfs_datasets_py/logic/integration/reasoning/hammer_backends.py, tests/unit/logic/integration/test_hammer_backend_availability.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_hammer_backend_availability.py -q
- Acceptance: Adds deterministic availability checks and lazy-install hooks for Z3, CVC5, Vampire, E, Lean, Coq, and Isabelle routes, while allowing tests and daemon runs to degrade to unavailable backend records instead of crashing.

```json
{
  "phase": "runtime_hardening",
  "scope": "solver_installation_and_health",
  "required_behavior": [
    "unavailable solvers are reported, not fatal",
    "timeouts are bounded per backend",
    "backend health is included in daemon summary"
  ]
}
```

## PORTAL-LIR-HAMMER-006 Extend Leanstral candidate schema for hammer use

- Status: completed
- Completion: 100
- Priority: P0
- Track: leanstral
- Depends on: PORTAL-LIR-HAMMER-001, PORTAL-LIR-HAMMER-002
- Outputs: ipfs_datasets_py/logic/modal/leanstral.py, tests/unit/logic/modal/test_leanstral_hammer_candidate_schema.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/modal/test_leanstral_hammer_candidate_schema.py -q
- Acceptance: Updates Leanstral prompts and validators so drafted_logic_candidates include obligation IDs, premise hints, target view, logic family, compiler surface, expected failure mode, confidence, and source-copy rejection metadata in strict JSON.

```json
{
  "phase": "leanstral_integration",
  "scope": "candidate_schema",
  "trust_boundary": "Leanstral drafts and ranks; it does not certify proof validity."
}
```

## PORTAL-LIR-HAMMER-007 Verify Leanstral candidates through hammer and deterministic validators

- Status: completed
- Completion: 100
- Priority: P0
- Track: leanstral
- Depends on: PORTAL-LIR-HAMMER-004, PORTAL-LIR-HAMMER-006
- Outputs: ipfs_datasets_py/logic/modal/leanstral_verifier.py, tests/unit/logic/modal/test_leanstral_hammer_verifier.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/modal/test_leanstral_hammer_verifier.py tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py -q
- Acceptance: Routes Leanstral candidates through syntax, provenance, KG, and hammer proof checks; marks candidates trusted only when deterministic checks pass; emits rejected reasons for copied source spans, invalid IR, failed proof, or failed reconstruction.

```json
{
  "phase": "leanstral_integration",
  "scope": "trusted_candidate_filter",
  "trusted_sources": [
    "deterministic_syntax_check",
    "knowledge_graph_shape_check",
    "hammer_backend_proof",
    "native_kernel_reconstruction"
  ]
}
```

## PORTAL-LIR-HAMMER-008 Persist verified hammer guidance and rule-gap reports

- Status: completed
- Completion: 100
- Priority: P0
- Track: leanstral
- Depends on: PORTAL-LIR-HAMMER-007
- Outputs: ipfs_datasets_py/logic/modal/leanstral_audit.py, scripts/ops/legal_ir/run_leanstral_audit_worker.py, tests/unit/logic/modal/test_leanstral_hammer_rule_gap_report.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/modal/test_leanstral_hammer_rule_gap_report.py -q
- Acceptance: Extends Leanstral audit outputs and rule-gap reports with verified hammer guidance artifacts, stable content hashes, stale-report protection, backend health, proof status, reconstruction status, and Codex projection fields.

```json
{
  "phase": "leanstral_integration",
  "scope": "artifact_persistence",
  "daemon_consumers": [
    "project_verified_leanstral_rule_gaps_into_queue",
    "project_verified_leanstral_guidance_artifacts_into_queue",
    "autoencoder.apply_leanstral_guidance"
  ]
}
```

## PORTAL-LIR-HAMMER-009 Teach the autoencoder to consume hammer-verified features

- Status: completed
- Completion: 100
- Priority: P0
- Track: autoencoder
- Depends on: PORTAL-LIR-HAMMER-008
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_hammer_guidance.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_hammer_guidance.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py -q
- Acceptance: Adds hammer-aware guidance ingestion that updates LegalIR view logits and feature heads from trusted proof obligation families, selected premise families, backend statuses, reconstruction failures, and verified target views while excluding raw generated proof text and full source spans from reconstruction targets.

```json
{
  "phase": "autoencoder_learning",
  "scope": "trusted_feature_learning",
  "new_feature_families": [
    "hammer:obligation-family",
    "hammer:selected-premise-view",
    "hammer:backend-status",
    "hammer:reconstruction-status",
    "hammer:failure-reason"
  ]
}
```

## PORTAL-LIR-HAMMER-010 Add hammer metrics and guarded objective terms

- Status: completed
- Completion: 100
- Priority: P0
- Track: metrics
- Depends on: PORTAL-LIR-HAMMER-004, PORTAL-LIR-HAMMER-008, PORTAL-LIR-HAMMER-009
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_hammer_metrics_objective.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_hammer_metrics_objective.py -q
- Acceptance: Adds explicit metrics for hammer proof success rate, reconstruction success rate, premise selection hit rate, per-view symbolic validity, source copy penalty, and proof failure ratio; projection/hparam scoring rejects candidates that improve cosine by degrading validity or source-copy guardrails.

```json
{
  "phase": "metrics",
  "scope": "objective_guardrails",
  "required_metric_groups": [
    "compiler_ir",
    "autoencoder",
    "symbolic_validity",
    "hammer",
    "source_copy_penalty",
    "round_trip"
  ]
}
```

## PORTAL-LIR-HAMMER-011 Project verified hammer failures into Codex TODOs

- Status: completed
- Completion: 100
- Priority: P0
- Track: codex-supervisor
- Depends on: PORTAL-LIR-HAMMER-008, PORTAL-LIR-HAMMER-010
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_hammer_codex_projection.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_hammer_codex_projection.py -q
- Acceptance: Converts repeated verified hammer failures into narrow Codex TODOs with scope, allowed paths, target metric, proof obligation IDs, expected validation command, and dedupe keys; one-off loss noise does not create unbounded tasks.

```json
{
  "phase": "codex_task_generation",
  "scope": "verified_failure_projection",
  "projection_rules": [
    "prefer recurring failures",
    "group by view family and compiler surface",
    "dedupe by obligation family and failure reason",
    "require bounded allowed_paths"
  ]
}
```

## PORTAL-LIR-HAMMER-012 Repair deterministic compiler lanes from verified gaps

- Status: completed
- Completion: 100
- Priority: P1
- Track: compiler
- Depends on: PORTAL-LIR-HAMMER-002, PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-011
- Outputs: ipfs_datasets_py/logic/modal, ipfs_datasets_py/logic/deontic, ipfs_datasets_py/logic/TDFOL, ipfs_datasets_py/logic/knowledge_graphs, tests/unit/logic/integration/test_legal_ir_verified_gap_repairs.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_verified_gap_repairs.py -q
- Acceptance: Implements deterministic compiler improvements for verified gaps in exception/prohibition guidance, temporal deadlines, frame role binding, KG actor/action/object/remedy edges, CEC lifecycle events, and external prover routing.

```json
{
  "phase": "compiler_repairs",
  "scope": "deterministic_ir_generation",
  "required_views": [
    "deontic.ir",
    "TDFOL.prover",
    "modal.frame_logic",
    "knowledge_graphs.neo4j_compat",
    "CEC.native",
    "external_provers.router"
  ]
}
```

## PORTAL-LIR-HAMMER-013 Add decompiler round-trip obligations and repairs

- Status: completed
- Completion: 100
- Priority: P1
- Track: decompiler
- Depends on: PORTAL-LIR-HAMMER-002, PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-012
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_obligations.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/logic/integration/test_decompiler_hammer_round_trip.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_decompiler_hammer_round_trip.py -q
- Acceptance: Adds obligations that check IR-to-text decompiler consistency without rewarding source copying, including provenance-preserving summaries, structural text reconstruction, modality retention, exception scope retention, and round-trip proof/failure artifacts.

```json
{
  "phase": "decompiler_repairs",
  "scope": "round_trip_validation",
  "guardrails": [
    "do not optimize by copying source spans into IR",
    "symbolic validity outranks text similarity",
    "decompiler repairs must preserve proof obligation IDs"
  ]
}
```

## PORTAL-LIR-HAMMER-014 Integrate hammer guidance into the daemon cycle

- Status: completed
- Completion: 100
- Priority: P0
- Track: daemon
- Depends on: PORTAL-LIR-HAMMER-007, PORTAL-LIR-HAMMER-008, PORTAL-LIR-HAMMER-009, PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-011
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_daemon_hammer_cycle.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_daemon_hammer_cycle.py -q
- Acceptance: Adds daemon cycle phases for obligation generation, Leanstral drafting, hammer verification, autoencoder guidance application, verified failure projection, summary metrics, cache reuse, and bounded skip behavior when Leanstral or solver backends are unavailable.

```json
{
  "phase": "daemon_integration",
  "scope": "cycle_orchestration",
  "required_summary_fields": [
    "hammer_proof_success_rate",
    "hammer_reconstruction_success_rate",
    "leanstral_hammer_candidate_count",
    "trusted_hammer_guidance_count",
    "hammer_projected_todo_count"
  ]
}
```

## PORTAL-LIR-HAMMER-015 Route Leanstral drafting through ipfs_accelerate_py batch and mesh inference

- Status: completed
- Completion: 100
- Priority: P1
- Track: leanstral-runtime
- Depends on: PORTAL-LIR-HAMMER-006
- Outputs: scripts/ops/legal_ir/run_leanstral_audit_worker.py, ipfs_datasets_py/logic/modal/leanstral_audit.py, tests/unit/logic/modal/test_leanstral_batch_mesh_inference.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/modal/test_leanstral_batch_mesh_inference.py -q
- Acceptance: Ensures Leanstral audit and drafting calls default to ipfs_accelerate_py llm_router, support batch inference and p2p mesh routing, preserve local fallback behavior, expose provider health, and avoid substituting non-Leanstral models unless explicitly allowed.

```json
{
  "phase": "runtime_acceleration",
  "scope": "leanstral_inference",
  "required_modes": [
    "direct_python_import",
    "llm_router_batch",
    "mcpplusplus_p2p_mesh",
    "local_llama_cpp_fallback"
  ]
}
```

## PORTAL-LIR-HAMMER-016 Build replay corpus for verified failures and repairs

- Status: completed
- Completion: 100
- Priority: P1
- Track: validation
- Depends on: PORTAL-LIR-HAMMER-007, PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-011, PORTAL-LIR-HAMMER-012, PORTAL-LIR-HAMMER-013
- Outputs: tests/fixtures/legal_ir/hammer_failure_replay.jsonl, tests/unit/logic/integration/test_hammer_failure_replay.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_hammer_failure_replay.py -q
- Acceptance: Adds a replayable fixture corpus of accepted and rejected Leanstral/hammer cases covering each Legal IR view family, each major failure reason, source-copy rejection, successful reconstruction, backend unavailable behavior, and Codex repair feedback.

```json
{
  "phase": "validation",
  "scope": "regression_corpus",
  "coverage_requirements": [
    "accepted_candidate",
    "source_copy_rejected",
    "syntax_rejected",
    "kg_rejected",
    "hammer_unproved",
    "reconstruction_failed",
    "backend_unavailable",
    "codex_repair_feedback"
  ]
}
```

## PORTAL-LIR-HAMMER-017 Add rollout gates for smoke, hparam, and 24-hour runs

- Status: completed
- Completion: 100
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-005, PORTAL-LIR-HAMMER-014, PORTAL-LIR-HAMMER-015, PORTAL-LIR-HAMMER-016
- Outputs: scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh, scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh, scripts/ops/logic/run_hparam_then_8h.sh, scripts/ops/logic/watch_hparam8h_pipeline.sh, tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py -q
- Acceptance: Adds guarded rollout commands for short hammer-enabled smoke, 1-hour hparam scan, and 24-hour optimizer loop; each gate verifies no metric regression beyond configured guardrails, no unbounded source-copy reward hacking, no stalled TODO generation, and no fatal backend availability failure.

```json
{
  "phase": "rollout",
  "scope": "operational_gating",
  "guarded_runs": [
    "short_smoke",
    "one_hour_hparam",
    "twenty_four_hour_optimizer"
  ]
}
```

## PORTAL-LIR-HAMMER-018 Document operator workflow and supervisor handoff

- Status: completed
- Completion: 100
- Priority: P2
- Track: docs
- Depends on: PORTAL-LIR-HAMMER-017
- Outputs: docs/LEGAL_IR_HAMMER_LEANSTRAL_OPERATOR_RUNBOOK.md, docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md
- Validation: PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=34, len(tasks); assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); print('parsed', len(tasks), 'tasks')"
- Acceptance: Adds an operator runbook explaining how to run the supervisor against this TODO board, how to read hammer/Leanstral metrics, how to distinguish trusted proof signal from Leanstral drafts, and how to start smoke, hparam, and 24-hour runs.

```json
{
  "phase": "handoff",
  "scope": "operator_docs",
  "example_supervisor_command": "PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon --once --todo-path docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md --state-dir workspace/hammer-leanstral-supervisor --state-prefix hammer_leanstral --task-prefix '## PORTAL-'"
}
```

## PORTAL-LIR-HAMMER-019 Define canonical multi-view LegalIR contracts

- Status: completed
- Completion: 100
- Priority: P0
- Track: legal-ir-contracts
- Depends on: PORTAL-LIR-HAMMER-001, PORTAL-LIR-HAMMER-018
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_view_contracts.py, tests/unit/logic/integration/test_legal_ir_view_contracts.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_view_contracts.py -q
- Acceptance: Adds a typed contract registry for deontic, frame_logic, TDFOL, CEC, knowledge_graphs, external_provers, and decompiler views with required fields, modality semantics, provenance requirements, allowed repair lanes, validation hooks, and stable contract IDs consumed by obligations, metrics, autoencoder features, and Codex TODO projection.

```json
{
  "phase": "contract_hardening",
  "scope": "canonical_ir_view_contracts",
  "required_views": [
    "deontic",
    "frame_logic",
    "tdfol",
    "cec",
    "knowledge_graphs",
    "external_provers",
    "decompiler"
  ],
  "guardrails": [
    "contracts are deterministic",
    "contracts store provenance IDs instead of source text",
    "contracts expose stable metric and obligation families"
  ]
}
```

## PORTAL-LIR-HAMMER-020 Expand proof obligations from canonical contracts

- Status: completed
- Completion: 0
- Priority: P0
- Track: proof-obligations
- Depends on: PORTAL-LIR-HAMMER-002, PORTAL-LIR-HAMMER-019
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_obligations.py, tests/unit/logic/integration/test_legal_ir_obligation_contract_coverage.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_obligation_contract_coverage.py -q
- Acceptance: Extends obligation generation so every canonical LegalIR view contract emits coverage obligations for required fields, cross-view consistency, exception precedence, prohibition polarity, temporal anchors, KG endpoint typing, CEC lifecycle transitions, external prover route preservation, and decompiler round-trip structure.

```json
{
  "phase": "contract_hardening",
  "scope": "obligation_coverage",
  "coverage_gates": [
    "each contract has at least one local obligation family",
    "each contract has at least one cross-view obligation family",
    "obligation IDs remain stable across runs"
  ]
}
```

## PORTAL-LIR-HAMMER-021 Emit deterministic compiler/decompiler contract telemetry

- Status: completed
- Completion: 0
- Priority: P1
- Track: compiler-telemetry
- Depends on: PORTAL-LIR-HAMMER-019, PORTAL-LIR-HAMMER-020
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_contract_telemetry.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/logic/integration/test_legal_ir_contract_telemetry.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_contract_telemetry.py -q
- Acceptance: Adds deterministic telemetry that records per-sample contract coverage, missing required fields, cross-view mismatches, decompiler preservation failures, and provenance-only source references in daemon summaries and hammer guidance artifacts.

```json
{
  "phase": "compiler_instrumentation",
  "scope": "contract_telemetry",
  "summary_fields": [
    "legal_ir_contract_coverage",
    "legal_ir_contract_failure_counts",
    "legal_ir_contract_view_family_gaps"
  ]
}
```

## PORTAL-LIR-HAMMER-022 Add premise selection ranking over contracts and failures

- Status: completed
- Completion: 0
- Priority: P0
- Track: premise-selection
- Depends on: PORTAL-LIR-HAMMER-003, PORTAL-LIR-HAMMER-019, PORTAL-LIR-HAMMER-021
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_premise_selection.py, tests/unit/logic/integration/test_legal_ir_premise_selection.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_premise_selection.py -q
- Acceptance: Adds deterministic premise ranking that scores compiler facts, theorem templates, sample-local assumptions, and verified Leanstral theorem registry entries by obligation family, target view, failure reason, citation/provenance hash, and contract fields while excluding copied source spans from the premise score.

```json
{
  "phase": "hammer_quality",
  "scope": "premise_selection",
  "ranking_features": [
    "obligation_family",
    "target_view",
    "contract_field_overlap",
    "verified_failure_reason",
    "provenance_hash"
  ]
}
```

## PORTAL-LIR-HAMMER-023 Add typed hammer translation and reconstruction receipts

- Status: completed
- Completion: 0
- Priority: P0
- Track: hammer-translation
- Depends on: PORTAL-LIR-HAMMER-004, PORTAL-LIR-HAMMER-019, PORTAL-LIR-HAMMER-022
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_translation.py, ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py, tests/unit/logic/integration/test_legal_ir_hammer_translation.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_hammer_translation.py tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py -q
- Acceptance: Adds typed translation records for SMT-LIB, TPTP, and Lean reconstruction surfaces, records monomorphization/type-encoding/lambda-elimination decisions where applicable, and persists reconstruction receipts that distinguish backend proof, native reconstruction, translation failure, and trust status.

```json
{
  "phase": "hammer_quality",
  "scope": "logic_translation_and_reconstruction",
  "trust_boundary": "backend proof is useful evidence; trusted=true requires deterministic validation or native reconstruction when configured"
}
```

## PORTAL-LIR-HAMMER-024 Add Leanstral failure-branch prompts and strict candidate sanitizer

- Status: completed
- Completion: 0
- Priority: P0
- Track: leanstral
- Depends on: PORTAL-LIR-HAMMER-006, PORTAL-LIR-HAMMER-020, PORTAL-LIR-HAMMER-023
- Outputs: ipfs_datasets_py/logic/modal/leanstral.py, ipfs_datasets_py/logic/modal/leanstral_verifier.py, tests/unit/logic/modal/test_leanstral_failure_branch_candidates.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/modal/test_leanstral_failure_branch_candidates.py tests/unit/logic/modal/test_leanstral_hammer_candidate_schema.py -q
- Acceptance: Adds prompt builders and validators that ask Leanstral to repair only failed obligation subtrees, emit strict JSON candidates with obligation IDs and premise hints, reject full-source copying, reject untyped freeform proof text, and preserve deterministic contract IDs.

```json
{
  "phase": "leanstral_integration",
  "scope": "failure_branch_candidate_generation",
  "required_rejections": [
    "source_copy",
    "missing_obligation_id",
    "unknown_contract_id",
    "untyped_logic",
    "freeform_proof_text"
  ]
}
```

## PORTAL-LIR-HAMMER-025 Split failed hammer goals into smaller Leanstral-guided subgoals

- Status: completed
- Completion: 0
- Priority: P1
- Track: leanstral
- Depends on: PORTAL-LIR-HAMMER-024
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_subgoals.py, ipfs_datasets_py/logic/modal/leanstral_audit.py, tests/unit/logic/integration/test_legal_ir_subgoal_decomposition.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_subgoal_decomposition.py -q
- Acceptance: Adds deterministic subgoal decomposition for failed hammer obligations so overly broad exception, temporal, KG, CEC, or decompiler failures are split into bounded subproblems before Leanstral drafting and Codex TODO projection.

```json
{
  "phase": "leanstral_integration",
  "scope": "failure_decomposition",
  "boundedness": [
    "subgoal_count capped per obligation",
    "each subgoal has one primary contract",
    "each subgoal has one validation command"
  ]
}
```

## PORTAL-LIR-HAMMER-026 Add trusted hammer/Leanstral feature bus for the autoencoder

- Status: completed
- Completion: 0
- Priority: P0
- Track: autoencoder
- Depends on: PORTAL-LIR-HAMMER-009, PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-021, PORTAL-LIR-HAMMER-024
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_trusted_feature_bus.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_trusted_feature_bus.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_hammer_guidance.py -q
- Acceptance: Adds a feature bus that converts trusted hammer/Leanstral guidance into bounded autoencoder features for contract IDs, obligation families, premise families, backend statuses, reconstruction outcomes, and per-view repair labels while excluding raw Leanstral text and full source spans from learned targets.

```json
{
  "phase": "autoencoder_learning",
  "scope": "trusted_feature_bus",
  "feature_families": [
    "contract_id",
    "obligation_family",
    "premise_family",
    "backend_status",
    "reconstruction_status",
    "repair_lane"
  ]
}
```

## PORTAL-LIR-HAMMER-027 Split validation metrics by LegalIR view family

- Status: completed
- Completion: 0
- Priority: P0
- Track: metrics
- Depends on: PORTAL-LIR-HAMMER-010, PORTAL-LIR-HAMMER-016, PORTAL-LIR-HAMMER-019, PORTAL-LIR-HAMMER-026
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_view_family_metrics.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_view_family_metrics.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_metrics_objective.py -q
- Acceptance: Reports and scores IR cross entropy, IR cosine, autoencoder cross entropy, autoencoder cosine, symbolic validity, hammer proof success, reconstruction success, and source-copy penalty separately for deontic, frame_logic, TDFOL, KG, CEC, external_provers, and decompiler view families.

```json
{
  "phase": "metrics",
  "scope": "per_view_family_scoring",
  "required_metric_groups": [
    "cross_entropy",
    "cosine",
    "symbolic_validity",
    "hammer",
    "reconstruction",
    "source_copy_penalty"
  ]
}
```

## PORTAL-LIR-HAMMER-028 Add adversarial source-copy reward-hacking fixtures

- Status: completed
- Completion: 0
- Priority: P0
- Track: validation
- Depends on: PORTAL-LIR-HAMMER-013, PORTAL-LIR-HAMMER-016, PORTAL-LIR-HAMMER-027
- Outputs: tests/fixtures/legal_ir/source_copy_reward_hack_replay.jsonl, tests/unit/logic/integration/test_source_copy_reward_hack_guardrails.py, tests/unit/optimizers/logic_theorem_optimizer/test_source_copy_reward_hack_metrics.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_source_copy_reward_hack_guardrails.py tests/unit/optimizers/logic_theorem_optimizer/test_source_copy_reward_hack_metrics.py -q
- Acceptance: Adds replay fixtures where copied legal text artificially improves text similarity but fails symbolic/decompiler obligations, and verifies that hparam scoring, rollout gates, and autoencoder objective reject those candidates even when cosine improves.

```json
{
  "phase": "validation",
  "scope": "reward_hacking_guardrails",
  "must_fail_when": [
    "raw_source_span_is_used_as_ir",
    "cosine_improves_but_symbolic_validity_regresses",
    "decompiler_output_copies_source_without_structure"
  ]
}
```

## PORTAL-LIR-HAMMER-029 Cluster recurring verified failures into bounded Codex TODOs

- Status: completed
- Completion: 0
- Priority: P0
- Track: codex-supervisor
- Depends on: PORTAL-LIR-HAMMER-011, PORTAL-LIR-HAMMER-025, PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-028
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_hammer_failure_clustering_todos.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_hammer_failure_clustering_todos.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_codex_projection.py -q
- Acceptance: Adds recurrence-aware clustering so Codex TODOs are created only for repeated verified failures or high-impact replay failures, grouped by contract ID, obligation family, target view, failure reason, and allowed path, with caps per scope and validation commands on every TODO.

```json
{
  "phase": "codex_task_generation",
  "scope": "recurring_failure_clustering",
  "dedupe_keys": [
    "contract_id",
    "obligation_family",
    "target_view",
    "failure_reason",
    "allowed_paths"
  ]
}
```

## PORTAL-LIR-HAMMER-030 Repair deterministic compiler lanes from clustered contract gaps

- Status: completed
- Completion: 0
- Priority: P0
- Track: compiler
- Depends on: PORTAL-LIR-HAMMER-012, PORTAL-LIR-HAMMER-020, PORTAL-LIR-HAMMER-029
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_verified_gap_repairs.py, ipfs_datasets_py/logic/modal, ipfs_datasets_py/logic/deontic, ipfs_datasets_py/logic/TDFOL, ipfs_datasets_py/logic/knowledge_graphs, tests/unit/logic/integration/test_clustered_legal_ir_compiler_repairs.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_clustered_legal_ir_compiler_repairs.py tests/unit/logic/integration/test_legal_ir_verified_gap_repairs.py -q
- Acceptance: Implements deterministic compiler repairs generated from clustered verified gaps, prioritizing exception precedence, prohibition polarity, temporal deadline anchors, frame role binding, KG actor/action/object/remedy edges, CEC lifecycle events, and external prover route selection.

```json
{
  "phase": "compiler_repairs",
  "scope": "clustered_verified_gaps",
  "promotion_rule": "repairs must improve or preserve fixed-canary per-view metrics and symbolic validity"
}
```

## PORTAL-LIR-HAMMER-031 Repair deterministic decompiler round-trip preservation

- Status: completed
- Completion: 0
- Priority: P0
- Track: decompiler
- Depends on: PORTAL-LIR-HAMMER-013, PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-030
- Outputs: ipfs_datasets_py/logic/modal, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/logic/integration/test_clustered_legal_ir_decompiler_repairs.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_clustered_legal_ir_decompiler_repairs.py tests/unit/logic/integration/test_decompiler_hammer_round_trip.py -q
- Acceptance: Implements decompiler repairs that preserve modality, actor/action/object roles, exception scope, temporal anchors, citation provenance, and structural summaries while keeping copied source-span text out of IR and learned targets.

```json
{
  "phase": "decompiler_repairs",
  "scope": "round_trip_preservation",
  "required_preservation": [
    "modality",
    "roles",
    "exceptions",
    "temporal_anchors",
    "provenance"
  ]
}
```

## PORTAL-LIR-HAMMER-032 Promote learned autoencoder representations into deterministic IR guidance

- Status: completed
- Completion: 0
- Priority: P0
- Track: representation-transfer
- Depends on: PORTAL-LIR-HAMMER-026, PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-030, PORTAL-LIR-HAMMER-031
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, ipfs_datasets_py/logic/integration/reasoning/legal_ir_learned_guidance.py, tests/unit/logic/integration/test_legal_ir_learned_guidance_promotion.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_learned_guidance_promotion.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_view_family_metrics.py -q
- Acceptance: Adds a deterministic export path that converts stable learned autoencoder features into compiler/decompiler guidance records with contract IDs, view-family weights, repair-lane suggestions, confidence, canary metric evidence, and rollback metadata; promotion is blocked if source-copy or symbolic-validity guardrails regress.

```json
{
  "phase": "representation_transfer",
  "scope": "learned_to_deterministic_ir",
  "guardrails": [
    "only stable feature-level summaries are exported",
    "sample-memory features are excluded",
    "promotion requires fixed-canary evidence"
  ]
}
```

## PORTAL-LIR-HAMMER-033 Add supervised rollout gate for representation promotion

- Status: completed
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-017, PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-032
- Outputs: scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh, scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_representation_rollout_gate.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_representation_rollout_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py -q
- Acceptance: Extends rollout gates so smoke, hparam, and 24-hour runs fail if learned representation promotion regresses fixed-canary per-view IR metrics, symbolic validity, hammer proof rate, reconstruction rate, source-copy penalty, or TODO generation productivity.

```json
{
  "phase": "rollout",
  "scope": "promotion_gating",
  "gated_artifacts": [
    "learned_guidance_exports",
    "compiler_repairs",
    "decompiler_repairs",
    "codex_projection_queues"
  ]
}
```

## PORTAL-LIR-HAMMER-034 Refresh operator workflow for the expanded hammer/Leanstral plan

- Status: completed
- Completion: 0
- Priority: P1
- Track: docs
- Depends on: PORTAL-LIR-HAMMER-033
- Outputs: docs/LEGAL_IR_HAMMER_LEANSTRAL_OPERATOR_RUNBOOK.md, docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md
- Validation: PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=34, len(tasks); assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); assert not [task for task in tasks if task.status not in {'todo','completed','in_progress','blocked'}]; print('parsed', len(tasks), 'tasks')"
- Acceptance: Updates the runbook and taskboard so the supervisor has no dependency gaps, every new optimization target has concrete outputs and validation commands, and operators can distinguish deterministic compiler repairs, trusted hammer/Leanstral guidance, autoencoder-learned representation exports, and untrusted Leanstral drafts.

```json
{
  "phase": "handoff",
  "scope": "expanded_supervisor_taskboard",
  "operator_checks": [
    "parse taskboard",
    "run smoke gate",
    "inspect per-view metrics",
    "promote only trusted representation exports"
  ]
}
```

## PORTAL-LIR-HAMMER-035 Add end-to-end phase and resource telemetry

- Status: completed
- Completion: 0
- Priority: P0
- Track: runtime-observability
- Depends on: PORTAL-LIR-HAMMER-034
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_runtime_phase_telemetry.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_runtime_phase_telemetry.py -q
- Acceptance: Adds versioned per-cycle and per-sample spans for sampling, compilation, decoding, embeddings, projection training, each LegalIR view, bridge evaluation, premise selection, solver execution, Lean reconstruction, Leanstral queue and inference, disagreement export, Codex queue wait, validation, merge, cache lookup, and state persistence; records CPU, memory, swap, GPU utilization, child-process count, queue depth, throughput, and cache hit rates without placing raw legal text in telemetry.

```json
{"phase":"runtime_foundation","scope":"phase_resource_telemetry","baseline_cycle_seconds":737.526,"target_cycle_seconds":400.0}
```

## PORTAL-LIR-HAMMER-036 Reuse immutable compiler and metric artifacts

- Status: completed
- Completion: 0
- Priority: P0
- Track: runtime-caching
- Depends on: PORTAL-LIR-HAMMER-035
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_evaluation_cache.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_evaluation_cache.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_evaluation_cache.py -q
- Acceptance: Compiles and embeds each immutable sample once per compiler commit, autoencoder state, metric schema, and configuration digest, then reuses the typed artifact across baseline, guided, train, validation, and per-view scoring; concurrent callers coalesce on one computation, corrupt or stale entries fail closed, and summaries report avoided recompilations and saved wall time.

```json
{"phase":"runtime_foundation","scope":"shared_evaluation_artifacts","required_key_parts":["sample_hash","compiler_commit","state_hash","metric_schema","config_hash"]}
```

## PORTAL-LIR-HAMMER-037 Correct state-to-compiler-patch lag accounting

- Status: completed
- Completion: 0
- Priority: P0
- Track: runtime-observability
- Depends on: PORTAL-LIR-HAMMER-035
- Outputs: ipfs_datasets_py/logic/modal/introspection_metrics.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_reporting.py, tests/unit/optimizers/logic_theorem_optimizer/test_state_to_patch_lag.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_state_to_patch_lag.py -q
- Acceptance: Replaces subtraction of incompatible counters with explicit state snapshot to audit, TODO, claimed worktree, validated patch, merged commit, and observed-next-cycle timestamps and version IDs; reports wall-clock, cycle, and queue-stage lag percentiles and marks incomplete paths as censored rather than fabricating a numeric lag.

```json
{"phase":"runtime_foundation","scope":"state_to_patch_lag","required_units":["seconds","cycles","snapshot_versions"]}
```

## PORTAL-LIR-HAMMER-038 Add one global nested-process resource scheduler

- Status: completed
- Completion: 0
- Priority: P0
- Track: runtime-scheduling
- Depends on: PORTAL-LIR-HAMMER-035
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py, ipfs_datasets_py/logic/hammers/portfolio.py, tests/unit/optimizers/logic_theorem_optimizer/test_global_resource_scheduler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_global_resource_scheduler.py tests/unit_tests/logic/hammers/test_portfolio.py -q
- Acceptance: Adds a process-safe global CPU and memory lease scheduler shared by Hammer requests, nested ATP/SMT portfolios, Lean reconstruction, validation, and Codex workers; enforces configurable per-lane reservations, counts child solver processes against the parent lease, prevents nested oversubscription, supports cancellation and lease recovery, and exposes saturation and wait-time telemetry.

```json
{"phase":"parallel_runtime","scope":"global_resource_scheduler","dgx_spark_initial_slots":{"hammer_lean":8,"codex":4,"validation":4,"orchestration":2,"reserve":2}}
```

## PORTAL-LIR-HAMMER-039 Decouple training from snapshot evaluation

- Status: completed
- Completion: 0
- Priority: P0
- Track: autoencoder-runtime
- Depends on: PORTAL-LIR-HAMMER-036, PORTAL-LIR-HAMMER-038
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/snapshot_evaluator.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_snapshot_evaluator.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_snapshot_evaluator.py -q
- Acceptance: Lets the single CUDA trainer publish immutable state snapshots to a bounded evaluation queue while continuing training; evaluator results are accepted only for matching state, compiler, holdout, and schema versions, promotion occurs only at snapshot boundaries, queue coalescing drops superseded unevaluated snapshots explicitly, and backpressure pauses training before evidence becomes stale.

```json
{"phase":"parallel_runtime","scope":"asynchronous_snapshot_evaluation","trainer_count":1,"required_guards":["bounded_queue","version_match","promotion_boundary","backpressure"]}
```

## PORTAL-LIR-HAMMER-040 Shard LegalIR evaluation by semantic family

- Status: completed
- Completion: 0
- Priority: P0
- Track: validation-runtime
- Depends on: PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-036, PORTAL-LIR-HAMMER-038
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_family_evaluator.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_family_evaluator.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_family_evaluator.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_view_family_metrics.py -q
- Acceptance: Runs deontic, frame_logic, TDFOL, knowledge_graphs, CEC, external_provers, decompiler, temporal, and provenance evaluation shards independently over shared immutable artifacts, aggregates only complete matching snapshots, preserves per-family failures instead of hiding them in a macro score, and retries only failed shards within a bounded budget.

```json
{"phase":"parallel_runtime","scope":"family_sharded_evaluation","required_families":["deontic","frame_logic","tdfol","knowledge_graphs","cec","external_provers","decompiler","temporal","provenance"]}
```

## PORTAL-LIR-HAMMER-041 Add single-flight persistent proof-obligation caching

- Status: completed
- Completion: 0
- Priority: P0
- Track: proof-runtime
- Depends on: PORTAL-LIR-HAMMER-023, PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-038
- Outputs: ipfs_datasets_py/logic/hammers/proof_cache.py, ipfs_datasets_py/logic/modal/leanstral_verifier.py, tests/unit_tests/logic/hammers/test_proof_cache.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit_tests/logic/hammers/test_proof_cache.py tests/unit_tests/logic/hammers/test_receipts.py tests/unit_tests/logic/modal/test_leanstral_verifier.py -q
- Acceptance: Caches trusted and explicitly non-trusted proof outcomes by canonical obligation, selected premise digests, translation version, solver and Lean toolchain identities, theorem registry, policy, and resource budget; coalesces concurrent identical requests, never promotes unverified ATP output as proof, invalidates stale toolchains, and records cache provenance in reconstruction receipts.

```json
{"phase":"parallel_runtime","scope":"proof_single_flight_cache","trust_boundary":"only kernel-accepted or deterministic trusted outcomes may satisfy a trusted cache lookup"}
```

## PORTAL-LIR-HAMMER-042 Add staged cheap-first proof routing and budgets

- Status: completed
- Completion: 0
- Priority: P0
- Track: proof-runtime
- Depends on: PORTAL-LIR-HAMMER-022, PORTAL-LIR-HAMMER-038, PORTAL-LIR-HAMMER-041
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_router.py, ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer.py, tests/unit/logic/integration/test_legal_ir_proof_router.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_proof_router.py tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py -q
- Acceptance: Routes obligations through deterministic syntax, graph and contract checks, native TDFOL or CEC, bounded SMT/ATP portfolios, and native Lean reconstruction in increasing cost order; stops when policy obtains the required trust level, distinguishes unsupported translation from theorem failure, allocates per-stage and total deadlines, and records skipped routes and cancellation reasons.

```json
{"phase":"parallel_runtime","scope":"staged_proof_routing","route_order":["deterministic","native_logic","smt_atp","lean_reconstruction"]}
```

## PORTAL-LIR-HAMMER-043 Add continuously batched Leanstral audit inference

- Status: completed
- Completion: 0
- Priority: P0
- Track: leanstral-runtime
- Depends on: PORTAL-LIR-HAMMER-015, PORTAL-LIR-HAMMER-025, PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-038
- Outputs: ipfs_datasets_py/logic/modal/leanstral_audit_worker.py, scripts/ops/legal_ir/run_leanstral_audit_worker.py, tests/unit_tests/logic/modal/test_leanstral_batch_scheduler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit_tests/logic/modal/test_leanstral_batch_scheduler.py tests/unit/logic/modal/test_leanstral_batch_mesh_inference.py -q
- Acceptance: Groups audit and failure-branch prompts by model, theorem template, logic family, token budget, and deadline into continuously formed bounded batches; supports mesh and direct-local providers, fair scheduling across families, cache-first lookup, per-item retries and schema repair, cancellation, and batch telemetry while preserving request IDs and deterministic output association.

```json
{"phase":"parallel_runtime","scope":"leanstral_continuous_batching","initial_batch_range":[4,8],"uncached_latency_baseline_seconds":46.103}
```

## PORTAL-LIR-HAMMER-044 Make Lean and solver process cleanup supervisor-owned

- Status: completed
- Completion: 0
- Priority: P0
- Track: process-reliability
- Depends on: PORTAL-LIR-HAMMER-038, PORTAL-LIR-HAMMER-042
- Outputs: ipfs_datasets_py/logic/hammers/process_lifecycle.py, ipfs_datasets_py/logic/modal/lean_runtime.py, tests/unit_tests/logic/hammers/test_process_lifecycle.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit_tests/logic/hammers/test_process_lifecycle.py tests/unit_tests/logic/hammers/test_fallbacks.py -q
- Acceptance: Starts every Lean, Lake, ATP, SMT, and translator process in a supervisor-owned process group with heartbeat, wall-clock and resource deadline, graceful cancellation, forced cleanup, and lease release; detects and recovers stale Elan locks and temporary work directories without killing unrelated toolchain users, and proves interrupted tests leave no managed child processes.

```json
{"phase":"reliability","scope":"proof_process_lifecycle","required_recovery":["orphan_process","stale_lock","timeout","supervisor_restart","partial_tempdir"]}
```

## PORTAL-LIR-HAMMER-045 Persist versioned proof-feedback training records

- Status: completed
- Completion: 0
- Priority: P0
- Track: proof-feedback
- Depends on: PORTAL-LIR-HAMMER-016, PORTAL-LIR-HAMMER-026, PORTAL-LIR-HAMMER-041, PORTAL-LIR-HAMMER-042
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_feedback.py, tests/unit/logic/integration/test_legal_ir_proof_feedback.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_proof_feedback.py -q
- Acceptance: Defines source-free, content-addressed training records for obligation type, semantic family and slots, selected premise families, route availability, backend outcome, kernel reconstruction, counterexample, minimal failing contract, repair label, and trust status; records retain evidence and receipt IDs, exclude raw legal text and unverified Leanstral assertions, and support deterministic replay and train/holdout partitioning.

```json
{"phase":"proof_supervision","scope":"verified_training_records","positive_label":"kernel_or_deterministic_trusted","negative_labels":["verified_counterexample","contract_failure","reconstruction_failure","unsupported_translation"]}
```

## PORTAL-LIR-HAMMER-046 Add proof-aware auxiliary autoencoder heads

- Status: completed
- Completion: 0
- Priority: P0
- Track: autoencoder-architecture
- Depends on: PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-045
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_proof_heads.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_proof_heads.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_trusted_feature_bus.py -q
- Acceptance: Adds bounded auxiliary heads for obligation family, semantic slots, premise family, proof-route availability, trusted outcome, reconstruction success, and minimal failing contract; trains them only from version-matched trusted feedback, reports loss and calibration by LegalIR family, prevents proof labels from overriding compiler CE, cosine, structural, provenance, and anti-copy objectives, and serializes the architecture version compatibly.

```json
{"phase":"proof_supervision","scope":"proof_aware_autoencoder_heads","required_reporting":["per_family_loss","calibration","coverage","abstention"]}
```

## PORTAL-LIR-HAMMER-047 Enable guarded trusted feedback weight updates

- Status: completed
- Completion: 0
- Priority: P0
- Track: representation-transfer
- Depends on: PORTAL-LIR-HAMMER-032, PORTAL-LIR-HAMMER-045, PORTAL-LIR-HAMMER-046
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_learned_guidance.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/trusted_feedback_trainer.py, tests/unit/logic/integration/test_trusted_feedback_weight_updates.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_trusted_feedback_weight_updates.py tests/unit/logic/integration/test_legal_ir_learned_guidance_promotion.py -q
- Acceptance: Changes accepted Hammer and verifier-confirmed Leanstral guidance from inert metadata into bounded sample-aware autoencoder updates when trust, version, holdout isolation, deduplication, and source-copy guards pass; emits explicit applied, duplicate, stale, untrusted, missing-sample, and guardrail-blocked counters and requires an ablation showing held-out benefit before enabling production weight writes.

```json
{"phase":"proof_supervision","scope":"trusted_feedback_training","current_gap":"verified compiler targets report write_to_autoencoder_weights=false"}
```

## PORTAL-LIR-HAMMER-048 Add changed-scope incremental candidate validation

- Status: completed
- Completion: 0
- Priority: P0
- Track: validation-runtime
- Depends on: PORTAL-LIR-HAMMER-012, PORTAL-LIR-HAMMER-040, PORTAL-LIR-HAMMER-045
- Outputs: ipfs_datasets_py/logic/modal/leanstral_validation.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/incremental_validation.py, tests/unit/optimizers/logic_theorem_optimizer/test_incremental_validation.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_incremental_validation.py tests/unit_tests/logic/modal/test_leanstral_validation.py -q
- Acceptance: Maps changed files and typed AST scopes to focused tests, LegalIR families, replay samples, mutation cases, and proof obligations; runs independent checks concurrently, reuses immutable baseline evidence, retries only transient failures, and still requires the complete frozen canary and promotion proof set at merge or rollout boundaries.

```json
{"phase":"codex_throughput","scope":"incremental_validation","hard_rule":"incremental checks may accelerate candidate feedback but may not replace promotion gates"}
```

## PORTAL-LIR-HAMMER-049 Classify and rescue program-synthesis failures

- Status: completed
- Completion: 0
- Priority: P0
- Track: codex-reliability
- Depends on: PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-037, PORTAL-LIR-HAMMER-048
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/program_synthesis_failures.py, tests/unit/optimizers/logic_theorem_optimizer/test_program_synthesis_failure_recovery.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_program_synthesis_failure_recovery.py -q
- Acceptance: Classifies transport, provider timeout, malformed response, empty patch, apply conflict, stale base, scope violation, deterministic test failure, metric regression, resource exhaustion, and supervisor interruption; applies bounded category-specific retries, rebases or rescues recoverable worktrees, preserves failed evidence, prevents poison-task loops, and reports transient and terminal failure rates by scope.

```json
{"phase":"codex_throughput","scope":"failure_taxonomy_and_rescue","transient_failure_rate_baseline":0.4526,"target_rate":0.10}
```

## PORTAL-LIR-HAMMER-050 Add conflict-aware Codex scope scheduling and merge serialization

- Status: completed
- Completion: 0
- Priority: P1
- Track: codex-runtime
- Depends on: PORTAL-LIR-HAMMER-029, PORTAL-LIR-HAMMER-038, PORTAL-LIR-HAMMER-048, PORTAL-LIR-HAMMER-049
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/codex_scope_scheduler.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_codex_scope_scheduler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_codex_scope_scheduler.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_failure_clustering_todos.py -q
- Acceptance: Schedules up to four initial Codex workers across disjoint compiler_parser, compiler_registry, ir_decompiler, deontic, frame_logic, TDFOL, KG, CEC, and external_prover ownership scopes; bundles correlated evidence for one scope, predicts write-set conflicts, runs isolated validation concurrently, serializes overlapping merges, and adaptively reduces workers when validation, apply conflicts, memory pressure, or transient failures rise.

```json
{"phase":"codex_throughput","scope":"conflict_aware_parallel_codex","initial_total_workers":4,"target_accepted_patch_rate":0.60}
```

## PORTAL-LIR-HAMMER-051 Distill stable learned representations into deterministic rule candidates

- Status: completed
- Completion: 0
- Priority: P0
- Track: representation-transfer
- Depends on: PORTAL-LIR-HAMMER-047, PORTAL-LIR-HAMMER-048
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_rule_distillation.py, tests/unit/logic/integration/test_legal_ir_rule_distillation.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_rule_distillation.py tests/unit/logic/integration/test_legal_ir_learned_guidance_promotion.py -q
- Acceptance: Converts stable family, semantic-slot, proof-head, and LegalIR-view patterns into bounded deterministic compiler or decompiler rule candidates with support, confidence, counterfactuals, mutation evidence, owned paths, and rollback metadata; rejects sample-memory and source-copy features and emits Codex TODOs only when per-family attribution predicts a held-out compiler improvement.

```json
{"phase":"representation_transfer","scope":"learned_to_deterministic_rule_distillation","quality_gap":{"learned_ir_view_cosine":0.937689005,"compiler_ir_cosine":0.238778667}}
```

## PORTAL-LIR-HAMMER-052 Benchmark and autotune the complete parallel pipeline

- Status: completed
- Completion: 0
- Priority: P1
- Track: performance-evaluation
- Depends on: PORTAL-LIR-HAMMER-039, PORTAL-LIR-HAMMER-040, PORTAL-LIR-HAMMER-042, PORTAL-LIR-HAMMER-043, PORTAL-LIR-HAMMER-044, PORTAL-LIR-HAMMER-047, PORTAL-LIR-HAMMER-050, PORTAL-LIR-HAMMER-051
- Outputs: benchmarks/bench_legal_ir_optimizer_pipeline.py, scripts/ops/legal_ir/tune_hammer_leanstral_parallelism.py, tests/unit/optimizers/logic_theorem_optimizer/test_parallelism_autotuner.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_parallelism_autotuner.py -q; /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python benchmarks/bench_legal_ir_optimizer_pipeline.py --dry-run
- Acceptance: Benchmarks cold and warm cache throughput, p50/p95 phase latency, trainer duty cycle, proof and reconstruction throughput, Leanstral batch efficiency, CPU/GPU utilization, memory and swap, queue lag, Codex accepted patches per hour, and quality metrics; autotunes within global resource and trust bounds, compares against the fixed baseline, and emits a reproducible DGX Spark production profile rather than maximizing CPU utilization alone.

```json
{"phase":"performance_evaluation","scope":"pipeline_benchmark_and_autotuning","promotion_targets":{"cycle_seconds":400.0,"transient_failure_rate":0.10,"useful_cpu_utilization_min":0.75,"useful_cpu_utilization_max":0.90}}
```

## PORTAL-LIR-HAMMER-053 Add staged smoke, hparam, canary, and production rollout

- Status: completed
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-033, PORTAL-LIR-HAMMER-037, PORTAL-LIR-HAMMER-044, PORTAL-LIR-HAMMER-047, PORTAL-LIR-HAMMER-049, PORTAL-LIR-HAMMER-052
- Outputs: scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh, docs/LEGAL_IR_HAMMER_LEANSTRAL_OPERATOR_RUNBOOK.md, tests/unit/optimizers/logic_theorem_optimizer/test_parallel_pipeline_rollout_gate.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_parallel_pipeline_rollout_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_representation_rollout_gate.py -q; PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=53; assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); print('parsed', len(tasks), 'tasks')"
- Acceptance: Adds a strict sequence of short smoke, one-hour hyperparameter search, eight-hour canary, and twenty-four-hour production run; promotion requires no hard per-family semantic, provenance, anti-copy, Hammer proof, Lean reconstruction, process-lifecycle, or queue-lag regression, verifies trusted feedback reaches the autoencoder, compares accepted patches per wall-clock hour, stores rollback evidence, and fails closed on incomplete snapshots or orphaned managed processes.

```json
{"phase":"production_rollout","scope":"parallel_hammer_leanstral_autoencoder_codex","stages":["short_smoke","one_hour_hparam","eight_hour_canary","twenty_four_hour_production"]}
```

## PORTAL-LIR-HAMMER-054 Prove learned and deterministic IR metric responsiveness

- Status: completed
- Completion: 0
- Priority: P0
- Track: metric-causality
- Depends on: PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-053
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_metric_lineage.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_metric_responsiveness.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_metric_responsiveness.py tests/unit/optimizers/logic_theorem_optimizer/test_metrics_wiring.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_view_family_metrics.py -q
- Acceptance: Gives learned IR metrics and deterministic compiler IR metrics explicit sample, state, compiler, schema, target, and cache lineage; adds controlled perturbation tests proving that learned-head changes move only the learned path and deterministic compiler mutations move the compiler path; rejects unexplained invariant metrics across materially different states and prevents stale or cross-path cache reuse.

```json
{"phase":"quality_causality","scope":"ir_metric_lineage","observed_gap":{"trials":6,"compiler_ir_ce":2.572561757,"compiler_ir_cosine":0.052416487,"variation":0.0}}
```

## PORTAL-LIR-HAMMER-055 Wire trainable LegalIR heads to the evaluated objective

- Status: completed
- Completion: 0
- Priority: P0
- Track: autoencoder-architecture
- Depends on: PORTAL-LIR-HAMMER-046, PORTAL-LIR-HAMMER-047, PORTAL-LIR-HAMMER-054
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/trusted_feedback_trainer.py, tests/unit/optimizers/logic_theorem_optimizer/test_trainable_legal_ir_objective.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_trainable_legal_ir_objective.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_proof_heads.py tests/unit/logic/integration/test_trusted_feedback_weight_updates.py -q
- Acceptance: Connects learned compiler-facing LegalIR view, semantic-slot, proof, and decompiler heads to the exact learned metrics selected by hparam search; reports gradient and update norms by head and family; proves trusted examples produce finite nonzero updates while frozen, untrusted, stale, holdout, and source-copy features cannot update weights.

```json
{"phase":"quality_causality","scope":"trainable_legal_ir_objective","hard_guardrails":["no_sample_memory","no_source_copy_targets","holdout_isolation","finite_gradients"]}
```

## PORTAL-LIR-HAMMER-056 Make representation promotion evidence complete and mandatory

- Status: completed
- Completion: 0
- Priority: P0
- Track: representation-transfer
- Depends on: PORTAL-LIR-HAMMER-032, PORTAL-LIR-HAMMER-033, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-055
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_learned_guidance.py, scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, tests/unit/logic/integration/test_representation_promotion_evidence.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_representation_promotion_evidence.py tests/unit/logic/integration/test_legal_ir_learned_guidance_promotion.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_representation_rollout_gate.py -q
- Acceptance: Emits one success, rejection, or no-candidate promotion report for every eligible snapshot; binds it to learned export, compiler commit, fixed canary, proof receipts, causal evidence, source-copy checks, activation state, and rollback metadata; makes missing, stale, partial, or path-mismatched reports a specific fail-closed rollout result rather than an absent artifact.

```json
{"phase":"quality_causality","scope":"representation_promotion","observed_gap":"missing_representation_promotion_report"}
```

## PORTAL-LIR-HAMMER-057 Measure causal efficacy of trusted Hammer and Leanstral feedback

- Status: completed
- Completion: 0
- Priority: P0
- Track: proof-feedback
- Depends on: PORTAL-LIR-HAMMER-045, PORTAL-LIR-HAMMER-047, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-055
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_feedback_ablation.py, tests/unit/optimizers/logic_theorem_optimizer/test_proof_feedback_ablation.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_proof_feedback_ablation.py tests/unit/logic/integration/test_legal_ir_proof_feedback.py tests/unit/logic/integration/test_trusted_feedback_weight_updates.py -q
- Acceptance: Runs matched no-feedback, Hammer-only, verified-Leanstral-plus-Hammer, and shuffled-label ablations over frozen train/holdout partitions; attributes per-family learned IR, compiler IR, proof, reconstruction, and anti-copy deltas; enables production weight writes only when correctly labeled trusted feedback has a repeatable held-out benefit over controls.

```json
{"phase":"quality_causality","scope":"trusted_feedback_ablation","arms":["none","hammer","verified_leanstral_hammer","shuffled_control"]}
```

## PORTAL-LIR-HAMMER-058 Add constrained per-family objective balancing

- Status: todo
- Completion: 0
- Priority: P0
- Track: autoencoder-objective
- Depends on: PORTAL-LIR-HAMMER-027, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-057
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_objective_balancer.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_objective_balancer.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_objective_balancer.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_metrics_objective.py tests/unit/optimizers/logic_theorem_optimizer/test_source_copy_reward_hack_metrics.py -q
- Acceptance: Optimizes learned CE/cosine, deterministic compiler CE/cosine, proof validity, reconstruction, and anti-copy metrics independently for every LegalIR family; prevents macro averages from hiding a failed family; adapts soft weights only inside bounded ranges while structural, provenance, source-copy, Hammer trust, and frozen-canary constraints remain hard guardrails.

```json
{"phase":"quality_causality","scope":"per_family_constrained_objective","families":["deontic","frame_logic","tdfol","knowledge_graphs","cec","external_provers","decompiler","temporal","provenance"]}
```

## PORTAL-LIR-HAMMER-059 Close Hammer obligation coverage and minimize counterexamples

- Status: todo
- Completion: 0
- Priority: P0
- Track: formal-verification
- Depends on: PORTAL-LIR-HAMMER-020, PORTAL-LIR-HAMMER-023, PORTAL-LIR-HAMMER-028, PORTAL-LIR-HAMMER-058
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_hammer_coverage.py, tests/unit/logic/integration/test_legal_ir_hammer_coverage.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_hammer_coverage.py tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py tests/unit/logic/integration/test_decompiler_hammer_round_trip.py -q
- Acceptance: Produces a contract-field-by-family obligation coverage matrix for well-formedness, cross-view consistency, modality, exception, temporal, graph, lifecycle, provenance, and round-trip behavior; minimizes verified counterexamples without changing their result; records unsupported translation separately; and blocks promotion when a required family has no executable trusted route or explicit approved waiver.

```json
{"phase":"formal_supervision","scope":"hammer_coverage_and_counterexamples","authority":"deterministic_or_reconstructed_proof"}
```

## PORTAL-LIR-HAMMER-060 Route Leanstral only to informative unresolved gaps

- Status: todo
- Completion: 0
- Priority: P1
- Track: leanstral-policy
- Depends on: PORTAL-LIR-HAMMER-024, PORTAL-LIR-HAMMER-025, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-059
- Outputs: ipfs_datasets_py/logic/modal/leanstral_audit_policy.py, ipfs_datasets_py/logic/modal/leanstral_audit_worker.py, tests/unit_tests/logic/modal/test_leanstral_audit_policy.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit_tests/logic/modal/test_leanstral_audit_policy.py tests/unit_tests/logic/modal/test_leanstral_audit_worker.py tests/unit_tests/logic/modal/test_leanstral_verifier.py -q
- Acceptance: Selects Leanstral work from recurrent, high-severity, high-uncertainty, or Hammer-unsolved gaps with an owned compiler surface; skips cache hits, solved obligations, stale snapshots, low-impact noise, and exhausted families; enforces fair per-family budgets and reports selected, skipped, abstained, cached, stale, and marginal-value outcomes.

```json
{"phase":"formal_supervision","scope":"selective_leanstral_auditing","optimization_target":"verified_information_gain_per_gpu_second"}
```

## PORTAL-LIR-HAMMER-061 Preserve closed-loop repair attribution through the next compiler cycle

- Status: todo
- Completion: 0
- Priority: P0
- Track: repair-attribution
- Depends on: PORTAL-LIR-HAMMER-029, PORTAL-LIR-HAMMER-037, PORTAL-LIR-HAMMER-049, PORTAL-LIR-HAMMER-056, PORTAL-LIR-HAMMER-057, PORTAL-LIR-HAMMER-059, PORTAL-LIR-HAMMER-060
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/compiler_repair_lineage.py, tests/unit/optimizers/logic_theorem_optimizer/test_compiler_repair_lineage.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_compiler_repair_lineage.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_codex_projection.py tests/unit/optimizers/logic_theorem_optimizer/test_program_synthesis_failure_recovery.py -q
- Acceptance: Links state snapshot, metric gap, Leanstral audit, Hammer receipt, rule-gap report, TODO, Codex attempt, validation, merge, and next-cycle observation with stable IDs and timestamps; classifies accepted benefit, neutral change, quality regression, disproven hypothesis, stale evidence, and operational failure; feeds only observed deterministic outcomes into future prioritization.

```json
{"phase":"formal_supervision","scope":"state_to_verified_patch_to_next_cycle","hard_rule":"model assertions never substitute for observed compiler outcomes"}
```

## PORTAL-LIR-HAMMER-062 Profile and optimize CUDA projection training

- Status: completed
- Completion: 0
- Priority: P0
- Track: cuda-runtime
- Depends on: PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-054
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/projection_profiler.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, benchmarks/bench_legal_ir_projection_training.py, tests/unit/optimizers/logic_theorem_optimizer/test_projection_profiler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_projection_profiler.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py -q; /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python benchmarks/bench_legal_ir_projection_training.py --dry-run
- Acceptance: Profiles host/device transfer, kernel, synchronization, Python-loop, optimizer, and feature-head costs by family; batches compatible updates and removes redundant synchronization; demonstrates at least 40 percent lower warm p95 projection time on the fixed benchmark without changing deterministic outputs, trust decisions, or quality beyond configured numerical tolerance.

```json
{"phase":"runtime_critical_path","scope":"cuda_projection_training","observed_seconds":401.604523724,"target_p95_reduction":0.40}
```

## PORTAL-LIR-HAMMER-063 Keep autoencoder state resident and batch multi-head CUDA updates

- Status: completed
- Completion: 0
- Priority: P0
- Track: cuda-runtime
- Depends on: PORTAL-LIR-HAMMER-046, PORTAL-LIR-HAMMER-062
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_cuda.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_cuda_residency.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_cuda_residency.py tests/unit/optimizers/logic_theorem_optimizer/test_trainable_legal_ir_objective.py -q
- Acceptance: Keeps reusable embeddings, family indices, masks, and head parameters on the selected CUDA device across inner iterations; batches family, slot, proof, and LegalIR-view updates; supports numerically checked mixed precision where safe; emits transfer and synchronization counters; and falls back deterministically when CUDA admission fails.

```json
{"phase":"runtime_critical_path","scope":"cuda_resident_multi_head_updates","production_trainers":1}
```

## PORTAL-LIR-HAMMER-064 Activate asynchronous immutable snapshot evaluation in production

- Status: todo
- Completion: 0
- Priority: P0
- Track: evaluation-runtime
- Depends on: PORTAL-LIR-HAMMER-039, PORTAL-LIR-HAMMER-040, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-063
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/snapshot_evaluator.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_production_snapshot_evaluation.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_production_snapshot_evaluation.py tests/unit/optimizers/logic_theorem_optimizer/test_snapshot_evaluator.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_loop_contract.py -q
- Acceptance: Runs family-sharded train, validation, compiler, proof, and promotion evaluation from immutable snapshots without blocking the canonical trainer; aggregates only matching state/compiler/schema/holdout shards; coalesces superseded unevaluated snapshots; applies bounded backpressure; and proves production summaries expose queue depth, staleness, dropped work, evaluator health, and snapshot-complete promotion state.

```json
{"phase":"runtime_pipeline","scope":"asynchronous_snapshot_evaluation","hard_boundaries":["one_canonical_trainer","immutable_snapshots","version_matched_aggregation"]}
```

## PORTAL-LIR-HAMMER-065 Build a shared single-flight compiler and embedding artifact graph

- Status: todo
- Completion: 0
- Priority: P0
- Track: artifact-runtime
- Depends on: PORTAL-LIR-HAMMER-036, PORTAL-LIR-HAMMER-041, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-064
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_evaluation_artifacts.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_evaluation_artifacts.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_evaluation_artifacts.py tests/unit/optimizers/logic_theorem_optimizer/test_metrics_wiring.py tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py -q
- Acceptance: Materializes compilation, normalization, tokenization, embedding, view-contract, obligation, and baseline metric nodes once per complete digest and shares them across unguided, guided, train, validation, Hammer, Leanstral, and promotion consumers; coalesces concurrent misses; validates cache provenance; and reports avoided work and saved wall time without cross-state leakage.

```json
{"phase":"runtime_pipeline","scope":"immutable_artifact_dag","observed_cache_hit_rate":0.824561404}
```

## PORTAL-LIR-HAMMER-066 Move disagreement export and checkpoint persistence off the cycle path

- Status: todo
- Completion: 0
- Priority: P1
- Track: persistence-runtime
- Depends on: PORTAL-LIR-HAMMER-035, PORTAL-LIR-HAMMER-065
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/async_artifact_writer.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, tests/unit/optimizers/logic_theorem_optimizer/test_async_artifact_writer.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_async_artifact_writer.py tests/unit_tests/logic/modal/test_introspection_export.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_loop_contract.py -q
- Acceptance: Writes append-only disagreement batches, summaries, state deltas, and periodic full checkpoints through a bounded asynchronous writer with atomic rename, checksum, fsync policy, crash replay, and backpressure; makes required promotion evidence durable before acknowledgement; and removes ordinary serialization and full-state writes from the trainer critical path.

```json
{"phase":"runtime_pipeline","scope":"nonblocking_durable_writes","observed_seconds":{"disagreement_export":32.467993758,"state_persistence":20.575898966}}
```

## PORTAL-LIR-HAMMER-067 Make CUDA telemetry and unified-memory admission trustworthy

- Status: completed
- Completion: 0
- Priority: P0
- Track: resource-runtime
- Depends on: PORTAL-LIR-HAMMER-038, PORTAL-LIR-HAMMER-044, PORTAL-LIR-HAMMER-062
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py, tests/unit/optimizers/logic_theorem_optimizer/test_cuda_resource_telemetry.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_cuda_resource_telemetry.py tests/unit/optimizers/logic_theorem_optimizer/test_runtime_phase_telemetry.py tests/unit/optimizers/logic_theorem_optimizer/test_global_resource_scheduler.py -q
- Acceptance: Detects CUDA through PyTorch and supported NVIDIA interfaces even when one collector is unavailable; attributes trainer and persistent Leanstral GPU/unified-memory use by process; distinguishes unavailable telemetry from zero use; admits work against reserved memory and pressure thresholds; and prevents an autotuner from increasing concurrency from unknown GPU data.

```json
{"phase":"runtime_resources","scope":"cuda_and_unified_memory_admission","observed_gap":"collector_status=gpu_unavailable while CUDA trainer and Leanstral server were active"}
```

## PORTAL-LIR-HAMMER-068 Adapt evaluator, Hammer, validation, and Codex workers to useful pressure

- Status: todo
- Completion: 0
- Priority: P0
- Track: parallel-runtime
- Depends on: PORTAL-LIR-HAMMER-038, PORTAL-LIR-HAMMER-050, PORTAL-LIR-HAMMER-064, PORTAL-LIR-HAMMER-065, PORTAL-LIR-HAMMER-066, PORTAL-LIR-HAMMER-067
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/parallelism_autotuner.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py, tests/unit/optimizers/logic_theorem_optimizer/test_adaptive_pipeline_parallelism.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_adaptive_pipeline_parallelism.py tests/unit/optimizers/logic_theorem_optimizer/test_parallelism_autotuner.py tests/unit/optimizers/logic_theorem_optimizer/test_codex_scope_scheduler.py -q
- Acceptance: Chooses worker counts from ready queue depth, disjoint scopes, measured service time, nested child count, validation capacity, merge conflicts, CPU, RAM, swap, and GPU pressure; preserves one canonical trainer and one overlapping-write merge lane; scales down before contention; and targets 70-90 percent useful CPU occupancy rather than raw process count.

```json
{"phase":"runtime_resources","scope":"adaptive_global_parallelism","observed_cpu_average":0.07486,"target_useful_cpu_range":[0.70,0.90]}
```

## PORTAL-LIR-HAMMER-069 Add resource-aware early-stopped hyperparameter search

- Status: todo
- Completion: 0
- Priority: P1
- Track: hparam-runtime
- Depends on: PORTAL-LIR-HAMMER-052, PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-064, PORTAL-LIR-HAMMER-067, PORTAL-LIR-HAMMER-068
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_hparam_scheduler.py, scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_hparam_scheduler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_hparam_scheduler.py tests/unit/optimizers/logic_theorem_optimizer/test_parallel_pipeline_rollout_gate.py -q; scripts/ops/legal_ir/run_hammer_leanstral_hparam.sh --dry-run
- Acceptance: Uses deterministic seeds, shared immutable baselines, successive-halving or equivalent bounded early stopping, confidence-aware family guardrails, and resource leases; permits concurrent evaluation and optional concurrent trainers only when memory admission proves safety; never compares incomplete or lineage-mismatched snapshots; and spends the fixed search budget on more informative candidates than six unconditional sequential full trials.

```json
{"phase":"runtime_search","scope":"resource_aware_hparam_scheduler","default_cuda_trainers":1,"parallel_lanes":["snapshot_evaluation","proof","validation"]}
```

## PORTAL-LIR-HAMMER-070 Operate Leanstral as a cache-first continuously batched service

- Status: todo
- Completion: 0
- Priority: P1
- Track: leanstral-runtime
- Depends on: PORTAL-LIR-HAMMER-043, PORTAL-LIR-HAMMER-060, PORTAL-LIR-HAMMER-067, PORTAL-LIR-HAMMER-068
- Outputs: ipfs_datasets_py/logic/modal/leanstral_audit_worker.py, scripts/ops/legal_ir/watch_leanstral_audit_worker.sh, tests/unit_tests/logic/modal/test_leanstral_continuous_batching.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit_tests/logic/modal/test_leanstral_continuous_batching.py tests/unit_tests/logic/modal/test_leanstral_audit_worker.py -q
- Acceptance: Reuses one healthy CUDA-backed Leanstral service, performs content-addressed lookup before admission, continuously batches compatible requests by model/template/family/deadline, preserves per-item IDs and retries, prevents one family from starving others, applies queue backpressure, and reports tokens, verified audits, cache value, and marginal information per GPU second.

```json
{"phase":"runtime_inference","scope":"leanstral_continuous_batch_service","hard_rule":"Leanstral service health does not confer proof authority"}
```

## PORTAL-LIR-HAMMER-071 Balance Codex generation, isolated validation, and merge capacity

- Status: todo
- Completion: 0
- Priority: P0
- Track: codex-runtime
- Depends on: PORTAL-LIR-HAMMER-048, PORTAL-LIR-HAMMER-049, PORTAL-LIR-HAMMER-050, PORTAL-LIR-HAMMER-061, PORTAL-LIR-HAMMER-068
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/codex_scope_scheduler.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/incremental_validation.py, tests/unit/optimizers/logic_theorem_optimizer/test_codex_validation_flow_control.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_codex_validation_flow_control.py tests/unit/optimizers/logic_theorem_optimizer/test_codex_scope_scheduler.py tests/unit/optimizers/logic_theorem_optimizer/test_incremental_validation.py tests/unit/optimizers/logic_theorem_optimizer/test_program_synthesis_failure_recovery.py -q
- Acceptance: Starts Codex workers only for verified ready work in disjoint predicted write sets; sizes generation against validation and serialized-merge service rates; bundles same-scope evidence; rescues transient failures without poisoning semantic statistics; pauses on validation backlog or conflict growth; and maximizes accepted, next-cycle-confirmed compiler patches per wall-clock hour rather than claims or generated diffs.

```json
{"phase":"runtime_implementation","scope":"codex_validation_merge_flow","primary_throughput":"accepted_next_cycle_confirmed_patches_per_hour"}
```

## PORTAL-LIR-HAMMER-072 Run the evidence-driven benchmark and staged promotion

- Status: todo
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-056, PORTAL-LIR-HAMMER-058, PORTAL-LIR-HAMMER-059, PORTAL-LIR-HAMMER-061, PORTAL-LIR-HAMMER-063, PORTAL-LIR-HAMMER-064, PORTAL-LIR-HAMMER-065, PORTAL-LIR-HAMMER-066, PORTAL-LIR-HAMMER-067, PORTAL-LIR-HAMMER-069, PORTAL-LIR-HAMMER-070, PORTAL-LIR-HAMMER-071
- Outputs: benchmarks/bench_legal_ir_optimizer_pipeline.py, scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md, tests/unit/optimizers/logic_theorem_optimizer/test_evidence_driven_rollout.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_evidence_driven_rollout.py tests/unit/optimizers/logic_theorem_optimizer/test_parallel_pipeline_rollout_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_hammer_rollout_gates.py -q; /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python benchmarks/bench_legal_ir_optimizer_pipeline.py --dry-run; PYTHONPATH=/home/barberb/portland-laws.github.io/ipfs_accelerate_py:. /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -c "from pathlib import Path; from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_task_file; tasks=parse_task_file(Path('docs/LEGAL_IR_HAMMER_LEANSTRAL_AGENT_TODOS.md')); ids={task.task_id for task in tasks}; assert len(tasks)>=72; assert all(task.acceptance and task.validation and task.outputs for task in tasks); assert all(dep in ids for task in tasks for dep in task.depends_on); print('parsed', len(tasks), 'tasks')"
- Acceptance: Publishes a matched cold/warm baseline, passes an integrated CUDA/Hammer/Leanstral/Codex smoke, runs a one-hour resource-aware hparam search, then an eight-hour canary and twenty-four-hour production run; requires responsive learned metrics, complete promotion lineage, trusted-feedback efficacy, full required Hammer coverage, no hard family/provenance/anti-copy/reconstruction regression, at least 40 percent lower projection p95, healthy resource telemetry, no orphaned processes, at least 20 percent better task-to-accepted-patch rate, and at least 25 percent lower state-to-merged-patch lag before promotion.

```json
{"phase":"evidence_driven_rollout","scope":"quality_and_throughput_promotion","stages":["benchmark","integrated_smoke","one_hour_hparam","eight_hour_canary","twenty_four_hour_production"]}
```

## PORTAL-LIR-HAMMER-073 Build leakage-resistant LegalIR corpus splits

- Status: todo
- Completion: 0
- Priority: P0
- Track: evaluation-integrity
- Depends on: PORTAL-LIR-HAMMER-054, PORTAL-LIR-HAMMER-072
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_eval_splits.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_eval_splits.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_eval_splits.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_metric_responsiveness.py -q
- Acceptance: Creates deterministic train, validation, canary, holdout, statute-family, jurisdiction, temporal, and external-test partitions with content, citation, source, amendment, and near-duplicate leakage checks; blocks training, hparam selection, representation promotion, and Codex TODO projection when an example, citation cluster, or source span crosses a protected split.

```json
{"phase":"evaluation_integrity","scope":"leakage_resistant_splits","hard_guardrails":["holdout_isolation","near_duplicate_blocking","citation_cluster_isolation"]}
```

## PORTAL-LIR-HAMMER-074 Add semantic-equivalence metrics beyond CE and cosine

- Status: todo
- Completion: 0
- Priority: P0
- Track: evaluation-integrity
- Depends on: PORTAL-LIR-HAMMER-058, PORTAL-LIR-HAMMER-073
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_semantic_metrics.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_semantic_metrics.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_semantic_metrics.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_objective_balancer.py -q
- Acceptance: Adds structural equivalence, obligation-equivalence, counterexample-equivalence, graph isomorphism, temporal-window agreement, decompiler round-trip preservation, and proof-obligation delta metrics; reports disagreement when CE/cosine improve while semantic equivalence regresses; makes semantic equivalence a hard promotion gate by family.

```json
{"phase":"evaluation_integrity","scope":"semantic_equivalence_metrics","reason":"cross_entropy_and_cosine_are_insufficient_as_compiler_quality_signals"}
```

## PORTAL-LIR-HAMMER-075 Constrain LegalIR decoding with typed grammars

- Status: todo
- Completion: 0
- Priority: P0
- Track: autoencoder-architecture
- Depends on: PORTAL-LIR-HAMMER-055, PORTAL-LIR-HAMMER-074
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_grammar_decoder.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_grammar_decoder.py tests/unit/optimizers/logic_theorem_optimizer/test_trainable_legal_ir_objective.py -q
- Acceptance: Adds typed constrained decoding for deontic, frame logic, TDFOL, KG, CEC, temporal, provenance, and decompiler plans; masks invalid productions before metric scoring; records grammar rejection reasons; and proves the learned path cannot gain reward by emitting syntactically impossible or source-copy placeholders.

```json
{"phase":"evaluation_integrity","scope":"typed_grammar_constrained_decoding","hard_guardrail":"invalid_ir_not_rewarded"}
```

## PORTAL-LIR-HAMMER-076 Calibrate uncertainty and abstention for learned guidance

- Status: todo
- Completion: 0
- Priority: P1
- Track: evaluation-integrity
- Depends on: PORTAL-LIR-HAMMER-055, PORTAL-LIR-HAMMER-073, PORTAL-LIR-HAMMER-075
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_uncertainty.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_uncertainty.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_uncertainty.py tests/unit/optimizers/logic_theorem_optimizer/test_trainable_legal_ir_objective.py -q
- Acceptance: Reports calibrated confidence, entropy, abstention, out-of-distribution, and unsupported-family signals by LegalIR family; routes low-confidence learned outputs to Hammer/Leanstral audit rather than Codex TODO generation; and blocks promotion when calibration error or unsupported abstention exceeds configured family thresholds.

```json
{"phase":"evaluation_integrity","scope":"uncertainty_and_abstention","promotion_rule":"uncertain_guidance_routes_to_audit_not_compiler_rules"}
```

## PORTAL-LIR-HAMMER-077 Add metamorphic and differential LegalIR fuzzing

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-validation
- Depends on: PORTAL-LIR-HAMMER-059, PORTAL-LIR-HAMMER-074, PORTAL-LIR-HAMMER-075
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_fuzzing.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_metamorphic_fuzzing.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_metamorphic_fuzzing.py tests/unit/logic/integration/test_legal_ir_hammer_coverage.py -q
- Acceptance: Generates semantics-preserving and semantics-changing mutations for legal text, deterministic IR, learned IR, obligations, and decompiler outputs; checks expected invariant or changed metrics; differentially compares deterministic compiler, learned guidance, Hammer obligations, and decompiler round trips; and stores minimal counterexamples as trusted negative training candidates only after verification.

```json
{"phase":"evaluation_integrity","scope":"metamorphic_differential_fuzzing","targets":["text","ir","obligations","decompiler"]}
```

## PORTAL-LIR-HAMMER-078 Train with verified hard-negative curricula

- Status: todo
- Completion: 0
- Priority: P0
- Track: autoencoder-objective
- Depends on: PORTAL-LIR-HAMMER-057, PORTAL-LIR-HAMMER-077
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_hard_negatives.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_hard_negatives.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_hard_negatives.py tests/unit/optimizers/logic_theorem_optimizer/test_proof_feedback_ablation.py -q
- Acceptance: Builds a curriculum from verified counterexamples, near-miss clauses, swapped actors, inverted modalities, stale amendments, wrong citations, source-copy spans, and decompiler hallucinations; schedules negatives by family difficulty; and proves hard negatives reduce false-positive semantic equivalence without degrading trusted positive obligations beyond tolerance.

```json
{"phase":"evaluation_integrity","scope":"verified_hard_negative_curriculum","hard_rule":"unverified_model_negatives_are_not_training_labels"}
```

## PORTAL-LIR-HAMMER-079 Require multi-seed statistical promotion evidence

- Status: todo
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-072, PORTAL-LIR-HAMMER-073, PORTAL-LIR-HAMMER-074, PORTAL-LIR-HAMMER-078
- Outputs: scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, tests/unit/optimizers/logic_theorem_optimizer/test_multi_seed_promotion_gate.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_multi_seed_promotion_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_evidence_driven_rollout.py -q
- Acceptance: Requires configured multi-seed confidence intervals for learned quality, deterministic compiler quality, semantic equivalence, proof validity, hard-negative performance, and accepted patch rate; rejects single-lucky-run promotion and records effect size, variance, seed set, and failure-family attribution.

```json
{"phase":"evaluation_integrity","scope":"multi_seed_statistical_promotion","hard_guardrail":"single_seed_success_is_not_production_evidence"}
```

## PORTAL-LIR-HAMMER-080 Version LegalIR schema evolution and compatibility

- Status: todo
- Completion: 0
- Priority: P0
- Track: legal-ir-contracts
- Depends on: PORTAL-LIR-HAMMER-019, PORTAL-LIR-HAMMER-056, PORTAL-LIR-HAMMER-075
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_schema_evolution.py, tests/unit/logic/integration/test_legal_ir_schema_evolution.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_schema_evolution.py tests/unit/logic/integration/test_legal_ir_view_contracts.py -q
- Acceptance: Adds explicit schema versions, migrations, compatibility checks, deprecation policy, downgrade behavior, feature gates, and metric lineage binding; rejects learned exports, Hammer receipts, Leanstral audits, caches, and compiler outputs whose schema compatibility is unknown or inconsistent.

```json
{"phase":"evaluation_integrity","scope":"ir_schema_evolution","hard_guardrail":"unknown_schema_never_reused"}
```

## PORTAL-LIR-HAMMER-081 Defend against prompt and premise poisoning

- Status: todo
- Completion: 0
- Priority: P0
- Track: security
- Depends on: PORTAL-LIR-HAMMER-022, PORTAL-LIR-HAMMER-060, PORTAL-LIR-HAMMER-080
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_premise_security.py, tests/unit/logic/integration/test_legal_ir_premise_security.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_premise_security.py tests/unit/logic/integration/test_legal_ir_premise_selection.py tests/unit_tests/logic/modal/test_leanstral_audit_policy.py -q
- Acceptance: Detects prompt injection, adversarial quoted text, poisoned premises, malicious citations, model-output-as-premise leakage, and untrusted proof hints; sanitizes Leanstral prompts and Hammer premises; records provenance and rejection reasons; and blocks poisoned artifacts from training, proof, Codex TODOs, and promotion.

```json
{"phase":"evaluation_integrity","scope":"prompt_and_premise_poisoning_defense","hard_rule":"legal_source_text_is_data_not_instructions"}
```

## PORTAL-LIR-HAMMER-082 Add external legal-expert benchmark packets

- Status: todo
- Completion: 0
- Priority: P1
- Track: external-evaluation
- Depends on: PORTAL-LIR-HAMMER-073, PORTAL-LIR-HAMMER-074, PORTAL-LIR-HAMMER-081
- Outputs: tests/fixtures/legal_ir/external_expert_benchmark.jsonl, ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_external_benchmark.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_external_benchmark.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_external_benchmark.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_semantic_metrics.py -q
- Acceptance: Defines a versioned external benchmark packet format for expert-authored examples, expected IR families, acceptable ambiguity, citations, proof obligations, decompiler expectations, and adjudication metadata; keeps external packets out of training and hparam selection; and reports external validity separately from internal canary metrics.

```json
{"phase":"evaluation_integrity","scope":"external_legal_expert_benchmark","hard_guardrail":"external_benchmark_never_training_data"}
```

## PORTAL-LIR-HAMMER-083 Monitor production drift and rollback learned guidance

- Status: todo
- Completion: 0
- Priority: P0
- Track: production-safety
- Depends on: PORTAL-LIR-HAMMER-056, PORTAL-LIR-HAMMER-079, PORTAL-LIR-HAMMER-082
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_drift_monitor.py, tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_drift_monitor.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_drift_monitor.py tests/unit/logic/integration/test_representation_promotion_evidence.py -q
- Acceptance: Tracks production distribution drift, family-specific metric drift, proof failure drift, prompt/premise rejection spikes, schema drift, GPU/resource degradation, and accepted-patch regression; automatically disables promoted learned guidance and opens rollback TODOs when drift exceeds configured thresholds.

```json
{"phase":"evaluation_integrity","scope":"production_drift_and_rollback","hard_guardrail":"learned_guidance_is_reversible"}
```

## PORTAL-LIR-HAMMER-084 Run external-validity promotion gate

- Status: todo
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-079, PORTAL-LIR-HAMMER-080, PORTAL-LIR-HAMMER-081, PORTAL-LIR-HAMMER-082, PORTAL-LIR-HAMMER-083
- Outputs: docs/implementation/reports/HAMMER_LEANSTRAL_EXTERNAL_VALIDITY_REPORT.md, scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, tests/unit/optimizers/logic_theorem_optimizer/test_external_validity_promotion_gate.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_external_validity_promotion_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_multi_seed_promotion_gate.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_drift_monitor.py -q
- Acceptance: Publishes an external-validity report that binds leak-free splits, semantic metrics, typed decoding, uncertainty, fuzzing, hard negatives, multi-seed statistics, schema compatibility, poisoning defenses, external benchmark scores, and rollback readiness; promotion fails closed on missing or inconsistent evidence.

```json
{"phase":"external_validity_rollout","scope":"fail_closed_evaluation_integrity_gate"}
```

## PORTAL-LIR-HAMMER-085 Add lossless source maps and provenance spans

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-080, PORTAL-LIR-HAMMER-084
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_source_maps.py, tests/unit/logic/integration/test_legal_ir_source_maps.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_source_maps.py tests/unit/logic/integration/test_legal_ir_schema_evolution.py -q
- Acceptance: Preserves source document, citation, offset, token span, normalized text, transformation step, and decompiler attribution for every IR node; supports many-to-one and one-to-many transforms; and proves compiler, decompiler, Hammer receipts, learned guidance, and diagnostics can trace every emitted fact back to source or mark it derived.

```json
{"phase":"compiler_productization","scope":"lossless_source_maps","compiler_property":"every_ir_fact_has_explainable_origin"}
```

## PORTAL-LIR-HAMMER-086 Implement legal symbol tables and definition resolution

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-085
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_symbols.py, tests/unit/logic/integration/test_legal_ir_symbols.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_symbols.py tests/unit/logic/integration/test_legal_ir_source_maps.py -q
- Acceptance: Resolves defined terms, scoped references, actors, authorities, exceptions, conditions, cross-document symbols, aliases, and shadowing with source-map provenance; exposes unresolved and ambiguous symbols as typed diagnostics rather than silent best guesses.

```json
{"phase":"compiler_productization","scope":"legal_symbol_tables","compiler_property":"definitions_are_scoped_and_diagnostic"}
```

## PORTAL-LIR-HAMMER-087 Link citations and cross references canonically

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-085, PORTAL-LIR-HAMMER-086
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_citations.py, tests/unit/logic/integration/test_legal_ir_citations.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_citations.py tests/unit/logic/integration/test_legal_ir_symbols.py -q
- Acceptance: Canonicalizes internal and external citations, ranges, subsections, incorporated references, repealed references, and unresolved references; records authority, version, source-map lineage, and confidence; and blocks proof or learned targets from treating unresolved citations as resolved law.

```json
{"phase":"compiler_productization","scope":"citation_cross_reference_linker","compiler_property":"references_are_explicitly_resolved_or_diagnostic"}
```

## PORTAL-LIR-HAMMER-088 Model authority, amendment, repeal, and temporal applicability

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-080, PORTAL-LIR-HAMMER-087
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_temporal_authority.py, tests/unit/logic/integration/test_legal_ir_temporal_authority.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_temporal_authority.py tests/unit/logic/integration/test_legal_ir_citations.py -q
- Acceptance: Represents effective dates, sunset dates, amendments, repeals, supersession, jurisdiction, authority hierarchy, emergency rules, and temporal query context; Hammer obligations verify that deontic and factual conclusions are evaluated under the correct authority and time window.

```json
{"phase":"compiler_productization","scope":"temporal_authority_model","compiler_property":"law_is_time_and_authority_scoped"}
```

## PORTAL-LIR-HAMMER-089 Represent ambiguity as first-class LegalIR

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-076, PORTAL-LIR-HAMMER-086, PORTAL-LIR-HAMMER-088
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_ambiguity.py, tests/unit/logic/integration/test_legal_ir_ambiguity.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_ambiguity.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_uncertainty.py -q
- Acceptance: Encodes unresolved ambiguity, competing parses, unsupported interpretations, and required human review as typed IR values with source spans and confidence; prevents ambiguity from being collapsed into arbitrary learned labels; and routes high-impact ambiguity to Leanstral audit or operator diagnostics.

```json
{"phase":"compiler_productization","scope":"first_class_ambiguity","compiler_property":"uncertainty_is_represented_not_hidden"}
```

## PORTAL-LIR-HAMMER-090 Build a verified LegalIR pass manager

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-core
- Depends on: PORTAL-LIR-HAMMER-059, PORTAL-LIR-HAMMER-085, PORTAL-LIR-HAMMER-089
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_pass_manager.py, tests/unit/logic/integration/test_legal_ir_pass_manager.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_pass_manager.py tests/unit/logic/integration/test_legal_ir_hammer_coverage.py -q
- Acceptance: Defines ordered compiler/decompiler passes, declared inputs and outputs, invalidation rules, source-map preservation, schema migrations, Hammer obligations, and deterministic replay; rejects passes that mutate protected fields without a proof or explicit diagnostic.

```json
{"phase":"compiler_productization","scope":"verified_pass_manager","compiler_property":"compiler_passes_are_ordered_replayable_and_checked"}
```

## PORTAL-LIR-HAMMER-091 Validate backend conformance across IR targets

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-backends
- Depends on: PORTAL-LIR-HAMMER-074, PORTAL-LIR-HAMMER-090
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_backend_conformance.py, tests/unit/logic/integration/test_legal_ir_backend_conformance.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_backend_conformance.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_semantic_metrics.py -q
- Acceptance: Checks that frame logic, deontic, TDFOL, KG, CEC, external prover, and decompiler backends agree on shared semantics or emit typed unsupported diagnostics; records backend feature coverage and blocks promotion when one backend silently drops obligations.

```json
{"phase":"compiler_productization","scope":"backend_conformance","compiler_property":"backends_cannot_silently_diverge"}
```

## PORTAL-LIR-HAMMER-092 Make legal compiler builds reproducible

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-ops
- Depends on: PORTAL-LIR-HAMMER-080, PORTAL-LIR-HAMMER-090
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_build_manifest.py, tests/unit/logic/integration/test_legal_ir_build_manifest.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_build_manifest.py tests/unit/logic/integration/test_legal_ir_schema_evolution.py -q
- Acceptance: Emits reproducible build manifests with source digests, compiler commit, schema versions, pass graph, model/export IDs, proof tool versions, runtime configuration, cache digests, and deterministic replay command; proves equivalent inputs produce equivalent manifests and outputs.

```json
{"phase":"compiler_productization","scope":"reproducible_builds","compiler_property":"outputs_are_replayable"}
```

## PORTAL-LIR-HAMMER-093 Add incremental and parallel compilation

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-performance
- Depends on: PORTAL-LIR-HAMMER-065, PORTAL-LIR-HAMMER-068, PORTAL-LIR-HAMMER-090, PORTAL-LIR-HAMMER-092
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_incremental_compiler.py, tests/unit/logic/integration/test_legal_ir_incremental_compiler.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_incremental_compiler.py tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_evaluation_artifacts.py -q
- Acceptance: Recompiles only changed source, citation, symbol, temporal, and pass dependency subgraphs; runs independent compilation shards in parallel under resource leases; preserves deterministic output order; and reports invalidated nodes, avoided work, and p95 speedup.

```json
{"phase":"compiler_productization","scope":"incremental_parallel_compilation","compiler_property":"large_corpora_do_not_force_full_rebuilds"}
```

## PORTAL-LIR-HAMMER-094 Produce semantic diffs and amendment impact analysis

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-analysis
- Depends on: PORTAL-LIR-HAMMER-088, PORTAL-LIR-HAMMER-091, PORTAL-LIR-HAMMER-093
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_semantic_diff.py, tests/unit/logic/integration/test_legal_ir_semantic_diff.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_semantic_diff.py tests/unit/logic/integration/test_legal_ir_temporal_authority.py -q
- Acceptance: Computes semantic diffs across source revisions, amendments, compiler commits, schema versions, and learned-guidance activation states; classifies obligation added, removed, narrowed, broadened, temporally shifted, citation changed, ambiguity changed, and proof status changed; and emits Codex TODOs only for verified compiler-impact regressions.

```json
{"phase":"compiler_productization","scope":"semantic_diff_and_amendment_impact","compiler_property":"changes_are_semantic_not_just_textual"}
```

## PORTAL-LIR-HAMMER-095 Emit proof-carrying LegalIR artifacts

- Status: todo
- Completion: 0
- Priority: P0
- Track: formal-verification
- Depends on: PORTAL-LIR-HAMMER-059, PORTAL-LIR-HAMMER-090, PORTAL-LIR-HAMMER-091, PORTAL-LIR-HAMMER-092
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_proof_carrying_artifacts.py, tests/unit/logic/integration/test_legal_ir_proof_carrying_artifacts.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_proof_carrying_artifacts.py tests/unit/logic/integration/test_legal_ir_backend_conformance.py -q
- Acceptance: Packages LegalIR outputs with proof obligations, Hammer receipts, reconstruction status, unsupported diagnostics, source maps, build manifest, and verification policy; downstream consumers can independently reject artifacts with missing, stale, incompatible, or failed proof evidence.

```json
{"phase":"compiler_productization","scope":"proof_carrying_ir_artifacts","compiler_property":"outputs_carry_their_verification_evidence"}
```

## PORTAL-LIR-HAMMER-096 Add diagnostics and explanation traces

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-ux
- Depends on: PORTAL-LIR-HAMMER-061, PORTAL-LIR-HAMMER-085, PORTAL-LIR-HAMMER-089, PORTAL-LIR-HAMMER-095
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_diagnostics.py, tests/unit/logic/integration/test_legal_ir_diagnostics.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_diagnostics.py tests/unit/optimizers/logic_theorem_optimizer/test_compiler_repair_lineage.py -q
- Acceptance: Emits structured diagnostics for unresolved symbols, citations, ambiguity, temporal authority, unsupported backend features, proof failures, learned-guidance abstentions, poisoning rejections, decompiler losses, and Codex repair attribution; every diagnostic includes severity, family, source map, remediation hint, and machine-readable code.

```json
{"phase":"compiler_productization","scope":"diagnostics_and_explanation_traces","compiler_property":"failures_are_actionable"}
```

## PORTAL-LIR-HAMMER-097 Expose compiler CLI, API, and LSP surfaces

- Status: todo
- Completion: 0
- Priority: P1
- Track: compiler-interface
- Depends on: PORTAL-LIR-HAMMER-092, PORTAL-LIR-HAMMER-093, PORTAL-LIR-HAMMER-096
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_compiler_api.py, scripts/ops/legal_ir/legal_ir_compile.py, tests/unit/logic/integration/test_legal_ir_compiler_api.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_compiler_api.py tests/unit/logic/integration/test_legal_ir_diagnostics.py -q; /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python scripts/ops/legal_ir/legal_ir_compile.py --help
- Acceptance: Provides stable compile, decompile, validate, diff, explain, benchmark, and artifact-export entrypoints with JSON output, deterministic exit codes, source-map diagnostics, and optional learned-guidance activation flags; keeps production defaults deterministic and proof-aware.

```json
{"phase":"compiler_productization","scope":"cli_api_lsp_surfaces","compiler_property":"compiler_is_operable_without_daemon_internals"}
```

## PORTAL-LIR-HAMMER-098 Add standards and interchange interoperability

- Status: todo
- Completion: 0
- Priority: P1
- Track: interoperability
- Depends on: PORTAL-LIR-HAMMER-091, PORTAL-LIR-HAMMER-095, PORTAL-LIR-HAMMER-097
- Outputs: ipfs_datasets_py/logic/integration/reasoning/legal_ir_interop.py, tests/unit/logic/integration/test_legal_ir_interop.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/logic/integration/test_legal_ir_interop.py tests/unit/logic/integration/test_legal_ir_proof_carrying_artifacts.py -q
- Acceptance: Imports and exports selected legal XML/JSON, RDF/OWL, KG, proof, and decompiler interchange forms with explicit lossy/lossless markers, schema mappings, source maps, and unsupported diagnostics; proves round-trip conformance for supported subsets.

```json
{"phase":"compiler_productization","scope":"standards_interoperability","compiler_property":"interchange_loss_is_explicit"}
```

## PORTAL-LIR-HAMMER-099 Build end-to-end compiler conformance suite

- Status: todo
- Completion: 0
- Priority: P0
- Track: compiler-validation
- Depends on: PORTAL-LIR-HAMMER-084, PORTAL-LIR-HAMMER-095, PORTAL-LIR-HAMMER-096, PORTAL-LIR-HAMMER-097, PORTAL-LIR-HAMMER-098
- Outputs: tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py, docs/implementation/reports/LEGAL_IR_COMPILER_CONFORMANCE_REPORT.md
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py -q
- Acceptance: Runs an end-to-end conformance suite covering compile, proof, decompile, semantic diff, diagnostics, reproducibility, external benchmark isolation, hard negatives, source maps, backend conformance, and CLI/API behavior; publishes a report with required, optional, unsupported, and failed capabilities.

```json
{"phase":"compiler_productization","scope":"end_to_end_conformance_suite","compiler_property":"gcc_for_legal_text_has_a_release_gate"}
```

## PORTAL-LIR-HAMMER-100 Run final compiler-system promotion

- Status: todo
- Completion: 0
- Priority: P0
- Track: rollout
- Depends on: PORTAL-LIR-HAMMER-084, PORTAL-LIR-HAMMER-094, PORTAL-LIR-HAMMER-095, PORTAL-LIR-HAMMER-099
- Outputs: docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_COMPILER_SYSTEM_PROMOTION.md, scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py, tests/unit/optimizers/logic_theorem_optimizer/test_compiler_system_promotion_gate.py
- Validation: /home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_compiler_system_promotion_gate.py tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py -q
- Acceptance: Promotes the system only when evaluation integrity, external validity, compiler source maps, symbols, citations, temporal authority, ambiguity, pass management, backend conformance, reproducible builds, incremental compilation, semantic diffs, proof-carrying artifacts, diagnostics, APIs, interoperability, and conformance evidence are complete and rollback-ready.

```json
{"phase":"compiler_system_promotion","scope":"legal_text_compiler_decompiler_ir","stages":["evaluation_integrity","compiler_productization","conformance","promotion"]}
```
