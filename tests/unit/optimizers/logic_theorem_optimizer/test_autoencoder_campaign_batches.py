"""Deterministic v8 generation from sealed synthetic campaign declarations.

The real source, receipt, projection, registry and plan codecs are exercised.
Injected vectors and optional injected worker updates establish transport only;
no embedding model, model evaluator, optimizer, publication or Lean admit runs.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_batches as batches
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_plan as plans
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as production
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as corpus_index
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import _campaign_inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _forbid_native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_plan import _updater, _register
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_embedding_receipt_set import _case
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import (
    ProjectionCase, _manifest, _prepared,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import ImmediateExecutor, _prepare
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_inventory import _row


ERRORS = (batches.CampaignBatchError, plans.CampaignPlanError, RegistryError,
          coordinator.TrainingCoordinationError, ValueError)


@pytest.fixture(autouse=True)
def no_native_model(monkeypatch):
    _forbid_native(monkeypatch)


def _forbidden(*args, **kwargs):
    pytest.fail("unexpected selected read, registration or native execution")


def _selected(fixture, role):
    by_input = {}
    for entry in fixture.case.partitions.entry_cids_for(role, require_nonempty=False):
        binding = fixture.receipt_set.binding_for(entry)
        if binding["status"] == "embedded":
            old = by_input.get(binding["input_id"])
            by_input[binding["input_id"]] = entry if old is None else min(old, entry)
    return tuple((input_id, by_input[input_id]) for input_id in sorted(by_input))


def _from_case(case):
    receipt_set = case.build()
    by_input = {}
    for leaf in case.leaves:
        for record in leaf.to_corpus_records(resolver=case.source_resolver):
            by_input[production.EmbeddingInput.from_source_record(record).input_id] = record
    records = {row["entry_cid"]: by_input[item.input_id]
               for row, (item, _) in zip(case.rows, case.entries, strict=True) if item.input_id in by_input}
    provisional = ProjectionCase(case, receipt_set, records, None, ())
    training = [entry for _, entry in _selected(provisional, "train")[:2]]
    validation = [entry for _, entry in _selected(provisional, "validation")[:2]]
    assert training and validation
    manifest, entries = _manifest(records, training, validation)
    return ProjectionCase(case, receipt_set, records, manifest, entries)


def _template(registry, root, *, fixture=None, updates=None):
    root.mkdir(parents=True, exist_ok=True)
    fixture = fixture or _prepared(root)
    inputs, binding, _ = _campaign_inputs(registry, root, fixture=fixture)
    state = modal.ModalAutoencoderTrainingState(feature_embedding_weights={
        "padding": [number / 1000 for number in range(2000)]})
    (root / "base.json").write_text(state.to_json() + "\n")
    spec = _prepare(registry, root, job_updates={**inputs, "capture_sparse_patches": True,
        "candidate_storage": "sparse", **(updates or {})},
        variant_updates={"source_campaign_binding": binding})
    return spec, fixture


def _generate(registry, spec, fixture, root, **kwargs):
    output_root = root / "generated"
    output_root.mkdir(exist_ok=True)
    return batches.prepare_campaign_batches(registry, spec.run_id,
        receipt_resolver=kwargs.pop("receipt_resolver", fixture.case.receipt_resolver),
        source_resolver=kwargs.pop("source_resolver", fixture.case.source_resolver),
        output_root=output_root, training_batch_size=kwargs.pop("training_batch_size", 2),
        validation_batch_size=kwargs.pop("validation_batch_size", 2),
        max_batches=kwargs.pop("max_batches", 2), **kwargs)


def _verify_jobs(registry, report, template, fixture, *, training_batch_size=2, validation_batch_size=2):
    training = _selected(fixture, "train")
    validation = _selected(fixture, "validation")[:validation_batch_size]
    assert report["run_ids"] == [row["run_id"] for row in report["jobs"]]
    assert report["page"]["selected_batch_ordinals"] == [row["ordinal"] for row in report["jobs"]]
    for row in report["jobs"]:
        checked = coordinator.registered_corpus_job_inputs(registry, row["run_id"])
        spec, verification = checked["spec"], checked["corpus_verification"]
        ordinal = row["ordinal"]
        expected_training = training[ordinal * training_batch_size:(ordinal + 1) * training_batch_size]
        expected_ids = [fixture.records_by_entry[entry].record_id for _, entry in expected_training]
        expected_validation = [fixture.records_by_entry[entry].record_id for _, entry in validation]
        assert verification["training_record_ids"] == expected_ids
        assert verification["validation_record_ids"] == expected_validation
        assert spec.schema_version == "autoencoder-training-job-v8"
        assert spec.job_id == row["job_id"] and spec.canonical_sha256 == row["job_spec_sha256"]
        assert checked["job_spec_artifact"] == row["job_spec_artifact"]
        assert spec.training_config == template.training_config
        assert dict(spec.autoencoder_config) == dict(template.autoencoder_config)
        assert dict(spec.expected_source_sha256) == dict(template.expected_source_sha256)
        assert spec.base_version_id == template.base_version_id
        assert spec.base_checkpoint == template.base_checkpoint
        assert spec.base_checkpoint_dependencies == template.base_checkpoint_dependencies
        assert spec.target_snapshot_id == template.target_snapshot_id
        assert spec.target_snapshot_artifact == template.target_snapshot_artifact
        assert spec.arrow_feature_weights_artifact == template.arrow_feature_weights_artifact
        for name in ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact"):
            assert getattr(spec, name) == getattr(template, name)
        projection = json.loads(Path(spec.produced_record_projection_artifact.path).read_bytes())
        by_record = {binding["record_summary"]["record_id"]: binding for binding in projection["records"]}
        assert [by_record[key]["entry_cid"] for key in expected_ids] == [entry for _, entry in expected_training]
        assert [by_record[key]["entry_cid"] for key in expected_validation] == [entry for _, entry in validation]
        assert all(binding["status"] == "embedded" for binding in by_record.values())
    value = plans.decode_campaign_plan(registry.artifact_path(report["plan_artifact"]).read_bytes())
    assert [row["run_id"] for row in value["batches"]] == report["run_ids"]
    assert value["source_campaign_binding"] == registry.get_variant("english-0")["manifest"]["source_campaign_binding"]
    for flag in ("admitted", "formalized", "source_authority_authenticated", "global_holdout_verified",
                 "training_dispatched", "promotion_performed", "publication_performed", "target_membership_verified"):
        assert report[flag] is False


def test_overlapping_pages_share_exact_jobs_and_reopen_does_not_reset_completed_runs(tmp_path):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        first = _generate(registry, template, fixture, tmp_path)
        repeated = _generate(registry, template, fixture, tmp_path)
        assert repeated == first
        _verify_jobs(registry, first, template, fixture)
        overlapping = _generate(registry, template, fixture, tmp_path, start_batch=1)
        assert overlapping["recipe_id"] == first["recipe_id"]
        assert overlapping["jobs"][0] == first["jobs"][1]
        assert overlapping["plan_artifact"] != first["plan_artifact"]
        calls, captured = [], {}
        trained = plans.run_campaign_plan(registry, first["plan_artifact"], max_new_batches=1,
            executor_factory=ImmediateExecutor, worker_function=_updater(calls, captured))
        assert calls == first["run_ids"][:1]
        assert trained["dispatch"]["execution_mode"] == "injected_test"
        saved = {run_id: registry.get_run(run_id) for run_id in first["run_ids"]}
    with AutoencoderRegistry(database, artifacts) as registry:
        reopened = _generate(registry, template, fixture, tmp_path)
        assert reopened == first
        assert {run_id: registry.get_run(run_id) for run_id in first["run_ids"]} == saved
        resumed = plans.run_campaign_plan(registry, reopened["plan_artifact"], executor_factory=ImmediateExecutor,
            worker_function=_updater(calls, captured))
        assert resumed["status"] == "complete" and calls == first["run_ids"]
        assert registry.get_run(template.run_id)["attempt"] == 0
        assert registry.resolve_head("english-0", "best")["version_id"] == template.base_version_id


def test_short_last_batch_is_not_padded_or_resampled(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        count = len(_selected(fixture, "train"))
        assert 2 < count <= 128
        report = _generate(registry, template, fixture, tmp_path, training_batch_size=count - 1,
            validation_batch_size=1)
        assert report["page"]["total_batches"] == 2
        assert len(report["jobs"]) == 2
        _verify_jobs(registry, report, template, fixture, training_batch_size=count - 1, validation_batch_size=1)
        last = coordinator.registered_corpus_job_inputs(registry, report["run_ids"][-1])["spec"]
        assert len(last.samples) == 1


def test_shared_leaf_does_not_require_unselected_source_files(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        fixture = _prepared(tmp_path / "inputs", groups=[list(range(32))])
        template, fixture = _template(registry, tmp_path / "inputs", fixture=fixture)
        entries = [entry for _, entry in (*_selected(fixture, "train")[:2], *_selected(fixture, "validation")[:2])]
        # The template was already independently verified. Preserve its CAS
        # files while removing every unselected external source from this leaf.
        allowed = {fixture.records_by_entry[entry].source.artifact.sha256 for entry in entries}
        for digest, path in fixture.case.source_paths.items():
            if digest not in allowed:
                path.unlink()
        reads = []
        def resolve(ref):
            assert ref["sha256"] in allowed, "generation expanded selected source authority"
            reads.append(ref["sha256"])
            return fixture.case.source_resolver(ref)
        report = _generate(registry, template, fixture, tmp_path, max_batches=1, source_resolver=resolve)
        assert set(reads) == allowed
        _verify_jobs(registry, report, template, fixture)
        spec = coordinator.registered_corpus_job_inputs(registry, report["run_ids"][0])["spec"]
        assert len(spec.embedding_receipt_artifacts) == 1
        assert len(spec.corpus_source_artifacts) == 4


@pytest.mark.parametrize("point", ["after_first_commit", "before_second_commit"])
def test_partial_registration_retry_reuses_stable_create_run_identities(tmp_path, monkeypatch, point):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        original = registry.create_run
        invocations = []
        interrupted = [False]
        def interrupted_create(operation_id, run_id, *args, **kwargs):
            invocations.append((operation_id, run_id))
            if point == "before_second_commit" and len(invocations) == 2 and not interrupted[0]:
                interrupted[0] = True
                raise OSError("fixture interruption before next registration")
            result = original(operation_id, run_id, *args, **kwargs)
            if point == "after_first_commit" and not interrupted[0]:
                interrupted[0] = True
                raise OSError("fixture lost CreateRun response after commit")
            return result
        monkeypatch.setattr(registry, "create_run", interrupted_create)
        try:
            _generate(registry, template, fixture, tmp_path)
        except (OSError, batches.CampaignBatchError):
            pass
        assert interrupted[0]
        monkeypatch.setattr(registry, "create_run", original)
        report = _generate(registry, template, fixture, tmp_path)
        assert report["run_ids"][0] == invocations[0][1]
        if point == "before_second_commit":
            assert report["run_ids"][1] == invocations[1][1]
        assert _generate(registry, template, fixture, tmp_path) == report
        assert all(registry.get_run(run_id)["attempt"] == 0 for run_id in report["run_ids"])
        _verify_jobs(registry, report, template, fixture)


def test_mixed_dispositions_aliases_and_protected_splits_keep_original_denominators(tmp_path):
    rows = [_row(number) for number in range(1, 65)]
    rows[4] = {**rows[4], "admission_status": "excluded"}
    rows.append({**rows[0], "entry_cid": _row(99)["entry_cid"], "document_index": 99})
    policy = corpus_index.SplitPolicy("cross-codec-parity", train=2500, validation=2500, canary=2500, holdout=2500)
    case = _case(tmp_path / "inputs", rows=rows,
        groups=[[number] for number in range(64) if number not in {3, 4}],
        statuses={1: "missing_input", 2: "token_limit_exceeded"}, native=True, policy=policy)
    fixture = _from_case(case)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs", fixture=fixture)
        report = _generate(registry, template, fixture, tmp_path)
        _verify_jobs(registry, report, template, fixture)
        expected = fixture.receipt_set.summary()
        coverage = report["coverage"]
        assert coverage["physical_row_count"] == 65
        assert coverage["eligible_row_count"] == 64
        assert coverage["excluded_row_count"] == coverage["alias_row_count"] == 1
        assert coverage["eligible_unique_input_count"] == 63
        assert coverage["source_partition_counts"] == case.partitions.partition_counts
        assert coverage["unique_embedding_status_counts"] == expected["unique_status_counts"]
        assert coverage["unique_embedding_status_counts"] == {
            "embedded": 60, "missing_input": 1, "token_limit_exceeded": 1, "unattempted": 1}
        assert coverage["selected_training_input_count"] == 4
        assert coverage["selected_validation_input_count"] == 2
        assert coverage["deferred_training_input_count"] == len(_selected(fixture, "train")) - 4
        assert coverage["deferred_validation_input_count"] == len(_selected(fixture, "validation")) - 2
        assert coverage["protected_canary_input_count"] > 0 and coverage["protected_holdout_input_count"] > 0
        sealed = json.loads(registry.artifact_path(report["generation_artifact"]).read_bytes())
        dispositions = sealed["input_dispositions"]
        assert len(dispositions) == len({row["input_id"] for row in dispositions}) == 63
        alias = next(row for row in dispositions if len(row["entry_cids"]) == 2)
        assert alias["representative_entry_cid"] == min(alias["entry_cids"])
        for row in dispositions:
            if row["split"] in {"canary", "holdout"}:
                assert row["disposition"] == "protected_" + row["split"]
            elif row["embedding_status"] != "embedded":
                assert row["disposition"] == row["embedding_status"]
            if row["disposition"] == "planned_training":
                assert row["split"] == "train" and row["embedding_status"] == "embedded"
                assert row["batch_ordinal"] in report["page"]["selected_batch_ordinals"]


@pytest.mark.parametrize("kind", ["source", "leaf"])
def test_bad_final_page_member_rejected_before_first_registration(tmp_path, monkeypatch, kind):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        entry = _selected(fixture, "train")[3][1]
        record = fixture.records_by_entry[entry]
        target = (fixture.case.source_paths[record.source.artifact.sha256] if kind == "source"
                  else fixture.case.leaf_paths[record.embedding_provenance.artifact_sha256])
        target.write_bytes(b"corrupt final selected batch member")
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path)
        assert registry.get_run(template.run_id)["attempt"] == 0
        assert registry.resolve_head("english-0", "best")["version_id"] == template.base_version_id


def test_later_selected_read_cannot_hide_mutation_of_earlier_source(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        first_digest = []
        changed = [False]
        def drifting(ref):
            if not first_digest:
                first_digest.append(ref["sha256"])
            elif ref["sha256"] != first_digest[0] and not changed[0]:
                fixture.case.source_paths[first_digest[0]].write_bytes(b"changed after earlier selected verification")
                changed[0] = True
            return fixture.case.source_resolver(ref)
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path, source_resolver=drifting)
        assert changed[0], "fixture must exercise mutation during a later selected read"


@pytest.mark.parametrize("name", ["MAX_SELECTED_LEAF_BYTES", "MAX_SELECTED_SOURCE_BYTES",
                                  "MAX_TOTAL_JOB_BYTES", "MAX_GENERATION_BYTES"])
def test_generation_budgets_are_checked_before_registration(tmp_path, monkeypatch, name):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        monkeypatch.setattr(batches, name, 1)
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path)
        assert registry.get_run(template.run_id)["attempt"] == 0


@pytest.mark.parametrize("kwargs", [{"training_batch_size": 0}, {"training_batch_size": 129},
    {"training_batch_size": True}, {"validation_batch_size": 0}, {"validation_batch_size": 256},
    {"validation_batch_size": True}, {"start_batch": -1}, {"start_batch": True},
    {"max_batches": 0}, {"max_batches": 129}, {"max_batches": True},
    {"training_batch_size": 128, "validation_batch_size": 129}])
def test_invalid_batch_request_fails_before_resolver_or_registration(tmp_path, monkeypatch, kwargs):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path, receipt_resolver=_forbidden,
                source_resolver=_forbidden, **kwargs)


def test_start_beyond_last_batch_does_not_create_empty_plan(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        count = (len(_selected(fixture, "train")) + 1) // 2
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path, start_batch=count,
                receipt_resolver=_forbidden, source_resolver=_forbidden)


def test_optional_shared_artifacts_are_copied_without_claiming_target_membership(tmp_path):
    """Opaque target bytes test declaration transport only; Arrow is real IPC."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import build_feature_embedding_weights_ipc
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        target = tmp_path / "target-declaration.bin"
        target.write_bytes(b"opaque fixture target declaration; not a target codec qualification")
        target_ref = registry.stage_artifact(target)
        base_state = modal.ModalAutoencoderTrainingState.from_dict(json.loads(Path(template.base_checkpoint.path).read_bytes()))
        arrow = tmp_path / "template-features.arrow"
        build_feature_embedding_weights_ipc(base_state, arrow, base_checkpoint_sha256=template.base_checkpoint.sha256)
        arrow_ref = registry.stage_artifact(arrow)
        template = _register(registry, tmp_path, {**template.to_dict(),
            "target_snapshot_id": "sha256:" + target_ref["sha256"],
            "target_snapshot_artifact": {**target_ref, "path": str(registry.artifact_path(target_ref))},
            "arrow_feature_weights_artifact": {**arrow_ref, "path": str(registry.artifact_path(arrow_ref))}}, "optional-template")
        before = {str(path): path.read_bytes() for path in (registry.artifact_path(target_ref), registry.artifact_path(arrow_ref))}
        report = _generate(registry, template, fixture, tmp_path)
        _verify_jobs(registry, report, template, fixture)
        assert report["target_membership_qualification"] == "deferred_to_worker"
        assert all(Path(path).read_bytes() == raw for path, raw in before.items())


