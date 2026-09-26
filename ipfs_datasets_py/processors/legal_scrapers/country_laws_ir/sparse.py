"""Country-law sparse GraphRAG export through the shared HF GraphRAG builders.

This is the same parquet layout used by US Code, state laws, Federal Register,
and SkillCenter:

* ``ipfs_datasets_py.retrieval.hf_graphrag.bm25.build_bm25_layout``
* ``ipfs_datasets_py.retrieval.hf_graphrag.graph.write_graph_layout``

No SQLite. Indexes are ZSTD parquet shards under ``data/bm25`` and
``data/graph``. DuckDB queries those shards at read time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import EDGE_IDENTITY_SCHEMA, SCHEMA_VERSION
from .cidutil import cid_of_json
from .graph import build_graph


def corpus_to_bm25_rows(corpus: pd.DataFrame) -> list[dict[str, Any]]:
    """Project a normalized country-law corpus onto the shared BM25 row schema.

    Rows with no searchable tokens are omitted. The shared
    ``build_bm25_layout`` builder fail-closes on empty documents (same
    admission rule as US Code / Federal Register).
    """
    from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import tokenize_bm25_text

    _MAX_TITLE = 4_096
    _MAX_BODY = 200_000
    _CTRL = dict.fromkeys(range(32))
    rows: list[dict[str, Any]] = []
    for rec in corpus.itertuples(index=False):
        cid = str(getattr(rec, "entry_cid", "") or "")
        record_type = str(getattr(rec, "record_type", "") or "law")
        title = str(getattr(rec, "title", "") or "").replace("\x00", "")
        body = str(getattr(rec, "body", "") or "").replace("\x00", "")
        title = title.translate(_CTRL).strip()
        body = body.strip()
        if len(title) > _MAX_TITLE:
            title = title[:_MAX_TITLE].rstrip()
        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY].rstrip()
        if not title:
            title = f"{record_type} {cid}"[:_MAX_TITLE].strip()
        if not title and not body:
            continue
        if not tokenize_bm25_text(title) and not tokenize_bm25_text(body):
            continue
        rows.append(
            {
                "entry_cid": cid,
                "title": title,
                "body": body,
                "record_type": record_type,
                "document_index": int(rec.document_index),
            }
        )
    if not rows:
        raise RuntimeError("no corpus rows had searchable BM25 tokens")
    for i, row in enumerate(rows):
        row["document_index"] = i
    return rows


def _graph_nodes_and_edges(corpus: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Structural graph only (no precomputed BM25 neighbor matrix)."""
    built = build_graph(corpus, [[] for _ in range(len(corpus))])
    nodes = [
        {
            "node_cid": str(row["node_cid"]),
            "node_type": str(row["node_type"]),
            "label": row.get("label"),
            "entry_cid": row.get("entry_cid") or None,
        }
        for row in built["nodes"].to_dict("records")
    ]
    edges = []
    for row in built["edges"].to_dict("records"):
        source = str(row.get("source_cid") or row.get("source_node_cid") or "")
        target = str(row.get("target_cid") or row.get("target_node_cid") or "")
        edge_type = str(row.get("edge_type") or "")
        if not source or not target or not edge_type:
            continue
        edge_cid = str(row.get("edge_cid") or "") or cid_of_json(
            {
                "edge_type": edge_type,
                "schema": EDGE_IDENTITY_SCHEMA,
                "source": source,
                "target": target,
            }
        )
        edges.append(
            {
                "edge_cid": edge_cid,
                "edge_type": edge_type,
                "source_node_cid": source,
                "target_node_cid": target,
                "retrieval_method": str(row.get("retrieval_method") or "structural"),
                "score": row.get("score"),
            }
        )
    return nodes, edges


def export_sparse_graphrag(
    corpus: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Any]:
    """Write BM25 + graph parquet shards using the shared HF GraphRAG builders."""
    from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (
        BM25LayoutConfig,
        build_bm25_layout,
    )
    from ipfs_datasets_py.retrieval.hf_graphrag.graph import write_graph_layout

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = corpus_to_bm25_rows(corpus)
    bm25 = build_bm25_layout(
        rows,
        output_dir,
        config=BM25LayoutConfig(max_documents=max(len(rows), 1)),
    )
    nodes, edges = _graph_nodes_and_edges(corpus)
    written = write_graph_layout(nodes, edges, output_dir)
    layout = written.layout
    return {
        "engine": "hf_graphrag",
        "schema_version": SCHEMA_VERSION,
        "bm25": bm25.to_manifest_fragment(),
        "graph": {
            "node_count": int(layout.node_count),
            "edge_count": int(layout.edge_count),
            "adjacency": "data/graph/adjacency/{out,in}/*.parquet",
        },
        "sqlite": False,
        "query_engine": "duckdb",
    }
