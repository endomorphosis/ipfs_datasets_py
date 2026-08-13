"""Fail-closed snapshot transport for Hugging Face Bucket objects.

The transport lists and range-reads ``hf://buckets/{bucket_id}/{path}`` objects
through an explicitly injected client.  Every list and read is bounded by
object and byte budgets, confined to normalized POSIX paths, checked for
listing drift against a pinned expected listing when one is supplied, and
verified by expected size plus SHA-256 of the returned bytes or the object's
Xet identity.  Successful listings emit a content-addressed, secret-free
content-root receipt that never grants source authority: buckets are mutable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request

from ..logic.ir_core.canonical import canonical_json_bytes
from ..logic.ir_core.identity import canonical_identity, cid_v1_from_digest
from .bucket import (
    HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION,
    HuggingFaceBucketError,
    HuggingFaceBucketListing,
    HuggingFaceBucketStore,
)

HF_BUCKET_URI_SCHEME: Final = "hf"
HF_BUCKET_URI_NETLOC: Final = "buckets"
HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION: Final = (
    "huggingface-bucket-content-root-receipt/v1"
)
HF_BUCKET_TRANSPORT_DOMAIN: Final = "huggingface-bucket-transport"
DEFAULT_OPEN_US_LAW_BUCKET_ID: Final = "justicedao/open-us-law-bucket"
OPEN_US_LAW_OBSERVED_OBJECT_COUNT: Final = 107
OPEN_US_LAW_OBSERVED_PARQUET_COUNT: Final = 103
OPEN_US_LAW_OBSERVED_TOTAL_BYTES: Final = 1_134_269_198
OPEN_US_LAW_ABSENT_JURISDICTIONS: Final = ("GA", "NC")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_BUCKET_ID_RE: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_CONTENT_RANGE_RE: Final = re.compile(
    r"^bytes (\d+)-(\d+)/(\d+|\*)$",
    re.IGNORECASE,
)
_READ_CHUNK: Final = 1024 * 1024
_RECEIPT_FIELDS: Final = frozenset(
    {
        "budgets",
        "bucket_id",
        "content_root",
        "grants_authority",
        "listing_schema_version",
        "listing_sha256",
        "object_count",
        "objects",
        "prefix",
        "schema_version",
        "total_size_bytes",
        "uri",
    }
)
_BUDGET_FIELDS: Final = frozenset(
    {
        "max_bytes",
        "max_object_bytes",
        "max_objects",
        "max_range_bytes",
    }
)
_RECEIPT_OBJECT_FIELDS: Final = frozenset(
    {
        "media_type",
        "path",
        "sha256",
        "size_bytes",
        "uri",
        "xet_hash",
    }
)


class HuggingFaceBucketTransportError(ValueError):
    """Raised when a bucket snapshot transport operation fails closed."""


class HuggingFaceBucketBudgetError(HuggingFaceBucketTransportError):
    """Raised before a list or range-read would exceed an explicit budget."""


class HuggingFaceBucketPathError(HuggingFaceBucketTransportError):
    """Raised when a URI or object path escapes the bucket root."""


class HuggingFaceBucketListingDriftError(HuggingFaceBucketTransportError):
    """Raised when a live listing disagrees with a pinned expected listing."""


class HuggingFaceBucketIntegrityError(HuggingFaceBucketTransportError):
    """Raised when size, SHA-256, or Xet identity cannot be verified."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HuggingFaceBucketTransportError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise HuggingFaceBucketTransportError(f"{label} must not contain NUL")
    return value


def _posix_path(value: Any, *, label: str = "path") -> str:
    text = _text(value, label=label)
    if "\\" in text:
        raise HuggingFaceBucketPathError(f"{label} must use POSIX separators")
    parsed = PurePosixPath(text)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != text
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise HuggingFaceBucketPathError(
            f"{label} must be a normalized root-relative POSIX path"
        )
    return text


def _sha256_hex(value: Any, *, label: str = "sha256") -> str:
    text = _text(value, label=label).casefold()
    if _SHA256_RE.fullmatch(text) is None:
        raise HuggingFaceBucketIntegrityError(
            f"{label} must be a full 64-character lowercase hexadecimal digest"
        )
    return text


def _non_negative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HuggingFaceBucketTransportError(
            f"{label} must be a non-negative integer"
        )
    return value


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HuggingFaceBucketBudgetError(f"{label} must be a positive integer")
    return value


def _bucket_id(value: Any) -> str:
    text = _text(value, label="bucket_id")
    if _BUCKET_ID_RE.fullmatch(text) is None:
        raise HuggingFaceBucketPathError(
            "bucket_id must be a namespace/name Hugging Face bucket identity"
        )
    return text


def _decode_uri_segment(segment: str, *, label: str) -> str:
    try:
        decoded = unquote(segment, errors="strict")
    except UnicodeDecodeError as exc:
        raise HuggingFaceBucketPathError(f"{label} is not valid percent-encoding") from exc
    if unquote(decoded, errors="strict") != decoded:
        raise HuggingFaceBucketPathError(f"{label} contains layered percent-encoding")
    return decoded