def test_conflicting_existing_last_run_prevents_first_new_registration(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        stage = batches._stage_bytes
        prepared_jobs = []
        class StopBeforeRegistration(RuntimeError):
            pass
        def capture(registry, raw, guard):
            value = json.loads(raw)
            if value.get("schema_version") == batches.SCHEMA_VERSION:
                prepared_jobs.extend(value["jobs"])
                raise StopBeforeRegistration
            return stage(registry, raw, guard)
        monkeypatch.setattr(batches, "_stage_bytes", capture)
        with pytest.raises(StopBeforeRegistration):
            _generate(registry, template, fixture, tmp_path)
        assert len(prepared_jobs) == 2
        monkeypatch.setattr(batches, "_stage_bytes", stage)
        last = prepared_jobs[-1]
        registry.create_run("conflicting-independent-registration", last["run_id"], "english-0", template.base_version_id,
            {"job_spec_sha256": "0" * 64, "job_spec_artifact": last["job_spec_artifact"]})
        saved = registry.get_run(last["run_id"])
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path)
        assert registry.get_run(last["run_id"]) == saved
        with pytest.raises(RegistryError, match="unknown run"):
            registry.get_run(prepared_jobs[0]["run_id"])
        assert registry.resolve_head("english-0", "best")["version_id"] == template.base_version_id


