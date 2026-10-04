"""v5 handoff tests with explicitly fake native execution, never Lake evidence.

Torch fitting is real. Source report validation and the native issuer are test
doubles; the end-to-end campaign separately executes actual native tools.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as api

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
    return api.train_validated_family_projection_autoencoder(
        original[0] if train is None else train, original[1] if tune is None else tune, **settings)


def test_decoder_strategy_preserves_live_gate_all_families_and_no_authority(tmp_path):
    train, tune = panels()
    result = fit(tmp_path / "fit", train, tune, refinement_strategy="decoder_blocks")
    report = result["report"]
    assert report["optimizer_steps"] == 6 and report["training_gate_passed"]
    assert report["refinement_strategy"] == "decoder_blocks"
    assert report["refinement_diagnostics"]["encoder_frozen"]
    assert report["loss_coverage"]["training"]["projection_occurrences"] == 12
    assert report["loss_coverage"]["tuning"]["projection_occurrences"] == 8
    assert not report["qualified"] and not report["admitted"] and not report["source_text_decoder_trained"]
    assert not report["roundtrip_ok"] and not report["constitution_formalized"]
    assert all(report["after"]["families"][family] <= value + api.EPS
               for family, value in report["before"]["families"].items())
    saved, parameters = api._read(result["descriptor"])
    assert len(parameters) == 4
    assert saved["implementation"]["decoder_refinement"] == api._sha(Path(api.decoder_refinement.__file__).read_bytes())
    inferred = api.infer_validated_family_projection_autoencoder(result["descriptor"], tune)
    assert inferred["loss_coverage"]["all_emitted_projections_have_loss"]
    assert set(inferred["families"]) == set(report["after"]["families"])
    assert not inferred["formulas_generated"] and not inferred["lake_build_executed"]


def test_default_still_matches_explicit_joint_adam(tmp_path):
    left = fit(tmp_path / "default")["report"]
    right = fit(tmp_path / "explicit", refinement_strategy="joint_adam")["report"]
    assert left["refinement_strategy"] == right["refinement_strategy"] == "joint_adam"
    assert left["selected_parameters_sha256"] == right["selected_parameters_sha256"]
    assert left["history"] == right["history"]
    assert left["refinement_diagnostics"] is None


def test_unknown_strategy_rejected_before_output(tmp_path):
    with pytest.raises(ValueError, match="refinement strategy"):
        fit(tmp_path / "fit", refinement_strategy="drop_hard_families")
    assert not (tmp_path / "fit").exists()


@pytest.mark.parametrize("strategy", ["joint_adam", "decoder_blocks"])
@pytest.mark.parametrize("field,bad", [("parser_status", "failed"), ("lake_status", "not_run"),
    ("semantic_lowering_supported", False)])
def test_each_strategy_blocks_any_invalid_native_projection(tmp_path, strategy, field, bad):
    value = report("bad")
    execution = FakeExecution(value); execution.rows[0][field] = bad
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "fit", [observe(value, execution)], refinement_strategy=strategy)
    assert not (tmp_path / "fit").exists()


def test_decoder_strategy_rejects_detached_json_and_missing_reviews(tmp_path):
    row = observe(report("bad"))
    with pytest.raises(ValueError, match="live validation observations"):
        fit(tmp_path / "detached", [row.to_dict()], refinement_strategy="decoder_blocks")
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "reviews", [observe(report("unreviewed"), missing_reviews=True)],
            refinement_strategy="decoder_blocks")
    assert not (tmp_path / "detached").exists() and not (tmp_path / "reviews").exists()


def test_missing_floor_cannot_be_waived_for_decoder_strategy(tmp_path):
    value = report("missing"); value["projections"].pop()
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "fit", [observe(value)], refinement_strategy="decoder_blocks")


def test_evidence_invalidated_during_decoder_refinement_blocks_artifact(tmp_path, monkeypatch):
    value = report("live")
    execution = FakeExecution(value)
    original = api.decoder_refinement.refine_decoder_blocks
    def invalidate(*args, **kwargs):
        result = original(*args, **kwargs)
        execution.valid = False
        return result
    monkeypatch.setattr(api.decoder_refinement, "refine_decoder_blocks", invalidate)
    with pytest.raises(policy.ProjectionValidationError):
        fit(tmp_path / "fit", [observe(value, execution)], refinement_strategy="decoder_blocks")
    assert not (tmp_path / "fit").exists()


def test_expired_whole_numerical_deadline_keeps_initialization(tmp_path):
    result = fit(tmp_path / "fit", refinement_strategy="decoder_blocks", max_seconds=1e-12)["report"]
    assert result["optimizer_steps"] == result["selected_epoch"] == 0
    assert result["stopping"] == "deadline"
    assert result["initial_parameters_sha256"] == result["selected_parameters_sha256"]
    assert not result["training_executed"]


def test_decoder_strategy_preserves_source_split_and_extra_projection_checks(tmp_path):
    same = observe(report("same"))
    with pytest.raises(ValueError, match="source leakage"):
        fit(tmp_path / "leakage", [same], [same], refinement_strategy="decoder_blocks")
    with pytest.raises(ValueError, match="every emitted projection"):
        fit(tmp_path / "extra", tune=[observe(report("extra", extra=True))],
            refinement_strategy="decoder_blocks")


def test_refinement_module_source_is_part_of_import_guard(tmp_path, monkeypatch):
    original = api._implementation
    def changed():
        result = original(); result["decoder_refinement"] = "0" * 64
        return result
    monkeypatch.setattr(api, "_implementation", changed)
    with pytest.raises(ValueError, match="producer changed"):
        fit(tmp_path / "fit", refinement_strategy="decoder_blocks")
    assert not (tmp_path / "fit").exists()
