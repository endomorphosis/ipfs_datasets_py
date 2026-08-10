"""Contract tests for the sealed, refill-aware legal-corpora supervisor board."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "scripts/validate_legal_corpora_reindex_board.py"
CONTROL_FILES = (
    "docs/architecture/LEGAL_CORPORA_REINDEX_PLAN.md",
    "docs/architecture/legal_corpora_reindex.objectives.md",
    "docs/architecture/legal_corpora_reindex.todo.md",
    "config/agent_supervisor_legal_corpora_reindex_scheduler.json",
    "data/agent_supervisor/legal_corpora_reindex/bundles/lane_matrix.json",
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json",
)


def _run_validator(root: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--check-all",
            "--repo-root",
            str(root),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout)


def _copy_control_plane(destination: Path) -> Path:
    for relative in CONTROL_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return destination


def _append_valid_refill(root: Path) -> None:
    objectives = root / "docs/architecture/legal_corpora_reindex.objectives.md"
    objectives.write_text(
        objectives.read_text(encoding="utf-8").rstrip()
        + """

## LCR-G141 Repair a newly observed cohort evidence gap
- Status: active
- Parent: LCR-G024
- Fib priority: 2
- Track: acquisition-repair
- Priority: P0
- Bundle: cohort-gap-repair
- Goal: Repair one current-tree acquisition contradiction without weakening the exact-51 contract.
- Evidence: A replacement jurisdiction receipt and reconciliation proof bound to the discovering evidence.
- Outputs: docs/reports/legal_corpora_reindex/refill/lcr-070-repair.json
- Validation: test -f docs/reports/legal_corpora_reindex/refill/lcr-070-repair.json
- Acceptance: The replacement receipt closes the observed gap and preserves the full jurisdiction cohort.
- Refinement depth: 3
- Embedding query: state laws cohort acquisition gap replacement receipt
- AST query: certify_state_laws_cohort objective refill
- Parallel lane: 0
- Conflict policy: Owns only its replacement evidence; aggregate coverage remains dependency ordered.
- Gap task: Close the discovered cohort receipt contradiction.
""",
        encoding="utf-8",
    )
    taskboard = root / "docs/architecture/legal_corpora_reindex.todo.md"
    taskboard.write_text(
        taskboard.read_text(encoding="utf-8").rstrip()
        + """

## LCR-070 Repair the discovered cohort evidence gap
- Status: todo
- Completion: manual
- Priority: P0
- Track: acquisition-repair
- Depends on: LCR-000
- Goal id: LCR-G141
- Outputs: docs/reports/legal_corpora_reindex/refill/lcr-070-repair.json
- Validation: test -f docs/reports/legal_corpora_reindex/refill/lcr-070-repair.json
- Board namespace: legal-corpora-reindex-v1
- Bundle: cohort-gap-repair
- Parallel lane: cohort-gap-repair
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 0
- Predicted files: docs/reports/legal_corpora_reindex/refill/lcr-070-repair.json
- Allow concurrent with:
- Conflict policy: Owns only its replacement evidence; aggregate coverage remains dependency ordered.
- Preconditions: A content-addressed cohort finding names the failed acceptance evidence.
- Effects: Produces replacement evidence without changing the sealed initial control-plane contract.
- Acceptance: The replacement receipt closes the exact finding and validates against the current tree.
""",
        encoding="utf-8",
    )


def test_declared_board_validator_accepts_control_plane() -> None:
    result, report = _run_validator(REPO_ROOT)
    assert result.returncode == 0, report
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["counts"] == {
        "blocked": 0,
        "completed": 1,
        "continuation_goals": 0,
        "continuation_tasks": 0,
        "goals": 19,
        "in_progress": 0,
        "jurisdictions": 51,
        "outputs": 270,
        "ready": 12,
        "sealed_goals": 19,
        "sealed_tasks": 70,
        "tasks": 70,
        "waiting": 57,
    }
    assert report["current_projection"]["ready_task_ids"] == [
        "LCR-001",
        "LCR-002",
        "LCR-003",
        "LCR-004",
        "LCR-005",
        "LCR-006",
        "LCR-007",
        "LCR-008",
        "LCR-048",
        "LCR-049",
        "LCR-050",
        "LCR-051",
    ]
    assert report["lane_task_counts"] == {"0": 20, "1": 19, "2": 15, "3": 16}


def test_refill_goal_and_task_are_admitted_and_projection_is_recomputed(
    tmp_path: Path,
) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    _append_valid_refill(root)
    taskboard = root / "docs/architecture/legal_corpora_reindex.todo.md"
    taskboard.write_text(
        taskboard.read_text(encoding="utf-8").replace(
            "## LCR-001 Freeze the live Hugging Face and local baseline\n- Status: todo",
            "## LCR-001 Freeze the live Hugging Face and local baseline\n- Status: completed",
            1,
        ),
        encoding="utf-8",
    )

    result, report = _run_validator(root)
    assert result.returncode == 0, report
    assert report["valid"] is True
    assert report["counts"]["tasks"] == 71
    assert report["counts"]["goals"] == 20
    assert report["counts"]["continuation_tasks"] == 1
    assert report["counts"]["continuation_goals"] == 1
    assert report["current_projection"]["continuation_task_ids"] == ["LCR-070"]
    assert report["current_projection"]["continuation_goal_ids"] == ["LCR-G141"]
    assert "LCR-070" in report["current_projection"]["ready_task_ids"]
    assert "LCR-001" not in report["current_projection"]["ready_task_ids"]
    assert report["current_projection"]["completed_task_ids"] == [
        "LCR-000",
        "LCR-001",
    ]
    assert report["sealed_initial_projection"]["ready_task_ids"] == [
        "LCR-001",
        "LCR-002",
        "LCR-003",
        "LCR-004",
        "LCR-005",
        "LCR-006",
        "LCR-007",
        "LCR-008",
        "LCR-048",
        "LCR-049",
        "LCR-050",
        "LCR-051",
    ]


def test_native_refill_semantic_lane_and_optional_metadata_are_admitted(tmp_path: Path) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    _append_valid_refill(root)
    result, report = _run_validator(root)
    assert result.returncode == 0, report
    assert report["valid"] is True
    assert report["current_projection"]["continuation_task_ids"] == ["LCR-070"]


def test_cohort_partition_and_refill_policy_drift_are_rejected(tmp_path: Path) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    taskboard = root / "docs/architecture/legal_corpora_reindex.todo.md"
    taskboard.write_text(
        taskboard.read_text(encoding="utf-8").replace(
            "cohort M (WI, WY, DC)",
            "cohort M (WI, WY, PR)",
        ),
        encoding="utf-8",
    )
    config_path = root / "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["objective_refill_enabled"] = False
    config["refill_policy"]["next_generated_task_number"] = 71
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    result, report = _run_validator(root)
    assert result.returncode == 1
    assert report["valid"] is False
    assert any("LCR-021: sealed title mismatch" in error for error in report["errors"])
    assert any("cohort M must be ['WI', 'WY', 'DC']" in error for error in report["errors"])
    assert any("objective_refill_enabled must be true" in error for error in report["errors"])
    assert any("next_generated_task_number must be 70" in error for error in report["errors"])
