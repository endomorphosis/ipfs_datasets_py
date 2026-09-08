"""Fail-closed guard for protected JusticeDAO Hugging Face repositories (LCR-084).

Protected dataset repositories may be mutated only through
``legal_corpora_publication_runtime.authorize_and_mutate_canonical``. Direct
``HfApi`` write methods against those repositories fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import CodeType, FunctionType, ModuleType
from typing import Any, Final

PROTECTED_REPOS: Final = frozenset(
    {
        "justicedao/ipfs_state_laws",
        "justicedao/ipfs_federal_register",
    }
)
STATE_MAIN_ROOT_README_CAS_OPERATION: Final = (
    "state_main_root_readme_compare_and_swap"
)
STATE_MAIN_ROOT_README_CAS_TASK_ID: Final = "LCR-042"
STATE_MAIN_ROOT_README_CAS_REPOSITORY_ID: Final = (
    "justicedao/ipfs_state_laws"
)
STATE_MAIN_ROOT_README_CAS_PATH: Final = "README.md"
PROTECTED_WRITE_METHODS: Final = frozenset(
    {
        # Repository lifecycle, visibility, and gated-access controls.
        "accept_access_request",
        "cancel_access_request",
        "create_repo",
        "delete_repo",
        "grant_access",
        "move_repo",
        "reject_access_request",
        "update_repo_settings",
        "update_repo_visibility",
        # Git content, references, and LFS storage.
        "create_branch",
        "create_commit",
        "create_tag",
        "delete_branch",
        "delete_file",
        "delete_files",
        "delete_folder",
        "delete_tag",
        "permanently_delete_lfs_files",
        "preupload_lfs_files",
        "super_squash_history",
        "upload_file",
        "upload_folder",
        "upload_large_folder",
        # Discussions and pull requests are mutable repository state too.
        "change_discussion_status",
        "comment_discussion",
        "create_discussion",
        "create_pull_request",
        "edit_discussion_comment",
        "hide_discussion_comment",
        "merge_pull_request",
        "rename_discussion",
    }
)
CANONICAL_RUNTIME = (
    "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ProtectedRepoGuardError(RuntimeError):
    """Raised when a protected repository would be mutated outside the runtime."""


def _normalized_text(value: Any, *, label: str, casefold: bool = False) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text:
        raise ProtectedRepoGuardError(f"canonical mutation {label} is malformed")
    return text.casefold() if casefold else text


def _normalized_path(value: Any, *, label: str) -> str:
    text = _normalized_text(value, label=label)
    if (
        text.startswith("/")
        or text.endswith("/")
        or "\\" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise ProtectedRepoGuardError(
            f"canonical mutation {label} must be a normalized relative path"
        )
    return text


def _normalized_sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").strip().casefold()
    if _SHA256_RE.fullmatch(digest) is None:
        raise ProtectedRepoGuardError(
            f"canonical mutation {label} must be a lowercase SHA-256 digest"
        )
    return digest


def _normalized_git_sha(value: Any, *, label: str) -> str:
    digest = str(value or "").strip().casefold()
    if _GIT_SHA_RE.fullmatch(digest) is None:
        raise ProtectedRepoGuardError(
            f"canonical mutation {label} must be an exact 40-hex Git SHA"
        )
    return digest


@dataclass(frozen=True, slots=True)
class CanonicalMutationFileBinding:
    """One immutable local-file/remote-object pair in commit order."""

    relative_path: str
    remote_path: str
    size_bytes: int
    sha256: str
    local_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise ProtectedRepoGuardError(
                "canonical mutation file size_bytes must be an integer"
            )
        if self.size_bytes < 0:
            raise ProtectedRepoGuardError(
                "canonical mutation file size_bytes must be non-negative"
            )
        object.__setattr__(
            self,
            "relative_path",
            _normalized_path(self.relative_path, label="relative_path"),
        )
        object.__setattr__(
            self,
            "remote_path",
            _normalized_path(self.remote_path, label="remote_path"),
        )
        object.__setattr__(
            self,
            "sha256",
            _normalized_sha256(self.sha256, label="sha256"),
        )
        object.__setattr__(
            self,
            "local_sha256",
            _normalized_sha256(self.local_sha256, label="local_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_sha256": self.local_sha256,
            "relative_path": self.relative_path,
            "remote_path": self.remote_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class CanonicalMutationBinding:
    """Normalized identity of one exact protected-repository mutation."""

    method: str
    repository_id: str
    repository_type: str
    revision: str
    parent_commit: str
    files: tuple[CanonicalMutationFileBinding, ...]
    plan_digest: str
    release_manifest_digest: str
    policy_proof_digest: str
    commit_message_digest: str
    root_readme_cas: StateMainRootReadmeCASPlanBinding | None = None

    def __post_init__(self) -> None:
        method = _normalized_text(self.method, label="method")
        repository_id = _normalized_text(
            self.repository_id,
            label="repository_id",
            casefold=True,
        )
        repository_type = _normalized_text(
            self.repository_type,
            label="repository_type",
            casefold=True,
        )
        revision = _normalized_text(self.revision, label="revision")
        parent_commit = _normalized_text(
            self.parent_commit,
            label="parent_commit",
            casefold=True,
        )
        files = tuple(self.files)
        if method not in PROTECTED_WRITE_METHODS:
            raise ProtectedRepoGuardError(
                "canonical mutation method is not a protected write method"
            )
        if not is_protected_repo(repository_id):
            raise ProtectedRepoGuardError(
                "canonical mutation repository_id is not protected"
            )
        if _GIT_SHA_RE.fullmatch(parent_commit) is None:
            raise ProtectedRepoGuardError(
                "canonical mutation parent_commit must be an exact 40-hex Git SHA"
            )
        if not files or any(
            not isinstance(item, CanonicalMutationFileBinding) for item in files
        ):
            raise ProtectedRepoGuardError(
                "canonical mutation files must be a non-empty tuple of normalized bindings"
            )
        remote_paths = tuple(item.remote_path for item in files)
        if len(remote_paths) != len(set(remote_paths)):
            raise ProtectedRepoGuardError(
                "canonical mutation files contain duplicate remote paths"
            )
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(self, "repository_type", repository_type)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "parent_commit", parent_commit)
        object.__setattr__(self, "files", files)
        for attribute in (
            "plan_digest",
            "release_manifest_digest",
            "policy_proof_digest",
            "commit_message_digest",
        ):
            object.__setattr__(
                self,
                attribute,
                _normalized_sha256(getattr(self, attribute), label=attribute),
            )
        root_readme_cas = self.root_readme_cas
        if root_readme_cas is not None:
            if type(root_readme_cas) is not StateMainRootReadmeCASPlanBinding:
                raise ProtectedRepoGuardError(
                    "canonical mutation root_readme_cas must be its exact immutable binding"
                )
            root_files = tuple(
                item
                for item in files
                if item.remote_path == STATE_MAIN_ROOT_README_CAS_PATH
            )
            immutable_files = tuple(
                item
                for item in files
                if item.remote_path != STATE_MAIN_ROOT_README_CAS_PATH
            )
            release_prefix = root_readme_cas.release_prefix + "/"
            if (
                method != "create_commit"
                or repository_id != STATE_MAIN_ROOT_README_CAS_REPOSITORY_ID
                or repository_type != "dataset"
                or revision != "main"
                or parent_commit != root_readme_cas.audited_parent_commit
                or self.plan_digest
                != root_readme_cas.publication_plan_digest
                or self.release_manifest_digest
                != root_readme_cas.release_manifest_digest
                or self.policy_proof_digest
                != root_readme_cas.policy_proof_digest
                or len(root_files) != 1
                or not immutable_files
                or any(
                    not item.remote_path.startswith(release_prefix)
                    for item in immutable_files
                )
                or root_files[0].sha256
                != root_readme_cas.replacement_sha256
                or root_files[0].local_sha256
                != root_readme_cas.replacement_sha256
                or root_files[0].size_bytes
                != root_readme_cas.replacement_size_bytes
            ):
                raise ProtectedRepoGuardError(
                    "root README CAS must be the sole non-additive object in one "
                    "exact State-main immutable-release create_commit"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "commit_message_digest": self.commit_message_digest,
            "files": [item.to_dict() for item in self.files],
            "method": self.method,
            "parent_commit": self.parent_commit,
            "plan_digest": self.plan_digest,
            "policy_proof_digest": self.policy_proof_digest,
            "release_manifest_digest": self.release_manifest_digest,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "revision": self.revision,
        }
        if self.root_readme_cas is not None:
            payload["root_readme_cas"] = self.root_readme_cas.to_dict()
        return payload

    @property
    def payload_digest(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class StateMainRootReadmeCASPlanBinding:
    """Reviewed intent for the sole mutable State Laws control object.

    Release artifacts retain their append-only contract while this nested
    binding truthfully records the sole compare-and-swap replacement (or an add
    conditioned on audited absence) allowed in the same one-shot commit:
    repository-root ``README.md``.
    """

    audited_parent_commit: str
    expected_previous_sha256: str | None
    replacement_sha256: str
    replacement_size_bytes: int
    release_manifest_digest: str
    release_prefix: str
    publication_plan_digest: str
    policy_proof_digest: str
    control_plan_digest: str
    review_id: str
    reviewer: str
    repository_id: str = STATE_MAIN_ROOT_README_CAS_REPOSITORY_ID
    repository_type: str = "dataset"
    revision: str = "main"
    remote_path: str = STATE_MAIN_ROOT_README_CAS_PATH
    phase: str = "state_main"
    operation: str = STATE_MAIN_ROOT_README_CAS_OPERATION
    task_id: str = STATE_MAIN_ROOT_README_CAS_TASK_ID

    def __post_init__(self) -> None:
        if (
            self.repository_id != STATE_MAIN_ROOT_README_CAS_REPOSITORY_ID
            or self.repository_type != "dataset"
            or self.revision != "main"
            or self.remote_path != STATE_MAIN_ROOT_README_CAS_PATH
            or self.phase != "state_main"
            or self.operation != STATE_MAIN_ROOT_README_CAS_OPERATION
            or self.task_id != STATE_MAIN_ROOT_README_CAS_TASK_ID
        ):
            raise ProtectedRepoGuardError(
                "root control CAS is limited to LCR-042, State main, and exact "
                "repository-root README.md"
            )
        if (
            not isinstance(self.replacement_size_bytes, int)
            or isinstance(self.replacement_size_bytes, bool)
            or self.replacement_size_bytes <= 0
        ):
            raise ProtectedRepoGuardError(
                "root control CAS replacement_size_bytes must be a positive integer"
            )
        object.__setattr__(
            self,
            "audited_parent_commit",
            _normalized_git_sha(
                self.audited_parent_commit,
                label="audited_parent_commit",
            ),
        )
        expected_previous = self.expected_previous_sha256
        if expected_previous is not None:
            if type(expected_previous) is not str:
                raise ProtectedRepoGuardError(
                    "root control CAS expected_previous_sha256 must be a digest "
                    "or exact null for audited absence"
                )
            expected_previous = _normalized_sha256(
                expected_previous,
                label="expected_previous_sha256",
            )
            object.__setattr__(
                self,
                "expected_previous_sha256",
                expected_previous,
            )
        for attribute in (
            "replacement_sha256",
            "release_manifest_digest",
            "publication_plan_digest",
            "policy_proof_digest",
            "control_plan_digest",
        ):
            object.__setattr__(
                self,
                attribute,
                _normalized_sha256(getattr(self, attribute), label=attribute),
            )
        if expected_previous == self.replacement_sha256:
            raise ProtectedRepoGuardError(
                "root control CAS refuses an identical no-op replacement"
            )
        expected_prefix = (
            "data/state_laws/sha256-" + self.release_manifest_digest
        )
        if self.release_prefix != expected_prefix:
            raise ProtectedRepoGuardError(
                "root control CAS release_prefix must be the exact immutable "
                "State Laws release-manifest prefix"
            )
        for attribute in ("review_id", "reviewer"):
            value = _normalized_text(getattr(self, attribute), label=attribute)
            if len(value) > 512:
                raise ProtectedRepoGuardError(
                    f"canonical mutation {attribute} is too long"
                )
            object.__setattr__(self, attribute, value)

    @property
    def expected_previous_absent(self) -> bool:
        return self.expected_previous_sha256 is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "audited_parent_commit": self.audited_parent_commit,
            "control_plan_digest": self.control_plan_digest,
            "expected_previous_absent": self.expected_previous_absent,
            "expected_previous_sha256": self.expected_previous_sha256,
            "operation": self.operation,
            "phase": self.phase,
            "policy_proof_digest": self.policy_proof_digest,
            "publication_plan_digest": self.publication_plan_digest,
            "release_manifest_digest": self.release_manifest_digest,
            "release_prefix": self.release_prefix,
            "remote_path": self.remote_path,
            "replacement_sha256": self.replacement_sha256,
            "replacement_size_bytes": self.replacement_size_bytes,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "review_id": self.review_id,
            "reviewer": self.reviewer,
            "revision": self.revision,
            "task_id": self.task_id,
        }

    @property
    def payload_digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def is_protected_repo(repo_id: Any) -> bool:
    text = str(repo_id or "").strip()
    return text.casefold() in PROTECTED_REPOS


def _build_authority_manager():
    """Keep the authority type, seal, and ContextVar outside module globals."""

    authority_seal = object()
    active_authority: ContextVar[Any | None] = ContextVar(
        "legal_corpora_canonical_runtime_authorization",
        default=None,
    )
    anchor_lock = Lock()
    runtime_anchor: tuple[Any, ...] | None = None
    publisher_anchor: tuple[Any, ...] | None = None
    expected_runtime_path = (
        Path(__file__).resolve().parents[1]
        / "processors/legal_data/legal_corpora_publication_runtime.py"
    ).resolve()

    expected_publisher_path = Path(__file__).resolve().with_name("publisher.py")

    class OneShotConsumption:
        __slots__ = ("count", "lock")

        def __init__(self) -> None:
            self.lock = Lock()
            self.count = 0

        def consume(self) -> None:
            with self.lock:
                if self.count != 0:
                    raise ProtectedRepoGuardError(
                        "canonical runtime mutation authority was already consumed"
                    )
                self.count = 1

        def consumed_once(self) -> bool:
            with self.lock:
                return self.count == 1

    class CanonicalRuntimeAuthorization:
        __slots__ = (
            "consumption",
            "credential_identity",
            "credentials_scope",
            "final_manifest_digest",
            "mutation_binding",
            "operation",
            "phase",
            "preflight_executor",
            "prepare_method",
            "prepared_call",
            "prepared_executor",
            "principal",
            "principal_authority_digest",
            "principal_probe",
            "repository_id",
            "seal",
            "token_env",
        )

        def __init__(
            self,
            *,
            repository_id: str,
            phase: str,
            operation: str,
            final_manifest_digest: str,
            mutation_binding: CanonicalMutationBinding,
            preflight_executor: Any = None,
            prepare_method: Any = None,
            prepared_executor: Any = None,
            prepared_call: Any = None,
            principal: str = "",
            principal_authority_digest: str = "",
            principal_probe: Any = None,
            credential_identity: str = "",
            credentials_scope: str = "",
            token_env: str = "",
        ) -> None:
            self.repository_id = repository_id
            self.phase = phase
            self.operation = operation
            self.final_manifest_digest = final_manifest_digest
            self.mutation_binding = mutation_binding
            self.preflight_executor = preflight_executor
            self.prepare_method = prepare_method
            self.prepared_executor = prepared_executor
            self.prepared_call = prepared_call
            self.principal = principal
            self.principal_authority_digest = principal_authority_digest
            self.principal_probe = principal_probe
            self.credential_identity = credential_identity
            self.credentials_scope = credentials_scope
            self.token_env = token_env
            self.consumption = OneShotConsumption()
            self.seal = authority_seal

    def _runtime_surface(runtime_executable: type) -> tuple[tuple[str, Any], ...]:
        return tuple(
            sorted(
                (
                    name,
                    value,
                )
                for name, value in vars(runtime_executable).items()
                if callable(value)
                or isinstance(value, (classmethod, staticmethod))
                or name
                in {
                    "AUTHORIZE_AND_MUTATE_CODE",
                    "EXECUTABLE_IMPORT_SHA256",
                }
            )
        )

    def _publisher_type_surface(target: type) -> tuple[Any, ...]:
        namespace = vars(target)
        executable = []
        for name, descriptor in namespace.items():
            function = (
                descriptor.__func__
                if isinstance(descriptor, (classmethod, staticmethod))
                else descriptor
            )
            if callable(function):
                executable.append(
                    (name, descriptor, function, getattr(function, "__code__", None))
                )
        return tuple(sorted(namespace)), tuple(sorted(executable, key=lambda item: item[0]))

    def _nested_code(root: CodeType, name: str) -> CodeType | None:
        matches: list[CodeType] = []

        def visit(code: CodeType) -> None:
            for constant in code.co_consts:
                if not isinstance(constant, CodeType):
                    continue
                if constant.co_name == name:
                    matches.append(constant)
                visit(constant)

        visit(root)
        return matches[0] if len(matches) == 1 else None

    def _closure_bindings(function: Any) -> dict[str, Any]:
        if not isinstance(function, FunctionType):
            return {}
        closure = function.__closure__ or ()
        freevars = function.__code__.co_freevars
        if len(closure) != len(freevars):
            return {}
        try:
            return {
                name: closure[index].cell_contents
                for index, name in enumerate(freevars)
            }
        except ValueError:
            return {}

    def register_publisher_anchor(
        *,
        publisher_module: ModuleType,
        preflight_type: type,
        prepared_type: type,
    ) -> None:
        """Register exact publisher classes/source once from module initialization."""

        nonlocal publisher_anchor
        caller = sys._getframe(1)
        try:
            namespace = vars(publisher_module) if type(publisher_module) is ModuleType else {}
            preflight_method = (
                vars(preflight_type).get("prepare")
                if isinstance(preflight_type, type)
                else None
            )
            prepared_method = (
                vars(prepared_type).get("__call__")
                if isinstance(prepared_type, type)
                else None
            )
            publisher_type = namespace.get("HuggingFaceReleasePublisher")
            publish_method = (
                vars(publisher_type).get(
                    "execute_canonical_legal_corpora_mutation"
                )
                if isinstance(publisher_type, type)
                else None
            )
            publish_code = getattr(publish_method, "__code__", None)
            principal_probe_code = (
                _nested_code(publish_code, "principal_probe")
                if isinstance(publish_code, CodeType)
                else None
            )
            hf_api_type = namespace.get("_CANONICAL_HF_API_TYPE")
            prepared_helpers = (
                (
                    "require_unprotected_or_runtime",
                    "require_guard",
                    "require_guard_local",
                    namespace.get("require_unprotected_or_runtime"),
                ),
                (
                    "_rehash_prepared_snapshot_files",
                    "rehash_files",
                    "rehash_files_local",
                    namespace.get("_rehash_prepared_snapshot_files"),
                ),
                (
                    "_canonical_revalidate_compound_parent_prefix_and_readme",
                    "revalidate_remote",
                    "revalidate_remote_local",
                    namespace.get(
                        "_canonical_revalidate_compound_parent_prefix_and_readme"
                    ),
                ),
                (
                    "guarded_write",
                    "protected_write",
                    "protected_write_local",
                    namespace.get("guarded_write"),
                ),
                (
                    "_canonical_hf_api_create_branch",
                    "create_branch",
                    "create_branch_local",
                    namespace.get("_canonical_hf_api_create_branch"),
                ),
                (
                    "_canonical_hf_api_create_commit",
                    "create_commit",
                    "create_commit_local",
                    namespace.get("_canonical_hf_api_create_commit"),
                ),
            )
            prepared_closure = _closure_bindings(prepared_method)
            source_digest = hashlib.sha256(expected_publisher_path.read_bytes()).hexdigest()
            valid = (
                namespace.get("__name__") == "ipfs_datasets_py.huggingface.publisher"
                and sys.modules.get(namespace.get("__name__")) is publisher_module
                and caller.f_globals is namespace
                and caller.f_code.co_name == "<module>"
                and Path(caller.f_code.co_filename).resolve()
                == expected_publisher_path
                and Path(str(namespace.get("__file__") or "")).resolve()
                == expected_publisher_path
                and not expected_publisher_path.is_symlink()
                and expected_publisher_path.is_file()
                and namespace.get("_StateLawsCanonicalCommitPreflight")
                is preflight_type
                and namespace.get("_PreparedStateLawsCanonicalCommitExecutor")
                is prepared_type
                and namespace.get("HuggingFaceReleasePublisher") is publisher_type
                and isinstance(publisher_type, type)
                and isinstance(publish_method, FunctionType)
                and isinstance(principal_probe_code, CodeType)
                and principal_probe_code.co_freevars == ("api_template", "self")
                and isinstance(hf_api_type, type)
                and namespace.get("_STATE_LAWS_CANONICAL_COMMIT_PREFLIGHT_CODE")
                is getattr(preflight_method, "__code__", None)
                and namespace.get("_STATE_LAWS_PREPARED_COMMIT_EXECUTOR_CODE")
                is getattr(prepared_method, "__code__", None)
                and getattr(prepared_method, "__globals__", None) is namespace
                and set(prepared_closure)
                == {item[1] for item in prepared_helpers}
                and all(
                    callable(helper)
                    and prepared_closure.get(closure_name) is helper
                    for _, closure_name, _, helper in prepared_helpers
                )
                and str(namespace.get("_PUBLISHER_IMPORT_SOURCE_SHA256") or "")
                == source_digest
            )
            if not valid:
                raise ProtectedRepoGuardError(
                    "canonical publisher trust anchor registration was not made "
                    "by the exact publisher module"
                )
            candidate = (
                publisher_module,
                publisher_type,
                publish_method,
                publish_code,
                _publisher_type_surface(publisher_type),
                principal_probe_code,
                hf_api_type,
                preflight_type,
                preflight_method,
                getattr(preflight_method, "__code__", None),
                _publisher_type_surface(preflight_type),
                prepared_type,
                prepared_method,
                getattr(prepared_method, "__code__", None),
                _publisher_type_surface(prepared_type),
                prepared_helpers,
                source_digest,
            )
            with anchor_lock:
                if publisher_anchor is not None and publisher_anchor != candidate:
                    raise ProtectedRepoGuardError(
                        "canonical publisher trust anchor is already registered"
                    )
                publisher_anchor = candidate
        finally:
            del caller

    def _require_publisher_anchor() -> tuple[Any, ...]:
        with anchor_lock:
            anchor = publisher_anchor
        if anchor is None:
            raise ProtectedRepoGuardError(
                "canonical publisher trust anchor is not registered"
            )
        (
            publisher_module,
            publisher_type,
            publish_method,
            publish_code,
            publisher_surface,
            principal_probe_code,
            hf_api_type,
            preflight_type,
            preflight_method,
            preflight_code,
            preflight_surface,
            prepared_type,
            prepared_method,
            prepared_code,
            prepared_surface,
            prepared_helpers,
            source_digest,
        ) = anchor
        namespace = vars(publisher_module)
        prepared_closure = _closure_bindings(prepared_method)
        loaded_path = Path(str(namespace.get("__file__") or ""))
        if (
            sys.modules.get("ipfs_datasets_py.huggingface.publisher")
            is not publisher_module
            or namespace.get("HuggingFaceReleasePublisher") is not publisher_type
            or vars(publisher_type).get(
                "execute_canonical_legal_corpora_mutation"
            ) is not publish_method
            or getattr(publish_method, "__code__", None) is not publish_code
            or _publisher_type_surface(publisher_type) != publisher_surface
            or _nested_code(publish_code, "principal_probe")
            is not principal_probe_code
            or namespace.get("_CANONICAL_HF_API_TYPE") is not hf_api_type
            or namespace.get("_StateLawsCanonicalCommitPreflight")
            is not preflight_type
            or namespace.get("_PreparedStateLawsCanonicalCommitExecutor")
            is not prepared_type
            or vars(preflight_type).get("prepare") is not preflight_method
            or getattr(preflight_method, "__code__", None) is not preflight_code
            or _publisher_type_surface(preflight_type) != preflight_surface
            or vars(prepared_type).get("__call__") is not prepared_method
            or getattr(prepared_method, "__code__", None) is not prepared_code
            or _publisher_type_surface(prepared_type) != prepared_surface
            or getattr(prepared_method, "__globals__", None) is not namespace
            or set(prepared_closure)
            != {item[1] for item in prepared_helpers}
            or any(
                namespace.get(global_name) is not helper
                or prepared_closure.get(closure_name) is not helper
                for global_name, closure_name, _, helper in prepared_helpers
            )
            or namespace.get("_STATE_LAWS_CANONICAL_COMMIT_PREFLIGHT_CODE")
            is not preflight_code
            or namespace.get("_STATE_LAWS_PREPARED_COMMIT_EXECUTOR_CODE")
            is not prepared_code
            or str(namespace.get("_PUBLISHER_IMPORT_SOURCE_SHA256") or "")
            != source_digest
            or not str(namespace.get("__file__") or "").strip()
            or loaded_path.is_symlink()
            or not loaded_path.is_file()
            or loaded_path.resolve() != expected_publisher_path
            or hashlib.sha256(loaded_path.read_bytes()).hexdigest()
            != source_digest
        ):
            raise ProtectedRepoGuardError(
                "canonical publisher executable/source identity drifted"
            )
        return anchor

    def _principal_probe_matches_anchor(
        principal_probe: Any,
        preflight_executor: Any,
    ) -> bool:
        anchor = _require_publisher_anchor()
        (
            publisher_module,
            publisher_type,
            _,
            _,
            _,
            principal_probe_code,
            hf_api_type,
            preflight_type,
            *_rest,
        ) = anchor
        if (
            type(principal_probe) is not FunctionType
            or principal_probe.__code__ is not principal_probe_code
            or principal_probe.__globals__ is not vars(publisher_module)
            or principal_probe.__defaults__ is not None
            or principal_probe.__kwdefaults__ is not None
            or principal_probe.__dict__
            or type(preflight_executor) is not preflight_type
            or principal_probe_code.co_freevars != ("api_template", "self")
        ):
            return False
        closure = principal_probe.__closure__ or ()
        if len(closure) != 2:
            return False
        try:
            bindings = {
                name: closure[index].cell_contents
                for index, name in enumerate(principal_probe_code.co_freevars)
            }
            api_template = object.__getattribute__(
                preflight_executor,
                "api_template",
            )
            publisher = object.__getattribute__(
                preflight_executor,
                "publisher",
            )
        except Exception:
            return False
        return bool(
            bindings.get("api_template") is api_template
            and bindings.get("self") is publisher
            and set(bindings) == {"api_template", "self"}
            and type(api_template) is hf_api_type
            and type(publisher) is publisher_type
        )

    def register_runtime_anchor(
        *,
        runtime_module: ModuleType,
        authorizer: Callable[..., Any],
        runtime_executable: type,
    ) -> None:
        """Register the real runtime once, from its own module initialization."""

        nonlocal runtime_anchor
        caller = sys._getframe(1)
        try:
            module_namespace = vars(runtime_module) if type(runtime_module) is ModuleType else {}
            executable_namespace = (
                vars(runtime_executable)
                if isinstance(runtime_executable, type)
                else {}
            )
            authorizer_code = getattr(authorizer, "__code__", None)
            assert_descriptor = executable_namespace.get("assert_current")
            assert_function = (
                assert_descriptor.__func__
                if isinstance(assert_descriptor, classmethod)
                else None
            )
            module_file = Path(
                str(module_namespace.get("__file__") or "")
            ).resolve()
            valid = (
                module_namespace.get("__name__") == CANONICAL_RUNTIME
                and sys.modules.get(CANONICAL_RUNTIME) is runtime_module
                and caller.f_globals is module_namespace
                and Path(caller.f_code.co_filename).resolve()
                == expected_runtime_path
                and module_file == expected_runtime_path
                and not expected_runtime_path.is_symlink()
                and expected_runtime_path.is_file()
                and module_namespace.get("authorize_and_mutate_canonical")
                is authorizer
                and module_namespace.get("_CanonicalPublicationRuntimeExecutable")
                is runtime_executable
                and executable_namespace.get("AUTHORIZE_AND_MUTATE_CODE")
                is authorizer_code
                and callable(assert_function)
                and getattr(authorizer, "__module__", None) == CANONICAL_RUNTIME
                and getattr(authorizer, "__qualname__", None)
                == "authorize_and_mutate_canonical"
            )
            if not valid:
                raise ProtectedRepoGuardError(
                    "canonical runtime trust anchor registration was not made by "
                    "the exact runtime module"
                )
            assert_function(runtime_executable)
            surface = _runtime_surface(runtime_executable)
            candidate = (
                runtime_module,
                authorizer,
                authorizer_code,
                runtime_executable,
                assert_function,
                surface,
                hashlib.sha256(expected_runtime_path.read_bytes()).hexdigest(),
            )
            with anchor_lock:
                if runtime_anchor is not None and runtime_anchor != candidate:
                    raise ProtectedRepoGuardError(
                        "canonical runtime trust anchor is already registered"
                    )
                runtime_anchor = candidate
        finally:
            del caller

    def _require_runtime_anchor() -> tuple[Any, ...]:
        with anchor_lock:
            anchor = runtime_anchor
        if anchor is None:
            raise ProtectedRepoGuardError(
                "no active canonical runtime authorize boundary is registered"
            )
        (
            runtime_module,
            authorizer,
            authorizer_code,
            runtime_executable,
            assert_function,
            surface,
            runtime_source_digest,
        ) = anchor
        if (
            sys.modules.get(CANONICAL_RUNTIME) is not runtime_module
            or vars(runtime_module).get("authorize_and_mutate_canonical")
            is not authorizer
            or vars(runtime_module).get("_CanonicalPublicationRuntimeExecutable")
            is not runtime_executable
            or vars(runtime_executable).get("AUTHORIZE_AND_MUTATE_CODE")
            is not authorizer_code
            or _runtime_surface(runtime_executable) != surface
            or expected_runtime_path.is_symlink()
            or not expected_runtime_path.is_file()
            or hashlib.sha256(expected_runtime_path.read_bytes()).hexdigest()
            != runtime_source_digest
        ):
            raise ProtectedRepoGuardError(
                "canonical runtime authorizer executable identity drifted"
            )
        try:
            assert_function(runtime_executable)
        except Exception as exc:
            raise ProtectedRepoGuardError(
                "canonical runtime authorizer executable identity drifted"
            ) from exc
        return anchor

    def enter_authority(
        *,
        repository_id: str,
        phase: str,
        operation: str,
        final_manifest_digest: str,
        mutation_binding: CanonicalMutationBinding | None = None,
        preflight_executor: Any = None,
        prepare_method: Any = None,
        prepared_executor: Any = None,
        prepared_call: Any = None,
        principal: str = "",
        principal_authority_digest: str = "",
        principal_probe: Any = None,
        credential_identity: str = "",
        credentials_scope: str = "",
        token_env: str = "",
    ):
        """Create one lexical authority from the anchored direct authorizer."""

        anchor = _require_runtime_anchor()
        runtime_module, _, authorizer_code, *_ = anchor
        caller = sys._getframe(1)
        try:
            if (
                caller.f_globals is not vars(runtime_module)
                or caller.f_code is not authorizer_code
                or caller.f_locals.get("mutation_executor") is not preflight_executor
                or caller.f_locals.get("prepare_method") is not prepare_method
                or caller.f_locals.get("prepared_executor") is not prepared_executor
                or caller.f_locals.get("prepared_call") is not prepared_call
                or getattr(caller.f_locals.get("req"), "principal_probe", None)
                is not principal_probe
            ):
                raise ProtectedRepoGuardError(
                    "canonical runtime authority may be entered only by the active "
                    "authorize_and_mutate_canonical implementation"
                )
        finally:
            del caller

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
        if not isinstance(mutation_binding, CanonicalMutationBinding):
            raise ProtectedRepoGuardError(
                "canonical runtime authority requires an immutable mutation binding"
            )
        if mutation_binding.repository_id != repository.casefold():
            raise ProtectedRepoGuardError(
                "canonical runtime mutation binding targets a different repository"
            )
        if not all(
            item is not None
            for item in (
                preflight_executor,
                prepare_method,
                prepared_executor,
                prepared_call,
            )
        ):
            raise ProtectedRepoGuardError(
                "canonical runtime authority requires the exact two-stage mutation "
                "executor"
            )
        if not _principal_probe_matches_anchor(
            principal_probe,
            preflight_executor,
        ):
            raise ProtectedRepoGuardError(
                "canonical runtime authority requires the exact source-anchored "
                "publisher principal probe"
            )
        principal_text = _normalized_text(principal, label="principal")
        authority_digest = _normalized_sha256(
            principal_authority_digest,
            label="principal_authority_digest",
        )
        credential_text = _normalized_text(
            credential_identity,
            label="credential_identity",
        )
        scope_text = _normalized_text(credentials_scope, label="credentials_scope")
        token_env_text = _normalized_text(token_env, label="token_env")
        if active_authority.get() is not None:
            raise ProtectedRepoGuardError(
                "canonical runtime mutation authority cannot be nested"
            )
        authorization = CanonicalRuntimeAuthorization(
            repository_id=repository.casefold(),
            phase=phase_text,
            operation=operation_text,
            final_manifest_digest=digest,
            mutation_binding=mutation_binding,
            preflight_executor=preflight_executor,
            prepare_method=prepare_method,
            prepared_executor=prepared_executor,
            prepared_call=prepared_call,
            principal=principal_text,
            principal_authority_digest=authority_digest,
            principal_probe=principal_probe,
            credential_identity=credential_text,
            credentials_scope=scope_text,
            token_env=token_env_text,
        )

        @contextmanager
        def scope():
            _require_runtime_anchor()
            token = active_authority.set(authorization)
            try:
                yield authorization
            finally:
                active_authority.reset(token)

        return scope()

    def require_authority(
        *,
        repository_id: str,
        method: str,
        expected_phase: str | None,
        expected_operation: str | None,
        expected_manifest_digest: str | None,
        expected_payload_digest: str | None,
    ) -> Any:
        authorization = active_authority.get()
        expected_digest = str(expected_manifest_digest or "").strip().casefold()
        expected_payload = str(expected_payload_digest or "").strip().casefold()
        method_text = str(method or "").strip()
        if (
            type(authorization) is CanonicalRuntimeAuthorization
            and authorization.seal is authority_seal
            and authorization.repository_id == repository_id.casefold()
            and authorization.mutation_binding.method == method_text
            and expected_phase is not None
            and authorization.phase == str(expected_phase).strip()
            and expected_operation is not None
            and authorization.operation == str(expected_operation).strip()
            and expected_manifest_digest is not None
            and _SHA256_RE.fullmatch(expected_digest) is not None
            and authorization.final_manifest_digest == expected_digest
            and expected_payload_digest is not None
            and _SHA256_RE.fullmatch(expected_payload) is not None
            and authorization.mutation_binding.payload_digest == expected_payload
            and not authorization.consumption.consumed_once()
        ):
            return authorization
        raise ProtectedRepoGuardError(
            f"{method} against protected repository {repository_id!r} must enter "
            f"{CANONICAL_RUNTIME}.authorize_and_mutate_canonical"
        )

    def assert_consumed(authorization: Any) -> None:
        if (
            type(authorization) is not CanonicalRuntimeAuthorization
            or authorization.seal is not authority_seal
            or not authorization.consumption.consumed_once()
        ):
            raise ProtectedRepoGuardError(
                "canonical runtime executor returned without consuming its mutation authority"
            )

    def attest_prepared_write_edge(authorization: Any, caller: Any) -> None:
        """Require the exact prepared call directly inside the anchored authorizer.

        The authorization class, its seal, and its ContextVar are deliberately
        not treated as secrets.  Even if all three are recovered through Python
        closure introspection, only the source-anchored two-stage executor may
        consume authority at the network-write edge.
        """

        anchor = _require_runtime_anchor()
        runtime_module, _, authorizer_code, *_ = anchor
        (
            publisher_module,
            _,
            _,
            _,
            _,
            _,
            _,
            preflight_type,
            expected_prepare,
            expected_prepare_code,
            _,
            prepared_type,
            expected_call,
            expected_call_code,
            _,
            prepared_helpers,
            publisher_source_digest,
        ) = _require_publisher_anchor()
        publisher_namespace = vars(publisher_module)
        publisher_path = expected_publisher_path
        loaded_path_text = str(publisher_namespace.get("__file__") or "").strip()
        loaded_path = Path(loaded_path_text)
        runtime_frame = getattr(caller, "f_back", None)
        try:
            valid = (
                type(authorization) is CanonicalRuntimeAuthorization
                and authorization.seal is authority_seal
                and type(authorization.preflight_executor) is preflight_type
                and type(authorization.prepared_executor) is prepared_type
                and authorization.prepare_method is expected_prepare
                and authorization.prepared_call is expected_call
                and _principal_probe_matches_anchor(
                    authorization.principal_probe,
                    authorization.preflight_executor,
                )
                and getattr(expected_prepare, "__code__", None)
                is expected_prepare_code
                and getattr(expected_call, "__code__", None)
                is expected_call_code
                and getattr(caller, "f_code", None) is expected_call_code
                and getattr(caller, "f_globals", None) is publisher_namespace
                and getattr(caller, "f_locals", {}).get("self")
                is authorization.prepared_executor
                and all(
                    getattr(caller, "f_locals", {}).get(local_name) is helper
                    for _, _, local_name, helper in prepared_helpers
                )
                and runtime_frame is not None
                and runtime_frame.f_code is authorizer_code
                and runtime_frame.f_globals is vars(runtime_module)
                and runtime_frame.f_locals.get("mutation_executor")
                is authorization.preflight_executor
                and runtime_frame.f_locals.get("prepare_method")
                is authorization.prepare_method
                and runtime_frame.f_locals.get("prepared_executor")
                is authorization.prepared_executor
                and runtime_frame.f_locals.get("prepared_call")
                is authorization.prepared_call
                and getattr(
                    runtime_frame.f_locals.get("req"),
                    "principal_probe",
                    None,
                )
                is authorization.principal_probe
                and runtime_frame.f_locals.get("final_snapshot", {}).get(
                    "principal"
                )
                == authorization.principal
                and runtime_frame.f_locals.get("final_snapshot", {}).get(
                    "principal_authority_digest"
                )
                == authorization.principal_authority_digest
                and runtime_frame.f_locals.get("final_snapshot", {}).get(
                    "credential_identity"
                )
                == authorization.credential_identity
                and runtime_frame.f_locals.get("final_snapshot", {}).get(
                    "credentials_scope"
                )
                == authorization.credentials_scope
                and runtime_frame.f_locals.get("final_snapshot", {}).get(
                    "token_env"
                )
                == authorization.token_env
                and object.__getattribute__(
                    authorization.preflight_executor,
                    "mutation_binding",
                )
                == authorization.mutation_binding
                and object.__getattribute__(
                    authorization.prepared_executor,
                    "mutation_binding",
                )
                == authorization.mutation_binding
                and bool(loaded_path_text)
                and not loaded_path.is_symlink()
                and loaded_path.is_file()
                and loaded_path.resolve() == publisher_path
                and hashlib.sha256(loaded_path.read_bytes()).hexdigest()
                == publisher_source_digest
            )
        except Exception as exc:
            raise ProtectedRepoGuardError(
                "canonical mutation did not reach the exact source-anchored "
                "prepared write edge"
            ) from exc
        finally:
            del runtime_frame
        if not valid:
            raise ProtectedRepoGuardError(
                "canonical mutation did not reach the exact source-anchored "
                "prepared write edge"
            )

    return (
        register_runtime_anchor,
        register_publisher_anchor,
        enter_authority,
        require_authority,
        assert_consumed,
        attest_prepared_write_edge,
    )


(
    _register_canonical_runtime_trust_anchor,
    _register_canonical_publisher_trust_anchor,
    _canonical_runtime_authorization,
    _authority_lookup,
    _assert_canonical_runtime_authorization_consumed,
    _attest_canonical_prepared_write_edge,
) = _build_authority_manager()


def _build_guarded_write_boundary(
    authority_lookup: Callable[..., Any],
    write_edge_attestor: Callable[[Any, Any], None],
):
    """Bind lookup privately so replacing module attributes cannot authorize."""

    protected_predicate = is_protected_repo

    def require_unprotected_or_runtime(
        repo_id: Any,
        *,
        method: str,
        expected_phase: str | None = None,
        expected_operation: str | None = None,
        expected_manifest_digest: str | None = None,
        expected_payload_digest: str | None = None,
        runtime_authorized: Any = None,
    ) -> Any | None:
        if not protected_predicate(repo_id):
            return None
        if runtime_authorized is not None:
            raise ProtectedRepoGuardError(
                "caller-supplied runtime_authorized booleans cannot authorize a "
                "protected repository mutation"
            )
        return authority_lookup(
            repository_id=str(repo_id).strip(),
            method=method,
            expected_phase=expected_phase,
            expected_operation=expected_operation,
            expected_manifest_digest=expected_manifest_digest,
            expected_payload_digest=expected_payload_digest,
        )

    def guarded_write(
        repo_id: Any,
        method: str,
        callback: Callable[[], Any],
        *,
        expected_phase: str | None = None,
        expected_operation: str | None = None,
        expected_manifest_digest: str | None = None,
        expected_payload_digest: str | None = None,
        runtime_authorized: Any = None,
    ) -> Any:
        if not callable(callback):
            raise ProtectedRepoGuardError("guarded_write callback must be callable")
        caller = sys._getframe(1)
        try:
            authorization = require_unprotected_or_runtime(
                repo_id,
                method=method,
                expected_phase=expected_phase,
                expected_operation=expected_operation,
                expected_manifest_digest=expected_manifest_digest,
                expected_payload_digest=expected_payload_digest,
                runtime_authorized=runtime_authorized,
            )
            if authorization is not None:
                write_edge_attestor(authorization, caller)
                authorization.consumption.consume()
        finally:
            del caller
        return callback()

    return require_unprotected_or_runtime, guarded_write


require_unprotected_or_runtime, guarded_write = _build_guarded_write_boundary(
    _authority_lookup,
    _attest_canonical_prepared_write_edge,
)
del _attest_canonical_prepared_write_edge, _authority_lookup


def inspect_kwargs_repo_id(kwargs: Mapping[str, Any]) -> str:
    for key in (
        "repo_id",
        "repo",
        "target_repo",
        "dataset_repo_id",
        "from_id",
        "to_id",
    ):
        value = kwargs.get(key)
        if value:
            return str(value)
    return ""
