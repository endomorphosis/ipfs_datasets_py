"""Detached exact-source contracts; no numerical owner or plugin is imported.

The source is compiled with imports stripped and explicit inert owners supplied.
The tiny fake tensors exercise routing and analytic derivatives, not a numerical
training runtime. Integration parity and bounded training belong to the guardian.
"""
import ast
import builtins
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[4] / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py"
SPLIT = SOURCE.with_name("legal_span_split_features.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def deny_import(name, *args, **kwargs):
    raise AssertionError("Detached contracts cannot import: " + name)


def owner_namespace():
    previous = {}
    selected = {"ORIGINAL_PARAMETER_NAMES", "FEATURE_PARAMETER_NAMES", "SPLIT_FEATURE_PARAMETER_NAMES", "LATENT_PARAMETER_NAMES", "MODEL_PARAMETER_NAMES"}
    for node in ast.parse(SPLIT.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in selected for t in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPLIT) + "#constants", "exec"), previous)
    names = previous["MODEL_PARAMETER_NAMES"]
    span = SimpleNamespace(
        FALSE=dict.fromkeys(("admitted", "formalized", "promotion_performed", "proof_authority", "publication_performed", "qualified", "roundtrip_ok", "semantic_correctness_verified"), False),
        _require=require, _raw=raw, checkpoint_digest=digest, _SHA=re.compile(r"[0-9a-f]{64}"),
        OPTIONAL_FIELDS=("object", "conditions", "exceptions", "temporal"),
        SPAN_FIELDS=("actor", "action", "object", "conditions", "exceptions", "temporal"),
        _implementation=lambda: {"inert": "span"})

    def progress(value):
        require(type(value) is dict and set(value) == {"optimizer_steps", "epochs_completed", "row_cursor"}
                and all(type(v) is int and v >= 0 for v in value.values()), "progress")
        return dict(value)

    def batch_indices(count, value, batch_size, seed):
        value = progress(value)
        require(value["row_cursor"] < count and value["row_cursor"] % batch_size == 0
                and value["optimizer_steps"] == value["epochs_completed"] * 14 + value["row_cursor"] // batch_size, "cursor")
        return list(range(value["row_cursor"], value["row_cursor"] + batch_size))

    def bounded(rows, tuning):
        require(len(rows) == 168 and not tuning, "training only")
        return [dict(id=r["id"], source_text=r["source_text"], labels=dict(presence=[True, True, False, False, False, r["temporal"]])) for r in rows], []

    def base_diagnostic(value):
        require(value == {"total_loss": 2.}, "inert base diagnostic")

    targeted = SimpleNamespace(MAX_BYTES=64 * 1024 * 1024, LEGACY96_SHA256="d" * 64,
        _policy=lambda seed, **kw: dict(seed=seed, **kw), _implementation=lambda: {"inert": "targeted"},
        _progress=progress, _batch_indices=batch_indices, _bounded_splits=bounded,
        _validate_objective_diagnostics=base_diagnostic)
    split = SimpleNamespace(MODEL_PARAMETER_NAMES=names, _implementation=lambda: {"inert": "split"},
        _validated=lambda source: require(set(source["model_state"]) == set(names), "source34"),
        _branch_digests=lambda state: dict.fromkeys(("modality_feature_state_sha256", "span_feature_state_sha256",
            "modality_path_state_sha256", "span_path_state_sha256", "dormant_latent_state_sha256"), digest(state)))
    continuation = SimpleNamespace(_implementation=lambda: {"inert": "continuation"}, _context_contract=lambda value: copy.deepcopy(value))
    namespace = dict(__file__=str(SOURCE), __name__="inert_temporal_attention", copy=copy, hashlib=hashlib,
        json=json, math=math, Path=Path, split=split, targeted=targeted, continuation=continuation, span=span)
    namespace["__builtins__"] = dict(vars(builtins), __import__=deny_import)
    body = [node for node in ast.parse(SOURCE.read_bytes()).body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE) + "#inert-owner-execution", "exec"), namespace)
    return namespace


def fixture(namespace):
    state = {name: [[float(i)]] for i, name in enumerate(namespace["BASE_PARAMETER_NAMES"])}
    state["presence.weight"] = [[float(i + j) / 100 for j in range(64)] for i in range(8)]
    state["presence.bias"] = [float(i) / 10 for i in range(8)]
    rows = [dict(id="train-" + str(i), source_text="source " + str(i), temporal=i % 2 == 0) for i in range(168)]
    context = dict(mode="source-only", dimension=384)
    child = dict(context_contract=context, context_contract_sha256=digest(context))
    source = dict(model_state=state, progress=dict(optimizer_steps=32),
        config=dict(hidden_size=32, latent_dimension=384, latent_enabled=False),
        initial_continuation_checkpoint=child, training_manifest_sha256=digest(rows),
        source_parent_checkpoint_sha256="a" * 64, source_parent_model_state_sha256="b" * 64)
    # The real immutable constants have a separate contract. Inert synthetic
    # owners permit exercising the actual closed provenance checks here.
    namespace["SOURCE_SPLIT_SHA256"] = digest(source)
    namespace["SOURCE_SPLIT_MODEL_SHA256"] = digest(state)
    checkpoint = namespace["build_checkpoint"](source, rows, (), context_contract=context)
    return source, rows, checkpoint


