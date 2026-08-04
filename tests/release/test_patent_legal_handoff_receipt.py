"""Tests for PATLAW-169 operator handoff receipt."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ops.patent_legal_intelligence import handoff_receipt as hr


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_assert_content_free_rejects_credential_markers() -> None:
    with pytest.raises(hr.HandoffError, match="content-free"):
        hr.assert_content_free({"note": "authorization: " + "bearer " + "example"})


def test_build_handoff_binds_tree_and_human_actions(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    state = tmp_path / "state"
    pr_path = state / "pr_package" / "pr_package.json"
    pr_path.parent.mkdir(parents=True)
    pr_path.write_text(
        json.dumps(
            {
                "schema": "patent-legal-pr-package.v1",
                "auto_push": False,
                "push_performed": False,
                "commits": [],
                "changed_paths": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    canary_path = state / "canary" / "receipt.json"
    canary_path.parent.mkdir(parents=True)
    canary_path.write_text(
        json.dumps({"schema": "live-canary-receipt.v1", "mode": "offline", "ok": True})
        + "\n",
        encoding="utf-8",
    )
    hub_path = state / "hub_dry_run" / "receipt.json"
    hub_path.parent.mkdir(parents=True)
    hub_path.write_text(
        json.dumps({"schema": "hub-dry-run-receipt.v1", "dry_run": True, "ok": True})
        + "\n",
        encoding="utf-8",
    )

    receipt = hr.build_handoff_receipt(
        repo_root=repo,
        state_root=state,
        pr_package_path=pr_path,
        canary_receipt_path=canary_path,
        hub_dry_run_receipt_path=hub_path,
    )
    assert receipt["schema"] == hr.SCHEMA
    assert receipt["git_head_sha"]
    assert receipt["git_tree_sha"]
    assert receipt["auto_push"] is False
    assert receipt["auto_file"] is False
    assert receipt["legal_signoff_complete"] is False
    assert receipt["components"]["pr_package"]["present"] is True
    assert receipt["components"]["canary"]["present"] is True
    assert receipt["components"]["hub_dry_run"]["present"] is True
    action_ids = {item["id"] for item in receipt["remaining_human_actions"]}
    assert "human_git_push" in action_ids
    assert "no_auto_legal_signoff" in action_ids
    assert "no_unattended_publish" in action_ids
    assert receipt["ready_for_human_review"] is True
    assert len(receipt["receipt_sha256"]) == 64


def test_build_handoff_lists_gaps_when_artifacts_missing(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    receipt = hr.build_handoff_receipt(repo_root=repo, state_root=tmp_path / "empty-state")
    assert receipt["components"]["pr_package"]["present"] is False
    assert receipt["components"]["pr_package"]["gap"] == "no_artifact_found"
    action_ids = {item["id"] for item in receipt["remaining_human_actions"]}
    assert "assemble_pr_package" in action_ids
    assert receipt["ready_for_human_review"] is False


def test_cli_writes_receipt(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    out = tmp_path / "handoff.json"
    code = hr.main(
        [
            "--repo-root",
            str(repo),
            "--state-root",
            str(tmp_path / "state"),
            "--output",
            str(out),
            "--json",
        ]
    )
    assert code == 0
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == hr.SCHEMA
    assert payload["legal_signoff_complete"] is False
