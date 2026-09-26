"""V8 owner bindings and durable batches with synthetic producer vectors only.

No inference, native training, listener, publication or Lean admission occurs.
Declared-native producer profiles exercise integrity contracts, not attestation.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import (
    _prepared, _manifest,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _fixture_worker, _prepare, _assert_rejected_before_dispatch, _indexed_corpus_inputs,
)


ROOT_FIELDS = ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
               "produced_record_projection_artifact")
LEGACY_FIELDS = {"corpus_index_artifact", "corpus_selection_sha256", "corpus_index_membership_verified",
                 "embedding_production_artifact", "embedding_production_verified", "embedding_production_verification",
                 "arrow_embedding_inputs_artifact", "arrow_embedding_inputs_verified"}


def _campaign_inputs(registry, root, *, fixture=None, batch_number=0):
    """Stage one independent batch while retaining the exact campaign roots."""
    root.mkdir(exist_ok=True)
    fixture = fixture or _prepared(root)
    if batch_number:
        start = batch_number * 2
        training = fixture.case.partitions.entry_cids_for("train")[start:start + 2]
        validation = fixture.case.partitions.entry_cids_for("validation")[start:start + 2]
        assert len(training) == len(validation) == 2
        fixture.manifest, fixture.entry_cids = _manifest(fixture.records_by_entry, training, validation)
    projection = fixture.build()

    def stage(path, digest=None):
        artifact = registry.stage_artifact(path, digest)
        return {**artifact, "path": str(registry.artifact_path(artifact))}

    def serialize(name, value):
        path = root / f"{name}-{batch_number}.json"
        path.write_bytes(value.to_bytes())
        return stage(path, value.sha256)

    selected = projection.selected_artifacts()
    inputs = {
        "schema_version": "autoencoder-training-job-v8",
        "source_inventory_artifact": serialize("inventory", fixture.case.partitions.inventory),
        "source_partitions_artifact": serialize("partitions", fixture.case.partitions),
        "embedding_receipt_set_artifact": serialize("receipt-set", fixture.receipt_set),
        "produced_record_projection_artifact": serialize("projection", projection),
        "corpus_manifest_artifact": serialize("manifest", fixture.manifest),
        "embedding_receipt_artifacts": [stage(fixture.case.receipt_resolver(ref), ref["sha256"])
                                        for ref in selected["leaf_receipts"]],
        "corpus_source_artifacts": [stage(fixture.case.source_resolver(ref), ref["sha256"])
                                    for ref in selected["source_artifacts"]],
        "dataset_snapshot_id": fixture.manifest.dataset_snapshot_id,
        "split_snapshot_id": fixture.manifest.split_snapshot_id,
    }
    by_id = {record.record_id: record for record in fixture.manifest.records}
    roles = fixture.manifest.to_dict()["split"]
    inputs["samples"] = [asdict(by_id[key].sample) for key in roles["training_record_ids"]]
    inputs["validation_samples"] = [asdict(by_id[key].sample) for key in roles["validation_record_ids"]]
    binding = {name: {key: inputs[f"{name}_artifact"][key] for key in ("sha256", "bytes")}
               for name in ("source_inventory", "source_partitions", "embedding_receipt_set")}
    return inputs, binding, fixture


def _next_job(registry, root, previous, inputs):
    payload = previous.to_dict()
    payload.update(inputs, job_id="job-next", run_id="run-next", output_directory=str(root / "attempt-next"))
    spec = TrainingJobSpec.from_dict(payload)
    path = root / "job-next.json"
    path.write_text(json.dumps(spec.to_dict()))
    artifact = registry.stage_artifact(path)
    registry.create_run("create-next", spec.run_id, "english-0", spec.base_version_id,
                        {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": artifact})
    return spec


def test_successive_batches_share_one_variant_and_keep_exact_bindings_after_restart(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, binding, fixture = _campaign_inputs(registry, tmp_path)
        first = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        second_inputs, second_binding, _ = _campaign_inputs(registry, tmp_path, fixture=fixture, batch_number=1)
        assert second_binding == binding
        second = _next_job(registry, tmp_path, first, second_inputs)
        assert first.produced_record_projection_artifact.sha256 != second.produced_record_projection_artifact.sha256
        assert {ref.sha256 for ref in first.embedding_receipt_artifacts}.isdisjoint(
            ref.sha256 for ref in second.embedding_receipt_artifacts)
        result = coordinator.run_training_jobs(registry, [first, second], max_workers=2,
            executor_factory=ImmediateExecutor, worker_function=_fixture_worker)
        assert result["failed"] == [], result
        assert len(result["completed"]) == 2
        saved = {}
        for completed in result["completed"]:
            spec = {first.run_id: first, second.run_id: second}[completed["run_id"]]
            summary = completed["result"]
            saved[spec.run_id] = deepcopy(summary)
            assert summary["execution_mode"] == "injected_test"
            assert summary["source_campaign_verified"] is True
            assert summary["produced_record_projection_verified"] is True
            assert summary["heldout_canary_qualified"] is False
            assert summary["admitted"] is summary["promotion_performed"] is False
            assert summary["sample_count"] == summary["validation_sample_count"] == 2
            assert not LEGACY_FIELDS.intersection(summary)
            for name in (*ROOT_FIELDS, "embedding_receipt_artifacts"):
                assert summary[name] == spec.to_dict()[name]
            corpus = summary["corpus_verification"]
            assert "source_campaign_verification" in corpus
            assert "produced_record_projection_verification" in corpus
            receipt = json.loads(registry.artifact_path(completed["worker_receipt_artifact"]).read_bytes())
            assert not LEGACY_FIELDS.intersection(receipt)
            assert receipt["corpus_verification"] == corpus
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_variant("english-0")["manifest"]["source_campaign_binding"] == binding
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
        for spec in (first, second):
            assert registry.get_run(spec.run_id)["result"] == saved[spec.run_id]
            resolved = coordinator.registered_corpus_job_inputs(registry, spec.run_id)
            assert resolved["spec"].canonical_sha256 == spec.canonical_sha256
            assert resolved["corpus_verification"] == saved[spec.run_id]["corpus_verification"]


@pytest.mark.parametrize("root", ["source_inventory", "source_partitions", "embedding_receipt_set"])
def test_registered_campaign_roots_cannot_be_replaced(tmp_path, root):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        changed = registry.get_variant("english-0")["manifest"]
        changed["source_campaign_binding"][root]["sha256"] = "0" * 64
        with pytest.raises(RegistryError, match="variant is immutable"):
            registry.register_variant("replace-campaign", "english-0", changed)
        assert registry.get_variant("english-0")["manifest"]["source_campaign_binding"] == binding


@pytest.mark.parametrize("problem", ["missing", "null", "extra", "projection_in_binding", "missing_root",
    "missing_bytes", "path", "boolean_bytes", "oversized", "sha256", "different_inventory",
    "different_partitions", "different_receipt_set", "legacy_index", "legacy_producer"])
def test_campaign_binding_rejected_before_claim(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        updates = {"source_campaign_binding": binding}
        if problem == "missing":
            updates = {}
        elif problem == "null":
            updates["source_campaign_binding"] = None
        elif problem in {"extra", "projection_in_binding"}:
            binding["unknown" if problem == "extra" else "produced_record_projection"] = {"sha256": "a" * 64, "bytes": 1}
        elif problem == "missing_root":
            del binding["source_inventory"]
        elif problem == "missing_bytes":
            del binding["source_inventory"]["bytes"]
        elif problem == "path":
            binding["source_inventory"]["path"] = inputs["source_inventory_artifact"]["path"]
        elif problem in {"boolean_bytes", "oversized"}:
            binding["source_inventory"]["bytes"] = True if problem == "boolean_bytes" else 64 * 1024**2 + 1
        elif problem == "sha256":
            binding["source_inventory"]["sha256"] = "A" * 64
        elif problem.startswith("different_"):
            name = {"different_inventory": "source_inventory", "different_partitions": "source_partitions",
                    "different_receipt_set": "embedding_receipt_set"}[problem]
            binding[name]["sha256"] = "0" * 64
        elif problem == "legacy_index":
            updates["corpus_index_binding"] = None
        else:
            updates["embedding_production_binding"] = None
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates=updates)
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="source_campaign_binding")


@pytest.mark.parametrize("schema", [f"autoencoder-training-job-v{number}" for number in range(1, 8)])
def test_campaign_variant_forbids_legacy_downgrade(tmp_path, monkeypatch, schema):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs = {"schema_version": schema}
        if schema in {"autoencoder-training-job-v4", "autoencoder-training-job-v5",
                      "autoencoder-training-job-v6", "autoencoder-training-job-v7"}:
            inputs, _, _ = _indexed_corpus_inputs(registry, tmp_path,
                production=schema in {"autoencoder-training-job-v6", "autoencoder-training-job-v7"},
                arrow_inputs=schema == "autoencoder-training-job-v7")
            if schema == "autoencoder-training-job-v4":
                inputs["schema_version"] = schema
                del inputs["corpus_index_artifact"]
                del inputs["corpus_selection_sha256"]
        spec = _prepare(registry, tmp_path, job_updates=inputs,
            variant_updates={"source_campaign_binding": {name: {"sha256": "a" * 64, "bytes": 1}
                for name in ("source_inventory", "source_partitions", "embedding_receipt_set")}})
        assert spec.schema_version == schema
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="legacy downgrade")


@pytest.mark.parametrize("field", [*ROOT_FIELDS, "embedding_receipt_artifacts", "corpus_source_artifacts"])
@pytest.mark.parametrize("problem", ["unstaged", "corrupted"])
def test_campaign_artifacts_must_be_exact_owner_staged_files(tmp_path, monkeypatch, field, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        artifact = inputs[field][0] if field.endswith("artifacts") else inputs[field]
        path = Path(artifact["path"])
        if problem == "unstaged":
            copied = tmp_path / f"mutable-{field}.json"
            copied.write_bytes(path.read_bytes())
            artifact["path"] = str(copied)
        else:
            path.write_bytes(b"corrupted")
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        _assert_rejected_before_dispatch(registry, spec, monkeypatch,
                                        match="staged immutable|SHA-256|size|digest|hash|artifact")


@pytest.mark.parametrize("field", [*ROOT_FIELDS, "embedding_receipt_artifacts", "source_campaign_verified",
    "produced_record_projection_verified", "corpus_verification", "legacy_claim"])
def test_owner_rejects_changed_v8_completion_receipt(tmp_path, field):
    def changed_worker(spec):
        receipt = _fixture_worker(spec)
        if field in ROOT_FIELDS:
            receipt[field]["sha256"] = "0" * 64
        elif field == "embedding_receipt_artifacts":
            receipt[field].reverse()
        elif field in {"source_campaign_verified", "produced_record_projection_verified"}:
            receipt[field] = False
        elif field == "corpus_verification":
            receipt[field]["source_campaign_verification"] = {"training_eligible": True}
        else:
            receipt["embedding_production_verified"] = True
        (Path(spec.output_directory) / "receipt.json").write_text(json.dumps(receipt))
        return receipt

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=changed_worker)
        assert result["completed"] == []
        assert len(result["failed"]) == 1
        assert "worker receipt" in result["failed"][0]["error"]
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("problem", ["missing_leaf", "extra_leaf", "foreign_leaf", "source_extra"])
def test_owner_rejects_nonexact_selected_closure_before_dispatch(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, fixture = _campaign_inputs(registry, tmp_path)
        if problem == "missing_leaf":
            inputs["embedding_receipt_artifacts"].pop()
        elif problem in {"extra_leaf", "foreign_leaf"}:
            selected = {ref["sha256"] for ref in inputs["embedding_receipt_artifacts"]}
            ref = next(ref for ref in fixture.case.descriptors if ref["sha256"] not in selected)
            staged = registry.stage_artifact(fixture.case.receipt_resolver(ref))
            located = {**staged, "path": str(registry.artifact_path(staged))}
            if problem == "extra_leaf":
                inputs["embedding_receipt_artifacts"].append(located)
            else:
                inputs["embedding_receipt_artifacts"][0] = located
        else:
            selected = {ref["sha256"] for ref in inputs["corpus_source_artifacts"]}
            path = next(path for digest, path in fixture.case.source_paths.items() if digest not in selected)
            staged = registry.stage_artifact(path)
            inputs["corpus_source_artifacts"].append({**staged, "path": str(registry.artifact_path(staged))})
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="closure|selected|source|receipt")


@pytest.mark.parametrize("problem", ["unauthorized_roles", "projection_manifest_mismatch", "extra_leaf"])
def test_owner_metadata_authorization_precedes_selected_cas_reads(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, fixture = _campaign_inputs(registry, tmp_path)
        if problem == "extra_leaf":
            selected = {ref["sha256"] for ref in inputs["embedding_receipt_artifacts"]}
            ref = next(ref for ref in fixture.case.descriptors if ref["sha256"] not in selected)
            artifact = registry.stage_artifact(fixture.case.receipt_resolver(ref))
            inputs["embedding_receipt_artifacts"].append({**artifact, "path": str(registry.artifact_path(artifact))})
        else:
            projection = json.loads(Path(inputs["produced_record_projection_artifact"]["path"]).read_bytes())
            if problem == "unauthorized_roles":
                projection["training_record_ids"], projection["validation_record_ids"] = (
                    projection["validation_record_ids"], projection["training_record_ids"])
            else:
                projection["corpus_manifest"]["sha256"] = "0" * 64
            path = tmp_path / "bad-projection.json"
            path.write_text(json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
            artifact = registry.stage_artifact(path)
            inputs["produced_record_projection_artifact"] = {**artifact, "path": str(registry.artifact_path(artifact))}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        selected_digests = {ref["sha256"] for name in ("embedding_receipt_artifacts", "corpus_source_artifacts")
                            for ref in inputs[name]}
        original = registry.verify_artifact

        def verify(artifact):
            assert artifact.get("sha256") not in selected_digests, "selected CAS artifact read before metadata authorization"
            return original(artifact)

        monkeypatch.setattr(registry, "verify_artifact", verify)
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="campaign|projection")


def _count_campaign_loaders(monkeypatch):
    """Count top-level loads, preserving each codec's nested revalidation."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inventory
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as partitions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_receipt_set as receipt_set
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_produced_record_projection as projection
    counts = {}
    for module, name in ((inventory, "load_uscode_source_inventory"), (partitions, "load_source_partitions"),
                         (receipt_set, "load_embedding_receipt_set"), (projection, "load_produced_record_projection")):
        original = getattr(module, name)
        counts[name] = 0

        def load(*args, _name=name, _original=original, **kwargs):
            counts[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, load)
    return counts


