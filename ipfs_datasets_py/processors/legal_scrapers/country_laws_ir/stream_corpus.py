"""Normalize a large laws parquet without holding the whole table in RAM.

Municipal ordinances (13.4M rows) and world caselaw (24.9M rows) were
SIGKILL'd inside ``build_corpus`` after ``pd.read_parquet`` of the source.
This path normalizes row batches, spills them, then sorts and dedupes
using the same instrument and article order as ``build_corpus``. Ordering
is an external merge of key columns. A DuckDB window over those keys pinned
its memory limit and died on the municipal corpus.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .reconstruct import article_sort_key
from .vectors import STREAM_LAYOUT_MIN_ROWS

# Source tables at or above this row count are not loaded as one DataFrame.
STREAM_SOURCE_MIN_ROWS = 1_000_000


def article_sort_key_hex(article_number: str, source_id: str) -> str:
    """Hex key whose lexicographic order matches ``article_sort_key``."""
    rank, nums, rest, sid = article_sort_key(article_number or "", source_id or "")
    parts = [bytes([int(rank)])]
    if int(rank) == 1:
        for number in nums:
            parts.append(b"\x01")
            parts.append(int(number).to_bytes(8, "big", signed=False))
        parts.append(b"\x00")
    rest_bytes = str(rest or "").replace("\x00", "").encode("utf-8")
    sid_bytes = str(sid or "").replace("\x00", "").encode("utf-8")
    parts.append(rest_bytes)
    parts.append(b"\x00")
    parts.append(sid_bytes)
    return b"".join(parts).hex()


def oversized_local_laws(local_dir: str | None) -> Path | None:
    """Return a laws parquet that must be streamed, or None."""
    if not local_dir:
        return None
    root = Path(local_dir)
    laws = None
    for cand in (root / "data" / "laws.parquet", root / "laws.parquet"):
        if cand.is_file():
            laws = cand
            break
    if laws is None:
        return None
    for cand in (root / "data" / "articles.parquet", root / "articles.parquet"):
        if not cand.is_file():
            continue
        try:
            if pq.ParquetFile(cand).metadata.num_rows > 0:
                return None
        except Exception:
            return None
    try:
        rows = int(pq.ParquetFile(laws).metadata.num_rows)
    except Exception:
        return None
    if rows < STREAM_SOURCE_MIN_ROWS:
        return None
    return laws


def source_meta_from_pack(local_dir: Path, laws_path: Path) -> dict[str, Any]:
    """Source metadata without reading the laws table into memory."""
    import json

    from .cidutil import sha256_file

    local_dir = Path(local_dir)
    laws_path = Path(laws_path)
    pack_meta: dict[str, Any] = {}
    meta_path = local_dir / "pack_meta.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                pack_meta = loaded
        except Exception:
            pack_meta = {}
    parquet = pq.ParquetFile(laws_path)
    source_dataset = (
        pack_meta.get("source_dataset")
        or pack_meta.get("repo")
        or f"local/{local_dir.name}"
    )
    source_revision = str(
        pack_meta.get("source_revision")
        or pack_meta.get("revision")
        or f"local:{local_dir.name}"
    )
    return {
        "source_dataset": source_dataset,
        "source_revision": source_revision,
        "laws_path": str(laws_path),
        "articles_path": None,
        "laws_sha256": sha256_file(laws_path),
        "articles_sha256": None,
        "n_laws_source": int(parquet.metadata.num_rows),
        "n_articles_source": 0,
        "laws_columns": list(parquet.schema_arrow.names),
        "articles_columns": [],
        "article_count_dtype": None,
        "schema_surprises": [],
        "local_source_dir": str(local_dir),
        "pack_meta": pack_meta,
    }


# Identity columns only. Titles and the other strings stay in the parquet.
# Loading those columns for 26,785,250 municipal rows held about 24 GiB, and
# the following full-matrix copy was what the kernel killed.
_SLIM_FRAME_COLUMNS = (
    "entry_cid",
    "document_index",
)


def load_corpus_frame(path: Path) -> pd.DataFrame:
    """Load a corpus, leaving bodies in the parquet when the table is large."""
    path = Path(path)
    parquet = pq.ParquetFile(path)
    if int(parquet.metadata.num_rows) < STREAM_LAYOUT_MIN_ROWS:
        return pd.read_parquet(path)
    names = set(parquet.schema_arrow.names)
    columns = [name for name in _SLIM_FRAME_COLUMNS if name in names]
    if "entry_cid" not in columns:
        columns = [name for name in parquet.schema_arrow.names if name != "body"]
    frame = pd.read_parquet(path, columns=columns)
    frame.attrs["body_parquet"] = str(path)
    return frame


def _release_native_heap() -> None:
    """Return DuckDB's allocator pages before the embedding matrix is created."""
    import gc

    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        return


