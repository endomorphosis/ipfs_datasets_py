"""Experimental reference supervision through both private 768D interfaces.

Admission is dependency-free and requires a complete joined native-input plan.
The two archived vocabularies retain separate token-normalized CE objectives.
Unqualified replay logits are never used as a distillation target. No function
creates an optimizer, updates weights, runs an encoder, or qualifies a teacher.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path


OBJECTIVE_SCHEMA = "gte-native-reference-objective/v1"
PROBE_SCHEMA = "gte-native-reference-gradient-probe/v1"
HEADS = ("primary384", "legacy8")
INTERFACES = ("primary.input_adapter.weight", "primary.input_adapter.bias",
              "auxiliary_connector.weight", "auxiliary_connector.bias")
FLAGS = {
    "reference_supervised_objective_computed": True,
    "input_adapter_exercised": True,
    "auxiliary_connector_exercised": True,
    "native768_inputs_used": True,
    "encoder_inference_executed": False,
    "download_executed": False,
    "producer_execution_authenticated": False,
    "training_executed": False,
    "distillation_executed": False,
    "teacher_qualified": False,
    "production_kd_enabled": False,
    "production_kd_eligible": False,
    "source_fidelity_qualified": False,
    "proof_authority": False,
}
_PROFILE = {"device": "cpu", "dtype": "float32", "threads": 1,
            "evaluation_mode": True}
_HEAD_FIELDS = {"loss", "reference_token_count", "excluded_token_count", "row_count",
                "codec_sha256", "head_weight"}
_GRAD_FIELDS = {"shape", "element_count", "finite", "nonzero", "max_abs", "l2_norm"}
_PROBE_FIELDS = {"schema", "status", "plan_sha256", "batch_sha256", "replay_sha256",
    "initialization_representation_id", "donor_pins", "objective", "head_normalization",
    "head_weights", "loss", "heads", "interface_gradients", "inherited_tensor_count",
    "inherited_gradients_absent", "all_26_inherited_tensors_unchanged",
    "model_state_sha256_before", "model_state_sha256_after", "whole_model_state_unchanged",
    "original_decoder_initialization_unchanged", "gradient_probe_executed",
    "logits_combined", "optimizer_steps", "numerical_profile", "implementation", *FLAGS}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_native_objective_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load native objective dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _implementation():
    names = ("gte_decoder_native_objective", "gte_decoder_native_batch",
             "gte_decoder_transfer_replay", "gte_decoder_reuse", "gte_decoder_warm_start",
             "gte_legacy8_decoder_donor")
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _weights(head_weights, *, probe=False):
    weights = dict.fromkeys(HEADS, 1.) if head_weights is None else deepcopy(head_weights)
    _require(type(weights) is dict and set(weights) == set(HEADS), "closed independent head weights required")
    for value in weights.values():
        _require(type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value),
                 "finite nonnegative bounded head weights required")
    _require(any(value > 0 for value in weights.values()), "at least one reference head must have positive weight")
    if probe:
        _require(all(value > 0 for value in weights.values()), "both head weights must be positive for the four-interface probe")
    return {name: float(weights[name]) for name in HEADS}


def _admit(plan, initialization, batch, replay, pins, weights):
    contract = _helper("gte_decoder_native_batch")
    contract.inspect_decoder_native_batch(plan, initialization, batch, replay,
                                         expected_donor_pins=pins)
    _require(plan["status"] == "ready", "complete ready native-input plan required before numerical execution")
    for name in HEADS:
        head = plan["heads"][name]
        _require(head["status"] == "ready" and head["ready_row_count"] == head["selected_row_count"]
                 and head["missing_row_count"] == head["quarantined_row_count"] == 0
                 and head["ready_row_count"] > 0,
                 "both native heads must be complete and nonempty")
        _require(any(any(row["reference_token_mask"]) for row in head["rows"]),
                 "each head requires eligible reference tokens")
    return weights


def _expected_state(initialization):
    state = {"primary." + name: value for name, value in initialization["primary"]["model_state"].items()}
    state.update({"legacy8." + name: value for name, value in initialization["legacy8"]["model_state"].items()})
    state.update({"auxiliary_connector." + name: value for name, value in initialization["connector"].items()})
    return state


def _admit_model(torch, model, initialization):
    """Allow interface updates while keeping the two exact archived bodies fixed."""
    _require(isinstance(model, torch.nn.Module), "private dual decoder module required")
    expected = _expected_state(initialization)
    parameters = dict(model.named_parameters())
    _require(set(parameters) == set(expected) and len(parameters) == 30,
             "exact dual decoder parameter inventory required")
    _require(set(model.state_dict()) == set(expected), "dual decoder persistent state inventory differs")
    _require(all(module.training is False for module in model.modules()), "evaluation mode required for reference objective")
    pointers = set()
    for name, parameter in parameters.items():
        _require(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                 and bool(torch.isfinite(parameter).all()), "finite CPU float32 decoder parameters required")
        reference = torch.tensor(expected[name], dtype=torch.float32, device="cpu")
        _require(parameter.shape == reference.shape, "decoder parameter shape differs: " + name)
        _require(parameter.requires_grad is (name in INTERFACES),
                 "only the four interfaces may be trainable: " + name)
        if name not in INTERFACES:
            _require(torch.equal(parameter.detach(), reference), "inherited decoder tensor changed: " + name)
        pointers.add(parameter.untyped_storage().data_ptr())
    _require(len(pointers) == 30, "private nonaliased decoder tensors required")
    buffers = dict(model.named_buffers())
    _require(set(buffers) == {"primary.input_mean"}, "saved primary input transform buffer required")
    mean = buffers["primary.input_mean"]
    transform = initialization["primary"]["input_transform"]
    _require(mean.device.type == "cpu" and mean.dtype == torch.float32 and not mean.requires_grad
             and torch.equal(mean, torch.tensor(transform["mean"], dtype=torch.float32))
             and model.primary.input_scale == transform["scale"], "archived primary input transform differs")
    config = initialization["primary"]["config"]
    _require(model.primary.max_target_tokens == config["max_target_tokens"]
             and model.primary.decoder.hidden_size == config["hidden_size"]
             and model.primary.decoder.input_size == config["token_embedding_dim"],
             "primary decoder configuration differs")
    for name, part, nested in (("primary384", model.primary, "primary"), ("legacy8", model.legacy8, "legacy8")):
        config = initialization[nested]["config"]
        _require(part.decoder.hidden_size == config["hidden_size"]
                 and part.decoder.input_size == config["token_embedding_dim"]
                 and part.target_embedding.num_embeddings == len(initialization[nested]["codec"]["target_vocabulary"]),
                 "archived decoder configuration differs: " + name)
    return parameters


@contextmanager
def _numerical_context(torch):
    previous_threads = torch.get_num_threads()
    try:
        if previous_threads != 1:
            torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            yield
    finally:
        if torch.get_num_threads() != previous_threads:
            torch.set_num_threads(previous_threads)


def _state_digest(model):
    return digest({name: tensor.detach().tolist() for name, tensor in model.state_dict().items()})


def _compute(torch, model, plan, weights):
    heads = {}
    for name in HEADS:
        head = plan["heads"][name]
        summed = None
        eligible = excluded = 0
        for row in head["rows"]:
            vectors = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32, device="cpu")
            prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64, device="cpu")
            bos = torch.tensor([[1]], dtype=torch.int64, device="cpu")
            if name == "primary384":
                output = model(vectors, prefix, bos)["primary_logits"]
            else:
                output = model(vectors, bos, prefix)["auxiliary_logits"]
            targets = torch.tensor(row["next_token_ids"], dtype=torch.int64, device="cpu")
            mask = torch.tensor(row["reference_token_mask"], dtype=torch.bool, device="cpu")
            _require(output.dtype == torch.float32 and output.device.type == "cpu"
                     and tuple(output.shape) == (1, len(row["prefix_ids"]), len(head["target_vocabulary"]))
                     and bool(torch.isfinite(output).all()) and output.requires_grad,
                     "finite differentiable independent decoder logits required")
            count = int(mask.sum().item())
            eligible += count
            excluded += len(mask) - count
            if count:
                loss = torch.nn.functional.cross_entropy(output[0][mask], targets[mask], reduction="sum")
                summed = loss if summed is None else summed + loss
        _require(eligible > 0 and summed is not None, "eligible reference targets required per head")
        loss = summed / eligible
        _require(bool(torch.isfinite(loss)), "nonfinite reference objective")
        heads[name] = {"loss": loss, "reference_token_count": eligible,
            "excluded_token_count": excluded, "row_count": head["ready_row_count"],
            "codec_sha256": head["codec_sha256"], "head_weight": weights[name]}
    total = sum(heads[name]["loss"] * weights[name] for name in HEADS)
    _require(bool(torch.isfinite(total)), "nonfinite combined reference objective")
    return {"schema": OBJECTIVE_SCHEMA, "loss": total, "heads": heads,
        "plan_sha256": plan["plan_sha256"], "objective": "reference_cross_entropy",
        "head_normalization": "eligible_reference_tokens_within_each_head", "head_weights": weights,
        "logits_combined": False, "optimizer_steps": 0, **FLAGS}


def compute_native_reference_objective(model, plan, *, initialization, batch, replay,
                                       expected_donor_pins, head_weights=None):
    """Return a differentiable reference CE; never backward or update the caller.

    All 26 inherited tensors must match the pinned initialization exactly. The
    four finite trainable interfaces may already have been fitted. Saved input
    normalization is exercised once by the original private student forward.
    Caller modes, RNG, parameters and existing gradient buffers are preserved.
    """
    weights = _weights(head_weights)
    _admit(plan, initialization, batch, replay, expected_donor_pins, weights)
    import torch
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled execution required for differentiable reference objective")
    with _numerical_context(torch):
        _admit_model(torch, model, initialization)
        return _compute(torch, model, plan, weights)


def probe_native_reference_gradients(plan, *, initialization, batch, replay,
                                     expected_donor_pins, head_weights=None):
    """Probe backward on a private fresh student; export no checkpoint or update."""
    weights = _weights(head_weights, probe=True)
    _admit(plan, initialization, batch, replay, expected_donor_pins, weights)
    original_digest = digest(initialization)
    import torch
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled execution required for private gradient probe")
    with _numerical_context(torch):
        model = _helper("gte_decoder_reuse").load_dual_decoder(initialization,
            expected_donor_pins=expected_donor_pins)
        parameters = _admit_model(torch, model, initialization)
        before = _state_digest(model)
        result = _compute(torch, model, plan, weights)
        result["loss"].backward()
        gradients = {}
        for name in INTERFACES:
            parameter = parameters[name]
            grad = parameter.grad
            _require(grad is not None and grad.device.type == "cpu" and grad.dtype == torch.float32
                     and bool(torch.isfinite(grad).all()) and bool(torch.count_nonzero(grad)),
                     "finite nonzero interface gradient required: " + name)
            gradients[name] = {"shape": list(grad.shape), "element_count": grad.numel(),
                "finite": True, "nonzero": True, "max_abs": float(grad.detach().abs().max()),
                "l2_norm": float(torch.linalg.vector_norm(grad.detach().to(torch.float64)))}
        _require(all(parameter.grad is None for name, parameter in parameters.items() if name not in INTERFACES),
                 "inherited decoder unexpectedly acquired gradients")
        after = _state_digest(model)
        _require(before == after and digest(initialization) == original_digest,
                 "gradient probe changed decoder state or original initialization")
        heads = {name: {**head, "loss": float(head["loss"].detach())} for name, head in result["heads"].items()}
        receipt = {"schema": PROBE_SCHEMA, "status": "reference_objective_probed_unqualified",
            "plan_sha256": plan["plan_sha256"], "batch_sha256": batch["batch_sha256"],
            "replay_sha256": digest(replay), "initialization_representation_id": initialization["representation_id"],
            "donor_pins": deepcopy(expected_donor_pins), "objective": "reference_cross_entropy",
            "head_normalization": "eligible_reference_tokens_within_each_head", "head_weights": weights,
            "loss": float(result["loss"].detach()), "heads": heads, "interface_gradients": gradients,
            "inherited_tensor_count": 26, "inherited_gradients_absent": True,
            "all_26_inherited_tensors_unchanged": True, "model_state_sha256_before": before,
            "model_state_sha256_after": after, "whole_model_state_unchanged": True,
            "original_decoder_initialization_unchanged": True, "gradient_probe_executed": True,
            "logits_combined": False, "optimizer_steps": 0, "numerical_profile": deepcopy(_PROFILE),
            "implementation": _implementation(), **FLAGS}
    inspect_native_reference_probe(receipt, plan, initialization=initialization,
        batch=batch, replay=replay, expected_donor_pins=expected_donor_pins)
    return receipt


def inspect_native_reference_probe(receipt, plan, *, initialization, batch, replay,
                                   expected_donor_pins):
    """Validate a saved probe's bindings and finite diagnostics without Torch.

    Consistency does not authenticate execution or encoder production. The
    caller remains responsible for admitting complete saved artifact bytes.
    """
    _require(type(receipt) is dict and set(receipt) == _PROBE_FIELDS, "closed native gradient probe required")
    weights = _weights(receipt["head_weights"], probe=True)
    _admit(plan, initialization, batch, replay, expected_donor_pins, weights)
    _require(receipt["schema"] == PROBE_SCHEMA and receipt["status"] == "reference_objective_probed_unqualified",
             "native gradient probe schema or status differs")
    _require(receipt["plan_sha256"] == plan["plan_sha256"] and receipt["batch_sha256"] == batch["batch_sha256"]
             and receipt["replay_sha256"] == digest(replay)
             and receipt["initialization_representation_id"] == initialization["representation_id"]
             and receipt["donor_pins"] == expected_donor_pins, "native gradient probe parent bindings differ")
    _require(all(type(receipt[key]) is bool and receipt[key] == value for key, value in FLAGS.items()),
             "native gradient probe scope flags differ")
    for key in ("inherited_gradients_absent", "all_26_inherited_tensors_unchanged", "whole_model_state_unchanged",
                "original_decoder_initialization_unchanged", "gradient_probe_executed"):
        _require(receipt[key] is True, "native gradient probe invariant differs: " + key)
    _require(type(receipt["inherited_tensor_count"]) is int and receipt["inherited_tensor_count"] == 26
             and type(receipt["optimizer_steps"]) is int and receipt["optimizer_steps"] == 0
             and receipt["logits_combined"] is False, "native gradient probe tensor or optimizer scope differs")
    _require(receipt["objective"] == "reference_cross_entropy"
             and receipt["head_normalization"] == "eligible_reference_tokens_within_each_head",
             "independent reference objective required")
    _require(digest(receipt["numerical_profile"]) == digest(_PROFILE)
             and receipt["implementation"] == _implementation(), "native gradient probe implementation or profile differs")
    expected_digest = digest(_expected_state(initialization))
    _require(receipt["model_state_sha256_before"] == receipt["model_state_sha256_after"] == expected_digest,
             "private probe state must equal the original initialization")
    _require(type(receipt["heads"]) is dict and set(receipt["heads"]) == set(HEADS), "separate probe heads required")
    for name in HEADS:
        head, selected = receipt["heads"][name], plan["heads"][name]
        _require(type(head) is dict and set(head) == _HEAD_FIELDS, "closed reference head diagnostic required")
        count = sum(sum(row["reference_token_mask"]) for row in selected["rows"])
        excluded = sum(len(row["reference_token_mask"]) for row in selected["rows"]) - count
        for key, expected in (("reference_token_count", count), ("excluded_token_count", excluded),
                              ("row_count", selected["ready_row_count"])):
            _require(type(head[key]) is int and head[key] == expected, "reference token or row diagnostic differs")
        _require(head["codec_sha256"] == selected["codec_sha256"]
                 and type(head["head_weight"]) is float and head["head_weight"] == weights[name],
                 "head codec or weight differs")
        _require(type(head["loss"]) is float and math.isfinite(head["loss"]) and head["loss"] >= 0,
                 "finite nonnegative reference CE required")
    _require(type(receipt["loss"]) is float and math.isfinite(receipt["loss"]) and receipt["loss"] >= 0
             and math.isclose(receipt["loss"], sum(receipt["heads"][name]["loss"] * weights[name] for name in HEADS),
                              rel_tol=2e-6, abs_tol=1e-6), "combined reference CE differs")
    _require(type(receipt["interface_gradients"]) is dict and set(receipt["interface_gradients"]) == set(INTERFACES),
             "all four interface gradients required")
    for name in INTERFACES:
        gradient = receipt["interface_gradients"][name]
        _require(type(gradient) is dict and set(gradient) == _GRAD_FIELDS, "closed interface gradient diagnostic required")
        value = _expected_state(initialization)[name]
        shape = [len(value)] + ([len(value[0])] if type(value[0]) is list else [])
        _require(type(gradient["shape"]) is list and all(type(dim) is int for dim in gradient["shape"])
                 and gradient["shape"] == shape and type(gradient["element_count"]) is int
                 and gradient["element_count"] == math.prod(shape)
                 and gradient["finite"] is True and gradient["nonzero"] is True,
                 "finite nonzero correctly shaped interface gradient required")
        maximum, norm = gradient["max_abs"], gradient["l2_norm"]
        _require(type(maximum) is float and type(norm) is float and math.isfinite(maximum)
                 and math.isfinite(norm) and 0 < maximum <= norm
                 and norm <= maximum * math.sqrt(math.prod(shape)) * (1 + 1e-12),
                 "interface gradient magnitude diagnostics differ")
    return {"schema": "gte-native-reference-gradient-probe-inspection/v1", "status": "consistent_unqualified",
        "plan_sha256": plan["plan_sha256"], "reference_token_counts":
            {name: receipt["heads"][name]["reference_token_count"] for name in HEADS},
        "interface_tensor_count": 4, "execution_authenticated": False,
        "teacher_qualified": False, "production_kd_enabled": False, "proof_authority": False}


__all__ = ["compute_native_reference_objective", "probe_native_reference_gradients",
           "inspect_native_reference_probe", "OBJECTIVE_SCHEMA", "PROBE_SCHEMA"]
