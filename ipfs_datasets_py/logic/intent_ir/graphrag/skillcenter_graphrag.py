"""Persisted, integrity-bound GraphRAG indexes for SkillCenter embeddings.

The builder joins verified embedding checkpoints back to pinned read-only
SkillCenter bundles, projects the full policy-classified corpus graph, and
creates an exact cosine FAISS index over eligible chunks.  Source bodies stay
in separately addressed blocks; vector metadata contains offsets and hashes,
never copied source text.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Final, Iterator

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1
from ..source_adapters.policy import (
    AllowedUseDecision,
    SkillSourcePolicy,
    SkillSourcePolicyDecision,
)
from ..source_adapters.skillcenter import (
    SkillCenterBundleReader,
    SkillCenterSkillRecord,
)
from .corpus_projector import (
    CorpusEvidenceRecord,
    CorpusNeighborObservation,
    CorpusProjector,
)
from .ontology import (
    AddressedArtifact,
    CorpusEdgeType,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusNodeType,
    IntentCorpusGraph,
)
from .retrieval import (
    GraphSnapshot,
    IntentGraphRetriever,
    NeighborCandidate,
    PartitionAssignment,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalResult,
)
from .skillcenter_embeddings import (
    iter_skillcenter_embedding_rows,
    load_skillcenter_embedding_corpus,
)
from .skillcenter_bm25 import SkillCenterBM25Index


SKILLCENTER_GRAPHRAG_INDEX_SCHEMA_VERSION: Final = (
    "skillcenter-graphrag-index/v1"
)
SKILLCENTER_GRAPHRAG_METADATA_SCHEMA_VERSION: Final = (
    "skillcenter-graphrag-vector-metadata/v1"
)
SKILLCENTER_GRAPHRAG_ASSIGNMENT_SCHEMA_VERSION: Final = (
    "skillcenter-graphrag-partitions/v1"
)
SKILLCENTER_GRAPHRAG_NEIGHBOR_SCHEMA_VERSION: Final = (
    "skillcenter-graphrag-neighbors/v1"
)
DEFAULT_NEIGHBOR_K: Final = 8
DEFAULT_PARTITION_SALT: Final = "intent-ir-skillcenter-partition/v1"
DEFAULT_TRAINING_PERCENT: Final = 80
DEFAULT_VALIDATION_PERCENT: Final = 10
DEFAULT_EVALUATION_PERCENT: Final = 10

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_GRAPH_BYTES = 512 * 1024 * 1024
_FILTER_FIELDS = frozenset(
    {
        "allowed_use",
        "domain",
        "language",
        "partition",
        "profile",
        "repository_file",
        "skill_id",
        "source_type",
    }
)
_EMBEDDING_ALLOWED_USES = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)


class SkillCenterGraphRAGError(ValueError):
    """Raised when a GraphRAG build or persisted index is invalid."""


@dataclass(frozen=True, slots=True)
class SkillCenterGraphRAGConfig:
    """Deterministic graph-neighborhood and split configuration."""

    neighbor_k: int = DEFAULT_NEIGHBOR_K
    partition_salt: str = DEFAULT_PARTITION_SALT
    training_percent: int = DEFAULT_TRAINING_PERCENT
    validation_percent: int = DEFAULT_VALIDATION_PERCENT
    evaluation_percent: int = DEFAULT_EVALUATION_PERCENT

    def __post_init__(self) -> None:
        if (
            isinstance(self.neighbor_k, bool)
            or not isinstance(self.neighbor_k, int)
            or not 1 <= self.neighbor_k <= 256
        ):
            raise SkillCenterGraphRAGError(
                "neighbor_k must be between 1 and 256"
            )
        salt = str(self.partition_salt or "").strip()
        if not salt or "\x00" in salt:
            raise SkillCenterGraphRAGError(
                "partition_salt must be non-empty normalized text"
            )
        object.__setattr__(self, "partition_salt", salt)
        percentages = (
            self.training_percent,
            self.validation_percent,
            self.evaluation_percent,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 100
            for value in percentages
        ):
            raise SkillCenterGraphRAGError(
                "partition percentages must be integers between 0 and 100"
            )
        if sum(percentages) != 100 or any(value == 0 for value in percentages):
            raise SkillCenterGraphRAGError(
                "partition percentages must be positive and sum to 100"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_percent": self.evaluation_percent,
            "neighbor_k": self.neighbor_k,
            "partition_salt": self.partition_salt,
            "training_percent": self.training_percent,
            "validation_percent": self.validation_percent,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SkillCenterGraphRAGBuildSummary:
    """Compact summary for a newly built or verified existing index."""

    output_dir: str
    dataset_revision: str
    model_name: str
    dimension: int
    source_records: int
    embedded_skills: int
    vector_count: int
    graph_nodes: int
    graph_edges: int
    neighbor_edges: int
    neighbor_backend: str
    graph_digest: str
    graph_cid: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_revision": self.dataset_revision,
            "dimension": self.dimension,
            "embedded_skills": self.embedded_skills,
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "graph_edges": self.graph_edges,
            "graph_nodes": self.graph_nodes,
            "manifest_sha256": self.manifest_sha256,
            "model_name": self.model_name,
            "neighbor_edges": self.neighbor_edges,
            "neighbor_backend": self.neighbor_backend,
            "output_dir": self.output_dir,
            "source_records": self.source_records,
            "vector_count": self.vector_count,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterGraphRAGSearchHit:
    """One source-addressed chunk hit with no inline source body."""

    row_index: int
    score: float
    metadata: Mapping[str, Any]
    proof_authority: bool = False
    authority: str = "context_only"

    def __post_init__(self) -> None:
        if (
            isinstance(self.row_index, bool)
            or not isinstance(self.row_index, int)
            or self.row_index < 0
        ):
            raise SkillCenterGraphRAGError(
                "search hit row_index must be non-negative"
            )
        if not math.isfinite(float(self.score)):
            raise SkillCenterGraphRAGError("search hit score must be finite")
        if self.proof_authority is not False or self.authority != "context_only":
            raise SkillCenterGraphRAGError(
                "GraphRAG search hits are context-only"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "metadata": dict(self.metadata),
            "proof_authority": self.proof_authority,
            "row_index": self.row_index,
            "score": float(self.score),
        }


class DirectoryContentAddressedStore:
    """Raw-CID block store rooted inside one atomic build directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise SkillCenterGraphRAGError(
                "block store root must be a real directory"
            )
        self._entries: dict[str, dict[str, Any]] = {}

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("block payload must be bytes")
        media_type = str(media_type or "").strip()
        if not media_type:
            raise SkillCenterGraphRAGError("block media_type must not be empty")
        digest = hashlib.sha256(payload).hexdigest()
        block_cid = cid_v1(payload)
        relative = PurePosixPath(digest[:2], block_cid)
        path = self.root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise SkillCenterGraphRAGError("block path must not be a symlink")
        if path.exists():
            if not path.is_file() or _file_sha256(path) != digest:
                raise SkillCenterGraphRAGError(
                    "existing content-addressed block failed verification"
                )
        else:
            _write_bytes(path, payload)
        entry = self._entries.setdefault(
            block_cid,
            {
                "cid": block_cid,
                "media_types": set(),
                "relative_path": (
                    PurePosixPath("blocks") / relative
                ).as_posix(),
                "sha256": digest,
                "size_bytes": len(payload),
            },
        )
        if (
            entry["sha256"] != digest
            or entry["size_bytes"] != len(payload)
        ):
            raise SkillCenterGraphRAGError(
                "content address was assigned conflicting bytes"
            )
        entry["media_types"].add(media_type)
        return block_cid

    def inventory(self) -> list[dict[str, Any]]:
        return [
            {
                **{
                    key: value
                    for key, value in self._entries[cid].items()
                    if key != "media_types"
                },
                "media_types": sorted(self._entries[cid]["media_types"]),
            }
            for cid in sorted(self._entries)
        ]