def _duckdb_rows(sql: str, params: list[Any] | None = None) -> list[tuple]:
    """Run one aggregate, then close it. An uncapped pool stayed in RSS."""
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='8GB'")
        con.execute("SET threads=2")
        con.execute("SET preserve_insertion_order=false")
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()
        _release_native_heap()


def _merge_drop(report: dict[str, Any], part: dict[str, Any]) -> None:
    drops = report["drops"]
    samples = report["drop_samples"]
    for key, count in (part.get("drops") or {}).items():
        drops[key] = int(drops.get(key) or 0) + int(count or 0)
        bucket = samples.setdefault(key, [])
        for sample in (part.get("drop_samples") or {}).get(key) or []:
            if len(bucket) >= 20:
                break
            bucket.append(sample)
    for key in (
        "n_reconstructed_parents",
        "n_reconstructed_truncated",
        "n_reconstructed_stubs",
        "n_empty_parents_with_articles_not_reconstructed",
        "n_thin_instruments_replaced",
    ):
        report[key] = int(report.get(key) or 0) + int(part.get(key) or 0)
    if part.get("unit") == "structured":
        report["unit"] = "structured"
    for note in part.get("schema_surprises") or []:
        if note not in report["schema_surprises"]:
            report["schema_surprises"].append(note)


def _verify_streamed(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    import duckdb

    from .structure import has_html_tags
    from .verify import (
        Check,
        check_empty_parents_reconstructed,
        check_heading_language,
        check_no_invented_text,
        check_parent_laws,
    )

    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    names = set(pq.ParquetFile(path).schema_arrow.names)
    hierarchy_expr = (
        "count(*) FILTER (WHERE hierarchy_path IS NOT NULL AND length(CAST(hierarchy_path AS VARCHAR)) > 0)"
        if "hierarchy_path" in names
        else "0"
    )
    stats = con.execute(
        f"""
        SELECT
          count(*) AS n,
          count(entry_cid) AS present,
          count(DISTINCT entry_cid) AS distinct_n,
          count(*) FILTER (
            WHERE entry_cid IS NULL OR length(trim(CAST(entry_cid AS VARCHAR))) = 0
          ) AS empty_cid,
          count(*) FILTER (WHERE record_type = 'law') AS n_laws,
          count(*) FILTER (WHERE record_type IN ('article', 'section')) AS n_children,
          {hierarchy_expr} AS n_hierarchy
        FROM read_parquet(?)
        """,
        [str(path)],
    ).fetchone()
    n = int(stats[0])
    present = int(stats[1])
    distinct_n = int(stats[2])
    empty_cid = int(stats[3])
    n_laws = int(stats[4])
    n_children = int(stats[5])
    n_hierarchy = int(stats[6])
    missing = n - present
    dupes = n - distinct_n
    cid_ok = n > 0 and missing == 0 and dupes == 0 and empty_cid == 0
    tagged = 0
    short = 0
    tag_samples: list[str] = []
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=4096, columns=["body"]):
        for value in batch.column(0).to_pylist():
            body = str(value or "")
            if len(body) < 40:
                short += 1
            if has_html_tags(body):
                tagged += 1
                if len(tag_samples) < 5:
                    tag_samples.append(body[:120])
    html_fraction = tagged / float(n or 1)
    short_fraction = short / float(n or 1)
    html_ok = html_fraction <= 0.02
    short_ok = n > 0 and short_fraction <= 0.50
    report["n_law_rows"] = n_laws
    report["n_child_rows"] = n_children
    if n_laws and n_children:
        report["unit"] = "law+structured" if report.get("unit") == "structured" else "law+article"
    elif n_laws:
        report["unit"] = "law"
    elif n_children:
        report["unit"] = "article"
    structured_rows = max(n_children, n_hierarchy)
    coverage = structured_rows / float(n) if n else 0.0
    unit = str(report.get("unit") or "")
    if unit in {"article", "structured", "law+article", "law+structured"} or coverage >= 0.5:
        structure = Check(
            id="legal_structure",
            severity="warn",
            passed=True,
            message=f"retrieval units are structured ({unit}, coverage={coverage:.2f})",
            evidence={"unit": unit, "structured_rows": structured_rows, "coverage": coverage},
        )
    else:
        structure = Check(
            id="legal_structure",
            severity="warn",
            passed=True,
            message=(
                "kept whole-instrument units; no title/article/section headings detected "
                "(expected for some gazettes)"
            ),
            evidence={"unit": unit, "structured_rows": structured_rows, "coverage": coverage},
        )
    checks = [
        Check(
            id="nonempty_corpus",
            severity="fail",
            passed=n > 0,
            message="normalized corpus has rows" if n else "normalized corpus is empty",
            evidence={"n_out": n, "n_dropped": report.get("n_dropped_total")},
        ),
        Check(
            id="entry_cid_unique",
            severity="fail",
            passed=cid_ok,
            message="every row has a unique entry_cid" if cid_ok else "missing or duplicate entry_cid",
            evidence={"missing": missing, "empty": empty_cid, "duplicate": dupes},
        ),
        check_no_invented_text(report),
        Check(
            id="html_residual",
            severity="fail",
            passed=html_ok,
            message=(
                "HTML tags stripped from legal bodies"
                if html_ok
                else f"{tagged}/{n} bodies still contain HTML tags"
            ),
            evidence={
                "n_bodies": n,
                "n_with_tags": tagged,
                "fraction": html_fraction,
                "samples": tag_samples,
            },
        ),
        Check(
            id="short_bodies",
            severity="fail" if not short_ok else "warn",
            passed=short_ok,
            message=(
                "most legal units have usable body length"
                if short_ok
                else f"{short}/{n} bodies shorter than 40 characters"
            ),
            evidence={"n_short": short, "n_bodies": n, "fraction": short_fraction},
        ),
        Check(
            id="reconstruction_grounded",
            severity="fail",
            passed=int(report.get("n_reconstructed_parents") or 0) == 0,
            message="streamed laws path did not reconstruct parents from articles",
            evidence={"n_reconstructed_parents": int(report.get("n_reconstructed_parents") or 0)},
        ),
        check_empty_parents_reconstructed(report),
        check_parent_laws(pd.DataFrame(), report),
        structure,
        check_heading_language(pd.DataFrame(), report),
    ]
    failed = [item for item in checks if item.severity == "fail" and not item.passed]
    con.close()
    _release_native_heap()
    return {
        "schema_version": "country-laws-normalize-verify/v1",
        "slug": "",
        "admitted": not failed,
        "n_checks": len(checks),
        "n_failed": len(failed),
        "failed_ids": [item.id for item in failed],
        "checks": [item.to_dict() for item in checks],
        "blocks_graphrag": bool(failed),
    }


