# Semantic Round-Trip Plateau-Break Objective Heap

This objective heap is machine-ingestible planning state for
`ipfs_accelerate_py.agent_supervisor` (objective daemon / bundle supervisor).
The companion taskboard
`semantic_roundtrip_plateau_break.taskboard.todo.md` is the executable
projection (task prefix `## PLAT-`).

## North star

**Improve the deterministic production path**

> `typed_deontic` constructor → CanonicalRuleIR → deterministic realizer

past the measured plateau of mean end-to-end loss **≈ 0.088** (forward ≈ 0.085,
cycle ≈ 0.003) on the five pilot cases, **without** promoting unearned optional
runtimes.

Optional methods (spaCy, autoencoder, Leanstral, SyMAI, selective repair,
Hammer/cvc5/Lean) are **teachers, proposers, and gates**. Codex / Grok via the
agent supervisor applies only **deterministic compiler/decompiler code edits**.
Production composition stays fail-closed until paired bootstrap CI high &lt; 0
versus the frozen baseline arm.

## Evidence already sealed (do not re-do harness repair)

| Artifact | Value |
| --- | --- |
| EVAL harness board | EVAL-001…009 complete |
| Baseline arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Baseline e2e | 0.088333333 |
| Research report CID | `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza` |
| Improvement plan | `docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md` |
| Guided AE status | `unavailable_no_reviewed_causal_l1_adapter` / `not_measured` |
| Selective repair on pilots | activation proven on fixtures; hybrid pilots `not_triggered` |
| Prover earned role | `repair_admission_gate_only` (never semantic authority) |

## Hard residual pilot cases (forward-dominated)

| Case | e2e (det. hybrid re-run) | Notes |
| --- | ---: | --- |
| `exception_with_window` | 0.00 | Already solved on pilots |
| `exec_order_1` | 0.05 | Small forward residual |
| `corp_policy_1` | 0.10 | Forward residual |
| `legal_doc_1` | 0.15 | Forward + small cycle |
| `construction_contract` | 0.14 | Forward residual |

## Composition doctrine (normative)

```text
Teachers (offline): spaCy diagnostics | AE residuals (after adapter)
                    | Leanstral (± SyMAI) selective IR patches
        → Provers:  Hammer/cvc5 + Lean admit/reject + proof_obligations
        → Packet:   residual + admitted ΔL1 + failed constraints + file targets
        → Supervisor: implement deterministic code only
        → Re-score: same det. path; promote only if CI high < 0 vs 0.088
```

Forbidden without a separate promotion decision:

- spaCy or model as default production constructor/realizer
- always-on Leanstral/SyMAI decompile
- treating proof pass as lower end-to-end loss
- gold leakage into AE features or repair prompts
- rewriting the immutable 2026-07-27 replacement promotion report

## Goal tree

```text
PLAT-G000  Break det. plateau with prover-gated Codex improvement loop
├── PLAT-G010  Residual forensics catalog (case × facet)
├── PLAT-G020  Prover-gated Codex packet contract
├── PLAT-G030  Selective-repair triggers aligned to pilot residuals
├── PLAT-G040  Leanstral proposal pipeline (teacher only)
├── PLAT-G050  spaCy diagnostic teacher (not production constructor)
├── PLAT-G060  Causal AE L1 adapter (unlock AE teacher)
├── PLAT-G070  Agent-supervisor plateau-break lane + materializer
├── PLAT-G080  Deterministic compiler edit waves (per residual case)
├── PLAT-G090  Re-measure, bootstrap, optional promotion decision
└── PLAT-G100  Dual-metric bridge (CE/cosine + structural) for AE loop
```

Parallelism: G010, G020, G050, G060, G070 can start in parallel after board
bootstrap. G030 depends on G010. G040 depends on G030 (+ G020 for packet
emit). G080 depends on G010+G020+G070 and consumes G040/G050 admits. G090
depends on at least one G080 wave. G100 parallel after G060 or standalone
metrics work.

---

## PLAT-G000 Break deterministic plateau with prover-gated Codex loop

