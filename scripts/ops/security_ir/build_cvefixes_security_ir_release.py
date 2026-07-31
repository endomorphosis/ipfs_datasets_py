#!/usr/bin/env python3
"""Build the complete Publicus CVEfixes Security IR GraphRAG release.

This command is an offline/local materializer except for two explicit inputs:

* a pinned CVEfixes snapshot already present on disk; and
* the pinned SentenceTransformer model fetched by the CUDA worker.

The final staging directory follows the same remotely routable physical
families as ``Publicus/skillcenter-ir``: corpus, BM25, vectors, graph nodes,
graph edges, both adjacency directions, and all eight content-addressed meta
indexes.  CUDA is mandatory for embeddings and there is no CPU fallback.

Source code and unrestricted descriptions never enter the public corpus.  A
strict release policy admits a row before GraphRAG projection; rejected or
malformed rows are retained as digest-only tombstones so source coverage is
explicit rather than silently reduced.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Final

import numpy as np

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.classification import (
    materialize_classification,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.graph import (
    CVEfixesGraph,
    build_cvefixes_graph,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_bm25 import (
    build_cvefixes_bm25_hf_layout,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_corpus_layout import (
    CVEFIXES_HF_CORPUS_SCHEMA_VERSION,
    build_cvefixes_hf_corpus_layout,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_graph_layout import (
    GRAPH_HF_CONFIG_PATHS,
    build_cvefixes_hf_graph_layout,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_release import (
    DEFAULT_HF_DATASET_ID,
    HF_PARQUET_SCHEMA_VERSION,
    HF_RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_vector_layout import (
    build_cvefixes_hf_vector_layout,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
    ProjectionDiagnostic,
    ProjectionResult,
    ProjectorConfig,
    project_cvefixes_row,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.release_policy import (
    CVEfixesReleasePolicy,
    LicenseProvenance,
    LicenseReviewStatus,
    PUBLIC_RELEASE_PROFILE,
    RELEASE_POLICY_SHA256,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.retrieval import (
    EmbeddingAcceleratorPort,
    RetrievalAuthority,
    RetrievalConfig,
    RetrievalEntry,
    RetrievalIndex,
    build_retrieval_index,
    graph_entries,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    CanonicalDerivedRecord,
    EvaluationRecord,
    FormalView,
    PolicyCandidate,
    ReleaseManifest,
    SourceRecord,
    canonical_config_cid,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import (
    CVEFIXES_DATASET_ID,
    CVEFIXES_REVISION,
    CVEFIXES_ROW_COUNT,
    PINNED_CVEFIXES_SOURCE,
    adapt_cvefixes_row,
)


TARGET_DATASET_ID: Final = DEFAULT_HF_DATASET_ID
MODEL_ID: Final = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION: Final = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_DIMENSION: Final = 384
SENTENCE_TRANSFORMERS_VERSION: Final = "5.4.1"
CUDA_IMAGE: Final = "nvcr.io/nvidia/pytorch:25.11-py3"
CUDA_IMAGE_DIGEST: Final = (
    "sha256:417cbf33f87b5378849df37983552cd1f8bc8b62fe1ceabe004de816a55dff21"
)
BUILD_SCHEMA_VERSION: Final = "cvefixes-complete-hf-build/v1"
CORPUS_SCHEMA_VERSION: Final = "cvefixes-hf-corpus/v1"
META_SCHEMA_VERSION: Final = "cvefixes-hf-shard-meta/v1"
ORIGINAL_ROW_INDEX_SCHEMA_VERSION: Final = (
    "cvefixes-hf-original-row-index/v1"
)
ORIGINAL_MIRROR_PROFILE: Final = "cvefixes-byte-preserving-mirror/v1"
EMBEDDING_MODEL_CONFIG_VERSION: Final = "cvefixes-embedding-model-config/v1"
# ``dataset_infos.json`` is reserved by Hugging Face Datasets/Viewer.  Keep the
# content-addressed release binding in a separate, ordinary Hub artifact.
RELEASE_METADATA_FILENAME: Final = "release-metadata.json"
SOURCE_URI: Final = (
    f"hf://datasets/{CVEFIXES_DATASET_ID}@{CVEFIXES_REVISION}"
)
MAX_TEXT_CHARS: Final = 4_096
_CID_RE: Final = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")

PROJECTION_CONFIG: Final = ProjectorConfig(
    max_hunks=1,
    max_symbols_per_unit=1,
    max_semantic_facts=256,
    max_excerpt_chars=1,
    max_predicate_chars=1_024,
)
TOMBSTONE_CONFIG_CID: Final = canonical_config_cid(
    {
        "body_treatment": "digest_only",
        "retains_source_row_coverage": True,
        "schema_version": "cvefixes-rejection-tombstone-config/v1",
    },
    schema_version="cvefixes-rejection-tombstone-config/v1",
)
RETRIEVAL_CONFIG: Final = RetrievalConfig(
    max_shards=8,
    # The production index remains bounded by the 250k corpus contract, but
    # its default security scan must cover the complete release rather than a
    # hash-ordered prefix.
    max_nodes=250_000,
    max_results=25,
    max_hops=2,
    max_query_terms=64,
)

VIEWER_CONFIG_PATHS: Final[dict[str, str]] = {
    "bm25_documents": "data/bm25/documents/*.parquet",
    "bm25_keyword_index": "indexes/bm25_keyword_shards.parquet",
    "bm25_postings": "data/bm25/postings/*.parquet",
    "corpus": "data/corpus/*.parquet",
    "corpus_chunk_index": "indexes/corpus_chunks.parquet",
    "graph_edges": "data/graph/edges/*.parquet",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/*.parquet",
    "graph_incoming_adjacency_index": (
        "indexes/graph_incoming_adjacency.parquet"
    ),
    "graph_nodes": "data/graph/nodes/*.parquet",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/*.parquet",
    "graph_outgoing_adjacency_index": (
        "indexes/graph_outgoing_adjacency.parquet"
    ),
    "original_data": "data/original/*.parquet",
    "original_row_index": "indexes/original_rows.parquet",
    "vector_meta_index": "indexes/vector_chunks.parquet",
    "vectors": "data/vectors/*.parquet",
}
HIDDEN_INDEX_CONFIG_PATHS: Final[dict[str, str]] = {
    "bm25_document_chunk_index": "indexes/bm25_document_chunks.parquet",
    "graph_edge_chunk_index": "indexes/graph_edge_chunks.parquet",
    "graph_node_chunk_index": "indexes/graph_node_chunks.parquet",
}
ALL_CONFIG_PATHS: Final[dict[str, str]] = {
    **VIEWER_CONFIG_PATHS,
    **HIDDEN_INDEX_CONFIG_PATHS,
}

PATH_CONFIGS: Final[tuple[tuple[str, str], ...]] = (
    ("data/graph/adjacency/incoming/", "graph_incoming_adjacency"),
    ("data/graph/adjacency/outgoing/", "graph_outgoing_adjacency"),
    ("data/bm25/documents/", "bm25_documents"),
    ("data/bm25/postings/", "bm25_postings"),
    ("data/graph/edges/", "graph_edges"),
    ("data/graph/nodes/", "graph_nodes"),
    ("data/original/", "original_data"),
    ("data/corpus/", "corpus"),
    ("data/vectors/", "vectors"),
)
INDEX_CONFIGS: Final[dict[str, str]] = {
    "indexes/bm25_document_chunks.parquet": "bm25_document_chunk_index",
    "indexes/bm25_keyword_shards.parquet": "bm25_keyword_index",
    "indexes/corpus_chunks.parquet": "corpus_chunk_index",
    "indexes/graph_edge_chunks.parquet": "graph_edge_chunk_index",
    "indexes/graph_incoming_adjacency.parquet": (
        "graph_incoming_adjacency_index"
    ),
    "indexes/graph_node_chunks.parquet": "graph_node_chunk_index",
    "indexes/graph_outgoing_adjacency.parquet": (
        "graph_outgoing_adjacency_index"
    ),
    "indexes/original_rows.parquet": "original_row_index",
    "indexes/vector_chunks.parquet": "vector_meta_index",
}


class CompleteReleaseBuildError(RuntimeError):
    """Raised when complete release materialization cannot prove its output."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _log(event: str, **values: Any) -> None:
    sys.stdout.write(
        _canonical_json({"event": event, **values}).decode("ascii") + "\n"
    )
    sys.stdout.flush()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _raw_cid(content: bytes) -> str:
    return cid_v1_from_digest(hashlib.sha256(content).digest())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field_receipts(raw: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for name, value in sorted(raw.items()):
        try:
            encoded = canonical_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise CompleteReleaseBuildError(
                f"cannot digest rejected source field {name!r}"
            ) from exc
        receipts[name] = {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "utf8_bytes": len(encoded),
        }
    return receipts


def _tombstone_source(
    raw: Mapping[str, Any],
    *,
    row_index: int,
    stage: str,
    reason: str,
) -> SourceRecord:
    receipts = _field_receipts(raw)
    source_cid = canonical_identity(
        {
            "dataset_id": CVEFIXES_DATASET_ID,
            "field_receipts": receipts,
            "row_index": row_index,
            "source_revision": CVEFIXES_REVISION,
        },
        domain="cvefixes-security-ir/rejected-source-row",
        schema_version="cvefixes-rejected-source-row/v1",
    ).cid
    reason_text = f"{stage}:{reason}"[:1_024]
    return SourceRecord(
        source_cids=(source_cid,),
        parent_cids=(source_cid,),
        config_cid=TOMBSTONE_CONFIG_CID,
        source_uri=SOURCE_URI,
        source_revision=CVEFIXES_REVISION,
        row_key=f"row:{row_index:05d}:rejected",
        payload={
            "field_receipts": receipts,
            "grants_execution_authority": False,
            "reason": reason_text,
            "row_index": row_index,
            "stage": stage,
            "status": "rejected_tombstone",
        },
    )


def _valid_source_record(
    row: Any,
    projection: ProjectionResult,
    admission: Any,
) -> SourceRecord:
    return SourceRecord(
        source_cids=(projection.source_cid,),
        parent_cids=(projection.cid,),
        config_cid=projection.config_cid,
        source_uri=SOURCE_URI,
        source_revision=CVEFIXES_REVISION,
        row_key=f"{row.row_index:05d}:{row.cve_id}:{row.hash}",
        payload={
            **dict(admission.projected_record),
            "admission": {
                "admission_id": admission.admission_id,
                "admitted": True,
                "policy_sha256": admission.policy_sha256,
                "warning_codes": list(admission.warning_codes),
            },
            "grants_execution_authority": False,
            "projection": {
                "code_unit_count": len(projection.code_units),
                "diagnostic_count": len(projection.diagnostics),
                "pair_count": len(projection.pairs),
                "projection_cid": projection.cid,
                "semantic_fact_count": len(projection.semantic_facts),
            },
        },
    )


def _without_semantic_facts(projection: ProjectionResult) -> ProjectionResult:
    """Drop possible personal-data-derived predicates while retaining evidence."""

    return ProjectionResult(
        source_cid=projection.source_cid,
        config_cid=projection.config_cid,
        language=projection.language,
        code_units=projection.code_units,
        pairs=projection.pairs,
        semantic_facts=(),
        diagnostics=(
            *projection.diagnostics,
            ProjectionDiagnostic(
                code=projection.diagnostics[0].code
                if projection.diagnostics
                else _diagnostic_limit_code(),
                message=(
                    "semantic facts omitted from public graph because the "
                    "source row contained body-only personal data"
                ),
            ),
        ),
    )


def _diagnostic_limit_code() -> Any:
    # Imported lazily to keep the public helper above concise.
    from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
        DiagnosticCode,
    )

    return DiagnosticCode.LIMIT_EXCEEDED


