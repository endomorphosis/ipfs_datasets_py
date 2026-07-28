# Semantic Round-Trip Plateau Holdout Taskboard (PLAT2)

Consumable by `ipfs_accelerate_py.agent_supervisor` with task prefix `## PLAT2-`.
Companion objectives: `semantic_roundtrip_plateau_holdout.objectives.md`.

## Objective

PLAT-000…091 broke the **five-pilot** deterministic plateau (0.088 → 0.0 e2e)
using residual → teacher → prover → supervisor → remeasure. This board
generalizes that loop without turning the evaluation population into a tuning
oracle:

1. a visible **repair-development** population supplies residuals, packets,
   ablations, and deterministic edit decisions;
2. a separately authored, access-controlled **blind holdout** remains outside
   the tuning worktree and default agent context until one candidate is frozen;
3. the blind holdout is evaluated once under an append-only access receipt.

Core production doctrine remains: production stays typed_deontic → IR → deterministic
realizer. Autoencoder/spaCy diagnostics, SyMAI orchestration, and Leanstral
proposals are heterogeneous advisory roles, not interchangeable candidates.
Hammer/cvc5/Lean are structural gates with `semantic_authority: false`.
Semantic e2e loss and preregistered holdout gates remain promotion authority.

## Baseline lock (post-pilot)

- Pilot promotion decision: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json`
- Post-pilot pilot mean e2e: **0.0**
- Production arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`
- Blind-holdout outcome status at launch: **sealed_unopened**
- The post-PLAT source tree, metrics, aggregation, noninferiority margin, and
  repair-development baseline are frozen by PLAT2-025 before any edit wave.

## Evidence and access doctrine

- Repository queries, spaCy/AE diagnostics, tests, and runtime traces are
  bounded observations, not mathematical proofs.
- Leanstral/SyMAI/model outputs are proposals or orchestration evidence, never
  merge or semantic authority.
- Hammer/cvc5/Lean receipts may admit declared structural properties only.
- Every packet and receipt binds the source tree, case-population digest,
  residual catalog, assumptions, toolchain/policy identity, and invalidators.
- Blind sources and gold bindings never enter prompts, packets, caches, or
  agent worktrees. Digests and custodian access receipts are sufficient here;
  ZK is out of scope absent a separate approved threat model.

## Parallel lanes

| Lane | Owns |
| --- | --- |
| `plat2-docs` | Plan seal |
| `plat2-residual` | Catalog generalization |
| `plat2-corpus` | Repair-development + blind-holdout split/custody |
| `plat2-baseline` | Baseline, metrics, and failure taxonomy freeze |
| `plat2-packets` | Obligation-first packet/materializer support |
| `plat2-interventions` | Method roles, capabilities, and ablation plan |
| `plat2-teachers` | Optional evidence-gated teachers |
| `plat2-det-edits` | Det. compiler edit waves (may split per case) |
| `plat2-freeze` | Candidate freeze, attribution, holdout authorization |
| `plat2-remeasure` | One-shot blind-holdout evaluation |

---

## PLAT2-000 Seal holdout plan artifacts

- Status: completed
- Completion: auto
- Priority: P0
- Track: plateau-holdout
- Depends on:
- Goal id: PLAT2-G000
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md, config/semantic_roundtrip_plateau_holdout_scheduler.json
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md && test -f config/semantic_roundtrip_plateau_holdout_scheduler.json
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/docs
- Parallel lane: plat2-docs
- Resource class: cpu-small
- Resource stage: analysis
- Implementation timeout seconds: 1800
- Predicted files: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md, config/semantic_roundtrip_plateau_holdout_scheduler.json
- Interfaces: PlateauHoldoutPlan@2
- Conflict policy: Own holdout plan docs only.
- Preconditions: PLAT pilot promotion evidence exists.
- Effects: Supervisor can prepare/launch PLAT2 without exposing the blind holdout to implementation lanes.
- Evidence subset: holdout plan seal
- Acceptance: Objectives, taskboard, human plan, and scheduler config exist; all distinguish repair-development from blind holdout, require candidate freeze before audited holdout access, preserve evidence-tier authority, and name the residual→packet→structural-gate→supervisor→freeze→one-shot-evaluation loop.

## PLAT2-010 Extend residual catalog for preregistered populations