- Status: active
- Parent:
- Priority: P0
- Track: plateau-break
- Bundle: semantic-roundtrip/plateau-break/root
- Goal: Drive deterministic typed_deontic → IR → deterministic realizer mean end-to-end loss strictly below the sealed 0.088 plateau on pilot cases using residual forensics, optional-method teachers, structural provers, and agent-supervisor Codex edits—without unearned production composition.
- Evidence: PLATEV000ROOT
- Outputs: docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md, docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md, docs/benchmarks/semantic_roundtrip_plateau_break_plan.md
- Validation: test -f docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md && test -f docs/benchmarks/semantic_roundtrip_plateau_break_plan.md
- Acceptance: All child goals have bound receipts or explicit blocked reasons; no production default change unless PLAT-G090 promotion authorizes it; board remains schedulable by agent supervisor.
- Gap task: Execute child workstreams in parallel lanes per the taskboard.
- Conflict policy: Own plateau-break planning artifacts only; do not reopen EVAL-001…009 harness contracts unless a defect blocks measurement.

## PLAT-G010 Residual forensics catalog

- Status: active
- Parent: PLAT-G000
- Priority: P0
- Track: residual
- Bundle: semantic-roundtrip/plateau-break/residual
- Goal: Produce a machine-readable case×facet residual catalog for the four non-zero pilot cases against the deterministic baseline L1, including loss contribution and suggested trigger kinds.
- Evidence: PLATEV010RESID
- Outputs: benchmarks/semantic_roundtrip/residual_catalog.py, tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau_residual_catalog.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
- Acceptance: Catalog covers exec_order_1, corp_policy_1, legal_doc_1, construction_contract; each residual names canonical field path(s), estimated forward contribution, and optional spaCy/AE cue placeholders; exception_with_window recorded as zero-residual control; CID-bound JSON written.
- Gap task: Implement residual catalog builder over typed_deontic L1 vs gold/facet scorer.
- Conflict policy: Own residual catalog module and receipt; do not change constructor semantics.

## PLAT-G020 Prover-gated Codex packet contract

- Status: active
- Parent: PLAT-G000
- Priority: P0
- Track: packets
- Bundle: semantic-roundtrip/plateau-break/packets
- Goal: Define and implement PlateauCodexPacket@1 that binds baseline L1, residual facets, teacher proposals, structural admission receipts, proof_obligation IDs, predicted files, and validation commands for supervisor implementation.
- Evidence: PLATEV020PKT
- Outputs: benchmarks/semantic_roundtrip/plateau_codex_packet.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py, docs/benchmarks/semantic_roundtrip_plateau_codex_packet.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q
- Acceptance: Packet schema is content-addressed; reject/timeout/error proposals cannot be marked implementable; admitted ΔL1 lists only canonical_field_changes; semantic_authority always false on prover receipts; round-trip serialize/deserialize tests pass.
- Gap task: Implement packet builder integrating StructuralAdmission@1 receipts.
- Conflict policy: Own packet contract; reuse structural_admission and selective_repair interfaces without weakening fail-closed rules.

## PLAT-G030 Selective-repair triggers aligned to pilot residuals

- Status: active
- Parent: PLAT-G000, PLAT-G010
- Priority: P0
- Track: repair-triggers
- Bundle: semantic-roundtrip/plateau-break/triggers
- Goal: Map residual catalog facets to compiler-declared RepairTrigger kinds so selective repair fires on pilot cases (not only fixture packs) without changing promotion defaults.
- Evidence: PLATEV030TRIG
- Outputs: benchmarks/semantic_roundtrip/selective_repair.py, benchmarks/semantic_roundtrip/pilot_residual_triggers.py, tests/unit/benchmarks/semantic_roundtrip/test_pilot_residual_triggers.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_pilot_residual_triggers.py tests/unit/benchmarks/semantic_roundtrip/test_selective_repair.py -q
- Acceptance: At least three of four non-zero pilot cases produce ≥1 trigger under the residual map; untriggered fields remain preserved; fixture pack activation still passes; production default remains no-repair unless explicitly configured.
- Gap task: Implement residual→trigger projection and tests on pilot L1s.
- Conflict policy: Own trigger projection; do not force model_calls on non-triggering paths.

