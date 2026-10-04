"""Native source-bound parent/child learning and currentness qualification."""
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError


@pytest.fixture
def native(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig

    repository = tmp_path / "source"
    repository.mkdir()
    for path, offset in (("train.py", 1), ("tune.py", 3), ("canary.py", 5)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {offset}\n")
    connection = duckdb.connect(str(tmp_path / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    cas = ImmutableCAS(tmp_path / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
                                   catalog=CodebaseCatalog(store, cas))
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    head = index.prepare_current(repository, repository_id="test:source-training", operation_id="initial",
                                 expected_head=None, scheduler=owner).head
    registry = AutoencoderRegistry(tmp_path / "model.duckdb", tmp_path / "model-artifacts")
    selections = [training.CodebaseTrainingSelection(path, role) for path, role in
                  (("train.py", "train"), ("tune.py", "tune"), ("canary.py", "canary"))]
    yield dict(index=index, repository=repository, expected_head=head, registry=registry,
               selections=selections, scheduler=owner, root=tmp_path, connection=connection)
    assert owner.snapshot()["active_lease_count"] == owner.snapshot()["waiting_request_count"] == 0
    registry.close()
    connection.close()


def train(native, **changes):
    arguments = {key: value for key, value in native.items() if key in
                 {"index", "repository", "expected_head", "registry", "selections", "scheduler"}}
    arguments.update(operation_id="bootstrap", epochs=1, learning_rate=.002)
    arguments.update(changes)
    return training.train_current_codebase_features(**arguments)


def saved(native, record):
    return runtimes._read_candidate(native["registry"], native["registry"].get_version(record.to_dict()["version_id"]))


def successor(native, source="def step(n: int) -> int:\n    return n + 2\n"):
    (native["repository"] / "train.py").write_text(source)
    result = native["index"].prepare_current(native["repository"], repository_id=native["expected_head"].repository_id,
        expected_head=native["expected_head"], operation_id="source-successor", scheduler=native["scheduler"])
    native["expected_head"] = result.head
    return result.head


def test_real_private_root_and_source_successor_keep_exact_basis_and_fixed_evaluation(native):
    parent = train(native)
    parent_saved = saved(native, parent)
    assert parent.observed_live and parent_saved["state"]["latent_width"] == 8
    assert parent_saved["state"]["completed_epochs"] == 1
    before = features.digest(parent_saved)
    old_head = native["expected_head"]
    successor(native)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="another complete source head"):
        training.infer_current_codebase_features(native["index"], native["repository"],
            expected_head=native["expected_head"], registry=native["registry"],
            version_id=parent.to_dict()["version_id"], paths=["train.py"], scheduler=native["scheduler"])
    child = train(native, operation_id="continue", parent_version_id=parent.to_dict()["version_id"])
    child_saved = saved(native, child)
    assert child.to_dict()["parent_version_id"] == parent.to_dict()["version_id"]
    assert child_saved["contract"] == parent_saved["contract"]
    assert child_saved["feature_space"] == parent_saved["feature_space"]
    assert child_saved["report"]["base_state_sha256"] == features.digest(parent_saved["state"])
    assert child_saved["state"]["completed_epochs"] == 2
    assert child_saved["state"]["parameters"] != parent_saved["state"]["parameters"]
    assert all(moment["step"] == 2 for moment in child_saved["state"]["adam"])
    provenance = child_saved["report"]["codebase_provenance"]
    for role in ("tuning_targets", "canary_targets", "replay_targets"):
        assert provenance[role] == parent_saved["report"]["codebase_provenance"][role]
    assert provenance["head"] != old_head.to_dict()
    assert provenance["continuation"] == "exact_frozen_basis_adam_resume"
    assert provenance["canary_monitoring"]["used_for_selection"] is False
    assert sum(row["unknown_atoms"] for row in child_saved["report"]["train_coverage"]) > 0
    assert len(provenance["training_targets"]) == 2  # New source plus immutable root replay.
    assert features.digest(saved(native, parent)) == before
    assert native["registry"].resolve_head(child.to_dict()["variant_id"], "main") is None
    assert all(value is False for value in child.to_dict()["authority"].values())
    inferred = training.infer_current_codebase_features(native["index"], native["repository"],
        expected_head=native["expected_head"], registry=native["registry"], version_id=child.to_dict()["version_id"],
        paths=["train.py"], scheduler=native["scheduler"])
    assert inferred["training_executed"] is False
    assert len(inferred["inference"]["rows"][0]["latent"]) == 8


def test_completed_bootstrap_and_child_retry_use_native_history_without_fitting(native, monkeypatch):
    parent = train(native)
    successor(native)
    child = train(native, operation_id="continue", parent_version_id=parent.to_dict()["version_id"])
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("completed retry fitted a model"))
    again = train(native, operation_id="continue", parent_version_id=parent.to_dict()["version_id"])
    assert again.artifact_cid == child.artifact_cid
    loaded = training.load_codebase_feature_training(native["index"], native["registry"], child.to_dict()["version_id"])
    assert not loaded.observed_live and loaded.to_dict() == child.to_dict()


def test_root_operation_replay_and_changed_configuration_refusal(native, monkeypatch):
    parent = train(native)
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("bootstrap retry fitted a model"))
    assert train(native).artifact_cid == parent.artifact_cid
    with pytest.raises(training.CodebaseFeatureTrainingError, match="another exact training request"):
        train(native, epochs=2)


def test_fixed_canary_source_change_requires_new_lineage_before_numerical_work(native, monkeypatch):
    parent = train(native)
    (native["repository"] / "canary.py").write_text("def step(n: int) -> int:\n    return n + 6\n")
    successor(native)
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("changed canary started fitting"))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="fixed evaluation source"):
        train(native, operation_id="continue", parent_version_id=parent.to_dict()["version_id"])


