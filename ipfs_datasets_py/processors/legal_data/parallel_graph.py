"""Process-pool graph extraction, cluster neighbors, and adjacency invert.

Citation/docket/RIN extraction is regex-heavy and GIL-bound, so it uses
the same spawn pool as tokenization. Embedding-neighbor kNN is per-cluster
and reads a shared memmap. Two-way adjacency shards each direction by
node-key range and sizes the pool with :func:`tokenize_process_pool_size`.

Do not use this to mutate a live in-memory BM25 index. Query-time graph
walks stay serial over the adjacency pages.
"""

from __future__ import annotations

import multiprocessing as mp
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
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
    chunk_items,
    ordered_process_map,
)

DEFAULT_MAX_GRAPH_CHARS = 20000
DEFAULT_NEIGHBOR_K = 8
DEFAULT_SHARD_ROWS = 4096
ADJ_SCHEMA_VERSION = "skillcenter-hf-graph-adjacency/v1"
ADJ_BYTES_PER_WORKER = 1024 * 1024 * 1024
REMAP_FILES_PER_CHUNK = 32


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


def bm25_neighbor_group(payload: Mapping[str, Any]) -> dict[str, Any]:
    """BM25 kNN inside one centroid group. Spawn-worker entry.

    Tokenizes the clipped texts with the shared legal tokenizer and scores
    Okapi BM25 against the in-group inverted index. Similarity edges are
    retrieval proposals, not legal authority.
    """

    from collections import Counter, defaultdict
    import math

    from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
        tokenize_terms,
    )

    legal_ids = [str(item) for item in payload.get("legal_ids") or ()]
    texts = [str(item or "") for item in payload.get("texts") or ()]
    neighbor_k = int(payload.get("neighbor_k") or DEFAULT_NEIGHBOR_K)
    k1 = float(payload.get("k1") or 1.2)
    b = float(payload.get("b") or 0.75)
    cid = int(payload.get("cid") or 0)
    if len(legal_ids) != len(texts):
        raise ValueError("legal_ids and texts must be aligned")
    n = len(legal_ids)
    if n < 2:
        return {"cid": cid, "dst": [], "n": n, "scores": [], "src": []}
    term_lists = [tokenize_terms(text) for text in texts]
    dl = [max(len(terms), 1) for terms in term_lists]
    avgdl = float(sum(dl)) / float(n)
    df: Counter[str] = Counter()
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    tfs: list[Counter[str]] = []
    for index, terms in enumerate(term_lists):
        tf = Counter(str(term) for term in terms)
        tfs.append(tf)
        for term, freq in tf.items():
            df[term] += 1
            postings[term].append((index, int(freq)))
    src: list[str] = []
    dst: list[str] = []
    scores: list[float] = []
    k = min(max(1, neighbor_k), n - 1)
    for index, tf in enumerate(tfs):
        accum: dict[int, float] = defaultdict(float)
        for term, freq in tf.items():
            docs = df[term]
            idf = math.log(1.0 + (n - docs + 0.5) / (docs + 0.5))
            for other, other_tf in postings[term]:
                if other == index:
                    continue
                denom = other_tf + k1 * (1.0 - b + b * dl[other] / avgdl)
                accum[other] += idf * (other_tf * (k1 + 1.0)) / denom
        ranked = sorted(
            accum.items(),
            key=lambda item: (-item[1], legal_ids[item[0]]),
        )[:k]
        for other, score in ranked:
            src.append(legal_ids[index])
            dst.append(legal_ids[other])
            scores.append(float(score))
    return {"cid": cid, "dst": dst, "n": n, "scores": scores, "src": src}


def _edge_cid(src: str, etype: str, dst: str) -> str:
    from ipfs_datasets_py.logic.ir_core.identity import cid_v1

    return cid_v1(f"{src}\t{etype}\t{dst}".encode("utf-8"))


def _retrieval_method(edge_type: str) -> str:
    if edge_type == "BM25_NEIGHBOR_OF":
        return "bm25"
    if edge_type == "EMBEDDING_NEIGHBOR_OF":
        return "embedding"
    return "graph"


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