@pytest.mark.parametrize("entry", ["registered_inputs", "validate_runs"])
def test_owner_reuses_preflight_only_within_one_operation_and_worker_verifies_afresh(tmp_path, monkeypatch, entry):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        # This independently freshly verified summary remains the exact contract.
        expected = coordinator.verify_corpus_job_inputs(spec)
        counts = _count_campaign_loaders(monkeypatch)

        def verify():
            if entry == "registered_inputs":
                return coordinator.registered_corpus_job_inputs(registry, spec.run_id)["corpus_verification"]
            return coordinator._validate_runs(registry, [spec])[spec.run_id]

        assert verify() == expected
        assert counts == {name: 1 for name in counts}
        # A separate owner operation cannot reuse the consumed context.
        assert verify() == expected
        assert counts == {name: 2 for name in counts}
        receipt = _fixture_worker(spec)
        assert counts == {name: 3 for name in counts}
        assert receipt["corpus_verification"] == expected
        assert receipt["execution_mode"] == "injected_test"


def test_independent_jobs_with_shared_roots_each_load_one_local_preflight(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, fixture = _campaign_inputs(registry, tmp_path)
        first = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        next_inputs, next_binding, _ = _campaign_inputs(registry, tmp_path, fixture=fixture, batch_number=1)
        assert next_binding == binding
        second = _next_job(registry, tmp_path, first, next_inputs)
        expected = {spec.run_id: coordinator.verify_corpus_job_inputs(spec) for spec in (first, second)}
        counts = _count_campaign_loaders(monkeypatch)
        actual = coordinator._validate_runs(registry, [first, second])
        assert actual == expected
        assert counts == {name: 2 for name in counts}
        assert actual[first.run_id] != actual[second.run_id]


@pytest.mark.parametrize("entry", ["registered_inputs", "validate_runs"])
@pytest.mark.parametrize("field", [*ROOT_FIELDS, "corpus_manifest_artifact", "embedding_receipt_artifacts",
                                   "corpus_source_artifacts"])
def test_owner_rechecks_current_bytes_after_selected_cas_preflight(tmp_path, monkeypatch, entry, field):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _campaign_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"source_campaign_binding": binding})
        counts = _count_campaign_loaders(monkeypatch)
        target = inputs[field][0] if field.endswith("artifacts") else inputs[field]
        path = Path(target["path"])
        trigger = inputs["corpus_source_artifacts"][-1]["sha256"]
        original_verify = registry.verify_artifact
        changed = False

        def verify(artifact):
            nonlocal changed
            result = original_verify(artifact)
            # This happens after the last selected CAS file has passed its hash
            # check, so only the following fresh verification can catch drift.
            if artifact["sha256"] == trigger and not changed:
                changed = True
                path.write_bytes(path.read_bytes() + b"\n")
            return result

        monkeypatch.setattr(registry, "verify_artifact", verify)
        with pytest.raises(ValueError, match="campaign|artifact|SHA|size|metadata|changed|bytes"):
            if entry == "registered_inputs":
                coordinator.registered_corpus_job_inputs(registry, spec.run_id)
            else:
                coordinator._validate_runs(registry, [spec])
        assert changed
        assert counts == {name: 1 for name in counts}
        run = registry.get_run(spec.run_id)
        assert run["status"] == "queued" and run["attempt"] == 0
        assert run["result"] is None and not Path(spec.output_directory).exists()
