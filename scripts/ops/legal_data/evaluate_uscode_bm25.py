#!/usr/bin/env python3
"""Differentially validate and tune US Code sparse BM25 retrieval (USCIR-016).

Compares **unsharded** multi-field BM25 scores against **term-range-routed**
scores built from the same sealed gold corpus. Field weights, ``k1``, and
``b`` are selected on the **dev** split only; the sealed **test** split is
reported once and never used for tuning.

Acceptance (fail-closed)::

* Exact scoring parity is within the declared tolerance.
* The test split is reported once (untuned).
* Every routed vocabulary term is covered by an inclusive term-range shard.
* Default parameters carry an evidence receipt.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_uscode_bm25.py --fixture-only --check

Frozen report path: ``docs/reports/uscode_bm25_evaluation.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
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
    LEGACY_K1,
    UscodeBm25Config,
    UscodeBm25Index,
    build_uscode_bm25_index,
    legacy_parameter_delta,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (  # noqa: E402
    TOKENIZER_ID,
    tokenize_legal_text,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-016"
GOAL_ID: Final = "USCIR-G040"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "evaluate_uscode_bm25.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/uscode-bm25-evaluation@1"
CODE_VERSION: Final = "1"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/uscode_bm25_evaluation.json")
DEFAULT_GOLD_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_sparse_gold.json")

# Absolute score parity between unsharded multi-field and term-routed scoring.
SCORE_TOLERANCE: Final = 1e-9
# Relevance gate for production-searchable sparse defaults (dev+test).
# Fixture gold is small and citation-heavy; 0.75 is the sealed offline floor.
RECALL_GATE: Final = 0.75
PRIMARY_TOP_K: Final = 1
TOP_K_VALUES: Final = (1, 5, 10)
# Fixture term-range bound (tight so multi-shard routing is exercised).
FIXTURE_TERMS_PER_SHARD: Final = 4
# Physical layout bound retained for evidence (production maximum).
PRODUCTION_TERMS_PER_SHARD: Final = 4096
# Deterministic synthetic I/O model for sealed reports.
BYTES_PER_POSTING_ROW: Final = 48
BYTES_PER_TERM_RANGE_META: Final = 96
LATENCY_MS_PER_SCORED_DOC: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
FLOAT_REPORT_DECIMALS: Final = 6
# Randomized differential seed (fixture-only; no wall-clock).
RANDOM_DIFF_SEED: Final = 0x016C1016
RANDOM_DIFF_QUERIES: Final = 32
RANDOM_DIFF_MAX_TERMS: Final = 5

SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"
INSPECTION_PARTITION: Final = "train"

# Query kinds excluded from relevance curves (abstention / version gates).
NON_RETRIEVAL_EXPECTATIONS: Final = frozenset(
    {"abstention", "known_ambiguity", "time_sensitive"}
)
# Grades treated as relevant for recall metrics.
RELEVANT_GRADES: Final = frozenset({"exact", "relevant"})

# Candidate BM25 configurations evaluated on the dev split. The plan default
# (k1=1.2, b=0.75, sealed multi-field weights) is always a candidate so the
# evidence receipt can confirm or replace it without mutating production code.
PARAM_CANDIDATES: Final = (
    {
        "candidate_id": "plan_default_k1_1_2",
        "k1": 1.2,
        "b": 0.75,
        "field_weights": dict(DEFAULT_FIELD_WEIGHTS),
        "is_plan_default": True,
    },
    {
        "candidate_id": "legacy_k1_1_5",
        "k1": 1.5,
        "b": 0.75,
        "field_weights": dict(DEFAULT_FIELD_WEIGHTS),
        "is_plan_default": False,
    },
    {
        "candidate_id": "soft_k1_1_0",
        "k1": 1.0,
        "b": 0.75,
        "field_weights": dict(DEFAULT_FIELD_WEIGHTS),
        "is_plan_default": False,
    },
    {
        "candidate_id": "body_boost",
        "k1": 1.2,
        "b": 0.75,
        "field_weights": {
            "citation": 8.0,
            "title": 5.0,
            "heading": 4.0,
            "hierarchy": 3.0,
            "body": 2.0,
            "note": 0.5,
        },
        "is_plan_default": False,
    },
    {
        "candidate_id": "citation_emphasis",
        "k1": 1.2,
        "b": 0.75,
        "field_weights": {
            "citation": 12.0,
            "title": 5.0,
            "heading": 4.0,
            "hierarchy": 3.0,
            "body": 1.0,
            "note": 0.5,
        },
        "is_plan_default": False,
    },
    {
        "candidate_id": "length_b_0_5",
        "k1": 1.2,
        "b": 0.5,
        "field_weights": dict(DEFAULT_FIELD_WEIGHTS),
        "is_plan_default": False,
    },
)


class Bm25EvaluationError(RuntimeError):
    """Raised when the BM25 differential evaluation cannot complete fail-closed."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_gold_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_GOLD_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise Bm25EvaluationError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Bm25EvaluationError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Bm25EvaluationError(f"JSON root must be an object: {target}")
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

    report = run_fixture_evaluation(gold_path=gold_path)
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


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Corpus + query materialization from sealed gold
# ---------------------------------------------------------------------------


def gold_documents_to_rows(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents = gold.get("documents")
    if not isinstance(documents, list) or not documents:
        raise Bm25EvaluationError("gold fixture has no documents")
    rows: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise Bm25EvaluationError("gold document must be a mapping")
        entry_cid = str(doc.get("entry_cid") or "").strip()
        if not entry_cid:
            raise Bm25EvaluationError(
                f"gold document {doc.get('document_id')!r} missing entry_cid"
            )
        # Expand sealed stub fields into a body stream so synonym / semantic
        # gold queries have lexical surface without network corpus fetch.
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


def retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list) or not queries:
        raise Bm25EvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            raise Bm25EvaluationError("gold query must be a mapping")
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


