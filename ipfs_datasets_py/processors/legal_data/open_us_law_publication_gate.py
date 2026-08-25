"""Additive Dataset and Bucket publication authority (OUL-007).

Fail-closed preflight every Open US Law uploader or resolver must invoke
**before** a network mutation or before treating a remote pin as queryable:

* Dataset ``justicedao/open-us-law-sparse-graphrag`` — create or additive
  commits only.
* Bucket ``justicedao/open-us-law-bucket`` — writes only under
  ``releases/<manifest_sha256>/``. A tiny ``LATEST.json`` pointer may be
  updated last after that prefix is complete and redownload-verified.

Root overwrite, delete, force-push, history rewrite, visibility change,
mutable query pins, and pre-seal writes fail **before** any callback.

This module performs no network I/O and never reads credential values
except to refuse them on policy surfaces.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    TypeVar,
    Union,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-publication-policy-v1"
GATE_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publication-policy@1"
TASK_ID: Final = "OUL-007"
GOAL_ID: Final = "OUL-G010"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_publication_gate.py"
RELEASE_MODE: Final = "additive"

AUTHORIZED_DATASET_REPO_ID: Final = "justicedao/open-us-law-sparse-graphrag"
AUTHORIZED_BUCKET_ID: Final = "justicedao/open-us-law-bucket"
BUCKET_RELEASE_PREFIX_TEMPLATE: Final = "releases/<manifest_sha256>/"
BUCKET_POINTER_PATH: Final = "LATEST.json"
DATASET_QUERY_IDENTITY: Final = "exact_40_hex_commit"
BUCKET_QUERY_IDENTITY: Final = BUCKET_RELEASE_PREFIX_TEMPLATE

DEFAULT_POLICY_SCHEMA_RELATIVE_PATH: Final = Path(
    "data/legal/open_us_law/publication_policy.schema.json"
)

GENERATED_WORK_TASK_NUMBER_FLOOR: Final = 49
TERMINAL_TASK_STATUSES: Final = frozenset({"completed"})
NONTERMINAL_TASK_STATUSES: Final = frozenset(
    {
        "todo",
        "in_progress",
        "blocked",
        "waiting",
        "ready",
        "parked",
        "failed",
        "externally_reserved",
    }
)

SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
)

CREDENTIALS_SCOPE_PREFIX: Final = "dataset:write:"
BUCKET_CREDENTIALS_SCOPE_PREFIX: Final = "bucket:write:"

PUBLICATION_GOAL_ROOTS: Final = (
    "OUL-G000",
    "OUL-G010",
    "OUL-G020",
    "OUL-G021",
    "OUL-G022",
    "OUL-G023",
    "OUL-G024",
    "OUL-G030",
    "OUL-G040",
    "OUL-G050",
    "OUL-G060",
    "OUL-G070",
    "OUL-G080",
    "OUL-G090",
)

AUTHORIZED_OPERATIONS: Final = frozenset(
    {
        "dataset_create",
        "dataset_additive_commit",
        "bucket_release_prefix_write",
        "bucket_pointer_update_last",
    }
)

QUERY_OPERATIONS: Final = frozenset({"dataset_query", "bucket_query"})

FORBIDDEN_OPERATIONS: Final = frozenset(
    {
        "delete",
        "delete_file",
        "delete_folder",
        "deletefile",
        "deletefolder",
        "force_push",
        "force-push",
        "history_rewrite",
        "history-rewrite",
        "super_squash_history",
        "visibility_change",
        "visibility-change",
        "root_overwrite",
        "overwrite_legacy",
        "overwrite-legacy",
        "overwrite_raw_root",
        "sync_delete",
        "sync-delete",
        "move",
        "copy",
        "rewrite_main",
        "rewrite-main",
        "destructive_upload",
        "replace_all",
        "truncate",
        "rotate_credentials",
        "mutable_query_pin",
        "pre_seal_write",
        "pre-seal-write",
    }
)

PROTECTED_RAW_ROOT_GLOBS: Final = (
    "*.parquet",
    "SHA256SUMS.json",
    "SHA256SUMS",
    "README.md",
)

GENERATED_WORK_GUARD: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "task_number_floor": GENERATED_WORK_TASK_NUMBER_FLOOR,
        "deny_nonterminal_generated_work": True,
        "unscoped_or_unknown_goal_lineage_denies": True,
        "review_only_exemption_allowed": False,
        "terminal_statuses": sorted(TERMINAL_TASK_STATUSES),
    }
)

REQUIRED_PUBLICATION_GATES: Final = (
    "target_authority",
    "operation_authority",
    "bucket_path",
    "query_pin",
    "prepublication_seal",
    "root_preservation",
    "destructive_ops",
    "generated_work_guard",
)

SEAL_TIMING_ALLOWED: Final = frozenset(
    {"before_mutation", "pre_mutation", "sealed", "prior", "ok", ""}
)
SEAL_TIMING_DENIED: Final = frozenset(
    {"absent", "missing", "future", "after_mutation", "post_hoc", "posthoc", "post-hoc"}
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
T = TypeVar("T")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID_RE = re.compile(r"^OUL-(\d{3,})$")
_GOAL_ID_RE = re.compile(r"^OUL-G(\d{3,})$")
_REPO_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_RELEASE_PREFIX_RE = re.compile(r"^releases/([0-9a-f]{64})(?:/(.*))?$")
_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key)s?$",
    re.IGNORECASE,
)
_MUTABLE_REVISION_RE = re.compile(
    r"^(?:latest|main|master|head|tip|trunk|default|current|live|prod|"
    r"production|staging|dev|develop|development|nightly|canary|"
    r"origin/.*|refs/.*|latest\.json|LATEST\.json)$",
    re.IGNORECASE,
)
_HF_DATASET_URI_RE = re.compile(
    r"^hf://(?:datasets/)?(?P<repo>[^/@#]+)(?:@(?P<rev>[^/#]+))?(?:/(?P<path>.*))?$",
    re.IGNORECASE,
)
_HF_BUCKET_URI_RE = re.compile(
    r"^hf://buckets/(?P<bucket>[^/]+)(?:/(?P<path>.*))?$",
    re.IGNORECASE,
)
_REDACTION_PLACEHOLDER: Final = "[REDACTED]"
_ALLOWED_POLICY_TOKEN_KEYS: Final = frozenset(
    {
        "credentials_scope",
        "credentials_environment_only",
        "secret_redaction_required",
        "secret_redacted",
        "authorization_status",
        "authorization_receipt_id",
        "mutation_requires_authorization",
        "credential_identity",
        "publication_authorization_required",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicationGateError(ValueError):
    """Base error for Open US Law publication-gate failures."""

    code: str = "publication_gate_error"


class PolicySchemaError(PublicationGateError):
    """Raised when the sealed publication policy or its schema is invalid."""

    code = "policy_schema_error"


class OperationForbiddenError(PublicationGateError):
    """Raised when the requested operation is not additive/authorized."""

    code = "operation_forbidden_error"


class TargetUnauthorizedError(PublicationGateError):
    """Raised when the dataset or bucket target is outside sealed authority."""

    code = "target_unauthorized_error"


class BucketPathError(PublicationGateError):
    """Raised when a bucket path is outside ``releases/<manifest_sha256>/``."""

    code = "bucket_path_error"


class MutableQueryPinError(PublicationGateError):
    """Raised when a query pin is mutable (``latest``, ``main``, pointer)."""

    code = "mutable_query_pin_error"


class PreSealWriteError(PublicationGateError):
    """Raised when a mutation is attempted without a prior seal."""

    code = "pre_seal_write_error"


class RootOverwriteError(PublicationGateError):
    """Raised when a write would overwrite raw bucket-root objects."""

    code = "root_overwrite_error"


class CredentialMismatchError(PublicationGateError):
    """Raised when credential scope/identity does not match the target."""

    code = "credential_mismatch_error"


class GeneratedWorkGuardError(PublicationGateError):
    """Raised when nonterminal generated refill work blocks publication."""

    code = "generated_work_guard_error"


class PublicationGateDeniedError(PublicationGateError):
    """Raised when :func:`require_publication_gate` fails closed."""

    code = "publication_gate_denied"

    def __init__(
        self,
        message: str,
        *,
        reason_codes: Sequence[str] = (),
        decision: Optional["PublicationGateDecision"] = None,
    ) -> None:
        super().__init__(message)
        self.reason_codes = tuple(reason_codes)
        self.decision = decision


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PublicationPhase(str, Enum):
    """Publication phase for a mutation or query-pin check."""

    STAGING = "staging"
    PUBLIC = "public"
    QUERY = "query"

    @classmethod
    def coerce(cls, value: Any) -> "PublicationPhase":
        if isinstance(value, PublicationPhase):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "stage": cls.STAGING,
            "additive_staging_upload": cls.STAGING,
            "staging_upload": cls.STAGING,
            "main": cls.PUBLIC,
            "production": cls.PUBLIC,
            "additive_main_upload": cls.PUBLIC,
            "public_upload": cls.PUBLIC,
            "main_upload": cls.PUBLIC,
            "pin": cls.QUERY,
            "resolve": cls.QUERY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise PublicationGateError(f"unknown publication phase: {value!r}")


class PublicationOperation(str, Enum):
    """Authorized additive mutations and immutable query operations."""

    DATASET_CREATE = "dataset_create"
    DATASET_ADDITIVE_COMMIT = "dataset_additive_commit"
    BUCKET_RELEASE_PREFIX_WRITE = "bucket_release_prefix_write"
    BUCKET_POINTER_UPDATE_LAST = "bucket_pointer_update_last"
    DATASET_QUERY = "dataset_query"
    BUCKET_QUERY = "bucket_query"

    @classmethod
    def coerce(cls, value: Any) -> "PublicationOperation":
        if isinstance(value, PublicationOperation):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        if _is_forbidden_operation_text(text):
            raise OperationForbiddenError(
                f"operation is forbidden for Open US Law publication: {value!r}"
            )
        aliases = {
            "create": cls.DATASET_CREATE,
            "create_dataset": cls.DATASET_CREATE,
            "dataset_creation": cls.DATASET_CREATE,
            "additive_commit": cls.DATASET_ADDITIVE_COMMIT,
            "additive_dataset_commit": cls.DATASET_ADDITIVE_COMMIT,
            "commit": cls.DATASET_ADDITIVE_COMMIT,
            "additive_main_upload": cls.DATASET_ADDITIVE_COMMIT,
            "additive_staging_upload": cls.DATASET_ADDITIVE_COMMIT,
            "bucket_write": cls.BUCKET_RELEASE_PREFIX_WRITE,
            "bucket_prefix_write": cls.BUCKET_RELEASE_PREFIX_WRITE,
            "release_prefix_write": cls.BUCKET_RELEASE_PREFIX_WRITE,
            "pointer": cls.BUCKET_POINTER_UPDATE_LAST,
            "pointer_update": cls.BUCKET_POINTER_UPDATE_LAST,
            "update_pointer": cls.BUCKET_POINTER_UPDATE_LAST,
            "latest_pointer": cls.BUCKET_POINTER_UPDATE_LAST,
            "query": cls.DATASET_QUERY,
            "dataset_pin": cls.DATASET_QUERY,
            "bucket_pin": cls.BUCKET_QUERY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OperationForbiddenError(f"unknown publication operation: {value!r}")

    @property
    def is_mutation(self) -> bool:
        return self.value in AUTHORIZED_OPERATIONS

    @property
    def is_bucket(self) -> bool:
        return self in {
            PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE,
            PublicationOperation.BUCKET_POINTER_UPDATE_LAST,
            PublicationOperation.BUCKET_QUERY,
        }

    @property
    def is_dataset(self) -> bool:
        return self in {
            PublicationOperation.DATASET_CREATE,
            PublicationOperation.DATASET_ADDITIVE_COMMIT,
            PublicationOperation.DATASET_QUERY,
        }


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _is_forbidden_operation_text(text: str) -> bool:
    folded = text.replace("-", "_")
    if folded in FORBIDDEN_OPERATIONS or text in FORBIDDEN_OPERATIONS:
        return True
    if folded.startswith("delete") or "force" in folded:
        return True
    if "visibility" in folded:
        return True
    if "history" in folded and "rewrite" in folded:
        return True
    if "overwrite" in folded and any(
        token in folded for token in ("root", "raw", "legacy")
    ):
        return True
    if folded in {"sync_delete", "pre_seal_write", "mutable_query_pin"}:
        return True
    return False


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicationGateError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PublicationGateError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise PublicationGateError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise PublicationGateError(f"{name} must be a boolean")
    return value


def repository_root() -> Path:
    """Return the repository root that contains ``data/legal``."""

    return Path(__file__).resolve().parents[3]


def publication_policy_schema_path(repo_root: Optional[PathLike] = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_POLICY_SCHEMA_RELATIVE_PATH).resolve()


def normalize_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = _require_non_empty_str(value, name, maximum=200)
    if text.lower().startswith("hf://datasets/"):
        text = text[len("hf://datasets/") :]
    elif text.lower().startswith("hf://buckets/"):
        text = text[len("hf://buckets/") :]
    text = text.split("@", 1)[0].split("#", 1)[0].strip("/")
    if not _REPO_ID_RE.fullmatch(text):
        raise TargetUnauthorizedError(f"{name} must look like org/name, got {value!r}")
    return text


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name, maximum=80).casefold()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_RE.fullmatch(text):
        raise PublicationGateError(
            f"{name} must be a 64-character lowercase hex digest"
        )
    return text


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    text = _require_non_empty_str(value, name, maximum=220)
    lowered = text.casefold()
    if lowered.startswith("sha256:"):
        digest = normalize_sha256(text, name=name)
        raise MutableQueryPinError(
            f"{name} must be a 40-character commit SHA for dataset queries, "
            f"not a content digest ({digest})"
        )
    if _MUTABLE_REVISION_RE.fullmatch(lowered) or lowered in {
        "latest.json",
        "latest",
        bucket_pointer_path().casefold(),
    }:
        raise MutableQueryPinError(
            f"{name} must be an immutable 40-hex commit, not a mutable pin "
            f"({value!r})"
        )
    folded = lowered
    if not _GIT_SHA_RE.fullmatch(folded):
        raise MutableQueryPinError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return folded


def is_immutable_revision(value: Any) -> bool:
    try:
        require_immutable_revision(value)
        return True
    except PublicationGateError:
        return False


def bucket_pointer_path() -> str:
    return BUCKET_POINTER_PATH


def normalize_posix_path(value: Any, *, name: str = "object_path") -> str:
    text = _require_non_empty_str(value, name, maximum=1024)
    if "\\" in text:
        raise BucketPathError(f"{name} must use POSIX separators")
    if text.startswith("hf://"):
        match = _HF_BUCKET_URI_RE.fullmatch(text)
        if match is None or not match.group("path"):
            raise BucketPathError(f"{name} is not a bucket object URI: {value!r}")
        text = match.group("path")
    text = text.lstrip("/")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise BucketPathError(
            f"{name} must be a normalized root-relative POSIX path, got {value!r}"
        )
    if parsed.as_posix() != text.rstrip("/"):
        # Allow a single trailing slash on directory prefixes.
        if not (text.endswith("/") and parsed.as_posix() + "/" == text):
            raise BucketPathError(f"{name} is not a normalized POSIX path: {value!r}")
    return text


def parse_release_prefix_path(
    value: Any, *, name: str = "object_path"
) -> tuple[str, str]:
    """Return ``(manifest_sha256, relative_suffix)`` for a release-prefix path."""

    text = normalize_posix_path(value, name=name)
    match = _RELEASE_PREFIX_RE.fullmatch(text.rstrip("/")) if text.endswith("/") else _RELEASE_PREFIX_RE.fullmatch(text)
    if match is None:
        # Directory form ``releases/<sha256>/``.
        match = _RELEASE_PREFIX_RE.fullmatch(text.rstrip("/"))
    if match is None:
        raise BucketPathError(
            f"{name} must be under {BUCKET_RELEASE_PREFIX_TEMPLATE}, got {value!r}"
        )
    digest = match.group(1)
    suffix = match.group(2) or ""
    return digest, suffix


def release_prefix_for(manifest_sha256: str) -> str:
    digest = normalize_sha256(manifest_sha256, name="manifest_sha256")
    return f"releases/{digest}/"


def is_protected_raw_root_path(path: str) -> bool:
    text = path.strip().lstrip("/")
    if not text or text in {".", "./"}:
        return True
    lowered = text.casefold()
    if lowered in {p.casefold() for p in PROTECTED_RAW_ROOT_GLOBS if "*" not in p}:
        return True
    if "/" not in text.rstrip("/") and text.casefold().endswith(".parquet"):
        return True
    if text.casefold().endswith(".parquet") and not text.startswith("releases/"):
        return True
    if lowered in {"sha256sums.json", "sha256sums", "readme.md", "readme.md.lfs"}:
        return True
    return False


def credentials_scope_for(
    *,
    dataset_repo_id: Optional[str] = None,
    bucket_id: Optional[str] = None,
) -> str:
    if bucket_id:
        return f"{BUCKET_CREDENTIALS_SCOPE_PREFIX}{normalize_repo_id(bucket_id, name='bucket_id')}"
    repo = normalize_repo_id(
        dataset_repo_id or AUTHORIZED_DATASET_REPO_ID, name="dataset_repo_id"
    )
    return f"{CREDENTIALS_SCOPE_PREFIX}{repo}"


def normalize_operation(value: Any) -> str:
    return PublicationOperation.coerce(value).value


def task_number(task_id: str) -> int:
    match = _TASK_ID_RE.fullmatch(str(task_id or "").strip())
    if not match:
        raise PublicationGateError(f"invalid task id: {task_id!r}")
    return int(match.group(1))


def digest_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(
    value: Any,
    *,
    label: str = "payload",
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Fail closed when tokens or credential-like values appear."""

    env = environ if environ is not None else {}
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    if key_text.casefold() in _ALLOWED_POLICY_TOKEN_KEYS:
                        visit(child, child_path)
                        continue
                    offenders.append(child_path)
                    continue
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            if "bearer " in lowered:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = env.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise CredentialMismatchError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


