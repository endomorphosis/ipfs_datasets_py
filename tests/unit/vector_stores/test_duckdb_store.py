"""Unit tests for the DuckDB vector lifecycle store (DQK-020).

Acceptance coverage:

* Update/delete cannot leave query-visible stale vectors
* Model/chunking/normalization identity is mandatory
* Generations publish atomically
* Exact dimension and dtype contracts
* Normalized source identities
* No pickle authority
"""

from __future__ import annotations

import importlib
import inspect
import pickle
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_store import (
    ALLOWED_DTYPES,
    DUCKDB_VECTOR_STORE_SCHEMA,
    SCHEMA_VERSION,
    VECTOR_TABLES,
    DuckDBVectorStore,
    GenerationStatus,
    VectorStoreContractError,
    canonical_identity_digest,
    decode_vector_bytes,
    encode_vector_bytes,
    normalize_source_identity,
    vector_content_digest,
)


DIM = 4
DTYPE = "float32"


def _vec(*values: float) -> list[float]:
    assert len(values) == DIM
    return list(values)


@pytest.fixture
def store(tmp_path: Path) -> DuckDBVectorStore:
    path = tmp_path / "vectors.duckdb"
    s = DuckDBVectorStore(path)
    yield s
    s.close()


@pytest.fixture
def model(store: DuckDBVectorStore):
    return store.create_embedding_model(
        name="text-embed-test",
        provider="unit",
        revision="r1",
        dtype=DTYPE,
        dimension=DIM,
        model_id="model_test",
    )


def _collection(store: DuckDBVectorStore, model_id: str = "model_test", **kwargs):
    defaults = dict(
        name="docs",
        dimension=DIM,
        dtype=DTYPE,
        model_id=model_id,
        chunking_identity="chunk:fixed-512@1",
        normalization_identity="norm:l2@1",
        source_revision="src-1",
        collection_id="col_docs",
    )
    defaults.update(kwargs)
    return store.create_collection(**defaults)


# ---------------------------------------------------------------------------
# Module / schema invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_import_does_not_require_pickle_authority(self):
        source = Path(
            inspect.getsourcefile(
                importlib.import_module("ipfs_datasets_py.vector_stores.duckdb_store")
            )
        ).read_text(encoding="utf-8")
        # Runtime authority path must not load pickle payloads.
        assert "pickle.load" not in source
        assert "pickle.loads" not in source
        assert "pickle.dump" not in source
        assert "pickle.dumps" not in source

    def test_schema_constants(self):
        assert SCHEMA_VERSION == 1
        assert DUCKDB_VECTOR_STORE_SCHEMA.startswith("ipfs_datasets_py/")
        assert "float32" in ALLOWED_DTYPES
        assert "float64" in ALLOWED_DTYPES
        for table in VECTOR_TABLES:
            assert table

    def test_all_lifecycle_tables_created(self, store: DuckDBVectorStore):
        tables = set(store.list_tables())
        for name in VECTOR_TABLES:
            assert name in tables, f"missing table {name}"

    def test_schema_digest_stable(self, store: DuckDBVectorStore):
        a = store.schema_digest()
        b = store.schema_digest()
        assert a == b
        assert a.startswith("sha256:")

    def test_reopen_preserves_schema(self, tmp_path: Path, model, store):
        # model fixture already created; reopen same file
        path = store.path
        store.close()
        reopened = DuckDBVectorStore(path)
        try:
            tables = set(reopened.list_tables())
            for name in VECTOR_TABLES:
                assert name in tables
            reopened.get_embedding_model("model_test")
        finally:
            reopened.close()


