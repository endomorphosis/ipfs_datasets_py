# Semantic round-trip holdout remeasure results

**Interface:** `EvalRepairMatrixReport@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-holdout-remeasure.v1`  
**Task:** PLAT2-060  
**Report CID:** `baguqeerau65iz4iqqla473n4n6u23yf6w6v5bfb3lsi72sofsvldgyostl5q`  
**Promotion decision CID:** `baguqeeraqbln33vkic4t3oihu3myudcmk5r63cwmj53dsgz6hwpjnagpddfq`  
**Captured:** 2026-07-28T05:10:24.861+00:00

This research receipt re-scores the **preregistered holdout** deterministic path
after det edit waves PLAT2-050 (`low_confidence_object`, `contradictory_modality`),
re-checks the five sealed pilots for non-regression (mean e2e must remain **0.0**),
compares holdout losses to the **declared post-pilot baseline (e2e = 0.0)** with
paired case-cluster bootstrap, and records a fail-closed promotion decision.

The immutable 2026-07-27 replacement promotion report is **not** rewritten:

- Replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
- Path: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

## Decision

| Field | Value |
| --- | --- |
| Production promotion authorized | **False** |
| E2e CI high &lt; 0 vs declared 0.0 | **False** (high = 0.268750) |
| Full gates pass | **True** (holdout smoke = `passed`) |
| Pilots non-regressed (mean e2e 0.0) | **True** |
| Remeasured holdout mean e2e | **0.155000** |
| Declared baseline mean e2e | **0.000000** |
| Mean Δ e2e (candidate − baseline) | **0.155000** |
| Selected production arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Next residuals | 11 named facet residual(s) across 4 case(s) |

Promotion rule (fail-closed): **true only if** e2e bootstrap CI high &lt; 0 **and**
full selection gates pass (and pilots remain non-regressed); otherwise **false**
with named next residuals.

## Status taxonomy (this remeasure)

| Status | Coordinate count | Meaning |
| --- | ---: | --- |
| `semantic_scored` | 13 | Holdout det path (8) + pilot non-regression (5) |
| `not_measured` | 0 | None of the coordinates scheduled in this holdout remeasure |
| `runtime_failed` | 0 | None |

Leaderboard policy:

- Admits **only** `semantic_scored` coordinates.
- **Excludes** `not_measured` (and runtime failures) from semantic rankings.
- Optional / guided / full-matrix arms not re-run here remain outside rankings.

## Declared post-pilot baseline

Arm claim: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` achieves mean e2e **0.0** on sealed pilots (PLAT-090).  
Holdout declared baseline constant: **0.0** per case.  
Baseline report CID: `baguqeerag7kwogvfkjciwoovp6cvpl5pueaoweucfqzjhbl4j6vhq5n5xn7q`

| Metric | Declared baseline mean |
| --- | ---: |
| Forward | 0.000000 |
| Cycle | 0.000000 |
| End-to-end | 0.000000 |

### Sealed residual-catalog prior (activation subset only)

Catalog CID: `baguqeeradibc5tj2rx2wkdppnbktk4dlpl6og54c6pilkrk7e24kbd3bofha`  
(Used as secondary lineage for PLAT2-050 edit-wave deltas; **not** the promotion gate.)

| Case | Prior forward | Prior residual count |
| --- | ---: | ---: |
| `missing_temporal` | 0.000000 | 0 |
| `low_confidence_object` | 0.100000 | 1 |
| `contradictory_modality` | 0.500000 | 1 |

## Holdout det path remeasure

Arm under test: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`  
(production det path after PLAT2-050 holdout edit waves)

| Case | Status | Forward | Cycle | End-to-end | Δ e2e vs 0.0 | Residuals now |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `missing_temporal` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 |
| `low_confidence_object` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 |
| `contradictory_modality` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 |
| `legal_doc_2` | semantic_scored | 0.300000 | 0.000000 | 0.300000 | 0.300000 | 3 |
| `privacy_act_amendment` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 |
| `fed_reg_1` | semantic_scored | 0.260000 | 0.000000 | 0.260000 | 0.260000 | 4 |
| `dept_memo_1` | semantic_scored | 0.250000 | 0.000000 | 0.250000 | 0.250000 | 1 |
| `hr_handbook` | semantic_scored | 0.420000 | 0.016667 | 0.430000 | 0.430000 | 3 |

