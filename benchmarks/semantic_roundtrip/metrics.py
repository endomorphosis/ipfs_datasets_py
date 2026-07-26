"""Exact structural metrics for the canonical semantic round-trip IR."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .contracts import (
    LIST_FIELDS,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ContractError,
    FailureReason,
    RoundTripResult,
)


RULE_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "modality": 0.25,
        "actor": 0.15,
        "action": 0.20,
        "object": 0.10,
        "conditions": 0.10,
        "exceptions": 0.10,
        "temporal": 0.10,
    }
)


@dataclass(frozen=True, slots=True)
class RoundTripLosses:
    """The three protocol losses for one scheduled coordinate."""

    forward: float
    cycle: float
    end_to_end: float

    def __post_init__(self) -> None:
        for field in ("forward", "cycle", "end_to_end"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ContractError(
                    f"{field} must be a finite number from zero to one"
                )
            object.__setattr__(self, field, float(value))

    @property
    def primary(self) -> float:
        return self.end_to_end

    @property
    def forward_loss(self) -> float:
        return self.forward

    @property
    def cycle_loss(self) -> float:
        return self.cycle

    @property
    def end_to_end_loss(self) -> float:
        return self.end_to_end


def _coerce_ir(value: CanonicalRuleIR | Mapping[str, object]) -> CanonicalRuleIR:
    if isinstance(value, CanonicalRuleIR):
        return value
    return CanonicalRuleIR.from_dict(value)


def _set_score(left: Sequence[str], right: Sequence[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def rule_similarity(
    left: CanonicalRule | Mapping[str, object],
    right: CanonicalRule | Mapping[str, object],
) -> float:
    """Return the frozen weighted structural similarity for two rules."""

    left_rule = (
        left if isinstance(left, CanonicalRule) else CanonicalRule.from_dict(left)
    )
    right_rule = (
        right
        if isinstance(right, CanonicalRule)
        else CanonicalRule.from_dict(right)
    )
    score = 0.0
    for field, weight in RULE_WEIGHTS.items():
        if field in LIST_FIELDS:
            part = _set_score(
                getattr(left_rule, field), getattr(right_rule, field)
            )
        else:
            part = float(
                getattr(left_rule, field) == getattr(right_rule, field)
            )
        score += weight * part
    return round(score, 9)


def maximum_weight_assignment(
    weights: Sequence[Sequence[float]],
) -> list[tuple[int, int]]:
    """Return an exact maximum-weight one-to-one rectangular assignment.

    This is the same Hungarian implementation used by the preliminary pilot.
    It intentionally avoids a greedy matcher, which can select a locally
    attractive pair while lowering the total structural score.
    """

    if not weights:
        return []
    if not weights[0]:
        if any(row for row in weights):
            raise ContractError("assignment matrix must be rectangular")
        return []
    row_count = len(weights)
    column_count = len(weights[0])
    if any(len(row) != column_count for row in weights):
        raise ContractError("assignment matrix must be rectangular")

    def finite_weight(value: object, row: int, column: int) -> float:
        if isinstance(value, bool):
            raise ContractError(
                f"assignment weight [{row}][{column}] must be finite"
            )
        try:
            converted = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractError(
                f"assignment weight [{row}][{column}] must be finite"
            ) from exc
        if not math.isfinite(converted):
            raise ContractError(
                f"assignment weight [{row}][{column}] must be finite"
            )
        return converted

    validated = [
        [
            finite_weight(value, row_index, column_index)
            for column_index, value in enumerate(row)
        ]
        for row_index, row in enumerate(weights)
    ]
    transposed = row_count > column_count
    matrix = (
        [
            [validated[row][column] for row in range(row_count)]
            for column in range(column_count)
        ]
        if transposed
        else validated
    )
    n = len(matrix)
    m = len(matrix[0])
    potentials_rows = [0.0] * (n + 1)
    potentials_columns = [0.0] * (m + 1)
    matched_row = [0] * (m + 1)
    predecessor = [0] * (m + 1)

    for row in range(1, n + 1):
        matched_row[0] = row
        column0 = 0
        minimum = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[column0] = True
            current_row = matched_row[column0]
            delta = float("inf")
            next_column = 0
            for column in range(1, m + 1):
                if used[column]:
                    continue
                reduced = (
                    -matrix[current_row - 1][column - 1]
                    - potentials_rows[current_row]
                    - potentials_columns[column]
                )
                if reduced < minimum[column]:
                    minimum[column] = reduced
                    predecessor[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    next_column = column
            for column in range(m + 1):
                if used[column]:
                    potentials_rows[matched_row[column]] += delta
                    potentials_columns[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = next_column
            if matched_row[column0] == 0:
                break
        while True:
            previous = predecessor[column0]
            matched_row[column0] = matched_row[previous]
            column0 = previous
            if column0 == 0:
                break

    assignment: list[tuple[int, int]] = []
    for column in range(1, m + 1):
        if matched_row[column] == 0:
            continue
        row_index = matched_row[column] - 1
        column_index = column - 1
        assignment.append(
            (column_index, row_index)
            if transposed
            else (row_index, column_index)
        )
    return sorted(assignment)


def compare_semantic_ir(
    reference: CanonicalRuleIR | Mapping[str, object],
    candidate: CanonicalRuleIR | Mapping[str, object],
) -> dict[str, object]:
    """Compare two IRs with the pilot's weighted exact-assignment score."""

    left = list(_coerce_ir(reference).rules)
    right = list(_coerce_ir(candidate).rules)
    weights = [
        [rule_similarity(left_rule, right_rule) for right_rule in right]
        for left_rule in left
    ]
    pairs = [
        (weights[left_index][right_index], left_index, right_index)
        for left_index, right_index in maximum_weight_assignment(weights)
    ]
    matches: list[dict[str, object]] = []
    for score, left_index, right_index in sorted(
        pairs, key=lambda item: (item[1], item[2])
    ):
        left_rule = left[left_index]
        right_rule = right[right_index]
        matches.append(
            {
                "reference_index": left_index,
                "candidate_index": right_index,
                "score": score,
                "exact": left_rule == right_rule,
                "modality_preserved": (
                    left_rule.modality == right_rule.modality
                ),
                "condition_preserved": (
                    set(left_rule.conditions) == set(right_rule.conditions)
                ),
                "exception_preserved": (
                    set(left_rule.exceptions) == set(right_rule.exceptions)
                ),
                "temporal_preserved": (
                    set(left_rule.temporal) == set(right_rule.temporal)
                ),
            }
        )

    denominator = max(len(left), len(right), 1)
    semantic_score = (
        sum(float(item["score"]) for item in matches) / denominator
    )
    exact_count = sum(bool(item["exact"]) for item in matches)
    exact_precision = exact_count / len(right) if right else 0.0
    exact_recall = exact_count / len(left) if left else 0.0
    exact_f1 = (
        2 * exact_precision * exact_recall / (exact_precision + exact_recall)
        if exact_precision + exact_recall
        else 0.0
    )
    nonvacuous = bool(left) and bool(right)
    return {
        "reference_rule_count": len(left),
        "candidate_rule_count": len(right),
        "matched_rule_count": len(matches),
        "semantic_score": round(semantic_score, 9),
        "semantic_loss": round(1.0 - semantic_score, 9),
        "exact_rule_f1": round(exact_f1, 9),
        "exact_ir": left == right,
        "nonvacuous": nonvacuous,
        "exact_ir_nonvacuous": bool(nonvacuous and left == right),
        "missing_rule_count": max(0, len(left) - len(matches)),
        "extra_rule_count": max(0, len(right) - len(matches)),
        "matches": matches,
        "facet_survival": {
            field: round(
                (
                    sum(
                        bool(
                            item[
                                f"{field[:-1] if field.endswith('s') else field}"
                                "_preserved"
                            ]
                        )
                        for item in matches
                    )
                    / len(matches)
                )
                if matches
                else 0.0,
                9,
            )
            for field in ("modality", "conditions", "exceptions", "temporal")
        },
    }


