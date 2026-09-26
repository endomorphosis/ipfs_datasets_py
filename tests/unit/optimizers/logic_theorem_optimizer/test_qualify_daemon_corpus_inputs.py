"""Qualification harness checks; synthetic vectors, no model or bridge generation."""
import copy
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/qualify_daemon_corpus_inputs.py"
    spec = importlib.util.spec_from_file_location("_local_corpus_qualification_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def issued_six(tmp_path):
    """Real owner and reader, explicitly synthetic producer declarations."""
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import load_corpus_index
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import build_corpus_manifest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import load_embedding_production_receipt
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_corpus_inputs import export_daemon_corpus_inputs
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_corpus_inputs import _fixtures

    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as owner:
        values, binding, _ = _fixtures["_indexed_corpus_inputs"](owner, tmp_path, production=True)
        source_paths = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in tmp_path.glob("indexed-source-*.txt")}
        resolver = lambda ref: source_paths[ref["sha256"]]
        production_ref = values["embedding_production_artifact"]
        production = load_embedding_production_receipt(production_ref["path"],
            expected_sha256=production_ref["sha256"], expected_size_bytes=production_ref["bytes"])
        records = production.to_corpus_records(resolver=resolver)
        index_ref = values["corpus_index_artifact"]
        index = load_corpus_index(index_ref["path"], expected_sha256=index_ref["sha256"], expected_size_bytes=index_ref["bytes"])
        by_id = {record.record_id: record for record in records}
        # Deliberately reverse role order; sorted-ID or text-only tests miss this.
        training = tuple(reversed(index.record_ids_for("train")[:3]))
        validation = tuple(reversed(index.record_ids_for("validation")[:3]))
        manifest = build_corpus_manifest([by_id[key] for key in (*training, *validation)],
            training_record_ids=training, validation_record_ids=validation, mode="corpus")
        saved = manifest.save(tmp_path / "six.json", resolver=resolver)

        def staged(path, digest):
            ref = owner.stage_artifact(path, digest)
            return {**ref, "path": str(owner.artifact_path(ref))}

        values.update(dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
            samples=[asdict(by_id[key].sample) for key in training],
            validation_samples=[asdict(by_id[key].sample) for key in validation],
            corpus_manifest_artifact=staged(saved["path"], saved["sha256"]),
            corpus_source_artifacts=[staged(resolver(ref), ref["sha256"]) for ref in manifest.source_refs])
        spec = _fixtures["_prepare"](owner, tmp_path, job_updates=values, variant_updates={
            "corpus_index_binding": binding, "embedding_production_binding": {
                "artifact": {k: production_ref[k] for k in ("sha256", "bytes")}}})
        exported = export_daemon_corpus_inputs(owner, spec.run_id, operation_id="issue-six")
        yield exported["descriptor"], spec.to_dict()


def test_actual_owner_issued_walk_preserves_order_roles_vectors_and_closes(harness, issued_six):
    snapshot, payload = issued_six
    result = harness.audit_inputs(snapshot, payload)
    assert result["closed_summary"]["closed"] is True
    assert result["closed_summary"]["counts"]["samples_built"] == 6
    assert result["closed_summary"]["counts"]["selected_checks"] == 2
    roles = result["roles"]
    assert len(roles["train"]) == len(roles["validation"]) == 3
    assert set(r["index"] for r in roles["train"]).isdisjoint(r["index"] for r in roles["validation"])
    assert [r["text_sha256"] for r in roles["train"]] == [hashlib.sha256(r["text"].encode()).hexdigest() for r in payload["samples"]]
    expected = hashlib.sha256(struct.pack("<384f", 1.0, *([0.0] * 383))).hexdigest()
    assert all(r["vector_float32_sha256"] == expected for rows in roles.values() for r in rows)
    assert result["verification"]["issuer_authenticated"] is False


@pytest.mark.parametrize("change", ["role_swap", "role_order", "text", "vector_bit", "signed_zero", "model"])
def test_walk_detects_independent_job_tampering(harness, issued_six, change):
    snapshot, original = issued_six
    payload = copy.deepcopy(original)
    if change == "role_swap":
        payload["samples"][0], payload["validation_samples"][0] = payload["validation_samples"][0], payload["samples"][0]
    elif change == "role_order":
        payload["samples"].reverse()
    elif change == "text":
        payload["samples"][0]["text"] += " Changed."
    elif change == "vector_bit":
        payload["samples"][0]["embedding_vector"][0] = struct.unpack("<f", struct.pack("<I", 0x3f800001))[0]
    elif change == "signed_zero":
        payload["samples"][0]["embedding_vector"][1] = -0.0
    else:
        payload["samples"][0]["embedding_model"] = "mock:stable-sha256"
    with pytest.raises(ValueError):
        harness.audit_inputs(snapshot, payload)


def test_vector_digest_rejects_rounded_non_native_numbers(harness):
    values = [0.0] * 384
    positive = harness.vector_digest(values)
    values[0] = -0.0
    assert harness.vector_digest(values) != positive
    for invalid in (True, 1, float("nan"), float("inf"), 0.1):
        values[0] = invalid
        with pytest.raises(ValueError):
            harness.vector_digest(values)