# ---------------------------------------------------------------------------
# Generated-work guard
# ---------------------------------------------------------------------------


def goal_parent_lineage_intersects(
    goal_id: str,
    roots: Iterable[str],
    goal_parents: Mapping[str, Iterable[str]],
) -> bool:
    wanted = {str(root) for root in roots}
    if not goal_id:
        return False
    pending = [str(goal_id)]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in wanted:
            return True
        pending.extend(str(parent) for parent in goal_parents.get(current, ()))
    return False


def find_publication_blocking_generated_work(
    *,
    task_statuses: Mapping[str, Any],
    task_goal_ids: Mapping[str, str],
    goal_parents: Mapping[str, Iterable[str]],
    task_number_floor: int = GENERATED_WORK_TASK_NUMBER_FLOOR,
) -> tuple[str, ...]:
    """Return nonterminal generated tasks that block publication."""

    roots = set(PUBLICATION_GOAL_ROOTS)
    blockers: list[str] = []
    for raw_task_id, raw_status in task_statuses.items():
        task_id = str(raw_task_id)
        try:
            number = task_number(task_id)
        except PublicationGateError:
            continue
        if number < task_number_floor:
            continue
        status = str(raw_status or "").strip().lower()
        if status in TERMINAL_TASK_STATUSES:
            continue
        goal_id = str(task_goal_ids.get(task_id, "") or "")
        if not goal_id:
            blockers.append(task_id)
            continue
        if goal_parent_lineage_intersects(goal_id, roots, goal_parents):
            blockers.append(task_id)
            continue
        if not goal_parent_lineage_intersects(goal_id, roots, goal_parents):
            # Unknown/unscoped lineage denies every publication phase.
            blockers.append(task_id)
    return tuple(sorted(set(blockers)))


