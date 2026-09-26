"""Feedback control tests; stub transitions here are not native repair evidence."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal.feedback_cycle import (
    FeedbackCycleError, PhaseJournal, check_storage, exclusive_loop, next_phase,
    queue_observation, run_phase,
)
from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE


def observation(counts, *, eligible=False):
    return {"counts": counts, "has_eligible_task": eligible}


def test_ready_repairs_are_drained_before_training_the_next_code_revision():
    prior = {"input_identity": "old", "discrepancies": 4}
    assert next_phase(observation({"ready": 4}, eligible=True), "new", prior) == "supervise"
    assert next_phase(observation({"completed": 4}), "new", prior) == "train"
    assert next_phase(observation({}), "first", None) == "train"


@pytest.mark.parametrize("status", ["blocked", "failed", "quarantined", "cancelled", "skipped", "rejected", "in_progress", "claimed", "running", "unknown"])
def test_empty_ready_queue_does_not_hide_unresolved_or_unknown_state(status):
    with pytest.raises(FeedbackCycleError):
        next_phase(observation({status: 1}), "same", {"input_identity": "same", "discrepancies": 0})


@pytest.mark.parametrize("status", ["proposed", "admitted", "pending", "ready", "todo", "queued", "retrying"])
def test_native_readiness_not_status_names_controls_dispatch(status):
    # Waiting must neither train nor reset a retry, even with new model input.
    assert next_phase(observation({status: 1}), "new-input", None) == "waiting"
    assert next_phase(observation({status: 1}, eligible=True), "new-input", None) == "supervise"


def test_counts_cannot_substitute_for_native_readiness():
    with pytest.raises(FeedbackCycleError, match="eligibility is required"):
        next_phase({"counts": {"ready": 1}}, "new", None)
    with pytest.raises(FeedbackCycleError, match="conflicts"):
        next_phase(observation({"completed": 1}, eligible=True), "new", None)


def test_observation_reads_native_backoff_without_writing_lifecycle():
    class Source:
        def list_tasks(self, *, cursor, limit):
            task = SimpleNamespace(status="retrying", body={"board_namespace": NAMESPACE})
            return SimpleNamespace(tasks=(task,), revision=82, next_cursor="")

        def ready_tasks(self, *, limit):
            assert limit == 1
            return SimpleNamespace(tasks=(), revision=82)

        def snapshot(self):
            return SimpleNamespace(revision=82)

    assert queue_observation(Source()) == {"counts": {"retrying": 1}, "revision": 82,
                                          "has_eligible_task": False}


def test_concurrent_queue_change_refuses_mixed_observation():
    source = SimpleNamespace(
        list_tasks=lambda **kwargs: SimpleNamespace(tasks=(), next_cursor="", revision=1),
        ready_tasks=lambda **kwargs: SimpleNamespace(tasks=(), revision=2),
        snapshot=lambda: SimpleNamespace(revision=2),
    )
    with pytest.raises(FeedbackCycleError, match="changed during observation"):
        queue_observation(source)


def test_huggingface_child_flags_forward_schedule_queue(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "autoformal_feedback_under_test", scripts / "run_autoformal_feedback_loop.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flags = module.huggingface_child_flags(
        SimpleNamespace(
            huggingface_package=Path("/hf"),
            pointer=Path("/pointer.json"),
            board=Path("/board.md"),
            schedule_queue=Path("/queue.json"),
            max_tokens=50000,
            max_validation_seconds=600,
        )
    )
    assert flags[flags.index("--huggingface-package") + 1] == "/hf"
    assert flags[flags.index("--schedule-queue") + 1] == "/queue.json"
    assert flags[flags.index("--max-tokens") + 1] == "50000"
    assert "--jsonl" not in flags


def test_no_busy_retraining_or_claim_of_model_improvement_on_unchanged_input():
    prior = {"input_identity": "same", "discrepancies": 0, "optimizer_accepted_epochs": 0}
    assert next_phase(observation({"completed": 2}), "same", prior) == "idle"
    prior["discrepancies"] = 1
    with pytest.raises(FeedbackCycleError, match="discrepancies"):
        next_phase(observation({"completed": 2}), "same", prior)


def test_phase_journal_restarts_without_reopening_uncertain_work(tmp_path):
    journal = PhaseJournal(tmp_path / "loop.duckdb")
    try:
        journal.start("train", "code-and-source", [sys.executable, "worker.py"], tmp_path / "phase.log", phase_id="phase-1")
    finally:
        journal.close()
    journal = PhaseJournal(tmp_path / "loop.duckdb")
    try:
        with pytest.raises(FeedbackCycleError, match="reconciliation"):
            journal.require_no_interrupted_phase()
        journal.finish("phase-1", "finished", {"candidate_version_id": "private-1", "discrepancies": 2,
                                               "optimizer_accepted_epochs": 0})
        assert journal.previous_training()["input_identity"] == "code-and-source"
        journal.require_no_interrupted_phase()
        with pytest.raises(FeedbackCycleError, match="terminal"):
            journal.finish("phase-1", "finished", {})
    finally:
        journal.close()


def test_runtime_has_one_owner_and_lock_file_is_not_owner_authority(tmp_path):
    with exclusive_loop(tmp_path):
        with pytest.raises(FeedbackCycleError, match="another feedback runner"):
            with exclusive_loop(tmp_path):
                pytest.fail("two owners admitted")
    assert (tmp_path / "feedback-loop.lock").exists()
    with exclusive_loop(tmp_path):
        pass  # A stale pathname must not prohibit a new owner.


def test_storage_refusal_retains_existing_artifacts(tmp_path):
    artifact = tmp_path / "retained.txt"
    artifact.write_text("retain this evidence")
    with pytest.raises(FeedbackCycleError, match="storage budget"):
        check_storage(tmp_path, 1_000_000_000, reserve=1_000_000_000)
    assert artifact.read_text() == "retain this evidence"


def test_real_subprocess_has_terminal_status_and_retained_log(tmp_path):
    result = run_phase([sys.executable, "-c", "print('child finished')"], cwd=tmp_path,
                       log=tmp_path / "phase.log", runtime=tmp_path, storage_limit=50_000_000_000,
                       wall_timeout=10, poll_seconds=0.01)
    assert result["returncode"] == 0 and result["launched"] and not result["stop_reason"]
    assert (tmp_path / "phase.log").read_text().strip() == "child finished"


def test_wall_timeout_terminates_only_the_owned_child(tmp_path):
    result = run_phase([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path,
                       log=tmp_path / "phase.log", runtime=tmp_path, storage_limit=50_000_000_000,
                       wall_timeout=0.05, poll_seconds=0.01)
    assert result["returncode"] is not None and result["returncode"] != 0
    assert result["stop_reason"] == "phase_wall_timeout"


def test_stop_marker_does_not_start_a_child(tmp_path):
    (tmp_path / "STOP").touch()
    result = run_phase(["intentionally-absent-executable"], cwd=tmp_path, log=tmp_path / "phase.log",
                       runtime=tmp_path, storage_limit=50_000_000_000, wall_timeout=1)
    assert not result["launched"]
    assert not (tmp_path / "phase.log").exists()


def loop_entry(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    scripts = root / "scripts/ops/legal_ir"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("feedback_loop_under_test", scripts / "run_autoformal_feedback_loop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cycle_receipt_requires_lineage_and_nonempty_fresh_observations(tmp_path, monkeypatch):
    runner = loop_entry(monkeypatch)
    receipt = tmp_path / "cycle.json"
    report = {"cycle_id": "cycle-1", "code_identity": "code-1", "stage": "native_training_and_repair_queue",
              "admitted": False, "formalized": False, "production_promotion": False,
              "candidate_version_id": "private-v1", "model_identity": "weights-v1",
              "optimizer_accepted_epochs": 0, "agreement": [{"rows": [{"agrees": True}, {"agrees": False}]}]}
    receipt.write_text(json.dumps(report))
    result = runner.cycle_result(receipt, "cycle-1", "code-1")
    assert result["discrepancies"] == 1 and result["optimizer_accepted_epochs"] == 0
    with pytest.raises(ValueError, match="another execution"):
        runner.cycle_result(receipt, "cycle-other", "code-1")
    report["agreement"] = []
    receipt.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="empty compiler replay"):
        runner.cycle_result(receipt, "cycle-1", "code-1")


def test_preflight_checks_sealed_files_outside_the_manual_protected_list(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import validator_profile
    runner = loop_entry(monkeypatch)
    original, candidate = tmp_path / "source", tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    (original / "sealed.py").write_text("new source\n")
    (candidate / "sealed.py").write_text("old source\n")
    monkeypatch.setattr(runner, "ROOT", original)
    monkeypatch.setattr(runner, "PROTECTED", ())
    monkeypatch.setattr(validator_profile, "SEALED_FILES", ("sealed.py",))
    monkeypatch.setattr(validator_profile, "require_deployment", lambda _: None)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda args, **kw:
                        str(candidate) if "rev-parse" in args else b"")
    with pytest.raises(ValueError, match="current protected harness: sealed.py"):
        runner.repository_preflight(candidate)


@pytest.mark.parametrize("selection", ["ready", "absent", "empty_queue"])
def test_explicit_task_loop_propagates_selection_and_never_falls_back(tmp_path, monkeypatch, selection):
    """Orchestration unit test; the stub blocks a temporary task, never completes it."""
    import subprocess
    import ipfs_accelerate_py
    import ipfs_datasets_py.logic.autoformal.feedback_cycle as control
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import enqueue_repairs, repair_packets

    repo = tmp_path / "candidate"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=repo,
                       check=True, capture_output=True)
    git("-c", "init.templateDir=", "init")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "-c", "commit.gpgsign=false",
        "commit", "--allow-empty", "-m", "unit fixture")
    template = tmp_path / "job.json"
    template.write_text("{}")
    database = tmp_path / "control.duckdb"
    with DatabaseTaskSource(database) as source:
        if selection != "empty_queue":
            packets = repair_packets({"rows": [
                {"id": "a", "text": "The clerk shall retain files.", "agrees": False, "reason": "compiler_abstain"},
                {"id": "b", "text": "The officer shall preserve records.", "agrees": False, "reason": "compiler_abstain"},
            ]}, release_id="test", code_identity="test", model_identity="test")
            enqueue_repairs(source, packets, packet_directory=tmp_path / "packets")
            first, target = source.ready_tasks(limit=2).tasks
        before = source.snapshot().to_dict()
    requested = target.task_alias if selection == "ready" else "AFTD-" + "0" * 20
    # The populated adapter carries an in-memory repository-tree annotation.
    # Compare equally bound reopened adapters plus the durable task records,
    # not that transient annotation against a default new adapter.
    with DatabaseTaskSource(database, install_schema=False) as source:
        before = source.snapshot().to_dict()
        before_tasks = [task.to_dict() for task in source.list_tasks(limit=100).tasks]
    runner = loop_entry(monkeypatch)
    monkeypatch.setattr(runner, "repository_preflight", lambda _: None)  # Temporary unit repository only.
    monkeypatch.setattr(runner, "code_identity", lambda _: "unit-code")
    preflight = runner.preflight_next_repair
    monkeypatch.setattr(runner, "preflight_next_repair", lambda source, repository, **kwargs:
                        preflight(source, repository, probe=lambda *a, **k: {"passed": True}, **kwargs))
    commands = []
    def fake_phase(command, **kwargs):
        assert selection == "ready", "unavailable selection must never dispatch or train"
        commands.append(command)
        assert command[1].endswith("run_autoformal_supervisor.py")
        assert command[command.index("--task-id") + 1] == requested
        assert command.index("--task-id") < command.index("supervise")
        with DatabaseTaskSource(database, install_schema=False) as source:
            record = source.get(target.task_cid)
            source.compare_and_set_status(record.task_cid, record.revision, "blocked",
                                          receipt={"operation": "unit-test-only"})
        return {"returncode": 0, "stop_reason": "", "launched": False, "unit_stub": True}
    monkeypatch.setattr(control, "run_phase", fake_phase)
    assert runner.main([
        "--accelerate-root", str(Path(ipfs_accelerate_py.__file__).resolve().parent.parent),
        "--repository-root", str(repo), "--runtime-root", str(tmp_path), "--database", str(database),
        "--job-template", str(template), "--task-id", requested, "--max-phases", "1", "--implement",
    ]) == 0
    with DatabaseTaskSource(database, install_schema=False) as source:
        if selection == "ready":
            assert len(commands) == 1
            assert source.get(first.task_cid).status == "ready"
            assert source.get(target.task_cid).status == "blocked"
        else:
            assert not commands
            assert source.snapshot().to_dict() == before
            assert [task.to_dict() for task in source.list_tasks(limit=100).tasks] == before_tasks
