"""Authorized Patent Center **export import** provider (local files only).

This module intentionally implements **import of user-supplied artifacts**
only. It does **not**:

- scrape or automate Patent Center UI;
- perform login, MFA, or session/cookie handling;
- read browser profiles or session storage;
- store passwords, API keys, payment cards, or signing credentials;
- open network connections to USPTO account surfaces.

The supported path is: an interactive user downloads material outside this
processor and hands an explicit export manifest + authorized import root to
:class:`PatentCenterExportProvider`, which classifies, rejects prohibited
content, encrypts via :class:`PrivateArtifactStore`, and records a sanitized
authorization / source receipt.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ArtifactManifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    SourceReceipt,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    UsptoPrivacyPolicy,
    DEFAULT_PRIVACY_POLICY,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    PrivateStoreError,
    ProhibitedContentError,
    assert_no_prohibited_content,
    detect_prohibited_content,
    sha256_hex,
)

PATENT_CENTER_EXPORT_SCHEMA_VERSION: Final = "uspto.patent-center-export.v1"
PATENT_CENTER_EXPORT_INTERFACE: Final = "PatentCenterExportProvider@1"

ALLOWED_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "compare_original_docx_to_converted_pdf",
        "import_user_supplied_acknowledgement",
        "prepare_local_review_package",
        "import_user_supplied_payment_receipt",
        "produce_human_review_checklist",
        "parse_user_downloaded_export",
    }
)

FORBIDDEN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "read_browser_profile_or_session_storage",
        "scrape_authenticated_patent_center",
        "bypass_mfa",
        "store_credentials_or_cookies",
        "network_login",
        "apply_signature",
        "automatically_file_ids",
        "pay_fee",
        "session_cookie_replay",
        "automate_mfa",
        "perform_final_submission",
    }
)

_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_REL_PATH_RE = re.compile(r"\A(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._\-/ ]+\Z")
_ARCHIVE_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/x-zip-compressed",
        "application/x-zip",
        "application/zip",
    }
)


class PatentCenterExportError(Exception):
    """Base error for authorized export import."""

    def __init__(
        self, message: str, *, code: str = "patent_center_export_error"
    ) -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class PathEscapeError(PatentCenterExportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="path_escape")


class AuthorizationError(PatentCenterExportError):
    def __init__(
        self, message: str, *, code: str = "authorization_error"
    ) -> None:
        super().__init__(message, code=code)


class ForbiddenCapabilityError(PatentCenterExportError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            f"capability is forbidden: {capability}",
            code="forbidden_capability",
        )
        self.capability = capability


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    return _require_str(value, field, max_len=max_len)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"unknown disclosure classification: {value!r}"
            ) from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _coerce_relation(value: Any) -> AuthorityRelation:
    if isinstance(value, AuthorityRelation):
        return value
    if isinstance(value, str):
        try:
            return AuthorityRelation(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid authority_relation: {value!r}") from exc
    raise TypeError("authority_relation must be AuthorityRelation or str")


def assert_no_scraping_surface() -> None:
    """Runtime guard: this module must not expose scraping/session entry points."""
    provider = PatentCenterExportProvider
    for name in (
        "login",
        "authenticate",
        "scrape",
        "automate_mfa",
        "load_session",
        "read_browser_profile",
        "store_cookie",
        "pay_fee",
        "submit_filing",
    ):
        if hasattr(provider, name):
            raise ForbiddenCapabilityError(name)


@dataclass(frozen=True, slots=True)
class ImportAuthorization:
    """User authorization for a local import (never contains secrets)."""

    schema_version: str
    authorization_id: str
    authorizing_user: str
    tenant_id: str
    granted_utc: str
    import_root: str
    scope: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PATENT_CENTER_EXPORT_SCHEMA_VERSION:
            raise ValueError(
                "ImportAuthorization.schema_version must be "
                f"{PATENT_CENTER_EXPORT_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "authorization_id",
            _identifier(self.authorization_id, "authorization_id"),
        )
        user = _require_str(self.authorizing_user, "authorizing_user", max_len=256)
        user_l = user.lower()
        for bad in ("password=", "cookie=", "mfa=", "api_key=", "bearer "):
            if bad in user_l:
                raise AuthorizationError(
                    "authorization must not embed credential material",
                    code="authorization_contains_secret",
                )
        object.__setattr__(self, "authorizing_user", user)
        object.__setattr__(
            self,
            "tenant_id",
            _require_str(self.tenant_id, "tenant_id", max_len=128),
        )
        object.__setattr__(
            self,
            "granted_utc",
            _require_str(self.granted_utc, "granted_utc", max_len=64),
        )
        object.__setattr__(
            self,
            "import_root",
            _require_str(self.import_root, "import_root", max_len=4096),
        )
        object.__setattr__(
            self, "scope", _require_str(self.scope, "scope", max_len=512)
        )
        notes = self.notes
        if notes is None:
            notes = ()
        if not isinstance(notes, Sequence) or isinstance(notes, (str, bytes)):
            raise TypeError("notes must be a sequence of strings")
        object.__setattr__(
            self,
            "notes",
            tuple(
                _require_str(n, "notes[]", max_len=512) for n in notes
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "authorizing_user": self.authorizing_user,
            "granted_utc": self.granted_utc,
            "import_root": self.import_root,
            "notes": list(self.notes),
            "schema_version": self.schema_version,
            "scope": self.scope,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImportAuthorization":
        if not isinstance(value, Mapping):
            raise TypeError("ImportAuthorization must be a mapping")
        return cls(
            schema_version=str(
                value.get("schema_version", PATENT_CENTER_EXPORT_SCHEMA_VERSION)
            ),
            authorization_id=str(value.get("authorization_id", "")),
            authorizing_user=str(value.get("authorizing_user", "")),
            tenant_id=str(value.get("tenant_id", "")),
            granted_utc=str(value.get("granted_utc", "")),
            import_root=str(value.get("import_root", "")),
            scope=str(value.get("scope", "")),
            notes=tuple(value.get("notes") or ()),
        )

    def sanitized_receipt_metadata(self) -> Mapping[str, str]:
        """Metadata safe for SourceReceipt (no path body, no secrets)."""
        return MappingProxyType(
            {
                "authorization_id": self.authorization_id,
                "authorizing_user": self.authorizing_user,
                "import_mode": "user_authorized_local_export",
                "scope": self.scope,
                "tenant_id": self.tenant_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ExportManifestEntry:
    """One file listed in an authorized export package."""

    relative_path: str
    classification: DisclosureClassification
    media_type: str
    authority_relation: AuthorityRelation = AuthorityRelation.AUTHORITATIVE_ORIGINAL
    expected_sha256: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    parent_relative_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        rel = _normalize_relative_path(
            _require_str(self.relative_path, "relative_path", max_len=1024)
        )
        if (
            not _REL_PATH_RE.match(rel)
            or rel.startswith("/")
            or ".." in Path(rel).parts
        ):
            raise PathEscapeError(f"relative_path escapes or is invalid: {rel!r}")
        object.__setattr__(self, "relative_path", rel)
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "media_type",
            _require_str(self.media_type, "media_type", max_len=256),
        )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_relation(self.authority_relation),
        )
        expected = self.expected_sha256
        if expected is not None:
            exp = str(expected).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", exp):
                raise ValueError("expected_sha256 must be 64-char hex")
            object.__setattr__(self, "expected_sha256", exp)
        labels = self.labels
        if labels is None:
            labels = {}
        if not isinstance(labels, Mapping):
            raise TypeError("labels must be a mapping")
        object.__setattr__(
            self,
            "labels",
            MappingProxyType(
                {str(k): str(v) for k, v in sorted(labels.items())}
            ),
        )
        parents: list[str] = []
        for p in self.parent_relative_paths or ():
            text = _require_str(p, "parent_relative_paths[]", max_len=1024)
            cleaned = _normalize_relative_path(text.replace("\\", "/"))
            if ".." in Path(cleaned).parts or cleaned.startswith("/"):
                raise PathEscapeError(f"parent path escapes: {cleaned!r}")
            parents.append(cleaned)
        object.__setattr__(self, "parent_relative_paths", tuple(parents))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_relation": self.authority_relation.value,
            "classification": self.classification.value,
            "expected_sha256": self.expected_sha256,
            "labels": dict(self.labels),
            "media_type": self.media_type,
            "parent_relative_paths": list(self.parent_relative_paths),
            "relative_path": self.relative_path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExportManifestEntry":
        if not isinstance(value, Mapping):
            raise TypeError("ExportManifestEntry must be a mapping")
        return cls(
            relative_path=str(value.get("relative_path", "")),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            media_type=str(value.get("media_type", "application/octet-stream")),
            authority_relation=value.get(
                "authority_relation",
                AuthorityRelation.AUTHORITATIVE_ORIGINAL.value,
            ),
            expected_sha256=value.get("expected_sha256"),
            labels=value.get("labels") or {},
            parent_relative_paths=tuple(value.get("parent_relative_paths") or ()),
        )


@dataclass(frozen=True, slots=True)
class ExportManifest:
    """Explicit package describing user-authorized Patent Center export files."""

    schema_version: str
    export_id: str
    matter_id: str
    application_number: str | None
    entries: tuple[ExportManifestEntry, ...]
    source: str = "user_authorized_patent_center_export"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PATENT_CENTER_EXPORT_SCHEMA_VERSION:
            raise ValueError(
                "ExportManifest.schema_version must be "
                f"{PATENT_CENTER_EXPORT_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "export_id", _identifier(self.export_id, "export_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number"),
        )
        object.__setattr__(
            self,
            "source",
            _require_str(self.source, "source", max_len=256),
        )
        if self.source != "user_authorized_patent_center_export":
            raise ValueError(
                "ExportManifest.source must be user_authorized_patent_center_export"
            )
        if not self.entries:
            raise ValueError("ExportManifest requires at least one entry")
        object.__setattr__(self, "entries", tuple(self.entries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "entries": [e.to_dict() for e in self.entries],
            "export_id": self.export_id,
            "matter_id": self.matter_id,
            "schema_version": self.schema_version,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExportManifest":
        if not isinstance(value, Mapping):
            raise TypeError("ExportManifest must be a mapping")
        entries_raw = value.get("entries")
        if not isinstance(entries_raw, Sequence) or isinstance(
            entries_raw, (str, bytes)
        ):
            raise TypeError("entries must be a sequence")
        return cls(
            schema_version=str(
                value.get("schema_version", PATENT_CENTER_EXPORT_SCHEMA_VERSION)
            ),
            export_id=str(value.get("export_id", "")),
            matter_id=str(value.get("matter_id", "")),
            application_number=value.get("application_number"),
            entries=tuple(
                ExportManifestEntry.from_dict(e) for e in entries_raw
            ),
            source=str(
                value.get("source", "user_authorized_patent_center_export")
            ),
        )

    @classmethod
    def load(cls, path: str | Path) -> "ExportManifest":
        with Path(path).open("r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


@dataclass(frozen=True, slots=True)
class ImportedArtifactResult:
    relative_path: str
    artifact_id: str
    sha256: str
    status: str
    reason_code: str | None
    manifest: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "manifest": dict(self.manifest) if self.manifest is not None else None,
            "reason_code": self.reason_code,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ImportBatchResult:
    """Outcome of one restartable import pass."""

    schema_version: str
    export_id: str
    tenant_id: str
    authorization_id: str
    source_receipt: SourceReceipt
    results: tuple[ImportedArtifactResult, ...]
    imported_count: int
    skipped_count: int
    rejected_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "export_id": self.export_id,
            "imported_count": self.imported_count,
            "rejected_count": self.rejected_count,
            "results": [r.to_dict() for r in self.results],
            "schema_version": self.schema_version,
            "skipped_count": self.skipped_count,
            "source_receipt": self.source_receipt.to_dict(),
            "tenant_id": self.tenant_id,
        }


def _normalize_relative_path(relative_path: str) -> str:
    """Normalize a relative path without stripping ``..`` via character lstrip."""
    rel = relative_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def resolve_under_import_root(import_root: Path, relative_path: str) -> Path:
    """Resolve *relative_path* strictly under *import_root*; reject escapes/symlinks."""
    root = Path(import_root)
    if root.exists() and root.is_symlink():
        raise PathEscapeError("import_root must not be a symlink")
    if not root.is_dir():
        raise PathEscapeError("import_root must be an existing directory")
    root_resolved = root.resolve()
    rel = _normalize_relative_path(relative_path)
    if (
        not rel
        or rel.startswith("/")
        or ".." in Path(rel).parts
    ):
        raise PathEscapeError(f"invalid relative_path: {relative_path!r}")
    cursor = root_resolved
    for part in Path(rel).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise PathEscapeError("path traversal rejected")
        candidate = cursor / part
        if candidate.is_symlink():
            raise PathEscapeError(f"symlink rejected: {rel}")
        cursor = candidate
    try:
        final = cursor.resolve(strict=False)
    except OSError as exc:
        raise PathEscapeError(f"cannot resolve path: {rel}") from exc
    try:
        final.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapeError(f"path escapes import_root: {rel}") from exc
    if final.is_symlink() or not final.is_file() or final.is_symlink():
        raise PathEscapeError(f"not a regular non-symlink file: {rel}")
    return final


def assert_zip_members_safe(data: bytes, *, max_members: int = 256) -> None:
    """Reject zip slip / absolute / symlink-like members without extracting."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PatentCenterExportError(
            "invalid zip archive", code="invalid_archive"
        ) from exc
    with zf:
        names = zf.namelist()
        if len(names) > max_members:
            raise PatentCenterExportError(
                "archive member count exceeds limit", code="archive_too_large"
            )
        for name in names:
            norm = name.replace("\\", "/")
            if (
                norm.startswith("../")
                or "/../" in norm
                or Path(norm).is_absolute()
                or ".." in Path(norm).parts
            ):
                raise PathEscapeError(f"archive member path escape: {name}")
            info = zf.getinfo(name)
            # Unix symlink: high 4 bits of external_attr == 0o120000 (symlink)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (mode & 0xF000) == 0xA000:  # S_IFLNK
                raise PathEscapeError(f"archive symlink member rejected: {name}")