def semantic_score(
    reference: CanonicalRuleIR | Mapping[str, object],
    candidate: CanonicalRuleIR | Mapping[str, object],
) -> float:
    """Return only the weighted exact-assignment score."""

    return float(compare_semantic_ir(reference, candidate)["semantic_score"])


def round_trip_losses(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    l1: CanonicalRuleIR | Mapping[str, object] | None,
    reconstruction: str | None,
    l2: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    failed: bool = False,
) -> RoundTripLosses:
    """Compute separate forward, cycle, and end-to-end losses.

    Any terminal failure, missing artifact, empty IR, or blank reconstruction
    is fail-closed and receives one for all three losses.
    """

    if (
        failed
        or l1 is None
        or l2 is None
        or not isinstance(reconstruction, str)
    ):
        return RoundTripLosses(1.0, 1.0, 1.0)
    try:
        first = _coerce_ir(l1)
        second = _coerce_ir(l2)
    except (ContractError, TypeError, ValueError):
        return RoundTripLosses(1.0, 1.0, 1.0)
    if first.is_empty or second.is_empty or not reconstruction.strip():
        return RoundTripLosses(1.0, 1.0, 1.0)
    gold = _coerce_ir(gold_ir)
    return RoundTripLosses(
        forward=round(1.0 - semantic_score(gold, first), 9),
        cycle=round(1.0 - semantic_score(first, second), 9),
        end_to_end=round(1.0 - semantic_score(gold, second), 9),
    )