class SkillCenterGraphRAGIndex:
    """Verified local facade over a persisted SkillCenter GraphRAG index."""

    def __init__(
        self,
        *,
        root: Path,
        manifest: Mapping[str, Any],
        graph: IntentCorpusGraph,
        faiss_index: Any,
        metadata_rows: Sequence[Mapping[str, Any]],
        assignment_rows: Sequence[Mapping[str, Any]],
        neighbor_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.root = root
        self.manifest = dict(manifest)
        self.graph = graph
        self._faiss_index = faiss_index
        self.metadata_rows = tuple(dict(row) for row in metadata_rows)
        self.assignment_rows = tuple(dict(row) for row in assignment_rows)
        self.neighbor_rows = tuple(dict(row) for row in neighbor_rows)
        self._skill_node_by_id = {
            str(node.properties["skill_id"]): node.node_id
            for node in graph.nodes
            if node.node_type is CorpusNodeType.SKILL
        }
        self.assignments = {
            str(row["graph_node_id"]): PartitionAssignment(
                partition=str(row["partition"]),
                source_family=str(row["source_family"]),
                adversarial=bool(row["adversarial"]),
            )
            for row in self.assignment_rows
        }

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        verify_blocks: bool = True,
    ) -> "SkillCenterGraphRAGIndex":
        """Load an index only after verifying every declared artifact."""

        index_root = Path(root).expanduser().resolve()
        manifest_path = index_root / "manifest.json"
        if (
            index_root.is_symlink()
            or not index_root.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise SkillCenterGraphRAGError(
                "GraphRAG index must contain a bounded regular manifest.json"
            )
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCenterGraphRAGError(
                "GraphRAG index manifest is malformed"
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version")
            != SKILLCENTER_GRAPHRAG_INDEX_SCHEMA_VERSION
        ):
            raise SkillCenterGraphRAGError(
                "unsupported GraphRAG index manifest"
            )
        files = manifest.get("files")
        if not isinstance(files, Mapping):
            raise SkillCenterGraphRAGError(
                "GraphRAG index manifest files are missing"
            )
        required_files = {
            "assignments",
            "block_inventory",
            "graph",
            "metadata",
            "neighbors",
            "vector_index",
        }
        if set(files) != required_files:
            raise SkillCenterGraphRAGError(
                "GraphRAG index manifest has an unexpected file set"
            )
        paths = {
            key: _verify_file_descriptor(index_root, files[key])
            for key in sorted(required_files)
        }

        graph_path = paths["graph"]
        if graph_path.stat().st_size > _MAX_GRAPH_BYTES:
            raise SkillCenterGraphRAGError(
                "GraphRAG graph artifact exceeds the safety bound"
            )
        try:
            graph = _graph_from_payload(json.loads(graph_path.read_bytes()))
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SkillCenterGraphRAGError(
                "GraphRAG graph artifact is invalid"
            ) from exc
        graph_summary = manifest.get("graph")
        if (
            not isinstance(graph_summary, Mapping)
            or graph_summary.get("graph_cid") != graph.graph_cid
            or graph_summary.get("graph_digest") != graph.graph_digest
            or int(graph_summary.get("node_count", -1)) != len(graph.nodes)
            or int(graph_summary.get("edge_count", -1)) != len(graph.edges)
        ):
            raise SkillCenterGraphRAGError(
                "GraphRAG graph summary does not match graph.json"
            )

        _, parquet = _pyarrow()
        metadata_rows = parquet.read_table(paths["metadata"]).to_pylist()
        assignment_rows = parquet.read_table(paths["assignments"]).to_pylist()
        neighbor_rows = parquet.read_table(paths["neighbors"]).to_pylist()
        if (
            len(metadata_rows) != int(manifest.get("vector_count", -1))
            or len(assignment_rows) != int(manifest.get("source_records", -1))
            or len(neighbor_rows) != int(manifest.get("neighbor_edges", -1))
        ):
            raise SkillCenterGraphRAGError(
                "GraphRAG parquet row counts do not match the manifest"
            )

        faiss, np = _faiss_numpy()
        try:
            vector_index = faiss.read_index(str(paths["vector_index"]))
        except Exception as exc:
            raise SkillCenterGraphRAGError(
                "FAISS vector index cannot be loaded"
            ) from exc
        dimension = int(manifest.get("dimension", -1))
        vector_count = int(manifest.get("vector_count", -1))
        if (
            int(vector_index.d) != dimension
            or int(vector_index.ntotal) != vector_count
            or int(vector_index.metric_type) != int(faiss.METRIC_INNER_PRODUCT)
        ):
            raise SkillCenterGraphRAGError(
                "FAISS index shape or metric does not match the manifest"
            )
        reconstructed = np.asarray(
            vector_index.reconstruct_n(0, vector_count),
            dtype=np.float32,
        )
        norms = np.linalg.norm(reconstructed, axis=1)
        if (
            reconstructed.shape != (vector_count, dimension)
            or not np.isfinite(reconstructed).all()
            or not np.allclose(norms, 1.0, rtol=2e-4, atol=2e-4)
        ):
            raise SkillCenterGraphRAGError(
                "FAISS index contains malformed or non-normalized vectors"
            )

        _validate_loaded_rows(
            manifest,
            graph,
            metadata_rows,
            assignment_rows,
            neighbor_rows,
        )
        if verify_blocks:
            _verify_block_inventory(
                index_root,
                paths["block_inventory"],
                graph,
            )
        return cls(
            root=index_root,
            manifest=manifest,
            graph=graph,
            faiss_index=vector_index,
            metadata_rows=metadata_rows,
            assignment_rows=assignment_rows,
            neighbor_rows=neighbor_rows,
        )

    @property
    def summary(self) -> SkillCenterGraphRAGBuildSummary:
        return _summary_from_manifest(self.root, self.manifest)

    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        k: int = 10,
        filters: Mapping[str, str | Sequence[str]] | None = None,
        deduplicate_skills: bool = True,
    ) -> tuple[SkillCenterGraphRAGSearchHit, ...]:
        """Search eligible chunks with exact cosine similarity."""

        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
            raise SkillCenterGraphRAGError("k must be between 1 and 100")
        prepared_filters = _prepare_filters(filters)
        _, np = _faiss_numpy()
        try:
            query = np.asarray(list(query_vector), dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise SkillCenterGraphRAGError(
                "query_vector must be numeric"
            ) from exc
        dimension = int(self.manifest["dimension"])
        if (
            query.shape != (dimension,)
            or not np.isfinite(query).all()
            or float(np.linalg.norm(query)) == 0.0
        ):
            raise SkillCenterGraphRAGError(
                f"query_vector must be a finite non-zero ({dimension},) vector"
            )
        query = query / np.linalg.norm(query)
        candidate_count = (
            len(self.metadata_rows)
            if prepared_filters or deduplicate_skills
            else min(k, len(self.metadata_rows))
        )
        scores, indices = self._faiss_index.search(
            query.reshape(1, -1).astype(np.float32),
            candidate_count,
        )
        results: list[SkillCenterGraphRAGSearchHit] = []
        seen_skills: set[str] = set()
        for score, row_index in zip(scores[0], indices[0]):
            index_value = int(row_index)
            if index_value < 0:
                continue
            metadata = self.metadata_rows[index_value]
            if not _matches_filters(metadata, prepared_filters):
                continue
            skill_id = str(metadata["skill_id"])
            if deduplicate_skills and skill_id in seen_skills:
                continue
            seen_skills.add(skill_id)
            results.append(
                SkillCenterGraphRAGSearchHit(
                    row_index=index_value,
                    score=float(score),
                    metadata=metadata,
                )
            )
            if len(results) == k:
                break
        return tuple(results)

    def search_text(
        self,
        text: str,
        *,
        embedder: Callable[[Sequence[str]], object],
        k: int = 10,
        filters: Mapping[str, str | Sequence[str]] | None = None,
        deduplicate_skills: bool = True,
    ) -> tuple[SkillCenterGraphRAGSearchHit, ...]:
        """Embed one query through an injected router and search the index."""

        query_text = str(text or "").strip()
        if not query_text:
            raise SkillCenterGraphRAGError("query text must not be empty")
        if not callable(embedder):
            raise TypeError("embedder must be callable")
        value = embedder((query_text,))
        if hasattr(value, "tolist") and callable(getattr(value, "tolist")):
            value = value.tolist()
        if not isinstance(value, (list, tuple)) or len(value) != 1:
            raise SkillCenterGraphRAGError(
                "query embedder must return exactly one vector"
            )
        return self.search_vector(
            value[0],
            k=k,
            filters=filters,
            deduplicate_skills=deduplicate_skills,
        )

    def retrieve_skill_neighbors(
        self,
        skill_id: str,
        *,
        k: int = 8,
        max_bytes: int = 64 * 1024,
        timeout_ms: int = 1_000,
    ) -> RetrievalResult:
        """Run partition-isolated graph retrieval for one indexed skill."""

        normalized_skill_id = str(skill_id or "").strip()
        try:
            query_node_id = self._skill_node_by_id[normalized_skill_id]
            assignment = self.assignments[query_node_id]
        except KeyError as exc:
            raise SkillCenterGraphRAGError(
                f"skill is not present in the graph: {normalized_skill_id!r}"
            ) from exc
        rows = [
            row
            for row in self.neighbor_rows
            if row["source_node_id"] == query_node_id
            or row["target_node_id"] == query_node_id
        ]
        rows.sort(
            key=lambda row: (
                -float(row["score"]),
                str(row["edge_id"]),
            )
        )
        candidates = []
        for row in rows:
            neighbor_node_id = (
                str(row["target_node_id"])
                if row["source_node_id"] == query_node_id
                else str(row["source_node_id"])
            )
            candidates.append(
                NeighborCandidate(
                    node_id=neighbor_node_id,
                    edge_id=str(row["edge_id"]),
                    score=float(row["score"]),
                    graph_digest=self.graph.graph_digest,
                )
            )
        request = RetrievalRequest(
            query_node_id=query_node_id,
            snapshot=GraphSnapshot.from_graph(self.graph),
            partition=assignment.partition,
            source_family=assignment.source_family,
            k=k,
            max_bytes=max_bytes,
            timeout_ms=timeout_ms,
            filters=RetrievalFilters(
                node_types=(CorpusNodeType.SKILL.value,),
                edge_types=(CorpusEdgeType.NEIGHBOR_OF.value,),
            ),
            candidates=tuple(candidates),
            adversarial=assignment.adversarial,
        )
        return IntentGraphRetriever(
            self.graph,
            self.assignments,
        ).retrieve(request)


def build_skillcenter_graphrag_index(
    readers: Sequence[SkillCenterBundleReader],
    *,
    embedding_dirs: Sequence[str | Path],
    bm25_dir: str | Path | None = None,
    output_dir: str | Path,
    config: SkillCenterGraphRAGConfig | None = None,
    policy: SkillSourcePolicy | None = None,
) -> SkillCenterGraphRAGBuildSummary:
    """Build one atomic GraphRAG graph/vector index over verified corpora."""

    active_config = config or SkillCenterGraphRAGConfig()
    if not isinstance(active_config, SkillCenterGraphRAGConfig):
        raise TypeError("config must be a SkillCenterGraphRAGConfig")
    active_policy = policy or SkillSourcePolicy()
    prepared_readers = tuple(readers)
    if not prepared_readers or any(
        not isinstance(reader, SkillCenterBundleReader)
        for reader in prepared_readers
    ):
        raise TypeError(
            "readers must contain at least one SkillCenterBundleReader"
        )
    prepared_dirs = tuple(
        sorted(
            (Path(path).expanduser().resolve() for path in embedding_dirs),
            key=lambda path: str(path),
        )
    )
    if len(prepared_dirs) != len(prepared_readers):
        raise SkillCenterGraphRAGError(
            "embedding_dirs and readers must have the same bundle count"
        )
    embedding_manifests = tuple(
        load_skillcenter_embedding_corpus(path) for path in prepared_dirs
    )
    _validate_embedding_manifest_set(embedding_manifests)
    reader_by_file: dict[str, SkillCenterBundleReader] = {}
    for reader in prepared_readers:
        bundle = reader.inspect()
        if bundle.repository_file in reader_by_file:
            raise SkillCenterGraphRAGError(
                "duplicate reader repository_file"
            )
        reader_by_file[bundle.repository_file] = reader
    expected_files = {
        str(manifest["repository_file"]) for manifest in embedding_manifests
    }
    if set(reader_by_file) != expected_files:
        raise SkillCenterGraphRAGError(
            "readers do not match embedding corpus repository files"
        )
    for manifest in embedding_manifests:
        bundle = reader_by_file[str(manifest["repository_file"])].inspect()
        if bundle.to_dict() != manifest["bundle_manifest"]:
            raise SkillCenterGraphRAGError(
                "reader snapshot does not match its embedding corpus"
            )

    inputs = [
        {
            "bundle_sha256": str(manifest["bundle_sha256"]),
            "embedding_manifest_cid": cid_v1(
                (path / "manifest.json").read_bytes()
            ),
            "embedding_manifest_sha256": _file_sha256(
                path / "manifest.json"
            ),
            "profile": str(manifest["profile"]),
            "repository_file": str(manifest["repository_file"]),
            "source_records": int(manifest["source_records_total"]),
            "vector_count": int(manifest["vector_count"]),
        }
        for path, manifest in sorted(
            zip(prepared_dirs, embedding_manifests),
            key=lambda item: str(item[1]["repository_file"]),
        )
    ]
    bm25_index: SkillCenterBM25Index | None = None
    bm25_input: dict[str, Any] | None = None
    if bm25_dir is not None:
        bm25_root = Path(bm25_dir).expanduser().resolve()
        bm25_index = SkillCenterBM25Index.load(bm25_root)
        _validate_bm25_input(
            bm25_index,
            embedding_manifests=embedding_manifests,
        )
        bm25_manifest_bytes = (bm25_root / "manifest.json").read_bytes()
        bm25_input = {
            "build_identity_sha256": str(
                bm25_index.manifest["build_identity_sha256"]
            ),
            "indexed_skills": int(
                bm25_index.manifest["indexed_skills"]
            ),
            "manifest_cid": cid_v1(bm25_manifest_bytes),
            "manifest_sha256": hashlib.sha256(
                bm25_manifest_bytes
            ).hexdigest(),
            "posting_count": int(
                bm25_index.manifest["posting_count"]
            ),
            "vocabulary_size": int(
                bm25_index.manifest["vocabulary_size"]
            ),
        }
    build_identity_payload = {
        "bm25_input": bm25_input,
        "config": active_config.to_dict(),
        "inputs": inputs,
        "schema_version": SKILLCENTER_GRAPHRAG_INDEX_SCHEMA_VERSION,
    }
    build_identity_sha256 = hashlib.sha256(
        canonical_json_bytes(build_identity_payload)
    ).hexdigest()

    output = Path(output_dir).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise SkillCenterGraphRAGError(
            "output_dir must not be a symlink"
        )
    with _build_lock(output):
        if output.exists():
            existing = SkillCenterGraphRAGIndex.load(output)
            if (
                existing.manifest.get("build_identity_sha256")
                != build_identity_sha256
            ):
                raise SkillCenterGraphRAGError(
                    "existing index was built from different inputs or config"
                )
            return existing.summary

        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.",
                suffix=".partial",
                dir=output.parent,
            )
        )
        try:
            manifest = _build_into_directory(
                staging,
                reader_by_file=reader_by_file,
                embedding_dirs=prepared_dirs,
                embedding_manifests=embedding_manifests,
                inputs=inputs,
                build_identity_sha256=build_identity_sha256,
                bm25_index=bm25_index,
                bm25_input=bm25_input,
                config=active_config,
                policy=active_policy,
            )
            os.replace(staging, output)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
    loaded = SkillCenterGraphRAGIndex.load(output)
    if loaded.manifest != manifest:
        raise SkillCenterGraphRAGError(
            "published GraphRAG manifest changed during atomic promotion"
        )
    return loaded.summary


