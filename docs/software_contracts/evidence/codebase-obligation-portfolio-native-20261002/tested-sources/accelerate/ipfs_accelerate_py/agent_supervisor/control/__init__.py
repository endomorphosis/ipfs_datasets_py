"""Control package for agent_supervisor (ASREF control plane).

This package owns the transport-neutral control plane, CLI adapter, contracts,
lifecycle orchestration, execution permits, and authorization policy surface.
It sits above ``core`` in the package DAG and must not depend on
``todo_daemon``, ``self_improvement``, or optional integration providers.

Modules owned by bundle ``asref/control`` (see
``docs/architecture/asref/move_map.json``) live under this package:

* ``authorization_logic``
* ``control_cli``
* ``control_contracts``
* ``control_plane``
* ``execution_permit``
* ``lifecycle_orchestrator``

Import them via::

    from ipfs_accelerate_py.agent_supervisor.control.<module> import ...

During the ASREF layout cutover, temporary flat copies may still exist at the
former root paths until a follow-on import-rewrite pass (outside the narrow
``control/`` edit scope) removes them. Prefer ``control.<module>`` for all new
code. Do not introduce long-lived re-export stubs at the old flat paths.

CLI entry surface: unified ``ipfs-accelerate agent`` registers through
``control_cli.register_agent_cli`` / ``control_cli.run_agent_cli``.
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "CONTROL_PACKAGE_NAME",
    "CONTROL_OWNED_MODULES",
    "CONTROL_ALLOWED_DEPENDENTS",
    "CONTROL_FORBIDDEN_DEPENDENCIES",
    "CONTROL_CLI_ENTRY_TARGETS",
)

CONTROL_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.control"

# Stems owned by asref/control in docs/architecture/asref/move_map.json.
CONTROL_OWNED_MODULES: Final[tuple[str, ...]] = (
    "authorization_logic",
    "campaign_public_api",
    "control_cli",
    "control_contracts",
    "control_plane",
    "execution_permit",
    "launch_profile_housekeeping",
    "lifecycle_orchestrator",
    "promotion_admission",
)

# Packages that may import from control (DAG dependents above this layer).
CONTROL_ALLOWED_DEPENDENTS: Final[tuple[str, ...]] = (
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

# Packages/modules control must not depend on (DAG / cycle guard).
CONTROL_FORBIDDEN_DEPENDENCIES: Final[tuple[str, ...]] = (
    "todo_daemon",
    "self_improvement",
    "integrations",
)

# Intended post-cutover CLI / dispatch targets (ASREF-G030).
CONTROL_CLI_ENTRY_TARGETS: Final[tuple[str, ...]] = (
    "ipfs_accelerate_py.agent_supervisor.control.control_cli:register_agent_cli",
    "ipfs_accelerate_py.agent_supervisor.control.control_cli:run_agent_cli",
    "ipfs_accelerate_py.agent_supervisor.control.control_plane:SupervisorControlService",
)
