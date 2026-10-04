"""Current captured source to real CPU fitting and native model registration."""
from dataclasses import replace
import json
import threading

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts import codebase_feature_training as training
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
from .test_codebase_current import repository, scheduler, current_index, publish, change


@pytest.fixture
def prepared(repository, scheduler, current_index, tmp_path):
    for name, offset in (("second", 2), ("tune", 1), ("canary", 2)):
        (repository / (name + ".py")).write_text(f"def {name}(n: int) -> int:\n    return n + {offset}\n")
    index, _, _ = current_index
    head = publish(index, repository, scheduler[0], "initial").head
    samples = [training.CodebaseFeatureSample(role, IntegerOffsetContract(path, function, "n", offset))
        for role, path, function, offset in (("training", "counter.py", "increment", 1),
            ("training", "second.py", "second", 2), ("tuning", "tune.py", "tune", 1),
            ("canary", "canary.py", "canary", 2))]
    with AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "model-artifacts") as registry:
        yield index, head, samples, registry


def train(prepared, repository, scheduler, tmp_path, name="candidate", **options):
    index, head, samples, registry = prepared
    return training.train_current_codebase_features(index, repository, expected_head=head,
        registry=registry, directory=tmp_path / name, samples=samples, scheduler=scheduler[0], **options)


def test_native_training_registration_changed_source_and_exact_optimizer_resume(prepared, repository, scheduler, tmp_path):
    index, head, samples, registry = prepared
    first = train(prepared, repository, scheduler, tmp_path)
    assert first["status"] == "candidate_registered"
    assert first["training_executed"] and not first["behavior_authority"]
    parent_id = first["candidate"]["version_id"]
    parent = runtimes.load_version(registry, parent_id, domain="codebase_ir", version=training.RUNTIME_VERSION)
    state = parent.state
    assert first["report"]["attempted_epochs"] == 2
    assert state["completed_epochs"] > 0
    assert first["report"]["codebase_worker"]["runtime"]["intraop_threads"] == 1
    assert first["report"]["codebase_resource_limits"]["workspace_cleaned"]
    change(repository, 2)
    with pytest.raises(StaleCodebaseError):
        train(prepared, repository, scheduler, tmp_path, "stale", parent_version_id=parent_id)
    successor = publish(index, repository, scheduler[0], "edit", head).head
    # The authored goal stays1 while the captured body changes to2. Both atoms
    # already belong to the original training vocabulary; no columns are added.
    second = train((index, successor, samples, registry), repository, scheduler, tmp_path,
                   "child", parent_version_id=parent_id, epochs=1)
    assert second["status"] == "candidate_registered"
    child = runtimes.load_version(registry, second["candidate"]["version_id"], domain="codebase_ir", version=training.RUNTIME_VERSION)
    assert features.digest(parent.state) == features.digest(state)
    assert child.feature_space == parent.feature_space
    assert second["report"]["base_state_sha256"] == features.digest(state)
    assert child.state["completed_epochs"] > state["completed_epochs"]
    assert all(moment["step"] == child.state["completed_epochs"] for moment in child.state["adam"])
    assert second["report"]["codebase_cohort"]["roles"]["tuning"] == first["report"]["codebase_cohort"]["roles"]["tuning"]
    assert second["report"]["codebase_worker"]["canary_nonregression"]
    assert registry.get_version(child.parent_version_id)["parent_version_id"] == parent_id


@pytest.mark.parametrize("controls", [{"epochs": True}, {"epochs": 9}, {"memory_mb": 1024},
                                      {"timeout_seconds": 0}, {"admission_timeout_seconds": -1}])
def test_invalid_controls_never_start_training(prepared, repository, scheduler, tmp_path, monkeypatch, controls):
    monkeypatch.setattr(training, "_run_worker", lambda *a: pytest.fail("worker started"))
    with pytest.raises(training.CodebaseFeatureTrainingError):
        train(prepared, repository, scheduler, tmp_path, **controls)


def test_external_pressure_and_cancellation_refuse_before_source_reads(prepared, repository, scheduler, tmp_path, monkeypatch):
    owner, pressure, healthy = scheduler
    monkeypatch.setattr(prepared[0], "observe_current", lambda *a, **k: pytest.fail("source read before admission"))
    pressure[0] = replace(healthy, available_memory_mb=32)
    with pytest.raises(LeaseTimeoutError):
        train(prepared, repository, scheduler, tmp_path, admission_timeout_seconds=.02)
    pressure[0] = healthy
    event = threading.Event()
    event.set()
    with pytest.raises(LeaseCancelledError):
        train(prepared, repository, scheduler, tmp_path, cancel_event=event)


@pytest.mark.parametrize("role", ["training", "tuning", "canary"])
def test_unknown_features_refuse_before_numerical_work(prepared, repository, scheduler, tmp_path, monkeypatch, role):
    index, head, samples, registry = prepared
    if role == "training":
        # Raw-source duplication must be refused despite distinct selectors.
        (repository / "duplicate.py").write_bytes((repository / "counter.py").read_bytes())
        samples = [*samples, training.CodebaseFeatureSample("training", IntegerOffsetContract("duplicate.py", "increment", "n", 1))]
    else:
        selected = next(row for row in samples if row.role == role)
        (repository / selected.contract.path).write_text(f"def {selected.contract.function_name}(n: int) -> int:\n    return n + 99\n")
    successor = publish(index, repository, scheduler[0], "bad-cohort", head).head
    monkeypatch.setattr(training, "_run_worker", lambda *a: pytest.fail("numerical work started"))
    with pytest.raises(training.CodebaseFeatureTrainingError):
        train((index, successor, samples, registry), repository, scheduler, tmp_path)


