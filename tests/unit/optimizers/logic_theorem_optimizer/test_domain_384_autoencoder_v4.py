"""Real numerical v4 projection-policy tests on synthetic vectors and a tiny trained parent.

These vectors are test fixtures, not verified semantic embeddings. No result
here supplies Lake evidence, source fidelity, or production qualification.
"""
from copy import deepcopy
import hashlib

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v4 as api
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
    options = dict(epochs=3, batch_size=1, max_seconds=30, eval_interval=1, patience=3, decoder_conditioning="initial_only", projection_update_policy="joint")
    options.update(config)
    return api.train(domain, rows(domain, "train"), rows(domain, "validation"),
        parent_projection=parent, config=options)


@pytest.fixture(scope="module", params=[(domain, mode, policy) for domain in api.DOMAINS for mode in api.MODES for policy in api.PROJECTION_POLICIES])
def trained(request, parent):
    before = deepcopy(parent)
    result = fit(parent, domain=request.param[0], decoder_conditioning=request.param[1], projection_update_policy=request.param[2])
    assert parent == before
    return result["checkpoint"]


def inference_rows(domain):
    return [{key: value for key, value in row.items() if key != "target"}
        for row in rows(domain, "validation")]



def prepared(parent, mode, policy="joint"):
    data_rows = rows("intent_ir", "train")
    vocabulary = [*base.SPECIAL, *sorted(set(base._tokens(data_rows[0]["target"])))]
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
    config = api._config({"decoder_conditioning": mode, "projection_update_policy": policy}, parent["config"])
    return data_rows, codec, config



def test_v4_preserves_v3_architecture_and_all_mathematical_gates():
    assert api.SCHEMA != api.v3.SCHEMA
    assert api.ARCHITECTURE == api.v3.ARCHITECTURE
    for name in ("_model", "_transfer", "_decoder_spec", "_loss", "_metrics", "_generate",
                 "_normalizer", "_selection", "_generated_metrics", "_validate_lineage"):
        assert getattr(api, name) is getattr(api.v3, name)


@pytest.mark.parametrize("mode", api.MODES)
def test_joint_numerically_matches_v3_training_and_selected_checkpoint(parent, mode):
    common = dict(epochs=3, batch_size=1, max_seconds=30, eval_interval=1, patience=3,
        decoder_conditioning=mode)
    before = deepcopy(parent)
    control = api.v3.train("intent_ir", rows("intent_ir", "train"), rows("intent_ir", "validation"),
        parent_projection=parent, config=common)
    candidate = api.train("intent_ir", rows("intent_ir", "train"), rows("intent_ir", "validation"),
        parent_projection=parent, config={**common, "projection_update_policy": "joint"})
    assert candidate["checkpoint"]["model_state"] == control["checkpoint"]["model_state"]
    assert candidate["checkpoint"]["weights_sha256"] == control["checkpoint"]["weights_sha256"]
    assert candidate["checkpoint"]["decoder_spec"] == control["checkpoint"]["decoder_spec"]
    for key in ("before_validation", "selected_validation", "history", "selected_epoch", "training", "optimizer_steps"):
        assert candidate["metrics"][key] == control["metrics"][key]
    assert parent == before


@pytest.mark.parametrize("policy", api.PROJECTION_POLICIES)
def test_optimizer_parameter_groups_exactly_match_declared_policy(parent, policy, monkeypatch):
    original, captured = torch.optim.Adam, []
    def observed(parameters, *args, **kwargs):
        parameters = list(parameters)
        optimizer = original(parameters, *args, **kwargs)
        if kwargs.get("foreach") is not False: captured.append((parameters, optimizer))
        return optimizer
    models, transfer = [], api._transfer
    def transferred(*args):
        model, lineage = transfer(*args); models.append(model); return model, lineage
    monkeypatch.setattr(api, "_transfer", transferred)
    monkeypatch.setattr(torch.optim, "Adam", observed)
    fitted = fit(parent, projection_update_policy=policy)
    assert len(models) == len(captured) == 1
    model, (optimized, optimizer) = models[0], captured[0]
    optimized_names = [name for name, value in model.named_parameters() if any(value is p for p in optimized)]
    frozen = set(api.PROJECTION_TENSORS) if policy == "frozen_parent_residual" else set()
    expected_names = [name for name, _ in model.named_parameters() if name not in frozen]
    assert optimized_names == expected_names
    assert len(optimized) == len(expected_names)
    assert fitted["checkpoint"]["projection_policy"]["trainable_tensor_names"] == expected_names
    assert set(fitted["checkpoint"]["projection_policy"]["frozen_tensor_names"]) == frozen
    for name, parameter in model.named_parameters():
        assert parameter.requires_grad is (name not in frozen)
        if name in frozen:
            assert parameter not in optimizer.state and parameter.grad is None
        else:
            assert parameter in optimizer.state and int(optimizer.state[parameter]["step"].item()) == 6
    for prefix in ("condition.", "target_embedding.", "decoder.", "output."):
        assert any(name.startswith(prefix) for name in optimized_names)


