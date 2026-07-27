"""Stage-local research metrics for semantic round-trip evaluation.

Interface: ``StageMetrics@1``

Research modes may score intermediate stages (for example constructor-only
forward loss and facet survival) without requiring a complete realizer cycle.
**Promotion still requires full gates**: full coverage, source-copy exclusion,
and polarity preservation on the complete round-trip, plus any preregistered
selection policy. Constructor-only scores never authorize production promotion
by themselves.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir


STAGE_METRICS_INTERFACE: Final = "StageMetrics@1"
STAGE_METRICS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-stage-metrics.v1"
)
STAGE_CONSTRUCTOR_ONLY: Final = "constructor_only"

# Documented promotion policy bound into every stage-metric export.
PROMOTION_REQUIRES_FULL_GATES: Final = True
PROMOTION_FULL_GATE_IDS: Final = (
    "full_coverage",
    "source_copy_exclusion",
    "polarity_preservation",
)
PROMOTION_POLICY_NOTE: Final = (
    "Constructor-only and other stage-local metrics are research scores. "
    "Promotion still requires full gates on the complete round-trip "
    "(full_coverage, source_copy_exclusion, polarity_preservation, and "
    "selection_eligible under the preregistered matrix policy). Stage-local "
    "forward loss or facet survival improvements alone never authorize "
    "production promotion."
)

_FACET_NAMES: Final = (
    "modality",
    "conditions",
    "exceptions",
    "temporal",
)


def _coerce_ir(
    value: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    field_name: str,
) -> CanonicalRuleIR | None:
    if value is None:
        return None
    if isinstance(value, CanonicalRuleIR):
        return value
    if isinstance(value, Mapping):
        return CanonicalRuleIR.from_dict(value)
    raise ContractError(f"{field_name} must be CanonicalRuleIR or object")


def _finite_unit_interval(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ContractError(
            f"{field_name} must be a finite number from zero to one"
        )
    return float(value)


@dataclass(frozen=True, slots=True)
class ConstructorOnlyStageMetrics:
    """Forward constructor quality without requiring a complete round-trip.

    Fields mirror the protocol's forward comparison: semantic forward loss and
    modality / conditions / exceptions / temporal survival on the gold→L1
    optimal assignment. ``promotion_requires_full_gates`` is always true.
    """

    stage: str
    forward_loss: float
    modality_survival: float
    conditions_survival: float
    exceptions_survival: float
    temporal_survival: float
    semantic_score: float
    polarity_preserved: bool
    polarity_inversion_count: int
    matched_rule_count: int
    reference_rule_count: int
    candidate_rule_count: int
    evaluated: bool
    promotion_requires_full_gates: bool = True
    promotion_full_gate_ids: tuple[str, ...] = PROMOTION_FULL_GATE_IDS
    promotion_policy_note: str = PROMOTION_POLICY_NOTE

    def __post_init__(self) -> None:
        if self.stage != STAGE_CONSTRUCTOR_ONLY:
            raise ContractError(
                f"stage must be {STAGE_CONSTRUCTOR_ONLY!r}"
            )
        for field in (
            "forward_loss",
            "modality_survival",
            "conditions_survival",
            "exceptions_survival",
            "temporal_survival",
            "semantic_score",
        ):
            object.__setattr__(
                self,
                field,
                _finite_unit_interval(getattr(self, field), field),
            )
        if not isinstance(self.polarity_preserved, bool):
            raise ContractError("polarity_preserved must be a boolean")
        for field in (
            "polarity_inversion_count",
            "matched_rule_count",
            "reference_rule_count",
            "candidate_rule_count",
        ):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ContractError(
                    f"{field} must be a nonnegative integer"
                )
        if not isinstance(self.evaluated, bool):
            raise ContractError("evaluated must be a boolean")
        if self.promotion_requires_full_gates is not True:
            raise ContractError(
                "promotion_requires_full_gates must remain True; "
                "stage metrics never authorize promotion alone"
            )
        if tuple(self.promotion_full_gate_ids) != PROMOTION_FULL_GATE_IDS:
            raise ContractError(
                "promotion_full_gate_ids must match the frozen full-gate set"
            )
        if (
            not isinstance(self.promotion_policy_note, str)
            or not self.promotion_policy_note.strip()
        ):
            raise ContractError("promotion_policy_note must be nonblank")

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": STAGE_METRICS_INTERFACE,
            "schema": STAGE_METRICS_SCHEMA,
            "stage": self.stage,
            "forward_loss": self.forward_loss,
            "modality_survival": self.modality_survival,
            "conditions_survival": self.conditions_survival,
            "exceptions_survival": self.exceptions_survival,
            "temporal_survival": self.temporal_survival,
            "semantic_score": self.semantic_score,
            "polarity_preserved": self.polarity_preserved,
            "polarity_inversion_count": self.polarity_inversion_count,
            "matched_rule_count": self.matched_rule_count,
            "reference_rule_count": self.reference_rule_count,
            "candidate_rule_count": self.candidate_rule_count,
            "evaluated": self.evaluated,
            "promotion_requires_full_gates": self.promotion_requires_full_gates,
            "promotion_full_gate_ids": list(self.promotion_full_gate_ids),
            "promotion_policy_note": self.promotion_policy_note,
        }


def compute_constructor_only_metrics(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    l1: CanonicalRuleIR | Mapping[str, object] | None,
) -> ConstructorOnlyStageMetrics:
    """Score gold→L1 constructor quality for research stage reporting.

    Missing or empty L1 is fail-closed: forward loss is 1.0 and all facet
    survival scores are 0.0. Polarity inversions on the optimal assignment
    set ``polarity_preserved`` to false but still export numeric facets so
    residual inversions remain diagnosable.
    """

    gold = _coerce_ir(gold_ir, field_name="gold_ir")
    if gold is None:
        raise ContractError("gold_ir is required")
    candidate = _coerce_ir(l1, field_name="l1")
    if candidate is None or candidate.is_empty:
        return ConstructorOnlyStageMetrics(
            stage=STAGE_CONSTRUCTOR_ONLY,
            forward_loss=1.0,
            modality_survival=0.0,
            conditions_survival=0.0,
            exceptions_survival=0.0,
            temporal_survival=0.0,
            semantic_score=0.0,
            polarity_preserved=False,
            polarity_inversion_count=0,
            matched_rule_count=0,
            reference_rule_count=len(gold.rules),
            candidate_rule_count=0 if candidate is None else len(candidate.rules),
            evaluated=False,
        )

    comparison = compare_semantic_ir(gold, candidate)
    matches = comparison["matches"]
    assert isinstance(matches, list)
    inversions = [
        match for match in matches if not bool(match["modality_preserved"])
    ]
    facets = comparison["facet_survival"]
    assert isinstance(facets, Mapping)
    semantic_score = float(comparison["semantic_score"])
    return ConstructorOnlyStageMetrics(
        stage=STAGE_CONSTRUCTOR_ONLY,
        forward_loss=round(1.0 - semantic_score, 9),
        modality_survival=float(facets.get("modality", 0.0)),
        conditions_survival=float(facets.get("conditions", 0.0)),
        exceptions_survival=float(facets.get("exceptions", 0.0)),
        temporal_survival=float(facets.get("temporal", 0.0)),
        semantic_score=semantic_score,
        polarity_preserved=not inversions,
        polarity_inversion_count=len(inversions),
        matched_rule_count=int(comparison["matched_rule_count"]),
        reference_rule_count=int(comparison["reference_rule_count"]),
        candidate_rule_count=int(comparison["candidate_rule_count"]),
        evaluated=True,
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def constructor_only_metrics_from_matrix_record(
    record: Mapping[str, object],
    *,
    gold_ir: CanonicalRuleIR | Mapping[str, object] | None = None,
) -> ConstructorOnlyStageMetrics:
    """Export constructor-only stage metrics from a sealed matrix record.

    Prefers the sealed ``diagnostics.semantic_comparisons.forward_gold_to_l1``
    payload when present so research reports can reuse matrix CIDs without
    recomputing assignment. When that comparison is absent, falls back to
    ``artifacts.l1`` plus an explicit ``gold_ir`` argument.

    The export always sets ``promotion_requires_full_gates`` and never treats
    constructor-only survival as selection eligibility.
    """

    if not isinstance(record, Mapping):
        raise ContractError("matrix record must be an object")

    diagnostics = _mapping(record.get("diagnostics"))
    comparisons = _mapping(diagnostics.get("semantic_comparisons"))
    forward = comparisons.get("forward_gold_to_l1")
    if isinstance(forward, Mapping) and forward:
        facets = _mapping(forward.get("facet_survival"))
        matches = forward.get("matches")
        match_list = matches if isinstance(matches, list) else []
        inversions = [
            match
            for match in match_list
            if isinstance(match, Mapping)
            and not bool(match.get("modality_preserved", False))
        ]
        semantic_score = _finite_unit_interval(
            forward.get("semantic_score", 0.0),
            "forward_gold_to_l1.semantic_score",
        )
        # Prefer sealed comparison; optionally reconcile loss from losses.forward.
        losses = _mapping(record.get("losses"))
        if "forward" in losses:
            forward_loss = _finite_unit_interval(
                losses["forward"], "losses.forward"
            )
        else:
            forward_loss = round(1.0 - semantic_score, 9)
        return ConstructorOnlyStageMetrics(
            stage=STAGE_CONSTRUCTOR_ONLY,
            forward_loss=forward_loss,
            modality_survival=float(facets.get("modality", 0.0) or 0.0),
            conditions_survival=float(facets.get("conditions", 0.0) or 0.0),
            exceptions_survival=float(facets.get("exceptions", 0.0) or 0.0),
            temporal_survival=float(facets.get("temporal", 0.0) or 0.0),
            semantic_score=semantic_score,
            polarity_preserved=not inversions,
            polarity_inversion_count=len(inversions),
            matched_rule_count=int(forward.get("matched_rule_count") or 0),
            reference_rule_count=int(
                forward.get("reference_rule_count") or 0
            ),
            candidate_rule_count=int(
                forward.get("candidate_rule_count") or 0
            ),
            evaluated=True,
        )

    artifacts = _mapping(record.get("artifacts"))
    l1_value = artifacts.get("l1")
    if gold_ir is None:
        # Some research exports embed gold under diagnostics.case.gold_ir.
        case_diag = _mapping(diagnostics.get("case"))
        gold_ir = case_diag.get("gold_ir")
    if gold_ir is None:
        raise ContractError(
            "matrix record lacks forward_gold_to_l1 comparison and gold_ir "
            "was not supplied for constructor_only export"
        )
    return compute_constructor_only_metrics(gold_ir, l1_value)


def export_constructor_only_stage_metrics(
    records: Sequence[Mapping[str, object]],
    *,
    gold_ir_by_case: Mapping[str, CanonicalRuleIR | Mapping[str, object]]
    | None = None,
) -> list[dict[str, object]]:
    """Export constructor_only metrics for a sequence of matrix records."""

    if not isinstance(records, Sequence) or isinstance(
        records, (str, bytes, bytearray)
    ):
        raise ContractError("records must be a sequence of matrix records")
    gold_map = gold_ir_by_case or {}
    exported: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ContractError(
                f"records[{index}] must be a matrix record object"
            )
        case_id = record.get("case_id")
        gold = None
        if isinstance(case_id, str) and case_id in gold_map:
            gold = gold_map[case_id]
        metrics = constructor_only_metrics_from_matrix_record(
            record, gold_ir=gold
        )
        payload = metrics.to_dict()
        payload["case_id"] = case_id
        payload["cell_id"] = record.get("cell_id")
        payload["record_cid"] = record.get("record_cid")
        exported.append(payload)
    return exported


__all__ = [
    "PROMOTION_FULL_GATE_IDS",
    "PROMOTION_POLICY_NOTE",
    "PROMOTION_REQUIRES_FULL_GATES",
    "STAGE_CONSTRUCTOR_ONLY",
    "STAGE_METRICS_INTERFACE",
    "STAGE_METRICS_SCHEMA",
    "ConstructorOnlyStageMetrics",
    "compute_constructor_only_metrics",
    "constructor_only_metrics_from_matrix_record",
    "export_constructor_only_stage_metrics",
]
