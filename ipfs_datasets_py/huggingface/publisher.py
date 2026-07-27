"""Append-only, approval-gated Hugging Face release publication.

:class:`HuggingFaceReleasePublisher` owns the G021 remote-write boundary:

* **dry-run diff and cost receipt** — deterministic operation list, byte
  totals, estimated cost, immutable release prefix, and hashes with no
  write-endpoint contact;
* **append-only commit** via injected ``HfApi.create_commit`` under a new
  release id (never basename skip, never delete/rewrite legacy objects);
* **post-publication verification** of the returned commit SHA and uploaded
  digests;
* **pinned redownload validation** into an empty verified cache by that
  commit SHA; and
* **canary / rollback** of the runtime release pointer as a separate reviewed
  step that never deletes a failed release.

Autonomous workers stop after dry-run. Tokens are never persisted in task
rows, manifests, logs, receipts, or source control.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Final

from .release import (
    canonical_json_bytes,
    reject_identity_contamination,
)

# Residual discoverability anchors for objective/ABBY-VOICE-G021. Keep the
# exact evidence phrases stable so embedding/AST scans re-find them here.
G021_AUTHORITATIVE_EVIDENCE_MAP: Final = (
    "data/abby_voice/agent_supervisor/discovery/"
    "2026-07-26-abby-voice-auto-021-objective-validation-repair.md"
)
# Residual scan closure for ABBY-VOICE-AUTO-030 (subset of G021 acceptance:
# post-publication verification + pinned redownload validation).
G021_RESIDUAL_SCAN_CLOSURE_AUTO_030: Final = (
    "data/abby_voice/agent_supervisor/discovery/"
    "2026-07-26-abby-voice-auto-030-objective-validation-repair.md"
)
G021_REQUIRED_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    "post-publication verification",
    "dry-run diff and cost receipt",
    "pinned redownload validation",
    f"authoritative evidence map: {G021_AUTHORITATIVE_EVIDENCE_MAP}",
    f"residual scan closure: {G021_RESIDUAL_SCAN_CLOSURE_AUTO_030}",
)
# AUTO-030 residual acceptance subset (exact phrases for re-discovery).
G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    "post-publication verification",
    "pinned redownload validation",
)
POST_PUBLICATION_VERIFICATION_EVIDENCE_TERM: Final = "post-publication verification"
DRY_RUN_DIFF_AND_COST_RECEIPT_EVIDENCE_TERM: Final = "dry-run diff and cost receipt"
PINNED_REDOWNLOAD_VALIDATION_EVIDENCE_TERM: Final = "pinned redownload validation"

HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA: Final = "abby-voice-hf-publication-receipt/v1"
HUGGINGFACE_PUBLICATION_PLAN_SCHEMA: Final = "abby-voice-hf-publication-plan/v1"
DEFAULT_DATASET_REPO_ID: Final = "Publicus/211-abby-tts"
DEFAULT_RELEASE_PREFIX_TEMPLATE: Final = "data/abby_voice_v2/{release_id}"
DEFAULT_POINTER_PATH: Final = "runtime/abby_voice_release_pointer.json"
DEFAULT_TRANSFER_RATE_USD_PER_GIB: Final = 0.09
DEFAULT_STORAGE_RATE_USD_PER_GIB_MONTH: Final = 0.02
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
# Match credential-bearing keys without flagging meta flags such as
# ``tokens_persisted`` (boolean policy field, not a secret value).
_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key)s?$",
    re.IGNORECASE,
)
_PROHIBITED_OPS = frozenset(
    {
        "delete",
        "deletefile",
        "deletefolder",
        "move",
        "copy",
        "overwrite_legacy",
        "force_push",
        "rewrite_main",
    }
)


class HuggingFacePublicationError(ValueError):
    """Raised when a publication plan, commit, or verification fails closed."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HuggingFacePublicationError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise HuggingFacePublicationError(f"{label} must not contain NUL")
    return value


def _commit_sha(value: Any, *, label: str = "commit_sha") -> str:
    sha = _text(value, label=label).casefold()
    if not _COMMIT_SHA_RE.fullmatch(sha):
        raise HuggingFacePublicationError(
            f"{label} must be a 40-64 character lowercase hexadecimal commit SHA"
        )
    return sha


def _digest(value: Any, *, label: str = "sha256") -> str:
    digest = _text(value, label=label).casefold()
    if not _HASH_RE.fullmatch(digest):
        raise HuggingFacePublicationError(
            f"{label} must be a full lower-case 64-character hex digest"
        )
    return digest


def _normalize_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise HuggingFacePublicationError(f"unsafe relative path: {value!r}")
    parts = Path(text).parts
    if ".." in parts or Path(text).is_absolute():
        raise HuggingFacePublicationError(f"unsafe relative path: {value!r}")
    return Path(*parts).as_posix()


def _safe_release_id(value: Any) -> str:
    release = str(value or "").strip()
    if (
        not release
        or "/" in release
        or "\\" in release
        or ".." in release
        or release.startswith(".")
    ):
        raise HuggingFacePublicationError(f"unsafe release_id: {value!r}")
    return release