def _bounded_text(parts: Sequence[str]) -> str:
    text = " ".join(item.strip() for item in parts if item and item.strip())
    text = text.replace("\x00", "\\x00")
    if not text:
        text = "CVEfixes Security IR non-authoritative evidence"
    return text[:MAX_TEXT_CHARS]


def _shard_key(record_cid: str) -> str:
    bucket = int(hashlib.sha256(record_cid.encode("ascii")).hexdigest()[:8], 16) % 8
    return f"train:{bucket:04d}"


def _record_entry(
    record: CanonicalDerivedRecord,
    *,
    kind: str,
    text: str,
    source_cids: Sequence[str] | None = None,
    cwes: Sequence[str] = (),
    languages: Sequence[str] = (),
    code_facts: Sequence[str] = (),
    actions: Sequence[str] = (),
    effects: Sequence[str] = (),
    policies: Sequence[str] = (),
) -> RetrievalEntry:
    authority = (
        RetrievalAuthority.CANDIDATE
        if isinstance(record, PolicyCandidate)
        else RetrievalAuthority.NON_AUTHORITATIVE
    )
    return RetrievalEntry(
        node_cid=record.cid,
        partition="train",
        # Co-shard canonical Security IR projections with graph entries so
        # the eight-shard retrieval ceiling covers both families.
        shard_key=_shard_key(record.cid),
        kind=kind,
        text=_bounded_text((text,)),
        source_cids=(
            tuple(source_cids)
            if source_cids is not None
            else record.source_cids
        ),
        authority=authority,
        cwes=tuple(sorted(set(cwes))),
        languages=tuple(sorted(set(languages))),
        code_facts=tuple(sorted(set(code_facts))),
        actions=tuple(sorted(set(actions))),
        effects=tuple(sorted(set(effects))),
        policies=tuple(sorted(set(policies))),
        graph_node=False,
    )


@dataclass(slots=True)
class Materialization:
    graph: CVEfixesGraph
    extra_entries: tuple[RetrievalEntry, ...]
    record_cids: tuple[str, ...]
    source_row_cids: tuple[str, ...]
    source_row_statuses: tuple[str, ...]
    evaluation: EvaluationRecord
    counts: dict[str, int]
    rejection_reasons: dict[str, int]
    source_verification: Mapping[str, Any]