- Status: completed
- Completion: auto
- Priority: P0
- Track: residual
- Depends on: PLAT2-000
- Goal id: PLAT2-G010
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/residual
- Parallel lane: plat2-residual
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_residual_catalog.json
- Interfaces: PlateauResidualCatalog@1
- Conflict policy: Extend residual_catalog without breaking sealed pilot validators used by PLAT-010 receipts.
- Preconditions: Pilot residual catalog module exists.
- Effects: Repair-development residuals become queryable inputs while blind-holdout residuals remain inaccessible before candidate freeze.
- Evidence subset: repair development residual catalog
- Acceptance: `build_plateau_residual_catalog` (or successor) accepts an explicitly typed pilot, repair_development, or authorized_blind_evaluation population; pilot-only validation helpers remain; normal supervisor/packet paths reject blind sources, gold bindings, blind residuals, and unauthorized evaluator mode; repair-development catalog records case×facet residuals, baseline/tree/population CIDs, status, assumptions, and provenance; unsupported/not_measured/runtime_failed remain distinct from semantic scores; tests cover pilot seal, repair-development generation, and premature blind-access rejection.

## PLAT2-020 Freeze repair-development and blind-holdout populations

- Status: completed
- Completion: auto
- Priority: P0
- Track: corpus
- Depends on: PLAT2-000
- Goal id: PLAT2-G020
- Outputs: benchmarks/semantic_roundtrip/holdout_protocol.py, tests/fixtures/semantic_roundtrip/repair_dev_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/corpus
- Parallel lane: plat2-corpus
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/holdout_protocol.py, tests/fixtures/semantic_roundtrip/repair_dev_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Interfaces: SemanticRoundtripPopulationManifest@1, SemanticRoundtripHoldoutSeal@1, HoldoutAccessAudit@1
- Conflict policy: Own PLAT2 population/seal artifacts; do not mutate pilot_cases.json or place private blind sources/gold in the repository, tuning worktree, or default context.
- Preconditions: Pilot cases fixture exists; an independent custodian can provide a blind corpus outside the tuning worktree.
- Effects: Visible repair-development cases support tuning while an independently sealed population can support one out-of-sample decision.
- Evidence subset: holdout fixture freeze
- Acceptance: Freeze disjoint pilot, repair_development, and blind_holdout manifests before repair-development outcomes are inspected; repair-development fixtures may include selective-repair cases and expose source/gold for diagnosis, while blind sources/gold live only in an access-controlled custodian store outside agent worktrees; public blind seal exposes schema, count/strata, aggregate commitments to the ordered private source/gold/provenance manifests, and seal CID but no per-case digest, source text, labels, gold IR, or semantic hints; exact, normalized, provenance, and preregistered near-duplicate checks reject cross-split leakage and prompt-example overlap; an append-only access ledger rejects access before PLAT2-055 authorization, repeated access, or post-access tuning; sample size/strata follow a preregistered precision or power justification, and an underpowered population is explicitly exploratory and cannot authorize promotion.

## PLAT2-025 Freeze repair-development baseline and experiment contract

- Status: completed
- Completion: auto
- Priority: P0
- Track: baseline
- Depends on: PLAT2-010, PLAT2-020
- Goal id: PLAT2-G025
- Outputs: benchmarks/semantic_roundtrip/holdout_baseline.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json, docs/benchmarks/semantic_roundtrip_plateau2_baseline.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/baseline
- Parallel lane: plat2-baseline
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/holdout_baseline.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json, docs/benchmarks/semantic_roundtrip_plateau2_baseline.md
- Interfaces: Plateau2ExperimentContract@1, EvalRepairMatrixReport@1
- Conflict policy: Own PLAT2 baseline/protocol artifacts; do not inspect blind outcomes or change sealed PLAT reports.
- Preconditions: Population split/seal and generalized residual catalog available.
- Effects: All later edit, ablation, and holdout claims share a reproducible pre-edit reference and frozen decision rules.
- Evidence subset: repair development baseline
- Acceptance: Before edit waves, bind the post-PLAT baseline git tree and recursive gitlinks, deterministic arm/config, environment/toolchain, population and residual CIDs, metric/facet definitions, per-case-first aggregation, paired-bootstrap method, confidence level/count, noninferiority margin, selection/promotion rules, packet token budget, capability policy, and failure taxonomy; run the deterministic baseline on pilots and repair-development only; record per-case and per-facet forward/cycle/e2e loss, coverage, polarity, source-copy gates, and failure clusters with semantic_scored/not_measured/runtime_failed/unsupported status; blind seal remains unopened with zero access receipts; protocol changes after this task mint a new experiment identity and retire downstream receipts.

