"""Feature artifact transport with injected receipts; no native/legal attestation."""
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_exchange as exchange
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_training as feature
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_feature_training import (
    _templates, _run, _rejected_worker, ImmediateExecutor)
from tests.unit.huggingface.test_autoencoder_incremental import FakeHub
from tests.unit.huggingface.test_autoencoder_incremental_download import FakeClient


def clone(value):
    return json.loads(exchange._json(value))


def make_package(root, registry, *, accepted=True):
    specs = _templates(registry, root, 1)
    if accepted:
        result = _run(registry, root, specs, lane_count=1, max_batches=1)
    else:
        result = feature.run_feature_incremental_training(registry, specs, state_directory=root / "feature",
            lane_count=1, executor_factory=ImmediateExecutor, worker_function=_rejected_worker)
    evidence = dict(result["completed"][0])
    evidence.pop("feature_evidence_artifact", None)
    original = json.loads(registry.artifact_path(evidence["worker_receipt_artifact"]).read_bytes())
    # Test-only declared-native metadata exercises transport contracts, not proof.
    worker = {**original, "execution_mode": "native_training", "execution_gate_applied": True,
              "source_manifest_verified": True}
    path = root / "declared-native-fixture.json"
    path.write_bytes(exchange._json(worker))
    evidence["worker_receipt_artifact"] = registry.stage_artifact(path)
    run = clone(registry.get_run(evidence["run_id"]))
    run["result"]["worker_receipt_artifact"] = evidence["worker_receipt_artifact"]
    class Owner:
        def __getattr__(self, name):
            return getattr(registry, name)
        def get_run(self, run_id):
            assert run_id == evidence["run_id"]
            return run
    owner = Owner()
    spec = TrainingJobSpec.from_dict(worker["job_spec"])
    parent = worker["base_materialized_checkpoint"]
    hub = FakeHub()
    seed = exchange.publish_feature_checkpoint(registry.artifact_path(parent), expected_artifact=parent,
        generation=1, upload=True, api=hub)
    staged = (exchange.stage_feature_update(owner, evidence["candidate_version_id"], evidence,
        root / "exchange", parent_reference=seed["anchor_reference"]) if accepted else None)
    return SimpleNamespace(root=root, registry=registry, owner=owner, spec=spec, evidence=evidence,
        worker=worker, original=original, seed=seed, staged=staged, hub=hub, completion={**evidence, "result": run["result"]})


