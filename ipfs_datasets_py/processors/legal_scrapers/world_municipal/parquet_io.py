"""Parquet I/O for the world municipal-law program.

Mirrors the pilot writers: ZSTD compression when the codec is available,
snappy fallback. One file per jurisdiction: ``{jurisdiction_id}_html.parquet``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

import pyarrow as pa
import pyarrow.parquet as pq

PathLike = Union[str, Path]


def default_compression() -> str:
    """'zstd' when the codec is available, else 'snappy' (pilot behavior)."""
    try:
        if pa.Codec.is_available("zstd"):
            return "zstd"
    except Exception:
        pass
    return "snappy"


def write_html_parquet(
    path: PathLike,
    table: pa.Table,
    *,
    compression: str | None = None,
) -> int:
    """Write a jurisdiction's article table. Returns the row count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression=compression or default_compression())
    return table.num_rows


def read_html_parquet(path: PathLike) -> pa.Table:
    """Read a jurisdiction parquet back to an Arrow table."""
    return pq.read_table(path)


def write_validation_report(path: PathLike, report: Dict[str, Any]) -> None:
    """Write a machine-readable validation.json sidecar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
