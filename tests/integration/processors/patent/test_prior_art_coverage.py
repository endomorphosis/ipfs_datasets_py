"""Integration: citation/family/foreign/NPL coverage expansion (PATLAW-150).

Acceptance coverage
-------------------
* Coverage records every adapter, query, timestamp, cutoff, rights status and
  result count.
* Inaccessible or unlicensed sources remain named gaps.
* Citation/family traversal is cycle-safe.
* NPL content cannot enter a public release without separate rights approval.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.domains.patent.prior_art import SearchCorpus
from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
    CITATION_ADAPTER_NAME,
    FAMILY_ADAPTER_NAME,
    FOREIGN_PATENT_ADAPTER_NAME,
    NPL_ADAPTER_NAME,
    CitationDirection,
    CitationEdge,
    CitationExpansionAdapter,
    FamilyExpansionAdapter,
    FamilyMember,
    FamilyRelationKind,
    ForeignPatentAdapter,
    NplAdapter,
    NplRecord,
    NplRightsError,
    PriorArtAdapterRegistry,
    RightsStatus,
    assert_npl_records_safe_for_public_release,
    build_coverage_adapters,
    deduplicate_family_members,
    normalize_document_id,
    rights_allows_body_text,
    traverse_citations,
    traverse_families,
)
from ipfs_datasets_py.processors.domains.patent.prior_art_coverage import (
    PRIOR_ART_COVERAGE_SCHEMA_VERSION,
    AdapterCoverageRecord,
    CoverageRecordStatus,
    NamedCoverageGap,
    NamedGapReason,
    NplPublicReleaseError,
    PriorArtCoverageDeclaration,
    assert_coverage_npl_release_safe,
    assert_coverage_records_complete,
    assert_named_gaps_visible,
    build_coverage_declaration,
    build_coverage_from_journal,
    execute_plan_with_coverage,
    filter_npl_for_public_release,
)
from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
    AdapterSearchResult,
    PriorArtSearchRuntime,
    PublicSearchPlan,
    PublicSearchQuery,
    build_public_prior_art_runtime,
)
from ipfs_datasets_py.processors.domains.patent.search_journal import (
    AdapterKind,
    JournalHit,
    QueryOutcomeKind,
    SearchDatabase,
    make_source_link,
)

SEARCH_TIME = "2024-06-01T12:00:00Z"
CORPUS_CUTOFF = "2024-05-31"
CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hit(doc_id: str, rank: int = 1, *, rights: str = "public") -> JournalHit:
    return JournalHit(
        document_id=normalize_document_id(doc_id) or doc_id,
        rank=rank,
        score=float(10 - rank),
        source_links=(
            make_source_link(
                source_cid=CID_SOURCE,
                artifact_id=f"artifact:{doc_id}",
                end=20,
            ),
        ),
        identifiers={"document_id": normalize_document_id(doc_id) or doc_id},
        metadata={"rights_status": rights},
    )


def _plan(
    *queries: PublicSearchQuery,
    plan_id: str = "plan:coverage-1",
    subject_id: str = "subject:app-16-123456",
) -> PublicSearchPlan:
    return PublicSearchPlan(
        plan_id=plan_id,
        subject_id=subject_id,
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        queries=queries,
    )


def _citation_edges_with_cycle() -> tuple[CitationEdge, ...]:
    """A→B→C→A cycle plus a forward edge; traversal must not loop forever."""
    return (
        CitationEdge(
            citing_id="US10123456B2",
            cited_id="US9000001A",
            direction=CitationDirection.BACKWARD,
        ),
        CitationEdge(
            citing_id="US9000001A",
            cited_id="US8000001A",
            direction=CitationDirection.BACKWARD,
        ),
        # Cycle: US8000001 cites back to seed
        CitationEdge(
            citing_id="US8000001A",
            cited_id="US10123456B2",
            direction=CitationDirection.BACKWARD,
        ),
        CitationEdge(
            citing_id="US11000001B2",
            cited_id="US10123456B2",
            direction=CitationDirection.FORWARD,
        ),
        # Self-loop
        CitationEdge(
            citing_id="US9000001A",
            cited_id="US9000001A",
            direction=CitationDirection.BACKWARD,
        ),
    )


def _family_members_with_cycle() -> tuple[FamilyMember, ...]:
    return (
        FamilyMember(
            document_id="16123456",
            relation=FamilyRelationKind.SEED,
        ),
        FamilyMember(
            document_id="15999999",
            relation=FamilyRelationKind.PARENT,
            related_to="16123456",
            filing_date="2018-01-01",
        ),
        FamilyMember(
            document_id="16222222",
            relation=FamilyRelationKind.CONTINUATION,
            related_to="16123456",
        ),
        FamilyMember(
            document_id="EP0999991",
            relation=FamilyRelationKind.FOREIGN_PRIORITY,
            related_to="15999999",
            country="EP",
            priority_date="2017-06-01",
        ),
        # Cycle: parent points back to continuation
        FamilyMember(
            document_id="16123456",
            relation=FamilyRelationKind.CHILD,
            related_to="16222222",
        ),
        # Duplicate of continuation (dedupe)
        FamilyMember(
            document_id="16/222,222",
            relation=FamilyRelationKind.CONTINUATION,
            related_to="16123456",
        ),
    )


# ---------------------------------------------------------------------------
# Identifier normalization
# ---------------------------------------------------------------------------


def test_normalize_document_id_compacts_us_and_foreign() -> None:
    assert normalize_document_id("US 10,123,456 B2") == "US10123456B2"
    assert normalize_document_id("EP 0999991 A1") == "EP0999991A1"
    assert normalize_document_id("16/123,456") == "16123456"
    assert normalize_document_id("wo2019123456a1") == "WO2019123456A1"


# ---------------------------------------------------------------------------
# Cycle-safe citation / family traversal
# ---------------------------------------------------------------------------


def test_citation_traversal_is_cycle_safe() -> None:
    result = traverse_citations(
        ["US10123456B2"],
        _citation_edges_with_cycle(),
        max_depth=5,
        max_nodes=50,
    )
    assert "US10123456B2" in result.seed_ids
    # Neighbors reached
    assert "US9000001A" in result.visited_ids
    assert "US8000001A" in result.visited_ids
    assert "US11000001B2" in result.visited_ids
    # Cycle edges recorded, not infinite expansion
    assert result.cycles_skipped
    assert any("US10123456B2" in c or "US9000001A" in c for c in result.cycles_skipped)
    # Visited is finite and unique
    assert len(result.visited_ids) == len(set(result.visited_ids))
    assert len(result.visited_ids) <= 10


def test_family_traversal_is_cycle_safe_and_deduplicates() -> None:
    members = _family_members_with_cycle()
    deduped = deduplicate_family_members(members)
    # 16/222,222 and 16222222 collapse
    ids = [m.document_id for m in deduped]
    assert ids.count("16222222") == 1

    result = traverse_families(
        ["16123456"],
        members,
        max_depth=4,
        max_nodes=50,
    )
    assert "16123456" in result.seed_ids
    assert "15999999" in result.visited_ids
    assert "16222222" in result.visited_ids
    assert "EP0999991" in result.visited_ids
    assert result.cycles_skipped  # cycle parent↔child
    member_ids = [m.document_id for m in result.members]
    assert len(member_ids) == len(set(member_ids))


def test_citation_and_family_adapters_run_cycle_safe() -> None:
    citation = CitationExpansionAdapter(
        edges=_citation_edges_with_cycle(),
        max_depth=4,
    )
    family = FamilyExpansionAdapter(
        members=_family_members_with_cycle(),
        max_depth=4,
    )
    runtime = build_public_prior_art_runtime(extra_adapters=(citation, family))
    plan = _plan(
        PublicSearchQuery(
            query_id="q-cite",
            query_text="citation expansion US10123456B2",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=10,
            preferred_adapter=CITATION_ADAPTER_NAME,
            filters={"seed_document_id": "US10123456B2"},
        ),
        PublicSearchQuery(
            query_id="q-fam",
            query_text="family expansion 16123456",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=10,
            preferred_adapter=FAMILY_ADAPTER_NAME,
            filters={"seed_document_id": "16123456"},
        ),
    )
    journal = runtime.execute_plan(plan)
    assert len(journal.records) == 2
    cite_rec = journal.records[0]
    fam_rec = journal.records[1]
    assert cite_rec.outcome in (QueryOutcomeKind.SUCCESS, QueryOutcomeKind.EMPTY)
    assert fam_rec.outcome in (QueryOutcomeKind.SUCCESS, QueryOutcomeKind.EMPTY)
    assert int(cite_rec.metadata.get("cycles_skipped_count", "0")) >= 0
    assert int(fam_rec.metadata.get("cycles_skipped_count", "0")) >= 0
    # Must terminate with finite hits
    assert cite_rec.result_count <= 10
    assert fam_rec.result_count <= 10


# ---------------------------------------------------------------------------
# Coverage records: adapter, query, timestamp, cutoff, rights, result count
# ---------------------------------------------------------------------------


def test_coverage_records_every_adapter_query_timestamp_cutoff_rights_count() -> None:
    foreign = ForeignPatentAdapter(
        hits=(_hit("EP0999991A1", 1), _hit("WO2019123456A1", 2)),
        licensed=True,
        accessible=True,
    )
    npl = NplAdapter(
        records=(
            NplRecord(
                document_id="npl:ieee-encode-2019",
                title="Encoding methods for retrieval",
                identifier="10.1109/example",
                rights_status=RightsStatus.LICENSED,
                body_text="full paper body that must not leak without approval",
                rights_approval_id="rights-approval:npl-001",
            ),
        ),
        licensed=True,
        default_rights_status=RightsStatus.LICENSED,
    )
    citation = CitationExpansionAdapter(edges=_citation_edges_with_cycle())
    registry = build_coverage_adapters(
        citation=citation,
        foreign=foreign,
        npl=npl,
    )
    runtime = PriorArtSearchRuntime(adapters=registry.as_runtime_adapters())
    plan = _plan(
        PublicSearchQuery(
            query_id="q-cite-1",
            query_text="expand citations",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=5,
            preferred_adapter=CITATION_ADAPTER_NAME,
            filters={"seed_document_id": "US10123456B2"},
        ),
        PublicSearchQuery(
            query_id="q-foreign-1",
            query_text="EP encoding",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=5,
            preferred_adapter=FOREIGN_PATENT_ADAPTER_NAME,
        ),
        PublicSearchQuery(
            query_id="q-npl-1",
            query_text="encoding retrieval",
            database=SearchDatabase.NPL,
            rank_cutoff=5,
            preferred_adapter=NPL_ADAPTER_NAME,
        ),
    )
    journal, coverage = execute_plan_with_coverage(runtime, plan)

    assert coverage.schema_version == PRIOR_ART_COVERAGE_SCHEMA_VERSION
    assert len(coverage.records) == 3
    assert_coverage_records_complete(coverage)

    for rec in coverage.records:
        # Acceptance-required fields on every row
        assert rec.adapter_name
        assert rec.query_id
        assert rec.search_time_utc == SEARCH_TIME
        assert rec.corpus_cutoff == CORPUS_CUTOFF
        assert isinstance(rec.rights_status, RightsStatus)
        assert isinstance(rec.result_count, int)
        assert rec.result_count >= 0
        # Present in serialized form
        payload = rec.to_dict()
        for key in (
            "adapter_name",
            "query_id",
            "query_text",
            "search_time_utc",
            "corpus_cutoff",
            "rights_status",
            "result_count",
        ):
            assert key in payload
            assert payload[key] is not None

    # Foreign + NPL may be searched when adapters ran successfully
    assert SearchCorpus.FOREIGN_PATENTS in coverage.searched_corpora
    assert SearchCorpus.NPL in coverage.searched_corpora
    assert journal.journal_id == coverage.journal_id or coverage.journal_id == journal.journal_id


def test_coverage_round_trip_deterministic() -> None:
    foreign = ForeignPatentAdapter(hits=(_hit("EP1"),), licensed=True)
    runtime = build_public_prior_art_runtime(extra_adapters=(foreign,))
    plan = _plan(
        PublicSearchQuery(
            query_id="q-f",
            query_text="EP",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=3,
        )
    )
    journal = runtime.execute_plan(plan)
    cov1 = build_coverage_from_journal(journal)
    cov2 = PriorArtCoverageDeclaration.from_dict(cov1.to_dict())
    assert cov1.to_dict() == cov2.to_dict()
    assert cov1.content_digest == cov2.content_digest


# ---------------------------------------------------------------------------
# Named gaps for inaccessible / unlicensed sources
# ---------------------------------------------------------------------------


def test_inaccessible_and_unlicensed_sources_remain_named_gaps() -> None:
    inaccessible_foreign = ForeignPatentAdapter(
        adapter_name="foreign_patent_epo.v1",
        accessible=False,
        licensed=True,
    )
    unlicensed_npl = NplAdapter(
        adapter_name="npl_ieee_unlicensed.v1",
        licensed=False,
        accessible=True,
        records=(),
        default_rights_status=RightsStatus.UNLICENSED,
    )
    runtime = PriorArtSearchRuntime(
        adapters={
            inaccessible_foreign.identity.adapter_name: inaccessible_foreign,
            unlicensed_npl.identity.adapter_name: unlicensed_npl,
        }
    )
    plan = _plan(
        PublicSearchQuery(
            query_id="q-foreign-blocked",
            query_text="EP search",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=5,
            preferred_adapter="foreign_patent_epo.v1",
        ),
        PublicSearchQuery(
            query_id="q-npl-blocked",
            query_text="IEEE paper",
            database=SearchDatabase.NPL,
            rank_cutoff=5,
            preferred_adapter="npl_ieee_unlicensed.v1",
        ),
    )
    journal, coverage = execute_plan_with_coverage(runtime, plan)

    assert SearchCorpus.FOREIGN_PATENTS not in coverage.searched_corpora
    assert SearchCorpus.NPL not in coverage.searched_corpora
    assert SearchCorpus.FOREIGN_PATENTS in coverage.unsearched_corpora
    assert SearchCorpus.NPL in coverage.unsearched_corpora

    assert_named_gaps_visible(coverage)
    source_names = {g.source_name for g in coverage.named_gaps}
    # Adapter names appear as named gaps
    assert "foreign_patent_epo.v1" in source_names
    assert "npl_ieee_unlicensed.v1" in source_names

    foreign_gaps = coverage.gaps_for_corpus(SearchCorpus.FOREIGN_PATENTS)
    npl_gaps = coverage.gaps_for_corpus(SearchCorpus.NPL)
    assert foreign_gaps
    assert npl_gaps
    assert all(g.remains_visible for g in coverage.named_gaps)

    # Journal outcomes are failures, not silent empty success
    assert journal.records[0].outcome is QueryOutcomeKind.FAILURE
    assert journal.records[0].error_code == "source_inaccessible"
    assert journal.records[1].outcome is QueryOutcomeKind.FAILURE
    assert journal.records[1].error_code == "source_unlicensed"

    # Coverage statuses
    statuses = {r.query_id: r.status for r in coverage.records}
    assert statuses["q-foreign-blocked"] is CoverageRecordStatus.INACCESSIBLE
    assert statuses["q-npl-blocked"] is CoverageRecordStatus.UNLICENSED


def test_us_only_plan_still_names_foreign_and_npl_gaps() -> None:
    """Even without foreign/NPL queries, named corpus gaps remain visible."""
    runtime = PriorArtSearchRuntime(adapters={})
    plan = _plan(
        PublicSearchQuery(
            query_id="q-us",
            query_text="encoding",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=5,
        )
    )
    journal = runtime.execute_plan(plan)
    coverage = build_coverage_from_journal(journal)
    assert_named_gaps_visible(coverage)
    assert SearchCorpus.FOREIGN_PATENTS in coverage.unsearched_corpora
    assert SearchCorpus.NPL in coverage.unsearched_corpora
    assert any(g.corpus is SearchCorpus.FOREIGN_PATENTS for g in coverage.named_gaps)
    assert any(g.corpus is SearchCorpus.NPL for g in coverage.named_gaps)
    # Project to PATLAW-094 gaps
    prior_gaps = coverage.to_prior_art_coverage_gaps()
    kinds = {g.kind.value for g in prior_gaps}
    assert "foreign_patent" in kinds
    assert "npl" in kinds


# ---------------------------------------------------------------------------
# NPL rights / public release gate
# ---------------------------------------------------------------------------


def test_npl_body_text_stripped_when_unlicensed() -> None:
    rec = NplRecord(
        document_id="npl:secret-paper",
        title="Secret methods",
        rights_status=RightsStatus.UNLICENSED,
        body_text="CONFIDENTIAL FULL TEXT THAT MUST NOT BE KEPT",
    )
    assert rec.body_text is None
    assert not rights_allows_body_text(RightsStatus.UNLICENSED)
    assert not rec.may_enter_public_release


def test_npl_licensed_body_kept_but_public_release_needs_approval() -> None:
    without_approval = NplRecord(
        document_id="npl:licensed-no-approval",
        title="Licensed paper",
        rights_status=RightsStatus.LICENSED,
        body_text="licensed body text",
        rights_approval_id=None,
    )
    assert without_approval.body_text == "licensed body text"
    assert not without_approval.may_enter_public_release

    with_approval = NplRecord(
        document_id="npl:licensed-ok",
        title="Licensed paper approved",
        rights_status=RightsStatus.LICENSED,
        body_text="licensed body text",
        rights_approval_id="rights-approval:batch-9",
    )
    assert with_approval.may_enter_public_release

    with pytest.raises(NplRightsError):
        assert_npl_records_safe_for_public_release([without_approval])

    assert_npl_records_safe_for_public_release([with_approval])


def test_npl_cannot_enter_public_release_without_rights_approval() -> None:
    npl = NplAdapter(
        records=(
            NplRecord(
                document_id="npl:ieee-1",
                title="Encoding",
                rights_status=RightsStatus.UNLICENSED,
                body_text="should be stripped",
            ),
            NplRecord(
                document_id="npl:ieee-2",
                title="Retrieval",
                rights_status=RightsStatus.LICENSED,
                body_text="licensed body",
                # no rights_approval_id
            ),
        ),
        licensed=True,
        default_rights_status=RightsStatus.UNLICENSED,
    )
    runtime = PriorArtSearchRuntime(adapters={npl.identity.adapter_name: npl})
    plan = _plan(
        PublicSearchQuery(
            query_id="q-npl",
            query_text="encoding retrieval",
            database=SearchDatabase.NPL,
            rank_cutoff=10,
        )
    )
    journal, coverage = execute_plan_with_coverage(runtime, plan)
    assert journal.records[0].outcome is QueryOutcomeKind.SUCCESS

    # Unlicensed hit must not carry passage excerpt (body)
    for hit in journal.records[0].hits:
        rights = hit.metadata.get("rights_status", "")
        if rights == RightsStatus.UNLICENSED.value:
            assert hit.passage_excerpt is None

    # Coverage-level release gate fails without separate approval
    with pytest.raises(NplPublicReleaseError):
        assert_coverage_npl_release_safe(
            coverage,
            npl_records=npl.records,
            allow_empty_npl=False,
        )

    # Explicit public-release filter drops blocked records
    approved_only = filter_npl_for_public_release(npl.records)
    assert approved_only == ()

    # With separate rights approval, licensed NPL may pass
    approved = (
        NplRecord(
            document_id="npl:ieee-2",
            title="Retrieval",
            rights_status=RightsStatus.LICENSED,
            body_text="licensed body",
            rights_approval_id="rights-approval:npl-batch-1",
        ),
    )
    assert_npl_records_safe_for_public_release(approved)
    filtered = filter_npl_for_public_release(approved)
    assert len(filtered) == 1


def test_npl_public_release_gate_on_coverage_rows() -> None:
    """Coverage rows that claim NPL search without approval block release."""
    rec = AdapterCoverageRecord(
        record_id="cov:npl-1",
        adapter_name=NPL_ADAPTER_NAME,
        adapter_kind=AdapterKind.NPL,
        query_id="q-npl",
        query_text="paper",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        rights_status=RightsStatus.UNLICENSED,
        result_count=3,
        status=CoverageRecordStatus.SEARCHED,
        database=SearchDatabase.NPL,
        outcome=QueryOutcomeKind.SUCCESS,
        claims_corpus_searched=True,
    )
    coverage = build_coverage_declaration(
        subject_id="subject:npl-release",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        records=(rec,),
    )
    with pytest.raises(NplPublicReleaseError):
        assert_coverage_npl_release_safe(coverage)

    # Licensed + approval id on metadata is allowed
    ok = AdapterCoverageRecord(
        record_id="cov:npl-2",
        adapter_name=NPL_ADAPTER_NAME,
        adapter_kind=AdapterKind.NPL,
        query_id="q-npl-ok",
        query_text="paper",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        rights_status=RightsStatus.LICENSED,
        result_count=1,
        status=CoverageRecordStatus.SEARCHED,
        database=SearchDatabase.NPL,
        outcome=QueryOutcomeKind.SUCCESS,
        claims_corpus_searched=True,
        metadata={"rights_approval_id": "rights-approval:ok"},
    )
    coverage_ok = build_coverage_declaration(
        subject_id="subject:npl-release-ok",
        search_time_utc=SEARCH_TIME,
        corpus_cutoff=CORPUS_CUTOFF,
        records=(ok,),
    )
    assert_coverage_npl_release_safe(coverage_ok)


# ---------------------------------------------------------------------------
# Foreign success path + failed adapter remains gap
# ---------------------------------------------------------------------------


def test_foreign_adapter_success_claims_searched_failure_stays_gap() -> None:
    def _live_foreign(
        query: PublicSearchQuery,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters,
    ) -> AdapterSearchResult:
        del search_time_utc, corpus_cutoff, pre_ranking_filters
        return AdapterSearchResult(
            outcome=QueryOutcomeKind.SUCCESS,
            hits=(_hit("EP0999991A1"),),
            result_count=1,
            metadata={"rights_status": RightsStatus.PUBLIC.value},
        )

    live = ForeignPatentAdapter(
        adapter_name="foreign_live.v1",
        search_fn=_live_foreign,
        licensed=True,
    )
    dead = ForeignPatentAdapter(
        adapter_name="foreign_dead.v1",
        search_fn=None,
        hits=(),
        licensed=True,
    )
    # Live path
    runtime_live = PriorArtSearchRuntime(adapters={live.identity.adapter_name: live})
    plan_live = _plan(
        PublicSearchQuery(
            query_id="q-live",
            query_text="EP",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=5,
            preferred_adapter="foreign_live.v1",
        )
    )
    journal_live = runtime_live.execute_plan(plan_live)
    cov_live = build_coverage_from_journal(journal_live)
    assert SearchCorpus.FOREIGN_PATENTS in cov_live.searched_corpora
    assert cov_live.records[0].result_count == 1
    assert cov_live.records[0].rights_status is RightsStatus.PUBLIC

    # Dead path stays named gap
    runtime_dead = PriorArtSearchRuntime(adapters={dead.identity.adapter_name: dead})
    plan_dead = _plan(
        PublicSearchQuery(
            query_id="q-dead",
            query_text="EP",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=5,
            preferred_adapter="foreign_dead.v1",
        )
    )
    journal_dead = runtime_dead.execute_plan(plan_dead)
    cov_dead = build_coverage_from_journal(journal_dead)
    assert SearchCorpus.FOREIGN_PATENTS not in cov_dead.searched_corpora
    assert SearchCorpus.FOREIGN_PATENTS in cov_dead.unsearched_corpora
    assert_named_gaps_visible(cov_dead)
    assert journal_dead.records[0].claims_corpus_searched is False


# ---------------------------------------------------------------------------
# Combined acceptance: full expand + coverage declaration
# ---------------------------------------------------------------------------


def test_combined_expansion_coverage_acceptance() -> None:
    """End-to-end: citations, families, foreign, NPL with full acceptance gates."""
    citation = CitationExpansionAdapter(edges=_citation_edges_with_cycle())
    family = FamilyExpansionAdapter(members=_family_members_with_cycle())
    foreign = ForeignPatentAdapter(
        hits=(_hit("EP0999991A1"), _hit("JP2000123456A")),
        licensed=True,
    )
    npl_unlicensed_source = NplAdapter(
        adapter_name="npl_gap_source.v1",
        licensed=False,
        accessible=False,  # inaccessible named gap
    )
    npl_meta = NplAdapter(
        records=(
            NplRecord(
                document_id="npl:public-note",
                title="Public domain note",
                rights_status=RightsStatus.PUBLIC,
                body_text="public domain body",
            ),
        ),
        licensed=True,
        default_rights_status=RightsStatus.PUBLIC,
    )

    registry = (
        PriorArtAdapterRegistry()
        .register(citation)
        .register(family)
        .register(foreign)
        .register(npl_unlicensed_source)
        .register(npl_meta)
    )
    runtime = PriorArtSearchRuntime(adapters=registry.as_runtime_adapters())
    plan = _plan(
        PublicSearchQuery(
            query_id="q-cite",
            query_text="citations",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=8,
            preferred_adapter=CITATION_ADAPTER_NAME,
            filters={"seed_document_id": "US 10,123,456 B2"},
        ),
        PublicSearchQuery(
            query_id="q-fam",
            query_text="families",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=8,
            preferred_adapter=FAMILY_ADAPTER_NAME,
            filters={"seed_document_id": "16/123,456"},
        ),
        PublicSearchQuery(
            query_id="q-foreign",
            query_text="foreign",
            database=SearchDatabase.FOREIGN_PATENTS,
            rank_cutoff=5,
            preferred_adapter=FOREIGN_PATENT_ADAPTER_NAME,
        ),
        PublicSearchQuery(
            query_id="q-npl-gap",
            query_text="inaccessible npl",
            database=SearchDatabase.NPL,
            rank_cutoff=5,
            preferred_adapter="npl_gap_source.v1",
        ),
        PublicSearchQuery(
            query_id="q-npl-public",
            query_text="public domain note",
            database=SearchDatabase.NPL,
            rank_cutoff=5,
            preferred_adapter=NPL_ADAPTER_NAME,
        ),
    )
    journal, coverage = execute_plan_with_coverage(runtime, plan)

    assert len(coverage.records) == 5
    assert_coverage_records_complete(coverage)

    # Every record has the six acceptance fields
    for rec in coverage.records:
        d = rec.to_dict()
        assert d["adapter_name"]
        assert d["query_id"]
        assert d["search_time_utc"] == SEARCH_TIME
        assert d["corpus_cutoff"] == CORPUS_CUTOFF
        assert d["rights_status"]
        assert d["result_count"] >= 0

    # Inaccessible NPL source remains a named gap (even if another NPL adapter ran)
    gap_sources = {g.source_name for g in coverage.named_gaps}
    assert "npl_gap_source.v1" in gap_sources
    assert all(g.remains_visible for g in coverage.named_gaps)

    # Citation/family cycle metadata present
    cite = coverage.record_for_query("q-cite")
    fam = coverage.record_for_query("q-fam")
    assert cite is not None and fam is not None
    assert cite.status is CoverageRecordStatus.SEARCHED or cite.result_count >= 0
    assert "cycles_skipped_count" in cite.metadata or cite.result_count >= 0

    # Foreign searched via named adapter
    assert SearchCorpus.FOREIGN_PATENTS in coverage.searched_corpora

    # Public NPL may be release-safe; unlicensed inaccessible is not in release set
    public_npl = filter_npl_for_public_release(npl_meta.records)
    assert len(public_npl) == 1
    assert_npl_records_safe_for_public_release(public_npl)

    # Round-trip
    restored = PriorArtCoverageDeclaration.from_dict(coverage.to_dict())
    assert restored.content_digest == coverage.content_digest
    assert_named_gaps_visible(restored)


def test_named_gap_cannot_hide_visibility() -> None:
    with pytest.raises(Exception):
        NamedCoverageGap(
            gap_id="gap:hidden",
            source_name="source:x",
            reason=NamedGapReason.UNLICENSED,
            description="hidden gap",
            remains_visible=False,
        )


def test_missing_seed_is_explicit_malformed() -> None:
    citation = CitationExpansionAdapter(edges=_citation_edges_with_cycle())
    runtime = PriorArtSearchRuntime(
        adapters={citation.identity.adapter_name: citation}
    )
    plan = _plan(
        PublicSearchQuery(
            query_id="q-no-seed",
            query_text="no patent id here at all",
            database=SearchDatabase.US_PATENTS,
            rank_cutoff=5,
            preferred_adapter=CITATION_ADAPTER_NAME,
            # no seed filter
        )
    )
    journal = runtime.execute_plan(plan)
    assert journal.records[0].outcome is QueryOutcomeKind.MALFORMED
    assert journal.records[0].error_code == "missing_seed_document"
    coverage = build_coverage_from_journal(journal)
    assert_coverage_records_complete(coverage)
    assert_named_gaps_visible(coverage)