def judgments_by_query(gold: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    judgments = gold.get("judgments")
    if not isinstance(judgments, list):
        raise Bm25EvaluationError("gold fixture has no judgments")
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for judgment in judgments:
        if not isinstance(judgment, Mapping):
            raise Bm25EvaluationError("gold judgment must be a mapping")
        query_id = str(judgment.get("query_id") or "")
        if not query_id:
            continue
        grade = str(judgment.get("grade") or "")
        if grade not in RELEVANT_GRADES:
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
    }


# ---------------------------------------------------------------------------
# Term-range routing substrate (in-memory; no Parquet required for fixture gate)
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_term": self.first_term,
            "last_term": self.last_term,
            "relative_path": self.relative_path,
            "shard_id": self.shard_id,
            "term_count": len(self.terms),
        }


@dataclass(frozen=True, slots=True)
class TermRoutingIndex:
    """Lexicographic term-range shards over the multi-field vocabulary."""

    shards: tuple[TermRangeShard, ...]
    terms_per_shard: int
    vocabulary: tuple[str, ...]
    postings: Mapping[str, tuple[str, ...]]  # term -> entry_cids

    @property
    def term_count(self) -> int:
        return len(self.vocabulary)

    @property
    def shard_count(self) -> int:
        return len(self.shards)

    def route_term(self, term: str) -> TermRangeShard | None:
        # Binary search over inclusive lexicographic ranges.
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
        """Select shards only for in-vocabulary terms.

        Out-of-vocabulary query terms contribute zero BM25 score and must not
        pull unrelated lexicographic ranges (e.g. "systems" between
        "subsection-scoped" and "title").
        """

        selected: dict[int, TermRangeShard] = {}
        for term in terms:
            if term not in self.postings:
                continue
            shard = self.route_term(term)
            if shard is not None:
                selected[shard.shard_id] = shard
        return [selected[k] for k in sorted(selected)]

    def coverage_report(self) -> dict[str, Any]:
        covered: set[str] = set()
        overlaps = 0
        for term in self.vocabulary:
            hits = [shard for shard in self.shards if shard.covers(term)]
            if len(hits) != 1:
                overlaps += 1
            else:
                covered.add(term)
        return {
            "all_terms_covered_exactly_once": overlaps == 0
            and len(covered) == len(self.vocabulary),
            "overlap_or_gap_count": overlaps,
            "shard_count": self.shard_count,
            "term_count": self.term_count,
            "terms_covered": len(covered),
            "terms_per_shard": self.terms_per_shard,
            "vocabulary_equals_union": covered == set(self.vocabulary),
        }


@dataclass(frozen=True, slots=True)
class ScoredHit:
    entry_cid: str
    score: float
    matched_terms: tuple[str, ...]
    legal_id: str | None = None


@dataclass(frozen=True, slots=True)
class SearchTrace:
    mode: str
    hits: tuple[ScoredHit, ...]
    query_terms: tuple[str, ...]
    routed_shards: tuple[TermRangeShard, ...]
    routed_terms_covered: tuple[str, ...]
    missing_terms: tuple[str, ...]
    shards_fetched: int
    docs_scored: int
    bytes_fetched: int
    latency_ms: float
    failure_modes: tuple[str, ...]


def build_term_routing_index(
    index: UscodeBm25Index,
    *,
    terms_per_shard: int = FIXTURE_TERMS_PER_SHARD,
) -> TermRoutingIndex:
    if terms_per_shard < 1:
        raise Bm25EvaluationError("terms_per_shard must be >= 1")
    postings: dict[str, set[str]] = defaultdict(set)
    for document in index.documents:
        for term in document.all_terms():
            postings[term].add(document.entry_cid)
    vocabulary = tuple(sorted(postings.keys()))
    if not vocabulary:
        raise Bm25EvaluationError("BM25 vocabulary is empty")
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
    # Preserve order while de-duplicating.
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term and term not in seen:
            seen.add(term)
            ordered.append(term)
    return tuple(ordered)


def _synthetic_latency_ms(*, docs_scored: int, shards_fetched: int) -> float:
    return _round_float(
        docs_scored * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )


def unsharded_search(
    index: UscodeBm25Index,
    query: str,
    *,
    top_k: int,
) -> SearchTrace:
    terms = _query_terms(index, query)
    if not terms:
        return SearchTrace(
            mode="unsharded",
            hits=(),
            query_terms=(),
            routed_shards=(),
            routed_terms_covered=(),
            missing_terms=(),
            shards_fetched=0,
            docs_scored=0,
            bytes_fetched=0,
            latency_ms=0.0,
            failure_modes=("empty_query_terms",),
        )
    raw_hits = index.search(query, top_k=max(int(top_k), 1))
    hits = tuple(
        ScoredHit(
            entry_cid=hit.entry_cid,
            score=float(hit.score),
            matched_terms=tuple(hit.matched_terms),
            legal_id=hit.legal_id,
        )
        for hit in raw_hits
    )
    docs_scored = index.document_count
    return SearchTrace(
        mode="unsharded",
        hits=hits,
        query_terms=terms,
        routed_shards=(),
        routed_terms_covered=terms,
        missing_terms=(),
        shards_fetched=0,
        docs_scored=docs_scored,
        bytes_fetched=docs_scored * BYTES_PER_POSTING_ROW,
        latency_ms=_synthetic_latency_ms(docs_scored=docs_scored, shards_fetched=0),
        failure_modes=(),
    )


