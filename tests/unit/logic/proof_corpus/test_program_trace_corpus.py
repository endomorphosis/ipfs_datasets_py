"""SAWM-023 execution-trace corpus admission tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.proof_corpus.program_trace_corpus import (
    admit_program_trace_row,
    audit_program_trace_leakage,
    build_program_trace_corpus,
)


FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "program_world_trace_corpus.json"
)


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "row_id": "row-1",
        "partition": "training",
        "repository_id": "repo:alpha",
        "commit_cid": "bafkrei",
        "task_cid": "bafkrei-task",
        "function_id": "fn.add",
        "family_id": "family-add",
        "rights_admitted": True,
        "privacy_admitted": True,
        "tree_cid": "bafkrei-tree",
    }
    base.update(overrides)
    return base


def test_empty_corpus_is_training_unavailable() -> None:
    manifest = build_program_trace_corpus([])
    assert manifest.training_unavailable is True
    assert manifest.row_count == 0


def test_fixture_has_six_disjoint_partitions() -> None:
    manifest = build_program_trace_corpus(fixture_path=FIXTURE)
    names = [item.partition for item in manifest.splits]
    assert names == [
        "training",
        "development",
        "held_out",
        "adversarial",
        "cross_repository",
        "ood",
    ]
    assert manifest.training_unavailable is False
    assert manifest.row_count == 6


def test_family_leakage_across_partitions_fails() -> None:
    rows = [
        _row(row_id="a", partition="training", family_id="shared"),
        _row(row_id="b", partition="held_out", family_id="shared"),
    ]
    audit = audit_program_trace_leakage(rows)
    assert audit.clean is False
    with pytest.raises(ValueError, match="leakage"):
        build_program_trace_corpus(rows)


def test_secret_and_model_nomination_rows_are_excluded() -> None:
    with pytest.raises(ValueError, match="excluded"):
        admit_program_trace_row(_row(secret="x"))
    with pytest.raises(ValueError, match="excluded"):
        admit_program_trace_row(_row(private_reasoning="hidden"))
    with pytest.raises(ValueError, match="never labels"):
        admit_program_trace_row(_row(label="model_nomination"))


def test_unadmitted_rights_fail_closed() -> None:
    with pytest.raises(ValueError, match="rights/privacy"):
        admit_program_trace_row(_row(rights_admitted=False))
