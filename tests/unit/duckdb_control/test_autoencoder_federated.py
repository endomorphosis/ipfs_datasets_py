"""Real registry integration, with synthetic complete-checkpoint fixtures.

These tests verify aggregation/ownership/storage behavior, not Legal quality or
compatibility of a JSON fixture with a production model checkpoint.
"""

from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_federated import (
    complete_federated_run,
    create_federated_run,
)
from ipfs_datasets_py.duckdb_control.autoencoder_registry import (
    AutoencoderRegistry,
    RegistryError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    ClientSpec,
    FederatedRound,
    ParameterSpec,
    aggregate_round,
    make_client_update,
    parameter_digest,
)


def prepare(registry, tmp_path, *, dimension=8, model_id="legal-8d"):
    parameters = (ParameterSpec("projection.weight", (dimension,), "float64"),)
    base = {"projection.weight": [0.0] * dimension}
    checkpoint = tmp_path / (model_id + ".json")
    checkpoint.write_text(json.dumps({"parameters": base, "dimension": dimension}))
    artifact = registry.stage_artifact(checkpoint)
    registry.register_variant("variant:" + model_id, model_id,
                              {"dimension": dimension, "architecture": "synthetic-test"})
    version = registry.register_version("base:" + model_id, model_id, artifact)
    registry.initialize_head("head:" + model_id, model_id, "main", version["version_id"])
    round_spec = FederatedRound(
        round_id="round-1", model_id=model_id, lineage_id=model_id,
        dimension=dimension, architecture="synthetic-test", runtime_profile="float64/v1",
        base_sha256=artifact["sha256"],
        base_parameters_sha256=parameter_digest(parameters, base),
        embedding_producer_sha256="e" * 64, parameters=parameters,
        clients=(ClientSpec("a", 1, "a" * 64), ClientSpec("b", 3, "b" * 64)),
    )
    updates = [make_client_update(round_spec, "a", {"projection.weight": {0: 4.0}},
                                 local_steps=1, local_data_sha256="a" * 64),
               make_client_update(round_spec, "b", {},
                                 local_steps=1, local_data_sha256="b" * 64)]
    return version["version_id"], round_spec, base, updates


def claimed(registry, version_id, round_spec):
    create_federated_run(registry, "create:" + round_spec.model_id,
                         "run:" + round_spec.model_id, version_id, round_spec)
    return registry.claim_run("claim:" + round_spec.model_id, "run:" + round_spec.model_id,
                              "aggregate-owner", lease_seconds=20)["lease"]


def materialize(tmp_path, round_spec, base, updates):
    candidate = aggregate_round(round_spec, base, updates)
    path = tmp_path / (round_spec.model_id + "-aggregate.json")
    path.write_text(json.dumps({"parameters": candidate.parameters,
                               "dimension": round_spec.dimension}))
    return path


def verify_synthetic(round_spec, candidate, path):
    saved = json.loads(path.read_bytes())
    return (saved["parameters"] == candidate.parameters
            and saved["dimension"] == round_spec.dimension)