def _query_one(query: Mapping[str, list[str]], *names: str) -> str | None:
    present = [name for name in names if name in query]
    if not present:
        return None
    if len(present) != 1 or len(query[present[0]]) != 1:
        raise HuggingFaceBucketTransportError(
            f"URI query must provide at most one {'/'.join(names)} value"
        )
    return query[present[0]][0]


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketRef:
    """Parsed ``hf://buckets/{bucket_id}/{path}`` reference."""

    bucket_id: str
    path: str = ""
    listing_sha256: str | None = None
    expected_sha256: str | None = None
    expected_xet_hash: str | None = None
    expected_size_bytes: int | None = None

    def __post_init__(self) -> None:
        bucket_id = _bucket_id(self.bucket_id)
        path = _posix_path(self.path) if self.path else ""
        listing_sha256 = (
            _sha256_hex(self.listing_sha256, label="listing_sha256")
            if self.listing_sha256 is not None
            else None
        )
        expected_sha256 = (
            _sha256_hex(self.expected_sha256, label="expected_sha256")
            if self.expected_sha256 is not None
            else None
        )
        expected_xet_hash = (
            _sha256_hex(self.expected_xet_hash, label="expected_xet_hash")
            if self.expected_xet_hash is not None
            else None
        )
        expected_size = self.expected_size_bytes
        if expected_size is not None:
            expected_size = _non_negative_int(expected_size, label="expected_size_bytes")
        object.__setattr__(self, "bucket_id", bucket_id)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "listing_sha256", listing_sha256)
        object.__setattr__(self, "expected_sha256", expected_sha256)
        object.__setattr__(self, "expected_xet_hash", expected_xet_hash)
        object.__setattr__(self, "expected_size_bytes", expected_size)

    @property
    def uri(self) -> str:
        suffix = f"/{self.path}" if self.path else ""
        query: list[str] = []
        if self.listing_sha256 is not None:
            query.append(f"listing_sha256={self.listing_sha256}")
        if self.expected_sha256 is not None:
            query.append(f"sha256={self.expected_sha256}")
        if self.expected_xet_hash is not None:
            query.append(f"xet_hash={self.expected_xet_hash}")
        if self.expected_size_bytes is not None:
            query.append(f"size_bytes={self.expected_size_bytes}")
        encoded = f"{HF_BUCKET_URI_SCHEME}://{HF_BUCKET_URI_NETLOC}/{self.bucket_id}{suffix}"
        if query:
            encoded = f"{encoded}?{'&'.join(query)}"
        return encoded


