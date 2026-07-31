"""Deterministic, read-only inventories for Hugging Face buckets."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from ..logic.ir_core.canonical import canonical_json_bytes

HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION = "huggingface-bucket-inventory/v1"
HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION = "huggingface-bucket-listing/v1"
_MAX_BUCKET_TREE_PAGES = 10_000
_LINK_TOKEN_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


class HuggingFaceBucketError(ValueError):
    """Raised when bucket inventory evidence is incomplete or unsafe."""


def _link_header_next_targets(value: Any) -> tuple[str, ...]:
    """Parse RFC 8288-style Link values and return ``rel=next`` targets."""

    if value is None or value == "":
        return ()
    if not isinstance(value, str):
        raise HuggingFaceBucketError("bucket pagination Link header must be text")
    if not value.strip():
        return ()

    targets: list[str] = []
    cursor = 0
    length = len(value)
    while cursor < length:
        while cursor < length and value[cursor] in " \t":
            cursor += 1
        if cursor >= length or value[cursor] != "<":
            raise HuggingFaceBucketError("bucket pagination Link header is malformed")
        target_end = value.find(">", cursor + 1)
        if target_end < 0:
            raise HuggingFaceBucketError("bucket pagination Link header is malformed")
        target = value[cursor + 1 : target_end]
        if (
            not target
            or "<" in target
            or any(ord(character) <= 32 or ord(character) == 127 for character in target)
        ):
            raise HuggingFaceBucketError("bucket pagination Link target is malformed")
        cursor = target_end + 1
        relations: list[str] = []
        saw_relation = False

        while True:
            while cursor < length and value[cursor] in " \t":
                cursor += 1
            if cursor >= length or value[cursor] == ",":
                break
            if value[cursor] != ";":
                raise HuggingFaceBucketError("bucket pagination Link header is malformed")
            cursor += 1
            while cursor < length and value[cursor] in " \t":
                cursor += 1
            name_match = _LINK_TOKEN_RE.match(value, cursor)
            if name_match is None:
                raise HuggingFaceBucketError("bucket pagination Link parameter is malformed")
            name = name_match.group().casefold()
            cursor = name_match.end()
            while cursor < length and value[cursor] in " \t":
                cursor += 1
            if cursor >= length or value[cursor] != "=":
                raise HuggingFaceBucketError("bucket pagination Link parameter is malformed")
            cursor += 1
            while cursor < length and value[cursor] in " \t":
                cursor += 1
            if cursor >= length:
                raise HuggingFaceBucketError("bucket pagination Link parameter is malformed")
            if value[cursor] == '"':
                cursor += 1
                parsed_value: list[str] = []
                while cursor < length and value[cursor] != '"':
                    character = value[cursor]
                    if character == "\\":
                        cursor += 1
                        if cursor >= length:
                            raise HuggingFaceBucketError(
                                "bucket pagination Link quoted value is malformed"
                            )
                        character = value[cursor]
                    if ord(character) < 32 or ord(character) == 127:
                        raise HuggingFaceBucketError(
                            "bucket pagination Link quoted value is malformed"
                        )
                    parsed_value.append(character)
                    cursor += 1
                if cursor >= length:
                    raise HuggingFaceBucketError(
                        "bucket pagination Link quoted value is malformed"
                    )
                cursor += 1
                parameter_value = "".join(parsed_value)
            else:
                value_match = _LINK_TOKEN_RE.match(value, cursor)
                if value_match is None:
                    raise HuggingFaceBucketError(
                        "bucket pagination Link parameter value is malformed"
                    )
                parameter_value = value_match.group()
                cursor = value_match.end()
            if name == "rel":
                if saw_relation:
                    raise HuggingFaceBucketError(
                        "bucket pagination Link value has multiple rel parameters"
                    )
                saw_relation = True
                relations.extend(
                    relation.casefold() for relation in parameter_value.split()
                )

        if "next" in relations:
            targets.append(target)
        if cursor < length:
            cursor += 1
            next_cursor = cursor
            while next_cursor < length and value[next_cursor] in " \t":
                next_cursor += 1
            if next_cursor >= length:
                raise HuggingFaceBucketError("bucket pagination Link header is malformed")

    return tuple(targets)


def _content_length(value: Any) -> int | None:
    """Parse a Content-Length field, including merged identical field values."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise HuggingFaceBucketError("download Content-Length header must be text")
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(re.fullmatch(r"[0-9]+", part) is None for part in parts):
        raise HuggingFaceBucketError("download Content-Length header is malformed")
    lengths = {int(part) for part in parts}
    if len(lengths) != 1:
        raise HuggingFaceBucketError("download Content-Length header is conflicting")
    return lengths.pop()


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
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise HuggingFaceBucketError("sha256 must be a full 64-character lowercase hexadecimal digest")
    return text