def test_all_domains_modes_and_policies_replay_with_separate_checkpoint_ownership(trained, parent):
    runtime = api.Runtime(trained)
    record = trained["projection_policy"]
    assert runtime.describe()["projection_policy"] == record
    assert runtime.describe()["projection_update_policy"] == trained["config"]["projection_update_policy"]
    with base._cpu():
        inherited, _ = api.v3._transfer(parent, trained["codec"], trained["config"])
        assert api._projection_sha256(inherited) == record["inherited_projection_sha256"]
        assert api._projection_sha256(runtime.model) == record["selected_projection_sha256"]
        if record["mode"] == "frozen_parent_residual":
            assert record["selected_projection_sha256"] == record["inherited_projection_sha256"]
            for name in api.PROJECTION_TENSORS:
                assert torch.equal(inherited.state_dict()[name].view(torch.uint8), runtime.model.state_dict()[name].view(torch.uint8))
            assert trained["training"]["frozen_projection_checks_after_optimizer_steps"] == 6
            assert trained["training"]["selected_validation"]["embedding_mse"] == trained["training"]["before_validation"]["embedding_mse"]
        else:
            assert record["frozen_tensor_names"] == [] and record["frozen_projection_verified"] is False
            assert trained["training"]["frozen_projection_checks_after_optimizer_steps"] == 0
    assert api.evaluate(trained, rows(trained["domain_id"], "validation"))["fidelity"] == trained["training"]["selected_validation"]["generated"]
    assert trained["config"]["max_target_tokens"] == trained["parent_context_limit"] == 64
    assert all(trained[key] is False for key in api.FALSE)
    for older in (base, api.v3, api.v3.v2):
        with pytest.raises(ValueError, match="closed"):
            older.Runtime(trained)


def test_frozen_projection_checks_every_update_without_hashing_in_hot_loop(parent, monkeypatch):
    calls = []
    real_verify, real_hash = api._verify_projection, api._projection_sha256
    def checked(model, snapshot):
        calls.append(snapshot is not None)
        return real_verify(model, snapshot)
    hashes = []
    def hashed(model):
        hashes.append(1); return real_hash(model)
    monkeypatch.setattr(api, "_verify_projection", checked)
    monkeypatch.setattr(api, "_projection_sha256", hashed)
    report = fit(parent, epochs=10, projection_update_policy="frozen_parent_residual")["metrics"]
    assert report["optimizer_steps"] == 20
    assert calls == [True] * 22  # Every update, then before/after selected restore.
    assert len(hashes) < report["optimizer_steps"]  # Only transfer/save/loader provenance.


def test_frozen_projection_mutation_after_optimizer_step_fails_immediately(parent, monkeypatch):
    models, transferred = [], api._transfer
    def transfer(*args):
        model, lineage = transferred(*args); models.append(model); return model, lineage
    real_step = torch.optim.Adam.step
    def corrupted(*args, **kwargs):
        result = real_step(*args, **kwargs)
        with torch.no_grad(): models[-1].projection_down.weight[0, 0] += .25
        return result
    monkeypatch.setattr(api, "_transfer", transfer)
    monkeypatch.setattr(torch.optim.Adam, "step", corrupted)
    with pytest.raises(ValueError, match="frozen projection changed"):
        fit(parent, projection_update_policy="frozen_parent_residual")


