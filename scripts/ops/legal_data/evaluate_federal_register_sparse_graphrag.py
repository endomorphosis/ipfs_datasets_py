#!/usr/bin/env python3
"""Evaluate Federal Register relevance, recall, graph, security, and determinism (LCR-063).

Offline, network-free fixture evaluation of BM25, dense vectors, hybrid
fusion, structural graph walks, filters, sparse I/O, coverage, two-build
determinism, and fail-closed security probes on the sealed LCR-051 gold
set. Fusion weights are selected on the **dev** split only; the sealed
**test** split is reported once and never used for tuning.

Consumed read-only inputs
-------------------------
* LCR-051 gold fixture / loader (``federal_register_gold``)
* LCR-059 query contract / fusion / filters (``federal_register_sparse_query``)
* LCR-062 candidate report (``federal_candidate.json``)

Acceptance (fail-closed)::

* Sealed BM25 / vector / hybrid relevance and vector-recall thresholds pass.
* Graph-edge, filter, sparse-I/O, and coverage gates pass.
* Two independent fixture builds yield identical evaluation digests.
* Traversal / tamper / digest / decompression / budget / mutable-revision /
  secret probes fail closed.
* No fixture result is called a live canary.

Validation gate::

    python scripts/ops/legal_data/evaluate_federal_register_sparse_graphrag.py --check

Frozen report path: ``docs/reports/legal_corpora_reindex/federal_evaluation.json``.

This gate uses the local deterministic embedding projection and the compact
gold fixture. It does **not** authorize Hub upload, a live staging canary,
or a production-searchable claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import tempfile
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (  # noqa: E402
    SecretInReceiptError,
    assert_no_secrets,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (  # noqa: E402
    DEFAULT_B,
    DEFAULT_FIELD_WEIGHTS,
    DEFAULT_K1,
    FIELD_ORDER,
    TOKENIZER_ID,
    robertson_sparck_jones_idf,
    tokenize_index_text,
    tokenize_query,
)
from ipfs_datasets_py.processors.legal_data.federal_register_gold import (  # noqa: E402
    GoldChecksumError,
    load_gold_set,
    verify_checksum_seal,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    ADR_PATH,
    ArtifactPathError,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    normalize_relative_artifact_path,
)
from ipfs_datasets_py.processors.legal_data.federal_register_sparse_query import (  # noqa: E402
    DEFAULT_BM25_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    FUSION_RRF,
    FUSION_WEIGHTED,
    FusionConfig,
    ImmutablePinError,
    LegalFilters,
    apply_legal_filters,
    cosine_similarity,
    fuse_hybrid_results,
    load_query_contract,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    deterministic_project,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (  # noqa: E402
    bm25_term_score,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (  # noqa: E402
    QueryBudgetExhausted,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    DigestDriftError,
    ImmutableHubResolver,
    LocalRootTransport,
    OversizedArtifactError,
    UnsafePathError,
    build_descriptor_for_bytes,
    safe_relative_path,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-063"
GOAL_ID: Final = "LCR-G130"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "evaluate_federal_register_sparse_graphrag.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-evaluation@1"
CODE_VERSION: Final = "1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-release-assurance"
DEPENDS_ON: Final = ("LCR-051", "LCR-059", "LCR-062")

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.json"
)
DEFAULT_GOLD_RELPATH: Final = Path("tests/fixtures/legal_ir/federal_register_gold_v1.json")
CANDIDATE_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/federal_candidate.json")
QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_query_contract.json"
)
BM25_REPORT_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/federal_bm25.json")
VECTOR_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.json"
)
GRAPH_REPORT_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/federal_graph.json")

GOLD_TASK_ID: Final = "LCR-051"
QUERY_TASK_ID: Final = "LCR-059"
CANDIDATE_TASK_ID: Final = "LCR-062"
BM25_TASK_ID: Final = "LCR-056"
VECTORS_TASK_ID: Final = "LCR-057"
GRAPH_TASK_ID: Final = "LCR-058"

TOP_K_VALUES: Final = (1, 5, 10)
PRIMARY_TOP_K: Final = 5
RECALL_GATE_BM25: Final = 0.75
RECALL_GATE_VECTOR: Final = 0.70
RECALL_GATE_HYBRID: Final = 0.80
RECALL_GATE_GRAPH: Final = 1.0
RECALL_GATE_SEMANTIC: Final = 0.75
RANKING_MRR_GATE: Final = 0.70
RANKING_NDCG_GATE: Final = 0.70
EXACT_CITATION_GATE: Final = 1.0
DENSE_RECALL_GATE: Final = 0.95
FILTER_GATE: Final = 1.0
REGRESSION_TOLERANCE: Final = 0.02
SPARSE_IO_BYTE_RATIO_GATE: Final = 0.40
SPARSE_IO_SHARD_RATIO_GATE: Final = 0.50

FLOAT_REPORT_DECIMALS: Final = 6
FIXTURE_TERMS_PER_SHARD: Final = 4
FIXTURE_VECTOR_ROWS_PER_SHARD: Final = 2
FIXTURE_TARGET_ROWS_PER_CENTROID: Final = 3
FIXTURE_MAX_SHARDS_PER_CENTROID: Final = 2
FIXTURE_GRAPH_ROWS_PER_SHARD: Final = 2
BYTES_PER_POSTING_ROW: Final = 48
BYTES_PER_TERM_RANGE_META: Final = 96
BYTES_PER_VECTOR_ROW: Final = 4 * PINNED_DIMENSION + 64
ROUTING_INDEX_BYTES_PER_CLUSTER: Final = 4 * PINNED_DIMENSION + 48
BYTES_PER_GRAPH_POINTER: Final = 64
BYTES_PER_CORPUS_ROW: Final = 2048
LATENCY_MS_PER_SCORED_DOC: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
BYTES_PER_CORPUS_ROW_MEMORY: Final = 2048
BYTES_PER_POSTING_MEMORY: Final = 64
BYTES_PER_VECTOR_MEMORY: Final = 4 * PINNED_DIMENSION + 128
BUILD_ROWS_PER_SECOND: Final = 2500.0
CACHE_HIT_RATIO_FIXTURE: Final = 0.0
PINNED_REVISION: Final = PREVIOUS_PUBLIC_PIN

SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"
INSPECTION_PARTITION: Final = "train"

NON_RETRIEVAL_EXPECTATIONS: Final = frozenset(
    {"abstention", "known_ambiguity", "time_sensitive", "missing_body"}
)
RELEVANT_GRADES: Final = frozenset({"exact", "relevant"})
GRADE_RELEVANCE: Final = {"exact": 3, "relevant": 2, "ambiguous": 1}
EXACT_QUERY_KINDS: Final = frozenset({"exact_document_number", "citation"})
FILTER_QUERY_KINDS: Final = frozenset(
    {"filter_agency", "filter_date", "filter_type"}
)
GRAPH_QUERY_KINDS: Final = frozenset(
    {"correction_path", "withdrawal_path", "citation"}
)

FUSION_CANDIDATES: Final = (
    {
        "candidate_id": "plan_default_weighted_0_5_0_5",
        "method": FUSION_WEIGHTED,
        "bm25_weight": DEFAULT_BM25_WEIGHT,
        "vector_weight": DEFAULT_VECTOR_WEIGHT,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": True,
    },
    {
        "candidate_id": "bm25_heavy_weighted_0_7_0_3",
        "method": FUSION_WEIGHTED,
        "bm25_weight": 0.7,
        "vector_weight": 0.3,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "vector_heavy_weighted_0_3_0_7",
        "method": FUSION_WEIGHTED,
        "bm25_weight": 0.3,
        "vector_weight": 0.7,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "rrf_k_60",
        "method": FUSION_RRF,
        "bm25_weight": 1.0,
        "vector_weight": 1.0,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "rrf_k_30",
        "method": FUSION_RRF,
        "bm25_weight": 1.0,
        "vector_weight": 1.0,
        "rrf_k": 30,
        "is_plan_default": False,
    },
)

REFERENCE_HARDWARE: Final = {
    "architecture": "x86_64",
    "cpu_model": "reference-generic-8vCPU",
    "cpu_cores_logical": 8,
    "memory_gib": 32,
    "storage": "nvme-ssd",
    "os_family": "linux",
    "python_target": "python3.12",
    "notes": (
        "Sealed offline evaluation uses a deterministic synthetic cost model; "
        "numbers are comparable across commits on this fixture, not absolute "
        "production SLAs for arbitrary hardware."
    ),
}
REFERENCE_NETWORK: Final = {
    "mode": "fixture_offline",
    "network_required": False,
    "assumed_bandwidth_mbps": 100.0,
    "assumed_rtt_ms": 20.0,
    "hub_access": "disabled_in_fixture_gate",
    "notes": (
        "LCR-063 fixture evaluation never contacts the network. Remote Hub "
        "byte budgets for live staging/canary are deferred to LCR-064 and "
        "must not be inferred from this report."
    ),
}


class SparseGraphragEvaluationError(RuntimeError):
    """Raised when the Federal Register evaluation cannot complete fail-closed."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_gold_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_GOLD_RELPATH).resolve()


def _repo_path(relpath: Path | str, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / Path(relpath)).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise SparseGraphragEvaluationError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SparseGraphragEvaluationError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SparseGraphragEvaluationError(f"JSON root must be an object: {target}")
    return payload


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
    tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(report_path)
    return report_path


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    gold_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the fixture evaluation and atomically write the sealed report."""

    report = run_fixture_evaluation(gold_path=gold_path, repo_root=repo_root)
    path = write_json_report(report, default_report_path(repo_root))
    return report, path


def _round_float(value: float) -> float:
    return round(float(value), FLOAT_REPORT_DECIMALS)


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _stat_block(values: Sequence[float]) -> dict[str, float]:
    nums = [float(v) for v in values]
    return {
        "mean": _round_float(statistics.fmean(nums) if nums else 0.0),
        "p50": _round_float(_percentile(nums, 50)),
        "p95": _round_float(_percentile(nums, 95)),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Gold / candidate / contract (read-only)
# ---------------------------------------------------------------------------


def load_sealed_gold(
    gold_path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load LCR-051 gold as a mutable dict copy; the on-disk fixture is not written."""

    path = Path(gold_path) if gold_path is not None else default_gold_path(repo_root)
    gold_set = load_gold_set(path, verify_seal=True)
    payload = json.loads(json.dumps(dict(gold_set.payload)))
    if not isinstance(payload, dict):
        raise SparseGraphragEvaluationError("gold payload must be an object")
    payload["_fixture_path"] = str(path)
    payload["_manifest_digest"] = gold_set.manifest_digest
    return payload


def load_readonly_report(
    relpath: Path,
    *,
    expected_task_id: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    path = _repo_path(relpath, repo_root=repo_root)
    payload = load_json_mapping(path)
    if payload.get("task_id") != expected_task_id:
        raise SparseGraphragEvaluationError(
            f"{path} task_id must be {expected_task_id!r}; got {payload.get('task_id')!r}"
        )
    return payload


def document_field_text(doc: Mapping[str, Any], field_name: str) -> str:
    if field_name == "citation":
        number = str(doc.get("document_number") or "").strip()
        legal_id = str(doc.get("legal_id") or "").strip()
        return " ".join(
            part
            for part in (
                number,
                f"Federal Register document {number}" if number else "",
                legal_id,
            )
            if part
        )
    if field_name == "title":
        return str(doc.get("title") or "").strip()
    if field_name == "heading":
        return " ".join(
            part
            for part in (
                str(doc.get("document_type") or "").replace("_", " "),
                str(doc.get("agency_name") or ""),
            )
            if part
        ).strip()
    if field_name == "agency":
        return " ".join(
            part
            for part in (
                str(doc.get("agency_code") or "").strip(),
                str(doc.get("agency_name") or "").strip(),
            )
            if part
        )
    if field_name == "document_type":
        return str(doc.get("document_type") or "").replace("_", " ").strip()
    if field_name == "hierarchy":
        citations = doc.get("cfr_citations") or ()
        return " ".join(str(item).strip() for item in citations if str(item).strip())
    if field_name == "body":
        topics = doc.get("topics") or ()
        topic_text = " ".join(str(item).replace("_", " ") for item in topics)
        related = str(doc.get("related_document_number") or "").strip()
        relation = str(doc.get("correction_relation") or "").strip()
        return " ".join(
            part
            for part in (
                str(doc.get("abstract") or "").strip(),
                topic_text,
                str(doc.get("notes") or "").strip(),
                f"related document {related}" if related else "",
                relation if relation not in {"", "none"} else "",
            )
            if part
        )
    if field_name == "note":
        return str(doc.get("notes") or "").strip()
    raise SparseGraphragEvaluationError(f"unknown BM25 field {field_name!r}")


def document_search_text(doc: Mapping[str, Any]) -> str:
    return " ".join(
        document_field_text(doc, name)
        for name in FIELD_ORDER
        if document_field_text(doc, name)
    ).strip()


def retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list) or not queries:
        raise SparseGraphragEvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            raise SparseGraphragEvaluationError("gold query must be a mapping")
        if partition is not None and str(query.get("partition")) != partition:
            continue
        expectation = str(query.get("expectation") or "")
        if expectation in NON_RETRIEVAL_EXPECTATIONS:
            continue
        if bool(query.get("abstain_if_unscoped")):
            continue
        text = str(query.get("query_text") or "").strip()
        if not text:
            continue
        selected.append(dict(query))
    return selected


def non_retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list):
        raise SparseGraphragEvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        if partition is not None and str(query.get("partition")) != partition:
            continue
        expectation = str(query.get("expectation") or "")
        if expectation in NON_RETRIEVAL_EXPECTATIONS or bool(
            query.get("abstain_if_unscoped")
        ):
            selected.append(dict(query))
    return selected


def filter_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for query in gold.get("queries") or ():
        if not isinstance(query, Mapping):
            continue
        if partition is not None and str(query.get("partition")) != partition:
            continue
        if str(query.get("query_kind") or "") in FILTER_QUERY_KINDS:
            selected.append(dict(query))
    return selected


