"""Explicit h0-only compact384 weighted-CE development state.

The canonical numerical owner still constructs the model and Adam. This owner
adds a closed 1:1 or 1:4 forced/choice objective and its checkpoint lineage; it
does not execute a forward, backward, optimizer step, or generation. The caller
owns admission, finite work accounting, the training loop, and durable outputs.
Public grammar inventories are recomputed from complete bound targets rather
than accepted as caller-authored labels. No legal/source authority is granted.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-weighted-training-checkpoint/v1"
PROFILE = "authored-h0-only-compact384-fixed537-weighted-development/v1"
POLICY_SCHEMA = "legal-compact-forced-choice-full537-objective/v1"
ARCHITECTURE = "inherited-joint-gru-h0-only/v1"
DONOR_SHA256 = "a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b"
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
MAX_NEW_STEPS = 2048
CONFIG = {"hidden_size": 8, "projection_width": 4, "seed": 1729, "token_embedding_dim": 8}
UPDATE_POLICY = {"gradient_clip_l2": 5.0, "batch_size": 1,
                 "row_order": "population_order_repeated", "curriculum": "none"}
AUTHORITY = {name: False for name in (
    "source_encoder_authenticated", "source_semantics_verified", "training_gold_qualified",
    "heldout_accuracy", "statutory_accuracy", "production_ready", "graph_admission",
    "Lean_admission", "native_admission")}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPECS = (
    ("head", "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("trainer", "logic/formalization/autoencoder/legal_compact_content_training_v2.py",
     "3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59"),
    ("runtime", "logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py",
     "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"),
    ("decisions", "logic/formalization/autoencoder/legal_compact_content_decisions_v1.py",
     "e404b4299790d099cc124e93092082e81848cade8c1d9f130e2c83cc34b1e5b2"),
    ("tokens", "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    (None, "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    (None, "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    ("numerical", "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
)
_FIELDS = {
    "schema", "profile", "architecture", "input_dimension", "vocabulary_size",
    "max_total_ids", "config", "codec", "codec_sha256", "runtime", "runtime_sha256",
    "donor_checkpoint", "donor_checkpoint_sha256", "historical_parent_progress",
    "population_raw_utf8", "population_sha256", "rows_utf8", "inventories",
    "inventories_sha256", "objective_policy", "objective_policy_sha256",
    "optimizer_config", "adam_policy", "update_policy", "optimizer_history_origin",
    "parameter_order", "model_state", "weights_sha256", "initial_weights_sha256",
    "optimizer_state", "optimizer_state_sha256", "progress",
    "initial_checkpoint_sha256", "parent_checkpoint_sha256", "implementation",
    "training_mask", "evaluation_gold_mask", "authority",
}


class WeightedTrainingError(ValueError):
    """Closed objective, immutable input, named state, source or runtime failed."""


def _need(ok, message):
    if not ok:
        raise WeightedTrainingError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise WeightedTrainingError("bounded ordinary finite JSON required") from error
    _need(len(raw) <= MAX_INPUT_BYTES, "whole canonical JSON byte limit exceeded")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path,
          "canonical unaliased source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= 131072, "bounded single-link source required")
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source bytes or identity changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, identity(after)


def _sources():
    root = None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor / "ipfs_datasets_py",
                          ancestor / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][1]).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical owner tree unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, expected) for _, relative, expected in _SPECS]]


def _implementation():
    return {"weighted_training_sha256": _SELF_SHA,
            "direct_owners": {relative: expected for _, relative, expected in _SPECS}}


@contextmanager
def _scope(original):
    """Pure owner imports and bounded snapshots; no numerical owner import."""
    root, pins = _sources()
    modules, captured, fingerprint, failure = {}, None, None, None
    def fence():
        _need(_sources() == (root, pins), "source custody changed")
        for key, relative, _ in _SPECS:
            if key in modules:
                _need(Path(modules[key].__file__).absolute() == root / relative,
                      "loaded owner origin changed")
        if fingerprint is not None:
            helper, head = modules["runtime"], modules["head"]
            _need(head._fingerprint(captured) == fingerprint
                  and head._fingerprint(helper._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == fingerprint,
                  "original or captured input changed")
    try:
        for key, relative, _ in _SPECS:
            if key is not None and key != "numerical":
                module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical public owner import required")
                modules[key] = module
        captured = modules["runtime"]._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
        fingerprint = modules["head"]._fingerprint(captured)
        fence()
        yield captured, modules, fence
        fence()
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, WeightedTrainingError):
            raise WeightedTrainingError(str(error)) from error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing weighted training custody check also failed.")


def policy(choice_weight=1):
    """This first profile supports only forced=1 and choice=1 or 4."""
    _need(type(choice_weight) in (int, float) and choice_weight in (1, 4),
          "only explicit choice weights 1 or 4 are supported")
    return {"schema": POLICY_SCHEMA, "objective": "weighted_full537_cross_entropy",
            "forced_weight": 1.0, "choice_weight": float(choice_weight),
            "normalization": "sum_of_complete_positive_position_weights",
            "uniform_kernel": "cross_entropy_mean_ignore_index_0",
            "weighted_kernel": "cross_entropy_none_then_weighted_sum_over_weight_sum",
            "ignore_index": 0, "vocabulary_size": 537,
            "inventory_schema": "legal-compact-content-decisions/v1",
            "inventory_profile": "all-predicates-prefix-decisions/v1"}


def _policy(offered):
    _need(type(offered) is dict and "choice_weight" in offered, "closed objective policy required")
    expected = policy(offered["choice_weight"])
    _need(set(offered) == set(expected) and all(type(offered[key]) is type(expected[key])
          and offered[key] == expected[key] for key in expected),
          "objective policy differs from supported exact policy")
    return expected


def policy_sha256(offered):
    return _digest(_policy(offered))


def checkpoint_sha256(checkpoint):
    """Canonical typed identity only; no checkpoint validation or restoration."""
    with _scope({"checkpoint": checkpoint}) as (data, modules, _):
        value = modules["runtime"]._copy(data["checkpoint"], MAX_CHECKPOINT_BYTES)
        return _digest(value)


def _donor(offered, modules):
    _need(_digest(offered) == DONOR_SHA256, "exact retained a98 donor required")
    value = modules["runtime"].inspect_compact_content_trained_checkpoint_v2(
        offered, expected_checkpoint_sha256=DONOR_SHA256)
    _need(value["config"] == CONFIG and value["population_count"] == 2
          and value["progress"] == {"optimizer_steps": 2, "epochs_completed": 1, "row_cursor": 0},
          "retained donor geometry or historical population differs")
    return value


def _raw_rows(stored):
    _need(type(stored) is list and len(stored) == 2, "complete two-row stored population required")
    result = []
    for row in stored:
        fields = {"id", "source_group", "source_utf8", "context_utf8", "target_utf8", "conditioning"}
        _need(type(row) is dict and set(row) == fields
              and all(type(row[key + "_utf8"]) is str for key in ("source", "context", "target")),
              "closed stored UTF8 training row required")
        result.append({"id": row["id"], "source_group": row["source_group"],
            "source_raw": row["source_utf8"].encode(), "context_raw": row["context_utf8"].encode(),
            "target_raw": row["target_utf8"].encode(), "conditioning": deepcopy(row["conditioning"])})
    return result


def _population(raw, rows, donor, modules):
    _need(type(raw) is bytes and raw == donor["population_raw_utf8"].encode(),
          "exact donor population bytes and order required")
    head, trainer = modules["head"], modules["trainer"]
    population = trainer._population(raw, donor["population_sha256"], head)
    loaded = {"modules": {"tokens": modules["tokens"]}}
    prepared = trainer._rows(rows, population, donor["codec"], donor["codec_sha256"], head, loaded)
    inventories = []
    for row, bound, encoded in zip(rows, population["rows"], prepared):
        inventory = modules["decisions"].prepare_compact_content_decisions_v1(
            row["target_raw"], row["context_raw"], expected_content_sha256=bound["target_sha256"],
            expected_context_sha256=bound["context_sha256"], codec=donor["codec"],
            expected_codec_sha256=donor["codec_sha256"])
        _need(inventory["target_ids"] == encoded["target_ids"]
              and inventory["counts"]["supervised_positions"] == len(encoded["target_ids"]) - 1
              and all(flag is False for flag in inventory["authority"].values())
              and inventory["training_mask"] == inventory["evaluation_gold_mask"] == 0,
              "complete source-bound public grammar inventory differs")
        inventories.append(inventory)
    return prepared, inventories


def _progress(value):
    _need(type(value) is dict and set(value) == {"optimizer_steps", "epochs_completed", "row_cursor"}
          and all(type(x) is int for x in value.values())
          and 0 <= value["optimizer_steps"] <= MAX_NEW_STEPS
          and value["epochs_completed"] == value["optimizer_steps"] // 2
          and value["row_cursor"] == value["optimizer_steps"] % 2,
          "exact bounded two-row progress required")
    return value["optimizer_steps"]


def _validate(offered, expected, expected_policy, modules):
    _sha(expected, "checkpoint")
    _sha(expected_policy, "objective policy")
    value = modules["runtime"]._copy(offered, MAX_CHECKPOINT_BYTES)
    _need(_digest(value) == expected and type(value) is dict and set(value) == _FIELDS,
          "closed independently bound weighted checkpoint required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["architecture"] == ARCHITECTURE
          and type(value["input_dimension"]) is int and value["input_dimension"] == 384
          and type(value["vocabulary_size"]) is int and value["vocabulary_size"] == 537
          and type(value["max_total_ids"]) is int and value["max_total_ids"] == 512,
          "weighted checkpoint profile or geometry differs")
    objective = _policy(value["objective_policy"])
    _need(_digest(objective) == value["objective_policy_sha256"] == expected_policy,
          "independent objective policy or resume policy changed")
    donor = _donor(value["donor_checkpoint"], modules)
    _need(value["donor_checkpoint_sha256"] == DONOR_SHA256
          and _wire(value["historical_parent_progress"]) == _wire(donor["progress"])
          and _wire(value["config"]) == _wire(donor["config"])
          and _wire(value["codec"]) == _wire(donor["codec"])
          and value["codec_sha256"] == donor["codec_sha256"]
          and _wire(value["runtime"]) == _wire(donor["runtime"])
          and value["runtime_sha256"] == _digest(donor["runtime"])
          and value["population_sha256"] == donor["population_sha256"]
          and type(value["population_raw_utf8"]) is str,
          "immutable donor, runtime, codec or population binding differs")
    prepared, inventories = _population(value["population_raw_utf8"].encode(),
                                         _raw_rows(value["rows_utf8"]), donor, modules)
    _need(_wire(value["inventories"]) == _wire(inventories)
          and value["inventories_sha256"] == _digest(inventories),
          "stored inventory differs from independently recomputed public grammar")
    head, trainer = modules["head"], modules["trainer"]
    _need(value["parameter_order"] == list(head._shapes(donor["config"]))
          and _wire(value["optimizer_config"]) == _wire({"learning_rate": 0.001})
          and _wire(value["adam_policy"]) == _wire({"name": "Adam", "defaults": donor["optimizer_policy"]["defaults"]})
          and _wire(value["update_policy"]) == _wire(UPDATE_POLICY)
          and value["optimizer_history_origin"] == "fresh_for_new_objective_no_donor_Adam_inheritance"
          and _wire(value["implementation"]) == _wire(_implementation()),
          "actual parameter order, Adam mechanics, objective lineage or source differs")
    head._state(value["model_state"], value["config"])
    _need(value["weights_sha256"] == _digest(value["model_state"])
          and value["initial_weights_sha256"] == donor["weights_sha256"], "model-state identity differs")
    steps = _progress(value["progress"])
    trainer._optimizer_state(value["optimizer_state"], value["progress"], value["config"], head)
    _need(value["optimizer_state_sha256"] == _digest(value["optimizer_state"]), "named Adam state digest differs")
    if not steps:
        _need(value["model_state"] == donor["model_state"]
              and value["initial_checkpoint_sha256"] is None and value["parent_checkpoint_sha256"] is None,
              "zero-step state must preserve exact donor weights and fresh Adam")
    else:
        _sha(value["initial_checkpoint_sha256"], "initial weighted checkpoint")
        _sha(value["parent_checkpoint_sha256"], "immediate weighted parent")
        initial = deepcopy(value)
        empty = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
        initial.update(model_state=deepcopy(donor["model_state"]), weights_sha256=donor["weights_sha256"],
            optimizer_state=empty, optimizer_state_sha256=_digest(empty),
            progress={"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
            initial_checkpoint_sha256=None, parent_checkpoint_sha256=None)
        _need(value["initial_checkpoint_sha256"] == _digest(initial),
              "initial weighted checkpoint identity differs from deterministic fresh state")
        if steps == 1:
            _need(value["parent_checkpoint_sha256"] == value["initial_checkpoint_sha256"],
                  "first update must bind exact zero-step parent")
    _need(_wire(value["authority"]) == _wire(AUTHORITY)
          and type(value["training_mask"]) is type(value["evaluation_gold_mask"]) is int
          and value["training_mask"] == value["evaluation_gold_mask"] == 0,
          "engineering checkpoint grants no semantic eligibility")
    return value, prepared


def create(donor, population_raw, rows, *, expected_donor_sha256,
           expected_population_sha256, choice_weight=1):
    """Pure creation from exact a98 weights; historical Adam is provenance only."""
    original = dict(donor=donor, population_raw=population_raw, rows=rows,
                    expected_donor_sha256=expected_donor_sha256,
                    expected_population_sha256=expected_population_sha256, choice_weight=choice_weight)
    with _scope(original) as (data, modules, _):
        _need(data["expected_donor_sha256"] == DONOR_SHA256, "independent exact a98 donor hash required")
        parent = _donor(data["donor"], modules)
        _need(data["expected_population_sha256"] == parent["population_sha256"],
              "independent exact donor population hash required")
        objective = policy(data["choice_weight"])
        _, inventories = _population(data["population_raw"], data["rows"], parent, modules)
        stored = [{"id": row["id"], "source_group": row["source_group"],
            "source_utf8": row["source_raw"].decode(), "context_utf8": row["context_raw"].decode(),
            "target_utf8": row["target_raw"].decode(), "conditioning": deepcopy(row["conditioning"])}
            for row in data["rows"]]
        empty = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
        value = {"schema": SCHEMA, "profile": PROFILE, "architecture": ARCHITECTURE,
            "input_dimension": 384, "vocabulary_size": 537, "max_total_ids": 512,
            "config": deepcopy(parent["config"]), "codec": deepcopy(parent["codec"]),
            "codec_sha256": parent["codec_sha256"], "runtime": deepcopy(parent["runtime"]),
            "runtime_sha256": _digest(parent["runtime"]), "donor_checkpoint": parent,
            "donor_checkpoint_sha256": DONOR_SHA256, "historical_parent_progress": deepcopy(parent["progress"]),
            "population_raw_utf8": data["population_raw"].decode(), "population_sha256": parent["population_sha256"],
            "rows_utf8": stored, "inventories": inventories, "inventories_sha256": _digest(inventories),
            "objective_policy": objective, "objective_policy_sha256": _digest(objective),
            "optimizer_config": {"learning_rate": 0.001},
            "adam_policy": {"name": "Adam", "defaults": deepcopy(parent["optimizer_policy"]["defaults"])},
            "update_policy": dict(UPDATE_POLICY),
            "optimizer_history_origin": "fresh_for_new_objective_no_donor_Adam_inheritance",
            "parameter_order": list(modules["head"]._shapes(parent["config"])),
            "model_state": deepcopy(parent["model_state"]), "weights_sha256": parent["weights_sha256"],
            "initial_weights_sha256": parent["weights_sha256"], "optimizer_state": empty,
            "optimizer_state_sha256": _digest(empty),
            "progress": {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
            "initial_checkpoint_sha256": None, "parent_checkpoint_sha256": None,
            "implementation": _implementation(), "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": dict(AUTHORITY)}
        return _validate(value, _digest(value), _digest(objective), modules)[0]


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Pure complete checkpoint/policy/grammar check; no model or Adam allocation."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, _):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        return {"schema": SCHEMA, "profile": PROFILE, "checkpoint_sha256": data["expected"],
            "objective_policy_sha256": data["expected_policy"], "inventories_sha256": value["inventories_sha256"],
            "weights_sha256": value["weights_sha256"], "optimizer_state_sha256": value["optimizer_state_sha256"],
            "progress": deepcopy(value["progress"]), "parameter_order": list(value["parameter_order"]),
            "runtime_verified": False, "model_constructed": False, "optimizer_constructed": False,
            "later_parent_is_commitment_not_replayed": value["progress"]["optimizer_steps"] > 1,
            "authority": dict(AUTHORITY)}


def _row(value, prepared):
    index = value["progress"]["row_cursor"]
    row, inventory = prepared[index], value["inventories"][index]
    objective = value["objective_policy"]
    weights = [objective[position["decision_kind"] + "_weight"] for position in inventory["positions"]]
    _need(len(weights) == len(row["target_ids"]) - 1 and all(x in (1.0, 4.0) for x in weights),
          "complete positive fixed position weights required")
    return {"id": row["id"], "row_index": index, "conditioning": deepcopy(row["conditioning"]),
            "target_ids": list(row["target_ids"]), "position_weights": weights,
            "inventory_sha256": _digest(inventory), "policy_sha256": value["objective_policy_sha256"]}


def training_row(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Return exact current ordered row and newly validated grammar-derived weights."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, _):
        value, prepared = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        return _row(value, prepared)


def _numeric(modules):
    root, pins = _sources()
    key, relative, _ = next(entry for entry in _SPECS if entry[0] == "numerical")
    numerical = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
    _need(Path(numerical.__file__).absolute() == root / relative and _sources() == (root, pins),
          "canonical numerical owner differs")
    modules[key] = numerical
    torch = numerical._torch()
    loaded = {"modules": {"numerical": numerical}}
    live = modules["trainer"]._runtime(modules["head"], loaded)
    return numerical, torch, live


def _actual(model, optimizer, value, steps, modules, numerical, torch):
    _need(type(optimizer) is torch.optim.Adam and len(optimizer.param_groups) == 1,
          "one exact original Adam required")
    observed = modules["trainer"]._optimizer_policy(optimizer, 0.001)
    _need(_wire({"name": observed["name"], "defaults": observed["defaults"]}) == _wire(value["adam_policy"])
          and observed["gradient_clip_l2"] == UPDATE_POLICY["gradient_clip_l2"],
          "actual Adam mechanics differ; weighted objective remains separately bound")
    named = dict(model.named_parameters())
    tensors = model.state_dict()
    _need(list(named) == list(tensors) == value["parameter_order"], "exact model parameter/state order required")
    group = optimizer.param_groups[0]
    _need(set(group) == set(value["adam_policy"]["defaults"]) | {"params"}
          and len(group["params"]) == len(named)
          and all(a is b for a, b in zip(group["params"], named.values()))
          and set(optimizer.state) == (set(named.values()) if steps else set()),
          "actual named Adam parameter membership differs")
    shapes = modules["head"]._shapes(value["config"])
    for name, parameter in named.items():
        _need(tuple(parameter.shape) == shapes[name] and parameter.device.type == "cpu"
              and parameter.dtype is torch.float32 and parameter.requires_grad is True
              and bool(torch.isfinite(parameter).all()), "actual model tensor flags or finiteness differ")
        if not steps:
            continue
        state = optimizer.state[parameter]
        _need(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"},
              "closed actual named Adam state required")
        step = state["step"]
        _need(isinstance(step, torch.Tensor) and tuple(step.shape) == () and step.device.type == "cpu"
              and step.dtype is torch.float32 and not step.requires_grad and bool(torch.isfinite(step))
              and float(step) == steps, "actual exact Adam step differs")
        for field in ("exp_avg", "exp_avg_sq"):
            tensor = state[field]
            _need(isinstance(tensor, torch.Tensor) and tuple(tensor.shape) == tuple(parameter.shape)
                  and tensor.device.type == "cpu" and tensor.dtype is torch.float32
                  and not tensor.requires_grad and bool(torch.isfinite(tensor).all())
                  and (field != "exp_avg_sq" or bool((tensor >= 0).all())),
                  "actual finite named Adam moment tensor differs")
    weights, moments = numerical._pack(model, optimizer)
    modules["head"]._state(weights, value["config"])
    modules["trainer"]._optimizer_state(moments,
        {"optimizer_steps": steps, "epochs_completed": steps // 2, "row_cursor": steps % 2},
        value["config"], modules["head"])
    return weights, moments


def restore(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Restore one canonical model and one Adam, after all pure checkpoint checks."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        numerical, torch, runtime = _numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live runtime differs before model/Adam restoration")
        rng = torch.get_rng_state().clone()
        try:
            model = numerical._model({"dimension": 384}, {"target_vocabulary": value["codec"]["vocabulary"]}, value["config"])
            templates = model.state_dict()
            _need(list(templates) == value["parameter_order"], "restored canonical model order differs")
            model.load_state_dict({name: numerical._tensor(value["model_state"][name], template, name)
                                   for name, template in templates.items()}, strict=True)
            model.eval()
            optimizer = numerical._optimizer(model, value["optimizer_config"])
            for name, parameter in model.named_parameters():
                state = value["optimizer_state"]["parameters"].get(name)
                if state is not None:
                    optimizer.state[parameter] = {
                        "step": torch.tensor(float(state["step"]), dtype=torch.float32, device="cpu"),
                        "exp_avg": numerical._tensor(state["exp_avg"], parameter, name + ".exp_avg"),
                        "exp_avg_sq": numerical._tensor(state["exp_avg_sq"], parameter, name + ".exp_avg_sq", nonnegative=True)}
            weights, moments = _actual(model, optimizer, value, value["progress"]["optimizer_steps"], modules, numerical, torch)
            _need(weights == value["model_state"] and moments == value["optimizer_state"],
                  "complete named model/Adam restoration is not exact")
            fence()
            _need(_wire(_numeric(modules)[2]) == _wire(runtime), "runtime changed during restoration")
            return model, optimizer
        finally:
            _need(torch.equal(rng, torch.get_rng_state()), "restoration changed ambient CPU RNG")


def objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Return a differentiable loss and JSON metadata; never forward or backward."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, prepared = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        row = _row(value, prepared)
        _, torch, runtime = _numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live objective runtime differs")
        _need(isinstance(logits, torch.Tensor) and logits.device.type == "cpu" and logits.dtype is torch.float32
              and tuple(logits.shape) == (1, len(row["target_ids"]) - 1, 537)
              and bool(torch.isfinite(logits).all()) and logits.requires_grad,
              "complete differentiable finite float32 teacher-forced scores required")
        version = logits._version
        rng = torch.get_rng_state().clone()
        labels = torch.tensor(row["target_ids"][1:], dtype=torch.long, device="cpu")
        _need(bool((labels != 0).all()), "no padding label belongs to this complete fixed profile")
        weights = row["position_weights"]
        if value["objective_policy"]["choice_weight"] == 1.0:
            # Deliberately the exact baseline kernel, not an algebraically
            # equivalent reduction with different floating-point accumulation.
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 537), labels.reshape(-1), ignore_index=0)
            reduction = "canonical_cross_entropy_mean_ignore_index_0"
        else:
            per_position = torch.nn.functional.cross_entropy(
                logits.reshape(-1, 537), labels.reshape(-1), ignore_index=0, reduction="none")
            weight_tensor = torch.tensor(weights, dtype=torch.float32, device="cpu")
            _need(bool(torch.isfinite(weight_tensor).all()) and bool((weight_tensor > 0).all()),
                  "complete weights must remain positive in numerical dtype")
            loss = (per_position * weight_tensor).sum() / weight_tensor.sum()
            reduction = "full537_none_weighted_sum_divide_weight_sum"
        _need(tuple(loss.shape) == () and loss.requires_grad and bool(torch.isfinite(loss)),
              "finite differentiable scalar objective required")
        fence()
        _need(logits._version == version and torch.equal(rng, torch.get_rng_state())
              and _wire(_numeric(modules)[2]) == _wire(runtime), "objective mutated scores/RNG or runtime changed")
        report = {"schema": "legal-compact-weighted-objective-observation/v1",
            "checkpoint_sha256": data["expected"], "objective_policy_sha256": data["expected_policy"],
            "row_id": row["id"], "row_index": row["row_index"], "inventory_sha256": row["inventory_sha256"],
            "target_ids": row["target_ids"], "label_ids": row["target_ids"][1:],
            "position_weights": weights, "weight_sum": math.fsum(weights),
            "supervised_positions": len(weights), "reduction": reduction,
            "full537_vocabulary": True, "conditional_allowed_set_loss": False,
            "forward_performed": False, "backward_performed": False, "optimizer_update_performed": False,
            "teacher_forcing": True, "authority": dict(AUTHORITY)}
        return loss, report


def pack(model, optimizer, checkpoint, progress, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Pack one completed actual update, binding policy and exact immediate parent."""
    with _scope(dict(checkpoint=checkpoint, progress=progress, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        steps = _progress(data["progress"])
        _need(steps == value["progress"]["optimizer_steps"] + 1, "pack must advance exactly one actual update")
        numerical, torch, runtime = _numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live packing runtime differs")
        rng = torch.get_rng_state().clone()
        weights, moments = _actual(model, optimizer, value, steps, modules, numerical, torch)
        result = deepcopy(value)
        result.update(model_state=weights, weights_sha256=_digest(weights), optimizer_state=moments,
            optimizer_state_sha256=_digest(moments), progress=deepcopy(data["progress"]),
            parent_checkpoint_sha256=data["expected"],
            initial_checkpoint_sha256=data["expected"] if value["progress"]["optimizer_steps"] == 0
                else value["initial_checkpoint_sha256"])
        result = _validate(result, _digest(result), data["expected_policy"], modules)[0]
        fence()
        _need(torch.equal(rng, torch.get_rng_state()) and _wire(_numeric(modules)[2]) == _wire(runtime),
              "packing changed RNG or runtime")
        return result