def test_content_leakage_is_rejected_even_when_paths_differ(native, monkeypatch):
    (native["repository"] / "tune.py").write_bytes((native["repository"] / "train.py").read_bytes())
    successor(native, source=(native["repository"] / "train.py").read_text())
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("leaked content trained"))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="leakage"):
        train(native)


def test_unsupported_source_does_not_launch_numerical_worker(native, monkeypatch):
    successor(native, source="def step(n: int) -> int:\n    return external(n)\n")
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("unsupported source trained"))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="unsupported feature extraction"):
        train(native)


def test_dirty_source_without_new_head_never_fits(native, monkeypatch):
    (native["repository"] / "train.py").write_text("def step(n: int) -> int:\n    return n + 2\n")
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("stale source trained"))
    with pytest.raises(StaleCodebaseError):
        train(native)


def test_source_edit_after_native_work_withholds_current_record(native, monkeypatch):
    original = training._worker
    def edit_after(*args, **kwargs):
        result = original(*args, **kwargs)
        (native["repository"] / "train.py").write_text("def step(n: int) -> int:\n    return n + 2\n")
        return result
    monkeypatch.setattr(training, "_worker", edit_after)
    with pytest.raises(StaleCodebaseError):
        train(native)
    with native["registry"]._transaction() as connection:
        assert connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0] == 0


def test_actual_worker_cancellation_fails_child_and_releases_native_process_resources(native, monkeypatch):
    parent = train(native)
    successor(native)
    event = threading.Event()
    original = training._worker
    def cancel_during(*args, **kwargs):
        timer = threading.Timer(.05, event.set)
        timer.start()
        try:
            return original(*args, **kwargs)
        finally:
            timer.cancel()
    monkeypatch.setattr(training, "_worker", cancel_during)
    with pytest.raises(LeaseCancelledError):
        train(native, operation_id="cancelled", parent_version_id=parent.to_dict()["version_id"], cancel_event=event)
    run = native["registry"].get_run("codebase-source:cancelled")
    assert run["status"] == "failed" and run["lease"] is None
    assert native["registry"].get_run_completion(run["run_id"]) is None


def test_native_fresh_process_reloads_parent_without_training_or_cas_writes(native):
    parent = train(native)
    version_id = parent.to_dict()["version_id"]
    native["registry"].close()
    native["connection"].close()
    script = r'''
import json, sys, duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
root = Path(sys.argv[1])
connection = duckdb.connect(str(root/'source.duckdb'))
store = DuckDBASTStore(connection=connection)
cas = ImmutableCAS(root/'source-artifacts')
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas, catalog=CodebaseCatalog(store,cas))
def forbidden(*args,**kwargs): raise AssertionError('historical read attempted fitting or writes')
training._worker = forbidden
cas.put = forbidden
with AutoencoderRegistry(root/'model.duckdb',root/'model-artifacts') as registry:
    record = training.load_codebase_feature_training(index, registry, sys.argv[2])
    assert record.observed_live is False
    print(json.dumps({'artifact_cid':record.artifact_cid,'version_id':record.to_dict()['version_id']}))
connection.close()
'''
    child = subprocess.run([sys.executable, "-c", script, str(native["root"]), version_id],
                           check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(child.stdout.splitlines()[-1])["artifact_cid"] == parent.artifact_cid


@pytest.mark.parametrize("configuration", [
    {"epochs": True}, {"epochs": 0}, {"learning_rate": float("inf")},
    {"seed": -1}, {"operation_id": "../escape"}, {"memory_mb": 64},
])
def test_invalid_numerical_or_admission_inputs_reject_before_worker(native, monkeypatch, configuration):
    monkeypatch.setattr(training, "_worker", lambda *args, **kwargs: pytest.fail("invalid numerical request executed"))
    with pytest.raises((ValueError, TypeError)):
        train(native, **configuration)


def test_inference_with_caller_training_options_is_rejected_by_api():
    import inspect
    assert "epochs" not in inspect.signature(training.infer_current_codebase_features).parameters
    assert "base_state" not in inspect.signature(training.train_current_codebase_features).parameters
