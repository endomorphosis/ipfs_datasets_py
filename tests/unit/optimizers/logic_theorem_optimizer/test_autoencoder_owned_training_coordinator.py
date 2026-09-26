"""Durable coordinator operations with injected workers and no native launch."""
from __future__ import annotations

from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    autoencoder_daemon_operation_journal as journals,
    autoencoder_training_coordinator as coordinator,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _fixture_worker, _prepare,
)


def _binding(registry):
    return {
        "schema": "autoencoder-campaign-training-request-v1",
        "owner": {"database_path": str(registry.database_path),
                  "artifact_root": str(registry.artifact_root)},
        "request_artifact": {"sha256": "a" * 64, "bytes": 1},
    }


def _run(registry, specs, journal, **kwargs):
    options = {
        "operation_journal": journal, "worker_id": "owned-fixture", "timeout_seconds": 60,
        "before_claim": lambda spec: None, "before_prepare": lambda spec, result: None,
        "before_submit": lambda spec, lease, artifact: None,
        "executor_factory": ImmediateExecutor, "worker_function": _fixture_worker,
        "max_workers": 1,
    }
    options.update(kwargs)
    return coordinator._run_owned_training_jobs(registry, specs, **options)


def _slot(spec, kind, ordinal=None):
    return coordinator._owned_operation_slot(spec.run_id, kind, ordinal)


def test_owned_coordinator_reuses_acceptance_and_orders_resource_callbacks(tmp_path):
    events = []
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)

        def admit(job):
            assert registry.get_run(job.run_id)["status"] == "queued"
            assert not Path(job.output_directory).exists()
            events.append("admit")

        def worker(job):
            assert events == ["admit", "start"]
            events.append("worker")
            return _fixture_worker(job)

        def start(job, lease, artifact):
            assert registry.get_run(job.run_id)["status"] == "running"
            assert lease["worker_id"] == "owned-fixture"
            assert set(artifact) == {"path", "sha256", "bytes"}
            assert Path(artifact["path"]) == registry.artifact_path(
                {key: artifact[key] for key in ("sha256", "bytes")})
            events.append("start")

        def prepare(job, returned):
            assert registry.get_run(job.run_id)["status"] == "running"
            assert returned["execution_mode"] == "injected_test"
            assert events == ["admit", "start", "worker"]
            events.append("prepare")

        def terminal(job, result):
            assert result["status"] == "completed"
            assert registry.get_run_completion(job.run_id) is not None
            assert not journal.pending()
            events.append("terminal")

        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, before_claim=admit,
                          before_prepare=prepare, before_submit=start,
                          after_terminal=terminal, worker_function=worker)
            assert events == ["admit", "start", "worker", "prepare", "terminal"]
            assert report["execution_mode"] == "injected_test"
            assert report["operation_journal_used"] is True
            assert report["recovery_required"] is False
            assert report["failed"] == report["undispatched_run_ids"] == []
            assert report["mutation_retry_count"] is report["resolved_operation_count"] is None
            operations = journal.operations()
            assert set(operations) == {_slot(spec, "claim"), _slot(spec, "renew", 1),
                                      _slot(spec, "renew", 2), _slot(spec, "complete")}
            assert not journal.pending()
            assert operations[_slot(spec, "claim")]["payload"]["worker_id"] == "owned-fixture"
            completion = registry.get_run_completion(spec.run_id)
            assert completion is not None
            assert completion["run"]["result"]["execution_mode"] == "injected_test"
            assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("method_name", ["claim_run", "renew_lease", "complete_run", "fail_run"])
def test_journalled_response_loss_resolves_without_worker_repetition(tmp_path, monkeypatch, method_name):
    calls, trained = [], []
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        original = getattr(registry, method_name)

        def lost_reply(*args, **kwargs):
            calls.append(args[0])
            result = original(*args, **kwargs)
            if len(calls) == 1:
                raise OSError("reply lost after commit")
            return result

        def worker(job):
            trained.append(job.run_id)
            if method_name == "fail_run":
                raise RuntimeError("injected failure")
            return _fixture_worker(job)

        monkeypatch.setattr(registry, method_name, lost_reply)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, worker_function=worker)
            assert trained == [spec.run_id]
            assert len(calls) == (2 if method_name == "renew_lease" else 1)
            assert len(set(calls)) == len(calls)
            assert not journal.pending()
            assert report["recovery_required"] is False
            assert registry.get_run(spec.run_id)["status"] == (
                "failed" if method_name == "fail_run" else "completed")