def _build_into_directory(
    root: Path,
    *,
    reader_by_file: Mapping[str, SkillCenterBundleReader],
    embedding_dirs: Sequence[Path],
    embedding_manifests: Sequence[Mapping[str, Any]],
    inputs: Sequence[Mapping[str, Any]],
    build_identity_sha256: str,
    bm25_index: SkillCenterBM25Index | None,
    bm25_input: Mapping[str, Any] | None,
    config: SkillCenterGraphRAGConfig,
    policy: SkillSourcePolicy,
) -> dict[str, Any]:
    faiss, np = _faiss_numpy()
    embedding_dir_by_file = {
        str(manifest["repository_file"]): path
        for path, manifest in zip(embedding_dirs, embedding_manifests)
    }
    vector_rows: list[dict[str, Any]] = []
    for repository_file in sorted(embedding_dir_by_file):
        vector_rows.extend(
            iter_skillcenter_embedding_rows(
                embedding_dir_by_file[repository_file]
            )
        )
    vector_rows.sort(
        key=lambda row: (
            str(row["repository_file"]),
            str(row["skill_id"]),
            int(row["chunk_index"]),
            str(row["chunk_id"]),
        )
    )
    if not vector_rows:
        raise SkillCenterGraphRAGError(
            "at least one eligible embedding vector is required"
        )
    dimension = int(embedding_manifests[0]["dimension"])
    try:
        vectors = np.asarray(
            [row["embedding"] for row in vector_rows],
            dtype=np.float32,
        )
    except (TypeError, ValueError) as exc:
        raise SkillCenterGraphRAGError(
            "embedding checkpoints contain malformed vectors"
        ) from exc
    if (
        vectors.shape != (len(vector_rows), dimension)
        or not np.isfinite(vectors).all()
    ):
        raise SkillCenterGraphRAGError(
            "embedding checkpoint vector shape is inconsistent"
        )
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if bool((norms == 0).any()):
        raise SkillCenterGraphRAGError(
            "embedding checkpoints contain a zero vector"
        )
    vectors = (vectors / norms).astype(np.float32)

    records: list[SkillCenterSkillRecord] = []
    decisions: dict[str, SkillSourcePolicyDecision] = {}
    record_by_key: dict[tuple[str, str], SkillCenterSkillRecord] = {}
    skill_ids: set[str] = set()
    for repository_file in sorted(reader_by_file):
        for record in reader_by_file[repository_file].iter_records():
            if record.skill_id in skill_ids:
                raise SkillCenterGraphRAGError(
                    "skill_id values must be globally unique across bundles"
                )
            skill_ids.add(record.skill_id)
            key = (record.repository_file, record.skill_id)
            record_by_key[key] = record
            records.append(record)
            decisions[record.skill_id] = policy.evaluate(record)
    records.sort(key=lambda record: (record.repository_file, record.skill_id))

    rows_by_skill: dict[str, list[int]] = defaultdict(list)
    embedded_keys: set[tuple[str, str]] = set()
    for row_index, row in enumerate(vector_rows):
        key = (str(row["repository_file"]), str(row["skill_id"]))
        record = record_by_key.get(key)
        if record is None:
            raise SkillCenterGraphRAGError(
                "embedding row does not resolve to a source record"
            )
        decision = decisions[record.skill_id]
        if decision.allowed_use not in _EMBEDDING_ALLOWED_USES:
            raise SkillCenterGraphRAGError(
                "embedding row is no longer allowed by the current policy"
            )
        if (
            str(row["content_sha256"]) != record.content_sha256
            or str(row["bundle_sha256"]) != record.bundle_sha256
            or str(row["allowed_use"]) != decision.allowed_use.value
        ):
            raise SkillCenterGraphRAGError(
                "embedding row provenance or policy binding is stale"
            )
        rows_by_skill[record.skill_id].append(row_index)
        embedded_keys.add(key)
    expected_embedded_keys = {
        (record.repository_file, record.skill_id)
        for record in records
        if decisions[record.skill_id].allowed_use in _EMBEDDING_ALLOWED_USES
    }
    if embedded_keys != expected_embedded_keys:
        raise SkillCenterGraphRAGError(
            "embedding skill coverage does not match the current policy"
        )

    if bm25_index is not None:
        expected_embedded_skill_ids = {
            skill_id for _repository_file, skill_id in expected_embedded_keys
        }
        if bm25_index.indexed_skill_ids != expected_embedded_skill_ids:
            raise SkillCenterGraphRAGError(
                "BM25 skill coverage does not match embedding/policy coverage"
            )
        (
            neighbor_observations,
            neighbor_pair_scores,
        ) = _bm25_skill_neighbors(
            bm25_index,
            k=config.neighbor_k,
        )
        neighbors: dict[str, tuple[str, ...]] = {}
        neighbor_backend = "bm25-okapi"
    else:
        pooled_skill_ids = sorted(rows_by_skill)
        pooled_vectors = []
        for skill_id in pooled_skill_ids:
            pooled = vectors[rows_by_skill[skill_id]].mean(axis=0)
            pooled_norm = float(np.linalg.norm(pooled))
            if not math.isfinite(pooled_norm) or pooled_norm == 0.0:
                raise SkillCenterGraphRAGError(
                    "pooled skill embedding is malformed"
                )
            pooled_vectors.append(
                (pooled / pooled_norm).astype(np.float32)
            )
        pooled_matrix = np.asarray(pooled_vectors, dtype=np.float32)
        neighbors, neighbor_pair_scores = _nearest_skill_neighbors(
            pooled_skill_ids,
            pooled_matrix,
            k=config.neighbor_k,
        )
        neighbor_observations = {}
        neighbor_backend = "embedding-cosine"

    evidence = tuple(
        CorpusEvidenceRecord(
            record,
            policy_decision=decisions[record.skill_id],
            neighbor_skill_ids=neighbors.get(record.skill_id, ()),
            neighbor_observations=neighbor_observations.get(
                record.skill_id, ()
            ),
        )
        for record in records
    )
    block_store = DirectoryContentAddressedStore(root / "blocks")
    graph = CorpusProjector(
        block_store,
        max_records=max(1, len(evidence)),
    ).project(evidence)
    graph_bytes = canonical_json_bytes(graph.to_dict())
    _write_bytes(root / "graph.json", graph_bytes)

    skill_node_by_id = {
        str(node.properties["skill_id"]): node.node_id
        for node in graph.nodes
        if node.node_type is CorpusNodeType.SKILL
    }
    if set(skill_node_by_id) != skill_ids:
        raise SkillCenterGraphRAGError(
            "projected graph skill nodes do not match source records"
        )
    assignment_rows: list[dict[str, Any]] = []
    assignment_by_skill: dict[str, dict[str, Any]] = {}
    for record in records:
        decision = decisions[record.skill_id]
        source_family = _source_family(record)
        assignment = {
            "adversarial": (
                decision.allowed_use is AllowedUseDecision.EXCLUDED
            ),
            "allowed_use": decision.allowed_use.value,
            "graph_node_id": skill_node_by_id[record.skill_id],
            "partition": _partition(source_family, config),
            "repository_file": record.repository_file,
            "schema_version": SKILLCENTER_GRAPHRAG_ASSIGNMENT_SCHEMA_VERSION,
            "skill_id": record.skill_id,
            "source_family": source_family,
            "source_ref_id": record.to_source_ref(
                review_status=decision.review_status
            ).ref_id,
        }
        assignment_rows.append(assignment)
        assignment_by_skill[record.skill_id] = assignment

    metadata_rows = []
    for row_index, row in enumerate(vector_rows):
        skill_id = str(row["skill_id"])
        assignment = assignment_by_skill[skill_id]
        metadata_rows.append(
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key != "embedding"
                },
                "graph_digest": graph.graph_digest,
                "graph_node_id": skill_node_by_id[skill_id],
                "partition": assignment["partition"],
                "row_index": row_index,
                "schema_version": SKILLCENTER_GRAPHRAG_METADATA_SCHEMA_VERSION,
                "source_family": assignment["source_family"],
            }
        )

    edge_by_nodes = {
        frozenset((edge.source, edge.target)): edge
        for edge in graph.edges
        if edge.edge_type is CorpusEdgeType.NEIGHBOR_OF
    }
    neighbor_rows = []
    for (left_skill, right_skill), score in sorted(
        neighbor_pair_scores.items()
    ):
        left_node = skill_node_by_id[left_skill]
        right_node = skill_node_by_id[right_skill]
        edge = edge_by_nodes.get(frozenset((left_node, right_node)))
        if edge is None:
            raise SkillCenterGraphRAGError(
                "projected graph is missing a retrieval neighbor edge"
            )
        source_node, target_node = sorted((left_node, right_node))
        source_skill, target_skill = (
            (left_skill, right_skill)
            if source_node == left_node
            else (right_skill, left_skill)
        )
        neighbor_rows.append(
            {
                "edge_id": edge.edge_id,
                "graph_digest": graph.graph_digest,
                "schema_version": SKILLCENTER_GRAPHRAG_NEIGHBOR_SCHEMA_VERSION,
                "score": float(score),
                "source_node_id": source_node,
                "source_skill_id": source_skill,
                "target_node_id": target_node,
                "target_skill_id": target_skill,
            }
        )
    neighbor_rows.sort(key=lambda row: str(row["edge_id"]))

    vector_index = faiss.IndexFlatIP(dimension)
    vector_index.add(vectors)
    faiss.write_index(vector_index, str(root / "index.faiss"))
    _write_metadata_parquet(root / "metadata.parquet", metadata_rows)
    _write_assignments_parquet(
        root / "assignments.parquet",
        assignment_rows,
    )
    _write_neighbors_parquet(root / "neighbors.parquet", neighbor_rows)
    inventory_bytes = canonical_json_bytes(
        {
            "blocks": block_store.inventory(),
            "schema_version": "skillcenter-graphrag-block-inventory/v1",
        }
    )
    _write_bytes(root / "blocks.json", inventory_bytes)

    files = {
        "assignments": _file_descriptor(
            root / "assignments.parquet",
            root=root,
            media_type="application/vnd.apache.parquet",
        ),
        "block_inventory": _file_descriptor(
            root / "blocks.json",
            root=root,
            media_type="application/json",
        ),
        "graph": _file_descriptor(
            root / "graph.json",
            root=root,
            media_type="application/vnd.intent-ir.corpus-graph+json",
        ),
        "metadata": _file_descriptor(
            root / "metadata.parquet",
            root=root,
            media_type="application/vnd.apache.parquet",
        ),
        "neighbors": _file_descriptor(
            root / "neighbors.parquet",
            root=root,
            media_type="application/vnd.apache.parquet",
        ),
        "vector_index": _file_descriptor(
            root / "index.faiss",
            root=root,
            media_type="application/vnd.faiss.index",
        ),
    }
    manifest = {
        "backend": "faiss-index-flat-ip",
        "build_identity_sha256": build_identity_sha256,
        "bm25_input": None if bm25_input is None else dict(bm25_input),
        "config": config.to_dict(),
        "config_sha256": config.digest,
        "dataset_id": str(embedding_manifests[0]["dataset_id"]),
        "dataset_revision": str(
            embedding_manifests[0]["dataset_revision"]
        ),
        "dimension": dimension,
        "embedded_skills": len(rows_by_skill),
        "embedding_device": str(
            embedding_manifests[0]["config"]["device"]
        ),
        "embedding_model": str(
            embedding_manifests[0]["config"]["model_name"]
        ),
        "embedding_provider": str(
            embedding_manifests[0]["config"]["provider"]
        ),
        "files": files,
        "graph": {
            "edge_count": len(graph.edges),
            "graph_cid": graph.graph_cid,
            "graph_digest": graph.graph_digest,
            "node_count": len(graph.nodes),
            "ontology_version": graph.ontology_version,
            "schema_version": graph.schema_version,
        },
        "inputs": list(inputs),
        "neighbor_edges": len(neighbor_rows),
        "neighbor_backend": neighbor_backend,
        "schema_version": SKILLCENTER_GRAPHRAG_INDEX_SCHEMA_VERSION,
        "source_records": len(records),
        "vector_count": len(metadata_rows),
    }
    _write_bytes(root / "manifest.json", canonical_json_bytes(manifest))
    return manifest


