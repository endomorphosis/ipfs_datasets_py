"""Synthetic 4096D architecture and closed-state controls; no fits or encoders.

The retained-positive-step fixtures below are deliberately fabricated numerical
states to test Adam/parent validation. They are not training or Leanstral output
evidence, are never saved as production checkpoints and grant no authority.
"""
from copy import deepcopy
import hashlib
import json
import os

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span


SETTINGS = dict(hidden_size=8, embedding_dim=4, projection_width=4, batch_size=1, seed=1729)
CONTEXT = {"dimension": 4096, "representation_id": "synthetic-native4096-architecture-control-only",
           "producer_sha256": "d" * 64, "training_index_sha256": "e" * 64}


def examples():
    return [{"id": "synthetic-4096-row", "source_text": "Lark must retain books.",
             "canonical_ir": {"rules": [{"modality": "O", "actor": "Lark", "action": "retain",
                 "object": "books", "conditions": [], "exceptions": [], "temporal": []}]},
             "latent": [.125] * 4096}]


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    return head.build_synthetic_fixture(examples(), context_contract=CONTEXT, **SETTINGS)


def moments(state, step=1):
    return {"schema": "adam-default-betas-eps/v1", "parameters": {
        name: {"step": step, "exp_avg": torch.zeros_like(torch.tensor(value)).tolist(),
               "exp_avg_sq": torch.zeros_like(torch.tensor(value)).tolist()}
        for name, value in state.items()}}


def retained_state(checkpoint):
    result = deepcopy(checkpoint)
    result["provenance"] = head._provenance(head._CALLER_KIND)
    result["progress"] = {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1}
    result["parent_checkpoint_sha256"] = "c" * 64
    result["optimizer_state"] = moments(result["model_state"])
    return result


def source_parent():
    config = span._config(latent_dimension=0, latent_enabled=False, learning_rate=.003,
        residual_scale=.25, **SETTINGS)
    model = head._fresh_model(torch, config)
    state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    return {"schema": span.SCHEMA, "lineage_id": span.LINEAGE_ID, "config": config,
        "implementation": span._implementation(), "training_manifest_sha256": "a" * 64,
        "training_count": 1, "tuning_manifest_sha256": "b" * 64, "tuning_count": 0,
        "model_state": state, "optimizer_state": moments(state),
        "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
        "parent_checkpoint_sha256": "c" * 64, **span.FALSE}


def test_actual4096_tensor_separate_lineage_and_untrained_provenance(checkpoint):
    assert checkpoint["schema"] == head.SCHEMA != dimensions.SCHEMA
    assert checkpoint["lineage_id"] == head.LINEAGE_ID != dimensions.LINEAGE_ID
    assert dimensions.DIMENSIONS == (0, 8, 384, 768)
    assert checkpoint["config"]["latent_dimension"] == 4096
    assert torch.tensor(checkpoint["model_state"]["latent_down.weight"]).shape == (4, 4096)
    assert checkpoint["optimizer_state"]["parameters"] == {}
    assert checkpoint["progress"]["optimizer_steps"] == 0
    assert checkpoint["provenance"] == {"schema": "native-4096-source-span-provenance/v1",
        "kind": "synthetic_untrained_architecture_control", "synthetic_embeddings": True,
        "trusted_native_owner_verified": False}
    assert all(checkpoint[name] is False for name in span.FALSE)


def test_public_builder_is_untrusted_and_has_own_fresh_adam():
    result = head.build_checkpoint(examples(), context_contract=CONTEXT, **SETTINGS)
    assert result["provenance"]["kind"] == "caller_supplied_native_vectors"
    assert result["provenance"]["trusted_native_owner_verified"] is False
    assert result["optimizer_state"]["parameters"] == {}
    decoder = head.Leanstral4096SpanDecoder(result)
    with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
        decoder.decode_formal_logic([examples()[0]["source_text"]], [examples()[0]["latent"]])


def test_private_loader_has_no_optimizer_no_cuda_seed_and_preserves_rng(checkpoint, monkeypatch):
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    def forbidden(*args, **kwargs):
        raise AssertionError("optimizer or global seed touched during inference restoration")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(torch, "manual_seed", forbidden)
    model = head._restore_for_inference(torch, checkpoint)
    assert next(model.parameters()).device.type == "cpu"
    assert next(model.parameters()).dtype == torch.float32
    assert span._raw(checkpoint) == before
    assert torch.equal(rng, torch.get_rng_state())
    head.validate_checkpoint(checkpoint)


