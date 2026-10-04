#!/usr/bin/env python3
"""Read US Code citation edges for the entity stitch.

The logic index already lives on justicedao/uscode-autoformal-entity-cache.
This script does not upload kg-meta-ontology.parquet and does not replace
kg-logic-index.parquet. A citation read is not a legal admit.
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
                str(record.get("node_cid") or record.get("node_id") or record.get("id") or ""),
            )
        return
    columns = [name for name in ("node_type", "label", "legal_id", "node_cid", "node_id") if name in names]
    for row in table.select(columns).to_pylist():
        yield (
            str(row.get("node_type") or ""),
            str(row.get("label") or row.get("legal_id") or ""),
            str(row.get("legal_id") or ""),
            str(row.get("node_cid") or row.get("node_id") or ""),
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
    columns = [name for name in ("record_kind", "edge_type", "graph_kind", "src", "dst") if name in names]
    for row in table.select(columns).to_pylist():
        if "record_kind" in row and str(row.get("record_kind") or "") not in {"edge", ""}:
            continue
        kind = str(row.get("edge_type") or row.get("graph_kind") or "")
        yield (kind, str(row.get("src") or ""), str(row.get("dst") or ""))


def read_graph_cites(table) -> list[dict]:
    """CITES and CITES_UNRESOLVED from a graph table. Other edges stay out."""

    legal_by_node = {}
    for _node_type, _label, legal_id, node_id in _nodes(table):
        if node_id and legal_id:
            legal_by_node[node_id] = legal_id
    cites = []
    for edge_type, src, dst in _edges(table):
        if edge_type not in {"CITES", "CITES_UNRESOLVED"}:
            continue
        source = legal_by_node.get(src, src)
        target = legal_by_node.get(dst, dst)
        unresolved = edge_type == "CITES_UNRESOLVED" or not target
        cites.append(
            {
                "source_legal_id": source,
                "target_legal_id": "" if unresolved else target,
                "unresolved": unresolved,
            }
        )
    return cites


def main(argv=None) -> int:
    """Read a local logic index. Never upload kg-meta-ontology.parquet."""

    import argparse
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logic-index", type=Path)
    args = parser.parse_args(argv)
    if args.logic_index is None or args.logic_index.name != "kg-logic-index.parquet":
        print("refusing to upload autoformal/uscode/kg-meta-ontology.parquet", flush=True)
        return 2
    cites = read_graph_cites(pq.read_table(args.logic_index))
    print(
        json.dumps(
            {"admitted": False, "cites": len(cites), "formalized": False, "uploaded": False},
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
