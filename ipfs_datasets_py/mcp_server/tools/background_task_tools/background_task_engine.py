"""
Compatibility shim — business logic moved to ipfs_datasets_py.tasks.background_task_engine.

Do not add new code here. Use the canonical package location instead.
Import from ipfs_datasets_py.tasks.background_task_engine for all new code.
"""
# noqa: F401 — re-export all symbols for backward compatibility
try:
	from ipfs_datasets_py.workflow_automation.background_task_engine import *  # noqa: F401,F403
except Exception:
	from ipfs_datasets_py.tasks.background_task_engine import *  # type: ignore  # noqa: F401,F403