def _output_schema(part_path: Path):
    """Corpus schema written by the sort: spill columns except ``sort_key``."""
    import pyarrow as pa

    schema = pq.ParquetFile(part_path).schema_arrow
    fields = [schema.field(name) for name in schema.names if name != "sort_key"]
    fields.append(pa.field("document_index", pa.int64()))
    fields.append(pa.field("corpus_index", pa.int64()))
    return pa.schema(fields)


def _write_sort_keys(parts: Path, keys_dir: Path) -> int:
    """Project identity columns so the sort never reads a body."""
    import numpy as np
    import pyarrow as pa

    keys_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in sorted(parts.glob("part-*.parquet")):
        part_id = int(path.stem.split("-", 1)[1])
        table = pq.read_table(
            path,
            columns=["entry_cid", "instrument_id", "sort_key", "source_id"],
        )
        nrows = int(table.num_rows)
        if nrows == 0:
            continue
        table = table.append_column(
            "part_id",
            pa.array(np.full(nrows, part_id, dtype=np.int32)),
        )
        table = table.append_column(
            "row_in_file",
            pa.array(np.arange(nrows, dtype=np.int32)),
        )
        pq.write_table(table, keys_dir / f"keys-{part_id:05d}.parquet", compression="zstd")
        written += nrows
        del table
    return written


# One sorted run stays small enough to order in process. The merge, not a
# window, is what orders the municipal and caselaw key tables.
_RUN_ROWS = 100_000
_MERGE_FANIN = 64
_WINNER_CHUNK_ROWS = 200_000
_KEY_BATCH = 4_096
_KEY_COLUMNS = (
    "entry_cid",
    "instrument_id",
    "sort_key",
    "source_id",
    "part_id",
    "row_in_file",
)
_WINNER_COLUMNS = ("instrument_id", "sort_key", "part_id", "row_in_file")


def _order_value(value: Any) -> tuple[Any, ...]:
    """NULL sorts last. Strings stay strings so '10' does not become a number."""
    if value is None:
        return (2, "")
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return (0, value)
    return (1, value)


def _dedupe_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """entry_cid, then the same order build_corpus uses, then spill position."""
    return (
        _order_value(row[0]),
        _order_value(row[1]),
        _order_value(row[2]),
        int(row[4]),
        int(row[5]),
    )


