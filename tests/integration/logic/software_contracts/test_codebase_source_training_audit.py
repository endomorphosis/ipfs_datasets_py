"""Independent source-lineage and immutable checkpoint adversarial checks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import hashlib
import json
import subprocess
import threading

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as targets
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    root = tmp_path_factory.mktemp("source-training-independent-audit")
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("train.py", 1), ("tune.py", 2), ("canary.py", 3)):
        (repository / path).write_text(f"def increment(n: int) -> int:\n    return n + {value}\n")
    for args in (("init", "-q"), ("config", "user.name", "Independent Audit"),
                 ("config", "user.email", "audit@example.invalid"), ("add", "."),
                 ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(root / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    head = index.prepare_current(repository, repository_id="repository:independent-source-training-audit",
                                 operation_id="capture", expected_head=None, scheduler=scheduler).head
    selections = [training.CodebaseTrainingSelection(path, role)
                  for path, role in (("train.py", "train"), ("tune.py", "tune"), ("canary.py", "canary"))]
    with AutoencoderRegistry(root / "models.duckdb", root / "models") as registry:
        record = training.train_current_codebase_features(index, repository, expected_head=head, registry=registry,
            selections=selections, operation_id="root", scheduler=scheduler, epochs=1, learning_rate=0.002,
            timeout_seconds=120, memory_mb=1024)
        row = registry.get_version(record.to_dict()["version_id"])
        raw = registry.artifact_path(row["artifact"]).read_bytes()
        saved = json.loads(raw)
        yield root, repository, index, registry, scheduler, head, selections, record, row, raw, saved
        assert scheduler.snapshot()["active_lease_count"] == 0
        assert registry.resolve_head(row["variant_id"], "main") is None
    connection.close()


def _register_changed(trained, tmp_path, saved, name, *, raw=None):
    _, _, _, registry, _, _, _, _, row, _, _ = trained
    raw = training._wire(saved) if raw is None else raw
    path = tmp_path / (name + ".json")
    path.write_bytes(raw)
    artifact = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    receipt = registry.register_version("audit:" + name, row["variant_id"], artifact, row["metadata"])
    return receipt["version_id"]


def test_root_replay_neither_fits_nor_publishes_and_raw_cid_matches_bytes(trained, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
    _, _, index, registry, _, _, _, record, _, raw, _ = trained
    monkeypatch.setattr(index.artifacts, "put", lambda *a, **k: pytest.fail("historical replay published"))
    monkeypatch.setattr(training, "_worker", lambda *a, **k: pytest.fail("historical replay launched worker"))
    loaded = training.load_codebase_feature_training(index, registry, record.to_dict()["version_id"])
    assert loaded.to_dict() == record.to_dict()
    assert loaded.to_dict()["checkpoint_raw_cid"] == cid_for_bytes(raw)
    assert loaded.observed_live is False


def test_native_target_dict_roundtrip_is_validated_before_lineage_use(trained):
    _, _, _, _, _, _, _, _, _, _, saved = trained
    rows = saved["report"]["codebase_provenance"]["training_targets"]
    batch = training._batch(rows, training.CodebaseFeatureTrainingLimits())
    assert [item.to_dict() for item in batch] == rows


def test_forged_request_digest_is_not_an_independent_training_receipt(trained, tmp_path):
    _, _, index, registry, _, _, _, _, _, _, original = trained
    changed = copy.deepcopy(original)
    changed["report"]["codebase_request_sha256"] = "0" * 64
    version = _register_changed(trained, tmp_path, changed, "request")
    with pytest.raises(training.CodebaseFeatureTrainingError, match="request"):
        training._derive_training_record(index, registry, version)


@pytest.mark.parametrize("change", ["qualified", "training", "state", "selection"])
def test_nested_diagnostics_cannot_claim_authority_or_foreign_state(trained, tmp_path, change):
    _, _, index, registry, _, _, _, _, _, _, original = trained
    changed = copy.deepcopy(original)
    monitoring = changed["report"]["codebase_provenance"]["canary_monitoring"]
    if change == "qualified":
        monitoring["after"]["inference"]["qualified"] = True
    elif change == "training":
        monitoring["after"]["inference"]["training_executed"] = True
    elif change == "state":
        monitoring["after"]["inference"]["state_sha256"] = "0" * 64
    else:
        monitoring["used_for_selection"] = True
    version = _register_changed(trained, tmp_path, changed, "monitoring:" + change)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="diagnostic|monitor|canary|inference"):
        training._derive_training_record(index, registry, version)


def test_checkpoint_raw_identity_cannot_silently_canonicalize_other_bytes(trained, tmp_path):
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
    _, _, index, registry, _, _, _, _, _, original_raw, original = trained
    raw = b" \n" + original_raw + b"\n"
    version = _register_changed(trained, tmp_path, original, "whitespace", raw=raw)
    try:
        record = training._derive_training_record(index, registry, version)
    except training.CodebaseFeatureTrainingError as exc:
        assert "canonical" in str(exc) or "bytes" in str(exc)
    else:
        assert record.to_dict()["checkpoint_raw_cid"] == cid_for_bytes(raw)


@pytest.mark.parametrize("change", ["tuning_targets_sha256", "learning_rate"])
def test_saved_resume_state_cannot_change_recorded_tuning_or_optimizer(trained, tmp_path, change):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    _, _, index, registry, _, _, _, _, _, _, original = trained
    changed = copy.deepcopy(original)
    if change == "tuning_targets_sha256":
        changed["state"][change] = "0" * 64
    else:
        changed["state"]["optimizer_config"][change] = 0.03
    state_digest = features.digest(changed["state"])
    provenance = changed["report"]["codebase_provenance"]
    provenance["canary_monitoring"]["after"]["inference"]["state_sha256"] = state_digest
    provenance["replay_monitoring"]["inference"]["state_sha256"] = state_digest
    version = _register_changed(trained, tmp_path, changed, "resume:" + change)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="tuning|optimizer|state"):
        training._derive_training_record(index, registry, version)


def test_fixed_split_rejects_edited_ancestor_path_even_with_new_digest(trained):
    _, _, _, _, _, _, _, _, _, _, saved = trained
    provenance = saved["report"]["codebase_provenance"]
    train, tune, canary = [training._batch(provenance[name + "_targets"], training.CodebaseFeatureTrainingLimits())
                           for name in ("training", "tuning", "canary")]
    binding = targets.source_binding_from_target(tune[0])
    history = [{"repository_id": binding["repository_id"], "path": binding["path"], "source_digest": "f" * 64}]
    with pytest.raises(training.CodebaseFeatureTrainingError, match="path.*leakage"):
        training._split_check(train, tune, canary, history)


def _train_again(trained, operation_id, **changes):
    _, repository, index, registry, scheduler, head, selections, _, _, _, _ = trained
    arguments = dict(expected_head=head, registry=registry, selections=selections,
                     operation_id=operation_id, scheduler=scheduler, epochs=1, learning_rate=0.002,
                     timeout_seconds=120, memory_mb=1024)
    arguments.update(changes)
    return training.train_current_codebase_features(index, repository, **arguments)


def test_duplicate_active_bootstrap_runs_once_without_blocking_native_registry(trained, monkeypatch):
    _, _, _, registry, _, _, _, record, _, _, _ = trained
    entered, release = threading.Event(), threading.Event()
    calls = []
    original_worker = training._worker
    def blocked_worker(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(15), "test did not release the native fitting worker"
        return original_worker(*args, **kwargs)
    monkeypatch.setattr(training, "_worker", blocked_worker)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(_train_again, trained, "race-root")
        assert entered.wait(15)
        try:
            second = pool.submit(_train_again, trained, "race-root")
            with pytest.raises(training.CodebaseFeatureTrainingError, match="busy|active|concurrent"):
                second.result(timeout=5)
            # Bootstrap fitting must not hold the model owner's transaction lock.
            unrelated = pool.submit(registry.get_version, record.to_dict()["version_id"])
            assert unrelated.result(timeout=5)["version_id"] == record.to_dict()["version_id"]
        finally:
            release.set()
        assert first.result(timeout=30).observed_live is True
    assert calls == [1]


def test_racing_native_child_claims_cannot_share_an_idempotent_lease(trained, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import RegistryError
    _, _, _, registry, _, _, _, record, _, _, _ = trained
    barrier = threading.Barrier(2)
    claim, worker = registry.claim_run, training._worker
    calls, claimed_operations = [], []
    def simultaneous_claim(operation_id, run_id, *args, **kwargs):
        if run_id == "codebase-source:race-child":
            claimed_operations.append(operation_id)
            barrier.wait(timeout=15)
        return claim(operation_id, run_id, *args, **kwargs)
    def counted_worker(*args, **kwargs):
        calls.append(1)
        return worker(*args, **kwargs)
    monkeypatch.setattr(registry, "claim_run", simultaneous_claim)
    monkeypatch.setattr(training, "_worker", counted_worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_train_again, trained, "race-child",
                               parent_version_id=record.to_dict()["version_id"]) for _ in range(2)]
        successful, refused = [], []
        for future in futures:
            try:
                successful.append(future.result(timeout=30))
            except RegistryError as exc:
                refused.append(str(exc))
    assert len(successful) == len(refused) == 1
    assert "already leased" in refused[0]
    assert len(claimed_operations) == len(set(claimed_operations)) == 2
    assert calls == [1]
    assert registry.get_run("codebase-source:race-child")["status"] == "completed"


def test_prospective_child_depth_refuses_before_fitting(trained, monkeypatch):
    _, _, _, _, _, _, _, record, _, _, _ = trained
    limits = replace(training.CodebaseFeatureTrainingLimits(), max_ancestry=1)
    monkeypatch.setattr(training, "_worker", lambda *a, **k: pytest.fail("oversized ancestry launched worker"))
    with pytest.raises(training.CodebaseFeatureTrainingError, match="prospective.*ancestry"):
        _train_again(trained, "depth-refused", parent_version_id=record.to_dict()["version_id"], limits=limits)


def test_prospective_child_bytes_fail_without_registering_an_unloadable_version(trained):
    _, _, _, registry, _, _, _, record, row, _, _ = trained
    limits = replace(training.CodebaseFeatureTrainingLimits(), max_ancestry_bytes=row["artifact"]["bytes"])
    with registry._transaction() as connection:
        count_before = connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
    with pytest.raises(training.CodebaseFeatureTrainingError, match="ancestry.*byte|byte.*ancestry"):
        _train_again(trained, "bytes-refused", parent_version_id=record.to_dict()["version_id"], limits=limits)
    with registry._transaction() as connection:
        count_after = connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
    assert count_after == count_before
    assert registry.get_run("codebase-source:bytes-refused")["status"] == "failed"