def _validate_embedding_manifest_set(
    manifests: Sequence[Mapping[str, Any]],
) -> None:
    if not manifests:
        raise SkillCenterGraphRAGError(
            "at least one embedding corpus is required"
        )
    scalar_fields = (
        "dataset_id",
        "dataset_revision",
        "dimension",
        "config_sha256",
    )
    for field in scalar_fields:
        if len({str(manifest[field]) for manifest in manifests}) != 1:
            raise SkillCenterGraphRAGError(
                f"embedding corpora disagree on {field}"
            )
    if int(manifests[0]["dimension"]) < 1:
        raise SkillCenterGraphRAGError(
            "embedding corpora must have a positive dimension"
        )
    repository_files = [
        str(manifest["repository_file"]) for manifest in manifests
    ]
    if len(set(repository_files)) != len(repository_files):
        raise SkillCenterGraphRAGError(
            "embedding corpora repeat a repository file"
        )


def _validate_bm25_input(
    index: SkillCenterBM25Index,
    *,
    embedding_manifests: Sequence[Mapping[str, Any]],
) -> None:
    if (
        index.manifest.get("dataset_id")
        != embedding_manifests[0]["dataset_id"]
        or index.manifest.get("dataset_revision")
        != embedding_manifests[0]["dataset_revision"]
    ):
        raise SkillCenterGraphRAGError(
            "BM25 index does not match the embedding dataset revision"
        )
    expected_inputs = {
        (
            str(manifest["repository_file"]),
            str(manifest["bundle_sha256"]),
            int(manifest["source_records_total"]),
        )
        for manifest in embedding_manifests
    }
    actual_inputs = {
        (
            str(item.get("repository_file", "")),
            str(item.get("bundle_sha256", "")),
            int(item.get("source_records", -1)),
        )
        for item in index.manifest.get("inputs", ())
        if isinstance(item, Mapping)
    }
    if actual_inputs != expected_inputs:
        raise SkillCenterGraphRAGError(
            "BM25 source bundles do not match embedding source bundles"
        )


