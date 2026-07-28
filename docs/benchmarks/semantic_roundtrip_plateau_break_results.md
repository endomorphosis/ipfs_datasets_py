# Semantic round-trip plateau-break remeasure results

**Interface:** `EvalRepairMatrixReport@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-plateau-break-matrix.v1`  
**Task:** PLAT-090  
**Report CID:** `baguqeerazqjvhhlk7l2kiovwkmcoezbuodziikspu6564hxdoxaplazlrmpq`  
**Promotion decision CID:** `baguqeerahsrat44dqs3ypo2jodopcj6finktd2rcvvcsaatk4yndwvsmfwka`  
**Captured:** 2026-07-28T01:19:14.803+00:00

This research receipt re-scores the **pilot deterministic path** after det edit
waves PLAT-081 (legal_doc_1), PLAT-082 (construction_contract), and PLAT-083
(corp_policy_1), compares it to the frozen plateau baseline (**e2e ≈ 0.088**)
with paired case-cluster bootstrap, and records a fail-closed promotion
decision.

The immutable 2026-07-27 replacement promotion report is **not** rewritten:

- Replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
- Path: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

## Decision

| Field | Value |
| --- | --- |
| Production promotion authorized | **True** |
| E2e CI high < 0 vs frozen 0.088 | **True** (high = -0.040000) |
| Full gates pass | **True** (smoke = `passed`) |
| Remeasured mean e2e | **0.000000** |
| Frozen baseline mean e2e | **0.088333** |
| Mean Δ e2e (candidate − baseline) | **-0.088333** |
| Selected production arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Next residuals | 0 named facet residual(s) |

Promotion rule (fail-closed): **true only if** e2e bootstrap CI high &lt; 0 **and**
full selection gates pass; otherwise **false** with named next residuals.

## Status taxonomy (this remeasure)

| Status | Coordinate count | Meaning |
| --- | ---: | --- |
| `semantic_scored` | 15 | Hybrid det path (5) + constructor_only typed_deontic (5) + constructor_only modal_spacy (5) |
| `not_measured` | 0 | None of the coordinates scheduled in this pilot remeasure |
| `runtime_failed` | 0 | None |

Leaderboard policy:

- Admits **only** `semantic_scored` coordinates.
- **Excludes** `not_measured` (and runtime failures) from semantic rankings.
- Optional / guided / full-matrix arms not re-run here remain outside rankings
  (deferred to PLAT-091 if promotion is true).

## Frozen plateau baseline (EVAL-009 / residual catalog)

Arm: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`  
Baseline report CID: `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`

| Metric | Mean loss |
| --- | ---: |
| Forward | 0.085000 |
| Cycle | 0.003333 |
| End-to-end | 0.088333 |

### Per-case frozen baseline

| Case | Forward | Cycle | End-to-end | Residuals |
| --- | ---: | ---: | ---: | ---: |
| `exception_with_window` | 0.000000 | 0.000000 | 0.000000 | 0 |
| `legal_doc_1` | 0.133333 | 0.016667 | 0.150000 | 4 |
| `exec_order_1` | 0.050000 | 0.000000 | 0.050000 | 2 |
| `corp_policy_1` | 0.100000 | 0.000000 | 0.100000 | 4 |
| `construction_contract` | 0.141667 | 0.000000 | 0.141667 | 8 |

## Pilot det path remeasure (hybrid + production identity)

Arm under test: `hybrid__typed_deontic__no_repair__deterministic`  
(research measurement of the production det path after PLAT-081/082/083)

| Case | Status | Forward | Cycle | End-to-end | Δ e2e | Residuals now |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `exception_with_window` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 |
| `legal_doc_1` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | -0.150000 | 0 |
| `exec_order_1` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | -0.050000 | 0 |
| `corp_policy_1` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | -0.100000 | 0 |
| `construction_contract` | semantic_scored | 0.000000 | 0.000000 | 0.000000 | -0.141667 | 0 |

| Metric | Remeasured mean |
| --- | ---: |
| Forward | 0.000000 |
| Cycle | 0.000000 |
| End-to-end | 0.000000 |

## Constructor-only remeasure

| Arm | Scored n | Mean forward | Cycle | End-to-end |
| --- | ---: | ---: | --- | --- |
| `constructor_only__typed_deontic_baseline` | 5 | 0.000000 | n/a | n/a |
| `constructor_only__modal_spacy_candidate` | 5 | 0.130833 | n/a | n/a |

## Semantic rankings (excludes not_measured)

Policy: mean end-to-end among **semantic_scored** coordinates only (constructor_only
rows ranked by forward); lower is better.

| Rank | Arm | Scored n | Forward | Cycle | End-to-end | Model calls |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` (post-edit) | 5 | 0.000000 | 0.000000 | 0.000000 | 0 |
| 1 | `hybrid__typed_deontic__no_repair__deterministic` | 5 | 0.000000 | 0.000000 | 0.000000 | 0 |
| 3 | `constructor_only__typed_deontic_baseline` | 5 | 0.000000 | n/a | n/a | 0 |
| 4 | `constructor_only__modal_spacy_candidate` | 5 | 0.130833 | n/a | n/a | 0 |

Arms excluded from rankings (not remeasured / not_measured this task): guided
autoencoder paths, full optional model matrix, selective hybrid pilot path.

## Baseline delta tables (paired bootstrap)

Paired case-cluster bootstrap; **candidate − frozen baseline**. Negative delta
means lower loss (better). A candidate **beats baseline** only when the 95% CI
is entirely below zero (`high < 0`).

