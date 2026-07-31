"""Deterministic, domain-neutral Logic Tactician planner.

The planner:

* orders caller-provided sources under an explicit :class:`TacticianPolicy`;
* records selected and excluded routes with rationales and proof-gap focus;
* emits a finite acyclic subgoal decomposition;
* records stop/abstain conditions;
* performs **no** proof, write, or network work; and
* is byte-stable on replay for identical inputs.

Optional learned/LLM guidance may only reorder or nominate under a pinned
model digest. Any guidance failure falls back to the deterministic baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import (
    RouteDisposition,
    StopDisposition,
    TacticianError,
    TacticianGoal,
    TacticianPlan,
    TacticianPolicy,
    TacticianRoute,
    TacticianSource,
    TacticianSubgoal,
    TacticianValidationError,
    compute_content_digest,
)
from .policy import (
    DETERMINISTIC_PLANNER_ID,
    default_policy,
    order_sources,
    partition_by_denial,
    truncate_query_hints,
)

#: Type of an optional learned/LLM ranker. Receives ordered source ids and
#: returns a permutation of the same ids. Must be pure for byte-stable plans.
SourceRanker = Callable[[Sequence[str], Mapping[str, Any]], Sequence[str]]


class PlannerError(TacticianError):
    """Raised when planning inputs are inconsistent or unsafe."""


@dataclass(frozen=True)
class GuidanceConfig:
    """Optional pinned guidance that may only reorder or nominate.

    Attributes:
        learned_ranker: Pure callable that reorders admitted source ids.
        learned_model_digest: Pinned digest required when ranking is enabled.
        llm_nominator: Pure callable returning additional opaque source ids to
            nominate (already present in the candidate set only).
        llm_model_digest: Pinned digest required when nomination is enabled.
    """

    learned_ranker: Optional[SourceRanker] = None
    learned_model_digest: str = ""
    llm_nominator: Optional[SourceRanker] = None
    llm_model_digest: str = ""


class LogicTactician:
    """Domain-neutral proof-search planner.

    Instances are pure with respect to planning: they hold no mutable network
    clients, proof engines, or write handles.
    """

    def __init__(self, *, planner_id: str = DETERMINISTIC_PLANNER_ID) -> None:
        if not isinstance(planner_id, str) or not planner_id.strip():
            raise PlannerError("planner_id must be a non-empty string")
        self.planner_id = planner_id.strip()

    def plan(
        self,
        goal: TacticianGoal,
        sources: Sequence[TacticianSource],
        policy: Optional[TacticianPolicy] = None,
        *,
        guidance: Optional[GuidanceConfig] = None,
        nominated_subgoal_deps: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> TacticianPlan:
        """Build a finite, content-addressed :class:`TacticianPlan`.

        Args:
            goal: Validated goal with exact opaque roots.
            sources: Caller-provided source candidates (domain-supplied).
            policy: Explicit planning policy; defaults to the closed baseline.
            guidance: Optional pinned learned/LLM reorder/nominate helpers.
            nominated_subgoal_deps: Optional dependency edges among gap-derived
                subgoals (opaque gap id -> dependency gap ids). Cycles are
                rejected and produce abstention rather than an invalid plan.
        """

        if not isinstance(goal, TacticianGoal):
            raise PlannerError("goal must be a TacticianGoal")
        goal.validate()
        active_policy = policy if policy is not None else default_policy()
        if not isinstance(active_policy, TacticianPolicy):
            raise PlannerError("policy must be a TacticianPolicy")
        active_policy.validate()

        # Exact root binding: policy/config identity must match goal binding.
        policy_digest = compute_content_digest(active_policy.to_dict())
        if goal.config_root not in {active_policy.policy_id, policy_digest}:
            # Allow either the human policy_id or its content digest as the
            # config root binding, so callers can pin either form.
            raise PlannerError(
                "goal.config_root must equal policy_id or the policy content digest"
            )

        validated_sources = self._validate_sources(sources, active_policy)
        admitted, denied = partition_by_denial(validated_sources, active_policy)
        admitted = truncate_query_hints(
            admitted, max_hints=active_policy.max_query_hints_per_source
        )

        learned_applied = False
        learned_digest = ""
        llm_applied = False
        llm_digest = ""

        ordered = list(admitted)
        if guidance is not None and active_policy.allow_learned_ranking:
            ordered, learned_applied, learned_digest = self._apply_learned_ranking(
                ordered, active_policy, guidance
            )
        if guidance is not None and active_policy.allow_llm_nomination:
            ordered, llm_applied, llm_digest = self._apply_llm_nomination(
                ordered, admitted, active_policy, guidance
            )

        selected, excluded_budget = self._select_routes(
            ordered, goal, active_policy
        )
        excluded = list(excluded_budget)
        for source in denied:
            excluded.append(
                TacticianRoute(
                    route_id=f"route:excluded:{source.source_id}",
                    source_id=source.source_id,
                    source_class=source.source_class,
                    stage_index=len(selected) + len(excluded),
                    disposition=RouteDisposition.EXCLUDED,
                    rationale=(
                        f"Source class {source.source_class!r} is denied by policy"
                    ),
                    addresses_gaps=[],
                )
            )

        # Sources truncated by max_sources after selection budget.
        admitted_ids = {route.source_id for route in selected}
        admitted_ids.update(route.source_id for route in excluded)
        for source in ordered:
            if source.source_id in admitted_ids:
                continue
            excluded.append(
                TacticianRoute(
                    route_id=f"route:excluded:{source.source_id}",
                    source_id=source.source_id,
                    source_class=source.source_class,
                    stage_index=len(selected) + len(excluded),
                    disposition=RouteDisposition.EXCLUDED,
                    rationale="Excluded after max_sources/max_routes budget",
                    addresses_gaps=[],
                )
            )
            admitted_ids.add(source.source_id)

        subgoals, stop_disposition = self._decompose_subgoals(
            goal, active_policy, nominated_subgoal_deps or {}
        )

        if not selected and goal.proof_gaps:
            stop_disposition = StopDisposition.ABSTAIN
        elif not selected:
            stop_disposition = StopDisposition.NO_ADMISSIBLE_SOURCES
        elif stop_disposition is StopDisposition.CONTINUE:
            if len(selected) >= active_policy.max_routes:
                stop_disposition = StopDisposition.BUDGET_EXHAUSTED
            elif not goal.proof_gaps:
                stop_disposition = StopDisposition.GAPS_CLOSED

        plan = TacticianPlan.build(
            goal_id=goal.goal_id,
            goal_root=goal.goal_root,
            corpus_root=goal.corpus_root,
            config_root=goal.config_root,
            authority_roots=goal.authority_roots,
            policy_id=active_policy.policy_id,
            planner_id=self.planner_id,
            selected_routes=selected,
            excluded_routes=excluded,
            proof_gaps=goal.proof_gaps,
            subgoals=subgoals,
            stop_conditions=active_policy.stop_conditions,
            abstain_conditions=active_policy.abstain_conditions,
            stop_disposition=stop_disposition,
            learned_guidance_applied=learned_applied,
            learned_model_digest=learned_digest,
            llm_guidance_applied=llm_applied,
            llm_model_digest=llm_digest,
        )
        return plan

    def _validate_sources(
        self,
        sources: Sequence[TacticianSource],
        policy: TacticianPolicy,
    ) -> List[TacticianSource]:
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            raise PlannerError("sources must be a sequence of TacticianSource")
        if len(sources) > policy.max_sources * 4:
            # Hard reject unbounded candidate floods rather than silently drop.
            raise PlannerError(
                f"sources length {len(sources)} exceeds hard admission bound "
                f"{policy.max_sources * 4}"
            )
        validated: List[TacticianSource] = []
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, TacticianSource):
                raise PlannerError("sources must contain only TacticianSource")
            source.validate()
            if source.source_id in seen:
                raise TacticianValidationError(
                    f"duplicate source identity {source.source_id!r}"
                )
            seen.add(source.source_id)
            validated.append(source)
        return validated

    def _apply_learned_ranking(
        self,
        ordered: Sequence[TacticianSource],
        policy: TacticianPolicy,
        guidance: GuidanceConfig,
    ) -> Tuple[List[TacticianSource], bool, str]:
        pinned = (guidance.learned_model_digest or policy.learned_model_digest).strip()
        if not pinned or pinned != policy.learned_model_digest:
            # Deterministic fallback: pinned identity mismatch or missing digest.
            return list(ordered), False, ""
        if guidance.learned_ranker is None:
            return list(ordered), False, ""
        try:
            source_ids = [source.source_id for source in ordered]
            ranked_ids = list(
                guidance.learned_ranker(
                    source_ids,
                    {
                        "model_digest": pinned,
                        "policy_id": policy.policy_id,
                    },
                )
            )
            if sorted(ranked_ids) != sorted(source_ids):
                # Must be a pure reorder of the admitted set.
                return list(ordered), False, ""
            by_id = {source.source_id: source for source in ordered}
            return [by_id[source_id] for source_id in ranked_ids], True, pinned
        except Exception:
            return list(ordered), False, ""

    def _apply_llm_nomination(
        self,
        ordered: Sequence[TacticianSource],
        admitted: Sequence[TacticianSource],
        policy: TacticianPolicy,
        guidance: GuidanceConfig,
    ) -> Tuple[List[TacticianSource], bool, str]:
        pinned = (guidance.llm_model_digest or policy.llm_model_digest).strip()
        if not pinned or pinned != policy.llm_model_digest:
            return list(ordered), False, ""
        if guidance.llm_nominator is None:
            return list(ordered), False, ""
        try:
            source_ids = [source.source_id for source in ordered]
            nominated = list(
                guidance.llm_nominator(
                    source_ids,
                    {
                        "model_digest": pinned,
                        "policy_id": policy.policy_id,
                    },
                )
            )
            admitted_ids = {source.source_id for source in admitted}
            # Nomination may only prioritize already-admitted sources.
            preferred = [
                source_id for source_id in nominated if source_id in admitted_ids
            ]
            if not preferred:
                return list(ordered), False, ""
            by_id = {source.source_id: source for source in ordered}
            rest = [source_id for source_id in source_ids if source_id not in preferred]
            new_order = preferred + rest
            # Deduplicate while preserving order.
            seen: set[str] = set()
            final_ids: List[str] = []
            for source_id in new_order:
                if source_id in seen:
                    continue
                seen.add(source_id)
                final_ids.append(source_id)
            return [by_id[source_id] for source_id in final_ids], True, pinned
        except Exception:
            return list(ordered), False, ""

    def _select_routes(
        self,
        ordered: Sequence[TacticianSource],
        goal: TacticianGoal,
        policy: TacticianPolicy,
    ) -> Tuple[List[TacticianRoute], List[TacticianRoute]]:
        selected: List[TacticianRoute] = []
        excluded: List[TacticianRoute] = []
        gaps = list(goal.proof_gaps)
        for index, source in enumerate(ordered):
            if len(selected) >= min(policy.max_sources, policy.max_routes):
                excluded.append(
                    TacticianRoute(
                        route_id=f"route:excluded:{source.source_id}",
                        source_id=source.source_id,
                        source_class=source.source_class,
                        stage_index=index,
                        disposition=RouteDisposition.EXCLUDED,
                        rationale="Excluded after selection budget",
                        addresses_gaps=[],
                    )
                )
                continue
            addresses = gaps[:1] if gaps else []
            selected.append(
                TacticianRoute(
                    route_id=f"route:selected:{source.source_id}",
                    source_id=source.source_id,
                    source_class=source.source_class,
                    stage_index=len(selected),
                    disposition=RouteDisposition.SELECTED,
                    rationale=source.rationale,
                    addresses_gaps=addresses,
                )
            )
        return selected, excluded

    def _decompose_subgoals(
        self,
        goal: TacticianGoal,
        policy: TacticianPolicy,
        nominated_deps: Mapping[str, Sequence[str]],
    ) -> Tuple[List[TacticianSubgoal], StopDisposition]:
        gaps = list(goal.proof_gaps)[: policy.max_subgoals]
        if not gaps:
            return [], StopDisposition.GAPS_CLOSED

        subgoals: List[TacticianSubgoal] = []
        for index, gap in enumerate(gaps):
            raw_deps = list(nominated_deps.get(gap, ()))
            # Only allow dependencies among the emitted subgoal gap set.
            depends_on = [
                f"subgoal:{dep}"
                for dep in raw_deps
                if dep in gaps and dep != gap
            ]
            # Deterministic default chain: each gap after the first depends on
            # the previous gap subgoal when no nomination is supplied.
            if not depends_on and index > 0 and gap not in nominated_deps:
                depends_on = [f"subgoal:{gaps[index - 1]}"]
            subgoals.append(
                TacticianSubgoal(
                    subgoal_id=f"subgoal:{gap}",
                    parent_goal_id=goal.goal_id,
                    statement_ref=f"{goal.statement_ref}#gap:{gap}",
                    depends_on=depends_on,
                    addresses_gaps=[gap],
                    rationale=f"Cover proof gap {gap}",
                )
            )

        # Cycle detection is enforced by TacticianPlan.validate; surface
        # abstention early for clearer stop disposition.
        from .models import detect_cycle

        graph = {sg.subgoal_id: list(sg.depends_on) for sg in subgoals}
        if detect_cycle(graph) is not None:
            return [], StopDisposition.CYCLE_DETECTED

        if len(goal.proof_gaps) > policy.max_subgoals:
            return subgoals, StopDisposition.BUDGET_EXHAUSTED
        return subgoals, StopDisposition.CONTINUE


__all__ = [
    "SourceRanker",
    "GuidanceConfig",
    "PlannerError",
    "LogicTactician",
    "DETERMINISTIC_PLANNER_ID",
]
