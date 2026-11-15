"""Audit label tiers without turning a failure or a parse into gold.

Solver and resource statuses stay operational. Reviewed, compiler-weak,
synthetic, and unresolved tiers keep distinct authored masks and origins.
A successful parse keeps both eligibility masks at zero, and Lean
admission stays false. This module runs no solver, builds no Lean
module, scores no federal corpus, and records an authored fixture only.
"""

from __future__ import annotations

SCHEMA = "legal-label-mask-audit/v1"
TIER_NAMES = ("reviewed", "compiler_weak", "synthetic", "unresolved")
RESOURCE_FAILURE_STATUSES = ("budget_exhausted", "cancellation", "error", "timeout")
RESOURCE_MAP_KEYS = (
    "output_limit_without_eos",
    "no_admissible_next_token_within_total_limit",
)
NEGATIVE_LEGAL_LABELS = ("accepted", "illegal", "negative_legal", "rejected_as_law")
STRUCTURAL_OUTCOMES = ("unsupported", "invalid_typed_output", "compared", "accepted")
LABEL_MASK_BOUNDARY = """Solver or resource failure is not a negative legal label.
Reviewed, compiler-weak, synthetic and unresolved tiers keep distinct masks and origins.
Parser or Lean success creates no gold.
"""


class LabelMaskAuditError(ValueError):
    """A tier collided, a resource failure became a legal label, or gold appeared."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise LabelMaskAuditError(message)


def _tiers(value: object) -> dict[str, tuple[int, str]]:
    _need(type(value) is tuple and len(value) == 4, "label tiers stay explicit")
    rows: dict[str, tuple[int, str]] = {}
    for item in value:
        _need(type(item) is tuple and len(item) == 3, "label tiers stay explicit")
        name, mask, origin = item
        _need(type(name) is str and name in TIER_NAMES, "label tiers stay explicit")
        _need(name not in rows, "label tiers stay explicit")
        _need(type(mask) is int and not isinstance(mask, bool) and mask > 0, "label tiers share a mask")
        _need(
            type(origin) is str and origin.strip() == origin and bool(origin),
            "label tier origins stay distinct",
        )
        _need("gold" not in origin and "lean-admitted" not in origin, "parser or Lean success created gold")
        rows[name] = (mask, origin)
    _need(tuple(sorted(rows)) == tuple(sorted(TIER_NAMES)), "label tiers stay explicit")
    masks = [row[0] for row in rows.values()]
    origins = [row[1] for row in rows.values()]
    _need(len(set(masks)) == 4, "label tiers share a mask")
    _need(0 not in masks, "parser or Lean success created gold")
    _need(len(set(origins)) == 4, "label tier origins stay distinct")
    return rows


def audit_label_masks(
    tiers: tuple[tuple[str, int, str], ...],
    *,
    owner_terminal_statuses: tuple[str, ...],
    resource_status_map: dict[str, str],
    parser_success_status: str,
    training_mask: int,
    evaluation_gold_mask: int,
    evaluation_gold_qualified: bool,
    lean_admitted: bool,
    accepted: bool,
) -> dict[str, object]:
    """Record distinct tier masks and a parse that creates no gold.

    A shared mask, a resource status used as a negative legal label, a
    parser status of accepted, or a non-zero gold mask is refused.
    """

    recorded = _tiers(tiers)
    _need(
        type(owner_terminal_statuses) is tuple and owner_terminal_statuses,
        "solver or resource failure is a negative legal label",
    )
    for status in RESOURCE_FAILURE_STATUSES:
        _need(type(status) is str and status in owner_terminal_statuses, "solver or resource failure is a negative legal label")
        _need(status not in NEGATIVE_LEGAL_LABELS, "solver or resource failure is a negative legal label")
        _need(status not in STRUCTURAL_OUTCOMES, "solver or resource failure is a negative legal label")
    _need(type(resource_status_map) is dict, "solver or resource failure is a negative legal label")
    for key in RESOURCE_MAP_KEYS:
        _need(resource_status_map.get(key) == "budget_exhausted", "solver or resource failure is a negative legal label")
    _need(parser_success_status == "valid_without_reference", "parser success created a legal label")
    _need(
        type(training_mask) is int
        and not isinstance(training_mask, bool)
        and type(evaluation_gold_mask) is int
        and not isinstance(evaluation_gold_mask, bool)
        and training_mask == 0
        and evaluation_gold_mask == 0,
        "parser or Lean success created gold",
    )
    _need(evaluation_gold_qualified is False, "parser or Lean success created gold")
    _need(lean_admitted is False, "parser or Lean success created gold")
    _need(accepted is False, "parser success created a legal label")
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "reviewed_mask": recorded["reviewed"][0],
        "reviewed_origin": recorded["reviewed"][1],
        "compiler_weak_mask": recorded["compiler_weak"][0],
        "compiler_weak_origin": recorded["compiler_weak"][1],
        "synthetic_mask": recorded["synthetic"][0],
        "synthetic_origin": recorded["synthetic"][1],
        "unresolved_mask": recorded["unresolved"][0],
        "unresolved_origin": recorded["unresolved"][1],
        "masks_distinct": True,
        "origins_distinct": True,
        "tier_count": 4,
        "reviewed_tier_review_completed": False,
        "resource_failure_statuses": list(RESOURCE_FAILURE_STATUSES),
        "resource_failure_is_negative_legal_label": False,
        "negative_legal_label_count": 0,
        "parser_success_status": "valid_without_reference",
        "gold_created_by_parser_or_lean_success": False,
        "training_mask": 0,
        "evaluation_gold_mask": 0,
        "evaluation_gold_qualified": False,
        "Lean_admitted": False,
        "solver_executed": False,
        "lean_executed": False,
        "resource_failure_executed": False,
        "decoder_executed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
