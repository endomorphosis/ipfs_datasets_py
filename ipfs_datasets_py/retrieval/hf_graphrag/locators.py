"""Direct CID-to-corpus and CID-to-vector locators (USCIR-011).

Domain-neutral compact key-range locators used for:

* final-hit corpus hydration by durable ``entry_cid``; and
* off-centroid / graph-frontier vector fetch by the same primary key.

A locator index is an ordered sequence of inclusive ``[first_key, last_key]``
ranges, each pointing at exactly one bounded artifact (Parquet shard / page).
Construction is fail-closed:

* ranges must be ordered, non-overlapping, and free of internal gaps
  (``first_key > last_key``);
* locator pages themselves respect the physical 4,096-row bound;
* missing keys raise an explicit :class:`MissingKeyError` rather than
  silently returning a partial set.

Lookup is deterministic: the same multiset of rows and the same key always
resolve to the same single containing artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional

from .schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
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

LOCATOR_SCHEMA_VERSION: Final = "hf-graphrag-locator/v1"
LOCATOR_INDEX_SCHEMA_VERSION: Final = "hf-graphrag-locator-index/v1"
LOCATOR_FIXTURE_SCHEMA_VERSION: Final = "hf-graphrag-locator-fixture/v1"

KIND_CORPUS: Final = "corpus"
KIND_VECTORS: Final = "vectors"
SUPPORTED_LOCATOR_KINDS: Final = frozenset({KIND_CORPUS, KIND_VECTORS})

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LocatorError(HfGraphragSchemaError):
    """Base error for CID / key-range locator failures."""


class LocatorRangeError(LocatorError):
    """Raised when locator ranges overlap, invert, or leave a dense gap."""


class MissingKeyError(LocatorError):
    """Raised when a requested key is not covered by any locator range."""


class LocatorPageError(LocatorError):
    """Raised when a locator page exceeds the physical row bound."""


class LocatorKindError(LocatorError):
    """Raised when a locator kind is unsupported or inconsistent."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocatorError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise LocatorError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise LocatorError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LocatorError(f"{name} must be an integer")
    if value < 0:
        raise LocatorError(f"{name} must be >= 0")
    return value


def normalize_locator_kind(value: Any, *, name: str = "kind") -> str:
    """Normalize a locator kind to a supported family token."""

    if isinstance(value, ArtifactFamily):
        if value is ArtifactFamily.CORPUS:
            return KIND_CORPUS
        if value is ArtifactFamily.VECTORS:
            return KIND_VECTORS
        raise LocatorKindError(f"{name} must be corpus or vectors, got {value!r}")
    text = _require_non_empty_str(value, name, maximum=128).lower().replace("-", "_")
    aliases = {
        "corpus": KIND_CORPUS,
        "document": KIND_CORPUS,
        "documents": KIND_CORPUS,
        "vector": KIND_VECTORS,
        "vectors": KIND_VECTORS,
        "embedding": KIND_VECTORS,
        "embeddings": KIND_VECTORS,
    }
    if text not in aliases:
        raise LocatorKindError(
            f"{name} must be one of {sorted(SUPPORTED_LOCATOR_KINDS)}, got {value!r}"
        )
    return aliases[text]


