"""Repair and pack globally sorted range-routed GraphRAG shards.

Thin clients fetch every compact-index row where
``first_key <= probe <= last_key``. That is a bounded fetch only when
data shards are internally sorted and their ranges are disjoint.
Overlapping or inverted ranges over-fetch (one BM25 term covering 66
posting shards) and internally unsorted shards can drop recall.

This module:

* diagnoses locator overlap / inversion / unsorted keys;
* rewrites already-packed families without re-extracting the corpus;
* packs nested BM25 cells term-atomically (a term never spans shards).

Domain builders should call :func:`write_term_sorted_posting_shards`
instead of concatenating nest chunks in routing-file order.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import OrderedDict, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.parallel_tokenize import (
    chunk_items,
    ordered_process_map,
)

from .artifacts import ArtifactWriterConfig, atomic_staging, write_zstd_parquet
from .schema import MAX_ROWS_PER_PHYSICAL_SHARD, part_filename

# Workers hold a few mmapped Parquet tables, not a live inverted index.
GRAPHRAG_BYTES_PER_WORKER: Final = 1024 * 1024 * 1024
REPAIR_BYTES_PER_WORKER: Final = GRAPHRAG_BYTES_PER_WORKER

SIDECAR_PARQUET_NAMES: Final = frozenset(
    {
        "identity.parquet",
        "centroids.parquet",
        "ids.parquet",
    }
)

# Families whose compact index is probed with first_key <= key <= last_key.
# Vectors are centroid-routed; graph edges are walked via adjacency.
RANGE_ROUTED_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "graph_nodes",
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
    }
)

GROUP_KEY_BY_FAMILY: Final = {
    "bm25_documents": "entry_cid",
    "bm25_postings": "term",
    "corpus": "entry_cid",
    "graph_incoming_adjacency": "node_cid",
    "graph_nodes": "node_cid",
    "graph_outgoing_adjacency": "node_cid",
}

TIE_FIELDS_BY_FAMILY: Final = {
    "bm25_postings": ("posting_chunk_index", "document_index"),
}


def _log(message: str, *, file: TextIO | None = None) -> None:
    handle = file or sys.stdout
    print(message, file=handle, flush=True)


def _ensure_package_on_pythonpath() -> None:
    """Spawn workers re-import the package; they need PYTHONPATH, not sys.path."""

    import ipfs_datasets_py

    root = str(Path(ipfs_datasets_py.__file__).resolve().parents[1])
    current = os.environ.get("PYTHONPATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    if root not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([root, *parts])


def graphrag_process_pool_plan(*, requested: int | None = None):
    """Admit spawn workers from unused RAM/CPU for GraphRAG pack/repair I/O.

    Same admission as :func:`tokenize_process_pool_size` (1 GiB per worker,
    one core reserved, RAM fraction 0.45). Query-time walks stay serial.
    """

    _ensure_package_on_pythonpath()
    return tokenize_process_pool_size(
        per_task_budget=GRAPHRAG_BYTES_PER_WORKER,
        requested=requested,
    )


def _repair_pool_plan(*, requested: int | None = None):
    return graphrag_process_pool_plan(requested=requested)


@dataclass(frozen=True, slots=True)
class RangeRoutingDiagnosis:
    """Locator health for one data family."""

    family: str
    shard_count: int
    inverted_ranges: int
    overlapping_pairs: int
    internally_unsorted: int
    ok: bool
    samples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "internally_unsorted": self.internally_unsorted,
            "inverted_ranges": self.inverted_ranges,
            "ok": self.ok,
            "overlapping_pairs": self.overlapping_pairs,
            "samples": list(self.samples),
            "shard_count": self.shard_count,
        }


@dataclass(frozen=True, slots=True)
class RangeRepairResult:
    family: str
    rewritten: bool
    diagnosis_before: RangeRoutingDiagnosis
    diagnosis_after: RangeRoutingDiagnosis
    shard_count: int
    index_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis_after": self.diagnosis_after.to_dict(),
            "diagnosis_before": self.diagnosis_before.to_dict(),
            "family": self.family,
            "index_path": self.index_path,
            "rewritten": self.rewritten,
            "shard_count": self.shard_count,
        }


@dataclass(frozen=True, slots=True)
class _RowPointer:
    key: str
    group: str
    tie: tuple[Any, ...]
    file_index: int
    row_index: int


def _index_file_batch(payload: Mapping[str, Any]) -> list[_RowPointer]:
    """Top-level spawn worker: index key columns for a batch of parquet files."""

    import pyarrow.parquet as pq

    paths = [Path(item) for item in payload["paths"]]
    start_index = int(payload["start_index"])
    key_fields = tuple(payload["key_fields"])
    group_field = payload.get("group_field")
    tie_fields = tuple(payload.get("tie_fields") or ())
    pointers: list[_RowPointer] = []
    for offset, path in enumerate(paths):
        file_index = start_index + offset
        parquet = pq.ParquetFile(path, memory_map=True)
        names = set(parquet.schema_arrow.names)
        column = next((name for name in key_fields if name in names), None)
        if column is None:
            from .engine import GraphragEngineError

            raise GraphragEngineError(
                f"{path} has none of the locator key columns {tuple(key_fields)}"
            )
        extra_cols = [name for name in tie_fields if name in names]
        take_names = [column, *extra_cols]
        if group_field and group_field in names and group_field not in take_names:
            take_names.append(group_field)
        table = parquet.read(columns=[name for name in take_names if name in names])
        rows = table.to_pylist()
        for row_index, row in enumerate(rows):
            key = "" if row.get(column) is None else str(row.get(column))
            if not key:
                from .engine import GraphragEngineError

                raise GraphragEngineError(f"{path} row {row_index} is missing {column}")
            group = str(row.get(group_field) or key) if group_field else key
            pointers.append(
                _RowPointer(
                    key=key,
                    group=group,
                    tie=_tie_tuple(row, tie_fields),
                    file_index=file_index,
                    row_index=row_index,
                )
            )
    return pointers


def _write_shard_batch(payload: Mapping[str, Any]) -> int:
    """Top-level spawn worker: materialize and write a batch of dest shards."""

    files = [Path(item) for item in payload["files"]]
    max_rows = int(payload["max_rows"])
    cache = _TableCache(files, max_open=8)
    written = 0
    for shard in payload["shards"]:
        pointers = [
            _RowPointer(key="", group="", tie=(), file_index=int(file_index), row_index=int(row_index))
            for file_index, row_index in shard["pairs"]
        ]
        rows = _materialize_shard(pointers, cache)
        write_zstd_parquet(
            Path(shard["dest"]),
            rows,
            max_rows=max_rows,
            config=ArtifactWriterConfig(max_rows_per_shard=max_rows),
        )
        written += 1
    return written


def _describe_family_file_batch(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Top-level spawn worker: key ends + sha256 descriptor for compact indexes."""

    from .artifacts import describe_file
    from .schema import COMPACT_INDEX_SCHEMA_VERSION, ArtifactFamily

    root = Path(payload["root"])
    key_fields = tuple(payload["key_fields"])
    require_sorted = bool(payload.get("require_sorted"))
    rows: list[dict[str, Any]] = []
    for path_str in payload["paths"]:
        path = Path(path_str)
        values = _parquet_key_column(path, key_fields)
        if not values:
            continue
        first, last = values[0], values[-1]
        unsorted = first > last or not _keys_are_sorted(values)
        if require_sorted and unsorted:
            from .engine import GraphragEngineError

            raise GraphragEngineError(
                f"{path} key column is not sorted (first={first!r}, last={last!r}). "
                "Call repair_graphrag_range_routing() to globally sort shards."
            )
        if not require_sorted:
            # Catalog families (graph_edges, centroid-routed vectors) are
            # not probed with first_key <= key <= last_key. Use the span of
            # keys so CompactIndexRow never sees an inverted first/last row.
            first, last = min(values), max(values)
        if not str(first or "").strip() or not str(last or "").strip():
            continue
        descriptor = describe_file(
            path,
            root=root,
            row_count=len(values),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            first_key=first,
            last_key=last,
        )
        rows.append(
            {
                "content_cid": descriptor.content_cid,
                "first_key": first,
                "last_key": last,
                "relative_path": descriptor.relative_path,
                "row_count": len(values),
                "sha256": descriptor.sha256,
                "size_bytes": descriptor.size_bytes,
            }
        )
    return rows