def test_complete_aggregate_keeps_independent_lineage_heads_unchanged(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        lanes = [prepare(registry, tmp_path),
                 prepare(registry, tmp_path, dimension=384, model_id="legal-384d")]
        for version, round_spec, base, updates in lanes:
            lease = claimed(registry, version, round_spec)
            path = materialize(tmp_path, round_spec, base, updates)
            observed_paths = []

            def verifier(round_binding, candidate, staged):
                observed_paths.append(staged)
                assert staged != path  # Verify the immutable copy, not the source.
                assert candidate.parameters["projection.weight"][0] == 1.0
                return verify_synthetic(round_binding, candidate, staged)

            receipt = complete_federated_run(registry, "complete:" + round_spec.model_id,
                lease, round_spec, base, updates, path, verify_checkpoint=verifier)
            assert observed_paths
            assert receipt["promoted"] is False and receipt["admitted"] is False
            assert registry.resolve_head(round_spec.model_id, "main")["version_id"] == version
            saved = registry.get_version(receipt["version_id"])
            assert saved["parent_version_id"] == version
            result = saved["metadata"]["result"]
            assert result["aggregation"]["total_sample_count"] == 4
            assert result["qualified"] is False
            assert result["publication_performed"] is False


def test_exact_completion_retry_survives_owner_restart(tmp_path):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        path = materialize(tmp_path, round_spec, base, updates)
        first = complete_federated_run(registry, "complete", lease, round_spec,
            base, updates, path, verify_checkpoint=verify_synthetic)
    with AutoencoderRegistry(database, artifacts) as registry:
        assert complete_federated_run(registry, "complete", lease, round_spec,
            base, updates, path, verify_checkpoint=verify_synthetic) == first
        assert registry.resolve_head("legal-8d", "main")["generation"] == 1


@pytest.mark.parametrize("change", [{"base_sha256": "0" * 64}, {"model_id": "legal-384d"}])
def test_wrong_registered_parent_is_rejected_before_creating_run(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        version, round_spec, _, _ = prepare(registry, tmp_path)
        with pytest.raises(RegistryError):
            create_federated_run(registry, "wrong-base", "wrong-run", version,
                                 replace(round_spec, **change))
        with pytest.raises(RegistryError, match="unknown run"):
            registry.get_run("wrong-run")


def test_different_round_cannot_complete_a_claimed_run(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        with pytest.raises(RegistryError, match="binding differs"):
            complete_federated_run(registry, "wrong-round", lease,
                replace(round_spec, lineage_id="other-lineage"), base, updates,
                tmp_path / "does-not-exist", verify_checkpoint=verify_synthetic)
        assert registry.get_run(lease["run_id"])["status"] == "running"


@pytest.mark.parametrize("verdict", [False, None, 1, "verified"])
def test_owner_materialization_verifier_must_return_exact_true(tmp_path, verdict):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        path = materialize(tmp_path, round_spec, base, updates)
        with pytest.raises(RegistryError, match="verification failed"):
            complete_federated_run(registry, "complete", lease, round_spec, base,
                updates, path, verify_checkpoint=lambda *_: verdict)
        assert registry.get_run(lease["run_id"])["status"] == "running"
        assert registry.resolve_head("legal-8d", "main")["version_id"] == version


def test_incorrect_checkpoint_parameters_are_not_recorded(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        path = materialize(tmp_path, round_spec, base, updates)
        path.write_text(json.dumps({"parameters": base, "dimension": 8}))
        with pytest.raises(RegistryError, match="verification failed"):
            complete_federated_run(registry, "complete", lease, round_spec,
                base, updates, path, verify_checkpoint=verify_synthetic)


def test_verifier_cannot_accidentally_modify_the_staged_checkpoint(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        path = materialize(tmp_path, round_spec, base, updates)

        def bad_verifier(_round, _candidate, staged):
            staged.write_bytes(b"accidentally modified")
            return True

        with pytest.raises(RegistryError, match="digest mismatch"):
            complete_federated_run(registry, "complete", lease, round_spec,
                base, updates, path, verify_checkpoint=bad_verifier)
        assert registry.get_run(lease["run_id"])["status"] == "running"


def test_expired_lease_cannot_complete_or_move_the_head(tmp_path):
    now = [1_800_000_000.0]
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts",
                             clock=lambda: now[0]) as registry:
        version, round_spec, base, updates = prepare(registry, tmp_path)
        lease = claimed(registry, version, round_spec)
        path = materialize(tmp_path, round_spec, base, updates)
        now[0] += 30
        with pytest.raises(RegistryError, match="lease"):
            complete_federated_run(registry, "complete", lease, round_spec,
                base, updates, path, verify_checkpoint=verify_synthetic)
        assert registry.get_run(lease["run_id"])["status"] == "running"
        assert registry.resolve_head("legal-8d", "main")["version_id"] == version
