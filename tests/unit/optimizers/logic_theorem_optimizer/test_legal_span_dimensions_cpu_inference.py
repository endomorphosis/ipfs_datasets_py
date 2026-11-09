"""Small synthetic numerical parity; no native embedding or legal qualification."""
from copy import deepcopy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as owner


def rows(dimension=0):
    result = []
    for i, (actor, phrase, modality, action, obj) in enumerate((
        ("Lark", "must", "O", "retain", "books"),
        ("Wren", "may", "P", "publish", "records"),
    )):
        row = {"id": f"fictional-{i}", "source_text": f"{actor} {phrase} {action} {obj}.",
            "canonical_ir": {"rules": [{"actor": actor, "modality": modality,
                "action": action, "object": obj, "conditions": [], "exceptions": [], "temporal": []}]}}
        if dimension:
            row["latent"] = [(i + 1) / (j + 1) for j in range(dimension)]
        result.append(row)
    return result


@pytest.fixture(scope="module", autouse=True)
def threads():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def parent():
    data = rows()
    checkpoint = span.build_checkpoint(data, hidden_size=8, embedding_dim=4,
        projection_width=4, batch_size=2)
    return span.train_decoder(checkpoint, data, max_steps=2, max_seconds=30)["checkpoint"]


@pytest.fixture(scope="module", params=[384, 768])
def checkpoint(parent, request):
    dimension = request.param
    data = rows(dimension)
    initial = dims.build_checkpoint(parent, data, latent_dimension=dimension,
        context_contract={"dimension": dimension, "representation_id": "fictional-test-only",
            "producer_sha256": "a" * 64, "training_index_sha256": "b" * 64}, batch_size=2)
    trained = dims.train_decoder(initial, data, max_steps=2, max_seconds=30)["checkpoint"]
    return initial, trained


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("ablation", ["none", "zero", "disabled", "rotate"])
def test_exact_original_cpu_output_parity(checkpoint, which, ablation):
    cp = checkpoint[which]
    sources = ["A new trustee must inspect unfamiliar records.", "Another board may retain notices."]
    vectors = [[.2] * cp["config"]["latent_dimension"], [-.3] * cp["config"]["latent_dimension"]]
    original = dims.DimensionalSpanDecoder(cp).decode_formal_logic(sources, vectors, latent_ablation=ablation)
    actual = owner.CpuDimensionalSpanDecoder(cp).decode_formal_logic(sources, vectors, latent_ablation=ablation)
    assert actual == original
    assert actual["training_executed"] is actual["target_access"] is actual["qualified"] is False


def test_restore_and_decode_never_construct_an_optimizer(checkpoint, monkeypatch):
    cp = checkpoint[1]

    def forbidden(*args, **kwargs):
        raise AssertionError("inference must never construct Adam")

    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    restored_torch, model = owner.restore_for_inference(cp)
    assert restored_torch is torch
    assert all(parameter.device.type == "cpu" for parameter in model.parameters())
    decoder = owner.CpuDimensionalSpanDecoder(cp)
    result = decoder.decode_formal_logic(["A trustee may inspect records."], [[.1] * cp["config"]["latent_dimension"]])
    assert result["model_state_unchanged"] is True


def test_input_checkpoint_and_rng_unchanged_and_no_caller_config_alias(checkpoint):
    cp = deepcopy(checkpoint[1])
    before = deepcopy(cp)
    rng = torch.random.get_rng_state().clone()
    decoder = owner.CpuDimensionalSpanDecoder(cp)
    assert cp == before
    assert torch.equal(torch.random.get_rng_state(), rng)
    sources, vectors = ["A trustee may inspect records."], [[.1] * cp["config"]["latent_dimension"]]
    sources_before, vectors_before = deepcopy(sources), deepcopy(vectors)
    output = decoder.decode_formal_logic(sources, vectors)
    cp["config"]["latent_enabled"] = False
    cp["config"]["residual_scale"] = .75
    cp["model_state"]["modality.bias"][0] += 1
    assert decoder.decode_formal_logic(sources, vectors) == output
    assert sources == sources_before and vectors == vectors_before
    assert torch.equal(torch.random.get_rng_state(), rng)


@pytest.mark.parametrize("damage", ["negative_variance", "wrong_step", "missing_parameter", "wrong_shape"])
@pytest.mark.parametrize("location", ["child", "parent"])
def test_invalid_stored_moments_rejected_without_adam(checkpoint, monkeypatch, damage, location):
    cp = deepcopy(checkpoint[1])
    state_owner = cp if location == "child" else cp["source_parent_checkpoint"]
    parameters = state_owner["optimizer_state"]["parameters"]
    name = "modality.bias"
    if damage == "negative_variance":
        parameters[name]["exp_avg_sq"][0] = -1.
    elif damage == "wrong_step":
        parameters[name]["step"] += 1
    elif damage == "missing_parameter":
        del parameters[name]
    else:
        parameters[name]["exp_avg"] = []
    if location == "parent":
        cp["source_parent_checkpoint_sha256"] = span.checkpoint_digest(state_owner)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid checkpoint must not construct Adam")

    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    with pytest.raises(ValueError):
        owner.restore_for_inference(cp)


