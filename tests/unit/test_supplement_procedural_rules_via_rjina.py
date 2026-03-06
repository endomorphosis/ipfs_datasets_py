from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "supplement_procedural_rules_via_rjina.py"
    spec = importlib.util.spec_from_file_location("supplement_procedural_rules_via_rjina", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_row() -> dict:
    return {
        "jurisdiction_code": "MI",
        "jurisdiction_name": "Michigan",
        "territory": False,
        "procedure_family": "civil_procedure",
        "ipfs_cid": None,
        "name": "Michigan Court Rules",
        "titleName": None,
        "chapterName": None,
        "sectionName": "Michigan Court Rules",
        "sourceUrl": "https://www.courts.michigan.gov/rules-administrative-orders-and-jury-instructions/",
        "code_name": "supplemental_procedural_rules_rjina",
        "text": None,
        "record": {
            "source": "r.jina.ai",
            "seed_url": "https://www.courts.michigan.gov/",
            "label": "Michigan Court Rules",
            "target_url": "https://www.courts.michigan.gov/rules-administrative-orders-and-jury-instructions/",
        },
    }


def test_run_no_post_cleanup(tmp_path) -> None:
    module = _load_module()

    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"supported_with_no_procedural_matches": []}), encoding="utf-8")
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(_base_row()) + "\n", encoding="utf-8")

    supplemental_out = tmp_path / "supplemental.jsonl"
    merged_out = tmp_path / "merged.jsonl"

    report = module.run(
        summary_path=summary,
        output_jsonl=supplemental_out,
        merged_output_jsonl=merged_out,
        base_jsonl=base,
        sleep_s=0.0,
        target_states=[],
        post_cleanup_merged=False,
        post_cleanup_require_equal_coverage=True,
    )

    assert report["status"] == "success"
    assert report["supplemental_records"] == 0
    assert report["merged_count"] == 1
    assert report["post_cleanup_invoked"] is False
    assert report["post_cleanup_report"] is None
    assert report["post_cleanup_exit_code"] is None


def test_run_post_cleanup_invokes_subprocess(tmp_path, monkeypatch) -> None:
    module = _load_module()

    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"supported_with_no_procedural_matches": []}), encoding="utf-8")
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(_base_row()) + "\n", encoding="utf-8")

    supplemental_out = tmp_path / "supplemental.jsonl"
    merged_out = tmp_path / "merged.jsonl"

    calls = []

    class _Result:
        returncode = 0

    def _fake_run(cmd, capture_output, text):
        calls.append((cmd, capture_output, text))
        return _Result()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    report = module.run(
        summary_path=summary,
        output_jsonl=supplemental_out,
        merged_output_jsonl=merged_out,
        base_jsonl=base,
        sleep_s=0.0,
        target_states=[],
        post_cleanup_merged=True,
        post_cleanup_require_equal_coverage=True,
    )

    assert report["post_cleanup_invoked"] is True
    assert report["post_cleanup_exit_code"] == 0
    assert report["post_cleanup_report"].endswith(".cleanup_report.json")

    assert len(calls) == 1
    cmd, capture_output, text = calls[0]
    assert capture_output is True
    assert text is True
    assert "cleanup_procedural_rules_merged.py" in cmd[1]
    assert "--in-place" in cmd
    assert "--require-equal-coverage" in cmd


def test_run_post_cleanup_no_require_equal_coverage_flag(tmp_path, monkeypatch) -> None:
    module = _load_module()

    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"supported_with_no_procedural_matches": []}), encoding="utf-8")
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(_base_row()) + "\n", encoding="utf-8")

    supplemental_out = tmp_path / "supplemental.jsonl"
    merged_out = tmp_path / "merged.jsonl"

    calls = []

    class _Result:
        returncode = 0

    def _fake_run(cmd, capture_output, text):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.run(
        summary_path=summary,
        output_jsonl=supplemental_out,
        merged_output_jsonl=merged_out,
        base_jsonl=base,
        sleep_s=0.0,
        target_states=[],
        post_cleanup_merged=True,
        post_cleanup_require_equal_coverage=False,
    )

    assert len(calls) == 1
    cmd = calls[0]
    assert "--in-place" in cmd
    assert "--require-equal-coverage" not in cmd


def test_run_post_cleanup_error_fail_fast(tmp_path, monkeypatch) -> None:
    module = _load_module()

    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"supported_with_no_procedural_matches": []}), encoding="utf-8")
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(_base_row()) + "\n", encoding="utf-8")

    supplemental_out = tmp_path / "supplemental.jsonl"
    merged_out = tmp_path / "merged.jsonl"

    class _Result:
        returncode = 2

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: _Result())

    report = module.run(
        summary_path=summary,
        output_jsonl=supplemental_out,
        merged_output_jsonl=merged_out,
        base_jsonl=base,
        sleep_s=0.0,
        target_states=[],
        post_cleanup_merged=True,
        post_cleanup_require_equal_coverage=True,
        fail_on_post_cleanup_error=True,
    )

    assert report["status"] == "error"
    assert report["post_cleanup_invoked"] is True
    assert report["post_cleanup_exit_code"] == 2
    assert report["post_cleanup_ok"] is False


def test_run_post_cleanup_error_non_fail_mode(tmp_path, monkeypatch) -> None:
    module = _load_module()

    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"supported_with_no_procedural_matches": []}), encoding="utf-8")
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(_base_row()) + "\n", encoding="utf-8")

    supplemental_out = tmp_path / "supplemental.jsonl"
    merged_out = tmp_path / "merged.jsonl"

    class _Result:
        returncode = 2

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: _Result())

    report = module.run(
        summary_path=summary,
        output_jsonl=supplemental_out,
        merged_output_jsonl=merged_out,
        base_jsonl=base,
        sleep_s=0.0,
        target_states=[],
        post_cleanup_merged=True,
        post_cleanup_require_equal_coverage=True,
        fail_on_post_cleanup_error=False,
    )

    assert report["status"] == "success"
    assert report["post_cleanup_invoked"] is True
    assert report["post_cleanup_exit_code"] == 2
    assert report["post_cleanup_ok"] is False