def _materialize_source(source_root: Path) -> Materialization:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CompleteReleaseBuildError("pyarrow is required") from exc

    verification = PINNED_CVEFIXES_SOURCE.verify_local_shards(source_root)
    license_provenance = _license_provenance()
    policy = CVEfixesReleasePolicy()
    projections: list[ProjectionResult] = []
    records: list[CanonicalDerivedRecord] = []
    entries: list[RetrievalEntry] = []
    source_row_cids: list[str] = []
    source_row_statuses: list[str] = []
    counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    cwe_by_cve: dict[str, str] = {}
    row_index = 0
    start = time.monotonic()

    for shard in PINNED_CVEFIXES_SOURCE.shards:
        parquet = pq.ParquetFile(source_root / shard.path)
        for batch in parquet.iter_batches(batch_size=16):
            for raw in batch.to_pylist():
                if not isinstance(raw, Mapping):
                    raise CompleteReleaseBuildError(
                        f"source row {row_index} is not a mapping"
                    )
                try:
                    row = adapt_cvefixes_row(raw, row_index=row_index)
                except Exception as exc:
                    reason = f"{type(exc).__name__}:{exc}"
                    tombstone = _tombstone_source(
                        raw,
                        row_index=row_index,
                        stage="adaptation",
                        reason=reason,
                    )
                    records.append(tombstone)
                    source_row_cids.extend(tombstone.source_cids)
                    source_row_statuses.append("adaptation_rejected")
                    entries.append(
                        _record_entry(
                            tombstone,
                            kind="security_ir_source_tombstone",
                            text=(
                                f"source row {row_index} rejected at adaptation "
                                f"{type(exc).__name__}"
                            ),
                            policies=("release_rejected",),
                        )
                    )
                    rejection_reasons[reason] += 1
                    counts["rejected_rows"] += 1
                    row_index += 1
                    continue

                admission = policy.evaluate(
                    row.to_dict(),
                    license_provenance=license_provenance,
                    profile=PUBLIC_RELEASE_PROFILE,
                    expected_policy_sha256=RELEASE_POLICY_SHA256,
                )
                if not admission.admitted:
                    reason = ",".join(admission.reason_codes)
                    tombstone = _tombstone_source(
                        raw,
                        row_index=row_index,
                        stage="publication_admission",
                        reason=reason,
                    )
                    records.append(tombstone)
                    source_row_cids.extend(tombstone.source_cids)
                    source_row_statuses.append("publication_rejected")
                    entries.append(
                        _record_entry(
                            tombstone,
                            kind="security_ir_source_tombstone",
                            text=(
                                f"{row.cve_id} source row {row_index} rejected "
                                "by public release policy"
                            ),
                            cwes=(row.cwe_id,) if row.cwe_id else (),
                            languages=(row.language,) if row.language else (),
                            policies=("release_rejected",),
                        )
                    )
                    rejection_reasons[f"publication:{reason}"] += 1
                    counts["rejected_rows"] += 1
                    row_index += 1
                    continue

                projection = project_cvefixes_row(
                    row,
                    config=PROJECTION_CONFIG,
                )
                if "privacy.personal_data_body_omitted" in admission.warning_codes:
                    projection = _without_semantic_facts(projection)
                    counts["personal_data_fact_omissions"] += 1
                materialized = materialize_classification(row, projection)
                source_record = _valid_source_record(
                    row, projection, admission
                )
                projections.append(projection)
                records.extend(
                    (
                        source_record,
                        *projection.code_units,
                        materialized.candidate,
                        materialized.formal_view,
                    )
                )
                source_row_cids.append(projection.source_cid)
                source_row_statuses.append("admitted")
                if row.cwe_id and row.cwe_id.startswith("CWE-"):
                    cwe_by_cve.setdefault(row.cve_id, row.cwe_id)

                compact_source_text = _bounded_text(
                    (
                        row.cve_id,
                        row.cwe_id or "",
                        row.cwe_name or "",
                        row.severity or "",
                        row.language or "",
                        row.repo_url,
                        " ".join(row.security_keywords),
                    )
                )
                entries.extend(
                    (
                        _record_entry(
                            source_record,
                            kind="security_ir_source_record",
                            text=compact_source_text,
                            cwes=(row.cwe_id,) if row.cwe_id else (),
                            languages=(
                                (projection.language,)
                                if projection.language
                                else ()
                            ),
                        ),
                        _record_entry(
                            materialized.candidate,
                            kind="security_ir_policy_candidate",
                            text=_bounded_text(
                                (
                                    row.cve_id,
                                    row.cwe_id or "",
                                    "classification-only audit candidate",
                                    "exact forbidden action scope unresolved",
                                )
                            ),
                            cwes=(row.cwe_id,) if row.cwe_id else (),
                            languages=(
                                (projection.language,)
                                if projection.language
                                else ()
                            ),
                            policies=(
                                "classification_only",
                                "forbidden_constraints_unresolved",
                            ),
                        ),
                        _record_entry(
                            materialized.formal_view,
                            kind="security_ir_formal_view",
                            text=materialized.formal_view.expression,
                            cwes=(row.cwe_id,) if row.cwe_id else (),
                            policies=(
                                "formal_logic",
                                "forbidden_constraints_unresolved",
                            ),
                        ),
                    )
                )
                counts["admitted_rows"] += 1
                counts["code_units"] += len(projection.code_units)
                counts["pairs"] += len(projection.pairs)
                counts["semantic_facts"] += len(projection.semantic_facts)
                counts["projection_diagnostics"] += len(
                    projection.diagnostics
                )
                row_index += 1
                if row_index % 250 == 0:
                    _log(
                        "source_progress",
                        admitted_rows=counts["admitted_rows"],
                        elapsed_seconds=round(time.monotonic() - start, 2),
                        rejected_rows=counts["rejected_rows"],
                        rows=row_index,
                    )

    if row_index != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError(
            f"source row count differs: {row_index} != {CVEFIXES_ROW_COUNT}"
        )
    if counts["admitted_rows"] + counts["rejected_rows"] != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError("source coverage is incomplete")
    if (
        len(source_row_cids) != CVEFIXES_ROW_COUNT
        or len(source_row_statuses) != CVEFIXES_ROW_COUNT
    ):
        raise CompleteReleaseBuildError(
            "ordered source-row lineage inventory is incomplete"
        )
    if not projections:
        raise CompleteReleaseBuildError("no source rows passed admission")

    _log(
        "graph_build_started",
        projections=len(projections),
        code_units=counts["code_units"],
    )
    graph = build_cvefixes_graph(
        projections,
        cwe_by_cve=cwe_by_cve,
    )
    counts["graph_nodes"] = len(graph.nodes)
    counts["graph_edges"] = len(graph.edges)

    evaluation = EvaluationRecord(
        source_cids=tuple(
            sorted(set(source_row_cids))
        ),
        parent_cids=(graph.graph_root,),
        config_cid=canonical_config_cid(
            {
                "build_schema_version": BUILD_SCHEMA_VERSION,
                "release_policy_sha256": RELEASE_POLICY_SHA256,
            },
            schema_version="cvefixes-release-evaluation-config/v1",
        ),
        # These metrics describe the complete derived graph, not an arbitrary
        # individual policy candidate.
        subject_cids=(graph.graph_root,),
        metrics={
            "admitted_rows": counts["admitted_rows"],
            "coverage_rows": CVEFIXES_ROW_COUNT,
            "graph_edges": counts["graph_edges"],
            "graph_nodes": counts["graph_nodes"],
            "rejected_rows": counts["rejected_rows"],
            "source_coverage": 1.0,
        },
        payload={
            "grants_execution_authority": False,
            "promotion_decision": "not_applicable_non_authoritative_dataset",
        },
    )
    records.append(evaluation)
    entries.append(
        _record_entry(
            evaluation,
            kind="security_ir_evaluation",
            text=(
                "CVEfixes release evaluation full source coverage "
                f"{CVEFIXES_ROW_COUNT} rows non-authoritative"
            ),
            # The evaluation report retains the complete ordered source-CID
            # inventory.  Its compact retrieval projection binds to the
            # aggregate graph root instead of copying more than the
            # RetrievalEntry provenance limit into one search row.
            source_cids=evaluation.parent_cids,
            policies=(
                "aggregate_provenance_in_evaluation_report",
                "release_evaluation",
            ),
        )
    )
    counts["canonical_security_ir_records"] = len(records)
    counts["extra_retrieval_entries"] = len(entries)
    return Materialization(
        graph=graph,
        extra_entries=tuple(sorted(entries, key=lambda item: item.entry_id)),
        record_cids=tuple(sorted(item.cid for item in records)),
        # Preserve global source-row order for the original-data lookup.  The
        # aggregate EvaluationRecord above separately stores a sorted set.
        source_row_cids=tuple(source_row_cids),
        source_row_statuses=tuple(source_row_statuses),
        evaluation=evaluation,
        counts=dict(counts),
        rejection_reasons=dict(sorted(rejection_reasons.items())),
        source_verification=verification.to_dict(),
    )


