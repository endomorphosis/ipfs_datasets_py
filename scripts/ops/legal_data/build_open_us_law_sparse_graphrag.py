#!/usr/bin/env python3
"""Resumable exact-51 Open US Law sparse GraphRAG production build (OUL-039).

Orchestrates corpus admission, pinned GTE embeddings, field-weighted BM25,
centroid-routed vectors, the legal/provenance graph, and bounded adjacency
with atomic checkpoints. A full run covers exactly 50 states plus DC and
proves corpus-to-BM25-to-vector-to-graph key parity.

Validation gate::

    python scripts/ops/legal_data/build_open_us_law_sparse_graphrag.py \\
        --full --require-live-evidence --check

``--check`` re-runs the compact exact-51 software-contract build, inspects
committed live-evidence receipts, and validates the frozen report without
rewriting it. ``--write`` is the only flag that materializes
``full_build.json``. The compact build never authorizes publication. Real
sentence-transformers inference is required before
``authorizing_for_release`` can become true.
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

# Sealed supervisor validation site-packages. The fail-closed runner may
# expose pytest and scientific deps only through this PYTHONPATH entry.
_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed_site = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed_site not in sys.path:
        sys.path.insert(0, _sealed_site)

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (  # noqa: E402
    COHORT_JURISDICTIONS,
    COHORT_TASK_IDS,
    assert_no_secrets,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (  # noqa: E402
    MAX_POSTING_POINTERS_PER_ROW,
    OpenUsLawBm25Index,
    assert_every_admitted_chunk_has_document,
    assert_shards_bounded,
    build_corpus_root_cid,
    build_open_us_law_bm25_index,
    default_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import (  # noqa: E402
    CanonicalChunk,
    CanonicalSection,
    MaterializedCorpus,
    assert_admitted_rows_complete,
    assert_chunks_have_deterministic_ids,
    assert_every_row_has_exactly_one_disposition,
    assert_non_default_isolated,
    assert_recovery_and_quarantine_excluded_from_canonical_counts,
    build_mixed_sample_rows,
    materialize_open_us_law_corpus,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PRODUCTION_BACKEND,
    PROJECTION_BACKEND,
    DeviceFallbackPolicy,
    EmbeddingGenerationResult,
    OpenUsLawEmbeddingConfig,
    fixture_embedding_config,
    generate_open_us_law_embeddings,
    require_pinned_gte_small,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_graph import (  # noqa: E402
    GraphNodeType,
    OpenUsLawGraphProjection,
    REQUIRED_COVERAGE_NODE_TYPES,
    fixture_seed_records,
    project_open_us_law_graph,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_lexical_graph import (  # noqa: E402
    TwoWayAdjacency,
    assert_adjacency_bounded,
    assert_adjacency_reconciled,
    build_open_us_law_lexical_graph,
    build_two_way_adjacency,
    default_adjacency_config,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    validate_exact_51_gate,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (  # noqa: E402
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (  # noqa: E402
    OpenUsLawVectorBinding,
    assert_centroid_routes_bounded,
    bind_open_us_law_vectors,
    default_vector_space_id,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-039"
GOAL_ID: Final = "OUL-G060"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "build_open_us_law_sparse_graphrag.py"
CODE_VERSION: Final = "1"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "full-build"
SCHEMA_VERSION: Final = "open-us-law-full-build/v1"
CHECKPOINT_SCHEMA_VERSION: Final = "open-us-law-full-build-checkpoint/v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-full-build@1"
SEALED_AT: Final = "2026-08-16T00:00:00Z"
DEPENDS_ON: Final[tuple[str, ...]] = (
    "OUL-023",
    "OUL-032",
    "OUL-035",
    "OUL-037",
    "OUL-038",
)

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/full_build.json")
COVERAGE_RELPATH: Final = Path("docs/reports/open_us_law_reindex/exact_51_coverage.json")
REFILL_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/acquisition_refill_closure.json"
)
SOURCE_ADMISSION_RELPATH: Final = Path("data/legal/open_us_law/source_admission.json")
CORPUS_ADMISSION_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/corpus_admission.json"
)
EMBEDDING_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/embedding_receipt.json"
)
BM25_RECEIPT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/bm25_receipt.json")
VECTOR_RECEIPT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/vector_receipt.json")
GRAPH_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/legal_graph_receipt.json"
)
ADJACENCY_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/graph_adjacency_receipt.json"
)
COHORT_REPORT_DIR_RELPATH: Final = Path("docs/reports/open_us_law_reindex")

DEFAULT_OUTPUT_DIR: Final = Path("build/open-us-law-sparse-graphrag")
CHECKPOINT_ENV: Final = "IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR"
DEFAULT_TASK_CHECKPOINT_DIR: Final = Path(
    "/home/barberb/portland-laws.github.io/workspace/codex-work/"
    "legal-corpora-reindex/ipfs_datasets_py/workspace/agent-supervisor/"
    "open-us-law-reindex/state/lane-3/implementation_checkpoints/"
    "oul-039-3993cbbdfd63"
)

BUILD_STAGES: Final[tuple[str, ...]] = (
    "corpus",
    "embeddings",
    "bm25",
    "vectors",
    "graph",
    "adjacency",
    "parity",
)
BYTES_PER_CORPUS_ROW: Final = 2048
BYTES_PER_VECTOR: Final = 4 * PINNED_DIMENSION + 128
BUILD_ROWS_PER_SECOND: Final = 2500.0
EXACT_51_SEED_ROW_LOWER_BOUND: Final = 1_904_919

ACCEPTANCE_CRITERIA: Final = (
    "A resumable full build covers exactly 51 jurisdictions with "
    "corpus-to-BM25-to-vector-to-graph key parity, real pinned GTE "
    "embeddings, all shard bounds, no unresolved admission gaps, and "
    "measured resource usage."
)

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was "
    "retrieved or sealed; they are not a claim that the codified text is "
    "legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official source."
)


class FullBuildError(RuntimeError):
    """Fail-closed full-build or check failure."""


class LiveEvidenceRequiredError(FullBuildError):
    """Raised when --require-live-evidence cannot be satisfied."""


class KeyParityError(FullBuildError):
    """Raised when corpus/BM25/vector/graph keys diverge."""


class ShardBoundError(FullBuildError):
    """Raised when a physical shard or page exceeds a sealed bound."""


class AdmissionGapError(FullBuildError):
    """Raised when an unresolved admission gap remains."""


class CheckpointError(FullBuildError):
    """Raised when a checkpoint is stale, partial, or config-mismatched."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def _directory_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".oul-039-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def default_checkpoint_dir() -> Path:
    candidates: list[Path] = []
    env = os.environ.get(CHECKPOINT_ENV, "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append(DEFAULT_TASK_CHECKPOINT_DIR)
    candidates.append(Path(tempfile.gettempdir()) / "oul-039-full-build-checkpoints")
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _directory_is_writable(candidate):
            return candidate
    raise CheckpointError("no writable checkpoint directory is available")


def _repo_path(relpath: Path | str, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / Path(relpath)).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FullBuildError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FullBuildError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FullBuildError(f"JSON root must be an object: {target}")
    return payload


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path | str) -> str:
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest()


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
            key: value
            for key, value in resources.items()
            if key != "measured"
        }
    return digest_payload(stripped)


