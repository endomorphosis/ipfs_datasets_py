"""Explicit scope-denominator objectives for the retained compact384 donor.

Both objectives retain baseline-v1 forced/choice weights. Scope inventories are
additional commitments, never replacement training labels or old checkpoints.
The caller owns admission and finite forward/backward/update work.
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

SCHEMA = "legal-compact-scope-training-checkpoint/v1"
PROFILE = "authored-h0-only-compact384-fixed537-scope-objective-development/v1"
POLICY_SCHEMA = "legal-compact-baseline-weighted-scope-objective/v1"
INVENTORY_SCHEMA = "legal-compact-content-scope-training-inventory/v1"
INVENTORY_PROFILE = "baseline-weights-with-scope-allowed-sets/v1"
ARCHITECTURE = "inherited-joint-gru-h0-only/v1"
DONOR_SHA256 = "a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b"
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
AUTHORITY = {name: False for name in (
    "source_encoder_authenticated", "source_semantics_verified", "training_gold_qualified",
    "heldout_accuracy", "statutory_accuracy", "production_ready", "graph_admission",
    "Lean_admission", "native_admission")}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPECS = (
    ("weighted", "logic/formalization/autoencoder/legal_compact_content_weighted_training_v1.py",
     "3646b831d73338a2bc93f4ca414f8e3cf317b576d404244be4089fbe736168cc"),
    ("scope", "logic/formalization/autoencoder/legal_compact_content_scope_filter_v1.py",
     "7b77e5d71012f9394ec0eb9fa05a70310644a3ed5e334f8e91904354b6a187b9"),
)
_FIELDS = {
    "schema", "profile", "architecture", "input_dimension", "vocabulary_size", "max_total_ids",
    "config", "codec", "codec_sha256", "runtime", "runtime_sha256", "donor_checkpoint",
    "donor_checkpoint_sha256", "historical_parent_progress", "population_raw_utf8", "population_sha256",
    "rows_utf8", "inventories", "inventories_sha256", "scope_inventories", "scope_inventories_sha256",
    "scope_policy", "scope_policy_sha256", "objective_policy", "objective_policy_sha256",
    "optimizer_config", "adam_policy", "update_policy", "optimizer_history_origin", "parameter_order",
    "model_state", "weights_sha256", "initial_weights_sha256", "optimizer_state", "optimizer_state_sha256",
    "progress", "initial_checkpoint_sha256", "parent_checkpoint_sha256", "implementation",
    "training_mask", "evaluation_gold_mask", "authority",
}


class ScopeTrainingError(ValueError):
    """Closed scope policy, state, input, source or numerical contract failed."""


def _need(ok, message):
    if not ok:
        raise ScopeTrainingError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent SHA256 required: " + label)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ScopeTrainingError("bounded ordinary finite JSON required") from error
    _need(len(raw) <= MAX_INPUT_BYTES, "whole canonical JSON byte limit exceeded")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path, "unaliased source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 131072,
          "bounded single-link source required")
    raw, after = path.read_bytes(), path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source bytes or identity changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, identity(after)


def _sources():
    root = None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor / "ipfs_datasets_py", ancestor / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][1]).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical weighted/scope owner tree unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, pin) for _, relative, pin in _SPECS]]


def _implementation():
    return {"scope_training_sha256": _SELF_SHA,
            "direct_owners": {relative: pin for _, relative, pin in _SPECS}}


@contextmanager
def _scope(original):
    """Compose the unchanged input/source owner with this owner and scope filter."""
    root, observed = _sources()
    owners, scope_owners, failure = {}, None, None
    def outer_fence():
        _need(_sources() == (root, observed), "scope training source custody changed")
        for key, relative, _ in _SPECS:
            if key in owners:
                _need(Path(owners[key].__file__).absolute() == root / relative, "loaded owner origin changed")
        if scope_owners is not None:
            current = owners["scope"]._owners()
            _need(current[0] is scope_owners[0] and current[1] is scope_owners[1]
                  and current[2] == scope_owners[2], "scope dependency custody changed")
    try:
        for key, relative, _ in _SPECS:
            module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical owner import required")
            owners[key] = module
        scope_owners = owners["scope"]._owners()
        with owners["weighted"]._scope(original) as (data, modules, original_fence):
            _need(scope_owners[1] is modules["tokens"] and owners["scope"].POLICY == scope_policy()["policy"],
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
        if isinstance(error, ValueError) and not isinstance(error, ScopeTrainingError):
            failure = ScopeTrainingError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer_fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing scope training custody check also failed.")


def scope_policy():
    return {"schema": "legal-compact-training-scope-policy/v1",
            "policy": "lexically-bound-variable-predicate-arguments/v1",
            "scope_filter_sha256": _SPECS[1][2], "inventory_schema": INVENTORY_SCHEMA,
            "inventory_profile": INVENTORY_PROFILE, "weight_basis": "baseline_v1_decision_kind",
            "target_policy": "all_complete_bound_target_prefixes_target_must_be_allowed"}


def policy(choice_weight=4, *, objective_kind="full537"):
    """Closed1:4 baseline weights; only the score denominator differs."""
    _need(type(choice_weight) in (int, float) and choice_weight == 4, "only fixed baseline choice weight4 is supported")
    _need(type(objective_kind) is str and objective_kind in ("full537", "scope_conditional"),
          "objective_kind must be full537 or scope_conditional")
    return {"schema": POLICY_SCHEMA, "objective_kind": objective_kind,
            "objective": "baseline_weighted_cross_entropy", "forced_weight": 1.0, "choice_weight": 4.0,
            "weight_basis": "baseline_v1_decision_kind", "normalization": "sum_of_complete_baseline_position_weights",
            "denominator": "full537" if objective_kind == "full537" else "scope_allowed_token_ids",
            "weighted_kernel": "cross_entropy_none_then_weighted_sum_over_weight_sum",
            "ignore_index": 0, "vocabulary_size": 537,
            "baseline_inventory_schema": "legal-compact-content-decisions/v1",
            "scope_policy_sha256": _digest(scope_policy()),
            "scope_singleton_conditional_loss": "zero_independent_of_model_quality"}


def _policy(value):
    _need(type(value) is dict and "objective_kind" in value and "choice_weight" in value, "closed objective policy required")
    expected = policy(value["choice_weight"], objective_kind=value["objective_kind"])
    _need(set(value) == set(expected) and all(type(value[k]) is type(expected[k]) and value[k] == expected[k]
          for k in expected), "objective policy differs from exact supported policy")
    return expected


def policy_sha256(offered):
    return _digest(_policy(offered))


def checkpoint_sha256(checkpoint):
    """Typed canonical identity only; no validation or numerical allocation."""
    with _scope({"checkpoint": checkpoint}) as (data, modules, _):
        return _digest(modules["runtime"]._copy(data["checkpoint"], MAX_CHECKPOINT_BYTES))


def _inventories(rows, donor, baseline, modules):
    result = []
    for row, inventory in zip(rows, baseline):
        positions, ids = [], inventory["target_ids"]
        for position in inventory["positions"]:
            index = position["target_position"]
            prefix = ids[:index]
            report = modules["scope"].allowed_token_ids(prefix, row["context_raw"],
                expected_context_sha256=inventory["context_raw_sha256"], codec=donor["codec"],
                expected_codec_sha256=donor["codec_sha256"])
            allowed = report["allowed_token_ids"]
            _need(report["schema"] == modules["scope"].PREFIX_SCHEMA and report["policy"] == scope_policy()["policy"]
                  and report["owner_pins"] == modules["scope_pins"] and report["status"] == "prefix"
                  and report["reason"] is None and report["offered_ids"] == prefix
                  and report["context_raw_sha256"] == inventory["context_raw_sha256"]
                  and report["codec_sha256"] == donor["codec_sha256"]
                  and report["baseline_prefix_report"]["allowed_token_ids"] == position["allowed_token_ids"]
                  and _digest(report["baseline_prefix_report"]) == position["prefix_report_sha256"]
                  and allowed == sorted(set(allowed)) and allowed and ids[index] in allowed
                  and set(allowed) <= set(position["allowed_token_ids"])
                  and all(flag is False for flag in report["authority"].values())
                  and report["training_mask"] == report["evaluation_gold_mask"] == 0,
                  "complete target scope inventory or original annotation differs")
            weight = 1.0 if position["decision_kind"] == "forced" else 4.0
            positions.append(dict(target_position=index, prefix_ids_sha256=_digest(prefix),
                target_token_id=ids[index], baseline_decision_kind=position["decision_kind"],
                baseline_position_weight=weight, baseline_allowed_token_ids=list(position["allowed_token_ids"]),
                allowed_token_ids=list(allowed), allowed_count=len(allowed),
                removed_token_ids=sorted(set(position["allowed_token_ids"]) - set(allowed)),
                scope_prefix_report_sha256=_digest(report)))
        result.append(dict(schema=INVENTORY_SCHEMA, profile=INVENTORY_PROFILE, row_id=row["id"],
            source_raw_sha256=hashlib.sha256(row["source_raw"]).hexdigest(),
            context_raw_sha256=inventory["context_raw_sha256"], content_raw_sha256=inventory["content_raw_sha256"],
            codec_sha256=donor["codec_sha256"], baseline_inventory_sha256=_digest(inventory),
            scope_policy_sha256=_digest(scope_policy()), target_ids_sha256=_digest(ids), positions=positions,
            supervised_positions=len(positions), baseline_weight_sum=math.fsum(p["baseline_position_weight"] for p in positions),
            singleton_positions=sum(p["allowed_count"] == 1 for p in positions),
            nontrivial_positions=sum(p["allowed_count"] > 1 for p in positions),
            owner_pins=deepcopy(modules["scope_pins"]), target_exposed=True,
            global_completability_proven=False, authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0))
    _need(len(result) == 2 and all(r["supervised_positions"] == 46 and r["baseline_weight_sum"] == 67
          and r["singleton_positions"] == 39 and r["nontrivial_positions"] == 7 for r in result),
          "retained two-row baseline1:4 population or scope geometry differs")
    return result


def _validate(offered, expected, expected_policy, modules):
    _sha(expected, "checkpoint"); _sha(expected_policy, "objective policy")
    value = modules["runtime"]._copy(offered, MAX_CHECKPOINT_BYTES)
    _need(type(value) is dict and set(value) == _FIELDS and _digest(value) == expected,
          "closed independently bound scope checkpoint required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["architecture"] == ARCHITECTURE
          and all(type(value[k]) is int and value[k] == n for k, n in
                  (("input_dimension", 384), ("vocabulary_size", 537), ("max_total_ids", 512))),
          "scope checkpoint profile or geometry differs")
    objective = _policy(value["objective_policy"])
    _need(_digest(objective) == value["objective_policy_sha256"] == expected_policy
          and _wire(value["scope_policy"]) == _wire(scope_policy())
          and value["scope_policy_sha256"] == _digest(scope_policy()), "objective or scope policy changed")
    weighted = modules["weighted"]
    donor = weighted._donor(value["donor_checkpoint"], modules)
    _need(value["donor_checkpoint_sha256"] == DONOR_SHA256
          and all(_wire(value[k]) == _wire(donor[d]) for k, d in (
              ("historical_parent_progress", "progress"), ("config", "config"), ("codec", "codec"), ("runtime", "runtime")))
          and value["codec_sha256"] == donor["codec_sha256"]
          and value["runtime_sha256"] == _digest(donor["runtime"])
          and value["population_sha256"] == donor["population_sha256"]
          and type(value["population_raw_utf8"]) is str, "immutable donor/runtime/codec/population differs")
    rows = weighted._raw_rows(value["rows_utf8"])
    prepared, inventories = weighted._population(value["population_raw_utf8"].encode(), rows, donor, modules)
    scope_inventories = _inventories(rows, donor, inventories, modules)
    for field, actual in (("inventories", inventories), ("scope_inventories", scope_inventories)):
        _need(_wire(value[field]) == _wire(actual) and value[field + "_sha256"] == _digest(actual),
              "stored " + field + " differs from public recomputation")
    head, trainer = modules["head"], modules["trainer"]
    _need(value["parameter_order"] == list(head._shapes(donor["config"]))
          and _wire(value["optimizer_config"]) == _wire({"learning_rate": 0.001})
          and _wire(value["adam_policy"]) == _wire({"name": "Adam", "defaults": donor["optimizer_policy"]["defaults"]})
          and _wire(value["update_policy"]) == _wire(weighted.UPDATE_POLICY)
          and value["optimizer_history_origin"] == "fresh_for_new_objective_no_donor_Adam_inheritance"
          and _wire(value["implementation"]) == _wire(_implementation()), "state mechanics or implementation differs")
    head._state(value["model_state"], value["config"])
    _need(value["weights_sha256"] == _digest(value["model_state"])
          and value["initial_weights_sha256"] == donor["weights_sha256"], "model-state identity differs")
    steps = weighted._progress(value["progress"])
    trainer._optimizer_state(value["optimizer_state"], value["progress"], value["config"], head)
    _need(value["optimizer_state_sha256"] == _digest(value["optimizer_state"]), "named Adam state digest differs")
    if not steps:
        _need(value["model_state"] == donor["model_state"] and value["initial_checkpoint_sha256"] is None
              and value["parent_checkpoint_sha256"] is None, "zero-step weights or fresh Adam lineage differs")
    else:
        _sha(value["initial_checkpoint_sha256"], "initial scope checkpoint")
        _sha(value["parent_checkpoint_sha256"], "immediate scope parent")
        initial = deepcopy(value)
        empty = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
        initial.update(model_state=deepcopy(donor["model_state"]), weights_sha256=donor["weights_sha256"],
            optimizer_state=empty, optimizer_state_sha256=_digest(empty),
            progress={"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
            initial_checkpoint_sha256=None, parent_checkpoint_sha256=None)
        _need(value["initial_checkpoint_sha256"] == _digest(initial), "initial fresh objective checkpoint identity differs")
        if steps == 1:
            _need(value["parent_checkpoint_sha256"] == value["initial_checkpoint_sha256"], "first update parent differs")
    _need(_wire(value["authority"]) == _wire(AUTHORITY)
          and type(value["training_mask"]) is type(value["evaluation_gold_mask"]) is int
          and value["training_mask"] == value["evaluation_gold_mask"] == 0, "engineering state grants no semantic eligibility")
    return value, prepared


def create(donor, population_raw, rows, *, expected_donor_sha256, expected_population_sha256,
           choice_weight=4, objective_kind="full537"):
    """Pure creation from original a98 weights with a fresh Adam commitment."""
    original = dict(donor=donor, population_raw=population_raw, rows=rows, expected_donor_sha256=expected_donor_sha256,
                    expected_population_sha256=expected_population_sha256, choice_weight=choice_weight,
                    objective_kind=objective_kind)
    with _scope(original) as (data, modules, _):
        _need(data["expected_donor_sha256"] == DONOR_SHA256, "independent exact a98 donor hash required")
        parent = modules["weighted"]._donor(data["donor"], modules)
        _need(data["expected_population_sha256"] == parent["population_sha256"], "independent donor population hash required")
        objective = policy(data["choice_weight"], objective_kind=data["objective_kind"])
        _, inventories = modules["weighted"]._population(data["population_raw"], data["rows"], parent, modules)
        scoped = _inventories(data["rows"], parent, inventories, modules)
        stored = [{"id": r["id"], "source_group": r["source_group"], "source_utf8": r["source_raw"].decode(),
                   "context_utf8": r["context_raw"].decode(), "target_utf8": r["target_raw"].decode(),
                   "conditioning": deepcopy(r["conditioning"])} for r in data["rows"]]
        empty = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
        value = dict(schema=SCHEMA, profile=PROFILE, architecture=ARCHITECTURE, input_dimension=384,
            vocabulary_size=537, max_total_ids=512, config=deepcopy(parent["config"]), codec=deepcopy(parent["codec"]),
            codec_sha256=parent["codec_sha256"], runtime=deepcopy(parent["runtime"]), runtime_sha256=_digest(parent["runtime"]),
            donor_checkpoint=parent, donor_checkpoint_sha256=DONOR_SHA256, historical_parent_progress=deepcopy(parent["progress"]),
            population_raw_utf8=data["population_raw"].decode(), population_sha256=parent["population_sha256"], rows_utf8=stored,
            inventories=inventories, inventories_sha256=_digest(inventories), scope_inventories=scoped,
            scope_inventories_sha256=_digest(scoped), scope_policy=scope_policy(), scope_policy_sha256=_digest(scope_policy()),
            objective_policy=objective, objective_policy_sha256=_digest(objective), optimizer_config={"learning_rate": 0.001},
            adam_policy={"name": "Adam", "defaults": deepcopy(parent["optimizer_policy"]["defaults"])},
            update_policy=dict(modules["weighted"].UPDATE_POLICY),
            optimizer_history_origin="fresh_for_new_objective_no_donor_Adam_inheritance",
            parameter_order=list(modules["head"]._shapes(parent["config"])), model_state=deepcopy(parent["model_state"]),
            weights_sha256=parent["weights_sha256"], initial_weights_sha256=parent["weights_sha256"],
            optimizer_state=empty, optimizer_state_sha256=_digest(empty),
            progress={"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0}, initial_checkpoint_sha256=None,
            parent_checkpoint_sha256=None, implementation=_implementation(), training_mask=0, evaluation_gold_mask=0,
            authority=dict(AUTHORITY))
        return _validate(value, _digest(value), _digest(objective), modules)[0]


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, _):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        return dict(schema=SCHEMA, profile=PROFILE, checkpoint_sha256=data["expected"],
            objective_policy_sha256=data["expected_policy"], objective_kind=value["objective_policy"]["objective_kind"],
            inventories_sha256=value["inventories_sha256"], scope_inventories_sha256=value["scope_inventories_sha256"],
            scope_policy_sha256=value["scope_policy_sha256"], weights_sha256=value["weights_sha256"],
            optimizer_state_sha256=value["optimizer_state_sha256"], progress=deepcopy(value["progress"]),
            parameter_order=list(value["parameter_order"]), runtime_verified=False, model_constructed=False,
            optimizer_constructed=False, later_parent_is_commitment_not_replayed=value["progress"]["optimizer_steps"] > 1,
            authority=dict(AUTHORITY))


def _row(value, prepared, modules):
    # The old helper reads original decision_kind and weights only; it neither
    # validates a checkpoint schema nor receives a fabricated old checkpoint.
    row = modules["weighted"]._row(value, prepared)
    scoped = value["scope_inventories"][row["row_index"]]
    _need(row["position_weights"] == [p["baseline_position_weight"] for p in scoped["positions"]], "baseline weights differ")
    row.update(baseline_inventory_sha256=row["inventory_sha256"], scope_inventory_sha256=_digest(scoped),
        scope_allowed_token_ids=[list(p["allowed_token_ids"]) for p in scoped["positions"]],
        baseline_decision_kinds=[p["baseline_decision_kind"] for p in scoped["positions"]],
        objective_kind=value["objective_policy"]["objective_kind"], singleton_positions=scoped["singleton_positions"],
        nontrivial_positions=scoped["nontrivial_positions"])
    return row


def training_row(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, _):
        value, prepared = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        return _row(value, prepared, modules)


def restore(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Restore exact new-schema named state with original model/Adam owners."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        weighted = modules["weighted"]
        numerical, torch, runtime = weighted._numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live restoration runtime differs")
        rng = torch.get_rng_state().clone()
        try:
            model = numerical._model({"dimension": 384}, {"target_vocabulary": value["codec"]["vocabulary"]}, value["config"])
            templates = model.state_dict()
            _need(list(templates) == value["parameter_order"], "restored parameter order differs")
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
            weights, moments = weighted._actual(model, optimizer, value, value["progress"]["optimizer_steps"], modules, numerical, torch)
            _need(weights == value["model_state"] and moments == value["optimizer_state"], "complete named restore differs")
            return model, optimizer
        finally:
            fence()
            _need(torch.equal(rng, torch.get_rng_state()) and _wire(weighted._numeric(modules)[2]) == _wire(runtime),
                  "restoration changed CPU RNG or numerical runtime")


def objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Return a differentiable scalar and observations; no forward/backward."""
    with _scope(dict(checkpoint=checkpoint, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, prepared = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        row = _row(value, prepared, modules)
        weighted = modules["weighted"]
        _, torch, runtime = weighted._numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live objective runtime differs")
        _need(isinstance(logits, torch.Tensor) and logits.device.type == "cpu" and logits.dtype is torch.float32
              and tuple(logits.shape) == (1, len(row["target_ids"]) - 1, 537)
              and bool(torch.isfinite(logits).all()) and logits.requires_grad,
              "complete differentiable finite float32 teacher-forced scores required")
        version, saved = logits._version, logits.detach().clone()
        rng = torch.get_rng_state().clone()
        try:
            labels = torch.tensor(row["target_ids"][1:], dtype=torch.long, device="cpu")
            _need(bool((labels != 0).all()), "complete profile has no padding labels")
            weights = torch.tensor(row["position_weights"], dtype=torch.float32, device="cpu")
            flat = logits.reshape(-1, 537)
            conditional = row["objective_kind"] == "scope_conditional"
            if conditional:
                allowed = torch.zeros_like(flat, dtype=torch.bool)
                for index, choices in enumerate(row["scope_allowed_token_ids"]):
                    _need(choices and row["target_ids"][index + 1] in choices, "target absent from scope denominator")
                    allowed[index, choices] = True
                per_position = torch.nn.functional.cross_entropy(flat.masked_fill(~allowed, -torch.inf),
                    labels, ignore_index=0, reduction="none")
                with torch.no_grad():
                    full = torch.nn.functional.cross_entropy(flat, labels, ignore_index=0, reduction="none")
            else:
                per_position = torch.nn.functional.cross_entropy(flat, labels, ignore_index=0, reduction="none")
                full = per_position.detach()
            loss = (per_position * weights).sum() / weights.sum()
            _need(tuple(loss.shape) == () and loss.requires_grad and bool(torch.isfinite(loss))
                  and bool(torch.isfinite(per_position).all()) and bool(torch.isfinite(full).all()),
                  "finite differentiable objective and diagnostics required")
            report = dict(schema="legal-compact-scope-objective-observation/v1", checkpoint_sha256=data["expected"],
                objective_policy_sha256=data["expected_policy"], objective_kind=row["objective_kind"],
                row_id=row["id"], row_index=row["row_index"], inventory_sha256=row["inventory_sha256"],
                baseline_inventory_sha256=row["baseline_inventory_sha256"], scope_inventory_sha256=row["scope_inventory_sha256"],
                scope_policy_sha256=value["scope_policy_sha256"], target_ids=row["target_ids"], label_ids=row["target_ids"][1:],
                position_weights=row["position_weights"], weight_sum=math.fsum(row["position_weights"]),
                supervised_positions=len(row["position_weights"]), scope_allowed_token_ids=row["scope_allowed_token_ids"],
                baseline_decision_kinds=row["baseline_decision_kinds"], singleton_positions=row["singleton_positions"],
                nontrivial_positions=row["nontrivial_positions"], per_position_losses=per_position.detach().tolist(),
                weighted_loss=float(loss.detach()), full537_per_position_losses=full.detach().tolist(),
                full537_weighted_loss=float(((full * weights).sum() / weights.sum()).detach()),
                reduction="scope_masked_none_weighted_sum_divide_baseline_weight_sum" if conditional else "full537_none_weighted_sum_divide_weight_sum",
                full537_logits_observed=True, full537_vocabulary=not conditional, conditional_allowed_set_loss=conditional,
                singleton_zero_loss_is_not_accuracy=True, full537_and_conditional_losses_not_comparable_as_accuracy=True,
                forward_performed=False, backward_performed=False, optimizer_update_performed=False,
                teacher_forcing=True, authority=dict(AUTHORITY))
            return loss, report
        finally:
            fence()
            _need(logits._version == version and torch.equal(saved, logits.detach()) and torch.equal(rng, torch.get_rng_state())
                  and _wire(weighted._numeric(modules)[2]) == _wire(runtime), "objective mutated logits/RNG or runtime")


def pack(model, optimizer, checkpoint, progress, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Bind exactly one actual update to the preceding new-schema checkpoint."""
    with _scope(dict(checkpoint=checkpoint, progress=progress, expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data, modules, fence):
        value, _ = _validate(data["checkpoint"], data["expected"], data["expected_policy"], modules)
        weighted = modules["weighted"]
        steps = weighted._progress(data["progress"])
        _need(steps == value["progress"]["optimizer_steps"] + 1, "pack must advance exactly one actual update")
        numerical, torch, runtime = weighted._numeric(modules)
        _need(_wire(runtime) == _wire(value["runtime"]), "live packing runtime differs")
        rng = torch.get_rng_state().clone()
        try:
            weights, moments = weighted._actual(model, optimizer, value, steps, modules, numerical, torch)
            result = deepcopy(value)
            result.update(model_state=weights, weights_sha256=_digest(weights), optimizer_state=moments,
                optimizer_state_sha256=_digest(moments), progress=deepcopy(data["progress"]),
                parent_checkpoint_sha256=data["expected"],
                initial_checkpoint_sha256=data["expected"] if value["progress"]["optimizer_steps"] == 0 else value["initial_checkpoint_sha256"])
            return _validate(result, _digest(result), data["expected_policy"], modules)[0]
        finally:
            fence()
            _need(torch.equal(rng, torch.get_rng_state()) and _wire(weighted._numeric(modules)[2]) == _wire(runtime),
                  "packing changed CPU RNG or numerical runtime")


__all__ = ["ScopeTrainingError", "scope_policy", "policy", "policy_sha256", "checkpoint_sha256",
           "create", "inspect", "training_row", "restore", "objective", "pack"]
