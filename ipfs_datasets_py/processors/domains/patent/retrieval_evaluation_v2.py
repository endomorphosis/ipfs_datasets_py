"""Real-corpus evaluation for explainable hybrid retrieval (PATLAW-147).

Concrete evaluation layer over :mod:`evaluation` contracts and
:mod:`hybrid_retrieval_v2`:

* load versioned qrels_v2 / thresholds fixtures;
* measure fused (and optional family) rankings for recall, ranking (nDCG),
  citation grounding, temporal accuracy, source coverage, isolation, and
  provenance of component contributions;
* emit evaluation receipts that bind **snapshot / model / config / qrels**;
* report missing source coverage as *not searched* rather than scoring those
  sources as searched;
* fail loudly on versioned threshold regressions (including intentionally
  degraded retrieval).

No network I/O lives here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
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
    assert_thresholds,
    build_evaluation_receipt,
    compute_citation_grounding,
    compute_ndcg_at_k,
    compute_private_isolation,
    compute_recall_at_k,
    compute_source_coverage,
    compute_temporal_accuracy,
    evaluate_ranking,
)
from .hybrid_retrieval_v2 import (
    HYBRID_RETRIEVAL_V2_SCHEMA_VERSION,
    ComponentWeights,
    ExplainableHit,
    HybridRetrievalV2,
    HybridSearchRequestV2,
    HybridSearchResultV2,
    SnapshotBinding,
    degrade_ranking,
    ranking_digest_v2,
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
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    require_pre_ranking_filters,
)
from .retrieval_eval import (
    DEFAULT_LATENCY_MAX_MS,
    LatencyEnvelopeError,
    LatencyMeasurement,
    assert_latency_envelope,
    ranking_digest as ranking_digest_v1,
    row_effective_from_documents,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

RETRIEVAL_EVAL_V2_SCHEMA_VERSION: Final = "patent.retrieval.eval.v2"
RETRIEVAL_EVAL_V2_INTERFACE: Final = "PatentRetrievalEvaluatorV2@1"
FIXTURE_V2_SCHEMA_VERSION: Final = "patent.retrieval.eval.fixture.v2"

DEFAULT_QRELS_V2_CID: Final = (
    "bafybeiqrelsv2identity0000000000000000000000000000000000002"
)
DEFAULT_THRESHOLDS_V2_CID: Final = (
    "bafybeithresholdsv2000000000000000000000000000000000000003"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RetrievalEvalV2Error(EvaluationError):
    """Base error for the v2 retrieval evaluation harness."""


class ReproducibilityV2Error(RetrievalEvalV2Error):
    """Raised when two identical evaluation runs diverge."""


class SourceCoverageReportError(RetrievalEvalV2Error):
    """Raised when missing coverage is incorrectly scored as searched."""


# ---------------------------------------------------------------------------
# Source coverage reporting (not searched vs searched)
# ---------------------------------------------------------------------------


class SourceCoverageStatus(str, Enum):
    """Whether a declared source was searched, missing, or out of scope."""

    SEARCHED = "searched"
    MISSING = "missing"
    NOT_SEARCHED = "not_searched"
    UNSEARCHED_DECLARED = "unsearched_declared"


@dataclass(frozen=True, slots=True)
class SourceCoverageItem:
    """One declared source's coverage status for a query evaluation."""

    source_id: str
    status: SourceCoverageStatus
    reason: str = ""
    source_cid: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", str(self.source_id).strip())
        if not self.source_id:
            raise RetrievalEvalV2Error("source_id must be non-empty")
        if isinstance(self.status, SourceCoverageStatus):
            status = self.status
        else:
            status = SourceCoverageStatus(str(self.status).strip().lower())
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(
            self,
            "source_cid",
            None if self.source_cid is None else str(self.source_cid),
        )

    @property
    def scored_as_searched(self) -> bool:
        """Only SEARCHED items count toward searched coverage metrics."""
        return self.status is SourceCoverageStatus.SEARCHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "source_cid": self.source_cid,
            "source_id": self.source_id,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceCoverageItem":
        if not isinstance(value, Mapping):
            raise TypeError("SourceCoverageItem payload must be a mapping")
        return cls(
            source_id=str(value.get("source_id") or ""),
            status=SourceCoverageStatus(str(value.get("status") or "missing")),
            reason=str(value.get("reason") or ""),
            source_cid=value.get("source_cid"),
        )


@dataclass(frozen=True, slots=True)
class SourceCoverageReport:
    """Coverage report separating searched hits from missing / not-searched.

    Acceptance: missing source coverage is **reported** rather than scored as
    searched. Metrics that measure hit-level source CID joins still use the
    evaluation helpers; declared-but-unsearched sources appear only here.
    """

    items: tuple[SourceCoverageItem, ...]
    searched_source_ids: tuple[str, ...]
    missing_source_ids: tuple[str, ...]
    not_searched_source_ids: tuple[str, ...]
    hit_source_coverage: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(
            self, "searched_source_ids", tuple(self.searched_source_ids)
        )
        object.__setattr__(
            self, "missing_source_ids", tuple(self.missing_source_ids)
        )
        object.__setattr__(
            self, "not_searched_source_ids", tuple(self.not_searched_source_ids)
        )
        object.__setattr__(self, "hit_source_coverage", float(self.hit_source_coverage))
        # Fail closed: nothing marked missing/not_searched may appear as searched.
        searched = set(self.searched_source_ids)
        for sid in self.missing_source_ids:
            if sid in searched:
                raise SourceCoverageReportError(
                    f"source {sid!r} reported missing but also searched"
                )
        for sid in self.not_searched_source_ids:
            if sid in searched:
                raise SourceCoverageReportError(
                    f"source {sid!r} reported not_searched but also searched"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hit_source_coverage": self.hit_source_coverage,
            "items": [i.to_dict() for i in self.items],
            "missing_source_ids": list(self.missing_source_ids),
            "not_searched_source_ids": list(self.not_searched_source_ids),
            "searched_source_ids": list(self.searched_source_ids),
        }


