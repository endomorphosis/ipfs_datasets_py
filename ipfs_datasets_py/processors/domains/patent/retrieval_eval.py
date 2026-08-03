"""Patent retrieval evaluation harness (PATLAW-093).

Concrete I/O layer over :mod:`evaluation` contracts and hybrid retrieval:

* load versioned qrels / thresholds fixtures;
* measure each retrieval family and fused ranking for recall, ranking
  (nDCG), exact citation grounding, effective-time accuracy, source
  coverage, reproducibility, latency envelope, and private isolation;
* emit evaluation receipts that bind corpus / index / model / config /
  qrels CIDs;
* enumerate source and temporal errors; and
* record denied provider-call counts on isolation metrics and receipts.

Versioned thresholds fail loudly (:class:`MetricThresholdError`) on
regression. No network I/O lives here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .evaluation import (
    EVALUATION_SCHEMA_VERSION,
    REQUIRED_METRIC_KINDS,
    EvaluationError,
    EvaluationReceipt,
    MetricKind,
    MetricScore,
    MetricThresholdError,
    MetricThresholds,
    Qrel,
    QrelSet,
    RelevanceGrade,
    assert_thresholds,
    build_evaluation_receipt,
    canonical_json,
    compute_citation_grounding,
    compute_ndcg_at_k,
    compute_private_isolation,
    compute_recall_at_k,
    compute_source_coverage,
    compute_temporal_accuracy,
    evaluate_ranking,
)
from .hybrid_retrieval import (
    HybridSearchRequest,
    HybridSearchResult,
    PatentHybridRetriever,
    hybrid_search,
)
from .indexing import (
    PatentIndexBundle,
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    FusionWeights,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    require_pre_ranking_filters,
)

RETRIEVAL_EVAL_SCHEMA_VERSION: Final = "patent.retrieval.eval.v1"
RETRIEVAL_EVAL_INTERFACE: Final = "PatentRetrievalEvaluator@1"
FIXTURE_SCHEMA_VERSION: Final = "patent.retrieval.eval.fixture.v1"

DEFAULT_QRELS_CID: Final = (
    "bafybeiqrelsidentity000000000000000000000000000000000000002"
)
DEFAULT_THRESHOLDS_CID: Final = (
    "bafybeithresholds00000000000000000000000000000000000000003"
)

# Local hashed embeddings + three-way fusion should finish well under this
# envelope on CI; the bound is intentionally generous but still finite.
DEFAULT_LATENCY_MAX_MS: Final = 30_000.0

_FAMILY_ATTR: Final[Mapping[RetrievalFamily, str]] = MappingProxyType(
    {
        RetrievalFamily.BM25: "bm25_hits",
        RetrievalFamily.VECTOR: "vector_hits",
        RetrievalFamily.GRAPH: "graph_hits",
        RetrievalFamily.FUSION: "fused_hits",
    }
)


class RetrievalEvalError(EvaluationError):
    """Base error for the retrieval evaluation harness."""


class LatencyEnvelopeError(RetrievalEvalError):
    """Raised when measured latency exceeds the versioned envelope."""


class ReproducibilityError(RetrievalEvalError):
    """Raised when two identical evaluation runs diverge."""


@dataclass(frozen=True, slots=True)
class LatencyMeasurement:
    """One latency sample against a versioned maximum envelope."""

    elapsed_ms: float
    max_ms: float
    label: str = "search"

    def __post_init__(self) -> None:
        object.__setattr__(self, "elapsed_ms", float(self.elapsed_ms))
        object.__setattr__(self, "max_ms", float(self.max_ms))
        if self.elapsed_ms < 0.0:
            raise ValueError("elapsed_ms must be non-negative")
        if self.max_ms <= 0.0:
            raise ValueError("max_ms must be positive")
        object.__setattr__(self, "label", str(self.label or "search"))

    @property
    def passed(self) -> bool:
        return self.elapsed_ms <= self.max_ms + 1e-9

    def to_dict(self) -> dict[str, Any]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "label": self.label,
            "max_ms": self.max_ms,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class FamilyEvaluation:
    """Metrics + enumerated errors for one retrieval family ranking."""

    family: RetrievalFamily
    metrics: tuple[MetricScore, ...]
    source_errors: tuple[str, ...]
    temporal_errors: tuple[str, ...]
    citation_errors: tuple[str, ...]
    hit_document_ids: tuple[str, ...]
    ranking_digest: str
    denied_provider_call_count: int
    receipt: EvaluationReceipt | None = None
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_errors": list(self.citation_errors),
            "denied_provider_call_count": self.denied_provider_call_count,
            "family": self.family.value,
            "hit_document_ids": list(self.hit_document_ids),
            "metrics": [m.to_dict() for m in self.metrics],
            "passed": self.passed,
            "ranking_digest": self.ranking_digest,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "source_errors": list(self.source_errors),
            "temporal_errors": list(self.temporal_errors),
        }


@dataclass(frozen=True, slots=True)
class QueryEvaluationResult:
    """Per-query multi-family evaluation with latency and reproducibility."""

    schema_version: str
    query_id: str
    query: str
    family_results: Mapping[str, FamilyEvaluation]
    fused: FamilyEvaluation
    latency: LatencyMeasurement
    reproducibility_digest: str
    reproducible: bool
    denied_provider_call_count: int
    remote_embedding_calls: int
    binding_cids: Mapping[str, str]
    index_cids: Mapping[str, str]
    passed: bool
    metadata: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_cids": dict(self.binding_cids),
            "denied_provider_call_count": self.denied_provider_call_count,
            "family_results": {
                key: value.to_dict() for key, value in self.family_results.items()
            },
            "fused": self.fused.to_dict(),
            "index_cids": dict(self.index_cids),
            "latency": self.latency.to_dict(),
            "metadata": dict(self.metadata),
            "passed": self.passed,
            "query": self.query,
            "query_id": self.query_id,
            "remote_embedding_calls": self.remote_embedding_calls,
            "reproducibility_digest": self.reproducibility_digest,
            "reproducible": self.reproducible,
            "schema_version": self.schema_version,
        }

    def receipt(self, family: RetrievalFamily | str = RetrievalFamily.FUSION) -> EvaluationReceipt:
        """Return the evaluation receipt for *family* (default fused)."""
        if isinstance(family, str):
            family = RetrievalFamily(family.strip())
        if family is RetrievalFamily.FUSION:
            if self.fused.receipt is None:
                raise RetrievalEvalError("fused evaluation has no receipt")
            return self.fused.receipt
        key = family.value
        if key not in self.family_results or self.family_results[key].receipt is None:
            raise RetrievalEvalError(f"no receipt for family {key!r}")
        return self.family_results[key].receipt  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class EvaluationFixture:
    """Loaded evaluation fixture (qrels + thresholds + query texts)."""

    schema_version: str
    qrel_set: QrelSet
    thresholds: MetricThresholds
    queries: tuple[Mapping[str, str], ...]
    latency_max_ms: float
    private_document_ids: tuple[str, ...]
    gold_corpus_fixture: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "gold_corpus_fixture": self.gold_corpus_fixture,
            "latency_max_ms": self.latency_max_ms,
            "metadata": dict(self.metadata),
            "private_document_ids": list(self.private_document_ids),
            "qrel_set": self.qrel_set.to_dict(),
            "queries": [dict(q) for q in self.queries],
            "schema_version": self.schema_version,
            "thresholds": self.thresholds.to_dict(),
        }


def default_fixture_path() -> Path:
    """Return the repository path of the packaged qrels fixture."""
    # retrieval_eval.py → patent → domains → processors → ipfs_datasets_py → repo root
    root = Path(__file__).resolve().parents[4]
    return root / "tests" / "fixtures" / "patent" / "retrieval" / "qrels.json"


def default_gold_corpus_path() -> Path:
    """Return the repository path of the hybrid golden corpus fixture."""
    return default_fixture_path().with_name("golden_case.json")


def load_qrel_set(path: str | Path | Mapping[str, Any] | QrelSet) -> QrelSet:
    """Load a :class:`QrelSet` from a path, mapping, or existing instance."""
    if isinstance(path, QrelSet):
        return path
    if isinstance(path, Mapping):
        payload = path
    else:
        raw = Path(path).read_text(encoding="utf-8")
        payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise TypeError("qrels payload must be a mapping")
    # Support both bare QrelSet and EvaluationFixture envelopes.
    if "qrel_set" in payload:
        inner = payload["qrel_set"]
        if not isinstance(inner, Mapping):
            raise TypeError("fixture.qrel_set must be a mapping")
        return QrelSet.from_dict(inner)
    return QrelSet.from_dict(payload)


def load_evaluation_fixture(
    path: str | Path | Mapping[str, Any] | None = None,
) -> EvaluationFixture:
    """Load the PATLAW-093 evaluation fixture (qrels + thresholds + queries)."""
    if path is None:
        path = default_fixture_path()
    if isinstance(path, Mapping):
        payload = dict(path)
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("evaluation fixture must be a mapping")

    schema = str(payload.get("schema_version") or FIXTURE_SCHEMA_VERSION)
    if schema not in {FIXTURE_SCHEMA_VERSION, EVALUATION_SCHEMA_VERSION}:
        # Accept bare QrelSet documents by wrapping them.
        if "judgments" in payload and "qrels_cid" in payload:
            qrel_set = QrelSet.from_dict(payload)
            thresholds = MetricThresholds.default(thresholds_cid=DEFAULT_THRESHOLDS_CID)
            return EvaluationFixture(
                schema_version=FIXTURE_SCHEMA_VERSION,
                qrel_set=qrel_set,
                thresholds=thresholds,
                queries=(),
                latency_max_ms=DEFAULT_LATENCY_MAX_MS,
                private_document_ids=(),
            )
        raise RetrievalEvalError(
            f"unsupported evaluation fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )

    qrel_raw = payload.get("qrel_set") or payload.get("qrels")
    if qrel_raw is None:
        raise RetrievalEvalError("evaluation fixture missing qrel_set")
    qrel_set = QrelSet.from_dict(qrel_raw)

    thr_raw = payload.get("thresholds")
    if thr_raw is None:
        thresholds = MetricThresholds.default(
            thresholds_cid=str(
                payload.get("thresholds_cid") or DEFAULT_THRESHOLDS_CID
            )
        )
    else:
        thresholds = MetricThresholds.from_dict(thr_raw)

    queries_out: list[dict[str, str]] = []
    for i, item in enumerate(payload.get("queries") or ()):
        if not isinstance(item, Mapping):
            raise TypeError(f"queries[{i}] must be a mapping")
        qid = str(item.get("query_id") or "").strip()
        text = str(item.get("query") or "").strip()
        if not qid or not text:
            raise RetrievalEvalError(
                f"queries[{i}] requires non-empty query_id and query"
            )
        queries_out.append({"query_id": qid, "query": text})

    private_ids = tuple(
        str(x).strip()
        for x in (payload.get("private_document_ids") or ())
        if str(x).strip()
    )
    latency_max = float(payload.get("latency_max_ms") or DEFAULT_LATENCY_MAX_MS)
    if latency_max <= 0.0:
        raise RetrievalEvalError("latency_max_ms must be positive")

    meta_raw = payload.get("metadata") or {}
    if not isinstance(meta_raw, Mapping):
        raise TypeError("metadata must be a mapping")
    metadata = {str(k): str(v) for k, v in meta_raw.items()}

    gold = payload.get("gold_corpus_fixture")
    return EvaluationFixture(
        schema_version=FIXTURE_SCHEMA_VERSION,
        qrel_set=qrel_set,
        thresholds=thresholds,
        queries=tuple(queries_out),
        latency_max_ms=latency_max,
        private_document_ids=private_ids,
        gold_corpus_fixture=None if gold is None else str(gold),
        metadata=MappingProxyType(metadata),
    )


def ranking_digest(hits: Sequence[RankedHit]) -> str:
    """Deterministic digest of a ranked hit list (reproducibility surface)."""
    payload = [
        {
            "document_id": h.document_id,
            "family": h.family.value if hasattr(h.family, "value") else str(h.family),
            "rank": h.rank,
            "score": round(float(h.score), 12),
            "source_cids": sorted({link.source_cid for link in h.source_links}),
        }
        for h in sorted(hits, key=lambda x: (x.rank, x.document_id))
    ]
    blob = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def row_effective_from_documents(
    documents: Sequence[PatentIndexDocument | Mapping[str, Any]],
) -> dict[str, tuple[str | None, str | None]]:
    """Map document_id → (effective_from_utc, effective_to_utc)."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for item in documents:
        if isinstance(item, PatentIndexDocument):
            doc_id = item.document_id
            start = item.effective_from_utc
            end = item.effective_to_utc
        elif isinstance(item, Mapping):
            doc_id = str(item.get("document_id") or "").strip()
            start = item.get("effective_from_utc")
            end = item.get("effective_to_utc")
        else:
            raise TypeError(
                "documents items must be PatentIndexDocument or mapping"
            )
        if not doc_id:
            raise RetrievalEvalError("document missing document_id")
        out[doc_id] = (
            None if start is None else str(start),
            None if end is None else str(end),
        )
    return out


