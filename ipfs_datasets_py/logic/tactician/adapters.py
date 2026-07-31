"""Domain adapters that project external Tactician-like plans into the generic
``logic.tactician@1`` models.

The legal :class:`~ipfs_datasets_py.processors.legal_data.proof_tactician.ProofTactician`
remains a domain implementation. This module adapts its outputs without
importing legal source-class names into the generic model module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .models import (
    TacticianGoal,
    TacticianPlan,
    TacticianPolicy,
    TacticianSource,
    TacticianValidationError,
)
from .planner import LogicTactician
from .policy import default_policy
from .receipts import TacticianReceipt


class DomainAdapterError(TacticianValidationError):
    """Raised when a domain adapter cannot project into generic models."""


def _as_str(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainAdapterError(f"{field_name} must be a non-empty string")
    return text


def sources_from_proof_search_plan(
    plan_dict: Mapping[str, Any],
    *,
    source_root_prefix: str = "legal",
) -> List[TacticianSource]:
    """Project ProofTactician candidate sources into generic sources.

    Legal source types remain opaque strings on :class:`TacticianSource`; they
    are never imported as enumerations into the generic models package.
    """

    candidates = list(plan_dict.get("candidate_sources") or [])
    sources: List[TacticianSource] = []
    for index, raw in enumerate(candidates):
        if hasattr(raw, "to_dict"):
            item = raw.to_dict()
        elif isinstance(raw, Mapping):
            item = dict(raw)
        else:
            raise DomainAdapterError(
                "candidate_sources entries must be mappings or to_dict objects"
            )
        source_id = _as_str(item.get("source_id"), field_name="source_id")
        source_type = _as_str(
            item.get("source_type") or item.get("source_class"),
            field_name="source_type",
        )
        precedence = int(item.get("priority", item.get("precedence", index + 1)))
        rationale = _as_str(
            item.get("rationale") or f"Adapted legal source {source_type}",
            field_name="rationale",
        )
        query_hints = [
            str(hint).strip()
            for hint in list(item.get("query_hints") or [])
            if str(hint).strip()
        ]
        metadata = dict(item.get("metadata") or {})
        # Never promote legal metadata authority flags.
        for key in (
            "semantic_authority",
            "expectation_authority",
            "proof_authority",
            "write_authority",
            "authoritative",
        ):
            metadata.pop(key, None)
        sources.append(
            TacticianSource(
                source_id=source_id,
                source_class=source_type,
                precedence=max(0, precedence),
                rationale=rationale,
                query_hints=query_hints,
                source_root=f"{source_root_prefix}:{source_id}",
                metadata=metadata,
            )
        )
    return sources


def goal_from_proof_search_plan(
    plan_dict: Mapping[str, Any],
    *,
    corpus_root: str,
    config_root: str,
    authority_roots: Optional[Mapping[str, str]] = None,
) -> TacticianGoal:
    """Build a generic goal from a ProofTactician plan dictionary."""

    plan_id = _as_str(plan_dict.get("plan_id"), field_name="plan_id")
    work_item_id = _as_str(
        plan_dict.get("work_item_id") or plan_id, field_name="work_item_id"
    )
    objective = _as_str(plan_dict.get("objective") or "legal-proof", field_name="objective")
    gaps = [
        str(gap).strip()
        for gap in list(plan_dict.get("proof_gap_focus") or [])
        if str(gap).strip()
    ]
    return TacticianGoal(
        goal_id=f"legal-goal:{work_item_id}",
        statement_ref=f"legal-objective:{plan_id}",
        goal_family="legal_proof_search",
        goal_root=f"legal-goal-root:{work_item_id}",
        corpus_root=corpus_root,
        config_root=config_root,
        authority_roots=dict(authority_roots or {}),
        proof_gaps=gaps,
        assumptions=[],
        metadata={
            "party": str(plan_dict.get("party") or ""),
            "objective": objective,
            "adapter": "ProofTactician",
        },
    )


def adapt_proof_tactician_plan(
    plan: Any,
    *,
    corpus_root: str,
    policy: Optional[TacticianPolicy] = None,
    authority_roots: Optional[Mapping[str, str]] = None,
    tactician: Optional[LogicTactician] = None,
) -> TacticianReceipt:
    """Adapt a ProofTactician :class:`ProofSearchPlan` into a generic receipt.

    The legal planner remains responsible for legal source discovery. This
    adapter only projects already-built plan data through the generic
    deterministic planner so legal categories never become generic semantics.
    """

    if hasattr(plan, "to_dict"):
        plan_dict: Dict[str, Any] = plan.to_dict()
    elif isinstance(plan, Mapping):
        plan_dict = dict(plan)
    else:
        raise DomainAdapterError(
            "plan must be a ProofSearchPlan-like object or mapping"
        )

    active_policy = policy if policy is not None else default_policy(
        policy_id="logic.tactician.policy.legal-adapter@1",
        source_class_order=[
            # Order is caller-supplied opaque strings from the legal plan's
            # recommended route; fall back to an empty policy order when absent.
        ],
    )
    # Prefer the legal plan's recommended route as source_class_order when
    # the policy did not specify one.
    if not active_policy.source_class_order:
        recommended = [
            str(item).strip()
            for item in list(plan_dict.get("recommended_route") or [])
            if str(item).strip()
        ]
        # Deduplicate while preserving order.
        seen: set[str] = set()
        ordered_classes: List[str] = []
        for item in recommended:
            if item in seen:
                continue
            seen.add(item)
            ordered_classes.append(item)
        if ordered_classes:
            active_policy = TacticianPolicy.from_dict(
                {
                    **active_policy.to_dict(),
                    "source_class_order": ordered_classes,
                }
            )

    config_root = active_policy.policy_id
    goal = goal_from_proof_search_plan(
        plan_dict,
        corpus_root=corpus_root,
        config_root=config_root,
        authority_roots=authority_roots,
    )
    sources = sources_from_proof_search_plan(plan_dict)
    planner = tactician or LogicTactician()
    generic_plan = planner.plan(goal, sources, active_policy)
    return TacticianReceipt.from_plan(generic_plan, active_policy)


__all__ = [
    "DomainAdapterError",
    "sources_from_proof_search_plan",
    "goal_from_proof_search_plan",
    "adapt_proof_tactician_plan",
]
