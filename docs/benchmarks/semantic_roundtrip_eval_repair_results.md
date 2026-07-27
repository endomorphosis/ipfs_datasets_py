# Semantic round-trip eval-repair research matrix results

**Interface:** `EvalRepairMatrixReport@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-eval-repair-matrix.v1`  
**Task:** EVAL-009  
**Report CID:** `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`  
**Captured:** 2026-07-27T18:32:07.994138+00:00

This research report reclassifies the immutable 2026-07-27 replacement shell with the
EVAL-001 status taxonomy, re-runs hybrid and constructor_only research modes on the
five pilot cases, and ranks improvements against the typed_deontic deterministic
baseline with paired case-cluster bootstrap.

The frozen promotion report is **not** rewritten:

- Replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
- Path: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

## Status taxonomy

| Status | Coordinate count | Meaning |
| --- | ---: | --- |
| `not_measured` | 260 | terminal_unsupported / preflight_blocked — never fairly measured |
| `runtime_failed` | 210 | retry_exhausted / provider boundary |
| `semantic_scored` | 200 | success with defined gates |

Reason counts: `{"retry_exhausted": 210, "success": 200, "terminal_unsupported": 260}`.

Leaderboard policy:

- Admits **only** `semantic_scored` coordinates.
- **Excludes** `not_measured` (and runtime failures) from semantic rankings.
- Historical constants match: scheduled 670, not_measured 260, runtime_failed 210, semantic_scored 200 → `{'not_measured': True, 'runtime_failed': True, 'scheduled': True, 'semantic_scored': True}`.

Arms excluded entirely from semantic rankings (no `semantic_scored` coordinates): 12 (guided / unsupported).

## Deterministic baseline (semantic_scored only)

Arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`

| Metric | Mean loss |
| --- | ---: |
| Forward | 0.085000 |
| Cycle | 0.003333 |
| End-to-end | 0.088333 |

## Semantic rankings (excludes not_measured)

Policy: mean end-to-end among **semantic_scored** coordinates only; lower is better.

| Rank | Arm | Scored n | Forward | Cycle | End-to-end | Gate-eligible scored | Model calls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 5 | 0.085000 | 0.003333 | 0.088333 | 5 | 0 |
| 2 | `typed_deontic__no_guidance__selective__not_applicable__deterministic` | 25 | 0.085000 | 0.003333 | 0.088333 | 25 | 0 |
| 3 | `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 0.000000 | 0.100000 | 0.100000 | 5 | 45 |
| 4 | `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 0.000000 | 0.100000 | 0.100000 | 5 | 45 |
| 5 | `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 10 | 0.070833 | 0.072727 | 0.141667 | 10 | 40 |
| 6 | `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 10 | 0.070833 | 0.072727 | 0.141667 | 10 | 40 |
| 7 | `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 10 | 0.131250 | 0.050000 | 0.181250 | 5 | 40 |
| 8 | `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 10 | 0.131250 | 0.050000 | 0.181250 | 5 | 40 |
| 9 | `modal_spacy__no_guidance__no_repair__not_applicable__deterministic` | 5 | 0.167500 | 0.053718 | 0.212308 | 1 | 0 |
| 10 | `modal_spacy__no_guidance__selective__not_applicable__deterministic` | 25 | 0.167500 | 0.053718 | 0.212308 | 5 | 0 |
| 11 | `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 15 | 0.176389 | 0.105556 | 0.237500 | 5 | 35 |
| 12 | `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 15 | 0.176389 | 0.105556 | 0.237500 | 5 | 35 |
| 13 | `model__not_applicable__always_on__direct__leanstral_symai` | 5 | 0.150000 | 0.200000 | 0.250000 | 5 | 75 |
| 14 | `model__not_applicable__always_on__direct__deterministic` | 15 | 0.482292 | 0.075000 | 0.432292 | 10 | 75 |
| 15 | `model__not_applicable__always_on__symai__leanstral_direct` | 5 | 0.200000 | 0.250000 | 0.450000 | 5 | 80 |
| 16 | `model__not_applicable__always_on__symai__leanstral_symai` | 5 | 0.200000 | 0.250000 | 0.450000 | 5 | 75 |
| 17 | `model__not_applicable__always_on__direct__leanstral_direct` | 10 | 0.325000 | 0.200000 | 0.462500 | 10 | 90 |
| 18 | `model__not_applicable__always_on__symai__deterministic` | 20 | 0.519844 | 0.072188 | 0.502969 | 10 | 65 |

## Model arm accept rates

Definition: `accept_rate = semantic_scored / (semantic_scored + runtime_failed)`.  
`not_measured` coordinates are **excluded** from the denominator.  
`retry_exhausted_rate` uses the same attempted denominator.

| Arm | accept_rate | retry_exhausted_rate | success | retry_exhausted | attempted | not_measured | model_calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `model__not_applicable__always_on__symai__deterministic` | 0.800000 | 0.200000 | 20 | 5 | 25 | 0 | 65 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 0.600000 | 0.400000 | 15 | 10 | 25 | 0 | 35 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 0.600000 | 0.400000 | 15 | 10 | 25 | 0 | 35 |
| `model__not_applicable__always_on__direct__deterministic` | 0.600000 | 0.400000 | 15 | 10 | 25 | 0 | 75 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 0.400000 | 0.600000 | 10 | 15 | 25 | 0 | 40 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 0.400000 | 0.600000 | 10 | 15 | 25 | 0 | 40 |
| `model__not_applicable__always_on__direct__leanstral_direct` | 0.400000 | 0.600000 | 10 | 15 | 25 | 0 | 90 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 0.400000 | 0.600000 | 10 | 15 | 25 | 0 | 40 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 0.400000 | 0.600000 | 10 | 15 | 25 | 0 | 40 |
| `model__not_applicable__always_on__direct__leanstral_symai` | 0.200000 | 0.800000 | 5 | 20 | 25 | 0 | 75 |
| `model__not_applicable__always_on__symai__leanstral_direct` | 0.200000 | 0.800000 | 5 | 20 | 25 | 0 | 80 |
| `model__not_applicable__always_on__symai__leanstral_symai` | 0.200000 | 0.800000 | 5 | 20 | 25 | 0 | 75 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 0.200000 | 0.800000 | 5 | 20 | 25 | 0 | 45 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 0.200000 | 0.800000 | 5 | 20 | 25 | 0 | 45 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_direct` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_symai` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `modal_spacy__guided__selective__not_applicable__leanstral_direct` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `modal_spacy__guided__selective__not_applicable__leanstral_symai` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_direct` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_symai` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `typed_deontic__guided__selective__not_applicable__leanstral_direct` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |
| `typed_deontic__guided__selective__not_applicable__leanstral_symai` | n/a | n/a | 0 | 0 | 0 | 25 | 0 |

## Selective repair activation

| Field | Value |
| --- | --- |
| Fixture pack | `selective-repair-activation-fixture-pack@1` |
| Validation passed | `True` |
| Activation report CID | `baguqeera6pubyat2ea2d5lujvdr4o4pjai6z5v5f2uc3l4rypv7lreehhosa` |
| Repair triggered count | 3 |
| Repair applied count | 3 |
| Model calls total | 3 |
| Any repair triggered | True |

| Case | repair_triggered | repair_applied | model_calls | trigger_kinds | only_triggered_fields_changed |
| --- | :---: | :---: | ---: | --- | :---: |
| `missing_temporal` | True | True | 1 | missing | True |
| `low_confidence_object` | True | True | 1 | low_confidence | True |
| `contradictory_modality` | True | True | 1 | contradictory, missing | True |

Historical note: the 2026-07-27 selective deterministic promotion arm
`typed_deontic__no_guidance__selective__not_applicable__deterministic` matched baseline
loss with **model_calls=0** on pilot cases (no triggers). The activation fixture pack
now proves triggers fire and repairs apply when missing temporal / low-confidence /
contradictory slots are present.

## Research matrix re-run (hybrid + constructor_only)

Pilot cases: `exception_with_window`, `legal_doc_1`, `exec_order_1`, `corp_policy_1`, `construction_contract`.  
Live smoke routes: `{"direct": {"model_inference_performed": true, "status": "passed"}, "symai": {"model_inference_performed": true, "status": "passed"}}`.

| Arm | Scored | Forward | Cycle | End-to-end | Statuses | Repair statuses |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `hybrid__typed_deontic__no_repair__deterministic` | 5 | 0.085000 | 0.003333 | 0.088333 | {'semantic_scored': 5} | {'not_applicable': 5} |
| `hybrid__typed_deontic__optional_selective_repair__deterministic` | 5 | 0.085000 | 0.003333 | 0.088333 | {'semantic_scored': 5} | {'not_triggered': 5} |
| `constructor_only__typed_deontic_baseline` | 5 | 0.085000 | n/a | n/a | {'semantic_scored': 5} | {'None': 5} |
| `constructor_only__modal_spacy_candidate` | 5 | 0.130833 | n/a | n/a | {'semantic_scored': 5} | {'None': 5} |

## Baseline delta tables (paired bootstrap)

Paired case-cluster bootstrap; **candidate − baseline**. Negative delta means lower loss (better).  
A candidate **beats baseline** only when the 95% CI is entirely below zero (`high < 0`).

Hybrid bootstrap report CID: `baguqeeravum2wsad5vasrvx6nqxae2dx5n43myktz2blji6n4vqs4lp7tara`  
Constructor-only bootstrap report CID: `baguqeeralquird3ferxqtfnaupox3iolmjezmsxtx5aqafps2fhseblncc7q`

### Hybrid vs typed_deontic deterministic baseline

| Candidate | Baseline | Forward Δ (CI) | Cycle Δ (CI) | End-to-end Δ (CI) | Beats baseline (e2e CI high < 0) |
| --- | --- | --- | --- | --- | :---: |
| `hybrid__typed_deontic__no_repair__deterministic` | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] | no |
| `hybrid__typed_deontic__optional_selective_repair__deterministic` | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] | no |


### Constructor-only vs typed_deontic constructor baseline

| Candidate | Baseline | Forward Δ (CI) | Cycle Δ (CI) | End-to-end Δ (CI) | Beats baseline (e2e CI high < 0) |
| --- | --- | --- | --- | --- | :---: |
| `constructor_only__modal_spacy_candidate` | `constructor_only__typed_deontic_baseline` | 0.045833 [0.020000, 0.075833] | 0.000000 [0.000000, 0.000000] | 0.045833 [0.017500, 0.075833] | no |


## Improvement ranking

| Rank | Candidate | Mode | Δ end-to-end | Δ forward | Earned production composition |
| ---: | --- | --- | ---: | ---: | :---: |
| 1 | `hybrid__typed_deontic__no_repair__deterministic` | hybrid | 0.000000 | 0.000000 | no |
| 2 | `hybrid__typed_deontic__optional_selective_repair__deterministic` | hybrid | 0.000000 | 0.000000 | no |
| 3 | `constructor_only__modal_spacy_candidate` | constructor_only | 0.045833 | 0.045833 | no |

## Production composition decision

- Canonical production path: **typed_deontic → CanonicalRuleIR → deterministic realizer (no guidance, no repair)**
- Production promotion authorized by this research matrix: **False**
- Selection policy: Fail-closed: only methods with semantic_scored evidence and paired-bootstrap CI entirely below zero vs typed_deontic deterministic baseline may earn composition into the production path. Full selection gates still apply for promotion.

### Methods that earned composition into the production path

- **None.** No optional method strictly beat the typed_deontic deterministic baseline under paired bootstrap (CI entirely below zero).

### Methods evaluated but not earned

- `hybrid__typed_deontic__no_repair__deterministic` (hybrid): Δe2e=0.000000, Δforward=0.000000 — did not strictly beat typed_deontic deterministic baseline under paired case-cluster bootstrap (lower loss is better; require CI high < 0)
- `hybrid__typed_deontic__optional_selective_repair__deterministic` (hybrid): Δe2e=0.000000, Δforward=0.000000 — did not strictly beat typed_deontic deterministic baseline under paired case-cluster bootstrap (lower loss is better; require CI high < 0)
- `constructor_only__modal_spacy_candidate` (constructor_only): Δe2e=0.045833, Δforward=0.045833 — did not strictly beat typed_deontic deterministic baseline under paired case-cluster bootstrap (lower loss is better; require CI high < 0)

### Structural admission (Hammer / cvc5 / Lean)

- Earned role: `repair_admission_gate_only`
- Not earned: `semantic_loss_replacement`
- Hammer/cvc5 and Lean may reject unsafe repairs before they affect T1/L2; proof pass is never scored as lower end-to-end loss by itself.

### Guided autoencoder

- Status: `not_measured` / `unavailable_no_reviewed_causal_l1_adapter`
- Earned composition: **False**
- Reason: `unavailable_no_reviewed_causal_l1_adapter`

### Selective repair

- Activation proven: **True**
- Earned default production composition: **False**
- Selective repair activation is proven on the fixture pack, but on pilot cases the optional selective hybrid path does not improve loss versus typed_deontic deterministic baseline under paired bootstrap. Keep as optional research composition; do not change the default production path.

### Model constructors / realizers

- Earned composition: **False**
- Model-backed arms remain below baseline on semantic_scored end-to-end loss and exhibit material retry_exhausted mass; accept_rate is reported separately from end-to-end loss and does not authorize promotion.

## Acceptance checklist

| Criterion | Met |
| --- | :---: |
| Excludes not_measured from semantic rankings | yes |
| Reports accept_rate for model arms | yes |
| Reports repair activation for selective arms | yes |
| Ranks hybrid and constructor_only vs baseline with paired bootstrap | yes |
| Improvement plan names methods earned into production path | yes |
| Status taxonomy fields present | yes |
| Baseline delta tables present | yes |
| Immutable 2026-07-27 replacement promotion report preserved | yes |

## Evidence

- Machine-readable report: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_eval_repair_matrix.json`
- Report CID: `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`
- Improvement plan: `docs/benchmarks/semantic_roundtrip_improvement_plan_from_eval.md`
- Causal qualification CID: `baguqeerazzwzs54m7tolyu5g3he5km3fdr7eateaibpuifa2zkyekd6hek5q`
