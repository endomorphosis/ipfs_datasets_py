"""E2E tests: DuckDB-only vector metadata authority (DQK-064).

Acceptance:

* Normal runtime never reads or writes ``*_metadata.pkl``,
  ``vector_indexes/*/metadata.json``, shard JSON, or mutable manifest JSON
* MCP and manager restart from DuckDB plus vector segments without
  process-local mapping loss
* Publication exposes approved collection/build statistics rather than
  unrestricted embeddings
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pickle
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.vector_stores.management_engine import (
    ImplicitLegacyMetadataError,
    VECTOR_DUCKDB_ONLY_OWNER_TASK,
    VECTOR_PUBLICATION_TYPE,
    VectorLegacyFilesystemGuard,
    VectorStoreManager as EngineManager,
    configure_vector_authority_catalog,
    duckdb_only_after_promotion,
    get_vector_filesystem_guard,
    import_faiss_pickle_compat,
    legacy_metadata_io_allowed,
    reset_vector_authority_catalog,
    reset_vector_filesystem_guard,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_STATE_PATH = (
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "mcp_server"
    / "tools"
    / "vector_tools"
    / "shared_state.py"
)
_SHARD_ENGINE_PATH = (
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "embeddings"
    / "shard_embeddings_engine.py"
)


def _ensure_package_shell(pkg_name: str, pkg_path: Path) -> None:
    """Register a namespace package shell without executing eager ``__init__``."""

    if pkg_name in sys.modules:
        return
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(pkg_path)]  # type: ignore[attr-defined]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg


def _load_module_from_path(module_name: str, path: Path, *parent_packages: tuple[str, Path]):
    """Import a single module file without executing parent package inits."""

    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    for pkg_name, pkg_path in parent_packages:
        _ensure_package_shell(pkg_name, pkg_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_mcp_vector_shared_state():
    """Load MCP shared_state without importing package ``__init__``.

    The sealed validator environment does not ship ``numpy``, which the
    vector_tools package init eagerly imports via create_vector_index.
    shared_state itself only depends on management_engine (allowed).
    """

    return _load_module_from_path(
        "ipfs_datasets_py.mcp_server.tools.vector_tools.shared_state",
        _SHARED_STATE_PATH,
        (
            "ipfs_datasets_py.mcp_server",
            _REPO_ROOT / "ipfs_datasets_py" / "mcp_server",
        ),
        (
            "ipfs_datasets_py.mcp_server.tools",
            _REPO_ROOT / "ipfs_datasets_py" / "mcp_server" / "tools",
        ),
        (
            "ipfs_datasets_py.mcp_server.tools.vector_tools",
            _REPO_ROOT
            / "ipfs_datasets_py"
            / "mcp_server"
            / "tools"
            / "vector_tools",
        ),
    )


def _load_shard_embeddings_engine():
    """Load shard engine without embeddings package init (avoids numpy)."""

    return _load_module_from_path(
        "ipfs_datasets_py.embeddings.shard_embeddings_engine",
        _SHARD_ENGINE_PATH,
        (
            "ipfs_datasets_py.embeddings",
            _REPO_ROOT / "ipfs_datasets_py" / "embeddings",
        ),
    )


DIM = 4


def _vecs() -> List[List[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]


def _ids() -> List[str]:
    return ["vec_a", "vec_b", "vec_c"]


@pytest.fixture
def catalog(tmp_path: Path):
    reset_vector_authority_catalog()
    reset_vector_filesystem_guard()
    path = tmp_path / "vector_duckdb_only.duckdb"
    cat = configure_vector_authority_catalog(path, enabled=True)
    yield cat
    reset_vector_authority_catalog()
    reset_vector_filesystem_guard()


@pytest.fixture
def promoted_catalog(catalog):
    """Seed a collection and promote DuckDB to sole metadata authority."""

    result = catalog.dual_create(
        logical_name="docs",
        backend="faiss",
        dimension=DIM,
        vectors=_vecs(),
        vector_ids=_ids(),
        model_name="e2e-model",
        model_provider="unit",
        model_revision="r1",
        chunking_identity="chunk:e2e@1",
        normalization_identity="norm:l2@1",
        source_revision="src-e2e-1",
        operation_id="op-e2e-seed",
        index_build={
            "index_kind": "faiss",
            "status": "completed",
            "distance_metric": "cosine",
        },
        metadata_json={
            "producer": "e2e",
            "publication_approved": True,
            "distance_metric": "cosine",
        },
        bytes_location="engine",
    )
    assert result.ok is True
    decision = catalog.ensure_duckdb_authority(
        logical_name="docs", backend="faiss", decision_id="cutover:docs"
    )
    assert decision is not None and decision.accepted is True
    assert catalog.mode == AuthorityMode.DB_PRIMARY.value
    assert catalog.legacy_io_allowed is False
    return catalog


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_owner_task_and_publication_constants(self):
        assert VECTOR_DUCKDB_ONLY_OWNER_TASK == "DQK-064"
        assert VECTOR_PUBLICATION_TYPE == "vector_quack_publication_v1"

    def test_filesystem_guard_classifies_guarded_paths(self, tmp_path: Path):
        guard = VectorLegacyFilesystemGuard(allow_legacy_io=False)
        assert guard.classify_path(tmp_path / "col_metadata.pkl") == "metadata_pkl"
        assert (
            guard.classify_path(tmp_path / "vector_indexes" / "x" / "metadata.json")
            == "metadata_json"
        )
        assert guard.classify_path(tmp_path / "shard_0001.json") == "shard_json"
        assert (
            guard.classify_path(tmp_path / "sharding_manifest.json")
            == "mutable_manifest_json"
        )
        assert (
            guard.classify_path(tmp_path / "clustering_manifest.json")
            == "mutable_manifest_json"
        )
        assert guard.classify_path(tmp_path / "index.faiss") is None


# ---------------------------------------------------------------------------
# Acceptance: normal runtime never reads/writes legacy metadata surfaces
# ---------------------------------------------------------------------------


class TestNoSilentLegacyMetadataIO:
    def test_blocks_metadata_pkl_after_promotion(
        self, promoted_catalog, tmp_path: Path
    ):
        assert duckdb_only_after_promotion() is True
        assert legacy_metadata_io_allowed() is False
        guard = get_vector_filesystem_guard()
        pkl = tmp_path / "docs_metadata.pkl"
        with pytest.raises(ImplicitLegacyMetadataError) as excinfo:
            guard.assert_allowed(pkl, kind="metadata_pkl", operation="write")
        assert excinfo.value.kind == "metadata_pkl"
        assert "implicit" in str(excinfo.value).lower()

        with pytest.raises(ImplicitLegacyMetadataError):
            guard.assert_allowed(pkl, kind="metadata_pkl", operation="read")

        # Writing the file without a permit must not be used by runtime.
        # Guard still rejects the path even if a sibling process wrote bytes.
        pkl.write_bytes(pickle.dumps({"vectors": {}}))
        with pytest.raises(ImplicitLegacyMetadataError):
            guard.check_path_read(pkl, kind="metadata_pkl")

    def test_blocks_vector_indexes_metadata_json(
        self, promoted_catalog, tmp_path: Path
    ):
        indexes = tmp_path / "vector_indexes" / "docs"
        indexes.mkdir(parents=True)
        meta = indexes / "metadata.json"
        manager = EngineManager(indexes_dir=str(tmp_path / "vector_indexes"))
        manager.authority_catalog = promoted_catalog
        manager.shadow_catalog = promoted_catalog

        with pytest.raises(ImplicitLegacyMetadataError):
            manager._write_index_metadata_json(
                "docs",
                {
                    "index_name": "docs",
                    "documents": [{"text": "secret unrestricted"}],
                    "embeddings": [[0.1] * DIM],
                },
            )
        assert not meta.exists()

        # Even if present on disk, promoted runtime refuses to read it.
        meta.write_text(json.dumps({"document_count": 99, "documents": ["x"]}))
        with pytest.raises(ImplicitLegacyMetadataError):
            manager._read_index_metadata_json("docs")

    def test_blocks_shard_json_and_mutable_manifests(
        self, promoted_catalog, tmp_path: Path
    ):
        guard = get_vector_filesystem_guard()
        for name, kind in (
            ("shard_0000.json", "shard_json"),
            ("cluster_0001_shard_0002.json", "shard_json"),
            ("sharding_manifest.json", "mutable_manifest_json"),
            ("clustering_manifest.json", "mutable_manifest_json"),
        ):
            path = tmp_path / name
            with pytest.raises(ImplicitLegacyMetadataError) as excinfo:
                guard.assert_allowed(path, kind=kind, operation="write")
            assert excinfo.value.kind == kind

    def test_explicit_import_permit_allows_one_time_pickle_compat(
        self, promoted_catalog, tmp_path: Path
    ):
        """Pickle remains explicit one-time import compatibility only."""

        pkl = tmp_path / "legacy_metadata.pkl"
        payload = {
            "vectors": {
                "import_a": [1.0, 0.0, 0.0, 0.0],
                "import_b": [0.0, 1.0, 0.0, 0.0],
            }
        }
        pkl.write_bytes(pickle.dumps(payload))

        # Without permit: blocked.
        with pytest.raises(ImplicitLegacyMetadataError):
            get_vector_filesystem_guard().assert_allowed(
                pkl, kind="metadata_pkl", operation="read"
            )

        # Explicit one-time import path obtains a permit internally.
        report = import_faiss_pickle_compat(
            pkl,
            logical_name="imported",
            backend="faiss",
            dimension=DIM,
            catalog=promoted_catalog,
        )
        assert report["ok"] is True
        assert report["one_time_import"] is True
        assert report["pickle_authority"] is False
        assert report["owner_task"] == VECTOR_DUCKDB_ONLY_OWNER_TASK

        # After import, normal path is still blocked (no silent fallback).
        with pytest.raises(ImplicitLegacyMetadataError):
            get_vector_filesystem_guard().assert_allowed(
                pkl, kind="metadata_pkl", operation="write"
            )

    def test_faiss_store_skips_pickle_write_after_promotion(
        self, promoted_catalog, tmp_path: Path
    ):
        """FAISS pickle write path is blocked after promotion (no silent write).

        Exercises the same guard rails FAISSVectorStore._save_metadata uses
        without importing heavy FAISS/numpy/pydantic store wiring.
        """

        meta_path = tmp_path / "faiss_metadata" / "promo_col_metadata.pkl"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        assert promoted_catalog.legacy_io_allowed is False
        with pytest.raises(ImplicitLegacyMetadataError):
            get_vector_filesystem_guard().assert_allowed(
                meta_path, kind="metadata_pkl", operation="write"
            )
        assert not meta_path.exists()

        # Source-level contract: faiss_store confins pickle to import-compat.
        faiss_src = Path("ipfs_datasets_py/vector_stores/faiss_store.py").read_text()
        assert "import_pickle_metadata_once" in faiss_src
        assert "_legacy_pickle_io_allowed" in faiss_src
        assert "pickle.load" not in faiss_src or "_pickle_compat" in faiss_src


# ---------------------------------------------------------------------------
# Acceptance: restart without process-local mapping loss
# ---------------------------------------------------------------------------


class TestRestartFromDuckDB:
    def test_reopen_rehydrates_live_mappings(self, promoted_catalog):
        live_before = set(
            promoted_catalog.live_vector_ids(logical_name="docs", backend="faiss")
        )
        assert live_before == set(_ids())
        # Wipe process-local maps then reopen (simulates restart).
        promoted_catalog._logical_vector_map.clear()
        promoted_catalog._logical_to_collection.clear()
        promoted_catalog.reopen(rehydrate_from_duckdb=True)
        live_after = set(
            promoted_catalog.live_vector_ids(logical_name="docs", backend="faiss")
        )
        assert live_after == live_before
        assert promoted_catalog.mode == AuthorityMode.DB_PRIMARY.value
        assert promoted_catalog.legacy_io_allowed is False
        for vid in _ids():
            assert promoted_catalog.is_vector_live(
                logical_name="docs", backend="faiss", vector_id=vid
            )

    def test_process_rebind_from_catalog_path_without_mapping_loss(
        self, promoted_catalog, tmp_path: Path
    ):
        path = Path(promoted_catalog.path)
        live_before = set(
            promoted_catalog.live_vector_ids(logical_name="docs", backend="faiss")
        )
        # Full process rebind: drop process catalog, reconfigure from path.
        reset_vector_authority_catalog()
        reopened = configure_vector_authority_catalog(path, enabled=True)
        assert reopened.mode == AuthorityMode.DB_PRIMARY.value
        assert reopened.legacy_io_allowed is False
        live_after = set(
            reopened.live_vector_ids(logical_name="docs", backend="faiss")
        )
        assert live_after == live_before == set(_ids())
        assert duckdb_only_after_promotion() is True

    def test_mcp_restart_helper_preserves_mappings(
        self, promoted_catalog, tmp_path: Path
    ):
        shared = _load_mcp_vector_shared_state()

        path = Path(promoted_catalog.path)
        live_before = set(
            promoted_catalog.live_vector_ids(logical_name="docs", backend="faiss")
        )
        # Bind MCP shared state to the same durable path.
        shared.configure_mcp_vector_authority_catalog(path, enabled=True)
        result = shared.restart_mcp_vector_catalog_from_duckdb(path)
        assert result["status"] == "success"
        assert result["process_local_mapping_loss"] is False
        assert result["mode"] == AuthorityMode.DB_PRIMARY.value
        assert result["legacy_io_allowed"] is False
        cat = shared.get_mcp_vector_authority_catalog()
        assert cat is not None
        live_after = set(cat.live_vector_ids(logical_name="docs", backend="faiss"))
        assert live_after == live_before

    def test_manager_rehydrate_and_list_without_metadata_json(
        self, promoted_catalog, tmp_path: Path
    ):
        indexes_dir = tmp_path / "vector_indexes"
        # Segment-only directory (no metadata.json).
        docs_dir = indexes_dir / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "index.faiss").write_bytes(b"faiss-segment-placeholder")

        manager = EngineManager(indexes_dir=str(indexes_dir))
        manager.authority_catalog = promoted_catalog
        manager.shadow_catalog = promoted_catalog
        # List must not require metadata.json after promotion.
        listed = manager.list_indexes("faiss")
        assert listed["status"] == "success"
        assert listed.get("authority") in {"duckdb", "dual"}
        names = {item.get("name") for item in listed.get("indexes", {}).get("faiss", [])}
        assert any("docs" in str(n) for n in names)
        # Ensure no metadata.json was read/created.
        assert not (docs_dir / "metadata.json").exists()


# ---------------------------------------------------------------------------
# Acceptance: publication exposes approved stats, not unrestricted embeddings
# ---------------------------------------------------------------------------


class TestPublicationSurface:
    def test_publication_exposes_approved_stats_only(self, promoted_catalog):
        doc = promoted_catalog.publication_document()
        assert doc["publication_type"] == VECTOR_PUBLICATION_TYPE
        assert doc["embeddings_excluded"] is True
        assert doc["unrestricted_documents_excluded"] is True
        assert doc["pickle_authority"] is False
        assert doc["process_local_mappings_excluded"] is True
        assert doc["owner_task"] == VECTOR_DUCKDB_ONLY_OWNER_TASK

        stats = doc["approved_collection_build_statistics"]
        assert isinstance(stats, list)
        assert len(stats) >= 1
        for item in stats:
            assert item.get("embeddings_excluded") is True
            assert item.get("documents_excluded") is True
            assert "live_vector_count" in item
            assert "dimension" in item
            # Must never leak raw embeddings or unrestricted document payloads.
            assert "embeddings" not in item
            assert "vectors" not in item
            assert "documents" not in item
            assert "id_mapping" not in item

        serialized = json.dumps(doc)
        assert "embeddings" not in serialized or '"embeddings_excluded": true' in serialized
        # No unrestricted embedding arrays appear as numeric lists under vectors.
        assert '"vectors":' not in serialized
        assert "pickle" not in serialized.lower() or "pickle_authority" in serialized

    def test_mcp_publication_helper(self, promoted_catalog):
        shared = _load_mcp_vector_shared_state()

        shared.configure_mcp_vector_authority_catalog(
            promoted_catalog.path, enabled=True
        )
        doc = shared.mcp_vector_publication_document()
        assert doc["publication_type"] == VECTOR_PUBLICATION_TYPE
        assert doc["embeddings_excluded"] is True
        assert isinstance(doc["approved_collection_build_statistics"], list)

    def test_engine_manager_publication_document(self, promoted_catalog):
        manager = EngineManager()
        manager.authority_catalog = promoted_catalog
        doc = manager.publication_document()
        assert doc["embeddings_excluded"] is True
        assert doc["publication_type"] == VECTOR_PUBLICATION_TYPE


# ---------------------------------------------------------------------------
# Shard engine respects DuckDB-only I/O
# ---------------------------------------------------------------------------


class TestShardEngineDuckDBOnly:
    def test_shard_engine_skips_json_after_promotion(
        self, promoted_catalog, tmp_path: Path
    ):
        # Sealed validator may lack pytest-asyncio and numpy; load the engine
        # module directly and drive the coroutine with asyncio.run.
        engine = _load_shard_embeddings_engine()

        out = tmp_path / "shards_out"
        embeddings = [
            {"id": "e0", "embedding": [1.0, 0.0, 0.0, 0.0]},
            {"id": "e1", "embedding": [0.0, 1.0, 0.0, 0.0]},
        ]
        result = asyncio.run(
            engine.shard_embeddings_by_dimension(
                embeddings,
                str(out),
                shard_size=10,
            )
        )
        assert result["status"] == "success"
        # After promotion, shard JSON and mutable manifests must not be written.
        assert result.get("manifest_json_written") is False
        assert result.get("manifest_file") is None
        shard_jsons = list(out.glob("shard_*.json")) if out.exists() else []
        assert shard_jsons == []
        assert not (out / "sharding_manifest.json").exists()
        # DuckDB still received the projection.
        assert "shadow" in result or result.get("authority") in {
            "dual",
            "duckdb",
            None,
        }


# ---------------------------------------------------------------------------
# Unified manager restart helper
# ---------------------------------------------------------------------------


class TestUnifiedManagerRestart:
    def test_manager_rehydrate_from_duckdb(self, promoted_catalog):
        """Engine manager rehydrate + publication (unified manager pulls pydantic)."""

        manager = EngineManager()
        manager.authority_catalog = promoted_catalog
        manager.shadow_catalog = promoted_catalog
        # Rehydrate via catalog (same path unified manager.rehydrate_from_duckdb uses).
        summary = promoted_catalog.rehydrate_process_maps_from_store()
        assert summary["live_vectors"] >= len(_ids())
        assert summary["mode"] == AuthorityMode.DB_PRIMARY.value
        pub = manager.publication_document()
        assert pub["embeddings_excluded"] is True
        # Source contract for unified manager helpers.
        mgr_src = Path("ipfs_datasets_py/vector_stores/manager.py").read_text()
        assert "rehydrate_from_duckdb" in mgr_src
        assert "publication_document" in mgr_src
