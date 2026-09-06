from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_progress import (
    classify_progress,
    snapshot_graphrag_progress,
    summarize_lcr_board,
    write_status,
)


def _dest(tmp_path: Path) -> Path:
    dest = tmp_path / "snapshot-graphrag-v2026.08.31-all51-cuda"
    (dest / "checkpoints" / "embeddings").mkdir(parents=True)
    (dest / "checkpoints" / "embeddings" / "manifest.json").write_text(
        json.dumps({"row_count": 695934, "batch_count": 10900}) + "\n",
        encoding="utf-8",
    )
    (dest / "build.resume2.log").write_text(
        "snapshot stage=bm25 sections=537665 chunks=695934\n",
        encoding="utf-8",
    )
    return dest


def test_progress_snapshot_reads_embedding_checkpoint(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    snap = snapshot_graphrag_progress(dest, processes=[])
    assert snap["embedding_row_count"] == 695934
    assert snap["receipt"] is False
    assert snap["authorizing_for_publication"] is False
    assert snap["stage"] == "bm25"


def test_dead_builder_with_embeddings_is_blocked_and_retryable(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    snap = snapshot_graphrag_progress(dest, processes=[])
    snap["process_alive"] = False
    verdict = classify_progress(snap)
    assert verdict["health"] == "blocked"
    assert verdict["retry"] is True


def test_receipt_is_complete(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    (dest / "snapshot_build_receipt.json").write_text("{}\n", encoding="utf-8")
    (dest / "hf-release").mkdir()
    (dest / "hf-release" / "manifest.json").write_text("{}\n", encoding="utf-8")
    snap = snapshot_graphrag_progress(dest, processes=[])
    verdict = classify_progress(snap)
    assert verdict["health"] == "complete"
    assert verdict["retry"] is False


def test_unchanged_signature_inside_window_is_progressing(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    first = snapshot_graphrag_progress(dest, processes=[{"argv": ["python", "build_state_laws_snapshot_sparse_graphrag.py"]}])
    first["process_alive"] = True
    write_status(tmp_path / "status.json", first)
    first["observed_epoch"] = 1_000.0
    second = dict(first)
    second["signature"] = first["signature"]
    verdict = classify_progress(
        second, previous=first, now=1_000.0 + 30, stall_seconds=600
    )
    assert verdict["health"] == "progressing"


def test_lcr_board_marks_084_host_blocked(tmp_path: Path) -> None:
    board = tmp_path / "legal_corpora_reindex.todo.md"
    board.write_text(
        "## LCR-001 Freeze baseline\n- Status: completed\n\n"
        "## LCR-084 Invalidate synthetic state-scrape success\n"
        "- Status: todo\n"
        "- Acceptance: require-live-official exhaustive official evidence for exactly 51\n\n"
        "## LCR-090 Snapshot research index\n- Status: todo\n- Effects: snapshot_research GraphRAG\n",
        encoding="utf-8",
    )
    summary = summarize_lcr_board(board)
    assert summary["counts"]["completed"] == 1
    assert summary["counts"]["todo"] == 2
    assert "LCR-084" in summary["blocked"]
    assert "LCR-090" in summary["feasible"]


def test_unchanged_signature_past_window_is_stalled(tmp_path: Path) -> None:
    dest = _dest(tmp_path)
    first = snapshot_graphrag_progress(
        dest,
        processes=[{"argv": ["python", "build_state_laws_snapshot_sparse_graphrag.py"]}],
    )
    first["process_alive"] = True
    first["observed_epoch"] = 1.0
    second = dict(first)
    verdict = classify_progress(
        second, previous=first, now=1.0 + 1200, stall_seconds=600
    )
    assert verdict["health"] == "stalled"
    assert verdict["retry"] is False
