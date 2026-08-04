"""Authenticated Hub PR staging with exact human operator approval (PATLAW-159).

Pipeline (fail-closed):

1. **plan** — enumerate only manifest-declared artifacts, bind exact base
   revisions per repository, produce a staged-diff digest (no Hub contact);
2. **stage** — create an add-only branch (never ``main``) and commit via
   injected ``create_commit`` / ``create_branch`` / ``create_pull_request``;
3. **operator approval** — a *separate* HMAC-signed
   :class:`PublicationApprovalReceipt` that binds the release root CID and
   staged-diff digest; the publisher **never** generates this material;
4. **promote** — after verifying the operator signature and re-checking base
   revisions / artifact digests, merge the staged PR to the target revision.

Missing or wrong approval, changed base, changed artifact, conflict, partial
upload, auth error, or race must not publish ``main`` or move runtime
pointers. Credentials are scoped references and never appear in receipts.

Pointer promotion / pinned redownload / rollback are owned by PATLAW-160.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.huggingface.release import (
    canonical_json_bytes,
    file_digest,
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    CANONICAL_REPOSITORY_NAMES,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
    RELEASE_MANIFEST_FILENAME,
    REPOS_DIRNAME,
)

# ---------------------------------------------------------------------------
# Constants / schemas
# ---------------------------------------------------------------------------

PUBLISHER_V2_SCHEMA: Final = "patent-legal-hf-publication-plan/v2"
STAGED_RECEIPT_SCHEMA: Final = "patent-legal-hf-staged-pr-receipt/v2"
APPROVAL_SCHEMA: Final = "patent-legal-hf-operator-approval/v2"
PROMOTION_RECEIPT_SCHEMA: Final = "patent-legal-hf-promotion-receipt/v2"
GOAL_ID: Final = "PATLAW-G182"
PROGRAM_ID: Final = "patent-legal-intelligence"
DEFAULT_TARGET_REVISION: Final = "main"
DEFAULT_BRANCH_PREFIX: Final = "stage/patent-legal"
PROHIBITED_TARGET_REVISIONS: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
    }
)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key)s?$",
    re.IGNORECASE,
)
_CREDENTIAL_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
)
_OPERATOR_KEY_ENV: Final = "PATENT_HF_OPERATOR_APPROVAL_KEY"
# Explicitly no default key material lives in this module.  Tests inject keys.
_AGENT_SELF_APPROVAL_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "implementation-agent",
        "agent-supervisor",
        "supervisor-self",
        "auto-approve",
        "unattended",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatentHFPublisherV2Error(ValueError):
    """Base error for fail-closed v2 Hub publication."""


class ApprovalError(PatentHFPublisherV2Error):
    """Missing, wrong, self-generated, or unbound operator approval."""


class BaseRevisionError(PatentHFPublisherV2Error):
    """Expected base revision mismatch or race after audit."""


class ArtifactChangedError(PatentHFPublisherV2Error):
    """Local or remote artifact digest/size no longer matches the plan."""


class ConflictError(PatentHFPublisherV2Error):
    """Branch, path, or merge conflict prevents staging/promotion."""


class PartialUploadError(PatentHFPublisherV2Error):
    """Multi-repo stage/promote aborted; main was not advanced."""


class AuthError(PatentHFPublisherV2Error):
    """Missing or rejected Hub credentials."""


class CredentialLeakError(PatentHFPublisherV2Error):
    """Credentials or key material appeared in a receipt/plan payload."""


class DirectMainUploadError(PatentHFPublisherV2Error):
    """Direct writes to main/master are prohibited; use staged PR + promote."""


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PatentHFPublisherV2Error(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise PatentHFPublisherV2Error(f"{label} must not contain NUL")
    return value


def _commit_sha(value: Any, *, label: str = "commit_sha") -> str:
    sha = _text(value, label=label).casefold()
    if not _COMMIT_SHA_RE.fullmatch(sha):
        raise PatentHFPublisherV2Error(
            f"{label} must be a 40-64 character lowercase hex commit SHA"
        )
    return sha


def _digest(value: Any, *, label: str = "sha256") -> str:
    digest = _text(value, label=label).casefold()
    if not _HASH_RE.fullmatch(digest):
        raise PatentHFPublisherV2Error(
            f"{label} must be a full lower-case 64-character hex digest"
        )
    return digest


def _normalize_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if (
        not text
        or text.startswith("/")
        or text.startswith("../")
        or "/../" in f"/{text}/"
    ):
        raise PatentHFPublisherV2Error(f"unsafe relative path: {value!r}")
    parts = Path(text).parts
    if ".." in parts or Path(text).is_absolute():
        raise PatentHFPublisherV2Error(f"unsafe relative path: {value!r}")
    return Path(*parts).as_posix()


def _dataset_id(organization: str, repository: str) -> str:
    org = _text(organization, label="organization").casefold()
    repo = _text(repository, label="repository").casefold()
    if "/" in org or "/" in repo or ".." in org or ".." in repo:
        raise PatentHFPublisherV2Error(
            f"unsafe dataset identity: {organization}/{repository}"
        )
    return f"{org}/{repo}"


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens, secrets, or credential-like keys appear."""

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) > 12:
                offenders.append(f"{path}:hf_token_like")
            if "bearer " in lowered:
                offenders.append(f"{path}:bearer")
            if lowered.startswith("pat_") and len(item) > 16:
                offenders.append(f"{path}:pat_token_like")

    visit(value, label)
    if offenders:
        raise CredentialLeakError(
            "credentials must never appear in receipts or plans: "
            + ", ".join(sorted(set(offenders)))
        )


def credentials_resolved(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    for name in _CREDENTIAL_ENV_NAMES:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return True
    return False


def resolve_hub_token(
    *,
    token: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_missing: bool = False,
) -> str | None:
    """Resolve a Hub token only from explicit argument or process environment.

    The token value is never written into plans, receipts, or logs by this
    module.  Callers must pass the resolved token into the API client only.
    """

    if token is not None:
        text = str(token).strip()
        if not text:
            if allow_missing:
                return None
            raise AuthError("Hub token is empty")
        return text
    source = env if env is not None else os.environ
    for name in _CREDENTIAL_ENV_NAMES:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if allow_missing:
        return None
    raise AuthError(
        "Hub credentials are required for authenticated stage/promote; "
        "set HF_TOKEN (or HUGGING_FACE_HUB_TOKEN) in the operator environment"
    )


def _file_sha256_hex(path: Path) -> tuple[int, str]:
    size, digest = file_digest(path)
    return int(size), digest.hex()


# ---------------------------------------------------------------------------
# Plan / receipt dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedArtifact:
    """One manifest-enumerated file planned for upload to a single repository."""

    repository: str
    dataset_id: str
    relative_path: str
    """Path relative to the local release root (may include ``repos/<name>/``)."""

    remote_path: str
    """Path inside the Hub repository (no ``repos/`` prefix)."""

    size_bytes: int
    sha256: str
    content_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository", _text(self.repository, label="repository").casefold()
        )
        object.__setattr__(
            self, "dataset_id", _text(self.dataset_id, label="dataset_id").casefold()
        )
        object.__setattr__(
            self,
            "relative_path",
            _normalize_relative_path(self.relative_path),
        )
        object.__setattr__(
            self, "remote_path", _normalize_relative_path(self.remote_path)
        )
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise PatentHFPublisherV2Error("size_bytes must be a non-negative integer")
        object.__setattr__(self, "sha256", _digest(self.sha256))
        if self.content_cid:
            object.__setattr__(
                self, "content_cid", _text(self.content_cid, label="content_cid")
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataset_id": self.dataset_id,
            "operation": "add",
            "relative_path": self.relative_path,
            "remote_path": self.remote_path,
            "repository": self.repository,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid:
            payload["content_cid"] = self.content_cid
        return payload


@dataclass(frozen=True, slots=True)
class StagePlan:
    """Deterministic dry-run plan for an add-only multi-repo staged PR."""

    schema_version: str
    organization: str
    version_tag: str
    release_root_cid: str
    release_id: str
    branch_name: str
    target_revision: str
    base_revisions: Mapping[str, str]
    """dataset_id → audited parent commit SHA."""

    artifacts: tuple[PlannedArtifact, ...]
    plan_digest: str = ""
    staged_diff_digest: str = ""
    upload_bytes: int = 0
    dry_run: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        org = _text(self.organization, label="organization").casefold()
        version = _text(self.version_tag, label="version_tag")
        release_root = _text(self.release_root_cid, label="release_root_cid")
        release_id = _text(self.release_id, label="release_id")
        branch = _text(self.branch_name, label="branch_name")
        target = _text(self.target_revision, label="target_revision").casefold()
        if branch.casefold() in PROHIBITED_TARGET_REVISIONS:
            raise DirectMainUploadError(
                "stage branch must not be main/master; use a stage/* branch"
            )
        if not self.artifacts:
            raise PatentHFPublisherV2Error("stage plan requires at least one artifact")
        bases: dict[str, str] = {}
        for key, value in dict(self.base_revisions).items():
            bases[_text(key, label="dataset_id").casefold()] = _commit_sha(
                value, label="base_revision"
            )
        arts = tuple(sorted(self.artifacts, key=lambda a: (a.dataset_id, a.remote_path)))
        upload_bytes = sum(int(a.size_bytes) for a in arts)
        meta = dict(self.metadata or {})
        reject_credentials_in_payload(meta, label="plan.metadata")
        reject_identity_contamination(meta, label="plan.metadata")

        # Binding payload for digests (no secrets).
        binding = {
            "artifacts": [a.to_dict() for a in arts],
            "base_revisions": dict(sorted(bases.items())),
            "branch_name": branch,
            "organization": org,
            "release_id": release_id,
            "release_root_cid": release_root,
            "schema_version": PUBLISHER_V2_SCHEMA,
            "target_revision": target,
            "version_tag": version,
        }
        plan_digest = sha256(canonical_json_bytes(binding)).hexdigest()
        staged_diff = {
            "artifacts": [
                {
                    "dataset_id": a.dataset_id,
                    "remote_path": a.remote_path,
                    "sha256": a.sha256,
                    "size_bytes": a.size_bytes,
                }
                for a in arts
            ],
            "base_revisions": dict(sorted(bases.items())),
            "branch_name": branch,
            "release_root_cid": release_root,
        }
        staged_diff_digest = sha256(canonical_json_bytes(staged_diff)).hexdigest()

        object.__setattr__(self, "schema_version", PUBLISHER_V2_SCHEMA)
        object.__setattr__(self, "organization", org)
        object.__setattr__(self, "version_tag", version)
        object.__setattr__(self, "release_root_cid", release_root)
        object.__setattr__(self, "release_id", release_id)
        object.__setattr__(self, "branch_name", branch)
        object.__setattr__(self, "target_revision", target)
        object.__setattr__(self, "base_revisions", MappingProxyType(bases))
        object.__setattr__(self, "artifacts", arts)
        object.__setattr__(self, "plan_digest", plan_digest)
        object.__setattr__(self, "staged_diff_digest", staged_diff_digest)
        object.__setattr__(self, "upload_bytes", upload_bytes)
        object.__setattr__(self, "metadata", MappingProxyType(meta))
        if type(self.dry_run) is not bool:
            raise PatentHFPublisherV2Error("dry_run must be boolean")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "artifacts": [a.to_dict() for a in self.artifacts],
            "base_revisions": dict(self.base_revisions),
            "branch_name": self.branch_name,
            "dry_run": self.dry_run,
            "goal_id": GOAL_ID,
            "metadata": dict(self.metadata),
            "organization": self.organization,
            "plan_digest": self.plan_digest,
            "program_id": PROGRAM_ID,
            "release_id": self.release_id,
            "release_root_cid": self.release_root_cid,
            "remote_write_contacted": False,
            "schema_version": self.schema_version,
            "staged_diff_digest": self.staged_diff_digest,
            "target_revision": self.target_revision,
            "upload_bytes": self.upload_bytes,
            "upload_file_count": len(self.artifacts),
            "version_tag": self.version_tag,
        }
        reject_credentials_in_payload(payload, label="stage_plan")
        return payload

    def artifacts_for_dataset(self, dataset_id: str) -> tuple[PlannedArtifact, ...]:
        key = dataset_id.casefold()
        return tuple(a for a in self.artifacts if a.dataset_id == key)

    def dataset_ids(self) -> tuple[str, ...]:
        return tuple(sorted({a.dataset_id for a in self.artifacts}))


