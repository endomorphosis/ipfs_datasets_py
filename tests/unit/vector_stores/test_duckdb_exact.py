"""Unit tests for DuckDB exact FLOAT[N] search (DQK-021).

Acceptance coverage:

* Exact results agree with NumPy fixtures
* Mixed dimensions cannot enter one physical table
* Metadata filters and deterministic tie-breaking are covered
* Results bind collection generation and content digests
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
np = pytest.importorskip("numpy")

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ALLOWED_METRICS,
    DUCKDB_EXACT_SCHEMA,
    EXACT_SCHEMA_VERSION,
    DuckDBExactVectorStore,
    ExactSearchHit,
    ExactVectorRow,
    numpy_cosine_distance,
    numpy_inner_product,
    numpy_l2_distance,
    physical_table_name,
    sql_array_type,
)
from ipfs_datasets_py.vector_stores.duckdb_store import (
    DuckDBVectorStore,
    VectorStoreContractError,
    vector_content_digest,
)

DIM = 4
DTYPE = "float32"
GEN_DIGEST = "sha256:" + "ab" * 32
GEN_DIGEST_2 = "sha256:" + "cd" * 32


def _vec(*values: float) -> list[float]:
    assert len(values) == DIM
    return list(values)


@pytest.fixture
def exact(tmp_path: Path) -> DuckDBExactVectorStore:
    path = tmp_path / "exact.duckdb"
    store = DuckDBExactVectorStore(path)
    yield store
    store.close()


@pytest.fixture
def dim_table(exact: DuckDBExactVectorStore) -> str:
    return exact.ensure_dimension_table(dimension=DIM, dtype=DTYPE)


def _seed(
    exact: DuckDBExactVectorStore,
    rows: list[dict],
    *,
    collection_id: str = "col_docs",
    generation_id: int = 1,
    generation_content_digest: str = GEN_DIGEST,
    dimension: int = DIM,
    dtype: str = DTYPE,
) -> list[ExactVectorRow]:
    exact.ensure_dimension_table(dimension=dimension, dtype=dtype)
    return exact.upsert_many(
        rows,
        dimension=dimension,
        dtype=dtype,
        collection_id=collection_id,
        generation_id=generation_id,
        generation_content_digest=generation_content_digest,
    )


# ---------------------------------------------------------------------------
# Module / schema
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_import_does_not_require_pickle_authority(self):
        source = Path(
            inspect.getsourcefile(
                importlib.import_module("ipfs_datasets_py.vector_stores.duckdb_exact")
            )
        ).read_text(encoding="utf-8")
        assert "pickle.load" not in source
        assert "pickle.loads" not in source
        assert "pickle.dump" not in source
        assert "pickle.dumps" not in source

    def test_schema_constants(self):
        assert EXACT_SCHEMA_VERSION == 1
        assert DUCKDB_EXACT_SCHEMA.startswith("ipfs_datasets_py/")
        assert "l2" in ALLOWED_METRICS
        assert "cosine" in ALLOWED_METRICS

    def test_physical_table_name_stable(self):
        assert physical_table_name(4, "float32") == "vector_exact_f32_d4"
        assert physical_table_name(768, "float64") == "vector_exact_f64_d768"
        assert sql_array_type(4, "float32") == "FLOAT[4]"
        assert sql_array_type(8, "float64") == "DOUBLE[8]"

    def test_core_tables_created(self, exact: DuckDBExactVectorStore):
        tables = set(exact.list_tables())
        assert "vector_exact_meta" in tables
        assert "vector_exact_dimension_tables" in tables

    def test_ensure_dimension_table_registers(self, exact: DuckDBExactVectorStore):
        name = exact.ensure_dimension_table(dimension=DIM, dtype=DTYPE)
        assert name == "vector_exact_f32_d4"
        assert name in exact.list_tables()
        registered = exact.list_dimension_tables()
        assert any(t["table_name"] == name and t["dimension"] == DIM for t in registered)
        digest = exact.schema_digest()
        assert digest.startswith("sha256:")
        assert exact.schema_digest() == digest


# ---------------------------------------------------------------------------
# Mixed dimensions cannot enter one physical table
# ---------------------------------------------------------------------------


class TestDimensionIsolation:
    def test_wrong_length_rejected_on_upsert(self, exact: DuckDBExactVectorStore, dim_table):
        with pytest.raises(VectorStoreContractError) as exc:
            exact.upsert_vector(
                chunk_id="bad",
                collection_id="col",
                document_id="doc",
                generation_id=1,
                vector=[1.0, 0.0, 0.0],  # length 3 into dim 4
                generation_content_digest=GEN_DIGEST,
                dimension=DIM,
                dtype=DTYPE,
            )
        assert exc.value.code == "DIMENSION_MISMATCH"
        assert "cannot enter physical table" in exc.value.message

    def test_mixed_batch_rejected_atomically(self, exact: DuckDBExactVectorStore, dim_table):
        with pytest.raises(VectorStoreContractError) as exc:
            exact.upsert_many(
                [
                    {
                        "chunk_id": "ok",
                        "document_id": "d",
                        "vector": _vec(1, 0, 0, 0),
                    },
                    {
                        "chunk_id": "bad",
                        "document_id": "d",
                        "vector": [0.0, 1.0],  # wrong dim
                    },
                ],
                dimension=DIM,
                dtype=DTYPE,
                collection_id="col",
                generation_id=1,
                generation_content_digest=GEN_DIGEST,
            )
        assert exc.value.code == "DIMENSION_MISMATCH"
        # No partial write of the good row.
        assert exact.get_vector("ok", dimension=DIM, dtype=DTYPE) is None

    def test_sql_array_type_rejects_mixed_insert(self, exact: DuckDBExactVectorStore, dim_table):
        """DuckDB FLOAT[N] column itself refuses a different array size."""

        with exact._lock:
            with pytest.raises(Exception):
                exact._conn.execute(
                    f"INSERT INTO {dim_table} VALUES ("
                    f"'x','c','d',1,0,[1.0,0.0,0.0]::FLOAT[3],"
                    f"'{GEN_DIGEST}','{GEN_DIGEST}','{GEN_DIGEST}',"
                    f"'live','{{}}','t')"
                )

    def test_separate_physical_tables_per_dimension(self, exact: DuckDBExactVectorStore):
        t4 = exact.ensure_dimension_table(dimension=4, dtype="float32")
        t8 = exact.ensure_dimension_table(dimension=8, dtype="float32")
        assert t4 != t8
        exact.upsert_vector(
            chunk_id="c4",
            collection_id="col",
            document_id="d",
            generation_id=1,
            vector=_vec(1, 0, 0, 0),
            generation_content_digest=GEN_DIGEST,
            dimension=4,
        )
        exact.upsert_vector(
            chunk_id="c8",
            collection_id="col",
            document_id="d",
            generation_id=1,
            vector=[1, 0, 0, 0, 0, 0, 0, 0],
            generation_content_digest=GEN_DIGEST,
            dimension=8,
        )
        assert exact.get_vector("c4", dimension=4) is not None
        assert exact.get_vector("c8", dimension=8) is not None
        assert exact.get_vector("c4", dimension=8) is None


# ---------------------------------------------------------------------------
# Exact results agree with NumPy fixtures
# ---------------------------------------------------------------------------


class TestNumpyParity:
    """Distances from DuckDB exact search must match NumPy reference metrics."""

    FIXTURES = {
        "a": _vec(1.0, 0.0, 0.0, 0.0),
        "b": _vec(0.0, 1.0, 0.0, 0.0),
        "c": _vec(0.7, 0.7, 0.0, 0.0),
        "d": _vec(0.5, 0.5, 0.5, 0.5),
    }
    QUERY = _vec(1.0, 0.0, 0.0, 0.0)

    @pytest.fixture
    def seeded(self, exact: DuckDBExactVectorStore) -> DuckDBExactVectorStore:
        _seed(
            exact,
            [
                {
                    "chunk_id": cid,
                    "document_id": f"doc_{cid}",
                    "vector": vec,
                    "ordinal": i,
                }
                for i, (cid, vec) in enumerate(self.FIXTURES.items())
            ],
        )
        return exact

    def test_l2_matches_numpy(self, seeded: DuckDBExactVectorStore):
        hits = seeded.search(
            collection_id="col_docs",
            query=self.QUERY,
            dimension=DIM,
            dtype=DTYPE,
            metric="l2",
            top_k=10,
        )
        by_id = {h.chunk_id: h.distance for h in hits}
        for cid, vec in self.FIXTURES.items():
            expected = numpy_l2_distance(self.QUERY, vec, dtype=DTYPE)
            assert by_id[cid] == pytest.approx(expected, rel=1e-6, abs=1e-6)

        # Ranking: a (0), then c, d, b
        assert [h.chunk_id for h in hits][0] == "a"
        assert hits[0].distance == pytest.approx(0.0, abs=1e-6)

    def test_cosine_matches_numpy(self, seeded: DuckDBExactVectorStore):
        hits = seeded.search(
            collection_id="col_docs",
            query=self.QUERY,
            dimension=DIM,
            metric="cosine",
            top_k=10,
        )
        by_id = {h.chunk_id: h.distance for h in hits}
        for cid, vec in self.FIXTURES.items():
            expected = numpy_cosine_distance(self.QUERY, vec, dtype=DTYPE)
            assert by_id[cid] == pytest.approx(expected, rel=1e-5, abs=1e-5)
        assert hits[0].chunk_id == "a"

    def test_inner_product_ranking_matches_numpy(self, seeded: DuckDBExactVectorStore):
        hits = seeded.search(
            collection_id="col_docs",
            query=self.QUERY,
            dimension=DIM,
            metric="ip",
            top_k=10,
        )
        # distance stored is negative IP; nearest (highest IP) first
        ips = {
            cid: numpy_inner_product(self.QUERY, vec, dtype=DTYPE)
            for cid, vec in self.FIXTURES.items()
        }
        for h in hits:
            assert h.distance == pytest.approx(-ips[h.chunk_id], rel=1e-5, abs=1e-5)
        # Highest IP is a (1.0)
        assert hits[0].chunk_id == "a"
        # Order by IP descending
        ordered = sorted(self.FIXTURES, key=lambda cid: -ips[cid])
        assert [h.chunk_id for h in hits] == ordered

    def test_euclidean_alias(self, seeded: DuckDBExactVectorStore):
        l2 = seeded.search(
            collection_id="col_docs",
            query=self.QUERY,
            dimension=DIM,
            metric="l2",
            top_k=4,
        )
        eu = seeded.search(
            collection_id="col_docs",
            query=self.QUERY,
            dimension=DIM,
            metric="euclidean",
            top_k=4,
        )
        assert [h.chunk_id for h in l2] == [h.chunk_id for h in eu]
        for a, b in zip(l2, eu):
            assert a.distance == pytest.approx(b.distance, abs=1e-9)

    def test_float64_numpy_parity(self, exact: DuckDBExactVectorStore):
        dim = 3
        dtype = "float64"
        fixtures = {
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0],
            "z": [0.6, 0.8, 0.0],
        }
        query = [1.0, 0.0, 0.0]
        _seed(
            exact,
            [
                {"chunk_id": k, "document_id": "d", "vector": v}
                for k, v in fixtures.items()
            ],
            dimension=dim,
            dtype=dtype,
        )
        hits = exact.search(
            collection_id="col_docs",
            query=query,
            dimension=dim,
            dtype=dtype,
            metric="l2",
            top_k=3,
        )
        for h in hits:
            expected = numpy_l2_distance(query, fixtures[h.chunk_id], dtype=dtype)
            assert h.distance == pytest.approx(expected, rel=1e-12, abs=1e-12)


# ---------------------------------------------------------------------------
# Metadata filters + deterministic tie-breaking
# ---------------------------------------------------------------------------


class TestFiltersAndTieBreak:
    def test_metadata_equality_filter(self, exact: DuckDBExactVectorStore):
        _seed(
            exact,
            [
                {
                    "chunk_id": "en1",
                    "document_id": "d1",
                    "vector": _vec(1, 0, 0, 0),
                    "metadata": {"lang": "en", "tier": 1},
                },
                {
                    "chunk_id": "en2",
                    "document_id": "d2",
                    "vector": _vec(0.9, 0.1, 0, 0),
                    "metadata": {"lang": "en", "tier": 2},
                },
                {
                    "chunk_id": "fr1",
                    "document_id": "d3",
                    "vector": _vec(0.99, 0.01, 0, 0),
                    "metadata": {"lang": "fr", "tier": 1},
                },
            ],
        )
        hits = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            metric="l2",
            top_k=10,
            metadata_filter={"lang": "en"},
        )
        assert {h.chunk_id for h in hits} == {"en1", "en2"}
        hits_tier = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            metric="l2",
            top_k=10,
            metadata_filter={"lang": "en", "tier": 1},
        )
        assert [h.chunk_id for h in hits_tier] == ["en1"]

    def test_deterministic_tie_break_by_chunk_id(self, exact: DuckDBExactVectorStore):
        # Identical vectors → identical distance; order by chunk_id ASC.
        same = _vec(1, 0, 0, 0)
        ids = ["chunk_c", "chunk_a", "chunk_b"]
        _seed(
            exact,
            [
                {"chunk_id": cid, "document_id": "doc", "vector": same, "ordinal": 0}
                for cid in ids
            ],
        )
        hits = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            metric="l2",
            top_k=10,
        )
        assert [h.chunk_id for h in hits] == sorted(ids)
        distances = [h.distance for h in hits]
        assert all(d == pytest.approx(0.0, abs=1e-6) for d in distances)
        # Ranks are 1-based contiguous.
        assert [h.rank for h in hits] == [1, 2, 3]

    def test_tie_break_stable_across_runs(self, exact: DuckDBExactVectorStore):
        same = _vec(0.5, 0.5, 0.5, 0.5)
        _seed(
            exact,
            [
                {"chunk_id": "z", "document_id": "d", "vector": same},
                {"chunk_id": "m", "document_id": "d", "vector": same},
                {"chunk_id": "a", "document_id": "d", "vector": same},
            ],
        )
        first = [
            h.chunk_id
            for h in exact.search(
                collection_id="col_docs",
                query=_vec(0.5, 0.5, 0.5, 0.5),
                dimension=DIM,
                top_k=10,
            )
        ]
        second = [
            h.chunk_id
            for h in exact.search(
                collection_id="col_docs",
                query=_vec(0.5, 0.5, 0.5, 0.5),
                dimension=DIM,
                top_k=10,
            )
        ]
        assert first == second == ["a", "m", "z"]

    def test_unsafe_metadata_key_rejected(self, exact: DuckDBExactVectorStore, dim_table):
        _seed(
            exact,
            [{"chunk_id": "c", "document_id": "d", "vector": _vec(1, 0, 0, 0)}],
        )
        with pytest.raises(VectorStoreContractError) as exc:
            exact.search(
                collection_id="col_docs",
                query=_vec(1, 0, 0, 0),
                dimension=DIM,
                metadata_filter={"lang;drop": "en"},
            )
        assert exc.value.code == "INVALID_METADATA"


# ---------------------------------------------------------------------------
# Generation + content digest binding
# ---------------------------------------------------------------------------


class TestGenerationBinding:
    def test_hits_bind_generation_and_digests(self, exact: DuckDBExactVectorStore):
        rows = _seed(
            exact,
            [
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "vector": _vec(1, 0, 0, 0),
                    "metadata": {"k": "v"},
                }
            ],
            generation_id=7,
            generation_content_digest=GEN_DIGEST,
        )
        assert rows[0].generation_id == 7
        assert rows[0].generation_content_digest == GEN_DIGEST
        assert rows[0].value_digest == vector_content_digest(
            _vec(1, 0, 0, 0), dimension=DIM, dtype=DTYPE
        )

        hits = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            top_k=1,
            include_vector=True,
        )
        assert len(hits) == 1
        hit = hits[0]
        assert isinstance(hit, ExactSearchHit)
        assert hit.generation_id == 7
        assert hit.generation_content_digest == GEN_DIGEST
        assert hit.value_digest.startswith("sha256:")
        assert hit.chunk_content_digest.startswith("sha256:")
        assert hit.vector is not None
        assert hit.vector[0] == pytest.approx(1.0, abs=1e-5)

    def test_filter_by_generation_identity(self, exact: DuckDBExactVectorStore):
        _seed(
            exact,
            [{"chunk_id": "g1", "document_id": "d", "vector": _vec(1, 0, 0, 0)}],
            generation_id=1,
            generation_content_digest=GEN_DIGEST,
        )
        _seed(
            exact,
            [{"chunk_id": "g2", "document_id": "d", "vector": _vec(0, 1, 0, 0)}],
            generation_id=2,
            generation_content_digest=GEN_DIGEST_2,
        )
        hits = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            top_k=10,
            generation_id=2,
            generation_content_digest=GEN_DIGEST_2,
        )
        assert [h.chunk_id for h in hits] == ["g2"]
        assert hits[0].generation_content_digest == GEN_DIGEST_2

    def test_tombstoned_not_searchable(self, exact: DuckDBExactVectorStore):
        _seed(
            exact,
            [
                {"chunk_id": "live", "document_id": "d", "vector": _vec(1, 0, 0, 0)},
                {
                    "chunk_id": "dead",
                    "document_id": "d",
                    "vector": _vec(0.99, 0.01, 0, 0),
                    "status": "tombstoned",
                },
            ],
        )
        hits = exact.search(
            collection_id="col_docs",
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            top_k=10,
        )
        assert [h.chunk_id for h in hits] == ["live"]


# ---------------------------------------------------------------------------
# Lifecycle materialization
# ---------------------------------------------------------------------------


class TestLifecycleMaterialize:
    def test_materialize_from_published_generation(self, tmp_path: Path):
        life_path = tmp_path / "life.duckdb"
        exact_path = tmp_path / "exact.duckdb"

        life = DuckDBVectorStore(life_path)
        life.create_embedding_model(
            name="m",
            provider="p",
            revision="r1",
            dtype=DTYPE,
            dimension=DIM,
            model_id="model_t",
        )
        col = life.create_collection(
            name="docs",
            dimension=DIM,
            dtype=DTYPE,
            model_id="model_t",
            chunking_identity="chunk:fixed@1",
            normalization_identity="norm:l2@1",
            collection_id="col_docs",
        )
        gen = life.open_generation(col.collection_id)
        doc = life.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="doc-a",
        )
        c1 = life.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="chunk_a",
            metadata={"lang": "en"},
        )
        c2 = life.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(0, 1, 0, 0),
            chunk_id="chunk_b",
            ordinal=1,
            metadata={"lang": "fr"},
        )
        # Draft not visible — materialize empty.
        exact = DuckDBExactVectorStore(exact_path)
        assert exact.materialize_from_lifecycle(life, collection_id=col.collection_id) == []

        published = life.publish_generation(col.collection_id, gen.generation_id)
        rows = exact.materialize_from_lifecycle(life, collection_id=col.collection_id)
        assert {r.chunk_id for r in rows} == {"chunk_a", "chunk_b"}
        for r in rows:
            assert r.generation_id == published.generation_id
            assert r.generation_content_digest == published.content_digest
            assert r.value_digest.startswith("sha256:")

        hits = exact.search(
            collection_id=col.collection_id,
            query=_vec(1, 0, 0, 0),
            dimension=DIM,
            metric="l2",
            top_k=2,
            generation_id=published.generation_id,
            generation_content_digest=published.content_digest,
            metadata_filter={"lang": "en"},
        )
        assert len(hits) == 1
        assert hits[0].chunk_id == c1.chunk_id
        assert hits[0].generation_content_digest == published.content_digest
        assert hits[0].distance == pytest.approx(0.0, abs=1e-6)

        # After delete in lifecycle + rematerialize, stale exact row is gone.
        life.delete_chunk(collection_id=col.collection_id, chunk_id=c2.chunk_id)
        rows2 = exact.materialize_from_lifecycle(life, collection_id=col.collection_id)
        assert {r.chunk_id for r in rows2} == {"chunk_a"}
        assert exact.count_live(
            collection_id=col.collection_id, dimension=DIM, dtype=DTYPE
        ) == 1

        life.close()
        exact.close()


# ---------------------------------------------------------------------------
# Contracts / errors
# ---------------------------------------------------------------------------


class TestContracts:
    def test_query_dimension_mismatch(self, exact: DuckDBExactVectorStore, dim_table):
        _seed(
            exact,
            [{"chunk_id": "c", "document_id": "d", "vector": _vec(1, 0, 0, 0)}],
        )
        with pytest.raises(VectorStoreContractError) as exc:
            exact.search(
                collection_id="col_docs",
                query=[1.0, 0.0],
                dimension=DIM,
            )
        assert exc.value.code == "DIMENSION_MISMATCH"

    def test_missing_dimension_table(self, exact: DuckDBExactVectorStore):
        with pytest.raises(VectorStoreContractError) as exc:
            exact.search(
                collection_id="col",
                query=_vec(1, 0, 0, 0),
                dimension=DIM,
            )
        assert exc.value.code == "DIMENSION_TABLE_MISSING"

    def test_invalid_metric(self, exact: DuckDBExactVectorStore, dim_table):
        _seed(
            exact,
            [{"chunk_id": "c", "document_id": "d", "vector": _vec(1, 0, 0, 0)}],
        )
        with pytest.raises(VectorStoreContractError) as exc:
            exact.search(
                collection_id="col_docs",
                query=_vec(1, 0, 0, 0),
                dimension=DIM,
                metric="hamming",
            )
        assert exc.value.code == "INVALID_METRIC"

    def test_top_k_and_persistence(self, tmp_path: Path):
        path = tmp_path / "persist.duckdb"
        store = DuckDBExactVectorStore(path)
        _seed(
            store,
            [
                {"chunk_id": f"c{i}", "document_id": "d", "vector": _vec(1, 0, 0, 0)}
                for i in range(5)
            ],
        )
        store.close()

        reopened = DuckDBExactVectorStore(path)
        try:
            assert "vector_exact_f32_d4" in reopened.list_tables()
            hits = reopened.search(
                collection_id="col_docs",
                query=_vec(1, 0, 0, 0),
                dimension=DIM,
                top_k=3,
            )
            assert len(hits) == 3
            assert reopened.count_live(
                collection_id="col_docs", dimension=DIM, dtype=DTYPE
            ) == 5
        finally:
            reopened.close()
