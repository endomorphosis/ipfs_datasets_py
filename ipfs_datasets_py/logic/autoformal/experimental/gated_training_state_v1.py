"""Strict matched fresh-Adam development state for compact384 engineering arms.

The qualified zero-gate migration remains unchanged. This separate profile
supports changed model weights and actual named Adam moments. It accepts only
the exact retained parent and initial migration, never their historical Adam
state as a resume source. No call trains a model: the admitted caller owns the
declared loss, clip, backward, step, finite cohort, custody and closeout.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('gated_training_state')["sha256"]

SCHEMA = "legal-gated-matched-training-checkpoint/v1"
PROFILE = "authored-compact384-matched-fresh-adam-development/v1"
PARENT_SHA = "a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b"
MIGRATION_SHA = "c17a875dbafe7018435978ce133692c62718e118936657f27ac17bac0686593a"
CANDIDATE_SHA = "dd91a47e8c116ea2cb6daa60716f0c452b82585df78d4c88756a1147eb55ba00"
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_POPULATION_BYTES = 2 * 1024**2
MAX_NEW_STEPS = 2048
ARMS = ("h0_only", "gated_per_step")
POPULATION_AUTHORITY = {name: False for name in (
    "source_encoder_authenticated", "statutory_accuracy", "heldout_accuracy", "graph_admission", "Lean_admission")}
AUTHORITY = {**POPULATION_AUTHORITY, "production_ready": False, "native_admission": False}
ADAM_DEFAULTS = {"lr": 0.001, "betas": [0.9, 0.999], "eps": 1e-8,
    "weight_decay": 0, "amsgrad": False, "maximize": False, "foreach": False,
    "capturable": False, "differentiable": False, "fused": None, "decoupled_weight_decay": False}
TRAINING_POLICY = {"objective": "compact_token_cross_entropy", "ignore_index": 0,
    "gradient_clip_l2": 5.0, "batch_size": 1, "row_order": "population_order_repeated", "curriculum": "none"}
BODY_SHAPES = {
    "projection_down.weight": (4, 384), "projection_down.bias": (4,),
    "projection_up.weight": (384, 4), "projection_up.bias": (384,),
    "condition.weight": (8, 384), "condition.bias": (8,), "target_embedding.weight": (537, 8),
    "decoder.weight_ih_l0": (24, 8), "decoder.weight_hh_l0": (24, 8),
    "decoder.bias_ih_l0": (24,), "decoder.bias_hh_l0": (24,),
    "output.weight": (537, 8), "output.bias": (537,),
}
GATED_SHAPES = {"gate": (), **{"body." + name: shape for name, shape in BODY_SHAPES.items()},
                "source_to_embedding.weight": (8, 384)}
FIELDS = {"schema", "profile", "arm", "architecture", "input_dimension", "vocabulary_size",
    "config", "codec", "codec_sha256", "runtime", "runtime_sha256", "initial_migration",
    "initial_migration_sha256", "parent_checkpoint_sha256", "historical_parent_progress",
    "population", "population_sha256", "parameter_order", "model_state", "weights_sha256",
    "initial_weights_sha256", "optimizer_policy", "training_policy", "optimizer_state",
    "optimizer_state_sha256", "optimizer_history_origin", "progress", "initial_checkpoint_sha256",
    "parent_training_checkpoint_sha256", "implementation", "training_mask", "evaluation_gold_mask", "authority"}
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class TrainingStateError(ValueError):
    """Closed checkpoint, actual optimizer, lineage or runtime contract failed."""


def _need(ok, message):
    if not ok:
        raise TrainingStateError(message)


def _file_sha(path):
    path = Path(path).absolute()
    _need(path.resolve(strict=True) == path and 0 < path.stat().st_size <= 1024**2,
          "bounded unaliased source required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


_SELF_SHA = _file_sha(__file__)


def _candidate():
    from . import gated_conditioning_v1 as module
    _bridge.require_module("gated_conditioning", module)
    _need(_file_sha(__file__) == _SELF_SHA, "training-state source changed since checked loading")
    return module


def _implementation():
    candidate = _candidate()
    return {"training_state_sha256": _SELF_SHA,
            "gated_candidate_sha256": _bridge.source_reference("gated_conditioning")["sha256"],
            "canonical_owners": candidate._sources(),
            "source_profile_bridge_sha256": _bridge.implementation_sha256()}


def _copy(value, maximum=MAX_CHECKPOINT_BYTES):
    # Reuse the qualified bounded ordinary-container parser, then enforce this
    # profile's smaller complete transport envelope. It imports no Torch.
    candidate = _candidate()
    try:
        result = candidate._copy(value)
    except candidate.GatedConditioningError as error:
        raise TrainingStateError("bounded ordinary finite checkpoint input required") from error
    _wire(result, maximum)
    return result


def _wire(value, maximum=MAX_CHECKPOINT_BYTES):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise TrainingStateError("bounded ordinary finite UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON envelope exceeded")
    return raw


def checkpoint_sha256(value):
    return hashlib.sha256(_wire(_copy(value))).hexdigest()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value, label):
    _need(type(value) is str and _HEX.fullmatch(value) is not None, "exact SHA256 required: " + label)


def _shapes(arm):
    _need(type(arm) is str and arm in ARMS, "explicit matched arm required")
    return BODY_SHAPES if arm == "h0_only" else GATED_SHAPES


def _tensor(value, shape, *, nonnegative=False):
    if shape:
        _need(type(value) is list and len(value) == shape[0], "complete tensor shape differs")
        for child in value:
            _tensor(child, shape[1:], nonnegative=nonnegative)
    else:
        _need(type(value) is float and math.isfinite(value) and (not nonnegative or value >= 0),
              "finite valid float32 scalar required")
        try:
            rounded = struct.unpack("!f", struct.pack("!f", value))[0]
        except (OverflowError, struct.error) as error:
            raise TrainingStateError("float32 tensor overflow") from error
        _need(value.hex() == rounded.hex(), "exact exported float32 scalar required")


def _migration(value):
    migration = _copy(value)
    _need(_digest(migration) == MIGRATION_SHA, "exact qualified c17 initial migration required")
    candidate = _candidate()
    candidate.inspect_checkpoint(migration)  # pure contract; no model/Adam
    parent = migration["parent_checkpoint"]
    _need(_digest(parent) == PARENT_SHA and migration["parent_checkpoint_sha256"] == PARENT_SHA
          and parent["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0},
          "exact a98 parent with historical two updates required")
    return migration


def _population(offered, migration):
    population = _copy(offered, MAX_POPULATION_BYTES)
    _need(type(population) is dict and set(population) == {"schema", "training_exposed", "authority", "rows"}
          and population["schema"] == "legal-gated-training-population/v1"
          and population["training_exposed"] is True and population["authority"] == POPULATION_AUTHORITY
          and all(flag is False for flag in population["authority"].values())
          and type(population["rows"]) is list and len(population["rows"]) == 2,
          "complete exposed two-row population required")
    parent = migration["parent_checkpoint"]
    commitments = json.loads(parent["population_raw_utf8"])["rows"]
    head = _candidate()._owners()["head"]
    owners = head._owners(numeric=False)
    try:
        tokens = owners["modules"]["tokens"]
        for row, bound in zip(population["rows"], commitments):
            _need(type(row) is dict and set(row) == {"id", "source_group", "source_sha256", "conditioning",
                "conditioning_sha256", "context_utf8", "context_sha256", "target_utf8", "target_sha256", "target_ids"},
                "closed exact training row required")
            _need(all(row[key] == bound[key] for key in ("id", "source_group", "source_sha256",
                "conditioning_sha256", "context_sha256", "target_sha256")), "original population occurrence differs")
            vector = row["conditioning"]
            _need(type(vector) is list and len(vector) == 384 and all(type(x) is float and math.isfinite(x)
                and abs(x) <= 1e8 for x in vector) and _digest(vector) == row["conditioning_sha256"],
                "exact retained384 vector required")
            for key, maximum in (("context", 524288), ("target", 16384)):
                text = row[key + "_utf8"]
                _need(type(text) is str and 0 < len(text.encode("utf-8")) <= maximum
                    and hashlib.sha256(text.encode("utf-8")).hexdigest() == row[key + "_sha256"],
                    "exact source-bound context/target bytes required")
            ids = row["target_ids"]
            _need(type(ids) is list and 3 <= len(ids) <= 512 and all(type(x) is int for x in ids)
                  and ids[0] == 1 and ids[-1] == 2, "complete public target IDs required")
            encoded = tokens.encode_compact_content_tokens_v1(row["target_utf8"].encode(), row["context_utf8"].encode(),
                expected_content_sha256=row["target_sha256"], expected_context_sha256=row["context_sha256"],
                codec=migration["codec"], expected_codec_sha256=migration["codec_sha256"])
            _need(ids == encoded["target_ids"], "public codec target tokenization differs")
    finally:
        head._closing(owners)
    return population


def _progress(value):
    _need(type(value) is dict and set(value) == {"optimizer_steps", "epochs_completed", "row_cursor"}
          and all(type(x) is int for x in value.values())
          and 0 <= value["optimizer_steps"] <= MAX_NEW_STEPS
          and value["epochs_completed"] == value["optimizer_steps"] // 2
          and value["row_cursor"] == value["optimizer_steps"] % 2, "exact bounded new-step progress required")
    return value["optimizer_steps"]


def _validate(checkpoint):
    value = _copy(checkpoint)
    _need(type(value) is dict and set(value) == FIELDS and value["schema"] == SCHEMA and value["profile"] == PROFILE,
          "closed matched training profile required")
    shapes = _shapes(value["arm"])
    migration = _migration(value["initial_migration"])
    parent = migration["parent_checkpoint"]
    population = _population(value["population"], migration)
    architecture = "inherited-joint-gru-h0-only/v1" if value["arm"] == "h0_only" else migration["architecture"]
    _need(value["architecture"] == architecture and type(value["input_dimension"]) is int
          and value["input_dimension"] == 384 and type(value["vocabulary_size"]) is int and value["vocabulary_size"] == 537
          and _wire(value["config"]) == _wire(parent["config"]) and _wire(value["codec"]) == _wire(migration["codec"])
          and value["codec_sha256"] == migration["codec_sha256"] and _wire(value["runtime"]) == _wire(parent["runtime"])
          and value["runtime_sha256"] == _digest(value["runtime"])
          and value["initial_migration_sha256"] == MIGRATION_SHA and value["parent_checkpoint_sha256"] == PARENT_SHA
          and _wire(value["historical_parent_progress"]) == _wire(parent["progress"])
          and value["population_sha256"] == _digest(population),
          "exact architecture/codec/runtime/parent/population identity required")
    _need(_wire(value["optimizer_policy"]) == _wire({"name": "Adam", "defaults": ADAM_DEFAULTS})
          and _wire(value["training_policy"]) == _wire(TRAINING_POLICY)
          and value["optimizer_history_origin"] == "fresh_for_new_architecture_no_parent_optimizer_inheritance"
          and _bridge.compatible_implementation(value["implementation"], _implementation()), "exact fresh policy/source implementation required")
    state = value["model_state"]
    _need(type(state) is dict and set(state) == set(shapes) and value["parameter_order"] == list(shapes),
          "exact named parameter inventory/order required")
    for name, shape in shapes.items():
        _tensor(state[name], shape)
    _need(value["weights_sha256"] == _digest(state), "current model weights digest differs")
    initial_state = parent["model_state"] if value["arm"] == "h0_only" else migration["model_state"]
    _need(value["initial_weights_sha256"] == _digest(initial_state), "initial model-state identity differs")
    steps = _progress(value["progress"])
    optimizer = value["optimizer_state"]
    _need(type(optimizer) is dict and set(optimizer) == {"schema", "parameters"}
          and optimizer["schema"] == "named-adam-state/v1" and type(optimizer["parameters"]) is dict
          and set(optimizer["parameters"]) == (set(shapes) if steps else set())
          and value["optimizer_state_sha256"] == _digest(optimizer), "exact named Adam moment inventory required")
    for name, moments in optimizer["parameters"].items():
        _need(type(moments) is dict and set(moments) == {"step", "exp_avg", "exp_avg_sq"}
              and type(moments["step"]) is int and moments["step"] == steps,
              "every parameter needs its actual matching Adam step, including zero-gradient parameters")
        _tensor(moments["exp_avg"], shapes[name])
        _tensor(moments["exp_avg_sq"], shapes[name], nonnegative=True)
    if not steps:
        _need(state == initial_state and value["initial_checkpoint_sha256"] is None
              and value["parent_training_checkpoint_sha256"] is None, "zero-step initial state must be exact and fresh")
    else:
        _sha(value["initial_checkpoint_sha256"], "initial training checkpoint")
        _sha(value["parent_training_checkpoint_sha256"], "immediate training parent")
        initial = deepcopy(value)
        empty = {"schema": "named-adam-state/v1", "parameters": {}}
        initial.update(model_state=deepcopy(initial_state), weights_sha256=_digest(initial_state),
            optimizer_state=empty, optimizer_state_sha256=_digest(empty),
            progress={"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
            initial_checkpoint_sha256=None, parent_training_checkpoint_sha256=None)
        initial_sha = _digest(initial)
        _need(value["initial_checkpoint_sha256"] == initial_sha,
              "initial checkpoint identity differs from deterministic fresh zero-step state")
        if steps == 1:
            _need(value["parent_training_checkpoint_sha256"] == initial_sha,
                  "first update must bind its exact zero-step parent")
    _need(value["authority"] == AUTHORITY and all(flag is False for flag in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0,
          "engineering state grants no semantic eligibility")
    return value


def inspect(checkpoint):
    """Pure source/shape/lineage inspection; no model or optimizer allocation."""
    value = _validate(checkpoint)
    return {"schema": SCHEMA, "profile": PROFILE, "arm": value["arm"],
        "checkpoint_sha256": _digest(value), "weights_sha256": value["weights_sha256"],
        "optimizer_state_sha256": value["optimizer_state_sha256"], "progress": deepcopy(value["progress"]),
        "parameter_order": list(value["parameter_order"]), "parameter_count": 16101 if value["arm"] == "h0_only" else 19174,
        "runtime_verified": False, "optimizer_constructed": False, "historical_parent_steps": 2,
        "new_optimizer_steps": value["progress"]["optimizer_steps"],
        "initial_checkpoint_identity_derived": True,
        "immediate_parent_verified_from_zero_state": value["progress"]["optimizer_steps"] <= 1,
        "later_immediate_parent_is_retained_commitment_not_replay_verified": value["progress"]["optimizer_steps"] > 1,
        "authority": dict(AUTHORITY)}


def create(parent, migration, arm, population):
    """Create a pure zero-new-step checkpoint with empty fresh Adam state."""
    _shapes(arm)
    migration = _migration(migration)
    _need(checkpoint_sha256(parent) == PARENT_SHA and parent == migration["parent_checkpoint"],
          "offered original parent differs from the migration parent")
    population = _population(population, migration)
    inherited = migration["parent_checkpoint"]
    initial = deepcopy(inherited["model_state"] if arm == "h0_only" else migration["model_state"])
    optimizer = {"schema": "named-adam-state/v1", "parameters": {}}
    value = {"schema": SCHEMA, "profile": PROFILE, "arm": arm,
        "architecture": "inherited-joint-gru-h0-only/v1" if arm == "h0_only" else migration["architecture"],
        "input_dimension": 384, "vocabulary_size": 537, "config": deepcopy(inherited["config"]),
        "codec": deepcopy(migration["codec"]), "codec_sha256": migration["codec_sha256"],
        "runtime": deepcopy(inherited["runtime"]), "runtime_sha256": _digest(inherited["runtime"]),
        "initial_migration": migration, "initial_migration_sha256": MIGRATION_SHA, "parent_checkpoint_sha256": PARENT_SHA,
        "historical_parent_progress": deepcopy(inherited["progress"]), "population": population,
        "population_sha256": _digest(population), "parameter_order": list(_shapes(arm)), "model_state": initial,
        "weights_sha256": _digest(initial), "initial_weights_sha256": _digest(initial),
        "optimizer_policy": {"name": "Adam", "defaults": deepcopy(ADAM_DEFAULTS)},
        "training_policy": dict(TRAINING_POLICY), "optimizer_state": optimizer, "optimizer_state_sha256": _digest(optimizer),
        "optimizer_history_origin": "fresh_for_new_architecture_no_parent_optimizer_inheritance",
        "progress": {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
        "initial_checkpoint_sha256": None, "parent_training_checkpoint_sha256": None,
        "implementation": _implementation(), "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(AUTHORITY)}
    return _validate(value)


def _numeric():
    candidate = _candidate()
    numerical = candidate._owners(numerical=True)["numerical"]
    return candidate, numerical, numerical._torch()


def _policy(model, optimizer, torch):
    _need(type(optimizer) is torch.optim.Adam and len(optimizer.param_groups) == 1, "one exact Adam optimizer required")
    expected = dict(ADAM_DEFAULTS)
    defaults = dict(optimizer.defaults)
    defaults["betas"] = list(defaults["betas"])
    _need(defaults == expected, "actual Adam defaults differ")
    group = optimizer.param_groups[0]
    _need(set(group) == set(expected) | {"params"}, "closed actual Adam parameter group required")
    actual = {name: list(value) if name == "betas" else value for name, value in group.items() if name != "params"}
    parameters = list(model.parameters())
    _need(actual == expected and len(group["params"]) == len(parameters)
          and all(a is b for a, b in zip(group["params"], parameters)), "actual Adam values/named order differ")
    # This canonical helper only inspects an already real Adam. It constructs
    # no optimizer and preserves the reference trainer's clipping/loss policy.
    trainer = _candidate()._owners()["trainer"]
    observed = trainer._optimizer_policy(optimizer, 0.001)
    _need(observed == {"name": "Adam", "defaults": expected, "gradient_clip_l2": 5.0,
        "batch_size": 1, "row_order": "population_order_repeated", "objective": "compact_token_cross_entropy"},
        "canonical trainer's actual optimizer policy differs")


def _export(model, optimizer, arm, steps, torch):
    shapes = _shapes(arm)
    named = dict(model.named_parameters())
    tensors = model.state_dict()
    _need(list(named) == list(tensors) == list(shapes), "actual complete model/parameter order differs")
    _policy(model, optimizer, torch)
    for name, parameter in named.items():
        _need(list(parameter.shape) == list(shapes[name]) and parameter.device.type == "cpu"
              and parameter.dtype is torch.float32 and parameter.requires_grad is True
              and bool(torch.isfinite(parameter).all()), "actual parameter geometry/flags/finiteness differs")
    weights = {name: tensor.detach().tolist() for name, tensor in tensors.items()}
    _need(set(optimizer.state) == (set(named.values()) if steps else set()),
          "actual Adam state must include exactly all progressed parameters")
    moments = {}
    for name, parameter in named.items():
        if not steps:
            continue
        item = optimizer.state[parameter]
        _need(type(item) is dict and set(item) == {"step", "exp_avg", "exp_avg_sq"}, "closed actual Adam state required")
        step = item["step"]
        _need(isinstance(step, torch.Tensor) and step.device.type == "cpu" and step.dtype is torch.float32
              and tuple(step.shape) == () and bool(torch.isfinite(step)) and float(step) == steps,
              "actual Adam scalar step differs")
        for key in ("exp_avg", "exp_avg_sq"):
            tensor = item[key]
            _need(isinstance(tensor, torch.Tensor) and tuple(tensor.shape) == tuple(parameter.shape)
                  and tensor.device.type == "cpu" and tensor.dtype is torch.float32
                  and bool(torch.isfinite(tensor).all()) and tensor.requires_grad is False
                  and (key != "exp_avg_sq" or bool((tensor >= 0).all())), "actual Adam moment tensor differs")
        moments[name] = {"step": steps, "exp_avg": item["exp_avg"].detach().tolist(),
                         "exp_avg_sq": item["exp_avg_sq"].detach().tolist()}
    return weights, {"schema": "named-adam-state/v1", "parameters": moments}


def restore(checkpoint):
    """Restore one strict model and fresh/new-profile Adam; never old Adam."""
    before = checkpoint_sha256(checkpoint)
    value = _validate(checkpoint)
    candidate, numerical, torch = _numeric()
    runtime = candidate.runtime_metadata()
    _need(runtime == value["runtime"], "live CPU runtime differs from the fixed parent")
    rng = torch.get_rng_state().clone()
    try:
        wrapped = candidate.restore(value["initial_migration"])
        model = wrapped.body if value["arm"] == "h0_only" else wrapped
        templates = model.state_dict()
        _need(list(templates) == value["parameter_order"], "restored arm parameter names differ")
        model.load_state_dict({name: numerical._tensor(value["model_state"][name], template, name)
                               for name, template in templates.items()}, strict=True)
        model.eval()
        options = deepcopy(ADAM_DEFAULTS); options["betas"] = tuple(options["betas"])
        optimizer = torch.optim.Adam(model.parameters(), **options)
        for name, parameter in model.named_parameters():
            saved = value["optimizer_state"]["parameters"].get(name)
            if saved is not None:
                optimizer.state[parameter] = {
                    "step": torch.tensor(float(saved["step"]), dtype=torch.float32, device="cpu"),
                    "exp_avg": numerical._tensor(saved["exp_avg"], parameter, name + " exp_avg"),
                    "exp_avg_sq": numerical._tensor(saved["exp_avg_sq"], parameter, name + " exp_avg_sq", nonnegative=True)}
        weights, moments = _export(model, optimizer, value["arm"], value["progress"]["optimizer_steps"], torch)
        _need(weights == value["model_state"] and moments == value["optimizer_state"], "model/Adam restore is not exact")
        _need(candidate.runtime_metadata() == runtime and checkpoint_sha256(checkpoint) == before,
              "runtime or caller checkpoint changed during restore")
        return model, optimizer
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "model/Adam restore changed ambient CPU RNG")


def _require_current_producer(implementation):
    # The legacy profile reconstructs its initial checkpoint digest from its
    # original producer recipe. Replacing that recipe would sever lineage;
    # retaining it for new updates would falsely name the historical producer.
    _need(_wire(implementation) == _wire(_implementation()),
          "legacy producer requires a separately versioned continuation before pack")


def pack(model, optimizer, previousCP, progress):
    """Export exactly one actual completed update, including all real moments."""
    before = checkpoint_sha256(previousCP)
    value = _validate(previousCP)
    _require_current_producer(value["implementation"])
    progress = _copy(progress)
    steps = _progress(progress)
    _need(steps == value["progress"]["optimizer_steps"] + 1, "pack must advance exactly one actual update")
    candidate, _, torch = _numeric()
    runtime = candidate.runtime_metadata()
    _need(runtime == value["runtime"], "packing runtime differs")
    rng = torch.get_rng_state().clone()
    weights, moments = _export(model, optimizer, value["arm"], steps, torch)
    result = deepcopy(value)
    result.update(model_state=weights, weights_sha256=_digest(weights), optimizer_state=moments,
        optimizer_state_sha256=_digest(moments), progress=progress, parent_training_checkpoint_sha256=before,
        initial_checkpoint_sha256=before if value["progress"]["optimizer_steps"] == 0 else value["initial_checkpoint_sha256"])
    result = _validate(result)
    _need(checkpoint_sha256(previousCP) == before and candidate.runtime_metadata() == runtime
          and torch.equal(rng, torch.get_rng_state()), "packing mutated source/runtime/RNG or caller checkpoint")
    return result


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('gated_training_state', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('gated_training_state')
