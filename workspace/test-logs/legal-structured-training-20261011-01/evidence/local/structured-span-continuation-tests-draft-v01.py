"""Inert objective-continuation controls; numerical owners are always doubles.

Synthetic source strings, latent lists and sentinel Adam moments exercise the
contract, not learned model behavior or statutory gold. No Torch, encoder,
real optimizer, model restoration or genuine inference is used by these tests.
"""
from contextlib import nullcontext
from copy import deepcopy
import ast
import builtins
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import random
import re
import sys
from types import SimpleNamespace

import pytest


SOURCE = (Path(__file__).resolve().parents[5]
          / "ipfs_datasets_py/logic/formalization/autoencoder/structured_span_continuation.py")
SCHEMA = "objective-resumed-source-span-checkpoint/v1"
LINEAGE = "objective_resumed_source_span_v1"
PROBABILITY_SCHEMA = "source-span-order-overlap-probability/v1"
FALSE = {key: False for key in (
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed",
)}
NUMERICAL_ROOTS = {"torch", "numpy", "tensorflow", "jax", "transformers",
                   "sentence_transformers", "safetensors"}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def detached_subject():
    spec = importlib.util.spec_from_file_location("detached_structured_span_controls", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def denied(*args, **kwargs):
    raise AssertionError("a numerical or legacy constructor was reached")


class NumericalFence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in NUMERICAL_ROOTS:
            raise AssertionError("unexpected numerical import: " + fullname)
        return None


def fence_imports(monkeypatch):
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name.split(".")[0] in NUMERICAL_ROOTS:
            raise AssertionError("unexpected numerical import: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    monkeypatch.setattr(sys, "meta_path", [NumericalFence(), *sys.meta_path])


def synthetic_rows(split, count):
    result = []
    for index in range(count):
        actor = split + "_actor_" + str(index)
        text = actor + " archive report"
        result.append({"id": split + "-" + str(index), "source_text": text,
            "latent": [float(index + (1 if split == "train" else 2000)) / 10000] + [0.] * 383,
            "canonical_ir": {"rules": [{"modality": "O", "actor": actor,
                "action": "archive", "object": "report", "conditions": [],
                "exceptions": [], "temporal": []}]}})
    return result


def synthetic_config():
    return {"architecture": "utf8-byte-pool-bidirectional-gru-tied-film-span-heads/v1",
        "latent_dimension": 384, "latent_enabled": True, "learning_rate": .001,
        "batch_size": 12, "seed": 1729, "hidden_size": 8, "embedding_dim": 4,
        "projection_width": 4, "residual_scale": .25, "device": "cpu", "dtype": "float32",
        "torch_version": "inert-fixture", "max_source_characters": 16384,
        "max_source_tokens": 256, "max_token_bytes": 2048,
        "tokenizer": "unicode_word_or_punctuation_exact_offsets/v1",
        "byte_alphabet": "casefold_utf8_plus1_pad0/v1", "initialization": "from_scratch",
        "loss": "equal_facet_modality_presence_mean_start_end/v1"}


def synthetic_tensor(shape, value):
    return [synthetic_tensor(shape[1:], value) for _ in range(shape[0])] if shape else value


def synthetic_weights(value):
    shapes = {
        "byte_embedding.weight": (257, 4),
        "token_projection.weight": (8, 13), "token_projection.bias": (8,),
        "encoder.weight_ih_l0": (24, 8), "encoder.weight_hh_l0": (24, 8),
        "encoder.bias_ih_l0": (24,), "encoder.bias_hh_l0": (24,),
        "encoder.weight_ih_l0_reverse": (24, 8), "encoder.weight_hh_l0_reverse": (24, 8),
        "encoder.bias_ih_l0_reverse": (24,), "encoder.bias_hh_l0_reverse": (24,),
        "modality.weight": (3, 16), "modality.bias": (3,),
        "presence.weight": (8, 16), "presence.bias": (8,),
        "start.weight": (6, 16), "start.bias": (6,),
        "end.weight": (6, 16), "end.bias": (6,),
        "latent_down.weight": (4, 384), "latent_down.bias": (4,),
        "latent_up.weight": (16, 4), "latent_up.bias": (16,),
    }
    return {name: synthetic_tensor(shape, value + index / 10000)
            for index, (name, shape) in enumerate(shapes.items())}


def synthetic_base(train, tune, implementation, *, steps, epoch, cursor, value):
    weights = synthetic_weights(value)
    moments = {name: {"step": steps,
        "exp_avg": synthetic_tensor(_shape(tensor), .03125),
        "exp_avg_sq": synthetic_tensor(_shape(tensor), .0625)}
        for name, tensor in weights.items()} if steps else {}
    return {"schema": "span-legal-formula-checkpoint/v1", "lineage_id": "source_span_formula_v1",
        "config": synthetic_config(), "implementation": deepcopy(implementation),
        "training_manifest_sha256": digest(train), "training_count": len(train),
        "tuning_manifest_sha256": digest(tune), "tuning_count": len(tune),
        "model_state": weights,
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": moments},
        "progress": {"epochs_completed": epoch, "row_cursor": cursor, "optimizer_steps": steps},
        "parent_checkpoint_sha256": "6" * 64 if steps else None, **FALSE}


def _shape(value):
    return (len(value), *_shape(value[0])) if isinstance(value, list) else ()


def synthetic_tokens(text):
    return [{"text": match.group(), "start": match.start(), "end": match.end(),
             "byte_ids": [value + 1 for value in match.group().casefold().encode("utf-8")]}
            for match in re.finditer(r"\w+|[^\w\s]", text)]


def synthetic_records(rows, dimension, *, allow_empty=False):
    if type(rows) not in (list, tuple) or (not rows and not allow_empty):
        raise ValueError("bounded examples required")
    records, ids, sources = [], set(), set()
    for row in rows:
        if type(row) is not dict or set(row) != {"id", "source_text", "canonical_ir", "latent"}:
            raise ValueError("closed example required")
        if row["id"] in ids or row["source_text"] in sources or len(row["latent"]) != dimension:
            raise ValueError("example identity or latent differs")
        ids.add(row["id"])
        sources.add(row["source_text"])
        records.append({"tokens": synthetic_tokens(row["source_text"]), "latent": list(row["latent"]),
            "labels": {"modality": 0, "presence": [True, True, True, False, False, False],
                "spans": [(0, 0), (1, 1), (2, 2), (-100, -100), (-100, -100), (-100, -100)]}})
    return records, ids, sources


def synthetic_splits(train, tune, dimension):
    fit, fit_ids, fit_sources = synthetic_records(train, dimension)
    validation, validation_ids, validation_sources = synthetic_records(tune, dimension, allow_empty=True)
    if fit_ids & validation_ids or fit_sources & validation_sources:
        raise ValueError("training/tuning overlap")
    return fit, validation


def initial_base(base, parent):
    result = deepcopy(base)
    result.update(model_state=deepcopy(parent["model_state"]),
        optimizer_state={"schema": "adam-default-betas-eps/v1", "parameters": {}},
        progress={"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        parent_checkpoint_sha256=None)
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


WARM_INITIALIZATION = {
    "mode": "warm_start_all_source_parent_model_tensors",
    "optimizer": "fresh_adam_at_warm_start_then_exact_moment_resumption",
    "base_config_initialization_scope": "standalone_constructor_descriptor; outer_lineage_defines_actual_weight_provenance",
    "all_parent_model_tensors_copied": True, "parent_optimizer_moments_transferred": False,
    "trainable_parameters": "all_model_parameters",
}


def synthetic_parent(train, tune, span_implementation, warm_implementation):
    source = synthetic_base(train, tune, span_implementation,
                            steps=800, epoch=8, cursor=384, value=.125)
    base = synthetic_base(train, tune, span_implementation,
                          steps=400, epoch=4, cursor=192, value=.25)
    contract = {"dimension": 384, "representation_id": "synthetic-source-only/raw384/v1",
                "producer_sha256": "5" * 64, "training_index_sha256": "7" * 64}
    return {"schema": "warm-start-span-legal-formula-checkpoint/v1",
        "lineage_id": "warm_start_source_span_formula_v1",
        "initialization": deepcopy(WARM_INITIALIZATION), "implementation": deepcopy(warm_implementation),
        "source_parent_checkpoint": source, "source_parent_checkpoint_sha256": digest(source),
        "source_parent_optimizer_steps": 800, "initial_model_state_sha256": digest(source["model_state"]),
        "initial_base_checkpoint_sha256": digest(initial_base(base, source)),
        "context_contract": contract, "context_contract_sha256": digest(contract),
        "base_checkpoint": base, "parent_checkpoint_sha256": "8" * 64, **FALSE}


@pytest.fixture
def bundle(monkeypatch):
    subject = detached_subject()
    train, tune = synthetic_rows("train", 1152), synthetic_rows("tune", 96)
    span_implementation = dict(span="a" * 64, codec="b" * 64,
                               canonical="c" * 64, grammar="d" * 64)
    warm_implementation = {"continuation_sha256": "e" * 64,
                           "base_span": deepcopy(span_implementation)}
    geometry_calls = []

    def geometry(records):
        require(1 <= len(records) <= 32, "one to 32 geometry records required")
        geometry_calls.append(deepcopy(records))
        return {"row_count": len(records), "provided_label_geometry_valid": True,
                "semantic_gold": False, "qualified": False, "proof_authority": False}

    def vector(value, dimension):
        require(type(value) in (list, tuple) and len(value) == dimension, "latent dimension differs")
        require(all(type(item) in (int, float) and abs(item) <= 3.4028234e38 for item in value),
                "bounded finite latent required")
        return list(value)

    def contract(value):
        require(type(value) is dict and set(value) == {
            "dimension", "representation_id", "producer_sha256", "training_index_sha256"},
            "closed context contract required")
        require(type(value["dimension"]) is int and value["dimension"] == 384,
                "context dimension differs")
        return deepcopy(value)

    span = SimpleNamespace(SCHEMA="span-legal-formula-checkpoint/v1", LINEAGE_ID="source_span_formula_v1",
        FALSE=deepcopy(FALSE), _implementation=lambda: deepcopy(span_implementation),
        _splits=synthetic_splits, _records=synthetic_records, _vector=vector,
        tokenize_source=synthetic_tokens, _config=denied, _model=denied, _restore=denied,
        build_checkpoint=denied, validate_checkpoint=denied, SpanLegalFormulaDecoder=denied,
        checkpoint_digest=digest, _raw=raw, _require=require,
        _SHA=re.compile(r"[0-9a-f]{64}\Z"), _batch=denied, _pack=denied)
    warm = SimpleNamespace(SCHEMA="warm-start-span-legal-formula-checkpoint/v1",
        LINEAGE_ID="warm_start_source_span_formula_v1", _INITIALIZATION=deepcopy(WARM_INITIALIZATION),
        _implementation=lambda: deepcopy(warm_implementation), _context_contract=contract,
        _initial_base=initial_base, validate_checkpoint=denied, build_checkpoint=denied)
    objective = SimpleNamespace(SCHEMA=PROBABILITY_SCHEMA,
        __file__=str(SOURCE.parents[2] / "legal_ir/structured_span_objective.py"),
        reference_geometry=geometry, objective_from_output=denied)
    monkeypatch.setattr(subject, "_owners", lambda: (span, warm, objective))
    monkeypatch.setattr(subject, "_restore_current", denied)
    parent = synthetic_parent(train, tune, span_implementation, warm_implementation)
    return SimpleNamespace(subject=subject, train=train, tune=tune, parent=parent,
        span=span, warm=warm, objective=objective, geometry_calls=geometry_calls,
        monkeypatch=monkeypatch)


class FakeScalar:
    def __init__(self, value=1.25, *, backward=None):
        self.value, self._backward = value, backward

    def __float__(self):
        return float(self.value)

    def detach(self):
        return self

    def numel(self):
        return 1

    def all(self):
        return self

    def clone(self):
        return FakeScalar(self.value)

    def __bool__(self):
        return bool(self.value)

    def backward(self):
        if self._backward is not None:
            self._backward()


class FakeScores:
    dtype = "torch.float32"
    device = SimpleNamespace(type="cpu")
    requires_grad = False

    def __init__(self, values):
        self.values = deepcopy(values)
        self.shape = _shape(values)

    def __getitem__(self, index):
        return FakeScores(self.values[index])

    def detach(self):
        return self

    def tolist(self):
        return deepcopy(self.values)


class FakeModel:
    def __init__(self, checkpoint):
        self.weights = deepcopy(checkpoint["state"]["model_state"])
        self._parameters = [SimpleNamespace(grad=FakeScalar()) for _ in self.weights]
        self._forward_hooks, self._forward_pre_hooks = {}, {}
        self.forward_calls = 0
        self.removed_hooks = 0

    def train(self):
        return self

    def eval(self):
        return self

    def parameters(self):
        return iter(self._parameters)

    def register_forward_hook(self, callback):
        key = len(self._forward_hooks)
        self._forward_hooks[key] = callback

        def remove():
            self._forward_hooks.pop(key)
            self.removed_hooks += 1

        return SimpleNamespace(remove=remove)

    def __call__(self, records):
        self.forward_calls += 1
        size = max(len(row["tokens"]) for row in records)
        count = len(records)
        output = {"modality": FakeScores([[0., 1., -1.] for _ in range(count)]),
            "presence": FakeScores([[[0., 1.] for _ in range(4)] for _ in range(count)]),
            "start": FakeScores([[[0.] * size for _ in range(6)] for _ in range(count)]),
            "end": FakeScores([[[0.] * size for _ in range(6)] for _ in range(count)])}
        for callback in tuple(self._forward_hooks.values()):
            callback(self, (), output)
        return output


class FakeOptimizer:
    def __init__(self, checkpoint, model):
        self.moments = deepcopy(checkpoint["state"]["optimizer_state"])
        self.model, self.steps = model, 0
        self.state = {}

    def zero_grad(self, *, set_to_none):
        assert set_to_none is True
        for parameter in self.model._parameters:
            parameter.grad = None

    def step(self):
        self.steps += 1
        self.model.weights["modality.bias"][0] += .001
        for moment in self.moments["parameters"].values():
            moment["step"] += 1


def inert_backend(bundle, checkpoint, *, fail_decode=False):
    model = FakeModel(checkpoint)
    optimizer = FakeOptimizer(checkpoint, model)
    torch = SimpleNamespace(get_rng_state=lambda: FakeScalar(1729),
        equal=lambda left, right: left.value == right.value,
        random=SimpleNamespace(fork_rng=lambda **kwargs: nullcontext()),
        no_grad=nullcontext, isfinite=lambda value: FakeScalar(1),
        is_tensor=lambda value: isinstance(value, (FakeScalar, FakeScores)),
        nn=SimpleNamespace(utils=SimpleNamespace(clip_grad_norm_=lambda *args, **kwargs: FakeScalar(.25))))
    bundle.monkeypatch.setitem(sys.modules, "torch", torch)
    bundle.monkeypatch.setattr(bundle.subject, "_restore_current", lambda value: (torch, model, optimizer))
    bundle.monkeypatch.setattr(bundle.span, "_batch", lambda owner, records: (records,))
    bundle.monkeypatch.setattr(bundle.span, "_pack", lambda owner, adam:
        (deepcopy(owner.weights), deepcopy(adam.moments)))
    decode_calls, objective_calls = [], []

    def objective(owner, output, records, *, structure_weight):
        objective_calls.append((len(records), structure_weight))

        def backward():
            for parameter in model._parameters:
                parameter.grad = FakeScalar(1)

        values = {key: FakeScalar(value) for key, value in
            (("ce", 1.25), ("validity", .2), ("overlap", .3), ("structure", .25),
             ("weighted_structure", structure_weight * .25), ("total", 1.25 + structure_weight * .25))}
        values["total"]._backward = backward
        return values

    class DecoderDouble:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy decoder constructor reached")

        def _decode(self, text, latent, *, enabled):
            decode_calls.append({"text": text, "latent": list(latent), "enabled": enabled})
            if fail_decode:
                raise RuntimeError("synthetic decode failure")
            self.model([{"tokens": synthetic_tokens(text), "latent": latent}])
            return {"status": "abstained", "reason": "inert_diagnostic_double",
                    "target_access": False, "teacher_forcing": False, **FALSE}

    bundle.monkeypatch.setattr(bundle.objective, "objective_from_output", objective)
    bundle.monkeypatch.setattr(bundle.span, "SpanLegalFormulaDecoder", DecoderDouble)
    return SimpleNamespace(torch=torch, model=model, optimizer=optimizer,
                           decode_calls=decode_calls, objective_calls=objective_calls)


def test_standalone_module_import_is_fenced_from_numerical_packages(monkeypatch):
    fence_imports(monkeypatch)
    module = detached_subject()
    assert module.SCHEMA == SCHEMA
    assert module.LINEAGE_ID == LINEAGE
    tree = ast.parse(SOURCE.read_text())
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            assert all(alias.name.split(".")[0] not in NUMERICAL_ROOTS for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom):
            assert (statement.module or "").split(".")[0] not in NUMERICAL_ROOTS


def prepare(bundle, *, structure_weight=0., **changes):
    options = {"structure_weight": structure_weight,
        "expected_parent_sha256": digest(bundle.parent),
        "expected_training_sha256": digest(bundle.train),
        "expected_tuning_sha256": digest(bundle.tune)}
    options.update(changes)
    return bundle.subject.prepare_checkpoint(bundle.parent, bundle.train, bundle.tune, **options)


def test_wrong_parent_hash_is_rejected_before_any_restore(bundle):
    before = raw(bundle.parent)
    with pytest.raises(ValueError, match="(?i)(parent|hash|sha256)"):
        prepare(bundle, expected_parent_sha256="0" * 64)
    assert raw(bundle.parent) == before


@pytest.mark.parametrize("split", ["train", "tune"])
@pytest.mark.parametrize("change", ["source", "target", "latent", "order", "expected_pin"])
def test_source_target_latent_and_order_manifest_drift_is_rejected(bundle, split, change):
    rows = getattr(bundle, split)
    before = deepcopy(rows)
    options = {"expected_parent_sha256": digest(bundle.parent), "structure_weight": .1,
        "expected_training_sha256": digest(bundle.train),
        "expected_tuning_sha256": digest(bundle.tune)}
    if change == "source":
        rows[0]["source_text"] += " changed"
    elif change == "target":
        rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif change == "latent":
        rows[0]["latent"][0] += .5
    elif change == "order":
        rows[:2] = reversed(rows[:2])
    else:
        options["expected_training_sha256" if split == "train" else "expected_tuning_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="(?i)(manifest|training|tuning|hash|sha256)"):
        bundle.subject.prepare_checkpoint(bundle.parent, bundle.train, bundle.tune, **options)
    if change == "expected_pin":
        assert rows == before


@pytest.mark.parametrize("value", [True, -.1, .05, .2, 1., "0.1", float("nan"), float("inf")])
def test_objective_weight_allows_only_the_paired_zero_and_point_one_arms(bundle, value):
    with pytest.raises(ValueError):
        prepare(bundle, structure_weight=value)


@pytest.mark.parametrize("steps", [-1, 33, True, 1.5, None])
def test_training_refuses_more_than_32_steps_and_noninteger_bounds(bundle, steps):
    checkpoint = prepare(bundle)
    with pytest.raises(ValueError, match="(?i)(step|bound|32|update)"):
        bundle.subject.train_decoder(checkpoint, bundle.train, bundle.tune,
                                     max_steps=steps, max_seconds=1.)


@pytest.mark.parametrize("seconds", [-1., True, float("nan"), float("inf"), "1"])
def test_training_refuses_invalid_deadline_bounds_before_restore(bundle, seconds):
    checkpoint = prepare(bundle)
    with pytest.raises(ValueError, match="(?i)(seconds|deadline|bound)"):
        bundle.subject.train_decoder(checkpoint, bundle.train, bundle.tune,
                                     max_steps=1, max_seconds=seconds)


def all_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(child) for child in value))
    return set()


def test_preparation_is_numeric_import_free_and_preserves_complete_Adam400(bundle, monkeypatch):
    fence_imports(monkeypatch)
    before = digest(bundle.parent), digest(bundle.train), digest(bundle.tune)
    checkpoint = prepare(bundle, structure_weight=.1)
    base = bundle.parent["base_checkpoint"]
    assert checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE
    assert checkpoint["objective"]["schema"] == PROBABILITY_SCHEMA
    assert checkpoint["objective"]["structure_weight"] == .1
    assert checkpoint["historical_parent"] == bundle.parent
    assert checkpoint["historical_parent"] is not bundle.parent
    assert checkpoint["historical_parent_sha256"] == digest(bundle.parent)
    assert set(checkpoint["state"]) == {"model_state", "optimizer_state"}
    assert checkpoint["state"] == {key: base[key] for key in ("model_state", "optimizer_state")}
    assert set(checkpoint["state"]["optimizer_state"]["parameters"]) == set(base["model_state"])
    assert all(moment["step"] == 400 for moment in checkpoint["state"]["optimizer_state"]["parameters"].values())
    assert checkpoint["progress"] == {"inherited_optimizer_steps": 400, "new_optimizer_steps": 0,
        "absolute_optimizer_steps": 400, "epochs_completed": 4, "row_cursor": 192}
    assert checkpoint["previous_checkpoint_sha256"] is None
    assert checkpoint["initial_model_state_sha256"] == digest(base["model_state"])
    assert checkpoint["initial_optimizer_state_sha256"] == digest(base["optimizer_state"])
    assert checkpoint["initialization"]["fresh_optimizer"] is False
    assert checkpoint["initialization"]["parent_optimizer_moments_transferred"] is True
    assert checkpoint["initialization"]["parent_epoch_and_cursor_transferred"] is True
    assert all(checkpoint[key] is False for key in FALSE)
    assert not ({"canonical_ir", "source_text", "labels", "tokens", "latent"} & all_keys(checkpoint))
    assert sum(len(rows) for rows in bundle.geometry_calls) == 1152 + 96
    assert max(map(len, bundle.geometry_calls)) <= 32
    detached = bundle.subject.validate_checkpoint(checkpoint)
    assert detached == checkpoint and detached is not checkpoint
    assert before == (digest(bundle.parent), digest(bundle.train), digest(bundle.tune))


def test_prepared_nested_model_moments_history_and_progress_are_detached(bundle):
    before = digest(bundle.parent), digest(bundle.train), digest(bundle.tune)
    checkpoint = prepare(bundle)
    checkpoint["state"]["model_state"]["modality.bias"][0] = 999.
    checkpoint["state"]["optimizer_state"]["parameters"]["modality.bias"]["exp_avg"][0] = 999.
    checkpoint["historical_parent"]["base_checkpoint"]["model_state"]["modality.bias"][0] = 999.
    checkpoint["progress"]["row_cursor"] = 0
    assert before == (digest(bundle.parent), digest(bundle.train), digest(bundle.tune))


@pytest.mark.parametrize("change", ["outer_extra", "outer_missing", "legacy_schema", "legacy_lineage",
    "state_extra", "state_schema", "objective_extra", "objective_hinge", "history_extra",
    "history_hash", "progress_extra", "absolute_counter", "new_counter", "cursor", "epoch",
    "moment_step", "moment_missing", "negative_squared_moment", "authority"])
def test_checkpoint_schema_objective_counters_and_moments_are_closed(bundle, change):
    checkpoint = prepare(bundle, structure_weight=.1)
    moment = checkpoint["state"]["optimizer_state"]["parameters"]["modality.bias"]
    if change == "outer_extra":
        checkpoint["test_gold"] = True
    elif change == "outer_missing":
        del checkpoint["initial_optimizer_state_sha256"]
    elif change == "legacy_schema":
        checkpoint["schema"] = "warm-start-span-legal-formula-checkpoint/v1"
    elif change == "legacy_lineage":
        checkpoint["lineage_id"] = "warm_start_source_span_formula_v1"
    elif change == "state_extra":
        checkpoint["state"]["canonical_ir"] = {"rules": []}
    elif change == "state_schema":
        checkpoint["state"]["schema"] = "span-legal-formula-checkpoint/v1"
    elif change == "objective_extra":
        checkpoint["objective"]["hinge_margin"] = .1
    elif change == "objective_hinge":
        checkpoint["objective"]["schema"] = "source-span-order-overlap-hinge/v1"
    elif change == "history_extra":
        checkpoint["historical_parent"]["extra"] = None
    elif change == "history_hash":
        checkpoint["historical_parent_sha256"] = "0" * 64
    elif change == "progress_extra":
        checkpoint["progress"]["teacher_steps"] = 1
    elif change == "absolute_counter":
        checkpoint["progress"]["absolute_optimizer_steps"] = 399
    elif change == "new_counter":
        checkpoint["progress"]["new_optimizer_steps"] = True
    elif change == "cursor":
        checkpoint["progress"]["row_cursor"] = 193
    elif change == "epoch":
        checkpoint["progress"]["epochs_completed"] = 0
    elif change == "moment_step":
        moment["step"] = 0
    elif change == "moment_missing":
        del checkpoint["state"]["optimizer_state"]["parameters"]["modality.bias"]
    elif change == "negative_squared_moment":
        moment["exp_avg_sq"][0] = -.1
    else:
        checkpoint["qualified"] = True
    with pytest.raises(ValueError):
        bundle.subject.validate_checkpoint(checkpoint)


@pytest.mark.parametrize("owner", ["span", "warm"])
def test_live_owner_source_hash_drift_is_rejected_without_restoration(bundle, monkeypatch, owner):
    checkpoint = prepare(bundle)
    module = getattr(bundle, owner)
    changed = deepcopy(module._implementation())
    changed["span" if owner == "span" else "continuation_sha256"] = "0" * 64
    monkeypatch.setattr(module, "_implementation", lambda: deepcopy(changed))
    with pytest.raises(ValueError, match="(?i)(implementation|owner|source)"):
        bundle.subject.validate_checkpoint(checkpoint)


@pytest.mark.parametrize("location", ["outer", "base", "source"])
def test_reauthenticated_parent_still_requires_each_pinned_implementation(bundle, location):
    if location == "outer":
        bundle.parent["implementation"]["continuation_sha256"] = "0" * 64
    elif location == "base":
        bundle.parent["base_checkpoint"]["implementation"]["span"] = "0" * 64
    else:
        source = bundle.parent["source_parent_checkpoint"]
        source["implementation"]["span"] = "0" * 64
        bundle.parent["source_parent_checkpoint_sha256"] = digest(source)
    with pytest.raises(ValueError, match="(?i)(owner|implementation|source)"):
        prepare(bundle)


def test_preexisting_warm_lineage_cannot_be_reinitialized_at_zero(bundle):
    base = bundle.parent["base_checkpoint"]
    base["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    base["optimizer_state"]["parameters"] = {}
    with pytest.raises(ValueError, match="(?i)(400|boundary|Adam)"):
        prepare(bundle)


def test_paired_objectives_share_the_exact_next_32_deterministic_batches(bundle):
    ce = prepare(bundle, structure_weight=0.)
    structured = prepare(bundle, structure_weight=.1)
    before = digest(ce), digest(structured), digest(bundle.train)
    order = list(range(1152))
    random.Random(1733).shuffle(order)
    expected = [[bundle.train[index]["id"] for index in order[offset:offset + 12]]
                for offset in range(192, 576, 12)]
    ce_batches = bundle.subject.next_batch_ids(ce, bundle.train, steps=32)
    structured_batches = bundle.subject.next_batch_ids(structured, bundle.train, steps=32)
    assert ce_batches == structured_batches == expected
    assert len(ce_batches) == 32 and all(len(batch) == 12 for batch in ce_batches)
    assert len({identifier for batch in ce_batches for identifier in batch}) == 384
    assert bundle.subject.next_batch_ids(ce, bundle.train, steps=0) == []
    assert before == (digest(ce), digest(structured), digest(bundle.train))


@pytest.mark.parametrize("steps", [-1, 33, True, 1.5])
def test_pure_schedule_rejects_invalid_new_step_bounds(bundle, steps):
    with pytest.raises(ValueError, match="(?i)(step|bound)"):
        bundle.subject.next_batch_ids(prepare(bundle), bundle.train, steps=steps)


@pytest.mark.parametrize("legacy_file,validator", [
    ("legal_span_formula.py", "_restore"), ("legal_span_continuation.py", "_validated")])
def test_actual_legacy_loader_metadata_guards_reject_the_new_outer_without_importing_owners(
        bundle, monkeypatch, legacy_file, validator):
    fence_imports(monkeypatch)
    checkpoint = prepare(bundle)
    owner_path = SOURCE.parents[3] / "optimizers/logic_theorem_optimizer" / legacy_file
    tree = ast.parse(owner_path.read_text())
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == validator)
    fields_index = next(index for index, item in enumerate(function.body)
        if isinstance(item, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "fields" for name in item.targets))
    # Execute only the real closed-field assignment and rejection guard. The
    # restore function's Torch import and every model operation are excluded.
    guard = ast.Module(body=function.body[fields_index:fields_index + 2], type_ignores=[])
    with pytest.raises(ValueError, match="closed"):
        exec(compile(guard, str(owner_path), "exec"), {"FALSE": FALSE, "checkpoint": checkpoint, "_require": require})


def test_32_fake_updates_report_new_and_absolute_counts_without_parent_mutation(bundle, monkeypatch):
    checkpoint = prepare(bundle, structure_weight=.1)
    before = digest(checkpoint), digest(bundle.parent), digest(bundle.train), digest(bundle.tune)
    backend = inert_backend(bundle, checkpoint)
    monkeypatch.setattr(bundle.subject.time, "monotonic", lambda: 0.)
    expected = bundle.subject.next_batch_ids(checkpoint, bundle.train, steps=32)
    result = bundle.subject.train_decoder(checkpoint, bundle.train, bundle.tune,
                                         max_steps=32, max_seconds=1.)
    updated, report = result["checkpoint"], result["report"]
    assert updated["schema"] == SCHEMA and updated["lineage_id"] == LINEAGE
    assert set(updated["state"]) == {"model_state", "optimizer_state"}
    assert updated["progress"] == {"inherited_optimizer_steps": 400, "new_optimizer_steps": 32,
        "absolute_optimizer_steps": 432, "epochs_completed": 4, "row_cursor": 576}
    assert updated["previous_checkpoint_sha256"] == digest(checkpoint)
    assert all(moment["step"] == 432 for moment in updated["state"]["optimizer_state"]["parameters"].values())
    assert updated["historical_parent"] == bundle.parent
    assert report["actual_new_updates"] == report["requested_new_updates"] == 32
    assert report["actual_TRAIN_rows"] == 384 and report["batch_ids"] == expected
    assert report["batch_ids_sha256"] == digest(expected)
    assert report["complete"] is True and report["stopped_reason"] == "step_limit"
    assert report["inherited_full_Adam_preserved_at_entry"] is True
    assert report["historical_parent_unchanged"] is True
    assert report["ambient_CPU_RNG_preserved"] is True
    assert report["tuning_used_for_updates"] is False
    assert report["targets_embedded_in_new_state"] is False
    assert report["changed_parameter_names"] == ["modality.bias"]
    assert backend.optimizer.steps == backend.model.forward_calls == 32
    assert backend.objective_calls == [(12, .1)] * 32
    assert len(report["batch_components"]) == 32
    assert all(component["weighted_structure"] == .025 for component in report["batch_components"])
    assert all(report[key] is False for key in FALSE)
    assert before == (digest(checkpoint), digest(bundle.parent), digest(bundle.train), digest(bundle.tune))
    with pytest.raises(ValueError, match="(?i)(32|step|bound)"):
        bundle.subject.train_decoder(updated, bundle.train, bundle.tune, max_steps=1, max_seconds=1.)


def test_deadline_before_first_batch_reports_zero_actual_updates_and_exact_state(bundle, monkeypatch):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint)
    before = digest(checkpoint), digest(bundle.parent)
    monkeypatch.setattr(bundle.subject.time, "monotonic", lambda: 10.)
    result = bundle.subject.train_decoder(checkpoint, bundle.train, bundle.tune,
                                         max_steps=32, max_seconds=0.)
    report = result["report"]
    assert result["checkpoint"] == checkpoint and result["checkpoint"] is not checkpoint
    assert report["requested_new_updates"] == 32 and report["actual_new_updates"] == 0
    assert report["actual_TRAIN_rows"] == 0 and report["batch_ids"] == []
    assert report["batch_components"] == [] and report["changed_parameter_names"] == []
    assert report["stopped_reason"] == "deadline_before_batch" and report["complete"] is False
    assert report["training_executed"] is False
    assert "before_each_batch" in report["deadline_scope"]
    assert backend.optimizer.steps == backend.model.forward_calls == 0
    assert before == (digest(checkpoint), digest(bundle.parent))


def test_deadline_between_fake_batches_preserves_the_committed_prefix(bundle, monkeypatch):
    checkpoint = prepare(bundle, structure_weight=.1)
    backend = inert_backend(bundle, checkpoint)
    readings = iter([0., 0., 0., 2., 2.])
    monkeypatch.setattr(bundle.subject.time, "monotonic", lambda: next(readings))
    result = bundle.subject.train_decoder(checkpoint, bundle.train, bundle.tune,
                                         max_steps=2, max_seconds=1.)
    report = result["report"]
    assert report["actual_new_updates"] == 1 and report["requested_new_updates"] == 2
    assert report["actual_TRAIN_rows"] == 12
    assert report["batch_ids"] == bundle.subject.next_batch_ids(checkpoint, bundle.train, steps=1)
    assert report["complete"] is False and report["stopped_reason"] == "deadline_before_batch"
    assert result["checkpoint"]["progress"] == {"inherited_optimizer_steps": 400,
        "new_optimizer_steps": 1, "absolute_optimizer_steps": 401, "epochs_completed": 4, "row_cursor": 204}
    assert backend.optimizer.steps == backend.model.forward_calls == 1
    assert result["checkpoint"]["historical_parent"] == checkpoint["historical_parent"]


def test_authored_tuning_evaluation_is_external_and_performs_no_fake_updates(bundle, monkeypatch):
    checkpoint = prepare(bundle, structure_weight=.1)
    backend = inert_backend(bundle, checkpoint)
    before = digest(checkpoint), digest(bundle.parent), digest(bundle.tune)
    monkeypatch.setattr(bundle.subject.time, "monotonic", lambda: 0.)
    result = bundle.subject.evaluate(checkpoint, bundle.tune, max_seconds=1.)
    assert result["rows_evaluated"] == result["expected_rows"] == 96
    assert result["complete"] is True and result["used_for_updates"] is False
    assert result["reference_access"] is True and result["teacher_forcing"] is True
    assert result["training_executed"] is False
    assert result["semantics"] == "exposed_authored_construction_targets_only"
    assert result["losses"]["ce"] == 1.25 and result["losses"]["weighted_structure"] == pytest.approx(.025)
    assert backend.objective_calls == [(12, .1)] * 8
    assert backend.optimizer.steps == 0 and backend.model.forward_calls == 8
    assert all(result[key] is False for key in FALSE)
    assert before == (digest(checkpoint), digest(bundle.parent), digest(bundle.tune))


def test_tuning_deadline_reports_unmeasured_losses_without_fabricated_completion(bundle, monkeypatch):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint)
    monkeypatch.setattr(bundle.subject.time, "monotonic", lambda: 10.)
    result = bundle.subject.evaluate(checkpoint, bundle.tune, max_seconds=0.)
    assert result["rows_evaluated"] == 0 and result["expected_rows"] == 96
    assert result["complete"] is False
    assert all(value is None for value in result["losses"].values())
    assert result["batch_components"] == []
    assert backend.model.forward_calls == backend.optimizer.steps == 0


def inference_rows(bundle):
    return [{key: deepcopy(row[key]) for key in ("id", "source_text", "latent")}
            for row in bundle.train[:2]]


@pytest.mark.parametrize("control", ["none", "zero", "disabled", "rotate"])
def test_target_free_inference_controls_and_scores_share_each_single_fake_forward(bundle, control):
    checkpoint = prepare(bundle, structure_weight=.1)
    backend = inert_backend(bundle, checkpoint)
    runtime = bundle.subject.open_checkpoint(checkpoint)
    source = inference_rows(bundle)
    before = digest(source), digest(checkpoint), digest(bundle.parent)
    result = runtime.infer(source, control=control)
    assert result["schema"] == "objective-resumed-source-span-inference/v1"
    assert result["lineage_id"] == LINEAGE
    assert result["actual_source_forwards"] == 2 and result["additional_model_forwards"] == 0
    assert result["same_forward_scores"] is True
    assert result["target_access"] is result["teacher_forcing"] is result["training_executed"] is False
    assert result["optimizer_updates"] == 0 and result["legal_accuracy"] is None
    assert result["weights_unchanged"] is result["optimizer_moments_unchanged"] is True
    assert result["native_encoder_executed"] is result["family_bridge_admitted"] is False
    assert result["Lake_executed"] is False
    assert backend.model.forward_calls == 2 and backend.optimizer.steps == 0
    assert backend.model.removed_hooks == 1 and backend.model._forward_hooks == {}
    assert all(result[key] is False for key in FALSE)
    for position, row in enumerate(result["rows"]):
        donor = (position + 1) % 2 if control == "rotate" else position
        effective = [0.] * 384 if control == "zero" else source[donor]["latent"]
        assert row["id"] == source[position]["id"]
        assert row["latent_donor_id"] == source[donor]["id"] and row["latent_donor_position"] == donor
        assert row["effective_latent_sha256"] == digest(effective)
        assert backend.decode_calls[position] == {"text": source[position]["source_text"],
                                                  "latent": effective, "enabled": control != "disabled"}
        assert row["scores"]["schema"] == "joint-source-span-scores/v1"
        assert set(row["scores"]["start_logits"]) == set(("actor", "action", "object", "conditions", "exceptions", "temporal"))
        assert len(row["scores"]["tokens"]) == 3
    assert before == (digest(source), digest(checkpoint), digest(bundle.parent))
    runtime_copy = runtime.checkpoint
    runtime_copy["state"]["model_state"]["modality.bias"][0] = 999.
    assert runtime.checkpoint == checkpoint


def test_inference_without_score_capture_installs_no_hook_or_additional_forward(bundle):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint)
    result = bundle.subject.open_checkpoint(checkpoint).infer(inference_rows(bundle), capture_scores=False)
    assert result["same_forward_scores"] is False
    assert all(row["scores"] is None for row in result["rows"])
    assert backend.model.forward_calls == 2
    assert backend.model.removed_hooks == 0 and backend.model._forward_hooks == {}


