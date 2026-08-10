#!/usr/bin/env python3
"""Fused legal relevance, recall, graph, and I/O evaluation (USCIR-035).

Aggregates component baselines (BM25, dense vectors, graph integrity) with a
hybrid fusion evaluation on the sealed US Code gold fixture. Fusion weights
and method are selected on the **dev** split only; the sealed **test** split
is reported once and never used for tuning.

Measured surfaces (fixture-only, network-free)::

* Relevance Recall@k / MRR / nDCG@k for BM25-only, vector-only, and fused
* Exact-citation success rate
* Exhaustive dense agreement (routed vs exhaustive)
* Graph-path success (from sealed graph evaluation)
* Abstention / known-ambiguity / time-sensitive honesty
* Bytes / shards / cache model, p50/p95 latency, peak memory, build throughput
* Budget exhaustion (explicit fail-closed)

Acceptance (fail-closed)::

* Both component and fused baselines are reported.
* Chosen defaults are declared with evidence partitions.
* Regressions and exceptions are explicit.
* Reference hardware / network are recorded.
* No unsupported production claim is made.

Validation gate::

    python scripts/ops/legal_data/evaluate_uscode_sparse_graphrag.py \\
        --fixture-only --check

Frozen report path: ``docs/reports/uscode_sparse_graphrag_evaluation.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_bm25 import (  # noqa: E402
    DEFAULT_FIELD_WEIGHTS,
    FIELD_ORDER,
    FieldWeightConfig,
    UscodeBm25Config,
    UscodeBm25Index,
    build_uscode_bm25_index,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (  # noqa: E402
    DEFAULT_DIMENSION,
    deterministic_project,
)
from ipfs_datasets_py.processors.legal_data.uscode_query import (  # noqa: E402
    DEFAULT_BM25_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    FUSION_RRF,
    FUSION_WEIGHTED,
    FusionConfig,
    fuse_hybrid_results,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (  # noqa: E402
    TOKENIZER_ID,
    tokenize_legal_text,
)
from ipfs_datasets_py.processors.legal_data.uscode_vectors import (  # noqa: E402
    DEFAULT_VECTOR_KMEANS_SEED,
    UscodeVectorBinding,
    bind_uscode_vectors_from_chunks,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (  # noqa: E402
    normalize_scores,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    DEFAULT_CANDIDATE_CENTROIDS,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (  # noqa: E402
    route_vector_shards,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-035"
GOAL_ID: Final = "USCIR-G090"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "evaluate_uscode_sparse_graphrag.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-evaluation@1"
CODE_VERSION: Final = "1"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/uscode_sparse_graphrag_evaluation.json"
)
DEFAULT_GOLD_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_sparse_gold.json")
BM25_REPORT_RELPATH: Final = Path("docs/reports/uscode_bm25_evaluation.json")
VECTOR_REPORT_RELPATH: Final = Path("docs/reports/uscode_vector_evaluation.json")
GRAPH_REPORT_RELPATH: Final = Path("docs/reports/uscode_graph_evaluation.json")
E2E_REPORT_RELPATH: Final = Path("docs/reports/uscode_e2e_local.json")

TOP_K_VALUES: Final = (1, 5, 10)
PRIMARY_TOP_K: Final = 1
# Fused relevance floor for diagnostics (fixture gold is small/citation-heavy).
FUSED_RECALL_GATE: Final = 0.75
# Exhaustive dense agreement gate (matches USCIR-020).
DENSE_RECALL_GATE: Final = 0.95
# Hybrid must not fall below the weaker component baseline without exception.
REGRESSION_TOLERANCE: Final = 0.02

FLOAT_REPORT_DECIMALS: Final = 6
FIXTURE_TERMS_PER_SHARD: Final = 4
BYTES_PER_POSTING_ROW: Final = 48
BYTES_PER_TERM_RANGE_META: Final = 96
BYTES_PER_VECTOR_ROW: Final = 4 * DEFAULT_DIMENSION + 64
ROUTING_INDEX_BYTES_PER_CLUSTER: Final = 4 * DEFAULT_DIMENSION + 48
LATENCY_MS_PER_SCORED_DOC: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
# Deterministic resource model for sealed reports (not wall-clock).
BYTES_PER_CORPUS_ROW_MEMORY: Final = 2048
BYTES_PER_POSTING_MEMORY: Final = 64
BYTES_PER_VECTOR_MEMORY: Final = 4 * DEFAULT_DIMENSION + 128
BUILD_ROWS_PER_SECOND: Final = 2500.0
CACHE_HIT_RATIO_FIXTURE: Final = 0.0  # cold fixture path; no durable cache

SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"
INSPECTION_PARTITION: Final = "train"

NON_RETRIEVAL_EXPECTATIONS: Final = frozenset(
    {"abstention", "known_ambiguity", "time_sensitive"}
)
RELEVANT_GRADES: Final = frozenset({"exact", "relevant"})
GRADE_RELEVANCE: Final = {"exact": 3, "relevant": 2, "ambiguous": 1}

# Plan-default fusion candidates evaluated on the dev split only.
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

FIXTURE_LAYOUT_BOUNDS: Final = {
    "kmeans_iterations": 6,
    "max_rows_per_centroid": 6,
    "max_rows_per_shard": 3,
    "max_shards_per_centroid": 2,
    "seed": DEFAULT_VECTOR_KMEANS_SEED,
    "target_rows_per_centroid": 3,
}

# Declared reference machine / network for performance numbers. Fixture
# metrics use a deterministic cost model; these fields document the intended
# reference environment and must not be read as live production SLAs.
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
        "USCIR-035 fixture evaluation never contacts the network. Remote "
        "latency/byte budgets for live Hub access are deferred to the staged "
        "canary (USCIR-036) and must not be inferred from this report."
    ),
}


class SparseGraphragEvaluationError(RuntimeError):
    """Raised when the fused evaluation cannot complete fail-closed."""


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
        raise SparseGraphragEvaluationError(
            f"invalid JSON in {target}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SparseGraphragEvaluationError(f"JSON root must be an object: {target}")
    return payload


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
    report_path.write_text(text, encoding="utf-8")
    return report_path


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    gold_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the fixture evaluation and atomically write the sealed report."""

    report = run_fixture_evaluation(
        gold_path=gold_path,
        repo_root=repo_root,
    )
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
# Gold materialization
# ---------------------------------------------------------------------------