def test_retained_adam_inference_and_training_restore_are_serialization_equivalent(checkpoint, monkeypatch):
    retained = retained_state(checkpoint)
    expected = deepcopy(retained)
    _, model, optimizer = head._restore(retained)
    weights, saved_moments = span._pack(model, optimizer)
    assert span._raw(weights) == span._raw(retained["model_state"])
    assert span._raw(saved_moments) == span._raw(retained["optimizer_state"])
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("inference constructs Adam"))
    head._restore_for_inference(torch, retained)
    assert retained == expected


def test_source_parent_copies_only_source_tensors_and_no_adam_transfer():
    parent = source_parent()
    before = span._raw(parent)
    result = head.build_checkpoint(examples(), context_contract=CONTEXT, source_parent=parent, **SETTINGS)
    assert head._source_state(result["model_state"]) == parent["model_state"]
    assert result["source_parent_checkpoint_sha256"] == span.checkpoint_digest(parent)
    assert result["source_parent_optimizer_steps"] == 1
    assert result["progress"]["optimizer_steps"] == 0
    assert result["optimizer_state"]["parameters"] == {}
    assert not bool(torch.tensor(result["model_state"]["latent_up.weight"]).count_nonzero())
    assert not bool(torch.tensor(result["model_state"]["latent_up.bias"]).count_nonzero())
    head.validate_checkpoint(result)
    assert span._raw(parent) == before


@pytest.mark.parametrize("width", [8, 384, 768, 4095, 4097])
def test_builder_rejects_every_wrong_vector_width(width):
    rows = examples()
    rows[0]["latent"] = [.1] * width
    with pytest.raises(ValueError, match="dimension"):
        head.build_synthetic_fixture(rows, context_contract=CONTEXT, **SETTINGS)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.0", 1e39])
def test_builder_rejects_nonfinite_nonplain_or_overflow_vectors(value):
    rows = examples()
    rows[0]["latent"][42] = value
    with pytest.raises(ValueError):
        head.build_synthetic_fixture(rows, context_contract=CONTEXT, **SETTINGS)


@pytest.mark.parametrize("field,value", [("dimension", 768), ("dimension", True), ("producer_sha256", "F" * 64),
    ("training_index_sha256", "x"), ("representation_id", " "), ("representation_id", "x" * 513)])
def test_context_contract_is_closed_and_native4096(field, value):
    context = deepcopy(CONTEXT)
    context[field] = value
    with pytest.raises(ValueError):
        head.build_synthetic_fixture(examples(), context_contract=context, **SETTINGS)


@pytest.mark.parametrize("mutation", ["extra", "schema", "lineage", "authority", "implementation", "configuration",
    "context_digest", "initial_source", "initial_model", "training_count", "tuning_count", "training_hash",
    "progress_type", "progress_identity", "preceding_hash", "source_parent_hash", "source_parent_steps",
    "weights_keys", "weights_shape", "weights_nonfinite", "weights_rounding", "weights_zero_update", "provenance"])
def test_closed_checkpoint_rejects_mutated_state(checkpoint, mutation):
    changed = deepcopy(checkpoint)
    if mutation == "extra": changed["extra"] = None
    elif mutation == "schema": changed["schema"] = dimensions.SCHEMA
    elif mutation == "lineage": changed["lineage_id"] = dimensions.LINEAGE_ID
    elif mutation == "authority": changed["proof_authority"] = True
    elif mutation == "implementation": changed["implementation"]["native4096_sha256"] = "a" * 64
    elif mutation == "configuration": changed["config"]["latent_dimension"] = 768
    elif mutation == "context_digest": changed["context_contract"]["producer_sha256"] = "a" * 64
    elif mutation == "initial_source": changed["initial_source_model_sha256"] = "a" * 64
    elif mutation == "initial_model": changed["initial_model_state_sha256"] = "a" * 64
    elif mutation == "training_count": changed["training_count"] = True
    elif mutation == "tuning_count": changed["tuning_count"] = -1
    elif mutation == "training_hash": changed["training_manifest_sha256"] = "x"
    elif mutation == "progress_type": changed["progress"]["row_cursor"] = False
    elif mutation == "progress_identity": changed["progress"]["optimizer_steps"] = 1
    elif mutation == "preceding_hash": changed["parent_checkpoint_sha256"] = "a" * 64
    elif mutation == "source_parent_hash": changed["source_parent_checkpoint_sha256"] = "a" * 64
    elif mutation == "source_parent_steps": changed["source_parent_optimizer_steps"] = True
    elif mutation == "weights_keys": changed["model_state"]["unexpected"] = []
    elif mutation == "weights_shape": changed["model_state"]["latent_down.weight"][0].pop()
    elif mutation == "weights_nonfinite": changed["model_state"]["latent_down.weight"][0][0] = float("nan")
    elif mutation == "weights_rounding": changed["model_state"]["latent_down.weight"][0][0] = .10000000000001
    elif mutation == "weights_zero_update": changed["model_state"]["latent_down.weight"][0][0] = .125
    elif mutation == "provenance": changed["provenance"]["trusted_native_owner_verified"] = True
    with pytest.raises(ValueError):
        head._restore_for_inference(torch, changed)


