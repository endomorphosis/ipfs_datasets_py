"""Tests for deterministic ``ObjectiveRefillFixedPoint@2`` evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.conformance import fixed_point_v2 as fp


def _run(repo: Path, *args: str) -> None:
    subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _board(*, sealing_statuses: tuple[str, str] = ("todo", "todo")) -> str:
    blocks = ["# Test Wave-2 board", ""]
    for index in range(51):
        task_id = f"LFP2-{index:03d}"
        status = "completed" if index <= 48 else sealing_statuses[index - 49]
        blocks.extend(
            (
                f"## {task_id} Test task {index}",
                "",
                f"- Status: {status}",
                "- Completion: manual",
                "",
            )
        )
    return "\n".join(blocks)


def _matrix_payload() -> dict[str, Any]:
    zeros = {name: 0 for name in fp.HARD_ZERO_FLOOR_NAMES}
    return {
        "interface": "ReachableConformanceMatrix@2",
        "schema_version": "reachable-conformance-matrix/v2",
        "task_id": "LFP2-047",
        "goal_id": "LFP2-G080",
        "materialization": (
            "ipfs_datasets_py.logic.conformance.matrix_v2:"
            "build_default_reachable_conformance_matrix"
        ),
        "acceptance": {
            **zeros,
            "hard_zero_floors_clear": True,
            "sparse": True,
        },
        "hard_zero_floors": {
            **zeros,
            "all_clear": True,
            "schema_version": "reachable-conformance-hard-zero-floors/v2",
        },
        "summary": {
            "acceptance_holds": True,
            "every_cell_has_all_join_dimensions": True,
            "hard_zero_floors_clear": True,
            "sparse": True,
        },
    }


def _fake_live_accounting() -> dict[str, Any]:
    return {
        "interface": "ReachableConformanceMatrix@2",
        "content_id": "sha256:" + "1" * 64,
        "content_sha256": "1" * 64,
        "cell_count": 7,
        "domain_count": 2,
        "domain_ids": ["legal_ir", "security_ir"],
        "provider_count": 2,
        "provider_ids": ["cvc5", "z3"],
        "hard_zero_floors": {
            **{name: 0 for name in fp.HARD_ZERO_FLOOR_NAMES},
            "all_clear": True,
            "schema_version": "reachable-conformance-hard-zero-floors/v2",
        },
        "acceptance_holds": True,
    }


@pytest.fixture()
def evidence_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "outer"
    nested = root / fp.NESTED_REPOSITORY_PATH
    root.mkdir()
    _run(root, "init", "-b", fp.MERGE_TARGET_BRANCH)
    _run(root, "config", "user.email", "fixed-point@example.test")
    _run(root, "config", "user.name", "Fixed Point Test")

    nested.mkdir()
    _run(nested, "init", "-b", "nested-test")
    _run(nested, "config", "user.email", "fixed-point@example.test")
    _run(nested, "config", "user.name", "Fixed Point Test")
    for name, relative in fp._NESTED_BINDING_PATHS.items():
        path = nested / relative
        if name == "reachable_matrix":
            _write(path, json.dumps(_matrix_payload(), sort_keys=True) + "\n")
        else:
            _write(path, f"fixture for {name}\n")
    predecessor_release = nested / "data/logic/conformance/logic_family_parser_release.json"
    _write(predecessor_release, '{"wave":1}\n')
    _run(nested, "add", ".")
    _run(nested, "commit", "-m", "nested semantic evidence")

    _write(root / fp.TODO_RELATIVE_PATH, _board())
    _write(root / fp.OBJECTIVE_RELATIVE_PATH, "# Objective heap\n")
    _write(root / fp.SCHEDULER_RELATIVE_PATH, '{"max_lanes":4}\n')
    predecessor_paths = (
        "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md",
        "docs/architecture/ipfs_datasets_logic_family_parser.objectives.md",
        "docs/architecture/ipfs_datasets_logic_family_parser.todo.md",
        ("data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/fixed_point_receipt.json"),
        ("data/agent_supervisor/ipfs_datasets_logic_family_parser/refill/gap_ledger.jsonl"),
    )
    for index, relative in enumerate(predecessor_paths, start=1):
        _write(root / relative, f"wave-1-anchor-{index}\n")
    pins = {
        relative: _digest(root / relative)
        for relative in (
            *predecessor_paths[:3],
            "ipfs_datasets_py/data/logic/conformance/logic_family_parser_release.json",
            *predecessor_paths[3:],
        )
    }
    monkeypatch.setattr(fp, "PREDECESSOR_ANCHOR_SHA256", pins)
    monkeypatch.setattr(fp, "_live_matrix_accounting", lambda _path: _fake_live_accounting())
    _run(root, "add", ".")
    _run(root, "commit", "-m", "outer evidence and nested gitlink")
    return root


def _paths(root: Path) -> tuple[Path, Path]:
    return root / "artifacts/fixed_point_receipt.json", root / "artifacts/gap_ledger.jsonl"


def _materialize(root: Path) -> tuple[dict[str, Any], Path, Path]:
    fixed, ledger = _paths(root)
    receipt = fp.materialize_fixed_point_evidence(
        repo_root=root,
        fixed_point_path=fixed,
        ledger_path=ledger,
    )
    return receipt, fixed, ledger


def test_materializes_two_serial_empty_epochs_idempotently(
    evidence_repo: Path,
) -> None:
    receipt, fixed, ledger = _materialize(evidence_repo)
    first_fixed = fixed.read_bytes()
    first_ledger = ledger.read_bytes()
    second = fp.materialize_fixed_point_evidence(
        repo_root=evidence_repo,
        fixed_point_path=fixed,
        ledger_path=ledger,
    )
    assert fixed.read_bytes() == first_fixed
    assert ledger.read_bytes() == first_ledger
    assert second == receipt
    assert receipt["interface"] == "ObjectiveRefillFixedPoint@2"
    assert receipt["is_fixed_point"] is True
    assert receipt["consecutive_empty_scans"] == 2
    assert receipt["open_nonsealing_task_ids"] == []
    assert receipt["open_nonsealing_task_count"] == 0
    assert receipt["sealing_exclusions"] == ["LFP2-049", "LFP2-050"]
    assert [epoch["disposition"] for epoch in receipt["epochs"]] == [
        "empty_input",
        "empty_input",
    ]
    assert all(not epoch["admitted_tasks"] for epoch in receipt["epochs"])
    assert receipt["matrix_accounting"]["cell_count"] == 7
    assert receipt["completion_authority"] is False
    assert receipt["mutation_authority"] is False
    assert receipt["seed_board_edit"] is False

    entries = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(entries) == 2
    assert entries[0]["previous_entry_sha256"] == "sha256:" + "0" * 64
    assert entries[1]["previous_entry_sha256"] == entries[0]["entry_sha256"]
    assert all(entry["entry_id"] == entry["entry_sha256"] for entry in entries)
    assert receipt["ledger"]["raw_sha256"] == _digest(ledger)


@pytest.mark.parametrize(
    "sealing_statuses",
    (("completed", "todo"), ("completed", "completed")),
)
def test_sealing_status_transitions_do_not_stale_receipt(
    evidence_repo: Path, sealing_statuses: tuple[str, str]
) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    board = evidence_repo / fp.TODO_RELATIVE_PATH
    board.write_text(_board(sealing_statuses=sealing_statuses), encoding="utf-8")
    validated = fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)
    assert validated["is_fixed_point"] is True


def test_staged_release_self_outputs_are_tolerated(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    nested = evidence_repo / fp.NESTED_REPOSITORY_PATH
    for relative in fp.RELEASE_SELF_OUTPUT_PATHS:
        _write(nested / relative, f"release self output: {relative}\n")
    _run(nested, "add", *fp.RELEASE_SELF_OUTPUT_PATHS)
    validated = fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)
    assert validated["is_fixed_point"] is True


def test_committed_release_outputs_and_new_gitlink_do_not_stale_receipt(
    evidence_repo: Path,
) -> None:
    receipt, fixed, ledger = _materialize(evidence_repo)
    nested = evidence_repo / fp.NESTED_REPOSITORY_PATH
    projection = receipt["identity_bindings"]["nested_repository"][
        "semantic_tree_projection_sha256"
    ]
    for relative in fp.RELEASE_SELF_OUTPUT_PATHS:
        _write(nested / relative, f"committed release output: {relative}\n")
    _run(nested, "add", *fp.RELEASE_SELF_OUTPUT_PATHS)
    _run(nested, "commit", "-m", "add Wave-2 release self outputs")
    _run(evidence_repo, "add", fp.NESTED_REPOSITORY_PATH)
    _run(evidence_repo, "commit", "-m", "advance release gitlink")
    validated = fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)
    nested_identity = validated["identity_bindings"]["nested_repository"]
    assert nested_identity["semantic_tree_projection_sha256"] == projection
    assert "nested_head_oid" not in nested_identity
    assert "nested_tree_oid" not in nested_identity
    assert "superproject_gitlink_oid" not in nested_identity


def test_rejects_other_dirty_nested_path(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    nested = evidence_repo / fp.NESTED_REPOSITORY_PATH
    _write(nested / "semantic-drift.txt", "uncommitted semantic drift\n")
    with pytest.raises(fp.FixedPointIdentityError, match="semantic inputs"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_other_committed_nested_projection_change(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    nested = evidence_repo / fp.NESTED_REPOSITORY_PATH
    _write(nested / "semantic-drift.txt", "committed semantic drift\n")
    _run(nested, "add", "semantic-drift.txt")
    _run(nested, "commit", "-m", "change semantic projection")
    _run(evidence_repo, "add", fp.NESTED_REPOSITORY_PATH)
    _run(evidence_repo, "commit", "-m", "advance semantic gitlink")
    with pytest.raises(fp.FixedPointIdentityError, match="identities have drifted"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_receipt_tampering(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    payload = json.loads(fixed.read_text())
    payload["is_fixed_point"] = False
    fixed.write_bytes(fp._canonical_bytes(payload) + b"\n")
    with pytest.raises(fp.FixedPointV2Error, match="is_fixed_point"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_changed_content_identity(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    objective = evidence_repo / fp.OBJECTIVE_RELATIVE_PATH
    objective.write_text("# Changed objective heap\n", encoding="utf-8")
    with pytest.raises(fp.FixedPointIdentityError, match="identit"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_matrix_gap_before_sealing(evidence_repo: Path) -> None:
    matrix = (
        evidence_repo / fp.NESTED_REPOSITORY_PATH / fp._NESTED_BINDING_PATHS["reachable_matrix"]
    )
    payload = json.loads(matrix.read_text())
    payload["acceptance"]["unexplained_reachable_gap"] = 1
    matrix.write_text(json.dumps(payload), encoding="utf-8")
    fixed, ledger = _paths(evidence_repo)
    with pytest.raises(fp.FixedPointMatrixError, match="integer zero"):
        fp.materialize_fixed_point_evidence(
            repo_root=evidence_repo,
            fixed_point_path=fixed,
            ledger_path=ledger,
        )


def test_rejects_open_appended_derived_task(evidence_repo: Path) -> None:
    board = evidence_repo / fp.TODO_RELATIVE_PATH
    board.write_text(
        board.read_text() + "\n## LFP2-051 Derived gap\n\n- Status: todo\n- Completion: manual\n",
        encoding="utf-8",
    )
    fixed, ledger = _paths(evidence_repo)
    with pytest.raises(fp.FixedPointOpenWorkError, match="appended derived"):
        fp.materialize_fixed_point_evidence(
            repo_root=evidence_repo,
            fixed_point_path=fixed,
            ledger_path=ledger,
        )


def test_rejects_reopened_nonsealing_seed_task(evidence_repo: Path) -> None:
    board = evidence_repo / fp.TODO_RELATIVE_PATH
    text = board.read_text().replace(
        "## LFP2-048 Test task 48\n\n- Status: completed",
        "## LFP2-048 Test task 48\n\n- Status: todo",
    )
    board.write_text(text, encoding="utf-8")
    fixed, ledger = _paths(evidence_repo)
    with pytest.raises(fp.FixedPointOpenWorkError, match="non-sealing seed"):
        fp.materialize_fixed_point_evidence(
            repo_root=evidence_repo,
            fixed_point_path=fixed,
            ledger_path=ledger,
        )


def test_rejects_ledger_digest_or_chain_mismatch(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    ledger.write_bytes(ledger.read_bytes() + b"\n")
    with pytest.raises(fp.FixedPointV2Error, match="ledger bytes"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_body_digest_mismatch(evidence_repo: Path) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    payload = json.loads(fixed.read_text())
    payload["receipt_body_sha256"] = "sha256:" + "0" * 64
    fixed.write_bytes(fp._canonical_bytes(payload) + b"\n")
    with pytest.raises(fp.FixedPointV2Error, match="body sha256 mismatch"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_live_matrix_drift(evidence_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, fixed, ledger = _materialize(evidence_repo)
    changed = _fake_live_accounting()
    changed["content_id"] = "sha256:" + "2" * 64
    changed["content_sha256"] = "2" * 64
    monkeypatch.setattr(fp, "_live_matrix_accounting", lambda _path: changed)
    with pytest.raises(fp.FixedPointMatrixError, match="accounting has drifted"):
        fp.validate_fixed_point_artifacts(fixed, ledger, repo_root=evidence_repo)


def test_rejects_missing_canonical_predecessor_anchor(evidence_repo: Path) -> None:
    missing = next(
        relative
        for relative in fp.PREDECESSOR_ANCHOR_SHA256
        if relative.endswith("gap_ledger.jsonl")
    )
    (evidence_repo / missing).unlink()
    fixed, ledger = _paths(evidence_repo)
    with pytest.raises(fp.FixedPointIdentityError, match="unreadable"):
        fp.materialize_fixed_point_evidence(
            repo_root=evidence_repo,
            fixed_point_path=fixed,
            ledger_path=ledger,
        )


def test_rejects_duplicate_merge_target_worktree_metadata(
    evidence_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_git = fp._git
    original = original_git(evidence_repo, "worktree", "list", "--porcelain")

    def duplicated(repo: Path, *args: str) -> bytes:
        if args == ("worktree", "list", "--porcelain"):
            return original + b"\n" + original
        return original_git(repo, *args)

    monkeypatch.setattr(fp, "_git", duplicated)
    with pytest.raises(fp.FixedPointIdentityError, match="exactly one worktree"):
        fp._canonical_merge_target_worktree(evidence_repo)


def test_rejects_missing_merge_target_branch(evidence_repo: Path) -> None:
    _run(evidence_repo, "branch", "-m", "not-the-merge-target")
    with pytest.raises(fp.FixedPointIdentityError, match="found 0"):
        fp._canonical_merge_target_worktree(evidence_repo)


def test_cli_materialize_and_validate_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt = {
        "is_fixed_point": True,
        "consecutive_empty_scans": 2,
        "receipt_body_sha256": "sha256:" + "3" * 64,
        "ledger": {"raw_sha256": "sha256:" + "4" * 64},
    }
    calls: list[tuple[str, Path, Path, Path]] = []

    def materialize(**kwargs: Any) -> dict[str, Any]:
        calls.append(
            (
                "materialize",
                Path(kwargs["repo_root"]),
                Path(kwargs["fixed_point_path"]),
                Path(kwargs["ledger_path"]),
            )
        )
        return receipt

    def validate(
        fixed_path: Path | str,
        ledger_path: Path | str,
        *,
        repo_root: Path | str,
        tasks: object = None,
    ) -> dict[str, Any]:
        del tasks
        calls.append(("validate", Path(repo_root), Path(fixed_path), Path(ledger_path)))
        return receipt

    monkeypatch.setattr(fp, "materialize_fixed_point_evidence", materialize)
    monkeypatch.setattr(fp, "validate_fixed_point_artifacts", validate)
    fixed = tmp_path / "fixed.json"
    ledger = tmp_path / "ledger.jsonl"
    common = [
        "--repo-root",
        str(tmp_path),
        "--fixed-point-path",
        str(fixed),
        "--ledger-path",
        str(ledger),
    ]
    assert fp.main(["materialize", *common]) == 0
    assert fp.main(["validate", *common]) == 0
    assert [call[0] for call in calls] == ["materialize", "validate"]
    assert capsys.readouterr().out.count('"valid": true') == 2