def describe_family_files_parallel(
    files: Sequence[Path],
    *,
    root: str | Path,
    key_fields: Sequence[str],
    require_sorted: bool = False,
) -> list[dict[str, Any]]:
    """Hash and read locator key ends for *files* with a resource-aware pool."""

    if not files:
        return []
    plan = graphrag_process_pool_plan()
    batch = max(8, math.ceil(len(files) / max(1, plan.workers * 4)))
    payloads = [
        {
            "key_fields": tuple(key_fields),
            "paths": [str(path) for path in group],
            "require_sorted": require_sorted,
            "root": str(Path(root).expanduser().resolve()),
        }
        for group in chunk_items(list(files), batch)
    ]
    _log(
        f"  describe files={len(files)} batches={len(payloads)} "
        f"workers={plan.workers} reason={plan.reason}"
    )
    rows: list[dict[str, Any]] = []
    for part in ordered_process_map(
        _describe_family_file_batch,
        payloads,
        plan=plan,
        per_task_budget=GRAPHRAG_BYTES_PER_WORKER,
    ):
        rows.extend(part)
    return rows


def _scan_key_file_batch(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Top-level spawn worker: first/last/sorted flags for diagnose."""

    key_fields = tuple(payload["key_fields"])
    rows: list[dict[str, Any]] = []
    for path_str in payload["paths"]:
        path = Path(path_str)
        values = _parquet_key_column(path, key_fields)
        if not values:
            continue
        first, last = values[0], values[-1]
        rows.append(
            {
                "first": first,
                "inverted": first > last,
                "last": last,
                "relative": path.name,
                "unsorted": not _keys_are_sorted(values),
            }
        )
    return rows


def list_family_parquet_files(
    root: str | Path,
    data_dir: str,
    *,
    glob: str = "**/*.parquet",
) -> list[Path]:
    """Return data parquet shards, skipping sidecars and locator files."""

    family_dir = Path(root).expanduser().resolve() / data_dir
    if not family_dir.is_dir():
        return []
    files = [
        path
        for path in sorted(family_dir.glob(glob))
        if path.is_file()
        and path.suffix == ".parquet"
        and path.name not in SIDECAR_PARQUET_NAMES
        and "locator" not in path.as_posix()
    ]
    return files


def posting_cell_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Global nested-posting order: term, then chunk, then first document."""

    if not isinstance(record, Mapping):
        raise TypeError("posting cell must be a mapping")
    chunk = record.get("posting_chunk_index") or 0
    try:
        chunk_i = int(chunk)
    except (TypeError, ValueError):
        chunk_i = 0
    docs = record.get("document_indices") or ()
    first_doc = int(docs[0]) if docs else int(record.get("document_index") or 0)
    return (str(record.get("term") or ""), chunk_i, first_doc)


def covering_locator_rows(
    rows: Sequence[Mapping[str, Any]], key: str
) -> list[dict[str, Any]]:
    """Inclusive range probe used by the thin client."""

    hits = []
    for row in rows:
        first = str(row.get("first_key") or "")
        last = str(row.get("last_key") or "")
        if first <= key <= last:
            hits.append(dict(row))
    return hits


def _keys_are_sorted(values: Sequence[str]) -> bool:
    return all(values[index] <= values[index + 1] for index in range(len(values) - 1))


def _parquet_key_column(path: Path, key_fields: Sequence[str]) -> list[str] | None:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    for column in key_fields:
        if column not in names:
            continue
        table = pq.read_table(path, columns=[column])
        values = [
            "" if value is None else str(value) for value in table.column(0).to_pylist()
        ]
        if any(value.strip() for value in values):
            return values
    return None


def _overlapping_pairs(
    ranges: Sequence[tuple[str, str, str]],
) -> list[tuple[str, str, str, str]]:
    ordered = sorted(ranges, key=lambda item: (item[0], item[2]))
    overlaps: list[tuple[str, str, str, str]] = []
    previous: tuple[str, str, str] | None = None
    for item in ordered:
        first, last, path = item
        if previous is not None and previous[1] >= first:
            overlaps.append((previous[2], previous[0], previous[1], path))
        previous = item
    return overlaps


def diagnose_family_files(
    files: Sequence[Path],
    *,
    family: str,
    key_fields: Sequence[str],
) -> RangeRoutingDiagnosis:
    """Inspect physical shards (first/last row, internal order, overlap)."""

    scanned: list[dict[str, Any]] = []
    if files:
        plan = _repair_pool_plan()
        batch = max(8, math.ceil(len(files) / max(1, plan.workers * 4)))
        payloads = [
            {
                "key_fields": tuple(key_fields),
                "paths": [str(path) for path in group],
            }
            for group in chunk_items(list(files), batch)
        ]
        for part in ordered_process_map(
            _scan_key_file_batch,
            payloads,
            plan=plan,
            per_task_budget=REPAIR_BYTES_PER_WORKER,
        ):
            scanned.extend(part)

    ranges: list[tuple[str, str, str]] = []
    inverted = 0
    unsorted = 0
    samples: list[str] = []
    for item in scanned:
        first = str(item["first"])
        last = str(item["last"])
        relative = str(item["relative"])
        if item["inverted"]:
            inverted += 1
            if len(samples) < 8:
                samples.append(f"inverted {relative}: {first!r} > {last!r}")
        if item["unsorted"]:
            unsorted += 1
            if len(samples) < 8:
                samples.append(f"unsorted {relative}")
        ranges.append((first, last, relative))
    overlaps = _overlapping_pairs(ranges) if inverted == 0 else []
    # Inverted ranges are not comparable with first <= key <= last; still
    # count lexicographic overlaps among the non-inverted remainder.
    if inverted:
        comparable = [item for item in ranges if item[0] <= item[1]]
        overlaps = _overlapping_pairs(comparable)
    for left_path, first, last, right_path in overlaps[:8]:
        if len(samples) >= 8:
            break
        samples.append(
            f"overlap {left_path} [{first!r}, {last!r}] vs {right_path}"
        )
    ok = inverted == 0 and unsorted == 0 and not overlaps
    return RangeRoutingDiagnosis(
        family=family,
        shard_count=len(files),
        inverted_ranges=inverted,
        overlapping_pairs=len(overlaps),
        internally_unsorted=unsorted,
        ok=ok,
        samples=tuple(samples),
    )


def diagnose_range_routing(
    root: str | Path,
    *,
    families: Sequence[str] | None = None,
) -> dict[str, RangeRoutingDiagnosis]:
    """Diagnose every present range-routed family under *root*."""

    from .engine import STANDARD_INDEX_PATHS, GraphragEngineError

    release_root = Path(root).expanduser().resolve()
    selected = tuple(families) if families is not None else tuple(RANGE_ROUTED_FAMILIES)
    reports: dict[str, RangeRoutingDiagnosis] = {}
    for family in selected:
        if family not in STANDARD_INDEX_PATHS:
            raise GraphragEngineError(f"unknown GraphRAG family: {family}")
        data_dir, _index_path, key_fields = STANDARD_INDEX_PATHS[family]
        family_dir = release_root / data_dir
        if not family_dir.is_dir():
            continue
        files = list_family_parquet_files(release_root, data_dir)
        reports[family] = diagnose_family_files(
            files, family=family, key_fields=key_fields
        )
    return reports


def _pack_groups(
    grouped: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
    *,
    max_rows: int,
) -> list[list[dict[str, Any]]]:
    if max_rows < 1 or max_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
        from .engine import GraphragEngineError

        raise GraphragEngineError(
            f"max_rows={max_rows} exceeds the {MAX_ROWS_PER_PHYSICAL_SHARD}-row bound"
        )
    shards: list[list[dict[str, Any]]] = []
    pending: list[dict[str, Any]] = []
    for group_key, rows in grouped:
        payload = [dict(row) for row in rows]
        if pending and len(pending) + len(payload) > max_rows:
            shards.append(pending)
            pending = []
        if len(payload) > max_rows:
            from .engine import GraphragEngineError

            raise GraphragEngineError(
                f"group {group_key!r} has {len(payload)} rows; exceeds "
                f"{max_rows}-row shard bound (a range key cannot span shards)"
            )
        pending.extend(payload)
    if pending:
        shards.append(pending)
    return shards


def write_term_sorted_posting_shards(
    rows: Sequence[Mapping[str, Any]],
    dest_dir: str | Path,
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    document_count: int | None = None,
    document_lengths: Mapping[int, int] | None = None,
) -> list[Path]:
    """Write nested BM25 cells as globally term-sorted, disjoint shards.

    Exploded ``(term, document_index, tf)`` hits are nested first. A term's
    cells always stay in one shard so ``first_key``/``last_key`` ranges do
    not overlap.
    """

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    materialised = [dict(row) for row in rows]
    if not materialised:
        from .engine import GraphragEngineError

        raise GraphragEngineError("no posting rows to pack")
    if "document_indices" not in materialised[0]:
        from .engine import nest_exploded_postings

        corpus_size = document_count
        if corpus_size is None:
            indexes = {
                int(row["document_index"])
                for row in materialised
                if row.get("document_index") is not None
            }
            corpus_size = (max(indexes) + 1) if indexes else len(materialised)
        materialised = nest_exploded_postings(
            materialised,
            document_count=corpus_size,
            document_lengths=document_lengths,
        )
    materialised.sort(key=posting_cell_sort_key)
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    current_term = ""
    current_rows: list[dict[str, Any]] = []
    for row in materialised:
        term = str(row.get("term") or "")
        if not term:
            from .engine import GraphragEngineError

            raise GraphragEngineError("posting cell is missing term")
        if current_rows and term != current_term:
            grouped.append((current_term, current_rows))
            current_rows = []
        current_term = term
        current_rows.append(row)
    if current_rows:
        grouped.append((current_term, current_rows))
    written: list[Path] = []
    for shard_id, shard in enumerate(_pack_groups(grouped, max_rows=max_rows)):
        path = dest / part_filename(shard_id)
        write_zstd_parquet(
            path,
            shard,
            max_rows=max_rows,
            config=ArtifactWriterConfig(max_rows_per_shard=max_rows),
        )
        written.append(path)
    return written


def _tie_tuple(row: Mapping[str, Any], fields: Sequence[str]) -> tuple[Any, ...]:
    values: list[Any] = []
    for name in fields:
        if name not in row:
            continue
        value = row[name]
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float, str)):
            values.append(value)
    docs = row.get("document_indices")
    if not values and isinstance(docs, Sequence) and docs:
        values.append(int(docs[0]))
    return tuple(values)


