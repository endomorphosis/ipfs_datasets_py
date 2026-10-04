"""Private 768D decoder generation with its analytically fitted input boundary.

The original dual-donor initialization remains unchanged inside this checkpoint.
Only the primary 768-to-384 affine tensors change in the current student. Both
learned decoder bodies and the still-unfitted 8D connector retain their exact
initial values. Inspection is dependency-free; loading uses private CPU tensors.
The saved alignment evidence does not qualify a teacher or authorize KD labels.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path


SCHEMA = "gte-aligned-dual-decoder/v1"
ARCHITECTURE = "factorized-768-shared-condition-dual-decoder/v1"
MAX_BYTES = 128 * 1024 * 1024
FLAGS = {
    "analytic_alignment_fit_executed": True,
    "primary_input_boundary_fitted": True,
    "auxiliary_connector_fitted": False,
    "boundary_alignment_required": True,
    "inherited_decoder_weights_unchanged": True,
    "original_initialization_unchanged": True,
    "decoder_parameters_random": False,
    "encoder_initially_frozen": True,
    "encoder_inference_executed": False,
    "encoder_numerics_verified": False,
    "source_vectors_producer_verified": False,
    "student_vectors_producer_verified": False,
    "teacher_qualified": False,
    "source_fidelity_qualified": False,
    "student_decoder_gradient_training_executed": False,
    "distillation_executed": False,
    "proof_authority": False,
    "optimizer_resume_supported": False,
}
MODE_POLICY = {
    "inherited_primary_decoder_frozen": True,
    "inherited_legacy8_decoder_frozen": True,
    "primary_input_boundary_trainable": True,
    "auxiliary_connector_trainable": True,
    "default_module_mode": "evaluation",
    "device": "cpu",
    "dtype": "float32",
    "construction_threads": 1,
}
OPTIMIZER = {"mode": "fresh", "state": None, "resume": False}
_FIELDS = {
    "schema", "architecture", "domain_id", "dimension", "source_profile_id",
    "representation_id", "parent_file_pins", "donor_pins", "initialization",
    "bridge", "plan", "fit_report", "handoff", "handoff_sha256",
    "model_state_sha256", "tensor_inventory", "tensor_inventory_sha256",
    "implementation", "mode_policy", "optimizer", "optimizer_steps", *FLAGS,
}
_PRIMARY_BOUNDARY = {"primary.input_adapter.weight", "primary.input_adapter.bias"}
_AUXILIARY_CONNECTOR = {"auxiliary_connector.weight", "auxiliary_connector.bias"}


def _helper(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_gte_aligned_decoder_" + name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load aligned decoder helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("bounded finite JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _implementation():
    names = (
        "gte_aligned_decoder", "gte_aligned_decoder_contract",
        "gte_alignment_contract", "gte_decoder_reuse", "gte_decoder_warm_start",
        "gte_legacy8_decoder_donor", "gte_affine_bridge",
    )
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _handoff(initialization, bridge, plan, fit_report, file_pins, donor_pins):
    return _helper("gte_aligned_decoder_contract").inspect_alignment_handoff(
        initialization, bridge, plan, fit_report,
        expected_file_pins=file_pins, expected_donor_pins=donor_pins)


def _state(initialization, bridge):
    """Derive the current state without altering immutable parent snapshots."""
    state = {"primary." + name: value
             for name, value in initialization["primary"]["model_state"].items()}
    state.update({"legacy8." + name: value
                  for name, value in initialization["legacy8"]["model_state"].items()})
    state.update({"auxiliary_connector." + name: value
                  for name, value in initialization["connector"].items()})
    for name, value in bridge["model_state"].items():
        state["primary.input_adapter." + name] = value
    return state


def _shapes(initialization, reuse):
    primary = initialization["primary"]
    legacy = initialization["legacy8"]
    result = {"primary." + name: shape
              for name, shape in reuse._PRIMARY._shapes(primary["config"], primary["codec"]).items()}
    result.update({"legacy8." + name: shape for name, shape in reuse._LEGACY._shapes(
        legacy["config"], len(legacy["codec"]["target_vocabulary"])).items()})
    result.update({"auxiliary_connector.weight": (8, primary["config"]["hidden_size"]),
                   "auxiliary_connector.bias": (8,)})
    return result


def _inventory(state, shapes):
    result = []
    for name in sorted(shapes):
        if name in _PRIMARY_BOUNDARY:
            origin = "analytic_training_pair_alignment"
        elif name in _AUXILIARY_CONNECTOR:
            origin = "unchanged_unfitted_auxiliary_connector"
        elif name.startswith("primary."):
            origin = "copied_384d_decoder"
        else:
            origin = "copied_8d_decoder"
        result.append({"name": name, "shape": list(shapes[name]),
            "sha256": digest(state[name]), "parameter_count": math.prod(shapes[name]),
            "origin": origin, "requires_grad": name in (_PRIMARY_BOUNDARY | _AUXILIARY_CONNECTOR)})
    return result


def inspect_aligned_decoder(checkpoint, *, expected_file_pins, expected_donor_pins):
    """Inspect an externally authenticated aligned generation without Torch.

    The caller must authenticate checkpoint bytes and independently admit the
    four parent files. Parent raw-file pins cannot be inferred from this payload.
    Parent initialization flags describe historical initialization, not current
    fitted weights. Current flags and inventory belong to this outer generation.
    """
    _require(type(checkpoint) is dict and set(checkpoint) == _FIELDS,
             "closed aligned decoder checkpoint required")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "aligned decoder checkpoint exceeds byte bound")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["architecture"] == ARCHITECTURE,
             "aligned decoder schema or architecture differs")
    _require(checkpoint["domain_id"] == "legal_ir" and type(checkpoint["dimension"]) is int
             and checkpoint["dimension"] == 768, "aligned decoder geometry differs")
    _require(all(type(checkpoint[key]) is bool and checkpoint[key] == value
                 for key, value in FLAGS.items()), "aligned generation declarations differ")
    _require(type(checkpoint["optimizer_steps"]) is int and checkpoint["optimizer_steps"] == 0,
             "analytic handoff has no decoder optimizer steps")
    _require(_raw(checkpoint["mode_policy"]) == _raw(MODE_POLICY), "aligned decoder mode policy differs")
    _require(_raw(checkpoint["optimizer"]) == _raw(OPTIMIZER), "fresh optimizer without donor moments required")
    _require(checkpoint["parent_file_pins"] == expected_file_pins
             and checkpoint["donor_pins"] == expected_donor_pins,
             "external parent or donor identities differ")
    _require(checkpoint["implementation"] == _implementation(), "aligned decoder implementation differs")
    handoff = _handoff(checkpoint["initialization"], checkpoint["bridge"], checkpoint["plan"],
                       checkpoint["fit_report"], expected_file_pins, expected_donor_pins)
    _require(_raw(checkpoint["handoff"]) == _raw(handoff)
             and checkpoint["handoff_sha256"] == digest(handoff), "aligned handoff receipt differs")
    _require(checkpoint["representation_id"] == handoff["aligned_representation_id"]
             and checkpoint["source_profile_id"] == handoff["source_profile_id"],
             "aligned decoder representation or input profile differs")
    reuse = _helper("gte_decoder_reuse")
    state = _state(checkpoint["initialization"], checkpoint["bridge"])
    shapes = _shapes(checkpoint["initialization"], reuse)
    _require(set(state) == set(shapes) and len(state) == 30, "exact 30-tensor aligned state required")
    inventory = _inventory(state, shapes)
    _require(checkpoint["model_state_sha256"] == digest(state), "aligned whole-model state digest differs")
    _require(_raw(checkpoint["tensor_inventory"]) == _raw(inventory)
             and checkpoint["tensor_inventory_sha256"] == digest(inventory), "aligned tensor inventory differs")
    counts = {origin: sum(entry["parameter_count"] for entry in inventory if entry["origin"] == origin)
              for origin in {entry["origin"] for entry in inventory}}
    return {"schema": "gte-aligned-dual-decoder-inspection/v1", "status": "fitted_unqualified",
        "dimension": 768, "representation_id": checkpoint["representation_id"],
        "initialization_representation_id": handoff["initialization_representation_id"],
        "source_profile_id": checkpoint["source_profile_id"], "model_state_sha256": digest(state),
        "tensor_count": len(state), "copied_tensor_count": 26, "fitted_tensor_count": 2,
        "unfitted_connector_tensor_count": 2, "trainable_tensor_count": 4,
        "copied_parameter_count": counts["copied_384d_decoder"] + counts["copied_8d_decoder"],
        "fitted_boundary_parameter_count": counts["analytic_training_pair_alignment"],
        "unfitted_connector_parameter_count": counts["unchanged_unfitted_auxiliary_connector"],
        "primary_max_target_tokens": checkpoint["initialization"]["primary"]["config"]["max_target_tokens"],
        "auxiliary_max_target_tokens": checkpoint["initialization"]["legacy8"]["config"]["max_target_tokens"],
        "handoff": deepcopy(handoff), "tensor_inventory": deepcopy(inventory),
        "optimizer_steps": 0, **FLAGS}


@contextmanager
def _numerical_context(torch):
    before = torch.get_num_threads()
    try:
        if before != 1:
            torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            yield
    finally:
        if torch.get_num_threads() != before:
            torch.set_num_threads(before)


def _private_model(checkpoint, donor_pins, receipt):
    import torch
    with _numerical_context(torch):
        model = _helper("gte_decoder_reuse").load_dual_decoder(
            checkpoint["initialization"], expected_donor_pins=donor_pins)
        state = {key: torch.tensor(value, dtype=torch.float32, device="cpu")
                 for key, value in checkpoint["bridge"]["model_state"].items()}
        _require(all(bool(torch.isfinite(value).all()) for value in state.values())
                 and digest({key: value.tolist() for key, value in state.items()})
                    == digest(checkpoint["bridge"]["model_state"]),
                 "fitted boundary must reload exact finite float32 values")
        model.primary.input_adapter.load_state_dict(state, strict=True)
        actual = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        _require(digest(actual) == receipt["model_state_sha256"], "private aligned model state differs")
        trainable = _PRIMARY_BOUNDARY | _AUXILIARY_CONNECTOR
        _require(all(parameter.requires_grad == (name in trainable) and parameter.grad is None
                     and parameter.device.type == "cpu" and parameter.dtype == torch.float32
                     for name, parameter in model.named_parameters()), "aligned decoder parameter modes differ")
        model.eval()
        model.representation_id = checkpoint["representation_id"]
        model.initialization_representation_id = receipt["initialization_representation_id"]
        model.aligned_identity = deepcopy(receipt["handoff"])
    return model


def create_aligned_decoder(initialization, bridge, plan, fit_report, *,
                           expected_file_pins, expected_donor_pins):
    """Create a private generation; replace only the primary affine boundary."""
    initialization, bridge, plan, fit_report, file_pins, donor_pins = deepcopy(
        (initialization, bridge, plan, fit_report, expected_file_pins, expected_donor_pins))
    handoff = _handoff(initialization, bridge, plan, fit_report, file_pins, donor_pins)
    reuse = _helper("gte_decoder_reuse")
    state = _state(initialization, bridge)
    inventory = _inventory(state, _shapes(initialization, reuse))
    checkpoint = {"schema": SCHEMA, "architecture": ARCHITECTURE, "domain_id": "legal_ir",
        "dimension": 768, "source_profile_id": handoff["source_profile_id"],
        "representation_id": handoff["aligned_representation_id"],
        "parent_file_pins": file_pins, "donor_pins": donor_pins,
        "initialization": initialization, "bridge": bridge, "plan": plan, "fit_report": fit_report,
        "handoff": handoff, "handoff_sha256": digest(handoff), "model_state_sha256": digest(state),
        "tensor_inventory": inventory, "tensor_inventory_sha256": digest(inventory),
        "implementation": _implementation(), "mode_policy": deepcopy(MODE_POLICY),
        "optimizer": deepcopy(OPTIMIZER), "optimizer_steps": 0, **FLAGS}
    receipt = inspect_aligned_decoder(checkpoint, expected_file_pins=file_pins, expected_donor_pins=donor_pins)
    model = _private_model(checkpoint, donor_pins, receipt)
    return model, checkpoint


def load_aligned_decoder(checkpoint, *, expected_file_pins, expected_donor_pins):
    """Reload exact private aligned state without importing optimizer moments."""
    checkpoint, file_pins, donor_pins = deepcopy((checkpoint, expected_file_pins, expected_donor_pins))
    receipt = inspect_aligned_decoder(checkpoint, expected_file_pins=file_pins, expected_donor_pins=donor_pins)
    return _private_model(checkpoint, donor_pins, receipt)


__all__ = ["SCHEMA", "ARCHITECTURE", "create_aligned_decoder", "inspect_aligned_decoder",
           "load_aligned_decoder", "digest"]
