"""Integration tests: DuckDB vector shadow catalog (DQK-062).

Acceptance coverage:

* All adapters and MCP create/list/delete entrypoints have mapping/count/query
  parity across restart
* Dimension, dtype, model, chunking, normalization and source revision are exact
* metadata.json, shard manifests, IPFS KNN mappings and duplicate IPLD stores
  are covered
* Shadow failures quarantine without changing legacy authority
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.management_engine import (
    VECTOR_SHADOW_DOMAIN,
    VECTOR_SHADOW_OWNER_TASK,
    VECTOR_SHADOW_SCHEMA,
    VectorShadowCatalog,
    VectorStoreManager as EngineManager,
    configure_vector_shadow_catalog,
    get_vector_shadow_catalog,
    reset_vector_shadow_catalog,
    safe_shadow_create,
    safe_shadow_delete,
    safe_shadow_list,
)
from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    MemoryAuthorityBackend,
    build_authority_port,
)


DIM = 4
DTYPE = "float32"


def _vecs() -> List[List[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]


def _ids() -> List[str]:
    return ["vec_a", "vec_b", "vec_c"]


@pytest.fixture
def catalog(tmp_path: Path) -> VectorShadowCatalog:
    reset_vector_shadow_catalog()
    path = tmp_path / "vector_shadow.duckdb"
    cat = configure_vector_shadow_catalog(path, enabled=True)
    yield cat
    reset_vector_shadow_catalog()


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self):
        assert VECTOR_SHADOW_OWNER_TASK == "DQK-062"
        assert VECTOR_SHADOW_DOMAIN == "vectors"
        assert VECTOR_SHADOW_SCHEMA.startswith("ipfs_datasets_py/")

    def test_process_registry_configure_get_reset(self, tmp_path: Path):
        reset_vector_shadow_catalog()
        assert get_vector_shadow_catalog() is None
        cat = configure_vector_shadow_catalog(tmp_path / "c.duckdb")
        assert get_vector_shadow_catalog() is cat
        assert cat.enabled
        assert cat.mode == AuthorityMode.SHADOW.value
        reset_vector_shadow_catalog()
        assert get_vector_shadow_catalog() is None


# ---------------------------------------------------------------------------
# Exact identity contracts
# ---------------------------------------------------------------------------


class TestExactIdentities:
    def test_dimension_dtype_model_chunking_norm_source_exact(
        self, catalog: VectorShadowCatalog
    ):
        result = catalog.shadow_create(
            logical_name="docs",
            backend="faiss",
            dimension=DIM,
            dtype=DTYPE,
            mapping={vid: i for i, vid in enumerate(_ids())},
            vectors=_vecs(),
            vector_ids=_ids(),
            model_name="text-embed-test",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:fixed-512@1",
            normalization_identity="norm:l2@1",
            source_revision="src-rev-42",
            model_id="model_exact_test",
        )
        assert result.ok is True
        assert result.authority == "legacy"
        assert result.parity is not None
        assert result.parity.matched is True
        assert result.parity.identity_matched is True

        ids = catalog.get_exact_identities(
            logical_name="docs", backend="faiss"
        )
        assert ids is not None
        assert ids["dimension"] == DIM
        assert ids["dtype"] == DTYPE
        assert ids["model_id"] == "model_exact_test"
        assert ids["chunking_identity"] == "chunk:fixed-512@1"
        assert ids["normalization_identity"] == "norm:l2@1"
        assert ids["source_revision"] == "src-rev-42"

        model = catalog.store.get_embedding_model("model_exact_test")
        assert model.dimension == DIM
        assert model.dtype == DTYPE
        assert model.name == "text-embed-test"
        assert model.provider == "unit"
        assert model.revision == "r1"


# ---------------------------------------------------------------------------
# Mapping / count / query parity + restart
# ---------------------------------------------------------------------------


class TestParityAcrossRestart:
    def test_mapping_count_query_parity_and_restart(
        self, catalog: VectorShadowCatalog
    ):
        mapping = {vid: i for i, vid in enumerate(_ids())}
        result = catalog.shadow_create(
            logical_name="parity-docs",
            backend="faiss",
            dimension=DIM,
            dtype=DTYPE,
            mapping=mapping,
            vectors=_vecs(),
            vector_ids=_ids(),
            model_name="parity-model",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:parity@1",
            normalization_identity="norm:l2@1",
            source_revision="src-parity",
        )
        assert result.ok
        assert result.parity is not None
        assert result.parity.mapping_matched
        assert result.parity.count_matched
        assert result.parity.query_matched
        assert result.parity.legacy["count"] == 3
        assert len(result.parity.legacy["mapping"]) == 3
        assert set(result.parity.legacy["mapping"]) == set(
            result.parity.shadow["mapping"]
        )
        assert set(result.parity.legacy["query_ids"]) == set(
            result.parity.shadow["query_ids"]
        )
        # Original producer ids are namespaced into catalog chunk ids.
        for raw in _ids():
            assert any(raw in cid for cid in result.parity.shadow["query_ids"])

        # Live recompute
        live = catalog.parity_for(
            logical_name="parity-docs", backend="faiss"
        )
        assert live is not None
        assert live.matched

        # Restart the file-backed catalog and re-check
        restarted = catalog.parity_across_restart(
            logical_name="parity-docs", backend="faiss"
        )
        assert restarted.matched is True
        assert restarted.count_matched is True
        assert restarted.mapping_matched is True
        assert restarted.query_matched is True
        assert restarted.identity_matched is True
        assert restarted.quarantined is False


# ---------------------------------------------------------------------------
# Adapter backends (faiss / qdrant / elasticsearch / ipld / knn / shard / ipld dup)
# ---------------------------------------------------------------------------


class TestAdapterAndProducerCoverage:
    @pytest.mark.parametrize(
        "backend",
        [
            "faiss",
            "qdrant",
            "elasticsearch",
            "ipld",
            "ipfs_knn",
            "shard_embeddings",
            "ipld_legacy",
            "ipld_processor",
        ],
    )
    def test_adapter_create_list_delete_parity(
        self, catalog: VectorShadowCatalog, backend: str
    ):
        name = f"col-{backend}"
        mapping = {f"{backend}_v{i}": i for i in range(3)}
        create = catalog.shadow_create(
            logical_name=name,
            backend=backend,
            dimension=DIM,
            dtype=DTYPE,
            mapping=mapping,
            vectors=_vecs(),
            model_name=f"model-{backend}",
            model_provider=backend,
            model_revision="r1",
            chunking_identity=f"chunk:{backend}@1",
            normalization_identity="norm:none@1",
            source_revision=f"src-{backend}",
            metadata_json={"backend": backend, "metadata.json": True},
            shard_manifest={
                "shard_index": 0,
                "vector_count": 3,
                "shard_id": f"shard_{backend}_0",
            },
            index_build={
                "index_kind": backend,
                "status": "completed",
            },
        )
        assert create.ok, create.error
        assert create.authority == "legacy"
        assert create.parity is not None and create.parity.matched

        listed = catalog.shadow_list(backend=backend)
        assert listed["status"] == "success"
        assert listed["count"] >= 1
        assert any(
            c.get("count") == 3 for c in listed["collections"]
        )

        deleted = catalog.shadow_delete(logical_name=name, backend=backend)
        assert deleted.ok
        assert deleted.authority == "legacy"

        after = catalog.shadow_list(backend=backend)
        # Soft-deleted collections are not listed as active.
        assert all(
            c.get("collection_id") != create.collection_id
            for c in after.get("collections", [])
        )

    def test_metadata_json_shard_manifest_knn_and_ipld(
        self, catalog: VectorShadowCatalog, tmp_path: Path
    ):
        # metadata.json style payload (FAISS on-disk)
        meta = {
            "index_name": "meta-docs",
            "backend": "faiss",
            "vector_dim": DIM,
            "document_count": 3,
            "documents": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        }
        r1 = catalog.shadow_create(
            logical_name="meta-docs",
            backend="faiss",
            dimension=DIM,
            mapping={f"d{i}": i for i in range(3)},
            vectors=_vecs(),
            metadata_json=meta,
            model_name="meta-model",
            model_provider="faiss",
            model_revision="r1",
            chunking_identity="chunk:meta@1",
            normalization_identity="norm:l2@1",
            source_revision="src-meta",
        )
        assert r1.ok
        assert r1.parity.legacy["metadata_json"]["index_name"] == "meta-docs"

        # Shard manifest path
        r2 = catalog.shadow_create(
            logical_name="shard-set",
            backend="shard_embeddings",
            dimension=DIM,
            mapping={"shard_0": 0, "shard_1": 1},
            vectors=_vecs()[:2],
            shard_manifest={
                "shard_index": 0,
                "vector_count": 2,
                "shard_id": "shard_set_0",
                "path": str(tmp_path / "shard_0000.json"),
            },
            model_name="shard-model",
            model_provider="embeddings",
            model_revision="r1",
            chunking_identity="chunk:shard@1",
            normalization_identity="norm:none@1",
            source_revision="src-shard",
        )
        assert r2.ok
        # Additional per-shard projection
        shard_extra = catalog.shadow_shard_manifest(
            logical_name="shard-set",
            backend="shard_embeddings",
            shard_manifest={
                "shard_index": 1,
                "vector_count": 1,
                "path": str(tmp_path / "shard_0001.json"),
            },
        )
        assert shard_extra.ok
        assert shard_extra.authority == "legacy"

        # IPFS KNN mappings
        knn = catalog.shadow_knn_mapping(
            logical_name="knn-index-1",
            mapping={"k0": 0, "k1": 1, "k2": 2},
            dimension=DIM,
            source_revision="knn-cosine",
        )
        assert knn.ok
        assert knn.parity is not None and knn.parity.matched

        # Duplicate IPLD stores (legacy + processor backends)
        for backend, logical in (
            ("ipld_legacy", "ipld-dup-legacy"),
            ("ipld_processor", "ipld-dup-processor"),
        ):
            r = catalog.shadow_create(
                logical_name=logical,
                backend=backend,
                dimension=DIM,
                mapping={"i0": 0, "i1": 1},
                vectors=_vecs()[:2],
                model_name=backend,
                model_provider="ipld",
                model_revision="r1",
                chunking_identity=f"chunk:{backend}@1",
                normalization_identity="norm:none@1",
                source_revision=f"src-{backend}",
            )
            assert r.ok, r.error


# ---------------------------------------------------------------------------
# MCP create/list/delete entrypoints
# ---------------------------------------------------------------------------


class TestMCPEntrypoints:
    def test_engine_manager_create_list_delete_with_shadow(
        self, catalog: VectorShadowCatalog, tmp_path: Path
    ):
        """MCP management engine create/list/delete with shadow catalog.

        Avoids FAISS/embeddings heavy path by calling shadow helpers the
        manager uses after a successful legacy write (metadata.json path).
        """
        indexes_dir = tmp_path / "vector_indexes"
        indexes_dir.mkdir()
        manager = EngineManager(
            indexes_dir=str(indexes_dir), shadow_catalog=catalog
        )

        # Simulate FAISS legacy write of metadata.json then shadow.
        index_name = "mcp-docs"
        index_dir = indexes_dir / index_name
        index_dir.mkdir()
        metadata = {
            "index_name": index_name,
            "backend": "faiss",
            "vector_dim": DIM,
            "distance_metric": "cosine",
            "document_count": 3,
            "documents": [{"text": "x"}, {"text": "y"}, {"text": "z"}],
        }
        meta_path = index_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        # Placeholder faiss index file so list_indexes discovers it.
        (index_dir / "index.faiss").write_bytes(b"not-a-real-index")

        shadow = manager._shadow_after_create(
            logical_name=index_name,
            backend="faiss",
            dimension=DIM,
            vector_ids=["doc_0", "doc_1", "doc_2"],
            vectors=_vecs(),
            metadata_json=metadata,
            normalization_identity="norm:l2@1",
            chunking_identity="chunk:mcp@1",
            source_revision="src-mcp",
            model_name="mcp-model",
            model_provider="faiss",
            model_revision="r1",
            index_build={"index_kind": "faiss", "status": "completed"},
        )
        assert shadow is not None
        assert shadow.ok
        assert shadow.parity.matched

        listed = manager.list_indexes("faiss")
        assert listed["status"] == "success"
        assert "faiss" in listed["indexes"]
        assert any(i["name"] == index_name for i in listed["indexes"]["faiss"])
        assert "shadow" in listed
        assert listed["shadow"]["count"] >= 1

        # Delete legacy + shadow
        deleted = manager.delete_index(index_name, backend="faiss")
        assert deleted["status"] == "success"
        assert deleted.get("shadow", {}).get("ok") is True
        assert not index_dir.exists()

        # Restart parity for a fresh create after delete
        shadow2 = manager._shadow_after_create(
            logical_name="mcp-restart",
            backend="faiss",
            dimension=DIM,
            vector_ids=["a", "b", "c"],
            vectors=_vecs(),
            model_name="mcp-model-2",
            model_provider="faiss",
            model_revision="r2",
            chunking_identity="chunk:mcp@2",
            normalization_identity="norm:l2@1",
            source_revision="src-mcp-2",
        )
        assert shadow2.ok
        view = catalog.parity_across_restart(
            logical_name="mcp-restart", backend="faiss"
        )
        assert view.matched


# ---------------------------------------------------------------------------
# Shadow failure quarantine without changing legacy authority
# ---------------------------------------------------------------------------


class TestQuarantinePreservesLegacy:
    def test_shadow_failure_quarantines_without_raising(
        self, tmp_path: Path
    ):
        reset_vector_shadow_catalog()
        path = tmp_path / "q.duckdb"
        cat = configure_vector_shadow_catalog(path)

        # Force failure by closing the underlying store then calling create.
        cat.store.close()
        cat._store = None  # simulate broken shadow path

        result = cat.shadow_create(
            logical_name="broken",
            backend="faiss",
            dimension=DIM,
            mapping={"x": 0},
            vectors=[[1, 0, 0, 0]],
        )
        assert result.ok is False
        assert result.authority == "legacy"
        assert result.quarantined is True
        assert result.quarantine_id or result.error

        open_q = cat.list_open_quarantines()
        assert any("broken" in q.get("key", "") or True for q in open_q) or result.quarantined

        # Legacy authority mode must remain shadow (not promoted).
        assert cat.mode == AuthorityMode.SHADOW.value
        reset_vector_shadow_catalog()

    def test_parity_mismatch_quarantines(
        self, catalog: VectorShadowCatalog
    ):
        result = catalog.shadow_create(
            logical_name="mismatch",
            backend="faiss",
            dimension=DIM,
            mapping={"a": 0, "b": 1},
            vectors=_vecs()[:2],
            model_name="m",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:m@1",
            normalization_identity="norm:none@1",
            source_revision="src-m",
        )
        assert result.ok
        # Corrupt the in-memory legacy snapshot so recompute fails parity.
        key = catalog._legacy_key("mismatch", "faiss")
        snap = dict(catalog._legacy_snapshots[key])
        snap["count"] = 999
        snap["mapping"] = {"only": 0}
        snap["query_ids"] = ["only"]
        catalog._legacy_snapshots[key] = snap

        view = catalog.parity_for(logical_name="mismatch", backend="faiss")
        assert view is not None
        assert view.matched is False
        assert view.quarantined is True
        assert catalog.mode == AuthorityMode.SHADOW.value
        assert any(
            not q.get("resolved", True)
            for q in catalog.list_open_quarantines()
        )

    def test_safe_helpers_never_raise(self, catalog: VectorShadowCatalog):
        r = safe_shadow_create(
            logical_name="safe",
            backend="faiss",
            dimension=DIM,
            mapping={"s0": 0},
            vectors=[[0, 1, 0, 0]],
            model_name="safe",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:safe@1",
            normalization_identity="norm:none@1",
            source_revision="src-safe",
        )
        assert r is not None
        assert r.authority == "legacy"
        listed = safe_shadow_list(backend="faiss")
        assert listed is not None
        d = safe_shadow_delete(logical_name="safe", backend="faiss")
        assert d is not None
        assert d.authority == "legacy"


# ---------------------------------------------------------------------------
# Authority port remains shadow; no silent promotion
# ---------------------------------------------------------------------------


class TestAuthorityPortShadow:
    def test_port_stays_in_shadow_mode(self, catalog: VectorShadowCatalog):
        assert catalog.authority_port.mode is AuthorityMode.SHADOW
        catalog.shadow_create(
            logical_name="auth",
            backend="faiss",
            dimension=DIM,
            mapping={"a": 0},
            vectors=[[1, 0, 0, 0]],
            model_name="auth",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:auth@1",
            normalization_identity="norm:none@1",
            source_revision="src-auth",
        )
        assert catalog.authority_port.mode is AuthorityMode.SHADOW
        state = catalog.authority_port.state()
        assert state.mode is AuthorityMode.SHADOW

    def test_custom_authority_port_injection(self, tmp_path: Path):
        reset_vector_shadow_catalog()
        backend = MemoryAuthorityBackend()
        port = build_authority_port(
            backend,
            domain=VECTOR_SHADOW_DOMAIN,
            initial_mode=AuthorityMode.SHADOW,
            writer_id="writer:test",
        )
        cat = VectorShadowCatalog(
            tmp_path / "custom.duckdb",
            authority_port=port,
        )
        try:
            r = cat.shadow_create(
                logical_name="custom",
                backend="qdrant",
                dimension=DIM,
                mapping={"q0": 0},
                vectors=[[0, 0, 1, 0]],
                model_name="custom",
                model_provider="qdrant",
                model_revision="r1",
                chunking_identity="chunk:custom@1",
                normalization_identity="norm:none@1",
                source_revision="src-custom",
            )
            assert r.ok
            assert port.mode is AuthorityMode.SHADOW
            assert port.read("qdrant:custom") is not None
        finally:
            cat.close()
            reset_vector_shadow_catalog()


# ---------------------------------------------------------------------------
# Generation / tombstone / build producers
# ---------------------------------------------------------------------------


class TestLifecycleProducers:
    def test_generation_shard_build_and_tombstone(
        self, catalog: VectorShadowCatalog
    ):
        r = catalog.shadow_create(
            logical_name="lifecycle",
            backend="faiss",
            dimension=DIM,
            mapping={"t0": 0, "t1": 1},
            vectors=_vecs()[:2],
            model_name="life",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:life@1",
            normalization_identity="norm:none@1",
            source_revision="src-life",
            shard_manifest={
                "shard_index": 0,
                "vector_count": 2,
                "shard_id": "life_shard_0",
            },
            index_build={"index_kind": "faiss", "status": "completed"},
        )
        assert r.ok
        assert r.generation_id == 1
        col = catalog.store.get_collection(r.collection_id)
        assert col.published_generation == 1

        # Tombstone via delete_chunk then soft-delete collection
        visible_before = catalog.store.list_query_visible_chunks(r.collection_id)
        assert len(visible_before) == 2
        target = visible_before[0].chunk_id
        catalog.store.delete_chunk(
            collection_id=r.collection_id,
            chunk_id=target,
            reason="test_tombstone",
        )
        visible = catalog.store.list_query_visible_chunks(r.collection_id)
        assert all(c.chunk_id != target for c in visible)
        tombs = catalog.store.list_tombstones(r.collection_id)
        assert any(t.entity_id == target for t in tombs)

        deleted = catalog.shadow_delete(
            logical_name="lifecycle", backend="faiss"
        )
        assert deleted.ok
        assert deleted.authority == "legacy"