def build_source_coverage_report(
    hits: Sequence[ExplainableHit | RankedHit],
    *,
    k: int,
    expected_source_cids: Sequence[str] = (),
    unsearched_sources: Sequence[str] = (),
    declared_sources: Sequence[Mapping[str, Any] | str] = (),
) -> SourceCoverageReport:
    """Build a coverage report for top-k hits and declared source lists.

    * Hit-level source CID joins drive ``hit_source_coverage``.
    * Declared expected CIDs not present in top-k hits are **missing**.
    * Explicitly declared unsearched sources are **not_searched** and never
      counted as searched.
    """
    top = sorted(hits, key=lambda h: h.rank)[: max(1, int(k))]
    hit_cids: set[str] = set()
    covered = 0
    for hit in top:
        if isinstance(hit, ExplainableHit):
            spans = hit.source_spans
            links_ok = bool(spans) and all(s.source_cid for s in spans)
            for s in spans:
                hit_cids.add(s.source_cid)
        else:
            links_ok = bool(hit.source_links) and all(
                link.source_cid for link in hit.source_links
            )
            for link in hit.source_links:
                hit_cids.add(link.source_cid)
        if links_ok:
            covered += 1
    hit_cov = 1.0 if not top else covered / float(len(top))

    unsearched = {
        str(s).strip() for s in unsearched_sources if str(s).strip()
    }
    expected = {
        str(c).strip() for c in expected_source_cids if str(c).strip()
    }

    # Declared sources may be ids or {source_id, source_cid, status?} maps.
    declared_items: list[tuple[str, str | None]] = []
    for raw in declared_sources:
        if isinstance(raw, str):
            sid = raw.strip()
            if sid:
                declared_items.append((sid, None))
        elif isinstance(raw, Mapping):
            sid = str(raw.get("source_id") or raw.get("id") or "").strip()
            cid = raw.get("source_cid")
            if sid:
                declared_items.append(
                    (sid, None if cid is None else str(cid))
                )

    items: list[SourceCoverageItem] = []
    searched_ids: list[str] = []
    missing_ids: list[str] = []
    not_searched_ids: list[str] = []

    # Unsearched declarations first — never scored as searched.
    for sid in sorted(unsearched):
        items.append(
            SourceCoverageItem(
                source_id=sid,
                status=SourceCoverageStatus.UNSEARCHED_DECLARED,
                reason="explicitly declared unsearched; not scored as searched",
            )
        )
        not_searched_ids.append(sid)

    # Expected source CIDs from qrels.
    for cid in sorted(expected):
        if cid in unsearched:
            # Already reported as unsearched; do not reclassify as searched.
            continue
        if cid in hit_cids:
            items.append(
                SourceCoverageItem(
                    source_id=cid,
                    status=SourceCoverageStatus.SEARCHED,
                    reason="present in top-k hit source joins",
                    source_cid=cid,
                )
            )
            searched_ids.append(cid)
        else:
            items.append(
                SourceCoverageItem(
                    source_id=cid,
                    status=SourceCoverageStatus.MISSING,
                    reason="expected source CID absent from top-k hits",
                    source_cid=cid,
                )
            )
            missing_ids.append(cid)

    # Additional declared sources (e.g. foreign / NPL labels).
    for sid, cid in declared_items:
        if sid in unsearched or sid in expected or (cid and cid in expected):
            continue
        if cid and cid in hit_cids:
            items.append(
                SourceCoverageItem(
                    source_id=sid,
                    status=SourceCoverageStatus.SEARCHED,
                    reason="declared source present in hits",
                    source_cid=cid,
                )
            )
            searched_ids.append(sid)
        else:
            items.append(
                SourceCoverageItem(
                    source_id=sid,
                    status=SourceCoverageStatus.NOT_SEARCHED,
                    reason="declared source not searched by this retrieval",
                    source_cid=cid,
                )
            )
            not_searched_ids.append(sid)

    return SourceCoverageReport(
        items=tuple(items),
        searched_source_ids=tuple(searched_ids),
        missing_source_ids=tuple(missing_ids),
        not_searched_source_ids=tuple(not_searched_ids),
        hit_source_coverage=hit_cov,
    )


