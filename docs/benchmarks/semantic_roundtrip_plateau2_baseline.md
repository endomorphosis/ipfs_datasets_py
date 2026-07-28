# Plateau2 Baseline and Experiment Contract (PLAT2-025)

**Interfaces:** `Plateau2ExperimentContract@1`, `EvalRepairMatrixReport@1`  
**Module:** `benchmarks/semantic_roundtrip/holdout_baseline.py`  
**Task:** PLAT2-025 / PLAT2-G025  
**Evidence:** PLAT2EV025BASE  
**Status:** frozen before edit waves

## Purpose

PLAT2-025 freezes the **pre-edit-wave experiment contract** and the
**deterministic repair-development baseline** so later residual packets,
ablations, candidate freezes, and the single-use blind comparison all share
one reproducible reference and one set of decision rules.

Before any PLAT2 edit wave:

1. Bind the post-PLAT source tree (git commit, tree, recursive gitlinks).
2. Freeze the production arm / config, environment, and toolchain.
3. Bind pilot and repair-development population and residual-catalog CIDs.
4. Preregister metrics, facets, per-case-first aggregation, paired bootstrap,
   confidence level/count, noninferiority margin, selection/promotion rules,
   packet token budget, capability policy, and failure taxonomy.
5. Run the deterministic baseline on **pilots and repair-development only**.
6. Record per-case and per-facet forward/cycle/e2e loss, coverage, polarity,
   source-copy gates, and failure clusters under the evaluation-status
   taxonomy.
7. Keep the blind seal **unopened** with **zero** access receipts.

Protocol changes after this freeze **mint a new experiment identity** and
retire downstream receipts; they must not mutate this freeze in place.

## Artifact paths

| Artifact | Path |
| --- | --- |
| Experiment + baseline module | `benchmarks/semantic_roundtrip/holdout_baseline.py` |
| Baseline report | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json` |
| Unit tests | `tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py` |
| This document | `docs/benchmarks/semantic_roundtrip_plateau2_baseline.md` |
| Pilot residual catalog | `workspace/benchmarks/semantic-roundtrip-compositions/plateau_residual_catalog.json` |
| Repair-dev residual catalog | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_residual_catalog.json` |
| Blind public seal | `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json` |

## Production arm (post-PLAT)

| Field | Value |
| --- | --- |
| Arm ID | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| Constructor | `TypedDeonticCanonicalConstructor@1` |
| Realizer | `CanonicalDeterministicRealizer@1` |
| Guidance / repair / route | `no_guidance` / `no_repair` / `not_applicable` |
| Post-PLAT pilot mean e2e | **0.0** |
| Post-PLAT baseline report CID | `baguqeerag7kwogvfkjciwoovp6cvpl5pueaoweucfqzjhbl4j6vhq5n5xn7q` |

Production doctrine remains **typed_deontic → IR → deterministic realizer**.

## Metric and facet definitions

| Item | Frozen value |
| --- | --- |
| Primary promotion metric | `end_to_end_loss` (structural; lower is better) |
| Loss legs | `forward`, `cycle`, `end_to_end` |
| Facets | `modality`, `conditions`, `exceptions`, `temporal` |
| Aggregation | **per-case-first** macro mean (`per_case_first_macro_mean`) |
| Failure loss | `1.0` (fail-closed) |
| Selection gates | `full_coverage`, `source_copy_exclusion`, `polarity_preservation` |

Stage-local scores, CE/cosine dual metrics, and structural proof passes never
authorize promotion alone.

## Uncertainty (paired bootstrap)

| Item | Frozen value |
| --- | --- |
| Method | `seeded_percentile_case_cluster_bootstrap` |
| Unit | case cluster (never individual repeats) |
| Samples | `10000` |
| Confidence level | `0.95` |
| Seed | `17291` |
| Comparison | `candidate_minus_baseline` on end-to-end loss |

## Noninferiority and promotion rules

| Item | Frozen value |
| --- | --- |
| Noninferiority margin | **0.03** |
| Noninferiority rule | upper CI bound ≤ margin |
| Improvement rule | paired CI high **&lt; 0** |
| Full gates required | **true** |
| Pilot non-regression | pilot mean e2e must remain **0.0** |
| Underpowered populations | cannot authorize promotion |

### Decision outcomes

