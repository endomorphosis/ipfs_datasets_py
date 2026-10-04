"""Synthetic count-loss integration controls; no corpus or proof evidence."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as adapter
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as conditioning
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as fidelity
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_decoder_training as previous
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_cardinality_training as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def validate_rule(value):
    """Test grammar only, deliberately without source/native authority."""
    rules = value.get("rules") if type(value) is dict else None
    valid = type(rules) is list and len(rules) == 1
    if valid:
        rule = rules[0]
        valid = (type(rule) is dict and set(rule) == set(fidelity.FACETS)
            and all(type(rule[field]) is str for field in fidelity.FACETS[:4])
            and rule["modality"] in ("O", "P", "F")
            and all(type(rule[field]) is list and all(type(item) is str for item in rule[field])
                    for field in fidelity.FACETS[4:]))
    return {"valid": valid, "scope": "synthetic-only"}


def setup(*, guide=False, conditioning_mode="every_step"):
    first = dict(actor="officer", action="retain", object="file", modality="O",
                 conditions=[], exceptions=[], temporal=[])
    second = dict(first, actor="agency", action="disclose", modality="F", conditions=["requested"])
    targets = [{"rules": [first]}, {"rules": [first, second]}]
    vocabulary = ["<pad>", "<bos>", "<eos>"]+sorted({token for target in targets
        for token, _ in previous._tokens(target, semantic=False)})
    codec = dict(schema="synthetic-count-lexical/v1", target_vocabulary=vocabulary)
    raw = numerical._model({"dimension": 8}, codec,
        dict(seed=2026, projection_width=2, hidden_size=8, token_embedding_dim=8))
    for name, parameter in raw.named_parameters():
        if "projection_down" in name or "projection_up" in name:
            parameter.requires_grad_(False)
    base = conditioning.bind_persistent_model(raw, dimension=8, conditioning=conditioning_mode)
    model = adapter.bind_cardinality_model(base, codec=codec, guide_boundary=guide)
    def make_rows(split):
        rows, references = [], []
        for index, target in enumerate(targets):
            identity = split+"-"+str(index)
            source = split+" authored synthetic paragraph "+str(index)
            ids = [1]+[vocabulary.index(token) for token, _ in previous._tokens(target, semantic=False)]+[2]
            rows.append(dict(id=identity, source_text=source, input=[.2+index*.3]+[0.]*7, target_ids=ids))
            references.append(dict(id=identity, source_text=source, target=deepcopy(target), clause_count=index+1))
        return rows, references
    train, train_refs = make_rows("train")
    tune, tune_refs = make_rows("validation")
    options = dict(training_references=train_refs, validation_references=tune_refs, codec=codec,
        input_transform=dict(mode="none", origin="training_only", mean=[0.]*8, scale=1.),
        lineage=dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=core.digest(codec),
            input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic-count-test",
            student_lineage="private-count-learner", teacher_output_limit=128, student_role="learned_formula_sidecar"),
        validate_rule=validate_rule, validator_id="synthetic-count-validator/v1",
        curriculum=[dict(name="short", training_ids=[train[0]["id"]], epochs=1),
                    dict(name="cumulative", training_ids=[row["id"] for row in train], epochs=1)],
        config=dict(epochs=2, max_optimizer_steps=4, batch_size=2, max_target_tokens=128,
                    max_seconds=20., validation_interval=1, learning_rate=.001))
    return model, base, train, tune, options


def evaluated(options, *, ce=2., mse=.001, count_ce=2., mutate=None):
    predictions = []
    for reference in options["validation_references"]:
        target = deepcopy(reference["target"])
        if mutate:
            mutate(target)
        ids = [options["codec"]["target_vocabulary"].index(token)
               for token, _ in previous._tokens(target, semantic=False)]
        predictions.append(dict(id=reference["id"], token_ids=ids, eos_reached=True, generation_status="eos"))
    report = fidelity.score_predictions(options["validation_references"], predictions,
        codec=options["codec"], validate_rule=validate_rule, output_limit=128,
        validator_id=options["validator_id"])
    return dict(numerical=dict(token_cross_entropy=ce, reconstructed_input_mse=mse, complete=True),
                fidelity=report, predictions=predictions, source_count=dict(rows=len(predictions),
                    cross_entropy=count_ce, used_for_selection=False,
                    reference_count_supplied_to_generation=False))


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
@pytest.mark.parametrize("conditioning_mode", ["first_step", "every_step"])
def test_zero_aux_guide_off_exactly_preserves_old_training_and_shared_updates(strategy, conditioning_mode):
    model, base, train, tune, options = setup(conditioning_mode=conditioning_mode)
    legacy = previous.train(base, train, tune, strategy=strategy, **options)
    actual = subject.train(model, train, tune, cardinality_weight=0., strategy=strategy, **options)
    for name, value in legacy["state_dict"].items():
        assert torch.equal(value, actual["state_dict"]["body."+name]), name
    assert torch.count_nonzero(actual["state_dict"]["count_head.weight"]) == 0
    assert torch.count_nonzero(actual["state_dict"]["count_head.bias"]) == 0
    assert legacy["predictions"] == actual["predictions"]
    for key in ("optimizer_steps", "row_presentations", "valid_target_token_presentations", "selected_epoch", "stopped_reason"):
        assert legacy["report"][key] == actual["report"][key]
    for left, right in zip(legacy["report"]["history"], actual["report"]["history"]):
        for key in ("mean_minibatch_ce", "mean_minibatch_weighted_ce", "mean_minibatch_raw_reconstruction_mse",
                    "accepted", "rejection_reasons", "selected_epoch"):
            assert left[key] == right[key]
    if legacy["last_complete_attempt_state_dict"] is not None:
        for name, value in legacy["last_complete_attempt_state_dict"].items():
            assert torch.equal(value, actual["last_complete_attempt_state_dict"]["body."+name]), name


def test_zero_aux_guide_off_does_not_create_count_gradients_or_adam_state(monkeypatch):
    model, _, train, tune, options = setup()
    copies, observations = [], []
    original_copy, original_step = subject.deepcopy, torch.optim.AdamW.step
    def capture_copy(value):
        result = original_copy(value)
        if isinstance(value, torch.nn.Module):
            copies.append(result)
        return result
    def checked_step(optimizer, *args, **kwargs):
        assert len(copies) == 1
        head = copies[0].count_head
        assert head.weight.grad is None and head.bias.grad is None
        result = original_step(optimizer, *args, **kwargs)
        assert head.weight not in optimizer.state and head.bias not in optimizer.state
        observations.append(1)
        return result
    monkeypatch.setattr(subject, "deepcopy", capture_copy)
    monkeypatch.setattr(torch.optim.AdamW, "step", checked_step)
    result = subject.train(model, train, tune, cardinality_weight=0., **options)
    assert len(observations) == result["report"]["optimizer_steps"] == 2
    assert all(row["mean_minibatch_count_ce"] > 0 for row in result["report"]["history"])
    assert result["report"]["baseline"]["source_count"]["cross_entropy"] > 0


@pytest.mark.parametrize("strategy", ["reference_ce", "semantic_fields"])
def test_zero_aux_repeated_clipped_updates_remain_exactly_equal_to_previous_owner(strategy, monkeypatch):
    model, base, train, tune, options = setup()
    options["curriculum"] = [dict(name="repeated-clipped", training_ids=[row["id"] for row in train], epochs=128)]
    options["config"].update(epochs=128, max_optimizer_steps=128, max_grad_norm=.005,
                             validation_interval=128, patience=0)
    clip_norms = []
    original_clip = torch.nn.utils.clip_grad_norm_
    def capture_clip(*args, **kwargs):
        norm = original_clip(*args, **kwargs)
        clip_norms.append(float(norm))
        return norm
    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", capture_clip)
    legacy = previous.train(base, train, tune, strategy=strategy, **options)
    actual = subject.train(model, train, tune, cardinality_weight=0., strategy=strategy, **options)
    assert legacy["report"]["optimizer_steps"] == actual["report"]["optimizer_steps"] == 128
    assert len(clip_norms) == 256 and all(norm > .005 for norm in clip_norms)
    assert clip_norms[:128] == clip_norms[128:]
    for field in ("state_dict", "last_complete_attempt_state_dict"):
        assert legacy[field] is not None and actual[field] is not None
        for name, tensor in legacy[field].items():
            assert torch.equal(tensor, actual[field]["body."+name]), (field, name)
        assert not actual[field]["count_head.weight"].any()
        assert not actual[field]["count_head.bias"].any()
    assert legacy["predictions"] == actual["predictions"]
    assert legacy["last_complete_attempt_predictions"] == actual["last_complete_attempt_predictions"]
    for old, new in zip(legacy["report"]["history"], actual["report"]["history"]):
        assert old["mean_minibatch_ce"] == new["mean_minibatch_ce"]
        assert old["mean_minibatch_weighted_ce"] == new["mean_minibatch_weighted_ce"]
        assert old["rejection_reasons"] == new["rejection_reasons"]


@pytest.mark.parametrize("guide", [False, True])
def test_positive_count_aux_updates_head_without_mutating_caller_or_frozen_projection(guide):
    model, _, train, tune, options = setup(guide=guide)
    before = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    inputs = deepcopy((train, tune, options))
    frozen = {name: parameter.detach().clone() for name, parameter in model.named_parameters()
              if not parameter.requires_grad}
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    assert core.tensor_digest(model) == before
    assert modes == {name: module.training for name, module in model.named_modules()}
    assert (train, tune, options) == inputs
    assert all(parameter.grad is None for parameter in model.parameters())
    last = result["last_complete_attempt_state_dict"]
    assert last is not None and torch.count_nonzero(last["count_head.weight"]) > 0
    assert torch.count_nonzero(last["count_head.bias"]) > 0
    replay = deepcopy(model)
    replay.load_state_dict(last, strict=True)
    assert result["report"]["last_complete_attempt_weights_sha256"] == core.tensor_digest(replay)
    replay.load_state_dict(result["state_dict"], strict=True)
    assert result["report"]["selected_weights_sha256"] == core.tensor_digest(replay)
    assert all(torch.equal(last[name], value) for name, value in frozen.items())
    assert all(torch.equal(result["state_dict"][name], value) for name, value in frozen.items())
    assert result["report"]["frozen_parameters_verified"]
    assert result["report"]["optimizer_steps"] == 2
    assert all(result["report"][name] is False for name in subject.FALSE)
    # Keep complete final diagnostic rows, but do not multiply those rows by
    # every training epoch in the history record.
    assert len(result["report"]["baseline"]["source_count"]["predictions"]) == len(tune)
    assert len(result["report"]["last_complete_attempt"]["source_count"]["predictions"]) == len(tune)
    assert all("predictions" not in row["source_count"] for row in result["report"]["history"])


def test_count_cross_entropy_gradient_reaches_shared_initial_conditioner_after_head_learns():
    model, _, train, _, options = setup()
    data, _ = core._batch(torch, train, options["input_transform"])
    targets = torch.tensor([row["clause_count"]-1 for row in options["training_references"]])
    projected = model.project(data)
    logits = model.count_logits(projected)
    assert logits.shape == (2, 32) and not logits.any()
    loss = torch.nn.functional.cross_entropy(logits, targets)
    loss.backward()
    assert model.count_head.weight.grad.abs().sum() > 0
    assert model.count_head.bias.grad.abs().sum() > 0
    optimizer = torch.optim.AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=.01)
    optimizer.step(); optimizer.zero_grad(set_to_none=True)
    torch.nn.functional.cross_entropy(model.count_logits(model.project(data)), targets).backward()
    shared = [(name, parameter.grad) for name, parameter in model.body.body.named_parameters()
              if parameter.requires_grad and parameter.grad is not None]
    assert any(gradient.abs().sum() > 0 for _, gradient in shared)
    assert all(parameter.grad is None for name, parameter in model.named_parameters()
               if "projection_down" in name or "projection_up" in name)


def test_single_adam_moments_survive_cumulative_count_training():
    model, _, train, tune, options = setup()
    result = subject.train(model, train, tune, cardinality_weight=.25, **options)
    report = result["report"]
    left, right = report["stage_reports"]
    assert left["optimizer_state_end"] == right["optimizer_state_start"]
    assert left["optimizer_state_start"] != left["optimizer_state_end"]
    assert right["optimizer_state_start"] != right["optimizer_state_end"]
    assert (left["optimizer_step_start"], left["optimizer_step_end"], right["optimizer_step_end"]) == (0, 1, 2)
    assert report["optimizer_instance_count"] == 1 and not report["optimizer_reinitialized_between_stages"]
    assert report["row_presentations"] == 3
    assert report["valid_target_token_presentations"] == 2*(len(train[0]["target_ids"])-1)+len(train[1]["target_ids"])-1


@pytest.mark.parametrize("weight", [-.1, 1.1, float("nan"), float("inf"), True, "0.2", None])
def test_cardinality_weight_must_be_explicit_finite_bounded_number(weight):
    model, _, train, tune, options = setup()
    with pytest.raises(ValueError, match="cardinality"):
        subject.train(model, train, tune, cardinality_weight=weight, **options)


@pytest.mark.parametrize("bad_count", [0, 33, True, 1., "1", None, float("nan"), float("inf")])
def test_count_labels_are_exact_positive_integers_bound_to_complete_rules(bad_count):
    model, _, train, tune, options = setup()
    options["training_references"][0]["clause_count"] = bad_count
    with pytest.raises(ValueError):
        subject.train(model, train, tune, cardinality_weight=.5, **options)


@pytest.mark.parametrize("references", [None, {}, [], [None],
    [dict(id="sample", clause_count=1, target={})],
    [dict(id="sample", clause_count=1, target={"rules": "not an array"})]])
def test_count_label_helper_refuses_malformed_reference_shape(references):
    with pytest.raises(ValueError, match="count"):
        subject._count_labels(references)


def test_reference_order_does_not_change_row_bound_count_labels():
    model, _, train, tune, options = setup()
    reordered = deepcopy(options)
    reordered["training_references"].reverse()
    left = subject.train(model, train, tune, cardinality_weight=.5, **options)
    right = subject.train(model, train, tune, cardinality_weight=.5, **reordered)
    assert all(torch.equal(value, right["state_dict"][name]) for name, value in left["state_dict"].items())
    assert all(torch.equal(value, right["last_complete_attempt_state_dict"][name])
               for name, value in left["last_complete_attempt_state_dict"].items())


def test_count_predictions_and_generation_do_not_receive_reference_counts_or_targets():
    model, _, _, tune, options = setup(guide=True)
    with torch.no_grad():
        model.count_head.bias[1] = 2.
        model.count_head.weight[0].fill_(.1)
    before = core.tensor_digest(model)
    changed = deepcopy(tune)
    for row in changed:
        row["source_text"] = "changed provenance "+row["id"]
        row["target_ids"] = [1]+list(reversed(row["target_ids"][1:-1]))+[2]
    config = core._config(options["config"])
    original = core._evaluate(torch, model, tune, options["input_transform"], config,
                              len(options["codec"]["target_vocabulary"]), time.monotonic()+20.)
    alternative = core._evaluate(torch, model, changed, options["input_transform"], config,
                                 len(options["codec"]["target_vocabulary"]), time.monotonic()+20.)
    for first, second in zip(original["predictions"], alternative["predictions"]):
        for key in ("token_ids", "generation_status", "eos_reached", "reconstructed_input"):
            assert first[key] == second[key]
    data, _ = core._batch(torch, tune, options["input_transform"])
    first = model.count_logits(model.project(data))
    second = model.start(model.project(data))[3]
    assert torch.equal(first, second)
    assert core.tensor_digest(model) == before


def test_zero_condition_ablation_removes_both_source_lanes_and_count_features():
    model, _, train, _, options = setup(guide=True)
    with torch.no_grad():
        model.count_head.weight.fill_(.2)
        model.count_head.bias.copy_(torch.linspace(0., 1., 32))
        model.body.source_to_embedding.weight.fill_(.3)
    ablation = adapter.bind_zero_condition_model(model)
    data, labels = core._batch(torch, train, options["input_transform"])
    projected = ablation.project(data)
    state = ablation.start(projected)
    assert not state[0].any() and not state[1].any()
    assert torch.equal(state[3][0], state[3][1])
    assert torch.equal(state[3][0], model.count_head.bias)
    assert torch.equal(ablation.count_logits(projected), state[3])
    # Both sequences consume the SAME observed prefix; distinct source vectors
    # cannot alter count or token outputs after the complete source ablation.
    prefix = labels[0:1, :-1].repeat(2, 1)
    logits, _ = ablation.next_logits(prefix, state)
    assert torch.equal(logits[0], logits[1])
    assert torch.equal(projected, model.project(data))


def test_optimizer_limit_prevents_incomplete_epoch_selection():
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="all", training_ids=[row["id"] for row in train], epochs=1)]
    options["config"].update(batch_size=1, max_optimizer_steps=1)
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 1 and report["selected_epoch"] == 0
    assert report["stopped_reason"] == "optimizer_step_limit"
    assert not report["history"][0]["complete_epoch"]
    assert result["last_complete_attempt_state_dict"] is None
    assert report["last_complete_attempt_weights_sha256"] is None


def test_model_without_count_head_is_not_silently_accepted():
    _, base, train, tune, options = setup()
    with pytest.raises(ValueError, match="count"):
        subject.train(base, train, tune, cardinality_weight=.5, **options)


def test_first_real_update_equals_independent_full_token_plus_count_objective():
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="all", training_ids=[row["id"] for row in train], epochs=1)]
    config = core._config(options["config"])
    manual = deepcopy(model)
    parameters = [parameter for parameter in manual.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config["learning_rate"],
                                 weight_decay=config["weight_decay"], foreach=False)
    permutation = torch.randperm(len(train), generator=torch.Generator().manual_seed(config["seed"])).tolist()
    batch = [train[index] for index in permutation]
    data, labels = core._batch(torch, batch, options["input_transform"])
    projected, logits = core._logits(torch, manual, data, labels[:, :-1], len(options["codec"]["target_vocabulary"]))
    reference_ce = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
        ignore_index=0, reduction="sum")/(labels[:, 1:] != 0).sum()
    by_id = {row["id"]: len(row["target"]["rules"])-1 for row in options["training_references"]}
    count_ce = torch.nn.functional.cross_entropy(manual.count_logits(projected),
        torch.tensor([by_id[row["id"]] for row in batch]))
    mse = (projected-data).square().mean()*options["input_transform"]["scale"]**2
    objective = reference_ce+config["reconstruction_weight"]*mse+.5*count_ce
    objective.backward()
    torch.nn.utils.clip_grad_norm_(parameters, config["max_grad_norm"], error_if_nonfinite=True)
    optimizer.step()
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    last = result["last_complete_attempt_state_dict"]
    assert last is not None
    for name, tensor in manual.state_dict().items():
        assert torch.equal(tensor, last[name]), name
    history = result["report"]["history"][0]
    assert history["mean_minibatch_count_ce"] == pytest.approx(count_ce.item(), abs=1e-7)
    # The fused sum and unreduced-then-sum kernels may round their reductions
    # differently; the complete actual parameter update above remains exact.
    assert history["mean_minibatch_ce"] == pytest.approx(reference_ce.item(), abs=5e-7)


def test_count_only_progress_does_not_select_weights(monkeypatch):
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="all", training_ids=[row["id"] for row in train], epochs=1)]
    values = iter([evaluated(options, count_ce=2.), evaluated(options, count_ce=.01)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(values))
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    report = result["report"]
    assert report["selected_epoch"] == 0
    assert report["selected_weights_sha256"] == core.tensor_digest(model)
    assert report["last_complete_attempt"]["source_count"]["cross_entropy"] == .01
    diagnostic = deepcopy(model)
    diagnostic.load_state_dict(result["last_complete_attempt_state_dict"], strict=True)
    assert report["last_complete_attempt_weights_sha256"] == core.tensor_digest(diagnostic)
    assert report["last_complete_attempt_weights_sha256"] != report["selected_weights_sha256"]
    assert "no_fidelity_or_reference_ce_progress" in report["history"][0]["rejection_reasons"]
    assert not report["count_metrics_used_for_selection"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda target: target["rules"][0].update(modality="F"), "modality"),
    (lambda target: target["rules"][0].update(actor="agency"), "actor"),
    (lambda target: target["rules"].reverse(), "ordered_exact"),
    (lambda target: target["rules"].pop() if len(target["rules"]) > 1 else None, "whole_rules_missing"),
])
def test_better_count_and_token_loss_cannot_override_per_length_source_regressions(monkeypatch, mutation, reason):
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="all", training_ids=[row["id"] for row in train], epochs=1)]
    values = iter([evaluated(options, ce=2., count_ce=2.),
                   evaluated(options, ce=.1, count_ce=.01, mutate=mutation)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(values))
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    report = result["report"]
    assert report["selected_epoch"] == 0 and report["optimizer_steps"] == 1
    assert report["selected_weights_sha256"] == core.tensor_digest(model)
    assert any(reason in item for item in report["history"][0]["rejection_reasons"])
    assert result["predictions"] != result["last_complete_attempt_predictions"]


def test_better_count_cannot_override_reconstruction_regression(monkeypatch):
    model, _, train, tune, options = setup()
    options["curriculum"] = [dict(name="all", training_ids=[row["id"] for row in train], epochs=1)]
    values = iter([evaluated(options, ce=2., mse=.001, count_ce=2.),
                   evaluated(options, ce=.1, mse=.1, count_ce=.01)])
    monkeypatch.setattr(subject, "_evaluate", lambda *args: next(values))
    report = subject.train(model, train, tune, cardinality_weight=.5, **options)["report"]
    assert report["selected_epoch"] == 0
    assert "initial_reconstruction_regression" in report["history"][0]["rejection_reasons"]


@pytest.mark.parametrize("bad_logits", [
    lambda value: torch.zeros(len(value), 31),
    lambda value: torch.zeros(len(value), 32, dtype=torch.float64),
    lambda value: torch.full((len(value), 32), float("nan")),
    lambda value: [[0.]*32 for _ in value],
])
def test_invalid_count_output_cannot_enter_losses_or_evidence(monkeypatch, bad_logits):
    model, _, train, tune, options = setup()
    monkeypatch.setattr(type(model), "count_logits", lambda self, projected: bad_logits(projected))
    with pytest.raises(ValueError, match="32-class count logits"):
        subject.train(model, train, tune, cardinality_weight=.5, **options)


def test_count_evaluation_receipt_is_complete_row_bound_and_diagnostic():
    model, _, _, tune, options = setup()
    config = core._config(options["config"])
    before = core.tensor_digest(model)
    report = subject._count_evaluation(torch, model, tune,
        list(reversed(options["validation_references"])), options["input_transform"], config,
        time.monotonic()+20.)
    assert report["rows"] == 2 and report["correct"] == 1
    assert report["cross_entropy"] == pytest.approx(torch.tensor(32.).log().item())
    assert report["predictions"] == [dict(id=tune[0]["id"], expected=1, predicted=1),
                                      dict(id=tune[1]["id"], expected=2, predicted=1)]
    assert report["by_length"] == {"1": dict(rows=1, correct=1, absolute_error=0),
                                    "2": dict(rows=1, correct=0, absolute_error=1)}
    assert report["source_only_head"] and not report["used_for_selection"]
    assert not report["reference_count_supplied_to_generation"]
    assert core.tensor_digest(model) == before


def test_count_evaluation_deadline_invalidates_otherwise_complete_validation(monkeypatch):
    model, _, train, tune, options = setup()
    original = subject._count_evaluation
    calls = []
    def bounded(*args):
        calls.append(1)
        return original(*args) if len(calls) == 1 else None
    monkeypatch.setattr(subject, "_count_evaluation", bounded)
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    report = result["report"]
    assert len(calls) == 2 and report["selected_epoch"] == 0
    assert report["stopped_reason"] == "deadline_during_validation"
    assert report["history"][0]["rejection_reasons"] == ["incomplete_validation"]
    assert report["selected_weights_sha256"] == core.tensor_digest(model)
    assert result["last_complete_attempt_state_dict"] is None
    assert report["last_complete_attempt_weights_sha256"] is None


def test_no_complete_count_baseline_means_no_training_or_validated_selection(monkeypatch):
    model, _, train, tune, options = setup()
    monkeypatch.setattr(subject, "_count_evaluation", lambda *args: None)
    result = subject.train(model, train, tune, cardinality_weight=.5, **options)
    report = result["report"]
    assert report["optimizer_steps"] == 0 and report["selected_epoch"] is None
    assert report["baseline"] is None and report["selected"] is None
    assert result["predictions"] == []
    assert result["last_complete_attempt_state_dict"] is None
    assert report["last_complete_attempt_weights_sha256"] is None
    assert report["exported_state_role"] == "unvalidated_initial_state"
    assert report["stopped_reason"] == "deadline_before_complete_baseline"


def test_late_complete_evaluation_still_cannot_commit_selection(monkeypatch):
    model, _, train, tune, options = setup()
    clock, calls = [0.], []
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    def evaluate(*args):
        calls.append(1)
        result = evaluated(options, ce=2. if len(calls) == 1 else .1)
        if len(calls) == 2:
            clock[0] = 21.
        return result
    monkeypatch.setattr(subject, "_evaluate", evaluate)
    report = subject.train(model, train, tune, cardinality_weight=.5, **options)["report"]
    assert report["selected_epoch"] == 0 and report["optimizer_steps"] == 1
    assert report["stopped_reason"] == "deadline_before_selection_commit"


def test_memory_preflight_still_occurs_before_model_copy(monkeypatch):
    model, _, train, tune, options = setup()
    options["config"].update(batch_size=128, max_memory_bytes=1048576)
    original = subject.deepcopy
    def checked(value):
        assert not isinstance(value, torch.nn.Module), "model copied before memory admission"
        return original(value)
    monkeypatch.setattr(subject, "deepcopy", checked)
    with pytest.raises(ValueError, match="trial tensor work exceeds budget"):
        subject.train(model, train, tune, cardinality_weight=.5, **options)