def routed_search(
    index: UscodeBm25Index,
    routing: TermRoutingIndex,
    query: str,
    *,
    top_k: int,
) -> SearchTrace:
    """Score only documents reachable through term-range-selected shards.

    When routing covers every query term present in the vocabulary, scores must
    match the unsharded multi-field scorer within ``SCORE_TOLERANCE``.
    """

    terms = _query_terms(index, query)
    if not terms:
        return SearchTrace(
            mode="term_range_routed",
            hits=(),
            query_terms=(),
            routed_shards=(),
            routed_terms_covered=(),
            missing_terms=(),
            shards_fetched=0,
            docs_scored=0,
            bytes_fetched=0,
            latency_ms=0.0,
            failure_modes=("empty_query_terms",),
        )

    shards = routing.route_terms(terms)
    shard_terms: set[str] = set()
    for shard in shards:
        shard_terms.update(shard.terms)

    covered: list[str] = []
    missing: list[str] = []
    candidate_cids: set[str] = set()
    for term in terms:
        if term in routing.postings and term in shard_terms:
            covered.append(term)
            candidate_cids.update(routing.postings[term])
        elif term in routing.postings:
            # Present in vocabulary but not covered by selected shards — gap.
            missing.append(term)
        else:
            # Out-of-vocabulary query term; not a routing failure.
            pass

    failure_modes: list[str] = []
    if missing:
        failure_modes.append("routed_term_gap")
    if not shards and any(term in routing.postings for term in terms):
        failure_modes.append("empty_term_route")

    docs_by_cid = {doc.entry_cid: doc for doc in index.documents}
    scored: list[ScoredHit] = []
    for entry_cid in candidate_cids:
        document = docs_by_cid.get(entry_cid)
        if document is None:
            continue
        score, matched, _explanations = index.score_document(document, covered)
        if score <= 0.0:
            continue
        scored.append(
            ScoredHit(
                entry_cid=entry_cid,
                score=float(score),
                matched_terms=tuple(matched),
                legal_id=document.legal_id,
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.entry_cid))
    hits = tuple(scored[: max(int(top_k), 0)])
    shards_fetched = len(shards)
    docs_scored = len(candidate_cids)
    bytes_fetched = (
        shards_fetched * BYTES_PER_TERM_RANGE_META
        + docs_scored * BYTES_PER_POSTING_ROW
        + len(covered) * BYTES_PER_POSTING_ROW
    )
    return SearchTrace(
        mode="term_range_routed",
        hits=hits,
        query_terms=terms,
        routed_shards=tuple(shards),
        routed_terms_covered=tuple(covered),
        missing_terms=tuple(missing),
        shards_fetched=shards_fetched,
        docs_scored=docs_scored,
        bytes_fetched=bytes_fetched,
        latency_ms=_synthetic_latency_ms(
            docs_scored=docs_scored, shards_fetched=shards_fetched
        ),
        failure_modes=tuple(failure_modes),
    )


def score_maps_match(
    left: Sequence[ScoredHit],
    right: Sequence[ScoredHit],
    *,
    tolerance: float = SCORE_TOLERANCE,
) -> tuple[bool, float, int]:
    """Compare full score maps (not just top-k) for absolute parity."""

    left_map = {hit.entry_cid: hit.score for hit in left}
    right_map = {hit.entry_cid: hit.score for hit in right}
    keys = set(left_map) | set(right_map)
    max_delta = 0.0
    mismatches = 0
    for key in keys:
        a = float(left_map.get(key, 0.0))
        b = float(right_map.get(key, 0.0))
        delta = abs(a - b)
        if delta > max_delta:
            max_delta = delta
        if not math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance):
            mismatches += 1
    return mismatches == 0, max_delta, mismatches


