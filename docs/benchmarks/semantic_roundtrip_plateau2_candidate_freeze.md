# Plateau2 Candidate Freeze, Attribution, and Holdout Authorization (PLAT2-055)

**Interfaces:** `Plateau2CandidateFreeze@1`, `SemanticRoundtripHoldoutAuthorization@1`  
**Module:** `benchmarks/semantic_roundtrip/holdout_candidate_freeze.py`  
**Task:** PLAT2-055 / PLAT2-G055  
**Evidence:** PLAT2EV055FREEZE  
**Status:** freezes zero or one candidate; sole issuer of blind-access authorization

## Purpose

PLAT2-055 is the **only** step that may:

1. Attribute isolated and cumulative deterministic edit-wave effects on **pilot**
   and **repair-development** populations.
2. Select **zero or one** immutable candidate under frozen **PLAT2-025** rules.
3. Emit the **only** valid blind-holdout access authorization for PLAT2-060.

It never loads blind sources, gold, residuals, or outcomes. Structural gate
coverage is reported separately and never substitutes for semantic e2e loss.

## Doctrine

```text
PLAT2-050 terminal edit-wave receipts
  → isolated-wave attribution (prior → post per case)
  → cumulative candidate re-score on pilot + repair-development
  → zero-or-one selection under PLAT2-025 rules
  → optional SemanticRoundtripHoldoutAuthorization@1
  → PLAT2-060 single-use custodian evaluation
```

Production remains **typed_deontic → IR → deterministic realizer**. Optional
spaCy / AE / Leanstral / SyMAI outputs stay non-authoritative teachers.
Hammer / cvc5 / Lean remain structural gates with `semantic_authority: false`.

## Artifact paths

| Artifact | Path |
| --- | --- |
| Freeze module | `benchmarks/semantic_roundtrip/holdout_candidate_freeze.py` |
| Candidate freeze | `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_candidate_freeze.json` |
| Holdout authorization | `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_holdout_authorization.json` |
| Unit tests | `tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py` |
| This document | `docs/benchmarks/semantic_roundtrip_plateau2_candidate_freeze.md` |
| Edit-wave receipts | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_edit_wave_receipts/` |
| Baseline (PLAT2-025) | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_baseline.json` |
| Intervention registry (PLAT2-035) | `workspace/benchmarks/semantic-roundtrip-compositions/repair_dev_intervention_registry.json` |
| Blind public seal (PLAT2-020) | `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json` |

## Attribution evidence (no blind data)

For every terminal PLAT2-050 edit wave and for the cumulative candidate, the
freeze records:

| Evidence class | Source |
| --- | --- |
| Per-wave **marginal** deltas | Receipt prior → post on the targeted repair-development case |
| **Cumulative** deltas | Live production-path scores vs PLAT2-025 baseline (pilot + repair-development) |
| **Interactions** | Per-case cumulative forward delta − isolated marginal |
| First-pass / eventual repair success | Post-loss cleared flags on each wave |
| Accepted-patch regressions | Pilot mean/case worsening or targeted-case worsening after accept |
| Structural-gate coverage | Declared constraints preserved (non-semantic) |
| Context tokens | Packet token counts vs frozen 8192 budget |
| Provider calls | Leanstral / SyMAI / LLM / optional teacher call counts |
| Cost | Explicit zero when residual-only deterministic waves meter no paid inference |

Blind populations, private manifests, and gold bindings are **out of scope**.

## Selection rules (frozen PLAT2-025)

Exactly **zero or one** candidate may be selected:

| Gate | Rule |
| --- | --- |
| Evidence complete | Terminal receipts for every sealed nonzero residual case; no blind access; no optional-runtime promotion; production arm unchanged |
| Pilot non-regression | Pilot mean end-to-end loss remains **0.0** |
| No pilot case e2e regression | Each pilot e2e ≤ baseline e2e |
| No new pilot gate failures | Coverage / source-copy / polarity gates that passed at baseline still pass |
| No accepted-patch regression | Isolated waves and cumulative pilot view show no regression |
| Repair-development improvement | At least one wave eventually clears its residual |
| Blind seal | Still unopened with **zero** access receipts |