# ---------------------------------------------------------------------------
# Identity / dtype / dimension contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_encode_decode_roundtrip_float32(self):
        values = _vec(0.1, -0.2, 0.3, 0.4)
        raw = encode_vector_bytes(values, dimension=DIM, dtype="float32")
        decoded = decode_vector_bytes(raw, dimension=DIM, dtype="float32")
        assert len(decoded) == DIM
        for a, b in zip(decoded, values):
            assert a == pytest.approx(b, rel=1e-6, abs=1e-6)

    def test_dimension_mismatch_rejected(self):
        with pytest.raises(VectorStoreContractError) as exc:
            encode_vector_bytes([1.0, 2.0], dimension=DIM, dtype="float32")
        assert exc.value.code == "DIMENSION_MISMATCH"

    def test_dtype_rejected(self):
        with pytest.raises(VectorStoreContractError) as exc:
            encode_vector_bytes(_vec(1, 2, 3, 4), dimension=DIM, dtype="float16")
        assert exc.value.code == "INVALID_DTYPE"

    def test_nonfinite_rejected(self):
        with pytest.raises(VectorStoreContractError) as exc:
            encode_vector_bytes(_vec(1.0, float("nan"), 0.0, 0.0), dimension=DIM, dtype="float32")
        assert exc.value.code == "INVALID_VECTOR"

    def test_normalize_source_identity_digest(self):
        identity, digest = normalize_source_identity("sha256:" + "ab" * 32)
        assert identity.startswith("sha256:")
        assert digest == identity

    def test_normalize_source_strips_file_uri(self):
        identity, digest = normalize_source_identity("file:///data/docs/a.txt")
        assert digest.startswith("sha256:")
        assert identity  # non-empty
        # Second call is deterministic.
        identity2, digest2 = normalize_source_identity("file:///data/docs/a.txt")
        assert digest == digest2
        assert identity == identity2

    def test_pickle_path_forbidden_as_source(self):
        with pytest.raises(VectorStoreContractError) as exc:
            normalize_source_identity("/var/lib/index_metadata.pkl")
        assert exc.value.code == "PICKLE_FORBIDDEN"

    def test_vector_content_digest_stable(self):
        v = _vec(1.0, 0.0, 0.0, 0.0)
        assert vector_content_digest(v, dimension=DIM, dtype=DTYPE) == vector_content_digest(
            v, dimension=DIM, dtype=DTYPE
        )

    def test_mandatory_identities_on_collection(self, store, model):
        with pytest.raises(VectorStoreContractError) as exc:
            store.create_collection(
                name="bad",
                dimension=DIM,
                dtype=DTYPE,
                model_id=model.model_id,
                chunking_identity="",
                normalization_identity="norm:l2@1",
            )
        assert exc.value.code == "MISSING_IDENTITY"

        with pytest.raises(VectorStoreContractError) as exc:
            store.create_collection(
                name="bad2",
                dimension=DIM,
                dtype=DTYPE,
                model_id=model.model_id,
                chunking_identity="chunk:fixed-512@1",
                normalization_identity="",
            )
        assert exc.value.code == "MISSING_IDENTITY"

    def test_collection_must_match_model_dim_dtype(self, store, model):
        with pytest.raises(VectorStoreContractError) as exc:
            store.create_collection(
                name="bad-dim",
                dimension=DIM + 1,
                dtype=DTYPE,
                model_id=model.model_id,
                chunking_identity="chunk:fixed-512@1",
                normalization_identity="norm:l2@1",
            )
        assert exc.value.code == "DIMENSION_MISMATCH"

        with pytest.raises(VectorStoreContractError) as exc:
            store.create_collection(
                name="bad-dtype",
                dimension=DIM,
                dtype="float64",
                model_id=model.model_id,
                chunking_identity="chunk:fixed-512@1",
                normalization_identity="norm:l2@1",
            )
        assert exc.value.code == "DTYPE_MISMATCH"


# ---------------------------------------------------------------------------
# Lifecycle: draft → publish atomicity
# ---------------------------------------------------------------------------


class TestGenerationLifecycle:
    def test_draft_not_query_visible(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="docs/a.txt",
        )
        chunk = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            text="hello",
        )
        assert store.list_query_visible_chunks(col.collection_id) == []
        assert store.get_query_visible_vector(col.collection_id, chunk.chunk_id) is None

    def test_publish_makes_chunks_visible_atomically(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source={"uri": "ipfs://bafytest", "digest": "sha256:" + "11" * 32},
        )
        c1 = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            ordinal=0,
        )
        c2 = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(0, 1, 0, 0),
            ordinal=1,
        )
        published = store.publish_generation(col.collection_id, gen.generation_id)
        assert published.status == GenerationStatus.PUBLISHED.value
        assert published.published_at is not None
        assert published.content_digest.startswith("sha256:")
        assert published.chunk_count == 2

        col2 = store.get_collection(col.collection_id)
        assert col2.published_generation == gen.generation_id

        visible = store.list_query_visible_chunks(col.collection_id)
        assert {c.chunk_id for c in visible} == {c1.chunk_id, c2.chunk_id}

    def test_second_generation_supersedes_first(self, store, model):
        col = _collection(store)
        g1 = store.open_generation(col.collection_id)
        d1 = store.add_document(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            source="a",
        )
        old = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            document_id=d1.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="chunk_old",
        )
        store.publish_generation(col.collection_id, g1.generation_id)

        g2 = store.open_generation(col.collection_id)
        d2 = store.add_document(
            collection_id=col.collection_id,
            generation_id=g2.generation_id,
            source="b",
        )
        new = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g2.generation_id,
            document_id=d2.document_id,
            vector=_vec(0, 1, 0, 0),
            chunk_id="chunk_new",
        )
        # Before publish of g2, g1 remains visible.
        visible = {c.chunk_id for c in store.list_query_visible_chunks(col.collection_id)}
        assert visible == {"chunk_old"}

        store.publish_generation(col.collection_id, g2.generation_id)
        g1_after = store.get_generation(col.collection_id, g1.generation_id)
        assert g1_after.status == GenerationStatus.SUPERSEDED.value
        visible = {c.chunk_id for c in store.list_query_visible_chunks(col.collection_id)}
        assert visible == {"chunk_new"}
        assert store.get_query_visible_vector(col.collection_id, old.chunk_id) is None
        assert store.get_query_visible_vector(col.collection_id, new.chunk_id) is not None

    def test_cannot_mutate_published_generation_directly(self, store, model):
        col = _collection(store)
        g1 = store.open_generation(col.collection_id)
        d1 = store.add_document(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            source="a",
        )
        store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            document_id=d1.document_id,
            vector=_vec(1, 0, 0, 0),
        )
        store.publish_generation(col.collection_id, g1.generation_id)
        with pytest.raises(VectorStoreContractError) as exc:
            store.add_document(
                collection_id=col.collection_id,
                generation_id=g1.generation_id,
                source="b",
            )
        assert exc.value.code == "NOT_DRAFT"

    def test_abort_generation_tombstones_draft_chunks(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="a",
        )
        chunk = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
        )
        aborted = store.abort_generation(col.collection_id, gen.generation_id)
        assert aborted.status == GenerationStatus.ABORTED.value
        stored = store.get_chunk(chunk.chunk_id)
        assert stored.status == "tombstoned"
        assert store.list_query_visible_chunks(col.collection_id) == []


