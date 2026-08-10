"""Unit tests for exact FLOAT[N] DuckDB vector search (DQK-021).

Acceptance coverage:

* Exact results agree with NumPy fixtures
* Mixed dimensions cannot enter one physical table
* Metadata filters and deterministic tie-breaking are covered

Also covers generation binding, content digests, FLOAT[N] physical types,
and per-dimension table isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    DUCKDB_EXACT_SCHEMA,
    ExactHit,
    ExactVectorStore,
    ExactVectorStoreError,
    decode_vector,
    distance,
    encode_vector,
    physical_table_name,
    vector_digest,
)


@pytest.fixture
def store(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Acceptance: exact results agree with NumPy fixtures
# ---------------------------------------------------------------------------


def test_exact_results_agree_with_numpy(store: ExactVectorStore) -> None:
    dim = 3
    store.create_collection("col", dimension=dim)
    vectors = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.0, 1.0, 0.0],
        "c": [0.9, 0.1, 0.0],
    }
    digests = {}
    for vid, vals in vectors.items():
        digests[vid] = store.upsert_vector("col", vid, vals, metadata={"tag": vid})

    query = [1.0, 0.0, 0.0]
    hits = store.search("col", query, k=3, metric="l2")

    # NumPy reference ranking (float64 on the same logical vectors).
    q = np.asarray(query, dtype=np.float64)
    expected = sorted(
        (
            (float(np.linalg.norm(q - np.asarray(v, dtype=np.float64))), vid)
            for vid, v in vectors.items()
        ),
        key=lambda item: (item[0], item[1]),
    )
    assert [h.vector_id for h in hits] == [vid for _, vid in expected]
    for hit, (dist, vid) in zip(hits, expected):
        assert hit.distance == pytest.approx(dist, rel=1e-5, abs=1e-6)
        assert hit.generation_id == 1
        assert hit.collection_id == "col"
        assert hit.content_digest == digests[vid]
        assert hit.content_digest == vector_digest(vectors[vid])
        assert hit.metadata["tag"] == vid
        assert isinstance(hit, ExactHit)


def test_exact_cosine_agrees_with_numpy(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    vectors = {
        "same": [1.0, 0.0],
        "ortho": [0.0, 1.0],
        "half": [1.0, 1.0],
    }
    for vid, vals in vectors.items():
        store.upsert_vector("col", vid, vals)

    query = [1.0, 0.0]
    hits = store.search("col", query, k=3, metric="cosine")

    def np_cosine_distance(a, b):
        a = np.asarray(a, dtype=np.float64)
        b = np.asarray(b, dtype=np.float64)
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0.0 or nb == 0.0:
            return 2.0
        cos = float(np.dot(a, b) / (na * nb))
        cos = max(-1.0, min(1.0, cos))
        return 1.0 - cos

    expected = sorted(
        ((np_cosine_distance(query, v), vid) for vid, v in vectors.items()),
        key=lambda item: (item[0], item[1]),
    )
    assert [h.vector_id for h in hits] == [vid for _, vid in expected]
    for hit, (dist, _) in zip(hits, expected):
        assert hit.distance == pytest.approx(dist, rel=1e-5, abs=1e-5)


def test_numpy_fixture_larger_dimension(store: ExactVectorStore) -> None:
    """Larger FLOAT[N] table still matches a NumPy ranking fixture."""
    rng = np.random.default_rng(42)
    dim = 16
    store.create_collection("big", dimension=dim)
    vectors = {
        f"v{i:02d}": rng.standard_normal(dim).astype(np.float64).tolist()
        for i in range(12)
    }
    for vid, vals in vectors.items():
        store.upsert_vector("big", vid, vals)

    query = rng.standard_normal(dim).astype(np.float64).tolist()
    hits = store.search("big", query, k=5, metric="l2")

    q = np.asarray(query, dtype=np.float64)
    expected = sorted(
        (
            (float(np.linalg.norm(q - np.asarray(v, dtype=np.float64))), vid)
            for vid, v in vectors.items()
        ),
        key=lambda item: (item[0], item[1]),
    )[:5]
    assert [h.vector_id for h in hits] == [vid for _, vid in expected]
    for hit, (dist, _) in zip(hits, expected):
        # FLOAT[N] SQL distance is float32; allow a tight but practical band.
        assert hit.distance == pytest.approx(dist, rel=1e-4, abs=1e-4)


# ---------------------------------------------------------------------------
# Acceptance: mixed dimensions cannot enter one physical table
# ---------------------------------------------------------------------------


def test_mixed_dimensions_rejected(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    store.upsert_vector("col", "v1", [0.0, 1.0])
    with pytest.raises(ExactVectorStoreError) as exc:
        store.upsert_vector("col", "v2", [0.0, 1.0, 2.0])
    assert exc.value.code == "DIM"
    with pytest.raises(ExactVectorStoreError) as exc2:
        store.search("col", [0.0, 1.0, 2.0])
    assert exc2.value.code == "DIM"


def test_dimension_specific_physical_tables(store: ExactVectorStore) -> None:
    store.create_collection("c2", dimension=2)
    store.create_collection("c3", dimension=3)
    store.upsert_vector("c2", "a", [1.0, 0.0])
    store.upsert_vector("c3", "b", [1.0, 0.0, 0.0])

    tables = store.physical_tables()
    assert tables[2] == "exact_vectors_d2"
    assert tables[3] == "exact_vectors_d3"
    assert physical_table_name(2) == "exact_vectors_d2"

    # Engine-level FLOAT[N] type rejects wrong length on the physical table.
    conn = store._conn  # noqa: SLF001 — assert physical contract
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO exact_vectors_d2 VALUES (?, ?, ?, ?, ?::FLOAT[2], ?)",
            ["bad", "c2", 1, "sha256:x", [1.0, 2.0, 3.0], "{}"],
        )

    # DESCRIBE proves FLOAT[N] authority.
    d2 = {row[0]: row[1] for row in conn.execute("DESCRIBE exact_vectors_d2").fetchall()}
    d3 = {row[0]: row[1] for row in conn.execute("DESCRIBE exact_vectors_d3").fetchall()}
    assert d2["embedding"] == "FLOAT[2]"
    assert d3["embedding"] == "FLOAT[3]"


def test_collection_dimension_mismatch_on_recreate(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=4)
    with pytest.raises(ExactVectorStoreError) as exc:
        store.create_collection("col", dimension=8)
    assert exc.value.code == "DIM"


# ---------------------------------------------------------------------------
# Acceptance: metadata filters and deterministic tie-breaking
# ---------------------------------------------------------------------------


def test_metadata_filter_and_deterministic_ties(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    # Equal distance to query [0,0]: both unit vectors on axes have dist 1.
    store.upsert_vector("col", "z-last", [1.0, 0.0], metadata={"group": "g1"})
    store.upsert_vector("col", "a-first", [0.0, 1.0], metadata={"group": "g1"})
    store.upsert_vector("col", "other", [0.5, 0.5], metadata={"group": "g2"})

    hits = store.search("col", [0.0, 0.0], k=10, metadata_filter={"group": "g1"})
    assert [h.vector_id for h in hits] == ["a-first", "z-last"]
    assert all(h.metadata["group"] == "g1" for h in hits)

    # Without filter, all three appear. "other" is closer; the two unit-axis
    # vectors share distance 1.0 and break ties by vector_id ascending.
    all_hits = store.search("col", [0.0, 0.0], k=10)
    assert [h.vector_id for h in all_hits] == ["other", "a-first", "z-last"]
    assert all_hits[1].distance == pytest.approx(all_hits[2].distance, abs=1e-6)

    # Cosine path sanity (reference helper + store).
    d = distance([1.0, 0.0], [1.0, 0.0], metric="cosine")
    assert d == pytest.approx(0.0, abs=1e-6)
    cos_hits = store.search("col", [1.0, 0.0], k=1, metric="cosine")
    assert cos_hits[0].vector_id == "z-last"
    assert cos_hits[0].distance == pytest.approx(0.0, abs=1e-5)


def test_metadata_numeric_and_bool_filters(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    store.upsert_vector(
        "col", "n1", [1.0, 0.0], metadata={"score": 3, "active": True}
    )
    store.upsert_vector(
        "col", "n2", [0.0, 1.0], metadata={"score": 7, "active": False}
    )
    hits = store.search(
        "col", [1.0, 0.0], k=5, metadata_filter={"score": 3, "active": True}
    )
    assert [h.vector_id for h in hits] == ["n1"]


# ---------------------------------------------------------------------------
# Generation binding and content digests
# ---------------------------------------------------------------------------


def test_search_bound_to_collection_generation(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2, generation_id=1)
    store.upsert_vector(
        "col", "old", [1.0, 0.0], generation_id=1, metadata={"gen": 1}
    )
    store.upsert_vector(
        "col", "new", [0.0, 1.0], generation_id=2, metadata={"gen": 2}
    )

    # Active generation is still 1 → only "old" is visible.
    hits_g1 = store.search("col", [1.0, 0.0], k=5)
    assert [h.vector_id for h in hits_g1] == ["old"]
    assert hits_g1[0].generation_id == 1
    assert store.count("col") == 1

    store.set_generation("col", 2)
    hits_g2 = store.search("col", [0.0, 1.0], k=5)
    assert [h.vector_id for h in hits_g2] == ["new"]
    assert hits_g2[0].generation_id == 2
    assert store.count("col") == 1

    # Explicit generation override still works for historical reads.
    hist = store.search("col", [1.0, 0.0], k=5, generation_id=1)
    assert [h.vector_id for h in hist] == ["old"]


def test_content_digest_is_float32_sha256(store: ExactVectorStore) -> None:
    values = [1.5, -2.25, 0.0, 3.125]
    digest = vector_digest(values)
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    raw = encode_vector(values)
    assert len(raw) == 16
    assert decode_vector(raw, 4) == pytest.approx(values)

    store.create_collection("col", dimension=4)
    got = store.upsert_vector("col", "v", values)
    assert got == digest
    hits = store.search("col", values, k=1)
    assert hits[0].content_digest == digest


def test_schema_identity_and_get_collection(store: ExactVectorStore) -> None:
    assert store.schema_name == DUCKDB_EXACT_SCHEMA
    store.create_collection("docs", dimension=8, generation_id=3)
    info = store.get_collection("docs")
    assert info == {
        "collection_id": "docs",
        "dimension": 8,
        "generation_id": 3,
        "physical_table": "exact_vectors_d8",
    }


def test_delete_vector(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    store.upsert_vector("col", "keep", [1.0, 0.0])
    store.upsert_vector("col", "drop", [0.0, 1.0])
    assert store.delete_vector("col", "drop") is True
    assert store.delete_vector("col", "drop") is False
    hits = store.search("col", [0.0, 1.0], k=5)
    assert [h.vector_id for h in hits] == ["keep"]


def test_non_finite_and_invalid_ids_rejected(store: ExactVectorStore) -> None:
    store.create_collection("col", dimension=2)
    with pytest.raises(ExactVectorStoreError) as exc:
        store.upsert_vector("col", "v", [float("nan"), 0.0])
    assert exc.value.code == "INVALID_VECTOR"
    with pytest.raises(ExactVectorStoreError) as exc2:
        store.create_collection("bad id!", dimension=2)
    assert exc2.value.code == "ID"
    with pytest.raises(ExactVectorStoreError) as exc3:
        store.search("col", [1.0, 0.0], k=0)
    assert exc3.value.code == "K"


def test_memory_store_and_context_manager(tmp_path: Path) -> None:
    with ExactVectorStore(":memory:") as mem:
        mem.create_collection("m", dimension=2)
        mem.upsert_vector("m", "x", [1.0, 0.0])
        assert mem.count("m") == 1
        assert len(mem.search("m", [1.0, 0.0], k=1)) == 1

    path = tmp_path / "persist.duckdb"
    with ExactVectorStore(path) as s:
        s.create_collection("p", dimension=2)
        s.upsert_vector("p", "y", [0.0, 1.0])
    with ExactVectorStore(path) as s2:
        hits = s2.search("p", [0.0, 1.0], k=1)
        assert hits[0].vector_id == "y"
