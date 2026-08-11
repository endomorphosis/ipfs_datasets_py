"""Integration: live public-patent prior-art search adapter + journal (PATLAW-148).

Acceptance coverage
-------------------
* Recorded transports and local snapshots replay identically.
* Every query identifies database, time, and cutoff.
* Failures and rate limits remain explicit.
* Journal cannot represent foreign or NPL sources as searched unless a named
  adapter actually ran.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.indexing import PatentIndexDocument
from ipfs_datasets_py.processors.domains.patent.prior_art import SearchCorpus
from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
    LOCAL_SNAPSHOT_ADAPTER_NAME,
    ODP_PUBLIC_ADAPTER_NAME,
    PRIOR_ART_RUNTIME_SCHEMA_VERSION,
    AdapterSearchResult,
    NamedCoverageAdapter,
    PriorArtSearchRuntime,
    PublicSearchPlan,
    PublicSearchQuery,
    build_local_snapshot_adapter,
    build_odp_adapter_from_transport,
    build_public_prior_art_runtime,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    PreRankingFilters,
    SourceLink,
    SourceSpan,
)
from ipfs_datasets_py.processors.domains.patent.search_journal import (
    SEARCH_JOURNAL_SCHEMA_VERSION,
    AdapterKind,
    ForeignOrNplCoverageError,
    JournalHit,
    NamedAdapterIdentity,
    QueryOutcomeKind,
    QueryRecord,
    SearchDatabase,
    SearchJournal,
    assert_journal_query_identity,
    assert_no_unjustified_foreign_npl,
    build_query_record,
    build_search_journal,
    canonical_json,
    content_digest,
    make_source_link,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderOutcomeKind,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import ApiKeySecret

SEARCH_TIME = "2024-06-01T12:00:00Z"
CORPUS_CUTOFF = "2024-05-31"
TENANT = "tenant-public"
CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_SOURCE_B = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _filters(*, applied: bool = True) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=TENANT,
        as_of_utc=SEARCH_TIME,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=applied,
        denied_provider_call_count=0,
        filter_receipt_id="filter:public-prior-art",
    )


def _link(
    cid: str = CID_SOURCE,
    artifact_id: str = "artifact:patent-encode",
    start: int = 0,
    end: int = 40,
) -> SourceLink:
    return SourceLink(
        source_cid=cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=start, end=end, unit="char"),
        authority_tier="official-base",
    )


def _public_docs() -> list[PatentIndexDocument]:
    return [
        PatentIndexDocument(
            document_id="doc:patent-encode",
            field_values={
                "title": "Encoding retrieval system for patent claims",
                "abstract": "A method comprising encoding claim text for retrieval",
                "claims": "1. A method comprising encoding claim text for retrieval.",
                "cpc": "G06F16/00",
            },
            source_links=(_link(CID_SOURCE, "artifact:patent-encode"),),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id=TENANT,
            publication_utc="2020-01-15T00:00:00Z",
        ),
        PatentIndexDocument(
            document_id="doc:patent-network",
            field_values={
                "title": "Network packet classification",
                "abstract": "Systems for classifying network packets using CPC codes",
                "claims": "1. A system comprising network packet classification.",
                "cpc": "H04L45/00",
            },
            source_links=(_link(CID_SOURCE_B, "artifact:patent-network"),),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id=TENANT,
            publication_utc="2019-06-01T00:00:00Z",
        ),
    ]


def _local_runtime(
    *,
    snapshot_cid: str | None = None,
) -> tuple[PriorArtSearchRuntime, str]:
    adapter = build_local_snapshot_adapter(
        _public_docs(),
        filters=_filters(applied=False),
        snapshot_cid=snapshot_cid,
    )
    runtime = build_public_prior_art_runtime(local_adapter=adapter)
    return runtime, adapter.snapshot_cid


def _local_plan(
    *,
    query_text: str = "encoding claim text retrieval G06F16/00",
    database: SearchDatabase = SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
    rank_cutoff: int = 5,
) -> PublicSearchPlan:
    return PublicSearchPlan(
        plan_id="plan:public-local-1",
        subject_id="subject:app-16-123456",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q-kw-1",
                query_text=query_text,
                database=database,
                rank_cutoff=rank_cutoff,
                keywords=("encoding", "retrieval", "claim"),
                classification_codes=("G06F16/00",),
            ),
        ),
        pre_ranking_filters=_filters(applied=True),
    )


def _odp_search_body(
    apps: list[dict[str, Any]],
    *,
    count: int | None = None,
) -> dict[str, Any]:
    return {
        "count": count if count is not None else len(apps),
        "patentFileWrapperDataBag": apps,
        "requestIdentifier": "prior-art-search-test",
    }


def _odp_app(number: str, title: str) -> dict[str, Any]:
    return {
        "applicationNumberText": number,
        "applicationMetaData": {
            "inventionTitle": title,
            "applicationTypeLabelName": "Utility",
        },
    }


def _odp_transport(exchanges: list[RecordedExchange]) -> RecordedHttpTransport:
    return RecordedHttpTransport(exchanges)


def _odp_runtime(
    transport: RecordedHttpTransport,
    *,
    source_snapshot_cid: str | None = "bafybeigodpsnapshotfixed0000000000000000000000000001",
) -> PriorArtSearchRuntime:
    adapter = build_odp_adapter_from_transport(
        transport,
        source_snapshot_cid=source_snapshot_cid,
        max_pages=1,
    )
    return build_public_prior_art_runtime(odp_adapter=adapter)


def _odp_plan(
    *,
    query_text: str = "encoding retrieval",
    rank_cutoff: int = 5,
) -> PublicSearchPlan:
    return PublicSearchPlan(
        plan_id="plan:public-odp-1",
        subject_id="subject:app-16-999999",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q-odp-1",
                query_text=query_text,
                database=SearchDatabase.ODP_PATENT_FILE_WRAPPER,
                rank_cutoff=rank_cutoff,
                keywords=("encoding", "retrieval"),
                preferred_adapter=ODP_PUBLIC_ADAPTER_NAME,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Local snapshot replay
# ---------------------------------------------------------------------------


def test_local_snapshot_search_replays_identically() -> None:
    """Same local snapshot + plan → identical journal content digests."""
    runtime_a, snap_a = _local_runtime(snapshot_cid="bafybeiglocalsnapfixed000000000000000000000000000001")
    runtime_b, snap_b = _local_runtime(snapshot_cid="bafybeiglocalsnapfixed000000000000000000000000000001")
    assert snap_a == snap_b

    plan = _local_plan()
    journal_a = runtime_a.execute_plan(plan)
    journal_b = runtime_b.execute_plan(plan)

    assert journal_a.schema_version == SEARCH_JOURNAL_SCHEMA_VERSION
    assert journal_a.records
    assert journal_a.content_digest == journal_b.content_digest
    assert canonical_json(journal_a.to_dict()) == canonical_json(journal_b.to_dict())

    # Round-trip preserves digest.
    restored = SearchJournal.from_dict(journal_a.to_dict())
    assert restored.content_digest == journal_a.content_digest
    assert restored == journal_a

    # Hits reference the snapshot.
    rec = journal_a.records[0]
    assert rec.source_snapshot_cid == snap_a
    assert rec.adapter.adapter_name == LOCAL_SNAPSHOT_ADAPTER_NAME
    assert rec.outcome in {QueryOutcomeKind.SUCCESS, QueryOutcomeKind.EMPTY}
    if rec.outcome is QueryOutcomeKind.SUCCESS:
        assert rec.hits
        assert rec.hits[0].source_links[0].source_cid


def test_local_snapshot_bind_source_snapshot_cid() -> None:
    runtime, snap = _local_runtime()
    journal = runtime.execute_plan(_local_plan())
    assert snap in journal.source_snapshot_cids
    assert all(r.source_snapshot_cid == snap for r in journal.records)


# ---------------------------------------------------------------------------
# Recorded ODP transport replay
# ---------------------------------------------------------------------------


def test_recorded_odp_transport_replays_identically() -> None:
    """Same recorded exchanges + plan → identical journals (consume-once transport)."""
    apps = [
        _odp_app("16100001", "Encoding apparatus for claim text"),
        _odp_app("16100002", "Retrieval system for patents"),
    ]
    body = _odp_search_body(apps)

    def _run() -> SearchJournal:
        transport = _odp_transport(
            [
                RecordedExchange(
                    method="POST",
                    path="/api/v1/patent/applications/search",
                    status=200,
                    body=body,
                )
            ]
        )
        runtime = _odp_runtime(transport)
        return runtime.execute_plan(_odp_plan())

    journal_a = _run()
    journal_b = _run()

    assert journal_a.content_digest == journal_b.content_digest
    assert journal_a.records[0].outcome is QueryOutcomeKind.SUCCESS
    assert journal_a.records[0].result_count == 2
    assert journal_a.records[0].hits[0].document_id == "doc:odp:16100001"
    assert journal_a.records[0].hits[0].rank == 1
    assert journal_a.records[0].adapter.adapter_name == ODP_PUBLIC_ADAPTER_NAME
    # Database / time / cutoff present.
    rec = journal_a.records[0]
    assert rec.database is SearchDatabase.ODP_PATENT_FILE_WRAPPER
    assert rec.search_time_utc == SEARCH_TIME
    assert rec.corpus_cutoff == CORPUS_CUTOFF
    assert_journal_query_identity(journal_a)


def test_recorded_odp_rate_limit_remains_explicit() -> None:
    transport = _odp_transport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=429,
                body={"error": "rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
        ]
    )
    runtime = _odp_runtime(transport)
    journal = runtime.execute_plan(_odp_plan())
    rec = journal.records[0]
    assert rec.outcome is QueryOutcomeKind.RATE_LIMITED
    assert rec.error_code is not None
    assert "rate" in (rec.error_code or "").lower() or rec.status_code == 429
    assert rec.claims_corpus_searched is False
    assert journal.has_rate_limit()
    # Rate limit is not rewritten as empty success.
    assert rec.outcome is not QueryOutcomeKind.SUCCESS
    assert rec.outcome is not QueryOutcomeKind.EMPTY
    assert_journal_query_identity(journal)


def test_recorded_odp_upstream_failure_remains_explicit() -> None:
    transport = _odp_transport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=503,
                body={"error": "service unavailable"},
            )
        ]
    )
    runtime = _odp_runtime(transport)
    journal = runtime.execute_plan(_odp_plan())
    rec = journal.records[0]
    assert rec.outcome in {
        QueryOutcomeKind.UPSTREAM_ERROR,
        QueryOutcomeKind.FAILURE,
        QueryOutcomeKind.RETRY_BUDGET_EXHAUSTED,
    }
    assert rec.claims_corpus_searched is False
    assert journal.has_explicit_failure()
    assert rec.error_code or rec.error_message


# ---------------------------------------------------------------------------
# Query identity: database, time, cutoff
# ---------------------------------------------------------------------------


def test_every_query_identifies_database_time_and_cutoff() -> None:
    runtime, _ = _local_runtime()
    plan = PublicSearchPlan(
        plan_id="plan:multi-q",
        subject_id="subject:app-1",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q1",
                query_text="encoding",
                database=SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
                rank_cutoff=3,
            ),
            PublicSearchQuery(
                query_id="q2",
                query_text="network classification",
                database=SearchDatabase.US_PATENTS,
                rank_cutoff=3,
            ),
        ),
        pre_ranking_filters=_filters(applied=True),
    )
    journal = runtime.execute_plan(plan)
    assert len(journal.records) == 2
    assert_journal_query_identity(journal)
    for rec in journal.records:
        assert rec.database is not None
        assert rec.search_time_utc == SEARCH_TIME
        assert rec.corpus_cutoff == CORPUS_CUTOFF
        assert rec.rank_cutoff >= 1


def test_query_record_rejects_missing_identity() -> None:
    adapter = NamedAdapterIdentity(
        adapter_name="local_public_snapshot.v1",
        adapter_kind=AdapterKind.LOCAL_SNAPSHOT,
        supported_corpora=(SearchCorpus.US_PATENTS,),
    )
    with pytest.raises(Exception):
        build_query_record(
            query_id="q-bad",
            query_text="x",
            database=SearchDatabase.US_PATENTS,
            search_time_utc="",  # missing
            corpus_cutoff=CORPUS_CUTOFF,
            rank_cutoff=5,
            adapter=adapter,
            outcome=QueryOutcomeKind.SUCCESS,
        )


# ---------------------------------------------------------------------------
# Foreign / NPL coverage gates
# ---------------------------------------------------------------------------


def test_journal_cannot_mark_foreign_or_npl_without_named_adapter() -> None:
    """US-only runtime leaves foreign/NPL unsearched even on success."""
    runtime, _ = _local_runtime()
    journal = runtime.execute_plan(_local_plan())
    assert SearchCorpus.FOREIGN_PATENTS in journal.unsearched_corpora
    assert SearchCorpus.NPL in journal.unsearched_corpora
    assert SearchCorpus.FOREIGN_PATENTS not in journal.searched_corpora
    assert SearchCorpus.NPL not in journal.searched_corpora
    assert_no_unjustified_foreign_npl(journal)

    # Attempting to forge a journal that claims foreign searched without adapter fails.
    us_rec = journal.records[0]
    foreign_adapter = NamedAdapterIdentity(
        adapter_name="us_only.v1",
        adapter_kind=AdapterKind.LOCAL_SNAPSHOT,
        supported_corpora=(SearchCorpus.US_PATENTS,),  # no foreign support
    )
    with pytest.raises(ForeignOrNplCoverageError):
        build_query_record(
            query_id="q-foreign-forge",
            query_text="EP search",
            database=SearchDatabase.FOREIGN_PATENTS,
            search_time_utc=SEARCH_TIME,
            corpus_cutoff=CORPUS_CUTOFF,
            rank_cutoff=5,
            adapter=foreign_adapter,
            outcome=QueryOutcomeKind.SUCCESS,
            claims_corpus_searched=True,
            hits=(
                JournalHit(
                    document_id="doc:ep-1",
                    rank=1,
                    score=1.0,
                    source_links=(
                        make_source_link(
                            source_cid=CID_SOURCE,
                            artifact_id="artifact:ep-1",
                        ),
                    ),
                ),
            ),
        )

    # Journal-level claim also fails closed.
    with pytest.raises(ForeignOrNplCoverageError):
        SearchJournal(
            schema_version=SEARCH_JOURNAL_SCHEMA_VERSION,
            journal_id="journal:forge",
            subject_id="subject:x",
            search_date_utc=SEARCH_TIME,
            corpus_cutoff=CORPUS_CUTOFF,
            records=(us_rec,),
            searched_corpora=(SearchCorpus.FOREIGN_PATENTS,),
        )


def test_named_foreign_adapter_must_actually_run_to_claim_searched() -> None:
    """Registered-but-unrun foreign adapter does not mark corpus searched.

    When a foreign query runs against a named adapter with a real backend,
    foreign may be marked searched. Without a run, it stays unsearched.
    """
    local_runtime, _ = _local_runtime()

    # 1) Foreign adapter registered but plan only runs US queries → unsearched.
    foreign = NamedCoverageAdapter(
        adapter_name="foreign_patent_epo.v1",
        adapter_kind=AdapterKind.FOREIGN_PATENT,
        supported_corpora=(SearchCorpus.FOREIGN_PATENTS,),
        search_fn=None,  # no backend
    )
    runtime = local_runtime.register(foreign)
    journal = runtime.execute_plan(_local_plan())
    assert SearchCorpus.FOREIGN_PATENTS not in journal.searched_corpora
    assert SearchCorpus.FOREIGN_PATENTS in journal.unsearched_corpora

    # 2) Plan targets foreign but backend unavailable → failure, not searched.
    foreign_plan = PublicSearchPlan(
        plan_id="plan:foreign-1",
        subject_id="subject:app-f",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q-foreign",
                query_text="EP encoding",
                database=SearchDatabase.FOREIGN_PATENTS,
                rank_cutoff=5,
                preferred_adapter="foreign_patent_epo.v1",
            ),
        ),
    )
    journal_f = runtime.execute_plan(foreign_plan)
    rec = journal_f.records[0]
    assert rec.outcome is QueryOutcomeKind.FAILURE
    assert rec.claims_corpus_searched is False
    assert SearchCorpus.FOREIGN_PATENTS not in journal_f.searched_corpora

    # 3) Named adapter with real backend that runs → may claim searched.
    def _fake_foreign_search(
        query: PublicSearchQuery,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None,
    ) -> AdapterSearchResult:
        del search_time_utc, corpus_cutoff, pre_ranking_filters
        return AdapterSearchResult(
            outcome=QueryOutcomeKind.SUCCESS,
            hits=(
                JournalHit(
                    document_id="doc:ep-991",
                    rank=1,
                    score=9.0,
                    source_links=(
                        make_source_link(
                            source_cid=CID_SOURCE,
                            artifact_id="artifact:ep-991",
                            end=20,
                        ),
                    ),
                    identifiers={"publicationNumber": "EP0999991"},
                ),
            ),
            result_count=1,
            source_snapshot_cid="bafybeigforeignsnap000000000000000000000000000000001",
        )

    foreign_live = NamedCoverageAdapter(
        adapter_name="foreign_patent_epo.v1",
        adapter_kind=AdapterKind.FOREIGN_PATENT,
        supported_corpora=(SearchCorpus.FOREIGN_PATENTS,),
        search_fn=_fake_foreign_search,
    )
    runtime_live = build_public_prior_art_runtime(extra_adapters=(foreign_live,))
    journal_live = runtime_live.execute_plan(foreign_plan)
    assert journal_live.records[0].outcome is QueryOutcomeKind.SUCCESS
    assert journal_live.records[0].claims_corpus_searched is True
    assert SearchCorpus.FOREIGN_PATENTS in journal_live.searched_corpora
    assert_no_unjustified_foreign_npl(journal_live)


def test_npl_requires_named_adapter_run() -> None:
    npl = NamedCoverageAdapter(
        adapter_name="npl_licensed.v1",
        adapter_kind=AdapterKind.NPL,
        supported_corpora=(SearchCorpus.NPL,),
        search_fn=None,
    )
    runtime = PriorArtSearchRuntime(adapters={npl.identity.adapter_name: npl})
    plan = PublicSearchPlan(
        plan_id="plan:npl",
        subject_id="subject:npl",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q-npl",
                query_text="IEEE encoding paper",
                database=SearchDatabase.NPL,
                rank_cutoff=3,
            ),
        ),
    )
    journal = runtime.execute_plan(plan)
    assert journal.records[0].outcome is QueryOutcomeKind.FAILURE
    assert SearchCorpus.NPL not in journal.searched_corpora
    assert SearchCorpus.NPL in journal.unsearched_corpora


def test_missing_adapter_for_database_is_explicit() -> None:
    runtime = PriorArtSearchRuntime(adapters={})
    plan = _local_plan()
    journal = runtime.execute_plan(plan)
    rec = journal.records[0]
    assert rec.outcome is QueryOutcomeKind.ADAPTER_NOT_REGISTERED
    assert rec.claims_corpus_searched is False
    assert rec.error_code == "adapter_not_registered"
    assert_journal_query_identity(journal)


# ---------------------------------------------------------------------------
# Multi-backend + combined acceptance
# ---------------------------------------------------------------------------


def test_combined_local_and_odp_plan() -> None:
    local_adapter = build_local_snapshot_adapter(
        _public_docs(),
        filters=_filters(applied=False),
        snapshot_cid="bafybeiglocalsnapfixed000000000000000000000000000002",
    )
    transport = _odp_transport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body=_odp_search_body(
                    [_odp_app("16999999", "Hybrid public search hit")]
                ),
            )
        ]
    )
    odp_adapter = build_odp_adapter_from_transport(
        transport,
        source_snapshot_cid="bafybeigodpsnapshotfixed0000000000000000000000000002",
    )
    runtime = build_public_prior_art_runtime(
        local_adapter=local_adapter,
        odp_adapter=odp_adapter,
    )
    plan = PublicSearchPlan(
        plan_id="plan:combined",
        subject_id="subject:combined",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=(
            PublicSearchQuery(
                query_id="q-local",
                query_text="encoding claim text",
                database=SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
                rank_cutoff=5,
                preferred_adapter=LOCAL_SNAPSHOT_ADAPTER_NAME,
            ),
            PublicSearchQuery(
                query_id="q-odp",
                query_text="hybrid public",
                database=SearchDatabase.ODP_PATENT_FILE_WRAPPER,
                rank_cutoff=5,
                preferred_adapter=ODP_PUBLIC_ADAPTER_NAME,
            ),
        ),
        pre_ranking_filters=_filters(applied=True),
    )
    journal = runtime.execute_plan(plan)
    assert len(journal.records) == 2
    assert_journal_query_identity(journal)
    assert_no_unjustified_foreign_npl(journal)
    names = {r.adapter.adapter_name for r in journal.records}
    assert LOCAL_SNAPSHOT_ADAPTER_NAME in names
    assert ODP_PUBLIC_ADAPTER_NAME in names
    # Foreign/NPL still unsearched.
    assert SearchCorpus.FOREIGN_PATENTS in journal.unsearched_corpora
    assert SearchCorpus.NPL in journal.unsearched_corpora


def test_journal_round_trip_and_schema_pins() -> None:
    runtime, _ = _local_runtime()
    journal = runtime.execute_plan(_local_plan())
    payload = journal.to_dict()
    assert payload["schema_version"] == SEARCH_JOURNAL_SCHEMA_VERSION
    restored = SearchJournal.from_dict(payload)
    assert restored.to_dict() == payload
    assert content_digest(payload) == journal.content_digest
    # Runtime version pin present in metadata.
    assert journal.metadata.get("runtime_schema") == PRIOR_ART_RUNTIME_SCHEMA_VERSION


def test_odp_client_direct_recorded_search_feeds_adapter() -> None:
    """Sanity: PatentFileWrapperClient search over recorded transport works."""
    transport = _odp_transport(
        [
            RecordedExchange(
                method="POST",
                path="/api/v1/patent/applications/search",
                status=200,
                body=_odp_search_body([_odp_app("16123456", "Direct client title")]),
            )
        ]
    )
    client = PatentFileWrapperClient(
        transport=transport,
        api_key=ApiKeySecret("test-key-not-live"),
        base_url="https://api.uspto.gov",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0),
    )
    result = client.search({"q": "encoding"}, limit=5)
    assert result.kind is ProviderOutcomeKind.SUCCESS
    assert result.ok
    adapter = build_odp_adapter_from_transport(
        _odp_transport(
            [
                RecordedExchange(
                    method="POST",
                    path="/api/v1/patent/applications/search",
                    status=200,
                    body=_odp_search_body(
                        [_odp_app("16123456", "Direct client title")]
                    ),
                )
            ]
        )
    )
    query = PublicSearchQuery(
        query_id="q-direct",
        query_text="encoding",
        database=SearchDatabase.ODP_PATENT_FILE_WRAPPER,
        rank_cutoff=5,
    )
    ar = adapter.search(
        query,
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
    )
    assert ar.outcome is QueryOutcomeKind.SUCCESS
    assert ar.hits