@pytest.fixture
def package(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        yield make_package(tmp_path, registry)


def publish(package):
    return exchange.publish_feature_update(package.staged["manifest_path"], upload=True, api=package.hub)["weight_reference"]


def report_for(package, reference, *, updated=True):
    samples = clone([asdict(row) for row in package.spec.samples])
    validation = clone([asdict(row) for row in package.spec.validation_samples])
    binding = {"validation_samples_sha256": exchange.transport._sha(exchange.sparse._json(validation))}
    assignment = {"run_id": "campaign-run", "record": {"record_id": "record-one", "sample": samples[0]},
        "source_observation": {"version": 1}, "generation": 1, "base_version_id": "remote-parent-version",
        "policy": {"training_purpose": "feature_pretraining", "feature_input_binding": binding,
                   "source_identity": {"source": "a" * 64}}}
    parent = package.worker["base_materialized_checkpoint"]
    return {"schema": exchange.REPORT_SCHEMA, "training_purpose": "feature_pretraining",
        "assignment_binding": assignment, "work_id": assignment["run_id"], "span_revision": "record-one",
        "source_provenance": {"source_record": assignment["record"], "source_observation": assignment["source_observation"],
            "canonical_generation": 1, "canonical_version_id": assignment["base_version_id"], "canonical_artifact": parent,
            "source_identity": assignment["policy"]["source_identity"], "feature_input_binding": binding},
        "disposition": "feature_updated" if updated else "feature_no_update",
        "candidate_version_id": package.evidence["candidate_version_id"],
        "candidate_artifact": package.worker["candidate_materialized_checkpoint"], "base_artifact": parent,
        "feature_evidence": package.evidence, "worker_receipt": package.worker,
        "completion": package.completion, "training_config": clone(package.spec.training_config.to_dict()),
        "autoencoder_config": clone(dict(package.spec.autoencoder_config)), "training_samples": samples,
        "validation_samples": validation, "weight_publication": reference, **exchange._FALSE}


def test_compacted_candidate_sparse_transport_replays_and_resumes(package):
    dry = exchange.publish_feature_update(package.staged["manifest_path"])
    assert dry["weight_reference"] is None and not dry["uploaded"]
    ref = publish(package)
    assert ref["kind"] == "feature_sparse" and exchange.validate_feature_reference(ref) == 1
    bundle = exchange.load_feature_update(package.staged["manifest_path"])
    assert package.worker["base_materialized_checkpoint"]["sha256"] not in bundle["paths"]
    client = FakeClient(package.hub.files)
    first = exchange.download_feature_update(ref, package.root / "download", client=client)
    assert first["replay_verified"] and first["weights_downloaded"]
    assert first["materialized_checkpoint"] == package.worker["candidate_materialized_checkpoint"]
    assert exchange.transport._ref(Path(first["materialized_checkpoint_path"]).read_bytes()) == first["materialized_checkpoint"]
    assert all(first[key] is False for key in exchange._FALSE)
    count = len(client.calls)
    resumed = exchange.download_feature_update(ref, package.root / "download", client=client)
    assert count == len(client.calls) and resumed["downloaded_bytes"] == 0 and not resumed["weights_downloaded"]


def test_local_parent_or_none_cold_fallback(package):
    ref = publish(package)
    client = FakeClient(package.hub.files)
    result = exchange.download_feature_update(ref, package.root / "local", client=client,
        local_parent_resolver=package.registry.artifact_path)
    assert result["replayed"] and not any("/anchors/" in path for _, path in client.calls)
    other = FakeClient(package.hub.files)
    cold = exchange.download_feature_update(ref, package.root / "cold", client=other, local_parent_resolver=lambda ref: None)
    assert cold["replayed"] and any("/anchors/" in path for _, path in other.calls)


def test_append_retry_and_remote_conflict(package):
    ref = publish(package)
    count = len(package.hub.commits)
    again = exchange.publish_feature_update(package.staged["manifest_path"], upload=True, api=package.hub)
    assert again["remote_already_present"] and len(package.hub.commits) == count
    package.hub.files[ref["path_in_repo"]] = b"foreign"
    with pytest.raises(ValueError, match="conflict"):
        publish(package)


@pytest.mark.parametrize("key,value", [("repository_id", "foreign/data"), ("commit_sha", "main"),
    ("path_in_repo", "../../bad"), ("kind", "sparse"), ("extra", "unbound")])
def test_bad_reference_rejected_before_network(package, key, value):
    ref = {**publish(package), key: value}
    client = FakeClient(package.hub.files)
    with pytest.raises((ValueError, TypeError)):
        exchange.download_feature_update(ref, package.root / "bad", client=client)
    assert not client.calls


def test_corrupt_patch_and_cached_state_fail(package):
    ref = publish(package)
    bundle = exchange.load_feature_update(package.staged["manifest_path"])
    patch = next(row for row in bundle["manifest"]["files"] if row["kind"] == "patch")
    with pytest.raises(ValueError):
        exchange.download_feature_update(ref, package.root / "corrupt", client=FakeClient(package.hub.files, corrupt=patch["path_in_repo"]))
    first = exchange.download_feature_update(ref, package.root / "good", client=FakeClient(package.hub.files))
    Path(first["materialized_checkpoint_path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="conflict"):
        exchange.download_feature_update(ref, package.root / "good", client=FakeClient(package.hub.files))


def test_interrupted_download_reuses_verified_prefix(package):
    ref = publish(package)
    client = FakeClient(package.hub.files, fail_at=3)
    with pytest.raises(OSError, match="interruption"):
        exchange.download_feature_update(ref, package.root / "resume", client=client)
    client.fail_at = None
    result = exchange.download_feature_update(ref, package.root / "resume", client=client)
    assert result["replayed"] and result["reused_files"] == 2


def test_wrong_parent_and_injected_worker_cannot_be_exported(package):
    wrong = {**package.seed["anchor_reference"], "sha256": "0" * 64}
    with pytest.raises(ValueError):
        exchange.stage_feature_update(package.owner, package.evidence["candidate_version_id"], package.evidence,
            package.root / "wrong", parent_reference=wrong)
    evidence = {**package.evidence, "worker_receipt_artifact": package.registry.get_run(package.evidence["run_id"])["result"]["worker_receipt_artifact"]}
    with pytest.raises(ValueError, match="native"):
        exchange.stage_feature_update(package.registry, evidence["candidate_version_id"], evidence,
            package.root / "injected", parent_reference=package.seed["anchor_reference"])


def test_feature_report_only_transfer_binds_assignment_and_evidence(package):
    report = report_for(package, publish(package))
    published = exchange.publish_feature_report(report, package.root / "report", upload=True, api=package.hub)
    ref = published["report_reference"]
    assert set(ref) == {"repository_id", "commit_sha", "path_in_repo", "sha256", "bytes"}
    client = FakeClient(package.hub.files)
    downloaded = exchange.download_feature_report(ref, package.root / "report-download", client=client)
    assert len(client.calls) == 1 and not downloaded["weights_downloaded"]
    assert downloaded["owner_replay_and_evaluation_required"]
    assert downloaded["report"]["assignment_binding"] == report["assignment_binding"]
    for field in ("qualified", "admitted", "formalized", "promotion_performed"):
        bad = clone(report); bad[field] = True
        with pytest.raises(ValueError):
            exchange.publish_feature_report(bad, package.root / "bad-report")


@pytest.mark.parametrize("problem", ["assignment", "validation", "input_binding", "metric", "epoch", "supervision"])
def test_report_rejects_inconsistent_evidence(package, problem):
    report = report_for(package, publish(package))
    report = clone(report)
    if problem == "assignment": report["assignment_binding"]["generation"] = 2
    elif problem == "validation": report["validation_samples"][0]["embedding_vector"] = [1., 1.]
    elif problem == "input_binding": report["source_provenance"]["feature_input_binding"] = {}
    elif problem == "metric": report["feature_evidence"]["raw_tuning_metrics"]["after"]["reconstruction_loss"] = .01
    elif problem == "epoch": report["worker_receipt"]["training_report"]["epoch_reports"][0]["committed_objective_delta"] = -.1
    else: report["worker_receipt"]["shared_target_supervision"]["complete"] = False
    with pytest.raises((ValueError, KeyError)):
        exchange.publish_feature_report(report, package.root / "inconsistent")


def test_no_update_report_has_no_weights_or_parent_advance(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        package = make_package(tmp_path, registry, accepted=False)
        with pytest.raises(ValueError, match="accepted optimizer"):
            exchange.stage_feature_update(package.owner, package.evidence["candidate_version_id"], package.evidence,
                tmp_path / "no-op-update", parent_reference=package.seed["anchor_reference"])
        report = report_for(package, None, updated=False)
        result = exchange.publish_feature_report(report, tmp_path / "no-update", upload=True, api=package.hub)
        downloaded = exchange.download_feature_report(result["report_reference"], tmp_path / "consumer", client=FakeClient(package.hub.files))
        assert downloaded["report"]["disposition"] == "feature_no_update"
        assert not downloaded["weights_downloaded"]
        report["disposition"] = "feature_updated"
        with pytest.raises(ValueError, match="rejected"):
            exchange.publish_feature_report(report, tmp_path / "bad")


def test_chain_depth_bound_rejects_before_network(package):
    ref = publish(package)
    for index in range(8):
        digest = f"{index:064x}"
        ref = {**ref, "sha256": digest, "path_in_repo": f"{exchange.PREFIX}/updates/{digest}.json", "anchor_reference": clone(ref)}
    client = FakeClient(package.hub.files)
    with pytest.raises(ValueError, match="depth"):
        exchange.download_feature_update(ref, package.root / "deep", client=client)
    assert not client.calls


def test_reply_lost_after_commit_is_idempotently_resumed(package):
    package.hub.fail_after_commit = True
    with pytest.raises(OSError, match="reply lost"):
        publish(package)
    count = len(package.hub.commits)
    result = exchange.publish_feature_update(package.staged["manifest_path"], upload=True, api=package.hub)
    assert result["remote_already_present"] and len(package.hub.commits) == count