# ---------------------------------------------------------------------------
# Policy document
# ---------------------------------------------------------------------------


def sealed_publication_policy() -> dict[str, Any]:
    """Return the sealed additive Dataset/Bucket publication policy."""

    return {
        "schema": GATE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "release_mode": RELEASE_MODE,
        "authorized_dataset": AUTHORIZED_DATASET_REPO_ID,
        "authorized_bucket": AUTHORIZED_BUCKET_ID,
        "dataset_creation_authorized": True,
        "dataset_additive_commits_authorized": True,
        "bucket_release_prefix_writes_authorized": True,
        "bucket_prefix_template": BUCKET_RELEASE_PREFIX_TEMPLATE,
        "bucket_pointer_updated_last": True,
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_raw_root_overwrite_allowed": False,
        "deletion_allowed": False,
        "force_push_allowed": False,
        "history_rewrite_allowed": False,
        "visibility_change_allowed": False,
        "mutable_query_pins_allowed": False,
        "pre_seal_writes_allowed": False,
        "dataset_query_identity": DATASET_QUERY_IDENTITY,
        "bucket_query_identity": BUCKET_QUERY_IDENTITY,
        "prepublication_seal_required_for_public": True,
        "staging_does_not_require_public_seal": True,
        "callback_requires_authorization": True,
        "credentials_environment_only": True,
        "secret_redaction_required": True,
        "authorized_operations": sorted(AUTHORIZED_OPERATIONS),
        "query_operations": sorted(QUERY_OPERATIONS),
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "required_gates": list(REQUIRED_PUBLICATION_GATES),
        "generated_work_guard": dict(GENERATED_WORK_GUARD),
        "protected_raw_root_globs": list(PROTECTED_RAW_ROOT_GLOBS),
    }


