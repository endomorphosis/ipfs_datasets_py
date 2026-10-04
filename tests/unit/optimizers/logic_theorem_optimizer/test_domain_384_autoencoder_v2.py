"""Real numerical v2 tests on synthetic vectors and a tiny trained parent.

These vectors are test fixtures, not verified semantic embeddings. No result
here supplies Lake evidence, source fidelity, or production qualification.
"""
from copy import deepcopy
import hashlib

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v2 as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal


@pytest.fixture(scope="module")
def parent():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain="legal_ir", lineage_id="current_legal_v2", dimension=384,
            runtime_profile="unit-test-authored/v1", core_sha256="a" * 64)
        rows = [dict(id="legal-training", source_text="The agency must save the report.",
            latent=[.5] + [0.] * 383, embedding=[.3] + [0.] * 383,
            canonical_ir={"rules": [dict(modality="O", actor="agency", action="save", object="report",
                conditions=[], exceptions=[], temporal=[])]})]
        initial = legal.build_checkpoint(binding, rows, [], hidden_size=16,
            token_embedding_dim=8, projection_width=4, batch_size=1)
        return legal.train(initial, rows, [], epochs=1, max_seconds=30)["checkpoint"]
    finally:
        torch.set_num_threads(previous)


def target(domain):
    if domain == "intent_ir":
        return dict(kind="intent_rich_ast", document=dict(kind="atom", actor="operator", action="save",
            object="report", modality="required"))
    if domain == "ui_ux_ir":
        return dict(kind="ui_component", document=dict(component_id="submit", role="button"))
    return dict(kind="program_expression", document=dict(expression_id="expr:one", kind="literal",
        type_ref="integer", attributes={"value": 1}, source_ref_ids=["authored-source"]))


def rows(domain, split):
    values = [.4, .6] if split == "train" else [.8]
    return [dict(id=f"{split}-{index}", source_text=f"{split} authored source {index}",
        embedding=[value, .01 * index] + [0.] * 382, target=target(domain))
        for index, value in enumerate(values)]


def fit(parent, *, domain="intent_ir", **config):
    options = dict(epochs=3, batch_size=1, max_seconds=30, eval_interval=1, patience=3)
    options.update(config)
    return api.train(domain, rows(domain, "train"), rows(domain, "validation"),
        parent_projection=parent, config=options)


@pytest.fixture(scope="module", params=api.DOMAINS)
def trained(request, parent):
    before = deepcopy(parent)
    result = fit(parent, domain=request.param)
    assert parent == before
    return result["checkpoint"]


def inference_rows(domain):
    return [{key: value for key, value in row.items() if key != "target"}
        for row in rows(domain, "validation")]


def test_real_training_new_lineage_preserves_parent_and_context_limit(trained):
    runtime = api.Runtime(trained)
    assert runtime.describe()["schema"] == api.SCHEMA != base.SCHEMA
    assert trained["config"]["max_target_tokens"] == trained["parent_context_limit"] == 64
    assert trained["config"]["source_conditioning"] == "none"
    assert trained["config"]["scalar_value_weight"] == 8.
    assert trained["lineage"]["random_parameters_used"] is False
    assert trained["lineage"]["parent_modified"] is False
    assert trained["training"]["optimizer_steps"] == 6
    assert trained["training"]["test_used_for_selection"] is False
    assert all(trained[key] is False for key in api.FALSE)
    assert runtime.describe()["embedding_provenance_verified_by_runtime"] is False
    assert not runtime.describe()["sample_memory_used"]
    with pytest.raises(ValueError, match="closed domain checkpoint"):
        base.Runtime(trained)


def test_target_free_inference_depends_on_embedding_not_provenance_text(trained):
    runtime = api.Runtime(trained)
    inputs = inference_rows(trained["domain_id"])
    previous = torch.get_num_threads()
    predicted = runtime.infer(inputs)["rows"][0]
    assert torch.get_num_threads() == previous
    changed = deepcopy(inputs); changed[0]["source_text"] = "Changed provenance, identical embedding."
    other = runtime.infer(changed)["rows"][0]
    for key in ("candidate_ir", "generated_tokens", "reconstructed_embedding", "status"):
        assert predicted[key] == other[key]
    assert predicted["source_sha256"] != other["source_sha256"]
    assert predicted["target_access"] is False and predicted["teacher_forcing"] is False
    assert all(predicted[key] is False for key in api.FALSE)
    with pytest.raises(ValueError, match="closed domain row"):
        runtime.infer([{**inputs[0], "target": target(trained["domain_id"])}])


