"""Offline B1 preparation; no model, native child or resource admission.

The three-byte checkpoint and opaque optional artifacts establish transport and
inventory contracts only. They cannot establish native qualification.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.logic.autoformal import tree_pin
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_training as owned
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_plan as plans
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation as daemon
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as compact
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import (
    _campaign_inputs, _next_job,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import _prepare

TABLES = ("events", "heads", "meta", "operations", "outbox", "runs", "variants", "versions")
ERRORS = (ValueError, RegistryError, OSError, resources.DaemonResourceError)


def _forbidden(*args, **kwargs):
    pytest.fail("B1 must not construct a model, execute, replay, admit resources or connect")


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    for obj, name in (
        (modal.AdaptiveModalAutoencoder, "__init__"),
        (modal.ModalAutoencoderTrainingState, "__init__"),
        (compact, "load_checkpoint"), (compact, "deserialize_checkpoint"),
        (sparse, "resolve_checkpoint"), (sparse, "replay_patch"),
        (coordinator, "run_training_jobs"), (worker, "execute_training_job"),
        (plans, "_inspect"), (plans, "_completed"),
        (daemon, "prepare_daemon_invocation"), (daemon, "run_owned_daemon_invocation"),
        (resources.DaemonResourceReservation, "__enter__"),
        (resources.DaemonResourceReservation, "_locked"),
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (subprocess, "Popen"),
    ):
        monkeypatch.setattr(obj, name, _forbidden)


def _tables(registry):
    with registry._transaction() as connection:
        return {name: sorted(connection.execute("SELECT * FROM autoencoder_control." + name).fetchall(), key=repr)
                for name in TABLES}


def _request(case, handle):
    raw = case.registry.artifact_path(handle["request_artifact"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == handle["request_artifact"]["sha256"]
    assert len(raw) == handle["request_artifact"]["bytes"]
    value = codec.decode_campaign_training_request(raw)
    assert codec.encode_campaign_training_request(value) == raw
    return value


def _case(registry, root, *, optional=False):
    data = root / "inputs"
    data.mkdir()
    (data / "base.json").write_bytes(b"{}\n")
    inputs, binding, fixture = _campaign_inputs(registry, data)
    if optional:
        for field, filename in (("target_snapshot_artifact", "target.fixture"),
                                ("arrow_feature_weights_artifact", "arrow.fixture")):
            path = data / filename
            path.write_bytes(("opaque-transport-only:" + field).encode())
            ref = registry.stage_artifact(path)
            inputs[field] = {**ref, "path": str(registry.artifact_path(ref))}
        inputs.update(target_snapshot_id="sha256:" + "a" * 64,
                      capture_sparse_patches=True, candidate_storage="sparse")
    first = _prepare(registry, data, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
    next_inputs, next_binding, _ = _campaign_inputs(registry, data, fixture=fixture, batch_number=1)
    assert next_binding == binding
    second = _next_job(registry, data, first, next_inputs)
    plan = plans.seal_campaign_plan(registry, [first.run_id, second.run_id])
    payload = plans.decode_campaign_plan(registry.artifact_path(plan).read_bytes())
    output = root / "prepared"
    output.mkdir()
    return SimpleNamespace(registry=registry, root=root, specs=(first, second), plan=plan, plan_payload=payload,
        output=output, selected=[row["batch_id"] for row in payload["batches"]],
        resource={"ledger_path": str(root / "disk-ledger.json"), "roots": [str(root)],
                  "storage_bytes": 50_000_000, "memory_mb": 512, "cpu_slots": 1},
        execution={"max_workers": 2, "lease_seconds": 300.0, "poll_seconds": 0.25,
                   "timeout_seconds": 600.0, "defer_target_hydration_gc": False,
                   "reduce_native_targets": False,
                   "sparse_checkpoint_policy": {"max_depth": 8, "max_patch_fraction": 0.5}})


@pytest.fixture
def case(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        yield _case(registry, tmp_path)


def _prepare_owned(case, **changes):
    values = {"selected_batch_ids": case.selected, "worker_id": "campaign-owner",
              "output_root": str(case.output), "resource_policy": case.resource,
              "execution_policy": case.execution}
    values.update(changes)
    return owned.prepare_campaign_training(case.registry, case.plan, **values)


def _report(case, handle):
    report = owned.inspect_campaign_training(case.registry, handle["request_artifact"])
    assert report["schema_version"] == "autoencoder-campaign-training-preparation-status-v1"
    for key in ("execution_available", "capacity_admitted", "native_execution_verified",
                "training_dispatched", "admitted", "formalized", "promotion_performed", "publication_performed"):
        assert report[key] is False
    assert all(row["completion_verified"] is False for row in report["batches"])
    return report


def _unchanged_originals(case, before):
    after = _tables(case.registry)
    for name in TABLES:
        if name != "operations":
            assert after[name] == before[name], name
    assert all(not Path(spec.output_directory).exists() for spec in case.specs)
    assert not Path(case.resource["ledger_path"]).exists()


def test_exact_request_and_read_only_inspection_preserve_original_jobs(case):
    before = _tables(case.registry)
    original = [spec.to_dict() for spec in case.specs]
    handle = _prepare_owned(case)
    assert set(handle) == {"request_artifact", "journal_path", "registration"}
    assert set(handle["request_artifact"]) == {"sha256", "bytes"}
    assert handle["registration"]["admitted"] is False
    request = _request(case, handle)
    assert request["plan_artifact"] == case.plan
    assert request["owner"] == {"database_path": str(case.registry.database_path),
                                "artifact_root": str(case.registry.artifact_root)}
    assert request["resource_policy"] == case.resource and request["execution_policy"] == case.execution
    assert [row["batch_id"] for row in request["batches"]] == case.selected
    for row, batch, spec in zip(request["batches"], case.plan_payload["batches"], case.specs, strict=True):
        assert row["plan_ordinal"] == batch["ordinal"]
        assert row["run_id"] == spec.run_id and row["job_id"] == spec.job_id
        assert row["job_spec_artifact"] == batch["job_spec_artifact"]
        assert row["job_spec_sha256"] == spec.canonical_sha256
        assert row["base_version_id"] == spec.base_version_id
        assert row["output_directory"] == spec.output_directory
    assert all(request[key] is False for key in codec.FALSE_FIELDS)
    _unchanged_originals(case, before)
    assert [spec.to_dict() for spec in case.specs] == original
    after = _tables(case.registry)
    journal_bytes = Path(handle["journal_path"]).read_bytes()
    report = _report(case, handle)
    assert report["status"] == "prepared" and report["pristine_queued_count"] == 2
    assert report["execution_history_present"] is False
    assert report["registration"] == handle["registration"]
    assert _tables(case.registry) == after
    assert Path(handle["journal_path"]).read_bytes() == journal_bytes
    assert _prepare_owned(case) == handle
    assert _tables(case.registry) == after


def test_reopen_resolves_identical_handle_without_recreating_original_runs(tmp_path):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        value = _case(registry, tmp_path)
        handle = _prepare_owned(value)
        before = _tables(registry)
        raw = registry.artifact_path(handle["request_artifact"]).read_bytes()
    with AutoencoderRegistry(database, artifacts) as registry:
        value.registry = registry
        assert _prepare_owned(value) == handle
        assert registry.artifact_path(handle["request_artifact"]).read_bytes() == raw
        assert _report(value, handle)["status"] == "prepared"
        after = _tables(registry)
        # Opening the actual registry advances owner_generation only.
        assert {k: v for k, v in after.items() if k != "meta"} == {k: v for k, v in before.items() if k != "meta"}


def test_exact_optional_target_arrow_and_sparse_policy_transport_is_unqualified(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        value = _case(registry, tmp_path, optional=True)
        handle = _prepare_owned(value)
        request = _request(value, handle)
        for batch, spec in zip(request["batches"], value.specs, strict=True):
            assert batch["target_snapshot_id"] == spec.target_snapshot_id
            for field in ("target_snapshot_artifact", "arrow_feature_weights_artifact"):
                ref = getattr(spec, field)
                assert batch[field] == {"sha256": ref.sha256, "bytes": ref.bytes}
            assert spec.capture_sparse_patches is True and spec.candidate_storage == "sparse"
        assert request["execution_policy"]["sparse_checkpoint_policy"] == value.execution["sparse_checkpoint_policy"]
        _report(value, handle)


@pytest.mark.parametrize("selection", [[], ["missing"], "not-a-list", "reversed", "duplicate"])
def test_invalid_selection_rejected_without_registry_mutation(case, selection):
    if selection == "reversed":
        selection = list(reversed(case.selected))
    elif selection == "duplicate":
        selection = [case.selected[0], case.selected[0]]
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case, selected_batch_ids=selection)
    assert _tables(case.registry) == before


@pytest.mark.parametrize("kind", ["unselected_output", "nested_control", "resolved_alias"])
def test_control_output_cannot_overlap_any_unselected_original_job(case, kind):
    unselected = Path(case.specs[-1].output_directory)
    if kind == "resolved_alias":
        unselected.symlink_to(case.output, target_is_directory=True)
        control = case.output
    else:
        unselected.mkdir()
        control = unselected
        if kind == "nested_control":
            control = unselected / "control"
            control.mkdir()
    before = _tables(case.registry)
    cas_before = {str(path.relative_to(case.registry.artifact_root)): path.read_bytes()
                  for path in case.registry.artifact_root.rglob("*") if path.is_file()}
    with pytest.raises(ERRORS):
        _prepare_owned(case, selected_batch_ids=case.selected[:1], output_root=str(control))
    assert _tables(case.registry) == before
    assert list(control.iterdir()) == []
    assert {str(path.relative_to(case.registry.artifact_root)): path.read_bytes()
            for path in case.registry.artifact_root.rglob("*") if path.is_file()} == cas_before



@pytest.mark.parametrize("bound", ["lease_seconds", "timeout_seconds", "root_coverage"])
def test_actual_job_budget_and_owner_paths_must_fit_declared_future_policy(case, bound):
    before = _tables(case.registry)
    if bound == "root_coverage":
        changes = {"resource_policy": {**case.resource, "roots": [str(case.output)]}}
    else:
        policy = deepcopy(case.execution)
        policy[bound] = case.specs[0].training_config.max_seconds / 2
        policy["poll_seconds"] = min(0.01, policy["lease_seconds"] / 8)
        changes = {"execution_policy": policy}
    with pytest.raises(ERRORS):
        _prepare_owned(case, **changes)
    assert _tables(case.registry) == before


def test_overlapping_reordered_plan_cannot_escape_original_run_binding(case):
    _prepare_owned(case, selected_batch_ids=case.selected[:1])
    reverse = plans.seal_campaign_plan(case.registry, [spec.run_id for spec in reversed(case.specs)])
    payload = plans.decode_campaign_plan(case.registry.artifact_path(reverse).read_bytes())
    assert payload["batches"][-1]["run_id"] == case.specs[0].run_id
    assert payload["batches"][-1]["batch_id"] != case.selected[0]
    replacement = case.root / "other-plan-control"
    replacement.mkdir()
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        owned.prepare_campaign_training(case.registry, reverse,
            selected_batch_ids=[payload["batches"][-1]["batch_id"]], worker_id="campaign-owner",
            output_root=str(replacement), resource_policy=case.resource, execution_policy=case.execution)
    assert _tables(case.registry) == before


def test_disjoint_selections_get_independent_bindings_without_any_run_execution(case):
    first = _prepare_owned(case, selected_batch_ids=case.selected[:1])
    second_output = case.root / "second-prepared"
    second_output.mkdir()
    second = _prepare_owned(case, selected_batch_ids=case.selected[1:], output_root=str(second_output))
    assert first["request_artifact"] != second["request_artifact"]
    assert first["journal_path"] != second["journal_path"]
    assert _report(case, first)["batch_count"] == _report(case, second)["batch_count"] == 1
    assert all(case.registry.get_run(spec.run_id)["attempt"] == 0 for spec in case.specs)
    assert all(not Path(spec.output_directory).exists() for spec in case.specs)


def test_journal_registration_cannot_substitute_for_registry_receipt(case):
    handle = _prepare_owned(case)
    path = Path(handle["journal_path"])
    binding = json.loads(path.read_bytes())["binding"]
    with owned.DurableDaemonOperationJournal(path, binding) as journal:
        forged = deepcopy(handle["registration"])
        forged["admitted"] = True
        journal.set_metadata("registration", forged)
    before = _tables(case.registry)
    journal_before = path.read_bytes()
    with pytest.raises(ERRORS):
        _report(case, handle)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert _tables(case.registry) == before
    assert path.read_bytes() == journal_before



@pytest.mark.parametrize("kind", ["source", "inventory", "helper_identity"])
def test_mutation_during_staging_rejects_before_journal_or_binding(case, monkeypatch, kind):
    original_stage = case.registry.stage_artifact
    original_sources = owned._sources
    changed = False
    def observed_sources():
        value = deepcopy(original_sources())
        if changed and kind == "helper_identity":
            key = next(iter(value))
            value[key]["sha256"] = "0" * 64
        return value
    def stage_then_mutate(*args, **kwargs):
        nonlocal changed
        result = original_stage(*args, **kwargs)
        if not changed:
            changed = True
            if kind != "helper_identity":
                ref = (case.specs[0].corpus_source_artifacts[0] if kind == "source"
                       else case.specs[0].source_inventory_artifact)
                path = Path(ref.path)
                path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(owned, "_sources", observed_sources)
    monkeypatch.setattr(case.registry, "stage_artifact", stage_then_mutate)
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert changed
    assert _tables(case.registry) == before
    assert list(case.output.iterdir()) == []


@pytest.mark.parametrize("missing", ["journal", "lock"])
@pytest.mark.parametrize("operation", ["inspect", "prepare"])
def test_race_never_recreates_validated_but_removed_journal_or_lock(case, monkeypatch, missing, operation):
    handle = _prepare_owned(case)
    original = owned._journal_paths
    journal = Path(handle["journal_path"])
    victim = journal if missing == "journal" else journal.with_name("." + journal.name + ".lock")
    def remove_after_check(*args, **kwargs):
        path = original(*args, **kwargs)
        victim.unlink()
        return path
    monkeypatch.setattr(owned, "_journal_paths", remove_after_check)
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _report(case, handle) if operation == "inspect" else _prepare_owned(case)
    assert not victim.exists()
    assert _tables(case.registry) == before


def test_committed_registration_missing_local_receipt_is_inspected_without_writes_then_repaired(case, monkeypatch):
    original = owned.DurableDaemonOperationJournal.set_metadata
    def fail_registration(self, key, value):
        if key == "registration":
            raise OSError("injected local receipt write failure")
        return original(self, key, value)
    monkeypatch.setattr(owned.DurableDaemonOperationJournal, "set_metadata", fail_registration)
    with pytest.raises(OSError, match="local receipt"):
        _prepare_owned(case)
    journal_path = case.output / "owner-operations.json"
    local = json.loads(journal_path.read_bytes())
    reference = local["metadata"]["prepared"]["request_artifact"]
    assert "registration" not in local["metadata"]
    before = _tables(case.registry)
    before_journal = journal_path.read_bytes()
    report = owned.inspect_campaign_training(case.registry, reference)
    assert report["execution_available"] is False and report["status"] == "prepared"
    assert journal_path.read_bytes() == before_journal
    assert _tables(case.registry) == before
    monkeypatch.setattr(owned.DurableDaemonOperationJournal, "set_metadata", original)
    handle = _prepare_owned(case)
    assert handle["request_artifact"] == reference
    assert handle["registration"] == report["registration"]
    assert _tables(case.registry) == before


@pytest.mark.parametrize("fault", ["digest", "authority", "request", "missing_binding"])
def test_corrupt_or_partial_registry_binding_never_becomes_preparation_authority(case, fault):
    handle = _prepare_owned(case)
    with case.registry._transaction() as connection:
        rows = connection.execute("SELECT operation_id,payload_digest,receipt FROM autoencoder_control.operations").fetchall()
        operation, digest, encoded = next(row for row in rows if json.loads(row[2])["command"] == owned.BIND_COMMAND)
        if fault == "missing_binding":
            connection.execute("DELETE FROM autoencoder_control.operations WHERE operation_id=?", [operation])
        elif fault == "digest":
            connection.execute("UPDATE autoencoder_control.operations SET payload_digest=? WHERE operation_id=?",
                               ["0" * 64, operation])
        else:
            receipt = json.loads(encoded)
            if fault == "authority":
                receipt["admitted"] = True
            else:
                receipt["request_artifact"]["sha256"] = "0" * 64
            connection.execute("UPDATE autoencoder_control.operations SET receipt=? WHERE operation_id=?",
                               [json.dumps(receipt), operation])
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _report(case, handle)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert _tables(case.registry) == before


def test_foreign_owner_rejects_before_reading_any_campaign_input(case, monkeypatch):
    handle = _prepare_owned(case)
    alternate = case.root / "other-owner"
    alternate.mkdir()
    with AutoencoderRegistry(alternate / "owner.duckdb", alternate / "artifacts") as registry:
        copied = registry.stage_artifact(case.registry.artifact_path(handle["request_artifact"]))
        assert copied == handle["request_artifact"]
        before = _tables(registry)
        monkeypatch.setattr(owned, "_capture", _forbidden)
        with pytest.raises(ERRORS):
            owned.inspect_campaign_training(registry, copied)
        assert _tables(registry) == before


def test_postcommit_guard_failure_retains_history_without_returning_success(case, monkeypatch):
    original = case.registry._mutate
    victim = Path(case.specs[0].corpus_source_artifacts[0].path)
    raw = victim.read_bytes()
    def commit_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        victim.write_bytes(raw + b" ")
        return result
    monkeypatch.setattr(case.registry, "_mutate", commit_then_change)
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    after = _tables(case.registry)
    assert len(after["operations"]) == len(before["operations"]) + len(case.specs) + 1
    _unchanged_originals(case, before)
    local = json.loads((case.output / "owner-operations.json").read_bytes())
    reference = local["metadata"]["prepared"]["request_artifact"]
    with pytest.raises(ERRORS):
        owned.inspect_campaign_training(case.registry, reference)
    assert _tables(case.registry) == after



@pytest.mark.parametrize("status", ["running", "failed", "completed", "queued_attempt"])
def test_nonpristine_last_selected_job_rejected_before_any_binding(case, status):
    with case.registry._transaction() as connection:
        connection.execute("UPDATE autoencoder_control.runs SET status=?, attempt=? WHERE run_id=?",
                           ["queued" if status == "queued_attempt" else status, 1, case.specs[-1].run_id])
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert _tables(case.registry) == before


def test_unselected_completion_is_observed_without_replay_or_completion_authority(case):
    with case.registry._transaction() as connection:
        connection.execute("UPDATE autoencoder_control.runs SET status='completed', attempt=1, result=? WHERE run_id=?",
                           [json.dumps({"fixture_unverified": True}), case.specs[-1].run_id])
    before = _tables(case.registry)
    handle = _prepare_owned(case, selected_batch_ids=case.selected[:1])
    assert [row["run_id"] for row in _request(case, handle)["batches"]] == [case.specs[0].run_id]
    assert _report(case, handle)["status"] == "prepared"
    _unchanged_originals(case, before)


@pytest.mark.parametrize("status", ["running", "failed", "completed"])
def test_inspection_observes_later_state_but_never_verifies_completion_or_reprepares(case, status):
    handle = _prepare_owned(case)
    with case.registry._transaction() as connection:
        connection.execute("UPDATE autoencoder_control.runs SET status=?, attempt=1, result=? WHERE run_id=?",
                           [status, json.dumps({"fixture_unverified": True}), case.specs[-1].run_id])
    before = _tables(case.registry)
    report = _report(case, handle)
    assert report["status"] == "recovery_required" and report["pristine_queued_count"] == 1
    assert report["batches"][-1]["registry_status"] == status
    assert report["batches"][-1]["pristine_queued"] is False
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert _tables(case.registry) == before


@pytest.mark.parametrize("field", ["worker_id", "output_root", "resource_policy", "execution_policy"])
def test_existing_run_binding_cannot_change_owner_request_policy(case, field):
    handle = _prepare_owned(case)
    before = _tables(case.registry)
    if field == "worker_id":
        changed = "another-worker"
    elif field == "output_root":
        changed = case.root / "other-prepared"
        changed.mkdir()
        changed = str(changed)
    elif field == "resource_policy":
        changed = {**case.resource, "storage_bytes": case.resource["storage_bytes"] + 1}
    else:
        changed = {**case.execution, "timeout_seconds": 601.0}
    with pytest.raises(ERRORS):
        _prepare_owned(case, **{field: changed})
    assert _tables(case.registry) == before
    assert _prepare_owned(case) == handle


def test_overlapping_subset_is_not_a_second_assignment_for_the_same_run(case):
    _prepare_owned(case, selected_batch_ids=case.selected[:1])
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert _tables(case.registry) == before


def test_existing_binding_never_recreates_missing_journal(case):
    handle = _prepare_owned(case)
    victim = Path(handle["journal_path"])
    victim.unlink()
    before = _tables(case.registry)
    for call in (lambda: _prepare_owned(case), lambda: _report(case, handle)):
        with pytest.raises(ERRORS):
            call()
        assert not victim.exists()
        assert _tables(case.registry) == before


def test_inspection_rejects_missing_request_without_writing_anything(case):
    handle = _prepare_owned(case)
    victim = case.registry.artifact_path(handle["request_artifact"])
    victim.unlink()
    before = _tables(case.registry)
    journal = Path(handle["journal_path"]).read_bytes()
    with pytest.raises(ERRORS):
        _report(case, handle)
    assert not victim.exists()
    assert _tables(case.registry) == before
    assert Path(handle["journal_path"]).read_bytes() == journal


def test_committed_response_loss_returns_the_exact_registration(case, monkeypatch):
    original, committed = case.registry._mutate, []
    def lose_response(operation_id, command, payload, apply):
        receipt = original(operation_id, command, payload, apply)
        committed.append(deepcopy(receipt))
        raise OSError("injected response lost after durable commit")
    monkeypatch.setattr(case.registry, "_mutate", lose_response)
    try:
        handle = _prepare_owned(case)
    except OSError:
        monkeypatch.setattr(case.registry, "_mutate", original)
        handle = _prepare_owned(case)
    assert len(committed) == 1
    assert handle["registration"] == committed[0]
    monkeypatch.setattr(case.registry, "_mutate", original)
    before = _tables(case.registry)
    assert _prepare_owned(case) == handle
    assert _tables(case.registry) == before


def test_binding_transaction_rolls_back_every_run_if_apply_fails(case, monkeypatch):
    original = case.registry._mutate
    before = _tables(case.registry)
    def fail_after_apply(operation_id, command, payload, apply):
        def failing(connection):
            apply(connection)
            raise RuntimeError("injected rollback before outer receipt commit")
        return original(operation_id, command, payload, failing)
    monkeypatch.setattr(case.registry, "_mutate", fail_after_apply)
    with pytest.raises(RuntimeError, match="injected rollback"):
        _prepare_owned(case)
    assert _tables(case.registry) == before
    monkeypatch.setattr(case.registry, "_mutate", original)
    handle = _prepare_owned(case)
    assert _report(case, handle)["status"] == "prepared"


def test_last_run_race_is_rechecked_in_atomic_binding_transaction(case, monkeypatch):
    original = case.registry._mutate
    before = _tables(case.registry)
    def changed_before_commit(operation_id, command, payload, apply):
        with case.registry._transaction() as connection:
            connection.execute("UPDATE autoencoder_control.runs SET status='running', attempt=1 WHERE run_id=?",
                               [case.specs[-1].run_id])
        return original(operation_id, command, payload, apply)
    monkeypatch.setattr(case.registry, "_mutate", changed_before_commit)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    after = _tables(case.registry)
    assert after["operations"] == before["operations"]
    assert all(after[name] == before[name] for name in TABLES if name not in {"runs", "operations"})


@pytest.mark.parametrize("field", ["source_inventory_artifact", "produced_record_projection_artifact",
                                  "corpus_manifest_artifact", "source", "leaf", "base_checkpoint"])
def test_current_artifact_corruption_blocks_repeat_and_inspection(case, field):
    handle = _prepare_owned(case)
    spec = case.specs[0]
    ref = (spec.corpus_source_artifacts[0] if field == "source" else
           spec.embedding_receipt_artifacts[0] if field == "leaf" else getattr(spec, field))
    path = Path(ref.path)
    path.write_bytes(path.read_bytes() + b" ")
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    with pytest.raises(ERRORS):
        _report(case, handle)
    assert _tables(case.registry) == before


@pytest.mark.parametrize("kind", ["alias", "missing", "worker_output", "nonempty"])
def test_unsafe_or_overlapping_preparation_paths_reject_before_binding(case, kind):
    output = case.output
    if kind == "alias":
        output = case.root / "alias"
        output.symlink_to(case.output, target_is_directory=True)
    elif kind == "missing":
        output = case.root / "missing-output"
    elif kind == "worker_output":
        output = Path(case.specs[0].output_directory)
        output.mkdir()
    else:
        (output / "foreign.txt").write_text("existing user data")
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        _prepare_owned(case, output_root=str(output))
    assert _tables(case.registry) == before


def test_inspection_of_unbound_but_valid_request_does_not_create_binding(case):
    handle = _prepare_owned(case)
    request = _request(case, handle)
    request["worker_id"] = "unregistered-worker"
    path = case.root / "unbound-request.json"
    path.write_bytes(codec.encode_campaign_training_request(request))
    ref = case.registry.stage_artifact(path)
    before = _tables(case.registry)
    with pytest.raises(ERRORS):
        owned.inspect_campaign_training(case.registry, ref)
    assert _tables(case.registry) == before


def test_inspection_rejects_worker_output_created_after_status_observation(case, monkeypatch):
    handle = _prepare_owned(case)
    before = _tables(case.registry)
    journal = Path(handle["journal_path"])
    original_bytes = journal.read_bytes()
    output = Path(case.specs[-1].output_directory)
    original, calls = owned._guard_artifacts, []

    def create_after_guard(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        output.mkdir()
        return result

    monkeypatch.setattr(owned, "_guard_artifacts", create_after_guard)
    with pytest.raises(ERRORS):
        _report(case, handle)
    assert calls == [True] and output.is_dir()
    assert _tables(case.registry) == before
    assert journal.read_bytes() == original_bytes


@pytest.mark.parametrize("missing", ["journal", "lock"])
def test_final_inspection_journal_boundary_never_recreates_removed_file(case, monkeypatch, missing):
    handle = _prepare_owned(case)
    journal = Path(handle["journal_path"])
    lock = journal.with_name("." + journal.name + ".lock")
    victim, survivor = (journal, lock) if missing == "journal" else (lock, journal)
    survivor_bytes = survivor.read_bytes()
    before = _tables(case.registry)
    original, calls = owned._guard_artifacts, []

    def remove_after_guard(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        victim.unlink()
        return result

    monkeypatch.setattr(owned, "_guard_artifacts", remove_after_guard)
    with pytest.raises(ERRORS):
        _report(case, handle)
    assert calls == [True] and not victim.exists()
    assert survivor.read_bytes() == survivor_bytes
    assert _tables(case.registry) == before


def test_existing_only_journal_on_empty_directory_creates_nothing(tmp_path):
    with pytest.raises(ValueError):
        owned.DurableDaemonOperationJournal(tmp_path / "journal.json", {"fixture": True}, create=False)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing", ["journal", "lock"])
def test_default_journal_creation_and_existing_only_reopen_preserve_exact_bytes(tmp_path, missing):
    path, binding = tmp_path / "journal.json", {"fixture": True}
    lock = path.with_name("." + path.name + ".lock")
    with owned.DurableDaemonOperationJournal(path, binding) as journal:
        journal.set_metadata("fixture", {"created_with_default": True})
    before = {item: item.read_bytes() for item in (path, lock)}
    with owned.DurableDaemonOperationJournal(path, binding, create=False) as journal:
        assert journal.binding == binding
        assert journal.get_metadata("fixture") == {"created_with_default": True}
        assert journal.operations() == {}
    assert {item: item.read_bytes() for item in before} == before
    victim, survivor = (path, lock) if missing == "journal" else (lock, path)
    victim.unlink()
    with pytest.raises(ValueError):
        owned.DurableDaemonOperationJournal(path, binding, create=False)
    assert not victim.exists()
    assert survivor.read_bytes() == before[survivor]
    assert set(tmp_path.iterdir()) == {survivor}


@pytest.mark.parametrize("create", [0, 1, None, "false"])
def test_journal_create_flag_requires_boolean_before_any_filesystem_write(tmp_path, create):
    with pytest.raises(ValueError, match="create must be boolean"):
        owned.DurableDaemonOperationJournal(tmp_path / "journal.json", {"fixture": True}, create=create)
    assert list(tmp_path.iterdir()) == []


def test_pending_execution_intent_requires_recovery_without_claiming_a_pristine_run(case, monkeypatch):
    handle = _prepare_owned(case)
    path = Path(handle["journal_path"])
    binding = json.loads(path.read_bytes())["binding"]
    before = _tables(case.registry)
    calls = []
    payload = {"run_id": case.specs[0].run_id, "worker_id": "future-worker", "lease_seconds": 300.0}

    def fail_before_claim(operation_id, **kwargs):
        calls.append((operation_id, deepcopy(kwargs)))
        raise OSError("injected failure before any lease mutation")

    monkeypatch.setattr(case.registry, "claim_run", fail_before_claim)
    with owned.DurableDaemonOperationJournal(path, binding, create=False) as journal:
        with pytest.raises(OSError, match="before any lease mutation"):
            journal.invoke(case.registry, "future-claim", "ClaimRun", payload)
        pending = journal.pending()
        assert set(pending) == {"future-claim"}
        intent = pending["future-claim"]
        assert intent["command"] == "ClaimRun" and intent["payload"] == payload
        assert intent["receipt"] is None
        assert calls == [(intent["operation_id"], payload)]
    journal_bytes = path.read_bytes()
    assert _tables(case.registry) == before
    report = _report(case, handle)
    assert report["execution_history_present"] is True
    assert report["status"] == "recovery_required"
    assert report["pristine_queued_count"] == len(case.specs)
    assert all(row["registry_status"] == "queued" and row["attempt"] == row["fence"] == 0
               for row in report["batches"])
    with pytest.raises(ERRORS):
        _prepare_owned(case)
    assert len(calls) == 1
    assert path.read_bytes() == journal_bytes
    assert _tables(case.registry) == before


def test_foreign_tree_pin_rejects_before_plan_capture_or_artifact_mutation(case, monkeypatch):
    before = _tables(case.registry)
    cas_before = {str(path.relative_to(case.registry.artifact_root)): path.read_bytes()
                  for path in case.registry.artifact_root.rglob("*") if path.is_file()}
    monkeypatch.setattr(tree_pin, "workspace_root", lambda: case.root / "foreign-checkout")
    monkeypatch.setattr(owned, "_capture", _forbidden)
    with pytest.raises(owned.CampaignOwnedTrainingError, match="another checkout"):
        _prepare_owned(case)
    assert _tables(case.registry) == before
    assert {str(path.relative_to(case.registry.artifact_root)): path.read_bytes()
            for path in case.registry.artifact_root.rglob("*") if path.is_file()} == cas_before
    assert list(case.output.iterdir()) == []
