"""Semantic-equivalence metrics for LegalIR promotion gates.

Cross entropy and cosine similarity are useful optimization signals, but they
are not sufficient compiler-quality evidence.  This module evaluates the
semantic surfaces that must remain stable when a learned or deterministic
LegalIR candidate is promoted:

* structural equivalence
* deontic obligation equivalence
* counterexample equivalence
* graph isomorphism
* temporal-window agreement
* decompiler round-trip preservation
* proof-obligation delta

The implementation accepts either explicit per-family metric blocks or raw
reference/candidate LegalIR payloads.  Raw payload evaluation is deliberately
deterministic and dependency-free so it can run inside rollout and daemon gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Optional

from .legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
    canonical_legal_ir_evaluation_family,
)


LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION: Final = "legal-ir-semantic-equivalence-metrics-v1"
LEGAL_IR_LATENT_DIAGNOSTICS_SCHEMA_VERSION: Final = "legal-ir-latent-diagnostics-v1"
DEFAULT_FALSE_NEIGHBORHOOD_K: Final = 3
DEFAULT_ACTIVE_DIMENSION_EPSILON: Final = 1e-8
DEFAULT_JACOBI_SWEEPS: Final = 64
DEFAULT_JACOBI_TOLERANCE: Final = 1e-15

STRUCTURAL_EQUIVALENCE: Final = "structural_equivalence"
OBLIGATION_EQUIVALENCE: Final = "obligation_equivalence"
COUNTEREXAMPLE_EQUIVALENCE: Final = "counterexample_equivalence"
GRAPH_ISOMORPHISM: Final = "graph_isomorphism"
TEMPORAL_WINDOW_AGREEMENT: Final = "temporal_window_agreement"
DECOMPILER_ROUND_TRIP_PRESERVATION: Final = "decompiler_round_trip_preservation"
PROOF_OBLIGATION_DELTA_SCORE: Final = "proof_obligation_delta_score"
PROOF_OBLIGATION_DELTA: Final = "proof_obligation_delta"

SEMANTIC_EQUIVALENCE_METRICS: Final[tuple[str, ...]] = (
    STRUCTURAL_EQUIVALENCE,
    OBLIGATION_EQUIVALENCE,
    COUNTEREXAMPLE_EQUIVALENCE,
    GRAPH_ISOMORPHISM,
    TEMPORAL_WINDOW_AGREEMENT,
    DECOMPILER_ROUND_TRIP_PRESERVATION,
    PROOF_OBLIGATION_DELTA_SCORE,
)

_METRIC_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    STRUCTURAL_EQUIVALENCE: (
        "structural_equivalence",
        "structural_equivalence_score",
        "structural_equivalence_success_rate",
        "semantic_structural_equivalence",
    ),
    OBLIGATION_EQUIVALENCE: (
        "obligation_equivalence",
        "obligation_equivalence_score",
        "obligation_equivalence_success_rate",
        "deontic_obligation_equivalence",
    ),
    COUNTEREXAMPLE_EQUIVALENCE: (
        "counterexample_equivalence",
        "counterexample_equivalence_score",
        "counterexample_equivalence_success_rate",
        "cex_equivalence",
    ),
    GRAPH_ISOMORPHISM: (
        "graph_isomorphism",
        "graph_isomorphism_score",
        "graph_isomorphism_success_rate",
        "knowledge_graph_isomorphism",
    ),
    TEMPORAL_WINDOW_AGREEMENT: (
        "temporal_window_agreement",
        "temporal_window_agreement_score",
        "temporal_window_success_rate",
    ),
    DECOMPILER_ROUND_TRIP_PRESERVATION: (
        "decompiler_round_trip_preservation",
        "decompiler_round_trip_preservation_score",
        "decompiler_round_trip_success_rate",
        "round_trip_preservation",
    ),
    PROOF_OBLIGATION_DELTA_SCORE: (
        "proof_obligation_delta_score",
        "proof_obligation_equivalence",
        "proof_obligation_preservation",
        "proof_obligation_success_rate",
    ),
}

_PROOF_DELTA_ALIASES: Final = (
    "proof_obligation_delta",
    "proof_obligation_symmetric_difference",
    "proof_obligation_delta_count",
)

_REFERENCE_KEYS: Final = (
    "reference_ir",
    "canonical_ir",
    "expected_ir",
    "target_ir",
    "reference_legal_ir",
    "canonical_legal_ir",
)
_CANDIDATE_KEYS: Final = (
    "candidate_ir",
    "predicted_ir",
    "actual_ir",
    "decoded_ir",
    "candidate_legal_ir",
    "predicted_legal_ir",
)

_IGNORED_NORMALIZATION_KEYS: Final = frozenset(
    {
        "created_at",
        "digest",
        "hash",
        "id",
        "lineage",
        "metadata",
        "sample_id",
        "source_span",
        "span",
        "timestamp",
        "trace_id",
        "uuid",
    }
)

_MODALITY_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "obligation": ("must", "shall", "required", "obligated", "duty"),
    "permission": ("may", "permitted", "authorized", "can"),
    "prohibition": ("shall not", "must not", "prohibited", "forbidden"),
}


@dataclass(frozen=True, slots=True)
class SemanticEquivalenceConfig:
    """Policy for semantic-equivalence gate evaluation."""

    families: tuple[str, ...] = LEGAL_IR_EVALUATION_FAMILIES
    minimum_scores: Mapping[str, float] = field(
        default_factory=lambda: {metric: 1.0 for metric in SEMANTIC_EQUIVALENCE_METRICS}
    )
    regression_tolerance: float = 0.0
    require_complete_metrics: bool = True

    def __post_init__(self) -> None:
        families = tuple(canonical_legal_ir_evaluation_family(family) for family in self.families)
        if not families:
            raise ValueError("at least one LegalIR family is required")
        if len(set(families)) != len(families):
            raise ValueError("families must be unique after canonicalization")
        object.__setattr__(self, "families", families)

        minimum_scores: dict[str, float] = {}
        for metric in SEMANTIC_EQUIVALENCE_METRICS:
            value = _finite_float(self.minimum_scores.get(metric, 1.0), 1.0)
            if value < 0.0:
                raise ValueError(f"minimum score for {metric!r} must be non-negative")
            minimum_scores[metric] = min(1.0, value)
        object.__setattr__(self, "minimum_scores", minimum_scores)

        tolerance = _finite_float(self.regression_tolerance, 0.0)
        if tolerance < 0.0:
            raise ValueError("regression_tolerance must be non-negative")
        object.__setattr__(self, "regression_tolerance", tolerance)


@dataclass(frozen=True, slots=True)
class SemanticEquivalenceFamilyResult:
    """Semantic-equivalence evidence for one LegalIR family or IR pair."""

    family: str
    scores: Mapping[str, float]
    raw_deltas: Mapping[str, float] = field(default_factory=dict)
    missing_metrics: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def minimum_score(self) -> float:
        if not self.scores:
            return 0.0
        return min(float(value) for value in self.scores.values())

    @property
    def complete(self) -> bool:
        return not self.missing_metrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "detail": _json_ready(self.detail),
            "evidence_sources": list(self.evidence_sources),
            "family": self.family,
            "minimum_score": round(self.minimum_score, 12),
            "missing_metrics": list(self.missing_metrics),
            "raw_deltas": _round_mapping(self.raw_deltas),
            "scores": _round_mapping(self.scores),
        }


@dataclass(frozen=True, slots=True)
class SemanticEquivalenceFamilyComparison:
    """Before/after semantic-equivalence gate result for one family."""

    family: str
    before: SemanticEquivalenceFamilyResult
    after: SemanticEquivalenceFamilyResult
    metric_deltas: Mapping[str, float]
    regressions: Mapping[str, Mapping[str, float]]
    threshold_failures: Mapping[str, Mapping[str, float]]
    ce_cosine_improvements: Mapping[str, float] = field(default_factory=dict)

    @property
    def missing_metrics(self) -> tuple[str, ...]:
        missing = set(self.before.missing_metrics) | set(self.after.missing_metrics)
        return tuple(metric for metric in SEMANTIC_EQUIVALENCE_METRICS if metric in missing)

    @property
    def semantic_regressed(self) -> bool:
        return bool(self.regressions or self.threshold_failures)

    @property
    def ce_cosine_improved(self) -> bool:
        return bool(self.ce_cosine_improvements)

    @property
    def disagreement(self) -> bool:
        return self.ce_cosine_improved and self.semantic_regressed

    @property
    def passed(self) -> bool:
        return not self.missing_metrics and not self.semantic_regressed

    @property
    def status(self) -> str:
        if self.missing_metrics:
            return "semantic_equivalence_evidence_missing"
        if self.threshold_failures:
            return "semantic_equivalence_threshold_failed"
        if self.regressions:
            return "semantic_equivalence_regressed"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "after": self.after.to_dict(),
            "before": self.before.to_dict(),
            "ce_cosine_improved": self.ce_cosine_improved,
            "ce_cosine_improvements": _round_mapping(self.ce_cosine_improvements),
            "disagreement": self.disagreement,
            "family": self.family,
            "metric_deltas": _round_mapping(self.metric_deltas),
            "missing_metrics": list(self.missing_metrics),
            "passed": self.passed,
            "regressions": _json_ready(self.regressions),
            "status": self.status,
            "threshold_failures": _json_ready(self.threshold_failures),
        }


@dataclass(frozen=True, slots=True)
class SemanticEquivalenceComparisonReport:
    """Hard-gate report for semantic equivalence across LegalIR families."""

    family_results: Mapping[str, SemanticEquivalenceFamilyComparison]
    block_reasons: tuple[str, ...]
    disagreements: tuple[str, ...]
    gate_id: str
    schema_version: str = LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION

    @property
    def accepted(self) -> bool:
        return not self.block_reasons

    @property
    def failed_families(self) -> tuple[str, ...]:
        return tuple(family for family, result in self.family_results.items() if not result.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "block_reasons": list(self.block_reasons),
            "disagreements": list(self.disagreements),
            "failed_families": list(self.failed_families),
            "families": list(self.family_results),
            "family_results": {
                family: result.to_dict() for family, result in self.family_results.items()
            },
            "gate_id": self.gate_id,
            "hard_promotion_gate": True,
            "metric_names": list(SEMANTIC_EQUIVALENCE_METRICS),
            "schema_version": self.schema_version,
            "status": "accepted" if self.accepted else "blocked",
        }


def evaluate_legal_ir_semantic_equivalence(
    reference_ir: Any,
    candidate_ir: Any,
    *,
    family: str = "unscoped",
) -> SemanticEquivalenceFamilyResult:
    """Compute semantic-equivalence scores for one reference/candidate IR pair."""

    family_name = _canonical_family_or_unscoped(family)
    structural_left = _structural_signature(reference_ir)
    structural_right = _structural_signature(candidate_ir)
    obligations_left = _obligation_signature(reference_ir)
    obligations_right = _obligation_signature(candidate_ir)
    counterexamples_left = _counterexample_signature(reference_ir)
    counterexamples_right = _counterexample_signature(candidate_ir)
    graph_left = _graph_signature(reference_ir)
    graph_right = _graph_signature(candidate_ir)
    temporal_left = _temporal_window_signature(reference_ir)
    temporal_right = _temporal_window_signature(candidate_ir)
    decompiler_left = _decompiler_round_trip_signature(reference_ir)
    decompiler_right = _decompiler_round_trip_signature(candidate_ir)
    proof_left = _proof_obligation_signature(reference_ir)
    proof_right = _proof_obligation_signature(candidate_ir)
    proof_delta = float(len(proof_left ^ proof_right))

    scores = {
        STRUCTURAL_EQUIVALENCE: _set_similarity(structural_left, structural_right),
        OBLIGATION_EQUIVALENCE: _empty_aware_similarity(
            obligations_left,
            obligations_right,
        ),
        COUNTEREXAMPLE_EQUIVALENCE: _empty_aware_similarity(
            counterexamples_left,
            counterexamples_right,
        ),
        GRAPH_ISOMORPHISM: _empty_aware_similarity(graph_left, graph_right),
        TEMPORAL_WINDOW_AGREEMENT: _empty_aware_similarity(
            temporal_left,
            temporal_right,
        ),
        DECOMPILER_ROUND_TRIP_PRESERVATION: _empty_aware_similarity(
            decompiler_left or structural_left,
            decompiler_right or structural_right,
        ),
        PROOF_OBLIGATION_DELTA_SCORE: _proof_delta_score(proof_left, proof_right),
    }
    return SemanticEquivalenceFamilyResult(
        family=family_name,
        scores=scores,
        raw_deltas={PROOF_OBLIGATION_DELTA: proof_delta},
        evidence_sources=("computed_ir_pair",),
        detail={
            "counterexample_signature_sizes": {
                "candidate": len(counterexamples_right),
                "reference": len(counterexamples_left),
            },
            "graph_signature_sizes": {
                "candidate": len(graph_right),
                "reference": len(graph_left),
            },
            "obligation_signature_sizes": {
                "candidate": len(obligations_right),
                "reference": len(obligations_left),
            },
            "proof_obligation_counts": {
                "candidate": len(proof_right),
                "reference": len(proof_left),
                "symmetric_difference": int(proof_delta),
            },
            "temporal_window_signature_sizes": {
                "candidate": len(temporal_right),
                "reference": len(temporal_left),
            },
        },
    )


def semantic_equivalence_from_metrics(
    payload: Mapping[str, Any],
    *,
    family: str,
) -> SemanticEquivalenceFamilyResult:
    """Extract or compute semantic-equivalence metrics from one family payload."""

    source = dict(payload or {})
    reference_ir, candidate_ir = _reference_candidate_pair(source)
    if reference_ir is not _MISSING and candidate_ir is not _MISSING:
        computed = evaluate_legal_ir_semantic_equivalence(
            reference_ir,
            candidate_ir,
            family=family,
        )
        explicit = _explicit_semantic_scores(source)
        if not explicit:
            return computed
        merged = dict(computed.scores)
        merged.update(explicit)
        raw_deltas = dict(computed.raw_deltas)
        raw_deltas.update(_explicit_proof_deltas(source))
        return SemanticEquivalenceFamilyResult(
            family=computed.family,
            scores=merged,
            raw_deltas=raw_deltas,
            missing_metrics=tuple(
                metric for metric in SEMANTIC_EQUIVALENCE_METRICS if metric not in merged
            ),
            evidence_sources=("computed_ir_pair", "explicit_metric"),
            detail=computed.detail,
        )

    scores = _explicit_semantic_scores(source)
    raw_deltas = _explicit_proof_deltas(source)
    if PROOF_OBLIGATION_DELTA_SCORE not in scores and PROOF_OBLIGATION_DELTA in raw_deltas:
        scores[PROOF_OBLIGATION_DELTA_SCORE] = 1.0 / (
            1.0 + max(0.0, raw_deltas[PROOF_OBLIGATION_DELTA])
        )
    missing = tuple(metric for metric in SEMANTIC_EQUIVALENCE_METRICS if metric not in scores)
    return SemanticEquivalenceFamilyResult(
        family=_canonical_family_or_unscoped(family),
        scores=scores,
        raw_deltas=raw_deltas,
        missing_metrics=missing,
        evidence_sources=("explicit_metric",) if scores or raw_deltas else (),
    )


def compare_legal_ir_semantic_equivalence(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    config: Optional[SemanticEquivalenceConfig] = None,
    families: Optional[Sequence[str]] = None,
    regression_tolerance: Optional[float] = None,
) -> SemanticEquivalenceComparisonReport:
    """Compare before/after semantic-equivalence evidence by family."""

    if config is None:
        config = SemanticEquivalenceConfig(
            families=tuple(families) if families is not None else LEGAL_IR_EVALUATION_FAMILIES,
            regression_tolerance=0.0 if regression_tolerance is None else regression_tolerance,
        )
    elif families is not None or regression_tolerance is not None:
        config = SemanticEquivalenceConfig(
            families=tuple(families) if families is not None else config.families,
            minimum_scores=config.minimum_scores,
            regression_tolerance=config.regression_tolerance
            if regression_tolerance is None
            else regression_tolerance,
            require_complete_metrics=config.require_complete_metrics,
        )

    baseline = _extract_family_payloads(baseline_metrics, config.families)
    candidate = _extract_family_payloads(candidate_metrics, config.families)
    family_results: dict[str, SemanticEquivalenceFamilyComparison] = {}
    for family in config.families:
        before = semantic_equivalence_from_metrics(baseline.get(family, {}), family=family)
        after = semantic_equivalence_from_metrics(candidate.get(family, {}), family=family)
        deltas = {
            metric: round(after.scores.get(metric, 0.0) - before.scores.get(metric, 0.0), 12)
            for metric in SEMANTIC_EQUIVALENCE_METRICS
            if metric in before.scores and metric in after.scores
        }
        regressions = _semantic_regressions(before, after, config)
        threshold_failures = _semantic_threshold_failures(after, config)
        if not config.require_complete_metrics:
            threshold_failures = {
                key: value for key, value in threshold_failures.items() if key in after.scores
            }
        comparison = SemanticEquivalenceFamilyComparison(
            family=family,
            before=before,
            after=after,
            metric_deltas=deltas,
            regressions=regressions,
            threshold_failures=threshold_failures,
            ce_cosine_improvements=_ce_cosine_improvements(
                baseline.get(family, {}),
                candidate.get(family, {}),
            ),
        )
        family_results[family] = comparison

    block_reasons = _semantic_block_reasons(family_results, config)
    disagreements = tuple(
        f"{family}:ce_cosine_improved_semantic_equivalence_regressed"
        for family, result in family_results.items()
        if result.disagreement
    )
    descriptor = {
        "after": {family: result.after.scores for family, result in family_results.items()},
        "before": {family: result.before.scores for family, result in family_results.items()},
        "families": config.families,
        "minimum_scores": config.minimum_scores,
    }
    return SemanticEquivalenceComparisonReport(
        family_results=family_results,
        block_reasons=tuple(block_reasons),
        disagreements=disagreements,
        gate_id="lir-semantic-equivalence-" + _stable_hash(descriptor)[:24],
    )


def semantic_equivalence_promotion_gate(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    config: Optional[SemanticEquivalenceConfig] = None,
) -> dict[str, Any]:
    """Dictionary API for rollout/promotion callers."""

    return compare_legal_ir_semantic_equivalence(
        baseline_metrics,
        candidate_metrics,
        config=config,
    ).to_dict()


class _Missing:
    pass


_MISSING = _Missing()


def _extract_family_payloads(
    payload: Mapping[str, Any],
    families: Sequence[str],
) -> dict[str, dict[str, Any]]:
    source = _mapping_payload(payload)
    by_family: dict[str, dict[str, Any]] = {family: {} for family in families}
    for key in (
        "semantic_equivalence_metrics",
        "semantic_equivalence_by_family",
        "semantic_family_metrics",
        "view_family_metrics",
        "legal_ir_view_family_metrics",
    ):
        nested = source.get(key)
        if isinstance(nested, Mapping):
            _merge_nested_family_payload(nested, by_family)
            family_metrics = nested.get("family_metrics")
            if isinstance(family_metrics, Mapping):
                _merge_nested_family_payload(family_metrics, by_family)

    flat = source.get("flat_metrics")
    if isinstance(flat, Mapping):
        _merge_flat_family_payload(flat, by_family)
    _merge_flat_family_payload(source, by_family)
    losses = source.get("legal_ir_losses")
    if isinstance(losses, Mapping):
        _merge_flat_family_payload(losses, by_family)
    return by_family


def _merge_nested_family_payload(
    nested: Mapping[str, Any],
    by_family: dict[str, dict[str, Any]],
) -> None:
    for raw_family, raw_metrics in nested.items():
        family = _canonical_family_or_empty(str(raw_family))
        if family in by_family and isinstance(raw_metrics, Mapping):
            by_family[family].update(dict(raw_metrics))


def _merge_flat_family_payload(
    flat: Mapping[str, Any],
    by_family: dict[str, dict[str, Any]],
) -> None:
    prefixes = (
        "legal_ir_view_family_",
        "legal_ir_semantic_family_",
        "semantic_equivalence_family_",
    )
    for key, value in flat.items():
        name = str(key)
        for prefix in prefixes:
            if not name.startswith(prefix):
                continue
            remainder = name.removeprefix(prefix)
            for family in sorted(by_family, key=len, reverse=True):
                aliases = (family, "kg") if family == "knowledge_graphs" else (family,)
                for alias in aliases:
                    marker = f"{alias}_"
                    if remainder.startswith(marker):
                        by_family[family][remainder.removeprefix(marker)] = value
                        break


def _explicit_semantic_scores(payload: Mapping[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for metric, aliases in _METRIC_ALIASES.items():
        for alias in aliases:
            if alias not in payload:
                continue
            value = _maybe_float(payload[alias])
            if value is not None:
                scores[metric] = min(1.0, max(0.0, value))
                break
    return scores


def _explicit_proof_deltas(payload: Mapping[str, Any]) -> dict[str, float]:
    for alias in _PROOF_DELTA_ALIASES:
        if alias not in payload:
            continue
        value = _maybe_float(payload[alias])
        if value is not None:
            return {PROOF_OBLIGATION_DELTA: max(0.0, value)}
    return {}


def _reference_candidate_pair(payload: Mapping[str, Any]) -> tuple[Any, Any]:
    reference = _MISSING
    candidate = _MISSING
    pair = payload.get("semantic_equivalence")
    if isinstance(pair, Mapping):
        reference, candidate = _reference_candidate_pair(pair)
    for key in _REFERENCE_KEYS:
        if key in payload:
            reference = payload[key]
            break
    for key in _CANDIDATE_KEYS:
        if key in payload:
            candidate = payload[key]
            break
    return reference, candidate


def _semantic_regressions(
    before: SemanticEquivalenceFamilyResult,
    after: SemanticEquivalenceFamilyResult,
    config: SemanticEquivalenceConfig,
) -> dict[str, Mapping[str, float]]:
    regressions: dict[str, Mapping[str, float]] = {}
    for metric in SEMANTIC_EQUIVALENCE_METRICS:
        if metric not in before.scores or metric not in after.scores:
            continue
        regression = before.scores[metric] - after.scores[metric]
        if regression > config.regression_tolerance:
            regressions[metric] = {
                "after": round(after.scores[metric], 12),
                "before": round(before.scores[metric], 12),
                "regression": round(regression, 12),
            }
    return regressions


def _semantic_threshold_failures(
    after: SemanticEquivalenceFamilyResult,
    config: SemanticEquivalenceConfig,
) -> dict[str, Mapping[str, float]]:
    failures: dict[str, Mapping[str, float]] = {}
    for metric, minimum in config.minimum_scores.items():
        score = after.scores.get(metric)
        if score is None:
            continue
        if score + config.regression_tolerance < minimum:
            failures[metric] = {
                "actual": round(score, 12),
                "minimum": round(minimum, 12),
            }
    return failures


def _semantic_block_reasons(
    family_results: Mapping[str, SemanticEquivalenceFamilyComparison],
    config: SemanticEquivalenceConfig,
) -> list[str]:
    reasons: list[str] = []
    for family, result in family_results.items():
        if config.require_complete_metrics and result.missing_metrics:
            reasons.append(f"{family}:semantic_equivalence_evidence_missing")
        if result.threshold_failures:
            reasons.append(f"{family}:semantic_equivalence_threshold_failed")
        if result.regressions:
            reasons.append(f"{family}:semantic_equivalence_regressed")
        if result.disagreement:
            reasons.append(f"{family}:ce_cosine_semantic_disagreement")
    return reasons


def _ce_cosine_improvements(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, float]:
    aliases: Mapping[str, tuple[tuple[str, ...], bool]] = {
        "learned_cross_entropy_loss": (
            (
                "learned_cross_entropy_loss",
                "autoencoder_cross_entropy_loss",
                "legal_ir_view_cross_entropy_loss",
                "cross_entropy_loss",
            ),
            False,
        ),
        "compiler_cross_entropy_loss": (
            (
                "compiler_cross_entropy_loss",
                "compiler_ir_cross_entropy_loss",
                "ir_cross_entropy_loss",
            ),
            False,
        ),
        "learned_cosine_similarity": (
            (
                "learned_cosine_similarity",
                "autoencoder_cosine_similarity",
                "embedding_cosine_similarity",
                "cosine_similarity",
            ),
            True,
        ),
        "compiler_cosine_similarity": (
            (
                "compiler_cosine_similarity",
                "compiler_ir_cosine_similarity",
                "ir_cosine_similarity",
            ),
            True,
        ),
    }
    improvements: dict[str, float] = {}
    for name, (metric_aliases, higher_is_better) in aliases.items():
        before = _first_float(baseline, metric_aliases)
        after = _first_float(candidate, metric_aliases)
        if before is None or after is None:
            continue
        delta = after - before if higher_is_better else before - after
        if delta > 0.0:
            improvements[name] = round(delta, 12)
    return improvements


def _structural_signature(value: Any) -> frozenset[str]:
    tokens: set[str] = set()

    def visit(item: Any, path: tuple[str, ...]) -> None:
        if isinstance(item, Mapping):
            keys = tuple(
                _normalize_token(key)
                for key in item
                if _normalize_token(key) not in _IGNORED_NORMALIZATION_KEYS
            )
            tokens.add("dict:" + "/".join(path) + ":" + ",".join(sorted(keys)))
            for key, child in sorted(item.items(), key=lambda pair: str(pair[0])):
                key_token = _normalize_token(key)
                if key_token in _IGNORED_NORMALIZATION_KEYS:
                    continue
                visit(child, path + (key_token,))
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            tokens.add(f"list:{'/'.join(path)}:{len(item)}")
            for child in item:
                visit(child, path + ("[]",))
            return
        scalar = _normalize_scalar(item)
        if (
            path
            and path[-1] in {"from", "source", "subject", "target", "to"}
            and any(part in {"edge", "edges", "relationships"} for part in path)
        ):
            scalar = "<graph-endpoint>"
        tokens.add("scalar:" + "/".join(path) + ":" + scalar)

    visit(value, ())
    return frozenset(tokens)


def _obligation_signature(value: Any) -> frozenset[str]:
    obligations: set[str] = set()

    def visit(item: Any, context: Mapping[str, Any] | None = None) -> None:
        if isinstance(item, Mapping):
            keys = {_normalize_token(key): child for key, child in item.items()}
            modality = _normalize_scalar(
                keys.get("modality")
                or keys.get("type")
                or keys.get("norm_type")
                or keys.get("obligation_type")
                or ""
            )
            if modality in {"obligation", "permission", "prohibition"} or any(
                name in keys for name in ("obligation", "obligations", "duty", "duties")
            ):
                subject = _normalize_scalar(
                    keys.get("subject")
                    or keys.get("actor")
                    or keys.get("agent")
                    or keys.get("party")
                    or ""
                )
                action = _normalize_scalar(
                    keys.get("action")
                    or keys.get("predicate")
                    or keys.get("verb")
                    or keys.get("duty")
                    or keys.get("obligation")
                    or ""
                )
                condition = _normalize_scalar(
                    keys.get("condition")
                    or keys.get("unless")
                    or keys.get("if")
                    or keys.get("exception")
                    or ""
                )
                obligations.add(
                    "structured:"
                    + "|".join(
                        (
                            modality or "obligation",
                            subject,
                            action,
                            condition,
                        )
                    )
                )
            for key, child in item.items():
                if "obligation" in _normalize_token(key) and isinstance(
                    child,
                    (str, int, float, bool),
                ):
                    obligations.add("keyed:" + _normalize_scalar(child))
                visit(child, item)
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for child in item:
                visit(child, context)
            return
        if isinstance(item, str):
            text = _normalize_text(item)
            for modality, words in _MODALITY_WORDS.items():
                if any(word in text for word in words):
                    obligations.add(f"text:{modality}:{_compact_clause(text)}")

    visit(value)
    return frozenset(obligations)


def _counterexample_signature(value: Any) -> frozenset[str]:
    return frozenset(_contextual_values(value, ("counterexample", "cex", "witness_model")))


def _graph_signature(value: Any) -> frozenset[str]:
    signatures: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if "triples" in item and isinstance(item["triples"], Sequence):
                for triple in item["triples"]:
                    triple_sig = _triple_signature(triple)
                    if triple_sig:
                        signatures.add(triple_sig)
            if "kg_triples" in item and isinstance(item["kg_triples"], Sequence):
                for triple in item["kg_triples"]:
                    triple_sig = _triple_signature(triple)
                    if triple_sig:
                        signatures.add(triple_sig)
            nodes = item.get("nodes")
            edges = item.get("edges") or item.get("relationships")
            if isinstance(nodes, Sequence) and isinstance(edges, Sequence):
                node_labels = _node_label_map(nodes)
                for edge in edges:
                    edge_sig = _edge_signature(edge, node_labels)
                    if edge_sig:
                        signatures.add(edge_sig)
            for child in item.values():
                visit(child)
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for child in item:
                visit(child)

    visit(value)
    return frozenset(signatures)


def _temporal_window_signature(value: Any) -> frozenset[str]:
    windows: set[str] = set()

    def visit(item: Any, key_hint: str = "") -> None:
        if isinstance(item, Mapping):
            keys = {_normalize_token(key): child for key, child in item.items()}
            start = _date_like(
                keys.get("start")
                or keys.get("from")
                or keys.get("effective")
                or keys.get("begin")
                or keys.get("after")
            )
            end = _date_like(
                keys.get("end")
                or keys.get("to")
                or keys.get("expires")
                or keys.get("deadline")
                or keys.get("before")
            )
            duration = _duration_like(
                keys.get("duration") or keys.get("within") or keys.get("window")
            )
            if start or end or duration:
                windows.add("|".join((start or "", end or "", duration or "")))
            for key, child in item.items():
                visit(child, _normalize_token(key))
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for child in item:
                visit(child, key_hint)
            return
        if isinstance(item, str):
            if any(marker in key_hint for marker in ("time", "date", "window", "deadline")):
                parsed = _date_like(item) or _duration_like(item)
                if parsed:
                    windows.add(parsed)
            for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", item):
                windows.add(match.group(0))
            for match in re.finditer(
                r"\bwithin\s+\d+\s+(?:day|days|month|months|year|years)\b", item, re.I
            ):
                windows.add(_duration_like(match.group(0)) or _normalize_text(match.group(0)))

    visit(value)
    return frozenset(windows)


def _decompiler_round_trip_signature(value: Any) -> frozenset[str]:
    return frozenset(
        _contextual_values(
            value,
            (
                "decompiled",
                "decompiler",
                "round_trip",
                "roundtrip",
                "reconstructed_ir",
                "recompiled_ir",
            ),
        )
    )


def _proof_obligation_signature(value: Any) -> frozenset[str]:
    proof_ids: set[str] = set(_contextual_values(value, ("proof_obligation", "goal_name")))

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = _normalize_token(key)
                if key_text in {
                    "proof_obligation_ids",
                    "proof_obligations",
                    "obligation_id",
                    "goal_name",
                }:
                    proof_ids.update(_flatten_scalars(child))
                visit(child)
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for child in item:
                visit(child)

    visit(value)
    return frozenset(_normalize_scalar(item) for item in proof_ids if item)


def _contextual_values(value: Any, key_markers: Sequence[str]) -> set[str]:
    values: set[str] = set()

    def visit(item: Any, active: bool = False, key_hint: str = "") -> None:
        marker_active = active or any(marker in key_hint for marker in key_markers)
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, marker_active, _normalize_token(key))
            return
        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for child in item:
                visit(child, marker_active, key_hint)
            return
        if marker_active:
            values.add(_normalize_scalar(item))

    visit(value)
    return {item for item in values if item}


def _node_label_map(nodes: Sequence[Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for index, raw_node in enumerate(nodes):
        if isinstance(raw_node, Mapping):
            raw_id = raw_node.get("id", raw_node.get("node_id", index))
            label = raw_node.get("label") or raw_node.get("name") or raw_node.get("type") or raw_id
        else:
            raw_id = index
            label = raw_node
        labels[_normalize_scalar(raw_id)] = _normalize_scalar(label)
    return labels


def _edge_signature(edge: Any, node_labels: Mapping[str, str]) -> str:
    if isinstance(edge, Mapping):
        source = edge.get("source", edge.get("from", edge.get("subject", "")))
        target = edge.get("target", edge.get("to", edge.get("object", "")))
        relation = edge.get("label", edge.get("type", edge.get("predicate", "")))
    elif isinstance(edge, Sequence) and not isinstance(edge, (str, bytes, bytearray)):
        values = list(edge)
        if len(values) < 2:
            return ""
        source = values[0]
        relation = values[1] if len(values) > 2 else ""
        target = values[2] if len(values) > 2 else values[1]
    else:
        return ""
    source_label = node_labels.get(_normalize_scalar(source), _normalize_scalar(source))
    target_label = node_labels.get(_normalize_scalar(target), _normalize_scalar(target))
    return "edge:" + "|".join(
        (
            _normalize_scalar(source_label),
            _normalize_scalar(relation),
            _normalize_scalar(target_label),
        )
    )


def _triple_signature(triple: Any) -> str:
    if isinstance(triple, Mapping):
        subject = triple.get("subject", triple.get("s", ""))
        predicate = triple.get("predicate", triple.get("p", triple.get("relation", "")))
        obj = triple.get("object", triple.get("o", ""))
    elif isinstance(triple, Sequence) and not isinstance(triple, (str, bytes, bytearray)):
        values = list(triple)
        if len(values) < 3:
            return ""
        subject, predicate, obj = values[:3]
    else:
        return ""
    return "edge:" + "|".join(
        (_normalize_scalar(subject), _normalize_scalar(predicate), _normalize_scalar(obj))
    )


def _flatten_scalars(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {item for child in value.values() for item in _flatten_scalars(child)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {item for child in value for item in _flatten_scalars(child)}
    return {_normalize_scalar(value)}


def _set_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return round(len(left & right) / len(union), 12)


def _empty_aware_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    return _set_similarity(left, right)


def _proof_delta_score(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return round(1.0 - (len(left ^ right) / len(union)), 12)


def _date_like(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = _normalize_text(value)
    if not text:
        return ""
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b\d{4}\b", text)
    return match.group(0) if match else ""


def _duration_like(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    match = re.search(r"\b(?:within\s+)?(\d+)\s+(day|days|month|months|year|years)\b", text)
    if not match:
        return ""
    unit = match.group(2)
    if unit.endswith("s"):
        unit = unit[:-1]
    return f"{int(match.group(1))}:{unit}"


def _compact_clause(text: str) -> str:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return " ".join(words[:16])


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(round(value, 12)) if math.isfinite(value) else "0"
    if isinstance(value, int):
        return str(value)
    return _normalize_text(value)


def _canonical_family_or_empty(value: str) -> str:
    try:
        return canonical_legal_ir_evaluation_family(value)
    except ValueError:
        return ""


def _canonical_family_or_unscoped(value: str) -> str:
    family = _canonical_family_or_empty(value)
    return family or str(value or "unscoped")


def _mapping_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        raw = value.to_dict()
        return dict(raw) if isinstance(raw, Mapping) else {}
    return dict(value or {})


def _first_float(payload: Mapping[str, Any], aliases: Sequence[str]) -> Optional[float]:
    for alias in aliases:
        if alias not in payload:
            continue
        value = _maybe_float(payload[alias])
        if value is not None:
            return value
    return None


def _maybe_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_float(value: Any, default: float) -> float:
    number = _maybe_float(value)
    return float(default) if number is None else number


def _round_mapping(values: Mapping[str, Any]) -> dict[str, float]:
    rounded: dict[str, float] = {}
    for key, value in sorted(values.items()):
        number = _maybe_float(value)
        if number is not None:
            rounded[str(key)] = round(number, 12)
    return rounded


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_ready(item) for item in value)
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else 0.0
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _json_ready(value),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class LatentRepresentationRecord:
    """One frozen representation used for diagnostic/calibration instrumentation."""

    sample_id: str
    vector: tuple[float, ...]
    family: str = ""
    domain: str = ""
    jurisdiction: str = ""
    length_bin: str = ""
    length: Optional[float] = None
    duplicate_group: str = ""
    split: str = "development"
    ood: bool = False
    success: Optional[bool] = None
    confidence: Optional[float] = None
    latent_used: bool = True
    semantic_class: str = ""

    def __post_init__(self) -> None:
        sample_id = str(self.sample_id or "").strip()
        if not sample_id:
            raise ValueError("sample_id must be non-empty")
        vector = tuple(float(value) for value in self.vector)
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("representation vector contains a non-finite value")
        object.__setattr__(self, "sample_id", sample_id)
        object.__setattr__(self, "vector", vector)
        object.__setattr__(self, "family", str(self.family or "").strip())
        object.__setattr__(self, "domain", str(self.domain or "").strip())
        object.__setattr__(self, "jurisdiction", str(self.jurisdiction or "").strip())
        object.__setattr__(self, "length_bin", str(self.length_bin or "").strip())
        object.__setattr__(self, "duplicate_group", str(self.duplicate_group or "").strip())
        object.__setattr__(self, "split", str(self.split or "development").strip().lower())
        object.__setattr__(self, "semantic_class", str(self.semantic_class or "").strip())
        if self.confidence is not None:
            confidence = float(self.confidence)
            if not math.isfinite(confidence):
                raise ValueError("confidence must be finite")
            object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))
        if self.length is not None:
            length = float(self.length)
            if not math.isfinite(length) or length < 0.0:
                raise ValueError("length must be finite and non-negative")
            object.__setattr__(self, "length", length)

    @property
    def dimension(self) -> int:
        return len(self.vector)

    @property
    def neighborhood_class(self) -> str:
        return self.semantic_class or self.family or "unspecified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "domain": self.domain,
            "duplicate_group": self.duplicate_group,
            "family": self.family,
            "jurisdiction": self.jurisdiction,
            "latent_used": bool(self.latent_used),
            "length": self.length,
            "length_bin": self.length_bin,
            "ood": bool(self.ood),
            "sample_id": self.sample_id,
            "semantic_class": self.semantic_class,
            "split": self.split,
            "success": self.success,
            "vector": list(self.vector),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LatentRepresentationRecord":
        success = payload.get("success")
        if success is None:
            success = payload.get("correct")
        if not isinstance(success, bool):
            success = None if success is None else bool(success)
        vector = payload.get("vector")
        if vector is None:
            vector = payload.get("latent") or payload.get("embedding") or ()
        return cls(
            sample_id=str(payload.get("sample_id") or payload.get("id") or ""),
            vector=tuple(float(value) for value in vector or ()),
            family=str(payload.get("family") or ""),
            domain=str(payload.get("domain") or ""),
            jurisdiction=str(payload.get("jurisdiction") or ""),
            length_bin=str(payload.get("length_bin") or ""),
            length=payload.get("length"),
            duplicate_group=str(payload.get("duplicate_group") or ""),
            split=str(payload.get("split") or "development"),
            ood=bool(payload.get("ood", False)),
            success=success,
            confidence=payload.get("confidence"),
            latent_used=bool(payload.get("latent_used", True)),
            semantic_class=str(payload.get("semantic_class") or ""),
        )


def coerce_latent_records(records: Sequence[Any]) -> tuple[LatentRepresentationRecord, ...]:
    coerced: list[LatentRepresentationRecord] = []
    for item in records or ():
        if isinstance(item, LatentRepresentationRecord):
            coerced.append(item)
            continue
        if isinstance(item, Mapping):
            coerced.append(LatentRepresentationRecord.from_mapping(item))
            continue
        if hasattr(item, "to_dict") and callable(item.to_dict):
            raw = item.to_dict()
            if isinstance(raw, Mapping):
                coerced.append(LatentRepresentationRecord.from_mapping(raw))
                continue
        payload = {
            name: getattr(item, name)
            for name in (
                "sample_id",
                "vector",
                "latent",
                "embedding",
                "family",
                "domain",
                "jurisdiction",
                "length_bin",
                "length",
                "duplicate_group",
                "split",
                "ood",
                "success",
                "correct",
                "confidence",
                "latent_used",
                "semantic_class",
            )
            if hasattr(item, name)
        }
        if "vector" not in payload:
            payload["vector"] = payload.get("latent") or payload.get("embedding") or ()
        coerced.append(LatentRepresentationRecord.from_mapping(payload))
    return tuple(coerced)


@dataclass(frozen=True, slots=True)
class LatentSpectrumReport:
    """Singular-value, rank, variance, and anisotropy diagnostics."""

    sample_count: int
    dimension: int
    singular_values: tuple[float, ...]
    effective_rank: Optional[float]
    participation_ratio: Optional[float]
    spectral_anisotropy: Optional[float]
    mean_cosine_to_mean: Optional[float]
    mean_l2_norm: Optional[float]
    std_l2_norm: Optional[float]
    min_l2_norm: Optional[float]
    max_l2_norm: Optional[float]
    total_variance: Optional[float]
    mean_per_dimension_variance: Optional[float]
    active_dimension_count: int
    active_dimension_ratio: Optional[float]
    latent_use_rate: Optional[float]
    vectors_normalized_for_cosine: bool
    unknown_denominators: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_dimension_count": self.active_dimension_count,
            "active_dimension_ratio": None
            if self.active_dimension_ratio is None
            else round(self.active_dimension_ratio, 12),
            "dimension": self.dimension,
            "effective_rank": None
            if self.effective_rank is None
            else round(self.effective_rank, 12),
            "latent_use_rate": None
            if self.latent_use_rate is None
            else round(self.latent_use_rate, 12),
            "max_l2_norm": None if self.max_l2_norm is None else round(self.max_l2_norm, 12),
            "mean_cosine_to_mean": None
            if self.mean_cosine_to_mean is None
            else round(self.mean_cosine_to_mean, 12),
            "mean_l2_norm": None if self.mean_l2_norm is None else round(self.mean_l2_norm, 12),
            "mean_per_dimension_variance": None
            if self.mean_per_dimension_variance is None
            else round(self.mean_per_dimension_variance, 12),
            "min_l2_norm": None if self.min_l2_norm is None else round(self.min_l2_norm, 12),
            "participation_ratio": None
            if self.participation_ratio is None
            else round(self.participation_ratio, 12),
            "sample_count": self.sample_count,
            "singular_values": [round(value, 12) for value in self.singular_values],
            "spectral_anisotropy": None
            if self.spectral_anisotropy is None
            else round(self.spectral_anisotropy, 12),
            "std_l2_norm": None if self.std_l2_norm is None else round(self.std_l2_norm, 12),
            "total_variance": None if self.total_variance is None else round(self.total_variance, 12),
            "unknown_denominators": list(self.unknown_denominators),
            "vectors_normalized_for_cosine": self.vectors_normalized_for_cosine,
        }

    def metric_vector(self) -> dict[str, float]:
        values = {
            "active_dimension_count": float(self.active_dimension_count),
            "dimension": float(self.dimension),
            "sample_count": float(self.sample_count),
        }
        for name in (
            "effective_rank",
            "participation_ratio",
            "spectral_anisotropy",
            "mean_cosine_to_mean",
            "mean_l2_norm",
            "std_l2_norm",
            "total_variance",
            "latent_use_rate",
            "active_dimension_ratio",
        ):
            value = getattr(self, name)
            if value is not None:
                values[name] = round(float(value), 12)
        for index, value in enumerate(self.singular_values):
            values[f"singular_value_{index}"] = round(float(value), 12)
        return values


@dataclass(frozen=True, slots=True)
class FalseNeighborhoodReport:
    """Nearest-neighbor mixing that must not be treated as equivalence."""

    neighbor_k: int
    pair_count: int
    false_neighborhood_count: int
    false_neighborhood_rate: Optional[float]
    unknown_denominators: tuple[str, ...]
    latent_similarity_is_not_equivalence: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "false_neighborhood_count": self.false_neighborhood_count,
            "false_neighborhood_rate": None
            if self.false_neighborhood_rate is None
            else round(self.false_neighborhood_rate, 12),
            "latent_similarity_is_not_equivalence": True,
            "neighbor_k": self.neighbor_k,
            "pair_count": self.pair_count,
            "unknown_denominators": list(self.unknown_denominators),
        }


@dataclass(frozen=True, slots=True)
class LatentDiagnosticsReport:
    """Content-bound latent diagnostic block for one frozen representation batch."""

    spectrum: LatentSpectrumReport
    false_neighborhoods: FalseNeighborhoodReport
    schema_version: str = LEGAL_IR_LATENT_DIAGNOSTICS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "false_neighborhoods": self.false_neighborhoods.to_dict(),
            "latent_similarity_is_not_equivalence": True,
            "schema_version": self.schema_version,
            "spectrum": self.spectrum.to_dict(),
        }

    def metric_vector(self) -> dict[str, float]:
        values = self.spectrum.metric_vector()
        if self.false_neighborhoods.false_neighborhood_rate is not None:
            values["false_neighborhood_rate"] = round(
                self.false_neighborhoods.false_neighborhood_rate, 12
            )
        values["false_neighborhood_count"] = float(
            self.false_neighborhoods.false_neighborhood_count
        )
        return values


def evaluate_latent_diagnostics(
    records: Sequence[Any],
    *,
    neighbor_k: int = DEFAULT_FALSE_NEIGHBORHOOD_K,
    active_dimension_epsilon: float = DEFAULT_ACTIVE_DIMENSION_EPSILON,
) -> LatentDiagnosticsReport:
    """Measure singular values, rank, norms, anisotropy, use, and false neighborhoods."""

    batch = coerce_latent_records(records)
    return LatentDiagnosticsReport(
        spectrum=_evaluate_latent_spectrum(
            batch, active_dimension_epsilon=active_dimension_epsilon
        ),
        false_neighborhoods=_evaluate_false_neighborhoods(batch, neighbor_k=neighbor_k),
    )


def _evaluate_latent_spectrum(
    records: Sequence[LatentRepresentationRecord],
    *,
    active_dimension_epsilon: float,
) -> LatentSpectrumReport:
    unknown: list[str] = []
    sample_count = len(records)
    dimension = records[0].dimension if records else 0
    if sample_count == 0:
        unknown.extend(
            [
                "spectrum:no_records",
                "effective_rank",
                "participation_ratio",
                "spectral_anisotropy",
                "mean_cosine_to_mean",
                "variance",
                "latent_use_rate",
            ]
        )
        return LatentSpectrumReport(
            sample_count=0,
            dimension=0,
            singular_values=(),
            effective_rank=None,
            participation_ratio=None,
            spectral_anisotropy=None,
            mean_cosine_to_mean=None,
            mean_l2_norm=None,
            std_l2_norm=None,
            min_l2_norm=None,
            max_l2_norm=None,
            total_variance=None,
            mean_per_dimension_variance=None,
            active_dimension_count=0,
            active_dimension_ratio=None,
            latent_use_rate=None,
            vectors_normalized_for_cosine=True,
            unknown_denominators=tuple(unknown),
        )
    if any(record.dimension != dimension for record in records):
        raise ValueError("representation vectors must share one dimension")
    if dimension == 0:
        unknown.append("spectrum:zero_dimension")
    matrix = [list(record.vector) for record in records]
    norms = [_l2(vector) for vector in matrix]
    mean_norm = _mean_numbers(norms)
    std_norm = _std_numbers(norms)
    used = [1.0 if record.latent_used else 0.0 for record in records]
    latent_use_rate = _mean_numbers(used)
    mean_vector = [_mean_numbers([vector[index] for vector in matrix]) for index in range(dimension)]
    centered = [
        [vector[index] - mean_vector[index] for index in range(dimension)] for vector in matrix
    ]
    variances = [
        _mean_numbers([(vector[index] - mean_vector[index]) ** 2 for vector in matrix])
        for index in range(dimension)
    ]
    total_variance = sum(variances) if variances else None
    mean_variance = _mean_numbers(variances) if variances else None
    active = sum(1 for value in variances if value > active_dimension_epsilon)
    active_ratio = (active / dimension) if dimension else None
    singular_values = _singular_values(centered)
    energy = sum(value * value for value in singular_values)
    if energy <= 0.0:
        unknown.extend(
            [
                "spectrum:centered_matrix_is_zero",
                "effective_rank",
                "participation_ratio",
                "spectral_anisotropy",
            ]
        )
        effective_rank = None
        participation = None
        anisotropy = None
    else:
        masses = [(value * value) / energy for value in singular_values if value > 0.0]
        entropy = -sum(mass * math.log(mass) for mass in masses if mass > 0.0)
        effective_rank = math.exp(entropy) if masses else None
        quartic = sum((value * value) ** 2 for value in singular_values)
        participation = (energy * energy / quartic) if quartic > 0.0 else None
        anisotropy = (singular_values[0] * singular_values[0] / energy) if singular_values else None
    mean_cosine = _mean_cosine_to_mean(matrix, mean_vector)
    if mean_cosine is None:
        unknown.append("mean_cosine_to_mean")
    if sample_count < 2:
        unknown.append("spectrum:sample_count_below_two")
    return LatentSpectrumReport(
        sample_count=sample_count,
        dimension=dimension,
        singular_values=tuple(round(value, 12) for value in singular_values),
        effective_rank=effective_rank,
        participation_ratio=participation,
        spectral_anisotropy=anisotropy,
        mean_cosine_to_mean=mean_cosine,
        mean_l2_norm=mean_norm,
        std_l2_norm=std_norm,
        min_l2_norm=min(norms) if norms else None,
        max_l2_norm=max(norms) if norms else None,
        total_variance=total_variance,
        mean_per_dimension_variance=mean_variance,
        active_dimension_count=active,
        active_dimension_ratio=active_ratio,
        latent_use_rate=latent_use_rate,
        vectors_normalized_for_cosine=True,
        unknown_denominators=tuple(dict.fromkeys(unknown)),
    )


def _evaluate_false_neighborhoods(
    records: Sequence[LatentRepresentationRecord],
    *,
    neighbor_k: int,
) -> FalseNeighborhoodReport:
    unknown: list[str] = []
    k = max(1, int(neighbor_k))
    if len(records) < 2:
        unknown.append("false_neighborhoods:sample_count_below_two")
        return FalseNeighborhoodReport(
            neighbor_k=k,
            pair_count=0,
            false_neighborhood_count=0,
            false_neighborhood_rate=None,
            unknown_denominators=tuple(unknown),
        )
    normalized = [_unit_vector(record.vector) for record in records]
    if any(vector is None for vector in normalized):
        unknown.append("false_neighborhoods:zero_vector")
    pair_count = 0
    false_count = 0
    for index, left in enumerate(normalized):
        if left is None:
            continue
        scored: list[tuple[float, int]] = []
        for other_index, right in enumerate(normalized):
            if other_index == index or right is None:
                continue
            scored.append((_dot(left, right), other_index))
        scored.sort(key=lambda item: (-item[0], records[item[1]].sample_id, item[1]))
        neighbors = scored[:k]
        if len(neighbors) < k:
            unknown.append("false_neighborhoods:insufficient_neighbors")
        query_class = records[index].neighborhood_class
        for _score, other_index in neighbors:
            pair_count += 1
            other_class = records[other_index].neighborhood_class
            if query_class == "unspecified" or other_class == "unspecified":
                unknown.append("false_neighborhoods:unspecified_class")
                continue
            if other_class != query_class:
                false_count += 1
    rate = (false_count / pair_count) if pair_count else None
    if rate is None:
        unknown.append("false_neighborhood_rate")
    return FalseNeighborhoodReport(
        neighbor_k=k,
        pair_count=pair_count,
        false_neighborhood_count=false_count,
        false_neighborhood_rate=rate,
        unknown_denominators=tuple(dict.fromkeys(unknown)),
    )


def _singular_values(centered: Sequence[Sequence[float]]) -> tuple[float, ...]:
    rows = len(centered)
    cols = len(centered[0]) if centered else 0
    if rows == 0 or cols == 0:
        return ()
    if rows >= cols:
        gram = _matmul_ata(centered)
        eigenvalues = _jacobi_eigenvalues(gram)
        padded = [math.sqrt(max(0.0, value)) for value in eigenvalues]
        padded.sort(reverse=True)
        return tuple(padded)
    gram = _matmul_aat(centered)
    eigenvalues = _jacobi_eigenvalues(gram)
    values = [math.sqrt(max(0.0, value)) for value in eigenvalues]
    values.sort(reverse=True)
    values.extend([0.0] * (cols - len(values)))
    return tuple(values[:cols])


def _matmul_ata(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    cols = len(matrix[0])
    gram = [[0.0 for _ in range(cols)] for _ in range(cols)]
    for row in matrix:
        for i in range(cols):
            left = float(row[i])
            if left == 0.0:
                continue
            for j in range(i, cols):
                product = left * float(row[j])
                gram[i][j] += product
                if i != j:
                    gram[j][i] += product
    return gram


def _matmul_aat(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    rows = len(matrix)
    gram = [[0.0 for _ in range(rows)] for _ in range(rows)]
    for i in range(rows):
        for j in range(i, rows):
            product = _dot(matrix[i], matrix[j])
            gram[i][j] = product
            gram[j][i] = product
    return gram


def _jacobi_eigenvalues(matrix: Sequence[Sequence[float]]) -> list[float]:
    size = len(matrix)
    if size == 0:
        return []
    if size == 1:
        return [float(matrix[0][0])]
    work = [list(map(float, row)) for row in matrix]
    for _sweep in range(DEFAULT_JACOBI_SWEEPS):
        pivot_i, pivot_j, off = 0, 1, 0.0
        for i in range(size):
            for j in range(i + 1, size):
                value = abs(work[i][j])
                if value > off:
                    off, pivot_i, pivot_j = value, i, j
        if off <= DEFAULT_JACOBI_TOLERANCE:
            break
        app = work[pivot_i][pivot_i]
        aqq = work[pivot_j][pivot_j]
        apq = work[pivot_i][pivot_j]
        tau = (aqq - app) / (2.0 * apq)
        tangent = math.copysign(1.0, tau) / (abs(tau) + math.sqrt(1.0 + tau * tau))
        cosine = 1.0 / math.sqrt(1.0 + tangent * tangent)
        sine = tangent * cosine
        for k in range(size):
            if k in {pivot_i, pivot_j}:
                continue
            aik = work[k][pivot_i]
            ajk = work[k][pivot_j]
            work[k][pivot_i] = cosine * aik - sine * ajk
            work[pivot_i][k] = work[k][pivot_i]
            work[k][pivot_j] = sine * aik + cosine * ajk
            work[pivot_j][k] = work[k][pivot_j]
        work[pivot_i][pivot_i] = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq
        work[pivot_j][pivot_j] = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq
        work[pivot_i][pivot_j] = 0.0
        work[pivot_j][pivot_i] = 0.0
    return [work[index][index] for index in range(size)]


def _mean_cosine_to_mean(
    matrix: Sequence[Sequence[float]],
    mean_vector: Sequence[float],
) -> Optional[float]:
    unit_mean = _unit_vector(mean_vector)
    if unit_mean is None:
        return None
    values: list[float] = []
    for vector in matrix:
        unit = _unit_vector(vector)
        if unit is None:
            continue
        values.append(_dot(unit, unit_mean))
    return _mean_numbers(values)


def _unit_vector(vector: Sequence[float]) -> Optional[tuple[float, ...]]:
    norm = _l2(vector)
    if norm == 0.0:
        return None
    return tuple(float(value) / norm for value in vector)


def _l2(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _mean_numbers(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _std_numbers(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = _mean_numbers(values)
    if mean is None:
        return None
    variance = sum((float(value) - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(0.0, variance))


def synthetic_collapse_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Rank-1 batch whose centered spectrum occupies a single axis."""

    return tuple(
        LatentRepresentationRecord(
            sample_id=f"collapse-{index}",
            vector=(float(index), 0.0, 0.0),
            family="deontic",
            domain="notice",
            jurisdiction="us-federal",
            length_bin="short",
            length=12.0 + index,
            duplicate_group="collapse",
            split="development",
            success=True,
            confidence=0.9,
        )
        for index in range(1, 5)
    )


