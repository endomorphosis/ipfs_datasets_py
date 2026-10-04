"""Clause benchmark input/control contracts; no checkpoint or model execution."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_controls as controls
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as fidelity
from .test_clause_source_controls import fixture

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "scripts/ops/autoencoder/benchmark_clause_context_source_training.py"
SPEC = importlib.util.spec_from_file_location("_clause_context_runner_contract", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class Model:
    def __init__(self, schema="clause-source-decoder-development/v1"):
        self.schema = schema

    def describe(self):
        return {"schema": self.schema}


def context(monkeypatch, *, lengths=(1, 1, 2, 2, 4, 4, 8, 8), complete=True):
    rows, contexts = fixture(lengths)
    references = [dict(id=row["id"], original_reference=index) for index, row in enumerate(rows)]
    calls = {}

    def numeric(model, actual, **kwargs):
        calls["numeric"] = (model, actual, kwargs)
        return dict(report=dict(complete=complete, elapsed_seconds=.01), predictions=[{"id": row["id"]} for row in actual])

    def score(refs, predictions, **kwargs):
        calls["score"] = (refs, predictions, kwargs)
        return {"complete_evaluation": True}

    def count(torch, model, actual, refs, transform, config, deadline):
        calls["count"] = (model, actual, refs)
        return {"count_readout": True}

    def reference_values(original, refs, codec, **kwargs):
        assert original is rows and refs is references
        calls["labels"] = original
        return {"opaque_reference_labels": True}

    def scalar(torch, model, actual, labels, transform, config, codec, deadline, **kwargs):
        calls["scalar"] = (model, actual, labels, kwargs)
        return {"scalar_readout": True}

    def guidance(ctx, model, actual, actual_contexts, deadline):
        calls["guidance"] = (model, actual, actual_contexts)
        return {"guidance_readout": True}

    def zero(model):
        calls["zero"] = model
        return Model("zero-clause-source-control/v1")

    monkeypatch.setattr(subject, "guidance_diagnostic", guidance)
    ctx = dict(rows={"validation": rows, "train": rows}, references={"validation": references, "train": references},
        source_contexts={"validation": contexts, "train": contexts},
        core=SimpleNamespace(evaluate_model=numeric, digest=controls._digest),
        owners={"clause_source_controls": controls,
            "clause_source_decoder_experiment": SimpleNamespace(bind_zero_condition_model=zero),
            "long_span_count_exposure_training": SimpleNamespace(_count_evaluation=count),
            "source_value_decoder_experiment": SimpleNamespace(reference_source_values=reference_values),
            "long_span_source_value_training": SimpleNamespace(_source_value_evaluation=scalar)},
        scorer=SimpleNamespace(score_predictions=score), donor={"codec": {}, "input_transform": {}},
        plan={"max_seconds_per_postfit": 30}, lineage={}, validate_rule=object(), validator_id="synthetic",
        old=SimpleNamespace(boundary_diagnostics=lambda *args: {"posthoc_only": True}),
        preprocessing={"count_prior": {}}, shared=SimpleNamespace())
    return ctx, calls


@pytest.mark.parametrize("control", ["conditioned", "source_shuffle", "cross_length_shuffle",
    "context_only_shuffle", "context_reverse", "context_rotate", "zero_condition"])
def test_contextual_evaluation_routes_one_source_control_to_all_readouts_and_original_references(monkeypatch, control):
    lengths = tuple(x for x in (1, 2, 4, 8) for _ in range(12)) if control == "cross_length_shuffle" else (1, 1, 2, 2, 4, 4, 8, 8)
    ctx, calls = context(monkeypatch, lengths=lengths)
    original = deepcopy((ctx["rows"], ctx["references"], ctx["source_contexts"]))
    model = Model()
    value = subject.evaluate(ctx, model, "validation", control)
    actual = calls["numeric"][1]
    supplied = calls["numeric"][2]["source_contexts"]
    assert calls["scalar"][1] is actual and calls["guidance"][1] is actual
    assert calls["scalar"][3]["source_contexts"] is supplied and calls["guidance"][2] is supplied
    assert calls["score"][0] is ctx["references"]["validation"]
    assert calls["count"][2] is ctx["references"]["validation"]
    assert calls["labels"] is ctx["rows"]["validation"]
    assert [r["target_ids"] for r in actual] == [r["target_ids"] for r in ctx["rows"]["validation"]]
    assert (ctx["rows"], ctx["references"], ctx["source_contexts"]) == original
    assert value["execution"]["kind"] == control
    assert calls["score"][2]["control"]["kind"] == control
    assert value["execution"]["context_passed_to_model"]
    assert value["execution"]["source_contexts_sha256"] == controls._digest(supplied)
    assert not value["execution"]["training_performed"] and not value["execution"]["selection_performed"]
    if control == "zero_condition":
        assert calls["zero"] is model
        assert calls["numeric"][0].schema == "zero-clause-source-control/v1"
        assert value["execution"]["normalized_clause_values_and_padding_mask_removed"]


@pytest.mark.parametrize("kind", controls.KINDS)
def test_real_fidelity_scorer_accepts_exact_control_descriptor_without_relabeling(kind):
    lengths = tuple(x for x in (1, 2, 4, 8) for _ in range(12)) if kind == "cross_length_shuffle" else (1, 1, 2, 2)
    rows, contexts = fixture(lengths)
    _, _, execution = controls.prepare_control(rows, contexts, kind)
    result = fidelity._control(execution["control"], [row["id"] for row in rows])
    assert result == execution["control"] and result["kind"] == kind


@pytest.mark.parametrize("control", [row[2] for row in subject.CONTROLS])
def test_baseline_original_five_controls_delegate_exactly_without_context_preparation(monkeypatch, control):
    ctx, calls = context(monkeypatch)
    sentinel = {"original_baseline_result": True}
    observed = []
    ctx["shared"].evaluate = lambda *args: observed.append(args) or sentinel
    monkeypatch.setattr(controls, "prepare_control", lambda *args: pytest.fail("changed baseline control preparation"))
    model = Model("shared-slot-source-decoder-development/v1")
    assert subject.evaluate(ctx, model, "validation", control) is sentinel
    assert observed == [(ctx, model, "validation", control)] and not calls


@pytest.mark.parametrize("control", [row[2] for row in subject.EXTRA_CONTROLS])
def test_baseline_clause_only_controls_never_pass_sidecars_to_pooled_model(monkeypatch, control):
    ctx, calls = context(monkeypatch)
    model = Model("shared-slot-source-decoder-development/v1")
    value = subject.evaluate(ctx, model, "validation", control)
    assert "source_contexts" not in calls["numeric"][2]
    assert not calls["scalar"][3] and calls["guidance"][2] is None
    assert [r["input"] for r in calls["numeric"][1]] == [r["input"] for r in ctx["rows"]["validation"]]
    assert not value["execution"]["context_passed_to_model"]
    assert value["execution"]["source_contexts_sha256"] is None
    assert value["execution"]["kind"] == control


def test_incomplete_numeric_evaluation_stops_before_auxiliary_scores(monkeypatch):
    ctx, calls = context(monkeypatch, complete=False)
    with pytest.raises(ValueError, match="incomplete contextual"):
        subject.evaluate(ctx, Model(), "validation", "conditioned")
    assert set(calls) == {"numeric"}


@pytest.mark.parametrize("recipe", subject.ARMS)
def test_training_sidecars_are_opt_in_and_optimizer_budget_and_gates_are_fixed(recipe):
    captured = []
    trainer = SimpleNamespace(train=lambda *args, **kwargs: captured.append((args, kwargs)) or "result")
    ctx = dict(owners={"long_span_source_value_training": trainer}, rows={"train": [], "validation": []},
        references={"train": [], "validation": []}, donor={"codec": {}, "input_transform": {}}, lineage={},
        validate_rule=object(), validator_id="synthetic", stages=[], source_contexts={"train": {}, "validation": {}})
    assert subject.train_candidate(ctx, Model(), 1729, recipe) == "result"
    kwargs = captured[0][1]
    assert kwargs["generated_boundary_weight"] == 0. and kwargs["order_augmentation"] is None
    assert kwargs["cardinality_weight"] == kwargs["source_value_weight"] == .25
    assert kwargs["count_exposure"] == "balanced_all"
    assert kwargs["config"] == dict(seed=1729, max_seconds=180, max_target_tokens=512,
        batch_size=8, learning_rate=.001, max_optimizer_steps=1000, patience=0, validation_interval=4, alpha=0.)
    if recipe["head_kind"] == "pooled":
        assert "source_contexts" not in kwargs
    else:
        assert kwargs["source_contexts"] is ctx["source_contexts"]


@pytest.mark.parametrize("field,value", [("candidate_training_parameter_delta", 0),
    ("fixed_encoder_context_tokens", 1024), ("fixed_decoder_output_limit", 1024),
    ("temperature", 1), ("generated_boundary_loss_enabled", True),
    ("expected_optimizer_steps_per_arm", 341), ("source_only_generation", False),
    ("selection_unchanged", False), ("unique_training_clause_count", 114),
    ("production_promotion_allowed", True)])
def test_fixed_plan_rejects_changed_architecture_exposure_or_qualification(field, value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[field] = value
    with pytest.raises(ValueError, match="fixed training recipe"):
        subject.validate_plan(plan)


def test_frozen_helper_cannot_load_with_wrong_manifest_digest(tmp_path):
    path = tmp_path / "helper.py"
    path.write_text("value=17\n")
    with pytest.raises(ValueError, match="frozen helper differs"):
        subject.load_helper(tmp_path, {"helper.py": "0" * 64}, "helper.py", "_clause_wrong_hash")
    helper = subject.load_helper(tmp_path, {"helper.py": hashlib.sha256(path.read_bytes()).hexdigest()},
        "helper.py", "_clause_correct_hash")
    assert helper.value == 17


@pytest.mark.parametrize("value", [True, 1729., 2718, [], {"value": 1729}])
def test_persisted_integer_seed_cannot_be_coerced_or_changed(value):
    template = {"head_initialization_seed": torch.tensor(1729, dtype=torch.long)}
    with pytest.raises(ValueError, match="integer architecture buffer"):
        subject.restored_tensors({}, {"head_initialization_seed": value}, template)


def test_persisted_known_integer_seed_preserves_exact_dtype_and_value():
    template = {"head_initialization_seed": torch.tensor(1729, dtype=torch.long)}
    restored = subject.restored_tensors({}, {"head_initialization_seed": 1729}, template)
    assert restored["head_initialization_seed"].dtype == torch.long
    assert torch.equal(restored["head_initialization_seed"], template["head_initialization_seed"])


def baseline():
    old = dict(elapsed_seconds=1., config={"max_seconds": 90, "learning_rate": .001},
        optimizer_steps=340, selected_epoch=0, selected_weights_sha256="a" * 64,
        last_complete_attempt_weights_sha256="b" * 64, committed_updates=[{"loss": .2}])
    report = deepcopy(old); report["elapsed_seconds"] = 2.; report["config"]["max_seconds"] = 180
    postfit = {role: {label: {"predictions": [{"id": "row", "token_ids": [3],
        "eos_reached": True, "generation_status": "eos", "exact_target": False,
        "reconstructed_input": [1.]}]} for label, _, _ in subject.CONTROLS}
        for role in ("selected", "last-attempt")}
    return report, {"training": old, "postfit": deepcopy(postfit)}, postfit


def test_baseline_replay_permits_only_predeclared_wall_headroom_and_elapsed_time():
    report, prior, postfit = baseline()
    value = subject.validate_baseline(report, prior, postfit, SimpleNamespace(digest=controls._digest))
    assert value["complete"] and value["all_tensors_and_predictions_equal"]
    assert not value["timing_equality_claimed"]


@pytest.mark.parametrize("field", ["optimizer_steps", "selected_epoch", "selected_weights_sha256",
    "last_complete_attempt_weights_sha256", "committed_updates", "unplanned_new_key"])
def test_baseline_replay_rejects_report_or_selection_drift(field):
    report, prior, postfit = baseline()
    report[field] = "changed"
    with pytest.raises(ValueError, match="baseline"):
        subject.validate_baseline(report, prior, postfit, SimpleNamespace(digest=controls._digest))


@pytest.mark.parametrize("field", ["id", "token_ids", "eos_reached", "generation_status",
    "exact_target", "reconstructed_input"])
def test_baseline_replay_compares_complete_prediction_envelope(field):
    report, prior, postfit = baseline()
    postfit["last-attempt"]["validation"]["predictions"][0][field] = "changed"
    with pytest.raises(ValueError, match="full source-control predictions"):
        subject.validate_baseline(report, prior, postfit, SimpleNamespace(digest=controls._digest))
