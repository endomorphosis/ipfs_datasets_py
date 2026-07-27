"""Hugging Face release packaging for complete SkillCenter retrieval artifacts.

The release is intentionally thin-client friendly:

* every data shard is Zstandard-compressed Parquet;
* corpus, graph, document, posting, and vector shards contain at most 4,096
  rows;
* a compact lexical-range meta-index points query terms to BM25 posting
  shards;
* a compact centroid meta-index points dense queries to vector shards; and
* canonical ``entry_cid`` values remain the primary content identities.

SQLite FTS5 storage is converted to logical BM25 postings rather than copying
private FTS segment blobs.  The logical export preserves document identifiers,
per-column term frequencies, document lengths, and the constants needed to
reproduce FTS5's Okapi BM25 ranking.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from .skillcenter_cid_graph import SkillCenterCIDGraphIndex
from .skillcenter_cid_vectors import SkillCenterCIDVectorIndex
from .skillcenter_corpus import SkillCenterCorpusIndex
from .skillcenter_corpus_bm25 import SkillCenterCorpusBM25Index


SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2: Final = (
    "skillcenter-huggingface-release/v2"
)
SKILLCENTER_HF_RELEASE_SCHEMA_VERSION: Final = (
    "skillcenter-huggingface-release/v3"
)
SKILLCENTER_HF_BM25_POSTING_SCHEMA_VERSION: Final = (
    "skillcenter-hf-bm25-posting/v1"
)
SKILLCENTER_HF_VECTOR_CHUNK_SCHEMA_VERSION: Final = (
    "skillcenter-hf-vector-chunk/v2"
)
SKILLCENTER_HF_GRAPH_ADJACENCY_SCHEMA_VERSION: Final = (
    "skillcenter-hf-graph-adjacency/v1"
)
SKILLCENTER_HF_META_SCHEMA_VERSION: Final = (
    "skillcenter-hf-shard-meta/v1"
)
DEFAULT_RELEASE_REPO_ID: Final = "Publicus/skillcenter-ir"
RELEASE_CHUNK_ROWS: Final = 4096
BM25_TERMS_PER_SHARD: Final = 4096
BM25_POSTINGS_PER_ROW: Final = 4096
PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6
FTS5_K1: Final = 1.2
FTS5_B: Final = 0.75
VECTOR_TRAINING_ROWS: Final = 65_536
VECTOR_COARSE_CLUSTERS: Final = 64
VECTOR_MAX_SHARDS_PER_CENTROID: Final = 2
VECTOR_MAX_ROWS_PER_CENTROID: Final = (
    VECTOR_MAX_SHARDS_PER_CENTROID * RELEASE_CHUNK_ROWS
)
VECTOR_DEFAULT_PROBE_CENTROIDS: Final = 4
VECTOR_KMEANS_SEED: Final = 0x5C11C3
GRAPH_ADJACENCY_POINTERS_PER_ROW: Final = 4096
GRAPH_ADJACENCY_POINTERS_PER_SHARD: Final = 8192

ProgressCallback = Callable[[Mapping[str, Any]], None]


class SkillCenterHFReleaseError(ValueError):
    """Raised when a Hugging Face release cannot be built or validated."""


def _semantic_traversal_source(
    value: str | Path | None,
) -> Path:
    """Resolve the standalone semantic traversal module to bundle."""
    source = (
        Path(value).expanduser().resolve()
        if value is not None
        else (
            Path(__file__).resolve().parents[3]
            / "knowledge_graphs"
            / "query"
            / "semantic_traversal.py"
        )
    )
    if not source.is_file():
        raise SkillCenterHFReleaseError(
            f"semantic traversal module does not exist: {source}"
        )
    return source


def _copy_skill_tree(source: Path, target: Path) -> None:
    """Copy a skill deterministically without interpreter cache artifacts."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


@dataclass(frozen=True, slots=True)
class SkillCenterHFReleaseSummary:
    output_dir: str
    dataset_repo_id: str
    dataset_revision: str
    corpus_rows: int
    bm25_terms: int
    bm25_postings: int
    graph_nodes: int
    graph_edges: int
    vector_rows: int
    vector_chunks: int
    manifest_sha256: str
    graph_adjacency_rows: int = 0
    graph_adjacency_shards: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_postings": self.bm25_postings,
            "bm25_terms": self.bm25_terms,
            "corpus_rows": self.corpus_rows,
            "dataset_repo_id": self.dataset_repo_id,
            "dataset_revision": self.dataset_revision,
            "graph_edges": self.graph_edges,
            "graph_adjacency_rows": self.graph_adjacency_rows,
            "graph_adjacency_shards": self.graph_adjacency_shards,
            "graph_nodes": self.graph_nodes,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "vector_chunks": self.vector_chunks,
            "vector_rows": self.vector_rows,
        }


def _vector_manifest_config(
    *,
    dimension: int,
    model_name: str,
    centroid_count: int,
    shard_count: int,
) -> dict[str, Any]:
    """Describe the bounded semantic-centroid vector layout."""

    return {
        "assignment": "recursive_spherical_kmeans",
        "centroid_count": int(centroid_count),
        "default_probe_centroids": VECTOR_DEFAULT_PROBE_CENTROIDS,
        "dimension": int(dimension),
        "layout": "semantic_centroid_groups",
        "max_rows_per_centroid": VECTOR_MAX_ROWS_PER_CENTROID,
        "max_shards_per_centroid": VECTOR_MAX_SHARDS_PER_CENTROID,
        "max_rows_per_chunk": RELEASE_CHUNK_ROWS,
        "model_name": str(model_name),
        "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
        "shard_count": int(shard_count),
        "similarity": "cosine",
    }


def build_skillcenter_hf_release(
    corpus_dir: str | Path,
    bm25_dir: str | Path,
    graph_dir: str | Path,
    vector_dir: str | Path,
    *,
    output_dir: str | Path,
    dataset_repo_id: str = DEFAULT_RELEASE_REPO_ID,
    query_script: str | Path | None = None,
    skill_dir: str | Path | None = None,
    semantic_traversal_module: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SkillCenterHFReleaseSummary:
    """Convert the complete local indexes to a Hub-ready Parquet release."""

    repo_id = str(dataset_repo_id or "").strip()
    if "/" not in repo_id or repo_id.startswith("/") or repo_id.endswith("/"):
        raise SkillCenterHFReleaseError(
            "dataset_repo_id must have the form namespace/repository"
        )
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    complete_manifest = output / "manifest.json"
    if complete_manifest.is_file():
        try:
            existing_manifest = json.loads(complete_manifest.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterHFReleaseError(
                "existing release manifest is malformed"
            ) from exc
        if (
            existing_manifest.get("schema_version")
            != SKILLCENTER_HF_RELEASE_SCHEMA_VERSION
        ):
            raise SkillCenterHFReleaseError(
                "existing release uses an older vector layout; use "
                "--rebalance-from with a separate v2 output directory"
            )
        if query_script is not None and skill_dir is not None:
            return refresh_skillcenter_hf_release_support(
                output,
                query_script=query_script,
                skill_dir=skill_dir,
                semantic_traversal_module=semantic_traversal_module,
            )
        return validate_skillcenter_hf_release(output)

    _notify(progress_callback, {"phase": "load_inputs"})
    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    bm25 = SkillCenterCorpusBM25Index.load(bm25_dir)
    graph = SkillCenterCIDGraphIndex.load(graph_dir)
    vectors = SkillCenterCIDVectorIndex.load(vector_dir)
    _validate_input_bindings(
        corpus=corpus,
        bm25=bm25,
        graph=graph,
        vectors=vectors,
    )
    revisions = {
        corpus.summary.dataset_revision,
        bm25.summary.dataset_revision,
        graph.summary.dataset_revision,
        vectors.summary.dataset_revision,
    }
    if len(revisions) != 1:
        raise SkillCenterHFReleaseError(
            f"input dataset revisions differ: {sorted(revisions)}"
        )
    dataset_revision = next(iter(revisions))
    expected_rows = corpus.summary.source_records
    if {
        expected_rows,
        bm25.summary.indexed_entries,
        graph.summary.skill_nodes,
        vectors.summary.vector_count,
    } != {expected_rows}:
        raise SkillCenterHFReleaseError(
            "corpus, BM25, graph, and vector coverage differs"
        )

    corpus_meta = _export_corpus(
        corpus,
        output,
        progress_callback=progress_callback,
    )
    document_lengths = _fts5_document_lengths(
        bm25.database_path,
        expected_rows=expected_rows,
    )
    document_meta = _export_bm25_documents(
        bm25,
        document_lengths,
        output,
        progress_callback=progress_callback,
    )
    bm25_meta, bm25_stats = _export_bm25_postings(
        bm25,
        document_lengths,
        output,
        progress_callback=progress_callback,
    )
    graph_node_meta = _export_graph_table(
        graph.database_path,
        table_name="nodes",
        order_column="node_cid",
        output_root=output,
        progress_callback=progress_callback,
    )
    graph_edge_meta = _export_graph_table(
        graph.database_path,
        table_name="edges",
        order_column="edge_cid",
        output_root=output,
        progress_callback=progress_callback,
    )
    graph_outgoing_meta, graph_outgoing_stats = _export_graph_adjacency(
        graph.database_path,
        direction="outgoing",
        output_root=output,
        progress_callback=progress_callback,
    )
    graph_incoming_meta, graph_incoming_stats = _export_graph_adjacency(
        graph.database_path,
        direction="incoming",
        output_root=output,
        progress_callback=progress_callback,
    )
    vector_meta = _export_vectors(
        vectors,
        corpus,
        output,
        progress_callback=progress_callback,
    )

    index_dir = output / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_descriptors = {}
    for name, rows in (
        ("corpus_chunks", corpus_meta),
        ("bm25_document_chunks", document_meta),
        ("bm25_keyword_shards", bm25_meta),
        ("graph_node_chunks", graph_node_meta),
        ("graph_edge_chunks", graph_edge_meta),
        ("graph_outgoing_adjacency", graph_outgoing_meta),
        ("graph_incoming_adjacency", graph_incoming_meta),
        ("vector_chunks", vector_meta),
    ):
        path = index_dir / f"{name}.parquet"
        _write_meta_index(path, rows)
        index_descriptors[name] = _file_descriptor(path, root=output)

    copied_files: dict[str, Any] = {}
    if query_script is not None:
        source = Path(query_script).expanduser().resolve()
        if not source.is_file():
            raise SkillCenterHFReleaseError(
                f"query script does not exist: {source}"
            )
        target = output / "scripts" / "query_skillcenter_hf.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied_files["query_script"] = _file_descriptor(target, root=output)
        semantic_source = _semantic_traversal_source(
            semantic_traversal_module
        )
        semantic_target = output / "scripts" / "semantic_traversal.py"
        shutil.copy2(semantic_source, semantic_target)
        copied_files["semantic_traversal"] = _file_descriptor(
            semantic_target,
            root=output,
        )
    if skill_dir is not None:
        source = Path(skill_dir).expanduser().resolve()
        if not (source / "SKILL.md").is_file():
            raise SkillCenterHFReleaseError(
                f"skill directory is incomplete: {source}"
            )
        target = output / "skill" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_tree(source, target)
        copied_files["skill"] = _tree_descriptor(target, root=output)

    input_bindings = {
        "bm25_manifest_sha256": _sha256_file(bm25.root / "manifest.json"),
        "bm25_sqlite_cid": bm25.summary.sqlite_cid,
        "corpus_cid": corpus.summary.corpus_cid,
        "corpus_manifest_sha256": _sha256_file(
            corpus.root / "manifest.json"
        ),
        "graph_cid": graph.summary.graph_cid,
        "graph_manifest_sha256": _sha256_file(
            graph.root / "manifest.json"
        ),
        "vector_faiss_cid": vectors.summary.faiss_cid,
        "vector_manifest_sha256": _sha256_file(
            vectors.root / "manifest.json"
        ),
    }
    counts = {
        "bm25_document_chunks": len(document_meta),
        "bm25_documents": sum(int(row["row_count"]) for row in document_meta),
        "bm25_keyword_shards": len(bm25_meta),
        "bm25_posting_rows": int(bm25_stats["posting_rows"]),
        "bm25_postings": int(bm25_stats["posting_count"]),
        "bm25_terms": int(bm25_stats["term_count"]),
        "corpus_chunks": len(corpus_meta),
        "corpus_rows": sum(int(row["row_count"]) for row in corpus_meta),
        "graph_edge_chunks": len(graph_edge_meta),
        "graph_edges": sum(int(row["row_count"]) for row in graph_edge_meta),
        "graph_node_chunks": len(graph_node_meta),
        "graph_nodes": sum(int(row["row_count"]) for row in graph_node_meta),
        "graph_outgoing_adjacency_rows": int(
            graph_outgoing_stats["row_count"]
        ),
        "graph_outgoing_adjacency_shards": len(graph_outgoing_meta),
        "graph_outgoing_adjacency_edges": int(
            graph_outgoing_stats["adjacency_count"]
        ),
        "graph_incoming_adjacency_rows": int(
            graph_incoming_stats["row_count"]
        ),
        "graph_incoming_adjacency_shards": len(graph_incoming_meta),
        "graph_incoming_adjacency_edges": int(
            graph_incoming_stats["adjacency_count"]
        ),
        "vector_chunks": len(vector_meta),
        "vector_rows": sum(int(row["row_count"]) for row in vector_meta),
    }
    if {
        counts["corpus_rows"],
        counts["bm25_documents"],
        counts["vector_rows"],
    } != {expected_rows}:
        raise SkillCenterHFReleaseError(
            f"release row coverage differs: {counts}"
        )
    if counts["graph_nodes"] != graph.summary.graph_nodes:
        raise SkillCenterHFReleaseError("graph node export is incomplete")
    if counts["graph_edges"] != graph.summary.graph_edges:
        raise SkillCenterHFReleaseError("graph edge export is incomplete")
    if {
        counts["graph_outgoing_adjacency_edges"],
        counts["graph_incoming_adjacency_edges"],
    } != {graph.summary.graph_edges}:
        raise SkillCenterHFReleaseError(
            "graph adjacency export is incomplete"
        )

    manifest = {
        "bm25": {
            "average_document_length": bm25_stats[
                "average_document_length"
            ],
            "b": FTS5_B,
            "body_weight": bm25.config.body_weight,
            "k1": FTS5_K1,
            "max_query_terms": bm25.config.max_query_terms,
            "posting_rows_per_record": BM25_POSTINGS_PER_ROW,
            "terms_per_shard": BM25_TERMS_PER_SHARD,
            "title_weight": bm25.config.title_weight,
            "tokenizer": bm25.config.tokenizer,
        },
        "counts": counts,
        "dataset_id": corpus.manifest["dataset_id"],
        "dataset_repo_id": repo_id,
        "dataset_revision": dataset_revision,
        "files": copied_files,
        "indexes": index_descriptors,
        "input_bindings": input_bindings,
        "graph": {
            "adjacency_pointers_per_row": (
                GRAPH_ADJACENCY_POINTERS_PER_ROW
            ),
            "adjacency_pointers_per_shard": (
                GRAPH_ADJACENCY_POINTERS_PER_SHARD
            ),
            "directions": ["incoming", "outgoing"],
            "max_remote_walk_depth": 8,
            "ordering": "score_desc_nulls_last",
        },
        "parquet": {
            "compression": PARQUET_COMPRESSION,
            "compression_level": PARQUET_COMPRESSION_LEVEL,
            "max_rows_per_file": RELEASE_CHUNK_ROWS,
            "row_group_size": RELEASE_CHUNK_ROWS,
        },
        "primary_key": "entry_cid",
        "schema_version": SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        "vector": _vector_manifest_config(
            dimension=vectors.summary.dimension,
            model_name=vectors.summary.model_name,
            centroid_count=len(
                {int(row["cluster_id"]) for row in vector_meta}
            ),
            shard_count=len(vector_meta),
        ),
    }
    _atomic_write_bytes(
        output / "README.md",
        render_skillcenter_hf_readme(manifest).encode("utf-8"),
    )
    _atomic_write_bytes(
        complete_manifest,
        canonical_json_bytes(manifest),
    )
    _notify(
        progress_callback,
        {
            "phase": "complete",
            "counts": counts,
            "output_dir": str(output),
        },
    )
    return validate_skillcenter_hf_release(output)


def refresh_skillcenter_hf_release_support(
    root: str | Path,
    *,
    query_script: str | Path,
    skill_dir: str | Path,
    semantic_traversal_module: str | Path | None = None,
) -> SkillCenterHFReleaseSummary:
    """Refresh the dataset card, query client, and skill without data rebuild."""

    release_root = Path(root).expanduser().resolve()
    manifest_path = release_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterHFReleaseError(
            "completed release manifest is malformed"
        ) from exc
    source_script = Path(query_script).expanduser().resolve()
    source_skill = Path(skill_dir).expanduser().resolve()
    if not source_script.is_file():
        raise SkillCenterHFReleaseError(
            f"query script does not exist: {source_script}"
        )
    if not (source_skill / "SKILL.md").is_file():
        raise SkillCenterHFReleaseError(
            f"skill directory is incomplete: {source_skill}"
        )
    target_script = release_root / "scripts" / "query_skillcenter_hf.py"
    target_script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_script, target_script)
    semantic_source = _semantic_traversal_source(
        semantic_traversal_module
    )
    semantic_target = release_root / "scripts" / "semantic_traversal.py"
    shutil.copy2(semantic_source, semantic_target)
    target_skill = release_root / "skill" / source_skill.name
    target_skill.parent.mkdir(parents=True, exist_ok=True)
    _copy_skill_tree(source_skill, target_skill)
    manifest["files"] = {
        "query_script": _file_descriptor(
            target_script,
            root=release_root,
        ),
        "semantic_traversal": _file_descriptor(
            semantic_target,
            root=release_root,
        ),
        "skill": _tree_descriptor(target_skill, root=release_root),
    }
    _atomic_write_bytes(
        release_root / "README.md",
        render_skillcenter_hf_readme(manifest).encode("utf-8"),
    )
    _atomic_write_bytes(
        manifest_path,
        canonical_json_bytes(manifest),
    )
    return validate_skillcenter_hf_release(release_root)


def retarget_skillcenter_hf_release(
    source_release: str | Path,
    *,
    output_dir: str | Path,
    dataset_repo_id: str,
    query_script: str | Path,
    skill_dir: str | Path,
    semantic_traversal_module: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SkillCenterHFReleaseSummary:
    """Prepare a clean release copy for a different Hub dataset repository.

    Immutable Parquet data and meta-indexes are hard-linked when possible.
    Dataset-card, client, skill, and manifest files are regenerated for the
    destination repository. Interpreter caches and other unmanifested support
    files are never copied.
    """

    repo_id = str(dataset_repo_id or "").strip()
    if "/" not in repo_id or repo_id.startswith("/") or repo_id.endswith("/"):
        raise SkillCenterHFReleaseError(
            "dataset_repo_id must have the form namespace/repository"
        )
    source = Path(source_release).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if source == output:
        raise SkillCenterHFReleaseError(
            "retarget output must differ from the source release"
        )
    if output.exists():
        if (output / "manifest.json").is_file():
            return validate_skillcenter_hf_release(output)
        raise SkillCenterHFReleaseError(
            f"retarget output already exists: {output}"
        )
    try:
        manifest_bytes = (source / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterHFReleaseError(
            "source release manifest is missing or malformed"
        ) from exc
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version")
        not in {
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2,
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        }
        or manifest.get("primary_key") != "entry_cid"
    ):
        raise SkillCenterHFReleaseError(
            "retarget requires a supported CID-keyed source release"
        )

    source_script = Path(query_script).expanduser().resolve()
    source_skill = Path(skill_dir).expanduser().resolve()
    if not source_script.is_file() or not (source_skill / "SKILL.md").is_file():
        raise SkillCenterHFReleaseError(
            "current query script or agent skill is missing"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-retarget-",
            dir=output.parent,
        )
    )
    moved = False
    try:
        _notify(
            progress_callback,
            {
                "dataset_repo_id": repo_id,
                "phase": "retarget_copy_artifacts",
            },
        )
        for root_name in ("data", "indexes"):
            source_root = source / root_name
            if not source_root.is_dir():
                raise SkillCenterHFReleaseError(
                    f"source release is missing {root_name}/"
                )
            for source_path in sorted(
                path for path in source_root.rglob("*") if path.is_file()
            ):
                relative = source_path.relative_to(source)
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source_path, target)
                except OSError:
                    shutil.copy2(source_path, target)

        target_script = staging / "scripts" / "query_skillcenter_hf.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_script, target_script)
        semantic_source = _semantic_traversal_source(
            semantic_traversal_module
        )
        semantic_target = staging / "scripts" / "semantic_traversal.py"
        shutil.copy2(semantic_source, semantic_target)
        target_skill = staging / "skill" / source_skill.name
        target_skill.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_tree(source_skill, target_skill)

        retargeted = dict(manifest)
        retargeted["dataset_repo_id"] = repo_id
        retargeted["files"] = {
            "query_script": _file_descriptor(
                target_script,
                root=staging,
            ),
            "semantic_traversal": _file_descriptor(
                semantic_target,
                root=staging,
            ),
            "skill": _tree_descriptor(target_skill, root=staging),
        }
        retargeted["publication"] = {
            "source_dataset_repo_id": str(
                manifest.get("dataset_repo_id") or ""
            ),
            "source_manifest_sha256": hashlib.sha256(
                manifest_bytes
            ).hexdigest(),
            "target_dataset_repo_id": repo_id,
        }
        _atomic_write_bytes(
            staging / "README.md",
            render_skillcenter_hf_readme(retargeted).encode("utf-8"),
        )
        _atomic_write_bytes(
            staging / "manifest.json",
            canonical_json_bytes(retargeted),
        )
        staged_summary = validate_skillcenter_hf_release(staging)
        os.replace(staging, output)
        moved = True
    finally:
        if not moved and staging.exists():
            shutil.rmtree(staging)

    _notify(
        progress_callback,
        {
            "dataset_repo_id": repo_id,
            "output_dir": str(output),
            "phase": "retarget_complete",
        },
    )
    return SkillCenterHFReleaseSummary(
        output_dir=str(output),
        dataset_repo_id=staged_summary.dataset_repo_id,
        dataset_revision=staged_summary.dataset_revision,
        corpus_rows=staged_summary.corpus_rows,
        bm25_terms=staged_summary.bm25_terms,
        bm25_postings=staged_summary.bm25_postings,
        graph_nodes=staged_summary.graph_nodes,
        graph_edges=staged_summary.graph_edges,
        vector_rows=staged_summary.vector_rows,
        vector_chunks=staged_summary.vector_chunks,
        manifest_sha256=staged_summary.manifest_sha256,
        graph_adjacency_rows=staged_summary.graph_adjacency_rows,
        graph_adjacency_shards=staged_summary.graph_adjacency_shards,
    )


