"""Immutable content-addressed cache for smart-contract acquisition results.

CRYPTOIR-G210: only content-bound results are cached.  Digest mismatch, length
truncation, and key collision with different bytes fail closed.  Importing this
module performs no network I/O.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .artifacts import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
    StoredArtifact,
    bytes_digest,
)
from .canonical import canonical_json
from .errors import (
    ArtifactPoisonedError,
    InvalidRequestError,
    ResourceLimitError,
)
from .models import ArtifactKind


CACHE_SCHEMA_VERSION = "smart-contract-artifact-cache-v1"
DEFAULT_MAX_OBJECTS = 10_000
DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CacheObjectMeta:
    """Public metadata for one cached object (never includes raw bytes)."""

    content_digest: str
    byte_length: int
    kind: str
    media_type: str
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "content_digest": self.content_digest,
            "kind": self.kind,
            "label": self.label,
            "media_type": self.media_type,
        }


class ContractArtifactCache:
    """Content-addressed, immutable artifact and manifest cache.

    Objects are keyed solely by SHA-256 digest of their raw bytes.  Putting the
    same digest twice is a no-op when bytes match and fails closed when they
    differ (poisoning / CAS corruption).
    """

    __slots__ = (
        "_lock",
        "_manifests",
        "_max_objects",
        "_max_total_bytes",
        "_objects",
        "_root",
        "_total_bytes",
    )

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        max_objects: int = DEFAULT_MAX_OBJECTS,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        if isinstance(max_objects, bool) or not isinstance(max_objects, int) or max_objects <= 0:
            raise InvalidRequestError("max_objects must be a positive integer")
        if (
            isinstance(max_total_bytes, bool)
            or not isinstance(max_total_bytes, int)
            or max_total_bytes <= 0
        ):
            raise InvalidRequestError("max_total_bytes must be a positive integer")
        self._max_objects = max_objects
        self._max_total_bytes = max_total_bytes
        self._objects: dict[str, StoredArtifact] = {}
        self._manifests: dict[str, ArtifactManifest] = {}
        self._total_bytes = 0
        self._lock = RLock()
        self._root = Path(root) if root is not None else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            (self._root / "objects").mkdir(exist_ok=True)
            (self._root / "manifests").mkdir(exist_ok=True)
            self._load_from_disk()

    @property
    def object_count(self) -> int:
        return len(self._objects)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def schema_version(self) -> str:
        return CACHE_SCHEMA_VERSION

    def _object_path(self, digest: str) -> Path:
        assert self._root is not None
        # Strip tag for filesystem key.
        hex_part = digest.split(":", 1)[-1]
        return self._root / "objects" / f"{hex_part}.bin"

    def _meta_path(self, digest: str) -> Path:
        assert self._root is not None
        hex_part = digest.split(":", 1)[-1]
        return self._root / "objects" / f"{hex_part}.json"

    def _manifest_path(self, digest: str) -> Path:
        assert self._root is not None
        hex_part = digest.split(":", 1)[-1]
        return self._root / "manifests" / f"{hex_part}.json"

    def _load_from_disk(self) -> None:
        assert self._root is not None
        objects_dir = self._root / "objects"
        for meta_file in objects_dir.glob("*.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                digest = str(meta["content_digest"])
                body = self._object_path(digest).read_bytes()
                if bytes_digest(body) != digest:
                    raise ArtifactPoisonedError("on-disk object digest mismatch")
                if len(body) != int(meta["byte_length"]):
                    raise ArtifactPoisonedError("on-disk object length mismatch")
                stored = StoredArtifact(
                    raw_bytes=body,
                    kind=ArtifactKind(str(meta["kind"])),
                    media_type=str(meta["media_type"]),
                    label=str(meta.get("label", "")),
                )
                self._objects[digest] = stored
                self._total_bytes += stored.byte_length
            except (OSError, KeyError, ValueError, TypeError, ArtifactPoisonedError):
                # Fail closed: skip corrupted objects rather than serving them.
                continue
        manifests_dir = self._root / "manifests"
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                payload = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest = ArtifactManifest.from_dict(payload)
                self._manifests[manifest.manifest_digest] = manifest
            except (OSError, ValueError, TypeError, ArtifactPoisonedError, InvalidRequestError):
                continue

    def put_bytes(
        self,
        data: bytes,
        *,
        kind: ArtifactKind | str = ArtifactKind.OTHER,
        media_type: str = "application/octet-stream",
        label: str = "",
    ) -> StoredArtifact:
        """Store *data* under its content digest; immutable on conflict."""

        if type(data) is not bytes:
            raise InvalidRequestError("cache accepts exact bytes only")
        stored = StoredArtifact(
            raw_bytes=data,
            kind=kind if isinstance(kind, ArtifactKind) else ArtifactKind(str(kind)),
            media_type=media_type,
            label=label,
        )
        return self.put_artifact(stored)

    def put_artifact(self, artifact: StoredArtifact) -> StoredArtifact:
        """Insert a :class:`StoredArtifact` under strict CAS rules."""

        if not isinstance(artifact, StoredArtifact):
            raise InvalidRequestError("artifact must be a StoredArtifact")
        artifact.verify()
        digest = artifact.content_digest
        with self._lock:
            existing = self._objects.get(digest)
            if existing is not None:
                if existing.raw_bytes != artifact.raw_bytes:
                    raise ArtifactPoisonedError(
                        "CAS collision: digest already bound to different bytes"
                    )
                # Metadata mismatch on identical bytes is schema drift.
                if (
                    existing.kind != artifact.kind
                    or existing.media_type != artifact.media_type
                ):
                    raise ArtifactPoisonedError(
                        "CAS metadata drift for existing content digest"
                    )
                return existing
            if len(self._objects) >= self._max_objects:
                raise ResourceLimitError("artifact cache object count exceeded")
            if self._total_bytes + artifact.byte_length > self._max_total_bytes:
                raise ResourceLimitError("artifact cache byte budget exceeded")
            self._objects[digest] = artifact
            self._total_bytes += artifact.byte_length
            if self._root is not None:
                self._persist_object(artifact)
            return artifact

    def _persist_object(self, artifact: StoredArtifact) -> None:
        assert self._root is not None
        path = self._object_path(artifact.content_digest)
        meta_path = self._meta_path(artifact.content_digest)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(artifact.raw_bytes)
        os.replace(tmp, path)
        meta = CacheObjectMeta(
            content_digest=artifact.content_digest,
            byte_length=artifact.byte_length,
            kind=artifact.kind.value
            if isinstance(artifact.kind, ArtifactKind)
            else str(artifact.kind),
            media_type=artifact.media_type,
            label=artifact.label,
        )
        meta_tmp = meta_path.with_suffix(".tmp")
        meta_tmp.write_text(
            canonical_json(meta.to_dict()),
            encoding="utf-8",
        )
        os.replace(meta_tmp, meta_path)

    def get(self, content_digest: str) -> StoredArtifact:
        """Return stored bytes after re-validating the digest binding."""

        if not isinstance(content_digest, str) or not content_digest.startswith(
            "sha256:"
        ):
            raise InvalidRequestError("content_digest must be a tagged sha256 digest")
        with self._lock:
            artifact = self._objects.get(content_digest)
            if artifact is None:
                raise LookupError(f"cache miss for {content_digest}")
            try:
                artifact.verify(content_digest)
            except ArtifactPoisonedError:
                # Evict corrupted entry.
                self._objects.pop(content_digest, None)
                self._total_bytes = max(0, self._total_bytes - artifact.byte_length)
                raise
            return artifact

    def contains(self, content_digest: str) -> bool:
        with self._lock:
            return content_digest in self._objects

    def put_manifest(self, manifest: ArtifactManifest) -> ArtifactManifest:
        """Cache an immutable artifact manifest keyed by its content digest."""

        if not isinstance(manifest, ArtifactManifest):
            raise InvalidRequestError("manifest must be an ArtifactManifest")
        if manifest.schema_version != ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise InvalidRequestError("unsupported artifact manifest schema")
        digest = manifest.manifest_digest
        with self._lock:
            existing = self._manifests.get(digest)
            if existing is not None:
                if existing.to_dict() != manifest.to_dict():
                    raise ArtifactPoisonedError(
                        "manifest CAS collision with differing content"
                    )
                return existing
            if len(self._manifests) >= self._max_objects:
                raise ResourceLimitError("artifact cache manifest count exceeded")
            self._manifests[digest] = manifest
            if self._root is not None:
                path = self._manifest_path(digest)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(manifest.to_canonical_json(), encoding="utf-8")
                os.replace(tmp, path)
            return manifest

    def get_manifest(self, manifest_digest: str) -> ArtifactManifest:
        if not isinstance(manifest_digest, str) or not manifest_digest.startswith(
            "sha256:"
        ):
            raise InvalidRequestError("manifest_digest must be a tagged sha256 digest")
        with self._lock:
            manifest = self._manifests.get(manifest_digest)
            if manifest is None:
                raise LookupError(f"manifest cache miss for {manifest_digest}")
            if manifest.manifest_digest != manifest_digest:
                self._manifests.pop(manifest_digest, None)
                raise ArtifactPoisonedError("cached manifest digest mismatch")
            return manifest

    def metadata(self, content_digest: str) -> CacheObjectMeta:
        artifact = self.get(content_digest)
        return CacheObjectMeta(
            content_digest=artifact.content_digest,
            byte_length=artifact.byte_length,
            kind=artifact.kind.value
            if isinstance(artifact.kind, ArtifactKind)
            else str(artifact.kind),
            media_type=artifact.media_type,
            label=artifact.label,
        )

    def list_digests(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._objects))

    def clear_memory(self) -> None:
        """Drop in-memory entries (does not delete durable root files)."""

        with self._lock:
            self._objects.clear()
            self._manifests.clear()
            self._total_bytes = 0


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CacheObjectMeta",
    "ContractArtifactCache",
    "DEFAULT_MAX_OBJECTS",
    "DEFAULT_MAX_TOTAL_BYTES",
]
