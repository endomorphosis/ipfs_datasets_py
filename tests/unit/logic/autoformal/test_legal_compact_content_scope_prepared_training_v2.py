"""Pure custody checks, invoked by the admitted native worker before training.

The caller supplies the canonically loaded v2 module. No package roots are
imported here, no model is allocated, and no on-disk source is changed. Source
witness injection is explicitly simulated; loaded-origin and input mutations
are actual changes in this isolated process and are restored in finally.
"""
from copy import deepcopy
import unittest


def run_tests(prepared_module):
    owner = prepared_module

    def fixture():
        return {"checkpoint": {"x": [1, 2], "raw": b"\x00\xff"},
                "expected": "fixture-only", "max_steps": 2}

    class CustodyTests(unittest.TestCase):
        def test_01_happy_detached_capture_and_repeat_fences(self):
            original = fixture()
            with owner._scope(original) as (captured, modules, fence):
                self.assertEqual(captured, original)
                self.assertIsNot(captured, original)
                self.assertIsNot(captured["checkpoint"], original["checkpoint"])
                self.assertIn("tokens", modules)
                self.assertIn("scope_pins", modules)
                fence()
                fence()

        def test_02_borrowed_input_mutation(self):
            original = fixture()
            with owner._scope(original) as (_, _, fence):
                original["checkpoint"]["x"].append(3)
                try:
                    with self.assertRaisesRegex(ValueError, "input changed"):
                        fence()
                finally:
                    original["checkpoint"]["x"].pop()
                fence()

        def test_03_captured_input_mutation(self):
            with owner._scope(fixture()) as (captured, _, fence):
                captured["checkpoint"]["x"][0] = 7
                try:
                    with self.assertRaisesRegex(ValueError, "input changed"):
                        fence()
                finally:
                    captured["checkpoint"]["x"][0] = 1
                fence()

        def test_04_closing_checks_borrowed_input(self):
            original = fixture()
            with self.assertRaisesRegex(ValueError, "input changed"):
                with owner._scope(original):
                    original["checkpoint"]["x"].append(3)

        def test_05_closing_checks_captured_input(self):
            with self.assertRaisesRegex(ValueError, "input changed"):
                with owner._scope(fixture()) as (captured, _, _):
                    captured["checkpoint"]["x"].append(3)

        def test_06_loaded_baseline_origin(self):
            with owner._scope(fixture()) as (_, modules, fence):
                module = modules["head"]
                old = module.__file__
                module.__file__ = old + ".wrong-origin"
                try:
                    with self.assertRaisesRegex(ValueError, "origin"):
                        fence()
                finally:
                    module.__file__ = old
                fence()

        def test_07_loaded_scope_origin(self):
            with owner._scope(fixture()) as (_, modules, fence):
                module = modules["scope"]
                old = module.__file__
                module.__file__ = old + ".wrong-origin"
                try:
                    with self.assertRaisesRegex(ValueError, "origin"):
                        fence()
                finally:
                    module.__file__ = old
                fence()

        def test_08_simulated_weighted_source_witness(self):
            with owner._scope(fixture()) as (_, modules, fence):
                module = modules["weighted"]
                old = module._sources
                root, pins = old()
                module._sources = lambda: (root, [*pins, ("simulated-change",)])
                try:
                    with self.assertRaisesRegex(ValueError, "custody"):
                        fence()
                finally:
                    module._sources = old
                fence()

        def test_09_simulated_scope_dependency_witness(self):
            with owner._scope(fixture()) as (_, modules, fence):
                module = modules["scope"]
                old = module._owners
                selector, tokens, pins = old()
                changed = deepcopy(pins)
                # Preserve the container type while changing its commitment.
                if type(changed) is dict:
                    changed["simulated-only"] = "changed"
                elif type(changed) is list:
                    changed.append("simulated-only")
                else:
                    changed = (changed, "simulated-only")
                module._owners = lambda: (selector, tokens, changed)
                try:
                    with self.assertRaisesRegex(ValueError, "custody"):
                        fence()
                finally:
                    module._owners = old
                fence()

        def test_10_fast_helper_origin(self):
            _, owners, _ = owner._owners()
            helper = owners["fingerprint"]
            with owner._scope(fixture()) as (_, _, fence):
                old = helper.__file__
                helper.__file__ = old + ".wrong-origin"
                try:
                    with self.assertRaisesRegex(ValueError, "origin"):
                        fence()
                finally:
                    helper.__file__ = old
                fence()

        def test_11_legacy_hash_and_scope_are_not_entered(self):
            with owner._scope(fixture()) as (_, modules, _):
                head, weighted = modules["head"], modules["weighted"]
            old_hash, old_scope = head._fingerprint, weighted._scope
            calls = []

            def forbidden(*args, **kwargs):
                calls.append("legacy-call")
                raise AssertionError("legacy input hash/context entered")

            head._fingerprint = weighted._scope = forbidden
            try:
                with owner._scope(fixture()) as (_, _, fence):
                    fence()
                self.assertEqual(calls, [])
            finally:
                head._fingerprint, weighted._scope = old_hash, old_scope

        def test_12_invalid_original_rejected_before_yield(self):
            for value in (float("nan"), {"x": object()}, {"x": 2**63}):
                with self.subTest(kind=type(value).__name__):
                    with self.assertRaises(ValueError):
                        with owner._scope(value):
                            self.fail("unsupported input yielded")

        def test_13_cycles_rejected_before_yield(self):
            value = []
            value.append(value)
            with self.assertRaises(ValueError):
                with owner._scope(value):
                    self.fail("cyclic input yielded")

        def test_14_body_error_preserved_with_closing_failure(self):
            class BodyError(RuntimeError):
                pass
            original = fixture()
            with self.assertRaisesRegex(BodyError, "body-witness"):
                with owner._scope(original):
                    original["checkpoint"]["x"].append(3)
                    raise BodyError("body-witness")

    class Result(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.successes = []

        def addSuccess(self, test):
            super().addSuccess(test)
            self.successes.append(test._testMethodName)

    result = Result()
    unittest.defaultTestLoader.loadTestsFromTestCase(CustodyTests).run(result)
    return {"schema": "legal-fast-prepared-pure-custody-tests/v1",
            "passed": result.wasSuccessful(), "tests_run": result.testsRun,
            "successful_tests": result.successes,
            "failures": [{"test": test._testMethodName, "traceback": trace[-2048:]}
                         for test, trace in result.failures + result.errors],
            "scope": "pure custody, no checkpoint validation or numerical allocation",
            "source_witness_changes": "simulated in-process only; source files unchanged",
            "loaded_origin_changes": "actual in-process __file__ changes restored in finally",
            "production_sources_modified": False}