def synthetic_anisotropy_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Near-collinear batch with a known 2-D singular spectrum."""

    vectors = (
        (1.0, 0.0),
        (2.0, 0.1),
        (3.0, 0.0),
        (4.0, -0.1),
    )
    return tuple(
        LatentRepresentationRecord(
            sample_id=f"anisotropy-{index}",
            vector=vector,
            family="tdfol",
            domain="deadline",
            jurisdiction="us-federal",
            length_bin="medium",
            length=50.0 + index,
            duplicate_group=f"anisotropy-{index}",
            split="calibration",
            success=index < 3,
            confidence=0.8 if index < 3 else 0.2,
        )
        for index, vector in enumerate(vectors)
    )


def synthetic_memorization_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Exact duplicate groups used to trigger memorization diagnostics."""

    records: list[LatentRepresentationRecord] = []
    for group, family, vector in (
        ("dup-a", "deontic", (1.0, 0.0, 0.0, 0.0)),
        ("dup-b", "frame_logic", (0.0, 1.0, 0.0, 0.0)),
    ):
        for copy in range(3):
            records.append(
                LatentRepresentationRecord(
                    sample_id=f"{group}-{copy}",
                    vector=vector,
                    family=family,
                    domain="template",
                    jurisdiction="ca",
                    length_bin="short",
                    length=20.0,
                    duplicate_group=group,
                    split="development",
                    success=True,
                    confidence=0.99,
                )
            )
    return tuple(records)


