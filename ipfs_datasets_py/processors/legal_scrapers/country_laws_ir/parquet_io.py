"""ZSTD parquet shard writer matching skillcenter-huggingface-release/v3."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import MAX_ROWS_PER_FILE, SCHEMA_VERSION
from .cidutil import file_descriptor

COMPRESSION = "zstd"
COMPRESSION_LEVEL = 6


def write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(
        table,
        path,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        row_group_size=min(MAX_ROWS_PER_FILE, max(len(df), 1)),
        use_dictionary=True,
    )


def shard_frames(df: pd.DataFrame, max_rows: int = MAX_ROWS_PER_FILE) -> list[pd.DataFrame]:
    if df.empty:
        return [df.copy()]
    n = int(math.ceil(len(df) / max_rows))
    return [df.iloc[i * max_rows : (i + 1) * max_rows].copy() for i in range(n)]


def write_dataframe_chunked(
    df: pd.DataFrame,
    path: Path,
    rows_per_group: int = 8192,
) -> None:
    """Write *df* without converting the whole frame to one Arrow table.

    ``DataFrame.to_parquet`` copies every column at once. India caselaw was
    SIGKILL'd there: the 8.7M-row frame already used about 67 GiB, and the
    copy asked for more than the host had left.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        write_parquet(path, df)
        return
    schema = pa.Schema.from_pandas(df, preserve_index=False)
    writer: pq.ParquetWriter | None = None
    try:
        for start in range(0, len(df), rows_per_group):
            chunk = df.iloc[start : start + rows_per_group]
            table = pa.Table.from_pandas(
                chunk, schema=schema, preserve_index=False, safe=False
            )
            if writer is None:
                writer = pq.ParquetWriter(
                    path,
                    table.schema,
                    compression=COMPRESSION,
                    compression_level=COMPRESSION_LEVEL,
                    use_dictionary=True,
                )
            writer.write_table(table, row_group_size=max(table.num_rows, 1))
    finally:
        if writer is not None:
            writer.close()


def _iter_shard_frames(df: pd.DataFrame, max_rows: int = MAX_ROWS_PER_FILE):
    """Yield one shard at a time.

    ``shard_frames`` copies every shard into a list first. At France's
    3.6M rows that is a second copy of the corpus and OOMs packaging.
    """
    if df.empty:
        yield df.copy()
        return
    step = max(int(max_rows), 1)
    for start in range(0, len(df), step):
        yield df.iloc[start : start + step].copy()


def write_sharded(
    df: pd.DataFrame,
    out_dir: Path,
    relative_dir: str,
    kind: str,
    key_col: str | None = None,
    index_col: str | None = None,
    extra_index: dict | None = None,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for i, part in enumerate(_iter_shard_frames(df)):
        name = f"part-{i:06d}.parquet"
        path = out_dir / name
        write_parquet(path, part)
        rel = f"{relative_dir}/{name}"
        first_key = last_key = ""
        if key_col and key_col in part.columns and not part.empty:
            keys = part[key_col].astype(str)
            first_key = keys.iloc[0]
            last_key = keys.iloc[-1]
        start_idx = end_idx = 0
        if index_col and index_col in part.columns and not part.empty:
            start_idx = int(part[index_col].iloc[0])
            end_idx = int(part[index_col].iloc[-1])
        desc = file_descriptor(
            path,
            rel,
            extra={
                "shard_id": i,
                "kind": kind,
                "row_count": int(len(part)),
                "first_key": first_key,
                "last_key": last_key,
                "start_document_index": start_idx,
                "end_document_index": end_idx,
                "schema_version": SCHEMA_VERSION,
            },
        )
        if extra_index:
            desc.update(extra_index)
        rows.append(desc)
    return rows


def write_corpus_shards(
    source: Path,
    out_dir: Path,
    relative_dir: str,
    *,
    key_col: str = "entry_cid",
    index_col: str = "document_index",
    max_rows: int = MAX_ROWS_PER_FILE,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Shard a corpus parquet without loading it into one DataFrame.

    France's package step was SIGKILL'd on ``pd.read_parquet`` of the 5.4 GB
    corpus after the graph had already been written.
    """
    import pyarrow.compute as pc

    source = Path(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet = pq.ParquetFile(source)
    names = set(parquet.schema_arrow.names)
    rows: list[dict[str, Any]] = []
    n_laws = 0
    n_articles = 0
    n_rows = 0
    shard_id = 0
    step = max(int(max_rows), 1)
    for batch in parquet.iter_batches(batch_size=step):
        if batch.num_rows == 0:
            continue
        table = pa.Table.from_batches([batch])
        name = f"part-{shard_id:06d}.parquet"
        path = out_dir / name
        pq.write_table(
            table,
            path,
            compression=COMPRESSION,
            compression_level=COMPRESSION_LEVEL,
            row_group_size=max(table.num_rows, 1),
            use_dictionary=True,
        )
        n_rows += table.num_rows
        if "record_type" in names:
            record_type = table.column("record_type")
            n_laws += int(pc.sum(pc.equal(record_type, "law")).as_py() or 0)
            n_articles += int(pc.sum(pc.equal(record_type, "article")).as_py() or 0)
        first_key = last_key = ""
        if key_col in names and table.num_rows:
            keys = table.column(key_col).to_pylist()
            first_key = "" if keys[0] is None else str(keys[0])
            last_key = "" if keys[-1] is None else str(keys[-1])
        start_idx = end_idx = 0
        if index_col in names and table.num_rows:
            indexes = table.column(index_col).to_pylist()
            start_idx = int(indexes[0] or 0)
            end_idx = int(indexes[-1] or 0)
        rel = f"{relative_dir}/{name}"
        rows.append(
            file_descriptor(
                path,
                rel,
                extra={
                    "shard_id": shard_id,
                    "kind": "corpus",
                    "row_count": int(table.num_rows),
                    "first_key": first_key,
                    "last_key": last_key,
                    "start_document_index": start_idx,
                    "end_document_index": end_idx,
                    "schema_version": SCHEMA_VERSION,
                },
            )
        )
        shard_id += 1
    return rows, {"n_rows": n_rows, "n_laws": n_laws, "n_articles": n_articles}
