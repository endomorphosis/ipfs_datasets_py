"""v6 complete-feature tests with fake native execution, never Lake evidence.

Torch fitting is real. Source report validation and the native issuer are test
doubles; the end-to-end campaign separately executes actual native tools.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_complete_v6 as api

policy = api.policy


class FakeExecution:
    def __init__(self, report):
        self.report = deepcopy(report)
        self.valid = True
        self.rows = [{"projection_id": r["projection_id"], "logic_family": r["logic_family"],
            "profile": r["profile"], "payload_sha256": policy._sha(r["payload"]),
            "source_digest": report["source_digest"], "parser_status": "passed", "lake_status": "passed",
            "semantic_lowering_supported": True, "lowering": {"capability_floor_eligible": True}}
            for r in report["projections"]]


@pytest.fixture(autouse=True)
def fake_native_issuer(monkeypatch):
    def validate(report):
        assert report["fixture_scope"] == "unit_v5_refinement_not_native_evidence"
    def verify(execution, report):
        if type(execution) is not FakeExecution or not execution.valid or execution.report != report:
            raise ValueError("missing matching fake live execution")
        return {"per_projection": deepcopy(execution.rows)}
    monkeypatch.setattr(policy, "_validate_report", validate)
    monkeypatch.setattr(policy, "_verify_execution", verify)
    monkeypatch.setattr(api.native, "validate_family_training_report_v7", validate)


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
        "requested_families": floor["family_inventory"], "frontier": [],
        "fixture_scope": "unit_v5_refinement_not_native_evidence",
        "producer_pins": {api.native.__name__: api._sha(Path(api.native.__file__).read_bytes())}}


def observe(value, execution=None, *, missing_reviews=False):
    execution = execution or FakeExecution(value)
    existing = {r["logic_family"] for r in value["projections"]}
    reviews = [] if missing_reviews else [{"family_id": family, "source_digest": value["source_digest"],
        "disposition": "inapplicable", "reason": "Synthetic policy fixture has a bounded source model.",
        "evidence_refs": ["unit-test:synthetic"]}
        for family in policy.domain_projection_policy("security_ir")["family_inventory"] if family not in existing]
    return policy.validate_projection_report(value, lake_execution=execution, applicability_review=reviews)


def panels():
    return ([observe(report("train" + str(i))) for i in range(3)],
            [observe(report("tune" + str(i))) for i in range(2)])


def fit(path, train=None, tune=None, **options):
    original = panels()
    settings = dict(domain_id="security_ir", output_dir=path,
        epochs=3, latent_width=2, minibatch_size=2, patience=3)
    settings.update(options)
    return api.train_complete_family_projection_autoencoder(
        original[0] if train is None else train, original[1] if tune is None else tune, **settings)


def test_complete_head_keeps_every_training_atom_and_native_family(tmp_path):
    train, tune = panels()
    fitted = fit(tmp_path / "fit", train, tune)
    saved, parameters = api._read(fitted["descriptor"])
    selection = saved["space"]["feature_selection"]
    assert selection["available_atoms"] == selection["retained_atoms"]
    assert fitted["report"]["optimizer_steps"] == 6
    assert all(fitted["report"]["after"]["families"][key] <= value + api.EPS
               for key, value in fitted["report"]["before"]["families"].items())
    inferred = api.infer_complete_family_projection_autoencoder(fitted["descriptor"], tune)
    assert inferred["complete_support_metrics"]
    assert inferred["loss_coverage"]["all_emitted_projections_have_loss"]
    assert not inferred["formulas_generated"] and not inferred["source_text_decoded"]
    assert not fitted["report"]["admitted"] and not fitted["report"]["qualified"]


def test_full_vocabulary_can_exceed_old_budget_without_pruning(tmp_path):
    def large(identity):
        value = report(identity)
        value["projections"][0]["payload"]["ordered_values"] = [str(i) for i in range(2200)]
        return observe(value)
    fitted = fit(tmp_path / "large", [large("train-a"), large("train-b")],
                 [large("tune-a")], epochs=1)
    saved, _ = api._read(fitted["descriptor"])
    assert len(saved["space"]["columns"]) > 4096
    assert saved["space"]["feature_selection"]["available_atoms"] == saved["space"]["feature_selection"]["retained_atoms"]


@pytest.mark.parametrize("option", [{"max_features": 1}, {"memory_budget_bytes": 1}])
def test_complete_budget_failure_never_truncates_or_writes(tmp_path, option):
    with pytest.raises(ValueError):
        fit(tmp_path / "bounded", **option)
    assert not (tmp_path / "bounded").exists()


@pytest.mark.parametrize("field,bad", [("parser_status", "failed"), ("lake_status", "not_run"),
    ("semantic_lowering_supported", False)])
def test_complete_path_requires_every_live_native_projection(tmp_path, field, bad):
    value = report("bad")
    execution = FakeExecution(value); execution.rows[0][field] = bad
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "blocked", [observe(value, execution)])
    assert not (tmp_path / "blocked").exists()


def test_complete_path_rejects_detached_observations_and_source_overlap(tmp_path):
    value = observe(report("source"))
    with pytest.raises(ValueError, match="live validation observations"):
        fit(tmp_path / "detached", [value.to_dict()])
    with pytest.raises(ValueError, match="source leakage"):
        fit(tmp_path / "leak", [value], [value])


def test_complete_path_does_not_select_after_expired_deadline(tmp_path):
    fitted = fit(tmp_path / "expired", max_seconds=1e-12)
    report = fitted["report"]
    assert report["optimizer_steps"] == 0 and report["selected_epoch"] == 0
    assert report["initial_parameters_sha256"] == report["selected_parameters_sha256"]


def test_complete_checkpoint_cannot_use_v5_descriptor(tmp_path):
    fitted = fit(tmp_path / "fit")
    descriptor = {**fitted["descriptor"], "schema": api.previous.SCHEMA}
    with pytest.raises(ValueError, match="descriptor"):
        api._read(descriptor)


@pytest.mark.parametrize("option", [{"adaptive_learning_rate": "yes"}, {"plateau_patience": 0},
    {"plateau_factor": 2}, {"min_learning_rate_ratio": 0}])
def test_invalid_adaptive_options_reject_before_output(tmp_path, option):
    with pytest.raises(ValueError):
        fit(tmp_path / "invalid", **option)
    assert not (tmp_path / "invalid").exists()


def test_live_evidence_change_during_refinement_blocks_artifact(tmp_path, monkeypatch):
    value = report("live")
    execution = FakeExecution(value)
    original = api.adaptive.refine_decoder_blocks_adaptive
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        execution.valid = False
        return result
    monkeypatch.setattr(api.adaptive, "refine_decoder_blocks_adaptive", mutate)
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "changed", [observe(value, execution)])
    assert not (tmp_path / "changed").exists()
