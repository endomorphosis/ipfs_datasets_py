#!/usr/bin/env python3
"""Cross-audit CID coverage across all complete SkillCenter indexes."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_graph import (  # noqa: E402
    SkillCenterCIDGraphIndex,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_vectors import (  # noqa: E402
    SkillCenterCIDVectorIndex,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus import (  # noqa: E402
    SKILLCENTER_CORPUS_PRIMARY_KEY,
    SkillCenterCorpusIndex,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus_bm25 import (  # noqa: E402
    SkillCenterCorpusBM25Index,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (  # noqa: E402
    INSPECTED_SKILLCENTER_PILOT_REVISION,
)


DEFAULT_REVISION = INSPECTED_SKILLCENTER_PILOT_REVISION
EXPECTED_FULL_RECORDS = 216_972


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _xdg_path(environment_name: str, fallback: str) -> Path:
    configured = str(os.environ.get(environment_name) or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path(fallback).expanduser()
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rehash all complete SkillCenter artifacts and prove that corpus, "
            "BM25, graph Skill nodes, and FAISS metadata contain exactly the "
            "same entry_cid primary-key set."
        )
    )
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--bm25-dir", type=Path, default=None)
    parser.add_argument("--graph-dir", type=Path, default=None)
    parser.add_argument("--vector-dir", type=Path, default=None)
    parser.add_argument(
        "--expected-records",
        type=_positive_int,
        default=EXPECTED_FULL_RECORDS,
    )
    parser.add_argument(
        "--verify-corpus-rows",
        action="store_true",
        help="Recompute every canonical corpus row CID in addition to file hashes.",
    )
    return parser


def _graph_skill_cids(graph: SkillCenterCIDGraphIndex) -> frozenset[str]:
    uri = f"{graph.database_path.as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT node_cid FROM nodes "
                "WHERE node_type = 'SKILL' AND node_cid = entry_cid"
            )
        )


def _bm25_cids(bm25: SkillCenterCorpusBM25Index) -> frozenset[str]:
    uri = f"{bm25.database_path.as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT entry_cid FROM documents"
            )
        )


def _manifest_sha256(root: Path) -> str:
    return hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data_home = _xdg_path("XDG_DATA_HOME", "~/.local/share")
    base = data_home / "ipfs_datasets_py/intent-ir"
    corpus_dir = args.corpus_dir or (
        base / "skillcenter-corpus" / args.revision / "full"
    )
    bm25_dir = args.bm25_dir or (
        base / "skillcenter-bm25" / args.revision / "full-cid"
    )
    graph_dir = args.graph_dir or (
        base
        / "skillcenter-graphrag"
        / args.revision
        / "full-cid-bm25"
    )
    vector_dir = args.vector_dir or (
        base
        / "skillcenter-vectors"
        / args.revision
        / "full-cid"
        / "thenlper-gte-small-cuda"
    )

    corpus = SkillCenterCorpusIndex.load(
        corpus_dir,
        verify_rows=args.verify_corpus_rows,
    )
    bm25 = SkillCenterCorpusBM25Index.load(bm25_dir)
    graph = SkillCenterCIDGraphIndex.load(graph_dir)
    vectors = SkillCenterCIDVectorIndex.load(vector_dir)

    expected_cids = corpus.entry_cids
    bm25_cids = _bm25_cids(bm25)
    graph_cids = _graph_skill_cids(graph)
    vector_cids = frozenset(
        str(row["entry_cid"]) for row in vectors.metadata_rows
    )
    expected_count = int(args.expected_records)
    counts = {
        "bm25": bm25.summary.indexed_entries,
        "corpus": corpus.summary.source_records,
        "graph": graph.summary.skill_nodes,
        "vectors": vectors.summary.vector_count,
    }
    if set(counts.values()) != {expected_count}:
        raise ValueError(
            f"index counts do not all equal {expected_count}: {counts}"
        )
    if (
        bm25_cids != expected_cids
        or graph_cids != expected_cids
        or vector_cids != expected_cids
    ):
        raise ValueError("entry_cid sets differ across complete indexes")

    corpus_manifest_sha256 = _manifest_sha256(corpus.root)
    bm25_manifest_sha256 = _manifest_sha256(bm25.root)
    corpus_cid = str(corpus.manifest["files"]["corpus"]["cid"])
    expected_bm25_corpus_input = {
        "corpus_cid": corpus_cid,
        "manifest_sha256": corpus_manifest_sha256,
        "primary_key": str(corpus.manifest["primary_key"]),
        "source_records": int(corpus.manifest["source_records"]),
        "unique_entry_cids": int(corpus.manifest["unique_entry_cids"]),
    }
    expected_graph_corpus_input = {
        "corpus_cid": corpus_cid,
        "manifest_sha256": corpus_manifest_sha256,
        "primary_key": str(corpus.manifest["primary_key"]),
        "source_records": int(corpus.manifest["source_records"]),
    }
    expected_vector_corpus_input = {
        "corpus_cid": corpus_cid,
        "manifest_sha256": corpus_manifest_sha256,
        "source_records": int(corpus.manifest["source_records"]),
    }
    expected_graph_bm25_input = {
        "indexed_entries": int(bm25.manifest["indexed_entries"]),
        "manifest_sha256": bm25_manifest_sha256,
        "primary_key": str(bm25.manifest["primary_key"]),
        "sqlite_cid": str(bm25.manifest["sqlite"]["cid"]),
    }
    input_bindings = {
        "bm25_to_corpus": (
            bm25.manifest.get("corpus_input")
            == expected_bm25_corpus_input
        ),
        "graph_to_bm25": (
            graph.manifest.get("bm25_input")
            == expected_graph_bm25_input
        ),
        "graph_to_corpus": (
            graph.manifest.get("corpus_input")
            == expected_graph_corpus_input
        ),
        "vectors_to_corpus": (
            vectors.manifest.get("corpus_input")
            == expected_vector_corpus_input
        ),
    }
    if not all(input_bindings.values()):
        raise ValueError(f"artifact input bindings differ: {input_bindings}")

    primary_keys = {
        "bm25": bm25.summary.primary_key,
        "corpus": str(corpus.manifest["primary_key"]),
        "graph": str(graph.manifest["primary_key"]),
        "vectors": vectors.summary.primary_key,
    }
    if set(primary_keys.values()) != {SKILLCENTER_CORPUS_PRIMARY_KEY}:
        raise ValueError(f"primary-key declarations differ: {primary_keys}")
    revisions = {
        "bm25": bm25.summary.dataset_revision,
        "corpus": corpus.summary.dataset_revision,
        "graph": graph.summary.dataset_revision,
        "vectors": vectors.summary.dataset_revision,
    }
    if set(revisions.values()) != {args.revision}:
        raise ValueError(f"dataset revisions differ: {revisions}")

    print(
        json.dumps(
            {
                "artifact_cids": {
                    "bm25_sqlite": bm25.summary.sqlite_cid,
                    "corpus_parquet": corpus.summary.corpus_cid,
                    "graph_root": graph.summary.graph_cid,
                    "graph_sqlite": graph.summary.sqlite_cid,
                    "vectors_faiss": vectors.summary.faiss_cid,
                },
                "counts": counts,
                "dataset_revision": args.revision,
                "entry_cid_set_equal": True,
                "input_bindings": input_bindings,
                "primary_key": SKILLCENTER_CORPUS_PRIMARY_KEY,
                "primary_keys": primary_keys,
                "revisions": revisions,
                "verified_cids": len(expected_cids),
                "verified_corpus_rows": bool(args.verify_corpus_rows),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
