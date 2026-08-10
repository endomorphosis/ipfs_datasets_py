"""Unit tests for FAISS metadata migration and shadow dual-path (DQK-023).

Acceptance coverage:

* Normal runtime never unpickles
* Every imported generation has a source digest and reject report
* External backend parity is measured before promotion

Also covers: vector/mapping validation, stale-duplicate quarantine, and
dual-read/write for FAISS, Qdrant, and Elasticsearch in shadow mode.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore, vector_digest
from ipfs_datasets_py.vector_stores.duckdb_migration import (
    ExternalBackend,
    PromotionBlockedError,
    ShadowMode,
    VectorMigrationError,
    VectorShadowAdapter,
    import_faiss_pickle_metadata,
    measure_external_parity,
    require_parity_for_promotion,
)


@pytest.fixture
def store(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    yield s
    s.close()


def _write_pickle(path: Path, payload: object) -> Path:
    path.write_bytes(pickle.dumps(payload))
    return path


# ---------------------------------------------------------------------------
# Acceptance: normal runtime never unpickles
# ---------------------------------------------------------------------------


def test_normal_runtime_never_unpickles(tmp_path: Path, store: ExactVectorStore) -> None:
    path = _write_pickle(tmp_path / "meta.pkl", {"vectors": {"a": [1.0, 0.0]}})
    with pytest.raises(VectorMigrationError, match="never unpickles"):
        import_faiss_pickle_metadata(
            path, store, collection_id="c", dimension=2, allow_unpickle=False
        )


def test_allow_unpickle_default_is_false(tmp_path: Path, store: ExactVectorStore) -> None:
    path = _write_pickle(tmp_path / "meta.pkl", {"vectors": {"a": [1.0, 0.0]}})
    with pytest.raises(VectorMigrationError, match="never unpickles"):
        import_faiss_pickle_metadata(path, store, collection_id="c", dimension=2)


# ---------------------------------------------------------------------------
# Acceptance: source digest + reject report per generation
# ---------------------------------------------------------------------------


def test_import_records_source_digest_and_rejects(
    tmp_path: Path, store: ExactVectorStore
) -> None:
    payload = {
        "vectors": {
            "a": [1.0, 0.0, 0.0],
            "b": [0.0, 1.0],  # bad dim
            "c": [0.0, 0.0, 1.0],
        }
    }
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report = import_faiss_pickle_metadata(
        path,
        store,
        collection_id="c",
        dimension=3,
        allow_unpickle=True,
        generation_id=2,
    )
    assert report.source_digest.startswith("sha256:")
    assert report.imported_count == 2
    assert report.generation_id == 2
    assert any(r.reason == "dimension mismatch" for r in report.rejected)
    as_dict = report.to_dict()
    assert as_dict["source_digest"] == report.source_digest
    assert as_dict["generation_id"] == 2
    assert as_dict["pickle_authority"] is False
    assert as_dict["authority"] == "duckdb"
    assert isinstance(as_dict["rejected"], list)
    assert store.count("c") == 2


def test_reject_non_finite_and_missing_values(
    tmp_path: Path, store: ExactVectorStore
) -> None:
    payload = {
        "vectors": {
            "ok": [1.0, 0.0],
            "nan": [float("nan"), 0.0],
            "missing": {"metadata": {"x": 1}},
            "nested": {"vector": [0.0, 1.0], "content": "hi"},
        }
    }
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=2, allow_unpickle=True
    )
    assert report.imported_count == 2
    reasons = {r.vector_id: r.reason for r in report.rejected}
    assert reasons["nan"] == "non-finite vector component"
    assert reasons["missing"] == "vector values missing"


# ---------------------------------------------------------------------------
# Validate mappings + quarantine stale duplicates
# ---------------------------------------------------------------------------


def test_faiss_id_mapping_validation(tmp_path: Path, store: ExactVectorStore) -> None:
    payload = {
        "vectors": {
            "a": [1.0, 0.0],
            "b": [0.0, 1.0],
        },
        "id_mapping": {"a": 0, "b": 1},
        "reverse_id_mapping": {0: "a", 1: "b"},
    }
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=2, allow_unpickle=True
    )
    assert report.mapping_validated is True
    assert report.imported_count == 2
    assert not any(r.reason == "id_mapping inconsistent" for r in report.rejected)


def test_faiss_id_mapping_inconsistency_reported(
    tmp_path: Path, store: ExactVectorStore
) -> None:
    payload = {
        "vectors": {"a": [1.0, 0.0]},
        "id_mapping": {"a": 0},
        "reverse_id_mapping": {0: "other"},
    }
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=2, allow_unpickle=True
    )
    assert any(r.reason == "id_mapping inconsistent" for r in report.rejected)


def test_quarantine_batch_duplicates(
    tmp_path: Path, store: ExactVectorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real pickle dicts cannot hold duplicate keys; inject a mapping that
    # yields the same vector_id twice to exercise batch quarantine.
    class DupMap(dict):
        def items(self):  # type: ignore[override]
            yield "a", [1.0, 0.0]
            yield "a", [0.5, 0.5]
            yield "b", [0.0, 1.0]

    path = tmp_path / "meta.pkl"
    path.write_bytes(b"synthetic-pickle-bytes")
    monkeypatch.setattr(
        "ipfs_datasets_py.vector_stores.duckdb_migration.pickle.loads",
        lambda _raw: {"vectors": DupMap()},
    )
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=2, allow_unpickle=True
    )
    assert "a" in report.quarantined_duplicates
    assert report.quarantine_reasons.get("a") == "batch_duplicate"
    assert report.imported_count == 2  # first a + b


def test_quarantine_content_duplicates(tmp_path: Path, store: ExactVectorStore) -> None:
    same = [1.0, 0.0, 0.0]
    payload = {"vectors": {"a": same, "b": list(same), "c": [0.0, 1.0, 0.0]}}
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert report.imported_count == 2
    assert "b" in report.quarantined_duplicates
    assert report.quarantine_reasons["b"] == "content_duplicate"


def test_quarantine_stale_duplicates_on_reimport(
    tmp_path: Path, store: ExactVectorStore
) -> None:
    payload = {"vectors": {"a": [1.0, 0.0, 0.0], "c": [0.0, 0.0, 1.0]}}
    path = _write_pickle(tmp_path / "meta.pkl", payload)
    report1 = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert report1.imported_count == 2

    payload2 = {
        "vectors": {
            "a": [1.0, 0.0, 0.0],  # stale re-import
            "d": [0.1, 0.2, 0.3],
        }
    }
    path2 = _write_pickle(tmp_path / "meta2.pkl", payload2)
    report2 = import_faiss_pickle_metadata(
        path2, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert "a" in report2.quarantined_duplicates
    assert report2.quarantine_reasons["a"] == "stale_duplicate"
    assert report2.imported_count == 1
    assert report2.source_digest.startswith("sha256:")
    assert report2.source_digest != report1.source_digest


# ---------------------------------------------------------------------------
# Acceptance: external backend parity before promotion
# ---------------------------------------------------------------------------


def test_external_parity_before_promotion(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    store.upsert_vector("c", "a", [1.0, 0.0])
    store.upsert_vector("c", "b", [0.0, 1.0])
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
    assert parity.to_dict()["backend"] == "faiss"

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


def test_require_parity_blocks_promotion(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    store.upsert_vector("c", "a", [1.0, 0.0])
    store.upsert_vector("c", "b", [0.0, 1.0])
    good = measure_external_parity(
        store,
        collection_id="c",
        query=[1.0, 0.0],
        external_hits=["a", "b"],
        backend=ExternalBackend.FAISS,
        k=2,
        min_ratio=0.5,
    )
    bad = measure_external_parity(
        store,
        collection_id="c",
        query=[1.0, 0.0],
        external_hits=["nope"],
        backend=ExternalBackend.ELASTICSEARCH,
        k=1,
        min_ratio=0.9,
    )
    with pytest.raises(PromotionBlockedError):
        require_parity_for_promotion([good, bad])
    require_parity_for_promotion([good])


# ---------------------------------------------------------------------------
# Shadow dual-read / dual-write for FAISS, Qdrant, Elasticsearch
# ---------------------------------------------------------------------------


def test_shadow_dual_read_all_backends(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    store.upsert_vector("c", "a", [1.0, 0.0])
    store.upsert_vector("c", "b", [0.0, 1.0])

    external_rankings = {
        ExternalBackend.FAISS: ["a", "b"],
        ExternalBackend.QDRANT: ["a", "b"],
        ExternalBackend.ELASTICSEARCH: ["a", "b"],
    }

    adapter = VectorShadowAdapter(
        store, collection_id="c", mode=ShadowMode.DUAL_READ, min_ratio=0.5
    )
    for backend, ranking in external_rankings.items():
        adapter.register_backend(
            backend,
            search=lambda _cid, _q, k=10, r=ranking: r[:k],
        )

    for backend in ExternalBackend:
        result = adapter.dual_read([1.0, 0.0], backend=backend, k=2)
        assert result.backend is backend
        assert result.mode is ShadowMode.DUAL_READ
        # Shadow mode: caller still sees external (primary) ordering.
        assert list(result.caller_ids) == list(result.primary_ids)
        assert result.primary_ids[0] == "a"
        assert "a" in result.candidate_ids

    reports = adapter.measure_all_backends(
        [1.0, 0.0],
        external_hits=external_rankings,
        k=2,
    )
    assert len(reports) == 3
    assert all(r.promotion_allowed for r in reports)
    assert adapter.promote_if_parity(reports) is ShadowMode.PROMOTED
    assert adapter.mode is ShadowMode.PROMOTED

    # After promotion, dual-read returns DuckDB candidate as caller-visible.
    result = adapter.dual_read([1.0, 0.0], backend=ExternalBackend.FAISS, k=2)
    assert list(result.caller_ids) == list(result.candidate_ids)


def test_shadow_dual_write_requires_flags(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    adapter = VectorShadowAdapter(store, collection_id="c")
    with pytest.raises(VectorMigrationError, match="dual-write"):
        adapter.dual_write(
            "a",
            [1.0, 0.0],
            backend=ExternalBackend.FAISS,
            idempotency_key="k1",
        )


def test_shadow_dual_write_all_backends(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    written: dict[str, list[tuple[str, list[float]]]] = {
        "faiss": [],
        "qdrant": [],
        "elasticsearch": [],
    }

    adapter = VectorShadowAdapter(
        store,
        collection_id="c",
        mode=ShadowMode.DUAL_WRITE,
        allow_dual_write=True,
    )
    for backend in ExternalBackend:
        name = backend.value

        def _upsert(
            _cid: str,
            vid: str,
            values,
            metadata=None,
            bucket=name,
        ) -> None:
            written[bucket].append((vid, list(values)))

        adapter.register_backend(backend, upsert=_upsert)

    for backend in ExternalBackend:
        result = adapter.dual_write(
            f"id-{backend.value}",
            [1.0, 0.0],
            backend=backend,
            idempotency_key=f"idem-{backend.value}",
            metadata={"src": backend.value},
        )
        assert result.dual_write_applied is True
        assert result.error == ""
        assert result.idempotency_key == f"idem-{backend.value}"

    assert store.count("c") == 3
    assert len(written["faiss"]) == 1
    assert len(written["qdrant"]) == 1
    assert len(written["elasticsearch"]) == 1

    # Idempotent replay does not re-apply.
    replay = adapter.dual_write(
        "id-faiss",
        [1.0, 0.0],
        backend=ExternalBackend.FAISS,
        idempotency_key="idem-faiss",
    )
    assert replay.dual_write_applied is False
    assert replay.error == "idempotent_replay"
    assert len(written["faiss"]) == 1


def test_promotion_blocked_without_parity(store: ExactVectorStore) -> None:
    store.create_collection("c", dimension=2)
    store.upsert_vector("c", "a", [1.0, 0.0])
    adapter = VectorShadowAdapter(
        store, collection_id="c", mode=ShadowMode.DUAL_READ, min_ratio=0.99
    )
    adapter.register_backend(
        ExternalBackend.FAISS,
        search=lambda *_a, **_k: ["zzz"],
    )
    adapter.dual_read([1.0, 0.0], backend=ExternalBackend.FAISS, k=1)
    with pytest.raises(PromotionBlockedError):
        adapter.promote_if_parity()


def test_vector_digest_stable_for_import(tmp_path: Path, store: ExactVectorStore) -> None:
    values = [0.25, 0.5, 0.75]
    path = _write_pickle(tmp_path / "meta.pkl", {"vectors": {"x": values}})
    report = import_faiss_pickle_metadata(
        path, store, collection_id="c", dimension=3, allow_unpickle=True
    )
    assert report.imported_count == 1
    hits = store.search("c", values, k=1)
    assert hits[0].vector_id == "x"
    assert hits[0].content_digest == vector_digest(values)