def rebalance_skillcenter_hf_release_vectors(
    source_release: str | Path,
    *,
    output_dir: str | Path,
    corpus_dir: str | Path,
    vector_dir: str | Path,
    query_script: str | Path,
    skill_dir: str | Path,
    semantic_traversal_module: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SkillCenterHFReleaseSummary:
    """Create a v2 release by rebuilding only its vector layout.

    Immutable corpus, BM25, and graph artifacts are hard-linked when the
    source and destination share a filesystem, with a copy fallback.  The
    source release is never modified.
    """

    source = Path(source_release).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if source == output:
        raise SkillCenterHFReleaseError(
            "vector rebalance output must differ from the source release"
        )
    if output.exists():
        if (output / "manifest.json").is_file():
            return validate_skillcenter_hf_release(output)
        raise SkillCenterHFReleaseError(
            f"vector rebalance output already exists: {output}"
        )
    try:
        manifest = json.loads((source / "manifest.json").read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterHFReleaseError(
            "source release manifest is missing or malformed"
        ) from exc
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version")
        not in {
            "skillcenter-huggingface-release/v1",
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2,
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        }
        or manifest.get("primary_key") != "entry_cid"
    ):
        raise SkillCenterHFReleaseError(
            "source release schema is unsupported"
        )
    source_script = Path(query_script).expanduser().resolve()
    source_skill = Path(skill_dir).expanduser().resolve()
    if not source_script.is_file() or not (source_skill / "SKILL.md").is_file():
        raise SkillCenterHFReleaseError(
            "current query script or agent skill is missing"
        )

    corpus = SkillCenterCorpusIndex.load(corpus_dir, verify_rows=False)
    vectors = SkillCenterCIDVectorIndex.load(vector_dir)
    bindings = dict(manifest.get("input_bindings") or {})
    if (
        corpus.summary.dataset_revision != manifest.get("dataset_revision")
        or vectors.summary.dataset_revision != manifest.get("dataset_revision")
        or corpus.summary.source_records != vectors.summary.vector_count
        or corpus.summary.corpus_cid != bindings.get("corpus_cid")
        or vectors.summary.faiss_cid != bindings.get("vector_faiss_cid")
    ):
        raise SkillCenterHFReleaseError(
            "source release, corpus, and vector index bindings differ"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-vector-rebalance-",
            dir=output.parent,
        )
    )
    moved = False
    try:
        excluded_roots = {"scripts", "skill"}
        excluded_files = {
            "README.md",
            "indexes/vector_chunks.parquet",
            "manifest.json",
        }
        for source_path in sorted(
            path for path in source.rglob("*") if path.is_file()
        ):
            relative = source_path.relative_to(source)
            relative_posix = relative.as_posix()
            if (
                relative.parts[0] in excluded_roots
                or relative_posix in excluded_files
                or relative_posix.startswith("data/vectors/")
            ):
                continue
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source_path, target)
            except OSError:
                shutil.copy2(source_path, target)

        vector_meta = _export_vectors(
            vectors,
            corpus,
            staging,
            progress_callback=progress_callback,
        )
        vector_index = staging / "indexes" / "vector_chunks.parquet"
        _write_meta_index(vector_index, vector_meta)

        target_script = staging / "scripts" / "query_skillcenter_hf.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_script, target_script)
        semantic_source = _semantic_traversal_source(
            semantic_traversal_module
        )
        semantic_target = staging / "scripts" / "semantic_traversal.py"
        shutil.copy2(semantic_source, semantic_target)
        target_skill = staging / "skill" / source_skill.name
        target_skill.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_tree(source_skill, target_skill)

        upgraded = dict(manifest)
        upgraded["schema_version"] = SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2
        upgraded["indexes"] = {
            **dict(manifest["indexes"]),
            "vector_chunks": _file_descriptor(
                vector_index,
                root=staging,
            ),
        }
        upgraded["counts"] = {
            **dict(manifest["counts"]),
            "vector_chunks": len(vector_meta),
            "vector_rows": sum(
                int(row["row_count"]) for row in vector_meta
            ),
        }
        upgraded["vector"] = _vector_manifest_config(
            dimension=vectors.summary.dimension,
            model_name=vectors.summary.model_name,
            centroid_count=len(
                {int(row["cluster_id"]) for row in vector_meta}
            ),
            shard_count=len(vector_meta),
        )
        upgraded["files"] = {
            "query_script": _file_descriptor(
                target_script,
                root=staging,
            ),
            "semantic_traversal": _file_descriptor(
                semantic_target,
                root=staging,
            ),
            "skill": _tree_descriptor(target_skill, root=staging),
        }
        upgraded["vector_layout_upgrade"] = {
            "source_manifest_sha256": _sha256_file(
                source / "manifest.json"
            ),
            "source_schema_version": manifest["schema_version"],
        }
        _atomic_write_bytes(
            staging / "README.md",
            render_skillcenter_hf_readme(upgraded).encode("utf-8"),
        )
        _atomic_write_bytes(
            staging / "manifest.json",
            canonical_json_bytes(upgraded),
        )
        staged_summary = validate_skillcenter_hf_release(staging)
        os.replace(staging, output)
        moved = True
    finally:
        if not moved and staging.exists():
            shutil.rmtree(staging)

    return SkillCenterHFReleaseSummary(
        output_dir=str(output),
        dataset_repo_id=staged_summary.dataset_repo_id,
        dataset_revision=staged_summary.dataset_revision,
        corpus_rows=staged_summary.corpus_rows,
        bm25_terms=staged_summary.bm25_terms,
        bm25_postings=staged_summary.bm25_postings,
        graph_nodes=staged_summary.graph_nodes,
        graph_edges=staged_summary.graph_edges,
        vector_rows=staged_summary.vector_rows,
        vector_chunks=staged_summary.vector_chunks,
        manifest_sha256=staged_summary.manifest_sha256,
    )