# ---------------------------------------------------------------------------
# Locator row
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocatorRow:
    """One inclusive key-range locator pointing at a single artifact page.

    Ranges are inclusive on both ends.  ``first_key`` and ``last_key`` are
    durable content keys (typically ``entry_cid``).  Paths are release-relative.
    """

    first_key: str
    last_key: str
    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int
    shard_id: int
    kind: str
    schema_version: str = LOCATOR_SCHEMA_VERSION
    content_cid: Optional[str] = None
    page_index: int = 0
    start_document_index: Optional[int] = None
    end_document_index: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        first_key = _require_non_empty_str(self.first_key, "first_key")
        last_key = _require_non_empty_str(self.last_key, "last_key")
        if first_key > last_key:
            raise LocatorRangeError(
                f"locator range is inverted/gapped: first_key={first_key!r} "
                f"> last_key={last_key!r}"
            )
        object.__setattr__(self, "first_key", first_key)
        object.__setattr__(self, "last_key", last_key)
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self, "row_count", validate_physical_row_count(self.row_count)
        )
        object.__setattr__(
            self,
            "shard_id",
            _require_non_negative_int(self.shard_id, "shard_id"),
        )
        object.__setattr__(self, "kind", normalize_locator_kind(self.kind))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "page_index",
            _require_non_negative_int(self.page_index, "page_index"),
        )
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
            raise LocatorRangeError(
                "end_document_index must be >= start_document_index"
            )
        if not isinstance(self.metadata, Mapping):
            raise LocatorError("metadata must be a mapping")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def contains(self, key: str) -> bool:
        """Return True when *key* falls in the inclusive range."""

        text = _require_non_empty_str(key, "key")
        return self.first_key <= text <= self.last_key

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "first_key": self.first_key,
            "kind": self.kind,
            "last_key": self.last_key,
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
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    def to_compact_index_row(self) -> CompactIndexRow:
        """Project this locator into a shared compact-index row."""

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
                "locator_page_index": self.page_index,
                "locator_schema_version": self.schema_version,
            },
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocatorRow":
        if not isinstance(value, Mapping):
            raise LocatorError("locator row must be a mapping")
        return cls(
            first_key=value.get("first_key") or "",
            last_key=value.get("last_key") or "",
            relative_path=value.get("relative_path") or value.get("path") or "",
            sha256=value.get("sha256") or "",
            size_bytes=value.get("size_bytes", value.get("byte_length", 0)),
            row_count=value.get("row_count", 0),
            shard_id=value.get("shard_id", 0),
            kind=value.get("kind") or value.get("family") or "",
            schema_version=value.get("schema_version", LOCATOR_SCHEMA_VERSION),
            content_cid=value.get("content_cid") or value.get("cid"),
            page_index=value.get("page_index", 0),
            start_document_index=value.get("start_document_index"),
            end_document_index=value.get("end_document_index"),
            metadata=(
                value.get("metadata")
                if isinstance(value.get("metadata"), Mapping)
                else {}
            ),
        )

    @classmethod
    def from_compact_index_row(cls, row: CompactIndexRow) -> "LocatorRow":
        if not isinstance(row, CompactIndexRow):
            raise LocatorError("expected CompactIndexRow")
        meta = dict(row.metadata)
        page_index = meta.pop("locator_page_index", 0)
        schema_version = meta.pop(
            "locator_schema_version", LOCATOR_SCHEMA_VERSION
        )
        return cls(
            first_key=row.first_key,
            last_key=row.last_key,
            relative_path=row.relative_path,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            row_count=row.row_count,
            shard_id=row.shard_id,
            kind=row.kind,
            schema_version=str(schema_version),
            content_cid=row.content_cid,
            page_index=int(page_index) if page_index is not None else 0,
            start_document_index=row.start_document_index,
            end_document_index=row.end_document_index,
            metadata=meta,
        )


@dataclass(frozen=True, slots=True)
class LocatorHit:
    """Result of resolving one key to its single containing artifact."""

    key: str
    row: LocatorRow

    def __post_init__(self) -> None:
        key = _require_non_empty_str(self.key, "key")
        if not isinstance(self.row, LocatorRow):
            raise LocatorError("row must be a LocatorRow")
        if not self.row.contains(key):
            raise LocatorError(
                f"hit row does not contain key {key!r}: "
                f"[{self.row.first_key!r}, {self.row.last_key!r}]"
            )
        object.__setattr__(self, "key", key)

    @property
    def relative_path(self) -> str:
        return self.row.relative_path

    @property
    def shard_id(self) -> int:
        return self.row.shard_id

    @property
    def kind(self) -> str:
        return self.row.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.row.kind,
            "relative_path": self.row.relative_path,
            "row": self.row.to_dict(),
            "shard_id": self.row.shard_id,
            "sha256": self.row.sha256,
        }


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------


