"""Domain-neutral versioned Logic Tactician (``ipfs_datasets_py.logic.tactician@1``).

Public surface:

* :mod:`.models` — versioned goals, sources, routes, subgoals, policy, plans
* :mod:`.policy` — defaults and pure ordering helpers
* :mod:`.planner` — :class:`LogicTactician` deterministic planner
* :mod:`.receipts` — content-addressed plan receipts
* :mod:`.adapters` — domain adapters (legal ProofTactician compatibility)

Exports resolve lazily so package import stays free of optional domain
dependencies and never eagerly imports legal processors or network clients.
"""

from __future__ import annotations

import importlib
from typing import Any, Final

_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "models": (
        "TACTICIAN_INTERFACE",
        "SCHEMA_VERSION",
        "SUPPORTED_SCHEMA_VERSIONS",
        "TacticianError",
        "TacticianValidationError",
        "RouteDisposition",
        "StopDisposition",
        "TacticianGoal",
        "TacticianSource",
        "TacticianRoute",
        "TacticianSubgoal",
        "TacticianPolicy",
        "TacticianPlan",
        "canonical_json_bytes",
        "compute_content_digest",
        "detect_cycle",
    ),
    "policy": (
        "DETERMINISTIC_PLANNER_ID",
        "DEFAULT_POLICY_ID",
        "default_policy",
        "policy_content_id",
        "order_sources",
        "partition_by_denial",
        "truncate_query_hints",
    ),
    "planner": (
        "SourceRanker",
        "GuidanceConfig",
        "PlannerError",
        "LogicTactician",
    ),
    "receipts": (
        "ReceiptError",
        "TacticianReceipt",
    ),
    "adapters": (
        "DomainAdapterError",
        "sources_from_proof_search_plan",
        "goal_from_proof_search_plan",
        "adapt_proof_tactician_plan",
    ),
}

__all__ = sorted({name for names in _EXPORTS.values() for name in names})

_NAME_TO_MODULE: Final[dict[str, str]] = {
    name: module for module, names in _EXPORTS.items() for name in names
}


def __getattr__(name: str) -> Any:
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