def add_skillcenter_hf_graph_navigation(
    source_release: str | Path,
    *,
    output_dir: str | Path,
    graph_dir: str | Path,
    query_script: str | Path,
    skill_dir: str | Path,
    semantic_traversal_module: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SkillCenterHFReleaseSummary:
    """Add compact bidirectional adjacency artifacts to a v2 release."""

    source = Path(source_release).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if source == output:
        raise SkillCenterHFReleaseError(
            "graph navigation output must differ from the source release"
        )
    if output.exists():
        if (output / "manifest.json").is_file():
            return validate_skillcenter_hf_release(output)
        raise SkillCenterHFReleaseError(
            f"graph navigation output already exists: {output}"
        )
    try:
        manifest = json.loads((source / "manifest.json").read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterHFReleaseError(
            "source release manifest is missing or malformed"
        ) from exc
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version")
        not in {
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2,
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        }
        or manifest.get("primary_key") != "entry_cid"
    ):
        raise SkillCenterHFReleaseError(
            "graph navigation requires a v2 or v3 source release"
        )
    source_script = Path(query_script).expanduser().resolve()
    source_skill = Path(skill_dir).expanduser().resolve()
    if not source_script.is_file() or not (source_skill / "SKILL.md").is_file():
        raise SkillCenterHFReleaseError(
            "current query script or agent skill is missing"
        )
    graph = SkillCenterCIDGraphIndex.load(graph_dir)
    bindings = dict(manifest.get("input_bindings") or {})
    if (
        graph.summary.dataset_revision != manifest.get("dataset_revision")
        or graph.summary.graph_cid != bindings.get("graph_cid")
        or _sha256_file(graph.root / "manifest.json")
        != bindings.get("graph_manifest_sha256")
        or graph.summary.graph_edges
        != int(dict(manifest["counts"])["graph_edges"])
        or graph.summary.graph_nodes
        != int(dict(manifest["counts"])["graph_nodes"])
    ):
        raise SkillCenterHFReleaseError(
            "source release and graph index bindings differ"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-graph-navigation-",
            dir=output.parent,
        )
    )
    moved = False
    try:
        excluded_roots = {"scripts", "skill"}
        excluded_files = {
            "README.md",
            "indexes/graph_incoming_adjacency.parquet",
            "indexes/graph_outgoing_adjacency.parquet",
            "manifest.json",
        }
        for source_path in sorted(
            path for path in source.rglob("*") if path.is_file()
        ):
            relative = source_path.relative_to(source)
            relative_posix = relative.as_posix()
            if (
                relative.parts[0] in excluded_roots
                or relative_posix in excluded_files
                or relative_posix.startswith("data/graph/adjacency/")
            ):
                continue
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source_path, target)
            except OSError:
                shutil.copy2(source_path, target)

        outgoing_meta, outgoing_stats = _export_graph_adjacency(
            graph.database_path,
            direction="outgoing",
            output_root=staging,
            progress_callback=progress_callback,
        )
        incoming_meta, incoming_stats = _export_graph_adjacency(
            graph.database_path,
            direction="incoming",
            output_root=staging,
            progress_callback=progress_callback,
        )
        indexes = dict(manifest["indexes"])
        for name, rows in (
            ("graph_outgoing_adjacency", outgoing_meta),
            ("graph_incoming_adjacency", incoming_meta),
        ):
            path = staging / "indexes" / f"{name}.parquet"
            _write_meta_index(path, rows)
            indexes[name] = _file_descriptor(path, root=staging)

        target_script = staging / "scripts" / "query_skillcenter_hf.py"
        target_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_script, target_script)
        semantic_source = _semantic_traversal_source(
            semantic_traversal_module
        )
        semantic_target = staging / "scripts" / "semantic_traversal.py"
        shutil.copy2(semantic_source, semantic_target)
        target_skill = staging / "skill" / source_skill.name
        target_skill.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_tree(source_skill, target_skill)

        upgraded = dict(manifest)
        upgraded["schema_version"] = SKILLCENTER_HF_RELEASE_SCHEMA_VERSION
        upgraded["indexes"] = indexes
        upgraded["counts"] = {
            **dict(manifest["counts"]),
            "graph_outgoing_adjacency_rows": int(
                outgoing_stats["row_count"]
            ),
            "graph_outgoing_adjacency_shards": len(outgoing_meta),
            "graph_outgoing_adjacency_edges": int(
                outgoing_stats["adjacency_count"]
            ),
            "graph_incoming_adjacency_rows": int(
                incoming_stats["row_count"]
            ),
            "graph_incoming_adjacency_shards": len(incoming_meta),
            "graph_incoming_adjacency_edges": int(
                incoming_stats["adjacency_count"]
            ),
        }
        upgraded["graph"] = {
            "adjacency_pointers_per_row": (
                GRAPH_ADJACENCY_POINTERS_PER_ROW
            ),
            "adjacency_pointers_per_shard": (
                GRAPH_ADJACENCY_POINTERS_PER_SHARD
            ),
            "directions": ["incoming", "outgoing"],
            "max_remote_walk_depth": 8,
            "ordering": "score_desc_nulls_last",
        }
        upgraded["files"] = {
            "query_script": _file_descriptor(
                target_script,
                root=staging,
            ),
            "semantic_traversal": _file_descriptor(
                semantic_target,
                root=staging,
            ),
            "skill": _tree_descriptor(target_skill, root=staging),
        }
        upgraded["graph_navigation_upgrade"] = {
            "source_manifest_sha256": _sha256_file(
                source / "manifest.json"
            ),
            "source_schema_version": manifest["schema_version"],
        }
        _atomic_write_bytes(
            staging / "README.md",
            render_skillcenter_hf_readme(upgraded).encode("utf-8"),
        )
        _atomic_write_bytes(
            staging / "manifest.json",
            canonical_json_bytes(upgraded),
        )
        staged_summary = validate_skillcenter_hf_release(staging)
        os.replace(staging, output)
        moved = True
    finally:
        if not moved and staging.exists():
            shutil.rmtree(staging)

    return SkillCenterHFReleaseSummary(
        output_dir=str(output),
        dataset_repo_id=staged_summary.dataset_repo_id,
        dataset_revision=staged_summary.dataset_revision,
        corpus_rows=staged_summary.corpus_rows,
        bm25_terms=staged_summary.bm25_terms,
        bm25_postings=staged_summary.bm25_postings,
        graph_nodes=staged_summary.graph_nodes,
        graph_edges=staged_summary.graph_edges,
        vector_rows=staged_summary.vector_rows,
        vector_chunks=staged_summary.vector_chunks,
        manifest_sha256=staged_summary.manifest_sha256,
        graph_adjacency_rows=staged_summary.graph_adjacency_rows,
        graph_adjacency_shards=staged_summary.graph_adjacency_shards,
    )


def render_skillcenter_hf_readme(manifest: Mapping[str, Any]) -> str:
    """Render a Hugging Face dataset card for a completed release manifest."""

    counts = dict(manifest["counts"])
    dataset_repo_id = str(manifest["dataset_repo_id"])
    source_dataset_id = str(manifest["dataset_id"])
    revision = str(manifest["dataset_revision"])
    model_name = str(manifest["vector"]["model_name"])
    dimension = int(manifest["vector"]["dimension"])
    chunk_rows = int(manifest["parquet"]["max_rows_per_file"])
    return f"""---
pretty_name: SkillCenter Intent IR Retrieval Corpus
license: other
language:
- en
task_categories:
- text-retrieval
- feature-extraction
- sentence-similarity
size_categories:
- 100K<n<1M
tags:
- agents
- bm25
- embeddings
- graphrag
- ipfs
- parquet
- skills
configs:
- config_name: corpus
  data_files:
  - split: train
    path: data/corpus/*.parquet
- config_name: bm25_documents
  data_files:
  - split: train
    path: data/bm25/documents/*.parquet
- config_name: bm25_postings
  data_files:
  - split: train
    path: data/bm25/postings/*.parquet
- config_name: graph_nodes
  data_files:
  - split: train
    path: data/graph/nodes/*.parquet
- config_name: graph_edges
  data_files:
  - split: train
    path: data/graph/edges/*.parquet
- config_name: graph_outgoing_adjacency
  data_files:
  - split: train
    path: data/graph/adjacency/outgoing/*.parquet
- config_name: graph_incoming_adjacency
  data_files:
  - split: train
    path: data/graph/adjacency/incoming/*.parquet
- config_name: vectors
  data_files:
  - split: train
    path: data/vectors/*.parquet
- config_name: corpus_chunk_index
  data_files:
  - split: train
    path: indexes/corpus_chunks.parquet
- config_name: bm25_keyword_index
  data_files:
  - split: train
    path: indexes/bm25_keyword_shards.parquet
- config_name: vector_meta_index
  data_files:
  - split: train
    path: indexes/vector_chunks.parquet
- config_name: graph_outgoing_adjacency_index
  data_files:
  - split: train
    path: indexes/graph_outgoing_adjacency.parquet
- config_name: graph_incoming_adjacency_index
  data_files:
  - split: train
    path: indexes/graph_incoming_adjacency.parquet
---

# SkillCenter Intent IR retrieval corpus

This is the CID-keyed retrieval release at
[`{dataset_repo_id}`](https://huggingface.co/datasets/{dataset_repo_id}). It
converts the complete
[`{source_dataset_id}`](https://huggingface.co/datasets/{source_dataset_id})
SkillCenter corpus and its local retrieval artifacts into
thin-client-friendly, Zstandard-compressed Parquet. It is bound to upstream
revision `{revision}` and contains:

- {int(counts["corpus_rows"]):,} canonical skills keyed by `entry_cid`;
- {int(counts["bm25_terms"]):,} BM25 terms and
  {int(counts["bm25_postings"]):,} document-term postings;
- {int(counts["graph_nodes"]):,} graph nodes and
  {int(counts["graph_edges"]):,} graph edges; and
- {int(counts["vector_rows"]):,} normalized {dimension}-dimensional
  `{model_name}` vectors.

Every data shard contains at most {chunk_rows:,} rows. `entry_cid` is the
canonical content identity; integer `document_index` values are compact
pointers into the sharded release and are not primary identities.

## Remote retrieval without a full download

The bundled client fetches the manifest, compact meta-indexes, only the
relevant posting/vector shards, and corpus shards containing the final hits.

```bash
python -m pip install pyarrow numpy huggingface_hub
hf download {dataset_repo_id} \\
  scripts/query_skillcenter_hf.py scripts/semantic_traversal.py \\
  --repo-type dataset --local-dir .
python scripts/query_skillcenter_hf.py \\
  --repo-id {dataset_repo_id} \\
  --revision main \\
  bm25 "securely rotate an API credential" --top-k 10
```

Vector retrieval embeds the query locally, ranks chunk centroids, and fetches
only the requested candidate chunks:

```bash
python -m pip install pyarrow numpy huggingface_hub \\
  sentence-transformers torch
python scripts/query_skillcenter_hf.py \\
  --repo-id {dataset_repo_id} \\
  --revision main \\
  vector "securely rotate an API credential" \\
  --candidate-centroids 4 --device auto --top-k 10
```

Pass a pinned Hub commit to `--revision` for reproducible queries. Private
datasets use `HF_TOKEN`. Each response includes `fetch_trace`, which lists
every requested release file and its size.

## Index layout

- `indexes/bm25_keyword_shards.parquet` maps lexical term ranges to complete
  BM25 posting shards. Posting arrays are bounded to 4,096 document pointers
  per Parquet row.
- `indexes/vector_chunks.parquet` stores semantic routing centroids and their
  physical shard pointers. Recursive spherical k-means guarantees that each
  centroid points to only one or two shards; rows inside each shard are sorted
  by decreasing similarity to its shard centroid.
- `indexes/corpus_chunks.parquet` maps compact document ranges to canonical
  corpus shards.
- `data/graph/nodes` and `data/graph/edges` are the lossless logical Parquet
  conversion of the GraphRAG SQLite tables.
- `data/graph/adjacency/{{incoming,outgoing}}` stores compact, score-ordered
  neighbor pages. Each page contains at most 4,096 edge pointers and each
  artifact at most 8,192, allowing bounded node lookup and graph walks.

BM25 uses the original FTS5 title/body weights and exported document lengths.
Vector search normally probes four semantic centroids, each of which fetches
one or two shards, followed by exact cosine scoring inside those shards. Use
`--candidate-centroids 1` for minimum transfer, or increase it when higher
recall is more important.

Graph retrieval resolves a node CID through the compact range indexes and
downloads only adjacency artifacts intersecting the current frontier. The
client enforces depth, node, edge, per-node, and artifact budgets; high-degree
nodes can be paged without downloading their complete adjacency. Semantic
walks additionally route the query through the compact vector centroid index,
make only a bounded set of one-or-two-shard centroid groups available, and use
the bundled reusable traversal engine to choose the next graph direction.

```bash
python scripts/query_skillcenter_hf.py \\
  --repo-id {dataset_repo_id} \\
  --revision main \\
  graph neighbors <node-cid> --direction both --limit 25

python scripts/query_skillcenter_hf.py \\
  --repo-id {dataset_repo_id} \\
  --revision main \\
  graph walk <node-cid> --direction outgoing \\
  --max-depth 2 --max-nodes 100 --max-edges 500 --max-shards 32

python scripts/query_skillcenter_hf.py \\
  --repo-id {dataset_repo_id} \\
  --revision main \\
  graph walk <node-cid> --strategy semantic-beam \\
  --query "securely rotate an API credential" --direction adaptive \\
  --candidate-centroids 4 --max-vector-shards 8 --beam-width 16 \\
  --max-depth 2 --max-nodes 100 --max-edges 500 --max-shards 32
```

Semantic responses expose proximity, progress, direction-alignment, missing
embedding coverage, beam pruning, and every graph/vector shard fetched.
Non-skill graph nodes can lack vectors; these remain traversable through
structural edge scoring and are explicitly marked approximate.

The `graph_outgoing_adjacency` and `graph_incoming_adjacency` card configs can
also be filtered server-side through the Hugging Face Dataset Viewer API using
`node_cid`. The bundled client uses manifest-verified shard descriptors so it
works before Dataset Viewer materialization and with pinned Hub revisions.

## Provenance, licensing, and safe use

The release manifest records the source corpus, BM25 SQLite, graph, and FAISS
content identities, including SHA-256 bindings to each input manifest. CIDs
identify local content; they do not prove public IPFS pinning. The original
source URL, source type, license expression, provenance, and trust metadata
remain attached to each canonical skill.

The release packaging and query machinery are produced by
[`ipfs_datasets_py`](https://github.com/endomorphosis/ipfs_datasets_py).
SkillCenter aggregates material from multiple public sources. The framework
and packaging code do not replace each skill's original license; review the
record-level `license_expression` and source metadata before redistribution.

Retrieved skills and graph relationships are context-only inputs. They are not
formal proof authority and must not be executed solely because retrieval
ranked them highly. Inspect their content and provenance, apply the least
privilege needed, and obtain human approval before consequential actions.
"""