def synthetic_orthogonal_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Centered orthogonal axes used as a well-conditioned golden batch."""

    families = ("deontic", "frame_logic", "tdfol")
    records: list[LatentRepresentationRecord] = []
    for axis, family in enumerate(families):
        positive = [0.0, 0.0, 0.0]
        negative = [0.0, 0.0, 0.0]
        positive[axis] = 1.0
        negative[axis] = -1.0
        for polarity, vector in (("pos", tuple(positive)), ("neg", tuple(negative))):
            records.append(
                LatentRepresentationRecord(
                    sample_id=f"ortho-{family}-{polarity}",
                    vector=vector,
                    family=family,
                    domain=family,
                    jurisdiction="us-federal",
                    length_bin="medium",
                    length=80.0,
                    duplicate_group=f"ortho-{family}",
                    split="development",
                    ood=False,
                    success=True,
                    confidence=0.7,
                    semantic_class=family,
                )
            )
    return tuple(records)


def synthetic_false_neighborhood_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Two families occupying one neighborhood, proving similarity is not equivalence."""

    records: list[LatentRepresentationRecord] = []
    for index, family in enumerate(("deontic", "tdfol", "deontic", "tdfol")):
        records.append(
            LatentRepresentationRecord(
                sample_id=f"neighbor-{family}-{index}",
                vector=(1.0, 0.01 * index, 0.0),
                family=family,
                domain="mixed",
                jurisdiction="us-federal",
                length_bin="short",
                length=15.0,
                duplicate_group=f"neighbor-{index}",
                split="calibration",
                success=family == "deontic",
                confidence=0.55,
                semantic_class=family,
            )
        )
    return tuple(records)


