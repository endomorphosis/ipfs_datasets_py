"""Unit tests for source-linked patent retrieval contracts (PATLAW-090)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    DEFAULT_FIELD_WEIGHTS,
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    EmbeddingIdentity,
    FieldWeight,
    FieldWeightConfig,
    FusionResult,
    FusionWeights,
    GeneratedSummary,
    GraphEdge,
    GraphRankHit,
    IndexField,
    MissingPreRankingFiltersError,
    PreRankingFilterViolation,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceAuthorityClaimError,
    SourceLink,
    SourceLinkedIndexRow,
    SourceSpan,
    VectorIndexRow,
    allow_source_authority_for,
    assert_authority_claim_allowed,
    canonical_json,
    claims_source_authority,
    filter_index_rows,
    fuse_ranked_hits,
    is_private_disclosure,
    is_public_disclosure,
    require_pre_ranking_filters,
    requires_quarantine,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CONFIG = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_MODEL = "bafybeimodelidentity000000000000000000000000000000000000001"


def _source_link(**overrides: object) -> SourceLink:
    base = {
        "source_cid": CID_SOURCE,
        "artifact_id": "artifact:cfr-37-1.56",
        "span": SourceSpan(start=0, end=12),
        "source_receipt_id": "receipt:1",
        "authority_tier": "official-base",
    }
    base.update(overrides)
    return SourceLink(**base)  # type: ignore[arg-type]


def _filters(*, applied: bool = True, tenant: str = "tenant-public") -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=tenant,
        as_of_utc="2024-06-01T00:00:00Z",
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=applied,
        denied_provider_call_count=2,
        filter_receipt_id="filter:1",
    )


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


def test_schema_version_pinned() -> None:
    assert RETRIEVAL_CONTRACTS_SCHEMA_VERSION == "patent.retrieval.contracts.v1"


def test_disclosure_helpers() -> None:
    assert is_public_disclosure(DisclosureClass.PUBLIC_OFFICIAL)
    assert is_public_disclosure("public_user")
    assert is_private_disclosure(DisclosureClass.CONFIDENTIAL_APPLICATION)
    assert is_private_disclosure(DisclosureClass.PRIVILEGED_WORK_PRODUCT)
    assert requires_quarantine(DisclosureClass.UNKNOWN)
    assert not requires_quarantine(DisclosureClass.PUBLIC_OFFICIAL)


def test_field_weight_config_default_covers_patent_fields() -> None:
    cfg = FieldWeightConfig.default(config_cid=CID_CONFIG)
    _assert_round_trip(cfg)
    assert set(DEFAULT_FIELD_WEIGHTS) == {f.value for f in IndexField}
    assert cfg.weight_for(IndexField.CLAIMS) == 4.0
    assert cfg.weight_for("title") == 3.0
    assert cfg.k1 == 1.5
    assert cfg.b == 0.75


def test_field_weight_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        FieldWeightConfig(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            weights=(
                FieldWeight(field=IndexField.TITLE, weight=1.0),
                FieldWeight(field=IndexField.TITLE, weight=2.0),
            ),
        )


def test_source_linked_index_row_requires_source_and_fields() -> None:
    row = SourceLinkedIndexRow(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        row_id="row:1",
        document_id="doc:patent-1",
        family=RetrievalFamily.BM25,
        field_values={
            IndexField.TITLE.value: "Method of encoding",
            IndexField.CLAIMS.value: "1. A method comprising...",
            IndexField.CPC.value: "G06F16/00",
        },
        source_links=(_source_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        content_digest=DIGEST_A,
        effective_from_utc="2020-01-01T00:00:00Z",
        field_weights_config_cid=CID_CONFIG,
    )
    _assert_round_trip(row)
    assert row.family is RetrievalFamily.BM25
    assert len(row.source_links) == 1
    assert row.source_links[0].source_cid == CID_SOURCE


def test_source_linked_index_row_rejects_empty_source_links() -> None:
    with pytest.raises(ValueError, match="source link"):
        SourceLinkedIndexRow(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            row_id="row:2",
            document_id="doc:2",
            family=RetrievalFamily.BM25,
            field_values={IndexField.TITLE.value: "x"},
            source_links=(),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id="tenant-public",
            content_digest=DIGEST_A,
        )


def test_embedding_identity_and_vector_row() -> None:
    emb = EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider="local_hash",
        model_id="hashed-term-v1",
        model_version="1.0.0",
        dimension=256,
        config_cid=CID_CONFIG,
        model_cid=CID_MODEL,
    )
    _assert_round_trip(emb)
    row = VectorIndexRow(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        row_id="vec:1",
        document_id="doc:patent-1",
        embedding=emb,
        vector_digest=DIGEST_B,
        source_links=(_source_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        content_digest=DIGEST_A,
    )
    _assert_round_trip(row)
    assert row.embedding.dimension == 256
    assert row.embedding.model_cid == CID_MODEL


def test_source_derived_edge_may_claim_source_authority() -> None:
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:1",
        subject_id="node:a",
        object_id="node:b",
        kind=EdgeKind.CITES,
        provenance=EdgeProvenance.SOURCE_DERIVED,
        authority_claim=AuthorityClaim.SOURCE_BOUND,
        source_links=(_source_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
    )
    _assert_round_trip(edge)
    assert claims_source_authority(edge.authority_claim)
    assert allow_source_authority_for(EdgeProvenance.SOURCE_DERIVED)


def test_candidate_edge_cannot_claim_source_authority() -> None:
    assert not allow_source_authority_for(EdgeProvenance.CANDIDATE)
    with pytest.raises(SourceAuthorityClaimError, match="cannot claim source authority"):
        GraphEdge(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            edge_id="edge:cand",
            subject_id="node:a",
            object_id="node:b",
            kind=EdgeKind.OTHER,
            provenance=EdgeProvenance.CANDIDATE,
            authority_claim=AuthorityClaim.SOURCE_BOUND,
            source_links=(),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id="tenant-public",
        )
    # Allowed when claim is review-only / none.
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:cand-ok",
        subject_id="node:a",
        object_id="node:b",
        kind=EdgeKind.OTHER,
        provenance=EdgeProvenance.CANDIDATE,
        authority_claim=AuthorityClaim.REVIEW_ONLY,
        source_links=(),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
    )
    assert edge.authority_claim is AuthorityClaim.REVIEW_ONLY
    _assert_round_trip(edge)


def test_generated_summary_cannot_claim_source_authority() -> None:
    with pytest.raises(SourceAuthorityClaimError):
        GeneratedSummary(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            summary_id="sum:1",
            document_id="doc:1",
            text_digest=DIGEST_A,
            provenance=EdgeProvenance.GENERATED_SUMMARY,
            authority_claim=AuthorityClaim.SOURCE_BOUND,
            source_links=(),
            disclosure=DisclosureClass.PUBLIC_USER,
            tenant_id="tenant-public",
        )
    summary = GeneratedSummary(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        summary_id="sum:2",
        document_id="doc:1",
        text_digest=DIGEST_A,
        provenance=EdgeProvenance.GENERATED_SUMMARY,
        authority_claim=AuthorityClaim.NONE,
        source_links=(_source_link(),),
        disclosure=DisclosureClass.PUBLIC_USER,
        tenant_id="tenant-public",
        model_id="summarizer-v1",
    )
    assert summary.authority_claim is AuthorityClaim.NONE
    assert not claims_source_authority(summary.authority_claim)
    _assert_round_trip(summary)


def test_assert_authority_claim_allowed_helper() -> None:
    assert (
        assert_authority_claim_allowed(
            EdgeProvenance.SOURCE_DERIVED, AuthorityClaim.SOURCE_BOUND
        )
        is AuthorityClaim.SOURCE_BOUND
    )
    with pytest.raises(SourceAuthorityClaimError):
        assert_authority_claim_allowed(
            EdgeProvenance.GENERATED_SUMMARY, AuthorityClaim.SOURCE_BOUND
        )


def test_graph_rank_hit_round_trip() -> None:
    hit = GraphRankHit(
        node_id="node:1",
        document_id="doc:1",
        score=0.85,
        rank=1,
        path_edge_ids=("edge:1", "edge:2"),
        source_links=(_source_link(),),
    )
    _assert_round_trip(hit)


def test_pre_ranking_filters_mandatory_before_scoring() -> None:
    unapplied = _filters(applied=False)
    with pytest.raises(MissingPreRankingFiltersError, match="before scoring"):
        require_pre_ranking_filters(unapplied)
    with pytest.raises(MissingPreRankingFiltersError):
        require_pre_ranking_filters(None)

    applied = unapplied.mark_applied(filter_receipt_id="filter:done")
    assert applied.applied is True
    assert require_pre_ranking_filters(applied) is applied
    _assert_round_trip(applied)


def test_pre_ranking_filters_reject_unknown_disclosure() -> None:
    with pytest.raises(ValueError, match="unknown"):
        PreRankingFilters(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            tenant_id="tenant-public",
            as_of_utc="2024-06-01T00:00:00Z",
            allowed_disclosures=(DisclosureClass.UNKNOWN,),
            applied=True,
        )


def test_pre_ranking_admit_row() -> None:
    filters = _filters(applied=True)
    filters.admit_row(
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        effective_from_utc="2020-01-01T00:00:00Z",
        effective_to_utc="2030-01-01T00:00:00Z",
    )
    with pytest.raises(PreRankingFilterViolation, match="disclosure"):
        filters.admit_row(
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
            tenant_id="tenant-public",
        )
    with pytest.raises(PreRankingFilterViolation, match="tenant"):
        filters.admit_row(
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id="other-tenant",
        )
    with pytest.raises(PreRankingFilterViolation, match="as-of"):
        filters.admit_row(
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id="tenant-public",
            effective_from_utc="2025-01-01T00:00:00Z",
        )


def test_filter_index_rows_requires_applied_filters() -> None:
    row_ok = SourceLinkedIndexRow(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        row_id="row:ok",
        document_id="doc:ok",
        family=RetrievalFamily.BM25,
        field_values={IndexField.TITLE.value: "ok"},
        source_links=(_source_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        content_digest=DIGEST_A,
        effective_from_utc="2020-01-01T00:00:00Z",
    )
    row_private = SourceLinkedIndexRow(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        row_id="row:priv",
        document_id="doc:priv",
        family=RetrievalFamily.BM25,
        field_values={IndexField.TITLE.value: "secret"},
        source_links=(_source_link(),),
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        tenant_id="tenant-public",
        content_digest=DIGEST_B,
    )
    with pytest.raises(MissingPreRankingFiltersError):
        filter_index_rows([row_ok], _filters(applied=False))

    admitted = filter_index_rows([row_ok, row_private], _filters(applied=True))
    assert [r.row_id for r in admitted] == ["row:ok"]


def test_fusion_requires_applied_filters_and_binds_cids() -> None:
    link = _source_link()
    bm25 = (
        RankedHit(
            document_id="doc:a",
            score=3.0,
            rank=1,
            family=RetrievalFamily.BM25,
            source_links=(link,),
            matched_fields=(IndexField.CLAIMS.value,),
        ),
        RankedHit(
            document_id="doc:b",
            score=1.0,
            rank=2,
            family=RetrievalFamily.BM25,
            source_links=(link,),
        ),
    )
    vector = (
        RankedHit(
            document_id="doc:b",
            score=0.9,
            rank=1,
            family=RetrievalFamily.VECTOR,
            source_links=(link,),
        ),
    )
    graph = (
        RankedHit(
            document_id="doc:c",
            score=0.5,
            rank=1,
            family=RetrievalFamily.GRAPH,
            source_links=(link,),
        ),
    )

    with pytest.raises(MissingPreRankingFiltersError):
        fuse_ranked_hits(
            query_id="q1",
            filters=_filters(applied=False),
            bm25_hits=bm25,
            corpus_cid=CID_CORPUS,
            config_cid=CID_CONFIG,
        )

    result = fuse_ranked_hits(
        query_id="q1",
        filters=_filters(applied=True),
        bm25_hits=bm25,
        vector_hits=vector,
        graph_hits=graph,
        fusion_weights=FusionWeights(bm25=1.0, vector=1.0, graph=0.5),
        corpus_cid=CID_CORPUS,
        config_cid=CID_CONFIG,
        model_cid=CID_MODEL,
        index_cids={"bm25": CID_SOURCE, "vector": CID_CONFIG},
        top_k=10,
    )
    assert isinstance(result, FusionResult)
    assert result.filters.applied is True
    assert result.corpus_cid == CID_CORPUS
    assert result.config_cid == CID_CONFIG
    assert result.model_cid == CID_MODEL
    assert result.fused_hits
    assert result.fused_hits[0].family is RetrievalFamily.FUSION
    assert all(h.source_links for h in result.fused_hits)
    _assert_round_trip(result)


def test_fusion_result_rejects_unapplied_filters_on_construct() -> None:
    with pytest.raises(MissingPreRankingFiltersError):
        FusionResult(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            query_id="q1",
            filters=_filters(applied=False),
            bm25_hits=(),
            vector_hits=(),
            graph_hits=(),
            fused_hits=(),
            fusion_weights=FusionWeights(),
            corpus_cid=CID_CORPUS,
            config_cid=CID_CONFIG,
        )