## PLAT-G040 Leanstral proposal pipeline (teacher only)

- Status: active
- Parent: PLAT-G000, PLAT-G030, PLAT-G020
- Priority: P1
- Track: leanstral-teacher
- Bundle: semantic-roundtrip/plateau-break/leanstral-teacher
- Goal: Emit structure-bounded Leanstral (± optional SyMAI) selective IR patches for triggered pilot slots and feed them through structural admission into Codex packets.
- Evidence: PLATEV040LLM
- Outputs: benchmarks/semantic_roundtrip/plateau_leanstral_proposals.py, tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py, workspace/benchmarks/semantic-roundtrip-compositions/plateau_leanstral_proposal_receipts.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_leanstral_proposals.py -q
- Acceptance: Proposals change only triggered fields; rejects leave prior L1 unchanged; accept_rate/retry_exhausted recorded separately from e2e; no production routing change; dry-run mode works without live model using fixtures.
- Gap task: Wire selective repair + StructuralAdmissionGate into packet emission.
- Conflict policy: Own teacher pipeline; Leanstral never becomes default realizer.

## PLAT-G050 spaCy diagnostic teacher

- Status: active
- Parent: PLAT-G000
- Priority: P1
- Track: spacy-teacher
- Bundle: semantic-roundtrip/plateau-break/spacy-teacher
- Goal: Export spaCy polarity/span/missing-slot diagnostics into residual packets without promoting modal_spacy as production constructor.
- Evidence: PLATEV050SPACY
- Outputs: benchmarks/semantic_roundtrip/constructors/modal_spacy.py, benchmarks/semantic_roundtrip/spacy_residual_diagnostics.py, tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_spacy_residual_diagnostics.py tests/unit/benchmarks/semantic_roundtrip/test_modal_spacy_constructor.py -q
- Acceptance: Diagnostics attach to residual catalog rows; constructor-only forward still not claimed as production win; polarity preflight remains fail-closed on inversions.
- Gap task: Add diagnostic export API and unit tests.
- Conflict policy: Own diagnostics export; do not swap typed_deontic production default.

## PLAT-G060 Causal autoencoder L1 adapter (AE teacher unlock)

- Status: active
- Parent: PLAT-G000
- Priority: P2
- Track: autoencoder
- Bundle: semantic-roundtrip/plateau-break/autoencoder
- Goal: Supply a reviewed causal feature→CanonicalRuleIR field adapter (or keep guided arms explicitly not_measured) so AE residuals can enter Codex packets without gold leakage.
- Evidence: PLATEV060AE
- Outputs: benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py, tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py, workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py -q
- Acceptance: Either scored_supported with preregistered feature map, independent review CID, negative control zero-change, forbidden inputs enforced; or explicit terminal_unsupported with schedule_for_semantic_scoring false. Qualification JSON CID refreshed.
- Gap task: Close unavailable_no_reviewed_causal_l1_adapter or document permanent exclusion.
- Conflict policy: Own causal guidance only; no fabricated L1 mutations; no gold/sample memory.

## PLAT-G070 Agent-supervisor plateau-break lane

- Status: active
- Parent: PLAT-G000, PLAT-G020
- Priority: P0
- Track: supervisor
- Bundle: semantic-roundtrip/plateau-break/supervisor
- Goal: Materialize plateau Codex packets into agent-supervisor tasks with proof_obligation bindings, predicted files limited to deterministic compiler/realizer, and validation that re-runs structural admission + pilot re-score.
- Evidence: PLATEV070SUP
- Outputs: benchmarks/semantic_roundtrip/plateau_supervisor_materialize.py, docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md, tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_supervisor_materialize.py -q
- Acceptance: Materializer emits one task per implementable packet; rejected-only packets become documentation/obligation tasks not silent merges; merge target branch policy documented; no automatic production promotion.
- Gap task: Implement materializer and document launch flags for bundle_supervisor.
- Conflict policy: Own materializer and board projection; coordinate with G080 case tasks via packet CIDs.

## PLAT-G080 Deterministic compiler edit waves

