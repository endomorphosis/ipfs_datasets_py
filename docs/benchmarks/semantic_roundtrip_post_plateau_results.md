# Semantic round-trip post-plateau full research matrix results

**Interface:** `EvalRepairMatrixReport@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-post-plateau-matrix.v1`  
**Task:** PLAT-091  
**Report CID:** `baguqeerag7kwogvfkjciwoovp6cvpl5pueaoweucfqzjhbl4j6vhq5n5xn7q`  
**Captured:** 2026-07-28T01:31:51.063+00:00

This research receipt refreshes the **full 670-cell** status-taxonomized research
matrix **after** the production det path plateau broke (PLAT-090). It re-ranks
optional methods fairly against the **post-plateau** baseline (mean e2e **0.0**),
retains the EVAL-001 status taxonomy, and applies **fail-closed** promotion rules.

The immutable 2026-07-27 replacement promotion report is **not** rewritten:

- Replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
- Path: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

## Eligibility gate

| Field | Value |
| --- | --- |
| Full matrix refresh allowed | **True** |
| Gate | `PLAT-090 production_promotion_authorized == true` |
| PLAT-090 promotion | **True** |
| PLAT-090 decision CID | `baguqeerahsrat44dqs3ypo2jodopcj6finktd2rcvvcsaatk4yndwvsmfwka` |
| Operator override | none |

Acceptance rule: **do not** run a full 670 re-rank unless PLAT-090 succeeded or an
explicit operator override is recorded. This receipt ran because PLAT-090 promotion
is **true**.

## Decision (fail-closed)

| Field | Value |
| --- | --- |
| Post-plateau production det path | **authorized** (from PLAT-090) |
| Optional runtime promotion | **False** |
| Any optional arm beats post-plateau baseline (e2e CI high < 0) | **False** |
| Selected production arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Post-plateau mean e2e | **0.000000** |
| Frozen pre-break mean e2e | **0.088333** |

Promotion rule (fail-closed): optional method production promotion is **true only if**
e2e bootstrap CI high &lt; 0 vs the **post-plateau** baseline **and** full selection
gates pass; `not_measured` is excluded from rankings; proof pass is never scored as
semantic loss reduction.

## Status taxonomy (670-cell shell)

| Status | Coordinate count | Meaning |
| --- | ---: | --- |
| `not_measured` | 260 | terminal_unsupported / preflight_blocked — never fairly measured |
| `runtime_failed` | 210 | retry_exhausted / provider boundary |
| `semantic_scored` | 200 | success with defined gates |
| **Scheduled** | **670** | sealed replacement shell |

Reason counts: `{"retry_exhausted": 210, "success": 200, "terminal_unsupported": 260}`.

Leaderboard policy:

- Admits **only** `semantic_scored` coordinates.
- **Excludes** `not_measured` (and runtime failures) from semantic rankings.
- Historical constants match: scheduled 670, not_measured 260, runtime_failed 210,
  semantic_scored 200.
- Arms excluded entirely from semantic rankings (no `semantic_scored` coordinates): 12 (guided / unsupported).

## Refresh methodology

- **Kind:** `post_plateau_research_matrix_refresh`
- **Live 670 model re-execution:** `False`
- **Status taxonomy source:** EVAL-009 reclassification of 2026-07-27 replacement shell
- **Production score source:** PLAT-090 pilot det path remeasure
- **Optional arm score source:** EVAL-009 semantic_scored aggregates from historical shell

PLAT-091 re-ranks the sealed 670-cell replacement shell under EVAL-001 status taxonomy after the production det path moved (PLAT-090). Deterministic production/selective det arms are overlaid with post-edit pilot remeasure scores (e2e=0). Optional model arm losses and accept rates retain EVAL-009/historical shell evidence and are re-ranked against the new baseline under fail-closed promotion rules. Live re-execution of all 650 model-backed coordinates is not required for this research re-rank receipt; status taxonomy constants remain sealed.

## Post-plateau production baseline

Arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`  
Source: PLAT-090 report CID `baguqeerazqjvhhlk7l2kiovwkmcoezbuodziikspu6564hxdoxaplazlrmpq`

| Metric | Mean loss |
| --- | ---: |
| Forward | 0.000000 |
| Cycle | 0.000000 |
| End-to-end | 0.000000 |

### Pilot det path (hybrid research mode)

| Arm | Scored n | Forward | Cycle | End-to-end |
| --- | ---: | ---: | ---: | ---: |
| `hybrid__typed_deontic__no_repair__deterministic` | 5 | 0.000000 | 0.000000 | 0.000000 |

### Constructor-only research modes

| Rank | Arm | Forward | Note |
| ---: | --- | ---: | --- |
| 1 | `constructor_only__typed_deontic_baseline` | 0.000000 | constructor_only |
| 2 | `constructor_only__modal_spacy_candidate` | 0.130833 | constructor_only |

## Semantic rankings (excludes not_measured)

Policy: mean end-to-end among **semantic_scored** coordinates only; lower is better.
Post-plateau production det path and selective-deterministic (untriggered) sit at e2e **0.0**.

| Rank | Arm | Scored n | Forward | Cycle | End-to-end | Gate-eligible scored | Model calls | Provenance |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 5 | 0.000000 | 0.000000 | 0.000000 | 5 | 0 | PLAT-090_pilot_det_path_remeasure |
| 1 | `typed_deontic__no_guidance__selective__not_applicable__deterministic` | 25 | 0.000000 | 0.000000 | 0.000000 | 25 | 0 | PLAT-090_pilot_det_path_remeasure |
| 3 | `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 0.000000 | 0.100000 | 0.100000 | 5 | 45 | EVAL-009_historical_shell_reclassified |
| 3 | `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 0.000000 | 0.100000 | 0.100000 | 5 | 45 | EVAL-009_historical_shell_reclassified |
| 5 | `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 10 | 0.070833 | 0.072727 | 0.141667 | 10 | 40 | EVAL-009_historical_shell_reclassified |
| 5 | `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 10 | 0.070833 | 0.072727 | 0.141667 | 10 | 40 | EVAL-009_historical_shell_reclassified |
| 7 | `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 10 | 0.131250 | 0.050000 | 0.181250 | 5 | 40 | EVAL-009_historical_shell_reclassified |
| 7 | `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 10 | 0.131250 | 0.050000 | 0.181250 | 5 | 40 | EVAL-009_historical_shell_reclassified |
| 9 | `modal_spacy__no_guidance__no_repair__not_applicable__deterministic` | 5 | 0.167500 | 0.053718 | 0.212308 | 1 | 0 | EVAL-009_historical_shell_reclassified |
| 9 | `modal_spacy__no_guidance__selective__not_applicable__deterministic` | 25 | 0.167500 | 0.053718 | 0.212308 | 5 | 0 | EVAL-009_historical_shell_reclassified |
| 11 | `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 15 | 0.176389 | 0.105556 | 0.237500 | 5 | 35 | EVAL-009_historical_shell_reclassified |
| 11 | `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 15 | 0.176389 | 0.105556 | 0.237500 | 5 | 35 | EVAL-009_historical_shell_reclassified |
| 13 | `model__not_applicable__always_on__direct__leanstral_symai` | 5 | 0.150000 | 0.200000 | 0.250000 | 5 | 75 | EVAL-009_historical_shell_reclassified |
| 14 | `model__not_applicable__always_on__direct__deterministic` | 15 | 0.482292 | 0.075000 | 0.432292 | 10 | 75 | EVAL-009_historical_shell_reclassified |
| 15 | `model__not_applicable__always_on__symai__leanstral_direct` | 5 | 0.200000 | 0.250000 | 0.450000 | 5 | 80 | EVAL-009_historical_shell_reclassified |
| 15 | `model__not_applicable__always_on__symai__leanstral_symai` | 5 | 0.200000 | 0.250000 | 0.450000 | 5 | 75 | EVAL-009_historical_shell_reclassified |
| 17 | `model__not_applicable__always_on__direct__leanstral_direct` | 10 | 0.325000 | 0.200000 | 0.462500 | 10 | 90 | EVAL-009_historical_shell_reclassified |
| 18 | `model__not_applicable__always_on__symai__deterministic` | 20 | 0.519844 | 0.072188 | 0.502969 | 10 | 65 | EVAL-009_historical_shell_reclassified |

## Paired comparisons vs post-plateau baseline

Delta = candidate − post-plateau baseline (0.0). **Beats baseline** only when e2e CI high &lt; 0.

| Candidate | Mean e2e | Δ e2e | CI high | Beats baseline |
| --- | ---: | ---: | ---: | :---: |
| `typed_deontic__no_guidance__selective__not_applicable__deterministic` | 0.000000 | 0.000000 | 0.000000 | no |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 0.100000 | 0.100000 | 1.000000 | no |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 0.100000 | 0.100000 | 1.000000 | no |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 0.141667 | 0.141667 | 1.000000 | no |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 0.141667 | 0.141667 | 1.000000 | no |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 0.181250 | 0.181250 | 1.000000 | no |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 0.181250 | 0.181250 | 1.000000 | no |
| `modal_spacy__no_guidance__no_repair__not_applicable__deterministic` | 0.212308 | 0.212308 | 0.257500 | no |
| `modal_spacy__no_guidance__selective__not_applicable__deterministic` | 0.212308 | 0.212308 | 0.259808 | no |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 0.237500 | 0.237500 | 0.870000 | no |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 0.237500 | 0.237500 | 0.870000 | no |
| `model__not_applicable__always_on__direct__leanstral_symai` | 0.250000 | 0.250000 | 1.000000 | no |
| `model__not_applicable__always_on__direct__deterministic` | 0.432292 | 0.432292 | 0.934375 | no |
| `model__not_applicable__always_on__symai__leanstral_direct` | 0.450000 | 0.450000 | 1.000000 | no |
| `model__not_applicable__always_on__symai__leanstral_symai` | 0.450000 | 0.450000 | 1.000000 | no |
| `model__not_applicable__always_on__direct__leanstral_direct` | 0.462500 | 0.462500 | 1.000000 | no |
| `model__not_applicable__always_on__symai__deterministic` | 0.502969 | 0.502969 | 0.870375 | no |

## Model arm accept rates

Definition: `accept_rate = semantic_scored / (semantic_scored + runtime_failed)`.  
`not_measured` coordinates are **excluded** from the denominator.

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

## Production composition decision

- Canonical production path: **typed_deontic → CanonicalRuleIR → deterministic realizer (no guidance, no repair)**
- Post-edit det path promotion (PLAT-090): **True**
- Optional runtime promotion: **False**
- Selection policy: Post-plateau research re-rank admits only semantic_scored coordinates. The post-edit typed_deontic deterministic path remains production. Optional spaCy/AE/Leanstral/SyMAI/selective-repair runtimes are not promoted.
- Promotion rule: fail-closed: optional method production promotion requires e2e paired-bootstrap CI high < 0 vs post-plateau baseline AND full selection gates; not_measured excluded from rankings; proof pass is never semantic loss reduction

### Methods that earned composition into the production path

- `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` — post-plateau production det path (pilot mean e2e **0.0**).

### Methods evaluated but not earned

Count: **17** optional/research arms with
`semantic_scored` evidence. None beat the post-plateau baseline under fail-closed CI rules.
Optional methods (spaCy / AE / Leanstral / SyMAI / selective repair defaults) remain
**teachers/gates only**.

### Structural admission (Hammer / cvc5 / Lean)

- Earned role: `repair_admission_gate_only`
- Not earned: `semantic_loss_replacement`
- Proof pass is never scored as lower end-to-end loss by itself.

### Guided autoencoder

- Status: `not_measured`
- Earned composition: **False**
- Reason: guided arms remain terminal_unsupported / preflight_blocked in 670 shell

### Selective repair

- Default production composition: **False**
- Note: Default production path remains no-repair deterministic; selective scores match when no residual triggers fire

## Acceptance checklist

| Criterion | Met |
| --- | :---: |
| Full 670 re-rank only after PLAT-090 success (or override) | yes |
| Status taxonomy retained (670/260/210/200) | yes |
| not_measured excluded from rankings | yes |
| Fail-closed promotion rules retained | yes |
| Optional methods not promoted without e2e CI high < 0 | yes |
| Immutable 2026-07-27 replacement promotion report preserved | yes |

## Evidence

- Machine-readable matrix: `docs/performance_snapshots/2026-07-28_semantic_roundtrip_post_plateau_matrix.json`
- Matrix report CID: `baguqeerag7kwogvfkjciwoovp6cvpl5pueaoweucfqzjhbl4j6vhq5n5xn7q`
- PLAT-090 matrix CID: `baguqeerazqjvhhlk7l2kiovwkmcoezbuodziikspu6564hxdoxaplazlrmpq`
- PLAT-090 promotion decision CID: `baguqeerahsrat44dqs3ypo2jodopcj6finktd2rcvvcsaatk4yndwvsmfwka`
- EVAL-009 report CID: `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`
- Immutable replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`

