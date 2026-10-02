"""Closed completion boundary for the supervisor self-improvement root.

The generic goal-completion evaluator intentionally accepts goals with
different producer, child, analyzer, and quorum policies.  ASI-G000 is the
root assurance boundary for the self-improvement program, so its population
and proof policy must not be caller-selectable.  This module validates that
closed contract before delegating the lifecycle transition to the shared
two-phase evaluator.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Final, Mapping, Sequence

from ..objectives.goal_completion import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    GoalCompletionDecision,
    evaluate_goal_completion,
)


SELF_IMPROVEMENT_ROOT_OBJECTIVE_ID: Final = "ASI-G000"
SELF_IMPROVEMENT_ROOT_OBJECTIVE_REVISION: Final = "ASI-G000@asi-082"
SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS: Final = 2
SELF_IMPROVEMENT_ROOT_PRODUCING_TASK_IDS: Final[tuple[str, ...]] = tuple(
    f"ASI-{index:03d}" for index in range(1, 25)
)
SELF_IMPROVEMENT_ROOT_CHILD_GOAL_IDS: Final[tuple[str, ...]] = tuple(
    f"ASI-G{index:03d}" for index in range(10, 100, 10)
)
SELF_IMPROVEMENT_ROOT_ACCEPTANCE_CRITERIA: Final[tuple[str, ...]] = (
    "Every child goal has fresh tree-bound evidence",
    "rollout has zero false completion or authority-boundary violations",
    "Python, CLI, and MCP controls agree",
    "a drained board runs bounded evidence-driven refill rather than stopping "
    "or creating duplicate busywork.",
)

_SUCCESSFUL_TASK_STATES: Final = frozenset(
    {
        "complete",
        "completed",
        "passed",
        "success",
        "succeeded",
        "verified",
        "verified_complete",
    }
)


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _now(value: Any) -> datetime:
    parsed = _datetime(value)
    return parsed if parsed is not None else datetime.now(timezone.utc)


def _implementation_bound(row: Mapping[str, Any]) -> bool:
    for name in (
        "implementation",
        "implementation_binding",
        "changed_files",
        "predicted_files",
        "ast_symbols",
        "interfaces",
    ):
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            return True
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
            and any(str(item or "").strip() for item in value)
        ):
            return True
    return False


def _validation_ids(row: Mapping[str, Any]) -> set[str]:
    raw = row.get(
        "validation_receipt_ids",
        row.get("validation_receipt_id", ()),
    )
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, Sequence):
        return set()
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def _evidence_receipt_ids(
    evidence: Sequence[Any],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for item in evidence:
        value = _payload(item)
        source = value.get("evidence", value)
        source = source if isinstance(source, Mapping) else value
        criterion = _normalized(source.get("acceptance_criterion"))
        receipt_id = str(
            source.get(
                "provenance_cid",
                source.get("receipt_id", source.get("evidence_id", "")),
            )
            or ""
        ).strip()
        if criterion and receipt_id:
            result.setdefault(criterion, set()).add(receipt_id)
    return result


def _fresh(
    value: Any,
    *,
    current: datetime,
    freshness_seconds: float,
    clock_skew_seconds: float,
) -> bool:
    observed = _datetime(value)
    if observed is None:
        return False
    return observed <= current + timedelta(
        seconds=max(0.0, clock_skew_seconds)
    ) and current - observed <= timedelta(seconds=max(0.0, freshness_seconds))


def evaluate_self_improvement_root_completion(
    *,
    repository_id: str,
    repository_tree: str,
    producing_tasks: Sequence[Any] = (),
    child_goals: Sequence[Any] = (),
    current_state: Any = "active",
    evidence: Sequence[Any] = (),
    tasks_complete: bool = False,
    coverage: Any = None,
    analyzer_health: Any = None,
    exhaustion_quorum: Any = None,
    required_exhaustive_receipts: int = (SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS),
    now: Any = None,
    freshness_seconds: float = DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
    analysis_inconclusive: bool = False,
    blocked_reason: str = "",
) -> GoalCompletionDecision:
    """Evaluate the immutable ASI-G000 producer and completion-proof contract.

    A caller cannot narrow the four criteria, the ASI-001..ASI-024 producer
    population, the nine direct workstream children, or the configured
    exhaustive-receipt count.  Operational output is deliberately not accepted
    as standalone analysis authority; criterion validation, analyzer health,
    quorum proof, and descendant proof remain separate inputs.
    """

    if (
        isinstance(required_exhaustive_receipts, bool)
        or not isinstance(required_exhaustive_receipts, int)
        or required_exhaustive_receipts != SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS
    ):
        raise ValueError(
            "required_exhaustive_receipts must equal the configured ASI-G000 "
            f"count {SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS}"
        )
    repository_id = str(repository_id or "").strip()
    repository_tree = str(repository_tree or "").strip()
    current = _now(now)

    task_values = [_payload(item) for item in producing_tasks]
    task_ids = [str(item.get("task_id", item.get("id", "")) or "").strip() for item in task_values]
    producer_population_complete = (
        len(task_ids) == len(set(task_ids))
        and tuple(sorted(task_ids)) == tuple(sorted(SELF_IMPROVEMENT_ROOT_PRODUCING_TASK_IDS))
        and all(
            _normalized(item.get("status", item.get("state", ""))) in _SUCCESSFUL_TASK_STATES
            for item in task_values
        )
    )

    evidence_ids = _evidence_receipt_ids(evidence)
    coverage_value = _payload(coverage)
    rows_value = coverage_value.get("criteria")
    rows = rows_value if isinstance(rows_value, list) else []
    expected_criteria = {_normalized(item) for item in SELF_IMPROVEMENT_ROOT_ACCEPTANCE_CRITERIA}
    row_keys = [
        _normalized(row.get("criterion", row.get("acceptance_criterion", "")))
        for row in rows
        if isinstance(row, Mapping)
    ]
    coverage_bound = (
        len(row_keys) == len(expected_criteria)
        and len(row_keys) == len(set(row_keys))
        and set(row_keys) == expected_criteria
        and all(
            isinstance(row, Mapping)
            and _implementation_bound(row)
            and bool(
                _validation_ids(row).intersection(
                    evidence_ids.get(
                        _normalized(
                            row.get(
                                "criterion",
                                row.get("acceptance_criterion", ""),
                            )
                        ),
                        set(),
                    )
                )
            )
            for row in rows
        )
    )
    if not coverage_bound:
        reasons = coverage_value.get("reason_codes")
        reasons = list(reasons) if isinstance(reasons, (list, tuple)) else []
        coverage_value = {
            **coverage_value,
            "verified": False,
            "reason_codes": list(dict.fromkeys([*reasons, "coverage_validation_receipt_unbound"])),
        }

    expected_binding = {
        "repository_id": repository_id,
        "tree_id": repository_tree,
        "objective_id": SELF_IMPROVEMENT_ROOT_OBJECTIVE_ID,
        "objective_revision": SELF_IMPROVEMENT_ROOT_OBJECTIVE_REVISION,
    }
    health_value = _payload(analyzer_health)
    health_binding_value = health_value.get("binding")
    health_binding = dict(health_binding_value) if isinstance(health_binding_value, Mapping) else {}
    binding_complete = (
        all(health_binding.get(name) == value for name, value in expected_binding.items())
        and all(expected_binding.values())
        and all(
            str(health_binding.get(name) or "").strip()
            for name in ("analyzer_version", "configuration_revision")
        )
    )
    health_valid = (
        _normalized(health_value.get("status")) == "healthy"
        and health_value.get("healthy") is True
        and health_value.get("safe_for_completion_reasoning") is True
        and binding_complete
    )
    if not health_valid:
        health_value = {
            **health_value,
            "healthy": False,
            "safe_for_completion_reasoning": False,
        }

    quorum_value = _payload(exhaustion_quorum)
    members_value = quorum_value.get("members")
    members = members_value if isinstance(members_value, list) else []
    quorum_binding_value = quorum_value.get("binding")
    quorum_binding = dict(quorum_binding_value) if isinstance(quorum_binding_value, Mapping) else {}

    def unique_member_field(name: str) -> bool:
        values = [
            str(member.get(name) or "").strip() for member in members if isinstance(member, Mapping)
        ]
        return len(values) == len(members) and all(values) and len(values) == len(set(values))

    quorum_valid = (
        quorum_value.get("required_members") == SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS
        and quorum_value.get("member_count") == len(members)
        and len(members) >= SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS
        and quorum_value.get("satisfied") is True
        and quorum_binding == health_binding
        and unique_member_field("member_id")
        and unique_member_field("evidence_channel")
        and unique_member_field("receipt_cid")
        and all(
            isinstance(member, Mapping)
            and member.get("healthy") is True
            and member.get("safe_for_completion_reasoning") is True
            and _normalized(member.get("scan_mode")) == "exhaustive"
            and isinstance(member.get("binding"), Mapping)
            and dict(member["binding"]) == health_binding
            for member in members
        )
    )
    if not quorum_valid:
        quorum_value = {
            **quorum_value,
            "satisfied": False,
            "quorum_met": False,
        }

    child_values = [_payload(item) for item in child_goals]
    child_ids = [
        str(item.get("goal_id", item.get("id", "")) or "").strip() for item in child_values
    ]
    child_population_complete = len(child_ids) == len(set(child_ids)) and tuple(
        sorted(child_ids)
    ) == tuple(sorted(SELF_IMPROVEMENT_ROOT_CHILD_GOAL_IDS))
    child_bindings_complete = child_population_complete and all(
        _child_goal_is_current(
            item,
            repository_id=repository_id,
            repository_tree=repository_tree,
            current=current,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
        )
        for item in child_values
    )
    if not child_bindings_complete:
        child_values.append(
            {
                "goal_id": "ASI-G000-required-descendant-population",
                "state": "active",
                "verified": False,
                "completion_gate": {
                    "passed": False,
                    "reason_code": ("required_descendant_population_or_binding_incomplete"),
                },
            }
        )

    return evaluate_goal_completion(
        current_state=current_state,
        acceptance_criteria=SELF_IMPROVEMENT_ROOT_ACCEPTANCE_CRITERIA,
        evidence=evidence,
        tasks_complete=bool(tasks_complete and producer_population_complete),
        repository_tree=repository_tree,
        repository_id=repository_id,
        now=current,
        freshness_seconds=freshness_seconds,
        clock_skew_seconds=clock_skew_seconds,
        coverage=coverage_value,
        analyzer_health=health_value,
        exhaustion_quorum=quorum_value,
        child_goals=child_values,
        analysis_result=None,
        analysis_inconclusive=analysis_inconclusive,
        blocked_reason=blocked_reason,
        require_completion_gate=True,
    )


def _child_goal_is_current(
    child: Mapping[str, Any],
    *,
    repository_id: str,
    repository_tree: str,
    current: datetime,
    freshness_seconds: float,
    clock_skew_seconds: float,
) -> bool:
    gate_value = child.get("completion_gate", child.get("gate"))
    gate = gate_value if isinstance(gate_value, Mapping) else {}
    evaluated_value = gate.get("evaluated_evidence")
    evaluated = evaluated_value if isinstance(evaluated_value, Mapping) else {}
    validations = evaluated.get("validation_evidence")
    proof_requirements = child.get(
        "proof_requirements",
        evaluated.get("proof_requirements", ()),
    )
    if isinstance(proof_requirements, Mapping):
        proof_requirements = (proof_requirements,)
    validation_records_current = (
        isinstance(validations, list)
        and bool(validations)
        and all(
            isinstance(item, Mapping)
            and item.get("valid") is True
            and isinstance(item.get("evidence"), Mapping)
            and item["evidence"].get("repository_tree") == repository_tree
            and item["evidence"].get("repository_id") == repository_id
            for item in validations
        )
    )
    proof_requirements_bound = (
        isinstance(proof_requirements, (list, tuple))
        and bool(proof_requirements)
        and all(
            isinstance(item, Mapping)
            and item.get("repository_tree") == repository_tree
            and str(item.get("provenance_id") or "").strip()
            for item in proof_requirements
        )
    )
    return bool(
        str(child.get("state", child.get("next_state", ""))).strip().lower() == "verified_complete"
        and child.get("verified") is True
        and gate.get("passed") is True
        and evaluated.get("repository_tree") == repository_tree
        and evaluated.get("repository_id") == repository_id
        and _fresh(
            evaluated.get("evaluated_at"),
            current=current,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
        )
        and validation_records_current
        and proof_requirements_bound
    )


__all__ = [
    "SELF_IMPROVEMENT_ROOT_ACCEPTANCE_CRITERIA",
    "SELF_IMPROVEMENT_ROOT_CHILD_GOAL_IDS",
    "SELF_IMPROVEMENT_ROOT_OBJECTIVE_ID",
    "SELF_IMPROVEMENT_ROOT_OBJECTIVE_REVISION",
    "SELF_IMPROVEMENT_ROOT_PRODUCING_TASK_IDS",
    "SELF_IMPROVEMENT_ROOT_REQUIRED_EXHAUSTIVE_RECEIPTS",
    "evaluate_self_improvement_root_completion",
]