def test_pending_completion_reopens_and_resolves_without_fail_or_worker_repeat(tmp_path, monkeypatch):
    database, artifacts, path = tmp_path / "owner.duckdb", tmp_path / "cas", tmp_path / "journal.json"
    trained = []
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare(registry, tmp_path)
        binding = _binding(registry)
        original_complete, original_resolve = registry.complete_run, registry.resolve_operation
        lost = False

        def complete(*args, **kwargs):
            nonlocal lost
            original_complete(*args, **kwargs)
            lost = True
            raise OSError("committed reply unavailable")

        def resolve(operation_id, command, payload):
            if lost and command == "CompleteRun":
                raise OSError("completion lookup unavailable")
            return original_resolve(operation_id, command, payload)

        def worker(job):
            trained.append(job.run_id)
            return _fixture_worker(job)

        monkeypatch.setattr(registry, "complete_run", complete)
        monkeypatch.setattr(registry, "resolve_operation", resolve)
        monkeypatch.setattr(registry, "fail_run", lambda *a, **k: pytest.fail("cannot fail uncertain completion"))
        with journals.DurableDaemonOperationJournal(path, binding) as journal:
            report = _run(registry, [spec], journal, worker_function=worker,
                          after_terminal=lambda *a: pytest.fail("uncertain completion cannot qualify"))
            assert report["recovery_required"] is True
            assert report["completed"] == []
            assert report["failed"][0]["failure_recorded"] is False
            assert set(journal.pending()) == {_slot(spec, "complete")}
            assert registry.get_run(spec.run_id)["status"] == "completed"
    with AutoencoderRegistry(database, artifacts) as registry:
        monkeypatch.setattr(registry, "claim_run", lambda *a, **k: pytest.fail("recovery cannot reclaim"))
        monkeypatch.setattr(registry, "complete_run", lambda *a, **k: pytest.fail("resolve cannot send completion"))
        with journals.DurableDaemonOperationJournal(path, binding, create=False) as journal:
            receipt = journal.resolve(registry, _slot(spec, "complete"))
            assert receipt["status"] == "completed"
            assert not journal.pending()
            assert registry.get_run_completion(spec.run_id) is not None
            assert trained == [spec.run_id]


@pytest.mark.parametrize("command,method", [("ClaimRun", "claim_run"), ("RenewLease", "renew_lease")])
def test_pending_nonterminal_mutation_blocks_failure_and_later_dispatch(tmp_path, monkeypatch, command, method):
    trained = []
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        first, second = _prepare(registry, tmp_path), _prepare(registry, tmp_path, index=1)
        original_method, original_resolve = getattr(registry, method), registry.resolve_operation
        lost = False

        def mutate(*args, **kwargs):
            nonlocal lost
            original_method(*args, **kwargs)
            lost = True
            raise OSError("mutation reply unavailable")

        def resolve(operation_id, kind, payload):
            if lost and kind == command:
                raise OSError("lookup unavailable")
            return original_resolve(operation_id, kind, payload)

        def worker(job):
            trained.append(job.run_id)
            return _fixture_worker(job)

        monkeypatch.setattr(registry, method, mutate)
        monkeypatch.setattr(registry, "resolve_operation", resolve)
        monkeypatch.setattr(registry, "fail_run", lambda *a, **k: pytest.fail("pending mutation must not fail"))
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [first, second], journal, worker_function=worker)
            assert report["recovery_required"] is True
            assert report["undispatched_run_ids"] == [second.run_id]
            assert trained == ([] if command == "ClaimRun" else [first.run_id])
            assert registry.get_run(first.run_id)["status"] == "running"
            assert registry.get_run(second.run_id)["status"] == "queued"
            assert len(journal.pending()) == 1


