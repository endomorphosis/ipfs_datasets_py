"""Task-source projections package for agent_supervisor (ASREF task_sources).

This package owns Markdown and DuckDB task projections, taskboard storage,
persistent queues, dataset/todo vector indexes, and related identity helpers
(bundle ``asref/task-sources``; see
``docs/architecture/asref/move_map.json``).

It sits above ``core`` in the package DAG and must not import
``todo_daemon``, ``runtime``, ``merge``, ``rescue``, or
``self_improvement``.

Modules owned by this package:

* ``dataset_store``
* ``duckdb_state``
* ``duckdb_task_source``
* ``markdown_task_source``
* ``persistent_task_queue``
* ``task_identity``
* ``task_source`` (protocol / dual-projection boundary)
* ``taskboard_store``
* ``taskboard_ingest``
* ``todo_vector_index``
* ``huggingface_todo_locator``

Import them via::

    from ipfs_accelerate_py.agent_supervisor.task_sources.<module> import ...

The design intent (ASREF-G040 refinement) is that the backend-neutral
``task_source`` protocol remains importable from ``core`` once core cutover
includes it; implementations live here. Until that split lands, the protocol
module co-resides in this package and depends only on same-package
implementations plus still-flat siblings (for example ``prompt_workflow``,
``event_log``).

During the ASREF layout cutover, temporary flat copies may still exist at the
former root paths until a follow-on import-rewrite pass (outside the narrow
``task_sources/`` edit scope) removes them. Prefer ``task_sources.<module>``
for all new code. Do not introduce long-lived re-export stubs at the old flat
paths.

Package metadata and the public module list are intentional surface area so
importers and tooling can discover the task-sources contract without loading
optional supervisor providers.
"""

from __future__ import annotations

from typing import Final

__all__: Final[tuple[str, ...]] = (
    "TASK_SOURCES_PACKAGE_NAME",
    "TASK_SOURCES_OWNED_MODULES",
    "TASK_SOURCES_ALLOWED_DEPENDENTS",
    "TASK_SOURCES_FORBIDDEN_DEPENDENTS",
    "TASK_SOURCES_ALLOWED_DEPENDENCIES",
)

TASK_SOURCES_PACKAGE_NAME: Final[str] = "ipfs_accelerate_py.agent_supervisor.task_sources"

# Stems owned by asref/task-sources in docs/architecture/asref/move_map.json.
TASK_SOURCES_OWNED_MODULES: Final[tuple[str, ...]] = (
    "dataset_store",
    "duckdb_state",
    "duckdb_task_source",
    "markdown_task_source",
    "persistent_task_queue",
    "task_identity",
    "task_source",
    "taskboard_store",
    "taskboard_ingest",
    "todo_vector_index",
    "huggingface_todo_locator",
)

# Packages that may import from task_sources (DAG dependents).
TASK_SOURCES_ALLOWED_DEPENDENTS: Final[tuple[str, ...]] = (
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

# Lower DAG packages this package may depend on.
TASK_SOURCES_ALLOWED_DEPENDENCIES: Final[tuple[str, ...]] = ("core",)

# Packages that must not be imported by task_sources (DAG / cycle guard).
TASK_SOURCES_FORBIDDEN_DEPENDENTS: Final[tuple[str, ...]] = (
    "todo_daemon",
    "runtime",
    "merge",
    "rescue",
    "self_improvement",
    "integrations",
)
