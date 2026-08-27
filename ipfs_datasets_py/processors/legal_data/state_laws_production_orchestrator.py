"""Local, restartable composition of the production state-law artifacts.

This module owns no corpus transformation or retrieval algorithm.  It only
orders the existing production writers, binds their checkpoints to one build
identity, verifies completed descriptors, and asks the existing local-release
assembler to close the exact-51 manifest.

The orchestrator has no network, Hub, upload, or publication operation.  The
pinned tokenizer is opened with ``local_files_only=True`` and the real
GTE-small embedding writer runs with the common offline environment asserted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_TOKEN_COUNTER_ID,
    OpenUsLawEmbeddingConfig,
    build_pinned_model_token_counter,
    default_embedding_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    StateLawsBm25Config,
    default_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunk_physical import (
    StateLawsChunkPhysicalLayout,
    write_state_laws_chunk_physical_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    StateLawsStreamingCorpusPhysicalLayout,
    write_state_laws_corpus_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    SCHEMA_VERSION as EMBEDDING_STORE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    EmbeddingStoreResult,
    build_state_laws_embedding_store,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_physical import (
    write_state_laws_streaming_graph_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_streaming_projection import (
    StateLawsStreamingGraphProjectionStage,
    project_state_laws_streaming_graph_from_corpus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    MANIFEST_PATH,
    LocalStateLawsReleaseManifest,
    assemble_state_laws_local_release_manifest,
    state_laws_source_provenance_verifier_attestation,
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    SourceReceiptRecord,
    canonical_json_dumps,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vector_physical import (
    write_state_laws_vector_physical_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_write_canonical_json,
    confine_path,
    file_digest,
    resolve_release_root,
    verify_descriptor,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
)

SCHEMA_VERSION: Final = "state-laws-production-orchestrator/v1"
CHECKPOINT_SCHEMA_VERSION: Final = "state-laws-production-orchestrator-checkpoint/v1"
DEFAULT_CHECKPOINT_PATH: Final = "checkpoints/state_laws_production_orchestrator.json"
DEFAULT_WORK_DIR: Final = "checkpoints/state_laws_production_orchestrator"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False
LOCAL_ONLY: Final = True

STAGE_ORDER: Final = (
    "corpus",
    "canonical_chunks",
    "gte_small_embeddings",
    "streaming_bm25",
    "centroid_vectors",
    "streaming_graph",
    "exact_51_manifest",
)
_CHECKPOINT_STAGE_NAMES: Final = frozenset((*STAGE_ORDER, "graph_projection"))

_OFFLINE_ENVIRONMENT: Final = {
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}

_VECTOR_OPTION_NAMES: Final = frozenset(
    {
        "kmeans_iterations",
        "locator_page_size",
        "max_centroids",
        "max_rows_per_centroid",
        "max_rows_per_shard",
        "max_shards_per_centroid",
        "max_sort_records_in_memory",
        "max_training_rows",
        "seed",
        "target_rows_per_centroid",
    }
)


class StateLawsProductionOrchestratorError(ValueError):
    """Base failure for local production composition."""


class StateLawsProductionInputDriftError(StateLawsProductionOrchestratorError):
    """A restart checkpoint does not bind the active immutable inputs."""


class StateLawsProductionArtifactDriftError(StateLawsProductionOrchestratorError):
    """A completed local stage no longer matches its recorded bytes."""


class StateLawsProductionGateError(StateLawsProductionOrchestratorError):
    """A composed stage cannot satisfy the production release gates."""


@dataclass(frozen=True, slots=True)
class StateLawsProductionBuildResult:
    """Compact outcome of one local production build or verified resume."""

    output_root: str
    checkpoint_path: str
    build_digest: str
    release: LocalStateLawsReleaseManifest
    resumed_complete_release: bool
    stage_order: tuple[str, ...]
    stage_receipts: Mapping[str, Mapping[str, Any]]
    local_only: bool = True
    authorizes_publication: bool = False
    authorizes_hub_upload: bool = False
    network_io_performed: bool = False
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_hub_upload": self.authorizes_hub_upload,
            "authorizes_publication": self.authorizes_publication,
            "build_digest": self.build_digest,
            "checkpoint_path": self.checkpoint_path,
            "local_only": self.local_only,
            "network_io_performed": self.network_io_performed,
            "output_root": self.output_root,
            "release": self.release.to_dict(),
            "resumed_complete_release": self.resumed_complete_release,
            "schema_version": self.schema_version,
            "stage_order": list(self.stage_order),
            "stage_receipts": {
                name: dict(value) for name, value in self.stage_receipts.items()
            },
        }


@contextmanager
def _local_model_only_environment() -> Iterator[None]:
    """Assert common model-library offline controls and restore the caller."""

    prior = {name: os.environ.get(name) for name in _OFFLINE_ENVIRONMENT}
    os.environ.update(_OFFLINE_ENVIRONMENT)
    try:
        yield
    finally:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _stage_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body["stage_digest"] = content_sha256(canonical_json_dumps(body))
    return body


def _verify_stage_record(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StateLawsProductionArtifactDriftError(
            f"checkpoint stage {name!r} is missing or malformed"
        )
    payload = dict(value)
    observed = str(payload.pop("stage_digest", ""))
    expected = content_sha256(canonical_json_dumps(payload))
    if observed != expected:
        raise StateLawsProductionArtifactDriftError(
            f"checkpoint stage {name!r} digest drifted"
        )
    payload["stage_digest"] = observed
    return payload


def _descriptor(value: Any, *, label: str) -> ArtifactDescriptor:
    if not isinstance(value, Mapping):
        raise StateLawsProductionArtifactDriftError(
            f"{label} descriptor is malformed"
        )
    try:
        return ArtifactDescriptor.from_mapping(value)
    except Exception as exc:
        raise StateLawsProductionArtifactDriftError(
            f"{label} descriptor cannot be reconstructed"
        ) from exc


def _source_receipts_digest(
    source_receipts: Sequence[SourceReceiptRecord],
) -> str:
    """Digest normalized receipt lineage in the release's canonical order."""

    by_code = {item.jurisdiction: item for item in source_receipts}
    if set(by_code) != set(CANONICAL_JURISDICTIONS):
        raise StateLawsProductionGateError(
            "source receipt lineage does not cover the exact-51 jurisdiction set"
        )
    return digest_mapping(
        {
            "source_receipts": [
                by_code[code].to_dict() for code in CANONICAL_JURISDICTION_ORDER
            ]
        }
    )


