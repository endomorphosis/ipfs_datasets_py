# Leanstral Legal IR Compiler Supervisor Task List

Status: Ready for agent-supervisor execution
Owner: `ipfs_datasets_py`
Executor: `ipfs_accelerate_py.agent_supervisor`
Task prefix: `## PORTAL-`

## Goal

Use Leanstral as a proof-oriented auditor and translator between persistent
autoencoder state and the deterministic legal IR compiler/decompiler. The
autoencoder supplies ranked evidence about representation gaps; Leanstral turns
that evidence into checked semantic diagnoses and bounded compiler change
specifications; the existing Codex supervisor implements those specifications
in isolated worktrees. The deterministic compiler, source provenance, local
proof tools, mutation tests, and held-out metrics remain authoritative.

The intended flow is:

`autoencoder state -> normalized LegalIR gaps -> Leanstral audit -> verified compiler change spec -> Codex TODO -> isolated validation -> merge`

## Supervisor Policy

- Treat learned projections as evidence, never executable truth.
- Keep Leanstral in `off`, `export`, or `shadow` mode until the canary tasks pass.
- Never accept lower cross entropy or higher cosine when provenance, formal
  validity, anti-copy, mutation, or deterministic round-trip gates regress.
- Keep compiler IR CE/cosine, learned IR-view CE/cosine, semantic embedding
  validation, structural/prover validity, and source-copy penalties separate.
- Use frozen, stratified holdouts for deontic, frame-logic, TDFOL, knowledge
  graph, event-calculus, temporal, definition, amendment, and remedy cases.
- Preserve evidence IDs, canonical IR hashes, source-span hashes, model/config
  versions, and canary-manifest versions in every audit and TODO packet.
- Do not enable automatic proposal application as part of this task list.

## Execution Waves

Wave 0 is already present in the repository. Wave 1 establishes stable evidence
and baselines. Waves 2 and 3 may use separate supervisor bundles after their
dependencies complete. Wave 4 connects verified findings to the existing TODO
queue. Wave 5 is a bounded, reversible rollout.

## PORTAL-LIRLS-001 Keep explicit Leanstral provider routing and transport

- Status: completed
- Completion: manual
- Priority: P0
- Track: legal-ir
- Depends on:
- Outputs: ipfs_datasets_py/llm_router.py, tests/unit/test_llm_router_provider_aliases.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/test_llm_router_provider_aliases.py -q
- Bundle: legal-ir/leanstral-foundation
- Goal id: LIR-LEANSTRAL-FOUNDATION
- Merge key: legal-ir-leanstral-foundation
- Acceptance: Preserve the explicit `mistral_vibe` Lean-agent route, bounded timeout and token configuration, and deterministic provider selection without falling back to a generic agent.

## PORTAL-LIRLS-002 Preserve typed projection evidence and compiler change specifications

- Status: completed
- Completion: manual
- Priority: P0
- Track: legal-ir
- Depends on: PORTAL-LIRLS-001
- Outputs: ipfs_datasets_py/logic/modal/leanstral.py, ipfs_datasets_py/logic/modal/__init__.py, tests/unit_tests/logic/modal/test_leanstral.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral.py -q
- Bundle: legal-ir/leanstral-foundation
- Goal id: LIR-LEANSTRAL-FOUNDATION
- Merge key: legal-ir-leanstral-foundation
- Acceptance: Keep `ProjectionEvidence` and `CompilerChangeSpec` stable, hash-bound to canonical IR and source-span evidence, restricted to deterministic allowed paths, and explicit about target metrics, theorem templates, and mutation cases.

## PORTAL-LIRLS-003 Preserve the non-mutating Leanstral shadow contract and patch admission gate