def test_weight_ablation_cannot_mutate_runtime_or_fabricate_fallback(trained):
    runtime = api.Runtime(trained)
    inputs = inference_rows(trained["domain_id"])
    before = runtime.infer(inputs)
    zero = runtime.infer(inputs, weight_ablation="zero_decoder")["rows"][0]
    assert zero["candidate_ir"] is None and zero["status"] == "invalid_generated_output"
    assert zero["generated_tokens"] == [] and not zero["ended"]
    assert runtime.infer(inputs) == before


def test_reopen_requires_digest_domain_and_v2_schema(trained, tmp_path):
    raw = api._raw(trained)
    path = tmp_path / "checkpoint.json"; path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    runtime = api.load_checkpoint(path, expected_sha256=digest, expected_domain=trained["domain_id"])
    assert runtime.describe()["dimension"] == 384
    with pytest.raises(ValueError, match="bytes differ"):
        api.load_checkpoint(path, expected_sha256="0" * 64, expected_domain=trained["domain_id"])
    with pytest.raises(ValueError, match="another domain"):
        api.load_checkpoint(path, expected_sha256=digest, expected_domain="legal_ir")
    changed = deepcopy(trained); changed["schema"] = base.SCHEMA
    with pytest.raises(ValueError, match="closed v2"):
        api.Runtime(changed)


def test_selected_generated_metrics_replay_from_saved_runtime(trained):
    evaluated = api.evaluate(trained, rows(trained["domain_id"], "validation"))["fidelity"]
    selected = trained["training"]["selected_validation"]["generated"]
    for key in ("exact_count", "native_valid_count", "field_accuracy", "per_field", "count", "generated_outputs_sha256"):
        assert evaluated[key] == selected[key]
    assert all(row["total"] > 0 for row in evaluated["per_field"].values())


def test_scalar_roles_cover_values_without_removing_keys_structure_eos_or_padding():
    target = {"same": "same", "array": [False, None, 1, 1., {"same": "same"}]}
    aligned = api.fidelity.target_token_alignment(target, scalar_value_weight=8)
    tokens = base._tokens(target)
    assert aligned["tokens"] == tokens
    duplicated = [row for row in aligned["alignment"] if row["token"] == '"same"']
    assert {row["role"] for row in duplicated} == {"key", "scalar_value"}
    assert {row["weight"] for row in duplicated} == {1., 8.}
    weights = api.fidelity.teacher_forcing_weights(target, width=len(tokens) + 3, scalar_value_weight=8)
    assert all(value > 0 for value in weights[:len(tokens) + 1])
    assert weights[-3:] == [1., 0., 0.]
    assert {row["value_type"] for row in aligned["alignment"] if row["role"] == "scalar_value"} >= {
        "string", "boolean", "null", "integer", "number"}


def test_unit_weights_and_no_conditioning_match_original_loss(parent):
    data_rows = rows("intent_ir", "train")
    vocabulary = [*base.SPECIAL, *sorted(set(base._tokens(data_rows[0]["target"])))]
    config = api._config({"scalar_value_weight": 1., "source_conditioning": "none"}, parent["config"])
    with base._cpu() as torch:
        model, _ = base._transfer(parent, {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}, config)
        data, labels = base._batch(torch, data_rows, vocabulary, 64)
        normalizer = api._normalizer(torch, data, "none")
        weights = (labels[:, 1:] != 0).to(dtype=torch.float32)
        actual = api._loss(torch, model, data, labels, weights, config, normalizer)
        original = base._loss(torch, model, data, labels, config)
    for left, right in zip(actual[:3], original):
        assert float(left.detach()) == pytest.approx(float(right.detach()), rel=1e-6, abs=1e-7)
    assert float(actual[1].detach()) == float(actual[3].detach())


def test_normalization_is_training_only_bounded_and_raw_projection_mse_unchanged(parent):
    data_rows = rows("intent_ir", "train")
    vocabulary = [*base.SPECIAL, *sorted(set(base._tokens(data_rows[0]["target"])))]
    config = api._config({}, parent["config"])
    with base._cpu() as torch:
        model, _ = base._transfer(parent, {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}, config)
        data, labels = base._batch(torch, data_rows, vocabulary, 64)
        none, normalized = (api._normalizer(torch, data, mode) for mode in ("none", "train_rms"))
        assert normalized["mean"] == data.mean(0).tolist()
        assert normalized["fitted_rows"] == len(data_rows)
        assert normalized["scale"] >= 1 / 64
        expected_rms = float(((data - data.mean(0)).square().sum(1).mean()).sqrt())
        assert normalized["observed_rms"] == expected_rms
        weights = (labels[:, 1:] != 0).to(dtype=torch.float32)
        a = api._loss(torch, model, data, labels, weights, config, none)
        b = api._loss(torch, model, data, labels, weights, config, normalized)
        assert float(a[2].detach()) == float(b[2].detach())
        constant = api._normalizer(torch, torch.ones((2, 384)), "train_rms")
        assert constant["scale"] == 1 / 64
        assert torch.isfinite(api._conditioning(torch, data, constant)).all()


