"""Private CPU affine adapter and differentiable frozen-decoder boundary.

This helper imports Torch only when numerical work is requested. It neither
loads an encoder nor authenticates the supplied teacher against a checkpoint.
Callers must admit that checkpoint separately. The source vector-space label
does not authenticate archived vectors. No optimizer or qualification is saved.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re


SCHEMA = "gte-affine-bridge/v1"
ARCHITECTURE = "affine_cpu_float32/v1"
SOURCE_DIMENSION = 768
TARGET_DIMENSION = 384
SOURCE_REPRESENTATION_ID = (
    "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
    "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
STUDENT_REPRESENTATION_ID = (
    "Alibaba-NLP/gte-multilingual-base@9bbca17d9273fd0d03d5725c7a4b0f6b45142062:"
    "code=Alibaba-NLP/new-impl@40ced75c3017eb27626c9d4ea981bde21a2662f4:"
    "d768:pool=cls:norm=l2:cpu:float32:tokens8192:reject_overlength:v1")
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
FLAGS = {"proof_authority": False, "source_fidelity_qualified": False,
         "encoder_numerics_verified": False, "optimizer_resume_supported": False,
         "adapted_outputs_are_gte_small": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"schema", "architecture", "input_dimension", "output_dimension", "seed",
           "domain_id", "teacher_runtime_id", "source_representation_id",
           "student_representation_id", "teacher_checkpoint_sha256", "input_transform",
           "input_transform_sha256", "model_state", "weights_sha256",
           "adapted_representation_id", *FLAGS}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("finite canonical JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), "full lowercase " + label + " SHA256 required")
    return value


def _seed(value):
    _require(type(value) is int and 0 <= value < 2**31, "bounded integer seed required")
    return value


def validate_input_transform(value):
    """Validate exactly the saved source_training_v2 normalization convention."""
    _require(type(value) is dict and set(value) == {"mode", "mean", "scale", "origin"},
             "closed source input transform required")
    _require(value["mode"] in ("none", "center_rms") and value["origin"] == "training_only",
             "saved training-only input transform required")
    mean, scale = value["mean"], value["scale"]
    _require(type(mean) is list and len(mean) == TARGET_DIMENSION and all(
        type(item) in (int, float) and math.isfinite(item) and abs(item) <= 1e8 for item in mean),
        "finite 384D transform mean required")
    _require(type(scale) in (int, float) and math.isfinite(scale) and .01 <= scale <= 1e8,
             "finite bounded transform scale required")
    if value["mode"] == "none":
        _require(mean == [0.] * TARGET_DIMENSION and scale == 1., "identity transform differs")
    return deepcopy(value)


def _torch():
    import torch
    return torch


def create_affine_bridge(seed=1729):
    """Create independent 768→384 weights; preserve process RNG and thread settings."""
    seed = _seed(seed)
    torch = _torch()
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    # Linear's constructor consumes the process CPU RNG; discard that draw.
    with torch.random.fork_rng(devices=[]):
        bridge = torch.nn.Linear(SOURCE_DIMENSION, TARGET_DIMENSION, bias=True,
                                 device="cpu", dtype=torch.float32)
    with torch.no_grad():
        bridge.weight.normal_(mean=0., std=.02, generator=generator)
        bridge.bias.zero_()
    return bridge


def _bridge(torch, bridge):
    _require(type(bridge) is torch.nn.Linear and bridge.in_features == SOURCE_DIMENSION
             and bridge.out_features == TARGET_DIMENSION and bridge.bias is not None,
             "exact private 768 to 384 affine bridge required")
    _require(tuple(bridge.weight.shape) == (TARGET_DIMENSION, SOURCE_DIMENSION)
             and tuple(bridge.bias.shape) == (TARGET_DIMENSION,), "bridge parameter shapes differ")
    for parameter in bridge.parameters():
        _require(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                 and parameter.requires_grad and bool(torch.isfinite(parameter).all()),
                 "finite trainable CPU float32 bridge parameters required")


def _inputs(torch, vectors, tokens):
    _require(isinstance(vectors, torch.Tensor) and vectors.device.type == "cpu"
             and vectors.dtype == torch.float32 and vectors.ndim == 2
             and 1 <= vectors.shape[0] <= 256 and vectors.shape[1] == SOURCE_DIMENSION
             and bool(torch.isfinite(vectors).all()), "finite batched CPU float32 768D input required")
    _require(isinstance(tokens, torch.Tensor) and tokens.device.type == "cpu"
             and tokens.dtype == torch.long and tokens.ndim == 2
             and tokens.shape[0] == vectors.shape[0] and 1 <= tokens.shape[1] <= 1024
             and bool((tokens >= 0).all()) and bool((tokens < 4096).all()),
             "bounded CPU int64 decoder prefixes required")


def _teacher(torch, teacher, bridge):
    _require(isinstance(teacher, torch.nn.Module), "explicit differentiable teacher module required")
    private_storages = {parameter.untyped_storage().data_ptr() for parameter in bridge.parameters()}
    parameters = list(teacher.parameters())
    _require(bool(parameters), "teacher parameters required")
    for tensor in [*parameters, *teacher.buffers()]:
        _require(tensor.device.type == "cpu" and (not tensor.is_floating_point()
                 or tensor.dtype == torch.float32) and bool(torch.isfinite(tensor).all()),
                 "finite CPU float32 teacher required")
        _require(tensor.untyped_storage().data_ptr() not in private_storages,
                 "bridge and teacher cannot share parameter storage")
    teacher.eval()
    for parameter in parameters:
        parameter.requires_grad_(False)


def compose_teacher_logits(bridge, teacher_model, student_vectors768, *,
                           input_transform, decoder_tokens):
    """Freeze the supplied teacher and retain autograd through its decoder.

    Freezing persists after this call. Existing teacher gradients are preserved;
    no new teacher gradient is accumulated. Prefix tokens are an explicit input,
    suitable for a training loss, and do not imply free-running IR evaluation.
    Unlike Runtime.infer, this path must not run under inference_mode/no_grad.
    No adapter L2 normalization, clipping, padding or prefix copying is applied.
    """
    transform = validate_input_transform(input_transform)
    torch = _torch()
    _bridge(torch, bridge)
    _inputs(torch, student_vectors768, decoder_tokens)
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled decoder composition required")
    _teacher(torch, teacher_model, bridge)
    mean = torch.tensor(transform["mean"], dtype=torch.float32, device="cpu")
    data = (bridge(student_vectors768) - mean) / transform["scale"]
    _require(bool(torch.isfinite(data).all()), "nonfinite normalized bridge output")
    output = teacher_model(data, decoder_tokens)
    _require(type(output) is tuple and len(output) == 2, "teacher projected/logits forward boundary required")
    projected, logits = output
    _require(isinstance(projected, torch.Tensor) and projected.shape == data.shape
             and projected.device.type == "cpu" and projected.dtype == torch.float32
             and bool(torch.isfinite(projected).all()), "finite teacher projection required")
    _require(isinstance(logits, torch.Tensor) and logits.ndim == 3
             and logits.shape[:2] == decoder_tokens.shape and 1 <= logits.shape[2] <= 4096
             and bool((decoder_tokens < logits.shape[2]).all())
             and logits.device.type == "cpu" and logits.dtype == torch.float32
             and bool(torch.isfinite(logits).all()) and logits.requires_grad,
             "finite differentiable teacher token logits required")
    return logits


def probe_gradient_flow(bridge, teacher_model, student_vectors768, *,
                        input_transform, decoder_tokens):
    """Check a local gradient path, preserving model states and process CPU RNG.

    This deterministic diagnostic performs no optimizer step. Its inputs may be
    synthetic; it cannot qualify an encoder, teacher, IR, or training objective.
    A nonzero diagnostic derivative is necessary local evidence, not evidence
    that every later loss or input will yield an informative gradient.
    """
    torch = _torch()
    _bridge(torch, bridge)
    _require(isinstance(teacher_model, torch.nn.Module), "teacher module required")
    state = {name: value.detach().clone() for name, value in teacher_model.state_dict().items()}
    bridge_state = {name: value.detach().clone() for name, value in bridge.state_dict().items()}
    modes = [(module, module.training) for module in teacher_model.modules()]
    flags = [(parameter, parameter.requires_grad) for parameter in teacher_model.parameters()]
    gradients = [(parameter, None if parameter.grad is None else parameter.grad.detach().clone())
                 for parameter in [*teacher_model.parameters(), *bridge.parameters()]]
    try:
        with torch.random.fork_rng(devices=[]):
            logits = compose_teacher_logits(bridge, teacher_model, student_vectors768,
                input_transform=input_transform, decoder_tokens=decoder_tokens)
            coefficients = torch.linspace(.5, 1.5, logits.numel(), dtype=torch.float32).reshape(logits.shape)
            objective = (logits * coefficients).mean()
            derivatives = torch.autograd.grad(objective, tuple(bridge.parameters()),
                                               allow_unused=True)
        _require(all(gradient is not None and bool(torch.isfinite(gradient).all())
                     and bool((gradient != 0).any()) for gradient in derivatives),
                 "adapter gradient path is absent, zero or nonfinite")
        _require(all(torch.equal(state[name], value) for name, value in teacher_model.state_dict().items())
                 and set(state) == set(teacher_model.state_dict()), "teacher state changed during probe")
        _require(all(torch.equal(bridge_state[name], value) for name, value in bridge.state_dict().items()),
                 "bridge weights changed during probe")
        _require(all((parameter.grad is None if previous is None else parameter.grad is not None
                      and torch.equal(parameter.grad, previous)) for parameter, previous in gradients),
                 "parameter gradients changed during probe")
        return {"schema": "gte-affine-gradient-probe/v1", "status": "passed",
                "input_rows": student_vectors768.shape[0], "decoder_prefix_length": decoder_tokens.shape[1],
                "parameter_gradient_l2": {name: float(derivative.double().norm())
                    for (name, _), derivative in zip(bridge.named_parameters(), derivatives)},
                "teacher_state_unchanged": True, "bridge_state_unchanged": True,
                "existing_parameter_gradients_unchanged": True, "optimizer_steps": 0,
                "synthetic_or_caller_supplied_inputs": True, "teacher_qualified": False,
                "local_gradient_evidence_only": True, **FLAGS}
    finally:
        # A custom trusted forward may mutate state; never leave that mutation
        # behind after a diagnostic failure.
        teacher_model.load_state_dict(state, strict=True)
        bridge.load_state_dict(bridge_state, strict=True)
        for module, mode in modes:
            module.training = mode
        for parameter, enabled in flags:
            parameter.requires_grad_(enabled)
        for parameter, previous in gradients:
            if previous is None:
                parameter.grad = None
            elif parameter.grad is None or not torch.equal(parameter.grad, previous):
                parameter.grad = previous


def _bindings(*, domain_id, teacher_runtime_id, source_representation_id,
              student_representation_id, teacher_checkpoint_sha256):
    _require(domain_id in DOMAINS and teacher_runtime_id == domain_id + ":source_training_v2",
             "exact domain source_training_v2 runtime binding required")
    _require(source_representation_id == SOURCE_REPRESENTATION_ID,
             "exact 384D source vector-space identity required")
    _require(student_representation_id == STUDENT_REPRESENTATION_ID,
             "exact 768D student producer identity required")
    _hash(teacher_checkpoint_sha256, "teacher checkpoint")


def adapted_representation_id(*, weights_sha256, teacher_checkpoint_sha256,
                              input_transform_sha256, student_representation_id,
                              source_representation_id):
    """Name derived adapter coordinates, distinct from genuine GTE-small vectors."""
    binding = {"weights_sha256": _hash(weights_sha256, "weights"),
        "teacher_checkpoint_sha256": _hash(teacher_checkpoint_sha256, "teacher checkpoint"),
        "input_transform_sha256": _hash(input_transform_sha256, "input transform"),
        "student_representation_id": student_representation_id,
        "source_representation_id": source_representation_id}
    _require(student_representation_id == STUDENT_REPRESENTATION_ID
             and source_representation_id == SOURCE_REPRESENTATION_ID,
             "exact adapter alignment reference identities required")
    return "gte-affine-bridge/v1@sha256:" + digest(binding) + ":d384:derived"


def pack_bridge_checkpoint(bridge, *, seed, domain_id, teacher_runtime_id,
                           source_representation_id, student_representation_id,
                           teacher_checkpoint_sha256, input_transform):
    """Serialize private adapter weights and declarations, without optimizer state.

    source_representation_id names the alignment reference. Adapter outputs have
    their own adapted_representation_id and are never authenticated GTE-small.
    """
    torch = _torch()
    _bridge(torch, bridge)
    seed = _seed(seed)
    _bindings(domain_id=domain_id, teacher_runtime_id=teacher_runtime_id,
              source_representation_id=source_representation_id,
              student_representation_id=student_representation_id,
              teacher_checkpoint_sha256=teacher_checkpoint_sha256)
    transform = validate_input_transform(input_transform)
    state = {name: value.detach().tolist() for name, value in bridge.state_dict().items()}
    checkpoint = {"schema": SCHEMA, "architecture": ARCHITECTURE,
        "input_dimension": SOURCE_DIMENSION, "output_dimension": TARGET_DIMENSION, "seed": seed,
        "domain_id": domain_id, "teacher_runtime_id": teacher_runtime_id,
        "source_representation_id": source_representation_id,
        "student_representation_id": student_representation_id,
        "teacher_checkpoint_sha256": teacher_checkpoint_sha256,
        "input_transform": transform, "input_transform_sha256": digest(transform),
        "model_state": state, "weights_sha256": digest(state), **FLAGS}
    checkpoint["adapted_representation_id"] = adapted_representation_id(**{
        name: checkpoint[name] for name in ("weights_sha256", "teacher_checkpoint_sha256",
            "input_transform_sha256", "student_representation_id", "source_representation_id")})
    _require(len(_raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, "bridge checkpoint exceeds byte bound")
    return checkpoint


def _validate_state(state):
    _require(type(state) is dict and set(state) == {"weight", "bias"}, "closed affine state required")
    _require(type(state["weight"]) is list and len(state["weight"]) == TARGET_DIMENSION,
             "bridge weight output dimension differs")
    arrays = [state["bias"]]
    for row in state["weight"]:
        _require(type(row) is list and len(row) == SOURCE_DIMENSION, "bridge weight input dimension differs")
        arrays.append(row)
    _require(type(state["bias"]) is list and len(state["bias"]) == TARGET_DIMENSION,
             "bridge bias dimension differs")
    _require(all(type(value) in (int, float) and math.isfinite(value) for row in arrays for value in row),
             "finite numerical affine state required")


def load_bridge_checkpoint(checkpoint, *, expected_domain_id, expected_teacher_runtime_id,
                           expected_source_representation_id, expected_student_representation_id,
                           expected_teacher_checkpoint_sha256, input_transform):
    """Restore an exact adapter with externally supplied expected bindings."""
    _require(type(checkpoint) is dict and set(checkpoint) == _FIELDS and checkpoint["schema"] == SCHEMA,
             "closed bridge checkpoint required")
    _require(len(_raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, "bridge checkpoint exceeds byte bound")
    _require(checkpoint["architecture"] == ARCHITECTURE
             and type(checkpoint["input_dimension"]) is int and checkpoint["input_dimension"] == SOURCE_DIMENSION
             and type(checkpoint["output_dimension"]) is int and checkpoint["output_dimension"] == TARGET_DIMENSION,
             "exact affine dimensions and architecture required")
    _require(all(checkpoint[name] is False for name in FLAGS), "bridge cannot grant qualification or authority")
    expected = {"domain_id": expected_domain_id, "teacher_runtime_id": expected_teacher_runtime_id,
        "source_representation_id": expected_source_representation_id,
        "student_representation_id": expected_student_representation_id,
        "teacher_checkpoint_sha256": expected_teacher_checkpoint_sha256}
    _bindings(**expected)
    _require(all(checkpoint[name] == value for name, value in expected.items()), "bridge external bindings differ")
    transform = validate_input_transform(checkpoint["input_transform"])
    _require(transform == validate_input_transform(input_transform)
             and _hash(checkpoint["input_transform_sha256"], "input transform") == digest(transform),
             "bridge input transform binding differs")
    state = checkpoint["model_state"]
    _validate_state(state)
    _require(_hash(checkpoint["weights_sha256"], "weights") == digest(state), "bridge weights digest differs")
    _require(checkpoint["adapted_representation_id"] == adapted_representation_id(**{
        name: checkpoint[name] for name in ("weights_sha256", "teacher_checkpoint_sha256",
            "input_transform_sha256", "student_representation_id", "source_representation_id")}),
        "derived adapted representation identity differs")
    bridge = create_affine_bridge(checkpoint["seed"])
    torch = _torch()
    tensors = {name: torch.tensor(value, dtype=torch.float32, device="cpu") for name, value in state.items()}
    _require(all(bool(torch.isfinite(value).all()) for value in tensors.values()), "bridge state overflows float32")
    # A serialized state must itself be exact float32 values, not merely round
    # to a different tensor while retaining its caller-supplied JSON digest.
    _require(digest({name: value.tolist() for name, value in tensors.items()}) == checkpoint["weights_sha256"],
             "bridge state is not exact float32 serialization")
    bridge.load_state_dict(tensors, strict=True)
    return bridge
