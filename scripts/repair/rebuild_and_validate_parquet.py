#!/usr/bin/env python3
"""Rebuild a dataset into valid parquet shards and run integrity checks.

This script is designed for datasets that need republishing to Hugging Face in a
thin-client friendly parquet layout.

What it does:
1. Loads source rows from parquet/csv/json/jsonl using pyarrow.dataset.
2. Optionally normalizes CID field to string and trims empty CIDs.
3. Writes sharded parquet files to an output directory.
4. Validates each shard with:
   - raw footer/header magic byte check
   - pyarrow parquet reader
   - duckdb SQL query check
5. Emits a JSON validation report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def _infer_format(source: Path) -> str:
    if source.is_dir():
        return "parquet"
    suffix = source.suffix.lower()
    if suffix == ".parquet":
        return "parquet"
    if suffix == ".csv":
        return "csv"
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return "json"
    raise ValueError(f"Unsupported source format for {source}")


def _load_source_table(source: Path, source_format: Optional[str]) -> pa.Table:
    fmt = source_format or _infer_format(source)
    dataset = ds.dataset(str(source), format=fmt)
    return dataset.to_table()


def _normalize_cid_column(table: pa.Table, cid_column: str, drop_empty_cids: bool) -> pa.Table:
    if cid_column not in table.column_names:
        return table

    col = table[cid_column]
    if not pa.types.is_string(col.type):
        col = pc.cast(col, pa.string())
        idx = table.column_names.index(cid_column)
        table = table.set_column(idx, cid_column, col)

    if drop_empty_cids:
        not_null = pc.invert(pc.is_null(table[cid_column]))
        non_empty = pc.greater(pc.utf8_length(table[cid_column]), 0)
        mask = pc.and_(not_null, non_empty)
        table = table.filter(mask)

    return table


def _write_shards(
    table: pa.Table,
    out_dir: Path,
    compression: str,
    max_rows_per_file: int,
    row_group_size: int,
) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    ds.write_dataset(
        data=table,
        base_dir=str(out_dir),
        format="parquet",
        basename_template="part-{i}.parquet",
        existing_data_behavior="overwrite_or_ignore",
        max_rows_per_file=max_rows_per_file,
        max_rows_per_group=row_group_size,
        file_options=ds.ParquetFileFormat().make_write_options(compression=compression),
    )

    return sorted(out_dir.glob("*.parquet"))


def _magic_ok(path: Path) -> Dict[str, Any]:
    with path.open("rb") as f:
        head = f.read(4)
        f.seek(-4, 2)
        tail = f.read(4)
    return {
        "header_hex": head.hex(),
        "footer_hex": tail.hex(),
        "header_ok": head == b"PAR1",
        "footer_ok": tail == b"PAR1",
    }


def _validate_shard(path: Path, cid_column: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"file": str(path), "ok": False}

    magic = _magic_ok(path)
    result.update(magic)

    try:
        pf = pq.ParquetFile(str(path))
        result["num_row_groups"] = pf.num_row_groups
        result["num_rows"] = pf.metadata.num_rows if pf.metadata else None
        result["columns"] = pf.schema.names
    except Exception as exc:  # pragma: no cover - defensive path
        result["parquet_error"] = str(exc)
        return result

    try:
        con = duckdb.connect()
        query = f"SELECT {cid_column} FROM read_parquet('{path}') LIMIT 5"
        rows = con.execute(query).fetchall()
        result["duckdb_sample"] = [r[0] for r in rows]
    except Exception as exc:  # pragma: no cover - defensive path
        result["duckdb_error"] = str(exc)
        return result

    result["ok"] = bool(result["header_ok"] and result["footer_ok"])
    return result


def rebuild_and_validate(
    source: Path,
    out_dir: Path,
    source_format: Optional[str],
    cid_column: str,
    drop_empty_cids: bool,
    compression: str,
    max_rows_per_file: int,
    row_group_size: int,
    report_path: Path,
) -> Dict[str, Any]:
    table = _load_source_table(source=source, source_format=source_format)
    table = _normalize_cid_column(table=table, cid_column=cid_column, drop_empty_cids=drop_empty_cids)

    shards = _write_shards(
        table=table,
        out_dir=out_dir,
        compression=compression,
        max_rows_per_file=max_rows_per_file,
        row_group_size=row_group_size,
    )

    validations = [_validate_shard(path=p, cid_column=cid_column) for p in shards]
    all_ok = all(v.get("ok", False) for v in validations)

    report: Dict[str, Any] = {
        "source": str(source),
        "output_dir": str(out_dir),
        "source_rows": table.num_rows,
        "source_columns": table.column_names,
        "shard_count": len(shards),
        "all_ok": all_ok,
        "shards": validations,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild source data into valid parquet shards and validate them")
    parser.add_argument("--source", required=True, help="Source file/directory (parquet/csv/json/jsonl)")
    parser.add_argument("--out-dir", required=True, help="Output directory for rebuilt parquet shards")
    parser.add_argument("--source-format", default=None, choices=["parquet", "csv", "json"], help="Optional source format override")
    parser.add_argument("--cid-column", default="cid", help="CID column name")
    parser.add_argument("--drop-empty-cids", action="store_true", help="Drop rows where CID is null/empty")
    parser.add_argument("--compression", default="zstd", choices=["zstd", "snappy", "gzip", "brotli", "none"], help="Parquet compression codec")
    parser.add_argument("--max-rows-per-file", type=int, default=500_000, help="Maximum rows per output shard")
    parser.add_argument("--row-group-size", type=int, default=100_000, help="Rows per parquet row group")
    parser.add_argument("--report-path", default="outputs/parquet_rebuild_report.json", help="Path to validation report JSON")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()

    compression = None if args.compression == "none" else args.compression

    report = rebuild_and_validate(
        source=source,
        out_dir=out_dir,
        source_format=args.source_format,
        cid_column=args.cid_column,
        drop_empty_cids=args.drop_empty_cids,
        compression=compression,
        max_rows_per_file=args.max_rows_per_file,
        row_group_size=args.row_group_size,
        report_path=report_path,
    )

    print(json.dumps({
        "all_ok": report["all_ok"],
        "shard_count": report["shard_count"],
        "source_rows": report["source_rows"],
        "report_path": str(report_path),
    }, indent=2))

    if not report["all_ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