@lru_cache(maxsize=1)
def load_publication_policy_schema(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    schema_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else publication_policy_schema_path()
    )
    if not schema_path.is_file():
        raise PolicySchemaError(f"publication policy schema missing: {schema_path}")
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PolicySchemaError(f"invalid publication policy schema JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicySchemaError("publication policy schema root must be a JSON object")
    if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise PolicySchemaError("publication policy schema must declare JSON Schema 2020-12")
    if payload.get("title") != "Open US Law additive Dataset and Bucket publication policy":
        raise PolicySchemaError("publication policy schema title is not the sealed OUL title")
    return payload


def validate_publication_policy(
    policy: Mapping[str, Any],
    *,
    schema: Optional[Mapping[str, Any]] = None,
) -> None:
    """Validate *policy* against the sealed JSON Schema."""

    if not isinstance(policy, Mapping):
        raise PolicySchemaError("publication policy must be a mapping")
    resolved = schema if schema is not None else load_publication_policy_schema()
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError, ValidationError
    except ImportError as exc:  # pragma: no cover - validation env ships jsonschema
        raise PolicySchemaError(
            "jsonschema is required to validate publication_policy.schema.json"
        ) from exc
    try:
        Draft202012Validator.check_schema(resolved)
        Draft202012Validator(resolved).validate(dict(policy))
    except SchemaError as exc:
        raise PolicySchemaError(f"publication policy schema itself is invalid: {exc}") from exc
    except ValidationError as exc:
        raise PolicySchemaError(
            f"publication policy failed schema validation: {exc.message}"
        ) from exc


def clear_policy_schema_cache() -> None:
    load_publication_policy_schema.cache_clear()


# ---------------------------------------------------------------------------
# Request / decision models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Inputs evaluated before any live Hub mutation or query pin use."""

    phase: str
    operation: str
    dataset_repo_id: str = AUTHORIZED_DATASET_REPO_ID
    bucket_id: str = AUTHORIZED_BUCKET_ID
    object_path: Optional[str] = None
    final_manifest_digest: Optional[str] = None
    query_revision: Optional[str] = None
    query_bucket_prefix: Optional[str] = None
    prepublication_seal: Optional[Mapping[str, Any]] = None
    authorize_mutation: bool = False
    sealed: bool = False
    overwrite_raw_root: bool = False
    overwrite_existing_prefix: bool = False
    delete_requested: bool = False
    force_push: bool = False
    history_rewrite: bool = False
    visibility_change: bool = False
    visibility: Optional[str] = None
    prefix_complete: bool = False
    prefix_redownload_verified: bool = False
    pointer_updated_last: bool = False
    credentials_environment_only: bool = True
    secret_redacted: bool = True
    credentials_scope: Optional[str] = None
    credential_identity: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    argv: tuple[str, ...] = ()
    task_statuses: Mapping[str, str] = field(default_factory=dict)
    task_goal_ids: Mapping[str, str] = field(default_factory=dict)
    goal_parents: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        phase = PublicationPhase.coerce(self.phase)
        object.__setattr__(self, "phase", phase.value)
        op = PublicationOperation.coerce(self.operation)
        object.__setattr__(self, "operation", op.value)
        object.__setattr__(
            self,
            "dataset_repo_id",
            normalize_repo_id(self.dataset_repo_id, name="dataset_repo_id"),
        )
        object.__setattr__(
            self, "bucket_id", normalize_repo_id(self.bucket_id, name="bucket_id")
        )
        object.__setattr__(
            self, "authorize_mutation", _require_bool(self.authorize_mutation, "authorize_mutation")
        )
        object.__setattr__(self, "sealed", _require_bool(self.sealed, "sealed"))
        for flag in (
            "overwrite_raw_root",
            "overwrite_existing_prefix",
            "delete_requested",
            "force_push",
            "history_rewrite",
            "visibility_change",
            "prefix_complete",
            "prefix_redownload_verified",
            "pointer_updated_last",
            "credentials_environment_only",
            "secret_redacted",
        ):
            object.__setattr__(self, flag, _require_bool(getattr(self, flag), flag))
        if self.final_manifest_digest is not None:
            object.__setattr__(
                self,
                "final_manifest_digest",
                normalize_sha256(self.final_manifest_digest, name="final_manifest_digest"),
            )
        if self.object_path is not None:
            object.__setattr__(
                self,
                "object_path",
                normalize_posix_path(self.object_path, name="object_path"),
            )
        if self.query_revision is not None:
            # Store raw; query_pin gate applies the immutable-commit rule.
            object.__setattr__(
                self,
                "query_revision",
                _require_non_empty_str(self.query_revision, "query_revision", maximum=220),
            )
        if self.query_bucket_prefix is not None:
            object.__setattr__(
                self,
                "query_bucket_prefix",
                normalize_posix_path(
                    self.query_bucket_prefix, name="query_bucket_prefix"
                ),
            )
        if self.visibility is not None:
            object.__setattr__(
                self,
                "visibility",
                _require_non_empty_str(self.visibility, "visibility", maximum=32).lower(),
            )
        if self.credentials_scope is not None:
            object.__setattr__(
                self,
                "credentials_scope",
                _require_non_empty_str(self.credentials_scope, "credentials_scope", maximum=300),
            )
        if self.credential_identity is not None:
            object.__setattr__(
                self,
                "credential_identity",
                _require_non_empty_str(
                    self.credential_identity, "credential_identity", maximum=300
                ),
            )
        if self.prepublication_seal is not None:
            if not isinstance(self.prepublication_seal, Mapping):
                raise PreSealWriteError("prepublication_seal must be a mapping")
            object.__setattr__(
                self, "prepublication_seal", MappingProxyType(dict(self.prepublication_seal))
            )
        if not isinstance(self.payload, Mapping):
            raise PublicationGateError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        object.__setattr__(
            self,
            "task_statuses",
            MappingProxyType({str(k): str(v) for k, v in dict(self.task_statuses).items()}),
        )
        object.__setattr__(
            self,
            "task_goal_ids",
            MappingProxyType({str(k): str(v) for k, v in dict(self.task_goal_ids).items()}),
        )
        object.__setattr__(
            self,
            "goal_parents",
            MappingProxyType(
                {
                    str(k): tuple(str(p) for p in v)
                    for k, v in dict(self.goal_parents).items()
                }
            ),
        )

    @property
    def operation_enum(self) -> PublicationOperation:
        return PublicationOperation.coerce(self.operation)

    @property
    def phase_enum(self) -> PublicationPhase:
        return PublicationPhase.coerce(self.phase)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PublicationRequest":
        if not isinstance(value, Mapping):
            raise PublicationGateError("publication request must be a mapping")
        return cls(
            phase=value.get("phase", ""),
            operation=value.get("operation", ""),
            dataset_repo_id=value.get("dataset_repo_id", AUTHORIZED_DATASET_REPO_ID),
            bucket_id=value.get("bucket_id", AUTHORIZED_BUCKET_ID),
            object_path=value.get("object_path"),
            final_manifest_digest=value.get("final_manifest_digest"),
            query_revision=value.get("query_revision") or value.get("revision"),
            query_bucket_prefix=value.get("query_bucket_prefix")
            or value.get("bucket_prefix"),
            prepublication_seal=value.get("prepublication_seal"),
            authorize_mutation=value.get("authorize_mutation", False),
            sealed=value.get("sealed", False),
            overwrite_raw_root=value.get("overwrite_raw_root", False),
            overwrite_existing_prefix=value.get("overwrite_existing_prefix", False),
            delete_requested=value.get("delete_requested", False)
            or value.get("delete", False),
            force_push=value.get("force_push", False),
            history_rewrite=value.get("history_rewrite", False),
            visibility_change=value.get("visibility_change", False),
            visibility=value.get("visibility"),
            prefix_complete=value.get("prefix_complete", False),
            prefix_redownload_verified=value.get("prefix_redownload_verified", False),
            pointer_updated_last=value.get("pointer_updated_last", False),
            credentials_environment_only=value.get(
                "credentials_environment_only", True
            ),
            secret_redacted=value.get("secret_redacted", True),
            credentials_scope=value.get("credentials_scope"),
            credential_identity=value.get("credential_identity"),
            payload=value.get("payload") or {},
            argv=tuple(value.get("argv") or ()),
            task_statuses=value.get("task_statuses") or {},
            task_goal_ids=value.get("task_goal_ids") or {},
            goal_parents=value.get("goal_parents") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorize_mutation": self.authorize_mutation,
            "argv": list(self.argv),
            "bucket_id": self.bucket_id,
            "credential_identity": self.credential_identity,
            "credentials_environment_only": self.credentials_environment_only,
            "credentials_scope": self.credentials_scope,
            "dataset_repo_id": self.dataset_repo_id,
            "delete_requested": self.delete_requested,
            "final_manifest_digest": self.final_manifest_digest,
            "force_push": self.force_push,
            "goal_parents": {k: list(v) for k, v in self.goal_parents.items()},
            "history_rewrite": self.history_rewrite,
            "object_path": self.object_path,
            "operation": self.operation,
            "overwrite_existing_prefix": self.overwrite_existing_prefix,
            "overwrite_raw_root": self.overwrite_raw_root,
            "payload": dict(self.payload),
            "phase": self.phase,
            "pointer_updated_last": self.pointer_updated_last,
            "prefix_complete": self.prefix_complete,
            "prefix_redownload_verified": self.prefix_redownload_verified,
            "prepublication_seal": (
                dict(self.prepublication_seal)
                if self.prepublication_seal is not None
                else None
            ),
            "query_bucket_prefix": self.query_bucket_prefix,
            "query_revision": self.query_revision,
            "sealed": self.sealed,
            "secret_redacted": self.secret_redacted,
            "task_goal_ids": dict(self.task_goal_ids),
            "task_statuses": dict(self.task_statuses),
            "visibility": self.visibility,
            "visibility_change": self.visibility_change,
        }


@dataclass(frozen=True, slots=True)
class PublicationGateDecision:
    """Fail-closed decision for a publication-gate request."""

    authorized: bool
    phase: str
    operation: str
    dataset_repo_id: str
    bucket_id: str
    reason_codes: tuple[str, ...]
    passed_gates: tuple[str, ...]
    required_gates: tuple[str, ...]
    final_manifest_digest: str = ""
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    network_mutation_permitted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorized", _require_bool(self.authorized, "authorized"))
        object.__setattr__(
            self,
            "network_mutation_permitted",
            _require_bool(self.network_mutation_permitted, "network_mutation_permitted"),
        )
        if not self.authorized:
            object.__setattr__(self, "network_mutation_permitted", False)
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "passed_gates", tuple(self.passed_gates))
        object.__setattr__(self, "required_gates", tuple(self.required_gates))
        if not isinstance(self.details, Mapping):
            raise PublicationGateError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "bucket_id": self.bucket_id,
            "dataset_repo_id": self.dataset_repo_id,
            "details": dict(self.details),
            "final_manifest_digest": self.final_manifest_digest,
            "message": self.message,
            "network_mutation_permitted": self.network_mutation_permitted,
            "operation": self.operation,
            "passed_gates": list(self.passed_gates),
            "phase": self.phase,
            "reason_codes": list(self.reason_codes),
            "required_gates": list(self.required_gates),
            "schema": GATE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }

    def require_authorized(self) -> "PublicationGateDecision":
        if not self.authorized:
            raise PublicationGateDeniedError(
                self.message
                or (
                    "publication gate denied: "
                    + ", ".join(self.reason_codes or ("policy.denied",))
                ),
                reason_codes=self.reason_codes,
                decision=self,
            )
        return self


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------