@dataclass(frozen=True, slots=True)
class RepositoryStageResult:
    """Per-repository staged branch commit identity."""

    dataset_id: str
    base_commit: str
    branch_name: str
    staged_commit_sha: str
    uploaded_paths: tuple[str, ...]
    upload_bytes: int
    pull_request_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_commit": self.base_commit,
            "branch_name": self.branch_name,
            "dataset_id": self.dataset_id,
            "pull_request_number": self.pull_request_number,
            "staged_commit_sha": self.staged_commit_sha,
            "upload_bytes": self.upload_bytes,
            "uploaded_paths": list(self.uploaded_paths),
        }


@dataclass(frozen=True, slots=True)
class StagedPRReceipt:
    """Identity of a staged multi-repo PR / branch set (not yet on main)."""

    schema_version: str
    organization: str
    version_tag: str
    release_root_cid: str
    release_id: str
    plan_digest: str
    staged_diff_digest: str
    branch_name: str
    repositories: tuple[RepositoryStageResult, ...]
    status: str = "staged_pending_approval"
    main_published: bool = False
    pointers_moved: bool = False
    credentials_scope: str = ""
    token_material_present: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", STAGED_RECEIPT_SCHEMA)
        object.__setattr__(
            self, "organization", _text(self.organization, label="organization")
        )
        object.__setattr__(
            self, "version_tag", _text(self.version_tag, label="version_tag")
        )
        object.__setattr__(
            self,
            "release_root_cid",
            _text(self.release_root_cid, label="release_root_cid"),
        )
        object.__setattr__(
            self, "release_id", _text(self.release_id, label="release_id")
        )
        object.__setattr__(self, "plan_digest", _digest(self.plan_digest, label="plan_digest"))
        object.__setattr__(
            self,
            "staged_diff_digest",
            _digest(self.staged_diff_digest, label="staged_diff_digest"),
        )
        object.__setattr__(
            self, "branch_name", _text(self.branch_name, label="branch_name")
        )
        if self.main_published:
            raise PatentHFPublisherV2Error(
                "staged receipt must not claim main_published"
            )
        if self.pointers_moved:
            raise PatentHFPublisherV2Error(
                "staged receipt must not claim pointers_moved (PATLAW-160)"
            )
        if self.token_material_present:
            raise CredentialLeakError("token material must never be marked present")
        repos = tuple(
            sorted(self.repositories, key=lambda r: r.dataset_id)
        )
        if not repos:
            raise PatentHFPublisherV2Error("staged receipt requires repositories")
        object.__setattr__(self, "repositories", repos)
        if not self.credentials_scope:
            scope = "dataset:write:" + ",".join(r.dataset_id for r in repos)
            object.__setattr__(self, "credentials_scope", scope)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "branch_name": self.branch_name,
            "credentials_scope": self.credentials_scope,
            "goal_id": GOAL_ID,
            "main_published": False,
            "organization": self.organization,
            "plan_digest": self.plan_digest,
            "pointers_moved": False,
            "program_id": PROGRAM_ID,
            "release_id": self.release_id,
            "release_root_cid": self.release_root_cid,
            "repositories": [r.to_dict() for r in self.repositories],
            "schema_version": self.schema_version,
            "staged_diff_digest": self.staged_diff_digest,
            "status": self.status,
            "token_material_present": False,
            "tokens_persisted": False,
            "version_tag": self.version_tag,
        }
        reject_credentials_in_payload(payload, label="staged_pr_receipt")
        return payload


@dataclass(frozen=True, slots=True)
class PublicationApprovalReceipt:
    """Operator-signed approval binding release root + staged diff.

    This object is *consumed* by :meth:`PatentHFPublisherV2.promote_approved`.
    The publisher never constructs a valid instance; operators (or tests with
    an external key) must call :func:`create_operator_approval` with key
    material that does not live in this module.
    """

    schema_version: str
    approval_id: str
    approver: str
    plan_digest: str
    staged_diff_digest: str
    release_root_cid: str
    signature: str
    """HMAC-SHA256 hex over the approval binding (not a Hub token)."""

    credentials_scope: str
    max_upload_bytes: int
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", APPROVAL_SCHEMA)
        object.__setattr__(
            self, "approval_id", _text(self.approval_id, label="approval_id")
        )
        approver = _text(self.approver, label="approver")
        if approver.casefold() in _AGENT_SELF_APPROVAL_MARKERS:
            raise ApprovalError(
                "implementation agents and supervisors cannot self-approve; "
                f"rejected approver={approver!r}"
            )
        object.__setattr__(self, "approver", approver)
        object.__setattr__(self, "plan_digest", _digest(self.plan_digest, label="plan_digest"))
        object.__setattr__(
            self,
            "staged_diff_digest",
            _digest(self.staged_diff_digest, label="staged_diff_digest"),
        )
        object.__setattr__(
            self,
            "release_root_cid",
            _text(self.release_root_cid, label="release_root_cid"),
        )
        object.__setattr__(
            self, "signature", _digest(self.signature, label="signature")
        )
        object.__setattr__(
            self,
            "credentials_scope",
            _text(self.credentials_scope, label="credentials_scope"),
        )
        if (
            not isinstance(self.max_upload_bytes, int)
            or isinstance(self.max_upload_bytes, bool)
            or self.max_upload_bytes < 0
        ):
            raise ApprovalError("max_upload_bytes must be a non-negative integer")
        notes = str(self.notes or "")
        lowered = notes.casefold()
        for needle in ("hf_", "bearer ", "password=", "secret=", "token=", "operator_key"):
            if needle in lowered:
                raise ApprovalError(
                    "approval notes must not contain credential-like material"
                )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        # Signature is a digest, not a secret — safe to record.  Key material
        # that produced it must never appear here.
        payload = {
            "approval_id": self.approval_id,
            "approver": self.approver,
            "credentials_scope": self.credentials_scope,
            "max_upload_bytes": self.max_upload_bytes,
            "notes": self.notes,
            "plan_digest": self.plan_digest,
            "release_root_cid": self.release_root_cid,
            "schema_version": self.schema_version,
            "signature": self.signature,
            "staged_diff_digest": self.staged_diff_digest,
        }
        reject_credentials_in_payload(payload, label="approval_receipt")
        return payload


@dataclass(frozen=True, slots=True)
class RepositoryPromotionResult:
    dataset_id: str
    parent_commit: str
    promoted_commit_sha: str
    target_revision: str
    uploaded_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "parent_commit": self.parent_commit,
            "promoted_commit_sha": self.promoted_commit_sha,
            "target_revision": self.target_revision,
            "uploaded_paths": list(self.uploaded_paths),
        }


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    """Receipt after an approved promotion transaction (main advanced)."""

    schema_version: str
    organization: str
    version_tag: str
    release_root_cid: str
    release_id: str
    plan_digest: str
    staged_diff_digest: str
    approval_id: str
    repositories: tuple[RepositoryPromotionResult, ...]
    status: str = "promoted"
    main_published: bool = True
    pointers_moved: bool = False
    token_material_present: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", PROMOTION_RECEIPT_SCHEMA)
        if self.pointers_moved:
            raise PatentHFPublisherV2Error(
                "promotion receipt must not move runtime pointers (PATLAW-160)"
            )
        if self.token_material_present:
            raise CredentialLeakError("token material must never be marked present")
        repos = tuple(sorted(self.repositories, key=lambda r: r.dataset_id))
        if not repos:
            raise PatentHFPublisherV2Error("promotion requires repositories")
        object.__setattr__(self, "repositories", repos)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "approval_id": self.approval_id,
            "goal_id": GOAL_ID,
            "main_published": True,
            "organization": self.organization,
            "plan_digest": self.plan_digest,
            "pointers_moved": False,
            "program_id": PROGRAM_ID,
            "release_id": self.release_id,
            "release_root_cid": self.release_root_cid,
            "repositories": [r.to_dict() for r in self.repositories],
            "schema_version": self.schema_version,
            "staged_diff_digest": self.staged_diff_digest,
            "status": self.status,
            "token_material_present": False,
            "tokens_persisted": False,
            "version_tag": self.version_tag,
        }
        reject_credentials_in_payload(payload, label="promotion_receipt")
        return payload