def sort_locator_rows(
    rows: Sequence[LocatorRow | Mapping[str, Any]],
) -> tuple[LocatorRow, ...]:
    """Return locator rows sorted by ``(first_key, shard_id, relative_path)``.

    Deterministic for the same multiset of rows regardless of input order.
    """

    materialised: list[LocatorRow] = []
    for position, item in enumerate(rows):
        if isinstance(item, LocatorRow):
            materialised.append(item)
        elif isinstance(item, Mapping):
            materialised.append(LocatorRow.from_mapping(item))
        else:
            raise LocatorError(
                f"rows[{position}] must be a LocatorRow or mapping"
            )
    # Stable total order: primary key range start, then shard_id, then path.
    ordered = sorted(
        materialised,
        key=lambda row: (row.first_key, row.shard_id, row.relative_path),
    )
    return tuple(ordered)


def validate_locator_ranges(
    rows: Sequence[LocatorRow],
    *,
    kind: str | None = None,
    require_dense_shard_ids: bool = True,
    max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
) -> tuple[LocatorRow, ...]:
    """Validate and return ordered non-overlapping locator ranges.

    Fail-closed checks:

    * at most *max_rows* locator rows (physical routing bound);
    * optional single *kind* constraint;
    * each row has ``first_key <= last_key`` (enforced by :class:`LocatorRow`);
    * after sorting by ``first_key``, consecutive ranges do not overlap
      (``prev.last_key < curr.first_key``);
    * optional dense ``shard_id`` sequence ``0..n-1`` without gaps;
    * no duplicate ``relative_path`` or ``shard_id``.
    """

    if (
        not isinstance(max_rows, int)
        or isinstance(max_rows, bool)
        or max_rows <= 0
    ):
        raise PhysicalBoundError("max_rows must be a positive integer")
    if max_rows > MAX_ROUTING_ROWS_PER_INDEX:
        raise PhysicalBoundError(
            f"max_rows={max_rows} exceeds physical routing bound "
            f"{MAX_ROUTING_ROWS_PER_INDEX}"
        )
    ordered = sort_locator_rows(rows)
    if len(ordered) > max_rows:
        raise LocatorPageError(
            f"locator page has {len(ordered)} rows; exceeds bound {max_rows}"
        )
    expected_kind = (
        normalize_locator_kind(kind, name="kind") if kind is not None else None
    )
    seen_paths: set[str] = set()
    seen_shards: set[int] = set()
    previous: LocatorRow | None = None
    for index, row in enumerate(ordered):
        if expected_kind is not None and row.kind != expected_kind:
            raise LocatorKindError(
                f"locator row kind {row.kind!r} does not match index kind "
                f"{expected_kind!r}"
            )
        if row.relative_path in seen_paths:
            raise LocatorRangeError(
                f"duplicate locator relative_path: {row.relative_path!r}"
            )
        seen_paths.add(row.relative_path)
        if row.shard_id in seen_shards:
            raise LocatorRangeError(
                f"duplicate locator shard_id: {row.shard_id}"
            )
        seen_shards.add(row.shard_id)
        if previous is not None:
            # Inclusive ranges: equality means the boundary key is claimed twice.
            if previous.last_key >= row.first_key:
                raise LocatorRangeError(
                    "locator ranges overlap or are not ordered: "
                    f"[{previous.first_key!r}, {previous.last_key!r}] vs "
                    f"[{row.first_key!r}, {row.last_key!r}]"
                )
            # Dense coverage of consecutive partitioned shards: after sorting
            # by first_key, shard_ids must increase. A decrease indicates a
            # gapped / mis-ordered partition even when key ranges do not overlap.
            if previous.shard_id >= row.shard_id:
                raise LocatorRangeError(
                    "locator shard_id sequence is gapped or mis-ordered: "
                    f"{previous.shard_id} then {row.shard_id}"
                )
        previous = row
    if require_dense_shard_ids and ordered:
        expected_ids = list(range(len(ordered)))
        actual_ids = [row.shard_id for row in ordered]
        if actual_ids != expected_ids:
            raise LocatorRangeError(
                "locator shard_id sequence has gaps or is not dense "
                f"0..{len(ordered) - 1}: {actual_ids}"
            )
    return ordered


