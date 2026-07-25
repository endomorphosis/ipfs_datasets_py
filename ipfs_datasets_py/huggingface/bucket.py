"""Deterministic, read-only inventories for Hugging Face buckets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..logic.ir_core.canonical import canonical_json_bytes

HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION = "huggingface-bucket-inventory/v1"
_SHA256_LENGTH = 64


class HuggingFaceBucketError(ValueError):
    """Raised when bucket inventory evidence is incomplete or unsafe."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HuggingFaceBucketError(f"{label} must be a non-empty string without surrounding whitespace")
    if "\x00" in value:
        raise HuggingFaceBucketError(f"{label} must not contain NUL")
    return value


def _path(value: Any, *, label: str = "path") -> str:
    text = _text(value, label=label)
    if "\\" in text:
        raise HuggingFaceBucketError(f"{label} must use POSIX separators")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or parsed.as_posix() != text or any(part in {"", ".", ".."} for part in parsed.parts):
        raise HuggingFaceBucketError(f"{label} must be a normalized root-relative POSIX path")
    return text


def _sha256(value: Any) -> str:
    text = _text(value, label="sha256")
    if len(text) != _SHA256_LENGTH:
        raise HuggingFaceBucketError("sha256 must be a full 64-character lowercase hexadecimal digest")
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise HuggingFaceBucketError("sha256 must be a full 64-character lowercase hexadecimal digest") from exc
    if text != text.casefold():
        raise HuggingFaceBucketError("sha256 must use lowercase hexadecimal")
    return text


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketObject:
    """Canonical integrity metadata for one bucket object."""

    path: str
    size_bytes: int
    sha256: str
    etag: str
    media_type: str

    def __post_init__(self) -> None:
        path = _path(self.path)
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise HuggingFaceBucketError("size_bytes must be a non-negative integer")
        sha256 = _sha256(self.sha256)
        etag = _text(self.etag, label="etag")
        media_type = _text(self.media_type, label="media_type").casefold()
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "etag", etag)
        object.__setattr__(self, "media_type", media_type)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "etag": self.etag,
            "media_type": self.media_type,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HuggingFaceBucketObject:
        if not isinstance(value, Mapping):
            raise HuggingFaceBucketError("bucket object must be a mapping")
        aliases = {
            "path": ("path", "key", "name"),
            "size_bytes": ("size_bytes", "size"),
            "sha256": ("sha256", "checksum_sha256"),
            "etag": ("etag", "e_tag"),
            "media_type": ("media_type", "content_type", "mime_type"),
        }
        normalized: dict[str, Any] = {}
        for field, names in aliases.items():
            present = [name for name in names if name in value]
            if len(present) != 1:
                raise HuggingFaceBucketError(f"bucket object must provide exactly one {field} field")
            normalized[field] = value[present[0]]
        return cls(**normalized)


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketInventory:
    """Sorted inventory whose digest commits to every required object field."""

    bucket_id: str
    objects: tuple[HuggingFaceBucketObject, ...]
    prefix: str = ""
    schema_version: str = HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        bucket_id = _text(self.bucket_id, label="bucket_id")
        prefix = _path(self.prefix, label="prefix") if self.prefix else ""
        if self.schema_version != HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION:
            raise HuggingFaceBucketError("unsupported Hugging Face bucket inventory schema_version")
        try:
            objects = tuple(sorted(self.objects, key=lambda item: item.path))
        except (AttributeError, TypeError) as exc:
            raise HuggingFaceBucketError("objects must contain HuggingFaceBucketObject values") from exc
        if any(not isinstance(item, HuggingFaceBucketObject) for item in objects):
            raise HuggingFaceBucketError("objects must contain HuggingFaceBucketObject values")
        paths = [item.path for item in objects]
        if len(paths) != len(set(paths)):
            raise HuggingFaceBucketError("bucket inventory paths must be unique")
        if prefix and any(path != prefix and not path.startswith(f"{prefix}/") for path in paths):
            raise HuggingFaceBucketError("bucket object path is outside the requested prefix")
        object.__setattr__(self, "bucket_id", bucket_id)
        object.__setattr__(self, "prefix", prefix)
        object.__setattr__(self, "objects", objects)

    @property
    def object_count(self) -> int:
        return len(self.objects)

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.objects)

    @property
    def inventory_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def inventory_digest(self) -> str:
        """Compatibility spelling for the canonical inventory SHA-256."""

        return self.inventory_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "objects": [item.to_dict() for item in self.objects],
            "prefix": self.prefix,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceBucketInventory:
        if not isinstance(value, Mapping):
            raise HuggingFaceBucketError("bucket inventory must be a mapping")
        expected = {"bucket_id", "objects", "prefix", "schema_version"}
        if set(value) != expected:
            raise HuggingFaceBucketError("bucket inventory has unknown or missing fields")
        raw_objects = value["objects"]
        if not isinstance(raw_objects, list):
            raise HuggingFaceBucketError("bucket inventory objects must be an array")
        if not all(isinstance(item, Mapping) for item in raw_objects):
            raise HuggingFaceBucketError("bucket inventory objects must contain mappings")
        return cls(
            bucket_id=value["bucket_id"],
            prefix=value["prefix"],
            objects=tuple(HuggingFaceBucketObject.from_mapping(item) for item in raw_objects),
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> HuggingFaceBucketInventory:
        if isinstance(value, bytes | bytearray):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HuggingFaceBucketError("bucket inventory JSON must be UTF-8") from exc
        if not isinstance(value, str):
            raise TypeError("bucket inventory JSON must be str or bytes")
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise HuggingFaceBucketError(f"invalid bucket inventory JSON: {exc}") from exc
        return cls.from_dict(decoded)


class HuggingFaceBucketStore:
    """Read-only bucket adapter using an explicitly injected client.

    The client must expose ``list_bucket_tree`` and may expose the read-only
    ``download_bucket_file`` operation.  No upload, delete, copy, move,
    overwrite, or release-pointer methods are part of this adapter.
    """

    def __init__(self, bucket_id: str, *, client: Any) -> None:
        self.bucket_id = _text(bucket_id, label="bucket_id")
        if client is None:
            raise HuggingFaceBucketError("an injected bucket client is required")
        self.client = client

    def inventory(self, *, prefix: str = "") -> HuggingFaceBucketInventory:
        normalized_prefix = _path(prefix, label="prefix") if prefix else ""
        list_tree = getattr(self.client, "list_bucket_tree", None)
        if not callable(list_tree):
            raise HuggingFaceBucketError("bucket client must provide list_bucket_tree")
        try:
            response = list_tree(
                bucket_id=self.bucket_id,
                prefix=normalized_prefix,
            )
        except Exception as exc:
            raise HuggingFaceBucketError(f"failed to inventory bucket: {exc}") from exc
        if isinstance(response, Mapping):
            raw_objects = response.get("objects", response.get("items"))
        else:
            raw_objects = response
        if isinstance(raw_objects, str | bytes | bytearray | Mapping) or not isinstance(raw_objects, Iterable):
            raise HuggingFaceBucketError("list_bucket_tree must return an object sequence")
        objects = tuple(
            item if isinstance(item, HuggingFaceBucketObject) else HuggingFaceBucketObject.from_mapping(item)
            for item in raw_objects
        )
        return HuggingFaceBucketInventory(
            bucket_id=self.bucket_id,
            prefix=normalized_prefix,
            objects=objects,
        )

    def fetch(
        self,
        item: HuggingFaceBucketObject,
        destination: str | Path,
    ) -> Path:
        """Download, verify, and atomically promote one inventoried object."""

        if not isinstance(item, HuggingFaceBucketObject):
            raise TypeError("item must be a HuggingFaceBucketObject")
        download = getattr(self.client, "download_bucket_file", None)
        if not callable(download):
            raise HuggingFaceBucketError("bucket client must provide download_bucket_file")
        destination_path = Path(destination)
        if destination_path.exists() or destination_path.is_symlink():
            raise HuggingFaceBucketError("bucket download destination must not already exist")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.parent.is_symlink():
            raise HuggingFaceBucketError("bucket download parent must not be a symlink")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.",
            suffix=".partial",
            dir=destination_path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            result = download(
                bucket_id=self.bucket_id,
                path=item.path,
                destination=temporary_path,
            )
            if isinstance(result, bytes | bytearray | memoryview):
                temporary_path.write_bytes(bytes(result))
            elif isinstance(result, int) and not isinstance(result, bool):
                pass
            elif result is not None:
                source = Path(result)
                if source.is_symlink() or not source.is_file():
                    raise HuggingFaceBucketError("bucket client returned a path that is not a regular file")
                if source.resolve() != temporary_path.resolve():
                    shutil.copyfile(source, temporary_path)
            self.verify_download(item, temporary_path)
            os.replace(temporary_path, destination_path)
            return destination_path
        except HuggingFaceBucketError:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        except Exception as exc:
            if temporary_path.exists():
                temporary_path.unlink()
            raise HuggingFaceBucketError(f"failed to fetch bucket object: {exc}") from exc

    @staticmethod
    def verify_download(item: HuggingFaceBucketObject, path: str | Path) -> Path:
        """Verify locally downloaded bucket bytes against inventory evidence."""

        if not isinstance(item, HuggingFaceBucketObject):
            raise TypeError("item must be a HuggingFaceBucketObject")
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise HuggingFaceBucketError("downloaded bucket object must be a regular file")
        if candidate.stat().st_size != item.size_bytes:
            raise HuggingFaceBucketError("downloaded bucket object size mismatch")
        digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != item.sha256:
            raise HuggingFaceBucketError("downloaded bucket object sha256 mismatch")
        return candidate


__all__ = [
    "HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION",
    "HuggingFaceBucketError",
    "HuggingFaceBucketInventory",
    "HuggingFaceBucketObject",
    "HuggingFaceBucketStore",
]
