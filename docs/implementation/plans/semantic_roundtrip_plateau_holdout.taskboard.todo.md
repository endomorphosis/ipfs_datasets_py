# Semantic Round-Trip Plateau Holdout Taskboard (PLAT2)

Consumable by `ipfs_accelerate_py.agent_supervisor` with task prefix `## PLAT2-`.
Companion objectives: `semantic_roundtrip_plateau_holdout.objectives.md`.

## Objective

PLAT-000…091 broke the **five-pilot** det. plateau (0.088 → 0.0 e2e) using
residual → teacher → prover → supervisor → remeasure. This board generalizes
that loop to a **preregistered holdout** case set so improvements do not overfit
the pilot population.

Doctrine unchanged: optional methods are teachers/gates; production stays
typed_deontic → IR → deterministic realizer; Hammer/cvc5/Lean never have
semantic authority.

## Baseline lock (post-pilot)

- Pilot promotion decision: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json`
- Post-pilot pilot mean e2e: **0.0**
- Production arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`

## Parallel lanes

| Lane | Owns |
| --- | --- |
| `plat2-docs` | Plan seal |
| `plat2-residual` | Catalog generalization |
| `plat2-corpus` | Holdout fixture freeze |
| `plat2-packets` | Packet/materializer holdout support |
| `plat2-teachers` | Prover-gated teachers |
| `plat2-det-edits` | Det. compiler edit waves (may split per case) |
| `plat2-remeasure` | Holdout remeasure |

---

## PLAT2-000 Seal holdout plan artifacts

- Status: completed
- Completion: auto
- Priority: P0
- Track: plateau-holdout
- Depends on:
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md, config/semantic_roundtrip_plateau_holdout_scheduler.json
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md && test -f config/semantic_roundtrip_plateau_holdout_scheduler.json
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/docs
- Parallel lane: plat2-docs
- Resource class: cpu-small
- Resource stage: analysis
- Implementation timeout seconds: 1800
- Predicted files: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md, config/semantic_roundtrip_plateau_holdout_scheduler.json
- Interfaces: PlateauHoldoutPlan@1
- Conflict policy: Own holdout plan docs only.
- Preconditions: PLAT pilot promotion evidence exists.
- Effects: Supervisor can prepare/launch PLAT2 board.
- Evidence subset: holdout plan seal
- Acceptance: Objectives, taskboard, human plan, and scheduler config exist and name the residual→packet→prover→supervisor loop.

## PLAT2-010 Extend residual catalog for holdout populations

- Status: todo
- Completion: auto
- Priority: P0
- Track: residual
- Depends on: PLAT2-000
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/holdout_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/residual
- Parallel lane: plat2-residual
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/holdout_residual_catalog.json
- Interfaces: PlateauResidualCatalog@1
- Conflict policy: Extend residual_catalog without breaking sealed pilot validators used by PLAT-010 receipts.
- Preconditions: Pilot residual catalog module exists.
- Effects: Holdout residual catalogs can be built and CID-bound.
- Evidence subset: holdout residual catalog
- Acceptance: `build_plateau_residual_catalog` (or successor) accepts a preregistered case population path; pilot-only validation helpers remain; holdout catalog JSON written with case×facet residuals; unit tests cover both pilot seal and holdout path.

## PLAT2-020 Freeze holdout case fixtures

- Status: todo
- Completion: auto
- Priority: P0
- Track: corpus
- Depends on: PLAT2-000
- Outputs: tests/fixtures/semantic_roundtrip/holdout_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/corpus
- Parallel lane: plat2-corpus
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: tests/fixtures/semantic_roundtrip/holdout_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Interfaces: HoldoutCaseFixture@1
- Conflict policy: Own holdout fixtures; do not mutate pilot_cases.json semantics.
- Preconditions: Pilot cases fixture exists; selective-repair fixture cases may be reused as non-pilot starters.
- Effects: Holdout population preregistered before outcome inspection.
- Evidence subset: holdout fixture freeze
- Acceptance: At least three cases beyond the five pilots **or** a documented hybrid set including selective-repair activation cases (`missing_temporal`, `low_confidence_object`, `contradictory_modality`) plus any additional legal cases available; stable IDs; gold IR or explicit score bindings; digest recorded in docs.

## PLAT2-030 Holdout packets and materializer

- Status: todo
- Completion: auto
- Priority: P0
- Track: packets
- Depends on: PLAT2-010, PLAT2-020
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/packets
- Parallel lane: plat2-packets
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Extend packet modules; preserve pilot packet tests.
- Preconditions: Holdout residual catalog + fixtures available.
- Effects: Holdout residuals become implementable supervisor tasks when admitted.
- Evidence subset: holdout packet materialize
- Acceptance: Packets build for holdout residuals; reject/timeout not implementable; materializer emits tasks with det.-only predicted files and validation commands; unit tests pass.

