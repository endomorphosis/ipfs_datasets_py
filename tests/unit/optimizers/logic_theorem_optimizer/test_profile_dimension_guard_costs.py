"""Portable stdlib controls; authored protocol fixtures are not model evidence."""
import hashlib
import importlib.util
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).absolute().parents[4] / "benchmarks/profile_dimension_guard_costs.py"
specification = importlib.util.spec_from_file_location("_dimension_costs_cpu_controls", SOURCE)
subject = importlib.util.module_from_spec(specification)
specification.loader.exec_module(subject)


def _protocol_framework(calls):
    class Adam:
        def __init__(self):
            calls.append("adam_body")
        def step(self):
            calls.append("adam_step_body")
    class Optimizer:
        def step(self):
            calls.append("optimizer_step_body")
    class Module:
        def train(self, mode=True):
            calls.append(("train_body", mode))
            return self
    def train_decoder():
        calls.append("fit_body")
    return SimpleNamespace(optim=SimpleNamespace(Adam=Adam, Optimizer=Optimizer),
        nn=SimpleNamespace(Module=Module)), {"authored_source": SimpleNamespace(train_decoder=train_decoder)}


def _counters():
    return {"optimizer_constructor_calls": 0, "optimizer_steps": 0, "new_training_fits": 0,
            "training_mode_true_calls": 0, "encoder_calls": 0}


class _ProtocolRegistrar:
    @staticmethod
    def build_registry(modules):
        return {}
    @staticmethod
    def register(registry, label, function, role):
        function = inspect.unwrap(getattr(function, "__func__", function))
        code = function.__code__
        registry[code] = {"label": label, "source_role": role, "function_qualname": code.co_qualname,
            "firstlineno": code.co_firstlineno, "code_sha256": hashlib.sha256(code.co_code).hexdigest(),
            "kind": "generator_segment" if code.co_flags & inspect.CO_GENERATOR else "python"}


