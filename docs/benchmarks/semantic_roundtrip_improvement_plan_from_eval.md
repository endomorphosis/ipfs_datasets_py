# Semantic round-trip improvement plan from eval repair matrix

**Source report CID:** `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`  
**Task:** EVAL-009  
**Baseline:** `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`  
**Decision date:** 2026-07-27

## Executive decision

**No optional method earned composition into the default production path.**

The production path remains:

> **typed_deontic → CanonicalRuleIR → deterministic realizer (no guidance, no repair)**

Production promotion of an alternate composition is **not authorized**. Fail-closed
selection continues: a method earns production composition only with
`semantic_scored` evidence and a paired case-cluster bootstrap CI entirely below
zero versus the typed_deontic deterministic baseline, plus full selection gates.

## Methods that earned composition

- **None.** No optional method strictly beat the typed_deontic deterministic baseline under paired bootstrap (CI entirely below zero).

## What was measured fairly

1. **Status taxonomy** — 670 replacement coordinates reclassified:
   - `not_measured` 260 (guided / unsupported) — **excluded from semantic rankings**
   - `runtime_failed` 210 (mostly `retry_exhausted`)
   - `semantic_scored` 200
2. **Model accept rates** — reported per model arm as
   `semantic_scored / (semantic_scored + runtime_failed)`, separate from end-to-end loss.
3. **Selective repair activation** — fixture pack validation **passed** with
   3 triggered / 3 applied coordinates
   and 3 model calls (activation report
   `baguqeera6pubyat2ea2d5lujvdr4o4pjai6z5v5f2uc3l4rypv7lreehhosa`).
4. **Hybrid research re-run** — `hybrid__typed_deontic__no_repair__deterministic` and
   `hybrid__typed_deontic__optional_selective_repair__deterministic` both score
   mean end-to-end **0.088333**, identical to baseline under paired bootstrap
   (Δ = 0.0, CI [0, 0]).
5. **Constructor-only** — typed_deontic forward mean **0.085000**; modal_spacy forward
   mean **0.130833** (worse; CI for Δ entirely above zero).

## Ranked research improvements vs baseline

| Rank | Method | Mode | Paired Δ (primary) | Earned? | Action |
| ---: | --- | --- | --- | :---: | --- |
| 1 | `hybrid__typed_deontic__no_repair__deterministic` | hybrid | e2e Δ = 0.0 (CI [0, 0]) | no | Identity of production path; already canonical |
| 2 | `hybrid__typed_deontic__optional_selective_repair__deterministic` | hybrid | e2e Δ = 0.0 (CI [0, 0]) | no | Optional research composition only; not default |
| 3 | `constructor_only__modal_spacy_candidate` | constructor_only | forward Δ ≈ +0.046 (CI above 0) | no | Do not compose; keep as research constructor metric only |

## Composition plan (production path)

### Keep (production)

| Component | Method | Rationale |
| --- | --- | --- |
| Constructor | `typed_deontic` (no guidance) | Lowest fair semantic loss; gate-eligible |
| Repair | **none** (default) | Selective optional path does not improve loss on pilot; activation is proven but not beneficial by default |
| Realizer | deterministic source-withheld paraphraser | Stable cycle loss; no model accept/retry risk |
| Validators | Hammer/cvc5 + Lean post-hoc / admission | Structural admission gates only — never score proof pass as semantic win |

### Do not compose into production (yet)

| Method | Why not earned |
| --- | --- |
| Guided autoencoder arms | `not_measured` / `unavailable_no_reviewed_causal_l1_adapter` |
| modal_spacy constructor | Higher forward loss vs typed_deontic under paired bootstrap |
| Leanstral direct / SyMAI constructors & realizers | Higher e2e loss among `semantic_scored`; material `retry_exhausted_rate`; accept_rate ≠ promotion |
| Always-on model arms | Same; no baseline beat under fair status filter |
| Selective repair as **default** | Activation proven, but pilot hybrid path is exact tie (not improvement) |

### Optional research compositions (non-production)

1. **Selective repair on trigger-bearing packs** — keep the activation harness and
   hybrid selective arm for experiments; require paired bootstrap before any
   “beats baseline” claim; use structural admission (Hammer/cvc5/Lean) to reject
   unsafe repairs.
2. **Constructor-only stage metrics** — continue scoring modal_spacy / model
   constructors on forward loss without full round-trip eligibility; promotion
   still requires full gates.
3. **Model recovery research policy** — track `accept_rate` and
   `retry_exhausted_rate` separately; do not fold retries into semantic loss.
4. **Causal guidance** — remains off the semantic schedule until a reviewed L1
   adapter contract lands (`scored_supported`).

## Implementation backlog suggested by this eval

| Priority | Work item | Success signal |
| --- | --- | --- |
| P0 | Keep production path frozen at typed_deontic + deterministic realizer | No silent substitution |
| P1 | Improve Leanstral recovery accept_rate under promotion retry budget | Higher accept_rate **and** e2e ≤ baseline with paired CI |
| P1 | Trigger-aware selective repair on real pilot diagnostics (not only fixture pack) | `repair_triggered` on pilot + paired e2e CI high < 0 |
| P2 | Reviewed causal L1 adapter for guided arms | Guided cells `scored_supported` rather than `not_measured` |
| P2 | modal_spacy residual polarity / facet gaps by case ID | constructor_only forward ≤ typed_deontic on paired bootstrap |
| P3 | Expand pilot/holdout only after research method beats baseline fail-closed | Holdout protocol + frozen gates |

## Explicit non-goals

- Do not rewrite the immutable 2026-07-27 replacement promotion report.
- Do not treat historical loss 1.0 on guided arms as semantic defeats of the baseline.
- Do not promote on accept_rate, solver proof, or activation alone.
- Do not schedule guided cells for semantic scoring without causal qualification.

## Evidence binding

| Artifact | Path / CID |
| --- | --- |
| Research matrix report | `docs/performance_snapshots/2026-07-27_semantic_roundtrip_eval_repair_matrix.json` |
| Report CID | `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza` |
| Human results | `docs/benchmarks/semantic_roundtrip_eval_repair_results.md` |
| This plan | `docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md` |
| Source replacement report CID | `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga` |
| Causal qualification CID | `baguqeerazzwzs54m7tolyu5g3he5km3fdr7eateaibpuifa2zkyekd6hek5q` |
| Selective activation CID | `baguqeera6pubyat2ea2d5lujvdr4o4pjai6z5v5f2uc3l4rypv7lreehhosa` |

## Bottom line

**Methods earned into the production path:** none beyond the existing
typed_deontic → deterministic realizer baseline.

**Methods earned supporting roles only:**

- Hammer/cvc5 and Lean as **repair admission gates** (not semantic scorers)
- Selective repair as **activation-proven optional research path** (not default)
- Status taxonomy + accept_rate + stage metrics as **measurement infrastructure**

Revisit composition only when a candidate shows `semantic_scored` evidence and a
paired bootstrap CI entirely below zero versus
`typed_deontic__no_guidance__no_repair__not_applicable__deterministic`.