def check_target_authority(request: PublicationRequest) -> None:
    op = request.operation_enum
    if op.is_dataset and request.dataset_repo_id != AUTHORIZED_DATASET_REPO_ID:
        raise TargetUnauthorizedError(
            f"dataset target {request.dataset_repo_id!r} is not authorized; "
            f"only {AUTHORIZED_DATASET_REPO_ID!r} may be created or committed"
        )
    if op.is_bucket and request.bucket_id != AUTHORIZED_BUCKET_ID:
        raise TargetUnauthorizedError(
            f"bucket target {request.bucket_id!r} is not authorized; "
            f"only {AUTHORIZED_BUCKET_ID!r} may receive release-prefix writes"
        )
    if request.dataset_repo_id != AUTHORIZED_DATASET_REPO_ID:
        raise TargetUnauthorizedError(
            f"dataset_repo_id must remain {AUTHORIZED_DATASET_REPO_ID!r}"
        )
    if request.bucket_id != AUTHORIZED_BUCKET_ID:
        raise TargetUnauthorizedError(
            f"bucket_id must remain {AUTHORIZED_BUCKET_ID!r}"
        )


def check_operation_authority(request: PublicationRequest) -> None:
    op = request.operation_enum
    if op.is_mutation:
        if op.value not in AUTHORIZED_OPERATIONS:
            raise OperationForbiddenError(
                f"operation {op.value!r} is not an authorized additive mutation"
            )
        if not request.authorize_mutation:
            raise OperationForbiddenError(
                "authorize_mutation must be true before any network mutation"
            )
        if op is PublicationOperation.BUCKET_POINTER_UPDATE_LAST:
            if request.phase_enum is not PublicationPhase.PUBLIC:
                raise OperationForbiddenError(
                    "bucket pointer update is authorized only for the public phase"
                )
            if not request.prefix_complete or not request.prefix_redownload_verified:
                raise OperationForbiddenError(
                    "LATEST.json may be updated only after the release prefix is "
                    "complete and redownload-verified"
                )
            if not request.pointer_updated_last:
                raise OperationForbiddenError(
                    "pointer_updated_last must be true; the pointer is written last"
                )
    elif op.value not in QUERY_OPERATIONS:
        raise OperationForbiddenError(f"operation {op.value!r} is not authorized")
    elif request.phase_enum is not PublicationPhase.QUERY:
        raise OperationForbiddenError(
            f"query operation {op.value!r} requires phase=query"
        )

    if request.credentials_environment_only is not True:
        raise CredentialMismatchError("credentials must be environment-only")
    if request.secret_redacted is not True:
        raise CredentialMismatchError("secret_redacted must be true")
    if op.is_mutation:
        expected = credentials_scope_for(
            dataset_repo_id=request.dataset_repo_id
            if op.is_dataset
            else None,
            bucket_id=request.bucket_id if op.is_bucket else None,
        )
        if request.credentials_scope is None:
            raise CredentialMismatchError(
                "credentials_scope is required and must match the write target"
            )
        if request.credentials_scope != expected:
            raise CredentialMismatchError(
                f"credentials_scope {request.credentials_scope!r} does not match "
                f"target scope {expected!r}"
            )
        if request.credential_identity is not None:
            identity = request.credential_identity
            target = request.bucket_id if op.is_bucket else request.dataset_repo_id
            if target not in identity and expected not in identity:
                raise CredentialMismatchError(
                    "credential_identity does not match the authorized write target"
                )
    reject_credentials_in_payload(request.payload, label="gate_request.payload")
    reject_credentials_in_payload(request.to_dict(), label="gate_request")


