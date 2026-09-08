"""Property graph: document nodes, facet nodes, BM25 neighbors, CONTAINED_IN."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from . import SCHEMA_VERSION
from .cidutil import cid_of_text

FACET_KINDS = (
    ("jurisdiction", "HAS_JURISDICTION", "jurisdiction"),
    ("law_id", "HAS_LAW_ID", "law_id"),
    ("language", "HAS_LANGUAGE", "language"),
    ("source", "HAS_SOURCE", "source_type"),
)
ADJ_POINTERS_PER_ROW = 4096
ADJ_POINTERS_PER_SHARD = 8192


def _facet_cid(kind: str, value: str) -> str:
    return cid_of_text("facet", kind, value)


def _edge_cid(source: str, edge_type: str, target: str) -> str:
    return cid_of_text("edge", source, edge_type, target)


def build_graph(
    corpus: pd.DataFrame,
    neighbors: list[list[tuple[int, float]]],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_facets: set[str] = set()
    cid_by_idx = corpus["entry_cid"].tolist()
    type_by_idx = corpus["record_type"].tolist()
    law_cid_by_id: dict[str, str] = {}
    for _, row in corpus.iterrows():
        if row["record_type"] == "law":
            law_cid_by_id[row["law_id"]] = row["entry_cid"]

    for _, row in corpus.iterrows():
        node_type = "law" if row["record_type"] == "law" else "article"
        nodes.append(
            {
                "node_cid": row["entry_cid"],
                "node_type": node_type,
                "entry_cid": row["entry_cid"],
                "label": row["title"] or row["source_id"],
                "properties_json": _props(row),
                "schema_version": SCHEMA_VERSION,
            }
        )
        src = row["entry_cid"]
        for kind, edge_type, col in FACET_KINDS:
            value = str(row.get(col) or "").strip()
            if not value:
                continue
            fc = _facet_cid(kind, value)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": f"facet_{kind}",
                        "entry_cid": "",
                        "label": f"{kind}:{value}",
                        "properties_json": _json({"kind": kind, "value": value}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(_edge(src, edge_type, fc, "facet", 1.0, {"facet": kind, "value": value}))

        if row["record_type"] == "article" and row.get("parent_law_id"):
            parent = law_cid_by_id.get(row["parent_law_id"])
            if parent:
                edges.append(
                    _edge(
                        row["entry_cid"],
                        "CONTAINED_IN",
                        parent,
                        "structural",
                        1.0,
                        {"law_id": row["parent_law_id"]},
                    )
                )

    for i, neigh in enumerate(neighbors):
        src = cid_by_idx[i]
        for j, score in neigh:
            tgt = cid_by_idx[j]
            edges.append(
                _edge(
                    src,
                    "BM25_NEIGHBOR_OF",
                    tgt,
                    "bm25",
                    float(score),
                    {"k": 8, "neighbor_index": j},
                )
            )

    nodes_df = pd.DataFrame(nodes).drop_duplicates("node_cid").reset_index(drop=True)
    nodes_df = nodes_df.sort_values(["node_type", "node_cid"]).reset_index(drop=True)
    edges_df = pd.DataFrame(edges)
    if not edges_df.empty:
        edges_df = edges_df.drop_duplicates("edge_cid").reset_index(drop=True)
        edges_df = edges_df.sort_values(["edge_type", "source_cid", "target_cid"]).reset_index(drop=True)

    node_type = {r["node_cid"]: r["node_type"] for r in nodes_df.to_dict("records")}
    incoming, outgoing = _adjacency(edges_df, node_type)
    return {
        "nodes": nodes_df,
        "edges": edges_df,
        "incoming": incoming,
        "outgoing": outgoing,
        "stats": {
            "n_nodes": int(len(nodes_df)),
            "n_edges": int(len(edges_df)),
            "n_doc_nodes": int((nodes_df["node_type"].isin(["law", "article"])).sum()),
            "n_facet_nodes": int(nodes_df["node_type"].astype(str).str.startswith("facet_").sum()),
        },
    }


def _json(obj: dict) -> str:
    import json

    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _props(row: pd.Series) -> str:
    keys = [
        "record_type",
        "law_id",
        "source_id",
        "jurisdiction",
        "country",
        "language",
        "source_type",
        "source_url",
        "identifier",
        "official_identifier",
        "article_number",
    ]
    return _json({k: ("" if pd.isna(row.get(k)) else str(row.get(k))) for k in keys})


def _edge(src: str, etype: str, tgt: str, method: str, score: float, props: dict) -> dict[str, Any]:
    return {
        "edge_cid": _edge_cid(src, etype, tgt),
        "edge_type": etype,
        "source_cid": src,
        "target_cid": tgt,
        "retrieval_method": method,
        "score": float(score),
        "query_terms_json": "[]",
        "properties_json": _json(props),
        "schema_version": SCHEMA_VERSION,
    }


def _adjacency(edges: pd.DataFrame, node_type: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    out_map: dict[str, list[tuple[float, str, str, str]]] = defaultdict(list)
    in_map: dict[str, list[tuple[float, str, str, str]]] = defaultdict(list)
    if edges is None or edges.empty:
        return pd.DataFrame(), pd.DataFrame()
    for rec in edges.itertuples(index=False):
        score = float(rec.score) if rec.score == rec.score else float("-inf")
        out_map[rec.source_cid].append((score, rec.target_cid, rec.edge_type, rec.edge_cid))
        in_map[rec.target_cid].append((score, rec.source_cid, rec.edge_type, rec.edge_cid))

    def pages(mapping: dict[str, list], direction: str) -> pd.DataFrame:
        rows = []
        for node, items in mapping.items():
            items = sorted(items, key=lambda t: (-t[0] if t[0] == t[0] else float("inf"), t[1]))
            total = len(items)
            page_size = ADJ_POINTERS_PER_ROW
            n_pages = max(1, (total + page_size - 1) // page_size)
            for p in range(n_pages):
                chunk = items[p * page_size : (p + 1) * page_size]
                rows.append(
                    {
                        "direction": direction,
                        "node_cid": node,
                        "page_index": p,
                        "page_count": n_pages,
                        "neighbor_count": len(chunk),
                        "total_neighbor_count": total,
                        "neighbor_cids": [t[1] for t in chunk],
                        "neighbor_node_types": [node_type.get(t[1], "") for t in chunk],
                        "edge_types": [t[2] for t in chunk],
                        "edge_cids": [t[3] for t in chunk],
                        "retrieval_methods": ["graph"] * len(chunk),
                        "scores": [t[0] if t[0] != float("-inf") else None for t in chunk],
                        "schema_version": SCHEMA_VERSION,
                    }
                )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["node_cid", "page_index"]).reset_index(drop=True)

    return pages(in_map, "incoming"), pages(out_map, "outgoing")
