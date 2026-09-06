"""Unit tests for shared durable graph projection helpers."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.processors.legal_data.legal_graph_projection_runtime import (
    group_rows_by_jurisdiction,
    neighbors_for_legal_ids,
    same_jurisdiction_candidates,
)


def test_group_rows_by_jurisdiction_sorts_and_partitions() -> None:
    rows = [
        SimpleNamespace(jurisdiction_code="WA", legal_id="wa-1"),
        SimpleNamespace(jurisdiction_code="or", legal_id="or-1"),
        {"jurisdiction_code": "OR", "legal_id": "or-2"},
        SimpleNamespace(jurisdiction_code="WA", legal_id="wa-2"),
    ]
    grouped = group_rows_by_jurisdiction(rows)
    assert list(grouped) == ["OR", "WA"]
    assert [row.legal_id if hasattr(row, "legal_id") else row["legal_id"] for row in grouped["OR"]] == [
        "or-1",
        "or-2",
    ]
    assert [row.legal_id for row in grouped["WA"]] == ["wa-1", "wa-2"]


def test_neighbors_for_legal_ids_drops_cross_state_endpoints() -> None:
    kept = neighbors_for_legal_ids(
        [
            {"source_legal_id": "or-1", "target_legal_id": "or-2"},
            {"source_legal_id": "or-1", "target_legal_id": "wa-1"},
        ],
        {"or-1", "or-2"},
    )
    assert len(kept) == 1
    assert kept[0]["target_legal_id"] == "or-2"


def test_same_jurisdiction_candidates_keeps_only_matching_state() -> None:
    source = SimpleNamespace(jurisdiction_code="OR", filters={"jurisdiction": "OR"})
    by_cid = {
        "in": SimpleNamespace(jurisdiction_code="OR", filters={"jurisdiction": "OR"}),
        "out": SimpleNamespace(jurisdiction_code="WA", filters={"jurisdiction": "WA"}),
    }
    kept = same_jurisdiction_candidates(
        {"in": ["term"], "out": ["term"]},
        source=source,
        by_cid=by_cid,
    )
    assert list(kept) == ["in"]