def _build_row_index(
    files: Sequence[Path],
    *,
    key_fields: Sequence[str],
    group_field: str | None,
    tie_fields: Sequence[str],
) -> list[_RowPointer]:
    plan = _repair_pool_plan()
    batch = max(8, math.ceil(len(files) / max(1, plan.workers * 4)))
    payloads: list[dict[str, Any]] = []
    for start in range(0, len(files), batch):
        group = files[start : start + batch]
        payloads.append(
            {
                "group_field": group_field,
                "key_fields": tuple(key_fields),
                "paths": [str(path) for path in group],
                "start_index": start,
                "tie_fields": tuple(tie_fields),
            }
        )
    _log(
        f"  index files={len(files)} batches={len(payloads)} "
        f"workers={plan.workers} reason={plan.reason}"
    )
    pointers: list[_RowPointer] = []
    for part in ordered_process_map(
        _index_file_batch,
        payloads,
        plan=plan,
        per_task_budget=REPAIR_BYTES_PER_WORKER,
    ):
        pointers.extend(part)
        _log(f"  index rows={len(pointers)}")
    pointers.sort(key=lambda item: (item.key, item.tie, item.file_index, item.row_index))
    return pointers


def _assign_term_atomic_shards(
    pointers: Sequence[_RowPointer],
    *,
    max_rows: int,
    group_atomic: bool,
) -> list[list[_RowPointer]]:
    if not group_atomic:
        return [
            list(pointers[index : index + max_rows])
            for index in range(0, len(pointers), max_rows)
        ]
    grouped: list[tuple[str, list[_RowPointer]]] = []
    current = ""
    bucket: list[_RowPointer] = []
    for item in pointers:
        if bucket and item.group != current:
            grouped.append((current, bucket))
            bucket = []
        current = item.group
        bucket.append(item)
    if bucket:
        grouped.append((current, bucket))
    shards: list[list[_RowPointer]] = []
    pending: list[_RowPointer] = []
    for group_key, group in grouped:
        if pending and len(pending) + len(group) > max_rows:
            shards.append(pending)
            pending = []
        if len(group) > max_rows:
            from .engine import GraphragEngineError

            raise GraphragEngineError(
                f"group {group_key!r} has {len(group)} rows; exceeds "
                f"{max_rows}-row shard bound (a range key cannot span shards)"
            )
        pending.extend(group)
    if pending:
        shards.append(pending)
    return shards