| Outcome | Meaning |
| --- | --- |
| `improvement_confirmed` | Blind paired CI high &lt; 0, all frozen gates pass, powered sample, complete evidence |
| `generalization_confirmed_no_improvement` | Noninferiority + no-regression pass; no improvement claimed |
| `promotion_declined` | All other complete outcomes |
| `incomplete` | Missing, leaked, stale, underpowered, or unauthorized evidence |

## Packet token budget

| Item | Frozen value |
| --- | --- |
| Max tokens | **8192** |
| Soft warn | 6144 |
| Counting method | `whitespace_split_proxy_v1` |
| Omitted-handle coverage | required |

PLAT2-030 packets must record token counts against this budget and keep
expansion handles auditable.

## Capability policy

| Method | Role | Semantic authority |
| --- | --- | --- |
| typed_deontic + deterministic | Production edit target | **true** (composition authority via e2e gates) |
| Autoencoder | Causal guidance only when qualified | false |
| spaCy | Diagnostics | false |
| SyMAI | Orchestration | false |
| Leanstral | Proposal teacher | false |
| Hammer / cvc5 / Lean | Structural gates | false |

Queries, diagnostics, tests, model outputs, and structural receipts do **not**
replace semantic e2e loss.

## Failure taxonomy

Evaluation statuses (mutually exclusive; non-semantic statuses never enter
score aggregates):

| Status | Meaning |
| --- | --- |
| `semantic_scored` | Fairly measured with defined gates |
| `not_measured` | Never fairly measured (unsupported / preflight blocked) |
| `runtime_failed` | Execution attempted; runtime/provider failure |
| `unsupported` | Terminal unsupported on this path |

Failure clusters on the baseline report also group nonzero loss legs, failed
gates, facet survivals &lt; 1, residual kinds, and non-semantic statuses.

## Populations in scope

| Population | Baseline scored? | Notes |
| --- | --- | --- |
| `pilot` | **Yes** | Immutable regression; mean e2e must stay 0.0 |
| `repair_development` | **Yes** | Visible diagnosis population; underpowered alone |
| `blind_holdout` | **No** | Seal remains unopened; zero access receipts |

## Baseline report fields

`repair_dev_baseline.json` (`EvalRepairMatrixReport@1`) binds:

- `contract_cid` / `experiment_id` from `Plateau2ExperimentContract@1`
- production `arm_id`
- per-population case rows with:
  - `losses.forward` / `cycle` / `end_to_end`
  - `facets` survival for each loss leg
  - `gates` (coverage, source-copy, polarity, selection_eligible)
  - `evaluation_status` taxonomy
- per-population aggregates (per-case-first means, status counts, gate passes)
- `failure_clusters`
- `blind_holdout` seal status (`sealed_unopened`, `access_receipt_count: 0`)
- pilot non-regression snapshot

## Protocol change policy

Any change to metrics, aggregation, bootstrap parameters, margin, gates, token
budget, capability policy, failure taxonomy, populations, or baseline scoring
rules must:

1. Call `mint_new_experiment_identity(previous_contract, reason=...)`.
2. Emit a new `experiment_id` / revision.
3. Retire all downstream receipts bound to the previous experiment identity.
4. **Not** reopen or retune against the existing blind seal.

## Reproduce

```bash
# Contract only (no scoring)
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_baseline --contract-only

# Full freeze: score pilots + repair-development and write the report
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_baseline \
  --output workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json

# Validation
PYTHONPATH=. python -m pytest \
  tests/unit/benchmarks/semantic_roundtrip/test_holdout_baseline.py \
  tests/unit/benchmarks/semantic_roundtrip/test_residual_catalog.py -q
```

## Downstream consumers

| Task | Uses this freeze for |
| --- | --- |
| PLAT2-030 | Packet bindings (baseline/tree/population/catalog CIDs, token budget) |
| PLAT2-035 | Intervention registry against frozen capability policy |
| PLAT2-050 | Edit-wave deltas vs this baseline |
| PLAT2-055 | Candidate freeze + holdout authorization under frozen decision rules |
| PLAT2-060 | One-shot blind comparison using frozen margin/bootstrap/gates |

## Related freezes

- Population split / blind seal: `docs/benchmarks/semantic_roundtrip_holdout_cases.md`
- Post-plateau research matrix: `docs/benchmarks/semantic_roundtrip_post_plateau_results.md`
- Pilot promotion: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_plateau_break_promotion_decision.json`
- Plan: `docs/benchmarks/semantic_roundtrip_plateau_holdout_plan.md`