def _graph_edge_fingerprint_update(
    state: list[int],
    edge_cid: str,
) -> None:
    digest = hashlib.sha256(edge_cid.encode("utf-8")).digest()
    value = int.from_bytes(digest, "big")
    state[0] += 1
    state[1] ^= value
    state[2] = (state[2] + value) % (1 << 256)


def _validate_graph_adjacency(
    release_root: Path,
    *,
    index_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    counts: Mapping[str, Any],
    pq: Any,
) -> None:
    """Validate paging, ordering, coverage, and bounded artifact invariants."""

    graph_config = {
        "adjacency_pointers_per_row": GRAPH_ADJACENCY_POINTERS_PER_ROW,
        "adjacency_pointers_per_shard": (
            GRAPH_ADJACENCY_POINTERS_PER_SHARD
        ),
    }
    fingerprints: dict[str, tuple[int, int, int]] = {}
    for direction in ("incoming", "outgoing"):
        index_name = f"graph_{direction}_adjacency"
        meta_rows = sorted(
            index_rows[index_name],
            key=lambda row: int(row["shard_id"]),
        )
        fingerprint = [0, 0, 0]
        previous_node = ""
        previous_page = -1
        expected_pages = 0
        expected_neighbors = 0
        seen_neighbors = 0
        previous_order_key: tuple[Any, ...] | None = None
        for meta in meta_rows:
            if (
                str(meta["direction"]) != direction
                or int(meta["adjacency_count"])
                > graph_config["adjacency_pointers_per_shard"]
                or str(meta["first_key"]) > str(meta["last_key"])
            ):
                raise SkillCenterHFReleaseError(
                    f"{direction} adjacency shard metadata is malformed"
                )
            path = release_root.joinpath(
                *Path(str(meta["relative_path"])).parts
            )
            table = pq.read_table(path)
            rows = table.to_pylist()
            if (
                not rows
                or str(rows[0]["node_cid"]) != str(meta["first_key"])
                or str(rows[-1]["node_cid"]) != str(meta["last_key"])
                or int(rows[0]["page_index"])
                != int(meta["first_page_index"])
                or int(rows[-1]["page_index"])
                != int(meta["last_page_index"])
                or sum(int(row["neighbor_count"]) for row in rows)
                != int(meta["adjacency_count"])
            ):
                raise SkillCenterHFReleaseError(
                    f"{direction} adjacency shard range differs"
                )
            for row in rows:
                node_cid = str(row["node_cid"])
                page_index = int(row["page_index"])
                page_count = int(row["page_count"])
                total_neighbors = int(row["total_neighbor_count"])
                edge_cids = [str(value) for value in row["edge_cids"]]
                edge_types = [str(value) for value in row["edge_types"]]
                neighbor_cids = [
                    str(value) for value in row["neighbor_cids"]
                ]
                neighbor_types = [
                    str(value) for value in row["neighbor_node_types"]
                ]
                methods = [
                    str(value) for value in row["retrieval_methods"]
                ]
                scores = [
                    float(value) if value is not None else None
                    for value in row["scores"]
                ]
                neighbor_count = int(row["neighbor_count"])
                if (
                    str(row["direction"]) != direction
                    or str(row["schema_version"])
                    != SKILLCENTER_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
                    or not 1
                    <= neighbor_count
                    <= graph_config["adjacency_pointers_per_row"]
                    or not (
                        len(edge_cids)
                        == len(edge_types)
                        == len(neighbor_cids)
                        == len(neighbor_types)
                        == len(methods)
                        == len(scores)
                        == neighbor_count
                    )
                    or node_cid < previous_node
                ):
                    raise SkillCenterHFReleaseError(
                        f"{direction} adjacency row is malformed"
                    )
                if node_cid != previous_node:
                    if (
                        previous_node
                        and (
                            previous_page + 1 != expected_pages
                            or seen_neighbors != expected_neighbors
                        )
                    ):
                        raise SkillCenterHFReleaseError(
                            f"{direction} adjacency pages are incomplete"
                        )
                    if page_index != 0 or page_count < 1:
                        raise SkillCenterHFReleaseError(
                            f"{direction} adjacency pages do not start at zero"
                        )
                    previous_node = node_cid
                    previous_page = -1
                    expected_pages = page_count
                    expected_neighbors = total_neighbors
                    seen_neighbors = 0
                    previous_order_key = None
                if (
                    page_index != previous_page + 1
                    or page_count != expected_pages
                    or total_neighbors != expected_neighbors
                ):
                    raise SkillCenterHFReleaseError(
                        f"{direction} adjacency page sequence differs"
                    )
                for (
                    edge_cid,
                    edge_type,
                    neighbor_cid,
                    score,
                ) in zip(edge_cids, edge_types, neighbor_cids, scores):
                    order_key = (
                        1 if score is None else 0,
                        -(score if score is not None else 0.0),
                        edge_type,
                        neighbor_cid,
                        edge_cid,
                    )
                    if (
                        previous_order_key is not None
                        and order_key < previous_order_key
                    ):
                        raise SkillCenterHFReleaseError(
                            f"{direction} adjacency is not score-ordered"
                        )
                    previous_order_key = order_key
                    _graph_edge_fingerprint_update(
                        fingerprint,
                        edge_cid,
                    )
                previous_page = page_index
                seen_neighbors += neighbor_count
        if (
            not previous_node
            or previous_page + 1 != expected_pages
            or seen_neighbors != expected_neighbors
            or fingerprint[0] != int(counts["graph_edges"])
            or fingerprint[0]
            != int(counts[f"graph_{direction}_adjacency_edges"])
        ):
            raise SkillCenterHFReleaseError(
                f"{direction} adjacency coverage differs"
            )
        fingerprints[direction] = tuple(fingerprint)
    if fingerprints["incoming"] != fingerprints["outgoing"]:
        raise SkillCenterHFReleaseError(
            "incoming and outgoing adjacency edge coverage differs"
        )


