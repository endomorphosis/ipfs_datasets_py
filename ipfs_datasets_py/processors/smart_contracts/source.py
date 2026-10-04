"""Source and build manifests for reproducible smart-contract acquisition.

CRYPTOIR-G210: source artifacts qualify only when a reproducible manifest binds
exact file digests, compiler/toolchain identity, and expected deployment
artifacts.  Toolchain mismatch and schema drift fail closed.

Importing this module performs no network I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar

from .artifacts import (
    ArtifactManifest,
    StoredArtifact,
    bind_toolchain,
    bytes_digest,
)
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
from .models import ArtifactKind, ensure_secret_safe


SOURCE_MANIFEST_SCHEMA_VERSION = "smart-contract-source-manifest-v1"
TOOLCHAIN_PIN_SCHEMA_VERSION = "smart-contract-toolchain-pin-v1"


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


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    """One source path bound to exact content digest and length."""

    path: str
    content_digest: str
    byte_length: int
    language: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = _required_text(self.path, "path")
        if path.startswith("/") or ".." in path.split("/"):
            raise InvalidRequestError("source path must be relative without traversal")
        object.__setattr__(self, "path", path)
        digest = _required_text(self.content_digest, "content_digest")
        if not digest.startswith("sha256:"):
            raise InvalidRequestError("content_digest must be a tagged sha256 digest")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self, "language", self.language.strip() if self.language else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "content_digest": self.content_digest,
            "language": self.language,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceFileRecord":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SourceFileRecord must be a mapping")
        return cls(
            path=str(value.get("path", "")),
            content_digest=str(value.get("content_digest", "")),
            byte_length=int(value.get("byte_length", 0)),
            language=str(value.get("language", "")),
            attributes=value.get("attributes", {}),
        )

    @classmethod
    def from_bytes(
        cls,
        path: str,
        data: bytes,
        *,
        language: str = "",
    ) -> "SourceFileRecord":
        if type(data) is not bytes:
            raise InvalidRequestError("source file data must be exact bytes")
        return cls(
            path=path,
            content_digest=bytes_digest(data),
            byte_length=len(data),
            language=language,
        )


@dataclass(frozen=True, slots=True)
class ToolchainPin:
    """Pinned compiler/linker identity and deterministic settings digest."""

    compiler: str
    compiler_version: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    libraries: Mapping[str, str] = field(default_factory=dict)
    linker: str = ""
    linker_version: str = ""
    target: str = ""
    optimization: str = ""
    schema_version: str = TOOLCHAIN_PIN_SCHEMA_VERSION
    toolchain_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compiler", _required_text(self.compiler, "compiler"))
        object.__setattr__(
            self,
            "compiler_version",
            _required_text(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(self, "settings", _freeze_mapping(self.settings))
        libraries = {
            _required_text(key, "library name"): _required_text(value, "library address")
            for key, value in dict(self.libraries).items()
        }
        object.__setattr__(self, "libraries", MappingProxyType(libraries))
        object.__setattr__(self, "linker", self.linker.strip() if self.linker else "")
        object.__setattr__(
            self,
            "linker_version",
            self.linker_version.strip() if self.linker_version else "",
        )
        object.__setattr__(self, "target", self.target.strip() if self.target else "")
        object.__setattr__(
            self,
            "optimization",
            self.optimization.strip() if self.optimization else "",
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TOOLCHAIN_PIN_SCHEMA_VERSION:
            raise InvalidRequestError(
                f"unsupported toolchain pin schema: {self.schema_version}"
            )
        digest = bind_toolchain(
            compiler=self.compiler,
            compiler_version=self.compiler_version,
            settings={
                **thaw_json(self.settings),
                "libraries": dict(self.libraries),
                "linker": self.linker,
                "linker_version": self.linker_version,
                "optimization": self.optimization,
                "target": self.target,
            },
        )
        object.__setattr__(self, "toolchain_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "libraries": dict(self.libraries),
            "linker": self.linker,
            "linker_version": self.linker_version,
            "optimization": self.optimization,
            "schema_version": self.schema_version,
            "settings": thaw_json(self.settings),
            "target": self.target,
            "toolchain_digest": self.toolchain_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolchainPin":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ToolchainPin must be a mapping")
        pin = cls(
            compiler=str(value.get("compiler", "")),
            compiler_version=str(value.get("compiler_version", "")),
            settings=value.get("settings", {}),
            libraries=value.get("libraries", {}),
            linker=str(value.get("linker", "")),
            linker_version=str(value.get("linker_version", "")),
            target=str(value.get("target", "")),
            optimization=str(value.get("optimization", "")),
            schema_version=str(
                value.get("schema_version", TOOLCHAIN_PIN_SCHEMA_VERSION)
            ),
        )
        claimed = value.get("toolchain_digest")
        if claimed and claimed != pin.toolchain_digest:
            raise ArtifactPoisonedError(
                "toolchain digest does not match deterministic pin content"
            )
        return pin

    def assert_matches(self, other: "ToolchainPin") -> None:
        """Fail closed when two pins disagree on toolchain identity."""

        if self.toolchain_digest != other.toolchain_digest:
            raise ArtifactInconsistentError(
                "artifact/toolchain mismatch between source and build evidence"
            )


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Reproducible source-to-deployment binding for contract artifacts.

    A source artifact qualifies only when this manifest binds exact source
    bytes, toolchain identity, and expected creation/runtime digests.
    """

    files: tuple[SourceFileRecord, ...]
    toolchain: ToolchainPin
    request_id: str
    observed_at: datetime
    creation_bytecode_digest: str = ""
    runtime_bytecode_digest: str = ""
    interface_digest: str = ""
    metadata_policy: str = "embedded-cbor-ipfs-none"
    constructor_args_digest: str = ""
    code_epoch: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SOURCE_MANIFEST_SCHEMA_VERSION
    manifest_digest: str = field(init=False)

    MAX_FILES: ClassVar[int] = 4096

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
        if not isinstance(self.toolchain, ToolchainPin):
            raise InvalidRequestError("toolchain must be a ToolchainPin")
        files = tuple(self.files)
        if not files:
            raise InvalidRequestError("source manifest requires at least one file")
        if len(files) > self.MAX_FILES:
            raise ResourceLimitError("source manifest file count exceeded")
        paths: set[str] = set()
        for index, record in enumerate(files):
            if not isinstance(record, SourceFileRecord):
                raise InvalidRequestError(
                    f"files[{index}] must be a SourceFileRecord"
                )
            if record.path in paths:
                raise InvalidRequestError(f"duplicate source path: {record.path}")
            paths.add(record.path)
        # Deterministic order for identity.
        ordered = tuple(sorted(files, key=lambda item: item.path))
        object.__setattr__(self, "files", ordered)
        for name in (
            "creation_bytecode_digest",
            "runtime_bytecode_digest",
            "interface_digest",
            "constructor_args_digest",
        ):
            raw = getattr(self, name)
            if raw:
                text = _required_text(raw, name)
                if not text.startswith("sha256:"):
                    raise InvalidRequestError(f"{name} must be a tagged sha256 digest")
                object.__setattr__(self, name, text)
            else:
                object.__setattr__(self, name, "")
        object.__setattr__(
            self,
            "metadata_policy",
            _required_text(self.metadata_policy, "metadata_policy"),
        )
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SOURCE_MANIFEST_SCHEMA_VERSION:
            raise InvalidRequestError(
                f"unsupported source manifest schema: {self.schema_version}"
            )
        object.__setattr__(self, "manifest_digest", content_digest(self._identity()))
        ensure_secret_safe(self.to_dict())

    def _identity(self) -> dict[str, Any]:
        return {
            "code_epoch": self.code_epoch,
            "constructor_args_digest": self.constructor_args_digest,
            "creation_bytecode_digest": self.creation_bytecode_digest,
            "files": [item.to_dict() for item in self.files],
            "interface_digest": self.interface_digest,
            "metadata_policy": self.metadata_policy,
            "request_id": self.request_id,
            "runtime_bytecode_digest": self.runtime_bytecode_digest,
            "schema_version": self.schema_version,
            "toolchain": self.toolchain.to_dict(),
        }

    @property
    def record_id(self) -> str:
        return deterministic_id(
            "source-manifest",
            {
                "manifest_digest": self.manifest_digest,
                "request_id": self.request_id,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "code_epoch": self.code_epoch,
            "constructor_args_digest": self.constructor_args_digest,
            "creation_bytecode_digest": self.creation_bytecode_digest,
            "files": [item.to_dict() for item in self.files],
            "interface_digest": self.interface_digest,
            "manifest_digest": self.manifest_digest,
            "metadata_policy": self.metadata_policy,
            "observed_at": format_datetime(self.observed_at),
            "request_id": self.request_id,
            "runtime_bytecode_digest": self.runtime_bytecode_digest,
            "schema_version": self.schema_version,
            "toolchain": self.toolchain.to_dict(),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_digest(self) -> str:
        return self.manifest_digest

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceManifest":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SourceManifest must be a mapping")
        observed = value.get("observed_at")
        if isinstance(observed, str):
            observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        elif isinstance(observed, datetime):
            observed_at = observed
        else:
            raise InvalidRequestError("observed_at is required")
        files = tuple(
            SourceFileRecord.from_dict(item) for item in value.get("files", ())
        )
        toolchain = ToolchainPin.from_dict(value.get("toolchain", {}))
        manifest = cls(
            files=files,
            toolchain=toolchain,
            request_id=str(value.get("request_id", "")),
            observed_at=observed_at,
            creation_bytecode_digest=str(value.get("creation_bytecode_digest", "")),
            runtime_bytecode_digest=str(value.get("runtime_bytecode_digest", "")),
            interface_digest=str(value.get("interface_digest", "")),
            metadata_policy=str(
                value.get("metadata_policy", "embedded-cbor-ipfs-none")
            ),
            constructor_args_digest=str(value.get("constructor_args_digest", "")),
            code_epoch=str(value.get("code_epoch", "")),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", SOURCE_MANIFEST_SCHEMA_VERSION)
            ),
        )
        claimed = value.get("manifest_digest")
        if claimed and claimed != manifest.manifest_digest:
            raise ArtifactPoisonedError(
                "source manifest digest does not match deterministic content"
            )
        return manifest

    def verify_sources(
        self,
        sources_by_path: Mapping[str, bytes],
    ) -> None:
        """Fail closed when supplied source bytes disagree with the manifest."""

        if set(sources_by_path) != {record.path for record in self.files}:
            raise ArtifactInconsistentError(
                "source path set does not match source manifest"
            )
        for record in self.files:
            payload = sources_by_path[record.path]
            if type(payload) is not bytes:
                raise InvalidRequestError(
                    f"source bytes for {record.path} must be exact bytes"
                )
            if len(payload) != record.byte_length:
                raise ArtifactPoisonedError(
                    f"source length mismatch for {record.path}"
                )
            if bytes_digest(payload) != record.content_digest:
                raise ArtifactPoisonedError(
                    f"source digest mismatch for {record.path}"
                )

    def assert_deployed_equivalence(
        self,
        *,
        creation: bytes | None = None,
        runtime: bytes | None = None,
    ) -> None:
        """Require declared creation/runtime digests match supplied bytecode.

        When a digest is declared empty, that artifact is treated as unbound
        evidence rather than a successful reproduction claim.
        """

        if creation is not None:
            if not self.creation_bytecode_digest:
                raise ArtifactInconsistentError(
                    "creation bytecode supplied without declared digest binding"
                )
            if bytes_digest(creation) != self.creation_bytecode_digest:
                raise ArtifactInconsistentError(
                    "creation bytecode does not reproduce source manifest binding"
                )
        if runtime is not None:
            if not self.runtime_bytecode_digest:
                raise ArtifactInconsistentError(
                    "runtime bytecode supplied without declared digest binding"
                )
            if bytes_digest(runtime) != self.runtime_bytecode_digest:
                raise ArtifactInconsistentError(
                    "runtime bytecode does not reproduce source manifest binding"
                )

    def assert_toolchain_matches(self, other: ToolchainPin) -> None:
        self.toolchain.assert_matches(other)

    def to_artifact_manifest(
        self,
        sources_by_path: Mapping[str, bytes],
        *,
        provider_ids: Sequence[str] = (),
    ) -> ArtifactManifest:
        """Materialize an :class:`ArtifactManifest` from verified source bytes."""

        self.verify_sources(sources_by_path)
        stored: list[tuple[str, StoredArtifact]] = []
        for record in self.files:
            stored.append(
                (
                    record.path,
                    StoredArtifact(
                        raw_bytes=sources_by_path[record.path],
                        kind=ArtifactKind.SOURCE,
                        media_type="text/plain",
                        label=record.path,
                    ),
                )
            )
        return ArtifactManifest.from_stored(
            stored,
            request_id=self.request_id,
            observed_at=self.observed_at,
            provider_ids=tuple(provider_ids),
            toolchain_digest=self.toolchain.toolchain_digest,
            code_epoch=self.code_epoch,
        )


__all__ = [
    "SOURCE_MANIFEST_SCHEMA_VERSION",
    "TOOLCHAIN_PIN_SCHEMA_VERSION",
    "SourceFileRecord",
    "SourceManifest",
    "ToolchainPin",
]
