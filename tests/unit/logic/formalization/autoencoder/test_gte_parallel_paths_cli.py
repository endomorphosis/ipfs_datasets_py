"""Only synthetic subprocess workers exercise the dependency-free JSON CLI."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts/ops/autoencoder/run_gte_parallel_paths.py"
SPEC = importlib.util.spec_from_file_location("gte_parallel_paths_cli_under_test", SCRIPT)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def config(tmp_path):
    folder = tmp_path / "configuration"
    folder.mkdir()
    jobs = [{"lane_id": lane, "dimension": dimension,
             "runtime_id": "synthetic:" + lane, "representation_id": "synthetic-representation:" + lane,
             "checkpoint_sha256": str(index + 1) * 64,
             "state_directory": lane + "/state", "output_directory": lane + "/output",
             "command": [sys.executable, "-c", "import json,os; from pathlib import Path; "
                         "Path(os.environ['GTE_PATH_STATE_DIRECTORY'],'marker.json').write_text("
                         "json.dumps({k:v for k,v in os.environ.items() if k.startswith('GTE_PATH_')})); "
                         "print('synthetic worker')"]}
            for index, (lane, dimension) in enumerate((('legacy_8d', 8), ('source_384d', 384), ('multilingual_768d', 768)))]
    payload = {"schema": subject.JOBS_SCHEMA, "jobs": jobs}
    path = folder / "jobs.json"
    path.write_text(json.dumps(payload))
    return path, payload


def cli(tmp_path, jobs_file, report_file, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--jobs-file", str(jobs_file),
                           "--report-file", str(report_file), *extra], cwd=tmp_path,
                          capture_output=True, text=True, timeout=15)


def test_cli_dispatches_synthetic_jobs_with_paths_relative_to_configuration(tmp_path):
    path, payload = config(tmp_path)
    report_path = tmp_path / "dispatch.json"
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {"status": "success", "report_file": str(report_path)}
    report = json.loads(report_path.read_text())
    assert report["status"] == "success"
    assert report["model_numerics_verified"] is False
    for job, lane in zip(payload["jobs"], report["lanes"]):
        state = path.parent / job["state_directory"]
        output = path.parent / job["output_directory"]
        marker = json.loads((state / "marker.json").read_text())
        assert marker["GTE_PATH_STATE_DIRECTORY"] == str(state)
        assert marker["GTE_PATH_OUTPUT_DIRECTORY"] == str(output)
        assert marker["GTE_PATH_LANE"] == job["lane_id"]
        assert marker["GTE_PATH_DIMENSION"] == str(job["dimension"])
        assert lane["runtime_id"] == job["runtime_id"]
        assert not (tmp_path / job["state_directory"]).exists()


def test_cli_preserves_partial_failure_and_unavailable_768(tmp_path):
    path, payload = config(tmp_path)
    payload["jobs"][0]["command"][-1] = "raise SystemExit(7)"
    payload["jobs"][2].update(command=None, checkpoint_sha256=None)
    path.write_text(json.dumps(payload))
    report_path = tmp_path / "dispatch.json"
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 1
    assert "partial" in process.stderr
    report = json.loads(report_path.read_text())
    assert [lane["status"] for lane in report["lanes"]] == ["failed", "succeeded", "unavailable"]
    assert report["lanes"][2]["checkpoint_sha256"] is None
    assert not (path.parent / payload["jobs"][2]["output_directory"]).exists()


def test_existing_report_is_never_overwritten_and_no_worker_launches(tmp_path):
    path, payload = config(tmp_path)
    report_path = tmp_path / "dispatch.json"
    report_path.write_text("KEEP EXISTING REPORT")
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 2
    assert "fresh report-file" in process.stderr
    assert report_path.read_text() == "KEEP EXISTING REPORT"
    assert all(not (path.parent / job["state_directory"]).exists() for job in payload["jobs"])


@pytest.mark.parametrize("where", ["state", "output", "ancestor", "equal"])
def test_report_namespace_conflicts_are_rejected_before_launch(tmp_path, where):
    path, payload = config(tmp_path)
    lane = payload["jobs"][0]
    directory = path.parent / lane["state_directory" if where == "state" else "output_directory"]
    report_path = directory / "report.json" if where in ("state", "output") else directory.parent if where == "ancestor" else directory
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 2
    assert "namespace" in process.stderr
    assert not report_path.exists()
    assert all(not (path.parent / job["state_directory"]).exists() for job in payload["jobs"])


@pytest.mark.parametrize("invalid", ["duplicate", "nan", "overflow", "schema", "extra"])
def test_invalid_json_and_envelope_are_rejected(tmp_path, invalid):
    path, payload = config(tmp_path)
    if invalid == "duplicate": raw = '{"schema":"gte-parallel-path-jobs/v1","schema":"again","jobs":[]}'
    elif invalid == "nan": raw = '{"schema":"gte-parallel-path-jobs/v1","jobs":NaN}'
    elif invalid == "overflow": raw = '{"schema":"gte-parallel-path-jobs/v1","jobs":1e999}'
    elif invalid == "schema":
        payload["schema"] = "unsupported/v1"
        raw = json.dumps(payload)
    else:
        payload["unknown"] = True
        raw = json.dumps(payload)
    path.write_text(raw)
    report_path = tmp_path / "dispatch.json"
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 2
    assert "parallel dispatch failed:" in process.stderr
    assert "Traceback" not in process.stderr
    assert not report_path.exists()


@pytest.mark.parametrize("extra", [("--max-parallel", "0"), ("--timeout-seconds", "nan")])
def test_invalid_dispatch_settings_fail_before_report_reservation(tmp_path, extra):
    path, _ = config(tmp_path)
    report_path = tmp_path / "dispatch.json"
    process = cli(tmp_path, path, report_path, *extra)
    assert process.returncode == 2
    assert not report_path.exists()


def test_invalid_dimension_fails_before_report_reservation(tmp_path):
    path, payload = config(tmp_path)
    payload["jobs"][2]["dimension"] = 786
    path.write_text(json.dumps(payload))
    report_path = tmp_path / "dispatch.json"
    process = cli(tmp_path, path, report_path)
    assert process.returncode == 2
    assert "dimension differs" in process.stderr
    assert not report_path.exists()


def test_report_is_reserved_before_dispatch_and_command_is_not_reinterpreted(tmp_path, monkeypatch):
    path, payload = config(tmp_path)
    report_path = tmp_path / "dispatch.json"
    coordinator = subject._coordinator()
    seen = {}
    def dispatch(jobs, **kwargs):
        assert report_path.exists()
        assert report_path.read_bytes() == b""
        seen["jobs"] = jobs
        return {"status": "success"}
    monkeypatch.setattr(coordinator, "run_parallel_paths", dispatch)
    monkeypatch.setattr(subject, "_coordinator", lambda: coordinator)
    report, _ = subject.run_jobs_file(path, report_path)
    assert report["status"] == "success"
    assert [job["command"] for job in seen["jobs"]] == [job["command"] for job in payload["jobs"]]
    assert all(Path(job["state_directory"]).is_absolute() for job in seen["jobs"])


@pytest.mark.parametrize("error,exit_code", [(KeyboardInterrupt, 130), (OSError, 2)])
def test_interrupted_or_exceptional_dispatch_leaves_no_complete_report_claim(tmp_path, monkeypatch, capsys, error, exit_code):
    path, _ = config(tmp_path)
    report_path = tmp_path / "dispatch.json"
    coordinator = subject._coordinator()
    def dispatch(*args, **kwargs):
        raise error("injected dispatch failure")
    monkeypatch.setattr(coordinator, "run_parallel_paths", dispatch)
    monkeypatch.setattr(subject, "_coordinator", lambda: coordinator)
    with pytest.raises(SystemExit) as caught:
        subject.main(["--jobs-file", str(path), "--report-file", str(report_path)])
    assert caught.value.code == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "parallel dispatch" in captured.err
    assert report_path.exists() and report_path.read_bytes() == b""
