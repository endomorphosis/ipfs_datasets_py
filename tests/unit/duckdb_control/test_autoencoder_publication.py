"""Real owner/CAS publication recovery with synthetic checkpoint contents.

These tests prepare local private packages and immutable outbox intents. They
do not train a model, validate an evaluation, approve an upload or contact a Hub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_publication as publication
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes


REPOSITORY = Path(__file__).resolve().parents[3]
REPO_ID = "fixture-owner/private-autoencoder"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("publication storage fixtures must not contact the network")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


def _owner(root):
    return AutoencoderRegistry(root / "owner.duckdb", root / "artifacts")


def _seed(registry, root, *, language="en", suffix="base", compact=False, register_variant=True):
    variant_id = f"language-{language}"
    variant = {"source_languages": [language], "target_logic": "typed_deontic",
               "architecture": "modal_autoencoder", "parameter_schema": "fixture-preserved-v1"}
    if register_variant:
        registry.register_variant(f"variant-{language}", variant_id, variant)
    source = root / f"{language}-{suffix}.state"
    state = None
    if compact:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint, serialize_checkpoint
        state = ModalAutoencoderTrainingState(
            feature_embedding_weights={"original source-like key": [-0.0, 0.12345678901234568, 5e-324], "empty": [], suffix: [0.25]},
            decoded_embeddings={"unremoved sample memory": [0.75, -0.0]},
            applied_todo_ids=["duplicate", "duplicate"],
        )
        state.legal_ir_view_logits["synthetic-change"] = 0.125
        state.applied_leanstral_guidance_ids.append("synthetic-not-guidance")
        payload = serialize_checkpoint(state, metric_lineage={"fixture": "not-evaluation"},
                                       metadata={"synthetic_storage_fixture": True})
    else:
        payload = ("{\n  \"feature_embedding_weights\": {\"source / é\": [-0.0, 0.125]},\n"
                   "  \"sample_memory\": {\"text retained\": [1, 2]},\n"
                   f"  \"fixture_variant\": {json.dumps(language + '-' + suffix)}\n}}\n").encode()
    source.write_bytes(payload)
    if compact:
        # The registered artifact is authoritative. Its ordinary serializer may
        # normalize ordering/duplicate IDs before publication even begins.
        state = load_checkpoint(source, recover=False, allow_json=False).state
    artifact = registry.stage_artifact(source)
    receipt = registry.register_version(f"version-{language}-{suffix}", variant_id, artifact,
                                        metadata={"synthetic_storage_fixture": True})
    return {"version": registry.get_version(receipt["version_id"]), "variant": variant,
            "source": source, "bytes": payload, "state": state}


def _prepare(registry, root, seeded, **options):
    values = {"operation_id": "publish-fixture", "version_id": seeded["version"]["version_id"],
              "repo_id": REPO_ID, "output_directory": root / "publication"}
    values.update(options)
    return publication.prepare_autoencoder_publication(registry, **values)


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _assert_queued(registry, result, version):
    assert result["schema"] == "autoencoder-private-publication-preparation-v1"
    assert result["status"] == "queued"
    assert result["version_id"] == version["version_id"]
    assert result["uploaded"] is False and result["admitted"] is False
    event = registry.get_outbox_event("huggingface", result["event_id"])
    assert event["kind"] == "publication_requested"
    assert event["payload"] == {"version_id": version["version_id"], "plan_artifact": result["plan_artifact"]}
    assert event["status"] == "pending" and event["lease"] is None and event["receipt"] is None
    assert result["operation_receipt"]["uploaded"] is False
    assert registry.verify_artifact(result["plan_artifact"]) == result["plan_artifact"]


@pytest.mark.parametrize("compact", [False, True], ids=["legacy-original-bytes", "native-compact-original-bytes"])
def test_selected_non_head_version_restores_exact_package_after_owner_restart(tmp_path, compact):
    with _owner(tmp_path) as registry:
        selected = _seed(registry, tmp_path, compact=compact)
        different = _seed(registry, tmp_path, suffix="different-head", compact=compact, register_variant=False)
        assert selected["version"]["version_id"] != different["version"]["version_id"]
        assert selected["bytes"] != different["bytes"]
        registry.initialize_head("head", "language-en", "main", different["version"]["version_id"])
        before_head = registry.resolve_head("language-en", "main")
        evaluation = tmp_path / "evaluation.json"
        evaluation.write_bytes(b'{"synthetic_fixture":true,"admitted":false,"score":0.125}\n')
        evaluation_ref = registry.stage_artifact(evaluation)
        options = {"evaluation_artifacts": (evaluation_ref,)}
        result = _prepare(registry, tmp_path, selected, **options)
        _assert_queued(registry, result, selected["version"])
        package_bytes = _files(tmp_path / "publication/package")
        assert registry.resolve_head("language-en", "main") == before_head
        selected["source"].unlink()
        evaluation.unlink()
        shutil.rmtree(tmp_path / "publication/package")
    with _owner(tmp_path) as registry:
        # Historical queued replay is independent of deleted local package files.
        assert _prepare(registry, tmp_path, selected, **options) == result
        restored = publication.restore_autoencoder_publication(
            registry, event_id=result["event_id"], destination=tmp_path / "restored")
        assert _files(restored.package_root) == package_bytes
        checkpoint = restored.release_root / ("state.compact" if compact else "state.json")
        assert checkpoint.read_bytes() == selected["bytes"]
        assert checkpoint.stat().st_ino != registry.artifact_path(selected["version"]["artifact"]).stat().st_ino
        manifest = json.loads((restored.release_root / "release-manifest.json").read_bytes())
        assert manifest["identities"]["registry_version_id"] == selected["version"]["version_id"]
        assert manifest["evaluation_status"] == "supplied_not_revalidated"
        assert manifest["admitted"] is False
        assert restored.publication_plan.repository_id == REPO_ID
        assert restored.publication_plan.dry_run is True
        assert restored.publication_plan.remote_write_contacted is False
        assert restored.publication_plan.metadata["upload_ready"] is False
        if compact:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot
            loaded = load_checkpoint(checkpoint, recover=False, allow_json=False)
            assert exact_state_snapshot(loaded.state) == exact_state_snapshot(selected["state"])
            assert len(exact_state_snapshot(loaded.state)["components"]) == 38
        assert registry.resolve_head("language-en", "main") == before_head
        assert len(registry.pending_outbox("huggingface")) == 1
        _assert_queued(registry, result, selected["version"])


def test_independent_language_versions_have_separate_intents_and_exact_variant_manifests(tmp_path):
    with _owner(tmp_path) as registry:
        versions = {language: _seed(registry, tmp_path, language=language) for language in ("en", "fr")}
        results = {}
        for language, seeded in versions.items():
            registry.initialize_head(f"head-{language}", f"language-{language}", "main", seeded["version"]["version_id"])
            results[language] = _prepare(registry, tmp_path, seeded, operation_id=f"publish-{language}",
                                         output_directory=tmp_path / f"publication-{language}")
        assert results["en"]["event_id"] != results["fr"]["event_id"]
        assert results["en"]["plan_artifact"] != results["fr"]["plan_artifact"]
        for language, result in results.items():
            restored = publication.restore_autoencoder_publication(
                registry, event_id=result["event_id"], destination=tmp_path / f"restore-{language}")
            config = json.loads((restored.release_root / "config.json").read_bytes())
            assert config["variant_manifest"] == versions[language]["variant"]
            assert (restored.release_root / "state.json").read_bytes() == versions[language]["bytes"]
            assert registry.resolve_head(f"language-{language}", "main")["generation"] == 1
        assert len(registry.pending_outbox("huggingface")) == 2


@pytest.mark.parametrize("replacement", ["different-evaluation", "wrong-byte-count", "wrong-hash"])
def test_evaluation_descriptor_substitution_cannot_change_frozen_preparation(tmp_path, replacement):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        path = tmp_path / "evaluation.json"
        path.write_bytes(b'{"fixture":1}\n')
        original = registry.stage_artifact(path)
        result = _prepare(registry, tmp_path, seeded, evaluation_artifacts=(original,))
        if replacement == "different-evaluation":
            path.write_bytes(b'{"fixture":2}\n')
            changed = registry.stage_artifact(path)
        elif replacement == "wrong-byte-count":
            changed = {**original, "bytes": original["bytes"] + 1}
        else:
            changed = {**original, "sha256": "0" * 64}
        with pytest.raises(ValueError):
            _prepare(registry, tmp_path, seeded, evaluation_artifacts=(changed,))
        assert _prepare(registry, tmp_path, seeded, evaluation_artifacts=(original,)) == result
        assert len(registry.pending_outbox("huggingface")) == 1


@pytest.mark.parametrize("max_bytes", [True, 0, -1, 512 * 1024 * 1024 + 1, 1])
def test_invalid_or_insufficient_package_budget_fails_before_builder_or_cas_growth(tmp_path, monkeypatch, max_bytes):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        before = _files(registry.artifact_root)
        def forbidden(*args, **kwargs):
            raise AssertionError("budget must be checked before package construction")
        monkeypatch.setattr(publication, "build_private_resume_release", forbidden)
        with pytest.raises(ValueError):
            _prepare(registry, tmp_path, seeded, max_package_bytes=max_bytes)
        assert _files(registry.artifact_root) == before
        assert registry.pending_outbox("huggingface") == []


def test_same_preparation_cannot_be_reused_by_another_owner(tmp_path):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        expected = _prepare(registry, tmp_path, seeded)
    other = tmp_path / "other"
    other.mkdir()
    with _owner(other) as registry:
        equivalent = _seed(registry, other)
        assert equivalent["version"] == seeded["version"]
        with pytest.raises(ValueError):
            _prepare(registry, tmp_path, equivalent)
        assert registry.pending_outbox("huggingface") == []
    with _owner(tmp_path) as registry:
        assert _prepare(registry, tmp_path, seeded) == expected


@pytest.mark.parametrize("delivery_state", ["pending", "leased", "acknowledged"])
def test_restore_preserves_outbox_delivery_state_and_never_implies_upload(tmp_path, delivery_state):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        result = _prepare(registry, tmp_path, seeded)
        if delivery_state != "pending":
            claimed = registry.claim_outbox_event("fixture-claim", result["event_id"], "huggingface", "fixture-reader")
            if delivery_state == "acknowledged":
                registry.ack_outbox("fixture-ack", result["event_id"], "huggingface",
                                    {"synthetic_delivery_fixture": True, "uploaded": False}, claimed["delivery"]["lease"])
        before = registry.get_outbox_event("huggingface", result["event_id"])
        assert before["status"] == delivery_state
        restored = publication.restore_autoencoder_publication(
            registry, event_id=result["event_id"], destination=tmp_path / "restored")
        assert restored.publication_plan.remote_write_contacted is False
        assert registry.get_outbox_event("huggingface", result["event_id"]) == before


@pytest.mark.parametrize("target", ["envelope", "checkpoint", "package-manifest", "evaluation"])
def test_restore_rejects_tampered_cas_closure_without_acknowledging(tmp_path, target):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        evaluation = tmp_path / "evaluation.json"
        evaluation.write_bytes(b'{"fixture":true}\n')
        evaluation_ref = registry.stage_artifact(evaluation)
        result = _prepare(registry, tmp_path, seeded, evaluation_artifacts=(evaluation_ref,))
        envelope = json.loads(registry.artifact_path(result["plan_artifact"]).read_bytes())
        if target == "envelope":
            descriptor = result["plan_artifact"]
        elif target == "checkpoint":
            descriptor = seeded["version"]["artifact"]
        elif target == "evaluation":
            descriptor = evaluation_ref
        else:
            descriptor = next(entry["artifact"] for entry in envelope["files"] if entry["path"] == "package-manifest.json")
        path = registry.artifact_path(descriptor)
        original = path.read_bytes()
        path.chmod(0o600)
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        before = registry.get_outbox_event("huggingface", result["event_id"])
        with pytest.raises(ValueError):
            publication.restore_autoencoder_publication(
                registry, event_id=result["event_id"], destination=tmp_path / "invalid-restore")
        assert registry.get_outbox_event("huggingface", result["event_id"]) == before
        assert before["status"] == "pending" and before["receipt"] is None


def test_lost_enqueue_reply_resolves_exact_operation_after_package_deletion_and_restart(tmp_path, monkeypatch):
    observed = []
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        original = registry.enqueue_publication
        def commit_then_lose_reply(operation_id, version_id, plan_artifact):
            receipt = original(operation_id, version_id, plan_artifact)
            observed.append((operation_id, version_id, dict(plan_artifact), receipt))
            raise ConnectionError("synthetic reply loss after durable EnqueuePublication")
        monkeypatch.setattr(registry, "enqueue_publication", commit_then_lose_reply)
        try:
            initial = _prepare(registry, tmp_path, seeded)
        except ConnectionError:
            # A transport may propagate the lost response. Durable retry, rather
            # than this call's in-memory outcome, is the property under test.
            initial = None
        assert len(observed) == 1
        assert len(registry.pending_outbox("huggingface")) == 1
        frozen_request = (tmp_path / "publication/preparation.json").read_bytes()
        shutil.rmtree(tmp_path / "publication/package")
        (tmp_path / "publication/publication-envelope.json").unlink()
    with _owner(tmp_path) as registry:
        def forbidden(*args, **kwargs):
            raise AssertionError("committed historical replay must precede new staging/build/enqueue")
        monkeypatch.setattr(registry, "stage_artifact", forbidden)
        monkeypatch.setattr(registry, "enqueue_publication", forbidden)
        monkeypatch.setattr(publication, "build_private_resume_release", forbidden)
        restored = _prepare(registry, tmp_path, seeded)
        assert restored["operation_receipt"] == observed[0][3]
        assert restored["plan_artifact"] == observed[0][2]
        assert restored["version_id"] == observed[0][1]
        if initial is not None:
            assert restored == initial
        assert len(registry.pending_outbox("huggingface")) == 1
        assert registry.resolve_operation(observed[0][0], "EnqueuePublication", {
            "version_id": observed[0][1], "plan_artifact": observed[0][2]}) == observed[0][3]
        journal = json.loads((tmp_path / "publication/preparation.json").read_bytes())
        assert json.loads(frozen_request)["binding"] == journal["binding"]


def test_incomplete_package_is_retained_and_requires_new_output_directory(tmp_path, monkeypatch):
    class SimulatedProcessLoss(BaseException):
        pass
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        original = publication.build_private_resume_release
        def incomplete_build(version, artifact, destination, **kwargs):
            destination = Path(destination)
            destination.mkdir()
            (destination / "unfinished").write_bytes(b"retained crash evidence")
            raise SimulatedProcessLoss()
        monkeypatch.setattr(publication, "build_private_resume_release", incomplete_build)
        with pytest.raises(SimulatedProcessLoss):
            _prepare(registry, tmp_path, seeded)
        partial = _files(tmp_path / "publication/package")
        monkeypatch.setattr(publication, "build_private_resume_release", original)
        with pytest.raises((ValueError, FileNotFoundError)):
            _prepare(registry, tmp_path, seeded)
        assert _files(tmp_path / "publication/package") == partial
        assert registry.pending_outbox("huggingface") == []
        completed = _prepare(registry, tmp_path, seeded, output_directory=tmp_path / "fresh-publication")
        _assert_queued(registry, completed, seeded["version"])


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires POSIX SIGKILL")
def test_actual_sigkill_after_durable_staging_before_enqueue_recovers_from_disk(tmp_path):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        registry.initialize_head("head", "language-en", "main", seeded["version"]["version_id"])
        original_head = registry.resolve_head("language-en", "main")
    script = r'''
import json, os, signal, socket, sys
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.autoencoder_publication import prepare_autoencoder_publication
def denied(*args, **kwargs):
    raise AssertionError("synthetic storage child must stay offline")
socket.socket.connect = denied
root = Path(sys.argv[1])
registry = AutoencoderRegistry(root / "owner.duckdb", root / "artifacts")
def kill_before_enqueue(operation_id, version_id, plan_artifact):
    journal = json.loads((root / "publication/preparation.json").read_bytes())
    assert journal["bundle_ref"] == plan_artifact
    registry.verify_artifact(plan_artifact)
    envelope = json.loads(registry.artifact_path(plan_artifact).read_bytes())
    for entry in envelope["files"]:
        registry.verify_artifact(entry["artifact"])
    assert registry.pending_outbox("huggingface") == []
    print("SIGKILL_AFTER_DURABLE_CAS_BEFORE_ENQUEUE", flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
registry.enqueue_publication = kill_before_enqueue
prepare_autoencoder_publication(registry, operation_id="publish-fixture", version_id=sys.argv[2],
    repo_id="fixture-owner/private-autoencoder", output_directory=root / "publication")
raise AssertionError("enqueue fault point did not execute")
'''
    env = {**os.environ, "PYTHONPATH": str(REPOSITORY), "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
           "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1"}
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path), seeded["version"]["version_id"]],
                           cwd=REPOSITORY, env=env, text=True, capture_output=True, timeout=45, check=False)
    assert child.returncode == -signal.SIGKILL, child.stdout + child.stderr
    assert "SIGKILL_AFTER_DURABLE_CAS_BEFORE_ENQUEUE" in child.stdout
    journal = json.loads((tmp_path / "publication/preparation.json").read_bytes())
    assert journal["bundle_ref"] is not None
    with _owner(tmp_path) as registry:
        assert registry.pending_outbox("huggingface") == []
        assert registry.resolve_operation("publish-fixture", "EnqueuePublication", {
            "version_id": seeded["version"]["version_id"], "plan_artifact": journal["bundle_ref"]}) is None
        staged_before = _files(registry.artifact_root)
        result = _prepare(registry, tmp_path, seeded)
        _assert_queued(registry, result, seeded["version"])
        assert result["plan_artifact"] == journal["bundle_ref"]
        assert _files(registry.artifact_root) == staged_before
        assert registry.resolve_head("language-en", "main") == original_head
        assert len(registry.pending_outbox("huggingface")) == 1
        assert _prepare(registry, tmp_path, seeded) == result


def test_same_size_package_mutation_after_verified_load_is_rejected_before_staging(tmp_path, monkeypatch):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        original_cas = _files(registry.artifact_root)
        original_load = publication.load_private_resume_release
        changed = []
        def verified_then_mutated(*args, **kwargs):
            release = original_load(*args, **kwargs)
            path = release.package_root / "README.md"
            before = path.read_bytes()
            after = bytes([before[0] ^ 1]) + before[1:]
            assert len(before) == len(after) and before != after
            path.write_bytes(after)
            changed.append(path)
            return release
        monkeypatch.setattr(publication, "load_private_resume_release", verified_then_mutated)
        with pytest.raises(publication.AutoencoderPublicationError, match="inventory differs from verified manifest"):
            _prepare(registry, tmp_path, seeded)
        assert len(changed) == 1
        journal = json.loads((tmp_path / "publication/preparation.json").read_bytes())
        assert journal["bundle_ref"] is None and journal["result"] is None
        assert _files(registry.artifact_root) == original_cas
        assert registry.pending_outbox("huggingface") == []


def _different_plan_digest(bundle):
    digest = bundle["publication_plan_digest"]
    bundle["publication_plan_digest"] = digest[:-1] + ("0" if digest[-1] != "0" else "1")


def test_uncommitted_resealed_envelope_plan_substitution_cannot_enqueue_existing_package(tmp_path, monkeypatch):
    class StoppedBeforeEnqueue(BaseException):
        pass
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        original_enqueue = registry.enqueue_publication
        def stop(*args, **kwargs):
            raise StoppedBeforeEnqueue()
        monkeypatch.setattr(registry, "enqueue_publication", stop)
        with pytest.raises(StoppedBeforeEnqueue):
            _prepare(registry, tmp_path, seeded)
        journal_path = tmp_path / "publication/preparation.json"
        journal = json.loads(journal_path.read_bytes())
        assert journal["bundle_ref"] is not None and journal["result"] is None
        bundle = json.loads(registry.artifact_path(journal["bundle_ref"]).read_bytes())
        unchanged_package = _files(tmp_path / "publication/package")
        _different_plan_digest(bundle)
        substitute = tmp_path / "substituted-envelope.json"
        substitute.write_bytes(canonical_json_bytes(bundle) + b"\n")
        # Reseal both layers so rejection must reconcile the plan with the real
        # verified package, not merely notice a broken outer checksum.
        journal["bundle_ref"] = registry.stage_artifact(substitute)
        journal_path.write_bytes(canonical_json_bytes(journal) + b"\n")
        monkeypatch.setattr(registry, "enqueue_publication", original_enqueue)
        with pytest.raises(publication.AutoencoderPublicationError, match="frozen publication plan"):
            _prepare(registry, tmp_path, seeded)
        assert _files(tmp_path / "publication/package") == unchanged_package
        assert registry.pending_outbox("huggingface") == []
        assert registry.resolve_operation("publish-fixture", "EnqueuePublication", {
            "version_id": seeded["version"]["version_id"], "plan_artifact": journal["bundle_ref"]}) is None


def test_same_size_envelope_mutation_after_save_cannot_become_the_first_cas_binding(tmp_path, monkeypatch):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        original_save = publication._save
        changed = []
        def save_then_mutate(path, value):
            original_save(path, value)
            if path.name == "publication-envelope.json":
                before = path.read_bytes()
                bundle = json.loads(before)
                _different_plan_digest(bundle)
                after = canonical_json_bytes(bundle) + b"\n"
                assert len(after) == len(before) and after != before
                path.write_bytes(after)
                changed.append(path)
        monkeypatch.setattr(publication, "_save", save_then_mutate)
        with pytest.raises(ValueError, match="hash|SHA|sha256|digest"):
            _prepare(registry, tmp_path, seeded)
        assert len(changed) == 1
        journal = json.loads((tmp_path / "publication/preparation.json").read_bytes())
        assert journal["bundle_ref"] is None and journal["result"] is None
        assert registry.pending_outbox("huggingface") == []


def test_envelope_replaced_between_cas_verification_and_parse_is_rejected(tmp_path, monkeypatch):
    with _owner(tmp_path) as registry:
        seeded = _seed(registry, tmp_path)
        result = _prepare(registry, tmp_path, seeded)
        envelope_path = registry.artifact_path(result["plan_artifact"])
        before_event = registry.get_outbox_event("huggingface", result["event_id"])
        original_read = publication._read
        original_verify = registry.verify_artifact
        verified = []
        def verify_then_mark(descriptor):
            value = original_verify(descriptor)
            if descriptor == result["plan_artifact"]:
                verified.append(dict(descriptor))
            return value
        def mutate_before_read(path, **kwargs):
            if path == envelope_path:
                assert verified == [result["plan_artifact"]]
                before = path.read_bytes()
                bundle = json.loads(before)
                _different_plan_digest(bundle)
                after = canonical_json_bytes(bundle) + b"\n"
                assert len(after) == len(before) and after != before
                path.chmod(0o600)
                path.write_bytes(after)
            return original_read(path, **kwargs)
        monkeypatch.setattr(registry, "verify_artifact", verify_then_mark)
        monkeypatch.setattr(publication, "_read", mutate_before_read)
        with pytest.raises(publication.AutoencoderPublicationError, match="parsed publication envelope differs"):
            publication.restore_autoencoder_publication(
                registry, event_id=result["event_id"], destination=tmp_path / "never-restored")
        assert not (tmp_path / "never-restored").exists()
        assert registry.get_outbox_event("huggingface", result["event_id"]) == before_event
