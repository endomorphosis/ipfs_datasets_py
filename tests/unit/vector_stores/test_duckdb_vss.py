"""Unit tests for capability-gated VSS acceleration (DQK-022)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore
from ipfs_datasets_py.vector_stores.duckdb_vss import (
    DEFAULT_RECALL_THRESHOLD,
    DEFAULT_TOMBSTONE_PARITY_THRESHOLD,
    IndexHealth,
    VSSIndex,
)


@pytest.fixture
def exact(tmp_path: Path) -> ExactVectorStore:
    s = ExactVectorStore(tmp_path / "exact.duckdb")
    s.create_collection("col", dimension=3)
    yield s
    s.close()


def test_vss_never_identity_authority(exact: ExactVectorStore) -> None:
    idx = VSSIndex(
        exact=exact,
        collection_id="col",
        dimension=3,
        extension_probe=lambda: True,
    )
    receipt = idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    assert receipt.authority == "exact"
    assert receipt.to_dict()["authority"] == "exact"


def test_missing_extension_falls_back_to_exact(exact: ExactVectorStore) -> None:
    idx = VSSIndex(
        exact=exact,
        collection_id="col",
        dimension=3,
        extension_probe=lambda: False,
    )
    idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    result = idx.search([1.0, 0.0, 0.0], k=1)
    assert result.used_fallback is True
    assert result.health is IndexHealth.MISSING_EXTENSION
    assert result.hits[0].vector_id == "a"


def test_corrupt_rebuild_and_tombstone_parity(exact: ExactVectorStore) -> None:
    idx = VSSIndex(
        exact=exact,
        collection_id="col",
        dimension=3,
        extension_probe=lambda: True,
    )
    idx.build({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0], "c": [0.0, 0.0, 1.0]})
    idx.tombstone("b")
    assert idx.tombstone_parity() >= DEFAULT_TOMBSTONE_PARITY_THRESHOLD
    idx.mark_corrupt()
    assert idx.health() is IndexHealth.CORRUPT
    result = idx.search([0.0, 1.0, 0.0], k=2)
    assert result.used_fallback is True
    rebuilt = idx.rebuild()
    assert rebuilt.health is IndexHealth.HEALTHY
    assert "b" not in {h.vector_id for h in idx.search([0.0, 1.0, 0.0], k=5).hits}
    assert DEFAULT_RECALL_THRESHOLD == 0.9