def _doc_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """Winner row ordered as instrument_id, sort_key, part_id, row_in_file."""
    return (
        _order_value(row[0]),
        _order_value(row[1]),
        int(row[2]),
        int(row[3]),
    )


def _write_row_batches(path: Path, schema, rows) -> None:
    """Write rows in batches. ``rows`` may be a list or a generator."""
    import pyarrow as pa

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    buf: list[tuple[Any, ...]] = []

    def flush() -> None:
        nonlocal writer
        if not buf:
            return
        arrays = [
            pa.array([row[i] for row in buf], type=field.type)
            for i, field in enumerate(schema)
        ]
        table = pa.Table.from_arrays(arrays, schema=schema)
        if writer is None:
            writer = pq.ParquetWriter(path, schema, compression="zstd")
        writer.write_table(table)
        buf.clear()

    try:
        for row in rows:
            buf.append(row)
            if len(buf) >= 65_536:
                flush()
        flush()
        if writer is None:
            writer = pq.ParquetWriter(path, schema, compression="zstd")
        writer.close()
    except Exception:
        if writer is not None:
            writer.close()
        path.unlink(missing_ok=True)
        raise


class _RunCursor:
    """One sorted parquet run. The heap only holds the current key."""

    def __init__(self, seq: int, path: Path, key_fn, columns: tuple[str, ...]) -> None:
        self.seq = seq
        self._key_fn = key_fn
        self._iter = pq.ParquetFile(path).iter_batches(
            batch_size=_KEY_BATCH,
            columns=list(columns),
        )
        self.rows: list[tuple[Any, ...]] = []
        self.pos = 0
        self.row: tuple[Any, ...] | None = None
        self.key: tuple[Any, ...] | None = None
        self._pull()

    def _pull(self) -> None:
        while True:
            try:
                batch = next(self._iter)
            except StopIteration:
                self.rows = []
                self.row = None
                self.key = None
                return
            if batch.num_rows == 0:
                continue
            cols = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
            self.rows = list(zip(*cols))
            self.pos = 0
            self.row = self.rows[0]
            self.key = self._key_fn(self.row)
            return

    def advance(self) -> bool:
        self.pos += 1
        if self.pos >= len(self.rows):
            self._pull()
            return self.row is not None
        self.row = self.rows[self.pos]
        self.key = self._key_fn(self.row)
        return True


def _merge_runs(paths: list[Path], key_fn, columns: tuple[str, ...]):
    """Yield rows from sorted runs in key order. Fan-in is the open-file bound."""
    import heapq

    heap: list[tuple[Any, int, _RunCursor]] = []
    for seq, path in enumerate(paths):
        cursor = _RunCursor(seq, path, key_fn, columns)
        if cursor.row is not None and cursor.key is not None:
            heapq.heappush(heap, (cursor.key, seq, cursor))
    while heap:
        _key, seq, cursor = heapq.heappop(heap)
        row = cursor.row
        if row is None:
            continue
        if cursor.advance() and cursor.key is not None:
            heapq.heappush(heap, (cursor.key, seq, cursor))
        yield row


def _collapse_runs(
    paths: list[Path],
    key_fn,
    columns: tuple[str, ...],
    schema,
    dest_dir: Path,
) -> list[Path]:
    """Merge until every remaining run fits in one k-way pass."""
    if len(paths) <= _MERGE_FANIN:
        return paths
    dest_dir.mkdir(parents=True, exist_ok=True)
    merged: list[Path] = []
    for start in range(0, len(paths), _MERGE_FANIN):
        group = paths[start : start + _MERGE_FANIN]
        out = dest_dir / f"m-{len(merged):05d}.parquet"
        _write_row_batches(out, schema, _merge_runs(group, key_fn, columns))
        merged.append(out)
    return _collapse_runs(merged, key_fn, columns, schema, dest_dir / "next")


def _sorted_key_runs(keys_dir: Path, run_dir: Path) -> tuple[list[Path], Any]:
    """Sort each key file in bounded pieces. Returns runs and their schema."""
    import pyarrow as pa

    paths = sorted(keys_dir.glob("keys-*.parquet"))
    if not paths:
        from .schema import SchemaError

        raise SchemaError(f"no sort keys in {keys_dir}")
    full = pq.read_schema(paths[0])
    schema = pa.schema([full.field(name) for name in _KEY_COLUMNS])
    run_dir.mkdir(parents=True, exist_ok=True)
    runs: list[Path] = []
    pending: list[tuple[Any, ...]] = []

    def flush() -> None:
        if not pending:
            return
        pending.sort(key=_dedupe_key)
        dest = run_dir / f"run-{len(runs):05d}.parquet"
        _write_row_batches(dest, schema, pending)
        runs.append(dest)
        pending.clear()

    for path in paths:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=_RUN_ROWS, columns=list(_KEY_COLUMNS)):
            cols = [batch.column(i).to_pylist() for i in range(len(_KEY_COLUMNS))]
            rows = list(zip(*cols))
            if pending and len(pending) + len(rows) > _RUN_ROWS:
                flush()
            pending.extend(rows)
            if len(pending) >= _RUN_ROWS:
                flush()
    flush()
    if not runs:
        from .schema import SchemaError

        raise SchemaError(f"sort keys in {keys_dir} were empty")
    return runs, schema