def test_frozen_projection_mutation_during_selected_restore_is_rejected(parent, monkeypatch):
    original, corrupt = torch.nn.Module.load_state_dict, [False]
    def load(model, state, *args, **kwargs):
        result = original(model, state, *args, **kwargs)
        if isinstance(model, torch.nn.Module) and hasattr(model, "projection_down") and not model.projection_down.weight.requires_grad:
            with torch.no_grad(): model.projection_down.weight[0, 0] += .5
            corrupt[0] = True
        return result
    monkeypatch.setattr(torch.nn.Module, "load_state_dict", load)
    with pytest.raises(ValueError, match="frozen projection changed"):
        fit(parent, projection_update_policy="frozen_parent_residual")
    assert corrupt[0]


def test_byte_equality_includes_signed_zero_and_reference_is_detached(parent):
    _, codec, config = prepared(parent, "initial_only", "frozen_parent_residual")
    with base._cpu() as torch:
        model, _ = api._transfer(parent, codec, config); api._configure_projection(model, config)
        with torch.no_grad(): model.projection_down.weight[0, 0] = 0.
        before = api._projection_sha256(model); snapshot = api._projection_snapshot(model, config)
        assert all(not value.requires_grad and value.dtype == torch.uint8 for value in snapshot.values())
        with torch.no_grad(): model.projection_down.weight[0, 0] = -0.
        assert api._projection_sha256(model) != before
        with pytest.raises(ValueError, match="frozen projection changed"):
            api._verify_projection(model, snapshot)


@pytest.mark.parametrize("mutation", ["config_policy", "record_policy", "inherited_hash", "selected_hash", "projection_weight",
    "frozen_names", "trainable_names", "verification_flag", "training_policy", "training_check_count",
    "training_trainable_count", "training_frozen_count", "training_boolean_count", "schema", "architecture", "pins"])
def test_loader_rejects_policy_weight_and_provenance_mismatch(parent, mutation):
    c = fit(parent, epochs=1, projection_update_policy="frozen_parent_residual")["checkpoint"]
    if mutation == "config_policy": c["config"]["projection_update_policy"] = "joint"
    elif mutation == "record_policy": c["projection_policy"]["mode"] = "joint"
    elif mutation == "inherited_hash": c["projection_policy"]["inherited_projection_sha256"] = "0" * 64
    elif mutation == "selected_hash": c["projection_policy"]["selected_projection_sha256"] = "0" * 64
    elif mutation == "projection_weight":
        c["model_state"]["projection_up.bias"][0] += .1
        c["weights_sha256"] = api.digest(c["model_state"])
    elif mutation == "frozen_names": c["projection_policy"]["frozen_tensor_names"] = []
    elif mutation == "trainable_names": c["projection_policy"]["trainable_tensor_names"].append("projection_up.bias")
    elif mutation == "verification_flag": c["projection_policy"]["frozen_projection_verified"] = 1
    elif mutation == "training_policy": c["training"]["projection_update_policy"] = "joint"
    elif mutation == "training_check_count": c["training"]["frozen_projection_checks_after_optimizer_steps"] = 0
    elif mutation == "training_trainable_count": c["training"]["trainable_parameter_count"] += 1
    elif mutation == "training_frozen_count": c["training"]["frozen_parameter_count"] -= 1
    elif mutation == "training_boolean_count": c["training"]["frozen_projection_checks_after_optimizer_steps"] = True
    elif mutation == "schema": c["schema"] = api.v3.SCHEMA
    elif mutation == "architecture": c["architecture"] += "-larger"
    elif mutation == "pins": c["implementation"]["runtime"] = "0" * 64
    with pytest.raises(ValueError): api.Runtime(c)


@pytest.mark.parametrize("config", [None, {}, {"decoder_conditioning": "initial_only"},
    {"decoder_conditioning": "every_step", "projection_update_policy": "frozen"},
    {"decoder_conditioning": "every_step", "projection_update_policy": True},
    {"projection_update_policy": "joint"}])
def test_explicit_projection_and_decoder_policies_are_required(parent, config):
    with pytest.raises(ValueError): api._config(config, parent["config"])


def test_frozen_reference_clones_are_budgeted_before_model_creation(parent, monkeypatch):
    _, codec, config = prepared(parent, "every_step", "frozen_parent_residual")
    inherited = api.v3._memory(config, 3, len(codec["target_vocabulary"]))
    actual = api._memory(config, 3, len(codec["target_vocabulary"]))
    expected = sum(torch.tensor(parent["model_state"][name]).numel() * 4 for name in api.PROJECTION_TENSORS)
    assert actual["frozen_projection_reference_bytes"] == expected
    assert actual["estimated_tensor_bytes"] == inherited["estimated_tensor_bytes"] + expected
    monkeypatch.setattr(api, "_transfer", lambda *args: pytest.fail("allocated model before memory preflight"))
    with pytest.raises(ValueError, match="reservation exceeds budget"):
        fit(parent, projection_update_policy="frozen_parent_residual", memory_budget_bytes=1024**2, batch_size=64)