@pytest.mark.parametrize("mutation", ["keys", "step", "first_shape", "second_shape", "nonfinite", "negative", "rounding"])
def test_retained_adam_rejects_corruption_without_optimizer(checkpoint, mutation, monkeypatch):
    retained = retained_state(checkpoint)
    name = "latent_down.weight"
    if mutation == "keys": del retained["optimizer_state"]["parameters"][name]
    elif mutation == "step": retained["optimizer_state"]["parameters"][name]["step"] = 2
    elif mutation == "first_shape": retained["optimizer_state"]["parameters"][name]["exp_avg"][0].pop()
    elif mutation == "second_shape": retained["optimizer_state"]["parameters"][name]["exp_avg_sq"][0].pop()
    elif mutation == "nonfinite": retained["optimizer_state"]["parameters"][name]["exp_avg"][0][0] = float("inf")
    elif mutation == "negative": retained["optimizer_state"]["parameters"][name]["exp_avg_sq"][0][0] = -.1
    elif mutation == "rounding": retained["optimizer_state"]["parameters"][name]["exp_avg"][0][0] = .10000000000001
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("inference constructs Adam"))
    with pytest.raises(ValueError):
        head._restore_for_inference(torch, retained)


def test_adam_step_float32_rounding_cannot_change_resumed_counter(checkpoint):
    retained = retained_state(checkpoint)
    steps = 2**24 + 1
    retained["progress"] = {"epochs_completed": steps, "row_cursor": 0, "optimizer_steps": steps}
    for moment in retained["optimizer_state"]["parameters"].values():
        moment["step"] = steps
    with pytest.raises(ValueError, match="not exactly representable as float32"):
        head._restore_for_inference(torch, retained)


def test_synthetic_fixture_cannot_claim_positive_steps(checkpoint):
    changed = retained_state(checkpoint)
    changed["provenance"] = deepcopy(checkpoint["provenance"])
    with pytest.raises(ValueError, match="must remain untrained"):
        head.validate_checkpoint(changed)


def test_synthetic_fixture_cannot_fit(checkpoint, monkeypatch):
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("blocked training constructs Adam"))
    with pytest.raises(ValueError, match="cannot be trained"):
        head.train_decoder(checkpoint, examples(), max_steps=1)


def test_caller_vectors_cannot_fit_without_trusted_owner(monkeypatch):
    checkpoint = head.build_checkpoint(examples(), context_contract=CONTEXT, **SETTINGS)
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("blocked training constructs Adam"))
    with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
        head.train_decoder(checkpoint, examples(), max_steps=1)


def test_synthetic4096_gradient_shape_and_finiteness_without_optimizer_step(checkpoint):
    before = span._raw(checkpoint)
    model = head._restore_for_inference(torch, checkpoint)
    records, _ = span._splits(examples(), [], 4096)
    loss = span._loss(torch, model, records)
    assert bool(torch.isfinite(loss))
    loss.backward()
    assert all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
               for parameter in model.parameters())
    assert tuple(model.latent_down.weight.grad.shape) == (4, 4096)
    assert bool(model.latent_up.weight.grad.count_nonzero())
    assert not bool(model.latent_down.weight.grad.count_nonzero())
    assert span._raw(checkpoint) == before
    assert checkpoint["progress"]["optimizer_steps"] == 0


def test_index4095_reaches_actual_adapter_without_truncation_or_fit(checkpoint, monkeypatch):
    before = span._raw(checkpoint)
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("architecture control constructs optimizer"))
    model = head._restore_for_inference(torch, checkpoint)
    # Modify only this unsaved temporary synthetic model to isolate its final
    # input coordinate. This is wiring evidence, not an optimizer update.
    with torch.no_grad():
        model.latent_down.weight.zero_()
        model.latent_down.bias.zero_()
        model.latent_down.weight[0, 4095] = .25
        model.latent_up.weight.zero_()
        model.latent_up.bias.zero_()
        model.latent_up.weight[0, 0] = .5
        tokens = span.tokenize_source(examples()[0]["source_text"])
        zero, final = [0.] * 4096, [0.] * 4096
        final[4095] = 1.
        baseline = model(*span._batch(torch, [{"tokens": tokens, "latent": zero}]))
        reached = model(*span._batch(torch, [{"tokens": tokens, "latent": final}]))
    assert all(bool(torch.isfinite(value).all()) for value in reached.values())
    assert any(not torch.equal(baseline[name], reached[name]) for name in baseline)
    assert span._raw(checkpoint) == before
    assert checkpoint["progress"]["optimizer_steps"] == 0


