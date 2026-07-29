"""Sharded graph manifest v2 (KGP-013).

Defines bounded virtual/physical shard descriptors, rendezvous routing, explicit
cross-shard adjacency, schema/index versions, statistics, checksums/CIDs,
bloom/index buckets, codecs, and provenance for sharded CAR graphs.

v1 compatibility: JSON produced by
``ipfs_datasets_py.search.graph_query.sharded_car.manifest.GraphShardManifest``
remains readable via :meth:`ShardedGraphManifest.from_dict` /
:func:`load_sharded_graph_manifest`.

This module is free of backend I/O (no Kubo/CAR fetch). Identity and integrity
reuse the KGP-004 canonical JSON + sha256 + CIDv1 helpers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Optional

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    ManifestError,
    ManifestIntegrityError,
    ManifestValidationError,
    ProvenanceDescriptor,
    canonical_json_bytes,
    cid_v1_from_sha256_hex,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Schema / bounds
# ---------------------------------------------------------------------------

SHARD_MANIFEST_V1: Final = "v1"
SHARD_MANIFEST_V2: Final = "kg-shard-manifest/v2"
SUPPORTED_VERSIONS: Final = frozenset({SHARD_MANIFEST_V1, SHARD_MANIFEST_V2})

CANONICAL_JSON_PROFILE: Final = "kg-canonical-json-v1"
IDENTITY_DOMAIN: Final = "kg.shard-manifest"

ROUTING_HASH_MODULO: Final = "hash-modulo"
ROUTING_RENDEZVOUS_HRW: Final = "rendezvous-hrw"
ROUTING_ALGORITHMS: Final = frozenset({ROUTING_HASH_MODULO, ROUTING_RENDEZVOUS_HRW})

HASH_FUNCTIONS: Final = frozenset({"sha256"})
KEY_NORMALIZATIONS: Final = frozenset({"utf-8", "utf-8-nfc", "identity"})

SHARD_CODECS: Final = frozenset(
    {
        "car",
        "dag-cbor",
        "json",
        "jsonl",
        "bloom-v1",
        "btree-v1",
        "raw",
        "gzip-json",
    }
)

INDEX_BUCKET_KINDS: Final = frozenset(
    {
        "headers",
        "type_index",
        "neighbors",
        "bloom_entity_type",
        "bloom_relationship_type",
        "bloom_entity_id",
        "adjacency",
        "composite",
        "other",
    }
)

ADJACENCY_DIRECTIONS: Final = frozenset({"outgoing", "incoming", "bidirectional"})

DEFAULT_SHARD_SIZE_LIMIT_BYTES: Final = 100 * 1024 * 1024
DEFAULT_TARGET_SHARD_BYTES: Final = 85 * 1024 * 1024
DEFAULT_VIRTUAL_SHARD_COUNT: Final = 1024

MAX_PHYSICAL_SHARDS: Final = 65_536
MAX_VIRTUAL_SHARDS: Final = 1_048_576
MAX_INDEX_BUCKETS_PER_SHARD: Final = 256
MAX_CROSS_SHARD_ADJACENCY: Final = 65_536
MAX_PATH_LENGTH: Final = 512
MAX_BYTES: Final = 2**63 - 1
MAX_COUNT: Final = 2**63 - 1
MAX_BLOOM_BITS: Final = 64 * 1024 * 1024  # 64 Mi bits (~8 MiB)
MAX_BLOOM_HASHES: Final = 64
MAX_PROVENANCE_STRING: Final = 1_024
MAX_PROVENANCE_KEYS: Final = 64
MAX_FIELD_NAMES: Final = 32

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(
    r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{50,120}|bagu[a-z2-7]{50,120})$"
)
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

_V2_REQUIRED_KEYS: Final = frozenset(
    {
        "version",
        "routing",
        "schema_version",
        "index_version",
        "codec",
        "physical_shards",
        "virtual_shards",
        "cross_shard_adjacency",
        "statistics",
        "provenance",
        "checksum",
        "root_cid",
        "shard_size_limit_bytes",
        "target_shard_bytes",
    }
)

_V2_OPTIONAL_KEYS: Final = frozenset(
    {
        "entity_type_bloom",
        "relationship_type_bloom",
    }
)

_V1_REQUIRED_KEYS: Final = frozenset({"version", "shards"})


# ---------------------------------------------------------------------------
# Errors (aliases so callers can catch package-local names)
# ---------------------------------------------------------------------------


class ShardManifestError(ManifestError):
    """Base validation error for shard manifests."""


class ShardManifestValidationError(ManifestValidationError, ShardManifestError):
    """Raised when a shard manifest or descriptor is malformed."""


class ShardManifestIntegrityError(ManifestIntegrityError, ShardManifestError):
    """Raised when checksums or CIDs disagree with declared values."""


def _reject(code: str, message: str) -> None:
    raise ShardManifestValidationError(code, message)


# ---------------------------------------------------------------------------
# Low-level validators
# ---------------------------------------------------------------------------


def _require_str(label: str, value: Any, *, code: str = "NONCANONICAL_VALUE") -> str:
    if not isinstance(value, str):
        _reject(code, f"{label} must be a string")
    if not value or value.strip() != value:
        _reject(code, f"{label} must be non-empty without surrounding whitespace")
    if "\x00" in value:
        _reject(code, f"{label} must not contain NUL")
    return value


def _require_id(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _ID_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} is not a stable identifier: {value!r}")
    if "//" in text or text.startswith("/") or text.endswith("/"):
        _reject("AMBIGUOUS_ID", f"{label} is ambiguous or path-like: {value!r}")
    return text


def _require_schema_ref(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _SCHEMA_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} is not a valid schema/index version: {value!r}")
    return text


def _require_nonneg_int(
    label: str,
    value: Any,
    *,
    maximum: int = MAX_BYTES,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _reject("INVALID_COUNT", f"{label} must be an integer (got {type(value).__name__})")
    if value < 0:
        _reject("INVALID_COUNT", f"{label} must be >= 0 (got {value})")
    if value > maximum:
        _reject("INVALID_COUNT", f"{label} exceeds maximum {maximum}")
    return value


def _require_positive_int(
    label: str,
    value: Any,
    *,
    maximum: int = MAX_BYTES,
) -> int:
    n = _require_nonneg_int(label, value, maximum=maximum)
    if n < 1:
        _reject("INVALID_COUNT", f"{label} must be >= 1 (got {n})")
    return n


def _require_codec(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if text not in SHARD_CODECS:
        _reject("NONCANONICAL_VALUE", f"{label} unknown codec: {text!r}")
    return text


def _require_cid(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if not _CID_RE.fullmatch(text):
        _reject("NONCANONICAL_VALUE", f"{label} is not a recognized CID: {value!r}")
    return text


def _optional_cid(label: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _require_cid(label, value)


def _safe_relative_path(label: str, value: Any) -> str:
    text = _require_str(label, value, code="UNSAFE_PATH")
    if len(text) > MAX_PATH_LENGTH:
        _reject("UNSAFE_PATH", f"{label} exceeds max path length {MAX_PATH_LENGTH}")
    if "\\" in text or "\x00" in text:
        _reject("UNSAFE_PATH", f"{label} must be a POSIX path without backslashes")
    if text.startswith("/") or text.startswith("~"):
        _reject("UNSAFE_PATH", f"{label} must be root-relative (got {value!r})")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _reject(
            "UNSAFE_PATH",
            f"{label} must be normalized root-relative without '.'/'..' segments",
        )
    normalized = path.as_posix()
    if normalized != text:
        _reject("UNSAFE_PATH", f"{label} must be canonical POSIX text (got {value!r})")
    return normalized


def _optional_path(label: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _safe_relative_path(label, value)


def _check_checksum_cid_pair(
    *,
    label: str,
    checksum_hex: Optional[str],
    cid: Optional[str],
) -> None:
    if checksum_hex is None or cid is None:
        return
    expected = cid_v1_from_sha256_hex(checksum_hex)
    if cid != expected:
        raise ShardManifestIntegrityError(
            "CHECKSUM_CID_MISMATCH",
            f"{label}: cid {cid!r} does not match sha256 {checksum_hex} "
            f"(expected {expected})",
        )


def _unique_ids(items: Iterable[str], *, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            _reject("AMBIGUOUS_ID", f"{label} contains duplicate id {item!r}")
        seen.add(item)


def _require_known_keys(
    data: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
) -> None:
    if not isinstance(data, Mapping):
        _reject("UNKNOWN_REQUIRED_FIELD", f"{label} must be a mapping")
    keys = frozenset(data.keys())
    missing = required - keys
    if missing:
        _reject(
            "UNKNOWN_REQUIRED_FIELD",
            f"{label} missing required field(s): {sorted(missing)}",
        )
    allowed = required | optional
    unknown = keys - allowed
    if unknown:
        _reject(
            "UNKNOWN_REQUIRED_FIELD",
            f"{label} has unknown field(s): {sorted(unknown)}",
        )


def _field_names(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _reject("NONCANONICAL_VALUE", f"{label} must be a sequence of field names")
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _FIELD_NAME_RE.fullmatch(item):
            _reject("NONCANONICAL_VALUE", f"{label} contains invalid field name {item!r}")
        if item in seen:
            _reject("AMBIGUOUS_ID", f"{label} contains duplicate field {item!r}")
        seen.add(item)
        names.append(item)
    if len(names) > MAX_FIELD_NAMES:
        _reject("NONCANONICAL_VALUE", f"{label} exceeds max fields {MAX_FIELD_NAMES}")
    ordered = tuple(sorted(names))
    if ordered != tuple(names):
        _reject("NONCANONICAL_VALUE", f"{label} must be lexicographically sorted")
    return ordered


def _freeze_json_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    def visit(item: Any, path: str) -> Any:
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):  # NaN/Inf
                _reject("NONCANONICAL_VALUE", f"non-finite float at {path}")
            return item
        if isinstance(item, str):
            if "\x00" in item:
                _reject("NONCANONICAL_VALUE", f"NUL in string at {path}")
            if len(item) > MAX_PROVENANCE_STRING:
                _reject("NONCANONICAL_VALUE", f"string too long at {path}")
            return item
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return tuple(visit(child, f"{path}[{i}]") for i, child in enumerate(item))
        if isinstance(item, Mapping):
            if len(item) > MAX_PROVENANCE_KEYS:
                _reject("NONCANONICAL_VALUE", f"too many keys at {path}")
            out: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str) or not key or key.strip() != key:
                    _reject("NONCANONICAL_VALUE", f"invalid key at {path}: {key!r}")
                out[key] = visit(child, f"{path}.{key}" if path else key)
            return MappingProxyType(out)
        _reject(
            "NONCANONICAL_VALUE",
            f"disallowed type {type(item).__name__} at {path or label}",
        )

    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        _reject("NONCANONICAL_VALUE", f"{label} must be a mapping")
    return visit(value, label)  # type: ignore[return-value]


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw_json(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(v) for v in value]
    return value


def _sorted_by_id(
    items: Sequence[Any],
    *,
    id_attr: str,
    label: str,
    maximum: int,
) -> tuple[Any, ...]:
    if isinstance(items, (str, bytes, bytearray)) or not isinstance(items, Sequence):
        _reject("NONCANONICAL_VALUE", f"{label} must be a sequence")
    seq = tuple(items)
    if len(seq) > maximum:
        _reject("NONCANONICAL_VALUE", f"{label} exceeds bound {maximum}")
    ids = [getattr(item, id_attr) for item in seq]
    _unique_ids(ids, label=label)
    ordered = tuple(sorted(seq, key=lambda item: getattr(item, id_attr)))
    if tuple(getattr(item, id_attr) for item in ordered) != tuple(ids):
        _reject("NONCANONICAL_VALUE", f"{label} must be sorted by {id_attr}")
    return ordered


# ---------------------------------------------------------------------------
# Rendezvous / routing primitives
# ---------------------------------------------------------------------------


def normalize_routing_key(entity_id: str, *, normalization: str = "utf-8") -> bytes:
    """Normalize an entity id to routing key bytes."""
    text = _require_str("entity_id", entity_id, code="AMBIGUOUS_ID")
    if normalization == "identity":
        return text.encode("utf-8", errors="strict")
    if normalization == "utf-8":
        return text.encode("utf-8", errors="strict")
    if normalization == "utf-8-nfc":
        import unicodedata

        return unicodedata.normalize("NFC", text).encode("utf-8", errors="strict")
    _reject("NONCANONICAL_VALUE", f"unknown key_normalization: {normalization!r}")
    raise AssertionError("unreachable")  # pragma: no cover


def hash_modulo_index(key: bytes, *, modulus: int) -> int:
    """v1-compatible deterministic index: sha256(key) mod N over first 8 bytes."""
    if modulus <= 0:
        raise ValueError("modulus must be > 0")
    digest = hashlib.sha256(key).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return value % modulus


def stable_shard_index(entity_id: str, *, num_shards: int) -> int:
    """v1 hash-modulo routing over a UTF-8 entity id (matches sharded_car.routing)."""
    return hash_modulo_index(
        entity_id.encode("utf-8", errors="strict"),
        modulus=num_shards,
    )


def rendezvous_score(key: bytes, node_id: str, *, seed: str = "") -> int:
    """Highest-random-weight score for (key, node) under sha256.

    Larger scores win. Domain-separated with optional seed so different
    graphs cannot collide on routing tables.
    """
    node = _require_id("node_id", node_id)
    seed_b = seed.encode("utf-8") if seed else b""
    material = b"|".join((b"kg-rendezvous-v1", seed_b, key, node.encode("utf-8")))
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest, "big", signed=False)


def rendezvous_pick(key: bytes, node_ids: Sequence[str], *, seed: str = "") -> str:
    """Pick the node with the highest rendezvous score (ties broken by node id)."""
    if not node_ids:
        raise ValueError("node_ids must be non-empty")
    best_id: Optional[str] = None
    best_score = -1
    for node_id in node_ids:
        score = rendezvous_score(key, node_id, seed=seed)
        if best_id is None or score > best_score or (score == best_score and node_id < best_id):
            best_id = node_id
            best_score = score
    assert best_id is not None
    return best_id


def _virtual_index_impl(key: bytes, *, virtual_shard_count: int, seed: str) -> int:
    if seed:
        material = b"kg-virtual|" + seed.encode("utf-8") + b"|" + key
        digest = hashlib.sha256(material).digest()
        return hash_modulo_index(digest, modulus=virtual_shard_count)
    return hash_modulo_index(key, modulus=virtual_shard_count)


def virtual_shard_index(
    entity_id: str,
    *,
    virtual_shard_count: int,
    normalization: str = "utf-8",
    seed: str = "",
) -> int:
    """Map an entity id to a stable virtual shard index in ``[0, V)``."""
    if virtual_shard_count <= 0:
        raise ValueError("virtual_shard_count must be > 0")
    key = normalize_routing_key(entity_id, normalization=normalization)
    return _virtual_index_impl(key, virtual_shard_count=virtual_shard_count, seed=seed)


def virtual_shard_id_for_index(index: int) -> str:
    return f"vs-{index:08d}"


def physical_shard_for_virtual(
    virtual_index: int,
    physical_shard_ids: Sequence[str],
    *,
    seed: str = "",
    algorithm: str = ROUTING_RENDEZVOUS_HRW,
) -> str:
    """Map a virtual shard index onto a physical shard id."""
    if not physical_shard_ids:
        raise ValueError("physical_shard_ids must be non-empty")
    ordered = tuple(sorted(physical_shard_ids))
    if algorithm == ROUTING_HASH_MODULO:
        return ordered[virtual_index % len(ordered)]
    if algorithm == ROUTING_RENDEZVOUS_HRW:
        key = virtual_index.to_bytes(8, "big", signed=False)
        return rendezvous_pick(key, ordered, seed=seed)
    raise ValueError(f"unknown routing algorithm: {algorithm!r}")


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BloomFilterDescriptor:
    """Bounded inline bloom filter descriptor (bits may be CID-backed instead)."""

    num_bits: int
    num_hashes: int
    bits_hex: Optional[str] = None
    checksum: Optional[ContentChecksum] = None
    cid: Optional[str] = None

    def __post_init__(self) -> None:
        num_bits = _require_positive_int(
            "BloomFilterDescriptor.num_bits", self.num_bits, maximum=MAX_BLOOM_BITS
        )
        num_hashes = _require_positive_int(
            "BloomFilterDescriptor.num_hashes", self.num_hashes, maximum=MAX_BLOOM_HASHES
        )
        bits_hex = self.bits_hex
        if bits_hex is not None:
            bits_hex = _require_str("BloomFilterDescriptor.bits_hex", bits_hex)
            if not re.fullmatch(r"^[0-9a-f]*$", bits_hex) or len(bits_hex) % 2 != 0:
                _reject("NONCANONICAL_VALUE", "bits_hex must be even-length lowercase hex")
            expected_bytes = (num_bits + 7) // 8
            if len(bits_hex) // 2 != expected_bytes:
                _reject(
                    "INVALID_COUNT",
                    f"bits_hex length {len(bits_hex) // 2} != expected {expected_bytes} bytes",
                )
        checksum = self.checksum
        if checksum is not None and not isinstance(checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "BloomFilterDescriptor.checksum must be ContentChecksum")
        cid = _optional_cid("BloomFilterDescriptor.cid", self.cid)
        if checksum is not None:
            _check_checksum_cid_pair(
                label="bloom",
                checksum_hex=checksum.hex_digest,
                cid=cid,
            )
        if bits_hex is None and checksum is None and cid is None:
            _reject(
                "AMBIGUOUS_ID",
                "bloom filter requires bits_hex and/or checksum/cid payload",
            )
        object.__setattr__(self, "num_bits", num_bits)
        object.__setattr__(self, "num_hashes", num_hashes)
        object.__setattr__(self, "bits_hex", bits_hex)
        object.__setattr__(self, "checksum", checksum)
        object.__setattr__(self, "cid", cid)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "num_bits": self.num_bits,
            "num_hashes": self.num_hashes,
            "bits_hex": self.bits_hex,
            "checksum": self.checksum.to_dict() if self.checksum is not None else None,
            "cid": self.cid,
        }
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BloomFilterDescriptor":
        # Accept v1 bloom shape {num_bits, num_hashes, bits_hex} and extended shape.
        if not isinstance(data, Mapping):
            _reject("UNKNOWN_REQUIRED_FIELD", "BloomFilterDescriptor must be a mapping")
        required = frozenset({"num_bits", "num_hashes"})
        optional = frozenset({"bits_hex", "checksum", "cid"})
        # Tolerate unknown? No — closed set, but allow pure v1 keys.
        keys = frozenset(data.keys())
        if not required <= keys:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"BloomFilterDescriptor missing: {sorted(required - keys)}",
            )
        unknown = keys - required - optional
        if unknown:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"BloomFilterDescriptor unknown fields: {sorted(unknown)}",
            )
        checksum_raw = data.get("checksum")
        checksum: Optional[ContentChecksum] = None
        if checksum_raw is not None:
            if not isinstance(checksum_raw, Mapping):
                _reject("NONCANONICAL_VALUE", "BloomFilterDescriptor.checksum must be object")
            checksum = ContentChecksum.from_dict(checksum_raw)
        return cls(
            num_bits=data["num_bits"],
            num_hashes=data["num_hashes"],
            bits_hex=data.get("bits_hex"),
            checksum=checksum,
            cid=data.get("cid"),
        )

    @classmethod
    def from_v1_bloom_dict(cls, data: Mapping[str, Any]) -> "BloomFilterDescriptor":
        """Accept the exact dict shape emitted by sharded_car BloomFilter.to_dict()."""
        return cls.from_dict(
            {
                "num_bits": data["num_bits"],
                "num_hashes": data["num_hashes"],
                "bits_hex": data["bits_hex"],
            }
        )


@dataclass(frozen=True, slots=True)
class IndexBucketDescriptor:
    """Bounded index/bloom bucket stored beside a physical CAR shard."""

    bucket_id: str
    kind: str
    codec: str
    checksum: ContentChecksum
    size_bytes: int
    fields: tuple[str, ...] = ()
    path: Optional[str] = None
    cid: Optional[str] = None
    bloom: Optional[BloomFilterDescriptor] = None
    schema_version: Optional[str] = None

    def __post_init__(self) -> None:
        bid = _require_id("IndexBucketDescriptor.bucket_id", self.bucket_id)
        kind = _require_str("IndexBucketDescriptor.kind", self.kind)
        if kind not in INDEX_BUCKET_KINDS:
            _reject("NONCANONICAL_VALUE", f"unknown index bucket kind: {kind!r}")
        codec = _require_codec("IndexBucketDescriptor.codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "IndexBucketDescriptor.checksum must be ContentChecksum")
        size = _require_nonneg_int(
            "IndexBucketDescriptor.size_bytes", self.size_bytes, maximum=MAX_BYTES
        )
        fields = _field_names(self.fields, label="IndexBucketDescriptor.fields")
        path = _optional_path("IndexBucketDescriptor.path", self.path)
        cid = _optional_cid("IndexBucketDescriptor.cid", self.cid)
        if path is None and cid is None and self.bloom is None:
            _reject(
                "AMBIGUOUS_ID",
                f"index bucket {bid!r} requires path, cid, and/or inline bloom",
            )
        bloom = self.bloom
        if bloom is not None and not isinstance(bloom, BloomFilterDescriptor):
            _reject("NONCANONICAL_VALUE", "IndexBucketDescriptor.bloom must be BloomFilterDescriptor")
        schema_version = (
            None
            if self.schema_version is None
            else _require_schema_ref("IndexBucketDescriptor.schema_version", self.schema_version)
        )
        _check_checksum_cid_pair(
            label=f"index bucket {bid}",
            checksum_hex=self.checksum.hex_digest,
            cid=cid,
        )
        object.__setattr__(self, "bucket_id", bid)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "bloom", bloom)
        object.__setattr__(self, "schema_version", schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "kind": self.kind,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "size_bytes": self.size_bytes,
            "fields": list(self.fields),
            "path": self.path,
            "cid": self.cid,
            "bloom": self.bloom.to_dict() if self.bloom is not None else None,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IndexBucketDescriptor":
        _require_known_keys(
            data,
            required=frozenset({"bucket_id", "kind", "codec", "checksum", "size_bytes"}),
            optional=frozenset({"fields", "path", "cid", "bloom", "schema_version"}),
            label="IndexBucketDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "IndexBucketDescriptor.checksum must be an object")
        bloom_raw = data.get("bloom")
        bloom: Optional[BloomFilterDescriptor] = None
        if bloom_raw is not None:
            if not isinstance(bloom_raw, Mapping):
                _reject("NONCANONICAL_VALUE", "IndexBucketDescriptor.bloom must be an object")
            bloom = BloomFilterDescriptor.from_dict(bloom_raw)
        return cls(
            bucket_id=data["bucket_id"],
            kind=data["kind"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            size_bytes=data["size_bytes"],
            fields=tuple(data.get("fields") or ()),
            path=data.get("path"),
            cid=data.get("cid"),
            bloom=bloom,
            schema_version=data.get("schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ShardStatistics:
    """Per-shard or whole-graph aggregate statistics."""

    entity_count: int = 0
    relationship_count: int = 0
    approx_bytes: int = 0
    cross_shard_out_edges: int = 0
    cross_shard_in_edges: int = 0
    virtual_shard_count: int = 0
    physical_shard_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entity_count",
            _require_nonneg_int("entity_count", self.entity_count, maximum=MAX_COUNT),
        )
        object.__setattr__(
            self,
            "relationship_count",
            _require_nonneg_int(
                "relationship_count", self.relationship_count, maximum=MAX_COUNT
            ),
        )
        object.__setattr__(
            self,
            "approx_bytes",
            _require_nonneg_int("approx_bytes", self.approx_bytes, maximum=MAX_BYTES),
        )
        object.__setattr__(
            self,
            "cross_shard_out_edges",
            _require_nonneg_int(
                "cross_shard_out_edges", self.cross_shard_out_edges, maximum=MAX_COUNT
            ),
        )
        object.__setattr__(
            self,
            "cross_shard_in_edges",
            _require_nonneg_int(
                "cross_shard_in_edges", self.cross_shard_in_edges, maximum=MAX_COUNT
            ),
        )
        object.__setattr__(
            self,
            "virtual_shard_count",
            _require_nonneg_int(
                "virtual_shard_count", self.virtual_shard_count, maximum=MAX_VIRTUAL_SHARDS
            ),
        )
        object.__setattr__(
            self,
            "physical_shard_count",
            _require_nonneg_int(
                "physical_shard_count",
                self.physical_shard_count,
                maximum=MAX_PHYSICAL_SHARDS,
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "approx_bytes": self.approx_bytes,
            "cross_shard_out_edges": self.cross_shard_out_edges,
            "cross_shard_in_edges": self.cross_shard_in_edges,
            "virtual_shard_count": self.virtual_shard_count,
            "physical_shard_count": self.physical_shard_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShardStatistics":
        if not isinstance(data, Mapping):
            _reject("UNKNOWN_REQUIRED_FIELD", "ShardStatistics must be a mapping")
        allowed = frozenset(
            {
                "entity_count",
                "relationship_count",
                "approx_bytes",
                "cross_shard_out_edges",
                "cross_shard_in_edges",
                "virtual_shard_count",
                "physical_shard_count",
            }
        )
        unknown = frozenset(data.keys()) - allowed
        if unknown:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"ShardStatistics has unknown field(s): {sorted(unknown)}",
            )
        return cls(
            entity_count=int(data.get("entity_count") or 0),
            relationship_count=int(data.get("relationship_count") or 0),
            approx_bytes=int(data.get("approx_bytes") or 0),
            cross_shard_out_edges=int(data.get("cross_shard_out_edges") or 0),
            cross_shard_in_edges=int(data.get("cross_shard_in_edges") or 0),
            virtual_shard_count=int(data.get("virtual_shard_count") or 0),
            physical_shard_count=int(data.get("physical_shard_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class CrossShardAdjacencyDescriptor:
    """Explicit descriptor for edges that cross physical shard boundaries."""

    adjacency_id: str
    source_physical_shard_id: str
    target_physical_shard_id: str
    direction: str
    edge_count: int
    codec: str
    checksum: ContentChecksum
    path: Optional[str] = None
    cid: Optional[str] = None
    source_virtual_shard_id: Optional[str] = None
    target_virtual_shard_id: Optional[str] = None

    def __post_init__(self) -> None:
        aid = _require_id("adjacency_id", self.adjacency_id)
        src = _require_id("source_physical_shard_id", self.source_physical_shard_id)
        dst = _require_id("target_physical_shard_id", self.target_physical_shard_id)
        direction = _require_str("direction", self.direction)
        if direction not in ADJACENCY_DIRECTIONS:
            _reject("NONCANONICAL_VALUE", f"unknown adjacency direction: {direction!r}")
        if src == dst:
            _reject(
                "AMBIGUOUS_ID",
                f"cross-shard adjacency {aid!r} must span distinct physical shards",
            )
        edges = _require_nonneg_int("edge_count", self.edge_count, maximum=MAX_COUNT)
        codec = _require_codec("codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "checksum must be ContentChecksum")
        path = _optional_path("path", self.path)
        cid = _optional_cid("cid", self.cid)
        if path is None and cid is None:
            _reject(
                "AMBIGUOUS_ID",
                f"cross-shard adjacency {aid!r} requires path and/or cid",
            )
        src_vs = (
            None
            if self.source_virtual_shard_id is None
            else _require_id("source_virtual_shard_id", self.source_virtual_shard_id)
        )
        dst_vs = (
            None
            if self.target_virtual_shard_id is None
            else _require_id("target_virtual_shard_id", self.target_virtual_shard_id)
        )
        _check_checksum_cid_pair(
            label=f"cross-shard adjacency {aid}",
            checksum_hex=self.checksum.hex_digest,
            cid=cid,
        )
        object.__setattr__(self, "adjacency_id", aid)
        object.__setattr__(self, "source_physical_shard_id", src)
        object.__setattr__(self, "target_physical_shard_id", dst)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "edge_count", edges)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "source_virtual_shard_id", src_vs)
        object.__setattr__(self, "target_virtual_shard_id", dst_vs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency_id": self.adjacency_id,
            "source_physical_shard_id": self.source_physical_shard_id,
            "target_physical_shard_id": self.target_physical_shard_id,
            "direction": self.direction,
            "edge_count": self.edge_count,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "path": self.path,
            "cid": self.cid,
            "source_virtual_shard_id": self.source_virtual_shard_id,
            "target_virtual_shard_id": self.target_virtual_shard_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CrossShardAdjacencyDescriptor":
        _require_known_keys(
            data,
            required=frozenset(
                {
                    "adjacency_id",
                    "source_physical_shard_id",
                    "target_physical_shard_id",
                    "direction",
                    "edge_count",
                    "codec",
                    "checksum",
                }
            ),
            optional=frozenset(
                {
                    "path",
                    "cid",
                    "source_virtual_shard_id",
                    "target_virtual_shard_id",
                }
            ),
            label="CrossShardAdjacencyDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "checksum must be an object")
        return cls(
            adjacency_id=data["adjacency_id"],
            source_physical_shard_id=data["source_physical_shard_id"],
            target_physical_shard_id=data["target_physical_shard_id"],
            direction=data["direction"],
            edge_count=data["edge_count"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            path=data.get("path"),
            cid=data.get("cid"),
            source_virtual_shard_id=data.get("source_virtual_shard_id"),
            target_virtual_shard_id=data.get("target_virtual_shard_id"),
        )


@dataclass(frozen=True, slots=True)
class VirtualShardDescriptor:
    """Stable logical shard; many virtual shards map onto fewer physical shards."""

    virtual_shard_id: str
    index: int
    physical_shard_id: str
    statistics: Optional[ShardStatistics] = None

    def __post_init__(self) -> None:
        vid = _require_id("virtual_shard_id", self.virtual_shard_id)
        index = _require_nonneg_int("index", self.index, maximum=MAX_VIRTUAL_SHARDS - 1)
        pid = _require_id("physical_shard_id", self.physical_shard_id)
        stats = self.statistics
        if stats is not None and not isinstance(stats, ShardStatistics):
            _reject("NONCANONICAL_VALUE", "statistics must be ShardStatistics")
        object.__setattr__(self, "virtual_shard_id", vid)
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "physical_shard_id", pid)
        object.__setattr__(self, "statistics", stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "virtual_shard_id": self.virtual_shard_id,
            "index": self.index,
            "physical_shard_id": self.physical_shard_id,
            "statistics": self.statistics.to_dict() if self.statistics is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VirtualShardDescriptor":
        _require_known_keys(
            data,
            required=frozenset({"virtual_shard_id", "index", "physical_shard_id"}),
            optional=frozenset({"statistics"}),
            label="VirtualShardDescriptor",
        )
        stats_raw = data.get("statistics")
        stats: Optional[ShardStatistics] = None
        if stats_raw is not None:
            if not isinstance(stats_raw, Mapping):
                _reject("NONCANONICAL_VALUE", "statistics must be an object")
            stats = ShardStatistics.from_dict(stats_raw)
        return cls(
            virtual_shard_id=data["virtual_shard_id"],
            index=data["index"],
            physical_shard_id=data["physical_shard_id"],
            statistics=stats,
        )


@dataclass(frozen=True, slots=True)
class PhysicalShardDescriptor:
    """Physical CAR (or equivalent) object holding one or more virtual shards."""

    physical_shard_id: str
    codec: str
    checksum: ContentChecksum
    size_bytes: int
    statistics: ShardStatistics
    path: Optional[str] = None
    car_cid: Optional[str] = None
    virtual_shard_ids: tuple[str, ...] = ()
    index_buckets: tuple[IndexBucketDescriptor, ...] = ()
    schema_version: Optional[str] = None
    index_version: Optional[str] = None
    # v1 compatibility optional index CIDs / blooms
    headers_cid: Optional[str] = None
    type_index_cid: Optional[str] = None
    neighbors_index_cid: Optional[str] = None
    entity_type_bloom: Optional[BloomFilterDescriptor] = None
    relationship_type_bloom: Optional[BloomFilterDescriptor] = None

    def __post_init__(self) -> None:
        sid = _require_id("physical_shard_id", self.physical_shard_id)
        codec = _require_codec("codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "checksum must be ContentChecksum")
        size = _require_nonneg_int("size_bytes", self.size_bytes, maximum=MAX_BYTES)
        if not isinstance(self.statistics, ShardStatistics):
            _reject("NONCANONICAL_VALUE", "statistics must be ShardStatistics")
        path = _optional_path("path", self.path)
        car_cid = _optional_cid("car_cid", self.car_cid)
        if path is None and car_cid is None:
            _reject(
                "AMBIGUOUS_ID",
                f"physical shard {sid!r} requires path and/or car_cid",
            )
        if isinstance(self.virtual_shard_ids, (str, bytes, bytearray)) or not isinstance(
            self.virtual_shard_ids, Sequence
        ):
            _reject("NONCANONICAL_VALUE", "virtual_shard_ids must be a sequence")
        vids = tuple(self.virtual_shard_ids)
        for vid in vids:
            _require_id("virtual_shard_ids[]", vid)
        _unique_ids(vids, label="virtual_shard_ids")
        ordered_vids = tuple(sorted(vids))
        if ordered_vids != vids:
            _reject("NONCANONICAL_VALUE", "virtual_shard_ids must be lexicographically sorted")

        buckets = _sorted_by_id(
            self.index_buckets,
            id_attr="bucket_id",
            label="index_buckets",
            maximum=MAX_INDEX_BUCKETS_PER_SHARD,
        )
        schema_version = (
            None
            if self.schema_version is None
            else _require_schema_ref("schema_version", self.schema_version)
        )
        index_version = (
            None
            if self.index_version is None
            else _require_schema_ref("index_version", self.index_version)
        )
        headers_cid = _optional_cid("headers_cid", self.headers_cid)
        type_index_cid = _optional_cid("type_index_cid", self.type_index_cid)
        neighbors_index_cid = _optional_cid("neighbors_index_cid", self.neighbors_index_cid)
        etb = self.entity_type_bloom
        if etb is not None and not isinstance(etb, BloomFilterDescriptor):
            _reject("NONCANONICAL_VALUE", "entity_type_bloom must be BloomFilterDescriptor")
        rtb = self.relationship_type_bloom
        if rtb is not None and not isinstance(rtb, BloomFilterDescriptor):
            _reject(
                "NONCANONICAL_VALUE",
                "relationship_type_bloom must be BloomFilterDescriptor",
            )
        # Note: car_cid is the addressing CID of the CAR object on IPFS and may
        # use a different multicodec than ContentChecksum.as_cid() (raw/sha2-256).
        # Integrity of CAR bytes is verified at fetch time against checksum when
        # the publisher records checksum over the CAR payload; we do not force
        # car_cid == checksum.as_cid() here so v1 multiformat CIDs remain valid.
        object.__setattr__(self, "physical_shard_id", sid)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "car_cid", car_cid)
        object.__setattr__(self, "virtual_shard_ids", ordered_vids)
        object.__setattr__(self, "index_buckets", buckets)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "index_version", index_version)
        object.__setattr__(self, "headers_cid", headers_cid)
        object.__setattr__(self, "type_index_cid", type_index_cid)
        object.__setattr__(self, "neighbors_index_cid", neighbors_index_cid)
        object.__setattr__(self, "entity_type_bloom", etb)
        object.__setattr__(self, "relationship_type_bloom", rtb)

    def to_dict(self) -> dict[str, Any]:
        return {
            "physical_shard_id": self.physical_shard_id,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "size_bytes": self.size_bytes,
            "statistics": self.statistics.to_dict(),
            "path": self.path,
            "car_cid": self.car_cid,
            "virtual_shard_ids": list(self.virtual_shard_ids),
            "index_buckets": [b.to_dict() for b in self.index_buckets],
            "schema_version": self.schema_version,
            "index_version": self.index_version,
            "headers_cid": self.headers_cid,
            "type_index_cid": self.type_index_cid,
            "neighbors_index_cid": self.neighbors_index_cid,
            "entity_type_bloom": (
                self.entity_type_bloom.to_dict()
                if self.entity_type_bloom is not None
                else None
            ),
            "relationship_type_bloom": (
                self.relationship_type_bloom.to_dict()
                if self.relationship_type_bloom is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhysicalShardDescriptor":
        _require_known_keys(
            data,
            required=frozenset(
                {
                    "physical_shard_id",
                    "codec",
                    "checksum",
                    "size_bytes",
                    "statistics",
                }
            ),
            optional=frozenset(
                {
                    "path",
                    "car_cid",
                    "virtual_shard_ids",
                    "index_buckets",
                    "schema_version",
                    "index_version",
                    "headers_cid",
                    "type_index_cid",
                    "neighbors_index_cid",
                    "entity_type_bloom",
                    "relationship_type_bloom",
                }
            ),
            label="PhysicalShardDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "checksum must be an object")
        stats_raw = data["statistics"]
        if not isinstance(stats_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "statistics must be an object")
        buckets_raw = data.get("index_buckets") or ()
        if isinstance(buckets_raw, (str, bytes, bytearray)) or not isinstance(
            buckets_raw, Sequence
        ):
            _reject("NONCANONICAL_VALUE", "index_buckets must be an array")
        etb_raw = data.get("entity_type_bloom")
        etb = BloomFilterDescriptor.from_dict(etb_raw) if isinstance(etb_raw, Mapping) else None
        rtb_raw = data.get("relationship_type_bloom")
        rtb = BloomFilterDescriptor.from_dict(rtb_raw) if isinstance(rtb_raw, Mapping) else None
        return cls(
            physical_shard_id=data["physical_shard_id"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            size_bytes=data["size_bytes"],
            statistics=ShardStatistics.from_dict(stats_raw),
            path=data.get("path"),
            car_cid=data.get("car_cid"),
            virtual_shard_ids=tuple(data.get("virtual_shard_ids") or ()),
            index_buckets=tuple(
                IndexBucketDescriptor.from_dict(b) for b in buckets_raw  # type: ignore[arg-type]
            ),
            schema_version=data.get("schema_version"),
            index_version=data.get("index_version"),
            headers_cid=data.get("headers_cid"),
            type_index_cid=data.get("type_index_cid"),
            neighbors_index_cid=data.get("neighbors_index_cid"),
            entity_type_bloom=etb,
            relationship_type_bloom=rtb,
        )


@dataclass(frozen=True, slots=True)
class RendezvousRoutingDescriptor:
    """Routing table configuration for virtual → physical placement."""

    algorithm: str
    hash_function: str
    virtual_shard_count: int
    seed: str = ""
    key_normalization: str = "utf-8"

    def __post_init__(self) -> None:
        algorithm = _require_str("algorithm", self.algorithm)
        if algorithm not in ROUTING_ALGORITHMS:
            _reject("NONCANONICAL_VALUE", f"unknown routing algorithm: {algorithm!r}")
        hash_function = _require_str("hash_function", self.hash_function)
        if hash_function not in HASH_FUNCTIONS:
            _reject("NONCANONICAL_VALUE", f"unknown hash_function: {hash_function!r}")
        vcount = _require_positive_int(
            "virtual_shard_count",
            self.virtual_shard_count,
            maximum=MAX_VIRTUAL_SHARDS,
        )
        seed = self.seed
        if not isinstance(seed, str):
            _reject("NONCANONICAL_VALUE", "seed must be a string")
        if "\x00" in seed or len(seed) > 256:
            _reject("NONCANONICAL_VALUE", "seed must be <= 256 chars without NUL")
        kn = _require_str("key_normalization", self.key_normalization)
        if kn not in KEY_NORMALIZATIONS:
            _reject("NONCANONICAL_VALUE", f"unknown key_normalization: {kn!r}")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "hash_function", hash_function)
        object.__setattr__(self, "virtual_shard_count", vcount)
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "key_normalization", kn)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "hash_function": self.hash_function,
            "virtual_shard_count": self.virtual_shard_count,
            "seed": self.seed,
            "key_normalization": self.key_normalization,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RendezvousRoutingDescriptor":
        _require_known_keys(
            data,
            required=frozenset({"algorithm", "hash_function", "virtual_shard_count"}),
            optional=frozenset({"seed", "key_normalization"}),
            label="RendezvousRoutingDescriptor",
        )
        return cls(
            algorithm=data["algorithm"],
            hash_function=data["hash_function"],
            virtual_shard_count=data["virtual_shard_count"],
            seed=str(data.get("seed") or ""),
            key_normalization=str(data.get("key_normalization") or "utf-8"),
        )


# ---------------------------------------------------------------------------
# Top-level manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShardedGraphManifest:
    """Versioned sharded graph manifest (v1-compatible reader, v2 native writer)."""

    version: str
    routing: RendezvousRoutingDescriptor
    schema_version: str
    index_version: str
    codec: str
    physical_shards: tuple[PhysicalShardDescriptor, ...]
    virtual_shards: tuple[VirtualShardDescriptor, ...]
    cross_shard_adjacency: tuple[CrossShardAdjacencyDescriptor, ...]
    statistics: ShardStatistics
    provenance: ProvenanceDescriptor
    checksum: ContentChecksum
    root_cid: Optional[str] = None
    shard_size_limit_bytes: int = DEFAULT_SHARD_SIZE_LIMIT_BYTES
    target_shard_bytes: int = DEFAULT_TARGET_SHARD_BYTES
    entity_type_bloom: Optional[BloomFilterDescriptor] = None
    relationship_type_bloom: Optional[BloomFilterDescriptor] = None
    # When True, identity checksum enforcement is skipped (v1 imports only).
    _skip_identity_checksum: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        version = _require_str("version", self.version)
        if version not in SUPPORTED_VERSIONS:
            _reject("NONCANONICAL_VALUE", f"unsupported shard manifest version: {version!r}")
        if not isinstance(self.routing, RendezvousRoutingDescriptor):
            _reject("NONCANONICAL_VALUE", "routing must be RendezvousRoutingDescriptor")
        schema_version = _require_schema_ref("schema_version", self.schema_version)
        index_version = _require_schema_ref("index_version", self.index_version)
        codec = _require_codec("codec", self.codec)
        if not isinstance(self.statistics, ShardStatistics):
            _reject("NONCANONICAL_VALUE", "statistics must be ShardStatistics")
        if not isinstance(self.provenance, ProvenanceDescriptor):
            _reject("NONCANONICAL_VALUE", "provenance must be ProvenanceDescriptor")
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "checksum must be ContentChecksum")

        physical = _sorted_by_id(
            self.physical_shards,
            id_attr="physical_shard_id",
            label="physical_shards",
            maximum=MAX_PHYSICAL_SHARDS,
        )
        virtual = _sorted_by_id(
            self.virtual_shards,
            id_attr="virtual_shard_id",
            label="virtual_shards",
            maximum=MAX_VIRTUAL_SHARDS,
        )
        adjacency = _sorted_by_id(
            self.cross_shard_adjacency,
            id_attr="adjacency_id",
            label="cross_shard_adjacency",
            maximum=MAX_CROSS_SHARD_ADJACENCY,
        )

        physical_ids = {p.physical_shard_id for p in physical}
        virtual_ids = {v.virtual_shard_id for v in virtual}
        virtual_indexes = [v.index for v in virtual]
        _unique_ids((str(i) for i in virtual_indexes), label="virtual_shards.index")

        if self.routing.virtual_shard_count < len(virtual):
            _reject(
                "INVALID_COUNT",
                "routing.virtual_shard_count must be >= number of virtual_shards",
            )
        for v in virtual:
            if v.index >= self.routing.virtual_shard_count:
                _reject(
                    "INVALID_COUNT",
                    f"virtual shard index {v.index} >= virtual_shard_count "
                    f"{self.routing.virtual_shard_count}",
                )
            if v.physical_shard_id not in physical_ids:
                _reject(
                    "AMBIGUOUS_ID",
                    f"virtual shard {v.virtual_shard_id!r} references unknown "
                    f"physical shard {v.physical_shard_id!r}",
                )

        for p in physical:
            missing = set(p.virtual_shard_ids) - virtual_ids
            if missing and virtual_ids:
                _reject(
                    "AMBIGUOUS_ID",
                    f"physical shard {p.physical_shard_id!r} references unknown "
                    f"virtual shards {sorted(missing)}",
                )

        for edge in adjacency:
            if edge.source_physical_shard_id not in physical_ids:
                _reject(
                    "AMBIGUOUS_ID",
                    f"adjacency {edge.adjacency_id!r} unknown source "
                    f"{edge.source_physical_shard_id!r}",
                )
            if edge.target_physical_shard_id not in physical_ids:
                _reject(
                    "AMBIGUOUS_ID",
                    f"adjacency {edge.adjacency_id!r} unknown target "
                    f"{edge.target_physical_shard_id!r}",
                )

        # Global statistics consistency (when declared non-zero).
        if self.statistics.physical_shard_count not in (0, len(physical)):
            _reject(
                "INVALID_COUNT",
                f"statistics.physical_shard_count {self.statistics.physical_shard_count} "
                f"!= len(physical_shards) {len(physical)}",
            )
        if self.statistics.virtual_shard_count not in (0, len(virtual)):
            # Also allow matching routing.virtual_shard_count for sparse tables.
            if self.statistics.virtual_shard_count != self.routing.virtual_shard_count:
                _reject(
                    "INVALID_COUNT",
                    f"statistics.virtual_shard_count {self.statistics.virtual_shard_count} "
                    f"inconsistent with virtual_shards/routing",
                )

        limit = _require_positive_int(
            "shard_size_limit_bytes", self.shard_size_limit_bytes, maximum=MAX_BYTES
        )
        target = _require_positive_int(
            "target_shard_bytes", self.target_shard_bytes, maximum=MAX_BYTES
        )
        if target > limit:
            _reject(
                "INVALID_COUNT",
                f"target_shard_bytes {target} exceeds shard_size_limit_bytes {limit}",
            )

        etb = self.entity_type_bloom
        if etb is not None and not isinstance(etb, BloomFilterDescriptor):
            _reject("NONCANONICAL_VALUE", "entity_type_bloom must be BloomFilterDescriptor")
        rtb = self.relationship_type_bloom
        if rtb is not None and not isinstance(rtb, BloomFilterDescriptor):
            _reject(
                "NONCANONICAL_VALUE",
                "relationship_type_bloom must be BloomFilterDescriptor",
            )

        root_cid = _optional_cid("root_cid", self.root_cid)

        object.__setattr__(self, "version", version)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "index_version", index_version)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "physical_shards", physical)
        object.__setattr__(self, "virtual_shards", virtual)
        object.__setattr__(self, "cross_shard_adjacency", adjacency)
        object.__setattr__(self, "root_cid", root_cid)
        object.__setattr__(self, "shard_size_limit_bytes", limit)
        object.__setattr__(self, "target_shard_bytes", target)
        object.__setattr__(self, "entity_type_bloom", etb)
        object.__setattr__(self, "relationship_type_bloom", rtb)

        if not self._skip_identity_checksum:
            expected = ContentChecksum.of_bytes(self.identity_bytes())
            if self.checksum.hex_digest != expected.hex_digest:
                raise ShardManifestIntegrityError(
                    "CHECKSUM_CID_MISMATCH",
                    "manifest checksum does not match canonical identity payload "
                    f"(declared {self.checksum.hex_digest}, expected {expected.hex_digest})",
                )
            if root_cid is not None and root_cid != expected.as_cid():
                raise ShardManifestIntegrityError(
                    "CHECKSUM_CID_MISMATCH",
                    f"root_cid {root_cid!r} does not match identity payload CID "
                    f"{expected.as_cid()!r}",
                )

    # -- routing helpers ----------------------------------------------------

    def physical_shard_ids(self) -> tuple[str, ...]:
        return tuple(p.physical_shard_id for p in self.physical_shards)

    def physical_by_id(self) -> dict[str, PhysicalShardDescriptor]:
        return {p.physical_shard_id: p for p in self.physical_shards}

    def route_entity(self, entity_id: str) -> str:
        """Return the physical_shard_id that should own ``entity_id``."""
        pids = self.physical_shard_ids()
        if not pids:
            raise ValueError("manifest has no physical shards")
        if self.version == SHARD_MANIFEST_V1 or self.routing.algorithm == ROUTING_HASH_MODULO:
            if self.routing.virtual_shard_count == len(pids):
                # Classic v1: hash mod number of physical shards (sorted order).
                ordered = tuple(sorted(pids))
                idx = stable_shard_index(entity_id, num_shards=len(ordered))
                return ordered[idx]
            # Hash-modulo over virtual count then map via declared virtual table
            # or deterministic fold.
            v_idx = virtual_shard_index(
                entity_id,
                virtual_shard_count=self.routing.virtual_shard_count,
                normalization=self.routing.key_normalization,
                seed=self.routing.seed,
            )
            return self._resolve_virtual_index(v_idx)

        v_idx = virtual_shard_index(
            entity_id,
            virtual_shard_count=self.routing.virtual_shard_count,
            normalization=self.routing.key_normalization,
            seed=self.routing.seed,
        )
        return self._resolve_virtual_index(v_idx)

    def _resolve_virtual_index(self, v_idx: int) -> str:
        for vs in self.virtual_shards:
            if vs.index == v_idx:
                return vs.physical_shard_id
        # Sparse virtual table: rendezvous/hash fold onto physical set.
        return physical_shard_for_virtual(
            v_idx,
            self.physical_shard_ids(),
            seed=self.routing.seed,
            algorithm=self.routing.algorithm,
        )

    # -- serialization ------------------------------------------------------

    def identity_dict(self) -> dict[str, Any]:
        """Deterministic fields defining content identity (excludes checksum/CID)."""
        return {
            "version": self.version,
            "routing": self.routing.to_dict(),
            "schema_version": self.schema_version,
            "index_version": self.index_version,
            "codec": self.codec,
            "physical_shards": [p.to_dict() for p in self.physical_shards],
            "virtual_shards": [v.to_dict() for v in self.virtual_shards],
            "cross_shard_adjacency": [a.to_dict() for a in self.cross_shard_adjacency],
            "statistics": self.statistics.to_dict(),
            "provenance": self.provenance.to_dict(),
            "shard_size_limit_bytes": self.shard_size_limit_bytes,
            "target_shard_bytes": self.target_shard_bytes,
            "entity_type_bloom": (
                self.entity_type_bloom.to_dict()
                if self.entity_type_bloom is not None
                else None
            ),
            "relationship_type_bloom": (
                self.relationship_type_bloom.to_dict()
                if self.relationship_type_bloom is not None
                else None
            ),
        }

    def identity_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_dict()
        payload["checksum"] = self.checksum.to_dict()
        payload["root_cid"] = self.root_cid
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    def to_v1_dict(self) -> dict[str, Any]:
        """Project to search.graph_query.sharded_car v1 GraphShardManifest shape."""
        shards: list[dict[str, Any]] = []
        for p in self.physical_shards:
            shards.append(
                {
                    "shard_id": p.physical_shard_id,
                    "car_cid": p.car_cid or "",
                    "approx_bytes": p.statistics.approx_bytes or p.size_bytes,
                    "headers_cid": p.headers_cid,
                    "type_index_cid": p.type_index_cid,
                    "neighbors_index_cid": p.neighbors_index_cid,
                    "entity_type_bloom": (
                        {
                            "num_bits": p.entity_type_bloom.num_bits,
                            "num_hashes": p.entity_type_bloom.num_hashes,
                            "bits_hex": p.entity_type_bloom.bits_hex,
                        }
                        if p.entity_type_bloom is not None
                        and p.entity_type_bloom.bits_hex is not None
                        else None
                    ),
                    "relationship_type_bloom": (
                        {
                            "num_bits": p.relationship_type_bloom.num_bits,
                            "num_hashes": p.relationship_type_bloom.num_hashes,
                            "bits_hex": p.relationship_type_bloom.bits_hex,
                        }
                        if p.relationship_type_bloom is not None
                        and p.relationship_type_bloom.bits_hex is not None
                        else None
                    ),
                }
            )
        return {
            "version": "v1",
            "shard_size_limit_bytes": self.shard_size_limit_bytes,
            "target_shard_bytes": self.target_shard_bytes,
            "shards": shards,
            "entity_type_bloom": (
                {
                    "num_bits": self.entity_type_bloom.num_bits,
                    "num_hashes": self.entity_type_bloom.num_hashes,
                    "bits_hex": self.entity_type_bloom.bits_hex,
                }
                if self.entity_type_bloom is not None
                and self.entity_type_bloom.bits_hex is not None
                else None
            ),
            "relationship_type_bloom": (
                {
                    "num_bits": self.relationship_type_bloom.num_bits,
                    "num_hashes": self.relationship_type_bloom.num_hashes,
                    "bits_hex": self.relationship_type_bloom.bits_hex,
                }
                if self.relationship_type_bloom is not None
                and self.relationship_type_bloom.bits_hex is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShardedGraphManifest":
        if not isinstance(data, Mapping):
            _reject("UNKNOWN_REQUIRED_FIELD", "manifest must be a mapping")
        version = data.get("version") or data.get("manifest_version") or SHARD_MANIFEST_V1
        if version == SHARD_MANIFEST_V1 or (
            version not in SUPPORTED_VERSIONS and "shards" in data and "physical_shards" not in data
        ):
            return cls.from_v1_dict(data)
        if version != SHARD_MANIFEST_V2:
            _reject("NONCANONICAL_VALUE", f"unsupported version: {version!r}")
        return cls._from_v2_dict(data)

    @classmethod
    def _from_v2_dict(cls, data: Mapping[str, Any]) -> "ShardedGraphManifest":
        keys = frozenset(data.keys())
        missing = _V2_REQUIRED_KEYS - keys
        if missing:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"manifest missing required field(s): {sorted(missing)}",
            )
        unknown = keys - _V2_REQUIRED_KEYS - _V2_OPTIONAL_KEYS
        if unknown:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"manifest has unknown field(s): {sorted(unknown)}",
            )

        routing_raw = data["routing"]
        if not isinstance(routing_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "routing must be an object")
        stats_raw = data["statistics"]
        if not isinstance(stats_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "statistics must be an object")
        prov_raw = data["provenance"]
        if not isinstance(prov_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "provenance must be an object")
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "checksum must be an object")

        physical_raw = data["physical_shards"]
        virtual_raw = data["virtual_shards"]
        adj_raw = data["cross_shard_adjacency"]
        for label, raw in (
            ("physical_shards", physical_raw),
            ("virtual_shards", virtual_raw),
            ("cross_shard_adjacency", adj_raw),
        ):
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
                _reject("NONCANONICAL_VALUE", f"{label} must be an array")

        etb_raw = data.get("entity_type_bloom")
        etb = BloomFilterDescriptor.from_dict(etb_raw) if isinstance(etb_raw, Mapping) else None
        rtb_raw = data.get("relationship_type_bloom")
        rtb = BloomFilterDescriptor.from_dict(rtb_raw) if isinstance(rtb_raw, Mapping) else None

        return cls(
            version=SHARD_MANIFEST_V2,
            routing=RendezvousRoutingDescriptor.from_dict(routing_raw),
            schema_version=data["schema_version"],
            index_version=data["index_version"],
            codec=data["codec"],
            physical_shards=tuple(
                PhysicalShardDescriptor.from_dict(p) for p in physical_raw  # type: ignore[arg-type]
            ),
            virtual_shards=tuple(
                VirtualShardDescriptor.from_dict(v) for v in virtual_raw  # type: ignore[arg-type]
            ),
            cross_shard_adjacency=tuple(
                CrossShardAdjacencyDescriptor.from_dict(a) for a in adj_raw  # type: ignore[arg-type]
            ),
            statistics=ShardStatistics.from_dict(stats_raw),
            provenance=ProvenanceDescriptor.from_dict(prov_raw),
            checksum=ContentChecksum.from_dict(checksum_raw),
            root_cid=data["root_cid"],
            shard_size_limit_bytes=int(data["shard_size_limit_bytes"]),
            target_shard_bytes=int(data["target_shard_bytes"]),
            entity_type_bloom=etb,
            relationship_type_bloom=rtb,
        )

    @classmethod
    def from_v1_dict(cls, data: Mapping[str, Any]) -> "ShardedGraphManifest":
        """Read search.graph_query.sharded_car GraphShardManifest JSON."""
        if not isinstance(data, Mapping):
            _reject("UNKNOWN_REQUIRED_FIELD", "v1 manifest must be a mapping")
        shards_raw = data.get("shards")
        if isinstance(shards_raw, (str, bytes, bytearray)) or not isinstance(
            shards_raw, Sequence
        ):
            _reject("NONCANONICAL_VALUE", "shards must be an array")

        version = str(data.get("version") or SHARD_MANIFEST_V1)
        if version != SHARD_MANIFEST_V1:
            # Still accept if caller forced from_v1_dict with v1 shape.
            pass

        physical: list[PhysicalShardDescriptor] = []
        virtual: list[VirtualShardDescriptor] = []
        total_entities = 0
        total_bytes = 0

        for i, raw in enumerate(shards_raw):  # type: ignore[arg-type]
            if not isinstance(raw, Mapping):
                _reject("NONCANONICAL_VALUE", f"shards[{i}] must be an object")
            shard_id = _require_id(f"shards[{i}].shard_id", raw.get("shard_id"))
            car_cid = raw.get("car_cid")
            if car_cid is None or car_cid == "":
                _reject("AMBIGUOUS_ID", f"v1 shard {shard_id!r} missing car_cid")
            car_cid_s = _require_str(f"shards[{i}].car_cid", car_cid)
            # v1 car_cid may be any multiformat CID string; validate loosely.
            if not _CID_RE.fullmatch(car_cid_s):
                # Allow non-CID placeholders used in unit tests of the legacy path
                # only when they look like opaque tokens (still non-empty).
                if not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", car_cid_s):
                    _reject(
                        "NONCANONICAL_VALUE",
                        f"shards[{i}].car_cid is not a recognized CID: {car_cid_s!r}",
                    )
            approx = int(raw.get("approx_bytes") or 0)
            if approx < 0:
                _reject("INVALID_COUNT", f"shards[{i}].approx_bytes must be >= 0")
            # Integrity digest of the addressing material (not the CAR bytes).
            material = canonical_json_bytes(
                {
                    "approx_bytes": approx,
                    "car_cid": car_cid_s,
                    "shard_id": shard_id,
                }
            )
            checksum = ContentChecksum.of_bytes(material)
            etb = None
            if isinstance(raw.get("entity_type_bloom"), Mapping):
                etb = BloomFilterDescriptor.from_v1_bloom_dict(raw["entity_type_bloom"])
            rtb = None
            if isinstance(raw.get("relationship_type_bloom"), Mapping):
                rtb = BloomFilterDescriptor.from_v1_bloom_dict(
                    raw["relationship_type_bloom"]
                )
            headers_cid = raw.get("headers_cid")
            type_index_cid = raw.get("type_index_cid")
            neighbors_index_cid = raw.get("neighbors_index_cid")

            def _opt_cid(label: str, value: Any) -> Optional[str]:
                """Accept real CIDs; drop empty; reject other non-empty garbage."""
                if value is None or value == "":
                    return None
                text = _require_str(label, value)
                if _CID_RE.fullmatch(text):
                    return text
                _reject("NONCANONICAL_VALUE", f"{label} is not a recognized CID: {value!r}")
                return None

            stats = ShardStatistics(
                entity_count=0,
                relationship_count=0,
                approx_bytes=approx,
                physical_shard_count=1,
                virtual_shard_count=1,
            )
            total_bytes += approx
            vid = virtual_shard_id_for_index(i)
            is_real_cid = bool(_CID_RE.fullmatch(car_cid_s))
            physical.append(
                PhysicalShardDescriptor(
                    physical_shard_id=shard_id,
                    codec="car",
                    checksum=checksum,
                    size_bytes=approx,
                    statistics=stats,
                    path=None if is_real_cid else f"shards/{shard_id}.car",
                    car_cid=car_cid_s if is_real_cid else None,
                    virtual_shard_ids=(vid,),
                    index_buckets=(),
                    schema_version="1",
                    index_version="1",
                    headers_cid=_opt_cid("headers_cid", headers_cid),
                    type_index_cid=_opt_cid("type_index_cid", type_index_cid),
                    neighbors_index_cid=_opt_cid("neighbors_index_cid", neighbors_index_cid),
                    entity_type_bloom=etb,
                    relationship_type_bloom=rtb,
                )
            )
            virtual.append(
                VirtualShardDescriptor(
                    virtual_shard_id=vid,
                    index=i,
                    physical_shard_id=shard_id,
                    statistics=stats,
                )
            )

        # Sort physical/virtual by id as required by constructor.
        physical_t = tuple(sorted(physical, key=lambda p: p.physical_shard_id))
        # Re-index virtual shards in sorted physical order for v1 routing parity:
        # stable_shard_index uses sorted shard_id order.
        ordered_ids = [p.physical_shard_id for p in physical_t]
        virtual_rebuilt: list[VirtualShardDescriptor] = []
        for idx, pid in enumerate(ordered_ids):
            src = next(v for v in virtual if v.physical_shard_id == pid)
            virtual_rebuilt.append(
                VirtualShardDescriptor(
                    virtual_shard_id=virtual_shard_id_for_index(idx),
                    index=idx,
                    physical_shard_id=pid,
                    statistics=src.statistics,
                )
            )
        # Rewrite physical virtual_shard_ids to match rebuilt virtual ids.
        physical_fixed: list[PhysicalShardDescriptor] = []
        for idx, p in enumerate(physical_t):
            vid = virtual_shard_id_for_index(idx)
            physical_fixed.append(
                PhysicalShardDescriptor(
                    physical_shard_id=p.physical_shard_id,
                    codec=p.codec,
                    checksum=p.checksum,
                    size_bytes=p.size_bytes,
                    statistics=p.statistics,
                    path=p.path,
                    car_cid=p.car_cid,
                    virtual_shard_ids=(vid,),
                    index_buckets=p.index_buckets,
                    schema_version=p.schema_version,
                    index_version=p.index_version,
                    headers_cid=p.headers_cid,
                    type_index_cid=p.type_index_cid,
                    neighbors_index_cid=p.neighbors_index_cid,
                    entity_type_bloom=p.entity_type_bloom,
                    relationship_type_bloom=p.relationship_type_bloom,
                )
            )

        n = len(physical_fixed)
        routing = RendezvousRoutingDescriptor(
            algorithm=ROUTING_HASH_MODULO,
            hash_function="sha256",
            virtual_shard_count=max(n, 1),
            seed="",
            key_normalization="utf-8",
        )
        global_stats = ShardStatistics(
            entity_count=total_entities,
            relationship_count=0,
            approx_bytes=total_bytes,
            virtual_shard_count=n,
            physical_shard_count=n,
        )
        provenance = ProvenanceDescriptor(
            producer_id="producer:sharded-car-v1",
            producer_version="1",
            source="search.graph_query.sharded_car",
            created_at="1970-01-01T00:00:00Z",
            repository_revision=None,
            parent_manifest_cid=None,
            extra={"imported_version": "v1"},
        )
        etb_top = None
        if isinstance(data.get("entity_type_bloom"), Mapping):
            etb_top = BloomFilterDescriptor.from_v1_bloom_dict(data["entity_type_bloom"])
        rtb_top = None
        if isinstance(data.get("relationship_type_bloom"), Mapping):
            rtb_top = BloomFilterDescriptor.from_v1_bloom_dict(
                data["relationship_type_bloom"]
            )

        # Build identity for checksum without circular validation: use build path.
        return build_sharded_graph_manifest(
            version=SHARD_MANIFEST_V1,
            routing=routing,
            schema_version="1",
            index_version="1",
            codec="json",
            physical_shards=tuple(physical_fixed),
            virtual_shards=tuple(virtual_rebuilt),
            cross_shard_adjacency=(),
            statistics=global_stats,
            provenance=provenance,
            shard_size_limit_bytes=int(
                data.get("shard_size_limit_bytes", DEFAULT_SHARD_SIZE_LIMIT_BYTES)
            ),
            target_shard_bytes=int(
                data.get("target_shard_bytes", DEFAULT_TARGET_SHARD_BYTES)
            ),
            entity_type_bloom=etb_top,
            relationship_type_bloom=rtb_top,
            include_root_cid=True,
        )

    @classmethod
    def from_json(cls, text: str) -> "ShardedGraphManifest":
        if not isinstance(text, str) or not text:
            _reject("NONCANONICAL_VALUE", "json must be a non-empty string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ShardManifestValidationError(
                "NONCANONICAL_VALUE", f"invalid JSON: {exc}"
            ) from exc
        if not isinstance(data, Mapping):
            _reject("NONCANONICAL_VALUE", "json root must be an object")
        return cls.from_dict(data)

    @classmethod
    def build(cls, **kwargs: Any) -> "ShardedGraphManifest":
        return build_sharded_graph_manifest(**kwargs)


def build_sharded_graph_manifest(
    *,
    routing: RendezvousRoutingDescriptor,
    schema_version: str,
    index_version: str,
    codec: str,
    physical_shards: Sequence[PhysicalShardDescriptor],
    provenance: ProvenanceDescriptor,
    virtual_shards: Sequence[VirtualShardDescriptor] = (),
    cross_shard_adjacency: Sequence[CrossShardAdjacencyDescriptor] = (),
    statistics: Optional[ShardStatistics] = None,
    version: str = SHARD_MANIFEST_V2,
    shard_size_limit_bytes: int = DEFAULT_SHARD_SIZE_LIMIT_BYTES,
    target_shard_bytes: int = DEFAULT_TARGET_SHARD_BYTES,
    entity_type_bloom: Optional[BloomFilterDescriptor] = None,
    relationship_type_bloom: Optional[BloomFilterDescriptor] = None,
    include_root_cid: bool = True,
) -> ShardedGraphManifest:
    """Build a fully validated manifest with computed checksum and optional root CID."""
    physical_n = tuple(sorted(physical_shards, key=lambda p: p.physical_shard_id))
    virtual_n = tuple(sorted(virtual_shards, key=lambda v: v.virtual_shard_id))
    adj_n = tuple(sorted(cross_shard_adjacency, key=lambda a: a.adjacency_id))

    if statistics is None:
        statistics = ShardStatistics(
            entity_count=sum(p.statistics.entity_count for p in physical_n),
            relationship_count=sum(p.statistics.relationship_count for p in physical_n),
            approx_bytes=sum(
                p.statistics.approx_bytes or p.size_bytes for p in physical_n
            ),
            cross_shard_out_edges=sum(a.edge_count for a in adj_n if a.direction == "outgoing"),
            cross_shard_in_edges=sum(a.edge_count for a in adj_n if a.direction == "incoming"),
            virtual_shard_count=len(virtual_n) or routing.virtual_shard_count,
            physical_shard_count=len(physical_n),
        )

    # Provisional object for identity hashing: construct identity dict manually
    # to avoid double-validation with wrong checksum.
    provisional = ShardedGraphManifest(
        version=version,
        routing=routing,
        schema_version=schema_version,
        index_version=index_version,
        codec=codec,
        physical_shards=physical_n,
        virtual_shards=virtual_n,
        cross_shard_adjacency=adj_n,
        statistics=statistics,
        provenance=provenance,
        checksum=ContentChecksum.from_sha256_hex("0" * 64),
        root_cid=None,
        shard_size_limit_bytes=shard_size_limit_bytes,
        target_shard_bytes=target_shard_bytes,
        entity_type_bloom=entity_type_bloom,
        relationship_type_bloom=relationship_type_bloom,
        _skip_identity_checksum=True,
    )
    checksum = ContentChecksum.of_bytes(provisional.identity_bytes())
    root_cid = checksum.as_cid() if include_root_cid else None
    return ShardedGraphManifest(
        version=version,
        routing=routing,
        schema_version=schema_version,
        index_version=index_version,
        codec=codec,
        physical_shards=physical_n,
        virtual_shards=virtual_n,
        cross_shard_adjacency=adj_n,
        statistics=statistics,
        provenance=provenance,
        checksum=checksum,
        root_cid=root_cid,
        shard_size_limit_bytes=shard_size_limit_bytes,
        target_shard_bytes=target_shard_bytes,
        entity_type_bloom=entity_type_bloom,
        relationship_type_bloom=relationship_type_bloom,
        _skip_identity_checksum=False,
    )


def load_sharded_graph_manifest(data: Mapping[str, Any]) -> ShardedGraphManifest:
    """Load v1 or v2 shard manifest dict."""
    return ShardedGraphManifest.from_dict(data)


def build_virtual_to_physical_table(
    *,
    virtual_shard_count: int,
    physical_shard_ids: Sequence[str],
    algorithm: str = ROUTING_RENDEZVOUS_HRW,
    seed: str = "",
) -> tuple[VirtualShardDescriptor, ...]:
    """Materialize a full virtual→physical mapping for a routing configuration."""
    if virtual_shard_count < 1:
        raise ValueError("virtual_shard_count must be >= 1")
    if not physical_shard_ids:
        raise ValueError("physical_shard_ids must be non-empty")
    pids = tuple(sorted(_require_id("physical_shard_id", p) for p in physical_shard_ids))
    _unique_ids(pids, label="physical_shard_ids")
    rows: list[VirtualShardDescriptor] = []
    for i in range(virtual_shard_count):
        pid = physical_shard_for_virtual(
            i, pids, seed=seed, algorithm=algorithm
        )
        rows.append(
            VirtualShardDescriptor(
                virtual_shard_id=virtual_shard_id_for_index(i),
                index=i,
                physical_shard_id=pid,
            )
        )
    return tuple(rows)


__all__ = [
    "SHARD_MANIFEST_V1",
    "SHARD_MANIFEST_V2",
    "SUPPORTED_VERSIONS",
    "CANONICAL_JSON_PROFILE",
    "IDENTITY_DOMAIN",
    "ROUTING_HASH_MODULO",
    "ROUTING_RENDEZVOUS_HRW",
    "ROUTING_ALGORITHMS",
    "HASH_FUNCTIONS",
    "SHARD_CODECS",
    "INDEX_BUCKET_KINDS",
    "ADJACENCY_DIRECTIONS",
    "DEFAULT_SHARD_SIZE_LIMIT_BYTES",
    "DEFAULT_TARGET_SHARD_BYTES",
    "DEFAULT_VIRTUAL_SHARD_COUNT",
    "MAX_PHYSICAL_SHARDS",
    "MAX_VIRTUAL_SHARDS",
    "ShardManifestError",
    "ShardManifestValidationError",
    "ShardManifestIntegrityError",
    "BloomFilterDescriptor",
    "IndexBucketDescriptor",
    "ShardStatistics",
    "CrossShardAdjacencyDescriptor",
    "VirtualShardDescriptor",
    "PhysicalShardDescriptor",
    "RendezvousRoutingDescriptor",
    "ShardedGraphManifest",
    "build_sharded_graph_manifest",
    "load_sharded_graph_manifest",
    "build_virtual_to_physical_table",
    "normalize_routing_key",
    "hash_modulo_index",
    "stable_shard_index",
    "rendezvous_score",
    "rendezvous_pick",
    "virtual_shard_index",
    "virtual_shard_id_for_index",
    "physical_shard_for_virtual",
    "ContentChecksum",
    "ProvenanceDescriptor",
    "canonical_json_bytes",
    "sha256_hex",
]