@pytest.mark.parametrize("extra", ["canonical_ir", "target", "labels", "gold", "embedding"])
def test_target_reference_and_uncontracted_fields_are_rejected_before_fake_forward(bundle, extra):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint)
    runtime = bundle.subject.open_checkpoint(checkpoint)
    source = inference_rows(bundle)
    source[0][extra] = {"diagnostic": True}
    with pytest.raises(ValueError, match="target-free"):
        runtime.infer(source)
    assert backend.model.forward_calls == backend.optimizer.steps == 0
    assert backend.model._forward_hooks == {}


@pytest.mark.parametrize("change", ["duplicate_id", "empty_text", "wrong_latent", "one_row_rotate",
                                       "unknown_control", "nonboolean_capture"])
def test_inference_input_geometry_and_controls_are_closed(bundle, change):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint)
    runtime = bundle.subject.open_checkpoint(checkpoint)
    source, options = inference_rows(bundle), {}
    if change == "duplicate_id":
        source[1]["id"] = source[0]["id"]
    elif change == "empty_text":
        source[0]["source_text"] = "  "
    elif change == "wrong_latent":
        source[0]["latent"] = [0.] * 383
    elif change == "one_row_rotate":
        source, options = source[:1], {"control": "rotate"}
    elif change == "unknown_control":
        options["control"] = "teacher"
    else:
        options["capture_scores"] = 1
    with pytest.raises(ValueError):
        runtime.infer(source, **options)
    assert backend.model.forward_calls == backend.optimizer.steps == 0
    assert backend.model._forward_hooks == {}


@pytest.mark.parametrize("failure", ["decoder", "score_geometry", "missing_forward"])
def test_temporary_capture_hooks_are_removed_on_every_inference_failure(bundle, monkeypatch, failure):
    checkpoint = prepare(bundle)
    backend = inert_backend(bundle, checkpoint, fail_decode=failure == "decoder")
    runtime = bundle.subject.open_checkpoint(checkpoint)
    if failure == "score_geometry":
        monkeypatch.setattr(FakeScores, "dtype", "torch.float64")
    elif failure == "missing_forward":
        monkeypatch.setattr(bundle.span.SpanLegalFormulaDecoder, "_decode",
            lambda *args, **kwargs: {"reason": "inert_without_forward", "status": "abstained"})
    with pytest.raises((RuntimeError, ValueError)):
        runtime.infer(inference_rows(bundle))
    assert backend.model._forward_hooks == {} and backend.model._forward_pre_hooks == {}
    assert backend.model.removed_hooks == 1 and backend.optimizer.steps == 0
    assert runtime.checkpoint == checkpoint
