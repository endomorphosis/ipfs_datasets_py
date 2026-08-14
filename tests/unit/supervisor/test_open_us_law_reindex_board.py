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
    counts = report["counts"]
    assert counts["tasks"] == 58
    assert counts["goals"] == 14
    assert counts["completed"] == 9
    assert counts["ready"] == 2
    assert counts["waiting"] == 47
    assert counts["blocked"] == 0
    assert counts["in_progress"] == 0
    assert counts["generated_tasks"] == 9
    assert counts["generated_goals"] == 0
    assert counts["jurisdictions"] == 51
    assert set(report["current_projection"]["ready_task_ids"]) == {
        "OUL-025",
        "OUL-049",
    }
    assert report["current_projection"]["generated_nonterminal_task_ids"] == [
        f"OUL-{number:03d}" for number in range(49, 58)
    ]
    assert {
        _task_lane(task_id)
        for task_id in report["current_projection"]["ready_task_ids"]
    } == {0, 2}


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
    assert config["source_binding"]["paired_accelerator"]["required_revision"] == (
        "4cc59787445ff759c6172e96ff0174a7471133f6"
    )


def test_shared_status_derives_oul_state_prefix(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config_path = repo_root / "config/agent_supervisor_open_us_law_reindex_scheduler.json"
    report = sample(repo_root, config_path)
    assert report["board_namespace"] == "open-us-law-reindex-v1"
    assert report["lanes"][0]["paths"]["status"].endswith(
        "/lane-0/oul_lane_0_supervisor_status.json"
    )