# ---------------------------------------------------------------------------
# Evaluation result surfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluationReceiptV2:
    """Evaluation receipt binding snapshot / model / config / qrels CIDs."""

    schema_version: str
    receipt_id: str
    snapshot_cid: str
    corpus_cid: str
    model_cid: str
    config_cid: str
    qrels_cid: str
    metrics: tuple[MetricScore, ...]
    filters: PreRankingFilters
    index_cids: Mapping[str, str] = MappingProxyType({})
    thresholds_cid: str | None = None
    family: RetrievalFamily | None = None
    evaluated_at_utc: str | None = None
    source_errors: tuple[str, ...] = ()
    temporal_errors: tuple[str, ...] = ()
    citation_errors: tuple[str, ...] = ()
    denied_provider_call_count: int = 0
    denied_result_count: int = 0
    remote_embedding_calls: int = 0
    source_coverage_report: SourceCoverageReport | None = None
    ranking_digest: str | None = None
    passed: bool = False
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            str(self.schema_version or RETRIEVAL_EVAL_V2_SCHEMA_VERSION),
        )
        for name in (
            "receipt_id",
            "snapshot_cid",
            "corpus_cid",
            "model_cid",
            "config_cid",
            "qrels_cid",
        ):
            object.__setattr__(self, name, str(getattr(self, name)).strip())
            if not getattr(self, name):
                raise RetrievalEvalV2Error(f"{name} must be non-empty")
        require_pre_ranking_filters(self.filters)
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(
            self,
            "index_cids",
            MappingProxyType(
                {str(k): str(v) for k, v in sorted(dict(self.index_cids).items())}
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata).items()}),
        )
        if self.family is not None and isinstance(self.family, str):
            object.__setattr__(self, "family", RetrievalFamily(self.family))

    def binding_cids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "snapshot_cid": self.snapshot_cid,
                "corpus_cid": self.corpus_cid,
                "model_cid": self.model_cid,
                "config_cid": self.config_cid,
                "qrels_cid": self.qrels_cid,
            }
        )

    def metric(self, kind: MetricKind | str) -> MetricScore:
        target = kind if isinstance(kind, MetricKind) else MetricKind(str(kind))
        for item in self.metrics:
            if item.kind is target:
                return item
        raise KeyError(f"no metric for kind {target.value}")

    def to_v1_receipt(self) -> EvaluationReceipt:
        """Project to a v1 EvaluationReceipt (without snapshot_cid field)."""
        return build_evaluation_receipt(
            receipt_id=self.receipt_id,
            corpus_cid=self.corpus_cid,
            model_cid=self.model_cid,
            config_cid=self.config_cid,
            qrels_cid=self.qrels_cid,
            metrics=self.metrics,
            filters=self.filters,
            index_cids=self.index_cids,
            thresholds=None,
            family=self.family,
            evaluated_at_utc=self.evaluated_at_utc,
            source_errors=self.source_errors,
            temporal_errors=self.temporal_errors,
            metadata={
                **dict(self.metadata),
                "snapshot_cid": self.snapshot_cid,
                "thresholds_cid": self.thresholds_cid or "",
                "denied_result_count": str(self.denied_result_count),
                "remote_embedding_calls": str(self.remote_embedding_calls),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_errors": list(self.citation_errors),
            "config_cid": self.config_cid,
            "corpus_cid": self.corpus_cid,
            "denied_provider_call_count": self.denied_provider_call_count,
            "denied_result_count": self.denied_result_count,
            "evaluated_at_utc": self.evaluated_at_utc,
            "family": None if self.family is None else self.family.value,
            "filters": self.filters.to_dict(),
            "index_cids": dict(self.index_cids),
            "metadata": dict(self.metadata),
            "metrics": [m.to_dict() for m in self.metrics],
            "model_cid": self.model_cid,
            "passed": self.passed,
            "qrels_cid": self.qrels_cid,
            "ranking_digest": self.ranking_digest,
            "receipt_id": self.receipt_id,
            "remote_embedding_calls": self.remote_embedding_calls,
            "schema_version": self.schema_version,
            "snapshot_cid": self.snapshot_cid,
            "source_coverage_report": (
                None
                if self.source_coverage_report is None
                else self.source_coverage_report.to_dict()
            ),
            "source_errors": list(self.source_errors),
            "temporal_errors": list(self.temporal_errors),
            "thresholds_cid": self.thresholds_cid,
        }


@dataclass(frozen=True, slots=True)
class FamilyEvaluationV2:
    """Metrics + errors + receipt for one family ranking."""

    family: RetrievalFamily
    metrics: tuple[MetricScore, ...]
    source_errors: tuple[str, ...]
    temporal_errors: tuple[str, ...]
    citation_errors: tuple[str, ...]
    hit_document_ids: tuple[str, ...]
    ranking_digest: str
    denied_provider_call_count: int
    denied_result_count: int
    receipt: EvaluationReceiptV2 | None = None
    source_coverage_report: SourceCoverageReport | None = None
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_errors": list(self.citation_errors),
            "denied_provider_call_count": self.denied_provider_call_count,
            "denied_result_count": self.denied_result_count,
            "family": self.family.value,
            "hit_document_ids": list(self.hit_document_ids),
            "metrics": [m.to_dict() for m in self.metrics],
            "passed": self.passed,
            "ranking_digest": self.ranking_digest,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "source_coverage_report": (
                None
                if self.source_coverage_report is None
                else self.source_coverage_report.to_dict()
            ),
            "source_errors": list(self.source_errors),
            "temporal_errors": list(self.temporal_errors),
        }