def test_frozen_arm_cannot_relax_field_or_embedding_selection_gates():
    def observed(action, modality, mse=.1, loss=1):
        return {"objective": loss, "embedding_mse": mse, "generated": {
            "exact_count": 0, "native_valid_count": 2, "field_accuracy": (action + modality) / 4,
            "per_field": {"action": {"correct": action, "total": 2}, "modality": {"correct": modality, "total": 2}}}}
    before = observed(1, 1)
    assert api._selection(observed(2, 0, loss=.1), before, before) == (False, "generated_field_regression")
    assert api._selection(observed(2, 1, mse=.2, loss=.1), before, before) == (False, "embedding_regression_against_initialization")


@pytest.mark.parametrize("policy", api.PROJECTION_POLICIES)
def test_partial_deadline_preserves_initialization_and_projection_receipt(parent, policy, monkeypatch):
    clock = [0.]; monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    original = torch.optim.Adam.step
    def late(*args, **kwargs):
        result = original(*args, **kwargs); clock[0] = 2.; return result
    monkeypatch.setattr(torch.optim.Adam, "step", late)
    c = fit(parent, projection_update_policy=policy, max_seconds=1.)["checkpoint"]
    assert c["training"]["optimizer_steps"] == 1 and c["training"]["selected_epoch"] == 0
    assert c["training"]["stopped_reason"] == "deadline" and c["training"]["history"] == []
    assert c["projection_policy"]["selected_projection_sha256"] == c["projection_policy"]["inherited_projection_sha256"]
    assert c["training"]["selected_validation"] == c["training"]["before_validation"]


def test_incomplete_generated_evaluation_cannot_select_frozen_candidate(parent, monkeypatch):
    original, calls = api._generate, [0]
    def incomplete(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2: raise api.EvaluationDeadline("unit incomplete evaluation")
        return original(*args, **kwargs)
    monkeypatch.setattr(api, "_generate", incomplete)
    report = fit(parent, projection_update_policy="frozen_parent_residual")["metrics"]
    assert report["selected_epoch"] == 0 and report["history"] == []
    assert report["selected_validation"] == report["before_validation"]
    assert report["stopped_reason"] == "deadline_incomplete_generated_evaluation"


def test_loaded_frozen_checkpoint_ablation_is_target_free_and_nonmutating(parent):
    c = fit(parent, projection_update_policy="frozen_parent_residual")["checkpoint"]
    runtime = api.Runtime(c); inputs = inference_rows("intent_ir")
    before, digest = runtime.infer(inputs), api._projection_sha256(runtime.model)
    for ablation in ("zero_projection", "zero_condition", "zero_decoder"):
        result = runtime.infer(inputs, weight_ablation=ablation)
        assert all(r["target_access"] is False and not r["teacher_forcing"] for r in result["rows"])
    assert runtime.infer(inputs) == before and api._projection_sha256(runtime.model) == digest
    with pytest.raises(ValueError, match="closed domain row"):
        runtime.infer(rows("intent_ir", "validation"))


def test_parent_file_remains_immutable_and_reopening_needs_file_digest_domain(parent, tmp_path):
    parent_path = tmp_path / "parent.json"; original = base._raw(parent); parent_path.write_bytes(original)
    fitted = fit({"path": str(parent_path), "sha256": hashlib.sha256(original).hexdigest()},
        projection_update_policy="frozen_parent_residual", epochs=1)
    assert parent_path.read_bytes() == original
    path = tmp_path / "v4.json"; payload = api._raw(fitted["checkpoint"]); path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    runtime = api.load_checkpoint(path, expected_sha256=sha, expected_domain="intent_ir")
    assert runtime.describe()["projection_update_policy"] == "frozen_parent_residual"
    with pytest.raises(ValueError, match="bytes differ"):
        api.load_checkpoint(path, expected_sha256="0" * 64, expected_domain="intent_ir")
    with pytest.raises(ValueError, match="another domain"):
        api.load_checkpoint(path, expected_sha256=sha, expected_domain="ui_ux_ir")
