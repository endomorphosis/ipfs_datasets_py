"""Portable 4096-only envelope controls; no model or execution evidence."""
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import inspect
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parents[4]
SOURCE = ROOT / "benchmarks/profile_dimension_guard_costs_v6.py"
SOURCE_SHA = "c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0"
PREDECESSOR_SOURCE = ROOT / "benchmarks/profile_dimension_guard_costs_v5.py"
PREDECESSOR_TESTS = Path(__file__).with_name("test_profile_dimension_guard_costs_v5.py")
PREDECESSOR_SOURCE_SHA = "8c3cf068624bc47e41f90df3bb3217d602f3c17d91b85a797b066b669a9767c0"
PREDECESSOR_TESTS_SHA = "85b9d14defdca81113815b04edaa647a6061bdf981cd1fcefd190fd0615681ce"
ADAPTER_SHA = "7716ea86869c56b5506e62ee45dea159a646759405ae922d5fd5833a84f8b2dd"


def _load(path, name, expected_sha):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("independent portable source pin differs")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if path.read_bytes() != raw:
        raise ValueError("portable source changed during import")
    return module


subject = _load(SOURCE, "_dimension_costs_v6_cpu_controls", SOURCE_SHA)
_load(PREDECESSOR_SOURCE, "_dimension_costs_v5_pinned_predecessor", PREDECESSOR_SOURCE_SHA)
previous_controls = _load(PREDECESSOR_TESTS, "_dimension_costs_v5_preserved_controls", PREDECESSOR_TESTS_SHA)


class _SuccessorSubject:
    def setUp(self):
        self.previous_subject = previous_controls.subject
        previous_controls.subject = subject

    def tearDown(self):
        previous_controls.subject = self.previous_subject


class PreservedIdentityControls(_SuccessorSubject, previous_controls.DimensionCodeIdentityControls):
    """The independently pinned identity-registry controls run unchanged."""


class PreservedProgressControls(_SuccessorSubject, previous_controls.RetainedProgressProvenanceControls):
    """Independent child/parent bytes and all plain progress refusals remain."""


class PreservedRepresentativeTraceControls(_SuccessorSubject, previous_controls.RepresentativeNativeTraceControls):
    """All-count Python scope/overflow/hooks and count-one native bounds remain."""


