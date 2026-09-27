#!/usr/bin/env python3
"""Publish the US Code knowledge graph under the deontic meta-ontology.

Reads nodes and edges already stored in justicedao/ipfs_uscode. Does not invent
named-entity nodes. Participant, act, state, and object stay category
definitions until span rules fill them. Not a legal admit.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

REPO = "justicedao/ipfs_uscode"
REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
TARGET = "justicedao/uscode-autoformal-entity-cache"
TARGET_PATH = "autoformal/uscode/kg-meta-ontology.parquet"


def _files(prefix: str) -> list[str]:
    from huggingface_hub import HfApi

    names = HfApi().list_repo_files(REPO, repo_type="dataset", revision=REVISION)
    return sorted(name for name in names if name.startswith(prefix) and name.endswith(".parquet"))


def _nodes(table):
    names = set(table.schema.names)
    if "record_json" in names:
        for raw in table.column("record_json").to_pylist():
            record = json.loads(raw)
            yield (
                str(record.get("node_type") or ""),
                str(record.get("label") or record.get("legal_id") or ""),
                str(record.get("legal_id") or ""),
                str(record.get("node_cid") or record.get("id") or ""),
            )
        return
    columns = [name for name in ("node_type", "label", "legal_id", "node_cid") if name in names]
    for row in table.select(columns).to_pylist():
        yield (
            str(row.get("node_type") or ""),
            str(row.get("label") or row.get("legal_id") or ""),
            str(row.get("legal_id") or ""),
            str(row.get("node_cid") or ""),
        )


def _edges(table):
    names = set(table.schema.names)
    if "record_json" in names:
        for raw in table.column("record_json").to_pylist():
            record = json.loads(raw)
            yield (
                str(record.get("edge_type") or record.get("type") or ""),
                str(record.get("src") or record.get("source") or ""),
                str(record.get("dst") or record.get("target") or ""),
            )
        return
    for row in table.select([name for name in ("edge_type", "src", "dst") if name in names]).to_pylist():
        yield (str(row.get("edge_type") or ""), str(row.get("src") or ""), str(row.get("dst") or ""))


def main() -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    from ipfs_datasets_py.logic.autoformal.meta_ontology import (
        CATEGORIES,
        graph_edge_category,
        graph_node_category,
    )

    destination = Path("/tmp/ipfs-uscode-ontology/kg-meta-ontology.parquet")
    destination.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("record_kind", pa.string()),
            ("meta_category", pa.string()),
            ("graph_kind", pa.string()),
            ("label", pa.string()),
            ("legal_id", pa.string()),
            ("node_id", pa.string()),
            ("src", pa.string()),
            ("dst", pa.string()),
            ("admitted", pa.bool_()),
            ("formalized", pa.bool_()),
        ]
    )

    def batch(rows: list[dict]) -> pa.RecordBatch:
        return pa.RecordBatch.from_pylist(rows, schema=schema)

    counts = {"category": 0, "node": 0, "edge": 0}
    with pq.ParquetWriter(destination, schema) as writer:
        categories = [
            {
                "admitted": False,
                "dst": "",
                "formalized": False,
                "graph_kind": name,
                "label": spec["definition"],
                "legal_id": "",
                "meta_category": name,
                "node_id": "",
                "record_kind": "category",
                "src": "",
            }
            for name, spec in CATEGORIES.items()
        ]
        writer.write_batch(batch(categories))
        counts["category"] = len(categories)
        for name in _files("data/graph/nodes/"):
            path = hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION)
            rows = []
            for node_type, label, legal_id, node_id in _nodes(pq.read_table(path)):
                rows.append(
                    {
                        "admitted": False,
                        "dst": "",
                        "formalized": False,
                        "graph_kind": node_type,
                        "label": label,
                        "legal_id": legal_id,
                        "meta_category": graph_node_category(node_type),
                        "node_id": node_id,
                        "record_kind": "node",
                        "src": "",
                    }
                )
            if rows:
                writer.write_batch(batch(rows))
                counts["node"] += len(rows)
            print(f"NODES file={name} total={counts['node']}", flush=True)
        for name in _files("data/graph/edges/"):
            path = hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION)
            rows = []
            for edge_type, src, dst in _edges(pq.read_table(path)):
                rows.append(
                    {
                        "admitted": False,
                        "dst": dst,
                        "formalized": False,
                        "graph_kind": edge_type,
                        "label": edge_type,
                        "legal_id": "",
                        "meta_category": graph_edge_category(edge_type),
                        "node_id": "",
                        "record_kind": "edge",
                        "src": src,
                    }
                )
            if rows:
                writer.write_batch(batch(rows))
                counts["edge"] += len(rows)
            print(f"EDGES file={name} total={counts['edge']}", flush=True)
    print(f"WROTE {destination} {counts} bytes={destination.stat().st_size}", flush=True)
    api = HfApi()
    existing = set(api.list_repo_files(TARGET, repo_type="dataset"))
    for old in ("autoformal/uscode/entity-resume-checkpoint.parquet", "autoformal/uscode/meta-ontology.parquet"):
        if old in existing:
            api.delete_file(path_in_repo=old, repo_id=TARGET, repo_type="dataset", commit_message=f"remove {old}")
            print(f"DELETED {old}", flush=True)
    info = api.upload_file(
        path_or_fileobj=str(destination),
        path_in_repo=TARGET_PATH,
        repo_id=TARGET,
        repo_type="dataset",
        commit_message="capture US Code knowledge graph under the meta-ontology",
    )
    print("uploaded", getattr(info, "commit_url", None) or "ok", flush=True)
    print("files", api.list_repo_files(TARGET, repo_type="dataset"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