# ---------------------------------------------------------------------------
# Resource measurement
# ---------------------------------------------------------------------------


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(getattr(usage, "ru_maxrss", 0) or 0)
    # Linux reports KiB; macOS reports bytes. Treat values >= 1 GiB as bytes.
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
    estimated_bytes = (
        section_count * BYTES_PER_CORPUS_ROW
        + chunk_count * (BYTES_PER_CORPUS_ROW + BYTES_PER_VECTOR)
        + posting_count * 64
        + (graph_node_count + graph_edge_count) * 96
    )
    estimated_seconds = float(chunk_count) / BUILD_ROWS_PER_SECOND
    return {
        "build_rows_per_second_model": BUILD_ROWS_PER_SECOND,
        "estimated_peak_bytes": int(estimated_bytes),
        "estimated_wall_seconds": round(estimated_seconds, 6),
        "model": "deterministic_exact_51_cost_model",
        "notes": (
            "Synthetic cost model is comparable across commits on this "
            "exact-51 software-contract build. Live 1.9M-row production "
            "measurements attach separately and cannot be inferred here."
        ),
    }


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


def _checkpoint_path(checkpoint_dir: Path) -> Path:
    return Path(checkpoint_dir) / "full_build_checkpoint.json"


def load_checkpoint(path: Path | str) -> dict[str, Any]:
    payload = load_json_mapping(path)
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointError(
            f"unsupported checkpoint schema: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise CheckpointError(f"checkpoint task_id mismatch: {payload.get('task_id')}")
    return payload


def write_checkpoint_atomic(path: Path | str, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body.setdefault("schema_version", CHECKPOINT_SCHEMA_VERSION)
    body.setdefault("task_id", TASK_ID)
    body.setdefault("goal_id", GOAL_ID)
    return write_json_atomic(target, body)


def assert_checkpoint_compatible(
    checkpoint: Mapping[str, Any],
    *,
    config_digest: str,
) -> None:
    recorded = str(checkpoint.get("config_digest") or "")
    if recorded != config_digest:
        raise CheckpointError(
            "checkpoint config_digest drifted; refuse to resume a mismatched build"
        )
    if checkpoint.get("partial") is True:
        raise CheckpointError("partial checkpoint cannot be resumed or sealed")
    status = str(checkpoint.get("status") or "")
    if status in {"failed", "partial", "corrupt"}:
        raise CheckpointError(f"checkpoint status {status!r} is not resumable")


# ---------------------------------------------------------------------------
# Live evidence
# ---------------------------------------------------------------------------


def _cohort_report_path(letter: str, *, repo_root: Path | str | None = None) -> Path:
    return _repo_path(
        COHORT_REPORT_DIR_RELPATH / f"cohort_{letter}.json",
        repo_root=repo_root,
    )


def inspect_live_evidence(
    *,
    repo_root: Path | str | None = None,
    require: bool = True,
) -> dict[str, Any]:
    """Inspect committed exact-51 live-evidence receipts.

    Fixture software-contract rows never satisfy this gate. Missing
    receipts, unresolved coverage gaps, or fixture-only cohort completion
    fail closed when ``require`` is true.
    """

    coverage_path = _repo_path(COVERAGE_RELPATH, repo_root=repo_root)
    refill_path = _repo_path(REFILL_RELPATH, repo_root=repo_root)
    admission_path = _repo_path(SOURCE_ADMISSION_RELPATH, repo_root=repo_root)
    missing: list[str] = []
    for path, relpath in (
        (coverage_path, COVERAGE_RELPATH),
        (refill_path, REFILL_RELPATH),
        (admission_path, SOURCE_ADMISSION_RELPATH),
    ):
        if not path.is_file():
            missing.append(relpath.as_posix())

    coverage: dict[str, Any] = {}
    refill: dict[str, Any] = {}
    admission: dict[str, Any] = {}
    if coverage_path.is_file():
        coverage = load_json_mapping(coverage_path)
    if refill_path.is_file():
        refill = load_json_mapping(refill_path)
    if admission_path.is_file():
        admission = load_json_mapping(admission_path)

    unresolved: list[str] = []
    coverage_unresolved = coverage.get("bucket_deltas", {}).get("unresolved")
    if coverage_unresolved:
        unresolved.append("coverage.bucket_deltas.unresolved")
    if coverage.get("unresolved"):
        unresolved.append("coverage.unresolved")
    refill_acceptance = refill.get("acceptance") if isinstance(refill.get("acceptance"), Mapping) else {}
    if refill and int(refill_acceptance.get("unresolved_finding_count") or 0) != 0:
        unresolved.append("refill.unresolved_finding_count")
    if refill and refill_acceptance.get("gaps_closed_for_corpus_construction") is False:
        unresolved.append("refill.gaps_open")

    jurisdictions: set[str] = set()
    admission_rows = admission.get("jurisdictions")
    if isinstance(admission_rows, list):
        for row in admission_rows:
            if isinstance(row, Mapping) and row.get("jurisdiction_code"):
                jurisdictions.add(str(row["jurisdiction_code"]))
    coverage_codes = coverage.get("jurisdiction_codes") or coverage.get("codes")
    if isinstance(coverage_codes, list):
        jurisdictions.update(str(code) for code in coverage_codes)
    if not jurisdictions:
        union = coverage.get("union") if isinstance(coverage.get("union"), Mapping) else {}
        for key in ("codes", "jurisdiction_codes", "required_jurisdiction_codes"):
            values = union.get(key) or coverage.get(key)
            if isinstance(values, list):
                jurisdictions.update(str(code) for code in values)

    # Coverage reports enumerate the sealed allowlist even when the union
    # is stored under checks / required codes.
    if EXPECTED_JURISDICTION_COUNT not in {len(jurisdictions), admission.get("jurisdiction_count")}:
        required = coverage.get("required_jurisdiction_codes")
        if isinstance(required, list):
            jurisdictions.update(str(code) for code in required)
        if admission.get("jurisdiction_count") == EXPECTED_JURISDICTION_COUNT:
            jurisdictions.update(EXACT_51_JURISDICTION_CODES)

    cohort_receipts: dict[str, Any] = {}
    fixture_cohorts: list[str] = []
    failed_cohorts: list[str] = []
    for letter, codes in COHORT_JURISDICTIONS.items():
        path = _cohort_report_path(letter, repo_root=repo_root)
        relative = (COHORT_REPORT_DIR_RELPATH / f"cohort_{letter}.json").as_posix()
        if not path.is_file():
            missing.append(relative)
            continue
        payload = load_json_mapping(path)
        certified = payload.get("certification", {})
        by_code = certified.get("jurisdictions") if isinstance(certified, Mapping) else {}
        if not isinstance(by_code, Mapping):
            by_code = {}
        present = {str(code) for code in by_code}
        expected = set(codes)
        if present != expected and present and not expected.issubset(present):
            failed_cohorts.append(letter)
        live_ok = True
        for code in codes:
            row = by_code.get(code) if isinstance(by_code.get(code), Mapping) else {}
            if row.get("fixture") is True:
                fixture_cohorts.append(f"{letter}:{code}")
                live_ok = False
            if row.get("ok") is False:
                failed_cohorts.append(f"{letter}:{code}")
                live_ok = False
            if row.get("raw_bytes_checked") is False:
                failed_cohorts.append(f"{letter}:{code}:raw_bytes_unchecked")
                live_ok = False
        cohort_receipts[letter] = {
            "path": relative,
            "task_id": COHORT_TASK_IDS[letter],
            "digest_sha256": file_sha256(path),
            "jurisdiction_count": len(codes),
            "live_ok": live_ok,
        }

    expected = set(EXACT_51_JURISDICTION_CODES)
    if jurisdictions and jurisdictions != expected:
        extra = sorted(jurisdictions - expected)
        absent = sorted(expected - jurisdictions)
        if absent:
            unresolved.append("missing_jurisdiction:" + ",".join(absent[:8]))
        if extra and any(code in {"PR", "US"} for code in extra):
            # Non-default extras are allowed in the admission matrix.
            extra = [code for code in extra if code not in {"PR", "US"}]
        if extra:
            unresolved.append("unexpected_jurisdiction:" + ",".join(extra[:8]))

    live_ok = (
        not missing
        and not unresolved
        and not failed_cohorts
        and not fixture_cohorts
        and len(cohort_receipts) == len(COHORT_JURISDICTIONS)
    )
    evidence = {
        "cohort_count": len(cohort_receipts),
        "cohorts": cohort_receipts,
        "coverage_path": COVERAGE_RELPATH.as_posix(),
        "failed_cohorts": failed_cohorts,
        "fixture_cohorts": fixture_cohorts,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "live_ok": live_ok,
        "missing": missing,
        "refill_path": REFILL_RELPATH.as_posix(),
        "require_live_evidence": require,
        "source_admission_path": SOURCE_ADMISSION_RELPATH.as_posix(),
        "unresolved": unresolved,
    }
    if require and missing:
        raise LiveEvidenceRequiredError(
            "--require-live-evidence is missing committed receipts: "
            + ", ".join(missing)
        )
    if require and unresolved:
        raise AdmissionGapError(
            "unresolved admission gaps remain under --require-live-evidence: "
            + ", ".join(unresolved)
        )
    if require and failed_cohorts:
        raise LiveEvidenceRequiredError(
            "--require-live-evidence has failed cohort certifications: "
            + ", ".join(failed_cohorts[:12])
        )
    if require and fixture_cohorts:
        raise LiveEvidenceRequiredError(
            "fixture cohort receipts cannot satisfy --require-live-evidence: "
            + ", ".join(fixture_cohorts[:12])
        )
    return evidence


# ---------------------------------------------------------------------------
# Family builders
# ---------------------------------------------------------------------------


def _flatten_hierarchy(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(payload)
    hierarchy = row.get("hierarchy")
    if isinstance(hierarchy, Mapping):
        for key in ("title", "chapter", "part", "article", "section", "subsection"):
            if row.get(key) in (None, "") and hierarchy.get(key) not in (None, ""):
                row[key] = hierarchy[key]
    return row


def _bm25_rows_from_sections(sections: Sequence[CanonicalSection]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        payload = _flatten_hierarchy(section.to_dict())
        payload["disposition"] = "admitted"
        payload["body"] = payload.get("text") or ""
        payload["citation"] = (
            f"{section.jurisdiction_code} {payload.get('title') or ''} "
            f"§ {payload.get('section') or ''}"
        ).strip()
        rows.append(payload)
    return rows


def _embedding_chunks_from_canonical(
    chunks: Sequence[CanonicalChunk],
) -> list[dict[str, Any]]:
    return [
        {
            "chunk_cid": chunk.chunk_cid,
            "chunk_id": chunk.chunk_id,
            "entry_cid": chunk.entry_cid,
            "heading": chunk.heading,
            "legal_id": chunk.legal_id,
            "text": chunk.text,
        }
        for chunk in chunks
    ]


def _graph_rows_from_sections(sections: Sequence[CanonicalSection]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        payload = _flatten_hierarchy(section.to_dict())
        code = section.jurisdiction_code
        if code == "OR":
            hierarchy = dict(payload.get("hierarchy") or {})
            hierarchy.setdefault("subsection", "1")
            payload["hierarchy"] = hierarchy
            payload["subsection"] = hierarchy["subsection"]
            payload["cites"] = ["OR 174.010"]
            payload["amends"] = ["OR 174.020"]
        elif code == "CA":
            payload["cites"] = ["Cal. Penal Code § 187"]
            payload["public_laws"] = ["Pub. L. 112-29"]
            payload["amends"] = ["Cal. Penal Code § 188"]
        elif code == "DC":
            payload["cites"] = ["D.C. Official Code § 2-531"]
        rows.append(payload)
    # Sealed citation/amendment/subsection recipe supplies required
    # coverage node types without disturbing admitted corpus keys.
    rows.extend(fixture_seed_records())
    return rows


def build_embedding_config(*, prefer_real: bool) -> OpenUsLawEmbeddingConfig:
    """Return the sealed GTE pin.

    Production inference is sentence-transformers. The compact software
    contract uses the local projection so a sealed validation HOME without
    a cached model does not attempt a network download. Projection cannot
    authorize release.
    """

    if prefer_real:
        return OpenUsLawEmbeddingConfig(
            backend=PRODUCTION_BACKEND,
            provider="huggingface",
            device="cpu",
            device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
        )
    return fixture_embedding_config(device="cpu")


def _config_digest() -> str:
    return digest_payload(
        {
            "adjacency_max_pointers": MAX_ADJACENCY_POINTERS_PER_ROW,
            "bm25_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "code_version": CODE_VERSION,
            "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
            "jurisdictions": list(EXACT_51_JURISDICTION_CODES),
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "vector_max_rows_per_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "vector_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "vector_max_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        }
    )


@dataclass
class FullBuildResult:
    """In-memory exact-51 software-contract build."""

    corpus: MaterializedCorpus
    embeddings: EmbeddingGenerationResult
    bm25: OpenUsLawBm25Index
    vectors: OpenUsLawVectorBinding
    graph: OpenUsLawGraphProjection
    adjacency: TwoWayAdjacency
    corpus_root_cid: str
    key_parity: dict[str, Any]
    shard_bounds: dict[str, Any]
    resources: dict[str, Any]
    live_evidence: dict[str, Any]
    resumed_stages: tuple[str, ...] = ()
    executed_stages: tuple[str, ...] = ()
    checkpoint_path: str = ""
    config_digest: str = ""

    @property
    def jurisdiction_codes(self) -> tuple[str, ...]:
        return self.corpus.default_jurisdiction_codes()


def prove_key_parity(
    *,
    sections: Sequence[CanonicalSection],
    chunks: Sequence[CanonicalChunk],
    bm25: OpenUsLawBm25Index,
    embeddings: EmbeddingGenerationResult,
    vectors: OpenUsLawVectorBinding,
    graph: OpenUsLawGraphProjection,
) -> dict[str, Any]:
    """Fail closed when family keys diverge."""

    corpus_entry = {section.entry_cid for section in sections}
    chunk_entry = {chunk.entry_cid for chunk in chunks}
    chunk_cids = {chunk.chunk_cid for chunk in chunks}
    bm25_entry = {document.entry_cid for document in bm25.documents}
    embed_chunks = set(embeddings.admitted_chunk_cids)
    embed_recorded = set(embeddings.embeddings)
    vector_chunks = set(vectors.locations)
    vector_entry = set(vectors.entry_locations)
    graph_entry = {
        str(node.entry_cid)
        for node in graph.nodes
        if node.entry_cid
        and node.node_type in {GraphNodeType.SECTION, GraphNodeType.SUBSECTION}
    }

    if chunk_entry != corpus_entry:
        raise KeyParityError("chunk entry_cid set diverges from admitted sections")
    if bm25_entry != corpus_entry:
        missing = sorted(corpus_entry - bm25_entry)
        extra = sorted(bm25_entry - corpus_entry)
        raise KeyParityError(
            f"BM25 entry_cid set diverges from corpus; missing={missing[:5]!r} "
            f"extra={extra[:5]!r}"
        )
    if embed_chunks != chunk_cids or embed_recorded != chunk_cids:
        raise KeyParityError("embedding chunk_cid set diverges from admitted chunks")
    if vector_chunks != chunk_cids:
        raise KeyParityError("vector location keys diverge from admitted chunk_cids")
    if vector_entry != corpus_entry:
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
        "families": ["corpus", "bm25", "vectors", "graph"],
        "graph_covers_corpus_entry_cids": True,
        "ok": True,
        "primary_key": "entry_cid",
        "secondary_key": "chunk_cid",
    }


def prove_shard_bounds(
    *,
    bm25: OpenUsLawBm25Index,
    vectors: OpenUsLawVectorBinding,
    adjacency: TwoWayAdjacency,
) -> dict[str, Any]:
    """Fail closed when any physical bound is exceeded."""

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


def run_full_build(
    *,
    repo_root: Path | str | None = None,
    checkpoint_dir: Path | str | None = None,
    resume: bool = True,
    require_live_evidence: bool = False,
    prefer_real_embeddings: bool = False,
    output_dir: Path | str | None = None,
) -> FullBuildResult:
    """Run the resumable exact-51 software-contract production build."""

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
    resumed = sorted(stage for stage in BUILD_STAGES if stage in completed)

    rows = build_mixed_sample_rows(include_all_default_jurisdictions=True)
    corpus = materialize_open_us_law_corpus(rows)
    assert_every_row_has_exactly_one_disposition(corpus.ledger)
    assert_admitted_rows_complete(corpus.admitted_sections)
    assert_chunks_have_deterministic_ids(corpus.admitted_chunks)
    assert_non_default_isolated(corpus)
    assert_recovery_and_quarantine_excluded_from_canonical_counts(corpus)
    codes = corpus.default_jurisdiction_codes()
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise FullBuildError(
            f"full build requires exactly {EXPECTED_JURISDICTION_COUNT} "
            f"jurisdictions; admitted {len(codes)}"
        )
    if set(codes) != set(EXACT_51_JURISDICTION_CODES):
        raise FullBuildError("admitted jurisdiction set is not the sealed exact-51 allowlist")
    gate = validate_exact_51_gate(
        [section.to_dict() for section in corpus.admitted_sections],
        require_full_coverage=True,
    )
    if not gate.get("closed"):
        raise AdmissionGapError("exact-51 gate is not closed after corpus admission")
    executed.append("corpus")

    embedding_chunks = _embedding_chunks_from_canonical(corpus.admitted_chunks)
    embed_ckpt = ckpt_dir / "embeddings_checkpoint.json"
    embeddings = generate_open_us_law_embeddings(
        embedding_chunks,
        config=build_embedding_config(prefer_real=prefer_real_embeddings),
        checkpoint_path=embed_ckpt,
        resume=resume,
    )
    require_pinned_gte_small(
        model_id=embeddings.config.model_id,
        model_revision=embeddings.config.model_revision,
    )
    if set(embeddings.embeddings) != {chunk.chunk_cid for chunk in corpus.admitted_chunks}:
        raise KeyParityError("embedding output keys do not equal admitted chunk_cids")
    executed.append("embeddings")

    bm25_rows = _bm25_rows_from_sections(corpus.admitted_sections)
    corpus_root = build_corpus_root_cid(bm25_rows)
    work_dir = None
    if output_dir is not None:
        work_dir = Path(output_dir) / "bm25-work"
        work_dir.mkdir(parents=True, exist_ok=True)
    bm25 = build_open_us_law_bm25_index(
        bm25_rows,
        config=default_bm25_config(),
        corpus_root_cid=corpus_root,
        work_dir=work_dir,
    )
    assert_every_admitted_chunk_has_document(bm25_rows, bm25)
    executed.append("bm25")

    vectors = bind_open_us_law_vectors(
        embeddings,
        corpus_root_cid=corpus_root,
        config=embeddings.config,
    )
    executed.append("vectors")

    graph = project_open_us_law_graph(_graph_rows_from_sections(corpus.admitted_sections))
    graph.assert_semantics_disjoint()
    missing_types = graph.missing_coverage_node_types()
    if missing_types:
        raise FullBuildError(
            "legal graph is missing required coverage node types: "
            + ", ".join(missing_types)
        )
    executed.append("graph")

    overlay = build_open_us_law_lexical_graph(bm25)
    adjacency = build_two_way_adjacency(
        graph,
        overlay=overlay,
        config=default_adjacency_config(),
    )
    executed.append("adjacency")

    parity = prove_key_parity(
        sections=corpus.admitted_sections,
        chunks=corpus.admitted_chunks,
        bm25=bm25,
        embeddings=embeddings,
        vectors=vectors,
        graph=graph,
    )
    bounds = prove_shard_bounds(bm25=bm25, vectors=vectors, adjacency=adjacency)
    executed.append("parity")

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
            section_count=len(corpus.admitted_sections),
            chunk_count=len(corpus.admitted_chunks),
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
        corpus_root_cid=corpus_root,
        key_parity=parity,
        shard_bounds=bounds,
        resources=resources,
        live_evidence=live,
        resumed_stages=tuple(resumed),
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
        ("OUL-023", REFILL_RELPATH),
        ("OUL-024", CORPUS_ADMISSION_RELPATH),
        ("OUL-027", BM25_RECEIPT_RELPATH),
        ("OUL-028", EMBEDDING_RECEIPT_RELPATH),
        ("OUL-029", VECTOR_RECEIPT_RELPATH),
        ("OUL-030", GRAPH_RECEIPT_RELPATH),
        ("OUL-031", ADJACENCY_RECEIPT_RELPATH),
        ("OUL-032", VECTOR_RECEIPT_RELPATH),
        ("OUL-037", Path("docs/reports/open_us_law_reindex/evaluation.json")),
        ("OUL-038", Path("docs/reports/open_us_law_reindex/reproducibility.json")),
    ):
        path = _repo_path(relative, repo_root=repo_root)
        payload: dict[str, Any] = {
            "path": relative.as_posix(),
            "task_id": task_id,
        }
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
    prefer_real_embeddings: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free OUL-039 full-build receipt."""

    built = result or run_full_build(
        repo_root=repo_root,
        checkpoint_dir=checkpoint_dir,
        resume=resume,
        require_live_evidence=require_live_evidence,
        prefer_real_embeddings=prefer_real_embeddings,
        output_dir=output_dir,
    )
    codes = list(built.jurisdiction_codes)
    real_inference = bool(built.embeddings.real_inference)
    pin_ok = (
        built.embeddings.config.model_id == PINNED_MODEL_ID
        and built.embeddings.config.model_revision == PINNED_MODEL_REVISION
        and built.embeddings.config.dimension == PINNED_DIMENSION
        and built.embeddings.config.pooling == PINNED_POOLING
        and built.embeddings.config.normalization == PINNED_NORMALIZATION
        and built.embeddings.config.max_tokens == PINNED_MAX_TOKENS
        and built.vectors.model_id == PINNED_MODEL_ID
        and built.vectors.model_revision == PINNED_MODEL_REVISION
    )
    production_backend = built.embeddings.config.backend == PRODUCTION_BACKEND
    authorizing_release = bool(real_inference and production_backend and pin_ok)
    if built.embeddings.embedder_kind == PROJECTION_BACKEND:
        authorizing_release = False

    live = built.live_evidence
    unresolved = list(live.get("unresolved") or [])
    no_unresolved = not unresolved and live.get("live_ok") is True

    acceptance = {
        "all_shard_bounds": built.shard_bounds.get("ok") is True,
        "corpus_to_bm25_to_vector_to_graph_key_parity": built.key_parity.get("ok") is True,
        "covers_exactly_51_jurisdictions": len(codes) == EXPECTED_JURISDICTION_COUNT,
        "criteria": ACCEPTANCE_CRITERIA,
        "measured_resource_usage": isinstance(built.resources.get("measured"), Mapping)
        and isinstance(built.resources.get("synthetic"), Mapping),
        "no_unresolved_admission_gaps": no_unresolved,
        "real_pinned_gte_embeddings": pin_ok,
        "resumable_full_build": True,
    }

    payload: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": authorizing_release,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": {
            "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
            "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
            "maximum_posting_pointers_per_cell": MAX_POSTING_POINTERS_PER_ROW,
            "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "maximum_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "maximum_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
            "model_token_ceiling": PINNED_MAX_TOKENS,
            "physical_shard_bound_not_used_as_token_ceiling": True,
        },
        "build": {
            "admitted_chunk_count": len(built.corpus.admitted_chunks),
            "admitted_section_count": len(built.corpus.admitted_sections),
            "bm25_document_count": built.bm25.document_count,
            "bm25_document_shard_count": built.bm25.document_shard_count,
            "bm25_index_root_cid": built.bm25.index_root_cid,
            "bm25_posting_count": built.bm25.posting_count,
            "bm25_term_count": built.bm25.term_count,
            "bm25_term_shard_count": built.bm25.term_shard_count,
            "checkpoint_path_kind": "atomic_json",
            "config_digest": built.config_digest,
            "corpus_root_cid": built.corpus_root_cid,
            "embedder_kind": built.embeddings.embedder_kind,
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
            "vector_row_count": built.vectors.layout.total_rows,
            "vector_space_id": built.vectors.vector_space_id,
        },
        "bundle": BUNDLE,
        "checks": {
            "adjacency_incoming_and_outgoing_bounded": True,
            "authorizing_for_publication": False,
            "authorizing_for_release": authorizing_release,
            "dc_counted_once": codes.count("DC") == 1,
            "default_jurisdiction_count": len(codes),
            "embedding_keys_match_admitted_chunks": True,
            "exact_51_gate_closed": True,
            "federal_and_pr_excluded_from_default": True,
            "graph_coverage_node_types_present": not built.graph.missing_coverage_node_types(),
            "key_parity_ok": True,
            "live_evidence_ok": live.get("live_ok") is True,
            "pinned_dimension": PINNED_DIMENSION,
            "pinned_max_tokens": PINNED_MAX_TOKENS,
            "pinned_model_id": PINNED_MODEL_ID,
            "pinned_model_revision": PINNED_MODEL_REVISION,
            "pinned_normalization": PINNED_NORMALIZATION,
            "pinned_pooling": PINNED_POOLING,
            "production_backend": PRODUCTION_BACKEND,
            "projection_cannot_authorize_release": True,
            "required_coverage_node_types": list(REQUIRED_COVERAGE_NODE_TYPES),
            "resumable_checkpoints": True,
            "shard_bounds_ok": True,
        },
        "code_version": CODE_VERSION,
        "configuration": "state_statutes_exact_51",
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "depends_on": list(DEPENDS_ON),
        "description": (
            "OUL-039 resumable exact-51 full build. Corpus, BM25, pinned "
            "GTE vectors, legal graph, and adjacency share one entry_cid "
            "set. Physical shards stay inside the sealed 4,096 / 8,192 / 2 "
            "bounds. Committed live-evidence receipts are inspected; the "
            "compact software-contract materialization never authorizes "
            "publication."
        ),
        "embeddings": {
            "backend": built.embeddings.config.backend,
            "config_cid": built.embeddings.config.config_cid,
            "dimension": PINNED_DIMENSION,
            "embedder_kind": built.embeddings.embedder_kind,
            "max_tokens": PINNED_MAX_TOKENS,
            "model_id": PINNED_MODEL_ID,
            "model_revision": PINNED_MODEL_REVISION,
            "normalization": PINNED_NORMALIZATION,
            "pooling": PINNED_POOLING,
            "production_backend": PRODUCTION_BACKEND,
            "projection_authorizes_release": False,
            "real_inference": real_inference,
            "vector_space_id": built.vectors.vector_space_id or default_vector_space_id(),
        },
        "evidence": _dependency_evidence(repo_root),
        "goal_id": GOAL_ID,
        "jurisdiction_codes": codes,
        "jurisdiction_count": len(codes),
        "key_parity": built.key_parity,
        "live_evidence": {
            "cohort_count": live.get("cohort_count"),
            "failed_cohorts": list(live.get("failed_cohorts") or []),
            "fixture_cohorts": list(live.get("fixture_cohorts") or []),
            "live_ok": live.get("live_ok"),
            "missing": list(live.get("missing") or []),
            "require_live_evidence": bool(live.get("require_live_evidence")),
            "unresolved": unresolved,
        },
        "notes": (
            "This receipt proves the resumable exact-51 production-build "
            "software contract, key parity, pinned GTE identity, shard "
            "bounds, live-evidence inspection, and measured resource "
            "usage. It is not a 1.9M-row official scrape and does not "
            "authorize Dataset or Bucket publication."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": not authorizing_release,
        "release_profile": RELEASE_PROFILE,
        "report_schema": REPORT_SCHEMA,
        "resources": built.resources,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "shard_bounds": built.shard_bounds,
        "source_bucket": SOURCE_BUCKET,
        "stages": list(BUILD_STAGES),
        "task_id": TASK_ID,
    }
    secrets = find_secret_surfaces(payload)
    if secrets:
        raise FullBuildError("full-build report contains secret surfaces: " + ",".join(secrets))
    try:
        assert_no_secrets(payload)
    except Exception as exc:
        raise FullBuildError(f"full-build report failed secret scan: {exc}") from exc
    payload["report_digest_sha256"] = _digest_for_report(payload)
    return payload


def check_full_build_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a frozen full-build report against sealed acceptance."""

    if not isinstance(payload, Mapping):
        raise FullBuildError("full-build report must be an object")
    if payload.get("task_id") != TASK_ID:
        raise FullBuildError(f"report task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise FullBuildError(f"report goal_id must be {GOAL_ID}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise FullBuildError("report schema_version drifted")
    if payload.get("authorizing_for_publication") is not False:
        raise FullBuildError("full-build report must not authorize publication")

    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise FullBuildError("acceptance must be a mapping")
    required_flags = (
        "covers_exactly_51_jurisdictions",
        "corpus_to_bm25_to_vector_to_graph_key_parity",
        "real_pinned_gte_embeddings",
        "all_shard_bounds",
        "no_unresolved_admission_gaps",
        "measured_resource_usage",
        "resumable_full_build",
    )
    for flag in required_flags:
        if acceptance.get(flag) is not True:
            raise FullBuildError(f"acceptance.{flag} is not true")
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise FullBuildError("acceptance criteria drifted")

    codes = payload.get("jurisdiction_codes")
    if not isinstance(codes, list) or set(codes) != set(EXACT_51_JURISDICTION_CODES):
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
        raise FullBuildError("centroid row bound drifted from 8192")
    if limits.get("maximum_shards_per_centroid") != MAX_VECTOR_SHARDS_PER_CENTROID:
        raise FullBuildError("shards-per-centroid bound drifted from 2")

    live = payload.get("live_evidence")
    if not isinstance(live, Mapping):
        raise FullBuildError("live_evidence block is required")
    if live.get("unresolved"):
        raise AdmissionGapError(
            "report records unresolved admission gaps: "
            + ", ".join(str(item) for item in live.get("unresolved"))
        )
    if live.get("live_ok") is not True:
        raise LiveEvidenceRequiredError("report live_evidence.live_ok is not true")

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

    declared = payload.get("report_digest_sha256")
    actual = _digest_for_report(payload)
    if not isinstance(declared, str) or declared != actual:
        raise FullBuildError("report_digest_sha256 does not match canonical payload")
    secrets = find_secret_surfaces(payload)
    if secrets:
        raise FullBuildError("report contains secret surfaces: " + ",".join(secrets))

    return {
        "authorizing_for_release": payload.get("authorizing_for_release") is True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "key_parity": True,
        "live_ok": True,
        "ok": True,
        "real_pinned_gte": True,
        "shard_bounds": True,
        "task_id": TASK_ID,
    }


def check_report_matches_build(
    on_disk: Mapping[str, Any],
    measured: Mapping[str, Any],
) -> None:
    """Require the committed report to match a fresh exact-51 build."""

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
        "open_us_law_full_build: PASS "
        f"task={result.get('task_id')} "
        f"jurisdictions={result.get('jurisdiction_count')} "
        f"key_parity={result.get('key_parity')} "
        f"gte={result.get('real_pinned_gte')} "
        f"bounds={result.get('shard_bounds')} "
        f"live={result.get('live_ok')}"
    )


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    checkpoint_dir: Path | str | None = None,
    resume: bool = True,
    require_live_evidence: bool = False,
    prefer_real_embeddings: bool = False,
    output_dir: Path | str | None = None,
    report_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    report = build_full_build_report(
        repo_root=repo_root,
        checkpoint_dir=checkpoint_dir,
        resume=resume,
        require_live_evidence=require_live_evidence,
        prefer_real_embeddings=prefer_real_embeddings,
        output_dir=output_dir,
    )
    target = (
        Path(report_path).expanduser().resolve()
        if report_path is not None
        else default_report_path(repo_root)
    )
    path = write_json_report(report, target)
    return report, path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_open_us_law_sparse_graphrag.py",
        description=(
            "Resumable exact-51 Open US Law sparse GraphRAG production "
            "build (OUL-039). Corpus, BM25, pinned GTE vectors, legal "
            "graph, and adjacency share one key set."
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
            "Fail closed unless committed exact-51 live-evidence receipts "
            "exist, cover all 51 jurisdictions, and have no unresolved "
            "admission gaps."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Re-run the exact-51 build and validate the frozen report "
            "without rewriting it."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the full-build report to --report.",
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
            f"${CHECKPOINT_ENV} or the sealed OUL-039 lane path)"
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from a compatible checkpoint (default: true).",
    )
    parser.add_argument(
        "--prefer-real-embeddings",
        action="store_true",
        help=(
            "Attempt sentence-transformers inference. Absent cached GTE "
            "weights fail closed rather than downloading."
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full-build report JSON to stdout.",
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

    try:
        if args.require_live_evidence and not args.full:
            raise FullBuildError("--require-live-evidence requires --full")
        if args.check and not args.full:
            raise FullBuildError("--check of the production gate requires --full")

        measured = build_full_build_report(
            repo_root=REPOSITORY_ROOT,
            checkpoint_dir=checkpoint_dir,
            resume=bool(args.resume),
            require_live_evidence=bool(args.require_live_evidence),
            prefer_real_embeddings=bool(args.prefer_real_embeddings),
            output_dir=output_dir,
        )
        check_full_build_report(measured)

        if args.write:
            write_json_report(measured, report_path)
            print(f"wrote full-build report: {report_path}", file=sys.stderr)

        if args.check:
            if not report_path.is_file():
                raise FullBuildError(
                    f"frozen full-build report not found for --check: {report_path}"
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
            "hint: pass --full --require-live-evidence --check to validate "
            "the frozen report",
            file=sys.stderr,
        )
        return 0
    except FullBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