def _xet_hash(value: Any) -> str:
    text = _text(value, label="xet_hash")
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise HuggingFaceBucketError("xet_hash must be a full 64-character lowercase hexadecimal digest")
    return text


def _timestamp(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = _text(value, label=label)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HuggingFaceBucketError(f"{label} must be an ISO-8601 timestamp") from exc
    else:
        raise HuggingFaceBucketError(f"{label} must be an ISO-8601 timestamp or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HuggingFaceBucketError(f"{label} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _source_field(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return default


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketListingObject:
    """Unverified metadata discovered from a mutable Hugging Face bucket.

    ``xet_hash`` is the storage-layer identity returned by Hugging Face.  It is
    deliberately not exposed as ``sha256``: only hashing downloaded bytes can
    produce the raw SHA-256 required by :class:`HuggingFaceBucketObject`.
    """

    path: str
    size_bytes: int
    xet_hash: str
    media_type: str
    mtime: str | None = None
    uploaded_at: str | None = None

    def __post_init__(self) -> None:
        path = _path(self.path)
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise HuggingFaceBucketError("size_bytes must be a non-negative integer")
        xet_hash = _xet_hash(self.xet_hash)
        media_type = _text(self.media_type, label="media_type").casefold()
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "xet_hash", xet_hash)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "mtime", _timestamp(self.mtime, label="mtime"))
        object.__setattr__(
            self,
            "uploaded_at",
            _timestamp(self.uploaded_at, label="uploaded_at"),
        )

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "media_type": self.media_type,
            "mtime": self.mtime,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at,
            "xet_hash": self.xet_hash,
        }

    @classmethod
    def from_source(cls, value: Any) -> HuggingFaceBucketListingObject:
        path = _source_field(value, "path", "key", "name")
        media_type = _source_field(
            value,
            "media_type",
            "content_type",
            "contentType",
            "mime_type",
        )
        if media_type is None and isinstance(path, str):
            media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return cls(
            path=path,
            size_bytes=_source_field(value, "size_bytes", "size"),
            xet_hash=_source_field(value, "xet_hash", "xetHash"),
            media_type=media_type,
            mtime=_source_field(value, "mtime"),
            uploaded_at=_source_field(value, "uploaded_at", "uploadedAt"),
        )


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketListing:
    """Canonical, unverified discovery receipt for a mutable bucket view."""

    bucket_id: str
    objects: tuple[HuggingFaceBucketListingObject, ...]
    prefix: str = ""
    schema_version: str = HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        bucket_id = _text(self.bucket_id, label="bucket_id")
        prefix = _path(self.prefix, label="prefix") if self.prefix else ""
        if self.schema_version != HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION:
            raise HuggingFaceBucketError("unsupported Hugging Face bucket listing schema_version")
        try:
            objects = tuple(sorted(self.objects, key=lambda item: item.path))
        except (AttributeError, TypeError) as exc:
            raise HuggingFaceBucketError("objects must contain HuggingFaceBucketListingObject values") from exc
        if any(not isinstance(item, HuggingFaceBucketListingObject) for item in objects):
            raise HuggingFaceBucketError("objects must contain HuggingFaceBucketListingObject values")
        paths = [item.path for item in objects]
        if len(paths) != len(set(paths)):
            raise HuggingFaceBucketError("bucket listing paths must be unique")
        if prefix and any(path != prefix and not path.startswith(f"{prefix}/") for path in paths):
            raise HuggingFaceBucketError("bucket listing path is outside the requested prefix")
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
    def listing_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

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
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceBucketListing:
        if not isinstance(value, Mapping):
            raise HuggingFaceBucketError("bucket listing must be a mapping")
        expected = {"bucket_id", "objects", "prefix", "schema_version"}
        if set(value) != expected:
            raise HuggingFaceBucketError("bucket listing has unknown or missing fields")
        raw_objects = value["objects"]
        if not isinstance(raw_objects, list):
            raise HuggingFaceBucketError("bucket listing objects must be an array")
        return cls(
            bucket_id=value["bucket_id"],
            prefix=value["prefix"],
            objects=tuple(HuggingFaceBucketListingObject.from_source(item) for item in raw_objects),
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> HuggingFaceBucketListing:
        if isinstance(value, bytes | bytearray):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HuggingFaceBucketError("bucket listing JSON must be UTF-8") from exc
        if not isinstance(value, str):
            raise TypeError("bucket listing JSON must be str or bytes")
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise HuggingFaceBucketError(f"invalid bucket listing JSON: {exc}") from exc
        return cls.from_dict(decoded)


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

    def discover(self, *, prefix: str = "") -> HuggingFaceBucketListing:
        """Discover mutable bucket metadata without claiming content integrity."""

        normalized_prefix = _path(prefix, label="prefix") if prefix else ""
        list_tree = getattr(self.client, "list_bucket_tree", None)
        if not callable(list_tree):
            raise HuggingFaceBucketError("bucket client must provide list_bucket_tree")
        try:
            response = list_tree(
                bucket_id=self.bucket_id,
                prefix=normalized_prefix,
                recursive=True,
            )
        except Exception as exc:
            raise HuggingFaceBucketError(f"failed to list bucket: {exc}") from exc
        if isinstance(response, Mapping):
            raw_objects = response.get("objects", response.get("items"))
        else:
            raw_objects = response
        if isinstance(raw_objects, str | bytes | bytearray | Mapping) or not isinstance(raw_objects, Iterable):
            raise HuggingFaceBucketError("list_bucket_tree must return an object sequence")
        objects: list[HuggingFaceBucketListingObject] = []
        for item in raw_objects:
            if _source_field(item, "type") in {"directory", "folder"}:
                continue
            objects.append(
                item
                if isinstance(item, HuggingFaceBucketListingObject)
                else HuggingFaceBucketListingObject.from_source(item)
            )
        return HuggingFaceBucketListing(
            bucket_id=self.bucket_id,
            prefix=normalized_prefix,
            objects=tuple(objects),
        )

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

    def fetch_discovered(
        self,
        item: HuggingFaceBucketListingObject,
        destination: str | Path,
    ) -> HuggingFaceBucketObject:
        """Download discovery metadata and return verified raw-content evidence.

        Discovery metadata contains no raw-file checksum, so an existing local
        file can never prove that it contains the bytes named by ``xet_hash``.
        Resumable callers must validate cache bytes against a previously pinned
        raw SHA-256 with :meth:`verify_discovered_file`.
        """

        if not isinstance(item, HuggingFaceBucketListingObject):
            raise TypeError("item must be a HuggingFaceBucketListingObject")
        destination_path = Path(destination)
        if destination_path.exists() or destination_path.is_symlink():
            raise HuggingFaceBucketError(
                "bucket download destination must not already exist"
            )
        download = getattr(self.client, "download_bucket_file", None)
        if not callable(download):
            raise HuggingFaceBucketError(
                "bucket client must provide Xet-bound download_bucket_file"
            )
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
                expected_xet_hash=item.xet_hash,
                expected_size_bytes=item.size_bytes,
            )
            if isinstance(result, bytes | bytearray | memoryview):
                temporary_path.write_bytes(bytes(result))
            elif isinstance(result, int) and not isinstance(result, bool):
                pass
            elif result is not None:
                source = Path(result)
                if source.is_symlink() or not source.is_file():
                    raise HuggingFaceBucketError(
                        "bucket client returned a path that is not a regular file"
                    )
                if source.resolve() != temporary_path.resolve():
                    shutil.copyfile(source, temporary_path)
            verified = self._hash_discovered_file(item, temporary_path)
            os.replace(temporary_path, destination_path)
            return verified
        except HuggingFaceBucketError:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        except Exception as exc:
            if temporary_path.exists():
                temporary_path.unlink()
            raise HuggingFaceBucketError(f"failed to fetch bucket object: {exc}") from exc

    @staticmethod
    def _hash_discovered_file(
        item: HuggingFaceBucketListingObject,
        path: str | Path,
    ) -> HuggingFaceBucketObject:
        """Hash bytes obtained from the Xet-bound download response."""

        if not isinstance(item, HuggingFaceBucketListingObject):
            raise TypeError("item must be a HuggingFaceBucketListingObject")
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise HuggingFaceBucketError("downloaded bucket object must be a regular file")
        if candidate.stat().st_size != item.size_bytes:
            raise HuggingFaceBucketError("downloaded bucket object size mismatch")
        digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return HuggingFaceBucketObject(
            path=item.path,
            size_bytes=item.size_bytes,
            sha256=digest.hexdigest(),
            etag=f"hf-xet:{item.xet_hash}",
            media_type=item.media_type,
        )

    @staticmethod
    def verify_discovered_file(
        item: HuggingFaceBucketListingObject,
        path: str | Path,
        *,
        expected_sha256: str,
    ) -> HuggingFaceBucketObject:
        """Validate cache bytes against previously pinned raw-file evidence."""

        expected = _sha256(expected_sha256)
        verified = HuggingFaceBucketStore._hash_discovered_file(item, path)
        if verified.sha256 != expected:
            raise HuggingFaceBucketError(
                "cached bucket object sha256 mismatch"
            )
        return verified

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


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Never forward a Hugging Face bearer token to a redirect host."""

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        redirected = super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )
        if redirected is not None and urlparse(request.full_url).netloc != urlparse(new_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


class HuggingFaceBucketHttpClient:
    """Dependency-free, read-only Hugging Face bucket HTTP client.

    This adapter implements only recursive listing and download.  It exists so
    applications pinned to ``huggingface_hub<1`` do not need to upgrade that
    package merely to consume the newer bucket API.  ``opener`` is injectable
    for deterministic tests.
    """

    def __init__(
        self,
        *,
        endpoint: str = "https://huggingface.co",
        token: str | None = None,
        opener: Any | None = None,
        timeout_seconds: float = 60.0,
        user_agent: str = "ipfs-datasets-py/huggingface-bucket-readonly",
    ) -> None:
        endpoint = _text(endpoint, label="endpoint").rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise HuggingFaceBucketError("endpoint must be an absolute HTTP(S) URL")
        if token is not None:
            token = _text(token, label="token")
        if opener is None:
            opener = build_opener(_SafeRedirectHandler())
        if not callable(getattr(opener, "open", None)):
            raise HuggingFaceBucketError("opener must provide an open operation")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int | float):
            raise HuggingFaceBucketError("timeout_seconds must be a positive number")
        if timeout_seconds <= 0:
            raise HuggingFaceBucketError("timeout_seconds must be a positive number")
        self.endpoint = endpoint
        self.token = token
        self.opener = opener
        self.timeout_seconds = float(timeout_seconds)
        self.user_agent = _text(user_agent, label="user_agent")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _open(self, request: Request) -> Any:
        return self.opener.open(request, timeout=self.timeout_seconds)

    def list_bucket_tree(
        self,
        *,
        bucket_id: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        bucket_id = _text(bucket_id, label="bucket_id")
        normalized_prefix = _path(prefix, label="prefix") if prefix else ""
        bucket_path = quote(bucket_id, safe="/")
        url = f"{self.endpoint}/api/buckets/{bucket_path}/tree"
        if normalized_prefix:
            url += f"/{quote(normalized_prefix, safe='')}"
        url += f"?recursive={'true' if recursive else 'false'}"
        rows: list[dict[str, Any]] = []
        visited_urls: set[str] = set()
        page_count = 0
        while url:
            if url in visited_urls:
                raise HuggingFaceBucketError("bucket pagination next link forms a loop")
            if page_count >= _MAX_BUCKET_TREE_PAGES:
                raise HuggingFaceBucketError("bucket pagination exceeded the page limit")
            visited_urls.add(url)
            page_count += 1
            request = Request(url, headers=self._headers(), method="GET")
            try:
                with self._open(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    get_all = getattr(response.headers, "get_all", None)
                    if callable(get_all):
                        raw_link_values = get_all("Link") or []
                    else:
                        raw_link = response.headers.get("Link")
                        raw_link_values = [] if raw_link is None else [raw_link]
            except Exception as exc:
                raise HuggingFaceBucketError(f"failed to list Hugging Face bucket: {exc}") from exc
            if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
                raise HuggingFaceBucketError("Hugging Face bucket tree response must be an array of objects")
            rows.extend(dict(item) for item in payload)
            if not all(isinstance(value, str) for value in raw_link_values):
                raise HuggingFaceBucketError("bucket pagination Link header must be text")
            next_targets = _link_header_next_targets(", ".join(raw_link_values))
            if len(next_targets) > 1:
                raise HuggingFaceBucketError("bucket pagination response has multiple next links")
            if next_targets:
                try:
                    next_url = urljoin(url, next_targets[0])
                    current = urlparse(next_url)
                except ValueError as exc:
                    raise HuggingFaceBucketError(
                        "bucket pagination next link is malformed"
                    ) from exc
                endpoint = urlparse(self.endpoint)
                if (
                    current.fragment
                    or current.username is not None
                    or current.password is not None
                    or (current.scheme.casefold(), current.netloc.casefold())
                    != (endpoint.scheme.casefold(), endpoint.netloc.casefold())
                ):
                    raise HuggingFaceBucketError("bucket pagination next link changed origin")
                url = next_url
            else:
                url = ""
        return rows

    def download_bucket_file(
        self,
        *,
        bucket_id: str,
        path: str,
        destination: str | Path,
        expected_xet_hash: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> int:
        bucket_id = _text(bucket_id, label="bucket_id")
        normalized_path = _path(path)
        if expected_xet_hash is not None:
            expected_xet_hash = _xet_hash(expected_xet_hash)
        if expected_size_bytes is not None and (
            isinstance(expected_size_bytes, bool) or not isinstance(expected_size_bytes, int) or expected_size_bytes < 0
        ):
            raise HuggingFaceBucketError("expected_size_bytes must be a non-negative integer")
        url = f"{self.endpoint}/buckets/{quote(bucket_id, safe='/')}/resolve/{quote(normalized_path, safe='')}"
        request = Request(
            url,
            headers={**self._headers(), "Accept": "application/octet-stream"},
            method="GET",
        )
        destination_path = Path(destination)
        try:
            with self._open(request) as response:
                response_xet = response.headers.get("X-Xet-Hash")
                declared_size = _content_length(
                    response.headers.get("Content-Length")
                )
                if (
                    expected_size_bytes is not None
                    and declared_size is not None
                    and declared_size > expected_size_bytes
                ):
                    raise HuggingFaceBucketError(
                        "download Content-Length exceeds expected size"
                    )
                if (
                    expected_xet_hash is not None
                    and response_xet != expected_xet_hash
                ):
                    final_path_segments = tuple(
                        unquote(segment, errors="strict")
                        for segment in urlparse(response.geturl()).path.split("/")
                    )
                    if expected_xet_hash not in final_path_segments:
                        raise HuggingFaceBucketError(
                            "download response does not match discovered Xet hash"
                        )
                size = 0
                stream_limit = expected_size_bytes
                if declared_size is not None:
                    stream_limit = (
                        declared_size
                        if stream_limit is None
                        else min(stream_limit, declared_size)
                    )
                with destination_path.open("wb") as handle:
                    while True:
                        read_size = 1024 * 1024
                        if stream_limit is not None:
                            read_size = min(read_size, stream_limit - size + 1)
                        chunk = response.read(read_size)
                        if not chunk:
                            break
                        next_size = size + len(chunk)
                        if stream_limit is not None and next_size > stream_limit:
                            raise HuggingFaceBucketError(
                                "downloaded bucket object exceeded expected size"
                            )
                        handle.write(chunk)
                        size = next_size
        except HuggingFaceBucketError:
            raise
        except Exception as exc:
            raise HuggingFaceBucketError(f"failed to download Hugging Face bucket file: {exc}") from exc
        if declared_size is not None and size != declared_size:
            raise HuggingFaceBucketError("download Content-Length does not match response body")
        if expected_size_bytes is not None and size != expected_size_bytes:
            raise HuggingFaceBucketError("downloaded bucket object size mismatch")
        return size


__all__ = [
    "HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION",
    "HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION",
    "HuggingFaceBucketError",
    "HuggingFaceBucketHttpClient",
    "HuggingFaceBucketInventory",
    "HuggingFaceBucketListing",
    "HuggingFaceBucketListingObject",
    "HuggingFaceBucketObject",
    "HuggingFaceBucketStore",
]
