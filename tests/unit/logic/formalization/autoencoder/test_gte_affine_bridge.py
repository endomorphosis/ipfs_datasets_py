"""Synthetic decoder-boundary tests, never real encoder/teacher qualification."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_affine_bridge.py"
spec = importlib.util.spec_from_file_location("gte_affine_bridge_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def bounded_test_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def transform(mode="center_rms"):
    return {"mode": mode, "mean": [0.25] * 384 if mode == "center_rms" else [0.] * 384,
            "scale": 2. if mode == "center_rms" else 1., "origin": "training_only"}


class SyntheticJointDecoder(torch.nn.Module):
    """Same forward boundary as modal_latent_formula; tiny new random weights."""
    def __init__(self, behavior="ordinary"):
        super().__init__()
        self.projection_down = torch.nn.Linear(384, 4)
        self.projection_up = torch.nn.Linear(4, 384)
        self.condition = torch.nn.Linear(384, 8)
        self.target_embedding = torch.nn.Embedding(8, 4, padding_idx=0)
        self.decoder = torch.nn.GRU(4, 8, batch_first=True)
        self.output = torch.nn.Linear(8, 8)
        self.dropout = torch.nn.Dropout(.2)
        self.behavior = behavior

    def forward(self, latent, tokens):
        self.seen_latent = latent
        projected = latent + self.projection_up(torch.tanh(self.projection_down(latent)))
        hidden = torch.tanh(self.condition(projected)).unsqueeze(0)
        logits = self.output(self.decoder(self.target_embedding(tokens), hidden)[0])
        if self.behavior == "zero":
            logits = logits * 0
        elif self.behavior == "detached":
            logits = logits.detach()
        elif self.behavior == "random":
            logits = logits + torch.rand_like(logits)
        elif self.behavior == "mutation":
            with torch.no_grad():
                self.output.bias.add_(1)
        return projected, logits


@pytest.fixture
def numerical_case():
    bridge = subject.create_affine_bridge(73)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(79)
        teacher = SyntheticJointDecoder()
    vectors = torch.linspace(-.8, .9, 2 * 768, dtype=torch.float32).reshape(2, 768)
    tokens = torch.tensor([[1, 3], [1, 4]], dtype=torch.long)
    return bridge, teacher, vectors, tokens


def compose(case, **overrides):
    bridge, teacher, vectors, tokens = case
    arguments = {"input_transform": transform(), "decoder_tokens": tokens}
    arguments.update(overrides)
    return subject.compose_teacher_logits(bridge, teacher, vectors, **arguments)


def probe(case):
    bridge, teacher, vectors, tokens = case
    return subject.probe_gradient_flow(bridge, teacher, vectors,
        input_transform=transform(), decoder_tokens=tokens)


def pack(bridge):
    return subject.pack_bridge_checkpoint(bridge, seed=73, domain_id="legal_ir",
        teacher_runtime_id="legal_ir:source_training_v2",
        source_representation_id=subject.SOURCE_REPRESENTATION_ID,
        student_representation_id=subject.STUDENT_REPRESENTATION_ID,
        teacher_checkpoint_sha256="b" * 64, input_transform=transform())


def restore(checkpoint, **overrides):
    arguments = dict(expected_domain_id="legal_ir",
        expected_teacher_runtime_id="legal_ir:source_training_v2",
        expected_source_representation_id=subject.SOURCE_REPRESENTATION_ID,
        expected_student_representation_id=subject.STUDENT_REPRESENTATION_ID,
        expected_teacher_checkpoint_sha256="b" * 64, input_transform=transform())
    arguments.update(overrides)
    return subject.load_bridge_checkpoint(checkpoint, **arguments)


def test_import_does_not_load_model_dependencies():
    code = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('isolated_bridge', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch', 'transformers', 'numpy'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(MODULE)], check=True)


def test_constructor_is_deterministic_private_and_preserves_rng():
    before = torch.get_rng_state().clone()
    threads = torch.get_num_threads()
    first, second = subject.create_affine_bridge(73), subject.create_affine_bridge(73)
    third = subject.create_affine_bridge(74)
    assert torch.equal(torch.get_rng_state(), before)
    assert torch.get_num_threads() == threads
    assert first.weight.device.type == "cpu" and first.weight.dtype == torch.float32
    assert first.weight.shape == (384, 768) and first.bias.shape == (384,)
    assert torch.equal(first.weight, second.weight) and torch.equal(first.bias, torch.zeros(384))
    assert not torch.equal(first.weight, third.weight)
    assert first.weight.data_ptr() != second.weight.data_ptr()
    assert bool((first.weight[:, :384] != 0).all())
    assert bool((first.weight[:, 384:] != 0).all())


@pytest.mark.parametrize("seed", [-1, 2**31, True, 1.2, "73"])
def test_constructor_rejects_invalid_seed(seed):
    with pytest.raises(ValueError):
        subject.create_affine_bridge(seed)


def test_real_autograd_crosses_frozen_decoder_and_saved_transform(numerical_case):
    bridge, teacher, vectors, tokens = numerical_case
    before = {name: value.clone() for name, value in teacher.state_dict().items()}
    raw_bridge = bridge(vectors)
    logits = compose(numerical_case)
    assert torch.allclose(teacher.seen_latent, (raw_bridge - .25) / 2)
    assert not torch.allclose(teacher.seen_latent.norm(dim=1), torch.ones(2))
    logits.square().mean().backward()
    assert bool((bridge.weight.grad != 0).any()) and bool((bridge.bias.grad != 0).any())
    assert all(parameter.grad is None and not parameter.requires_grad for parameter in teacher.parameters())
    assert not teacher.training
    assert all(torch.equal(value, before[name]) for name, value in teacher.state_dict().items())


def test_identity_transform_is_exact(numerical_case):
    bridge, teacher, vectors, _ = numerical_case
    compose(numerical_case, input_transform=transform("none"))
    assert torch.equal(teacher.seen_latent, bridge(vectors))


def test_probe_preserves_flags_modes_grads_rng_and_weights(numerical_case):
    bridge, teacher, _, _ = numerical_case
    teacher.behavior = "random"
    teacher.train()
    teacher.dropout.eval()
    next(teacher.parameters()).requires_grad_(False)
    for parameter in [*teacher.parameters(), *bridge.parameters()]:
        parameter.grad = torch.ones_like(parameter)
    states = {name: value.clone() for name, value in teacher.state_dict().items()}
    modes = [module.training for module in teacher.modules()]
    enabled = [parameter.requires_grad for parameter in teacher.parameters()]
    gradients = [parameter.grad.clone() for parameter in [*teacher.parameters(), *bridge.parameters()]]
    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    result = probe(numerical_case)
    assert result["status"] == "passed" and result["optimizer_steps"] == 0
    assert result["local_gradient_evidence_only"] and not result["teacher_qualified"]
    assert all(value > 0 for value in result["parameter_gradient_l2"].values())
    assert all(torch.equal(value, states[name]) for name, value in teacher.state_dict().items())
    assert [module.training for module in teacher.modules()] == modes
    assert [parameter.requires_grad for parameter in teacher.parameters()] == enabled
    assert all(torch.equal(parameter.grad, previous) for parameter, previous in zip(
        [*teacher.parameters(), *bridge.parameters()], gradients))
    assert torch.equal(torch.get_rng_state(), rng) and torch.get_num_threads() == threads


@pytest.mark.parametrize("behavior", ["zero", "detached", "mutation"])
def test_probe_rejects_broken_gradient_or_mutating_teacher_and_restores(numerical_case, behavior):
    _, teacher, _, _ = numerical_case
    teacher.behavior = behavior
    before = {name: value.clone() for name, value in teacher.state_dict().items()}
    with pytest.raises(ValueError):
        probe(numerical_case)
    assert teacher.training and all(parameter.requires_grad for parameter in teacher.parameters())
    assert all(parameter.grad is None for parameter in teacher.parameters())
    assert all(torch.equal(value, before[name]) for name, value in teacher.state_dict().items())


@pytest.mark.parametrize("invalid", ["width", "dtype", "nan", "empty", "token_batch", "token_dtype", "token_oov"])
def test_composition_rejects_bad_inputs(numerical_case, invalid):
    bridge, teacher, vectors, tokens = numerical_case
    if invalid == "width":
        vectors = vectors[:, :384]
    elif invalid == "dtype":
        vectors = vectors.double()
    elif invalid == "nan":
        vectors[0, 0] = float("nan")
    elif invalid == "empty":
        vectors, tokens = vectors[:0], tokens[:0]
    elif invalid == "token_batch":
        tokens = tokens[:1]
    elif invalid == "token_dtype":
        tokens = tokens.float()
    elif invalid == "token_oov":
        tokens[0, 0] = 4096
    with pytest.raises(ValueError):
        subject.compose_teacher_logits(bridge, teacher, vectors,
            input_transform=transform(), decoder_tokens=tokens)


@pytest.mark.parametrize("change", ["scale0", "scale_nan", "mean_width", "mean_bool", "origin", "extra", "none_mismatch"])
def test_composition_rejects_bad_transform(numerical_case, change):
    value = transform()
    if change == "scale0":
        value["scale"] = 0
    elif change == "scale_nan":
        value["scale"] = float("nan")
    elif change == "mean_width":
        value["mean"] = value["mean"][:383]
    elif change == "mean_bool":
        value["mean"][0] = True
    elif change == "origin":
        value["origin"] = "test_fit"
    elif change == "extra":
        value["extra"] = True
    elif change == "none_mismatch":
        value["mode"] = "none"
    with pytest.raises(ValueError):
        compose(numerical_case, input_transform=value)


def test_inference_mode_is_rejected(numerical_case):
    with torch.inference_mode(), pytest.raises(ValueError, match="gradient-enabled"):
        compose(numerical_case)
    with torch.no_grad(), pytest.raises(ValueError, match="gradient-enabled"):
        compose(numerical_case)


def test_checkpoint_roundtrip_preserves_weights_without_optimizer(numerical_case):
    bridge = numerical_case[0]
    checkpoint = json.loads(json.dumps(pack(bridge)))
    before = torch.get_rng_state().clone()
    loaded = restore(checkpoint)
    assert torch.equal(torch.get_rng_state(), before)
    assert loaded.weight.data_ptr() != bridge.weight.data_ptr()
    assert torch.equal(loaded.weight, bridge.weight) and torch.equal(loaded.bias, bridge.bias)
    assert "optimizer_state" not in checkpoint
    assert all(checkpoint[key] is False for key in subject.FLAGS)
    assert checkpoint["input_transform_sha256"] == subject.digest(transform())
    assert checkpoint["weights_sha256"] == subject.digest(checkpoint["model_state"])


@pytest.mark.parametrize("field,value", [("input_dimension", 786), ("output_dimension", 768),
    ("architecture", "prefix_copy"), ("proof_authority", True), ("optimizer_resume_supported", True),
    ("domain_id", "intent_ir"), ("teacher_runtime_id", "legal_ir:legacy_v1"),
    ("source_representation_id", "legal_ir:source_training_v2"),
    ("student_representation_id", "gte768"), ("teacher_checkpoint_sha256", "c" * 64),
    ("adapted_representation_id", subject.SOURCE_REPRESENTATION_ID),
    ("adapted_outputs_are_gte_small", True),
    ("input_transform_sha256", "c" * 64), ("weights_sha256", "c" * 64), ("seed", True)])
def test_checkpoint_rejects_tampered_bindings(numerical_case, field, value):
    checkpoint = pack(numerical_case[0])
    checkpoint[field] = value
    with pytest.raises(ValueError):
        restore(checkpoint)


@pytest.mark.parametrize("change", ["unknown", "bad_weight_width", "nonfinite", "overflow", "float64_rounding", "bad_bias", "weights_tamper", "transform_tamper"])
def test_checkpoint_rejects_bad_or_nonexact_state(numerical_case, change):
    checkpoint = pack(numerical_case[0])
    if change == "unknown":
        checkpoint["optimizer_state"] = {}
    elif change == "bad_weight_width":
        checkpoint["model_state"]["weight"][0] = [0.] * 384
    elif change == "nonfinite":
        checkpoint["model_state"]["weight"][0][0] = float("nan")
    elif change == "overflow":
        checkpoint["model_state"]["weight"][0][0] = 1e40
    elif change == "float64_rounding":
        checkpoint["model_state"]["weight"][0][0] = .1
    elif change == "bad_bias":
        checkpoint["model_state"]["bias"] = [0.] * 383
    elif change == "weights_tamper":
        checkpoint["model_state"]["weight"][0][0] = 0.
    elif change == "transform_tamper":
        checkpoint["input_transform"]["scale"] = 3.
    if change not in ("unknown", "nonfinite", "weights_tamper"):
        checkpoint["weights_sha256"] = subject.digest(checkpoint["model_state"])
    with pytest.raises(ValueError):
        restore(checkpoint)


def test_checkpoint_requires_external_teacher_and_transform_identity(numerical_case):
    checkpoint = pack(numerical_case[0])
    with pytest.raises(ValueError, match="external bindings"):
        restore(checkpoint, expected_teacher_checkpoint_sha256="a" * 64)
    alternate = transform()
    alternate["scale"] = 4.
    with pytest.raises(ValueError, match="input transform"):
        restore(checkpoint, input_transform=alternate)


def test_derived_adapter_identity_changes_with_frozen_teacher_pin(numerical_case):
    checkpoint = pack(numerical_case[0])
    arguments = {name: checkpoint[name] for name in ("weights_sha256", "teacher_checkpoint_sha256",
        "input_transform_sha256", "student_representation_id", "source_representation_id")}
    first = subject.adapted_representation_id(**arguments)
    arguments["teacher_checkpoint_sha256"] = "d" * 64
    second = subject.adapted_representation_id(**arguments)
    assert first == checkpoint["adapted_representation_id"] and first != second
    assert first.endswith(":d384:derived") and first != subject.SOURCE_REPRESENTATION_ID