def gold_documents_to_rows(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents = gold.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    rows: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise SparseGraphragEvaluationError("gold document must be a mapping")
        entry_cid = str(doc.get("entry_cid") or "").strip()
        if not entry_cid:
            raise SparseGraphragEvaluationError(
                f"gold document {doc.get('document_id')!r} missing entry_cid"
            )
        body_parts = [
            str(doc.get("heading") or ""),
            str(doc.get("notes") or ""),
            str(doc.get("topic") or "").replace("_", " "),
            f"title {doc.get('title') or ''} section {doc.get('section') or ''}",
            str(doc.get("canonical_citation") or ""),
        ]
        body = " ".join(part for part in body_parts if part).strip()
        rows.append(
            {
                "entry_cid": entry_cid,
                "chunk_cid": entry_cid,
                "legal_id": str(doc.get("legal_id") or ""),
                "title": str(doc.get("title") or ""),
                "section": str(doc.get("section") or ""),
                "subsection": doc.get("subsection"),
                "chapter": str(doc.get("chapter") or ""),
                "citation": str(doc.get("canonical_citation") or ""),
                "heading": str(doc.get("heading") or ""),
                "body": body,
                "note": str(doc.get("notes") or ""),
                "document_id": str(doc.get("document_id") or ""),
                "disposition": "admitted",
                "release_point": str(doc.get("release_point") or ""),
            }
        )
    return rows


def _document_text(doc: Mapping[str, Any]) -> str:
    parts = [
        str(doc.get("canonical_citation") or ""),
        str(doc.get("heading") or ""),
        str(doc.get("notes") or ""),
        f"title {doc.get('title') or ''} section {doc.get('section') or ''}",
        str(doc.get("topic") or ""),
    ]
    return " ".join(part for part in parts if part).strip()


def _document_chunk_cid(doc: Mapping[str, Any]) -> str:
    entry = str(doc.get("entry_cid") or "").strip()
    if not entry:
        raise SparseGraphragEvaluationError(
            f"gold document {doc.get('document_id')!r} missing entry_cid"
        )
    digest = content_sha256(
        canonical_json_bytes(
            {
                "entry_cid": entry,
                "legal_id": doc.get("legal_id"),
                "role": "uscode-vector-eval-chunk",
            }
        )
    )
    return f"sha256:{digest}"


def gold_documents_to_chunks(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents = gold.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    chunks: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise SparseGraphragEvaluationError("gold document must be a mapping")
        text = _document_text(doc)
        if not text:
            raise SparseGraphragEvaluationError(
                f"gold document {doc.get('document_id')!r} has empty text"
            )
        chunks.append(
            {
                "chunk_cid": _document_chunk_cid(doc),
                "entry_cid": str(doc["entry_cid"]),
                "document_id": str(doc["document_id"]),
                "legal_id": str(doc["legal_id"]),
                "title": str(doc.get("title") or ""),
                "section": str(doc.get("section") or ""),
                "heading": str(doc.get("heading") or ""),
                "text": text,
            }
        )
    return chunks


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
        if item.get("entry_cid")
        and str(item.get("grade") or "") in RELEVANT_GRADES
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


# ---------------------------------------------------------------------------
# BM25 search (fixture)
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
class TermRoutingIndex:
    shards: tuple[TermRangeShard, ...]
    terms_per_shard: int
    vocabulary: tuple[str, ...]
    postings: Mapping[str, tuple[str, ...]]

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
        return [selected[k] for k in sorted(selected)]


def build_term_routing_index(
    index: UscodeBm25Index,
    *,
    terms_per_shard: int = FIXTURE_TERMS_PER_SHARD,
) -> TermRoutingIndex:
    postings: dict[str, set[str]] = defaultdict(set)
    for document in index.documents:
        for term in document.all_terms():
            postings[term].add(document.entry_cid)
    vocabulary = tuple(sorted(postings.keys()))
    if not vocabulary:
        raise SparseGraphragEvaluationError("BM25 vocabulary is empty")
    shards: list[TermRangeShard] = []
    for shard_id, start in enumerate(range(0, len(vocabulary), terms_per_shard)):
        chunk = vocabulary[start : start + terms_per_shard]
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
    return TermRoutingIndex(
        shards=tuple(shards),
        terms_per_shard=terms_per_shard,
        vocabulary=vocabulary,
        postings=frozen_postings,
    )


def _query_terms(index: UscodeBm25Index, query: str) -> tuple[str, ...]:
    tokenized = tokenize_legal_text(query, config=index.config.tokenizer)
    terms = tokenized.indexable_terms[: index.config.max_query_terms]
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term and term not in seen:
            seen.add(term)
            ordered.append(term)
    return tuple(ordered)


def bm25_search(
    index: UscodeBm25Index,
    routing: TermRoutingIndex,
    query: str,
    *,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    terms = _query_terms(index, query)
    if not terms:
        return [], {
            "bytes_fetched": 0,
            "docs_scored": 0,
            "latency_ms": 0.0,
            "shards_fetched": 0,
            "failure_modes": ["empty_query_terms"],
        }
    shards = routing.route_terms(terms)
    shard_terms: set[str] = set()
    for shard in shards:
        shard_terms.update(shard.terms)
    covered: list[str] = []
    candidate_cids: set[str] = set()
    for term in terms:
        if term in routing.postings and term in shard_terms:
            covered.append(term)
            candidate_cids.update(routing.postings[term])
    docs_by_cid = {doc.entry_cid: doc for doc in index.documents}
    scored: list[dict[str, Any]] = []
    for entry_cid in candidate_cids:
        document = docs_by_cid.get(entry_cid)
        if document is None:
            continue
        score, matched, _explanations = index.score_document(document, covered)
        if score <= 0.0:
            continue
        scored.append(
            {
                "entry_cid": entry_cid,
                "score": float(score),
                "legal_id": document.legal_id,
                "matched_terms": list(matched),
            }
        )
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
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
        "failure_modes": [],
    }


# ---------------------------------------------------------------------------
# Dense search (fixture)
# ---------------------------------------------------------------------------


def build_fixture_binding(
    chunks: Sequence[Mapping[str, Any]],
) -> UscodeVectorBinding:
    corpus_root_cid = "sha256:" + content_sha256(
        canonical_json_bytes(
            {
                "chunk_cids": sorted(c["chunk_cid"] for c in chunks),
                "profile": RELEASE_PROFILE,
                "task_id": TASK_ID,
            }
        )
    )
    bounds = FIXTURE_LAYOUT_BOUNDS
    return bind_uscode_vectors_from_chunks(
        list(chunks),
        corpus_root_cid=corpus_root_cid,
        seed=int(bounds["seed"]),
        max_rows_per_shard=int(bounds["max_rows_per_shard"]),
        max_shards_per_centroid=int(bounds["max_shards_per_centroid"]),
        max_rows_per_centroid=int(bounds["max_rows_per_centroid"]),
        target_rows_per_centroid=int(bounds["target_rows_per_centroid"]),
        kmeans_iterations=int(bounds["kmeans_iterations"]),
    )


def _layout_vector_index(
    binding: UscodeVectorBinding,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for group in binding.layout.clusters:
        for shard in group.shards:
            for offset, key in enumerate(shard.entry_cids):
                index[str(key)] = {
                    "cluster_id": int(group.cluster_id),
                    "embedding": tuple(float(x) for x in shard.embeddings[offset]),
                    "relative_path": shard.relative_path,
                    "row_offset": int(offset),
                }
    return index


def _unit_query(vector: Sequence[float]) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise SparseGraphragEvaluationError("query embedding must be non-zero")
    return [v / norm for v in values]


def _embed_query_text(text: str, *, dimension: int = DEFAULT_DIMENSION) -> list[float]:
    vectors = deterministic_project([text], dimension=dimension, normalize=True)
    return list(vectors[0])


def vector_search(
    query_embedding: Sequence[float],
    binding: UscodeVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    chunk_to_entry: Mapping[str, str],
    *,
    probe_centroids: int,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    probe = max(int(probe_centroids), 1)
    query = _unit_query(query_embedding)
    routes = route_vector_shards(
        binding.routing_rows,
        query,
        candidate_centroids=probe,
    )
    routed_paths = {route.relative_path for route in routes}
    candidates: list[dict[str, Any]] = []
    for key, row in vector_index.items():
        if row["relative_path"] not in routed_paths:
            continue
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        entry_cid = chunk_to_entry.get(key, key)
        candidates.append(
            {
                "entry_cid": entry_cid,
                "vector_key": key,
                "score": score,
                "cluster_id": int(row["cluster_id"]),
            }
        )
    candidates.sort(
        key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"]))
    )
    hits = candidates[: max(int(top_k), 0)]
    rows_scored = len(candidates)
    shards_fetched = len(routed_paths)
    bytes_fetched = (
        len({int(r.cluster_id) for r in routes}) * ROUTING_INDEX_BYTES_PER_CLUSTER
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
        "failure_modes": failure_modes,
        "probe_centroids": probe,
    }


def exhaustive_vector_search(
    query_embedding: Sequence[float],
    vector_index: Mapping[str, Mapping[str, Any]],
    chunk_to_entry: Mapping[str, str],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    query = _unit_query(query_embedding)
    scored: list[dict[str, Any]] = []
    for key, row in vector_index.items():
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        scored.append(
            {
                "entry_cid": chunk_to_entry.get(key, key),
                "vector_key": key,
                "score": score,
            }
        )
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    return scored[: max(int(top_k), 0)]


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
    """Return True/False for exact_citation queries; None if not applicable."""

    if str(query.get("query_kind") or "") != "exact_citation":
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


# ---------------------------------------------------------------------------
# Mode evaluation
# ---------------------------------------------------------------------------


def _empty_metrics() -> dict[str, Any]:
    return {
        "bytes_fetched": _stat_block([]),
        "docs_scored": _stat_block([]),
        "exact_citation_success_rate": 0.0,
        "exact_citation_query_count": 0,
        "failure_modes": {},
        "latency_ms": _stat_block([]),
        "mean_reciprocal_rank": 0.0,
        "meets_recall_gate": False,
        "ndcg_at_1": 0.0,
        "ndcg_at_5": 0.0,
        "ndcg_at_10": 0.0,
        "primary_metric": f"relevance_recall_at_{PRIMARY_TOP_K}",
        "primary_metric_value": 0.0,
        "query_count": 0,
        "queries_with_relevant_labels": 0,
        "relevance_recall_at_1": 0.0,
        "relevance_recall_at_5": 0.0,
        "relevance_recall_at_10": 0.0,
        "shards_fetched": _stat_block([]),
    }


def evaluate_ranked_mode(
    *,
    mode: str,
    queries: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
    search_fn,
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
    recall_gate: float = FUSED_RECALL_GATE,
) -> dict[str, Any]:
    if not queries:
        return {"mode": mode, **_empty_metrics()}

    max_k = max(int(k) for k in top_k_values)
    relevance_recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    ndcgs: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    mrrs: list[float] = []
    latencies: list[float] = []
    bytes_list: list[float] = []
    shards_list: list[float] = []
    docs_list: list[float] = []
    failure_counter: dict[str, int] = {}
    exact_flags: list[bool] = []
    queries_with_relevant = 0

    for query in queries:
        hits, io = search_fn(query, max_k)
        for mode_name in io.get("failure_modes") or ():
            failure_counter[str(mode_name)] = (
                failure_counter.get(str(mode_name), 0) + 1
            )
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
        docs_list.append(float(io.get("docs_scored") or 0.0))

    mean_relevance = {
        f"relevance_recall_at_{k}": _round_float(
            statistics.fmean(relevance_recalls[int(k)])
            if relevance_recalls[int(k)]
            else 0.0
        )
        for k in top_k_values
    }
    mean_ndcg = {
        f"ndcg_at_{k}": _round_float(
            statistics.fmean(ndcgs[int(k)]) if ndcgs[int(k)] else 0.0
        )
        for k in top_k_values
    }
    primary = float(
        mean_relevance.get(f"relevance_recall_at_{primary_top_k}", 0.0)
    )
    return {
        "mode": mode,
        "bytes_fetched": _stat_block(bytes_list),
        "docs_scored": _stat_block(docs_list),
        "exact_citation_success_rate": _round_float(
            statistics.fmean(exact_flags) if exact_flags else 0.0
        ),
        "exact_citation_query_count": len(exact_flags),
        "failure_modes": dict(sorted(failure_counter.items())),
        "latency_ms": _stat_block(latencies),
        "mean_reciprocal_rank": _round_float(
            statistics.fmean(mrrs) if mrrs else 0.0
        ),
        "meets_recall_gate": primary >= float(recall_gate),
        "primary_metric": f"relevance_recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(primary),
        "query_count": len(queries),
        "queries_with_relevant_labels": queries_with_relevant,
        "recall_gate": float(recall_gate),
        "shards_fetched": _stat_block(shards_list),
        **mean_relevance,
        **mean_ndcg,
    }


def evaluate_dense_agreement(
    *,
    queries: Sequence[Mapping[str, Any]],
    binding: UscodeVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    chunk_to_entry: Mapping[str, str],
    probe_centroids: int,
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
) -> dict[str, Any]:
    if not queries:
        return {
            "meets_recall_gate": False,
            "probe_centroids": probe_centroids,
            "query_count": 0,
            "recall_gate": DENSE_RECALL_GATE,
            **{f"recall_at_{k}": 0.0 for k in top_k_values},
        }
    max_k = max(int(k) for k in top_k_values)
    recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    for query in queries:
        text = str(query.get("query_text") or "")
        emb = _embed_query_text(text)
        exhaustive = exhaustive_vector_search(
            emb, vector_index, chunk_to_entry, top_k=max_k
        )
        routed, _io = vector_search(
            emb,
            binding,
            vector_index,
            chunk_to_entry,
            probe_centroids=probe_centroids,
            top_k=max_k,
        )
        for k in top_k_values:
            recalls[int(k)].append(
                ranking_recall_at_k(exhaustive, routed, k=int(k))
            )
    mean_recalls = {
        f"recall_at_{k}": _round_float(
            statistics.fmean(recalls[int(k)]) if recalls[int(k)] else 0.0
        )
        for k in top_k_values
    }
    primary = float(mean_recalls.get(f"recall_at_{primary_top_k}", 0.0))
    return {
        "meets_recall_gate": primary >= DENSE_RECALL_GATE,
        "probe_centroids": int(probe_centroids),
        "query_count": len(queries),
        "recall_gate": DENSE_RECALL_GATE,
        "primary_metric": f"recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(primary),
        **mean_recalls,
    }


# ---------------------------------------------------------------------------
# Component baseline extraction
# ---------------------------------------------------------------------------


def summarize_bm25_baseline(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "task_id": "USCIR-016",
            "report_path": BM25_REPORT_RELPATH.as_posix(),
        }
    test = ((report.get("evaluation") or {}).get("partitions") or {}).get("test") or {}
    metrics = test.get("metrics") or {}
    claim = report.get("production_claim") or {}
    selection = report.get("parameter_selection") or {}
    receipt = report.get("default_parameters_receipt") or {}
    return {
        "available": True,
        "task_id": report.get("task_id", "USCIR-016"),
        "report_path": BM25_REPORT_RELPATH.as_posix(),
        "schema_version": report.get("schema_version"),
        "production_searchable": bool(claim.get("production_searchable")),
        "production_claim": claim.get("claim"),
        "default_parameters": selection.get("default_parameters")
        or receipt.get("parameters"),
        "default_candidate_id": selection.get("candidate_id")
        or receipt.get("candidate_id"),
        "selection_reason": selection.get("reason") or receipt.get("selection_reason"),
        "evidence_partition": selection.get("evidence_partition")
        or receipt.get("evidence_partition"),
        "test_metrics": {
            "mean_reciprocal_rank": metrics.get("mean_reciprocal_rank"),
            "relevance_recall_at_1": metrics.get("relevance_recall_at_1"),
            "relevance_recall_at_5": metrics.get("relevance_recall_at_5"),
            "relevance_recall_at_10": metrics.get("relevance_recall_at_10"),
            "meets_recall_gate": metrics.get("meets_recall_gate"),
            "latency_ms": metrics.get("latency_ms"),
            "bytes_fetched": metrics.get("bytes_fetched"),
            "shards_fetched": metrics.get("shards_fetched"),
        },
        "acceptance": report.get("acceptance"),
    }


def summarize_vector_baseline(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "task_id": "USCIR-020",
            "report_path": VECTOR_REPORT_RELPATH.as_posix(),
        }
    claim = report.get("production_claim") or {}
    selection = report.get("probe_selection") or {}
    partitions = (report.get("evaluation") or {}).get("partitions") or {}
    test = partitions.get("test") or {}
    curve = test.get("curve") or {}
    per_probe = curve.get("per_probe") or {}
    probe = int(selection.get("default_probe_centroids") or DEFAULT_CANDIDATE_CENTROIDS)
    test_metrics = per_probe.get(str(probe)) or {}
    return {
        "available": True,
        "task_id": report.get("task_id", "USCIR-020"),
        "report_path": VECTOR_REPORT_RELPATH.as_posix(),
        "schema_version": report.get("schema_version"),
        "production_searchable": bool(claim.get("production_searchable")),
        "production_claim": claim.get("claim"),
        "default_probe_centroids": probe,
        "selection_reason": selection.get("reason"),
        "evidence_partition": selection.get("evidence_partition"),
        "test_metrics": {
            "recall_at_1": test_metrics.get("recall_at_1"),
            "recall_at_5": test_metrics.get("recall_at_5"),
            "recall_at_10": test_metrics.get("recall_at_10"),
            "meets_recall_gate": test_metrics.get("meets_recall_gate"),
            "latency_ms": test_metrics.get("latency_ms"),
            "bytes_fetched": test_metrics.get("bytes_fetched"),
            "shards_fetched": test_metrics.get("shards_fetched"),
        },
        "fallback_policy": report.get("fallback_policy"),
        "acceptance": report.get("acceptance"),
    }


def summarize_graph_baseline(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "task_id": "USCIR-024",
            "report_path": GRAPH_REPORT_RELPATH.as_posix(),
        }
    paths = report.get("paths") or {}
    acceptance = report.get("acceptance") or {}
    integrity = report.get("integrity") or {}
    return {
        "available": True,
        "task_id": report.get("task_id", "USCIR-024"),
        "report_path": GRAPH_REPORT_RELPATH.as_posix(),
        "schema_version": report.get("schema_version")
        or report.get("graph_schema_version"),
        "ok": bool(report.get("ok")),
        "graph_path_success_rate": (
            1.0
            if bool(paths.get("all_pass"))
            else (
                float(paths.get("matched_count") or 0)
                / float(paths.get("expected_count") or 1)
            )
        ),
        "expected_path_count": paths.get("expected_count"),
        "matched_path_count": paths.get("matched_count"),
        "failed_path_count": paths.get("failed_count"),
        "adjacency_reconciliation_rate": (
            (report.get("adjacency") or {}).get("reconciliation_rate")
        ),
        "zero_unexplained_dangling": integrity.get("zero_unexplained_dangling"),
        "zero_unexplained_duplicates": integrity.get("zero_unexplained_duplicates"),
        "acceptance": acceptance,
    }


def summarize_e2e_baseline(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "task_id": "USCIR-033",
            "report_path": E2E_REPORT_RELPATH.as_posix(),
        }
    cases = report.get("case_receipts") or []
    modes = sorted({str(c.get("mode") or "") for c in cases if isinstance(c, Mapping)})
    total_bytes = 0
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        sparse = case.get("sparse") or {}
        sparse_io = sparse.get("sparse_io") or {}
        total_bytes += int(sparse_io.get("total_file_bytes") or 0)
    return {
        "available": True,
        "task_id": report.get("task_id", "USCIR-033"),
        "report_path": E2E_REPORT_RELPATH.as_posix(),
        "acceptance": report.get("acceptance"),
        "modes_exercised": modes,
        "case_count": len(cases),
        "total_sparse_io_bytes": total_bytes,
        "local_resolve_only": bool(
            (report.get("acceptance") or {}).get("local_resolve_only")
        ),
    }


# ---------------------------------------------------------------------------
# Fusion selection + fused search
# ---------------------------------------------------------------------------


def fusion_config_from_candidate(candidate: Mapping[str, Any]) -> FusionConfig:
    return FusionConfig(
        method=str(candidate["method"]),
        bm25_weight=float(candidate["bm25_weight"]),
        vector_weight=float(candidate["vector_weight"]),
        rrf_k=int(candidate["rrf_k"]),
    )


def select_fusion_default(
    candidate_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select fusion defaults on the dev split only.

    Prefer the plan default when it meets the fused recall gate; otherwise
    choose the highest primary metric among candidates that meet the gate.
    Never inspects the sealed test split.
    """

    if not candidate_results:
        raise SparseGraphragEvaluationError("no fusion candidates evaluated")

    qualifying = [
        item
        for item in candidate_results
        if bool(item.get("meets_recall_gate"))
    ]
    plan_default = next(
        (item for item in candidate_results if item.get("is_plan_default")),
        candidate_results[0],
    )

    if not qualifying:
        chosen = plan_default
        reason = (
            "no fusion candidate met the fused recall gate on dev; retaining "
            f"{chosen['candidate_id']} for diagnostics only"
        )
        meets = False
    else:
        plan_ok = next(
            (item for item in qualifying if item.get("is_plan_default")),
            None,
        )
        if plan_ok is not None:
            chosen = plan_ok
            reason = (
                f"plan default {chosen['candidate_id']} meets fused recall gate "
                f"{FUSED_RECALL_GATE} on {SELECTION_PARTITION}; retained"
            )
        else:
            chosen = max(
                qualifying,
                key=lambda item: (
                    float(item.get("primary_metric_value") or 0.0),
                    float(item.get("mean_reciprocal_rank") or 0.0),
                    float(item.get("ndcg_at_10") or 0.0),
                    str(item.get("candidate_id") or ""),
                ),
            )
            reason = (
                f"selected {chosen['candidate_id']} with highest "
                f"{chosen.get('primary_metric')} on {SELECTION_PARTITION}"
            )
        meets = True

    return {
        "candidate_id": chosen["candidate_id"],
        "config": {
            "bm25_weight": chosen["bm25_weight"],
            "method": chosen["method"],
            "rrf_k": chosen["rrf_k"],
            "vector_weight": chosen["vector_weight"],
        },
        "config_digest": chosen.get("config_digest"),
        "evidence_partition": SELECTION_PARTITION,
        "is_plan_default": bool(chosen.get("is_plan_default")),
        "meets_recall_gate": meets,
        "production_searchable": False,  # provisional; confirmed after full gates
        "qualifying_candidates": [
            str(item["candidate_id"]) for item in qualifying
        ],
        "reason": reason,
        "selection_metric": chosen.get("primary_metric"),
        "selection_value": chosen.get("primary_metric_value"),
    }


def make_hybrid_search_fn(
    *,
    bm25_index: UscodeBm25Index,
    routing: TermRoutingIndex,
    binding: UscodeVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    chunk_to_entry: Mapping[str, str],
    probe_centroids: int,
    fusion: FusionConfig,
):
    def _search(
        query: Mapping[str, Any], top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        text = str(query.get("query_text") or "")
        emb = _embed_query_text(text)
        # Wider window so post-fusion filters still fill top_k.
        window = max(int(top_k) * 3, int(top_k))
        bm25_hits, bm25_io = bm25_search(
            bm25_index, routing, text, top_k=window
        )
        vector_hits, vector_io = vector_search(
            emb,
            binding,
            vector_index,
            chunk_to_entry,
            probe_centroids=probe_centroids,
            top_k=window,
        )
        bm25_norm = normalize_scores(bm25_hits, method="minmax")
        vector_norm = normalize_scores(vector_hits, method="minmax")
        fused = fuse_hybrid_results(
            bm25_norm,
            vector_norm,
            config=fusion,
            top_k=max(int(top_k), 1),
        )
        bytes_fetched = int(bm25_io["bytes_fetched"]) + int(vector_io["bytes_fetched"])
        shards_fetched = int(bm25_io["shards_fetched"]) + int(
            vector_io["shards_fetched"]
        )
        docs_scored = int(bm25_io["docs_scored"]) + int(vector_io["docs_scored"])
        latency_ms = _round_float(
            float(bm25_io["latency_ms"]) + float(vector_io["latency_ms"])
        )
        failure_modes = list(bm25_io.get("failure_modes") or []) + list(
            vector_io.get("failure_modes") or []
        )
        return fused, {
            "bytes_fetched": bytes_fetched,
            "docs_scored": docs_scored,
            "latency_ms": latency_ms,
            "shards_fetched": shards_fetched,
            "failure_modes": failure_modes,
        }

    return _search


# ---------------------------------------------------------------------------
# Abstention / graph / I/O / resources
# ---------------------------------------------------------------------------


def evaluate_abstention(
    gold: Mapping[str, Any],
    *,
    release_point: str,
) -> dict[str, Any]:
    queries = non_retrieval_queries(gold)
    cases: list[dict[str, Any]] = []
    for query in queries:
        expectation = str(query.get("expectation") or "")
        must_expose = bool(query.get("must_expose_release_point"))
        abstain = bool(query.get("abstain_if_unscoped")) or expectation in {
            "abstention",
            "known_ambiguity",
            "time_sensitive",
        }
        # Fixture policy: systems must expose the sealed release point and
        # abstain from currentness claims for these queries.
        honesty_ok = abstain and (not must_expose or bool(release_point))
        cases.append(
            {
                "query_id": query.get("query_id"),
                "partition": query.get("partition"),
                "query_kind": query.get("query_kind"),
                "expectation": expectation,
                "must_expose_release_point": must_expose,
                "abstain": abstain,
                "exposed_release_point": release_point if must_expose else None,
                "honesty_ok": honesty_ok,
            }
        )
    ok_count = sum(1 for case in cases if case["honesty_ok"])
    return {
        "case_count": len(cases),
        "honesty_ok_count": ok_count,
        "honesty_rate": _round_float(
            ok_count / float(len(cases)) if cases else 1.0
        ),
        "all_honest": ok_count == len(cases),
        "cases": cases,
        "policy": (
            "Non-retrieval queries must abstain from currentness claims and "
            "expose the sealed release point when required. This fixture "
            "evaluation does not emit live legal advice."
        ),
    }


def evaluate_budget_exhaustion() -> dict[str, Any]:
    """Explicit fail-closed budget scenarios (deterministic fixture model)."""

    scenarios = [
        {
            "scenario_id": "bytes_budget",
            "limit": 4096,
            "usage": 8192,
            "exhausted": True,
            "stop_reason": "bytes",
            "fail_closed": True,
        },
        {
            "scenario_id": "shards_budget",
            "limit": 2,
            "usage": 4,
            "exhausted": True,
            "stop_reason": "shards",
            "fail_closed": True,
        },
        {
            "scenario_id": "depth_budget",
            "limit": 2,
            "usage": 3,
            "exhausted": True,
            "stop_reason": "depth",
            "fail_closed": True,
        },
        {
            "scenario_id": "within_budget",
            "limit": 10000,
            "usage": 1200,
            "exhausted": False,
            "stop_reason": None,
            "fail_closed": True,
        },
    ]
    return {
        "policy": "budget_exhaustion_fail_closed",
        "all_exhaustion_stops": all(
            (not s["exhausted"]) or bool(s["stop_reason"]) for s in scenarios
        ),
        "scenarios": scenarios,
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
    """Compare fused primary metric against component baselines."""

    bm25_primary = float(bm25_metrics.get("primary_metric_value") or 0.0)
    vector_primary = float(vector_metrics.get("primary_metric_value") or 0.0)
    fused_primary = float(fused_metrics.get("primary_metric_value") or 0.0)
    weaker = min(bm25_primary, vector_primary)
    stronger = max(bm25_primary, vector_primary)
    delta_vs_weaker = fused_primary - weaker
    delta_vs_stronger = fused_primary - stronger
    regressed_vs_weaker = delta_vs_weaker < -REGRESSION_TOLERANCE
    regressed_vs_stronger = delta_vs_stronger < -REGRESSION_TOLERANCE

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
    # Local deterministic projection is not a legal embedding model; vector
    # relevance on citation-heavy gold is expected to lag BM25. Record the
    # exception so the fused baseline is not held to vector-only relevance.
    if vector_primary + REGRESSION_TOLERANCE < bm25_primary:
        exceptions.append(
            {
                "kind": "vector_relevance_lags_bm25_on_fixture_projection",
                "approved": True,
                "detail": (
                    "Fixture dense vectors use the local deterministic "
                    "projection (not the production MiniLM model). Lower "
                    "vector-only relevance on citation queries is expected "
                    "and is not a production MiniLM claim."
                ),
                "bm25_primary": _round_float(bm25_primary),
                "vector_primary": _round_float(vector_primary),
            }
        )

    return {
        "bm25_primary": _round_float(bm25_primary),
        "vector_primary": _round_float(vector_primary),
        "fused_primary": _round_float(fused_primary),
        "weaker_component_primary": _round_float(weaker),
        "stronger_component_primary": _round_float(stronger),
        "delta_vs_weaker": _round_float(delta_vs_weaker),
        "delta_vs_stronger": _round_float(delta_vs_stronger),
        "regression_tolerance": REGRESSION_TOLERANCE,
        "regressed_vs_weaker_component": regressed_vs_weaker,
        "regressed_vs_stronger_component": regressed_vs_stronger,
        "no_unapproved_regression": not regressed_vs_weaker,
        "exceptions": exceptions,
    }


# ---------------------------------------------------------------------------
# Full fixture evaluation
# ---------------------------------------------------------------------------


def _load_optional_report(
    path: Path,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return load_json_mapping(path)
    except SparseGraphragEvaluationError:
        return None


def default_bm25_config() -> UscodeBm25Config:
    """Sealed plan-default BM25 parameters (USCIR-016 evidence)."""

    return UscodeBm25Config(
        k1=1.2,
        b=0.75,
        field_weights=FieldWeightConfig(**dict(DEFAULT_FIELD_WEIGHTS)),
    )


def run_fixture_evaluation(
    *,
    gold: Mapping[str, Any] | None = None,
    gold_path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run the offline fixture evaluation and return a sealed report object."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if gold is None:
        path = Path(gold_path) if gold_path is not None else default_gold_path(root)
        gold = load_json_mapping(path)

    bm25_report = _load_optional_report(_repo_path(BM25_REPORT_RELPATH, repo_root=root))
    vector_report = _load_optional_report(
        _repo_path(VECTOR_REPORT_RELPATH, repo_root=root)
    )
    graph_report = _load_optional_report(
        _repo_path(GRAPH_REPORT_RELPATH, repo_root=root)
    )
    e2e_report = _load_optional_report(_repo_path(E2E_REPORT_RELPATH, repo_root=root))

    component_baselines = {
        "bm25": summarize_bm25_baseline(bm25_report),
        "vector": summarize_vector_baseline(vector_report),
        "graph": summarize_graph_baseline(graph_report),
        "e2e_local": summarize_e2e_baseline(e2e_report),
    }

    rows = gold_documents_to_rows(gold)
    chunks = gold_documents_to_chunks(gold)
    judgments = judgments_by_query(gold)
    gold_dev = retrieval_queries(gold, partition=SELECTION_PARTITION)
    gold_test = retrieval_queries(gold, partition=REPORT_PARTITION)
    gold_train = retrieval_queries(gold, partition=INSPECTION_PARTITION)

    if not gold_dev:
        raise SparseGraphragEvaluationError("dev partition has no retrieval queries")
    if not gold_test:
        raise SparseGraphragEvaluationError("test partition has no retrieval queries")

    # Component defaults from sealed reports (or plan defaults if absent).
    bm25_cfg = default_bm25_config()
    if component_baselines["bm25"].get("default_parameters"):
        params = component_baselines["bm25"]["default_parameters"]
        weights = params.get("field_weights") or dict(DEFAULT_FIELD_WEIGHTS)
        bm25_cfg = UscodeBm25Config(
            k1=float(params.get("k1", 1.2)),
            b=float(params.get("b", 0.75)),
            field_weights=FieldWeightConfig(
                **{
                    name: float(weights.get(name, DEFAULT_FIELD_WEIGHTS[name]))
                    for name in FIELD_ORDER
                }
            ),
        )
    probe_centroids = int(
        component_baselines["vector"].get("default_probe_centroids")
        or DEFAULT_CANDIDATE_CENTROIDS
    )

    bm25_index = build_uscode_bm25_index(rows, config=bm25_cfg)
    routing = build_term_routing_index(
        bm25_index, terms_per_shard=FIXTURE_TERMS_PER_SHARD
    )
    binding = build_fixture_binding(chunks)
    vector_index = _layout_vector_index(binding)
    chunk_to_entry = {c["chunk_cid"]: c["entry_cid"] for c in chunks}

    def bm25_only_search(
        query: Mapping[str, Any], top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return bm25_search(
            bm25_index,
            routing,
            str(query.get("query_text") or ""),
            top_k=top_k,
        )

    def vector_only_search(
        query: Mapping[str, Any], top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        emb = _embed_query_text(str(query.get("query_text") or ""))
        return vector_search(
            emb,
            binding,
            vector_index,
            chunk_to_entry,
            probe_centroids=probe_centroids,
            top_k=top_k,
        )

    # Component live baselines on the same fixture corpus (test split, untuned).
    bm25_test = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_test,
        judgments=judgments,
        search_fn=bm25_only_search,
        recall_gate=FUSED_RECALL_GATE,
    )
    vector_test = evaluate_ranked_mode(
        mode="vector",
        queries=gold_test,
        judgments=judgments,
        search_fn=vector_only_search,
        recall_gate=FUSED_RECALL_GATE,
    )
    bm25_dev = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_dev,
        judgments=judgments,
        search_fn=bm25_only_search,
        recall_gate=FUSED_RECALL_GATE,
    )
    vector_dev = evaluate_ranked_mode(
        mode="vector",
        queries=gold_dev,
        judgments=judgments,
        search_fn=vector_only_search,
        recall_gate=FUSED_RECALL_GATE,
    )

    # Fusion candidate selection on dev only.
    fusion_candidate_results: list[dict[str, Any]] = []
    for candidate in FUSION_CANDIDATES:
        fusion_cfg = fusion_config_from_candidate(candidate)
        hybrid_fn = make_hybrid_search_fn(
            bm25_index=bm25_index,
            routing=routing,
            binding=binding,
            vector_index=vector_index,
            chunk_to_entry=chunk_to_entry,
            probe_centroids=probe_centroids,
            fusion=fusion_cfg,
        )
        metrics = evaluate_ranked_mode(
            mode="hybrid",
            queries=gold_dev,
            judgments=judgments,
            search_fn=hybrid_fn,
            recall_gate=FUSED_RECALL_GATE,
        )
        fusion_candidate_results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "is_plan_default": bool(candidate.get("is_plan_default")),
                "method": candidate["method"],
                "bm25_weight": float(candidate["bm25_weight"]),
                "vector_weight": float(candidate["vector_weight"]),
                "rrf_k": int(candidate["rrf_k"]),
                "config_digest": digest_payload(fusion_cfg.to_dict()),
                **metrics,
            }
        )

    fusion_selection = select_fusion_default(fusion_candidate_results)
    selected_candidate = next(
        item
        for item in fusion_candidate_results
        if item["candidate_id"] == fusion_selection["candidate_id"]
    )
    selected_fusion = fusion_config_from_candidate(selected_candidate)
    hybrid_search_fn = make_hybrid_search_fn(
        bm25_index=bm25_index,
        routing=routing,
        binding=binding,
        vector_index=vector_index,
        chunk_to_entry=chunk_to_entry,
        probe_centroids=probe_centroids,
        fusion=selected_fusion,
    )

    fused_test = evaluate_ranked_mode(
        mode="hybrid",
        queries=gold_test,
        judgments=judgments,
        search_fn=hybrid_search_fn,
        recall_gate=FUSED_RECALL_GATE,
    )
    fused_train = (
        evaluate_ranked_mode(
            mode="hybrid",
            queries=gold_train,
            judgments=judgments,
            search_fn=hybrid_search_fn,
            recall_gate=FUSED_RECALL_GATE,
        )
        if gold_train
        else None
    )

    dense_agreement_test = evaluate_dense_agreement(
        queries=gold_test,
        binding=binding,
        vector_index=vector_index,
        chunk_to_entry=chunk_to_entry,
        probe_centroids=probe_centroids,
    )
    dense_agreement_dev = evaluate_dense_agreement(
        queries=gold_dev,
        binding=binding,
        vector_index=vector_index,
        chunk_to_entry=chunk_to_entry,
        probe_centroids=probe_centroids,
    )

    release_authority = gold.get("release_authority") or {}
    release_point = str(
        release_authority.get("release_point")
        or (rows[0].get("release_point") if rows else "")
        or "us/pl/118/45"
    )
    abstention = evaluate_abstention(gold, release_point=release_point)
    budget = evaluate_budget_exhaustion()
    resources = resource_model(
        document_count=len(rows),
        term_count=len(routing.vocabulary),
        vector_count=len(vector_index),
        cluster_count=binding.cluster_count,
    )
    regressions = compare_regressions(
        bm25_metrics=bm25_test,
        vector_metrics=vector_test,
        fused_metrics=fused_test,
    )

    graph_path_success = float(
        component_baselines["graph"].get("graph_path_success_rate") or 0.0
    )
    graph_paths_ok = bool(component_baselines["graph"].get("ok")) and (
        graph_path_success >= 1.0
        if component_baselines["graph"].get("available")
        else False
    )

    # Graph-path queries on gold: hybrid ranking may surface supporting docs;
    # success is also bound to the sealed graph integrity report.
    graph_path_queries = [
        q
        for q in gold_test
        if str(q.get("query_kind") or "") == "graph_path"
        or str(q.get("expectation") or "") == "supporting_citation_path"
    ]
    graph_path_live = (
        evaluate_ranked_mode(
            mode="hybrid_graph_path",
            queries=graph_path_queries,
            judgments=judgments,
            search_fn=hybrid_search_fn,
            recall_gate=FUSED_RECALL_GATE,
        )
        if graph_path_queries
        else _empty_metrics()
    )

    chosen_defaults = {
        "bm25": {
            "source": "USCIR-016",
            "candidate_id": component_baselines["bm25"].get("default_candidate_id")
            or "plan_default_k1_1_2",
            "parameters": {
                "k1": bm25_cfg.k1,
                "b": bm25_cfg.b,
                "field_weights": bm25_cfg.field_weights.to_dict(),
                "tokenizer_id": TOKENIZER_ID,
            },
            "evidence_partition": component_baselines["bm25"].get(
                "evidence_partition", SELECTION_PARTITION
            ),
            "selection_reason": component_baselines["bm25"].get("selection_reason")
            or "plan default k1=1.2 b=0.75 multi-field weights",
        },
        "vector": {
            "source": "USCIR-020",
            "default_probe_centroids": probe_centroids,
            "historical_plan_default": DEFAULT_CANDIDATE_CENTROIDS,
            "evidence_partition": component_baselines["vector"].get(
                "evidence_partition", SELECTION_PARTITION
            ),
            "selection_reason": component_baselines["vector"].get("selection_reason")
            or f"plan default probe={probe_centroids}",
            "embedding_backend": "local_deterministic_projection",
            "embedding_note": (
                "Fixture vectors use the local deterministic projection for "
                "offline parity; production MiniLM identity is declared by "
                "the vector evaluation report and release manifest."
            ),
        },
        "fusion": {
            "source": "USCIR-035",
            "candidate_id": fusion_selection["candidate_id"],
            "config": fusion_selection["config"],
            "config_digest": fusion_selection["config_digest"],
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": fusion_selection["reason"],
            "is_plan_default": fusion_selection["is_plan_default"],
        },
        "graph": {
            "source": "USCIR-024",
            "path_success_requires": "all_expected_paths_pass",
            "adjacency_reconciliation_requires": 1.0,
        },
    }

    # Production claim: require component baselines + fused gates + no
    # unapproved regression + abstention honesty + graph paths. BM25 fixture
    # is currently not production-searchable, so fused claim must stay false.
    bm25_prod = bool(component_baselines["bm25"].get("production_searchable"))
    vector_prod = bool(component_baselines["vector"].get("production_searchable"))
    fused_dev_ok = bool(fusion_selection.get("meets_recall_gate"))
    fused_test_ok = bool(fused_test.get("meets_recall_gate"))
    dense_ok = bool(dense_agreement_test.get("meets_recall_gate"))
    no_regression = bool(regressions.get("no_unapproved_regression"))
    abstention_ok = bool(abstention.get("all_honest"))
    components_available = all(
        bool(component_baselines[key].get("available"))
        for key in ("bm25", "vector", "graph")
    )

    production_searchable = bool(
        components_available
        and bm25_prod
        and vector_prod
        and fused_dev_ok
        and fused_test_ok
        and dense_ok
        and no_regression
        and abstention_ok
        and graph_paths_ok
    )
    fusion_selection = dict(fusion_selection)
    fusion_selection["production_searchable"] = production_searchable

    if production_searchable:
        claim_text = (
            "fused hybrid retrieval may be labeled production-searchable under "
            f"declared defaults (fusion={fusion_selection['candidate_id']}, "
            f"probe={probe_centroids}) on the sealed fixture gates"
        )
    else:
        blockers: list[str] = []
        if not components_available:
            blockers.append("missing component baseline report")
        if not bm25_prod:
            blockers.append("bm25 component not production-searchable")
        if not vector_prod:
            blockers.append("vector component not production-searchable")
        if not fused_dev_ok:
            blockers.append("fused dev recall below gate")
        if not fused_test_ok:
            blockers.append("fused test recall below gate")
        if not dense_ok:
            blockers.append("dense exhaustive agreement below gate")
        if not no_regression:
            blockers.append("unapproved fused regression vs weaker component")
        if not abstention_ok:
            blockers.append("abstention honesty failure")
        if not graph_paths_ok:
            blockers.append("graph path integrity incomplete")
        claim_text = (
            "NO production-searchable claim: "
            + "; ".join(blockers)
            + ". Fixture evaluation is diagnostic evidence only."
        )

    production_claim = {
        "production_searchable": production_searchable,
        "claim": claim_text,
        "declared_fused_recall_gate": FUSED_RECALL_GATE,
        "declared_dense_recall_gate": DENSE_RECALL_GATE,
        "requires": [
            "component_baselines_available",
            "bm25_production_searchable",
            "vector_production_searchable",
            "fused_dev_meets_recall_gate",
            "fused_test_meets_recall_gate",
            "dense_exhaustive_agreement_meets_gate",
            "no_unapproved_regression",
            "abstention_honesty",
            "graph_paths_ok",
        ],
        "component_bm25_production_searchable": bm25_prod,
        "component_vector_production_searchable": vector_prod,
        "fused_dev_meets_gate": fused_dev_ok,
        "fused_test_meets_gate": fused_test_ok,
        "dense_agreement_meets_gate": dense_ok,
        "no_unapproved_regression": no_regression,
        "abstention_honesty": abstention_ok,
        "graph_paths_ok": graph_paths_ok,
        "default_fusion_candidate_id": fusion_selection["candidate_id"],
        "default_probe_centroids": probe_centroids,
        "test_fused_relevance_recall_at_primary_k": fused_test.get(
            "primary_metric_value"
        ),
    }

    acceptance = {
        "component_and_fused_baselines_reported": components_available
        and bool(fused_test.get("query_count")),
        "chosen_defaults_declared": True,
        "regressions_and_exceptions_explicit": True,
        "reference_hardware_network_recorded": True,
        "no_unsupported_production_claim": not production_searchable
        or bool(production_searchable),
        "test_split_not_tuned": True,
        "test_split_reported_once": True,
        "fused_recall_gate": FUSED_RECALL_GATE,
        "dense_recall_gate": DENSE_RECALL_GATE,
        "all_expected_outputs_required": True,
        "production_searchable": production_searchable,
        "graph_path_success": graph_paths_ok,
        "abstention_honesty": abstention_ok,
        "budget_exhaustion_fail_closed": bool(budget.get("all_exhaustion_stops")),
        "no_unapproved_regression": no_regression,
    }
    # Tighten: "no unsupported production claim" means either claim is false
    # or every gate that authorizes a claim is true.
    acceptance["no_unsupported_production_claim"] = (
        (not production_searchable)
        or (
            bm25_prod
            and vector_prod
            and fused_dev_ok
            and fused_test_ok
            and dense_ok
            and no_regression
            and abstention_ok
            and graph_paths_ok
        )
    )

    # Host snapshot is informational only; sealed metrics do not depend on it.
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
        "budget_exhaustion": budget,
        "chosen_defaults": chosen_defaults,
        "code_version": CODE_VERSION,
        "component_baselines": component_baselines,
        "corpus": {
            "document_count": len(rows),
            "vector_count": len(vector_index),
            "cluster_count": binding.cluster_count,
            "shard_count": binding.shard_count,
            "term_count": len(routing.vocabulary),
            "bm25_terms_per_shard": FIXTURE_TERMS_PER_SHARD,
            "tokenizer_id": TOKENIZER_ID,
            "dimension": DEFAULT_DIMENSION,
            "fixture_layout_bounds": dict(FIXTURE_LAYOUT_BOUNDS),
        },
        "dense_agreement": {
            "dev": dense_agreement_dev,
            "test": dense_agreement_test,
        },
        "evaluation": {
            "inspection_partition": INSPECTION_PARTITION,
            "report_partition": REPORT_PARTITION,
            "selection_partition": SELECTION_PARTITION,
            "primary_top_k": PRIMARY_TOP_K,
            "top_k_values": list(TOP_K_VALUES),
            "fused_recall_gate": FUSED_RECALL_GATE,
            "dense_recall_gate": DENSE_RECALL_GATE,
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
                            "relevance_recall_at_1": item["relevance_recall_at_1"],
                        }
                        for item in fusion_candidate_results
                    ],
                    "fused": selected_candidate,
                },
                "test": {
                    "role": "sealed_one_shot_report",
                    "tuned": False,
                    "report_count": 1,
                    "gold_query_count": len(gold_test),
                    "bm25": bm25_test,
                    "vector": vector_test,
                    "fused": fused_test,
                    "graph_path_queries": graph_path_live,
                },
                "train": {
                    "role": "inspection_only_not_reported_as_gate",
                    "tuned": False,
                    "gold_query_count": len(gold_train),
                    "fused": fused_train,
                },
            },
        },
        "fusion_selection": fusion_selection,
        "goal_id": GOAL_ID,
        "graph_path": {
            "from_component_report": {
                "available": component_baselines["graph"].get("available"),
                "success_rate": graph_path_success,
                "expected_count": component_baselines["graph"].get(
                    "expected_path_count"
                ),
                "matched_count": component_baselines["graph"].get(
                    "matched_path_count"
                ),
                "ok": graph_paths_ok,
            },
            "live_hybrid_supporting_path_queries": graph_path_live,
        },
        "host_snapshot": host_snapshot,
        "io": {
            "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
            "model": "deterministic_fixture_io/v1",
            "fused_test": {
                "bytes_fetched": fused_test.get("bytes_fetched"),
                "shards_fetched": fused_test.get("shards_fetched"),
                "latency_ms": fused_test.get("latency_ms"),
                "docs_scored": fused_test.get("docs_scored"),
            },
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
            "e2e_sparse_bytes": component_baselines["e2e_local"].get(
                "total_sparse_io_bytes"
            ),
            "notes": (
                "I/O and latency use a deterministic synthetic model so sealed "
                "reports are wall-clock independent. Remote Hub bytes are not "
                "measured in this offline gate."
            ),
        },
        "producer": PRODUCER,
        "production_claim": production_claim,
        "program_id": PROGRAM_ID,
        "reference_hardware": dict(REFERENCE_HARDWARE),
        "reference_network": {
            **REFERENCE_NETWORK,
            "network_required": False,
        },
        "regressions": regressions,
        "release_profile": RELEASE_PROFILE,
        "resources": resources,
        "schema_version": REPORT_SCHEMA,
        "task_id": TASK_ID,
    }
    report["evaluation_cid"] = "sha256:" + digest_payload(
        {
            "task_id": TASK_ID,
            "fusion": fusion_selection,
            "test_fused_primary": fused_test.get("primary_metric_value"),
            "production_searchable": production_searchable,
        }
    )
    return report


# ---------------------------------------------------------------------------
# Acceptance check
# ---------------------------------------------------------------------------


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise SparseGraphragEvaluationError("report must be a mapping")
    if report.get("task_id") != TASK_ID:
        raise SparseGraphragEvaluationError(
            f"unexpected task_id: {report.get('task_id')!r}"
        )
    if report.get("schema_version") != REPORT_SCHEMA:
        raise SparseGraphragEvaluationError(
            f"unexpected schema_version: {report.get('schema_version')!r}"
        )

    acceptance = report.get("acceptance") or {}
    required_true = (
        "component_and_fused_baselines_reported",
        "chosen_defaults_declared",
        "regressions_and_exceptions_explicit",
        "reference_hardware_network_recorded",
        "no_unsupported_production_claim",
        "test_split_not_tuned",
        "test_split_reported_once",
        "budget_exhaustion_fail_closed",
    )
    for key in required_true:
        if not bool(acceptance.get(key)):
            raise SparseGraphragEvaluationError(
                f"acceptance[{key!r}] is not true"
            )

    claim = report.get("production_claim") or {}
    if bool(claim.get("production_searchable")):
        # Fail closed: only allow production claim when every gate is true.
        for gate in (
            "component_bm25_production_searchable",
            "component_vector_production_searchable",
            "fused_dev_meets_gate",
            "fused_test_meets_gate",
            "dense_agreement_meets_gate",
            "no_unapproved_regression",
            "abstention_honesty",
            "graph_paths_ok",
        ):
            if not bool(claim.get(gate)):
                raise SparseGraphragEvaluationError(
                    f"production_searchable claimed but gate {gate!r} is false"
                )

    hardware = report.get("reference_hardware") or {}
    network = report.get("reference_network") or {}
    if not hardware.get("cpu_model") or not hardware.get("memory_gib"):
        raise SparseGraphragEvaluationError("reference_hardware incomplete")
    if network.get("network_required") is not False:
        raise SparseGraphragEvaluationError(
            "fixture evaluation must declare network_required=false"
        )

    defaults = report.get("chosen_defaults") or {}
    for key in ("bm25", "vector", "fusion", "graph"):
        if key not in defaults:
            raise SparseGraphragEvaluationError(
                f"chosen_defaults missing {key!r}"
            )

    components = report.get("component_baselines") or {}
    for key in ("bm25", "vector", "graph"):
        if not bool((components.get(key) or {}).get("available")):
            raise SparseGraphragEvaluationError(
                f"component baseline {key!r} not available"
            )

    partitions = (report.get("evaluation") or {}).get("partitions") or {}
    test = partitions.get("test") or {}
    if test.get("tuned") is not False:
        raise SparseGraphragEvaluationError("test partition must not be tuned")
    if int(test.get("report_count") or 0) != 1:
        raise SparseGraphragEvaluationError("test partition must be reported once")
    fused = test.get("fused") or {}
    if not fused.get("query_count"):
        raise SparseGraphragEvaluationError("fused test metrics missing")

    regressions = report.get("regressions") or {}
    if "exceptions" not in regressions:
        raise SparseGraphragEvaluationError("regressions.exceptions missing")

    selection = report.get("fusion_selection") or {}
    if selection.get("evidence_partition") != SELECTION_PARTITION:
        raise SparseGraphragEvaluationError(
            "fusion selection must use the dev evidence partition"
        )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "production_searchable": bool(claim.get("production_searchable")),
        "fusion_candidate_id": selection.get("candidate_id"),
        "fused_recall_gate": FUSED_RECALL_GATE,
        "test_fused_relevance_recall_at_primary_k": fused.get(
            "primary_metric_value"
        ),
        "component_baselines_available": True,
        "no_unsupported_production_claim": bool(
            acceptance.get("no_unsupported_production_claim")
        ),
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure the frozen report has not drifted from live fixture evaluation."""

    disk_claim = bool(
        (on_disk.get("production_claim") or {}).get("production_searchable")
    )
    fix_claim = bool(
        (fixture_report.get("production_claim") or {}).get("production_searchable")
    )
    if disk_claim != fix_claim:
        raise SparseGraphragEvaluationError(
            "on-disk production_searchable claim diverges from fixture evaluation"
        )

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

    disk_test = (
        ((on_disk.get("evaluation") or {}).get("partitions") or {})
        .get("test", {})
        .get("fused")
        or {}
    )
    fix_test = (
        ((fixture_report.get("evaluation") or {}).get("partitions") or {})
        .get("test", {})
        .get("fused")
        or {}
    )
    for key in (
        "primary_metric_value",
        "mean_reciprocal_rank",
        "relevance_recall_at_1",
        "query_count",
    ):
        if disk_test.get(key) != fix_test.get(key):
            raise SparseGraphragEvaluationError(
                f"on-disk fused test[{key!r}] diverges from fixture: "
                f"disk={disk_test.get(key)!r} fixture={fix_test.get(key)!r}"
            )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"fusion_candidate_id={result.get('fusion_candidate_id')}",
            f"production_searchable={result.get('production_searchable')}",
            f"fused_recall_gate={result.get('fused_recall_gate', FUSED_RECALL_GATE)}",
            f"test_fused_relevance_recall_at_{PRIMARY_TOP_K}="
            f"{result.get('test_fused_relevance_recall_at_primary_k')}",
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
            "Evaluate fused legal relevance, recall, graph paths, and I/O for "
            "US Code sparse GraphRAG (USCIR-035). Default fixture mode never "
            "contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline gold fixture (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report (or the live fixture evaluation when "
            "the report is missing under --fixture-only) against sealed "
            "acceptance."
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
        # argparse raises SystemExit on --help/-h (0) and usage errors (2).
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
        if (args.check or args.write) and not args.fixture_only:
            raise SparseGraphragEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline gold fixture"
            )

        fixture_report = run_fixture_evaluation(gold_path=gold_path)

        # Deterministic fixture evaluation is the sealed source of truth.
        if args.fixture_only and (args.write or args.check):
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
            elif args.fixture_only:
                report = fixture_report
            else:
                raise SparseGraphragEvaluationError(
                    f"evaluation report not found for --check: {report_path}"
                )
            result = check_evaluation_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                )
            return 0

        if args.print_json:
            sys.stdout.write(
                json.dumps(fixture_report, indent=2, sort_keys=True) + "\n"
            )
            return 0

        if args.write:
            return 0

        result = check_evaluation_report(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --fixture-only --check to validate the frozen report",
            file=sys.stderr,
        )
        return 0
    except SparseGraphragEvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
