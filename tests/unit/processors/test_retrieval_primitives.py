from ipfs_datasets_py.processors import (
    bm25_search_documents,
    build_bm25_index,
    search_bm25_index,
)


def test_build_bm25_index_exports_reusable_payload():
    index = build_bm25_index(
        [
            {"id": "doc-1", "title": "Extension of time", "text": "Motion for extension of time to answer"},
            {"id": "doc-2", "title": "Notice", "text": "Simple notice of appearance"},
        ]
    )

    assert index["backend"] == "local_bm25"
    assert index["document_count"] == 2
    assert len(index["documents"]) == 2
    assert index["stats"]["average_document_tokens"] > 0


def test_search_bm25_index_returns_ranked_results():
    index = build_bm25_index(
        [
            {"id": "doc-1", "title": "Extension of time", "text": "Motion for extension of time to answer"},
            {"id": "doc-2", "title": "Notice", "text": "Notice of filing"},
        ]
    )

    results = search_bm25_index("extension answer", index, top_k=2)

    assert len(results) == 1
    assert results[0]["id"] == "doc-1"
    assert results[0]["backend"] == "local_bm25"


def test_bm25_search_documents_prefers_title_matches():
    results = bm25_search_documents(
        "screening approval",
        [
            {"id": "doc-1", "title": "Approved screening", "text": "Parkside Manor approved screening email"},
            {"id": "doc-2", "title": "Miscellaneous", "text": "Unrelated filing text"},
        ],
        top_k=2,
    )

    assert len(results) == 1
    assert results[0]["id"] == "doc-1"
    assert "screening" in results[0]["matched_terms"]
