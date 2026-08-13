"""Control-plane tests for the Open US Law sparse GraphRAG supervisor."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ops.legal_corpora_reindex.status import sample
from scripts.validate_open_us_law_reindex_board import _task_lane, validate


def test_open_us_law_board_is_valid_and_parallel() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    report = validate(repo_root)
    assert report["valid"], report["errors"]
    assert report["counts"] == {
        "tasks": 49,
        "goals": 14,
        "completed": 1,
        "ready": 8,
        "waiting": 40,
        "blocked": 0,
        "in_progress": 0,
        "generated_tasks": 0,
        "generated_goals": 0,
        "jurisdictions": 51,
        "outputs": 124,
    }
    assert set(report["current_projection"]["ready_task_ids"]) == {
        f"OUL-{number:03d}" for number in range(1, 9)
    }
    assert {_task_lane(task_id) for task_id in report["current_projection"]["ready_task_ids"]} == {0, 1, 2, 3}


def test_open_us_law_provider_and_release_contract_are_exact() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = json.loads(
        (repo_root / "config/agent_supervisor_open_us_law_reindex_scheduler.json").read_text()
    )
    assert config["provider"] == {
        "primary_provider_id": "grok_cli",
        "primary_model_id": "grok-4.6",
        "fallback_provider_id": "codex",
        "fallback_model_id": "gpt-5.6-terra",
        "fallback_trigger": "primary_quota_exhausted",
        "fallback_reasoning_effort": "medium",
        "max_concurrency": 4,
        "secrets_from_environment_only": True,
        "secrets_in_argv_prompts_logs_or_receipts": False,
    }
    assert config["release_policy"]["maximum_rows_per_physical_shard"] == 4096
    assert config["release_policy"]["embedding_model"] == "thenlper/gte-small"
    assert len(config["release_policy"]["embedding_revision"]) == 40


def test_shared_status_derives_oul_state_prefix(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config_path = repo_root / "config/agent_supervisor_open_us_law_reindex_scheduler.json"
    report = sample(repo_root, config_path)
    assert report["board_namespace"] == "open-us-law-reindex-v1"
    assert report["lanes"][0]["paths"]["status"].endswith(
        "/lane-0/oul_lane_0_supervisor_status.json"
    )