Selection does **not** open the blind holdout and does **not** claim promotion.
Promotion remains a PLAT2-060 decision under paired bootstrap + noninferiority.

Frozen thresholds bound into the freeze (not retunable post-authorization):

| Item | Value |
| --- | --- |
| Primary metric | `end_to_end_loss` (lower is better) |
| Aggregation | `per_case_first_macro_mean` |
| Bootstrap | seeded percentile case-cluster, 10000 samples, seed 17291, CL 0.95 |
| Noninferiority margin | **0.03** on candidate − baseline e2e |
| Packet token budget | 8192 (`whitespace_split_proxy_v1`) |
| Selection gates | `full_coverage`, `source_copy_exclusion`, `polarity_preservation` |

## Identity bindings

The freeze binds, at minimum:

- baseline and candidate **git commit / tree / recursive gitlinks CIDs**
- compiler / realizer modules and identities
  (`TypedDeonticCanonicalConstructor@1`, `CanonicalDeterministicRealizer@1`)
- production arm / config
- metrics, facets, aggregation, bootstrap, noninferiority, selection/promotion rules
- intervention registry CID, packet context metrics CID, edit-wave manifest CID
- provider / model / toolchain identities (production + optional teachers not promoted)
- environment inventory
- tests and validation commands
- pilot / repair-development population and residual CIDs
- blind **public** seal CID (not private content)
- all thresholds listed above

## Holdout authorization

`SemanticRoundtripHoldoutAuthorization@1` is emitted **only** when:

1. The freeze selects exactly one candidate (`candidate_selected=true`).
2. Evidence is complete and required pilot gates pass.
3. The blind seal has **zero** prior access receipts.
4. The freeze payload validates (`freeze_cid` matches content).

Authorization fields (protocol-compatible with
`HoldoutAccessAuthorization` in `holdout_protocol.py`):

| Field | Value |
| --- | --- |
| `goal_id` | `PLAT2-055` |
| `seal_cid` | frozen public blind seal CID |
| `candidate_freeze_cid` | freeze CID |
| `complete` | `true` |
| `holdout_authorized` | `true` |
| `outcomes_inspected` | `false` |
| `tuning_permitted` | `false` |

If no candidate is selected, **no** authorization file is minted and the blind
holdout remains sealed.

## Invalidation after authorization

Any subsequent change to:

- compiler / realizer code
- production arm or config
- metrics, aggregation, bootstrap, margins, thresholds
- selection / promotion rules
- intervention registry, packets, prompts
- provider / model / toolchain identity
- environment
- acceptance-defining tests
- population or seal CIDs
- candidate source tree

**invalidates** the authorization. Operators must:

1. Mint a **new experiment identity** (PLAT2-025 protocol-change policy).
2. Author a **fresh** blind holdout population and seal.
3. **Not** retune or re-evaluate against this blind holdout.

## Reproduce

```bash
PYTHONPATH=. python -m benchmarks.semantic_roundtrip.holdout_candidate_freeze \
  --repo-root .

PYTHONPATH=. python -m pytest \
  tests/unit/benchmarks/semantic_roundtrip/test_holdout_candidate_freeze.py \
  tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
```

## Downstream

| Consumer | Role |
| --- | --- |
| PLAT2-060 one-shot evaluation | Requires valid freeze + authorization; single append-only access receipt |
| Access ledger (`holdout_protocol`) | Rejects pre-authorization, repeated, and post-access tuning events |
| Residual catalog evaluator mode | Requires post-freeze `candidate_freeze_cid` before blind residuals |

## Acceptance checklist

| Criterion | Status |
| --- | --- |
| Replay isolated waves + cumulative candidate on pilot/repair-development only | met |
| Report marginal/cumulative deltas, interactions, repair success, regressions, structural coverage, tokens, calls, cost | met |
| No blind data in freeze evidence | met |
| Zero or one candidate under PLAT2-025 rules | met |
| Bind baseline/candidate tree, code, configs, metrics, stats, registry, packets, providers, env, tests, populations, seal, thresholds | met |
| Authorization only when evidence complete, gates pass, zero prior access, candidate frozen | met |
| Post-authorization change invalidates and requires new experiment + fresh blind holdout | met |
