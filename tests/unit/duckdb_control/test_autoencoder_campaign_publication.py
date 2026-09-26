"""Offline owner capture and restoration preserve exact control-plane state.

Only synthetic vectors and an empty three-byte checkpoint are used. Registry
state transitions below are explicit fixtures, never worker/model execution.
"""

import json
import os
from pathlib import Path
import socket

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_campaign_publication as publication
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.huggingface import autoencoder_campaign_release as transport
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_batches as batches
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as compact
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import _campaign_inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import _prepare


TABLES = ("meta", "operations", "variants", "versions", "heads", "runs", "events", "outbox")


def _forbidden(*args, **kwargs):
    pytest.fail("campaign evidence packaging must not construct state, execute models or contact services")


@pytest.fixture(autouse=True)
def no_model_or_network(monkeypatch):
    for owner, name in (
        (modal.AdaptiveModalAutoencoder, "__init__"),
        (modal.ModalAutoencoderTrainingState, "__init__"),
        (modal.ModalAutoencoderTrainingState, "from_dict"),
        (compact, "deserialize_checkpoint"), (compact, "load_checkpoint"),
        (sparse, "resolve_checkpoint"), (sparse, "replay_patch"),
        (sparse, "checkpoint_identity"), (socket.socket, "connect"),
        (socket, "create_connection"),
    ):
        monkeypatch.setattr(owner, name, _forbidden)


def _snapshot(registry):
    # Same live owner, so even its meta owner generation must remain unchanged.
    # Public pending_outbox alone omits acknowledged rows and truncates at 100.
    with registry._transaction() as connection:
        result = {}
        for name in TABLES:
            rows = connection.execute("SELECT * FROM autoencoder_control." + name).fetchall()
            assert len(rows) <= 256
            result[name] = sorted(rows, key=repr)
        return result


def _page(registry, root):
    inputs_root = root / "inputs"
    inputs_root.mkdir()
    inputs, binding, fixture = _campaign_inputs(registry, inputs_root)
    (inputs_root / "base.json").write_bytes(b"{}\n")
    template = _prepare(registry, inputs_root, job_updates=inputs,
        variant_updates={"source_campaign_binding": binding})
    output = root / "future-workers"
    output.mkdir()
    generated = batches.prepare_campaign_batches(registry, template.run_id,
        receipt_resolver=fixture.case.receipt_resolver,
        source_resolver=fixture.case.source_resolver, output_root=output,
        training_batch_size=2, validation_batch_size=2, max_batches=3)
    assert len(generated["jobs"]) == 3
    return template, generated


def _build(registry, generated, destination, **kwargs):
    return publication.build_registered_campaign_package(registry,
        generation_artifact=generated["generation_artifact"],
        plan_artifact=generated["plan_artifact"], destination=destination, **kwargs)


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def _stage_json(registry, root, name, value):
    path = root / name
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode())
    return registry.stage_artifact(path)


def _run_state(registry, root, run_id, status):
    if status == "queued":
        return None
    lease = registry.claim_run("fixture-claim-" + status, run_id, "fixture-no-worker")["lease"]
    if status == "failed":
        registry.fail_run("fixture-fail", lease, {"admitted": False, "fixture_only": True})
    elif status == "completed":
        candidate = root / "excluded-candidate.json"
        candidate.write_bytes(b'{"candidate_history_only":true}\n')
        artifact = registry.stage_artifact(candidate)
        registry.complete_run("fixture-complete", lease, artifact,
            {"admitted": False, "fixture_only": True, "candidate_artifact": artifact})
        return artifact
    elif status == "requeued":
        with registry._transaction() as connection:
            connection.execute("UPDATE autoencoder_control.runs SET status='queued', lease=NULL WHERE run_id=?",
                               [run_id])
    return None


