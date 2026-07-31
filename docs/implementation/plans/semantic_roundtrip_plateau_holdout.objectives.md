# Semantic Round-Trip Plateau Holdout Objective Heap (PLAT2)

Companion executable board:
`docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md`
(task prefix `## PLAT2-`).

## Context from PLAT-000…091 (complete)

Pilot plateau-break succeeded on the sealed five-case population:

- Frozen mean e2e ≈ **0.088** → remeasured **0.000** on all five pilots
- Production path remains **typed_deontic → IR → deterministic realizer**
- Optional methods remain **teachers / gates** only
- Loop: residual catalog → teachers → Hammer/cvc5/Lean admit → Codex packet →
  agent supervisor det. edits → remeasure with CI high &lt; 0

## North star (this wave)

**Generalize the improvement loop without adaptive holdout leakage:** use a
visible repair-development population to diagnose residuals and choose one
deterministic candidate, then evaluate that frozen candidate once on an
independently authored blind holdout outside agent worktrees. Theorem-prover
receipts remain structural gates; semantic e2e loss remains the decision metric.

## Goal tree

```text
PLAT2-G000  Holdout residual loop for det. path
├── PLAT2-G010  Extend residual catalog for typed populations
├── PLAT2-G020  Repair-development / blind-holdout split and custody
├── PLAT2-G025  Baseline, metrics, failure taxonomy, and experiment freeze
├── PLAT2-G030  Obligation-first repair-development packets
├── PLAT2-G035  Method roles, capabilities, and ablation plan
├── PLAT2-G040  Optional evidence-gated teachers on repair-development
├── PLAT2-G050  Deterministic edit waves on repair-development
├── PLAT2-G055  Candidate freeze, attribution, and holdout authorization
└── PLAT2-G060  One-shot blind-holdout evaluation and decision
```

## Parallelism

- G010 and G020 can run in parallel after G000 seal
- G025 depends on G010+G020
- G030 and G035 can run in parallel after G025
- G040 is an optional provider lane after G030+G035
- G050 may split by deterministic hypothesis after G030+G035; optional G040
  receipts are consumed only when applicable
- G055 freezes one candidate after G050
- G060 is the only blind-access task and depends on G055 authorization

## Normative constraints

- Do not rewrite immutable 2026-07-27 replacement promotion report
- Do not expose blind sources, gold, residuals, or diagnostics to agents, prompts,
  packets, teachers, caches, or tuning worktrees
- Do not tune or rerun after blind access; a new attempt needs a new blind corpus
- Do not promote spaCy / AE / Leanstral / SyMAI to production without a separate
  preregistered measured program
- Hammer/cvc5/Lean: admission only (`semantic_authority: false`)
- Queries/diagnostics/tests are bounded observations; model outputs are
  candidates; neither class is a kernel proof or semantic-loss authority
- Pilot population PLAT results remain sealed historical evidence
- Repair-development and blind populations, metrics, margins, interventions,
  and candidate selection rules must be preregistered before outcome inspection
- Digests and access receipts are sufficient; ZK is out of scope without a
  separate approved private-witness threat model

## PLAT2-G000 Holdout residual loop for det. path

- Status: active
- Parent:
- Priority: P0
- Track: plateau-holdout
- Bundle: semantic-roundtrip/plateau-holdout/root
- Goal: Run residual→packet→structural-gate→supervisor on repair-development, freeze one deterministic candidate, then execute one audited comparison on a separately sealed blind holdout.
- Evidence: PLAT2EV000ROOT
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md, config/semantic_roundtrip_plateau_holdout_scheduler.json
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md
- Acceptance: Board is schedulable; doctrine references PLAT pilot success, separates repair-development from blind evaluation, requires candidate freeze and audited single-use access, distinguishes evidence authority, and forbids optional runtime promotion without a separate measured program.
- Gap task: Execute child goals via parallel lanes.

## PLAT2-G010 Extend residual catalog for typed populations

- Status: active
- Parent: PLAT2-G000
- Priority: P0
- Track: residual
- Bundle: semantic-roundtrip/plateau-holdout/residual
- Goal: Generalize residual_catalog for explicitly typed pilot, repair_development, and authorized_blind_evaluation populations while rejecting blind data on normal supervisor paths.
- Evidence: PLAT2EV010CAT
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Acceptance: Pilot validators remain valid; repair-development catalog binds tree/population/baseline CIDs, case×facet residuals, status, assumptions, and provenance; unsupported/not_measured/runtime_failed stay distinct; blind generation requires post-freeze evaluator authorization and premature blind access fails closed.
- Conflict policy: Own residual_catalog extensions; do not break PLAT-010 pilot receipt validation.