def split_adjacency_key_ranges(
    keys: Sequence[str], n_parts: int
) -> list[tuple[str | None, str | None]]:
    """Split sorted unique keys into contiguous ``[lo, hi)`` ranges."""

    uniq = sorted({str(key) for key in keys})
    if not uniq:
        return [(None, None)]
    parts = max(1, min(int(n_parts), len(uniq)))
    if parts <= 1:
        return [(None, None)]
    width = (len(uniq) + parts - 1) // parts
    ranges: list[tuple[str | None, str | None]] = []
    for index in range(parts):
        start = index * width
        if start >= len(uniq):
            break
        end = start + width
        lo = uniq[start]
        hi = uniq[end] if end < len(uniq) else None
        ranges.append((lo, hi))
    return ranges or [(None, None)]


def _empty_adjacency_result(direction: str) -> dict[str, Any]:
    return {
        "direction": direction,
        "max_degree": 0,
        "nodes_with_edges": 0,
        "pages": 0,
        "pointer_total": 0,
        "routing": [],
        "shards": 0,
    }


def _filter_edge_table(
    table: pa.Table, node_col: str, key_lo: str | None, key_hi: str | None
) -> pa.Table:
    if key_lo is None and key_hi is None:
        return table
    col = table[node_col]
    mask = None
    if key_lo is not None:
        mask = pc.greater_equal(col, str(key_lo))
    if key_hi is not None:
        upper = pc.less(col, str(key_hi))
        mask = upper if mask is None else pc.and_(mask, upper)
    return table.filter(mask)


