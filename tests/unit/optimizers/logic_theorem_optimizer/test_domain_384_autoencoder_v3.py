"""Real numerical v3 tests on synthetic vectors and a tiny trained parent.

These vectors are test fixtures, not verified semantic embeddings. No result
here supplies Lake evidence, source fidelity, or production qualification.
"""
from copy import deepcopy
import hashlib

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v3 as api
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
    options = dict(epochs=3, batch_size=1, max_seconds=30, eval_interval=1, patience=3, decoder_conditioning="initial_only")
    options.update(config)
    return api.train(domain, rows(domain, "train"), rows(domain, "validation"),
        parent_projection=parent, config=options)


@pytest.fixture(scope="module", params=[(domain, mode) for domain in api.DOMAINS for mode in api.MODES])
def trained(request, parent):
    before = deepcopy(parent)
    result = fit(parent, domain=request.param[0], decoder_conditioning=request.param[1])
    assert parent == before
    return result["checkpoint"]


def inference_rows(domain):
    return [{key: value for key, value in row.items() if key != "target"}
        for row in rows(domain, "validation")]



def prepared(parent, mode):
    data_rows = rows("intent_ir", "train")
    vocabulary = [*base.SPECIAL, *sorted(set(base._tokens(data_rows[0]["target"])))]
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
    config = api._config({"decoder_conditioning": mode}, parent["config"])
    return data_rows, codec, config


def test_inherited_math_is_unchanged_versioned_policy():
    for name in ("_loss", "_metrics", "_generate", "_generated_metrics", "_selection", "_normalizer", "_conditioning"):
        assert getattr(api, name) is getattr(api.v2, name)
    assert api.SCHEMA not in (base.SCHEMA, api.v2.SCHEMA)
    assert api.ARCHITECTURE != legal.ARCHITECTURE


@pytest.mark.parametrize("mode", api.MODES)
def test_transfer_and_initial_function_match_unchanged_v2(parent, mode):
    data_rows, codec, config = prepared(parent, mode)
    original = deepcopy(parent)
    with base._cpu() as torch:
        shared, old_lineage = base._transfer(parent, codec, config)
        rng = torch.random.get_rng_state().clone()
        candidate, lineage = api._transfer(parent, codec, config)
        assert torch.equal(rng, torch.random.get_rng_state())
        e = config["token_embedding_dim"]
        for name, value in candidate.state_dict().items():
            expected = shared.state_dict()[name]
            if name == "decoder.weight_ih_l0" and mode == "every_step":
                assert torch.equal(value[:, :e], expected)
                assert torch.count_nonzero(value[:, e:]) == 0
            else:
                assert torch.equal(value, expected)
        data, labels = base._batch(torch, data_rows, codec["target_vocabulary"], 64)
        normalizer = api._normalizer(torch, data, "none")
        weights = (labels[:, 1:] != 0).float()
        expected = api.v2._loss(torch, shared, data, labels, weights, config, normalizer)
        actual = api._loss(torch, candidate, data, labels, weights, config, normalizer)
        for left, right in zip(actual, expected):
            torch.testing.assert_close(left, right, rtol=1e-6, atol=1e-7)
        inputs = [{k: r[k] for k in ("id", "source_text", "embedding")} for r in data_rows]
        a = api._generate(torch, candidate, inputs, codec["target_vocabulary"], config, normalizer)
        b = api._generate(torch, shared, inputs, codec["target_vocabulary"], config, normalizer)
        assert a == b
        spec = api._decoder_spec(config, len(codec["target_vocabulary"]))
        assert spec["parameter_count"] == sum(p.numel() for p in candidate.parameters())
        assert spec["additional_parameter_count"] == (3 * config["hidden_size"] ** 2 if mode == "every_step" else 0)
        assert lineage["inherited_initial_state_sha256"] == old_lineage["initial_state_sha256"]
        assert lineage["random_parameters_used"] is False
        assert lineage["common_initial_parameters_identical"] is True
    assert parent == original


@pytest.mark.parametrize("mode", api.MODES)
def test_teacher_forcing_and_stepwise_decoding_have_identical_source_carry(parent, mode):
    data_rows, codec, config = prepared(parent, mode)
    with base._cpu() as torch:
        model, _ = api._transfer(parent, codec, config)
        data, labels = base._batch(torch, data_rows, codec["target_vocabulary"], 64)
        state = model.start(model.project(data))
        original = state.detach().clone()
        full, completed = model.next_logits(labels[:, :8], state)
        incremental, carried = [], state
        for i in range(8):
            logits, carried = model.next_logits(labels[:, i:i + 1], carried)
            incremental.append(logits)
            assert torch.equal(carried[1], original[1])
        torch.testing.assert_close(full, torch.cat(incremental, dim=1), rtol=1e-6, atol=1e-7)
        torch.testing.assert_close(completed, carried, rtol=1e-6, atol=1e-7)
        assert torch.equal(state, original)