## PLAT2-G020 Repair-development / blind-holdout split and custody

- Status: active
- Parent: PLAT2-G000
- Priority: P0
- Track: corpus
- Bundle: semantic-roundtrip/plateau-holdout/corpus
- Goal: Freeze disjoint pilot, visible repair-development, and access-controlled blind-holdout populations with leakage checks and append-only access audit.
- Evidence: PLAT2EV020CORP
- Outputs: benchmarks/semantic_roundtrip/holdout_protocol.py, tests/fixtures/semantic_roundtrip/repair_dev_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
- Acceptance: Repair-development source/gold may be visible for diagnosis; blind source/gold remain in an independent custodian store outside repo/tuning worktrees; public blind seal exposes count/strata and aggregate commitments to ordered private content/provenance manifests but no per-case digests or semantic hints; exact/normalized/provenance/near-copy and prompt-overlap checks pass; access before G055, repeated access, and post-access tuning fail closed; sample size has a frozen precision/power justification and underpowered evidence cannot promote.
- Conflict policy: Own PLAT2 population/seal contracts only; do not mutate pilots or commit private blind content.

## PLAT2-G025 Baseline, metrics, failure taxonomy, and experiment freeze

- Status: active
- Parent: PLAT2-G000, PLAT2-G010, PLAT2-G020
- Priority: P0
- Track: baseline
- Bundle: semantic-roundtrip/plateau-holdout/baseline
- Goal: Pin the post-PLAT source/config/environment and preregister metrics, aggregation, uncertainty, noninferiority, token budget, status taxonomy, and decision rules before edit waves.
- Evidence: PLAT2EV025BASE
- Outputs: benchmarks/semantic_roundtrip/holdout_baseline.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json, docs/benchmarks/semantic_roundtrip_plateau2_baseline.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Acceptance: Bind baseline git tree/gitlinks, arm/config, toolchain/environment, population/residual CIDs, facet/e2e metrics, per-case-first aggregation, bootstrap parameters, margin, promotion rules, packet budget, and capability/failure taxonomy; score pilots and repair-development only with per-case/facet gates and failure clusters; blind seal remains unopened; any protocol change retires downstream receipts under a new identity.
- Conflict policy: Own PLAT2 baseline/protocol artifacts; never inspect blind outcomes or rewrite PLAT.

## PLAT2-G030 Repair-development packets + materializer

- Status: active
- Parent: PLAT2-G000, PLAT2-G025
- Priority: P0
- Track: packets
- Bundle: semantic-roundtrip/plateau-holdout/packets
- Goal: Emit provenance-bound, obligation-first PlateauCodexPacket@1 records for repair-development residuals and materialize minimal deterministic supervisor tasks.
- Evidence: PLAT2EV030PKT
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_packet_context_metrics.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Acceptance: Packet binds baseline/tree/population/catalog CIDs, residual facet/counterexample, assumptions, evidence status, structural obligations, invalidators, acceptance IDs, relevant spec/rule and changed AST/dependency handles, and pilot regressions; blind data, gold bodies, full-repo dumps, raw solver traces, and untrusted instructions are excluded; expansion handles and omitted coverage are auditable under the frozen token budget; stale/reject/timeout/unsupported/not_measured packets are non-implementable; predicted files and validation commands remain deterministic compiler/realizer/tests/metrics/gates only.
- Conflict policy: Extend existing packet modules without weakening pilot contracts.

## PLAT2-G035 Method roles, capabilities, and ablation plan

- Status: active
- Parent: PLAT2-G000, PLAT2-G025
- Priority: P0
- Track: interventions
- Bundle: semantic-roundtrip/plateau-holdout/interventions
- Goal: Map each heterogeneous method to its measured role and each repair-development residual to the smallest preregistered intervention, negative control, and attribution plan.
- Evidence: PLAT2EV035INT
- Outputs: benchmarks/semantic_roundtrip/holdout_interventions.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json, docs/benchmarks/semantic_roundtrip_plateau2_interventions.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_interventions.py tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py -q
- Acceptance: Deterministic compiler is edit target; AE is causal guidance only when qualified; spaCy is diagnostic; SyMAI is orchestration; Leanstral is proposal teacher; Hammer/cvc5/Lean are structural gates; exact identities and semantic_scored/not_measured/runtime_failed/terminal_unsupported/not_selected status are evidence-backed; health-only is not model inference; residual mappings and per-wave/cumulative ablations are frozen without blind access; full matrix reruns require explicit override.
- Conflict policy: Plan/classification only; do not change production routes, optional adapters, or sealed PLAT evidence.

