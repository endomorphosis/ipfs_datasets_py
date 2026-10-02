"""Merge package for agent_supervisor (ASREF).

Owns merge queue, train, checkpoint, conflict repair, checkout lock, and
lane lease surfaces. Higher packages may depend on ``merge``; ``merge``
must not form cycles with ``todo_daemon``, ``self_improvement``, or
``integrations``.

Modules owned by bundle ``asref/merge`` (see
``docs/architecture/asref/move_map.json``) move into this package via
``git mv`` without long-lived re-export stubs at the former flat paths.

First-batch modules are dual-copied under this package (flat originals
remain until ASREF-G090 cutover). Prefer package imports for landed
modules; remaining owned stems still live at flat paths until child
batches land. Import landed modules via::

    from ipfs_accelerate_py.agent_supervisor.merge.<module> import ...

Post-move console entry point (pyproject / setup) retargets to::

    ipfs_accelerate_py.agent_supervisor.merge.merge_resolver:main
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "MERGE_LANDED_MODULES",
    "MERGE_PACKAGE_NAME",
    "MERGE_OWNED_MODULES",
    "MERGE_FORBIDDEN_DEPENDENTS",
    "MERGE_ENTRY_POINT_TARGETS",
)

MERGE_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.merge"

# Stems owned by asref/merge in docs/architecture/asref/move_map.json.
MERGE_OWNED_MODULES: Final[tuple[str, ...]] = (
    "campaign_leases",
    "checkout_lock",
    "git_gc",
    "lease_coordination",
    "leased_lane",
    "merge_checkpoint",
    "merge_conflict_repair",
    "merge_queue",
    "merge_resolver",
    "merge_train",
    "promotion_pointer",
)

# Dual-copied under this package in the current ASREF-011 batch.
MERGE_LANDED_MODULES: Final[tuple[str, ...]] = (
    "merge_resolver",
    "checkout_lock",
    "merge_checkpoint",
    "git_gc",
    "merge_conflict_repair",
)

# Packages that must not be imported by merge (DAG / cycle guard).
MERGE_FORBIDDEN_DEPENDENTS: Final[tuple[str, ...]] = (
    "todo_daemon",
    "self_improvement",
    "integrations",
)

# Intended post-move entry-point module targets (ASREF-G070).
MERGE_ENTRY_POINT_TARGETS: Final[tuple[str, ...]] = (
    "ipfs_accelerate_py.agent_supervisor.merge.merge_resolver:main",
)
