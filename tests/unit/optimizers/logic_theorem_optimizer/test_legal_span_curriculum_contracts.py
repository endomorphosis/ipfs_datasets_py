"""Pure curriculum contracts; no trainer/module or numerical imports.

Only the named pure helper definitions are extracted from the source AST. The
trainer's top-level imports, provenance capture, model wrappers and entry points
are never executed. Assertions use independently constructed schedules and trace
expectations rather than loading checkpoints or restoring a model.
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
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[4] / "ipfs_datasets_py" / "optimizers"
          / "logic_theorem_optimizer" / "legal_span_curriculum.py")
PURE_NAMES = (
    "_require", "_raw", "checkpoint_digest", "_policy", "_validate_policy",
    "_combine_loss", "_progress", "_batch_indices", "_advance_progress", "_batch_trace_entry",
    "_trace_summary",
)
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
ZERO = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
FALSE_FLAGS = (
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed",
)


def _load_pure_helpers():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    definitions = {node.name: node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name in PURE_NAMES}
    if set(definitions) != set(PURE_NAMES):
        raise AssertionError("curriculum source lacks a required pure helper")
    for node in definitions.values():
        if node.decorator_list or any(isinstance(child, (ast.Import, ast.ImportFrom))
                                      for child in ast.walk(node)):
            raise AssertionError("pure extraction refuses decorators and imports")
    namespace = {
        "__name__": "_extracted_pure_curriculum_contracts", "math": math,
        "random": random, "hashlib": hashlib, "json": json, "copy": copy,
        "MAX_NEW_STEPS": 32, "SPAN_FIELDS": SPAN_FIELDS,
        "POLICY_SCHEMA": "bounded-source-span-curriculum-policy/v1",
    }
    selected = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
             + [definitions[name] for name in PURE_NAMES], type_ignores=[])
    exec(compile(ast.fix_missing_locations(selected), str(SOURCE), "exec"), namespace)
    return namespace


def _load_validation_guard():
    """Extract one real guard with an explicit forbidden continuation boundary."""
    namespace = _load_pure_helpers()
    implementation = {"curriculum_sha256": "a" * 64, "closure": "synthetic-static-control"}
    calls = []

    class ContinuationBoundaryReached(RuntimeError):
        pass

    def forbidden_continuation(checkpoint):
        calls.append(copy.deepcopy(checkpoint))
        raise ContinuationBoundaryReached("synthetic continuation boundary reached")

    namespace.update({
        "SCHEMA": "bounded-curriculum-span-legal-formula-checkpoint/v1",
        "LINEAGE_ID": "bounded_source_span_curriculum_v1", "MAX_BYTES": 128 * 1024 * 1024,
        "FALSE": {flag: False for flag in FALSE_FLAGS},
        "_implementation": lambda: copy.deepcopy(implementation),
        "continuation": SimpleNamespace(_validated=forbidden_continuation),
        "span": SimpleNamespace(_SHA=re.compile(r"[0-9a-f]{64}\Z")),
    })
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    node = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_validated")
    if node.decorator_list or any(isinstance(child, (ast.Import, ast.ImportFrom))
                                  for child in ast.walk(node)):
        raise AssertionError("static guard extraction refuses decorators and imports")
    selected = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node],
        type_ignores=[])
    exec(compile(ast.fix_missing_locations(selected), str(SOURCE), "exec"), namespace)
    policy = namespace["_policy"](1729)
    child = {"opaque_synthetic_child": True, "source_parent_checkpoint_sha256": "b" * 64,
             "initial_model_state_sha256": "c" * 64}
    checkpoint = {
        "schema": namespace["SCHEMA"], "lineage_id": namespace["LINEAGE_ID"],
        "implementation": implementation, "training_policy": policy,
        "training_policy_sha256": namespace["checkpoint_digest"](policy),
        "initial_training_policy_sha256": namespace["checkpoint_digest"](policy),
        "initial_continuation_checkpoint_sha256": namespace["checkpoint_digest"](child),
        "source_parent_checkpoint_sha256": "b" * 64,
        "source_parent_model_state_sha256": "c" * 64,
        "continuation_checkpoint": child, "parent_checkpoint_sha256": None,
        **{flag: False for flag in FALSE_FLAGS},
    }
    checkpoint["initial_curriculum_checkpoint_sha256"] = namespace["checkpoint_digest"](checkpoint)
    return namespace["_validated"], checkpoint, calls, ContinuationBoundaryReached


def _legacy_schedule(count, steps, *, seed=1729, batch_size=12, progress=None):
    """Independent transcription of the frozen legacy shuffle/progress rule."""
    position = dict(ZERO if progress is None else progress)
    batches = []
    for _ in range(steps):
        order = list(range(count))
        random.Random(seed + position["epochs_completed"]).shuffle(order)
        start = position["row_cursor"]
        indices = order[start:start + batch_size]
        batches.append(indices)
        position["optimizer_steps"] += 1
        position["row_cursor"] += len(indices)
        if position["row_cursor"] == count:
            position["epochs_completed"] += 1
            position["row_cursor"] = 0
    return batches, position


class PureCurriculumContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = _load_pure_helpers()

    def helper(self, name):
        return self.helpers[name]

    def test_extraction_contains_only_named_helpers_and_stdlib_dependencies(self):
        self.assertTrue(set(PURE_NAMES).issubset(self.helpers))
        self.assertNotIn("train_decoder", self.helpers)
        self.assertNotIn("build_checkpoint", self.helpers)
        self.assertNotIn("torch", self.helpers)
        self.assertNotIn("numpy", self.helpers)
        self.assertNotIn("_capture_implementation", self.helpers)

    def test_require_rejects_false_and_preserves_the_contract_message(self):
        self.helper("_require")(True, "safe")
        with self.assertRaisesRegex(ValueError, "specific contract"):
            self.helper("_require")(False, "specific contract")

    def test_canonical_bytes_and_digest_bind_order_unicode_and_exact_values(self):
        value = {"z": [0, 1.25, "\u00a7"], "a": {"enabled": False}}
        expected = b'{"a":{"enabled":false},"z":[0,1.25,"\\u00a7"]}'
        before = copy.deepcopy(value)
        self.assertEqual(self.helper("_raw")(value), expected)
        self.assertEqual(self.helper("checkpoint_digest")(value), hashlib.sha256(expected).hexdigest())
        self.assertEqual(self.helper("checkpoint_digest")(value),
                         self.helper("checkpoint_digest")({"a": value["a"], "z": value["z"]}))
        self.assertNotEqual(self.helper("checkpoint_digest")(value),
                            self.helper("checkpoint_digest")({"z": [0, 1.2501, "\u00a7"], "a": value["a"]}))
        self.assertEqual(value, before)
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.helper("_raw")({"value": bad})

    def schedule(self, count, steps, *, seed=1729, batch_size=12, progress=None):
        position = dict(ZERO if progress is None else progress)
        batches = []
        for _ in range(steps):
            before = copy.deepcopy(position)
            indices = self.helper("_batch_indices")(count, position, batch_size, seed)
            self.assertEqual(position, before, "batch selection must not mutate progress")
            batches.append(indices)
            previous = position
            position = self.helper("_advance_progress")(previous, len(indices), count)
            self.assertEqual(previous, before, "progress advance must not mutate its input")
            self.assertIsNot(position, previous)
        return batches, position

    def test_default_batches_match_frozen_legacy_shuffle_across_epoch_boundaries(self):
        expected, expected_progress = _legacy_schedule(168, 32)
        actual, progress = self.schedule(168, 32)
        self.assertEqual(actual, expected)
        self.assertEqual(progress, expected_progress)
        self.assertEqual(progress, {"epochs_completed": 2, "row_cursor": 48, "optimizer_steps": 32})
        self.assertTrue(all(len(batch) == 12 and len(set(batch)) == 12 for batch in actual))
        self.assertEqual(sorted(index for batch in actual[:14] for index in batch), list(range(168)))

    def test_default_batches_resume_16_plus_16_with_exact_same_indices(self):
        all_batches, end = self.schedule(168, 32)
        first, middle = self.schedule(168, 16)
        before = copy.deepcopy(middle)
        second, resumed_end = self.schedule(168, 16, progress=middle)
        self.assertEqual(all_batches, first + second)
        self.assertEqual(end, resumed_end)
        self.assertEqual(middle, before)

    def test_small_last_batch_wraps_once_without_skipping_or_repeating_rows(self):
        actual, progress = self.schedule(17, 5)
        expected, expected_progress = _legacy_schedule(17, 5)
        self.assertEqual(actual, expected)
        self.assertEqual([len(batch) for batch in actual], [12, 5, 12, 5, 12])
        self.assertEqual(progress, expected_progress)
        for start in (0, 2):
            self.assertEqual(sorted(actual[start] + actual[start + 1]), list(range(17)))

    def test_policy_separates_initialization_and_order_seed_with_closed_objective(self):
        default = self.helper("_policy")(1729)
        expected = {
            "schema": "bounded-source-span-curriculum-policy/v1",
            "objective": "weighted_modality_equal_facet_mean_pointer/v1",
            "modality_loss_weight": 1,
            "facet_loss_weights": {field: 1 for field in SPAN_FIELDS},
            "normalization_denominator": 7,
            "initialization_seed": 1729,
            "batch_order_seed": 1729,
            "batch_order_seed_origin": "inherited_initialization_seed",
            "batch_size": 12,
            "max_new_optimizer_steps": 32,
            "latent_dimension": 384,
            "latent_enabled": False,
            "nested_loss_metadata_scope": (
                "legacy_constructor_descriptor; this_outer_policy_defines_actual_training_objective"),
        }
        self.assertEqual(default, expected)
        explicit = self.helper("_policy")(1729, modality_loss_weight=2, batch_order_seed=2718)
        self.assertEqual(explicit["initialization_seed"], 1729)
        self.assertEqual(explicit["batch_order_seed"], 2718)
        self.assertEqual(explicit["batch_order_seed_origin"], "explicit")
        self.assertEqual(explicit["normalization_denominator"], 8)
        self.assertEqual(explicit["facet_loss_weights"], expected["facet_loss_weights"])
        self.assertFalse(explicit["latent_enabled"])
        default_batches, _ = self.schedule(168, 32, seed=default["batch_order_seed"])
        explicit_batches, _ = self.schedule(168, 32, seed=explicit["batch_order_seed"])
        expected_batches, _ = _legacy_schedule(168, 32, seed=2718)
        self.assertNotEqual(explicit_batches, default_batches)
        self.assertEqual(explicit_batches, expected_batches)

    def test_policy_rejects_bool_nonfinite_noninteger_and_out_of_range_parameters(self):
        invalid_seeds = (True, False, -1, 2**31, 1729.0, "1729", math.nan, math.inf, -math.inf)
        for bad in invalid_seeds:
            with self.subTest(initialization_seed=bad), self.assertRaises(ValueError):
                self.helper("_policy")(bad)
            with self.subTest(batch_order_seed=bad), self.assertRaises(ValueError):
                self.helper("_policy")(1729, batch_order_seed=bad)
        for bad in (True, False, 0, 3, -1, 1.0, 2.0, "2", None, math.nan, math.inf):
            with self.subTest(weight=bad), self.assertRaises(ValueError):
                self.helper("_policy")(1729, modality_loss_weight=bad)
        for bad in (True, False, 0, 33, -1, 12.0, "12", math.nan, math.inf):
            with self.subTest(batch_size=bad), self.assertRaises(ValueError):
                self.helper("_policy")(1729, batch_size=bad)
        for seed in (0, 2**31 - 1):
            for size in (1, 32):
                policy = self.helper("_policy")(seed, batch_order_seed=seed, batch_size=size)
                self.assertEqual(policy["batch_order_seed"], seed)
                self.assertEqual(policy["batch_size"], size)

    def test_policy_validation_refuses_metadata_drift_and_returns_an_isolated_copy(self):
        policy = self.helper("_policy")(1729, modality_loss_weight=2, batch_order_seed=2718)
        checked = self.helper("_validate_policy")(policy)
        self.assertEqual(checked, policy)
        self.assertIsNot(checked, policy)
        self.assertIsNot(checked["facet_loss_weights"], policy["facet_loss_weights"])
        checked["facet_loss_weights"]["actor"] = 99
        self.assertEqual(policy["facet_loss_weights"]["actor"], 1)
        changes = {
            "schema": "wrong/v1", "objective": "legacy", "modality_loss_weight": True,
            "normalization_denominator": 7, "initialization_seed": True,
            "batch_order_seed": -1, "batch_order_seed_origin": "implicit",
            "batch_size": 33, "max_new_optimizer_steps": 33,
            "latent_dimension": 768, "latent_enabled": True,
            "nested_loss_metadata_scope": "actual_objective",
        }
        for field, bad in changes.items():
            broken = copy.deepcopy(policy)
            broken[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.helper("_validate_policy")(broken)
        broken = copy.deepcopy(policy)
        broken["facet_loss_weights"]["actor"] = 2
        with self.assertRaises(ValueError):
            self.helper("_validate_policy")(broken)
        broken = copy.deepcopy(policy)
        broken["extra"] = False
        with self.assertRaises(ValueError):
            self.helper("_validate_policy")(broken)
        for field in policy:
            broken = copy.deepcopy(policy)
            del broken[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.helper("_validate_policy")(broken)
        inherited = self.helper("_policy")(1729)
        inherited["batch_order_seed"] = 2718
        with self.assertRaises(ValueError):
            self.helper("_validate_policy")(inherited)

    def test_default_loss_keeps_exact_legacy_arithmetic_and_weight_two_normalizes_by_eight(self):
        cases = ((0.0, [0.0] * 6), (0.4, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
                 (1e16, [1.0, -1e16, 0.25, 2.0, 3.0, 4.0]))
        for modality, facets in cases:
            with self.subTest(modality=modality, facets=facets):
                self.assertEqual(self.helper("_combine_loss")(modality, facets, 1),
                                 (modality + sum(facets)) / 7)
                self.assertEqual(self.helper("_combine_loss")(modality, tuple(facets), 2),
                                 (2 * modality + sum(facets)) / 8)

        class NoMultiplyModality:
            def __add__(self, value):
                return 3.0 + value

            def __mul__(self, value):
                raise AssertionError("default loss must not insert modality * 1")

            __rmul__ = __mul__

        self.assertEqual(self.helper("_combine_loss")(NoMultiplyModality(), [1.0] * 6, 1), 9.0 / 7)
        for bad in (True, False, 0, 3, 1.0, math.nan, math.inf):
            with self.subTest(weight=bad), self.assertRaises(ValueError):
                self.helper("_combine_loss")(1.0, [1.0] * 6, bad)
        for bad in ([], [0.0] * 5, [0.0] * 7, {name: 0.0 for name in SPAN_FIELDS}):
            with self.subTest(facets=bad), self.assertRaises(ValueError):
                self.helper("_combine_loss")(1.0, bad, 1)

    def test_progress_and_sampler_reject_invalid_bounds_types_and_step_identity(self):
        for field in ZERO:
            for bad in (-1, True, 0.0, math.nan, 10**9 + 1):
                progress = dict(ZERO)
                progress[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.helper("_progress")(progress)
        for progress in (None, [], {"epochs_completed": 0, "row_cursor": 0}, {**ZERO, "extra": 0}):
            with self.subTest(progress=progress), self.assertRaises(ValueError):
                self.helper("_progress")(progress)
        for bad in (True, 0, -1, 4097, 168.0, math.nan, math.inf):
            with self.subTest(count=bad), self.assertRaises(ValueError):
                self.helper("_batch_indices")(bad, ZERO, 12, 1729)
        for bad in (True, 0, -1, 33, 12.0, math.nan, math.inf):
            with self.subTest(batch_size=bad), self.assertRaises(ValueError):
                self.helper("_batch_indices")(168, ZERO, bad, 1729)
        for bad in (True, -1, 2**31, 1729.0, math.nan, math.inf):
            with self.subTest(seed=bad), self.assertRaises(ValueError):
                self.helper("_batch_indices")(168, ZERO, 12, bad)
        for progress in (
                {"epochs_completed": 0, "row_cursor": 168, "optimizer_steps": 14},
                {"epochs_completed": 0, "row_cursor": 1, "optimizer_steps": 0},
                {"epochs_completed": 1, "row_cursor": 24, "optimizer_steps": 17}):
            with self.subTest(progress=progress), self.assertRaises(ValueError):
                self.helper("_batch_indices")(168, progress, 12, 1729)
        for bad in (True, 0, -1, 33, 12.0, math.nan):
            with self.subTest(indices_count=bad), self.assertRaises(ValueError):
                self.helper("_advance_progress")(ZERO, bad, 168)
        with self.assertRaises(ValueError):
            self.helper("_advance_progress")(
                {"epochs_completed": 0, "row_cursor": 12, "optimizer_steps": 1}, 6, 17)

    @staticmethod
    def examples(count=168):
        return [{"id": "authored-%03d" % index, "source_text": "fixture text %d" % index}
                for index in range(count)]

    def completed_trace(self, steps=32, *, seed=1729, count=168, progress=None):
        rows = self.examples(count)
        initial = dict(ZERO if progress is None else progress)
        batches, final = _legacy_schedule(count, steps, seed=seed, progress=initial)
        entries, position = [], dict(initial)
        for offset, indices in enumerate(batches):
            _, after = _legacy_schedule(count, 1, seed=seed, progress=position)
            entry = self.helper("_batch_trace_entry")(
                indices, rows, position, after, loss=0.25 + offset / 100.0,
                gradient_norm=1.5 + offset / 100.0)
            expected = {
                "schema": "completed-curriculum-batch/v1",
                "indices": list(indices), "ids": [rows[index]["id"] for index in indices],
                "pre_progress": dict(position), "post_progress": dict(after),
                "optimizer_step": after["optimizer_steps"],
                "loss": float(0.25 + offset / 100.0),
                "gradient_norm_before_clip": float(1.5 + offset / 100.0),
            }
            self.assertEqual(entry, expected)
            self.assertIsNot(entry["indices"], indices)
            self.assertIsNot(entry["pre_progress"], position)
            self.assertIsNot(entry["post_progress"], after)
            entries.append(entry)
            position = after
        self.assertEqual(position, final)
        return rows, entries, initial, final

    def test_batch_trace_attests_only_the_completed_update_and_copies_its_evidence(self):
        rows, entries, _, _ = self.completed_trace(1)
        entry = entries[0]
        self.assertEqual(entry["optimizer_step"], 1)
        self.assertEqual(entry["pre_progress"], ZERO)
        self.assertEqual(entry["post_progress"],
                         {"epochs_completed": 0, "row_cursor": 12, "optimizer_steps": 1})
        self.assertEqual(entry["ids"], [rows[index]["id"] for index in entry["indices"]])
        self.assertEqual(set(entry), {"schema", "indices", "ids", "pre_progress", "post_progress",
                                     "optimizer_step", "loss", "gradient_norm_before_clip"})
        before, after = dict(ZERO), dict(entry["post_progress"])
        indices = list(entry["indices"])
        snapshot = copy.deepcopy((indices, rows, before, after))
        copied = self.helper("_batch_trace_entry")(
            indices, rows, before, after, loss=0, gradient_norm=0)
        self.assertEqual((indices, rows, before, after), snapshot)
        copied["indices"][0] = -1
        copied["ids"][0] = "changed"
        copied["pre_progress"]["optimizer_steps"] = 100
        copied["post_progress"]["optimizer_steps"] = 100
        self.assertEqual((indices, rows, before, after), snapshot)

    def test_batch_trace_refuses_duplicate_out_of_range_indices_and_nonunique_ids(self):
        rows = self.examples()
        valid_indices = list(range(12))
        after = {"epochs_completed": 0, "row_cursor": 12, "optimizer_steps": 1}
        for indices in ([], tuple(valid_indices), [0, 0], [-1], [168], [True], [1.0], list(range(33))):
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    indices, rows, ZERO, after, loss=1.0, gradient_norm=1.0)
        for bad_id in (None, True, "", "   ", "x" * 513):
            changed = copy.deepcopy(rows)
            changed[0]["id"] = bad_id
            with self.subTest(identifier=bad_id), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    valid_indices, changed, ZERO, after, loss=1.0, gradient_norm=1.0)
        changed = copy.deepcopy(rows)
        changed[1]["id"] = changed[0]["id"]
        with self.assertRaises(ValueError):
            self.helper("_batch_trace_entry")(
                valid_indices, changed, ZERO, after, loss=1.0, gradient_norm=1.0)
        for population in ([], self.examples(4097)):
            with self.subTest(count=len(population)), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    [0], population, ZERO, after, loss=1.0, gradient_norm=1.0)

    def test_batch_trace_refuses_incomplete_progress_and_invalid_loss_or_gradient(self):
        rows = self.examples()
        indices = list(range(12))
        valid_after = {"epochs_completed": 0, "row_cursor": 12, "optimizer_steps": 1}
        for after in (dict(ZERO),
                      {"epochs_completed": 0, "row_cursor": 12, "optimizer_steps": 0},
                      {"epochs_completed": 0, "row_cursor": 24, "optimizer_steps": 1},
                      {"epochs_completed": 1, "row_cursor": 12, "optimizer_steps": 1}):
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    indices, rows, ZERO, after, loss=1.0, gradient_norm=1.0)
        for bad in (True, False, None, "1", math.nan, math.inf, -math.inf):
            with self.subTest(loss=bad), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    indices, rows, ZERO, valid_after, loss=bad, gradient_norm=1.0)
            with self.subTest(gradient=bad), self.assertRaises(ValueError):
                self.helper("_batch_trace_entry")(
                    indices, rows, ZERO, valid_after, loss=1.0, gradient_norm=bad)
        with self.assertRaises(ValueError):
            self.helper("_batch_trace_entry")(
                indices, rows, ZERO, valid_after, loss=1.0, gradient_norm=-0.01)
        with self.assertRaises(ValueError):
            self.helper("_batch_trace_entry")(
                indices, rows, ZERO, valid_after, loss=-0.01, gradient_norm=1.0)
        malformed_rows = self.examples()
        malformed_rows[0] = "not a dictionary"
        with self.assertRaises(ValueError):
            self.helper("_batch_trace_entry")(
                indices, malformed_rows, ZERO, valid_after, loss=1.0, gradient_norm=1.0)
        _, past_end = _legacy_schedule(168, 33)
        _, last_allowed = _legacy_schedule(168, 32)
        next_indices, _ = _legacy_schedule(168, 1, progress=last_allowed)
        with self.assertRaises(ValueError):
            self.helper("_batch_trace_entry")(
                next_indices[0], rows, last_allowed, past_end, loss=1.0, gradient_norm=1.0)

    def test_summary_binds_all_completed_indices_ids_progress_and_population(self):
        rows, entries, initial, final = self.completed_trace()
        inputs_before = copy.deepcopy((rows, entries, initial, final))
        policy = self.helper("_policy")(1729)
        summary = self.helper("_trace_summary")(entries, initial, final, policy, rows)

        def independent_digest(value):
            serialized = json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")
            return hashlib.sha256(serialized).hexdigest()

        expected = {
            "schema": "completed-curriculum-batch-trace/v1", "batches": entries,
            "initial_progress": initial, "final_progress": final,
            "completed_updates": 32, "training_count": 168,
            "training_manifest_sha256": independent_digest(rows),
            "batch_size": 12, "batch_order_seed": 1729,
            "batch_order_seed_origin": "inherited_initialization_seed",
            "indices_sha256": independent_digest([entry["indices"] for entry in entries]),
            "ids_sha256": independent_digest([entry["ids"] for entry in entries]),
            "batches_sha256": independent_digest(entries),
            "scope": ("indices_and_IDs_used_by_this_trainer_recorded_after_returned_optimizer_step"
                      "_and_finite_guards"),
            "independent_runtime_trace": False,
            "unreturned_partial_updates_attested": False,
        }
        self.assertEqual(summary, expected)
        self.assertEqual((rows, entries, initial, final), inputs_before)
        summary["batches"][0]["indices"][0] = -1
        summary["batches"][0]["ids"][0] = "changed"
        summary["initial_progress"]["optimizer_steps"] = 99
        summary["final_progress"]["optimizer_steps"] = 99
        self.assertEqual((rows, entries, initial, final), inputs_before)

    def test_summary_refuses_trace_field_sampler_id_and_progress_drift(self):
        rows, entries, initial, final = self.completed_trace(2)
        policy = self.helper("_policy")(1729)
        variants = []
        for field, bad in (
                ("schema", "wrong/v1"), ("optimizer_step", 0), ("loss", True),
                ("gradient_norm_before_clip", -1.0), ("loss", math.nan),
                ("gradient_norm_before_clip", math.inf)):
            changed = copy.deepcopy(entries)
            changed[0][field] = bad
            variants.append((field, changed))
        for field in ("indices", "ids"):
            changed = copy.deepcopy(entries)
            changed[0][field][0], changed[0][field][1] = changed[0][field][1], changed[0][field][0]
            variants.append((field, changed))
        changed = copy.deepcopy(entries)
        changed[0]["indices"][0] = changed[0]["indices"][1]
        variants.append(("duplicate indices", changed))
        changed = copy.deepcopy(entries)
        changed[0]["indices"][0] = 168
        variants.append(("out of range indices", changed))
        for field in ("pre_progress", "post_progress"):
            changed = copy.deepcopy(entries)
            changed[0][field]["optimizer_steps"] += 1
            variants.append((field, changed))
        changed = copy.deepcopy(entries)
        changed[1]["pre_progress"] = copy.deepcopy(ZERO)
        variants.append(("broken chain", changed))
        changed = copy.deepcopy(entries)
        changed[0]["extra"] = False
        variants.append(("extra field", changed))
        variants.extend([("missing entry", entries[:1]), ("reordered entries", entries[::-1])])
        for reason, changed in variants:
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.helper("_trace_summary")(changed, initial, final, policy, rows)
        changed_rows = copy.deepcopy(rows)
        changed_rows[entries[0]["indices"][0]]["id"] = "different identity"
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")(entries, initial, final, policy, changed_rows)
        changed_rows = copy.deepcopy(rows)
        changed_rows[-1]["id"] = changed_rows[0]["id"]
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")(entries, initial, final, policy, changed_rows)
        changed_final = {**final, "optimizer_steps": final["optimizer_steps"] + 1}
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")(entries, initial, changed_final, policy, rows)
        different_sampler = self.helper("_policy")(1729, batch_order_seed=2718)
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")(entries, initial, final, different_sampler, rows)

    def test_summary_supports_exact_resume_and_zero_updates_without_overclaiming(self):
        rows, first, initial, middle = self.completed_trace(16)
        _, second, resumed_initial, final = self.completed_trace(16, progress=middle)
        policy = self.helper("_policy")(1729)
        whole = self.helper("_trace_summary")(first + second, initial, final, policy, rows)
        resumed = self.helper("_trace_summary")(second, resumed_initial, final, policy, rows)
        self.assertEqual(whole["completed_updates"], 32)
        self.assertEqual(resumed["completed_updates"], 16)
        self.assertEqual(resumed["initial_progress"], middle)
        empty = self.helper("_trace_summary")([], final, final, policy, rows)
        self.assertEqual(empty["completed_updates"], 0)
        self.assertEqual(empty["batches"], [])
        self.assertFalse(empty["independent_runtime_trace"])
        self.assertFalse(empty["unreturned_partial_updates_attested"])
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")(first + second + [second[-1]], initial, final, policy, rows)
        invalid = {"epochs_completed": 0, "row_cursor": 1, "optimizer_steps": 0}
        with self.assertRaises(ValueError):
            self.helper("_trace_summary")([], invalid, invalid, policy, rows)

    def test_real_outer_validator_refuses_vanilla_warm_schema_before_continuation_boundary(self):
        validate, checkpoint, calls, boundary = _load_validation_guard()
        vanilla = {"schema": "warm-start-span-legal-formula-checkpoint/v1",
                   "base_checkpoint": {"opaque_synthetic_parent": True}}
        with self.assertRaisesRegex(ValueError, "vanilla warm checkpoints are refused"):
            validate(vanilla)
        self.assertEqual(calls, [])
        with self.assertRaises(boundary):
            validate(checkpoint)
        self.assertEqual(calls, [checkpoint["continuation_checkpoint"]])

    def test_real_outer_validator_rejects_schema_authority_source_and_policy_drift_before_boundary(self):
        validate, checkpoint, calls, boundary = _load_validation_guard()
        mutations = (
            ("schema", "warm-start-span-legal-formula-checkpoint/v1"),
            ("lineage_id", "legacy_continuation"), ("qualified", True),
            ("implementation", {"curriculum_sha256": "d" * 64}),
            ("training_policy_sha256", "0" * 64),
            ("initial_training_policy_sha256", "0" * 64),
        )
        for field, bad in mutations:
            changed = copy.deepcopy(checkpoint)
            changed[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(changed)
            self.assertEqual(calls, [])
        changed = copy.deepcopy(checkpoint)
        changed["training_policy"]["modality_loss_weight"] = 2
        with self.assertRaises(ValueError):
            validate(changed)
        self.assertEqual(calls, [])
        # Even a valid new policy and recomputed current policy hash may not
        # silently replace the independently bound original resume objective.
        changed = copy.deepcopy(checkpoint)
        changed["training_policy"] = self.helper("_policy")(1729, modality_loss_weight=2)
        changed["training_policy_sha256"] = self.helper("checkpoint_digest")(changed["training_policy"])
        with self.assertRaisesRegex(ValueError, "resume must preserve"):
            validate(changed)
        self.assertEqual(calls, [])
        changed = copy.deepcopy(checkpoint)
        changed["extra"] = False
        with self.assertRaises(ValueError):
            validate(changed)
        self.assertEqual(calls, [])
        with self.assertRaises(boundary):
            validate(checkpoint)
        self.assertEqual(len(calls), 1)





