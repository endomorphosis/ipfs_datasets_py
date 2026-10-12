"""Pure targeted-loss contracts; production imports and numerical runs excluded.

Named AST functions are detached without executing producer imports, model
construction or provenance capture. Differentiable scalar/vector fakes check
selection and gradient routing; they do not qualify PyTorch kernels or accuracy.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import re
import struct
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[4] / "ipfs_datasets_py" / "optimizers"
          / "logic_theorem_optimizer" / "legal_span_targeted_loss.py")
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
FLAGS = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
         "semantic_correctness_verified", "promotion_performed", "publication_performed")
NAMES = ("_require", "_raw", "checkpoint_digest", "_policy", "_validate_policy",
         "_combine_main_loss", "_combine_total_loss", "_progress", "_batch_indices",
         "_advance_progress", "_batch_trace_entry", "_trace_summary", "_f32",
         "_span_coordinates", "_actor_domain", "_actor_record", "_choose_actor_wrong",
         "_actor_auxiliary", "_validate_objective_diagnostics", "_objective_trace_entry",
         "_objective_trace_summary")
ZERO = dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)


def detach(path, names, namespace):
    tree = ast.parse(path.read_bytes())
    selected = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names}
    if set(selected) != set(names):
        raise AssertionError("missing exact detached definitions")
    for node in selected.values():
        if node.decorator_list or any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node)):
            raise AssertionError("detached contract refuses imports/decorators")
    exec(compile(ast.Module(body=[selected[n] for n in names], type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def helpers():
    namespace = dict(copy=copy, hashlib=hashlib, json=json, math=math, random=random,
        struct=struct, SPAN_FIELDS=FIELDS, MAX_SOURCE_TOKENS=128, MAX_NEW_STEPS=32,
        MAX_SECONDS=32, MAX_BYTES=128 * 1024 * 1024,
        POLICY_SCHEMA="bounded-source-span-targeted-loss-policy/v1",
        LEGACY96_SHA256="4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995")
    detach(SOURCE, NAMES, namespace)
    tokens = detach(SOURCE.with_name("legal_span_formula.py"), ("_require", "tokenize_source"),
        dict(re=re, _TOKEN_RE=re.compile(r"\w+|[^\w\s]", re.UNICODE),
             MAX_SOURCE_CHARACTERS=16384, MAX_SOURCE_TOKENS=256, MAX_TOKEN_BYTES=2048))
    namespace["span"] = SimpleNamespace(tokenize_source=tokens["tokenize_source"],
        _SHA=re.compile(r"[0-9a-f]{64}\Z"))
    return namespace


def record(namespace, count=5, gold=(0, 1), action=(2, 2), object_span=(4, 4)):
    source = " ".join("t" + str(i) for i in range(count))
    spans = [gold, action, object_span, (-100, -100), (-100, -100), (-100, -100)]
    presence = [True, True, object_span != (-100, -100), False, False, False]
    return dict(id="synthetic-row", source_text=source,
        tokens=namespace["span"].tokenize_source(source), latent=[0.] * 384,
        labels=dict(modality=0, spans=spans, presence=presence))


def f32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


class Scalar:
    """A finite float32 scalar with an explicit symbolic derivative map."""
    def __init__(self, value, gradient=None):
        self.value = f32(value)
        self.gradient = dict(gradient or {})

    @staticmethod
    def coerce(value):
        return value if isinstance(value, Scalar) else Scalar(value)

    def __add__(self, other):
        other = self.coerce(other)
        return Scalar(self.value + other.value,
            {k: self.gradient.get(k, 0.) + other.gradient.get(k, 0.)
             for k in self.gradient.keys() | other.gradient.keys()})

    __radd__ = __add__

    def __neg__(self):
        return Scalar(-self.value, {k: -v for k, v in self.gradient.items()})

    def __sub__(self, other):
        return self + -self.coerce(other)

    def __rsub__(self, other):
        return self.coerce(other) + -self

    def __mul__(self, other):
        other = self.coerce(other)
        return Scalar(self.value * other.value,
            {k: self.gradient.get(k, 0.) * other.value + other.gradient.get(k, 0.) * self.value
             for k in self.gradient.keys() | other.gradient.keys()})

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.coerce(other)
        return Scalar(self.value / other.value,
            {k: self.gradient.get(k, 0.) / other.value
             - self.value * other.gradient.get(k, 0.) / other.value ** 2
             for k in self.gradient.keys() | other.gradient.keys()})

    def detach(self):
        return Scalar(self.value)

    def item(self):
        return self.value

    def __float__(self):
        return self.value


class BoolVector:
    def __init__(self, values):
        self.values = values

    def sum(self):
        return Scalar(sum(self.values))


class Vector:
    dtype = "fake-float32"
    device = SimpleNamespace(type="cpu")

    def __init__(self, values):
        self.values = [Scalar.coerce(v) for v in values]
        self.shape = (len(self.values),)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return Vector(self.values[key])
        if isinstance(key, list):
            return Vector([self.values[i] for i in key])
        return self.values[key]

    def __add__(self, other):
        return Vector([a + b for a, b in zip(self.values, other.values, strict=True)])

    def __eq__(self, other):
        other = Scalar.coerce(other)
        return BoolVector([v.value == other.value for v in self.values])

    def detach(self):
        return Vector([v.detach() for v in self.values])

    def tolist(self):
        return [v.value for v in self.values]

    def sum(self):
        return sum(self.values)

    def mean(self):
        return self.sum() / len(self.values)


class Cube:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, key):
        position, field = key
        if field != 0:
            raise AssertionError("fake actor auxiliary must use actor head only")
        return self.rows[position]


class FakeTorch:
    """Only scalar/vector algebra, never tensors, a model or numerical library."""
    float32 = Vector.dtype
    long = "fake-long"

    def __init__(self):
        self.argmax_calls = 0
        self.gathers = []
        self.nn = SimpleNamespace(functional=SimpleNamespace(relu=self.relu))

    def tensor(self, values, *, dtype):
        if dtype != self.long or not all(type(v) is int for v in values):
            raise AssertionError("only contained integer gather coordinates expected")
        self.gathers.append(list(values))
        return list(values)

    def argmax(self, values):
        self.argmax_calls += 1
        if any(v.gradient for v in values.values):
            raise AssertionError("argmax received a differentiable score")
        return Scalar(max(range(len(values.values)), key=lambda i: values.values[i].value))

    @staticmethod
    def stack(values):
        return Vector(values)

    @staticmethod
    def relu(value):
        return Scalar(value.value, value.gradient) if value.value > 0 else Scalar(0., {k: 0. for k in value.gradient})


def fake_output(starts, ends):
    return dict(start=Cube([Vector([Scalar(v, {"s" + str(i): 1.}) for i, v in enumerate(starts)])]),
                end=Cube([Vector([Scalar(v, {"e" + str(i): 1.}) for i, v in enumerate(ends)])]))


class Expr:
    """Arithmetic syntax witness for exact unchanged expression association."""
    def __init__(self, expression):
        self.expression = expression

    def __add__(self, other):
        return Expr(("+", self.expression, other.expression if isinstance(other, Expr) else other))

    def __radd__(self, other):
        return Expr(("+", other, self.expression))

    def __mul__(self, other):
        return Expr(("*", self.expression, other))

    def __rmul__(self, other):
        return Expr(("*", other, self.expression))

    def __truediv__(self, other):
        return Expr(("/", self.expression, other))


class TargetedLossContracts(unittest.TestCase):
    def setUp(self):
        self.n = helpers()

    def test_four_closed_policies_and_fixed_recipe(self):
        for ranking in (False, True):
            for weight in (1, 2):
                p = self.n["_policy"](1729, actor_ranking_enabled=ranking, presence_ce_weight=weight)
                self.assertEqual(p, self.n["_validate_policy"](p))
                self.assertEqual(p["normalization_denominator"], 8 + 2 * (weight - 1))
                self.assertEqual(p["modality_loss_weight"], 2)
                self.assertEqual(p["optional_presence_CE_weights"],
                    dict(object=1, conditions=weight, exceptions=weight, temporal=1))
                self.assertEqual(set(p["facet_pointer_CE_weights"].values()), {1})
                self.assertEqual((p["actor_hinge_coefficient"], p["actor_hinge_margin"]), (.25, 1.))
                self.assertFalse(p["inference_candidate_coverage_guaranteed"])
                self.assertEqual(p["max_source_tokens"], 128)
                self.assertEqual((p["initialization_seed"], p["batch_order_seed"], p["batch_size"]), (1729, 1729, 12))
                self.assertEqual((p["max_new_optimizer_steps"], p["max_seconds"]), (32, 32))
                self.assertEqual(p["training_count"], 168)
                self.assertFalse(p["latent_enabled"])
                self.assertEqual(p["promotion_gate"]["raw_exact_IR_required"], 96)
                self.assertEqual(p["promotion_gate"]["joint_exact_IR_required"], 96)
                self.assertEqual(p["promotion_gate"]["permission_to_obligation_errors_required"], 0)
                self.assertFalse(p["promotion_gate"]["trainer_executes_promotion"])

    def test_policy_rejects_coercion_and_policy_drift(self):
        for key, values in {"actor_ranking_enabled": (0, 1, None), "presence_ce_weight": (True, 0, 3, 1.),
                            "batch_order_seed": (None, 1, True), "batch_size": (1, 12., True)}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.n["_policy"](1729, **{key: value})
        for seed in (None, 0, 1729., True):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                self.n["_policy"](seed)
        for key, value in {"normalization_denominator": 9, "actor_hinge_coefficient": .5,
                           "actor_hinge_margin": 2., "latent_enabled": True, "extra": 1}.items():
            p = self.n["_policy"](); p[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.n["_validate_policy"](p)

    def test_OFF_presence1_exact_legacy_modality2_expression_and_ast(self):
        old = detach(SOURCE.with_name("legal_span_curriculum.py"), ("_combine_loss",),
            dict(_require=self.n["_require"], SPAN_FIELDS=FIELDS))
        modality = Expr("modality"); facets = [Expr(f) for f in FIELDS]
        new = self.n["_combine_main_loss"](modality, facets, dict(conditions=Expr("c"), exceptions=Expr("e")), 1)
        self.assertEqual(new.expression, old["_combine_loss"](modality, facets, 2).expression)
        self.assertIs(self.n["_combine_total_loss"](new, Expr("unused"), False), new)
        old_node = next(n for n in ast.parse(SOURCE.with_name("legal_span_curriculum.py").read_bytes()).body
                        if isinstance(n, ast.FunctionDef) and n.name == "_combine_loss")
        new_node = next(n for n in ast.parse(SOURCE.read_bytes()).body
                        if isinstance(n, ast.FunctionDef) and n.name == "_combine_main_loss")
        self.assertEqual(ast.dump(old_node.body[-1].value), ast.dump(new_node.body[-2].body[0].value))

    def test_presence_weight_changes_only_two_presence_means_and_normalization(self):
        facets = [Scalar(2., {f: 1.}) for f in FIELDS]
        p = {f: Scalar(3., {"presence_" + f: 1.}) for f in ("conditions", "exceptions")}
        w1 = self.n["_combine_main_loss"](Scalar(4., {"modality": 1.}), facets, p, 1)
        w2 = self.n["_combine_main_loss"](Scalar(4., {"modality": 1.}), facets, p, 2)
        self.assertEqual(w1.value, 2.5)
        self.assertEqual(w2.value, f32(2.6))
        self.assertEqual(w2.gradient["presence_conditions"], .1)
        self.assertEqual(w2.gradient["presence_exceptions"], .1)
        self.assertEqual(w2.gradient["modality"], .2)
        self.assertTrue(all(w2.gradient[f] == .1 for f in FIELDS))
        self.assertNotIn("presence_conditions", w1.gradient)
        total = self.n["_combine_total_loss"](w2, Scalar(8., {"hinge": 1.}), True)
        self.assertEqual(total.value, f32(w2.value + 2.))
        self.assertEqual(total.gradient["hinge"], .25)

    def test_pointer_CE_expression_matches_retained_source(self):
        def pointer(path):
            loss = next(n for n in ast.parse(path.read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == "_loss")
            return next(n.value for n in ast.walk(loss) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "pointer" for t in n.targets))
        self.assertEqual(ast.dump(pointer(SOURCE)), ast.dump(pointer(SOURCE.with_name("legal_span_curriculum.py"))))

    def test_full128_boundary_domain_is_not_K_truncated(self):
        domain = self.n["_actor_domain"](128, (0, 0), dict(action=(127, 127)))
        self.assertEqual(len(domain), 127 * 128 // 2 - 1)
        self.assertEqual(domain[0], (0, 1)); self.assertEqual(domain[-1], (126, 126))
        self.assertTrue(all(0 <= a <= b < 127 for a, b in domain))
        self.assertNotIn((0, 0), domain)

    def test_domain_matches_independent_exhaustive_inclusive_nonoverlap(self):
        for count in range(2, 12):
            gold = (0, min(1, count - 2)); other = dict(action=(count - 1, count - 1))
            expected = [(a, b) for a in range(count) for b in range(count)
                        if a <= b and (a, b) != gold and not set(range(a, b + 1)) & {count - 1}]
            self.assertEqual(self.n["_actor_domain"](count, gold, other), expected)

    def test_adjacent_spans_allowed_overlap_and_invalid_gold_rejected(self):
        self.n["_actor_domain"](8, (0, 2), dict(action=(3, 3), object=(4, 5)))
        invalid = [(-100, -100), (), (2, 1), (0, 8), (False, 1), (0., 1)]
        for coordinates in invalid:
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                self.n["_actor_domain"](8, coordinates, dict(action=(6, 6)))
        for others in (dict(action=(2, 3)), dict(action=(4, 5), object=(5, 6)), dict(unknown=(6, 6))):
            with self.subTest(others=others), self.assertRaises(ValueError):
                self.n["_actor_domain"](8, (0, 2), others)
        for count in (0, 129, True, 8.):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.n["_actor_domain"](count, (0, 0), {})

    def test_required_actor_and_optional_ignore_index_contracts(self):
        self.n["_actor_record"](record(self.n))
        for field in (0, 1):
            row = record(self.n); row["labels"]["presence"][field] = False
            row["labels"]["spans"][field] = (-100, -100)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.n["_actor_record"](row)
        row = record(self.n); row["labels"]["spans"][3] = (0, 0)
        with self.assertRaises(ValueError): self.n["_actor_record"](row)
        row = record(self.n); row["labels"]["presence"][3] = True
        with self.assertRaises(ValueError): self.n["_actor_record"](row)
        row = record(self.n); row["tokens"][0]["end"] += 1
        with self.assertRaises(ValueError): self.n["_actor_record"](row)

    def test_source129_rejected_without_truncation(self):
        with self.assertRaises(ValueError):
            self.n["_actor_record"](record(self.n, count=129))

    def test_detached_reference_argmax_ties_and_padding(self):
        decision = self.n["_choose_actor_wrong"]([0.] * 5 + [100000.], [0.] * 5 + [100000.],
            5, (0, 1), dict(action=(2, 2), object=(4, 4)))
        self.assertEqual(decision["chosen_wrong_coordinates"], [0, 0])
        self.assertEqual(decision["compatible_wrong_candidate_count"], 3)
        self.assertEqual(decision["chosen_wrong_tie_count"], 3)
        self.assertEqual(decision["padded_score_width"], 6)
        for values in ([math.nan] * 5, [math.inf] * 5, [True] * 5, [1 / 3] * 5):
            with self.subTest(values=values[0]), self.assertRaises(ValueError):
                self.n["_choose_actor_wrong"](values, [0.] * 5, 5, (0, 1), dict(action=(2, 2)))

    def test_actual_aux_vectorized_detached_choice_and_both_score_gradients(self):
        torch = FakeTorch(); row = record(self.n)
        loss, rows = self.n["_actor_auxiliary"](torch,
            fake_output([2., 5., 900., 1., 900., 100000.], [2., 0., 900., 6., 900., 100000.]), [row], True)
        self.assertEqual(rows[0]["chosen_wrong_coordinates"], [3, 3])
        self.assertEqual(rows[0]["compatible_wrong_candidate_count"], 3)
        self.assertEqual(rows[0]["gold_score_float32"], 2.)
        self.assertEqual(rows[0]["chosen_wrong_score_float32"], 7.)
        self.assertEqual(loss.value, 6.)
        self.assertEqual(loss.gradient, dict(s3=1., e3=1., s0=-1., e1=-1.))
        self.assertEqual(torch.argmax_calls, 1)
        self.assertEqual(torch.gathers, [[0, 1, 3], [0, 1, 3]])
        self.assertTrue(rows[0]["argmax_detached"])
        self.assertTrue(rows[0]["hinge_active"])
        self.assertEqual(rows[0]["selection_implementation"], "vectorized_detached_source_boundary_gather")

    def test_actual_aux_tie_order_zero_domain_and_inactive_hinge(self):
        row = record(self.n); torch = FakeTorch()
        _, rows = self.n["_actor_auxiliary"](torch, fake_output([0.] * 5, [0.] * 5), [row], False)
        self.assertEqual(rows[0]["chosen_wrong_coordinates"], [0, 0])
        self.assertEqual(rows[0]["chosen_wrong_tie_count"], 3)
        self.assertFalse(rows[0]["gradient_enabled_by_policy"])
        empty = record(self.n, count=2, gold=(0, 0), action=(1, 1), object_span=(-100, -100))
        torch = FakeTorch(); loss, rows = self.n["_actor_auxiliary"](torch, fake_output([2., 3.], [2., 3.]), [empty], True)
        self.assertEqual(loss.value, 0.)
        self.assertTrue(all(v == 0. for v in loss.gradient.values()))
        self.assertEqual(rows[0]["compatible_wrong_candidate_count"], 0)
        self.assertIsNone(rows[0]["chosen_wrong_coordinates"])
        self.assertTrue(rows[0]["zero_domain_differentiable_zero"])
        self.assertEqual(torch.argmax_calls, 0)
        loss, rows = self.n["_actor_auxiliary"](FakeTorch(), fake_output([20., 0., 0., 0., 0.], [0., 5., 0., 0., 0.]), [row], True)
        self.assertEqual(loss.value, 0.); self.assertFalse(rows[0]["hinge_active"])

    def test_aux_rejects_score_width_above128_or_non_CPU_float32(self):
        row = record(self.n)
        with self.assertRaises(ValueError):
            self.n["_actor_auxiliary"](FakeTorch(), fake_output([0.] * 129, [0.] * 129), [row], True)
        output = fake_output([0.] * 5, [0.] * 5); output["start"].rows[0].dtype = "fake-float64"
        with self.assertRaises(ValueError):
            self.n["_actor_auxiliary"](FakeTorch(), output, [row], True)

    def diagnostic(self, enabled=True):
        row = record(self.n)
        loss, rows = self.n["_actor_auxiliary"](FakeTorch(), fake_output([2., 5., 0., 1., 0.], [2., 0., 0., 6., 0.]), [row], enabled)
        return dict(schema="targeted-source-span-objective-diagnostics/v1", main_loss=2.,
            actor_hinge_mean=loss.value, actor_hinge_applied=enabled, actor_hinge_coefficient=.25,
            total_loss=3.5 if enabled else 2., presence_CE_means=dict(conditions=1., exceptions=1.),
            rows=rows, teacher_forcing=True, evaluation_references_used=False, semantic_compatibility_verified=False)

    def test_objective_diagnostics_close_domain_scores_and_authority(self):
        original = self.diagnostic()
        self.assertEqual(self.n["_validate_objective_diagnostics"](original), original)
        changes = (lambda v: v.update(evaluation_references_used=True),
                   lambda v: v["rows"][0].update(compatible_wrong_candidate_count=2),
                   lambda v: v["rows"][0].update(compatible_wrong_domain_sha256="wrong"),
                   lambda v: v["rows"][0].update(actor_hinge_value=7.),
                   lambda v: v["rows"][0].update(chosen_wrong_coordinates=[2, 2]),
                   lambda v: v["rows"][0].update(chosen_wrong_score_float32=math.inf),
                   lambda v: v["rows"][0].update(gold_score_float32=3.),
                   lambda v: v["rows"][0].update(chosen_wrong_score_float32=8.),
                   lambda v: v.update(actor_hinge_mean=7.),
                   lambda v: v.update(total_loss=4.),
                   lambda v: v["rows"][0].update(semantic_compatibility_verified=True),
                   lambda v: v["rows"][0].update(extra="unclosed"))
        for i, change in enumerate(changes):
            v = copy.deepcopy(original); change(v)
            with self.subTest(change=i), self.assertRaises(ValueError):
                self.n["_validate_objective_diagnostics"](v)

    def test_objective_trace_after_returned_step_joins_ID_and_source(self):
        example = dict(id="synthetic-row", source_text=record(self.n)["source_text"])
        diagnostic = self.diagnostic()
        entry = self.n["_objective_trace_entry"]([0], [example], 1, diagnostic)
        batch = dict(optimizer_step=1, indices=[0], ids=[example["id"]], loss=diagnostic["total_loss"])
        trace = self.n["_objective_trace_summary"]([entry], [batch], self.n["_policy"](actor_ranking_enabled=True))
        self.assertEqual(trace["completed_updates"], 1)
        self.assertEqual(trace["batches_sha256"], self.n["checkpoint_digest"]([entry]))
        self.assertFalse(trace["evaluation_references_used"])
        with self.assertRaises(ValueError):
            self.n["_objective_trace_entry"]([0], [dict(example, id="wrong")], 1, diagnostic)
        with self.assertRaises(ValueError):
            self.n["_objective_trace_entry"]([0], [dict(example, source_text="wrong")], 1, diagnostic)
        with self.assertRaises(ValueError):
            self.n["_objective_trace_summary"]([entry], [batch], self.n["_policy"]())
        with self.assertRaises(ValueError):
            self.n["_objective_trace_summary"]([entry], [], self.n["_policy"](actor_ranking_enabled=True))
        with self.assertRaises(ValueError):
            self.n["_objective_trace_summary"]([entry], [dict(batch, loss=9.)], self.n["_policy"](actor_ranking_enabled=True))

    def test_OFF_mean_and_total_associations_and_rounding_bound(self):
        value = self.diagnostic(enabled=False)
        self.n["_validate_objective_diagnostics"](value)
        self.assertEqual(value["total_loss"], value["main_loss"])
        # OFF records the unweighted counterfactual margin diagnostic, with
        # zero applied contribution and no change to the exact old main loss.
        self.assertEqual(value["actor_hinge_mean"], 6.)
        wrong = copy.deepcopy(value); wrong["total_loss"] += .25 * wrong["actor_hinge_mean"]
        with self.assertRaises(ValueError): self.n["_validate_objective_diagnostics"](wrong)
        value = self.diagnostic()
        value["actor_hinge_mean"] = f32(6. + 2. ** -21)
        value["total_loss"] = f32(value["main_loss"] + f32(.25 * value["actor_hinge_mean"]))
        self.n["_validate_objective_diagnostics"](value)
        value["actor_hinge_mean"] = f32(6.01)
        with self.assertRaises(ValueError): self.n["_validate_objective_diagnostics"](value)

    def test_same168_seed1729_actual32_update_schedule_and_trace(self):
        examples = [dict(id="row" + str(i)) for i in range(168)]
        policy = self.n["_policy"](); cursor = dict(ZERO); batches = []
        independent_epoch = independent_cursor = 0
        for step in range(1, 33):
            order = list(range(168)); random.Random(1729 + independent_epoch).shuffle(order)
            expected = order[independent_cursor:independent_cursor + 12]
            indices = self.n["_batch_indices"](168, cursor, 12, 1729)
            self.assertEqual(indices, expected)
            after = self.n["_advance_progress"](cursor, len(indices), 168)
            batches.append(self.n["_batch_trace_entry"](indices, examples, cursor, after, loss=1., gradient_norm=2.))
            cursor = after; independent_cursor += len(indices)
            if independent_cursor == 168:
                independent_epoch += 1; independent_cursor = 0
        self.assertEqual(cursor, dict(epochs_completed=2, row_cursor=48, optimizer_steps=32))
        trace = self.n["_trace_summary"](batches, ZERO, cursor, policy, examples)
        self.assertEqual(trace["schema"], "completed-curriculum-batch-trace/v1")
        self.assertEqual(trace["completed_updates"], 32)
        self.assertFalse(trace["independent_runtime_trace"])
        wrong = copy.deepcopy(batches); wrong[0]["ids"][0] = "wrong"
        with self.assertRaises(ValueError): self.n["_trace_summary"](wrong, ZERO, cursor, policy, examples)

    def test_numeric_entrypoint_bounds_fail_before_stubbed_restore_boundary(self):
        class BoundaryReached(RuntimeError):
            pass
        def stop(checkpoint):
            raise BoundaryReached("no model or numerical validation allowed in test")
        n = dict(self.n, time=SimpleNamespace(monotonic=lambda: 0.), _validated=stop)
        detach(SOURCE, ("train_decoder",), n)
        for options in (dict(max_steps=33), dict(max_steps=-1), dict(max_steps=True),
                        dict(max_seconds=33), dict(max_seconds=-1), dict(max_seconds=math.nan), dict(max_seconds=True)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                n["train_decoder"]({}, [], **options)
        with self.assertRaises(BoundaryReached): n["train_decoder"]({}, [], max_steps=32, max_seconds=32)

    def checkpoint_guard(self):
        n = dict(self.n, SCHEMA="bounded-targeted-loss-span-legal-formula-checkpoint/v1",
            LINEAGE_ID="bounded_source_span_targeted_loss_v1", FALSE={f: False for f in FLAGS},
            SOURCE_PARENT_SHA256="fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279",
            SOURCE_MODEL_SHA256="54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb")
        base = dict(config=dict(seed=1729, batch_size=12, latent_dimension=384,
                    latent_enabled=False, learning_rate=.001), training_count=168, progress=dict(ZERO))
        child = dict(opaque_synthetic_metadata_child=True,
            source_parent_checkpoint_sha256=n["SOURCE_PARENT_SHA256"],
            initial_model_state_sha256=n["SOURCE_MODEL_SHA256"], source_parent_optimizer_steps=400)
        implementation = {"synthetic_source_metadata": "a" * 64}
        n.update(_implementation=lambda: copy.deepcopy(implementation),
            continuation=SimpleNamespace(_validated=lambda value: copy.deepcopy(base)),
            _initial_continuation=lambda value: copy.deepcopy(child))
        detach(SOURCE, ("_validated",), n)
        policy = n["_policy"]()
        checkpoint = dict(schema=n["SCHEMA"], lineage_id=n["LINEAGE_ID"], implementation=implementation,
            training_policy=policy, training_policy_sha256=n["checkpoint_digest"](policy),
            initial_training_policy_sha256=n["checkpoint_digest"](policy),
            initial_continuation_checkpoint_sha256=n["checkpoint_digest"](child),
            source_parent_checkpoint_sha256=n["SOURCE_PARENT_SHA256"],
            source_parent_model_state_sha256=n["SOURCE_MODEL_SHA256"],
            continuation_checkpoint=copy.deepcopy(child), parent_checkpoint_sha256=None,
            **{f: False for f in FLAGS})
        checkpoint["initial_targeted_checkpoint_sha256"] = n["checkpoint_digest"](checkpoint)
        return n, checkpoint, base

    def test_strict_outer_schema_origin_parent_and_policy_metadata(self):
        n, checkpoint, _ = self.checkpoint_guard()
        n["_validated"](checkpoint)
        with self.assertRaises(ValueError):
            n["_validated"](dict(schema="warm-start-span-legal-formula-checkpoint/v1"))
        mutations = (lambda c: c.update(schema="bounded-curriculum-span-legal-formula-checkpoint/v1"),
                     lambda c: c.update(admitted=True), lambda c: c.update(extra=1),
                     lambda c: c.update(initial_training_policy_sha256="b" * 64),
                     lambda c: c.update(initial_targeted_checkpoint_sha256="b" * 64),
                     lambda c: c["training_policy"].update(presence_ce_weight=2),
                     lambda c: c["continuation_checkpoint"].update(source_parent_checkpoint_sha256="b" * 64),
                     lambda c: c["continuation_checkpoint"].update(source_parent_optimizer_steps=399))
        for i, change in enumerate(mutations):
            candidate = copy.deepcopy(checkpoint); change(candidate)
            with self.subTest(mutation=i), self.assertRaises(ValueError):
                n["_validated"](candidate)

    def test_resume_cumulative32_and_constructor_metadata_not_relaxed(self):
        for key, value in (("training_count", 167), ("learning_rate", .002), ("latent_enabled", True),
                           ("seed", 1), ("batch_size", 11), ("optimizer_steps", 33)):
            n, checkpoint, base = self.checkpoint_guard()
            if key in base["config"]: base["config"][key] = value
            elif key == "optimizer_steps": base["progress"][key] = value
            else: base[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                n["_validated"](checkpoint)

    def test_fixed_legacy96_and168_guards_precede_split_boundary(self):
        class SplitBoundary(RuntimeError):
            pass
        def stop(*args):
            raise SplitBoundary("synthetic split boundary, no codec/model execution")
        n = dict(self.n, span=SimpleNamespace(_splits=stop))
        detach(SOURCE, ("_bounded_splits",), n)
        for count in (0, 96, 167, 168, 169):
            examples = [dict(id="untrusted" + str(i)) for i in range(count)]
            with self.subTest(count=count), self.assertRaises(ValueError):
                n["_bounded_splits"](examples, ())
        n["checkpoint_digest"] = lambda value: n["LEGACY96_SHA256"]
        with self.assertRaises(SplitBoundary):
            n["_bounded_splits"]([dict(id=str(i)) for i in range(168)], ())

    def test_parent_hash_and_latent_recipe_refuse_before_builder_boundary(self):
        class BuilderBoundary(RuntimeError):
            pass
        def stop(*args, **kwargs):
            raise BuilderBoundary("forbidden old numerical builder")
        n = dict(self.n, SOURCE_PARENT_SHA256="b" * 64, SOURCE_MODEL_SHA256="c" * 64,
            continuation=SimpleNamespace(build_checkpoint=stop))
        detach(SOURCE, ("build_checkpoint",), n)
        for options in (dict(latent_enabled=True), dict(learning_rate=.002), dict(seed=1), {}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                n["build_checkpoint"]({}, [], context_contract={}, **options)

    def test_no_old_train_delegation_and_after_step_objective_recording(self):
        tree = ast.parse(SOURCE.read_bytes())
        train = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "train_decoder")
        calls = [n for n in ast.walk(train) if isinstance(n, ast.Call)]
        self.assertFalse(any(isinstance(c.func, ast.Attribute) and c.func.attr == "train_decoder" for c in calls))
        lines = SOURCE.read_text().splitlines()
        step = next(i for i, line in enumerate(lines) if "optimizer.step()" in line)
        objective = next(i for i, line in enumerate(lines) if "objective_entries.append(" in line)
        finite = next(i for i, line in enumerate(lines) if "nonfinite optimizer moments" in line)
        self.assertLess(step, finite); self.assertLess(finite, objective)
        self.assertLess(next(i for i, line in enumerate(lines) if "records, tuning = _bounded_splits(training_examples" in line),
                        next(i for i, line in enumerate(lines) if "torch, model, optimizer = span._restore(base)" in line))


if __name__ == "__main__":
    unittest.main()
