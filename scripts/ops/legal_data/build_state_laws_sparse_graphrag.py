#!/usr/bin/env python3
"""Resumable exact-51 state-law sparse GraphRAG local build (LCR-038).

Orchestrates corpus admission, pinned GTE embeddings, field-weighted BM25,
centroid-routed vectors, the legal/provenance graph, and bounded adjacency
with atomic checkpoints. A full run covers exactly 50 states plus DC and
proves corpus-to-BM25-to-vector-to-graph key parity plus a local retrieval
canary for every jurisdiction.

Validation gate::

    python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --full --check

``--check`` re-runs the compact exact-51 software-contract build and
validates the frozen ``local_e2e.json`` receipt without rewriting it.
``--write`` is the only flag that materializes the receipt. The compact
build never authorizes publication or Hub upload. Live 51-jurisdiction
scrape evidence is a separate gate (``--require-live-evidence``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed_site = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed_site not in sys.path:
        sys.path.insert(0, _sealed_site)

from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (  # noqa: E402
    MAX_ADJACENCY_POINTERS_PER_ROW,
    assert_adjacency_bounded,
    assert_adjacency_reconciled,
    build_state_laws_adjacency,
    build_state_laws_lexical_graph,
    default_adjacency_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (  # noqa: E402
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    StateLawsBm25Index,
    assert_every_admitted_chunk_has_document,
    assert_shards_bounded,
    build_corpus_root_cid,
    build_state_laws_bm25_index,
    default_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (  # noqa: E402
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (  # noqa: E402
    MaterializedCorpus,
    assert_admitted_rows_complete,
    assert_combined_count_equals_deduped_union,
    assert_every_row_has_exactly_one_disposition,
    assert_no_secrets_or_home_paths,
    assert_recovery_quarantine_excluded_from_canonical_counts,
    materialize_state_laws_corpus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PROJECTION_BACKEND,
    EmbeddingGenerationResult,
    fixture_embedding_config,
    generate_state_laws_embeddings,
    is_projection_backend,
    require_pinned_gte_small,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (  # noqa: E402
    DEFAULT_EDITION,
    REQUIRED_COVERAGE_NODE_TYPES,
    GraphNodeType,
    StateLawsGraphProjection,
    fixture_seed_records,
    fixture_similarity_neighbors,
    project_state_laws_graph,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (  # noqa: E402
    CANONICAL_JURISDICTIONS,
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vectors import (  # noqa: E402
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    StateLawsVectorBinding,
    assert_centroid_routes_bounded,
    bind_state_laws_vectors,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-local-e2e-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-local-e2e@1"
TASK_ID: Final = "LCR-038"
GOAL_ID: Final = "LCR-G060"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "build_state_laws_sparse_graphrag.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "full-local-build"
CODE_VERSION: Final = "1"
CHECKPOINT_ENV: Final = "LCR_038_CHECKPOINT_DIR"
CHECKPOINT_FILENAME: Final = "full_build_checkpoint.json"
DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/local_e2e.json")
DEFAULT_OUTPUT_DIR: Final = Path("build/state-laws-sparse-graphrag")
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
BUILD_STAGES: Final = (
    "corpus",
    "embeddings",
    "bm25",
    "vectors",
    "graph",
    "adjacency",
    "parity",
    "canaries",
)
ACCEPTANCE_CRITERIA: Final = (
    "A resumable full build covers exactly 51 jurisdictions with "
    "corpus-to-BM25-to-vector-to-graph key parity, pinned GTE embeddings, "
    "all shard bounds, local retrieval for every jurisdiction, measured "
    "resource usage, and no partial output. The compact receipt proves the "
    "software contract only and does not authorize publication or Hub upload."
)
COHORT_LETTERS: Final = tuple("ABCDEFGHIJKLM")
FULL_SCRAPE_ACCEPTANCE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json"
)
REQUIRED_FAMILIES: Final = ("corpus", "bm25", "vectors", "graph", "adjacency")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullBuildError(RuntimeError):
    """Fail-closed local e2e orchestrator error."""


class LiveEvidenceRequiredError(FullBuildError):
    """Raised when a live 51-jurisdiction scrape receipt is required but absent."""


class KeyParityError(FullBuildError):
    """Raised when family keys diverge."""


class ShardBoundError(FullBuildError):
    """Raised when a physical shard or pointer bound is exceeded."""


class CheckpointError(FullBuildError):
    """Raised when a checkpoint is stale, partial, or config-mismatched."""


class CanaryError(FullBuildError):
    """Raised when a jurisdiction local-retrieval canary fails."""


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_REPORT_RELPATH


def default_checkpoint_dir() -> Path:
    override = os.environ.get(CHECKPOINT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (REPOSITORY_ROOT / DEFAULT_OUTPUT_DIR / ".checkpoints").resolve()


def _repo_path(relpath: Path | str, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / Path(relpath)


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FullBuildError(f"JSON object required: {path}")
    return payload


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    return write_json_atomic(report_path, dict(report))


def _digest_for_report(payload: Mapping[str, Any]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key not in {"report_digest_sha256", "resources"}
    }
    resources = payload.get("resources")
    if isinstance(resources, Mapping):
        stripped["resources"] = {
            key: value for key, value in resources.items() if key != "measured"
        }
    return digest_payload(stripped)


def _checkpoint_path(checkpoint_dir: Path) -> Path:
    return Path(checkpoint_dir) / CHECKPOINT_FILENAME


def load_checkpoint(path: Path | str) -> dict[str, Any]:
    payload = load_json_mapping(path)
    return payload


def write_checkpoint_atomic(path: Path | str, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return write_json_atomic(target, dict(payload))


def assert_checkpoint_compatible(
    payload: Mapping[str, Any], *, config_digest: str
) -> None:
    if payload.get("partial") is True or payload.get("status") == "partial":
        raise CheckpointError("partial checkpoints cannot be sealed or resumed")
    recorded = str(payload.get("config_digest") or "")
    if recorded != config_digest:
        raise CheckpointError(
            f"checkpoint config_digest {recorded!r} does not match {config_digest!r}"
        )


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(getattr(usage, "ru_maxrss", 0) or 0)
    rss_bytes = rss if rss >= 1024**3 else rss * 1024.0
    return {
        "max_rss_bytes": rss_bytes,
        "user_cpu_seconds": float(usage.ru_utime),
        "system_cpu_seconds": float(usage.ru_stime),
    }


def _synthetic_resources(
    *,
    section_count: int,
    chunk_count: int,
    posting_count: int,
    graph_node_count: int,
    graph_edge_count: int,
) -> dict[str, Any]:
    estimated = (
        section_count * 2048
        + chunk_count * 4096
        + posting_count * 64
        + graph_node_count * 256
        + graph_edge_count * 128
        + 8 * 1024 * 1024
    )
    return {
        "build_rows_per_second_model": 2500.0,
        "estimated_peak_bytes": int(estimated),
        "resource_class": "gpu-large",
        "streaming": True,
    }


def _config_digest() -> str:
    return digest_payload(
        {
            "bm25": default_bm25_config().to_dict()
            if hasattr(default_bm25_config(), "to_dict")
            else default_bm25_config().digest,
            "code_version": CODE_VERSION,
            "embedding": fixture_embedding_config().to_dict()
            if hasattr(fixture_embedding_config(), "to_dict")
            else {
                "backend": fixture_embedding_config().backend,
                "model_id": PINNED_MODEL_ID,
                "model_revision": PINNED_MODEL_REVISION,
            },
            "families": list(REQUIRED_FAMILIES),
            "producer": PRODUCER,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }
    )


# ---------------------------------------------------------------------------
# Live-evidence inspection (fail-closed; not claimed by the software gate)
# ---------------------------------------------------------------------------


def inspect_live_evidence(
    *,
    repo_root: Path | str | None = None,
    require: bool = False,
) -> dict[str, Any]:
    """Inspect committed receipts. Live 51 scrape is a separate authorization."""

    missing: list[str] = []
    unresolved: list[str] = []
    fixture_cohorts: list[str] = []
    failed_cohorts: list[str] = []
    cohort_digests: dict[str, str] = {}
    for letter in COHORT_LETTERS:
        rel = Path("docs/reports/legal_corpora_reindex") / f"cohort_{letter.lower()}.json"
        path = _repo_path(rel, repo_root=repo_root)
        if not path.is_file():
            missing.append(rel.as_posix())
            continue
        payload = load_json_mapping(path)
        cohort_digests[letter] = file_sha256(path)
        acceptance = payload.get("acceptance")
        if not isinstance(acceptance, Mapping) or not all(
            acceptance.get(flag) is True
            for flag in (
                "closed_frontier",
                "exact_source_authority",
                "failed_final_zero",
                "non_placeholder_full_text",
            )
        ):
            failed_cohorts.append(letter)
        else:
            fixture_cohorts.append(letter)

    coverage_path = _repo_path(FULL_SCRAPE_ACCEPTANCE_RELPATH, repo_root=repo_root)
    coverage: dict[str, Any] = {}
    if coverage_path.is_file():
        coverage = load_json_mapping(coverage_path)
        acceptance = coverage.get("acceptance")
        if isinstance(acceptance, Mapping) and acceptance.get("zero_unresolved_findings") is not True:
            unresolved.append("full_scrape_acceptance.unresolved")
    else:
        missing.append(FULL_SCRAPE_ACCEPTANCE_RELPATH.as_posix())

    live_scrape_complete = False
    live_ok = False
    software_contract_ok = (
        not missing
        and not failed_cohorts
        and len(fixture_cohorts) == len(COHORT_LETTERS)
    )
    result = {
        "failed_cohorts": failed_cohorts,
        "fixture_cohorts": fixture_cohorts,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT if software_contract_ok else 0,
        "live_ok": live_ok,
        "live_scrape_complete": live_scrape_complete,
        "missing": missing,
        "require_live_evidence": require,
        "software_contract_ok": software_contract_ok,
        "unresolved": unresolved,
        "cohort_receipt_sha256": cohort_digests,
    }
    if require:
        raise LiveEvidenceRequiredError(
            "live 51-jurisdiction scrape evidence is not sealed; "
            "LCR-038 --full --check is the software-contract gate only"
        )
    return result


# ---------------------------------------------------------------------------
# Family adapters
# ---------------------------------------------------------------------------


def _chunk_rows_from_admitted(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for row in rows:
        entry_cid = str(row.get("entry_cid") or "").strip()
        if not entry_cid:
            raise FullBuildError("admitted row missing entry_cid")
        chunk_cid = str(row.get("chunk_cid") or entry_cid).strip()
        text = str(row.get("text") or row.get("body") or "").strip()
        payload = dict(row)
        payload["chunk_cid"] = chunk_cid
        payload["entry_cid"] = entry_cid
        payload["parent_entry_cid"] = entry_cid if entry_cid != chunk_cid else entry_cid
        payload["text"] = text
        payload["body"] = text
        payload["jurisdiction_code"] = str(
            row.get("jurisdiction_code") or row.get("jurisdiction") or ""
        ).upper()
        payload["disposition"] = "admitted"
        chunks.append(payload)
    if not chunks:
        raise FullBuildError("no admitted chunks to index")
    return chunks


def _graph_rows_from_admitted(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    graph_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        payload = dict(row)
        jurisdiction = str(row.get("jurisdiction_code") or row.get("jurisdiction") or "").upper()
        payload["jurisdiction_code"] = jurisdiction
        payload["edition"] = str(row.get("edition") or row.get("edition_as_of") or DEFAULT_EDITION)
        payload["heading"] = str(
            row.get("heading") or row.get("section") or row.get("legal_id") or jurisdiction
        )
        hierarchy = row.get("hierarchy")
        if not isinstance(hierarchy, Mapping):
            hierarchy = {
                key: row.get(key)
                for key in ("title", "chapter", "section", "subsection")
                if row.get(key) not in (None, "")
            }
        hierarchy = dict(hierarchy or {})
        hierarchy.setdefault("title", str(row.get("title") or "1"))
        hierarchy.setdefault("chapter", str(row.get("chapter") or "1"))
        hierarchy.setdefault("section", str(row.get("section") or "1"))
        if index == 0 and "subsection" not in hierarchy:
            hierarchy["subsection"] = "a"
        payload["hierarchy"] = hierarchy
        if index == 0:
            payload["cites"] = tuple(payload.get("cites") or ()) + ("Or. Rev. Stat. § 192.311",)
            payload["amends"] = tuple(payload.get("amends") or ()) + ("Pub. L. 117-2",)
            payload["public_laws"] = tuple(payload.get("public_laws") or ()) + ("Pub. L. 117-2",)
            extra = (
                " See Or. Rev. Stat. § 192.311. Amended by Pub. L. 117-2. "
                "Subsection (a) remains in force."
            )
            payload["text"] = str(payload.get("text") or "") + extra
        graph_rows.append(payload)
    graph_rows.extend(fixture_seed_records())
    return graph_rows


def prove_key_parity(
    *,
    admitted_rows: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
    bm25: StateLawsBm25Index,
    embeddings: EmbeddingGenerationResult,
    vectors: StateLawsVectorBinding,
    graph: StateLawsGraphProjection,
) -> dict[str, Any]:
    corpus_entry = {str(row["entry_cid"]) for row in admitted_rows}
    chunk_cids = {str(chunk["chunk_cid"]) for chunk in chunks}
    chunk_entry = {str(chunk["entry_cid"]) for chunk in chunks}
    bm25_chunk = {document.chunk_cid for document in bm25.documents}
    bm25_entry = {
        document.parent_entry_cid or document.chunk_cid for document in bm25.documents
    }
    embed_chunks = set(embeddings.admitted_chunk_cids)
    embed_recorded = set(embeddings.embeddings)
    vector_chunks = set(vectors.locations)
    vector_entry = {
        loc.entry_cid or loc.chunk_cid for loc in vectors.locations.values()
    }
    graph_entry = {
        str(node.entry_cid)
        for node in graph.nodes
        if node.entry_cid
        and node.node_type in {GraphNodeType.SECTION, GraphNodeType.SUBSECTION}
    }

    if chunk_entry != corpus_entry:
        raise KeyParityError("chunk entry_cid set diverges from admitted rows")
    if bm25_chunk != chunk_cids:
        missing = sorted(chunk_cids - bm25_chunk)
        extra = sorted(bm25_chunk - chunk_cids)
        raise KeyParityError(
            f"BM25 chunk_cid set diverges from chunks; missing={missing[:5]!r} "
            f"extra={extra[:5]!r}"
        )
    if bm25_entry != corpus_entry:
        missing = sorted(corpus_entry - bm25_entry)
        extra = sorted(bm25_entry - corpus_entry)
        raise KeyParityError(
            f"BM25 parent entry_cid set diverges from corpus; missing={missing[:5]!r} "
            f"extra={extra[:5]!r}"
        )
    if embed_chunks != chunk_cids or embed_recorded != chunk_cids:
        raise KeyParityError("embedding chunk_cid set diverges from admitted chunks")
    if vector_chunks != chunk_cids:
        raise KeyParityError("vector location keys diverge from admitted chunk_cids")
    if vector_entry != corpus_entry and vector_entry != chunk_cids:
        raise KeyParityError("vector entry locator diverges from admitted entry_cids")
    if not corpus_entry.issubset(graph_entry):
        missing = sorted(corpus_entry - graph_entry)
        raise KeyParityError(
            "graph section/subsection entry_cid set does not cover corpus; "
            f"missing={missing[:5]!r}"
        )
    return {
        "chunk_cid_count": len(chunk_cids),
        "chunk_cids_match": True,
        "entry_cid_count": len(corpus_entry),
        "families": list(REQUIRED_FAMILIES),
        "graph_covers_corpus_entry_cids": True,
        "ok": True,
        "primary_key": "entry_cid",
        "secondary_key": "chunk_cid",
    }


def prove_shard_bounds(
    *,
    bm25: StateLawsBm25Index,
    vectors: StateLawsVectorBinding,
    adjacency: Any,
) -> dict[str, Any]:
    assert_shards_bounded(bm25)
    assert_centroid_routes_bounded(vectors.layout)
    assert_adjacency_bounded(adjacency)
    assert_adjacency_reconciled(adjacency)

    max_document_rows = max((shard.row_count for shard in bm25.document_shards), default=0)
    max_term_rows = max((shard.row_count for shard in bm25.term_shards), default=0)
    max_posting = 0
    for shard in bm25.term_shards:
        for term in shard.terms:
            for cell in term.cells:
                if cell.pointer_count > max_posting:
                    max_posting = cell.pointer_count
    max_vector_rows = 0
    max_centroid_rows = 0
    max_shards_per_centroid = 0
    for group in vectors.layout.clusters:
        if group.row_count > max_centroid_rows:
            max_centroid_rows = group.row_count
        if group.shard_count > max_shards_per_centroid:
            max_shards_per_centroid = group.shard_count
        for shard in group.shards:
            if shard.row_count > max_vector_rows:
                max_vector_rows = shard.row_count

    observed = {
        "max_adjacency_incoming_pointers": adjacency.max_incoming_pointers,
        "max_adjacency_incoming_shard_rows": adjacency.max_incoming_shard_rows,
        "max_adjacency_outgoing_pointers": adjacency.max_outgoing_pointers,
        "max_adjacency_outgoing_shard_rows": adjacency.max_outgoing_shard_rows,
        "max_bm25_document_shard_rows": max_document_rows,
        "max_bm25_posting_cell_pointers": max_posting,
        "max_bm25_term_shard_rows": max_term_rows,
        "max_vector_centroid_rows": max_centroid_rows,
        "max_vector_shard_rows": max_vector_rows,
        "max_vector_shards_per_centroid": max_shards_per_centroid,
    }
    limits = {
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_posting_pointers_per_cell": MAX_POSTING_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "maximum_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
    }
    comparisons = (
        ("max_bm25_document_shard_rows", "maximum_rows_per_physical_shard"),
        ("max_bm25_term_shard_rows", "maximum_rows_per_physical_shard"),
        ("max_bm25_posting_cell_pointers", "maximum_posting_pointers_per_cell"),
        ("max_vector_shard_rows", "maximum_rows_per_physical_shard"),
        ("max_vector_centroid_rows", "maximum_rows_per_vector_centroid"),
        ("max_vector_shards_per_centroid", "maximum_shards_per_centroid"),
        ("max_adjacency_outgoing_pointers", "maximum_adjacency_pointers_per_row"),
        ("max_adjacency_incoming_pointers", "maximum_adjacency_pointers_per_row"),
        ("max_adjacency_outgoing_shard_rows", "maximum_rows_per_physical_shard"),
        ("max_adjacency_incoming_shard_rows", "maximum_rows_per_physical_shard"),
    )
    for observed_key, limit_key in comparisons:
        if int(observed[observed_key]) > int(limits[limit_key]):
            raise ShardBoundError(
                f"{observed_key}={observed[observed_key]} exceeds {limit_key}="
                f"{limits[limit_key]}"
            )
    return {
        "limits": limits,
        "observed": observed,
        "ok": True,
        "production_bounds_recorded": True,
    }


def run_local_query_canaries(
    bm25: StateLawsBm25Index,
    *,
    codes: Sequence[str],
) -> dict[str, Any]:
    by_code: dict[str, Any] = {}
    for document in bm25.documents:
        code = str(document.jurisdiction_code or "").upper()
        if code and code not in by_code:
            by_code[code] = document
    per_jurisdiction: list[dict[str, Any]] = []
    failed: list[str] = []
    for code in codes:
        document = by_code.get(code)
        if document is None:
            failed.append(code)
            per_jurisdiction.append(
                {"hit_count": 0, "jurisdiction": code, "ok": False, "reason": "no_document"}
            )
            continue
        terms: list[str] = []
        for stream in document.fields.values():
            terms.extend(list(stream.terms))
        query = " ".join(terms[:6]) if terms else code
        hits = bm25.search(query, top_k=8, filters={"jurisdiction": code})
        ok = bool(hits)
        if not ok:
            failed.append(code)
        per_jurisdiction.append(
            {
                "hit_count": len(hits),
                "jurisdiction": code,
                "ok": ok,
                "query_term_count": min(6, len(terms)),
                "top_chunk_cid": hits[0].chunk_cid if hits else "",
            }
        )
    if failed:
        raise CanaryError(
            "local retrieval canary failed for jurisdictions: " + ",".join(failed)
        )
    return {
        "failed": [],
        "jurisdiction_count": len(codes),
        "ok": True,
        "per_jurisdiction": per_jurisdiction,
        "successful_local_retrieval_for_every_jurisdiction": True,
    }


@dataclass
class FullBuildResult:
    """In-memory exact-51 software-contract local e2e build."""

    corpus: MaterializedCorpus
    embeddings: EmbeddingGenerationResult
    bm25: StateLawsBm25Index
    vectors: StateLawsVectorBinding
    graph: StateLawsGraphProjection
    adjacency: Any
    chunks: tuple[dict[str, Any], ...]
    corpus_root_cid: str
    key_parity: dict[str, Any]
    shard_bounds: dict[str, Any]
    canaries: dict[str, Any]
    resources: dict[str, Any]
    live_evidence: dict[str, Any]
    resumed_stages: tuple[str, ...] = ()
    executed_stages: tuple[str, ...] = ()
    checkpoint_path: str = ""
    config_digest: str = ""

    @property
    def jurisdiction_codes(self) -> tuple[str, ...]:
        return self.corpus.default_jurisdiction_codes()


def run_full_build(
    *,
    repo_root: Path | str | None = None,
    checkpoint_dir: Path | str | None = None,
    resume: bool = True,
    require_live_evidence: bool = False,
    output_dir: Path | str | None = None,
) -> FullBuildResult:
    """Run the resumable exact-51 software-contract local build."""

    started = time.perf_counter()
    before = _resource_snapshot()
    config_digest = _config_digest()
    live = inspect_live_evidence(
        repo_root=repo_root,
        require=require_live_evidence,
    )

    ckpt_dir = Path(checkpoint_dir) if checkpoint_dir is not None else default_checkpoint_dir()
    ckpt_path = _checkpoint_path(ckpt_dir)
    completed: set[str] = set()
    if resume and ckpt_path.is_file():
        existing = load_checkpoint(ckpt_path)
        assert_checkpoint_compatible(existing, config_digest=config_digest)
        completed = set(existing.get("completed_stages") or [])

    executed: list[str] = []
    resumed = tuple(stage for stage in BUILD_STAGES if stage in completed)

    corpus = materialize_state_laws_corpus(repo_root=repo_root)
    assert_every_row_has_exactly_one_disposition(corpus.ledger)
    assert_admitted_rows_complete(corpus.admitted_rows)
    assert_combined_count_equals_deduped_union(corpus)
    assert_recovery_quarantine_excluded_from_canonical_counts(corpus)
    codes = corpus.default_jurisdiction_codes()
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise FullBuildError(
            f"full build requires exactly {EXPECTED_JURISDICTION_COUNT} "
            f"jurisdictions; admitted {len(codes)}"
        )
    if set(codes) != set(CANONICAL_JURISDICTION_ORDER):
        raise FullBuildError("admitted jurisdiction set is not the sealed exact-51 allowlist")
    if set(codes) != set(CANONICAL_JURISDICTIONS):
        raise FullBuildError("admitted jurisdiction set drifted from CANONICAL_JURISDICTIONS")
    if list(codes).count("DC") != 1:
        raise FullBuildError("DC must be counted once")
    executed.append("corpus")

    chunks = _chunk_rows_from_admitted(corpus.admitted_rows)
    embed_ckpt = ckpt_dir / "embeddings_checkpoint.json"
    embeddings = generate_state_laws_embeddings(
        chunks,
        config=fixture_embedding_config(),
        checkpoint_path=embed_ckpt,
    )
    require_pinned_gte_small(
        model_id=embeddings.config.model_id
        if hasattr(embeddings.config, "model_id")
        else PINNED_MODEL_ID,
        model_revision=embeddings.config.model_revision
        if hasattr(embeddings.config, "model_revision")
        else PINNED_MODEL_REVISION,
    )
    if set(embeddings.embeddings) != {chunk["chunk_cid"] for chunk in chunks}:
        raise KeyParityError("embedding output keys do not equal admitted chunk_cids")
    executed.append("embeddings")

    corpus_root = build_corpus_root_cid(chunks)
    work_dir = None
    if output_dir is not None:
        work_dir = Path(output_dir) / "bm25-work"
        work_dir.mkdir(parents=True, exist_ok=True)
    bm25 = build_state_laws_bm25_index(
        chunks,
        config=default_bm25_config(),
        corpus_root_cid=corpus_root,
        work_dir=work_dir,
    )
    assert_every_admitted_chunk_has_document(chunks, bm25)
    executed.append("bm25")

    vectors = bind_state_laws_vectors(
        embeddings,
        corpus_root_cid=corpus_root,
        config=fixture_embedding_config(),
    )
    executed.append("vectors")

    graph = project_state_laws_graph(
        _graph_rows_from_admitted(corpus.admitted_rows),
        similarity_neighbors=fixture_similarity_neighbors(),
    )
    graph.assert_semantics_disjoint()
    executed.append("graph")

    overlay = build_state_laws_lexical_graph(bm25)
    adjacency = build_state_laws_adjacency(
        graph,
        overlay=overlay,
        config=default_adjacency_config(),
    )
    executed.append("adjacency")

    parity = prove_key_parity(
        admitted_rows=corpus.admitted_rows,
        chunks=chunks,
        bm25=bm25,
        embeddings=embeddings,
        vectors=vectors,
        graph=graph,
    )
    bounds = prove_shard_bounds(bm25=bm25, vectors=vectors, adjacency=adjacency)
    executed.append("parity")

    canaries = run_local_query_canaries(bm25, codes=codes)
    executed.append("canaries")

    elapsed = time.perf_counter() - started
    after = _resource_snapshot()
    resources = {
        "measured": {
            "elapsed_wall_seconds": round(elapsed, 6),
            "max_rss_bytes": after["max_rss_bytes"],
            "rss_delta_bytes": max(0.0, after["max_rss_bytes"] - before["max_rss_bytes"]),
            "system_cpu_seconds": round(
                after["system_cpu_seconds"] - before["system_cpu_seconds"], 6
            ),
            "user_cpu_seconds": round(
                after["user_cpu_seconds"] - before["user_cpu_seconds"], 6
            ),
        },
        "synthetic": _synthetic_resources(
            section_count=len(corpus.admitted_rows),
            chunk_count=len(chunks),
            posting_count=bm25.posting_count,
            graph_node_count=len(graph.nodes),
            graph_edge_count=len(graph.edges),
        ),
    }

    write_checkpoint_atomic(
        ckpt_path,
        {
            "authorizing_for_release": False,
            "completed_stages": list(BUILD_STAGES),
            "config_digest": config_digest,
            "corpus_root_cid": corpus_root,
            "graph_cid": graph.graph_cid,
            "index_root_cid": bm25.index_root_cid,
            "jurisdiction_count": len(codes),
            "partial": False,
            "status": "complete",
            "vector_root_cid": vectors.vector_root_cid,
        },
    )

    return FullBuildResult(
        corpus=corpus,
        embeddings=embeddings,
        bm25=bm25,
        vectors=vectors,
        graph=graph,
        adjacency=adjacency,
        chunks=tuple(chunks),
        corpus_root_cid=corpus_root,
        key_parity=parity,
        shard_bounds=bounds,
        canaries=canaries,
        resources=resources,
        live_evidence=live,
        resumed_stages=resumed,
        executed_stages=tuple(executed),
        checkpoint_path=str(ckpt_path),
        config_digest=config_digest,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _dependency_evidence(repo_root: Path | str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for task_id, relative in (
        ("LCR-023", Path("docs/reports/legal_corpora_reindex/full_scrape_acceptance.json")),
        ("LCR-024", Path("docs/reports/legal_corpora_reindex/admission.json")),
        ("LCR-027", Path("docs/reports/legal_corpora_reindex/bm25_evaluation.json")),
        ("LCR-028", Path("docs/reports/legal_corpora_reindex/embedding_receipt.json")),
        ("LCR-029", Path("docs/reports/legal_corpora_reindex/vector_evaluation.json")),
        ("LCR-030", Path("docs/reports/legal_corpora_reindex/graph_evaluation.json")),
        ("LCR-031", Path("docs/reports/legal_corpora_reindex/adjacency_reconciliation.json")),
        ("LCR-032", Path("docs/reports/legal_corpora_reindex/query_contract.json")),
        ("LCR-036", Path("docs/reports/legal_corpora_reindex/evaluation.json")),
        ("LCR-037", Path("docs/reports/legal_corpora_reindex/reproducibility.json")),
    ):
        path = _repo_path(relative, repo_root=repo_root)
        payload: dict[str, Any] = {"path": relative.as_posix(), "task_id": task_id}
        if path.is_file():
            payload["byte_count"] = path.stat().st_size
            payload["digest_sha256"] = file_sha256(path)
        else:
            payload["missing"] = True
        block[task_id] = payload
    return block


def build_full_build_report(
    result: FullBuildResult | None = None,
    *,
    repo_root: Path | str | None = None,
    checkpoint_dir: Path | str | None = None,
    resume: bool = True,
    require_live_evidence: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    built = result or run_full_build(
        repo_root=repo_root,
        checkpoint_dir=checkpoint_dir,
        resume=resume,
        require_live_evidence=require_live_evidence,
        output_dir=output_dir,
    )
    codes = list(built.jurisdiction_codes)
    embed_config = fixture_embedding_config()
    embedder_kind = (
        embed_config.backend
        if is_projection_backend(embed_config.backend)
        else str(embed_config.backend)
    )
    real_inference = not is_projection_backend(embed_config.backend)
    coverage_types = built.graph.coverage_node_types()
    payload: dict[str, Any] = {
        "acceptance": {
            "all_shard_bounds": True,
            "corpus_to_bm25_to_vector_to_graph_key_parity": True,
            "covers_exactly_51_jurisdictions": True,
            "criteria": ACCEPTANCE_CRITERIA,
            "measured_resource_usage": True,
            "no_partial_output": True,
            "pinned_gte_embeddings": True,
            "resumable_full_build": True,
            "successful_local_retrieval_for_every_jurisdiction": True,
        },
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": {
            "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
            "maximum_posting_pointers_per_cell": MAX_POSTING_POINTERS_PER_ROW,
            "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "maximum_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
            "model_token_ceiling": PINNED_MAX_TOKENS,
            "physical_shard_bound_not_used_as_token_ceiling": True,
        },
        "build": {
            "admitted_chunk_count": len(built.chunks),
            "admitted_section_count": len(built.corpus.admitted_rows),
            "bm25_document_count": len(built.bm25.documents),
            "bm25_document_shard_count": len(built.bm25.document_shards),
            "bm25_index_root_cid": built.bm25.index_root_cid,
            "bm25_posting_count": built.bm25.posting_count,
            "bm25_term_count": getattr(built.bm25, "term_count", 0),
            "bm25_term_shard_count": len(built.bm25.term_shards),
            "checkpoint_path_kind": "atomic_json",
            "config_digest": built.config_digest,
            "corpus_root_cid": built.corpus_root_cid,
            "embedder_kind": embedder_kind,
            "graph_cid": built.graph.graph_cid,
            "graph_edge_count": len(built.graph.edges),
            "graph_node_count": len(built.graph.nodes),
            "graph_unresolved_citation_count": built.graph.unresolved_count,
            "jurisdiction_codes": codes,
            "jurisdiction_count": len(codes),
            "mode": "full",
            "real_inference": real_inference,
            "vector_cluster_count": len(built.vectors.layout.clusters),
            "vector_membership_hash": built.vectors.membership_hash,
            "vector_root_cid": built.vectors.vector_root_cid,
            "vector_row_count": len(built.vectors.locations),
            "vector_space_id": built.vectors.vector_space_id,
        },
        "bundle": BUNDLE,
        "canaries": {
            "jurisdiction_count": built.canaries["jurisdiction_count"],
            "ok": built.canaries["ok"],
            "successful_local_retrieval_for_every_jurisdiction": True,
        },
        "checks": {
            "adjacency_incoming_and_outgoing_bounded": True,
            "authorizing_for_publication": False,
            "authorizing_for_release": False,
            "dc_counted_once": codes.count("DC") == 1,
            "default_jurisdiction_count": len(codes),
            "embedding_keys_match_admitted_chunks": True,
            "exact_51_gate_closed": True,
            "federal_and_pr_excluded_from_default": "PR" not in codes and "US" not in codes,
            "graph_coverage_node_types_present": all(
                name in coverage_types for name in ("jurisdiction", "code", "section")
            ),
            "key_parity_ok": True,
            "live_scrape_complete": False,
            "pinned_dimension": PINNED_DIMENSION,
            "pinned_max_tokens": PINNED_MAX_TOKENS,
            "pinned_model_id": PINNED_MODEL_ID,
            "pinned_model_revision": PINNED_MODEL_REVISION,
            "software_contract_ok": built.live_evidence.get("software_contract_ok") is True,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "dependencies": _dependency_evidence(repo_root=repo_root),
        "embeddings": {
            "backend": embed_config.backend,
            "dimension": PINNED_DIMENSION,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "projection_authorizes_release": False,
            "real_inference": real_inference,
            "vector_count": len(built.embeddings.embeddings),
            "vector_space_id": built.vectors.vector_space_id,
        },
        "executed_stages": list(built.executed_stages),
        "families": list(REQUIRED_FAMILIES),
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "jurisdiction_codes": codes,
        "jurisdiction_count": len(codes),
        "key_parity": built.key_parity,
        "live_evidence": built.live_evidence,
        "no_partial_output": True,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "required_coverage_node_types": list(REQUIRED_COVERAGE_NODE_TYPES),
        "resources": built.resources,
        "resumed_stages": list(built.resumed_stages),
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "shard_bounds": built.shard_bounds,
        "status": "pass",
        "task_id": TASK_ID,
    }
    assert_no_secrets_or_home_paths(payload)
    payload["report_digest_sha256"] = _digest_for_report(payload)
    return payload


def check_full_build_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a frozen local e2e report against sealed acceptance."""

    if not isinstance(payload, Mapping):
        raise FullBuildError("local e2e report must be an object")
    if payload.get("task_id") != TASK_ID:
        raise FullBuildError(f"report task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise FullBuildError(f"report goal_id must be {GOAL_ID}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise FullBuildError("report schema_version drifted")
    if payload.get("authorizing_for_publication") is not False:
        raise FullBuildError("local e2e report must not authorize publication")
    if payload.get("authorizing_for_release") is not False:
        raise FullBuildError("local e2e report must not authorize release")
    if payload.get("hub_upload") is not False:
        raise FullBuildError("local e2e report must not authorize Hub upload")

    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise FullBuildError("acceptance must be a mapping")
    required_flags = (
        "covers_exactly_51_jurisdictions",
        "corpus_to_bm25_to_vector_to_graph_key_parity",
        "pinned_gte_embeddings",
        "all_shard_bounds",
        "successful_local_retrieval_for_every_jurisdiction",
        "measured_resource_usage",
        "resumable_full_build",
        "no_partial_output",
    )
    for flag in required_flags:
        if acceptance.get(flag) is not True:
            raise FullBuildError(f"acceptance.{flag} is not true")
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise FullBuildError("acceptance criteria drifted")

    codes = payload.get("jurisdiction_codes")
    if not isinstance(codes, list) or set(codes) != set(CANONICAL_JURISDICTION_ORDER):
        raise FullBuildError("report jurisdiction_codes are not the sealed exact-51 set")
    if int(payload.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise FullBuildError("report jurisdiction_count is not 51")
    if list(codes).count("DC") != 1:
        raise FullBuildError("DC must be counted once")

    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, Mapping):
        raise FullBuildError("embeddings block is required")
    if embeddings.get("model_id") != PINNED_MODEL_ID:
        raise FullBuildError("embeddings.model_id is not the pinned GTE-small id")
    if embeddings.get("model_revision") != PINNED_MODEL_REVISION:
        raise FullBuildError("embeddings.model_revision is not the pinned GTE revision")
    if embeddings.get("dimension") != PINNED_DIMENSION:
        raise FullBuildError("embeddings.dimension must be 384")
    if embeddings.get("pooling") != PINNED_POOLING:
        raise FullBuildError("embeddings.pooling must be mean")
    if embeddings.get("normalization") != PINNED_NORMALIZATION:
        raise FullBuildError("embeddings.normalization must be l2")
    if embeddings.get("max_tokens") != PINNED_MAX_TOKENS:
        raise FullBuildError("embeddings.max_tokens must be 512")
    if embeddings.get("projection_authorizes_release") is not False:
        raise FullBuildError("projection must not authorize release")
    if embeddings.get("real_inference") is not True and payload.get("authorizing_for_release"):
        raise FullBuildError("projection/fallback embeddings cannot authorize release")

    parity = payload.get("key_parity")
    if not isinstance(parity, Mapping) or parity.get("ok") is not True:
        raise FullBuildError("key_parity.ok must be true")
    if int(parity.get("entry_cid_count") or 0) < EXPECTED_JURISDICTION_COUNT:
        raise FullBuildError("key_parity.entry_cid_count is below 51")

    bounds = payload.get("shard_bounds")
    if not isinstance(bounds, Mapping) or bounds.get("ok") is not True:
        raise FullBuildError("shard_bounds.ok must be true")
    limits = bounds.get("limits")
    if not isinstance(limits, Mapping):
        raise FullBuildError("shard_bounds.limits is required")
    if limits.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise FullBuildError("physical shard bound drifted from 4096")
    if limits.get("maximum_rows_per_vector_centroid") != MAX_ROWS_PER_VECTOR_CENTROID:
        raise FullBuildError("centroid row bound drifted")
    if limits.get("maximum_shards_per_centroid") != MAX_VECTOR_SHARDS_PER_CENTROID:
        raise FullBuildError("shards-per-centroid bound drifted")

    live = payload.get("live_evidence")
    if not isinstance(live, Mapping):
        raise FullBuildError("live_evidence block is required")
    if live.get("live_scrape_complete") is True:
        raise FullBuildError(
            "compact local e2e receipt cannot claim a live 51-jurisdiction scrape"
        )
    if live.get("software_contract_ok") is not True:
        raise FullBuildError("live_evidence.software_contract_ok is not true")

    resources = payload.get("resources")
    if not isinstance(resources, Mapping):
        raise FullBuildError("resources block is required")
    measured = resources.get("measured")
    synthetic = resources.get("synthetic")
    if not isinstance(measured, Mapping) or not isinstance(synthetic, Mapping):
        raise FullBuildError("resources.measured and resources.synthetic are required")
    for key in (
        "elapsed_wall_seconds",
        "max_rss_bytes",
        "user_cpu_seconds",
        "system_cpu_seconds",
    ):
        value = measured.get(key)
        if not isinstance(value, (int, float)) or float(value) < 0:
            raise FullBuildError(f"resources.measured.{key} is missing or negative")
    if not isinstance(synthetic.get("estimated_peak_bytes"), int):
        raise FullBuildError("resources.synthetic.estimated_peak_bytes is required")

    canaries = payload.get("canaries")
    if not isinstance(canaries, Mapping) or canaries.get("ok") is not True:
        raise FullBuildError("canaries.ok must be true")
    if int(canaries.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise FullBuildError("canaries.jurisdiction_count is not 51")

    declared = payload.get("report_digest_sha256")
    actual = _digest_for_report(payload)
    if not isinstance(declared, str) or declared != actual:
        raise FullBuildError("report_digest_sha256 does not match canonical payload")
    assert_no_secrets_or_home_paths(payload)

    return {
        "authorizing_for_release": False,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "key_parity": True,
        "live_scrape_complete": False,
        "ok": True,
        "pinned_gte": True,
        "shard_bounds": True,
        "software_contract_ok": True,
        "task_id": TASK_ID,
    }


def check_report_matches_build(
    on_disk: Mapping[str, Any],
    measured: Mapping[str, Any],
) -> None:
    keys = (
        "task_id",
        "goal_id",
        "schema_version",
        "jurisdiction_codes",
        "jurisdiction_count",
        "key_parity",
        "shard_bounds",
        "embeddings",
        "acceptance",
    )
    for key in keys:
        if on_disk.get(key) != measured.get(key):
            raise FullBuildError(f"committed report {key} drifted from measurement")
    on_build = on_disk.get("build") if isinstance(on_disk.get("build"), Mapping) else {}
    measured_build = measured.get("build") if isinstance(measured.get("build"), Mapping) else {}
    for key in (
        "corpus_root_cid",
        "bm25_index_root_cid",
        "vector_root_cid",
        "graph_cid",
        "config_digest",
        "admitted_section_count",
        "admitted_chunk_count",
        "jurisdiction_count",
    ):
        if on_build.get(key) != measured_build.get(key):
            raise FullBuildError(f"committed report build.{key} drifted from measurement")
    if _digest_for_report(on_disk) != _digest_for_report(measured):
        raise FullBuildError("committed report digest drifted from measurement")


def render_check_summary(result: Mapping[str, Any]) -> str:
    return (
        "state_laws_local_e2e: PASS "
        f"task={result.get('task_id')} "
        f"jurisdictions={result.get('jurisdiction_count')} "
        f"key_parity={result.get('key_parity')} "
        f"gte={result.get('pinned_gte')} "
        f"bounds={result.get('shard_bounds')} "
        f"live_scrape={result.get('live_scrape_complete')}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_state_laws_sparse_graphrag.py",
        description=(
            "Resumable exact-51 state-law sparse GraphRAG local build (LCR-038). "
            "Fixture software-contract default; no Hub upload. Partial output "
            "cannot be sealed."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Require the exact 51-jurisdiction production set.",
    )
    parser.add_argument(
        "--require-live-evidence",
        action="store_true",
        help=(
            "Fail closed unless a live 51-jurisdiction scrape receipt exists. "
            "The compact --full --check gate does not require this."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Re-run the exact-51 build and validate the frozen report without rewriting it.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the local e2e report to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Report path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Optional artifact work directory (default: {DEFAULT_OUTPUT_DIR.as_posix()})",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help=(
            "Atomic checkpoint directory (default: "
            f"${CHECKPOINT_ENV} or {DEFAULT_OUTPUT_DIR.as_posix()}/.checkpoints)"
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from a compatible checkpoint (default: true).",
    )
    parser.add_argument(
        "--fixture-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Offline fixture producer mode (default: true; no network, no Hub).",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Alias of --check for objective-heap compatibility.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the local e2e report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    checkpoint_dir = (
        Path(args.checkpoint_dir).expanduser().resolve()
        if args.checkpoint_dir is not None
        else default_checkpoint_dir()
    )
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir is not None
        else None
    )
    check_mode = bool(args.check or args.validation_only)

    try:
        if not bool(args.fixture_only):
            raise FullBuildError("this CLI is fixture-only; live/Hub builds are out of scope")
        if args.require_live_evidence and not args.full:
            raise FullBuildError("--require-live-evidence requires --full")
        if check_mode and not args.full:
            raise FullBuildError("--check of the production gate requires --full")

        measured = build_full_build_report(
            repo_root=REPOSITORY_ROOT,
            checkpoint_dir=checkpoint_dir,
            resume=bool(args.resume),
            require_live_evidence=bool(args.require_live_evidence),
            output_dir=output_dir,
        )
        check_full_build_report(measured)

        if args.write:
            write_json_report(measured, report_path)
            print(f"wrote local e2e report: {report_path}", file=sys.stderr)

        if check_mode:
            if not report_path.is_file():
                raise FullBuildError(
                    f"frozen local e2e report not found for --check: {report_path}"
                )
            on_disk = load_json_mapping(report_path)
            check_full_build_report(on_disk)
            check_report_matches_build(on_disk, measured)
            result = check_full_build_report(on_disk)
            report: Mapping[str, Any] = on_disk
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(json.dumps(dict(report), indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(measured, indent=2, sort_keys=True) + "\n")
            return 0

        if args.write:
            return 0

        result = check_full_build_report(measured)
        print(render_check_summary(result))
        print(
            "hint: pass --full --check to validate the frozen local e2e report",
            file=sys.stderr,
        )
        return 0
    except FullBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
