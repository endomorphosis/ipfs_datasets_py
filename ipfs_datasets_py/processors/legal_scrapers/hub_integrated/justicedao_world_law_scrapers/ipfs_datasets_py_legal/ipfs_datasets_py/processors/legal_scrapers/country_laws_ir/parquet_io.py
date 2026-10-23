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
    shards = shard_frames(df)
    rows: list[dict[str, Any]] = []
    for i, part in enumerate(shards):
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