def _observed_corpus_input_digest(
    layout: StateLawsStreamingCorpusPhysicalLayout,
    *,
    source_receipts_digest: str,
) -> str:
    """Read the byte digest emitted by the existing canonical sorter."""

    document_order = layout.sort_receipts.get("document_order")
    if not isinstance(document_order, Mapping):
        raise StateLawsProductionArtifactDriftError(
            "corpus lacks its canonical input-byte sort receipt"
        )
    observed_input_digest = str(document_order.get("output_digest") or "")
    if (
        len(observed_input_digest) != 64
        or int(document_order.get("row_count") or -1) != layout.row_count
        or int(document_order.get("records_consumed") or -1) != layout.row_count
    ):
        raise StateLawsProductionArtifactDriftError(
            "corpus canonical input-byte sort receipt is malformed"
        )
    observed_receipts_digest = _source_receipts_digest(layout.source_receipts)
    if observed_receipts_digest != source_receipts_digest:
        raise StateLawsProductionInputDriftError(
            "canonical corpus receipt lineage differs from the active exact-51 receipts"
        )
    return observed_input_digest


def _verify_corpus_input_lineage(
    layout: StateLawsStreamingCorpusPhysicalLayout,
    *,
    source_input_digest: str,
    source_receipts_digest: str,
) -> None:
    """Bind caller identity to bytes emitted by the existing canonical sorter."""

    observed_input_digest = _observed_corpus_input_digest(
        layout,
        source_receipts_digest=source_receipts_digest,
    )
    if observed_input_digest != source_input_digest:
        raise StateLawsProductionInputDriftError(
            "source_input_digest does not match the canonical admitted input bytes"
        )


def _corpus_checkpoint_record(
    layout: StateLawsStreamingCorpusPhysicalLayout,
    *,
    source_input_digest: str,
    source_receipts_digest: str,
) -> dict[str, Any]:
    return _stage_record(
        {
            "canonical_input_digest": source_input_digest,
            "corpus_index_descriptor": layout.corpus_index_descriptor.to_dict(),
            "data_descriptors": [item.to_dict() for item in layout.data_descriptors],
            "receipt_descriptors": [
                item.to_dict() for item in layout.receipt_descriptors
            ],
            "route_rows": [dict(item) for item in layout.route_rows],
            "row_count": layout.row_count,
            "sort_receipts": {
                name: dict(value) for name, value in layout.sort_receipts.items()
            },
            "source_receipts": [
                item.to_dict() for item in layout.source_receipts
            ],
            "source_receipts_digest": source_receipts_digest,
            "status": "complete",
        }
    )


def _restore_corpus_layout(
    record: Any,
    *,
    root: Path,
    source_input_digest: str,
    source_receipts_digest: str,
) -> StateLawsStreamingCorpusPhysicalLayout:
    payload = _verify_stage_record(record, name="corpus")
    if (
        payload.get("canonical_input_digest") != source_input_digest
        or payload.get("source_receipts_digest") != source_receipts_digest
    ):
        raise StateLawsProductionInputDriftError(
            "corpus checkpoint is not bound to the active canonical input and receipts"
        )
    try:
        layout = StateLawsStreamingCorpusPhysicalLayout(
            output_dir=str(root),
            source_receipts=tuple(
                SourceReceiptRecord.from_mapping(item)
                for item in payload["source_receipts"]
            ),
            data_descriptors=tuple(
                _descriptor(item, label="corpus data")
                for item in payload["data_descriptors"]
            ),
            receipt_descriptors=tuple(
                _descriptor(item, label="corpus receipt")
                for item in payload["receipt_descriptors"]
            ),
            corpus_index_descriptor=_descriptor(
                payload["corpus_index_descriptor"], label="corpus index"
            ),
            route_rows=tuple(dict(item) for item in payload["route_rows"]),
            row_count=int(payload["row_count"]),
            sort_receipts={
                str(name): dict(value)
                for name, value in payload["sort_receipts"].items()
            },
        )
    except StateLawsProductionArtifactDriftError:
        raise
    except Exception as exc:
        raise StateLawsProductionArtifactDriftError(
            "corpus checkpoint cannot reconstruct its typed layout"
        ) from exc
    for descriptor in layout.descriptors:
        verify_descriptor(root, descriptor)
    if layout.production_ready is not True:
        raise StateLawsProductionGateError("restored corpus is not production ready")
    _verify_corpus_input_lineage(
        layout,
        source_input_digest=source_input_digest,
        source_receipts_digest=source_receipts_digest,
    )
    return layout


def _chunk_checkpoint_record(
    layout: StateLawsChunkPhysicalLayout,
    *,
    parent_corpus_stage_digest: str,
) -> dict[str, Any]:
    return _stage_record(
        {
            "chunk_count": layout.chunk_count,
            "config": dict(layout.config),
            "corpus_index_descriptor": layout.corpus_index_descriptor.to_dict(),
            "data_descriptors": [item.to_dict() for item in layout.data_descriptors],
            "model_token_validation_passed": layout.model_token_validation_passed,
            "parent_corpus_stage_digest": parent_corpus_stage_digest,
            "parent_corpus_digest": layout.parent_corpus_digest,
            "parent_document_count": layout.parent_document_count,
            "route_rows": [dict(item) for item in layout.route_rows],
            "sort_receipts": {
                name: dict(value) for name, value in layout.sort_receipts.items()
            },
            "status": "complete",
        }
    )


