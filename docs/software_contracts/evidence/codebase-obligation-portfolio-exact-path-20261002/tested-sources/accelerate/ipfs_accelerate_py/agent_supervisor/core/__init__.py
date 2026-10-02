"""Shared foundation package for agent_supervisor (ASREF core).

This package is the bottom of the agent_supervisor package DAG. Higher
packages (control, task_sources, context, analysis, proof, and layers above
them) may depend on ``core``; ``core`` must not depend on ``todo_daemon``,
``runtime``, ``merge``, ``rescue``, or ``self_improvement``.

Modules owned by bundle ``asref/core`` (see
``docs/architecture/asref/move_map.json``) live under this package:

* ``conflict_graph``
* ``external_completion``
* ``program_behavior``
* ``submodule_degradation``
* ``wrapper_utils``
* ``multiformats_identity``
* ``asref_layout_evidence``

Import them via::

    from ipfs_accelerate_py.agent_supervisor.core.<module> import ...

Flat package-root copies of these modules have been removed. Prefer
``core.<module>`` for all new code. Historical flat import paths resolve only
through package-root ``AGENT_SUPERVISOR_LANDED_MODULE_TO_PACKAGE`` aliasing.
Do not reintroduce long-lived re-export stubs at the old flat paths.

Package metadata and the public module list are intentional surface area so
importers and tooling can discover the core contract without loading optional
supervisor providers.
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "CORE_PACKAGE_NAME",
    "CORE_OWNED_MODULES",
    "CORE_ALLOWED_DEPENDENTS",
    "CORE_FORBIDDEN_DEPENDENTS",
)

CORE_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.core"

# Stems owned by asref/core in docs/architecture/asref/move_map.json.
CORE_OWNED_MODULES: Final[tuple[str, ...]] = (
    "asref_layout_evidence",
    "conflict_graph",
    "external_completion",
    "multiformats_identity",
    "program_behavior",
    "submodule_degradation",
    "wrapper_utils",
)

# Packages that may import from core (DAG dependents).
CORE_ALLOWED_DEPENDENTS: Final[tuple[str, ...]] = (
    "control",
    "task_sources",
    "context",
    "analysis",
    "proof",
    "objectives",
    "planning",
    "validation",
    "prompt",
    "merge",
    "rescue",
    "runtime",
    "self_improvement",
    "todo_daemon",
    "integrations",
)

# Packages that must not be imported by core (DAG / cycle guard).
CORE_FORBIDDEN_DEPENDENTS: Final[tuple[str, ...]] = (
    "todo_daemon",
    "runtime",
    "merge",
    "rescue",
    "self_improvement",
    "integrations",
)
