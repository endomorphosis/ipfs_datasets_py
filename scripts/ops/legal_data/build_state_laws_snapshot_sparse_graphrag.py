#!/usr/bin/env python3
"""Snapshot sparse GraphRAG orchestrator using the existing OUL indexers.

Reads assembled snapshot rows (never build_mixed_sample_rows). Calls corpus
materialize, term-range BM25, pinned gte-small, centroid vectors, legal graph,
lexical adjacency, and the HF packager. Authorizing flags stay false even when
real GTE inference succeeds.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[3]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (  # noqa: E402
    assert_every_admitted_chunk_has_document,
    build_corpus_root_cid,
    build_open_us_law_bm25_index,
    default_bm25_config,
    load_complete_sorted_postings_parquet,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import (  # noqa: E402
    assert_admitted_rows_complete,
    assert_chunks_have_deterministic_ids,
    assert_every_row_has_exactly_one_disposition,
    materialize_open_us_law_corpus,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embedding_parquet import (  # noqa: E402
    ParquetEmbeddingCheckpoint,
    load_parquet_checkpoint_records,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (  # noqa: E402
    DeviceEvidence,
    DeviceFallbackPolicy,
    EmbeddingGenerationResult,
    OpenUsLawEmbeddingConfig,
    OpenUsLawEmbeddingGenerator,
    PINNED_MAX_TOKENS,
    PRODUCTION_BACKEND,
    TruncationEvidence,
    empty_cuda_working_set,
    fixture_embedding_config,
    is_production_backend,
    require_pinned_gte_small,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_projection_runtime import (  # noqa: E402
    group_rows_by_jurisdiction,
    merge_graph_projections,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_graph import (  # noqa: E402
    OpenUsLawGraphProjection,
    graph_projection_from_dict,
    project_open_us_law_graph,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_hf_release import (  # noqa: E402
    assemble_open_us_law_hf_release,
    fixture_family_rows,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_lexical_graph import (  # noqa: E402
    build_open_us_law_lexical_graph,
    build_two_way_adjacency,
    default_adjacency_config,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    validate_exact_51_gate,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (  # noqa: E402
    bind_open_us_law_vectors,
)
from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_graphrag import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
    DEFAULT_RELEASE_ROOT,
    MODE,
    SnapshotGraphragError,
    apply_skillcenter_snapshot_release,
    assembled_jurisdiction_codes,
    load_assembled_rows,
    nonauthorizing_receipt,
    refuse_authorizing_for_publication,
    refuse_live_dest,
    utc_now,
)

# Pin CUDA torch and sentence-transformers before OUL-039 prepends the
# sealed CPU-only site-packages (which would otherwise shadow both).
import torch  # noqa: E402,F401
import sentence_transformers  # noqa: E402,F401

from scripts.ops.legal_data.build_open_us_law_sparse_graphrag import (  # noqa: E402
    _bm25_rows_from_sections,
    _embedding_chunks_from_canonical,
    _graph_rows_from_sections,
    prove_key_parity,
    prove_shard_bounds,
)


def build_snapshot_embedding_config(*, prefer_real: bool) -> OpenUsLawEmbeddingConfig:
    """Pinned GTE config. Production inference uses CUDA when available."""

    if prefer_real:
        return OpenUsLawEmbeddingConfig(
            backend=PRODUCTION_BACKEND,
            provider="huggingface",
            device="cuda",
            device_fallback=DeviceFallbackPolicy.BLOCK,
            batch_size=64,
        )
    return fixture_embedding_config(device="cpu")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--states", default="", help="Comma-separated codes (default: all assembled).")
    parser.add_argument(
        "--limit-per-state",
        type=int,
        default=0,
        help="Optional per-state row cap for canaries (0 = no cap).",
    )
    parser.add_argument(
        "--prefer-real-embeddings",
        action="store_true",
        help="Use cached thenlper/gte-small. Missing weights fail closed.",
    )
    parser.add_argument(
        "--authorizing-for-publication",
        action="store_true",
        help="Rejected. Snapshot GraphRAG cannot authorize Hub publication.",
    )
    parser.add_argument("--print-json", action="store_true")
    return parser


SNAPSHOT_STAGE_SCHEMA = "ipfs_datasets_py.state_laws.snapshot_graphrag.stage.v1"


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _sha256_lines(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _corpus_identity_payload(
    *,
    chunk_cids: Sequence[str],
    section_count: int,
    codes: Sequence[str],
    notes: str,
) -> dict[str, Any]:
    ordered = tuple(chunk_cids)
    return {
        "chunk_cid_sha256": _sha256_lines(ordered),
        "chunk_count": len(ordered),
        "jurisdiction_codes": list(codes),
        "notes": notes,
        "schema": SNAPSHOT_STAGE_SCHEMA,
        "section_count": int(section_count),
        "stage": "corpus",
        "status": "complete",
    }


def _write_corpus_identity(output_dir: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_json(output_dir / "checkpoints" / "corpus" / "identity.json", payload)


def _load_corpus_identity(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "checkpoints" / "corpus" / "identity.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "complete":
        return None
    return payload


def _write_graph_checkpoint(output_dir: Path, graph: Any) -> None:
    dest = output_dir / "checkpoints" / "graph"
    dest.mkdir(parents=True, exist_ok=True)
    payload = graph.to_dict()
    _atomic_write_json(dest / "projection.json", payload)
    _atomic_write_json(
        dest / "identity.json",
        {
            "edge_count": len(getattr(graph, "edges", ()) or ()),
            "graph_cid": str(getattr(graph, "graph_cid", "") or ""),
            "node_count": len(getattr(graph, "nodes", ()) or ()),
            "partition": "jurisdiction",
            "schema": SNAPSHOT_STAGE_SCHEMA,
            "stage": "graph",
            "status": "complete",
        },
    )


def _jurisdiction_graph_dir(output_dir: Path, code: str) -> Path:
    return output_dir / "checkpoints" / "graph" / "by_jurisdiction" / str(code)


def _write_jurisdiction_graph_checkpoint(output_dir: Path, code: str, graph: Any) -> None:
    dest = _jurisdiction_graph_dir(output_dir, code)
    dest.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(dest / "projection.json", graph.to_dict())
    _atomic_write_json(
        dest / "identity.json",
        {
            "edge_count": len(getattr(graph, "edges", ()) or ()),
            "graph_cid": str(getattr(graph, "graph_cid", "") or ""),
            "jurisdiction_code": str(code),
            "node_count": len(getattr(graph, "nodes", ()) or ()),
            "partition": "jurisdiction",
            "schema": SNAPSHOT_STAGE_SCHEMA,
            "stage": "graph",
            "status": "complete",
        },
    )


def _load_jurisdiction_graph_checkpoint(output_dir: Path, code: str) -> Any | None:
    dest = _jurisdiction_graph_dir(output_dir, code)
    identity_path = dest / "identity.json"
    projection_path = dest / "projection.json"
    if not identity_path.is_file() or not projection_path.is_file():
        return None
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        payload = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, MemoryError):
        return None
    if not isinstance(identity, dict) or identity.get("status") != "complete":
        return None
    if str(identity.get("jurisdiction_code") or "") != str(code):
        return None
    if not isinstance(payload, dict):
        return None
    graph = graph_projection_from_dict(payload)
    if str(graph.graph_cid) != str(identity.get("graph_cid") or ""):
        return None
    return graph


def _load_graph_checkpoint(output_dir: Path) -> Any | None:
    dest = output_dir / "checkpoints" / "graph"
    identity_path = dest / "identity.json"
    if not identity_path.is_file():
        return None
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, MemoryError):
        return None
    if not isinstance(identity, dict) or identity.get("status") != "complete":
        return None
    if identity.get("partition") == "jurisdiction":
        codes = identity.get("jurisdictions") or []
        if not isinstance(codes, list) or not codes:
            return None
        parts = []
        for code in codes:
            part = _load_jurisdiction_graph_checkpoint(output_dir, str(code))
            if part is None:
                return None
            parts.append(part)
        merged = merge_graph_projections(
            parts, factory=OpenUsLawGraphProjection, skipped_row_count=0
        )
        if str(merged.graph_cid) != str(identity.get("graph_cid") or ""):
            return None
        return merged
    projection_path = dest / "projection.json"
    if not projection_path.is_file():
        return None
    try:
        payload = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, MemoryError):
        return None
    if not isinstance(payload, dict):
        return None
    graph = graph_projection_from_dict(payload)
    if str(graph.graph_cid) != str(identity.get("graph_cid") or ""):
        return None
    return graph


def _project_graphs_by_jurisdiction(
    output_dir: Path,
    rows: Sequence[Any],
    *,
    corpus_digest: str,
) -> Any:
    """Project one durable graph per state, then concatenate for the packager."""

    groups = group_rows_by_jurisdiction(rows)
    parts: list[Any] = []
    codes: list[str] = []
    for code, part_rows in groups.items():
        loaded = _load_jurisdiction_graph_checkpoint(output_dir, code)
        if loaded is not None:
            print(
                f"snapshot stage=graph resume jurisdiction={code} "
                f"cid={loaded.graph_cid} documents={len(part_rows)}",
                file=sys.stderr,
                flush=True,
            )
            parts.append(loaded)
            codes.append(code)
            continue
        print(
            f"snapshot stage=graph jurisdiction={code} documents={len(part_rows)}",
            file=sys.stderr,
            flush=True,
        )
        dest = _jurisdiction_graph_dir(output_dir, code)
        graph = project_open_us_law_graph(
            part_rows,
            checkpoint_dir=dest / "work",
            corpus_digest=f"{corpus_digest}:{code}",
        )
        _write_jurisdiction_graph_checkpoint(output_dir, code, graph)
        work_dir = dest / "work"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        parts.append(graph)
        codes.append(code)
    merged = merge_graph_projections(
        parts, factory=OpenUsLawGraphProjection, skipped_row_count=0
    )
    dest = output_dir / "checkpoints" / "graph"
    dest.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(
        dest / "identity.json",
        {
            "edge_count": len(getattr(merged, "edges", ()) or ()),
            "graph_cid": str(getattr(merged, "graph_cid", "") or ""),
            "jurisdiction_count": len(codes),
            "jurisdictions": codes,
            "node_count": len(getattr(merged, "nodes", ()) or ()),
            "partition": "jurisdiction",
            "schema": SNAPSHOT_STAGE_SCHEMA,
            "stage": "graph",
            "status": "complete",
        },
    )
    return merged


def _retain_complete_bm25_work(bm25_work: Path) -> bool:
    """Keep finished posting parquet; only drop incomplete sort leftovers."""

    reused = load_complete_sorted_postings_parquet(bm25_work / "postings")
    if reused is None:
        return False
    leftover = bm25_work / "postings" / "postings-sort"
    if leftover.exists():
        shutil.rmtree(leftover, ignore_errors=True)
    return True


def _codes(raw: str) -> Optional[list[str]]:
    text = (raw or "").strip()
    if not text:
        return None
    return [item.strip().upper() for item in text.split(",") if item.strip()]


def _embed_assembled_by_jurisdiction(
    *,
    corpus_root: Path,
    codes: Sequence[str],
    limit_per_state: int,
    notes: str,
    config: OpenUsLawEmbeddingConfig,
    checkpoint_path: Path,
) -> dict[str, Any]:
    """Embed one jurisdiction at a time into a shared parquet checkpoint.

    Peak RAM is one state's chunks plus the cached gte-small model. Resume
    uses a CID/hash skip index and does not reload prior vectors. The
    returned mapping is device/model metadata only.
    """

    generator = OpenUsLawEmbeddingGenerator(config)
    metadata: dict[str, Any] | None = None
    try:
        for index, code in enumerate(codes, start=1):
            rows = load_assembled_rows(
                corpus_root,
                codes=[code],
                limit_per_state=limit_per_state,
            )
            if not rows:
                print(
                    f"snapshot embed skip {code} ({index}/{len(codes)}): no rows",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            part = materialize_open_us_law_corpus(rows, notes=notes)
            assert_every_row_has_exactly_one_disposition(part.ledger)
            assert_admitted_rows_complete(part.admitted_sections)
            assert_chunks_have_deterministic_ids(part.admitted_chunks)
            chunks = _embedding_chunks_from_canonical(part.admitted_chunks)
            print(
                f"snapshot embed {code} ({index}/{len(codes)}) "
                f"sections={len(part.admitted_sections)} "
                f"chunks={len(chunks)}",
                file=sys.stderr,
                flush=True,
            )
            result = generator.generate(
                chunks,
                checkpoint_path=checkpoint_path,
                resume=True,
            )
            metadata = {
                "batch_count": result.batch_count,
                "device": result.device,
                "embedder_kind": result.embedder_kind,
                "model_file_evidence": dict(result.model_file_evidence),
                "real_inference": result.real_inference,
                "truncation": result.truncation,
            }
            del part, rows, chunks, result
            gc.collect()
    finally:
        generator.release()

    if metadata is None:
        raise SnapshotGraphragError(f"no assembled snapshot rows under {corpus_root}")
    return metadata


def _metadata_from_parquet_checkpoint(
    config: OpenUsLawEmbeddingConfig,
    checkpoint_path: Path,
) -> dict[str, Any] | None:
    """Reuse a complete parquet embedding checkpoint without rematerializing."""

    store = ParquetEmbeddingCheckpoint.load(
        checkpoint_path, config_digest=config.digest
    )
    if store.row_count < 1 or not store.parts:
        return None
    production = is_production_backend(config.backend)
    return {
        "batch_count": store.batch_count,
        "device": DeviceEvidence(
            requested=config.device,
            selected=config.device,
            fallback_applied=False,
            precision=config.precision,
            runtime={"resumed_from_parquet": True, "row_count": store.row_count},
        ),
        "embedder_kind": config.backend,
        "model_file_evidence": {
            "resumed_from_parquet": True,
            "row_count": store.row_count,
        },
        "parquet_row_count": store.row_count,
        "real_inference": production,
        "truncation": TruncationEvidence(
            applied=production,
            max_seq_length=PINNED_MAX_TOKENS if production else None,
            tokenizer_model_max_length=PINNED_MAX_TOKENS if production else None,
            max_tokens=config.max_tokens,
        ),
    }


def run_snapshot_build(
    *,
    corpus_root: Path,
    output_dir: Path,
    codes: Optional[Sequence[str]] = None,
    limit_per_state: int = 0,
    prefer_real_embeddings: bool = False,
) -> dict[str, Any]:
    refuse_live_dest(output_dir)
    selected = assembled_jurisdiction_codes(corpus_root, codes=codes)
    if not selected:
        raise SnapshotGraphragError(f"no assembled snapshot rows under {corpus_root}")

    notes = (
        "snapshot_research corpus; not a current-bundle; "
        "does not satisfy exact-51 publication gate"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    embedding_ckpt = output_dir / "checkpoints" / "embeddings"
    embedding_config = build_snapshot_embedding_config(
        prefer_real=prefer_real_embeddings
    )
    resumed = _metadata_from_parquet_checkpoint(embedding_config, embedding_ckpt)
    if resumed is not None:
        print(
            "snapshot stage=embed resume "
            f"parquet_rows={resumed['parquet_row_count']}",
            file=sys.stderr,
            flush=True,
        )
        embed_meta = resumed
    else:
        print("snapshot stage=embed", file=sys.stderr, flush=True)
        embed_meta = _embed_assembled_by_jurisdiction(
            corpus_root=corpus_root,
            codes=selected,
            limit_per_state=limit_per_state,
            notes=notes,
            config=embedding_config,
            checkpoint_path=embedding_ckpt,
        )
    empty_cuda_working_set()

    print("snapshot stage=materialize", file=sys.stderr, flush=True)
    rows = load_assembled_rows(
        corpus_root,
        codes=selected,
        limit_per_state=limit_per_state,
    )
    corpus = materialize_open_us_law_corpus(rows, notes=notes)
    assert_every_row_has_exactly_one_disposition(corpus.ledger)
    assert_admitted_rows_complete(corpus.admitted_sections)
    assert_chunks_have_deterministic_ids(corpus.admitted_chunks)
    del rows
    gc.collect()

    gate = validate_exact_51_gate(
        [section.to_dict() for section in corpus.admitted_sections],
        require_full_coverage=False,
    )
    # Snapshot indexing may cover many codes as text. That is never
    # publication authority; the receipt keeps satisfies_exact_51_gate false.

    chunk_cids = tuple(chunk.chunk_cid for chunk in corpus.admitted_chunks)
    identity = _corpus_identity_payload(
        chunk_cids=chunk_cids,
        section_count=len(corpus.admitted_sections),
        codes=selected,
        notes=notes,
    )
    prior_identity = _load_corpus_identity(output_dir)
    known_prior = prior_identity is not None
    corpus_changed = (
        not known_prior
        or prior_identity.get("chunk_cid_sha256") != identity["chunk_cid_sha256"]
        or int(prior_identity.get("section_count") or 0) != identity["section_count"]
    )
    if known_prior and corpus_changed:
        graph_ckpt = output_dir / "checkpoints" / "graph"
        if graph_ckpt.exists():
            shutil.rmtree(graph_ckpt, ignore_errors=True)
        bm25_work = output_dir / "bm25-work"
        if bm25_work.exists():
            shutil.rmtree(bm25_work, ignore_errors=True)
    _write_corpus_identity(output_dir, identity)
    skip = ParquetEmbeddingCheckpoint.load(
        embedding_ckpt, config_digest=embedding_config.digest
    ).load_skip_index()
    extra = sorted(set(skip) - set(chunk_cids))
    absent = sorted(set(chunk_cids) - set(skip))
    if extra:
        raise SnapshotGraphragError(
            "parquet embeddings contain extra chunk_cids; "
            f"extra={extra[:5]!r}"
        )
    if absent:
        print(
            f"snapshot stage=embed fill_missing={len(absent)}",
            file=sys.stderr,
            flush=True,
        )
        embed_meta = _embed_assembled_by_jurisdiction(
            corpus_root=corpus_root,
            codes=selected,
            limit_per_state=limit_per_state,
            notes=notes,
            config=embedding_config,
            checkpoint_path=embedding_ckpt,
        )
        skip = ParquetEmbeddingCheckpoint.load(
            embedding_ckpt, config_digest=embedding_config.digest
        ).load_skip_index()
        extra = sorted(set(skip) - set(chunk_cids))
        absent = sorted(set(chunk_cids) - set(skip))
        if extra or absent:
            raise SnapshotGraphragError(
                "parquet embeddings do not match admitted chunks; "
                f"extra={extra[:5]!r} absent={absent[:5]!r}"
            )
    del skip
    gc.collect()
    require_pinned_gte_small(
        model_id=embedding_config.model_id,
        model_revision=embedding_config.model_revision,
    )

    print(
        f"snapshot stage=bm25 sections={len(corpus.admitted_sections)} "
        f"chunks={len(chunk_cids)}",
        file=sys.stderr,
        flush=True,
    )
    bm25_work = output_dir / "bm25-work"
    reused_postings = _retain_complete_bm25_work(bm25_work)
    if reused_postings:
        print(
            "snapshot stage=bm25 resume parquet_postings",
            file=sys.stderr,
            flush=True,
        )
    bm25_rows = _bm25_rows_from_sections(corpus.admitted_sections)
    corpus_root_cid = build_corpus_root_cid(bm25_rows)
    bm25 = build_open_us_law_bm25_index(
        bm25_rows,
        config=default_bm25_config(),
        corpus_root_cid=corpus_root_cid,
        work_dir=bm25_work,
    )
    assert_every_admitted_chunk_has_document(bm25_rows, bm25)
    del bm25_rows
    gc.collect()

    graph = (
        _load_graph_checkpoint(output_dir)
        if known_prior and not corpus_changed
        else None
    )
    if graph is not None:
        print(
            f"snapshot stage=graph resume cid={graph.graph_cid}",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            "snapshot stage=graph partition=jurisdiction",
            file=sys.stderr,
            flush=True,
        )
        combined_work = output_dir / "checkpoints" / "graph" / "work"
        if combined_work.exists():
            shutil.rmtree(combined_work, ignore_errors=True)
        graph = _project_graphs_by_jurisdiction(
            output_dir,
            _graph_rows_from_sections(corpus.admitted_sections),
            corpus_digest=str(identity.get("chunk_cid_sha256") or ""),
        )
    graph.assert_semantics_disjoint()
    overlay = build_open_us_law_lexical_graph(
        bm25,
        same_jurisdiction_only=True,
        checkpoint_dir=output_dir / "checkpoints" / "neighbors",
    )
    adjacency = build_two_way_adjacency(
        graph,
        overlay=overlay,
        config=default_adjacency_config(),
    )
    gc.collect()

    print(
        "snapshot stage=vectors partition=jurisdiction kmeans_device=cuda",
        file=sys.stderr,
        flush=True,
    )
    records = load_parquet_checkpoint_records(
        embedding_ckpt, config=embedding_config
    )
    embeddings = EmbeddingGenerationResult(
        embeddings=records,
        config=embedding_config,
        admitted_chunk_cids=chunk_cids,
        device=embed_meta["device"],
        truncation=embed_meta["truncation"],
        missing=(),
        batch_count=int(embed_meta["batch_count"]),
        resumed_chunk_cids=(),
        executed_chunk_cids=chunk_cids,
        embedder_kind=str(embed_meta["embedder_kind"]),
        real_inference=bool(embed_meta["real_inference"]),
        model_file_evidence=dict(embed_meta["model_file_evidence"]),
        checkpoint_path=str(embedding_ckpt),
    )
    del records
    gc.collect()
    chunk_jurisdiction = {
        chunk.chunk_cid: chunk.jurisdiction_code
        for chunk in corpus.admitted_chunks
    }
    vectors = bind_open_us_law_vectors(
        embeddings,
        corpus_root_cid=corpus_root_cid,
        config=embeddings.config,
        chunk_jurisdiction=chunk_jurisdiction,
        checkpoint_dir=output_dir / "checkpoints" / "vectors",
        progress_log=lambda message: print(message, file=sys.stderr, flush=True),
        kmeans_device="cuda",
    )
    gc.collect()
    parity = prove_key_parity(
        sections=corpus.admitted_sections,
        chunks=corpus.admitted_chunks,
        bm25=bm25,
        embeddings=embeddings,
        vectors=vectors,
        graph=graph,
    )
    bounds = prove_shard_bounds(bm25=bm25, vectors=vectors, adjacency=adjacency)

    print("snapshot stage=packager", file=sys.stderr, flush=True)
    hf_release_dir = output_dir / "hf-release"
    hf_manifest = ""
    isolation_families = {
        key: value
        for key, value in fixture_family_rows().items()
        if key
        in {
            "recovery",
            "quarantine",
            "federal_uscode",
            "puerto_rico",
            "constitutions",
            "historical",
            "source_receipts",
        }
    }
    try:
        release = assemble_open_us_law_hf_release(
            family_rows=isolation_families,
            corpus_rows=[section.to_dict() for section in corpus.admitted_sections],
            bm25_index=bm25,
            vector_binding=vectors,
            graph_projection=graph,
            adjacency=adjacency,
            dry_run=False,
            output_dir=hf_release_dir,
        )
        hf_manifest = str(getattr(release, "manifest_path", "") or "")
        if not hf_manifest:
            candidate = hf_release_dir / "manifest.json"
            if candidate.is_file():
                hf_manifest = str(candidate)
        skillcenter_layout = apply_skillcenter_snapshot_release(
            hf_release_dir,
            query_script=HERE.parent / "query_open_us_law_hf.py",
        )
    except Exception as exc:
        hf_manifest = f"packager_skipped:{type(exc).__name__}:{exc}"
        skillcenter_layout = {"error": str(exc)}

    # assert_shards_bounded already proves lexicographic term-range order.
    term_sorted = True
    layout = getattr(vectors, "layout", None)
    clusters = list(getattr(layout, "clusters", []) or []) if layout is not None else []
    centroid_ids = list(getattr(vectors, "centroid_ids", []) or []) or [
        getattr(cluster, "cluster_id", index) for index, cluster in enumerate(clusters)
    ]
    receipt = nonauthorizing_receipt(
        built_at=utc_now(),
        mode=MODE,
        prefer_real_embeddings=prefer_real_embeddings,
        real_inference=bool(getattr(embeddings, "real_inference", False)),
        embedder_kind=str(getattr(embeddings, "embedder_kind", "") or embeddings.config.backend),
        embedding_device=str(embeddings.config.device),
        embedding_device_selected=str(
            getattr(getattr(embeddings, "device", None), "selected", "")
            or embeddings.config.device
        ),
        embedding_checkpoint_format="parquet_parts",
        embedding_checkpoint_path=str(embedding_ckpt),
        admitted_section_count=len(corpus.admitted_sections),
        admitted_chunk_count=len(corpus.admitted_chunks),
        jurisdiction_codes=list(corpus.default_jurisdiction_codes()),
        corpus_root_cid=corpus_root_cid,
        bm25_index_root_cid=bm25.index_root_cid,
        vector_root_cid=vectors.vector_root_cid,
        graph_cid=graph.graph_cid,
        bm25_term_shards_lexicographically_sorted=term_sorted if getattr(bm25, "term_shards", None) else True,
        vector_centroid_count=len(centroid_ids) or len(getattr(vectors, "centroids", []) or []),
        key_parity=parity,
        shard_bounds=bounds,
        exact_51_gate_closed=bool(gate.get("closed")),
        exact_51_gate_used_as_publication_authority=False,
        hf_release_dir=str(hf_release_dir),
        hf_manifest=hf_manifest,
        skillcenter_layout=skillcenter_layout,
        output_dir=str(output_dir),
    )
    (output_dir / "snapshot_build_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    refuse_authorizing_for_publication(bool(args.authorizing_for_publication))
    try:
        receipt = run_snapshot_build(
            corpus_root=args.corpus_root.expanduser().resolve(),
            output_dir=args.output_dir.expanduser().resolve(),
            codes=_codes(args.states),
            limit_per_state=int(args.limit_per_state),
            prefer_real_embeddings=bool(args.prefer_real_embeddings),
        )
    except SnapshotGraphragError as exc:
        raise SystemExit(str(exc)) from exc
    if args.print_json:
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"snapshot GraphRAG {receipt.get('admitted_section_count')} sections "
            f"under {receipt.get('output_dir')} authorizing_for_publication=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
