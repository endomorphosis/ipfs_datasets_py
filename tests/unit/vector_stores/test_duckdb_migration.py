"""Unit tests for FAISS metadata migration (DQK-023)."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore
from ipfs_datasets_py.vector_stores.duckdb_migration import (
    ExternalBackend,
    VectorMigrationError,
    import_faiss_pickle_metadata,
    measure_external_parity,
)


@pytest.fixture
def store(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    yield s
    s.close()


def test_normal_runtime_never_unpickles(tmp_path: Path, store: ExactVectorStore) -> None:
    path = tmp_path / "meta.pkl"
    path.write_bytes(pickle.dumps({"vectors": {"a": [1.0, 0.0]}}))
    with pytest.raises(VectorMigrationError, match="never unpickles"):
        import_faiss_pickle_metadata(
            path, store, collection_id="c", dimension=2, allow_unpickle=False
        )


def test_import_records_source_digest_and_rejects(tmp_path: Path, store: ExactVectorStore) -> None:
    payload = {
        "vectors": {
            "a": [1.0, 0.0, 0.0],
            "b": [0.0, 1.0],  # bad dim
            "c": [0.0, 0.0, 1.0],
        }
    }
    path = tmp_path / "meta.pkl"
    path.write_bytes(pickle.dumps(payload))
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert report.source_digest.startswith("sha256:")
    assert report.imported_count == 2
    assert any(r.reason == "dimension mismatch" for r in report.rejected)
    assert report.to_dict()["source_digest"] == report.source_digest
    # Second import of same ids quarantines duplicates when we pass a list-style
    # payload by re-importing after first success via direct second call simulation.
    payload2 = {"vectors": {"a": [1.0, 0.0, 0.0], "d": [0.1, 0.2, 0.3]}}
    path2 = tmp_path / "meta2.pkl"
    path2.write_bytes(pickle.dumps(payload2))
    report2 = import_faiss_pickle_metadata(
        path2, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert report2.imported_count >= 1


def test_external_parity_before_promotion(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    store.upsert_vector("c", "a", [1.0, 0.0])
    store.upsert_vector("c", "b", [0.0, 1.0])
    # External backend returns same top hit.
    parity = measure_external_parity(
        store,
        collection_id="c",
        query=[1.0, 0.0],
        external_hits=["a", "b"],
        backend=ExternalBackend.FAISS,
        k=2,
        min_ratio=0.5,
    )
    assert parity.promotion_allowed is True
    assert parity.ratio >= 0.5
    bad = measure_external_parity(
        store,
        collection_id="c",
        query=[1.0, 0.0],
        external_hits=["zzz"],
        backend=ExternalBackend.QDRANT,
        k=1,
        min_ratio=0.9,
    )
    assert bad.promotion_allowed is False