@pytest.mark.parametrize("stage", ["worker", "registration"])
def test_source_drift_withholds_candidate_delivery(prepared, repository, scheduler, tmp_path, monkeypatch, stage):
    registered = []
    original_register = features.register_feature_candidate
    def register(*args, **kwargs):
        result = original_register(*args, **kwargs)
        registered.append(result)
        if stage == "registration":
            change(repository, 2)
        return result
    monkeypatch.setattr(features, "register_feature_candidate", register)
    if stage == "worker":
        original = training._run_worker
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            change(repository, 2)
            return result
        monkeypatch.setattr(training, "_run_worker", changed)
    with pytest.raises(StaleCodebaseError):
        train(prepared, repository, scheduler, tmp_path)
    assert len(registered) == (1 if stage == "registration" else 0)
    assert prepared[0].current(prepared[1].repository_id) == prepared[1]
    with prepared[3]._transaction() as connection:
        assert connection.execute("SELECT count(*) FROM autoencoder_control.heads").fetchone()[0] == 0


def test_native_worker_cancel_joins_process_and_cleans_workspace(prepared, repository, scheduler, tmp_path, monkeypatch):
    event = threading.Event()
    original = training.BoundedToolRunner.run
    observations = []
    def cancelled(runner, arguments, **options):
        timer = threading.Timer(.2, event.set)
        timer.start()
        try:
            result = original(runner, arguments, **options)
            observations.append(result)
            return result
        finally:
            timer.join()
    monkeypatch.setattr(training.BoundedToolRunner, "run", cancelled)
    with pytest.raises(LeaseCancelledError):
        train(prepared, repository, scheduler, tmp_path, cancel_event=event)
    assert len(observations) == 1
    assert observations[0].cancelled and observations[0].process_tree_terminated
    assert observations[0].workspace_cleaned
    assert not (tmp_path / "candidate").exists()


def test_child_admission_obeys_short_wait_budget(prepared, repository, scheduler, tmp_path, monkeypatch):
    owner, pressure, healthy = scheduler
    original = training._run_worker
    def pressure_before_child(*args, **kwargs):
        pressure[0] = replace(healthy, available_memory_mb=32)
        return original(*args, **kwargs)
    monkeypatch.setattr(training, "_run_worker", pressure_before_child)
    monkeypatch.setattr(training.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("worker launched under pressure"))
    import time
    started = time.monotonic()
    with pytest.raises(LeaseTimeoutError):
        train(prepared, repository, scheduler, tmp_path, admission_timeout_seconds=.02)
    assert time.monotonic() - started < 5


def test_saved_split_changes_and_new_atoms_cannot_silently_resume(prepared, repository, scheduler, tmp_path, monkeypatch):
    index, head, samples, registry = prepared
    first = train(prepared, repository, scheduler, tmp_path)
    parent_id = first["candidate"]["version_id"]
    monkeypatch.setattr(training, "_run_worker", lambda *a, **k: pytest.fail("bad successor started training"))
    changed_roles = [replace(row, role="canary" if row.role == "training" else "training" if row.role == "canary" else row.role)
                     for row in samples]
    with pytest.raises(training.CodebaseFeatureTrainingError):
        train((index, head, changed_roles, registry), repository, scheduler, tmp_path, "role-switch", parent_version_id=parent_id)
    change(repository, 99)
    successor = publish(index, repository, scheduler[0], "unseen", head).head
    with pytest.raises(training.CodebaseFeatureTrainingError, match="unknown atoms"):
        train((index, successor, samples, registry), repository, scheduler, tmp_path, "unknown", parent_version_id=parent_id)
    (repository / "tune.py").write_text("def tune(n: int) -> int:\n    return n + 2\n")
    newer = publish(index, repository, scheduler[0], "changed-tune", successor).head
    with pytest.raises(training.CodebaseFeatureTrainingError, match="tuning/canary source"):
        train((index, newer, samples, registry), repository, scheduler, tmp_path, "heldout", parent_version_id=parent_id)


def test_canary_regression_retains_parent_without_registering(prepared, repository, scheduler, tmp_path, monkeypatch):
    original = training._run_worker
    def regressed(*args, **kwargs):
        result, limits = original(*args, **kwargs)
        result["canary_nonregression"] = False
        return result, limits
    monkeypatch.setattr(training, "_run_worker", regressed)
    monkeypatch.setattr(features, "register_feature_candidate", lambda *a, **k: pytest.fail("regressing candidate registered"))
    result = train(prepared, repository, scheduler, tmp_path)
    assert result["status"] == "candidate_rejected" and result["candidate"] is None
    assert result["training_executed"] and not result["promotion_performed"]
