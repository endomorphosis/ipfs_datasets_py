"""Contract tests for the sealed US Code supervisor board."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "config/agent_supervisor_uscode_sparse_graphrag_scheduler.json"


def test_declared_board_validator_accepts_control_plane() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/validate_uscode_sparse_graphrag_board.py"),
            "--check-all",
            "--repo-root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0, report
    assert report["valid"] is True
    assert report["counts"] == {
        "completed": 1,
        "goals": 11,
        "outputs": 126,
        "ready": 6,
        "tasks": 41,
    }
    assert report["ready_task_ids"] == [
        "USCIR-001",
        "USCIR-002",
        "USCIR-003",
        "USCIR-004",
        "USCIR-006",
        "USCIR-007",
    ]


def test_scheduler_is_strict_and_publication_is_human_gated() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["strict_task_sharding"] is True
    assert config["max_lanes"] == 4
    assert [lane["strict_shard_remainder"] for lane in config["lanes"]] == [0, 1, 2, 3]
    assert config["provider"]["fallback_trigger"] == "primary_quota_exhausted"
    assert config["authority_policy"]["autonomous_live_dataset_publication_allowed"] is False
    assert config["authority_policy"]["human_publication_seal_required"] is True
