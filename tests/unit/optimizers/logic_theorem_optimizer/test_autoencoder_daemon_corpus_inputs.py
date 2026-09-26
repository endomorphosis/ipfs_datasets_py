"""Owner-issued synthetic input fixtures; no native model/training qualification."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_corpus_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import verify_corpus_job_inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_samples


# Reuse explicitly synthetic v6 declarations from existing owner tests. The
# actual new registry/export/session path runs; these are not inference claims.
_fixtures = runpy.run_path(str(Path(__file__).with_name("test_autoencoder_training_coordinator.py")))


def _prepare(registry, root, *, production=True, arrow_inputs=False):
    values, index_binding, _ = _fixtures["_indexed_corpus_inputs"](
        registry, root, production=production, arrow_inputs=arrow_inputs)
    variant = {"corpus_index_binding": index_binding}
    if production:
        variant["embedding_production_binding"] = {
            "artifact": {key: values["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
    return _fixtures["_prepare"](registry, root, job_updates=values, variant_updates=variant)


@pytest.fixture
def issued(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        exported = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        yield registry, spec, exported, inputs.DaemonCorpusInputDescriptor(**exported["descriptor"])


def _restage(registry, payload, tmp_path):
    path = tmp_path / "modified-snapshot.json"
    path.write_bytes(canonical_json_bytes(payload))
    reference = registry.stage_artifact(path)
    return inputs.DaemonCorpusInputDescriptor(str(registry.artifact_path(reference)), **reference)


def test_export_restart_is_byte_stable_without_run_lease_or_head_change(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare(registry, tmp_path)
        before = registry.get_run(spec.run_id)
        head = registry.resolve_head("english-0", "best")
        first = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        assert first == inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
        assert registry.get_run(spec.run_id) == before
        assert registry.resolve_head("english-0", "best") == head
        assert first["registration"]["scope"] == "immutable_inputs_only"
        assert first["registration"]["execution_authorized"] is False
        assert first["registration"]["promotion_authorized"] is False
        payload = json.loads(Path(first["descriptor"]["path"]).read_bytes())
        assert set(payload) == inputs._FIELDS
        assert payload["variant_manifest_sha256"] == hashlib.sha256(
            canonical_json_bytes(registry.get_variant("english-0")["manifest"])).hexdigest()
    with AutoencoderRegistry(database, artifacts) as registry:
        assert inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs") == first


def test_completed_run_and_existing_output_remain_valid_input_anchor(issued):
    registry, spec, _, descriptor = issued
    lease = registry.claim_run("claim-fixture", spec.run_id, "fixture-worker")["lease"]
    registry.complete_run("finish-fixture", lease, {"sha256": spec.base_checkpoint.sha256,
                                                   "bytes": spec.base_checkpoint.bytes},
                          {"unit_fixture": True, "admitted": False})
    Path(spec.output_directory).mkdir()
    again = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-completed")
    assert again["descriptor"] == descriptor.to_dict()
    with pytest.raises(coordinator.TrainingCoordinationError, match="attempt directory must be new"):
        coordinator._validate_runs(registry, [spec])


def test_session_reuses_exact_worker_integrity_and_builds_native_list_vectors(issued):
    _, spec, _, descriptor = issued
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        assert session.row_count == 4
        summary = session.summary()
        assert summary["corpus_verification"] == verify_corpus_job_inputs(spec)
        assert summary["issuer_authenticated"] is False
        assert summary["live_owner_lease_verified"] is False
        assert summary["checkpoint_authority_verified"] is False
        assert summary["corpus_verification"]["embedding_production_verification"]["runtime_computation_proven"] is False
        for role, rows in (("train", spec.samples), ("validation", spec.validation_samples)):
            positions = session.indices_for(role)
            samples = [session.build_sample(index) for index in positions]
            session.verify_selected(positions, samples, role=role)
            for index, sample, row in zip(positions, samples, rows):
                assert type(sample) is legal_samples.LegalSample
                assert type(sample.embedding_vector) is list
                assert sample.embedding_vector == list(row.embedding_vector)
                assert sample.text == row.text
                assert session.text_length(index) == len(row.text)
                assert session.record_id(index).startswith("sha256:")
            # Snapshot copies own their vectors and remain verifiable.
            session.verify_selected(positions, deepcopy(samples), role=role)
        assert set(session.indices_for("train")).isdisjoint(session.indices_for("validation"))
        summary["counts"]["samples_built"] = -1
        summary["corpus_verification"].clear()
        assert session.summary()["counts"]["samples_built"] == 4
        session.verify_boundary("before_persistence")
    assert session.summary()["closed"] is True
    with pytest.raises(inputs.DaemonCorpusInputError, match="closed"):
        session.build_sample(0)


@pytest.mark.parametrize("index", [-1, 4, True, 1.0, "0", None])
def test_row_indices_are_exact_bounded_integers(issued, index):
    with inputs.VerifiedDaemonCorpusInputs(issued[3]) as session:
        with pytest.raises(inputs.DaemonCorpusInputError, match="row index"):
            session.build_sample(index)


@pytest.mark.parametrize("field,value", [("text", "changed"), ("sample_id", "changed"),
                                          ("normalized_text", "changed"), ("source", "other"),
                                          ("embedding_model", "mock:stable-sha256")])
def test_selected_native_scalar_mutation_poisoned(issued, field, value):
    with inputs.VerifiedDaemonCorpusInputs(issued[3]) as session:
        index = session.indices_for("train")[0]
        sample = replace(session.build_sample(index), **{field: value})
        with pytest.raises(inputs.DaemonCorpusInputError):
            session.verify_selected([index], [sample], role="train")
        assert session.summary()["poisoned"] is True
        with pytest.raises(inputs.DaemonCorpusInputError, match="poisoned"):
            session.verify_boundary("shutdown")


def test_selected_vector_signed_zero_mutation_and_wrong_role_rejected(issued):
    descriptor = issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        index = session.indices_for("train")[0]
        sample = session.build_sample(index)
        sample.embedding_vector[1] = -0.0
        with pytest.raises(inputs.DaemonCorpusInputError, match="vector bits"):
            session.verify_selected([index], [sample], role="train")
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        index = session.indices_for("train")[0]
        sample = session.build_sample(index)
        with pytest.raises(inputs.DaemonCorpusInputError, match="role partition"):
            session.verify_selected([index], [sample], role="validation")


@pytest.mark.parametrize("kind", ["source", "manifest", "index", "production", "job", "snapshot"])
def test_boundary_detects_same_inode_mutation_of_every_closure_kind(issued, kind):
    registry, spec, _, descriptor = issued
    payload = json.loads(Path(descriptor.path).read_bytes())
    paths = {
        "source": spec.corpus_source_artifacts[0].path, "manifest": spec.corpus_manifest_artifact.path,
        "index": spec.corpus_index_artifact.path, "production": spec.embedding_production_artifact.path,
        "job": registry.artifact_path(payload["job_spec_artifact"]), "snapshot": descriptor.path,
    }
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        path = Path(paths[kind])
        raw = path.read_bytes()
        with path.open("r+b") as stream:
            stream.write(bytes([raw[0] ^ 1]))
        with pytest.raises(inputs.DaemonCorpusInputError, match="changed"):
            session.verify_boundary("before_persistence")
        assert session.summary()["failure"]["phase"] == "before_persistence"


def test_boundary_detects_same_bytes_inode_replacement(issued, tmp_path):
    spec, descriptor = issued[1], issued[3]
    with inputs.VerifiedDaemonCorpusInputs(descriptor) as session:
        source = Path(spec.corpus_source_artifacts[0].path)
        replacement = tmp_path / "replacement"
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
        with pytest.raises(inputs.DaemonCorpusInputError, match="identity changed"):
            session.verify_boundary("shutdown")


@pytest.mark.parametrize("kind", ["snapshot_alias", "source_alias", "missing_source"])
def test_bad_active_inputs_fail_without_live_fallback(issued, tmp_path, kind):
    _, spec, _, descriptor = issued
    if kind == "snapshot_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(descriptor.path)
        descriptor = replace(descriptor, path=str(alias))
    else:
        path = Path(spec.corpus_source_artifacts[0].path)
        raw = path.read_bytes()
        path.unlink()
        if kind == "source_alias":
            other = tmp_path / "other-source"
            other.write_bytes(raw)
            path.symlink_to(other)
    with pytest.raises(inputs.DaemonCorpusInputError):
        inputs.VerifiedDaemonCorpusInputs(descriptor)


@pytest.mark.parametrize("field,value", [("job_spec_sha256", "0" * 64), ("run_id", "other"),
                                          ("variant_manifest_sha256", "0" * 64)])
def test_snapshot_cannot_relabel_exact_registered_payload(issued, tmp_path, field, value):
    registry, _, _, descriptor = issued
    payload = json.loads(Path(descriptor.path).read_bytes())
    payload[field] = value
    changed = _restage(registry, payload, tmp_path)
    with pytest.raises(inputs.DaemonCorpusInputError):
        inputs.VerifiedDaemonCorpusInputs(changed)


def test_export_requires_v6_and_owner_staged_closure(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, production=False)
        with pytest.raises(inputs.DaemonCorpusInputError, match="exactly a v6"):
            inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="bad-export")


def test_shared_owner_extraction_preserves_queued_validation(issued):
    registry, spec, _, _ = issued
    resolved = coordinator.registered_corpus_job_inputs(registry, spec.run_id)
    assert resolved["spec"].canonical_sha256 == spec.canonical_sha256
    assert resolved["corpus_verification"] == coordinator._validate_runs(registry, [spec])[spec.run_id]
    # Caller copy with correct bytes but a non-owner path remains rejected.
    source = spec.corpus_source_artifacts[0]
    alias = Path(spec.output_directory).with_name("caller-owned-source")
    alias.write_bytes(Path(source.path).read_bytes())
    changed = replace(spec, corpus_source_artifacts=(replace(source, path=str(alias)),
                                                   *spec.corpus_source_artifacts[1:]))
    with pytest.raises(coordinator.TrainingCoordinationError, match="staged immutable"):
        coordinator._verify_staged_corpus_artifacts(registry, changed)


@pytest.mark.parametrize("options", [{"path": "/tmp/snapshot"}, {"sha256": "a" * 64},
                                     {"bytes": 1}, {"path": "/tmp/snapshot", "sha256": "a" * 64,
                                                    "bytes": True},
                                     {"path": "/tmp/snapshot", "sha256": "a" * 64,
                                      "bytes": inputs.MAX_SNAPSHOT_BYTES + 1}])
def test_descriptor_requires_complete_strict_bounded_values(options):
    with pytest.raises(inputs.DaemonCorpusInputError):
        inputs.DaemonCorpusInputDescriptor.from_options(**options)


def test_all_absent_descriptor_is_only_legacy_optout():
    assert inputs.DaemonCorpusInputDescriptor.from_options() is None


@pytest.mark.parametrize("raw", [b"{}", b'{"x":1,"x":1}', b'{"x":NaN}', b'[]', b'null',
                                 b" " * (inputs.MAX_SNAPSHOT_BYTES + 1)])
def test_snapshot_parser_rejects_malformed_or_oversize_json(raw):
    with pytest.raises(inputs.DaemonCorpusInputError):
        inputs._parse_snapshot(raw)