def moments(namespace, step):
    def zeros(shape):
        return [zeros(shape[1:]) for _ in range(shape[0])] if shape else 0.
    return dict(schema="adam-default-betas-eps/v1", parameters={name: dict(step=step,
        exp_avg=zeros(shape), exp_avg_sq=zeros(shape)) for name, shape in namespace["_trainable_shapes"]().items()})


class Dual:
    """A single analytic derivative coordinate for the inert forward contract."""
    def __init__(self, value, gradient=0.):
        self.value, self.gradient = float(value), float(gradient)

    def __float__(self):
        return self.value

    def detach(self):
        return self

    def __add__(self, other):
        other = as_dual(other)
        return Dual(self.value + other.value, self.gradient + other.gradient)

    __radd__ = __add__

    def __neg__(self):
        return Dual(-self.value, -self.gradient)

    def __sub__(self, other):
        return self + -as_dual(other)

    def __rsub__(self, other):
        return as_dual(other) + -self

    def __mul__(self, other):
        other = as_dual(other)
        return Dual(self.value * other.value, self.gradient * other.value + self.value * other.gradient)

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = as_dual(other)
        return Dual(self.value / other.value,
            (self.gradient * other.value - self.value * other.gradient) / (other.value * other.value))


def as_dual(value):
    return value if isinstance(value, Dual) else Dual(value)


class Bits:
    def __init__(self, values):
        self.values = values

    def all(self):
        return all(self.values)


class Array:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return Array(self.values[index])

    def flat(self):
        return [v for row in self.values for v in row] if self.values and isinstance(self.values[0], list) else self.values

    def isfinite(self):
        return Bits([math.isfinite(v) for v in self.flat()])

    def __eq__(self, other):
        return Bits([v == other for v in self.flat()])


class Parameter:
    def __init__(self, pointer, shape=(1,)):
        self.pointer, self.shape = pointer, shape
        self.grad, self.requires_grad = "unconfigured", None

    def untyped_storage(self):
        return SimpleNamespace(data_ptr=lambda: self.pointer)

    def numel(self):
        return math.prod(self.shape)

    def requires_grad_(self, value):
        self.requires_grad = value