Hybrid bootstrap report CID: `baguqeera7jbv4cfvmomf3i2vcgfrst65sdmb6gnyxm7hyuwc65tam3gtwpiq`  
Success authorization CID: `baguqeeraeb3gokw6dasd3v5b5walt6vcf23riyyws46ymtnmpcnl4xwkkn4a`  
Bootstrap: method=`seeded_percentile_case_cluster_bootstrap`, samples=10000, seed=17291, confidence=0.95.

### Hybrid det path vs frozen typed_deontic 0.088 baseline

| Candidate | Baseline | Forward Δ (CI) | Cycle Δ (CI) | End-to-end Δ (CI) | Beats baseline (e2e CI high < 0) |
| --- | --- | --- | --- | --- | :---: |
| `hybrid__typed_deontic__no_repair__deterministic` | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` (frozen) | -0.085000 [-0.130000, -0.036667] | -0.003333 [-0.010000, 0.000000] | -0.088333 [-0.136667, -0.040000] | yes |

### Case-level e2e deltas

| Case | Δ end-to-end |
| --- | ---: |
| `exception_with_window` | 0.000000 |
| `legal_doc_1` | -0.150000 |
| `exec_order_1` | -0.050000 |
| `corp_policy_1` | -0.100000 |
| `construction_contract` | -0.141667 |

## Full selection gates

Smoke interface: `ReplacementDeterministicPilotSmoke@1`  
Smoke CID: `baguqeeraiy3s54wnug2vsgjyypkwi4cx3gnxwxqxqewxhs6vqqy56oelsoua`  
Status: **passed**

| Case | nonempty L1/T1/L2 | full_coverage | source_copy_exclusion | polarity_preservation |
| --- | :---: | :---: | :---: | :---: |
| `exception_with_window` | True | True | True | True |
| `legal_doc_1` | True | True | True | True |
| `exec_order_1` | True | True | True | True |
| `corp_policy_1` | True | True | True | True |
| `construction_contract` | True | True | True | True |

## Edit-wave lineage

| Task | Case | Receipt CID | Implementable |
| --- | --- | --- | :---: |
| PLAT-081 | `legal_doc_1` | `baguqeerafzaqfs26bovklw4lbhrauqkz25d2mktgnv3po64sncgusbukikwq` | True |
| PLAT-082 | `construction_contract` | `baguqeera3iqbkg7rnsdtw2qqiwy2yyva4iulz5ujjec453u572vd4rrnlqza` | True |
| PLAT-083 | `corp_policy_1` | `baguqeeraxo3kidzq7lazgdmof7nf2qawebub2bftvyrztny5kk7slu475nwq` | True |

Residual catalog CID: `baguqeerar435zxtsbiiilmv6bvtmqbiz7vlvhz4kq64rekbavz7zvuaf4mhq`

## Production composition decision

- Canonical production path: **typed_deontic → CanonicalRuleIR → deterministic realizer (no guidance, no repair)**
- Production promotion authorized by this plateau-break remeasure: **True**
- Selection policy: Fail-closed; e2e paired-bootstrap CI high &lt; 0 vs frozen 0.088 **and** full gates required.
- Optional methods (spaCy / AE / Leanstral / SyMAI / selective repair) remain **teachers/gates only**.

### Methods that earned composition into the production path

- `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` — improved det compiler/decompiler path; pilot mean e2e **0.0** with e2e CI high **-0.040000** &lt; 0 and full gates pass.

### Methods evaluated but not earned

- `constructor_only__modal_spacy_candidate` (constructor_only): mean forward 0.130833 — worse than typed_deontic forward 0.0; not eligible for production composition.

### Structural admission (Hammer / cvc5 / Lean)

- Earned role: `repair_admission_gate_only`
- Not earned: `semantic_loss_replacement`
- Proof pass is never scored as lower end-to-end loss by itself.

### Guided autoencoder

- Status: `not_measured` (not re-scored in PLAT-090)
- Earned composition: **False**

### Selective repair

- Default production composition: **False** (no-repair deterministic remains default)

## Next residuals

**None.** All five pilot cases have zero facet residuals after the merged det edit waves. Optional PLAT-091 full research matrix refresh is eligible because promotion is **True**.

## Acceptance checklist

| Criterion | Met |
| --- | :---: |
| Pilot det path re-scored | yes |
| Paired bootstrap vs 0.088 baseline | yes |
| not_measured excluded from rankings | yes |
| Promotion true only if e2e CI high &lt; 0 and full gates pass | yes |
| Promotion authorized | yes |
| Named next residuals when not promoted | n/a (promoted; residuals empty) |
| Immutable 2026-07-27 replacement promotion report preserved | yes |

## Evidence

- Machine-readable matrix: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_matrix.json`
- Promotion decision: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json`
- Matrix report CID: `baguqeerazqjvhhlk7l2kiovwkmcoezbuodziikspu6564hxdoxaplazlrmpq`
- Decision CID: `baguqeerahsrat44dqs3ypo2jodopcj6finktd2rcvvcsaatk4yndwvsmfwka`
- Hybrid bootstrap report CID: `baguqeera7jbv4cfvmomf3i2vcgfrst65sdmb6gnyxm7hyuwc65tam3gtwpiq`
- Success authorization CID: `baguqeeraeb3gokw6dasd3v5b5walt6vcf23riyyws46ymtnmpcnl4xwkkn4a`
- Smoke CID: `baguqeeraiy3s54wnug2vsgjyypkwi4cx3gnxwxqxqewxhs6vqqy56oelsoua`
- Frozen EVAL-009 matrix CID: `baguqeerak4mzpaqxrkbibk45ymkdmjcwpeoo6ze4wvtbkh5qr6blzygenfza`
- Immutable replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