| Metric | Remeasured holdout mean |
| --- | ---: |
| Forward | 0.153750 |
| Cycle | 0.002083 |
| End-to-end | 0.155000 |

## Pilot non-regression re-check

Required: mean pilot e2e remains **0.0** after holdout edit waves.

| Case | Forward | Cycle | End-to-end | Non-regressed |
| --- | ---: | ---: | ---: | :---: |
| `exception_with_window` | 0.000000 | 0.000000 | 0.000000 | True |
| `exec_order_1` | 0.000000 | 0.000000 | 0.000000 | True |
| `corp_policy_1` | 0.000000 | 0.000000 | 0.000000 | True |
| `legal_doc_1` | 0.000000 | 0.000000 | 0.000000 | True |
| `construction_contract` | 0.000000 | 0.000000 | 0.000000 | True |

| Metric | Pilot mean |
| --- | ---: |
| Forward | 0.000000 |
| Cycle | 0.000000 |
| End-to-end | 0.000000 |

## Semantic rankings (excludes not_measured)

Policy: mean end-to-end among **semantic_scored** holdout coordinates; lower is better.

| Rank | Arm | Scored n | Forward | Cycle | End-to-end | Model calls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` (holdout) | 8 | 0.153750 | 0.002083 | 0.155000 | 0 |

## Baseline delta tables (paired bootstrap)

Paired case-cluster bootstrap; **candidate − declared baseline 0.0**. Negative delta
means lower loss (better). A candidate **beats baseline** only when the 95% CI
is entirely below zero (`high < 0`).

Hybrid/paired bootstrap report CID: `baguqeerab3auplramyh2kw6jywc7ylbe3dkdrmtmwsxuycot2rjfuqwbimra`  
Success authorization CID: `baguqeeravanbdfwjf67567txfsmomvyfmzu4ibyapzdy67y6vzlfvxrxmqsq`  
Bootstrap: method=`seeded_percentile_case_cluster_bootstrap`, samples=10000, seed=17291, confidence=0.95.

### Holdout det path vs declared post-pilot 0.0 baseline

| Candidate | Baseline | Forward Δ (CI) | Cycle Δ (CI) | End-to-end Δ (CI) | Beats baseline (e2e CI high &lt; 0) |
| --- | --- | --- | --- | --- | :---: |
| `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | declared post-pilot 0.0 | 0.153750 [0.037500, 0.268750] | 0.002083 [0.000000, 0.006250] | 0.155000 [0.037500, 0.268750] | no |

### Case-level e2e deltas vs declared 0.0

| Case | Δ end-to-end |
| --- | ---: |
| `contradictory_modality` | 0.000000 |
| `dept_memo_1` | 0.250000 |
| `fed_reg_1` | 0.260000 |
| `hr_handbook` | 0.430000 |
| `legal_doc_2` | 0.300000 |
| `low_confidence_object` | 0.000000 |
| `missing_temporal` | 0.000000 |
| `privacy_act_amendment` | 0.000000 |

### Secondary: activation subset vs sealed residual-catalog prior

Bootstrap report CID: `baguqeeran4ru75oiznfahwfqe4mtsojrxewk6dm3cittsso6aupdbpvoehfa`  
Authorization CID: `baguqeeraopnrj256n2t4npc7zgkivngt2fdhsrbuyfgvmil6sey4xxi2yruq`  
Mean Δ e2e: **-0.200000**  
CI: [-0.500000, 0.000000]  
Beats prior CI high &lt; 0: **False** (high = 0.0 is not &lt; 0)

PLAT2-050 cleared the two nonzero activation residuals to 0.0; this is lineage
evidence, not the PLAT2-060 promotion gate.

## Full selection gates (holdout)

Smoke interface: `HoldoutDeterministicSmoke@1`  
Smoke CID: `baguqeeraezjkuul7u3pbzp7g53wnwzq57pqts5hhucybzszpj35o3ywpom3a`  
Status: **passed**

| Case | nonempty L1/T1/L2 | full_coverage | source_copy_exclusion | polarity_preservation |
| --- | :---: | :---: | :---: | :---: |
| `missing_temporal` | True | True | True | True |
| `low_confidence_object` | True | True | True | True |
| `contradictory_modality` | True | True | True | True |
| `legal_doc_2` | True | True | True | True |
| `privacy_act_amendment` | True | True | True | True |
| `fed_reg_1` | True | True | True | True |
| `dept_memo_1` | True | True | True | True |
| `hr_handbook` | True | True | True | True |

