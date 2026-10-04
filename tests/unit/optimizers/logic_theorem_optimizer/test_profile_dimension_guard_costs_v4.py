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
SOURCE = ROOT / "benchmarks/profile_dimension_guard_costs_v4.py"
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


subject = _load(SOURCE, "_dimension_costs_v4_cpu_controls")
original_controls = _load(ORIGINAL_TESTS, "_dimension_costs_original_cpu_controls", ORIGINAL_TESTS_SHA)
original_subject = original_controls.subject


class PreservedIdentityDimensionProtocolControls(original_controls.DimensionProfilerProtocolControls):
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
        self.previous_registrar = original_controls._ProtocolRegistrar
        class ProtocolRegistrar(self.previous_registrar):
            # Legacy authored controls have distinct code bodies, so their
            # old set-of-code assertions remain portable. Dedicated controls
            # below exercise the actual identity-keyed current helper.
            registry_key = staticmethod(lambda code: code)
        original_controls._ProtocolRegistrar = ProtocolRegistrar

    def tearDown(self):
        original_controls.subject = original_subject
        original_controls._ProtocolRegistrar = self.previous_registrar


class DimensionIdentityCallbackBudgetControls(unittest.TestCase):
    def test_successor_schema_and_plain_callback_policy_are_explicit(self):
        self.assertEqual(subject.SCHEMA, "dimension-guard-cost-profiling/v4")
        policy = subject.CALLBACK_LIMIT_POLICY
        self.assertEqual(policy["schema"], "dimension-guard-cost-callback-budget/v2")
        self.assertEqual(type(policy["max_callback_events"]), int)
        self.assertEqual(policy["max_callback_events"], 4000000)
        self.assertEqual(policy["selected_span_limit"], 20000)
        self.assertEqual(policy["native_operator_postcollection_limit"], 50000)
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
            with self.assertRaisesRegex(ValueError, "fixed v3 observer budget adapter"):
                subject.run("uncreated", "unused", dimension=4096,
                    expected_profiler_sha256=subject.BASE_COST_PROFILER_SHA,
                    expected_budget_adapter_sha256="b" * 64)
            bootstrap.assert_not_called()

    def test_original_sources_and_portable_controls_remain_exact(self):
        self.assertEqual(hashlib.sha256(ORIGINAL_SOURCE.read_bytes()).hexdigest(), ORIGINAL_SOURCE_SHA)
        self.assertEqual(hashlib.sha256(ORIGINAL_TESTS.read_bytes()).hexdigest(), ORIGINAL_TESTS_SHA)

    def test_original_profiler_bytes_remain_exact_without_import(self):
        raw = (ROOT / "benchmarks/profile_formula_guard_costs_v2.py").read_bytes()
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


class DimensionCodeIdentityControls(unittest.TestCase):
    def _profiler(self):
        return _load(ROOT / "benchmarks/profile_formula_guard_costs_v2.py",
                     "_dimension_current_identity_protocol_helper", subject.BASE_COST_PROFILER_SHA)

    @staticmethod
    def _authored(role):
        path = ROOT / "benchmarks" / ("controlled-" + role + ".py")
        namespace = {}
        exec(compile("def _implementation():\n    return 1\n", str(path), "exec"), namespace)
        return namespace["_implementation"], path

    def test_equal_structural_code_objects_keep_distinct_source_roles_and_strong_references(self):
        first, first_path = self._authored("first")
        second, second_path = self._authored("second")
        self.assertEqual(first.__code__, second.__code__)
        self.assertIsNot(first.__code__, second.__code__)
        class Model:
            def modules(self):
                return []
        from types import SimpleNamespace
        helper = self._profiler()
        registry = subject._registry(helper,
            {"legal_span_formula": SimpleNamespace(_implementation=first, SpanLegalFormulaDecoder=type("Empty", (), {})),
             "legal_span_dimensions": SimpleNamespace(_implementation=second)},
            {"legal_span_formula": first_path, "legal_span_dimensions": second_path}, Model())
        self.assertEqual(len(registry), 2)
        for function, role in ((first, "legal_span_formula"), (second, "legal_span_dimensions")):
            key = helper.registry_key(function.__code__)
            self.assertIn(key, registry)
            self.assertEqual(key[0], id(function.__code__))
            self.assertIs(next(item[1] for item in registry if item[0] == key[0]), function.__code__)
            self.assertEqual(registry[key]["source_role"], role)
        self.assertNotEqual(helper.registry_key(first.__code__), helper.registry_key(second.__code__))

    def test_same_exact_code_alias_is_registered_only_once(self):
        function, path = self._authored("shared")
        class Model:
            def modules(self):
                return []
        helper = self._profiler()
        from types import SimpleNamespace
        registry = subject._registry(helper,
            {"legal_span_formula": SimpleNamespace(_implementation=function, _batch=function,
                 SpanLegalFormulaDecoder=type("Empty", (), {}))}, {"legal_span_formula": path}, Model())
        self.assertEqual(len(registry), 1)
        self.assertIn(helper.registry_key(function.__code__), registry)