def validate_skillcenter_hf_release(
    root: str | Path,
) -> SkillCenterHFReleaseSummary:
    """Validate a completed release manifest, indexes, and shard invariants."""

    release_root = Path(root).expanduser().resolve()
    manifest_path = release_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterHFReleaseError(
            "release manifest is missing or malformed"
        ) from exc
    schema_version = (
        str(manifest.get("schema_version") or "")
        if isinstance(manifest, Mapping)
        else ""
    )
    if (
        not isinstance(manifest, Mapping)
        or schema_version
        not in {
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION_V2,
            SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        }
        or manifest.get("primary_key") != "entry_cid"
    ):
        raise SkillCenterHFReleaseError("unsupported release manifest")
    has_graph_navigation = (
        schema_version == SKILLCENTER_HF_RELEASE_SCHEMA_VERSION
    )
    indexes = manifest.get("indexes")
    if not isinstance(indexes, Mapping):
        raise SkillCenterHFReleaseError("release indexes are missing")
    required_indexes = {
        "bm25_document_chunks",
        "bm25_keyword_shards",
        "corpus_chunks",
        "graph_edge_chunks",
        "graph_node_chunks",
        "vector_chunks",
    }
    if has_graph_navigation:
        required_indexes.update(
            {
                "graph_incoming_adjacency",
                "graph_outgoing_adjacency",
            }
        )
    if set(indexes) != required_indexes:
        raise SkillCenterHFReleaseError(
            f"release index set differs: {sorted(indexes)}"
        )
    _, pq = _pyarrow()
    index_rows: dict[str, list[dict[str, Any]]] = {}
    data_paths: set[str] = set()
    for name, descriptor in indexes.items():
        path = _verify_file_descriptor(release_root, descriptor)
        _validate_parquet_file(path, max_rows=None)
        table = pq.read_table(path)
        rows = [dict(row) for row in table.to_pylist()]
        index_rows[name] = rows
        for row in table.to_pylist():
            shard_path = _verify_file_descriptor(
                release_root,
                {
                    "cid": row["cid"],
                    "relative_path": row["relative_path"],
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                },
            )
            _validate_parquet_file(
                shard_path,
                max_rows=RELEASE_CHUNK_ROWS,
            )
            actual_rows = int(pq.ParquetFile(shard_path).metadata.num_rows)
            if actual_rows != int(row["row_count"]):
                raise SkillCenterHFReleaseError(
                    f"shard row count differs: {row['relative_path']}"
                )
            relative_path = str(row["relative_path"])
            if relative_path in data_paths:
                raise SkillCenterHFReleaseError(
                    f"duplicate shard pointer: {relative_path}"
                )
            data_paths.add(relative_path)
    actual_data_paths = {
        path.relative_to(release_root).as_posix()
        for path in (release_root / "data").rglob("*.parquet")
        if path.is_file()
    }
    if data_paths != actual_data_paths:
        raise SkillCenterHFReleaseError(
            "meta-index pointers do not cover the data files exactly"
        )
    readme = release_root / "README.md"
    if readme.is_symlink() or not readme.is_file():
        raise SkillCenterHFReleaseError("release README.md is missing")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise SkillCenterHFReleaseError("release support files are missing")
    query_descriptor = files.get("query_script")
    if not isinstance(query_descriptor, Mapping):
        raise SkillCenterHFReleaseError("release query script is missing")
    _verify_file_descriptor(release_root, query_descriptor)
    semantic_descriptor = files.get("semantic_traversal")
    if not isinstance(semantic_descriptor, Mapping):
        raise SkillCenterHFReleaseError(
            "release semantic traversal module is missing"
        )
    semantic_path = _verify_file_descriptor(
        release_root,
        semantic_descriptor,
    )
    if semantic_path.parent != release_root / "scripts":
        raise SkillCenterHFReleaseError(
            "release semantic traversal module is not beside the client"
        )
    skill_descriptor = files.get("skill")
    if not isinstance(skill_descriptor, Mapping):
        raise SkillCenterHFReleaseError("release agent skill is missing")
    skill_path = release_root.joinpath(
        *Path(str(skill_descriptor.get("relative_path") or "")).parts
    )
    if not (skill_path / "SKILL.md").is_file():
        raise SkillCenterHFReleaseError("release agent skill is incomplete")
    actual_skill = _tree_descriptor(skill_path, root=release_root)
    if (
        actual_skill["sha256"] != skill_descriptor.get("sha256")
        or actual_skill["file_count"] != skill_descriptor.get("file_count")
    ):
        raise SkillCenterHFReleaseError(
            "release agent skill descriptor differs"
        )
    counts = dict(manifest["counts"])
    count_bindings = {
        "bm25_document_chunks": (
            "bm25_documents",
            "bm25_document_chunks",
        ),
        "bm25_keyword_shards": (
            "bm25_posting_rows",
            "bm25_keyword_shards",
        ),
        "corpus_chunks": ("corpus_rows", "corpus_chunks"),
        "graph_edge_chunks": ("graph_edges", "graph_edge_chunks"),
        "graph_node_chunks": ("graph_nodes", "graph_node_chunks"),
        "vector_chunks": ("vector_rows", "vector_chunks"),
    }
    if has_graph_navigation:
        count_bindings.update(
            {
                "graph_incoming_adjacency": (
                    "graph_incoming_adjacency_rows",
                    "graph_incoming_adjacency_shards",
                ),
                "graph_outgoing_adjacency": (
                    "graph_outgoing_adjacency_rows",
                    "graph_outgoing_adjacency_shards",
                ),
            }
        )
    for index_name, (row_count_name, shard_count_name) in count_bindings.items():
        rows = index_rows[index_name]
        if (
            sum(int(row["row_count"]) for row in rows)
            != int(counts[row_count_name])
            or len(rows) != int(counts[shard_count_name])
        ):
            raise SkillCenterHFReleaseError(
                f"release count binding differs: {index_name}"
            )
    if has_graph_navigation:
        graph_config = dict(manifest.get("graph") or {})
        if (
            int(graph_config.get("adjacency_pointers_per_row", -1))
            != GRAPH_ADJACENCY_POINTERS_PER_ROW
            or int(
                graph_config.get("adjacency_pointers_per_shard", -1)
            )
            != GRAPH_ADJACENCY_POINTERS_PER_SHARD
            or graph_config.get("directions")
            != ["incoming", "outgoing"]
        ):
            raise SkillCenterHFReleaseError(
                "graph navigation configuration is malformed"
            )
        _validate_graph_adjacency(
            release_root,
            index_rows=index_rows,
            counts=counts,
            pq=pq,
        )
    bm25_rows = index_rows["bm25_keyword_shards"]
    if (
        sum(int(row["term_count"]) for row in bm25_rows)
        != int(counts["bm25_terms"])
        or sum(int(row["posting_count"]) for row in bm25_rows)
        != int(counts["bm25_postings"])
    ):
        raise SkillCenterHFReleaseError(
            "BM25 meta-index coverage differs from manifest"
        )
    ordered_bm25 = sorted(bm25_rows, key=lambda row: int(row["shard_id"]))
    for previous, current in zip(ordered_bm25, ordered_bm25[1:]):
        if str(previous["last_key"]) >= str(current["first_key"]):
            raise SkillCenterHFReleaseError(
                "BM25 keyword ranges overlap or are not ordered"
            )
    vector_config = dict(manifest["vector"])
    dimension = int(vector_config["dimension"])
    vector_rows = index_rows["vector_chunks"]
    if (
        vector_config.get("layout") != "semantic_centroid_groups"
        or vector_config.get("assignment")
        != "recursive_spherical_kmeans"
        or vector_config.get("rows_sorted_by")
        != "cosine_similarity_to_shard_centroid_desc"
        or int(vector_config.get("shard_count", -1)) != len(vector_rows)
        or int(vector_config.get("default_probe_centroids", -1)) < 1
        or int(vector_config.get("max_shards_per_centroid", -1))
        != VECTOR_MAX_SHARDS_PER_CENTROID
        or int(vector_config.get("max_rows_per_centroid", -1))
        != VECTOR_MAX_ROWS_PER_CENTROID
    ):
        raise SkillCenterHFReleaseError(
            "semantic vector layout metadata is malformed"
        )
    vector_groups: dict[int, list[dict[str, Any]]] = {}
    for row in vector_rows:
        vector_groups.setdefault(int(row["cluster_id"]), []).append(row)
    if (
        sorted(vector_groups) != list(range(len(vector_groups)))
        or int(vector_config.get("centroid_count", -1))
        != len(vector_groups)
    ):
        raise SkillCenterHFReleaseError(
            "semantic vector centroid identifiers are malformed"
        )
    for cluster_id, group in vector_groups.items():
        ordered = sorted(
            group,
            key=lambda row: int(row["chunk_in_cluster"]),
        )
        centroid = [float(value) for value in ordered[0]["centroid"]]
        centroid_norm = math.sqrt(
            sum(value * value for value in centroid)
        )
        if (
            not 1 <= len(ordered) <= VECTOR_MAX_SHARDS_PER_CENTROID
            or [
                int(row["chunk_in_cluster"]) for row in ordered
            ] != list(range(len(ordered)))
            or any(
                int(row["centroid_shard_count"]) != len(ordered)
                for row in ordered
            )
            or sum(int(row["row_count"]) for row in ordered)
            > VECTOR_MAX_ROWS_PER_CENTROID
            or len(centroid) != dimension
            or not math.isclose(
                centroid_norm,
                1.0,
                rel_tol=1e-5,
                abs_tol=1e-5,
            )
            or any(
                len(row["centroid"]) != dimension
                or any(
                    not math.isclose(
                        float(left),
                        float(right),
                        rel_tol=1e-6,
                        abs_tol=1e-6,
                    )
                    for left, right in zip(
                        row["centroid"],
                        centroid,
                    )
                )
                for row in ordered[1:]
            )
        ):
            raise SkillCenterHFReleaseError(
                f"vector centroid {cluster_id} must point to one or two shards"
            )
        for row in ordered:
            shard_centroid = [
                float(value) for value in row["shard_centroid"]
            ]
            shard_norm = math.sqrt(
                sum(value * value for value in shard_centroid)
            )
            if len(shard_centroid) != dimension or not math.isclose(
                shard_norm,
                1.0,
                rel_tol=1e-5,
                abs_tol=1e-5,
            ):
                raise SkillCenterHFReleaseError(
                    "physical vector shard centroid is malformed"
                )
    if not (
        int(counts["corpus_rows"])
        == int(counts["bm25_documents"])
        == int(counts["vector_rows"])
    ):
        raise SkillCenterHFReleaseError(
            "release primary-key coverage counts differ"
        )
    cid_sets = {}
    document_sets = {}
    try:
        import numpy as np
    except ImportError as exc:
        raise SkillCenterHFReleaseError(
            "numpy is required to validate vector shard ordering"
        ) from exc
    vector_group_sums = {
        cluster_id: np.zeros(dimension, dtype=np.float64)
        for cluster_id in vector_groups
    }
    for name in ("corpus_chunks", "bm25_document_chunks", "vector_chunks"):
        cids: set[str] = set()
        documents: set[int] = set()
        for row in index_rows[name]:
            path = release_root.joinpath(
                *Path(str(row["relative_path"])).parts
            )
            columns = ["document_index", "entry_cid"]
            if name == "vector_chunks":
                columns.extend(
                    [
                        "chunk_id",
                        "cluster_id",
                        "embedding",
                        "schema_version",
                    ]
                )
            table = pq.read_table(path, columns=columns)
            cids.update(str(value) for value in table["entry_cid"].to_pylist())
            documents.update(
                int(value) for value in table["document_index"].to_pylist()
            )
            if name == "vector_chunks":
                shard_id = int(row["shard_id"])
                cluster_id = int(row["cluster_id"])
                expected_chunk = f"vector-{shard_id:06d}"
                if (
                    set(table["chunk_id"].to_pylist()) != {expected_chunk}
                    or set(table["cluster_id"].to_pylist()) != {cluster_id}
                    or set(table["schema_version"].to_pylist())
                    != {SKILLCENTER_HF_VECTOR_CHUNK_SCHEMA_VERSION}
                    or str(table["entry_cid"][0].as_py())
                    != str(row["first_key"])
                    or str(table["entry_cid"][table.num_rows - 1].as_py())
                    != str(row["last_key"])
                ):
                    raise SkillCenterHFReleaseError(
                        f"vector shard identity differs: {expected_chunk}"
                    )
                embeddings = table["embedding"].combine_chunks()
                matrix = np.asarray(
                    embeddings.values.to_numpy(zero_copy_only=False),
                    dtype=np.float32,
                ).reshape(table.num_rows, dimension)
                vector_group_sums[cluster_id] += matrix.sum(
                    axis=0,
                    dtype=np.float64,
                )
                centroid = np.asarray(
                    row["shard_centroid"],
                    dtype=np.float32,
                )
                mean = matrix.mean(axis=0)
                mean /= np.linalg.norm(mean)
                scores = matrix @ centroid
                if (
                    not np.allclose(
                        mean,
                        centroid,
                        rtol=1.0e-5,
                        atol=1.0e-5,
                    )
                    or bool(
                        (
                            scores[1:]
                            > scores[:-1] + np.float32(2.0e-6)
                        ).any()
                    )
                    or not math.isclose(
                        float(scores[-1]),
                        float(row["centroid_min_score"]),
                        rel_tol=1.0e-5,
                        abs_tol=2.0e-6,
                    )
                ):
                    raise SkillCenterHFReleaseError(
                        f"vector shard is not centroid-sorted: {expected_chunk}"
                    )
        cid_sets[name] = cids
        document_sets[name] = documents
    for cluster_id, vector_sum in vector_group_sums.items():
        vector_sum /= np.linalg.norm(vector_sum)
        expected = np.asarray(
            vector_groups[cluster_id][0]["centroid"],
            dtype=np.float64,
        )
        if not np.allclose(
            vector_sum,
            expected,
            rtol=1.0e-5,
            atol=1.0e-5,
        ):
            raise SkillCenterHFReleaseError(
                f"routing centroid differs from vector cell {cluster_id}"
            )
    expected_documents = set(range(int(counts["corpus_rows"])))
    if (
        len({frozenset(values) for values in cid_sets.values()}) != 1
        or any(values != expected_documents for values in document_sets.values())
    ):
        raise SkillCenterHFReleaseError(
            "corpus, BM25, and vector CID/document coverage differs"
        )
    return SkillCenterHFReleaseSummary(
        output_dir=str(release_root),
        dataset_repo_id=str(manifest["dataset_repo_id"]),
        dataset_revision=str(manifest["dataset_revision"]),
        corpus_rows=int(counts["corpus_rows"]),
        bm25_terms=int(counts["bm25_terms"]),
        bm25_postings=int(counts["bm25_postings"]),
        graph_nodes=int(counts["graph_nodes"]),
        graph_edges=int(counts["graph_edges"]),
        vector_rows=int(counts["vector_rows"]),
        vector_chunks=int(counts["vector_chunks"]),
        manifest_sha256=hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        graph_adjacency_rows=(
            int(counts.get("graph_incoming_adjacency_rows", 0))
            + int(counts.get("graph_outgoing_adjacency_rows", 0))
        ),
        graph_adjacency_shards=(
            int(counts.get("graph_incoming_adjacency_shards", 0))
            + int(counts.get("graph_outgoing_adjacency_shards", 0))
        ),
    )


def _export_corpus(
    corpus: SkillCenterCorpusIndex,
    output_root: Path,
    *,
    progress_callback: ProgressCallback | None,
) -> list[dict[str, Any]]:
    _, pq = _pyarrow()
    source = corpus.root / corpus.manifest["files"]["corpus"]["relative_path"]
    destination = output_root / "data" / "corpus"
    destination.mkdir(parents=True, exist_ok=True)
    metadata = []
    expected_index = 0
    for chunk_id, batch in enumerate(
        pq.ParquetFile(source).iter_batches(batch_size=RELEASE_CHUNK_ROWS)
    ):
        table = _table_from_batch(batch)
        if table.num_rows > RELEASE_CHUNK_ROWS:
            raise SkillCenterHFReleaseError("corpus batch exceeds shard limit")
        indices = [int(value) for value in table["corpus_index"].to_pylist()]
        if indices != list(range(expected_index, expected_index + len(indices))):
            raise SkillCenterHFReleaseError(
                "corpus_index is not contiguous"
            )
        table = table.append_column("document_index", table["corpus_index"])
        path = destination / f"part-{chunk_id:06d}.parquet"
        _write_parquet(path, table)
        metadata.append(
            _shard_meta_row(
                path,
                root=output_root,
                shard_id=chunk_id,
                row_count=table.num_rows,
                first_key=str(table["entry_cid"][0].as_py()),
                last_key=str(table["entry_cid"][table.num_rows - 1].as_py()),
                start_document_index=expected_index,
                end_document_index=expected_index + table.num_rows - 1,
                kind="corpus",
            )
        )
        expected_index += table.num_rows
        _notify(
            progress_callback,
            {
                "phase": "corpus",
                "rows_processed": expected_index,
                "rows_total": corpus.summary.source_records,
            },
        )
    if expected_index != corpus.summary.source_records:
        raise SkillCenterHFReleaseError("corpus export is incomplete")
    return metadata