- Status: completed
- Completion: manual
- Priority: P0
- Track: legal-ir
- Depends on: PORTAL-LIRLS-002
- Outputs: ipfs_datasets_py/logic/modal/leanstral.py, ipfs_datasets_py/logic/modal/autoencoder_loop.py, tests/unit_tests/logic/modal/test_autoencoder_loop.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral.py tests/unit_tests/logic/modal/test_autoencoder_loop.py -q
- Bundle: legal-ir/leanstral-foundation
- Goal id: LIR-LEANSTRAL-FOUNDATION
- Merge key: legal-ir-leanstral-foundation
- Acceptance: Keep proof bodies unable to add imports, axioms, theorem declarations, unsafe constructs, `sorry`, or `admit`; keep Python diffs path-restricted and `git apply --check` gated; record shadow results without mutating canonical IR.

## PORTAL-LIRLS-004 Freeze the introspection metric schema and stratified canary baseline

- Status: completed
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: PORTAL-LIRLS-003
- Outputs: ipfs_datasets_py/logic/modal/introspection_metrics.py, tests/fixtures/logic/modal/leanstral_canary_manifest.json, tests/unit_tests/logic/modal/test_introspection_metrics.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_introspection_metrics.py -q
- Bundle: legal-ir/leanstral-validation
- Goal id: LIR-LEANSTRAL-EVIDENCE
- Merge key: legal-ir-introspection-metric-schema
- Acceptance: Define versioned records for compiler IR CE/cosine, learned IR-view CE/cosine by family, source-to-decoded embedding and token loss, structural/prover validity, anti-copy penalty, state/config versions, and per-phase timing; add a frozen manifest with at least one deterministic case for every required legal logic family and fail closed on unknown schema or manifest versions.

## PORTAL-LIRLS-005 Export prioritized autoencoder-to-compiler disagreement packets

- Status: completed
- Completion: manual
- Priority: P0
- Track: legal-ir
- Depends on: PORTAL-LIRLS-003
- Outputs: ipfs_datasets_py/logic/modal/introspection_export.py, ipfs_datasets_py/logic/modal/__init__.py, tests/unit_tests/logic/modal/test_introspection_export.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_introspection_export.py -q
- Bundle: legal-ir/leanstral-evidence
- Goal id: LIR-LEANSTRAL-EVIDENCE
- Merge key: legal-ir-introspection-export
- Acceptance: Export compact deterministic packets containing evidence ID, state/schema/config versions, sample and source-span hashes, canonical and predicted LegalIR views, per-family CE/cosine gaps, compiler round-trip gaps, ranked feature contributions, synthesis focus, proof-route status, and anti-copy evidence; exclude raw dense weight tables and cap packet size deterministically.

## PORTAL-LIRLS-006 Normalize and cluster LegalIR gaps by semantic family and compiler surface

- Status: completed
- Completion: manual
- Priority: P0
- Track: legal-ir
- Depends on: PORTAL-LIRLS-004, PORTAL-LIRLS-005
- Outputs: ipfs_datasets_py/logic/modal/introspection_analysis.py, ipfs_datasets_py/logic/modal/__init__.py, tests/unit_tests/logic/modal/test_introspection_analysis.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_introspection_analysis.py -q
- Bundle: legal-ir/leanstral-evidence
- Goal id: LIR-LEANSTRAL-EVIDENCE
- Merge key: legal-ir-introspection-analysis
- Acceptance: Normalize deontic, frame-logic, TDFOL, knowledge-graph, event-calculus, temporal, provenance, decompiler, and prover gaps; cluster repeated disagreements by canonical semantic signature and owned code surface; rank clusters by held-out impact, recurrence, confidence, and formal severity rather than raw loss magnitude alone.

## PORTAL-LIRLS-007 Implement verifier-owned Lean theorem templates for legal semantics

