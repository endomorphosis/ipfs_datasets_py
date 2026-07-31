# Semantic Round-Trip Dual Metrics Bridge

**Interface:** `DualRoundTripMetrics@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-dual-metrics.v1`  
**Module:** `benchmarks.semantic_roundtrip.dual_metrics`  
**Task:** PLAT-080 / PLAT-G100  

## Purpose

Bridge the original AE-loop metrics (**cross-entropy**, **cosine similarity**)
with the composition protocol's **structural** forward / cycle / end-to-end
losses so residual catalogs, Codex packets, and AE training share one residual
language.

The composition protocol primary loss is unchanged:

```text
loss_e2e = 1 - S(gold IR, L2)   # structural assignment score
```

CE/cosine are optional research diagnostics. They **never** replace structural
losses for promotion or selection.

## Doctrine

| Rule | Behavior |
| --- | --- |
| Structural always | Every report includes `structural_forward`, `structural_cycle`, `structural_end_to_end` from `round_trip_losses` |
| CE/cosine only when real | Attached only when an embedding backend is present, available, and scores **every** leg |
| Fail closed | Missing, unavailable, partial, or erroring backends → `metric_mode=structural_only` with CE/cosine fields set to `null` |
| No invention | Defaults such as `0.0` / `1.0` are **not** written for missing CE/cosine |
| No silent substitution | `silent_metric_substitution` is always `false`; promotion primary is always `structural_end_to_end` |
| Promotion authority | `ce_cosine_may_substitute_for_promotion` is always `false` |

## Metric modes

| Mode | When | Optional fields |
| --- | --- | --- |
| `structural_only` | No backend, backend unavailable, or any leg unscored | All CE/cosine = `null` |
| `dual` | Backend present, available, and scores forward + cycle + e2e | Full CE and cosine on every leg |

Partial dual scores are rejected. Incomplete embedding evidence collapses to
`structural_only` rather than publishing half-filled CE/cosine.

## Legs

| Leg | Structural | Optional CE/cosine pair |
| --- | --- | --- |
| Forward | gold → L1 | same pair |
| Cycle | L1 → L2 | same pair |
| End-to-end | gold → L2 | same pair |

Structural failure policy is inherited from the protocol: missing artifacts,
empty IR, blank reconstruction, or `failed=True` set structural losses to
`1.0` on every leg.

## Public API

| Symbol | Role |
| --- | --- |
| `DualRoundTripMetrics` | Frozen dual report record |
| `DualMetricMode` | `structural_only` \| `dual` |
| `EmbeddingPairMetrics` | CE + cosine for one IR pair |
| `EmbeddingMetricBackend` | Protocol: `identity`, `available()`, `pair_metrics()` |
| `CallableEmbeddingBackend` | Adapter for pure scoring callables |
| `UnavailableEmbeddingBackend` | Explicit offline backend |
| `compute_dual_metrics(...)` | Primary entry: artifacts → dual report |
| `dual_metrics_from_structural(...)` | Bridge precomputed structural losses + optional pairs |
| `attach_dual_metrics_to_residual_row(...)` | Non-destructive residual-catalog attachment |
| `cosine_similarity` / `cross_entropy_from_distributions` | Pure helpers for backend implementers |

### `compute_dual_metrics`

```python
from benchmarks.semantic_roundtrip.dual_metrics import (
    CallableEmbeddingBackend,
    EmbeddingPairMetrics,
    compute_dual_metrics,
)

report = compute_dual_metrics(
    gold_ir,
    l1,
    reconstruction,
    l2,
    embedding_backend=None,  # structural-only
)

backend = CallableEmbeddingBackend(
    identity="ae-teacher@1",
    scorer=lambda ref, cand: EmbeddingPairMetrics(0.12, 0.91),
)
dual = compute_dual_metrics(
    gold_ir, l1, reconstruction, l2, embedding_backend=backend
)
assert dual.metric_mode.value == "dual"
assert dual.promotion_primary_metric == "structural_end_to_end"
```

### Residual catalog attachment

```python
from benchmarks.semantic_roundtrip.dual_metrics import (
    attach_dual_metrics_to_residual_row,
)

row = {"case_id": "legal_doc_1", "field_path": "rules[0].modality"}
enriched = attach_dual_metrics_to_residual_row(row, dual)
# enriched["dual_metrics"] is the sealed to_dict() payload
# original row is not mutated; structural keys on the row are not replaced
```

## Sealed export shape

```json
{
  "interface": "DualRoundTripMetrics@1",
  "schema": "ipfs-datasets.semantic-roundtrip-dual-metrics.v1",
  "structural_forward": 0.085,
  "structural_cycle": 0.003333,
  "structural_end_to_end": 0.088333,
  "metric_mode": "structural_only",
  "embedding_backend_present": false,
  "embedding_backend_id": null,
  "cross_entropy_forward": null,
  "cross_entropy_cycle": null,
  "cross_entropy_end_to_end": null,
  "cosine_forward": null,
  "cosine_cycle": null,
  "cosine_end_to_end": null,
  "promotion_primary_metric": "structural_end_to_end",
  "ce_cosine_may_substitute_for_promotion": false,
  "silent_metric_substitution": false,
  "promotion_policy_note": "..."
}
```

When dual:

- `metric_mode` is `"dual"`
- `embedding_backend_present` is `true`
- `embedding_backend_id` is a nonblank identity
- every CE field is a finite non-negative float
- every cosine field is a finite float in `[-1, 1]`

## Integration notes

- **Does not change** `benchmarks.semantic_roundtrip.metrics.round_trip_losses`
  or the composition protocol primary loss definition.
- **AE teacher path (PLAT-060):** supply a real embedding backend when causal
  L1 / AE embeddings are available; otherwise residual rows stay structural-only.
- **Codex packets (PLAT-020):** may cite dual reports as residual language; packet
  admission and promotion remain structural + structural-admission gates.
- **Promotion (PLAT-090):** ignore CE/cosine for “beats baseline” claims unless a
  later sealed policy explicitly changes promotion authority (this module forbids
  that by contract).

## Non-goals

- Replacing structural e2e as the selection metric
- Inventing CE/cosine when embeddings are offline
- Requiring torch / modal autoencoder imports in this bridge module
- Rewriting the immutable 2026-07-27 replacement promotion report

## Validation

```bash
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_dual_metrics.py -q
```

## Related

- `docs/benchmarks/semantic_roundtrip_composition_protocol.md` — structural primary loss
- `docs/benchmarks/semantic_roundtrip_plateau_break_plan.md` — PLAT-080 / G100
- `benchmarks/semantic_roundtrip/metrics.py` — structural helpers
- `benchmarks/semantic_roundtrip/stage_metrics.py` — stage-local research metrics (also non-promotable alone)
