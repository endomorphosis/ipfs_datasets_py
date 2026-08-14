"""Unit tests for the Open US Law scrape-cohort runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_runner():
    path = _repo_root() / "scripts" / "ops" / "legal_data" / "run_open_us_law_scrape_cohort.py"
    spec = importlib.util.spec_from_file_location("run_open_us_law_scrape_cohort_oul049", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()
main = runner.main


def test_fixture_only_check_proves_software_and_not_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--fixture-only", "--cohort", "C", "--check"]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "software_behavior_proven=True" in out
    assert "cohort_complete=False" in out
    assert "fixture_only=True" in out


def test_fixture_only_json_never_authorizes_publication(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--fixture-only", "--cohort", "C", "--check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["cohort"] == "C"
    assert payload["cohort_complete"] is False
    assert payload["fixture_execution"] is True
    assert payload["fixture_proves_cohort_completion"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["software_behavior_proven"] is True
    assert payload["jurisdictions"] == ["FL", "GA", "HI", "ID"]
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_require_live_without_declared_report_fails(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "cohort_C.json"
    assert main(["--cohort", "C", "--require-live", "--check", "--report", str(missing)]) == 1
    text = capsys.readouterr().err + capsys.readouterr().out
    assert "FAILED" in text or "require-live" in text.lower() or "missing" in text.lower()


def test_fixture_only_and_require_live_are_exclusive() -> None:
    assert main(["--fixture-only", "--require-live", "--cohort", "C", "--check"]) == 2


def test_check_is_required() -> None:
    assert main(["--fixture-only", "--cohort", "C"]) == 2


def test_unknown_cohort_fails() -> None:
    assert main(["--fixture-only", "--cohort", "Z", "--check"]) == 1


def test_live_and_fixture_flags_required() -> None:
    assert main(["--cohort", "C", "--check"]) == 2