## Edit-wave lineage

| Task | Case | Receipt CID | Implementable |
| --- | --- | --- | :---: |
| PLAT2-050 | `contradictory_modality` | `baguqeerabmuaey5svgiakecagca4hkeby54llqhlxorxurs677ohlsl3qsla` | True |
| PLAT2-050 | `low_confidence_object` | `baguqeerarn76cssfcgqtumrumdydvtifziirubxamjg3g5kc3d5yqleim6uq` | True |

Residual catalog CID: `baguqeeradibc5tj2rx2wkdppnbktk4dlpl6og54c6pilkrk7e24kbd3bofha`

## Production composition decision

- Canonical production path: **typed_deontic → CanonicalRuleIR → deterministic realizer (no guidance, no repair)**
- Production promotion authorized by this holdout remeasure: **False**
- Selection policy: Fail-closed; e2e paired-bootstrap CI high &lt; 0 vs declared post-pilot 0.0 **and** full gates required; pilots must remain non-regressed.
- Optional methods (spaCy / AE / Leanstral / SyMAI / selective repair) remain **teachers/gates only**.

### Methods that earned composition into the production path

- `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` — remains the production det path; holdout mean e2e **0.155000** does **not** beat declared 0.0 with CI high &lt; 0, so **no additional promotion claim** is authorized by PLAT2-060.

### Structural admission (Hammer / cvc5 / Lean)

- Earned role: `repair_admission_gate_only`
- Not earned: `semantic_loss_replacement`
- Proof pass is never scored as lower end-to-end loss by itself.

### Guided autoencoder / selective repair

- Default production composition: **False** (no-repair deterministic remains default)
- Not re-scored as production candidates in PLAT2-060

## Next residuals

**11 named residual(s)** remaining on holdout legal-corpus cases (`dept_memo_1`, `fed_reg_1`, `hr_handbook`, `legal_doc_2`). These are the next residual → packet → det-edit targets.

| Case | Field path | Kind | Canonical field | Loss contrib | Case e2e |
| --- | --- | --- | --- | ---: | ---: |
| `legal_doc_2` | `rules[2]` | `missing_rule` | `None` | 0.250000 | 0.300000 |
| `legal_doc_2` | `rules[3].conditions` | `field_mismatch` | `conditions` | 0.025000 | 0.300000 |
| `legal_doc_2` | `rules[3].temporal` | `field_mismatch` | `temporal` | 0.025000 | 0.300000 |
| `fed_reg_1` | `rules[3]` | `missing_rule` | `None` | 0.200000 | 0.260000 |
| `fed_reg_1` | `rules[2].object` | `field_mismatch` | `object` | 0.020000 | 0.260000 |
| `fed_reg_1` | `rules[4].conditions` | `field_mismatch` | `conditions` | 0.020000 | 0.260000 |
| `fed_reg_1` | `rules[4].temporal` | `field_mismatch` | `temporal` | 0.020000 | 0.260000 |
| `dept_memo_1` | `rules[2]` | `missing_rule` | `None` | 0.250000 | 0.250000 |
| `hr_handbook` | `rules[1]` | `missing_rule` | `None` | 0.200000 | 0.430000 |
| `hr_handbook` | `rules[3]` | `missing_rule` | `None` | 0.200000 | 0.430000 |
| `hr_handbook` | `rules[0].object` | `field_mismatch` | `object` | 0.020000 | 0.430000 |

## Acceptance checklist

| Criterion | Met |
| --- | :---: |
| Per-case loss tables for holdout | yes |
| Pilots re-checked non-regressed (mean e2e 0.0) | yes |
| Paired bootstrap vs declared baseline | yes |
| Promotion true only if CI high &lt; 0 and full gates | yes (promotion=False) |
| Named next residuals when not promoted | yes |
| Immutable 2026-07-27 replacement report not rewritten | yes |

## Reproduction

```bash
PYTHONPATH=. python -m pytest \
  tests/unit/benchmarks/semantic_roundtrip/test_hybrid_arms.py \
  tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
```