## PLAT2-G040 Optional evidence-gated teachers on repair-development

- Status: active
- Parent: PLAT2-G000, PLAT2-G030, PLAT2-G035
- Priority: P1
- Track: teachers
- Bundle: semantic-roundtrip/plateau-holdout/teachers
- Goal: Run only preregistered repair-development diagnostics/proposals and declared structural admission while retaining every missing capability, rejection, and authority boundary.
- Evidence: PLAT2EV040TCH
- Outputs: workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_teacher_receipts.json, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py -q
- Acceptance: Only registry-eligible methods/residuals run; direct and SyMAI route identities stay distinct; real model calls prove inference and retain typed failures; diagnostics/guidance/proposals remain non-authoritative; only triggered fields change; StructuralAdmission checks declared properties and cannot replace e2e loss; receipts bind packet/tree/intervention/provider/toolchain/assumption/status CIDs; blind data and namespaces remain untouched.
- Conflict policy: Teacher-only; no production routing change.

## PLAT2-G050 Deterministic repair-development edit waves

- Status: active
- Parent: PLAT2-G000, PLAT2-G030, PLAT2-G035
- Priority: P0
- Track: det-compiler
- Bundle: semantic-roundtrip/plateau-holdout/compiler-edits
- Goal: Evaluate one bounded deterministic typed_deontic rule hypothesis per repair-development wave while retaining pilots as regression controls.
- Evidence: PLAT2EV050EDIT
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_edit_wave_receipts/, tests/unit/benchmarks/semantic_roundtrip/
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=20
- Acceptance: Each isolated/revertible wave cites packet/intervention/baseline/tree CIDs, exact changes, assumptions, tests, structural receipts, context/model cost, and before/after repair-development plus pilot metrics; optional teacher evidence is consumed only when applicable and missing/rejected evidence cannot masquerade as admission; residual-only reviewed hypotheses may use their own gates; shared hotspots serialize; pilots remain mean e2e 0.0 with full gates; no optional runtime or blind access.
- Conflict policy: Parallel case lanes; merge-train serialize shared typed_deontic hotspots.

## PLAT2-G055 Candidate freeze, attribution, and holdout authorization

- Status: active
- Parent: PLAT2-G000, PLAT2-G050
- Priority: P0
- Track: candidate-freeze
- Bundle: semantic-roundtrip/plateau-holdout/freeze
- Goal: Attribute isolated and cumulative edit effects on repair-development/pilots, select zero or one candidate under frozen rules, and bind the only valid blind-access authorization.
- Evidence: PLAT2EV055FREEZE
- Outputs: benchmarks/semantic_roundtrip/holdout_candidate_freeze.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_candidate_freeze.json, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_authorization.json, docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
- Acceptance: Replay per-wave/cumulative ablations on identical repair-development/pilots and report semantic, repair, regression, structural-coverage, token/call/cost metrics; freeze baseline/candidate commits and gitlinks, code/config/prompts/metrics/statistics/margins/interventions/packets/providers/toolchains/environment/tests/population/seal/threshold CIDs; authorize only one complete candidate with zero prior blind access; any subsequent input change invalidates authorization and requires a new experiment plus fresh blind population.
- Conflict policy: Freeze/authorization only; no code, packet, prompt, threshold, metric, population, or blind edits.

## PLAT2-G060 One-shot blind-holdout evaluation and decision

- Status: active
- Parent: PLAT2-G000, PLAT2-G055
- Priority: P0
- Track: remeasure
- Bundle: semantic-roundtrip/plateau-holdout/remeasure
- Goal: Under one audited custodian access, compare the frozen baseline and candidate on identical blind cases and publish improvement, noninferiority-without-improvement, or declined promotion without feedback tuning.
- Evidence: PLAT2EV060MEAS
- Outputs: benchmarks/semantic_roundtrip/holdout_evaluation.py, tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_access_ledger.json, docs/performance_snapshots/*_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md, docs/performance_snapshots/*_semantic_roundtrip_holdout_promotion_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_evaluation.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py -q
- Acceptance: Single-use access receipt binds authorization and all frozen identities; evaluator/scorer boundaries prevent blind gold/diagnostics from reaching agents/prompts/packets/teachers/caches; baseline and candidate receive identical cases and preregistered analysis; publish coverage, per-case/facet loss, gates, paired delta/CI, separate structural evidence, resources, missingness, and ledger CID; improvement requires CI high &lt; 0 plus gates, generalization-without-improvement requires frozen noninferiority plus no regressions, otherwise decline; no post-access changes/reruns, and follow-up requires a new board and fresh blind population.
- Conflict policy: Own holdout snapshot paths only.