def _restore_chunk_layout(
    record: Any,
    *,
    root: Path,
    parent_corpus_stage_digest: str,
) -> StateLawsChunkPhysicalLayout:
    payload = _verify_stage_record(record, name="canonical_chunks")
    if payload.get("parent_corpus_stage_digest") != parent_corpus_stage_digest:
        raise StateLawsProductionInputDriftError(
            "canonical chunk checkpoint is not bound to the active corpus stage"
        )
    try:
        layout = StateLawsChunkPhysicalLayout(
            output_dir=str(root),
            parent_corpus_digest=str(payload["parent_corpus_digest"]),
            data_descriptors=tuple(
                _descriptor(item, label="canonical chunk data")
                for item in payload["data_descriptors"]
            ),
            corpus_index_descriptor=_descriptor(
                payload["corpus_index_descriptor"], label="canonical chunk index"
            ),
            route_rows=tuple(dict(item) for item in payload["route_rows"]),
            parent_document_count=int(payload["parent_document_count"]),
            chunk_count=int(payload["chunk_count"]),
            config=dict(payload["config"]),
            sort_receipts={
                str(name): dict(value)
                for name, value in payload["sort_receipts"].items()
            },
            model_token_validation_passed=bool(
                payload["model_token_validation_passed"]
            ),
        )
    except StateLawsProductionArtifactDriftError:
        raise
    except Exception as exc:
        raise StateLawsProductionArtifactDriftError(
            "canonical chunk checkpoint cannot reconstruct its typed layout"
        ) from exc
    for descriptor in layout.descriptors:
        verify_descriptor(root, descriptor)
    if layout.production_ready is not True:
        raise StateLawsProductionGateError(
            "restored canonical chunks are not production ready"
        )
    return layout


def _projection_checkpoint_record(
    stage: StateLawsStreamingGraphProjectionStage,
    *,
    root: Path,
    parent_corpus_stage_digest: str,
) -> dict[str, Any]:
    database = Path(stage.database_path).resolve()
    try:
        relative = database.relative_to(root).as_posix()
    except ValueError as exc:
        raise StateLawsProductionOrchestratorError(
            "graph projection database must remain below the local output root"
        ) from exc
    return _stage_record(
        {
            "corpus_fingerprint": stage.corpus_fingerprint,
            "corpus_row_count": stage.corpus_row_count,
            "database_relative_path": relative,
            "database_sha256": stage.database_sha256,
            "database_size_bytes": stage.database_size_bytes,
            "duplicate_edge_count": stage.duplicate_edge_count,
            "edge_count": stage.edge_count,
            "max_parent_rows_per_batch": stage.max_parent_rows_per_batch,
            "max_projected_edges_per_parent": stage.max_projected_edges_per_parent,
            "node_count": stage.node_count,
            "parent_corpus_stage_digest": parent_corpus_stage_digest,
            "status": "complete",
        }
    )


def _restore_projection_stage(
    record: Any,
    *,
    root: Path,
    parent_corpus_stage_digest: str,
) -> StateLawsStreamingGraphProjectionStage:
    payload = _verify_stage_record(record, name="graph_projection")
    if payload.get("parent_corpus_stage_digest") != parent_corpus_stage_digest:
        raise StateLawsProductionInputDriftError(
            "graph projection checkpoint is not bound to the active corpus stage"
        )
    path = confine_path(root, str(payload["database_relative_path"]))
    stage = StateLawsStreamingGraphProjectionStage(
        database_path=str(path),
        database_size_bytes=int(payload["database_size_bytes"]),
        database_sha256=str(payload["database_sha256"]),
        corpus_fingerprint=str(payload["corpus_fingerprint"]),
        corpus_row_count=int(payload["corpus_row_count"]),
        node_count=int(payload["node_count"]),
        edge_count=int(payload["edge_count"]),
        duplicate_edge_count=int(payload["duplicate_edge_count"]),
        max_parent_rows_per_batch=int(payload["max_parent_rows_per_batch"]),
        max_projected_edges_per_parent=int(
            payload["max_projected_edges_per_parent"]
        ),
    )
    stage.verify()
    if stage.production_ready is not True:
        raise StateLawsProductionGateError(
            "restored graph projection is not production ready"
        )
    return stage


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise StateLawsProductionArtifactDriftError(
            "orchestrator checkpoint must be a regular file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsProductionArtifactDriftError(
            "orchestrator checkpoint is invalid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsProductionArtifactDriftError(
            "orchestrator checkpoint must be an object"
        )
    return dict(payload)


def _checkpoint_payload(
    *,
    build_digest: str,
    build_contract: Mapping[str, Any],
    stages: Mapping[str, Mapping[str, Any]],
    status: str,
    final: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "build_contract": dict(build_contract),
        "build_digest": build_digest,
        "local_only": True,
        "network_io_performed": False,
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "stages": {name: dict(value) for name, value in stages.items()},
        "status": status,
    }
    if final is not None:
        payload["final"] = dict(final)
    return payload


def _checkpoint_has_legacy_embedding_surface(
    checkpoint: Mapping[str, Any],
) -> bool:
    checkpoint_stages = checkpoint.get("stages")
    checkpoint_contract = checkpoint.get("build_contract")
    if "embeddings_router" in checkpoint or (
        isinstance(checkpoint_stages, Mapping)
        and "embeddings_router" in checkpoint_stages
    ):
        return True
    if "embedding_model" in checkpoint and not str(
        checkpoint.get("embedding_model") or ""
    ).strip():
        return True
    if isinstance(checkpoint_contract, Mapping):
        legacy_embedding_config = checkpoint_contract.get("embedding_config")
        if (
            isinstance(legacy_embedding_config, Mapping)
            and "model_id" in legacy_embedding_config
            and not str(legacy_embedding_config.get("model_id") or "").strip()
        ):
            return True
    return False


def _checkpoint_source_input_digest(checkpoint: Mapping[str, Any]) -> str:
    """Recover a derived digest only from this orchestrator's local schema."""

    if _checkpoint_has_legacy_embedding_surface(checkpoint):
        raise StateLawsProductionInputDriftError(
            "legacy embeddings_router or blank-model artifacts are not resumable"
        )
    contract = checkpoint.get("build_contract")
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("local_only") is not True
        or checkpoint.get("network_io_performed") is not False
        or checkpoint.get("authorizes_publication") is not False
        or checkpoint.get("authorizes_hub_upload") is not False
        or not isinstance(contract, Mapping)
    ):
        raise StateLawsProductionInputDriftError(
            "only a current local production checkpoint can supply source_input_digest"
        )
    return normalize_sha256(
        contract.get("source_input_digest"),
        name="checkpoint source_input_digest",
    )