## PLAT2-030 Repair-development packets and materializer

- Status: completed
- Completion: auto
- Priority: P0
- Track: packets
- Depends on: PLAT2-025
- Goal id: PLAT2-G030
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_packet_context_metrics.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/packets
- Parallel lane: plat2-packets
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_packet_context_metrics.json
- Interfaces: PlateauResidualClaim@1, PlateauCodexPacket@1, Plateau2ExperimentContract@1, StructuralAdmission@1
- Conflict policy: Extend packet modules; preserve pilot packet tests.
- Preconditions: Frozen experiment contract and repair-development residual catalog available.
- Effects: Repair-development residuals become small, provenance-bound supervisor tasks without disclosing blind or unrelated source; an optional CBP bridge may project claim/receipt handles without becoming a PLAT2 dependency or semantic authority.
- Evidence subset: repair development packet materialize
- Acceptance: Packets accept repair-development residuals only and bind baseline/tree/population/catalog CIDs, residual facets, assumptions, evidence status, structural-obligation IDs, invalidators, acceptance IDs, and provenance; invariant context contains the failing facet/counterexample, relevant canonical spec/rule handles, changed AST/dependency slice, pilot-regression requirements, and proof/receipt digests—not full-repository dumps, gold target bodies, blind IDs/sources/gold, raw solver traces, or untrusted instructions; optional evidence uses content-addressed expansion handles and records omitted-handle coverage plus token count against the frozen budget; stale bindings, reject/timeout/unsupported/not_measured, or missing required evidence set implementable=false; materializer emits deterministic-only predicted files and validation commands for unit tests, repair-development/pilot metrics, structural gates, and packet revalidation.

## PLAT2-035 Preregister intervention roles, capabilities, and ablations

- Status: completed
- Completion: auto
- Priority: P0
- Track: interventions
- Depends on: PLAT2-025
- Goal id: PLAT2-G035
- Outputs: benchmarks/semantic_roundtrip/holdout_interventions.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json, docs/benchmarks/semantic_roundtrip_plateau2_interventions.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/interventions
- Parallel lane: plat2-interventions
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/holdout_interventions.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json, docs/benchmarks/semantic_roundtrip_plateau2_interventions.md
- Interfaces: Plateau2InterventionRegistry@1, SemanticRoundtripCapabilityRecord@1
- Conflict policy: Classification/plan only; do not change production defaults, optional adapters, sealed PLAT results, or inspect blind inputs/outcomes.
- Preconditions: Frozen experiment contract and PLAT/SRT method evidence available.
- Effects: Each residual cluster has an outcome-independent minimal intervention and attribution plan instead of an incoherent Cartesian product.
- Evidence subset: repair development intervention registry
- Acceptance: Registry classifies the deterministic compiler/IR/decompiler as the edit target, autoencoder as bounded causal guidance only when its reviewed adapter is scored_supported, spaCy as non-authoritative diagnostics, SyMAI as orchestration/routing only, Leanstral as a proposal teacher, and Hammer/cvc5/Lean as declared structural gates; every method has exact version/model/route/toolchain identity and semantic_scored/not_measured/runtime_failed/terminal_unsupported/not_selected status backed by PLAT evidence or a bounded capability smoke; health-only probes cannot establish model inference; each repair-development residual maps to the smallest preregistered intervention/negative control and per-wave/cumulative ablation needed for attribution; full matrix reruns require an explicit evidence-backed override; no blind data or outcome-dependent selection is permitted.

## PLAT2-040 Optional evidence-gated teachers on repair-development residuals

- Status: completed
- Completion: auto
- Priority: P1
- Track: teachers
- Depends on: PLAT2-030, PLAT2-035
- Goal id: PLAT2-G040
- Outputs: workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_teacher_receipts.json, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/teachers
- Parallel lane: plat2-teachers
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 10800
- Predicted files: workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_teacher_receipts.json, benchmarks/semantic_roundtrip/plateau_leanstral_proposals.py
- Interfaces: Plateau2InterventionRegistry@1, StructuralAdmission@1, ModelOutputRecovery@1
- Conflict policy: Teacher-only; dry-run fixtures required if live model unavailable.
- Preconditions: Repair-development packets and frozen intervention registry exist; blind seal remains unopened.
- Effects: Eligible advisory methods may propose bounded repair-development changes; every rejection or missing capability remains explicit evidence.
- Evidence subset: repair development teacher receipts
- Acceptance: Execute only methods/residuals preregistered as eligible; direct/SyMAI route identities remain distinct and SyMAI cannot receive proof credit; Leanstral calls prove real inference occurred and record typed blank/schema/polarity/empty_rules/timeout/retry-exhausted outcomes; spaCy/AE outputs remain diagnostics/guidance at their declared status; only triggered fields may change; model/solver outputs remain candidate evidence and `semantic_authority: false`; StructuralAdmission checks only declared structural properties and cannot substitute for e2e loss; dry-run/negative controls always pass; receipts bind packet, tree, intervention, provider/toolchain, assumptions, and status CIDs; no blind case, source, gold, residual, prompt example, or cache namespace is accessed.