def test_repeated_owner_capture_preserves_all_eight_tables_and_exact_package(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        # Include acknowledged delivery history so a pending-only check could
        # not accidentally stand in for complete outbox preservation.
        event = registry.pending_outbox("ducklake")[0]
        delivery = registry.claim_outbox_event("fixture-claim-event", event["event_id"],
            "ducklake", "fixture-no-service")["delivery"]
        registry.ack_outbox("fixture-ack-event", event["event_id"], "ducklake",
            {"fixture_only": True}, delivery["lease"])
        before = _snapshot(registry)
        first = _build(registry, generated, tmp_path / "first")
        assert _snapshot(registry) == before
        repeated = _build(registry, generated, tmp_path / "repeat")
        assert _snapshot(registry) == before
        assert first["package_id"] == repeated["package_id"]
        assert first["package_manifest_artifact"] == repeated["package_manifest_artifact"]
        assert _files(tmp_path / "first") == _files(tmp_path / "repeat")
        manifest = json.loads((tmp_path / "first/campaign-package.json").read_bytes())
        assert [run["run_id"] for run in manifest["run_records"]] == [template.run_id, *generated["run_ids"]]
        assert all(registry.get_run(run_id)["status"] == "queued" for run_id in generated["run_ids"])
        assert first["qualification"]["completion_history_exported"] is False
        assert first["qualification"]["execution_authorized"] is False


@pytest.mark.parametrize("status", ["queued", "running", "failed", "completed"])
def test_template_historical_status_is_preserved_without_exporting_candidate_history(tmp_path, status):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        excluded = _run_state(registry, owner, template.run_id, status)
        if excluded is not None:
            # Candidate availability is not part of this selected-input scope.
            registry.artifact_path(excluded).unlink()
        before = _snapshot(registry)
        report = _build(registry, generated, tmp_path / "package")
        assert _snapshot(registry) == before
        manifest = json.loads((tmp_path / "package/campaign-package.json").read_bytes())
        assert manifest["run_records"][0] == registry.get_run(template.run_id)
        assert manifest["run_records"][0]["status"] == status
        assert report["qualification"]["completion_history_exported"] is False
        if excluded is not None:
            assert excluded["sha256"] not in {ref["sha256"] for ref in manifest["artifacts"]}
            assert len(manifest["version_records"]) == 1


@pytest.mark.parametrize("status", ["running", "failed", "completed", "requeued"])
def test_generated_nonfresh_runs_reject_before_builder_without_other_effects(tmp_path, monkeypatch, status):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        _, generated = _page(registry, owner)
        _run_state(registry, owner, generated["run_ids"][0], status)
        before = _snapshot(registry)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="fresh queued"):
            _build(registry, generated, tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("field", ["base_checkpoint", "source_inventory_artifact",
                                   "corpus_source_artifacts", "embedding_receipt_artifacts"])
def test_foreign_job_locator_rejected_before_selected_io_or_builder(tmp_path, monkeypatch, field):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        job = template.to_dict()
        artifact = job[field][0] if type(job[field]) is list else job[field]
        artifact["path"] = str(tmp_path / "foreign-owner" / artifact["sha256"])
        spec = TrainingJobSpec.from_dict(job)
        job_ref = _stage_json(registry, owner, "foreign-job.json", spec.to_dict())
        with registry._transaction() as connection:
            connection.execute("UPDATE autoencoder_control.runs SET spec=? WHERE run_id=?",
                [json.dumps({"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": job_ref}), template.run_id])
        generation = json.loads(registry.artifact_path(generated["generation_artifact"]).read_bytes())
        generation["recipe"]["template_job_spec_artifact"] = job_ref
        generation["recipe"]["template_job_spec_sha256"] = spec.canonical_sha256
        modified = {**generated, "generation_artifact": _stage_json(registry, owner, "foreign-generation.json", generation)}
        selected = {ref.sha256 for ref in (*template.embedding_receipt_artifacts, *template.corpus_source_artifacts)}
        original = publication._hash_owner_artifact

        def reject_selected(path, ref):
            assert ref["sha256"] not in selected, "selected payload was read before owner locator rejection"
            return original(path, ref)

        monkeypatch.setattr(publication, "_hash_owner_artifact", reject_selected)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="outside the current owner CAS"):
            _build(registry, modified, tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("changed", ["recipe", "plan", "both"])
def test_recipe_and_plan_must_name_current_owner_root_before_selected_io(tmp_path, monkeypatch, changed):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        generation = json.loads(registry.artifact_path(generated["generation_artifact"]).read_bytes())
        plan = json.loads(registry.artifact_path(generated["plan_artifact"]).read_bytes())
        if changed in {"recipe", "both"}:
            generation["recipe"]["artifact_root"] = str(tmp_path / "foreign-cas")
        if changed in {"plan", "both"}:
            plan["artifact_root"] = str(tmp_path / "foreign-cas")
        modified = {**generated,
            "generation_artifact": _stage_json(registry, owner, "wrong-root-generation.json", generation),
            "plan_artifact": _stage_json(registry, owner, "wrong-root-plan.json", plan)}
        selected = {ref.sha256 for ref in (*template.embedding_receipt_artifacts, *template.corpus_source_artifacts)}
        original = publication._hash_owner_artifact

        def reject_selected(path, ref):
            assert ref["sha256"] not in selected
            return original(path, ref)

        monkeypatch.setattr(publication, "_hash_owner_artifact", reject_selected)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="current owner CAS root"):
            _build(registry, modified, tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("field", ["max_control_bytes", "max_blobs", "max_blob_bytes", "max_total_bytes",
    "max_directories", "max_namespace_entries", "max_path_depth", "max_path_bytes"])
def test_mutated_limit_object_rejected_before_any_artifact_or_registry_read(tmp_path, monkeypatch, field):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        limits = transport.CampaignPackageLimits()
        object.__setattr__(limits, field, getattr(limits, field) + 1)
        monkeypatch.setattr(registry, "verify_artifact", _forbidden)
        monkeypatch.setattr(publication, "_hash_owner_artifact", _forbidden)
        monkeypatch.setattr(registry, "get_run", _forbidden)
        monkeypatch.setattr(publication, "_read_owner_metadata", _forbidden)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        descriptor = {"sha256": "a" * 64, "bytes": 1}
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="capture limits"):
            publication.build_registered_campaign_package(registry, generation_artifact=descriptor,
                plan_artifact=descriptor, destination=tmp_path / "package", limits=limits)
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