def check_bucket_path(request: PublicationRequest) -> None:
    op = request.operation_enum
    if op is PublicationOperation.BUCKET_POINTER_UPDATE_LAST:
        path = request.object_path or BUCKET_POINTER_PATH
        if path != BUCKET_POINTER_PATH:
            raise BucketPathError(
                f"pointer update path must be {BUCKET_POINTER_PATH!r}, got {path!r}"
            )
        if request.final_manifest_digest is None:
            raise BucketPathError(
                "pointer update must bind the verified releases/<manifest_sha256>/ prefix"
            )
        return
    if op is PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE:
        if not request.object_path:
            raise BucketPathError(
                "bucket release-prefix write requires object_path under "
                f"{BUCKET_RELEASE_PREFIX_TEMPLATE}"
            )
        digest, _suffix = parse_release_prefix_path(request.object_path)
        if request.final_manifest_digest and digest != request.final_manifest_digest:
            raise BucketPathError(
                f"object_path digest {digest!r} drifts from final_manifest_digest "
                f"{request.final_manifest_digest!r}"
            )
        return
    if op is PublicationOperation.BUCKET_QUERY:
        prefix = request.query_bucket_prefix or request.object_path
        if not prefix:
            raise MutableQueryPinError(
                "bucket query requires releases/<manifest_sha256>/ "
                "(query_bucket_prefix or object_path)"
            )
        parse_release_prefix_path(prefix, name="query_bucket_prefix")
        return
    if request.object_path:
        # Dataset operations must not smuggle a raw bucket overwrite path.
        if is_protected_raw_root_path(request.object_path):
            raise RootOverwriteError(
                f"dataset operation must not target protected bucket path "
                f"{request.object_path!r}"
            )


def check_query_pin(request: PublicationRequest) -> None:
    op = request.operation_enum
    if op is PublicationOperation.DATASET_QUERY:
        if not request.query_revision:
            raise MutableQueryPinError(
                "dataset query requires an exact 40-hex commit revision"
            )
        require_immutable_revision(request.query_revision, name="query_revision")
        return
    if op is PublicationOperation.BUCKET_QUERY:
        prefix = request.query_bucket_prefix or request.object_path
        if not prefix:
            raise MutableQueryPinError(
                "bucket query requires releases/<manifest_sha256>/"
            )
        lowered = prefix.casefold().rstrip("/")
        if lowered in {"latest", "latest.json", "releases/latest"} or lowered.endswith(
            "/latest"
        ):
            raise MutableQueryPinError(
                "bucket query must not use LATEST.json or another mutable pointer"
            )
        digest, _suffix = parse_release_prefix_path(prefix, name="query_bucket_prefix")
        if request.final_manifest_digest and digest != request.final_manifest_digest:
            raise MutableQueryPinError(
                "bucket query prefix digest drifts from final_manifest_digest"
            )
        return
    if request.query_revision is not None:
        require_immutable_revision(request.query_revision, name="query_revision")
    if request.query_bucket_prefix is not None:
        parse_release_prefix_path(
            request.query_bucket_prefix, name="query_bucket_prefix"
        )


def check_prepublication_seal(request: PublicationRequest) -> None:
    op = request.operation_enum
    phase = request.phase_enum
    if not op.is_mutation:
        return
    if not request.sealed:
        raise PreSealWriteError(
            "pre-seal writes are forbidden; a sealed candidate or "
            "prepublication seal must precede mutation"
        )
    if request.final_manifest_digest is None:
        raise PreSealWriteError(
            "mutations must bind a sealed final_manifest_digest"
        )

    if phase is PublicationPhase.QUERY:
        raise PreSealWriteError("mutating operations cannot use phase=query")

    if phase is PublicationPhase.STAGING:
        seal = request.prepublication_seal
        if seal is not None:
            if seal.get("substitutes_for_phase_evidence") is True:
                raise PreSealWriteError(
                    "staging refuses a public prepublication seal as phase evidence"
                )
            if seal.get("required_for_staging") is True:
                raise PreSealWriteError(
                    "staging does not require and must not demand the public seal"
                )
            timing = str(seal.get("timing") or "").strip().lower().replace("-", "_")
            if timing in SEAL_TIMING_DENIED:
                raise PreSealWriteError(
                    f"staging refuses {timing} prepublication seal timing"
                )
        return

    if phase is not PublicationPhase.PUBLIC:
        raise PreSealWriteError(f"unsupported mutation phase: {phase.value!r}")

    seal = request.prepublication_seal
    if seal is None:
        raise PreSealWriteError(
            "public mutation requires a prepublication seal before any callback"
        )
    if seal.get("present") is False:
        raise PreSealWriteError("prepublication seal is absent")
    timing = str(
        seal.get("timing") or seal.get("seal_timing") or "before_mutation"
    ).strip().lower().replace("-", "_")
    if timing in SEAL_TIMING_DENIED:
        raise PreSealWriteError(f"public mutation refuses {timing} prepublication seal")
    if timing not in SEAL_TIMING_ALLOWED:
        raise PreSealWriteError(f"unrecognized prepublication seal timing: {timing!r}")
    if seal.get("created_after_mutation") is True or seal.get("post_hoc") is True:
        raise PreSealWriteError("public mutation refuses a post-hoc prepublication seal")
    if seal.get("future") is True or seal.get("sealed_in_future") is True:
        raise PreSealWriteError("public mutation refuses a future-dated prepublication seal")
    bound = seal.get("final_manifest_digest") or seal.get("manifest_digest")
    if bound is not None:
        bound_norm = normalize_sha256(bound, name="seal.manifest")
        if bound_norm != request.final_manifest_digest:
            raise PreSealWriteError(
                "prepublication seal manifest digest drifts from final_manifest_digest"
            )