def _bm25_skill_neighbors(
    index: SkillCenterBM25Index,
    *,
    k: int,
) -> tuple[
    dict[str, tuple[CorpusNeighborObservation, ...]],
    dict[tuple[str, str], float],
]:
    pair_evidence: dict[
        tuple[str, str], tuple[float, tuple[str, ...], str]
    ] = {}
    for source_skill_id, hits in index.all_skill_neighbors(
        k=k,
        max_matched_terms=32,
    ).items():
        for hit in hits:
            pair = tuple(sorted((source_skill_id, hit.skill_id)))
            candidate = (
                float(hit.score),
                tuple(hit.matched_terms),
                source_skill_id,
            )
            existing = pair_evidence.get(pair)
            if existing is None or (
                -candidate[0],
                candidate[1],
                candidate[2],
            ) < (
                -existing[0],
                existing[1],
                existing[2],
            ):
                pair_evidence[pair] = candidate
    observations: dict[str, list[CorpusNeighborObservation]] = defaultdict(
        list
    )
    scores: dict[tuple[str, str], float] = {}
    for (left_skill_id, right_skill_id), (
        score,
        matched_terms,
        _source_skill_id,
    ) in sorted(pair_evidence.items()):
        observations[left_skill_id].append(
            CorpusNeighborObservation(
                right_skill_id,
                score=score,
                retrieval_method="bm25-okapi",
                matched_terms=matched_terms,
            )
        )
        scores[(left_skill_id, right_skill_id)] = score
    return (
        {
            skill_id: tuple(values)
            for skill_id, values in observations.items()
        },
        scores,
    )


