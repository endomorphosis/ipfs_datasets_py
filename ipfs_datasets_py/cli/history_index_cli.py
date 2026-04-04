#!/usr/bin/env python3
"""
DuckDB history index search CLI.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any

import duckdb

__all__ = ["search_duckdb", "create_parser", "main"]


def _resolve_db_path(index_path: str) -> Path:
    raw = Path(index_path).expanduser().resolve()
    if raw.is_file():
        return raw
    candidate = raw / "duckdb" / "evidence_index.duckdb"
    if candidate.is_file():
        return candidate
    raise SystemExit(f"[error] DuckDB index not found at {raw} or {candidate}")


def _truncate(text: str, width: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) > width:
        return clean[:width] + " ..."
    return clean


def _search_documents(con: duckdb.DuckDBPyConnection, query: str, limit: int, source_like: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            d.doc_id,
            d.relative_path,
            d.absolute_path,
            d.status,
            d.text_length,
            d.metadata_json
        FROM documents d
        WHERE (
            lower(d.doc_id) LIKE lower(?)
            OR lower(d.relative_path) LIKE lower(?)
            OR lower(d.absolute_path) LIKE lower(?)
            OR lower(d.metadata_json) LIKE lower(?)
        )
    """
    params: list[Any] = [f"%{query}%"] * 4
    if source_like:
        sql += " AND lower(d.metadata_json) LIKE lower(?)"
        params.append(f"%{source_like}%")
    sql += " ORDER BY d.relative_path ASC LIMIT ?"
    params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    return [
        {
            "doc_id": row[0],
            "relative_path": row[1],
            "absolute_path": row[2],
            "status": row[3],
            "text_length": row[4],
            "metadata_json": row[5],
        }
        for row in rows
    ]


def _search_chunks(con: duckdb.DuckDBPyConnection, query: str, limit: int, source_like: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            c.chunk_id,
            c.doc_id,
            c.chunk_index,
            c.text,
            c.metadata_json
        FROM chunks c
        WHERE (
            lower(c.text) LIKE lower(?)
            OR lower(c.doc_id) LIKE lower(?)
            OR lower(c.metadata_json) LIKE lower(?)
        )
    """
    params: list[Any] = [f"%{query}%"] * 3
    if source_like:
        sql += " AND lower(c.metadata_json) LIKE lower(?)"
        params.append(f"%{source_like}%")
    sql += " ORDER BY c.doc_id ASC, c.chunk_index ASC LIMIT ?"
    params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    return [
        {
            "chunk_id": row[0],
            "doc_id": row[1],
            "chunk_index": row[2],
            "text": row[3],
            "metadata_json": row[4],
        }
        for row in rows
    ]


def _search_entities(con: duckdb.DuckDBPyConnection, query: str, limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT entity_id, entity_type, name, confidence, attributes_json
        FROM entities
        WHERE (
            lower(entity_id) LIKE lower(?)
            OR lower(entity_type) LIKE lower(?)
            OR lower(name) LIKE lower(?)
            OR lower(attributes_json) LIKE lower(?)
            OR lower(raw_json) LIKE lower(?)
        )
        ORDER BY confidence DESC, name ASC
        LIMIT ?
        """,
        [f"%{query}%"] * 5 + [int(limit)],
    ).fetchall()
    return [
        {
            "entity_id": row[0],
            "entity_type": row[1],
            "name": row[2],
            "confidence": row[3],
            "attributes_json": row[4],
        }
        for row in rows
    ]


def _search_relationships(con: duckdb.DuckDBPyConnection, query: str, limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT relationship_id, source_id, target_id, relation_type, confidence, attributes_json
        FROM relationships
        WHERE (
            lower(relationship_id) LIKE lower(?)
            OR lower(source_id) LIKE lower(?)
            OR lower(target_id) LIKE lower(?)
            OR lower(relation_type) LIKE lower(?)
            OR lower(attributes_json) LIKE lower(?)
            OR lower(raw_json) LIKE lower(?)
        )
        ORDER BY confidence DESC, relationship_id ASC
        LIMIT ?
        """,
        [f"%{query}%"] * 6 + [int(limit)],
    ).fetchall()
    return [
        {
            "relationship_id": row[0],
            "source_id": row[1],
            "target_id": row[2],
            "relation_type": row[3],
            "confidence": row[4],
            "attributes_json": row[5],
        }
        for row in rows
    ]


def search_duckdb(*, db_path: str | Path, query: str, table: str, limit: int = 10, source_like: str = "") -> dict[str, Any]:
    resolved = _resolve_db_path(str(db_path))
    con = duckdb.connect(str(resolved), read_only=True)
    try:
        if table == "documents":
            results = _search_documents(con, query, limit, source_like)
        elif table == "entities":
            results = _search_entities(con, query, limit)
        elif table == "relationships":
            results = _search_relationships(con, query, limit)
        else:
            results = _search_chunks(con, query, limit, source_like)
    finally:
        con.close()
    return {
        "status": "success",
        "db_path": str(resolved),
        "table": table,
        "query": query,
        "source_like": source_like,
        "result_count": len(results),
        "results": results,
    }


def _print_results(payload: dict[str, Any]) -> None:
    print(f"\nQuery: {payload['query']!r}  table={payload['table']}\n{'-' * 72}")
    for rank, row in enumerate(payload["results"], start=1):
        if payload["table"] == "chunks":
            print(f"\n#{rank}  {row['chunk_id']}  doc={row['doc_id']}")
            print(textwrap.fill(_truncate(str(row["text"])), width=90, initial_indent="    ", subsequent_indent="    "))
        elif payload["table"] == "documents":
            print(f"\n#{rank}  {row['doc_id']}")
            print(f"    {row['relative_path']}")
        elif payload["table"] == "entities":
            print(f"\n#{rank}  {row['entity_id']}  {row['entity_type']}  conf={row['confidence']}")
            print(f"    {row['name']}")
        else:
            print(f"\n#{rank}  {row['relationship_id']}  conf={row['confidence']}")
            print(f"    {row['source_id']} -> {row['target_id']} ({row['relation_type']})")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets history-index",
        description="Search the DuckDB history index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(__doc__),
    )
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--index-path", default="./research_results/history_index_v8/duckdb/evidence_index.duckdb", help="DuckDB file path or index directory")
    parser.add_argument("--table", choices=["chunks", "documents", "entities", "relationships"], default="chunks")
    parser.add_argument("--top-k", type=int, default=10, help="Maximum results to return")
    parser.add_argument("--source-like", default="", help="Optional metadata substring filter, e.g. google_voice or gmail_email")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)
    payload = search_duckdb(
        db_path=parsed.index_path,
        query=" ".join(parsed.query),
        table=parsed.table,
        limit=parsed.top_k,
        source_like=parsed.source_like,
    )
    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_results(payload)
    return 0
