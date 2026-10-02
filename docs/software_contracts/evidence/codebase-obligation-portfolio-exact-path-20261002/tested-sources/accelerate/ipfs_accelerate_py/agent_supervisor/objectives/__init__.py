"""Objectives and goal-ownership package for agent_supervisor (ASREF).

Owns objective heap, goal tracking, backlog refinery, and bundle
supervisor surfaces. Higher packages may depend on ``objectives``;
``objectives`` must not form cycles with ``todo_daemon``, ``runtime``,
``merge``, ``rescue``, or ``self_improvement``.

Modules owned by bundle ``asref/objectives`` (see
``docs/architecture/asref/move_map.json``) move into this package via
``git mv`` without long-lived re-export stubs at the former flat paths.

First-batch modules are dual-copied under this package (flat originals
remain until ASREF-G090 cutover). Prefer package imports for landed
modules; remaining owned stems still live at flat paths until child
batches land. Import landed modules via::

    from ipfs_accelerate_py.agent_supervisor.objectives.<module> import ...

Post-move console entry points (pyproject / setup) retarget to::

    ipfs_accelerate_py.agent_supervisor.objectives.objective_daemon:main
    ipfs_accelerate_py.agent_supervisor.objectives.backlog_refinery:main
    ipfs_accelerate_py.agent_supervisor.objectives.bundle_supervisor:main
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "OBJECTIVES_LANDED_MODULES",
    "OBJECTIVES_PACKAGE_NAME",
    "OBJECTIVES_OWNED_MODULES",
    "OBJECTIVES_FORBIDDEN_DEPENDENTS",
    "OBJECTIVES_ENTRY_POINT_TARGETS",
)

OBJECTIVES_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.objectives"

# Stems owned by asref/objectives in docs/architecture/asref/move_map.json.
OBJECTIVES_OWNED_MODULES: Final[tuple[str, ...]] = (
    "adaptive_goal_refiner",
    "backlog_refinery",
    "bundle_optimizer",
    "bundle_supervisor",
    "goal_completion",
    "goal_coverage",
    "goal_development_contracts",
    "goal_quality",
    "goal_refinement_verification",
    "expert_iteration_campaign",
    "ir_learning_campaign",
    "ir_learning_campaign_contracts",
    "objective_daemon",
    "objective_graph",
    "objective_task_janitor",
    "objective_tracker",
    "scan_receipts",
)

# Dual-copied under this package in the current ASREF-011 batch.
OBJECTIVES_LANDED_MODULES: Final[tuple[str, ...]] = (
    "objective_graph",
    "objective_daemon",
    "backlog_refinery",
)

# Packages that must not be imported by objectives (DAG / cycle guard).
OBJECTIVES_FORBIDDEN_DEPENDENTS: Final[tuple[str, ...]] = (
    "todo_daemon",
    "runtime",
    "merge",
    "rescue",
    "self_improvement",
    "integrations",
)

# Intended post-move entry-point module targets (ASREF-G070).
OBJECTIVES_ENTRY_POINT_TARGETS: Final[tuple[str, ...]] = (
    "ipfs_accelerate_py.agent_supervisor.objectives.objective_daemon:main",
    "ipfs_accelerate_py.agent_supervisor.objectives.backlog_refinery:main",
    "ipfs_accelerate_py.agent_supervisor.objectives.bundle_supervisor:main",
)