class _TableCache:
    def __init__(self, files: Sequence[Path], *, max_open: int = 32) -> None:
        self._files = list(files)
        self._max_open = max(1, max_open)
        self._cache: OrderedDict[int, Any] = OrderedDict()

    def take(self, file_index: int, row_indices: Sequence[int]) -> list[dict[str, Any]]:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = self._cache.get(file_index)
        if table is None:
            table = pq.read_table(self._files[file_index], memory_map=True)
            self._cache[file_index] = table
            if len(self._cache) > self._max_open:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(file_index)
        taken = table.take(pa.array(list(row_indices), type=pa.int32()))
        return taken.to_pylist()


def _materialize_shard(
    pointers: Sequence[_RowPointer],
    cache: _TableCache,
) -> list[dict[str, Any]]:
    by_file: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for out_index, pointer in enumerate(pointers):
        by_file[pointer.file_index].append((out_index, pointer.row_index))
    rows: list[dict[str, Any] | None] = [None] * len(pointers)
    for file_index, pairs in by_file.items():
        local = [row_index for _, row_index in pairs]
        fetched = cache.take(file_index, local)
        for (out_index, _), row in zip(pairs, fetched):
            rows[out_index] = row
    missing = [index for index, row in enumerate(rows) if row is None]
    if missing:
        from .engine import GraphragEngineError

        raise GraphragEngineError(f"failed to materialize shard rows {missing[:8]}")
    return [dict(row) for row in rows if row is not None]


