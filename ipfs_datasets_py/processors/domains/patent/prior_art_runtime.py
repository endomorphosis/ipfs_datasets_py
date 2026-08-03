"""Live public-patent prior-art search adapters and runtime (PATLAW-148).

Executes bounded **local snapshot** and **ODP public** searches from explicit
query plans, records keywords/classifications/filters/cutoffs/results/scores/
retries and source-snapshot bindings, and emits replayable content-addressed
:class:`~ipfs_datasets_py.processors.domains.patent.search_journal.SearchJournal`
artifacts.

Design invariants
-----------------
* Recorded transports and local snapshots replay **identically** (same journal
  content digest for the same plan + fixtures).
* Every query record identifies database, search time, and corpus cutoff.
* Failures and rate limits remain explicit outcomes (never empty successes).
* Foreign-patent and NPL cannot be represented as searched unless a **named**
  adapter that supports those corpora actually ran.
* Does not scrape authenticated USPTO interfaces, claim Patent Public Search
  is an API, or query private matters. Interactive PPS verification remains a
  documented human step outside this runtime.
* Never asserts novelty, obviousness, or patentability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Protocol, Sequence

from .hybrid_retrieval import (
    HybridSearchRequest,
    HybridSearchResult,
    PatentHybridRetriever,
    apply_pre_ranking_filters,
)
from .indexing import PatentIndexDocument, build_patent_indexes, default_embedding_identity
from .prior_art import (
    PRIOR_ART_DISCLAIMER,
    PriorArtError,
    PriorArtSearchPlan,
    QueryFamily,
    SearchCorpus,
    SearchQuerySpec,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    SourceSpan,
)
from .search_journal import (
    SEARCH_JOURNAL_SCHEMA_VERSION,
    AdapterKind,
    JournalHit,
    NamedAdapterIdentity,
    QueryOutcomeKind,
    QueryRecord,
    RetryAttemptRecord,
    SearchDatabase,
    SearchJournal,
    build_query_record,
    build_search_journal,
    content_cid,
    content_digest,
    make_source_link,
    outcome_claims_search,
)

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

PRIOR_ART_RUNTIME_SCHEMA_VERSION: Final = "patent.prior_art_runtime.v1"
PRIOR_ART_RUNTIME_INTERFACE: Final = "PriorArtSearchRuntime@1"
PRIOR_ART_RUNTIME_CODE_VERSION: Final = "1.0.0"

LOCAL_SNAPSHOT_ADAPTER_NAME: Final = "local_public_snapshot.v1"
ODP_PUBLIC_ADAPTER_NAME: Final = "odp_public_patent_search.v1"

DEFAULT_RANK_CUTOFF: Final = 10
DEFAULT_MAX_QUERIES: Final = 128
DEFAULT_ODP_PAGE_LIMIT: Final = 25

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]{1,63}")

# Synthetic but stable CID prefix for ODP item payloads when no store CID.
_ODP_SOURCE_CID_PREFIX: Final = "bafybeigodppriorart"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PriorArtRuntimeError(PriorArtError):
    """Base error for the prior-art search runtime."""

    code: str = "prior_art_runtime_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class AdapterNotRegisteredError(PriorArtRuntimeError):
    """Raised when a required named adapter is not registered."""

    code = "adapter_not_registered"


class AdapterExecutionError(PriorArtRuntimeError):
    """Raised when an adapter fails in a non-recordable way."""

    code = "adapter_execution_error"


class RuntimeConfigError(PriorArtRuntimeError):
    """Raised when runtime configuration is invalid."""

    code = "runtime_config_invalid"


class SnapshotSearchError(PriorArtRuntimeError):
    """Raised when a local snapshot cannot be searched."""

    code = "snapshot_search_error"


# ---------------------------------------------------------------------------
# Enums / modes
# ---------------------------------------------------------------------------


class RuntimeSearchMode(str, Enum):
    """How the runtime obtains search backends."""

    LOCAL_SNAPSHOT = "local_snapshot"
    ODP_RECORDED = "odp_recorded"
    ODP_PRODUCTION = "odp_production"
    MULTI = "multi"


# ---------------------------------------------------------------------------
# Query plan surface (explicit, independent of PriorArtSearchPlan)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicSearchQuery:
    """One explicit public-patent query for the runtime to execute."""

    query_id: str
    query_text: str
    database: SearchDatabase
    rank_cutoff: int = DEFAULT_RANK_CUTOFF
    keywords: tuple[str, ...] = ()
    classification_codes: tuple[str, ...] = ()
    family: QueryFamily = QueryFamily.KEYWORD
    filters: Mapping[str, str] = MappingProxyType({})
    related_limitation_ids: tuple[str, ...] = ()
    preferred_adapter: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_text", _require_str(self.query_text, "query_text", max_len=8192)
        )
        object.__setattr__(
            self, "database", _coerce_enum(SearchDatabase, self.database, "database")
        )
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        object.__setattr__(
            self, "keywords", _tuple_of_str(self.keywords, "keywords", max_items=128)
        )
        object.__setattr__(
            self,
            "classification_codes",
            _tuple_of_str(
                self.classification_codes, "classification_codes", max_items=64
            ),
        )
        object.__setattr__(
            self, "family", _coerce_enum(QueryFamily, self.family, "family")
        )
        object.__setattr__(self, "filters", _frozen_str_map(self.filters, "filters"))
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "preferred_adapter",
            _optional_str(self.preferred_adapter, "preferred_adapter", max_len=128),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification_codes": list(self.classification_codes),
            "database": self.database.value,
            "family": self.family.value,
            "filters": dict(self.filters),
            "keywords": list(self.keywords),
            "metadata": dict(self.metadata),
            "preferred_adapter": self.preferred_adapter,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "rank_cutoff": self.rank_cutoff,
            "related_limitation_ids": list(self.related_limitation_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicSearchQuery":
        if not isinstance(value, Mapping):
            raise TypeError("PublicSearchQuery.from_dict expects a mapping")
        return cls(
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            database=value.get("database", SearchDatabase.US_PATENTS.value),
            rank_cutoff=int(value.get("rank_cutoff") or DEFAULT_RANK_CUTOFF),
            keywords=tuple(value.get("keywords") or ()),
            classification_codes=tuple(value.get("classification_codes") or ()),
            family=value.get("family", QueryFamily.KEYWORD.value),
            filters=value.get("filters") or {},
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            preferred_adapter=value.get("preferred_adapter"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PublicSearchPlan:
    """Bounded explicit plan of public-patent queries for the runtime."""

    plan_id: str
    subject_id: str
    search_time_utc: str
    corpus_cutoff: str
    queries: tuple[PublicSearchQuery, ...]
    pre_ranking_filters: PreRankingFilters | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, "plan_id"))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "search_time_utc", _iso_utc(self.search_time_utc, "search_time_utc")
        )
        cutoff = _require_str(self.corpus_cutoff, "corpus_cutoff", max_len=64)
        if not (_ISO_DATE_RE.match(cutoff) or _ISO_UTC_RE.match(cutoff)):
            raise RuntimeConfigError(
                f"corpus_cutoff must be YYYY-MM-DD or ISO-8601 UTC, got {cutoff!r}"
            )
        object.__setattr__(self, "corpus_cutoff", cutoff)
        queries = self.queries or ()
        if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
            raise TypeError("queries must be a sequence")
        if not queries:
            raise RuntimeConfigError("PublicSearchPlan.queries must be non-empty")
        if len(queries) > DEFAULT_MAX_QUERIES:
            raise RuntimeConfigError(
                f"queries exceeds max items {DEFAULT_MAX_QUERIES}",
                code="too_many_queries",
            )
        parsed: list[PublicSearchQuery] = []
        for i, item in enumerate(queries):
            if isinstance(item, PublicSearchQuery):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(PublicSearchQuery.from_dict(item))
            else:
                raise TypeError(f"queries[{i}] must be PublicSearchQuery or mapping")
        object.__setattr__(self, "queries", tuple(parsed))
        if self.pre_ranking_filters is not None and not isinstance(
            self.pre_ranking_filters, PreRankingFilters
        ):
            if isinstance(self.pre_ranking_filters, Mapping):
                object.__setattr__(
                    self,
                    "pre_ranking_filters",
                    PreRankingFilters.from_dict(self.pre_ranking_filters),
                )
            else:
                raise TypeError(
                    "pre_ranking_filters must be PreRankingFilters, mapping, or None"
                )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_cutoff": self.corpus_cutoff,
            "metadata": dict(self.metadata),
            "plan_id": self.plan_id,
            "pre_ranking_filters": (
                None
                if self.pre_ranking_filters is None
                else self.pre_ranking_filters.to_dict()
            ),
            "queries": [q.to_dict() for q in self.queries],
            "search_time_utc": self.search_time_utc,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicSearchPlan":
        if not isinstance(value, Mapping):
            raise TypeError("PublicSearchPlan.from_dict expects a mapping")
        filters_raw = value.get("pre_ranking_filters")
        filters = (
            None
            if filters_raw is None
            else (
                filters_raw
                if isinstance(filters_raw, PreRankingFilters)
                else PreRankingFilters.from_dict(filters_raw)
            )
        )
        return cls(
            plan_id=value.get("plan_id", ""),
            subject_id=value.get("subject_id", ""),
            search_time_utc=value.get("search_time_utc", ""),
            corpus_cutoff=value.get("corpus_cutoff", ""),
            queries=tuple(value.get("queries") or ()),
            pre_ranking_filters=filters,
            metadata=value.get("metadata") or {},
        )


def public_search_plan_from_prior_art_plan(
    plan: PriorArtSearchPlan,
    *,
    corpus_cutoff: str | None = None,
    database: SearchDatabase = SearchDatabase.US_PATENTS,
) -> PublicSearchPlan:
    """Project a PATLAW-094 :class:`PriorArtSearchPlan` into a runtime plan."""
    cutoff = corpus_cutoff or plan.search_date_utc[:10]
    queries: list[PublicSearchQuery] = []
    for q in plan.queries:
        # Prefer US corpora only; foreign/NPL queries require dedicated adapters.
        db = database
        for intended in q.intended_corpora:
            if intended is SearchCorpus.US_PUBLICATIONS:
                db = SearchDatabase.US_PUBLICATIONS
                break
            if intended is SearchCorpus.US_PATENTS:
                db = SearchDatabase.US_PATENTS
                break
            if intended is SearchCorpus.FOREIGN_PATENTS:
                db = SearchDatabase.FOREIGN_PATENTS
                break
            if intended is SearchCorpus.NPL:
                db = SearchDatabase.NPL
                break
        keywords = tuple(
            t for t in _TOKEN_RE.findall(q.query_text) if len(t) > 2
        )[:32]
        queries.append(
            PublicSearchQuery(
                query_id=q.query_id,
                query_text=q.query_text,
                database=db,
                rank_cutoff=q.rank_cutoff,
                keywords=keywords,
                classification_codes=q.classification_codes,
                family=q.family,
                related_limitation_ids=q.related_limitation_ids,
                metadata=dict(q.metadata),
            )
        )
    return PublicSearchPlan(
        plan_id=plan.plan_id,
        subject_id=plan.subject_id,
        search_time_utc=plan.search_date_utc,
        corpus_cutoff=cutoff,
        queries=tuple(queries),
        pre_ranking_filters=plan.filters,
        metadata={"source": "prior_art_search_plan"},
    )


# ---------------------------------------------------------------------------
# Adapter protocol + results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterSearchResult:
    """Normalized result from one named adapter invocation."""

    outcome: QueryOutcomeKind
    hits: tuple[JournalHit, ...] = ()
    retries: tuple[RetryAttemptRecord, ...] = ()
    source_snapshot_cid: str | None = None
    transport_receipt_id: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_count: int = 0
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outcome", _coerce_enum(QueryOutcomeKind, self.outcome, "outcome")
        )
        hits = self.hits or ()
        if not isinstance(hits, Sequence) or isinstance(hits, (str, bytes)):
            raise TypeError("hits must be a sequence")
        parsed: list[JournalHit] = []
        for i, item in enumerate(hits):
            if isinstance(item, JournalHit):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(JournalHit.from_dict(item))
            else:
                raise TypeError(f"hits[{i}] must be JournalHit or mapping")
        object.__setattr__(self, "hits", tuple(parsed))
        retries = self.retries or ()
        parsed_r: list[RetryAttemptRecord] = []
        for i, item in enumerate(retries or ()):
            if isinstance(item, RetryAttemptRecord):
                parsed_r.append(item)
            elif isinstance(item, Mapping):
                parsed_r.append(RetryAttemptRecord.from_dict(item))
            else:
                raise TypeError(f"retries[{i}] must be RetryAttemptRecord or mapping")
        object.__setattr__(self, "retries", tuple(parsed_r))
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )
        if self.result_count == 0 and outcome_claims_search(self.outcome):
            object.__setattr__(self, "result_count", len(self.hits))


class PriorArtSearchAdapter(Protocol):
    """Protocol for a named prior-art search backend."""

    @property
    def identity(self) -> NamedAdapterIdentity: ...

    def supports_database(self, database: SearchDatabase) -> bool: ...

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult: ...


# ---------------------------------------------------------------------------
# Local snapshot adapter
# ---------------------------------------------------------------------------


@dataclass
class LocalSnapshotSearchAdapter:
    """Search a pinned local public-patent index snapshot (hybrid retrieval).

    Deterministic: identical documents + query + cutoff → identical hits and
    source-snapshot CID, enabling journal replay.
    """

    retriever: PatentHybridRetriever
    snapshot_cid: str
    supported_databases: tuple[SearchDatabase, ...] = (
        SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
        SearchDatabase.US_PATENTS,
        SearchDatabase.US_PUBLICATIONS,
    )
    adapter_name: str = LOCAL_SNAPSHOT_ADAPTER_NAME
    adapter_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not isinstance(self.retriever, PatentHybridRetriever):
            raise TypeError("retriever must be PatentHybridRetriever")
        self.snapshot_cid = _require_str(self.snapshot_cid, "snapshot_cid", max_len=256)
        dbs = tuple(
            _coerce_enum(SearchDatabase, d, "supported_databases")
            for d in (self.supported_databases or ())
        )
        if not dbs:
            raise RuntimeConfigError("supported_databases must be non-empty")
        self.supported_databases = dbs  # type: ignore[assignment]

    @property
    def identity(self) -> NamedAdapterIdentity:
        # Local snapshot never claims foreign/NPL support.
        corpora: list[SearchCorpus] = []
        for db in self.supported_databases:
            if db is SearchDatabase.US_PUBLICATIONS:
                corpora.append(SearchCorpus.US_PUBLICATIONS)
            elif db in (
                SearchDatabase.US_PATENTS,
                SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
            ):
                corpora.append(SearchCorpus.US_PATENTS)
        if not corpora:
            corpora = [SearchCorpus.US_PATENTS]
        # Unique preserve order
        seen: list[SearchCorpus] = []
        for c in corpora:
            if c not in seen:
                seen.append(c)
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.LOCAL_SNAPSHOT,
            supported_corpora=tuple(seen),
            adapter_version=self.adapter_version,
            metadata={"snapshot_cid": self.snapshot_cid},
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database in self.supported_databases

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=(
                    f"local snapshot adapter does not support {query.database.value}"
                ),
                source_snapshot_cid=self.snapshot_cid,
            )
        filters = pre_ranking_filters
        if filters is None:
            filters = PreRankingFilters(
                schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                tenant_id="tenant-public",
                as_of_utc=search_time_utc,
                allowed_disclosures=(
                    DisclosureClass.PUBLIC_OFFICIAL,
                    DisclosureClass.PUBLIC_USER,
                ),
                applied=False,
                filter_receipt_id=f"filter:local:{query.query_id}",
            )
        applied = filters if filters.applied else apply_pre_ranking_filters(filters)

        try:
            request = HybridSearchRequest(
                query_id=query.query_id,
                query=query.query_text,
                filters=applied,
                top_k=query.rank_cutoff,
                query_disclosure=DisclosureClass.PUBLIC_USER,
            )
            result = self.retriever.search(request)
        except Exception as exc:  # noqa: BLE001 — record as failure
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code=getattr(exc, "code", type(exc).__name__),
                error_message=str(exc)[:1024],
                source_snapshot_cid=self.snapshot_cid,
                retries=(
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.FAILURE,
                        error_code=getattr(exc, "code", type(exc).__name__),
                        message=str(exc)[:512],
                    ),
                ),
            )

        hits = _hybrid_hits_to_journal_hits(result, rank_cutoff=query.rank_cutoff)
        outcome = (
            QueryOutcomeKind.SUCCESS if hits else QueryOutcomeKind.EMPTY
        )
        return AdapterSearchResult(
            outcome=outcome,
            hits=hits,
            source_snapshot_cid=self.snapshot_cid,
            result_count=len(hits),
            retries=(
                RetryAttemptRecord(
                    attempt=1,
                    outcome=outcome,
                    status_code=200,
                ),
            ),
            metadata={
                "bm25_backend": str(getattr(result, "bm25_backend", "") or ""),
                "corpus_cid": str(
                    getattr(getattr(result, "fusion", None), "corpus_cid", "") or ""
                ),
            },
        )


def build_local_snapshot_adapter(
    documents: Sequence[PatentIndexDocument | Mapping[str, Any]],
    *,
    filters: PreRankingFilters,
    snapshot_cid: str | None = None,
    corpus_cid: str | None = None,
    edges: Sequence[Any] = (),
) -> LocalSnapshotSearchAdapter:
    """Build a deterministic local-snapshot adapter from public documents."""
    docs: list[PatentIndexDocument] = []
    for item in documents:
        if isinstance(item, PatentIndexDocument):
            docs.append(item)
        elif isinstance(item, Mapping):
            docs.append(PatentIndexDocument.from_dict(item))
        else:
            raise TypeError("documents must be PatentIndexDocument or mapping")
    applied = filters if filters.applied else apply_pre_ranking_filters(filters)
    emb = default_embedding_identity()
    c_cid = corpus_cid or "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    bundle = build_patent_indexes(
        docs,
        filters=applied,
        edges=edges,
        embedding=emb,
        corpus_cid=c_cid,
        allow_remote=False,
    )
    retriever = PatentHybridRetriever(bundle)
    # Snapshot identity binds corpus + config + document digests.
    snap_payload = {
        "corpus_cid": c_cid,
        "config_cid": bundle.config_cid,
        "document_ids": sorted(d.document_id for d in docs),
        "doc_digests": sorted(d.content_digest for d in docs),
        "schema": PRIOR_ART_RUNTIME_SCHEMA_VERSION,
    }
    snap_cid = snapshot_cid or content_cid(snap_payload, prefix="bafybeiglocalsnap")
    return LocalSnapshotSearchAdapter(retriever=retriever, snapshot_cid=snap_cid)


def _hybrid_hits_to_journal_hits(
    result: HybridSearchResult,
    *,
    rank_cutoff: int,
) -> tuple[JournalHit, ...]:
    fused = result.fused_hits if isinstance(result, HybridSearchResult) else ()
    out: list[JournalHit] = []
    for hit in fused:
        if not isinstance(hit, RankedHit):
            continue
        if hit.rank > rank_cutoff:
            continue
        links = hit.source_links
        if not links:
            continue
        # Ensure span present for journal contract.
        fixed: list[SourceLink] = []
        for link in links:
            if link.span is None:
                fixed.append(
                    SourceLink(
                        source_cid=link.source_cid,
                        artifact_id=link.artifact_id,
                        span=SourceSpan(start=0, end=1, unit="char"),
                        source_receipt_id=link.source_receipt_id,
                        authority_tier=link.authority_tier,
                    )
                )
            else:
                fixed.append(link)
        out.append(
            JournalHit(
                document_id=hit.document_id,
                rank=hit.rank,
                score=float(hit.score),
                source_links=tuple(fixed),
                metadata={"family": hit.family.value if hit.family else "fusion"},
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# ODP public search adapter
# ---------------------------------------------------------------------------


@dataclass
class OdpPublicSearchAdapter:
    """Bounded ODP Patent File Wrapper **search** adapter (public only).

    Uses an injected :class:`PatentFileWrapperClient` (production or
    :class:`RecordedHttpTransport`). Does not claim Patent Public Search is an
    API and does not touch private matters.
    """

    client: Any  # PatentFileWrapperClient — typed loosely to avoid hard import cycles
    adapter_name: str = ODP_PUBLIC_ADAPTER_NAME
    adapter_version: str = "1.0.0"
    default_page_limit: int = DEFAULT_ODP_PAGE_LIMIT
    max_pages: int = 1
    source_snapshot_cid: str | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            raise RuntimeConfigError("OdpPublicSearchAdapter requires a client")
        self.default_page_limit = _positive_int(
            self.default_page_limit, "default_page_limit"
        )
        self.max_pages = _positive_int(self.max_pages, "max_pages")
        if self.source_snapshot_cid is not None:
            self.source_snapshot_cid = _require_str(
                self.source_snapshot_cid, "source_snapshot_cid", max_len=256
            )

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.ODP_PUBLIC,
            supported_corpora=(
                SearchCorpus.US_PATENTS,
                SearchCorpus.US_PUBLICATIONS,
            ),
            adapter_version=self.adapter_version,
            metadata={"endpoint": "POST /api/v1/patent/applications/search"},
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database in {
            SearchDatabase.ODP_PATENT_FILE_WRAPPER,
            SearchDatabase.US_PATENTS,
            SearchDatabase.US_PUBLICATIONS,
        }

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        del pre_ranking_filters  # ODP search uses text query; filters recorded only
        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=(
                    f"ODP public adapter does not support {query.database.value}"
                ),
            )

        retries: list[RetryAttemptRecord] = []
        # Build ODP query body from keywords/classifications/text.
        body = _build_odp_search_body(query)
        page_limit = min(query.rank_cutoff, self.default_page_limit)

        try:
            from ipfs_datasets_py.processors.domains.uspto.providers.base import (
                ProviderOutcomeKind,
            )
        except ImportError:  # pragma: no cover — environment gap
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="odp_import_error",
                error_message="ODP provider modules unavailable",
            )

        all_items: list[Any] = []
        last_status: int | None = None
        receipt_id: str | None = None
        attempt = 0
        snapshot_parts: list[Any] = []

        try:
            pages = self.client.iter_search_pages(
                body, limit=page_limit, max_pages=self.max_pages
            )
            for page_result in pages:
                attempt += 1
                last_status = page_result.status_code
                outcome = _provider_outcome_to_query_outcome(page_result.kind)
                err = page_result.error_code
                msg = page_result.message
                retries.append(
                    RetryAttemptRecord(
                        attempt=attempt,
                        outcome=outcome,
                        status_code=page_result.status_code,
                        error_code=err,
                        message=msg,
                    )
                )
                if page_result.receipt is not None:
                    # Prefer content-bound receipt identity so recorded transport
                    # replays produce identical journals (UUID receipt_ids vary).
                    receipt_id = _deterministic_receipt_id(page_result.receipt) or receipt_id
                    snap_meta = _receipt_snapshot_meta(page_result.receipt)
                    if snap_meta:
                        snapshot_parts.append(snap_meta)

                if page_result.kind is ProviderOutcomeKind.RATE_LIMITED:
                    return AdapterSearchResult(
                        outcome=QueryOutcomeKind.RATE_LIMITED,
                        retries=tuple(retries),
                        status_code=page_result.status_code,
                        error_code=err or "rate_limited",
                        error_message=msg or "ODP rate limited",
                        transport_receipt_id=receipt_id,
                        source_snapshot_cid=self._snapshot_cid(snapshot_parts),
                    )
                if not page_result.ok:
                    # Map other failures explicitly.
                    return AdapterSearchResult(
                        outcome=outcome
                        if outcome is not QueryOutcomeKind.SUCCESS
                        else QueryOutcomeKind.FAILURE,
                        retries=tuple(retries),
                        status_code=page_result.status_code,
                        error_code=err or outcome.value,
                        error_message=msg or f"ODP search failed: {page_result.kind}",
                        transport_receipt_id=receipt_id,
                        source_snapshot_cid=self._snapshot_cid(snapshot_parts),
                    )

                payload = page_result.payload
                items = getattr(payload, "items", ()) or ()
                all_items.extend(items)
                snapshot_parts.append(
                    {
                        "offset": getattr(payload, "offset", 0),
                        "limit": getattr(payload, "limit", page_limit),
                        "total_count": getattr(payload, "total_count", None),
                        "item_ids": [
                            _odp_item_document_id(it) for it in items
                        ],
                    }
                )
        except Exception as exc:  # noqa: BLE001 — surface as transport/failure
            attempt = max(attempt, 1)
            code = getattr(exc, "code", type(exc).__name__)
            # Fixture miss / transport errors stay explicit.
            if code in {"fixture_miss", "transport_error"} or "recorded exchange" in str(
                exc
            ).lower():
                q_outcome = QueryOutcomeKind.TRANSPORT_ERROR
            else:
                q_outcome = QueryOutcomeKind.FAILURE
            retries.append(
                RetryAttemptRecord(
                    attempt=attempt,
                    outcome=q_outcome,
                    error_code=str(code),
                    message=str(exc)[:512],
                )
            )
            return AdapterSearchResult(
                outcome=q_outcome,
                retries=tuple(retries),
                error_code=str(code),
                error_message=str(exc)[:1024],
                source_snapshot_cid=self._snapshot_cid(snapshot_parts),
            )

        hits = _odp_items_to_journal_hits(
            all_items,
            rank_cutoff=query.rank_cutoff,
            receipt_id=receipt_id,
        )
        snap = self._snapshot_cid(snapshot_parts)
        if not hits:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.EMPTY,
                hits=(),
                retries=tuple(retries)
                or (
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.EMPTY,
                        status_code=last_status or 200,
                    ),
                ),
                status_code=last_status or 200,
                result_count=0,
                transport_receipt_id=receipt_id,
                source_snapshot_cid=snap,
            )
        return AdapterSearchResult(
            outcome=QueryOutcomeKind.SUCCESS,
            hits=hits,
            retries=tuple(retries)
            or (
                RetryAttemptRecord(
                    attempt=1,
                    outcome=QueryOutcomeKind.SUCCESS,
                    status_code=last_status or 200,
                ),
            ),
            status_code=last_status or 200,
            result_count=len(hits),
            transport_receipt_id=receipt_id,
            source_snapshot_cid=snap,
        )

    def _snapshot_cid(self, parts: Sequence[Any]) -> str:
        if self.source_snapshot_cid:
            return self.source_snapshot_cid
        return content_cid(
            {"adapter": self.adapter_name, "parts": list(parts)},
            prefix="bafybeigodpsnap",
        )


def _build_odp_search_body(query: PublicSearchQuery) -> dict[str, Any]:
    """Compose a compact ODP search body from an explicit query."""
    # Prefer structured q string; include classification filters when present.
    parts = [query.query_text.strip()]
    if query.classification_codes:
        codes = " OR ".join(query.classification_codes)
        parts.append(f"({codes})")
    q_text = " ".join(p for p in parts if p)
    body: dict[str, Any] = {"q": q_text}
    # Optional metadata filters recorded for replay matching.
    if query.filters:
        body["filters"] = dict(query.filters)
    return body


def _deterministic_receipt_id(receipt: Any) -> str | None:
    """Derive a replay-stable receipt token from digests (not UUID receipt_id)."""
    if receipt is None:
        return None
    response_digest = getattr(receipt, "response_digest", None)
    request_digest = getattr(receipt, "request_digest", None)
    if response_digest:
        return f"receipt:odp:sha256:{str(response_digest)[:40]}"
    if request_digest:
        return f"receipt:odp:req:{str(request_digest)[:40]}"
    # Fall back only when digests are unavailable.
    rid = getattr(receipt, "receipt_id", None)
    return str(rid) if rid else None


def _receipt_snapshot_meta(receipt: Any) -> dict[str, Any] | None:
    """Stable receipt fields for source-snapshot binding (exclude wall-clock/UUID)."""
    if receipt is None:
        return None
    endpoint = getattr(receipt, "endpoint", None)
    status = getattr(receipt, "response_status", None)
    response_digest = getattr(receipt, "response_digest", None)
    request_digest = getattr(receipt, "request_digest", None)
    if not any((endpoint, status, response_digest, request_digest)):
        return None
    return {
        "endpoint": endpoint,
        "request_digest": request_digest,
        "response_digest": response_digest,
        "response_status": status,
    }


def _provider_outcome_to_query_outcome(kind: Any) -> QueryOutcomeKind:
    name = kind.value if hasattr(kind, "value") else str(kind)
    mapping = {
        "success": QueryOutcomeKind.SUCCESS,
        "not_modified": QueryOutcomeKind.SUCCESS,
        "rate_limited": QueryOutcomeKind.RATE_LIMITED,
        "retry_budget_exhausted": QueryOutcomeKind.RETRY_BUDGET_EXHAUSTED,
        "cancelled": QueryOutcomeKind.CANCELLED,
        "transport_error": QueryOutcomeKind.TRANSPORT_ERROR,
        "upstream_error": QueryOutcomeKind.UPSTREAM_ERROR,
        "client_error": QueryOutcomeKind.CLIENT_ERROR,
        "malformed": QueryOutcomeKind.MALFORMED,
        "schema_drift": QueryOutcomeKind.MALFORMED,
        "not_found": QueryOutcomeKind.NOT_FOUND,
        "unauthorized": QueryOutcomeKind.UNAUTHORIZED,
        "forbidden": QueryOutcomeKind.FORBIDDEN,
        "circuit_open": QueryOutcomeKind.UPSTREAM_ERROR,
    }
    return mapping.get(name, QueryOutcomeKind.FAILURE)


def _odp_item_document_id(item: Any) -> str:
    if isinstance(item, Mapping):
        for key in (
            "applicationNumberText",
            "patentNumber",
            "publicationNumber",
            "document_id",
            "id",
        ):
            val = item.get(key)
            if val:
                return f"doc:odp:{val}"
        meta = item.get("applicationMetaData") or {}
        if isinstance(meta, Mapping):
            for key in ("applicationNumberText", "patentNumber"):
                val = meta.get(key)
                if val:
                    return f"doc:odp:{val}"
    return f"doc:odp:{content_digest(item if not hasattr(item, 'to_dict') else item)[:16]}"


def _odp_items_to_journal_hits(
    items: Sequence[Any],
    *,
    rank_cutoff: int,
    receipt_id: str | None,
) -> tuple[JournalHit, ...]:
    out: list[JournalHit] = []
    for index, item in enumerate(items):
        rank = index + 1
        if rank > rank_cutoff:
            break
        doc_id = _odp_item_document_id(item)
        payload = item if isinstance(item, Mapping) else {"value": str(item)}
        source_cid = content_cid(payload, prefix=_ODP_SOURCE_CID_PREFIX)
        # Score: deterministic reverse-rank score (no model ranking from ODP).
        score = float(max(rank_cutoff - index, 1))
        title = ""
        if isinstance(item, Mapping):
            meta = item.get("applicationMetaData") or {}
            if isinstance(meta, Mapping):
                title = str(meta.get("inventionTitle") or meta.get("title") or "")
            title = title or str(item.get("inventionTitle") or "")
        excerpt = (title or doc_id)[:512]
        identifiers: dict[str, str] = {}
        if isinstance(item, Mapping):
            for key in (
                "applicationNumberText",
                "patentNumber",
                "publicationNumber",
            ):
                if item.get(key):
                    identifiers[key] = str(item[key])
            meta = item.get("applicationMetaData")
            if isinstance(meta, Mapping):
                for key in (
                    "applicationNumberText",
                    "patentNumber",
                    "publicationNumber",
                ):
                    if meta.get(key) and key not in identifiers:
                        identifiers[key] = str(meta[key])
        out.append(
            JournalHit(
                document_id=doc_id,
                rank=rank,
                score=score,
                source_links=(
                    make_source_link(
                        source_cid=source_cid,
                        artifact_id=f"artifact:{doc_id}",
                        start=0,
                        end=max(len(excerpt), 1),
                        source_receipt_id=receipt_id,
                        authority_tier="odp-public",
                    ),
                ),
                passage_excerpt=excerpt or None,
                identifiers=identifiers,
                metadata={"source": "odp_search"},
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Optional named foreign / NPL adapters (must run to claim coverage)
# ---------------------------------------------------------------------------


@dataclass
class NamedCoverageAdapter:
    """Explicit foreign-patent or NPL adapter stub that must **run** to claim search.

    Production licensed backends inject a real ``search_fn``. Without a real
    run, the journal cannot mark foreign/NPL as searched.
    """

    adapter_name: str
    adapter_kind: AdapterKind
    supported_corpora: tuple[SearchCorpus, ...]
    search_fn: Callable[
        [PublicSearchQuery, str, str, PreRankingFilters | None], AdapterSearchResult
    ] | None = None
    adapter_version: str = "1.0.0"
    databases: tuple[SearchDatabase, ...] = ()

    def __post_init__(self) -> None:
        self.adapter_name = _identifier(self.adapter_name, "adapter_name")
        kind = _coerce_enum(AdapterKind, self.adapter_kind, "adapter_kind")
        assert isinstance(kind, AdapterKind)
        self.adapter_kind = kind
        corpora = tuple(
            _coerce_enum(SearchCorpus, c, "supported_corpora")
            for c in (self.supported_corpora or ())
        )
        if not corpora:
            raise RuntimeConfigError("supported_corpora must be non-empty")
        self.supported_corpora = corpora  # type: ignore[assignment]
        if not self.databases:
            dbs: list[SearchDatabase] = []
            for c in corpora:
                if c is SearchCorpus.FOREIGN_PATENTS:
                    dbs.append(SearchDatabase.FOREIGN_PATENTS)
                elif c is SearchCorpus.NPL:
                    dbs.append(SearchDatabase.NPL)
            self.databases = tuple(dbs)

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=self.adapter_kind,
            supported_corpora=self.supported_corpora,
            adapter_version=self.adapter_version,
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database in self.databases

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=f"{self.adapter_name} does not support {query.database.value}",
            )
        if self.search_fn is None:
            # Adapter is registered but has no backend — explicit failure, not searched.
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="adapter_backend_unavailable",
                error_message=(
                    f"named adapter {self.adapter_name} has no search backend; "
                    f"corpus remains unsearched"
                ),
                retries=(
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.FAILURE,
                        error_code="adapter_backend_unavailable",
                    ),
                ),
            )
        return self.search_fn(
            query, search_time_utc, corpus_cutoff, pre_ranking_filters
        )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


@dataclass
class PriorArtSearchRuntime:
    """Orchestrate named public-patent search adapters and emit a journal.

    Register only the adapters that should run. Foreign/NPL coverage requires
    an explicit :class:`NamedCoverageAdapter` (or equivalent) that actually
    executes — mere registration is insufficient if it never runs.
    """

    adapters: Mapping[str, PriorArtSearchAdapter] = field(default_factory=dict)
    default_local_adapter: str | None = None
    default_odp_adapter: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.adapters, Mapping):
            raise RuntimeConfigError("adapters must be a mapping of name → adapter")
        # Normalize keys to adapter identity names.
        normalized: dict[str, PriorArtSearchAdapter] = {}
        for key, adapter in dict(self.adapters).items():
            identity = adapter.identity
            name = identity.adapter_name
            normalized[name] = adapter
            # Also allow registration under the provided key.
            if str(key) != name:
                normalized[str(key)] = adapter
        self.adapters = MappingProxyType(normalized)  # type: ignore[assignment]

        if self.default_local_adapter is None:
            for name, adapter in self.adapters.items():
                if adapter.identity.adapter_kind is AdapterKind.LOCAL_SNAPSHOT:
                    self.default_local_adapter = adapter.identity.adapter_name
                    break
        if self.default_odp_adapter is None:
            for name, adapter in self.adapters.items():
                if adapter.identity.adapter_kind is AdapterKind.ODP_PUBLIC:
                    self.default_odp_adapter = adapter.identity.adapter_name
                    break

    def register(self, adapter: PriorArtSearchAdapter) -> "PriorArtSearchRuntime":
        """Return a new runtime with *adapter* registered (immutable style)."""
        merged = dict(self.adapters)
        merged[adapter.identity.adapter_name] = adapter
        return PriorArtSearchRuntime(
            adapters=merged,
            default_local_adapter=self.default_local_adapter,
            default_odp_adapter=self.default_odp_adapter,
        )

    def resolve_adapter(self, query: PublicSearchQuery) -> PriorArtSearchAdapter | None:
        """Pick a registered adapter for the query database."""
        if query.preferred_adapter:
            adapter = self.adapters.get(query.preferred_adapter)
            if adapter is not None and adapter.supports_database(query.database):
                return adapter
            return None

        # Preference order by database.
        candidates: list[str] = []
        if query.database is SearchDatabase.LOCAL_PUBLIC_SNAPSHOT:
            if self.default_local_adapter:
                candidates.append(self.default_local_adapter)
        elif query.database is SearchDatabase.ODP_PATENT_FILE_WRAPPER:
            if self.default_odp_adapter:
                candidates.append(self.default_odp_adapter)
        elif query.database in (
            SearchDatabase.US_PATENTS,
            SearchDatabase.US_PUBLICATIONS,
        ):
            if self.default_local_adapter:
                candidates.append(self.default_local_adapter)
            if self.default_odp_adapter:
                candidates.append(self.default_odp_adapter)
        elif query.database is SearchDatabase.FOREIGN_PATENTS:
            for name, adapter in self.adapters.items():
                if adapter.identity.adapter_kind is AdapterKind.FOREIGN_PATENT:
                    candidates.append(adapter.identity.adapter_name)
        elif query.database is SearchDatabase.NPL:
            for name, adapter in self.adapters.items():
                if adapter.identity.adapter_kind is AdapterKind.NPL:
                    candidates.append(adapter.identity.adapter_name)

        for name in candidates:
            adapter = self.adapters.get(name)
            if adapter is not None and adapter.supports_database(query.database):
                return adapter

        # Fallback: first registered adapter that supports the database.
        for adapter in self.adapters.values():
            if adapter.supports_database(query.database):
                return adapter
        return None

    def execute_query(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> QueryRecord:
        """Execute one query and return a journal :class:`QueryRecord`."""
        adapter = self.resolve_adapter(query)
        if adapter is None:
            # Explicit adapter-missing outcome; restricted corpora stay unsearched.
            placeholder = NamedAdapterIdentity(
                adapter_name="adapter:none",
                adapter_kind=AdapterKind.OTHER,
                supported_corpora=(SearchCorpus.US_PATENTS,),
                adapter_version="0.0.0",
            )
            return build_query_record(
                query_id=query.query_id,
                query_text=query.query_text,
                database=query.database,
                search_time_utc=search_time_utc,
                corpus_cutoff=corpus_cutoff,
                rank_cutoff=query.rank_cutoff,
                adapter=placeholder,
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                keywords=query.keywords,
                classification_codes=query.classification_codes,
                filters=query.filters,
                error_code="adapter_not_registered",
                error_message=(
                    f"no named adapter registered for database {query.database.value}"
                ),
                claims_corpus_searched=False,
                metadata={"runtime": PRIOR_ART_RUNTIME_INTERFACE},
            )

        result = adapter.search(
            query,
            search_time_utc=search_time_utc,
            corpus_cutoff=corpus_cutoff,
            pre_ranking_filters=pre_ranking_filters,
        )
        identity = adapter.identity
        # claims_corpus_searched only when outcome claims search AND adapter supports.
        claims = bool(
            outcome_claims_search(result.outcome)
            and identity.supports(
                {
                    SearchDatabase.US_PATENTS: SearchCorpus.US_PATENTS,
                    SearchDatabase.US_PUBLICATIONS: SearchCorpus.US_PUBLICATIONS,
                    SearchDatabase.LOCAL_PUBLIC_SNAPSHOT: SearchCorpus.US_PATENTS,
                    SearchDatabase.ODP_PATENT_FILE_WRAPPER: SearchCorpus.US_PATENTS,
                    SearchDatabase.FOREIGN_PATENTS: SearchCorpus.FOREIGN_PATENTS,
                    SearchDatabase.NPL: SearchCorpus.NPL,
                }[query.database]
            )
        )
        return build_query_record(
            query_id=query.query_id,
            query_text=query.query_text,
            database=query.database,
            search_time_utc=search_time_utc,
            corpus_cutoff=corpus_cutoff,
            rank_cutoff=query.rank_cutoff,
            adapter=identity,
            outcome=result.outcome,
            keywords=query.keywords,
            classification_codes=query.classification_codes,
            filters=query.filters,
            hits=result.hits,
            retries=result.retries,
            source_snapshot_cid=result.source_snapshot_cid,
            transport_receipt_id=result.transport_receipt_id,
            status_code=result.status_code,
            error_code=result.error_code,
            error_message=result.error_message,
            result_count=result.result_count,
            claims_corpus_searched=claims,
            metadata={
                "runtime": PRIOR_ART_RUNTIME_INTERFACE,
                **dict(result.metadata),
            },
        )

    def execute_plan(self, plan: PublicSearchPlan) -> SearchJournal:
        """Execute every query in *plan* and emit a content-addressed journal."""
        if not isinstance(plan, PublicSearchPlan):
            if isinstance(plan, Mapping):
                plan = PublicSearchPlan.from_dict(plan)
            else:
                raise TypeError("plan must be PublicSearchPlan or mapping")

        records: list[QueryRecord] = []
        for query in plan.queries:
            records.append(
                self.execute_query(
                    query,
                    search_time_utc=plan.search_time_utc,
                    corpus_cutoff=plan.corpus_cutoff,
                    pre_ranking_filters=plan.pre_ranking_filters,
                )
            )

        adapters_run: list[NamedAdapterIdentity] = []
        seen: set[str] = set()
        for rec in records:
            if rec.adapter.adapter_name not in seen and rec.adapter.adapter_name != "adapter:none":
                # Only count adapters that actually ran (not placeholder).
                if rec.outcome is not QueryOutcomeKind.ADAPTER_NOT_REGISTERED or (
                    rec.adapter.adapter_name in self.adapters
                ):
                    adapters_run.append(rec.adapter)
                    seen.add(rec.adapter.adapter_name)

        return build_search_journal(
            subject_id=plan.subject_id,
            search_date_utc=plan.search_time_utc,
            corpus_cutoff=plan.corpus_cutoff,
            records=records,
            plan_id=plan.plan_id,
            adapters_run=adapters_run,
            metadata={
                "runtime_schema": PRIOR_ART_RUNTIME_SCHEMA_VERSION,
                "runtime_interface": PRIOR_ART_RUNTIME_INTERFACE,
                "disclaimer": PRIOR_ART_DISCLAIMER[:200],
            },
        )

    def execute_prior_art_plan(
        self,
        plan: PriorArtSearchPlan,
        *,
        corpus_cutoff: str | None = None,
        database: SearchDatabase = SearchDatabase.US_PATENTS,
    ) -> SearchJournal:
        """Convenience: project PATLAW-094 plan then execute."""
        public_plan = public_search_plan_from_prior_art_plan(
            plan, corpus_cutoff=corpus_cutoff, database=database
        )
        return self.execute_plan(public_plan)


def build_odp_adapter_from_transport(
    transport: Any,
    *,
    api_key: str = "test-key-not-live",
    base_url: str = "https://api.uspto.gov",
    source_snapshot_cid: str | None = None,
    max_pages: int = 1,
) -> OdpPublicSearchAdapter:
    """Construct an ODP adapter over an injected HTTP transport (recorded/live)."""
    from ipfs_datasets_py.processors.domains.uspto.providers.base import (
        ApiKeySecret,
        RetryPolicy,
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        PatentFileWrapperClient,
    )

    client = PatentFileWrapperClient(
        transport=transport,
        api_key=ApiKeySecret(api_key),
        base_url=base_url,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0),
    )
    return OdpPublicSearchAdapter(
        client=client,
        source_snapshot_cid=source_snapshot_cid,
        max_pages=max_pages,
    )


def build_public_prior_art_runtime(
    *,
    local_adapter: LocalSnapshotSearchAdapter | None = None,
    odp_adapter: OdpPublicSearchAdapter | None = None,
    extra_adapters: Sequence[PriorArtSearchAdapter] = (),
) -> PriorArtSearchRuntime:
    """Assemble a runtime from optional local and ODP public adapters."""
    adapters: dict[str, PriorArtSearchAdapter] = {}
    if local_adapter is not None:
        adapters[local_adapter.identity.adapter_name] = local_adapter
    if odp_adapter is not None:
        adapters[odp_adapter.identity.adapter_name] = odp_adapter
    for adapter in extra_adapters:
        adapters[adapter.identity.adapter_name] = adapter
    return PriorArtSearchRuntime(adapters=adapters)


# ---------------------------------------------------------------------------
# Helpers (shared validation)
# ---------------------------------------------------------------------------


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 1:
        raise ValueError(f"{field} must be >= 1")
    return value


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value))


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


__all__ = [
    "PRIOR_ART_RUNTIME_CODE_VERSION",
    "PRIOR_ART_RUNTIME_INTERFACE",
    "PRIOR_ART_RUNTIME_SCHEMA_VERSION",
    "LOCAL_SNAPSHOT_ADAPTER_NAME",
    "ODP_PUBLIC_ADAPTER_NAME",
    "AdapterExecutionError",
    "AdapterNotRegisteredError",
    "AdapterSearchResult",
    "LocalSnapshotSearchAdapter",
    "NamedCoverageAdapter",
    "OdpPublicSearchAdapter",
    "PriorArtRuntimeError",
    "PriorArtSearchAdapter",
    "PriorArtSearchRuntime",
    "PublicSearchPlan",
    "PublicSearchQuery",
    "RuntimeConfigError",
    "RuntimeSearchMode",
    "SnapshotSearchError",
    "build_local_snapshot_adapter",
    "build_odp_adapter_from_transport",
    "build_public_prior_art_runtime",
    "public_search_plan_from_prior_art_plan",
]