# ---------------------------------------------------------------------------
# Operator approval (external key; publisher does not generate)
# ---------------------------------------------------------------------------


def approval_binding_payload(
    *,
    plan_digest: str,
    staged_diff_digest: str,
    release_root_cid: str,
    credentials_scope: str,
    max_upload_bytes: int,
    approval_id: str,
    approver: str,
) -> dict[str, Any]:
    """Canonical binding signed by the operator key."""

    return {
        "approval_id": _text(approval_id, label="approval_id"),
        "approver": _text(approver, label="approver"),
        "credentials_scope": _text(credentials_scope, label="credentials_scope"),
        "max_upload_bytes": int(max_upload_bytes),
        "plan_digest": _digest(plan_digest, label="plan_digest"),
        "release_root_cid": _text(release_root_cid, label="release_root_cid"),
        "schema_version": APPROVAL_SCHEMA,
        "staged_diff_digest": _digest(
            staged_diff_digest, label="staged_diff_digest"
        ),
    }


def _operator_key_bytes(operator_key: bytes | str) -> bytes:
    if isinstance(operator_key, str):
        raw = operator_key.encode("utf-8")
    elif isinstance(operator_key, (bytes, bytearray)):
        raw = bytes(operator_key)
    else:
        raise ApprovalError("operator_key must be bytes or str")
    if len(raw) < 16:
        raise ApprovalError("operator_key must be at least 16 bytes")
    # Refuse keys that look like Hub tokens so they are not confused.
    lowered = raw.lower()
    if lowered.startswith(b"hf_") or lowered.startswith(b"hf-"):
        raise ApprovalError(
            "operator_key must not be a Hugging Face token; use a separate "
            "approval HMAC key"
        )
    return raw


def sign_approval_binding(
    binding: Mapping[str, Any],
    *,
    operator_key: bytes | str,
) -> str:
    """Return HMAC-SHA256 hex of the canonical binding using *operator_key*."""

    key = _operator_key_bytes(operator_key)
    message = canonical_json_bytes(dict(binding))
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def create_operator_approval(
    *,
    plan: StagePlan | Mapping[str, Any],
    operator_key: bytes | str,
    approver: str,
    approval_id: str,
    credentials_scope: str | None = None,
    max_upload_bytes: int | None = None,
    notes: str = "",
) -> PublicationApprovalReceipt:
    """Create an operator-signed approval from *external* key material.

    This function deliberately lives at module scope and requires an operator
    key that is **not** supplied by :class:`PatentHFPublisherV2`.  The
    implementation agent / publisher cannot produce a valid approval without
    that external key.
    """

    approver_text = _text(approver, label="approver")
    if approver_text.casefold() in _AGENT_SELF_APPROVAL_MARKERS:
        raise ApprovalError(
            "implementation agents and supervisors cannot self-approve; "
            f"rejected approver={approver_text!r}"
        )

    if isinstance(plan, StagePlan):
        plan_digest = plan.plan_digest
        staged_diff_digest = plan.staged_diff_digest
        release_root_cid = plan.release_root_cid
        scope = credentials_scope or (
            "dataset:write:" + ",".join(plan.dataset_ids())
        )
        max_bytes = (
            int(max_upload_bytes)
            if max_upload_bytes is not None
            else int(plan.upload_bytes)
        )
    else:
        plan_digest = str(plan["plan_digest"])
        staged_diff_digest = str(plan["staged_diff_digest"])
        release_root_cid = str(plan["release_root_cid"])
        scope = credentials_scope or str(plan.get("credentials_scope") or "")
        if not scope:
            raise ApprovalError("credentials_scope is required")
        max_bytes = (
            int(max_upload_bytes)
            if max_upload_bytes is not None
            else int(plan.get("upload_bytes") or 0)
        )

    binding = approval_binding_payload(
        plan_digest=plan_digest,
        staged_diff_digest=staged_diff_digest,
        release_root_cid=release_root_cid,
        credentials_scope=scope,
        max_upload_bytes=max_bytes,
        approval_id=approval_id,
        approver=approver,
    )
    signature = sign_approval_binding(binding, operator_key=operator_key)
    return PublicationApprovalReceipt(
        schema_version=APPROVAL_SCHEMA,
        approval_id=approval_id,
        approver=approver,
        plan_digest=plan_digest,
        staged_diff_digest=staged_diff_digest,
        release_root_cid=release_root_cid,
        signature=signature,
        credentials_scope=scope,
        max_upload_bytes=max_bytes,
        notes=notes,
    )


def verify_operator_approval(
    approval: PublicationApprovalReceipt | Mapping[str, Any],
    *,
    plan: StagePlan,
    operator_key: bytes | str,
) -> PublicationApprovalReceipt:
    """Verify an operator approval against a plan and external key."""

    if isinstance(approval, Mapping):
        approval = PublicationApprovalReceipt(
            schema_version=str(approval.get("schema_version") or APPROVAL_SCHEMA),
            approval_id=str(approval["approval_id"]),
            approver=str(approval["approver"]),
            plan_digest=str(approval["plan_digest"]),
            staged_diff_digest=str(approval["staged_diff_digest"]),
            release_root_cid=str(approval["release_root_cid"]),
            signature=str(approval["signature"]),
            credentials_scope=str(approval["credentials_scope"]),
            max_upload_bytes=int(approval["max_upload_bytes"]),
            notes=str(approval.get("notes") or ""),
        )
    if not isinstance(approval, PublicationApprovalReceipt):
        raise ApprovalError("approval must be a PublicationApprovalReceipt")
    if approval.plan_digest != plan.plan_digest:
        raise ApprovalError("approval plan_digest does not match stage plan")
    if approval.staged_diff_digest != plan.staged_diff_digest:
        raise ApprovalError("approval staged_diff_digest does not match stage plan")
    if approval.release_root_cid != plan.release_root_cid:
        raise ApprovalError("approval release_root_cid does not match stage plan")
    expected_scope = "dataset:write:" + ",".join(plan.dataset_ids())
    if approval.credentials_scope != expected_scope:
        # Allow explicit multi-scope that matches exactly the plan datasets.
        if approval.credentials_scope != plan.metadata.get("credentials_scope"):
            # Still accept if scope lists the same datasets (order-stable).
            if approval.credentials_scope != expected_scope:
                raise ApprovalError(
                    "approval credentials_scope does not match planned repositories"
                )
    if plan.upload_bytes > int(approval.max_upload_bytes):
        raise ApprovalError("plan upload_bytes exceeds approved max_upload_bytes")

    binding = approval_binding_payload(
        plan_digest=approval.plan_digest,
        staged_diff_digest=approval.staged_diff_digest,
        release_root_cid=approval.release_root_cid,
        credentials_scope=approval.credentials_scope,
        max_upload_bytes=approval.max_upload_bytes,
        approval_id=approval.approval_id,
        approver=approval.approver,
    )
    expected = sign_approval_binding(binding, operator_key=operator_key)
    if not hmac.compare_digest(expected, approval.signature):
        raise ApprovalError("approval signature verification failed")
    return approval