def test_saved_training_normalizer_excludes_validation_rows_and_detects_tampering(parent):
    result = fit(parent, source_conditioning="train_rms")
    checkpoint = result["checkpoint"]
    data = torch.tensor([row["embedding"] for row in rows("intent_ir", "train")])
    assert checkpoint["normalizer"]["mean"] == data.mean(0).tolist()
    changed = deepcopy(checkpoint); changed["normalizer"]["mean"][0] += 1
    with pytest.raises(ValueError, match="normalizer identity"):
        api.Runtime(changed)
    changed = deepcopy(checkpoint); changed["normalizer"]["training_embedding_digest"] = "0" * 64
    changed["normalizer_sha256"] = api.digest(changed["normalizer"])
    with pytest.raises(ValueError, match="normalizer identity"):
        api.Runtime(changed)


def observation(*, action=1, modality=1, exact=0, native=2, objective=1., mse=.1):
    return {"objective": objective, "embedding_mse": mse, "generated": {
        "exact_count": exact, "native_valid_count": native, "count": 2,
        "field_accuracy": (action + modality) / 4,
        "per_field": {"/document/action": {"correct": action, "total": 2},
                      "/document/modality": {"correct": modality, "total": 2}}}}


def test_lower_loss_cannot_hide_modality_or_native_validity_regression():
    best = observation()
    selected, reason = api._selection(observation(action=2, modality=0, objective=.01), best, best)
    assert not selected and reason == "generated_field_regression"
    selected, reason = api._selection(observation(action=2, native=1, objective=.01), best, best)
    assert not selected and reason == "generated_field_regression"
    assert api._selection(observation(action=2, objective=2.), best, best)[0]


def test_initial_embedding_bound_is_preserved_by_default():
    before, best = observation(mse=.2), observation(mse=.1)
    candidate = observation(action=2, mse=.21)
    assert api._selection(candidate, best, before) == (False, "embedding_regression_against_initialization")
    assert api._selection(candidate, best, before, embedding_nonregression=False)[0]
    changed = observation(); changed["generated"]["per_field"].pop("/document/action")
    with pytest.raises(ValueError, match="coverage"):
        api._selection(changed, best, before)


def test_invalid_generated_output_has_no_exact_or_semantic_field_credit():
    expected = rows("intent_ir", "validation")
    generated = [{"id": expected[0]["id"], "target_access": False,
        "source_sha256": hashlib.sha256(expected[0]["source_text"].encode()).hexdigest(),
        "generated_tokens": ["{"], "ended": True, "reconstructed_embedding": expected[0]["embedding"]}]
    result = api._generated_metrics("intent_ir", generated, expected)
    assert result["exact_count"] == result["native_valid_count"] == result["scalar_correct"] == 0
    assert result["scalar_total"] > 0 and result["field_accuracy"] == 0
    with pytest.raises(ValueError, match="count differs"):
        api._generated_metrics("intent_ir", [], expected)


@pytest.mark.parametrize("config", [{"max_target_tokens": 65}, {"scalar_value_weight": 0},
    {"scalar_value_weight": True}, {"source_conditioning": "validation_rms"},
    {"eval_interval": 0}, {"plateau_patience": 0}, {"plateau_factor": 1},
    {"min_learning_rate_ratio": 0}, {"memory_budget_bytes": True}])
def test_invalid_settings_and_context_growth_fail_before_fit(parent, config):
    with pytest.raises(ValueError):
        fit(parent, **config)


def test_split_overlap_and_target_window_overflow_do_not_truncate(parent):
    data = rows("intent_ir", "train")
    with pytest.raises(ValueError, match="overlap"):
        api.train("intent_ir", data, data, parent_projection=parent)
    with pytest.raises(ValueError, match="token limit"):
        fit(parent, max_target_tokens=8)


def test_parent_file_is_never_rewritten(parent, tmp_path):
    path = tmp_path / "parent.json"; original = base._raw(parent); path.write_bytes(original)
    descriptor = {"path": str(path), "sha256": hashlib.sha256(original).hexdigest()}
    fitted = fit(descriptor, epochs=1)
    assert path.read_bytes() == original
    assert fitted["checkpoint"]["parent_sha256"] == descriptor["sha256"]


