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


LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION: Final = (
    "legal-ir-semantic-equivalence-metrics-v1"
)

STRUCTURAL_EQUIVALENCE: Final = "structural_equivalence"
OBLIGATION_EQUIVALENCE: Final = "obligation_equivalence"
COUNTEREXAMPLE_EQUIVALENCE: Final = "counterexample_equivalence"
GRAPH_ISOMORPHISM: Final = "graph_isomorphism"
TEMPORAL_WINDOW_AGREEMENT: Final = "temporal_window_agreement"
DECOMPILER_ROUND_TRIP_PRESERVATION: Final = (
    "decompiler_round_trip_preservation"
)
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
        families = tuple(
            canonical_legal_ir_evaluation_family(family) for family in self.families
        )
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
        return tuple(
            family
            for family, result in self.family_results.items()
            if not result.passed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "block_reasons": list(self.block_reasons),
            "disagreements": list(self.disagreements),
            "failed_families": list(self.failed_families),
            "families": list(self.family_results),
            "family_results": {
                family: result.to_dict()
                for family, result in self.family_results.items()
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
    missing = tuple(
        metric for metric in SEMANTIC_EQUIVALENCE_METRICS if metric not in scores
    )
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
                key: value
                for key, value in threshold_failures.items()
                if key in after.scores
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
        "after": {
            family: result.after.scores for family, result in family_results.items()
        },
        "before": {
            family: result.before.scores for family, result in family_results.items()
        },
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
                name in keys
                for name in ("obligation", "obligations", "duty", "duties")
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
            for match in re.finditer(r"\bwithin\s+\d+\s+(?:day|days|month|months|year|years)\b", item, re.I):
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
        (_normalize_scalar(source_label), _normalize_scalar(relation), _normalize_scalar(target_label))
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
        return {
            item
            for child in value.values()
            for item in _flatten_scalars(child)
        }
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


__all__ = [
    "COUNTEREXAMPLE_EQUIVALENCE",
    "DECOMPILER_ROUND_TRIP_PRESERVATION",
    "GRAPH_ISOMORPHISM",
    "LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION",
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
    "compare_legal_ir_semantic_equivalence",
    "evaluate_legal_ir_semantic_equivalence",
    "semantic_equivalence_from_metrics",
    "semantic_equivalence_promotion_gate",
]