class Tensor:
    """Flat-list tensor implementing only operations used by the extracted forward."""
    def __init__(self, values, shape, *, contiguous=False):
        self.values, self.shape, self.was_contiguous = list(values), tuple(shape), contiguous
        assert len(self.values) == math.prod(self.shape)

    def positions(self):
        return itertools.product(*(range(size) for size in self.shape))

    def at(self, position):
        offset = 0
        for size, index in zip(self.shape, position, strict=True):
            offset = offset * size + index
        return self.values[offset]

    def __getitem__(self, indices):
        indices = indices if isinstance(indices, tuple) else (indices,)
        if Ellipsis in indices:
            position = indices.index(Ellipsis)
            indices = indices[:position] + (slice(None),) * (len(self.shape) - sum(index is not None and index is not Ellipsis for index in indices)) + indices[position + 1:]
        missing = len(self.shape) - sum(index is not None for index in indices)
        indices += (slice(None),) * missing
        choices, shape, dimension = [], [], 0
        for index in indices:
            if index is None:
                choices.append([None]); shape.append(1)
            elif isinstance(index, slice):
                choice = list(range(self.shape[dimension]))[index]
                choices.append(choice); shape.append(len(choice)); dimension += 1
            else:
                choices.append([index]); dimension += 1
        values = [self.at(tuple(index for index in position if index is not None)) for position in itertools.product(*choices)]
        return Tensor(values, shape)

    def binary(self, other, operation):
        if not isinstance(other, Tensor):
            return Tensor([operation(value, other) for value in self.values], self.shape)
        rank = max(len(self.shape), len(other.shape))
        left, right = (1,) * (rank - len(self.shape)) + self.shape, (1,) * (rank - len(other.shape)) + other.shape
        assert all(a == b or a == 1 or b == 1 for a, b in zip(left, right, strict=True))
        shape = tuple(max(a, b) for a, b in zip(left, right, strict=True))
        values = []
        for position in itertools.product(*(range(size) for size in shape)):
            a = tuple(0 if size == 1 else index for size, index in zip(left, position, strict=True))
            b = tuple(0 if size == 1 else index for size, index in zip(right, position, strict=True))
            values.append(operation(self.at(a[rank - len(self.shape):]), other.at(b[rank - len(other.shape):])))
        return Tensor(values, shape)

    def __mul__(self, other):
        return self.binary(other, lambda a, b: a * b)

    def __truediv__(self, other):
        return self.binary(other, lambda a, b: a / b)

    def __add__(self, other):
        return self.binary(other, lambda a, b: a + b)

    def __invert__(self):
        return Tensor([not value for value in self.values], self.shape)

    def sum(self, dimension):
        dimension %= len(self.shape)
        shape = self.shape[:dimension] + self.shape[dimension + 1:]
        values = []
        for position in itertools.product(*(range(size) for size in shape)):
            values.append(sum(self.at(position[:dimension] + (index,) + position[dimension:]) for index in range(self.shape[dimension])))
        return Tensor(values, shape)

    def reshape(self, *shape):
        shape = tuple(len(self.values) // math.prod(x for x in shape if x != -1) if size == -1 else size for size in shape)
        return Tensor(self.values, shape)

    def transpose(self, first, second):
        shape = list(self.shape); shape[first], shape[second] = shape[second], shape[first]
        values = []
        for position in itertools.product(*(range(size) for size in shape)):
            old = list(position); old[first], old[second] = old[second], old[first]
            values.append(self.at(old))
        return Tensor(values, shape)

    def masked_fill(self, mask, value):
        return self.binary(mask, lambda a, masked: value if masked else a)

    def contiguous(self):
        return Tensor(self.values, self.shape, contiguous=True)


class NoGrad:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def fake_forward(namespace, *, query_value=0., attention_weight=0., uniform=False, training=False):
    tree = ast.parse(SOURCE.read_bytes())
    model = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_model")
    cls = next(node for node in model.body if isinstance(node, ast.ClassDef))
    forward = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "forward")
    local = dict(namespace)
    exec(compile(ast.Module(body=[forward], type_ignores=[]), str(SOURCE) + "#fake-forward", "exec"), local)
    calls, projections, observed_probabilities = [], [], []

    def linear(value, weight, bias):
        assert value.shape[-1] == weight.shape[-1]
        projections.append((value.shape, weight.shape, bias is not None, weight.was_contiguous))
        rows, width, outputs = value.shape[0], value.shape[1], weight.shape[0]
        values = [sum(value.at((row, index)) * weight.at((output, index)) for index in range(width)) +
                  (bias.at((output,)) if bias is not None else 0.) for row in range(rows) for output in range(outputs)]
        return Tensor(values, (rows, outputs))

    def softmax(value, dim):
        assert dim == 1 and len(value.shape) == 2
        values = []
        for row in range(value.shape[0]):
            scores = [as_dual(value.at((row, index))) for index in range(value.shape[1])]
            shift = max(score.value for score in scores)
            exponentials = [Dual(math.exp(score.value - shift), math.exp(score.value - shift) * score.gradient) for score in scores]
            denominator = sum(exponentials)
            values.extend(score / denominator for score in exponentials)
        result = Tensor(values, value.shape)
        observed_probabilities.append([float(value) for value in result.values])
        return result

    def cat(values, dim):
        assert dim == 1 and values[0].shape[0] == 1
        return Tensor([item for value in values for item in value.values],
            (1, sum(value.shape[1] for value in values), values[0].shape[2]))

    torch = SimpleNamespace(no_grad=NoGrad, softmax=softmax, cat=cat,
        zeros_like=lambda value: Tensor([0.] * len(value.values), value.shape),
        nn=SimpleNamespace(functional=SimpleNamespace(linear=linear)))
    encoded = Tensor([value if index == 0 else 0. for value in (1., 3., 999.) for index in range(64)], (1, 3, 64))
    mask = Tensor([True, True, False], (1, 3))
    query = Tensor([Dual(query_value, 1.)] + [Dual(0.)] * 63, (64,))
    weights = Tensor([(.5 if column == 0 else attention_weight if column == 64 and row >= 6 else 0.)
        for row in range(8) for column in range(128)], (8, 128))
    old_head = Tensor([1., 2., 3., 4., 5., 6., 7., 8.], (1, 8))
    boundary = Tensor([float(index) for index in range(18)], (1, 3, 6))

    def features(*args):
        calls.append(args[-1])
        return encoded, mask

    owner = SimpleNamespace(_features=features, modality=lambda value: Tensor([1., 2., 3.], (1, 3)),
        presence=lambda value: old_head, start=lambda value: boundary, end=lambda value: boundary,
        temporal_attention=SimpleNamespace(query=query), temporal_presence=SimpleNamespace(weight=weights, bias=Tensor([0.] * 8, (8,))),
        _attention_control="uniform" if uniform else "learned", training=training,
        _temporal_forward_accounting=dict.fromkeys(("source_model_forwards", "modality_encoder_forwards", "span_encoder_forwards",
            "original_presence_head_forwards", "attention_pool_forwards", "temporal_mean_projection_forwards", "temporal_attention_projection_forwards"), 0))
    local["torch"] = torch
    output = local["forward"](owner, None, None, Tensor([2.], (1,)), None)
    return output, calls, projections, observed_probabilities, owner