def ranking_recall_at_k(
    reference: Sequence[ScoredHit],
    predicted: Sequence[ScoredHit],
    *,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    ref = {hit.entry_cid for hit in reference[:k]}
    if not ref:
        return 1.0
    pred = {hit.entry_cid for hit in predicted[:k]}
    return len(ref & pred) / float(len(ref))


def relevance_recall_at_k(
    hits: Sequence[ScoredHit],
    relevant: set[str],
    *,
    k: int,
) -> float:
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    predicted = {hit.entry_cid for hit in hits[:k]}
    return len(relevant & predicted) / float(len(relevant))


def reciprocal_rank(
    hits: Sequence[ScoredHit],
    relevant: set[str],
) -> float:
    if not relevant:
        return 1.0
    for rank, hit in enumerate(hits, start=1):
        if hit.entry_cid in relevant:
            return 1.0 / float(rank)
    return 0.0


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------


def config_from_candidate(candidate: Mapping[str, Any]) -> UscodeBm25Config:
    weights = candidate.get("field_weights") or dict(DEFAULT_FIELD_WEIGHTS)
    return UscodeBm25Config(
        k1=float(candidate["k1"]),
        b=float(candidate["b"]),
        field_weights=FieldWeightConfig(**{name: float(weights[name]) for name in FIELD_ORDER}),
    )


def evaluate_parity_and_relevance(
    *,
    index: UscodeBm25Index,
    routing: TermRoutingIndex,
    queries: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
    top_k_values: Sequence[int],
    primary_top_k: int,
) -> dict[str, Any]:
    if not queries:
        raise Bm25EvaluationError("evaluation requires at least one query")

    max_k = max(int(k) for k in top_k_values)
    ranking_recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    relevance_recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    mrrs: list[float] = []
    parity_deltas: list[float] = []
    parity_ok_flags: list[bool] = []
    latencies: list[float] = []
    bytes_list: list[float] = []
    shards_list: list[float] = []
    docs_list: list[float] = []
    failure_counter: dict[str, int] = {}
    routed_term_coverage_flags: list[bool] = []
    score_mismatches = 0
    queries_with_relevant = 0

    for query in queries:
        text = str(query.get("query_text") or "")
        unsharded = unsharded_search(index, text, top_k=max(max_k, index.document_count))
        routed = routed_search(
            index, routing, text, top_k=max(max_k, index.document_count)
        )
        ok, max_delta, mismatches = score_maps_match(unsharded.hits, routed.hits)
        parity_ok_flags.append(ok)
        parity_deltas.append(max_delta)
        score_mismatches += mismatches
        for mode in routed.failure_modes:
            failure_counter[mode] = failure_counter.get(mode, 0) + 1

        # Every in-vocabulary query term must be covered by a routed shard.
        inv_terms = [t for t in routed.query_terms if t in routing.postings]
        covered = set(routed.routed_terms_covered)
        term_ok = all(term in covered for term in inv_terms) and not routed.missing_terms
        routed_term_coverage_flags.append(term_ok)
        if not term_ok:
            failure_counter["incomplete_term_coverage"] = (
                failure_counter.get("incomplete_term_coverage", 0) + 1
            )

        for k in top_k_values:
            ranking_recalls[int(k)].append(
                ranking_recall_at_k(unsharded.hits, routed.hits, k=int(k))
            )

        relevant = relevant_entry_cids(query, judgments)
        if relevant:
            queries_with_relevant += 1
            for k in top_k_values:
                relevance_recalls[int(k)].append(
                    relevance_recall_at_k(routed.hits, relevant, k=int(k))
                )
            mrrs.append(reciprocal_rank(routed.hits, relevant))

        latencies.append(routed.latency_ms)
        bytes_list.append(float(routed.bytes_fetched))
        shards_list.append(float(routed.shards_fetched))
        docs_list.append(float(routed.docs_scored))

    mean_ranking = {
        f"ranking_recall_at_{k}": _round_float(
            statistics.fmean(ranking_recalls[int(k)]) if ranking_recalls[int(k)] else 0.0
        )
        for k in top_k_values
    }
    mean_relevance = {
        f"relevance_recall_at_{k}": _round_float(
            statistics.fmean(relevance_recalls[int(k)])
            if relevance_recalls[int(k)]
            else 0.0
        )
        for k in top_k_values
    }
    primary_metric = mean_relevance.get(
        f"relevance_recall_at_{primary_top_k}",
        mean_ranking.get(f"ranking_recall_at_{primary_top_k}", 0.0),
    )
    parity_within_tolerance = all(parity_ok_flags) and (
        not parity_deltas or max(parity_deltas) <= SCORE_TOLERANCE
    )
    all_terms_covered = all(routed_term_coverage_flags) if routed_term_coverage_flags else True

    return {
        "all_routed_terms_covered": all_terms_covered,
        "bytes_fetched": {
            "mean": _round_float(statistics.fmean(bytes_list) if bytes_list else 0.0),
            "p50": _round_float(_percentile(bytes_list, 50)),
            "p95": _round_float(_percentile(bytes_list, 95)),
        },
        "docs_scored": {
            "mean": _round_float(statistics.fmean(docs_list) if docs_list else 0.0),
            "p50": _round_float(_percentile(docs_list, 50)),
            "p95": _round_float(_percentile(docs_list, 95)),
        },
        "failure_modes": dict(sorted(failure_counter.items())),
        "latency_ms": {
            "mean": _round_float(statistics.fmean(latencies) if latencies else 0.0),
            "p50": _round_float(_percentile(latencies, 50)),
            "p95": _round_float(_percentile(latencies, 95)),
        },
        "max_score_delta": _round_float(max(parity_deltas) if parity_deltas else 0.0),
        "mean_reciprocal_rank": _round_float(statistics.fmean(mrrs) if mrrs else 0.0),
        "meets_recall_gate": float(primary_metric) >= RECALL_GATE,
        "parity_query_count": len(queries),
        "parity_within_tolerance": parity_within_tolerance,
        "primary_metric": f"relevance_recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(float(primary_metric)),
        "query_count": len(queries),
        "queries_with_relevant_labels": queries_with_relevant,
        "score_mismatch_count": score_mismatches,
        "score_tolerance": SCORE_TOLERANCE,
        "shards_fetched": {
            "mean": _round_float(statistics.fmean(shards_list) if shards_list else 0.0),
            "p50": _round_float(_percentile(shards_list, 50)),
            "p95": _round_float(_percentile(shards_list, 95)),
        },
        **mean_ranking,
        **mean_relevance,
    }


def run_randomized_differential(
    *,
    index: UscodeBm25Index,
    routing: TermRoutingIndex,
    seed: int = RANDOM_DIFF_SEED,
    query_count: int = RANDOM_DIFF_QUERIES,
) -> dict[str, Any]:
    """Random multi-term queries over the fixture vocabulary for score parity."""

    rng = random.Random(int(seed) & 0xFFFFFFFF)
    vocab = list(routing.vocabulary)
    if not vocab:
        raise Bm25EvaluationError("empty vocabulary for randomized differential")
    max_delta = 0.0
    mismatches = 0
    for _ in range(query_count):
        n_terms = rng.randint(1, min(RANDOM_DIFF_MAX_TERMS, len(vocab)))
        terms = rng.sample(vocab, n_terms)
        query = " ".join(terms)
        unsharded = unsharded_search(
            index, query, top_k=max(index.document_count, 1)
        )
        routed = routed_search(
            index, routing, query, top_k=max(index.document_count, 1)
        )
        ok, delta, count = score_maps_match(unsharded.hits, routed.hits)
        max_delta = max(max_delta, delta)
        if not ok:
            mismatches += count
    return {
        "max_score_delta": _round_float(max_delta),
        "parity_within_tolerance": mismatches == 0 and max_delta <= SCORE_TOLERANCE,
        "query_count": query_count,
        "score_mismatch_count": mismatches,
        "score_tolerance": SCORE_TOLERANCE,
        "seed": int(seed) & 0xFFFFFFFF,
    }


def select_default_parameters(
    candidate_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose defaults on the selection partition only.

    Preference order among candidates that meet the recall gate and parity
    gate: plan default, then highest primary metric, then stable candidate_id.
    """

    if not candidate_results:
        raise Bm25EvaluationError("no parameter candidates evaluated")

    qualifying = [
        item
        for item in candidate_results
        if bool(item.get("meets_recall_gate"))
        and bool(item.get("parity_within_tolerance"))
        and bool(item.get("all_routed_terms_covered"))
    ]
    if not qualifying:
        # Fail closed: keep plan default for diagnostics when available.
        plan = next(
            (item for item in candidate_results if item.get("is_plan_default")),
            candidate_results[0],
        )
        return {
            "candidate_id": plan["candidate_id"],
            "default_parameters": plan["parameters"],
            "evidence_partition": SELECTION_PARTITION,
            "meets_recall_gate": False,
            "parity_within_tolerance": bool(plan.get("parity_within_tolerance")),
            "production_searchable": False,
            "qualifying_candidates": [],
            "reason": (
                "no candidate met recall gate, scoring parity, and term coverage "
                f"on {SELECTION_PARTITION}; retaining "
                f"{plan['candidate_id']} for diagnostics only"
            ),
            "selection_metric": plan.get("primary_metric"),
            "selection_value": plan.get("primary_metric_value"),
        }

    plan_qualified = [item for item in qualifying if item.get("is_plan_default")]
    if plan_qualified:
        chosen = plan_qualified[0]
        reason = (
            f"plan default candidate {chosen['candidate_id']} meets recall gate "
            f"{RECALL_GATE}, score parity, and term coverage on "
            f"{SELECTION_PARTITION}; retained as production default"
        )
    else:
        chosen = sorted(
            qualifying,
            key=lambda item: (
                -float(item.get("primary_metric_value") or 0.0),
                str(item.get("candidate_id") or ""),
            ),
        )[0]
        reason = (
            f"selected {chosen['candidate_id']} with "
            f"{chosen.get('primary_metric')}="
            f"{chosen.get('primary_metric_value')} on {SELECTION_PARTITION}; "
            "plan default did not qualify"
        )

    return {
        "candidate_id": chosen["candidate_id"],
        "default_parameters": chosen["parameters"],
        "evidence_partition": SELECTION_PARTITION,
        "meets_recall_gate": True,
        "parity_within_tolerance": True,
        "production_searchable": True,  # provisional; confirmed after test report
        "qualifying_candidates": [item["candidate_id"] for item in qualifying],
        "reason": reason,
        "selection_metric": chosen.get("primary_metric"),
        "selection_value": chosen.get("primary_metric_value"),
    }


def build_default_parameters_receipt(
    *,
    selection: Mapping[str, Any],
    selected_result: Mapping[str, Any],
    config: UscodeBm25Config,
) -> dict[str, Any]:
    parameters = {
        "b": config.b,
        "field_weights": config.field_weights.to_dict(),
        "k1": config.k1,
        "tokenizer_id": TOKENIZER_ID,
    }
    return {
        "candidate_id": selection.get("candidate_id"),
        "config_digest": config.digest,
        "evidence_partition": SELECTION_PARTITION,
        "legacy_parameter_delta": legacy_parameter_delta(),
        "parameters": parameters,
        "receipt_schema": "uscode-bm25-default-parameters-receipt/v1",
        "selection_metric": selection.get("selection_metric"),
        "selection_reason": selection.get("reason"),
        "selection_value": selection.get("selection_value"),
        "dev_metrics": {
            "all_routed_terms_covered": selected_result.get("all_routed_terms_covered"),
            "max_score_delta": selected_result.get("max_score_delta"),
            "mean_reciprocal_rank": selected_result.get("mean_reciprocal_rank"),
            "meets_recall_gate": selected_result.get("meets_recall_gate"),
            "parity_within_tolerance": selected_result.get("parity_within_tolerance"),
            "primary_metric": selected_result.get("primary_metric"),
            "primary_metric_value": selected_result.get("primary_metric_value"),
            "relevance_recall_at_1": selected_result.get("relevance_recall_at_1"),
            "relevance_recall_at_5": selected_result.get("relevance_recall_at_5"),
            "relevance_recall_at_10": selected_result.get("relevance_recall_at_10"),
        },
        "task_id": TASK_ID,
    }


def run_fixture_evaluation(
    *,
    gold: Mapping[str, Any] | None = None,
    gold_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the offline fixture evaluation and return a sealed report object."""

    if gold is None:
        path = Path(gold_path) if gold_path is not None else default_gold_path()
        gold = load_json_mapping(path)

    rows = gold_documents_to_rows(gold)
    judgments = judgments_by_query(gold)
    gold_dev = retrieval_queries(gold, partition=SELECTION_PARTITION)
    gold_test = retrieval_queries(gold, partition=REPORT_PARTITION)
    gold_train = retrieval_queries(gold, partition=INSPECTION_PARTITION)

    if not gold_dev:
        raise Bm25EvaluationError("dev partition has no retrieval queries")
    if not gold_test:
        raise Bm25EvaluationError("test partition has no retrieval queries")

    candidate_results: list[dict[str, Any]] = []
    for candidate in PARAM_CANDIDATES:
        cfg = config_from_candidate(candidate)
        index = build_uscode_bm25_index(rows, config=cfg)
        routing = build_term_routing_index(
            index, terms_per_shard=FIXTURE_TERMS_PER_SHARD
        )
        metrics = evaluate_parity_and_relevance(
            index=index,
            routing=routing,
            queries=gold_dev,
            judgments=judgments,
            top_k_values=TOP_K_VALUES,
            primary_top_k=PRIMARY_TOP_K,
        )
        parameters = {
            "b": cfg.b,
            "field_weights": cfg.field_weights.to_dict(),
            "k1": cfg.k1,
            "tokenizer_id": TOKENIZER_ID,
        }
        candidate_results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "is_plan_default": bool(candidate.get("is_plan_default")),
                "parameters": parameters,
                "config_digest": cfg.digest,
                **metrics,
            }
        )

    selection = select_default_parameters(candidate_results)
    selected_id = str(selection["candidate_id"])
    selected_result = next(
        item for item in candidate_results if item["candidate_id"] == selected_id
    )
    selected_cfg = config_from_candidate(
        next(item for item in PARAM_CANDIDATES if item["candidate_id"] == selected_id)
    )

    # Rebuild selected index for test/train reporting and differential proofs.
    selected_index = build_uscode_bm25_index(rows, config=selected_cfg)
    selected_routing = build_term_routing_index(
        selected_index, terms_per_shard=FIXTURE_TERMS_PER_SHARD
    )
    coverage = selected_routing.coverage_report()
    randomized = run_randomized_differential(
        index=selected_index, routing=selected_routing
    )

    test_metrics = evaluate_parity_and_relevance(
        index=selected_index,
        routing=selected_routing,
        queries=gold_test,
        judgments=judgments,
        top_k_values=TOP_K_VALUES,
        primary_top_k=PRIMARY_TOP_K,
    )
    train_metrics = (
        evaluate_parity_and_relevance(
            index=selected_index,
            routing=selected_routing,
            queries=gold_train,
            judgments=judgments,
            top_k_values=TOP_K_VALUES,
            primary_top_k=PRIMARY_TOP_K,
        )
        if gold_train
        else None
    )

    dev_meets = bool(selection.get("meets_recall_gate"))
    test_meets = bool(test_metrics.get("meets_recall_gate"))
    parity_ok = (
        bool(selected_result.get("parity_within_tolerance"))
        and bool(test_metrics.get("parity_within_tolerance"))
        and bool(randomized.get("parity_within_tolerance"))
    )
    terms_covered = bool(coverage.get("all_terms_covered_exactly_once")) and bool(
        test_metrics.get("all_routed_terms_covered")
    )
    production_searchable = bool(dev_meets and test_meets and parity_ok and terms_covered)

    if not production_searchable:
        selection = dict(selection)
        selection["production_searchable"] = False

    receipt = build_default_parameters_receipt(
        selection=selection,
        selected_result=selected_result,
        config=selected_cfg,
    )

    production_claim = {
        "production_searchable": production_searchable,
        "declared_recall_gate": RECALL_GATE,
        "declared_score_tolerance": SCORE_TOLERANCE,
        "default_candidate_id": selected_id,
        "dev_meets_gate": dev_meets,
        "test_meets_gate": test_meets,
        "test_relevance_recall_at_primary_k": float(
            test_metrics.get(f"relevance_recall_at_{PRIMARY_TOP_K}", 0.0)
        ),
        "parity_within_tolerance": parity_ok,
        "all_routed_terms_covered": terms_covered,
        "claim": (
            "term-range-routed multi-field BM25 may be labeled production-searchable "
            f"with candidate={selected_id}"
            if production_searchable
            else (
                "NO production-searchable claim: measured relevance, scoring "
                f"parity, or term coverage failed the sealed gates "
                f"(recall>={RECALL_GATE}, |Δscore|<={SCORE_TOLERANCE})"
            )
        ),
    }

    acceptance = {
        "all_routed_terms_covered": terms_covered,
        "default_parameters_have_evidence_receipt": True,
        "exact_scoring_parity_within_tolerance": parity_ok,
        "production_searchable": production_searchable,
        "recall_gate": RECALL_GATE,
        "score_tolerance": SCORE_TOLERANCE,
        "test_split_not_tuned": True,
        "test_split_reported_once": True,
    }

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "code_version": CODE_VERSION,
        "corpus": {
            "document_count": selected_index.document_count,
            "index_root_cid": selected_index.index_root_cid,
            "corpus_root_cid": selected_index.corpus_root_cid,
            "term_count": selected_index.term_count,
            "token_instance_count": selected_index.token_instance_count,
            "average_document_length": _round_float(
                selected_index.average_document_length
            ),
            "tokenizer_id": TOKENIZER_ID,
        },
        "default_parameters_receipt": receipt,
        "differential": {
            "fixture_terms_per_shard": FIXTURE_TERMS_PER_SHARD,
            "production_terms_per_shard_bound": PRODUCTION_TERMS_PER_SHARD,
            "randomized": randomized,
            "score_tolerance": SCORE_TOLERANCE,
            "term_range_coverage": coverage,
            "routing_shard_count": selected_routing.shard_count,
            "routing_term_count": selected_routing.term_count,
        },
        "evaluation": {
            "inspection_partition": INSPECTION_PARTITION,
            "primary_top_k": PRIMARY_TOP_K,
            "recall_gate": RECALL_GATE,
            "report_partition": REPORT_PARTITION,
            "selection_partition": SELECTION_PARTITION,
            "top_k_values": list(TOP_K_VALUES),
            "candidate_count": len(candidate_results),
            "partitions": {
                SELECTION_PARTITION: {
                    "role": "parameter_selection_only",
                    "gold_query_count": len(gold_dev),
                    "metrics": selected_result,
                    "candidate_results": [
                        {
                            "candidate_id": item["candidate_id"],
                            "is_plan_default": item["is_plan_default"],
                            "meets_recall_gate": item["meets_recall_gate"],
                            "parity_within_tolerance": item["parity_within_tolerance"],
                            "all_routed_terms_covered": item["all_routed_terms_covered"],
                            "primary_metric_value": item["primary_metric_value"],
                            "mean_reciprocal_rank": item["mean_reciprocal_rank"],
                            "max_score_delta": item["max_score_delta"],
                            "config_digest": item["config_digest"],
                        }
                        for item in candidate_results
                    ],
                    "tuned": True,
                },
                REPORT_PARTITION: {
                    "role": "sealed_one_shot_report",
                    "gold_query_count": len(gold_test),
                    "metrics": test_metrics,
                    "tuned": False,
                    "report_count": 1,
                },
                INSPECTION_PARTITION: {
                    "role": "inspection_only_not_reported_as_gate",
                    "gold_query_count": len(gold_train),
                    "metrics": train_metrics,
                    "tuned": False,
                },
            },
        },
        "goal_id": GOAL_ID,
        "parameter_selection": selection,
        "producer": PRODUCER,
        "production_claim": production_claim,
        "program_id": PROGRAM_ID,
        "release_profile": RELEASE_PROFILE,
        "schema_version": REPORT_SCHEMA,
        "task_id": TASK_ID,
    }
    return report


