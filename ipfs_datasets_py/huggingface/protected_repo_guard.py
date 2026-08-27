"""Fail-closed guard for protected JusticeDAO Hugging Face repositories (LCR-084).

Protected dataset repositories may be mutated only through
``legal_corpora_publication_runtime.authorize_and_mutate_canonical``. Direct
``HfApi`` write methods against those repositories fail closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import re
import sys
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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProtectedRepoGuardError(RuntimeError):
    """Raised when a protected repository would be mutated outside the runtime."""


@dataclass(frozen=True, slots=True)
class _CanonicalRuntimeAuthorization:
    """Context-local authority minted around one canonical runtime callback."""

    repository_id: str
    phase: str
    operation: str
    final_manifest_digest: str


_CANONICAL_RUNTIME_AUTHORIZATION: ContextVar[
    _CanonicalRuntimeAuthorization | None
] = ContextVar("legal_corpora_canonical_runtime_authorization", default=None)


def is_protected_repo(repo_id: Any) -> bool:
    text = str(repo_id or "").strip()
    return text.casefold() in PROTECTED_REPOS


@contextmanager
def _canonical_runtime_authorization(
    *,
    repository_id: str,
    phase: str,
    operation: str,
    final_manifest_digest: str,
):
    """Enter the private authority scope owned by the canonical runtime.

    This is intentionally not exported.  Public guard callers cannot grant
    themselves authority with a boolean; the runtime brackets the callback
    with this context only after its second canonical-evidence revalidation.
    """

    runtime_module = sys.modules.get(CANONICAL_RUNTIME)
    runtime_executable = getattr(
        runtime_module,
        "_CanonicalPublicationRuntimeExecutable",
        None,
    )
    expected_authorizer_code = getattr(
        runtime_executable,
        "AUTHORIZE_AND_MUTATE_CODE",
        None,
    )
    authorizer = getattr(
        runtime_module,
        "authorize_and_mutate_canonical",
        None,
    )
    if (
        runtime_module is None
        or runtime_executable is None
        or expected_authorizer_code is None
        or not callable(authorizer)
        or getattr(authorizer, "__code__", None) is not expected_authorizer_code
    ):
        raise ProtectedRepoGuardError(
            "canonical runtime authorizer executable identity drifted"
        )
    try:
        runtime_executable.assert_current()
    except Exception as exc:
        raise ProtectedRepoGuardError(
            "canonical runtime authorizer executable identity drifted"
        ) from exc

    frame = sys._getframe(1)
    runtime_frame_found = False
    while frame is not None:
        if (
            frame.f_globals is runtime_module.__dict__
            and frame.f_code is expected_authorizer_code
        ):
            runtime_frame_found = True
            break
        frame = frame.f_back
    if not runtime_frame_found:
        raise ProtectedRepoGuardError(
            "canonical runtime authority may be entered only by the active "
            "authorize_and_mutate_canonical implementation"
        )

    repository = str(repository_id or "").strip()
    phase_text = str(phase or "").strip()
    operation_text = str(operation or "").strip()
    digest = str(final_manifest_digest or "").strip().casefold()
    if (
        not is_protected_repo(repository)
        or not phase_text
        or not operation_text
        or not _SHA256_RE.fullmatch(digest)
    ):
        raise ProtectedRepoGuardError(
            "canonical runtime authority is malformed or targets an "
            "unprotected repository"
        )
    authorization = _CanonicalRuntimeAuthorization(
        repository_id=repository.casefold(),
        phase=phase_text,
        operation=operation_text,
        final_manifest_digest=digest,
    )
    token = _CANONICAL_RUNTIME_AUTHORIZATION.set(authorization)
    try:
        yield
    finally:
        _CANONICAL_RUNTIME_AUTHORIZATION.reset(token)


def require_unprotected_or_runtime(
    repo_id: Any,
    *,
    method: str,
    expected_phase: str | None = None,
    expected_operation: str | None = None,
    expected_manifest_digest: str | None = None,
    runtime_authorized: Any = None,
) -> None:
    if not is_protected_repo(repo_id):
        return
    if runtime_authorized is not None:
        raise ProtectedRepoGuardError(
            "caller-supplied runtime_authorized booleans cannot authorize a "
            "protected repository mutation"
        )
    authorization = _CANONICAL_RUNTIME_AUTHORIZATION.get()
    if authorization is not None:
        expected_digest = str(expected_manifest_digest or "").strip().casefold()
        if (
            authorization.repository_id == str(repo_id).strip().casefold()
            and (
                expected_phase is None
                or authorization.phase == str(expected_phase).strip()
            )
            and (
                expected_operation is None
                or authorization.operation == str(expected_operation).strip()
            )
            and (
                expected_manifest_digest is None
                or (
                    _SHA256_RE.fullmatch(expected_digest) is not None
                    and authorization.final_manifest_digest == expected_digest
                )
            )
        ):
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
    expected_phase: str | None = None,
    expected_operation: str | None = None,
    expected_manifest_digest: str | None = None,
    runtime_authorized: Any = None,
) -> Any:
    require_unprotected_or_runtime(
        repo_id,
        method=method,
        expected_phase=expected_phase,
        expected_operation=expected_operation,
        expected_manifest_digest=expected_manifest_digest,
        runtime_authorized=runtime_authorized,
    )
    return callback()


def inspect_kwargs_repo_id(kwargs: Mapping[str, Any]) -> str:
    for key in ("repo_id", "repo", "target_repo", "dataset_repo_id"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return ""
