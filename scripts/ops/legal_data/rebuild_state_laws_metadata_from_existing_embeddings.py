#!/usr/bin/env python3
"""Rebuild state_laws retrieval metadata from canonical + existing embeddings.

This script regenerates:
  - cid_index parquet
  - bm25 parquet
  - knowledge graph entity/relationship parquet + summary json
  - faiss index + faiss metadata parquet

It avoids expensive embedding recomputation by reusing STATE-XX_embeddings.parquet.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_STATE_CODES: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD",
    "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH",
    "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
    "DC",
]


@dataclass
class StateRebuildResult:
    state: str
    success: bool
    row_count: int = 0
    vector_count: int = 0
    vector_source: str = ""
    vector_coverage: float = 0.0
    uploaded: List[str] = None  # type: ignore[assignment]
    error: Optional[str] = None
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.uploaded is None:
            self.uploaded = []


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate state_laws KG/BM25/CID/FAISS artifacts from existing embeddings and upload to HF."
    )
    parser.add_argument("--repo-id", default="justicedao/ipfs_state_laws")
    parser.add_argument("--state", action="append", dest="states", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=4.0)
    parser.add_argument("--min-embedding-coverage", type=float, default=0.9)
    parser.add_argument("--fallback-dimension", type=int, default=384)
    parser.add_argument("--force-recompute-vectors", action="store_true")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--artifact-output-root", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--hf-token", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _state_paths(state: str) -> Dict[str, str]:
    base = f"state_laws_parquet_cid/STATE-{state}"
    return {
        "canonical": f"{base}.parquet",
        "embeddings": f"{base}_embeddings.parquet",
        "cid_index": f"{base}_cid_index.parquet",
        "bm25": f"{base}_bm25.parquet",
        "kg_entities": f"{base}_knowledge_graph_entities.parquet",
        "kg_relationships": f"{base}_knowledge_graph_relationships.parquet",
        "kg_summary": f"{base}_knowledge_graph_summary.json",
        "faiss": f"{base}.faiss",
        "faiss_metadata": f"{base}_faiss_metadata.parquet",
    }


def _download_required_files(repo_id: str, state: str) -> Dict[str, str]:
    from huggingface_hub import hf_hub_download

    paths = _state_paths(state)
    return {
        "canonical": hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=paths["canonical"]),
        "embeddings": hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=paths["embeddings"]),
    }


def _build_faiss_from_embeddings(
    *,
    state: str,
    canonical_rows: Sequence[Dict[str, Any]],
    embeddings_path: str,
    faiss_index_out: str,
    faiss_metadata_out: str,
    min_embedding_coverage: float,
    fallback_dimension: int,
    force_recompute_vectors: bool,
) -> tuple[int, int, str, float]:
    import faiss  # type: ignore
    import numpy as np  # type: ignore
    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
        _build_semantic_text_for_row,
        _coerce_embedding_vector,
        _fit_vector_dimension,
    )
    from ipfs_datasets_py.processors.retrieval import hashed_term_projection

    join_field = "ipfs_cid"
    canonical_by_join = {
        str(row.get(join_field) or ""): dict(row)
        for row in canonical_rows
        if str(row.get(join_field) or "")
    }

    embedding_rows = pq.read_table(embeddings_path).to_pylist()
    valid_vectors: List[List[float]] = []
    faiss_rows: List[Dict[str, Any]] = []
    dimension = 0

    for row in embedding_rows:
        join_value = str(row.get(join_field) or "").strip()
        if not join_value:
            continue
        canonical_row = canonical_by_join.get(join_value)
        if canonical_row is None:
            continue

        vector = _coerce_embedding_vector(row.get("embedding"))
        if not vector:
            continue
        if dimension <= 0:
            dimension = len(vector)
        vector = _fit_vector_dimension(vector, dimension)
        if not vector:
            continue

        vector_id = len(valid_vectors)
        valid_vectors.append([float(item) for item in vector])

        meta: Dict[str, Any] = {
            "vector_id": vector_id,
            join_field: join_value,
            "semantic_text": row.get("semantic_text") or "",
            "state_code": canonical_row.get("state_code") or state,
        }
        for field in ("identifier", "name", "source_id", "agency", "legislation_type", "date_published"):
            if field in canonical_row:
                meta[field] = canonical_row.get(field)
        faiss_rows.append(meta)

    row_count = len(canonical_rows)
    vector_count = len(valid_vectors)
    coverage = 0.0 if row_count <= 0 else float(vector_count) / float(row_count)

    def _recompute_from_canonical(target_dimension: int) -> tuple[List[List[float]], List[Dict[str, Any]]]:
        recomputed_vectors: List[List[float]] = []
        recomputed_meta: List[Dict[str, Any]] = []
        for row in canonical_rows:
            join_value = str(row.get(join_field) or "").strip()
            if not join_value:
                continue
            semantic_text = _build_semantic_text_for_row(
                row,
                title_fields=["name", "identifier", "source_id", "official_cite"],
                text_fields=["text", "jsonld", "name", "identifier", "source_id"],
            )
            vector = hashed_term_projection(semantic_text, dimension=target_dimension)
            if not vector:
                continue
            vector_id = len(recomputed_vectors)
            recomputed_vectors.append([float(item) for item in vector])
            meta: Dict[str, Any] = {
                "vector_id": vector_id,
                join_field: join_value,
                "semantic_text": semantic_text,
                "state_code": row.get("state_code") or state,
            }
            for field in ("identifier", "name", "source_id", "agency", "legislation_type", "date_published"):
                if field in row:
                    meta[field] = row.get(field)
            recomputed_meta.append(meta)
        return recomputed_vectors, recomputed_meta

    if not valid_vectors:
        dimension = max(8, int(fallback_dimension or 384))
        valid_vectors, faiss_rows = _recompute_from_canonical(dimension)
        vector_source = "recomputed_local_hash"
    else:
        vector_source = "existing_embeddings"

    # Promote to full-state vectors when existing embeddings are sparse/incomplete.
    # This keeps FAISS metadata aligned with the canonical corpus even when legacy
    # embeddings parquet files are partial or stale.
    if force_recompute_vectors or coverage < float(min_embedding_coverage):
        target_dimension = dimension if dimension > 0 else max(8, int(fallback_dimension or 384))
        valid_vectors, faiss_rows = _recompute_from_canonical(target_dimension)
        vector_source = "recomputed_local_hash"

    if not valid_vectors:
        raise ValueError(f"No valid vectors produced for STATE-{state}")

    if hasattr(faiss, "IndexFlatIP"):
        index = faiss.IndexFlatIP(dimension)
    elif hasattr(faiss, "IndexFlatL2"):
        index = faiss.IndexFlatL2(dimension)
    elif hasattr(faiss, "index_factory"):
        metric = getattr(faiss, "METRIC_INNER_PRODUCT", 0)
        index = faiss.index_factory(dimension, "Flat", metric)
    else:
        raise RuntimeError("No usable FAISS index constructor found")

    matrix = np.asarray(valid_vectors, dtype="float32")
    if matrix.shape[1] != dimension:
        dimension = int(matrix.shape[1])
        if hasattr(faiss, "IndexFlatIP"):
            index = faiss.IndexFlatIP(dimension)
        elif hasattr(faiss, "IndexFlatL2"):
            index = faiss.IndexFlatL2(dimension)
        elif hasattr(faiss, "index_factory"):
            metric = getattr(faiss, "METRIC_INNER_PRODUCT", 0)
            index = faiss.index_factory(dimension, "Flat", metric)
        else:
            raise RuntimeError("No usable FAISS index constructor found")
    index.add(matrix)
    faiss.write_index(index, faiss_index_out)
    pq.write_table(pa.Table.from_pylist(faiss_rows), faiss_metadata_out)
    final_vector_count = len(valid_vectors)
    final_coverage = 0.0 if row_count <= 0 else float(final_vector_count) / float(row_count)
    return row_count, final_vector_count, vector_source, final_coverage


def _rebuild_state(
    *,
    repo_id: str,
    state: str,
    hf_token: Optional[str],
    min_embedding_coverage: float,
    fallback_dimension: int,
    force_recompute_vectors: bool,
    upload: bool,
    artifact_output_root: str,
) -> StateRebuildResult:
    from huggingface_hub import CommitOperationAdd, HfApi
    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
        _build_bm25_rows,
        _build_cid_index_rows,
        _build_generic_knowledge_graph_rows,
        _ensure_join_field_rows,
        _normalize_rows_for_parquet,
    )

    start = time.time()
    paths = _state_paths(state)
    downloaded = _download_required_files(repo_id, state)
    canonical_path = downloaded["canonical"]
    embeddings_path = downloaded["embeddings"]

    canonical_rows = [dict(row) for row in pq.read_table(canonical_path).to_pylist()]
    canonical_rows = [
        row for row in canonical_rows
        if str(row.get("state_code") or "").strip().upper() in {"", state}
    ]
    canonical_rows, _ = _ensure_join_field_rows(canonical_rows, join_field="ipfs_cid")
    if not canonical_rows:
        raise ValueError(f"No canonical rows for STATE-{state}")

    cid_rows = _build_cid_index_rows(
        canonical_rows,
        join_field="ipfs_cid",
        config={"title_fields": ["name", "identifier", "source_id", "official_cite"], "text_fields": ["text", "jsonld", "name", "identifier", "source_id"]},
    )
    bm25_rows = _build_bm25_rows(
        canonical_rows,
        join_field="ipfs_cid",
        title_fields=["name", "identifier", "source_id", "official_cite"],
        text_fields=["text", "jsonld", "name", "identifier", "source_id"],
    )
    kg_entities, kg_relationships, kg_summary = _build_generic_knowledge_graph_rows(
        canonical_rows,
        corpus_key="state_laws",
        join_field="ipfs_cid",
        title_fields=["name", "identifier", "source_id", "official_cite"],
        text_fields=["text", "jsonld", "name", "identifier", "source_id"],
    )

    with tempfile.TemporaryDirectory(prefix=f"state_laws_meta_{state}_") as tmpdir:
        out_dir = Path(tmpdir)
        cid_path = str((out_dir / Path(paths["cid_index"]).name).resolve())
        bm25_path = str((out_dir / Path(paths["bm25"]).name).resolve())
        kg_entities_path = str((out_dir / Path(paths["kg_entities"]).name).resolve())
        kg_relationships_path = str((out_dir / Path(paths["kg_relationships"]).name).resolve())
        kg_summary_path = str((out_dir / Path(paths["kg_summary"]).name).resolve())
        faiss_path = str((out_dir / Path(paths["faiss"]).name).resolve())
        faiss_meta_path = str((out_dir / Path(paths["faiss_metadata"]).name).resolve())

        pq.write_table(pa.Table.from_pylist(cid_rows), cid_path)
        pq.write_table(pa.Table.from_pylist(bm25_rows), bm25_path)
        pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(kg_entities)), kg_entities_path)
        pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(kg_relationships)), kg_relationships_path)
        Path(kg_summary_path).write_text(json.dumps(kg_summary, indent=2, sort_keys=True), encoding="utf-8")

        row_count, vector_count, vector_source, vector_coverage = _build_faiss_from_embeddings(
            state=state,
            canonical_rows=canonical_rows,
            embeddings_path=embeddings_path,
            faiss_index_out=faiss_path,
            faiss_metadata_out=faiss_meta_path,
            min_embedding_coverage=min_embedding_coverage,
            fallback_dimension=fallback_dimension,
            force_recompute_vectors=force_recompute_vectors,
        )

        upload_map = [
            (cid_path, paths["cid_index"]),
            (bm25_path, paths["bm25"]),
            (kg_entities_path, paths["kg_entities"]),
            (kg_relationships_path, paths["kg_relationships"]),
            (kg_summary_path, paths["kg_summary"]),
            (faiss_path, paths["faiss"]),
            (faiss_meta_path, paths["faiss_metadata"]),
        ]
        uploaded: List[str] = []
        if upload:
            api = HfApi(token=hf_token) if hf_token else HfApi()
            commit_message = f"Regenerate state_laws metadata artifacts for STATE-{state}"
            operations = [
                CommitOperationAdd(path_in_repo=repo_path, path_or_fileobj=local_path)
                for local_path, repo_path in upload_map
            ]
            api.create_commit(
                repo_id=repo_id,
                repo_type="dataset",
                operations=operations,
                commit_message=commit_message,
            )
            uploaded = [repo_path for _, repo_path in upload_map]
        else:
            target_root = Path(str(artifact_output_root or "").strip() or ".").expanduser().resolve()
            for local_path, repo_path in upload_map:
                target_path = (target_root / repo_path).resolve()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, target_path)
                uploaded.append(str(target_path))

    return StateRebuildResult(
        state=state,
        success=True,
        row_count=row_count,
        vector_count=vector_count,
        vector_source=vector_source,
        vector_coverage=vector_coverage,
        uploaded=uploaded,
        elapsed_seconds=time.time() - start,
    )


def _state_artifacts_exist(repo_files: set[str], state: str) -> bool:
    paths = _state_paths(state)
    required = [
        paths["cid_index"],
        paths["bm25"],
        paths["kg_entities"],
        paths["kg_relationships"],
        paths["kg_summary"],
        paths["faiss"],
        paths["faiss_metadata"],
    ]
    return all(path in repo_files for path in required)


def main() -> int:
    from huggingface_hub import list_repo_files

    args = _parse_args()
    states = [str(item).strip().upper() for item in (args.states or []) if str(item).strip()]
    if not states:
        states = list(DEFAULT_STATE_CODES)

    repo_files = set(list_repo_files(repo_id=args.repo_id, repo_type="dataset"))
    pending_states = []
    for state in states:
        if args.skip_existing and _state_artifacts_exist(repo_files, state):
            continue
        pending_states.append(state)

    results: List[StateRebuildResult] = []
    for state in pending_states:
        attempt = 0
        while True:
            attempt += 1
            try:
                result = _rebuild_state(
                    repo_id=args.repo_id,
                    state=state,
                    hf_token=args.hf_token,
                    min_embedding_coverage=float(args.min_embedding_coverage),
                    fallback_dimension=int(args.fallback_dimension),
                    force_recompute_vectors=bool(args.force_recompute_vectors),
                    upload=not bool(args.no_upload),
                    artifact_output_root=str(args.artifact_output_root or ""),
                )
                results.append(result)
                print(
                    f"[ok] STATE-{state} rows={result.row_count} vectors={result.vector_count} "
                    f"coverage={result.vector_coverage:.3f} source={result.vector_source} "
                    f"elapsed={result.elapsed_seconds:.1f}s"
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt >= max(1, int(args.retries or 1)):
                    failed = StateRebuildResult(
                        state=state,
                        success=False,
                        error=str(exc),
                    )
                    results.append(failed)
                    print(f"[fail] STATE-{state} attempts={attempt} error={exc}")
                    break
                delay = max(0.1, float(args.retry_delay_seconds or 1.0))
                print(f"[retry] STATE-{state} attempt={attempt} error={exc}; sleeping {delay:.1f}s")
                time.sleep(delay)

    payload = {
        "repo_id": args.repo_id,
        "requested_states": states,
        "processed_states": pending_states,
        "success_count": len([r for r in results if r.success]),
        "failure_count": len([r for r in results if not r.success]),
        "results": [asdict(item) for item in results],
    }

    if args.output_json:
        output_path = Path(args.output_json).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))

    return 0 if payload["failure_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
