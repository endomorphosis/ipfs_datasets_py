"""Real CodebaseIR parameter updates, weighted aggregation and fresh Adam policy."""
from dataclasses import replace
import copy
import json
import math
import subprocess

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated as federation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_federated_codebase as adapter
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import (
    read_client_update, write_client_update,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    root = tmp_path_factory.mktemp("federated-codebase-native")
    repository = root / "repository"
    repository.mkdir()
    for value in range(1, 7):
        (repository / f"increment_{value}.py").write_text(
            f"def increment(n: int) -> int:\n    return n + {value}\n", encoding="utf-8")
    for arguments in (("init", "-q"), ("config", "user.name", "Federated Fixture"),
                      ("config", "user.email", "fixture@example.invalid"),
                      ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(root / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8,8192,8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    head = index.prepare_current(repository, repository_id="repository:federation-fixture",
        operation_id="capture", expected_head=None, scheduler=owner).head
    targets = [runtimes.prepare_targets("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        index=index, expected_head=head, path=f"increment_{value}.py") for value in range(1, 7)]
    train, tune = targets[:4], targets[4:]
    runtime = runtimes.build_source_bound_codebase_runtime(train)
    runtime.train(train, validation_samples=tune, epochs=1, learning_rate=0.0001)
    with AutoencoderRegistry(root / "models.duckdb", root / "models") as registry:
        receipt = runtime.register_candidate(registry, root / "parent")
        loaded = runtimes.load_version(registry, receipt["version_id"], domain="codebase_ir",
                                       version=runtimes.CODEBASE_SOURCE_FEATURE_VERSION)
        sha = registry.get_version(receipt["version_id"])["artifact"]["sha256"]
    base = adapter.CodebaseFeatureCheckpoint.from_runtime(loaded, base_sha256=sha,
                                                          base_version_id=receipt["version_id"])
    clients = (federation.ClientSpec("a", 3, features.digest([target.to_dict() for target in train[:3]])),
               federation.ClientSpec("b", 1, features.digest([target.to_dict() for target in train[3:]])))
    round_spec = base.build_round("round:codebase", "lineage:fixture8d", clients, max_local_steps=2)
    local = [features.train_projection_features(base.contract, base.feature_space, rows, tune,
        base_state=base.state, epochs=1, latent_width=8, learning_rate=0.0001)
        for rows in (train[:3], train[3:])]
    updates = [base.build_update(round_spec, client.client_id, result["state"], result["report"]["attempted_epochs"])
               for client, result in zip(clients, local)]
    yield base, round_spec, local, updates, targets
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


def _candidate(native):
    base, round_spec, _, updates, _ = native
    return federation.aggregate_round(round_spec, base.parameters, updates)


def _flat(array):
    return [value for row in array for value in row] if array and type(array[0]) is list else list(array)


def test_actual_native_clients_weighted_binary_update_and_reset_materialization(native, tmp_path):
    base, round_spec, local, updates, targets = native
    assert base.state["completed_epochs"] >= 1
    assert all(result["report"]["attempted_epochs"] == 1 for result in local)
    assert any(update.deltas[name][index] != 0 for update in updates
               for name, row in update.deltas.items() for index in row)
    reread = []
    for update in updates:
        path = tmp_path / (update.client_id + ".update")
        artifact = write_client_update(path, round_spec, update)
        restored = read_client_update(path, round_spec, expected_sha256=artifact["sha256"],
                                      expected_cidv1=artifact["cidv1"])
        assert restored == update and restored.update_sha256 == update.update_sha256
        reread.append(restored)
    aggregate = federation.aggregate_round(round_spec, base.parameters, reread)
    assert aggregate == federation.aggregate_round(round_spec, base.parameters, list(reversed(reread)))
    for name, values in base.parameters.items():
        for index, initial in enumerate(values):
            expected = math.fsum((initial, updates[0].deltas[name][index] * 0.75,
                                  updates[1].deltas[name][index] * 0.25))
            assert aggregate.parameters[name][index] == expected
    state = base.materialize_state(round_spec, aggregate)
    assert state["parameters"] != base.state["parameters"]
    assert state["completed_epochs"] == 0
    assert state["optimizer_config"] == base.state["optimizer_config"]
    assert state["tuning_targets_sha256"] == base.state["tuning_targets_sha256"]
    assert all(moment["step"] == 0 for moment in state["adam"])
    assert all(value == 0.0 for moment in state["adam"]
               for key in ("exp_avg", "exp_avg_sq") for value in _flat(moment[key]))
    assert any(value != 0.0 for moment in base.state["adam"] for value in _flat(moment["exp_avg"]))
    runtime = runtimes.open_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        contract=base.contract, feature_space=base.feature_space, state=state)
    inference = runtime.infer(targets[4:])
    assert inference["training_executed"] is False and inference["decoded_formulas_generated"] is False
    assert all(inference[key] is False for key in features.FALSE)


def test_exact_profile_has_only_four_float64_parameters_and_no_gte(native):
    base, round_spec, *_ = native
    assert round_spec.dimension == 8 and round_spec.architecture == adapter.PROFILE
    assert round_spec.runtime_profile == adapter.RUNTIME_PROFILE
    assert len(base.parameter_specs) == 4 and all(spec.dtype == "float64" for spec in base.parameter_specs)
    assert set(base.parameters) == {"encoder.weight", "encoder.bias", "decoder.weight", "decoder.bias"}
    assert base.base_parameters_sha256 == federation.parameter_digest(base.parameter_specs, base.parameters)
    assert round_spec.embedding_producer_sha256 == features.digest(base.semantic_profile)
    assert "gte" not in json.dumps(base.semantic_profile).lower()
    descriptor = adapter.describe_profile()
    assert descriptor["aggregate_optimizer_policy"] == adapter.OPTIMIZER_POLICY
    assert all(descriptor[key] is False for key in ("registry_writes", "artifact_writes", "proof_authority",
                                                   "semantic_decoder", "qualified", "admitted", "promotion_performed"))


def test_detached_owned_base_update_and_materialized_state(native):
    base, round_spec, local, _, _ = native
    initial = base.state
    copy_state = base.state
    copy_state["parameters"][0][0][0] += 99
    space = base.feature_space
    space["columns"][0][1] = "changed"
    assert base.state == initial and base.feature_space != space
    trained = copy.deepcopy(local[0]["state"])
    update = base.build_update(round_spec, "a", trained, 1)
    commitment = update.update_sha256
    trained["parameters"][0][0][0] += 99
    assert update.update_sha256 == commitment
    materialized = base.materialize_state(round_spec, _candidate(native))
    materialized["parameters"][0][0][0] += 99
    assert base.state == initial


@pytest.mark.parametrize("change", ["dimension", "base_sha256", "base_parameters_sha256", "embedding_producer_sha256",
                                    "architecture", "runtime_profile", "model_id", "parameters"])
def test_foreign_base_semantics_layout_and_384d_round_rejected(native, change):
    base, round_spec, *_ = native
    if change == "dimension":
        value = 384
    elif change.endswith("sha256"):
        value = "0" * 64
    elif change == "parameters":
        value = tuple(replace(spec, dtype="float32") for spec in round_spec.parameters)
    else:
        value = "another-profile"
    changed = replace(round_spec, **{change: value})
    with pytest.raises(ValueError, match="another CodebaseIR"):
        base.validate_round(changed)


@pytest.mark.parametrize("change", ["tuning", "optimizer", "progress", "latent", "authority", "nan", "shape"])
def test_local_state_cannot_change_fixed_semantics_or_policy(native, change):
    base, round_spec, local, *_ = native
    state = copy.deepcopy(local[0]["state"])
    if change == "tuning":
        state["tuning_targets_sha256"] = "0" * 64
    elif change == "optimizer":
        state["optimizer_config"]["learning_rate"] *= 2
    elif change == "progress":
        state["completed_epochs"] += 9
        for moment in state["adam"]:
            moment["step"] = state["completed_epochs"]
    elif change == "latent":
        state["latent_width"] = 384
    elif change == "authority":
        state["qualified"] = True
    elif change == "nan":
        state["parameters"][0][0][0] = math.nan
    else:
        state["parameters"][0].pop()
    with pytest.raises(ValueError):
        base.build_update(round_spec, "a", state, 1)


@pytest.mark.parametrize("steps", [0, True, -1, 3])
def test_local_work_bound_is_positive_builtin_and_owner_bounded(native, steps):
    base, round_spec, local, *_ = native
    with pytest.raises(ValueError, match="local_steps"):
        base.build_update(round_spec, "a", local[0]["state"], steps)


def test_actual_attempted_work_can_select_unchanged_parent_without_inventing_progress(native):
    base, round_spec, *_ = native
    update = base.build_update(round_spec, "a", base.state, 1)
    assert update.local_steps == 1
    assert all(value == 0.0 for coordinates in update.deltas.values() for value in coordinates.values())
    with pytest.raises(ValueError, match="local_steps"):
        base.build_update(round_spec, "a", base.state, 0)


def test_unknown_client_and_candidate_from_different_complete_round_rejected(native):
    base, round_spec, local, *_ = native
    with pytest.raises(ValueError, match="not approved"):
        base.build_update(round_spec, "unknown", local[0]["state"], 1)
    foreign = replace(round_spec, round_id="another-round")
    with pytest.raises(ValueError, match="another complete CodebaseIR round"):
        base.materialize_state(foreign, _candidate(native))


def test_unsafe_frozen_objects_revalidate_before_reduction_materialization(native):
    base, round_spec, *_ = native
    poisoned = copy.copy(round_spec)
    object.__setattr__(poisoned.parameters[0], "dtype", "malicious")
    try:
        with pytest.raises(ValueError, match="dtype"):
            base.validate_round(poisoned)
    finally:
        object.__setattr__(poisoned.parameters[0], "dtype", "float64")
    candidate = _candidate(native)
    object.__setattr__(candidate, "candidate_sha256", "0" * 64)
    with pytest.raises(ValueError, match="digest"):
        base.materialize_state(round_spec, candidate)


@pytest.mark.parametrize("field", ["base_sha256", "base_version_id"])
def test_base_references_are_strict_owned_hashes(native, field):
    base, *_ = native
    values = {"base_sha256": base.base_sha256, "base_version_id": base.base_version_id}
    values[field] = "not-an-artifact-digest"
    with pytest.raises(ValueError, match="SHA256|native sha256"):
        adapter.CodebaseFeatureCheckpoint(base._snapshot_json, **values)


def test_noncanonical_or_384d_snapshot_and_nonexact_runtime_rejected(native):
    base, *_ = native
    with pytest.raises(ValueError, match="canonical"):
        adapter.CodebaseFeatureCheckpoint(base._snapshot_json + b"\n", base.base_sha256, base.base_version_id)
    snapshot = json.loads(base._snapshot_json)
    snapshot["contract"]["state_codec"]["version"] = "1:latent-384"
    with pytest.raises(ValueError, match="8D"):
        adapter.CodebaseFeatureCheckpoint(adapter._wire(snapshot), base.base_sha256, base.base_version_id)
    with pytest.raises(ValueError, match="exact SourceBound"):
        adapter.CodebaseFeatureCheckpoint.from_runtime(object(), base_sha256=base.base_sha256,
                                                       base_version_id=base.base_version_id)
