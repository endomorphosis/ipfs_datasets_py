"""Tests for LCR-071 live corpus materialization."""

from __future__ import annotations

from pathlib import Path

import scripts.ops.legal_data.materialize_federal_register_live_corpus as mat


def test_missing_checkpoint_fails_closed(tmp_path: Path) -> None:
    try:
        mat.materialize(
            checkpoint_path=tmp_path / "missing.json",
            corpus_dir=tmp_path / "corpus",
            limit=1,
        )
    except (mat.MaterializeError, FileNotFoundError, OSError):
        return
    raise AssertionError("missing checkpoint must fail closed")