def row_effective_from_bundle(
    bundle: PatentIndexBundle,
) -> dict[str, tuple[str | None, str | None]]:
    """Collect effective intervals from all family indexes in *bundle*."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for doc in bundle.bm25.documents:
        out[doc.document_id] = (doc.effective_from_utc, doc.effective_to_utc)
    for doc in bundle.vector.documents:
        row = doc.row
        out.setdefault(
            row.document_id, (row.effective_from_utc, row.effective_to_utc)
        )
    for node in bundle.graph.nodes:
        doc_id = node.document_id or node.node_id
        if doc_id:
            out.setdefault(
                doc_id, (node.effective_from_utc, node.effective_to_utc)
            )
    return out


def hits_for_family(
    result: HybridSearchResult, family: RetrievalFamily
) -> tuple[RankedHit, ...]:
    """Extract the ranked hits for *family* from a hybrid search result."""
    if family is RetrievalFamily.FUSION:
        return result.fusion.fused_hits
    attr = _FAMILY_ATTR.get(family)
    if attr is None:
        raise RetrievalEvalError(f"unsupported family {family!r}")
    return getattr(result.fusion, attr)


def leaked_private_hits(
    hits: Sequence[RankedHit],
    private_document_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return private document ids that leaked into *hits*."""
    private = frozenset(str(x) for x in private_document_ids)
    if not private:
        return ()
    return tuple(
        sorted({h.document_id for h in hits if h.document_id in private})
    )