def test_lookup_only_resolution_cannot_send_an_uncommitted_intent(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            monkeypatch.setattr(registry, "claim_run", lambda *a, **k: (_ for _ in ()).throw(OSError("before commit")))
            with pytest.raises(OSError, match="before commit"):
                journal.invoke(registry, _slot(spec, "claim"), "ClaimRun", {
                    "run_id": spec.run_id, "worker_id": "owned-fixture", "lease_seconds": 300})
            before = journal.path.read_bytes()
            monkeypatch.setattr(registry, "claim_run", lambda *a, **k: pytest.fail("resolve must not send"))
            assert journal.resolve(registry, _slot(spec, "claim")) is None
            assert journal.path.read_bytes() == before
            assert registry.get_run(spec.run_id)["status"] == "queued"
            with pytest.raises(journals.DaemonOperationJournalError, match="unknown"):
                journal.resolve(registry, "missing-slot")
            with pytest.raises(coordinator.TrainingCoordinationError, match="recovery"):
                _run(registry, [spec], journal,
                     before_claim=lambda job: pytest.fail("pending journal must precede admission"))


def test_resolved_claim_from_old_owner_never_authorizes_new_execution(tmp_path, monkeypatch):
    database, artifacts, path = tmp_path / "owner.duckdb", tmp_path / "cas", tmp_path / "journal.json"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare(registry, tmp_path)
        binding = _binding(registry)
        with journals.DurableDaemonOperationJournal(path, binding) as journal:
            original = journal.invoke(registry, _slot(spec, "claim"), "ClaimRun", {
                "run_id": spec.run_id, "worker_id": "owned-fixture", "lease_seconds": 300})
    with AutoencoderRegistry(database, artifacts) as registry:
        monkeypatch.setattr(registry, "claim_run", lambda *a, **k: pytest.fail("cannot reclaim old generation"))
        with journals.DurableDaemonOperationJournal(path, binding, create=False) as journal:
            assert journal.resolve(registry, _slot(spec, "claim")) == original
            with pytest.raises(coordinator.TrainingCoordinationError, match="queued"):
                _run(registry, [spec], journal,
                     before_claim=lambda job: pytest.fail("old attempt cannot be admitted"))
            assert registry.get_run(spec.run_id)["attempt"] == 1


def test_all_jobs_validate_before_any_resource_admission_or_claim(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        first, second = _prepare(registry, tmp_path), _prepare(registry, tmp_path, index=1)
        Path(second.output_directory).mkdir()
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            with pytest.raises(coordinator.TrainingCoordinationError, match="directory"):
                _run(registry, [first, second], journal,
                     before_claim=lambda job: pytest.fail("invalid last job must block admission"))
            assert journal.operations() == {}
            assert registry.get_run(first.run_id)["status"] == "queued"


@pytest.mark.parametrize("phase", ["claim", "prepare"])
def test_resource_rejection_precedes_claim_or_owner_staging(tmp_path, monkeypatch, phase):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)

        def reject(*args):
            raise OSError("resource allowance exhausted")

        monkeypatch.setattr(coordinator, "_prepare_completion",
                            lambda *a, **k: pytest.fail("resource failure must precede staging"))
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, **{f"before_{phase}": reject})
            assert report["completed"] == []
            assert registry.get_run(spec.run_id)["status"] == ("queued" if phase == "claim" else "failed")
            assert report["failed"][0]["failure_recorded"] is (phase == "prepare")
            assert not journal.pending()


@pytest.mark.parametrize("bound,value", [("MAX_OPERATIONS", 1), ("MAX_JOURNAL_BYTES", 2048)])
def test_journal_capacity_fails_before_admission_and_claim(tmp_path, monkeypatch, bound, value):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            monkeypatch.setattr(journals, bound, value)
            with pytest.raises(coordinator.TrainingCoordinationError, match="capacity"):
                _run(registry, [spec], journal,
                     before_claim=lambda job: pytest.fail("capacity must precede admission"))
            assert registry.get_run(spec.run_id)["status"] == "queued"
            assert journal.operations() == {}


@pytest.mark.parametrize("option", ["defer_target_hydration_gc", "reduce_native_targets"])
def test_injected_executor_cannot_opt_into_native_runtime_policy(tmp_path, option):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            with pytest.raises(coordinator.TrainingCoordinationError, match="native"):
                _run(registry, [spec], journal, **{option: True})
            assert journal.operations() == {}
            assert registry.get_run(spec.run_id)["status"] == "queued"