- Status: todo
- Completion: manual
- Priority: P0
- Track: proof
- Depends on: PORTAL-LIRLS-002
- Outputs: ipfs_datasets_py/logic/modal/leanstral_theorems.py, tests/unit_tests/logic/modal/test_leanstral_theorems.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_theorems.py tests/unit_tests/logic/modal/test_leanstral.py -q
- Bundle: legal-ir/leanstral-proof
- Goal id: LIR-LEANSTRAL-PROOF
- Merge key: legal-ir-leanstral-theorem-registry
- Acceptance: Generate fixed theorem statements for modality, prohibition and permission, exception scope, temporal bounds, actor/action/object roles, source provenance, graph endpoint integrity, and compiler/decompiler round trips; allow Leanstral to supply only proof bodies and bind every theorem to canonical evidence hashes.

## PORTAL-LIRLS-008 Add structured Leanstral audit requests, responses, and content-addressed caching

- Status: completed
- Completion: manual
- Priority: P0
- Track: proof
- Depends on: PORTAL-LIRLS-005
- Outputs: ipfs_datasets_py/logic/modal/leanstral_audit.py, tests/unit_tests/logic/modal/test_leanstral_audit.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_audit.py tests/unit_tests/logic/modal/test_leanstral.py -q
- Bundle: legal-ir/leanstral-audit
- Goal id: LIR-LEANSTRAL-AUDIT
- Merge key: legal-ir-leanstral-audit-contract
- Acceptance: Require machine-readable audit output with classification, missing semantic rule, counterexample or witness, affected IR families, proposed compiler surface, confidence, proof obligation IDs, and abstention reason; cache by evidence, prompt, model, theorem-registry, and schema hashes; never treat malformed, stale, or unverified cache entries as accepted evidence.

## PORTAL-LIRLS-009 Verify every Leanstral audit against deterministic compilers and local proof tools

- Status: todo
- Completion: manual
- Priority: P0
- Track: proof
- Depends on: PORTAL-LIRLS-006, PORTAL-LIRLS-007, PORTAL-LIRLS-008
- Outputs: ipfs_datasets_py/logic/modal/leanstral_verifier.py, ipfs_datasets_py/logic/modal/leanstral.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py, tests/unit_tests/logic/modal/test_leanstral_verifier.py, tests/unit_tests/optimizers/test_prover_integration.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py tests/unit_tests/optimizers/test_prover_integration.py -q
- Bundle: legal-ir/leanstral-proof
- Goal id: LIR-LEANSTRAL-PROOF
- Merge key: legal-ir-leanstral-verifier
- Acceptance: Recompile referenced examples, check canonical hashes and source spans, run available Lean and bridge/prover checks with bounded per-prover timeouts, distinguish route availability from theorem validity, and emit accepted, rejected, unsupported, or timed-out outcomes without allowing an LLM assertion to substitute for a checker result.

## PORTAL-LIRLS-010 Aggregate verified audits into bounded compiler rule-gap reports

- Status: todo
- Completion: manual
- Priority: P0
- Track: synthesis
- Depends on: PORTAL-LIRLS-009
- Outputs: ipfs_datasets_py/logic/modal/leanstral_reporting.py, ipfs_datasets_py/logic/modal/synthesis.py, tests/unit_tests/logic/modal/test_leanstral_reporting.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_reporting.py tests/unit_tests/logic/modal/test_leanstral.py -q
- Bundle: legal-ir/leanstral-synthesis
- Goal id: LIR-LEANSTRAL-PROJECTION
- Merge key: legal-ir-leanstral-rule-gap-report
- Acceptance: Collapse duplicate audits into evidence-backed rule gaps, preserve supporting and conflicting examples, map each gap to one owned compiler/decompiler surface and focused validation set, reject free-form architecture tasks, and prioritize changes expected to improve held-out compiler IR metrics or formal validity.

## PORTAL-LIRLS-011 Project verified rule gaps into the existing program-synthesis TODO queue

- Status: todo
- Completion: manual
- Priority: P0
- Track: synthesis
- Depends on: PORTAL-LIRLS-010
- Outputs: ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py, ipfs_datasets_py/logic/modal/synthesis.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py -q
- Bundle: legal-ir/leanstral-supervisor
- Goal id: LIR-LEANSTRAL-PROJECTION
- Merge key: legal-ir-leanstral-todo-handoff
- Acceptance: Add Leanstral evidence to the existing queue rather than creating a parallel queue; emit narrow TODOs with evidence/spec/proof IDs, allowed paths, exact target metrics, counterexamples, validation commands, and dedup keys; enforce per-cycle and per-scope budgets and leave unverified audits in report-only state.