def _nearest_skill_neighbors(
    skill_ids: Sequence[str],
    vectors: Any,
    *,
    k: int,
) -> tuple[dict[str, tuple[str, ...]], dict[tuple[str, str], float]]:
    _, np = _faiss_numpy()
    if len(skill_ids) < 2:
        return {skill_id: () for skill_id in skill_ids}, {}
    similarities = np.matmul(vectors, vectors.T)
    count = len(skill_ids)
    bounded_k = min(k, count - 1)
    neighbors: dict[str, tuple[str, ...]] = {}
    pairs: dict[tuple[str, str], float] = {}
    for index, skill_id in enumerate(skill_ids):
        ranked = sorted(
            (candidate for candidate in range(count) if candidate != index),
            key=lambda candidate: (
                -float(similarities[index, candidate]),
                skill_ids[candidate],
            ),
        )[:bounded_k]
        neighbors[skill_id] = tuple(skill_ids[item] for item in ranked)
        for candidate in ranked:
            pair = tuple(sorted((skill_id, skill_ids[candidate])))
            pairs[pair] = max(
                pairs.get(pair, -math.inf),
                float(similarities[index, candidate]),
            )
    return neighbors, pairs


def _source_family(record: SkillCenterSkillRecord) -> str:
    material = (
        record.primary_source_id
        or record.source_id
        or record.source_url
        or record.skill_id
    )
    digest = hashlib.sha256(
        f"{record.source_type}\0{material}".encode("utf-8")
    ).hexdigest()
    return f"skillcenter-family:sha256:{digest}"


def _partition(
    source_family: str,
    config: SkillCenterGraphRAGConfig,
) -> str:
    bucket = int.from_bytes(
        hashlib.sha256(
            f"{config.partition_salt}\0{source_family}".encode("utf-8")
        ).digest()[:8],
        "big",
    ) % 100
    if bucket < config.training_percent:
        return "training"
    if bucket < config.training_percent + config.validation_percent:
        return "validation"
    return "evaluation"


