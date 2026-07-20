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
- The representation targets, PORTAL-LIR-HAMMER-019 through PORTAL-LIR-HAMMER-033, retain focused output and validation contracts; PORTAL-LIR-HAMMER-034 records their operator handoff. Runtime and proof-feedback targets PORTAL-LIR-HAMMER-035 through PORTAL-LIR-HAMMER-052 form the next dependency-ordered execution wave, and PORTAL-LIR-HAMMER-053 is its production rollout handoff.
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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

- Status: todo
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