def _is_exploded_postings(path: Path) -> bool:
    import pyarrow.parquet as pq

    names = set(pq.ParquetFile(path).schema_arrow.names)
    return "term" in names and "document_indices" not in names


def _document_count_for_root(root: Path) -> int | None:
    manifest = root / "manifest.json"
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping):
            counts = payload.get("counts") if isinstance(payload.get("counts"), Mapping) else {}
            for key in ("corpus_rows", "document_count", "documents"):
                value = counts.get(key) if counts else payload.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
            bm25 = payload.get("bm25") if isinstance(payload.get("bm25"), Mapping) else {}
            value = bm25.get("document_count") if bm25 else None
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    import pyarrow.parquet as pq

    for relative in ("data/bm25/documents", "data/corpus"):
        folder = root / relative
        if not folder.is_dir():
            continue
        total = 0
        for path in folder.glob("*.parquet"):
            if path.name in SIDECAR_PARQUET_NAMES:
                continue
            total += int(pq.ParquetFile(path).metadata.num_rows)
        if total > 0:
            return total
    return None


def _rewrite_exploded_postings(
    files: Sequence[Path],
    dest: Path,
    *,
    max_rows: int,
    document_count: int | None,
    document_lengths: Mapping[int, int] | None,
) -> int:
    from .engine import nest_exploded_postings

    pointers = _build_row_index(
        files,
        key_fields=("term",),
        group_field="term",
        tie_fields=("document_index", "legal_id", "entry_cid"),
    )
    cache = _TableCache(files)
    grouped: list[tuple[str, list[_RowPointer]]] = []
    current = ""
    bucket: list[_RowPointer] = []
    for item in pointers:
        if bucket and item.group != current:
            grouped.append((current, bucket))
            bucket = []
        current = item.group
        bucket.append(item)
    if bucket:
        grouped.append((current, bucket))
    cells: list[dict[str, Any]] = []
    inferred = document_count
    if inferred is None:
        inferred = 1
    for _term, group in grouped:
        hits = _materialize_shard(group, cache)
        cells.extend(
            nest_exploded_postings(
                hits,
                document_count=inferred,
                document_lengths=document_lengths,
            )
        )
    written = write_term_sorted_posting_shards(
        cells,
        dest,
        max_rows=max_rows,
        document_count=inferred,
        document_lengths=document_lengths,
    )
    return len(written)