def publisher_can_generate_operator_approval() -> bool:
    """Return False — the publisher never generates operator approval."""

    return False


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_release_manifest(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.is_symlink():
        raise PatentHFPublisherV2Error(
            f"release manifest must be a regular file: {target}"
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PatentHFPublisherV2Error(
            f"cannot read release manifest: {target}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise PatentHFPublisherV2Error("release manifest must be a JSON object")
    return dict(payload)


def _artifact_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("artifacts") or manifest.get("files") or manifest.get(
        "descriptors"
    )
    if not isinstance(raw, list) or not raw:
        raise PatentHFPublisherV2Error(
            "manifest must declare a non-empty artifacts/files list"
        )
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise PatentHFPublisherV2Error(f"artifacts[{index}] must be an object")
        entries.append(dict(item))
    return entries


def _split_repo_path(
    relative_path: str,
    *,
    repository_hint: str | None,
    organization: str,
) -> tuple[str, str, str]:
    """Return ``(repository, dataset_id, remote_path)`` for a local relative path."""

    path = _normalize_relative_path(relative_path)
    if path.startswith(f"{REPOS_DIRNAME}/"):
        rest = path[len(REPOS_DIRNAME) + 1 :]
        if "/" not in rest:
            raise PatentHFPublisherV2Error(
                f"repo-prefixed path missing remote path: {path}"
            )
        repository, remote = rest.split("/", 1)
        repository = repository.casefold()
        remote = _normalize_relative_path(remote)
    elif repository_hint:
        repository = repository_hint.casefold()
        remote = path
    else:
        # Support artifacts (manifest, cards) go to the corpus repository by
        # default so they remain on the primary Hub dataset.
        repository = CANONICAL_REPOSITORY_NAMES[0]
        remote = path
    dataset_id = _dataset_id(organization, repository)
    return repository, dataset_id, remote


def plan_stage_from_local_root(
    *,
    local_root: str | Path,
    manifest: Mapping[str, Any] | None = None,
    organization: str | None = None,
    version_tag: str | None = None,
    base_revisions: Mapping[str, str],
    branch_name: str | None = None,
    target_revision: str = DEFAULT_TARGET_REVISION,
    release_id: str | None = None,
) -> StagePlan:
    """Build a dry-run stage plan from a local staged release tree.

    Only files listed in the release manifest are included.  Local digests
    must match the manifest; any drift fails closed.
    """

    root = Path(local_root).expanduser().resolve()
    if not root.is_dir():
        raise PatentHFPublisherV2Error(f"local_root is not a directory: {root}")

    if manifest is None:
        manifest_path = root / RELEASE_MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise PatentHFPublisherV2Error(
                f"missing {RELEASE_MANIFEST_FILENAME} under {root}"
            )
        manifest = load_release_manifest(manifest_path)
    else:
        manifest = dict(manifest)

    org = (
        organization
        or str(manifest.get("organization") or ORGANIZATION)
    ).casefold()
    version = version_tag or str(manifest.get("version_tag") or "v2.0.0")
    release_root_cid = str(
        manifest.get("release_root_cid") or manifest.get("release_cid") or ""
    ).strip()
    if not release_root_cid:
        raise PatentHFPublisherV2Error("manifest requires release_root_cid")
    rid = release_id or str(
        manifest.get("release_id")
        or f"patent-legal-{version}-{release_root_cid[:16]}"
    )
    branch = branch_name or f"{DEFAULT_BRANCH_PREFIX}/{rid}"

    bases = {
        _text(k, label="dataset_id").casefold(): _commit_sha(v, label="base_revision")
        for k, v in dict(base_revisions).items()
    }
    if not bases:
        raise PatentHFPublisherV2Error(
            "base_revisions must map every target dataset_id to a commit SHA"
        )

    planned: list[PlannedArtifact] = []
    for entry in _artifact_entries(manifest):
        rel = str(
            entry.get("relative_path")
            or entry.get("path")
            or entry.get("local_path")
            or ""
        ).strip()
        if not rel:
            raise PatentHFPublisherV2Error("artifact missing relative_path")
        repository, dataset_id, remote = _split_repo_path(
            rel,
            repository_hint=(
                str(entry["repository"]) if entry.get("repository") else None
            ),
            organization=org,
        )
        if dataset_id not in bases:
            raise BaseRevisionError(
                f"no base revision declared for dataset {dataset_id}"
            )
        local = root.joinpath(*Path(rel).parts)
        if not local.is_file() or local.is_symlink():
            raise ArtifactChangedError(f"missing local artifact: {rel}")
        size_bytes, digest = _file_sha256_hex(local)
        expected_sha = str(entry.get("sha256") or "").strip().casefold()
        expected_size = entry.get("size_bytes", entry.get("byte_length"))
        if expected_sha:
            if digest != _digest(expected_sha):
                raise ArtifactChangedError(
                    f"local artifact digest mismatch: {rel}"
                )
        if expected_size is not None and int(expected_size) != size_bytes:
            raise ArtifactChangedError(f"local artifact size mismatch: {rel}")
        content_cid = str(entry.get("content_cid") or "")
        planned.append(
            PlannedArtifact(
                repository=repository,
                dataset_id=dataset_id,
                relative_path=rel,
                remote_path=remote,
                size_bytes=size_bytes,
                sha256=digest,
                content_cid=content_cid,
            )
        )

    return StagePlan(
        schema_version=PUBLISHER_V2_SCHEMA,
        organization=org,
        version_tag=version,
        release_root_cid=release_root_cid,
        release_id=rid,
        branch_name=branch,
        target_revision=target_revision,
        base_revisions=bases,
        artifacts=tuple(planned),
        dry_run=True,
        metadata={
            "goal_id": GOAL_ID,
            "manifest_schema": str(manifest.get("schema_version") or ""),
            "uses_hf_api_upload_file": False,
        },
    )


# ---------------------------------------------------------------------------
# Fake Hub service (integration tests; no network / no real tokens)
# ---------------------------------------------------------------------------


class FakeHubService:
    """In-memory multi-repo Hub stand-in used by integration tests.

    Records all calls.  Never touches the network.  Optional ``auth_token``
    simulates authentication; wrong/missing tokens raise :class:`AuthError`.
    """

    def __init__(
        self,
        *,
        base_revisions: Mapping[str, str] | None = None,
        auth_token: str | None = "fake-operator-token-not-a-real-secret",
        require_auth: bool = True,
        fail_auth: bool = False,
        fail_create_commit_after: int | None = None,
        conflict_on_branch: bool = False,
        advance_main_on: str | None = None,
    ) -> None:
        self.auth_token = auth_token
        self.require_auth = require_auth
        self.fail_auth = fail_auth
        self.fail_create_commit_after = fail_create_commit_after
        self.conflict_on_branch = conflict_on_branch
        self.advance_main_on = advance_main_on
        self.calls: list[str] = []
        self.create_commit_calls: list[dict[str, Any]] = []
        self.create_branch_calls: list[dict[str, Any]] = []
        self.create_pr_calls: list[dict[str, Any]] = []
        self.merge_pr_calls: list[dict[str, Any]] = []
        self.tokens_seen: list[str] = []
        self._commit_counter = 0
        # dataset_id → revision → path → body
        self._files: dict[str, dict[str, dict[str, bytes]]] = {}
        self._heads: dict[str, dict[str, str]] = {}
        self._prs: dict[str, dict[int, dict[str, Any]]] = {}
        self._pr_counter = 0
        for dataset_id, sha in dict(base_revisions or {}).items():
            self.ensure_repo(dataset_id, head_sha=sha)

    def ensure_repo(self, dataset_id: str, *, head_sha: str | None = None) -> None:
        key = dataset_id.casefold()
        if key not in self._heads:
            sha = _commit_sha(head_sha or ("0" * 40))
            self._heads[key] = {"main": sha}
            self._files[key] = {sha: {}}
            self._prs[key] = {}

    def _check_auth(self, token: str | None) -> None:
        if self.fail_auth:
            raise AuthError("Hub authentication rejected")
        if not self.require_auth:
            return
        if not token:
            raise AuthError("Hub authentication required")
        self.tokens_seen.append(token)
        if self.auth_token is not None and token != self.auth_token:
            raise AuthError("Hub authentication rejected: invalid token")

    def _next_sha(self) -> str:
        self._commit_counter += 1
        return sha256(f"fake-commit-{self._commit_counter}".encode()).hexdigest()[:40]

    def repo_info(
        self,
        *,
        repo_id: str,
        repo_type: str = "dataset",
        revision: str | None = None,
        token: str | None = None,
        **_: Any,
    ) -> dict[str, str]:
        self.calls.append("repo_info")
        self._check_auth(token)
        key = repo_id.casefold()
        self.ensure_repo(key)
        rev = revision or "main"
        heads = self._heads[key]
        # Branch name hit.
        if rev in heads:
            return {"sha": heads[rev]}
        rev_cf = rev.casefold()
        for name, sha in heads.items():
            if name.casefold() == rev_cf:
                return {"sha": sha}
        # Commit SHA that exists as a known tip or tree key.
        if _COMMIT_SHA_RE.fullmatch(rev_cf):
            if rev_cf in self._files.get(key, {}):
                return {"sha": rev_cf}
            for sha in heads.values():
                if sha == rev_cf:
                    return {"sha": sha}
            # Unknown SHA still returned only if it matches a head value above.
        if rev_cf in ("main", "master"):
            return {"sha": heads["main"]}
        raise BaseRevisionError(f"unknown revision {revision!r} for {repo_id}")

    def create_branch(
        self,
        *,
        branch: str,
        repo_id: str,
        revision: str | None = None,
        repo_type: str = "dataset",
        token: str | None = None,
        **_: Any,
    ) -> dict[str, str]:
        self.calls.append("create_branch")
        self.create_branch_calls.append(
            {"branch": branch, "repo_id": repo_id, "revision": revision}
        )
        self._check_auth(token)
        if self.conflict_on_branch:
            raise ConflictError(f"branch conflict creating {branch!r}")
        key = repo_id.casefold()
        self.ensure_repo(key)
        branch_name = _text(branch, label="branch")
        if branch_name.casefold() in PROHIBITED_TARGET_REVISIONS:
            raise DirectMainUploadError("refusing to create main as a stage branch")
        if branch_name in self._heads[key]:
            raise ConflictError(f"branch already exists: {branch_name}")
        base_rev = revision or "main"
        if (
            isinstance(base_rev, str)
            and _COMMIT_SHA_RE.fullmatch(base_rev.casefold())
            and base_rev.casefold() in self._files.get(key, {})
        ):
            base_sha = base_rev.casefold()
        else:
            info = self.repo_info(
                repo_id=repo_id, repo_type=repo_type, revision=base_rev, token=token
            )
            base_sha = info["sha"]
        self._heads[key][branch_name] = base_sha
        # Copy file tree reference at branch tip.
        self._files[key].setdefault(base_sha, dict(self._files[key].get(base_sha, {})))
        return {"branch": branch_name, "sha": base_sha}

    def create_commit(
        self,
        *,
        repo_id: str,
        operations: Sequence[Any],
        commit_message: str,
        repo_type: str = "dataset",
        revision: str | None = None,
        parent_commit: str | None = None,
        token: str | None = None,
        **_: Any,
    ) -> dict[str, str]:
        self.calls.append("create_commit")
        self.create_commit_calls.append(
            {
                "repo_id": repo_id,
                "revision": revision,
                "parent_commit": parent_commit,
                "operation_count": len(list(operations or ())),
                "commit_message": commit_message,
            }
        )
        self._check_auth(token)
        if (
            self.fail_create_commit_after is not None
            and len(self.create_commit_calls) > self.fail_create_commit_after
        ):
            raise PartialUploadError(
                f"simulated partial upload failure for {repo_id}"
            )
        key = repo_id.casefold()
        self.ensure_repo(key)
        rev = revision or "main"
        heads = self._heads[key]
        if rev not in heads and rev.casefold() not in ("main", "master"):
            # Auto-create only for explicit stage branches already registered.
            raise ConflictError(f"revision not found for commit: {rev}")
        current = heads.get(rev) or heads["main"]
        if parent_commit is not None and _commit_sha(parent_commit) != current:
            raise BaseRevisionError(
                f"parent race: expected {parent_commit}, current {current}"
            )
        if self.advance_main_on and key == self.advance_main_on.casefold():
            # Simulate concurrent main advance before commit.
            heads["main"] = self._next_sha()
            if rev in ("main", "master") or rev == "main":
                raise BaseRevisionError(
                    f"repository advanced after audit: current {heads['main']}"
                )

        parent_tree = dict(self._files[key].get(current, {}))
        new_tree = dict(parent_tree)
        for op in operations or ():
            path = getattr(op, "path_in_repo", None)
            source = getattr(op, "path_or_fileobj", None)
            op_type = getattr(op, "operation", None) or getattr(op, "op", "add")
            if path is None and isinstance(op, Mapping):
                path = op.get("path_in_repo")
                source = op.get("path_or_fileobj")
                op_type = op.get("operation") or op.get("op") or "add"
            if str(op_type).casefold() not in {"add", "create", ""}:
                raise ConflictError(f"prohibited commit operation: {op_type}")
            if path is None:
                raise PatentHFPublisherV2Error("commit operation missing path_in_repo")
            path_text = _normalize_relative_path(str(path))
            if path_text in new_tree:
                raise ConflictError(
                    f"append-only refuses overwrite of existing path: {path_text}"
                )
            if source is None:
                raise PatentHFPublisherV2Error(
                    f"commit operation missing file for {path_text}"
                )
            if isinstance(source, (bytes, bytearray)):
                body = bytes(source)
            else:
                body = Path(str(source)).read_bytes()
            new_tree[path_text] = body

        new_sha = self._next_sha()
        self._files[key][new_sha] = new_tree
        heads[rev] = new_sha
        return {"commit_sha": new_sha, "oid": new_sha}

    def create_pull_request(
        self,
        *,
        repo_id: str,
        title: str,
        head: str,
        base: str = "main",
        token: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append("create_pull_request")
        self.create_pr_calls.append(
            {"repo_id": repo_id, "title": title, "head": head, "base": base}
        )
        self._check_auth(token)
        key = repo_id.casefold()
        self.ensure_repo(key)
        self._pr_counter += 1
        number = self._pr_counter
        self._prs[key][number] = {
            "number": number,
            "head": head,
            "base": base,
            "title": title,
            "merged": False,
            "head_sha": self._heads[key].get(head),
        }
        return {"number": number, "html_url": f"fake://{key}/pr/{number}"}

    def merge_pull_request(
        self,
        *,
        repo_id: str,
        number: int,
        token: str | None = None,
        parent_commit: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append("merge_pull_request")
        self.merge_pr_calls.append({"repo_id": repo_id, "number": number})
        self._check_auth(token)
        key = repo_id.casefold()
        pr = self._prs.get(key, {}).get(int(number))
        if pr is None:
            raise ConflictError(f"unknown pull request {number} for {repo_id}")
        if pr["merged"]:
            raise ConflictError(f"pull request already merged: {number}")
        head = pr["head"]
        base = pr["base"]
        head_sha = self._heads[key].get(head)
        base_sha = self._heads[key].get(base)
        if head_sha is None or base_sha is None:
            raise ConflictError("PR head/base revision missing")
        if parent_commit is not None and _commit_sha(parent_commit) != base_sha:
            raise BaseRevisionError(
                f"merge race: base advanced after audit "
                f"(expected {parent_commit}, current {base_sha})"
            )
        # Fast-forward base to head tree.
        tree = dict(self._files[key].get(head_sha, {}))
        new_sha = self._next_sha()
        self._files[key][new_sha] = tree
        self._heads[key][base] = new_sha
        pr["merged"] = True
        pr["merge_commit_sha"] = new_sha
        return {"merged": True, "sha": new_sha, "commit_sha": new_sha}

    def get_paths_info(
        self,
        *,
        repo_id: str,
        paths: Sequence[str],
        revision: str | None = None,
        token: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append("get_paths_info")
        self._check_auth(token)
        key = repo_id.casefold()
        self.ensure_repo(key)
        rev = revision or "main"
        sha = self._heads[key].get(rev) or self._heads[key]["main"]
        tree = self._files[key].get(sha, {})
        result: list[dict[str, Any]] = []
        for requested in paths or ():
            path = _normalize_relative_path(str(requested))
            if path in tree:
                body = tree[path]
                result.append(
                    {
                        "path": path,
                        "size": len(body),
                        "lfs": {
                            "sha256": sha256(body).hexdigest(),
                            "size": len(body),
                        },
                    }
                )
        return result

    def upload_file(self, **kwargs: Any) -> None:
        self.calls.append("upload_file")
        raise DirectMainUploadError(
            "upload_file is prohibited; use create_commit on a stage branch"
        )

    def delete_file(self, **kwargs: Any) -> None:
        self.calls.append("delete_file")
        raise ConflictError("delete_file is prohibited under append-only publication")

    def delete_repo(self, **kwargs: Any) -> None:
        self.calls.append("delete_repo")
        raise ConflictError("repository deletion is prohibited")

    def main_sha(self, dataset_id: str) -> str:
        return self._heads[dataset_id.casefold()]["main"]

    def branch_sha(self, dataset_id: str, branch: str) -> str | None:
        return self._heads[dataset_id.casefold()].get(branch)


# ---------------------------------------------------------------------------
# Commit operation helper (duck-typed for HfApi / FakeHubService)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CommitOp:
    path_in_repo: str
    path_or_fileobj: str
    operation: str = "add"


class LiveHubApiAdapter:
    """Adapt real ``huggingface_hub.HfApi`` to the FakeHubService duck-type.

    The publisher calls create_branch → create_commit → create_pull_request →
    merge_pull_request with FakeHub-shaped kwargs.  Real HfApi uses different
    operation objects and PR parameter names; this adapter bridges them without
    embedding tokens in receipts.

    Live stage strategy:

    * ``create_branch`` creates the add-only stage branch from the audited base
    * ``create_commit`` uploads artifacts onto that branch (no direct main write)
    * ``create_pull_request`` opens a PR via a follow-up ``create_commit`` with
      ``create_pr=True`` is **not** used for the file commit (to keep the stage
      branch identity stable); instead we open a PR discussion after the
      branch commit.  When the Hub refuses a head-less PR, we re-commit with
      ``create_pr=True`` against ``main`` from ``parent_commit=base``.
    * ``merge_pull_request`` maps ``number`` → ``discussion_num``
    """

    def __init__(self, *, token: str, endpoint: str | None = None) -> None:
        text = str(token or "").strip()
        if not text:
            raise AuthError("LiveHubApiAdapter requires a non-empty Hub token")
        try:
            import importlib

            hub_mod = importlib.import_module("huggingface_hub")
        except ImportError as exc:  # pragma: no cover - env dependency
            raise PatentHFPublisherV2Error(
                "huggingface_hub is required for live Hub stage/promote"
            ) from exc
        api_cls = getattr(hub_mod, "HfApi")
        kwargs: dict[str, Any] = {"token": text}
        if endpoint:
            kwargs["endpoint"] = endpoint
        self._api = api_cls(**kwargs)
        self._token = text
        # dataset_id → last PR number opened for promote
        self._pr_by_repo: dict[str, int] = {}
        # dataset_id → last staged branch commit sha
        self._branch_head: dict[str, str] = {}
        # dataset_id → base sha used for last stage commit
        self._base_by_repo: dict[str, str] = {}

    def repo_info(
        self,
        *,
        repo_id: str,
        repo_type: str = "dataset",
        revision: str | None = None,
        token: str | None = None,
        **_: Any,
    ) -> Any:
        return self._api.repo_info(
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            token=token or self._token,
        )

    def create_repo(
        self,
        *,
        repo_id: str,
        repo_type: str = "dataset",
        private: bool = False,
        exist_ok: bool = True,
        token: str | None = None,
        **_: Any,
    ) -> Any:
        return self._api.create_repo(
            repo_id=repo_id,
            repo_type=repo_type,
            private=private,
            exist_ok=exist_ok,
            token=token or self._token,
        )

    def create_branch(
        self,
        *,
        branch: str,
        repo_id: str,
        revision: str | None = None,
        repo_type: str = "dataset",
        token: str | None = None,
        exist_ok: bool = True,
        **_: Any,
    ) -> None:
        try:
            self._api.create_branch(
                repo_id=repo_id,
                branch=branch,
                revision=revision,
                repo_type=repo_type,
                token=token or self._token,
                exist_ok=exist_ok,
            )
        except Exception as exc:
            # exist_ok race / already exists
            msg = str(exc).casefold()
            if exist_ok and (
                "already exists" in msg or "409" in msg or "exist" in msg
            ):
                return
            raise ConflictError(f"create_branch failed for {repo_id}: {exc}") from exc

    def create_commit(
        self,
        *,
        repo_id: str,
        operations: Sequence[Any],
        commit_message: str,
        repo_type: str = "dataset",
        revision: str | None = None,
        parent_commit: str | None = None,
        token: str | None = None,
        create_pr: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        import importlib

        hub_mod = importlib.import_module("huggingface_hub")
        add_cls = getattr(hub_mod, "CommitOperationAdd")

        ops: list[Any] = []
        for item in operations:
            path_in_repo = getattr(item, "path_in_repo", None)
            path_or_fileobj = getattr(item, "path_or_fileobj", None)
            if path_in_repo is None and isinstance(item, Mapping):
                path_in_repo = item.get("path_in_repo")
                path_or_fileobj = item.get("path_or_fileobj")
            if not path_in_repo or path_or_fileobj is None:
                raise PatentHFPublisherV2Error(
                    f"invalid commit operation for {repo_id}: {item!r}"
                )
            ops.append(
                add_cls(
                    path_in_repo=str(path_in_repo),
                    path_or_fileobj=path_or_fileobj,
                )
            )
        if not ops and not create_pr:
            raise PatentHFPublisherV2Error(
                f"no commit operations for {repo_id}"
            )

        # For live stage, open a PR carrying the artifact commit so promote can
        # merge via discussion_num.  parent_commit pins the audited main base.
        # Do not force create_pr when the caller already targets a non-main
        # revision without parent (branch maintenance commits).
        use_create_pr = bool(create_pr)
        use_revision = revision
        if (
            not use_create_pr
            and parent_commit
            and ops
            and (revision is None or str(revision).casefold() not in {"main", "master"})
        ):
            # Publisher stages onto a branch then opens a PR.  Real Hub PRs with
            # file payloads are created most reliably via create_pr=True from the
            # audited parent (main).  Keep branch create as audit sidecar only.
            use_create_pr = True
            use_revision = None

        info = self._api.create_commit(
            repo_id=repo_id,
            operations=ops,
            commit_message=commit_message,
            repo_type=repo_type,
            revision=use_revision,
            parent_commit=parent_commit,
            token=token or self._token,
            create_pr=use_create_pr,
        )
        oid = getattr(info, "oid", None) or getattr(info, "commit_sha", None)
        if not oid:
            raise PartialUploadError(
                f"create_commit returned no oid for {repo_id}"
            )
        key = repo_id.casefold()
        self._branch_head[key] = _commit_sha(oid)
        if parent_commit:
            self._base_by_repo[key] = _commit_sha(parent_commit)
        pr_num_raw = getattr(info, "pr_num", None)
        if pr_num_raw is not None and str(pr_num_raw).strip():
            try:
                self._pr_by_repo[key] = int(pr_num_raw)
            except (TypeError, ValueError):
                pass
        return {
            "commit_sha": _commit_sha(oid),
            "oid": _commit_sha(oid),
            "sha": _commit_sha(oid),
            "pr_num": self._pr_by_repo.get(key),
            "pr_url": getattr(info, "pr_url", None),
        }

    def create_pull_request(
        self,
        *,
        repo_id: str,
        title: str,
        head: str,
        base: str = "main",
        token: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Return the PR number opened by the preceding live create_commit."""
        del title, head, base, token  # title/head recorded on the create_pr commit
        key = repo_id.casefold()
        number = self._pr_by_repo.get(key)
        if number is None:
            raise PartialUploadError(
                f"no PR number recorded for {repo_id}; live create_commit must "
                "open a PR (create_pr=True) before create_pull_request"
            )
        return {
            "number": int(number),
            "html_url": (
                f"https://huggingface.co/datasets/{repo_id}/discussions/{int(number)}"
            ),
        }

    def merge_pull_request(
        self,
        *,
        repo_id: str,
        number: int,
        token: str | None = None,
        parent_commit: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        # Optional race check against main.
        if parent_commit is not None:
            info = self.repo_info(
                repo_id=repo_id, repo_type="dataset", revision="main", token=token
            )
            current = getattr(info, "sha", None)
            if current and _commit_sha(current) != _commit_sha(parent_commit):
                raise BaseRevisionError(
                    f"merge race: main advanced after audit "
                    f"(expected {parent_commit}, current {current})"
                )
        try:
            result = self._api.merge_pull_request(
                repo_id=repo_id,
                discussion_num=int(number),
                token=token or self._token,
                repo_type="dataset",
                comment="Operator-approved patent-legal hub index promote",
            )
        except Exception as exc:
            raise PartialUploadError(
                f"merge_pull_request failed for {repo_id}: {exc}"
            ) from exc

        # After merge, resolve main head sha.
        info = self.repo_info(
            repo_id=repo_id, repo_type="dataset", revision="main", token=token
        )
        sha = getattr(info, "sha", None)
        if not sha:
            # DiscussionStatusChange may not include commit; fail closed.
            raise PartialUploadError(
                f"merge returned no main sha for {repo_id} (result={result!r})"
            )
        return {
            "merged": True,
            "sha": _commit_sha(sha),
            "commit_sha": _commit_sha(sha),
            "discussion_num": int(number),
        }


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class PatentHFPublisherV2:
    """Stage authenticated Hub PRs and promote only with operator approval.

    The publisher **cannot** generate the operator approval it consumes.  Call
    :func:`create_operator_approval` with external key material, then pass the
    receipt to :meth:`promote_approved`.
    """

    # Class-level guard: no embedded operator key.
    OPERATOR_APPROVAL_KEY: None = None

    def __init__(
        self,
        *,
        api: Any | None = None,
        token: str | None = None,
        organization: str = ORGANIZATION,
        commit_message_prefix: str = "patent-legal v2 release",
    ) -> None:
        self.api = api
        self._token = token
        self.organization = organization.casefold()
        self.commit_message_prefix = commit_message_prefix

    # -- intentional absence of self-approval --------------------------------

    def generate_operator_approval(self, *args: Any, **kwargs: Any) -> None:
        """Hard-disabled: the implementation agent cannot self-approve."""

        raise ApprovalError(
            "PatentHFPublisherV2 cannot generate the operator approval it "
            "consumes; obtain a PublicationApprovalReceipt from an external "
            "operator key via create_operator_approval()"
        )

    def self_approve(self, *args: Any, **kwargs: Any) -> None:
        raise ApprovalError(
            "supervisor self-approval is prohibited; use create_operator_approval "
            "with external operator key material"
        )

    # -- API helpers ---------------------------------------------------------

    def _require_api(self) -> Any:
        if self.api is None:
            raise PatentHFPublisherV2Error(
                "an injected Hub API client is required for stage/promote "
                "(live HfApi is never constructed implicitly)"
            )
        return self.api

    def _require_method(self, name: str) -> Callable[..., Any]:
        api = self._require_api()
        method = getattr(api, name, None)
        if not callable(method):
            raise PatentHFPublisherV2Error(f"API client must provide {name}")
        return method

    def _auth_token(self, *, required: bool) -> str | None:
        if self._token is not None:
            return self._token
        return resolve_hub_token(allow_missing=not required)

    def plan(
        self,
        *,
        local_root: str | Path,
        base_revisions: Mapping[str, str],
        manifest: Mapping[str, Any] | None = None,
        version_tag: str | None = None,
        branch_name: str | None = None,
        release_id: str | None = None,
        target_revision: str = DEFAULT_TARGET_REVISION,
    ) -> StagePlan:
        """Offline dry-run plan (no Hub contact, no token use)."""

        return plan_stage_from_local_root(
            local_root=local_root,
            manifest=manifest,
            organization=self.organization,
            version_tag=version_tag,
            base_revisions=base_revisions,
            branch_name=branch_name,
            target_revision=target_revision,
            release_id=release_id,
        )

    def assert_bases_current(self, plan: StagePlan) -> dict[str, str]:
        """Re-read each repository head and fail on race / mismatch."""

        repo_info = self._require_method("repo_info")
        token = self._auth_token(required=True)
        current: dict[str, str] = {}
        for dataset_id, expected in plan.base_revisions.items():
            try:
                info = repo_info(
                    repo_id=dataset_id,
                    repo_type="dataset",
                    revision=plan.target_revision,
                    token=token,
                )
            except PatentHFPublisherV2Error:
                raise
            except Exception as exc:  # pragma: no cover - transport
                raise AuthError(f"cannot read repo_info for {dataset_id}: {exc}") from exc
            sha = None
            if isinstance(info, Mapping):
                sha = info.get("sha") or info.get("oid")
            else:
                sha = getattr(info, "sha", None) or getattr(info, "oid", None)
            if sha is None:
                raise BaseRevisionError(
                    f"repo_info missing sha for {dataset_id}"
                )
            current_sha = _commit_sha(sha, label=f"current_head:{dataset_id}")
            if current_sha != expected:
                raise BaseRevisionError(
                    "Hugging Face repository advanced after audit: "
                    f"approved parent {expected}, current {current_sha} "
                    f"for {dataset_id}; rerun plan and obtain a new approval"
                )
            current[dataset_id] = current_sha
        return current

    def _verify_local_artifacts(
        self, plan: StagePlan, local_root: Path
    ) -> None:
        for item in plan.artifacts:
            local = local_root.joinpath(*Path(item.relative_path).parts)
            if not local.is_file() or local.is_symlink():
                raise ArtifactChangedError(
                    f"missing local artifact before upload: {item.relative_path}"
                )
            size_bytes, digest = _file_sha256_hex(local)
            if size_bytes != item.size_bytes or digest != item.sha256:
                raise ArtifactChangedError(
                    f"local artifact changed before upload: {item.relative_path}"
                )

    def stage_pull_request(
        self,
        plan: StagePlan,
        *,
        local_root: str | Path,
        create_pr: bool = True,
        commit_message: str | None = None,
    ) -> StagedPRReceipt:
        """Create add-only stage branches and optional PRs (never touches main).

        Uploads only manifest-enumerated artifacts via ``create_commit`` on the
        stage branch.  Partial multi-repo failure leaves main unchanged and
        raises :class:`PartialUploadError`.
        """

        if not isinstance(plan, StagePlan):
            raise PatentHFPublisherV2Error("plan must be a StagePlan")
        if plan.branch_name.casefold() in PROHIBITED_TARGET_REVISIONS:
            raise DirectMainUploadError("refusing direct main upload")

        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise PatentHFPublisherV2Error(f"local_root is not a directory: {root}")

        self._verify_local_artifacts(plan, root)
        # Confirm bases before any write.
        self.assert_bases_current(plan)

        create_branch = self._require_method("create_branch")
        create_commit = self._require_method("create_commit")
        token = self._auth_token(required=True)
        message = commit_message or (
            f"{self.commit_message_prefix}: stage {plan.release_id}"
        )

        results: list[RepositoryStageResult] = []
        completed: list[str] = []
        try:
            for dataset_id in plan.dataset_ids():
                arts = plan.artifacts_for_dataset(dataset_id)
                base = plan.base_revisions[dataset_id]
                try:
                    create_branch(
                        branch=plan.branch_name,
                        repo_id=dataset_id,
                        revision=base,
                        repo_type="dataset",
                        token=token,
                    )
                except ConflictError:
                    raise
                except PatentHFPublisherV2Error:
                    raise
                except Exception as exc:
                    raise ConflictError(
                        f"create_branch failed for {dataset_id}: {exc}"
                    ) from exc

                operations: list[_CommitOp] = []
                uploaded: list[str] = []
                upload_bytes = 0
                for item in arts:
                    local = root.joinpath(*Path(item.relative_path).parts)
                    size_bytes, digest = _file_sha256_hex(local)
                    if size_bytes != item.size_bytes or digest != item.sha256:
                        raise ArtifactChangedError(
                            f"artifact changed during stage: {item.relative_path}"
                        )
                    operations.append(
                        _CommitOp(
                            path_in_repo=item.remote_path,
                            path_or_fileobj=str(local),
                            operation="add",
                        )
                    )
                    uploaded.append(item.remote_path)
                    upload_bytes += size_bytes

                if not operations:
                    raise PatentHFPublisherV2Error(
                        f"no operations for dataset {dataset_id}"
                    )

                try:
                    commit_result = create_commit(
                        repo_id=dataset_id,
                        operations=operations,
                        commit_message=message,
                        repo_type="dataset",
                        revision=plan.branch_name,
                        parent_commit=base,
                        token=token,
                    )
                except PartialUploadError:
                    raise
                except BaseRevisionError:
                    raise
                except ConflictError:
                    raise
                except AuthError:
                    raise
                except PatentHFPublisherV2Error:
                    raise
                except Exception as exc:
                    raise PartialUploadError(
                        f"create_commit failed for {dataset_id}: {exc}"
                    ) from exc

                staged_sha = None
                if isinstance(commit_result, Mapping):
                    staged_sha = (
                        commit_result.get("commit_sha")
                        or commit_result.get("oid")
                        or commit_result.get("sha")
                    )
                else:
                    staged_sha = (
                        getattr(commit_result, "commit_sha", None)
                        or getattr(commit_result, "oid", None)
                        or getattr(commit_result, "sha", None)
                    )
                if not staged_sha:
                    raise PartialUploadError(
                        f"create_commit returned no commit sha for {dataset_id}"
                    )
                staged_sha = _commit_sha(staged_sha)

                pr_number: int | None = None
                if create_pr:
                    create_pr_fn = self._require_method("create_pull_request")
                    try:
                        pr = create_pr_fn(
                            repo_id=dataset_id,
                            title=message,
                            head=plan.branch_name,
                            base=plan.target_revision,
                            token=token,
                        )
                    except Exception as exc:
                        raise PartialUploadError(
                            f"create_pull_request failed for {dataset_id}: {exc}"
                        ) from exc
                    if isinstance(pr, Mapping):
                        pr_number = int(pr.get("number") or 0) or None
                    else:
                        pr_number = int(getattr(pr, "number", 0) or 0) or None

                results.append(
                    RepositoryStageResult(
                        dataset_id=dataset_id,
                        base_commit=base,
                        branch_name=plan.branch_name,
                        staged_commit_sha=staged_sha,
                        uploaded_paths=tuple(uploaded),
                        upload_bytes=upload_bytes,
                        pull_request_number=pr_number,
                    )
                )
                completed.append(dataset_id)
        except Exception:
            # Main must remain at audited bases for all repos; staged branches
            # may exist but promotion is impossible without a full receipt.
            if completed and len(completed) < len(plan.dataset_ids()):
                raise PartialUploadError(
                    "partial multi-repo stage aborted before all repositories "
                    f"completed; finished={completed}; main not published"
                )
            raise

        receipt = StagedPRReceipt(
            schema_version=STAGED_RECEIPT_SCHEMA,
            organization=plan.organization,
            version_tag=plan.version_tag,
            release_root_cid=plan.release_root_cid,
            release_id=plan.release_id,
            plan_digest=plan.plan_digest,
            staged_diff_digest=plan.staged_diff_digest,
            branch_name=plan.branch_name,
            repositories=tuple(results),
            status="staged_pending_approval",
            main_published=False,
            pointers_moved=False,
            credentials_scope="dataset:write:" + ",".join(plan.dataset_ids()),
            token_material_present=False,
        )
        reject_credentials_in_payload(receipt.to_dict(), label="staged_pr_receipt")
        return receipt

    def promote_approved(
        self,
        plan: StagePlan,
        *,
        staged: StagedPRReceipt,
        approval: PublicationApprovalReceipt | Mapping[str, Any],
        operator_key: bytes | str,
        local_root: str | Path,
    ) -> PromotionReceipt:
        """Promote a staged PR after verifying exact operator approval.

        Requires the *same* external operator key used to sign the approval.
        Re-checks base revisions, local artifacts, and staged commit identity
        before merging.  Never moves runtime pointers.
        """

        if not isinstance(plan, StagePlan):
            raise PatentHFPublisherV2Error("plan must be a StagePlan")
        if not isinstance(staged, StagedPRReceipt):
            raise PatentHFPublisherV2Error("staged must be a StagedPRReceipt")
        if staged.plan_digest != plan.plan_digest:
            raise ApprovalError("staged receipt plan_digest does not match plan")
        if staged.staged_diff_digest != plan.staged_diff_digest:
            raise ApprovalError(
                "staged receipt staged_diff_digest does not match plan"
            )
        if staged.release_root_cid != plan.release_root_cid:
            raise ApprovalError(
                "staged receipt release_root_cid does not match plan"
            )

        verified = verify_operator_approval(
            approval, plan=plan, operator_key=operator_key
        )

        root = Path(local_root).expanduser().resolve()
        self._verify_local_artifacts(plan, root)
        # Race check: main must still equal audited bases.
        self.assert_bases_current(plan)

        merge = self._require_method("merge_pull_request")
        token = self._auth_token(required=True)

        promoted: list[RepositoryPromotionResult] = []
        completed: list[str] = []
        try:
            for repo_result in staged.repositories:
                pr_number = repo_result.pull_request_number
                if pr_number is None:
                    raise PatentHFPublisherV2Error(
                        f"staged repository {repo_result.dataset_id} has no PR number"
                    )
                try:
                    merge_result = merge(
                        repo_id=repo_result.dataset_id,
                        number=int(pr_number),
                        token=token,
                        parent_commit=repo_result.base_commit,
                    )
                except BaseRevisionError:
                    raise
                except ConflictError:
                    raise
                except AuthError:
                    raise
                except PatentHFPublisherV2Error:
                    raise
                except Exception as exc:
                    raise PartialUploadError(
                        f"merge_pull_request failed for "
                        f"{repo_result.dataset_id}: {exc}"
                    ) from exc

                sha = None
                if isinstance(merge_result, Mapping):
                    sha = (
                        merge_result.get("commit_sha")
                        or merge_result.get("sha")
                        or merge_result.get("oid")
                    )
                else:
                    sha = (
                        getattr(merge_result, "commit_sha", None)
                        or getattr(merge_result, "sha", None)
                    )
                if not sha:
                    raise PartialUploadError(
                        f"merge returned no commit sha for {repo_result.dataset_id}"
                    )
                promoted.append(
                    RepositoryPromotionResult(
                        dataset_id=repo_result.dataset_id,
                        parent_commit=repo_result.base_commit,
                        promoted_commit_sha=_commit_sha(sha),
                        target_revision=plan.target_revision,
                        uploaded_paths=repo_result.uploaded_paths,
                    )
                )
                completed.append(repo_result.dataset_id)
        except Exception:
            if completed and len(completed) < len(staged.repositories):
                raise PartialUploadError(
                    "partial multi-repo promote aborted; "
                    f"completed={completed}; not all mains published"
                )
            raise

        receipt = PromotionReceipt(
            schema_version=PROMOTION_RECEIPT_SCHEMA,
            organization=plan.organization,
            version_tag=plan.version_tag,
            release_root_cid=plan.release_root_cid,
            release_id=plan.release_id,
            plan_digest=plan.plan_digest,
            staged_diff_digest=plan.staged_diff_digest,
            approval_id=verified.approval_id,
            repositories=tuple(promoted),
            status="promoted",
            main_published=True,
            pointers_moved=False,
            token_material_present=False,
        )
        reject_credentials_in_payload(receipt.to_dict(), label="promotion_receipt")
        return receipt

    def canary_promote_pointer(self, *args: Any, **kwargs: Any) -> None:
        """Pointer promotion is out of scope for PATLAW-159 (see PATLAW-160)."""

        raise PatentHFPublisherV2Error(
            "runtime pointer promotion is not allowed in hf_publisher_v2; "
            "use verify_patent_hf_release_v2 (PATLAW-160)"
        )


# ---------------------------------------------------------------------------
# Test fixture helpers (no operator key embedded)
# ---------------------------------------------------------------------------


def materialize_minimal_release_tree(
    root: str | Path,
    *,
    organization: str = ORGANIZATION,
    version_tag: str = "v2.0.0-test",
    release_root_cid: str = "bafyreipatlaw159testrelease000000000000001",
    repositories: Sequence[str] = CANONICAL_REPOSITORY_NAMES,
) -> dict[str, Any]:
    """Write a compact multi-repo release tree for integration tests."""

    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []

    # Support manifest written last; content artifacts first.
    for repo in repositories:
        rel = f"{REPOS_DIRNAME}/{repo}/data/public/part-000000.parquet"
        body = b"PAR1" + repo.encode("utf-8") + b"\x00" * 16 + b"PAR1"
        path = target.joinpath(*Path(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        digest = sha256(body).hexdigest()
        artifacts.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": len(body),
                "content_cid": f"bafkrei{digest[:32]}",
                "repository": repo,
                "row_count": 1,
            }
        )
        card_rel = f"{REPOS_DIRNAME}/{repo}/README.md"
        card_body = (
            f"# {repo}\n\nJusticeDAO patent-legal test fixture.\n"
        ).encode("utf-8")
        card_path = target.joinpath(*Path(card_rel).parts)
        card_path.write_bytes(card_body)
        card_digest = sha256(card_body).hexdigest()
        artifacts.append(
            {
                "relative_path": card_rel,
                "sha256": card_digest,
                "size_bytes": len(card_body),
                "content_cid": f"bafkrei{card_digest[:32]}",
                "repository": repo,
            }
        )

    # Top-level support files.
    policy_body = b'{"admitted":true,"policy":"v2-test"}\n'
    policy_path = target / "policy-admission.json"
    policy_path.write_bytes(policy_body)
    artifacts.append(
        {
            "relative_path": "policy-admission.json",
            "sha256": sha256(policy_body).hexdigest(),
            "size_bytes": len(policy_body),
            "content_cid": "bafkreipolicyadmissiontest0000001",
        }
    )

    manifest: dict[str, Any] = {
        "artifacts": sorted(artifacts, key=lambda a: a["relative_path"]),
        "dry_run": False,
        "organization": organization,
        "program_id": PROGRAM_ID,
        "release_root_cid": release_root_cid,
        "repositories": [
            {
                "dataset_id": f"{organization}/{repo}",
                "repository": repo,
            }
            for repo in repositories
        ],
        "schema_version": "patent-legal-huggingface-release/v2",
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "version_tag": version_tag,
    }
    # Include the manifest itself after computing its body without self-ref,
    # then rewrite once with the final artifact list including the manifest.
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path = target / RELEASE_MANIFEST_FILENAME
    # Provisional write for digest of content excluding itself.
    support_entry = {
        "relative_path": RELEASE_MANIFEST_FILENAME,
        "sha256": sha256(manifest_bytes).hexdigest(),
        "size_bytes": len(manifest_bytes),
        "content_cid": f"bafkrei{sha256(manifest_bytes).hexdigest()[:32]}",
    }
    manifest["artifacts"] = sorted(
        list(manifest["artifacts"]) + [support_entry],
        key=lambda a: a["relative_path"],
    )
    final_bytes = canonical_json_bytes(manifest)
    # Fix digest to match final bytes.
    for entry in manifest["artifacts"]:
        if entry["relative_path"] == RELEASE_MANIFEST_FILENAME:
            entry["sha256"] = sha256(final_bytes).hexdigest()
            entry["size_bytes"] = len(final_bytes)
            entry["content_cid"] = (
                f"bafkrei{sha256(final_bytes).hexdigest()[:32]}"
            )
    final_bytes = canonical_json_bytes(manifest)
    for entry in manifest["artifacts"]:
        if entry["relative_path"] == RELEASE_MANIFEST_FILENAME:
            entry["sha256"] = sha256(final_bytes).hexdigest()
            entry["size_bytes"] = len(final_bytes)
    final_bytes = canonical_json_bytes(manifest)
    # One last stable pass: digest of bytes that include the correct digest.
    # For tests, write the finalized object and recompute from on-disk after.
    manifest_path.write_bytes(final_bytes)
    on_disk = manifest_path.read_bytes()
    disk_digest = sha256(on_disk).hexdigest()
    for entry in manifest["artifacts"]:
        if entry["relative_path"] == RELEASE_MANIFEST_FILENAME:
            entry["sha256"] = disk_digest
            entry["size_bytes"] = len(on_disk)
    # If digest field changed, rewrite once more so file matches entry.
    stabilized = canonical_json_bytes(manifest)
    # Accept residual mismatch by updating entry to match whatever we write.
    manifest_path.write_bytes(stabilized)
    final_on_disk = manifest_path.read_bytes()
    final_digest = sha256(final_on_disk).hexdigest()
    for entry in manifest["artifacts"]:
        if entry["relative_path"] == RELEASE_MANIFEST_FILENAME:
            entry["sha256"] = final_digest
            entry["size_bytes"] = len(final_on_disk)
    # When the only change is the digest of the manifest itself, a second
    # rewrite would diverge again; tests re-hash from disk in the planner, so
    # keep the planner-facing entry aligned with the *written* bytes above.
    # Re-write entry-aligned manifest: planner trusts local file hash.
    # Simplest stable approach: drop self from artifacts and let planner add
    # nothing extra — planner only uploads listed files, so include a fixed
    # support file instead of self-referential digest games.
    return _rewrite_manifest_without_self_digest_loop(
        target, organization, version_tag, release_root_cid, repositories
    )


def _rewrite_manifest_without_self_digest_loop(
    target: Path,
    organization: str,
    version_tag: str,
    release_root_cid: str,
    repositories: Sequence[str],
) -> dict[str, Any]:
    """Build a stable manifest that does not include itself (planner re-reads)."""

    artifacts: list[dict[str, Any]] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == RELEASE_MANIFEST_FILENAME:
            continue
        body = path.read_bytes()
        digest = sha256(body).hexdigest()
        repo = None
        if rel.startswith(f"{REPOS_DIRNAME}/"):
            repo = rel.split("/")[1]
        artifacts.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": len(body),
                "content_cid": f"bafkrei{digest[:32]}",
                **({"repository": repo} if repo else {}),
            }
        )
    # Fixed quality report as support (not self-referential).
    quality = {
        "orphan_check": "pass",
        "total_data_rows": len(repositories),
    }
    quality_bytes = canonical_json_bytes(quality)
    quality_path = target / "quality-report.json"
    quality_path.write_bytes(quality_bytes)
    q_digest = sha256(quality_bytes).hexdigest()
    artifacts.append(
        {
            "relative_path": "quality-report.json",
            "sha256": q_digest,
            "size_bytes": len(quality_bytes),
            "content_cid": f"bafkrei{q_digest[:32]}",
        }
    )
    # Ensure policy file still present.
    if not (target / "policy-admission.json").is_file():
        policy_body = b'{"admitted":true,"policy":"v2-test"}\n'
        (target / "policy-admission.json").write_bytes(policy_body)

    # Refresh non-manifest artifacts from disk.
    artifacts = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == RELEASE_MANIFEST_FILENAME:
            continue
        body = path.read_bytes()
        digest = sha256(body).hexdigest()
        repo = None
        if rel.startswith(f"{REPOS_DIRNAME}/"):
            repo = rel.split("/")[1]
        artifacts.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": len(body),
                "content_cid": f"bafkrei{digest[:32]}",
                **({"repository": repo} if repo else {}),
            }
        )

    manifest: dict[str, Any] = {
        "artifacts": sorted(artifacts, key=lambda a: a["relative_path"]),
        "dry_run": False,
        "organization": organization,
        "program_id": PROGRAM_ID,
        "release_root_cid": release_root_cid,
        "repositories": [
            {
                "dataset_id": f"{organization}/{repo}",
                "repository": repo,
            }
            for repo in repositories
        ],
        "schema_version": "patent-legal-huggingface-release/v2",
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "version_tag": version_tag,
    }
    # Also list the manifest file with its true digest after write.
    body = canonical_json_bytes(manifest)
    # First write without self entry is fine for planner if we omit it; include
    # a static companion manifest.sha256 file instead.
    manifest_path = target / RELEASE_MANIFEST_FILENAME
    manifest_path.write_bytes(body)
    disk = manifest_path.read_bytes()
    entry = {
        "relative_path": RELEASE_MANIFEST_FILENAME,
        "sha256": sha256(disk).hexdigest(),
        "size_bytes": len(disk),
        "content_cid": f"bafkrei{sha256(disk).hexdigest()[:32]}",
    }
    # For planner honesty: update entry then accept that the on-disk file's
    # digest may differ slightly from the embedded entry.  The planner hashes
    # the *file* and compares to the entry — so keep them equal by *not*
    # embedding the self-digest inside the hashed content.  Store self entry
    # only as a sidecar.
    sidecar = {
        "manifest_sha256": entry["sha256"],
        "manifest_size_bytes": entry["size_bytes"],
        "schema_version": "patent-legal-hf-manifest-sidecar/v1",
    }
    sidecar_path = target / "release-manifest.sha256.json"
    sidecar_bytes = canonical_json_bytes(sidecar)
    sidecar_path.write_bytes(sidecar_bytes)
    # Rebuild artifact list including sidecar (not self-referential manifest).
    artifacts = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == RELEASE_MANIFEST_FILENAME:
            continue
        file_body = path.read_bytes()
        digest = sha256(file_body).hexdigest()
        repo = None
        if rel.startswith(f"{REPOS_DIRNAME}/"):
            repo = rel.split("/")[1]
        artifacts.append(
            {
                "relative_path": rel,
                "sha256": digest,
                "size_bytes": len(file_body),
                "content_cid": f"bafkrei{digest[:32]}",
                **({"repository": repo} if repo else {}),
            }
        )
    manifest = {
        "artifacts": sorted(artifacts, key=lambda a: a["relative_path"]),
        "dry_run": False,
        "organization": organization,
        "program_id": PROGRAM_ID,
        "release_root_cid": release_root_cid,
        "repositories": [
            {
                "dataset_id": f"{organization}/{repo}",
                "repository": repo,
            }
            for repo in repositories
        ],
        "schema_version": "patent-legal-huggingface-release/v2",
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "version_tag": version_tag,
    }
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest


def default_test_base_revisions(
    organization: str = ORGANIZATION,
    repositories: Sequence[str] = CANONICAL_REPOSITORY_NAMES,
    *,
    sha: str = "0" * 40,
) -> dict[str, str]:
    return {
        f"{organization.casefold()}/{repo.casefold()}": sha for repo in repositories
    }


def new_ephemeral_operator_key() -> bytes:
    """Return a fresh random operator key (tests only; never a module constant)."""

    return secrets.token_bytes(32)


__all__ = [
    "APPROVAL_SCHEMA",
    "ApprovalError",
    "ArtifactChangedError",
    "AuthError",
    "BaseRevisionError",
    "ConflictError",
    "CredentialLeakError",
    "DEFAULT_BRANCH_PREFIX",
    "DEFAULT_TARGET_REVISION",
    "DirectMainUploadError",
    "FakeHubService",
    "GOAL_ID",
    "LiveHubApiAdapter",
    "PartialUploadError",
    "PatentHFPublisherV2",
    "PatentHFPublisherV2Error",
    "PlannedArtifact",
    "PROMOTION_RECEIPT_SCHEMA",
    "PromotionReceipt",
    "PublicationApprovalReceipt",
    "PUBLISHER_V2_SCHEMA",
    "RepositoryPromotionResult",
    "RepositoryStageResult",
    "STAGED_RECEIPT_SCHEMA",
    "StagePlan",
    "StagedPRReceipt",
    "approval_binding_payload",
    "create_operator_approval",
    "credentials_resolved",
    "default_test_base_revisions",
    "load_release_manifest",
    "materialize_minimal_release_tree",
    "new_ephemeral_operator_key",
    "plan_stage_from_local_root",
    "publisher_can_generate_operator_approval",
    "reject_credentials_in_payload",
    "resolve_hub_token",
    "sign_approval_binding",
    "verify_operator_approval",
]
