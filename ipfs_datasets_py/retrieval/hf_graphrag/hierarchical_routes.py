"""Integrity-bound hierarchical route pages for HF GraphRAG (OUL-026).

A single compact-index page is bounded at 4,096 descriptors.  When a
family has more shards or locator rows than that, this module builds a
tree of route pages:

* every physical page has at most 4,096 descriptors;
* each page is integrity-bound (SHA-256, byte size, row count, schema
  ID, first/last key, parent route digest);
* lookup walks only the covering path, never the full descriptor set;
* legacy US Code, patent, CVE, and SkillCenter single-page layouts
  remain readable as height-1 trees.

``page_locator_rows`` in :mod:`locators` still validates the whole index
against the 4,096 bound.  This module is the scale primitive that pages
beyond that single-page ceiling.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from .locators import (
    KIND_CORPUS,
    LocatorRow,
)
from .schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_ROUTING_ROWS_PER_INDEX,
    ArtifactDescriptor,
    ArtifactFamily,
    CompactIndexRow,
    HfGraphragSchemaError,
    PhysicalBoundError,
    canonical_json_dumps,
    content_sha256,
    normalize_relative_artifact_path,
    normalize_sha256,
    part_filename,
    validate_digest,
    validate_physical_row_count,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

ROUTE_PAGE_SCHEMA_VERSION: Final = "hf-graphrag-route-page/v1"
HIERARCHICAL_ROUTE_SCHEMA_VERSION: Final = "hf-graphrag-hierarchical-route/v1"
ROUTE_DESCRIPTOR_SCHEMA_VERSION: Final = "hf-graphrag-route-descriptor/v1"
TASK_ID: Final = "OUL-026"
MAX_DESCRIPTORS_PER_ROUTE_PAGE: Final = MAX_ROUTING_ROWS_PER_INDEX
DEFAULT_ROUTE_DIR: Final = "indexes/routes"

# Legacy single-page layouts that remain readable as height-1 trees.
# Schema IDs are accepted on envelopes and per-row ``schema_version``.
LEGACY_LAYOUT_SCHEMAS: Final = frozenset(
    {
        COMPACT_INDEX_SCHEMA_VERSION,
        "hf-graphrag-locator/v1",
        "hf-graphrag-locator-index/v1",
        "hf-graphrag-bm25-shard-meta/v1",
        "hf-graphrag-vector-routing/v1",
        "hf-graphrag-graph-routing/v1",
        "hf-graphrag-artifact-schema/v1",
        "uscode-sparse-graphrag-release-schema-v2",
        "uscode-bm25-v1",
        "uscode-hf-release/v1",
        "publicus-ir-graphrag/v1",
        "publicus-ir-graphrag/v2",
        "cvefixes-security-ir-hf-release/v1",
        "cvefixes-hf-shard-meta/v1",
        "skillcenter-huggingface-release/v3",
        "skillcenter-hf-shard-meta/v1",
        ROUTE_PAGE_SCHEMA_VERSION,
        HIERARCHICAL_ROUTE_SCHEMA_VERSION,
        ROUTE_DESCRIPTOR_SCHEMA_VERSION,
    }
)

LEGACY_LAYOUT_DOMAINS: Final = frozenset(
    {"uscode", "patent", "cve", "cvefixes", "skillcenter"}
)

_LEGACY_DOMAIN_SCHEMAS: Final = {
    "uscode": frozenset(
        {
            "uscode-sparse-graphrag-release-schema-v2",
            "uscode-bm25-v1",
            "uscode-hf-release/v1",
            "publicus-ir-graphrag/v2",
            "hf-graphrag-bm25-shard-meta/v1",
            COMPACT_INDEX_SCHEMA_VERSION,
        }
    ),
    "patent": frozenset(
        {
            "publicus-ir-graphrag/v1",
            "publicus-ir-graphrag/v2",
            COMPACT_INDEX_SCHEMA_VERSION,
        }
    ),
    "cve": frozenset(
        {
            "cvefixes-security-ir-hf-release/v1",
            "cvefixes-hf-shard-meta/v1",
            COMPACT_INDEX_SCHEMA_VERSION,
        }
    ),
    "cvefixes": frozenset(
        {
            "cvefixes-security-ir-hf-release/v1",
            "cvefixes-hf-shard-meta/v1",
            COMPACT_INDEX_SCHEMA_VERSION,
        }
    ),
    "skillcenter": frozenset(
        {
            "skillcenter-huggingface-release/v3",
            "skillcenter-hf-shard-meta/v1",
            COMPACT_INDEX_SCHEMA_VERSION,
        }
    ),
}

DescriptorLike = Union[
    "RouteDescriptor",
    CompactIndexRow,
    LocatorRow,
    ArtifactDescriptor,
    Mapping[str, Any],
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HierarchicalRouteError(HfGraphragSchemaError):
    """Base error for hierarchical route construction and lookup."""


class RoutePageError(HierarchicalRouteError):
    """Raised when a route page exceeds the physical descriptor bound."""


class RouteRangeError(HierarchicalRouteError):
    """Raised when route ranges overlap, invert, or leave a dense gap."""


class MissingRouteKeyError(HierarchicalRouteError):
    """Raised when a requested key is not covered by any route range."""


class RouteIntegrityError(HierarchicalRouteError):
    """Raised when a page digest, size, or parent binding disagrees."""


class LegacyLayoutError(HierarchicalRouteError):
    """Raised when a legacy single-page layout cannot be read."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HierarchicalRouteError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise HierarchicalRouteError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise HierarchicalRouteError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HierarchicalRouteError(f"{name} must be an integer")
    if value < 0:
        raise HierarchicalRouteError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise HierarchicalRouteError(f"{name} must be >= 1")
    return number


