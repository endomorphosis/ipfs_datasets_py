"""Explicit fixed-support view diagnostics; never an acceptance or proof gate.

The caller declares raw view IDs for its modality/schema/lineage. This module
does not infer that schema from observed targets or learned sparse keys, and
does not certify the declaration's coverage. It reuses existing numeric heads
without changing their arithmetic, encoder context or checkpoint format.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from numbers import Real
from typing import Any, Mapping, Sequence


def _label(value: Any, name: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty exact string")


@dataclass(frozen=True)
class FixedViewVocabulary:
    """A caller-owned declaration, independent of the current batch and state.

    Labels identify the intended schema/lineage, not authenticated provenance.
    Bind source/checkpoint/target hashes in the surrounding experiment receipt.
    """

    profile_id: str
    modality_id: str
    schema_id: str
    lineage_id: str
    embedding_dimensions: int
    view_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("profile_id", "modality_id", "schema_id", "lineage_id"):
            _label(getattr(self, name), name)
        if type(self.embedding_dimensions) is not int or self.embedding_dimensions <= 0:
            raise ValueError("embedding_dimensions must be a positive integer")
        if type(self.view_ids) is not tuple or not 1 <= len(self.view_ids) <= 4096:
            raise ValueError("view_ids must be a nonempty bounded tuple")
        for value in self.view_ids:
            _label(value, "view ID")
        if len(set(self.view_ids)) != len(self.view_ids):
            raise ValueError("duplicate view IDs")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["view_ids"] = list(self.view_ids)
        result["schema_version"] = "fixed-view-vocabulary/v1"
        return result

    @property
    def sha256(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
        return hashlib.sha256(raw).hexdigest()

    def validate_samples(self, model: Any, samples: Sequence[Any]) -> None:
        collisions = set(self.view_ids).intersection(model.modal_families)
        if collisions:
            raise ValueError("raw view IDs collide with modal labels: " + repr(sorted(collisions)))
        if not samples:
            raise ValueError("fixed-view diagnostics require samples")
        ids = []
        for sample in samples:
            _label(sample.sample_id, "sample ID")
            ids.append(sample.sample_id)
            if len(sample.embedding_vector) != self.embedding_dimensions:
                raise ValueError("sample embedding dimensions differ from declared profile")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate diagnostic sample IDs")


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(name + " must be finite and numeric")
    return float(value)


def validate_fixed_view_targets(
    model: Any,
    samples: Sequence[Any],
    target_distributions: Mapping[str, Mapping[str, float]],
    vocabulary: FixedViewVocabulary,
) -> dict[str, dict[str, float]]:
    """Validate and copy explicit targets before a caller starts any updates."""
    if not isinstance(vocabulary, FixedViewVocabulary):
        raise ValueError("an explicit FixedViewVocabulary is required")
    rows = list(samples)
    vocabulary.validate_samples(model, rows)
    if not isinstance(target_distributions, Mapping):
        raise ValueError("explicit target distributions must be a mapping")
    if set(target_distributions) != {sample.sample_id for sample in rows}:
        raise ValueError("target sample IDs must exactly match diagnostic samples")
    declared = set(vocabulary.view_ids)
    targets = {}
    for sample in rows:
        distribution = target_distributions[sample.sample_id]
        if not isinstance(distribution, Mapping) or not distribution:
            raise ValueError("missing target distribution for " + sample.sample_id)
        unknown = set(distribution) - declared
        if unknown:
            raise ValueError("target view IDs outside declared vocabulary: " + repr(sorted(unknown, key=repr)))
        values = {name: _number(value, "target probability") for name, value in distribution.items()}
        # Probabilities above one also prevent overflow in the bounded sum.
        if any(not 0 <= value <= 1 for value in values.values()) or not math.isclose(
            math.fsum(values.values()), 1.0, rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ValueError("target probabilities must be nonnegative and sum to one")
        targets[sample.sample_id] = values
    return targets


def score_fixed_view_vocabulary(
    model: Any,
    samples: Sequence[Any],
    target_distributions: Mapping[str, Mapping[str, float]],
    vocabulary: FixedViewVocabulary,
) -> dict[str, Any]:
    """Score explicit targets with memory off and one declared denominator.

    Missing, malformed and out-of-schema targets raise instead of disappearing
    from a mean. All validation precedes numeric head evaluation. No bridge,
    compiler, prover, target selection or target-cache fallback is performed
    here. Existing model feature caches may be read and warmed; this function
    does not change trainable state.
    """
    rows = list(samples)
    targets = validate_fixed_view_targets(model, rows, target_distributions, vocabulary)
    declared = set(vocabulary.view_ids)

    results = []
    for sample in rows:
        target = targets[sample.sample_id]
        raw_logits = model._legal_ir_view_logits_for(
            sample, vocabulary.view_ids, use_sample_memory=False,
        )
        if set(raw_logits) != declared:
            raise ValueError("numeric head did not return the declared view IDs")
        logits = {name: _number(raw_logits[name], "view logit") for name in vocabulary.view_ids}
        maximum = max(logits.values())
        shifted = {name: value - maximum for name, value in logits.items()}
        if not all(math.isfinite(value) for value in shifted.values()):
            raise ValueError("view logit range is not finite")
        denominator = math.fsum(math.exp(value) for value in shifted.values())
        log_denominator = math.log(denominator)
        log_probs = {name: value - log_denominator for name, value in shifted.items()}
        probabilities = {name: math.exp(value) for name, value in log_probs.items()}
        ce = -math.fsum(value * log_probs[name] for name, value in target.items() if value)
        entropy = -math.fsum(value * math.log(value) for value in target.values() if value)
        if not math.isfinite(ce):
            raise ValueError("fixed-view cross entropy is not finite")
        results.append({
            "sample_id": sample.sample_id,
            "positive_target_view_count": sum(value > 0 for value in target.values()),
            "probabilities": probabilities,
            "cross_entropy_loss": ce,
            "target_entropy": entropy,
            "cross_entropy_excess_loss": ce - entropy,
        })
    return {
        "schema_version": "fixed-view-diagnostic/v1",
        "status": "scored",
        "profile": vocabulary.to_dict(),
        "profile_sha256": vocabulary.sha256,
        "target_distributions_sha256": hashlib.sha256(json.dumps(
            targets, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest(),
        "sample_count": len(rows),
        "declared_view_count": len(vocabulary.view_ids),
        "cross_entropy_loss": math.fsum(row["cross_entropy_loss"] for row in results) / len(rows),
        "cross_entropy_excess_loss": math.fsum(row["cross_entropy_excess_loss"] for row in results) / len(rows),
        "rows": results,
        "sample_memory_used": False,
        "bridge_evaluation_performed": False,
        "changes_acceptance": False,
        "schema_coverage_certified": False,
        "undeclared_head_policy": "excluded_by_declared_support_not_coverage_certified",
        "admitted": False,
    }
