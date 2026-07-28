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

**Generalize the same improvement loop beyond the sealed five pilots** so we do
not overfit the pilot set, and keep theorem-prover + agent-supervisor packets
as the standard way to improve the deterministic compiler/decompiler.

## Goal tree

```text
PLAT2-G000  Holdout residual loop for det. path
├── PLAT2-G010  Extend residual catalog beyond sealed pilots
├── PLAT2-G020  Holdout case fixture / corpus freeze
├── PLAT2-G030  Packet + materializer reuse for holdout cases
├── PLAT2-G040  Prover-gated teacher proposals on holdout residuals
├── PLAT2-G050  Det. compiler edit waves (holdout cases, parallel)
└── PLAT2-G060  Holdout remeasure + promotion gates vs post-pilot baseline
```

## Parallelism

- G010 and G020 can run in parallel after G000 seal
- G030 depends on G010+G020
- G040 depends on G030
- G050 case lanes parallel after G030 (G040 optional if packets can form from residuals alone)
- G060 depends on G050 waves

## Normative constraints

- Do not rewrite immutable 2026-07-27 replacement promotion report
- Do not promote spaCy / AE / Leanstral / SyMAI to production without CI high &lt; 0
- Hammer/cvc5/Lean: admission only (`semantic_authority: false`)
- Pilot population PLAT results remain sealed historical evidence
- Holdout cases must be preregistered before inspecting holdout outcomes

## PLAT2-G000 Holdout residual loop for det. path

- Status: active
- Parent:
- Priority: P0
- Track: plateau-holdout
- Bundle: semantic-roundtrip/plateau-holdout/root
- Goal: Run residual→packet→prover→supervisor→remeasure on a preregistered holdout case set, preserving the det. production path and fail-closed promotion rules.
- Evidence: PLAT2EV000ROOT
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_holdout.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_holdout.taskboard.todo.md
- Acceptance: Board is schedulable; doctrine references PLAT pilot success and forbids optional runtime promotion without gates.
- Gap task: Execute child goals via parallel lanes.

## PLAT2-G010 Extend residual catalog beyond sealed pilots

- Status: active
- Parent: PLAT2-G000
- Priority: P0
- Track: residual
- Bundle: semantic-roundtrip/plateau-holdout/residual
- Goal: Generalize residual_catalog to accept a preregistered case population (not only PILOT_CASE_IDS) while keeping pilot catalog validation intact for historical receipts.
- Evidence: PLAT2EV010CAT
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/holdout_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Acceptance: API builds catalogs for holdout case lists; pilot sealed validators still pass; holdout catalog CID written.
- Conflict policy: Own residual_catalog extensions; do not break PLAT-010 pilot receipt validation.

## PLAT2-G020 Holdout case fixture freeze

- Status: active
- Parent: PLAT2-G000
- Priority: P0
- Track: corpus
- Bundle: semantic-roundtrip/plateau-holdout/corpus
- Goal: Preregister a holdout case fixture set disjoint from or strictly larger than the five pilots, with stable case_ids and gold IR bindings.
- Evidence: PLAT2EV020CORP
- Outputs: tests/fixtures/semantic_roundtrip/holdout_cases.json, tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py, docs/benchmarks/semantic_roundtrip_holdout_cases.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py -q
- Acceptance: Holdout IDs frozen before outcome inspection; at least 3 non-pilot cases OR documented expansion using selective-repair fixture cases plus any additional legal pilots available; CID-bound fixture.
- Conflict policy: Own holdout fixtures only.

## PLAT2-G030 Holdout packets + materializer

- Status: active
- Parent: PLAT2-G000, PLAT2-G010, PLAT2-G020
- Priority: P0
- Track: packets
- Bundle: semantic-roundtrip/plateau-holdout/packets
- Goal: Emit PlateauCodexPacket@1 (or HoldoutCodexPacket@1 extending it) for holdout residuals and materialize supervisor tasks.
- Evidence: PLAT2EV030PKT
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Acceptance: Holdout packets fail-closed on reject/timeout; materializer produces one task per implementable packet; predicted files limited to det. compiler/realizer/tests.
- Conflict policy: Extend existing packet modules without weakening pilot contracts.

## PLAT2-G040 Prover-gated teachers on holdout

- Status: active
- Parent: PLAT2-G000, PLAT2-G030
- Priority: P1
- Track: teachers
- Bundle: semantic-roundtrip/plateau-holdout/teachers
- Goal: Run spaCy diagnostics + Leanstral selective proposals + structural admission on holdout residuals.
- Evidence: PLAT2EV040TCH
- Outputs: workspace/benchmarks/semantic-roundtrip-compositions/holdout_leanstral_proposal_receipts.json, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py -q
- Acceptance: Dry-run fixtures pass; live path optional; only triggered fields change; StructuralAdmission@1 applied.
- Conflict policy: Teacher-only; no production routing change.

## PLAT2-G050 Det. compiler holdout edit waves

- Status: active
- Parent: PLAT2-G000, PLAT2-G030
- Priority: P0
- Track: det-compiler
- Bundle: semantic-roundtrip/plateau-holdout/compiler-edits
- Goal: Apply prover-gated packets as deterministic typed_deontic edits for holdout cases in parallel lanes.
- Evidence: PLAT2EV050EDIT
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, workspace/benchmarks/semantic-roundtrip-compositions/holdout_edit_wave_receipts/, tests/unit/benchmarks/semantic_roundtrip/
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=20
- Acceptance: Each wave cites packet CID; holdout mean e2e not worse than pre-wave; no LLM runtime in production path.
- Conflict policy: Parallel case lanes; merge-train serialize shared typed_deontic hotspots.

## PLAT2-G060 Holdout remeasure + gates

- Status: active
- Parent: PLAT2-G000, PLAT2-G050
- Priority: P0
- Track: remeasure
- Bundle: semantic-roundtrip/plateau-holdout/remeasure
- Goal: Remeasure holdout det. path vs post-pilot baseline (mean e2e 0 on pilots) with paired bootstrap and full gates; record promotion or named residuals.
- Evidence: PLAT2EV060MEAS
- Outputs: docs/performance_snapshots/*_semantic_roundtrip_holdout_remeasure.json, docs/benchmarks/semantic_roundtrip_holdout_results.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Acceptance: Per-case tables published; promotion only if CI high &lt; 0 vs declared baseline and gates pass; pilots remain non-regressed.
- Conflict policy: Own holdout snapshot paths only.