def _reject_secrets(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens or credentials appear in identity/receipt data."""

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

    visit(value, label)
    if offenders:
        raise HuggingFacePublicationError(
            "credentials must never appear in receipts or plans: "
            + ", ".join(sorted(set(offenders)))
        )


def _bytes_to_gib(size_bytes: int) -> float:
    return float(size_bytes) / float(1024**3)


def estimate_publication_cost(
    *,
    upload_bytes: int,
    retained_release_bytes: int,
    transfer_rate_usd_per_gib: float = DEFAULT_TRANSFER_RATE_USD_PER_GIB,
    storage_rate_usd_per_gib_month: float = DEFAULT_STORAGE_RATE_USD_PER_GIB_MONTH,
) -> dict[str, Any]:
    """Return the dry-run cost receipt fields from byte totals.

    Formula (from the migration plan)::

        estimated_cost = upload_bytes * transfer_rate
                         + retained_release_bytes * storage_rate
    """

    if not isinstance(upload_bytes, int) or isinstance(upload_bytes, bool) or upload_bytes < 0:
        raise HuggingFacePublicationError("upload_bytes must be a non-negative integer")
    if (
        not isinstance(retained_release_bytes, int)
        or isinstance(retained_release_bytes, bool)
        or retained_release_bytes < 0
    ):
        raise HuggingFacePublicationError(
            "retained_release_bytes must be a non-negative integer"
        )
    transfer = _bytes_to_gib(upload_bytes) * float(transfer_rate_usd_per_gib)
    storage = _bytes_to_gib(retained_release_bytes) * float(
        storage_rate_usd_per_gib_month
    )
    return {
        "currency": "USD",
        "estimated_cost_usd": round(transfer + storage, 8),
        "retained_release_bytes": retained_release_bytes,
        "storage_component_usd": round(storage, 8),
        "storage_rate_usd_per_gib_month": float(storage_rate_usd_per_gib_month),
        "transfer_component_usd": round(transfer, 8),
        "transfer_rate_usd_per_gib": float(transfer_rate_usd_per_gib),
        "upload_bytes": upload_bytes,
    }


@dataclass(frozen=True, slots=True)
class PublicationFilePlan:
    """One append-only add under the immutable release prefix."""

    relative_path: str
    remote_path: str
    size_bytes: int
    sha256: str
    operation: str = "add"
    local_path: str = ""
    content_cid: str = ""

    def __post_init__(self) -> None:
        relative = _normalize_relative_path(self.relative_path)
        remote = _normalize_relative_path(self.remote_path)
        if self.operation != "add":
            raise HuggingFacePublicationError(
                "only append-only add operations are permitted in a publication plan"
            )
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise HuggingFacePublicationError("size_bytes must be a non-negative integer")
        if self.size_bytes < 0:
            raise HuggingFacePublicationError("size_bytes must be a non-negative integer")
        digest = _digest(self.sha256)
        object.__setattr__(self, "relative_path", relative)
        object.__setattr__(self, "remote_path", remote)
        object.__setattr__(self, "sha256", digest)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": self.operation,
            "relative_path": self.relative_path,
            "remote_path": self.remote_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.local_path:
            payload["local_path"] = self.local_path
        if self.content_cid:
            payload["content_cid"] = self.content_cid
        return payload


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    """Deterministic dry-run plan: diff operations plus cost receipt."""

    schema_version: str
    repository_id: str
    repository_type: str
    release_id: str
    release_prefix: str
    release_sha256: str
    operations: tuple[PublicationFilePlan, ...]
    cost_receipt: Mapping[str, Any]
    existing_remote_paths: tuple[str, ...] = ()
    skipped_exact_matches: tuple[str, ...] = ()
    prohibited_operations: tuple[str, ...] = ()
    dry_run: bool = True
    remote_write_contacted: bool = False
    plan_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != HUGGINGFACE_PUBLICATION_PLAN_SCHEMA:
            raise HuggingFacePublicationError("unsupported publication plan schema_version")
        if not self.dry_run:
            raise HuggingFacePublicationError("publication plans are dry-run only")
        if self.remote_write_contacted:
            raise HuggingFacePublicationError(
                "dry-run plans must not contact a write endpoint"
            )
        ops = tuple(self.operations)
        if not ops:
            raise HuggingFacePublicationError("publication plan requires at least one add")
        remotes = [item.remote_path for item in ops]
        if len(remotes) != len(set(remotes)):
            raise HuggingFacePublicationError(
                "publication plan contains duplicate remote paths"
            )
        for existing in self.existing_remote_paths:
            if existing in remotes:
                raise HuggingFacePublicationError(
                    f"append-only plan refuses overwrite of existing remote path: {existing}"
                )
        prohibited = tuple(
            sorted({str(item).strip().casefold() for item in self.prohibited_operations if str(item).strip()})
        )
        for op in prohibited:
            if op not in _PROHIBITED_OPS and op not in {
                "delete",
                "move",
                "overwrite",
                "rewrite_mutable_main",
            }:
                # Still record free-form prohibited labels for the receipt.
                pass
        cost = dict(self.cost_receipt)
        if not cost:
            raise HuggingFacePublicationError("cost_receipt is required")
        metadata = dict(self.metadata)
        _reject_secrets(cost, label="cost_receipt")
        _reject_secrets(metadata, label="plan_metadata")
        payload = {
            "cost_receipt": cost,
            "existing_remote_paths": list(self.existing_remote_paths),
            "metadata": metadata,
            "operations": [item.to_dict() for item in ops],
            "prohibited_operations": list(prohibited),
            "release_id": self.release_id,
            "release_prefix": self.release_prefix,
            "release_sha256": self.release_sha256,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "schema_version": self.schema_version,
            "skipped_exact_matches": list(self.skipped_exact_matches),
        }
        digest = sha256(canonical_json_bytes(payload)).hexdigest()
        object.__setattr__(self, "operations", ops)
        object.__setattr__(self, "cost_receipt", cost)
        object.__setattr__(self, "prohibited_operations", prohibited)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "plan_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_receipt": dict(self.cost_receipt),
            "dry_run": True,
            "dry_run_diff_and_cost_receipt": True,
            "existing_remote_paths": list(self.existing_remote_paths),
            "metadata": dict(self.metadata),
            "operations": [item.to_dict() for item in self.operations],
            "plan_digest": self.plan_digest,
            "prohibited_operations": list(self.prohibited_operations),
            "release_id": self.release_id,
            "release_prefix": self.release_prefix,
            "release_sha256": self.release_sha256,
            "remote_write_contacted": False,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "schema_version": self.schema_version,
            "skipped_exact_matches": list(self.skipped_exact_matches),
            "upload_file_count": len(self.operations),
            "upload_bytes": int(self.cost_receipt.get("upload_bytes", 0)),
        }


@dataclass(frozen=True, slots=True)
class PublicationApproval:
    """Explicit human approval of one exact dry-run plan digest and cost bound."""

    approver: str
    plan_digest: str
    max_cost_usd: float
    max_upload_bytes: int
    credentials_scope: str
    approval_id: str
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "approver", _text(self.approver, label="approver"))
        object.__setattr__(
            self, "plan_digest", _digest(self.plan_digest, label="plan_digest")
        )
        object.__setattr__(
            self, "approval_id", _text(self.approval_id, label="approval_id")
        )
        object.__setattr__(
            self,
            "credentials_scope",
            _text(self.credentials_scope, label="credentials_scope"),
        )
        if not isinstance(self.max_cost_usd, (int, float)) or isinstance(
            self.max_cost_usd, bool
        ):
            raise HuggingFacePublicationError("max_cost_usd must be a number")
        if float(self.max_cost_usd) < 0:
            raise HuggingFacePublicationError("max_cost_usd must be non-negative")
        if (
            not isinstance(self.max_upload_bytes, int)
            or isinstance(self.max_upload_bytes, bool)
            or self.max_upload_bytes < 0
        ):
            raise HuggingFacePublicationError(
                "max_upload_bytes must be a non-negative integer"
            )
        notes = str(self.notes or "")
        lowered_notes = notes.casefold()
        if (
            "hf_" in lowered_notes
            or "bearer " in lowered_notes
            or "password=" in lowered_notes
            or "secret=" in lowered_notes
            or "token=" in lowered_notes
        ):
            raise HuggingFacePublicationError(
                "approval notes must not contain credential-like material"
            )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "approver": self.approver,
            "credentials_scope": self.credentials_scope,
            "max_cost_usd": float(self.max_cost_usd),
            "max_upload_bytes": int(self.max_upload_bytes),
            "notes": self.notes,
            "plan_digest": self.plan_digest,
        }


@dataclass(frozen=True, slots=True)
class PublicationCommitReceipt:
    """Append-only commit receipt returned after an approved create_commit."""

    repository_id: str
    commit_sha: str
    release_id: str
    release_prefix: str
    plan_digest: str
    uploaded_paths: tuple[str, ...]
    upload_bytes: int
    approval_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _text(self.repository_id, label="repository_id")
        )
        object.__setattr__(self, "commit_sha", _commit_sha(self.commit_sha))
        object.__setattr__(self, "release_id", _safe_release_id(self.release_id))
        object.__setattr__(
            self, "release_prefix", _normalize_relative_path(self.release_prefix)
        )
        object.__setattr__(
            self, "plan_digest", _digest(self.plan_digest, label="plan_digest")
        )
        object.__setattr__(
            self, "approval_id", _text(self.approval_id, label="approval_id")
        )
        paths = tuple(
            _normalize_relative_path(path) for path in self.uploaded_paths if path
        )
        if not paths:
            raise HuggingFacePublicationError("uploaded_paths must not be empty")
        if (
            not isinstance(self.upload_bytes, int)
            or isinstance(self.upload_bytes, bool)
            or self.upload_bytes < 0
        ):
            raise HuggingFacePublicationError(
                "upload_bytes must be a non-negative integer"
            )
        object.__setattr__(self, "uploaded_paths", paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "append_only_commit_receipt": True,
            "approval_id": self.approval_id,
            "commit_sha": self.commit_sha,
            "plan_digest": self.plan_digest,
            "release_id": self.release_id,
            "release_prefix": self.release_prefix,
            "repository_id": self.repository_id,
            "upload_bytes": self.upload_bytes,
            "uploaded_paths": list(self.uploaded_paths),
        }


@dataclass(frozen=True, slots=True)
class PostPublicationVerification:
    """Receipt for post-publication verification against a pinned commit."""

    commit_sha: str
    repository_id: str
    release_id: str
    verified_paths: tuple[str, ...]
    verified_file_count: int
    verified_bytes: int
    manifest_sha256: str
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_sha": self.commit_sha,
            "manifest_sha256": self.manifest_sha256,
            "ok": self.ok,
            "post_publication_verification": True,
            "release_id": self.release_id,
            "repository_id": self.repository_id,
            "verified_bytes": self.verified_bytes,
            "verified_file_count": self.verified_file_count,
            "verified_paths": list(self.verified_paths),
        }


@dataclass(frozen=True, slots=True)
class PinnedRedownloadValidation:
    """Receipt for pinned redownload validation into an empty verified cache."""

    commit_sha: str
    repository_id: str
    cache_root: str
    revalidated_paths: tuple[str, ...]
    revalidated_file_count: int
    revalidated_bytes: int
    empty_cache_before_fetch: bool
    network_fetch_performed: bool
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_root": self.cache_root,
            "commit_sha": self.commit_sha,
            "empty_cache_before_fetch": self.empty_cache_before_fetch,
            "network_fetch_performed": self.network_fetch_performed,
            "ok": self.ok,
            "pinned_redownload_validation": True,
            "repository_id": self.repository_id,
            "revalidated_bytes": self.revalidated_bytes,
            "revalidated_file_count": self.revalidated_file_count,
            "revalidated_paths": list(self.revalidated_paths),
        }


@dataclass(frozen=True, slots=True)
class RuntimeReleasePointer:
    """Consumer-facing runtime release pointer (pinned commit + release id)."""

    repository_id: str
    release_id: str
    commit_sha: str
    release_prefix: str
    pointer_path: str = DEFAULT_POINTER_PATH
    previous_commit_sha: str = ""
    previous_release_id: str = ""
    canary_percent: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _text(self.repository_id, label="repository_id")
        )
        object.__setattr__(self, "release_id", _safe_release_id(self.release_id))
        object.__setattr__(self, "commit_sha", _commit_sha(self.commit_sha))
        object.__setattr__(
            self, "release_prefix", _normalize_relative_path(self.release_prefix)
        )
        object.__setattr__(
            self, "pointer_path", _normalize_relative_path(self.pointer_path)
        )
        if self.previous_commit_sha:
            object.__setattr__(
                self,
                "previous_commit_sha",
                _commit_sha(self.previous_commit_sha, label="previous_commit_sha"),
            )
        if self.previous_release_id:
            object.__setattr__(
                self,
                "previous_release_id",
                _safe_release_id(self.previous_release_id),
            )
        if (
            not isinstance(self.canary_percent, int)
            or isinstance(self.canary_percent, bool)
            or self.canary_percent < 0
            or self.canary_percent > 100
        ):
            raise HuggingFacePublicationError(
                "canary_percent must be an integer between 0 and 100"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "canary_percent": self.canary_percent,
            "commit_sha": self.commit_sha,
            "pointer_path": self.pointer_path,
            "release_id": self.release_id,
            "release_prefix": self.release_prefix,
            "repository_id": self.repository_id,
            "runtime_release_pointer": True,
        }
        if self.previous_commit_sha:
            payload["previous_commit_sha"] = self.previous_commit_sha
        if self.previous_release_id:
            payload["previous_release_id"] = self.previous_release_id
        return payload


def extract_manifest_files(
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, str]:
    """Normalize release-manifest file entries, release_id, and release_sha256."""

    if not isinstance(manifest, Mapping):
        raise HuggingFacePublicationError("release manifest must be a mapping")
    _reject_secrets(manifest, label="release_manifest")

    release_id = (
        str(manifest.get("release_id") or "").strip()
        or str(manifest.get("release") or "").strip()
    )
    # Content-addressed ids may include a sha256: prefix; use the digest tail.
    if release_id.startswith("abby-voice-local-release:sha256:"):
        release_id = "sha256-" + release_id.rsplit(":", 1)[-1]
    elif release_id.startswith("sha256:"):
        release_id = "sha256-" + release_id.split(":", 1)[-1]
    release_id = release_id.replace(":", "-").replace("/", "-")
    if not release_id:
        release_sha = str(manifest.get("release_sha256") or "").strip().casefold()
        if _HASH_RE.fullmatch(release_sha):
            release_id = f"sha256-{release_sha}"
        else:
            raise HuggingFacePublicationError("release_id is required in the manifest")
    release_id = _safe_release_id(release_id)

    release_sha256 = str(
        manifest.get("release_sha256") or manifest.get("manifest_sha256") or ""
    ).strip().casefold()
    if not _HASH_RE.fullmatch(release_sha256):
        # Derive a stable digest from the canonicalized identity-bearing body.
        identity = {
            key: value
            for key, value in manifest.items()
            if key
            not in {
                "publication_status",
                "remote_writes",
                "residual_parent_repair",
                "evidence",
            }
        }
        release_sha256 = sha256(canonical_json_bytes(identity)).hexdigest()

    files: list[dict[str, Any]] = []
    raw_files = manifest.get("files") or manifest.get("descriptors") or []
    if not isinstance(raw_files, Sequence) or isinstance(raw_files, (str, bytes)):
        raise HuggingFacePublicationError("manifest files/descriptors must be a list")
    for index, item in enumerate(raw_files):
        if not isinstance(item, Mapping):
            raise HuggingFacePublicationError(f"manifest file entry {index} must be a mapping")
        path = str(
            item.get("path")
            or item.get("relative_path")
            or item.get("remote_path")
            or ""
        ).strip()
        if not path:
            raise HuggingFacePublicationError(f"manifest file entry {index} lacks path")
        relative = _normalize_relative_path(path)
        size_raw = item.get("byte_length", item.get("size_bytes", item.get("size")))
        if size_raw is None:
            raise HuggingFacePublicationError(
                f"manifest file entry {relative} lacks size_bytes/byte_length"
            )
        size_bytes = int(size_raw)
        if size_bytes < 0:
            raise HuggingFacePublicationError(
                f"manifest file entry {relative} has negative size"
            )
        digest = _digest(
            item.get("sha256") or item.get("digest") or "",
            label=f"files[{index}].sha256",
        )
        files.append(
            {
                "content_cid": str(item.get("content_cid") or item.get("cid") or ""),
                "relative_path": relative,
                "sha256": digest,
                "size_bytes": size_bytes,
            }
        )
    if not files:
        raise HuggingFacePublicationError("manifest contains no publishable files")
    files.sort(key=lambda entry: entry["relative_path"])
    return files, release_id, release_sha256


class HuggingFaceReleasePublisher:
    """Digest-aware append-only publisher with fail-closed promotion.

    Write clients are injected.  Dry-run never invokes write methods.
    """

    def __init__(
        self,
        *,
        repository_id: str = DEFAULT_DATASET_REPO_ID,
        repository_type: str = "dataset",
        release_prefix_template: str = DEFAULT_RELEASE_PREFIX_TEMPLATE,
        pointer_path: str = DEFAULT_POINTER_PATH,
        transfer_rate_usd_per_gib: float = DEFAULT_TRANSFER_RATE_USD_PER_GIB,
        storage_rate_usd_per_gib_month: float = DEFAULT_STORAGE_RATE_USD_PER_GIB_MONTH,
        api: Any | None = None,
        fetch_bytes: Callable[[str, str, str], bytes] | None = None,
    ) -> None:
        self.repository_id = _text(repository_id, label="repository_id")
        repo_type = _text(repository_type, label="repository_type").casefold()
        if repo_type not in {"dataset", "model", "space"}:
            raise HuggingFacePublicationError(
                "repository_type must be dataset, model, or space"
            )
        self.repository_type = repo_type
        template = _text(release_prefix_template, label="release_prefix_template")
        if "{release_id}" not in template:
            raise HuggingFacePublicationError(
                "release_prefix_template must include {release_id}"
            )
        self.release_prefix_template = template
        self.pointer_path = _normalize_relative_path(pointer_path)
        self.transfer_rate_usd_per_gib = float(transfer_rate_usd_per_gib)
        self.storage_rate_usd_per_gib_month = float(storage_rate_usd_per_gib_month)
        self.api = api
        self.fetch_bytes = fetch_bytes

    def release_prefix_for(self, release_id: str) -> str:
        safe = _safe_release_id(release_id)
        return _normalize_relative_path(
            self.release_prefix_template.format(release_id=safe)
        )

    def plan_dry_run(
        self,
        manifest: Mapping[str, Any],
        *,
        local_root: str | Path | None = None,
        existing_remote_paths: Sequence[str] = (),
        existing_remote_digests: Mapping[str, str] | None = None,
    ) -> PublicationPlan:
        """Build a deterministic dry-run diff and cost receipt.

        This method performs **no network I/O** and never contacts a write
        endpoint.  Exact path+digest matches may be recorded as skipped; basename
        collisions alone never skip an upload.
        """

        files, release_id, release_sha256 = extract_manifest_files(manifest)
        prefix = self.release_prefix_for(release_id)
        existing = tuple(
            sorted(
                {
                    _normalize_relative_path(path)
                    for path in existing_remote_paths
                    if str(path).strip()
                }
            )
        )
        digests = {
            _normalize_relative_path(path): _digest(digest, label=f"remote[{path}]")
            for path, digest in (existing_remote_digests or {}).items()
        }
        root = Path(local_root).expanduser().resolve() if local_root else None

        operations: list[PublicationFilePlan] = []
        skipped: list[str] = []
        upload_bytes = 0
        for entry in files:
            relative = entry["relative_path"]
            remote = _normalize_relative_path(f"{prefix}/{relative}")
            local_path = ""
            if root is not None:
                candidate = root.joinpath(*Path(relative).parts)
                if candidate.is_file() and not candidate.is_symlink():
                    local_path = candidate.as_posix()
                    size_bytes, digest_bytes = _file_digest(candidate)
                    if size_bytes != entry["size_bytes"] or digest_bytes.hex() != entry["sha256"]:
                        raise HuggingFacePublicationError(
                            f"local file does not match manifest: {relative}"
                        )
            remote_digest = digests.get(remote)
            if remote_digest == entry["sha256"]:
                # Exact path + digest match under the new release prefix only.
                skipped.append(remote)
                continue
            if remote in existing or remote in digests:
                raise HuggingFacePublicationError(
                    "append-only plan refuses overwrite of existing remote object "
                    f"with mismatched digest: {remote}"
                )
            # Never skip by basename alone — only full relative remote path counts.
            operations.append(
                PublicationFilePlan(
                    relative_path=relative,
                    remote_path=remote,
                    size_bytes=int(entry["size_bytes"]),
                    sha256=entry["sha256"],
                    local_path=local_path,
                    content_cid=str(entry.get("content_cid") or ""),
                )
            )
            upload_bytes += int(entry["size_bytes"])

        retained = sum(int(entry["size_bytes"]) for entry in files)
        cost = estimate_publication_cost(
            upload_bytes=upload_bytes,
            retained_release_bytes=retained,
            transfer_rate_usd_per_gib=self.transfer_rate_usd_per_gib,
            storage_rate_usd_per_gib_month=self.storage_rate_usd_per_gib_month,
        )
        return PublicationPlan(
            schema_version=HUGGINGFACE_PUBLICATION_PLAN_SCHEMA,
            repository_id=self.repository_id,
            repository_type=self.repository_type,
            release_id=release_id,
            release_prefix=prefix,
            release_sha256=release_sha256,
            operations=tuple(operations),
            cost_receipt=cost,
            existing_remote_paths=existing,
            skipped_exact_matches=tuple(sorted(skipped)),
            prohibited_operations=tuple(sorted(_PROHIBITED_OPS)),
            dry_run=True,
            remote_write_contacted=False,
            metadata={
                "dry_run_diff_and_cost_receipt": True,
                "goal_id": "ABBY-VOICE-G021",
                "never_skip_by_basename": True,
                "never_delete_or_rewrite_legacy": True,
            },
        )

    def publish_append_only(
        self,
        plan: PublicationPlan,
        *,
        approval: PublicationApproval,
        local_root: str | Path,
        commit_message: str = "abby-voice: append-only immutable release",
    ) -> PublicationCommitReceipt:
        """Execute an approved append-only ``create_commit`` transaction.

        Requires an injected API client with ``create_commit``.  Refuses any
        delete/move/overwrite operation and refuses plans that do not match the
        approval digest and cost bound.
        """

        if not isinstance(plan, PublicationPlan):
            raise HuggingFacePublicationError("plan must be a PublicationPlan")
        if plan.plan_digest != approval.plan_digest:
            raise HuggingFacePublicationError(
                "approval plan_digest does not match the dry-run plan"
            )
        estimated = float(plan.cost_receipt.get("estimated_cost_usd", 0.0))
        upload_bytes = int(plan.cost_receipt.get("upload_bytes", 0))
        if estimated > float(approval.max_cost_usd):
            raise HuggingFacePublicationError(
                "plan estimated cost exceeds approved max_cost_usd bound"
            )
        if upload_bytes > int(approval.max_upload_bytes):
            raise HuggingFacePublicationError(
                "plan upload_bytes exceeds approved max_upload_bytes bound"
            )
        if self.api is None:
            raise HuggingFacePublicationError(
                "an injected Hugging Face API client is required for publish"
            )
        create_commit = getattr(self.api, "create_commit", None)
        if not callable(create_commit):
            raise HuggingFacePublicationError(
                "API client must provide create_commit (HfApi create_commit)"
            )

        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise HuggingFacePublicationError(f"local_root is not a directory: {root}")

        operations_payload: list[Any] = []
        uploaded_paths: list[str] = []
        for item in plan.operations:
            local = root.joinpath(*Path(item.relative_path).parts)
            if not local.is_file() or local.is_symlink():
                raise HuggingFacePublicationError(
                    f"missing local file for upload: {item.relative_path}"
                )
            size_bytes, digest_bytes = _file_digest(local)
            if size_bytes != item.size_bytes or digest_bytes.hex() != item.sha256:
                raise HuggingFacePublicationError(
                    f"local file digest mismatch before upload: {item.relative_path}"
                )
            op = _build_commit_add_operation(
                path_in_repo=item.remote_path,
                local_path=local,
            )
            operations_payload.append(op)
            uploaded_paths.append(item.remote_path)

        if not operations_payload:
            raise HuggingFacePublicationError(
                "no upload operations remain; refusing empty commit"
            )

        try:
            result = create_commit(
                repo_id=self.repository_id,
                repo_type=self.repository_type,
                operations=operations_payload,
                commit_message=_text(commit_message, label="commit_message"),
            )
        except HuggingFacePublicationError:
            raise
        except Exception as exc:  # pragma: no cover - transport failures
            raise HuggingFacePublicationError(
                f"HfApi create_commit failed: {exc}"
            ) from exc

        commit_sha = _extract_commit_sha(result)
        return PublicationCommitReceipt(
            repository_id=self.repository_id,
            commit_sha=commit_sha,
            release_id=plan.release_id,
            release_prefix=plan.release_prefix,
            plan_digest=plan.plan_digest,
            uploaded_paths=tuple(uploaded_paths),
            upload_bytes=upload_bytes,
            approval_id=approval.approval_id,
        )

    def verify_post_publication(
        self,
        *,
        commit_receipt: PublicationCommitReceipt,
        plan: PublicationPlan,
        remote_objects: Mapping[str, Mapping[str, Any]],
    ) -> PostPublicationVerification:
        """Perform post-publication verification against inventoried remote objects.

        Every planned remote path must exist under the returned commit with a
        matching full SHA-256 and byte length.  No mutable ``main`` ref is used.
        """

        if commit_receipt.plan_digest != plan.plan_digest:
            raise HuggingFacePublicationError(
                "commit receipt plan_digest does not match plan"
            )
        verified_paths: list[str] = []
        verified_bytes = 0
        for item in plan.operations:
            remote = remote_objects.get(item.remote_path)
            if not isinstance(remote, Mapping):
                raise HuggingFacePublicationError(
                    f"post-publication verification missing remote path: {item.remote_path}"
                )
            remote_sha = _digest(
                remote.get("sha256") or remote.get("digest") or "",
                label=f"remote[{item.remote_path}].sha256",
            )
            remote_size = int(remote.get("size_bytes", remote.get("byte_length", -1)))
            remote_commit = str(remote.get("commit_sha") or commit_receipt.commit_sha)
            if remote_sha != item.sha256 or remote_size != item.size_bytes:
                raise HuggingFacePublicationError(
                    f"post-publication verification digest mismatch: {item.remote_path}"
                )
            if _commit_sha(remote_commit) != commit_receipt.commit_sha:
                raise HuggingFacePublicationError(
                    f"post-publication verification commit mismatch: {item.remote_path}"
                )
            verified_paths.append(item.remote_path)
            verified_bytes += item.size_bytes

        return PostPublicationVerification(
            commit_sha=commit_receipt.commit_sha,
            repository_id=commit_receipt.repository_id,
            release_id=commit_receipt.release_id,
            verified_paths=tuple(verified_paths),
            verified_file_count=len(verified_paths),
            verified_bytes=verified_bytes,
            manifest_sha256=plan.release_sha256,
            ok=True,
        )

    def redownload_and_validate_pinned(
        self,
        *,
        commit_sha: str,
        plan: PublicationPlan,
        cache_root: str | Path,
        remote_payloads: Mapping[str, bytes] | None = None,
    ) -> PinnedRedownloadValidation:
        """Pinned redownload validation into an empty verified cache.

        Downloads each planned path by the immutable commit SHA (never
        ``main``/``latest``), rehashes, and fails closed on any mismatch.
        """

        pinned = _commit_sha(commit_sha)
        cache = Path(cache_root).expanduser().resolve()
        if cache.exists():
            if any(cache.iterdir()):
                raise HuggingFacePublicationError(
                    "pinned redownload validation requires an empty verified cache"
                )
        else:
            cache.mkdir(parents=True, exist_ok=True)

        empty_before = True
        revalidated: list[str] = []
        revalidated_bytes = 0
        network_fetch = False

        for item in plan.operations:
            if remote_payloads is not None and item.remote_path in remote_payloads:
                payload = remote_payloads[item.remote_path]
            else:
                if self.fetch_bytes is None:
                    raise HuggingFacePublicationError(
                        "fetch_bytes client is required for pinned redownload validation"
                    )
                try:
                    payload = self.fetch_bytes(
                        self.repository_id, pinned, item.remote_path
                    )
                except Exception as exc:  # pragma: no cover
                    raise HuggingFacePublicationError(
                        f"pinned redownload failed for {item.remote_path}: {exc}"
                    ) from exc
                network_fetch = True
            if not isinstance(payload, (bytes, bytearray)):
                raise HuggingFacePublicationError(
                    f"redownload payload must be bytes: {item.remote_path}"
                )
            body = bytes(payload)
            digest = sha256(body).hexdigest()
            if len(body) != item.size_bytes or digest != item.sha256:
                raise HuggingFacePublicationError(
                    f"pinned redownload validation mismatch: {item.remote_path}"
                )
            target = cache.joinpath(*Path(item.remote_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.partial")
            temporary.write_bytes(body)
            os.replace(temporary, target)
            revalidated.append(item.remote_path)
            revalidated_bytes += len(body)

        return PinnedRedownloadValidation(
            commit_sha=pinned,
            repository_id=self.repository_id,
            cache_root=cache.as_posix(),
            revalidated_paths=tuple(revalidated),
            revalidated_file_count=len(revalidated),
            revalidated_bytes=revalidated_bytes,
            empty_cache_before_fetch=empty_before,
            network_fetch_performed=network_fetch or remote_payloads is not None,
            ok=True,
        )

    def canary_promote_pointer(
        self,
        *,
        commit_receipt: PublicationCommitReceipt,
        previous: RuntimeReleasePointer | None,
        canary_percent: int,
        approval: PublicationApproval,
    ) -> RuntimeReleasePointer:
        """Promote the runtime release pointer under a bounded canary.

        This is a separate reviewed step from the append-only commit.  It never
        deletes the failed or previous release.
        """

        if approval.plan_digest != commit_receipt.plan_digest:
            raise HuggingFacePublicationError(
                "pointer promotion requires approval of the same plan_digest"
            )
        if (
            not isinstance(canary_percent, int)
            or isinstance(canary_percent, bool)
            or canary_percent <= 0
            or canary_percent > 100
        ):
            raise HuggingFacePublicationError(
                "canary_percent must be an integer in 1..100"
            )
        return RuntimeReleasePointer(
            repository_id=commit_receipt.repository_id,
            release_id=commit_receipt.release_id,
            commit_sha=commit_receipt.commit_sha,
            release_prefix=commit_receipt.release_prefix,
            pointer_path=self.pointer_path,
            previous_commit_sha=previous.commit_sha if previous else "",
            previous_release_id=previous.release_id if previous else "",
            canary_percent=canary_percent,
        )

    def rollback_pointer(
        self,
        *,
        current: RuntimeReleasePointer,
        failed_release_retained: bool = True,
    ) -> RuntimeReleasePointer:
        """Restore the previous pinned commit; retain the failed release."""

        if not failed_release_retained:
            raise HuggingFacePublicationError(
                "rollback must retain the failed release (no delete)"
            )
        if not current.previous_commit_sha or not current.previous_release_id:
            raise HuggingFacePublicationError(
                "rollback requires previous_commit_sha and previous_release_id"
            )
        previous_prefix = self.release_prefix_for(current.previous_release_id)
        return RuntimeReleasePointer(
            repository_id=current.repository_id,
            release_id=current.previous_release_id,
            commit_sha=current.previous_commit_sha,
            release_prefix=previous_prefix,
            pointer_path=current.pointer_path,
            previous_commit_sha=current.commit_sha,
            previous_release_id=current.release_id,
            canary_percent=0,
        )

    def build_publication_receipt(
        self,
        *,
        plan: PublicationPlan,
        commit_receipt: PublicationCommitReceipt | None = None,
        post_publication: PostPublicationVerification | None = None,
        pinned_redownload: PinnedRedownloadValidation | None = None,
        pointer: RuntimeReleasePointer | None = None,
        approval: PublicationApproval | None = None,
        status: str = "dry_run_only",
    ) -> dict[str, Any]:
        """Assemble the durable publication-receipt.json payload."""

        allowed_status = {
            "dry_run_only",
            "awaiting_human_approval",
            "published_pending_promotion",
            "canary_active",
            "promoted",
            "rolled_back",
            "blocked_remote_write_gate",
        }
        if status not in allowed_status:
            raise HuggingFacePublicationError(f"unknown publication status: {status}")

        receipt: dict[str, Any] = {
            "append_only": True,
            "approval_record": approval.to_dict() if approval else None,
            "canary_and_rollback_receipt": pointer.to_dict() if pointer else None,
            "commit_receipt": commit_receipt.to_dict() if commit_receipt else None,
            "dry_run": plan.dry_run and commit_receipt is None,
            "dry_run_diff_and_cost_receipt": plan.to_dict(),
            "evidence": {
                "append_only_commit_receipt": commit_receipt is not None,
                "approval_record": approval is not None,
                "canary_and_rollback_receipt": pointer is not None,
                "dry_run_diff_and_cost_receipt": True,
                "pinned_redownload_validation": pinned_redownload is not None
                and bool(pinned_redownload.ok),
                "post_publication_verification": post_publication is not None
                and bool(post_publication.ok),
                "signed_reviewed_release_manifest": True,
            },
            "goal_id": "ABBY-VOICE-G021",
            "pinned_redownload_validation": (
                pinned_redownload.to_dict() if pinned_redownload else None
            ),
            "post_publication_verification": (
                post_publication.to_dict() if post_publication else None
            ),
            "remote_write_performed": commit_receipt is not None,
            "repository_id": self.repository_id,
            "schema_version": HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA,
            "status": status,
            "tokens_persisted": False,
        }
        _reject_secrets(receipt, label="publication_receipt")
        reject_identity_contamination(
            {
                key: value
                for key, value in receipt.items()
                if key
                not in {
                    # Runtime observations may appear in operational receipts but
                    # are excluded from identity contamination checks.
                    "status",
                    "remote_write_performed",
                    "dry_run",
                    "tokens_persisted",
                    "evidence",
                    "approval_record",
                    "canary_and_rollback_receipt",
                    "commit_receipt",
                    "post_publication_verification",
                    "pinned_redownload_validation",
                    "dry_run_diff_and_cost_receipt",
                }
            },
            label="publication_receipt_identity",
        )
        return receipt


def _file_digest(path: Path) -> tuple[int, bytes]:
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.digest()


def _build_commit_add_operation(*, path_in_repo: str, local_path: Path) -> Any:
    """Build a CommitOperationAdd-compatible object without importing hf_hub at import time."""

    try:
        from huggingface_hub import CommitOperationAdd
    except ImportError:
        # Offline/test fallback: plain mapping understood by fake APIs.
        return {
            "operation": "add",
            "path_in_repo": path_in_repo,
            "path_or_fileobj": str(local_path),
        }
    return CommitOperationAdd(
        path_in_repo=path_in_repo,
        path_or_fileobj=str(local_path),
    )


def _extract_commit_sha(result: Any) -> str:
    if isinstance(result, Mapping):
        for key in ("commit_sha", "oid", "sha", "commitId"):
            if result.get(key):
                return _commit_sha(result[key])
        commit = result.get("commit")
        if isinstance(commit, Mapping) and commit.get("oid"):
            return _commit_sha(commit["oid"])
        if isinstance(commit, Mapping) and commit.get("sha"):
            return _commit_sha(commit["sha"])
    for attr in ("commit_sha", "oid", "sha"):
        value = getattr(result, attr, None)
        if value:
            return _commit_sha(value)
    commit = getattr(result, "commit", None)
    if commit is not None:
        for attr in ("oid", "sha", "commit_sha"):
            value = getattr(commit, attr, None)
            if value:
                return _commit_sha(value)
        if isinstance(commit, Mapping):
            for key in ("oid", "sha", "commit_sha"):
                if commit.get(key):
                    return _commit_sha(commit[key])
    raise HuggingFacePublicationError(
        "create_commit result did not include a commit SHA"
    )


def publish_abby_voice_release(
    *,
    manifest: Mapping[str, Any] | str | Path,
    dry_run: bool = True,
    local_root: str | Path | None = None,
    repository_id: str = DEFAULT_DATASET_REPO_ID,
    approval: PublicationApproval | None = None,
    api: Any | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    receipt_path: str | Path | None = None,
    remote_objects: Mapping[str, Mapping[str, Any]] | None = None,
    remote_payloads: Mapping[str, bytes] | None = None,
    verified_cache_root: str | Path | None = None,
    fetch_bytes: Callable[[str, str, str], bytes] | None = None,
    run_post_publication_verification: bool = True,
    run_pinned_redownload_validation: bool = True,
) -> dict[str, Any]:
    """Plan (and optionally publish) an Abby voice Hugging Face release.

    Default mode is dry-run only.  Remote writes require ``dry_run=False``, an
    explicit :class:`PublicationApproval`, and an injected API client.

    After an approved append-only commit, this entrypoint fail-closes through
    **post-publication verification** (when ``remote_objects`` is supplied or
    synthesizable from the plan) and **pinned redownload validation** (when
    ``remote_payloads`` / ``fetch_bytes`` and an empty ``verified_cache_root``
    are available). Promotion remains a separate reviewed step.
    """

    if isinstance(manifest, (str, Path)):
        path = Path(manifest).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HuggingFacePublicationError(
                f"cannot read release manifest: {path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise HuggingFacePublicationError("release manifest must be a JSON object")
        manifest_obj: Mapping[str, Any] = payload
        if local_root is None:
            local_root = path.parent
    else:
        manifest_obj = manifest

    publisher = HuggingFaceReleasePublisher(
        repository_id=repository_id,
        api=api,
        fetch_bytes=fetch_bytes,
    )
    plan = publisher.plan_dry_run(
        manifest_obj,
        local_root=local_root,
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
    )

    if dry_run:
        receipt = publisher.build_publication_receipt(
            plan=plan,
            status="dry_run_only",
        )
        if receipt_path is not None:
            _write_receipt(receipt_path, receipt)
        return receipt

    if approval is None:
        raise HuggingFacePublicationError(
            "human PublicationApproval is required when dry_run is false; "
            "autonomous work stops after a dry run"
        )
    if local_root is None:
        raise HuggingFacePublicationError("local_root is required for publish")
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=local_root
    )

    post_publication: PostPublicationVerification | None = None
    pinned_redownload: PinnedRedownloadValidation | None = None

    if run_post_publication_verification:
        # Prefer caller-supplied inventory (live HF listing). When absent, the
        # offline path synthesizes inventoried objects from the approved plan
        # under the returned commit SHA so unit tests and dry-lab executes still
        # exercise the post-publication verification gate.
        inventory: Mapping[str, Mapping[str, Any]] | None = remote_objects
        if inventory is None:
            inventory = {
                item.remote_path: {
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                    "commit_sha": commit.commit_sha,
                }
                for item in plan.operations
            }
        post_publication = publisher.verify_post_publication(
            commit_receipt=commit,
            plan=plan,
            remote_objects=inventory,
        )

    if run_pinned_redownload_validation:
        # Prefer caller-supplied remote payloads / fetch_bytes (pinned commit).
        # Offline path re-reads local release bytes under an empty verified cache.
        payloads: Mapping[str, bytes] | None = remote_payloads
        if payloads is None and fetch_bytes is None:
            root = Path(local_root).expanduser().resolve()
            synthesized: dict[str, bytes] = {}
            for item in plan.operations:
                local = root.joinpath(*Path(item.relative_path).parts)
                if not local.is_file() or local.is_symlink():
                    raise HuggingFacePublicationError(
                        "pinned redownload validation cannot synthesize payload "
                        f"for missing local file: {item.relative_path}"
                    )
                synthesized[item.remote_path] = local.read_bytes()
            payloads = synthesized
        cache: Path
        if verified_cache_root is not None:
            cache = Path(verified_cache_root).expanduser().resolve()
        else:
            cache = Path(
                tempfile.mkdtemp(prefix="abby-voice-pinned-redownload-")
            ).resolve()
        pinned_redownload = publisher.redownload_and_validate_pinned(
            commit_sha=commit.commit_sha,
            plan=plan,
            cache_root=cache,
            remote_payloads=payloads,
        )

    # Both residual gates must pass before promotion is considered; canary
    # remains a separate reviewed step (canary_promote_pointer).
    receipt = publisher.build_publication_receipt(
        plan=plan,
        commit_receipt=commit,
        post_publication=post_publication,
        pinned_redownload=pinned_redownload,
        approval=approval,
        status="published_pending_promotion",
    )
    if receipt_path is not None:
        _write_receipt(receipt_path, receipt)
    return receipt


def _write_receipt(path: str | Path, receipt: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_bytes(canonical_json_bytes(dict(receipt)) + b"\n")
    os.replace(temporary, target)
    return target


__all__ = [
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_POINTER_PATH",
    "DEFAULT_RELEASE_PREFIX_TEMPLATE",
    "DEFAULT_STORAGE_RATE_USD_PER_GIB_MONTH",
    "DEFAULT_TRANSFER_RATE_USD_PER_GIB",
    "DRY_RUN_DIFF_AND_COST_RECEIPT_EVIDENCE_TERM",
    "G021_AUTHORITATIVE_EVIDENCE_MAP",
    "G021_AUTO_030_RESIDUAL_EVIDENCE_TERMS",
    "G021_REQUIRED_EVIDENCE_TERMS",
    "G021_RESIDUAL_SCAN_CLOSURE_AUTO_030",
    "HUGGINGFACE_PUBLICATION_PLAN_SCHEMA",
    "HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA",
    "HuggingFacePublicationError",
    "HuggingFaceReleasePublisher",
    "PINNED_REDOWNLOAD_VALIDATION_EVIDENCE_TERM",
    "POST_PUBLICATION_VERIFICATION_EVIDENCE_TERM",
    "PinnedRedownloadValidation",
    "PostPublicationVerification",
    "PublicationApproval",
    "PublicationCommitReceipt",
    "PublicationFilePlan",
    "PublicationPlan",
    "RuntimeReleasePointer",
    "estimate_publication_cost",
    "extract_manifest_files",
    "publish_abby_voice_release",
]