def _prepare_filters(
    filters: Mapping[str, str | Sequence[str]] | None,
) -> dict[str, frozenset[str]]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise TypeError("filters must be a mapping")
    unknown = set(filters) - _FILTER_FIELDS
    if unknown:
        raise SkillCenterGraphRAGError(
            f"unsupported search filter(s): {', '.join(sorted(unknown))}"
        )
    prepared = {}
    for key, value in filters.items():
        values = (value,) if isinstance(value, str) else tuple(value)
        normalized = frozenset(str(item) for item in values if str(item))
        if not normalized:
            raise SkillCenterGraphRAGError(
                f"search filter {key!r} must not be empty"
            )
        prepared[key] = normalized
    return prepared


def _matches_filters(
    row: Mapping[str, Any],
    filters: Mapping[str, frozenset[str]],
) -> bool:
    return all(str(row.get(key, "")) in values for key, values in filters.items())


def _graph_from_payload(payload: object) -> IntentCorpusGraph:
    if not isinstance(payload, Mapping):
        raise SkillCenterGraphRAGError("graph payload must be an object")
    nodes = tuple(
        CorpusGraphNode(
            node_id=str(item["id"]),
            node_type=item["node_type"],
            source_digest=str(item["source_digest"]),
            graph_digest=str(item["graph_digest"]),
            properties=item.get("properties", {}),
            ontology_version=str(item["ontology_version"]),
        )
        for item in payload["nodes"]
    )
    edges = tuple(
        CorpusGraphEdge(
            edge_id=str(item["id"]),
            edge_type=item["edge_type"],
            source=str(item["source"]),
            target=str(item["target"]),
            source_digest=str(item["source_digest"]),
            graph_digest=str(item["graph_digest"]),
            properties=item.get("properties", {}),
            ontology_version=str(item["ontology_version"]),
        )
        for item in payload["edges"]
    )
    source_bodies = tuple(
        AddressedArtifact(**dict(item)) for item in payload["source_bodies"]
    )
    embeddings = tuple(
        AddressedArtifact(**dict(item)) for item in payload["embeddings"]
    )
    return IntentCorpusGraph(
        nodes=nodes,
        edges=edges,
        graph_digest=str(payload["graph_digest"]),
        source_digests=tuple(str(item) for item in payload["source_digests"]),
        source_bodies=source_bodies,
        embeddings=embeddings,
        graph_cid=str(payload["graph_cid"]),
        schema_version=str(payload["schema_version"]),
        ontology_version=str(payload["ontology_version"]),
    )


def _validate_loaded_rows(
    manifest: Mapping[str, Any],
    graph: IntentCorpusGraph,
    metadata_rows: Sequence[Mapping[str, Any]],
    assignment_rows: Sequence[Mapping[str, Any]],
    neighbor_rows: Sequence[Mapping[str, Any]],
) -> None:
    neighbor_backend = str(
        manifest.get("neighbor_backend") or "embedding-cosine"
    )
    if neighbor_backend not in {"embedding-cosine", "bm25-okapi"}:
        raise SkillCenterGraphRAGError(
            "GraphRAG neighbor_backend is unsupported"
        )
    skill_nodes = {
        node.node_id: str(node.properties["skill_id"])
        for node in graph.nodes
        if node.node_type is CorpusNodeType.SKILL
    }
    if len(skill_nodes) != int(manifest["source_records"]):
        raise SkillCenterGraphRAGError(
            "graph skill count does not match source_records"
        )
    if [int(row.get("row_index", -1)) for row in metadata_rows] != list(
        range(len(metadata_rows))
    ):
        raise SkillCenterGraphRAGError(
            "vector metadata row indexes are not contiguous"
        )
    chunk_ids = [str(row.get("chunk_id", "")) for row in metadata_rows]
    if any(not item for item in chunk_ids) or len(set(chunk_ids)) != len(chunk_ids):
        raise SkillCenterGraphRAGError(
            "vector metadata chunk IDs must be non-empty and unique"
        )
    for row in metadata_rows:
        node_id = str(row.get("graph_node_id", ""))
        if (
            node_id not in skill_nodes
            or skill_nodes[node_id] != str(row.get("skill_id", ""))
            or row.get("graph_digest") != graph.graph_digest
            or row.get("schema_version")
            != SKILLCENTER_GRAPHRAG_METADATA_SCHEMA_VERSION
        ):
            raise SkillCenterGraphRAGError(
                "vector metadata has a stale graph binding"
            )
    assignment_node_ids = [
        str(row.get("graph_node_id", "")) for row in assignment_rows
    ]
    if (
        set(assignment_node_ids) != set(skill_nodes)
        or len(set(assignment_node_ids)) != len(assignment_node_ids)
    ):
        raise SkillCenterGraphRAGError(
            "partition assignments do not cover graph skills exactly once"
        )
    for row in assignment_rows:
        if (
            row.get("schema_version")
            != SKILLCENTER_GRAPHRAG_ASSIGNMENT_SCHEMA_VERSION
            or str(row.get("partition", ""))
            not in {"training", "validation", "evaluation"}
            or not str(row.get("source_family", ""))
        ):
            raise SkillCenterGraphRAGError(
                "partition assignment is malformed"
            )
    edge_by_id = {
        edge.edge_id: edge
        for edge in graph.edges
        if edge.edge_type is CorpusEdgeType.NEIGHBOR_OF
    }
    if set(edge_by_id) != {
        str(row.get("edge_id", "")) for row in neighbor_rows
    }:
        raise SkillCenterGraphRAGError(
            "neighbor table does not cover graph neighbor edges"
        )
    for row in neighbor_rows:
        edge = edge_by_id[str(row["edge_id"])]
        endpoints = {edge.source, edge.target}
        if (
            endpoints
            != {
                str(row.get("source_node_id", "")),
                str(row.get("target_node_id", "")),
            }
            or row.get("graph_digest") != graph.graph_digest
            or row.get("schema_version")
            != SKILLCENTER_GRAPHRAG_NEIGHBOR_SCHEMA_VERSION
            or not math.isfinite(float(row.get("score", math.nan)))
        ):
            raise SkillCenterGraphRAGError(
                "neighbor table has a stale or malformed graph binding"
            )
        if neighbor_backend == "bm25-okapi" and (
            edge.properties.get("retrieval_method") != "bm25-okapi"
            or not math.isclose(
                float(edge.properties.get("score", math.nan)),
                float(row["score"]),
                rel_tol=1e-5,
                abs_tol=1e-5,
            )
            or not edge.properties.get("matched_terms")
        ):
            raise SkillCenterGraphRAGError(
                "BM25 neighbor edge lacks lexical evidence"
            )