def _window_sort_keys(keys_dir: Path, winners_path: Path, sort_tmp: Path) -> list[Any]:
    """First-wins dedupe on keys. Tie-break is spill order, matching a stable sort.

    DuckDB's window sort keeps the key table and both row_number operators in
    one memory pool. This merge sorts at most ``_RUN_ROWS`` keys at a time,
    then k-way merges those runs twice: once to drop duplicate entry_cids,
    once to number the survivors.
    """
    import pyarrow as pa

    winners_path.unlink(missing_ok=True)
    runs, schema = _sorted_key_runs(keys_dir, sort_tmp / "ext-runs")
    runs = _collapse_runs(runs, _dedupe_key, _KEY_COLUMNS, schema, sort_tmp / "ext-merged")
    samples: list[Any] = []
    chunk_rows: list[tuple[Any, ...]] = []
    chunks: list[Path] = []
    chunk_dir = sort_tmp / "ext-winners"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    winner_schema = pa.schema(
        [
            pa.field("instrument_id", schema.field("instrument_id").type),
            pa.field("sort_key", schema.field("sort_key").type),
            pa.field("part_id", pa.int32()),
            pa.field("row_in_file", pa.int32()),
        ]
    )
    previous: Any = object()

    def flush_chunk() -> None:
        if not chunk_rows:
            return
        chunk_rows.sort(key=_doc_key)
        dest = chunk_dir / f"w-{len(chunks):05d}.parquet"
        _write_row_batches(dest, winner_schema, chunk_rows)
        chunks.append(dest)
        chunk_rows.clear()

    for row in _merge_runs(runs, _dedupe_key, _KEY_COLUMNS):
        cid = row[0]
        if cid == previous:
            if len(samples) < 20:
                samples.append(row[3])
            continue
        previous = cid
        chunk_rows.append((row[1], row[2], int(row[4]), int(row[5])))
        if len(chunk_rows) >= _WINNER_CHUNK_ROWS:
            flush_chunk()
    flush_chunk()
    if not chunks:
        from .schema import SchemaError

        raise SchemaError("external key sort kept no rows")
    ordered = _collapse_runs(
        chunks,
        _doc_key,
        _WINNER_COLUMNS,
        winner_schema,
        sort_tmp / "ext-ordered",
    )
    out_schema = pa.schema(
        [
            pa.field("part_id", pa.int32()),
            pa.field("row_in_file", pa.int32()),
            pa.field("document_index", pa.int64()),
        ]
    )

    def numbered():
        document_index = 0
        for row in _merge_runs(ordered, _doc_key, _WINNER_COLUMNS):
            yield (int(row[2]), int(row[3]), document_index)
            document_index += 1

    _write_row_batches(winners_path, out_schema, numbered())
    return samples


def _write_kept_parts(
    parts: Path,
    winners_path: Path,
    kept_dir: Path,
    schema,
    log=None,
) -> list[Path]:
    """Take winning rows from each spill file, already ordered by document_index."""
    import numpy as np
    import pyarrow as pa

    winners = pq.read_table(winners_path, columns=["part_id", "row_in_file", "document_index"])
    part_ids = np.asarray(winners.column("part_id").to_numpy())
    row_in_file = np.asarray(winners.column("row_in_file").to_numpy())
    document_index = np.asarray(winners.column("document_index").to_numpy())
    del winners
    if part_ids.size == 0:
        return []
    order = np.lexsort((document_index, part_ids))
    part_ids = part_ids[order]
    row_in_file = row_in_file[order]
    document_index = document_index[order]
    changes = np.flatnonzero(np.diff(part_ids)) + 1
    starts = np.concatenate((np.array([0], dtype=np.int64), changes.astype(np.int64)))
    ends = np.concatenate((changes.astype(np.int64), np.array([part_ids.size], dtype=np.int64)))
    base_names = [field.name for field in schema if field.name not in ("document_index", "corpus_index")]
    kept_dir.mkdir(parents=True, exist_ok=True)
    kept: list[Path] = []
    for nth, (start, end) in enumerate(zip(starts, ends)):
        part_id = int(part_ids[start])
        part_path = parts / f"part-{part_id:05d}.parquet"
        table = pq.read_table(part_path)
        if "sort_key" in table.column_names:
            table = table.drop(["sort_key"])
        table = table.select(base_names)
        idx = row_in_file[start:end]
        docs = document_index[start:end]
        taken = table.take(pa.array(np.asarray(idx, dtype=np.int64)))
        doc_arr = pa.array(np.asarray(docs, dtype=np.int64))
        taken = taken.append_column("document_index", doc_arr)
        taken = taken.append_column("corpus_index", doc_arr)
        if taken.schema != schema:
            taken = taken.cast(schema)
        dest = kept_dir / f"kept-{part_id:05d}.parquet"
        pq.write_table(taken, dest, compression="zstd")
        kept.append(dest)
        del table, taken
        if log and (nth + 1) % 50 == 0:
            log(f"stream normalize kept parts={nth + 1}")
    return kept