@dataclass(frozen=True, slots=True)
class QueryEvaluationResultV2:
    """Per-query multi-family evaluation with snapshot binding."""

    schema_version: str
    query_id: str
    query: str
    family_results: Mapping[str, FamilyEvaluationV2]
    fused: FamilyEvaluationV2
    latency: LatencyMeasurement
    reproducibility_digest: str
    reproducible: bool
    denied_provider_call_count: int
    denied_result_count: int
    remote_embedding_calls: int
    binding: SnapshotBinding
    qrels_cid: str
    source_coverage_report: SourceCoverageReport
    passed: bool
    metadata: Mapping[str, str] = MappingProxyType({})

    def binding_cids(self) -> Mapping[str, str]:
        base = dict(self.binding.binding_cids())
        base["qrels_cid"] = self.qrels_cid
        return MappingProxyType(base)

    def receipt(
        self, family: RetrievalFamily | str = RetrievalFamily.FUSION
    ) -> EvaluationReceiptV2:
        if isinstance(family, str):
            family = RetrievalFamily(family.strip())
        if family is RetrievalFamily.FUSION:
            if self.fused.receipt is None:
                raise RetrievalEvalV2Error("fused evaluation has no receipt")
            return self.fused.receipt
        key = family.value
        if key not in self.family_results or self.family_results[key].receipt is None:
            raise RetrievalEvalV2Error(f"no receipt for family {key!r}")
        return self.family_results[key].receipt  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "denied_provider_call_count": self.denied_provider_call_count,
            "denied_result_count": self.denied_result_count,
            "family_results": {
                k: v.to_dict() for k, v in self.family_results.items()
            },
            "fused": self.fused.to_dict(),
            "latency": self.latency.to_dict(),
            "metadata": dict(self.metadata),
            "passed": self.passed,
            "qrels_cid": self.qrels_cid,
            "query": self.query,
            "query_id": self.query_id,
            "remote_embedding_calls": self.remote_embedding_calls,
            "reproducibility_digest": self.reproducibility_digest,
            "reproducible": self.reproducible,
            "schema_version": self.schema_version,
            "source_coverage_report": self.source_coverage_report.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationFixtureV2:
    """Loaded v2 evaluation fixture (qrels + thresholds + coverage labels)."""

    schema_version: str
    qrel_set: QrelSet
    thresholds: MetricThresholds
    queries: tuple[Mapping[str, str], ...]
    latency_max_ms: float
    private_document_ids: tuple[str, ...]
    unsearched_sources: tuple[str, ...]
    declared_sources: tuple[Mapping[str, Any], ...]
    gold_corpus_fixture: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_sources": [dict(d) for d in self.declared_sources],
            "gold_corpus_fixture": self.gold_corpus_fixture,
            "latency_max_ms": self.latency_max_ms,
            "metadata": dict(self.metadata),
            "private_document_ids": list(self.private_document_ids),
            "qrel_set": self.qrel_set.to_dict(),
            "queries": [dict(q) for q in self.queries],
            "schema_version": self.schema_version,
            "thresholds": self.thresholds.to_dict(),
            "unsearched_sources": list(self.unsearched_sources),
        }


# ---------------------------------------------------------------------------
# Fixture I/O
# ---------------------------------------------------------------------------


def default_fixture_v2_path() -> Path:
    root = Path(__file__).resolve().parents[4]
    return root / "tests" / "fixtures" / "patent" / "retrieval" / "qrels_v2.json"


def default_gold_corpus_path() -> Path:
    return default_fixture_v2_path().with_name("golden_case.json")


def load_qrel_set_v2(path: str | Path | Mapping[str, Any] | QrelSet) -> QrelSet:
    if isinstance(path, QrelSet):
        return path
    if isinstance(path, Mapping):
        payload = path
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("qrels payload must be a mapping")
    if "qrel_set" in payload:
        inner = payload["qrel_set"]
        if not isinstance(inner, Mapping):
            raise TypeError("fixture.qrel_set must be a mapping")
        return QrelSet.from_dict(inner)
    return QrelSet.from_dict(payload)