def deterministic_artifact_id(
    *, export_id: str, relative_path: str, sha256: str
) -> str:
    """Stable artifact id for restartable/idempotent imports."""
    material = f"{export_id}\x00{relative_path}\x00{sha256}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:32]
    return f"pce:{export_id}:{digest}"


class PatentCenterExportProvider:
    """Import authorized local Patent Center export packages into private storage.

    Network login, MFA, session cookies, browser profiles, and filing actions
    are out of scope and rejected if requested as capabilities.
    """

    schema_version: str = PATENT_CENTER_EXPORT_SCHEMA_VERSION
    interface: str = PATENT_CENTER_EXPORT_INTERFACE
    allowed_capabilities: frozenset[str] = ALLOWED_CAPABILITIES
    forbidden_capabilities: frozenset[str] = FORBIDDEN_CAPABILITIES

    def __init__(
        self,
        store: PrivateArtifactStore,
        *,
        privacy_policy: UsptoPrivacyPolicy | None = None,
    ) -> None:
        if not isinstance(store, PrivateArtifactStore):
            raise TypeError("store must be a PrivateArtifactStore")
        self._store = store
        self._policy = privacy_policy or DEFAULT_PRIVACY_POLICY
        assert_no_scraping_surface()

    @property
    def store(self) -> PrivateArtifactStore:
        return self._store

    @property
    def tenant_id(self) -> str:
        return self._store.tenant_id

    def assert_capability_allowed(self, capability: str) -> None:
        cap = str(capability).strip()
        if cap in self.forbidden_capabilities:
            raise ForbiddenCapabilityError(cap)
        if cap not in self.allowed_capabilities:
            raise ForbiddenCapabilityError(cap)

    def build_source_receipt(
        self,
        *,
        authorization: ImportAuthorization,
        export: ExportManifest,
        request_digest: str,
        response_digest: str | None = None,
    ) -> SourceReceipt:
        material = f"{authorization.authorization_id}:{export.export_id}"
        receipt_id = (
            "src:"
            + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        )
        meta = dict(authorization.sanitized_receipt_metadata())
        meta["export_id"] = export.export_id
        meta["matter_id"] = export.matter_id
        meta["entry_count"] = str(len(export.entries))
        return SourceReceipt(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            receipt_id=receipt_id,
            endpoint="local://authorized-patent-center-export",
            retrieval_utc=_utc_now_iso(),
            response_status=200,
            upstream_id=None,
            last_modified=None,
            request_digest=request_digest,
            response_digest=response_digest,
            cache_hit=False,
            retry_count=0,
            metadata=meta,
        )

    def import_export(
        self,
        *,
        import_root: str | Path,
        manifest: ExportManifest | Mapping[str, Any] | str | Path,
        authorization: ImportAuthorization | Mapping[str, Any],
        fail_fast: bool = False,
    ) -> ImportBatchResult:
        """Import all manifest entries under *import_root* into encrypted storage.

        Restartable and idempotent: re-running with the same files and digests
        yields ``skipped_idempotent`` without rewriting ciphertext history.
        """
        auth = (
            authorization
            if isinstance(authorization, ImportAuthorization)
            else ImportAuthorization.from_dict(authorization)
        )
        if auth.tenant_id != self.tenant_id:
            raise AuthorizationError(
                "authorization tenant_id does not match private store tenant",
                code="tenant_mismatch",
            )
        root = Path(import_root).expanduser()
        try:
            root = root.resolve()
        except OSError as exc:
            raise PathEscapeError(f"cannot resolve import_root: {import_root}") from exc
        auth_root = Path(auth.import_root).expanduser()
        try:
            auth_root = auth_root.resolve()
        except OSError as exc:
            raise AuthorizationError(
                "authorization.import_root does not match import_root argument",
                code="import_root_mismatch",
            ) from exc
        roots_match = root.as_posix().rstrip("/") == auth_root.as_posix().rstrip("/")
        if not roots_match:
            raise AuthorizationError(
                "authorization.import_root does not match import_root argument",
                code="import_root_mismatch",
            )

        export = self._coerce_manifest(manifest)
        request_digest = sha256_hex(
            canonical_json(
                {
                    "authorization_id": auth.authorization_id,
                    "export": export.to_dict(),
                    "import_root": str(root),
                    "tenant_id": auth.tenant_id,
                }
            ).encode("utf-8")
        )
        source_receipt = self.build_source_receipt(
            authorization=auth,
            export=export,
            request_digest=request_digest,
        )
        results: list[ImportedArtifactResult] = []
        imported = 0
        skipped = 0
        rejected = 0
        for entry in export.entries:
            try:
                item = self._import_one(
                    root=root,
                    export=export,
                    entry=entry,
                    source_receipt=source_receipt,
                )
            except (
                PathEscapeError,
                ProhibitedContentError,
                PrivacyBoundaryError,
                PatentCenterExportError,
                PrivateStoreError,
                ValueError,
                TypeError,
            ) as exc:
                code = getattr(exc, "code", None) or type(exc).__name__
                if fail_fast:
                    raise
                item = ImportedArtifactResult(
                    relative_path=entry.relative_path,
                    artifact_id="",
                    sha256="",
                    status="rejected",
                    reason_code=str(code),
                    manifest=None,
                )
            results.append(item)
            if item.status == "imported":
                imported += 1
            elif item.status == "skipped_idempotent":
                skipped += 1
            else:
                rejected += 1

        return ImportBatchResult(
            schema_version=PATENT_CENTER_EXPORT_SCHEMA_VERSION,
            export_id=export.export_id,
            tenant_id=self.tenant_id,
            authorization_id=auth.authorization_id,
            source_receipt=source_receipt,
            results=tuple(results),
            imported_count=imported,
            skipped_count=skipped,
            rejected_count=rejected,
        )

    def _coerce_manifest(
        self, manifest: ExportManifest | Mapping[str, Any] | str | Path
    ) -> ExportManifest:
        if isinstance(manifest, ExportManifest):
            return manifest
        if isinstance(manifest, Mapping):
            return ExportManifest.from_dict(manifest)
        path = Path(manifest)
        return ExportManifest.load(path)

    def _import_one(
        self,
        *,
        root: Path,
        export: ExportManifest,
        entry: ExportManifestEntry,
        source_receipt: SourceReceipt,
    ) -> ImportedArtifactResult:
        cls = self._policy.classify_before_dispatch(entry.classification)
        if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
            raise ProhibitedContentError(
                "credential_or_payment classification rejected",
                code="classification_credential_or_payment",
            )
        if detect_prohibited_content(
            b"",
            relative_path=entry.relative_path,
            labels=entry.labels,
            classification=cls,
        ):
            raise ProhibitedContentError(
                "entry name/labels indicate prohibited material",
                code="prohibited_name_or_label",
            )
        path = resolve_under_import_root(root, entry.relative_path)
        data = path.read_bytes()
        digest = sha256_hex(data)
        if entry.expected_sha256 is not None and entry.expected_sha256 != digest:
            raise PatentCenterExportError(
                "file digest does not match manifest expected_sha256",
                code="digest_mismatch",
            )
        assert_no_prohibited_content(
            data,
            relative_path=entry.relative_path,
            labels=entry.labels,
            classification=cls,
        )
        if (
            entry.media_type.lower() in _ARCHIVE_MEDIA_TYPES
            or path.suffix.lower() == ".zip"
        ):
            assert_zip_members_safe(data)
        # Quarantine is allowed into encrypted private storage (fail-closed elsewhere).
        if self._policy.must_quarantine(cls):
            pass
        artifact_id = deterministic_artifact_id(
            export_id=export.export_id,
            relative_path=entry.relative_path,
            sha256=digest,
        )
        labels = dict(entry.labels)
        labels.setdefault("export_id", export.export_id)
        labels.setdefault("relative_path", entry.relative_path)
        labels.setdefault("source", export.source)
        manifest, created = self._store.put_bytes(
            data,
            artifact_id=artifact_id,
            classification=cls,
            media_type=entry.media_type,
            matter_id=export.matter_id,
            source_receipt_id=source_receipt.receipt_id,
            authority_relation=entry.authority_relation,
            labels=labels,
            relative_path=entry.relative_path,
            content_kind=ContentKind.DOCUMENT_BYTES,
        )
        status = "imported" if created else "skipped_idempotent"
        reason_code = None if created else "already_present"
        if manifest.is_private or manifest.is_quarantined:
            man_dict: Mapping[str, Any] = {
                "artifact_id": manifest.artifact_id,
                "authority_relation": manifest.authority_relation.value,
                "classification": manifest.classification.value,
                "media_type": manifest.media_type,
                "schema_version": manifest.schema_version,
                "sha256": manifest.sha256,
                "size_bytes": manifest.size_bytes,
            }
        else:
            man_dict = manifest.public_projection()
        return ImportedArtifactResult(
            relative_path=entry.relative_path,
            artifact_id=manifest.artifact_id,
            sha256=manifest.sha256,
            status=status,
            reason_code=reason_code,
            manifest=man_dict,
        )