def _merge_kept_parquets(paths: list[Path], dest: Path, schema) -> None:
    """K-way merge of per-part files that are already ordered by document_index."""
    import heapq

    import pyarrow as pa

    class _Cursor:
        def __init__(self, seq: int, path: Path) -> None:
            self.seq = seq
            self._iter = pq.ParquetFile(path).iter_batches(batch_size=8192)
            self.batch = None
            self.pos = 0
            self.doc: int | None = None
            self._next_batch()

        def _next_batch(self) -> None:
            while True:
                try:
                    batch = next(self._iter)
                except StopIteration:
                    self.batch = None
                    self.doc = None
                    return
                if batch.num_rows == 0:
                    continue
                self.batch = batch
                self.pos = 0
                self.doc = int(batch.column("document_index")[0].as_py())
                return

        def take_until(self, stop: int | None):
            batch = self.batch
            if batch is None or self.doc is None:
                raise RuntimeError("sort cursor is empty")
            col = batch.column("document_index")
            n = batch.num_rows
            if stop is None:
                end = n
            else:
                lo, hi = self.pos, n
                while lo < hi:
                    mid = (lo + hi) // 2
                    if int(col[mid].as_py()) < stop:
                        lo = mid + 1
                    else:
                        hi = mid
                end = max(lo, self.pos + 1)
            piece = batch.slice(self.pos, end - self.pos)
            self.pos = end
            if self.pos >= n:
                self._next_batch()
            else:
                self.doc = int(col[self.pos].as_py())
            if piece.schema != schema:
                piece = pa.record_batch(
                    [piece.column(field.name) for field in schema],
                    schema=schema,
                )
            return piece

    heap: list[tuple[int, int, _Cursor]] = []
    for seq, path in enumerate(paths):
        cursor = _Cursor(seq, path)
        if cursor.doc is not None:
            heapq.heappush(heap, (cursor.doc, seq, cursor))
    if not heap:
        from .schema import SchemaError

        raise SchemaError("streamed normalize kept no rows")
    dest.unlink(missing_ok=True)
    writer = pq.ParquetWriter(dest, schema, compression="zstd")
    pending: list = []
    pending_rows = 0
    try:
        def flush() -> None:
            nonlocal pending_rows
            if not pending:
                return
            writer.write_table(pa.Table.from_batches(pending, schema=schema))
            pending.clear()
            pending_rows = 0

        while heap:
            doc, seq, cursor = heapq.heappop(heap)
            if cursor.doc != doc:
                continue
            stop = heap[0][0] if heap else None
            piece = cursor.take_until(stop)
            pending.append(piece)
            pending_rows += piece.num_rows
            if pending_rows >= 65_536:
                flush()
            if cursor.doc is not None:
                heapq.heappush(heap, (cursor.doc, seq, cursor))
        flush()
        writer.close()
    except Exception:
        writer.close()
        dest.unlink(missing_ok=True)
        raise


def _assert_dense_document_index(path: Path) -> None:
    """document_index is the parquet row order. A gap means the merge dropped a row."""
    import numpy as np

    from .schema import SchemaError

    expect = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=["document_index"]):
        values = np.asarray(batch.column(0).to_numpy())
        if values.size == 0:
            continue
        if int(values[0]) != expect or not np.array_equal(
            values, np.arange(expect, expect + values.size)
        ):
            raise SchemaError(
                f"streamed document_index is not dense at row {expect} "
                f"(saw {int(values[0])}..{int(values[-1])})"
            )
        expect += int(values.size)
    if expect <= 0:
        raise SchemaError(f"streamed normalize wrote no rows to {path}")


