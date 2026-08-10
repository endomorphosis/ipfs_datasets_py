"""Unit tests for exact FLOAT[N] DuckDB vector search (DQK-021)."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ExactVectorStore,
    ExactVectorStoreError,
    distance,
    vector_digest,
)


@pytest.fixture
def store(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    yield s
    s.close()


def test_exact_results_agree_with_numpy(store: ExactVectorStore) -> None:
    dim = 3
    store.create_collection("col", dimension=dim)
    vectors = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.0, 1.0, 0.0],
        "c": [0.9, 0.1, 0.0],
    }
    for vid, vals in vectors.items():
        store.upsert_vector("col", vid, vals, metadata={"tag": vid})
    query = [1.0, 0.0, 0.0]
    hits = store.search("col", query, k=3, metric="l2")
    # NumPy reference ranking
    q = np.asarray(query, dtype=np.float64)
    expected = sorted(
        (
            (float(np.linalg.norm(q - np.asarray(v, dtype=np.float64))), vid)
            for vid, v in vectors.items()
        ),
        key=lambda item: (item[0], item[1]),
    )
    assert [h.vector_id for h in hits] == [vid for _, vid in expected]
    for hit, (dist, _) in zip(hits, expected):
        assert hit.distance == pytest.approx(dist, rel=1e-5, abs=1e-6)
        assert hit.generation_id == 1
        assert hit.content_digest == vector_digest(vectors[hit.vector_id])


def test_mixed_dimensions_rejected(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    store.upsert_vector("col", "v1", [0.0, 1.0])
    with pytest.raises(ExactVectorStoreError) as exc:
        store.upsert_vector("col", "v2", [0.0, 1.0, 2.0])
    assert exc.value.code == "DIM"
    with pytest.raises(ExactVectorStoreError) as exc2:
        store.search("col", [0.0, 1.0, 2.0])
    assert exc2.value.code == "DIM"


def test_metadata_filter_and_deterministic_ties(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    # Equal distance to query [0,0]: both unit vectors on axes have dist 1.
    store.upsert_vector("col", "z-last", [1.0, 0.0], metadata={"group": "g1"})
    store.upsert_vector("col", "a-first", [0.0, 1.0], metadata={"group": "g1"})
    store.upsert_vector("col", "other", [0.5, 0.5], metadata={"group": "g2"})
    hits = store.search("col", [0.0, 0.0], k=10, metadata_filter={"group": "g1"})
    assert [h.vector_id for h in hits] == ["a-first", "z-last"]
    assert all(h.metadata["group"] == "g1" for h in hits)
    # Cosine path sanity.
    d = distance([1.0, 0.0], [1.0, 0.0], metric="cosine")
    assert d == pytest.approx(0.0, abs=1e-6)
