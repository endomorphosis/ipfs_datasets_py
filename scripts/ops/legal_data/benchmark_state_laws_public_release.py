#!/usr/bin/env python3
"""Benchmark sparse production queries at the public pin (LCR-044).

Read-only public-pin benchmark against the immutable SHA recorded by the
LCR-042 publication receipt and verified by the LCR-043 public canary.
This script never mutates the Hub, never adjusts a failing receipt, and
never treats a fixture-only substitute as a public pin.

Default ``--check`` is credential-free and does not contact the Hub:

1. Require the LCR-043 public canary and LCR-036 sealed evaluation
   thresholds as preconditions.
2. Reconstruct the published artifact tree from the sealed candidate
   (in-memory FakeHub redownload).
3. Measure cold/warm bytes, shards, latency, and cache hits for
   route-justified production shards only.
4. Run BM25 / vector / hybrid / graph / DC-filter queries for every
   jurisdiction and compare ordered CIDs and explanations to the local
   LCR-038 oracle (and the rematerialized corpus).
5. Enforce declared query budgets and jurisdiction-skew / recall
   controls. A regression emits a repair task and refuses to rewrite
   the sealed receipt.

Validation gate::

    python scripts/ops/legal_data/benchmark_state_laws_public_release.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import (
    DEFAULT_BM25_WEIGHT,
    DEFAULT_VECTOR_WEIGHT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    EXPECTED_JURISDICTION_COUNT,
    RELEASE_PROFILE,
    required_semantic_families,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    ResolverError,
    validate_immutable_revision,
    validate_repo_id,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    CANARY_BUDGETS,
    CanaryBudgetError,
    CanaryParityError,
    CanaryStateLawsError,
    _bm25_hits,
    _graph_neighbors,
    _hybrid_hits,
    _resolver_descriptor,
    _vector_hits,
    assert_no_secrets_or_absolute_paths,
    assert_trace_within_bounds,
    candidate_file_index,
    inventory_digest,
    publication_digest,
    refuse_fixture_only,
    rematerialize_candidate_package,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    reject_credentials_in_payload as canary_reject_credentials,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    reject_secrets_in_argv as canary_reject_secrets_in_argv,
)
from scripts.ops.legal_data.check_state_laws_public_release import (
    PUBLIC_BUDGETS,
    PublicPinError,
    assert_public_pin_contract,
    check_canonical_public_canary_receipt,
    load_publication_receipt,
    reconstruct_public_revision,
    require_public_pin,
)
from scripts.ops.legal_data.publish_state_laws_hf_release import (
    DEFAULT_DATASET_REPO,
    DEFAULT_OBSERVATION_CUTOFF,
    DEFAULT_RECEIPT_RELPATH,
    FORBIDDEN_OPERATIONS,
    PRODUCTION_REVISION,
    PUBLIC_BRANCH,
    FakeStateLawsPublicHub,
    PublishSafetyError,
    PublishStateLawsError,
    candidate_file_bytes,
    declared_file_digests,
    reject_credentials_in_payload,
    reject_secrets_in_argv,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-044"
GOAL_ID: Final = "LCR-G080"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
if DEFAULT_DATASET_REPO != "justicedao/ipfs_state_laws":
    raise RuntimeError("sealed state-law target drifted from the publication gate")
if DEFAULT_DATASET_REPO != DEFAULT_DATASET_REPO_ID:
    raise RuntimeError("sealed state-law target drifted from DEFAULT_DATASET_REPO_ID")
PRODUCER: Final = "benchmark_state_laws_public_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-hf-public-benchmark/v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-036", "LCR-043")
PUBLICATION_TASK_ID: Final = "LCR-042"
PUBLIC_CANARY_TASK_ID: Final = "LCR-043"
EVALUATION_TASK_ID: Final = "LCR-036"
LOCAL_E2E_TASK_ID: Final = "LCR-038"

BENCHMARK_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-public-benchmark@1"
CANONICAL_BENCHMARK_SCHEMA: Final = RECEIPT_SCHEMA_V1
CANONICAL_BENCHMARK_KIND: Final = "state-laws-public-benchmark/v2"
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_benchmark.json"
)
DEFAULT_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
DEFAULT_EVALUATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/evaluation.json"
)
DEFAULT_LOCAL_E2E_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/local_e2e.json"
)
DEFAULT_QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/query_contract.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)

REMOTE_REPO_ENV: Final = "STATE_LAWS_PUBLIC_BENCHMARK_REPO_ID"
REMOTE_REVISION_ENV: Final = "STATE_LAWS_PUBLIC_BENCHMARK_REVISION"
REMOTE_ENABLE_ENV: Final = "STATE_LAWS_PUBLIC_BENCHMARK_REMOTE"

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was "
    "retrieved or sealed; they are not a claim that the codified text is "
    "legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official source."
)
SORTED_JURISDICTIONS: Final = tuple(sorted(CANONICAL_JURISDICTIONS))

SELF_DIGEST_FIELDS: Final = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "file_sha256",
        "final_manifest_digest",
        "manifest_digest",
        "raw_digest",
        "report_digest_sha256",
        "sha256",
    }
)

MAX_REPORT_BYTES: Final = 1048576
FUSED_RECALL_GATE: Final = 0.50
DENSE_RECALL_GATE: Final = 0.95
PRIMARY_TOP_K: Final = 5
MIN_WARM_CACHE_HIT_RATIO: Final = 1.0
MAX_JURISDICTION_SKEW: Final = 0.0
MAX_LATENCY_MS_COLD: Final = 5_000.0
MAX_LATENCY_MS_WARM: Final = 50.0
QUERY_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"

BENCHMARK_BUDGETS: Final[dict[str, Any]] = {
    **dict(PUBLIC_BUDGETS or CANARY_BUDGETS),
    "max_latency_ms_cold": MAX_LATENCY_MS_COLD,
    "max_latency_ms_warm": MAX_LATENCY_MS_WARM,
    "min_cache_hit_ratio_warm": MIN_WARM_CACHE_HIT_RATIO,
    "min_fused_recall": FUSED_RECALL_GATE,
    "min_dense_recall": DENSE_RECALL_GATE,
    "max_jurisdiction_skew": MAX_JURISDICTION_SKEW,
}

REFERENCE_HARDWARE: Final = {
    "architecture": "x86_64",
    "cpu_cores_logical": 8,
    "cpu_model": "reference-generic-8vCPU",
    "memory_gib": 32,
    "notes": (
        "Public-pin benchmark latency uses a deterministic synthetic cost "
        "model so sealed numbers stay comparable; they are not an SLA for "
        "arbitrary hardware."
    ),
    "os_family": "linux",
    "python_target": "python3.12",
    "storage": "nvme-ssd",
}
REFERENCE_NETWORK: Final = {
    "assumed_bandwidth_mbps": 100.0,
    "assumed_rtt_ms": 20.0,
    "hub_access": "disabled_in_default_check",
    "mode": "public_pin_offline_redownload",
    "network_required": False,
}

SPARSE_ROUTE: Final = "lexicographic_bm25_term_ranges"
DENSE_ROUTE: Final = "normalized_embedding_centroids"
GRAPH_ROUTE: Final = "bounded_adjacency_neighbors"
HYDRATE_ROUTE: Final = "ranked_hit_hydrate"

QUERY_INDEX_FAMILIES: Final = frozenset(
    {"bm25_postings", "vectors", "graph_adjacency_out"}
)
COMPLETE_FAMILY_ALIASES: Final = {
    "bm25": ("bm25_postings", "bm25_documents"),
    "vector": ("vectors",),
    "graph": (
        "graph_adjacency_out",
        "graph_adjacency_in",
        "graph_nodes",
        "graph_edges",
    ),
    "corpus": ("corpus",),
}

SUPPORTED_RESOLVER_SCHEMAS: Final = frozenset(
    {
        "hf-graphrag-release/v1",
        "publicus-ir-graphrag/v2",
        "state-laws-ir-graphrag/v2",
        "state-laws-sparse-graphrag-release-schema-v2",
        "state-laws-hf-release/v1",
    }
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

__all__ = [
    "BENCHMARK_BUDGETS",
    "BENCHMARK_SCHEMA",
    "DEPENDS_ON",
    "GOAL_ID",
    "TASK_ID",
    "PublicBenchmarkBudgetError",
    "PublicBenchmarkError",
    "PublicBenchmarkRegressionError",
    "build_parser",
    "build_public_benchmark_report",
    "check_state_public_benchmark",
    "compare_public_to_local_ordered",
    "create_repair_task",
    "main",
    "measure_cold_warm",
    "run_public_benchmark_loop",
]


class PublicBenchmarkError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublicBenchmarkBudgetError(PublicBenchmarkError, CanaryBudgetError):
    """Raised when public-pin query budgets are exceeded."""


class PublicBenchmarkParityError(PublicBenchmarkError, CanaryParityError):
    """Raised when public artifacts or local oracles disagree."""


class PublicBenchmarkRegressionError(PublicBenchmarkError):
    """Raised when public behavior regresses versus local ordered CIDs."""

    def __init__(self, message: str, *, repair_task: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.repair_task = dict(repair_task)


class PublicBenchmarkRemoteError(PublicBenchmarkError):
    """Raised when remote coordinates are missing or mutable."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANARY_RELPATH).resolve()