## PLAT2-050 Deterministic compiler edit waves on repair-development

- Status: completed
- Completion: auto
- Priority: P0
- Track: det-compiler
- Depends on: PLAT2-030, PLAT2-035
- Goal id: PLAT2-G050
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_edit_wave_receipts/, tests/unit/benchmarks/semantic_roundtrip/
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=20
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/compiler-edits
- Parallel lane: plat2-det-edits
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 14400
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_edit_wave_receipts/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: May edit typed_deontic; serialize conflicting hotspots; do not introduce LLM runtime.
- Preconditions: At least one implementable repair-development packet exists; optional PLAT2-040 receipts are consumed only when available and applicable.
- Effects: One bounded deterministic rule hypothesis at a time is evaluated on repair-development while pilots remain regression controls.
- Evidence subset: repair development edit waves
- Acceptance: Each isolated wave cites packet/intervention/baseline/tree CIDs, names one residual cluster and deterministic hypothesis, records exact changed symbols/files, assumptions, tests, structural receipts, context tokens, provider calls, and before/after per-case/per-facet repair-development plus pilot metrics; rejected, unsupported, stale, or optional-teacher-missing evidence cannot be presented as an admitted proposal, but a reviewed residual-only deterministic hypothesis may proceed through its own tests and structural gates; shared-hotspot edits serialize and every wave is independently revertible; no optional runtime enters production; pilot mean e2e remains 0.0 with all coverage/polarity/source-copy gates passing; no blind data or outcomes are accessed.

## PLAT2-055 Freeze candidate, attribution evidence, and holdout authorization

- Status: completed
- Completion: auto
- Priority: P0
- Track: candidate-freeze
- Depends on: PLAT2-050
- Goal id: PLAT2-G055
- Outputs: benchmarks/semantic_roundtrip/holdout_candidate_freeze.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_candidate_freeze.json, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_authorization.json, docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/freeze
- Parallel lane: plat2-freeze
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/holdout_candidate_freeze.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_candidate_freeze.json, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_authorization.json, docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md
- Interfaces: Plateau2CandidateFreeze@1, SemanticRoundtripHoldoutAuthorization@1
- Conflict policy: Freeze/evaluation authority only; do not edit compiler, packets, prompts, metrics, populations, sealed PLAT artifacts, or private holdout.
- Preconditions: All selected deterministic edit waves terminal; repair-development/pilot evidence complete; blind seal still unopened.
- Effects: Exactly one immutable candidate and one comparison protocol may cross the blind-holdout boundary.
- Evidence subset: plateau2 candidate freeze
- Acceptance: Replay each isolated edit wave and the cumulative candidate on identical repair-development and pilot cases; report per-wave marginal and cumulative deltas, interactions, first-pass/eventual repair success, accepted-patch regressions, structural-gate coverage, context tokens, provider calls, and cost without using blind data; select zero or one candidate using the frozen PLAT2-025 rules; bind baseline and candidate commits/recursive gitlinks, compiler/realizer code, configs, metrics, aggregation/bootstrap/noninferiority rules, intervention registry, packets, prompts, provider/model/toolchain identities, environment, tests, population/seal CIDs, and all thresholds; authorization is emitted only when the blind seal has zero prior access, pilot and required gates pass, evidence is complete, and a candidate is frozen; after authorization any code/config/prompt/threshold/population change invalidates it and requires a new experiment identity and fresh blind holdout rather than retuning against this one.

## PLAT2-060 One-shot blind-holdout evaluation and decision

