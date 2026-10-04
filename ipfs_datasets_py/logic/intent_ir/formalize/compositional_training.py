"""Replayed compositional curriculum training with separated source metrics."""
from __future__ import annotations

from .copy_training import train_intent_copy, evaluate_intent_copy
from .roundtrip_training import _metrics


def train_compositional_intent(corpus, output, **settings):
    """Validate all generated labels and base-source bindings before fitting."""
    from .compositional_curriculum import validate_compositional_corpus
    validate_compositional_corpus(corpus)
    return train_intent_copy(corpus, output, **settings)


def evaluate_compositional_intent(descriptor, samples, *, weight_ablation=None):
    """Keep public data, existing controls and new curriculum scores separate."""
    report = evaluate_intent_copy(descriptor, samples, weight_ablation=weight_ablation)
    by_id = {sample["id"]: sample for sample in samples}
    if (len(by_id) != len(samples) or len(report["rows"]) != len(samples)
            or {row["id"] for row in report["rows"]} != set(by_id)):
        raise ValueError("compositional evaluation identities differ")
    kinds = sorted({str(sample["provenance"]["kind"]) for sample in samples})
    return {**report, "schema": "intent-compositional-evaluation/v1",
        "source_groups": {kind: _metrics([row for row in report["rows"]
            if by_id[row["id"]]["provenance"]["kind"] == kind]) for kind in kinds},
        "source_group_ids": {kind: sorted(sample["id"] for sample in samples
            if sample["provenance"]["kind"] == kind) for kind in kinds},
        "authored_curriculum_is_not_public_semantic_gold": True}
