"""Synthetic target/dispatch parity; no native training or timing qualification."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ontology_observation import observe_ontology_captures
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import RichLegalIRTarget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


class _Untouched:
    def __iter__(self):
        raise AssertionError("invalid options must precede job consumption")

    def __getattr__(self, name):
        raise AssertionError("invalid options must precede registry access")


def _spec(tmp_path):
    return worker.TrainingJobSpec.from_dict({
        "job_id": "reduction-dispatch-fixture", "run_id": "reduction-run",
        "base_version_id": "fixture-base",
        "base_checkpoint": {"path": str(tmp_path / "absent-base.json"), "bytes": 1, "sha256": "a" * 64},
        "output_directory": str(tmp_path / "absent-output"), "code_identity": "synthetic-unit-fixture",
        "dataset_snapshot_id": "fixture-data", "split_snapshot_id": "fixture-split",
        "samples": [{"title": "5", "section": "1", "text": "The agency shall retain records."}],
    })


@pytest.mark.parametrize("option", [None, 0, 1, 0.0, "true", [], {}])
def test_reduction_option_requires_boolean_before_job_or_registry_access(option):
    with pytest.raises(coordinator.TrainingCoordinationError, match="must be boolean"):
        coordinator.run_training_jobs(_Untouched(), _Untouched(), reduce_native_targets=option)


@pytest.mark.parametrize("injection", ["executor", "worker", "both"])
def test_reduction_optin_rejects_injected_owner_execution(injection):
    def forbidden(*args, **kwargs):
        raise AssertionError("injected execution must not run")

    kwargs = {"reduce_native_targets": True}
    if injection in {"executor", "both"}:
        kwargs["executor_factory"] = forbidden
    if injection in {"worker", "both"}:
        kwargs["worker_function"] = forbidden
    with pytest.raises(coordinator.TrainingCoordinationError, match="native spawned"):
        coordinator.run_training_jobs(_Untouched(), _Untouched(), **kwargs)


@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("reduced", [False, True])
def test_independent_gc_and_reduction_policies_choose_exact_spawn_entry(
    monkeypatch, tmp_path, deferred, reduced
):
    """Observe submission only; the fake pool never executes a worker."""
    spec = _spec(tmp_path)
    original_spec = spec.to_dict()
    submissions, failures, shutdowns = [], [], []

    class StoppedBeforeExecution(RuntimeError):
        pass

    class Pool:
        def __init__(self, *, max_workers, mp_context):
            assert max_workers == 1
            assert mp_context.get_start_method() == "spawn"

        def submit(self, function, submitted):
            submissions.append((function, submitted))
            raise StoppedBeforeExecution("synthetic dispatch observation only")

        def shutdown(self, **kwargs):
            shutdowns.append(kwargs)

    class Registry:
        def claim_run(self, operation_id, run_id, worker_id, lease_seconds):
            return {"lease": {"run_id": run_id, "expires_at": 300.0}}

        def get_run(self, run_id):
            return {"status": "running", "run_id": run_id}

        def fail_run(self, operation_id, lease, error):
            failures.append(error)
            return {"status": "failed"}

    monkeypatch.setattr(coordinator, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(coordinator, "_validate_runs", lambda registry, specs: {spec.run_id: {}})
    report = coordinator.run_training_jobs(
        Registry(), [spec], max_workers=1, clock=lambda: 0.0,
        defer_target_hydration_gc=deferred, reduce_native_targets=reduced,
    )
    entries = {
        (False, False): worker.execute_training_job,
        (True, False): worker._execute_native_training_job_with_deferred_gc,
        (False, True): worker._execute_native_training_job_with_reduced_targets,
        (True, True): worker._execute_native_training_job_with_deferred_gc_and_reduced_targets,
    }
    assert submissions == [(entries[deferred, reduced], spec)]
    assert report["reduce_native_targets"] is reduced
    assert report["defer_target_hydration_gc"] is deferred
    assert report["completed"] == []
    assert len(failures) == 1 and failures[0]["error_type"] == "StoppedBeforeExecution"
    assert shutdowns == [{"wait": True, "cancel_futures": True}]
    assert spec.to_dict() == original_spec
    assert "reduce_native_targets" not in original_spec
    assert not (tmp_path / "absent-output").exists()


def test_worker_entrypoints_keep_default_and_injected_path_unchanged(monkeypatch, tmp_path):
    calls = []
    sentinel = {"synthetic_dispatch_only": True}

    def execute(spec, **kwargs):
        calls.append((spec, kwargs))
        return sentinel

    monkeypatch.setattr(worker, "_execute_training_job", execute)
    spec = _spec(tmp_path)
    trainer = lambda *args, **kwargs: None
    assert worker.execute_training_job(spec, trainer=trainer, job_file_sha256="b" * 64) is sentinel
    assert calls[-1] == (spec, {"trainer": trainer, "job_file_sha256": "b" * 64})
    for entry, deferred in (
        (worker._execute_native_training_job_with_reduced_targets, False),
        (worker._execute_native_training_job_with_deferred_gc_and_reduced_targets, True),
    ):
        assert entry(spec) is sentinel
        submitted, kwargs = calls[-1]
        assert submitted is spec
        assert kwargs["trainer"] is None and kwargs["job_file_sha256"] is None
        assert kwargs["reduce_native_targets"] is True
        assert kwargs.get("defer_target_hydration_gc", False) is deferred


def test_private_reduction_entry_rejects_injected_trainer_before_reading_spec():
    with pytest.raises(worker.TrainingJobValidationError, match="without an injected trainer"):
        worker._execute_training_job(
            _Untouched(), trainer=lambda *args, **kwargs: None,
            job_file_sha256=None, reduce_native_targets=True,
        )


@pytest.fixture
def native_fixture():
    """Plain native types with synthetic contents, never production evidence."""
    samples, targets = [], {}
    for index in range(2):
        text = f"The agency shall retain record {index}."
        sample_id = f"synthetic-reduction-{index}"
        sample = LegalSample(
            sample_id, "us_code", "5", str(index), f"5 U.S.C. {index}", text, text,
            "mock:synthetic-reduction", [0.5, -0.0, 0.25, -0.5],
            ModalIRDocument(sample_id, "us_code", text),
        )
        document = LegalIRDocument(
            sample_id, text, text, source="us_code", citation=sample.citation,
            views={"deontic.ir": LogicIRView("deontic.ir", {
                "rules": [{"modality": "obligation", "subject": "agency", "action": "retain"}],
                "ordered": (2, 1), "negative_zero": -0.0,
            })}, metadata={"created_at": "fixed-synthetic-time", "nested": {"revision": index}},
        )
        target = LegalIRTrainingTarget(
            ("deontic_norms",), document,
            {"legal_ir_multiview_total_loss": 0.25, "fixture_loss": 0.125 + index, "signed_zero": -0.0},
            {"deontic_norms": {"fixture_loss": 0.125 + index}},
            {"deontic.ir": 1.0, "zero": 0.0, "negative": -0.25}, False,
        )
        samples.append(sample)
        targets[sample_id] = target
    return samples, targets


def _without_elapsed(value):
    if isinstance(value, dict):
        return {key: _without_elapsed(item) for key, item in value.items() if key != "elapsed_seconds"}
    if isinstance(value, list):
        return [_without_elapsed(item) for item in value]
    return value


@pytest.mark.parametrize("indices", [(0, 1), (1, 0), (0, 0, 1), (1,), ()])
def test_full_and_prepared_native_targets_keep_evaluation_state_and_capture(
    native_fixture, monkeypatch, indices
):
    from ipfs_datasets_py.logic.autoformal import embedded_actor, ontology_capture, procedure_slot, recipient_reference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import _prepare_native_targets

    samples, targets = native_fixture
    original_documents = {key: deepcopy(value.document.to_dict()) for key, value in targets.items()}
    original_hashes = {key: value.document.canonical_hash() for key, value in targets.items()}
    prepared, telemetry = _prepare_native_targets(targets)
    assert telemetry["applied"] is True
    assert prepared is not targets
    assert list(prepared) == list(targets)
    assert all(math.copysign(1.0, target.losses["signed_zero"]) == -1.0 for target in prepared.values())
    for target in prepared.values():
        with pytest.raises(TypeError):
            target.losses["signed_zero"] = 1.0
    samples = [samples[index] for index in indices]
    assert modal._legal_ir_target_payload(samples, legal_ir_targets=prepared) == (
        modal._legal_ir_target_payload(samples, legal_ir_targets=targets)
    )

    # Preserve the real capture loop/records; only external leaf extraction is
    # fixed to keep this a small deterministic fixture rather than a parser run.
    monkeypatch.setattr(ontology_capture, "triples_from_sample", lambda sample: [
        {"subject": sample.sample_id, "predicate": "type", "object": "record"}])
    monkeypatch.setattr(recipient_reference, "recipient_surface_from_sentence", lambda text: "")
    monkeypatch.setattr(procedure_slot, "procedure_from_sentence", lambda text: {
        "events": [], "procedure_id": "", "surface": "", "admitted": False})
    monkeypatch.setattr(embedded_actor, "clause_actors", lambda text: [])
    monkeypatch.setattr(embedded_actor, "actor_triples", lambda sample_id, actors: [])

    outcomes = []
    for selected in (targets, prepared):
        model = modal.AdaptiveModalAutoencoder(compute_device="python")
        with observe_ontology_captures(producer_identity={"kind": "synthetic-unit-fixture"}) as observer:
            evaluation = model.evaluate(
                samples, legal_ir_targets=selected,
                legal_ir_bridge_names=("deontic_norms",), use_sample_memory=False,
            )
        captures = getattr(model, "last_ontology_captures", None)
        assert hasattr(model, "last_ontology_captures") is bool(samples)
        outcomes.append((evaluation.to_dict(), model.state.to_dict(), captures,
                         _without_elapsed(observer.to_dict())))
    assert outcomes[0] == outcomes[1]
    assert outcomes[1][0]["legal_ir_target_count"] == len(samples)
    assert outcomes[1][0]["legal_ir_target_hashes"] == {
        sample.sample_id: original_hashes[sample.sample_id] for sample in samples
    }
    assert [row["sample_id"] for row in outcomes[1][2] or []] == [sample.sample_id for sample in samples]
    assert all(row["admitted"] is False for row in outcomes[1][2] or [])
    assert outcomes[1][3]["reuse_qualified"] is False
    assert outcomes[1][3]["context_closed"] is True
    assert {key: value.document.to_dict() for key, value in targets.items()} == original_documents


def test_default_public_worker_passes_original_full_hydrated_objects(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as preparation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import write_target_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    record = {"title": "5", "section": "fixture", "text": "The agency shall retain records."}
    sample = build_us_code_sample(**record)
    config = TargetSnapshotConfig(worker.BRIDGE_NAMES, False, 1, {"synthetic_fixture": "a" * 64})
    target = LegalIRTrainingTarget(
        worker.BRIDGE_NAMES,
        LegalIRDocument(sample.sample_id, sample.text, sample.normalized_text,
                        views={"deontic.ir": LogicIRView("deontic.ir", {"retained": [1, 2]})}),
        losses={"legal_ir_multiview_total_loss": 0.25}, view_distribution={"deontic.ir": 1.0},
    )
    saved = write_target_bundle(tmp_path / "synthetic.bundle", [(sample, target, "ready")], config=config)
    artifact_before = Path(saved["path"]).read_bytes()
    checkpoint = tmp_path / "base.json"
    checkpoint.write_text(modal.ModalAutoencoderTrainingState().to_json() + "\n")
    checkpoint_bytes = checkpoint.read_bytes()
    spec = worker.TrainingJobSpec.from_dict({
        "job_id": "default-target-fixture", "run_id": "default-target-run", "base_version_id": "base",
        "base_checkpoint": {"path": str(checkpoint), "bytes": len(checkpoint_bytes),
                            "sha256": hashlib.sha256(checkpoint_bytes).hexdigest()},
        "output_directory": str(tmp_path / "attempt"), "code_identity": "synthetic-unit-fixture",
        "dataset_snapshot_id": "synthetic-data", "split_snapshot_id": "synthetic-split",
        "samples": [record], "autoencoder_config": {"compute_device": "python"},
        "target_snapshot_id": saved["snapshot_id"],
        "target_snapshot_artifact": {key: saved[key] for key in ("path", "sha256", "bytes")},
    })
    monkeypatch.setattr(preparation, "target_snapshot_config", lambda _: config)
    original_hydrate = worker._hydrate_shared_targets
    observed = {}

    def hydrate(*args, **kwargs):
        result = original_hydrate(*args, **kwargs)
        observed["targets"] = result[0]
        return result

    monkeypatch.setattr(worker, "_hydrate_shared_targets", hydrate)

    def trainer(model, samples, *, validation_samples, **kwargs):
        assert kwargs["legal_ir_targets"] is observed["targets"]
        full = kwargs["legal_ir_targets"][sample.sample_id]
        assert type(full) is LegalIRTrainingTarget
        assert type(full.document) is LegalIRDocument
        assert full.document.views["deontic.ir"].payload == {"retained": [1, 2]}
        return {"accepted_epochs": 0, "stopped_reason": "synthetic-default-path-fixture"}

    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert receipt["execution_mode"] == "injected_test"
    assert receipt["target_reduction"]["requested"] is False
    assert receipt["target_reduction"]["applied"] is False
    assert json.loads((Path(spec.output_directory) / "receipt.json").read_text()) == receipt
    assert Path(saved["path"]).read_bytes() == artifact_before
    assert checkpoint.read_bytes() == checkpoint_bytes


@pytest.mark.parametrize("owner,method", [(LegalIRTrainingTarget, "to_dict"), (LegalIRDocument, "canonical_hash")])
def test_native_method_override_preserves_full_mapping_without_invoking_override(
    native_fixture, monkeypatch, owner, method
):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import _prepare_native_targets

    _samples, targets = native_fixture
    calls = []

    def custom(self):
        calls.append(self)
        raise AssertionError("reducer must not invoke a custom serializer or hash")

    monkeypatch.setattr(owner, method, custom)
    prepared, telemetry = _prepare_native_targets(targets)
    assert prepared is targets and telemetry["applied"] is False
    assert calls == []


def test_mixed_rich_grammar_targets_keep_original_mapping_and_live_revalidation(native_fixture):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import _prepare_native_targets

    samples, targets = native_fixture
    rich = RichLegalIRTarget({
        "family": "deontic", "candidate_ir": {
            "family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "retain"}],
        },
    })
    targets[samples[1].sample_id] = rich
    prepared, telemetry = _prepare_native_targets(targets)
    assert prepared is targets and telemetry["applied"] is False
    first = modal._legal_ir_target_payload(samples, legal_ir_targets=prepared)
    assert first["grammar_rejection_reasons_by_sample"][samples[1].sample_id]
    rich.candidate_ir["rules"][0]["modality"] = "obligation"
    current = modal._legal_ir_target_payload(samples, legal_ir_targets=prepared)
    assert current == modal._legal_ir_target_payload(samples, legal_ir_targets=targets)
    assert current != first


@pytest.mark.parametrize("attribute", ["grammar_validation", "legal_ir_grammar_validation"])
def test_native_attached_grammar_retains_full_mapping_and_exact_rejection(native_fixture, attribute):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import _prepare_native_targets

    samples, targets = native_fixture
    selected = samples[1].sample_id
    rejection = {"reason": "synthetic_explicit_rejection", "path": "$.rules[0]",
                 "family": "deontic", "production": "rule", "detail": "fixture detail"}
    object.__setattr__(targets[selected], attribute, {
        "accepted": False, "family": "deontic", "rejection_reasons": [rejection],
        "selected_productions": ["chosen"], "masked_productions": ["masked"],
    })
    before = modal._legal_ir_target_payload(samples, legal_ir_targets=targets)
    prepared, telemetry = _prepare_native_targets(targets)
    assert prepared is targets and telemetry["applied"] is False
    assert telemetry["skip_reason"] == "non_native_target_or_fields"
    after = modal._legal_ir_target_payload(samples, legal_ir_targets=prepared)
    assert after == before
    assert after["grammar_rejection_reasons_by_sample"][selected] == [rejection]
    assert after["target_losses_by_sample"][selected]["legal_ir_grammar_accepted"] == 0.0


def test_generic_dynamic_serializer_keeps_observation_order_and_rejection():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import _prepare_native_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import LegalIRGrammarDecoder

    calls = []

    def dynamic():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return {}
        return {"family": "deontic", "candidate_ir": {
            "family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "retain"}],
        }}

    target = SimpleNamespace(to_dict=dynamic)
    targets = {"custom-fixture": target}
    prepared, telemetry = _prepare_native_targets(targets)
    assert prepared is targets and telemetry["applied"] is False
    assert calls == []
    validation = modal._legal_ir_grammar_validation_from_target(
        prepared["custom-fixture"], decoder=LegalIRGrammarDecoder(),
        source_text="The agency shall retain records.",
    )
    assert calls == [1, 2]
    assert validation.accepted is False and validation.rejection_reasons
