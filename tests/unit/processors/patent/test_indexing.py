"""Unit tests for fielded BM25, pinned vector, and graph-fusion indexes (PATLAW-092)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.indexing import (
    DEFAULT_EMBEDDING_CONFIG_CID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_PROVIDER,
    INDEXING_SCHEMA_VERSION,
    TOKENIZER_VERSION,
    EmbeddingCallLedger,
    FieldedBm25Index,
    MissingSourceCIDError,
    PatentIndexDocument,
    build_fielded_bm25_index,
    build_graph_fusion_index,
    build_patent_indexes,
    build_pinned_vector_index,
    chunk_document_atomically,
    content_digest_hex,
    default_embedding_identity,
    embed_texts_for_index,
    expand_graph,
    legal_tokens_present,
    score_fielded_bm25,
    score_pinned_vectors,
    tokenize_patent_text,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    AuthorityClaim,
    EmbeddingIdentity,
    FieldWeightConfig,
    GraphEdge,
    IndexField,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    SourceLink,
    SourceSpan,
    canonical_json,
)

CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CONFIG = DEFAULT_EMBEDDING_CONFIG_CID
CID_MODEL = "bafybeimodelidentity000000000000000000000000000000000000001"
CID_PRIVATE = "bafybeiprivate000000000000000000000000000000000000000000001"


def _link(source_cid: str = CID_SOURCE, artifact_id: str = "artifact:1") -> SourceLink:
    return SourceLink(
        source_cid=source_cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=0, end=12),
        authority_tier="official-base",
    )


def _filters(
    *,
    applied: bool = True,
    tenant: str = "tenant-public",
    as_of: str = "2024-06-01T00:00:00Z",
    denied: int = 0,
) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=tenant,
        as_of_utc=as_of,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=applied,
        denied_provider_call_count=denied,
        filter_receipt_id="filter:unit",
    )


def _doc(
    document_id: str,
    *,
    title: str,
    claims: str = "",
    legal_bases: str = "",
    cpc: str = "",
    numbers: str = "",
    disclosure: DisclosureClass = DisclosureClass.PUBLIC_OFFICIAL,
    tenant_id: str = "tenant-public",
    effective_from_utc: str | None = "2020-01-01T00:00:00Z",
    effective_to_utc: str | None = "2030-01-01T00:00:00Z",
    source_cid: str = CID_SOURCE,
    claim_units: tuple[str, ...] = (),
    extra_fields: dict[str, str] | None = None,
) -> PatentIndexDocument:
    fields = {
        IndexField.TITLE.value: title,
        IndexField.ABSTRACT.value: f"Abstract for {title}",
        IndexField.CLAIMS.value: claims or f"1. A method related to {title}.",
        IndexField.DESCRIPTION.value: f"Description of {title}",
        IndexField.CPC.value: cpc,
        IndexField.IPC.value: cpc,
        IndexField.CITATIONS.value: numbers,
        IndexField.NUMBERS.value: numbers,
        IndexField.LEGAL_BASES.value: legal_bases,
    }
    if extra_fields:
        fields.update(extra_fields)
    fields = {k: v for k, v in fields.items() if v}
    return PatentIndexDocument(
        document_id=document_id,
        field_values=fields,
        source_links=(_link(source_cid=source_cid, artifact_id=f"artifact:{document_id}"),),
        disclosure=disclosure,
        tenant_id=tenant_id,
        effective_from_utc=effective_from_utc,
        effective_to_utc=effective_to_utc,
        claim_units=claim_units,
        section_units=(legal_bases,) if legal_bases else (),
    )


# ---------------------------------------------------------------------------
# Tokenization: legal/patent tokens survive
# ---------------------------------------------------------------------------


def test_legal_and_patent_tokens_survive_tokenization() -> None:
    text = (
        "Analysis under 35 U.S.C. § 102(a)(1) and 37 C.F.R. § 1.56 for "
        "CPC G06F16/00 and patent US11222333 citing claim 1; MPEP § 2106."
    )
    tokens = tokenize_patent_text(text)
    protected = legal_tokens_present(text)
    assert protected, "expected protected legal/patent tokens"
    # Every protected token must appear in the tokenizer output.
    for token in protected:
        assert token in tokens, f"protected token {token!r} did not survive"
    # Spot-check canonical forms.
    joined = " ".join(tokens)
    assert "102" in joined or any("102" in t for t in tokens)
    assert any("g06f" in t for t in tokens)
    assert any("us11222333" in t or "us_11222333" in t for t in tokens)


def test_tokenizer_version_pinned() -> None:
    assert TOKENIZER_VERSION == "patent-legal-tokens/v1"
    assert INDEXING_SCHEMA_VERSION == "patent.indexing.v1"


# ---------------------------------------------------------------------------
# Source CID joins and atomic chunking
# ---------------------------------------------------------------------------


def test_document_requires_source_cid() -> None:
    with pytest.raises(MissingSourceCIDError):
        PatentIndexDocument(
            document_id="doc:x",
            field_values={IndexField.TITLE.value: "x"},
            source_links=(),
            disclosure=DisclosureClass.PUBLIC_OFFICIAL,
            tenant_id="tenant-public",
        )


def test_atomic_chunking_preserves_claim_units() -> None:
    claim = "1. A method comprising applying 35 U.S.C. § 102 analysis."
    doc = _doc(
        "doc:chunk",
        title="Chunked patent",
        claims=claim,
        legal_bases="35 U.S.C. § 102",
        claim_units=(claim, "2. The method of claim 1 further comprising indexing."),
    )
    chunks = chunk_document_atomically(doc)
    claim_chunks = [c for c in chunks if c.kind == "claim"]
    assert len(claim_chunks) == 2
    assert claim_chunks[0].text == claim
    assert all(c.source_links and c.source_links[0].source_cid for c in chunks)


# ---------------------------------------------------------------------------
# Pre-ranking filters run first
# ---------------------------------------------------------------------------


def test_filters_must_be_applied_before_bm25_build() -> None:
    docs = [_doc("doc:a", title="Alpha")]
    with pytest.raises(MissingPreRankingFiltersError):
        build_fielded_bm25_index(docs, filters=_filters(applied=False))


def test_authority_as_of_disclosure_tenant_filters_run_first() -> None:
    docs = [
        _doc("doc:public", title="Public encode", legal_bases="35 U.S.C. § 102"),
        _doc(
            "doc:private",
            title="Secret",
            disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
            source_cid=CID_PRIVATE,
        ),
        _doc(
            "doc:future",
            title="Future",
            effective_from_utc="2025-01-01T00:00:00Z",
        ),
        _doc(
            "doc:other-tenant",
            title="Other tenant",
            tenant_id="tenant-other",
        ),
    ]
    index = build_fielded_bm25_index(docs, filters=_filters(applied=True))
    ids = {d.document_id for d in index.documents}
    assert ids == {"doc:public"}
    assert index.filters_receipt["applied"] is True
    # Every remaining row joins to a source CID.
    for doc in index.documents:
        assert doc.source_links
        assert all(link.source_cid for link in doc.source_links)


# ---------------------------------------------------------------------------
# Fielded BM25
# ---------------------------------------------------------------------------


def test_fielded_bm25_indexes_all_patent_fields_and_scores() -> None:
    docs = [
        _doc(
            "doc:encode",
            title="Method of encoding",
            claims="1. Applying 35 U.S.C. § 102 prior art.",
            legal_bases="35 U.S.C. § 102(a)(1)",
            cpc="G06F16/00",
            numbers="US11222333",
        ),
        _doc(
            "doc:network",
            title="Network security",
            claims="1. Cipher module.",
            legal_bases="35 U.S.C. § 103",
            cpc="H04L9/32",
            numbers="US10123456B2",
        ),
    ]
    weights = FieldWeightConfig.default(config_cid=CID_CONFIG)
    index = build_fielded_bm25_index(
        docs, filters=_filters(applied=True), field_weights=weights, corpus_cid=CID_CORPUS
    )
    assert index.backend == "fielded_bm25"
    assert index.stats["document_count"] == 2
    # Claims field should be present with protected tokens.
    encode = next(d for d in index.documents if d.document_id == "doc:encode")
    field_names = {f.field for f in encode.fields}
    assert IndexField.CLAIMS.value in field_names
    assert IndexField.CPC.value in field_names
    assert encode.matched_token_samples  # legal tokens survived into samples
    assert all(link.source_cid for link in encode.source_links)

    hits = score_fielded_bm25(
        "35 U.S.C. § 102 encoding G06F16/00", index, top_k=5
    )
    assert hits
    assert hits[0]["document_id"] == "doc:encode"
    assert hits[0]["source_links"]
    assert hits[0]["source_links"][0]["source_cid"] == CID_SOURCE
    assert "claims" in hits[0]["matched_fields"] or hits[0]["matched_terms"]


def test_fielded_bm25_round_trip_dict() -> None:
    docs = [_doc("doc:rt", title="Round trip", cpc="G06F16/00")]
    index = build_fielded_bm25_index(docs, filters=_filters(applied=True))
    restored = FieldedBm25Index.from_dict(index.to_dict())
    assert restored.content_digest == index.content_digest
    assert restored.to_dict() == index.to_dict()


# ---------------------------------------------------------------------------
# Pinned vector: embedding identity recorded; private route isolation
# ---------------------------------------------------------------------------


def test_pinned_vector_records_embedding_provider_model_config() -> None:
    docs = [
        _doc("doc:v1", title="Vector patent one", legal_bases="35 U.S.C. § 102"),
        _doc("doc:v2", title="Vector patent two", legal_bases="35 U.S.C. § 103"),
    ]
    identity = default_embedding_identity(
        config_cid=CID_CONFIG, model_cid=CID_MODEL, dimension=64
    )
    index = build_pinned_vector_index(
        docs,
        filters=_filters(applied=True),
        embedding=identity,
        corpus_cid=CID_CORPUS,
        allow_remote=False,
    )
    assert index.embedding.provider == DEFAULT_EMBEDDING_PROVIDER
    assert index.embedding.model_id == DEFAULT_EMBEDDING_MODEL_ID
    assert index.embedding.config_cid == CID_CONFIG
    assert index.embedding.model_cid == CID_MODEL
    assert index.embedding.dimension == 64
    assert len(index.documents) == 2
    for doc in index.documents:
        assert doc.row.embedding.provider == identity.provider
        assert doc.row.embedding.model_id == identity.model_id
        assert doc.row.embedding.config_cid == identity.config_cid
        assert doc.row.source_links
        assert doc.row.vector_digest
        assert len(doc.vector) == 64

    hits = score_pinned_vectors("Vector patent one 102", index, top_k=2)
    assert hits
    assert hits[0]["source_links"]
    assert hits[0]["embedding"]["provider"] == identity.provider


def test_denied_private_routes_make_zero_remote_embedding_calls() -> None:
    """Private material must never invoke a remote embedder."""
    remote_calls = {"count": 0}

    def remote_embedder(texts):
        remote_calls["count"] += len(texts)
        return (
            [[0.1] * 32 for _ in texts],
            {"backend": "embeddings_router", "provider": "openai"},
        )

    public = _doc("doc:pub", title="Public vector doc")
    private = _doc(
        "doc:priv",
        title="Private vector doc",
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        source_cid=CID_PRIVATE,
    )
    # Admit private by expanding allowed disclosures for this isolation probe
    # of the embedder path; tenant/as-of still apply.
    filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc="2024-06-01T00:00:00Z",
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
            DisclosureClass.CONFIDENTIAL_APPLICATION,
        ),
        applied=True,
        filter_receipt_id="filter:private-probe",
    )
    identity = EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider="openai",
        model_id="text-embedding-3-small",
        model_version="1",
        dimension=32,
        config_cid=CID_CONFIG,
        model_cid=CID_MODEL,
        backend="embeddings_router",
    )
    ledger = EmbeddingCallLedger()
    index = build_pinned_vector_index(
        [public, private],
        filters=filters,
        embedding=identity,
        allow_remote=True,
        remote_embedder=remote_embedder,
        ledger=ledger,
    )
    # Public may use remote; private must not.
    assert remote_calls["count"] == 1, "only public row may call remote embedder"
    assert ledger.remote_call_count == 1
    assert ledger.denied_remote_count >= 1
    assert index.denied_provider_call_count >= 1
    private_row = next(d for d in index.documents if d.row.document_id == "doc:priv")
    public_row = next(d for d in index.documents if d.row.document_id == "doc:pub")
    # Both still have vectors and source CIDs.
    assert private_row.vector and private_row.row.source_links
    assert public_row.vector and public_row.row.source_links
    # Embedding identity still recorded on every row.
    assert private_row.row.embedding.provider == "openai"
    assert private_row.row.embedding.config_cid == CID_CONFIG


def test_embed_texts_for_index_private_route_zero_remote() -> None:
    calls = {"n": 0}

    def remote(texts):
        calls["n"] += 1
        return [[1.0] * 8 for _ in texts], {"backend": "remote"}

    identity = default_embedding_identity(dimension=8, provider="openai")
    # Force remote classification via provider name.
    identity = EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider="openai",
        model_id="m",
        model_version="1",
        dimension=8,
        config_cid=CID_CONFIG,
        backend="embeddings_router",
    )
    ledger = EmbeddingCallLedger()
    vectors, meta, denied = embed_texts_for_index(
        ["secret text"],
        embedding=identity,
        allow_remote=True,
        private_route=True,
        ledger=ledger,
        remote_embedder=remote,
    )
    assert calls["n"] == 0
    assert meta.get("remote_calls") == 0
    assert denied >= 1
    assert vectors and len(vectors[0]) == 8
    assert ledger.remote_call_count == 0


# ---------------------------------------------------------------------------
# Graph fusion index
# ---------------------------------------------------------------------------


def test_graph_index_joins_nodes_and_edges_to_source_cid() -> None:
    docs = [
        _doc("doc:a", title="Alpha patent", numbers="US1"),
        _doc("doc:b", title="Beta patent", numbers="US2"),
    ]
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:a-cites-b",
        subject_id="node:doc:a",
        object_id="node:doc:b",
        kind=EdgeKind.CITES,
        provenance=EdgeProvenance.SOURCE_DERIVED,
        authority_claim=AuthorityClaim.SOURCE_BOUND,
        source_links=(_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        weight=1.0,
    )
    index = build_graph_fusion_index(
        docs, filters=_filters(applied=True), edges=[edge], corpus_cid=CID_CORPUS
    )
    assert len(index.nodes) == 2
    assert len(index.edges) == 1
    for node in index.nodes:
        assert node.source_links and node.source_links[0].source_cid
    for e in index.edges:
        assert e.source_links and e.source_links[0].source_cid

    expanded = expand_graph(["doc:a"], index, top_k=5, max_hops=2)
    assert expanded
    assert any(item["document_id"] == "doc:b" for item in expanded)
    assert all(item["source_links"] for item in expanded)


# ---------------------------------------------------------------------------
# Repeat builds identical
# ---------------------------------------------------------------------------


def test_repeat_builds_identical() -> None:
    docs = [
        _doc(
            "doc:encode",
            title="Method of encoding",
            claims="1. Applying 35 U.S.C. § 102.",
            legal_bases="35 U.S.C. § 102",
            cpc="G06F16/00",
            numbers="US11222333",
            claim_units=("1. Applying 35 U.S.C. § 102.",),
        ),
        _doc(
            "doc:network",
            title="Network security",
            legal_bases="35 U.S.C. § 103",
            cpc="H04L9/32",
        ),
    ]
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:cites",
        subject_id="node:doc:encode",
        object_id="node:doc:network",
        kind=EdgeKind.CITES,
        provenance=EdgeProvenance.SOURCE_DERIVED,
        authority_claim=AuthorityClaim.SOURCE_BOUND,
        source_links=(_link(),),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
    )
    filters = _filters(applied=True)
    first = build_patent_indexes(
        docs, filters=filters, edges=[edge], corpus_cid=CID_CORPUS
    )
    second = build_patent_indexes(
        docs, filters=filters, edges=[edge], corpus_cid=CID_CORPUS
    )
    assert first.bundle_digest == second.bundle_digest
    assert first.bm25.content_digest == second.bm25.content_digest
    assert first.vector.content_digest == second.vector.content_digest
    assert first.graph.content_digest == second.graph.content_digest
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    # Every family row/node joins to source CID.
    for doc in first.bm25.documents:
        assert doc.source_links[0].source_cid
    for doc in first.vector.documents:
        assert doc.row.source_links[0].source_cid
    for node in first.graph.nodes:
        assert node.source_links[0].source_cid
    assert first.vector.embedding.provider
    assert first.vector.embedding.model_id
    assert first.vector.embedding.config_cid
    assert first.atomic_chunks


def test_content_digest_hex_stable() -> None:
    payload = {"a": 1, "b": ["x", "y"]}
    assert content_digest_hex(payload) == content_digest_hex(payload)
    assert len(content_digest_hex(payload)) == 64


def test_golden_case_fixture_loads() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "patent"
        / "retrieval"
        / "golden_case.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["case_id"]
    assert data["documents"]
    assert data["queries"]
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=data["tenant_id"],
        as_of_utc=data["as_of_utc"],
        allowed_disclosures=tuple(data["allowed_disclosures"]),
        applied=True,
    )
    bundle = build_patent_indexes(
        docs,
        filters=filters,
        edges=data.get("edges") or [],
        corpus_cid=data["corpus_cid"],
    )
    # Private + future rows filtered out; two public effective docs remain.
    assert bundle.bm25.stats["document_count"] == 2
    assert all(
        any(link.source_cid for link in doc.source_links)
        for doc in bundle.bm25.documents
    )
