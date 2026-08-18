"""E1 metric catalog for the deterministic compiler/decompiler baseline.

Interface: ``IRDeterministicE1Metrics@1``

PGIR-023 measures parser/type acceptance, exact, canonical, AST, graph,
source-span, semantic, proof, unsupported, and latency separately for the
compiler and the decompiler.  A missing, inapplicable, or unmeasured metric
is reported with an explicit status and reason.  It is never coerced to zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    CanonicalRule,
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir


IR_DETERMINISTIC_E1_METRICS_INTERFACE: Final = "IRDeterministicE1Metrics@1"
IR_DETERMINISTIC_E1_METRICS_SCHEMA: Final = (
    "ipfs-datasets.ir-learning.evaluations.deterministic.e1-metrics.v1"
)

E1_METRIC_IDS: Final[tuple[str, ...]] = (
    "parser_acceptance",
    "type_acceptance",
    "exact",
    "canonical",
    "ast",
    "graph",
    "source_span",
    "semantic",
    "proof",
    "unsupported",
    "latency",
)

E1_SURFACES: Final[tuple[str, ...]] = ("compiler", "decompiler")

METRIC_STATUS_MEASURED: Final = "measured"
METRIC_STATUS_UNSUPPORTED: Final = "unsupported"
METRIC_STATUS_UNKNOWN: Final = "unknown"
METRIC_STATUS_NOT_APPLICABLE: Final = "not_applicable"
METRIC_STATUS_NOT_MEASURED: Final = "not_measured"

UNMEASURED_STATUSES: Final = frozenset(
    {
        METRIC_STATUS_UNSUPPORTED,
        METRIC_STATUS_UNKNOWN,
        METRIC_STATUS_NOT_APPLICABLE,
        METRIC_STATUS_NOT_MEASURED,
    }
)

HIGHER_IS_BETTER: Final[Mapping[str, bool | None]] = MappingProxyType(
    {
        "parser_acceptance": True,
        "type_acceptance": True,
        "exact": True,
        "canonical": True,
        "ast": True,
        "graph": True,
        "source_span": True,
        "semantic": True,
        "proof": True,
        "unsupported": None,
        "latency": False,
    }
)

E1_METRIC_CATALOG: Final[tuple[Mapping[str, object], ...]] = (
    MappingProxyType(
        {
            "metric_id": "parser_acceptance",
            "description": (
                "Share of attempted cases whose parser/component produced a "
                "nonempty typed artifact without a parse or empty-output failure."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "type_acceptance",
            "description": (
                "Share of attempted cases whose output validated as the measured "
                "canonical IR (compiler) or whose reconstruction recompiled to a "
                "typed IR (decompiler)."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "exact",
            "description": (
                "Exact rule-list equality after the measured canonical sort. "
                "Compiler compares gold vs L1; decompiler compares L1 vs L2."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "canonical",
            "description": (
                "Canonical IR CID equality on the measured payload. Distinct "
                "from exact only when a non-canonical encoding is retained."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "ast",
            "description": (
                "Shape-only AST agreement: rule count, modality node types, and "
                "facet arities, ignoring atom strings."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "graph",
            "description": (
                "Labeled actor/action/object/qualifier edge-set agreement for "
                "the seven-facet rule graph."
            ),
            "unit": "cases",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "source_span",
            "description": (
                "Share of nonempty rule fields grounded by a valid half-open "
                "source-map span inside the source text. Source-withheld "
                "decompilation has no span channel."
            ),
            "unit": "fields",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "semantic",
            "description": (
                "Mean weighted assignment semantic score from the frozen "
                "round-trip metric. Not a substitute for proof or exact match."
            ),
            "unit": "score",
            "value_kind": "mean",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "proof",
            "description": (
                "Independent formal-proof replay on paired obligations. "
                "Reported unsupported unless a checked proof trace exists."
            ),
            "unit": "obligations",
            "value_kind": "rate",
            "higher_is_better": True,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "unsupported",
            "description": (
                "Disclosed unsupported-construct count per attempted case. "
                "This is a disclosure tally, not a quality score, and absence "
                "of a disclosure channel is not recorded as zero."
            ),
            "unit": "disclosures",
            "value_kind": "mean",
            "higher_is_better": None,
            "missing_as_zero": False,
        }
    ),
    MappingProxyType(
        {
            "metric_id": "latency",
            "description": "Wall-clock seconds for one isolated surface call.",
            "unit": "seconds",
            "value_kind": "mean",
            "higher_is_better": False,
            "missing_as_zero": False,
        }
    ),
)


def e1_metric_catalog() -> list[dict[str, object]]:
    """Return a detached copy of the frozen E1 catalog."""

    return [dict(item) for item in E1_METRIC_CATALOG]


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{field} must be a finite number")
    return number


def _nonneg_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field} must be a nonnegative integer")
    return value


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One E1 cell. Unmeasured cells keep ``value`` unset."""

    metric_id: str
    surface: str
    status: str
    denominator: int
    numerator: int | None = None
    value: float | None = None
    unit: str = "cases"
    reason: str | None = None
    detail: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.metric_id not in E1_METRIC_IDS:
            raise ContractError(f"unknown E1 metric_id {self.metric_id!r}")
        if self.surface not in E1_SURFACES:
            raise ContractError(f"unknown E1 surface {self.surface!r}")
        if self.status == METRIC_STATUS_MEASURED:
            if self.denominator <= 0:
                raise ContractError(
                    f"{self.surface}.{self.metric_id} measured denominator must be positive"
                )
            if self.value is None:
                raise ContractError(
                    f"{self.surface}.{self.metric_id} measured value must be present"
                )
            object.__setattr__(self, "value", _finite_number(self.value, "value"))
            if self.numerator is not None:
                object.__setattr__(
                    self, "numerator", _nonneg_int(self.numerator, "numerator")
                )
            if self.reason is not None:
                raise ContractError(
                    f"{self.surface}.{self.metric_id} measured metric cannot carry a reason"
                )
        else:
            if self.status not in UNMEASURED_STATUSES:
                raise ContractError(f"unknown metric status {self.status!r}")
            if self.value is not None:
                raise ContractError(
                    f"{self.surface}.{self.metric_id} {self.status} value must be null; "
                    "missing metrics are never reported as zero"
                )
            if self.numerator is not None:
                raise ContractError(
                    f"{self.surface}.{self.metric_id} {self.status} numerator must be null"
                )
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ContractError(
                    f"{self.surface}.{self.metric_id} {self.status} reason is required"
                )
            object.__setattr__(self, "denominator", _nonneg_int(self.denominator, "denominator"))
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ContractError("unit must be a nonblank string")
        if not isinstance(self.detail, Mapping):
            raise ContractError("detail must be an object")
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "metric_id": self.metric_id,
            "surface": self.surface,
            "status": self.status,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "unit": self.unit,
            "reason": self.reason,
            "missing_as_zero": False,
        }
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