class DimensionProfilerProtocolControls(unittest.TestCase):
    def test_dimensions_do_not_invent_a_768_v2_or_native_4096_training(self):
        self.assertEqual(subject.ROUTES[768], ("original", "bitwise_v1"))
        self.assertEqual(subject.ROUTES[4096], ("original", "bitwise_v1", "bitwise_v2"))
        self.assertEqual(subject.COUNTS, (1, 16, 32))
        self.assertEqual(set(subject.FIXTURES[768]), {"checkpoint", "sources", "historical_outputs"})
        self.assertEqual(set(subject.FIXTURES[4096]), {"checkpoint", "rows"})
        self.assertIn("synthetic-untrained-checkpoint", subject.FIXTURES[4096]["checkpoint"][0])

    def test_envelope_resources_bound_all_joint_cuda_children(self):
        self.assertEqual((subject.ROOT_CPU, subject.ROOT_RAM, subject.ROOT_GPU, subject.ROOT_UNIFIED), (3, 3072, 768, 3840))
        self.assertEqual(subject.MAX_SECONDS, 120)
        for width in (768, 4096):
            with self.subTest(width=width):
                routes = len(subject.ROUTES[width])
                self.assertLessEqual(routes, subject.ROOT_CPU)
                self.assertLessEqual(routes * subject.CHILD_RAM, subject.ROOT_RAM)
                self.assertLessEqual(routes * subject.CHILD_GPU, subject.ROOT_GPU)
                self.assertLessEqual(routes * subject.CHILD_UNIFIED, subject.ROOT_UNIFIED)

    def test_fixed_sources_have_plain_exact_sha_shapes(self):
        for pin in [subject.CONFIG_SHA, subject.SCHEDULER_SHA, subject.COORDINATOR_SHA,
                    subject.TRAINED_HELPERS_SHA, subject.SYNTHETIC_HELPERS_SHA, subject.ORDINARY_SPAN_HELPERS_SHA,
                    *subject.FIXED_SOURCES.values(), *(item[1] for fixtures in subject.FIXTURES.values() for item in fixtures.values())]:
            with self.subTest(pin=pin):
                self.assertEqual(type(pin), str)
                self.assertEqual(len(pin), 64)
                self.assertTrue(all(character in "0123456789abcdef" for character in pin))

    def test_preflight_rejects_wrong_dimension_before_helper_or_admission(self):
        for dimension in (8, 384, 768.0, True, "4096", None):
            with self.subTest(dimension=dimension), patch.object(subject, "_bootstrap_coordinator") as boot:
                with self.assertRaises(ValueError):
                    subject.run("uncreated", "unused", dimension=dimension, expected_profiler_sha256="a" * 64)
                boot.assert_not_called()

    def test_preflight_rejects_unbounded_or_boolean_admission_before_helper(self):
        for timeout in (0, 61, True, 1.0, None):
            with self.subTest(timeout=timeout), patch.object(subject, "_bootstrap_coordinator") as boot:
                with self.assertRaises(ValueError):
                    subject.run("uncreated", "unused", dimension=768, expected_profiler_sha256="a" * 64,
                                admission_timeout_seconds=timeout)
                boot.assert_not_called()

    def test_preflight_requires_external_lowercase_profiler_pin_before_helper(self):
        for digest in (None, True, "a" * 63, "a" * 65, "F" * 64, "z" * 64):
            with self.subTest(digest=digest), patch.object(subject, "_bootstrap_coordinator") as boot:
                with self.assertRaises(ValueError):
                    subject.run("uncreated", "unused", dimension=4096, expected_profiler_sha256=digest)
                boot.assert_not_called()

    def test_forbidden_constructor_is_observed_before_authored_body(self):
        calls, counters = [], _counters()
        framework, modules = _protocol_framework(calls)
        with self.assertRaisesRegex(RuntimeError, "optimizer_constructor_calls"):
            with subject._forbidden_calls(framework, modules, counters):
                framework.optim.Adam()
        self.assertEqual(calls, [])
        self.assertEqual(counters["optimizer_constructor_calls"], 1)

    def test_forbidden_steps_are_observed_before_authored_bodies(self):
        for owner in ("Adam", "Optimizer"):
            with self.subTest(owner=owner):
                calls, counters = [], _counters()
                framework, modules = _protocol_framework(calls)
                instance = object.__new__(getattr(framework.optim, owner))
                with self.assertRaisesRegex(RuntimeError, "optimizer_steps"):
                    with subject._forbidden_calls(framework, modules, counters):
                        instance.step()
                self.assertEqual(calls, [])
                self.assertEqual(counters["optimizer_steps"], 1)

    def test_forbidden_fit_is_observed_before_authored_body(self):
        calls, counters = [], _counters()
        framework, modules = _protocol_framework(calls)
        with self.assertRaisesRegex(RuntimeError, "new_training_fits"):
            with subject._forbidden_calls(framework, modules, counters):
                modules["authored_source"].train_decoder()
        self.assertEqual(calls, [])
        self.assertEqual(counters["new_training_fits"], 1)

    def test_eval_mode_allowed_and_true_mode_refuses_before_body(self):
        calls, counters = [], _counters()
        framework, modules = _protocol_framework(calls)
        instance = framework.nn.Module()
        with subject._forbidden_calls(framework, modules, counters):
            instance.train(False)
        self.assertEqual(calls, [("train_body", False)])
        with self.assertRaisesRegex(RuntimeError, "training_mode_true_calls"):
            with subject._forbidden_calls(framework, modules, counters):
                instance.train()
        self.assertEqual(calls, [("train_body", False)])
        self.assertEqual(counters["training_mode_true_calls"], 1)

    def test_counter_observer_chains_and_restores_existing_main_profiler(self):
        calls, counters, observed = [], _counters(), []
        framework, modules = _protocol_framework(calls)
        previous = sys.getprofile()
        def existing(frame, event, arg):
            if event == "call" and frame.f_code is framework.nn.Module.train.__code__:
                observed.append(frame.f_locals.get("mode"))
        sys.setprofile(existing)
        try:
            with subject._forbidden_calls(framework, modules, counters):
                framework.nn.Module().train(False)
            self.assertIs(sys.getprofile(), existing)
            self.assertEqual(observed, [False])
        finally:
            sys.setprofile(previous)

    def test_counter_observer_restores_hook_after_refusal(self):
        calls, counters = [], _counters()
        framework, modules = _protocol_framework(calls)
        previous = sys.getprofile()
        with self.assertRaises(RuntimeError):
            with subject._forbidden_calls(framework, modules, counters):
                framework.optim.Adam()
        self.assertIs(sys.getprofile(), previous)

    def test_registry_selects_high_level_costs_and_omits_recursive_atoms(self):
        def implementation():
            return 1
        def batch():
            return 2
        def recursive_atom():
            return 3
        class Decoder:
            def _decode(self):
                return 4
        class Model:
            def modules(self):
                return [self]
            def forward(self):
                return 5
            def unused_recursive_helper(self):
                return 6
        module = SimpleNamespace(_implementation=implementation, _batch=batch, _freeze=recursive_atom,
            _matches=recursive_atom, SpanLegalFormulaDecoder=Decoder)
        registry = subject._registry(_ProtocolRegistrar, {"legal_span_formula": module},
                                    {"legal_span_formula": Path(__file__)}, Model())
        self.assertEqual(set(registry), {implementation.__code__, batch.__code__, Decoder._decode.__code__, Model.forward.__code__})
        self.assertNotIn(recursive_atom.__code__, registry)
        self.assertNotIn(Model.unused_recursive_helper.__code__, registry)
        for code, descriptor in registry.items():
            self.assertEqual(descriptor["source_role"], "legal_span_formula")
            self.assertEqual(descriptor["firstlineno"], code.co_firstlineno)
            self.assertEqual(descriptor["code_sha256"], hashlib.sha256(code.co_code).hexdigest())

    def test_registry_rejects_foreign_filename_and_empty_selected_scope(self):
        class Model:
            def modules(self):
                return [self]
            def forward(self):
                return 1
        with self.assertRaises(ValueError):
            subject._registry(_ProtocolRegistrar, {}, {"unrelated": Path(__file__).with_name("foreign.py")}, Model())

    def test_registry_bound_is_checked_before_observer_collection(self):
        class Model:
            def modules(self):
                return []
        class Oversized(_ProtocolRegistrar):
            @staticmethod
            def build_registry(modules):
                return {index: {} for index in range(509)}
        with self.assertRaises(ValueError):
            subject._registry(Oversized, {}, {}, Model())

    def test_batched_numeric_rows_preserve_actual_tokens_and_drop_only_padding(self):
        values = {"modality": [[1., 2., 3.], [4., 5., 6.]],
            "presence": [[[1., 2.]] * 4, [[3., 4.]] * 4],
            "start": [[[float(index + token) for token in range(3)] for index in range(6)],
                      [[float(index + token + 10) for token in range(3)] for index in range(6)]],
            "end": [[[float(index + token + 20) for token in range(3)] for index in range(6)],
                    [[float(index + token + 30) for token in range(3)] for index in range(6)]]}
        rows = subject._rows_from_batched_logits(values, [1, 3])
        self.assertEqual(rows[0]["modality"], [[1., 2., 3.]])
        self.assertEqual(rows[0]["presence"], [[[1., 2.]] * 4])
        self.assertEqual(rows[0]["start"], [[[float(index)] for index in range(6)]])
        self.assertEqual(rows[1]["end"], [values["end"][1]])
        rows[1]["end"][0][0][0] = -1.
        self.assertEqual(values["end"][1][0][0], 30.)

    def test_batched_numeric_rows_refuse_missing_or_misdimensioned_actual_axes(self):
        from copy import deepcopy
        valid = {"modality": [[1., 2., 3.]], "presence": [[[1., 2.]] * 4],
                 "start": [[[1., 2.]] * 6], "end": [[[3., 4.]] * 6]}
        corruptions = []
        for name in valid:
            changed = deepcopy(valid)
            changed[name] = []
            corruptions.append(changed)
        for name in ("start", "end"):
            changed = deepcopy(valid)
            changed[name][0][0] = [1.]
            corruptions.append(changed)
        changed = deepcopy(valid)
        changed["start"][0][0][0] = float("nan")
        corruptions.append(changed)
        changed = deepcopy(valid)
        changed["modality"][0][0] = True
        corruptions.append(changed)
        for values in corruptions:
            with self.subTest(values=values), self.assertRaises(ValueError):
                subject._rows_from_batched_logits(values, [2])
        for lengths in ([], [True], [0], [257], [2.], [1, 2]):
            with self.subTest(lengths=lengths), self.assertRaises(ValueError):
                subject._rows_from_batched_logits(valid, lengths)

    def test_synthetic_lane_omits_all_embedding_receipt_parameters(self):
        captured = []
        class Owner:
            _lease = SimpleNamespace(lease_id="authored", released=False)
            def decode_formal_logic(self, texts, vectors, **options):
                captured.append(options)
                texts[0], vectors[0][0] = "changed", 10.
                return {"controlled_protocol_only": True}
        inputs = {"texts": ["source"], "vectors": [[1.]], "receipts": [{"irrelevant": True}], "receipt_pins": ["a" * 64]}
        subject.DimensionLane(Owner(), 4096).call(inputs, 1)
        self.assertEqual(captured, [{}])
        self.assertEqual(inputs["texts"], ["source"])
        self.assertEqual(inputs["vectors"], [[1.]])

    def test_historical768_lane_copies_receipts_and_preserves_supplied_content_pins(self):
        captured = []
        class Owner:
            _lease = SimpleNamespace(lease_id="authored", released=False)
            def decode_formal_logic(self, texts, vectors, **options):
                captured.append(options["expected_receipt_sha256s"])
                options["embedding_receipts"][0]["field"] = "changed"
                return {"controlled_protocol_only": True}
        inputs = {"texts": ["source"], "vectors": [[1.]], "receipts": [{"field": "original"}], "receipt_pins": ["a" * 64]}
        subject.DimensionLane(Owner(), 768).call(inputs, 1)
        self.assertEqual(captured, [["a" * 64]])
        self.assertEqual(inputs["receipts"], [{"field": "original"}])

    def test_owned_close_is_idempotent_and_requires_child_release(self):
        class Owner:
            def __init__(self):
                self._lease = SimpleNamespace(lease_id="authored", released=False)
                self.closes = 0
            def close(self):
                self.closes += 1
                self._lease.released = True
        owner = Owner()
        lane = subject.DimensionLane(owner, 768)
        lane.close(None, None)
        lane.close(None, None)
        self.assertEqual(owner.closes, 1)
        self.assertIsNone(lane.owner)
        self.assertTrue(lane.child_lease.released)

    def test_nonreleasing_owner_refuses_cleanup_success(self):
        class Owner:
            _lease = SimpleNamespace(lease_id="authored", released=False)
            def close(self):
                pass
        with self.assertRaises(ValueError):
            subject.DimensionLane(Owner(), 4096).close(None, None)


if __name__ == "__main__":
    unittest.main()