@pytest.mark.parametrize("mode", api.MODES)
def test_interleaved_requests_and_reversed_batches_have_no_global_source_cache(parent, mode):
    data_rows, codec, config = prepared(parent, mode)
    with base._cpu() as torch:
        model, _ = api._transfer(parent, codec, config)
        data, labels = base._batch(torch, data_rows, codec["target_vocabulary"], 64)
        state = model.start(model.project(data))
        a, b = state[:, :1].clone(), state[:, 1:].clone()
        first_a, a_next = model.next_logits(labels[:1, :1], a)
        model.next_logits(labels[1:, :1], b)
        repeated_a, repeated_next = model.next_logits(labels[:1, :1], a)
        assert torch.equal(first_a, repeated_a) and torch.equal(a_next, repeated_next)
        both, final = model.next_logits(labels[:, :4], state)
        reverse, reverse_final = model.next_logits(labels.flip(0)[:, :4], state.flip(1))
        torch.testing.assert_close(both, reverse.flip(0), rtol=1e-6, atol=1e-7)
        torch.testing.assert_close(final, reverse_final.flip(1), rtol=1e-6, atol=1e-7)
        with pytest.raises(ValueError, match="two-lane"):
            model.next_logits(labels[:, :1], state[:1])


def test_persistent_columns_learn_and_late_logits_use_the_preserved_source(parent):
    data_rows, codec, config = prepared(parent, "every_step")
    with base._cpu() as torch:
        model, _ = api._transfer(parent, codec, config)
        data, labels = base._batch(torch, data_rows, codec["target_vocabulary"], 64)
        normalizer = api._normalizer(torch, data, "none")
        loss = api._loss(torch, model, data, labels, (labels[:, 1:] != 0).float(), config, normalizer)[0]
        loss.backward()
        e = config["token_embedding_dim"]
        assert float(model.decoder.weight_ih_l0.grad[:, e:].abs().sum()) > 0
        with torch.no_grad():
            model.decoder.weight_ih_l0[:, e:].fill_(.2)
        state = torch.zeros((2, 2, config["hidden_size"]))
        changed = state.clone(); changed[1].fill_(.5)
        logits, carried = model.next_logits(labels[:, :3], state)
        other, other_carried = model.next_logits(labels[:, :3], changed)
        assert not torch.allclose(logits[:, -1], other[:, -1], rtol=1e-6, atol=1e-7)
        assert torch.equal(carried[1], state[1]) and torch.equal(other_carried[1], changed[1])


def test_real_training_and_checkpoint_replay_for_each_mode_and_domain(trained):
    runtime = api.Runtime(trained)
    spec = trained["decoder_spec"]
    assert spec["mode"] == trained["config"]["decoder_conditioning"]
    assert trained["config"]["max_target_tokens"] == trained["parent_context_limit"] == 64
    assert trained["config"]["source_conditioning"] == "none" and trained["config"]["scalar_value_weight"] == 8.
    assert trained["training"]["optimizer_steps"] == 6
    assert trained["training"]["test_used_for_selection"] is False
    assert all(trained[key] is False for key in api.FALSE)
    assert runtime.describe()["decoder_spec"] == spec
    result = api.evaluate(trained, rows(trained["domain_id"], "validation"))["fidelity"]
    assert result == trained["training"]["selected_validation"]["generated"]
    assert runtime.describe()["embedding_provenance_verified_by_runtime"] is False
    for older in (base, api.v2):
        with pytest.raises(ValueError, match="closed"):
            older.Runtime(trained)


def test_target_free_runtime_ablation_removes_both_condition_paths_without_mutation(trained, monkeypatch):
    runtime = api.Runtime(trained)
    inputs = inference_rows(trained["domain_id"])
    before = runtime.infer(inputs)
    real = api._generate
    observations = []
    def observed(torch, model, *args, **kwargs):
        projected = model.project(torch.tensor([inputs[0]["embedding"]]))
        state = model.start(projected)
        observations.append(state.detach().clone())
        return real(torch, model, *args, **kwargs)
    monkeypatch.setattr(api, "_generate", observed)
    zero = runtime.infer(inputs, weight_ablation="zero_condition")
    assert observations and torch.count_nonzero(observations[0]) == 0
    assert all(row["target_access"] is False for row in zero["rows"])
    monkeypatch.setattr(api, "_generate", real)
    assert runtime.infer(inputs) == before
    with pytest.raises(ValueError, match="closed domain row"):
        runtime.infer([{**inputs[0], "target": target(trained["domain_id"])}])
    changed = deepcopy(inputs); changed[0]["source_text"] = "Only provenance text changed."
    other = runtime.infer(changed)
    for key in ("generated_tokens", "candidate_ir", "reconstructed_embedding"):
        assert other["rows"][0][key] == before["rows"][0][key]