## PLAT2-040 Prover-gated teachers on holdout residuals

- Status: todo
- Completion: auto
- Priority: P1
- Track: teachers
- Depends on: PLAT2-030
- Outputs: workspace/benchmarks/semantic-roundtrip-compositions/holdout_leanstral_proposal_receipts.json, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/teachers
- Parallel lane: plat2-teachers
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 10800
- Predicted files: workspace/benchmarks/semantic-roundtrip-compositions/holdout_leanstral_proposal_receipts.json, benchmarks/semantic_roundtrip/plateau_leanstral_proposals.py
- Interfaces: StructuralAdmission@1, ModelOutputRecovery@1
- Conflict policy: Teacher-only; dry-run fixtures required if live model unavailable.
- Preconditions: Packets + residual catalog for holdout exist.
- Effects: Admitted proposals feed edit waves; rejects mint obligations.
- Evidence subset: holdout teacher receipts
- Acceptance: Dry-run path always passes tests; StructuralAdmission applied; only triggered fields change; receipts JSON CID-bindable.

## PLAT2-050 Det. compiler edit waves for holdout residuals

- Status: todo
- Completion: auto
- Priority: P0
- Track: det-compiler
- Depends on: PLAT2-030
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, workspace/benchmarks/semantic-roundtrip-compositions/holdout_edit_wave_receipts/, tests/unit/benchmarks/semantic_roundtrip/
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=20
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/compiler-edits
- Parallel lane: plat2-det-edits
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 14400
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/holdout_edit_wave_receipts/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: May edit typed_deontic; serialize conflicting hotspots; do not introduce LLM runtime.
- Preconditions: At least one implementable holdout packet or residual-driven obligation exists.
- Effects: Det. path improves or holds on holdout cases.
- Evidence subset: holdout edit waves
- Acceptance: Edit-wave receipts per holdout case with non-zero residual; pilot cases remain non-regressed (re-score pilots mean e2e still 0.0); unit tests pass.

## PLAT2-060 Holdout remeasure and promotion gates

- Status: todo
- Completion: auto
- Priority: P0
- Track: remeasure
- Depends on: PLAT2-050
- Outputs: docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_promotion_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v1
- Bundle: semantic-roundtrip/plateau-holdout/remeasure
- Parallel lane: plat2-remeasure
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 14400
- Predicted files: docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_promotion_decision.json
- Interfaces: EvalRepairMatrixReport@1
- Conflict policy: Own holdout snapshot paths; never rewrite 2026-07-27 replacement report.
- Preconditions: Holdout edit waves merged or explicit no-op receipts.
- Effects: Operators know if det. path holds on holdout and whether further promotion claims are justified.
- Evidence subset: holdout remeasure
- Acceptance: Per-case loss tables for holdout; pilots re-checked non-regressed; paired bootstrap vs declared baseline; promotion true only if CI high &lt; 0 and full gates pass; otherwise named next residuals.

---

## Dependency DAG

```text
PLAT2-000
  ├─ PLAT2-010 residual ──┐
  └─ PLAT2-020 corpus ────┼─ PLAT2-030 packets ─┬─ PLAT2-040 teachers (optional parallel)
                          │                     └─ PLAT2-050 det edits ── PLAT2-060 remeasure
```

## Launch sketch

```bash
export PYTHONPATH=ipfs_accelerate_py:.
export IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER=grok
RUNTIME=/var/tmp/hssl-srt-plateau-holdout
REPO=/var/tmp/hssl-semantic-roundtrip-20260726

python -m benchmarks.semantic_roundtrip_scheduler prepare \
  --repo-root "$REPO" \
  --config-path "$REPO/config/semantic_roundtrip_plateau_holdout_scheduler.json" \
  --runtime-root "$RUNTIME" \
  --taskboard-path "$REPO/docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md"

python -m ipfs_accelerate_py.agent_supervisor.bundle_supervisor \
  --bundle-index-path "$RUNTIME/bundles/index.json" \
  --repo-root "$REPO" --state-root "$RUNTIME/state" \
  --worktree-root "$RUNTIME/worktrees" --log-dir "$RUNTIME/logs" \
  --task-prefix '## PLAT2-' --max-lanes 2 --max-task-attempts 5 \
  --merge-target-branch benchmark/semantic-roundtrip-20260726 \
  --worktree-submodule-path ipfs_accelerate_py --implement --start
```
