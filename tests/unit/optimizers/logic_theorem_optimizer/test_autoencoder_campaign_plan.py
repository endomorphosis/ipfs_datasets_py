"""Bounded campaign plans and restart using injected updates, never training.

Real registry, corpus, checkpoint and plan codecs verify synthetic declarations.
No model evaluation, optimization, native inference, publication or admission is
performed. A completed fixture run only establishes its artifact contract.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_plan as plans
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import _campaign_inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import (
    _combined, _forbid_native, _injected_worker,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare, _indexed_corpus_inputs,
)


ERRORS = (plans.CampaignPlanError, RegistryError, coordinator.TrainingCoordinationError, ValueError)
ROOT_FIELDS = {"schema_version", "artifact_root", "variant_id", "variant_manifest_sha256",
    "source_campaign_binding", "parent_policy", "batches", "coverage", "admitted", "formalized",
    "source_authority_authenticated", "global_holdout_verified"}
BATCH_FIELDS = {"ordinal", "batch_id", "run_id", "job_id", "job_spec_artifact", "job_spec_sha256",
    "base_version_id", "training_record_ids", "validation_record_ids", "target_snapshot_id",
    "target_snapshot_artifact", "arrow_feature_weights_artifact", "training_config_sha256",
    "autoencoder_config_sha256"}


@pytest.fixture(autouse=True)
def no_model_execution(monkeypatch):
    _forbid_native(monkeypatch)


def _forbidden(*args, **kwargs):
    pytest.fail("no worker/executor should be reached by this inspection or restart")


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _reidentify(batch):
    batch["batch_id"] = "sha256:" + hashlib.sha256(_canonical({key: value for key, value in batch.items()
                                                             if key != "batch_id"})).hexdigest()


def _stage_plan(registry, root, value, *, name="changed-plan"):
    path = root / (name + ".json")
    path.write_bytes(plans.encode_campaign_plan(value))
    return registry.stage_artifact(path)


def _register(registry, root, payload, suffix):
    spec = worker.TrainingJobSpec.from_dict({**payload, "job_id": "job-" + suffix, "run_id": "run-" + suffix,
        "output_directory": str(root / ("attempt-" + suffix))})
    path = root / ("job-" + suffix + ".json")
    path.write_bytes(_canonical(spec.to_dict()))
    registry.create_run("create-" + suffix, spec.run_id, "english-0", spec.base_version_id,
        {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(path)})
    return spec


def _pair(registry, root, *, job_updates=None):
    inputs, binding, fixture = _campaign_inputs(registry, root)
    state = modal.ModalAutoencoderTrainingState(feature_embedding_weights={
        "padding": [index / 1000 for index in range(2000)]})
    (root / "base.json").write_text(state.to_json() + "\n")
    first = _prepare(registry, root, job_updates={**inputs, "capture_sparse_patches": True,
        "candidate_storage": "sparse", **(job_updates or {})}, variant_updates={"source_campaign_binding": binding})
    second_inputs, second_binding, _ = _campaign_inputs(registry, root, fixture=fixture, batch_number=1)
    assert second_binding == binding
    second = _register(registry, root, {**first.to_dict(), **second_inputs}, "second")
    return first, second


def _updater(calls, captured):
    def execute(spec):
        calls.append(spec.run_id)
        def trainer(model, samples, *, validation_samples, **kwargs):
            assert samples and validation_samples
            assert kwargs.get("legal_ir_targets") is None
            before = model.state.state_identity()
            key = "batch:" + samples[0].sample_id
            previous = model.state.feature_embedding_weights.get(key, [0.0])[0]
            with model.state.transaction(label="injected-plan-transport") as transaction:
                model.state.feature_embedding_weights[key] = [previous + 0.25, -0.0]
            sink = kwargs.get("accepted_patch_sink")
            if spec.capture_sparse_patches:
                assert callable(sink)
                sink(transaction.patch, {
                    "base_state_identity": before, "result_state_identity": model.state.state_identity(),
                    "base_revision": transaction.patch.base_revision, "result_revision": transaction.patch.result_revision,
                    "label": "injected-plan-transport"})
            else:
                assert sink is None
            captured[spec.run_id] = (model.state.to_json() + "\n").encode()
            return {"accepted_epochs": 1, "after": {"legal_ir_target_count": 0},
                    "stopped_reason": "injected_plan_transport_no_bridge_execution"}
        return worker.execute_training_job(spec, trainer=trainer)
    return execute


def _complete(registry, spec, calls=None, captured=None, *, policy=coordinator.SparseCheckpointPolicy()):
    calls = [] if calls is None else calls
    captured = {} if captured is None else captured
    result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
        worker_function=_updater(calls, captured), sparse_checkpoint_policy=policy)
    assert result["failed"] == [], json.dumps(result["failed"], sort_keys=True)
    return result["completed"][0]


def _assert_flags(report):
    for name in ("admitted", "formalized", "promotion_performed", "publication_performed"):
        assert report[name] is False


def _assert_untouched(registry, specs, before):
    assert {spec.run_id: registry.get_run(spec.run_id) for spec in specs} == before
    assert all(not Path(spec.output_directory).exists() for spec in specs)
    assert registry.resolve_head("english-0", "best")["version_id"] == specs[0].base_version_id


def test_exact_ordered_plan_roundtrip_and_metadata_coverage(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _pair(registry, tmp_path)
        value = plans.build_campaign_plan(registry, [spec.run_id for spec in specs])
        raw = plans.encode_campaign_plan(value)
        assert plans.decode_campaign_plan(raw) == value
        assert plans.encode_campaign_plan(plans.decode_campaign_plan(raw)) == raw
        assert set(value) == ROOT_FIELDS
        assert value["schema_version"] == "autoencoder-campaign-plan-v1"
        assert value["parent_policy"] == "common_fixed_parent"
        assert value["artifact_root"] == str(registry.artifact_root)
        assert value["source_campaign_binding"] == registry.get_variant("english-0")["manifest"]["source_campaign_binding"]
        for number, (batch, spec) in enumerate(zip(value["batches"], specs, strict=True)):
            assert set(batch) == BATCH_FIELDS
            assert batch["ordinal"] == number
            assert batch["run_id"] == spec.run_id and batch["job_id"] == spec.job_id
            assert batch["job_spec_sha256"] == spec.canonical_sha256
            checked = coordinator.registered_corpus_job_inputs(registry, spec.run_id)
            assert batch["job_spec_artifact"] == checked["job_spec_artifact"]
            for role in ("training_record_ids", "validation_record_ids"):
                assert batch[role] == checked["corpus_verification"][role]
            expected = deepcopy(batch)
            _reidentify(expected)
            assert batch == expected
        assert value["coverage"]["planned_training_record_count"] == 4
        assert value["coverage"]["planned_validation_record_count"] == 4
        assert value["coverage"]["planned_validation_occurrences"] == 4
        for name in ("admitted", "formalized", "source_authority_authenticated", "global_holdout_verified"):
            assert value[name] is False
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        assert set(artifact) == {"sha256", "bytes"}
        assert registry.artifact_path(artifact).read_bytes() == raw
        assert plans.build_campaign_plan(registry, [spec.run_id for spec in specs]) == value
        reverse = plans.build_campaign_plan(registry, [spec.run_id for spec in reversed(specs)])
        assert plans.encode_campaign_plan(reverse) != raw
        assert reverse["batches"][0]["run_id"] == specs[1].run_id
        assert reverse["batches"][0]["batch_id"] != value["batches"][1]["batch_id"]


def test_restart_skips_external_completion_then_all_completed_needs_no_executor(tmp_path):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    calls, captured = [], {}
    with AutoencoderRegistry(database, artifacts) as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        completed = _complete(registry, first, calls, captured)
        # No campaign execution receipt exists: completion is recovered from
        # the durable run/version link after reopening the owner.
        first_version = completed["version_id"]
    with AutoencoderRegistry(database, artifacts) as registry:
        before = plans.inspect_campaign_plan(registry, artifact)
        assert before["status"] == "ready"
        assert (before["completed_count"], before["queued_count"], before["unresolved_count"]) == (1, 1, 0)
        assert before["batches"][0]["candidate_version_id"] == first_version
        report = plans.run_campaign_plan(registry, artifact, executor_factory=ImmediateExecutor,
            worker_function=_updater(calls, captured))
        assert report["status"] == "complete"
        assert report["dispatched_run_ids"] == [second.run_id]
        assert calls == [first.run_id, second.run_id]
        assert report["dispatch"]["execution_mode"] == "injected_test"
        assert report["completed_count"] == 2
        _assert_flags(report)
        for row in report["batches"]:
            version = registry.get_version(row["candidate_version_id"])
            assert version["parent_version_id"] == first.base_version_id
            resolved = resolve_checkpoint(version["artifact"], resolver=registry.artifact_path)
            assert (resolved.state.to_json() + "\n").encode() == captured[row["run_id"]]
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
    with AutoencoderRegistry(database, artifacts) as registry:
        report = plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert report["status"] == "complete" and report["dispatch"] is None
        assert report["dispatched_run_ids"] == []
        assert {spec.run_id: registry.get_run(spec.run_id) for spec in specs} == saved
        assert report["batches"][0]["candidate_version_id"] == first_version
        _assert_flags(report)


def test_bounded_dispatch_preserves_plan_order_and_defers_remaining_jobs(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        calls = []
        report = plans.run_campaign_plan(registry, artifact, max_new_batches=1,
            executor_factory=ImmediateExecutor, worker_function=_updater(calls, {}))
        assert calls == report["dispatched_run_ids"] == [first.run_id]
        assert report["deferred_run_ids"] == [second.run_id]
        assert report["status"] == "ready" and report["queued_count"] == 1
        assert registry.get_run(second.run_id)["attempt"] == 0
        assert not Path(second.output_directory).exists()
        _assert_flags(report)


@pytest.mark.parametrize("target", ["last_job", "last_leaf", "last_source", "plan"])
def test_corrupt_final_member_fails_before_any_claim(tmp_path, target):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        if target == "last_job":
            path = registry.artifact_path(registry.get_run(second.run_id)["spec"]["job_spec_artifact"])
        elif target == "last_leaf":
            path = Path(second.embedding_receipt_artifacts[0].path)
        elif target == "last_source":
            path = Path(second.corpus_source_artifacts[0].path)
        else:
            path = registry.artifact_path(artifact)
        path.write_bytes(b"corrupted immutable campaign input")
        before = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        with pytest.raises(ERRORS):
            plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        _assert_untouched(registry, specs, before)


@pytest.mark.parametrize("state", ["failed", "running", "expired"])
def test_unresolved_attempt_blocks_without_reclaim_even_after_owner_restart(tmp_path, state):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    now = [100.0]
    with AutoencoderRegistry(database, artifacts, clock=lambda: now[0]) as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        lease = registry.claim_run("prior-claim", second.run_id, "prior-owner", 10)["lease"]
        if state == "failed":
            registry.fail_run("prior-failure", lease, {"admitted": False, "error": "retained synthetic failure"})
        elif state == "expired":
            now[0] = 200.0
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
    with AutoencoderRegistry(database, artifacts, clock=lambda: now[0]) as registry:
        inspected = plans.inspect_campaign_plan(registry, artifact)
        assert inspected["status"] == "unresolved" and inspected["unresolved_count"] == 1
        assert inspected["batches"][1]["status"] == "unresolved"
        assert inspected["batches"][1]["reason"]
        report = plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert report["status"] == "unresolved"
        assert report["dispatch"] is None and report["dispatched_run_ids"] == []
        _assert_untouched(registry, specs, saved)
        _assert_flags(report)


@pytest.mark.parametrize("target", ["candidate", "patch", "receipt"])
def test_completed_corruption_is_not_a_skippable_batch(tmp_path, target):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        done = _complete(registry, first)
        if target == "candidate":
            ref = done["candidate"]
        elif target == "receipt":
            ref = done["worker_receipt_artifact"]
        else:
            receipt = json.loads(registry.artifact_path(done["worker_receipt_artifact"]).read_bytes())
            ref = {key: receipt["sparse_patch_segments"][0][key] for key in ("sha256", "bytes")}
        registry.artifact_path(ref).write_bytes(b"corrupt completed evidence")
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        with pytest.raises(ERRORS):
            plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert {spec.run_id: registry.get_run(spec.run_id) for spec in specs} == saved
        assert not Path(second.output_directory).exists()
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id


def test_explicit_existing_parent_is_bound_without_implicit_head_selection(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = _pair(registry, tmp_path)
        parent = _complete(registry, first)
        child = _register(registry, tmp_path, {**second.to_dict(),
            **coordinator.registered_checkpoint_inputs(registry, parent["version_id"]),
            "base_version_id": parent["version_id"]}, "child")
        run_ids = [first.run_id, child.run_id]
        with pytest.raises(ERRORS):
            plans.build_campaign_plan(registry, run_ids)
        value = plans.build_campaign_plan(registry, run_ids, parent_policy="explicit_registered_parents")
        assert [batch["base_version_id"] for batch in value["batches"]] == [first.base_version_id, parent["version_id"]]
        artifact = plans.seal_campaign_plan(registry, run_ids, parent_policy="explicit_registered_parents")
        calls = []
        report = plans.run_campaign_plan(registry, artifact, executor_factory=ImmediateExecutor,
            worker_function=_updater(calls, {}))
        assert report["status"] == "complete" and calls == [child.run_id]
        assert registry.get_version(report["batches"][1]["candidate_version_id"])["parent_version_id"] == parent["version_id"]
        assert registry.get_run(second.run_id)["status"] == "queued"
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id


@pytest.mark.parametrize("mutation", ["reverse_training", "validation_as_training", "job_digest", "training_config",
    "constructor_config", "target_id", "base_version", "foreign_run", "root", "variant", "artifact_root"])
def test_well_formed_false_plan_binding_rejected_before_dispatch(tmp_path, mutation):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _pair(registry, tmp_path)
        value = plans.build_campaign_plan(registry, [spec.run_id for spec in specs])
        batch = value["batches"][-1]
        if mutation == "reverse_training":
            batch["training_record_ids"].reverse()
        elif mutation == "validation_as_training":
            batch["training_record_ids"], batch["validation_record_ids"] = batch["validation_record_ids"], batch["training_record_ids"]
        elif mutation == "job_digest":
            batch["job_spec_sha256"] = "0" * 64
        elif mutation == "training_config":
            batch["training_config_sha256"] = "0" * 64
        elif mutation == "constructor_config":
            batch["autoencoder_config_sha256"] = "0" * 64
        elif mutation == "target_id":
            batch["target_snapshot_id"] = "sha256:" + "0" * 64
            batch["target_snapshot_artifact"] = dict(batch["job_spec_artifact"])
        elif mutation == "base_version":
            batch["base_version_id"] = "sha256:" + "0" * 64
            value["parent_policy"] = "explicit_registered_parents"
        elif mutation == "foreign_run":
            batch["run_id"] = "run-absent"
        elif mutation == "root":
            value["source_campaign_binding"]["source_inventory"]["sha256"] = "0" * 64
        elif mutation == "variant":
            value["variant_manifest_sha256"] = "0" * 64
        else:
            value["artifact_root"] = str(tmp_path / "foreign-artifacts")
        _reidentify(batch)
        artifact = _stage_plan(registry, tmp_path, value)
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        with pytest.raises(ERRORS):
            plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        _assert_untouched(registry, specs, saved)


@pytest.mark.parametrize("mutation", ["extra", "null", "admitted", "formalized", "source_authority", "holdout",
    "batch_extra", "bool_ordinal", "stale_batch_id", "reorder", "duplicate_run", "duplicate_training", "empty",
    "too_many", "too_many_training", "too_many_roles", "bad_parent_policy", "null_ref", "coverage"])
def test_closed_codec_rejects_invalid_shape_order_and_authority_claims(tmp_path, mutation):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _pair(registry, tmp_path)
        value = plans.build_campaign_plan(registry, [spec.run_id for spec in specs])
        if mutation == "extra":
            value["extension"] = None
        elif mutation == "null":
            value["batches"] = None
        elif mutation in {"admitted", "formalized"}:
            value[mutation] = True
        elif mutation == "source_authority":
            value["source_authority_authenticated"] = True
        elif mutation == "holdout":
            value["global_holdout_verified"] = True
        elif mutation == "batch_extra":
            value["batches"][0]["extension"] = None
        elif mutation == "bool_ordinal":
            value["batches"][0]["ordinal"] = False
        elif mutation == "stale_batch_id":
            value["batches"][0]["job_id"] = "changed-job"
        elif mutation == "reorder":
            value["batches"].reverse()
        elif mutation == "duplicate_run":
            value["batches"][1]["run_id"] = value["batches"][0]["run_id"]
            _reidentify(value["batches"][1])
        elif mutation == "duplicate_training":
            value["batches"][1]["training_record_ids"] = value["batches"][0]["training_record_ids"][:]
            _reidentify(value["batches"][1])
        elif mutation == "empty":
            value["batches"] = []
        elif mutation == "too_many":
            value["batches"] *= 65
        elif mutation in {"too_many_training", "too_many_roles"}:
            role = "training_record_ids" if mutation == "too_many_training" else "validation_record_ids"
            count = 129 if mutation == "too_many_training" else 256
            value["batches"][0][role] = [f"sha256:{number:064x}" for number in range(count)]
            _reidentify(value["batches"][0])
        elif mutation == "bad_parent_policy":
            value["parent_policy"] = "latest_head"
        elif mutation == "null_ref":
            value["source_campaign_binding"]["source_inventory"] = None
        else:
            value["coverage"]["planned_training_record_count"] += 1
        with pytest.raises(ERRORS):
            plans.encode_campaign_plan(value)
        with pytest.raises(ERRORS):
            plans.decode_campaign_plan(_canonical(value))


def test_decoder_rejects_duplicate_keys_noncanonical_bytes_and_byte_limit(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _pair(registry, tmp_path)
        raw = plans.encode_campaign_plan(plans.build_campaign_plan(registry, [spec.run_id for spec in specs]))
        duplicate = b'{"schema_version":"autoencoder-campaign-plan-v1",' + raw[1:]
        for invalid in (duplicate, b" " + raw, raw + b"\n", b" " * (4 * 1024**2 + 1)):
            with pytest.raises(ERRORS):
                plans.decode_campaign_plan(invalid)


@pytest.mark.parametrize("selection", ["empty", "duplicate", "absent"])
def test_builder_rejects_invalid_registered_run_selection(tmp_path, selection):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = specs = _pair(registry, tmp_path)
        run_ids = [] if selection == "empty" else [first.run_id, first.run_id] if selection == "duplicate" else [first.run_id, "absent-run"]
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        with pytest.raises(ERRORS):
            plans.build_campaign_plan(registry, run_ids)
        _assert_untouched(registry, specs, saved)


@pytest.mark.parametrize("schema", ["v4", "v6", "v7"])
def test_legacy_and_mapped_input_jobs_cannot_enter_campaign_plan(tmp_path, schema):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        updates, variant = {}, {}
        if schema != "v4":
            updates, index, _ = _indexed_corpus_inputs(registry, tmp_path, production=True, arrow_inputs=schema == "v7")
            variant = {"corpus_index_binding": index, "embedding_production_binding": {
                "artifact": {key: updates["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}}
        spec = _prepare(registry, tmp_path, job_updates=updates, variant_updates=variant)
        saved = registry.get_run(spec.run_id)
        with pytest.raises(ERRORS):
            plans.build_campaign_plan(registry, [spec.run_id])
        assert registry.get_run(spec.run_id) == saved
        assert not Path(spec.output_directory).exists()


def test_common_source_roots_do_not_allow_mixing_registered_variants(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = _pair(registry, tmp_path)
        binding = registry.get_variant("english-0")["manifest"]["source_campaign_binding"]
        payload = second.to_dict()
        for field in ("base_version_id", "base_checkpoint", "job_id", "run_id", "output_directory"):
            payload.pop(field)
        foreign = _prepare(registry, tmp_path, index=1, job_updates=payload,
            variant_updates={"source_campaign_binding": binding})
        with pytest.raises(ERRORS):
            plans.build_campaign_plan(registry, [first.run_id, foreign.run_id])
        assert all(registry.get_run(spec.run_id)["attempt"] == 0 for spec in (first, second, foreign))


def test_validation_reuse_is_counted_without_duplicating_training_members(tmp_path):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import _manifest
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, fixture = _campaign_inputs(registry, tmp_path)
        first = _prepare(registry, tmp_path, job_updates=inputs,
            variant_updates={"source_campaign_binding": binding})
        training = fixture.case.partitions.entry_cids_for("train")[2:4]
        validation = fixture.case.partitions.entry_cids_for("validation")[:2]
        fixture.manifest, fixture.entry_cids = _manifest(fixture.records_by_entry, training, validation)
        reused, _, _ = _campaign_inputs(registry, tmp_path, fixture=fixture)
        second = _register(registry, tmp_path, {**first.to_dict(), **reused}, "reuse-validation")
        value = plans.build_campaign_plan(registry, [first.run_id, second.run_id])
        assert value["batches"][0]["validation_record_ids"] == value["batches"][1]["validation_record_ids"]
        assert value["coverage"]["planned_training_record_count"] == 4
        assert value["coverage"]["planned_validation_record_count"] == 2
        assert value["coverage"]["planned_validation_occurrences"] == 4


@pytest.mark.parametrize("overrides", [{"max_new_batches": 0}, {"max_new_batches": 129},
    {"max_new_batches": True}, {"max_workers": 0}, {"max_workers": 33}, {"max_workers": True}])
def test_dispatch_limits_fail_before_any_artifact_or_registry_work(monkeypatch, overrides):
    monkeypatch.setattr(plans, "_inspect", _forbidden)
    with pytest.raises(ERRORS):
        plans.run_campaign_plan(None, {}, executor_factory=_forbidden, worker_function=_forbidden, **overrides)


@pytest.mark.parametrize("operation", ["build", "inspect", "run"])
def test_plan_helper_source_drift_aborts_before_dispatch(tmp_path, monkeypatch, operation):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        before = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        hashes = iter(("a" * 64, "b" * 64))
        monkeypatch.setattr(plans, "_source_hash", lambda: next(hashes))
        with pytest.raises(ERRORS, match="helper changed"):
            if operation == "build":
                plans.build_campaign_plan(registry, [spec.run_id for spec in specs])
            elif operation == "inspect":
                plans.inspect_campaign_plan(registry, artifact)
            else:
                plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        _assert_untouched(registry, specs, before)


def test_shared_target_arrow_bindings_survive_plan_and_restart(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    captured = {}
    with AutoencoderRegistry(database, artifacts) as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True, artifact_format="bundle")
        first, second = combined.specs
        value = plans.build_campaign_plan(registry, [first.run_id, second.run_id])
        for batch, spec in zip(value["batches"], combined.specs, strict=True):
            assert batch["target_snapshot_id"] == spec.target_snapshot_id
            for name in ("target_snapshot_artifact", "arrow_feature_weights_artifact"):
                ref = getattr(spec, name)
                assert batch[name] == {"sha256": ref.sha256, "bytes": ref.bytes}
        artifact = plans.seal_campaign_plan(registry, [first.run_id, second.run_id])
        report = plans.run_campaign_plan(registry, artifact, executor_factory=ImmediateExecutor,
            worker_function=_injected_worker(combined, captured, arrow=True))
        assert report["status"] == "complete", report.get("dispatch")
        assert report["dispatch"]["execution_mode"] == "injected_test"
        for row in report["batches"]:
            version = registry.get_version(row["candidate_version_id"])
            resolved = resolve_checkpoint(version["artifact"], resolver=registry.artifact_path)
            assert (resolved.state.to_json() + "\n").encode() == captured[row["run_id"]]["raw"]
        _assert_flags(report)
    with AutoencoderRegistry(database, artifacts) as registry:
        result = plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert result["status"] == "complete" and result["dispatch"] is None
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
    assert all(Path(path).read_bytes() == raw for path, raw in combined.shared_files.items())


@pytest.mark.parametrize("storage,capture", [("full", False), ("full", True), ("sparse", True)])
def test_completed_full_and_compacted_candidates_reconcile_without_dispatch(tmp_path, storage, capture):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    captured = {}
    with AutoencoderRegistry(database, artifacts) as registry:
        first, second = _pair(registry, tmp_path,
            job_updates={"candidate_storage": storage, "capture_sparse_patches": capture})
        artifact = plans.seal_campaign_plan(registry, [first.run_id])
        done = _complete(registry, first, captured=captured, policy=coordinator.SparseCheckpointPolicy(max_depth=1))
        assert done["result"]["checkpoint_storage"] == "full_json"
        assert done["result"]["sparse_replay_verified"] is capture
        if storage == "sparse":
            assert done["result"]["sparse_compaction_performed"] is True
            assert "max_depth" in done["result"]["sparse_compaction_reasons"]
            assert done["candidate"] != done["result"]["worker_candidate_artifact"]
        receipt = json.loads(registry.artifact_path(done["worker_receipt_artifact"]).read_bytes())
        assert len(receipt["sparse_patch_segments"]) == (1 if capture else 0)
        assert receipt["optimizer_accepted_epochs"] == 1
    with AutoencoderRegistry(database, artifacts) as registry:
        report = plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert report["status"] == "complete" and report["dispatch"] is None
        assert report["batches"][0]["candidate_version_id"] == done["version_id"]
        candidate = registry.get_version(done["version_id"])["artifact"]
        resolved = resolve_checkpoint(candidate, resolver=registry.artifact_path)
        assert (resolved.state.to_json() + "\n").encode() == captured[first.run_id]
        assert registry.get_run(second.run_id)["status"] == "queued"
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
        _assert_flags(report)


@pytest.mark.parametrize("forgery", ["run_id", "base_version_id", "bridge_names", "prover", "sample_count",
    "capture_flag", "legacy_field", "patch_context", "manifest_parent", "compaction_summary", "lease_assignment"])
def test_low_level_complete_cannot_turn_forged_receipt_or_storage_into_plan_completion(tmp_path, forgery):
    """The low-level DB API records declarations; the plan must reverify them.

    Only this adversarial fixture bypasses normal coordinator acceptance, after
    first producing and staging a valid injected result through the real path.
    All forged receipt bytes have valid CAS hashes and matching result summaries.
    """
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first, second = specs = _pair(registry, tmp_path)
        artifact = plans.seal_campaign_plan(registry, [spec.run_id for spec in specs])
        lease = registry.claim_run("adversarial-claim", first.run_id, "injected-adversarial-owner", 300)["lease"]
        receipt = _updater([], {})(first)
        checked = coordinator.registered_corpus_job_inputs(registry, first.run_id)
        candidate, receipt_ref, summary = coordinator._prepare_completion(registry, first, receipt,
            native=False, corpus_verification=checked["corpus_verification"],
            sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy())
        assert summary["sparse_compaction_performed"] is False
        summary["sparse_acceptance_assignment"] = {
            key: lease[key] for key in ("run_id", "attempt", "owner_generation", "fence", "worker_id")}
        if forgery in {"run_id", "base_version_id"}:
            receipt[forgery] = "foreign-identity"
        elif forgery == "bridge_names":
            receipt["bridge_names"] = []
        elif forgery == "prover":
            receipt["legal_ir_evaluate_provers"] = True
        elif forgery == "sample_count":
            receipt["sample_count"] += 1
        elif forgery == "capture_flag":
            receipt["capture_sparse_patches"] = False
        elif forgery == "legacy_field":
            receipt["embedding_production_artifact"] = None
        elif forgery == "patch_context":
            receipt["sparse_patch_segments"][0]["capture_context"]["base_revision"] += 1
        elif forgery == "manifest_parent":
            # Semantically equal source state with different physical bytes is
            # a valid checkpoint, but is not this job's authorized parent.
            alternate = tmp_path / "alternate-parent.json"
            alternate.write_text(json.dumps(json.loads(Path(first.base_checkpoint.path).read_bytes()), indent=2) + "\n")
            alternate_ref = registry.stage_artifact(alternate)
            assert alternate_ref["sha256"] != first.base_checkpoint.sha256
            manifest = json.loads(registry.artifact_path(candidate).read_bytes())
            manifest["parent"] = alternate_ref
            forged_manifest = tmp_path / "forged-parent-manifest.json"
            forged_manifest.write_bytes(_canonical(manifest))
            candidate = registry.stage_artifact(forged_manifest)
            receipt["candidate"] = {**candidate, "path": receipt["candidate"]["path"]}
            summary["worker_candidate_artifact"] = candidate
            summary["checkpoint_anchor"] = alternate_ref
            summary["checkpoint_dependencies"] = sorted([
                alternate_ref if ref["sha256"] == first.base_checkpoint.sha256 else ref
                for ref in summary["checkpoint_dependencies"]], key=lambda ref: ref["sha256"])
            alternate_candidate = resolve_checkpoint(candidate, resolver=registry.artifact_path)
            assert alternate_candidate.state.state_identity() == receipt["candidate_state_identity"]["digest"]
            assert dict(alternate_candidate.materialized_checkpoint) == receipt["candidate_materialized_checkpoint"]
        elif forgery == "compaction_summary":
            summary["sparse_compaction_performed"] = True
            summary["sparse_compaction_reasons"] = ["max_depth"]
        else:
            summary["sparse_acceptance_assignment"]["worker_id"] = "different-lease-worker"
        forged_receipt = tmp_path / "forged-cas-receipt.json"
        forged_receipt.write_bytes(_canonical(receipt))
        receipt_ref = registry.stage_artifact(forged_receipt)
        # Match all ordinary derived receipt fields so rejection depends on
        # the authoritative job, replay, ancestry and lease checks.
        summary.update(coordinator._result_summary(receipt, receipt_ref, native=False))
        committed = registry.complete_run("adversarial-complete", lease, candidate, summary)
        assert committed["status"] == "completed"
        assert registry.get_run_completion(first.run_id)["candidate_version"]["artifact"] == candidate
        saved = {spec.run_id: registry.get_run(spec.run_id) for spec in specs}
        rejection = {"run_id": "run_id", "base_version_id": "base_version_id", "bridge_names": "bridge_names",
            "prover": "legal_ir_evaluate_provers", "sample_count": "sample_count", "capture_flag": "capture_sparse_patches",
            "legacy_field": "legacy", "patch_context": "capture context", "manifest_parent": "ancestry",
            "compaction_summary": "storage/replay summary", "lease_assignment": "lease assignment"}
        with pytest.raises(ERRORS, match=rejection[forgery]):
            plans.run_campaign_plan(registry, artifact, executor_factory=_forbidden, worker_function=_forbidden)
        assert {spec.run_id: registry.get_run(spec.run_id) for spec in specs} == saved
        assert not Path(second.output_directory).exists()
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
