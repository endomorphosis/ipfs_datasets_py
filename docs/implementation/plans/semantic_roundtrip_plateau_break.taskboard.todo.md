# Semantic Round-Trip Plateau-Break Taskboard

This board is consumable by `ipfs_accelerate_py.agent_supervisor` with task
prefix `## PLAT-`. Companion objectives:
`docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md`.

## Objective

The EVAL harness (EVAL-001…009) now fairly measures optional methods. Fair
results show **no optional runtime composition** beats the deterministic
plateau (**typed_deontic → IR → deterministic realizer**, e2e ≈ **0.088**).

Use spaCy, autoencoder, Leanstral, SyMAI, selective repair, and
Hammer/cvc5/Lean as **teachers and gates**; use the agent supervisor to apply
**prover-gated Codex packets** that improve the **deterministic**
compiler/decompiler. Promote only with paired bootstrap CI high &lt; 0.

Do **not** rewrite the immutable 2026-07-27 replacement promotion report.
Do **not** treat proof pass as semantic loss reduction.

## Baseline lock

- Baseline arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`
- Baseline e2e: `0.088333333`
- Report CID: `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`
- Branch intent: `benchmark/semantic-roundtrip-20260726` (or successor plateau-break branch)

## Parallel lane map

| Lane | Owns |
| --- | --- |
| `plat-docs` | Plan docs only |
| `plat-residual` | Residual catalog |
| `plat-packets` | Codex packet contract |
| `plat-triggers` | Pilot residual → selective-repair triggers |
| `plat-leanstral-teacher` | LLM proposal pipeline |
| `plat-spacy-teacher` | spaCy diagnostics export |
| `plat-autoencoder` | Causal L1 adapter |
| `plat-supervisor` | Materializer / board tooling |
| `plat-metrics` | Dual CE/cosine bridge |
| `plat-det-legal-doc` | Det. compiler edits for legal_doc_1 |
| `plat-det-construction` | Det. compiler edits for construction_contract |
| `plat-det-corp-policy` | Det. compiler edits for corp_policy_1 |
| `plat-det-exec-order` | Det. compiler edits for exec_order_1 |
| `plat-remeasure` | Bootstrap re-run + promotion decision |

---

## PLAT-000 Seal plateau-break plan artifacts

- Status: completed
- Completion: auto
- Priority: P0
- Track: plateau-break
- Depends on:
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_break_plan.md
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md && test -f docs/benchmarks/semantic_roundtrip_plateau_break_plan.md
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/docs
- Parallel lane: plat-docs
- Resource class: cpu-small
- Implementation timeout seconds: 1800
- Predicted files: docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_break_plan.md
- Interfaces: PlateauBreakPlan@1
- Conflict policy: Own only plateau-break planning docs; do not modify EVAL harness contracts.
- Preconditions: EVAL-009 research report exists.
- Effects: Supervisor and humans share one sealed doctrine for plateau break.
- Evidence subset: plateau-break plan seal
- Acceptance: Objectives heap, this taskboard, and human plan doc exist; doctrine states teachers/provers/supervisor roles, baseline lock, forbidden promotions, and parallel lane map.

## PLAT-010 Residual forensics catalog

- Status: todo
- Completion: auto
- Priority: P0
- Track: residual
- Depends on: PLAT-000
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/residual
- Parallel lane: plat-residual
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau_residual_catalog.json
- Interfaces: PlateauResidualCatalog@1
- Conflict policy: Own residual catalog module and receipt only.
- Preconditions: Typed deontic constructor and pilot cases available; baseline arm frozen.
- Effects: Case×facet residuals drive triggers, packets, and edit waves.
- Evidence subset: residual-catalog receipt
- Acceptance: Catalog includes exec_order_1, corp_policy_1, legal_doc_1, construction_contract with field paths and loss contributions; exception_with_window is a zero-residual control; JSON is CID-bindable; unit tests cover parsing and aggregation.

## PLAT-020 Prover-gated Codex packet contract

- Status: todo
- Completion: auto
- Priority: P0
- Track: packets
- Depends on: PLAT-000
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/packets
- Parallel lane: plat-packets
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Own packet contract; reuse structural_admission without weakening fail-closed semantics.
- Preconditions: StructuralAdmission@1 and CanonicalFieldChange APIs exist.
- Effects: Only admitted proposals become implementable supervisor work.
- Evidence subset: plateau-codex-packet contract
- Acceptance: Packet includes baseline L1 digest, residual refs, proposals, admission receipts, proof_obligation IDs, predicted files, validation commands; implementable=false when disposition is reject/timeout/error; semantic_authority false on prover receipts; docs describe supervisor consumption.

## PLAT-030 Pilot residual → selective-repair triggers

- Status: todo
- Completion: auto
- Priority: P0
- Track: repair-triggers
- Depends on: PLAT-010
- Outputs: benchmarks/semantic_roundtrip/pilot_residual_triggers.py, tests/unit/benchmarks/semantic_roundtrip/test_pilot_residual_triggers.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_pilot_residual_triggers.py tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/triggers
- Parallel lane: plat-triggers
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/pilot_residual_triggers.py, benchmarks/semantic_roundtrip/selective_repair.py, tests/unit/benchmarks/semantic_roundtrip/test_pilot_residual_triggers.py
- Interfaces: RepairTrigger@1, PlateauResidualCatalog@1
- Conflict policy: Own trigger projection; minimal selective_repair hooks only if required for declared triggers.
- Preconditions: Residual catalog exists.
- Effects: Selective repair can fire on pilot residuals (not only fixtures).
- Evidence subset: pilot-trigger map receipt
- Acceptance: ≥3 of 4 non-zero pilots emit ≥1 trigger; untriggered fields preserved; fixture activation pack still passes; default production path remains no-repair.

## PLAT-040 Leanstral selective proposal teacher

- Status: todo
- Completion: auto
- Priority: P1
- Track: leanstral-teacher
- Depends on: PLAT-020, PLAT-030
- Outputs: benchmarks/semantic_roundtrip/plateau_leanstral_proposals.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau_leanstral_proposal_receipts.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/leanstral-teacher
- Parallel lane: plat-leanstral-teacher
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/plateau_leanstral_proposals.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py
- Interfaces: ModelOutputRecovery@1, StructuralAdmission@1, PlateauCodexPacket@1
- Conflict policy: Own teacher pipeline only; never set Leanstral as default realizer.
- Preconditions: Live smoke can reach Leanstral or offline fixtures present for unit path.
- Effects: Admitted IR patches available for Codex packets; rejects retain prior L1.
- Evidence subset: leanstral-proposal receipts
- Acceptance: Dry-run fixtures pass without live model; live path records accept_rate and retry_exhausted separately; only triggered fields change; StructuralAdmissionGate applied before implementable=true.

## PLAT-050 spaCy residual diagnostics teacher

- Status: todo
- Completion: auto
- Priority: P1
- Track: spacy-teacher
- Depends on: PLAT-000
- Outputs: benchmarks/semantic_roundtrip/spacy_residual_diagnostics.py, tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/spacy-teacher
- Parallel lane: plat-spacy-teacher
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/spacy_residual_diagnostics.py, benchmarks/semantic_roundtrip/constructors/modal_spacy.py, tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py
- Interfaces: ModalSpacyConstructor@1, PlateauResidualCatalog@1
- Conflict policy: Own diagnostics export; do not promote modal_spacy to production constructor.
- Preconditions: modal_spacy constructor and polarity preflight exist.
- Effects: spaCy cues attach to residual/packet rows as non-authoritative diagnostics.
- Evidence subset: spacy-diagnostic receipt
- Acceptance: Diagnostics API returns polarity/span/missing-slot signals per pilot case; unit tests cover fail-closed polarity preflight interaction; no production default change.

## PLAT-060 Causal autoencoder L1 adapter

- Status: todo
- Completion: auto
- Priority: P2
- Track: autoencoder
- Depends on: PLAT-000
- Outputs: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/autoencoder
- Parallel lane: plat-autoencoder
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Interfaces: CausalGuidanceQualification@1, ReviewedFeatureToCanonicalFieldIntervention@1
- Conflict policy: Own causal guidance only; forbid gold leakage and fabricated L1 mutations.
- Preconditions: Current qualification is unavailable_no_reviewed_causal_l1_adapter.
- Effects: Guided AE either scored_supported for teacher residuals or explicitly not_measured.
- Evidence subset: causal-guidance qualification receipt
- Acceptance: Either (a) reviewed feature→field map, independent review CID, negative control zero-change, forbidden-input enforcement, scored_supported; or (b) terminal_unsupported with schedule_for_semantic_scoring false and refreshed qualification CID. Tests cover both fail-closed missing contract and negative control.

## PLAT-070 Supervisor packet materializer

- Status: todo
- Completion: auto
- Priority: P0
- Track: supervisor
- Depends on: PLAT-020
- Outputs: benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py, docs/benchmarks/semantic_roundtrip_plateau_supervisor_launch.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/supervisor
- Parallel lane: plat-supervisor
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py, docs/benchmarks/semantic_roundtrip_plateau_supervisor_launch.md
- Interfaces: PlateauCodexPacket@1
- Conflict policy: Own materializer and launch docs; do not edit unrelated supervisor boards.
- Preconditions: Packet contract available.
- Effects: Implementable packets become PLAT-08x style tasks or runtime board entries with proof_obligation IDs.
- Evidence subset: materializer receipt
- Acceptance: Materializer maps implementable packets → tasks with predicted files limited to typed_deontic/realizer/tests; non-implementable packets produce obligation-only notes; launch doc lists bundle_supervisor flags, merge branch, and max lanes.

## PLAT-080 Dual-metric bridge (CE / cosine + structural)

- Status: todo
- Completion: auto
- Priority: P2
- Track: metrics-bridge
- Depends on: PLAT-000
- Outputs: benchmarks/semantic_roundtrip/dual_metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py, docs/benchmarks/semantic_roundtrip_dual_metrics.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/metrics-bridge
- Parallel lane: plat-metrics
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/dual_metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py, docs/benchmarks/semantic_roundtrip_dual_metrics.md
- Interfaces: DualRoundTripMetrics@1
- Conflict policy: Own dual_metrics only; do not change composition protocol primary structural loss.
- Preconditions: Structural loss helpers exist.
- Effects: AE-loop CE/cosine can share residual language with Codex packets when embeddings available.
- Evidence subset: dual-metrics contract
- Acceptance: Reports structural forward/cycle/e2e always; attaches CE/cosine when backend present; missing backend fails closed to structural-only without inventing scores.

## PLAT-081 Det. compiler edit wave: legal_doc_1

- Status: todo
- Completion: auto
- Priority: P0
- Track: det-compiler
- Depends on: PLAT-010, PLAT-020, PLAT-070
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/legal_doc_1.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=15
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/det-legal-doc
- Parallel lane: plat-det-legal-doc
- Resource class: llm-proof-draft
- Resource stage: inference
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Prefer residual facets for legal_doc_1; coordinate merge if typed_deontic hotspots overlap other case lanes.
- Preconditions: Residual catalog lists legal_doc_1; packet materializer available; optional admitted Leanstral/spaCy proposals when present.
- Effects: Deterministic rules improve legal_doc_1 forward residual without LLM runtime.
- Evidence subset: edit-wave legal_doc_1
- Acceptance: Wave cites packet CID(s); pilot re-score for legal_doc_1 e2e ≤ prior; mean e2e across five pilots not worse; no production LLM dependency; structural constraints preserved on any repair examples in tests.

## PLAT-082 Det. compiler edit wave: construction_contract

- Status: todo
- Completion: auto
- Priority: P0
- Track: det-compiler
- Depends on: PLAT-010, PLAT-020, PLAT-070
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/construction_contract.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=15
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/det-construction
- Parallel lane: plat-det-construction
- Resource class: llm-proof-draft
- Resource stage: inference
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Own construction_contract residual facets; serialize merges that collide with other det lanes.
- Preconditions: Residual catalog lists construction_contract; materializer available.
- Effects: Deterministic rules improve construction_contract forward residual.
- Evidence subset: edit-wave construction_contract
- Acceptance: Same bar as PLAT-081 for construction_contract; no silent promotion of optional runtimes.

## PLAT-083 Det. compiler edit wave: corp_policy_1

- Status: todo
- Completion: auto
- Priority: P0
- Track: det-compiler
- Depends on: PLAT-010, PLAT-020, PLAT-070
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/corp_policy_1.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=15
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/det-corp-policy
- Parallel lane: plat-det-corp-policy
- Resource class: llm-proof-draft
- Resource stage: inference
- Implementation timeout seconds: 10800
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Own corp_policy_1 residual facets; merge-train coordination on shared files.
- Preconditions: Residual catalog lists corp_policy_1; materializer available.
- Effects: Deterministic rules improve corp_policy_1 forward residual.
- Evidence subset: edit-wave corp_policy_1
- Acceptance: Same bar as PLAT-081 for corp_policy_1.

## PLAT-084 Det. compiler edit wave: exec_order_1

- Status: todo
- Completion: auto
- Priority: P1
- Track: det-compiler
- Depends on: PLAT-010, PLAT-020, PLAT-070
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/exec_order_1.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=15
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/det-exec-order
- Parallel lane: plat-det-exec-order
- Resource class: llm-proof-draft
- Resource stage: inference
- Implementation timeout seconds: 7200
- Predicted files: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, tests/unit/benchmarks/semantic_roundtrip/
- Interfaces: PlateauCodexPacket@1, StructuralAdmission@1
- Conflict policy: Own exec_order_1 residual facets; merge-train coordination on shared files.
- Preconditions: Residual catalog lists exec_order_1; materializer available.
- Effects: Deterministic rules improve smaller exec_order_1 residual.
- Evidence subset: edit-wave exec_order_1
- Acceptance: Same bar as PLAT-081 for exec_order_1; e2e for this case ≤ 0.05 prior or improved.

## PLAT-090 Plateau re-measure and promotion decision

- Status: todo
- Completion: auto
- Priority: P0
- Track: remeasure
- Depends on: PLAT-081, PLAT-082, PLAT-083
- Outputs: docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_matrix.json, docs/benchmarks/semantic_roundtrip_plateau_break_results.md, docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/remeasure
- Parallel lane: plat-remeasure
- Resource class: cpu-medium
- Resource stage: analysis
- Implementation timeout seconds: 14400
- Predicted files: docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_matrix.json, docs/benchmarks/semantic_roundtrip_plateau_break_results.md, docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json
- Interfaces: EvalRepairMatrixReport@1, CanonicalCompilerDecision@1
- Conflict policy: Own new snapshot/decision paths only; never rewrite 2026-07-27 replacement promotion report.
- Preconditions: At least one det edit wave merged or explicit no-op wave receipts explaining no admitted patches.
- Effects: Operators know whether plateau broke and whether promotion is authorized.
- Evidence subset: plateau-break remeasure receipt
- Acceptance: Pilot det. path re-scored; paired bootstrap vs 0.088 baseline; not_measured excluded from rankings; promotion true only if e2e CI high &lt; 0 and full gates pass; otherwise promotion false with named next residuals.

## PLAT-091 Optional: full research matrix refresh (post-break only)

- Status: todo
- Completion: auto
- Priority: P3
- Track: remeasure
- Depends on: PLAT-090
- Outputs: docs/performance_snapshots/*_semantic_roundtrip_post_plateau_matrix.json, docs/benchmarks/semantic_roundtrip_post_plateau_results.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py -q
- Board namespace: semantic-roundtrip-plateau-break-v1
- Bundle: semantic-roundtrip/plateau-break/full-matrix
- Parallel lane: plat-remeasure
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: false
- Implementation timeout seconds: 14400
- Predicted files: docs/performance_snapshots/, docs/benchmarks/
- Interfaces: EvalRepairMatrixReport@1
- Conflict policy: Own post-plateau matrix artifacts only.
- Preconditions: PLAT-090 shows promotion true **or** explicit operator override with written reason.
- Effects: Optional methods re-ranked fairly after det. path moved.
- Evidence subset: post-plateau matrix
- Acceptance: Do not run a full 670 re-rank unless PLAT-090 succeeded or override is recorded; report keeps status taxonomy and fail-closed promotion rules.

---

## Dependency DAG (for scheduling)

```text
PLAT-000
  ├─ PLAT-010 residual ──────────────┐
  ├─ PLAT-020 packets ── PLAT-070 ───┼── PLAT-081 legal_doc ──┐
  ├─ PLAT-050 spacy                  │   PLAT-082 construction┤
  ├─ PLAT-060 autoencoder (//)       │   PLAT-083 corp_policy ┤── PLAT-090 ── PLAT-091?
  └─ PLAT-080 dual metrics (//)      │   PLAT-084 exec_order ─┘
                                     │
                     PLAT-010 → PLAT-030 → PLAT-040 ──┘ (feeds packets/edits)
```

## Launch sketch (operator)

```bash
# From ipfs_datasets_py repo root / SRT worktree
export PYTHONPATH=ipfs_accelerate_py:.
export IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER=grok   # or project default

python -m benchmarks.semantic_roundtrip_scheduler prepare \
  --repo-root "$REPO" \
  --config-path config/semantic_roundtrip_plateau_break_scheduler.json \
  --runtime-root /var/tmp/hssl-srt-plateau-break \
  --taskboard-path docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md

python -m ipfs_accelerate_py.agent_supervisor.bundle_supervisor \
  --bundle-index-path /var/tmp/hssl-srt-plateau-break/bundles/index.json \
  --repo-root "$REPO" \
  --state-root /var/tmp/hssl-srt-plateau-break/state \
  --worktree-root /var/tmp/hssl-srt-plateau-break/worktrees \
  --task-prefix '## PLAT-' \
  --max-lanes 4 \
  --merge-target-branch benchmark/semantic-roundtrip-20260726 \
  --implement --start
```

Create `config/semantic_roundtrip_plateau_break_scheduler.json` by cloning the
eval-harness scheduler config and pointing at this taskboard (PLAT-070 may
add that file if missing).

## Explicit non-goals

- Re-opening EVAL harness status taxonomy unless a measurement defect is found
- Promoting spaCy/AE/Leanstral/SyMAI to production defaults without PLAT-090
- Using Hammer/cvc5/Lean as semantic loss substitutes
- Expanding full matrix before residual-driven det. edits land
