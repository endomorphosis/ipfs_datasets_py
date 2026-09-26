"""V6/v8 cycle assembly with synthetic vectors and no training or queue calls."""
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_worker import _campaign_job, _artifact
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _indexed_corpus_job


def _spec(path, schema="v8"):
    path.mkdir(parents=True, exist_ok=True)
    if schema == "v8":
        payload, _, _ = _campaign_job(path)
    else:
        payload, _, _ = _indexed_corpus_job(path, production=True, arrow_inputs=schema == "v7")
    return worker.TrainingJobSpec.from_dict(payload)


def _forbidden(*args, **kwargs):
    pytest.fail("unexpected native execution, queue access or pre-verification side effect")


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_exact_default_training_order_and_explicit_subset_exclude_validation(tmp_path, schema):
    spec = _spec(tmp_path, schema)
    verified = worker.verify_corpus_job_inputs(spec)
    default = inputs.verify_cycle_inputs(spec)
    expected = verified["training_record_ids"]
    assert default.verification == verified
    assert [record.record_id for record in default.training_records] == expected
    assert [asdict(record.sample) for record in default.training_records] == [asdict(row) for row in spec.samples]
    chosen = list(reversed(expected))[:1]
    subset = inputs.verify_cycle_inputs(spec, record_ids=chosen)
    assert [record.record_id for record in subset.training_records] == chosen
    assert not set(chosen).intersection(verified["validation_record_ids"])
    for selection in (verified["validation_record_ids"], ["sha256:" + "0" * 64], [], expected * 2):
        with pytest.raises(ValueError, match="training members"):
            inputs.verify_cycle_inputs(spec, record_ids=selection)


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_feedback_bound_fails_before_source_work_or_training(tmp_path, monkeypatch, schema):
    spec = _spec(tmp_path, schema)
    too_many = replace(spec, samples=tuple(spec.samples[:1]) * 129)
    monkeypatch.setattr(inputs, "verify_corpus_job_inputs", _forbidden)
    with pytest.raises(ValueError, match="128"):
        inputs.verify_cycle_inputs(too_many)
    with pytest.raises(ValueError, match="128"):
        inputs.verify_cycle_inputs(spec, record_ids=(str(number) for number in range(129)))


def test_v7_mapped_transport_is_rejected_before_verification(tmp_path, monkeypatch):
    spec = _spec(tmp_path, "v7")
    monkeypatch.setattr(inputs, "verify_corpus_job_inputs", _forbidden)
    with pytest.raises(ValueError, match="v6 or v8 inline"):
        inputs.verify_cycle_inputs(spec)
    with pytest.raises(ValueError, match="v6 or v8 inline"):
        inputs.stage_cycle_job_inputs(SimpleNamespace(stage_artifact=_forbidden), spec)


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_staging_preserves_all_declared_bytes_options_and_correct_variant(tmp_path, schema):
    spec = _spec(tmp_path / "input", schema)
    refs = [_artifact(tmp_path / f"optional-{number}", f"opaque-staging-fixture-{number}".encode()) for number in range(3)]
    spec = replace(spec, target_snapshot_id="fixture-target", target_snapshot_artifact=worker.CheckpointArtifact.from_dict(refs[0]),
        arrow_feature_weights_artifact=worker.CheckpointArtifact.from_dict(refs[1]),
        base_checkpoint_dependencies=(worker.CheckpointArtifact.from_dict(refs[2]),),
        capture_sparse_patches=True, candidate_storage="sparse")
    original = spec.to_dict()
    # These optional artifacts exercise byte staging only, not their codecs.
    inputs.verify_cycle_inputs(spec)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        payload, variant = inputs.stage_cycle_job_inputs(registry, spec)
        restored = worker.TrainingJobSpec.from_dict(payload)
        assert restored.training_config == spec.training_config
        assert restored.capture_sparse_patches and restored.candidate_storage == "sparse"
        assert restored.target_snapshot_id == "fixture-target"
        fields = ("base_checkpoint", "corpus_manifest_artifact", "target_snapshot_artifact", "arrow_feature_weights_artifact")
        fields += (worker.CAMPAIGN_ARTIFACT_FIELDS if schema == "v8" else ("corpus_index_artifact", "embedding_production_artifact"))
        arrays = ("base_checkpoint_dependencies", "corpus_source_artifacts") + (("embedding_receipt_artifacts",) if schema == "v8" else ())
        for before, after in [(original[name], payload[name]) for name in fields] + [
                pair for name in arrays for pair in zip(original[name], payload[name], strict=True)]:
            assert {key: before[key] for key in ("sha256", "bytes")} == {key: after[key] for key in ("sha256", "bytes")}
            assert Path(after["path"]) == registry.artifact_path({key: after[key] for key in ("sha256", "bytes")})
            assert Path(before["path"]).read_bytes() == Path(after["path"]).read_bytes()
        if schema == "v8":
            assert set(variant) == set(payload["variant"]) | {"source_campaign_binding"}
            assert variant["source_campaign_binding"] == {name: {key: payload[name + "_artifact"][key]
                for key in ("sha256", "bytes")} for name in ("source_inventory", "source_partitions", "embedding_receipt_set")}
            assert not {"corpus_index_binding", "embedding_production_binding"}.intersection(variant)
        else:
            assert set(variant) == set(payload["variant"]) | {"corpus_index_binding", "embedding_production_binding"}
    assert spec.to_dict() == original


