"""Deterministic planning policy helpers for the domain-neutral Logic Tactician.

Policy objects themselves live in :mod:`.models` as versioned records. This
module supplies defaults, pure ordering helpers, and closed capability
invariants without importing domain-specific source classes into the generic
models.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from .models import TacticianPolicy, TacticianSource, compute_content_digest

#: Stable planner identity for the deterministic baseline implementation.
DETERMINISTIC_PLANNER_ID = "logic.tactician.deterministic@1"

#: Default policy identity for the closed, no-network, no-write baseline.
DEFAULT_POLICY_ID = "logic.tactician.policy.default@1"


def default_policy(
    *,
    policy_id: str = DEFAULT_POLICY_ID,
    source_class_order: Sequence[str] | None = None,
    **overrides: object,
) -> TacticianPolicy:
    """Return a validated baseline policy with closed capability flags.

    ``source_class_order`` is entirely caller-provided. The package does not
    invent domain source classes; an empty order means sources sort only by
    their own ``precedence`` then stable ``source_id``.
    """

    payload = {
        "policy_id": policy_id,
        "source_class_order": list(source_class_order or ()),
        "max_sources": 32,
        "max_routes": 32,
        "max_subgoals": 16,
        "max_query_hints_per_source": 16,
        "max_refinement_rounds": 4,
        "allow_learned_ranking": False,
        "allow_llm_nomination": False,
        "learned_model_digest": "",
        "llm_model_digest": "",
        "denied_source_classes": [],
        "network_allowed": False,
        "write_allowed": False,
        "proof_execution_allowed": False,
        "semantic_authority": False,
    }
    payload.update(overrides)
    return TacticianPolicy.from_dict(payload)


def policy_content_id(policy: TacticianPolicy) -> str:
    """Return a content digest over the validated policy body."""

    return compute_content_digest(policy.to_dict())


def order_sources(
    sources: Sequence[TacticianSource],
    policy: TacticianPolicy,
) -> List[TacticianSource]:
    """Order sources under explicit policy without dropping any candidate.

    Sort key (ascending):
    1. policy source-class rank (unknown classes after ordered classes);
    2. caller-provided ``precedence``;
    3. stable ``source_id``.
    """

    policy.validate()
    ordered = sorted(
        sources,
        key=lambda source: (
            policy.source_class_rank(source.source_class),
            source.precedence,
            source.source_id,
        ),
    )
    return list(ordered)


def partition_by_denial(
    sources: Sequence[TacticianSource],
    policy: TacticianPolicy,
) -> Tuple[List[TacticianSource], List[TacticianSource]]:
    """Split sources into (admissible, denied-by-policy) lists.

    Ordering of both lists is stable and deterministic.
    """

    denied_classes = set(policy.denied_source_classes)
    admitted: List[TacticianSource] = []
    denied: List[TacticianSource] = []
    for source in order_sources(sources, policy):
        if source.source_class in denied_classes:
            denied.append(source)
        else:
            admitted.append(source)
    return admitted, denied


def truncate_query_hints(
    sources: Iterable[TacticianSource],
    *,
    max_hints: int,
) -> List[TacticianSource]:
    """Return sources with query hints truncated to the policy bound."""

    out: List[TacticianSource] = []
    for source in sources:
        hints = list(source.query_hints)[: max(0, int(max_hints))]
        if hints == list(source.query_hints):
            out.append(source)
            continue
        out.append(
            TacticianSource(
                source_id=source.source_id,
                source_class=source.source_class,
                precedence=source.precedence,
                rationale=source.rationale,
                query_hints=hints,
                source_root=source.source_root,
                metadata=dict(source.metadata),
                schema_version=source.schema_version,
            )
        )
    return out


__all__ = [
    "DETERMINISTIC_PLANNER_ID",
    "DEFAULT_POLICY_ID",
    "default_policy",
    "policy_content_id",
    "order_sources",
    "partition_by_denial",
    "truncate_query_hints",
]
