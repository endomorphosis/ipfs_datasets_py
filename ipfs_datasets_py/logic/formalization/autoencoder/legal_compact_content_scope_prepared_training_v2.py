"""Opt-in v2 prepared training with a qualified byte-compatible custody helper.

The original scope checkpoint, objective, numerical and named-Adam owners remain
unchanged. This consumer replaces only its input-fingerprint custody context;
it preserves bounded original copies, both captured/original commitments, source
and loaded-origin checks, four update guards and nested closing checks. The v1
prepared orchestration is retained with explicit execution-provenance fields.
No old module, checkpoint implementation identity or source pin is rewritten.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time

SCHEMA = "legal-compact-scope-prepared-training-session/v2"
PROFILE = "closed-authored-h0-384-fixed537-cached-scope-training/v2"
ADVANCE_SCHEMA = "legal-compact-scope-prepared-training-advance/v2"
STEP_SCHEMA = "legal-compact-scope-prepared-training-step/v2"
MAX_ADVANCE_STEPS = 4
MAX_STEP_REPORT_BYTES = 24 * 1024**2
MAX_ADVANCE_BYTES = 112 * 1024**2
_SPECS = (
    ("scope_training", "logic/formalization/autoencoder/legal_compact_content_scope_training_v1.py",
     "fb86141cd0b69fe74e43cc9460d557e890c90c07178bf9e1a62d15098552c208"),
    ("session", "logic/formalization/autoencoder/legal_compact_content_weighted_prepared_training_v1.py",
     "6f7248714cea81edfe6fda69bb0abe38bb37535f2cb92d460d8e38c4d2cd4b07"),
    ("fingerprint", "logic/formalization/autoencoder/legal_compact_content_fingerprint_v1.py",
     "e28f769ce751fbadbca7b654aa2b1cae332487aabad2d19b9623d3db3b31f70f"),
    ("original_prepared", "logic/formalization/autoencoder/legal_compact_content_scope_prepared_training_v1.py",
     "a07025ba46fa0357797e709c37c27f7a8faf17e395df2657e3a71fa22533fc5f"),
)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_CATEGORIES = frozenset(("checkpoint_validation", "runtime_fence", "source_input_fence",
    "restore", "tensor_cache_preparation", "state_cache_fence", "forward", "objective",
    "backward", "gradient_capture_clip", "Adam", "actual_state_export_validation",
    "lineage_pack", "report_export"))


class PreparedTrainingError(ValueError):
    """A finite work, source/input, runtime, cache or training invariant failed."""


def _need(condition, message):
    if not condition:
        raise PreparedTrainingError(message)


def _wire(value, maximum):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise PreparedTrainingError("bounded ordinary finite JSON required") from error
    _need(len(raw) <= maximum, "prepared result byte bound exceeded")
    return raw


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path,
          "canonical unaliased prepared source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= 131072, "bounded single-link prepared source required")
    raw = path.read_bytes()
    after = path.lstat()
    fields = lambda value: (value.st_dev, value.st_ino, value.st_size,
                           value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    _need(fields(before) == fields(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected,
          "prepared source bytes or physical identity changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, fields(after)


def _owners():
    root = None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor / "ipfs_datasets_py",
                          ancestor / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][1]).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical scope/session owner tree unavailable")
    loaded, observations = {}, {}
    for key, relative, pin in _SPECS:
        path = root / relative
        observation = _source(path, pin)
        module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path
              and _source(path, pin) == observation, "canonical prepared owner origin differs")
        loaded[key], observations[key] = module, observation
    return root, loaded, observations


@contextmanager
def _input_scope(original, weighted, fast, fast_source_fence):
    """The original weighted custody lifecycle, with qualified framed hashing.

    This is a private layer used only by _scope. Its canonical owners and the
    fast helper are bound by the enclosing source/origin fence. The inner exit
    and finally checks intentionally remain distinct, as in the v1 owner.
    """
    root, pins = weighted._sources()
    modules, captured, fingerprint, failure = {}, None, None, None

    def fence():
        fast_source_fence()
        _need(weighted._sources() == (root, pins), "source custody changed")
        for key, relative, _ in weighted._SPECS:
            if key in modules:
                _need(Path(modules[key].__file__).absolute() == root / relative,
                      "loaded owner origin changed")
        if fingerprint is not None:
            helper = modules["runtime"]
            _need(fast.fingerprint(captured, maximum=weighted.MAX_INPUT_BYTES, allow_bytes=True) == fingerprint
                  and fast.fingerprint(helper._copy(original, weighted.MAX_INPUT_BYTES, allow_bytes=True),
                                       maximum=weighted.MAX_INPUT_BYTES, allow_bytes=True) == fingerprint,
                  "original or captured input changed")

    try:
        for key, relative, _ in weighted._SPECS:
            if key is not None and key != "numerical":
                module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical public owner import required")
                modules[key] = module
        captured = modules["runtime"]._copy(original, weighted.MAX_INPUT_BYTES, allow_bytes=True)
        fast_source_fence()
        fingerprint = fast.fingerprint(captured, maximum=weighted.MAX_INPUT_BYTES, allow_bytes=True)
        fence()
        yield captured, modules, fence
        fence()
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, PreparedTrainingError):
            raise PreparedTrainingError(str(error)) from error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing fast input custody check also failed.")


@contextmanager
def _scope(original):
    """Pure bounded custody of caller/captured values and every original owner.

    Yields (captured, modules, fence), without model or optimizer construction.
    It does not enter either legacy _scope or replace any loaded owner function.
    Canonical source reads/imports remain part of this private context's work.
    """
    prepared_root, prepared_owners, prepared_observations = _owners()
    own_source = _source(_SELF_PATH, _SELF_SHA)
    scope_owner = prepared_owners["scope_training"]
    root, observed = scope_owner._sources()
    _need(root == prepared_root, "prepared and scope source roots differ")
    owners, scope_owners, failure = {}, None, None

    def outer_fence():
        _need(_source(_SELF_PATH, _SELF_SHA) == own_source, "fast custody consumer source changed")
        for key, relative, pin in _SPECS:
            module = prepared_owners[key]
            _need(_source(prepared_root / relative, pin) == prepared_observations[key]
                  and type(module.__file__) is str
                  and Path(module.__file__).absolute() == prepared_root / relative,
                  "fast custody dependency source/origin changed")
        _need(scope_owner._sources() == (root, observed), "scope training source custody changed")
        for key, relative, _ in scope_owner._SPECS:
            if key in owners:
                _need(Path(owners[key].__file__).absolute() == root / relative, "loaded owner origin changed")
        if scope_owners is not None:
            current = owners["scope"]._owners()
            _need(current[0] is scope_owners[0] and current[1] is scope_owners[1]
                  and current[2] == scope_owners[2], "scope dependency custody changed")

    try:
        for key, relative, _ in scope_owner._SPECS:
            module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical owner import required")
            owners[key] = module
        scope_owners = owners["scope"]._owners()
        fast = prepared_owners["fingerprint"]
        _need(fast.DEFAULT_MAXIMUM == owners["weighted"].MAX_INPUT_BYTES == 24 * 1024**2
              and fast.MAX_JSON_ITEMS == 12_000_000 and fast.MAX_JSON_DEPTH == 96,
              "qualified fast fingerprint input domain differs")

        def fast_source_fence():
            _, relative, pin = next(item for item in _SPECS if item[0] == "fingerprint")
            _need(_source(prepared_root / relative, pin) == prepared_observations["fingerprint"]
                  and type(fast.__file__) is str
                  and Path(fast.__file__).absolute() == prepared_root / relative,
                  "fast fingerprint source/origin changed")

        # Establish the new helper's source/origin before its first invocation.
        outer_fence()
        with _input_scope(original, owners["weighted"], fast, fast_source_fence) as (data, modules, original_fence):
            _need(scope_owners[1] is modules["tokens"]
                  and owners["scope"].POLICY == scope_owner.scope_policy()["policy"],
                  "scope and baseline token owner disagree")
            modules.update(owners)
            modules["scope_pins"] = scope_owners[2]

            def fence():
                original_fence()
                outer_fence()

            fence()
            yield data, modules, fence
            fence()
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, PreparedTrainingError):
            failure = PreparedTrainingError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer_fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing fast prepared scope custody check also failed.")


def prepare(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256, max_steps):
    """Validate once and restore exactly one private canonical model and Adam.

    ``max_steps`` is a plain positive integer within the unchanged owner's total
    2048-step limit. It is a caller-declared bound, not evidence that a long run
    has been qualified. A single advance returns at most four complete reports;
    the caller must enroll all calls and account for their durable retention.
    """
    _need(type(max_steps) is int and 1 <= max_steps <= 2048,
          "plain positive bounded session update count required")
    owner_root, owners, owner_observations = _owners()
    owner = owners["scope_training"]
    owner_observation = owner_observations["scope_training"]
    prepared_source = _source(_SELF_PATH, _SELF_SHA)
    original = {"checkpoint": checkpoint, "expected": expected_checkpoint_sha256,
                "expected_policy": expected_policy_sha256, "max_steps": max_steps}
    scope = _scope(original)
    entered = False
    state = {"status": "preparing", "busy": False, "stage": "checkpoint_validation",
             "model": None, "optimizer": None, "rows": None, "snapshot": None,
             "value": None, "checkpoint_sha256": None, "completed_updates": 0,
             "pid": os.getpid(), "thread": threading.get_ident(), "totals": {},
             "preparation_timing": [], "last_failure_stage": None,
             "accounting": {name: 0 for name in (
                 "model_constructions_entered", "model_constructions_completed",
                 "optimizer_constructions_entered", "optimizer_constructions_completed",
                 "model_forward_entered", "model_forward_completed",
                 "backward_entered", "backward_completed", "optimizer_step_entered",
                 "optimizer_step_completed", "full_state_exports")}}

    @contextmanager
    def span(category, destination):
        _need(category in _CATEGORIES, "closed prepared timing category required")
        state["stage"] = category
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            yield
        finally:
            interval = {"category": category, "wall_ns": time.perf_counter_ns() - wall,
                        "thread_cpu_ns": time.thread_time_ns() - cpu}
            destination.append(interval)
            total = state["totals"].setdefault(category,
                {"intervals": 0, "wall_ns": 0, "thread_cpu_ns": 0})
            total["intervals"] += 1
            total["wall_ns"] += interval["wall_ns"]
            total["thread_cpu_ns"] += interval["thread_cpu_ns"]

    def decorate(error):
        if isinstance(error, PreparedTrainingError):
            result = error
        else:
            result = PreparedTrainingError("prepared training failed during " + state["stage"]
                                           + " (" + type(error).__name__ + ")")
        result.accounting = deepcopy(state["accounting"])
        result.last_checkpoint_sha256 = state["checkpoint_sha256"]
        result.last_failure_stage = state["stage"]
        result.completed_updates = state["completed_updates"]
        return result

    try:
        with span("checkpoint_validation", state["preparation_timing"]):
            data, modules, input_fence = scope.__enter__()
            entered = True
            value, prepared = owner._validate(data["checkpoint"], data["expected"],
                                               data["expected_policy"], modules)
            weighted = modules["weighted"]
            _need(data["max_steps"] <= weighted.MAX_NEW_STEPS - value["progress"]["optimizer_steps"],
                  "session would exceed the unchanged scope checkpoint progress bound")
            state["value"], state["checkpoint_sha256"] = value, data["expected"]
        with span("runtime_fence", state["preparation_timing"]):
            numerical, torch, runtime = weighted._numeric(modules)
            _need(owner._wire(runtime) == owner._wire(value["runtime"]),
                  "live prepared training runtime differs")
            _need(torch.get_default_dtype() is torch.float32,
                  "default float32 runtime required before model allocation")
            _need(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
                  "ordinary grad-enabled prepared training required")
            rng = torch.get_rng_state().clone()

        def tensor_mark(tensor):
            _need(isinstance(tensor, torch.Tensor) and tensor.device.type == "cpu"
                  and tensor.layout is torch.strided and tensor.is_contiguous(),
                  "plain contiguous CPU prepared tensor required")
            raw = bytes(tensor.detach().contiguous().reshape(-1).view(torch.uint8).tolist())
            return (id(tensor), tensor.data_ptr(), tuple(tensor.shape), tuple(tensor.stride()),
                    tensor.dtype, tensor.requires_grad, tensor._version,
                    hashlib.sha256(raw).hexdigest())

        def numeric_mark():
            model, optimizer = state["model"], state["optimizer"]
            named = list(model.named_parameters())
            _need(type(optimizer) is torch.optim.Adam and len(optimizer.param_groups) == 1,
                  "one exact private Adam required")
            group = optimizer.param_groups[0]
            _need(list(dict(named)) == value["parameter_order"]
                  and len(group["params"]) == len(named)
                  and all(left is right for left, (_, right) in zip(group["params"], named))
                  and set(optimizer.state).issubset({tensor for _, tensor in named}),
                  "private parameter inventory or Adam membership changed")
            moments = []
            for name, tensor in named:
                fields = optimizer.state.get(tensor, {})
                _need(type(fields) is dict and set(fields) in (set(), {"step", "exp_avg", "exp_avg_sq"}),
                      "private closed named Adam state required")
                moments.append((name, tuple((key, tensor_mark(fields[key])) for key in sorted(fields))))
            return (tuple((name, tensor_mark(tensor)) for name, tensor in named),
                    tuple((name, tensor_mark(tensor)) for name, tensor in model.named_buffers()),
                    tuple((name, id(module), type(module), module.training,
                           id(type(module).forward)) for name, module in model.named_modules()),
                    tuple(moments), owner._wire(optimizer.defaults),
                    owner._wire({key: item for key, item in group.items() if key != "params"}))

        with span("restore", state["preparation_timing"]):
            state["accounting"]["model_constructions_entered"] += 1
            model = numerical._model({"dimension": 384},
                {"target_vocabulary": value["codec"]["vocabulary"]}, value["config"])
            state["model"] = model
            state["accounting"]["model_constructions_completed"] += 1
            templates = model.state_dict()
            _need(list(templates) == value["parameter_order"], "restored model order differs")
            model.load_state_dict({name: numerical._tensor(value["model_state"][name], template, name)
                                   for name, template in templates.items()}, strict=True)
            model.train()
            state["accounting"]["optimizer_constructions_entered"] += 1
            optimizer = numerical._optimizer(model, value["optimizer_config"])
            state["optimizer"] = optimizer
            state["accounting"]["optimizer_constructions_completed"] += 1
            for name, parameter in model.named_parameters():
                stored = value["optimizer_state"]["parameters"].get(name)
                if stored is not None:
                    optimizer.state[parameter] = {
                        "step": torch.tensor(float(stored["step"]), dtype=torch.float32, device="cpu"),
                        "exp_avg": numerical._tensor(stored["exp_avg"], parameter, name + ".exp_avg"),
                        "exp_avg_sq": numerical._tensor(stored["exp_avg_sq"], parameter,
                                                        name + ".exp_avg_sq", nonnegative=True)}
            weights, moments = weighted._actual(model, optimizer, value,
                value["progress"]["optimizer_steps"], modules, numerical, torch)
            state["accounting"]["full_state_exports"] += 1
            _need(weights == value["model_state"] and moments == value["optimizer_state"],
                  "prepared complete model/Adam restore is not exact")
            state["snapshot"] = numeric_mark()
        with span("tensor_cache_preparation", state["preparation_timing"]):
            rows = []
            for index in range(2):
                selected = dict(value, progress={"row_cursor": index})
                row = owner._row(selected, prepared, modules)
                _need(len(row["target_ids"]) == 47 and len(row["position_weights"]) == 46,
                      "closed complete two-row teacher-forcing geometry differs")
                vector = torch.tensor([row["conditioning"]], dtype=torch.float32, device="cpu")
                target = torch.tensor([row["target_ids"]], dtype=torch.long, device="cpu")
                labels = torch.tensor(row["target_ids"][1:], dtype=torch.long, device="cpu")
                position_weights = torch.tensor(row["position_weights"], dtype=torch.float32, device="cpu")
                weight_sum = position_weights.sum()
                _need(bool(torch.isfinite(vector).all()) and bool((labels != 0).all())
                      and bool(torch.isfinite(position_weights).all()) and bool((position_weights > 0).all())
                      and bool(torch.isfinite(weight_sum)) and float(weight_sum) > 0,
                      "complete finite positive cached row tensors required")
                _need(float(weight_sum) == 67.0 and row["singleton_positions"] == 39
                      and row["nontrivial_positions"] == 7,
                      "original baseline weight normalization and scope inventory required")
                allowed = torch.zeros((46, 537), dtype=torch.bool, device="cpu")
                for position, choices in enumerate(row["scope_allowed_token_ids"]):
                    _need(bool(choices) and row["target_ids"][position + 1] in choices,
                          "every scope set must contain the original target")
                    allowed[position, choices] = True
                _need(bool(allowed.any(dim=1).all()), "nonempty cached scope denominator required")
                tensors = (vector, target, labels, position_weights, weight_sum, allowed)
                rows.append({"metadata": row, "metadata_sha256": owner._digest(row),
                             "tensors": tensors, "marks": tuple(tensor_mark(t) for t in tensors)})
            state["rows"] = rows

        input_custody = {
            "schema": "legal-compact-prepared-input-custody/v2",
            "consumer_owner": deepcopy(prepared_source[0]),
            "fingerprint_owner": deepcopy(owner_observations["fingerprint"][0]),
            "original_prepared_mechanics_owner": deepcopy(owner_observations["original_prepared"][0]),
            "framing_reference": "bounded_runtime_copy_then_original_head_fingerprint/v1",
            "maximum_input_bytes": weighted.MAX_INPUT_BYTES,
            "bounded_original_copy_retained": True,
            "captured_and_original_fingerprints_retained": True,
            "per_update_guard_sites": 4,
            "nested_closing_guards_retained": True,
            "legacy_modules_rebound": False,
            "checkpoint_implementation_identity_rewritten": False,
        }
        preparation = {"schema": SCHEMA, "profile": PROFILE,
            "input_custody": deepcopy(input_custody),
            "prepared_owner": deepcopy(prepared_source[0]),
            "scope_training_owner": deepcopy(owner_observation[0]),
            "session_capsule_owner": deepcopy(owner_observations["session"][0]),
            "checkpoint_schema_unchanged": True, "source_only_staged_owner": False,
            "external_execution_report_must_pin_prepared_owner": True,
            "checkpoint_validation_count": 1, "complete_grammar_inventory_validation_count": 1,
            "model_restore_count": 1, "optimizer_construction_count": 1,
            "optimizer_history_restored": value["progress"]["optimizer_steps"] > 0,
            "cached_row_count": 2, "cached_weight_kernels": True, "cached_scope_masks": True,
            "objective_kind": value["objective_policy"]["objective_kind"],
            "baseline_weight_sum": 67.0, "scope_policy_sha256": value["scope_policy_sha256"],
            "baseline_and_scope_inventories_recomputed_at_entry": True,
            "old_checkpoint_schema_conversion": False,
            "max_steps": data["max_steps"], "max_steps_is_not_long_run_qualification": True,
            "max_steps_per_advance": MAX_ADVANCE_STEPS,
            "initial_checkpoint_sha256": data["expected"],
            "objective_policy_sha256": data["expected_policy"],
            "full_actual_state_export_and_immediate_parent_commitment_every_update": True,
            "grammar_validated_once_per_session": True, "durable_output_owned_by_caller": True,
            "semantic_or_native_authority": False}

        def guard(timing, *, state_check=True):
            _need(os.getpid() == state["pid"] and threading.get_ident() == state["thread"],
                  "prepared session is confined to its original process and thread")
            with span("source_input_fence", timing):
                _need(_source(_SELF_PATH, _SELF_SHA) == prepared_source,
                      "prepared consumer source changed")
                for key, relative, pin in _SPECS:
                    _need(_source(owner_root / relative, pin) == owner_observations[key]
                          and type(owners[key].__file__) is str
                          and Path(owners[key].__file__).absolute() == owner_root / relative,
                          "scope or session capsule owner source/origin changed")
                input_fence()
            with span("runtime_fence", timing):
                _need(owner._wire(modules["trainer"]._runtime(modules["head"],
                          {"modules": {"numerical": numerical}})) == owner._wire(runtime),
                      "runtime changed during prepared session")
                _need(torch.equal(rng, torch.get_rng_state()), "prepared session changed ambient CPU RNG")
                _need(torch.get_default_dtype() is torch.float32,
                      "default float32 runtime changed during prepared session")
                _need(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
                      "ordinary grad-enabled prepared training required")
            with span("state_cache_fence", timing):
                for cached in state["rows"]:
                    _need(owner._digest(cached["metadata"]) == cached["metadata_sha256"]
                          and tuple(tensor_mark(t) for t in cached["tensors"]) == cached["marks"],
                          "cached row metadata, tensor objects or exact bytes changed")
                if state_check:
                    _need(numeric_mark() == state["snapshot"],
                          "private model, named Adam, flags or exact tensor bytes changed")

        def timing_report():
            return {"schema": "legal-compact-scope-prepared-phase-timing/v2",
                "totals": deepcopy(state["totals"]), "wall_and_calling_thread_CPU_only": True,
                "listed_phase_intervals_are_sequential_nonoverlapping": True,
                "whole_operation_time_includes_unattributed_dispatch_and_result_copy": True,
                "native_driver_IO_and_durable_saves_are_external": True,
                "not_isolated_kernel_throughput": True}

        def summary():
            return {"schema": SCHEMA, "profile": PROFILE, "status": state["status"],
                "last_checkpoint_sha256": state["checkpoint_sha256"],
                "progress": deepcopy(state["value"]["progress"]),
                "completed_updates": state["completed_updates"],
                "remaining_updates": data["max_steps"] - state["completed_updates"],
                "last_failure_stage": state["last_failure_stage"],
                "preparation": deepcopy(preparation), "accounting": deepcopy(state["accounting"]),
                "accounting_scope": "entered/completed calls to canonical factories, model, backward and Adam",
                "GRU_calls_require_independent_caller_observation": True,
                "last_checkpoint_is_complete_not_a_partial_live_state": True,
                "last_checkpoint_durability_not_claimed": True, "timing": timing_report()}

        def gradients():
            result = {}
            for name, parameter in state["model"].named_parameters():
                gradient = parameter.grad
                _need(gradient is not None and gradient.dtype is torch.float32
                      and gradient.device.type == "cpu" and tuple(gradient.shape) == tuple(parameter.shape)
                      and bool(torch.isfinite(gradient).all()), "complete finite named gradients required")
                result[name] = gradient.detach().tolist()
            _need(list(result) == value["parameter_order"], "complete ordered gradient inventory differs")
            return result

        def step():
            timing = []
            guard(timing)
            current = state["value"]
            parent_hash = state["checkpoint_sha256"]
            cached = state["rows"][current["progress"]["row_cursor"]]
            row = cached["metadata"]
            vector, target, labels, position_weights, weight_sum, allowed = cached["tensors"]
            state["model"].train()
            state["optimizer"].zero_grad(set_to_none=True)
            with span("forward", timing):
                state["accounting"]["model_forward_entered"] += 1
                projected, logits = state["model"](vector, target[:, :-1])
                state["accounting"]["model_forward_completed"] += 1
                _need(tuple(projected.shape) == (1, 384) and tuple(logits.shape) == (1, 46, 537)
                      and logits.dtype is projected.dtype is torch.float32
                      and logits.device.type == projected.device.type == "cpu"
                      and logits.requires_grad and bool(torch.isfinite(logits).all())
                      and bool(torch.isfinite(projected).all()), "complete finite forward geometry differs")
            guard(timing)
            with span("objective", timing):
                # The two small kernels exactly mirror the pinned direct owner.
                # No reusable kernel is exposed there: invoking its public
                # objective would repeat whole checkpoint/grammar validation.
                flat = logits.reshape(-1, 537)
                conditional = row["objective_kind"] == "scope_conditional"
                if conditional:
                    per_position = torch.nn.functional.cross_entropy(
                        flat.masked_fill(~allowed, -torch.inf), labels, ignore_index=0, reduction="none")
                    with torch.no_grad():
                        full = torch.nn.functional.cross_entropy(flat, labels, ignore_index=0, reduction="none")
                else:
                    per_position = torch.nn.functional.cross_entropy(flat, labels, ignore_index=0, reduction="none")
                    full = per_position.detach()
                loss = (per_position * position_weights).sum() / weight_sum
                _need(tuple(loss.shape) == () and loss.requires_grad and bool(torch.isfinite(loss))
                      and bool(torch.isfinite(per_position).all()) and bool(torch.isfinite(full).all()),
                      "finite differentiable objective and diagnostics required")
                reduction = ("scope_masked_none_weighted_sum_divide_baseline_weight_sum" if conditional
                             else "full537_none_weighted_sum_divide_weight_sum")
                # This is the direct objective's observation vocabulary, using
                # the actual cached row and actual forward logits. It reports
                # work inside the objective only, not the enclosing update.
                objective_report = dict(
                    schema="legal-compact-scope-objective-observation/v1", checkpoint_sha256=parent_hash,
                    objective_policy_sha256=row["policy_sha256"], objective_kind=row["objective_kind"],
                    row_id=row["id"], row_index=row["row_index"], inventory_sha256=row["inventory_sha256"],
                    baseline_inventory_sha256=row["baseline_inventory_sha256"],
                    scope_inventory_sha256=row["scope_inventory_sha256"],
                    scope_policy_sha256=current["scope_policy_sha256"], target_ids=list(row["target_ids"]),
                    label_ids=list(row["target_ids"][1:]), position_weights=list(row["position_weights"]),
                    weight_sum=math.fsum(row["position_weights"]), supervised_positions=len(row["position_weights"]),
                    scope_allowed_token_ids=deepcopy(row["scope_allowed_token_ids"]),
                    baseline_decision_kinds=list(row["baseline_decision_kinds"]),
                    singleton_positions=row["singleton_positions"], nontrivial_positions=row["nontrivial_positions"],
                    per_position_losses=per_position.detach().tolist(), weighted_loss=float(loss.detach()),
                    full537_per_position_losses=full.detach().tolist(),
                    full537_weighted_loss=float(((full * position_weights).sum() / weight_sum).detach()),
                    reduction=reduction, full537_logits_observed=True, full537_vocabulary=not conditional,
                    conditional_allowed_set_loss=conditional, singleton_zero_loss_is_not_accuracy=True,
                    full537_and_conditional_losses_not_comparable_as_accuracy=True,
                    forward_performed=False, backward_performed=False, optimizer_update_performed=False,
                    teacher_forcing=True, authority=dict(owner.AUTHORITY))
            with span("backward", timing):
                state["accounting"]["backward_entered"] += 1
                loss.backward()
                state["accounting"]["backward_completed"] += 1
            with span("gradient_capture_clip", timing):
                preclip = gradients()
                norm = torch.nn.utils.clip_grad_norm_(list(state["model"].parameters()),
                                                      5.0, error_if_nonfinite=True)
                postclip = gradients()
            guard(timing)
            with span("Adam", timing):
                state["accounting"]["optimizer_step_entered"] += 1
                state["optimizer"].step()
                state["accounting"]["optimizer_step_completed"] += 1
            completed = current["progress"]["optimizer_steps"] + 1
            progress = {"optimizer_steps": completed, "epochs_completed": completed // 2,
                        "row_cursor": completed % 2}
            with span("actual_state_export_validation", timing):
                weights, moments = weighted._actual(state["model"], state["optimizer"], current,
                    completed, modules, numerical, torch)
                state["accounting"]["full_state_exports"] += 1
            with span("lineage_pack", timing):
                # Exact new-schema direct pack construction. _actual above checks
                # all changed model/named-Adam/progress state; unchanged metadata
                # is private and copied from the once fully validated checkpoint.
                successor = deepcopy(current)
                successor.update(model_state=weights, weights_sha256=owner._digest(weights),
                    optimizer_state=moments, optimizer_state_sha256=owner._digest(moments),
                    progress=progress, parent_checkpoint_sha256=parent_hash,
                    initial_checkpoint_sha256=parent_hash if current["progress"]["optimizer_steps"] == 0
                        else current["initial_checkpoint_sha256"])
                checkpoint_raw = owner._wire(successor)
                _need(len(checkpoint_raw) <= owner.MAX_CHECKPOINT_BYTES,
                      "complete prepared checkpoint exceeds original byte limit")
                successor_hash = hashlib.sha256(checkpoint_raw).hexdigest()
                state["value"], state["checkpoint_sha256"] = successor, successor_hash
                state["completed_updates"] += 1
                state["snapshot"] = numeric_mark()
            guard(timing)
            with span("report_export", timing):
                report = {"schema": STEP_SCHEMA, "before_checkpoint_sha256": parent_hash,
                    "after_checkpoint_sha256": successor_hash, "checkpoint_sha256": successor_hash,
                    "checkpoint": deepcopy(successor), "checkpoint_progress": deepcopy(progress),
                    "row_id": row["id"], "row_index": row["row_index"],
                    "target_ids": list(row["target_ids"]), "label_ids": list(row["target_ids"][1:]),
                    "position_weights": list(row["position_weights"]),
                    "weight_sum": math.fsum(row["position_weights"]),
                    "scope_allowed_token_ids": deepcopy(row["scope_allowed_token_ids"]),
                    "inventory_sha256": row["inventory_sha256"],
                    "baseline_inventory_sha256": row["baseline_inventory_sha256"],
                    "scope_inventory_sha256": row["scope_inventory_sha256"],
                    "scope_policy_sha256": current["scope_policy_sha256"],
                    "objective_kind": row["objective_kind"],
                    "objective_report": objective_report,
                    "objective_policy_sha256": row["policy_sha256"], "reduction": reduction,
                    "full_sequence_logits": logits.detach().tolist(), "loss": float(loss.detach()),
                    "preclip_gradients": preclip, "postclip_gradients": postclip,
                    "preclip_global_L2_Torch": float(norm), "global_clip_max_norm": 5.0,
                    "model_state_sha256": successor["weights_sha256"],
                    "optimizer_state_sha256": successor["optimizer_state_sha256"],
                    "training_exposed": True, "teacher_forced": True,
                    "full537_logits_observed": True, "full537_vocabulary": not conditional,
                    "conditional_allowed_set_loss": conditional,
                    "singleton_zero_loss_is_not_accuracy": True,
                    "full537_and_conditional_losses_not_comparable_as_accuracy": True,
                    "prepared_owner": deepcopy(prepared_source[0]),
                    "input_custody": deepcopy(input_custody),
                    "scope_training_owner": deepcopy(owner_observation[0]),
                    "session_capsule_owner": deepcopy(owner_observations["session"][0]),
                    "checkpoint_constructed_with_original_actual_and_pack_fields": True,
                    "new_checkpoint_schema_preserved": True, "old_checkpoint_schema_conversion": False,
                    "checkpoint_durable": False, "source_encoder_authenticated": False,
                    "training_mask": 0, "evaluation_gold_mask": 0,
                    "authority": deepcopy(owner.AUTHORITY)}
                for field in ("full_sequence_logits", "preclip_gradients", "postclip_gradients"):
                    report[field + "_sha256"] = owner._digest(report[field])
                _wire(report, MAX_STEP_REPORT_BYTES)
            report["timing"] = {"intervals": timing,
                "wall_and_calling_thread_CPU_only": True, "durable_IO_external": True}
            _wire(report, MAX_STEP_REPORT_BYTES)
            return report

        def dispatch(operation, argument):
            _need(os.getpid() == state["pid"] and threading.get_ident() == state["thread"],
                  "prepared session is confined to its original process and thread")
            _need(not state["busy"], "prepared session operations cannot overlap or reenter")
            if operation == "inspect":
                return summary()
            if operation == "close" and state["status"] == "closed":
                return summary()
            _need(state["status"] != "closed", "prepared session lifetime ended")
            if operation == "advance":
                _need(state["status"] == "ready", "failed prepared session cannot advance")
                _need(type(argument) is int and 1 <= argument <= MAX_ADVANCE_STEPS
                      and argument <= data["max_steps"] - state["completed_updates"],
                      "plain bounded advance count within declared remaining work required")
            _need(operation in ("advance", "checkpoint", "close"), "unknown prepared operation")
            state["busy"] = True
            try:
                if operation == "close":
                    prior = state["status"]
                    closing_errors = []
                    try:
                        try:
                            guard([])
                        except BaseException as error:
                            closing_errors.append(error)
                        try:
                            scope.__exit__(None, None, None)
                        except BaseException as error:
                            closing_errors.append(error)
                    finally:
                        state["model"] = state["optimizer"] = state["rows"] = state["snapshot"] = None
                        state["status"] = "closed"
                    answer = summary()
                    answer["status_before_close"] = prior
                    answer["private_references_released"] = True
                    answer["closing_guard_passed"] = not closing_errors
                    answer["closing_error_types"] = [type(error).__name__ for error in closing_errors]
                    if closing_errors and prior != "poisoned":
                        raise closing_errors[0]
                    return answer
                if operation == "checkpoint":
                    # A poisoned session can yield its last complete recovery
                    # checkpoint only after source/input/runtime/cache checks;
                    # its partially changed live state is never serialized.
                    guard([], state_check=state["status"] == "ready")
                    return deepcopy(state["value"])
                reports = [step() for _ in range(argument)]
                answer = {"schema": ADVANCE_SCHEMA, "reports": reports,
                    "checkpoint": deepcopy(state["value"]),
                    "checkpoint_sha256": state["checkpoint_sha256"],
                    "preparation": deepcopy(preparation), "accounting": deepcopy(state["accounting"]),
                    "timing": timing_report(), "durable_outputs_written": False}
                _wire(answer, MAX_ADVANCE_BYTES)
                return answer
            except BaseException as error:
                state["last_failure_stage"] = state["stage"]
                if operation != "close":
                    state["status"] = "poisoned"
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    BaseException.add_note(error, "Prepared session work entered/completed counters are retained by inspect().")
                    raise
                raise decorate(error) from error
            finally:
                state["busy"] = False

        state["status"] = "ready"
        guard(state["preparation_timing"])
        preparation["timing"] = deepcopy(state["preparation_timing"])
        return owners["session"].PreparedTrainingSession(dispatch)
    except BaseException as error:
        state["last_failure_stage"] = state["stage"]
        state["status"] = "poisoned"
        state["model"] = state["optimizer"] = state["rows"] = state["snapshot"] = None
        if entered:
            try:
                scope.__exit__(type(error), error, error.__traceback__)
            except BaseException:
                BaseException.add_note(error, "Closing a failed prepared construction also failed.")
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise decorate(error) from error


__all__ = ["PreparedTrainingError", "prepare"]