def test_zero_step_resume_is_exact_and_does_not_fit(checkpoint, monkeypatch):
    before = span._raw(checkpoint)
    monkeypatch.setattr(torch.optim.Adam, "step", lambda *a, **kw: pytest.fail("fit executed"))
    result = head.train_decoder(checkpoint, examples(), max_steps=0, max_seconds=0)
    assert span._raw(result["checkpoint"]) == before
    assert result["report"]["training_executed"] is False
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["new_optimizer_steps_total"] == 0


@pytest.mark.parametrize("split", ["training", "tuning"])
def test_resume_rejects_changed_manifests_without_fit(checkpoint, monkeypatch, split):
    monkeypatch.setattr(torch.optim.Adam, "step", lambda *a, **kw: pytest.fail("fit executed"))
    training, tuning = examples(), []
    if split == "training": training[0]["id"] = "changed"
    else: tuning = examples()
    with pytest.raises(ValueError, match="manifests differ"):
        head.train_decoder(checkpoint, training, tuning, max_steps=0)


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_cpu_singleton_reference_uses_original_decisions_and_preserves_state(checkpoint, ablation):
    decoder = head.Leanstral4096SpanDecoder(checkpoint)
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    texts, vectors = ["Lark must retain books.", "Wren may publish records."], [[.1] * 4096, [.2] * 4096]
    result = decoder.decode_formal_logic(texts, vectors, latent_ablation=ablation)
    assert result["input_dimension"] == 4096
    assert result["synthetic_architecture_control"] is True
    assert result["training_executed"] is False
    assert result["trusted_native_owner_verified"] is False
    assert all(result[name] is False for name in span.FALSE)
    assert span._raw(checkpoint) == before
    assert torch.equal(torch.get_rng_state(), rng)
    actual = [[0.] * 4096 for _ in vectors] if ablation == "zero" else vectors[1:] + vectors[:1] if ablation == "rotate" else vectors
    expected = [span.SpanLegalFormulaDecoder._decode(decoder, text, vector, enabled=ablation != "disabled")
                for text, vector in zip(texts, actual)]
    assert result["rows"] == expected


def test_owned_checkpoint_and_model_mutation_refuse(checkpoint):
    decoder = head.Leanstral4096SpanDecoder(checkpoint)
    decoder.checkpoint["context_contract"]["producer_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="checkpoint changed"):
        decoder.decode_formal_logic(["Lark must retain books."], [[.1] * 4096])
    decoder = head.Leanstral4096SpanDecoder(checkpoint)
    with torch.no_grad():
        next(decoder.model.parameters()).add_(.125)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic(["Lark must retain books."], [[.1] * 4096])


def test_runtime_kernel_identity_drift_refuses(checkpoint, monkeypatch):
    monkeypatch.setattr(span, "_model", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="implementation changed"):
        head.validate_checkpoint(checkpoint)


def test_exact_file_roundtrip_without_replacement(checkpoint, tmp_path):
    path = tmp_path / "synthetic-control.json"
    receipt = head.save_checkpoint(checkpoint, path)
    assert receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert span._raw(head.load_checkpoint(path, expected_sha256=receipt["sha256"])) == span._raw(checkpoint)
    with pytest.raises(FileExistsError):
        head.save_checkpoint(checkpoint, path)
    with pytest.raises(ValueError, match="hash differs"):
        head.load_checkpoint(path, expected_sha256="0" * 64)


def test_file_symlink_and_hardlink_refuse(checkpoint, tmp_path):
    path = tmp_path / "synthetic-control.json"
    receipt = head.save_checkpoint(checkpoint, path)
    link = tmp_path / "symlink.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="canonical"):
        head.load_checkpoint(link, expected_sha256=receipt["sha256"])
    alias = tmp_path / "alias.json"
    os.link(path, alias)
    with pytest.raises(ValueError, match="nonaliased"):
        head.load_checkpoint(path, expected_sha256=receipt["sha256"])


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_strict_json_file_rejects_duplicate_keys_and_constants(raw, tmp_path):
    path = tmp_path / "malformed.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        head.load_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())
