#!/usr/bin/env python3
"""Build pinned GTE-small vectors and true centroid routes for LCR-071.

Embeds hash-verified live Federal Register bodies with the sealed
thenlper/gte-small revision, then binds deterministic balanced spherical
k-means routes (8192/4096/2 bounds). Does not rewrite the sealed fixture
``federal_vectors.json``. Does not upload to Hub.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PRODUCTION_BACKEND,
    PROJECTION_BACKEND,
    bind_federal_register_vectors,
    default_embedding_config,
    generate_federal_register_embeddings,
    production_embedding_config,
    production_vector_bounds,
)


TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_LIVE_DOCUMENTS = 11784
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
DEFAULT_VECTOR_DIR = Path("/var/tmp/lcr-071-fr-vectors")
VECTORS_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_vectors.live.json")
MAX_TEXT_CHARS = 2500
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class LiveVectorError(RuntimeError):
    pass


def _plain_text(html: str) -> str:
    stripped = _TAG_RE.sub(" ", html or "").replace("\x00", " ")
    return _WS_RE.sub(" ", stripped).strip()


def _load_index(corpus_dir: Path) -> list[dict[str, Any]]:
    path = corpus_dir / "index.jsonl"
    if not path.is_file():
        raise LiveVectorError(f"corpus index missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("status") == "verified":
                rows.append(item)
    return rows


def _chunks_from_corpus(
    corpus_dir: Path, rows: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for row in rows:
        legal_id = str(row["legal_id"])
        content_hash = str(row.get("content_hash") or "")
        if len(content_hash) != 64:
            raise LiveVectorError(f"invalid content_hash for {legal_id}")
        body_path = corpus_dir / str(row.get("path") or "")
        payload = json.loads(body_path.read_text(encoding="utf-8"))
        text = _plain_text(str(payload.get("text") or ""))[:MAX_TEXT_CHARS]
        if not text:
            raise LiveVectorError(f"empty body for {legal_id}")
        cid = f"sha256:{content_hash}"
        chunks.append(
            {
                "chunk_cid": cid,
                "entry_cid": cid,
                "chunk_id": legal_id,
                "legal_id": legal_id,
                "text": text,
                "section": legal_id.split(":")[1] if ":" in legal_id else legal_id,
            }
        )
    return chunks


def build_live_vectors(
    *,
    corpus_dir: Path,
    vector_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
    require_complete: bool = True,
    limit: int | None = None,
    backend: str = PRODUCTION_BACKEND,
    write_receipt: bool = True,
) -> dict[str, Any]:
    rows = _load_index(corpus_dir)
    if limit is not None:
        rows = rows[:limit]
    if require_complete and limit is None and len(rows) != EXPECTED_LIVE_DOCUMENTS:
        raise LiveVectorError(
            f"live vectors require {EXPECTED_LIVE_DOCUMENTS} verified bodies, got {len(rows)}"
        )
    if not rows:
        raise LiveVectorError("no verified corpus bodies")
    chunks = _chunks_from_corpus(corpus_dir, rows)
    if backend == PRODUCTION_BACKEND:
        config = production_embedding_config()
    elif backend in {PROJECTION_BACKEND, "projection", "deterministic"}:
        config = default_embedding_config()
    else:
        raise LiveVectorError(f"unsupported embedding backend: {backend!r}")
    result = generate_federal_register_embeddings(chunks, config=config)
    missing = list(result.missing or [])
    if missing:
        raise LiveVectorError(f"missing embeddings: {len(missing)}")
    binding = bind_federal_register_vectors(result, config=config)
    layout = binding.layout
    actual_max_centroid = max((group.row_count for group in layout.clusters), default=0)
    actual_max_shard = max((shard.row_count for shard in layout.shards), default=0)
    actual_max_shards_per_centroid = max(
        (group.shard_count for group in layout.clusters), default=0
    )
    bounds = production_vector_bounds()
    bounds_hold = (
        actual_max_centroid <= int(bounds["maximum_rows_per_vector_centroid"])
        and actual_max_shard <= int(bounds["maximum_rows_per_physical_shard"])
        and actual_max_shards_per_centroid <= int(bounds["maximum_shards_per_centroid"])
        and layout.dimension == PINNED_DIMENSION
        and len(result.embeddings) == len(chunks)
    )
    vector_dir.mkdir(parents=True, exist_ok=True)
    ids_path = vector_dir / "ids.jsonl"
    vectors_path = vector_dir / "vectors.npy"
    assignments_path = vector_dir / "assignments.jsonl"
    matrix = np.zeros((len(chunks), PINNED_DIMENSION), dtype=np.float32)
    with ids_path.open("w", encoding="utf-8") as handle:
        for index, chunk in enumerate(chunks):
            cid = chunk["chunk_cid"]
            record = result.embeddings[cid]
            matrix[index] = np.asarray(record.embedding, dtype=np.float32)
            handle.write(
                json.dumps(
                    {
                        "legal_id": chunk["legal_id"],
                        "chunk_cid": cid,
                        "row": index,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    np.save(vectors_path, matrix)
    cid_to_legal = {chunk["chunk_cid"]: chunk["legal_id"] for chunk in chunks}
    with assignments_path.open("w", encoding="utf-8") as handle:
        for group in layout.clusters:
            for shard in group.shards:
                for offset, entry_cid in enumerate(shard.entry_cids):
                    handle.write(
                        json.dumps(
                            {
                                "legal_id": cid_to_legal.get(entry_cid, ""),
                                "chunk_cid": entry_cid,
                                "cluster_id": group.cluster_id,
                                "shard_id": shard.global_shard_id,
                                "row_offset": offset,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
    routing_path = vector_dir / "routing_index.jsonl"
    with routing_path.open("w", encoding="utf-8") as handle:
        for group in layout.clusters:
            for shard in group.shards:
                handle.write(
                    json.dumps(
                        {
                            "cluster_id": group.cluster_id,
                            "shard_id": shard.global_shard_id,
                            "row_count": shard.row_count,
                            "first_key": shard.entry_cids[0] if shard.entry_cids else "",
                            "last_key": shard.entry_cids[-1] if shard.entry_cids else "",
                            "relative_path": shard.relative_path,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
    complete = limit is None and len(chunks) == EXPECTED_LIVE_DOCUMENTS
    report: dict[str, Any] = {
        "schema": "ipfs_datasets_py/federal-register-live-vectors@1",
        "producer": "build_federal_register_live_vectors.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "mode": "live",
        "fixture_only": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "backend": config.backend,
        "provider": config.provider,
        "device": config.device,
        "model_id": PINNED_MODEL_ID,
        "model_revision": PINNED_MODEL_REVISION,
        "dimension": PINNED_DIMENSION,
        "pooling": "mean",
        "normalization": "l2",
        "vector_space_id": config.vector_space_id,
        "vector_count": len(chunks),
        "expected_documents": EXPECTED_LIVE_DOCUMENTS,
        "complete": complete,
        "cluster_count": layout.cluster_count,
        "shard_count": layout.shard_count,
        "assignment": layout.assignment,
        "layout_seed": layout.seed,
        "max_centroid_rows": actual_max_centroid,
        "max_shard_rows": actual_max_shard,
        "max_shards_per_centroid": actual_max_shards_per_centroid,
        "centroid_bounds_hold": bounds_hold,
        "bounds": bounds,
        "vector_root_cid": binding.vector_root_cid,
        "config_cid": binding.config_cid,
        "ids_path": str(ids_path),
        "vectors_path": str(vectors_path),
        "assignments_path": str(assignments_path),
        "routing_path": str(routing_path),
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "status": "passed" if complete and bounds_hold else "partial",
    }
    report["content_digest"] = digest_mapping(
        {k: v for k, v in report.items() if k != "content_digest"}
    )
    (vector_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if write_receipt:
        out = repository_root / VECTORS_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["receipt_path"] = VECTORS_RELPATH.as_posix()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build live FR GTE-small vectors")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--backend", default=PRODUCTION_BACKEND)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--no-write-receipt", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    require_complete = not bool(args.allow_partial) and args.limit is None
    try:
        report = build_live_vectors(
            corpus_dir=args.corpus_dir,
            vector_dir=args.vector_dir,
            repository_root=args.repository_root,
            require_complete=require_complete,
            limit=args.limit,
            backend=str(args.backend),
            write_receipt=not bool(args.no_write_receipt),
        )
    except LiveVectorError as exc:
        sys.stderr.write(f"build_federal_register_live_vectors: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "build_federal_register_live_vectors: "
            f"{report['status'].upper()} vectors={report['vector_count']} "
            f"clusters={report['cluster_count']} backend={report['backend']}\n"
        )
    return 0 if report["status"] in {"passed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
