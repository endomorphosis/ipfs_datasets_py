#!/usr/bin/env python3
"""Build a full (~60k-row) US Code sparse GraphRAG HF release from baseline laws.parquet.

Operator-oriented end-to-end pipeline:
  1. Load justicedao/ipfs_uscode ``uscode_parquet/laws.parquet`` (baseline pin)
  2. Materialize admitted corpus + recovery quarantine
  3. Build BM25, deterministic embeddings, centroid vector binding, legal graph
  4. Package additive publicus-ir-graphrag/v2 release (no Hub upload here)

Upload remains a separate explicit step so production mutation stays gated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_bm25 import (  # noqa: E402
    build_uscode_bm25_index,
)
from ipfs_datasets_py.processors.legal_data.uscode_corpus import (  # noqa: E402
    materialize_uscode_corpus,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (  # noqa: E402
    AdmittedChunk,
    DEFAULT_DIMENSION,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_LICENSE,
    DEFAULT_MODEL_REVISION,
    DeviceFallbackPolicy,
    UscodeEmbeddingConfig,
    generate_uscode_embeddings,
)
from ipfs_datasets_py.processors.legal_data.uscode_graph import (  # noqa: E402
    project_uscode_graph,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    build_uscode_hf_release,
    stage_uscode_hf_release,
    validate_uscode_hf_release,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID,
)
from ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag import (  # noqa: E402
    BASELINE_CANONICAL_CID_COUNT,
    BASELINE_CORPUS_ROW_COUNT,
)
from ipfs_datasets_py.processors.legal_data.uscode_vectors import (  # noqa: E402
    bind_uscode_vectors,
)

BASELINE_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
RELEASE_POINT = "us/pl/118/45"
ACQUIRED_AT = "2024-09-20T12:05:00Z"
DEFAULT_LAWS = (
    Path.home()
    / ".cache/huggingface/hub/datasets--justicedao--ipfs_uscode"
    / f"snapshots/{BASELINE_REVISION}/uscode_parquet/laws.parquet"
)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "to_dict"):
        return dict(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__"):
        out: dict[str, Any] = {}
        for name in obj.__dataclass_fields__:
            val = getattr(obj, name)
            if hasattr(val, "to_dict"):
                out[name] = val.to_dict()
            elif isinstance(val, Mapping):
                out[name] = dict(val)
            else:
                out[name] = val
        return out
    raise TypeError(f"cannot coerce {type(obj)!r} to dict")


def load_laws_rows(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    _log(f"loading {path}")
    table = pq.read_table(
        path,
        columns=[
            "ipfs_cid",
            "title_number",
            "section_number",
            "text",
            "source_url",
            "date_modified",
            "law_name",
            "chapter_json",
            "citations_json",
            "subsections_json",
            "legislative_history_json",
        ],
    )
    n = table.num_rows if limit is None else min(limit, table.num_rows)
    _log(f"rows in table={table.num_rows} using={n}")
    cols = {name: table.column(name) for name in table.column_names}
    rows: list[dict[str, Any]] = []
    for i in range(n):
        cid = cols["ipfs_cid"][i].as_py()
        text = cols["text"][i].as_py() or ""
        title = cols["title_number"][i].as_py()
        section = cols["section_number"][i].as_py()
        row: dict[str, Any] = {
            "title": title,
            "section": section,
            "text": text,
            "official_source_url": cols["source_url"][i].as_py(),
            "date_modified": cols["date_modified"][i].as_py(),
            "law_name": cols["law_name"][i].as_py(),
            "chapter_json": cols["chapter_json"][i].as_py(),
            "citations_json": cols["citations_json"][i].as_py(),
            "subsections_json": cols["subsections_json"][i].as_py(),
            "legislative_history_json": cols["legislative_history_json"][i].as_py(),
            "release_point": RELEASE_POINT,
            "verification_result": "verified",
            "acquisition_time": ACQUIRED_AT,
            "row_id": f"laws-{i:06d}",
        }
        if cid:
            row["ipfs_cid"] = cid
            row["entry_cid"] = cid
        else:
            # Force recovery quarantine for the 9 heterogeneous no-CID rows.
            row["is_recovery"] = True
            row["row_kind"] = "recovery"
            row["recovery_id"] = f"baseline-no-cid-{i:06d}"
            row["source_path"] = f"recovery/baseline-no-cid-{i:06d}.json"
        rows.append(row)
    return rows


def _bm25_family_rows(index: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    for doc in index.documents:
        field_lengths = {
            name: int(stream.length) for name, stream in doc.fields.items()
        }
        documents.append(
            {
                "entry_cid": doc.entry_cid,
                "legal_id": doc.legal_id,
                "field_lengths": field_lengths,
                "document_index": doc.document_index,
                "title": doc.title_code,
                "section": doc.section,
            }
        )
        # Aggregate term TF across fields for compact postings.
        tf_total: dict[str, int] = defaultdict(int)
        for stream in doc.fields.values():
            for term, tf in stream.term_frequencies().items():
                tf_total[str(term)] += int(tf)
        for term, tf in sorted(tf_total.items()):
            postings.append(
                {
                    "term": term,
                    "entry_cid": doc.entry_cid,
                    "tf": int(tf),
                }
            )
    return documents, postings


def _vector_family_rows(emb_result: Any, binding: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk_cid, record in emb_result.embeddings.items():
        rec = record if isinstance(record, Mapping) else record
        embedding = (
            list(rec.embedding)
            if hasattr(rec, "embedding")
            else list(rec.get("embedding") or [])
        )
        entry_cid = (
            getattr(rec, "entry_cid", None)
            or (rec.get("entry_cid") if isinstance(rec, Mapping) else None)
            or chunk_cid
        )
        legal_id = getattr(rec, "legal_id", None) or (
            rec.get("legal_id") if isinstance(rec, Mapping) else None
        )
        dim = getattr(rec, "dimension", None) or (
            rec.get("dimension") if isinstance(rec, Mapping) else len(embedding)
        )
        loc = binding.locations.get(chunk_cid) if binding is not None else None
        rows.append(
            {
                "entry_cid": entry_cid,
                "chunk_cid": chunk_cid,
                "legal_id": legal_id,
                "dimension": int(dim),
                "model_id": emb_result.config.model_id,
                "model_revision": emb_result.config.model_revision,
                "vector_space_id": emb_result.config.vector_space_id
                if hasattr(emb_result.config, "vector_space_id")
                else binding.vector_space_id,
                "embedding": embedding,
                "centroid_id": getattr(loc, "centroid_id", None)
                if loc is not None
                else None,
                "shard_id": getattr(loc, "shard_id", None) if loc is not None else None,
            }
        )
    return rows


def _graph_family_rows(projection: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for node in projection.nodes:
        d = _to_dict(node)
        entry = d.get("entry_cid") or d.get("node_cid")
        nodes.append(
            {
                "entry_cid": entry,
                "node_cid": d.get("node_cid") or entry,
                "legal_id": d.get("legal_id"),
                "node_type": d.get("node_type") or d.get("type"),
                "node_key": d.get("node_key"),
                "label": d.get("label"),
            }
        )
    for edge in projection.edges:
        d = _to_dict(edge)
        edges.append(
            {
                "entry_cid": d.get("edge_cid") or d.get("entry_cid"),
                "source_entry_cid": d.get("source_node_cid")
                or d.get("source_entry_cid"),
                "target_entry_cid": d.get("target_node_cid")
                or d.get("target_entry_cid"),
                "edge_type": d.get("edge_type"),
                "edge_class": d.get("edge_class"),
                "resolution_status": d.get("resolution_status"),
            }
        )
    return nodes, edges


def build_family_rows(
    *,
    laws_path: Path,
    limit: int | None,
    checkpoint_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    source_rows = load_laws_rows(laws_path, limit=limit)
    _log(f"materializing corpus from {len(source_rows)} source rows")
    corpus = materialize_uscode_corpus(
        source_rows,
        release_point=RELEASE_POINT,
        acquisition_time=ACQUIRED_AT,
        baseline_revision=BASELINE_REVISION,
        notes="full baseline laws.parquet migration",
    )
    admitted = [dict(r) for r in corpus.admitted_rows]
    recovery = [dict(r) for r in corpus.recovery_rows]
    _log(
        f"admitted={len(admitted)} recovery={len(recovery)} "
        f"ledger={len(corpus.ledger)}"
    )
    (checkpoint_dir / "admission_summary.json").write_text(
        json.dumps(corpus.admission_report(), indent=2, sort_keys=True) + "\n"
    )

    _log("building BM25 index")
    bm25 = build_uscode_bm25_index(admitted)
    bm25_docs, bm25_postings = _bm25_family_rows(bm25)
    _log(
        f"bm25 docs={bm25.document_count} terms={bm25.term_count} "
        f"postings={len(bm25_postings)}"
    )

    _log(
        f"generating embeddings model={DEFAULT_MODEL_ID} "
        f"rev={DEFAULT_MODEL_REVISION} backend=sentence_transformers device=cuda"
    )
    try:
        import torch

        _log(
            f"torch={torch.__version__} cuda_available={torch.cuda.is_available()} "
            f"cuda_built={torch.version.cuda} devices={torch.cuda.device_count()}"
        )
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA-enabled PyTorch is required for production GTE embeddings; "
                f"got torch={torch.__version__} cuda_available=False. "
                "Install a CUDA build (e.g. torch 2.13+ with CUDA 12.8/13 on aarch64)."
            )
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for production GTE embeddings") from exc

    chunks = [
        AdmittedChunk(
            chunk_cid=str(row["entry_cid"]),
            text=str(row.get("text") or ""),
            entry_cid=str(row["entry_cid"]),
            legal_id=str(row["legal_id"]) if row.get("legal_id") else None,
            title=str(row.get("title") or ""),
            section=str(row.get("section") or ""),
            heading=str(row.get("law_name") or row.get("section") or ""),
        )
        for row in admitted
    ]
    embed_config = UscodeEmbeddingConfig(
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_MODEL_REVISION,
        license=DEFAULT_MODEL_LICENSE,
        max_tokens=512,
        pooling="mean",
        normalization="l2",
        input_fields=("text",),
        dimension=DEFAULT_DIMENSION,
        backend="sentence_transformers",
        provider="huggingface",
        device="cuda",
        device_fallback=DeviceFallbackPolicy.BLOCK,
        batch_size=64,
    )
    emb = generate_uscode_embeddings(
        chunks,
        config=embed_config,
        checkpoint_path=checkpoint_dir / "embeddings.checkpoint.json",
    )
    _log(
        f"embeddings={len(emb.embeddings)} missing={len(emb.missing)} "
        f"device_requested={emb.device_requested} device_selected={emb.device_selected} "
        f"fallback={emb.device_fallback_applied}"
    )

    _log("binding vectors / centroids")
    binding = bind_uscode_vectors(emb, corpus_root_cid=bm25.corpus_root_cid)
    vectors = _vector_family_rows(emb, binding)
    _log(f"vector rows={len(vectors)} layout_rows={binding.layout.total_rows}")

    _log("projecting legal graph (citations + structure)")
    graph = project_uscode_graph(admitted)
    graph_nodes, graph_edges = _graph_family_rows(graph)
    _log(
        f"graph nodes={len(graph_nodes)} edges={len(graph_edges)} "
        f"unresolved={graph.unresolved_count}"
    )

    family_rows = {
        "corpus": admitted,
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "vectors": vectors,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "recovery": recovery,
    }
    summary = {
        "admitted": len(admitted),
        "recovery": len(recovery),
        "bm25_documents": len(bm25_docs),
        "bm25_postings": len(bm25_postings),
        "bm25_terms": bm25.term_count,
        "vectors": len(vectors),
        "graph_nodes": len(graph_nodes),
        "graph_edges": len(graph_edges),
        "corpus_root_cid": bm25.corpus_root_cid,
        "vector_root_cid": binding.vector_root_cid,
        "vector_space_id": binding.vector_space_id,
        "graph_cid": graph.graph_cid,
        "baseline_revision": BASELINE_REVISION,
        "release_point": RELEASE_POINT,
        "expected_admitted": BASELINE_CANONICAL_CID_COUNT,
        "expected_total_rows": BASELINE_CORPUS_ROW_COUNT,
    }
    (checkpoint_dir / "family_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    _log(f"family summary written: {summary}")
    return family_rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--laws-parquet",
        type=Path,
        default=DEFAULT_LAWS,
        help="Path to baseline laws.parquet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/uscode-full-hf-release-v2"),
        help="Directory to stage the HF release tree",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Checkpoint/receipt directory (default: <output-dir>/.checkpoints)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional row limit for smoke builds",
    )
    parser.add_argument(
        "--dataset-id",
        default=DEFAULT_DATASET_REPO_ID,
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    laws_path = args.laws_parquet.expanduser().resolve()
    if not laws_path.is_file():
        print(f"error: laws.parquet not found: {laws_path}", file=sys.stderr)
        print(
            "hint: huggingface-cli download justicedao/ipfs_uscode "
            f"uscode_parquet/laws.parquet --revision {BASELINE_REVISION}",
            file=sys.stderr,
        )
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    checkpoint_dir = (
        args.checkpoint_dir.expanduser().resolve()
        if args.checkpoint_dir
        else output_dir / ".checkpoints"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    family_rows = build_family_rows(
        laws_path=laws_path,
        limit=args.limit,
        checkpoint_dir=checkpoint_dir,
    )

    admission_summary = json.loads(
        (checkpoint_dir / "admission_summary.json").read_text()
    )
    _log("packaging HF release (in-memory then stage)")
    release = build_uscode_hf_release(
        family_rows,
        dataset_id=args.dataset_id,
        dry_run=False,
        output_dir=output_dir,
        source_revision=BASELINE_REVISION,
        release_point=RELEASE_POINT,
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_MODEL_REVISION,
        admission_summary=admission_summary,
        include_legacy_config=True,
        include_recovery_config=True,
        # Do not re-upload a stub uscode_parquet; keep Hub legacy as-is.
        legacy_files=None,
    )
    staged = stage_uscode_hf_release(release, output_dir, dry_run=False)
    validation = validate_uscode_hf_release(staged)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    result = {
        "ok": bool(validation.get("valid")),
        "output_dir": str(output_dir),
        "artifact_count": validation.get("artifact_count"),
        "manifest_digest": validation.get("manifest_digest")
        or manifest.get("manifest_digest"),
        "release_root_cid": validation.get("release_root_cid")
        or staged.release_root_cid,
        "admitted": len(family_rows.get("corpus") or []),
        "recovery": len(family_rows.get("recovery") or []),
        "bm25_postings": len(family_rows.get("bm25_postings") or []),
        "vectors": len(family_rows.get("vectors") or []),
        "graph_nodes": len(family_rows.get("graph_nodes") or []),
        "graph_edges": len(family_rows.get("graph_edges") or []),
        "source_revision": BASELINE_REVISION,
        "release_point": RELEASE_POINT,
        "dataset_id": args.dataset_id,
        "validation": validation,
    }
    (checkpoint_dir / "build_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
