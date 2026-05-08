import asyncio
import importlib.util
import json
import sys
from pathlib import Path


def _load_runner_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "run_all_state_legal_corpora_agentic.py"
    spec = importlib.util.spec_from_file_location("run_all_state_legal_corpora_agentic", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_all_state_agentic_full_corpus_runs_guard_audit_before_cycles(tmp_path, monkeypatch):
    runner = _load_runner_module()
    events = []

    def _fake_audit(*, states):
        events.append(("audit", tuple(states)))
        return {
            "status": "pass",
            "states_checked": len(states),
            "missing_states": [],
            "error_count": 0,
            "warning_count": 0,
            "findings": [],
        }

    async def _fake_run_corpus(**kwargs):
        events.append(("run", kwargs["corpus"]))
        return {
            "status": "completed",
            "summary": {"latest_cycle": {"passed": True}},
            "output_dir": str(tmp_path / kwargs["corpus"]),
        }

    monkeypatch.setattr(runner, "_run_state_laws_full_corpus_guard_audit", _fake_audit)
    monkeypatch.setattr(runner, "_run_corpus", _fake_run_corpus)

    args = runner._build_arg_parser().parse_args(
        [
            "--full-corpus-mode",
            "--corpora",
            "state_laws",
            "--states",
            "AL,DC",
            "--output-root",
            str(tmp_path),
            "--max-cycles",
            "1",
        ]
    )

    assert asyncio.run(runner._main_async(args)) == 0
    assert events == [("audit", ("AL", "DC")), ("run", "state_laws")]

    summary = json.loads((tmp_path / "aggregated_summary.json").read_text(encoding="utf-8"))
    assert summary["state_laws_full_corpus_guard_audit"]["status"] == "pass"
    assert summary["state_laws_full_corpus_guard_audit"]["states_checked"] == 2
    assert summary["status"] == "success"


def test_run_all_state_agentic_full_corpus_guard_audit_blocks_cycles(tmp_path, monkeypatch):
    runner = _load_runner_module()

    def _fake_audit(*, states):
        return {
            "status": "fail",
            "states_checked": 0,
            "missing_states": list(states),
            "error_count": 1,
            "warning_count": 0,
            "findings": [{"severity": "error", "detail": "unguarded seed return"}],
        }

    async def _fail_run_corpus(**kwargs):
        raise AssertionError("corpus daemon should not run after a failed guard audit")

    monkeypatch.setattr(runner, "_run_state_laws_full_corpus_guard_audit", _fake_audit)
    monkeypatch.setattr(runner, "_run_corpus", _fail_run_corpus)

    args = runner._build_arg_parser().parse_args(
        [
            "--full-corpus-mode",
            "--corpora",
            "state_laws",
            "--states",
            "AZ",
            "--output-root",
            str(tmp_path),
        ]
    )

    assert asyncio.run(runner._main_async(args)) == 2

    summary = json.loads((tmp_path / "aggregated_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed_preflight"
    assert summary["reason"] == "state_laws_full_corpus_guard_audit_failed"
    assert summary["runs"] == {}


def test_run_all_state_agentic_preflight_only_exits_after_guard_audit(tmp_path, monkeypatch):
    runner = _load_runner_module()
    events = []

    def _fake_audit(*, states):
        events.append(("audit", tuple(states)))
        return {
            "status": "pass",
            "states_checked": len(states),
            "missing_states": [],
            "error_count": 0,
            "warning_count": 0,
            "findings": [],
        }

    async def _fail_run_corpus(**kwargs):
        raise AssertionError("preflight-only mode should not start corpus daemon cycles")

    monkeypatch.setattr(runner, "_run_state_laws_full_corpus_guard_audit", _fake_audit)
    monkeypatch.setattr(runner, "_run_corpus", _fail_run_corpus)

    args = runner._build_arg_parser().parse_args(
        [
            "--full-corpus-mode",
            "--preflight-only",
            "--corpora",
            "state_laws",
            "--states",
            "NY",
            "--output-root",
            str(tmp_path),
        ]
    )

    assert asyncio.run(runner._main_async(args)) == 0
    assert events == [("audit", ("NY",))]

    summary = json.loads((tmp_path / "aggregated_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "preflight_passed"
    assert summary["preflight_only"] is True
    assert summary["runs"] == {}


def test_run_all_state_agentic_bounded_mode_skips_guard_audit(tmp_path, monkeypatch):
    runner = _load_runner_module()
    events = []

    def _fail_audit(*, states):
        raise AssertionError("bounded runs should not invoke the full-corpus guard audit")

    async def _fake_run_corpus(**kwargs):
        events.append(kwargs["corpus"])
        return {
            "status": "completed",
            "summary": {"latest_cycle": {"passed": True}},
            "output_dir": str(tmp_path / kwargs["corpus"]),
        }

    monkeypatch.setattr(runner, "_run_state_laws_full_corpus_guard_audit", _fail_audit)
    monkeypatch.setattr(runner, "_run_corpus", _fake_run_corpus)

    args = runner._build_arg_parser().parse_args(
        [
            "--corpora",
            "state_laws",
            "--states",
            "CA",
            "--output-root",
            str(tmp_path),
            "--max-statutes",
            "5",
        ]
    )

    assert asyncio.run(runner._main_async(args)) == 0
    assert events == ["state_laws"]

    summary = json.loads((tmp_path / "aggregated_summary.json").read_text(encoding="utf-8"))
    assert "state_laws_full_corpus_guard_audit" not in summary
    assert summary["status"] == "success"
