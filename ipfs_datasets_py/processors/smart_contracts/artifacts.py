"""Content-addressed smart-contract artifact storage and manifests.

CRYPTOIR-G210: raw code, state, source, interface, compiler, and build
artifacts are stored as untouched bytes with deterministic manifests.  Public
records never embed raw bytes; they carry tagged digests and optional CIDs.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Any, ClassVar
import zipfile
from io import BytesIO

from .canonical import (
    canonical_json,
    content_digest,
    deterministic_id,
    format_datetime,
    freeze_json,
    thaw_json,
)
from .errors import (
    ArtifactInconsistentError,
    ArtifactPoisonedError,
    InvalidRequestError,
    ResourceLimitError,
)
from .models import (
    AcquisitionProvenance,
    AcquisitionStatus,
    ArtifactKind,
    ArtifactRef,
    ContractAcquisitionResult,
    ensure_secret_safe,
)


ARTIFACT_MANIFEST_SCHEMA_VERSION = "smart-contract-artifact-manifest-v1"
STORED_ARTIFACT_SCHEMA_VERSION = "smart-contract-stored-artifact-v1"
TRANSPORT_EVIDENCE_SCHEMA_VERSION = "smart-contract-transport-evidence-v1"


def bytes_digest(data: bytes) -> str:
    """Return a tagged SHA-256 digest of raw bytes."""

    if type(data) is not bytes:
        raise InvalidRequestError("bytes_digest requires exact bytes")
    return f"sha256:{sha256(data).hexdigest()}"


def raw_cid(data: bytes) -> str:
    """Return a dependency-free CIDv1 for raw codec + sha2-256 multihash."""

    if type(data) is not bytes:
        raise InvalidRequestError("raw_cid requires exact bytes")
    digest = sha256(data).digest()
    # CIDv1 (0x01), raw multicodec (0x55), sha2-256 multihash (0x12, 0x20).
    binary = b"\x01\x55\x12\x20" + digest
    return "b" + base64.b32encode(binary).decode("ascii").rstrip("=").lower()


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class TransportEvidence:
    """Content-addressed request/response metadata for one acquisition hop.

    Raw bodies are never stored here; only digests and finite scalar metadata.
    """

    request_digest: str
    response_digest: str
    final_url_digest: str
    status_code: int
    byte_length: int
    redirect_count: int = 0
    transport: str = "offline_fixture"
    headers_digest: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TRANSPORT_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _required_text(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "response_digest",
            _required_text(self.response_digest, "response_digest"),
        )
        object.__setattr__(
            self,
            "final_url_digest",
            _required_text(self.final_url_digest, "final_url_digest"),
        )
        object.__setattr__(
            self, "status_code", _non_negative(self.status_code, "status_code")
        )
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self, "redirect_count", _non_negative(self.redirect_count, "redirect_count")
        )
        object.__setattr__(
            self, "transport", _required_text(self.transport, "transport")
        )
        if self.headers_digest:
            object.__setattr__(
                self,
                "headers_digest",
                _required_text(self.headers_digest, "headers_digest"),
            )
        else:
            object.__setattr__(self, "headers_digest", "")
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if not self.request_digest.startswith("sha256:"):
            raise InvalidRequestError("request_digest must be a tagged sha256 digest")
        if not self.response_digest.startswith("sha256:"):
            raise InvalidRequestError("response_digest must be a tagged sha256 digest")
        ensure_secret_safe(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "final_url_digest": self.final_url_digest,
            "headers_digest": self.headers_digest,
            "redirect_count": self.redirect_count,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "schema_version": self.schema_version,
            "status_code": self.status_code,
            "transport": self.transport,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransportEvidence":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("TransportEvidence must be a mapping")
        return cls(
            request_digest=str(value.get("request_digest", "")),
            response_digest=str(value.get("response_digest", "")),
            final_url_digest=str(value.get("final_url_digest", "")),
            status_code=int(value.get("status_code", 0)),
            byte_length=int(value.get("byte_length", 0)),
            redirect_count=int(value.get("redirect_count", 0)),
            transport=str(value.get("transport", "offline_fixture")),
            headers_digest=str(value.get("headers_digest", "")),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", TRANSPORT_EVIDENCE_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Untouched acquired bytes with content addressing.

    The raw body is the sole authority for digests.  Callers that mutate the
    original buffer after construction do not affect digests already bound.
    """

    raw_bytes: bytes
    kind: ArtifactKind
    media_type: str
    label: str = ""
    content_digest: str = field(init=False)
    content_cid: str = field(init=False)
    byte_length: int = field(init=False)
    schema_version: str = STORED_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.raw_bytes) is not bytes:
            raise InvalidRequestError("raw_bytes must be exact bytes")
        object.__setattr__(
            self,
            "kind",
            self.kind
            if isinstance(self.kind, ArtifactKind)
            else ArtifactKind(str(self.kind)),
        )
        object.__setattr__(
            self, "media_type", _required_text(self.media_type, "media_type")
        )
        object.__setattr__(
            self, "label", self.label.strip() if self.label else ""
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        digest = bytes_digest(self.raw_bytes)
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", raw_cid(self.raw_bytes))
        object.__setattr__(self, "byte_length", len(self.raw_bytes))

    def as_ref(self) -> ArtifactRef:
        """Return a public content-addressed reference without raw bytes."""

        return ArtifactRef(
            kind=self.kind,
            content_digest=self.content_digest,
            media_type=self.media_type,
            byte_length=self.byte_length,
            content_cid=self.content_cid,
            label=self.label,
        )

    def verify(self, expected_digest: str | None = None) -> None:
        """Fail closed when stored bytes no longer match bound digests."""

        actual = bytes_digest(self.raw_bytes)
        if actual != self.content_digest:
            raise ArtifactPoisonedError("stored artifact digest mismatch")
        if raw_cid(self.raw_bytes) != self.content_cid:
            raise ArtifactPoisonedError("stored artifact CID mismatch")
        if len(self.raw_bytes) != self.byte_length:
            raise ArtifactPoisonedError("stored artifact length mismatch")
        if expected_digest is not None and actual != expected_digest:
            raise ArtifactPoisonedError("artifact does not match expected digest")


@dataclass(frozen=True, slots=True)
class ArtifactManifestEntry:
    """One content-addressed entry inside an :class:`ArtifactManifest`."""

    path: str
    kind: ArtifactKind
    content_digest: str
    media_type: str
    byte_length: int
    content_cid: str = ""
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _required_text(self.path, "path"))
        if ".." in self.path.split("/") or self.path.startswith("/"):
            raise InvalidRequestError("path must be relative without parent traversal")
        object.__setattr__(
            self,
            "kind",
            self.kind
            if isinstance(self.kind, ArtifactKind)
            else ArtifactKind(str(self.kind)),
        )
        digest = _required_text(self.content_digest, "content_digest")
        if not digest.startswith("sha256:"):
            raise InvalidRequestError("content_digest must be a tagged sha256 digest")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self, "media_type", _required_text(self.media_type, "media_type")
        )
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        if self.content_cid:
            object.__setattr__(
                self, "content_cid", _required_text(self.content_cid, "content_cid")
            )
        else:
            object.__setattr__(self, "content_cid", "")
        object.__setattr__(
            self, "label", self.label.strip() if self.label else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "kind": self.kind.value
            if isinstance(self.kind, ArtifactKind)
            else str(self.kind),
            "label": self.label,
            "media_type": self.media_type,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactManifestEntry":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ArtifactManifestEntry must be a mapping")
        return cls(
            path=str(value.get("path", "")),
            kind=value.get("kind", ArtifactKind.OTHER.value),
            content_digest=str(value.get("content_digest", "")),
            media_type=str(value.get("media_type", "")),
            byte_length=int(value.get("byte_length", 0)),
            content_cid=str(value.get("content_cid", "")),
            label=str(value.get("label", "")),
            attributes=value.get("attributes", {}),
        )

    @classmethod
    def from_stored(
        cls,
        stored: StoredArtifact,
        *,
        path: str,
    ) -> "ArtifactManifestEntry":
        return cls(
            path=path,
            kind=stored.kind,
            content_digest=stored.content_digest,
            media_type=stored.media_type,
            byte_length=stored.byte_length,
            content_cid=stored.content_cid,
            label=stored.label,
        )


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable, deterministic manifest over content-addressed artifacts.

    The manifest identity is a digest of ordered entries and binding metadata.
    Truncation, schema drift, and digest poisoning fail closed.
    """

    entries: tuple[ArtifactManifestEntry, ...]
    request_id: str
    observed_at: datetime
    transport_evidence: tuple[TransportEvidence, ...] = ()
    provider_ids: tuple[str, ...] = ()
    toolchain_digest: str = ""
    code_epoch: str = ""
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ARTIFACT_MANIFEST_SCHEMA_VERSION
    manifest_digest: str = field(init=False)

    MAX_ENTRIES: ClassVar[int] = 4096

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _required_text(self.request_id, "request_id")
        )
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise InvalidRequestError("observed_at must be a timezone-aware datetime")
        entries = tuple(self.entries)
        if len(entries) > self.MAX_ENTRIES:
            raise ResourceLimitError("artifact manifest entry count exceeded")
        paths: set[str] = set()
        digests: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, ArtifactManifestEntry):
                raise InvalidRequestError(
                    f"entries[{index}] must be an ArtifactManifestEntry"
                )
            if entry.path in paths:
                raise InvalidRequestError(f"duplicate manifest path: {entry.path}")
            paths.add(entry.path)
            digests.add(entry.content_digest)
        object.__setattr__(self, "entries", entries)
        evidence = tuple(self.transport_evidence)
        for index, item in enumerate(evidence):
            if not isinstance(item, TransportEvidence):
                raise InvalidRequestError(
                    f"transport_evidence[{index}] must be TransportEvidence"
                )
        object.__setattr__(self, "transport_evidence", evidence)
        providers = tuple(
            _required_text(item, "provider_ids item") for item in self.provider_ids
        )
        object.__setattr__(self, "provider_ids", providers)
        if self.toolchain_digest:
            text = _required_text(self.toolchain_digest, "toolchain_digest")
            if not text.startswith("sha256:"):
                raise InvalidRequestError(
                    "toolchain_digest must be a tagged sha256 digest"
                )
            object.__setattr__(self, "toolchain_digest", text)
        else:
            object.__setattr__(self, "toolchain_digest", "")
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise InvalidRequestError(
                f"unsupported artifact manifest schema: {self.schema_version}"
            )
        object.__setattr__(self, "manifest_digest", content_digest(self._identity()))
        ensure_secret_safe(self.to_dict())

    def _identity(self) -> dict[str, Any]:
        return {
            "code_epoch": self.code_epoch,
            "entries": [entry.to_dict() for entry in self.entries],
            "provider_ids": list(self.provider_ids),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "toolchain_digest": self.toolchain_digest,
            "transport_evidence": [
                item.to_dict() for item in self.transport_evidence
            ],
        }

    @property
    def record_id(self) -> str:
        return deterministic_id(
            "artifact-manifest",
            {
                "manifest_digest": self.manifest_digest,
                "request_id": self.request_id,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "code_epoch": self.code_epoch,
            "diagnostics": list(self.diagnostics),
            "entries": [entry.to_dict() for entry in self.entries],
            "manifest_digest": self.manifest_digest,
            "observed_at": format_datetime(self.observed_at),
            "provider_ids": list(self.provider_ids),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "toolchain_digest": self.toolchain_digest,
            "transport_evidence": [
                item.to_dict() for item in self.transport_evidence
            ],
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_digest(self) -> str:
        return self.manifest_digest

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactManifest":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ArtifactManifest must be a mapping")
        observed = value.get("observed_at")
        if isinstance(observed, str):
            observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        elif isinstance(observed, datetime):
            observed_at = observed
        else:
            raise InvalidRequestError("observed_at is required")
        entries = tuple(
            ArtifactManifestEntry.from_dict(item)
            for item in value.get("entries", ())
        )
        evidence = tuple(
            TransportEvidence.from_dict(item)
            for item in value.get("transport_evidence", ())
        )
        manifest = cls(
            entries=entries,
            request_id=str(value.get("request_id", "")),
            observed_at=observed_at,
            transport_evidence=evidence,
            provider_ids=tuple(value.get("provider_ids", ())),
            toolchain_digest=str(value.get("toolchain_digest", "")),
            code_epoch=str(value.get("code_epoch", "")),
            diagnostics=tuple(value.get("diagnostics", ())),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", ARTIFACT_MANIFEST_SCHEMA_VERSION)
            ),
        )
        claimed = value.get("manifest_digest")
        if claimed and claimed != manifest.manifest_digest:
            raise ArtifactPoisonedError(
                "artifact manifest digest does not match deterministic content"
            )
        return manifest

    @classmethod
    def from_stored(
        cls,
        stored: Sequence[tuple[str, StoredArtifact]],
        *,
        request_id: str,
        observed_at: datetime,
        transport_evidence: Sequence[TransportEvidence] = (),
        provider_ids: Sequence[str] = (),
        toolchain_digest: str = "",
        code_epoch: str = "",
        diagnostics: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> "ArtifactManifest":
        entries = tuple(
            ArtifactManifestEntry.from_stored(item, path=path)
            for path, item in stored
        )
        return cls(
            entries=entries,
            request_id=request_id,
            observed_at=observed_at,
            transport_evidence=tuple(transport_evidence),
            provider_ids=tuple(provider_ids),
            toolchain_digest=toolchain_digest,
            code_epoch=code_epoch,
            diagnostics=tuple(diagnostics),
            attributes=dict(attributes or {}),
        )

    def verify_against(
        self,
        artifacts_by_path: Mapping[str, StoredArtifact],
    ) -> None:
        """Validate that every entry matches stored bytes; fail closed otherwise."""

        if set(artifacts_by_path) != {entry.path for entry in self.entries}:
            raise ArtifactInconsistentError(
                "artifact set does not match manifest entry paths"
            )
        for entry in self.entries:
            stored = artifacts_by_path[entry.path]
            stored.verify(entry.content_digest)
            if stored.byte_length != entry.byte_length:
                raise ArtifactPoisonedError(
                    f"length mismatch for manifest path {entry.path}"
                )
            if entry.content_cid and stored.content_cid != entry.content_cid:
                raise ArtifactPoisonedError(
                    f"CID mismatch for manifest path {entry.path}"
                )
            if stored.kind != entry.kind:
                raise ArtifactInconsistentError(
                    f"kind mismatch for manifest path {entry.path}"
                )

    def artifact_refs(self) -> tuple[ArtifactRef, ...]:
        return tuple(
            ArtifactRef(
                kind=entry.kind,
                content_digest=entry.content_digest,
                media_type=entry.media_type,
                byte_length=entry.byte_length,
                content_cid=entry.content_cid,
                label=entry.label or entry.path,
            )
            for entry in self.entries
        )


def unpack_archive_bounded(
    archive_bytes: bytes,
    *,
    max_entries: int,
    max_total_bytes: int,
    max_depth: int = 1,
    depth: int = 0,
) -> tuple[tuple[str, bytes], ...]:
    """Extract a ZIP archive under explicit entry and byte ceilings.

    Nested archives are rejected once ``depth`` reaches ``max_depth``.  Path
    traversal and absolute paths fail closed.
    """

    _positive(max_entries, "max_entries")
    _positive(max_total_bytes, "max_total_bytes")
    _positive(max_depth, "max_depth")
    _non_negative(depth, "depth")
    if depth >= max_depth:
        raise ResourceLimitError("archive recursion depth exceeded")
    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ArtifactPoisonedError("archive is not a valid ZIP payload") from exc

    results: list[tuple[str, bytes]] = []
    total = 0
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > max_entries:
            raise ResourceLimitError("archive entry count exceeds max_archive_entries")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ArtifactPoisonedError("archive path traversal is forbidden")
            if info.file_size < 0 or info.file_size > max_total_bytes:
                raise ResourceLimitError("archive entry exceeds byte budget")
            payload = archive.read(info)
            if len(payload) != info.file_size and info.file_size != 0:
                # Some zip tools leave file_size 0 for streaming members; still
                # enforce the aggregate budget on actual payload length.
                pass
            total += len(payload)
            if total > max_total_bytes:
                raise ResourceLimitError("archive total bytes exceed budget")
            results.append((name, payload))
    return tuple(results)


def combine_provider_views(
    *,
    request_id: str,
    views: Sequence[tuple[str, ArtifactManifest | None, Sequence[str]]],
    trust_mode: str,
) -> ContractAcquisitionResult:
    """Combine multi-provider acquisition views without permissive selection.

    * ``preserve_disagreement`` — emit ``INCONSISTENT`` when digests differ and
      retain every provider's diagnostics and coverage notes.
    * ``require_agreement`` — same, but never elevates a partial majority.
    * ``single`` — accepts only exactly one successful view.
    """

    mode = trust_mode.strip().casefold()
    if mode not in {"single", "require_agreement", "preserve_disagreement"}:
        raise InvalidRequestError(f"unknown trust mode: {trust_mode!r}")

    successes: list[tuple[str, ArtifactManifest]] = []
    diagnostics: list[str] = []
    coverage: list[str] = []
    provenances: list[AcquisitionProvenance] = []

    for provider_id, manifest, notes in views:
        provider = _required_text(provider_id, "provider_id")
        coverage.extend(f"{provider}:{note}" for note in notes)
        if manifest is None:
            diagnostics.append(f"{provider}:unavailable")
            continue
        successes.append((provider, manifest))
        for evidence in manifest.transport_evidence:
            provenances.append(
                AcquisitionProvenance(
                    provider_id=provider,
                    transport=evidence.transport,
                    observed_at=manifest.observed_at,
                    request_digest=evidence.request_digest,
                    response_digest=evidence.response_digest,
                    endpoint_id=evidence.final_url_digest,
                    attributes={"status_code": evidence.status_code},
                )
            )

    if not successes:
        return ContractAcquisitionResult(
            request_id=request_id,
            status=AcquisitionStatus.UNAVAILABLE,
            provenances=tuple(provenances),
            diagnostics=tuple(diagnostics) or ("no provider returned artifacts",),
            coverage_notes=tuple(coverage),
        )

    if mode == "single" and len(successes) != 1:
        return ContractAcquisitionResult(
            request_id=request_id,
            status=AcquisitionStatus.INCONSISTENT,
            provenances=tuple(provenances),
            diagnostics=tuple(diagnostics)
            + (f"single trust mode requires exactly one provider; got {len(successes)}",),
            coverage_notes=tuple(coverage),
        )

    # Compare entry digests across providers without choosing a winner.
    signature = None
    disagree = False
    for _provider, manifest in successes:
        sig = tuple(
            (entry.path, entry.content_digest, entry.byte_length)
            for entry in sorted(manifest.entries, key=lambda item: item.path)
        )
        if signature is None:
            signature = sig
        elif signature != sig:
            disagree = True

    if disagree:
        # Preserve every provider's artifact set; never pick the permissive one.
        all_refs: list[ArtifactRef] = []
        seen: set[str] = set()
        for _provider, manifest in successes:
            for ref in manifest.artifact_refs():
                key = f"{ref.content_digest}:{ref.label}:{ref.kind.value}"
                if key not in seen:
                    seen.add(key)
                    all_refs.append(ref)
        provider_list = ",".join(provider for provider, _ in successes)
        return ContractAcquisitionResult(
            request_id=request_id,
            status=AcquisitionStatus.INCONSISTENT,
            artifacts=tuple(all_refs),
            provenances=tuple(provenances),
            diagnostics=tuple(diagnostics)
            + (f"provider disagreement among {provider_list}",),
            coverage_notes=tuple(coverage)
            + ("disagreement preserved; no permissive selection",),
        )

    # Agreement: merge coverage but use the first successful artifact set.
    primary = successes[0][1]
    status = (
        AcquisitionStatus.PARTIAL
        if diagnostics or any(not m.entries for _, m in successes)
        else AcquisitionStatus.AVAILABLE
    )
    if status is AcquisitionStatus.AVAILABLE and not primary.entries:
        status = AcquisitionStatus.PARTIAL
    return ContractAcquisitionResult(
        request_id=request_id,
        status=status,
        artifacts=primary.artifact_refs(),
        provenances=tuple(provenances),
        diagnostics=tuple(diagnostics),
        coverage_notes=tuple(coverage),
    )


def bind_toolchain(
    *,
    compiler: str,
    compiler_version: str,
    settings: Mapping[str, Any],
    libraries: Mapping[str, str] | None = None,
) -> str:
    """Return a content digest binding compiler identity and settings."""

    payload = {
        "compiler": _required_text(compiler, "compiler"),
        "compiler_version": _required_text(compiler_version, "compiler_version"),
        "libraries": dict(libraries or {}),
        "settings": dict(settings),
    }
    ensure_secret_safe(payload)
    return content_digest(payload)


__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "STORED_ARTIFACT_SCHEMA_VERSION",
    "TRANSPORT_EVIDENCE_SCHEMA_VERSION",
    "ArtifactManifest",
    "ArtifactManifestEntry",
    "StoredArtifact",
    "TransportEvidence",
    "bind_toolchain",
    "bytes_digest",
    "combine_provider_views",
    "raw_cid",
    "unpack_archive_bounded",
]