def page_locator_rows(
    rows: Sequence[LocatorRow | Mapping[str, Any]],
    *,
    max_rows_per_page: int = MAX_ROUTING_ROWS_PER_INDEX,
) -> tuple[tuple[LocatorRow, ...], ...]:
    """Partition ordered locator rows into bounded pages (≤4,096 each)."""

    if (
        not isinstance(max_rows_per_page, int)
        or isinstance(max_rows_per_page, bool)
        or max_rows_per_page <= 0
    ):
        raise PhysicalBoundError("max_rows_per_page must be a positive integer")
    if max_rows_per_page > MAX_ROUTING_ROWS_PER_INDEX:
        raise PhysicalBoundError(
            f"max_rows_per_page={max_rows_per_page} exceeds "
            f"{MAX_ROUTING_ROWS_PER_INDEX}"
        )
    # Validate globally first (overlap/gap), then page for packaging.
    ordered = validate_locator_ranges(
        sort_locator_rows(rows),
        require_dense_shard_ids=True,
        max_rows=MAX_ROUTING_ROWS_PER_INDEX,
    )
    if not ordered:
        return ((),)
    pages: list[tuple[LocatorRow, ...]] = []
    for start in range(0, len(ordered), max_rows_per_page):
        chunk = ordered[start : start + max_rows_per_page]
        paged: list[LocatorRow] = []
        page_index = start // max_rows_per_page
        for row in chunk:
            if row.page_index != page_index:
                # Re-stamp page_index deterministically for packaging.
                paged.append(
                    LocatorRow(
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
                        start_document_index=row.start_document_index,
                        end_document_index=row.end_document_index,
                        metadata=dict(row.metadata),
                    )
                )
            else:
                paged.append(row)
        pages.append(tuple(paged))
    return tuple(pages)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeyLocatorIndex:
    """Deterministic inclusive key-range locator for one artifact family.

    Lookup uses binary search over ordered ``first_key`` values and returns
    **only** the single containing artifact.  Keys outside every range raise
    :class:`MissingKeyError`.
    """

    rows: tuple[LocatorRow, ...]
    kind: str
    schema_version: str = LOCATOR_INDEX_SCHEMA_VERSION
    max_rows: int = MAX_ROUTING_ROWS_PER_INDEX

    def __post_init__(self) -> None:
        kind = normalize_locator_kind(self.kind)
        max_rows = self.max_rows
        if (
            not isinstance(max_rows, int)
            or isinstance(max_rows, bool)
            or max_rows <= 0
        ):
            raise PhysicalBoundError("max_rows must be a positive integer")
        if max_rows > MAX_ROUTING_ROWS_PER_INDEX:
            raise PhysicalBoundError(
                f"max_rows={max_rows} exceeds {MAX_ROUTING_ROWS_PER_INDEX}"
            )
        validated = validate_locator_ranges(
            self.rows,
            kind=kind,
            require_dense_shard_ids=True,
            max_rows=max_rows,
        )
        object.__setattr__(self, "rows", validated)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        object.__setattr__(self, "max_rows", max_rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[LocatorRow | Mapping[str, Any]],
        *,
        kind: str,
        schema_version: str = LOCATOR_INDEX_SCHEMA_VERSION,
        max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
    ) -> "KeyLocatorIndex":
        ordered = sort_locator_rows(rows)
        return cls(
            rows=ordered,
            kind=kind,
            schema_version=schema_version,
            max_rows=max_rows,
        )

    @classmethod
    def from_mappings(
        cls,
        rows: Sequence[Mapping[str, Any]],
        *,
        kind: str | None = None,
        schema_version: str = LOCATOR_INDEX_SCHEMA_VERSION,
        max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
    ) -> "KeyLocatorIndex":
        materialised = [LocatorRow.from_mapping(row) for row in rows]
        if kind is None:
            kinds = {row.kind for row in materialised}
            if len(kinds) != 1:
                raise LocatorKindError(
                    "locator rows must share a single kind when kind is omitted"
                )
            kind = next(iter(kinds)) if kinds else KIND_CORPUS
        return cls.from_rows(
            materialised,
            kind=kind,
            schema_version=schema_version,
            max_rows=max_rows,
        )

    def _bisect_first_key(self, key: str) -> int:
        """Return the rightmost index whose first_key <= key (or -1)."""

        lo = 0
        hi = len(self.rows)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.rows[mid].first_key <= key:
                lo = mid + 1
            else:
                hi = mid
        return lo - 1

    def locate(self, key: str) -> LocatorHit:
        """Return the single containing artifact for *key*.

        Raises :class:`MissingKeyError` when no inclusive range covers *key*.
        """

        text = _require_non_empty_str(key, "key")
        if not self.rows:
            raise MissingKeyError(f"locator index is empty; missing key {text!r}")
        index = self._bisect_first_key(text)
        if index < 0:
            raise MissingKeyError(
                f"key {text!r} is not covered by any {self.kind} locator range"
            )
        row = self.rows[index]
        if not row.contains(text):
            raise MissingKeyError(
                f"key {text!r} is not covered by any {self.kind} locator range"
            )
        # Safety: ensure no later overlapping claim (validated at construction,
        # but re-check the immediate neighbor for fail-closed lookup).
        if index + 1 < len(self.rows) and self.rows[index + 1].contains(text):
            raise LocatorRangeError(
                f"key {text!r} matches multiple locator ranges"
            )
        return LocatorHit(key=text, row=row)

    def locate_many(
        self,
        keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorHit, ...]:
        """Locate each key in input order.

        When *strict* is true (default), the first missing key raises
        :class:`MissingKeyError`.  When false, missing keys are skipped.
        """

        if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
            raise LocatorError("keys must be a sequence of strings")
        hits: list[LocatorHit] = []
        for position, key in enumerate(keys):
            try:
                hits.append(self.locate(str(key)))
            except MissingKeyError:
                if strict:
                    raise MissingKeyError(
                        f"keys[{position}]={key!r} is not covered by any "
                        f"{self.kind} locator range"
                    ) from None
        return tuple(hits)

    def containing_artifacts(
        self,
        keys: Sequence[str],
        *,
        strict: bool = True,
    ) -> tuple[LocatorRow, ...]:
        """Return the unique containing artifacts for *keys*.

        Only the artifacts required to hydrate the requested keys are returned,
        ordered by ``(shard_id, relative_path)`` for determinism.  This is the
        minimal fetch set — one page per hit group, never the full family.
        """

        hits = self.locate_many(keys, strict=strict)
        unique: dict[tuple[int, str], LocatorRow] = {}
        for hit in hits:
            unique[(hit.row.shard_id, hit.row.relative_path)] = hit.row
        return tuple(
            unique[key]
            for key in sorted(unique.keys(), key=lambda item: (item[0], item[1]))
        )

    def covers(self, key: str) -> bool:
        """Return True when *key* is covered without raising."""

        try:
            self.locate(key)
            return True
        except MissingKeyError:
            return False

    def to_dicts(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "max_rows": self.max_rows,
            "row_count": len(self.rows),
            "rows": self.to_dicts(),
            "schema_version": self.schema_version,
        }

    def fingerprint(self) -> str:
        """Deterministic content fingerprint of the sealed index."""

        return content_sha256(canonical_json_dumps(self.to_dict()))


