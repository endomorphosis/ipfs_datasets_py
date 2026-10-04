"""Portable callback-envelope controls; authored protocols are not model evidence."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import inspect
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parents[4]
SOURCE = ROOT / "benchmarks/profile_dimension_guard_costs_v2.py"
ORIGINAL_SOURCE = ROOT / "benchmarks/profile_dimension_guard_costs.py"
ORIGINAL_TESTS = Path(__file__).with_name("test_profile_dimension_guard_costs.py")
ORIGINAL_SOURCE_SHA = "cabc64a5479c92ac52cb577673f36615176d4660d6bc4956666c98748b7c584c"
ORIGINAL_TESTS_SHA = "2a911684c17282f4b10c9f8786a60970377e19ec1ed3747885107e7a0b204b9b"


def _load(path, name, expected_sha=None):
    raw = path.read_bytes()
    if expected_sha is not None and hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("preserved portable helper pin changed")
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    if path.read_bytes() != raw:
        raise ValueError("portable helper changed during import")
    return module


subject = _load(SOURCE, "_dimension_costs_v2_cpu_controls")
original_controls = _load(ORIGINAL_TESTS, "_dimension_costs_original_cpu_controls", ORIGINAL_TESTS_SHA)
original_subject = original_controls.subject


class PreservedDimensionProtocolControls(original_controls.DimensionProfilerProtocolControls):
    """Apply the preserved twenty-one controls to this successor's common code."""
    def setUp(self):
        # The original preflight controls target the old signature. The
        # explicit authored adapter pin here only bridges that signature;
        # separate controls below exercise missing/wrong adapter admission.
        values = {name: value for name, value in vars(subject).items() if not name.startswith("__")}
        def run(*args, **options):
            options.setdefault("expected_budget_adapter_sha256", subject.BUDGET_ADAPTER_SHA)
            return subject.run(*args, **options)
        values["run"] = run
        original_controls.subject = SimpleNamespace(**values)

    def tearDown(self):
        original_controls.subject = original_subject