def _assert_checkpoint_identity(
    checkpoint: Mapping[str, Any],
    *,
    build_digest: str,
    build_contract: Mapping[str, Any],
) -> None:
    if _checkpoint_has_legacy_embedding_surface(checkpoint):
        raise StateLawsProductionInputDriftError(
            "legacy embeddings_router or blank-model artifacts are not resumable"
        )
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("build_digest") != build_digest
        or canonical_json_dumps(checkpoint.get("build_contract"))
        != canonical_json_dumps(build_contract)
        or checkpoint.get("status") not in {"building", "complete"}
        or checkpoint.get("local_only") is not True
        or checkpoint.get("network_io_performed") is not False
        or checkpoint.get("authorizes_publication") is not False
        or checkpoint.get("authorizes_hub_upload") is not False
        or not isinstance(checkpoint.get("stages"), Mapping)
    ):
        raise StateLawsProductionInputDriftError(
            "orchestrator checkpoint does not match the active local build"
        )


def _assert_checkpoint_stage_bindings(
    stages: Mapping[str, Mapping[str, Any]],
    *,
    build_contract: Mapping[str, Any],
) -> None:
    """Reject stage reuse unless every predecessor and production pin closes."""

    corpus = stages.get("corpus")
    if corpus is not None:
        sort_receipts = corpus.get("sort_receipts")
        document_order = (
            sort_receipts.get("document_order")
            if isinstance(sort_receipts, Mapping)
            else None
        )
        try:
            checkpoint_receipts = tuple(
                SourceReceiptRecord.from_mapping(item)
                for item in corpus.get("source_receipts", ())
            )
            checkpoint_receipts_digest = _source_receipts_digest(
                checkpoint_receipts
            )
        except Exception as exc:
            raise StateLawsProductionInputDriftError(
                "corpus stage receipt lineage is malformed"
            ) from exc
        if (
            not isinstance(document_order, Mapping)
            or corpus.get("canonical_input_digest")
            != build_contract.get("source_input_digest")
            or document_order.get("output_digest")
            != build_contract.get("source_input_digest")
            or corpus.get("source_receipts_digest")
            != build_contract.get("source_receipts_digest")
            or checkpoint_receipts_digest
            != build_contract.get("source_receipts_digest")
        ):
            raise StateLawsProductionInputDriftError(
                "corpus stage is not bound to the active input/receipt lineage"
            )

    chunks = stages.get("canonical_chunks")
    chunk_index_sha256 = ""
    if chunks is not None:
        descriptor = chunks.get("corpus_index_descriptor")
        config = chunks.get("config")
        if isinstance(descriptor, Mapping):
            chunk_index_sha256 = str(descriptor.get("sha256") or "")
        if (
            corpus is None
            or chunks.get("parent_corpus_stage_digest")
            != corpus.get("stage_digest")
            or len(chunk_index_sha256) != 64
            or not isinstance(config, Mapping)
            or config.get("model_token_counter_id") != PINNED_TOKEN_COUNTER_ID
            or config.get("model_token_limit") != PINNED_MAX_TOKENS
        ):
            raise StateLawsProductionInputDriftError(
                "canonical chunk stage is not bound to the active corpus/model pin"
            )

    embedding_stage = stages.get("gte_small_embeddings")
    if embedding_stage is not None and (
        chunks is None
        or embedding_stage.get("parent_chunk_stage_digest")
        != chunks.get("stage_digest")
        or embedding_stage.get("canonical_chunk_artifact_digest")
        != chunk_index_sha256
        or embedding_stage.get("config_digest")
        != build_contract.get("embedding_config_digest")
        or embedding_stage.get("model_id") != PINNED_MODEL_ID
        or embedding_stage.get("model_revision") != PINNED_MODEL_REVISION
        or embedding_stage.get("dimension") != PINNED_DIMENSION
        or embedding_stage.get("jurisdictions")
        != list(CANONICAL_JURISDICTION_ORDER)
    ):
        raise StateLawsProductionInputDriftError(
            "embedding stage is not current-schema pinned GTE-small output"
        )

    bm25_stage = stages.get("streaming_bm25")
    if bm25_stage is not None and (
        chunks is None
        or bm25_stage.get("parent_chunk_stage_digest")
        != chunks.get("stage_digest")
        or bm25_stage.get("canonical_chunk_artifact_digest")
        != chunk_index_sha256
        or bm25_stage.get("bm25_config_digest")
        != build_contract.get("bm25_config_digest")
    ):
        raise StateLawsProductionInputDriftError(
            "BM25 stage is not bound to the active canonical chunks/config"
        )

    vector_stage = stages.get("centroid_vectors")
    if vector_stage is not None and (
        embedding_stage is None
        or vector_stage.get("parent_embedding_stage_digest")
        != embedding_stage.get("stage_digest")
        or vector_stage.get("canonical_chunk_artifact_digest")
        != chunk_index_sha256
        or vector_stage.get("model_id") != PINNED_MODEL_ID
        or vector_stage.get("model_revision") != PINNED_MODEL_REVISION
        or vector_stage.get("dimension") != PINNED_DIMENSION
    ):
        raise StateLawsProductionInputDriftError(
            "centroid vector stage is not bound to current pinned embeddings"
        )

    projection_stage = stages.get("graph_projection")
    if projection_stage is not None and (
        corpus is None
        or projection_stage.get("parent_corpus_stage_digest")
        != corpus.get("stage_digest")
    ):
        raise StateLawsProductionInputDriftError(
            "graph projection is not bound to the active corpus stage"
        )

    graph_stage = stages.get("streaming_graph")
    if graph_stage is not None and (
        projection_stage is None
        or bm25_stage is None
        or graph_stage.get("parent_projection_stage_digest")
        != projection_stage.get("stage_digest")
        or graph_stage.get("parent_bm25_stage_digest")
        != bm25_stage.get("stage_digest")
        or graph_stage.get("vocabulary_sha256")
        != bm25_stage.get("vocabulary_sha256")
    ):
        raise StateLawsProductionInputDriftError(
            "streaming graph is not bound to the active BM25 vocabulary/projection"
        )

    manifest_stage = stages.get("exact_51_manifest")
    if manifest_stage is not None and (
        graph_stage is None
        or vector_stage is None
        or manifest_stage.get("parent_graph_stage_digest")
        != graph_stage.get("stage_digest")
        or manifest_stage.get("parent_vector_stage_digest")
        != vector_stage.get("stage_digest")
    ):
        raise StateLawsProductionInputDriftError(
            "release manifest stage is not bound to graph/vector predecessors"
        )