def measured_rate(
    metric_id: str,
    surface: str,
    *,
    numerator: int,
    denominator: int,
    unit: str = "cases",
    detail: Mapping[str, object] | None = None,
) -> MetricObservation:
    """Build a measured rate with an explicit denominator."""

    if denominator <= 0:
        raise ContractError(f"{surface}.{metric_id} measured rate requires a positive denominator")
    if numerator > denominator:
        raise ContractError(
            f"{surface}.{metric_id} numerator {numerator} exceeds denominator {denominator}"
        )
    return MetricObservation(
        metric_id=metric_id,
        surface=surface,
        status=METRIC_STATUS_MEASURED,
        numerator=_nonneg_int(numerator, "numerator"),
        denominator=denominator,
        value=float(numerator) / float(denominator),
        unit=unit,
        detail={} if detail is None else detail,
    )


def measured_mean(
    metric_id: str,
    surface: str,
    values: Sequence[float],
    *,
    unit: str,
    numerator: int | None = None,
    extra_aggregates: Mapping[str, object] | None = None,
) -> MetricObservation:
    """Build a measured mean. An empty sample is not recorded as zero."""

    if not values:
        raise ContractError(f"{surface}.{metric_id} measured mean requires at least one sample")
    finite = [_finite_number(item, "values[]") for item in values]
    ordered = sorted(finite)
    count = len(finite)
    total = math.fsum(finite)
    mean = total / count
    detail: dict[str, object] = {
        "count": count,
        "sum": total,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean,
        "p50": _quantile(ordered, 0.50),
        "p95": _quantile(ordered, 0.95),
    }
    if extra_aggregates:
        detail.update(dict(extra_aggregates))
    return MetricObservation(
        metric_id=metric_id,
        surface=surface,
        status=METRIC_STATUS_MEASURED,
        numerator=numerator,
        denominator=count,
        value=mean,
        unit=unit,
        detail=detail,
    )


def unmeasured(
    metric_id: str,
    surface: str,
    status: str,
    reason: str,
    *,
    denominator: int = 0,
    unit: str = "cases",
    detail: Mapping[str, object] | None = None,
) -> MetricObservation:
    """Build an explicit unsupported/unknown/not-measured cell."""

    return MetricObservation(
        metric_id=metric_id,
        surface=surface,
        status=status,
        denominator=denominator,
        unit=unit,
        reason=reason,
        detail={} if detail is None else detail,
    )


