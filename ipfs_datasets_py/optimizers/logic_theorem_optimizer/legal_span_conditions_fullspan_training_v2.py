"""Recipe-bound numerical continuation of the immutable F18 donor profile.

The caller owns original source/resource admission. This sibling neither grants
custody nor runs a process. It keeps the v1 donor configuration and numerical
kernels, and uses a separately declared recipe for one fresh four-tensor Adam.
No v1 checkpoint is relabelled, and this module supplies no capture or scoring.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import time

from . import legal_span_conditions_fullspan_training_v1 as base
from . import legal_span_conditions_fullspan_optimizer_recipe_v1 as recipes

SCHEMA = "conditions-fullspan-f18-four-tensor-training/v2"
CHECKPOINT_SCHEMA = "conditions-fullspan-f18-four-tensor-checkpoint/v2"
CHECKPOINT_LINEAGE_ID = "conditions_fullspan_f18_four_tensor_v2"
REPORT_SCHEMA = "conditions-fullspan-four-tensor-continuation-report/v2"
ADAM_SCHEMA = base.ADAM_SCHEMA
SELECTED, FROZEN = base.SELECTED, base.FROZEN
CONDITIONS_ROW, INACTIVE_ROWS = base.CONDITIONS_ROW, base.INACTIVE_ROWS
MAX_UPDATES, MAX_SECONDS = 32, 32
MAX_CHECKPOINT_BYTES = base.MAX_CHECKPOINT_BYTES
BINDINGS_SCHEMA, BINDING_FIELDS = base.BINDINGS_SCHEMA, base.BINDING_FIELDS
checkpoint_digest = base.checkpoint_digest
_BASE_SHA256 = "56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147"
_RECIPE_SHA256 = "d22b932b80c48b688ff3f18d5f141152a6032b7cb2f6195845840af818d8dc84"
_BASE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py"
_RECIPE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_optimizer_recipe_v1.py"
_OWN_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v2.py"
_FIELDS = base._CHECKPOINT_FIELDS
_AUTHORITY = dict(base._AUTHORITY, native_admission=False,
                  input_origins_verified=False, initial_parity_verified=False)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return base._checkpoint_raw(value)


def _copy(value):
    return base._detached(value)


def _source(path, maximum):
    path = Path(path)
    _need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
          "bounded regular v2 source required")
    raw = path.read_bytes()
    _need(0 < len(raw) <= maximum, "bounded regular v2 source required")
    return hashlib.sha256(raw).hexdigest()


_SOURCE_AT_IMPORT = _source(__file__, 64 * 1024)


def _implementation():
    _need(_source(base.__file__, 128 * 1024) == _BASE_SHA256,
          "immutable profile56 source required")
    _need(_source(recipes.__file__, 64 * 1024) == _RECIPE_SHA256,
          "immutable qualified pure recipe source required")
    own = Path(__file__)
    _need(own.resolve() == Path(base.__file__).resolve().with_name(Path(_OWN_PATH).name)
          and _source(own, 64 * 1024) == _SOURCE_AT_IMPORT,
          "v2 sibling source changed since import")
    return {"schema": "conditions-fullspan-v2-source-owners/v1",
            "base": base._checkpoint_implementation(),
            "optimizer_recipe": {"path": _RECIPE_PATH, "sha256": _RECIPE_SHA256},
            "numerical": {"path": _OWN_PATH, "sha256": _SOURCE_AT_IMPORT}}


def _policy(recipe, provenance, expected_bindings, learning_rate, margin_weight):
    _need(type(provenance) is dict and type(provenance.get("config")) is dict,
          "independent F18 donor configuration required")
    # Every expectation comes from the caller scope, never from checkpoint fields.
    return recipes.validate_optimizer_recipe(recipe, donor_config=provenance["config"],
        expected_bindings=expected_bindings, learning_rate=learning_rate,
        margin_weight=margin_weight)


def _checked_checkpoint(checkpoint, state, provenance, records, teacher, weights,
                        expected_bindings, recipe, learning_rate, margin_weight):
    _need(type(checkpoint) is dict and set(checkpoint) == _FIELDS
          and checkpoint.get("schema") == CHECKPOINT_SCHEMA
          and checkpoint.get("lineage_id") == CHECKPOINT_LINEAGE_ID,
          "closed v2 four-tensor checkpoint required")
    policy = _policy(recipe, provenance, expected_bindings, learning_rate, margin_weight)
    _need(_raw(checkpoint["authority"]) == _raw(_AUTHORITY), "v2 checkpoint authority differs")
    _need(_raw(checkpoint["training_policy"]) == _raw(policy)
          and checkpoint["training_policy_sha256"] == checkpoint_digest(policy),
          "v2 independent recipe policy differs")
    _need(checkpoint["implementation"] == _implementation(), "v2 source owner binding differs")
    raw = _raw(checkpoint)
    _need(0 < len(raw) <= MAX_CHECKPOINT_BYTES, "v2 checkpoint byte bound exceeded")
    shapes, donor_root, seal = base._prepared_inputs(
        state, provenance, records, teacher, weights, expected_bindings)
    _need(_raw(checkpoint["input_bindings"]) == _raw(expected_bindings)
          and _raw(checkpoint["donor_provenance"]) == _raw(provenance),
          "v2 input or donor provenance differs")
    _need(checkpoint["donor_state_sha256"] == donor_root
          and checkpoint["source_frozen38_sha256"] == seal
          and checkpoint["source_inactive650_sha256"] == checkpoint_digest(base._inactive650(state))
          and checkpoint["selection_sha256"] == checkpoint_digest(base.selection_mask_contract()),
          "v2 donor/frozen38/inactive650/selection differs")
    selected = checkpoint["selected_state"]
    _need(type(selected) is dict and set(selected) == set(SELECTED), "exact four selected tensors required")
    reconstructed = copy.deepcopy(state)
    for name in SELECTED:
        base._binary32_tree(selected[name], shapes[name], name)
        reconstructed[name] = copy.deepcopy(selected[name])
    base._validate_state(reconstructed, shapes)
    _need(base.frozen38_seal(reconstructed) == seal
          and _raw(base._inactive650(reconstructed)) == _raw(base._inactive650(state))
          and checkpoint["model_state_sha256"] == checkpoint_digest(reconstructed),
          "v2 reconstructed42/frozen38/inactive650 differs")
    progress = base.f18.targeted._progress(checkpoint["progress"])
    _need(progress["optimizer_steps"] <= MAX_UPDATES, "v2 cumulative32 update budget exceeded")
    base.f18.targeted._batch_indices(base.TRAIN_INDEX_COUNT, progress, base.BATCH_SIZE, base.SEED)
    base._validate_four_adam(checkpoint["optimizer_state"], progress["optimizer_steps"], shapes)
    if progress["optimizer_steps"] == 0:
        _need(checkpoint["parent_checkpoint_sha256"] is None
              and _raw(reconstructed) == _raw(state), "v2 initial donor or parent differs")
    else:
        base._sha256_text(checkpoint["parent_checkpoint_sha256"])
    _need(checkpoint["initial_checkpoint_sha256"] == checkpoint_digest(base._checkpoint_origin(checkpoint, state)),
          "v2 initial checkpoint lineage differs")
    return reconstructed, policy


def build_checkpoint(state, provenance, *, records, teacher, weights, expected_bindings,
                     recipe, learning_rate, margin_weight):
    """Build a zero-step delta from caller-authenticated inputs; no model is made."""
    policy = _policy(recipe, provenance, expected_bindings, learning_rate, margin_weight)
    implementation = _implementation()
    _, donor_root, seal = base._prepared_inputs(
        state, provenance, records, teacher, weights, expected_bindings)
    value = {"schema": CHECKPOINT_SCHEMA, "lineage_id": CHECKPOINT_LINEAGE_ID,
        "implementation": implementation, "training_policy": policy,
        "training_policy_sha256": checkpoint_digest(policy),
        "input_bindings": _copy(expected_bindings), "donor_provenance": _copy(provenance),
        "selection_sha256": checkpoint_digest(base.selection_mask_contract()),
        "donor_state_sha256": donor_root, "source_frozen38_sha256": seal,
        "source_inactive650_sha256": checkpoint_digest(base._inactive650(state)),
        "selected_state": {name: copy.deepcopy(state[name]) for name in SELECTED},
        "model_state_sha256": donor_root, "optimizer_state": {"schema": ADAM_SCHEMA, "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, "authority": dict(_AUTHORITY)}
    value["initial_checkpoint_sha256"] = checkpoint_digest(base._checkpoint_origin(value, state))
    _checked_checkpoint(value, state, provenance, records, teacher, weights,
                        expected_bindings, recipe, learning_rate, margin_weight)
    return _copy(value)


def validate_checkpoint(checkpoint, *, state, provenance, records, teacher, weights,
                        expected_bindings, recipe, learning_rate, margin_weight):
    """Validate source, typed state, recipe and lineage without constructing Torch."""
    _checked_checkpoint(checkpoint, state, provenance, records, teacher, weights,
                        expected_bindings, recipe, learning_rate, margin_weight)


def save_checkpoint(checkpoint, path, *, state, provenance, records, teacher, weights,
                    expected_bindings, recipe, learning_rate, margin_weight):
    """Exclusive bounded persistence; no checkpoint/admission schema conversion."""
    from . import autoencoder_daemon_invocation_contracts as io
    kwargs = dict(state=state, provenance=provenance, records=records, teacher=teacher,
        weights=weights, expected_bindings=expected_bindings, recipe=recipe,
        learning_rate=learning_rate, margin_weight=margin_weight)
    validate_checkpoint(checkpoint, **kwargs)
    value = _copy(checkpoint)
    ref = io.write_new(path, value, MAX_CHECKPOINT_BYTES)
    loaded = load_checkpoint(ref["path"], expected_sha256=ref["sha256"], **kwargs)
    _need(_raw(loaded) == _raw(value), "persisted v2 checkpoint bytes differ")
    return {**ref, "schema": CHECKPOINT_SCHEMA}


def load_checkpoint(path, *, expected_sha256, state, provenance, records, teacher, weights,
                    expected_bindings, recipe, learning_rate, margin_weight):
    """Read one independently hash-bound checkpoint through the original strict IO."""
    from . import autoencoder_daemon_invocation_contracts as io
    from . import validation_run_resources as storage
    # Refuse invalid independent policy/source before opening a checkpoint body.
    _policy(recipe, provenance, expected_bindings, learning_rate, margin_weight)
    _implementation()
    base._sha256_text(expected_sha256)
    try:
        _, raw, _ = storage._regular_bytes(path, MAX_CHECKPOINT_BYTES)
        _need(0 < len(raw) and hashlib.sha256(raw).hexdigest() == expected_sha256,
              "v2 checkpoint physical SHA256 differs")
        value = io.parse_json(raw)
    except (storage.host.DaemonResourceError, OSError) as error:
        raise ValueError("bounded unaliased v2 checkpoint input required") from error
    validate_checkpoint(value, state=state, provenance=provenance, records=records,
        teacher=teacher, weights=weights, expected_bindings=expected_bindings,
        recipe=recipe, learning_rate=learning_rate, margin_weight=margin_weight)
    return _copy(value)


def _live_state(torch, runtime, donor, steps, policy, *, gradients=False):
    model, named, optimizer = runtime["model"], runtime["named"], runtime["optimizer"]
    _need(torch is runtime["torch"] and _raw(runtime["recipe"]) == _raw(policy)
          and _raw(runtime["config"]) == _raw(policy["donor_config"]), "v2 runtime recipe/config changed")
    parameters = tuple(model.named_parameters())
    _need(tuple(named) == base.f18.MODEL_PARAMETER_NAMES
          and len({id(value) for value in named.values()}) == base.DONOR_TENSOR_COUNT
          and tuple(name for name, _ in parameters) == tuple(named)
          and all(parameter is named[name] for name, parameter in parameters),
          "v2 live closed42 parameter identity differs")
    _need(len(runtime["selected"]) == len(SELECTED)
          and all(parameter is named[name] for name, parameter in zip(SELECTED, runtime["selected"], strict=True))
          and all(named[name].requires_grad is (name in SELECTED) for name in named)
          and all(named[name].grad is None for name in FROZEN), "v2 frozen38 or selection gradients differ")
    _need(len(optimizer.param_groups) == 1
          and tuple(id(parameter) for parameter in optimizer.param_groups[0]["params"])
              == tuple(id(named[name]) for name in SELECTED)
          and set(optimizer.state) <= {named[name] for name in SELECTED},
          "v2 live ordered four-tensor Adam differs")
    controls = policy["optimizer_recipe"]
    expected = {"lr": controls["learning_rate"], "betas": tuple(controls["betas"]),
        "eps": controls["eps"], "weight_decay": controls["weight_decay"], "foreach": controls["foreach"]}
    _need(all(type(optimizer.param_groups[0].get(key)) is type(value)
              and type(optimizer.defaults.get(key)) is type(value)
              and optimizer.param_groups[0].get(key) == value and optimizer.defaults.get(key) == value
              for key, value in expected.items()), "v2 live actual Adam recipe changed")
    _need(type(runtime["learning_rate"]) is type(controls["learning_rate"])
          and runtime["learning_rate"] == controls["learning_rate"]
          and runtime["recipe_sha256"] == checkpoint_digest(policy), "v2 runtime recipe identity changed")
    _need(type(runtime["model_forwards"]) is int and runtime["model_forwards"] >= 0,
          "v2 forward accounting required")
    for name in ("_actor_forward_accounting", "_conditions_forward_accounting"):
        table = getattr(model, name, None)
        _need(type(table) is dict and table and "source_model_forwards" in table
              and all(type(value) is int and value == runtime["model_forwards"] for value in table.values()),
              "v2 actual native forward counters differ")
    if gradients:
        for name in SELECTED:
            grad = named[name].grad
            _need(grad is not None and bool(torch.isfinite(grad).all())
                  and all(bool((grad[row] == 0).all()) for row in INACTIVE_ROWS),
                  "finite v2 row3-only gradients required")
    _need(all(value.dtype == torch.float32 and value.device.type == "cpu"
              and bool(torch.isfinite(value).all()) for value in model.state_dict().values()),
          "finite CPU float32 v2 state required")
    actual, moments = base.f18.span._pack(model, optimizer)
    moments["schema"] = ADAM_SCHEMA
    base._validate_four_adam(moments, steps, base._donor_shapes(runtime["config"]))
    _need(base.frozen38_seal(actual) == base.frozen38_seal(donor)
          and _raw(base._inactive650(actual)) == _raw(base._inactive650(donor)),
          "v2 live frozen38/inactive650 bytes changed")
    return actual, moments


def restore_optimizer(torch, checkpoint, state, provenance, *, records, teacher, weights,
                      expected_bindings, recipe, learning_rate, margin_weight):
    """Restore one fresh CPU F18 model and direct recipe-rate Adam, no forward."""
    reconstructed, policy = _checked_checkpoint(checkpoint, state, provenance, records,
        teacher, weights, expected_bindings, recipe, learning_rate, margin_weight)
    _need(torch is base.f18.sys.modules.get("torch"), "original caller Torch owner required")
    ambient = torch.get_rng_state().clone()
    incoming_grad_mode = torch.is_grad_enabled()
    model = optimizer = None
    try:
        with torch.random.fork_rng(devices=[]):
            model = base.f18._model(torch, provenance["config"])
            named = dict(model.named_parameters())
            _need(tuple(named) == base.f18.MODEL_PARAMETER_NAMES, "v2 closed42 model required")
            model.load_state_dict({name: base.f18.span._tensor(torch, reconstructed[name], parameter.shape, name)
                for name, parameter in model.state_dict().items()}, strict=True)
            for name, parameter in named.items():
                parameter.requires_grad_(name in SELECTED)
                parameter.grad = None
                if name in SELECTED:
                    parameter.register_hook(lambda gradient, row=CONDITIONS_ROW: base._mask_gradient(gradient, row))
            selected = [named[name] for name in SELECTED]
            controls = policy["optimizer_recipe"]
            optimizer = torch.optim.Adam(selected, lr=controls["learning_rate"],
                betas=tuple(controls["betas"]), eps=controls["eps"],
                weight_decay=controls["weight_decay"], foreach=controls["foreach"])
            _need(optimizer.state == {}, "v2 Adam must start with fresh empty moments")
            for name in SELECTED:
                moment = checkpoint["optimizer_state"]["parameters"].get(name)
                if moment is not None:
                    parameter = named[name]
                    optimizer.state[parameter] = {
                        "step": torch.tensor(float(moment["step"]), dtype=torch.float32, device="cpu"),
                        "exp_avg": base.f18.span._tensor(torch, moment["exp_avg"], parameter.shape, name),
                        "exp_avg_sq": base.f18.span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
            model.eval()
            counters = sum(sum(getattr(model, name, {}).values()) for name in
                           ("_actor_forward_accounting", "_conditions_forward_accounting"))
            _need(counters == 0 and all(parameter.grad is None for parameter in named.values()),
                  "v2 restore performed a forward or retained gradients")
            runtime = {"torch": torch, "model": model, "optimizer": optimizer, "named": named,
                "selected": selected, "config": _copy(provenance["config"]), "recipe": _copy(policy),
                "recipe_sha256": checkpoint_digest(policy), "learning_rate": learning_rate,
                "progress": dict(checkpoint["progress"]), "checkpoint_sha256": checkpoint_digest(checkpoint),
                "optimizer_steps": checkpoint["progress"]["optimizer_steps"], "model_forwards": 0,
                "restored": True, "training_executed": False, **_AUTHORITY}
            actual, moments = _live_state(torch, runtime, state, checkpoint["progress"]["optimizer_steps"], policy)
            _need(checkpoint_digest(actual) == checkpoint["model_state_sha256"]
                  and _raw(moments) == _raw(checkpoint["optimizer_state"]),
                  "v2 restored42/four-Adam differs")
        _need(torch.equal(ambient, torch.get_rng_state())
              and torch.is_grad_enabled() is incoming_grad_mode, "v2 restore changed caller RNG/gradmode")
        _need(_implementation() == checkpoint["implementation"], "v2 restore closing source changed")
        return runtime
    finally:
        if model is not None:
            model.eval()
        if optimizer is not None:
            optimizer.zero_grad(set_to_none=True)


def run_admitted_updates(checkpoint, provenance=None, *, torch=None, state=None,
                         records=None, teacher=None, weights=None, expected_bindings=None,
                         recipe=None, learning_rate=None, margin_weight=None,
                         max_steps=32, max_seconds=32):
    """One caller-owned finite TRAIN continuation; this API grants no custody."""
    _need(all(value is not None for value in (torch, state, provenance, records, teacher,
          weights, expected_bindings, recipe, learning_rate, margin_weight)),
          "complete caller-owned v2 checkpoint/input scope required")
    _need(type(max_steps) is int and 0 <= max_steps <= MAX_UPDATES
          and type(max_seconds) in (int, float) and math.isfinite(max_seconds)
          and 0 <= max_seconds <= MAX_SECONDS, "bounded32-step/32-second v2 call required")
    started = time.monotonic()
    deadline = started + max_seconds
    _, policy = _checked_checkpoint(checkpoint, state, provenance, records, teacher,
        weights, expected_bindings, recipe, learning_rate, margin_weight)
    value = _copy(checkpoint)
    input_root = checkpoint_digest(value)
    donor, provenance = copy.deepcopy(state), copy.deepcopy(provenance)
    records, teacher, weights = copy.deepcopy(records), copy.deepcopy(teacher), copy.deepcopy(weights)
    expected_bindings, recipe = _copy(expected_bindings), _copy(recipe)
    progress = dict(value["progress"])
    _need(progress["optimizer_steps"] + max_steps <= MAX_UPDATES, "v2 cumulative32 update budget exceeded")
    before_progress = dict(progress)
    trace, reason = [], "step_limit"
    runtime = None
    ambient = torch.get_rng_state().clone()
    incoming_grad_mode = torch.is_grad_enabled()
    try:
        with torch.random.fork_rng(devices=[]), torch.enable_grad():
            if max_steps and time.monotonic() < deadline:
                runtime = restore_optimizer(torch, value, donor, provenance, records=records,
                    teacher=teacher, weights=weights, expected_bindings=expected_bindings,
                    recipe=recipe, learning_rate=learning_rate, margin_weight=margin_weight)
            for _ in range(max_steps):
                if time.monotonic() >= deadline:
                    reason = "deadline_before_batch"
                    break
                _need(runtime is not None, "v2 restore did not complete")
                indices = base.f18.targeted._batch_indices(base.TRAIN_INDEX_COUNT, progress, base.BATCH_SIZE, base.SEED)
                batch = [records[index] for index in indices]
                model, optimizer = runtime["model"], runtime["optimizer"]
                optimizer.zero_grad(set_to_none=True)
                _live_state(torch, runtime, donor, progress["optimizer_steps"], policy)
                model.train()
                output = model(*base.f18.span._batch(torch, batch))
                runtime["model_forwards"] += 1
                objective = base.compose_objective_for_state(torch, output, batch, indices,
                    teacher, weights, donor, provenance, margin_weight=margin_weight)
                margin_trace = {key: float(item.detach()) if key in ("loss", "weighted_loss") else copy.deepcopy(item)
                                for key, item in objective["margin"].items()}
                margin_inputs = {"start_logits": output["start"][:, CONDITIONS_ROW, :].detach().tolist(),
                    "end_logits": output["end"][:, CONDITIONS_ROW, :].detach().tolist(),
                    "targets": base._conditions_targets(batch), "pre_update": True}
                objective["loss"].backward()
                _live_state(torch, runtime, donor, progress["optimizer_steps"], policy, gradients=True)
                gradient = float(base.clip_selected_gradients(torch, runtime["selected"]))
                optimizer.step()
                after = base.f18.targeted._advance_progress(progress, len(indices), base.TRAIN_INDEX_COUNT)
                current, moments = _live_state(torch, runtime, donor, after["optimizer_steps"], policy, gradients=True)
                _need(torch.equal(ambient, torch.get_rng_state()), "v2 TRAIN step consumed CPU RNG")
                f18_loss = float(objective["f18_ce_plus_kl"].detach())
                legacy_trace = base.f18.targeted._batch_trace_entry(indices, records, progress, after,
                    loss=f18_loss, gradient_norm=gradient)
                details = {"weighted_CE": objective["weighted_CE"], "retention": objective["retention"],
                    "total_loss": f18_loss, "teacher_forcing": True, "evaluation_references_used": False}
                base.f18._validate_objective_entry({"optimizer_step": after["optimizer_steps"],
                    "indices": indices, "ids": legacy_trace["ids"], "details": details}, legacy_trace,
                    base.f18._policy("modality-conditions-retention-ce"), teacher, weights)
                trace.append({**legacy_trace, "loss": float(objective["loss"].detach()),
                    "f18_ce_plus_kl": f18_loss, "weighted_conditions_margin": float(objective["margin"]["weighted_loss"].detach()),
                    "margin_weight": float(margin_weight), "learning_rate": learning_rate,
                    "f18_objective_details": copy.deepcopy(details), "conditions_margin": margin_trace,
                    "conditions_margin_inputs": margin_inputs, "model_state_sha256": checkpoint_digest(current),
                    "frozen38_sha256": base.frozen38_seal(current),
                    "inactive650_sha256": checkpoint_digest(base._inactive650(current)),
                    "optimizer_state_sha256": checkpoint_digest(moments)})
                progress = after
                runtime.update(progress=dict(progress), optimizer_steps=progress["optimizer_steps"], training_executed=True)
            if trace:
                value.update(selected_state={name: current[name] for name in SELECTED},
                    model_state_sha256=checkpoint_digest(current), optimizer_state=moments,
                    progress=progress, parent_checkpoint_sha256=input_root)
    finally:
        if runtime is not None:
            runtime["model"].eval()
            runtime["optimizer"].zero_grad(set_to_none=True)
    _need(torch.equal(ambient, torch.get_rng_state()) and torch.is_grad_enabled() is incoming_grad_mode,
          "v2 caller CPU RNG or gradient mode changed")
    _checked_checkpoint(value, donor, provenance, records, teacher, weights,
                        expected_bindings, recipe, learning_rate, margin_weight)
    _need(runtime is None or runtime["model_forwards"] == len(trace), "v2 update/forward count differs")
    report = {"schema": REPORT_SCHEMA, "checkpoint_sha256": checkpoint_digest(value),
        "input_checkpoint_sha256": input_root, "initial_checkpoint_sha256": value["initial_checkpoint_sha256"],
        "training_policy_sha256": value["training_policy_sha256"], "recipe": _copy(policy),
        "optimizer_recipe": _copy(policy["optimizer_recipe"]), "learning_rate": learning_rate,
        "donor_config_learning_rate": provenance["config"]["learning_rate"],
        "input_bindings": _copy(expected_bindings), "before_progress": before_progress,
        "after_progress": dict(progress), "optimizer_steps": len(trace), "requested_steps": max_steps,
        "reason": reason, "all_requested_steps_completed": len(trace) == max_steps,
        "elapsed_seconds": time.monotonic() - started, "max_seconds": max_seconds,
        "deadline_checked_before_batches": True, "batch_trace": trace,
        "training_executed": bool(trace), "teacher_model_forwards": 0,
        "training_model_forwards": 0 if runtime is None else runtime["model_forwards"],
        "ambient_cpu_rng_preserved": True, "incoming_grad_mode_preserved": True,
        "model_eval_on_exit": True, "tuning_or_evaluation_references_used": False,
        "lineage_integrity_only_not_gradient_replay": True, **_AUTHORITY}
    _need(len(_raw(report)) <= 32 * 1024 * 1024, "finite v2 report byte bound exceeded")
    return _copy(value), _copy(report)


__all__ = ["SCHEMA", "CHECKPOINT_SCHEMA", "CHECKPOINT_LINEAGE_ID", "REPORT_SCHEMA",
    "ADAM_SCHEMA", "SELECTED", "FROZEN", "CONDITIONS_ROW", "INACTIVE_ROWS",
    "MAX_UPDATES", "MAX_SECONDS", "MAX_CHECKPOINT_BYTES", "BINDINGS_SCHEMA", "BINDING_FIELDS",
    "checkpoint_digest", "build_checkpoint", "validate_checkpoint", "save_checkpoint",
    "load_checkpoint", "restore_optimizer", "run_admitted_updates"]