@pytest.mark.parametrize("status", ["running", "failed"])
def test_regeneration_preserves_unresolved_attempts_without_reclaim(tmp_path, status):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        report = _generate(registry, template, fixture, tmp_path)
        lease = registry.claim_run("existing-attempt", report["run_ids"][-1], "prior-worker", 300)["lease"]
        if status == "failed":
            registry.fail_run("existing-failure", lease, {"admitted": False, "error": "retained fixture failure"})
        before = {run_id: registry.get_run(run_id) for run_id in report["run_ids"]}
    with AutoencoderRegistry(database, artifacts) as registry:
        repeated = _generate(registry, template, fixture, tmp_path)
        assert repeated == report
        assert {run_id: registry.get_run(run_id) for run_id in report["run_ids"]} == before
        assert plans.inspect_campaign_plan(registry, repeated["plan_artifact"])["status"] == "unresolved"


def test_output_root_replaced_by_resolver_cannot_redirect_recipe_writes(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        output, moved, other = tmp_path / "generated", tmp_path / "moved-output", tmp_path / "other-output"
        output.mkdir()
        other.mkdir()
        changed = [False]
        def redirect(ref):
            if not changed[0]:
                output.rename(moved)
                output.symlink_to(other, target_is_directory=True)
                changed[0] = True
            return fixture.case.source_resolver(ref)
        monkeypatch.setattr(registry, "create_run", _forbidden)
        try:
            with pytest.raises(ERRORS):
                _generate(registry, template, fixture, tmp_path, source_resolver=redirect)
            assert changed[0]
            assert list(other.iterdir()) == [], "recipe writes escaped through changed output root"
        finally:
            if changed[0]:
                output.unlink()
                moved.rename(output)


def test_helper_source_drift_during_selected_read_fails_before_registration(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        before = hashlib.sha256(Path(batches.__file__).read_bytes()).hexdigest()
        changed = [False]
        monkeypatch.setattr(batches, "_source_hash", lambda: "0" * 64 if changed[0] else before)
        def drift(ref):
            changed[0] = True
            return fixture.case.receipt_resolver(ref)
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS, match="helper changed"):
            _generate(registry, template, fixture, tmp_path, receipt_resolver=drift)
        assert changed[0]