def _verify_complete_release(
    *,
    root: Path,
    final: Any,
) -> LocalStateLawsReleaseManifest:
    if not isinstance(final, Mapping):
        raise StateLawsProductionArtifactDriftError(
            "completed orchestrator checkpoint lacks its final receipt"
        )
    if (
        final.get("authorizes_publication") is not False
        or final.get("authorizes_hub_upload") is not False
        or final.get("network_io_performed") is not False
    ):
        raise StateLawsProductionGateError(
            "completed orchestrator receipt is not local-only"
        )
    relative = str(final.get("manifest_relative_path") or "")
    if relative != MANIFEST_PATH:
        raise StateLawsProductionArtifactDriftError(
            "completed release points at a noncanonical manifest path"
        )
    path = confine_path(root, relative)
    if path.is_symlink() or not path.is_file():
        raise StateLawsProductionArtifactDriftError(
            "completed local release manifest is missing or unsafe"
        )
    size, digest = file_digest(path)
    if (
        size != int(final.get("manifest_size_bytes") or -1)
        or digest.hex() != final.get("manifest_file_sha256")
    ):
        raise StateLawsProductionArtifactDriftError(
            "completed local release manifest bytes drifted"
        )
    try:
        release = verify_state_laws_local_release_manifest(root)
    except Exception as exc:
        raise StateLawsProductionGateError(
            f"completed manifest failed shared local-release verification: {exc}"
        ) from exc
    if release.manifest_digest != final.get("manifest_digest"):
        raise StateLawsProductionArtifactDriftError(
            "completed local release manifest digest drifted"
        )
    return release


def _validate_source_receipt_set(
    source_receipts: Sequence[SourceReceiptRecord],
) -> tuple[SourceReceiptRecord, ...]:
    if isinstance(source_receipts, (str, bytes, bytearray)):
        raise StateLawsProductionGateError(
            "source_receipts must be normalized SourceReceiptRecord values"
        )
    receipts = tuple(source_receipts)
    if len(receipts) != EXPECTED_JURISDICTION_COUNT or any(
        not isinstance(item, SourceReceiptRecord) for item in receipts
    ):
        raise StateLawsProductionGateError(
            "production orchestration requires exactly 51 normalized source receipts"
        )
    by_code = {item.jurisdiction: item for item in receipts}
    if len(by_code) != EXPECTED_JURISDICTION_COUNT or set(by_code) != set(
        CANONICAL_JURISDICTIONS
    ):
        raise StateLawsProductionGateError(
            "source receipts must cover exactly the 50 states plus DC"
        )
    return tuple(by_code[code] for code in CANONICAL_JURISDICTION_ORDER)


def _embedding_stage_receipt(
    results: Sequence[EmbeddingStoreResult],
    *,
    root: Path,
    config: OpenUsLawEmbeddingConfig,
    canonical_chunk_artifact_digest: str,
    parent_chunk_stage_digest: str,
) -> dict[str, Any]:
    rows = []
    for result in results:
        checkpoint = Path(result.checkpoint_path)
        size, digest = file_digest(checkpoint)
        try:
            relative = checkpoint.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise StateLawsProductionOrchestratorError(
                "embedding checkpoint must remain below the local output root"
            ) from exc
        checkpoint_payload = _load_checkpoint(checkpoint)
        if (
            result.schema_version != EMBEDDING_STORE_SCHEMA_VERSION
            or canonical_json_dumps(result.config)
            != canonical_json_dumps(config.to_dict())
            or checkpoint_payload.get("schema_version")
            != EMBEDDING_STORE_SCHEMA_VERSION
            or checkpoint_payload.get("config_digest") != config.digest
            or checkpoint_payload.get("jurisdiction_code")
            != result.jurisdiction_code
            or checkpoint_payload.get("production_ready") is not True
            or canonical_json_dumps(checkpoint_payload.get("config"))
            != canonical_json_dumps(config.to_dict())
        ):
            raise StateLawsProductionInputDriftError(
                f"{result.jurisdiction_code} embedding checkpoint is legacy, "
                "blank-model, or not bound to the active GTE-small pin"
            )
        rows.append(
            {
                "checkpoint_relative_path": relative,
                "checkpoint_sha256": digest.hex(),
                "checkpoint_size_bytes": size,
                "jurisdiction_code": result.jurisdiction_code,
                "part_count": result.part_count,
                "row_count": result.row_count,
            }
        )
    return _stage_record(
        {
            "canonical_chunk_artifact_digest": canonical_chunk_artifact_digest,
            "config_digest": config.digest,
            "dimension": config.dimension,
            "jurisdiction_count": len(rows),
            "jurisdictions": [item["jurisdiction_code"] for item in rows],
            "model_id": config.model_id,
            "model_revision": config.model_revision,
            "parent_chunk_stage_digest": parent_chunk_stage_digest,
            "row_count": sum(int(item["row_count"]) for item in rows),
            "states": rows,
            "status": "complete",
        }
    )


def _compact_stage_receipt(
    *,
    status: str = "complete",
    **values: Any,
) -> dict[str, Any]:
    return _stage_record({"status": status, **values})


