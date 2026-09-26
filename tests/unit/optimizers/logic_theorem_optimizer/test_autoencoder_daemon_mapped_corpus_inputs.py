"""Real owner/session/IPC plumbing using declared synthetic producer fixtures.

No inference, daemon execution, training, or runtime-computation proof is claimed.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct

import numpy as np
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as arrow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_corpus_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as production
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_samples
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import ARROW_INPUT_SCHEMA_VERSION, SampleRecord
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_corpus_inputs import _prepare, _restage, issued


@pytest.fixture
def mapped_issued(tmp_path, monkeypatch):
    original = production.build_embedding_production_receipt

    def signed_zero_fixture(*args, **kwargs):
        results = []
        for result in kwargs["results"]:
            vector = list(result["vector"])
            vector[-1] = -0.0
            results.append({**result, "vector": vector})
        return original(*args, **{**kwargs, "results": results})

    monkeypatch.setattr(production, "build_embedding_production_receipt", signed_zero_fixture)
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, arrow_inputs=True)
        exported = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        yield registry, spec, exported, inputs.DaemonCorpusInputDescriptor(**exported["descriptor"])


def test_v7_export_is_existing_capsule_shape_and_restart_stable(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare(registry, tmp_path, arrow_inputs=True)
        before = registry.get_run(spec.run_id)
        head = registry.resolve_head("english-0", "best")
        first = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        raw = Path(first["descriptor"]["path"]).read_bytes()
        payload = json.loads(raw)
        assert spec.schema_version == ARROW_INPUT_SCHEMA_VERSION
        assert payload["schema_version"] == "autoencoder-daemon-corpus-inputs-v1"
        assert set(payload) == inputs._FIELDS
        assert raw == canonical_json_bytes(payload)
        assert payload["job_spec_sha256"] == spec.canonical_sha256
        assert first["registration"]["execution_authorized"] is False
        assert registry.get_run(spec.run_id) == before
        assert registry.resolve_head("english-0", "best") == head
    with AutoencoderRegistry(database, artifacts) as registry:
        assert inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs") == first
        assert Path(first["descriptor"]["path"]).read_bytes() == raw
        assert registry.get_run(spec.run_id) == before


def test_native_sample_keeps_same_mapping_exact_bits_without_asdict_copy(mapped_issued, monkeypatch):
    _, spec, _, descriptor = mapped_issued
    original_asdict = inputs.asdict

    def reject_sample_copy(value):
        if type(value) is SampleRecord:
            pytest.fail("mapped sample construction must not asdict the vector")
        return original_asdict(value)

    monkeypatch.setattr(inputs, "asdict", reject_sample_copy)
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        assert session.summary()["arrow_embedding_inputs_statistics"]["row_accesses"] == 0
        for role, rows in (("train", spec.samples), ("validation", spec.validation_samples)):
            indices = session.indices_for(role)
            samples = [session.build_sample(index) for index in indices]
            session.verify_selected(indices, samples, role=role)
            for index, sample, row in zip(indices, samples, rows):
                vector = sample.embedding_vector
                assert type(vector) is arrow.MappedEmbeddingVector
                assert vector._owner is session._mapped_inputs
                assert vector.record_id == session.record_id(index)
                assert np.shares_memory(vector.readonly_array(), session._mapped_inputs._values)
                assert vector.readonly_array().flags.writeable is False
                assert struct.pack("<384f", *vector) == struct.pack("<384f", *row.embedding_vector)
                assert struct.pack("!d", vector[-1]) == struct.pack("!d", -0.0)
                assert sample.text == row.text and sample.citation == row.citation
        summary = session.summary()
        assert summary["embedding_input_storage"] == "arrow_mapped_float32"
        assert summary["arrow_embedding_inputs_artifact"] == {
            "sha256": spec.arrow_embedding_inputs_artifact.sha256, "bytes": spec.arrow_embedding_inputs_artifact.bytes}
        assert summary["arrow_embedding_inputs_statistics"]["mapped_numeric_bytes"] == session.row_count * 384 * 4
        assert summary["corpus_verification"]["arrow_embedding_inputs_verification"]["whole_training_zero_copy"] is False
        assert summary["corpus_verification"]["embedding_production_verification"]["runtime_computation_proven"] is False
        summary["arrow_embedding_inputs_statistics"]["read_only"] = False
        assert session.summary()["arrow_embedding_inputs_statistics"]["read_only"] is True


@pytest.mark.parametrize("replacement", ["other_owner", "other_record", "list", "deepcopy", "short_slice", "reversed"])
def test_primary_selection_rejects_wrong_owner_record_or_detached_vector(mapped_issued, replacement):
    descriptor = mapped_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session, inputs.VerifiedDaemonCorpusInputs(descriptor) as other:
        indices = session.indices_for("train")
        sample = session.build_sample(indices[0])
        if replacement == "other_owner":
            vector = other.build_sample(indices[0]).embedding_vector
        elif replacement == "other_record":
            # All fixture rows have identical numeric bits; the record ID must still bind.
            vector = session.build_sample(indices[1]).embedding_vector
        elif replacement == "list":
            vector = list(sample.embedding_vector)
        elif replacement == "deepcopy":
            vector = deepcopy(sample).embedding_vector
        elif replacement == "short_slice":
            vector = sample.embedding_vector[1:]
        else:
            vector = sample.embedding_vector[::-1]
        with pytest.raises(inputs.DaemonCorpusInputError, match="mapped record|shape|vector bits"):
            session.verify_selected([indices[0]], [replace(sample, embedding_vector=vector)], role="train")
        assert session.summary()["poisoned"] is True


def test_signed_zero_drift_in_real_mapped_buffer_fails_selected_bits(mapped_issued):
    spec, descriptor = mapped_issued[1], mapped_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        index = session.indices_for("train")[0]
        sample = session.build_sample(index)
        mapped = session._mapped_inputs
        offset = mapped._values.__array_interface__["data"][0] - mapped._file_buffer.address
        offset += (index * 384 + 383) * 4
        with Path(spec.arrow_embedding_inputs_artifact.path).open("r+b") as stream:
            stream.seek(offset)
            assert stream.read(4) == struct.pack("<f", -0.0)
            stream.seek(offset)
            stream.write(struct.pack("<f", 0.0))
            stream.flush()
        assert sample.embedding_vector[-1] == -0.0  # Numeric equality hides the changed sign bit.
        with pytest.raises(inputs.DaemonCorpusInputError, match="vector bits"):
            session.verify_selected([index], [sample], role="train")


@pytest.mark.parametrize("change", ["bytes", "replacement", "symlink"])
def test_arrow_boundary_checks_reject_drift_before_persistence(mapped_issued, tmp_path, change):
    spec, descriptor = mapped_issued[1], mapped_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        path = Path(spec.arrow_embedding_inputs_artifact.path)
        raw = path.read_bytes()
        if change == "bytes":
            with path.open("r+b") as stream:
                stream.write(bytes([raw[0] ^ 1]))
        else:
            other = tmp_path / "replacement-arrow"
            other.write_bytes(raw)
            if change == "replacement":
                other.replace(path)
            else:
                path.unlink()
                path.symlink_to(other)
        with pytest.raises(inputs.DaemonCorpusInputError, match="changed|alias"):
            session.verify_boundary("before_persistence")
        assert session.summary()["failure"]["phase"] == "before_persistence"
        assert session.summary()["poisoned"] is True
    assert session.summary()["arrow_embedding_inputs_statistics"]["closed"] is True


def test_v7_arrow_must_use_exact_owner_cas_path(mapped_issued, tmp_path):
    registry, spec, _, descriptor = mapped_issued
    outside = tmp_path / "same-arrow-bytes"
    outside.write_bytes(Path(spec.arrow_embedding_inputs_artifact.path).read_bytes())
    changed = replace(spec, arrow_embedding_inputs_artifact=replace(spec.arrow_embedding_inputs_artifact, path=str(outside)))
    path = tmp_path / "changed-job.json"
    path.write_bytes(canonical_json_bytes(changed.to_dict()))
    job = registry.stage_artifact(path)
    payload = json.loads(Path(descriptor.path).read_bytes())
    payload.update(job_spec_artifact=job, job_spec_sha256=changed.canonical_sha256)
    snapshot = _restage(registry, payload, tmp_path)
    with pytest.raises(inputs.DaemonCorpusInputError, match="owner-staged CAS"):
        inputs.VerifiedDaemonCorpusInputs(snapshot)


def test_close_is_idempotent_releases_fd_and_detached_snapshot_survives(mapped_issued):
    session = inputs.VerifiedDaemonCorpusInputs(mapped_issued[3])
    sample = session.build_sample(session.indices_for("train")[0])
    snapshot = deepcopy([sample, sample])
    assert snapshot[0] is snapshot[1]
    assert type(snapshot[0].embedding_vector) is list
    bits = struct.pack("<384f", *snapshot[0].embedding_vector)
    mapped = session._mapped_inputs
    fd = mapped._fd
    session.close()
    session.close()
    assert mapped.closed and session.summary()["closed"]
    assert session.summary()["arrow_embedding_inputs_statistics"]["closed"] is True
    with pytest.raises(OSError):
        os.fstat(fd)
    with pytest.raises(arrow.ArrowInputError, match="closed"):
        _ = sample.embedding_vector[0]
    assert struct.pack("<384f", *snapshot[0].embedding_vector) == bits


@pytest.mark.parametrize("phase", ["after_mapping", "opening_boundary"])
def test_constructor_failure_closes_verified_mapping_and_preserves_primary(mapped_issued, monkeypatch, phase):
    mapped = []
    original_load = arrow.load_embedding_inputs_ipc
    original_verify = inputs._verify_corpus_job_inputs
    failure = RuntimeError("synthetic initialization failure")

    def track(*args, **kwargs):
        value = original_load(*args, **kwargs)
        mapped.append((value, value._fd))
        return value

    monkeypatch.setattr(arrow, "load_embedding_inputs_ipc", track)
    if phase == "after_mapping":
        def fail(spec, resources):
            original_verify(spec, resources)
            raise failure
        monkeypatch.setattr(inputs, "_verify_corpus_job_inputs", fail)
    else:
        def fail(self, phase):
            raise failure
        monkeypatch.setattr(inputs.VerifiedDaemonCorpusInputs, "verify_boundary", fail)
    with pytest.raises(RuntimeError) as caught:
        inputs.VerifiedDaemonCorpusInputs(mapped_issued[3])
    assert caught.value is failure
    assert len(mapped) == 1
    assert mapped[0][0].closed
    with pytest.raises(OSError):
        os.fstat(mapped[0][1])


def test_v6_summary_and_provenance_keep_legacy_shape_and_list_storage(issued):
    descriptor = issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        summary = session.summary()
        assert type(session.build_sample(session.indices_for("train")[0]).embedding_vector) is list
        assert not {"job_schema_version", "embedding_input_storage", "arrow_embedding_inputs_artifact",
                    "arrow_embedding_inputs_statistics"}.intersection(summary)
        corpus = summary["corpus_verification"]
        producer = corpus["embedding_production_verification"]
        expected = {"descriptor": descriptor.to_dict(), "job_spec_sha256": summary["job_spec_sha256"],
            "variant_manifest_sha256": summary["variant_manifest_sha256"],
            "dataset_snapshot_id": corpus["dataset_snapshot_id"], "split_snapshot_id": corpus["split_snapshot_id"],
            "index_sha256": corpus["corpus_index_verification"]["index_sha256"],
            "embedding_production_artifact": {"sha256": producer["sha256"], "bytes": producer["bytes"]},
            "binding": "owner_snapshot_transitive_input_identity", "checkpoint_authority_verified": False}
        assert canonical_json_bytes(inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), summary)) == canonical_json_bytes(expected)


def test_v7_provenance_uses_deterministic_verification_excludes_counters(mapped_issued):
    descriptor = mapped_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        before = inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), session.summary())
        session.build_sample(session.indices_for("train")[0])
        session.verify_boundary("diagnostic")
        after = inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), session.summary())
        assert before == after
        assert after["arrow_embedding_inputs_verification"] == session.summary()["corpus_verification"]["arrow_embedding_inputs_verification"]
        assert "arrow_embedding_inputs_statistics" not in after
        after["arrow_embedding_inputs_verification"]["read_only"] = False
        assert session.summary()["corpus_verification"]["arrow_embedding_inputs_verification"]["read_only"] is True


@pytest.mark.parametrize("change", ["missing_marker", "missing_arrow", "missing_base", "wrong_artifact", "wrong_producer",
    "row_bool", "dimension_bool", "readonly_int", "whole_copy_claim", "extra_arrow_field"])
def test_malformed_v7_provenance_does_not_fall_back_or_normalize_types(mapped_issued, change):
    descriptor = mapped_issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        summary = session.summary()
    verification = summary["corpus_verification"]["arrow_embedding_inputs_verification"]
    if change == "missing_marker":
        del summary["job_schema_version"]
    elif change == "missing_arrow":
        del summary["corpus_verification"]["arrow_embedding_inputs_verification"]
    elif change == "missing_base":
        del summary["corpus_verification"]["dataset_snapshot_id"]
    elif change == "wrong_artifact":
        summary["arrow_embedding_inputs_artifact"]["sha256"] = "0" * 64
    elif change == "wrong_producer":
        verification["production_sha256"] = "0" * 64
    elif change == "row_bool":
        summary["row_count"] = True
        verification["row_count"] = 1
    elif change == "dimension_bool":
        verification["dimension"] = True
    elif change == "readonly_int":
        verification["read_only"] = 1
    elif change == "whole_copy_claim":
        verification["whole_training_zero_copy"] = True
    else:
        verification["extra"] = True
    with pytest.raises(inputs.DaemonCorpusInputError, match="provenance"):
        inputs.corpus_input_checkpoint_provenance(descriptor.to_dict(), summary)