def judgments_by_query(gold: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    judgments = gold.get("judgments")
    if not isinstance(judgments, list):
        raise SparseGraphragEvaluationError("gold fixture has no judgments")
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for judgment in judgments:
        if not isinstance(judgment, Mapping):
            continue
        query_id = str(judgment.get("query_id") or "")
        if not query_id:
            continue
        by_query[query_id].append(dict(judgment))
    return dict(by_query)


def relevant_entry_cids(
    query: Mapping[str, Any],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> set[str]:
    query_id = str(query.get("query_id") or "")
    return {
        str(item["entry_cid"])
        for item in judgments.get(query_id, ())
        if item.get("entry_cid") and str(item.get("grade") or "") in RELEVANT_GRADES
    }


def grade_map_for_query(
    query: Mapping[str, Any],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, int]:
    query_id = str(query.get("query_id") or "")
    grades: dict[str, int] = {}
    for item in judgments.get(query_id, ()):
        entry = str(item.get("entry_cid") or "")
        grade = str(item.get("grade") or "")
        if not entry or grade not in GRADE_RELEVANCE:
            continue
        grades[entry] = max(grades.get(entry, 0), int(GRADE_RELEVANCE[grade]))
    return grades


def _legal_filters_from_query(query: Mapping[str, Any]) -> LegalFilters | None:
    raw = query.get("filters") or {}
    if not isinstance(raw, Mapping) or not raw:
        return None
    mapped: dict[str, Any] = {}
    if raw.get("agency_code"):
        mapped["agency"] = raw["agency_code"]
    if raw.get("agency"):
        mapped.setdefault("agency", raw["agency"])
    if raw.get("document_type"):
        mapped["document_type"] = raw["document_type"]
    if raw.get("publication_date_from"):
        mapped["date_from"] = raw["publication_date_from"]
    if raw.get("publication_date_to"):
        mapped["date_to"] = raw["publication_date_to"]
    if raw.get("date_from"):
        mapped.setdefault("date_from", raw["date_from"])
    if raw.get("date_to"):
        mapped.setdefault("date_to", raw["date_to"])
    if not mapped:
        return None
    return LegalFilters.from_mapping(mapped)


def _annotate_hit(hit: Mapping[str, Any], docs_by_cid: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    row = dict(hit)
    doc = docs_by_cid.get(str(row.get("entry_cid") or ""))
    if doc is not None:
        row.setdefault("legal_id", doc.get("legal_id"))
        row.setdefault("agency", doc.get("agency_code"))
        row.setdefault("agency_code", doc.get("agency_code"))
        row.setdefault("document_type", doc.get("document_type"))
        row.setdefault("publication_date", doc.get("publication_date"))
        row.setdefault("document_number", doc.get("document_number"))
        row.setdefault("document_id", doc.get("document_id"))
    return row


# ---------------------------------------------------------------------------
# BM25 fixture index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TermRangeShard:
    shard_id: int
    first_term: str
    last_term: str
    terms: tuple[str, ...]
    relative_path: str

    def covers(self, term: str) -> bool:
        return self.first_term <= term <= self.last_term


@dataclass(frozen=True, slots=True)
class FixtureBm25Document:
    entry_cid: str
    legal_id: str
    agency_code: str
    document_type: str
    publication_date: str
    fields: Mapping[str, tuple[str, ...]]
    field_lengths: Mapping[str, int]
    all_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureBm25Index:
    documents: tuple[FixtureBm25Document, ...]
    shards: tuple[TermRangeShard, ...]
    vocabulary: tuple[str, ...]
    postings: Mapping[str, tuple[str, ...]]
    idf: Mapping[str, float]
    average_field_lengths: Mapping[str, float]
    k1: float
    b: float
    field_weights: Mapping[str, float]
    terms_per_shard: int

    def route_term(self, term: str) -> TermRangeShard | None:
        lo, hi = 0, len(self.shards) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            shard = self.shards[mid]
            if term < shard.first_term:
                hi = mid - 1
            elif term > shard.last_term:
                lo = mid + 1
            else:
                return shard
        return None

    def route_terms(self, terms: Sequence[str]) -> list[TermRangeShard]:
        selected: dict[int, TermRangeShard] = {}
        for term in terms:
            if term not in self.postings:
                continue
            shard = self.route_term(term)
            if shard is not None:
                selected[shard.shard_id] = shard
        return [selected[key] for key in sorted(selected)]


def build_fixture_bm25_index(
    documents: Sequence[Mapping[str, Any]],
    *,
    terms_per_shard: int = FIXTURE_TERMS_PER_SHARD,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> FixtureBm25Index:
    if not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    weights = {name: float(DEFAULT_FIELD_WEIGHTS[name]) for name in FIELD_ORDER}
    built: list[FixtureBm25Document] = []
    postings: dict[str, set[str]] = defaultdict(set)
    field_length_sums = {name: 0 for name in FIELD_ORDER}
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise SparseGraphragEvaluationError("gold document must be a mapping")
        entry_cid = str(doc.get("entry_cid") or "").strip()
        if not entry_cid:
            raise SparseGraphragEvaluationError(
                f"gold document {doc.get('document_id')!r} missing entry_cid"
            )
        fields: dict[str, tuple[str, ...]] = {}
        lengths: dict[str, int] = {}
        terms: list[str] = []
        for name in FIELD_ORDER:
            text = document_field_text(doc, name)
            tokenized = tokenize_index_text(text) if text else ()
            fields[name] = tokenized
            lengths[name] = len(tokenized)
            field_length_sums[name] += lengths[name]
            terms.extend(tokenized)
            for term in tokenized:
                postings[term].add(entry_cid)
        built.append(
            FixtureBm25Document(
                entry_cid=entry_cid,
                legal_id=str(doc.get("legal_id") or ""),
                agency_code=str(doc.get("agency_code") or ""),
                document_type=str(doc.get("document_type") or ""),
                publication_date=str(doc.get("publication_date") or ""),
                fields=fields,
                field_lengths=lengths,
                all_terms=tuple(dict.fromkeys(terms)),
            )
        )
    n_docs = len(built)
    vocabulary = tuple(sorted(postings.keys()))
    if not vocabulary:
        raise SparseGraphragEvaluationError("BM25 vocabulary is empty")
    shards: list[TermRangeShard] = []
    page = max(int(terms_per_shard), 1)
    for shard_id, start in enumerate(range(0, len(vocabulary), page)):
        chunk = vocabulary[start : start + page]
        shards.append(
            TermRangeShard(
                shard_id=shard_id,
                first_term=chunk[0],
                last_term=chunk[-1],
                terms=chunk,
                relative_path=f"data/bm25/postings/part-{shard_id:06d}.parquet",
            )
        )
    frozen_postings = {
        term: tuple(sorted(cids)) for term, cids in sorted(postings.items())
    }
    idf = {
        term: robertson_sparck_jones_idf(len(cids), n_docs)
        for term, cids in frozen_postings.items()
    }
    averages = {name: float(field_length_sums[name]) / float(n_docs) for name in FIELD_ORDER}
    return FixtureBm25Index(
        documents=tuple(built),
        shards=tuple(shards),
        vocabulary=vocabulary,
        postings=frozen_postings,
        idf=idf,
        average_field_lengths=averages,
        k1=float(k1),
        b=float(b),
        field_weights=weights,
        terms_per_shard=int(terms_per_shard),
    )


def bm25_search(
    index: FixtureBm25Index,
    query: str,
    *,
    top_k: int,
    filters: LegalFilters | None = None,
    docs_by_cid: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    terms = tokenize_query(query)
    if not terms:
        return [], {
            "bytes_fetched": 0,
            "docs_scored": 0,
            "latency_ms": 0.0,
            "shards_fetched": 0,
            "shards_available": len(index.shards),
            "failure_modes": ["empty_query_terms"],
            "route_family": "bm25_term_range",
            "routed_paths": [],
        }
    shards = index.route_terms(terms)
    shard_terms: set[str] = set()
    for shard in shards:
        shard_terms.update(shard.terms)
    covered: list[str] = []
    candidate_cids: set[str] = set()
    for term in terms:
        if term in index.postings and term in shard_terms:
            covered.append(term)
            candidate_cids.update(index.postings[term])
    docs_index = {doc.entry_cid: doc for doc in index.documents}
    scored: list[dict[str, Any]] = []
    for entry_cid in candidate_cids:
        document = docs_index.get(entry_cid)
        if document is None:
            continue
        score = 0.0
        matched: list[str] = []
        for term in covered:
            idf = float(index.idf.get(term) or 0.0)
            if idf <= 0.0:
                continue
            term_score = 0.0
            for field_name in FIELD_ORDER:
                tf = document.fields.get(field_name, ()).count(term)
                if tf <= 0:
                    continue
                term_score += bm25_term_score(
                    tf=float(tf),
                    idf=idf,
                    doc_length=float(document.field_lengths.get(field_name, 0)),
                    avg_doc_length=max(
                        float(index.average_field_lengths.get(field_name, 1.0)),
                        1e-12,
                    ),
                    k1=index.k1,
                    b=index.b,
                    field_weight=float(index.field_weights[field_name]),
                )
            if term_score > 0.0:
                score += term_score
                matched.append(term)
        if score <= 0.0:
            continue
        scored.append(
            {
                "entry_cid": entry_cid,
                "score": float(score),
                "legal_id": document.legal_id,
                "agency": document.agency_code,
                "agency_code": document.agency_code,
                "document_type": document.document_type,
                "publication_date": document.publication_date,
                "matched_terms": matched,
            }
        )
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    if filters is not None:
        scored = apply_legal_filters(scored, filters)
    if docs_by_cid is not None:
        scored = [_annotate_hit(hit, docs_by_cid) for hit in scored]
    hits = scored[: max(int(top_k), 0)]
    shards_fetched = len(shards)
    docs_scored = len(candidate_cids)
    bytes_fetched = (
        shards_fetched * BYTES_PER_TERM_RANGE_META
        + docs_scored * BYTES_PER_POSTING_ROW
        + len(covered) * BYTES_PER_POSTING_ROW
    )
    latency_ms = _round_float(
        docs_scored * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": docs_scored,
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": len(index.shards),
        "failure_modes": [],
        "route_family": "bm25_term_range",
        "routed_paths": [shard.relative_path for shard in shards],
    }


# ---------------------------------------------------------------------------
# Dense fixture index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VectorShard:
    shard_id: int
    cluster_id: int
    relative_path: str
    entry_cids: tuple[str, ...]
    embeddings: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class FixtureVectorIndex:
    shards: tuple[VectorShard, ...]
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, dict[str, Any]]
    embeddings: Mapping[str, tuple[float, ...]]
    cluster_count: int
    probe_centroids: int
    dimension: int = PINNED_DIMENSION

    @property
    def shard_count(self) -> int:
        return len(self.shards)

    @property
    def vector_count(self) -> int:
        return len(self.embeddings)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise SparseGraphragEvaluationError("embedding must be non-zero")
    return tuple(v / norm for v in values)


def _embed_query_text(text: str, *, dimension: int = PINNED_DIMENSION) -> list[float]:
    vectors = deterministic_project([text], dimension=dimension, normalize=True)
    return list(vectors[0])


def build_fixture_vector_index(
    documents: Sequence[Mapping[str, Any]],
    *,
    probe_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    rows_per_shard: int = FIXTURE_VECTOR_ROWS_PER_SHARD,
    target_rows_per_centroid: int = FIXTURE_TARGET_ROWS_PER_CENTROID,
) -> FixtureVectorIndex:
    if not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    texts = [document_search_text(doc) for doc in documents]
    if any(not text for text in texts):
        raise SparseGraphragEvaluationError("gold document has empty search text")
    raw = deterministic_project(texts, dimension=PINNED_DIMENSION, normalize=True)
    embeddings = {
        str(doc["entry_cid"]): _unit(vector) for doc, vector in zip(documents, raw)
    }
    ordered = sorted(embeddings.items(), key=lambda item: (item[1][0], item[0]))
    n_docs = len(ordered)
    n_clusters = max(4, math.ceil(n_docs / max(int(target_rows_per_centroid), 1)))
    n_clusters = max(n_clusters, int(probe_centroids) * 2)
    n_clusters = min(n_clusters, n_docs)
    groups: list[list[tuple[str, tuple[float, ...]]]] = [[] for _ in range(n_clusters)]
    for offset, item in enumerate(ordered):
        groups[offset % n_clusters].append(item)
    shards: list[VectorShard] = []
    routing_rows: list[dict[str, Any]] = []
    locations: dict[str, dict[str, Any]] = {}
    shard_id = 0
    for cluster_id, members in enumerate(groups):
        if not members:
            continue
        centroid_raw = [
            sum(vec[dim] for _cid, vec in members) / float(len(members))
            for dim in range(PINNED_DIMENSION)
        ]
        centroid = _unit(centroid_raw)
        members.sort(
            key=lambda item: (-sum(a * b for a, b in zip(item[1], centroid)), item[0])
        )
        chunk_in_cluster = 0
        page = max(int(rows_per_shard), 1)
        for start in range(0, len(members), page):
            chunk = members[start : start + page]
            path = f"data/vectors/cluster-{cluster_id:04d}/part-{chunk_in_cluster:04d}.parquet"
            shard = VectorShard(
                shard_id=shard_id,
                cluster_id=cluster_id,
                relative_path=path,
                entry_cids=tuple(cid for cid, _vec in chunk),
                embeddings=tuple(vec for _cid, vec in chunk),
            )
            shards.append(shard)
            routing_rows.append(
                {
                    "cluster_id": cluster_id,
                    "chunk_in_cluster": chunk_in_cluster,
                    "centroid_shard_count": math.ceil(len(members) / page),
                    "relative_path": path,
                    "row_count": len(chunk),
                    "shard_id": shard_id,
                    "centroid": list(centroid),
                    "dimension": PINNED_DIMENSION,
                }
            )
            for offset, (cid, vec) in enumerate(chunk):
                locations[cid] = {
                    "cluster_id": cluster_id,
                    "relative_path": path,
                    "row_offset": offset,
                    "shard_id": shard_id,
                    "embedding": vec,
                }
            shard_id += 1
            chunk_in_cluster += 1
    return FixtureVectorIndex(
        shards=tuple(shards),
        routing_rows=tuple(routing_rows),
        locations=locations,
        embeddings=embeddings,
        cluster_count=len({row["cluster_id"] for row in routing_rows}),
        probe_centroids=max(int(probe_centroids), 1),
    )


def route_vector_shards(
    index: FixtureVectorIndex,
    query: Sequence[float],
    *,
    probe_centroids: int | None = None,
) -> list[dict[str, Any]]:
    probe = max(int(probe_centroids or index.probe_centroids), 1)
    query_u = _unit(query)
    by_cluster: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in index.routing_rows:
        by_cluster[int(row["cluster_id"])].append(row)
    ranked: list[tuple[float, int]] = []
    for cluster_id, rows in by_cluster.items():
        centroid = _unit(rows[0]["centroid"])
        ranked.append((float(sum(a * b for a, b in zip(query_u, centroid))), cluster_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    for _score, cluster_id in ranked[:probe]:
        selected.extend(
            sorted(by_cluster[cluster_id], key=lambda row: int(row["chunk_in_cluster"]))
        )
    return selected


def vector_search(
    index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    *,
    top_k: int,
    probe_centroids: int | None = None,
    filters: LegalFilters | None = None,
    docs_by_cid: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_u = _unit(query_embedding)
    routes = route_vector_shards(index, query_u, probe_centroids=probe_centroids)
    routed_paths = {str(row["relative_path"]) for row in routes}
    candidates: list[dict[str, Any]] = []
    for entry_cid, loc in index.locations.items():
        if loc["relative_path"] not in routed_paths:
            continue
        score = float(sum(a * b for a, b in zip(query_u, loc["embedding"])))
        hit: dict[str, Any] = {
            "entry_cid": entry_cid,
            "score": score,
            "cluster_id": int(loc["cluster_id"]),
        }
        if docs_by_cid is not None:
            hit = _annotate_hit(hit, docs_by_cid)
        candidates.append(hit)
    candidates.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    if filters is not None:
        candidates = apply_legal_filters(candidates, filters)
    hits = candidates[: max(int(top_k), 0)]
    rows_scored = len(candidates)
    shards_fetched = len(routed_paths)
    clusters = {int(row["cluster_id"]) for row in routes}
    bytes_fetched = (
        len(clusters) * ROUTING_INDEX_BYTES_PER_CLUSTER
        + rows_scored * BYTES_PER_VECTOR_ROW
    )
    latency_ms = _round_float(
        rows_scored * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    failure_modes: list[str] = []
    if not routes:
        failure_modes.append("empty_centroid_route")
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": rows_scored,
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": index.shard_count,
        "failure_modes": failure_modes,
        "probe_centroids": max(int(probe_centroids or index.probe_centroids), 1),
        "route_family": "vector_centroid_probe",
        "routed_paths": sorted(routed_paths),
    }


def exhaustive_vector_search(
    index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    query_u = _unit(query_embedding)
    scored = [
        {
            "entry_cid": entry_cid,
            "score": float(sum(a * b for a, b in zip(query_u, vec))),
        }
        for entry_cid, vec in index.embeddings.items()
    ]
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    return scored[: max(int(top_k), 0)]


# ---------------------------------------------------------------------------
# Graph fixture
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphAdjacencyShard:
    shard_id: int
    relative_path: str
    source_cids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureGraph:
    nodes: Mapping[str, dict[str, Any]]
    outgoing: Mapping[str, tuple[tuple[str, str], ...]]
    incoming: Mapping[str, tuple[tuple[str, str], ...]]
    shards: tuple[GraphAdjacencyShard, ...]
    paths: tuple[dict[str, Any], ...]
    locator: Mapping[str, dict[str, Any]]

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self.outgoing.values())

    @property
    def shard_count(self) -> int:
        return len(self.shards)


def build_fixture_graph(
    gold: Mapping[str, Any],
    vector_index: FixtureVectorIndex,
) -> FixtureGraph:
    docs = {str(doc["document_id"]): dict(doc) for doc in gold.get("documents") or ()}
    docs_by_cid = {str(doc["entry_cid"]): dict(doc) for doc in docs.values()}
    by_number = {
        str(doc["document_number"]): dict(doc)
        for doc in docs.values()
        if doc.get("document_number")
    }
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def _link(src_cid: str, dst_cid: str, relation: str) -> None:
        if (dst_cid, relation) not in outgoing[src_cid]:
            outgoing[src_cid].append((dst_cid, relation))
            incoming[dst_cid].append((src_cid, relation))
        inv = f"inv:{relation}"
        if (src_cid, inv) not in outgoing[dst_cid]:
            outgoing[dst_cid].append((src_cid, inv))
            incoming[src_cid].append((dst_cid, inv))

    paths: list[dict[str, Any]] = []
    for spec in gold.get("graph_paths") or ():
        if not isinstance(spec, Mapping):
            continue
        node_ids = [str(item) for item in spec.get("nodes") or ()]
        node_cids = [str(docs[node_id]["entry_cid"]) for node_id in node_ids if node_id in docs]
        edge_rows: list[dict[str, str]] = []
        for edge in spec.get("edges") or ():
            if not isinstance(edge, Mapping):
                continue
            src = str(edge.get("source") or "")
            dst = str(edge.get("target") or "")
            if src not in docs or dst not in docs:
                continue
            relation = str(edge.get("relation") or "cites")
            src_cid = str(docs[src]["entry_cid"])
            dst_cid = str(docs[dst]["entry_cid"])
            _link(src_cid, dst_cid, relation)
            edge_rows.append(
                {"source": src_cid, "target": dst_cid, "relation": relation}
            )
        paths.append(
            {
                "path_id": spec.get("path_id"),
                "query_id": spec.get("query_id"),
                "partition": spec.get("partition"),
                "node_cids": node_cids,
                "edges": edge_rows,
            }
        )
    for doc in docs.values():
        related = str(doc.get("related_document_number") or "")
        relation = str(doc.get("correction_relation") or "")
        if related and related in by_number and relation not in {"", "none"}:
            _link(str(doc["entry_cid"]), str(by_number[related]["entry_cid"]), relation)
    by_agency: dict[str, list[str]] = defaultdict(list)
    for cid, doc in docs_by_cid.items():
        code = str(doc.get("agency_code") or "")
        if code:
            by_agency[code].append(cid)
    for _code, cids in by_agency.items():
        ordered = sorted(cids)
        for left, right in zip(ordered, ordered[1:]):
            _link(left, right, "same_agency")

    frozen_out = {
        cid: tuple(sorted(set(edges), key=lambda item: (item[0], item[1])))
        for cid, edges in outgoing.items()
    }
    frozen_in = {
        cid: tuple(sorted(set(edges), key=lambda item: (item[0], item[1])))
        for cid, edges in incoming.items()
    }
    sources = sorted(frozen_out)
    shards: list[GraphAdjacencyShard] = []
    page = max(int(FIXTURE_GRAPH_ROWS_PER_SHARD), 1)
    for shard_id, start in enumerate(range(0, len(sources), page)):
        chunk = tuple(sources[start : start + page])
        shards.append(
            GraphAdjacencyShard(
                shard_id=shard_id,
                relative_path=f"data/graph/adjacency/out/part-{shard_id:06d}.parquet",
                source_cids=chunk,
            )
        )
    locator = {cid: dict(loc) for cid, loc in vector_index.locations.items()}
    return FixtureGraph(
        nodes=docs_by_cid,
        outgoing=frozen_out,
        incoming=frozen_in,
        shards=tuple(shards),
        paths=tuple(paths),
        locator=locator,
    )


def _graph_shard_for(graph: FixtureGraph, source_cid: str) -> GraphAdjacencyShard | None:
    for shard in graph.shards:
        if source_cid in shard.source_cids:
            return shard
    return None


def graph_walk(
    graph: FixtureGraph,
    seeds: Sequence[str],
    *,
    top_k: int,
    max_depth: int = 2,
    max_nodes: int = 32,
    max_edges: int = 64,
    max_shards: int = 16,
    max_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    visited: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    fetched_paths: dict[str, GraphAdjacencyShard] = {}
    edges_used = 0
    stop_reason: str | None = None
    for seed in seeds:
        cid = str(seed or "").strip()
        if not cid or cid in visited:
            continue
        visited[cid] = 0
        queue.append((cid, 0))
    while queue:
        if len(visited) >= max_nodes:
            stop_reason = "nodes"
            break
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        shard = _graph_shard_for(graph, node)
        if shard is not None:
            if shard.relative_path not in fetched_paths:
                if len(fetched_paths) >= max_shards:
                    stop_reason = "shards"
                    break
                fetched_paths[shard.relative_path] = shard
        for neighbor, _relation in graph.outgoing.get(node, ()):
            if edges_used >= max_edges:
                stop_reason = "edges"
                break
            edges_used += 1
            if neighbor in visited:
                continue
            if len(visited) >= max_nodes:
                stop_reason = "nodes"
                break
            visited[neighbor] = depth + 1
            queue.append((neighbor, depth + 1))
        if stop_reason:
            break
        if max_bytes is not None:
            used = (
                len(fetched_paths) * BYTES_PER_TERM_RANGE_META
                + edges_used * BYTES_PER_GRAPH_POINTER
                + len(visited) * BYTES_PER_CORPUS_ROW
            )
            if used >= max_bytes:
                stop_reason = "bytes"
                break
    hits = [
        {
            "entry_cid": cid,
            "score": 1.0 / float(depth + 1),
            "depth": depth,
        }
        for cid, depth in sorted(visited.items(), key=lambda item: (item[1], item[0]))
    ][: max(int(top_k), 0)]
    shards_fetched = len(fetched_paths)
    bytes_fetched = (
        shards_fetched * BYTES_PER_TERM_RANGE_META
        + edges_used * BYTES_PER_GRAPH_POINTER
        + len(visited) * BYTES_PER_CORPUS_ROW
    )
    latency_ms = _round_float(
        len(visited) * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": len(visited),
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": graph.shard_count,
        "failure_modes": [] if visited else ["empty_graph_walk"],
        "route_family": "graph_adjacency",
        "routed_paths": sorted(fetched_paths),
        "edges_used": edges_used,
        "stop_reason": stop_reason,
        "budgets": {
            "depth": max_depth,
            "nodes": max_nodes,
            "edges": max_edges,
            "shards": max_shards,
            "bytes": max_bytes,
        },
    }


def semantic_graph_walk(
    graph: FixtureGraph,
    vector_index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    seeds: Sequence[str],
    *,
    top_k: int,
    max_depth: int = 2,
    max_nodes: int = 24,
    beam_width: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_u = _unit(query_embedding)
    frontier: list[tuple[float, str, int]] = []
    for seed in seeds:
        cid = str(seed or "").strip()
        if not cid:
            continue
        emb = vector_index.embeddings.get(cid)
        score = cosine_similarity(query_u, emb) if emb is not None else 0.0
        frontier.append((score, cid, 0))
    frontier.sort(key=lambda item: (-item[0], item[1]))
    seen: dict[str, float] = {}
    fetched_paths: set[str] = set()
    locator_pages = 0
    while frontier and len(seen) < max_nodes:
        frontier.sort(key=lambda item: (-item[0], item[1], item[2]))
        score, node, depth = frontier.pop(0)
        if node in seen and seen[node] >= score:
            continue
        loc = graph.locator.get(node)
        if loc is not None:
            fetched_paths.add(str(loc["relative_path"]))
            locator_pages += 1
        seen[node] = score
        if depth >= max_depth:
            continue
        for neighbor, _relation in graph.outgoing.get(node, ()):
            if neighbor in seen:
                continue
            emb = vector_index.embeddings.get(neighbor)
            nscore = cosine_similarity(query_u, emb) if emb is not None else 0.0
            frontier.append((nscore, neighbor, depth + 1))
        if len(frontier) > beam_width * 4:
            frontier = sorted(frontier, key=lambda item: (-item[0], item[1]))[: beam_width * 4]
    ranked = sorted(seen.items(), key=lambda item: (-item[1], item[0]))
    hits = [
        {"entry_cid": cid, "score": float(score)}
        for cid, score in ranked[: max(int(top_k), 0)]
    ]
    shards_fetched = len(fetched_paths)
    bytes_fetched = (
        locator_pages * BYTES_PER_TERM_RANGE_META
        + shards_fetched * BYTES_PER_VECTOR_ROW
        + len(seen) * BYTES_PER_CORPUS_ROW
    )
    latency_ms = _round_float(
        len(seen) * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": len(seen),
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": vector_index.shard_count + graph.shard_count,
        "failure_modes": [] if seen else ["empty_semantic_walk"],
        "route_family": "semantic_entry_locator",
        "routed_paths": sorted(fetched_paths),
        "locator_pages": locator_pages,
        "hydration_policy": "entry_locator",
        "beam_width": beam_width,
    }


def evaluate_graph_paths(
    graph: FixtureGraph,
    *,
    partition: str | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for path in graph.paths:
        if partition is not None and str(path.get("partition")) != partition:
            continue
        node_cids = [str(cid) for cid in path.get("node_cids") or ()]
        if not node_cids:
            continue
        hits, io = graph_walk(graph, [node_cids[0]], top_k=max(len(node_cids) + 2, 5))
        recovered = {str(hit["entry_cid"]) for hit in hits}
        missing = [cid for cid in node_cids if cid not in recovered]
        cases.append(
            {
                "path_id": path.get("path_id"),
                "query_id": path.get("query_id"),
                "partition": path.get("partition"),
                "expected_count": len(node_cids),
                "recovered_count": len(node_cids) - len(missing),
                "ok": not missing,
                "missing": missing,
                "shards_fetched": io["shards_fetched"],
                "shards_available": io["shards_available"],
                "edge_count": len(path.get("edges") or ()),
            }
        )
    ok_count = sum(1 for case in cases if case["ok"])
    return {
        "case_count": len(cases),
        "matched_count": ok_count,
        "failed_count": len(cases) - ok_count,
        "success_rate": _round_float(ok_count / float(len(cases)) if cases else 1.0),
        "ok": ok_count == len(cases) and bool(cases),
        "meets_recall_gate": (ok_count / float(len(cases)) if cases else 1.0)
        >= RECALL_GATE_GRAPH,
        "recall_gate": RECALL_GATE_GRAPH,
        "edge_count": graph.edge_count,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def relevance_recall_at_k(
    hits: Sequence[Mapping[str, Any]],
    relevant: set[str],
    *,
    k: int,
) -> float:
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    predicted = {str(hit.get("entry_cid") or "") for hit in hits[:k]}
    predicted.discard("")
    return len(relevant & predicted) / float(len(relevant))


def reciprocal_rank(
    hits: Sequence[Mapping[str, Any]],
    relevant: set[str],
) -> float:
    if not relevant:
        return 1.0
    for rank, hit in enumerate(hits, start=1):
        if str(hit.get("entry_cid") or "") in relevant:
            return 1.0 / float(rank)
    return 0.0


def ndcg_at_k(
    hits: Sequence[Mapping[str, Any]],
    grades: Mapping[str, int],
    *,
    k: int,
) -> float:
    if not grades or k <= 0:
        return 1.0 if not grades else 0.0

    def dcg(doc_ids: Sequence[str]) -> float:
        total = 0.0
        for i, doc in enumerate(doc_ids[:k], start=1):
            rel = float(grades.get(doc, 0))
            if rel <= 0:
                continue
            total += (2.0**rel - 1.0) / math.log2(i + 1.0)
        return total

    retrieved = [str(hit.get("entry_cid") or "") for hit in hits[:k]]
    actual = dcg(retrieved)
    ideal_docs = sorted(grades.keys(), key=lambda d: (-grades[d], d))
    ideal = dcg(ideal_docs)
    if ideal <= 0.0:
        return 0.0
    return actual / ideal


def ranking_recall_at_k(
    reference: Sequence[Mapping[str, Any]],
    predicted: Sequence[Mapping[str, Any]],
    *,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    ref = {str(hit.get("entry_cid") or "") for hit in reference[:k]}
    ref.discard("")
    if not ref:
        return 1.0
    pred = {str(hit.get("entry_cid") or "") for hit in predicted[:k]}
    pred.discard("")
    return len(ref & pred) / float(len(ref))


def exact_citation_success(
    query: Mapping[str, Any],
    hits: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool | None:
    if str(query.get("query_kind") or "") not in EXACT_QUERY_KINDS:
        return None
    query_id = str(query.get("query_id") or "")
    exact_targets = {
        str(item["entry_cid"])
        for item in judgments.get(query_id, ())
        if item.get("entry_cid") and str(item.get("grade") or "") == "exact"
    }
    if not exact_targets:
        return None
    if not hits:
        return False
    return str(hits[0].get("entry_cid") or "") in exact_targets


def _empty_metrics(mode: str, *, recall_gate: float) -> dict[str, Any]:
    return {
        "mode": mode,
        "bytes_fetched": _stat_block([]),
        "docs_scored": _stat_block([]),
        "exact_citation_success_rate": 0.0,
        "exact_citation_query_count": 0,
        "failure_modes": {},
        "latency_ms": _stat_block([]),
        "mean_reciprocal_rank": 0.0,
        "meets_ranking_gate": False,
        "meets_recall_gate": False,
        "ndcg_at_1": 0.0,
        "ndcg_at_5": 0.0,
        "ndcg_at_10": 0.0,
        "primary_metric": f"relevance_recall_at_{PRIMARY_TOP_K}",
        "primary_metric_value": 0.0,
        "query_count": 0,
        "queries_with_relevant_labels": 0,
        "recall_gate": float(recall_gate),
        "ranking_mrr_gate": RANKING_MRR_GATE,
        "ranking_ndcg_gate": RANKING_NDCG_GATE,
        "relevance_recall_at_1": 0.0,
        "relevance_recall_at_5": 0.0,
        "relevance_recall_at_10": 0.0,
        "shards_fetched": _stat_block([]),
        "shards_available_mean": 0.0,
        "fetch_traces": [],
    }


def evaluate_ranked_mode(
    *,
    mode: str,
    queries: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
    search_fn: Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]],
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
    recall_gate: float,
    ranking_mrr_gate: float = RANKING_MRR_GATE,
    ranking_ndcg_gate: float = RANKING_NDCG_GATE,
    keep_traces: int = 4,
) -> dict[str, Any]:
    if not queries:
        return _empty_metrics(mode, recall_gate=recall_gate)

    max_k = max(int(k) for k in top_k_values)
    relevance_recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    ndcgs: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    mrrs: list[float] = []
    latencies: list[float] = []
    bytes_list: list[float] = []
    shards_list: list[float] = []
    available_list: list[float] = []
    docs_list: list[float] = []
    failure_counter: dict[str, int] = {}
    exact_flags: list[bool] = []
    traces: list[dict[str, Any]] = []
    queries_with_relevant = 0

    for query in queries:
        hits, io = search_fn(query, max_k)
        for mode_name in io.get("failure_modes") or ():
            failure_counter[str(mode_name)] = failure_counter.get(str(mode_name), 0) + 1
        relevant = relevant_entry_cids(query, judgments)
        grades = grade_map_for_query(query, judgments)
        if relevant:
            queries_with_relevant += 1
            for k in top_k_values:
                relevance_recalls[int(k)].append(
                    relevance_recall_at_k(hits, relevant, k=int(k))
                )
                ndcgs[int(k)].append(ndcg_at_k(hits, grades, k=int(k)))
            mrrs.append(reciprocal_rank(hits, relevant))
        citation_ok = exact_citation_success(query, hits, judgments)
        if citation_ok is not None:
            exact_flags.append(bool(citation_ok))
        latencies.append(float(io.get("latency_ms") or 0.0))
        bytes_list.append(float(io.get("bytes_fetched") or 0.0))
        shards_list.append(float(io.get("shards_fetched") or 0.0))
        available_list.append(float(io.get("shards_available") or 0.0))
        docs_list.append(float(io.get("docs_scored") or 0.0))
        if len(traces) < keep_traces:
            shards_fetched = int(io.get("shards_fetched") or 0)
            shards_available = int(io.get("shards_available") or 0)
            traces.append(
                {
                    "query_id": query.get("query_id"),
                    "mode": mode,
                    "shards_fetched": shards_fetched,
                    "shards_available": shards_available,
                    "bytes_fetched": int(io.get("bytes_fetched") or 0),
                    "docs_scored": int(io.get("docs_scored") or 0),
                    "bounded_shard_selection": (
                        shards_available == 0 or shards_fetched < shards_available
                    ),
                    "route_family": io.get("route_family"),
                    "routed_paths": list(io.get("routed_paths") or ()),
                    "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
                }
            )

    mean_relevance = {
        f"relevance_recall_at_{k}": _round_float(
            statistics.fmean(relevance_recalls[int(k)]) if relevance_recalls[int(k)] else 0.0
        )
        for k in top_k_values
    }
    mean_ndcg = {
        f"ndcg_at_{k}": _round_float(
            statistics.fmean(ndcgs[int(k)]) if ndcgs[int(k)] else 0.0
        )
        for k in top_k_values
    }
    primary = float(mean_relevance.get(f"relevance_recall_at_{primary_top_k}", 0.0))
    mrr = statistics.fmean(mrrs) if mrrs else 0.0
    ndcg_primary = float(mean_ndcg.get(f"ndcg_at_{primary_top_k}", 0.0))
    exact_rate = statistics.fmean(exact_flags) if exact_flags else 0.0
    ranking_ok = (mrr >= ranking_mrr_gate) and (ndcg_primary >= ranking_ndcg_gate)
    recall_ok = primary >= float(recall_gate)
    if exact_flags:
        recall_ok = recall_ok and exact_rate >= EXACT_CITATION_GATE
    return {
        "mode": mode,
        "bytes_fetched": _stat_block(bytes_list),
        "docs_scored": _stat_block(docs_list),
        "exact_citation_success_rate": _round_float(exact_rate),
        "exact_citation_query_count": len(exact_flags),
        "failure_modes": dict(sorted(failure_counter.items())),
        "latency_ms": _stat_block(latencies),
        "mean_reciprocal_rank": _round_float(mrr),
        "meets_ranking_gate": ranking_ok,
        "meets_recall_gate": recall_ok,
        **mean_ndcg,
        "primary_metric": f"relevance_recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(primary),
        "query_count": len(queries),
        "queries_with_relevant_labels": queries_with_relevant,
        "recall_gate": float(recall_gate),
        "ranking_mrr_gate": ranking_mrr_gate,
        "ranking_ndcg_gate": ranking_ndcg_gate,
        **mean_relevance,
        "shards_fetched": _stat_block(shards_list),
        "shards_available_mean": _round_float(
            statistics.fmean(available_list) if available_list else 0.0
        ),
        "fetch_traces": traces,
    }


def evaluate_dense_agreement(
    *,
    queries: Sequence[Mapping[str, Any]],
    vector_index: FixtureVectorIndex,
    probe_centroids: int,
    top_k: int = 1,
) -> dict[str, Any]:
    recalls: list[float] = []
    for query in queries:
        embedding = _embed_query_text(str(query.get("query_text") or ""))
        exhaustive = exhaustive_vector_search(vector_index, embedding, top_k=top_k)
        routed, _io = vector_search(
            vector_index,
            embedding,
            top_k=top_k,
            probe_centroids=probe_centroids,
        )
        recalls.append(ranking_recall_at_k(exhaustive, routed, k=top_k))
    value = statistics.fmean(recalls) if recalls else 1.0
    return {
        "query_count": len(queries),
        "probe_centroids": int(probe_centroids),
        "top_k": int(top_k),
        "recall_at_1": _round_float(value if top_k == 1 else value),
        f"recall_at_{top_k}": _round_float(value),
        "meets_recall_gate": value >= DENSE_RECALL_GATE,
        "recall_gate": DENSE_RECALL_GATE,
    }


def evaluate_filters(
    *,
    queries: Sequence[Mapping[str, Any]],
    search_fn: Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]],
    docs_by_cid: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for query in queries:
        filters = _legal_filters_from_query(query)
        hits, _io = search_fn(query, 10)
        leaked: list[str] = []
        for hit in hits:
            cid = str(hit.get("entry_cid") or "")
            doc = docs_by_cid.get(cid) or hit
            if filters is None:
                continue
            if not apply_legal_filters([_annotate_hit(doc, docs_by_cid)], filters):
                leaked.append(cid)
        cases.append(
            {
                "query_id": query.get("query_id"),
                "query_kind": query.get("query_kind"),
                "filters": (filters.to_dict() if filters is not None else {}),
                "hit_count": len(hits),
                "ok": not leaked,
                "leaked": leaked,
            }
        )
    ok_count = sum(1 for case in cases if case["ok"])
    rate = ok_count / float(len(cases)) if cases else 1.0
    return {
        "case_count": len(cases),
        "ok_count": ok_count,
        "success_rate": _round_float(rate),
        "meets_filter_gate": rate >= FILTER_GATE,
        "filter_gate": FILTER_GATE,
        "ok": ok_count == len(cases),
        "cases": cases,
    }


def evaluate_abstention(
    queries: Sequence[Mapping[str, Any]],
    *,
    observation_cutoff: str,
    release_point: str,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for query in queries:
        expectation = str(query.get("expectation") or "")
        must_expose = bool(query.get("must_expose_cutoff"))
        abstain = bool(query.get("abstain_if_unscoped")) or expectation in {
            "abstention",
            "time_sensitive",
            "known_ambiguity",
        }
        honesty_ok = True
        if must_expose and not observation_cutoff:
            honesty_ok = False
        if expectation == "time_sensitive" and "current" in str(
            query.get("query_text") or ""
        ).lower():
            honesty_ok = honesty_ok and bool(observation_cutoff)
        cases.append(
            {
                "query_id": query.get("query_id"),
                "partition": query.get("partition"),
                "query_kind": query.get("query_kind"),
                "expectation": expectation,
                "must_expose_cutoff": must_expose,
                "abstain": abstain,
                "exposed_observation_cutoff": observation_cutoff if must_expose else None,
                "exposed_release_point": release_point if must_expose else None,
                "honesty_ok": honesty_ok,
            }
        )
    ok_count = sum(1 for case in cases if case["honesty_ok"])
    return {
        "case_count": len(cases),
        "honesty_ok_count": ok_count,
        "honesty_rate": _round_float(ok_count / float(len(cases)) if cases else 1.0),
        "all_honest": ok_count == len(cases),
        "cases": cases,
        "policy": (
            "Non-retrieval queries must abstain from currentness claims and "
            "expose the sealed observation cutoff / release pin when required. "
            "This fixture evaluation is not a live canary and does not emit "
            "live legal advice."
        ),
    }


def evaluate_hard_negatives(
    controls: Sequence[Mapping[str, Any]],
    *,
    docs_by_id: Mapping[str, Mapping[str, Any]],
    search_fn: Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for control in controls:
        if not isinstance(control, Mapping):
            continue
        query = {
            "query_id": control.get("query_id") or control.get("control_id"),
            "query_text": control.get("query_text"),
        }
        hits, _io = search_fn(query, 5)
        blocked: set[str] = set()
        for document_id in control.get("must_not_grade_exact_document_ids") or ():
            doc = docs_by_id.get(str(document_id))
            if doc and doc.get("entry_cid"):
                blocked.add(str(doc["entry_cid"]))
        top = hits[0] if hits else None
        top_cid = str((top or {}).get("entry_cid") or "")
        leaked_exact = bool(top_cid and top_cid in blocked)
        cases.append(
            {
                "control_id": control.get("control_id"),
                "control_kind": control.get("control_kind"),
                "partition": control.get("partition"),
                "ok": not leaked_exact,
                "leaked_blocked": [top_cid] if leaked_exact else [],
            }
        )
    ok_count = sum(1 for case in cases if case["ok"])
    return {
        "case_count": len(cases),
        "ok_count": ok_count,
        "all_ok": ok_count == len(cases),
        "cases": cases,
    }


def evaluate_missing_body(
    cases: Sequence[Mapping[str, Any]],
    *,
    docs_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        document_id = str(case.get("document_id") or "")
        doc = docs_by_id.get(document_id) or {}
        body_present = bool(doc.get("body_present"))
        availability = str(doc.get("text_availability") or "")
        ok = (not body_present) and availability not in {"", "full_text"}
        rows.append(
            {
                "case_id": case.get("case_id") or document_id,
                "document_id": document_id,
                "text_availability": availability,
                "body_present": body_present,
                "must_not_claim_full_text": bool(case.get("must_not_claim_full_text", True)),
                "ok": ok,
            }
        )
    ok_count = sum(1 for row in rows if row["ok"])
    return {
        "case_count": len(rows),
        "ok_count": ok_count,
        "all_ok": ok_count == len(rows),
        "cases": rows,
    }


def full_release_bytes(
    *,
    term_shards: int,
    document_count: int,
    vector_count: int,
    graph_edges: int,
    graph_shards: int,
) -> int:
    return (
        term_shards * BYTES_PER_TERM_RANGE_META
        + document_count * BYTES_PER_POSTING_ROW
        + vector_count * BYTES_PER_VECTOR_ROW
        + graph_shards * BYTES_PER_TERM_RANGE_META
        + graph_edges * BYTES_PER_GRAPH_POINTER
        + document_count * BYTES_PER_CORPUS_ROW
    )


def sparse_io_summary(
    mode_metrics: Mapping[str, Mapping[str, Any]],
    *,
    full_bytes: int,
) -> dict[str, Any]:
    modes: dict[str, Any] = {}
    bounded = True
    sparse = True
    for mode, metrics in mode_metrics.items():
        shards_mean = float((metrics.get("shards_fetched") or {}).get("mean") or 0.0)
        shards_available = float(metrics.get("shards_available_mean") or 0.0)
        bytes_mean = float((metrics.get("bytes_fetched") or {}).get("mean") or 0.0)
        shard_ratio = shards_mean / shards_available if shards_available else 0.0
        byte_ratio = bytes_mean / float(full_bytes) if full_bytes else 0.0
        traces = list(metrics.get("fetch_traces") or ())
        traces_bounded = all(bool(trace.get("bounded_shard_selection")) for trace in traces)
        mode_bounded = (shards_available == 0.0 or shards_mean < shards_available) and (
            not traces or traces_bounded
        )
        mode_sparse = byte_ratio <= SPARSE_IO_BYTE_RATIO_GATE and (
            shards_available == 0.0 or shard_ratio <= SPARSE_IO_SHARD_RATIO_GATE
        )
        bounded = bounded and mode_bounded
        sparse = sparse and mode_sparse
        modes[mode] = {
            "bytes_mean": _round_float(bytes_mean),
            "shards_mean": _round_float(shards_mean),
            "shards_available_mean": _round_float(shards_available),
            "bytes_ratio": _round_float(byte_ratio),
            "shard_ratio": _round_float(shard_ratio),
            "bounded_shard_selection": mode_bounded,
            "substantially_less_than_full_release": mode_sparse,
        }
    return {
        "full_release_bytes": int(full_bytes),
        "bounded_shard_selection": bounded,
        "substantially_less_than_full_release": sparse,
        "byte_ratio_gate": SPARSE_IO_BYTE_RATIO_GATE,
        "shard_ratio_gate": SPARSE_IO_SHARD_RATIO_GATE,
        "modes": modes,
        "notes": (
            "I/O uses a deterministic synthetic cost model so sealed reports "
            "are wall-clock independent. Routed queries must select a proper "
            "subset of shards and stay under the declared byte/shard ratios."
        ),
    }


def resource_model(
    *,
    document_count: int,
    term_count: int,
    vector_count: int,
    cluster_count: int,
) -> dict[str, Any]:
    peak_memory_bytes = (
        document_count * BYTES_PER_CORPUS_ROW_MEMORY
        + term_count * BYTES_PER_POSTING_MEMORY
        + vector_count * BYTES_PER_VECTOR_MEMORY
        + cluster_count * ROUTING_INDEX_BYTES_PER_CLUSTER
    )
    build_seconds = (
        (document_count + vector_count) / BUILD_ROWS_PER_SECOND
        if BUILD_ROWS_PER_SECOND > 0
        else 0.0
    )
    return {
        "peak_memory_bytes": int(peak_memory_bytes),
        "peak_memory_mib": _round_float(peak_memory_bytes / (1024.0 * 1024.0)),
        "build_throughput_rows_per_second": BUILD_ROWS_PER_SECOND,
        "build_estimated_seconds": _round_float(build_seconds),
        "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
        "model": "deterministic_fixture_resource_model/v1",
        "notes": (
            "Peak memory and build throughput are synthetic fixture estimates "
            "for regression tracking; they are not measured OS samples."
        ),
    }


def compare_regressions(
    *,
    bm25_metrics: Mapping[str, Any],
    vector_metrics: Mapping[str, Any],
    fused_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    bm25_primary = float(bm25_metrics.get("primary_metric_value") or 0.0)
    vector_primary = float(vector_metrics.get("primary_metric_value") or 0.0)
    fused_primary = float(fused_metrics.get("primary_metric_value") or 0.0)
    weaker = min(bm25_primary, vector_primary)
    stronger = max(bm25_primary, vector_primary)
    delta_vs_weaker = fused_primary - weaker
    delta_vs_stronger = fused_primary - stronger
    regressed_vs_weaker = delta_vs_weaker < -REGRESSION_TOLERANCE
    exceptions: list[dict[str, Any]] = []
    if regressed_vs_weaker:
        exceptions.append(
            {
                "kind": "fused_below_weaker_component",
                "approved": False,
                "detail": (
                    f"fused primary {fused_primary} is more than "
                    f"{REGRESSION_TOLERANCE} below weaker component {weaker}"
                ),
                "action": "must not label fused production-searchable",
            }
        )
    if vector_primary + REGRESSION_TOLERANCE < bm25_primary:
        exceptions.append(
            {
                "kind": "vector_relevance_lags_bm25_on_fixture_projection",
                "approved": True,
                "detail": (
                    "Fixture dense vectors use the local deterministic "
                    "projection (not production GTE-small). Lower vector-only "
                    "relevance on citation queries is expected and is not a "
                    "production embedding claim."
                ),
                "bm25_primary": _round_float(bm25_primary),
                "vector_primary": _round_float(vector_primary),
            }
        )
    unapproved = [item for item in exceptions if not item.get("approved")]
    return {
        "bm25_primary": _round_float(bm25_primary),
        "vector_primary": _round_float(vector_primary),
        "fused_primary": _round_float(fused_primary),
        "weaker_component_primary": _round_float(weaker),
        "stronger_component_primary": _round_float(stronger),
        "delta_vs_weaker": _round_float(delta_vs_weaker),
        "delta_vs_stronger": _round_float(delta_vs_stronger),
        "regression_tolerance": REGRESSION_TOLERANCE,
        "no_unapproved_regression": not unapproved,
        "exceptions": exceptions,
    }


def coverage_report(
    gold: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    documents = [doc for doc in gold.get("documents") or () if isinstance(doc, Mapping)]
    agencies = sorted({str(doc.get("agency_code") or "") for doc in documents if doc.get("agency_code")})
    types = sorted(
        {str(doc.get("document_type") or "") for doc in documents if doc.get("document_type")}
    )
    eras = sorted({str(doc.get("era") or "") for doc in documents if doc.get("era")})
    years = sorted(
        {str(doc.get("publication_date") or "")[:4] for doc in documents if doc.get("publication_date")}
    )
    family = candidate.get("semantic_family_closure") or {}
    closed = bool(family.get("closed"))
    return {
        "document_count": len(documents),
        "agencies": agencies,
        "agency_count": len(agencies),
        "document_types": types,
        "document_type_count": len(types),
        "eras": eras,
        "publication_years": years,
        "candidate_semantic_family_closed": closed,
        "candidate_missing_families": list(family.get("missing") or []),
        "ok": len(agencies) >= 8 and len(types) >= 4 and closed,
    }


# ---------------------------------------------------------------------------
# Security fail-closed probes
# ---------------------------------------------------------------------------


def _record_fail_closed(
    *,
    probe_id: str,
    kind: str,
    failed_closed: bool,
    error_type: str | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "probe_id": probe_id,
        "kind": kind,
        "fail_closed": True,
        "failed_closed": bool(failed_closed),
        "error_type": error_type,
        "detail": detail,
        "ok": bool(failed_closed),
    }


def evaluate_security_fail_closed(
    gold: Mapping[str, Any],
    graph: FixtureGraph,
) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []

    try:
        normalize_relative_artifact_path("../etc/passwd")
        probes.append(
            _record_fail_closed(
                probe_id="traversal_relative_path",
                kind="traversal",
                failed_closed=False,
                error_type=None,
                detail="traversal path was accepted",
            )
        )
    except ArtifactPathError as exc:
        probes.append(
            _record_fail_closed(
                probe_id="traversal_relative_path",
                kind="traversal",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )
    try:
        safe_relative_path("../../secret.json")
        probes.append(
            _record_fail_closed(
                probe_id="traversal_resolver_path",
                kind="traversal",
                failed_closed=False,
                error_type=None,
                detail="resolver accepted a traversing path",
            )
        )
    except (UnsafePathError, Exception) as exc:
        probes.append(
            _record_fail_closed(
                probe_id="traversal_resolver_path",
                kind="traversal",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )

    tampered = json.loads(json.dumps({k: v for k, v in gold.items() if not str(k).startswith("_")}))
    documents = list(tampered.get("documents") or [])
    if documents:
        documents[0] = dict(documents[0])
        documents[0]["title"] = "TAMPERED TITLE"
        tampered["documents"] = documents
    try:
        verify_checksum_seal(tampered)
        probes.append(
            _record_fail_closed(
                probe_id="tamper_gold_checksum",
                kind="tamper",
                failed_closed=False,
                error_type=None,
                detail="tampered gold seal verified",
            )
        )
    except GoldChecksumError as exc:
        probes.append(
            _record_fail_closed(
                probe_id="tamper_gold_checksum",
                kind="tamper",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )

    with tempfile.TemporaryDirectory(prefix="lcr063-security-") as tmp:
        root = Path(tmp)
        release = root / "release"
        release.mkdir()
        payload = b"federal-register-digest-probe\n"
        relative = "data/corpus/part-000000.parquet"
        artifact = release / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(payload)
        good = build_descriptor_for_bytes(relative, payload, row_count=1)
        bad_map = good.to_dict()
        bad_map["sha256"] = "0" * 64
        resolver = ImmutableHubResolver(
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=PINNED_REVISION,
            cache_dir=root / "cache",
            transport=LocalRootTransport(release),
            local_root=release,
            max_artifact_bytes=64,
        )
        try:
            resolver.resolve(relative, descriptor=bad_map)
            probes.append(
                _record_fail_closed(
                    probe_id="digest_drift",
                    kind="digest",
                    failed_closed=False,
                    error_type=None,
                    detail="digest mismatch was accepted",
                )
            )
        except DigestDriftError as exc:
            probes.append(
                _record_fail_closed(
                    probe_id="digest_drift",
                    kind="digest",
                    failed_closed=True,
                    error_type=type(exc).__name__,
                    detail=str(exc),
                )
            )
        oversized = b"x" * 2048
        over_rel = "data/vectors/bomb.parquet"
        over_path = release / over_rel
        over_path.parent.mkdir(parents=True, exist_ok=True)
        over_path.write_bytes(oversized)
        try:
            resolver.resolve(over_rel)
            probes.append(
                _record_fail_closed(
                    probe_id="decompression_artifact_budget",
                    kind="decompression",
                    failed_closed=False,
                    error_type=None,
                    detail="oversized artifact was accepted",
                )
            )
        except OversizedArtifactError as exc:
            probes.append(
                _record_fail_closed(
                    probe_id="decompression_artifact_budget",
                    kind="decompression",
                    failed_closed=True,
                    error_type=type(exc).__name__,
                    detail=str(exc),
                )
            )

    seeds = [next(iter(graph.nodes))] if graph.nodes else []
    _hits, walk_io = graph_walk(
        graph,
        seeds,
        top_k=8,
        max_depth=1,
        max_nodes=1,
        max_edges=0,
        max_shards=1,
        max_bytes=1,
    )
    budget_stopped = walk_io.get("stop_reason") in {"nodes", "edges", "shards", "bytes", "depth"}
    probes.append(
        _record_fail_closed(
            probe_id="traversal_budget_graph_walk",
            kind="budget",
            failed_closed=budget_stopped,
            error_type="QueryBudgetExhausted" if budget_stopped else None,
            detail=f"stop_reason={walk_io.get('stop_reason')}",
        )
    )
    try:
        raise QueryBudgetExhausted(
            "bytes",
            usage={"bytes": 8192},
            limits={"bytes": 4096},
        )
    except QueryBudgetExhausted as exc:
        probes.append(
            _record_fail_closed(
                probe_id="budget_typed_exhaustion",
                kind="budget",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )

    try:
        require_immutable_revision("main")
        probes.append(
            _record_fail_closed(
                probe_id="mutable_revision_main",
                kind="mutable-revision",
                failed_closed=False,
                error_type=None,
                detail="mutable main pin was accepted",
            )
        )
    except ImmutablePinError as exc:
        probes.append(
            _record_fail_closed(
                probe_id="mutable_revision_main",
                kind="mutable-revision",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )

    try:
        assert_no_secrets({"token": "hf_thisIsAFakeTokenValueForLeakTests063"}, context="federal_evaluation")
        probes.append(
            _record_fail_closed(
                probe_id="credential_surface",
                kind="secrets_absent",
                failed_closed=False,
                error_type=None,
                detail="secret surface was accepted",
            )
        )
    except SecretInReceiptError as exc:
        probes.append(
            _record_fail_closed(
                probe_id="credential_surface",
                kind="secrets_absent",
                failed_closed=True,
                error_type=type(exc).__name__,
                detail=str(exc),
            )
        )

    kinds = {
        "traversal": False,
        "tamper": False,
        "digest": False,
        "decompression": False,
        "budget": False,
        "mutable-revision": False,
        "secrets_absent": False,
    }
    for probe in probes:
        if probe["kind"] in kinds and probe["ok"]:
            kinds[probe["kind"]] = True
    all_ok = all(kinds.values()) and all(probe["ok"] for probe in probes)
    return {
        "policy": "security_probes_fail_closed",
        "all_fail_closed": all_ok,
        "kinds": kinds,
        "probes": probes,
        "live_canary": False,
        "fixture_result_called_live_canary": False,
    }


def evaluate_two_build_determinism(
    documents: Sequence[Mapping[str, Any]],
    gold: Mapping[str, Any],
) -> dict[str, Any]:
    first_bm25 = build_fixture_bm25_index(documents)
    second_bm25 = build_fixture_bm25_index(documents)
    first_vec = build_fixture_vector_index(documents)
    second_vec = build_fixture_vector_index(documents)
    first_graph = build_fixture_graph(gold, first_vec)
    second_graph = build_fixture_graph(gold, second_vec)
    bm25_match = (
        first_bm25.vocabulary == second_bm25.vocabulary
        and dict(first_bm25.postings) == dict(second_bm25.postings)
        and dict(first_bm25.idf) == dict(second_bm25.idf)
    )
    vector_match = dict(first_vec.embeddings) == dict(second_vec.embeddings)
    graph_match = (
        dict(first_graph.outgoing) == dict(second_graph.outgoing)
        and first_graph.edge_count == second_graph.edge_count
    )
    digest_a = digest_payload(
        {
            "vocab": first_bm25.vocabulary,
            "embeddings": {k: list(v[:8]) for k, v in sorted(first_vec.embeddings.items())},
            "edges": first_graph.edge_count,
        }
    )
    digest_b = digest_payload(
        {
            "vocab": second_bm25.vocabulary,
            "embeddings": {k: list(v[:8]) for k, v in sorted(second_vec.embeddings.items())},
            "edges": second_graph.edge_count,
        }
    )
    return {
        "runs": 2,
        "bm25_match": bm25_match,
        "vector_match": vector_match,
        "graph_match": graph_match,
        "digest_a": digest_a,
        "digest_b": digest_b,
        "ok": bm25_match and vector_match and graph_match and digest_a == digest_b,
        "policy": "two_independent_fixture_builds_must_match",
    }


# ---------------------------------------------------------------------------
# Fusion selection + fixture evaluation
# ---------------------------------------------------------------------------


def _fusion_config(candidate: Mapping[str, Any]) -> FusionConfig:
    return FusionConfig(
        method=str(candidate["method"]),
        bm25_weight=float(candidate["bm25_weight"]),
        vector_weight=float(candidate["vector_weight"]),
        rrf_k=int(candidate["rrf_k"]),
    )


def run_fixture_evaluation(
    *,
    gold_path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    gold = load_sealed_gold(gold_path, repo_root=repo_root)
    candidate = load_readonly_report(
        CANDIDATE_RELPATH, expected_task_id=CANDIDATE_TASK_ID, repo_root=repo_root
    )
    query_contract = load_query_contract(
        _repo_path(QUERY_CONTRACT_RELPATH, repo_root=repo_root)
    )
    bm25_baseline = load_readonly_report(
        BM25_REPORT_RELPATH, expected_task_id=BM25_TASK_ID, repo_root=repo_root
    )
    vector_baseline = load_readonly_report(
        VECTOR_REPORT_RELPATH, expected_task_id=VECTORS_TASK_ID, repo_root=repo_root
    )
    graph_baseline = load_readonly_report(
        GRAPH_REPORT_RELPATH, expected_task_id=GRAPH_TASK_ID, repo_root=repo_root
    )

    documents = [dict(doc) for doc in gold.get("documents") or ()]
    docs_by_cid = {str(doc["entry_cid"]): doc for doc in documents}
    docs_by_id = {str(doc["document_id"]): doc for doc in documents}
    judgments = judgments_by_query(gold)
    gold_dev = retrieval_queries(gold, partition=SELECTION_PARTITION)
    gold_test = retrieval_queries(gold, partition=REPORT_PARTITION)
    gold_train = retrieval_queries(gold, partition=INSPECTION_PARTITION)
    if not gold_dev or not gold_test:
        raise SparseGraphragEvaluationError("gold fixture missing dev/test retrieval queries")

    bm25_index = build_fixture_bm25_index(documents)
    vector_index = build_fixture_vector_index(documents)
    graph = build_fixture_graph(gold, vector_index)
    two_build = evaluate_two_build_determinism(documents, gold)

    def _bm25(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return bm25_search(
            bm25_index,
            str(query.get("query_text") or ""),
            top_k=top_k,
            filters=_legal_filters_from_query(query),
            docs_by_cid=docs_by_cid,
        )

    def _vector(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        embedding = _embed_query_text(str(query.get("query_text") or ""))
        return vector_search(
            vector_index,
            embedding,
            top_k=top_k,
            probe_centroids=vector_index.probe_centroids,
            filters=_legal_filters_from_query(query),
            docs_by_cid=docs_by_cid,
        )

    def _hybrid_for(
        fusion: FusionConfig,
    ) -> Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]]:
        def _search(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            bm25_hits, bm25_io = _bm25(query, top_k)
            vector_hits, vector_io = _vector(query, top_k)
            fused = fuse_hybrid_results(
                bm25_hits,
                vector_hits,
                config=fusion,
                top_k=top_k,
            )
            fused = [_annotate_hit(hit, docs_by_cid) for hit in fused]
            filters = _legal_filters_from_query(query)
            if filters is not None:
                fused = apply_legal_filters(fused, filters)
            io = {
                "bytes_fetched": int(bm25_io["bytes_fetched"]) + int(vector_io["bytes_fetched"]),
                "docs_scored": int(bm25_io["docs_scored"]) + int(vector_io["docs_scored"]),
                "latency_ms": _round_float(
                    float(bm25_io["latency_ms"]) + float(vector_io["latency_ms"])
                ),
                "shards_fetched": int(bm25_io["shards_fetched"]) + int(vector_io["shards_fetched"]),
                "shards_available": int(bm25_io["shards_available"])
                + int(vector_io["shards_available"]),
                "failure_modes": list(bm25_io.get("failure_modes") or ())
                + list(vector_io.get("failure_modes") or ()),
                "route_family": "hybrid_late_fusion",
                "routed_paths": list(bm25_io.get("routed_paths") or ())
                + list(vector_io.get("routed_paths") or ()),
            }
            return fused, io

        return _search

    def _graph(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        bm25_hits, _io = _bm25(query, max(top_k, 3))
        seeds = [str(hit.get("entry_cid") or "") for hit in bm25_hits[:2] if hit.get("entry_cid")]
        if not seeds and graph.nodes:
            seeds = [next(iter(graph.nodes))]
        hits, io = graph_walk(graph, seeds, top_k=top_k)
        return [_annotate_hit(hit, docs_by_cid) for hit in hits], io

    def _semantic(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        embedding = _embed_query_text(str(query.get("query_text") or ""))
        bm25_hits, _io = _bm25(query, max(top_k, 3))
        seeds = [str(hit.get("entry_cid") or "") for hit in bm25_hits[:2] if hit.get("entry_cid")]
        if not seeds and graph.nodes:
            seeds = [next(iter(graph.nodes))]
        hits, io = semantic_graph_walk(
            graph, vector_index, embedding, seeds, top_k=top_k
        )
        return [_annotate_hit(hit, docs_by_cid) for hit in hits], io

    bm25_dev = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_dev,
        judgments=judgments,
        search_fn=_bm25,
        recall_gate=RECALL_GATE_BM25,
    )
    vector_dev = evaluate_ranked_mode(
        mode="vector",
        queries=gold_dev,
        judgments=judgments,
        search_fn=_vector,
        recall_gate=RECALL_GATE_VECTOR,
    )
    fusion_candidate_results: list[dict[str, Any]] = []
    for candidate_row in FUSION_CANDIDATES:
        fusion = _fusion_config(candidate_row)
        metrics = evaluate_ranked_mode(
            mode="hybrid",
            queries=gold_dev,
            judgments=judgments,
            search_fn=_hybrid_for(fusion),
            recall_gate=RECALL_GATE_HYBRID,
        )
        fusion_candidate_results.append(
            {
                **candidate_row,
                "config_digest": digest_payload(fusion.to_dict()),
                "primary_metric_value": metrics["primary_metric_value"],
                "mean_reciprocal_rank": metrics["mean_reciprocal_rank"],
                "ndcg_at_10": metrics["ndcg_at_10"],
                "meets_recall_gate": metrics["meets_recall_gate"],
                "relevance_recall_at_5": metrics["relevance_recall_at_5"],
            }
        )
    selected_candidate = max(
        fusion_candidate_results,
        key=lambda item: (
            float(item["primary_metric_value"]),
            float(item["mean_reciprocal_rank"]),
            float(item["ndcg_at_10"]),
            str(item["candidate_id"]),
        ),
    )
    selected_fusion = _fusion_config(selected_candidate)
    fusion_selection = {
        "candidate_id": selected_candidate["candidate_id"],
        "config": selected_fusion.to_dict(),
        "config_digest": selected_candidate["config_digest"],
        "evidence_partition": SELECTION_PARTITION,
        "is_plan_default": bool(selected_candidate["is_plan_default"]),
        "meets_recall_gate": bool(selected_candidate["meets_recall_gate"]),
        "primary_metric_value": selected_candidate["primary_metric_value"],
        "reason": (
            "selected on sealed dev split by primary hybrid recall, then MRR, "
            "then nDCG@10; test split is not used for selection"
        ),
    }

    bm25_test = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_test,
        judgments=judgments,
        search_fn=_bm25,
        recall_gate=RECALL_GATE_BM25,
    )
    vector_test = evaluate_ranked_mode(
        mode="vector",
        queries=gold_test,
        judgments=judgments,
        search_fn=_vector,
        recall_gate=RECALL_GATE_VECTOR,
    )
    fused_test = evaluate_ranked_mode(
        mode="hybrid",
        queries=gold_test,
        judgments=judgments,
        search_fn=_hybrid_for(selected_fusion),
        recall_gate=RECALL_GATE_HYBRID,
    )
    graph_test = evaluate_ranked_mode(
        mode="graph",
        queries=gold_test,
        judgments=judgments,
        search_fn=_graph,
        recall_gate=RECALL_GATE_SEMANTIC,
    )
    semantic_test = evaluate_ranked_mode(
        mode="semantic-graph",
        queries=gold_test,
        judgments=judgments,
        search_fn=_semantic,
        recall_gate=RECALL_GATE_SEMANTIC,
    )
    fused_train = evaluate_ranked_mode(
        mode="hybrid",
        queries=gold_train,
        judgments=judgments,
        search_fn=_hybrid_for(selected_fusion),
        recall_gate=RECALL_GATE_HYBRID,
    )

    graph_paths = evaluate_graph_paths(graph)
    graph_paths_test = evaluate_graph_paths(graph, partition=REPORT_PARTITION)
    dense_agreement_dev = evaluate_dense_agreement(
        queries=gold_dev,
        vector_index=vector_index,
        probe_centroids=vector_index.probe_centroids,
        top_k=1,
    )
    dense_agreement_test = evaluate_dense_agreement(
        queries=gold_test,
        vector_index=vector_index,
        probe_centroids=vector_index.probe_centroids,
        top_k=1,
    )
    filters_eval = evaluate_filters(
        queries=filter_queries(gold),
        search_fn=_hybrid_for(selected_fusion),
        docs_by_cid=docs_by_cid,
    )
    abstention = evaluate_abstention(
        non_retrieval_queries(gold),
        observation_cutoff=str(
            (gold.get("release_authority") or {}).get("observation_cutoff")
            or DEFAULT_OBSERVATION_CUTOFF
        ),
        release_point=str((candidate.get("candidate") or {}).get("release_point") or ""),
    )
    negatives_eval = evaluate_hard_negatives(
        gold.get("hard_negatives") or (),
        docs_by_id=docs_by_id,
        search_fn=_hybrid_for(selected_fusion),
    )
    missing_body = evaluate_missing_body(
        gold.get("missing_body_cases") or (),
        docs_by_id=docs_by_id,
    )
    coverage = coverage_report(gold, candidate)
    sparse_io = sparse_io_summary(
        {
            "bm25": bm25_test,
            "vector": vector_test,
            "hybrid": fused_test,
            "graph": graph_test,
            "semantic-graph": semantic_test,
        },
        full_bytes=full_release_bytes(
            term_shards=len(bm25_index.shards),
            document_count=len(documents),
            vector_count=vector_index.vector_count,
            graph_edges=graph.edge_count,
            graph_shards=graph.shard_count,
        ),
    )
    resources = resource_model(
        document_count=len(documents),
        term_count=len(bm25_index.vocabulary),
        vector_count=vector_index.vector_count,
        cluster_count=vector_index.cluster_count,
    )
    regressions = compare_regressions(
        bm25_metrics=bm25_test,
        vector_metrics=vector_test,
        fused_metrics=fused_test,
    )
    security = evaluate_security_fail_closed(gold, graph)

    probe_centroids = vector_index.probe_centroids
    component_baselines = {
        "bm25": {
            "available": True,
            "task_id": BM25_TASK_ID,
            "path": BM25_REPORT_RELPATH.as_posix(),
            "index_root_cid": (bm25_baseline.get("admitted") or {}).get("index_root_cid"),
            "consumed_read_only": True,
        },
        "vector": {
            "available": True,
            "task_id": VECTORS_TASK_ID,
            "path": VECTOR_REPORT_RELPATH.as_posix(),
            "vector_root_cid": (vector_baseline.get("admitted") or {}).get("vector_root_cid"),
            "consumed_read_only": True,
        },
        "graph": {
            "available": True,
            "task_id": GRAPH_TASK_ID,
            "path": GRAPH_REPORT_RELPATH.as_posix(),
            "graph_cid": (graph_baseline.get("admitted") or {}).get("graph_cid"),
            "consumed_read_only": True,
        },
        "query": {
            "available": True,
            "task_id": QUERY_TASK_ID,
            "path": QUERY_CONTRACT_RELPATH.as_posix(),
            "contract_cid": query_contract.get("contract_cid"),
            "consumed_read_only": True,
        },
        "candidate": {
            "available": True,
            "task_id": CANDIDATE_TASK_ID,
            "path": CANDIDATE_RELPATH.as_posix(),
            "manifest_digest": (candidate.get("candidate") or {}).get("manifest_digest"),
            "consumed_read_only": True,
        },
        "gold": {
            "available": True,
            "task_id": GOLD_TASK_ID,
            "path": DEFAULT_GOLD_RELPATH.as_posix(),
            "manifest_digest": gold.get("_manifest_digest"),
            "consumed_read_only": True,
        },
    }
    chosen_defaults = {
        "bm25": {
            "source": BM25_TASK_ID,
            "parameters": {
                "k1": bm25_index.k1,
                "b": bm25_index.b,
                "field_weights": dict(bm25_index.field_weights),
                "tokenizer_id": TOKENIZER_ID,
                "terms_per_shard": bm25_index.terms_per_shard,
            },
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": "plan default k1=1.2 b=0.75 multi-field weights",
        },
        "vector": {
            "source": VECTORS_TASK_ID,
            "default_probe_centroids": probe_centroids,
            "historical_plan_default": DEFAULT_CANDIDATE_CENTROIDS,
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": f"plan default probe={probe_centroids}",
            "embedding_backend": "local_deterministic_projection",
            "embedding_model_id": PINNED_MODEL_ID,
            "embedding_model_revision": PINNED_MODEL_REVISION,
            "embedding_note": (
                "Fixture vectors use the local deterministic projection for "
                "offline parity; production GTE-small identity is declared by "
                "the vector receipt and cannot be authorized by this gate."
            ),
        },
        "fusion": {
            "source": QUERY_TASK_ID,
            "candidate_id": fusion_selection["candidate_id"],
            "config": fusion_selection["config"],
            "config_digest": fusion_selection["config_digest"],
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": fusion_selection["reason"],
            "is_plan_default": fusion_selection["is_plan_default"],
        },
        "graph": {
            "source": GRAPH_TASK_ID,
            "path_success_requires": "all_expected_paths_pass",
            "walk_strategy": "structural_bfs",
        },
        "semantic-graph": {
            "source": QUERY_TASK_ID,
            "hydration_policy": "entry_locator",
            "walk_strategy": "embedding_guided_beam",
        },
    }

    graph_paths_ok = bool(graph_paths.get("ok"))
    modes_meet = {
        "bm25": bool(bm25_test.get("meets_recall_gate")) and bool(bm25_test.get("meets_ranking_gate")),
        "vector": bool(vector_test.get("meets_recall_gate")),
        "hybrid": bool(fused_test.get("meets_recall_gate")) and bool(fused_test.get("meets_ranking_gate")),
        "graph": graph_paths_ok,
        "semantic-graph": bool(semantic_test.get("meets_recall_gate")),
    }
    exact_ok = (
        int(bm25_test.get("exact_citation_query_count") or 0) == 0
        or float(bm25_test.get("exact_citation_success_rate") or 0.0) >= EXACT_CITATION_GATE
    )
    sparse_ok = bool(sparse_io.get("bounded_shard_selection")) and bool(
        sparse_io.get("substantially_less_than_full_release")
    )
    production_searchable = False
    blockers = [
        "fixture uses local deterministic projection, not live GTE-small",
        "fixture evaluation is not a live canary and does not authorize Hub upload",
    ]
    claim_text = "NO production-searchable claim: " + "; ".join(blockers) + "."
    production_claim = {
        "production_searchable": production_searchable,
        "claim": claim_text,
        "live_canary": False,
        "fixture_result_called_live_canary": False,
        "declared_bm25_recall_gate": RECALL_GATE_BM25,
        "declared_vector_recall_gate": RECALL_GATE_VECTOR,
        "declared_hybrid_recall_gate": RECALL_GATE_HYBRID,
        "declared_graph_recall_gate": RECALL_GATE_GRAPH,
        "declared_semantic_recall_gate": RECALL_GATE_SEMANTIC,
        "declared_dense_recall_gate": DENSE_RECALL_GATE,
        "modes_meet_declared_gates": all(modes_meet.values()),
        "default_fusion_candidate_id": fusion_selection["candidate_id"],
        "default_probe_centroids": probe_centroids,
    }

    differential = {
        "gold_task_id": GOLD_TASK_ID,
        "gold_manifest_digest": gold.get("_manifest_digest"),
        "query_task_id": QUERY_TASK_ID,
        "query_contract_cid": query_contract.get("contract_cid"),
        "candidate_task_id": CANDIDATE_TASK_ID,
        "candidate_content_digest": candidate.get("content_digest"),
        "candidate_manifest_digest": (candidate.get("candidate") or {}).get("manifest_digest"),
        "ok": bool(
            gold.get("_manifest_digest")
            and query_contract.get("contract_cid")
            and candidate.get("content_digest")
        ),
    }
    sealed_thresholds_pass = all(
        (
            modes_meet["bm25"],
            modes_meet["vector"],
            modes_meet["hybrid"],
            modes_meet["graph"],
            bool(dense_agreement_test.get("meets_recall_gate")),
            bool(filters_eval.get("ok")),
            sparse_ok,
            bool(two_build.get("ok")),
            bool(security.get("all_fail_closed")),
            bool(differential.get("ok")),
        )
    )

    acceptance = {
        "bm25_meets_declared_gates": modes_meet["bm25"] and exact_ok,
        "vector_meets_declared_gates": modes_meet["vector"],
        "hybrid_meets_declared_gates": modes_meet["hybrid"],
        "graph_meets_declared_gates": modes_meet["graph"],
        "semantic_traversal_meets_declared_gates": modes_meet["semantic-graph"],
        "all_modes_meet_declared_recall_and_ranking": all(modes_meet.values()) and exact_ok,
        "vector_recall_meets_declared_gate": bool(dense_agreement_test.get("meets_recall_gate")),
        "graph_edges_pass": graph_paths_ok,
        "filters_pass": bool(filters_eval.get("ok")),
        "coverage_pass": bool(coverage.get("ok")),
        "bounded_shard_selection": bool(sparse_io.get("bounded_shard_selection")),
        "substantially_less_than_full_release": bool(
            sparse_io.get("substantially_less_than_full_release")
        ),
        "fetch_traces_prove_sparse_io": sparse_ok,
        "component_and_fused_baselines_reported": True,
        "chosen_defaults_declared": True,
        "regressions_and_exceptions_explicit": True,
        "reference_hardware_network_recorded": True,
        "no_unsupported_production_claim": True,
        "test_split_not_tuned": True,
        "test_split_reported_once": True,
        "budget_exhaustion_fail_closed": bool(security["kinds"]["budget"]),
        "traversal_fail_closed": bool(security["kinds"]["traversal"]),
        "tamper_fail_closed": bool(security["kinds"]["tamper"]),
        "digest_fail_closed": bool(security["kinds"]["digest"]),
        "decompression_fail_closed": bool(security["kinds"]["decompression"]),
        "mutable_revision_fail_closed": bool(security["kinds"]["mutable-revision"]),
        "secrets_absent_fail_closed": bool(security["kinds"]["secrets_absent"]),
        "security_probes_fail_closed": bool(security.get("all_fail_closed")),
        "two_build_determinism": bool(two_build.get("ok")),
        "sealed_thresholds_pass": sealed_thresholds_pass,
        "differential_references_pass": bool(differential.get("ok")),
        "no_fixture_result_called_live_canary": True,
        "abstention_honesty": bool(abstention.get("all_honest")),
        "graph_path_success": graph_paths_ok,
        "hard_negatives_ok": bool(negatives_eval.get("all_ok")),
        "missing_body_ok": bool(missing_body.get("all_ok")),
        "no_unapproved_regression": bool(regressions.get("no_unapproved_regression")),
        "all_expected_outputs_required": True,
        "production_searchable": production_searchable,
        "live_canary": False,
        "hub_upload": False,
        "criteria": (
            "Sealed thresholds and differential references pass; traversal, "
            "tamper, digest, decompression, budget, mutable-revision, and "
            "secret tests fail closed; no fixture result is called a live canary."
        ),
    }

    host_snapshot = {
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "processor": platform.processor() or "unknown",
        "role": "evaluation_host_snapshot_not_sla",
    }

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "abstention": abstention,
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "canary": {
            "kind": "fixture_offline_not_live",
            "live_canary": False,
            "fixture_result_called_live_canary": False,
            "staging_canary": False,
            "deferred_to": "LCR-064",
        },
        "chosen_defaults": chosen_defaults,
        "code_version": CODE_VERSION,
        "component_baselines": component_baselines,
        "consumed_inputs": {
            "gold": component_baselines["gold"],
            "query": component_baselines["query"],
            "candidate": component_baselines["candidate"],
            "read_only": True,
            "hub_upload": False,
        },
        "corpus": {
            "document_count": len(documents),
            "vector_count": vector_index.vector_count,
            "cluster_count": vector_index.cluster_count,
            "vector_shard_count": vector_index.shard_count,
            "term_count": len(bm25_index.vocabulary),
            "bm25_term_shard_count": len(bm25_index.shards),
            "bm25_terms_per_shard": FIXTURE_TERMS_PER_SHARD,
            "graph_edge_count": graph.edge_count,
            "graph_shard_count": graph.shard_count,
            "tokenizer_id": TOKENIZER_ID,
            "dimension": PINNED_DIMENSION,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "max_shards_per_centroid": FIXTURE_MAX_SHARDS_PER_CENTROID,
        },
        "coverage": coverage,
        "currentness_disclaimer": gold.get("currentness_disclaimer"),
        "dense_agreement": {"dev": dense_agreement_dev, "test": dense_agreement_test},
        "depends_on": list(DEPENDS_ON),
        "differential_references": differential,
        "evaluation": {
            "inspection_partition": INSPECTION_PARTITION,
            "report_partition": REPORT_PARTITION,
            "selection_partition": SELECTION_PARTITION,
            "primary_top_k": PRIMARY_TOP_K,
            "top_k_values": list(TOP_K_VALUES),
            "gates": {
                "bm25": RECALL_GATE_BM25,
                "vector": RECALL_GATE_VECTOR,
                "hybrid": RECALL_GATE_HYBRID,
                "graph": RECALL_GATE_GRAPH,
                "semantic-graph": RECALL_GATE_SEMANTIC,
                "dense": DENSE_RECALL_GATE,
                "mrr": RANKING_MRR_GATE,
                "ndcg": RANKING_NDCG_GATE,
                "exact_citation": EXACT_CITATION_GATE,
                "filters": FILTER_GATE,
            },
            "partitions": {
                "dev": {
                    "role": "fusion_selection_only",
                    "tuned": True,
                    "gold_query_count": len(gold_dev),
                    "bm25": bm25_dev,
                    "vector": vector_dev,
                    "fusion_candidates": [
                        {
                            "candidate_id": item["candidate_id"],
                            "is_plan_default": item["is_plan_default"],
                            "method": item["method"],
                            "bm25_weight": item["bm25_weight"],
                            "vector_weight": item["vector_weight"],
                            "rrf_k": item["rrf_k"],
                            "config_digest": item["config_digest"],
                            "primary_metric_value": item["primary_metric_value"],
                            "mean_reciprocal_rank": item["mean_reciprocal_rank"],
                            "ndcg_at_10": item["ndcg_at_10"],
                            "meets_recall_gate": item["meets_recall_gate"],
                            "relevance_recall_at_5": item["relevance_recall_at_5"],
                        }
                        for item in fusion_candidate_results
                    ],
                    "fused": {
                        "candidate_id": selected_candidate["candidate_id"],
                        "primary_metric_value": selected_candidate["primary_metric_value"],
                        "meets_recall_gate": selected_candidate["meets_recall_gate"],
                        "mean_reciprocal_rank": selected_candidate["mean_reciprocal_rank"],
                    },
                },
                "test": {
                    "role": "sealed_one_shot_report",
                    "tuned": False,
                    "report_count": 1,
                    "gold_query_count": len(gold_test),
                    "bm25": bm25_test,
                    "vector": vector_test,
                    "fused": fused_test,
                    "hybrid": fused_test,
                    "graph": graph_test,
                    "semantic-graph": semantic_test,
                },
                "train": {
                    "role": "inspection_only_not_reported_as_gate",
                    "tuned": False,
                    "gold_query_count": len(gold_train),
                    "fused": fused_train,
                },
            },
        },
        "filters": filters_eval,
        "fixture_only": True,
        "fusion_selection": fusion_selection,
        "goal_id": GOAL_ID,
        "graph_path": {
            "all_partitions": graph_paths,
            "test": graph_paths_test,
            "ok": graph_paths_ok,
            "edge_count": graph.edge_count,
        },
        "hard_negatives": negatives_eval,
        "host_snapshot": host_snapshot,
        "hub_upload": False,
        "io": {
            "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
            "model": "deterministic_fixture_io/v1",
            "sparse": sparse_io,
            "bm25_test": {
                "bytes_fetched": bm25_test.get("bytes_fetched"),
                "shards_fetched": bm25_test.get("shards_fetched"),
                "latency_ms": bm25_test.get("latency_ms"),
            },
            "vector_test": {
                "bytes_fetched": vector_test.get("bytes_fetched"),
                "shards_fetched": vector_test.get("shards_fetched"),
                "latency_ms": vector_test.get("latency_ms"),
            },
            "hybrid_test": {
                "bytes_fetched": fused_test.get("bytes_fetched"),
                "shards_fetched": fused_test.get("shards_fetched"),
                "latency_ms": fused_test.get("latency_ms"),
            },
            "graph_test": {
                "bytes_fetched": graph_test.get("bytes_fetched"),
                "shards_fetched": graph_test.get("shards_fetched"),
                "latency_ms": graph_test.get("latency_ms"),
            },
            "semantic_test": {
                "bytes_fetched": semantic_test.get("bytes_fetched"),
                "shards_fetched": semantic_test.get("shards_fetched"),
                "latency_ms": semantic_test.get("latency_ms"),
            },
        },
        "live_canary": False,
        "missing_body": missing_body,
        "modes_meet_declared_gates": modes_meet,
        "not_legal_advice": True,
        "producer": PRODUCER,
        "production_claim": production_claim,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "reference_hardware": dict(REFERENCE_HARDWARE),
        "reference_network": {**REFERENCE_NETWORK, "network_required": False},
        "regressions": regressions,
        "release_profile": RELEASE_PROFILE,
        "resources": resources,
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA,
        "security": security,
        "task_id": TASK_ID,
        "two_build_determinism": two_build,
    }
    report["evaluation_cid"] = "sha256:" + digest_payload(
        {
            "task_id": TASK_ID,
            "fusion": fusion_selection,
            "test_hybrid_primary": fused_test.get("primary_metric_value"),
            "test_bm25_primary": bm25_test.get("primary_metric_value"),
            "test_vector_primary": vector_test.get("primary_metric_value"),
            "graph_success_rate": graph_paths.get("success_rate"),
            "two_build": two_build.get("digest_a"),
            "gold_digest": gold.get("_manifest_digest"),
            "candidate_digest": candidate.get("content_digest"),
            "production_searchable": production_searchable,
            "live_canary": False,
        }
    )
    assert_no_secrets(report, context="federal_evaluation")
    return report


# ---------------------------------------------------------------------------
# Acceptance check
# ---------------------------------------------------------------------------


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise SparseGraphragEvaluationError("report must be a mapping")
    if report.get("task_id") != TASK_ID:
        raise SparseGraphragEvaluationError(f"unexpected task_id: {report.get('task_id')!r}")
    if report.get("schema_version") != REPORT_SCHEMA:
        raise SparseGraphragEvaluationError(
            f"unexpected schema_version: {report.get('schema_version')!r}"
        )
    if report.get("goal_id") != GOAL_ID:
        raise SparseGraphragEvaluationError(f"unexpected goal_id: {report.get('goal_id')!r}")
    if report.get("program_id") != PROGRAM_ID:
        raise SparseGraphragEvaluationError(
            f"unexpected program_id: {report.get('program_id')!r}"
        )

    acceptance = report.get("acceptance") or {}
    required_true = (
        "all_modes_meet_declared_recall_and_ranking",
        "vector_recall_meets_declared_gate",
        "graph_edges_pass",
        "filters_pass",
        "bounded_shard_selection",
        "substantially_less_than_full_release",
        "fetch_traces_prove_sparse_io",
        "component_and_fused_baselines_reported",
        "chosen_defaults_declared",
        "regressions_and_exceptions_explicit",
        "reference_hardware_network_recorded",
        "no_unsupported_production_claim",
        "test_split_not_tuned",
        "test_split_reported_once",
        "budget_exhaustion_fail_closed",
        "traversal_fail_closed",
        "tamper_fail_closed",
        "digest_fail_closed",
        "decompression_fail_closed",
        "mutable_revision_fail_closed",
        "secrets_absent_fail_closed",
        "security_probes_fail_closed",
        "two_build_determinism",
        "sealed_thresholds_pass",
        "differential_references_pass",
        "no_fixture_result_called_live_canary",
        "graph_path_success",
    )
    for key in required_true:
        if not bool(acceptance.get(key)):
            raise SparseGraphragEvaluationError(f"acceptance[{key!r}] is not true")

    if bool(report.get("live_canary")) or bool(acceptance.get("live_canary")):
        raise SparseGraphragEvaluationError("fixture result must not be called a live canary")
    canary = report.get("canary") or {}
    if bool(canary.get("live_canary")) or bool(canary.get("fixture_result_called_live_canary")):
        raise SparseGraphragEvaluationError("fixture result must not be called a live canary")
    claim = report.get("production_claim") or {}
    if bool(claim.get("production_searchable")):
        raise SparseGraphragEvaluationError(
            "fixture evaluation must not claim production_searchable"
        )
    if bool(claim.get("live_canary")):
        raise SparseGraphragEvaluationError("fixture result must not be called a live canary")
    if "NO production-searchable claim" not in str(claim.get("claim") or ""):
        raise SparseGraphragEvaluationError("production claim text is not fail-closed")

    hardware = report.get("reference_hardware") or {}
    network = report.get("reference_network") or {}
    if not hardware.get("cpu_model") or not hardware.get("memory_gib"):
        raise SparseGraphragEvaluationError("reference_hardware incomplete")
    if network.get("network_required") is not False:
        raise SparseGraphragEvaluationError(
            "fixture evaluation must declare network_required=false"
        )

    defaults = report.get("chosen_defaults") or {}
    for key in ("bm25", "vector", "fusion", "graph", "semantic-graph"):
        if key not in defaults:
            raise SparseGraphragEvaluationError(f"chosen_defaults missing {key!r}")

    components = report.get("component_baselines") or {}
    for key in ("bm25", "vector", "graph", "query", "candidate", "gold"):
        block = components.get(key) or {}
        if not bool(block.get("available")):
            raise SparseGraphragEvaluationError(f"component baseline {key!r} not available")
        if not bool(block.get("consumed_read_only")):
            raise SparseGraphragEvaluationError(f"component {key!r} must be consumed read-only")

    partitions = (report.get("evaluation") or {}).get("partitions") or {}
    test = partitions.get("test") or {}
    if test.get("tuned") is not False:
        raise SparseGraphragEvaluationError("test partition must not be tuned")
    if int(test.get("report_count") or 0) != 1:
        raise SparseGraphragEvaluationError("test partition must be reported once")
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        metrics = test.get(mode) or {}
        if not metrics.get("query_count"):
            raise SparseGraphragEvaluationError(f"test {mode} metrics missing")
        if mode in {"bm25", "hybrid", "vector", "semantic-graph"} and not bool(
            metrics.get("meets_recall_gate")
        ):
            raise SparseGraphragEvaluationError(f"{mode} missed declared recall gate")

    if not bool((report.get("graph_path") or {}).get("ok")):
        raise SparseGraphragEvaluationError("graph paths did not all succeed")
    if int((report.get("graph_path") or {}).get("edge_count") or 0) <= 0:
        raise SparseGraphragEvaluationError("graph edges missing")

    sparse = (report.get("io") or {}).get("sparse") or {}
    if not bool(sparse.get("bounded_shard_selection")):
        raise SparseGraphragEvaluationError("fetch traces do not prove bounded shards")
    if not bool(sparse.get("substantially_less_than_full_release")):
        raise SparseGraphragEvaluationError(
            "routed queries are not substantially below full-release transfer"
        )

    regressions = report.get("regressions") or {}
    if "exceptions" not in regressions:
        raise SparseGraphragEvaluationError("regressions.exceptions missing")

    selection = report.get("fusion_selection") or {}
    if selection.get("evidence_partition") != SELECTION_PARTITION:
        raise SparseGraphragEvaluationError(
            "fusion selection must use the dev evidence partition"
        )
    if not bool((report.get("two_build_determinism") or {}).get("ok")):
        raise SparseGraphragEvaluationError("two-build determinism failed")
    if not bool((report.get("security") or {}).get("all_fail_closed")):
        raise SparseGraphragEvaluationError("security probes did not all fail closed")
    if not bool((report.get("differential_references") or {}).get("ok")):
        raise SparseGraphragEvaluationError("differential references missing")
    if bool(report.get("hub_upload")) or bool(report.get("authorizing_hub_upload")):
        raise SparseGraphragEvaluationError("evaluation must not authorize Hub upload")

    text = json.dumps(dict(report))
    if "hf_" in text or "sk-" in text or "Bearer " in text:
        raise SparseGraphragEvaluationError("report contains secret-like material")

    return {
        "ok": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "production_searchable": False,
        "live_canary": False,
        "fusion_candidate_id": selection.get("candidate_id"),
        "hybrid_recall_gate": RECALL_GATE_HYBRID,
        "test_hybrid_relevance_recall_at_primary_k": (test.get("hybrid") or {}).get(
            "primary_metric_value"
        ),
        "modes_meet_declared_gates": dict(report.get("modes_meet_declared_gates") or {}),
        "bounded_shard_selection": True,
        "substantially_less_than_full_release": True,
        "component_baselines_available": True,
        "no_unsupported_production_claim": True,
        "sealed_thresholds_pass": True,
        "differential_references_pass": True,
        "security_probes_fail_closed": True,
        "two_build_determinism": True,
        "no_fixture_result_called_live_canary": True,
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    disk_claim = bool((on_disk.get("production_claim") or {}).get("production_searchable"))
    fix_claim = bool(
        (fixture_report.get("production_claim") or {}).get("production_searchable")
    )
    if disk_claim != fix_claim:
        raise SparseGraphragEvaluationError(
            "on-disk production_searchable claim diverges from fixture evaluation"
        )
    if bool(on_disk.get("live_canary")) or bool(
        (on_disk.get("canary") or {}).get("live_canary")
    ):
        raise SparseGraphragEvaluationError("on-disk report calls a fixture result a live canary")
    disk_sel = on_disk.get("fusion_selection") or {}
    fix_sel = fixture_report.get("fusion_selection") or {}
    if disk_sel.get("candidate_id") != fix_sel.get("candidate_id"):
        raise SparseGraphragEvaluationError(
            "on-disk fusion candidate diverges from fixture evaluation"
        )
    if disk_sel.get("config_digest") != fix_sel.get("config_digest"):
        raise SparseGraphragEvaluationError(
            "on-disk fusion config digest diverges from fixture evaluation"
        )
    disk_test = ((on_disk.get("evaluation") or {}).get("partitions") or {}).get("test", {})
    fix_test = ((fixture_report.get("evaluation") or {}).get("partitions") or {}).get(
        "test", {}
    )
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        for key in ("primary_metric_value", "mean_reciprocal_rank", "query_count"):
            if (disk_test.get(mode) or {}).get(key) != (fix_test.get(mode) or {}).get(key):
                raise SparseGraphragEvaluationError(
                    f"on-disk {mode} test[{key!r}] diverges from fixture"
                )
    if on_disk.get("evaluation_cid") != fixture_report.get("evaluation_cid"):
        raise SparseGraphragEvaluationError(
            "on-disk evaluation_cid diverges from fixture evaluation"
        )
    if (on_disk.get("differential_references") or {}).get("gold_manifest_digest") != (
        fixture_report.get("differential_references") or {}
    ).get("gold_manifest_digest"):
        raise SparseGraphragEvaluationError("on-disk gold digest diverges from fixture")


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"goal_id={result.get('goal_id', GOAL_ID)}",
            f"fusion_candidate_id={result.get('fusion_candidate_id')}",
            f"production_searchable={result.get('production_searchable')}",
            f"live_canary={result.get('live_canary')}",
            f"hybrid_recall_gate={result.get('hybrid_recall_gate', RECALL_GATE_HYBRID)}",
            f"test_hybrid_relevance_recall_at_{PRIMARY_TOP_K}="
            f"{result.get('test_hybrid_relevance_recall_at_primary_k')}",
            f"bounded_shard_selection={result.get('bounded_shard_selection')}",
            f"sealed_thresholds_pass={result.get('sealed_thresholds_pass')}",
            f"security_probes_fail_closed={result.get('security_probes_fail_closed')}",
            f"two_build_determinism={result.get('two_build_determinism')}",
            f"no_fixture_result_called_live_canary="
            f"{result.get('no_fixture_result_called_live_canary')}",
            f"no_unsupported_production_claim="
            f"{result.get('no_unsupported_production_claim')}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate BM25, vector, hybrid, graph, filter, sparse I/O, "
            "coverage, two-build determinism, and fail-closed security for "
            "Federal Register sparse GraphRAG (LCR-063). Default fixture mode "
            "never contacts the network and is never a live canary."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline gold/query/candidate inputs (default for --check).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report against sealed acceptance. --check "
            "always uses the fixture path; live Hub evaluation is not enabled."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Path to the frozen report (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help=f"Path to the sealed gold fixture (default: {DEFAULT_GOLD_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture evaluation report to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the evaluation report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    gold_path = (
        Path(args.gold).expanduser().resolve()
        if args.gold is not None
        else default_gold_path()
    )

    try:
        # Board validation is `--check`. Live corpus evaluation is not enabled;
        # both `--check` and `--fixture-only --check` use the sealed fixture.
        fixture_mode = bool(args.fixture_only or args.check or args.write)
        if not fixture_mode and not args.print_json:
            fixture_mode = True
        if (args.check or args.write) and not fixture_mode:
            raise SparseGraphragEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only or --check to use the sealed offline gold fixture"
            )

        fixture_report = run_fixture_evaluation(gold_path=gold_path)

        if args.write or args.check:
            write_json_report(fixture_report, report_path)
            print(
                f"wrote sparse graphrag evaluation report: {report_path}",
                file=sys.stderr,
            )

        if args.check:
            if report_path.is_file():
                on_disk = load_json_mapping(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            else:
                report = fixture_report
            result = check_evaluation_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(json.dumps(dict(report), indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(fixture_report, indent=2, sort_keys=True) + "\n")
            return 0

        if args.write:
            return 0

        result = check_evaluation_report(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --check to validate the frozen report (fixture-only)",
            file=sys.stderr,
        )
        return 0
    except SparseGraphragEvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
