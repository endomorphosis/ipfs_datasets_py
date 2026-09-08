"""Process-pool graph extraction, cluster neighbors, and adjacency invert.

Citation/docket/RIN extraction is regex-heavy and GIL-bound, so it uses
the same spawn pool as tokenization. Embedding-neighbor kNN is per-cluster
and reads a shared memmap. Two-way adjacency sorts outgoing and incoming
independently.

Do not use this to mutate a live in-memory BM25 index. Query-time graph
walks stay serial over the adjacency pages.
"""

from __future__ import annotations

import hashlib
import multiprocessing as mp
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
    extract_citation_mentions,
    extract_docket_mentions,
    extract_rin_mentions,
)
from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    TOKENIZE_BYTES_PER_WORKER,
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.parallel_tokenize import (
    ordered_process_map,
)

DEFAULT_MAX_GRAPH_CHARS = 20000
DEFAULT_NEIGHBOR_K = 8
DEFAULT_SHARD_ROWS = 4096
ADJ_SCHEMA_VERSION = "skillcenter-hf-graph-adjacency/v1"


def extract_document_graph(
    legal_id: str,
    text: str,
    publication_date: str = "",
    *,
    max_chars: int = DEFAULT_MAX_GRAPH_CHARS,
    max_dockets: int = 16,
    max_rins: int = 8,
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """Return (node_id→type, edges) for one document. Process-pool safe."""

    nodes: dict[str, str] = {legal_id: "document"}
    edges: list[tuple[str, str, str]] = []
    clipped = str(text or "")[: max(0, int(max_chars))]
    pub = str(publication_date or "")
    if pub:
        nodes[f"date:{pub}"] = "date"
        edges.append((legal_id, f"date:{pub}", "PUBLISHED_ON"))
    nodes[f"provenance:{legal_id}"] = "provenance"
    edges.append((legal_id, f"provenance:{legal_id}", "HAS_PROVENANCE"))
    for mention in extract_citation_mentions(clipped):
        if mention.kind == "cfr":
            key = f"citation:cfr:{mention.title}:{mention.section}"
            nodes[key] = "citation_cfr"
            edges.append((legal_id, key, "CITES"))
        elif mention.kind == "usc":
            key = f"citation:usc:{mention.title}:{mention.section}"
            nodes[key] = "citation_usc"
            edges.append((legal_id, key, "CITES"))
    for docket, _, _ in extract_docket_mentions(clipped)[:max_dockets]:
        key = f"docket:{docket}"
        nodes[key] = "docket"
        edges.append((legal_id, key, "HAS_DOCKET"))
    for rin, _, _ in extract_rin_mentions(clipped)[:max_rins]:
        key = f"rin:{rin}"
        nodes[key] = "rin"
        edges.append((legal_id, key, "HAS_RIN"))
    return nodes, edges


def extract_partition_graph(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract graph rows from one parquet partition. Spawn-worker entry."""

    month = Path(str(payload["month"]))
    out = Path(str(payload["out"]))
    max_chars = int(payload.get("max_chars") or DEFAULT_MAX_GRAPH_CHARS)
    shard_rows = int(payload.get("shard_rows") or DEFAULT_SHARD_ROWS)
    edge_dir = out / "edges"
    node_dir = out / "nodes_raw"
    edge_dir.mkdir(parents=True, exist_ok=True)
    node_dir.mkdir(parents=True, exist_ok=True)
    stem = month.name
    parquet_path = month / "bodies.parquet"
    pf = pq.ParquetFile(parquet_path)
    cols = ["legal_id", "disposition", "publication_date", "text"]
    available = set(pf.schema_arrow.names)
    cols = [c for c in cols if c in available]
    edge_buf: list[dict[str, str]] = []
    node_buf: list[dict[str, str]] = []
    edge_part = 0
    n_docs = 0
    edge_types: Counter[str] = Counter()

    def flush_edges() -> None:
        nonlocal edge_part, edge_buf
        if not edge_buf:
            return
        pq.write_table(
            pa.table({k: [r[k] for r in edge_buf] for k in ("src", "dst", "type")}),
            edge_dir / f"part-{stem}-{edge_part:05d}.parquet",
            compression="zstd",
        )
        edge_part += 1
        edge_buf.clear()

    for batch in pf.iter_batches(batch_size=512, columns=cols):
        for row in batch.to_pylist():
            if not str(row.get("disposition") or "").startswith("full_text"):
                continue
            legal_id = str(row["legal_id"])
            nodes, edges = extract_document_graph(
                legal_id,
                str(row.get("text") or ""),
                str(row.get("publication_date") or ""),
                max_chars=max_chars,
            )
            for node_id, node_type in nodes.items():
                node_buf.append({"node_id": node_id, "node_type": node_type})
            for src, dst, etype in edges:
                edge_buf.append({"src": src, "dst": dst, "type": etype})
                edge_types[etype] += 1
                if len(edge_buf) >= shard_rows:
                    flush_edges()
            n_docs += 1
    flush_edges()
    if node_buf:
        pq.write_table(
            pa.table(
                {
                    "node_id": [r["node_id"] for r in node_buf],
                    "node_type": [r["node_type"] for r in node_buf],
                }
            ),
            node_dir / f"{stem}.parquet",
            compression="zstd",
        )
    return {
        "edge_count": int(sum(edge_types.values())),
        "edge_types": dict(edge_types),
        "month": stem,
        "n_docs": n_docs,
    }


def embedding_neighbor_cluster(payload: Mapping[str, Any]) -> dict[str, Any]:
    """kNN within one k-means cluster. Returns integer index pairs."""

    cid = int(payload["cid"])
    vec_path = Path(str(payload["vec_path"]))
    labels_path = Path(str(payload["labels_path"]))
    n = int(payload["n"])
    dim = int(payload["dim"])
    neighbor_k = int(payload.get("neighbor_k") or DEFAULT_NEIGHBOR_K)
    labels = np.load(labels_path, mmap_mode="r")
    idx = np.where(np.asarray(labels) == cid)[0]
    if len(idx) < 2:
        return {"cid": cid, "dst": [], "n": int(len(idx)), "src": []}
    mmap = np.memmap(vec_path, mode="r", dtype=np.float32, shape=(n, dim))
    mat = np.asarray(mmap[idx], dtype=np.float32)
    sim = mat @ mat.T
    np.fill_diagonal(sim, -1.0)
    k = min(neighbor_k, len(idx) - 1)
    top = np.argpartition(sim, -k, axis=1)[:, -k:]
    src: list[int] = []
    dst: list[int] = []
    for i, neighbors in enumerate(top):
        src_i = int(idx[i])
        for j in neighbors:
            dst_i = int(idx[int(j)])
            if src_i == dst_i:
                continue
            src.append(src_i)
            dst.append(dst_i)
    return {"cid": cid, "dst": dst, "n": int(len(idx)), "src": src}


def _edge_cid(src: str, etype: str, dst: str) -> str:
    return "sha256:" + hashlib.sha256(f"{src}\t{etype}\t{dst}".encode("utf-8")).hexdigest()


def _adj_table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.table(
        {
            "direction": [r["direction"] for r in rows],
            "edge_cids": pa.array([r["edge_cids"] for r in rows], type=pa.list_(pa.string())),
            "edge_types": pa.array([r["edge_types"] for r in rows], type=pa.list_(pa.string())),
            "first_key": [r["first_key"] for r in rows],
            "last_key": [r["last_key"] for r in rows],
            "neighbor_cids": pa.array(
                [r["neighbor_cids"] for r in rows], type=pa.list_(pa.string())
            ),
            "neighbor_count": [r["neighbor_count"] for r in rows],
            "neighbor_node_types": pa.array(
                [r["neighbor_node_types"] for r in rows], type=pa.list_(pa.string())
            ),
            "node_cid": [r["node_cid"] for r in rows],
            "page_count": [r["page_count"] for r in rows],
            "page_index": [r["page_index"] for r in rows],
            "retrieval_methods": pa.array(
                [r["retrieval_methods"] for r in rows], type=pa.list_(pa.string())
            ),
            "schema_version": [r["schema_version"] for r in rows],
            "scores": pa.array([r["scores"] for r in rows], type=pa.list_(pa.float32())),
            "total_neighbor_count": [r["total_neighbor_count"] for r in rows],
        }
    )


def write_adjacency_direction(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Sort one directed adjacency family. Spawn-worker entry."""

    edge_files = [Path(p) for p in payload["edge_files"]]
    node_files = [Path(p) for p in payload["node_files"]]
    dest = Path(str(payload["dest"]))
    direction = str(payload["direction"])
    node_col = str(payload["node_col"])
    neighbor_col = str(payload["neighbor_col"])
    shard_rows = int(payload.get("shard_rows") or DEFAULT_SHARD_ROWS)
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("*.parquet"):
        stale.unlink()
    node_types: dict[str, str] = {}
    for path in node_files:
        table = pq.read_table(path, columns=["node_id", "node_type"])
        for nid, ntype in zip(
            table.column("node_id").to_pylist(), table.column("node_type").to_pylist()
        ):
            node_types[str(nid)] = str(ntype)
    edges = pa.concat_tables([pq.read_table(path) for path in edge_files])
    ordered = edges.sort_by(
        [(node_col, "ascending"), ("type", "ascending"), (neighbor_col, "ascending")]
    )
    del edges
    keys = ordered.column(node_col).to_pylist()
    nbors = ordered.column(neighbor_col).to_pylist()
    etypes = ordered.column("type").to_pylist()
    del ordered
    rows: list[dict[str, Any]] = []
    routing: list[dict[str, Any]] = []
    shard = 0
    pointer_total = 0
    max_degree = 0
    n_nodes = 0

    def flush() -> None:
        nonlocal shard, rows
        if not rows:
            return
        name = f"part-{shard:06d}.parquet"
        pq.write_table(_adj_table(rows), dest / name, compression="zstd")
        routing.append(
            {
                "first_key": rows[0]["node_cid"],
                "last_key": rows[-1]["node_cid"],
                "relative_path": f"data/graph/adjacency/{direction}/{name}",
                "row_count": len(rows),
                "shard_id": shard,
            }
        )
        shard += 1
        rows.clear()

    i = 0
    n = len(keys)
    while i < n:
        key = keys[i]
        j = i + 1
        while j < n and keys[j] == key:
            j += 1
        total = j - i
        max_degree = max(max_degree, total)
        pointer_total += total
        n_nodes += 1
        page_count = (total + shard_rows - 1) // shard_rows
        for page_index, start in enumerate(range(i, j, shard_rows)):
            end = min(start + shard_rows, j)
            neigh = nbors[start:end]
            ets = etypes[start:end]
            if direction == "outgoing":
                edge_cids = [_edge_cid(key, et, nb) for et, nb in zip(ets, neigh)]
            else:
                edge_cids = [_edge_cid(nb, et, key) for et, nb in zip(ets, neigh)]
            methods = [
                "embedding" if et == "EMBEDDING_NEIGHBOR_OF" else "graph" for et in ets
            ]
            scores = [0.0 if et == "EMBEDDING_NEIGHBOR_OF" else 1.0 for et in ets]
            page_key = f"{key}:{page_index:08d}"
            rows.append(
                {
                    "direction": direction,
                    "edge_cids": edge_cids,
                    "edge_types": list(ets),
                    "first_key": page_key,
                    "last_key": page_key,
                    "neighbor_cids": list(neigh),
                    "neighbor_count": end - start,
                    "neighbor_node_types": [node_types.get(nb, "unknown") for nb in neigh],
                    "node_cid": key,
                    "page_count": page_count,
                    "page_index": page_index,
                    "retrieval_methods": methods,
                    "schema_version": ADJ_SCHEMA_VERSION,
                    "scores": scores,
                    "total_neighbor_count": total,
                }
            )
            if len(rows) >= shard_rows:
                flush()
        i = j
    flush()
    return {
        "direction": direction,
        "max_degree": max_degree,
        "nodes_with_edges": n_nodes,
        "pages": sum(item["row_count"] for item in routing),
        "pointer_total": pointer_total,
        "routing": routing,
        "shards": len(routing),
    }


def map_graph_partitions(
    months: Sequence[Path],
    *,
    out: Path,
    max_chars: int = DEFAULT_MAX_GRAPH_CHARS,
    shard_rows: int = DEFAULT_SHARD_ROWS,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    """Process-pool citation graph extraction over parquet partitions."""

    plan = tokenize_process_pool_size(
        per_task_budget=TOKENIZE_BYTES_PER_WORKER, requested=workers
    )
    payloads = [
        {
            "max_chars": max_chars,
            "month": str(month),
            "out": str(out),
            "shard_rows": shard_rows,
        }
        for month in months
    ]
    print(
        f"graph extract partitions={len(payloads)} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(payloads) <= 1:
        return [extract_partition_graph(item) for item in payloads]
    ctx = mp.get_context(plan.start_method)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
        futures = [pool.submit(extract_partition_graph, item) for item in payloads]
        done = 0
        n_docs = 0
        for fut in as_completed(futures):
            rec = fut.result()
            results.append(rec)
            done += 1
            n_docs += int(rec["n_docs"])
            if done % 20 == 0 or done == len(payloads):
                print(
                    f"  graph partitions={done}/{len(payloads)} docs={n_docs}",
                    flush=True,
                )
    return results


def map_neighbor_clusters(
    cluster_ids: Sequence[int],
    *,
    vec_path: Path,
    labels_path: Path,
    n: int,
    dim: int,
    neighbor_k: int = DEFAULT_NEIGHBOR_K,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    """Process-pool within-cluster embedding neighbors."""

    plan = tokenize_process_pool_size(
        per_task_budget=512 * 1024 * 1024, requested=workers
    )
    payloads = [
        {
            "cid": int(cid),
            "dim": dim,
            "labels_path": str(labels_path),
            "n": n,
            "neighbor_k": neighbor_k,
            "vec_path": str(vec_path),
        }
        for cid in cluster_ids
    ]
    print(
        f"graph neighbors clusters={len(payloads)} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(payloads) <= 1:
        return [embedding_neighbor_cluster(item) for item in payloads]
    ctx = mp.get_context(plan.start_method)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
        futures = [pool.submit(embedding_neighbor_cluster, item) for item in payloads]
        done = 0
        for fut in as_completed(futures):
            rec = fut.result()
            results.append(rec)
            done += 1
            if done % 50 == 0 or done == len(payloads):
                print(f"  neighbors clusters={done}/{len(payloads)}", flush=True)
    return results


def map_adjacency_directions(
    *,
    edge_files: Sequence[Path],
    node_files: Sequence[Path],
    outgoing_dest: Path,
    incoming_dest: Path,
    shard_rows: int = DEFAULT_SHARD_ROWS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build outgoing and incoming adjacency in two spawn workers."""

    files = [str(path) for path in edge_files]
    nodes = [str(path) for path in node_files]
    payloads = [
        {
            "dest": str(outgoing_dest),
            "direction": "outgoing",
            "edge_files": files,
            "neighbor_col": "dst",
            "node_col": "src",
            "node_files": nodes,
            "shard_rows": shard_rows,
        },
        {
            "dest": str(incoming_dest),
            "direction": "incoming",
            "edge_files": files,
            "neighbor_col": "src",
            "node_col": "dst",
            "node_files": nodes,
            "shard_rows": shard_rows,
        },
    ]
    results = ordered_process_map(
        write_adjacency_direction, payloads, workers=2
    )
    by_dir = {str(item["direction"]): item for item in results}
    return by_dir["outgoing"], by_dir["incoming"]


__all__ = [
    "ADJ_SCHEMA_VERSION",
    "embedding_neighbor_cluster",
    "extract_document_graph",
    "extract_partition_graph",
    "map_adjacency_directions",
    "map_graph_partitions",
    "map_neighbor_clusters",
    "write_adjacency_direction",
]
