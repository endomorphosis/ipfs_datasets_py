"""Shared DuckDB owner with exact, scoped Quack mutations; no legal admissions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.autoencoder_quack import (
    RegistryQuackGateway, RegistryTransportError, WorkerScope, _envelope,
)
from ipfs_datasets_py.duckdb_control.autoencoder_shared_weight_control import (
    SharedWeightControlError, SharedWeightRegistry, _OwnerPreparedGateway,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare_sparse, _sparse_worker,
)
from tests.unit.duckdb_control.test_autoencoder_quack import native_available

NATIVE = pytest.mark.skipif(os.environ.get("IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE") != "1",
                           reason="native Quack test requires explicit isolated-test opt-in")


def _pair(registry, directory):
    first = _prepare_sparse(registry, directory)
    second = replace(first, job_id="job-b", run_id="run-b", output_directory=str(directory / "attempt-b"))
    path = directory / "job-b.json"
    path.write_text(json.dumps(second.to_dict()))
    artifact = registry.stage_artifact(path)
    registry.create_run("create-b", second.run_id, "english-0", first.base_version_id,
                        {"job_spec_sha256": second.canonical_sha256, "job_spec_artifact": artifact})
    return first, second


def test_explicit_prototype_and_actual_owner_required(tmp_path):
    with pytest.raises(SharedWeightControlError, match="opt-in"):
        SharedWeightRegistry(object())
    with pytest.raises(SharedWeightControlError, match="actual"):
        SharedWeightRegistry(object(), enable_prototype=True)


def test_generic_gateway_native_job_guard_is_preserved(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        gateway = RegistryQuackGateway(registry, WorkerScope("worker", frozenset({spec.run_id})), enable_prototype=True)
        with pytest.raises(RegistryTransportError, match="owner-verified"):
            gateway.dispatch(_envelope("ClaimRun", {"run_id": spec.run_id}, "claim"))


def test_wire_client_cannot_authorize_or_change_owner_prepared_mutation(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        first, second = _pair(registry, tmp_path)
        gateway = _OwnerPreparedGateway(registry, WorkerScope("worker", frozenset({first.run_id})))
        payload = {"run_id": first.run_id, "lease_seconds": 300}
        with pytest.raises(SharedWeightControlError, match="not prepared"):
            gateway.dispatch(_envelope("ClaimRun", payload, "claim"))
        with pytest.raises(RegistryTransportError, match="assigned worker"):
            gateway.authorize("other", "ClaimRun", {"run_id": second.run_id})
        gateway.authorize("claim", "ClaimRun", payload)
        claim = gateway.dispatch(_envelope("ClaimRun", payload, "claim"))
        assert claim["lease"]["run_id"] == first.run_id
        assert gateway.dispatch(_envelope("ClaimRun", payload, "claim")) == claim
        with pytest.raises(SharedWeightControlError, match="different content"):
            gateway.authorize("claim", "ClaimRun", {**payload, "lease_seconds": 99})
        with pytest.raises(SharedWeightControlError, match="not prepared"):
            gateway.dispatch(_envelope("ClaimRun", {**payload, "lease_seconds": 99}, "claim"))
        with pytest.raises(SharedWeightControlError, match="not prepared"):
            gateway.dispatch(_envelope("CompleteRun", {"lease": claim["lease"],
                "artifact": registry.get_version(first.base_version_id)["artifact"],
                "result": {"admitted": False}}, "complete"))
        assert registry.get_run(first.run_id)["status"] == "running"


def test_facade_closes_only_transports_and_has_no_network_side_effect_at_construction(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with SharedWeightRegistry(registry, enable_prototype=True) as shared:
            assert shared.get_run(spec.run_id) == registry.get_run(spec.run_id)
            report = shared.transport_report()
            assert report["scoped_run_count"] == 0
            assert not report["remote_artifact_transfer"] and not report["weights_downloaded"]
        assert registry.get_run(spec.run_id)["status"] == "queued"
        with pytest.raises(SharedWeightControlError, match="closed"):
            shared.get_run(spec.run_id)


def _direct_channel(shared, registry, spec, monkeypatch, alter):
    """Unit transport injection; the separate opt-in tests exercise native Quack."""
    gateway = _OwnerPreparedGateway(registry, WorkerScope("worker", frozenset({spec.run_id})))
    class DirectClient:
        def request(self, command, payload, operation_id):
            value = gateway.dispatch(_envelope(command, payload, operation_id))
            return alter(command, json.loads(json.dumps(value)))
    client = DirectClient()
    monkeypatch.setattr(shared, "_channel", lambda run_id, worker_id: (gateway, client))


@pytest.mark.parametrize("mismatch", ["run", "base"])
def test_scoped_claim_reads_must_match_registered_job_before_dispatch(tmp_path, monkeypatch, mismatch):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        shared = SharedWeightRegistry(registry, enable_prototype=True)
        corrupt = True
        def alter(command, value):
            if corrupt and mismatch == "run" and command == "ReadRun":
                value["run"]["base_version_id"] = "another-version"
            if corrupt and mismatch == "base" and command == "ReadVersion":
                value["version"]["artifact"]["sha256"] = "0" * 64
            return value
        _direct_channel(shared, registry, spec, monkeypatch, alter)
        with pytest.raises(SharedWeightControlError, match="Quack run identity|Quack base version"):
            shared.claim_run("claim", spec.run_id, "worker", 300)
        payload = {"run_id": spec.run_id, "worker_id": "worker", "lease_seconds": 300}
        with pytest.raises(SharedWeightControlError, match="Quack run identity|Quack base version"):
            shared.resolve_operation("claim", "ClaimRun", payload)
        corrupt = False
        receipt = shared.claim_run("claim", spec.run_id, "worker", 300)
        assert receipt["lease"]["attempt"] == 1
        assert shared.resolve_operation("claim", "ClaimRun", payload) == receipt
        shared.close()


def test_candidate_read_mismatch_cannot_bypass_via_committed_operation_resolution(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        shared = SharedWeightRegistry(registry, enable_prototype=True)
        corrupt = True
        def alter(command, value):
            if (corrupt and command == "ReadVersion"
                    and value["version"]["metadata"].get("producer_run") == spec.run_id):
                value["version"]["parent_version_id"] = "another-base"
            return value
        _direct_channel(shared, registry, spec, monkeypatch, alter)
        lease = shared.claim_run("claim", spec.run_id, "worker", 300)["lease"]
        artifact = registry.get_version(spec.base_version_id)["artifact"]
        result = {"admitted": False, "fixture_owner_prepared": True}
        with pytest.raises(SharedWeightControlError, match="Quack candidate"):
            shared.complete_run("complete", lease, artifact, result)
        assert registry.get_run(spec.run_id)["status"] == "completed"
        payload = {"lease": lease, "artifact": artifact, "result": result}
        with pytest.raises(SharedWeightControlError, match="Quack candidate"):
            shared.resolve_operation("complete", "CompleteRun", payload)
        corrupt = False
        resolved = shared.resolve_operation("complete", "CompleteRun", payload)
        assert resolved == shared.complete_run("complete", lease, artifact, result)
        assert registry.get_run_completion(spec.run_id)["completion_receipt"] == resolved
        shared.close()


@NATIVE
def test_native_quack_shared_registry_sparse_coordinator_and_conflicting_head_cas(tmp_path):
    native_available()
    with AutoencoderRegistry(tmp_path / "owner.db", tmp_path / "artifacts",
                             promotion_validator=lambda version, evaluation: evaluation.get("test_policy") is True) as registry:
        specs = _pair(registry, tmp_path)
        with SharedWeightRegistry(registry, enable_prototype=True) as shared:
            result = coordinator.run_training_jobs(shared, specs, max_workers=2,
                executor_factory=ImmediateExecutor, worker_function=_sparse_worker)
            assert not result["failed"] and len(result["completed"]) == 2
            assert result["execution_mode"] == "injected_test"  # Native wire, fixture optimizer.
            mandatory = shared.transport_report()["command_counts"]
            assert mandatory["ReadRun"] >= 2
            assert mandatory["ReadVersion"] >= 4
            versions = [shared.get_version(item["version_id"]) for item in result["completed"]]
            assert all(version["parent_version_id"] == specs[0].base_version_id for version in versions)
            assert versions[0]["version_id"] != versions[1]["version_id"]
            assert all(shared.get_run(spec.run_id)["status"] == "completed" for spec in specs)
            report = shared.transport_report()
            assert report["command_counts"]["CompleteRun"] == 2
            assert report["command_counts"]["ClaimRun"] == 2
            assert report["command_counts"]["ReadVersion"] >= 2
            assert report["command_counts"]["ReadRun"] >= 2
            assert report["database_writer_count"] == 1 and not report["workers_open_database"]
            assert not report["admitted"] and not report["automatic_branch_merge"]
            assert "token" not in json.dumps(report)
            assert all(capability["native_quack"] for capability in report["capabilities"])
        # The shared owner retains both branches. An explicit owner test policy
        # still has to win the unchanged registry compare-and-swap operation.
        assert registry.resolve_head("english-0", "best")["version_id"] == specs[0].base_version_id
        def promote(index):
            version = versions[index]["version_id"]
            try:
                return registry.promote_head("promote-" + str(index), "english-0", "best", version,
                    specs[0].base_version_id, 1,
                    {"candidate_version_id": version, "protocol_id": "synthetic-cas-policy", "test_policy": True})
            except RegistryError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(promote, [0, 1]))
        assert sum(isinstance(value, dict) for value in outcomes) == 1
        assert any(isinstance(value, str) and "compare-and-swap conflict" in value for value in outcomes)
        assert registry.get_run_completion(specs[0].run_id) is not None
        assert registry.get_run_completion(specs[1].run_id) is not None


@NATIVE
def test_native_parallel_claims_exact_replay_and_restart_fencing(tmp_path):
    native_available()
    database, artifacts = tmp_path / "owner.db", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        specs = _pair(registry, tmp_path)
        with SharedWeightRegistry(registry, enable_prototype=True) as shared:
            def claim(index):
                return shared.claim_run("claim-" + str(index), specs[index].run_id, "worker-" + str(index), 300)
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(claim, [0, 1]))
            for index in range(2):
                payload = {"run_id": specs[index].run_id, "worker_id": "worker-" + str(index), "lease_seconds": 300}
                assert shared.resolve_operation("claim-" + str(index), "ClaimRun", payload) == claims[index]
                assert claim(index) == claims[index]
    with AutoencoderRegistry(database, artifacts) as registry:
        with SharedWeightRegistry(registry, enable_prototype=True) as shared:
            for index in range(2):
                payload = {"run_id": specs[index].run_id, "worker_id": "worker-" + str(index), "lease_seconds": 300}
                assert shared.resolve_operation("claim-" + str(index), "ClaimRun", payload) == claims[index]
            with pytest.raises(RegistryTransportError, match="stale|expired"):
                shared.renew_lease("renew-old", claims[0]["lease"], 300)