def build_corpus_locator(
    rows: Sequence[LocatorRow | Mapping[str, Any]],
    *,
    max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
) -> KeyLocatorIndex:
    """Build a CID-to-corpus locator index."""

    return KeyLocatorIndex.from_rows(rows, kind=KIND_CORPUS, max_rows=max_rows)


def build_vector_locator(
    rows: Sequence[LocatorRow | Mapping[str, Any]],
    *,
    max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
) -> KeyLocatorIndex:
    """Build a CID-to-vector locator index (direct entry-CID routing)."""

    return KeyLocatorIndex.from_rows(rows, kind=KIND_VECTORS, max_rows=max_rows)


# ---------------------------------------------------------------------------
# Builders from ordered keys
# ---------------------------------------------------------------------------


def build_locator_rows_from_keys(
    keys: Sequence[str],
    *,
    kind: str,
    data_dir: str,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    size_bytes: int = 0,
    sha256_seed: str = "locator-fixture",
    start_document_index: int = 0,
) -> tuple[LocatorRow, ...]:
    """Partition sorted unique *keys* into inclusive locator ranges.

    Keys must already be unique and sorted ascending; violations fail closed
    so silent reordering cannot create non-deterministic shard boundaries.
    """

    kind_value = normalize_locator_kind(kind)
    data_relative = normalize_relative_artifact_path(data_dir)
    if (
        not isinstance(max_rows_per_shard, int)
        or isinstance(max_rows_per_shard, bool)
        or max_rows_per_shard <= 0
    ):
        raise PhysicalBoundError("max_rows_per_shard must be a positive integer")
    if max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError(
            f"max_rows_per_shard={max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
        raise LocatorError("keys must be a sequence of strings")
    materialised: list[str] = []
    seen: set[str] = set()
    previous: str | None = None
    for position, raw in enumerate(keys):
        key = _require_non_empty_str(raw, f"keys[{position}]")
        if key in seen:
            raise LocatorRangeError(f"duplicate key in locator build: {key!r}")
        if previous is not None and previous > key:
            raise LocatorRangeError(
                "keys must be sorted ascending for deterministic locator build; "
                f"keys[{position - 1}]={previous!r} > keys[{position}]={key!r}"
            )
        seen.add(key)
        materialised.append(key)
        previous = key
    if not materialised:
        return ()

    rows: list[LocatorRow] = []
    doc_base = _require_non_negative_int(start_document_index, "start_document_index")
    for shard_id, offset in enumerate(
        range(0, len(materialised), max_rows_per_shard)
    ):
        group = materialised[offset : offset + max_rows_per_shard]
        relative = f"{data_relative}/{part_filename(shard_id)}"
        digest = content_sha256(f"{sha256_seed}:{kind_value}:{relative}")
        start_doc = doc_base + offset
        end_doc = start_doc + len(group) - 1
        rows.append(
            LocatorRow(
                first_key=group[0],
                last_key=group[-1],
                relative_path=relative,
                sha256=digest,
                size_bytes=_require_non_negative_int(size_bytes, "size_bytes"),
                row_count=len(group),
                shard_id=shard_id,
                kind=kind_value,
                start_document_index=start_doc,
                end_document_index=end_doc,
            )
        )
    return validate_locator_ranges(rows, kind=kind_value)


# ---------------------------------------------------------------------------
# Dual corpus + vector surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DualCidLocators:
    """Paired corpus and vector locators sharing the same primary-key space."""

    corpus: KeyLocatorIndex
    vectors: KeyLocatorIndex

    def __post_init__(self) -> None:
        if not isinstance(self.corpus, KeyLocatorIndex):
            raise LocatorError("corpus must be a KeyLocatorIndex")
        if not isinstance(self.vectors, KeyLocatorIndex):
            raise LocatorError("vectors must be a KeyLocatorIndex")
        if self.corpus.kind != KIND_CORPUS:
            raise LocatorKindError("corpus locator kind must be 'corpus'")
        if self.vectors.kind != KIND_VECTORS:
            raise LocatorKindError("vectors locator kind must be 'vectors'")

    def locate_corpus(self, entry_cid: str) -> LocatorHit:
        return self.corpus.locate(entry_cid)

    def locate_vector(self, entry_cid: str) -> LocatorHit:
        return self.vectors.locate(entry_cid)

    def hydrate_artifacts(
        self,
        entry_cids: Sequence[str],
        *,
        include_vectors: bool = True,
        strict: bool = True,
    ) -> dict[str, tuple[LocatorRow, ...]]:
        """Return the minimal corpus (and optional vector) artifact set.

        Only containing pages are returned — never the full family.
        """

        result: dict[str, tuple[LocatorRow, ...]] = {
            KIND_CORPUS: self.corpus.containing_artifacts(
                entry_cids, strict=strict
            ),
        }
        if include_vectors:
            result[KIND_VECTORS] = self.vectors.containing_artifacts(
                entry_cids, strict=strict
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus.to_dict(),
            "schema_version": LOCATOR_INDEX_SCHEMA_VERSION,
            "vectors": self.vectors.to_dict(),
        }


def build_dual_cid_locators(
    *,
    corpus_rows: Sequence[LocatorRow | Mapping[str, Any]],
    vector_rows: Sequence[LocatorRow | Mapping[str, Any]],
    max_rows: int = MAX_ROUTING_ROWS_PER_INDEX,
) -> DualCidLocators:
    """Build paired corpus and vector locators from row sequences."""

    return DualCidLocators(
        corpus=build_corpus_locator(corpus_rows, max_rows=max_rows),
        vectors=build_vector_locator(vector_rows, max_rows=max_rows),
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def load_locator_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the sealed locator fixture (or *path*)."""

    if path is None:
        # tests/fixtures/hf_graphrag/locator_rows.json relative to repo layout
        # is not imported from production code at runtime; callers pass path.
        raise LocatorError("path is required to load a locator fixture")
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocatorError(f"cannot load locator fixture: {target}") from exc
    if not isinstance(payload, Mapping):
        raise LocatorError("locator fixture must be a JSON object")
    return dict(payload)


def locators_from_fixture(payload: Mapping[str, Any]) -> DualCidLocators:
    """Materialise :class:`DualCidLocators` from a fixture mapping."""

    if not isinstance(payload, Mapping):
        raise LocatorError("locator fixture payload must be a mapping")
    corpus = payload.get("corpus_rows") or payload.get("corpus") or []
    vectors = payload.get("vector_rows") or payload.get("vectors") or []
    if not isinstance(corpus, Sequence) or isinstance(corpus, (str, bytes)):
        raise LocatorError("corpus_rows must be a sequence")
    if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes)):
        raise LocatorError("vector_rows must be a sequence")
    return build_dual_cid_locators(
        corpus_rows=[dict(row) for row in corpus],
        vector_rows=[dict(row) for row in vectors],
    )


# Fixed digests for the sealed unit fixture (valid 64-hex; not content hashes
# of real Parquet bytes). Stable across hosts and Python versions.
_FIXTURE_DIGESTS: Final = {
    "corpus/part-000000": (
        "1111111111111111111111111111111111111111111111111111111111111111"
    ),
    "corpus/part-000001": (
        "2222222222222222222222222222222222222222222222222222222222222222"
    ),
    "corpus/part-000002": (
        "3333333333333333333333333333333333333333333333333333333333333333"
    ),
    "vectors/part-000000": (
        "4444444444444444444444444444444444444444444444444444444444444444"
    ),
    "vectors/part-000001": (
        "5555555555555555555555555555555555555555555555555555555555555555"
    ),
}


def example_locator_fixture_payload() -> dict[str, Any]:
    """Deterministic compact fixture payload for unit tests and golden files."""

    # Sorted synthetic entry CIDs — not real multihash CIDs; locators treat
    # keys as opaque total-ordered strings (durable primary keys).
    entry_cids = [
        "entry-cid-0001",
        "entry-cid-0002",
        "entry-cid-0003",
        "entry-cid-0004",
        "entry-cid-0005",
        "entry-cid-0006",
    ]
    corpus_rows = (
        LocatorRow(
            first_key="entry-cid-0001",
            last_key="entry-cid-0002",
            relative_path="data/corpus/part-000000.parquet",
            sha256=_FIXTURE_DIGESTS["corpus/part-000000"],
            size_bytes=256,
            row_count=2,
            shard_id=0,
            kind=KIND_CORPUS,
            start_document_index=0,
            end_document_index=1,
        ),
        LocatorRow(
            first_key="entry-cid-0003",
            last_key="entry-cid-0004",
            relative_path="data/corpus/part-000001.parquet",
            sha256=_FIXTURE_DIGESTS["corpus/part-000001"],
            size_bytes=256,
            row_count=2,
            shard_id=1,
            kind=KIND_CORPUS,
            start_document_index=2,
            end_document_index=3,
        ),
        LocatorRow(
            first_key="entry-cid-0005",
            last_key="entry-cid-0006",
            relative_path="data/corpus/part-000002.parquet",
            sha256=_FIXTURE_DIGESTS["corpus/part-000002"],
            size_bytes=256,
            row_count=2,
            shard_id=2,
            kind=KIND_CORPUS,
            start_document_index=4,
            end_document_index=5,
        ),
    )
    vector_rows = (
        LocatorRow(
            first_key="entry-cid-0001",
            last_key="entry-cid-0003",
            relative_path="data/vectors/part-000000.parquet",
            sha256=_FIXTURE_DIGESTS["vectors/part-000000"],
            size_bytes=512,
            row_count=3,
            shard_id=0,
            kind=KIND_VECTORS,
            start_document_index=0,
            end_document_index=2,
        ),
        LocatorRow(
            first_key="entry-cid-0004",
            last_key="entry-cid-0006",
            relative_path="data/vectors/part-000001.parquet",
            sha256=_FIXTURE_DIGESTS["vectors/part-000001"],
            size_bytes=512,
            row_count=3,
            shard_id=1,
            kind=KIND_VECTORS,
            start_document_index=3,
            end_document_index=5,
        ),
    )
    return {
        "corpus_rows": [row.to_dict() for row in corpus_rows],
        "description": (
            "Deterministic CID-to-corpus and CID-to-vector locator rows for "
            "USCIR-011 unit tests. Keys are opaque sorted entry_cid tokens."
        ),
        "entry_cids": list(entry_cids),
        "expected": {
            "corpus_shard_count": len(corpus_rows),
            "hydrate_entry_cid_0003": {
                "corpus_paths": ["data/corpus/part-000001.parquet"],
                "vector_paths": ["data/vectors/part-000000.parquet"],
            },
            "missing_key": "entry-cid-9999",
            "vector_shard_count": len(vector_rows),
        },
        "schema_version": LOCATOR_FIXTURE_SCHEMA_VERSION,
        "vector_rows": [row.to_dict() for row in vector_rows],
    }


__all__ = [
    "KIND_CORPUS",
    "KIND_VECTORS",
    "LOCATOR_FIXTURE_SCHEMA_VERSION",
    "LOCATOR_INDEX_SCHEMA_VERSION",
    "LOCATOR_SCHEMA_VERSION",
    "SUPPORTED_LOCATOR_KINDS",
    "DualCidLocators",
    "KeyLocatorIndex",
    "LocatorError",
    "LocatorHit",
    "LocatorKindError",
    "LocatorPageError",
    "LocatorRangeError",
    "LocatorRow",
    "MissingKeyError",
    "build_corpus_locator",
    "build_dual_cid_locators",
    "build_locator_rows_from_keys",
    "build_vector_locator",
    "example_locator_fixture_payload",
    "load_locator_fixture",
    "locators_from_fixture",
    "normalize_locator_kind",
    "page_locator_rows",
    "sort_locator_rows",
    "validate_locator_ranges",
]
