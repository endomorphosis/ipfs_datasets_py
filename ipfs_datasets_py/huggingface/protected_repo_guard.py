"""Fail-closed guard for protected JusticeDAO Hugging Face repositories (LCR-084).

Protected dataset repositories may be mutated only through
``legal_corpora_publication_runtime.authorize_and_mutate_canonical``. Direct
``HfApi`` write methods against those repositories fail closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

PROTECTED_REPOS: Final = frozenset(
    {
        "justicedao/ipfs_state_laws",
        "justicedao/ipfs_federal_register",
    }
)
PROTECTED_WRITE_METHODS: Final = frozenset(
    {
        "create_commit",
        "upload_file",
        "upload_folder",
        "create_repo",
        "delete_file",
        "delete_folder",
        "move",
        "create_branch",
        "delete_branch",
        "delete_repo",
        "super_squash_history",
        "create_pull_request",
        "merge_pull_request",
    }
)
CANONICAL_RUNTIME = (
    "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime"
)


class ProtectedRepoGuardError(RuntimeError):
    """Raised when a protected repository would be mutated outside the runtime."""


def is_protected_repo(repo_id: Any) -> bool:
    text = str(repo_id or "").strip()
    return text in PROTECTED_REPOS


def require_unprotected_or_runtime(
    repo_id: Any,
    *,
    method: str,
    runtime_authorized: bool = False,
) -> None:
    if not is_protected_repo(repo_id):
        return
    if runtime_authorized:
        return
    raise ProtectedRepoGuardError(
        f"{method} against protected repository {repo_id!r} must enter "
        f"{CANONICAL_RUNTIME}.authorize_and_mutate_canonical"
    )


def guarded_write(
    repo_id: Any,
    method: str,
    callback: Callable[[], Any],
    *,
    runtime_authorized: bool = False,
) -> Any:
    require_unprotected_or_runtime(
        repo_id, method=method, runtime_authorized=runtime_authorized
    )
    return callback()


def inspect_kwargs_repo_id(kwargs: Mapping[str, Any]) -> str:
    for key in ("repo_id", "repo", "target_repo", "dataset_repo_id"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return ""
