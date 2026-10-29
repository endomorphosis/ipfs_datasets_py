"""Real DuckDB publication/lookup tests; no provider, model or browser calls."""
import json

import pytest

pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.management_engine import VectorShadowCatalog


DOCS = [
    {"text": "cedar-ledger actual indexed text", "metadata": {"title": "Indexed note", "fixture_scope": "svf-notes-unit"}},
    {"text": "unrelated astronomy", "metadata": {"title": "Other note"}},
]


def publish(catalog, name="svf-notes-unit", documents=DOCS):
    result = catalog.shadow_create(logical_name=name, backend="faiss", dimension=2,
        vectors=[[1.0, 0.0], [0.0, 1.0]], vector_ids=["doc_0", "doc_1"],
        documents=documents, metadata_json={"document_payload_policy": "matched-only"} if documents is not None else {})
    assert result.ok, result.error
    return result


def test_payload_is_published_in_authoritative_document_rows_and_survives_restart(tmp_path):
    path = tmp_path / "catalog.duckdb"
    catalog = VectorShadowCatalog(path, enabled=True, allow_legacy_io=False)
    publish(catalog)
    hit = catalog.matched_document("svf-notes-unit", "faiss", "doc_0")
    assert hit["document"] == DOCS[0]
    document = catalog.store.get_document(hit["provenance"]["document_id"])
    assert document.metadata["indexed_document"] == DOCS[0]
    assert document.generation_id == hit["provenance"]["generation_id"]
    assert "cedar-ledger actual indexed text" not in json.dumps(catalog.publication_document())
    catalog.close()
    restored = VectorShadowCatalog(path, enabled=True, allow_legacy_io=False)
    try:
        assert restored.matched_document("svf-notes-unit", "faiss", "doc_0")["document"] == DOCS[0]
    finally:
        restored.close()


def test_default_collection_policy_does_not_return_documents_and_no_cross_collection_lookup(tmp_path):
    catalog = VectorShadowCatalog(tmp_path / "catalog.duckdb", enabled=True)
    try:
        publish(catalog, documents=None)
        assert catalog.matched_document("svf-notes-unit", "faiss", "doc_0") is None
        publish(catalog, name="svf-notes-controlled")
        assert catalog.matched_document("another-owner", "faiss", "doc_0") is None
        assert catalog.matched_document("svf-notes-controlled", "faiss", "another-id") is None
        assert catalog.matched_document("svf-notes-unit", "faiss", "doc_0") is None
    finally:
        catalog.close()


def test_tombstones_hide_previously_published_payloads(tmp_path):
    catalog = VectorShadowCatalog(tmp_path / "catalog.duckdb", enabled=True)
    try:
        publish(catalog)
        hit = catalog.matched_document("svf-notes-unit", "faiss", "doc_0")
        p = hit["provenance"]
        catalog.store.delete_chunk(collection_id=p["collection_id"], chunk_id=p["chunk_id"], reason="unit deletion")
        assert catalog.matched_document("svf-notes-unit", "faiss", "doc_0") is None
        assert catalog.matched_document("svf-notes-unit", "faiss", "doc_1")["document"] == DOCS[1]
    finally:
        catalog.close()


def test_payload_digest_mismatch_cannot_return_forged_document(tmp_path):
    catalog = VectorShadowCatalog(tmp_path / "catalog.duckdb", enabled=True)
    try:
        publish(catalog)
        hit = catalog.matched_document("svf-notes-unit", "faiss", "doc_0")
        # Deliberate corruption injection, never used to create passing proof.
        with catalog.store._lock:
            catalog.store._conn.execute("UPDATE vector_documents SET metadata_json = ? WHERE document_id = ?",
                [json.dumps({"indexed_document": {"text": "forged"}, "payload_digest": "wrong"}), hit["provenance"]["document_id"]])
        assert catalog.matched_document("svf-notes-unit", "faiss", "doc_0") is None
    finally:
        catalog.close()


def test_payload_publication_requires_explicit_policy_and_one_bounded_document_per_vector(tmp_path):
    catalog = VectorShadowCatalog(tmp_path / "catalog.duckdb", enabled=True)
    try:
        with pytest.raises(ValueError, match="matched-only"):
            catalog.shadow_create(logical_name="private", backend="faiss", dimension=2,
                vectors=[[1.0, 0.0]], vector_ids=["doc_0"], documents=DOCS[:1])
        with pytest.raises(ValueError, match="one document"):
            catalog.shadow_create(logical_name="private", backend="faiss", dimension=2,
                vectors=[[1.0, 0.0]], vector_ids=["doc_0"], documents=DOCS,
                metadata_json={"document_payload_policy": "matched-only"})
    finally:
        catalog.close()