def _optional_str(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _validate_page_bound(max_rows: Any, *, name: str = "max_rows_per_page") -> int:
    number = _require_positive_int(max_rows, name)
    if number > MAX_DESCRIPTORS_PER_ROUTE_PAGE:
        raise PhysicalBoundError(
            f"{name}={number} exceeds physical routing bound "
            f"{MAX_DESCRIPTORS_PER_ROUTE_PAGE}"
        )
    return number


def _mapping_get(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value and value[name] not in (None, ""):
            return value[name]
    return default


def normalize_route_kind(value: Any, *, name: str = "kind") -> str:
    """Normalize a route family token."""

    if isinstance(value, ArtifactFamily):
        return value.value
    text = _require_non_empty_str(value, name, maximum=128).lower().replace("-", "_")
    aliases = {
        "document": "bm25_documents",
        "documents": "bm25_documents",
        "bm25_docs": "bm25_documents",
        "posting": "bm25_postings",
        "postings": "bm25_postings",
        "keyword": "bm25_postings",
        "keywords": "bm25_postings",
        "vector": "vectors",
        "embedding": "vectors",
        "embeddings": "vectors",
        "centroid": "centroids",
        "locator": "locator_index",
        "locators": "locator_index",
        "index": "routing_index",
        "routing": "routing_index",
        "compact_index": "routing_index",
        "route": "routing_index",
        "routes": "routing_index",
        "document_index": KIND_CORPUS,
        "corpus_chunks": KIND_CORPUS,
    }
    return aliases.get(text, text)


def normalize_legacy_domain(value: Any, *, name: str = "domain") -> str:
    """Normalize a legacy layout domain token."""

    text = _require_non_empty_str(value, name, maximum=64).lower().replace("-", "_")
    aliases = {
        "us_code": "uscode",
        "us-code": "uscode",
        "usc": "uscode",
        "cve": "cvefixes",
        "cve_fixes": "cvefixes",
        "cvefix": "cvefixes",
        "skill_center": "skillcenter",
        "skill-center": "skillcenter",
        "patents": "patent",
    }
    domain = aliases.get(text, text)
    if domain not in LEGACY_LAYOUT_DOMAINS and domain not in _LEGACY_DOMAIN_SCHEMAS:
        raise LegacyLayoutError(
            f"{name} must be one of {sorted(LEGACY_LAYOUT_DOMAINS)}, got {value!r}"
        )
    return domain


def route_page_relative_path(
    kind: str,
    *,
    level: int,
    page_index: int,
    route_dir: str = DEFAULT_ROUTE_DIR,
) -> str:
    """Return the canonical relative path for one route page."""

    directory = normalize_relative_artifact_path(route_dir)
    kind_value = normalize_route_kind(kind)
    level_value = _require_non_negative_int(level, "level")
    index_value = _require_non_negative_int(page_index, "page_index")
    return f"{directory}/{kind_value}/page-L{level_value:02d}-{index_value:06d}.json"


def _first_key_from_mapping(value: Mapping[str, Any]) -> str:
    raw = _mapping_get(
        value,
        "first_key",
        "first_term",
        "start_key",
        "min_key",
        "first_entry_cid",
    )
    return _require_non_empty_str(raw if raw is not None else "", "first_key")


def _last_key_from_mapping(value: Mapping[str, Any]) -> str:
    raw = _mapping_get(
        value,
        "last_key",
        "last_term",
        "end_key",
        "max_key",
        "last_entry_cid",
    )
    return _require_non_empty_str(raw if raw is not None else "", "last_key")


def _relative_path_from_mapping(value: Mapping[str, Any]) -> str:
    raw = _mapping_get(value, "relative_path", "path", "artifact_path")
    return normalize_relative_artifact_path(raw if raw is not None else "")


def _sha256_from_mapping(value: Mapping[str, Any], *, payload: Mapping[str, Any]) -> str:
    raw = _mapping_get(value, "sha256", "digest")
    if raw:
        return normalize_sha256(raw, name="sha256")
    # Fixture / legacy rows without an explicit digest bind to their payload.
    return content_sha256(canonical_json_dumps(dict(payload)))


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteDescriptor:
    """One inclusive key-range descriptor on a route page.

    Leaf descriptors point at a data shard.  Internal descriptors point at
    a child route page and bind that page's integrity digest.
    """

    first_key: str
    last_key: str
    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int
    shard_id: int
    kind: str
    schema_version: str = ROUTE_DESCRIPTOR_SCHEMA_VERSION
    content_cid: Optional[str] = None
    page_index: int = 0
    level: int = 0
    is_leaf: bool = True
    start_document_index: Optional[int] = None
    end_document_index: Optional[int] = None
    parent_route_digest: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        first_key = _require_non_empty_str(self.first_key, "first_key")
        last_key = _require_non_empty_str(self.last_key, "last_key")
        if first_key > last_key:
            raise RouteRangeError(
                f"route range is inverted: first_key={first_key!r} "
                f"> last_key={last_key!r}"
            )
        object.__setattr__(self, "first_key", first_key)
        object.__setattr__(self, "last_key", last_key)
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256, name="sha256"))
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self, "row_count", validate_physical_row_count(self.row_count)
        )
        object.__setattr__(
            self, "shard_id", _require_non_negative_int(self.shard_id, "shard_id")
        )
        object.__setattr__(self, "kind", normalize_route_kind(self.kind))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "page_index", _require_non_negative_int(self.page_index, "page_index")
        )
        object.__setattr__(self, "level", _require_non_negative_int(self.level, "level"))
        if not isinstance(self.is_leaf, bool):
            raise HierarchicalRouteError("is_leaf must be a boolean")
        if self.content_cid is not None:
            object.__setattr__(
                self,
                "content_cid",
                validate_digest(self.content_cid, name="content_cid"),
            )
        if self.start_document_index is not None:
            object.__setattr__(
                self,
                "start_document_index",
                _require_non_negative_int(
                    self.start_document_index, "start_document_index"
                ),
            )
        if self.end_document_index is not None:
            object.__setattr__(
                self,
                "end_document_index",
                _require_non_negative_int(
                    self.end_document_index, "end_document_index"
                ),
            )
        if (
            self.start_document_index is not None
            and self.end_document_index is not None
            and self.end_document_index < self.start_document_index
        ):
            raise RouteRangeError(
                "end_document_index must be >= start_document_index"
            )
        if self.parent_route_digest is not None:
            object.__setattr__(
                self,
                "parent_route_digest",
                normalize_sha256(self.parent_route_digest, name="parent_route_digest"),
            )
        if not isinstance(self.metadata, Mapping):
            raise HierarchicalRouteError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def contains(self, key: str) -> bool:
        text = _require_non_empty_str(key, "key")
        return self.first_key <= text <= self.last_key

    def with_parent_digest(self, digest: str) -> "RouteDescriptor":
        """Return a copy bound to *digest* as the parent route page."""

        return RouteDescriptor(
            first_key=self.first_key,
            last_key=self.last_key,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.shard_id,
            kind=self.kind,
            schema_version=self.schema_version,
            content_cid=self.content_cid,
            page_index=self.page_index,
            level=self.level,
            is_leaf=self.is_leaf,
            start_document_index=self.start_document_index,
            end_document_index=self.end_document_index,
            parent_route_digest=digest,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "first_key": self.first_key,
            "is_leaf": self.is_leaf,
            "kind": self.kind,
            "last_key": self.last_key,
            "level": self.level,
            "page_index": self.page_index,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "shard_id": self.shard_id,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
            payload["cid"] = self.content_cid
        if self.start_document_index is not None:
            payload["start_document_index"] = self.start_document_index
        if self.end_document_index is not None:
            payload["end_document_index"] = self.end_document_index
        if self.parent_route_digest is not None:
            payload["parent_route_digest"] = self.parent_route_digest
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    def to_compact_index_row(self) -> CompactIndexRow:
        return CompactIndexRow(
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.shard_id,
            first_key=self.first_key,
            last_key=self.last_key,
            kind=self.kind,
            schema_version=COMPACT_INDEX_SCHEMA_VERSION,
            content_cid=self.content_cid,
            start_document_index=self.start_document_index,
            end_document_index=self.end_document_index,
            metadata={
                **dict(self.metadata),
                "is_leaf": self.is_leaf,
                "level": self.level,
                "page_index": self.page_index,
                "parent_route_digest": self.parent_route_digest,
                "route_schema_version": self.schema_version,
            },
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RouteDescriptor":
        if not isinstance(value, Mapping):
            raise HierarchicalRouteError("route descriptor must be a mapping")
        payload = dict(value)
        first_key = _first_key_from_mapping(payload)
        last_key = _last_key_from_mapping(payload)
        relative_path = _relative_path_from_mapping(payload)
        size_bytes = int(
            _mapping_get(payload, "size_bytes", "byte_length", "size", default=0) or 0
        )
        row_count = int(_mapping_get(payload, "row_count", "rows", default=0) or 0)
        shard_id = int(_mapping_get(payload, "shard_id", "chunk_id", default=0) or 0)
        kind = _mapping_get(payload, "kind", "family") or KIND_CORPUS
        digest_seed = {
            "first_key": first_key,
            "kind": kind,
            "last_key": last_key,
            "relative_path": relative_path,
            "row_count": row_count,
            "shard_id": shard_id,
            "size_bytes": size_bytes,
        }
        is_leaf_raw = payload.get("is_leaf")
        if is_leaf_raw is None:
            is_leaf = payload.get("level", 0) in (0, None, "")
        else:
            is_leaf = bool(is_leaf_raw)
        start_doc = payload.get("start_document_index")
        if start_doc is None:
            start_doc = payload.get("document_start")
        end_doc = payload.get("end_document_index")
        if end_doc is None:
            end_doc = payload.get("document_end")
        metadata = (
            payload.get("metadata")
            if isinstance(payload.get("metadata"), Mapping)
            else {}
        )
        return cls(
            first_key=first_key,
            last_key=last_key,
            relative_path=relative_path,
            sha256=_sha256_from_mapping(payload, payload=digest_seed),
            size_bytes=size_bytes,
            row_count=row_count,
            shard_id=shard_id,
            kind=kind,
            schema_version=str(
                payload.get("schema_version") or ROUTE_DESCRIPTOR_SCHEMA_VERSION
            ),
            content_cid=_mapping_get(payload, "content_cid", "cid"),
            page_index=int(payload.get("page_index") or 0),
            level=int(payload.get("level") or 0),
            is_leaf=is_leaf,
            start_document_index=start_doc,
            end_document_index=end_doc,
            parent_route_digest=payload.get("parent_route_digest"),
            metadata=metadata,
        )

    @classmethod
    def from_compact_index_row(cls, row: CompactIndexRow) -> "RouteDescriptor":
        if not isinstance(row, CompactIndexRow):
            raise HierarchicalRouteError("expected CompactIndexRow")
        meta = dict(row.metadata)
        return cls(
            first_key=row.first_key,
            last_key=row.last_key,
            relative_path=row.relative_path,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            row_count=row.row_count,
            shard_id=row.shard_id,
            kind=row.kind,
            schema_version=str(
                meta.pop("route_schema_version", row.schema_version)
            ),
            content_cid=row.content_cid,
            page_index=int(meta.pop("page_index", 0) or 0),
            level=int(meta.pop("level", 0) or 0),
            is_leaf=bool(meta.pop("is_leaf", True)),
            start_document_index=row.start_document_index,
            end_document_index=row.end_document_index,
            parent_route_digest=meta.pop("parent_route_digest", None),
            metadata=meta,
        )

    @classmethod
    def from_locator_row(cls, row: LocatorRow) -> "RouteDescriptor":
        if not isinstance(row, LocatorRow):
            raise HierarchicalRouteError("expected LocatorRow")
        return cls(
            first_key=row.first_key,
            last_key=row.last_key,
            relative_path=row.relative_path,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            row_count=row.row_count,
            shard_id=row.shard_id,
            kind=row.kind,
            schema_version=row.schema_version,
            content_cid=row.content_cid,
            page_index=row.page_index,
            level=0,
            is_leaf=True,
            start_document_index=row.start_document_index,
            end_document_index=row.end_document_index,
            metadata=dict(row.metadata),
        )

    @classmethod
    def from_artifact_descriptor(
        cls,
        item: ArtifactDescriptor,
        *,
        kind: str | None = None,
    ) -> "RouteDescriptor":
        if not isinstance(item, ArtifactDescriptor):
            raise HierarchicalRouteError("expected ArtifactDescriptor")
        first = item.first_key or (item.key_range[0] if item.key_range else "")
        last = item.last_key or (item.key_range[1] if item.key_range else "")
        return cls(
            first_key=first,
            last_key=last,
            relative_path=item.relative_path,
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            row_count=item.row_count,
            shard_id=item.shard_id or 0,
            kind=kind or item.family.value,
            schema_version=item.schema_id,
            content_cid=item.content_cid,
            metadata=dict(item.metadata),
        )


def coerce_route_descriptor(value: DescriptorLike) -> RouteDescriptor:
    """Coerce a compact-index, locator, or mapping row into a route descriptor."""

    if isinstance(value, RouteDescriptor):
        return value
    if isinstance(value, CompactIndexRow):
        return RouteDescriptor.from_compact_index_row(value)
    if isinstance(value, LocatorRow):
        return RouteDescriptor.from_locator_row(value)
    if isinstance(value, ArtifactDescriptor):
        return RouteDescriptor.from_artifact_descriptor(value)
    if isinstance(value, Mapping):
        return RouteDescriptor.from_mapping(value)
    raise HierarchicalRouteError(
        f"cannot coerce {type(value).__name__} to RouteDescriptor"
    )


def sort_route_descriptors(
    rows: Sequence[DescriptorLike],
) -> tuple[RouteDescriptor, ...]:
    """Return descriptors sorted by ``(first_key, shard_id, relative_path)``."""

    materialised = [coerce_route_descriptor(item) for item in rows]
    ordered = sorted(
        materialised,
        key=lambda row: (row.first_key, row.shard_id, row.relative_path),
    )
    return tuple(ordered)


def validate_route_ranges(
    rows: Sequence[RouteDescriptor],
    *,
    kind: str | None = None,
    require_ordered: bool = True,
) -> tuple[RouteDescriptor, ...]:
    """Validate non-overlapping inclusive ranges.  No global 4,096 cap."""

    ordered = sort_route_descriptors(rows)
    expected_kind = (
        normalize_route_kind(kind, name="kind") if kind is not None else None
    )
    seen_paths: set[tuple[int, str]] = set()
    previous: RouteDescriptor | None = None
    for row in ordered:
        if expected_kind is not None and row.kind != expected_kind:
            raise RouteRangeError(
                f"route descriptor kind {row.kind!r} does not match index kind "
                f"{expected_kind!r}"
            )
        path_key = (row.level, row.relative_path)
        if path_key in seen_paths:
            raise RouteRangeError(
                f"duplicate route relative_path at level {row.level}: "
                f"{row.relative_path!r}"
            )
        seen_paths.add(path_key)
        if previous is not None and require_ordered:
            if previous.last_key >= row.first_key:
                raise RouteRangeError(
                    "route ranges overlap or are not ordered: "
                    f"[{previous.first_key!r}, {previous.last_key!r}] vs "
                    f"[{row.first_key!r}, {row.last_key!r}]"
                )
        previous = row
    return ordered


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def _descriptor_digest_dict(row: "RouteDescriptor") -> dict[str, Any]:
    """Descriptor payload used to bind a page (parent digest is not hashed)."""

    payload = row.to_dict()
    payload.pop("parent_route_digest", None)
    return payload


def _page_digest_payload(page: "RoutePage") -> dict[str, Any]:
    """Canonical payload used to bind a page.  Excludes parent digest."""

    return {
        "descriptors": [_descriptor_digest_dict(row) for row in page.descriptors],
        "first_key": page.first_key,
        "kind": page.kind,
        "last_key": page.last_key,
        "leaf_count": page.leaf_count,
        "level": page.level,
        "page_index": page.page_index,
        "relative_path": page.relative_path,
        "row_count": page.row_count,
        "schema_version": page.schema_version,
    }


@dataclass(frozen=True, slots=True)
class RoutePage:
    """One integrity-bound route page of at most 4,096 descriptors."""

    descriptors: tuple[RouteDescriptor, ...]
    kind: str
    level: int
    page_index: int
    relative_path: str
    sha256: str
    size_bytes: int
    first_key: str
    last_key: str
    leaf_count: int
    schema_version: str = ROUTE_PAGE_SCHEMA_VERSION
    parent_route_digest: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.descriptors, tuple):
            object.__setattr__(self, "descriptors", tuple(self.descriptors))
        if len(self.descriptors) > MAX_DESCRIPTORS_PER_ROUTE_PAGE:
            raise RoutePageError(
                f"route page has {len(self.descriptors)} descriptors; "
                f"exceeds bound {MAX_DESCRIPTORS_PER_ROUTE_PAGE}"
            )
        for position, row in enumerate(self.descriptors):
            if not isinstance(row, RouteDescriptor):
                raise HierarchicalRouteError(
                    f"descriptors[{position}] must be a RouteDescriptor"
                )
        object.__setattr__(self, "kind", normalize_route_kind(self.kind))
        object.__setattr__(
            self, "level", _require_non_negative_int(self.level, "level")
        )
        object.__setattr__(
            self,
            "page_index",
            _require_non_negative_int(self.page_index, "page_index"),
        )
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256, name="sha256"))
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        if self.descriptors:
            object.__setattr__(
                self,
                "first_key",
                _require_non_empty_str(self.first_key, "first_key"),
            )
            object.__setattr__(
                self, "last_key", _require_non_empty_str(self.last_key, "last_key")
            )
            if self.first_key != self.descriptors[0].first_key:
                raise RouteRangeError("page first_key must match first descriptor")
            if self.last_key != self.descriptors[-1].last_key:
                raise RouteRangeError("page last_key must match last descriptor")
        else:
            object.__setattr__(self, "first_key", str(self.first_key or ""))
            object.__setattr__(self, "last_key", str(self.last_key or ""))
        object.__setattr__(
            self,
            "leaf_count",
            _require_non_negative_int(self.leaf_count, "leaf_count"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.parent_route_digest is not None:
            object.__setattr__(
                self,
                "parent_route_digest",
                normalize_sha256(self.parent_route_digest, name="parent_route_digest"),
            )
        validate_physical_row_count(len(self.descriptors), name="descriptor_count")

    def __len__(self) -> int:
        return len(self.descriptors)

    def __iter__(self):
        return iter(self.descriptors)

    @property
    def row_count(self) -> int:
        return len(self.descriptors)

    @property
    def is_leaf_page(self) -> bool:
        return self.level == 0

    def contains(self, key: str) -> bool:
        if not self.descriptors:
            return False
        text = _require_non_empty_str(key, "key")
        return self.first_key <= text <= self.last_key

    def covering_descriptor(self, key: str) -> RouteDescriptor:
        text = _require_non_empty_str(key, "key")
        if not self.descriptors:
            raise MissingRouteKeyError(
                f"route page is empty; missing key {text!r}"
            )
        lo = 0
        hi = len(self.descriptors)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.descriptors[mid].first_key <= text:
                lo = mid + 1
            else:
                hi = mid
        index = lo - 1
        if index < 0:
            raise MissingRouteKeyError(
                f"key {text!r} is not covered by route page {self.relative_path}"
            )
        row = self.descriptors[index]
        if not row.contains(text):
            raise MissingRouteKeyError(
                f"key {text!r} is not covered by route page {self.relative_path}"
            )
        if index + 1 < len(self.descriptors) and self.descriptors[index + 1].contains(
            text
        ):
            raise RouteRangeError(f"key {text!r} matches multiple route ranges")
        return row

    def payload_for_digest(self) -> dict[str, Any]:
        return _page_digest_payload(self)

    def compute_digest(self) -> str:
        return content_sha256(canonical_json_dumps(self.payload_for_digest()))

    def with_parent_digest(self, digest: str) -> "RoutePage":
        bound = normalize_sha256(digest, name="parent_route_digest")
        stamped = tuple(row.with_parent_digest(bound) for row in self.descriptors)
        return RoutePage(
            descriptors=stamped,
            kind=self.kind,
            level=self.level,
            page_index=self.page_index,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            first_key=self.first_key,
            last_key=self.last_key,
            leaf_count=self.leaf_count,
            schema_version=self.schema_version,
            parent_route_digest=bound,
        )

    def to_internal_descriptor(self) -> RouteDescriptor:
        """Project this page as a parent-level descriptor."""

        if not self.descriptors:
            raise HierarchicalRouteError(
                "cannot project an empty route page as an internal descriptor"
            )
        return RouteDescriptor(
            first_key=self.first_key,
            last_key=self.last_key,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.page_index,
            kind=self.kind,
            schema_version=ROUTE_DESCRIPTOR_SCHEMA_VERSION,
            page_index=self.page_index,
            level=self.level + 1,
            is_leaf=False,
            metadata={"child_leaf_count": self.leaf_count, "child_level": self.level},
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.payload_for_digest()
        payload["sha256"] = self.sha256
        payload["size_bytes"] = self.size_bytes
        if self.parent_route_digest is not None:
            payload["parent_route_digest"] = self.parent_route_digest
        return payload

    def as_legacy_rows(self) -> list[dict[str, Any]]:
        """Project leaf descriptors as compact-index rows (legacy shape)."""

        return [row.to_compact_index_row().to_dict() for row in self.descriptors]

    @classmethod
    def from_descriptors(
        cls,
        descriptors: Sequence[RouteDescriptor],
        *,
        kind: str,
        level: int,
        page_index: int,
        route_dir: str = DEFAULT_ROUTE_DIR,
        max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
        parent_route_digest: str | None = None,
    ) -> "RoutePage":
        bound = _validate_page_bound(max_rows_per_page)
        if len(descriptors) > bound:
            raise RoutePageError(
                f"route page has {len(descriptors)} descriptors; exceeds bound {bound}"
            )
        ordered = validate_route_ranges(descriptors, kind=kind)
        kind_value = normalize_route_kind(kind)
        relative = route_page_relative_path(
            kind_value, level=level, page_index=page_index, route_dir=route_dir
        )
        leaf_count = 0
        for row in ordered:
            if row.is_leaf or level == 0:
                leaf_count += 1
            else:
                leaf_count += int(row.metadata.get("child_leaf_count") or row.row_count)
        first_key = ordered[0].first_key if ordered else ""
        last_key = ordered[-1].last_key if ordered else ""
        page = cls(
            descriptors=ordered,
            kind=kind_value,
            level=level,
            page_index=page_index,
            relative_path=relative,
            sha256="0" * 64,
            size_bytes=0,
            first_key=first_key,
            last_key=last_key,
            leaf_count=leaf_count,
            parent_route_digest=parent_route_digest,
        )
        digest = page.compute_digest()
        encoded = canonical_json_dumps(page.payload_for_digest()).encode("utf-8")
        return cls(
            descriptors=ordered,
            kind=kind_value,
            level=level,
            page_index=page_index,
            relative_path=relative,
            sha256=digest,
            size_bytes=len(encoded),
            first_key=first_key,
            last_key=last_key,
            leaf_count=leaf_count,
            parent_route_digest=parent_route_digest,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RoutePage":
        if not isinstance(value, Mapping):
            raise HierarchicalRouteError("route page must be a mapping")
        rows = value.get("descriptors") or value.get("rows") or []
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise HierarchicalRouteError("route page descriptors must be a sequence")
        descriptors = tuple(coerce_route_descriptor(row) for row in rows)
        page = cls(
            descriptors=descriptors,
            kind=value.get("kind") or KIND_CORPUS,
            level=int(value.get("level") or 0),
            page_index=int(value.get("page_index") or 0),
            relative_path=value.get("relative_path")
            or route_page_relative_path(
                value.get("kind") or KIND_CORPUS,
                level=int(value.get("level") or 0),
                page_index=int(value.get("page_index") or 0),
            ),
            sha256=value.get("sha256") or "0" * 64,
            size_bytes=int(value.get("size_bytes") or 0),
            first_key=value.get("first_key")
            or (descriptors[0].first_key if descriptors else ""),
            last_key=value.get("last_key")
            or (descriptors[-1].last_key if descriptors else ""),
            leaf_count=int(
                value.get("leaf_count")
                or sum(1 for row in descriptors if row.is_leaf)
                or len(descriptors)
            ),
            schema_version=str(value.get("schema_version") or ROUTE_PAGE_SCHEMA_VERSION),
            parent_route_digest=value.get("parent_route_digest"),
        )
        return page


def verify_route_page(page: RoutePage) -> RoutePage:
    """Recompute the page digest and fail closed on drift."""

    if not isinstance(page, RoutePage):
        raise RouteIntegrityError("page must be a RoutePage")
    expected = page.compute_digest()
    if expected != page.sha256:
        raise RouteIntegrityError(
            f"route page digest mismatch for {page.relative_path}: "
            f"declared {page.sha256} computed {expected}"
        )
    encoded = canonical_json_dumps(page.payload_for_digest()).encode("utf-8")
    if page.size_bytes and page.size_bytes != len(encoded):
        raise RouteIntegrityError(
            f"route page size mismatch for {page.relative_path}: "
            f"declared {page.size_bytes} computed {len(encoded)}"
        )
    if len(page.descriptors) > MAX_DESCRIPTORS_PER_ROUTE_PAGE:
        raise RoutePageError(
            f"route page has {len(page.descriptors)} descriptors; "
            f"exceeds bound {MAX_DESCRIPTORS_PER_ROUTE_PAGE}"
        )
    return page


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteHit:
    """Result of resolving one key through the route tree."""

    key: str
    leaf: RouteDescriptor
    path: tuple[RoutePage, ...]

    def __post_init__(self) -> None:
        key = _require_non_empty_str(self.key, "key")
        if not isinstance(self.leaf, RouteDescriptor):
            raise HierarchicalRouteError("leaf must be a RouteDescriptor")
        if not self.leaf.contains(key):
            raise HierarchicalRouteError(
                f"hit leaf does not contain key {key!r}: "
                f"[{self.leaf.first_key!r}, {self.leaf.last_key!r}]"
            )
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "path", tuple(self.path))

    @property
    def relative_path(self) -> str:
        return self.leaf.relative_path

    @property
    def shard_id(self) -> int:
        return self.leaf.shard_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "leaf": self.leaf.to_dict(),
            "path": [
                {
                    "level": page.level,
                    "page_index": page.page_index,
                    "relative_path": page.relative_path,
                    "sha256": page.sha256,
                }
                for page in self.path
            ],
            "relative_path": self.leaf.relative_path,
            "shard_id": self.leaf.shard_id,
        }


@dataclass(frozen=True, slots=True)
class HierarchicalRouteIndex:
    """Tree of integrity-bound route pages covering one artifact family."""

    pages: tuple[RoutePage, ...]
    root: RoutePage
    kind: str
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE
    schema_version: str = HIERARCHICAL_ROUTE_SCHEMA_VERSION
    is_legacy: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.root, RoutePage):
            raise HierarchicalRouteError("root must be a RoutePage")
        pages = tuple(self.pages)
        if not pages:
            raise HierarchicalRouteError("hierarchical route index has no pages")
        object.__setattr__(self, "pages", pages)
        object.__setattr__(self, "kind", normalize_route_kind(self.kind))
        object.__setattr__(
            self,
            "max_rows_per_page",
            _validate_page_bound(self.max_rows_per_page),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if not isinstance(self.is_legacy, bool):
            raise HierarchicalRouteError("is_legacy must be a boolean")
        for page in pages:
            if len(page) > self.max_rows_per_page:
                raise RoutePageError(
                    f"route page {page.relative_path} has {len(page)} descriptors; "
                    f"exceeds bound {self.max_rows_per_page}"
                )
            verify_route_page(page)
        by_digest = {page.sha256: page for page in pages}
        if self.root.sha256 not in by_digest:
            raise RouteIntegrityError("root page is not a member of pages")
        object.__setattr__(self, "root", by_digest[self.root.sha256])

    def __len__(self) -> int:
        return self.leaf_count

    @property
    def height(self) -> int:
        return self.root.level + 1

    @property
    def leaf_count(self) -> int:
        return self.root.leaf_count

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def root_digest(self) -> str:
        return self.root.sha256

    @property
    def leaf_pages(self) -> tuple[RoutePage, ...]:
        return tuple(page for page in self.pages if page.is_leaf_page)

    def page_by_digest(self, digest: str) -> RoutePage:
        bound = normalize_sha256(digest, name="digest")
        for page in self.pages:
            if page.sha256 == bound:
                return page
        raise RouteIntegrityError(f"no route page with digest {bound}")

    def page_by_path(self, relative_path: str) -> RoutePage:
        path = normalize_relative_artifact_path(relative_path)
        for page in self.pages:
            if page.relative_path == path:
                return page
        raise RouteIntegrityError(f"no route page at {path!r}")

    def locate(self, key: str) -> RouteHit:
        """Walk the covering path and return the leaf descriptor for *key*."""

        text = _require_non_empty_str(key, "key")
        path: list[RoutePage] = []
        current = self.root
        while True:
            path.append(current)
            descriptor = current.covering_descriptor(text)
            if descriptor.is_leaf or current.is_leaf_page:
                return RouteHit(key=text, leaf=descriptor, path=tuple(path))
            current = self.page_by_digest(descriptor.sha256)

    def locate_many(
        self,
        keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[RouteHit, ...]:
        if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
            raise HierarchicalRouteError("keys must be a sequence of strings")
        hits: list[RouteHit] = []
        for position, key in enumerate(keys):
            try:
                hits.append(self.locate(str(key)))
            except MissingRouteKeyError:
                if strict:
                    raise MissingRouteKeyError(
                        f"keys[{position}]={key!r} is not covered by any "
                        f"{self.kind} route range"
                    ) from None
        return tuple(hits)

    def containing_artifacts(
        self,
        keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[RouteDescriptor, ...]:
        hits = self.locate_many(keys, strict=strict)
        unique: dict[tuple[int, str], RouteDescriptor] = {}
        for hit in hits:
            unique[(hit.leaf.shard_id, hit.leaf.relative_path)] = hit.leaf
        return tuple(
            unique[item]
            for item in sorted(unique.keys(), key=lambda pair: (pair[0], pair[1]))
        )

    def covers(self, key: str) -> bool:
        try:
            self.locate(key)
            return True
        except MissingRouteKeyError:
            return False

    def covering_path(self, key: str) -> tuple[RoutePage, ...]:
        return self.locate(key).path

    def to_dict(self) -> dict[str, Any]:
        return {
            "height": self.height,
            "is_legacy": self.is_legacy,
            "kind": self.kind,
            "leaf_count": self.leaf_count,
            "max_rows_per_page": self.max_rows_per_page,
            "page_count": self.page_count,
            "pages": [page.to_dict() for page in self.pages],
            "root": self.root.to_dict(),
            "root_digest": self.root_digest,
            "schema_version": self.schema_version,
        }

    def fingerprint(self) -> str:
        return content_sha256(canonical_json_dumps(self.to_dict()))

    def as_legacy_rows(self) -> list[dict[str, Any]]:
        """Flatten leaf descriptors into a single-page compact-index list."""

        rows: list[RouteDescriptor] = []
        for page in self.leaf_pages:
            rows.extend(page.descriptors)
        ordered = sort_route_descriptors(rows)
        return [row.to_compact_index_row().to_dict() for row in ordered]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HierarchicalRouteIndex":
        if not isinstance(value, Mapping):
            raise HierarchicalRouteError("hierarchical route index must be a mapping")
        pages_raw = value.get("pages") or []
        if not isinstance(pages_raw, Sequence) or isinstance(pages_raw, (str, bytes)):
            raise HierarchicalRouteError("pages must be a sequence")
        pages = tuple(RoutePage.from_mapping(item) for item in pages_raw)
        root_raw = value.get("root")
        if isinstance(root_raw, Mapping):
            root = RoutePage.from_mapping(root_raw)
        elif pages:
            root = max(pages, key=lambda page: (page.level, -page.page_index))
        else:
            raise HierarchicalRouteError("hierarchical route index missing root")
        return cls(
            pages=pages,
            root=root,
            kind=value.get("kind") or root.kind,
            max_rows_per_page=int(
                value.get("max_rows_per_page") or MAX_DESCRIPTORS_PER_ROUTE_PAGE
            ),
            schema_version=str(
                value.get("schema_version") or HIERARCHICAL_ROUTE_SCHEMA_VERSION
            ),
            is_legacy=bool(value.get("is_legacy", False)),
        )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def page_route_descriptors(
    rows: Sequence[DescriptorLike],
    *,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    kind: str | None = None,
) -> tuple[tuple[RouteDescriptor, ...], ...]:
    """Partition ordered descriptors into pages of at most *max_rows_per_page*.

    Unlike :func:`locators.page_locator_rows`, this does **not** reject a
    descriptor set larger than 4,096.  Each returned page is bounded.
    """

    bound = _validate_page_bound(max_rows_per_page)
    ordered = validate_route_ranges(sort_route_descriptors(rows), kind=kind)
    if not ordered:
        return ((),)
    pages: list[tuple[RouteDescriptor, ...]] = []
    for start in range(0, len(ordered), bound):
        chunk = list(ordered[start : start + bound])
        page_index = start // bound
        stamped: list[RouteDescriptor] = []
        for row in chunk:
            if row.page_index != page_index:
                stamped.append(
                    RouteDescriptor(
                        first_key=row.first_key,
                        last_key=row.last_key,
                        relative_path=row.relative_path,
                        sha256=row.sha256,
                        size_bytes=row.size_bytes,
                        row_count=row.row_count,
                        shard_id=row.shard_id,
                        kind=row.kind,
                        schema_version=row.schema_version,
                        content_cid=row.content_cid,
                        page_index=page_index,
                        level=row.level,
                        is_leaf=row.is_leaf,
                        start_document_index=row.start_document_index,
                        end_document_index=row.end_document_index,
                        parent_route_digest=row.parent_route_digest,
                        metadata=dict(row.metadata),
                    )
                )
            else:
                stamped.append(row)
        pages.append(tuple(stamped))
    return tuple(pages)


def stream_bounded_descriptor_partitions(
    rows: Iterable[DescriptorLike],
    *,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    already_sorted: bool = False,
    kind: str | None = None,
) -> Iterator[tuple[RouteDescriptor, ...]]:
    """Yield ordered descriptor partitions of at most *max_rows_per_page*.

    When *already_sorted* is true the caller guarantees
    ``(first_key, shard_id, relative_path)`` order and this generator
    holds at most one partition in memory.
    """

    bound = _validate_page_bound(max_rows_per_page)
    if already_sorted:
        buffer: list[RouteDescriptor] = []
        previous: RouteDescriptor | None = None
        for item in rows:
            row = coerce_route_descriptor(item)
            if kind is not None and row.kind != normalize_route_kind(kind):
                raise RouteRangeError(
                    f"route descriptor kind {row.kind!r} does not match {kind!r}"
                )
            if previous is not None and previous.last_key >= row.first_key:
                raise RouteRangeError(
                    "route ranges overlap or are not ordered: "
                    f"[{previous.first_key!r}, {previous.last_key!r}] vs "
                    f"[{row.first_key!r}, {row.last_key!r}]"
                )
            buffer.append(row)
            previous = row
            if len(buffer) >= bound:
                yield tuple(buffer)
                buffer.clear()
        if buffer:
            yield tuple(buffer)
        elif previous is None:
            yield ()
        return
    for page in page_route_descriptors(
        list(rows), max_rows_per_page=bound, kind=kind
    ):
        yield page


def _build_page_level(
    descriptors: Sequence[RouteDescriptor],
    *,
    kind: str,
    level: int,
    max_rows_per_page: int,
    route_dir: str,
) -> list[RoutePage]:
    partitions = page_route_descriptors(
        descriptors, max_rows_per_page=max_rows_per_page, kind=kind
    )
    pages: list[RoutePage] = []
    for page_index, chunk in enumerate(partitions):
        if not chunk and page_index > 0:
            continue
        pages.append(
            RoutePage.from_descriptors(
                chunk,
                kind=kind,
                level=level,
                page_index=page_index,
                route_dir=route_dir,
                max_rows_per_page=max_rows_per_page,
            )
        )
    if not pages:
        pages.append(
            RoutePage.from_descriptors(
                (),
                kind=kind,
                level=level,
                page_index=0,
                route_dir=route_dir,
                max_rows_per_page=max_rows_per_page,
            )
        )
    return pages


def _stamp_children(children: Sequence[RoutePage], parent: RoutePage) -> list[RoutePage]:
    return [child.with_parent_digest(parent.sha256) for child in children]


def build_hierarchical_routes(
    rows: Sequence[DescriptorLike],
    *,
    kind: str,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    route_dir: str = DEFAULT_ROUTE_DIR,
) -> HierarchicalRouteIndex:
    """Build an integrity-bound route tree covering *rows*.

    *rows* may exceed 4,096 descriptors.  Every physical page stays at or
    below *max_rows_per_page*.  A single page is a valid height-1
    (legacy-compatible) tree.
    """

    bound = _validate_page_bound(max_rows_per_page)
    kind_value = normalize_route_kind(kind)
    leaves = validate_route_ranges(sort_route_descriptors(rows), kind=kind_value)
    level_pages = _build_page_level(
        leaves,
        kind=kind_value,
        level=0,
        max_rows_per_page=bound,
        route_dir=route_dir,
    )
    all_pages: list[RoutePage] = []
    current = level_pages
    level = 0
    while len(current) > 1:
        parents = _build_page_level(
            [page.to_internal_descriptor() for page in current],
            kind=kind_value,
            level=level + 1,
            max_rows_per_page=bound,
            route_dir=route_dir,
        )
        stamped: list[RoutePage] = []
        offset = 0
        for parent in parents:
            child_count = len(parent.descriptors)
            group = current[offset : offset + child_count]
            stamped.extend(_stamp_children(group, parent))
            offset += child_count
        all_pages.extend(stamped)
        current = parents
        level += 1
    # Single remaining page is the root.  Height-1 trees have no parent.
    all_pages.extend(current)
    root = current[0]
    is_legacy = root.level == 0 and len(all_pages) == 1
    return HierarchicalRouteIndex(
        pages=tuple(all_pages),
        root=root,
        kind=kind_value,
        max_rows_per_page=bound,
        is_legacy=is_legacy,
    )


def hierarchical_routes(
    rows: Sequence[DescriptorLike],
    *,
    kind: str,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    route_dir: str = DEFAULT_ROUTE_DIR,
) -> HierarchicalRouteIndex:
    """Public alias used by the reuse-gap audit (``symbol=hierarchical_routes``)."""

    return build_hierarchical_routes(
        rows,
        kind=kind,
        max_rows_per_page=max_rows_per_page,
        route_dir=route_dir,
    )


def stream_route_pages(
    rows: Iterable[DescriptorLike],
    *,
    kind: str,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    already_sorted: bool = False,
    route_dir: str = DEFAULT_ROUTE_DIR,
) -> Iterator[RoutePage]:
    """Yield leaf :class:`RoutePage` objects as bounded partitions fill."""

    kind_value = normalize_route_kind(kind)
    bound = _validate_page_bound(max_rows_per_page)
    page_index = 0
    emitted = False
    for chunk in stream_bounded_descriptor_partitions(
        rows,
        max_rows_per_page=bound,
        already_sorted=already_sorted,
        kind=kind_value,
    ):
        emitted = True
        yield RoutePage.from_descriptors(
            chunk,
            kind=kind_value,
            level=0,
            page_index=page_index,
            route_dir=route_dir,
            max_rows_per_page=bound,
        )
        page_index += 1
    if not emitted:
        yield RoutePage.from_descriptors(
            (),
            kind=kind_value,
            level=0,
            page_index=0,
            route_dir=route_dir,
            max_rows_per_page=bound,
        )


def seal_streamed_route_pages(
    pages: Sequence[RoutePage],
    *,
    kind: str | None = None,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    route_dir: str = DEFAULT_ROUTE_DIR,
) -> HierarchicalRouteIndex:
    """Bind streamed leaf pages into a complete hierarchical index."""

    if not pages:
        raise HierarchicalRouteError("cannot seal an empty page stream")
    kind_value = normalize_route_kind(kind or pages[0].kind)
    leaves: list[RouteDescriptor] = []
    for page in pages:
        verify_route_page(page)
        leaves.extend(page.descriptors)
    return build_hierarchical_routes(
        leaves,
        kind=kind_value,
        max_rows_per_page=max_rows_per_page,
        route_dir=route_dir,
    )


# ---------------------------------------------------------------------------
# Legacy layout readers
# ---------------------------------------------------------------------------


def _extract_legacy_rows(payload: Any) -> tuple[list[Any], str | None]:
    """Pull a row sequence and optional schema from a legacy envelope."""

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload), None
    if not isinstance(payload, Mapping):
        raise LegacyLayoutError("legacy layout must be a mapping or a sequence of rows")
    schema = payload.get("schema_version") or payload.get("schema_id")
    schema_text = str(schema) if schema else None
    for key in (
        "rows",
        "descriptors",
        "compact_index_rows",
        "indexes",
        "index_rows",
        "locators",
        "corpus_rows",
        "vector_rows",
        "artifacts",
    ):
        candidate = payload.get(key)
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            return list(candidate), schema_text
    # Nested ``index`` / ``routing`` objects used by some SkillCenter cards.
    for key in ("index", "routing", "compact_index", "locator_index"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            return _extract_legacy_rows(nested)
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            return list(nested), schema_text
    raise LegacyLayoutError(
        "legacy layout has no rows/descriptors/compact_index_rows sequence"
    )


def _assert_legacy_schema_readable(
    schema: str | None,
    *,
    domain: str | None = None,
) -> None:
    if schema is None or schema == "":
        return
    if schema in LEGACY_LAYOUT_SCHEMAS:
        return
    if domain is not None:
        allowed = _LEGACY_DOMAIN_SCHEMAS.get(normalize_legacy_domain(domain), frozenset())
        if schema in allowed:
            return
    # Domain adapters may mint per-family schema IDs that still follow the
    # compact-index row shape.  Accept those that declare a known prefix.
    prefixes = (
        "hf-graphrag-",
        "uscode-",
        "publicus-ir-",
        "cvefixes-",
        "skillcenter-",
        "patent-",
    )
    if any(schema.startswith(prefix) for prefix in prefixes):
        return
    raise LegacyLayoutError(f"unsupported legacy layout schema: {schema!r}")


def read_legacy_route_layout(
    payload: Any,
    *,
    kind: str | None = None,
    domain: str | None = None,
    max_rows_per_page: int = MAX_DESCRIPTORS_PER_ROUTE_PAGE,
) -> HierarchicalRouteIndex:
    """Read a legacy single-page compact index as a height-1 route tree.

    Accepts US Code, patent, CVE/CVEfixes, and SkillCenter envelopes and
    raw compact-index / locator row lists.  Hierarchical envelopes built
    by this module are loaded as-is.
    """

    bound = _validate_page_bound(max_rows_per_page)
    if (
        isinstance(payload, Mapping)
        and payload.get("schema_version") == HIERARCHICAL_ROUTE_SCHEMA_VERSION
        and payload.get("pages") is not None
    ):
        return HierarchicalRouteIndex.from_mapping(payload)

    rows, schema = _extract_legacy_rows(payload)
    envelope_schema = None
    if isinstance(payload, Mapping):
        envelope_schema = payload.get("schema_version") or payload.get("schema_id")
    _assert_legacy_schema_readable(schema, domain=domain)
    _assert_legacy_schema_readable(
        str(envelope_schema) if envelope_schema else None, domain=domain
    )
    if domain is not None:
        normalize_legacy_domain(domain)
    if not rows:
        inferred_kind = kind or KIND_CORPUS
        return build_hierarchical_routes(
            (), kind=inferred_kind, max_rows_per_page=bound
        )

    materialised: list[RouteDescriptor] = []
    kinds: set[str] = set()
    for item in rows:
        if isinstance(item, Mapping) and item.get("family") == "manifest":
            continue
        descriptor = coerce_route_descriptor(item)
        materialised.append(descriptor)
        kinds.add(descriptor.kind)
    if kind is not None:
        inferred_kind = normalize_route_kind(kind)
    elif len(kinds) == 1:
        inferred_kind = next(iter(kinds))
    else:
        inferred_kind = KIND_CORPUS
        materialised = [
            RouteDescriptor(
                first_key=row.first_key,
                last_key=row.last_key,
                relative_path=row.relative_path,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                row_count=row.row_count,
                shard_id=row.shard_id,
                kind=inferred_kind,
                schema_version=row.schema_version,
                content_cid=row.content_cid,
                page_index=row.page_index,
                level=0,
                is_leaf=True,
                start_document_index=row.start_document_index,
                end_document_index=row.end_document_index,
                metadata=dict(row.metadata),
            )
            for row in materialised
        ]
    index = build_hierarchical_routes(
        materialised, kind=inferred_kind, max_rows_per_page=bound
    )
    if index.height == 1:
        return HierarchicalRouteIndex(
            pages=index.pages,
            root=index.root,
            kind=index.kind,
            max_rows_per_page=index.max_rows_per_page,
            is_legacy=True,
        )
    return index


def read_legacy_uscode_layout(
    payload: Any,
    *,
    kind: str = KIND_CORPUS,
) -> HierarchicalRouteIndex:
    """Read a US Code single-page compact index."""

    return read_legacy_route_layout(payload, kind=kind, domain="uscode")


def read_legacy_patent_layout(
    payload: Any,
    *,
    kind: str = "bm25_postings",
) -> HierarchicalRouteIndex:
    """Read a patent (publicus-ir) single-page compact index."""

    return read_legacy_route_layout(payload, kind=kind, domain="patent")


def read_legacy_cve_layout(
    payload: Any,
    *,
    kind: str = "bm25_postings",
) -> HierarchicalRouteIndex:
    """Read a CVE/CVEfixes single-page compact index."""

    return read_legacy_route_layout(payload, kind=kind, domain="cvefixes")


def read_legacy_skillcenter_layout(
    payload: Any,
    *,
    kind: str = KIND_CORPUS,
) -> HierarchicalRouteIndex:
    """Read a SkillCenter single-page compact index."""

    return read_legacy_route_layout(payload, kind=kind, domain="skillcenter")


def locate_covering_page(
    index: HierarchicalRouteIndex,
    key: str,
) -> RoutePage:
    """Return the leaf route page that covers *key*."""

    hit = index.locate(key)
    for page in reversed(hit.path):
        if page.is_leaf_page:
            return page
    raise MissingRouteKeyError(f"no leaf route page covers {key!r}")


def example_legacy_layout_payload(
    *,
    domain: str,
    kind: str = KIND_CORPUS,
    row_count: int = 2,
) -> dict[str, Any]:
    """Compact deterministic recipe for one legacy single-page layout."""

    domain_value = normalize_legacy_domain(domain)
    kind_value = normalize_route_kind(kind)
    schema = sorted(_LEGACY_DOMAIN_SCHEMAS[domain_value])[0]
    rows: list[dict[str, Any]] = []
    for shard_id in range(row_count):
        first = f"{domain_value}-key-{shard_id:06d}"
        last = f"{domain_value}-key-{shard_id:06d}-z"
        relative = f"data/{kind_value}/{part_filename(shard_id)}"
        digest = content_sha256(f"legacy:{domain_value}:{relative}")
        payload = {
            "first_key": first,
            "kind": kind_value,
            "last_key": last,
            "relative_path": relative,
            "row_count": 2,
            "schema_version": schema,
            "sha256": digest,
            "shard_id": shard_id,
            "size_bytes": 128 + shard_id,
            "start_document_index": shard_id * 2,
            "end_document_index": shard_id * 2 + 1,
        }
        if domain_value in {"cvefixes", "cve"}:
            payload["first_term"] = first
            payload["last_term"] = last
        rows.append(payload)
    return {
        "domain": domain_value,
        "kind": kind_value,
        "rows": rows,
        "schema_version": schema,
    }


__all__ = [
    "DEFAULT_ROUTE_DIR",
    "HIERARCHICAL_ROUTE_SCHEMA_VERSION",
    "LEGACY_LAYOUT_DOMAINS",
    "LEGACY_LAYOUT_SCHEMAS",
    "MAX_DESCRIPTORS_PER_ROUTE_PAGE",
    "ROUTE_DESCRIPTOR_SCHEMA_VERSION",
    "ROUTE_PAGE_SCHEMA_VERSION",
    "TASK_ID",
    "HierarchicalRouteError",
    "HierarchicalRouteIndex",
    "LegacyLayoutError",
    "MissingRouteKeyError",
    "RouteDescriptor",
    "RouteHit",
    "RouteIntegrityError",
    "RoutePage",
    "RoutePageError",
    "RouteRangeError",
    "build_hierarchical_routes",
    "coerce_route_descriptor",
    "example_legacy_layout_payload",
    "hierarchical_routes",
    "locate_covering_page",
    "normalize_legacy_domain",
    "normalize_route_kind",
    "page_route_descriptors",
    "read_legacy_cve_layout",
    "read_legacy_patent_layout",
    "read_legacy_route_layout",
    "read_legacy_skillcenter_layout",
    "read_legacy_uscode_layout",
    "route_page_relative_path",
    "seal_streamed_route_pages",
    "sort_route_descriptors",
    "stream_bounded_descriptor_partitions",
    "stream_route_pages",
    "validate_route_ranges",
    "verify_route_page",
]