def test_argv_preserves_default_async_and_uses_explicit_local_owner_descriptor(harness):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    snapshot = {"path": "/private/artifacts/aa/" + "a" * 64, "sha256": "a" * 64, "bytes": 1024}
    for native in (False, True):
        argv = harness.daemon_argv(snapshot, 8192, native_cycle=native)
        args = runner.build_uscode_modal_daemon_arg_parser().parse_args(argv)
        assert "--snapshot-evaluation-enabled" not in argv
        assert args.snapshot_evaluation_enabled is True
        assert args.loop_role == "autoencoder" and args.max_cycles == 1
        assert args.train_count == args.validation_count == 3 and args.validation_canary_count == 0
        assert args.autoencoder_corpus_input == snapshot["path"]
        assert args.autoencoder_corpus_input_sha256 == snapshot["sha256"]
        assert args.autoencoder_corpus_input_bytes == snapshot["bytes"]
        assert args.duration_seconds == (600 if native else 0)
        assert args.bridge_evaluate_provers is False


@pytest.mark.parametrize("failure", ["undrained", "not_durable", "wrong_checksum", "short_write", "worker_error"])
def test_failed_persistence_never_passes_qualification(harness, failure):
    checkpoint = {"sha256": "a" * 64, "bytes": 123}
    summary = {"final_state_persistence": {"durable": True, "checksum": "a" * 64, "written_bytes": 123},
        "async_artifact_writer_shutdown": {"drained": True}, "async_artifact_writer": {"failed_count": 0}}
    assert all(harness.persistence_checks(summary, checkpoint).values())
    if failure == "undrained":
        summary["async_artifact_writer_shutdown"]["drained"] = False
    elif failure == "not_durable":
        summary["final_state_persistence"]["durable"] = False
    elif failure == "wrong_checksum":
        summary["final_state_persistence"]["checksum"] = "b" * 64
    elif failure == "short_write":
        summary["final_state_persistence"]["written_bytes"] = 122
    else:
        summary["async_artifact_writer"]["failed_count"] = 1
    assert not all(harness.persistence_checks(summary, checkpoint).values())


@pytest.mark.parametrize("failure", ["state", "sequence", "failed", "not_closed", "undrained", "zero_targets"])
def test_snapshot_lifecycle_cannot_pass_from_enabled_flag_alone(harness, failure):
    versions = {"state_version": "state", "compiler_version": "code", "holdout_version": "roles", "schema_version": "schema"}
    published = {"versions": versions, "sequence": 1}
    summary = {"snapshot_evaluation_enabled": True, "snapshot_shutdown": {"drained": True},
        "snapshot_evaluator": {"closed": True, "worker_alive": False, "published_snapshots": 1,
            "completed_evaluations": 1, "failed_evaluations": 0, "rejected_result_count": 0},
        "latest_published_snapshot": published, "latest_promoted_snapshot_evaluation": copy.deepcopy(published),
        "latest_promoted_snapshot_complete": True}
    assert all(harness.snapshot_checks(summary).values())
    if failure == "state":
        summary["latest_promoted_snapshot_evaluation"]["versions"]["state_version"] = "other"
    elif failure == "sequence":
        summary["latest_promoted_snapshot_evaluation"]["sequence"] = 0
    elif failure == "failed":
        summary["snapshot_evaluator"]["failed_evaluations"] = 1
    elif failure == "not_closed":
        summary["snapshot_evaluator"]["closed"] = False
    elif failure == "undrained":
        summary["snapshot_shutdown"]["drained"] = False
    else:
        summary["snapshot_evaluator"]["published_snapshots"] = 0
    assert not all(harness.snapshot_checks(summary).values())


def test_source_inventory_skips_py_named_directory_and_detects_added_sources(harness, tmp_path, monkeypatch):
    package = tmp_path / "ipfs_datasets_py"
    (package / "directory.py").mkdir(parents=True)
    (package / "code.py").write_text("value = 1\n")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    before = harness.source_manifest()
    assert set(before) == {"ipfs_datasets_py/code.py"}
    (package / "new.py").write_text("value = 2\n")
    assert harness.source_manifest() != before


def test_help_is_standalone_and_does_not_open_owner(harness, tmp_path):
    completed = subprocess.run([sys.executable, str(Path(harness.__file__)), "--help"],
        cwd=tmp_path, text=True, capture_output=True, timeout=15)
    assert completed.returncode == 0 and "--native-cycle" in completed.stdout
    assert list(tmp_path.iterdir()) == []


def test_real_async_write_failure_surfaces_and_cannot_claim_durable_completion(harness, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import AsyncArtifactWriter
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"preserve me")
    writer = AsyncArtifactWriter(tmp_path / "spool")
    try:
        future = writer.write_state_checkpoint(blocker / "checkpoint.json", ModalAutoencoderTrainingState(), cycle=1)
        with pytest.raises(OSError):
            future.result(timeout=5)
        assert writer.wait_until_idle(timeout=5)
        summary = {"final_state_persistence": {"checkpoint_enqueued": True, "durable": False},
            "async_artifact_writer_shutdown": {"drained": True}, "async_artifact_writer": writer.summary()}
        checks = harness.persistence_checks(summary, {"sha256": "a" * 64, "bytes": 1})
        assert checks["durable"] is checks["writer_failed_count_zero"] is False
        assert blocker.read_bytes() == b"preserve me"
    finally:
        assert writer.close(wait=True, timeout=5)


def test_os_network_denial_is_real_and_confined_to_child(harness):
    # This child imports only the existing stdlib/libseccomp helper: no owner,
    # model, target generation or daemon evaluation is invoked.
    script = ("import sys; sys.path.insert(0, " + repr(str(Path(harness.__file__).parent)) + "); "
        "from audit_native_uscode_embedding_production import _deny_network; "
        "import json; print(json.dumps(_deny_network()))")
    completed = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mechanism"] == "linux_seccomp" and result["socket_denial_verified"] is True