## PORTAL-LIRLS-012 Add isolated worktree, mutation, and held-out Pareto validation for projected changes

- Status: todo
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: PORTAL-LIRLS-004, PORTAL-LIRLS-009, PORTAL-LIRLS-011
- Outputs: ipfs_datasets_py/logic/modal/leanstral_validation.py, ipfs_datasets_py/logic/modal/leanstral.py, tests/unit_tests/logic/modal/test_leanstral_validation.py, tests/fixtures/logic/modal/leanstral_mutations.json
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py tests/unit_tests/logic/modal/test_leanstral.py -q
- Bundle: legal-ir/leanstral-validation
- Goal id: LIR-LEANSTRAL-VALIDATION
- Merge key: legal-ir-leanstral-pareto-gate
- Acceptance: Validate candidate diffs in disposable worktrees with allowed-path, syntax, focused-test, deterministic round-trip, theorem, graph, provenance, anti-copy, mutation, and frozen-holdout checks; accept only Pareto-safe changes within explicit CE/cosine deadbands and produce machine-readable rejection reasons suitable for rescue tasks.

## PORTAL-LIRLS-013 Add reversible modes, budgets, lag telemetry, and supervisor health reporting

- Status: todo
- Completion: manual
- Priority: P1
- Track: ops
- Depends on: PORTAL-LIRLS-011, PORTAL-LIRLS-012
- Outputs: ipfs_datasets_py/logic/modal/autoencoder_loop.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py, ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_reporting.py, tests/unit_tests/logic/modal/test_autoencoder_loop.py, tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_loop_contract.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_autoencoder_loop.py tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder_loop_contract.py -q
- Bundle: legal-ir/leanstral-supervisor
- Goal id: LIR-LEANSTRAL-ROLLOUT
- Merge key: legal-ir-leanstral-rollout-controls
- Acceptance: Add `off|export|shadow|seed|enforce` introspection modes, maximum audits and TODOs per cycle, target-scope filters, prover-confirmation requirements, cache counters, per-phase timing, and `state_to_compiler_patch_lag`; default to `off`, keep `enforce` fail-closed, and expose enough summary data to distinguish an alive loop from a productive one.

## PORTAL-LIRLS-014 Run a no-mutation shadow canary over the highest-impact disagreement clusters

- Status: todo
- Completion: manual
- Priority: P1
- Track: evaluation
- Depends on: PORTAL-LIRLS-013
- Outputs: scripts/ops/legal_ir/run_leanstral_shadow_canary.py, docs/implementation/reports/leanstral_shadow_canary.md, tests/unit_tests/logic/modal/test_leanstral_shadow_canary.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_shadow_canary.py -q; PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_shadow_canary.py --dry-run --max-clusters 50
- Bundle: legal-ir/leanstral-rollout
- Goal id: LIR-LEANSTRAL-ROLLOUT
- Merge key: legal-ir-leanstral-shadow-canary
- Acceptance: Audit up to 50 highest-impact clusters without queue seeding or source mutation; report cache use, audit validity, theorem outcomes, disagreement categories, projected TODO specificity, runtime, and estimated compiler impact; fail promotion if provenance, anti-copy, schema, or verifier guardrails are bypassed.

## PORTAL-LIRLS-015 Seed a five-task paired evaluation and publish the production promotion decision