class Dimension4096CallbackEnvelopeControls(unittest.TestCase):
    def _run(self, **options):
        values = {"dimension": 4096, "expected_profiler_sha256": subject.BASE_COST_PROFILER_SHA,
                  "expected_budget_adapter_sha256": subject.BUDGET_ADAPTER_SHA}
        values.update(options)
        return subject.run("uncreated", "unused", **values)

    def test_exact_eight_million_policy_retains_all_other_bounds_and_false_authority(self):
        self.assertEqual(subject.SCHEMA, "dimension-guard-cost-profiling/v6")
        self.assertEqual(subject.CALLBACK_LIMIT_POLICY, {
            "schema": "dimension-guard-cost-callback-budget/v3", "max_callback_events": 8000000,
            "scope": "all_python_and_c_callbacks_including_unselected_recursive_guard_atoms",
            "selected_span_limit": 20000, "native_operator_postcollection_limit": 50000,
            "global_observer_limits_changed": False, "producer_checks_changed": False})
        for key in ("max_callback_events", "selected_span_limit", "native_operator_postcollection_limit"):
            self.assertIs(type(subject.CALLBACK_LIMIT_POLICY[key]), int)
            self.assertGreater(subject.CALLBACK_LIMIT_POLICY[key], 0)
        self.assertEqual((subject.MAX_SECONDS, subject.MAX_FILE_BYTES, subject.MAX_TOTAL_BYTES),
                         (120, 8388608, 67108864))
        self.assertEqual((subject.ROOT_CPU, subject.ROOT_RAM, subject.ROOT_GPU, subject.ROOT_UNIFIED),
                         (3, 3072, 768, 3840))
        self.assertEqual(subject.NATIVE_OPERATOR_COUNTS, (1,))

    def test_predecessor_positive_768_source_and_controls_remain_exact(self):
        self.assertEqual(hashlib.sha256(PREDECESSOR_SOURCE.read_bytes()).hexdigest(), PREDECESSOR_SOURCE_SHA)
        self.assertEqual(hashlib.sha256(PREDECESSOR_TESTS.read_bytes()).hexdigest(), PREDECESSOR_TESTS_SHA)
        self.assertEqual(previous_controls.subject.CALLBACK_LIMIT_POLICY["max_callback_events"], 4000000)
        self.assertEqual(previous_controls.subject.SCHEMA, "dimension-guard-cost-profiling/v5")

    def test_full_producer_ast_changes_only_declared_scope_policy_and_admission_literals(self):
        old_tree = ast.parse(PREDECESSOR_SOURCE.read_bytes())
        new_tree = ast.parse(SOURCE.read_bytes())
        replacements = {
            "dimension-guard-cost-profiling/v6": "dimension-guard-cost-profiling/v5",
            ADAPTER_SHA: "149ca08c53dc97606a8fe877cbcf8a4dae56b3f67a9a0730e2e697b26458b196",
            "dimension-guard-cost-callback-budget/v3": "dimension-guard-cost-callback-budget/v2",
            "fixed v4 observer budget adapter SHA required": "fixed v3 observer budget adapter SHA required",
            "guard_cost_observer_budget_v4.py": "guard_cost_observer_budget_v3.py"}
        class Normalize(ast.NodeTransformer):
            def visit_Constant(self, node):
                if node.value == 8000000:
                    return ast.Constant(value=4000000)
                if type(node.value) is str and node.value in replacements:
                    return ast.Constant(value=replacements[node.value])
                return node
            def visit_FunctionDef(self, node):
                self.generic_visit(node)
                if node.name == "run":
                    expected = ast.parse('_require(type(dimension) is int and dimension == 4096, "v6 eight-million callback envelope requires exact dimension4096")').body[0]
                    if ast.dump(node.body[0], include_attributes=False) != ast.dump(expected, include_attributes=False):
                        raise AssertionError("exact source-bound 4096-only entry changed")
                    node.body[0] = old_tree.body[next(i for i, item in enumerate(old_tree.body)
                                                   if isinstance(item, ast.FunctionDef) and item.name == "run")].body[0]
                if node.name == "main":
                    matches = [item for item in ast.walk(node) if isinstance(item, ast.Call)
                        and item.args and isinstance(item.args[0], ast.Constant) and item.args[0].value == "--dimension"]
                    if len(matches) != 1:
                        raise AssertionError("one dimension CLI gate required")
                    choices = next(item for item in matches[0].keywords if item.arg == "choices")
                    if ast.literal_eval(choices.value) != (4096,):
                        raise AssertionError("exact 4096-only CLI scope changed")
                    choices.value = ast.Tuple(elts=[ast.Constant(value=768), ast.Constant(value=4096)], ctx=ast.Load())
                return node
        new_tree = Normalize().visit(new_tree)
        old_tree.body.pop(0)
        new_tree.body.pop(0)
        self.assertEqual(ast.dump(new_tree, include_attributes=False), ast.dump(old_tree, include_attributes=False))

    def test_768_other_dimensions_and_non_plain_ints_refuse_before_any_bootstrap(self):
        for dimension in (768, 8, 384, True, 4096.0, "4096", None):
            with self.subTest(dimension=dimension), patch.object(subject, "_bootstrap_coordinator") as bootstrap:
                with self.assertRaisesRegex(ValueError, "exact dimension4096"):
                    self._run(dimension=dimension)
                bootstrap.assert_not_called()

    def test_exact_4096_external_pins_reach_only_controlled_bootstrap_sentinel(self):
        with patch.object(subject, "_bootstrap_coordinator", side_effect=RuntimeError("controlled protocol only")) as bootstrap:
            with self.assertRaisesRegex(RuntimeError, "controlled protocol only"):
                self._run()
            bootstrap.assert_called_once_with()

    def test_predecessor_adapter_or_malformed_pins_refuse_before_bootstrap(self):
        for digest in ("149ca08c53dc97606a8fe877cbcf8a4dae56b3f67a9a0730e2e697b26458b196",
                       "b" * 64, "", True, None, "A" * 64):
            with self.subTest(digest=digest), patch.object(subject, "_bootstrap_coordinator") as bootstrap:
                with self.assertRaisesRegex(ValueError, "budget adapter SHA"):
                    self._run(expected_budget_adapter_sha256=digest)
                bootstrap.assert_not_called()

    def test_new_adapter_current_bytes_policy_and_instance_default_are_independently_pinned(self):
        path = ROOT / "benchmarks/guard_cost_observer_budget_v4.py"
        raw = path.read_bytes()
        self.assertEqual(len(raw), 5771)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ADAPTER_SHA)
        self.assertEqual(subject.BUDGET_ADAPTER_SHA, ADAPTER_SHA)
        tree = ast.parse(raw)
        constants = {item.targets[0].id: ast.literal_eval(item.value) for item in tree.body
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name)
            and isinstance(item.value, ast.Constant)}
        self.assertIs(type(constants["MAX_EVENTS"]), int)
        self.assertEqual(constants["MAX_EVENTS"], 8000000)
        self.assertEqual(constants["POLICY_SCHEMA"], "guard-cost-observer-callback-budget/v4")
        self.assertEqual(constants["BASE_SOURCE_SHA256"], subject.BASE_COST_PROFILER_SHA)

    def test_external_adapter_pin_is_mandatory_not_a_callback_limit_override(self):
        parameter = inspect.signature(subject.run).parameters["expected_budget_adapter_sha256"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        with patch.object(subject, "_bootstrap_coordinator") as bootstrap:
            with self.assertRaises(TypeError):
                self._run(max_events=8000000)
            bootstrap.assert_not_called()

    def test_cli_rejects_768_without_calling_any_authored_run(self):
        args = [str(SOURCE), "--output", "uncreated", "--configuration", "unused", "--dimension", "768",
                "--expected-profiler-sha256", subject.BASE_COST_PROFILER_SHA,
                "--expected-budget-adapter-sha256", ADAPTER_SHA]
        with patch("sys.argv", args), patch.object(subject, "run") as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as refusal:
                subject.main()
            self.assertEqual(refusal.exception.code, 2)
            run.assert_not_called()

    def test_cli_passes_fixed_4096_and_external_pins_to_controlled_protocol(self):
        args = [str(SOURCE), "--output", "uncreated", "--configuration", "unused", "--dimension", "4096",
                "--expected-profiler-sha256", subject.BASE_COST_PROFILER_SHA,
                "--expected-budget-adapter-sha256", ADAPTER_SHA, "--admission-timeout-seconds", "17"]
        result = {"qualified": False, "error": {"type": "ControlledProtocolOnly", "detail": "no execution"}}
        with patch("sys.argv", args), patch.object(subject, "run", return_value=result) as run, redirect_stdout(io.StringIO()):
            self.assertEqual(subject.main(), 1)
        self.assertEqual(run.call_args.kwargs, {"dimension": 4096,
            "expected_profiler_sha256": subject.BASE_COST_PROFILER_SHA,
            "expected_budget_adapter_sha256": ADAPTER_SHA, "admission_timeout_seconds": 17})


if __name__ == "__main__":
    unittest.main()