def test_foreign_journal_owner_rejected_before_job_validation(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        binding = _binding(registry)
        binding["owner"]["database_path"] = str(tmp_path / "foreign.duckdb")
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", binding) as journal:
            monkeypatch.setattr(coordinator, "_validate_runs", lambda *a: pytest.fail("foreign owner"))
            with pytest.raises(coordinator.TrainingCoordinationError, match="another registry"):
                _run(registry, [], journal)


@pytest.mark.parametrize("worker_fails", [False, True])
def test_terminal_callback_failure_preserves_durable_status(tmp_path, monkeypatch, worker_fails):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        original_fail = registry.fail_run
        failures = []

        def fail(*args, **kwargs):
            failures.append(args[0])
            return original_fail(*args, **kwargs)

        def worker(job):
            if worker_fails:
                raise RuntimeError("fixture worker failure")
            return _fixture_worker(job)

        def terminal(job, receipt):
            assert receipt["status"] == ("failed" if worker_fails else "completed")
            raise OSError("terminal source guard unavailable")

        monkeypatch.setattr(registry, "fail_run", fail)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, worker_function=worker, after_terminal=terminal)
            assert report["recovery_required"] is True
            assert report["completed"] == []
            assert registry.get_run(spec.run_id)["status"] == ("failed" if worker_fails else "completed")
            assert len(failures) == int(worker_fails)
            assert report["failed"][0]["failure_recorded"] is worker_fails


def test_other_active_lease_is_renewed_before_terminal_qualification(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        specs = [_prepare(registry, tmp_path), _prepare(registry, tmp_path, index=1)]
        active_during_callbacks = []
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            def terminal(job, receipt):
                running = [other for other in specs if registry.get_run(other.run_id)["status"] == "running"]
                active_during_callbacks.append(len(running))
                for other in running:
                    assert journal.receipt(_slot(other, "renew", 1)) is not None

            result = _run(registry, specs, journal, max_workers=2, after_terminal=terminal)
            assert active_during_callbacks == [1, 0]
            assert len(result["completed"]) == 2
            assert sorted(item["lease_renewal_count"] for item in result["completed"]) == [2, 3]


def test_injected_start_failure_cannot_call_worker(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)

        def start(*args):
            raise OSError("injected start intent could not be recorded")

        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, before_submit=start,
                          worker_function=lambda *a: pytest.fail("start guard precedes worker"))
            assert registry.get_run(spec.run_id)["status"] == "failed"
            assert report["failed"][0]["failure_recorded"] is True
            assert not Path(spec.output_directory).exists()


def test_quarantine_keeps_terminal_resource_callback_until_preparation_drains(tmp_path, monkeypatch):
    entered, allow_finish, finished = threading.Event(), threading.Event(), threading.Event()
    callbacks = []
    failed_clock = False
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas", clock=lambda: 1000) as registry:
        spec = _prepare(registry, tmp_path)
        original_prepare, original_fail = coordinator._prepare_completion, registry.fail_run

        def prepare(*args, **kwargs):
            entered.set()
            assert allow_finish.wait(timeout=10), "owner failure should unblock fixture preparation"
            try:
                return original_prepare(*args, **kwargs)
            finally:
                finished.set()

        def clock():
            nonlocal failed_clock
            if entered.is_set() and not failed_clock:
                failed_clock = True
                raise OSError("coordinator clock unavailable during preparation")
            return 1000

        def fail(*args, **kwargs):
            try:
                assert entered.is_set() and not finished.is_set()
                return original_fail(*args, **kwargs)
            finally:
                allow_finish.set()

        monkeypatch.setattr(coordinator, "_prepare_completion", prepare)
        monkeypatch.setattr(registry, "fail_run", fail)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            report = _run(registry, [spec], journal, clock=clock,
                          after_terminal=lambda *args: callbacks.append(finished.is_set()))
            assert finished.is_set()
            assert callbacks == []
            assert registry.get_run(spec.run_id)["status"] == "failed"
            assert report["failed"][0]["failure_recorded"] is True


def test_existing_durable_failure_is_resolved_without_conflicting_second_payload(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        spec = _prepare(registry, tmp_path)
        with journals.DurableDaemonOperationJournal(tmp_path / "journal.json", _binding(registry)) as journal:
            original_error = {"admitted": False, "message": "original owner failure"}

            def injected_failure(job):
                # Simulate an owner-side failure already committed before the
                # injected execution reports its distinct coordination error.
                journal.invoke(registry, _slot(job, "fail"), "FailRun", {
                    "lease": registry.get_run(job.run_id)["lease"], "result": original_error})
                raise RuntimeError("later coordination failure")

            report = _run(registry, [spec], journal, worker_function=injected_failure)
            assert report["failed"][0]["failure_recorded"] is True
            assert report["recovery_required"] is False
            assert registry.get_run(spec.run_id)["result"] == original_error
            assert journal.operations()[_slot(spec, "fail")]["payload"]["result"] == original_error
            assert set(journal.operations()) == {_slot(spec, "claim"), _slot(spec, "fail")}