def build_state_laws_production_release(
    events_or_records: Iterable[Any] | None,
    *,
    source_receipts: Sequence[SourceReceiptRecord],
    rights_receipt: Mapping[str, Any],
    source_input_digest: str | None = None,
    source_revision: str,
    release_point: str,
    output_root: str | Path,
    embedding_config: OpenUsLawEmbeddingConfig | None = None,
    bm25_config: StateLawsBm25Config | None = None,
    graph_config: StreamingGraphConfig | None = None,
    vector_options: Mapping[str, Any] | None = None,
    corpus_max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    corpus_max_records_in_memory: int = 4096,
    chunk_max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    chunk_max_records_in_memory: int = 4096,
    embedding_rows_per_part: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    embedding_max_sort_records_in_memory: int = 4096,
    graph_max_parent_rows_per_batch: int = 64,
    checkpoint_path: str | Path | None = None,
    resume: bool = True,
) -> StateLawsProductionBuildResult:
    """Compose all production physical stages into one exact-51 local release.

    On a first build, ``source_input_digest=None`` derives the identity from
    the corpus writer's shared canonical ``document_order`` sort receipt.  No
    reusable orchestrator checkpoint is written until those bytes close.  A
    restart may also omit it; only a current local orchestrator checkpoint may
    supply the already-observed digest.
    """

    if not isinstance(resume, bool):
        raise StateLawsProductionOrchestratorError("resume must be a boolean")
    root = resolve_release_root(output_root, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = (
        Path(checkpoint_path).expanduser().resolve()
        if checkpoint_path is not None
        else confine_path(root, DEFAULT_CHECKPOINT_PATH)
    )
    if checkpoint.is_symlink():
        raise StateLawsProductionOrchestratorError(
            "orchestrator checkpoint must not be a symlink"
        )
    try:
        checkpoint.relative_to(root)
    except ValueError as exc:
        raise StateLawsProductionOrchestratorError(
            "orchestrator checkpoint must remain below output_root"
        ) from exc

    receipts = _validate_source_receipt_set(source_receipts)
    prior = _load_checkpoint(checkpoint)
    source_digest = (
        _checkpoint_source_input_digest(prior)
        if source_input_digest is None and prior
        else (
            None
            if source_input_digest is None
            else normalize_sha256(
                source_input_digest,
                name="source_input_digest",
            )
        )
    )
    revision = require_immutable_revision(source_revision, name="source_revision")
    exact_release_point = str(release_point or "").strip()
    if not exact_release_point or exact_release_point.lower() in {
        "head",
        "latest",
        "main",
        "master",
    }:
        raise StateLawsProductionOrchestratorError(
            "release_point must be exact and immutable"
        )
    if not isinstance(rights_receipt, Mapping):
        raise StateLawsProductionGateError("rights_receipt must be a mapping")

    embeddings = embedding_config or default_embedding_config()
    bm25_selected = bm25_config or default_bm25_config()
    graph_selected = graph_config or StreamingGraphConfig(overwrite=True)
    if not isinstance(embeddings, OpenUsLawEmbeddingConfig):
        raise StateLawsProductionGateError(
            "embedding_config must be the pinned OpenUsLawEmbeddingConfig"
        )
    if (
        embeddings.may_authorize_release is not True
        or embeddings.model_id != PINNED_MODEL_ID
        or embeddings.model_revision != PINNED_MODEL_REVISION
        or embeddings.dimension != PINNED_DIMENSION
        or embeddings.max_tokens != PINNED_MAX_TOKENS
    ):
        raise StateLawsProductionGateError(
            "production orchestration requires the sealed real GTE-small pin"
        )
    if not isinstance(bm25_selected, StateLawsBm25Config):
        raise StateLawsProductionGateError(
            "bm25_config must be a StateLawsBm25Config"
        )
    if not isinstance(graph_selected, StreamingGraphConfig):
        raise StateLawsProductionGateError(
            "graph_config must be a StreamingGraphConfig"
        )
    if graph_selected.overwrite is not True:
        raise StateLawsProductionGateError(
            "restartable graph composition requires atomic overwrite=True"
        )
    raw_vector_options = dict(vector_options or {})
    unexpected_vector_options = sorted(
        set(raw_vector_options).difference(_VECTOR_OPTION_NAMES)
    )
    if unexpected_vector_options:
        raise StateLawsProductionOrchestratorError(
            f"unsupported vector options: {unexpected_vector_options}"
        )

    receipt_digest = _source_receipts_digest(receipts)
    rights_digest = digest_mapping(dict(rights_receipt))
    source_provenance_verifier = (
        state_laws_source_provenance_verifier_attestation()
    )
    prebuilt_corpus: StateLawsStreamingCorpusPhysicalLayout | None = None
    if source_digest is None:
        if events_or_records is None:
            raise StateLawsProductionOrchestratorError(
                "events_or_records is required to derive first-build source_input_digest"
            )
        prebuilt_corpus = write_state_laws_corpus_physical_layout_from_iterable(
            events_or_records,
            source_receipts=receipts,
            output_dir=root,
            max_rows_per_shard=corpus_max_rows_per_shard,
            max_records_in_memory=corpus_max_records_in_memory,
        )
        if prebuilt_corpus.production_ready is not True:
            raise StateLawsProductionGateError("corpus stage is not production ready")
        source_digest = _observed_corpus_input_digest(
            prebuilt_corpus,
            source_receipts_digest=receipt_digest,
        )
    assert source_digest is not None
    build_contract = {
        "bm25_config": bm25_selected.to_dict(),
        "bm25_config_digest": bm25_selected.digest,
        "bounds": {
            "chunk_max_records_in_memory": chunk_max_records_in_memory,
            "chunk_max_rows_per_shard": chunk_max_rows_per_shard,
            "corpus_max_records_in_memory": corpus_max_records_in_memory,
            "corpus_max_rows_per_shard": corpus_max_rows_per_shard,
            "embedding_max_sort_records_in_memory": (
                embedding_max_sort_records_in_memory
            ),
            "embedding_rows_per_part": embedding_rows_per_part,
            "graph_max_parent_rows_per_batch": graph_max_parent_rows_per_batch,
        },
        "embedding_config": embeddings.to_dict(),
        "embedding_config_digest": embeddings.digest,
        "graph_config": graph_selected.to_dict(),
        "release_point": exact_release_point,
        "rights_receipt_digest": rights_digest,
        "source_input_digest": source_digest,
        "source_provenance_verifier": source_provenance_verifier,
        "source_receipts_digest": receipt_digest,
        "source_revision": revision,
        "stage_order": list(STAGE_ORDER),
        "vector_options": raw_vector_options,
    }
    build_digest = content_sha256(canonical_json_dumps(build_contract))
    if prior:
        if not resume:
            raise StateLawsProductionInputDriftError(
                "an orchestrator checkpoint already exists and resume=False"
            )
        _assert_checkpoint_identity(
            prior,
            build_digest=build_digest,
            build_contract=build_contract,
        )
    stages = {
        str(name): dict(value)
        for name, value in dict(prior.get("stages") or {}).items()
    }
    unexpected_stages = sorted(set(stages).difference(_CHECKPOINT_STAGE_NAMES))
    if unexpected_stages:
        raise StateLawsProductionArtifactDriftError(
            f"orchestrator checkpoint has unknown stages: {unexpected_stages}"
        )
    for name, value in stages.items():
        _verify_stage_record(value, name=name)
    for position, name in enumerate(STAGE_ORDER):
        if name in stages:
            missing_predecessors = [
                predecessor
                for predecessor in STAGE_ORDER[:position]
                if predecessor not in stages
            ]
            if missing_predecessors:
                raise StateLawsProductionArtifactDriftError(
                    f"checkpoint stage {name!r} lacks predecessors "
                    f"{missing_predecessors}"
                )
    if "graph_projection" in stages and not {
        "corpus",
        "streaming_bm25",
        "centroid_vectors",
    }.issubset(stages):
        raise StateLawsProductionArtifactDriftError(
            "graph projection checkpoint lacks its corpus/BM25/vector predecessors"
        )
    _assert_checkpoint_stage_bindings(stages, build_contract=build_contract)

    if prior.get("status") == "complete":
        missing_complete_stages = sorted(_CHECKPOINT_STAGE_NAMES.difference(stages))
        final_receipt = prior.get("final")
        if missing_complete_stages:
            raise StateLawsProductionArtifactDriftError(
                "completed orchestrator checkpoint lacks stages "
                f"{missing_complete_stages}"
            )
        if (
            not isinstance(final_receipt, Mapping)
            or final_receipt.get("manifest_digest")
            != stages["exact_51_manifest"].get("manifest_digest")
            or final_receipt.get("manifest_relative_path")
            != stages["exact_51_manifest"].get("manifest_relative_path")
        ):
            raise StateLawsProductionArtifactDriftError(
                "completed manifest receipt is not bound to its final stage"
            )
        release = _verify_complete_release(root=root, final=final_receipt)
        return StateLawsProductionBuildResult(
            output_root=str(root),
            checkpoint_path=str(checkpoint),
            build_digest=build_digest,
            release=release,
            resumed_complete_release=True,
            stage_order=STAGE_ORDER,
            stage_receipts=stages,
        )

    def save_checkpoint(
        *, status: str = "building", final: Mapping[str, Any] | None = None
    ) -> None:
        _assert_checkpoint_stage_bindings(stages, build_contract=build_contract)
        atomic_write_canonical_json(
            checkpoint,
            _checkpoint_payload(
                build_digest=build_digest,
                build_contract=build_contract,
                stages=stages,
                status=status,
                final=final,
            ),
        )

    if "corpus" in stages:
        corpus = _restore_corpus_layout(
            stages["corpus"],
            root=root,
            source_input_digest=source_digest,
            source_receipts_digest=receipt_digest,
        )
    else:
        if prebuilt_corpus is not None:
            corpus = prebuilt_corpus
        else:
            if events_or_records is None:
                raise StateLawsProductionOrchestratorError(
                    "events_or_records is required until the corpus stage is checkpointed"
                )
            corpus = write_state_laws_corpus_physical_layout_from_iterable(
                events_or_records,
                source_receipts=receipts,
                output_dir=root,
                max_rows_per_shard=corpus_max_rows_per_shard,
                max_records_in_memory=corpus_max_records_in_memory,
            )
        if corpus.production_ready is not True:
            raise StateLawsProductionGateError("corpus stage is not production ready")
        _verify_corpus_input_lineage(
            corpus,
            source_input_digest=source_digest,
            source_receipts_digest=receipt_digest,
        )
        stages["corpus"] = _corpus_checkpoint_record(
            corpus,
            source_input_digest=source_digest,
            source_receipts_digest=receipt_digest,
        )
        save_checkpoint()
    corpus_receipt_codes = tuple(item.jurisdiction for item in corpus.source_receipts)
    if (
        len(corpus_receipt_codes) != EXPECTED_JURISDICTION_COUNT
        or set(corpus_receipt_codes) != set(CANONICAL_JURISDICTIONS)
    ):
        raise StateLawsProductionGateError(
            "corpus source receipts do not preserve the exact-51 jurisdiction set"
        )

    if "canonical_chunks" in stages:
        chunks = _restore_chunk_layout(
            stages["canonical_chunks"],
            root=root,
            parent_corpus_stage_digest=str(stages["corpus"]["stage_digest"]),
        )
    else:
        with _local_model_only_environment():
            model_token_counter, counter_id = build_pinned_model_token_counter(
                embeddings,
                local_files_only=True,
            )
        chunks = write_state_laws_chunk_physical_layout(
            corpus,
            model_token_limit=embeddings.max_tokens,
            output_dir=root,
            model_token_counter=model_token_counter,
            model_token_counter_id=counter_id,
            max_rows_per_shard=chunk_max_rows_per_shard,
            max_records_in_memory=chunk_max_records_in_memory,
        )
        if chunks.production_ready is not True:
            raise StateLawsProductionGateError(
                "canonical chunk stage is not production ready"
            )
        stages["canonical_chunks"] = _chunk_checkpoint_record(
            chunks,
            parent_corpus_stage_digest=str(stages["corpus"]["stage_digest"]),
        )
        save_checkpoint()
    if chunks.parent_document_count != corpus.row_count:
        raise StateLawsProductionGateError(
            "canonical chunk parent count differs from corpus"
        )

    embedding_root = confine_path(root, f"{DEFAULT_WORK_DIR}/embedding_store")
    embedding_results: list[EmbeddingStoreResult] = []
    input_parts: list[Path] = []
    with _local_model_only_environment():
        for code in CANONICAL_JURISDICTION_ORDER:
            result = build_state_laws_embedding_store(
                chunks.iter_jurisdiction_chunks(code),
                embedding_root,
                jurisdiction_code=code,
                config=embeddings,
                rows_per_part=embedding_rows_per_part,
                max_sort_records_in_memory=embedding_max_sort_records_in_memory,
                resume=resume,
            )
            if result.production_ready is not True:
                raise StateLawsProductionGateError(
                    f"{code} embedding store lacks real pinned inference evidence"
                )
            embedding_results.append(result)
            for descriptor in result.descriptors:
                relative = str(descriptor.get("relative_path") or "")
                input_parts.append(confine_path(embedding_root, relative))
    if (
        len(embedding_results) != EXPECTED_JURISDICTION_COUNT
        or sum(item.row_count for item in embedding_results) != chunks.chunk_count
    ):
        raise StateLawsProductionGateError(
            "embedding stores do not conserve exact-51 canonical chunks"
        )
    stages["gte_small_embeddings"] = _embedding_stage_receipt(
        embedding_results,
        root=root,
        config=embeddings,
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        parent_chunk_stage_digest=str(stages["canonical_chunks"]["stage_digest"]),
    )
    save_checkpoint()

    bm25_checkpoint = confine_path(root, f"{DEFAULT_WORK_DIR}/bm25")
    bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        chunks.iter_chunks(),
        root,
        config=bm25_selected,
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        checkpoint_dir=bm25_checkpoint,
        resume=resume,
    )
    if (
        bm25.production_ready is not True
        or bm25.counts.get("bm25_documents") != chunks.chunk_count
        or bm25.canonical_chunk_artifact_digest
        != chunks.corpus_index_descriptor.sha256
    ):
        raise StateLawsProductionGateError(
            "streaming BM25 is not exactly bound to canonical chunks"
        )
    stages["streaming_bm25"] = _compact_stage_receipt(
        bm25_config_digest=bm25_selected.digest,
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        document_count=bm25.counts["bm25_documents"],
        index_root_cid=bm25.layout.index_root_cid,
        parent_chunk_stage_digest=str(stages["canonical_chunks"]["stage_digest"]),
        vocabulary_sha256=bm25.layout.vocabulary_sha256,
    )
    save_checkpoint()

    vectors = write_state_laws_vector_physical_layout(
        input_parts,
        root,
        resume=resume,
        **raw_vector_options,
    )
    if (
        vectors.production_ready is not True
        or vectors.jurisdiction_count != EXPECTED_JURISDICTION_COUNT
        or vectors.row_count != chunks.chunk_count
        or vectors.model.get("model_id") != PINNED_MODEL_ID
        or vectors.model.get("model_revision") != PINNED_MODEL_REVISION
        or vectors.model.get("dimension") != PINNED_DIMENSION
    ):
        raise StateLawsProductionGateError(
            "centroid vector layout does not close the pinned exact-51 model space"
        )
    stages["centroid_vectors"] = _compact_stage_receipt(
        build_digest=vectors.build_digest,
        canonical_chunk_artifact_digest=chunks.corpus_index_descriptor.sha256,
        cluster_count=vectors.cluster_count,
        dimension=PINNED_DIMENSION,
        jurisdiction_count=vectors.jurisdiction_count,
        model_id=PINNED_MODEL_ID,
        model_revision=PINNED_MODEL_REVISION,
        parent_embedding_stage_digest=str(
            stages["gte_small_embeddings"]["stage_digest"]
        ),
        row_count=vectors.row_count,
        shard_count=vectors.shard_count,
    )
    save_checkpoint()

    projection_record = stages.get("graph_projection")
    if projection_record is not None:
        projection = _restore_projection_stage(
            projection_record,
            root=root,
            parent_corpus_stage_digest=str(stages["corpus"]["stage_digest"]),
        )
    else:
        projection_dir = confine_path(root, f"{DEFAULT_WORK_DIR}/graph_projection")
        if projection_dir.exists():
            raise StateLawsProductionArtifactDriftError(
                "uncheckpointed graph projection work tree already exists"
            )
        projection = project_state_laws_streaming_graph_from_corpus(
            corpus,
            projection_dir,
            max_parent_rows_per_batch=graph_max_parent_rows_per_batch,
        )
        if projection.production_ready is not True:
            raise StateLawsProductionGateError(
                "streaming graph projection is not production ready"
            )
        stages["graph_projection"] = _projection_checkpoint_record(
            projection,
            root=root,
            parent_corpus_stage_digest=str(stages["corpus"]["stage_digest"]),
        )
        save_checkpoint()

    graph = write_state_laws_streaming_graph_layout(
        projection.iter_nodes(),
        projection.iter_edges(),
        root,
        bm25=bm25,
        config=graph_selected,
    )
    if graph.production_ready is not True:
        raise StateLawsProductionGateError(
            "streaming graph lacks exact physical BM25 vocabulary parity"
        )
    vocabulary = graph.vocabulary_parity
    if (
        vocabulary.vocabulary_sha256 != bm25.layout.vocabulary_sha256
        or vocabulary.bm25_config_digest != bm25_selected.digest
        or vocabulary.document_count != bm25.counts["bm25_documents"]
    ):
        raise StateLawsProductionGateError(
            "streaming graph vocabulary proof drifted from physical BM25"
        )
    stages["streaming_graph"] = _compact_stage_receipt(
        edge_count=graph.counts["edges"],
        node_count=graph.counts["nodes"],
        parent_bm25_stage_digest=str(stages["streaming_bm25"]["stage_digest"]),
        parent_projection_stage_digest=str(
            stages["graph_projection"]["stage_digest"]
        ),
        vocabulary_sha256=vocabulary.vocabulary_sha256,
    )
    save_checkpoint()

    release = assemble_state_laws_local_release_manifest(
        root,
        corpus=corpus,
        chunks=chunks,
        bm25=bm25,
        vectors=vectors,
        graph=graph,
        rights_receipt=rights_receipt,
        source_provenance_verifier=source_provenance_verifier,
        source_revision=revision,
        release_point=exact_release_point,
    )
    stages["exact_51_manifest"] = _compact_stage_receipt(
        manifest_digest=release.manifest_digest,
        manifest_relative_path=release.relative_path,
        parent_graph_stage_digest=str(stages["streaming_graph"]["stage_digest"]),
        parent_vector_stage_digest=str(stages["centroid_vectors"]["stage_digest"]),
    )
    manifest_size, manifest_file_digest = file_digest(release.path)
    final = {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "manifest_digest": release.manifest_digest,
        "manifest_file_sha256": manifest_file_digest.hex(),
        "manifest_relative_path": release.relative_path,
        "manifest_size_bytes": manifest_size,
        "network_io_performed": False,
    }
    # Reopen every descriptor and all release gates before sealing the
    # orchestrator checkpoint; this is also the exact fast-resume verifier.
    verified_release = _verify_complete_release(root=root, final=final)
    save_checkpoint(status="complete", final=final)
    return StateLawsProductionBuildResult(
        output_root=str(root),
        checkpoint_path=str(checkpoint),
        build_digest=build_digest,
        release=verified_release,
        resumed_complete_release=False,
        stage_order=STAGE_ORDER,
        stage_receipts=stages,
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_CHECKPOINT_PATH",
    "DEFAULT_WORK_DIR",
    "LOCAL_ONLY",
    "PERFORMS_NETWORK_IO",
    "SCHEMA_VERSION",
    "STAGE_ORDER",
    "StateLawsProductionArtifactDriftError",
    "StateLawsProductionBuildResult",
    "StateLawsProductionGateError",
    "StateLawsProductionInputDriftError",
    "StateLawsProductionOrchestratorError",
    "build_state_laws_production_release",
]