# ---------------------------------------------------------------------------
# Update / delete: no query-visible stale vectors
# ---------------------------------------------------------------------------


class TestUpdateDeleteVisibility:
    def test_delete_removes_from_query_visible(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="a",
        )
        c1 = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="keep",
        )
        c2 = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(0, 1, 0, 0),
            chunk_id="drop",
        )
        store.publish_generation(col.collection_id, gen.generation_id)

        tomb = store.delete_chunk(
            collection_id=col.collection_id, chunk_id="drop", reason="user_delete"
        )
        assert tomb.entity_id == "drop"
        visible = {c.chunk_id for c in store.list_query_visible_chunks(col.collection_id)}
        assert visible == {"keep"}
        assert store.get_query_visible_vector(col.collection_id, "drop") is None
        # keep still visible with original vector
        value = store.get_query_visible_vector(col.collection_id, c1.chunk_id)
        assert value is not None
        assert value.vector[0] == pytest.approx(1.0, abs=1e-5)

    def test_update_published_chunk_drops_stale_immediately(self, store, model):
        col = _collection(store)
        g1 = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            source="a",
        )
        old = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="stale",
            text="old",
        )
        store.publish_generation(col.collection_id, g1.generation_id)

        # Open draft required for published updates.
        store.open_generation(col.collection_id)
        replacement = store.update_chunk(
            collection_id=col.collection_id,
            chunk_id="stale",
            vector=_vec(0, 0, 1, 0),
            text="new",
        )
        # Old chunk no longer query-visible even before draft publish.
        visible = {c.chunk_id for c in store.list_query_visible_chunks(col.collection_id)}
        assert "stale" not in visible
        assert store.get_query_visible_vector(col.collection_id, "stale") is None
        old_row = store.get_chunk("stale")
        assert old_row.status == "tombstoned"

        # Replacement lives in draft — still not query-visible until publish.
        assert replacement.generation_id != g1.generation_id
        assert store.get_query_visible_vector(col.collection_id, replacement.chunk_id) is None

        store.publish_generation(col.collection_id, replacement.generation_id)
        value = store.get_query_visible_vector(col.collection_id, replacement.chunk_id)
        assert value is not None
        assert value.vector[2] == pytest.approx(1.0, abs=1e-5)
        # Stale remains non-visible after publish of successor.
        assert store.get_query_visible_vector(col.collection_id, "stale") is None

    def test_in_place_draft_update_no_dual_live(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="a",
        )
        chunk = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="draft_chunk",
        )
        updated = store.update_chunk(
            collection_id=col.collection_id,
            chunk_id="draft_chunk",
            vector=_vec(0, 1, 0, 0),
        )
        assert updated.chunk_id == chunk.chunk_id
        store.publish_generation(col.collection_id, gen.generation_id)
        visible = store.list_query_visible_chunks(col.collection_id)
        assert len(visible) == 1
        value = store.get_query_visible_vector(col.collection_id, "draft_chunk")
        assert value is not None
        assert value.vector[1] == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# Shards, index builds, compaction
# ---------------------------------------------------------------------------


