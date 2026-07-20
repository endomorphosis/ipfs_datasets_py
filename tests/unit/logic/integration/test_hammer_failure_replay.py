"""Replay tests for verified hammer guidance failures and repairs."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    hammer_guidance_metric_block,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    hammer_failure_projection_todos,
    load_leanstral_direct_guidance_artifacts,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "hammer_failure_replay.jsonl"
)


def _records() -> list[dict]:
    records: list[dict] = []
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                records.append(json.loads(raw))
    return records


def test_hammer_failure_replay_covers_required_cases() -> None:
    records = _records()
    case_types = {str(record.get("case_type") or "") for record in records}

    assert case_types == {
        "accepted_candidate",
        "backend_unavailable",
        "codex_repair_feedback",
        "hammer_unproved",
        "kg_rejected",
        "reconstruction_failed",
        "source_copy_rejected",
        "syntax_rejected",
    }
    serialized = json.dumps(records, sort_keys=True)
    assert "source_text" not in serialized


def test_hammer_failure_replay_feeds_metrics_and_codex_projection() -> None:
    records = _records()
    load_report = load_leanstral_direct_guidance_artifacts([FIXTURE_PATH])
    metrics = hammer_guidance_metric_block(records)
    todos = hammer_failure_projection_todos(
        records,
        min_support=1,
        max_todos_per_cycle=8,
        max_todos_per_scope=4,
    )

    assert load_report["artifact_count"] == 1
    assert load_report["guidance_count"] >= 8
    assert metrics["hammer_artifact_count"] >= 8
    assert 0.0 < metrics["hammer_proof_success_rate"] < 1.0
    assert metrics["hammer_reconstruction_success_rate"] > 0.0
    assert metrics["hammer_source_copy_penalty"] > 0.0
    assert metrics["hammer_backend_unavailable_count"] == 1
    assert todos
    assert any(todo.metadata["failure_reason"] == "hammer_unproved" for todo in todos)
    assert all(todo.metadata["validation_commands"] for todo in todos)
    assert all(todo.metadata["allowed_paths"] for todo in todos)