def _quantile(ordered: Sequence[float], probability: float) -> float:
    if len(ordered) == 1:
        return float(ordered[0])
    rank = probability * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def ir_ast_signature(ir: CanonicalRuleIR) -> tuple[object, ...]:
    """Return the shape-only AST of a canonical IR."""

    return tuple(
        (
            "rule",
            rule.modality,
            ("object", 1 if rule.object else 0),
            ("conditions", len(rule.conditions)),
            ("exceptions", len(rule.exceptions)),
            ("temporal", len(rule.temporal)),
        )
        for rule in ir.rules
    )


def ir_graph_edges(ir: CanonicalRuleIR) -> frozenset[tuple[str, ...]]:
    """Return the labeled seven-facet rule graph."""

    edges: set[tuple[str, ...]] = set()
    for index, rule in enumerate(ir.rules):
        rule_id = f"rule:{index}:{rule.modality}"
        edges.add(("actor", rule.actor, "has_modality", rule.modality, rule_id))
        edges.add((rule_id, "performs", "action", rule.action))
        if rule.object:
            edges.add((rule.action, "object", rule.object, rule_id))
        for field in LIST_FIELDS:
            for atom in getattr(rule, field):
                edges.add((rule_id, field, atom))
    return frozenset(edges)


def expected_grounded_fields(rule: CanonicalRule) -> tuple[str, ...]:
    """Return field paths that a source map should ground for one rule."""

    fields = ["modality", "actor", "action"]
    if rule.object:
        fields.append("object")
    for field in LIST_FIELDS:
        if getattr(rule, field):
            fields.append(field)
    return tuple(fields)


def compare_structural_views(
    reference: CanonicalRuleIR,
    candidate: CanonicalRuleIR,
) -> dict[str, object]:
    """Compare exact, canonical, AST, graph, and semantic views."""

    semantic = compare_semantic_ir(reference, candidate)
    reference_cid = semantic_ir_cid(reference)
    candidate_cid = semantic_ir_cid(candidate)
    return {
        "exact": list(reference.rules) == list(candidate.rules),
        "canonical": reference_cid == candidate_cid,
        "ast": ir_ast_signature(reference) == ir_ast_signature(candidate),
        "graph": ir_graph_edges(reference) == ir_graph_edges(candidate),
        "semantic_score": semantic["semantic_score"],
        "semantic_loss": semantic["semantic_loss"],
        "exact_ir": semantic["exact_ir"],
        "reference_rule_count": semantic["reference_rule_count"],
        "candidate_rule_count": semantic["candidate_rule_count"],
        "reference_cid": reference_cid,
        "candidate_cid": candidate_cid,
        "reference_ast": list(ir_ast_signature(reference)),
        "candidate_graph_edge_count": len(ir_graph_edges(candidate)),
        "reference_graph_edge_count": len(ir_graph_edges(reference)),
    }


def semantic_ir_cid(ir: CanonicalRuleIR) -> str:
    """Return the dag-json CID of the measured canonical IR payload."""

    from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json

    return cid_for_dag_json(ir.to_dict())


def require_complete_e1_surface(
    observations: Iterable[MetricObservation],
    surface: str,
) -> tuple[MetricObservation, ...]:
    """Fail closed unless every E1 metric is present exactly once."""

    by_id = {item.metric_id: item for item in observations}
    missing = [metric_id for metric_id in E1_METRIC_IDS if metric_id not in by_id]
    extra = sorted(set(by_id) - set(E1_METRIC_IDS))
    if missing or extra:
        raise ContractError(
            f"{surface} E1 set mismatch; missing={missing!r} extra={extra!r}"
        )
    for metric_id, item in by_id.items():
        if item.surface != surface:
            raise ContractError(f"{metric_id} is bound to {item.surface}, not {surface}")
    return tuple(by_id[metric_id] for metric_id in E1_METRIC_IDS)


__all__ = [
    "E1_METRIC_CATALOG",
    "E1_METRIC_IDS",
    "E1_SURFACES",
    "HIGHER_IS_BETTER",
    "IR_DETERMINISTIC_E1_METRICS_INTERFACE",
    "IR_DETERMINISTIC_E1_METRICS_SCHEMA",
    "METRIC_STATUS_MEASURED",
    "METRIC_STATUS_NOT_APPLICABLE",
    "METRIC_STATUS_NOT_MEASURED",
    "METRIC_STATUS_UNKNOWN",
    "METRIC_STATUS_UNSUPPORTED",
    "MetricObservation",
    "UNMEASURED_STATUSES",
    "compare_structural_views",
    "e1_metric_catalog",
    "expected_grounded_fields",
    "ir_ast_signature",
    "ir_graph_edges",
    "measured_mean",
    "measured_rate",
    "require_complete_e1_surface",
    "semantic_ir_cid",
    "unmeasured",
]
