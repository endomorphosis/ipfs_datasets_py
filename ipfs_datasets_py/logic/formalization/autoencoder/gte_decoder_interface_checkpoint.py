"""Strict versioned reference-trained interfaces over immutable decoder donors.

Only the four new interface tensors are stored in this generation. All 26
learned decoder tensors are derived unchanged from an externally admitted
original initialization. Inspection never imports a tensor library; loading
constructs a private CPU model after full native-plan and report admission.
Content hashes below do not reconstruct arbitrary original raw-file hashes or
independently attest optimizer execution, native embedding production or quality.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct


SCHEMA = "gte-decoder-interface-checkpoint/v1"
REPORT_SCHEMA = "gte-decoder-interface-training-report/v1"
ARCHITECTURE = "factorized-768-shared-condition-dual-decoder/v1"
MAX_BYTES = 16 * 1024 * 1024
INTERFACES = ("primary.input_adapter.weight", "primary.input_adapter.bias",
              "auxiliary_connector.weight", "auxiliary_connector.bias")
HEADS = ("primary384", "legacy8")
FLAGS = {
    "reference_supervised_training_executed": True, "training_executed": True,
    "reference_supervised_objective_computed": True,
    "input_adapter_exercised": True, "auxiliary_connector_exercised": True,
    "native768_inputs_used": True,
    "inherited_gradients_absent": True, "all_26_inherited_tensors_unchanged": True,
    "original_decoder_initialization_unchanged": True,
    "exact_trained_reload_passed": True, "all_selected_reference_outputs_preserved_on_reload": True,
    "interfaces_changed": True,
    "distillation_executed": False, "encoder_inference_executed": False,
    "download_executed": False, "teacher_qualified": False,
    "production_kd_eligible": False, "production_kd_enabled": False,
    "source_fidelity_qualified": False, "proof_authority": False,
    "optimizer_resume_supported": False, "producer_execution_authenticated": False,
    "logits_combined": False,
}
PROFILE = {"device": "cpu", "dtype": "float32", "threads": 1, "evaluation_mode": True}
MODE_POLICY = {"inherited_primary_decoder_frozen": True, "inherited_legacy8_decoder_frozen": True,
    "primary_input_boundary_trainable": True, "auxiliary_connector_trainable": True,
    "default_module_mode": "evaluation", "device": "cpu", "dtype": "float32", "construction_threads": 1}
OPTIMIZER_POLICY = {"mode": "fresh", "state": None, "resume": False, "donor_moments_imported": False}
_REPORT_FIELDS = {"schema", "status", "initialization_representation_id", "plan_sha256", "batch_sha256",
    "replay_sha256", "donor_pins", "profile_id", "primary_start", "steps", "optimizer_steps", "optimizer",
    "max_grad_norm", "head_weights", "objective", "head_normalization", "before", "after", "history",
    "interface_state_sha256_before", "interface_state_sha256_after", "model_state_sha256_before",
    "model_state_sha256_after", "inherited_tensor_count", "numerical_profile", "implementation",
    "trained_reference_outputs", "trained_reference_outputs_sha256", *FLAGS}
_OPTIMIZER_FIELDS = {"name", "fresh", "learning_rate", "betas", "eps", "weight_decay", "parameters",
                     "donor_state_imported", "resume"}
_HEAD_FIELDS = {"loss", "reference_token_count", "excluded_token_count", "row_count", "codec_sha256", "head_weight"}
_HISTORY_FIELDS = {"step", "loss_before", "loss_after", "head_losses_before", "head_losses_after",
    "gradient_global_norm_before_clipping", "gradient_global_norm_after_clipping", "interface_gradients"}
_GRAD_FIELDS = {"shape", "element_count", "finite", "nonzero", "max_abs", "l2_norm"}
_OUTPUT_FIELDS = {"id", "source_sha256", "reference_prefix_sha256", "native_row_sha256",
    "primary_logits_sha256", "auxiliary_logits_sha256", "shared_condition_sha256", "auxiliary_latent_sha256"}
_FIELDS = {"schema", "architecture", "domain_id", "dimension", "representation_id",
    "initialization_representation_id", "initialization_content_sha256", "plan_sha256", "batch_sha256", "replay_sha256",
    "donor_pins", "profile_id", "asset_manifest_sha256", "codec_sha256", "primary_start", "trainable_tensor_names",
    "interfaces", "interface_state_sha256", "inherited_state_sha256", "model_state_sha256", "tensor_inventory",
    "tensor_inventory_sha256", "training_report", "training_report_sha256", "implementation", "mode_policy",
    "optimizer", "optimizer_steps", *FLAGS}
_IMPLEMENTATION_NAMES = ("gte_decoder_interface_training", "gte_decoder_interface_checkpoint",
    "gte_decoder_native_objective", "gte_decoder_native_batch", "gte_decoder_transfer_replay",
    "gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor")


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_interface_checkpoint_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load interface checkpoint dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("bounded finite interface checkpoint JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _same(left, right, message):
    _require(_raw(left) == _raw(right), message)


def _implementation():
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in _IMPLEMENTATION_NAMES}


def _number(value, label, *, low=0., high=1e12, positive=False):
    _require(type(value) is float and math.isfinite(value) and low <= value <= high
             and (not positive or value > 0.), "bounded finite float " + label + " required")
    return value


def _sha(value, label):
    _require(type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value),
             "full lowercase SHA256 required: " + label)


def _state(initialization, interfaces=None):
    result = {"primary." + name: value for name, value in initialization["primary"]["model_state"].items()}
    result.update({"legacy8." + name: value for name, value in initialization["legacy8"]["model_state"].items()})
    result.update({"auxiliary_connector." + name: value for name, value in initialization["connector"].items()})
    if interfaces is not None:
        result.update(interfaces)
    return result


def _shapes(initialization, reuse):
    result = {"primary." + name: shape for name, shape in reuse._PRIMARY._shapes(
        initialization["primary"]["config"], initialization["primary"]["codec"]).items()}
    result.update({"legacy8." + name: shape for name, shape in reuse._LEGACY._shapes(
        initialization["legacy8"]["config"], len(initialization["legacy8"]["codec"]["target_vocabulary"])).items()})
    result.update({"auxiliary_connector.weight": (8, initialization["primary"]["config"]["hidden_size"]),
                   "auxiliary_connector.bias": (8,)})
    return result


def _tensor(value, shape, label):
    if shape:
        _require(type(value) is list and len(value) == shape[0], "exact interface tensor shape required: " + label)
        for child in value:
            _tensor(child, shape[1:], label)
        return
    _require(type(value) is float, "serialized float32 tensor leaves required: " + label)
    try:
        restored = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("interface tensor exceeds float32: " + label) from exc
    _require(math.isfinite(value) and math.isfinite(restored) and value == restored,
             "exact finite float32 tensor required: " + label)


def _parents(initialization, plan, pins):
    reuse = _helper("gte_decoder_reuse")
    reuse.inspect_dual_decoder(initialization, expected_donor_pins=pins)
    contract = _helper("gte_decoder_native_batch")
    _closed(plan, contract._FIELDS, "native interface training plan")
    _require(len(contract._raw(plan)) <= contract.MAX_PLAN_BYTES, "native training plan exceeds byte bound")
    _require(plan["schema"] == contract.SCHEMA and plan["status"] == "ready"
             and plan["initialization_representation_id"] == initialization["representation_id"]
             and plan["donor_pins"] == pins and plan["profile_id"] == contract.PROFILE_ID
             and plan["plan_sha256"] == contract.digest({key: value for key, value in plan.items() if key != "plan_sha256"}),
             "ready native training plan and original initialization binding required")
    _closed(plan["heads"], HEADS, "native training heads")
    for name in HEADS:
        head = plan["heads"][name]
        _closed(head, contract._HEAD_FIELDS, "native training head")
        _require(head["status"] == "ready" and type(head["ready_row_count"]) is int
                 and 1 <= head["ready_row_count"] <= 64 and head["ready_row_count"] == head["selected_row_count"]
                 and type(head["rows"]) is list and len(head["rows"]) == head["ready_row_count"]
                 and type(head["missing_row_count"]) is int and head["missing_row_count"] == 0
                 and type(head["quarantined_row_count"]) is int and head["quarantined_row_count"] == 0,
                 "complete selected native head required")
    shapes = _shapes(initialization, reuse)
    initial_state = _state(initialization)
    _require(len(initial_state) == 30 and set(shapes) == set(initial_state), "thirty original decoder tensors required")
    for name, shape in shapes.items():
        _tensor(initial_state[name], shape, name)
    return initial_state, shapes


def _summary(summary, plan, weights):
    _closed(summary, {"loss", "heads"}, "reference training loss summary")
    _closed(summary["heads"], HEADS, "reference training loss heads")
    losses = {}
    for name in HEADS:
        head, native = summary["heads"][name], plan["heads"][name]
        _closed(head, _HEAD_FIELDS, "reference training head metric")
        count = sum(sum(row["reference_token_mask"]) for row in native["rows"])
        excluded = sum(len(row["reference_token_mask"]) for row in native["rows"]) - count
        _require(count > 0, "eligible reference tokens required")
        for key, expected in (("reference_token_count", count), ("excluded_token_count", excluded),
                              ("row_count", native["ready_row_count"])):
            _require(type(head[key]) is int and head[key] == expected, "reference training head token or row count differs")
        _require(head["codec_sha256"] == native["codec_sha256"]
                 and type(head["head_weight"]) is float and head["head_weight"] == weights[name],
                 "reference training head codec or weight differs")
        losses[name] = _number(head["loss"], "reference CE")
    total = _number(summary["loss"], "combined reference CE")
    _require(math.isclose(total, sum(losses[name] * weights[name] for name in HEADS), rel_tol=2e-6, abs_tol=1e-6),
             "combined reference CE differs from independent head normalization")
    return losses


def _gradients(gradients, shapes):
    _closed(gradients, INTERFACES, "four interface gradient diagnostics")
    norms = []
    for name in INTERFACES:
        gradient = gradients[name]
        _closed(gradient, _GRAD_FIELDS, "interface gradient diagnostic")
        shape, count = list(shapes[name]), math.prod(shapes[name])
        _same(gradient["shape"], shape, "interface gradient shape differs")
        _require(type(gradient["element_count"]) is int and gradient["element_count"] == count
                 and gradient["finite"] is True and gradient["nonzero"] is True,
                 "finite nonzero interface gradient required")
        maximum = _number(gradient["max_abs"], "gradient maximum", positive=True)
        norm = _number(gradient["l2_norm"], "gradient norm", positive=True)
        _require(maximum <= norm and norm <= maximum * math.sqrt(count) * (1 + 1e-12),
                 "interface gradient magnitude diagnostics differ")
        norms.append(norm)
    return math.hypot(*norms)


def _report(report, initialization, plan, pins, interfaces, initial_state, shapes):
    _closed(report, _REPORT_FIELDS, "interface training report")
    _require(report["schema"] == REPORT_SCHEMA and report["status"] == "reference_interfaces_trained_unqualified"
             and report["primary_start"] == "original_initialization"
             and report["initialization_representation_id"] == initialization["representation_id"]
             and report["plan_sha256"] == plan["plan_sha256"] and report["batch_sha256"] == plan["batch_sha256"]
             and report["replay_sha256"] == plan["replay_sha256"] and report["donor_pins"] == pins
             and report["profile_id"] == plan["profile_id"], "interface training parent bindings differ")
    _require(all(type(report[key]) is bool and report[key] == value for key, value in FLAGS.items()),
             "interface training scope or immutable donor claims differ")
    _require(type(report["steps"]) is int and 1 <= report["steps"] <= 64
             and type(report["optimizer_steps"]) is int and report["optimizer_steps"] == report["steps"]
             and type(report["inherited_tensor_count"]) is int and report["inherited_tensor_count"] == 26,
             "bounded optimizer steps and all twenty-six inherited tensors required")
    _require(report["objective"] == "reference_cross_entropy"
             and report["head_normalization"] == "eligible_reference_tokens_within_each_head",
             "independent reference CE training required")
    _same(report["numerical_profile"], PROFILE, "interface training numerical profile differs")
    _same(report["implementation"], _implementation(), "interface training implementation differs")
    optimizer = report["optimizer"]
    _closed(optimizer, _OPTIMIZER_FIELDS, "fresh interface optimizer")
    _require(optimizer["name"] == "AdamW" and optimizer["fresh"] is True
             and optimizer["donor_state_imported"] is False and optimizer["resume"] is False,
             "fresh AdamW without imported donor moments required")
    _same(optimizer["parameters"], list(INTERFACES), "optimizer must contain exactly the four interfaces")
    _number(optimizer["learning_rate"], "interface learning rate", low=1e-6, high=.01)
    _same(optimizer["betas"], [.9, .999], "AdamW betas differ")
    _require(type(optimizer["eps"]) is float and optimizer["eps"] == 1e-8
             and type(optimizer["weight_decay"]) is float and optimizer["weight_decay"] == 0.,
             "fresh AdamW epsilon or weight decay differs")
    max_norm = _number(report["max_grad_norm"], "maximum gradient norm", low=1e-6, high=100.)
    weights = report["head_weights"]
    _closed(weights, HEADS, "independent positive training head weights")
    for value in weights.values():
        _number(value, "head weight", high=100., positive=True)
    before = _summary(report["before"], plan, weights)
    after = _summary(report["after"], plan, weights)
    history = report["history"]
    _require(type(history) is list and len(history) == report["steps"], "complete bounded optimizer history required")
    previous_total, previous_heads = report["before"]["loss"], before
    for index, step in enumerate(history, 1):
        _closed(step, _HISTORY_FIELDS, "optimizer step diagnostic")
        _require(type(step["step"]) is int and step["step"] == index, "one-based consecutive optimizer history required")
        _same(step["head_losses_before"], previous_heads, "optimizer history before-head losses differ")
        _require(type(step["loss_before"]) is float and step["loss_before"] == previous_total,
                 "optimizer history before loss differs")
        _closed(step["head_losses_after"], HEADS, "optimizer history head losses")
        for value in step["head_losses_after"].values():
            _number(value, "optimizer history reference CE")
        total = _number(step["loss_after"], "optimizer history combined CE")
        _require(math.isclose(total, sum(step["head_losses_after"][name] * weights[name] for name in HEADS),
                              rel_tol=2e-6, abs_tol=1e-6), "optimizer history combined CE differs")
        diagnostic_norm = _gradients(step["interface_gradients"], shapes)
        unclipped = _number(step["gradient_global_norm_before_clipping"], "unclipped gradient norm", positive=True)
        clipped = _number(step["gradient_global_norm_after_clipping"], "clipped gradient norm", positive=True)
        _require(math.isclose(unclipped, diagnostic_norm, rel_tol=2e-5, abs_tol=1e-8)
                 and clipped <= max_norm * (1 + 2e-5) and clipped <= unclipped * (1 + 2e-5),
                 "optimizer clipping diagnostics differ")
        previous_total, previous_heads = total, step["head_losses_after"]
    _require(previous_total == report["after"]["loss"], "optimizer final loss differs from final summary")
    _same(previous_heads, after, "optimizer final head losses differ from final summary")
    initial_interfaces = {name: initial_state[name] for name in INTERFACES}
    final_state = _state(initialization, interfaces)
    _require(report["interface_state_sha256_before"] == digest(initial_interfaces)
             and report["interface_state_sha256_after"] == digest(interfaces)
             and report["model_state_sha256_before"] == digest(initial_state)
             and report["model_state_sha256_after"] == digest(final_state),
             "interface training initial or final tensor digests differ")
    _require(all(digest(interfaces[name]) != digest(initial_interfaces[name]) for name in INTERFACES),
             "all four trained interface tensors must differ from the original initialization")
    outputs = report["trained_reference_outputs"]
    _closed(outputs, HEADS, "trained reference output heads")
    for name in HEADS:
        rows, selected = outputs[name], plan["heads"][name]["rows"]
        _require(type(rows) is list and len(rows) == len(selected), "all selected trained reference outputs required")
        for row, original in zip(rows, selected):
            _closed(row, _OUTPUT_FIELDS, "trained reference output binding")
            for key in ("id", "source_sha256", "reference_prefix_sha256", "native_row_sha256"):
                _same(row[key], original[key], "trained reference output source or prefix differs")
            for key in ("primary_logits_sha256", "auxiliary_logits_sha256", "shared_condition_sha256", "auxiliary_latent_sha256"):
                _sha(row[key], key)
    _require(report["trained_reference_outputs_sha256"] == digest(outputs), "trained reference output inventory differs")


def _inventory(state, shapes):
    return [{"name": name, "shape": list(shapes[name]), "sha256": digest(state[name]),
        "parameter_count": math.prod(shapes[name]), "requires_grad": name in INTERFACES,
        "origin": "reference_optimizer_trained_interface" if name in INTERFACES else
            "unchanged_copied_384d_decoder" if name.startswith("primary.") else "unchanged_copied_8d_decoder"}
        for name in sorted(shapes)]


def _identity(checkpoint):
    keys = ("schema", "initialization_representation_id", "initialization_content_sha256", "plan_sha256",
        "batch_sha256", "replay_sha256", "donor_pins", "profile_id", "asset_manifest_sha256", "codec_sha256",
        "interface_state_sha256", "inherited_state_sha256", "model_state_sha256", "training_report_sha256",
        "implementation", "optimizer_steps")
    return "gte-768-dual-reference-interfaces:sha256:" + digest({key: checkpoint[key] for key in keys})


def create_interface_checkpoint(initialization, plan, *, expected_donor_pins, interfaces, training_report):
    """Construct a versioned payload from an already admitted ready native plan.

    This constructor checks initialization, plan envelope, tensors and the closed
    training report. The complete independent inspector below additionally
    admits the original batch/replay and reconstructs the entire native plan;
    it must be called before publication or loading.
    """
    initial_state, shapes = _parents(initialization, plan, expected_donor_pins)
    _closed(interfaces, INTERFACES, "trained interface state")
    for name in INTERFACES:
        _tensor(interfaces[name], shapes[name], name)
    _report(training_report, initialization, plan, expected_donor_pins, interfaces, initial_state, shapes)
    state = _state(initialization, interfaces)
    inherited = {name: value for name, value in initial_state.items() if name not in INTERFACES}
    inventory = _inventory(state, shapes)
    result = {"schema": SCHEMA, "architecture": ARCHITECTURE, "domain_id": "legal_ir", "dimension": 768,
        "initialization_representation_id": initialization["representation_id"],
        "initialization_content_sha256": digest(initialization), "plan_sha256": plan["plan_sha256"],
        "batch_sha256": plan["batch_sha256"], "replay_sha256": plan["replay_sha256"],
        "donor_pins": deepcopy(expected_donor_pins), "profile_id": plan["profile_id"],
        "asset_manifest_sha256": plan["asset_manifest_sha256"],
        "codec_sha256": {name: plan["heads"][name]["codec_sha256"] for name in HEADS},
        "primary_start": "original_initialization", "trainable_tensor_names": list(INTERFACES),
        "interfaces": deepcopy(interfaces), "interface_state_sha256": digest(interfaces),
        "inherited_state_sha256": digest(inherited), "model_state_sha256": digest(state),
        "tensor_inventory": inventory, "tensor_inventory_sha256": digest(inventory),
        "training_report": deepcopy(training_report), "training_report_sha256": digest(training_report),
        "implementation": _implementation(), "mode_policy": deepcopy(MODE_POLICY),
        "optimizer": deepcopy(OPTIMIZER_POLICY), "optimizer_steps": training_report["optimizer_steps"], **FLAGS}
    result["representation_id"] = _identity(result)
    _require(result["representation_id"] != initialization["representation_id"], "trained generation must have a new identity")
    _require(len(_raw(result)) <= MAX_BYTES, "interface checkpoint exceeds 16 MiB")
    return result


def inspect_interface_checkpoint(checkpoint, *, initialization, plan, batch, replay, expected_donor_pins):
    """Inspect an externally byte-authenticated generation without model imports."""
    _helper("gte_decoder_native_batch").inspect_decoder_native_batch(plan, initialization, batch, replay,
                                                                   expected_donor_pins=expected_donor_pins)
    _closed(checkpoint, _FIELDS, "trained interface checkpoint")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "interface checkpoint exceeds 16 MiB")
    recomputed = create_interface_checkpoint(initialization, plan, expected_donor_pins=expected_donor_pins,
        interfaces=checkpoint["interfaces"], training_report=checkpoint["training_report"])
    _same(checkpoint, recomputed, "trained interface checkpoint does not match its immutable parents and report")
    return {"schema": "gte-decoder-interface-checkpoint-inspection/v1", "status": "consistent_trained_unqualified",
        "representation_id": checkpoint["representation_id"], "checkpoint_content_sha256": digest(checkpoint),
        "interface_state_sha256": checkpoint["interface_state_sha256"], "model_state_sha256": checkpoint["model_state_sha256"],
        "optimizer_steps": checkpoint["optimizer_steps"], "trainable_tensor_count": 4, "frozen_inherited_tensor_count": 26,
        "training_execution_authenticated": False, "optimizer_resume_supported": False,
        "producer_execution_authenticated": False, "teacher_qualified": False, "production_kd_eligible": False,
        "distillation_executed": False, "encoder_inference_executed": False, "proof_authority": False}


@contextmanager
def _cpu_context(torch):
    previous = torch.get_num_threads()
    try:
        if previous != 1:
            torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]), torch.no_grad():
            yield
    finally:
        if torch.get_num_threads() != previous:
            torch.set_num_threads(previous)


def load_interface_checkpoint(checkpoint, *, initialization, plan, batch, replay, expected_donor_pins):
    """Load a private frozen-body CPU model after strict dependency-free admission."""
    inspect_interface_checkpoint(checkpoint, initialization=initialization, plan=plan, batch=batch, replay=replay,
                                 expected_donor_pins=expected_donor_pins)
    import torch
    with _cpu_context(torch):
        model = _helper("gte_decoder_reuse").load_dual_decoder(initialization, expected_donor_pins=expected_donor_pins)
        parameters = dict(model.named_parameters())
        for name, values in checkpoint["interfaces"].items():
            parameters[name].copy_(torch.tensor(values, dtype=torch.float32, device="cpu"))
        current = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        _require(digest(current) == checkpoint["model_state_sha256"], "reloaded trained interface state differs")
        _require(all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                     and parameter.requires_grad is (name in INTERFACES) and parameter.grad is None
                     for name, parameter in model.named_parameters()), "private trained decoder mode policy differs")
        _require(len({parameter.untyped_storage().data_ptr() for parameter in model.parameters()}) == 30,
                 "private trained decoder tensors must have independent storage")
        model.eval()
        return model


__all__ = ["SCHEMA", "REPORT_SCHEMA", "INTERFACES", "FLAGS", "create_interface_checkpoint",
           "inspect_interface_checkpoint", "load_interface_checkpoint", "digest"]