def pack_range_routed_family(
    root: str | Path,
    family: str,
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    document_count: int | None = None,
    document_lengths: Mapping[int, int] | None = None,
) -> int:
    """Build-time alias of :func:`rewrite_range_routed_family`.

    Domain builders dump unsorted shards, then call this so keyword/CID
    locators are globally sorted with disjoint ranges. Repair of an
    already-packed release uses the same function.
    """

    return rewrite_range_routed_family(
        root,
        family,
        max_rows=max_rows,
        document_count=document_count,
        document_lengths=document_lengths,
    )


def rewrite_range_routed_family(
    root: str | Path,
    family: str,
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    document_count: int | None = None,
    document_lengths: Mapping[int, int] | None = None,
) -> int:
    """Globally sort *family* shards into disjoint key ranges and replace them."""

    from .engine import STANDARD_INDEX_PATHS, GraphragEngineError

    if family not in STANDARD_INDEX_PATHS:
        raise GraphragEngineError(f"unknown GraphRAG family: {family}")
    release_root = Path(root).expanduser().resolve()
    data_dir, _index_path, key_fields = STANDARD_INDEX_PATHS[family]
    files = list_family_parquet_files(release_root, data_dir)
    if not files:
        raise GraphragEngineError(f"no parquet shards under {release_root / data_dir}")

    with atomic_staging(release_root) as session:
        staged_dir = session.confine(data_dir)
        staged_dir.mkdir(parents=True, exist_ok=True)
        if family == "bm25_postings" and _is_exploded_postings(files[0]):
            count = document_count or _document_count_for_root(release_root)
            _rewrite_exploded_postings(
                files,
                staged_dir,
                max_rows=max_rows,
                document_count=count,
                document_lengths=document_lengths,
            )
        else:
            group_field = GROUP_KEY_BY_FAMILY.get(family)
            pointers = _build_row_index(
                files,
                key_fields=key_fields,
                group_field=group_field,
                tie_fields=TIE_FIELDS_BY_FAMILY.get(family, ()),
            )
            try:
                shards = _assign_term_atomic_shards(
                    pointers,
                    max_rows=max_rows,
                    group_atomic=group_field is not None,
                )
            except GraphragEngineError as exc:
                if family != "bm25_postings" or "cannot span shards" not in str(exc):
                    raise
                count = document_count or _document_count_for_root(release_root)
                _log(f"  re-nest {family}: {exc}")
                _rewrite_exploded_postings(
                    files,
                    staged_dir,
                    max_rows=max_rows,
                    document_count=count,
                    document_lengths=document_lengths,
                )
                shards = []
            if shards:
                plan = _repair_pool_plan()
                batch = max(1, math.ceil(len(shards) / max(1, plan.workers * 4)))
                payloads: list[dict[str, Any]] = []
                for start in range(0, len(shards), batch):
                    group = shards[start : start + batch]
                    needed = sorted(
                        {
                            pointer.file_index
                            for shard in group
                            for pointer in shard
                        }
                    )
                    remap = {old: new for new, old in enumerate(needed)}
                    payloads.append(
                        {
                            "files": [str(files[index]) for index in needed],
                            "max_rows": max_rows,
                            "shards": [
                                {
                                    "dest": str(staged_dir / part_filename(start + offset)),
                                    "pairs": [
                                        (remap[pointer.file_index], pointer.row_index)
                                        for pointer in shard
                                    ],
                                    "shard_id": start + offset,
                                }
                                for offset, shard in enumerate(group)
                            ],
                        }
                    )
                _log(
                    f"  rewrite {family} files={len(files)} shards={len(shards)} "
                    f"batches={len(payloads)} workers={plan.workers} reason={plan.reason}"
                )
                written = 0
                for count in ordered_process_map(
                    _write_shard_batch,
                    payloads,
                    plan=plan,
                    per_task_budget=REPAIR_BYTES_PER_WORKER,
                ):
                    written += int(count)
                    _log(f"  write {family} {written}/{len(shards)}")
        session.commit_tree(data_dir, overwrite=True)
        _log(f"  swapped {family} -> {data_dir}")
    return len(list_family_parquet_files(release_root, data_dir))