def _materialize_sorted_corpus(parts: Path, dest: Path, sort_tmp: Path, log=None) -> list[Any]:
    """Sort spill parts by instrument and article without loading bodies into DuckDB."""
    if sort_tmp.exists():
        shutil.rmtree(sort_tmp)
    sort_tmp.mkdir(parents=True, exist_ok=True)
    keys_dir = sort_tmp / "keys"
    if log:
        log(f"stream normalize writing sort keys from {parts}")
    n_keys = _write_sort_keys(parts, keys_dir)
    if n_keys <= 0:
        from .schema import SchemaError

        raise SchemaError(f"streamed normalize has no sort keys in {parts}")
    if log:
        log(f"stream normalize key window rows={n_keys}")
    winners_path = sort_tmp / "winners.parquet"
    dup_samples = _window_sort_keys(keys_dir, winners_path, sort_tmp)
    shutil.rmtree(keys_dir, ignore_errors=True)
    spill_parts = sorted(parts.glob("part-*.parquet"))
    schema = _output_schema(spill_parts[0])
    if log:
        log("stream normalize taking winning rows")
    kept = _write_kept_parts(parts, winners_path, sort_tmp / "kept", schema, log=log)
    winners_path.unlink(missing_ok=True)
    if log:
        log(f"stream normalize merging {len(kept)} kept parts")
    _merge_kept_parquets(kept, dest, schema)
    _assert_dense_document_index(dest)
    return dup_samples