def _verify_block_inventory(
    root: Path,
    inventory_path: Path,
    graph: IntentCorpusGraph,
) -> None:
    try:
        payload = json.loads(inventory_path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillCenterGraphRAGError(
            "block inventory is malformed"
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version")
        != "skillcenter-graphrag-block-inventory/v1"
        or not isinstance(payload.get("blocks"), list)
    ):
        raise SkillCenterGraphRAGError(
            "unsupported block inventory"
        )
    declared: set[str] = set()
    for entry in payload["blocks"]:
        if not isinstance(entry, Mapping):
            raise SkillCenterGraphRAGError(
                "block inventory entry must be an object"
            )
        path = _safe_relative_file(root, str(entry.get("relative_path", "")))
        expected_sha = str(entry.get("sha256", ""))
        expected_cid = str(entry.get("cid", ""))
        if (
            path.stat().st_size != int(entry.get("size_bytes", -1))
            or _file_sha256(path) != expected_sha
            or cid_v1(path.read_bytes()) != expected_cid
        ):
            raise SkillCenterGraphRAGError(
                "content-addressed block failed integrity verification"
            )
        declared.add(expected_cid)
    required = {
        graph.graph_cid,
        *(
            item.cid
            for item in graph.source_bodies
            if item.stored
        ),
        *(item.cid for item in graph.embeddings if item.stored),
    }
    if not required <= declared:
        raise SkillCenterGraphRAGError(
            "block inventory omits a stored graph artifact"
        )


def _write_metadata_parquet(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    pa, parquet = _pyarrow()
    fields = []
    sample = dict(rows[0])
    for key in sorted(sample):
        if key == "finding_codes":
            fields.append((key, pa.list_(pa.string())))
        elif key in {
            "chunk_count",
            "chunk_index",
            "embedding_dimension",
            "text_chars",
        }:
            fields.append((key, pa.int32()))
        elif key in {
            "row_index",
            "source_end_char",
            "source_start_char",
        }:
            fields.append((key, pa.int64()))
        elif key in {"embedding_norm", "overall_score"}:
            fields.append((key, pa.float64()))
        else:
            fields.append((key, pa.string()))
    schema = pa.schema(fields)
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _write_assignments_parquet(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("adversarial", pa.bool_()),
            ("allowed_use", pa.string()),
            ("graph_node_id", pa.string()),
            ("partition", pa.string()),
            ("repository_file", pa.string()),
            ("schema_version", pa.string()),
            ("skill_id", pa.string()),
            ("source_family", pa.string()),
            ("source_ref_id", pa.string()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _write_neighbors_parquet(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    pa, parquet = _pyarrow()
    schema = pa.schema(
        [
            ("edge_id", pa.string()),
            ("graph_digest", pa.string()),
            ("schema_version", pa.string()),
            ("score", pa.float32()),
            ("source_node_id", pa.string()),
            ("source_skill_id", pa.string()),
            ("target_node_id", pa.string()),
            ("target_skill_id", pa.string()),
        ]
    )
    parquet.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        path,
        compression="zstd",
    )


def _file_descriptor(
    path: Path,
    *,
    root: Path,
    media_type: str,
) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "cid": cid_v1(payload),
        "media_type": media_type,
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _verify_file_descriptor(
    root: Path,
    value: object,
) -> Path:
    if not isinstance(value, Mapping):
        raise SkillCenterGraphRAGError(
            "GraphRAG file descriptor must be an object"
        )
    path = _safe_relative_file(root, str(value.get("relative_path", "")))
    payload = path.read_bytes()
    if (
        len(payload) != int(value.get("size_bytes", -1))
        or hashlib.sha256(payload).hexdigest()
        != str(value.get("sha256", ""))
        or cid_v1(payload) != str(value.get("cid", ""))
        or not str(value.get("media_type", ""))
    ):
        raise SkillCenterGraphRAGError(
            "GraphRAG file descriptor failed verification"
        )
    return path


def _safe_relative_file(root: Path, relative_path: str) -> Path:
    try:
        relative = PurePosixPath(relative_path)
    except (TypeError, ValueError) as exc:
        raise SkillCenterGraphRAGError(
            "artifact path is invalid"
        ) from exc
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != relative_path
    ):
        raise SkillCenterGraphRAGError(
            "artifact path must be normalized and relative"
        )
    path = root.joinpath(*relative.parts)
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root)
    ):
        raise SkillCenterGraphRAGError(
            "artifact path is missing, unsafe, or not a regular file"
        )
    return path


def _summary_from_manifest(
    root: Path,
    manifest: Mapping[str, Any],
) -> SkillCenterGraphRAGBuildSummary:
    graph = manifest["graph"]
    return SkillCenterGraphRAGBuildSummary(
        output_dir=str(root),
        dataset_revision=str(manifest["dataset_revision"]),
        model_name=str(manifest["embedding_model"]),
        dimension=int(manifest["dimension"]),
        source_records=int(manifest["source_records"]),
        embedded_skills=int(manifest["embedded_skills"]),
        vector_count=int(manifest["vector_count"]),
        graph_nodes=int(graph["node_count"]),
        graph_edges=int(graph["edge_count"]),
        neighbor_edges=int(manifest["neighbor_edges"]),
        neighbor_backend=str(
            manifest.get("neighbor_backend") or "embedding-cosine"
        ),
        graph_digest=str(graph["graph_digest"]),
        graph_cid=str(graph["graph_cid"]),
        manifest_sha256=_file_sha256(root / "manifest.json"),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise SkillCenterGraphRAGError(
            "pyarrow is required to build a SkillCenter GraphRAG index"
        ) from exc
    return pa, parquet


def _faiss_numpy() -> tuple[Any, Any]:
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise SkillCenterGraphRAGError(
            "faiss-cpu and numpy are required for SkillCenter GraphRAG"
        ) from exc
    return faiss, np


@contextmanager
def _build_lock(output: Path) -> Iterator[None]:
    lock_path = output.parent / f".{output.name}.graphrag.lock"
    if lock_path.is_symlink() or (
        lock_path.exists() and not lock_path.is_file()
    ):
        raise SkillCenterGraphRAGError("GraphRAG build lock is invalid")
    with lock_path.open("a+b") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SkillCenterGraphRAGError(
                "another GraphRAG build owns this output directory"
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


__all__ = [
    "DEFAULT_EVALUATION_PERCENT",
    "DEFAULT_NEIGHBOR_K",
    "DEFAULT_PARTITION_SALT",
    "DEFAULT_TRAINING_PERCENT",
    "DEFAULT_VALIDATION_PERCENT",
    "DirectoryContentAddressedStore",
    "SKILLCENTER_GRAPHRAG_ASSIGNMENT_SCHEMA_VERSION",
    "SKILLCENTER_GRAPHRAG_INDEX_SCHEMA_VERSION",
    "SKILLCENTER_GRAPHRAG_METADATA_SCHEMA_VERSION",
    "SKILLCENTER_GRAPHRAG_NEIGHBOR_SCHEMA_VERSION",
    "SkillCenterGraphRAGBuildSummary",
    "SkillCenterGraphRAGConfig",
    "SkillCenterGraphRAGError",
    "SkillCenterGraphRAGIndex",
    "SkillCenterGraphRAGSearchHit",
    "build_skillcenter_graphrag_index",
]
