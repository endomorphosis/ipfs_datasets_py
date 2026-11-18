"""Compare two modality arms without selecting a hypothesis.

Initialization, source cases, trainable mask, optimizer, candidates, and
budget must be identical. The named permission veto and the recorded
complete-rule loss-ID veto are preserved. An E1 engineering ranking is a
separate list and cannot consume either veto. This module does not train,
select a modality hypothesis, or accept law.
"""
from __future__ import annotations

SCHEMA = "legal-modality-causal-comparison/v1"
FACTORS = (
    "initialization",
    "source_cases",
    "trainable_mask",
    "optimizer",
    "candidates",
    "budget",
)
PERMISSION_VETOES = ("32 tracked permission modality decisions",)
COMPLETE_RULE_LOSS_ID_VETOES = ("native-tuning-calendula-t4-q5-p",)


class CausalComparisonError(ValueError):
    """A causal comparison dropped a factor, a veto, or selected a hypothesis."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise CausalComparisonError(message)


def _names(value: object, label: str) -> tuple[str, ...]:
    _need(type(value) in (tuple, list) and 1 <= len(value) <= 32, label + " required")
    names = tuple(value)
    _need(
        all(type(item) is str and item.strip() == item and bool(item) for item in names),
        label + " required",
    )
    _need(len(set(names)) == len(names), label + " required")
    return names


def _arm(value: object) -> dict[str, str]:
    _need(type(value) is dict and set(value) == set(FACTORS), "closed causal arm required")
    arm: dict[str, str] = {}
    for factor in FACTORS:
        item = value[factor]
        _need(type(item) is str and item.strip() == item and bool(item), "closed causal arm required")
        arm[factor] = item
    return arm


def compare_causal_arms(
    control: dict[str, str],
    candidate: dict[str, str],
    permission_vetoes: tuple[str, ...] | list[str],
    complete_rule_loss_id_vetoes: tuple[str, ...] | list[str],
    e1_ranking: list[str],
) -> dict[str, object]:
    """Return one comparison that keeps the vetoes and selects nothing.

    ``e1_ranking`` is stored separately. A ranking entry that repeats a veto
    name is refused. Differing factors are refused.
    """

    left = _arm(control)
    right = _arm(candidate)
    _need(left == right, "causal comparison factors differ")
    permissions = _names(permission_vetoes, "named permission vetoes")
    loss_ids = _names(complete_rule_loss_id_vetoes, "complete-rule loss-ID vetoes")
    _need(permissions == PERMISSION_VETOES, "named permission vetoes were not preserved")
    _need(loss_ids == COMPLETE_RULE_LOSS_ID_VETOES, "complete-rule loss-ID vetoes were not preserved")
    _need(type(e1_ranking) is list and len(e1_ranking) <= 32, "E1 engineering ranking required")
    ranking = tuple(e1_ranking)
    _need(
        all(type(item) is str and item.strip() == item and bool(item) for item in ranking),
        "E1 engineering ranking required",
    )
    vetoes = set(permissions) | set(loss_ids)
    _need(not vetoes.intersection(ranking), "E1 engineering ranking consumes a veto")
    return {
        "schema": SCHEMA,
        "factors": list(FACTORS),
        "initialization_identical": True,
        "source_cases_identical": True,
        "trainable_mask_identical": True,
        "optimizer_identical": True,
        "candidates_identical": True,
        "budget_identical": True,
        "permission_vetoes": list(permissions),
        "complete_rule_loss_id_vetoes": list(loss_ids),
        "e1_engineering_ranking": list(ranking),
        "e1_engineering_ranking_tracked_separately": True,
        "e1_ranking_selects_hypothesis": False,
        "hypothesis_selected": False,
        "training_executed": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
        "proof_authority": False,
        "source_semantics_verified": False,
    }
