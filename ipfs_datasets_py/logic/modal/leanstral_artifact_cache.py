"""Optional distributed artifact cache for Leanstral audit payloads.

The local Leanstral audit cache remains the source of truth for normal runs.
This module adds an opt-in sidecar cache that can store verified audit payloads
through the ipfs_accelerate_py storage layer, which prefers ipfs_kit_py when it
is available.  The sidecar is intentionally fail-soft: backend errors should
never prevent local audit caching or validation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable


LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION = (
    "legal-ir-leanstral-artifact-cache-index-v1"
)

LEANSTRAL_ARTIFACT_CACHE_ENV = "IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_CACHE"
LEANSTRAL_AUDIT_IPFS_CACHE_ENV = "LEANSTRAL_AUDIT_IPFS_CACHE"
LEANSTRAL_ARTIFACT_CACHE_INDEX_ENV = "IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_INDEX_PATH"
LEANSTRAL_ARTIFACT_CACHE_PIN_ENV = "IPFS_DATASETS_PY_LEANSTRAL_ARTIFACT_PIN"


@runtime_checkable
class ArtifactStorage(Protocol):
    """Storage protocol shared by StorageWrapper-style adapters and tests."""

    def write_file(
        self,
        data: bytes | str,
        filename: Optional[str] = None,
        pin: bool = False,
    ) -> str: ...

    def read_file(self, identifier: str) -> Optional[bytes]: ...


@dataclass(frozen=True)
class LeanstralArtifactCacheRecord:
    """Index record mapping a logical audit cache key to distributed content."""

    key: str
    identifier: str
    sha256: str
    size_bytes: int
    artifact_type: str
    created_at: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralArtifactCacheRecord":
        return cls(
            key=str(data.get("key") or "").strip(),
            identifier=str(data.get("identifier") or data.get("cid") or "").strip(),
            sha256=str(data.get("sha256") or "").strip(),
            size_bytes=int(data.get("size_bytes") or 0),
            artifact_type=str(data.get("artifact_type") or "").strip(),
            created_at=float(data.get("created_at") or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "created_at": round(float(self.created_at), 6),
            "identifier": self.identifier,
            "key": self.key,
            "sha256": self.sha256,
            "size_bytes": int(self.size_bytes),
        }


def leanstral_artifact_cache_enabled() -> bool:
    """Return true when the distributed Leanstral artifact cache is requested."""

    return _truthy(os.getenv(LEANSTRAL_ARTIFACT_CACHE_ENV)) or _truthy(
        os.getenv(LEANSTRAL_AUDIT_IPFS_CACHE_ENV)
    )


class LeanstralArtifactCache:
    """Fail-soft sidecar cache for JSON audit artifacts."""

    def __init__(
        self,
        *,
        index_path: str | Path,
        storage: Optional[ArtifactStorage] = None,
        cache_dir: Optional[str | Path] = None,
        pin: bool = False,
        enabled: bool = True,
    ) -> None:
        self.index_path = Path(index_path).expanduser()
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self.pin = bool(pin)
        self.enabled = bool(enabled)
        self._storage = storage if storage is not None else self._build_storage()

    @classmethod
    def from_env(
        cls,
        cache_dir: Optional[str | Path] = None,
    ) -> Optional["LeanstralArtifactCache"]:
        """Build a configured cache only when explicitly enabled by env."""

        if not leanstral_artifact_cache_enabled():
            return None
        resolved_cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        raw_index_path = os.getenv(LEANSTRAL_ARTIFACT_CACHE_INDEX_ENV, "").strip()
        if raw_index_path:
            index_path = Path(raw_index_path).expanduser()
        elif resolved_cache_dir is not None:
            index_path = resolved_cache_dir / ".leanstral-artifact-cache-index.json"
        else:
            index_path = (
                Path.home()
                / ".cache"
                / "ipfs_datasets_py"
                / "leanstral-artifact-cache-index.json"
            )
        return cls(
            index_path=index_path,
            cache_dir=resolved_cache_dir,
            pin=_truthy(os.getenv(LEANSTRAL_ARTIFACT_CACHE_PIN_ENV)),
            enabled=True,
        )

    def put_json(
        self,
        key: str,
        payload: Mapping[str, Any],
        *,
        artifact_type: str = "leanstral_audit",
    ) -> Optional[LeanstralArtifactCacheRecord]:
        """Store a JSON payload and update the local mutable index."""

        if not self.enabled or self._storage is None:
            return None
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return None
        data = _json_bytes(payload)
        digest = hashlib.sha256(data).hexdigest()
        filename = f"{normalized_key}.json"
        try:
            identifier = self._storage.write_file(data, filename=filename, pin=self.pin)
        except Exception:
            return None
        identifier = str(identifier or "").strip()
        if not identifier:
            return None
        record = LeanstralArtifactCacheRecord(
            key=normalized_key,
            identifier=identifier,
            sha256=digest,
            size_bytes=len(data),
            artifact_type=str(artifact_type or "").strip() or "leanstral_artifact",
            created_at=time.time(),
        )
        try:
            index = self._load_index()
            index[normalized_key] = record.to_dict()
            self._save_index(index)
        except Exception:
            return None
        return record

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Load and verify a JSON payload from distributed storage."""

        if not self.enabled or self._storage is None:
            return None
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return None
        try:
            index = self._load_index()
            raw_record = index.get(normalized_key)
            if not isinstance(raw_record, Mapping):
                return None
            record = LeanstralArtifactCacheRecord.from_mapping(raw_record)
            if not record.identifier or record.key != normalized_key:
                return None
            data = self._storage.read_file(record.identifier)
        except Exception:
            return None
        if data is None:
            return None
        if isinstance(data, str):
            data = data.encode("utf-8")
        if record.sha256 and hashlib.sha256(data).hexdigest() != record.sha256:
            return None
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return dict(payload) if isinstance(payload, Mapping) else None

    def _build_storage(self) -> Optional[ArtifactStorage]:
        try:
            from ipfs_accelerate_py.common.storage_wrapper import StorageWrapper

            cache_dir = os.getenv("IPFS_KIT_CACHE_DIR", "").strip()
            if not cache_dir and self.cache_dir is not None:
                cache_dir = str(self.cache_dir / ".distributed-artifacts")
            return StorageWrapper(
                enable_distributed=True,
                cache_dir=cache_dir or None,
                auto_detect_ci=False,
            )
        except Exception:
            return None

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.is_file():
            return {}
        with self.index_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, Mapping) and payload.get("schema_version") == (
            LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION
        ):
            artifacts = payload.get("artifacts")
        elif isinstance(payload, Mapping):
            artifacts = payload
        else:
            artifacts = None
        if not isinstance(artifacts, Mapping):
            return {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for key, value in artifacts.items():
            if isinstance(value, Mapping):
                normalized[str(key)] = dict(value)
        return normalized

    def _save_index(self, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifacts": {str(key): dict(value) for key, value in artifacts.items()},
            "schema_version": LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION,
            "updated_at": round(time.time(), 6),
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.index_path.parent,
            prefix=f".{self.index_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, self.index_path)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "LEANSTRAL_ARTIFACT_CACHE_ENV",
    "LEANSTRAL_ARTIFACT_CACHE_INDEX_ENV",
    "LEANSTRAL_ARTIFACT_CACHE_INDEX_SCHEMA_VERSION",
    "LEANSTRAL_ARTIFACT_CACHE_PIN_ENV",
    "LEANSTRAL_AUDIT_IPFS_CACHE_ENV",
    "ArtifactStorage",
    "LeanstralArtifactCache",
    "LeanstralArtifactCacheRecord",
    "leanstral_artifact_cache_enabled",
]
