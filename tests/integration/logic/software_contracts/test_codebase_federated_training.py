"""Real source-owned CodebaseIR FedAvg, replay and lifecycle checks."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import TrainingMode, GradientBackendUnavailable


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    root = tmp_path_factory.mktemp("codebase-federated-native")
    repo = root / "source"
    repo.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repo / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    cas = ImmutableCAS(root / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
        catalog=CodebaseCatalog(store, cas))
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    head = index.prepare_current(repo, repository_id="test:codebase-federated", operation_id="capture",
                                 expected_head=None, scheduler=scheduler).head
    registry = AutoencoderRegistry(root / "model.duckdb", root / "model-artifacts")
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(index, repo, expected_head=head, registry=registry,
        selections=selections, operation_id="root", epochs=1, learning_rate=.002, scheduler=scheduler)
    state = {"root": root, "repository": repo, "index": index, "registry": registry, "scheduler": scheduler,
             "expected_head": head, "parent": parent, "connection": connection,
             "clients": [federation.CodebaseFederatedClient("two", ("a.py", "b.py")),
                         federation.CodebaseFederatedClient("one", ("c.py",))]}
    state["round"] = train(state)
    yield state
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    registry.close()
    connection.close()


def train(native, **changes):
    args = {name: native[name] for name in ("index", "repository", "registry", "scheduler", "expected_head", "clients")}
    args.update(base_version_id=native["parent"].to_dict()["version_id"], operation_id="round", epochs=1, learning_rate=.002)
    args.update(changes)
    return federation.train_current_codebase_federated_round(**args)


def saved(native, record):
    return runtimes._read_candidate(native["registry"], native["registry"].get_version(record.to_dict()["version_id"]))


def test_actual_weighted_round_and_reset_have_exact_parent_and_source_counts(native):
    parent, aggregate = saved(native, native["parent"]), saved(native, native["round"])
    report = aggregate["report"]["codebase_federation"]
    assert aggregate["feature_space"] == parent["feature_space"] and aggregate["contract"] == parent["contract"]
    assert report["optimizer_policy"] == federation.OPTIMIZER_POLICY
    assert [(row["client_id"], row["sample_count"]) for row in report["round"]["clients"]] == [("one", 1), ("two", 2)]
    assert sum(len(row["local_payload"]["training_targets"]) for row in report["clients"]) == 3
    assert all(row["training_report"]["attempted_epochs"] == 1 for row in report["clients"])
    assert all(row["training_report"]["base_state_sha256"] == features.digest(parent["state"]) for row in report["clients"])
    assert aggregate["state"]["completed_epochs"] == 0
    assert aggregate["state"]["parameters"] != parent["state"]["parameters"]
    def flatten(values):
        return [n for row in values for n in row] if isinstance(values[0], list) else values
    for item in aggregate["state"]["adam"]:
        assert item["step"] == 0
        assert not any(flatten(item["exp_avg"])) and not any(flatten(item["exp_avg_sq"]))
    assert aggregate["state"]["optimizer_config"] == parent["state"]["optimizer_config"]
    assert aggregate["state"]["tuning_targets_sha256"] == parent["state"]["tuning_targets_sha256"]
    assert report["evaluation"]["used_for_selection"] is False
    assert native["registry"].resolve_head(native["round"].to_dict()["variant_id"], "main") is None
    assert all(flag is False for flag in native["round"].to_dict()["authority"].values())


def test_completed_retry_and_pure_historical_replay_do_not_fit(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("completed retry launched worker"))
    assert train(native).artifact_cid == native["round"].artifact_cid
    monkeypatch.setattr(native["index"].artifacts, "put", lambda *a, **k: pytest.fail("historical load published"))
    loaded = federation.load_codebase_federated_training(native["index"], native["registry"], native["round"].to_dict()["version_id"])
    assert loaded.to_dict() == native["round"].to_dict() and loaded.observed_live is False
    assert source.load_codebase_feature_training(native["index"], native["registry"], native["parent"].to_dict()["version_id"]).artifact_cid == native["parent"].artifact_cid
    with pytest.raises(RegistryError, match="payload|operation"):
        train(native, seed=1)


@pytest.mark.parametrize("clients", [
    [federation.CodebaseFederatedClient("x", ("a.py",)), federation.CodebaseFederatedClient("y", ("b.py",))],
    [federation.CodebaseFederatedClient("x", ("a.py", "b.py")), federation.CodebaseFederatedClient("y", ("a.py", "c.py"))],
    [federation.CodebaseFederatedClient("x", ("a.py", "b.py")), federation.CodebaseFederatedClient("y", ("tune.py",))],
    [federation.CodebaseFederatedClient("x", ("a.py", "b.py")), federation.CodebaseFederatedClient("x", ("c.py",))],
])
def test_invalid_partition_rejects_before_worker(native, monkeypatch, clients):
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("invalid partition fitted"))
    with pytest.raises(source.CodebaseFeatureTrainingError):
        train(native, clients=clients, operation_id="invalid-partition")


def test_gradient_request_fails_before_source_work(native, monkeypatch):
    monkeypatch.setattr(source, "_native_owners", lambda *a, **k: pytest.fail("unavailable gradient read owner"))
    with pytest.raises(GradientBackendUnavailable):
        train(native, mode=TrainingMode.GRADIENT_SYNCHRONIZED)


def test_second_aggregate_round_can_use_reset_parent(native):
    child = train(native, base_version_id=native["round"].to_dict()["version_id"], operation_id="second-round")
    assert child.to_dict()["parent_version_id"] == native["round"].to_dict()["version_id"]
    child_saved = saved(native, child)
    assert child_saved["state"]["completed_epochs"] == 0
    assert child_saved["report"]["codebase_federation"]["origin_version_id"] == native["parent"].to_dict()["version_id"]
    assert federation.load_codebase_federated_training(native["index"], native["registry"], child.to_dict()["version_id"]).artifact_cid == child.artifact_cid


def test_exact_current_aggregate_inference_never_fits(native):
    result = federation.infer_current_codebase_federated_features(native["index"], native["repository"],
        expected_head=native["expected_head"], registry=native["registry"], version_id=native["round"].to_dict()["version_id"],
        paths=["a.py"], scheduler=native["scheduler"])
    assert result["training_executed"] is False and result["proof_authority"] is False


def test_actual_cancelled_local_job_clears_native_round_lease(native, monkeypatch):
    event = threading.Event()
    worker = source._worker
    def cancelled(*args, **kwargs):
        timer = threading.Timer(.05, event.set)
        timer.start()
        try:
            return worker(*args, **kwargs)
        finally:
            timer.cancel()
    monkeypatch.setattr(source, "_worker", cancelled)
    with pytest.raises(schedulers.LeaseCancelledError):
        train(native, operation_id="cancelled-round", cancel_event=event)
    row = native["registry"].get_run("codebase-fed:cancelled-round")
    assert row["status"] == "failed" and row["lease"] is None
    assert native["registry"].get_run_completion(row["run_id"]) is None


def test_racing_claims_use_distinct_leases_and_only_one_worker_set(native, monkeypatch):
    barrier = threading.Barrier(2)
    claim, worker = native["registry"].claim_run, source._worker
    operations, calls = [], []
    def racing(operation_id, run_id, *args, **kwargs):
        if run_id == "codebase-fed:race-round":
            operations.append(operation_id)
            barrier.wait(timeout=20)
        return claim(operation_id, run_id, *args, **kwargs)
    def counted(*args, **kwargs):
        calls.append(kwargs["action"])
        return worker(*args, **kwargs)
    monkeypatch.setattr(native["registry"], "claim_run", racing)
    monkeypatch.setattr(source, "_worker", counted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(train, native, operation_id="race-round") for _ in range(2)]
        success, refused = 0, 0
        for job in jobs:
            try:
                job.result(timeout=60)
                success += 1
            except RegistryError as error:
                assert "already leased" in str(error)
                refused += 1
    assert success == refused == 1 and len(set(operations)) == 2
    assert calls.count("train") == 2 and calls.count("infer") == 2


def test_prospective_ancestry_rejects_without_fit(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("oversized ancestry fitted"))
    with pytest.raises(source.CodebaseFeatureTrainingError, match="prospective.*depth"):
        train(native, operation_id="depth-refused", limits=replace(source.CodebaseFeatureTrainingLimits(), max_ancestry=1))


def test_prospective_total_artifact_bytes_refuse_before_version_publication(native):
    registry = native["registry"]
    artifact_bytes = registry.get_version(native["parent"].to_dict()["version_id"])["artifact"]["bytes"]
    with registry._transaction() as connection:
        before = connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
    with pytest.raises(source.CodebaseFeatureTrainingError, match="prospective.*bytes"):
        train(native, operation_id="bytes-refused", limits=replace(source.CodebaseFeatureTrainingLimits(), max_ancestry_bytes=artifact_bytes))
    with registry._transaction() as connection:
        after = connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
    assert before == after and registry.get_run("codebase-fed:bytes-refused")["status"] == "failed"


@pytest.mark.parametrize("edit", ["local-count", "adam", "eval-authority", "binary-reference", "local-step"])
def test_native_completed_but_forged_candidate_rejects_semantic_replay(native, tmp_path, edit):
    registry = native["registry"]
    row = registry.get_version(native["round"].to_dict()["version_id"])
    changed = copy.deepcopy(saved(native, native["round"]))
    report = changed["report"]["codebase_federation"]
    if edit == "local-count":
        report["clients"][0]["local_payload"]["sample_count"] += 1
    elif edit == "adam":
        changed["state"]["adam"][0]["exp_avg"][0][0] = 1.0
    elif edit == "eval-authority":
        report["evaluation"]["used_for_selection"] = True
    elif edit == "binary-reference":
        report["clients"][0]["update_cid"] = report["clients"][1]["update_cid"]
    else:
        report["clients"][0]["training_report"]["attempted_epochs"] = 0
    original_run = registry.get_run(row["metadata"]["producer_run"])
    run_id = "forged-" + edit
    registry.create_run(run_id + ":create", run_id, row["variant_id"], row["parent_version_id"], original_run["spec"])
    lease = registry.claim_run(run_id + ":claim", run_id, "audit")["lease"]
    for client in report["clients"]:
        client["work_binding"]["attempt"] = lease["attempt"]
        client["work_binding"]["fence"] = lease["fence"]
    path = tmp_path / (run_id + ".json")
    path.write_bytes(source._wire(changed))
    artifact = registry.stage_artifact(path)
    completed = registry.complete_run(run_id + ":complete", lease, artifact, row["metadata"]["result"])
    with pytest.raises(ValueError):
        federation._record(native["index"], registry, completed["version_id"], source.CodebaseFeatureTrainingLimits())


def test_successor_head_unknown_features_fences_old_model_and_keeps_fixed_canaries(native, monkeypatch):
    old = native["expected_head"]
    (native["repository"] / "a.py").write_text("def step(n: int) -> int:\n    return n + 11\n")
    native["expected_head"] = native["index"].prepare_current(native["repository"], repository_id=old.repository_id,
        operation_id="successor", expected_head=old, scheduler=native["scheduler"]).head
    with monkeypatch.context() as guarded:
        guarded.setattr(source, "_worker", lambda *a, **k: pytest.fail("stale inference fitted or ran"))
        with pytest.raises(source.CodebaseFeatureTrainingError, match="another complete source head"):
            federation.infer_current_codebase_federated_features(native["index"], native["repository"],
                expected_head=native["expected_head"], registry=native["registry"], version_id=native["round"].to_dict()["version_id"],
                paths=["a.py"], scheduler=native["scheduler"])
    child = train(native, base_version_id=native["round"].to_dict()["version_id"], operation_id="source-successor-round")
    report = saved(native, child)["report"]["codebase_federation"]
    assert any(row["unknown_atoms"] > 0 for item in report["clients"] for row in item["training_report"]["train_coverage"])
    assert report["evaluation"]["aggregate"]["canary"]["source_digests"] == saved(native, native["round"])["report"]["codebase_federation"]["evaluation"]["aggregate"]["canary"]["source_digests"]
    native["successor_round"] = child


def test_interrupted_metadata_publication_recovers_historically_without_refitting(native, monkeypatch):
    put = native["index"].artifacts.put
    def interrupted(value):
        if value.get("schema") == federation.SCHEMA:
            raise RuntimeError("interrupted provenance publication")
        return put(value)
    with monkeypatch.context() as failing:
        failing.setattr(native["index"].artifacts, "put", interrupted)
        with pytest.raises(RuntimeError, match="interrupted provenance"):
            train(native, base_version_id=native["successor_round"].to_dict()["version_id"], operation_id="publication-gap")
    completion = native["registry"].get_run_completion("codebase-fed:publication-gap")
    assert completion is not None
    version_id = completion["candidate_version"]["version_id"]
    # Recovery is also valid after this captured source view is superseded.
    head = native["expected_head"]
    (native["repository"] / "b.py").write_text("def step(n: int) -> int:\n    return n + 12\n")
    native["expected_head"] = native["index"].prepare_current(native["repository"], repository_id=head.repository_id,
        operation_id="post-gap-successor", expected_head=head, scheduler=native["scheduler"]).head
    with monkeypatch.context() as guarded:
        guarded.setattr(source, "_worker", lambda *a, **k: pytest.fail("recovery fitted or inferred"))
        guarded.setattr(native["index"], "observe_current", lambda *a, **k: pytest.fail("recovery scanned live source"))
        recovered = federation.recover_codebase_federated_training(native["index"], native["registry"], version_id)
        assert recovered.observed_live is False and recovered.to_dict()["head"] == head.to_dict()
        assert federation.load_codebase_federated_training(native["index"], native["registry"], version_id).artifact_cid == recovered.artifact_cid


def test_fresh_process_historical_replay_checks_binary_reduction_without_work_or_writes(native):
    native["registry"].close()
    native["connection"].close()
    script = r'''
import json,sys,duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source, codebase_federated_training as federation
root=Path(sys.argv[1])
connection=duckdb.connect(str(root/'source.duckdb'))
store=DuckDBASTStore(connection=connection)
cas=ImmutableCAS(root/'source-artifacts')
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
def forbidden(*a,**k): raise AssertionError('historical replay attempted execution/publication')
source._worker=forbidden
cas.put=forbidden
index.observe_current=forbidden
with AutoencoderRegistry(root/'model.duckdb',root/'model-artifacts') as registry:
    registry.stage_artifact=forbidden
    records=[federation.load_codebase_federated_training(index,registry,value) for value in sys.argv[2:]]
    assert all(record.observed_live is False for record in records)
    print(json.dumps([record.artifact_cid for record in records]))
connection.close()
'''
    records = [native["round"], native["successor_round"]]
    child = subprocess.run([sys.executable, "-c", script, str(native["root"]), *(item.to_dict()["version_id"] for item in records)],
        check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(child.stdout.splitlines()[-1]) == [item.artifact_cid for item in records]
