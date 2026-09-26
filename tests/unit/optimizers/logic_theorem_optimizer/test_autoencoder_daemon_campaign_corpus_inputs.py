"""V8 immutable daemon handoff with synthetic vectors; no model qualification."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_corpus_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import _campaign_inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import _prepare
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_corpus_inputs import _restage


def _prepare_campaign(registry, root):
    updates, binding, fixture = _campaign_inputs(registry, root)
    spec = _prepare(registry, root, job_updates=updates,
                    variant_updates={"source_campaign_binding": binding})
    return spec, fixture


@pytest.fixture
def campaign_issued(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec, fixture = _prepare_campaign(registry, tmp_path)
        exported = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        descriptor = inputs.DaemonCorpusInputDescriptor(**exported["descriptor"])
        yield registry, spec, exported, descriptor, fixture


def _ref(artifact):
    return {"sha256": artifact.sha256, "bytes": artifact.bytes}


def test_v8_export_restart_reuses_wrapper_bytes_without_execution_or_head_change(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec, _ = _prepare_campaign(registry, tmp_path)
        before, head = registry.get_run(spec.run_id), registry.resolve_head("english-0", "best")
        first = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        raw = Path(first["descriptor"]["path"]).read_bytes()
        payload = json.loads(raw)
        assert set(payload) == inputs._FIELDS
        assert payload["schema_version"] == "autoencoder-daemon-corpus-inputs-v1"
        assert payload["job_spec_sha256"] == spec.canonical_sha256
        assert raw == canonical_json_bytes(payload)
        assert first["registration"]["execution_authorized"] is False
        assert first["registration"]["promotion_authorized"] is False
        assert registry.get_run(spec.run_id) == before
        assert registry.resolve_head("english-0", "best") == head
    with AutoencoderRegistry(database, artifacts) as registry:
        assert inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs") == first
        assert Path(first["descriptor"]["path"]).read_bytes() == raw
        assert registry.get_run(spec.run_id) == before
        assert registry.resolve_head("english-0", "best") == head
    # The real offline consumer neither needs nor opens the owner database.
    with inputs.VerifiedDaemonCorpusInputs(inputs.DaemonCorpusInputDescriptor(**first["descriptor"])) as session:
        assert session.summary()["input_integrity_verified"] is True


def test_v8_consumer_matches_worker_and_preserves_native_list_vectors(campaign_issued):
    _, spec, _, descriptor, _ = campaign_issued
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        summary = session.summary()
        assert summary["job_schema_version"] == worker.CAMPAIGN_SCHEMA_VERSION
        assert summary["embedding_input_storage"] == "python_list"
        assert summary["corpus_verification"] == worker.verify_corpus_job_inputs(spec)
        assert not {"arrow_embedding_inputs_artifact", "arrow_embedding_inputs_statistics"}.intersection(summary)
        verification = summary["corpus_verification"]
        assert verification["source_campaign_verified"] is True
        assert verification["produced_record_projection_verified"] is True
        assert not {"corpus_index_verification", "embedding_production_verification"}.intersection(verification)
        for role, rows in (("train", spec.samples), ("validation", spec.validation_samples)):
            positions = session.indices_for(role)
            samples = [session.build_sample(index) for index in positions]
            session.verify_selected(positions, samples, role=role)
            session.verify_selected(positions, deepcopy(samples), role=role)
            for sample, row in zip(samples, rows):
                assert type(sample.embedding_vector) is list
                assert sample.embedding_vector == list(row.embedding_vector)
                assert sample.text == row.text and sample.citation == row.citation
        summary["source_inventory_artifact"]["sha256"] = "0" * 64
        assert session.summary()["source_inventory_artifact"] == _ref(spec.source_inventory_artifact)


def test_v8_checkpoint_provenance_is_distinct_exact_and_counter_independent(campaign_issued):
    _, spec, _, descriptor, _ = campaign_issued
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        before = inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), session.summary())
        session.build_sample(session.indices_for("train")[0])
        session.verify_boundary("diagnostic")
        assert inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), session.summary()) == before
        assert before["job_schema_version"] == worker.CAMPAIGN_SCHEMA_VERSION
        assert before["embedding_input_storage"] == "python_list"
        assert before["job_spec_sha256"] == spec.canonical_sha256
        assert before["dataset_snapshot_id"] == spec.dataset_snapshot_id
        assert before["split_snapshot_id"] == spec.split_snapshot_id
        assert before["binding"] == "owner_snapshot_source_campaign_projection_identity"
        for field in ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
                      "produced_record_projection_artifact", "corpus_manifest_artifact"):
            assert before[field] == _ref(getattr(spec, field))
        for field in ("embedding_receipt_artifacts", "corpus_source_artifacts"):
            assert before[field] == [_ref(artifact) for artifact in getattr(spec, field)]
        assert len(before["embedding_receipt_artifacts"]) > 1
        assert not {"index_sha256", "embedding_production_artifact", "arrow_embedding_inputs_artifact"}.intersection(before)
        for field in ("source_authority_authenticated", "embedding_producer_authenticated",
                      "runtime_cryptographically_attested", "global_holdout_verified", "admitted"):
            assert before[field] is False
        before["embedding_receipt_artifacts"][0]["sha256"] = "0" * 64
        assert session.summary()["embedding_receipt_artifacts"][0] == _ref(spec.embedding_receipt_artifacts[0])


@pytest.mark.parametrize("kind", ["inventory", "partitions", "receipt_set", "projection", "leaf", "source",
                                   "manifest", "job", "snapshot"])
def test_v8_boundary_guards_every_selected_cas_closure_kind(campaign_issued, kind):
    registry, spec, _, descriptor, _ = campaign_issued
    payload = json.loads(Path(descriptor.path).read_bytes())
    paths = {"inventory": spec.source_inventory_artifact.path, "partitions": spec.source_partitions_artifact.path,
        "receipt_set": spec.embedding_receipt_set_artifact.path, "projection": spec.produced_record_projection_artifact.path,
        "leaf": spec.embedding_receipt_artifacts[0].path, "source": spec.corpus_source_artifacts[0].path,
        "manifest": spec.corpus_manifest_artifact.path, "job": registry.artifact_path(payload["job_spec_artifact"]),
        "snapshot": descriptor.path}
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        path = Path(paths[kind])
        with path.open("r+b") as stream:
            first = stream.read(1)
            stream.seek(0)
            stream.write(bytes([first[0] ^ 1]))
        with pytest.raises(inputs.DaemonCorpusInputError, match="changed"):
            session.verify_boundary("before_persistence")
        assert session.summary()["poisoned"] is True
        with pytest.raises(inputs.DaemonCorpusInputError, match="provenance|descriptor"):
            inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), session.summary())


@pytest.mark.parametrize("kind", ["leaf", "source", "inventory", "projection"])
def test_v8_missing_or_aliased_artifacts_cannot_fall_back(campaign_issued, tmp_path, kind):
    _, spec, _, descriptor, _ = campaign_issued
    artifact = {"leaf": spec.embedding_receipt_artifacts[0], "source": spec.corpus_source_artifacts[0],
        "inventory": spec.source_inventory_artifact, "projection": spec.produced_record_projection_artifact}[kind]
    path = Path(artifact.path)
    replacement = tmp_path / "alias-target"
    replacement.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(replacement)
    with pytest.raises((inputs.DaemonCorpusInputError, ValueError)):
        inputs.VerifiedDaemonCorpusInputs(descriptor)


def test_v8_worker_authorization_precedes_daemon_source_or_leaf_reads(campaign_issued, monkeypatch):
    _, spec, _, descriptor, _ = campaign_issued
    selected = {item.path for item in (*spec.embedding_receipt_artifacts, *spec.corpus_source_artifacts)}
    read_bound = inputs._read_bound
    checked = []
    def read(path, reference, **kwargs):
        checked.append(str(path))
        assert str(path) not in selected
        return read_bound(path, reference, **kwargs)
    def reject(*_):
        raise ValueError("fixture authorization rejection before source access")
    monkeypatch.setattr(inputs, "_read_bound", read)
    monkeypatch.setattr(inputs, "_verify_corpus_job_inputs", reject)
    with pytest.raises(ValueError, match="authorization rejection"):
        inputs.VerifiedDaemonCorpusInputs(descriptor)
    assert spec.produced_record_projection_artifact.path in checked
    assert selected.isdisjoint(checked)


@pytest.mark.parametrize("kind", ["missing_schema", "v7_schema", "arrow_storage", "old_producer", "old_index",
    "arrow_artifact", "missing_root", "wrong_root", "wrong_projection", "wrong_leaf", "wrong_source",
    "row_bool", "verified_int", "source_authority", "runtime_attestation", "heldout", "admit",
    "wrong_descriptor", "poisoned", "wrong_snapshot", "root_authority", "root_attestation"])
def test_v8_provenance_rejects_misbindings_inflated_claims_and_downgrades(campaign_issued, kind):
    descriptor = campaign_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        summary = session.summary()
    verification = summary["corpus_verification"]
    projection = verification["produced_record_projection_verification"]
    if kind == "missing_schema":
        del summary["job_schema_version"]
    elif kind == "v7_schema":
        summary["job_schema_version"] = worker.ARROW_INPUT_SCHEMA_VERSION
    elif kind == "arrow_storage":
        summary["embedding_input_storage"] = "arrow_mapped_float32"
    elif kind == "old_producer":
        verification["embedding_production_verified"] = True
    elif kind == "old_index":
        verification["corpus_index_verification"] = {}
    elif kind == "arrow_artifact":
        summary["arrow_embedding_inputs_artifact"] = summary["source_inventory_artifact"]
    elif kind == "missing_root":
        del summary["source_inventory_artifact"]
    elif kind == "wrong_root":
        summary["source_partitions_artifact"]["sha256"] = "0" * 64
    elif kind == "wrong_projection":
        summary["produced_record_projection_artifact"]["sha256"] = "0" * 64
    elif kind == "wrong_leaf":
        summary["embedding_receipt_artifacts"][0]["sha256"] = "0" * 64
    elif kind == "wrong_source":
        summary["corpus_source_artifacts"][0]["sha256"] = "0" * 64
    elif kind == "row_bool":
        summary["row_count"] = True
    elif kind == "verified_int":
        verification["source_campaign_verified"] = 1
    elif kind == "source_authority":
        projection["source_authority_authenticated"] = True
    elif kind == "runtime_attestation":
        projection["runtime_cryptographically_attested"] = True
    elif kind == "heldout":
        projection["global_holdout_verified"] = True
    elif kind == "admit":
        projection["admitted"] = True
    elif kind == "wrong_descriptor":
        summary["descriptor"]["sha256"] = "0" * 64
    elif kind == "poisoned":
        summary["input_integrity_verified"] = False
    elif kind == "wrong_snapshot":
        projection["dataset_snapshot_id"] = "sha256:" + "0" * 64
    elif kind == "root_authority":
        verification["source_campaign_verification"]["source_partition_verification"]["source_authority_authenticated"] = True
    else:
        verification["source_campaign_verification"]["receipt_set_verification"]["runtime_cryptographically_attested"] = True
    with pytest.raises(inputs.DaemonCorpusInputError, match="provenance|descriptor"):
        inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), summary)


def test_v8_snapshot_cannot_relabel_campaign_variant(campaign_issued, tmp_path):
    registry, _, _, descriptor, _ = campaign_issued
    payload = json.loads(Path(descriptor.path).read_bytes())
    payload["variant_manifest"]["source_campaign_binding"]["source_inventory"]["sha256"] = "0" * 64
    payload["variant_manifest_sha256"] = inputs._sha(canonical_json_bytes(payload["variant_manifest"]))
    changed = _restage(registry, payload, tmp_path)
    with pytest.raises((inputs.DaemonCorpusInputError, coordinator.TrainingCoordinationError)):
        inputs.VerifiedDaemonCorpusInputs(changed)