- Status: todo
- Completion: manual
- Priority: P1
- Track: evaluation
- Depends on: PORTAL-LIRLS-014
- Outputs: scripts/ops/legal_ir/run_leanstral_seed_canary.py, docs/implementation/reports/leanstral_seed_canary.md, docs/implementation/runbooks/leanstral_legal_ir_rollout.md, tests/unit_tests/logic/modal/test_leanstral_seed_canary.py
- Validation: PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_seed_canary.py -q; PYTHONPATH=. python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5
- Bundle: legal-ir/leanstral-rollout
- Goal id: LIR-LEANSTRAL-ROLLOUT
- Merge key: legal-ir-leanstral-seed-canary
- Acceptance: Seed at most five verified tasks and compare them with a matched non-Leanstral control using compiler IR CE/cosine, learned IR-view metrics, proof and graph validity, anti-copy penalty, validation rejection rate, task-to-accepted-patch rate, cycle time, and state-to-patch lag; document rollback commands and permit broader rollout only when no hard guardrail regresses and compiler development throughput materially improves.

## Completion Criteria

This program is complete only when the shadow and seed canaries demonstrate
that autoencoder evidence reaches accepted deterministic compiler/decompiler
changes faster, while compiler IR metrics or formal coverage improve and no
provenance, anti-copy, structural, theorem, mutation, or held-out guardrail
regresses. A healthy provider call, a plausible Leanstral explanation, or a
high learned-view cosine is not sufficient by itself.

## Suggested Supervisor Invocation

Run from the `ipfs_datasets_py` repository root after reviewing the task board:

```bash
PYTHONPATH=../ipfs_accelerate_py:. python -m ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor \
  --todo-path docs/implementation/plans/LEANSTRAL_LEGAL_IR_COMPILER_TASKLIST.md \
  --task-prefix "## PORTAL-" \
  --state-dir workspace/agent-supervisor/leanstral-legal-ir \
  --state-prefix leanstral-legal-ir \
  --worktree-root workspace/agent-supervisor/leanstral-legal-ir/worktrees \
  --implement
```

Use `--once --no-implement` first to inspect dependency readiness without
starting an implementation worker.

## PORTAL-016 Resolve 1 preflight-conflicting backlogged worktree merges

- Status: completed
- Completion: manual
- Priority: P1
- Track: ops
- Fingerprint: cc6ea8fa964cffa02a91a118f2fcc26179e41d2c
- Dedupe key: reconciliation_guardrail:preflight_merge_conflict
- Depends on:
- Outputs: /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery, docs/implementation/plans/LEANSTRAL_LEGAL_IR_COMPILER_TASKLIST.md
- Validation: test -f /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery/2026-07-11-portal-016-reconciliation-cc6ea8fa964c.md
- Acceptance: Reconciliation guardrail filed this because 1 branch or worktree cleanup candidates are blocked by preflight_merge_conflict. Use evidence and the machine-readable reconciliation plan in /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery/2026-07-11-portal-016-reconciliation-cc6ea8fa964c.md, reconcile the dirty checkout or dirty worktree group deliberately, then rerun the supervisor cleanup/reconciliation pass and confirm that the blocked candidate count decreases.

## PORTAL-017 Resolve merge retry-budget failure for PORTAL-LIRLS-007

- Status: todo
- Completion: manual
- Priority: P1
- Track: ops
- Depends on: PORTAL-LIRLS-002
- Outputs: ipfs_datasets_py/logic/modal/leanstral_theorems.py, tests/unit_tests/logic/modal/test_leanstral_theorems.py, /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery
- Validation: test -f /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery/2026-07-11-portal-017-portal-lirls-007-merge-retry-budget.md
- Acceptance: Merge retry-budget guardrail filed this from repeated merge failures in PORTAL-LIRLS-007. Use evidence in /home/barberb/.local/state/ipfs_accelerate_py/leanstral-legal-ir-20260711T2244Z/discovery/2026-07-11-portal-017-portal-lirls-007-merge-retry-budget.md to fix the merge blocker, verify the intended implementation changes are committed in their owning repository or submodule, run `ipfs-accelerate-agent-merge-resolver --events-path ... --apply` when the conflict is semantic, then mark this repair task completed so the supervisor can release PORTAL-LIRLS-007 from strategy blocked_tasks.