def test_oversized_plan_descriptor_rejects_before_plan_io(tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        _, generated = _page(registry, owner)
        oversized = {**generated, "plan_artifact": {**generated["plan_artifact"], "bytes": 4 * 1024**2 + 1}}
        original = publication._hash_owner_artifact

        def no_plan_read(path, ref):
            assert ref["sha256"] != generated["plan_artifact"]["sha256"]
            return original(path, ref)

        monkeypatch.setattr(publication, "_hash_owner_artifact", no_plan_read)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="root byte bound"):
            _build(registry, oversized, tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


def test_generated_job_aggregate_rejects_before_any_job_io(tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        generation = json.loads(registry.artifact_path(generated["generation_artifact"]).read_bytes())
        for row in generation["jobs"]:
            row["job_spec_artifact"]["bytes"] = 24 * 1024**2
        modified = {**generated,
            "generation_artifact": _stage_json(registry, owner, "oversized-job-page.json", generation)}
        forbidden_digests = {row["job_spec_artifact"]["sha256"] for row in generation["jobs"]}
        forbidden_digests.add(registry.get_run(template.run_id)["spec"]["job_spec_artifact"]["sha256"])
        original = publication._hash_owner_artifact

        def no_job_read(path, ref):
            assert ref["sha256"] not in forbidden_digests
            return original(path, ref)

        monkeypatch.setattr(publication, "_hash_owner_artifact", no_job_read)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="page aggregate bound"):
            _build(registry, modified, tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("kind", ["fifo", "oversized_regular"])
def test_owner_cas_special_or_grown_artifact_rejects_without_unbounded_registry_read(tmp_path, monkeypatch, kind):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        ref = {"sha256": "a" * 64, "bytes": 1}
        path = registry.artifact_path(ref)
        path.parent.mkdir()
        if kind == "fifo":
            os.mkfifo(path)
        else:
            path.write_bytes(b"{}")
        monkeypatch.setattr(registry, "verify_artifact", _forbidden)
        monkeypatch.setattr(publication, "build_campaign_package", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="regular file|byte count differs"):
            publication.build_registered_campaign_package(registry, generation_artifact=ref,
                plan_artifact=ref, destination=tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


def test_bounded_hash_keeps_registry_configured_artifact_limit(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts", max_artifact_bytes=1) as registry:
        ref = {"sha256": "a" * 64, "bytes": 2}
        monkeypatch.setattr(registry, "verify_artifact", _forbidden)
        monkeypatch.setattr(publication, "_hash_owner_artifact", _forbidden)
        before = _snapshot(registry)
        with pytest.raises(publication.AutoencoderCampaignPublicationError, match="configured registry byte bound"):
            publication.build_registered_campaign_package(registry, generation_artifact=ref,
                plan_artifact=ref, destination=tmp_path / "package")
        assert _snapshot(registry) == before
        assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("change_template", [False, True])
def test_owner_state_change_during_blob_copy_rejects_at_final_barrier(tmp_path, monkeypatch, change_template):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        template, generated = _page(registry, owner)
        run_id = template.run_id if change_template else generated["run_ids"][0]
        original = transport._copy_blob
        changed = []

        def change_after_copy(*args, **kwargs):
            original(*args, **kwargs)
            if not changed:
                registry.claim_run("fixture-during-copy", run_id, "fixture-no-worker")
                changed.append(_snapshot(registry))

        monkeypatch.setattr(transport, "_copy_blob", change_after_copy)
        with pytest.raises(publication.AutoencoderCampaignPublicationError,
                           match="bindings changed|fresh queued"):
            _build(registry, generated, tmp_path / "package")
        assert len(changed) == 1
        assert _snapshot(registry) == changed[0]
        assert registry.get_run(run_id)["status"] == "running"


def test_restore_needs_no_owner_and_never_uses_historical_absolute_paths(tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    with AutoencoderRegistry(owner / "registry.duckdb", owner / "artifacts") as registry:
        _, generated = _page(registry, owner)
        before = _snapshot(registry)
        report = _build(registry, generated, tmp_path / "package")
        assert _snapshot(registry) == before
    original_files = _files(tmp_path / "package")
    owner.rename(tmp_path / "historical-owner-away")
    monkeypatch.setattr(AutoencoderRegistry, "__init__", _forbidden)
    monkeypatch.setattr(AutoencoderRegistry, "get_run", _forbidden)
    restored = transport.restore_campaign_package(tmp_path / "package", tmp_path / "restored",
        expected_manifest_sha256=report["package_manifest_artifact"]["sha256"])
    assert restored["package_id"] == report["package_id"]
    assert restored["qualification"] == report["qualification"]
    assert _files(tmp_path / "restored") == original_files == _files(tmp_path / "package")
    assert restored["qualification"]["historical_absolute_paths_used"] is False
    assert restored["qualification"]["execution_authorized"] is False
    assert not owner.exists()