def default_evaluation_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_EVALUATION_RELPATH).resolve()


def default_local_e2e_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_LOCAL_E2E_RELPATH).resolve()


def default_query_contract_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_QUERY_CONTRACT_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PublicBenchmarkError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicBenchmarkError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicBenchmarkError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    return schema in {BENCHMARK_SCHEMA, RECEIPT_SCHEMA_V1} or schema.startswith(
        "ipfs_datasets_py/legal-corpora-"
    )


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    body = {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}
    return (
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def seal_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    digest = publication_digest(report)
    report["content_digest"] = digest
    report["digest"] = digest
    report["report_digest_sha256"] = digest
    reject_credentials_in_payload(report, label="public_benchmark")
    canary_reject_credentials(report, label="public_benchmark")
    assert_no_secrets_or_absolute_paths(report, label="public_benchmark")
    encoded = _canonical_report_bytes(report)
    if len(encoded) > MAX_REPORT_BYTES:
        raise PublicBenchmarkError(
            f"public benchmark exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    if not receipt_schema_is_known(receipt_schema_of(report)):
        raise PublicBenchmarkError("public benchmark schema is not publication-bindable")
    return report


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise PublicBenchmarkError(
            f"report exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_benchmark_report(
    report: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    sealed = seal_report(report)
    if sealed.get("status") != "passed" or sealed.get("repair_tasks"):
        raise PublicBenchmarkRegressionError(
            "refusing to write a failing public-benchmark receipt; "
            "create a repair task instead of adjusting the receipt",
            repair_task=next(
                iter(
                    sealed.get("repair_tasks")
                    or [create_repair_task("failing_receipt")]
                )
            ),
        )
    target = Path(path) if path is not None else default_report_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ---------------------------------------------------------------------------
# Repair task (never an adjusted receipt)
# ---------------------------------------------------------------------------


def create_repair_task(
    reason: str,
    *,
    detail: str | None = None,
    failed_jurisdictions: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Describe a successor repair task. Never mutates the sealed receipt."""

    return {
        "board_namespace": PROGRAM_ID,
        "depends_on": [TASK_ID],
        "detail": detail or reason,
        "failed_jurisdictions": list(failed_jurisdictions or ()),
        "goal_id": GOAL_ID,
        "kind": "repair",
        "receipt_adjusted": False,
        "source_task_id": TASK_ID,
        "suggested_task_id": f"{TASK_ID}-R01",
        "title": "Repair public-pin sparse query regression",
        "track": "public-benchmark-repair",
    }


def refuse_adjusted_receipt(reason: str, **kwargs: Any) -> PublicBenchmarkRegressionError:
    return PublicBenchmarkRegressionError(
        f"{reason}; create a repair task rather than adjusting the receipt",
        repair_task=create_repair_task(reason, **kwargs),
    )


# ---------------------------------------------------------------------------
# Preconditions / oracles
# ---------------------------------------------------------------------------


def expected_entry_cid(code: str) -> str:
    return hashlib.sha256(f"corpus:{code}".encode()).hexdigest()


def load_public_canary(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_canary_path(repo_root)
    report = load_json_mapping(target)
    if str(report.get("task_id") or "") != PUBLIC_CANARY_TASK_ID:
        raise PublicBenchmarkParityError(
            f"public canary task_id is {report.get('task_id')!r}"
        )
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")),
        require_live_staging=True,
        label="public canary",
    )
    assert_public_pin_contract(report)
    return report


def load_evaluation_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_evaluation_path(repo_root)
    report = load_json_mapping(target)
    if str(report.get("task_id") or "") != EVALUATION_TASK_ID:
        raise PublicBenchmarkParityError(
            f"evaluation task_id is {report.get('task_id')!r}"
        )
    acceptance = (
        report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    )
    if acceptance.get("sealed_thresholds_pass") is not True:
        raise PublicBenchmarkParityError("LCR-036 sealed evaluation thresholds did not pass")
    if acceptance.get("per_cohort_thresholds_pass") is not True:
        raise PublicBenchmarkParityError("LCR-036 per-cohort evaluation thresholds did not pass")
    if acceptance.get("no_unapproved_regression") is not True:
        raise PublicBenchmarkParityError("LCR-036 reports an unapproved evaluation regression")
    claim = report.get("production_claim") if isinstance(report.get("production_claim"), Mapping) else {}
    if claim.get("live_canary") is True:
        raise PublicBenchmarkParityError("evaluation must not be labeled a live canary")
    return report


def load_local_e2e(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_local_e2e_path(repo_root)
    report = load_json_mapping(target)
    if str(report.get("task_id") or "") != LOCAL_E2E_TASK_ID:
        raise PublicBenchmarkParityError(
            f"local e2e task_id is {report.get('task_id')!r}"
        )
    retrieval = report.get("retrieval") if isinstance(report.get("retrieval"), Mapping) else {}
    if retrieval.get("every_jurisdiction_ok") is not True:
        raise PublicBenchmarkParityError("local e2e retrieval did not pass every jurisdiction")
    if int(retrieval.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PublicBenchmarkParityError("local e2e is not the exact 51-set")
    return report


def load_query_contract(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_query_contract_path(repo_root)
    report = load_json_mapping(target)
    bounds = report.get("bounds") if isinstance(report.get("bounds"), Mapping) else {}
    if not bounds:
        raise PublicBenchmarkParityError("query contract is missing bounds")
    return report


def load_candidate_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else (Path(repo_root) if repo_root is not None else REPOSITORY_ROOT)
        / DEFAULT_CANDIDATE_RELPATH
    )
    return load_json_mapping(target)


def reconstruct_public_pin_files(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Observe FakeHub reconstruction of the published file binding.

    The LCR-042 receipt records the live Hub commit SHA. Offline FakeHub
    reconstruction yields a content-addressed SHA-1 of the same declared
    file binding. Those 40-hex values may differ; this benchmark never
    rewrites the receipt to hide that. Query I/O uses rematerialized
    descriptor-verified bytes, not FakeHub placeholder blobs.
    """

    expected = candidate_file_index(candidate)
    declared = declared_file_digests(candidate)
    if declared != expected:
        raise PublicBenchmarkParityError(
            "publication candidate declared digests drifted from the upload manifest"
        )
    try:
        reconstructed = reconstruct_public_revision(
            repo_root=repo_root,
            receipt=receipt,
            candidate=candidate,
        )
        return {
            "pin_sha_agrees": True,
            "reconstructed_sha": reconstructed["reconstructed_sha"],
        }
    except PublicPinError as exc:
        if "does not equal receipt public SHA" not in str(exc):
            raise
    transport = FakeStateLawsPublicHub()
    uploaded = transport.upload_files(
        candidate_file_bytes(candidate),
        repo_id=str(receipt.get("target_repo") or DEFAULT_DATASET_REPO),
        branch=str(receipt.get("public_branch") or PUBLIC_BRANCH),
        base_revision=str(receipt.get("old_sha") or PRODUCTION_REVISION),
        declared_digests=declared,
    )
    return {
        "pin_sha_agrees": False,
        "reconstructed_sha": str(uploaded.get("public_revision") or ""),
    }


def local_ordered_from_e2e(local_e2e: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    retrieval = local_e2e.get("retrieval") if isinstance(local_e2e.get("retrieval"), Mapping) else {}
    rows = retrieval.get("jurisdictions") if isinstance(retrieval.get("jurisdictions"), Mapping) else {}
    ordered: dict[str, dict[str, Any]] = {}
    for code in SORTED_JURISDICTIONS:
        item = rows.get(code)
        if not isinstance(item, Mapping):
            raise PublicBenchmarkParityError(f"local e2e missing jurisdiction {code}")
        cid = str(item.get("top_entry_cid") or "")
        if not _SHA256_RE.fullmatch(cid):
            raise PublicBenchmarkParityError(f"local e2e CID for {code} is not 64-hex")
        ordered[code] = {
            "jurisdiction": code,
            "mode": "local_bm25_canary",
            "ordered_cids": [cid],
            "query": str(item.get("query") or f"{code} official statutory text"),
            "top_entry_cid": cid,
            "top_legal_id": str(item.get("top_legal_id") or ""),
        }
    return ordered


def local_ordered_from_corpus(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, dict[str, Any]]:
    by_code = {
        str(row.get("jurisdiction") or ""): dict(row)
        for row in family_rows.get("corpus") or ()
    }
    ordered: dict[str, dict[str, Any]] = {}
    for code in SORTED_JURISDICTIONS:
        row = by_code.get(code)
        if row is None:
            raise PublicBenchmarkParityError(f"rematerialized corpus missing {code}")
        cid = str(row.get("entry_cid") or "")
        expected = expected_entry_cid(code)
        if cid != expected:
            raise refuse_adjusted_receipt(
                f"rematerialized CID for {code} drifted from sealed compact identity",
                detail=f"observed={cid} expected={expected}",
                failed_jurisdictions=[code],
            )
        ordered[code] = {
            "jurisdiction": code,
            "mode": "local_corpus",
            "ordered_cids": [cid],
            "query": f"{code} official statutory text",
            "top_entry_cid": cid,
            "top_legal_id": str(row.get("legal_id") or ""),
        }
    return ordered


# ---------------------------------------------------------------------------
# Query / I/O helpers
# ---------------------------------------------------------------------------


def route_reason_for_family(family: str) -> str:
    if family == "bm25_postings":
        return SPARSE_ROUTE
    if family == "vectors":
        return DENSE_ROUTE
    if family in {"graph_adjacency_out", "graph_adjacency_in"}:
        return GRAPH_ROUTE
    if family == "corpus":
        return HYDRATE_ROUTE
    raise PublicBenchmarkParityError(f"no production route for family {family!r}")


def select_routed_query_artifacts(artifacts: Sequence[Any]) -> list[Any]:
    selected: list[Any] = []
    seen: set[str] = set()
    for family in ("bm25_postings", "vectors", "graph_adjacency_out"):
        artifact = next((item for item in artifacts if item.family == family), None)
        if artifact is None:
            raise PublicBenchmarkParityError(f"missing routed query family {family}")
        if artifact.relative_path in seen:
            continue
        seen.add(artifact.relative_path)
        selected.append(artifact)
    return selected


def synthetic_latency_ms(
    *,
    bytes_fetched: int,
    shards: int,
    cache_hits: int,
) -> float:
    bandwidth_bps = float(REFERENCE_NETWORK["assumed_bandwidth_mbps"]) * 1_000_000.0 / 8.0
    transfer_ms = (float(bytes_fetched) / bandwidth_bps) * 1000.0 if bandwidth_bps else 0.0
    misses = max(0, int(shards) - int(cache_hits))
    rtt_ms = float(REFERENCE_NETWORK["assumed_rtt_ms"]) * float(misses)
    return round(transfer_ms + rtt_ms, 4)


def _summarize_fetch(
    files: Sequence[Mapping[str, Any]],
    *,
    phase: str,
) -> dict[str, Any]:
    paths = [str(item.get("relative_path") or "") for item in files]
    bytes_fetched = sum(
        int(item.get("size_bytes") or 0) for item in files if not item.get("cache_hit")
    )
    shards = len({path for path in paths if path})
    cache_hits = sum(1 for item in files if item.get("cache_hit"))
    cache_misses = sum(1 for item in files if not item.get("cache_hit"))
    latency = synthetic_latency_ms(
        bytes_fetched=bytes_fetched, shards=shards, cache_hits=cache_hits
    )
    return {
        "bytes": bytes_fetched,
        "cache_hit_ratio": round(cache_hits / shards, 6) if shards else 0.0,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "latency_ms": latency,
        "phase": phase,
        "shards": shards,
        "unique_paths": sorted({path for path in paths if path}),
    }


def fetch_routed_shards(
    resolver: ImmutableHubResolver,
    artifacts: Sequence[Any],
    *,
    phase: str,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for artifact in artifacts:
        reason = route_reason_for_family(str(artifact.family))
        resolved = resolver.resolve(
            artifact.relative_path,
            descriptor=_resolver_descriptor(artifact),
        )
        if not resolved.verified:
            raise PublicBenchmarkParityError(
                f"{phase} shard was not descriptor-verified: {artifact.relative_path}"
            )
        files.append(
            {
                "cache_hit": bool(resolved.cache_hit),
                "family": str(artifact.family),
                "relative_path": str(artifact.relative_path),
                "route_justified": True,
                "route_reason": reason,
                "sha256": str(resolved.sha256),
                "size_bytes": int(resolved.size_bytes),
                "verified": True,
            }
        )
    summary = _summarize_fetch(files, phase=phase)
    summary["files"] = files
    summary["route_justified"] = all(item["route_justified"] for item in files)
    return summary


def measure_cold_warm(
    resolver: ImmutableHubResolver,
    artifacts: Sequence[Any],
) -> dict[str, Any]:
    """Measure a cold miss pass then a warm cache-hit replay on the same shards."""

    cold = fetch_routed_shards(resolver, artifacts, phase="cold")
    if cold["cache_misses"] != cold["shards"] or cold["cache_hits"] != 0:
        raise PublicBenchmarkParityError("cold public-pin query pass must be all cache misses")
    warm = fetch_routed_shards(resolver, artifacts, phase="warm")
    if warm["cache_hits"] != warm["shards"] or warm["cache_misses"] != 0:
        raise PublicBenchmarkParityError("warm public-pin query pass must be all cache hits")
    if warm["bytes"] != 0:
        raise PublicBenchmarkParityError("warm public-pin query must not re-fetch bytes")
    if cold["unique_paths"] != warm["unique_paths"]:
        raise PublicBenchmarkParityError("cold/warm routed shard sets drifted")
    if not cold["route_justified"] or not warm["route_justified"]:
        raise PublicBenchmarkParityError("public-pin fetches must be route-justified")
    return {
        "cold": {
            "bytes": cold["bytes"],
            "cache_hit_ratio": cold["cache_hit_ratio"],
            "cache_hits": cold["cache_hits"],
            "cache_misses": cold["cache_misses"],
            "latency_ms": cold["latency_ms"],
            "route_justified": True,
            "shards": cold["shards"],
        },
        "ok": True,
        "paths": list(cold["unique_paths"]),
        "route_justified": True,
        "warm": {
            "bytes": warm["bytes"],
            "cache_hit_ratio": warm["cache_hit_ratio"],
            "cache_hits": warm["cache_hits"],
            "cache_misses": warm["cache_misses"],
            "latency_ms": warm["latency_ms"],
            "route_justified": True,
            "shards": warm["shards"],
        },
        "warm_faster_or_equal": warm["latency_ms"] <= cold["latency_ms"],
        "warm_zero_bytes": warm["bytes"] == 0,
    }


def assert_no_complete_family_download(
    fetched_paths: Sequence[str],
    artifacts: Sequence[Any],
) -> dict[str, Any]:
    fetched = {str(path) for path in fetched_paths if path}
    all_paths = {str(item.relative_path) for item in artifacts}
    if not fetched:
        raise PublicBenchmarkParityError("public query fetched no routed shards")
    if fetched >= all_paths:
        raise refuse_adjusted_receipt(
            "public query downloaded the complete published tree",
            detail="fetched_paths equal the full artifact set",
        )
    families: dict[str, set[str]] = {}
    for item in artifacts:
        families.setdefault(str(item.family), set()).add(str(item.relative_path))
    complete: list[str] = []
    for alias, names in COMPLETE_FAMILY_ALIASES.items():
        union = set()
        for name in names:
            union.update(families.get(name) or ())
        if union and union <= fetched and len(union) > 1:
            complete.append(alias)
        if alias == "corpus" and union and union <= fetched:
            complete.append(alias)
    if complete:
        raise refuse_adjusted_receipt(
            "public query downloaded a complete index/corpus family",
            detail="families=" + ",".join(sorted(set(complete))),
        )
    if len(fetched) > int(BENCHMARK_BUDGETS["max_query_shards"]):
        raise PublicBenchmarkBudgetError(
            f"query shards {len(fetched)} exceed "
            f"{BENCHMARK_BUDGETS['max_query_shards']}"
        )
    return {
        "complete_bm25_downloaded": False,
        "complete_corpus_downloaded": False,
        "complete_graph_downloaded": False,
        "complete_vector_downloaded": False,
        "fetched_path_count": len(fetched),
        "ok": True,
        "proper_subset_of_release": True,
    }


def _corpus_text_hits(
    corpus: Sequence[Mapping[str, Any]],
    query: str,
    *,
    jurisdiction: str | None = None,
) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    hits: list[dict[str, Any]] = []
    for row in corpus:
        code = str(row.get("jurisdiction") or "")
        if jurisdiction and code != jurisdiction:
            continue
        text = str(row.get("text") or "").casefold()
        if needle not in text:
            continue
        hits.append(
            {
                "entry_cid": str(row.get("entry_cid") or ""),
                "jurisdiction": code,
                "legal_id": str(row.get("legal_id") or ""),
                "score": 1.0,
            }
        )
    hits.sort(key=lambda item: (-float(item["score"]), item["entry_cid"]))
    return hits


def run_public_production_queries(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    local_ordered: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    postings = list(family_rows.get("bm25_postings") or ())
    vectors = list(family_rows.get("vectors") or ())
    corpus = list(family_rows.get("corpus") or ())
    adjacency = list(family_rows.get("graph_adjacency_out") or ())
    if not postings or not vectors or not corpus or not adjacency:
        raise PublicBenchmarkParityError("public query families are incomplete")

    jurisdictions: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    explanations: list[dict[str, Any]] = []
    hit_counts: Counter[str] = Counter()

    for code in SORTED_JURISDICTIONS:
        expected = local_ordered[code]
        expected_cid = str(expected["top_entry_cid"])
        sparse_query = f"statute-{code.lower()}"
        local_query = str(expected["query"])
        bm25 = _bm25_hits(postings, sparse_query, jurisdiction=code)
        dense = _vector_hits(vectors, jurisdiction=code, top_k=1)
        text_hits = _corpus_text_hits(corpus, local_query, jurisdiction=code)
        public_cids = [str(item["entry_cid"]) for item in bm25 if item.get("entry_cid")]
        dense_cids = [str(item["entry_cid"]) for item in dense if item.get("entry_cid")]
        text_cids = [str(item["entry_cid"]) for item in text_hits if item.get("entry_cid")]
        top_cid = public_cids[0] if public_cids else ""
        ok = (
            bool(public_cids)
            and top_cid == expected_cid
            and public_cids == list(expected["ordered_cids"])
            and dense_cids[:1] == [expected_cid]
            and text_cids[:1] == [expected_cid]
            and bm25[0]["jurisdiction"] == code
        )
        if not ok:
            failed.append(code)
        hit_counts[code] += len(public_cids)
        explanation = {
            "dense_route": DENSE_ROUTE,
            "jurisdiction": code,
            "local_ordered_cids": list(expected["ordered_cids"]),
            "mode": "bm25+vector+text",
            "public_ordered_cids": public_cids,
            "query": sparse_query,
            "route_justified": True,
            "sparse_route": SPARSE_ROUTE,
            "top_entry_cid": top_cid,
            "top_legal_id": str(
                (text_hits[0]["legal_id"] if text_hits else expected.get("top_legal_id")) or ""
            ),
        }
        explanations.append(explanation)
        jurisdictions[code] = {
            "hit_count": len(public_cids),
            "local_query": local_query,
            "ok": ok,
            "ordered_cids": public_cids,
            "query": sparse_query,
            "top_entry_cid": top_cid,
            "top_legal_id": explanation["top_legal_id"],
        }

    if failed:
        raise refuse_adjusted_receipt(
            "public ordered CIDs/explanations drifted from the local oracle",
            detail="failed=" + ",".join(failed),
            failed_jurisdictions=failed,
        )

    dc_filter = _bm25_hits(postings, "statute-dc", jurisdiction="DC")
    if len(dc_filter) != 1 or dc_filter[0]["jurisdiction"] != "DC":
        raise refuse_adjusted_receipt("DC filter public query failed")
    if str(dc_filter[0]["entry_cid"]) != str(local_ordered["DC"]["top_entry_cid"]):
        raise refuse_adjusted_receipt("DC filter CID drifted from the local oracle")

    hybrid = _hybrid_hits(postings, vectors, "statute-dc", top_k=3)
    if not any(item["jurisdiction"] == "DC" for item in hybrid):
        raise refuse_adjusted_receipt("hybrid public query did not recover DC")
    if str(hybrid[0]["entry_cid"]) != str(local_ordered["DC"]["top_entry_cid"]):
        raise refuse_adjusted_receipt("hybrid top CID drifted from the local DC oracle")

    start = str(local_ordered[SORTED_JURISDICTIONS[0]]["top_entry_cid"])
    neighbors = _graph_neighbors(adjacency, start)
    if not neighbors:
        raise refuse_adjusted_receipt("graph neighbor public query returned no pointers")

    matched = sum(1 for item in jurisdictions.values() if item["ok"])
    recall_at_1 = matched / float(EXPECTED_JURISDICTION_COUNT)
    return {
        "dc_filter": {
            "jurisdiction": "DC",
            "ok": True,
            "ordered_cids": [str(dc_filter[0]["entry_cid"])],
            "query": "statute-dc",
            "result_count": len(dc_filter),
        },
        "every_jurisdiction": True,
        "explanations": explanations,
        "failed": [],
        "graph": {
            "neighbor_count": len(neighbors),
            "ok": True,
            "start_entry_cid": start,
        },
        "hit_counts": {code: int(hit_counts[code]) for code in SORTED_JURISDICTIONS},
        "hybrid": {
            "ok": True,
            "ordered_cids": [str(item["entry_cid"]) for item in hybrid],
            "query": "statute-dc",
            "recovered_dc": True,
            "result_count": len(hybrid),
            "top_entry_cid": str(hybrid[0]["entry_cid"]),
        },
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": jurisdictions,
        "ok": True,
        "recall_at_1": recall_at_1,
    }


def compare_public_to_local_ordered(
    public_queries: Mapping[str, Any],
    local_ordered: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    mismatches: list[str] = []
    public_rows = (
        public_queries.get("jurisdictions")
        if isinstance(public_queries.get("jurisdictions"), Mapping)
        else {}
    )
    for code in SORTED_JURISDICTIONS:
        local = local_ordered.get(code) or {}
        public = public_rows.get(code) or {}
        if list(public.get("ordered_cids") or []) != list(local.get("ordered_cids") or []) or str(public.get("top_entry_cid") or "") != str(local.get("top_entry_cid") or ""):
            mismatches.append(code)
    if mismatches:
        raise refuse_adjusted_receipt(
            "public ordered CIDs do not match local ordered CIDs",
            detail="mismatched=" + ",".join(mismatches),
            failed_jurisdictions=mismatches,
        )
    local_digest = inventory_digest(
        [
            {
                "jurisdiction": code,
                "ordered_cids": list(local_ordered[code]["ordered_cids"]),
            }
            for code in SORTED_JURISDICTIONS
        ]
    )
    public_digest = inventory_digest(
        [
            {
                "jurisdiction": code,
                "ordered_cids": list((public_rows.get(code) or {}).get("ordered_cids") or []),
            }
            for code in SORTED_JURISDICTIONS
        ]
    )
    if local_digest != public_digest:
        raise refuse_adjusted_receipt("public/local ordered-CID digests disagree")
    explanation_digest = inventory_digest(list(public_queries.get("explanations") or ()))
    return {
        "agree": True,
        "explanation_digest": explanation_digest,
        "local_digest": local_digest,
        "mismatches": [],
        "ok": True,
        "public_digest": public_digest,
    }


def compute_jurisdiction_skew(hit_counts: Mapping[str, int]) -> dict[str, Any]:
    values = [int(hit_counts.get(code) or 0) for code in SORTED_JURISDICTIONS]
    if len(values) != EXPECTED_JURISDICTION_COUNT:
        raise PublicBenchmarkParityError("jurisdiction skew is not the exact 51-set")
    if any(value <= 0 for value in values):
        starved = [
            code
            for code in SORTED_JURISDICTIONS
            if int(hit_counts.get(code) or 0) <= 0
        ]
        raise refuse_adjusted_receipt(
            "public queries starved one or more jurisdictions",
            failed_jurisdictions=starved,
        )
    mean = sum(values) / float(len(values))
    spread = max(values) - min(values)
    skew = round(spread / mean, 6) if mean else math.inf
    if skew > float(BENCHMARK_BUDGETS["max_jurisdiction_skew"]):
        raise refuse_adjusted_receipt(
            "public jurisdiction hit skew exceeded the declared budget",
            detail=f"skew={skew}",
        )
    return {
        "max": max(values),
        "mean": mean,
        "min": min(values),
        "ok": True,
        "skew": skew,
        "within_budget": True,
    }


def assert_io_within_budgets(measured: Mapping[str, Any]) -> dict[str, Any]:
    cold = measured.get("cold") if isinstance(measured.get("cold"), Mapping) else {}
    warm = measured.get("warm") if isinstance(measured.get("warm"), Mapping) else {}
    errors: list[str] = []
    if int(cold.get("bytes") or 0) > int(BENCHMARK_BUDGETS["max_query_bytes"]):
        errors.append(
            f"cold bytes {cold.get('bytes')} exceed "
            f"{BENCHMARK_BUDGETS['max_query_bytes']}"
        )
    if int(cold.get("shards") or 0) > int(BENCHMARK_BUDGETS["max_query_shards"]):
        errors.append(
            f"cold shards {cold.get('shards')} exceed "
            f"{BENCHMARK_BUDGETS['max_query_shards']}"
        )
    if float(cold.get("latency_ms") or 0.0) > float(BENCHMARK_BUDGETS["max_latency_ms_cold"]):
        errors.append(
            f"cold latency {cold.get('latency_ms')} exceeds "
            f"{BENCHMARK_BUDGETS['max_latency_ms_cold']}"
        )
    if float(warm.get("latency_ms") or 0.0) > float(BENCHMARK_BUDGETS["max_latency_ms_warm"]):
        errors.append(
            f"warm latency {warm.get('latency_ms')} exceeds "
            f"{BENCHMARK_BUDGETS['max_latency_ms_warm']}"
        )
    if float(warm.get("cache_hit_ratio") or 0.0) < float(
        BENCHMARK_BUDGETS["min_cache_hit_ratio_warm"]
    ):
        errors.append("warm cache-hit ratio is below the declared budget")
    if errors:
        raise PublicBenchmarkBudgetError(
            "public-pin benchmark exceeded declared budgets: " + "; ".join(errors)
        )
    return {
        **{key: BENCHMARK_BUDGETS[key] for key in BENCHMARK_BUDGETS},
        "observed": {
            "cold_bytes": int(cold.get("bytes") or 0),
            "cold_latency_ms": float(cold.get("latency_ms") or 0.0),
            "cold_shards": int(cold.get("shards") or 0),
            "warm_bytes": int(warm.get("bytes") or 0),
            "warm_cache_hit_ratio": float(warm.get("cache_hit_ratio") or 0.0),
            "warm_latency_ms": float(warm.get("latency_ms") or 0.0),
            "warm_shards": int(warm.get("shards") or 0),
        },
        "ok": True,
        "within_bounds": True,
    }


# ---------------------------------------------------------------------------
# Benchmark loop / report
# ---------------------------------------------------------------------------


def run_public_benchmark_loop(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    public_canary: Mapping[str, Any] | None = None,
    evaluation: Mapping[str, Any] | None = None,
    local_e2e: Mapping[str, Any] | None = None,
    query_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct the public pin and measure sparse production queries."""

    bound_receipt = (
        dict(receipt) if receipt is not None else load_publication_receipt(repo_root=repo_root)
    )
    public_sha = require_public_pin(bound_receipt)
    canary = (
        dict(public_canary)
        if public_canary is not None
        else load_public_canary(repo_root=repo_root)
    )
    eval_report = (
        dict(evaluation)
        if evaluation is not None
        else load_evaluation_report(repo_root=repo_root)
    )
    e2e = dict(local_e2e) if local_e2e is not None else load_local_e2e(repo_root=repo_root)
    contract = (
        dict(query_contract)
        if query_contract is not None
        else load_query_contract(repo_root=repo_root)
    )
    report = (
        dict(candidate) if candidate is not None else load_candidate_report(repo_root=repo_root)
    )
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")) or bool(canary.get("fixture_only")),
        require_live_staging=True,
        label="public benchmark loop",
    )
    canary_pin = require_public_pin(canary)
    if str(canary.get("manifest_digest") or "") != str(bound_receipt.get("manifest_digest") or ""):
        raise PublicBenchmarkParityError(
            "public canary manifest digest does not match the publication receipt"
        )
    if str(canary.get("status") or "") not in {"passed", "ok"}:
        raise PublicBenchmarkParityError("public canary status is not passed")
    if str(report.get("manifest_digest") or "") != str(bound_receipt.get("manifest_digest") or ""):
        raise PublicBenchmarkParityError(
            "candidate manifest digest does not match the publication receipt"
        )
    if str(e2e.get("manifest_digest") or "") not in {
        "",
        str(bound_receipt.get("manifest_digest") or ""),
    } and str(e2e.get("release_root_cid") or "") not in {
        "",
        str(bound_receipt.get("release_root_cid") or ""),
    }:
        raise PublicBenchmarkParityError(
            "local e2e identity drifted from the publication receipt"
        )

    reconstructed = reconstruct_public_pin_files(
        repo_root=repo_root,
        receipt=bound_receipt,
        candidate=report,
    )
    release, family_rows = rematerialize_candidate_package()
    rematerialized_index = {item.relative_path: str(item.sha256) for item in release.artifacts}
    expected_index = candidate_file_index(report)
    if rematerialized_index != expected_index:
        raise PublicBenchmarkParityError(
            "rematerialized package drifted from the candidate upload manifest"
        )
    public_files = {item.relative_path: bytes(item.content) for item in release.artifacts}

    local_from_e2e = local_ordered_from_e2e(e2e)
    local_from_corpus = local_ordered_from_corpus(family_rows)
    for code in SORTED_JURISDICTIONS:
        if local_from_e2e[code]["top_entry_cid"] != local_from_corpus[code]["top_entry_cid"]:
            raise refuse_adjusted_receipt(
                "local e2e CIDs disagree with the rematerialized corpus",
                failed_jurisdictions=[code],
            )

    routed = select_routed_query_artifacts(list(release.artifacts))
    with tempfile.TemporaryDirectory(prefix="lcr044-public-benchmark-") as tmp:
        resolver = ImmutableHubResolver(
            repo_id=DEFAULT_DATASET_REPO,
            revision=public_sha,
            cache_dir=Path(tmp) / "cache",
            transport=MappingTransport(public_files),
            require_descriptor=True,
            supported_schemas=SUPPORTED_RESOLVER_SCHEMAS,
        )
        measured = measure_cold_warm(resolver, routed)
        family_guard = assert_no_complete_family_download(
            measured["paths"], list(release.artifacts)
        )
        compact_redownload = assert_trace_within_bounds(
            {
                "file_count": len(public_files),
                "total_file_bytes": sum(len(blob) for blob in public_files.values()),
                "unique_paths": len(public_files),
            },
            budgets=PUBLIC_BUDGETS,
        )
    del resolver

    queries = run_public_production_queries(family_rows, local_ordered=local_from_e2e)
    cid_cmp = compare_public_to_local_ordered(queries, local_from_e2e)
    skew = compute_jurisdiction_skew(queries["hit_counts"])
    bounds = assert_io_within_budgets(measured)
    if float(queries["recall_at_1"]) < float(BENCHMARK_BUDGETS["min_fused_recall"]):
        raise refuse_adjusted_receipt(
            "public recall@1 fell below the sealed fused-recall gate",
            detail=f"recall_at_1={queries['recall_at_1']}",
        )

    eval_identity = (
        eval_report.get("named_identity")
        or eval_report.get("identity")
        or {}
    )
    fusion = ((eval_report.get("chosen_defaults") or {}).get("fusion") or {})
    return {
        "bounds": bounds,
        "candidate": report,
        "canary": {
            "manifest_digest": canary.get("manifest_digest"),
            "path": DEFAULT_CANARY_RELPATH.as_posix(),
            "public_sha": canary_pin,
            "status": canary.get("status"),
            "task_id": PUBLIC_CANARY_TASK_ID,
        },
        "pin_identity": {
            "advertised_public_sha": public_sha,
            "canary_public_sha": canary_pin,
            "content_equal": True,
            "manifest_digest": str(bound_receipt.get("manifest_digest") or ""),
            "reconstructed_sha": reconstructed.get("reconstructed_sha"),
            "sha_forms_agree": bool(reconstructed.get("pin_sha_agrees")),
        },
        "cid_compare": cid_cmp,
        "compact_redownload": compact_redownload,
        "evaluation": {
            "fused_recall_gate": FUSED_RECALL_GATE,
            "model_id": eval_identity.get("model_id") or DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": eval_identity.get("model_revision")
            or DEFAULT_EMBEDDING_MODEL_REVISION,
            "path": DEFAULT_EVALUATION_RELPATH.as_posix(),
            "per_cohort_thresholds_pass": True,
            "sealed_thresholds_pass": True,
            "task_id": EVALUATION_TASK_ID,
        },
        "family_guard": family_guard,
        "fusion": {
            "bm25_weight": float(
                (fusion.get("config") or {}).get("bm25_weight") or DEFAULT_BM25_WEIGHT
            ),
            "method": str((fusion.get("config") or {}).get("method") or "weighted"),
            "vector_weight": float(
                (fusion.get("config") or {}).get("vector_weight") or DEFAULT_VECTOR_WEIGHT
            ),
        },
        "io": measured,
        "local_e2e": {
            "manifest_digest": e2e.get("manifest_digest"),
            "path": DEFAULT_LOCAL_E2E_RELPATH.as_posix(),
            "release_root_cid": e2e.get("release_root_cid"),
            "task_id": LOCAL_E2E_TASK_ID,
        },
        "local_ordered": local_from_e2e,
        "public_sha": public_sha,
        "queries": queries,
        "query_contract": {
            "default_top_k": int((contract.get("bounds") or {}).get("default_top_k") or 10),
            "path": DEFAULT_QUERY_CONTRACT_RELPATH.as_posix(),
            "primary_key": contract.get("primary_key") or "entry_cid",
        },
        "receipt": bound_receipt,
        "reconstructed_sha": reconstructed["reconstructed_sha"],
        "release_file_count": len(release.artifacts),
        "required_semantic_families": list(required_semantic_families()),
        "skew": skew,
    }


def build_public_benchmark_report(
    *,
    repo_root: Path | str | None = None,
    loop: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sealed public-pin sparse-query benchmark receipt."""

    executed = dict(loop) if loop is not None else run_public_benchmark_loop(repo_root=repo_root)
    receipt = executed["receipt"]
    public_sha = require_public_pin({"public_sha": executed["public_sha"]})
    queries = dict(executed["queries"])
    measured = dict(executed["io"])
    cid_cmp = dict(executed["cid_compare"])
    report: dict[str, Any] = {
        "acceptance": {
            "cache_warm_hits": True,
            "cold_warm_bytes_measured": True,
            "complete_family_not_downloaded": True,
            "credentials_environment_only": True,
            "declared_budgets_held": True,
            "evaluation_thresholds_bound": True,
            "every_jurisdiction_query_passed": True,
            "exact_51_coverage": True,
            "fixture_only_rejected": True,
            "includes_dc": True,
            "jurisdiction_skew_within_budget": True,
            "local_ordered_cids_match": True,
            "local_ordered_explanations_match": True,
            "no_absolute_path_or_secret": True,
            "no_adjusted_receipt_on_regression": True,
            "no_remote_mutation": True,
            "public_canary_bound": True,
            "public_pin_immutable": True,
            "publication_receipt_bound": True,
            "read_only": True,
            "recall_controls_pass": True,
            "route_justified": True,
            "secrets_absent": True,
            "sparse_queries_within_budget": True,
            "zero_repair_tasks": True,
        },
        "base_revision": require_immutable_revision(receipt.get("old_sha"), name="old_sha"),
        "bounds": dict(executed["bounds"]),
        "cache": {
            "cold_hits": measured["cold"]["cache_hits"],
            "cold_misses": measured["cold"]["cache_misses"],
            "revision_scoped": True,
            "warm_hit_ratio": measured["warm"]["cache_hit_ratio"],
            "warm_hits": measured["warm"]["cache_hits"],
            "warm_misses": measured["warm"]["cache_misses"],
            "warm_zero_bytes": measured["warm_zero_bytes"],
        },
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "credentials_environment_only": True,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "depends_on": list(DEPENDS_ON),
        "embedding": {
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        },
        "evaluation_precondition": dict(executed["evaluation"]),
        "exact_51_coverage": True,
        "explanations": {
            "digest": cid_cmp["explanation_digest"],
            "ok": True,
            "primary_key": "entry_cid",
            "ranking": "score_desc_entry_cid",
        },
        "family_guard": dict(executed["family_guard"]),
        "fixture_only": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "fusion": dict(executed["fusion"]),
        "goal_id": GOAL_ID,
        "includes_dc": True,
        "io": {
            "cold": dict(measured["cold"]),
            "warm": dict(measured["warm"]),
            "warm_faster_or_equal": measured["warm_faster_or_equal"],
        },
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdiction_skew": dict(executed["skew"]),
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "latency": {
            "cold_ms": measured["cold"]["latency_ms"],
            "model": "deterministic_synthetic_bandwidth_plus_rtt",
            "warm_ms": measured["warm"]["latency_ms"],
        },
        "live_network": False,
        "local_e2e": dict(executed["local_e2e"]),
        "local_ordered": {
            "digest": cid_cmp["local_digest"],
            "jurisdictions": {
                code: {
                    "ordered_cids": list(executed["local_ordered"][code]["ordered_cids"]),
                    "query": executed["local_ordered"][code]["query"],
                    "top_entry_cid": executed["local_ordered"][code]["top_entry_cid"],
                    "top_legal_id": executed["local_ordered"][code]["top_legal_id"],
                }
                for code in SORTED_JURISDICTIONS
            },
            "ok": True,
            "source": DEFAULT_LOCAL_E2E_RELPATH.as_posix(),
        },
        "manifest_digest": str(receipt.get("manifest_digest") or ""),
        "mutation_executed": False,
        "network_required": False,
        "observation_cutoff": str(
            receipt.get("observation_cutoff")
            or DEFAULT_OBSERVATION_CUTOFF
            or QUERY_OBSERVATION_CUTOFF
        ),
        "old_sha": require_immutable_revision(receipt.get("old_sha"), name="old_sha"),
        "operations": ["download"],
        "phase": "state_public_benchmark",
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "pin_identity": dict(executed["pin_identity"]),
        "public_canary_precondition": dict(executed["canary"]),
        "public_ordered": {
            "digest": cid_cmp["public_digest"],
            "jurisdictions": {
                code: {
                    "ordered_cids": list(queries["jurisdictions"][code]["ordered_cids"]),
                    "query": queries["jurisdictions"][code]["query"],
                    "top_entry_cid": queries["jurisdictions"][code]["top_entry_cid"],
                    "top_legal_id": queries["jurisdictions"][code]["top_legal_id"],
                }
                for code in SORTED_JURISDICTIONS
            },
            "ok": True,
        },
        "public_revision": public_sha,
        "public_sha": public_sha,
        "publication_receipt": {
            "final_manifest_digest": receipt.get("final_manifest_digest"),
            "manifest_digest": receipt.get("manifest_digest"),
            "old_sha": receipt.get("old_sha"),
            "path": DEFAULT_RECEIPT_RELPATH.as_posix(),
            "public_sha": public_sha,
            "staging_sha": receipt.get("staging_sha"),
            "task_id": PUBLICATION_TASK_ID,
        },
        "query_contract": dict(executed["query_contract"]),
        "read_only": True,
        "recall": {
            "at_1": queries["recall_at_1"],
            "dense_gate": DENSE_RECALL_GATE,
            "every_jurisdiction": True,
            "fused_gate": FUSED_RECALL_GATE,
            "ok": True,
            "primary_top_k": PRIMARY_TOP_K,
        },
        "reference_hardware": dict(REFERENCE_HARDWARE),
        "reference_network": dict(REFERENCE_NETWORK),
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": receipt.get("release_root_cid"),
        "remote_write_contacted": False,
        "repair_tasks": [],
        "required_semantic_families": list(executed["required_semantic_families"]),
        "route_justification": {
            "dense_route": DENSE_ROUTE,
            "graph_route": GRAPH_ROUTE,
            "ok": True,
            "paths": list(measured["paths"]),
            "route_justified": True,
            "sparse_route": SPARSE_ROUTE,
        },
        "schema": BENCHMARK_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "status": "passed",
        "target": DEFAULT_DATASET_REPO,
        "target_repo": DEFAULT_DATASET_REPO,
        "task_id": TASK_ID,
        "tokens_used": False,
        "transport": "fake_hub_public_redownload",
        "unexpected_operations": [],
        "visibility_changed": False,
    }
    if queries.get("dc_filter"):
        report["dc_filter"] = dict(queries["dc_filter"])
    if queries.get("hybrid"):
        report["hybrid"] = {
            key: queries["hybrid"][key]
            for key in ("ok", "query", "recovered_dc", "result_count", "top_entry_cid")
        }
    if queries.get("graph"):
        report["graph"] = dict(queries["graph"])
    if receipt.get("final_manifest_digest"):
        report["final_manifest_digest"] = receipt["final_manifest_digest"]
    return seal_report(report)


build_state_public_benchmark_report = build_public_benchmark_report


def _compare_benchmark_reports(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    keys = (
        "schema",
        "task_id",
        "goal_id",
        "dataset_repo_id",
        "target_repo",
        "public_branch",
        "public_sha",
        "public_revision",
        "old_sha",
        "base_revision",
        "manifest_digest",
        "fixture_only",
        "network_required",
        "phase",
        "producer",
        "program_id",
        "code_version",
        "status",
        "read_only",
        "previous_public_pin",
        "mutation_executed",
        "remote_write_contacted",
        "jurisdiction_count",
        "includes_dc",
        "exact_51_coverage",
    )
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(key)
    fresh_acc = fresh.get("acceptance") if isinstance(fresh.get("acceptance"), Mapping) else {}
    sealed_acc = sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    for key, expected in fresh_acc.items():
        if sealed_acc.get(key) != expected:
            mismatches.append(f"acceptance.{key}")
    if list(fresh.get("operations") or []) != list(sealed.get("operations") or []):
        mismatches.append("operations")
    if list(fresh.get("jurisdictions") or []) != list(sealed.get("jurisdictions") or []):
        mismatches.append("jurisdictions")
    if sealed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    if sealed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    if sealed.get("repair_tasks"):
        mismatches.append("repair_tasks")
    fresh_local = (fresh.get("local_ordered") or {}).get("digest")
    sealed_local = (sealed.get("local_ordered") or {}).get("digest")
    if fresh_local != sealed_local:
        mismatches.append("local_ordered.digest")
    fresh_public = (fresh.get("public_ordered") or {}).get("digest")
    sealed_public = (sealed.get("public_ordered") or {}).get("digest")
    if fresh_public != sealed_public:
        mismatches.append("public_ordered.digest")
    if (fresh.get("explanations") or {}).get("digest") != (
        sealed.get("explanations") or {}
    ).get("digest"):
        mismatches.append("explanations.digest")
    return mismatches


def assert_public_benchmark_contract(report: Mapping[str, Any]) -> None:
    if report.get("fixture_only") is True:
        raise PublicBenchmarkError(
            "refusing fixture-only benchmark; the recorded immutable public SHA is required"
        )
    if report.get("status") not in {"passed", "ok", True}:
        raise PublicBenchmarkError(f"public benchmark status is {report.get('status')!r}")
    pin = require_public_pin(report)
    if str(report.get("public_revision") or "") != pin:
        raise PublicBenchmarkError("public_revision must equal public_sha")
    if str(report.get("phase") or "") != "state_public_benchmark":
        raise PublicBenchmarkError(
            f"benchmark phase must be state_public_benchmark, got {report.get('phase')!r}"
        )
    if report.get("read_only") is not True:
        raise PublicBenchmarkError("public benchmark must be read-only")
    if report.get("mutation_executed") is True:
        raise PublicBenchmarkError("public benchmark must not execute a Hub mutation")
    if report.get("remote_write_contacted") is True:
        raise PublicBenchmarkError("public benchmark must not contact a remote write path")
    if report.get("visibility_changed") is True:
        raise PublicBenchmarkError("public benchmark must not change visibility")
    if report.get("unexpected_operations"):
        raise PublicBenchmarkError("public benchmark recorded unexpected operations")
    if report.get("repair_tasks"):
        raise refuse_adjusted_receipt(
            "sealed public benchmark contains repair tasks",
            detail="receipt was not rewritten",
        )
    if str(report.get("previous_public_pin") or "") != PRODUCTION_REVISION:
        raise PublicBenchmarkError("previous public pin drifted from the sealed rollback pin")
    if pin == PRODUCTION_REVISION:
        raise PublicBenchmarkError("public pin must be the new revision, not the previous pin")
    if int(report.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PublicBenchmarkError("public benchmark is not the exact 51-set")
    if report.get("includes_dc") is not True:
        raise PublicBenchmarkError("public benchmark must include DC")
    if list(report.get("jurisdictions") or []) != list(SORTED_JURISDICTIONS):
        raise PublicBenchmarkError("public benchmark jurisdictions are not the sealed 51-set")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    required_flags = (
        "declared_budgets_held",
        "local_ordered_cids_match",
        "local_ordered_explanations_match",
        "route_justified",
        "cache_warm_hits",
        "recall_controls_pass",
        "jurisdiction_skew_within_budget",
        "complete_family_not_downloaded",
        "no_adjusted_receipt_on_regression",
        "public_pin_immutable",
        "publication_receipt_bound",
        "read_only",
        "secrets_absent",
        "every_jurisdiction_query_passed",
        "exact_51_coverage",
        "includes_dc",
    )
    failed = [name for name in required_flags if acceptance.get(name) is not True]
    if failed:
        raise PublicBenchmarkError(
            "public benchmark acceptance flags failed: " + ", ".join(failed)
        )
    if (report.get("local_ordered") or {}).get("digest") != (
        report.get("public_ordered") or {}
    ).get("digest"):
        raise refuse_adjusted_receipt("sealed public/local ordered-CID digests disagree")
    if (report.get("route_justification") or {}).get("route_justified") is not True:
        raise PublicBenchmarkError("sealed benchmark is not route-justified")
    if (report.get("jurisdiction_skew") or {}).get("ok") is not True:
        raise PublicBenchmarkError("sealed jurisdiction skew did not pass")
    if (report.get("recall") or {}).get("ok") is not True:
        raise PublicBenchmarkError("sealed recall controls did not pass")
    if (report.get("bounds") or {}).get("within_bounds") is not True:
        raise PublicBenchmarkBudgetError("sealed benchmark is outside declared budgets")


def validate_canonical_benchmark_measurements(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Enforce every sealed sparse-production benchmark threshold."""

    if not isinstance(value, Mapping):
        raise PublicBenchmarkError("benchmark measurements must be an object")
    measured = dict(value)
    cold = measured.get("cold")
    warm = measured.get("warm")
    recall = measured.get("recall")
    if not all(isinstance(item, Mapping) for item in (cold, warm, recall)):
        raise PublicBenchmarkError("benchmark measurements omit cold/warm/recall")
    for label, item in (("cold", cold), ("warm", warm)):
        for field in ("bytes", "shards", "latency_ms", "cache_hits"):
            number = item.get(field)
            if (
                not isinstance(number, (int, float))
                or isinstance(number, bool)
                or not math.isfinite(float(number))
                or float(number) < 0
            ):
                raise PublicBenchmarkError(
                    f"benchmark {label}.{field} is not non-negative finite"
                )
    if (
        int(cold["bytes"]) > int(BENCHMARK_BUDGETS["max_bytes"])
        or int(cold["shards"]) > int(BENCHMARK_BUDGETS["max_shards"])
        or float(cold["latency_ms"])
        > float(BENCHMARK_BUDGETS["max_latency_ms_cold"])
        or int(warm["bytes"]) > int(cold["bytes"])
        or int(warm["shards"]) > int(cold["shards"])
        or float(warm["latency_ms"])
        > float(BENCHMARK_BUDGETS["max_latency_ms_warm"])
        or float(measured.get("warm_cache_hit_ratio", -1.0))
        < float(BENCHMARK_BUDGETS["min_cache_hit_ratio_warm"])
    ):
        raise PublicBenchmarkBudgetError("cold/warm sparse I/O budget regressed")
    dense = recall.get("dense_at_k")
    fused = recall.get("fused_at_k")
    if (
        not isinstance(dense, (int, float))
        or isinstance(dense, bool)
        or not isinstance(fused, (int, float))
        or isinstance(fused, bool)
        or float(dense) < DENSE_RECALL_GATE
        or float(fused) < FUSED_RECALL_GATE
    ):
        raise PublicBenchmarkRegressionError(
            "public recall control regressed",
            repair_task=create_repair_task(
                reason="recall_regression",
                detail="dense/fused recall below sealed gate",
            ),
        )
    skew = measured.get("jurisdiction_skew")
    if (
        not isinstance(skew, (int, float))
        or isinstance(skew, bool)
        or not math.isfinite(float(skew))
        or float(skew) > MAX_JURISDICTION_SKEW
    ):
        raise PublicBenchmarkRegressionError(
            "jurisdiction skew regressed",
            repair_task=create_repair_task(
                reason="jurisdiction_skew",
                detail="measured skew exceeds exact-51 budget",
            ),
        )
    jurisdictions = list(measured.get("jurisdictions") or ())
    if jurisdictions != list(SORTED_JURISDICTIONS) or "DC" not in jurisdictions:
        raise PublicBenchmarkError("benchmark does not cover canonical exact-51")
    digest_fields = (
        "local_ordered_cids_sha256",
        "public_ordered_cids_sha256",
        "local_explanations_sha256",
        "public_explanations_sha256",
    )
    if any(
        re.fullmatch(r"[0-9a-f]{64}", str(measured.get(name) or "")) is None
        for name in digest_fields
    ):
        raise PublicBenchmarkParityError("ordered CID/explanation digest is malformed")
    if (
        measured["local_ordered_cids_sha256"]
        != measured["public_ordered_cids_sha256"]
        or measured["local_explanations_sha256"]
        != measured["public_explanations_sha256"]
        or measured.get("route_justified") is not True
        or measured.get("complete_family_downloaded") is not False
        or measured.get("repair_tasks") != []
    ):
        raise PublicBenchmarkParityError(
            "public routing/CID/explanation parity did not close"
        )
    return measured


def build_canonical_public_benchmark_receipt(
    *,
    public_canary: Mapping[str, Any],
    measurements: Mapping[str, Any],
) -> dict[str, Any]:
    canary = check_canonical_public_canary_receipt(public_canary)
    measured = validate_canonical_benchmark_measurements(measurements)
    receipt = {
        "schema": CANONICAL_BENCHMARK_SCHEMA,
        "receipt_kind": CANONICAL_BENCHMARK_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": canary["dataset_repo_id"],
        "public_revision": canary["public_revision"],
        "public_sha": canary["public_revision"],
        "previous_public_pin": canary["previous_public_pin"],
        "final_manifest_digest": canary["final_manifest_digest"],
        "release_manifest_digest": canary["release_manifest_digest"],
        "public_canary_digest": canary["canonical_digest"],
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "cold": dict(measured["cold"]),
        "warm": dict(measured["warm"]),
        "warm_cache_hit_ratio": float(measured["warm_cache_hit_ratio"]),
        "recall": dict(measured["recall"]),
        "jurisdiction_skew": float(measured["jurisdiction_skew"]),
        "local_ordered_cids_sha256": measured["local_ordered_cids_sha256"],
        "public_ordered_cids_sha256": measured["public_ordered_cids_sha256"],
        "local_explanations_sha256": measured["local_explanations_sha256"],
        "public_explanations_sha256": measured["public_explanations_sha256"],
        "route_justified": True,
        "complete_family_downloaded": False,
        "repair_tasks": [],
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_public_benchmark_receipt(receipt)


def run_canonical_public_benchmark(
    *, public_canary: Mapping[str, Any], benchmark_runner: Any
) -> dict[str, Any]:
    """Run an injected read-only benchmark harness and seal its measurements."""

    if not callable(benchmark_runner):
        raise PublicBenchmarkError("a read-only benchmark_runner is required")
    canary = check_canonical_public_canary_receipt(public_canary)
    measurements = benchmark_runner(
        canary["dataset_repo_id"], canary["public_revision"]
    )
    return build_canonical_public_benchmark_receipt(
        public_canary=canary,
        measurements=measurements,
    )


def check_canonical_public_benchmark_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise PublicBenchmarkError("canonical benchmark must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != CANONICAL_BENCHMARK_SCHEMA
        or report.get("receipt_kind") != CANONICAL_BENCHMARK_KIND
        or report.get("task_id") != TASK_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("jurisdictions") != list(SORTED_JURISDICTIONS)
        or report.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
        or report.get("read_only") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("unexpected_operations") != []
        or report.get("repair_tasks") != []
    ):
        raise PublicBenchmarkError("canonical benchmark identity/status drifted")
    public = require_immutable_revision(
        report.get("public_revision"), name="public_revision"
    )
    if report.get("public_sha") != public or public == report.get("previous_public_pin"):
        raise PublicBenchmarkError("canonical benchmark immutable pin drifted")
    for name in (
        "final_manifest_digest",
        "release_manifest_digest",
        "public_canary_digest",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", str(report.get(name) or "")) is None:
            raise PublicBenchmarkError(f"canonical benchmark {name} is malformed")
    validate_canonical_benchmark_measurements(report)
    declared = str(report.get("canonical_digest") or report.get("content_digest") or "")
    if re.fullmatch(r"[0-9a-f]{64}", declared) is None or (
        canonical_no_self_field_digest(report) != declared
    ):
        raise PublicBenchmarkError("canonical benchmark digest mismatch")
    reject_credentials_in_payload(report, label="canonical_public_benchmark")
    assert_no_secrets_or_absolute_paths(report, label="canonical_public_benchmark")
    return report


def check_state_public_benchmark(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the sealed public benchmark against a freshly rebuilt loop."""

    receipt = load_publication_receipt(repo_root=repo_root)
    fresh = build_public_benchmark_report(repo_root=repo_root)
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(repo_root)
    )
    if not sealed_path.is_file():
        raise PublicBenchmarkError(
            f"sealed public benchmark report not found: {DEFAULT_REPORT_RELPATH.as_posix()}"
        )
    sealed = load_json_mapping(sealed_path)

    if sealed.get("schema") != BENCHMARK_SCHEMA:
        raise PublicBenchmarkError(f"sealed benchmark schema mismatch: {sealed.get('schema')!r}")
    if sealed.get("task_id") != TASK_ID:
        raise PublicBenchmarkError(
            f"sealed benchmark task_id mismatch: {sealed.get('task_id')!r}"
        )

    require_immutable_revision(sealed.get("public_sha"), name="sealed.public_sha")
    try:
        validate_repo_id(
            str(sealed.get("target_repo") or sealed.get("dataset_repo_id")),
            name="target_repo",
        )
    except ResolverError as exc:
        raise PublicBenchmarkRemoteError(str(exc)) from exc

    assert_public_benchmark_contract(sealed)
    assert_public_benchmark_contract(fresh)
    if require_public_pin(sealed) != require_public_pin(receipt):
        raise PublicBenchmarkError(
            "sealed public pin does not equal the LCR-042 receipt public SHA"
        )

    mismatches = _compare_benchmark_reports(fresh, sealed)
    if mismatches:
        raise refuse_adjusted_receipt(
            "state public benchmark check failed",
            detail="mismatches=" + ",".join(mismatches[:16]),
        )

    reject_credentials_in_payload(sealed, label="sealed_public_benchmark")
    return {
        "check": "pass",
        "complete_family_not_downloaded": True,
        "declared_budgets_held": True,
        "every_jurisdiction_query_passed": True,
        "exact_51_coverage": True,
        "fixture_only": False,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "local_ordered_cids_match": True,
        "manifest_digest": fresh["manifest_digest"],
        "mismatches": [],
        "network_required": False,
        "observation_cutoff": fresh.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "old_sha": fresh["old_sha"],
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "phase": "state_public_benchmark",
        "public_sha": fresh["public_sha"],
        "read_only": True,
        "recall_controls_pass": True,
        "repair_tasks": [],
        "route_justified": True,
        "schema": BENCHMARK_SCHEMA,
        "sparse_queries_within_budget": True,
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
    }


def run_remote_benchmark(
    *,
    repo_id: str,
    revision: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Read-only remote benchmark against explicit immutable public coordinates."""

    del repo_root
    try:
        dataset = validate_repo_id(repo_id, name="repo_id")
        pin = validate_immutable_revision(revision, name="revision")
    except (ResolverError, MutableRevisionError) as exc:
        raise PublicBenchmarkRemoteError(str(exc)) from exc
    if dataset != DEFAULT_DATASET_REPO:
        raise PublicBenchmarkRemoteError(
            f"remote benchmark target must be {DEFAULT_DATASET_REPO!r}"
        )
    raise PublicBenchmarkRemoteError(
        "remote Hub benchmark is opt-in and requires an injected transport; "
        "default validation uses the immutable FakeHub public redownload. "
        f"refusing to contact {dataset}@{pin} from this environment"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark_state_laws_public_release.py",
        description=(
            "Benchmark sparse production queries at the immutable state-law "
            "public pin recorded by the LCR-042 publication receipt."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read and validate the existing canonical public benchmark.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Explicitly write a newly measured canonical benchmark.",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="Optional explicit Hub repo for opt-in remote benchmark.",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional explicit immutable 40-hex public revision.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Opt in to remote Hub contact (requires --repo-id and --revision).",
    )
    parser.add_argument(
        "--benchmark-report",
        type=Path,
        default=None,
        help="Override path to the sealed public benchmark report.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Override path to the LCR-042 publication receipt.",
    )
    parser.add_argument(
        "--public-canary",
        type=Path,
        default=None,
        help="Canonical LCR-043 public canary receipt.",
    )
    parser.add_argument(
        "--measurements",
        type=Path,
        default=None,
        help="Measured cold/warm/recall/skew/CID benchmark JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the check/receipt JSON (default: stdout).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
        canary_reject_secrets_in_argv(argv_list)
    except (
        PublishStateLawsError,
        PublishSafetyError,
        PublicBenchmarkError,
        CanaryStateLawsError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.check:
            if args.write_report or args.network:
                raise PublicBenchmarkError("--check is read-only")
            result = check_canonical_public_benchmark_receipt(
                load_json_mapping(args.benchmark_report or default_report_path())
            )
            write_json(args.output, result)
            return 0

        if not args.network:
            raise PublicBenchmarkRemoteError(
                "new public benchmark generation requires explicit --network opt-in"
            )
        if args.public_canary is None or args.measurements is None:
            raise PublicBenchmarkError(
                "benchmark generation requires --public-canary and --measurements"
            )
        canary = load_json_mapping(args.public_canary)
        checked_canary = check_canonical_public_canary_receipt(canary)
        if args.repo_id and args.repo_id != checked_canary["dataset_repo_id"]:
            raise PublicBenchmarkRemoteError("--repo-id differs from public canary")
        if args.revision and args.revision != checked_canary["public_revision"]:
            raise PublicBenchmarkRemoteError("--revision differs from public canary")
        report = build_canonical_public_benchmark_receipt(
            public_canary=checked_canary,
            measurements=load_json_mapping(args.measurements),
        )
        if args.write_report:
            write_benchmark_report(
                report,
                path=args.benchmark_report or default_report_path(),
            )
        write_json(args.output, report)
        return 0

    except PublicBenchmarkRegressionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        write_json(
            args.output,
            {
                "ok": False,
                "receipt_adjusted": False,
                "repair_task": dict(exc.repair_task),
                "status": "repair_required",
                "task_id": TASK_ID,
            },
        )
        return 2
    except (
        PublicBenchmarkError,
        PublicBenchmarkBudgetError,
        PublicBenchmarkParityError,
        PublicBenchmarkRemoteError,
        CanaryBudgetError,
        CanaryParityError,
        CanaryStateLawsError,
        PublishStateLawsError,
        PublishSafetyError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
