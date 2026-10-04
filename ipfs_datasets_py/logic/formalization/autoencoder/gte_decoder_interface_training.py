"""Bounded reference-supervised training of four private decoder interfaces.

The learned 384D and 8D decoder bodies stay exact and frozen. A complete native
input plan is admitted before Torch or a fresh optimizer is imported. This
experimental pilot starts with the original seeded interfaces, uses separate
reference CE objectives, and exports neither donor moments nor resume state.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path


REPORT_SCHEMA = "gte-decoder-interface-training-report/v1"
VERIFICATION_SCHEMA = "gte-decoder-interface-reload-verification/v1"
INTERFACES = ("primary.input_adapter.weight", "primary.input_adapter.bias",
              "auxiliary_connector.weight", "auxiliary_connector.bias")
HEADS = ("primary384", "legacy8")
FLAGS = {
    "reference_supervised_training_executed": True,
    "reference_supervised_objective_computed": True,
    "training_executed": True,
    "distillation_executed": False,
    "encoder_inference_executed": False,
    "download_executed": False,
    "teacher_qualified": False,
    "production_kd_eligible": False,
    "production_kd_enabled": False,
    "source_fidelity_qualified": False,
    "proof_authority": False,
    "optimizer_resume_supported": False,
    "producer_execution_authenticated": False,
    "input_adapter_exercised": True,
    "auxiliary_connector_exercised": True,
    "native768_inputs_used": True,
    "logits_combined": False,
    "inherited_gradients_absent": True,
    "all_26_inherited_tensors_unchanged": True,
    "original_decoder_initialization_unchanged": True,
    "interfaces_changed": True,
    "exact_trained_reload_passed": True,
    "all_selected_reference_outputs_preserved_on_reload": True,
}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_interface_training_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load interface training dependency")
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
    names = ("gte_decoder_interface_training", "gte_decoder_interface_checkpoint",
             "gte_decoder_native_objective", "gte_decoder_native_batch",
             "gte_decoder_transfer_replay", "gte_decoder_reuse", "gte_decoder_warm_start",
             "gte_legacy8_decoder_donor")
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _controls(steps, learning_rate, max_grad_norm, head_weights):
    _require(type(steps) is int and 1 <= steps <= 64, "bounded integer interface steps 1..64 required")
    for value, lower, upper, label in ((learning_rate, 1e-6, 1e-2, "learning rate"),
                                        (max_grad_norm, 1e-6, 100., "gradient norm")):
        _require(type(value) in (int, float) and lower <= value <= upper and math.isfinite(value),
                 "finite bounded " + label + " required")
    weights = dict.fromkeys(HEADS, 1.) if head_weights is None else deepcopy(head_weights)
    _require(type(weights) is dict and set(weights) == set(HEADS), "closed independent head weights required")
    _require(all(type(value) in (int, float) and 0 < value <= 100 and math.isfinite(value)
                 for value in weights.values()), "both interface-training head weights must be finite and positive")
    return float(learning_rate), float(max_grad_norm), {name: float(weights[name]) for name in HEADS}


def _summary(objective):
    return {"loss": float(objective["loss"].detach()), "heads": {
        name: {**head, "loss": float(head["loss"].detach())} for name, head in objective["heads"].items()}}


def _interface_state(model):
    parameters = dict(model.named_parameters())
    return {name: parameters[name].detach().tolist() for name in INTERFACES}


def _gradient_diagnostics(torch, parameters):
    diagnostics, norms = {}, []
    for name in INTERFACES:
        parameter = parameters[name]
        grad = parameter.grad
        _require(grad is not None and grad.device.type == "cpu" and grad.dtype == torch.float32
                 and tuple(grad.shape) == tuple(parameter.shape) and bool(torch.isfinite(grad).all())
                 and bool(torch.count_nonzero(grad)), "finite nonzero interface gradient required: " + name)
        norm = torch.linalg.vector_norm(grad.detach().to(torch.float64))
        norms.append(norm)
        diagnostics[name] = {"shape": list(grad.shape), "element_count": grad.numel(), "finite": True,
            "nonzero": True, "max_abs": float(grad.detach().abs().max()), "l2_norm": float(norm)}
    global_norm = float(torch.linalg.vector_norm(torch.stack(norms)))
    _require(math.isfinite(global_norm) and global_norm > 0, "finite positive global interface gradient norm required")
    return diagnostics, global_norm


def _unchanged_inherited(torch, parameters, inherited):
    _require(all(parameters[name].grad is None and not parameters[name].requires_grad
                 and torch.equal(parameters[name].detach(), tensor) for name, tensor in inherited.items()),
             "inherited decoder tensor or gradient changed during interface training")


def _reference_outputs(torch, model, plan):
    """Digest every selected native/reference forward, including both branches."""
    inventory = {}
    with torch.no_grad():
        for name in HEADS:
            rows = []
            for row in plan["heads"][name]["rows"]:
                vector = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32, device="cpu")
                prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64, device="cpu")
                bos = torch.tensor([[1]], dtype=torch.int64, device="cpu")
                output = model(vector, prefix if name == "primary384" else bos,
                               bos if name == "primary384" else prefix)
                rows.append({"id": row["id"], "source_sha256": row["source_sha256"],
                    "reference_prefix_sha256": row["reference_prefix_sha256"], "native_row_sha256": row["native_row_sha256"],
                    **{key + "_sha256": digest(value.detach().tolist()) for key, value in output.items()}})
            inventory[name] = rows
    return inventory


def _verify_reload(torch, original, reloaded, plan):
    original_state, reloaded_state = original.state_dict(), reloaded.state_dict()
    _require(set(original_state) == set(reloaded_state) and all(torch.equal(original_state[name], reloaded_state[name])
                 for name in original_state), "trained checkpoint reload changed model state")
    original_pointers = {parameter.untyped_storage().data_ptr() for parameter in original.parameters()}
    reload_pointers = {parameter.untyped_storage().data_ptr() for parameter in reloaded.parameters()}
    _require(len(original_pointers) == len(reload_pointers) == 30 and original_pointers.isdisjoint(reload_pointers),
             "trained reload must own all private tensor storage")
    with torch.no_grad():
        for name in HEADS:
            for row in plan["heads"][name]["rows"]:
                vector = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32, device="cpu")
                prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64, device="cpu")
                bos = torch.tensor([[1]], dtype=torch.int64, device="cpu")
                primary = prefix if name == "primary384" else bos
                auxiliary = bos if name == "primary384" else prefix
                previous, restored = original(vector, primary, auxiliary), reloaded(vector, primary, auxiliary)
                _require(set(previous) == set(restored) and all(torch.equal(previous[key], restored[key]) for key in previous),
                         "trained checkpoint reload changed selected reference-prefix output: " + name)


def train_decoder_interfaces(plan, *, initialization, batch, replay, expected_donor_pins,
                             steps=8, learning_rate=1e-3, max_grad_norm=1., head_weights=None):
    """Train a private initialization's interfaces and return a new checkpoint.

    The immutable original plan is fully admitted once before Torch. Subsequent
    steps use the admitted local copy and the unchanged original CE arithmetic.
    This initializes a fresh AdamW run; it accepts no optimizer or fitted-start
    state. Loss changes describe this pilot and confer no semantic qualification.
    """
    learning_rate, max_grad_norm, weights = _controls(steps, learning_rate, max_grad_norm, head_weights)
    original_inputs = [initialization, plan, batch, replay, expected_donor_pins]
    original_inputs_sha = digest(original_inputs)
    owned_initialization, owned_plan, owned_batch, owned_replay, owned_pins = deepcopy(original_inputs)
    owned_inputs = [owned_initialization, owned_plan, owned_batch, owned_replay, owned_pins]
    owned_inputs_sha = digest(owned_inputs)
    objective = _helper("gte_decoder_native_objective")
    objective._admit(owned_plan, owned_initialization, owned_batch, owned_replay, owned_pins, weights)
    import torch
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled interface training required")
    with objective._numerical_context(torch):
        model = _helper("gte_decoder_reuse").load_dual_decoder(owned_initialization, expected_donor_pins=owned_pins)
        parameters = objective._admit_model(torch, model, owned_initialization)
        inherited = {name: parameter.detach().clone() for name, parameter in parameters.items() if name not in INTERFACES}
        _require(len(inherited) == 26 and all(parameter.grad is None for parameter in parameters.values()),
                 "fresh private frozen-head model required")
        before_model_sha = objective._state_digest(model)
        initial_interfaces = _interface_state(model)
        before_interface_sha = digest(initial_interfaces)
        trainable = [parameters[name] for name in INTERFACES]
        optimizer = torch.optim.AdamW(trainable, lr=learning_rate, betas=(.9, .999), eps=1e-8,
                                      weight_decay=0., amsgrad=False, maximize=False, foreach=False)
        _require(not optimizer.state and len(optimizer.param_groups) == 1
                 and len(optimizer.param_groups[0]["params"]) == 4, "fresh four-interface optimizer required")
        result = objective._compute(torch, model, owned_plan, weights)
        before = _summary(result)
        history = []
        for step in range(1, steps + 1):
            step_before = _summary(result)
            optimizer.zero_grad(set_to_none=True)
            result["loss"].backward()
            gradients, norm_before = _gradient_diagnostics(torch, parameters)
            _unchanged_inherited(torch, parameters, inherited)
            torch.nn.utils.clip_grad_norm_(trainable, max_grad_norm, error_if_nonfinite=True, foreach=False)
            _, norm_after = _gradient_diagnostics(torch, parameters)
            _require(norm_after <= max_grad_norm * (1 + 2e-6), "interface gradient clipping exceeded configured bound")
            optimizer.step()
            _unchanged_inherited(torch, parameters, inherited)
            _require(all(bool(torch.isfinite(parameter).all()) for parameter in trainable),
                     "nonfinite updated interface tensor")
            _require(all(int(optimizer.state[parameter]["step"].item()) == step for parameter in trainable),
                     "fresh interface optimizer step count differs")
            result = objective._compute(torch, model, owned_plan, weights)
            step_after = _summary(result)
            history.append({"step": step, "loss_before": step_before["loss"], "loss_after": step_after["loss"],
                "head_losses_before": {name: step_before["heads"][name]["loss"] for name in HEADS},
                "head_losses_after": {name: step_after["heads"][name]["loss"] for name in HEADS},
                "gradient_global_norm_before_clipping": norm_before,
                "gradient_global_norm_after_clipping": norm_after, "interface_gradients": gradients})
        after = _summary(result)
        interfaces = _interface_state(model)
        _require(all(digest(interfaces[name]) != digest(initial_interfaces[name]) for name in INTERFACES),
                 "each trained interface must change from its initial values")
        _unchanged_inherited(torch, parameters, inherited)
        trained_reference_outputs = _reference_outputs(torch, model, owned_plan)
        report = {"schema": REPORT_SCHEMA, "status": "reference_interfaces_trained_unqualified",
            "initialization_representation_id": owned_initialization["representation_id"],
            "plan_sha256": owned_plan["plan_sha256"], "batch_sha256": owned_batch["batch_sha256"],
            "replay_sha256": digest(owned_replay), "donor_pins": deepcopy(owned_pins),
            "profile_id": owned_plan["profile_id"], "primary_start": "original_initialization",
            "steps": steps, "optimizer_steps": steps,
            "optimizer": {"name": "AdamW", "fresh": True, "learning_rate": learning_rate,
                "weight_decay": 0., "betas": [.9, .999], "eps": 1e-8, "parameters": list(INTERFACES),
                "donor_state_imported": False, "resume": False},
            "max_grad_norm": max_grad_norm, "head_weights": weights, "objective": "reference_cross_entropy",
            "head_normalization": "eligible_reference_tokens_within_each_head", "before": before, "after": after,
            "history": history, "interface_state_sha256_before": before_interface_sha,
            "interface_state_sha256_after": digest(interfaces), "model_state_sha256_before": before_model_sha,
            "model_state_sha256_after": objective._state_digest(model), "inherited_tensor_count": 26,
            "trained_reference_outputs": trained_reference_outputs,
            "trained_reference_outputs_sha256": digest(trained_reference_outputs),
            "numerical_profile": {"device": "cpu", "dtype": "float32", "threads": 1, "evaluation_mode": True},
            "implementation": _implementation(), **FLAGS}
        contract = _helper("gte_decoder_interface_checkpoint")
        checkpoint = contract.create_interface_checkpoint(owned_initialization, owned_plan,
            expected_donor_pins=owned_pins, interfaces=interfaces, training_report=report)
        admission = {"initialization": owned_initialization, "plan": owned_plan, "batch": owned_batch,
                     "replay": owned_replay, "expected_donor_pins": owned_pins}
        contract.inspect_interface_checkpoint(checkpoint, **admission)
        reloaded = contract.load_interface_checkpoint(checkpoint, **admission)
        _verify_reload(torch, model, reloaded, owned_plan)
        _require(digest(owned_inputs) == owned_inputs_sha and digest(original_inputs) == original_inputs_sha,
                 "interface training mutated original or owned input artifacts")
    return {"checkpoint": deepcopy(checkpoint), "report": deepcopy(report)}


def verify_trained_interface_reload(checkpoint, *, initialization, plan, batch, replay,
                                    expected_donor_pins):
    """Numerically verify a saved trained generation against its live-run export.

    Complete checkpoint and native-plan admission happens before Torch. Two
    independent private reloads must match the report's actual post-optimizer
    state and every selected reference output. This verifier never trains or
    creates an optimizer; it cannot authenticate the native encoder producer.
    """
    original_inputs = [checkpoint, initialization, plan, batch, replay, expected_donor_pins]
    original_inputs_sha = digest(original_inputs)
    owned_checkpoint, owned_initialization, owned_plan, owned_batch, owned_replay, owned_pins = deepcopy(original_inputs)
    admission = {"initialization": owned_initialization, "plan": owned_plan, "batch": owned_batch,
                 "replay": owned_replay, "expected_donor_pins": owned_pins}
    contract = _helper("gte_decoder_interface_checkpoint")
    contract.inspect_interface_checkpoint(owned_checkpoint, **admission)
    report = owned_checkpoint["training_report"]
    objective = _helper("gte_decoder_native_objective")
    import torch
    with objective._numerical_context(torch), torch.no_grad():
        first = contract.load_interface_checkpoint(owned_checkpoint, **admission)
        second = contract.load_interface_checkpoint(owned_checkpoint, **admission)
        for model in (first, second):
            parameters = objective._admit_model(torch, model, owned_initialization)
            _require(all(parameter.grad is None for parameter in parameters.values()),
                     "reloaded trained generation must not contain gradient buffers")
            _require(objective._state_digest(model) == report["model_state_sha256_after"],
                     "saved model state differs from actual post-optimizer export")
            outputs = _reference_outputs(torch, model, owned_plan)
            _require(outputs == report["trained_reference_outputs"]
                     and digest(outputs) == report["trained_reference_outputs_sha256"],
                     "saved reference outputs differ from actual post-optimizer export")
        _verify_reload(torch, first, second, owned_plan)
        _require(digest(original_inputs) == original_inputs_sha
                 and digest([owned_checkpoint, owned_initialization, owned_plan, owned_batch, owned_replay, owned_pins])
                    == original_inputs_sha, "saved trained reload verification mutated input artifacts")
        receipt = {"schema": VERIFICATION_SCHEMA, "status": "exact_trained_reload_verified_unqualified",
            "checkpoint_content_sha256": digest(owned_checkpoint), "training_report_sha256": digest(report),
            "initialization_representation_id": owned_initialization["representation_id"],
            "trained_representation_id": owned_checkpoint["representation_id"],
            "plan_sha256": owned_plan["plan_sha256"], "batch_sha256": owned_batch["batch_sha256"],
            "replay_sha256": digest(owned_replay), "donor_pins": deepcopy(owned_pins),
            "model_state_sha256": report["model_state_sha256_after"],
            "trained_reference_outputs_sha256": report["trained_reference_outputs_sha256"],
            "row_counts": {name: len(owned_plan["heads"][name]["rows"]) for name in HEADS},
            "all_26_inherited_tensors_unchanged": True, "inherited_gradients_absent": True,
            "all_30_reloaded_tensors_bitwise_equal": True, "private_storage_disjoint": True,
            "trained_reference_outputs_match": True, "original_inputs_unchanged": True,
            "optimizer_created": False, "optimizer_steps": 0, "training_executed": False,
            "distillation_executed": False, "encoder_inference_executed": False, "download_executed": False,
            "teacher_qualified": False, "production_kd_eligible": False, "production_kd_enabled": False,
            "source_fidelity_qualified": False, "proof_authority": False,
            "producer_execution_authenticated": False, "optimizer_resume_supported": False,
            "numerical_profile": {"device": "cpu", "dtype": "float32", "threads": 1, "evaluation_mode": True},
            "implementation": _implementation()}
    return receipt


__all__ = ["train_decoder_interfaces", "verify_trained_interface_reload", "REPORT_SCHEMA", "VERIFICATION_SCHEMA"]