def stream_laws_corpus(
    laws_path: Path,
    source_meta: dict[str, Any],
    out_path: Path,
    *,
    batch_rows: int = 20_000,
    log=None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Write a deduped corpus parquet and return a frame without the body column."""
    from .normalize import _empty_articles, build_corpus, validate_laws
    from .profiles import majority_language, score_heading_languages
    from .schema import SchemaError

    laws_path = Path(laws_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts = out_path.with_name(out_path.stem + ".stream-parts")
    tmp_out = out_path.with_name(out_path.stem + ".streaming.parquet")
    n_laws = int(source_meta.get("n_laws_source") or 0)
    expected_batches = (n_laws + int(batch_rows) - 1) // int(batch_rows) if n_laws else 0
    existing = sorted(parts.glob("part-*.parquet")) if parts.is_dir() else []
    resume_parts = (
        expected_batches > 0
        and len(existing) == expected_batches
        and existing[0].name == "part-00000.parquet"
        and existing[-1].name == f"part-{expected_batches - 1:05d}.parquet"
    )
    if parts.exists() and not resume_parts:
        shutil.rmtree(parts)
    parts.mkdir(parents=True, exist_ok=True)
    articles = _empty_articles()
    report: dict[str, Any] = {
        "source_dataset": source_meta["source_dataset"],
        "source_revision": source_meta["source_revision"],
        "laws_sha256": source_meta.get("laws_sha256"),
        "articles_sha256": None,
        "n_laws_in": int(source_meta.get("n_laws_source") or 0),
        "n_articles_in": 0,
        "unit": "law",
        "article_law_coverage": 0.0,
        "sparse_article_fallback": False,
        "drops": {
            "empty_body": 0,
            "missing_instrument": 0,
            "duplicate_cid": 0,
            "duplicate_source_kept_first": 0,
        },
        "drop_samples": {"empty_body": [], "missing_instrument": [], "duplicate_cid": []},
        "schema_surprises": list(source_meta.get("schema_surprises") or []),
        "never_invented_legal_text": True,
        "n_reconstructed_parents": 0,
        "n_reconstructed_truncated": 0,
        "n_reconstructed_stubs": 0,
        "n_empty_parents_with_articles_not_reconstructed": 0,
        "n_thin_instruments_replaced": 0,
        "streamed": True,
    }
    parquet = pq.ParquetFile(laws_path)
    validated = False
    part_id = 0
    n_before = 0
    seen_rows = 0
    if log:
        log("stream normalize sorter=external-merge")
    if resume_parts:
        for path in existing:
            n_before += int(pq.ParquetFile(path).metadata.num_rows)
        part_id = len(existing)
        if log:
            log(
                f"stream normalize reusing {part_id} spill batches "
                f"emitted={n_before} from {parts}"
            )
    for batch in parquet.iter_batches(batch_size=int(batch_rows)) if not resume_parts else []:
        frame = batch.to_pandas()
        seen_rows += int(len(frame))
        if frame.empty:
            continue
        if not validated:
            validate_laws(frame)
            validated = True
        partial, partial_report = build_corpus(
            frame,
            articles,
            source_meta,
            defer_dedupe=True,
        )
        _merge_drop(report, partial_report)
        del frame
        if partial.empty:
            continue
        partial["sort_key"] = [
            article_sort_key_hex(
                str(number or ""),
                str(source or ""),
            )
            for number, source in zip(
                partial.get("article_number", pd.Series([""] * len(partial))),
                partial.get("source_id", pd.Series([""] * len(partial))),
            )
        ]
        n_before += int(len(partial))
        partial.to_parquet(parts / f"part-{part_id:05d}.parquet", index=False)
        part_id += 1
        del partial
        if log and (part_id % 25 == 0):
            log(f"stream normalize batches={part_id} source_rows={seen_rows} emitted={n_before}")
    if part_id == 0:
        raise SchemaError(f"streamed normalize emitted no rows from {laws_path}")
    if log:
        log(f"stream normalize sorting emitted={n_before} batches={part_id}")
    sort_tmp = out_path.with_name(out_path.stem + ".stream-tmp")
    dup_samples = _materialize_sorted_corpus(parts, tmp_out, sort_tmp, log=log)
    tmp_out.replace(out_path)
    shutil.rmtree(parts, ignore_errors=True)
    shutil.rmtree(sort_tmp, ignore_errors=True)
    n_out = int(pq.ParquetFile(out_path).metadata.num_rows)
    dropped_dupes = n_before - n_out
    report["drops"]["duplicate_cid"] = int(report["drops"].get("duplicate_cid") or 0) + max(dropped_dupes, 0)
    report["drops"]["duplicate_source_kept_first"] = report["drops"]["duplicate_cid"]
    report["drop_samples"]["duplicate_cid"] = list(dup_samples)
    report["n_before_dedupe"] = n_before
    report["n_out"] = n_out
    report["n_dropped_total"] = (
        int(report["drops"]["empty_body"])
        + int(report["drops"]["missing_instrument"])
        + int(report["drops"]["duplicate_cid"])
    )
    counts = _duckdb_rows(
        f"""
        SELECT language, record_type, jurisdiction, count(*) AS n
        FROM read_parquet('{out_path.as_posix()}')
        GROUP BY 1, 2, 3
        """
    )
    languages: dict[str, int] = {}
    record_types: dict[str, int] = {}
    jurisdictions: dict[str, int] = {}
    for language, record_type, jurisdiction, count in counts:
        count = int(count)
        languages[str(language or "")] = languages.get(str(language or ""), 0) + count
        record_types[str(record_type or "")] = record_types.get(str(record_type or ""), 0) + count
        jurisdictions[str(jurisdiction or "")] = jurisdictions.get(str(jurisdiction or ""), 0) + count
    report["language_breakdown"] = languages
    report["record_type_breakdown"] = record_types
    report["jurisdiction_breakdown"] = jurisdictions
    sample_batch = next(
        pq.ParquetFile(out_path).iter_batches(batch_size=40, columns=["body", "title"])
    )
    sample = sample_batch.to_pandas()
    sample_text = "\n".join(str(x) for x in sample.get("title", pd.Series(dtype=str)).tolist())
    sample_text += "\n" + "\n".join(str(x) for x in sample.get("body", pd.Series(dtype=str)).tolist())
    heading_langs = score_heading_languages(sample_text)
    report["heading_language_counts"] = dict(heading_langs)
    report["heading_language_majority"] = majority_language(heading_langs)
    report["document_language_majority"] = None
    if languages:
        report["document_language_majority"] = max(languages.items(), key=lambda kv: kv[1])[0]
    dates = _duckdb_rows(
        f"""
        SELECT DISTINCT snapshot_date
        FROM read_parquet('{out_path.as_posix()}')
        WHERE snapshot_date IS NOT NULL AND length(CAST(snapshot_date AS VARCHAR)) > 0
        ORDER BY 1
        """
    )
    report["snapshot_dates"] = [str(row[0]) for row in dates]
    report["quality_flags"] = {
        "articles_table_empty": True,
        "sparse_article_fallback": False,
        "article_law_coverage": 0.0,
        "all_source_article_counts_zero": False,
        "article_extraction_status_counts": {},
        "missing_date": False,
        "missing_date_issued": False,
        "eli_present": False,
        "never_invented_legal_text": True,
        "empty_bodies_dropped": report["drops"]["empty_body"],
        "duplicate_cids_dropped": report["drops"]["duplicate_cid"],
    }
    report["verification"] = _verify_streamed(out_path, report)
    if log:
        log(
            f"normalized docs={n_out} unit={report['unit']} "
            f"dropped={report['n_dropped_total']} streamed=true"
        )
    _release_native_heap()
    return load_corpus_frame(out_path), report
