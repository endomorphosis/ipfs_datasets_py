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

## LCR-G146 Repair a newly observed cohort evidence gap
- Status: active
- Parent: LCR-G024
- Fib priority: 2
- Track: acquisition-repair
- Priority: P0
- Bundle: cohort-gap-repair
- Goal: Repair one current-tree acquisition contradiction without weakening the exact-51 contract.
- Evidence: A replacement jurisdiction receipt and reconciliation proof bound to the discovering evidence.
- Outputs: docs/reports/legal_corpora_reindex/refill/lcr-084-repair.json
- Validation: test -f docs/reports/legal_corpora_reindex/refill/lcr-084-repair.json
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

## LCR-084 Repair the discovered cohort evidence gap
- Status: todo
- Completion: manual
- Priority: P0
- Track: acquisition-repair
- Depends on: LCR-000
- Goal id: LCR-G146
- Outputs: docs/reports/legal_corpora_reindex/refill/lcr-084-repair.json
- Validation: test -f docs/reports/legal_corpora_reindex/refill/lcr-084-repair.json
- Board namespace: legal-corpora-reindex-v1
- Bundle: cohort-gap-repair
- Parallel lane: cohort-gap-repair
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 0
- Predicted files: docs/reports/legal_corpora_reindex/refill/lcr-084-repair.json
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
    counts = report["counts"]
    assert counts["sealed_tasks"] == 70
    assert counts["sealed_goals"] == 19
    assert counts["tasks"] >= 80
    assert counts["continuation_tasks"] >= 10
    assert counts["goals"] >= 20
    assert counts["jurisdictions"] == 51
    assert counts["blocked"] == 0
    required_continuations = {f"LCR-{number:03d}" for number in range(70, 80)}
    assert required_continuations <= set(
        report["current_projection"]["continuation_task_ids"]
    )
    rights_tasks = {"LCR-077", "LCR-078", "LCR-079"}
    phase_blockers = report["current_projection"][
        "publication_blocking_generated_task_ids_by_phase"
    ]
    assert all(rights_tasks <= set(task_ids) for task_ids in phase_blockers.values())
    assert sum(report["lane_task_counts"].values()) == counts["tasks"]


def test_refill_goal_and_task_are_admitted_and_projection_is_recomputed(
    tmp_path: Path,
) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    baseline_result, baseline = _run_validator(root)
    assert baseline_result.returncode == 0, baseline
    _append_valid_refill(root)

    result, report = _run_validator(root)
    assert result.returncode == 0, report
    assert report["valid"] is True
    assert report["counts"]["tasks"] == baseline["counts"]["tasks"] + 1
    assert report["counts"]["goals"] == baseline["counts"]["goals"] + 1
    assert (
        report["counts"]["continuation_tasks"]
        == baseline["counts"]["continuation_tasks"] + 1
    )
    assert (
        report["counts"]["continuation_goals"]
        == baseline["counts"]["continuation_goals"] + 1
    )
    assert "LCR-084" in report["current_projection"]["continuation_task_ids"]
    assert "LCR-G146" in report["current_projection"]["continuation_goal_ids"]
    assert "LCR-084" in report["current_projection"]["ready_task_ids"]
    blockers = report["current_projection"][
        "publication_blocking_generated_task_ids_by_phase"
    ]
    assert "LCR-084" in blockers["state_staging"]
    assert "LCR-084" in blockers["state_main"]
    assert "LCR-084" not in blockers["federal_staging"]
    assert "LCR-084" not in blockers["federal_main"]
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
    assert "LCR-084" in report["current_projection"]["continuation_task_ids"]


def test_shared_publication_gate_refill_blocks_every_mutation_phase(
    tmp_path: Path,
) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    _append_valid_refill(root)
    objectives = root / "docs/architecture/legal_corpora_reindex.objectives.md"
    objectives.write_text(
        objectives.read_text(encoding="utf-8").replace(
            "- Parent: LCR-G024\n- Fib priority: 2\n- Track: acquisition-repair",
            "- Parent: LCR-G080\n- Fib priority: 2\n- Track: acquisition-repair",
        ),
        encoding="utf-8",
    )

    result, report = _run_validator(root)
    assert result.returncode == 0, report
    blockers = report["current_projection"][
        "publication_blocking_generated_task_ids_by_phase"
    ]
    assert all("LCR-084" in task_ids for task_ids in blockers.values())


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
    config["refill_policy"]["generated_task_number_floor"] = 71
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    result, report = _run_validator(root)
    assert result.returncode == 1
    assert report["valid"] is False
    assert any("LCR-021: sealed title mismatch" in error for error in report["errors"])
    assert any("cohort M must be ['WI', 'WY', 'DC']" in error for error in report["errors"])
    assert any("objective_refill_enabled must be true" in error for error in report["errors"])
    assert any("generated_task_number_floor must be 70" in error for error in report["errors"])