- Status: blocked
- Blocked reason: One-shot evaluation ran at 2026-07-28T08:58:44.684+00:00 (54 tests passed); supervisor discarded the worktree before merge. Blind seal opened — do not retry or re-run the holdout. Operator recovery (2026-07-28): landed `holdout_evaluation.py` + tests on `benchmark/semantic-roundtrip-20260726` (commit 65bc28928; suite re-verified 54 passed). Present on tree: evaluation module, tests, remeasure JSON, results MD, promotion decision JSON. Intentionally not reconstructed: `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_access_ledger.json` (one-shot access ledger). Keep blocked until operator accepts 5/6 outputs without ledger (or recovers a genuine ledger receipt without re-opening blind data); then mark completed.
- Completion: auto
- Priority: P0
- Track: remeasure
- Depends on: PLAT2-055
- Goal id: PLAT2-G060
- Outputs: benchmarks/semantic_roundtrip/holdout_evaluation.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_access_ledger.json, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_promotion_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py -q
- Board namespace: semantic-roundtrip-plateau-holdout-v2
- Bundle: semantic-roundtrip/plateau-holdout/remeasure
- Parallel lane: plat2-remeasure
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 14400
- Predicted files: benchmarks/semantic_roundtrip/holdout_evaluation.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_access_ledger.json, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md, docs/performance_snapshots/2026-07-28_semantic_roundtrip_holdout_promotion_decision.json
- Interfaces: SemanticRoundtripHoldoutAuthorization@1, HoldoutAccessAudit@1, EvalRepairMatrixReport@1
- Conflict policy: Own holdout snapshot paths; never rewrite 2026-07-27 replacement report.
- Preconditions: Valid PLAT2-055 candidate freeze/authorization; blind seal unopened; independent custodian/evaluator available.
- Effects: Operators receive one honest out-of-sample comparison without feeding blind outcomes back into the same candidate.
- Evidence subset: holdout remeasure
- Acceptance: Custodian grants one path-free, append-only access receipt only after validating authorization and frozen identities; evaluation runtime may receive blind source text and scorer may receive gold, but implementation agents, prompts, packets, teachers, caches, and tuning worktrees receive neither gold nor blind diagnostics; run frozen baseline and candidate on identical blind cases under isolated namespaces and the preregistered per-case-first paired analysis; publish terminal coverage, per-case/facet forward/cycle/e2e loss, coverage/polarity/source-copy gates, paired delta and confidence interval, structural receipts as separate non-semantic evidence, resource/context summaries, all missingness, and access-ledger CID; `improvement_confirmed` requires CI high &lt; 0 plus all gates, `generalization_confirmed_no_improvement` requires the predeclared noninferiority rule plus no regressions and makes no improvement claim, and all other outcomes decline promotion; no code, prompt, threshold, method selection, or rerun changes after access; post-hoc residuals may seed a new board only with a newly authored blind population.

---

## Dependency DAG

```text
PLAT2-000
  ├─ PLAT2-010 residual ─────────┐
  └─ PLAT2-020 split + seal ─────┴─ PLAT2-025 baseline
                                      ├─ PLAT2-030 packets ─────────────┐
                                      └─ PLAT2-035 interventions ───────┤
                                                                          ├─ PLAT2-040 teachers (optional)
                                                                          └─ PLAT2-050 det edits
                                                                                 └─ PLAT2-055 candidate freeze
                                                                                        └─ PLAT2-060 one-shot blind evaluation
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

python -m ipfs_accelerate_py.agent_supervisor.objectives.bundle_supervisor \
  --bundle-index-path "$RUNTIME/bundles/index.json" \
  --repo-root "$REPO" --state-root "$RUNTIME/state" \
  --worktree-root "$RUNTIME/worktrees" --log-dir "$RUNTIME/logs" \
  --task-prefix '## PLAT2-' --max-lanes 2 --max-task-attempts 5 \
  --merge-target-branch benchmark/semantic-roundtrip-20260726 \
  --worktree-submodule-path ipfs_accelerate_py --implement --start
```

## Explicit non-goals

- Exposing blind source, gold, residuals, or diagnostics to implementation agents
- Tuning on the population later used for the out-of-sample decision
- Re-running the same blind holdout after observing its outcome
- Treating query results, diagnostics, tests, model proposals, or structural
  receipts as semantic-loss authority
- Promoting autoencoder, spaCy, SyMAI, or Leanstral into the deterministic
  production runtime without a separately preregistered measured program
- Full Cartesian method reruns without an evidence-backed override
- ZK implementation without a distinct private-witness threat model
- Rewriting sealed PLAT/SRT reports
