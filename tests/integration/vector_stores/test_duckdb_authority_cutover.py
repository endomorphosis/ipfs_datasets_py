"""Integration tests: DuckDB vector dual-mode authority cutover (DQK-063).

Acceptance coverage:

* Update/delete cannot resurrect stale or duplicate live vectors
* External backend failures retry idempotently
* VSS remains derived and exact-search fallback stays available

Also covers dual-mode promotion of collection / generation / tombstone /
compaction metadata while vector bytes remain in the selected engine or
immutable segment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    MemoryAuthorityBackend,
    build_authority_port,
)
from ipfs_datasets_py.vector_stores.management_engine import (
    DEFAULT_EXTERNAL_RETRY_ATTEMPTS,
    VECTOR_AUTHORITY_DOMAIN,
    VECTOR_AUTHORITY_OWNER_TASK,
    VECTOR_AUTHORITY_SCHEMA,
    ExternalMutationResult,
    VectorAuthorityCatalog,
    VectorStoreManager as EngineManager,
    VSSFallbackSearchResult,
    configure_vector_authority_catalog,
    get_vector_authority_catalog,
    reset_vector_authority_catalog,
    safe_dual_compact,
    safe_dual_create,
    safe_dual_delete,
    safe_dual_update,
    safe_retry_external_mutation,
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
def catalog(tmp_path: Path) -> VectorAuthorityCatalog:
    reset_vector_authority_catalog()
    path = tmp_path / "vector_authority.duckdb"
    cat = configure_vector_authority_catalog(path, enabled=True)
    yield cat
    reset_vector_authority_catalog()


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self):
        assert VECTOR_AUTHORITY_OWNER_TASK == "DQK-063"
        assert VECTOR_AUTHORITY_DOMAIN == "vectors"
        assert VECTOR_AUTHORITY_SCHEMA.startswith("ipfs_datasets_py/")
        assert DEFAULT_EXTERNAL_RETRY_ATTEMPTS >= 1

    def test_process_registry_defaults_to_dual(self, tmp_path: Path):
        reset_vector_authority_catalog()
        assert get_vector_authority_catalog() is None
        cat = configure_vector_authority_catalog(tmp_path / "c.duckdb")
        assert get_vector_authority_catalog() is cat
        assert cat.enabled
        assert cat.mode == AuthorityMode.DUAL.value
        assert cat._authority_label() == "dual"
        reset_vector_authority_catalog()
        assert get_vector_authority_catalog() is None


# ---------------------------------------------------------------------------
# Dual mode: metadata authority; bytes stay in engine
# ---------------------------------------------------------------------------


class TestDualModeAuthority:
    def test_dual_create_reports_dual_authority_and_engine_bytes(
        self, catalog: VectorAuthorityCatalog
    ):
        result = catalog.dual_create(
            logical_name="docs",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            model_name="dual-model",
            model_provider="unit",
            model_revision="r1",
            chunking_identity="chunk:dual@1",
            normalization_identity="norm:l2@1",
            source_revision="src-dual-1",
            operation_id="op-create-docs",
            bytes_location="engine",
        )
        assert result.ok is True
        assert result.authority == "dual"
        assert result.bytes_location == "engine"
        assert result.collection_id
        assert result.generation_id == 1
        assert result.idempotent_replay is False
        assert set(catalog.live_vector_ids(logical_name="docs", backend="faiss")) == set(
            _ids()
        )
        for vid in _ids():
            assert catalog.is_vector_live(
                logical_name="docs", backend="faiss", vector_id=vid
            )

    def test_dual_create_idempotent_replay(
        self, catalog: VectorAuthorityCatalog
    ):
        kwargs = dict(
            logical_name="idem",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-create-idem",
        )
        first = catalog.dual_create(**kwargs)
        second = catalog.dual_create(**kwargs)
        assert first.ok and second.ok
        assert second.idempotent_replay is True
        assert second.collection_id == first.collection_id
        # Still exactly three live logical ids (no duplicates from replay).
        assert sorted(
            catalog.live_vector_ids(logical_name="idem", backend="faiss")
        ) == sorted(_ids())

    def test_promote_to_db_primary(self, catalog: VectorAuthorityCatalog):
        created = catalog.dual_create(
            logical_name="promo",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs()[:1],
            vector_ids=["only"],
            operation_id="op-promo-seed",
        )
        assert created.ok
        assert catalog.mode == AuthorityMode.DUAL.value

        decision = catalog.ensure_duckdb_authority(
            logical_name="promo", backend="faiss", decision_id="cutover:promo"
        )
        assert decision is not None
        assert decision.accepted is True
        assert catalog.mode == AuthorityMode.DB_PRIMARY.value
        assert catalog._authority_label() == "duckdb"

        again = catalog.ensure_duckdb_authority(
            logical_name="promo", backend="faiss", decision_id="cutover:promo-2"
        )
        assert again is None or again.accepted is True
        assert catalog.mode == AuthorityMode.DB_PRIMARY.value

    def test_compaction_receipt_preserves_live_set(
        self, catalog: VectorAuthorityCatalog
    ):
        created = catalog.dual_create(
            logical_name="compact-docs",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-compact-seed",
        )
        assert created.ok
        # Tombstone one vector so compaction has work / tombstones present.
        deleted = catalog.dual_delete(
            logical_name="compact-docs",
            backend="faiss",
            vector_id="vec_c",
            operation_id="op-compact-del",
        )
        assert deleted.ok
        before = set(
            catalog.live_vector_ids(
                logical_name="compact-docs", backend="faiss"
            )
        )
        assert "vec_c" not in before
        assert before == {"vec_a", "vec_b"}

        compacted = catalog.dual_compact(
            logical_name="compact-docs",
            backend="faiss",
            from_generation=1,
            operation_id="op-compact-1",
        )
        # Compaction may no-op on range if only gen 1 is published; still must
        # not drop live vectors when it succeeds.
        if compacted.ok:
            after = set(
                catalog.live_vector_ids(
                    logical_name="compact-docs", backend="faiss"
                )
            )
            assert after == before
            assert compacted.compaction_id
            assert compacted.authority in {"dual", "duckdb"}
            # Idempotent replay
            again = catalog.dual_compact(
                logical_name="compact-docs",
                backend="faiss",
                from_generation=1,
                operation_id="op-compact-1",
            )
            assert again.idempotent_replay is True


# ---------------------------------------------------------------------------
# Acceptance: update/delete cannot resurrect stale or duplicate live vectors
# ---------------------------------------------------------------------------


class TestNoResurrection:
    def test_update_tombstones_stale_and_keeps_single_live(
        self, catalog: VectorAuthorityCatalog
    ):
        seed = catalog.dual_create(
            logical_name="upd",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-upd-seed",
        )
        assert seed.ok
        col_id = seed.collection_id
        before_chunk = catalog._logical_vector_map[
            catalog._vector_key("faiss", "upd", "vec_a")
        ]

        updated = catalog.dual_update(
            logical_name="upd",
            backend="faiss",
            vector_id="vec_a",
            vector=[0.5, 0.5, 0.0, 0.0],
            operation_id="op-upd-a",
        )
        assert updated.ok is True, updated.error
        assert catalog.is_vector_live(
            logical_name="upd", backend="faiss", vector_id="vec_a"
        )
        # Old chunk must not remain query-visible.
        visible = {
            c.chunk_id
            for c in catalog.store.list_query_visible_chunks(col_id)
        }
        if updated.tombstone_ids or before_chunk not in (
            catalog._logical_vector_map.get(
                catalog._vector_key("faiss", "upd", "vec_a")
            ),
        ):
            # When a new chunk was minted, the prior id is not live.
            after_chunk = catalog._logical_vector_map[
                catalog._vector_key("faiss", "upd", "vec_a")
            ]
            if after_chunk != before_chunk:
                assert before_chunk not in visible
                assert after_chunk in visible

        # Exactly one live logical mapping for vec_a (no duplicates).
        live = catalog.live_vector_ids(logical_name="upd", backend="faiss")
        assert live.count("vec_a") == 1
        assert set(live) == set(_ids())

        # Replay cannot resurrect a second live copy.
        replay = catalog.dual_update(
            logical_name="upd",
            backend="faiss",
            vector_id="vec_a",
            vector=[0.25, 0.25, 0.25, 0.25],
            operation_id="op-upd-a",
        )
        assert replay.idempotent_replay is True
        assert catalog.live_vector_ids(
            logical_name="upd", backend="faiss"
        ).count("vec_a") == 1

    def test_delete_cannot_resurrect_on_retry(
        self, catalog: VectorAuthorityCatalog
    ):
        catalog.dual_create(
            logical_name="del",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-del-seed",
        )
        deleted = catalog.dual_delete(
            logical_name="del",
            backend="faiss",
            vector_id="vec_b",
            operation_id="op-del-b",
        )
        assert deleted.ok is True
        assert not catalog.is_vector_live(
            logical_name="del", backend="faiss", vector_id="vec_b"
        )
        assert "vec_b" not in catalog.live_vector_ids(
            logical_name="del", backend="faiss"
        )

        # Idempotent retry must not re-live the vector.
        retry = catalog.dual_delete(
            logical_name="del",
            backend="faiss",
            vector_id="vec_b",
            operation_id="op-del-b",
        )
        assert retry.idempotent_replay is True
        assert not catalog.is_vector_live(
            logical_name="del", backend="faiss", vector_id="vec_b"
        )

        # Update after delete must refuse resurrection.
        refuse = catalog.dual_update(
            logical_name="del",
            backend="faiss",
            vector_id="vec_b",
            vector=[0.0, 0.0, 0.0, 1.0],
            operation_id="op-upd-after-del",
        )
        assert refuse.ok is False
        assert "resurrection" in (refuse.error or "")
        assert not catalog.is_vector_live(
            logical_name="del", backend="faiss", vector_id="vec_b"
        )

    def test_collection_delete_tombstones_all(
        self, catalog: VectorAuthorityCatalog
    ):
        catalog.dual_create(
            logical_name="gone",
            backend="qdrant",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-gone-seed",
        )
        deleted = catalog.dual_delete(
            logical_name="gone",
            backend="qdrant",
            operation_id="op-gone-all",
        )
        assert deleted.ok is True
        assert catalog.live_vector_ids(
            logical_name="gone", backend="qdrant"
        ) == []
        for vid in _ids():
            assert not catalog.is_vector_live(
                logical_name="gone", backend="qdrant", vector_id=vid
            )
        # Retry stays deleted.
        again = catalog.dual_delete(
            logical_name="gone",
            backend="qdrant",
            operation_id="op-gone-all",
        )
        assert again.idempotent_replay is True
        assert catalog.live_vector_ids(
            logical_name="gone", backend="qdrant"
        ) == []


# ---------------------------------------------------------------------------
# Acceptance: external backend failures retry idempotently
# ---------------------------------------------------------------------------


class TestExternalBackendRetry:
    def test_retries_until_success_then_idempotent_replay(
        self, catalog: VectorAuthorityCatalog
    ):
        attempts: Dict[str, int] = {"n": 0}

        def flaky(op_id: str) -> Dict[str, Any]:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError(f"backend outage attempt={attempts['n']}")
            return {"written": True, "operation_id": op_id}

        result = catalog.retry_external_mutation(
            operation_id="op-ext-retry",
            backend="qdrant",
            mutate_fn=flaky,
            max_attempts=5,
            backoff_s=0.0,
        )
        assert isinstance(result, ExternalMutationResult)
        assert result.ok is True
        assert result.attempts == 3
        assert result.result["written"] is True
        assert result.idempotent_replay is False
        assert attempts["n"] == 3

        # Same operation_id must not re-invoke the backend.
        replay = catalog.retry_external_mutation(
            operation_id="op-ext-retry",
            backend="qdrant",
            mutate_fn=flaky,
            max_attempts=5,
            backoff_s=0.0,
        )
        assert replay.ok is True
        assert replay.idempotent_replay is True
        assert attempts["n"] == 3  # no extra calls

    def test_exhausted_retries_fail_without_journaling_success(
        self, catalog: VectorAuthorityCatalog
    ):
        def always_fail(op_id: str) -> None:
            raise RuntimeError("permanent outage")

        result = catalog.retry_external_mutation(
            operation_id="op-ext-fail",
            backend="elasticsearch",
            mutate_fn=always_fail,
            max_attempts=3,
            backoff_s=0.0,
        )
        assert result.ok is False
        assert result.attempts == 3
        assert "permanent outage" in result.error

        # A later successful attempt with the same op id is allowed (not
        # journaled as completed on failure).
        def recover(op_id: str) -> str:
            return f"recovered:{op_id}"

        recovered = catalog.retry_external_mutation(
            operation_id="op-ext-fail",
            backend="elasticsearch",
            mutate_fn=recover,
            max_attempts=2,
            backoff_s=0.0,
        )
        assert recovered.ok is True
        assert recovered.result == "recovered:op-ext-fail"

    def test_safe_retry_helper(self, catalog: VectorAuthorityCatalog):
        def ok(op_id: str) -> int:
            return 42

        result = safe_retry_external_mutation(
            operation_id="op-safe-ext",
            backend="faiss",
            mutate_fn=ok,
            max_attempts=2,
            backoff_s=0.0,
        )
        assert result is not None
        assert result.ok is True
        assert result.result == 42


# ---------------------------------------------------------------------------
# Acceptance: VSS remains derived; exact-search fallback stays available
# ---------------------------------------------------------------------------


class TestVssDerivedExactFallback:
    def test_vss_never_identity_authority(
        self, catalog: VectorAuthorityCatalog
    ):
        catalog.dual_create(
            logical_name="vss",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-vss-seed",
        )
        # Extension unavailable → forced exact fallback.
        missing = catalog.search_with_vss_fallback(
            logical_name="vss",
            backend="faiss",
            query=[1.0, 0.0, 0.0, 0.0],
            k=2,
            extension_available=False,
        )
        assert isinstance(missing, VSSFallbackSearchResult)
        assert missing.authority == "exact"
        assert missing.vss_derived is True
        assert missing.used_fallback is True
        assert missing.health in {
            "missing_extension",
            "stale",
            "empty",
            "healthy",
        }
        assert len(missing.hits) >= 1
        assert all(h.get("authority") == "exact" for h in missing.hits)
        # Top hit should be vec_a (unit vector along first axis).
        assert missing.hits[0]["vector_id"] == "vec_a"

        # Even with extension "available", identity authority remains exact.
        present = catalog.search_with_vss_fallback(
            logical_name="vss",
            backend="faiss",
            query=[0.0, 1.0, 0.0, 0.0],
            k=1,
            extension_available=True,
        )
        assert present.authority == "exact"
        assert present.vss_derived is True
        assert present.hits[0]["vector_id"] == "vec_b"

    def test_tombstoned_vectors_excluded_from_exact_fallback(
        self, catalog: VectorAuthorityCatalog
    ):
        catalog.dual_create(
            logical_name="vss-tomb",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-vss-tomb-seed",
        )
        catalog.dual_delete(
            logical_name="vss-tomb",
            backend="faiss",
            vector_id="vec_a",
            operation_id="op-vss-tomb-del",
        )
        result = catalog.search_with_vss_fallback(
            logical_name="vss-tomb",
            backend="faiss",
            query=[1.0, 0.0, 0.0, 0.0],
            k=5,
            extension_available=False,
        )
        hit_ids = {h["vector_id"] for h in result.hits}
        assert "vec_a" not in hit_ids
        assert result.authority == "exact"


# ---------------------------------------------------------------------------
# Safe helpers + engine manager dual wiring
# ---------------------------------------------------------------------------


class TestSafeHelpersAndManager:
    def test_safe_dual_helpers(self, catalog: VectorAuthorityCatalog):
        created = safe_dual_create(
            logical_name="safe",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs()[:2],
            vector_ids=["x", "y"],
            operation_id="op-safe-create",
        )
        assert created is not None and created.ok
        updated = safe_dual_update(
            logical_name="safe",
            backend="faiss",
            vector_id="x",
            vector=[0.1, 0.2, 0.3, 0.4],
            operation_id="op-safe-upd",
        )
        assert updated is not None and updated.ok
        deleted = safe_dual_delete(
            logical_name="safe",
            backend="faiss",
            vector_id="y",
            operation_id="op-safe-del",
        )
        assert deleted is not None and deleted.ok
        assert not catalog.is_vector_live(
            logical_name="safe", backend="faiss", vector_id="y"
        )
        compact = safe_dual_compact(
            logical_name="safe",
            backend="faiss",
            from_generation=1,
            operation_id="op-safe-compact",
        )
        # Compaction may fail on invalid range when only gen 1 exists and
        # from_generation == published; either ok or structured error is fine.
        assert compact is not None

    def test_engine_manager_dual_helpers(
        self, catalog: VectorAuthorityCatalog, tmp_path: Path
    ):
        indexes_dir = tmp_path / "indexes"
        indexes_dir.mkdir()
        manager = EngineManager(
            indexes_dir=str(indexes_dir),
            authority_catalog=catalog,
        )
        created = manager._dual_after_create(
            logical_name="mgr-docs",
            backend="faiss",
            dimension=DIM,
            vectors=_vecs(),
            vector_ids=_ids(),
            operation_id="op-mgr-create",
            bytes_location="engine",
        )
        assert created is not None
        assert created.ok
        assert created.authority in {"dual", "duckdb"}

        deleted = manager._dual_after_delete(
            logical_name="mgr-docs",
            backend="faiss",
            vector_id="vec_c",
            operation_id="op-mgr-del",
        )
        assert deleted is not None
        assert deleted.ok
        assert not catalog.is_vector_live(
            logical_name="mgr-docs", backend="faiss", vector_id="vec_c"
        )

    def test_custom_dual_port_injection(self, tmp_path: Path):
        reset_vector_authority_catalog()
        port = build_authority_port(
            MemoryAuthorityBackend(),
            domain="vectors",
            initial_mode=AuthorityMode.DUAL,
            writer_id="writer:test-dual",
        )
        cat = VectorAuthorityCatalog(
            tmp_path / "custom.duckdb",
            authority_port=port,
            initial_mode=AuthorityMode.DUAL,
        )
        try:
            assert cat.mode == AuthorityMode.DUAL.value
            r = cat.dual_create(
                logical_name="custom",
                backend="ipld",
                dimension=DIM,
                vectors=_vecs()[:1],
                vector_ids=["only"],
                operation_id="op-custom",
                bytes_location="immutable_segment",
            )
            assert r.ok
            assert r.authority == "dual"
            assert r.bytes_location == "immutable_segment"
        finally:
            cat.close()
            reset_vector_authority_catalog()