def check_root_preservation(request: PublicationRequest) -> None:
    if request.overwrite_raw_root:
        raise RootOverwriteError("raw bucket-root overwrite is forbidden")
    if request.overwrite_existing_prefix:
        raise RootOverwriteError(
            "overwriting an existing releases/<manifest_sha256>/ prefix is forbidden"
        )
    op = request.operation_enum
    if request.object_path and is_protected_raw_root_path(request.object_path):
        if op is not PublicationOperation.BUCKET_POINTER_UPDATE_LAST:
            raise RootOverwriteError(
                f"refusing protected raw-root path {request.object_path!r}"
            )
        if request.object_path != BUCKET_POINTER_PATH:
            raise RootOverwriteError(
                f"refusing protected raw-root path {request.object_path!r}"
            )
    if op is PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE and request.object_path:
        if not request.object_path.startswith("releases/"):
            raise RootOverwriteError(
                "bucket writes outside releases/<manifest_sha256>/ are root overwrites"
            )


def check_destructive_ops(request: PublicationRequest) -> None:
    if request.delete_requested:
        raise OperationForbiddenError("delete is forbidden for Open US Law publication")
    if request.force_push:
        raise OperationForbiddenError("force-push is forbidden")
    if request.history_rewrite:
        raise OperationForbiddenError("history rewrite is forbidden")
    if request.visibility_change:
        raise OperationForbiddenError("visibility change is forbidden")
    if request.visibility is not None and request.visibility not in {"public", "unchanged"}:
        raise OperationForbiddenError(
            f"visibility {request.visibility!r} is not an authorized no-op"
        )
    if _is_forbidden_operation_text(request.operation):
        raise OperationForbiddenError(
            f"operation is forbidden for Open US Law publication: {request.operation!r}"
        )


def check_generated_work_guard(request: PublicationRequest) -> None:
    if not request.operation_enum.is_mutation:
        return
    if not request.task_statuses:
        return
    blockers = find_publication_blocking_generated_work(
        task_statuses=request.task_statuses,
        task_goal_ids=request.task_goal_ids,
        goal_parents=request.goal_parents,
    )
    if blockers:
        raise GeneratedWorkGuardError(
            "nonterminal generated work blocks publication: " + ", ".join(blockers)
        )


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------


