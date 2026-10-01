"""Strict training handoff tests; fake issuer isolates accounting, not Lake proof.

The positive numerical smoke runs real torch on tiny synthetic native-feature
panels. Native parsing and live Lake issuance are dependency doubles here; their
real end-to-end checks belong to the native issuer integration suite.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract as policy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated as api


class Execution:
    def __init__(self, report):
        self.digest = api._digest(report)
        self.valid = True
        self.rows = [{"projection_id": r["projection_id"], "logic_family": r["logic_family"],
            "profile": r["profile"], "payload_sha256": api._digest(r["payload"]),
            "source_digest": report["source_digest"], "parser_status": "passed", "lake_status": "passed",
            "semantic_lowering_supported": True} for r in report["projections"]]


@pytest.fixture(autouse=True)
def dependencies(monkeypatch):
    def validate(report):
        assert report["unit_test_not_native_evidence"] is True
    def verify(execution, report):
        if type(execution) is not Execution or not execution.valid or execution.digest != api._digest(report):
            raise ValueError("invalid live issuer fixture")
        return {"per_projection": deepcopy(execution.rows)}
    monkeypatch.setattr(policy, "_validate_report", validate)
    monkeypatch.setattr(policy, "_verify_execution", verify)
    monkeypatch.setattr(api.native, "validate_family_training_report_v3", validate)


def report(identity, *, extra=False):
    floor = policy.domain_projection_policy("security_ir")
    targets = []
    for index, route in enumerate(floor["minimum_batch_floor"]):
        target = {"projection_id": "security_ir/unit/" + str(index), "logic_family": route["family_id"],
            "profile": route["profile"], "representation_kind": "unit_ast", "producer_id": "fixture",
            "payload": {"op": "and", "arguments": [identity, "common"], "index": index}, "ready_for_training": True}
        target["target_sha256"] = api._digest(target)
        targets.append(target)
    if extra:
        target = deepcopy(targets[0]); target["projection_id"] += "/extra"
        target["target_sha256"] = api._digest(target)
        targets.append(target)
    return {"schema": api.native.SCHEMA, "domain_id": "security_ir", "source_digest": api._digest(identity),
        "source_sha256": api._digest("text:" + identity), "projections": targets,
        "requested_families": floor["family_inventory"], "frontier": [], "unit_test_not_native_evidence": True,
        "producer_pins": {api.native.__name__: api._sha(Path(api.native.__file__).read_bytes())}}


def observe(value, execution=None):
    execution = execution or Execution(value)
    existing = {r["logic_family"] for r in value["projections"]}
    reviews = [{"family_id": family, "source_digest": value["source_digest"], "disposition": "inapplicable",
        "reason": "Synthetic policy fixture has a bounded source model.", "evidence_refs": ["unit-test:synthetic"]}
        for family in policy.domain_projection_policy("security_ir")["family_inventory"] if family not in existing]
    return policy.validate_projection_report(value, lake_execution=execution, applicability_review=reviews)


def panels():
    return ([observe(report("train" + str(i))) for i in range(3)],
            [observe(report("tune" + str(i))) for i in range(2)])


def fit(tmp_path, train=None, tune=None, **kwargs):
    original = panels()
    return api.train_validated_family_projection_autoencoder(
        original[0] if train is None else train, original[1] if tune is None else tune,
        domain_id="security_ir", output_dir=tmp_path / "fit", epochs=2,
        latent_width=2, minibatch_size=2, patience=2, **kwargs)


def test_real_numerical_fit_and_inference_require_complete_loss_coverage(tmp_path):
    train, tune = panels()
    fitted = fit(tmp_path, train, tune)
    result = fitted["report"]
    assert result["optimizer_steps"] == 4
    assert result["training_executed"] and result["training_gate_passed"]
    assert result["loss_coverage"]["training"]["projection_occurrences"] == 12
    assert result["loss_coverage"]["tuning"]["projection_occurrences"] == 8
    assert not result["admitted"] and not result["qualified"] and not result["source_text_decoder_trained"]
    assert result["validation_policy"]["training"]["optimization_input_binding_checked"]
    assert all(result["after"]["families"][k] <= v + 1e-12 for k,v in result["before"]["families"].items())
    saved, tensors = api._read(fitted["descriptor"])
    assert len(tensors) == 4
    assert saved["space"]["training_reports_sha256"] == api._digest([r.native_report() for r in train])
    result = api.infer_validated_family_projection_autoencoder(fitted["descriptor"], tune)
    assert result["loss_coverage"]["all_emitted_projections_have_loss"]
    assert not result["formulas_generated"] and not result["lake_build_executed"]


@pytest.mark.parametrize("field,bad", [("lake_status","not_run"),("parser_status","failed"),
    ("semantic_lowering_supported",False)])
def test_one_failed_projection_blocks_before_output(tmp_path, field, bad):
    value = report("bad")
    execution = Execution(value); execution.rows[0][field] = bad
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path, [observe(value, execution)])
    assert not (tmp_path / "fit").exists()


def test_saved_observation_receipt_cannot_authorize_training(tmp_path):
    with pytest.raises(ValueError, match="live validation observations"):
        fit(tmp_path, [observe(report("bad")).to_dict()])
    assert not (tmp_path / "fit").exists()


def test_incomplete_modality_floor_blocks_even_all_emitted_rows_pass(tmp_path):
    value = report("missing"); value["projections"].pop()
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path, [observe(value)])
    assert not (tmp_path / "fit").exists()


def test_exact_source_overlap_is_rejected(tmp_path):
    value = observe(report("same"))
    with pytest.raises(ValueError, match="source leakage"):
        fit(tmp_path, [value], [value])


def test_same_source_text_with_different_typed_report_is_rejected(tmp_path):
    left, right = report("left"), report("right")
    right["source_sha256"] = left["source_sha256"]
    with pytest.raises(ValueError, match="source leakage"):
        fit(tmp_path, [observe(left)], [observe(right)])


def test_untrained_extra_projection_never_silently_disappears(tmp_path):
    with pytest.raises(ValueError, match="every emitted projection"):
        fit(tmp_path, tune=[observe(report("extra", extra=True))])
    assert not (tmp_path / "fit").exists()


def test_training_only_projection_without_tuning_metrics_blocks(tmp_path):
    with pytest.raises(ValueError, match="both training and tuning"):
        fit(tmp_path, train=[observe(report("extra", extra=True))])


def test_evidence_invalidated_during_fitting_blocks_publication(tmp_path, monkeypatch):
    value = report("bound"); execution = Execution(value)
    original = api.prepared._calibrate_decoder
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        execution.valid = False
        return result
    monkeypatch.setattr(api.prepared, "_calibrate_decoder", mutate)
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path, [observe(value, execution)])
    assert not (tmp_path / "fit").exists()


def test_expired_deadline_does_not_train_or_select_late_weights(tmp_path):
    fitted = fit(tmp_path, max_seconds=1e-12)
    result = fitted["report"]
    assert result["optimizer_steps"] == 0 and result["selected_epoch"] == 0
    assert not result["training_executed"]
    assert result["initial_parameters_sha256"] == result["selected_parameters_sha256"]
    assert result["stopping"] == "deadline"


def test_partial_epoch_consumes_work_but_is_never_selected(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original = api._forward
    def forward(torch, values, parameters):
        result = original(torch, values, parameters)
        if parameters[0].requires_grad:
            clock[0] = 2.0
        return result
    monkeypatch.setattr(api, "_forward", forward)
    result = fit(tmp_path, max_seconds=1.)["report"]
    assert result["optimizer_steps"] == 1 and result["epochs_completed"] == 0
    assert result["selected_epoch"] == 0
    assert result["stopping"] == "deadline_partial_epoch_not_selected"


def test_calibration_selection_finishing_after_deadline_is_discarded(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original = api.prepared._select_decoder_families
    def select(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 2.0
        return result
    monkeypatch.setattr(api.prepared, "_select_decoder_families", select)
    result = fit(tmp_path, max_seconds=1.)["report"]
    assert result["optimizer_steps"] == 0
    assert result["decoder_calibration"]["selection_discarded_due_deadline"]
    assert result["initial_parameters_sha256"] == result["selected_parameters_sha256"]
    assert not result["trained_logic_families"]


@pytest.mark.parametrize("setting,bad", [("learning_rate", float("nan")),("learning_rate",True),
    ("ridge",0), ("denoising",float("inf")),("seed",True),("max_seconds",-1)])
def test_invalid_settings_do_not_write_output(tmp_path, setting, bad):
    with pytest.raises(ValueError):
        fit(tmp_path, **{setting:bad})
    assert not (tmp_path / "fit").exists()


def test_checkpoint_tampering_and_old_schema_are_rejected(tmp_path):
    fitted = fit(tmp_path)
    descriptor = fitted["descriptor"]
    original = dict(descriptor); original["schema"] = api.prepared.SCHEMA
    with pytest.raises(ValueError, match="closed validated"):
        api._read(original)
    path = Path(descriptor["path"])
    saved = __import__('json').loads(path.read_bytes()); saved["admitted"] = True
    raw = api._raw(saved); path.write_bytes(raw)
    descriptor["sha256"] = api._sha(raw)
    with pytest.raises(ValueError, match="cannot grant authority"):
        api._read(descriptor)


def test_inference_reauthenticates_input_and_rejects_stored_receipt(tmp_path):
    fitted = fit(tmp_path)
    value = report("inference"); execution = Execution(value); observation = observe(value, execution)
    execution.valid = False
    with pytest.raises(policy.ProjectionValidationError):
        api.infer_validated_family_projection_autoencoder(fitted["descriptor"], [observation])
    with pytest.raises(ValueError, match="live validation observations"):
        api.infer_validated_family_projection_autoencoder(fitted["descriptor"], [observation.to_dict()])
