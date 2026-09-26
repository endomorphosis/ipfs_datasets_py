"""U.S. Code sparse GraphRAG ingest. No compiler and no model on inventory."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
    census_uscode_ledger,
    hub_sparse_graphrag_searcher,
    inventory_uscode_documents,
    local_sparse_graphrag_searcher,
    normalize_uscode_hit,
    pinned_sparse_graphrag_searcher,
    retrieve_uscode_hits,
    sparse_graphrag_searcher,
)


def test_inventory_splits_retrieved_sections_and_does_not_compile() -> None:
    ledger = inventory_uscode_documents(
        [
            {
                "entry_cid": "bafkreiabc",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "release_point": "us/pl/119/102",
                "text": "Each agency shall make available records. The agency may withhold secrets.",
            }
        ],
        query="agency records",
        release_id="hf:justicedao/ipfs_uscode@abc",
    )
    assert ledger["compiled"] is False
    assert ledger["admitted"] is False
    assert ledger["formalized"] is False
    assert ledger["retrieval"]["method"] == "sparse_bm25"
    assert ledger["retrieval"]["authority"] is False
    assert ledger["span_identity_schema"] == "uscode-sparse-autoformal-span-v1"
    assert len(ledger["spans"]) == 2
    assert all(span["status"] == "uncompiled" for span in ledger["spans"])
    assert ledger["spans"][0]["legal_id"] == "usc:us:5:552"
    assert ledger["spans"][0]["source_span_id"].startswith("uscode-span-")
    assert ledger["spans"][0]["source_span_id"] != ledger["spans"][1]["source_span_id"]


def test_local_sparse_graphrag_searcher_uses_pinned_local_release(tmp_path, monkeypatch) -> None:
    seen = {}

    class FakeEngine:
        def __init__(self, resolver):
            seen["resolver"] = resolver

    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.query.BoundedRemoteQueryEngine",
        FakeEngine,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.remote_search.bm25_search",
        lambda engine, query, **kwargs: SimpleNamespace(results=({"entry_cid": "a", "title": "5", "section": "552", "text": "Each agency shall make records available."},)),
    )
    (tmp_path / "release").mkdir()
    searcher = local_sparse_graphrag_searcher(
        tmp_path / "release",
        repo_id="justicedao/ipfs_uscode",
        revision="a" * 40,
        cache_dir=tmp_path / "cache",
    )
    hits = retrieve_uscode_hits(searcher, "FOIA")
    assert hits[0]["section"] == "552"
    skipped = retrieve_uscode_hits(
        searcher,
        "FOIA",
        exclude_document_ids=[hits[0]["document_id"]],
    )
    assert skipped == []
    assert seen["resolver"].repo_id == "justicedao/ipfs_uscode"
    assert seen["resolver"].revision == "a" * 40
    assert seen["resolver"].local_root == tmp_path / "release" or str(seen["resolver"].local_root).endswith("release")


def test_hub_sparse_graphrag_searcher_uses_hub_transport(monkeypatch) -> None:
    seen = {}

    class FakeEngine:
        def __init__(self, resolver):
            seen["resolver"] = resolver

    class FakeHub:
        pass

    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.query.BoundedRemoteQueryEngine",
        FakeEngine,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.resolver.HuggingFaceHubTransport",
        FakeHub,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.remote_search.bm25_search",
        lambda engine, query, **kwargs: SimpleNamespace(results=({"entry_cid": "a", "title": "5", "section": "552", "text": "Each agency shall make records available."},)),
    )
    searcher = hub_sparse_graphrag_searcher(repo_id="justicedao/ipfs_uscode", revision="b" * 40)
    hits = retrieve_uscode_hits(searcher, "FOIA")
    assert hits[0]["section"] == "552"
    assert seen["resolver"].repo_id == "justicedao/ipfs_uscode"
    assert seen["resolver"].revision == "b" * 40
    assert type(seen["resolver"].transport) is FakeHub


def test_pinned_searcher_prefers_local_root(tmp_path, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.autoformal.uscode_ingest.local_sparse_graphrag_searcher",
        lambda root, **kwargs: seen.setdefault("local", (Path(root), kwargs)) or (lambda query, **kw: []),
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.autoformal.uscode_ingest.hub_sparse_graphrag_searcher",
        lambda **kwargs: seen.setdefault("hub", kwargs) or (lambda query, **kw: []),
    )
    pinned_sparse_graphrag_searcher(
        repo_id="justicedao/ipfs_uscode",
        revision="c" * 40,
        release_root=tmp_path / "release",
    )
    assert "local" in seen and "hub" not in seen
    pinned_sparse_graphrag_searcher(repo_id="justicedao/ipfs_uscode", revision="c" * 40)
    assert "hub" in seen


def test_sparse_graphrag_searcher_requests_hydrated_content(monkeypatch) -> None:
    seen = {}

    def fake_bm25(engine, query, **kwargs):
        seen["engine"] = engine
        seen["query"] = query
        seen["kwargs"] = kwargs
        return SimpleNamespace(results=({"entry_cid": "a", "title": "5", "section": "552", "text": "Each agency shall make records available."},))

    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.remote_search.bm25_search",
        fake_bm25,
    )
    searcher = sparse_graphrag_searcher("engine")
    hits = retrieve_uscode_hits(searcher, "FOIA", top_k=5)
    assert seen["engine"] == "engine"
    assert seen["query"] == "FOIA"
    assert seen["kwargs"]["hydrate"] is True
    assert seen["kwargs"]["include_content"] is True
    assert seen["kwargs"]["top_k"] == 5
    assert hits[0]["section"] == "552"


def test_retrieve_uscode_hits_uses_sparse_searcher_and_drops_empty_text() -> None:
    result = SimpleNamespace(
        results=(
            {"entry_cid": "a", "title": "5", "section": "552", "text": "Each agency shall make records available."},
            {"entry_cid": "b", "title": "5", "section": "552a", "text": ""},
        )
    )
    hits = retrieve_uscode_hits(lambda query, **kwargs: result, "FOIA")
    assert len(hits) == 1
    assert hits[0]["entry_cid"] == "a"
    assert hits[0]["retrieval_method"] == "sparse_bm25"


def test_verified_row_objects_normalize() -> None:
    hit = SimpleNamespace(
        entry_cid="cid-1",
        legal_id="usc:us:18:1001",
        title="18",
        section="1001",
        canonical_citation="18 U.S.C. 1001",
        release_point="us/pl/119/102",
        text="Whoever makes a false statement shall be fined.",
        record_sha256="ab" * 32,
        text_sha256="cd" * 32,
    )
    document = normalize_uscode_hit(hit)
    assert document["legal_id"] == "usc:us:18:1001"
    assert document["canonical_citation"] == "18 U.S.C. 1001"


def test_census_names_gaps_and_does_not_mark_formalized() -> None:
    ledger = inventory_uscode_documents(
        [{"title": "5", "section": "552", "text": "Each agency shall make records available."}]
    )

    def compile_one(text: str) -> dict[str, str]:
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    report = census_uscode_ledger(ledger, compile_one)
    assert report["stopped"] is False
    span = report["ledger"]["spans"][0]
    assert span["status"] == "gap"
    assert span["reason"] == "no_parser_elements"
    assert report["ledger"]["compiled"] is False
    assert report["ledger"]["formalized"] is False
    assert report["ledger"]["admitted"] is False