def evaluate_publication_gate(
    request: PublicationRequest | Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationGateDecision:
    """Evaluate whether a mutation or query pin is authorized.

    Fail-closed: any missing gate produces ``authorized=False``. Does not
    perform network I/O and never returns secrets.
    """

    _ = environ
    reasons: list[str] = []
    passed: list[str] = []
    details: dict[str, Any] = {
        "task_id": TASK_ID,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "authorized_dataset": AUTHORIZED_DATASET_REPO_ID,
        "authorized_bucket": AUTHORIZED_BUCKET_ID,
        "bucket_prefix_template": BUCKET_RELEASE_PREFIX_TEMPLATE,
        "generated_work_guard": dict(GENERATED_WORK_GUARD),
    }

    try:
        req = (
            request
            if isinstance(request, PublicationRequest)
            else PublicationRequest.from_mapping(request)
        )
    except PublicationGateError as exc:
        raw_phase = "unknown"
        raw_op = "unknown"
        raw_dataset = AUTHORIZED_DATASET_REPO_ID
        raw_bucket = AUTHORIZED_BUCKET_ID
        raw_digest = ""
        if isinstance(request, Mapping):
            raw_phase = str(request.get("phase") or "unknown")
            raw_op = str(request.get("operation") or "unknown")
            raw_dataset = str(
                request.get("dataset_repo_id") or AUTHORIZED_DATASET_REPO_ID
            )
            raw_bucket = str(request.get("bucket_id") or AUTHORIZED_BUCKET_ID)
            try:
                if request.get("final_manifest_digest"):
                    raw_digest = normalize_sha256(
                        str(request.get("final_manifest_digest")),
                        name="final_manifest_digest",
                    )
            except PublicationGateError:
                raw_digest = ""
        try:
            safe_dataset = normalize_repo_id(raw_dataset, name="dataset_repo_id")
        except PublicationGateError:
            safe_dataset = AUTHORIZED_DATASET_REPO_ID
        try:
            safe_bucket = normalize_repo_id(raw_bucket, name="bucket_id")
        except PublicationGateError:
            safe_bucket = AUTHORIZED_BUCKET_ID
        return PublicationGateDecision(
            authorized=False,
            phase=raw_phase,
            operation=raw_op,
            dataset_repo_id=safe_dataset,
            bucket_id=safe_bucket,
            final_manifest_digest=raw_digest,
            reason_codes=(f"request.invalid:{exc.code}",),
            passed_gates=(),
            required_gates=REQUIRED_PUBLICATION_GATES,
            message=str(exc),
            details={"error": str(exc)},
            network_mutation_permitted=False,
        )

    gate_checks: tuple[tuple[str, Callable[[PublicationRequest], None]], ...] = (
        ("target_authority", check_target_authority),
        ("operation_authority", check_operation_authority),
        ("bucket_path", check_bucket_path),
        ("query_pin", check_query_pin),
        ("prepublication_seal", check_prepublication_seal),
        ("root_preservation", check_root_preservation),
        ("destructive_ops", check_destructive_ops),
        ("generated_work_guard", check_generated_work_guard),
    )
    for gate_name, checker in gate_checks:
        try:
            checker(req)
            passed.append(gate_name)
        except PublicationGateError as exc:
            reasons.append(f"gate.{gate_name}:{exc.code}")
            details[f"{gate_name}_error"] = str(exc)

    authorized = not reasons and set(passed) >= set(REQUIRED_PUBLICATION_GATES)
    mutation_ok = authorized and req.operation_enum.is_mutation
    if authorized:
        if mutation_ok:
            message = (
                f"publication gate authorized for {req.operation} on "
                f"{req.dataset_repo_id if req.operation_enum.is_dataset else req.bucket_id} "
                f"(phase={req.phase})"
            )
        else:
            message = (
                f"publication gate authorized immutable query pin for {req.operation}"
            )
    else:
        message = (
            "publication gate refused before network mutation: "
            + "; ".join(reasons[:10])
        )

    details["passed_gate_count"] = len(passed)
    details["required_gate_count"] = len(REQUIRED_PUBLICATION_GATES)
    details["prepublication_seal_required"] = req.phase_enum is PublicationPhase.PUBLIC
    details["operation_is_mutation"] = req.operation_enum.is_mutation
    details["release_prefix"] = (
        release_prefix_for(req.final_manifest_digest)
        if req.final_manifest_digest
        else None
    )

    decision = PublicationGateDecision(
        authorized=authorized,
        phase=req.phase,
        operation=req.operation,
        dataset_repo_id=req.dataset_repo_id,
        bucket_id=req.bucket_id,
        final_manifest_digest=req.final_manifest_digest or "",
        reason_codes=tuple(reasons),
        passed_gates=tuple(passed),
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=message,
        details=details,
        network_mutation_permitted=mutation_ok,
    )
    reject_credentials_in_payload(decision.to_dict(), label="publication_gate_decision")
    return decision


def require_publication_gate(
    request: PublicationRequest | Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> PublicationGateDecision:
    """Evaluate and raise :class:`PublicationGateDeniedError` when denied."""

    decision = evaluate_publication_gate(request, environ=environ)
    return decision.require_authorized()


def authorize_and_mutate(
    request: PublicationRequest | Mapping[str, Any],
    upload_callback: Callable[[PublicationGateDecision], T],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> T:
    """Run *upload_callback* only after the gate authorizes a mutation.

    On every denial path the callback is never invoked.
    """

    decision = require_publication_gate(request, environ=environ)
    if not decision.network_mutation_permitted:
        raise PublicationGateDeniedError(
            "network mutation not permitted",
            reason_codes=decision.reason_codes or ("network_mutation.denied",),
            decision=decision,
        )
    return upload_callback(decision)


# ---------------------------------------------------------------------------
# Example builders
# ---------------------------------------------------------------------------


def _stable_digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def example_authorized_request(
    phase: PublicationPhase | str = PublicationPhase.PUBLIC,
    operation: PublicationOperation | str = PublicationOperation.DATASET_ADDITIVE_COMMIT,
    *,
    manifest_digest: Optional[str] = None,
) -> dict[str, Any]:
    """Return a minimal mapping that passes the gate for *phase*/*operation*."""

    phase_key = PublicationPhase.coerce(phase).value
    op = PublicationOperation.coerce(operation)
    digest = manifest_digest or _stable_digest(f"manifest:{phase_key}:{op.value}")
    commit_sha = _stable_digest(f"commit:{phase_key}")[:40]
    payload: dict[str, Any] = {
        "phase": phase_key,
        "operation": op.value,
        "dataset_repo_id": AUTHORIZED_DATASET_REPO_ID,
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "final_manifest_digest": digest,
        "authorize_mutation": op.is_mutation,
        "sealed": op.is_mutation,
        "credentials_environment_only": True,
        "secret_redacted": True,
        "overwrite_raw_root": False,
        "overwrite_existing_prefix": False,
        "delete_requested": False,
        "force_push": False,
        "history_rewrite": False,
        "visibility_change": False,
        "visibility": "public",
        "payload": {
            "release_mode": RELEASE_MODE,
            "credentials_environment_only": True,
            "secret_redacted": True,
        },
        "argv": ["publish-open-us-law", "--phase", phase_key, "--authorize-mutation"],
        "task_statuses": {},
        "task_goal_ids": {},
        "goal_parents": {root: ("OUL-G000",) for root in PUBLICATION_GOAL_ROOTS},
    }
    payload["goal_parents"]["OUL-G000"] = []
    if op.is_dataset:
        payload["credentials_scope"] = credentials_scope_for(
            dataset_repo_id=AUTHORIZED_DATASET_REPO_ID
        )
        payload["credential_identity"] = f"env:{AUTHORIZED_DATASET_REPO_ID}"
    if op.is_bucket:
        payload["credentials_scope"] = credentials_scope_for(
            bucket_id=AUTHORIZED_BUCKET_ID
        )
        payload["credential_identity"] = f"env:{AUTHORIZED_BUCKET_ID}"
    if op is PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE:
        payload["object_path"] = f"releases/{digest}/manifest.json"
    if op is PublicationOperation.BUCKET_POINTER_UPDATE_LAST:
        payload["object_path"] = BUCKET_POINTER_PATH
        payload["prefix_complete"] = True
        payload["prefix_redownload_verified"] = True
        payload["pointer_updated_last"] = True
        payload["phase"] = PublicationPhase.PUBLIC.value
        phase_key = PublicationPhase.PUBLIC.value
    if op is PublicationOperation.DATASET_QUERY:
        payload["phase"] = PublicationPhase.QUERY.value
        payload["query_revision"] = commit_sha
        payload["authorize_mutation"] = False
        payload["sealed"] = False
        payload.pop("final_manifest_digest", None)
    if op is PublicationOperation.BUCKET_QUERY:
        payload["phase"] = PublicationPhase.QUERY.value
        payload["query_bucket_prefix"] = f"releases/{digest}/"
        payload["object_path"] = f"releases/{digest}/manifest.json"
        payload["authorize_mutation"] = False
        payload["sealed"] = False
    if phase_key == PublicationPhase.PUBLIC.value and op.is_mutation:
        payload["prepublication_seal"] = {
            "present": True,
            "timing": "before_mutation",
            "final_manifest_digest": digest,
        }
    return payload


def apply_denial_mutator(
    payload: Mapping[str, Any], mutator: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply a compact dotted-path mutator to a request mapping."""

    result: dict[str, Any] = json.loads(json.dumps(dict(payload)))
    for raw_key, value in mutator.items():
        if raw_key == "receipts" and isinstance(value, Mapping):
            target = result.setdefault("receipts", {})
            for path, patch in value.items():
                existing = dict(target.get(path) or {})
                existing.update(dict(patch) if isinstance(patch, Mapping) else {})
                target[path] = existing
            continue
        parts = str(raw_key).split(".")
        cursor: Any = result
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    return result


__all__ = [
    "AUTHORIZED_BUCKET_ID",
    "AUTHORIZED_DATASET_REPO_ID",
    "AUTHORIZED_OPERATIONS",
    "BUCKET_POINTER_PATH",
    "BUCKET_QUERY_IDENTITY",
    "BUCKET_RELEASE_PREFIX_TEMPLATE",
    "BucketPathError",
    "CredentialMismatchError",
    "DATASET_QUERY_IDENTITY",
    "FORBIDDEN_OPERATIONS",
    "GATE_SCHEMA",
    "GENERATED_WORK_GUARD",
    "GENERATED_WORK_TASK_NUMBER_FLOOR",
    "GOAL_ID",
    "GeneratedWorkGuardError",
    "MutableQueryPinError",
    "OperationForbiddenError",
    "POLICY_SCHEMA_VERSION",
    "PROGRAM_ID",
    "PROTECTED_RAW_ROOT_GLOBS",
    "PreSealWriteError",
    "PublicationGateDecision",
    "PublicationGateDeniedError",
    "PublicationGateError",
    "PublicationOperation",
    "PublicationPhase",
    "PublicationRequest",
    "QUERY_OPERATIONS",
    "REQUIRED_PUBLICATION_GATES",
    "RootOverwriteError",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TargetUnauthorizedError",
    "apply_denial_mutator",
    "authorize_and_mutate",
    "clear_policy_schema_cache",
    "credentials_scope_for",
    "evaluate_publication_gate",
    "example_authorized_request",
    "find_publication_blocking_generated_work",
    "is_immutable_revision",
    "is_protected_raw_root_path",
    "load_publication_policy_schema",
    "normalize_operation",
    "normalize_repo_id",
    "normalize_sha256",
    "parse_release_prefix_path",
    "publication_policy_schema_path",
    "reject_credentials_in_payload",
    "release_prefix_for",
    "require_immutable_revision",
    "require_publication_gate",
    "sealed_publication_policy",
    "validate_publication_policy",
]


# Back-compat alias used by a few call sites that say "policy schema version".
POLICY_SCHEMA_VERSION: Final = SCHEMA_VERSION
