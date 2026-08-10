"""Unit tests for capability-gated VSS acceleration (DQK-022).

Acceptance coverage:

* VSS is never the identity authority
* Missing/failed extension falls back safely to exact search
* Recall and tombstone parity thresholds are explicit constants
* Tombstone/compaction policy restores parity
* Corruption-safe rebuild re-materializes from exact authority
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore
from ipfs_datasets_py.vector_stores.duckdb_vss import (
    DEFAULT_RECALL_THRESHOLD,
    DEFAULT_TOMBSTONE_PARITY_THRESHOLD,
    DUCKDB_VSS_SCHEMA,
    PINNED_VSS_EXTENSION_BUILD,
    IndexHealth,
    VSSBuildReceipt,
    VSSIndex,
    VSSIndexError,
)


@pytest.fixture
def exact(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    s.create_collection("col", dimension=3)
    yield s
    s.close()


def _index(
    exact: ExactVectorStore,
    *,
    extension: bool = True,
    fail: bool = False,
) -> VSSIndex:
    if fail:

        def _probe() -> bool:
            raise RuntimeError("vss load failed")

        probe = _probe
    else:
        probe = (lambda: True) if extension else (lambda: False)
    return VSSIndex(
        exact=exact,
        collection_id="col",
        dimension=3,
        extension_probe=probe,
    )


# ---------------------------------------------------------------------------
# Acceptance: VSS is never the identity authority
# ---------------------------------------------------------------------------


def test_vss_never_identity_authority(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    receipt = idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    assert isinstance(receipt, VSSBuildReceipt)
    assert receipt.authority == "exact"
    assert receipt.to_dict()["authority"] == "exact"
    assert receipt.to_dict()["schema"] == DUCKDB_VSS_SCHEMA
    # Forged authority on the dataclass is forced back to exact.
    forged = VSSBuildReceipt(
        collection_id="col",
        generation_id=1,
        dimension=3,
        vector_count=1,
        build_digest="sha256:dead",
        authority="vss",  # type: ignore[arg-type]
    )
    assert forged.authority == "exact"
    assert forged.to_dict()["authority"] == "exact"


def test_build_receipt_records_pinned_extension(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    receipt = idx.build({"a": [1.0, 0.0, 0.0]})
    assert receipt.extension_build == PINNED_VSS_EXTENSION_BUILD
    assert receipt.extension_available is True
    assert receipt.health is IndexHealth.HEALTHY
    assert receipt.build_digest.startswith("sha256:")
    assert receipt.index_kind == "vss_hnsw"
    assert idx.last_receipt is receipt


# ---------------------------------------------------------------------------
# Acceptance: Missing/failed extension falls back safely
# ---------------------------------------------------------------------------


def test_missing_extension_falls_back_to_exact(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=False)
    idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    result = idx.search([1.0, 0.0, 0.0], k=1)
    assert result.used_fallback is True
    assert result.health is IndexHealth.MISSING_EXTENSION
    assert result.hits[0].vector_id == "a"
    assert result.recall_estimate == 1.0


def test_failed_extension_probe_falls_back(exact: ExactVectorStore) -> None:
    idx = _index(exact, fail=True)
    idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    assert idx.health() is IndexHealth.EXTENSION_FAILED
    result = idx.search([1.0, 0.0, 0.0], k=1)
    assert result.used_fallback is True
    assert result.health is IndexHealth.EXTENSION_FAILED
    assert result.hits[0].vector_id == "a"


def test_default_probe_is_unavailable_without_injection(
    exact: ExactVectorStore,
) -> None:
    idx = VSSIndex(exact=exact, collection_id="col", dimension=3)
    idx.build({"a": [1.0, 0.0, 0.0]})
    assert idx.health() is IndexHealth.MISSING_EXTENSION
    assert idx.search([1.0, 0.0, 0.0], k=1).used_fallback is True


# ---------------------------------------------------------------------------
# Acceptance: Recall and tombstone parity thresholds are explicit
# ---------------------------------------------------------------------------


def test_thresholds_are_explicit_constants() -> None:
    assert DEFAULT_RECALL_THRESHOLD == 0.9
    assert DEFAULT_TOMBSTONE_PARITY_THRESHOLD == 1.0
    assert 0.0 < DEFAULT_RECALL_THRESHOLD <= 1.0
    assert 0.0 < DEFAULT_TOMBSTONE_PARITY_THRESHOLD <= 1.0


def test_accelerated_path_when_healthy(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    idx.build(
        {
            "a": [1.0, 0.0, 0.0],
            "b": [0.0, 1.0, 0.0],
            "c": [0.0, 0.0, 1.0],
        }
    )
    result = idx.search([1.0, 0.0, 0.0], k=2)
    assert result.used_fallback is False
    assert result.health is IndexHealth.HEALTHY
    assert result.hits[0].vector_id == "a"
    assert result.recall_estimate is not None
    assert result.recall_estimate >= DEFAULT_RECALL_THRESHOLD
    assert result.tombstone_parity == 1.0


# ---------------------------------------------------------------------------
# Tombstone / compaction policy + corrupt rebuild
# ---------------------------------------------------------------------------


def test_corrupt_rebuild_and_tombstone_parity(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    idx.build(
        {
            "a": [1.0, 0.0, 0.0],
            "b": [0.0, 1.0, 0.0],
            "c": [0.0, 0.0, 1.0],
        }
    )
    idx.tombstone("b")
    # Until compact, the accelerated materialization still holds "b".
    assert idx.tombstone_parity() < DEFAULT_TOMBSTONE_PARITY_THRESHOLD
    assert idx.health() is IndexHealth.STALE
    # Search still post-filters tombstones and falls back because parity is low.
    result = idx.search([0.0, 1.0, 0.0], k=2)
    assert result.used_fallback is True
    assert "b" not in {h.vector_id for h in result.hits}

    compact = idx.compact()
    assert compact.authority == "exact"
    assert compact.removed_count == 1
    assert compact.tombstone_parity >= DEFAULT_TOMBSTONE_PARITY_THRESHOLD
    assert idx.tombstone_parity() >= DEFAULT_TOMBSTONE_PARITY_THRESHOLD
    assert idx.health() is IndexHealth.HEALTHY

    idx.mark_corrupt()
    assert idx.health() is IndexHealth.CORRUPT
    corrupt_result = idx.search([0.0, 1.0, 0.0], k=2)
    assert corrupt_result.used_fallback is True
    assert "b" not in {h.vector_id for h in corrupt_result.hits}

    rebuilt = idx.rebuild()
    assert rebuilt.health is IndexHealth.HEALTHY
    assert rebuilt.authority == "exact"
    assert "b" not in {h.vector_id for h in idx.search([0.0, 1.0, 0.0], k=5).hits}
    assert DEFAULT_RECALL_THRESHOLD == 0.9


def test_compaction_receipt_never_claims_vss_authority(
    exact: ExactVectorStore,
) -> None:
    idx = _index(exact, extension=True)
    idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    idx.tombstone("a")
    receipt = idx.compact()
    payload = receipt.to_dict()
    assert payload["authority"] == "exact"
    assert payload["schema"] == DUCKDB_VSS_SCHEMA
    assert payload["removed_count"] == 1
    assert idx.last_compaction is receipt


def test_rebuild_empty_after_all_tombstoned(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    idx.build({"a": [1.0, 0.0, 0.0]})
    idx.tombstone("a")
    idx.compact()
    receipt = idx.rebuild()
    assert receipt.vector_count == 0
    assert receipt.health in {IndexHealth.EMPTY, IndexHealth.MISSING_EXTENSION}
    # With extension available and zero live vectors → EMPTY
    assert receipt.health is IndexHealth.EMPTY
    result = idx.search([1.0, 0.0, 0.0], k=1)
    assert result.used_fallback is True
    assert result.hits == []


def test_dimension_mismatch_rejected(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    with pytest.raises(VSSIndexError) as exc:
        idx.build({"a": [1.0, 0.0]})
    assert exc.value.code == "DIM"


def test_query_dimension_mismatch_rejected(exact: ExactVectorStore) -> None:
    idx = _index(exact, extension=True)
    idx.build({"a": [1.0, 0.0, 0.0]})
    with pytest.raises(VSSIndexError) as exc:
        idx.search([1.0, 0.0], k=1)
    assert exc.value.code == "DIM"