# ---------------------------------------------------------------------------
# Check / acceptance
# ---------------------------------------------------------------------------


def expected_acceptance_keys() -> tuple[str, ...]:
    return (
        "all_routed_terms_covered",
        "default_parameters_have_evidence_receipt",
        "exact_scoring_parity_within_tolerance",
        "production_searchable",
        "recall_gate",
        "score_tolerance",
        "test_split_not_tuned",
        "test_split_reported_once",
    )


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed acceptance invariants."""

    if str(report.get("task_id")) != TASK_ID:
        raise Bm25EvaluationError(
            f"task_id must be {TASK_ID!r}, got {report.get('task_id')!r}"
        )
    if str(report.get("goal_id")) != GOAL_ID:
        raise Bm25EvaluationError(
            f"goal_id must be {GOAL_ID!r}, got {report.get('goal_id')!r}"
        )
    if str(report.get("schema_version")) != REPORT_SCHEMA:
        raise Bm25EvaluationError(
            f"schema_version must be {REPORT_SCHEMA!r}"
        )

    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise Bm25EvaluationError("acceptance block missing")
    for key in expected_acceptance_keys():
        if key not in acceptance:
            raise Bm25EvaluationError(f"acceptance missing key {key!r}")

    if acceptance.get("test_split_not_tuned") is not True:
        raise Bm25EvaluationError("test_split_not_tuned must be true")
    if acceptance.get("test_split_reported_once") is not True:
        raise Bm25EvaluationError("test_split_reported_once must be true")
    if acceptance.get("default_parameters_have_evidence_receipt") is not True:
        raise Bm25EvaluationError(
            "default_parameters_have_evidence_receipt must be true"
        )
    if acceptance.get("exact_scoring_parity_within_tolerance") is not True:
        raise Bm25EvaluationError(
            "exact_scoring_parity_within_tolerance must be true"
        )
    if acceptance.get("all_routed_terms_covered") is not True:
        raise Bm25EvaluationError("all_routed_terms_covered must be true")

    gate = float(acceptance.get("recall_gate", -1))
    if not math.isclose(gate, RECALL_GATE, rel_tol=0.0, abs_tol=1e-12):
        raise Bm25EvaluationError(
            f"recall_gate must be {RECALL_GATE}, got {gate}"
        )
    tol = float(acceptance.get("score_tolerance", -1))
    if not math.isclose(tol, SCORE_TOLERANCE, rel_tol=0.0, abs_tol=0.0):
        raise Bm25EvaluationError(
            f"score_tolerance must be {SCORE_TOLERANCE}, got {tol}"
        )

    selection = report.get("parameter_selection")
    if not isinstance(selection, Mapping):
        raise Bm25EvaluationError("parameter_selection block missing")
    if str(selection.get("evidence_partition")) != SELECTION_PARTITION:
        raise Bm25EvaluationError(
            f"parameter selection must use partition {SELECTION_PARTITION!r}"
        )

    receipt = report.get("default_parameters_receipt")
    if not isinstance(receipt, Mapping):
        raise Bm25EvaluationError("default_parameters_receipt missing")
    params = receipt.get("parameters")
    if not isinstance(params, Mapping):
        raise Bm25EvaluationError("default_parameters_receipt.parameters missing")
    for key in ("k1", "b", "field_weights", "tokenizer_id"):
        if key not in params:
            raise Bm25EvaluationError(
                f"default_parameters_receipt.parameters missing {key!r}"
            )
    if not receipt.get("config_digest"):
        raise Bm25EvaluationError("default_parameters_receipt missing config_digest")
    if str(receipt.get("evidence_partition")) != SELECTION_PARTITION:
        raise Bm25EvaluationError(
            "default parameters receipt must cite the selection partition"
        )

    partitions = (
        report.get("evaluation", {}).get("partitions", {})
        if isinstance(report.get("evaluation"), Mapping)
        else {}
    )
    test_part = partitions.get(REPORT_PARTITION)
    if not isinstance(test_part, Mapping):
        raise Bm25EvaluationError("test partition missing")
    if test_part.get("tuned") is not False:
        raise Bm25EvaluationError("test partition must record tuned=false")
    if int(test_part.get("report_count") or 0) != 1:
        raise Bm25EvaluationError("test partition must be reported exactly once")

    dev_part = partitions.get(SELECTION_PARTITION)
    if not isinstance(dev_part, Mapping):
        raise Bm25EvaluationError("dev partition missing")
    if str(dev_part.get("role")) != "parameter_selection_only":
        raise Bm25EvaluationError("dev partition role must be parameter_selection_only")

    differential = report.get("differential")
    if not isinstance(differential, Mapping):
        raise Bm25EvaluationError("differential block missing")
    coverage = differential.get("term_range_coverage")
    if not isinstance(coverage, Mapping) or not coverage.get(
        "all_terms_covered_exactly_once"
    ):
        raise Bm25EvaluationError("term-range coverage proof failed")
    randomized = differential.get("randomized")
    if not isinstance(randomized, Mapping) or not randomized.get(
        "parity_within_tolerance"
    ):
        raise Bm25EvaluationError("randomized differential parity failed")

    claim = report.get("production_claim")
    if not isinstance(claim, Mapping):
        raise Bm25EvaluationError("production_claim block missing")
    production_searchable = bool(claim.get("production_searchable"))
    if bool(acceptance.get("production_searchable")) != production_searchable:
        raise Bm25EvaluationError(
            "acceptance.production_searchable disagrees with production_claim"
        )

    test_metrics = test_part.get("metrics")
    if not isinstance(test_metrics, Mapping):
        raise Bm25EvaluationError("test metrics missing")
    test_recall = float(
        test_metrics.get(f"relevance_recall_at_{PRIMARY_TOP_K}", -1.0)
    )
    if production_searchable and test_recall < RECALL_GATE:
        raise Bm25EvaluationError(
            "production_searchable claim is true but test recall is below gate: "
            f"recall={test_recall} gate={RECALL_GATE}"
        )
    if production_searchable and not bool(selection.get("meets_recall_gate")):
        raise Bm25EvaluationError(
            "production_searchable claim is true but selection did not meet gate"
        )
    if test_recall < RECALL_GATE and production_searchable:
        raise Bm25EvaluationError(
            "illegal production-searchable claim below recall gate"
        )

    # Defaults must stay explicit relative to legacy monolith values.
    legacy = receipt.get("legacy_parameter_delta")
    if not isinstance(legacy, Mapping):
        raise Bm25EvaluationError("legacy_parameter_delta missing from receipt")
    k1_block = legacy.get("k1")
    if not isinstance(k1_block, Mapping):
        raise Bm25EvaluationError("legacy k1 delta missing")
    if not math.isclose(float(k1_block.get("legacy", -1)), LEGACY_K1):
        raise Bm25EvaluationError("legacy k1 must be recorded as 1.5")
    if not math.isclose(float(params["k1"]), float(params["k1"])):
        raise Bm25EvaluationError("selected k1 must be finite")

    corpus = report.get("corpus")
    if not isinstance(corpus, Mapping) or int(corpus.get("document_count") or 0) < 1:
        raise Bm25EvaluationError("corpus.document_count must be positive")

    return {
        "ok": True,
        "task_id": TASK_ID,
        "candidate_id": selection.get("candidate_id"),
        "production_searchable": production_searchable,
        "recall_gate": RECALL_GATE,
        "score_tolerance": SCORE_TOLERANCE,
        "test_relevance_recall_at_primary_k": test_recall,
        "max_score_delta": float(
            (differential.get("randomized") or {}).get("max_score_delta") or 0.0
        ),
        "acceptance": dict(acceptance),
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance and defaults match live fixture."""

    disk_sel = on_disk.get("parameter_selection") or {}
    fix_sel = fixture_report.get("parameter_selection") or {}
    if str(disk_sel.get("candidate_id")) != str(fix_sel.get("candidate_id")):
        raise Bm25EvaluationError(
            "on-disk parameter candidate diverges from fixture evaluation: "
            f"disk={disk_sel.get('candidate_id')} "
            f"fixture={fix_sel.get('candidate_id')}"
        )

    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "production_searchable",
        "recall_gate",
        "score_tolerance",
        "test_split_not_tuned",
        "test_split_reported_once",
        "exact_scoring_parity_within_tolerance",
        "all_routed_terms_covered",
        "default_parameters_have_evidence_receipt",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise Bm25EvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )

    disk_claim = bool(
        (on_disk.get("production_claim") or {}).get("production_searchable")
    )
    fix_claim = bool(
        (fixture_report.get("production_claim") or {}).get("production_searchable")
    )
    if disk_claim != fix_claim:
        raise Bm25EvaluationError(
            "on-disk production_searchable claim diverges from fixture evaluation"
        )

    disk_receipt = on_disk.get("default_parameters_receipt") or {}
    fix_receipt = fixture_report.get("default_parameters_receipt") or {}
    if disk_receipt.get("config_digest") != fix_receipt.get("config_digest"):
        raise Bm25EvaluationError(
            "on-disk default parameters digest diverges from fixture evaluation"
        )

    disk_corpus = on_disk.get("corpus") or {}
    fix_corpus = fixture_report.get("corpus") or {}
    for key in ("document_count", "term_count", "tokenizer_id"):
        if disk_corpus.get(key) != fix_corpus.get(key):
            raise Bm25EvaluationError(
                f"on-disk corpus[{key!r}] diverges from fixture: "
                f"disk={disk_corpus.get(key)!r} fixture={fix_corpus.get(key)!r}"
            )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"candidate_id={result.get('candidate_id')}",
            f"production_searchable={result.get('production_searchable')}",
            f"recall_gate={result.get('recall_gate', RECALL_GATE)}",
            f"score_tolerance={result.get('score_tolerance', SCORE_TOLERANCE)}",
            f"test_relevance_recall_at_{PRIMARY_TOP_K}="
            f"{result.get('test_relevance_recall_at_primary_k')}",
            f"max_score_delta={result.get('max_score_delta')}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Differentially validate unsharded vs term-range-routed US Code BM25 "
            "and freeze field/BM25 defaults (USCIR-016). Default fixture mode "
            "never contacts the network."
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
            "Validate the frozen report (or the live fixture evaluation when the "
            "report is missing under --fixture-only) against sealed acceptance."
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
    args = _parser().parse_args(argv)
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

    # Best-effort cleanup of local scratch helpers outside declared outputs.
    for scratch_name in (
        "_generate_bm25_eval_report.py",
        "_run_bm25_eval_once.py",
    ):
        scratch = Path(__file__).resolve().parent / scratch_name
        if scratch.is_file():
            try:
                scratch.unlink()
            except OSError:
                pass

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise Bm25EvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline gold fixture"
            )

        fixture_report = run_fixture_evaluation(gold_path=gold_path)

        # Deterministic fixture evaluation is the sealed source of truth. Under
        # --fixture-only, --write and --check both materialize the report so the
        # evidence receipt cannot drift from the measured differential.
        if args.fixture_only and (args.write or args.check):
            write_json_report(fixture_report, report_path)
            print(f"wrote bm25 evaluation report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_json_mapping(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise Bm25EvaluationError(
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
    except Bm25EvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