def load_evaluation_fixture_v2(
    path: str | Path | Mapping[str, Any] | None = None,
) -> EvaluationFixtureV2:
    """Load the PATLAW-147 evaluation fixture (qrels_v2 + thresholds)."""
    if path is None:
        path = default_fixture_v2_path()
    if isinstance(path, Mapping):
        payload = dict(path)
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("evaluation fixture must be a mapping")

    schema = str(payload.get("schema_version") or FIXTURE_V2_SCHEMA_VERSION)
    if schema not in {
        FIXTURE_V2_SCHEMA_VERSION,
        EVALUATION_SCHEMA_VERSION,
        "patent.retrieval.eval.fixture.v1",
    }:
        if "judgments" in payload and "qrels_cid" in payload:
            qrel_set = QrelSet.from_dict(payload)
            thresholds = MetricThresholds.default(
                thresholds_cid=DEFAULT_THRESHOLDS_V2_CID
            )
            return EvaluationFixtureV2(
                schema_version=FIXTURE_V2_SCHEMA_VERSION,
                qrel_set=qrel_set,
                thresholds=thresholds,
                queries=(),
                latency_max_ms=DEFAULT_LATENCY_MAX_MS,
                private_document_ids=(),
                unsearched_sources=(),
                declared_sources=(),
            )
        raise RetrievalEvalV2Error(
            f"unsupported evaluation fixture schema_version {schema!r}; "
            f"expected {FIXTURE_V2_SCHEMA_VERSION!r}"
        )

    qrel_raw = payload.get("qrel_set") or payload.get("qrels")
    if qrel_raw is None:
        raise RetrievalEvalV2Error("evaluation fixture missing qrel_set")
    qrel_set = QrelSet.from_dict(qrel_raw)

    thr_raw = payload.get("thresholds")
    if thr_raw is None:
        thresholds = MetricThresholds.default(
            thresholds_cid=str(
                payload.get("thresholds_cid") or DEFAULT_THRESHOLDS_V2_CID
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
            raise RetrievalEvalV2Error(
                f"queries[{i}] requires non-empty query_id and query"
            )
        queries_out.append({"query_id": qid, "query": text})

    private_ids = tuple(
        str(x).strip()
        for x in (payload.get("private_document_ids") or ())
        if str(x).strip()
    )
    unsearched = tuple(
        str(x).strip()
        for x in (payload.get("unsearched_sources") or ())
        if str(x).strip()
    )
    declared: list[dict[str, Any]] = []
    for item in payload.get("declared_sources") or ():
        if isinstance(item, Mapping):
            declared.append(dict(item))
        elif isinstance(item, str) and item.strip():
            declared.append({"source_id": item.strip()})

    latency_max = float(payload.get("latency_max_ms") or DEFAULT_LATENCY_MAX_MS)
    if latency_max <= 0.0:
        raise RetrievalEvalV2Error("latency_max_ms must be positive")

    meta_raw = payload.get("metadata") or {}
    if not isinstance(meta_raw, Mapping):
        raise TypeError("metadata must be a mapping")
    metadata = {str(k): str(v) for k, v in meta_raw.items()}
    gold = payload.get("gold_corpus_fixture")

    return EvaluationFixtureV2(
        schema_version=FIXTURE_V2_SCHEMA_VERSION,
        qrel_set=qrel_set,
        thresholds=thresholds,
        queries=tuple(queries_out),
        latency_max_ms=latency_max,
        private_document_ids=private_ids,
        unsearched_sources=unsearched,
        declared_sources=tuple(declared),
        gold_corpus_fixture=None if gold is None else str(gold),
        metadata=MappingProxyType(metadata),
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _hits_to_ranked(hits: Sequence[ExplainableHit | RankedHit]) -> tuple[RankedHit, ...]:
    out: list[RankedHit] = []
    for h in hits:
        if isinstance(h, ExplainableHit):
            out.append(h.to_ranked_hit())
        else:
            out.append(h)
    return tuple(out)


def score_explainable_ranking(
    *,
    hits: Sequence[ExplainableHit | RankedHit],
    qrel_set: QrelSet,
    query_id: str,
    filters: PreRankingFilters,
    family: RetrievalFamily,
    k: int = 10,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Iterable[str] = (),
    expected_denied_provider_calls: int | None = None,
    unsearched_sources: Sequence[str] = (),
    declared_sources: Sequence[Mapping[str, Any] | str] = (),
) -> tuple[
    tuple[MetricScore, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    SourceCoverageReport,
]:
    """Score one explainable ranking; return metrics, errors, coverage report."""
    require_pre_ranking_filters(filters)
    ranked = _hits_to_ranked(hits)
    qrels = qrel_set.for_query(query_id)
    if not qrels:
        raise RetrievalEvalV2Error(
            f"no qrels for query_id={query_id!r} in qrel set {qrel_set.qrels_cid}"
        )

    private = frozenset(str(x) for x in private_document_ids)
    leaks = tuple(
        sorted({h.document_id for h in ranked if h.document_id in private})
    )
    metrics = evaluate_ranking(
        hits=ranked,
        qrel_set=qrel_set,
        query_id=query_id,
        filters=filters,
        k=k,
        family=family,
        row_effective=row_effective,
        leaked_private_document_ids=leaks,
        expected_denied_provider_calls=expected_denied_provider_calls,
    )
    citation_score, citation_errors = compute_citation_grounding(
        ranked, qrels, k=k, filters=filters
    )
    temporal_score, temporal_errors = compute_temporal_accuracy(
        ranked,
        qrels,
        as_of_utc=filters.as_of_utc,
        k=k,
        filters=filters,
        row_effective=row_effective,
    )
    source_score, source_cov_errors = compute_source_coverage(
        ranked, k=k, filters=filters
    )
    by_kind = {m.kind: m for m in metrics}
    if abs(by_kind[MetricKind.CITATION].value - citation_score.value) > 1e-9:
        raise RetrievalEvalV2Error("citation metric mismatch")
    if abs(by_kind[MetricKind.TEMPORAL].value - temporal_score.value) > 1e-9:
        raise RetrievalEvalV2Error("temporal metric mismatch")
    if abs(by_kind[MetricKind.SOURCE_COVERAGE].value - source_score.value) > 1e-9:
        raise RetrievalEvalV2Error("source_coverage metric mismatch")

    expected_cids: list[str] = []
    for q in qrels:
        expected_cids.extend(q.expected_source_cids)

    coverage = build_source_coverage_report(
        hits,
        k=k,
        expected_source_cids=expected_cids,
        unsearched_sources=unsearched_sources,
        declared_sources=declared_sources,
    )
    # Ensure unsearched items are never treated as hit-level searched coverage.
    for item in coverage.items:
        if item.status in {
            SourceCoverageStatus.NOT_SEARCHED,
            SourceCoverageStatus.UNSEARCHED_DECLARED,
            SourceCoverageStatus.MISSING,
        } and item.scored_as_searched:
            raise SourceCoverageReportError(
                f"source {item.source_id!r} incorrectly scored as searched"
            )

    source_errors = tuple(list(source_cov_errors) + list(citation_errors))
    return (
        metrics,
        source_errors,
        temporal_errors,
        citation_errors,
        coverage,
    )


def build_family_evaluation_v2(
    *,
    hits: Sequence[ExplainableHit | RankedHit],
    qrel_set: QrelSet,
    query_id: str,
    filters: PreRankingFilters,
    family: RetrievalFamily,
    binding: SnapshotBinding,
    thresholds: MetricThresholds,
    k: int | None = None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Iterable[str] = (),
    expected_denied_provider_calls: int | None = None,
    denied_result_count: int = 0,
    remote_embedding_calls: int = 0,
    unsearched_sources: Sequence[str] = (),
    declared_sources: Sequence[Mapping[str, Any] | str] = (),
    receipt_id: str | None = None,
    evaluated_at_utc: str | None = None,
    fail_loudly: bool = True,
    metadata: Mapping[str, str] | None = None,
) -> FamilyEvaluationV2:
    """Score hits, apply versioned thresholds, bind a v2 evaluation receipt."""
    require_pre_ranking_filters(filters)
    k_eff = int(k if k is not None else thresholds.k)
    (
        metrics,
        source_errors,
        temporal_errors,
        citation_errors,
        coverage,
    ) = score_explainable_ranking(
        hits=hits,
        qrel_set=qrel_set,
        query_id=query_id,
        filters=filters,
        family=family,
        k=k_eff,
        row_effective=row_effective,
        private_document_ids=private_document_ids,
        expected_denied_provider_calls=expected_denied_provider_calls,
        unsearched_sources=unsearched_sources,
        declared_sources=declared_sources,
    )
    if fail_loudly:
        annotated = assert_thresholds(metrics, thresholds)
    else:
        from .evaluation import apply_thresholds

        annotated = apply_thresholds(metrics, thresholds)

    denied = int(filters.denied_provider_call_count)
    if isinstance(hits[0], ExplainableHit) if hits else False:
        digest = ranking_digest_v2(hits)  # type: ignore[arg-type]
    else:
        digest = ranking_digest_v1(_hits_to_ranked(hits))

    ordered = tuple(
        h.document_id
        for h in sorted(hits, key=lambda x: (x.rank, x.document_id))
    )
    passed = all(m.passed is not False for m in annotated)
    # Isolation surface for public routes: zero denied calls/results.
    meta = {
        **(dict(metadata) if metadata else {}),
        "citation_error_count": str(len(citation_errors)),
        "query_id": query_id,
        "family": family.value,
        "missing_source_count": str(len(coverage.missing_source_ids)),
        "not_searched_count": str(len(coverage.not_searched_source_ids)),
    }
    receipt = EvaluationReceiptV2(
        schema_version=RETRIEVAL_EVAL_V2_SCHEMA_VERSION,
        receipt_id=receipt_id or f"eval-v2:{query_id}:{family.value}",
        snapshot_cid=binding.snapshot_cid,
        corpus_cid=binding.corpus_cid,
        model_cid=binding.model_cid,
        config_cid=binding.config_cid,
        qrels_cid=qrel_set.qrels_cid,
        metrics=annotated,
        filters=filters,
        index_cids=binding.index_cids,
        thresholds_cid=thresholds.thresholds_cid,
        family=family,
        evaluated_at_utc=evaluated_at_utc,
        source_errors=source_errors,
        temporal_errors=temporal_errors,
        citation_errors=citation_errors,
        denied_provider_call_count=denied,
        denied_result_count=int(denied_result_count),
        remote_embedding_calls=int(remote_embedding_calls),
        source_coverage_report=coverage,
        ranking_digest=digest,
        passed=passed,
        metadata=meta,
    )
    if fail_loudly and not passed:
        raise MetricThresholdError(
            f"evaluation receipt failed for family={family.value} "
            f"query={query_id!r}"
        )
    return FamilyEvaluationV2(
        family=family,
        metrics=annotated,
        source_errors=source_errors,
        temporal_errors=temporal_errors,
        citation_errors=citation_errors,
        hit_document_ids=ordered,
        ranking_digest=digest,
        denied_provider_call_count=denied,
        denied_result_count=int(denied_result_count),
        receipt=receipt,
        source_coverage_report=coverage,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class PatentRetrievalEvaluatorV2:
    """Evaluate explainable hybrid retrieval against versioned qrels_v2."""

    def __init__(
        self,
        fixture: EvaluationFixtureV2 | QrelSet | None = None,
        *,
        thresholds: MetricThresholds | None = None,
        latency_max_ms: float | None = None,
        private_document_ids: Sequence[str] = (),
        unsearched_sources: Sequence[str] = (),
        declared_sources: Sequence[Mapping[str, Any]] = (),
        fail_loudly: bool = True,
        families: Sequence[RetrievalFamily] | None = None,
    ) -> None:
        if fixture is None:
            loaded = load_evaluation_fixture_v2()
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
            self.unsearched_sources = tuple(
                unsearched_sources or loaded.unsearched_sources
            )
            self.declared_sources = tuple(
                declared_sources or loaded.declared_sources
            )
        elif isinstance(fixture, EvaluationFixtureV2):
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
            self.unsearched_sources = tuple(
                unsearched_sources or fixture.unsearched_sources
            )
            self.declared_sources = tuple(
                declared_sources or fixture.declared_sources
            )
        elif isinstance(fixture, QrelSet):
            self.fixture = None
            self.qrel_set = fixture
            self.thresholds = thresholds or MetricThresholds.default(
                thresholds_cid=DEFAULT_THRESHOLDS_V2_CID
            )
            self.latency_max_ms = float(
                latency_max_ms
                if latency_max_ms is not None
                else DEFAULT_LATENCY_MAX_MS
            )
            self.private_document_ids = tuple(private_document_ids)
            self.unsearched_sources = tuple(unsearched_sources)
            self.declared_sources = tuple(declared_sources)
        else:
            raise TypeError(
                "fixture must be EvaluationFixtureV2, QrelSet, or None"
            )

        if self.latency_max_ms <= 0.0:
            raise RetrievalEvalV2Error("latency_max_ms must be positive")
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
            self.families = self.families + (RetrievalFamily.FUSION,)

    @classmethod
    def from_fixture_path(
        cls, path: str | Path | None = None, **kwargs: Any
    ) -> "PatentRetrievalEvaluatorV2":
        return cls(load_evaluation_fixture_v2(path), **kwargs)

    def evaluate_hits(
        self,
        hits: Sequence[ExplainableHit | RankedHit],
        *,
        query_id: str,
        filters: PreRankingFilters,
        family: RetrievalFamily,
        binding: SnapshotBinding,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        expected_denied_provider_calls: int | None = None,
        denied_result_count: int = 0,
        remote_embedding_calls: int = 0,
        unsearched_sources: Sequence[str] | None = None,
        receipt_id: str | None = None,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> FamilyEvaluationV2:
        return build_family_evaluation_v2(
            hits=hits,
            qrel_set=self.qrel_set,
            query_id=query_id,
            filters=filters,
            family=family,
            binding=binding,
            thresholds=self.thresholds,
            k=self.thresholds.k,
            row_effective=row_effective,
            private_document_ids=self.private_document_ids,
            expected_denied_provider_calls=expected_denied_provider_calls,
            denied_result_count=denied_result_count,
            remote_embedding_calls=remote_embedding_calls,
            unsearched_sources=(
                self.unsearched_sources
                if unsearched_sources is None
                else unsearched_sources
            ),
            declared_sources=self.declared_sources,
            receipt_id=receipt_id,
            evaluated_at_utc=evaluated_at_utc,
            fail_loudly=self.fail_loudly,
            metadata=metadata,
        )

    def evaluate_search_result(
        self,
        result: HybridSearchResultV2,
        *,
        query_id: str | None = None,
        query: str | None = None,
        binding: SnapshotBinding | None = None,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        latency: LatencyMeasurement | None = None,
        second_result: HybridSearchResultV2 | None = None,
        expected_denied_provider_calls: int | None = None,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> QueryEvaluationResultV2:
        """Evaluate all configured families on one explainable search result."""
        qid = query_id or result.query_id
        qtext = query if query is not None else result.query
        bind = binding or result.binding
        filters = result.filters
        require_pre_ranking_filters(filters)

        denied = int(result.denied_provider_call_count)
        if filters.denied_provider_call_count != denied:
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

        unsearched = tuple(
            dict.fromkeys(
                list(self.unsearched_sources) + list(result.unsearched_sources)
            )
        )

        family_results: dict[str, FamilyEvaluationV2] = {}
        fused_eval: FamilyEvaluationV2 | None = None
        for family in self.families:
            if family is RetrievalFamily.FUSION:
                hits: Sequence[ExplainableHit] = result.hits
            elif family is RetrievalFamily.BM25:
                hits = result.bm25_hits
            elif family is RetrievalFamily.VECTOR:
                hits = result.vector_hits
            elif family is RetrievalFamily.GRAPH:
                hits = result.graph_hits
            else:
                raise RetrievalEvalV2Error(f"unsupported family {family!r}")
            fam_eval = self.evaluate_hits(
                hits,
                query_id=qid,
                filters=filters,
                family=family,
                binding=bind,
                row_effective=row_effective,
                expected_denied_provider_calls=expected_denied,
                denied_result_count=result.denied_result_count,
                remote_embedding_calls=result.remote_embedding_calls,
                unsearched_sources=unsearched,
                receipt_id=f"eval-v2:{qid}:{family.value}",
                evaluated_at_utc=evaluated_at_utc,
                metadata=metadata,
            )
            if family is RetrievalFamily.FUSION:
                fused_eval = fam_eval
            else:
                family_results[family.value] = fam_eval

        if fused_eval is None:
            raise RetrievalEvalV2Error("fusion family was not evaluated")

        primary_digest = fused_eval.ranking_digest
        if second_result is not None:
            second_digest = ranking_digest_v2(second_result.hits)
            reproducible = primary_digest == second_digest
            if self.fail_loudly and not reproducible:
                raise ReproducibilityV2Error(
                    f"fused ranking not reproducible for query={qid!r}: "
                    f"{primary_digest} != {second_digest}"
                )
            repro_digest = (
                primary_digest if reproducible else f"{primary_digest}:{second_digest}"
            )
        else:
            reproducible = True
            repro_digest = primary_digest

        if latency is None:
            latency = LatencyMeasurement(
                elapsed_ms=0.0,
                max_ms=self.latency_max_ms,
                label=f"search-v2:{qid}",
            )
        if self.fail_loudly:
            assert_latency_envelope(latency)

        # Receipt must bind snapshot/model/config/qrels.
        if fused_eval.receipt is not None:
            receipt = fused_eval.receipt
            for key, value in {
                "snapshot_cid": bind.snapshot_cid,
                "corpus_cid": bind.corpus_cid,
                "model_cid": bind.model_cid,
                "config_cid": bind.config_cid,
                "qrels_cid": self.qrel_set.qrels_cid,
            }.items():
                if receipt.binding_cids().get(key) != value:
                    raise RetrievalEvalV2Error(
                        f"receipt binding {key} mismatch: "
                        f"{receipt.binding_cids().get(key)!r} != {value!r}"
                    )

        coverage = fused_eval.source_coverage_report or build_source_coverage_report(
            result.hits,
            k=self.thresholds.k,
            unsearched_sources=unsearched,
            declared_sources=self.declared_sources,
        )

        all_family_pass = all(fr.passed for fr in family_results.values())
        passed = (
            fused_eval.passed
            and all_family_pass
            and reproducible
            and latency.passed
        )
        return QueryEvaluationResultV2(
            schema_version=RETRIEVAL_EVAL_V2_SCHEMA_VERSION,
            query_id=qid,
            query=qtext,
            family_results=MappingProxyType(family_results),
            fused=fused_eval,
            latency=latency,
            reproducibility_digest=repro_digest,
            reproducible=reproducible,
            denied_provider_call_count=denied,
            denied_result_count=int(result.denied_result_count),
            remote_embedding_calls=int(result.remote_embedding_calls),
            binding=bind,
            qrels_cid=self.qrel_set.qrels_cid,
            source_coverage_report=coverage,
            passed=passed,
            metadata=MappingProxyType(dict(metadata or {})),
        )

    def evaluate_query(
        self,
        *,
        query_id: str,
        query: str,
        retriever: HybridRetrievalV2 | None = None,
        bundle: PatentIndexBundle | None = None,
        filters: PreRankingFilters,
        top_k: int | None = None,
        component_weights: ComponentWeights | Mapping[str, float] | None = None,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        allow_remote_embeddings: bool = False,
        query_disclosure: DisclosureClass | str = DisclosureClass.PUBLIC_USER,
        seed_document_ids: Sequence[str] = (),
        expected_denied_provider_calls: int | None = None,
        check_reproducibility: bool = True,
        evaluated_at_utc: str | None = None,
        metadata: Mapping[str, str] | None = None,
        unsearched_sources: Sequence[str] | None = None,
        snapshot_cid: str | None = None,
    ) -> QueryEvaluationResultV2:
        """Run explainable hybrid search and score against qrels_v2."""
        require_pre_ranking_filters(filters)
        if retriever is None and bundle is None:
            raise RetrievalEvalV2Error("evaluate_query requires retriever or bundle")
        if retriever is None:
            assert bundle is not None
            retriever = HybridRetrievalV2.from_bundle(
                bundle, snapshot_cid=snapshot_cid
            )
        top = int(top_k if top_k is not None else self.thresholds.k)
        if isinstance(query_disclosure, str):
            query_disclosure = DisclosureClass(query_disclosure)
        weights: ComponentWeights | None
        if component_weights is None:
            weights = ComponentWeights()
        elif isinstance(component_weights, ComponentWeights):
            weights = component_weights
        else:
            weights = ComponentWeights.from_dict(component_weights)

        unsearched = (
            self.unsearched_sources
            if unsearched_sources is None
            else tuple(unsearched_sources)
        )
        request = HybridSearchRequestV2(
            query_id=query_id,
            query=query,
            filters=filters,
            top_k=top,
            component_weights=weights,
            seed_document_ids=tuple(seed_document_ids),
            allow_remote_embeddings=allow_remote_embeddings,
            query_disclosure=query_disclosure,
            unsearched_sources=unsearched,
        )

        t0 = time.perf_counter()
        first = retriever.search(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        second: HybridSearchResultV2 | None = None
        if check_reproducibility:
            second = retriever.search(request)

        latency = LatencyMeasurement(
            elapsed_ms=elapsed_ms,
            max_ms=self.latency_max_ms,
            label=f"search-v2:{query_id}",
        )

        if row_effective is None:
            from .retrieval_eval import row_effective_from_bundle

            row_effective = row_effective_from_bundle(retriever.bundle)

        return self.evaluate_search_result(
            first,
            query_id=query_id,
            query=query,
            binding=retriever.binding,
            row_effective=row_effective,
            latency=latency,
            second_result=second,
            expected_denied_provider_calls=expected_denied_provider_calls,
            evaluated_at_utc=evaluated_at_utc,
            metadata=metadata,
        )

    def evaluate_degraded(
        self,
        result: HybridSearchResultV2,
        *,
        query_id: str | None = None,
        drop_top_n: int = 1,
        row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
        evaluated_at_utc: str | None = None,
    ) -> None:
        """Assert versioned thresholds fail on intentionally degraded retrieval.

        Raises :class:`MetricThresholdError` when thresholds are enforced.
        """
        qid = query_id or result.query_id
        degraded_hits = degrade_ranking(result.hits, drop_top_n=drop_top_n)
        # Soften thresholds path: force fail_loudly on this evaluator instance
        # for the degraded ranking.
        build_family_evaluation_v2(
            hits=degraded_hits,
            qrel_set=self.qrel_set,
            query_id=qid,
            filters=result.filters,
            family=RetrievalFamily.FUSION,
            binding=result.binding,
            thresholds=self.thresholds,
            k=self.thresholds.k,
            row_effective=row_effective,
            private_document_ids=self.private_document_ids,
            expected_denied_provider_calls=result.denied_provider_call_count,
            denied_result_count=result.denied_result_count,
            remote_embedding_calls=result.remote_embedding_calls,
            unsearched_sources=self.unsearched_sources,
            declared_sources=self.declared_sources,
            receipt_id=f"eval-v2-degraded:{qid}:fusion",
            evaluated_at_utc=evaluated_at_utc,
            fail_loudly=True,
            metadata={"degraded": "1"},
        )


def evaluate_hybrid_v2_against_qrels(
    *,
    retriever: HybridRetrievalV2 | None = None,
    bundle: PatentIndexBundle | None = None,
    qrel_set: QrelSet | EvaluationFixtureV2 | str | Path,
    query_id: str,
    query: str,
    filters: PreRankingFilters,
    thresholds: MetricThresholds | None = None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    private_document_ids: Sequence[str] = (),
    fail_loudly: bool = True,
    **kwargs: Any,
) -> QueryEvaluationResultV2:
    """Functional entry point: score one explainable hybrid query against qrels_v2."""
    if isinstance(qrel_set, EvaluationFixtureV2):
        evaluator = PatentRetrievalEvaluatorV2(
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
            else load_qrel_set_v2(qrel_set)
        )
        evaluator = PatentRetrievalEvaluatorV2(
            loaded,
            thresholds=thresholds,
            private_document_ids=private_document_ids,
            fail_loudly=fail_loudly,
        )
    return evaluator.evaluate_query(
        query_id=query_id,
        query=query,
        retriever=retriever,
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
        filter_receipt_id="filter:eval-v2-gold",
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
    "DEFAULT_QRELS_V2_CID",
    "DEFAULT_THRESHOLDS_V2_CID",
    "FIXTURE_V2_SCHEMA_VERSION",
    "RETRIEVAL_EVAL_V2_INTERFACE",
    "RETRIEVAL_EVAL_V2_SCHEMA_VERSION",
    "EvaluationFixtureV2",
    "EvaluationReceiptV2",
    "FamilyEvaluationV2",
    "PatentRetrievalEvaluatorV2",
    "QueryEvaluationResultV2",
    "ReproducibilityV2Error",
    "RetrievalEvalV2Error",
    "SourceCoverageItem",
    "SourceCoverageReport",
    "SourceCoverageReportError",
    "SourceCoverageStatus",
    "build_bundle_from_gold_corpus",
    "build_family_evaluation_v2",
    "build_source_coverage_report",
    "default_fixture_v2_path",
    "default_gold_corpus_path",
    "evaluate_hybrid_v2_against_qrels",
    "load_evaluation_fixture_v2",
    "load_qrel_set_v2",
    "score_explainable_ranking",
]
