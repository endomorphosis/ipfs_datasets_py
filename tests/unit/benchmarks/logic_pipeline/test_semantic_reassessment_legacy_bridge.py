"""Fail-closed coverage for the obsolete revision-1 semantic bridge."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import semantic_reassessment as semantic
from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline.matrix_reassessment import MATRIX_INDEX_SCHEMA
from benchmarks.logic_pipeline.reassessment_namespace import (
    ReassessmentRunLayout,
)
from benchmarks.logic_pipeline.semantic_reassessment import (
    SemanticReassessmentError,
)


RUN_ID = "legacy-semantic-bridge-rejection"


@pytest.mark.parametrize(
    "entrypoint",
    (
        semantic.execute_semantic_reassessment,
        semantic.validate_semantic_reassessment_from_matrix,
    ),
)
def test_revision_1_matrix_is_rejected_before_result_loading_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: Callable[..., object],
) -> None:
    benchmark_root = tmp_path / "benchmark-runs"
    layout = ReassessmentRunLayout.for_run(
        RUN_ID,
        benchmark_root=benchmark_root,
    )
    layout.matrix_index.parent.mkdir(parents=True)
    layout.matrix_index.write_text(
        canonical_json({"schema": MATRIX_INDEX_SCHEMA}) + "\n",
        encoding="utf-8",
    )

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        pytest.fail(
            "legacy matrix rejection must precede prerequisite validation, "
            "result loading, and semantic output construction"
        )

    monkeypatch.setattr(
        semantic,
        "validate_frozen_capability_reprobe",
        unexpected_call,
    )
    monkeypatch.setattr(
        semantic,
        "validate_reassessment_matrix",
        unexpected_call,
    )
    monkeypatch.setattr(
        semantic,
        "_load_matrix_frontend_results",
        unexpected_call,
    )
    monkeypatch.setattr(
        semantic,
        "build_semantic_reassessment",
        unexpected_call,
    )

    with pytest.raises(
        SemanticReassessmentError,
        match=(
            r"reassessment-matrix\.v1 is revision-1 diagnostic evidence.*"
            r"G201 source-only semantic-v2 execution path"
        ),
    ):
        entrypoint(
            repository_root=tmp_path,
            run_id=RUN_ID,
            benchmark_root=benchmark_root,
        )

    assert layout.matrix_index.is_file()
    assert not layout.frontend_report.exists()
    assert not layout.frontend_receipt_directory.exists()
    assert not layout.frontend_receipt_index.exists()
