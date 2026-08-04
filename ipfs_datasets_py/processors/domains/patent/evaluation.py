"""Patent retrieval evaluation contracts: qrels, metrics, and receipts.

Evaluation is deliberately separate from concrete harness I/O (PATLAW-093).
This module freezes:

* relevance judgments (qrels) with optional citation and temporal expectations;
* metric kinds covering recall, ranking, citation grounding, temporal accuracy,
  source coverage, and private isolation;
* evaluation receipts that bind corpus / model / config / qrels CIDs; and
* scoring helpers that refuse to run without applied disclosure / tenant /
  as-of pre-ranking filters.

No network I/O, index builders, or package re-exports live here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    _cid,
    _finite_float,
    _frozen_str_map,
    _identifier,
    _iso_utc,
    _mapping,
    _nonneg_float,
    _nonneg_int,
    _optional_cid,
    _optional_float_01,
    _optional_iso_utc,
    _optional_str,
    _positive_int,
    _reject_unknown,
    _require_str,
    _schema_pinned,
    _sha256_hex,
    _tuple_of_str,
    canonical_json,
    require_pre_ranking_filters,
)

EVALUATION_SCHEMA_VERSION: Final = "patent.retrieval.evaluation.v1"
EVALUATION_INTERFACE: Final = "PatentRetrievalEvaluation@1"

# Re-export for consumers that only import evaluation.
SCHEMA_VERSION: Final = EVALUATION_SCHEMA_VERSION


class EvaluationError(ValueError):
    """Base error for evaluation contract violations."""


class MetricThresholdError(EvaluationError):
    """Raised when a measured metric fails a versioned threshold."""


class RelevanceGrade(str, Enum):
    """Closed graded relevance scale for patent retrieval qrels."""

    NOT_RELEVANT = "not_relevant"
    PARTIAL = "partial"
    RELEVANT = "relevant"
    EXACT = "exact"


_GRADE_SCORE: Final[Mapping[RelevanceGrade, int]] = MappingProxyType(
    {
        RelevanceGrade.NOT_RELEVANT: 0,
        RelevanceGrade.PARTIAL: 1,
        RelevanceGrade.RELEVANT: 2,
        RelevanceGrade.EXACT: 3,
    }
)


class MetricKind(str, Enum):
    """Required evaluation metric families (PATLAW-090 acceptance)."""

    RECALL = "recall"
    RANKING = "ranking"
    CITATION = "citation"
    TEMPORAL = "temporal"
    SOURCE_COVERAGE = "source_coverage"
    PRIVATE_ISOLATION = "private_isolation"


REQUIRED_METRIC_KINDS: Final[frozenset[MetricKind]] = frozenset(MetricKind)


@dataclass(frozen=True, slots=True)
class Qrel:
    """One query–document relevance judgment."""

    query_id: str
    document_id: str
    grade: RelevanceGrade
    expected_citation: str | None = None
    expected_as_of_utc: str | None = None
    expected_source_cids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "grade", _coerce_grade(self.grade)
        )
        object.__setattr__(
            self,
            "expected_citation",
            _optional_str(self.expected_citation, "expected_citation", max_len=512),
        )
        object.__setattr__(
            self,
            "expected_as_of_utc",
            _optional_iso_utc(self.expected_as_of_utc, "expected_as_of_utc"),
        )
        cids: list[str] = []
        for i, raw in enumerate(self.expected_source_cids or ()):
            cids.append(_cid(raw, f"expected_source_cids[{i}]"))
        object.__setattr__(self, "expected_source_cids", tuple(cids))
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=16)
        )

    @property
    def is_relevant(self) -> bool:
        return _GRADE_SCORE[self.grade] >= _GRADE_SCORE[RelevanceGrade.RELEVANT]

    @property
    def grade_score(self) -> int:
        return _GRADE_SCORE[self.grade]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "expected_as_of_utc": self.expected_as_of_utc,
            "expected_citation": self.expected_citation,
            "expected_source_cids": list(self.expected_source_cids),
            "grade": self.grade.value,
            "notes": list(self.notes),
            "query_id": self.query_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Qrel":
        value = _mapping(value, "Qrel")
        _reject_unknown(
            value,
            frozenset(
                {
                    "query_id",
                    "document_id",
                    "grade",
                    "expected_citation",
                    "expected_as_of_utc",
                    "expected_source_cids",
                    "notes",
                }
            ),
            "Qrel",
        )
        return cls(
            query_id=value.get("query_id", ""),
            document_id=value.get("document_id", ""),
            grade=value.get("grade", RelevanceGrade.NOT_RELEVANT.value),
            expected_citation=value.get("expected_citation"),
            expected_as_of_utc=value.get("expected_as_of_utc"),
            expected_source_cids=tuple(value.get("expected_source_cids") or ()),
            notes=tuple(value.get("notes") or ()),
        )


def _coerce_grade(value: Any) -> RelevanceGrade:
    if isinstance(value, RelevanceGrade):
        return value
    if isinstance(value, str):
        try:
            return RelevanceGrade(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid relevance grade: {value!r}") from exc
    if isinstance(value, int) and not isinstance(value, bool):
        for grade, score in _GRADE_SCORE.items():
            if score == value:
                return grade
        raise ValueError(f"invalid relevance grade score: {value!r}")
    raise TypeError(f"grade must be RelevanceGrade, str, or int, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class QrelSet:
    """Versioned collection of qrels with a content identifier binding."""

    schema_version: str
    qrels_cid: str
    judgments: tuple[Qrel, ...]
    corpus_cid: str | None = None
    description: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(self.schema_version, EVALUATION_SCHEMA_VERSION, "QrelSet"),
        )
        object.__setattr__(self, "qrels_cid", _cid(self.qrels_cid, "qrels_cid"))
        if not isinstance(self.judgments, Sequence) or isinstance(
            self.judgments, (str, bytes)
        ):
            raise TypeError("judgments must be a sequence of Qrel")
        out: list[Qrel] = []
        seen: set[tuple[str, str]] = set()
        for i, item in enumerate(self.judgments):
            if isinstance(item, Qrel):
                qrel = item
            elif isinstance(item, Mapping):
                qrel = Qrel.from_dict(item)
            else:
                raise TypeError(f"judgments[{i}] must be Qrel or mapping")
            key = (qrel.query_id, qrel.document_id)
            if key in seen:
                raise ValueError(
                    f"duplicate qrel for query={qrel.query_id!r} "
                    f"document={qrel.document_id!r}"
                )
            seen.add(key)
            out.append(qrel)
        if not out:
            raise ValueError("QrelSet.judgments must be non-empty")
        object.__setattr__(
            self,
            "judgments",
            tuple(sorted(out, key=lambda q: (q.query_id, q.document_id))),
        )
        object.__setattr__(
            self, "corpus_cid", _optional_cid(self.corpus_cid, "corpus_cid")
        )
        object.__setattr__(
            self,
            "description",
            _optional_str(self.description, "description", max_len=1024),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def for_query(self, query_id: str) -> tuple[Qrel, ...]:
        qid = _identifier(query_id, "query_id")
        return tuple(q for q in self.judgments if q.query_id == qid)

    def relevant_document_ids(self, query_id: str) -> frozenset[str]:
        return frozenset(q.document_id for q in self.for_query(query_id) if q.is_relevant)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_cid": self.corpus_cid,
            "description": self.description,
            "judgments": [j.to_dict() for j in self.judgments],
            "metadata": dict(self.metadata),
            "qrels_cid": self.qrels_cid,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QrelSet":
        value = _mapping(value, "QrelSet")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "qrels_cid",
                    "judgments",
                    "corpus_cid",
                    "description",
                    "metadata",
                }
            ),
            "QrelSet",
        )
        return cls(
            schema_version=value.get("schema_version", EVALUATION_SCHEMA_VERSION),
            qrels_cid=value.get("qrels_cid", ""),
            judgments=tuple(value.get("judgments") or ()),
            corpus_cid=value.get("corpus_cid"),
            description=value.get("description"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class MetricScore:
    """One measured metric with optional diagnostic payload."""

    kind: MetricKind
    value: float
    k: int | None = None
    family: RetrievalFamily | None = None
    details: Mapping[str, str] = MappingProxyType({})
    passed: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _coerce_metric_kind(self.kind)
        )
        object.__setattr__(self, "value", _finite_float(self.value, "value"))
        if self.k is not None:
            object.__setattr__(self, "k", _positive_int(self.k, "k"))
        if self.family is not None:
            if isinstance(self.family, RetrievalFamily):
                family = self.family
            else:
                family = RetrievalFamily(str(self.family).strip())
            object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "details", _frozen_str_map(self.details, "details", max_items=64)
        )
        if self.passed is not None and not isinstance(self.passed, bool):
            raise TypeError("passed must be bool or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "details": dict(self.details),
            "family": None if self.family is None else self.family.value,
            "k": self.k,
            "kind": self.kind.value,
            "passed": self.passed,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MetricScore":
        value = _mapping(value, "MetricScore")
        _reject_unknown(
            value,
            frozenset({"kind", "value", "k", "family", "details", "passed"}),
            "MetricScore",
        )
        family_raw = value.get("family")
        return cls(
            kind=value.get("kind", ""),
            value=value.get("value", 0.0),
            k=value.get("k"),
            family=None if family_raw is None else family_raw,
            details=value.get("details") or {},
            passed=value.get("passed"),
        )


def _coerce_metric_kind(value: Any) -> MetricKind:
    if isinstance(value, MetricKind):
        return value
    if isinstance(value, str):
        try:
            return MetricKind(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid metric kind: {value!r}") from exc
    raise TypeError(f"kind must be MetricKind or str, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class MetricThresholds:
    """Versioned minimum thresholds; regressions fail loudly."""

    schema_version: str
    thresholds_cid: str
    minima: Mapping[str, float]
    k: int = 10

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, EVALUATION_SCHEMA_VERSION, "MetricThresholds"
            ),
        )
        object.__setattr__(
            self, "thresholds_cid", _cid(self.thresholds_cid, "thresholds_cid")
        )
        if not isinstance(self.minima, Mapping):
            raise TypeError("minima must be a mapping")
        out: dict[str, float] = {}
        for key, raw in self.minima.items():
            kind = _coerce_metric_kind(key)
            out[kind.value] = _nonneg_float(raw, f"minima[{kind.value}]")
            if out[kind.value] > 1.0 and kind is not MetricKind.PRIVATE_ISOLATION:
                # Isolation may count denied calls as absolute; others are [0,1].
                raise ValueError(
                    f"minima[{kind.value}] must be in [0.0, 1.0] for ratio metrics"
                )
        missing = {m.value for m in REQUIRED_METRIC_KINDS} - set(out)
        if missing:
            raise ValueError(
                "MetricThresholds.minima missing required kinds: "
                + ", ".join(sorted(missing))
            )
        object.__setattr__(self, "minima", MappingProxyType(dict(sorted(out.items()))))
        object.__setattr__(self, "k", _positive_int(self.k, "k"))

    def minimum_for(self, kind: MetricKind | str) -> float:
        key = _coerce_metric_kind(kind).value
        return float(self.minima[key])

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "minima": dict(self.minima),
            "schema_version": self.schema_version,
            "thresholds_cid": self.thresholds_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MetricThresholds":
        value = _mapping(value, "MetricThresholds")
        _reject_unknown(
            value,
            frozenset({"schema_version", "thresholds_cid", "minima", "k"}),
            "MetricThresholds",
        )
        return cls(
            schema_version=value.get("schema_version", EVALUATION_SCHEMA_VERSION),
            thresholds_cid=value.get("thresholds_cid", ""),
            minima=value.get("minima") or {},
            k=value.get("k", 10),
        )

    @classmethod
    def default(cls, *, thresholds_cid: str) -> "MetricThresholds":
        return cls(
            schema_version=EVALUATION_SCHEMA_VERSION,
            thresholds_cid=thresholds_cid,
            minima={
                MetricKind.RECALL.value: 0.5,
                MetricKind.RANKING.value: 0.4,
                MetricKind.CITATION.value: 0.5,
                MetricKind.TEMPORAL.value: 0.5,
                MetricKind.SOURCE_COVERAGE.value: 1.0,
                MetricKind.PRIVATE_ISOLATION.value: 1.0,
            },
            k=10,
        )


@dataclass(frozen=True, slots=True)
class EvaluationReceipt:
    """Immutable evaluation receipt binding corpus/model/config/qrels CIDs."""

    schema_version: str
    receipt_id: str
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
    denied_provider_call_count: int = 0
    passed: bool = False
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, EVALUATION_SCHEMA_VERSION, "EvaluationReceipt"
            ),
        )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(self, "corpus_cid", _cid(self.corpus_cid, "corpus_cid"))
        object.__setattr__(self, "model_cid", _cid(self.model_cid, "model_cid"))
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(self, "qrels_cid", _cid(self.qrels_cid, "qrels_cid"))
        if not isinstance(self.metrics, Sequence) or isinstance(
            self.metrics, (str, bytes)
        ):
            raise TypeError("metrics must be a sequence of MetricScore")
        metrics_out: list[MetricScore] = []
        kinds_seen: set[MetricKind] = set()
        for i, item in enumerate(self.metrics):
            if isinstance(item, MetricScore):
                metric = item
            elif isinstance(item, Mapping):
                metric = MetricScore.from_dict(item)
            else:
                raise TypeError(f"metrics[{i}] must be MetricScore or mapping")
            metrics_out.append(metric)
            kinds_seen.add(metric.kind)
        missing = REQUIRED_METRIC_KINDS - kinds_seen
        if missing:
            raise ValueError(
                "EvaluationReceipt.metrics must cover all required kinds; missing: "
                + ", ".join(sorted(m.value for m in missing))
            )
        object.__setattr__(self, "metrics", tuple(metrics_out))
        if isinstance(self.filters, Mapping):
            object.__setattr__(
                self, "filters", PreRankingFilters.from_dict(self.filters)
            )
        elif not isinstance(self.filters, PreRankingFilters):
            raise TypeError("filters must be PreRankingFilters or mapping")
        require_pre_ranking_filters(self.filters)
        object.__setattr__(
            self,
            "index_cids",
            _frozen_str_map(self.index_cids, "index_cids", max_items=16),
        )
        object.__setattr__(
            self,
            "thresholds_cid",
            _optional_cid(self.thresholds_cid, "thresholds_cid"),
        )
        if self.family is not None:
            if isinstance(self.family, RetrievalFamily):
                family = self.family
            else:
                family = RetrievalFamily(str(self.family).strip())
            object.__setattr__(self, "family", family)
        object.__setattr__(
            self,
            "evaluated_at_utc",
            _optional_iso_utc(self.evaluated_at_utc, "evaluated_at_utc"),
        )
        object.__setattr__(
            self,
            "source_errors",
            _tuple_of_str(self.source_errors, "source_errors", max_items=256),
        )
        object.__setattr__(
            self,
            "temporal_errors",
            _tuple_of_str(self.temporal_errors, "temporal_errors", max_items=256),
        )
        object.__setattr__(
            self,
            "denied_provider_call_count",
            _nonneg_int(
                self.denied_provider_call_count, "denied_provider_call_count"
            ),
        )
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be bool")
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )

    def metric(self, kind: MetricKind | str) -> MetricScore:
        target = _coerce_metric_kind(kind)
        for item in self.metrics:
            if item.kind is target:
                return item
        raise KeyError(f"no metric for kind {target.value}")

    def binding_cids(self) -> Mapping[str, str]:
        """Return the corpus/model/config/qrels CID binding map."""
        return MappingProxyType(
            {
                "corpus_cid": self.corpus_cid,
                "model_cid": self.model_cid,
                "config_cid": self.config_cid,
                "qrels_cid": self.qrels_cid,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "corpus_cid": self.corpus_cid,
            "denied_provider_call_count": self.denied_provider_call_count,
            "evaluated_at_utc": self.evaluated_at_utc,
            "family": None if self.family is None else self.family.value,
            "filters": self.filters.to_dict(),
            "index_cids": dict(self.index_cids),
            "metadata": dict(self.metadata),
            "metrics": [m.to_dict() for m in self.metrics],
            "model_cid": self.model_cid,
            "passed": self.passed,
            "qrels_cid": self.qrels_cid,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "source_errors": list(self.source_errors),
            "temporal_errors": list(self.temporal_errors),
            "thresholds_cid": self.thresholds_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationReceipt":
        value = _mapping(value, "EvaluationReceipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "receipt_id",
                    "corpus_cid",
                    "model_cid",
                    "config_cid",
                    "qrels_cid",
                    "metrics",
                    "filters",
                    "index_cids",
                    "thresholds_cid",
                    "family",
                    "evaluated_at_utc",
                    "source_errors",
                    "temporal_errors",
                    "denied_provider_call_count",
                    "passed",
                    "metadata",
                }
            ),
            "EvaluationReceipt",
        )
        family_raw = value.get("family")
        return cls(
            schema_version=value.get("schema_version", EVALUATION_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
            corpus_cid=value.get("corpus_cid", ""),
            model_cid=value.get("model_cid", ""),
            config_cid=value.get("config_cid", ""),
            qrels_cid=value.get("qrels_cid", ""),
            metrics=tuple(value.get("metrics") or ()),
            filters=value.get("filters") or {},
            index_cids=value.get("index_cids") or {},
            thresholds_cid=value.get("thresholds_cid"),
            family=None if family_raw is None else family_raw,
            evaluated_at_utc=value.get("evaluated_at_utc"),
            source_errors=tuple(value.get("source_errors") or ()),
            temporal_errors=tuple(value.get("temporal_errors") or ()),
            denied_provider_call_count=int(
                value.get("denied_provider_call_count", 0) or 0
            ),
            passed=bool(value.get("passed", False)),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Metric computations (filters mandatory)
# ---------------------------------------------------------------------------


def _ranked_doc_ids(hits: Sequence[RankedHit], *, k: int | None = None) -> list[str]:
    ordered = sorted(hits, key=lambda h: (h.rank, -h.score, h.document_id))
    docs = [h.document_id for h in ordered]
    if k is not None:
        return docs[:k]
    return docs


def compute_recall_at_k(
    hits: Sequence[RankedHit],
    relevant_ids: Iterable[str],
    *,
    k: int,
    filters: PreRankingFilters | None,
) -> MetricScore:
    require_pre_ranking_filters(filters)
    k = _positive_int(k, "k")
    relevant = frozenset(_identifier(r, "relevant_id") for r in relevant_ids)
    if not relevant:
        return MetricScore(
            kind=MetricKind.RECALL,
            value=1.0,
            k=k,
            details={"note": "no_relevant_documents"},
        )
    retrieved = set(_ranked_doc_ids(hits, k=k))
    hit_count = len(retrieved & relevant)
    value = hit_count / float(len(relevant))
    return MetricScore(
        kind=MetricKind.RECALL,
        value=value,
        k=k,
        details={
            "relevant_count": str(len(relevant)),
            "hit_count": str(hit_count),
        },
    )


def compute_ndcg_at_k(
    hits: Sequence[RankedHit],
    grades: Mapping[str, int],
    *,
    k: int,
    filters: PreRankingFilters | None,
) -> MetricScore:
    """Normalized discounted cumulative gain at *k* (ranking metric)."""
    require_pre_ranking_filters(filters)
    k = _positive_int(k, "k")
    if not grades:
        return MetricScore(
            kind=MetricKind.RANKING,
            value=1.0,
            k=k,
            details={"note": "empty_grades"},
        )

    def dcg(doc_ids: Sequence[str]) -> float:
        total = 0.0
        for i, doc in enumerate(doc_ids[:k], start=1):
            rel = float(grades.get(doc, 0))
            if rel <= 0:
                continue
            total += (2.0**rel - 1.0) / math.log2(i + 1.0)
        return total

    retrieved = _ranked_doc_ids(hits, k=k)
    actual = dcg(retrieved)
    ideal_docs = sorted(grades.keys(), key=lambda d: (-grades[d], d))
    ideal = dcg(ideal_docs)
    value = 0.0 if ideal <= 0.0 else actual / ideal
    return MetricScore(
        kind=MetricKind.RANKING,
        value=value,
        k=k,
        details={"dcg": f"{actual:.6f}", "idcg": f"{ideal:.6f}"},
    )


def compute_citation_grounding(
    hits: Sequence[RankedHit],
    qrels: Sequence[Qrel],
    *,
    k: int,
    filters: PreRankingFilters | None,
) -> tuple[MetricScore, tuple[str, ...]]:
    """Fraction of top-k relevant hits whose source links cover expected citations."""
    require_pre_ranking_filters(filters)
    k = _positive_int(k, "k")
    expectations = {
        q.document_id: q
        for q in qrels
        if q.is_relevant and (q.expected_citation or q.expected_source_cids)
    }
    if not expectations:
        return (
            MetricScore(
                kind=MetricKind.CITATION,
                value=1.0,
                k=k,
                details={"note": "no_citation_expectations"},
            ),
            (),
        )

    top = {h.document_id: h for h in sorted(hits, key=lambda x: x.rank)[:k]}
    errors: list[str] = []
    matched = 0
    checked = 0
    for doc_id, qrel in expectations.items():
        if doc_id not in top:
            continue
        checked += 1
        hit = top[doc_id]
        source_cids = {link.source_cid for link in hit.source_links}
        ok = True
        if qrel.expected_source_cids:
            missing = set(qrel.expected_source_cids) - source_cids
            if missing:
                ok = False
                errors.append(
                    f"doc={doc_id}: missing source CIDs {sorted(missing)}"
                )
        if qrel.expected_citation:
            # Citation string must appear in any source link artifact id or metadata path.
            citation = qrel.expected_citation
            artifact_ids = {link.artifact_id for link in hit.source_links}
            if citation not in artifact_ids and citation not in source_cids:
                # Soft check: require SOURCE_BOUND authority when citation expected.
                if hit.authority_claim is not AuthorityClaim.SOURCE_BOUND:
                    ok = False
                    errors.append(
                        f"doc={doc_id}: citation {citation!r} not source-bound"
                    )
        if ok:
            matched += 1
    value = 1.0 if checked == 0 else matched / float(checked)
    return (
        MetricScore(
            kind=MetricKind.CITATION,
            value=value,
            k=k,
            details={"checked": str(checked), "matched": str(matched)},
        ),
        tuple(errors),
    )


def compute_temporal_accuracy(
    hits: Sequence[RankedHit],
    qrels: Sequence[Qrel],
    *,
    as_of_utc: str,
    k: int,
    filters: PreRankingFilters | None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> tuple[MetricScore, tuple[str, ...]]:
    """Share of top-k hits whose effective interval covers query as-of.

    ``row_effective`` maps document_id → (effective_from_utc, effective_to_utc).
    When absent, only qrel ``expected_as_of_utc`` consistency is scored.
    """
    require_pre_ranking_filters(filters)
    k = _positive_int(k, "k")
    as_of = _iso_utc(as_of_utc, "as_of_utc")
    if as_of != filters.as_of_utc:
        raise EvaluationError(
            f"scoring as_of_utc {as_of!r} must match filters.as_of_utc "
            f"{filters.as_of_utc!r}"
        )
    row_effective = row_effective or {}
    top_docs = _ranked_doc_ids(hits, k=k)
    if not top_docs:
        return (
            MetricScore(
                kind=MetricKind.TEMPORAL,
                value=1.0,
                k=k,
                details={"note": "empty_hits"},
            ),
            (),
        )

    errors: list[str] = []
    ok_count = 0
    for doc in top_docs:
        interval = row_effective.get(doc)
        qrel_as_of = None
        for q in qrels:
            if q.document_id == doc and q.expected_as_of_utc:
                qrel_as_of = q.expected_as_of_utc
                break
        if interval is None and qrel_as_of is None:
            ok_count += 1
            continue
        good = True
        if interval is not None:
            start, end = interval
            if start is not None and as_of < _iso_utc(start, "effective_from_utc"):
                good = False
                errors.append(f"doc={doc}: as-of before effective_from")
            if end is not None and as_of > _iso_utc(end, "effective_to_utc"):
                good = False
                errors.append(f"doc={doc}: as-of after effective_to")
        if qrel_as_of is not None and qrel_as_of != as_of:
            # Judgment is for a different as-of; treat as temporal mismatch when
            # the document was retrieved under a different temporal query.
            good = False
            errors.append(
                f"doc={doc}: qrel expected_as_of {qrel_as_of!r} != query {as_of!r}"
            )
        if good:
            ok_count += 1
    value = ok_count / float(len(top_docs))
    return (
        MetricScore(
            kind=MetricKind.TEMPORAL,
            value=value,
            k=k,
            details={"checked": str(len(top_docs)), "ok": str(ok_count)},
        ),
        tuple(errors),
    )


def compute_source_coverage(
    hits: Sequence[RankedHit],
    *,
    k: int,
    filters: PreRankingFilters | None,
) -> tuple[MetricScore, tuple[str, ...]]:
    """Fraction of top-k hits that carry at least one source CID link."""
    require_pre_ranking_filters(filters)
    k = _positive_int(k, "k")
    top = sorted(hits, key=lambda h: h.rank)[:k]
    if not top:
        return (
            MetricScore(
                kind=MetricKind.SOURCE_COVERAGE,
                value=1.0,
                k=k,
                details={"note": "empty_hits"},
            ),
            (),
        )
    errors: list[str] = []
    covered = 0
    for hit in top:
        if hit.source_links and all(link.source_cid for link in hit.source_links):
            covered += 1
        else:
            errors.append(f"doc={hit.document_id}: missing source links")
    value = covered / float(len(top))
    return (
        MetricScore(
            kind=MetricKind.SOURCE_COVERAGE,
            value=value,
            k=k,
            details={"covered": str(covered), "total": str(len(top))},
        ),
        tuple(errors),
    )


def compute_private_isolation(
    *,
    filters: PreRankingFilters | None,
    expected_denied_provider_calls: int | None = None,
    leaked_private_document_ids: Iterable[str] = (),
) -> MetricScore:
    """Private isolation score.

    Score is 1.0 only when:

    * filters were applied;
    * no private documents leaked into scored results; and
    * when ``expected_denied_provider_calls`` is provided, the filters'
      ``denied_provider_call_count`` matches (records that private routes
      made zero remote calls by counting denials).
    """
    require_pre_ranking_filters(filters)
    assert filters is not None
    leaks = [
        _identifier(doc, "leaked_private_document_id")
        for doc in leaked_private_document_ids
    ]
    details = {
        "denied_provider_call_count": str(filters.denied_provider_call_count),
        "leaked_count": str(len(leaks)),
    }
    ok = len(leaks) == 0
    if expected_denied_provider_calls is not None:
        expected = _nonneg_int(
            expected_denied_provider_calls, "expected_denied_provider_calls"
        )
        details["expected_denied_provider_calls"] = str(expected)
        if filters.denied_provider_call_count != expected:
            ok = False
    if leaks:
        details["leaked"] = ",".join(leaks[:16])
    return MetricScore(
        kind=MetricKind.PRIVATE_ISOLATION,
        value=1.0 if ok else 0.0,
        details=details,
        passed=ok,
    )


def evaluate_ranking(
    *,
    hits: Sequence[RankedHit],
    qrel_set: QrelSet,
    query_id: str,
    filters: PreRankingFilters,
    k: int = 10,
    family: RetrievalFamily | None = None,
    row_effective: Mapping[str, tuple[str | None, str | None]] | None = None,
    leaked_private_document_ids: Iterable[str] = (),
    expected_denied_provider_calls: int | None = None,
) -> tuple[MetricScore, ...]:
    """Compute the full required metric suite for one query ranking.

    Fails closed if disclosure/tenant/as-of filters were not applied.
    """
    require_pre_ranking_filters(filters)
    qrels = qrel_set.for_query(query_id)
    relevant = qrel_set.relevant_document_ids(query_id)
    grades = {q.document_id: q.grade_score for q in qrels}

    recall = compute_recall_at_k(hits, relevant, k=k, filters=filters)
    ranking = compute_ndcg_at_k(hits, grades, k=k, filters=filters)
    citation, _ = compute_citation_grounding(hits, qrels, k=k, filters=filters)
    temporal, _ = compute_temporal_accuracy(
        hits,
        qrels,
        as_of_utc=filters.as_of_utc,
        k=k,
        filters=filters,
        row_effective=row_effective,
    )
    source_cov, _ = compute_source_coverage(hits, k=k, filters=filters)
    isolation = compute_private_isolation(
        filters=filters,
        expected_denied_provider_calls=expected_denied_provider_calls,
        leaked_private_document_ids=leaked_private_document_ids,
    )

    metrics = (recall, ranking, citation, temporal, source_cov, isolation)
    if family is not None:
        fam = (
            family
            if isinstance(family, RetrievalFamily)
            else RetrievalFamily(str(family).strip())
        )
        metrics = tuple(
            MetricScore(
                kind=m.kind,
                value=m.value,
                k=m.k,
                family=fam,
                details=dict(m.details),
                passed=m.passed,
            )
            for m in metrics
        )
    return metrics


def apply_thresholds(
    metrics: Sequence[MetricScore],
    thresholds: MetricThresholds,
) -> tuple[MetricScore, ...]:
    """Annotate metrics with pass/fail against versioned minima."""
    out: list[MetricScore] = []
    for metric in metrics:
        minimum = thresholds.minimum_for(metric.kind)
        # PRIVATE_ISOLATION minimum is a ratio; value already 0/1.
        passed = metric.value + 1e-12 >= minimum
        out.append(
            MetricScore(
                kind=metric.kind,
                value=metric.value,
                k=metric.k,
                family=metric.family,
                details={
                    **dict(metric.details),
                    "threshold": f"{minimum:.6f}",
                },
                passed=passed,
            )
        )
    return tuple(out)


def assert_thresholds(
    metrics: Sequence[MetricScore],
    thresholds: MetricThresholds,
) -> tuple[MetricScore, ...]:
    """Apply thresholds and raise if any required metric fails."""
    annotated = apply_thresholds(metrics, thresholds)
    failures = [m for m in annotated if m.passed is False]
    if failures:
        detail = ", ".join(
            f"{m.kind.value}={m.value:.4f}<{thresholds.minimum_for(m.kind):.4f}"
            for m in failures
        )
        raise MetricThresholdError(f"metric threshold regression: {detail}")
    return annotated


def build_evaluation_receipt(
    *,
    receipt_id: str,
    corpus_cid: str,
    model_cid: str,
    config_cid: str,
    qrels_cid: str,
    metrics: Sequence[MetricScore],
    filters: PreRankingFilters,
    index_cids: Mapping[str, str] | None = None,
    thresholds: MetricThresholds | None = None,
    family: RetrievalFamily | None = None,
    evaluated_at_utc: str | None = None,
    source_errors: Sequence[str] = (),
    temporal_errors: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
) -> EvaluationReceipt:
    """Construct a receipt; filters must already be applied.

    When *thresholds* are supplied, metrics are annotated and overall
    ``passed`` reflects full threshold satisfaction.
    """
    require_pre_ranking_filters(filters)
    scored: Sequence[MetricScore] = tuple(metrics)
    if thresholds is not None:
        scored = apply_thresholds(scored, thresholds)
    passed = all(m.passed is not False for m in scored) and all(
        m.kind in {x.kind for x in scored} for m in scored
    )
    # Require every kind present and none explicitly failed.
    kinds = {m.kind for m in scored}
    if kinds != REQUIRED_METRIC_KINDS:
        passed = False
    if any(m.passed is False for m in scored):
        passed = False

    return EvaluationReceipt(
        schema_version=EVALUATION_SCHEMA_VERSION,
        receipt_id=receipt_id,
        corpus_cid=corpus_cid,
        model_cid=model_cid,
        config_cid=config_cid,
        qrels_cid=qrels_cid,
        metrics=tuple(scored),
        filters=filters,
        index_cids=index_cids or {},
        thresholds_cid=None if thresholds is None else thresholds.thresholds_cid,
        family=family,
        evaluated_at_utc=evaluated_at_utc,
        source_errors=tuple(source_errors),
        temporal_errors=tuple(temporal_errors),
        denied_provider_call_count=filters.denied_provider_call_count,
        passed=passed,
        metadata=metadata or {},
    )


# Silence unused private re-import lint noise for intentional re-use.
_ = (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    SourceLink,
    _optional_float_01,
    _sha256_hex,
    MissingPreRankingFiltersError,
    canonical_json,
)


__all__ = [
    "EVALUATION_INTERFACE",
    "EVALUATION_SCHEMA_VERSION",
    "REQUIRED_METRIC_KINDS",
    "SCHEMA_VERSION",
    "EvaluationError",
    "EvaluationReceipt",
    "MetricKind",
    "MetricScore",
    "MetricThresholdError",
    "MetricThresholds",
    "Qrel",
    "QrelSet",
    "RelevanceGrade",
    "apply_thresholds",
    "assert_thresholds",
    "build_evaluation_receipt",
    "canonical_json",
    "compute_citation_grounding",
    "compute_ndcg_at_k",
    "compute_private_isolation",
    "compute_recall_at_k",
    "compute_source_coverage",
    "compute_temporal_accuracy",
    "evaluate_ranking",
]