def _export_bm25_documents(
    bm25: SkillCenterCorpusBM25Index,
    document_lengths: Sequence[tuple[int, int, int]],
    output_root: Path,
    *,
    progress_callback: ProgressCallback | None,
) -> list[dict[str, Any]]:
    pa, _ = _pyarrow()
    destination = output_root / "data" / "bm25" / "documents"
    destination.mkdir(parents=True, exist_ok=True)
    uri = f"{bm25.database_path.as_uri()}?mode=ro&immutable=1"
    metadata = []
    processed = 0
    schema = pa.schema(
        [
            ("entry_cid", pa.string(), False),
            ("document_index", pa.int32(), False),
            ("skill_id", pa.string(), False),
            ("title", pa.string(), False),
            ("domain", pa.string(), False),
            ("profile", pa.string(), False),
            ("repository_file", pa.string(), False),
            ("source_type", pa.string(), False),
            ("language", pa.string(), False),
            ("title_length", pa.int32(), False),
            ("body_length", pa.int32(), False),
            ("document_length", pa.int32(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": b"skillcenter-hf-bm25-document/v1",
        },
    )
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            "SELECT entry_cid, document_index, skill_id, title, domain, "
            "profile, repository_file, source_type, language "
            "FROM documents ORDER BY document_index"
        )
        chunk_id = 0
        while rows := cursor.fetchmany(RELEASE_CHUNK_ROWS):
            output_rows = []
            for row in rows:
                index = int(row["document_index"])
                title_length, body_length, total_length = document_lengths[
                    index
                ]
                output_rows.append(
                    {
                        **dict(row),
                        "title_length": title_length,
                        "body_length": body_length,
                        "document_length": total_length,
                        "schema_version": "skillcenter-hf-bm25-document/v1",
                    }
                )
            table = pa.Table.from_pylist(output_rows, schema=schema)
            path = destination / f"part-{chunk_id:06d}.parquet"
            _write_parquet(path, table)
            metadata.append(
                _shard_meta_row(
                    path,
                    root=output_root,
                    shard_id=chunk_id,
                    row_count=table.num_rows,
                    first_key=str(table["entry_cid"][0].as_py()),
                    last_key=str(
                        table["entry_cid"][table.num_rows - 1].as_py()
                    ),
                    start_document_index=processed,
                    end_document_index=processed + table.num_rows - 1,
                    kind="bm25_documents",
                )
            )
            processed += table.num_rows
            chunk_id += 1
            _notify(
                progress_callback,
                {
                    "phase": "bm25_documents",
                    "rows_processed": processed,
                    "rows_total": bm25.summary.indexed_entries,
                },
            )
    if processed != bm25.summary.indexed_entries:
        raise SkillCenterHFReleaseError("BM25 document export is incomplete")
    return metadata


def _export_bm25_postings(
    bm25: SkillCenterCorpusBM25Index,
    document_lengths: Sequence[tuple[int, int, int]],
    output_root: Path,
    *,
    progress_callback: ProgressCallback | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pa, _ = _pyarrow()
    destination = output_root / "data" / "bm25" / "postings"
    destination.mkdir(parents=True, exist_ok=True)
    uri = f"{bm25.database_path.as_uri()}?mode=ro&immutable=1"
    metadata = []
    last_term = ""
    total_terms = 0
    total_postings = 0
    total_posting_rows = 0
    total_token_instances = sum(item[2] for item in document_lengths)
    average_document_length = (
        total_token_instances / max(1, len(document_lengths))
    )
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.vocab_row USING "
            "fts5vocab(main, documents_fts, 'row')"
        )
        shard_id = 0
        while True:
            term_stats = connection.execute(
                "SELECT term, doc, cnt FROM vocab_row "
                "WHERE term > ? ORDER BY term LIMIT ?",
                (last_term, BM25_TERMS_PER_SHARD),
            ).fetchall()
            if not term_stats:
                break
            terms = [str(row[0]) for row in term_stats]
            first_term = terms[0]
            final_term = terms[-1]
            rows, posting_count, instance_count = _bm25_posting_rows(
                connection,
                first_term=first_term,
                last_term=final_term,
                expected_terms=terms,
                document_lengths=document_lengths,
                document_count=len(document_lengths),
            )
            if (
                posting_count != sum(int(row[1]) for row in term_stats)
                or instance_count != sum(int(row[2]) for row in term_stats)
            ):
                raise SkillCenterHFReleaseError(
                    "FTS5 row/instance posting statistics differ"
                )
            schema = _bm25_posting_schema(pa)
            for part in _partition_bm25_rows(rows):
                part_first_term = str(part[0]["term"])
                part_last_term = str(part[-1]["term"])
                part_terms = len({str(row["term"]) for row in part})
                part_postings = sum(
                    len(row["document_indices"]) for row in part
                )
                part_instances = sum(
                    sum(row["title_frequencies"])
                    + sum(row["body_frequencies"])
                    for row in part
                )
                path = destination / f"part-{shard_id:06d}.parquet"
                table = pa.Table.from_pylist(part, schema=schema)
                table = table.replace_schema_metadata(
                    {
                        **dict(schema.metadata or {}),
                        b"first_term": part_first_term.encode("utf-8"),
                        b"last_term": part_last_term.encode("utf-8"),
                        b"posting_count": str(part_postings).encode("ascii"),
                        b"term_count": str(part_terms).encode("ascii"),
                        b"token_instance_count": str(part_instances).encode(
                            "ascii"
                        ),
                    }
                )
                _write_parquet(path, table)
                metadata.append(
                    _shard_meta_row(
                        path,
                        root=output_root,
                        shard_id=shard_id,
                        row_count=table.num_rows,
                        first_key=part_first_term,
                        last_key=part_last_term,
                        start_document_index=-1,
                        end_document_index=-1,
                        kind="bm25_postings",
                        posting_count=part_postings,
                        term_count=part_terms,
                        token_instance_count=part_instances,
                    )
                )
                shard_id += 1
            total_terms += len(terms)
            total_postings += posting_count
            total_posting_rows += len(rows)
            last_term = final_term
            _notify(
                progress_callback,
                {
                    "phase": "bm25_postings",
                    "posting_rows": total_posting_rows,
                    "postings": total_postings,
                    "shards": shard_id,
                    "terms": total_terms,
                },
            )
    return metadata, {
        "average_document_length": average_document_length,
        "posting_count": total_postings,
        "posting_rows": total_posting_rows,
        "term_count": total_terms,
        "token_instance_count": total_token_instances,
    }


def _bm25_posting_rows(
    connection: sqlite3.Connection,
    *,
    first_term: str,
    last_term: str,
    expected_terms: Sequence[str],
    document_lengths: Sequence[tuple[int, int, int]],
    document_count: int,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    emitted_terms: list[str] = []
    total_postings = 0
    total_instances = 0
    current_term = ""
    current_doc = -1
    title_frequency = 0
    body_frequency = 0
    doc_ids: list[int] = []
    title_frequencies: list[int] = []
    body_frequencies: list[int] = []

    def finish_document() -> None:
        nonlocal title_frequency, body_frequency, total_instances
        if current_doc < 1:
            return
        document_index = current_doc - 1
        if not 0 <= document_index < len(document_lengths):
            raise SkillCenterHFReleaseError(
                "FTS posting document identifier is out of range"
            )
        doc_ids.append(document_index)
        title_frequencies.append(title_frequency)
        body_frequencies.append(body_frequency)
        total_instances += title_frequency + body_frequency
        title_frequency = 0
        body_frequency = 0

    def finish_term() -> None:
        nonlocal total_postings
        if not current_term:
            return
        finish_document()
        document_frequency = len(doc_ids)
        corpus_frequency = sum(title_frequencies) + sum(body_frequencies)
        chunk_count = math.ceil(
            document_frequency / BM25_POSTINGS_PER_ROW
        )
        idf = _fts5_idf(document_count, document_frequency)
        for chunk_index, start in enumerate(
            range(0, document_frequency, BM25_POSTINGS_PER_ROW)
        ):
            stop = min(start + BM25_POSTINGS_PER_ROW, document_frequency)
            selected_ids = doc_ids[start:stop]
            rows.append(
                {
                    "body_frequencies": body_frequencies[start:stop],
                    "corpus_frequency": corpus_frequency,
                    "document_frequency": document_frequency,
                    "document_indices": selected_ids,
                    "document_lengths": [
                        document_lengths[index][2]
                        for index in selected_ids
                    ],
                    "idf": idf,
                    "posting_chunk_count": chunk_count,
                    "posting_chunk_index": chunk_index,
                    "schema_version": (
                        SKILLCENTER_HF_BM25_POSTING_SCHEMA_VERSION
                    ),
                    "term": current_term,
                    "title_frequencies": title_frequencies[start:stop],
                }
            )
        total_postings += document_frequency
        emitted_terms.append(current_term)
        doc_ids.clear()
        title_frequencies.clear()
        body_frequencies.clear()

    cursor = connection.execute(
        "SELECT term, doc, col FROM documents_vocab "
        "WHERE term >= ? AND term <= ?",
        (first_term, last_term),
    )
    previous_key: tuple[str, int] | None = None
    for raw_term, raw_doc, raw_column in cursor:
        term = str(raw_term)
        doc = int(raw_doc)
        key = (term, doc)
        if previous_key is not None and key < previous_key:
            raise SkillCenterHFReleaseError(
                "FTS5 vocabulary scan is not canonically ordered"
            )
        if term != current_term:
            finish_term()
            current_term = term
            current_doc = doc
        elif doc != current_doc:
            finish_document()
            current_doc = doc
        column = str(raw_column)
        if column == "title":
            title_frequency += 1
        elif column == "body":
            body_frequency += 1
        else:
            raise SkillCenterHFReleaseError(
                f"unsupported FTS5 column: {column}"
            )
        previous_key = key
    finish_term()
    if emitted_terms != list(expected_terms):
        raise SkillCenterHFReleaseError(
            "FTS5 row and instance vocabularies differ"
        )
    return rows, total_postings, total_instances


def _partition_bm25_rows(
    rows: Sequence[Mapping[str, Any]],
) -> Iterator[list[Mapping[str, Any]]]:
    """Pack complete term groups into shards without splitting a term."""

    pending: list[Mapping[str, Any]] = []
    index = 0
    while index < len(rows):
        term = str(rows[index]["term"])
        stop = index + 1
        while stop < len(rows) and str(rows[stop]["term"]) == term:
            stop += 1
        group = list(rows[index:stop])
        if len(group) > RELEASE_CHUNK_ROWS:
            raise SkillCenterHFReleaseError(
                f"one BM25 term exceeds the Parquet row limit: {term!r}"
            )
        if pending and len(pending) + len(group) > RELEASE_CHUNK_ROWS:
            yield pending
            pending = []
        pending.extend(group)
        index = stop
    if pending:
        yield pending


def _export_graph_table(
    database_path: Path,
    *,
    table_name: str,
    order_column: str,
    output_root: Path,
    progress_callback: ProgressCallback | None,
) -> list[dict[str, Any]]:
    if table_name not in {"nodes", "edges"}:
        raise SkillCenterHFReleaseError("unsupported graph table")
    pa, _ = _pyarrow()
    schemas = {
        "nodes": pa.schema(
            [
                ("node_cid", pa.string(), False),
                ("node_type", pa.string(), False),
                ("entry_cid", pa.string()),
                ("label", pa.string(), False),
                ("properties_json", pa.large_string(), False),
                ("schema_version", pa.string(), False),
            ]
        ),
        "edges": pa.schema(
            [
                ("edge_cid", pa.string(), False),
                ("edge_type", pa.string(), False),
                ("source_cid", pa.string(), False),
                ("target_cid", pa.string(), False),
                ("retrieval_method", pa.string(), False),
                ("score", pa.float64()),
                ("query_terms_json", pa.large_string(), False),
                ("properties_json", pa.large_string(), False),
                ("schema_version", pa.string(), False),
            ]
        ),
    }
    destination = output_root / "data" / "graph" / table_name
    destination.mkdir(parents=True, exist_ok=True)
    uri = f"{database_path.as_uri()}?mode=ro&immutable=1"
    metadata = []
    processed = 0
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        total = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
        )
        cursor = connection.execute(
            f"SELECT * FROM {table_name} ORDER BY {order_column}"
        )
        shard_id = 0
        while rows := cursor.fetchmany(RELEASE_CHUNK_ROWS):
            table = pa.Table.from_pylist(
                [dict(row) for row in rows],
                schema=schemas[table_name],
            )
            path = destination / f"part-{shard_id:06d}.parquet"
            _write_parquet(path, table)
            first_key = str(table[order_column][0].as_py())
            last_key = str(table[order_column][table.num_rows - 1].as_py())
            metadata.append(
                _shard_meta_row(
                    path,
                    root=output_root,
                    shard_id=shard_id,
                    row_count=table.num_rows,
                    first_key=first_key,
                    last_key=last_key,
                    start_document_index=-1,
                    end_document_index=-1,
                    kind=f"graph_{table_name}",
                )
            )
            processed += table.num_rows
            shard_id += 1
            _notify(
                progress_callback,
                {
                    "phase": f"graph_{table_name}",
                    "rows_processed": processed,
                    "rows_total": total,
                },
            )
    if processed != total:
        raise SkillCenterHFReleaseError(
            f"graph {table_name} export is incomplete"
        )
    return metadata


def _iter_graph_adjacency_rows(
    connection: sqlite3.Connection,
    *,
    direction: str,
) -> Iterator[dict[str, Any]]:
    """Yield bounded adjacency pages ordered for deterministic traversal."""

    if direction == "outgoing":
        node_column = "source_cid"
        neighbor_column = "target_cid"
    elif direction == "incoming":
        node_column = "target_cid"
        neighbor_column = "source_cid"
    else:
        raise SkillCenterHFReleaseError(
            f"unsupported graph adjacency direction: {direction}"
        )
    cursor = connection.execute(
        "SELECT "
        f"e.{node_column} AS node_cid, "
        f"e.{neighbor_column} AS neighbor_cid, "
        "n.node_type AS neighbor_node_type, "
        "e.edge_cid, e.edge_type, e.retrieval_method, e.score "
        "FROM edges e "
        f"JOIN nodes n ON n.node_cid = e.{neighbor_column} "
        f"ORDER BY e.{node_column}, "
        "CASE WHEN e.score IS NULL THEN 1 ELSE 0 END, "
        "e.score DESC, e.edge_type, "
        f"e.{neighbor_column}, e.edge_cid"
    )
    current_node: str | None = None
    entries: list[sqlite3.Row] = []

    def pages(
        node_cid: str,
        values: Sequence[sqlite3.Row],
    ) -> Iterator[dict[str, Any]]:
        page_count = math.ceil(
            len(values) / GRAPH_ADJACENCY_POINTERS_PER_ROW
        )
        for page_index, start in enumerate(
            range(0, len(values), GRAPH_ADJACENCY_POINTERS_PER_ROW)
        ):
            selected = values[
                start : start + GRAPH_ADJACENCY_POINTERS_PER_ROW
            ]
            yield {
                "direction": direction,
                "edge_cids": [str(row["edge_cid"]) for row in selected],
                "edge_types": [str(row["edge_type"]) for row in selected],
                "neighbor_cids": [
                    str(row["neighbor_cid"]) for row in selected
                ],
                "neighbor_count": len(selected),
                "neighbor_node_types": [
                    str(row["neighbor_node_type"]) for row in selected
                ],
                "node_cid": node_cid,
                "page_count": page_count,
                "page_index": page_index,
                "retrieval_methods": [
                    str(row["retrieval_method"]) for row in selected
                ],
                "schema_version": (
                    SKILLCENTER_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
                ),
                "scores": [
                    (
                        float(row["score"])
                        if row["score"] is not None
                        else None
                    )
                    for row in selected
                ],
                "total_neighbor_count": len(values),
            }

    for row in cursor:
        node_cid = str(row["node_cid"])
        if current_node is None:
            current_node = node_cid
        if node_cid != current_node:
            yield from pages(current_node, entries)
            current_node = node_cid
            entries = []
        entries.append(row)
    if current_node is not None:
        yield from pages(current_node, entries)


def _export_graph_adjacency(
    database_path: Path,
    *,
    direction: str,
    output_root: Path,
    progress_callback: ProgressCallback | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Export a paged adjacency layer for bounded remote graph traversal."""

    if direction not in {"incoming", "outgoing"}:
        raise SkillCenterHFReleaseError(
            f"unsupported graph adjacency direction: {direction}"
        )
    pa, _ = _pyarrow()
    schema = pa.schema(
        [
            ("direction", pa.string(), False),
            ("edge_cids", pa.list_(pa.string()), False),
            ("edge_types", pa.list_(pa.string()), False),
            ("neighbor_cids", pa.list_(pa.string()), False),
            ("neighbor_count", pa.int32(), False),
            ("neighbor_node_types", pa.list_(pa.string()), False),
            ("node_cid", pa.string(), False),
            ("page_count", pa.int32(), False),
            ("page_index", pa.int32(), False),
            ("retrieval_methods", pa.list_(pa.string()), False),
            ("schema_version", pa.string(), False),
            ("scores", pa.list_(pa.float64()), False),
            ("total_neighbor_count", pa.int64(), False),
        ],
        metadata={
            b"schema_version": (
                SKILLCENTER_HF_GRAPH_ADJACENCY_SCHEMA_VERSION.encode()
            )
        },
    )
    destination = (
        output_root / "data" / "graph" / "adjacency" / direction
    )
    destination.mkdir(parents=True, exist_ok=True)
    uri = f"{database_path.as_uri()}?mode=ro&immutable=1"
    metadata = []
    pending: list[dict[str, Any]] = []
    pending_pointers = 0
    adjacency_count = 0
    row_count = 0
    node_count = 0
    shard_id = 0

    def flush() -> None:
        nonlocal pending, pending_pointers, shard_id
        if not pending:
            return
        table = pa.Table.from_pylist(pending, schema=schema)
        path = destination / f"part-{shard_id:06d}.parquet"
        _write_parquet(path, table)
        metadata.append(
            _shard_meta_row(
                path,
                root=output_root,
                shard_id=shard_id,
                row_count=table.num_rows,
                first_key=str(table["node_cid"][0].as_py()),
                last_key=str(
                    table["node_cid"][table.num_rows - 1].as_py()
                ),
                start_document_index=-1,
                end_document_index=-1,
                kind=f"graph_{direction}_adjacency",
                adjacency_count=pending_pointers,
                direction=direction,
                first_page_index=int(table["page_index"][0].as_py()),
                last_page_index=int(
                    table["page_index"][table.num_rows - 1].as_py()
                ),
                node_count=len(
                    set(str(row["node_cid"]) for row in pending)
                ),
            )
        )
        shard_id += 1
        _notify(
            progress_callback,
            {
                "adjacency_edges_processed": adjacency_count,
                "adjacency_rows_processed": row_count,
                "adjacency_shards": shard_id,
                "direction": direction,
                "phase": "graph_adjacency",
            },
        )
        pending = []
        pending_pointers = 0

    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        for row in _iter_graph_adjacency_rows(
            connection,
            direction=direction,
        ):
            pointers = int(row["neighbor_count"])
            if pending and (
                len(pending) >= RELEASE_CHUNK_ROWS
                or pending_pointers + pointers
                > GRAPH_ADJACENCY_POINTERS_PER_SHARD
            ):
                flush()
            pending.append(row)
            pending_pointers += pointers
            adjacency_count += pointers
            row_count += 1
            if int(row["page_index"]) == 0:
                node_count += 1
        flush()
    return metadata, {
        "adjacency_count": adjacency_count,
        "node_count": node_count,
        "row_count": row_count,
    }


def _balanced_shard_capacities(
    row_count: int,
    *,
    max_rows: int = RELEASE_CHUNK_ROWS,
) -> tuple[int, ...]:
    """Return near-equal capacities whose sum is ``row_count``."""

    if isinstance(row_count, bool) or row_count < 1:
        raise SkillCenterHFReleaseError("vector row count must be positive")
    if isinstance(max_rows, bool) or max_rows < 1:
        raise SkillCenterHFReleaseError("vector shard limit must be positive")
    shard_count = math.ceil(row_count / max_rows)
    base, larger_shards = divmod(row_count, shard_count)
    capacities = tuple(
        base + (1 if shard_id < larger_shards else 0)
        for shard_id in range(shard_count)
    )
    if (
        sum(capacities) != row_count
        or max(capacities) > max_rows
        or max(capacities) - min(capacities) > 1
    ):
        raise SkillCenterHFReleaseError(
            "balanced vector shard capacities are malformed"
        )
    return capacities


def _capacity_constrained_assignments(
    preference_scores: Any,
    preference_ids: Any,
    capacities: Sequence[int],
    *,
    np: Any,
) -> Any:
    """Assign every row to a preferred centroid without overflowing a shard.

    Rows propose to centroids in descending cosine-similarity order.  Each
    centroid retains its highest-scoring proposals up to its exact capacity.
    The stable matching is deterministic, including score ties.
    """

    scores = np.asarray(preference_scores, dtype=np.float32)
    preferences = np.asarray(preference_ids, dtype=np.int32)
    capacity_array = np.asarray(capacities, dtype=np.int64)
    if (
        scores.ndim != 2
        or preferences.shape != scores.shape
        or scores.shape[1] != len(capacity_array)
        or int(capacity_array.sum()) != scores.shape[0]
        or bool((capacity_array < 1).any())
        or not np.isfinite(scores).all()
    ):
        raise SkillCenterHFReleaseError(
            "centroid preferences or capacities are malformed"
        )
    centroid_count = scores.shape[1]
    if (
        bool((preferences < 0).any())
        or bool((preferences >= centroid_count).any())
    ):
        raise SkillCenterHFReleaseError(
            "centroid preference identifiers are malformed"
        )
    expected_ids = np.arange(centroid_count, dtype=np.int32)
    if not np.array_equal(
        np.sort(preferences, axis=1),
        np.broadcast_to(expected_ids, preferences.shape),
    ):
        raise SkillCenterHFReleaseError(
            "each vector must rank every shard centroid exactly once"
        )

    row_count = scores.shape[0]
    next_preference = np.zeros(row_count, dtype=np.int32)
    assignments = np.full(row_count, -1, dtype=np.int32)
    accepted: list[list[tuple[float, int, int]]] = [
        [] for _ in range(centroid_count)
    ]
    pending = deque(range(row_count))
    while pending:
        row_id = int(pending.popleft())
        rank = int(next_preference[row_id])
        if rank >= centroid_count:
            raise SkillCenterHFReleaseError(
                "capacity-constrained vector assignment did not converge"
            )
        centroid_id = int(preferences[row_id, rank])
        next_preference[row_id] = rank + 1
        proposal = (
            float(scores[row_id, rank]),
            -row_id,
            row_id,
        )
        retained = accepted[centroid_id]
        capacity = int(capacity_array[centroid_id])
        if len(retained) < capacity:
            heapq.heappush(retained, proposal)
            assignments[row_id] = centroid_id
            continue
        if proposal[:2] > retained[0][:2]:
            displaced = heapq.heapreplace(retained, proposal)
            displaced_row = int(displaced[2])
            assignments[displaced_row] = -1
            pending.append(displaced_row)
            assignments[row_id] = centroid_id
            continue
        pending.append(row_id)

    actual_counts = np.bincount(
        assignments,
        minlength=centroid_count,
    )
    if (
        bool((assignments < 0).any())
        or not np.array_equal(actual_counts, capacity_array)
    ):
        raise SkillCenterHFReleaseError(
            "balanced vector assignment coverage differs"
        )
    return assignments


def _spherical_kmeans_groups(
    matrix: Any,
    positions: Any,
    cluster_count: int,
    *,
    seed: int,
    faiss: Any,
    np: Any,
) -> list[Any]:
    """Partition selected unit vectors by nearest spherical centroid."""

    selected = matrix[positions]
    row_count, dimension = selected.shape
    cluster_count = min(int(cluster_count), row_count)
    if cluster_count < 1:
        raise SkillCenterHFReleaseError(
            "spherical vector cluster count must be positive"
        )
    training_count = min(row_count, VECTOR_TRAINING_ROWS)
    if training_count == row_count:
        training = selected
    else:
        sample_indices = np.linspace(
            0,
            row_count - 1,
            num=training_count,
            dtype=np.int64,
        )
        training = selected[sample_indices]
    kmeans = faiss.Kmeans(
        dimension,
        cluster_count,
        niter=20,
        nredo=1,
        seed=int(seed) & 0x7FFFFFFF,
        spherical=True,
        verbose=False,
    )
    kmeans.train(training)
    _, assignments = kmeans.index.search(selected, 1)
    assignments = assignments.reshape(-1)
    groups = [
        positions[np.flatnonzero(assignments == cluster_id)]
        for cluster_id in range(cluster_count)
    ]
    return [group for group in groups if len(group)]


def _semantic_centroid_groups(
    matrix: Any,
    *,
    faiss: Any,
    np: Any,
    progress_callback: ProgressCallback | None,
) -> list[Any]:
    """Create semantic cells that each fit in one or two physical shards."""

    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise SkillCenterHFReleaseError("vector matrix is malformed")
    row_count = matrix.shape[0]
    initial_count = min(VECTOR_COARSE_CLUSTERS, row_count)
    _notify(
        progress_callback,
        {
            "phase": "vector_centroid_training",
            "centroid_count": initial_count,
            "max_rows_per_centroid": VECTOR_MAX_ROWS_PER_CENTROID,
            "training_rows": min(row_count, VECTOR_TRAINING_ROWS),
        },
    )
    initial = _spherical_kmeans_groups(
        matrix,
        np.arange(row_count, dtype=np.int64),
        initial_count,
        seed=VECTOR_KMEANS_SEED,
        faiss=faiss,
        np=np,
    )

    def bounded(groups: Sequence[Any], *, seed_offset: int) -> list[Any]:
        output = []
        for group_index, positions in enumerate(groups):
            if len(positions) <= VECTOR_MAX_ROWS_PER_CENTROID:
                output.append(positions)
                continue
            child_count = math.ceil(
                len(positions) / VECTOR_MAX_ROWS_PER_CENTROID
            )
            children = _spherical_kmeans_groups(
                matrix,
                positions,
                child_count,
                seed=VECTOR_KMEANS_SEED + seed_offset + group_index,
                faiss=faiss,
                np=np,
            )
            if len(children) < 2 or max(map(len, children)) == len(positions):
                ordered = positions[
                    np.argsort(positions, kind="stable")
                ]
                children = [
                    ordered[start : start + VECTOR_MAX_ROWS_PER_CENTROID]
                    for start in range(
                        0,
                        len(ordered),
                        VECTOR_MAX_ROWS_PER_CENTROID,
                    )
                ]
            output.extend(
                bounded(
                    children,
                    seed_offset=seed_offset + 10_000 + group_index * 257,
                )
            )
        return output

    groups = bounded(initial, seed_offset=1_000)
    if (
        sum(len(group) for group in groups) != row_count
        or max(map(len, groups)) > VECTOR_MAX_ROWS_PER_CENTROID
    ):
        raise SkillCenterHFReleaseError(
            "semantic vector centroid coverage differs"
        )
    _notify(
        progress_callback,
        {
            "phase": "vector_centroid_partition",
            "centroid_count": len(groups),
            "max_shards_per_centroid": VECTOR_MAX_SHARDS_PER_CENTROID,
        },
    )
    return groups


def _centroid_group_shards(
    matrix: Any,
    positions: Any,
    *,
    seed: int,
    faiss: Any,
    np: Any,
) -> list[Any]:
    """Split one semantic cell into one or two balanced physical shards."""

    capacities = _balanced_shard_capacities(len(positions))
    if len(capacities) == 1:
        return [positions]
    selected = matrix[positions]
    dimension = selected.shape[1]
    kmeans = faiss.Kmeans(
        dimension,
        len(capacities),
        niter=15,
        nredo=1,
        seed=int(seed) & 0x7FFFFFFF,
        spherical=True,
        verbose=False,
    )
    kmeans.train(selected)
    centroids = np.asarray(
        kmeans.centroids,
        dtype=np.float32,
    ).reshape(len(capacities), dimension)
    centroid_index = faiss.IndexFlatIP(dimension)
    centroid_index.add(centroids)
    preference_scores, preference_ids = centroid_index.search(
        selected,
        len(capacities),
    )
    assignments = _capacity_constrained_assignments(
        preference_scores,
        preference_ids,
        capacities,
        np=np,
    )
    shards = [
        positions[np.flatnonzero(assignments == shard_id)]
        for shard_id in range(len(capacities))
    ]
    if [len(shard) for shard in shards] != list(capacities):
        raise SkillCenterHFReleaseError(
            "centroid-local physical shard coverage differs"
        )
    return shards


def _export_vectors(
    vectors: SkillCenterCIDVectorIndex,
    corpus: SkillCenterCorpusIndex,
    output_root: Path,
    *,
    progress_callback: ProgressCallback | None,
) -> list[dict[str, Any]]:
    pa, pq = _pyarrow()
    faiss, np = _faiss_numpy()
    count = vectors.summary.vector_count
    dimension = vectors.summary.dimension
    matrix = np.empty((count, dimension), dtype=np.float32)
    base_index = faiss.downcast_index(vectors.faiss_index.index)
    base_index.reconstruct_n(0, count, matrix)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (
        matrix.shape != (count, dimension)
        or not np.isfinite(matrix).all()
        or bool((norms == 0).any())
    ):
        raise SkillCenterHFReleaseError("FAISS vector matrix is malformed")
    matrix = (matrix / norms).astype(np.float32)
    identifiers = faiss.vector_to_array(
        vectors.faiss_index.id_map
    ).astype(np.int64)
    metadata_rows = list(vectors.metadata_rows)
    if not np.array_equal(
        identifiers,
        np.asarray(
            [int(row["faiss_id"]) for row in metadata_rows],
            dtype=np.int64,
        ),
    ):
        raise SkillCenterHFReleaseError(
            "FAISS insertion order differs from vector metadata"
        )
    corpus_path = (
        corpus.root / corpus.manifest["files"]["corpus"]["relative_path"]
    )
    corpus_rows = pq.read_table(
        corpus_path,
        columns=["corpus_index", "entry_cid"],
    ).to_pylist()
    document_by_cid = {
        str(row["entry_cid"]): int(row["corpus_index"])
        for row in corpus_rows
    }
    if len(document_by_cid) != count:
        raise SkillCenterHFReleaseError(
            "corpus CID/document pointer map is incomplete"
        )
    document_indices = np.asarray(
        [document_by_cid[str(row["entry_cid"])] for row in metadata_rows],
        dtype=np.int32,
    )

    centroid_groups = _semantic_centroid_groups(
        matrix,
        faiss=faiss,
        np=np,
        progress_callback=progress_callback,
    )

    destination = output_root / "data" / "vectors"
    destination.mkdir(parents=True, exist_ok=True)
    output_meta = []
    processed = 0
    shard_id = 0
    for cluster_id, group_positions in enumerate(centroid_groups):
        routing_centroid = matrix[group_positions].mean(axis=0)
        routing_norm = float(np.linalg.norm(routing_centroid))
        if not math.isfinite(routing_norm) or routing_norm == 0:
            raise SkillCenterHFReleaseError(
                "semantic routing centroid is malformed"
            )
        routing_centroid = (
            routing_centroid / routing_norm
        ).astype(np.float32)
        shards = _centroid_group_shards(
            matrix,
            group_positions,
            seed=VECTOR_KMEANS_SEED + 100_000 + cluster_id,
            faiss=faiss,
            np=np,
        )
        if not 1 <= len(shards) <= VECTOR_MAX_SHARDS_PER_CENTROID:
            raise SkillCenterHFReleaseError(
                "semantic centroid points to too many vector shards"
            )
        for chunk_in_cluster, selected in enumerate(shards):
            shard_centroid = matrix[selected].mean(axis=0)
            shard_norm = float(np.linalg.norm(shard_centroid))
            if not math.isfinite(shard_norm) or shard_norm == 0:
                raise SkillCenterHFReleaseError(
                    "physical vector shard centroid is malformed"
                )
            shard_centroid = (
                shard_centroid / shard_norm
            ).astype(np.float32)
            scores_to_centroid = matrix[selected] @ shard_centroid
            order = np.lexsort(
                (
                    document_indices[selected],
                    -scores_to_centroid,
                )
            )
            selected = selected[order]
            scores_to_centroid = scores_to_centroid[order]
            selected_matrix = matrix[selected]
            rows = [metadata_rows[int(index)] for index in selected]
            selected_docs = document_indices[selected]
            chunk_name = f"vector-{shard_id:06d}"
            table = pa.table(
                {
                    "chunk_id": pa.array(
                        [chunk_name] * len(selected), type=pa.string()
                    ),
                    "cluster_id": pa.array(
                        [cluster_id] * len(selected), type=pa.int32()
                    ),
                    "entry_cid": pa.array(
                        [str(row["entry_cid"]) for row in rows],
                        type=pa.string(),
                    ),
                    "faiss_id": pa.array(
                        [int(row["faiss_id"]) for row in rows],
                        type=pa.int64(),
                    ),
                    "document_index": pa.array(
                        selected_docs,
                        type=pa.int32(),
                    ),
                    "corpus_chunk_id": pa.array(
                        [
                            int(value) // RELEASE_CHUNK_ROWS
                            for value in selected_docs
                        ],
                        type=pa.int32(),
                    ),
                    "corpus_row_offset": pa.array(
                        [
                            int(value) % RELEASE_CHUNK_ROWS
                            for value in selected_docs
                        ],
                        type=pa.int32(),
                    ),
                    "skill_id": pa.array(
                        [str(row["skill_id"]) for row in rows],
                        type=pa.string(),
                    ),
                    "title": pa.array(
                        [str(row["title"]) for row in rows],
                        type=pa.string(),
                    ),
                    "domain": pa.array(
                        [str(row["domain"]) for row in rows],
                        type=pa.string(),
                    ),
                    "profile": pa.array(
                        [str(row["profile"]) for row in rows],
                        type=pa.string(),
                    ),
                    "repository_file": pa.array(
                        [str(row["repository_file"]) for row in rows],
                        type=pa.string(),
                    ),
                    "source_type": pa.array(
                        [str(row["source_type"]) for row in rows],
                        type=pa.string(),
                    ),
                    "language": pa.array(
                        [str(row["language"]) for row in rows],
                        type=pa.string(),
                    ),
                    "embedding": pa.FixedSizeListArray.from_arrays(
                        pa.array(
                            selected_matrix.reshape(-1),
                            type=pa.float32(),
                        ),
                        dimension,
                    ),
                    "schema_version": pa.array(
                        [SKILLCENTER_HF_VECTOR_CHUNK_SCHEMA_VERSION]
                        * len(selected),
                        type=pa.string(),
                    ),
                }
            )
            path = destination / f"part-{shard_id:06d}.parquet"
            _write_parquet(path, table)
            meta = _shard_meta_row(
                path,
                root=output_root,
                shard_id=shard_id,
                row_count=table.num_rows,
                first_key=str(table["entry_cid"][0].as_py()),
                last_key=str(
                    table["entry_cid"][table.num_rows - 1].as_py()
                ),
                start_document_index=int(selected_docs.min()),
                end_document_index=int(selected_docs.max()),
                kind="vectors",
                cluster_id=cluster_id,
                chunk_in_cluster=chunk_in_cluster,
                centroid=routing_centroid.tolist(),
                centroid_min_score=float(scores_to_centroid[-1]),
                centroid_shard_count=len(shards),
                dimension=dimension,
                model_name=vectors.summary.model_name,
                shard_centroid=shard_centroid.tolist(),
            )
            output_meta.append(meta)
            processed += table.num_rows
            shard_id += 1
            _notify(
                progress_callback,
                {
                    "phase": "vectors",
                    "rows_processed": processed,
                    "rows_total": count,
                    "vector_centroids": cluster_id + 1,
                    "vector_chunks": shard_id,
                },
            )
    if processed != count:
        raise SkillCenterHFReleaseError("vector export is incomplete")
    return output_meta


def _fts5_document_lengths(
    database_path: Path,
    *,
    expected_rows: int,
) -> list[tuple[int, int, int]]:
    uri = f"{database_path.as_uri()}?mode=ro&immutable=1"
    values: list[tuple[int, int, int] | None] = [None] * expected_rows
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        for rowid, payload in connection.execute(
            "SELECT id, sz FROM documents_fts_docsize ORDER BY id"
        ):
            counts = _decode_fts5_varints(bytes(payload))
            if len(counts) != 2:
                raise SkillCenterHFReleaseError(
                    "FTS5 docsize must contain title and body lengths"
                )
            document_index = int(rowid) - 1
            if not 0 <= document_index < expected_rows:
                raise SkillCenterHFReleaseError(
                    "FTS5 docsize rowid is out of range"
                )
            title_length, body_length = counts
            values[document_index] = (
                title_length,
                body_length,
                title_length + body_length,
            )
    if any(value is None for value in values):
        raise SkillCenterHFReleaseError("FTS5 docsize coverage is incomplete")
    return [value for value in values if value is not None]


def _validate_input_bindings(
    *,
    corpus: SkillCenterCorpusIndex,
    bm25: SkillCenterCorpusBM25Index,
    graph: SkillCenterCIDGraphIndex,
    vectors: SkillCenterCIDVectorIndex,
) -> None:
    corpus_manifest_sha256 = _sha256_file(corpus.root / "manifest.json")
    corpus_cid = str(corpus.manifest["files"]["corpus"]["cid"])
    expected_bm25_corpus = {
        "corpus_cid": corpus_cid,
        "manifest_sha256": corpus_manifest_sha256,
        "primary_key": str(corpus.manifest["primary_key"]),
        "source_records": int(corpus.manifest["source_records"]),
        "unique_entry_cids": int(corpus.manifest["unique_entry_cids"]),
    }
    expected_graph_corpus = {
        key: expected_bm25_corpus[key]
        for key in (
            "corpus_cid",
            "manifest_sha256",
            "primary_key",
            "source_records",
        )
    }
    expected_vector_corpus = {
        key: expected_bm25_corpus[key]
        for key in ("corpus_cid", "manifest_sha256", "source_records")
    }
    expected_graph_bm25 = {
        "indexed_entries": int(bm25.manifest["indexed_entries"]),
        "manifest_sha256": _sha256_file(bm25.root / "manifest.json"),
        "primary_key": str(bm25.manifest["primary_key"]),
        "sqlite_cid": str(bm25.manifest["sqlite"]["cid"]),
    }
    checks = {
        "bm25_to_corpus": (
            bm25.manifest.get("corpus_input") == expected_bm25_corpus
        ),
        "graph_to_bm25": (
            graph.manifest.get("bm25_input") == expected_graph_bm25
        ),
        "graph_to_corpus": (
            graph.manifest.get("corpus_input") == expected_graph_corpus
        ),
        "vectors_to_corpus": (
            vectors.manifest.get("corpus_input") == expected_vector_corpus
        ),
    }
    if not all(checks.values()):
        raise SkillCenterHFReleaseError(
            f"input artifact bindings differ: {checks}"
        )


def _decode_fts5_varints(payload: bytes) -> tuple[int, ...]:
    values = []
    current = 0
    active = False
    for byte in payload:
        active = True
        current = (current << 7) | (byte & 0x7F)
        if byte < 0x80:
            values.append(current)
            current = 0
            active = False
    if active:
        raise SkillCenterHFReleaseError("truncated FTS5 varint payload")
    return tuple(values)


def _fts5_idf(document_count: int, document_frequency: int) -> float:
    if (
        document_count < 1
        or document_frequency < 1
        or document_frequency > document_count
    ):
        raise SkillCenterHFReleaseError("invalid BM25 document frequency")
    value = math.log(
        (document_count - document_frequency + 0.5)
        / (document_frequency + 0.5)
    )
    return value if value > 0.0 else 1.0e-6


def _bm25_posting_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("body_frequencies", pa.list_(pa.int32()), False),
            ("corpus_frequency", pa.int64(), False),
            ("document_frequency", pa.int32(), False),
            ("document_indices", pa.list_(pa.int32()), False),
            ("document_lengths", pa.list_(pa.int32()), False),
            ("idf", pa.float64(), False),
            ("posting_chunk_count", pa.int32(), False),
            ("posting_chunk_index", pa.int32(), False),
            ("schema_version", pa.string(), False),
            ("term", pa.string(), False),
            ("title_frequencies", pa.list_(pa.int32()), False),
        ],
        metadata={
            b"schema_version": (
                SKILLCENTER_HF_BM25_POSTING_SCHEMA_VERSION.encode()
            )
        },
    )


def _write_meta_index(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pa, _ = _pyarrow()
    if not rows:
        raise SkillCenterHFReleaseError(
            f"cannot write an empty meta-index: {path.name}"
        )
    base_fields = [
        ("cid", pa.string(), False),
        ("end_document_index", pa.int64(), False),
        ("first_key", pa.string(), False),
        ("kind", pa.string(), False),
        ("last_key", pa.string(), False),
        ("relative_path", pa.string(), False),
        ("row_count", pa.int64(), False),
        ("schema_version", pa.string(), False),
        ("sha256", pa.string(), False),
        ("shard_id", pa.int32(), False),
        ("size_bytes", pa.int64(), False),
        ("start_document_index", pa.int64(), False),
    ]
    optional_types = {
        "adjacency_count": pa.int64(),
        "centroid": pa.list_(pa.float32()),
        "centroid_min_score": pa.float32(),
        "centroid_shard_count": pa.int32(),
        "chunk_in_cluster": pa.int32(),
        "cluster_id": pa.int32(),
        "dimension": pa.int32(),
        "direction": pa.string(),
        "first_page_index": pa.int32(),
        "last_page_index": pa.int32(),
        "model_name": pa.string(),
        "node_count": pa.int32(),
        "posting_count": pa.int64(),
        "term_count": pa.int32(),
        "token_instance_count": pa.int64(),
        "shard_centroid": pa.list_(pa.float32()),
    }
    optional_names = sorted(set().union(*(set(row) for row in rows)) - {
        name for name, *_ in base_fields
    })
    unknown = set(optional_names) - set(optional_types)
    if unknown:
        raise SkillCenterHFReleaseError(
            f"unsupported meta-index fields: {sorted(unknown)}"
        )
    schema = pa.schema(
        [
            *base_fields,
            *[(name, optional_types[name]) for name in optional_names],
        ],
        metadata={
            b"schema_version": SKILLCENTER_HF_META_SCHEMA_VERSION.encode()
        },
    )
    _write_parquet(path, pa.Table.from_pylist(list(rows), schema=schema))


def _shard_meta_row(
    path: Path,
    *,
    root: Path,
    shard_id: int,
    row_count: int,
    first_key: str,
    last_key: str,
    start_document_index: int,
    end_document_index: int,
    kind: str,
    **extra: Any,
) -> dict[str, Any]:
    descriptor = _file_descriptor(path, root=root)
    return {
        **descriptor,
        "end_document_index": int(end_document_index),
        "first_key": first_key,
        "kind": kind,
        "last_key": last_key,
        "row_count": int(row_count),
        "schema_version": SKILLCENTER_HF_META_SCHEMA_VERSION,
        "shard_id": int(shard_id),
        "start_document_index": int(start_document_index),
        **extra,
    }


def _write_parquet(path: Path, table: Any) -> None:
    _, pq = _pyarrow()
    if table.num_rows > RELEASE_CHUNK_ROWS:
        raise SkillCenterHFReleaseError(
            f"Parquet shard exceeds {RELEASE_CHUNK_ROWS} rows: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    pq.write_table(
        table,
        temporary,
        compression=PARQUET_COMPRESSION,
        compression_level=PARQUET_COMPRESSION_LEVEL,
        row_group_size=RELEASE_CHUNK_ROWS,
        use_dictionary=True,
        write_statistics=True,
    )
    _validate_parquet_file(temporary, max_rows=RELEASE_CHUNK_ROWS)
    os.replace(temporary, path)


def _validate_parquet_file(
    path: Path,
    *,
    max_rows: int | None,
) -> None:
    _, pq = _pyarrow()
    parquet = pq.ParquetFile(path)
    if max_rows is not None and parquet.metadata.num_rows > max_rows:
        raise SkillCenterHFReleaseError(
            f"Parquet file exceeds row limit: {path}"
        )
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.num_row_groups)
        for column in range(
            parquet.metadata.row_group(group).num_columns
        )
    }
    if compressions and compressions != {"ZSTD"}:
        raise SkillCenterHFReleaseError(
            f"Parquet file is not uniformly ZSTD-compressed: {path}"
        )


def _file_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    size_bytes, digest = _file_digest(path)
    return {
        "cid": cid_v1_from_digest(digest),
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
        "size_bytes": size_bytes,
    }


def _tree_descriptor(path: Path, *, root: Path) -> dict[str, Any]:
    entries = []
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        entries.append(_file_descriptor(item, root=root))
    digest = hashlib.sha256(canonical_json_bytes(entries)).digest()
    return {
        "cid": cid_v1_from_digest(digest),
        "file_count": len(entries),
        "files": entries,
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hex(),
    }


def _verify_file_descriptor(root: Path, value: Any) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterHFReleaseError("file descriptor is missing")
    relative = str(value.get("relative_path") or "")
    path = root.joinpath(*Path(relative).parts)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SkillCenterHFReleaseError(
            "file descriptor path escapes the release"
        ) from exc
    if (
        not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or path.is_symlink()
        or not path.is_file()
    ):
        raise SkillCenterHFReleaseError("file descriptor path is unsafe")
    size_bytes, digest = _file_digest(path)
    if (
        size_bytes != int(value.get("size_bytes", -1))
        or digest.hex() != str(value.get("sha256", ""))
        or cid_v1_from_digest(digest) != str(value.get("cid", ""))
    ):
        raise SkillCenterHFReleaseError(
            f"file descriptor failed verification: {relative}"
        )
    return path


def _file_digest(path: Path) -> tuple[int, bytes]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return size_bytes, digest.digest()


def _sha256_file(path: Path) -> str:
    return _file_digest(path)[1].hex()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _table_from_batch(batch: Any) -> Any:
    pa, _ = _pyarrow()
    return pa.Table.from_batches([batch])


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SkillCenterHFReleaseError(
            "pyarrow is required for Hugging Face release packaging"
        ) from exc
    return pa, pq


def _faiss_numpy() -> tuple[Any, Any]:
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise SkillCenterHFReleaseError(
            "faiss and numpy are required for vector export"
        ) from exc
    return faiss, np


def _notify(
    callback: ProgressCallback | None,
    event: Mapping[str, Any],
) -> None:
    if callback is not None:
        callback(dict(event))


__all__ = [
    "BM25_POSTINGS_PER_ROW",
    "BM25_TERMS_PER_SHARD",
    "DEFAULT_RELEASE_REPO_ID",
    "RELEASE_CHUNK_ROWS",
    "SKILLCENTER_HF_RELEASE_SCHEMA_VERSION",
    "SkillCenterHFReleaseError",
    "SkillCenterHFReleaseSummary",
    "build_skillcenter_hf_release",
    "refresh_skillcenter_hf_release_support",
    "render_skillcenter_hf_readme",
    "retarget_skillcenter_hf_release",
    "validate_skillcenter_hf_release",
]