class RetainedProgressProvenanceControls(unittest.TestCase):
    """Authored JSON content pins exercise provenance without training/models."""
    @staticmethod
    def _digest(value):
        return hashlib.sha256(subject._wire(value)).hexdigest()

    def _authored(self, dimension):
        parent = ({"progress": {"epochs_completed": 1, "optimizer_steps": 3, "row_cursor": 2},
                   "model_state": {"controlled_protocol_only": [[0.]]}} if dimension == 768 else None)
        parent_sha = self._digest(parent) if parent is not None else None
        checkpoint = {"progress": {"epochs_completed": 0, "optimizer_steps": 1 if dimension == 768 else 0,
                                   "row_cursor": 2 if dimension == 768 else 0},
            "source_parent_checkpoint": parent, "source_parent_checkpoint_sha256": parent_sha,
            "source_parent_optimizer_steps": 3 if dimension == 768 else 0,
            "model_state": {"controlled_protocol_only": [[1.]]}}
        return checkpoint, self._digest(checkpoint), parent_sha

    def test_authored_one_step_child_three_step_parent_binds_both_independent_byte_pins(self):
        checkpoint, digest, parent_sha = self._authored(768)
        binding = subject._retained_progress_binding(checkpoint, 768,
            expected_checkpoint_sha256=digest, expected_parent_sha256=parent_sha)
        self.assertEqual(binding["checkpoint_sha256"], digest)
        self.assertEqual(binding["checkpoint_progress"], {"epochs_completed": 0, "optimizer_steps": 1, "row_cursor": 2})
        self.assertEqual(binding["source_parent_checkpoint_sha256"], parent_sha)
        self.assertEqual(binding["source_parent_optimizer_steps"], 3)
        self.assertEqual(binding["source_parent_progress"], {"epochs_completed": 1, "optimizer_steps": 3, "row_cursor": 2})
        for flag in ("training_execution_authenticated", "model_quality_qualified", "new_training_execution_claimed"):
            self.assertIs(binding[flag], False)

    def test_authored_zero_step_synthetic_checkpoint_binds_absent_parent(self):
        checkpoint, digest, parent_sha = self._authored(4096)
        binding = subject._retained_progress_binding(checkpoint, 4096,
            expected_checkpoint_sha256=digest, expected_parent_sha256=parent_sha)
        self.assertEqual(binding["checkpoint_progress"], {"epochs_completed": 0, "optimizer_steps": 0, "row_cursor": 0})
        self.assertIsNone(binding["source_parent_checkpoint_sha256"])
        self.assertIsNone(binding["source_parent_progress"])
        self.assertEqual(type(binding["source_parent_optimizer_steps"]), int)
        self.assertEqual(binding["source_parent_optimizer_steps"], 0)

    def test_old_thirty_step_or_wrong_typed_child_progress_refuses_even_with_recomputed_checkpoint_pin(self):
        for value in (30, 0, True, 1.0, "1"):
            checkpoint, _, parent_sha = self._authored(768)
            checkpoint["progress"]["optimizer_steps"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "exact retained checkpoint progress"):
                subject._retained_progress_binding(checkpoint, 768,
                    expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_missing_extra_epoch_or_cursor_progress_fields_refuse(self):
        for change in ("missing", "extra", "epoch", "cursor"):
            checkpoint, _, parent_sha = self._authored(768)
            progress = checkpoint["progress"]
            if change == "missing":
                progress.pop("row_cursor")
            elif change == "extra":
                progress["unsupported"] = 0
            else:
                progress["epochs_completed" if change == "epoch" else "row_cursor"] += 1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "exact retained checkpoint progress"):
                subject._retained_progress_binding(checkpoint, 768,
                    expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_checkpoint_content_tamper_cannot_keep_independent_expected_pin(self):
        checkpoint, digest, parent_sha = self._authored(768)
        checkpoint["model_state"]["controlled_protocol_only"][0][0] = 2.
        with self.assertRaisesRegex(ValueError, "checkpoint content differs"):
            subject._retained_progress_binding(checkpoint, 768,
                expected_checkpoint_sha256=digest, expected_parent_sha256=parent_sha)

    def test_parent_model_and_claimed_parent_pin_paired_tamper_cannot_change_independent_parent_pin(self):
        checkpoint, _, parent_sha = self._authored(768)
        checkpoint["source_parent_checkpoint"]["model_state"]["controlled_protocol_only"][0][0] = 2.
        checkpoint["source_parent_checkpoint_sha256"] = self._digest(checkpoint["source_parent_checkpoint"])
        with self.assertRaisesRegex(ValueError, "source-parent checkpoint bytes"):
            subject._retained_progress_binding(checkpoint, 768,
                expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_parent_model_tamper_without_updating_claimed_pin_refuses(self):
        checkpoint, _, parent_sha = self._authored(768)
        checkpoint["source_parent_checkpoint"]["model_state"]["controlled_protocol_only"][0][0] = -0.
        with self.assertRaisesRegex(ValueError, "source-parent checkpoint bytes"):
            subject._retained_progress_binding(checkpoint, 768,
                expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_wrong_parent_progress_refuses_even_with_recomputed_content_pins(self):
        for field, value in (("optimizer_steps", 30), ("optimizer_steps", 3.0),
                             ("epochs_completed", True), ("row_cursor", 0)):
            checkpoint, _, _ = self._authored(768)
            checkpoint["source_parent_checkpoint"]["progress"][field] = value
            parent_sha = self._digest(checkpoint["source_parent_checkpoint"])
            checkpoint["source_parent_checkpoint_sha256"] = parent_sha
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "exact retained source-parent progress"):
                subject._retained_progress_binding(checkpoint, 768,
                    expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_wrong_or_boolean_source_parent_step_count_refuses(self):
        for dimension, value in ((768, 1), (768, 3.0), (768, True), (4096, False), (4096, 0.0), (4096, 1)):
            checkpoint, _, parent_sha = self._authored(dimension)
            checkpoint["source_parent_optimizer_steps"] = value
            with self.subTest(dimension=dimension, value=value), self.assertRaises(ValueError):
                subject._retained_progress_binding(checkpoint, dimension,
                    expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=parent_sha)

    def test_synthetic_checkpoint_refuses_any_inherited_parent(self):
        checkpoint, _, _ = self._authored(4096)
        checkpoint["source_parent_checkpoint"] = {"progress": {"optimizer_steps": 0}}
        with self.assertRaisesRegex(ValueError, "synthetic zero-step"):
            subject._retained_progress_binding(checkpoint, 4096,
                expected_checkpoint_sha256=self._digest(checkpoint), expected_parent_sha256=None)

    def test_binding_progress_snapshots_do_not_alias_checkpoint_inputs(self):
        checkpoint, digest, parent_sha = self._authored(768)
        binding = subject._retained_progress_binding(checkpoint, 768,
            expected_checkpoint_sha256=digest, expected_parent_sha256=parent_sha)
        binding["checkpoint_progress"]["optimizer_steps"] = 30
        binding["source_parent_progress"]["optimizer_steps"] = 30
        self.assertEqual(checkpoint["progress"]["optimizer_steps"], 1)
        self.assertEqual(checkpoint["source_parent_checkpoint"]["progress"]["optimizer_steps"], 3)

    def test_fixed_native_event_cap_is_plain_positive_and_within_shared_bound(self):
        self.assertEqual(type(subject.NATIVE_OPERATOR_EVENT_LIMIT), int)
        self.assertEqual(subject.NATIVE_OPERATOR_EVENT_LIMIT, 50000)
        self.assertGreater(subject.NATIVE_OPERATOR_EVENT_LIMIT, 0)
        self.assertEqual(subject.CALLBACK_LIMIT_POLICY["native_operator_postcollection_limit"], 50000)
        self.assertEqual((subject.MAX_FILE_BYTES, subject.MAX_TOTAL_BYTES, subject.MAX_SECONDS),
                         (8388608, 67108864, 120))

    def test_native_event_cap_is_not_a_caller_cli_override(self):
        arguments = [str(SOURCE), "--output", "uncreated", "--configuration", "unused", "--dimension", "4096",
            "--expected-profiler-sha256", subject.BASE_COST_PROFILER_SHA,
            "--expected-budget-adapter-sha256", subject.BUDGET_ADAPTER_SHA,
            "--max-operator-events", "50001"]
        with patch("sys.argv", arguments), patch.object(subject, "run") as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as refusal:
                subject.main()
            self.assertEqual(refusal.exception.code, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