def parse_hf_bucket_uri(value: Any) -> HuggingFaceBucketRef:
    """Parse and confine an ``hf://buckets/...`` object or listing URI."""

    text = _text(value, label="uri")
    parsed = urlparse(text)
    if parsed.scheme != HF_BUCKET_URI_SCHEME:
        raise HuggingFaceBucketPathError("uri scheme must be hf")
    if parsed.netloc != HF_BUCKET_URI_NETLOC:
        raise HuggingFaceBucketPathError("uri must use the hf://buckets/ namespace")
    if parsed.params or parsed.fragment:
        raise HuggingFaceBucketPathError("uri must not include params or a fragment")
    if parsed.username is not None or parsed.password is not None:
        raise HuggingFaceBucketPathError("uri must not include userinfo")
    raw_parts = [part for part in parsed.path.split("/")]
    if raw_parts[:1] != [""]:
        raise HuggingFaceBucketPathError("uri path must be absolute under hf://buckets")
    decoded_parts = [
        _decode_uri_segment(part, label="uri path segment")
        for part in raw_parts[1:]
        if part != ""
    ]
    if len(raw_parts) > 1 and any(part == "" for part in raw_parts[1:-1]):
        raise HuggingFaceBucketPathError("uri path must not contain empty segments")
    if len(decoded_parts) < 2:
        raise HuggingFaceBucketPathError("uri must include a namespace/name bucket_id")
    if any(part in {".", ".."} for part in decoded_parts):
        raise HuggingFaceBucketPathError("uri path escapes the bucket root")
    bucket_id = _bucket_id(f"{decoded_parts[0]}/{decoded_parts[1]}")
    object_path = "/".join(decoded_parts[2:])
    if object_path:
        object_path = _posix_path(object_path, label="uri object path")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    size_text = _query_one(query, "size_bytes", "size")
    expected_size: int | None = None
    if size_text is not None:
        if re.fullmatch(r"[0-9]+", size_text) is None:
            raise HuggingFaceBucketTransportError("uri size_bytes must be a non-negative integer")
        expected_size = int(size_text)
    return HuggingFaceBucketRef(
        bucket_id=bucket_id,
        path=object_path,
        listing_sha256=_query_one(query, "listing_sha256", "inventory_sha256"),
        expected_sha256=_query_one(query, "sha256", "expected_sha256"),
        expected_xet_hash=_query_one(query, "xet_hash", "expected_xet_hash"),
        expected_size_bytes=expected_size,
    )


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketBudgets:
    """Hard bounds for listing and range-reading a bucket snapshot."""

    max_objects: int
    max_bytes: int
    max_object_bytes: int
    max_range_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_objects", _positive_int(self.max_objects, label="max_objects"))
        object.__setattr__(self, "max_bytes", _positive_int(self.max_bytes, label="max_bytes"))
        object.__setattr__(
            self,
            "max_object_bytes",
            _positive_int(self.max_object_bytes, label="max_object_bytes"),
        )
        object.__setattr__(
            self,
            "max_range_bytes",
            _positive_int(self.max_range_bytes, label="max_range_bytes"),
        )
        if self.max_object_bytes > self.max_bytes:
            raise HuggingFaceBucketBudgetError(
                "max_object_bytes cannot exceed max_bytes"
            )
        if self.max_range_bytes > self.max_bytes:
            raise HuggingFaceBucketBudgetError(
                "max_range_bytes cannot exceed max_bytes"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_bytes": self.max_bytes,
            "max_object_bytes": self.max_object_bytes,
            "max_objects": self.max_objects,
            "max_range_bytes": self.max_range_bytes,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HuggingFaceBucketBudgets:
        if not isinstance(value, Mapping) or set(value) != _BUDGET_FIELDS:
            raise HuggingFaceBucketBudgetError("budgets have unknown or missing fields")
        return cls(
            max_objects=value["max_objects"],
            max_bytes=value["max_bytes"],
            max_object_bytes=value["max_object_bytes"],
            max_range_bytes=value["max_range_bytes"],
        )


DEFAULT_OPEN_US_LAW_BUDGETS = HuggingFaceBucketBudgets(
    max_objects=128,
    max_bytes=2 * 1024 * 1024 * 1024,
    max_object_bytes=256 * 1024 * 1024,
    max_range_bytes=64 * 1024 * 1024,
)


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketRangeRead:
    """Verified payload returned by one confined range-read."""

    uri: str
    bucket_id: str
    path: str
    start: int
    end: int
    size_bytes: int
    object_size_bytes: int
    sha256: str
    xet_hash: str | None
    identity_kind: str
    payload: bytes

    def __post_init__(self) -> None:
        if self.identity_kind not in {"sha256", "xet", "sha256+xet"}:
            raise HuggingFaceBucketIntegrityError("identity_kind is unsupported")
        if self.end < self.start:
            raise HuggingFaceBucketTransportError("range end must not precede start")
        if self.size_bytes != self.end - self.start:
            raise HuggingFaceBucketIntegrityError("range size_bytes does not match the slice")
        if len(self.payload) != self.size_bytes:
            raise HuggingFaceBucketIntegrityError("range payload length does not match size_bytes")
        digest = hashlib.sha256(self.payload).hexdigest()
        if digest != self.sha256:
            raise HuggingFaceBucketIntegrityError("range sha256 does not match payload bytes")


@dataclass(frozen=True, slots=True)
class HuggingFaceBucketContentRootReceipt:
    """Content-addressed receipt for one listed bucket view.

    The receipt names the listing digest as the content root.  It never grants
    source authority: a Hugging Face Bucket is mutable and is only a seed.
    """

    bucket_id: str
    prefix: str
    listing_sha256: str
    object_count: int
    total_size_bytes: int
    objects: tuple[Mapping[str, Any], ...]
    uri: str
    budgets: HuggingFaceBucketBudgets
    listing_schema_version: str = HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION
    grants_authority: bool = False
    schema_version: str = HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION
    receipt_id: str = ""

    def __post_init__(self) -> None:
        bucket_id = _bucket_id(self.bucket_id)
        prefix = _posix_path(self.prefix, label="prefix") if self.prefix else ""
        listing_sha256 = _sha256_hex(self.listing_sha256, label="listing_sha256")
        object_count = _non_negative_int(self.object_count, label="object_count")
        total_size = _non_negative_int(self.total_size_bytes, label="total_size_bytes")
        if not isinstance(self.budgets, HuggingFaceBucketBudgets):
            raise HuggingFaceBucketTransportError("budgets must be HuggingFaceBucketBudgets")
        if self.listing_schema_version != HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION:
            raise HuggingFaceBucketTransportError("unsupported listing schema_version")
        if self.schema_version != HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION:
            raise HuggingFaceBucketTransportError("unsupported content-root receipt schema_version")
        if self.grants_authority is not False:
            raise HuggingFaceBucketTransportError(
                "bucket content-root receipts must not grant authority"
            )
        if isinstance(self.objects, (str, bytes, bytearray)) or not isinstance(
            self.objects, Sequence
        ):
            raise HuggingFaceBucketTransportError("objects must be a sequence")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        running = 0
        for item in self.objects:
            if not isinstance(item, Mapping) or set(item) != _RECEIPT_OBJECT_FIELDS:
                raise HuggingFaceBucketTransportError(
                    "receipt object has unknown or missing fields"
                )
            path = _posix_path(item["path"])
            if path in seen:
                raise HuggingFaceBucketTransportError("receipt object paths must be unique")
            if prefix and path != prefix and not path.startswith(f"{prefix}/"):
                raise HuggingFaceBucketPathError("receipt object path is outside the prefix")
            size_bytes = _non_negative_int(item["size_bytes"], label="size_bytes")
            xet_hash = _sha256_hex(item["xet_hash"], label="xet_hash")
            sha256 = item["sha256"]
            if sha256 is not None:
                sha256 = _sha256_hex(sha256, label="object sha256")
            object_uri = (
                f"{HF_BUCKET_URI_SCHEME}://{HF_BUCKET_URI_NETLOC}/{bucket_id}/{path}"
            )
            parsed = parse_hf_bucket_uri(_text(item["uri"], label="object uri"))
            if parsed.bucket_id != bucket_id or parsed.path != path:
                raise HuggingFaceBucketIntegrityError(
                    "receipt object uri does not match bucket_id and path"
                )
            seen.add(path)
            running += size_bytes
            normalized.append(
                {
                    "media_type": _text(item["media_type"], label="media_type").casefold(),
                    "path": path,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "uri": object_uri,
                    "xet_hash": xet_hash,
                }
            )
        normalized.sort(key=lambda item: item["path"])
        if object_count != len(normalized):
            raise HuggingFaceBucketIntegrityError("receipt object_count does not match objects")
        if total_size != running:
            raise HuggingFaceBucketIntegrityError(
                "receipt total_size_bytes does not match object sizes"
            )
        uri = _text(self.uri, label="uri")
        parsed_uri = parse_hf_bucket_uri(uri)
        if parsed_uri.bucket_id != bucket_id:
            raise HuggingFaceBucketIntegrityError("receipt uri bucket_id does not match")
        if parsed_uri.path not in {"", prefix}:
            raise HuggingFaceBucketIntegrityError("receipt uri path must be empty or the prefix")
        object.__setattr__(self, "bucket_id", bucket_id)
        object.__setattr__(self, "prefix", prefix)
        object.__setattr__(self, "listing_sha256", listing_sha256)
        object.__setattr__(self, "object_count", object_count)
        object.__setattr__(self, "total_size_bytes", total_size)
        object.__setattr__(self, "objects", tuple(normalized))
        object.__setattr__(self, "uri", parsed_uri.uri)
        computed = self.identity
        if self.receipt_id and self.receipt_id != computed.cid:
            raise HuggingFaceBucketIntegrityError(
                "receipt_id does not match the content-addressed receipt"
            )
        object.__setattr__(self, "receipt_id", computed.cid)

    @property
    def content_root(self) -> str:
        return self.listing_sha256

    @property
    def content_root_cid(self) -> str:
        return cid_v1_from_digest(bytes.fromhex(self.listing_sha256))

    def to_dict(self) -> dict[str, Any]:
        return {
            "budgets": self.budgets.to_dict(),
            "bucket_id": self.bucket_id,
            "content_root": self.content_root,
            "grants_authority": False,
            "listing_schema_version": self.listing_schema_version,
            "listing_sha256": self.listing_sha256,
            "object_count": self.object_count,
            "objects": [dict(item) for item in self.objects],
            "prefix": self.prefix,
            "schema_version": self.schema_version,
            "total_size_bytes": self.total_size_bytes,
            "uri": self.uri,
        }

    @property
    def identity(self):
        return canonical_identity(
            self.to_dict(),
            domain=HF_BUCKET_TRANSPORT_DOMAIN,
            schema_version=self.schema_version,
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceBucketContentRootReceipt:
        if not isinstance(value, Mapping):
            raise HuggingFaceBucketTransportError("content-root receipt must be a mapping")
        payload = dict(value)
        receipt_id = payload.pop("receipt_id", "")
        if set(payload) != _RECEIPT_FIELDS:
            raise HuggingFaceBucketTransportError(
                "content-root receipt has unknown or missing fields"
            )
        if payload["content_root"] != payload["listing_sha256"]:
            raise HuggingFaceBucketIntegrityError(
                "content_root must equal listing_sha256"
            )
        return cls(
            bucket_id=payload["bucket_id"],
            prefix=payload["prefix"],
            listing_sha256=payload["listing_sha256"],
            object_count=payload["object_count"],
            total_size_bytes=payload["total_size_bytes"],
            objects=tuple(payload["objects"]),
            uri=payload["uri"],
            budgets=HuggingFaceBucketBudgets.from_mapping(payload["budgets"]),
            listing_schema_version=payload["listing_schema_version"],
            grants_authority=payload["grants_authority"],
            schema_version=payload["schema_version"],
            receipt_id=receipt_id or "",
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> HuggingFaceBucketContentRootReceipt:
        if isinstance(value, bytes | bytearray):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HuggingFaceBucketTransportError(
                    "content-root receipt JSON must be UTF-8"
                ) from exc
        if not isinstance(value, str):
            raise TypeError("content-root receipt JSON must be str or bytes")
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise HuggingFaceBucketTransportError(
                f"invalid content-root receipt JSON: {exc}"
            ) from exc
        return cls.from_dict(decoded)


def load_expected_listing(path: str | Path) -> HuggingFaceBucketListing:
    """Load a pinned listing or a compact fixture wrapper that contains one."""

    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise HuggingFaceBucketTransportError("expected listing must be a regular file")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HuggingFaceBucketTransportError(f"invalid expected listing JSON: {exc}") from exc
    return listing_from_mapping(payload)


def listing_from_mapping(value: Mapping[str, Any]) -> HuggingFaceBucketListing:
    """Accept a raw listing or a fixture wrapper with a ``listing`` object."""

    if not isinstance(value, Mapping):
        raise HuggingFaceBucketTransportError("expected listing must be a mapping")
    if "listing" in value:
        raw = value["listing"]
        if not isinstance(raw, Mapping):
            raise HuggingFaceBucketTransportError("fixture listing must be a mapping")
        return HuggingFaceBucketListing.from_dict(raw)
    return HuggingFaceBucketListing.from_dict(value)


def content_root_receipt_from_listing(
    listing: HuggingFaceBucketListing,
    *,
    budgets: HuggingFaceBucketBudgets,
    object_sha256: Mapping[str, str] | None = None,
    uri: str | None = None,
) -> HuggingFaceBucketContentRootReceipt:
    """Build a secret-free content-root receipt from a verified listing."""

    if not isinstance(listing, HuggingFaceBucketListing):
        raise TypeError("listing must be a HuggingFaceBucketListing")
    digests = object_sha256 or {}
    objects = []
    for item in listing.objects:
        sha256 = digests.get(item.path)
        objects.append(
            {
                "media_type": item.media_type,
                "path": item.path,
                "sha256": sha256,
                "size_bytes": item.size_bytes,
                "uri": f"{HF_BUCKET_URI_SCHEME}://{HF_BUCKET_URI_NETLOC}/{listing.bucket_id}/{item.path}",
                "xet_hash": item.xet_hash,
            }
        )
    receipt_uri = uri or f"{HF_BUCKET_URI_SCHEME}://{HF_BUCKET_URI_NETLOC}/{listing.bucket_id}"
    if listing.prefix and uri is None:
        receipt_uri = f"{receipt_uri}/{listing.prefix}"
    return HuggingFaceBucketContentRootReceipt(
        bucket_id=listing.bucket_id,
        prefix=listing.prefix,
        listing_sha256=listing.listing_sha256,
        object_count=listing.object_count,
        total_size_bytes=listing.total_size_bytes,
        objects=tuple(objects),
        uri=receipt_uri,
        budgets=budgets,
    )


def _compare_listings(
    expected: HuggingFaceBucketListing,
    live: HuggingFaceBucketListing,
) -> None:
    if expected.bucket_id != live.bucket_id:
        raise HuggingFaceBucketListingDriftError(
            f"listing drift: bucket_id {live.bucket_id!r} != {expected.bucket_id!r}"
        )
    if expected.prefix != live.prefix:
        raise HuggingFaceBucketListingDriftError(
            f"listing drift: prefix {live.prefix!r} != {expected.prefix!r}"
        )
    expected_map = {item.path: item for item in expected.objects}
    live_map = {item.path: item for item in live.objects}
    added = tuple(sorted(set(live_map) - set(expected_map)))
    removed = tuple(sorted(set(expected_map) - set(live_map)))
    changed: list[str] = []
    for path in sorted(set(expected_map) & set(live_map)):
        want = expected_map[path]
        got = live_map[path]
        if want.size_bytes != got.size_bytes or want.xet_hash != got.xet_hash:
            changed.append(path)
    if added or removed or changed or expected.listing_sha256 != live.listing_sha256:
        raise HuggingFaceBucketListingDriftError(
            "listing drift: "
            f"added={list(added)} removed={list(removed)} changed={changed}"
        )


def _enforce_listing_budgets(
    listing: HuggingFaceBucketListing,
    budgets: HuggingFaceBucketBudgets,
) -> None:
    if listing.object_count > budgets.max_objects:
        raise HuggingFaceBucketBudgetError(
            f"listing object count {listing.object_count} exceeds max_objects {budgets.max_objects}"
        )
    if listing.total_size_bytes > budgets.max_bytes:
        raise HuggingFaceBucketBudgetError(
            f"listing total size {listing.total_size_bytes} exceeds max_bytes {budgets.max_bytes}"
        )
    for item in listing.objects:
        if item.size_bytes > budgets.max_object_bytes:
            raise HuggingFaceBucketBudgetError(
                f"object {item.path!r} size {item.size_bytes} exceeds max_object_bytes "
                f"{budgets.max_object_bytes}"
            )


def _parse_content_range(value: Any) -> tuple[int, int, int | None]:
    text = _text(value, label="Content-Range")
    match = _CONTENT_RANGE_RE.fullmatch(text.strip())
    if match is None:
        raise HuggingFaceBucketIntegrityError("Content-Range header is malformed")
    start = int(match.group(1))
    end = int(match.group(2))
    total: int | None
    if match.group(3) == "*":
        total = None
    else:
        total = int(match.group(3))
    if end < start:
        raise HuggingFaceBucketIntegrityError("Content-Range end precedes start")
    return start, end, total


def _range_headers(client: Any) -> dict[str, str]:
    builder = getattr(client, "_headers", None)
    if callable(builder):
        headers = dict(builder())
    else:
        headers = {
            "User-Agent": str(
                getattr(client, "user_agent", "ipfs-datasets-py/huggingface-bucket-transport")
            )
        }
        token = getattr(client, "token", None)
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/octet-stream"
    return headers


def _range_read_via_http(
    client: Any,
    *,
    bucket_id: str,
    path: str,
    start: int,
    end: int,
    expected_xet_hash: str | None,
    expected_size_bytes: int | None,
) -> tuple[bytes, str | None]:
    opener = getattr(client, "opener", None)
    endpoint = getattr(client, "endpoint", None)
    if opener is None or not callable(getattr(opener, "open", None)):
        raise HuggingFaceBucketTransportError(
            "bucket client must provide range_read_bucket_file or an HTTP opener"
        )
    if not isinstance(endpoint, str) or not endpoint:
        raise HuggingFaceBucketTransportError("HTTP bucket client must provide an endpoint")
    timeout = float(getattr(client, "timeout_seconds", 60.0))
    inclusive_end = end - 1
    url = (
        f"{endpoint.rstrip('/')}/buckets/{quote(bucket_id, safe='/')}"
        f"/resolve/{quote(path, safe='')}"
    )
    headers = _range_headers(client)
    headers["Range"] = f"bytes={start}-{inclusive_end}"
    request = Request(url, headers=headers, method="GET")
    payload = bytearray()
    response_xet: str | None = None
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)
            response_xet = response.headers.get("X-Xet-Hash")
            content_range = response.headers.get("Content-Range")
            requested_len = end - start
            if status in {0, 206}:
                if not content_range:
                    if status == 206:
                        raise HuggingFaceBucketIntegrityError(
                            "partial response is missing Content-Range"
                        )
                else:
                    got_start, got_end, total = _parse_content_range(content_range)
                    if got_start != start or got_end != inclusive_end:
                        raise HuggingFaceBucketIntegrityError(
                            "Content-Range does not match the requested slice"
                        )
                    if (
                        expected_size_bytes is not None
                        and total is not None
                        and total != expected_size_bytes
                    ):
                        raise HuggingFaceBucketIntegrityError(
                            "Content-Range total does not match expected object size"
                        )
            elif status == 200:
                if start != 0 or (
                    expected_size_bytes is not None and end != expected_size_bytes
                ):
                    raise HuggingFaceBucketIntegrityError(
                        "server ignored Range and returned a full object"
                    )
            else:
                raise HuggingFaceBucketIntegrityError(
                    f"range-read returned unexpected HTTP status {status}"
                )
            if (
                expected_xet_hash is not None
                and response_xet is not None
                and response_xet != expected_xet_hash
            ):
                raise HuggingFaceBucketIntegrityError(
                    "download response does not match discovered Xet hash"
                )
            while True:
                remaining = requested_len - len(payload)
                chunk = response.read(min(_READ_CHUNK, remaining + 1))
                if not chunk:
                    break
                if len(payload) + len(chunk) > requested_len:
                    raise HuggingFaceBucketIntegrityError(
                        "range-read exceeded the requested byte range"
                    )
                payload.extend(chunk)
    except HuggingFaceBucketTransportError:
        raise
    except Exception as exc:
        raise HuggingFaceBucketTransportError(f"failed to range-read bucket object: {exc}") from exc
    if len(payload) != requested_len:
        raise HuggingFaceBucketIntegrityError("range-read returned an incomplete slice")
    if expected_xet_hash is not None and response_xet is None:
        raise HuggingFaceBucketIntegrityError(
            "range-read response did not provide a Xet identity"
        )
    return bytes(payload), response_xet


def _range_read_via_client(
    client: Any,
    *,
    bucket_id: str,
    path: str,
    start: int,
    end: int,
    expected_xet_hash: str | None,
    expected_size_bytes: int | None,
) -> tuple[bytes, str | None]:
    operation = getattr(client, "range_read_bucket_file", None)
    if not callable(operation):
        return _range_read_via_http(
            client,
            bucket_id=bucket_id,
            path=path,
            start=start,
            end=end,
            expected_xet_hash=expected_xet_hash,
            expected_size_bytes=expected_size_bytes,
        )
    try:
        result = operation(
            bucket_id=bucket_id,
            path=path,
            start=start,
            end=end,
            expected_xet_hash=expected_xet_hash,
            expected_size_bytes=expected_size_bytes,
        )
    except HuggingFaceBucketTransportError:
        raise
    except Exception as exc:
        raise HuggingFaceBucketTransportError(f"failed to range-read bucket object: {exc}") from exc
    response_xet: str | None = expected_xet_hash
    if isinstance(result, Mapping):
        raw = result.get("bytes", result.get("payload"))
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise HuggingFaceBucketTransportError(
                "range_read_bucket_file mapping must include bytes"
            )
        payload = bytes(raw)
        header_xet = result.get("xet_hash", result.get("xetHash"))
        if header_xet is not None:
            response_xet = _sha256_hex(header_xet, label="xet_hash")
    elif isinstance(result, (bytes, bytearray, memoryview)):
        payload = bytes(result)
    else:
        raise HuggingFaceBucketTransportError(
            "range_read_bucket_file must return bytes or a mapping"
        )
    return payload, response_xet


def _promote_destination(destination: Path, payload: bytes) -> Path:
    if destination.exists() or destination.is_symlink():
        raise HuggingFaceBucketTransportError(
            "bucket range-read destination must not already exist"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise HuggingFaceBucketTransportError("bucket range-read parent must not be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".partial",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_bytes(payload)
        os.replace(temporary_path, destination)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise
    return destination


class HuggingFaceBucketTransport:
    """List and range-read a Hugging Face Bucket under fail-closed budgets."""

    def __init__(
        self,
        *,
        client: Any,
        budgets: HuggingFaceBucketBudgets,
        expected_listing: HuggingFaceBucketListing | None = None,
        bucket_id: str | None = None,
    ) -> None:
        if client is None:
            raise HuggingFaceBucketTransportError("an injected bucket client is required")
        if not isinstance(budgets, HuggingFaceBucketBudgets):
            raise HuggingFaceBucketTransportError("budgets must be HuggingFaceBucketBudgets")
        resolved_bucket = bucket_id
        if expected_listing is not None:
            if not isinstance(expected_listing, HuggingFaceBucketListing):
                raise TypeError("expected_listing must be a HuggingFaceBucketListing")
            if resolved_bucket is None:
                resolved_bucket = expected_listing.bucket_id
            elif resolved_bucket != expected_listing.bucket_id:
                raise HuggingFaceBucketTransportError(
                    "bucket_id does not match the pinned expected listing"
                )
        if resolved_bucket is None:
            raise HuggingFaceBucketTransportError("bucket_id is required")
        self.client = client
        self.budgets = budgets
        self.expected_listing = expected_listing
        self.bucket_id = _bucket_id(resolved_bucket)
        self._bytes_consumed = 0
        self._paths_read: set[str] = set()

    @property
    def bytes_consumed(self) -> int:
        return self._bytes_consumed

    @property
    def objects_read(self) -> int:
        return len(self._paths_read)

    def parse_uri(self, uri: str) -> HuggingFaceBucketRef:
        ref = parse_hf_bucket_uri(uri)
        if ref.bucket_id != self.bucket_id:
            raise HuggingFaceBucketPathError(
                f"uri bucket_id {ref.bucket_id!r} is outside {self.bucket_id!r}"
            )
        return ref

    def list(
        self,
        uri: str | None = None,
        *,
        prefix: str = "",
    ) -> HuggingFaceBucketListing:
        """Discover objects, enforce budgets, and reject listing drift."""

        resolved_prefix = prefix
        pinned_digest: str | None = None
        if uri is not None:
            ref = self.parse_uri(uri)
            if ref.path:
                resolved_prefix = ref.path
            pinned_digest = ref.listing_sha256
        elif resolved_prefix:
            resolved_prefix = _posix_path(resolved_prefix, label="prefix")
        if self.expected_listing is not None and resolved_prefix != self.expected_listing.prefix:
            raise HuggingFaceBucketListingDriftError(
                "requested prefix does not match the pinned expected listing"
            )
        try:
            listing = HuggingFaceBucketStore(self.bucket_id, client=self.client).discover(
                prefix=resolved_prefix
            )
        except HuggingFaceBucketError as exc:
            message = str(exc)
            if "must be a normalized root-relative POSIX path" in message:
                raise HuggingFaceBucketPathError(message) from exc
            raise HuggingFaceBucketTransportError(f"failed to list bucket: {exc}") from exc
        _enforce_listing_budgets(listing, self.budgets)
        if self.expected_listing is not None:
            _compare_listings(self.expected_listing, listing)
        if pinned_digest is not None and listing.listing_sha256 != pinned_digest:
            raise HuggingFaceBucketListingDriftError(
                "live listing_sha256 does not match the URI pin"
            )
        return listing

    def snapshot(
        self,
        uri: str | None = None,
        *,
        prefix: str = "",
        object_sha256: Mapping[str, str] | None = None,
    ) -> HuggingFaceBucketContentRootReceipt:
        """List the bucket view and emit a content-root receipt."""

        listing = self.list(uri, prefix=prefix)
        receipt_uri = uri
        if receipt_uri is None:
            receipt_uri = f"{HF_BUCKET_URI_SCHEME}://{HF_BUCKET_URI_NETLOC}/{self.bucket_id}"
            if listing.prefix:
                receipt_uri = f"{receipt_uri}/{listing.prefix}"
        return content_root_receipt_from_listing(
            listing,
            budgets=self.budgets,
            object_sha256=object_sha256,
            uri=receipt_uri,
        )

    def range_read(
        self,
        uri: str,
        *,
        start: int,
        end: int,
        expected_sha256: str | None = None,
        expected_xet_hash: str | None = None,
        expected_size_bytes: int | None = None,
        destination: str | Path | None = None,
    ) -> HuggingFaceBucketRangeRead:
        """Range-read one object and verify size plus SHA-256 or Xet identity."""

        ref = self.parse_uri(uri)
        if not ref.path:
            raise HuggingFaceBucketPathError("range-read uri must name an object path")
        start = _non_negative_int(start, label="start")
        end = _non_negative_int(end, label="end")
        if end <= start:
            raise HuggingFaceBucketTransportError("range end must be greater than start")
        range_len = end - start
        if range_len > self.budgets.max_range_bytes:
            raise HuggingFaceBucketBudgetError(
                f"range length {range_len} exceeds max_range_bytes {self.budgets.max_range_bytes}"
            )
        if self._bytes_consumed + range_len > self.budgets.max_bytes:
            raise HuggingFaceBucketBudgetError(
                f"range-read would exceed max_bytes {self.budgets.max_bytes}"
            )
        if (
            ref.path not in self._paths_read
            and len(self._paths_read) + 1 > self.budgets.max_objects
        ):
            raise HuggingFaceBucketBudgetError(
                f"range-read would exceed max_objects {self.budgets.max_objects}"
            )

        listed = None
        if self.expected_listing is not None:
            listed = next(
                (item for item in self.expected_listing.objects if item.path == ref.path),
                None,
            )
            if listed is None:
                raise HuggingFaceBucketListingDriftError(
                    f"object {ref.path!r} is not present in the pinned listing"
                )

        object_size = expected_size_bytes
        if object_size is None:
            object_size = ref.expected_size_bytes
        if object_size is None and listed is not None:
            object_size = listed.size_bytes
        if object_size is not None:
            object_size = _non_negative_int(object_size, label="expected_size_bytes")
            if end > object_size:
                raise HuggingFaceBucketIntegrityError(
                    "requested range extends past the expected object size"
                )
            if object_size > self.budgets.max_object_bytes:
                raise HuggingFaceBucketBudgetError(
                    f"object {ref.path!r} size {object_size} exceeds max_object_bytes "
                    f"{self.budgets.max_object_bytes}"
                )

        want_sha256 = expected_sha256 or ref.expected_sha256
        want_xet = expected_xet_hash or ref.expected_xet_hash
        if want_xet is None and listed is not None:
            want_xet = listed.xet_hash
        if want_sha256 is not None:
            want_sha256 = _sha256_hex(want_sha256, label="expected_sha256")
        if want_xet is not None:
            want_xet = _sha256_hex(want_xet, label="expected_xet_hash")
        if want_sha256 is None and want_xet is None:
            raise HuggingFaceBucketIntegrityError(
                "range-read requires expected SHA256 or Xet identity"
            )
        if listed is not None and want_xet is not None and want_xet != listed.xet_hash:
            raise HuggingFaceBucketListingDriftError(
                "requested Xet identity does not match the pinned listing"
            )
        if (
            listed is not None
            and object_size is not None
            and object_size != listed.size_bytes
        ):
            raise HuggingFaceBucketListingDriftError(
                "requested size does not match the pinned listing"
            )

        payload, response_xet = _range_read_via_client(
            self.client,
            bucket_id=self.bucket_id,
            path=ref.path,
            start=start,
            end=end,
            expected_xet_hash=want_xet,
            expected_size_bytes=object_size,
        )
        if len(payload) != range_len:
            raise HuggingFaceBucketIntegrityError("range-read size mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if want_sha256 is not None and digest != want_sha256:
            raise HuggingFaceBucketIntegrityError("range-read sha256 mismatch")
        if want_xet is not None:
            if response_xet is not None and response_xet != want_xet:
                raise HuggingFaceBucketIntegrityError("range-read Xet hash mismatch")
            if response_xet is None and want_sha256 is None:
                raise HuggingFaceBucketIntegrityError(
                    "range-read could not verify Xet identity"
                )
        if object_size is None:
            object_size = end if start == 0 else end
        if want_sha256 is not None and want_xet is not None:
            identity_kind = "sha256+xet"
        elif want_sha256 is not None:
            identity_kind = "sha256"
        else:
            identity_kind = "xet"

        if destination is not None:
            _promote_destination(Path(destination), payload)

        self._bytes_consumed += range_len
        self._paths_read.add(ref.path)
        return HuggingFaceBucketRangeRead(
            uri=ref.uri,
            bucket_id=self.bucket_id,
            path=ref.path,
            start=start,
            end=end,
            size_bytes=range_len,
            object_size_bytes=object_size,
            sha256=digest,
            xet_hash=want_xet,
            identity_kind=identity_kind,
            payload=payload,
        )


__all__ = [
    "DEFAULT_OPEN_US_LAW_BUCKET_ID",
    "DEFAULT_OPEN_US_LAW_BUDGETS",
    "HF_BUCKET_CONTENT_ROOT_RECEIPT_SCHEMA_VERSION",
    "HF_BUCKET_TRANSPORT_DOMAIN",
    "HF_BUCKET_URI_NETLOC",
    "HF_BUCKET_URI_SCHEME",
    "HuggingFaceBucketBudgetError",
    "HuggingFaceBucketBudgets",
    "HuggingFaceBucketContentRootReceipt",
    "HuggingFaceBucketIntegrityError",
    "HuggingFaceBucketListingDriftError",
    "HuggingFaceBucketPathError",
    "HuggingFaceBucketRangeRead",
    "HuggingFaceBucketRef",
    "HuggingFaceBucketTransport",
    "HuggingFaceBucketTransportError",
    "OPEN_US_LAW_ABSENT_JURISDICTIONS",
    "OPEN_US_LAW_OBSERVED_OBJECT_COUNT",
    "OPEN_US_LAW_OBSERVED_PARQUET_COUNT",
    "OPEN_US_LAW_OBSERVED_TOTAL_BYTES",
    "content_root_receipt_from_listing",
    "listing_from_mapping",
    "load_expected_listing",
    "parse_hf_bucket_uri",
]