class TestShardsBuildsCompaction:
    def test_register_shard_and_index_build(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="a",
        )
        store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(1, 0, 0, 0),
        )
        shard = store.register_shard(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            shard_index=0,
            vector_count=1,
        )
        assert shard.content_digest.startswith("sha256:")
        store.publish_generation(col.collection_id, gen.generation_id)
        build = store.record_index_build(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            index_kind="vss_hnsw",
        )
        assert build.status == "completed"
        assert build.receipt_digest.startswith("sha256:")

    def test_compaction_removes_tombstoned_old_generation(self, store, model):
        col = _collection(store)
        g1 = store.open_generation(col.collection_id)
        d1 = store.add_document(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            source="a",
        )
        store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g1.generation_id,
            document_id=d1.document_id,
            vector=_vec(1, 0, 0, 0),
            chunk_id="g1_chunk",
        )
        store.publish_generation(col.collection_id, g1.generation_id)
        store.delete_chunk(collection_id=col.collection_id, chunk_id="g1_chunk")

        g2 = store.open_generation(col.collection_id)
        d2 = store.add_document(
            collection_id=col.collection_id,
            generation_id=g2.generation_id,
            source="b",
        )
        store.add_chunk(
            collection_id=col.collection_id,
            generation_id=g2.generation_id,
            document_id=d2.document_id,
            vector=_vec(0, 1, 0, 0),
            chunk_id="g2_chunk",
        )
        store.publish_generation(col.collection_id, g2.generation_id)

        result = store.compact(
            collection_id=col.collection_id,
            from_generation=1,
            to_generation=2,
        )
        assert result.status == "completed"
        assert result.removed_count >= 1
        # Live published generation intact.
        visible = {c.chunk_id for c in store.list_query_visible_chunks(col.collection_id)}
        assert visible == {"g2_chunk"}
        # Tombstoned g1 chunk hard-deleted.
        with pytest.raises(VectorStoreContractError) as exc:
            store.get_chunk("g1_chunk")
        assert exc.value.code == "CHUNK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Persistence / restart
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_restart_restores_published_visibility(self, tmp_path: Path):
        path = tmp_path / "persist.duckdb"
        store = DuckDBVectorStore(path)
        store.create_embedding_model(
            name="m",
            provider="p",
            revision="r",
            dtype=DTYPE,
            dimension=DIM,
            model_id="m1",
        )
        col = store.create_collection(
            name="persist",
            dimension=DIM,
            dtype=DTYPE,
            model_id="m1",
            chunking_identity="chunk:fixed-512@1",
            normalization_identity="norm:l2@1",
            collection_id="col_p",
        )
        gen = store.open_generation(col.collection_id)
        doc = store.add_document(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            source="s",
        )
        chunk = store.add_chunk(
            collection_id=col.collection_id,
            generation_id=gen.generation_id,
            document_id=doc.document_id,
            vector=_vec(0.5, 0.5, 0.0, 0.0),
            chunk_id="persist_chunk",
        )
        store.publish_generation(col.collection_id, gen.generation_id)
        store.close()

        reopened = DuckDBVectorStore(path)
        try:
            visible = reopened.list_query_visible_chunks(col.collection_id)
            assert [c.chunk_id for c in visible] == ["persist_chunk"]
            value = reopened.get_query_visible_vector(col.collection_id, chunk.chunk_id)
            assert value is not None
            assert value.dimension == DIM
            assert value.dtype == DTYPE
            col2 = reopened.get_collection(col.collection_id)
            assert col2.chunking_identity == "chunk:fixed-512@1"
            assert col2.normalization_identity == "norm:l2@1"
            assert col2.model_id == "m1"
        finally:
            reopened.close()


# ---------------------------------------------------------------------------
# No pickle authority (runtime)
# ---------------------------------------------------------------------------


class TestNoPickleAuthority:
    def test_store_rejects_pickle_source_identity(self, store, model):
        col = _collection(store)
        gen = store.open_generation(col.collection_id)
        with pytest.raises(VectorStoreContractError) as exc:
            store.add_document(
                collection_id=col.collection_id,
                generation_id=gen.generation_id,
                source="/tmp/vector_metadata.pkl",
            )
        assert exc.value.code == "PICKLE_FORBIDDEN"

    def test_cannot_bootstrap_from_pickle_blob(self, store, model):
        """Ensure pickle payloads are not a supported import path on this API."""

        col = _collection(store)
        payload = pickle.dumps({"collection": col.to_dict()})
        # There is intentionally no load_pickle / import_pickle method.
        assert not hasattr(store, "load_pickle")
        assert not hasattr(store, "import_pickle")
        assert not hasattr(store, "from_pickle")
        # And the bytes themselves are not accepted as source identity.
        with pytest.raises(VectorStoreContractError):
            normalize_source_identity(payload.hex() + ".pkl")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_canonical_identity_digest_order_independent_for_dict(self):
        a = canonical_identity_digest({"b": 1, "a": 2})
        b = canonical_identity_digest({"a": 2, "b": 1})
        assert a == b