def test_controlled_reseal_task_contract_drift_is_rejected(tmp_path: Path) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    taskboard = root / "docs/architecture/legal_corpora_reindex.todo.md"
    text = taskboard.read_text(encoding="utf-8")
    text = text.replace(
        "## LCR-071 Run the complete live Federal Register production pipeline end to end",
        "## LCR-071 Run a weakened Federal Register sample",
    )
    text = text.replace(
        "- Depends on: LCR-060, LCR-062, LCR-063, LCR-070, LCR-075, LCR-076",
        "- Depends on: LCR-060",
    )
    text = text.replace(
        "scripts/ops/legal_data/run_federal_register_full_release_acceptance.py, tests/integration/legal_data/test_federal_register_full_release_acceptance.py, docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json",
        "docs/reports/legal_corpora_reindex/weakened.json",
    )
    text = text.replace(
        "- Acceptance: No fixture-only, sampled, capped, metadata-as-body, future-dated, failed-final, stale-success, or partial-checkpoint path can satisfy the receipt; it binds actual cutoff/observation times, official totals, unique document numbers, per-source attempt exhaustion, full-text dispositions, model/revision, family/key parity, resource usage, artifact digests, and successful local queries before any Federal staging mutation.",
        "- Acceptance: A sample exists.",
    )
    taskboard.write_text(text, encoding="utf-8")

    result, report = _run_validator(root)
    assert result.returncode == 1
    assert any("LCR-071: controlled-reseal title mismatch" in error for error in report["errors"])
    assert any(
        "LCR-071: controlled-reseal dependency contract changed" in error
        for error in report["errors"]
    )
    assert any(
        "LCR-071: controlled-reseal output contract changed" in error
        for error in report["errors"]
    )
    assert any(
        "LCR-071: controlled-reseal acceptance contract changed" in error
        for error in report["errors"]
    )


def test_phase_gate_and_dynamic_generated_work_guard_drift_are_rejected(
    tmp_path: Path,
) -> None:
    root = _copy_control_plane(tmp_path / "repo")
    policy_path = (
        root
        / "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    contract = policy["prepublication_evidence_contract"]
    contract["phase_requirements"]["state_staging"][
        "prepublication_seal_required"
    ] = True
    contract["phase_requirements"]["state_staging"]["required_task_ids"].remove(
        "LCR-039"
    )
    contract["generated_work_guard"][
        "deny_nonterminal_matching_generated_work"
    ] = False
    policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result, report = _run_validator(root)
    assert result.returncode == 1
    assert any("phase_requirements" in error for error in report["errors"])
    assert any("generated_work_guard" in error for error in report["errors"])


def test_source_rights_goal_task_and_publication_contract_cannot_be_detached(
    tmp_path: Path,
) -> None:
    root = _copy_control_plane(tmp_path / "repo")

    objectives = root / "docs/architecture/legal_corpora_reindex.objectives.md"
    objectives.write_text(
        objectives.read_text(encoding="utf-8").replace(
            "## LCR-G141 Prove source rights and redistribution admissibility before publication\n"
            "- Status: active\n"
            "- Parent: LCR-G010",
            "## LCR-G141 Prove source rights and redistribution admissibility before publication\n"
            "- Status: active\n"
            "- Parent: LCR-G000",
        ),
        encoding="utf-8",
    )

    taskboard = root / "docs/architecture/legal_corpora_reindex.todo.md"
    taskboard.write_text(
        taskboard.read_text(encoding="utf-8").replace(
            "- Acceptance: Fixtures distinguish statutory or Federal government text from site presentation, annotations, editorial enhancements, and databases; malformed, stale, unknown, prohibited, scope-mismatched, or unsupported evidence fails closed and no dataset-card label alone proves admissibility.",
            "- Acceptance: A dataset-card label is enough.",
        ),
        encoding="utf-8",
    )

    config_path = root / "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["authority_policy"]["unknown_or_prohibited_source_rights_allowed"] = True
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    policy_path = (
        root
        / "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["source_rights_contract"][
        "unknown_or_prohibited_allowed_in_default_release"
    ] = True
    policy["prepublication_evidence_contract"]["phase_requirements"][
        "federal_main"
    ]["required_task_ids"].remove("LCR-079")
    policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    result, report = _run_validator(root)
    assert result.returncode == 1
    assert any(
        "LCR-G141: controlled-reseal parent contract changed" in error
        for error in report["errors"]
    )
    assert any(
        "LCR-077: controlled-reseal acceptance contract changed" in error
        for error in report["errors"]
    )
    assert any(
        "unknown_or_prohibited_source_rights_allowed" in error
        for error in report["errors"]
    )
    assert any("source_rights_contract" in error for error in report["errors"])
    assert any("phase_requirements" in error for error in report["errors"])