class DimensionCallbackBudgetControls(unittest.TestCase):
    def test_successor_schema_and_plain_callback_policy_are_explicit(self):
        self.assertEqual(subject.SCHEMA, "dimension-guard-cost-profiling/v2")
        policy = subject.CALLBACK_LIMIT_POLICY
        self.assertEqual(policy["schema"], "dimension-guard-cost-callback-budget/v2")
        self.assertEqual(type(policy["max_callback_events"]), int)
        self.assertEqual(policy["max_callback_events"], 4000000)
        self.assertEqual(policy["selected_span_limit"], 20000)
        self.assertEqual(policy["native_operator_postcollection_limit"], 15000)
        self.assertIs(policy["global_observer_limits_changed"], False)
        self.assertIs(policy["producer_checks_changed"], False)
        self.assertIn("unselected_recursive_guard_atoms", policy["scope"])

    def test_budget_adapter_pin_is_a_required_keyword(self):
        parameter = inspect.signature(subject.run).parameters["expected_budget_adapter_sha256"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_missing_adapter_pin_refuses_before_bootstrap_or_output(self):
        with patch.object(subject, "_bootstrap_coordinator") as bootstrap:
            with self.assertRaises(TypeError):
                subject.run("uncreated", "unused", dimension=768,
                            expected_profiler_sha256=subject.BASE_COST_PROFILER_SHA)
            bootstrap.assert_not_called()

    def test_malformed_adapter_pin_refuses_before_bootstrap_or_output(self):
        for digest in (None, True, 10, "", "a" * 63, "a" * 65, "A" * 64, "z" * 64):
            with self.subTest(digest=digest), patch.object(subject, "_bootstrap_coordinator") as bootstrap:
                with self.assertRaisesRegex(ValueError, "budget adapter SHA"):
                    subject.run("uncreated", "unused", dimension=4096,
                        expected_profiler_sha256=subject.BASE_COST_PROFILER_SHA,
                        expected_budget_adapter_sha256=digest)
                bootstrap.assert_not_called()

    def test_adapter_requires_original_qualified_base_profiler_sha(self):
        with patch.object(subject, "_bootstrap_coordinator") as bootstrap:
            with self.assertRaisesRegex(ValueError, "original qualified profiling utility"):
                subject.run("uncreated", "unused", dimension=768,
                    expected_profiler_sha256="a" * 64, expected_budget_adapter_sha256="b" * 64)
            bootstrap.assert_not_called()

    def test_valid_external_pins_reach_only_authored_bootstrap_sentinel(self):
        sentinel = RuntimeError("controlled protocol sentinel before any file or admission")
        with patch.object(subject, "_bootstrap_coordinator", side_effect=sentinel) as bootstrap:
            with self.assertRaisesRegex(RuntimeError, "controlled protocol sentinel"):
                subject.run("uncreated", "unused", dimension=768,
                    expected_profiler_sha256=subject.BASE_COST_PROFILER_SHA,
                    expected_budget_adapter_sha256=subject.BUDGET_ADAPTER_SHA)
            bootstrap.assert_called_once_with()

    def test_valid_shape_but_wrong_adapter_pin_refuses_before_bootstrap(self):
        with patch.object(subject, "_bootstrap_coordinator") as bootstrap:
            with self.assertRaisesRegex(ValueError, "fixed v2 observer budget adapter"):
                subject.run("uncreated", "unused", dimension=4096,
                    expected_profiler_sha256=subject.BASE_COST_PROFILER_SHA,
                    expected_budget_adapter_sha256="b" * 64)
            bootstrap.assert_not_called()

    def test_original_sources_and_portable_controls_remain_exact(self):
        self.assertEqual(hashlib.sha256(ORIGINAL_SOURCE.read_bytes()).hexdigest(), ORIGINAL_SOURCE_SHA)
        self.assertEqual(hashlib.sha256(ORIGINAL_TESTS.read_bytes()).hexdigest(), ORIGINAL_TESTS_SHA)

    def test_original_profiler_bytes_remain_exact_without_import(self):
        raw = (ROOT / "benchmarks/profile_formula_guard_costs.py").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), subject.BASE_COST_PROFILER_SHA)

    def test_callback_change_keeps_dimension_and_resource_scopes(self):
        self.assertEqual(subject.ROUTES, original_subject.ROUTES)
        self.assertEqual(subject.FIXTURES, original_subject.FIXTURES)
        self.assertEqual(subject.FIXED_SOURCES, original_subject.FIXED_SOURCES)
        self.assertEqual(subject.MAX_SECONDS, 120)
        self.assertEqual((subject.ROOT_CPU, subject.ROOT_RAM, subject.ROOT_GPU, subject.ROOT_UNIFIED),
                         (3, 3072, 768, 3840))
        self.assertNotIn(768, {width for width, routes in subject.ROUTES.items() if "bitwise_v2" in routes})

    def test_cli_missing_adapter_pin_refuses_before_authored_run(self):
        arguments = [str(SOURCE), "--output", "uncreated", "--configuration", "unused",
            "--dimension", "4096", "--expected-profiler-sha256", subject.BASE_COST_PROFILER_SHA]
        with patch("sys.argv", arguments), patch.object(subject, "run") as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as refusal:
                subject.main()
            self.assertEqual(refusal.exception.code, 2)
            run.assert_not_called()

    def test_cli_passes_both_external_pins_and_admission_scope_to_authored_run(self):
        arguments = [str(SOURCE), "--output", "uncreated", "--configuration", "unused", "--dimension", "768",
            "--expected-profiler-sha256", subject.BASE_COST_PROFILER_SHA,
            "--expected-budget-adapter-sha256", "b" * 64, "--admission-timeout-seconds", "17"]
        refusal = {"qualified": False, "error": {"type": "ControlledProtocolOnly", "detail": "no runtime"}}
        with (patch("sys.argv", arguments), patch.object(subject, "run", return_value=refusal) as run,
              redirect_stdout(io.StringIO())):
            self.assertEqual(subject.main(), 1)
        self.assertEqual(run.call_args.kwargs, {"dimension": 768,
            "expected_profiler_sha256": subject.BASE_COST_PROFILER_SHA,
            "expected_budget_adapter_sha256": "b" * 64, "admission_timeout_seconds": 17})


if __name__ == "__main__":
    unittest.main()