def load_fixture_manifest(fixture_dir: str | Path) -> ExportManifest:
    """Load ``export_manifest.json`` from a private_import fixture directory."""
    return ExportManifest.load(Path(fixture_dir) / "export_manifest.json")


def load_fixture_authorization(
    fixture_dir: str | Path,
    *,
    import_root: str | Path,
    tenant_id: str,
) -> ImportAuthorization:
    """Load authorization template and bind runtime import_root / tenant_id."""
    path = Path(fixture_dir) / "authorization.json"
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    raw = dict(raw)
    raw["import_root"] = str(import_root)
    raw["tenant_id"] = tenant_id
    raw.setdefault("schema_version", PATENT_CENTER_EXPORT_SCHEMA_VERSION)
    return ImportAuthorization.from_dict(raw)


__all__ = [
    "ALLOWED_CAPABILITIES",
    "AuthorizationError",
    "ExportManifest",
    "ExportManifestEntry",
    "FORBIDDEN_CAPABILITIES",
    "ForbiddenCapabilityError",
    "ImportAuthorization",
    "ImportBatchResult",
    "ImportedArtifactResult",
    "PATENT_CENTER_EXPORT_INTERFACE",
    "PATENT_CENTER_EXPORT_SCHEMA_VERSION",
    "PatentCenterExportError",
    "PatentCenterExportProvider",
    "PathEscapeError",
    "assert_no_scraping_surface",
    "assert_zip_members_safe",
    "deterministic_artifact_id",
    "load_fixture_authorization",
    "load_fixture_manifest",
    "resolve_under_import_root",
]