@pytest.mark.parametrize("alter", ["schema", "architecture", "mode", "spec", "shape", "domain", "pins", "normalized_overlap", "lineage"])
def test_closed_checkpoint_rejects_relabeling_drift_and_leakage(parent, alter):
    c = fit(parent, epochs=1)["checkpoint"]
    if alter == "schema": c["schema"] = api.v2.SCHEMA
    elif alter == "architecture": c["architecture"] = legal.ARCHITECTURE
    elif alter == "mode": c["config"]["decoder_conditioning"] = "every_step"
    elif alter == "spec": c["decoder_spec"]["parameter_count"] += 1
    elif alter == "shape":
        c["model_state"]["decoder.weight_ih_l0"][0].append(0.)
        c["weights_sha256"] = api.digest(c["model_state"])
    elif alter == "domain": c["domain_id"] = "legal_ir"
    elif alter == "pins": c["implementation"]["runtime"] = "0" * 64
    elif alter == "normalized_overlap":
        c["validation_manifest"][0]["normalized_source_sha256"] = c["training_manifest"][0]["normalized_source_sha256"]
    elif alter == "lineage": c["lineage"]["random_parameters_used"] = True
    with pytest.raises((ValueError, TypeError)):
        api.Runtime(c)


def test_checkpoint_digest_and_expected_domain_are_required(trained, tmp_path):
    path = tmp_path / "checkpoint.json"; raw = api._raw(trained); path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    assert api.load_checkpoint(path, expected_sha256=sha, expected_domain=trained["domain_id"]).describe()["decoder_conditioning"] == trained["config"]["decoder_conditioning"]
    with pytest.raises(ValueError, match="bytes differ"):
        api.load_checkpoint(path, expected_sha256="0" * 64, expected_domain=trained["domain_id"])
    with pytest.raises(ValueError, match="another domain"):
        api.load_checkpoint(path, expected_sha256=sha, expected_domain="legal_ir")


@pytest.mark.parametrize("options", [None, {}, {"decoder_conditioning": "persistent"}, {"decoder_conditioning": True},
    {"decoder_conditioning": "every_step", "max_target_tokens": 65},
    {"decoder_conditioning": "initial_only", "source_conditioning": "tuning_rms"}])
def test_configuration_requires_explicit_mode_and_keeps_parent_token_ceiling(parent, options):
    with pytest.raises(ValueError):
        api._config(options, parent["config"])


