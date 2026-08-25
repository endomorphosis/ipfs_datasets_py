"""Unit tests for the OUL-049 tracked retry-repair auditor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_audit():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "audit_open_us_law_retry_repair.py"
    spec = importlib.util.spec_from_file_location(
        "audit_open_us_law_retry_repair_oul049", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load_audit()
main = audit.main


def test_committed_report_matches_builder_and_releases_oul_011() -> None:
    report = audit.check_committed_repair(
        task_id="OUL-049",
        source_task_id="OUL-011",
        cohort="C",
    )
    assert report["status"] == "passed"
    assert report["repair_completed"] is True
    assert report["cohort_complete"] is False
    assert report["fixture_execution_proves_cohort_completion"] is False
    assert report["authorizing_for_publication"] is False
    assert report["source_task_id"] == "OUL-011"
    assert report["task_id"] == "OUL-049"
    assert report["cohort"] == "C"


def test_builder_binds_current_source_and_validation_digests() -> None:
    payload = audit.build_retry_repair_payload(
        task_id="OUL-049",
        source_task_id="OUL-011",
        cohort="C",
    )
    assert payload["jurisdictions"] == ["FL", "GA", "HI", "ID"]
    assert payload["repair_completed"] is True
    assert payload["cohort_complete"] is False
    assert payload["software_behavior_proven"] is True
    assert set(item["id"] for item in payload["repairs"]) == {
        item["id"] for item in audit.OUL_049_REPAIRS
    }
    assert payload["source_digests"] == audit.current_source_digests()
    assert payload["validation_digests"] == audit.current_validation_digests()
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_cli_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--task", "OUL-049", "--source", "OUL-011", "--cohort", "C", "--check"]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "repair_completed=True" in out
    assert "cohort_complete=False" in out


def test_cli_check_json_is_secret_free(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(
        ["--task", "OUL-049", "--source", "OUL-011", "--cohort", "C", "--check", "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_terminal_oul_085_builder_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = audit.build_retry_repair_payload(
        task_id="OUL-085",
        source_task_id="OUL-048",
    )
    assert payload["task_id"] == "OUL-085"
    assert payload["source_task_id"] == "OUL-048"
    assert payload["cohort"] == ""
    assert payload["goal_id"] == "OUL-G090"
    assert payload["repair_completed"] is True
    assert payload["cohort_complete"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["jurisdictions"] == []
    path = tmp_path / "oul-085-oul-048-validation.json"
    audit.write_retry_repair(path, payload)
    assert (
        main(
            [
                "--task",
                "OUL-085",
                "--source",
                "OUL-048",
                "--check",
                "--report",
                str(path),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "OUL-085" in out
    assert payload["status"] == "passed"
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_wrong_source_or_cohort_fails() -> None:
    assert main(["--task", "OUL-049", "--source", "OUL-009", "--cohort", "C", "--check"]) == 1
    assert main(["--task", "OUL-049", "--source", "OUL-011", "--cohort", "A", "--check"]) == 1


def test_check_or_write_is_required() -> None:
    assert main(["--task", "OUL-049", "--source", "OUL-011", "--cohort", "C"]) == 2


def test_write_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "oul-049-oul-011-validation.json"
    payload = audit.build_retry_repair_payload(
        task_id="OUL-049",
        source_task_id="OUL-011",
        cohort="C",
    )
    audit.write_retry_repair(path, payload)
    report = audit.check_committed_repair(
        task_id="OUL-049",
        source_task_id="OUL-011",
        cohort="C",
        report_path=path,
    )
    assert report["repair_completed"] is True
    assert report["cohort_complete"] is False