def test_staging_rejects_declared_size_mismatch_and_confers_no_verification(tmp_path):
    spec = _spec(tmp_path / "input")
    changed = replace(spec, base_checkpoint=replace(spec.base_checkpoint, bytes=spec.base_checkpoint.bytes + 1))
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(ValueError, match="declared byte identity"):
            inputs.stage_cycle_job_inputs(registry, changed)


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("autoformal_campaign_cycle_under_test", scripts / "run_autoformal_training_cycle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "pin_accelerate", lambda path: {})
    monkeypatch.setattr(module, "code_identity", lambda: "fixture-compiler-code")
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source",
                        SimpleNamespace(DatabaseTaskSource=_forbidden))
    return module


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_cycle_reaches_dispatch_with_owner_staged_contract_without_executing_it(tmp_path, monkeypatch, runner, schema):
    spec = _spec(tmp_path / "input", schema)
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    seen = []

    class StopBeforeTraining(Exception):
        pass

    def stop(registry, specs, **kwargs):
        seen.extend(specs)
        assert registry.get_run(specs[0].run_id)["status"] == "queued"
        assert worker.verify_corpus_job_inputs(specs[0])["training_record_ids"] == inputs.verify_cycle_inputs(spec).verification["training_record_ids"]
        raise StopBeforeTraining

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", stop)
    with pytest.raises(StopBeforeTraining):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "never-opened-queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert len(seen) == 1 and seen[0].schema_version == spec.schema_version
    assert not Path(seen[0].output_directory).exists()
    assert not (tmp_path / "never-opened-queue.duckdb").exists()


@pytest.mark.parametrize("problem", ["validation_changed", "too_many_feedback_records", "mapped_transport"])
def test_cycle_invalid_inputs_fail_before_registry_or_training(tmp_path, monkeypatch, runner, problem):
    spec = _spec(tmp_path / "input", "v7" if problem == "mapped_transport" else "v8")
    if problem == "validation_changed":
        spec = replace(spec, validation_samples=(replace(spec.validation_samples[0], text="changed held-out text"), *spec.validation_samples[1:]))
    elif problem == "too_many_feedback_records":
        spec = replace(spec, samples=spec.samples[:1] * 129)
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    from ipfs_datasets_py.duckdb_control import autoencoder_registry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    monkeypatch.setattr(autoencoder_registry, "AutoencoderRegistry", _forbidden)
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", _forbidden)
    monkeypatch.setattr(inputs, "stage_cycle_job_inputs", _forbidden)
    with pytest.raises(ValueError):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert not (tmp_path / "runtime").exists()