def synthetic_unknown_denominator_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Single unlabeled vector so rank and calibration denominators stay unknown."""

    return (
        LatentRepresentationRecord(
            sample_id="unknown-only",
            vector=(0.0, 0.0, 0.0),
            family="",
            split="development",
            success=None,
            confidence=None,
            latent_used=False,
        ),
    )


GOLDEN_COLLAPSE_METRIC_VECTOR: Final[Mapping[str, float]] = {
    "dimension": 3.0,
    "effective_rank": 1.0,
    "participation_ratio": 1.0,
    "sample_count": 4.0,
    "singular_value_0": round(math.sqrt(5.0), 12),
    "singular_value_1": 0.0,
    "singular_value_2": 0.0,
    "spectral_anisotropy": 1.0,
}
GOLDEN_ORTHOGONAL_METRIC_VECTOR: Final[Mapping[str, float]] = {
    "dimension": 3.0,
    "effective_rank": 3.0,
    "participation_ratio": 3.0,
    "sample_count": 6.0,
    "singular_value_0": round(math.sqrt(2.0), 12),
    "singular_value_1": round(math.sqrt(2.0), 12),
    "singular_value_2": round(math.sqrt(2.0), 12),
    "spectral_anisotropy": round(1.0 / 3.0, 12),
}
GOLDEN_ANISOTROPY_METRIC_VECTOR: Final[Mapping[str, float]] = {
    "dimension": 2.0,
    "effective_rank": 1.016935639849,
    "sample_count": 4.0,
    "singular_value_0": 2.237860410146,
    "singular_value_1": 0.109456770926,
    "spectral_anisotropy": 0.997613389502,
}
GOLDEN_CALIBRATION_METRIC_VECTOR: Final[Mapping[str, float]] = {
    "brier_score": 0.01,
    "expected_calibration_error": 0.1,
    "failure_conditioned_confidence": 0.1,
    "success_conditioned_confidence": 0.9,
}


def synthetic_calibration_fixture() -> tuple[LatentRepresentationRecord, ...]:
    """Five confident successes and five unconfident failures (ECE 0.1, Brier 0.01)."""

    records: list[LatentRepresentationRecord] = []
    for index in range(5):
        records.append(
            LatentRepresentationRecord(
                sample_id=f"cal-success-{index}",
                vector=(1.0, 0.0),
                family="deontic",
                split="calibration",
                success=True,
                confidence=0.9,
            )
        )
        records.append(
            LatentRepresentationRecord(
                sample_id=f"cal-failure-{index}",
                vector=(0.0, 1.0),
                family="tdfol",
                split="calibration",
                success=False,
                confidence=0.1,
            )
        )
    return tuple(records)


__all__ = [
    "COUNTEREXAMPLE_EQUIVALENCE",
    "DECOMPILER_ROUND_TRIP_PRESERVATION",
    "DEFAULT_FALSE_NEIGHBORHOOD_K",
    "GOLDEN_ANISOTROPY_METRIC_VECTOR",
    "GOLDEN_CALIBRATION_METRIC_VECTOR",
    "GOLDEN_COLLAPSE_METRIC_VECTOR",
    "GOLDEN_ORTHOGONAL_METRIC_VECTOR",
    "GRAPH_ISOMORPHISM",
    "LEGAL_IR_LATENT_DIAGNOSTICS_SCHEMA_VERSION",
    "LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION",
    "FalseNeighborhoodReport",
    "LatentDiagnosticsReport",
    "LatentRepresentationRecord",
    "LatentSpectrumReport",
    "OBLIGATION_EQUIVALENCE",
    "PROOF_OBLIGATION_DELTA",
    "PROOF_OBLIGATION_DELTA_SCORE",
    "SEMANTIC_EQUIVALENCE_METRICS",
    "STRUCTURAL_EQUIVALENCE",
    "TEMPORAL_WINDOW_AGREEMENT",
    "SemanticEquivalenceComparisonReport",
    "SemanticEquivalenceConfig",
    "SemanticEquivalenceFamilyComparison",
    "SemanticEquivalenceFamilyResult",
    "coerce_latent_records",
    "compare_legal_ir_semantic_equivalence",
    "evaluate_latent_diagnostics",
    "evaluate_legal_ir_semantic_equivalence",
    "semantic_equivalence_from_metrics",
    "semantic_equivalence_promotion_gate",
    "synthetic_anisotropy_fixture",
    "synthetic_calibration_fixture",
    "synthetic_collapse_fixture",
    "synthetic_false_neighborhood_fixture",
    "synthetic_memorization_fixture",
    "synthetic_orthogonal_fixture",
    "synthetic_unknown_denominator_fixture",
]