def _license_provenance() -> LicenseProvenance:
    return LicenseProvenance(
        dataset_id=CVEFIXES_DATASET_ID,
        source_revision=CVEFIXES_REVISION,
        license_expression="Apache-2.0",
        evidence_url=(
            "https://huggingface.co/datasets/hitoshura25/cvefixes"
        ),
        review_status=LicenseReviewStatus.REVIEWED,
        reviewed_by="Publicus Security IR release review",
        reviewed_at="2026-07-29T00:00:00Z",
        redistribution_allowed=True,
    )


def _ordered_unembedded_entries(
    materialization: Materialization,
) -> tuple[RetrievalEntry, ...]:
    partition = {
        node.cid: "train" for node in materialization.graph.nodes
    }
    base = graph_entries(
        materialization.graph,
        partition_by_node=partition,
        shard_count=8,
    )
    combined = (*base, *materialization.extra_entries)
    node_cids = [item.node_cid for item in combined]
    if len(node_cids) != len(set(node_cids)):
        raise CompleteReleaseBuildError(
            "CUDA input requires unique graph/record node CIDs"
        )
    return combined


def _write_embedding_input(
    entries: Sequence[RetrievalEntry],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    with temporary.open("wb") as handle:
        for position, entry in enumerate(entries):
            value = {
                "node_cid": entry.node_cid,
                "position": position,
                "text": entry.text,
                "text_sha256": hashlib.sha256(
                    entry.text.encode("utf-8")
                ).hexdigest(),
            }
            handle.write(_canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _cuda_image_binding(
    image: str,
    inspection: Mapping[str, Any],
) -> tuple[str, str]:
    image_id = inspection.get("Id")
    repo_digests = inspection.get("RepoDigests")
    if (
        not isinstance(image_id, str)
        or _SHA256_RE.fullmatch(image_id.removeprefix("sha256:")) is None
        or not isinstance(repo_digests, list)
        or any(not isinstance(item, str) for item in repo_digests)
    ):
        raise CompleteReleaseBuildError(
            "CUDA container inspection is malformed"
        )
    if image == CUDA_IMAGE:
        reviewed_reference = (
            f"nvcr.io/nvidia/pytorch@{CUDA_IMAGE_DIGEST}"
        )
        if reviewed_reference not in repo_digests:
            raise CompleteReleaseBuildError(
                "CUDA container manifest digest differs from the reviewed pin"
            )
        return reviewed_reference, reviewed_reference
    # A custom local image runs by immutable configuration ID after inspection.
    return image_id, f"{image}@{image_id}"


def _resolve_cuda_image(image: str) -> tuple[str, str]:
    if shutil.which("docker") is None:
        raise CompleteReleaseBuildError("docker is required for CUDA worker")
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        raise CompleteReleaseBuildError("CUDA container image is unavailable")
    try:
        decoded = json.loads(inspect.stdout)
    except json.JSONDecodeError as exc:
        raise CompleteReleaseBuildError(
            "CUDA container inspection is unreadable"
        ) from exc
    if not isinstance(decoded, list) or len(decoded) != 1:
        raise CompleteReleaseBuildError(
            "CUDA container inspection must identify exactly one image"
        )
    inspection = decoded[0]
    if not isinstance(inspection, Mapping):
        raise CompleteReleaseBuildError(
            "CUDA container inspection is malformed"
        )
    return _cuda_image_binding(image, inspection)


def _run_cuda_embeddings(
    *,
    repository_root: Path,
    work_root: Path,
    input_jsonl: Path,
    output_npy: Path,
    receipt_json: Path,
    runtime_image: str,
    container_identity: str,
    batch_size: int,
) -> Mapping[str, Any]:
    pip_cache = work_root / "pip-cache"
    pip_cache.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "--ipc=host",
        "--ulimit",
        "memlock=-1",
        "--ulimit",
        "stack=67108864",
        "-v",
        f"{repository_root}:/workspace:ro",
        "-v",
        f"{work_root}:/work",
        "-v",
        f"{pip_cache}:/root/.cache/pip",
        "-w",
        "/workspace",
        runtime_image,
        "bash",
        "-lc",
        (
            f"python -m pip install --disable-pip-version-check --no-input "
            f"sentence-transformers=={SENTENCE_TRANSFORMERS_VERSION} "
            '&& exec python "$@"'
        ),
        "python",
        "scripts/ops/security_ir/embed_cvefixes_cuda.py",
        "--input-jsonl",
        f"/work/{input_jsonl.relative_to(work_root).as_posix()}",
        "--model-id",
        MODEL_ID,
        "--model-revision",
        MODEL_REVISION,
        "--output-npy",
        f"/work/{output_npy.relative_to(work_root).as_posix()}",
        "--receipt-json",
        f"/work/{receipt_json.relative_to(work_root).as_posix()}",
        "--batch-size",
        str(batch_size),
    ]
    _log(
        "cuda_embedding_started",
        batch_size=batch_size,
        image=container_identity,
        model=f"{MODEL_ID}@{MODEL_REVISION}",
    )
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise CompleteReleaseBuildError(
            f"CUDA embedding worker failed with exit {result.returncode}"
        )
    return _validate_cuda_embedding_artifacts(
        input_jsonl=input_jsonl,
        output_npy=output_npy,
        receipt_json=receipt_json,
        container_identity=container_identity,
    )


def _validate_cuda_embedding_artifacts(
    *,
    input_jsonl: Path,
    output_npy: Path,
    receipt_json: Path,
    container_identity: str,
) -> Mapping[str, Any]:
    try:
        receipt = json.loads(receipt_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompleteReleaseBuildError(
            "CUDA embedding receipt is unreadable"
        ) from exc
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("cuda_required") is not True
        or receipt.get("model_id") != MODEL_ID
        or receipt.get("model_revision") != MODEL_REVISION
        or receipt.get("embedding_dimension") != MODEL_DIMENSION
        or receipt.get("sentence_transformers_version")
        != SENTENCE_TRANSFORMERS_VERSION
    ):
        raise CompleteReleaseBuildError(
            "CUDA embedding receipt differs from build contract"
        )
    try:
        artifacts_match = (
            receipt.get("input_sha256") == _file_sha256(input_jsonl)
            and receipt.get("output_sha256") == _file_sha256(output_npy)
            and receipt.get("output_size_bytes") == output_npy.stat().st_size
        )
    except OSError as exc:
        raise CompleteReleaseBuildError(
            "CUDA embedding artifacts are unreadable"
        ) from exc
    if not artifacts_match:
        raise CompleteReleaseBuildError(
            "CUDA embedding artifacts differ from their receipt"
        )
    return {**dict(receipt), "container_image": container_identity}


class _PrecomputedEmbeddingPort(EmbeddingAcceleratorPort):
    def __init__(
        self,
        matrix_path: Path,
        expected_entries: Sequence[RetrievalEntry],
    ) -> None:
        self.matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
        self.expected_hashes = tuple(
            hashlib.sha256(item.text.encode("utf-8")).hexdigest()
            for item in expected_entries
        )
        if (
            self.matrix.dtype != np.float32
            or self.matrix.shape
            != (len(expected_entries), MODEL_DIMENSION)
            or not np.isfinite(self.matrix).all()
        ):
            raise CompleteReleaseBuildError(
                "precomputed CUDA embedding matrix is malformed"
            )

    def embed_documents(
        self, texts: Sequence[str]
    ) -> Sequence[Sequence[float]]:
        hashes = tuple(
            hashlib.sha256(item.encode("utf-8")).hexdigest()
            for item in texts
        )
        if hashes != self.expected_hashes:
            raise CompleteReleaseBuildError(
                "retrieval builder requested a different embedding order"
            )
        return self.matrix.tolist()

    def embed_query(self, text: str) -> Sequence[float]:
        del text
        raise CompleteReleaseBuildError(
            "build-time embedding port does not embed queries"
        )


def _build_embedded_index(
    materialization: Materialization,
    unembedded_entries: Sequence[RetrievalEntry],
    matrix_path: Path,
) -> RetrievalIndex:
    partition = {
        node.cid: "train" for node in materialization.graph.nodes
    }
    port = _PrecomputedEmbeddingPort(matrix_path, unembedded_entries)
    model_config = {
        "cuda_required": True,
        "dimension": MODEL_DIMENSION,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "normalize_embeddings": True,
        "schema_version": EMBEDDING_MODEL_CONFIG_VERSION,
        "sentence_transformers_version": SENTENCE_TRANSFORMERS_VERSION,
    }
    return build_retrieval_index(
        materialization.graph,
        partition_by_node=partition,
        config=RETRIEVAL_CONFIG,
        shard_count=8,
        extra_entries=materialization.extra_entries,
        embedding_port=port,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        model_config=model_config,
    )


def _corpus_rows(index: RetrievalIndex) -> list[dict[str, Any]]:
    pairs = [
        (entry, shard.shard_id)
        for shard in index.shards
        for entry in shard.entries
    ]
    pairs.sort(key=lambda item: item[0].entry_id)
    rows: list[dict[str, Any]] = []
    for document_index, (entry, shard_id) in enumerate(pairs):
        title = _bounded_text(
            (
                entry.kind.replace("_", " "),
                " ".join(entry.cwes),
                " ".join(entry.languages),
            )
        )[:512]
        rows.append(
            {
                "document_index": document_index,
                "entry_cid": entry.entry_id,
                "node_cid": entry.node_cid,
                "title": title,
                "text": entry.text,
                "partition": entry.partition,
                "shard_key": shard_id,
                "kind": entry.kind,
                "authority": entry.authority.value,
                "source_cids": list(entry.source_cids),
                "cwes": list(entry.cwes),
                "languages": list(entry.languages),
                "code_facts": list(entry.code_facts),
                "actions": list(entry.actions),
                "effects": list(entry.effects),
                "policies": list(entry.policies),
                "graph_node": entry.graph_node,
                "grants_execution_authority": False,
                "text_sha256": hashlib.sha256(
                    entry.text.encode("utf-8")
                ).hexdigest(),
                "schema_version": CORPUS_SCHEMA_VERSION,
            }
        )
    return rows


def _install_graph_layout(root: Path, layout: Any) -> None:
    for artifact in layout.artifacts:
        path = root.joinpath(*PurePosixPath(artifact.path).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.content)


def _install_original_data(
    source_root: Path,
    release_root: Path,
) -> tuple[dict[str, Any], ...]:
    """Copy the reviewed source Parquet bytes into the public release.

    The copied files remain byte-for-byte identical to the immutable upstream
    snapshot.  They intentionally retain the upstream schema and compression;
    the bounded derived retrieval families continue to use their own Zstandard
    schemas.
    """

    target_root = release_root / "data" / "original"
    target_root.mkdir(parents=True, exist_ok=True)
    installed: list[dict[str, Any]] = []
    for shard_id, shard in enumerate(PINNED_CVEFIXES_SOURCE.shards):
        source_path = source_root / shard.path
        relative_path = f"data/original/part-{shard_id:06d}.parquet"
        target_path = release_root / relative_path
        if target_path.exists() or target_path.is_symlink():
            raise CompleteReleaseBuildError(
                f"original-data target already exists: {relative_path}"
            )
        try:
            shutil.copyfile(source_path, target_path)
            target_path.chmod(0o644)
        except OSError as exc:
            raise CompleteReleaseBuildError(
                f"cannot install original-data shard: {relative_path}"
            ) from exc
        observed_sha256 = _file_sha256(target_path)
        if (
            target_path.stat().st_size != shard.size_bytes
            or observed_sha256 != shard.sha256
        ):
            raise CompleteReleaseBuildError(
                f"installed original-data shard differs: {relative_path}"
            )
        installed.append(
            {
                "content_id": cid_v1_from_digest(
                    bytes.fromhex(shard.sha256)
                ),
                "release_path": relative_path,
                "row_count": shard.row_count,
                "sha256": shard.sha256,
                "size_bytes": shard.size_bytes,
                "source_path": shard.path,
            }
        )
    return tuple(installed)


def _write_original_row_index(
    materialization: Materialization,
    release_root: Path,
    original_shards: Sequence[Mapping[str, Any]],
) -> Path:
    """Map every stable source-row CID to its exact copied shard and offset."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CompleteReleaseBuildError(
            "pyarrow is required for the original-row index"
        ) from exc
    if len(materialization.source_row_cids) != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError(
            "original-row CID inventory differs from the pinned row count"
        )
    if len(materialization.source_row_statuses) != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError(
            "original-row status inventory differs from the pinned row count"
        )
    if len(set(materialization.source_row_cids)) != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError(
            "original-row CID inventory is not unique"
        )
    if len(original_shards) != len(PINNED_CVEFIXES_SOURCE.shards):
        raise CompleteReleaseBuildError(
            "original-data shard inventory is incomplete"
        )

    rows: list[dict[str, Any]] = []
    source_row_index = 0
    for source_shard_id, shard in enumerate(original_shards):
        row_count = int(shard["row_count"])
        for source_shard_row_index in range(row_count):
            rows.append(
                {
                    "security_ir_source_cid": materialization.source_row_cids[
                        source_row_index
                    ],
                    "source_row_index": source_row_index,
                    "source_status": materialization.source_row_statuses[
                        source_row_index
                    ],
                    "source_identity_domain": (
                        "cvefixes-security-ir/pinned-source-row"
                        if materialization.source_row_statuses[
                            source_row_index
                        ]
                        == "admitted"
                        else "cvefixes-security-ir/rejected-source-row"
                    ),
                    "source_identity_schema_version": (
                        "cvefixes-pinned-source-row/v1"
                        if materialization.source_row_statuses[
                            source_row_index
                        ]
                        == "admitted"
                        else "cvefixes-rejected-source-row/v1"
                    ),
                    "source_shard_cid": str(shard["content_id"]),
                    "source_shard_path": str(shard["source_path"]),
                    "source_shard_row_index": source_shard_row_index,
                    "relative_path": str(shard["release_path"]),
                    "source_dataset_id": CVEFIXES_DATASET_ID,
                    "source_revision": CVEFIXES_REVISION,
                    "schema_version": ORIGINAL_ROW_INDEX_SCHEMA_VERSION,
                }
            )
            source_row_index += 1
    if source_row_index != CVEFIXES_ROW_COUNT:
        raise CompleteReleaseBuildError(
            "original-data shard rows do not cover the pinned row count"
        )
    rows.sort(key=lambda item: str(item["security_ir_source_cid"]))
    schema = pa.schema(
        [
            ("security_ir_source_cid", pa.string(), False),
            ("source_row_index", pa.int32(), False),
            ("source_status", pa.string(), False),
            ("source_identity_domain", pa.string(), False),
            ("source_identity_schema_version", pa.string(), False),
            ("source_shard_cid", pa.string(), False),
            ("source_shard_path", pa.string(), False),
            ("source_shard_row_index", pa.int32(), False),
            ("relative_path", pa.string(), False),
            ("source_dataset_id", pa.string(), False),
            ("source_revision", pa.string(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"primary_key": b"security_ir_source_cid",
            b"schema_version": ORIGINAL_ROW_INDEX_SCHEMA_VERSION.encode(
                "ascii"
            ),
        },
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    index_path = release_root / "indexes" / "original_rows.parquet"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        pq.write_table(
            table,
            index_path,
            compression="zstd",
            compression_level=9,
            data_page_version="1.0",
            row_group_size=4_096,
            use_dictionary=True,
            version="2.6",
            write_statistics=True,
        )
        index_path.chmod(0o644)
    except OSError as exc:
        raise CompleteReleaseBuildError(
            "cannot write original-row index"
        ) from exc
    return index_path


def _parquet_config(path: str) -> str:
    if path in INDEX_CONFIGS:
        return INDEX_CONFIGS[path]
    for prefix, config in PATH_CONFIGS:
        if path.startswith(prefix):
            return config
    raise CompleteReleaseBuildError(
        f"unexpected complete-layout Parquet path: {path}"
    )


def _artifact_descriptor(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    try:
        if path.is_symlink() or not path.is_file():
            raise CompleteReleaseBuildError(
                f"release artifact is not a regular file: {relative}"
            )
        byte_length = path.stat().st_size
        sha256 = _file_sha256(path)
    except OSError as exc:
        raise CompleteReleaseBuildError(
            f"cannot inspect release artifact: {relative}"
        ) from exc
    descriptor: dict[str, Any] = {
        "byte_length": byte_length,
        "content_id": cid_v1_from_digest(bytes.fromhex(sha256)),
        "media_type": (
            "application/vnd.apache.parquet"
            if relative.endswith(".parquet")
            else (
                "application/json"
                if relative.endswith(".json")
                else "text/markdown; charset=utf-8"
            )
        ),
        "path": relative,
        "sha256": sha256,
    }
    if relative.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq

            row_count = pq.ParquetFile(path).metadata.num_rows
        except Exception as exc:
            raise CompleteReleaseBuildError(
                f"cannot inspect Parquet artifact {relative}"
            ) from exc
        if row_count <= 0:
            raise CompleteReleaseBuildError(
                f"Parquet artifact is empty: {relative}"
            )
        descriptor["config_name"] = _parquet_config(relative)
        descriptor["row_count"] = row_count
    return descriptor


def _features_for_artifact(path: Path) -> dict[str, dict[str, str]]:
    try:
        import pyarrow.parquet as pq

        schema = pq.ParquetFile(path).schema_arrow
    except Exception as exc:
        raise CompleteReleaseBuildError(
            f"cannot read feature schema for {path}"
        ) from exc
    # This is ordinary release metadata, not Hugging Face's reserved
    # dataset_infos.json.  Preserve the exact Arrow type text so remote
    # consumers do not mistake integer, floating, boolean, list, or fixed-size
    # vector columns for strings.
    return {
        field.name: {"dtype": str(field.type)}
        for field in schema
    }


def _release_metadata(
    root: Path,
    descriptors: Sequence[Mapping[str, Any]],
    *,
    derived_dataset_root: str,
) -> dict[str, Any]:
    configs: dict[str, Any] = {}
    for config_name in sorted(VIEWER_CONFIG_PATHS):
        selected = [
            item for item in descriptors
            if item.get("config_name") == config_name
        ]
        if not selected:
            raise CompleteReleaseBuildError(
                f"Viewer config has no artifact: {config_name}"
            )
        first_path = root / str(selected[0]["path"])
        configs[config_name] = {
            "features": _features_for_artifact(first_path),
            "splits": {
                "train": {
                    "num_bytes": sum(
                        int(item["byte_length"]) for item in selected
                    ),
                    "num_examples": sum(
                        int(item["row_count"]) for item in selected
                    ),
                }
            },
        }
    return {
        "configs": configs,
        "dataset_id": TARGET_DATASET_ID,
        "derived_dataset_root": derived_dataset_root,
        "schema_version": HF_PARQUET_SCHEMA_VERSION,
    }


def _dataset_card(
    *,
    counts: Mapping[str, Any],
    derived_dataset_root: str,
    graph_root: str,
    retrieval_root: str,
    cuda_receipt: Mapping[str, Any],
) -> bytes:
    lines = [
        "---",
        "license: apache-2.0",
        "pretty_name: CVEfixes Security IR GraphRAG",
        "configs:",
    ]
    for config_name, path in sorted(VIEWER_CONFIG_PATHS.items()):
        lines.extend(
            (
                f"- config_name: {config_name}",
                "  data_files:",
                "  - split: train",
                f"    path: {path}",
            )
        )
    lines.extend(
        (
            "source_datasets:",
            "- hitoshura25/cvefixes",
            "---",
            "",
            "# CVEfixes Security IR GraphRAG",
            "",
            "This is a content-addressed, remotely routable Security IR release "
            "of the exact pinned CVEfixes snapshot. It packages the byte-identical "
            "original Parquet data together with a searchable corpus, BM25 "
            "postings, CUDA-generated vectors, typed graph nodes and edges, "
            "bounded adjacency indexes, and a source-CID-to-original-row lookup.",
            "",
            "All entries are inert, non-authoritative evidence. Candidate and "
            "formal-logic rows cannot grant execution authority; exact forbidden "
            "action and scope constraints remain explicitly unresolved until "
            "reviewed by the Security IR policy workflow.",
            "",
            "## Immutable build bindings",
            "",
            f"- Source: `{CVEFIXES_DATASET_ID}@{CVEFIXES_REVISION}`",
            f"- Derived Security IR root: `{derived_dataset_root}`",
            f"- Graph root: `{graph_root}`",
            f"- Retrieval root: `{retrieval_root}`",
            f"- Embedding model: `{MODEL_ID}@{MODEL_REVISION}`",
            f"- CUDA device: `{cuda_receipt['gpu_name']}`",
            f"- CUDA runtime: `{cuda_receipt['cuda_version']}`",
            f"- Embedding dimension: `{cuda_receipt['embedding_dimension']}`",
            "",
            "## Coverage",
            "",
            f"- Source rows represented: `{CVEFIXES_ROW_COUNT}`",
            f"- Original rows packaged: `{CVEFIXES_ROW_COUNT}`",
            f"- Byte-identical original shards: "
            f"`{len(PINNED_CVEFIXES_SOURCE.shards)}`",
            f"- Admitted rows: `{counts.get('admitted_rows', 0)}`",
            f"- Rejection tombstones: `{counts.get('rejected_rows', 0)}`",
            f"- Graph nodes: `{counts.get('graph_nodes', 0)}`",
            f"- Graph edges: `{counts.get('graph_edges', 0)}`",
            "",
            "## Remote index contract",
            "",
            "Each physical Parquet shard is bound by SHA-256, raw CIDv1, byte "
            "size, row count, key range, and path. The Dataset Viewer exposes "
            "the declared data/meta configurations used by Publicus/skillcenter-ir.",
            "The `original_row_index` config maps every Security IR source CID "
            "to a global row index, copied shard CID/path, and shard-local offset.",
            "",
            "## Safety and limitations",
            "",
            "- `original_data` is a byte-preserving mirror of the pinned upstream "
            "dataset and includes unfiltered diffs, vulnerable/fixed code, "
            "secret-like strings, personal data, unsafe paths, and rows excluded "
            "from the derived public Security IR. Treat every value as untrusted "
            "inert evidence; never execute it or use it as a credential.",
            "- The upstream dataset card declares Apache-2.0. Embedded code comes "
            "from many repositories and may retain additional record-level "
            "license obligations; consumers must review those sources.",
            "- Only the derived corpus/graph configs are policy-filtered and "
            "bounded. Original bodies are not injected directly into agent context.",
            "- Graph, lexical, and vector similarity are retrieval evidence only.",
            "- Classification-only candidates do not infer forbidden behavior.",
            "- Consumers must pin a 40-character Hub commit before querying.",
            "",
        )
    )
    return "\n".join(lines).encode("utf-8")


def _source_shard_cids() -> tuple[str, ...]:
    return tuple(
        cid_v1_from_digest(bytes.fromhex(shard.sha256))
        for shard in PINNED_CVEFIXES_SOURCE.shards
    )


def _assemble_release(
    *,
    release_root_path: Path,
    materialization: Materialization,
    original_shards: Sequence[Mapping[str, Any]],
    index: RetrievalIndex,
    corpus_rows: Sequence[Mapping[str, Any]],
    corpus_summary: Any,
    bm25_summary: Any,
    vector_summary: Any,
    graph_layout: Any,
    cuda_receipt: Mapping[str, Any],
) -> Mapping[str, Any]:
    # The layout builders have already written every Parquet file.
    parquet_paths = sorted(release_root_path.rglob("*.parquet"))
    parquet_descriptors = [
        _artifact_descriptor(path, release_root_path)
        for path in parquet_paths
    ]
    observed_indexes = {
        str(item["path"])
        for item in parquet_descriptors
        if str(item["path"]).startswith("indexes/")
    }
    if observed_indexes != set(INDEX_CONFIGS):
        raise CompleteReleaseBuildError(
            "complete layout does not contain every physical index"
        )

    derived_dataset_root = canonical_identity(
        {
            "build_schema_version": BUILD_SCHEMA_VERSION,
            "canonical_record_cids": list(materialization.record_cids),
            "graph_root": materialization.graph.graph_root,
            "retrieval_index_root": index.index_root,
            "source_profile_sha256": PINNED_CVEFIXES_SOURCE.sha256,
        },
        domain="cvefixes-security-ir/complete-derived-dataset",
        schema_version=BUILD_SCHEMA_VERSION,
    ).cid

    evaluation_report = {
        "cuda_embedding_receipt": dict(cuda_receipt),
        "evaluation": materialization.evaluation.to_dict(),
        "grants_execution_authority": False,
        "rejection_reasons": materialization.rejection_reasons,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
        "source_coverage": {
            "covered_rows": CVEFIXES_ROW_COUNT,
            "expected_rows": CVEFIXES_ROW_COUNT,
            "fraction": 1.0,
        },
    }
    (release_root_path / "evaluation-report.json").write_bytes(
        _canonical_json(evaluation_report)
    )
    (release_root_path / "README.md").write_bytes(
        _dataset_card(
            counts=materialization.counts,
            derived_dataset_root=derived_dataset_root,
            graph_root=materialization.graph.graph_root,
            retrieval_root=index.index_root,
            cuda_receipt=cuda_receipt,
        )
    )

    preliminary = [
        *parquet_descriptors,
        _artifact_descriptor(
            release_root_path / "evaluation-report.json",
            release_root_path,
        ),
        _artifact_descriptor(
            release_root_path / "README.md",
            release_root_path,
        ),
    ]
    release_metadata = _release_metadata(
        release_root_path,
        preliminary,
        derived_dataset_root=derived_dataset_root,
    )
    (release_root_path / RELEASE_METADATA_FILENAME).write_bytes(
        _canonical_json(release_metadata)
    )
    artifact_descriptors = sorted(
        (
            *preliminary,
            _artifact_descriptor(
                release_root_path / RELEASE_METADATA_FILENAME,
                release_root_path,
            ),
        ),
        key=lambda item: str(item["path"]),
    )

    release_config = {
        "build_schema_version": BUILD_SCHEMA_VERSION,
        "corpus_schema_version": CORPUS_SCHEMA_VERSION,
        "cuda_image": cuda_receipt["container_image"],
        "embedding_model": f"{MODEL_ID}@{MODEL_REVISION}",
        "graph_config_cid": materialization.graph.config_cid,
        "release_policy_sha256": RELEASE_POLICY_SHA256,
        "retrieval_config_cid": RETRIEVAL_CONFIG.cid,
        "original_mirror_profile": ORIGINAL_MIRROR_PROFILE,
        "source_profile_sha256": PINNED_CVEFIXES_SOURCE.sha256,
    }
    release_config_cid = canonical_config_cid(
        release_config,
        schema_version=BUILD_SCHEMA_VERSION,
    )
    content_root = canonical_identity(
        {
            "artifacts": artifact_descriptors,
            "config_cid": release_config_cid,
            "dataset_id": TARGET_DATASET_ID,
            "derived_dataset_root": derived_dataset_root,
            "profile": ORIGINAL_MIRROR_PROFILE,
            "schema_version": HF_RELEASE_SCHEMA_VERSION,
            "source": _license_provenance().to_dict(),
        },
        domain="cvefixes-security-ir/huggingface-release",
        schema_version=HF_RELEASE_SCHEMA_VERSION,
    ).cid
    data_shard_cids = tuple(
        sorted(
            str(item["content_id"])
            for item in artifact_descriptors
            if str(item["path"]).startswith("data/")
        )
    )
    release_manifest = ReleaseManifest(
        source_cids=_source_shard_cids(),
        parent_cids=(derived_dataset_root,),
        config_cid=release_config_cid,
        dataset_id=TARGET_DATASET_ID,
        profile=ORIGINAL_MIRROR_PROFILE,
        record_cids=materialization.record_cids,
        shard_cids=data_shard_cids,
        payload={
            "derived_security_ir_profile": PUBLIC_RELEASE_PROFILE.name,
            "derived_dataset_schema_version": BUILD_SCHEMA_VERSION,
            "grants_execution_authority": False,
            "release_root": content_root,
            "release_schema_version": HF_RELEASE_SCHEMA_VERSION,
        },
    )
    index_descriptors = {
        PurePosixPath(str(item["path"])).stem: {
            "cid": item["content_id"],
            "relative_path": item["path"],
            "row_count": item["row_count"],
            "sha256": item["sha256"],
            "size_bytes": item["byte_length"],
        }
        for item in artifact_descriptors
        if str(item["path"]).startswith("indexes/")
    }
    counts = {
        **materialization.counts,
        **dict(bm25_summary.counts),
        "corpus_rows": len(corpus_rows),
        "graph_data_shards": len(graph_layout.data_artifacts),
        "original_data_bytes": sum(
            int(item["size_bytes"]) for item in original_shards
        ),
        "original_data_rows": sum(
            int(item["row_count"]) for item in original_shards
        ),
        "original_data_shards": len(original_shards),
        "original_row_index_rows": len(materialization.source_row_cids),
        "vector_chunks": vector_summary.vector_chunks,
        "vector_rows": vector_summary.vector_rows,
    }
    graph_manifest = {
        "adjacency": "incoming_and_outgoing_bounded_pages",
        "edge_count": len(materialization.graph.edges),
        "graph_root": materialization.graph.graph_root,
        "node_count": len(materialization.graph.nodes),
        "ontology_version": materialization.graph.ontology_version,
    }
    manifest = {
        "artifacts": artifact_descriptors,
        "bm25": bm25_summary.to_manifest_fragment()["bm25"],
        "build_runtime": {
            "build_schema_version": BUILD_SCHEMA_VERSION,
            "cuda": dict(cuda_receipt),
            "original_data": {
                "byte_exact_upstream_copy": True,
                "config_name": "original_data",
                "mirror_profile": ORIGINAL_MIRROR_PROFILE,
                "operator_acknowledgement_required": True,
                "row_index_config_name": "original_row_index",
                "shards": [dict(item) for item in original_shards],
                "source_dataset_id": CVEFIXES_DATASET_ID,
                "source_profile_sha256": PINNED_CVEFIXES_SOURCE.sha256,
                "source_revision": CVEFIXES_REVISION,
            },
            "source_verification": dict(
                materialization.source_verification
            ),
        },
        "configs": dict(sorted(ALL_CONFIG_PATHS.items())),
        "counts": counts,
        "dataset_id": TARGET_DATASET_ID,
        "derived_dataset_root": derived_dataset_root,
        "graph": graph_manifest,
        "indexes": index_descriptors,
        "parquet": {
            "compression": {
                "derived_and_indexes": "zstd",
                "original_data": "upstream_byte_exact",
            },
            "meta_schema_version": META_SCHEMA_VERSION,
            "physical_index_count": len(index_descriptors),
        },
        "primary_key": "entry_cid",
        "release_manifest": release_manifest.to_dict(),
        "release_root": content_root,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
        "source": _license_provenance().to_dict(),
        "vector": dict(vector_summary.manifest_config),
    }
    manifest_content = _canonical_json(manifest)
    if len(manifest_content) > 8 * 1024 * 1024:
        raise CompleteReleaseBuildError(
            "manifest exceeds the publisher's 8 MiB safety bound"
        )
    (release_root_path / "manifest.json").write_bytes(manifest_content)
    return manifest


def _fresh_directory(path: Path) -> Path:
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise CompleteReleaseBuildError(
                f"owned output path is unsafe: {path}"
            )
        if any(path.iterdir()):
            raise CompleteReleaseBuildError(
                f"owned output directory is not empty: {path}"
            )
    else:
        path.mkdir(parents=True)
    return path


def build_complete_release(
    *,
    source_root: Path,
    work_root: Path,
    release_directory: Path,
    cuda_image: str,
    cuda_batch_size: int,
    repository_root: Path,
    reuse_cuda_embeddings: bool = False,
) -> Mapping[str, Any]:
    source_root = source_root.expanduser().resolve(strict=True)
    work_root = work_root.expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    if work_root.is_symlink() or not work_root.is_dir():
        raise CompleteReleaseBuildError("work root must be a real directory")
    runtime_image, container_identity = _resolve_cuda_image(cuda_image)
    release_root_path = _fresh_directory(release_directory)

    materialization = _materialize_source(source_root)
    _log(
        "materialization_complete",
        **materialization.counts,
        rejection_reasons=materialization.rejection_reasons,
    )
    unembedded_entries = _ordered_unembedded_entries(materialization)
    embedding_dir = work_root / "embeddings"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    input_jsonl = embedding_dir / "input.jsonl"
    output_npy = embedding_dir / "embeddings.npy"
    receipt_json = embedding_dir / "receipt.json"
    for path in (input_jsonl, output_npy, receipt_json):
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise CompleteReleaseBuildError(
                    f"embedding output path is unsafe: {path}"
                )
            if path == input_jsonl or not reuse_cuda_embeddings:
                path.unlink()
    if reuse_cuda_embeddings and (
        not output_npy.is_file() or not receipt_json.is_file()
    ):
        raise CompleteReleaseBuildError(
            "reusable CUDA embedding artifacts are incomplete"
        )
    _write_embedding_input(unembedded_entries, input_jsonl)
    if reuse_cuda_embeddings:
        cuda_receipt = _validate_cuda_embedding_artifacts(
            input_jsonl=input_jsonl,
            output_npy=output_npy,
            receipt_json=receipt_json,
            container_identity=container_identity,
        )
        _log(
            "cuda_embedding_reused",
            image=container_identity,
            output_sha256=cuda_receipt["output_sha256"],
            records=cuda_receipt["record_count"],
        )
    else:
        cuda_receipt = _run_cuda_embeddings(
            repository_root=repository_root,
            work_root=work_root,
            input_jsonl=input_jsonl,
            output_npy=output_npy,
            receipt_json=receipt_json,
            runtime_image=runtime_image,
            container_identity=container_identity,
            batch_size=cuda_batch_size,
        )
    if cuda_receipt.get("record_count") != len(unembedded_entries):
        raise CompleteReleaseBuildError(
            "CUDA receipt row count differs from retrieval input"
        )
    index = _build_embedded_index(
        materialization,
        unembedded_entries,
        output_npy,
    )
    if index.embedding_dimension != MODEL_DIMENSION:
        raise CompleteReleaseBuildError(
            "retrieval index embedding dimension differs"
        )
    _log(
        "retrieval_index_complete",
        dimension=index.embedding_dimension,
        entries=sum(len(shard.entries) for shard in index.shards),
        index_root=index.index_root,
        shards=len(index.shards),
    )

    corpus_rows = _corpus_rows(index)
    corpus_summary = build_cvefixes_hf_corpus_layout(
        corpus_rows,
        release_root_path,
    )
    bm25_rows = [
        {
            "authority": row["authority"],
            "body": row["text"],
            "document_index": row["document_index"],
            "entry_cid": row["entry_cid"],
            "record_type": row["kind"],
            "title": row["title"],
        }
        for row in corpus_rows
    ]
    bm25_summary = build_cvefixes_bm25_hf_layout(
        bm25_rows,
        release_root_path,
    )
    vector_summary = build_cvefixes_hf_vector_layout(
        index,
        release_root_path,
        require_embeddings=True,
        require_immutable_model_revision=True,
    )
    entry_cid_by_node = {
        entry.node_cid: entry.entry_id
        for shard in index.shards
        for entry in shard.entries
        if entry.graph_node
    }
    graph_layout = build_cvefixes_hf_graph_layout(
        materialization.graph,
        entry_cid_by_node=entry_cid_by_node,
    )
    _install_graph_layout(release_root_path, graph_layout)
    original_shards = _install_original_data(
        source_root,
        release_root_path,
    )
    _write_original_row_index(
        materialization,
        release_root_path,
        original_shards,
    )
    manifest = _assemble_release(
        release_root_path=release_root_path,
        materialization=materialization,
        original_shards=original_shards,
        index=index,
        corpus_rows=corpus_rows,
        corpus_summary=corpus_summary,
        bm25_summary=bm25_summary,
        vector_summary=vector_summary,
        graph_layout=graph_layout,
        cuda_receipt=cuda_receipt,
    )
    _log(
        "release_complete",
        artifacts=len(manifest["artifacts"]),
        manifest_sha256=_file_sha256(
            release_root_path / "manifest.json"
        ),
        release_directory=str(release_root_path),
        release_root=manifest["release_root"],
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the complete CUDA-embedded Publicus CVEfixes Security IR "
            "GraphRAG Hugging Face release."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--cuda-image", default=CUDA_IMAGE)
    parser.add_argument("--cuda-batch-size", type=int, default=512)
    parser.add_argument(
        "--reuse-cuda-embeddings",
        action="store_true",
        help=(
            "Reuse existing work-root embeddings only after exact input, "
            "output, receipt, model, and CUDA contract verification."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.cuda_batch_size <= 4_096:
        raise SystemExit("--cuda-batch-size must be between 1 and 4096")
    repository_root = Path(__file__).resolve().parents[3]
    try:
        build_complete_release(
            source_root=args.source_root,
            work_root=args.work_root,
            release_directory=args.release_directory,
            cuda_image=args.cuda_image,
            cuda_batch_size=args.cuda_batch_size,
            repository_root=repository_root,
            reuse_cuda_embeddings=args.reuse_cuda_embeddings,
        )
    except CompleteReleaseBuildError as exc:
        sys.stderr.write(
            _canonical_json(
                {
                    "error": str(exc),
                    "schema_version": BUILD_SCHEMA_VERSION,
                    "success": False,
                }
            ).decode("ascii")
            + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