def _clear_parquet_dir(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("*.parquet"):
        stale.unlink()


def write_adjacency_direction(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Sort one directed adjacency family or node-key slice. Spawn-worker entry."""

    edge_files = [Path(p) for p in payload["edge_files"]]
    node_files = [Path(p) for p in payload["node_files"]]
    dest = Path(str(payload["dest"]))
    direction = str(payload["direction"])
    node_col = str(payload["node_col"])
    neighbor_col = str(payload["neighbor_col"])
    shard_rows = int(payload.get("shard_rows") or DEFAULT_SHARD_ROWS)
    key_lo = payload.get("key_lo")
    key_hi = payload.get("key_hi")
    part_id = int(payload.get("part_id") or 0)
    dest.mkdir(parents=True, exist_ok=True)
    if payload.get("clear_dest", True):
        _clear_parquet_dir(dest)
    else:
        prefix = f"part-{part_id:04d}-"
        for stale in dest.glob(f"{prefix}*.parquet"):
            stale.unlink()
    node_types: dict[str, str] = {}
    for path in node_files:
        table = pq.read_table(path, columns=["node_id", "node_type"])
        for nid, ntype in zip(
            table.column("node_id").to_pylist(), table.column("node_type").to_pylist()
        ):
            node_types[str(nid)] = str(ntype)
    tables = []
    for path in edge_files:
        table = _filter_edge_table(pq.read_table(path), node_col, key_lo, key_hi)
        if table.num_rows:
            tables.append(table)
    if not tables:
        return _empty_adjacency_result(direction)
    edges = pa.concat_tables(tables)
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
    ranged = key_lo is not None or key_hi is not None or part_id > 0

    def flush() -> None:
        nonlocal shard, rows
        if not rows:
            return
        name = (
            f"part-{part_id:04d}-{shard:04d}.parquet"
            if ranged
            else f"part-{shard:06d}.parquet"
        )
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
            methods = [_retrieval_method(et) for et in ets]
            scores = [
                0.0 if et in {"EMBEDDING_NEIGHBOR_OF", "BM25_NEIGHBOR_OF"} else 1.0
                for et in ets
            ]
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
        "part_id": part_id,
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


def map_bm25_neighbor_groups(
    payloads: Sequence[Mapping[str, Any]],
    *,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    """Process-pool BM25 neighbors over centroid groups."""

    plan = tokenize_process_pool_size(
        per_task_budget=TOKENIZE_BYTES_PER_WORKER, requested=workers
    )
    items = [dict(item) for item in payloads]
    print(
        f"graph bm25-neighbors groups={len(items)} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(items) <= 1:
        return [bm25_neighbor_group(item) for item in items]
    ctx = mp.get_context(plan.start_method)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
        futures = [pool.submit(bm25_neighbor_group, item) for item in items]
        done = 0
        n_edges = 0
        for fut in as_completed(futures):
            rec = fut.result()
            results.append(rec)
            done += 1
            n_edges += len(rec.get("src") or ())
            if done % 50 == 0 or done == len(items):
                print(
                    f"  bm25-neighbors groups={done}/{len(items)} edges={n_edges}",
                    flush=True,
                )
    return results


def _load_node_keys(
    node_files: Sequence[Path],
) -> tuple[list[str], list[str]]:
    documents: list[str] = []
    all_ids: list[str] = []
    for path in node_files:
        table = pq.read_table(path, columns=["node_id", "node_type"])
        for nid, ntype in zip(
            table.column("node_id").to_pylist(), table.column("node_type").to_pylist()
        ):
            nid = str(nid)
            all_ids.append(nid)
            if str(ntype) == "document":
                documents.append(nid)
    return documents or all_ids, all_ids


def _merge_adjacency_parts(parts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    filled = [dict(part) for part in parts if int(part.get("pointer_total") or 0) > 0]
    if not filled:
        direction = str(parts[0]["direction"]) if parts else "outgoing"
        return _empty_adjacency_result(direction)
    filled.sort(
        key=lambda part: (
            str((part.get("routing") or [{"first_key": ""}])[0].get("first_key") or ""),
            int(part.get("part_id") or 0),
        )
    )
    routing: list[dict[str, Any]] = []
    for part in filled:
        for item in part.get("routing") or ():
            rec = dict(item)
            rec["shard_id"] = len(routing)
            routing.append(rec)
    return {
        "direction": str(filled[0]["direction"]),
        "max_degree": max(int(part["max_degree"]) for part in filled),
        "nodes_with_edges": sum(int(part["nodes_with_edges"]) for part in filled),
        "pages": sum(int(part["pages"]) for part in filled),
        "pointer_total": sum(int(part["pointer_total"]) for part in filled),
        "routing": routing,
        "shards": len(routing),
    }


def map_adjacency_directions(
    *,
    edge_files: Sequence[Path],
    node_files: Sequence[Path],
    outgoing_dest: Path,
    incoming_dest: Path,
    shard_rows: int = DEFAULT_SHARD_ROWS,
    workers: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build outgoing and incoming adjacency with resource-aware spawn workers.

    Each direction is split into contiguous node-key ranges so the host can
    use more than two processes. Locator ``first_key``/``last_key`` ranges
    stay ordered after merge. Query-time walks stay serial.
    """

    plan = tokenize_process_pool_size(
        per_task_budget=ADJ_BYTES_PER_WORKER, requested=workers
    )
    files = [str(path) for path in edge_files]
    nodes = [str(path) for path in node_files]
    document_ids, all_ids = _load_node_keys(node_files)
    n_parts = max(1, plan.workers)
    outgoing_ranges = split_adjacency_key_ranges(document_ids, n_parts)
    incoming_ranges = split_adjacency_key_ranges(all_ids, n_parts)
    _clear_parquet_dir(outgoing_dest)
    _clear_parquet_dir(incoming_dest)
    payloads: list[dict[str, Any]] = []
    for direction, dest, node_col, neighbor_col, ranges in (
        ("outgoing", outgoing_dest, "src", "dst", outgoing_ranges),
        ("incoming", incoming_dest, "dst", "src", incoming_ranges),
    ):
        for part_id, (key_lo, key_hi) in enumerate(ranges):
            payloads.append(
                {
                    "clear_dest": False,
                    "dest": str(dest),
                    "direction": direction,
                    "edge_files": files,
                    "key_hi": key_hi,
                    "key_lo": key_lo,
                    "neighbor_col": neighbor_col,
                    "node_col": node_col,
                    "node_files": nodes,
                    "part_id": part_id,
                    "shard_rows": shard_rows,
                }
            )
    print(
        f"graph adjacency directions=2 parts={n_parts} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(payloads) <= 1:
        results = [write_adjacency_direction(item) for item in payloads]
    else:
        ctx = mp.get_context(plan.start_method)
        results = []
        with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
            futures = [pool.submit(write_adjacency_direction, item) for item in payloads]
            done = 0
            for fut in as_completed(futures):
                rec = fut.result()
                results.append(rec)
                done += 1
                print(
                    f"  adjacency parts={done}/{len(payloads)} "
                    f"direction={rec['direction']} pointers={rec['pointer_total']}",
                    flush=True,
                )
    outgoing = _merge_adjacency_parts(
        [item for item in results if item.get("direction") == "outgoing"]
    )
    incoming = _merge_adjacency_parts(
        [item for item in results if item.get("direction") == "incoming"]
    )
    return outgoing, incoming


def _identity_key_to_cid(path: Path) -> dict[str, str]:
    table = pq.read_table(path, columns=["node_key", "node_cid"])
    return {
        str(key): str(cid)
        for key, cid in zip(
            table.column("node_key").to_pylist(), table.column("node_cid").to_pylist()
        )
    }


def remap_graph_edge_file(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite one edge parquet onto CIDv1 src/dst/edge_cid. Spawn-worker entry."""

    path = Path(str(payload["path"]))
    dest = Path(str(payload["dest"]))
    key_to_cid = payload.get("key_to_cid")
    if not isinstance(key_to_cid, Mapping):
        key_to_cid = _identity_key_to_cid(Path(str(payload["identity_path"])))
    table = pq.read_table(path, columns=["src", "dst", "type"])
    srcs: list[str] = []
    dsts: list[str] = []
    types: list[str] = []
    cids: list[str] = []
    missing = 0
    for src, dst, etype in zip(
        table.column("src").to_pylist(),
        table.column("dst").to_pylist(),
        table.column("type").to_pylist(),
    ):
        src_cid = key_to_cid.get(str(src))
        dst_cid = key_to_cid.get(str(dst))
        if src_cid is None or dst_cid is None:
            missing += 1
            continue
        srcs.append(str(src_cid))
        dsts.append(str(dst_cid))
        types.append(str(etype))
        cids.append(_edge_cid(str(src_cid), str(etype), str(dst_cid)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if srcs:
        pq.write_table(
            pa.table({"src": srcs, "dst": dsts, "type": types, "edge_cid": cids}),
            dest,
            compression="zstd",
        )
    return {"kept": len(srcs), "missing": missing, "name": path.name}


def remap_graph_edge_files_chunk(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite a batch of edge parquet files. Spawn-worker entry."""

    key_to_cid = _identity_key_to_cid(Path(str(payload["identity_path"])))
    src_dir = Path(str(payload["src_dir"]))
    dest_dir = Path(str(payload["dest_dir"]))
    kept = 0
    missing = 0
    for name in payload["names"]:
        rec = remap_graph_edge_file(
            {
                "path": str(src_dir / str(name)),
                "dest": str(dest_dir / str(name)),
                "key_to_cid": key_to_cid,
            }
        )
        kept += int(rec["kept"])
        missing += int(rec["missing"])
    return {"kept": kept, "missing": missing, "files": len(payload["names"])}


def map_graph_edge_cid_files(
    edge_files: Sequence[Path],
    *,
    identity_path: Path,
    dest_dir: Path,
    workers: int | None = None,
) -> dict[str, int]:
    """Process-pool CIDv1 rewrite of graph edge parquet files."""

    files = [Path(path) for path in edge_files]
    dest_dir.mkdir(parents=True, exist_ok=True)
    plan = tokenize_process_pool_size(
        per_task_budget=TOKENIZE_BYTES_PER_WORKER, requested=workers
    )
    names = [path.name for path in files]
    src_dir = files[0].parent if files else dest_dir
    chunk_size = max(1, REMAP_FILES_PER_CHUNK)
    payloads = [
        {
            "dest_dir": str(dest_dir),
            "identity_path": str(identity_path),
            "names": list(chunk),
            "src_dir": str(src_dir),
        }
        for chunk in chunk_items(names, chunk_size)
    ]
    print(
        f"graph remap-edges files={len(names)} chunks={len(payloads)} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(payloads) <= 1:
        recs = [remap_graph_edge_files_chunk(item) for item in payloads]
    else:
        ctx = mp.get_context(plan.start_method)
        recs = []
        with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
            futures = [pool.submit(remap_graph_edge_files_chunk, item) for item in payloads]
            done = 0
            kept = 0
            for fut in as_completed(futures):
                rec = fut.result()
                recs.append(rec)
                done += 1
                kept += int(rec["kept"])
                if done % 10 == 0 or done == len(payloads):
                    print(
                        f"  remap-edges chunks={done}/{len(payloads)} kept={kept}",
                        flush=True,
                    )
    return {
        "files": len(names),
        "kept": int(sum(int(rec["kept"]) for rec in recs)),
        "missing": int(sum(int(rec["missing"]) for rec in recs)),
        "workers": int(plan.workers),
    }


def remap_vector_entry_cid_file(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite ``entry_cid`` on one vector parquet. Spawn-worker entry."""

    path = Path(str(payload["path"]))
    dest = Path(str(payload.get("dest") or path))
    key_to_cid = payload.get("key_to_cid")
    if not isinstance(key_to_cid, Mapping):
        key_to_cid = _identity_key_to_cid(Path(str(payload["identity_path"])))
    table = pq.read_table(path)
    old = table.column("entry_cid").to_pylist()
    new = [str(key_to_cid.get(str(item), str(item))) for item in old]
    cols = {name: table.column(name) for name in table.schema.names if name != "entry_cid"}
    cols["entry_cid"] = pa.array(new, type=pa.string())
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), dest, compression="zstd")
    return {"rows": len(new), "name": path.name}


def remap_vector_entry_cid_files_chunk(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite ``entry_cid`` on a batch of vector parquet files."""

    key_to_cid = _identity_key_to_cid(Path(str(payload["identity_path"])))
    rows = 0
    for item in payload["files"]:
        rec = remap_vector_entry_cid_file(
            {
                "path": str(item["path"]),
                "dest": str(item.get("dest") or item["path"]),
                "key_to_cid": key_to_cid,
            }
        )
        rows += int(rec["rows"])
    return {"rows": rows, "files": len(payload["files"])}


def map_vector_entry_cid_files(
    files: Sequence[tuple[Path, Path]],
    *,
    identity_path: Path,
    workers: int | None = None,
) -> dict[str, int]:
    """Process-pool CIDv1 rewrite of vector ``entry_cid`` columns."""

    pairs = [(Path(src), Path(dst)) for src, dst in files]
    plan = tokenize_process_pool_size(
        per_task_budget=TOKENIZE_BYTES_PER_WORKER, requested=workers
    )
    payloads = [
        {
            "files": [{"path": str(src), "dest": str(dst)} for src, dst in chunk],
            "identity_path": str(identity_path),
        }
        for chunk in chunk_items(pairs, max(1, REMAP_FILES_PER_CHUNK))
    ]
    print(
        f"graph remap-vectors files={len(pairs)} chunks={len(payloads)} workers={plan.workers}",
        flush=True,
    )
    if plan.workers <= 1 or len(payloads) <= 1:
        recs = [remap_vector_entry_cid_files_chunk(item) for item in payloads]
    else:
        ctx = mp.get_context(plan.start_method)
        recs = []
        with ProcessPoolExecutor(max_workers=plan.workers, mp_context=ctx) as pool:
            futures = [
                pool.submit(remap_vector_entry_cid_files_chunk, item) for item in payloads
            ]
            done = 0
            rows = 0
            for fut in as_completed(futures):
                rec = fut.result()
                recs.append(rec)
                done += 1
                rows += int(rec["rows"])
                if done % 5 == 0 or done == len(payloads):
                    print(
                        f"  remap-vectors chunks={done}/{len(payloads)} rows={rows}",
                        flush=True,
                    )
    return {
        "files": len(pairs),
        "rows": int(sum(int(rec["rows"]) for rec in recs)),
        "workers": int(plan.workers),
    }


__all__ = [
    "ADJ_BYTES_PER_WORKER",
    "ADJ_SCHEMA_VERSION",
    "bm25_neighbor_group",
    "embedding_neighbor_cluster",
    "extract_document_graph",
    "extract_partition_graph",
    "map_adjacency_directions",
    "map_bm25_neighbor_groups",
    "map_graph_edge_cid_files",
    "map_graph_partitions",
    "map_neighbor_clusters",
    "map_vector_entry_cid_files",
    "remap_graph_edge_file",
    "remap_vector_entry_cid_file",
    "split_adjacency_key_ranges",
    "write_adjacency_direction",
]
