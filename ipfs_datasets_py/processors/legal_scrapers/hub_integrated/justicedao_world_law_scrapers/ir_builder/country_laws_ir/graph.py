"""Property graph: entry nodes, facet nodes, BM25_NEIGHBOR_OF k=8, ARTICLE_OF, ELI."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from . import EDGE_IDENTITY_SCHEMA, FACET_IDENTITY_SCHEMA, SCHEMA_VERSION
from .cidutil import cid_of_json

# Facet kinds requested by the SkillCenter-style country-laws graph:
# jurisdiction, language, instrument/law, source, status.
FACET_FIELDS = (
    ("jurisdiction", "HAS_JURISDICTION", "jurisdiction"),
    ("language", "HAS_LANGUAGE", "language"),
    ("instrument", "HAS_INSTRUMENT", "instrument_id"),
    ("source", "HAS_SOURCE", "source_type"),
    ("status", "HAS_STATUS", "law_status"),
)
ADJ_POINTERS_PER_ROW = 4096
ADJ_POINTERS_PER_SHARD = 8192


def _facet_cid(kind: str, value: str) -> str:
    """CIDv1 raw sha2-256 of sorted JSON {kind, schema, value}."""
    return cid_of_json(
        {
            "kind": kind,
            "schema": FACET_IDENTITY_SCHEMA,
            "value": value,
        }
    )


def _edge_cid(source: str, edge_type: str, target: str) -> str:
    return cid_of_json(
        {
            "edge_type": edge_type,
            "schema": EDGE_IDENTITY_SCHEMA,
            "source": source,
            "target": target,
        }
    )


def build_graph(
    corpus: pd.DataFrame,
    neighbors: list[list[tuple]],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_facets: set[str] = set()
    cid_by_idx = corpus["entry_cid"].tolist()

    # Law identity nodes (targets of ARTICLE_OF when the parent is not a corpus entry).
    law_nodes: dict[str, dict[str, Any]] = {}
    entry_by_instrument: dict[str, str] = {}
    for rec in corpus.itertuples(index=False):
        law_cid = str(getattr(rec, "law_cid", "") or "")
        instrument_id = str(getattr(rec, "instrument_id", "") or "")
        if getattr(rec, "record_type", "") == "law" and instrument_id and rec.entry_cid:
            entry_by_instrument.setdefault(instrument_id, rec.entry_cid)
        if not law_cid or law_cid in law_nodes:
            continue
        law_nodes[law_cid] = {
            "node_cid": law_cid,
            "node_type": "law",
            "entry_cid": "",
            "label": getattr(rec, "instrument_title", None) or instrument_id,
            "properties_json": _json(
                {
                    "instrument_id": instrument_id,
                    "instrument_title": str(getattr(rec, "instrument_title", "") or ""),
                    "jurisdiction": str(getattr(rec, "jurisdiction", "") or ""),
                    "language": str(getattr(rec, "language", "") or ""),
                    "law_cid": law_cid,
                }
            ),
            "schema_version": SCHEMA_VERSION,
        }

    for law_node in law_nodes.values():
        nodes.append(law_node)

    for rec in corpus.itertuples(index=False):
        node_type = "law_entry" if rec.record_type == "law" else "article"
        title = getattr(rec, "title", None) or getattr(rec, "instrument_title", None) or rec.source_id
        nodes.append(
            {
                "node_cid": rec.entry_cid,
                "node_type": node_type,
                "entry_cid": rec.entry_cid,
                "label": title,
                "properties_json": _props_tuple(rec),
                "schema_version": SCHEMA_VERSION,
            }
        )
        src = rec.entry_cid
        row_map = rec._asdict() if hasattr(rec, "_asdict") else {}

        for kind, edge_type, col in FACET_FIELDS:
            value = str(row_map.get(col) or "").strip()
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

        # ELI / identifier links — only values present in the source, never invented.
        eli = str(row_map.get("eli") or "").strip()
        if eli:
            fc = _facet_cid("eli", eli)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": "facet_eli",
                        "entry_cid": "",
                        "label": f"eli:{eli}",
                        "properties_json": _json({"kind": "eli", "value": eli}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(_edge(src, "IDENTIFIED_BY_ELI", fc, "identifier", 1.0, {"eli": eli}))
        ident = str(row_map.get("official_identifier") or row_map.get("identifier") or "").strip()
        if ident and ident != eli:
            fc = _facet_cid("identifier", ident)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": "facet_identifier",
                        "entry_cid": "",
                        "label": f"identifier:{ident}",
                        "properties_json": _json({"kind": "identifier", "value": ident}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(
                _edge(src, "IDENTIFIED_BY", fc, "identifier", 1.0, {"identifier": ident})
            )

        law_cid = str(row_map.get("law_cid") or "")
        instrument_id = str(row_map.get("instrument_id") or "")
        if rec.record_type == "article":
            parent = entry_by_instrument.get(instrument_id) or law_cid
            if parent and parent != rec.entry_cid:
                edges.append(
                    _edge(
                        rec.entry_cid,
                        "ARTICLE_OF",
                        parent,
                        "structural",
                        1.0,
                        {
                            "instrument_id": instrument_id,
                            "article_number": row_map.get("article_number"),
                        },
                    )
                )
        elif law_cid and rec.entry_cid != law_cid:
            # Law-level corpus unit still points at its instrument identity node.
            edges.append(
                _edge(
                    rec.entry_cid,
                    "HAS_INSTRUMENT",
                    law_cid,
                    "structural",
                    1.0,
                    {"instrument_id": instrument_id},
                )
            )

    for i, neigh in enumerate(neighbors):
        src = cid_by_idx[i]
        for item in neigh:
            if len(item) == 3:
                j, score, terms = item
            else:
                j, score = item[0], item[1]
                terms = []
            tgt = cid_by_idx[int(j)]
            edges.append(
                _edge(
                    src,
                    "BM25_NEIGHBOR_OF",
                    tgt,
                    "bm25-okapi",
                    float(score),
                    {"k": 8, "neighbor_index": int(j)},
                    matched_terms=list(terms),
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
            "n_doc_nodes": int(nodes_df["node_type"].isin(["law_entry", "article", "law"]).sum()),
            "n_facet_nodes": int(nodes_df["node_type"].astype(str).str.startswith("facet_").sum()),
            "edge_types": sorted(edges_df["edge_type"].unique().tolist()) if not edges_df.empty else [],
        },
    }


def _json(obj: dict) -> str:
    import json

    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _props_tuple(rec: Any) -> str:
    keys = [
        "record_type",
        "instrument_id",
        "instrument_title",
        "law_cid",
        "article_number",
        "article_title",
        "jurisdiction",
        "language",
        "source_url",
        "snapshot_date",
        "coverage",
        "license",
        "collector",
        "source_id",
        "eli",
        "law_status",
        "source_type",
    ]
    d = rec._asdict() if hasattr(rec, "_asdict") else {}
    out = {}
    for k in keys:
        v = d.get(k, "")
        if v is None or (isinstance(v, float) and pd.isna(v)):
            v = ""
        out[k] = str(v)
    return _json(out)


def _edge(
    src: str,
    etype: str,
    tgt: str,
    method: str,
    score: float,
    props: dict,
    matched_terms: list[str] | None = None,
) -> dict[str, Any]:
    import json

    terms = matched_terms or []
    return {
        "edge_cid": _edge_cid(src, etype, tgt),
        "edge_type": etype,
        "source_cid": src,
        "target_cid": tgt,
        "retrieval_method": method,
        "score": float(score),
        "query_terms_json": json.dumps(terms, ensure_ascii=False, separators=(",", ":")),
        "matched_terms": terms,
        "properties_json": _json({k: v for k, v in props.items() if v is not None}),
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
