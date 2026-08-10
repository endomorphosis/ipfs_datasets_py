"""Unit tests for exact FLOAT[N] DuckDB vector search (DQK-021).

Acceptance coverage:

* Exact results agree with NumPy fixtures (pure-Python float64 reference that
  mirrors ``numpy.linalg.norm`` L2 ranking; optional dual-check if NumPy is
  installed)
* Mixed dimensions cannot enter one physical table
* Metadata filters and deterministic tie-breaking are covered
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ExactHit,
    ExactVectorStore,
    ExactVectorStoreError,
    distance,
    vector_digest,
)


def _l2(a: list[float], b: list[float]) -> float:
    """NumPy-equivalent float64 Euclidean distance (``linalg.norm(a - b)``)."""

    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def _numpy_reference_ranking(
    query: list[float],
    vectors: dict[str, list[float]],
) -> list[tuple[float, str]]:
    """Reference ranking matching NumPy fixtures: sort by (L2, vector_id).

    Pure-Python float64 L2 mirrors ``numpy.linalg.norm(q - v)``. When NumPy is
    installed the ranking is dual-checked; sealed validation does not require it.
    """

    ranked = sorted(
        ((_l2(query, vals), vid) for vid, vals in vectors.items()),
        key=lambda item: (item[0], item[1]),
    )
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return ranked

    q = np.asarray(query, dtype=np.float64)
    np_ranked = sorted(
        (
            (
                float(np.linalg.norm(q - np.asarray(v, dtype=np.float64))),
                vid,
            )
            for vid, v in vectors.items()
        ),
        key=lambda item: (item[0], item[1]),
    )
    assert [vid for _, vid in ranked] == [vid for _, vid in np_ranked]
    for (d1, _), (d2, _) in zip(ranked, np_ranked):
        assert d1 == pytest.approx(d2, rel=1e-12, abs=1e-12)
    return ranked


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
    expected = _numpy_reference_ranking(query, vectors)
    assert [h.vector_id for h in hits] == [vid for _, vid in expected]
    for hit, (dist, _) in zip(hits, expected):
        assert isinstance(hit, ExactHit)
        assert hit.distance == pytest.approx(dist, rel=1e-5, abs=1e-6)
        assert hit.generation_id == 1
        assert hit.content_digest == vector_digest(vectors[hit.vector_id])
        assert hit.collection_id == "col"
        assert hit.metadata["tag"] == hit.vector_id


def test_mixed_dimensions_rejected(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    store.upsert_vector("col", "v1", [0.0, 1.0])
    with pytest.raises(ExactVectorStoreError) as exc:
        store.upsert_vector("col", "v2", [0.0, 1.0, 2.0])
    assert exc.value.code == "DIM"
    assert "mixed dimensions" in str(exc.value).lower() or "physical table" in str(
        exc.value
    ).lower() or "expected" in str(exc.value).lower()
    with pytest.raises(ExactVectorStoreError) as exc2:
        store.search("col", [0.0, 1.0, 2.0])
    assert exc2.value.code == "DIM"
    # Distinct dimensions land in distinct physical tables.
    store.create_collection("col3", dimension=3)
    assert store.physical_table_name(2) != store.physical_table_name(3)
    store.upsert_vector("col3", "v3", [0.0, 1.0, 2.0])
    assert store.count("col") == 1
    assert store.count("col3") == 1


def test_metadata_filter_and_deterministic_ties(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    # Equal distance to query [0,0]: both unit vectors on axes have dist 1.
    store.upsert_vector("col", "z-last", [1.0, 0.0], metadata={"group": "g1"})
    store.upsert_vector("col", "a-first", [0.0, 1.0], metadata={"group": "g1"})
    store.upsert_vector("col", "other", [0.5, 0.5], metadata={"group": "g2"})
    hits = store.search("col", [0.0, 0.0], k=10, metadata_filter={"group": "g1"})
    assert [h.vector_id for h in hits] == ["a-first", "z-last"]
    assert all(h.metadata["group"] == "g1" for h in hits)
    assert all(h.generation_id == 1 for h in hits)
    assert all(h.content_digest.startswith("sha256:") for h in hits)
    # Cosine path sanity.
    d = distance([1.0, 0.0], [1.0, 0.0], metric="cosine")
    assert d == pytest.approx(0.0, abs=1e-6)
    cosine_hits = store.search("col", [1.0, 0.0], k=1, metric="cosine")
    assert cosine_hits[0].vector_id == "z-last"
    assert cosine_hits[0].distance == pytest.approx(0.0, abs=1e-5)