class TemporalAttentionContracts(unittest.TestCase):
    def setUp(self):
        self.ns = owner_namespace()

    def test_real_constants_closed_partition_and_exact_scalar_counts(self):
        namespace = self.ns
        self.assertEqual(namespace["SOURCE_SPLIT_SHA256"], "95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035")
        self.assertEqual(namespace["SOURCE_SPLIT_MODEL_SHA256"], "fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5")
        self.assertEqual(namespace["SCHEMA"], "bounded-temporal-attention-adapter-checkpoint/v1")
        partition = namespace["_partition"]()
        self.assertEqual(len(partition["model_parameter_names"]), 37)
        self.assertEqual(len(partition["frozen_parameter_names"]), 34)
        self.assertEqual(partition["optimizer_parameter_order"], ["temporal_attention.query", "temporal_presence.weight", "temporal_presence.bias"])
        self.assertEqual(partition["inactive_head_rows"], list(range(6)))
        self.assertEqual(partition["stored_trainable_scalar_count"], 64 + 8 * 128 + 8)
        self.assertEqual(partition["active_trainable_scalar_count"], 64 + 2 * 128 + 2)

    def test_initial_state_copies_mean_and_bias_and_zeros_query_attention(self):
        namespace = self.ns
        source, _, checkpoint = fixture(namespace)
        state = checkpoint["model_state"]
        self.assertEqual(state["temporal_attention.query"], [0.] * 64)
        self.assertEqual(state["temporal_presence.bias"], source["model_state"]["presence.bias"])
        for row, parent in zip(state["temporal_presence.weight"], source["model_state"]["presence.weight"], strict=True):
            self.assertEqual(row[:64], parent)
            self.assertEqual(row[64:], [0.] * 64)
        state["temporal_presence.weight"][0][0] = 999.
        self.assertNotEqual(state["temporal_presence.weight"][0][0], source["model_state"]["presence.weight"][0][0])
        self.assertNotEqual(state["temporal_presence.weight"][0][0], state["presence.weight"][0][0])
        for malformed in ({}, dict(source["model_state"], extra=[0.])):
            with self.subTest(malformed=bool(malformed)), self.assertRaises(ValueError):
                namespace["_initial_state"](malformed)

    def test_fixed_unchanged_ce_policy_and_no_margin_or_extra_objective(self):
        namespace = self.ns
        policy = namespace["_policy"]("temporal-attention-ce")
        self.assertEqual(namespace["_validate_policy"](policy), policy)
        self.assertEqual(policy["objective_policy"]["presence_ce_weight"], 1)
        self.assertFalse(policy["objective_policy"]["actor_ranking_enabled"])
        self.assertNotIn("margin", policy)
        self.assertNotIn("anchor_factors", policy)
        for mutate in (lambda p: p.update(extra=True), lambda p: p.update(evaluation_references_used=True),
                       lambda p: p["optimizer"].update(weight_decay=.01), lambda p: p["attention"].update(valid_tokens_only=False)):
            bad = copy.deepcopy(policy); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validate_policy"](bad)
        for kwargs in (dict(objective="temporal-ce-control"), dict(objective="temporal-anchor-margin"),
                       dict(objective="temporal-attention-ce", seed=True), dict(objective="temporal-attention-ce", batch_size=13)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                namespace["_policy"](**kwargs)

    def test_closed_source_training_context_and_checkpoint_provenance(self):
        namespace = self.ns
        source, rows, checkpoint = fixture(namespace)
        namespace["_validated"](checkpoint)
        for mutate in (lambda c: c.update(source_split_checkpoint_sha256="e" * 64),
                       lambda c: c.update(training_manifest_sha256="e" * 64), lambda c: c.update(tuning_count=96),
                       lambda c: c.update(legacy_prefix_sha256="e" * 64), lambda c: c.update(extra=True),
                       lambda c: c["source_split_checkpoint"]["progress"].update(optimizer_steps=31),
                       lambda c: c["config"].update(latent_enabled=True), lambda c: c.update(source_split_optimizer_steps=400),
                       lambda c: c["temporal_adapter_source_state_map"].update({"temporal_attention.query": "presence.weight"})):
            bad = copy.deepcopy(checkpoint); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validated"](bad)
        with self.assertRaises(ValueError):
            namespace["build_checkpoint"](source, list(reversed(rows)), (), context_contract=checkpoint["context_contract"])
        with self.assertRaises(ValueError):
            namespace["build_checkpoint"](source, rows, [dict(reference=True)], context_contract=checkpoint["context_contract"])
        with self.assertRaises(ValueError):
            namespace["build_checkpoint"](source, rows, (), context_contract=dict(wrong=True))

    def trained_fixture(self):
        namespace = self.ns
        _, _, checkpoint = fixture(namespace)
        trained = copy.deepcopy(checkpoint)
        trained["parent_checkpoint_sha256"] = digest(checkpoint)
        trained["progress"] = dict(optimizer_steps=1, epochs_completed=0, row_cursor=12)
        trained["optimizer_state"] = moments(namespace, 1)
        trained["model_state"]["temporal_presence.bias"][7] += .01
        return checkpoint, trained

    def test_zero_step_initialization_rejects_signed_zero_and_equal_integer_mutations(self):
        namespace = self.ns
        source, rows, _ = fixture(namespace)
        source["model_state"]["presence.weight"][6][0] = 0.
        source["model_state"]["presence.bias"][6] = 0.
        namespace["SOURCE_SPLIT_SHA256"] = digest(source)
        namespace["SOURCE_SPLIT_MODEL_SHA256"] = digest(source["model_state"])
        checkpoint = namespace["build_checkpoint"](source, rows, (),
            context_contract=source["initial_continuation_checkpoint"]["context_contract"])
        namespace["_validated"](checkpoint)
        mutations = (
            lambda state: state["temporal_attention.query"].__setitem__(0, -0.),
            lambda state: state["temporal_attention.query"].__setitem__(0, 0),
            lambda state: state["temporal_presence.weight"][6].__setitem__(64, -0.),
            lambda state: state["temporal_presence.weight"][6].__setitem__(0, -0.),
            lambda state: state["temporal_presence.bias"].__setitem__(6, -0.),
        )
        for mutate in mutations:
            bad = copy.deepcopy(checkpoint)
            mutate(bad["model_state"])
            self.assertEqual(bad["model_state"], checkpoint["model_state"])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validated"](bad)

    def test_dormant_placeholder_parity_rejects_opposite_signed_zero_scores(self):
        namespace = self.ns
        writes = []
        def capture(*args, control="none", **kwargs):
            value = -0. if control == "disabled" else 0.
            return dict(occurrences=[dict(scores=dict(temporal=[value])) for _ in range(2)],
                        inference=dict(rows=[dict(status="decoded") for _ in range(2)]))
        namespace["captured_inference"] = capture
        namespace["_write_artifact"] = lambda path, value: writes.append(str(path)) or dict(path=str(path))
        rows = [dict(id=str(index), source_text="source", latent=[0.] * 384) for index in range(2)]
        with self.assertRaisesRegex(ValueError, "source-only scores changed"):
            namespace["source_only_parity"](None, None, None, {}, rows, Path("/inert"), "initial")
        self.assertEqual(len(writes), 2)

    def test_frozen_and_inactive_rows_both_blocks_are_immutable(self):
        namespace = self.ns
        checkpoint, trained = self.trained_fixture()
        namespace["_validated"](trained)
        self.assertEqual(namespace["_origin"](trained)["model_state"], checkpoint["model_state"])
        for name, row, column in ((namespace["BASE_PARAMETER_NAMES"][0], 0, 0),
                                   ("presence.weight", 7, 63), ("temporal_presence.weight", 0, 0),
                                   ("temporal_presence.weight", 5, 127), ("temporal_presence.bias", 5, None)):
            bad = copy.deepcopy(trained)
            if column is None:
                bad["model_state"][name][row] += .1
            else:
                bad["model_state"][name][row][column] += .1
            with self.subTest(name=name, row=row, column=column), self.assertRaises(ValueError):
                namespace["_validated"](bad)
        bad = copy.deepcopy(checkpoint); bad["model_state"]["temporal_presence.bias"][7] += .01
        with self.assertRaises(ValueError):
            namespace["_validated"](bad)

    def test_trainable_shape_scalar_and_adam_validation(self):
        namespace = self.ns
        _, trained = self.trained_fixture()
        for mutate in (lambda c: c["model_state"]["temporal_attention.query"].pop(),
                       lambda c: c["model_state"]["temporal_presence.weight"][7].pop(),
                       lambda c: c["model_state"]["temporal_presence.bias"].__setitem__(7, True),
                       lambda c: c["model_state"]["temporal_attention.query"].__setitem__(0, float("inf")),
                       lambda c: c["model_state"]["temporal_attention.query"].__setitem__(0, 1e39),
                       lambda c: c["optimizer_state"]["parameters"].pop("temporal_attention.query"),
                       lambda c: c["optimizer_state"]["parameters"]["temporal_presence.weight"]["exp_avg"][5].__setitem__(127, .1),
                       lambda c: c["optimizer_state"]["parameters"]["temporal_presence.bias"]["exp_avg_sq"].__setitem__(7, -.1),
                       lambda c: c["optimizer_state"]["parameters"]["temporal_attention.query"].update(step=2)):
            bad = copy.deepcopy(trained); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validated"](bad)
        with self.assertRaises(ValueError):
            namespace["_validate_optimizer_state"](moments(namespace, 1), 0)
        with self.assertRaises(ValueError):
            namespace["_validate_optimizer_state"](moments(namespace, 1), True)

    def test_parameters_have_exact_order_shapes_and_independent_storage(self):
        namespace = self.ns
        names, shapes = namespace["MODEL_PARAMETER_NAMES"], namespace["_trainable_shapes"]()
        params = {name: Parameter(i + 1, shapes.get(name, (1,))) for i, name in enumerate(names)}
        named, selected = namespace["_configure_parameters"](SimpleNamespace(named_parameters=lambda: list(params.items())))
        self.assertEqual(selected, [params[name] for name in namespace["TRAINABLE_PARAMETER_NAMES"]])
        self.assertTrue(all(parameter.grad is None for parameter in named.values()))
        self.assertEqual(sum(parameter.requires_grad for parameter in named.values()), 3)
        for shared in ("parameter", "storage", "order", "shape"):
            bad = dict(params)
            if shared == "parameter":
                bad[names[-1]] = bad[names[0]]
            elif shared == "storage":
                bad[names[-1]] = Parameter(1, (8,))
            elif shared == "order":
                bad = dict(reversed(list(bad.items())))
            else:
                bad["temporal_attention.query"] = Parameter(99, (65,))
            with self.subTest(shared=shared), self.assertRaises(ValueError):
                namespace["_configure_parameters"](SimpleNamespace(named_parameters=lambda: list(bad.items())))

    def test_gradients_freeze_both_inactive_blocks_and_first_query_zero(self):
        namespace = self.ns
        named = {name: Parameter(i) for i, name in enumerate(namespace["MODEL_PARAMETER_NAMES"])}
        for name, parameter in named.items():
            parameter.grad = None if name in namespace["BASE_PARAMETER_NAMES"] else Array([0.] * 64 if name.endswith("query") else [0.] * 6 + [1., -1.])
        optimizer = SimpleNamespace(state={named[name]: dict(exp_avg=Array([0.] * (64 if name.endswith("query") else 8)),
            exp_avg_sq=Array([0.] * (64 if name.endswith("query") else 8))) for name in namespace["TRAINABLE_PARAMETER_NAMES"]})
        namespace["_row_invariants"](named, optimizer, require_query_zero=True)
        named["temporal_attention.query"].grad = Array([.1] + [0.] * 63)
        namespace["_row_invariants"](named, optimizer)
        with self.assertRaises(ValueError):
            namespace["_row_invariants"](named, optimizer, require_query_zero=True)
        named["temporal_presence.weight"].grad = Array([[0.] * 128 for _ in range(8)])
        named["temporal_presence.weight"].grad.values[5][127] = .1
        with self.assertRaises(ValueError):
            namespace["_row_invariants"](named, optimizer)
        named["temporal_presence.weight"].grad.values[5][127] = 0.
        named[namespace["BASE_PARAMETER_NAMES"][0]].grad = Array([0.])
        with self.assertRaises(ValueError):
            namespace["_row_invariants"](named, optimizer)

    def test_authenticated_strata_and_training_only_labels(self):
        namespace = self.ns
        _, rows, _ = fixture(namespace)
        self.assertEqual(len(namespace["_training_records"](rows)), 168)
        self.assertEqual(namespace["_stratum"](95, True), "legacy_positive")
        self.assertEqual(namespace["_stratum"](96, False), "authored_negative")
        for index, present in ((True, True), (168, True), (-1, False), (1, 1)):
            with self.subTest(index=index, present=present), self.assertRaises(ValueError):
                namespace["_stratum"](index, present)
        bad = copy.deepcopy(rows); bad[0]["temporal"] = not bad[0]["temporal"]
        with self.assertRaises(ValueError):
            namespace["_training_records"](bad)

    def test_unchanged_objective_and_training_row_join(self):
        namespace = self.ns
        base = Dual(2., .25)
        seen = []
        namespace["targeted"]._loss = lambda torch, model, records, policy: (seen.append((model(), records, policy)) or (base, dict(total_loss=2.)))
        fake = SimpleNamespace(tensor=lambda value, **kwargs: value, long="inert-long",
            nn=SimpleNamespace(functional=SimpleNamespace(cross_entropy=lambda logits, target: Dual(.75))))
        class Presence:
            def __getitem__(self, index):
                self.last_index = index
                return "inert-logits"
        output = dict(presence=Presence())
        records = [dict(id="train-0", labels=dict(presence=[True, True, False, False, False, True])),
                   dict(id="train-96", labels=dict(presence=[True, True, False, False, False, False]))]
        policy = namespace["_policy"]("temporal-attention-ce")
        loss, details = namespace["_loss"](fake, output, records, [0, 96], policy)
        self.assertIs(loss, base)
        self.assertEqual(loss.gradient, .25)
        self.assertIs(seen[0][0], output)
        self.assertEqual(details["total_loss"], 2.)
        self.assertEqual([row["stratum"] for row in details["rows"]], ["legacy_positive", "authored_negative"])
        entry = dict(optimizer_step=1, indices=[0, 96], ids=[row["id"] for row in records], details=details)
        batch = dict(optimizer_step=1, indices=[0, 96], ids=entry["ids"], loss=2.)
        namespace["_validate_objective_entry"](entry, batch, policy)
        for mutate in (lambda e: e["details"].update(batch_denominator=1), lambda e: e["details"].update(total_loss=9.),
                       lambda e: e["details"].update(evaluation_references_used=True), lambda e: e.update(ids=["other", "train-96"]),
                       lambda e: e["details"]["rows"][0].update(stratum="authored_positive"),
                       lambda e: e["details"]["rows"][0].update(temporal_CE=float("nan"))):
            bad = copy.deepcopy(entry); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validate_objective_entry"](bad, batch, policy)

    def test_freeze_trace_binds_frozen_branches_inactive_blocks_and_first_query_gradient(self):
        namespace = self.ns
        _, _, checkpoint = fixture(namespace)
        branches = namespace["_branch_digests"](checkpoint["model_state"])
        batch = dict(optimizer_step=1, indices=[0], ids=["train-0"])
        entry = dict(**batch, frozen_before=namespace["SOURCE_SPLIT_MODEL_SHA256"],
            frozen_after=namespace["SOURCE_SPLIT_MODEL_SHA256"],
            inactive_before=branches["inactive_temporal_head_rows_sha256"],
            inactive_after=branches["inactive_temporal_head_rows_sha256"], frozen_head_sample_sha256="a" * 64,
            frozen_gradients_none=True, trainable_gradients_finite_nonNone=True, inactive_gradients_zero=True,
            inactive_moments_zero=True, changed_parameter_names=["temporal_presence.bias"], completed_returned_update=True,
            branch_digests_before=branches, branch_digests_after=copy.deepcopy(branches),
            attention_query_gradient_l2=0., attention_query_gradient_exact_zero=True)
        namespace["_validate_freeze_entry"](entry, batch)
        for mutate in (lambda e: e.update(frozen_after="e" * 64), lambda e: e.update(inactive_after="e" * 64),
                       lambda e: e.update(inactive_moments_zero=False), lambda e: e.update(changed_parameter_names=["presence.bias"]),
                       lambda e: e["branch_digests_after"].update(span_path_state_sha256="e" * 64),
                       lambda e: e["branch_digests_after"].update(attention_query_sha256="e" * 64),
                       lambda e: e.update(attention_query_gradient_l2=.1, attention_query_gradient_exact_zero=False),
                       lambda e: e.update(attention_query_gradient_l2=float("nan")), lambda e: e.update(optimizer_step=2)):
            bad = copy.deepcopy(entry); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                namespace["_validate_freeze_entry"](bad, batch)
        entry["optimizer_step"] = batch["optimizer_step"] = 2
        entry["attention_query_gradient_l2"] = .1
        entry["attention_query_gradient_exact_zero"] = False
        entry["branch_digests_after"]["attention_query_sha256"] = "e" * 64
        namespace["_validate_freeze_entry"](entry, batch)

    def test_training_call_budget_rejects_before_numerical_restore(self):
        namespace = self.ns
        for kwargs in (dict(max_steps=True), dict(max_steps=-1), dict(max_steps=33),
                       dict(max_seconds=True), dict(max_seconds=-1), dict(max_seconds=33), dict(max_seconds=float("nan"))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                namespace["train_decoder"]({}, [], **kwargs)
        _, trained = self.trained_fixture()
        namespace["time"] = SimpleNamespace(monotonic=lambda: 0.)
        _, rows, _ = fixture(namespace)
        with self.assertRaises(ValueError):
            namespace["train_decoder"](trained, rows, max_steps=32)

    def test_fake_forward_masks_padding_uses_two_encoders_and_parent_shaped_projections(self):
        output, calls, projections, probabilities, owner = fake_forward(self.ns)
        self.assertEqual(calls, [False, True])
        self.assertEqual(projections, [((1, 64), (8, 64), True, True), ((1, 64), (8, 64), False, True)])
        self.assertEqual(probabilities, [[.5, .5, 0.]])
        self.assertEqual([float(value) for value in output["presence"].values], [1., 2., 3., 4., 5., 6., 1., 1.])
        self.assertEqual(output["start"].shape, (1, 6, 3))
        self.assertEqual({owner._temporal_forward_accounting[key] for key in owner._temporal_forward_accounting}, {1})

    def test_first_query_gradient_zero_then_learnable_and_uniform_inference_ablation(self):
        initial, *_ = fake_forward(self.ns)
        self.assertTrue(all(as_dual(value).gradient == 0. for value in initial["presence"].values))
        trained, _, _, probabilities, _ = fake_forward(self.ns, query_value=8., attention_weight=1.)
        self.assertGreater(as_dual(trained["presence"].values[-1]).gradient, 0.)
        self.assertGreater(probabilities[0][1], probabilities[0][0])
        self.assertEqual(probabilities[0][2], 0.)
        uniform, _, _, uniform_probabilities, _ = fake_forward(self.ns, query_value=8., attention_weight=1., uniform=True)
        self.assertEqual(uniform_probabilities, [[.5, .5, 0.]])
        self.assertNotEqual(float(trained["presence"].values[-1]), float(uniform["presence"].values[-1]))
        self.assertEqual([float(value) for value in trained["presence"].values[:6]], [float(value) for value in uniform["presence"].values[:6]])
        for field in ("modality", "start", "end"):
            self.assertEqual(trained[field].values, uniform[field].values)
        with self.assertRaises(ValueError):
            fake_forward(self.ns, uniform=True, training=True)

    def test_capture_and_readout_bounds_and_uniform_mode_restored_in_finally(self):
        tree = ast.parse(SOURCE.read_bytes())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SpanTemporalAttentionAdapterDecoder")
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "decode_formal_logic")
        condition = compile(ast.Expression(method.body[0].value.args[0]), str(SOURCE) + "#readout-bound", "eval")
        span = SimpleNamespace(tokenize_source=lambda text: [None] * int(text))
        self.assertTrue(eval(condition, dict(texts=["128"] * 168, span=span)))
        for texts in ([], ["1"] * 169, ["129"], [1]):
            with self.subTest(count=len(texts)):
                self.assertFalse(eval(condition, dict(texts=texts, span=span)))
        capture = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "captured_inference")
        capture_condition = compile(ast.Expression(capture.body[2].value.args[0]), str(SOURCE) + "#capture-bound", "eval")
        self.assertTrue(eval(capture_condition, dict(rows=[{}] * 168)))
        for rows in ([], [{}] * 169, iter([{}])):
            self.assertFalse(eval(capture_condition, dict(rows=rows)))
        finalizers = [node for node in ast.walk(method) if isinstance(node, ast.Try) and node.finalbody]
        self.assertTrue(any('self.model._attention_control = \'learned\'' in ast.unparse(node.finalbody[0]) for node in finalizers))
        self.assertIn("attention_control", [arg.arg for arg in capture.args.kwonlyargs])

    def test_model_constructor_keeps_stable_module_query_order_without_rng_draws(self):
        tree = ast.parse(SOURCE.read_bytes())
        model = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_model")
        source = ast.unparse(model)
        self.assertIn("base.temporal_attention = torch.nn.Module()", source)
        self.assertIn("base.temporal_attention.register_parameter('query'", source)
        self.assertLess(source.index("base.temporal_attention ="), source.index("base.temporal_presence ="))
        self.assertNotIn("manual_seed", source)
        self.assertNotIn("randn", source)
        self.assertEqual(len([node for node in ast.walk(model) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "_features"]), 2)
        restore = ast.unparse(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_restore"))
        self.assertIn("weight_decay=0.0", restore)
        self.assertIn("foreach=False", restore)
        train = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "train_decoder")
        self.assertEqual(len([node for node in ast.walk(train) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "model"]), 1)

    def test_numerical_imports_are_unavailable(self):
        with self.assertRaises(AssertionError):
            self.ns["_restore"]({})


if __name__ == "__main__":
    unittest.main()