def repair_graphrag_range_routing(
    root: str | Path,
    *,
    families: Sequence[str] | None = None,
    force: bool = False,
    document_count: int | None = None,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> dict[str, RangeRepairResult]:
    """Rewrite unsorted/overlapping range-routed families and refresh locators.

    Families that already have internally sorted, disjoint ranges are left
    in place unless *force* is true. Compact indexes are always rewritten
    for families this function touches.
    """

    from .engine import STANDARD_INDEX_PATHS, GraphragEngineError, write_standard_compact_indexes

    release_root = Path(root).expanduser().resolve()
    selected = tuple(families) if families is not None else tuple(
        family
        for family in RANGE_ROUTED_FAMILIES
        if family in STANDARD_INDEX_PATHS
        and (release_root / STANDARD_INDEX_PATHS[family][0]).is_dir()
    )
    reports = diagnose_range_routing(release_root, families=selected)
    results: dict[str, RangeRepairResult] = {}
    rewritten_families: list[str] = []
    for family in selected:
        before = reports.get(family)
        if before is None:
            continue
        needs_rewrite = force or not before.ok
        shard_count = before.shard_count
        _log(
            f"{family}: shards={before.shard_count} inverted={before.inverted_ranges} "
            f"unsorted={before.internally_unsorted} overlap={before.overlapping_pairs} "
            f"ok={before.ok} rewrite={needs_rewrite}"
        )
        if needs_rewrite:
            shard_count = rewrite_range_routed_family(
                release_root,
                family,
                document_count=document_count,
                max_rows=max_rows,
            )
            rewritten_families.append(family)
        after = diagnose_range_routing(release_root, families=(family,))[family]
        if not after.ok:
            raise GraphragEngineError(
                f"{family} still has overlapping or unsorted locator ranges "
                f"after repair: {after.to_dict()}"
            )
        data_dir, index_path, _keys = STANDARD_INDEX_PATHS[family]
        results[family] = RangeRepairResult(
            family=family,
            rewritten=needs_rewrite,
            diagnosis_before=before,
            diagnosis_after=after,
            shard_count=shard_count,
            index_path=index_path,
        )
    # Refresh locators for every selected family so a partial prior run
    # cannot leave sorted data behind a stale compact index.
    index_families = tuple(
        family
        for family in selected
        if (release_root / STANDARD_INDEX_PATHS[family][0]).is_dir()
    )
    if index_families:
        written = write_standard_compact_indexes(
            release_root,
            families=index_families,
            validate=True,
            repair=False,
        )
        _update_manifest_indexes(release_root, written)
        for family, result in written.items():
            _log(
                f"  index {family}: rows={result.row_count} "
                f"path={result.index_path}"
            )
    return results


def _update_manifest_indexes(root: Path, written: Mapping[str, Any]) -> None:
    """Keep manifest sha256/cid in lockstep with rewritten compact indexes."""

    path = root / "manifest.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    index_aliases = {
        "bm25_postings": ("bm25_postings", "bm25_keyword_shards", "bm25_keyword_index"),
        "corpus": ("corpus", "corpus_chunks"),
        "bm25_documents": ("bm25_documents", "bm25_document_chunks"),
        "graph_nodes": ("graph_nodes", "graph_node_chunks"),
        "graph_edges": ("graph_edges", "graph_edge_chunks"),
        "vectors": ("vectors", "vector_chunks"),
        "graph_outgoing_adjacency": ("graph_outgoing_adjacency",),
        "graph_incoming_adjacency": ("graph_incoming_adjacency",),
    }
    indexes = dict(payload.get("indexes") or {})
    counts = dict(payload.get("counts") or {})
    for family, result in written.items():
        descriptor = dict(getattr(result, "descriptor", None) or {})
        if descriptor:
            for key in index_aliases.get(family, (family,)):
                merged = dict(indexes.get(key) or {})
                merged.update(descriptor)
                if "relative_path" not in merged:
                    merged["relative_path"] = getattr(result, "index_path", "")
                indexes[key] = merged
        row_count = int(getattr(result, "row_count", 0) or 0)
        if family == "bm25_postings":
            counts["bm25_posting_shards"] = row_count
        elif family == "corpus":
            counts["corpus_shards"] = row_count
        elif family == "graph_nodes":
            counts["graph_node_shards"] = row_count
    if indexes:
        payload["indexes"] = indexes
    if counts:
        payload["counts"] = counts
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose or repair GraphRAG range-routed shard locators."
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="diagnose",
        choices=("diagnose", "repair"),
        help="diagnose (default) or repair",
    )
    parser.add_argument("root", help="Release root (contains data/ and indexes/)")
    parser.add_argument(
        "--family",
        action="append",
        dest="families",
        default=None,
        help="Limit to one family (repeatable). Default: all range-routed families present.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite even when diagnosis is already ok.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root)
    if args.action == "diagnose":
        reports = diagnose_range_routing(root, families=args.families)
        payload = {name: report.to_dict() for name, report in reports.items()}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if all(report.ok for report in reports.values()) else 1
    results = repair_graphrag_range_routing(
        root, families=args.families, force=args.force
    )
    payload = {name: result.to_dict() for name, result in results.items()}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


__all__ = [
    "GRAPHRAG_BYTES_PER_WORKER",
    "GROUP_KEY_BY_FAMILY",
    "RANGE_ROUTED_FAMILIES",
    "REPAIR_BYTES_PER_WORKER",
    "SIDECAR_PARQUET_NAMES",
    "RangeRepairResult",
    "RangeRoutingDiagnosis",
    "covering_locator_rows",
    "describe_family_files_parallel",
    "diagnose_family_files",
    "diagnose_range_routing",
    "graphrag_process_pool_plan",
    "list_family_parquet_files",
    "pack_range_routed_family",
    "posting_cell_sort_key",
    "repair_graphrag_range_routing",
    "rewrite_range_routed_family",
    "write_term_sorted_posting_shards",
]


if __name__ == "__main__":
    raise SystemExit(_cli())
