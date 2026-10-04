"""Synthetic numerical controls only; no source fidelity or corpus evidence."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def single_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def setup(dimension=8):
    codec = {"schema": "explicit-synthetic-test/v1", "target_vocabulary": ["<pad>", "<bos>", "<eos>", "a", "b"]}
    model = numerical._model({"dimension": dimension}, codec,
        dict(seed=3517, projection_width=2, hidden_size=8, token_embedding_dim=8))
    model = subject.bind_model(model, dimension=dimension)
    transform = dict(mode="none", origin="training_only", mean=[0.]*dimension, scale=1.)
    lineage = dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=subject.digest(codec),
        input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic-test-only",
        student_lineage="fresh-experimental-test", teacher_output_limit=64,
        student_role="learned_formula_sidecar" if dimension == 8 else "source_conditioned_decoder")
    def rows(split):
        return [dict(id=f"{split}-{i}", source_text=f"{split} authored synthetic sample {i}",
            input=[.1+i*.1]+[0.]*(dimension-1), target_ids=[1, 3+i%2, 2]) for i in range(2)]
    return model, rows("train"), rows("validation"), dict(codec=codec, input_transform=transform,
        lineage=lineage, config=dict(epochs=2, max_optimizer_steps=2, batch_size=2,
        max_target_tokens=8, max_seconds=20., validation_interval=1))


def test_real_projection_start_next_protocol_and_teacher_unchanged():
    model, train, tune, options = setup()
    before, inputs = subject.tensor_digest(model), deepcopy((train, tune, options))
    modes = [module.training for module in model.modules()]
    result = subject.run_trial(model, train, tune, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 2
    assert report["initial_student_weights_sha256"] == before
    assert report["teacher_weights_sha256"] == subject.tensor_digest(model) == before
    assert modes == [module.training for module in model.modules()]
    assert (train, tune, options) == inputs
    assert all(parameter.grad is None for parameter in model.parameters())
    assert report["baseline_validation"]["complete"] and report["selected_validation"]["complete"]
    assert report["selected_validation"]["token_cross_entropy"] <= report["baseline_validation"]["token_cross_entropy"]
    assert report["training_row_presentations"] == 4 and report["training_token_presentations"] == 8
    assert report["distillation_temperature"] == 1 and report["generation_temperature"] == 0
    assert report["scope"] == "exposed_development_only"
    assert all(report[key] is False for key in subject.FALSE)
    assert report["teacher_qualification"] == "not_established" and report["optimizer_resumable"] is False
    assert len(result["predictions"]) == 2
    assert not any(value.requires_grad for value in result["state_dict"].values())
    model.load_state_dict(result["state_dict"], strict=True)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_dimensions_are_explicit_model_inputs_not_invented_embeddings(dimension):
    model, train, tune, options = setup(dimension)
    options["config"].update(epochs=1, max_optimizer_steps=1, alpha=0)
    result = subject.run_trial(model, train, tune, **options)
    assert result["report"]["input_dimension"] == dimension
    assert len(result["predictions"][0]["reconstructed_input"]) == dimension


def test_bind_is_private_and_refuses_protocol_or_unspecified_dimension():
    model, *_ = setup()
    adapted = subject.bind_model(model, dimension=8)
    assert next(adapted.parameters()).data_ptr() != next(model.parameters()).data_ptr()
    with pytest.raises(ValueError, match="input dimension"):
        subject.bind_model(model, dimension=16)
    with pytest.raises(ValueError, match="protocol"):
        subject.bind_model(torch.nn.Linear(8, 8), dimension=8)


def test_kl_exact_shared_mask_teacher_detached_and_padding_ignored():
    student = torch.tensor([[[1., 2., 3.], [4., 0., -1.]]], requires_grad=True)
    teacher = torch.tensor([[[3., 0., 1.], [-4., 4., 1.]]], requires_grad=True)
    labels = torch.tensor([[2, 0]])
    objective, ce, kl = subject._loss(torch, student, teacher, labels, .5)
    expected_ce = torch.nn.functional.cross_entropy(student[:, 0], labels[:, 0])
    expected_kl = torch.nn.functional.kl_div(torch.log_softmax(student[:, 0], -1),
        torch.softmax(teacher[:, 0].detach(), -1), reduction="batchmean")
    assert torch.allclose(ce, expected_ce) and torch.allclose(kl, expected_kl)
    assert torch.allclose(objective, ce+.5*kl)
    objective.backward()
    assert teacher.grad is None and torch.equal(student.grad[:, 1], torch.zeros_like(student.grad[:, 1]))


def test_expanded_output_cap_is_fresh_generation_and_teacher_prefix_is_bounded():
    model, train, tune, options = setup()
    options["lineage"]["teacher_output_limit"] = 4
    for row in train + tune:
        row["target_ids"] = [1, 3, 4, 3, 2]
    with pytest.raises(ValueError, match="teacher output limit"):
        subject.run_trial(model, train, tune, **options)
    options["config"].update(alpha=0, epochs=1)
    report = subject.run_trial(model, train, tune, **options)["report"]
    assert report["output_limit_migration"] == dict(teacher=4, student=8,
        experimental_generation_only=True, published_parent_unchanged=True)
    assert report["encoder_context_changed"] is False


@pytest.mark.parametrize("mutation,reason", [
    (lambda t, v, o: t[0].update(target_ids=[1, 3, 3, 3, 3, 3, 3, 3, 2]), "without truncation"),
    (lambda t, v, o: t[0].update(target_ids=[1, 3, 0, 2]), "complete BOS"),
    (lambda t, v, o: t[0].update(target_ids=[True, 3, 2]), "complete BOS"),
    (lambda t, v, o: t[0].update(target_ids=[1, 99, 2]), "complete BOS"),
    (lambda t, v, o: t[0].update(input=[0.]), "input width"),
    (lambda t, v, o: v[0].update(id=t[0]["id"]), "split overlap"),
    (lambda t, v, o: v[0].update(source_text=t[0]["source_text"].upper()), "split overlap"),
    (lambda t, v, o: o["lineage"].update(teacher_codec_sha256="c"*64), "codec identity"),
    (lambda t, v, o: o["lineage"].update(qualified=True), "closed development lineage"),
    (lambda t, v, o: o["lineage"].update(student_role="source_conditioned_decoder"), "historical linguistic"),
    (lambda t, v, o: o["input_transform"].update(origin="validation"), "training-only"),
    (lambda t, v, o: o["input_transform"].update(scale=2.), "identity transform"),
    (lambda t, v, o: o["config"].update(max_target_tokens=1025), "max_target_tokens"),
    (lambda t, v, o: o["config"].update(plateau_factor=1.), "reduce learning rate"),
    (lambda t, v, o: o["config"].update(temperature=1.), "unknown trial option"),
])
def test_bad_inputs_fail_closed(mutation, reason):
    model, train, tune, options = setup()
    mutation(train, tune, options)
    with pytest.raises(ValueError, match=reason):
        subject.run_trial(model, train, tune, **options)


def test_incomplete_validation_cannot_replace_baseline(monkeypatch):
    model, train, tune, options = setup()
    original = subject._evaluate
    calls = []
    def bounded(*args):
        calls.append(1)
        return original(*args) if len(calls) == 1 else None
    monkeypatch.setattr(subject, "_evaluate", bounded)
    result = subject.run_trial(model, train, tune, **options)
    assert len(calls) == 2
    assert result["report"]["stopped_reason"] == "deadline_during_validation"
    assert result["report"]["selected_epoch"] == 0
    assert result["report"]["selected_student_weights_sha256"] == subject.tensor_digest(model)
    assert result["report"]["history"][0]["validation"] is None


def test_deadline_before_baseline_provides_no_validated_selection(monkeypatch):
    model, train, tune, options = setup()
    monkeypatch.setattr(subject, "_evaluate", lambda *args: None)
    result = subject.run_trial(model, train, tune, **options)
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["selected_epoch"] is None
    assert result["report"]["baseline_validation"] is None and result["predictions"] == []


@pytest.mark.parametrize("token,status,ended", [(0, "invalid_special_token", False),
    (1, "invalid_special_token", False), (2, "eos", True), (3, "output_limit", False)])
def test_greedy_status_no_bos_pad_or_truncation_success(token, status, ended):
    model, train, _, options = setup()
    with torch.no_grad():
        model.body.output.weight.zero_()
        model.body.output.bias.fill_(-10.)
        model.body.output.bias[token] = 10.
    data, _ = subject._batch(torch, train, options["input_transform"])
    _, outputs, statuses = subject._greedy(torch, model, data, 4, 5, time.monotonic()+5)
    assert statuses == [status]*2
    assert all((item == "eos") == ended for item in statuses)
    assert outputs == ([[3]*3]*2 if token == 3 else [[], []])


def test_memory_budget_checks_before_training():
    model, train, tune, options = setup(768)
    options["config"].update(max_memory_bytes=1048576, batch_size=128, max_target_tokens=1024)
    for row in train + tune:
        row["target_ids"] = [1]+[3]*62+[2]
    with pytest.raises(ValueError, match="memory budget"):
        subject.run_trial(model, train, tune, **options)


def test_distinct_student_is_private_and_dimension_mismatch_rejected():
    teacher, train, tune, options = setup()
    other, *_ = setup(384)
    with pytest.raises(ValueError, match="dimensions differ"):
        subject.run_trial(teacher, train, tune, student=other, **options)
    student = deepcopy(teacher)
    with torch.no_grad():
        student.body.output.bias.add_(.2)
    before = subject.tensor_digest(student)
    result = subject.run_trial(teacher, train, tune, student=student, **options)
    assert subject.tensor_digest(student) == before
    assert result["report"]["initial_student_weights_sha256"] == before


def test_teacher_context_and_optimizer_configuration_do_not_change():
    model, train, tune, options = setup()
    first = subject.run_trial(model, train, tune, **options)
    second = subject.run_trial(model, train, tune, **options)
    assert first["report"]["selected_student_weights_sha256"] == second["report"]["selected_student_weights_sha256"]
    assert first["report"]["optimizer_steps"] == second["report"]["optimizer_steps"] == 2
    assert first["report"]["history"] == second["report"]["history"]


def evaluation_options(options, cap=8):
    return {key: options[key] for key in ("codec", "input_transform", "lineage")} | dict(
        max_target_tokens=cap, max_seconds=10., batch_size=2)


def test_public_evaluation_matches_trial_baseline_and_keeps_model_modes():
    model, train, tune, options = setup()
    before = subject.tensor_digest(model)
    modes = [part.training for part in model.modules()]
    fit = subject.run_trial(model, train, tune, **options)
    measured = subject.evaluate_model(model, tune, **evaluation_options(options))
    assert measured["report"]["metrics"] == fit["report"]["baseline_validation"]
    assert measured["report"]["optimizer_steps"] == 0 and measured["report"]["weight_selection_performed"] is False
    assert before == subject.tensor_digest(model) == measured["report"]["model_weights_sha256"]
    assert modes == [part.training for part in model.modules()]
    assert measured["report"]["complete"]
    assert all(measured["report"][key] is False for key in subject.FALSE)


def test_public_evaluation_of_selected_state_replays_saved_selection():
    model, train, tune, options = setup()
    fit = subject.run_trial(model, train, tune, **options)
    model.load_state_dict(fit["state_dict"], strict=True)
    measured = subject.evaluate_model(model, tune, **evaluation_options(options))
    assert measured["report"]["metrics"] == fit["report"]["selected_validation"]
    assert measured["predictions"] == fit["predictions"]


def test_public_evaluation_generation_does_not_consume_reference_targets():
    model, _, tune, options = setup()
    changed = deepcopy(tune)
    for row in changed:
        row["target_ids"] = [1, 3, 4, 3, 2]
    first = subject.evaluate_model(model, tune, **evaluation_options(options))
    second = subject.evaluate_model(model, changed, **evaluation_options(options))
    for left, right in zip(first["predictions"], second["predictions"]):
        assert {k: v for k, v in left.items() if k != "exact_target"} == {
            k: v for k, v in right.items() if k != "exact_target"}
    assert first["report"]["model_weights_sha256"] == second["report"]["model_weights_sha256"]
    assert first["report"]["validation_rows_sha256"] != second["report"]["validation_rows_sha256"]


@pytest.mark.parametrize("cap", [64, 128, 256, 512, 1024])
def test_public_evaluation_output_caps_do_not_alter_weights_or_context(cap):
    model, _, tune, options = setup()
    # All cap arms deterministically emit EOS on the first generated step.
    with torch.no_grad():
        model.body.output.weight.zero_(); model.body.output.bias.fill_(-10.)
        model.body.output.bias[2] = 10.
    before = subject.tensor_digest(model)
    result = subject.evaluate_model(model, tune, **evaluation_options(options, cap))
    assert result["report"]["max_target_tokens"] == cap
    assert result["report"]["metrics"]["eos_count"] == 2
    assert result["report"]["encoder_context_changed"] is False
    assert subject.tensor_digest(model) == before


def test_public_evaluation_incomplete_deadline_never_reports_partial_quality(monkeypatch):
    model, _, tune, options = setup()
    monkeypatch.setattr(subject, "_evaluate", lambda *args: None)
    result = subject.evaluate_model(model, tune, **evaluation_options(options))
    assert result["report"]["complete"] is False
    assert result["report"]["metrics"] is None and result["predictions"] == []
    assert result["report"]["spans_per_wall_second"] is None


@pytest.mark.parametrize("key,value,reason", [
    ("exact_targets", 1, "exact_targets_below_baseline"),
    ("eos_count", 1, "eos_count_below_baseline"),
    ("output_limit_count", 1, "output_limit_count_above_baseline"),
    ("invalid_special_token_count", 1, "invalid_special_token_count_above_baseline"),
    ("reconstructed_input_mse", .1001, "reconstructed_input_mse_above_baseline"),
])
def test_lower_ce_cannot_win_by_regressing_baseline_generation_or_reconstruction(key, value, reason):
    baseline = dict(token_cross_entropy=1., exact_targets=2, eos_count=2,
        output_limit_count=0, invalid_special_token_count=0, reconstructed_input_mse=.1)
    candidate = {**baseline, "token_cross_entropy": .9, key: value}
    accepted, reasons = subject._selection(candidate, baseline, baseline, subject._config(None))
    assert not accepted and reasons == [reason]
    accepted, reasons = subject._selection(candidate, baseline, baseline,
        subject._config(dict(selection_policy="ce_only_diagnostic")))
    assert accepted and reasons == []


def test_selection_records_overlapping_failures_and_requires_strict_ce_progress():
    baseline = dict(token_cross_entropy=1., exact_targets=2, eos_count=2,
        output_limit_count=0, invalid_special_token_count=0, reconstructed_input_mse=.1)
    candidate = {**baseline, "exact_targets": 0, "eos_count": 0, "output_limit_count": 2}
    accepted, reasons = subject._selection(candidate, baseline, baseline, subject._config(None))
    assert not accepted and set(reasons) == {"reference_ce_not_improved", "exact_targets_below_baseline",
        "eos_count_below_baseline", "output_limit_count_above_baseline"}
    candidate = {**baseline, "token_cross_entropy": .9, "reconstructed_input_mse": .1000001}
    assert subject._selection(candidate, baseline, baseline, subject._config(None)) == (True, [])


def test_deadline_after_state_copy_cannot_commit_candidate(monkeypatch):
    model, train, tune, options = setup()
    baseline = dict(token_cross_entropy=1., exact_targets=0, eos_count=0, count=2,
        output_limit_count=2, invalid_special_token_count=0, reconstructed_input_mse=.1,
        predictions=[], complete=True)
    clock = [0.]
    evaluations = []
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    def observe(*args):
        evaluations.append(1)
        if len(evaluations) == 1:
            return deepcopy(baseline)
        clock[0] = options["config"]["max_seconds"] + 1.
        return {**baseline, "token_cross_entropy": .5}
    monkeypatch.setattr(subject, "_evaluate", observe)
    result = subject.run_trial(model, train, tune, **options)
    assert result["report"]["selected_epoch"] == 0
    assert result["report"]["selected_student_weights_sha256"] == subject.tensor_digest(model)
    assert result["report"]["stopped_reason"] == "deadline_before_selection_commit"
    assert result["report"]["history"][0]["accepted"] is False
    assert result["report"]["history"][0]["rejection_reasons"] == ["deadline_before_selection_commit"]


def test_nonregression_also_preserves_previously_earned_exactness():
    baseline = dict(token_cross_entropy=1., exact_targets=0, eos_count=0,
        output_limit_count=2, invalid_special_token_count=0, reconstructed_input_mse=.1)
    selected = {**baseline, "token_cross_entropy": .9, "exact_targets": 2, "eos_count": 2, "output_limit_count": 0}
    candidate = {**baseline, "token_cross_entropy": .8, "exact_targets": 1, "eos_count": 1, "output_limit_count": 1}
    accepted, reasons = subject._selection(candidate, baseline, selected, subject._config(None))
    assert not accepted and set(reasons) == {"exact_targets_below_selected", "eos_count_below_selected",
        "output_limit_count_above_selected"}


def test_cumulative_curriculum_keeps_adam_moments_and_fixed_validation():
    model, train, tune, options = setup()
    plan = [dict(name="short", training_ids=[train[0]["id"]], epochs=1),
        dict(name="short_and_long", training_ids=[row["id"] for row in train], epochs=1)]
    result = subject.run_trial(model, train, tune, curriculum=plan, **options)
    report = result["report"]
    assert report["config"]["epochs"] == 2 and report["optimizer_steps"] == 2
    assert report["training_row_presentations"] == 3
    assert report["optimizer_instance_count"] == 1 and report["optimizer_reinitialized_between_stages"] is False
    first, second = report["stage_reports"]
    assert first["status"] == second["status"] == "complete"
    assert first["optimizer_state_start"]["parameter_steps"] == {}
    assert first["optimizer_state_end"] == second["optimizer_state_start"]
    assert set(first["optimizer_state_end"]["parameter_steps"].values()) == {1}
    assert set(second["optimizer_state_end"]["parameter_steps"].values()) == {2}
    assert [row["validation"]["count"] for row in report["history"]] == [2, 2]
    assert [row["stage"] for row in report["history"]] == ["short", "short_and_long"]


@pytest.mark.parametrize("plan,reason", [
    ([], "nonempty curriculum"),
    ([dict(name="short", training_ids=["train-0"], epochs=1)], "include all training"),
    ([dict(name="bad", training_ids=["test-0"], epochs=1)], "existing unique"),
    ([dict(name="bad", training_ids=["train-0", "train-0"], epochs=1)], "existing unique"),
    ([dict(name="all", training_ids=["train-0", "train-1"], epochs=1),
      dict(name="regress", training_ids=["train-0"], epochs=1)], "cumulative"),
    ([dict(name="same", training_ids=["train-0"], epochs=1),
      dict(name="same", training_ids=["train-0", "train-1"], epochs=1)], "unique bounded stage"),
    ([dict(name="all", training_ids=["train-0", "train-1"], epochs=True)], "epoch count"),
])
def test_curriculum_rejects_new_rows_resetting_coverage_and_ambiguous_stages(plan, reason):
    model, train, tune, options = setup()
    with pytest.raises(ValueError, match=reason):
        subject.run_trial(model, train, tune, curriculum=plan, **options)


def test_curriculum_step_limit_keeps_unstarted_stages_visible():
    model, train, tune, options = setup()
    options["config"]["max_optimizer_steps"] = 1
    plan = [dict(name="short", training_ids=[train[0]["id"]], epochs=1),
        dict(name="long", training_ids=[row["id"] for row in train], epochs=1)]
    report = subject.run_trial(model, train, tune, curriculum=plan, **options)["report"]
    assert report["stopped_reason"] == "optimizer_step_limit"
    assert report["stage_reports"][1]["status"] == "not_started"
    assert report["stage_reports"][1]["optimizer_steps"] == 0


def test_frozen_projection_names_and_exact_verification_are_reported():
    model, train, tune, options = setup()
    for name, parameter in model.named_parameters():
        if "projection_" in name:
            parameter.requires_grad_(False)
    result = subject.run_trial(model, train, tune, **options)
    report = result["report"]
    assert len(report["frozen_parameter_names"]) == 4
    assert all("projection_" in name for name in report["frozen_parameter_names"])
    assert report["frozen_student_parameters_verified"]
    for name in report["frozen_parameter_names"]:
        assert torch.equal(result["state_dict"][name], model.state_dict()[name])
    assert report["baseline_validation"]["reconstructed_input_mse"] == report["selected_validation"]["reconstructed_input_mse"]


@pytest.mark.parametrize("bias,scale,reason", [(1e38, 1e8, "reconstructed raw input"),
    (1e19, 1., "reconstruction reduction")])
def test_finite_tensor_inputs_cannot_produce_infinite_report_values(bias, scale, reason):
    model, _, tune, options = setup()
    with torch.no_grad():
        model.body.projection_up.weight.zero_()
        model.body.projection_up.bias.fill_(bias)
    options["input_transform"].update(mode="center_rms", scale=scale)
    with pytest.raises(ValueError, match=reason):
        subject.evaluate_model(model, tune, **evaluation_options(options))
