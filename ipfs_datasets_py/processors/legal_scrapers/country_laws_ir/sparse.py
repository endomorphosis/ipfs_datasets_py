"""Country-law sparse GraphRAG export through the shared HF GraphRAG builders.

This is the same parquet layout used by US Code, state laws, Federal Register,
and SkillCenter:

* ``ipfs_datasets_py.retrieval.hf_graphrag.bm25.build_bm25_layout``
* ``ipfs_datasets_py.retrieval.hf_graphrag.graph.write_graph_layout``

No SQLite. Indexes are ZSTD parquet shards under ``data/bm25`` and
``data/graph``. DuckDB queries those shards at read time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import EDGE_IDENTITY_SCHEMA, SCHEMA_VERSION
from .cidutil import cid_of_json
from .graph import build_graph

_BM25_MAX_TITLE = 4_096
_BM25_MAX_BODY = 200_000
_BM25_CTRL = dict.fromkeys(range(32))


def _bm25_row(rec: Any) -> dict[str, Any] | None:
    """One searchable BM25 row, or None when the text has no tokens."""
    from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import tokenize_bm25_text

    cid = str(getattr(rec, "entry_cid", "") or "")
    record_type = str(getattr(rec, "record_type", "") or "law")
    title = str(getattr(rec, "title", "") or "").replace("\x00", "")
    body = str(getattr(rec, "body", "") or "").replace("\x00", "")
    title = title.translate(_BM25_CTRL).strip()
    body = body.strip()
    if len(title) > _BM25_MAX_TITLE:
        title = title[:_BM25_MAX_TITLE].rstrip()
    if len(body) > _BM25_MAX_BODY:
        body = body[:_BM25_MAX_BODY].rstrip()
    if not title:
        title = f"{record_type} {cid}"[:_BM25_MAX_TITLE].strip()
    if not title and not body:
        return None
    if not tokenize_bm25_text(title) and not tokenize_bm25_text(body):
        return None
    return {
        "entry_cid": cid,
        "title": title,
        "body": body,
        "record_type": record_type,
        "document_index": 0,
    }


def corpus_to_bm25_rows(corpus: pd.DataFrame) -> list[dict[str, Any]]:
    """Project a normalized country-law corpus onto the shared BM25 row schema.

    Rows with no searchable tokens are omitted. The shared
    ``build_bm25_layout`` builder fail-closes on empty documents (same
    admission rule as US Code / Federal Register).
    """
    rows: list[dict[str, Any]] = []
    for rec in corpus.itertuples(index=False):
        row = _bm25_row(rec)
        if row is not None:
            rows.append(row)
    if not rows:
        raise RuntimeError("no corpus rows had searchable BM25 tokens")
    for i, row in enumerate(rows):
        row["document_index"] = i
    return rows


def iter_bm25_rows(corpus_parquet: Path):
    """Yield BM25 rows from a corpus parquet without holding every body."""
    import pyarrow.parquet as pq

    path = Path(corpus_parquet)
    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    columns = [
        name
        for name in ("entry_cid", "title", "body", "record_type", "document_index")
        if name in names
    ]
    produced = 0
    for batch in parquet.iter_batches(batch_size=1024, columns=columns):
        frame = batch.to_pandas()
        for rec in frame.itertuples(index=False):
            row = _bm25_row(rec)
            if row is None:
                continue
            row["document_index"] = produced
            produced += 1
            yield row
    if produced == 0:
        raise RuntimeError("no corpus rows had searchable BM25 tokens")


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


def _release_frame(frame: pd.DataFrame) -> None:
    import gc

    columns = list(frame.columns)
    if columns:
        frame.drop(columns=columns, inplace=True)
    gc.collect()


def _stream_graph(corpus_parquet: Path, output_dir: Path, log=None) -> dict[str, Any]:
    """Write the structural graph with the external-sort writer.

    The in-memory ``write_graph_layout`` path keeps every node, edge, and
    adjacency page in RAM. That SIGKILL'd Poland (3.39M docs) and France
    (3.64M docs) after BM25 had already been validated.
    """
    from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
        StreamingGraphConfig,
        write_streaming_graph_layout,
    )

    from .graph import iter_structural_edges, iter_structural_nodes

    def _counted(rows, label: str):
        count = 0
        for row in rows:
            count += 1
            if log and count % 500_000 == 0:
                log(f"graph {label} {count}")
            yield row
        if log:
            log(f"graph {label} done {count}")

    result = write_streaming_graph_layout(
        _counted(iter_structural_nodes(corpus_parquet), "nodes"),
        _counted(iter_structural_edges(corpus_parquet), "edges"),
        output_dir,
        config=StreamingGraphConfig(
            overwrite=True,
            max_records_in_memory=32_768,
            max_bytes_in_memory=256 * 1024 * 1024,
        ),
    )
    report = result.graph_report()
    if log:
        log(
            f"graph streamed nodes={report['node_count']} edges={report['edge_count']}"
        )
    return {
        "node_count": int(report["node_count"]),
        "edge_count": int(report["edge_count"]),
        "adjacency": "data/graph/adjacency/{out,in}/*.parquet",
        "streaming": True,
    }


def _graph_report(corpus: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    from ipfs_datasets_py.retrieval.hf_graphrag.graph import write_graph_layout

    nodes, edges = _graph_nodes_and_edges(corpus)
    written = write_graph_layout(nodes, edges, output_dir)
    layout = written.layout
    del nodes, edges
    return {
        "node_count": int(layout.node_count),
        "edge_count": int(layout.edge_count),
        "adjacency": "data/graph/adjacency/{out,in}/*.parquet",
    }


def _install_bm25_layout(layout_dir: Path, output_dir: Path) -> None:
    import shutil

    source = layout_dir / "data" / "bm25"
    dest = output_dir / "data" / "bm25"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    indexes = output_dir / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    for name in ("bm25_document_chunks.parquet", "bm25_keyword_shards.parquet"):
        shutil.copy2(layout_dir / "indexes" / name, indexes / name)


def _bm25_done_path(cache_dir: Path) -> Path:
    return cache_dir / "DONE.json"


def bm25_cache_ready(cache_dir: Path, fingerprint: str) -> bool:
    marker = _bm25_done_path(cache_dir)
    layout = cache_dir / "layout"
    if not marker.is_file() or not (layout / "data" / "bm25" / "postings").is_dir():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("fingerprint") == fingerprint and bool(payload.get("fragment"))


def export_sparse_graphrag_large(
    corpus: pd.DataFrame,
    output_dir: Path,
    *,
    cache_dir: Path,
    corpus_parquet: Path,
    log=None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """BM25 via on-disk postings, then the structural graph.

    The returned corpus is reloaded for packaging. The caller's frame is cleared
    so the posting build does not keep a second copy of every body.
    """
    import gc
    import shutil

    from .bm25_spill import chunks_ready, spill_bm25_layout
    from .mem import checkpoint
    from .vectors import corpus_cid_fingerprint

    output_dir = Path(output_dir)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = corpus_cid_fingerprint(corpus)
    layout_dir = cache_dir / "layout"
    work_dir = cache_dir / "work"
    if bm25_cache_ready(cache_dir, fingerprint):
        fragment = json.loads(_bm25_done_path(cache_dir).read_text(encoding="utf-8"))["fragment"]
        if log:
            log(f"reused bm25 layout {layout_dir}")
        _release_frame(corpus)
    else:
        if chunks_ready(work_dir, fingerprint):
            if log:
                log(f"resuming bm25 merge from {work_dir}")
            _release_frame(corpus)
            summary = spill_bm25_layout(
                None, layout_dir, work_dir=work_dir, fingerprint=fingerprint, log=log
            )
        else:
            # Bodies stay in the corpus parquet. Building the row list from
            # the in-memory frame SIGKILL'd the 13M-row municipal pack.
            if log:
                log(f"bm25 streaming rows from {corpus_parquet}")
            _release_frame(corpus)
            checkpoint("bm25_rows_ready", log=log)
            summary = spill_bm25_layout(
                iter_bm25_rows(corpus_parquet),
                layout_dir,
                work_dir=work_dir,
                fingerprint=fingerprint,
                log=log,
            )
            gc.collect()
        fragment = summary.to_manifest_fragment()
        _bm25_done_path(cache_dir).write_text(
            json.dumps({"fingerprint": fingerprint, "fragment": fragment}) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(work_dir, ignore_errors=True)
        checkpoint("bm25_validated", log=log)
    _install_bm25_layout(layout_dir, output_dir)
    if log:
        log(f"graph start from {corpus_parquet}")
    graph = _stream_graph(corpus_parquet, output_dir, log=log)
    gc.collect()
    checkpoint("graph_done", log=log)
    if log:
        log(f"graph kept on disk; package will stream {corpus_parquet}")
    return (
        {
            "engine": "hf_graphrag",
            "schema_version": SCHEMA_VERSION,
            "bm25": fragment,
            "graph": graph,
            "sqlite": False,
            "query_engine": "duckdb",
        },
        None,
    )


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