def test_memory_preflight_before_training_model_allocation(parent, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("new model allocated before memory preflight")
    monkeypatch.setattr(api, "_transfer", forbidden)
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        fit(parent, decoder_conditioning="every_step", memory_budget_bytes=1024**2, batch_size=64)


def test_memory_preflight_before_loader_model_allocation(parent, monkeypatch):
    c = fit(parent, epochs=1)["checkpoint"]
    c["config"]["memory_budget_bytes"] = 1024**2; c["config"]["batch_size"] = 64
    monkeypatch.setattr(api, "_model", lambda *args: pytest.fail("load allocated model before preflight"))
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        api.Runtime(c)


def test_ablation_memory_preflight_before_model_copy(parent, monkeypatch):
    runtime = api.Runtime(fit(parent, epochs=1)["checkpoint"])
    runtime.checkpoint["config"]["memory_budget_bytes"] = 1024**2
    runtime.checkpoint["config"]["batch_size"] = 64
    original = api.deepcopy
    def reject_model_copy(value):
        if isinstance(value, torch.nn.Module): pytest.fail("ablation copied before preflight")
        return original(value)
    monkeypatch.setattr(api, "deepcopy", reject_model_copy)
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        runtime.infer(inference_rows("intent_ir"), weight_ablation="zero_condition")


def test_memory_accounts_for_added_columns_two_lanes_and_ablation(parent):
    _, codec, a = prepared(parent, "initial_only")
    _, _, b = prepared(parent, "every_step")
    first, second = (api._memory(c, 2, len(codec["target_vocabulary"])) for c in (a, b))
    assert first["two_lane_state_reserved"] and second["two_lane_state_reserved"]
    assert second["estimated_tensor_bytes"] > first["estimated_tensor_bytes"]
    copied = api._memory(b, 2, len(codec["target_vocabulary"]), ablation_copy=True)
    assert copied["estimated_tensor_bytes"] - second["estimated_tensor_bytes"] == second["parameter_count"] * 4


def test_training_only_normalization_and_normalized_source_manifest(parent):
    c = fit(parent, epochs=1, decoder_conditioning="every_step", source_conditioning="train_rms")["checkpoint"]
    assert c["normalizer"]["mean"] == torch.tensor([r["embedding"] for r in rows("intent_ir", "train")]).mean(0).tolist()
    assert c["normalizer"]["scale"] >= 1 / 64
    for r in c["training_manifest"] + c["validation_manifest"]:
        assert len(r["normalized_source_sha256"]) == 64
    data = rows("intent_ir", "train")
    tune = rows("intent_ir", "validation")
    tune[0]["source_text"] = "  " + data[0]["source_text"].upper() + "  "
    with pytest.raises(ValueError, match="overlap"):
        api.train("intent_ir", data, tune, parent_projection=parent, config={"decoder_conditioning": "every_step"})


def test_deadline_partial_epoch_cannot_replace_initial_state(parent, monkeypatch):
    clock = [0.]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original = torch.optim.Adam.step
    def late(*args, **kwargs):
        result = original(*args, **kwargs); clock[0] = 2.
        return result
    monkeypatch.setattr(torch.optim.Adam, "step", late)
    report = fit(parent, decoder_conditioning="every_step", max_seconds=1.)["metrics"]
    assert report["optimizer_steps"] == 1 and report["selected_epoch"] == 0
    assert report["selected_validation"] == report["before_validation"]
    assert report["history"] == [] and report["stopped_reason"] == "deadline"


def test_incomplete_generated_evaluation_never_selects(parent, monkeypatch):
    original, calls = api._generate, [0]
    def interrupted(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2: raise api.EvaluationDeadline("unit incomplete generated evaluation")
        return original(*args, **kwargs)
    monkeypatch.setattr(api, "_generate", interrupted)
    report = fit(parent, decoder_conditioning="every_step")["metrics"]
    assert report["selected_epoch"] == 0 and report["history"] == []
    assert report["selected_validation"] == report["before_validation"]
    assert report["stopped_reason"] == "deadline_incomplete_generated_evaluation"


def test_late_candidate_state_copy_never_selects(parent, monkeypatch):
    from collections import OrderedDict
    clock = [0.]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original, copies = api.deepcopy, [0]
    def copying(value):
        result = original(value)
        if isinstance(value, OrderedDict) and "projection_down.weight" in value:
            copies[0] += 1
            if copies[0] == 2: clock[0] = 2.
        return result
    monkeypatch.setattr(api, "deepcopy", copying)
    monkeypatch.setattr(api, "_selection", lambda *args: (True, "unit_forced_candidate"))
    report = fit(parent, max_seconds=1.)["metrics"]
    assert copies[0] >= 2 and report["selected_epoch"] == 0
    assert report["selected_validation"] == report["before_validation"]
    assert report["history"][0]["selection_reason"] == "late_state_copy"


def test_rejected_but_improving_objective_keeps_continuous_optimizer_learning(parent, monkeypatch):
    observations, constructions = [0], []
    def improving(*args, **kwargs):
        observations[0] += 1; value = 1. / observations[0]
        return dict(objective=value, token_cross_entropy=value, weighted_token_cross_entropy=value, embedding_mse=0.)
    original = torch.optim.Adam
    def counted(*args, **kwargs):
        value = original(*args, **kwargs)
        if kwargs.get("foreach") is not False: constructions.append(value)
        return value
    monkeypatch.setattr(torch.optim, "Adam", counted)
    monkeypatch.setattr(api, "_metrics", improving)
    monkeypatch.setattr(api, "_selection", lambda *args: (False, "unit_forced_rejection"))
    report = fit(parent, decoder_conditioning="every_step", epochs=4, patience=1, plateau_patience=1)["metrics"]
    assert len(constructions) == 1 and report["optimizer_steps"] == 8
    assert report["selected_epoch"] == 0 and len(report["history"]) == 4
    assert all(row["candidate_learning_progress"] and row["next_learning_rate"] == row["learning_rate"] for row in report["history"])
    assert all(int(state["step"].item()) == 8 for state in constructions[0].state.values())


def test_owner_and_v2_policy_provenance_are_checked(parent, monkeypatch):
    original = api._implementation
    def changed():
        result = original(); result["runtime"] = "0" * 64; return result
    monkeypatch.setattr(api, "_implementation", changed)
    with pytest.raises(ValueError, match="producer changed"):
        fit(parent)