@pytest.mark.parametrize("damage", ["parent_hash", "parent_authority", "initial_source", "initial_state",
    "context_hash", "config", "progress", "extra_field", "nonfinite_weight"])
def test_lineage_and_closed_checkpoint_corruption_rejected(checkpoint, damage):
    cp = deepcopy(checkpoint[1])
    if damage == "parent_hash":
        cp["source_parent_checkpoint_sha256"] = "c" * 64
    elif damage == "parent_authority":
        cp["source_parent_checkpoint"]["qualified"] = True
        cp["source_parent_checkpoint_sha256"] = span.checkpoint_digest(cp["source_parent_checkpoint"])
    elif damage == "initial_source":
        cp["initial_source_model_sha256"] = "c" * 64
    elif damage == "initial_state":
        cp["initial_model_state_sha256"] = "c" * 64
    elif damage == "context_hash":
        cp["context_contract_sha256"] = "c" * 64
    elif damage == "config":
        cp["config"]["extra"] = True
    elif damage == "progress":
        cp["progress"]["optimizer_steps"] = True
    elif damage == "extra_field":
        cp["target"] = {"rules": []}
    else:
        cp["model_state"]["modality.bias"][0] = float("inf")
    with pytest.raises(ValueError):
        owner.CpuDimensionalSpanDecoder(cp)


def test_owned_checkpoint_mutation_rejected_before_decode(checkpoint, monkeypatch):
    decoder = owner.CpuDimensionalSpanDecoder(checkpoint[1])
    decoder.checkpoint["config"]["latent_enabled"] = False
    with pytest.raises(ValueError, match="owned inference checkpoint changed"):
        decoder.decode_formal_logic(["A trustee may inspect records."],
            [[.1] * checkpoint[1]["config"]["latent_dimension"]])


def test_finite_model_mutation_rejected_before_any_forward(checkpoint):
    decoder = owner.CpuDimensionalSpanDecoder(checkpoint[1])
    forwards = []
    handle = decoder.model.register_forward_pre_hook(lambda *args: forwards.append(True))
    try:
        with torch.no_grad():
            decoder.model.modality.bias[0].add_(1)
        with pytest.raises(ValueError, match="state changed before forward"):
            decoder.decode_formal_logic(["A trustee may inspect records."],
                [[.1] * checkpoint[1]["config"]["latent_dimension"]])
        assert forwards == []
    finally:
        handle.remove()


def test_model_dtype_change_rejected_before_any_forward(checkpoint):
    decoder = owner.CpuDimensionalSpanDecoder(checkpoint[1])
    forwards = []
    handle = decoder.model.register_forward_pre_hook(lambda *args: forwards.append(True))
    try:
        decoder.model.to(dtype=torch.float64)
        with pytest.raises(ValueError, match="model must remain CPU float32"):
            decoder.decode_formal_logic(["A trustee may inspect records."],
                [[.1] * checkpoint[1]["config"]["latent_dimension"]])
        assert forwards == []
    finally:
        handle.remove()


def test_zero_update_state_requires_exact_initialization(checkpoint):
    cp = deepcopy(checkpoint[0])
    cp["model_state"]["modality.bias"][0] += 1
    with pytest.raises(ValueError, match="zero-update"):
        owner.restore_for_inference(cp)


def test_source_and_context_only_inference_rejects_targets(checkpoint):
    cp = checkpoint[1]
    decoder = owner.CpuDimensionalSpanDecoder(cp)
    with pytest.raises(TypeError):
        decoder.decode_formal_logic(["A trustee may inspect records."],
            [[.1] * cp["config"]["latent_dimension"]], canonical_ir={"rules": []})
    with pytest.raises(ValueError, match="dimension"):
        decoder.decode_formal_logic(["A trustee may inspect records."], [[.1] * 8])


@pytest.mark.parametrize("setting", ["get_default_device", "get_default_dtype"])
def test_changed_process_defaults_are_refused_without_changing_them(checkpoint, monkeypatch, setting):
    value = "meta" if setting == "get_default_device" else torch.float64
    monkeypatch.setattr(torch, setting, lambda: value)
    with pytest.raises(ValueError, match="CPU/float32 Torch defaults"):
        owner.restore_for_inference(checkpoint[1])
    assert getattr(torch, setting)() == value


def test_ambient_autocast_refused_without_mutating_it(checkpoint):
    decoder = owner.CpuDimensionalSpanDecoder(checkpoint[1])
    with torch.autocast("cpu"):
        with pytest.raises(ValueError, match="forbids autocast"):
            decoder.decode_formal_logic(["A trustee may inspect records."],
                [[.1] * checkpoint[1]["config"]["latent_dimension"]])
        assert torch.is_autocast_enabled("cpu")

