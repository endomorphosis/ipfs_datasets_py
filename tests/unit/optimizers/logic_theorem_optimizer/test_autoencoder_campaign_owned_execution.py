"""Owned v8 execution through injected updates, never native model training.

The real worker hydrates complete targets and writes accepted sparse patches;
owner validation replays them and verifies optional Arrow feature mappings.
The resource fixture records accounting/order without acquiring a host lease.
Every execution and durable result must retain the injected_test label.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import uuid

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_execution as execution
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_training as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_plan as plans
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as requests
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import (
    _assert_transport_result, _combined, _injected_worker,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import ImmediateExecutor


ERRORS = (ValueError, RegistryError, OSError, resources.DaemonResourceError)
FALSE_AUTHORITY = ("admitted", "formalized", "promotion_performed", "publication_performed")


def _forbidden(*args, **kwargs):
    pytest.fail("an already completed or rejected owned request must not launch a worker")


class RecordingReservations:
    """Explicit injected resource factory; no ledger or real host lease."""

    def __init__(self, *, deny=False):
        self.deny = deny
        self.identity = uuid.uuid4().hex
        self.instances = []
        self.events = []

    @property
    def active(self):
        return [item for item in self.instances if item.status == "active"]

    def __call__(self, ledger_path, **kwargs):
        item = RecordingReservation(self, ledger_path, kwargs, len(self.instances))
        self.instances.append(item)
        return item


class RecordingReservation:
    def __init__(self, owner, ledger_path, kwargs, ordinal):
        self.owner = owner
        self.ledger_path = Path(ledger_path)
        self.roots = tuple(Path(path) for path in kwargs["roots"])
        self.root_identities = [{"path": str(path), "device": path.stat().st_dev,
                                 "inode": path.stat().st_ino} for path in self.roots]
        self.storage_bytes = kwargs["storage_bytes"]
        self.memory_mb = kwargs["memory_mb"]
        self.cpu_slots = kwargs["cpu_slots"]
        self.reservation_id = f"injected-{owner.identity}-{ordinal:04d}"
        self.status = "not_entered"
        self.charges = {}
        self.attempt = None
        self._record = None

    def _event(self, name, **fields):
        self.owner.events.append({"event": name, "reservation_id": self.reservation_id, **fields})

    def __enter__(self):
        self._event("admission_attempt")
        if self.owner.deny:
            raise resources.DaemonResourceError("injected capacity denial")
        assert self.status == "not_entered"
        self.status = "active"
        self._record = {"reservation_id": self.reservation_id, "status": self.status,
                        "external_charges": self.charges}
        self._event("admitted")
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.status == "active":
            self.status = "retained"
            self._record["status"] = self.status
            self._event("retained", error=None if exc_type is None else exc_type.__name__)
        return False

    def check_usage(self, attempt_directory, child_pid=None):
        assert self.status == "active"
        assert child_pid is None, "injected update must not invent an observed native child"
        path = Path(attempt_directory)
        assert path.is_dir()
        assert any(path == root or root in path.parents for root in self.roots)
        if self.attempt is not None:
            assert self.attempt == path
        self.attempt = path
        count = resources._inventory([path], strict=True)["apparent_bytes"]
        external = sum(self.charges.values())
        assert count + external <= self.storage_bytes
        self._event("checked", path=str(path), attempt_bytes=count, external_charged_bytes=external)
        return {"attempt_bytes": count, "attempt_limit_bytes": self.storage_bytes,
                "external_charged_bytes": external, "total_attempt_charged_bytes": count + external,
                "group_rss": {"rss_bytes": 0, "live_processes": 0},
                "memory_limit_bytes": self.memory_mb * 1024 * 1024}

    def account_external_bytes(self, key, byte_count):
        assert self.status == "active" and type(byte_count) is int and byte_count >= 0
        existed = key in self.charges
        assert not existed or self.charges[key] == byte_count
        self.charges[key] = byte_count
        assert sum(self.charges.values()) <= self.storage_bytes
        self._event("charged", key=key, bytes=byte_count)
        return {"key": key, "bytes": byte_count, "already_charged": existed,
                "usage": {"external_charged_bytes": sum(self.charges.values())}}

    def release(self, *, artifacts_durable=False):
        assert self.status == "active" and artifacts_durable is True
        self.status = "released"
        self._record.update(status=self.status, artifacts_durable_asserted=True)
        self._event("released")
        return self.to_dict()

    def to_dict(self):
        return {"schema": resources.SCHEMA, "reservation_id": self.reservation_id,
                "status": self.status, "ledger_path": str(self.ledger_path),
                "roots": deepcopy(self.root_identities), "record": deepcopy(self._record),
                "resource_lease": None, "cleanup_error": None,
                "enforcement": "injected_fixture_no_host_capacity_claim"}


@dataclass
class OwnedCase:
    registry: object
    combined: object
    plan: dict
    prepared: dict
    request: dict
    observations: dict
    reservations: RecordingReservations
    execute: object
    immutable: dict


def _case(registry, root, monkeypatch, *, arrow=False, artifact_format="bundle", problem=None,
          execution_changes=None):
    data = root / "inputs"
    data.mkdir()
    combined = _combined(registry, data, monkeypatch, arrow=arrow,
                         artifact_format=artifact_format, problem=problem)
    plan = plans.seal_campaign_plan(registry, [spec.run_id for spec in combined.specs])
    plan_payload = plans.decode_campaign_plan(registry.artifact_path(plan).read_bytes())
    output = root / "prepared"
    output.mkdir()
    policy = {"max_workers": 2, "lease_seconds": 300.0, "poll_seconds": 0.25,
              "timeout_seconds": 600.0, "defer_target_hydration_gc": False,
              "reduce_native_targets": False,
              "sparse_checkpoint_policy": {"max_depth": 8, "max_patch_fraction": 0.5}}
    policy.update(execution_changes or {})
    prepared = preparation.prepare_campaign_training(registry, plan,
        selected_batch_ids=[batch["batch_id"] for batch in plan_payload["batches"]],
        worker_id="injected-owned-campaign", output_root=str(output),
        resource_policy={"ledger_path": str(root / "fixture-resource-ledger.json"), "roots": [str(root)],
                         "storage_bytes": 50_000_000, "memory_mb": 512, "cpu_slots": 1},
        execution_policy=policy)
    request_raw = registry.artifact_path(prepared["request_artifact"]).read_bytes()
    request = requests.decode_campaign_training_request(request_raw)
    originals = {str(registry.artifact_path(ref)): registry.artifact_path(ref).read_bytes()
                 for ref in (plan, prepared["request_artifact"],
                             *(batch["job_spec_artifact"] for batch in request["batches"]))}
    originals.update(combined.shared_files)
    observations = {}
    return OwnedCase(registry, combined, plan, prepared, request, observations,
                     RecordingReservations(), _injected_worker(combined, observations, arrow=arrow), originals)


def _run(case, *, max_new_batches=2, max_workers=2, worker_function=None, executor_factory=ImmediateExecutor):
    return execution._execute_prepared_campaign_training(case.registry, case.prepared["request_artifact"],
        max_new_batches=max_new_batches, max_workers=max_workers,
        executor_factory=executor_factory, worker_function=case.execute if worker_function is None else worker_function,
        reservation_factory=case.reservations)


def _completed(registry, spec):
    durable = registry.get_run_completion(spec.run_id)
    assert durable is not None
    run, version = durable["run"], durable["candidate_version"]
    return {"run_id": spec.run_id, "job_id": spec.job_id, "version_id": version["version_id"],
            "candidate": version["artifact"], "result": run["result"],
            "worker_receipt_artifact": run["result"]["worker_receipt_artifact"]}


def _assert_report(case, report, *, status):
    assert report["status"] == status, report
    assert report["request_artifact"] == case.prepared["request_artifact"]
    assert report["execution_mode"] == "injected_test"
    assert report["native_execution_verified"] is False
    assert all(report[name] is False for name in FALSE_AUTHORITY)
    assert [row["run_id"] for row in report["batches"]] == [spec.run_id for spec in case.combined.specs]
    assert report["resources"]
    if report["dispatch"] is not None:
        assert report["dispatch"]["execution_mode"] == "injected_test"
    for path, raw in case.immutable.items():
        assert Path(path).read_bytes() == raw
    assert not Path(case.request["resource_policy"]["ledger_path"]).exists()
    assert case.registry.resolve_head("english-0", "best")["version_id"] == case.combined.specs[0].base_version_id


def _assert_pristine(case):
    for spec in case.combined.specs:
        run = case.registry.get_run(spec.run_id)
        assert run["status"] == "queued" and run["attempt"] == run["fence"] == 0
        assert run["lease"] is run["result"] is None
        assert not Path(spec.output_directory).exists()
    assert case.observations == {}


@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
@pytest.mark.parametrize("arrow", [False, True])
def test_owned_complete_targets_sparse_branches_arrow_and_repeat(tmp_path, monkeypatch, artifact_format, arrow):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=arrow, artifact_format=artifact_format)
        claimed = []
        original_claim = registry.claim_run
        def claim(operation_id, run_id, worker_id, lease_seconds):
            assert case.reservations.active, "claim preceded injected capacity admission"
            claimed.append(run_id)
            return original_claim(operation_id, run_id, worker_id, lease_seconds)
        monkeypatch.setattr(registry, "claim_run", claim)
        report = _run(case)
        _assert_report(case, report, status="complete")
        ids = [spec.run_id for spec in case.combined.specs]
        assert report["dispatched_run_ids"] == report["completed_run_ids"] == ids
        assert report["deferred_run_ids"] == []
        assert claimed == ids and set(case.observations) == set(ids)
        assert all(row["completion_verified"] is True for row in report["batches"])
        versions = []
        for spec, other in (case.combined.specs, tuple(reversed(case.combined.specs))):
            completed = _completed(registry, spec)
            versions.append(completed["version_id"])
            resolved = _assert_transport_result(registry, completed, spec, case.observations[spec.run_id],
                case.combined, arrow=arrow, artifact_format=artifact_format)
            assert case.observations[spec.run_id]["branch"] in resolved.state.feature_embedding_weights
            assert case.observations[other.run_id]["branch"] not in resolved.state.feature_embedding_weights
        assert len(set(versions)) == 2
        assert all(item.status == "released" for item in case.reservations.instances)
        before_claims = list(claimed)
        before_admissions = len(case.reservations.instances)
        original_completed = plans._completed
        def replay(*args, **kwargs):
            assert case.reservations.active, "completed candidate replay preceded resource admission"
            return original_completed(*args, **kwargs)
        monkeypatch.setattr(plans, "_completed", replay)
        repeated = _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        _assert_report(case, repeated, status="complete")
        assert repeated["dispatch"] is None and repeated["dispatched_run_ids"] == []
        assert repeated["completed_run_ids"] == ids and claimed == before_claims
        assert len(case.reservations.instances) >= before_admissions + 2
        third = _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        _assert_report(case, third, status="complete")
        assert third["dispatched_run_ids"] == [] and third["completed_run_ids"] == ids


def test_between_batches_owner_restart_dispatches_only_remaining_original_job(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        first, second = case.combined.specs
        initial = _run(case, max_new_batches=1, max_workers=1)
        _assert_report(case, initial, status="ready")
        assert initial["dispatched_run_ids"] == initial["completed_run_ids"] == [first.run_id]
        assert initial["deferred_run_ids"] == [second.run_id]
        assert registry.get_run(second.run_id)["attempt"] == registry.get_run(second.run_id)["fence"] == 0
        original_first = _completed(registry, first)
    with AutoencoderRegistry(database, artifacts) as registry:
        case.registry = registry
        resumed = _run(case, max_new_batches=1, max_workers=1)
        _assert_report(case, resumed, status="complete")
        assert resumed["dispatched_run_ids"] == [second.run_id]
        assert resumed["completed_run_ids"] == [first.run_id, second.run_id]
        assert _completed(registry, first) == original_first
        assert set(case.observations) == {first.run_id, second.run_id}
        for spec in case.combined.specs:
            _assert_transport_result(registry, _completed(registry, spec), spec, case.observations[spec.run_id],
                case.combined, arrow=True, artifact_format="bundle")


def test_single_worker_page_releases_verified_capacity_before_claiming_next_job(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch)
        first, second = case.combined.specs
        original_claim = registry.claim_run
        claims = []
        def claim(operation_id, run_id, worker_id, lease_seconds):
            assert len(case.reservations.active) == 1
            if run_id == second.run_id:
                assert case.reservations.instances[0].status == "released"
                assert registry.get_run(first.run_id)["status"] == "completed"
                _assert_transport_result(registry, _completed(registry, first), first,
                    case.observations[first.run_id], case.combined, arrow=False, artifact_format="bundle")
            claims.append(run_id)
            return original_claim(operation_id, run_id, worker_id, lease_seconds)
        monkeypatch.setattr(registry, "claim_run", claim)
        report = _run(case, max_workers=1)
        _assert_report(case, report, status="complete")
        assert claims == report["completed_run_ids"] == [first.run_id, second.run_id]
        assert len(case.reservations.instances) == 2
        assert all(item.status == "released" for item in case.reservations.instances)


@pytest.mark.parametrize("limits", [
    {"max_new_batches": 0}, {"max_new_batches": True}, {"max_new_batches": 65},
    {"max_workers": 0}, {"max_workers": True}, {"max_workers": 3}, {"max_workers": 5},
])
def test_invalid_or_unsealed_dispatch_bounds_reject_before_admission(tmp_path, monkeypatch, limits):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch)
        with pytest.raises(ERRORS):
            _run(case, **limits)
        assert case.reservations.instances == []
        _assert_pristine(case)


@pytest.mark.parametrize("field", ["defer_target_hydration_gc", "reduce_native_targets"])
def test_injected_execution_cannot_claim_native_target_runtime_policy(tmp_path, monkeypatch, field):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, execution_changes={field: True})
        with pytest.raises(ERRORS, match="native|inject"):
            _run(case)
        assert case.reservations.instances == []
        _assert_pristine(case)


def test_capacity_denial_precedes_claim_worker_and_target_hydration(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        case.reservations.deny = True
        monkeypatch.setattr(registry, "claim_run", _forbidden)
        report = _run(case, worker_function=_forbidden)
        assert report["dispatched_run_ids"] == [] and report["completed_run_ids"] == []
        assert report["dispatch"]["failed"]
        assert all("capacity denial" in row["error"] for row in report["dispatch"]["failed"])
        assert case.reservations.events and all(row["event"] == "admission_attempt" for row in case.reservations.events)
        _assert_pristine(case)


@pytest.mark.parametrize("kind", ["target", "arrow", "last_source"])
def test_changed_selected_input_rejects_entire_selection_before_first_claim(tmp_path, monkeypatch, kind):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        last = case.combined.specs[-1]
        ref = (last.target_snapshot_artifact if kind == "target" else last.arrow_feature_weights_artifact
               if kind == "arrow" else last.corpus_source_artifacts[-1])
        Path(ref.path).write_bytes(b"corrupted selected dependency")
        monkeypatch.setattr(registry, "claim_run", _forbidden)
        with pytest.raises(ERRORS):
            _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        _assert_pristine(case)


def test_one_injected_worker_failure_preserves_other_candidate_and_requires_recovery(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        first, second = case.combined.specs
        def execute(spec):
            if spec.run_id == first.run_id:
                raise RuntimeError("explicit injected worker failure")
            return case.execute(spec)
        report = _run(case, worker_function=execute)
        _assert_report(case, report, status="recovery_required")
        assert report["completed_run_ids"] == [second.run_id]
        assert registry.get_run(first.run_id)["status"] == "failed"
        assert registry.get_run(second.run_id)["status"] == "completed"
        assert set(case.observations) == {second.run_id}
        _assert_transport_result(registry, _completed(registry, second), second, case.observations[second.run_id],
            case.combined, arrow=True, artifact_format="bundle")
        before = [registry.get_run(spec.run_id) for spec in case.combined.specs]
        repeated = _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        assert repeated["status"] == "recovery_required" and repeated["dispatched_run_ids"] == []
        assert [registry.get_run(spec.run_id) for spec in case.combined.specs] == before


def test_sparse_owner_compaction_preserves_the_exact_injected_candidate(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True, execution_changes={
            "sparse_checkpoint_policy": {"max_depth": 1, "max_patch_fraction": 0.5}})
        report = _run(case)
        _assert_report(case, report, status="complete")
        for spec in case.combined.specs:
            completed = _completed(registry, spec)
            summary = completed["result"]
            assert summary["execution_mode"] == "injected_test"
            assert summary["sparse_replay_verified"] is True
            assert summary["sparse_compaction_performed"] is True
            assert "max_depth" in summary["sparse_compaction_reasons"]
            assert summary["checkpoint_storage"] == "full_json"
            assert summary["checkpoint_dependencies"] == []
            assert summary["checkpoint_chain_depth"] == 0
            candidate = registry.artifact_path(completed["candidate"]).read_bytes()
            assert candidate == case.observations[spec.run_id]["raw"]
            assert completed["candidate"] == {"sha256": hashlib.sha256(candidate).hexdigest(), "bytes": len(candidate)}
        repeated = _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        _assert_report(case, repeated, status="complete")
        assert repeated["dispatched_run_ids"] == []


@pytest.mark.parametrize("method_name", ["claim_run", "complete_run"])
def test_committed_response_loss_resolves_exact_operation_without_second_update(tmp_path, monkeypatch, method_name):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch)
        original = getattr(registry, method_name)
        calls = []
        def committed_then_lost(*args, **kwargs):
            calls.append((deepcopy(args), deepcopy(kwargs)))
            original(*args, **kwargs)
            raise OSError("injected committed reply loss")
        monkeypatch.setattr(registry, method_name, committed_then_lost)
        report = _run(case, max_new_batches=1, max_workers=1)
        _assert_report(case, report, status="ready")
        first, second = case.combined.specs
        assert report["completed_run_ids"] == report["dispatched_run_ids"] == [first.run_id]
        assert report["deferred_run_ids"] == [second.run_id]
        assert len(calls) == 1 and set(case.observations) == {first.run_id}
        _assert_transport_result(registry, _completed(registry, first), first, case.observations[first.run_id],
            case.combined, arrow=False, artifact_format="bundle")


def test_unresolved_committed_completion_reconciles_without_retrying_or_releasing_old_claim(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    updates = []
    with AutoencoderRegistry(database, artifacts) as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        first, second = case.combined.specs
        original_complete, original_resolve = registry.complete_run, registry.resolve_operation
        lost = False
        def update(spec):
            updates.append(spec.run_id)
            return case.execute(spec)
        def complete_then_lose(*args, **kwargs):
            nonlocal lost
            original_complete(*args, **kwargs)
            lost = True
            raise OSError("injected completion reply unavailable")
        def unavailable(operation_id, command, payload):
            if lost and command == "CompleteRun":
                raise OSError("injected completion lookup unavailable")
            return original_resolve(operation_id, command, payload)
        monkeypatch.setattr(registry, "complete_run", complete_then_lose)
        monkeypatch.setattr(registry, "resolve_operation", unavailable)
        monkeypatch.setattr(registry, "fail_run", _forbidden)
        report = _run(case, max_new_batches=1, max_workers=1, worker_function=update)
        assert report["status"] == "recovery_required"
        assert registry.get_run(first.run_id)["status"] == "completed"
        assert registry.get_run(second.run_id)["status"] == "queued"
        assert updates == [first.run_id]
        journal = json.loads(Path(case.prepared["journal_path"]).read_bytes())
        assert any(row["command"] == "CompleteRun" and row.get("receipt") is None
                   for row in journal["operations"].values())
    with AutoencoderRegistry(database, artifacts) as registry:
        case.registry = registry
        report = _run(case, max_new_batches=1, max_workers=1, worker_function=_forbidden, executor_factory=_forbidden)
        _assert_report(case, report, status="recovery_required")
        assert report["dispatched_run_ids"] == []
        assert report["completed_run_ids"] == [first.run_id]
        assert report["pending_operation_slots"] == [] and updates == [first.run_id]
        assert report["batches"][0]["reason"] == "prior_resource_release_unresolved"
        assert any(item.status == "retained" for item in case.reservations.instances)
        assert registry.get_run(second.run_id)["status"] == "queued"
        _assert_transport_result(registry, _completed(registry, first), first, case.observations[first.run_id],
            case.combined, arrow=True, artifact_format="bundle")


def test_uncommitted_completion_after_restart_requires_explicit_recovery(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        case = _case(registry, tmp_path, monkeypatch)
        first, second = case.combined.specs
        def unavailable(*args, **kwargs):
            raise OSError("injected pre-commit completion interruption")
        monkeypatch.setattr(registry, "complete_run", unavailable)
        monkeypatch.setattr(registry, "fail_run", _forbidden)
        report = _run(case, max_new_batches=1, max_workers=1)
        assert report["status"] == "recovery_required"
        assert registry.get_run(first.run_id)["status"] == "running"
        assert registry.get_run(second.run_id)["status"] == "queued"
        previous_attempt = registry.get_run(first.run_id)["attempt"]
        previous_generation = registry.owner_generation
        assert set(case.observations) == {first.run_id}
    with AutoencoderRegistry(database, artifacts) as registry:
        case.registry = registry
        assert registry.owner_generation > previous_generation
        for name in ("claim_run", "complete_run", "fail_run"):
            monkeypatch.setattr(registry, name, _forbidden)
        report = _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        assert report["status"] == "recovery_required" and report["dispatched_run_ids"] == []
        assert registry.get_run(first.run_id)["attempt"] == previous_attempt
        assert registry.get_run(second.run_id)["attempt"] == registry.get_run(second.run_id)["fence"] == 0


def test_resource_injection_alone_cannot_enable_native_target_policy(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, execution_changes={"reduce_native_targets": True})
        with pytest.raises(ERRORS, match="native|inject"):
            execution._execute_prepared_campaign_training(registry, case.prepared["request_artifact"],
                reservation_factory=case.reservations)
        assert case.reservations.instances == []
        _assert_pristine(case)


def test_completed_candidate_corruption_is_rechecked_under_capacity_without_redispatch(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        initial = _run(case)
        _assert_report(case, initial, status="complete")
        first = case.combined.specs[0]
        candidate = _completed(registry, first)["candidate"]
        registry.artifact_path(candidate).write_bytes(b"corrupted completed sparse manifest")
        admitted_before = len(case.reservations.instances)
        original_runs = [registry.get_run(spec.run_id) for spec in case.combined.specs]
        with pytest.raises(ERRORS):
            _run(case, worker_function=_forbidden, executor_factory=_forbidden)
        assert len(case.reservations.instances) == admitted_before + 1
        assert case.reservations.instances[-1].status == "retained"
        assert [registry.get_run(spec.run_id) for spec in case.combined.specs] == original_runs
        assert set(case.observations) == {spec.run_id for spec in case.combined.specs}


@pytest.mark.parametrize("problem", ["segment_bytes", "native_label"])
def test_forged_worker_result_cannot_gain_owner_acceptance_or_cancel_sibling(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        case = _case(registry, tmp_path, monkeypatch, arrow=True)
        first, second = case.combined.specs
        def forged(spec):
            receipt = case.execute(spec)
            if spec.run_id == first.run_id:
                if problem == "segment_bytes":
                    Path(receipt["sparse_patch_segments"][0]["path"]).write_bytes(b"corrupt injected patch")
                else:
                    receipt["execution_mode"] = "native_training"
                    Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
            return receipt
        report = _run(case, worker_function=forged)
        _assert_report(case, report, status="recovery_required")
        assert report["completed_run_ids"] == [second.run_id]
        assert registry.get_run(first.run_id)["status"] == "failed"
        assert registry.get_run(first.run_id)["result"]["execution_mode"] == "injected_test"
        assert registry.get_run_completion(first.run_id) is None
        _assert_transport_result(registry, _completed(registry, second), second, case.observations[second.run_id],
            case.combined, arrow=True, artifact_format="bundle")
        assert any(item.status == "retained" for item in case.reservations.instances)
        assert any(item.status == "released" for item in case.reservations.instances)