- Status: active
- Parent: PLAT-G000, PLAT-G010, PLAT-G020, PLAT-G070
- Priority: P0
- Track: det-compiler
- Bundle: semantic-roundtrip/plateau-break/compiler-edits
- Goal: Apply prover-gated Codex packets as deterministic code changes to typed_deontic (and realizer only if cycle residual requires it), re-scoring pilots after each wave.
- Evidence: PLATEV080EDIT
- Outputs: benchmarks/semantic_roundtrip/constructors/typed_deontic.py, benchmarks/semantic_roundtrip/realizers/, tests/unit/benchmarks/semantic_roundtrip/, workspace/benchmarks/semantic-roundtrip-compositions/plateau_edit_wave_receipts/
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/ -q --maxfail=20
- Acceptance: Each merged wave cites packet CID(s); structural constraints still pass on admitted repairs; pilot mean e2e not worse than pre-wave; no LLM runtime dependency introduced into production path.
- Gap task: Execute parallel per-case edit tasks PLAT-081…084 from packets.
- Conflict policy: Case lanes may edit disjoint residual facets; serialize merges that touch the same typed_deontic regions via supervisor merge train.

## PLAT-G090 Re-measure, bootstrap, promotion decision

- Status: active
- Parent: PLAT-G000, PLAT-G080
- Priority: P0
- Track: remeasure
- Bundle: semantic-roundtrip/plateau-break/remeasure
- Goal: Re-run hybrid constructor_only + det. path on pilots with paired bootstrap vs frozen 0.088 baseline; write a new research receipt and optional promotion decision.
- Evidence: PLATEV090MEAS
- Outputs: docs/performance_snapshots/*_semantic_roundtrip_plateau_break_matrix.json, docs/benchmarks/semantic_roundtrip_plateau_break_results.md, docs/performance_snapshots/*_plateau_break_promotion_decision.json
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_replacement_matrix.py tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py -q
- Acceptance: Report excludes not_measured from rankings; promotion authorized only if e2e CI high &lt; 0 vs baseline and full gates pass; immutable 2026-07-27 replacement report not rewritten.
- Gap task: Automate re-measure entrypoint and decision validator.
- Conflict policy: Own new snapshot paths only.

## PLAT-G100 Dual-metric bridge (CE / cosine + structural)

- Status: active
- Parent: PLAT-G000
- Priority: P2
- Track: metrics-bridge
- Bundle: semantic-roundtrip/plateau-break/metrics-bridge
- Goal: Bridge original AE-loop metrics (cross-entropy, cosine similarity) with structural forward/cycle/e2e so Codex packets and AE training share a common residual language.
- Evidence: PLATEV100MET
- Outputs: benchmarks/semantic_roundtrip/dual_metrics.py, tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py, docs/benchmarks/semantic_roundtrip_dual_metrics.md
- Validation: PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py -q
- Acceptance: Dual metric report attaches to residual catalog rows when embeddings available; missing embedding backends fail closed to structural-only; no silent metric substitution in promotion.
- Gap task: Implement dual metric helpers and docs.
- Conflict policy: Own dual_metrics module; do not change composition protocol primary loss definition.

## Parallel schedule summary

| Wave | Goals | Lanes |
| --- | --- | --- |
| 0 bootstrap | G000 plan sealed | docs |
| 1 foundation | G010, G020, G050, G060*, G070, G100* | residual, packets, spacy, autoencoder, supervisor, metrics |
| 2 teachers | G030 → G040 | triggers, leanstral-teacher |
| 3 edits | G080 case tasks (parallel by case) | det-legal-doc, det-construction, det-corp-policy, det-exec-order |
| 4 close | G090 | remeasure |

\*G060 and G100 may lag without blocking wave-3 if packets can proceed with spaCy + Leanstral teachers only.

## Completion rule

Root PLAT-G000 is complete only when:

1. Residual catalog CID exists (G010).
2. Packet contract is tested (G020).
3. At least one edit wave merged with packet provenance (G080) **or** explicit blocked analysis shows no implementable admitted patches after G040.
4. Re-measure receipt exists (G090), even if promotion is false.
5. Production default remains typed_deontic+deterministic unless G090 authorizes otherwise.