def make_round_trip_result(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    l1: CanonicalRuleIR | Mapping[str, object] | None,
    reconstruction: str | None,
    l2: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    failure_reason: FailureReason | None = None,
    failure_detail: str | None = None,
) -> RoundTripResult:
    """Bind artifacts and their loss-one failure policy into one result."""

    inferred_reason = failure_reason
    try:
        first = _coerce_ir(l1) if l1 is not None else None
    except (ContractError, TypeError, ValueError):
        first = None
        inferred_reason = inferred_reason or FailureReason.INVALID_OUTPUT
    try:
        second = _coerce_ir(l2) if l2 is not None else None
    except (ContractError, TypeError, ValueError):
        second = None
        inferred_reason = inferred_reason or FailureReason.INVALID_OUTPUT
    if reconstruction is not None and not isinstance(reconstruction, str):
        reconstruction = None
        inferred_reason = inferred_reason or FailureReason.INVALID_OUTPUT
    if inferred_reason is None:
        if first is None or second is None or reconstruction is None:
            inferred_reason = FailureReason.MISSING_OUTPUT
        elif first.is_empty:
            inferred_reason = FailureReason.EMPTY_L1
        elif not reconstruction.strip():
            inferred_reason = FailureReason.BLANK_T1
        elif second.is_empty:
            inferred_reason = FailureReason.EMPTY_L2
    failed = inferred_reason is not None
    losses = round_trip_losses(
        gold_ir, first, reconstruction, second, failed=failed
    )
    status = ComponentStatus.FAILED if failed else ComponentStatus.SUCCESS
    return RoundTripResult(
        status=status,
        l1=first,
        reconstruction=reconstruction,
        l2=second,
        forward_loss=losses.forward,
        cycle_loss=losses.cycle,
        end_to_end_loss=losses.end_to_end,
        failure_reason=inferred_reason,
        failure_detail=failure_detail,
    )


__all__ = [
    "RULE_WEIGHTS",
    "RoundTripLosses",
    "rule_similarity",
    "maximum_weight_assignment",
    "compare_semantic_ir",
    "semantic_score",
    "round_trip_losses",
    "make_round_trip_result",
]