def score_family_ranking(
    *,
    hits: Sequence[RankedHit],
    qrel_set: QrelSet,
    query_id: str,
    filters: PreRankingFilters,
    family: RetrievalFamily,
    k: int = 10,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Iterable[str] = (),
    expected_denied_provider_calls: int | None = None,
) -> tuple[
    tuple[MetricScore, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Score one ranking; return metrics plus source/citation/temporal errors.

    Filters must already be applied. Source errors combine missing source
    coverage and citation grounding failures.
    """
    require_pre_ranking_filters(filters)
    qrels = qrel_set.for_query(query_id)
    if not qrels:
        raise RetrievalEvalError(
            f"no qrels for query_id={query_id!r} in qrel set {qrel_set.qrels_cid}"
        )

    leaks = leaked_private_hits(hits, private_document_ids)
    metrics = evaluate_ranking(
        hits=hits,
        qrel_set=qrel_set,
        query_id=query_id,
        filters=filters,
        k=k,
        family=family,
        row_effective=row_effective,
        leaked_private_document_ids=leaks,
        expected_denied_provider_calls=expected_denied_provider_calls,
    )
    # Re-run enumerating helpers so errors are not discarded.
    citation_score, citation_errors = compute_citation_grounding(
        hits, qrels, k=k, filters=filters
    )
    temporal_score, temporal_errors = compute_temporal_accuracy(
        hits,
        qrels,
        as_of_utc=filters.as_of_utc,
        k=k,
        filters=filters,
        row_effective=row_effective,
    )
    source_score, source_cov_errors = compute_source_coverage(
        hits, k=k, filters=filters
    )
    # Sanity: metric suite values should match re-scored helpers.
    by_kind = {m.kind: m for m in metrics}
    if abs(by_kind[MetricKind.CITATION].value - citation_score.value) > 1e-9:
        raise RetrievalEvalError("citation metric mismatch with enumeration pass")
    if abs(by_kind[MetricKind.TEMPORAL].value - temporal_score.value) > 1e-9:
        raise RetrievalEvalError("temporal metric mismatch with enumeration pass")
    if abs(by_kind[MetricKind.SOURCE_COVERAGE].value - source_score.value) > 1e-9:
        raise RetrievalEvalError("source_coverage metric mismatch with enumeration pass")

    source_errors = tuple(list(source_cov_errors) + list(citation_errors))
    return metrics, source_errors, temporal_errors, citation_errors


def build_family_evaluation(
    *,
    hits: Sequence[RankedHit],
    qrel_set: QrelSet,
    query_id: str,
    filters: PreRankingFilters,
    family: RetrievalFamily,
    corpus_cid: str,
    model_cid: str,
    config_cid: str,
    index_cids: Mapping[str, str],
    thresholds: MetricThresholds,
    k: int | None = None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Iterable[str] = (),
    expected_denied_provider_calls: int | None = None,
    receipt_id: str | None = None,
    evaluated_at_utc: str | None = None,
    fail_loudly: bool = True,
    metadata: Mapping[str, str] | None = None,
) -> FamilyEvaluation:
    """Score *hits*, apply versioned thresholds, and bind an evaluation receipt."""
    require_pre_ranking_filters(filters)
    k_eff = int(k if k is not None else thresholds.k)
    metrics, source_errors, temporal_errors, citation_errors = score_family_ranking(
        hits=hits,
        qrel_set=qrel_set,
        query_id=query_id,
        filters=filters,
        family=family,
        k=k_eff,
        row_effective=row_effective,
        private_document_ids=private_document_ids,
        expected_denied_provider_calls=expected_denied_provider_calls,
    )
    if fail_loudly:
        annotated = assert_thresholds(metrics, thresholds)
    else:
        from .evaluation import apply_thresholds

        annotated = apply_thresholds(metrics, thresholds)

    denied = int(filters.denied_provider_call_count)
    receipt = build_evaluation_receipt(
        receipt_id=receipt_id
        or f"eval:{query_id}:{family.value}",
        corpus_cid=corpus_cid,
        model_cid=model_cid,
        config_cid=config_cid,
        qrels_cid=qrel_set.qrels_cid,
        metrics=annotated,
        filters=filters,
        index_cids=index_cids,
        thresholds=thresholds,
        family=family,
        evaluated_at_utc=evaluated_at_utc,
        source_errors=source_errors,
        temporal_errors=temporal_errors,
        metadata={
            **(dict(metadata) if metadata else {}),
            "citation_error_count": str(len(citation_errors)),
            "query_id": query_id,
            "family": family.value,
        },
    )
    # Isolation must surface denied provider-call counts on the receipt.
    if receipt.denied_provider_call_count != denied:
        raise RetrievalEvalError(
            "receipt denied_provider_call_count does not match filters"
        )

    ordered = tuple(
        h.document_id
        for h in sorted(hits, key=lambda x: (x.rank, x.document_id))
    )
    passed = bool(receipt.passed) and all(
        m.passed is not False for m in annotated
    )
    if fail_loudly and not passed:
        # assert_thresholds already raises on metric regression; this covers
        # receipt-level failures (missing kinds, etc.).
        raise MetricThresholdError(
            f"evaluation receipt failed for family={family.value} "
            f"query={query_id!r}"
        )
    return FamilyEvaluation(
        family=family,
        metrics=annotated,
        source_errors=source_errors,
        temporal_errors=temporal_errors,
        citation_errors=citation_errors,
        hit_document_ids=ordered,
        ranking_digest=ranking_digest(hits),
        denied_provider_call_count=denied,
        receipt=receipt,
        passed=passed,
    )


def assert_latency_envelope(measurement: LatencyMeasurement) -> LatencyMeasurement:
    """Fail loudly when measured latency exceeds the versioned envelope."""
    if not measurement.passed:
        raise LatencyEnvelopeError(
            f"latency envelope exceeded for {measurement.label!r}: "
            f"{measurement.elapsed_ms:.3f}ms > {measurement.max_ms:.3f}ms"
        )
    return measurement


class PatentRetrievalEvaluator:
    """Evaluate hybrid retrieval quality, time, citations, and isolation.

    Usage::

        fixture = load_evaluation_fixture()
        evaluator = PatentRetrievalEvaluator(fixture)
        result = evaluator.evaluate_query(
            query_id=..., query=..., retriever=..., filters=...,
            row_effective=...,
        )
    """

    def __init__(
        self,
        fixture: EvaluationFixture | QrelSet | None = None,
        *,
        thresholds: MetricThresholds | None = None,
        latency_max_ms: float | None = None,
        private_document_ids: Sequence[str] = (),
        fail_loudly: bool = True,
        families: Sequence[RetrievalFamily] | None = None,
    ) -> None:
        if fixture is None:
            loaded = load_evaluation_fixture()
            self.fixture = loaded
            self.qrel_set = loaded.qrel_set
            self.thresholds = thresholds or loaded.thresholds
            self.latency_max_ms = float(
                latency_max_ms
                if latency_max_ms is not None
                else loaded.latency_max_ms
            )
            self.private_document_ids = tuple(
                private_document_ids or loaded.private_document_ids
            )
        elif isinstance(fixture, EvaluationFixture):
            self.fixture = fixture
            self.qrel_set = fixture.qrel_set
            self.thresholds = thresholds or fixture.thresholds
            self.latency_max_ms = float(
                latency_max_ms
                if latency_max_ms is not None
                else fixture.latency_max_ms
            )
            self.private_document_ids = tuple(
                private_document_ids or fixture.private_document_ids
            )
        elif isinstance(fixture, QrelSet):
            self.fixture = None
            self.qrel_set = fixture
            self.thresholds = thresholds or MetricThresholds.default(
                thresholds_cid=DEFAULT_THRESHOLDS_CID
            )
            self.latency_max_ms = float(
                latency_max_ms
                if latency_max_ms is not None
                else DEFAULT_LATENCY_MAX_MS
            )
            self.private_document_ids = tuple(private_document_ids)
        else:
            raise TypeError(
                "fixture must be EvaluationFixture, QrelSet, or None"
            )

        if self.latency_max_ms <= 0.0:
            raise RetrievalEvalError("latency_max_ms must be positive")
        self.fail_loudly = bool(fail_loudly)
        if families is None:
            self.families = (
                RetrievalFamily.BM25,
                RetrievalFamily.VECTOR,
                RetrievalFamily.GRAPH,
                RetrievalFamily.FUSION,
            )
        else:
            self.families = tuple(
                f if isinstance(f, RetrievalFamily) else RetrievalFamily(str(f))
                for f in families
            )
        if RetrievalFamily.FUSION not in self.families:
            # Fusion is always evaluated so receipts bind the fused ranking.
            self.families = self.families + (RetrievalFamily.FUSION,)

    @classmethod
    def from_fixture_path(
        cls, path: str | Path | None = None, **kwargs: Any
    ) -> "PatentRetrievalEvaluator":
        """Construct an evaluator from a fixture path (default packaged qrels)."""
        return cls(load_evaluation_fixture(path), **kwargs)

    def evaluate_hits(
        self,
        hits: Sequence[RankedHit],
        *,
        query_id: str,
        filters: PreRankingFilters,
        family: RetrievalFamily,
        corpus_cid: str,
        model_cid: str,
        config_cid: str,
        index_cids: Mapping[str, str],
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        expected_denied_provider_calls: int | None = None,
        receipt_id: str | None = None,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> FamilyEvaluation:
        """Evaluate a single ranked hit list against qrels and thresholds."""
        return build_family_evaluation(
            hits=hits,
            qrel_set=self.qrel_set,
            query_id=query_id,
            filters=filters,
            family=family,
            corpus_cid=corpus_cid,
            model_cid=model_cid,
            config_cid=config_cid,
            index_cids=index_cids,
            thresholds=self.thresholds,
            k=self.thresholds.k,
            row_effective=row_effective,
            private_document_ids=self.private_document_ids,
            expected_denied_provider_calls=expected_denied_provider_calls,
            receipt_id=receipt_id,
            evaluated_at_utc=evaluated_at_utc,
            fail_loudly=self.fail_loudly,
            metadata=metadata,
        )

    def evaluate_search_result(
        self,
        result: HybridSearchResult,
        *,
        query_id: str,
        query: str,
        corpus_cid: str,
        model_cid: str,
        config_cid: str,
        index_cids: Mapping[str, str] | None = None,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        latency: LatencyMeasurement | None = None,
        second_result: HybridSearchResult | None = None,
        expected_denied_provider_calls: int | None = None,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> QueryEvaluationResult:
        """Evaluate all configured families on one hybrid search result."""
        filters = result.filters
        require_pre_ranking_filters(filters)
        idx = dict(index_cids if index_cids is not None else result.fusion.index_cids)
        denied = int(result.denied_provider_call_count)
        # Prefer the filter receipt count when the search already stamped it.
        if filters.denied_provider_call_count != denied:
            # Align filters with the authoritative search counter for isolation.
            filters = PreRankingFilters(
                schema_version=filters.schema_version,
                tenant_id=filters.tenant_id,
                as_of_utc=filters.as_of_utc,
                allowed_disclosures=filters.allowed_disclosures,
                applied=True,
                denied_provider_call_count=denied,
                filter_receipt_id=filters.filter_receipt_id,
                metadata=dict(filters.metadata),
            )
        expected_denied = (
            denied
            if expected_denied_provider_calls is None
            else int(expected_denied_provider_calls)
        )

        family_results: dict[str, FamilyEvaluation] = {}
        fused_eval: FamilyEvaluation | None = None
        for family in self.families:
            hits = hits_for_family(result, family)
            fam_eval = self.evaluate_hits(
                hits,
                query_id=query_id,
                filters=filters,
                family=family,
                corpus_cid=corpus_cid,
                model_cid=model_cid,
                config_cid=config_cid,
                index_cids=idx,
                row_effective=row_effective,
                expected_denied_provider_calls=expected_denied,
                receipt_id=f"eval:{query_id}:{family.value}",
                evaluated_at_utc=evaluated_at_utc,
                metadata=metadata,
            )
            if family is RetrievalFamily.FUSION:
                fused_eval = fam_eval
            else:
                family_results[family.value] = fam_eval

        if fused_eval is None:
            raise RetrievalEvalError("fusion family was not evaluated")

        # Reproducibility: optional second run, else self-digest of fused ranking.
        primary_digest = fused_eval.ranking_digest
        if second_result is not None:
            second_hits = hits_for_family(second_result, RetrievalFamily.FUSION)
            second_digest = ranking_digest(second_hits)
            reproducible = primary_digest == second_digest
            if self.fail_loudly and not reproducible:
                raise ReproducibilityError(
                    f"fused ranking not reproducible for query={query_id!r}: "
                    f"{primary_digest} != {second_digest}"
                )
            repro_digest = primary_digest if reproducible else (
                f"{primary_digest}:{second_digest}"
            )
        else:
            reproducible = True
            repro_digest = primary_digest

        if latency is None:
            latency = LatencyMeasurement(
                elapsed_ms=0.0,
                max_ms=self.latency_max_ms,
                label=f"search:{query_id}",
            )
        if self.fail_loudly:
            assert_latency_envelope(latency)

        binding = {
            "corpus_cid": corpus_cid,
            "model_cid": model_cid,
            "config_cid": config_cid,
            "qrels_cid": self.qrel_set.qrels_cid,
        }
        # Receipt must also bind index CIDs.
        if fused_eval.receipt is not None:
            for key, value in idx.items():
                if fused_eval.receipt.index_cids.get(key) != value:
                    raise RetrievalEvalError(
                        f"receipt index_cids[{key!r}] does not match binding"
                    )
            for key, value in binding.items():
                if fused_eval.receipt.binding_cids().get(key) != value:
                    raise RetrievalEvalError(
                        f"receipt binding {key} mismatch"
                    )

        all_family_pass = all(fr.passed for fr in family_results.values())
        passed = (
            fused_eval.passed
            and all_family_pass
            and reproducible
            and latency.passed
        )
        return QueryEvaluationResult(
            schema_version=RETRIEVAL_EVAL_SCHEMA_VERSION,
            query_id=query_id,
            query=query,
            family_results=MappingProxyType(family_results),
            fused=fused_eval,
            latency=latency,
            reproducibility_digest=repro_digest,
            reproducible=reproducible,
            denied_provider_call_count=denied,
            remote_embedding_calls=int(result.remote_embedding_calls),
            binding_cids=MappingProxyType(binding),
            index_cids=MappingProxyType(dict(sorted(idx.items()))),
            passed=passed,
            metadata=MappingProxyType(dict(metadata or {})),
        )

    def evaluate_query(
        self,
        *,
        query_id: str,
        query: str,
        retriever: PatentHybridRetriever | None = None,
        bundle: PatentIndexBundle | None = None,
        filters: PreRankingFilters,
        top_k: int | None = None,
        fusion_weights: FusionWeights | Mapping[str, float] | None = None,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        allow_remote_embeddings: bool = False,
        query_disclosure: DisclosureClass | str = DisclosureClass.PUBLIC_USER,
        seed_document_ids: Sequence[str] = (),
        expected_denied_provider_calls: int | None = None,
        check_reproducibility: bool = True,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> QueryEvaluationResult:
        """Run hybrid search (twice when checking reproducibility) and score it."""
        require_pre_ranking_filters(filters)
        if retriever is None and bundle is None:
            raise RetrievalEvalError("evaluate_query requires retriever or bundle")
        if retriever is None:
            assert bundle is not None
            retriever = PatentHybridRetriever(bundle)
        top = int(top_k if top_k is not None else self.thresholds.k)
        if isinstance(query_disclosure, str):
            query_disclosure = DisclosureClass(query_disclosure)
        weights: FusionWeights | None
        if fusion_weights is None:
            weights = FusionWeights(bm25=1.0, vector=1.0, graph=0.5)
        elif isinstance(fusion_weights, FusionWeights):
            weights = fusion_weights
        else:
            weights = FusionWeights.from_dict(fusion_weights)

        request = HybridSearchRequest(
            query_id=query_id,
            query=query,
            filters=filters,
            top_k=top,
            fusion_weights=weights,
            seed_document_ids=tuple(seed_document_ids),
            allow_remote_embeddings=allow_remote_embeddings,
            query_disclosure=query_disclosure,
        )

        t0 = time.perf_counter()
        first = retriever.search(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        second: HybridSearchResult | None = None
        if check_reproducibility:
            second = retriever.search(request)

        latency = LatencyMeasurement(
            elapsed_ms=elapsed_ms,
            max_ms=self.latency_max_ms,
            label=f"search:{query_id}",
        )

        corpus_cid = retriever.corpus_cid
        model_cid = retriever.model_cid or (
            first.vector_embedding.get("model_cid")
            or first.fusion.model_cid
            or ""
        )
        if not model_cid:
            raise RetrievalEvalError("model_cid missing from retriever/search result")
        config_cid = retriever.config_cid or first.fusion.config_cid
        index_cids = dict(retriever.index_cids or first.fusion.index_cids)

        if row_effective is None and retriever._bundle is not None:
            row_effective = row_effective_from_bundle(retriever._bundle)

        return self.evaluate_search_result(
            first,
            query_id=query_id,
            query=query,
            corpus_cid=corpus_cid,
            model_cid=str(model_cid),
            config_cid=str(config_cid),
            index_cids=index_cids,
            row_effective=row_effective,
            latency=latency,
            second_result=second,
            expected_denied_provider_calls=expected_denied_provider_calls,
            evaluated_at_utc=evaluated_at_utc,
            metadata=metadata,
        )

    def evaluate_fixture_queries(
        self,
        *,
        retriever: PatentHybridRetriever | None = None,
        bundle: PatentIndexBundle | None = None,
        filters: PreRankingFilters,
        queries: Sequence[Mapping[str, str]] | None = None,
        **kwargs: Any,
    ) -> tuple[QueryEvaluationResult, ...]:
        """Evaluate every query declared on the loaded fixture (or *queries*)."""
        items: Sequence[Mapping[str, str]]
        if queries is not None:
            items = queries
        elif self.fixture is not None and self.fixture.queries:
            items = self.fixture.queries
        else:
            raise RetrievalEvalError(
                "no queries provided and fixture declares none"
            )
        results: list[QueryEvaluationResult] = []
        for item in items:
            results.append(
                self.evaluate_query(
                    query_id=str(item["query_id"]),
                    query=str(item["query"]),
                    retriever=retriever,
                    bundle=bundle,
                    filters=filters,
                    **kwargs,
                )
            )
        return tuple(results)


def evaluate_hybrid_against_qrels(
    *,
    bundle: PatentIndexBundle,
    qrel_set: QrelSet | EvaluationFixture | str | Path,
    query_id: str,
    query: str,
    filters: PreRankingFilters,
    thresholds: MetricThresholds | None = None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Sequence[str] = (),
    fail_loudly: bool = True,
    **kwargs: Any,
) -> QueryEvaluationResult:
    """Functional entry point: score one hybrid query against qrels."""
    if isinstance(qrel_set, EvaluationFixture):
        evaluator = PatentRetrievalEvaluator(
            qrel_set,
            thresholds=thresholds,
            private_document_ids=private_document_ids
            or qrel_set.private_document_ids,
            fail_loudly=fail_loudly,
        )
    else:
        loaded = (
            qrel_set
            if isinstance(qrel_set, QrelSet)
            else load_qrel_set(qrel_set)
        )
        evaluator = PatentRetrievalEvaluator(
            loaded,
            thresholds=thresholds,
            private_document_ids=private_document_ids,
            fail_loudly=fail_loudly,
        )
    return evaluator.evaluate_query(
        query_id=query_id,
        query=query,
        bundle=bundle,
        filters=filters,
        row_effective=row_effective,
        **kwargs,
    )


def build_bundle_from_gold_corpus(
    gold: Mapping[str, Any] | str | Path | None = None,
) -> tuple[PatentIndexBundle, dict[str, Any]]:
    """Build a patent index bundle from the golden hybrid corpus fixture."""
    if gold is None:
        gold_path = default_gold_corpus_path()
        data = json.loads(gold_path.read_text(encoding="utf-8"))
    elif isinstance(gold, (str, Path)):
        data = json.loads(Path(gold).read_text(encoding="utf-8"))
    else:
        data = dict(gold)
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=str(data["tenant_id"]),
        as_of_utc=str(data["as_of_utc"]),
        allowed_disclosures=tuple(data["allowed_disclosures"]),
        applied=True,
        filter_receipt_id="filter:eval-gold",
    )
    emb_cfg = data.get("embedding") or {}
    embedding = default_embedding_identity(
        config_cid=data.get("config_cid"),
        model_cid=data.get("model_cid"),
        dimension=int(emb_cfg.get("dimension") or 256),
        provider=str(emb_cfg.get("provider") or "local_hash"),
        model_id=str(emb_cfg.get("model_id") or "hashed-term-patent-v1"),
        model_version=str(emb_cfg.get("model_version") or "1.0.0"),
        backend=str(emb_cfg.get("backend") or "pinned"),
    )
    bundle = build_patent_indexes(
        docs,
        filters=filters,
        edges=data.get("edges") or [],
        embedding=embedding,
        corpus_cid=str(data["corpus_cid"]),
        allow_remote=False,
    )
    return bundle, data


__all__ = [
    "DEFAULT_LATENCY_MAX_MS",
    "DEFAULT_QRELS_CID",
    "DEFAULT_THRESHOLDS_CID",
    "FIXTURE_SCHEMA_VERSION",
    "RETRIEVAL_EVAL_INTERFACE",
    "RETRIEVAL_EVAL_SCHEMA_VERSION",
    "EvaluationFixture",
    "FamilyEvaluation",
    "LatencyEnvelopeError",
    "LatencyMeasurement",
    "PatentRetrievalEvaluator",
    "QueryEvaluationResult",
    "ReproducibilityError",
    "RetrievalEvalError",
    "assert_latency_envelope",
    "build_bundle_from_gold_corpus",
    "build_family_evaluation",
    "default_fixture_path",
    "default_gold_corpus_path",
    "evaluate_hybrid_against_qrels",
    "hits_for_family",
    "leaked_private_hits",
    "load_evaluation_fixture",
    "load_qrel_set",
    "ranking_digest",
    "row_effective_from_bundle",
    "row_effective_from_documents",
    "score_family_ranking",
    # Re-exports used by integration tests / callers.
    "EvaluationReceipt",
    "MetricKind",
    "MetricThresholdError",
    "MetricThresholds",
    "Qrel",
    "QrelSet",
    "RelevanceGrade",
    "REQUIRED_METRIC_KINDS",
    "canonical_json",
    "hybrid_search",
    "MissingPreRankingFiltersError",
]
