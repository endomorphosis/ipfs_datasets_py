# Semantic Round-Trip Population Freeze (PLAT2-020)

**Interfaces:** `SemanticRoundtripPopulationManifest@1`,
`SemanticRoundtripHoldoutSeal@1`, `HoldoutAccessAudit@1`  
**Status:** frozen before repair-development outcome inspection  
**Module:** `benchmarks/semantic_roundtrip/holdout_protocol.py`

## Purpose

PLAT-000…091 sealed deterministic improvements on five pilot cases. PLAT2
generalizes residual → teacher → prover → supervisor → remeasure **without
adaptive holdout leakage**:

| Population | Visibility | Purpose |
| --- | --- | --- |
| `pilot` | Visible fixture | Immutable regression controls (historical e2e 0.0) |
| `repair_development` | Visible fixture (source/gold) | Residual diagnosis, packets, edit waves, ablations |
| `blind_holdout` | Custodian-only private store | One audited out-of-sample decision after PLAT2-055 |

This document freezes the three-way split, public seal contract, leakage
policy, sample-size justification, and access-ledger rules. Downstream tasks
must load these freezes rather than inventing cases after inspecting losses.

## Artifact paths

| Artifact | Path | Contents |
| --- | --- | --- |
| Pilot fixture | `tests/fixtures/semantic_roundtrip/pilot_cases.json` | Source + gold (regression) |
| Repair-dev fixture | `tests/fixtures/semantic_roundtrip/repair_dev_cases.json` | Source + gold (diagnosis) |
| Public blind seal | `workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json` | Count/strata + aggregate commitments only |
| Protocol module | `benchmarks/semantic_roundtrip/holdout_protocol.py` | Manifests, seal, leakage, ledger |
| Private blind sources/gold | **Outside** agent/tuning worktrees | Custodian store only |

Compatibility note: `tests/fixtures/semantic_roundtrip/holdout_cases.json`
remains a historical hybrid fixture consumed by residual-catalog paths. The
PLAT2 repair-development freeze is `repair_dev_cases.json`. Blind content is
**not** that file.

## Freeze boundaries

### Pilot (`SemanticRoundtripPopulationManifest@1`)

- Case IDs (frozen order from residual catalog):  
  `exception_with_window`, `exec_order_1`, `corp_policy_1`, `legal_doc_1`,
  `construction_contract`
- Population kind: `pilot`
- Source/gold exposed for non-regression scoring only
- Sample-size role: historical control, not a promotion population

### Repair-development (`SemanticRoundtripPopulationManifest@1`)

Fixture: `tests/fixtures/semantic_roundtrip/repair_dev_cases.json`

Includes selective-repair activation cases and additional legal corpus cases
with adjudicated `gold_ir` and `score_bindings` for diagnosis:

| Case ID | Family / stratum |
| --- | --- |
| `missing_temporal` | `selective_repair_activation` |
| `low_confidence_object` | `selective_repair_activation` |
| `contradictory_modality` | `selective_repair_activation` |
| `legal_doc_2` | `legal_corpus` |
| `privacy_act_amendment` | `legal_corpus` |
| `fed_reg_1` | `legal_corpus` |
| `dept_memo_1` | `legal_corpus` |
| `hr_handbook` | `legal_corpus` |

Repair-development **may** expose source text and gold IR. It is intentionally
visible so residual catalogs, packets, and deterministic edit waves can run
before any blind access.

With the preregistered precision formula (see below), eight cases are
**underpowered** (`exploratory: true`, `promotion_eligible: false`).
Repair-development outcomes alone cannot authorize promotion.

### Blind holdout (`SemanticRoundtripHoldoutSeal@1`)

Public seal path:

`workspace/benchmarks/semantic-roundtrip-compositions/plateau2_blind_holdout_seal.json`

The public seal exposes **only**:

- schema / interface
- `case_count` and `strata_counts`
- `aggregate_commitments` to the ordered private **source**, **gold**, and
  **provenance** manifests (whole-manifest CIDs)
- `sample_size_justification`
- `leakage_policy_cid`, `access_ledger_authority_cid`
- `sealed_private_bundle_cid`
- normalization / near-duplicate policy parameters
- `seal_cid` (content address of the public identity payload)

The public seal **must not** expose:

- per-case digests or case IDs
- source text
- labels or score bindings
- gold IR bodies
- semantic hints, residuals, or diagnostics

Private source/gold/provenance bytes live only in an access-controlled
custodian store **outside** agent worktrees, tuning worktrees, prompts,
packets, and default context.

Preregistered public counts (revision 1):

| Field | Value |
| --- | --- |
| `case_count` | 12 |
| `strata_counts.complexity_tier_1` | 4 |
| `strata_counts.complexity_tier_2` | 8 |

Recompute / validate:

```bash
PYTHONPATH=. python - <<'PY'
from benchmarks.semantic_roundtrip.holdout_protocol import (
    build_frozen_blind_holdout_seal,
    load_frozen_blind_holdout_seal,
)
seal = load_frozen_blind_holdout_seal()
assert seal.seal_cid == build_frozen_blind_holdout_seal().seal_cid
print(seal.seal_cid)
print(seal.case_count, dict(seal.strata_counts))
PY
```

## Sample-size / power justification

Method: `paired_case_cluster_bootstrap_precision`

\[
n \ge \left\lceil\left(\frac{z_{1-\alpha/2}\cdot \sigma}{h}\right)^2\right\rceil
\]

Frozen parameters:

| Parameter | Value |
| --- | --- |
| \(\alpha\) | 0.05 |
| \(z_{1-\alpha/2}\) | 1.959963984540054 |
| Assumed SD of paired e2e delta \(\sigma\) | 0.08 |
| Target CI half-width \(h\) | 0.05 |
| Required \(n\) | 10 |

| Population | \(n\) | Powered? | Promotion sample-size gate |
| --- | ---: | --- | --- |
| Pilot | 5 | no | not a promotion population |
| Repair-development | 8 | no | exploratory; cannot authorize promotion |
| Blind holdout | 12 | yes | may authorize only after PLAT2-055 + full decision gates |

An underpowered population is explicitly **exploratory** and **cannot**
authorize promotion (`assert_promotion_sample_size_gate`).

## Leakage policy

Checks (all fail closed across pilot × repair_development × blind_holdout):

1. **Exact** source SHA-256 overlap
2. **Normalized** source SHA-256 after `unicode-nfkc-casefold-alnum-v1`
3. **Provenance** `source_ref` reuse
4. **Near-duplicate** token-shingle Jaccard ≥ 0.8
5. **Prompt-example** isolation against blind sources (exact/normalized/near-copy)

```python
from benchmarks.semantic_roundtrip.holdout_protocol import (
    freeze_all_populations_with_private_blind,
    materialize_preregistered_blind_records,
)

freeze_all_populations_with_private_blind(
    materialize_preregistered_blind_records(),
    prompt_examples={...},  # optional development prompts
)
```

## Append-only access ledger (`HoldoutAccessAudit@1`)

Blind access is single-use and authorization-gated:

| Rule | Behavior |
| --- | --- |
| Before PLAT2-055 authorization | `unauthorized_access_rejected` |
| Valid PLAT2-055 authorization | `access_granted` then `manifest_released` |
| Repeated access after release | `repeated_access_rejected` |
| Post-access code/prompt/threshold/population tuning | `post_access_tuning_rejected` |

Authorization must bind:

- `goal_id = PLAT2-055`
- exact `seal_cid`
- candidate freeze CID
- `complete=true`, `holdout_authorized=true`
- `outcomes_inspected=false`, `tuning_permitted=false`

Ledger records are append-only JSONL with chained `receipt_cid` values. Digests
and access receipts are sufficient; ZK is out of scope for PLAT2.

## Loading visible cases

```python
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.holdout_protocol import (
    load_pilot_manifest,
    load_repair_development_manifest,
    load_frozen_blind_holdout_seal,
)

pilots = load_matrix_cases("tests/fixtures/semantic_roundtrip/pilot_cases.json")
repair = load_matrix_cases("tests/fixtures/semantic_roundtrip/repair_dev_cases.json")
pilot_manifest = load_pilot_manifest()
repair_manifest = load_repair_development_manifest()
blind_seal = load_frozen_blind_holdout_seal()  # public metadata only
```

Never load private blind sources through ordinary supervisor, packet, residual,
or test helpers in agent worktrees.

## Acceptance (PLAT2-020)

| Criterion | Status |
| --- | --- |
| Disjoint pilot, repair_development, and blind_holdout freezes before outcome inspection | met |
| Repair-dev may include selective-repair cases and expose source/gold | met |
| Blind sources/gold only in access-controlled custodian store outside worktrees | met (public seal only in repo) |
| Public seal: schema, count/strata, aggregate commitments, seal CID; no per-case digest/source/labels/gold/hints | met |
| Exact, normalized, provenance, near-duplicate, and prompt-example checks | met |
| Append-only ledger rejects pre-PLAT2-055, repeated access, post-access tuning | met |
| Sample size/strata preregistered; underpowered = exploratory, no promotion | met |

## Validation

```bash
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_protocol.py -q
```

## Downstream consumers

| Consumer | Use |
| --- | --- |
| PLAT2-010 residual catalog | Typed `repair_development` population; reject premature blind |
| PLAT2-025 baseline freeze | Bind population/seal CIDs without opening blind |
| PLAT2-030 packets | Repair-development only |
| PLAT2-050 edit waves | Repair-development + pilot regression |
| PLAT2-055 candidate freeze | Sole issuer of holdout authorization |
| PLAT2-060 evaluation | Single-use custodian access + decision |

Doctrine unchanged: production remains typed_deontic → IR → deterministic
realizer; Hammer/cvc5/Lean never have semantic authority.