def test_deadline_partial_epoch_cannot_replace_initial_state(parent, monkeypatch):
    clock = [0.]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original = torch.optim.Adam.step
    def late(*args, **kwargs):
        result = original(*args, **kwargs); clock[0] = 2.
        return result
    monkeypatch.setattr(torch.optim.Adam, "step", late)
    result = fit(parent, max_seconds=1.)
    report = result["metrics"]
    assert report["optimizer_steps"] == 1 and report["selected_epoch"] == 0
    assert report["selected_validation"] == report["before_validation"]
    assert not report["history"] and report["stopped_reason"] == "deadline"


def test_adam_instance_continues_through_rate_reductions(parent, monkeypatch):
    constructions = []
    original = torch.optim.Adam
    def counted(*args, **kwargs):
        optimizer = original(*args, **kwargs)
        # The parent validator separately restores its historical Adam state
        # with foreach=False; count only the optimizer belonging to this fit.
        if kwargs.get("foreach") is not False:
            constructions.append(optimizer)
        return optimizer
    monkeypatch.setattr(torch.optim, "Adam", counted)
    monkeypatch.setattr(api, "_selection", lambda *args, **kwargs: (False, "unit_forced_plateau"))
    monkeypatch.setattr(api, "_metrics", lambda *args, **kwargs: dict(objective=1.,
        token_cross_entropy=1., weighted_token_cross_entropy=1., embedding_mse=.1))
    result = fit(parent, epochs=4, patience=4, plateau_patience=1)
    assert len(constructions) == 1
    report = result["metrics"]
    assert report["optimizer_steps"] == 8
    assert all(row["next_learning_rate"] < row["learning_rate"] for row in report["history"])
    assert all(int(state["step"].item()) == 8 for state in constructions[0].state.values())


def test_evaluation_interval_counts_completed_evaluations_for_patience(parent, monkeypatch):
    monkeypatch.setattr(api, "_selection", lambda *args, **kwargs: (False, "unit_forced_plateau"))
    monkeypatch.setattr(api, "_metrics", lambda *args, **kwargs: dict(objective=1.,
        token_cross_entropy=1., weighted_token_cross_entropy=1., embedding_mse=.1))
    result = fit(parent, epochs=10, eval_interval=3, patience=2)
    assert [row["epoch"] for row in result["metrics"]["history"]] == [1, 3]
    assert result["metrics"]["optimizer_steps"] == 6
    assert result["metrics"]["stopped_reason"] == "generated_validation_patience"


def test_rejected_selection_with_improving_objective_is_not_a_plateau(parent, monkeypatch):
    observations = [0]
    def improving(*args, **kwargs):
        observations[0] += 1
        value = 1. / observations[0]
        return dict(objective=value, token_cross_entropy=value,
            weighted_token_cross_entropy=value, embedding_mse=0.)
    monkeypatch.setattr(api, "_metrics", improving)
    monkeypatch.setattr(api, "_selection", lambda *args, **kwargs: (False, "unit_forced_rejection"))
    result = fit(parent, epochs=4, patience=1, plateau_patience=1)
    report = result["metrics"]
    assert report["optimizer_steps"] == 8 and report["selected_epoch"] == 0
    assert len(report["history"]) == 4
    assert all(row["candidate_learning_progress"] for row in report["history"])
    assert all(row["next_learning_rate"] == row["learning_rate"] for row in report["history"])
    assert report["selected_validation"] == report["before_validation"]
    assert "rejection_alone_is_not_plateau" in report["schedule_signal"]


def test_incomplete_generated_evaluation_cannot_select_partial_results(parent, monkeypatch):
    original = api._generate
    calls = [0]
    def interrupted(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise api.EvaluationDeadline("unit partial generated evaluation")
        return original(*args, **kwargs)
    monkeypatch.setattr(api, "_generate", interrupted)
    result = fit(parent)
    report = result["metrics"]
    assert report["optimizer_steps"] == 2 and report["selected_epoch"] == 0
    assert report["selected_validation"] == report["before_validation"]
    assert not report["history"]
    assert report["stopped_reason"] == "deadline_incomplete_generated_evaluation"


def test_memory_budget_rejects_bounded_but_oversized_work(parent):
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        fit(parent, memory_budget_bytes=1024**2, batch_size=64)


def test_source_guard_includes_new_owner_and_baseline_dependencies(parent, monkeypatch):
    original = api._implementation
    def changed():
        result = original(); result["runtime"] = "0" * 64
        return result
    monkeypatch.setattr(api, "_implementation", changed)
    with pytest.raises(ValueError, match="producer changed"):
        fit(parent)
