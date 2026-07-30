"""Structured chaos-receipt tests without executing the chaos suite."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.knowledge_graphs.chaos import (
    CHAOS_RECEIPT_SCHEMA,
    run_chaos_suite,
)


def test_chaos_runner_writes_content_addressed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, **kwargs):
        if "--junitxml" in command:
            junit = Path(command[command.index("--junitxml") + 1])
            junit.write_text(
                '<testsuites><testsuite tests="3" failures="0" errors="0" '
                'skipped="1" time="0.25"></testsuite></testsuites>',
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0, stdout="2 passed, 1 skipped", stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    receipt_path = tmp_path / "evidence" / "chaos.json"
    result = run_chaos_suite(
        repo_root=tmp_path,
        work_dir=tmp_path / "work",
        receipt_path=receipt_path,
        environment_id="dev-test-linux",
    )
    assert result.status == "success"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == CHAOS_RECEIPT_SCHEMA
    assert receipt["environment_id"] == "dev-test-linux"
    assert receipt["summary"] == {
        "tests": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 1,
        "duration_s": 0.25,
        "problem_tests": [],
    }
    assert receipt["junit_sha256"]
    assert len(receipt["digest"]) == 64


def test_chaos_runner_rejects_unlabelled_environment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="labelled environment"):
        run_chaos_suite(
            repo_root=tmp_path,
            work_dir=tmp_path / "work",
            receipt_path=tmp_path / "receipt.json",
            environment_id="unknown",
        )
