"""Specify width classes and named controls without measuring them.

Historical 8D variants, active native vectors, and detached disabled-latent
components stay distinct. Correct, zero, branch-disabled, permuted,
source-only, and retrieval controls are named and stay unexecuted.
Mean-coordinate MSE is not semantic superiority. This module records no
preprocessing budget, no cost, no producer call, and no encoder call.
"""

from __future__ import annotations

SCHEMA = "legal-width-control-specification/v1"
WIDTH_CLASSES = (
    "historical_8d",
    "active_native",
    "detached_disabled_latent",
)
CONTROL_NAMES = (
    "correct",
    "zero",
    "branch_disabled",
    "permuted",
    "source_only",
    "retrieval",
)
WIDTH_CONTROL_BOUNDARY = """Historical 8D variants, active native vectors and detached disabled-latent components remain distinct.
Correct, zero, branch-disabled and permuted inputs plus source-only and retrieval controls stay named and unexecuted.
Mean-coordinate MSE is not semantic superiority.
No control was executed and no mean-coordinate MSE was measured.
"""


class WidthControlSpecificationError(ValueError):
    """A width class was merged, a control ran, or MSE was treated as meaning."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise WidthControlSpecificationError(message)


def specify_width_controls(
    width_classes: tuple[str, ...] | list[str],
    control_names: tuple[str, ...] | list[str],
    mean_coordinate_mse: object = None,
    *,
    controls_executed: bool = False,
) -> dict[str, object]:
    """Return the named specification, or refuse a merge, a run, or an MSE."""

    _need(
        type(width_classes) in (tuple, list)
        and tuple(width_classes) == WIDTH_CLASSES,
        "width classes remain distinct",
    )
    _need(
        type(control_names) in (tuple, list)
        and tuple(control_names) == CONTROL_NAMES,
        "controls are not explicit",
    )
    _need(
        mean_coordinate_mse is None,
        "mean-coordinate MSE is not semantic superiority",
    )
    _need(controls_executed is False, "controls stay unexecuted")
    return {
        "schema": SCHEMA,
        "width_classes": list(WIDTH_CLASSES),
        "width_classes_distinct": True,
        "historical_8d_distinct": True,
        "active_native_distinct": True,
        "detached_disabled_latent_distinct": True,
        "control_names": list(CONTROL_NAMES),
        "controls_explicit": True,
        "controls_executed": False,
        "mean_coordinate_mse_is_semantic_superiority": False,
        "mean_coordinate_mse_measured": False,
        "producer_called": False,
        "encoder_called": False,
        "preprocessing_specified": False,
        "budgets_recorded": False,
        "cost_measured": False,
        "training_executed": False,
        "model_executed": False,
        "worker_launched": False,
        "encoder_unfrozen": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
