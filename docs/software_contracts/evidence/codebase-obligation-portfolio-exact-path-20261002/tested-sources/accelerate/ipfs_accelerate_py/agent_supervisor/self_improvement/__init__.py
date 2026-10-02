"""Self-improvement package for agent_supervisor (ASREF).

Owns epoch contracts, successor refill, rollout/benchmark surfaces, and
supervisor v2 efficiency/state models. Higher packages may depend on
``self_improvement``; ``self_improvement`` must not form cycles with
``todo_daemon`` or ``integrations``.

Modules owned by bundle ``asref/self-improvement`` live under this package
(see ``docs/architecture/asref/move_map.json``).
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "SELF_IMPROVEMENT_LANDED_MODULES",
    "SELF_IMPROVEMENT_PACKAGE_NAME",
    "SELF_IMPROVEMENT_OWNED_MODULES",
    "SELF_IMPROVEMENT_FORBIDDEN_DEPENDENTS",
)

SELF_IMPROVEMENT_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.self_improvement"

# Stems owned by asref/self-improvement in docs/architecture/asref/move_map.json.
SELF_IMPROVEMENT_OWNED_MODULES: Final[tuple[str, ...]] = (
    "campaign_refill_policy",
    "self_improvement",
    "self_improvement_completion",
    "self_improvement_rollout",
    "self_improvement_v2",
    "self_improvement_v2_rollout",
    "supervisor_efficiency_metrics",
    "supervisor_state_model",
    "supervisor_token_ledger",
    "supervisor_v2_benchmark",
    "supervisor_v2_contracts",
)

SELF_IMPROVEMENT_LANDED_MODULES: Final[tuple[str, ...]] = SELF_IMPROVEMENT_OWNED_MODULES

# Packages that must not be imported by self_improvement (DAG / cycle guard).
SELF_IMPROVEMENT_FORBIDDEN_DEPENDENTS: Final[tuple[str, ...]] = (
    "todo_daemon",
    "integrations",
)