def test_new_runtime_helper_and_contract_tests_are_protected(runner):
    from run_autoformal_supervisor import PROTECTED
    assert {"ipfs_datasets_py/logic/autoformal/training_cycle_inputs.py",
            "tests/unit/logic/test_autoformal_campaign_training_inputs.py",
            "tests/unit/logic/test_autoformal_campaign_learned_feedback.py"}.issubset(PROTECTED)


@pytest.mark.parametrize("problem", ["helper_before_dispatch", "compiler_after_selection", "helper_after_selection", "compiler_during_census"])
def test_cycle_source_guards_stop_dispatch_or_repair_mutation(tmp_path, monkeypatch, runner, problem):
    """Injected control-flow receipts are never native execution evidence."""
    spec = _spec(tmp_path / "input")
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec.to_dict()))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator
    from ipfs_datasets_py.logic.autoformal import learned_feedback, autoencoder_router, supervisor_queue
    stages, dispatches, queue_opens = [], [], []
    stage = inputs.stage_cycle_job_inputs
    verify = inputs.verify_cycle_inputs

    def staging(*args, **kwargs):
        result = stage(*args, **kwargs)
        stages.append(True)
        if problem == "helper_before_dispatch":
            monkeypatch.setattr(inputs, "__file__", learned_feedback.__file__)
        return result

    verification_calls = []

    def verifying(*args, **kwargs):
        result = verify(*args, **kwargs)
        verification_calls.append(True)
        if len(verification_calls) == 2:
            if problem == "compiler_after_selection":
                monkeypatch.setattr(runner, "code_identity", lambda: "changed-compiler")
            elif problem == "helper_after_selection":
                monkeypatch.setattr(inputs, "__file__", learned_feedback.__file__)
        return result

    def injected_dispatch(registry, specs, **kwargs):
        assert problem != "helper_before_dispatch", "changed helper reached dispatch"
        current = specs[0]
        dispatches.append(current)
        output = Path(current.output_directory)
        output.mkdir()
        (output / "receipt.json").write_text(json.dumps({"execution_mode": "native_training", "promotion_performed": False,
            "optimizer_accepted_epochs": 0, "training_report": {}}))
        return {"failed": [], "completed": [{"candidate": {"sha256": current.base_checkpoint.sha256,
            "bytes": current.base_checkpoint.bytes}, "version_id": "synthetic-no-training-version"}]}

    class FakeSource:
        def __init__(self, *args, **kwargs):
            queue_opens.append(True)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def census(samples, inference):
        assert problem == "compiler_during_census"
        monkeypatch.setattr(runner, "code_identity", lambda: "changed-compiler")
        return {"rows": samples}

    monkeypatch.setattr(inputs, "stage_cycle_job_inputs", staging)
    monkeypatch.setattr(inputs, "verify_cycle_inputs", verifying)
    monkeypatch.setattr(autoencoder_training_coordinator, "run_training_jobs", injected_dispatch)
    monkeypatch.setattr(learned_feedback, "observe_checkpoint", lambda *args, **kwargs: {"observation_count": 0})
    monkeypatch.setattr(learned_feedback, "attach_guidance", lambda agreement, *args: agreement)
    monkeypatch.setattr(autoencoder_router, "agreement_census", census)
    monkeypatch.setattr(supervisor_queue, "repair_packets", _forbidden)
    monkeypatch.setattr(supervisor_queue, "enqueue_repairs", _forbidden)
    monkeypatch.setitem(sys.modules, "ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source",
                        SimpleNamespace(DatabaseTaskSource=FakeSource))
    with pytest.raises(RuntimeError, match="helper changed|compiler changed"):
        runner.main(["--accelerate-root", str(tmp_path), "--job-template", str(job),
            "--database", str(tmp_path / "never-opened-queue.duckdb"), "--runtime-root", str(tmp_path / "runtime")])
    assert stages == [True]
    assert len(dispatches) == (0 if problem == "helper_before_dispatch" else 1)
    assert len(queue_opens) == (1 if problem == "compiler_during_census" else 0)
    assert not (tmp_path / "never-opened-queue.duckdb").exists()
