"""Authored ordinary profiling-data controls; no tensor/model execution.

Tiny fictional spans/operators exercise reader custody and arithmetic rules.
They do not stand in for the separately pinned native profiling archives.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).absolute().parents[4] / "benchmarks/audit_formula_guard_costs_v5.py"
SOURCE_SHA = "9552de463d7577a5715f5b3a9c6fcfe6278ba1fd18c35bbe22f9f631df403209"


def load_reader():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("current profiling reader changed")
    specification = importlib.util.spec_from_file_location("_authored_guard_cost_reader", SOURCE)
    module = importlib.util.module_from_spec(specification)
    exec(compile(raw, str(SOURCE), "exec"), module.__dict__)
    return module


def python_fixture(reader):
    raw = b"def selected():\n    return 1\nclass Scheduler:\n    def _locked_state(self):\n        yield None\n"
    codes = reader._code_inventory(raw, "/fictional/current/source.py")
    one = next(item for item in codes if item[0] == "selected")
    locked = next(item for item in codes if item[0] == "Scheduler._locked_state")
    registry = [{"id": 0, "label": "selected", "source_role": "benchmark", "function_qualname": one[0],
        "firstlineno": one[1], "code_sha256": one[2], "kind": "python"},
        {"id": 1, "label": "locked", "source_role": "resource_scheduler", "function_qualname": locked[0],
         "firstlineno": locked[1], "code_sha256": locked[2], "kind": "generator_segment"},
        {"id": 2, "label": "complete_public_call", "source_role": "benchmark", "function_qualname": "complete_public_call",
         "firstlineno": 0, "code_sha256": None, "kind": "manual"},
        {"id": 3, "label": "os.fsync", "source_role": "resource_scheduler", "function_qualname": "os.fsync",
         "firstlineno": 0, "code_sha256": None, "kind": "cfunction"},
        {"id": 4, "label": "fcntl.flock", "source_role": "resource_scheduler", "function_qualname": "fcntl.flock",
         "firstlineno": 0, "code_sha256": None, "kind": "cfunction"},
        {"id": 5, "label": "os.replace", "source_role": "resource_scheduler", "function_qualname": "os.replace",
         "firstlineno": 0, "code_sha256": None, "kind": "cfunction"}]
    spans = [[1, 0, 7, 2, 10, 110, 100, 150, 100, 40, 50, 30, "manual_return"],
             [2, 1, 7, 0, 20, 80, 110, 130, 60, 30, 20, 10, "return"],
             [3, 2, 7, 1, 30, 60, 115, 125, 30, 20, 10, 6, "return"],
             [4, 3, 7, 3, 40, 50, 118, 122, 10, 10, 4, 4, "c_return"]]
    value = {"schema": "source-bound-guard-call-costs/v1", "instrumented": True, "performance_qualified": False,
        "clock": {"wall": "perf_counter_ns", "cpu": "thread_time_ns", "operator_clock_alignment_claimed": False},
        "exclusive_scope": "inclusive_minus_direct_selected_children_unselected_work_stays_with_parent",
        "generator_scope": "resumption_segments_not_logical_transactions",
        "background_scope": "windowed_owned_python_threads_prior_default_none_edges_censored_no_whole_job_coverage",
        "background_activity_claim": "observed_events_only_absence_is_not_zero_activity_attestation",
        "background_censor_scope": "complete_spans_only_partial_start_or_end_not_added_to_completed_costs",
        "observer_overhead_scope": "callback_and_native_profiler_overhead_included_not_measured_or_subtracted",
        "main_thread_id": 7, "window_start_ns": 1, "window_end_ns": 120, "callback_events_observed": 100,
        "bounds": {"max_events": 1000000, "max_spans": 20000, "max_threads": 32}, "overflow": False,
        "unsupported_thread_observed": False, "hooks_restored": True, "censored_background": [],
        "registry": registry, "threads": [{"thread_id": 7, "scope": "inline_main"}],
        "span_columns": reader.PYTHON_COLUMNS, "spans": spans, "aggregate_columns": reader.PYTHON_AGGREGATE_COLUMNS,
        "aggregates": [["inline_main", 0, 1, 60, 30, 20, 10, 0], ["inline_main", 1, 1, 30, 20, 10, 6, 0],
                       ["inline_main", 2, 1, 100, 40, 50, 30, 0], ["inline_main", 3, 1, 10, 10, 4, 4, 0]]}
    return value, {"benchmark": codes, "resource_scheduler": codes}, {
        "instrumented_public_call_wall_ns": 100, "instrumented_public_call_thread_cpu_ns": 50}


def operator_fixture(reader):
    return {"schema": "bounded-torch-operator-costs/v1", "instrumented": True, "performance_qualified": False,
        "activities": ["CPU", "CUDA"], "record_shapes": False, "profile_memory": False, "with_stack": False,
        "clock": "native_profiler_relative_microseconds_alignment_to_python_clock_not_claimed",
        "collection_bound_scope": "fixed_admitted_workload_only_native_buffer_allocation_not_enforced",
        "postcollection_event_limit": 50000, "event_count": 2, "cuda_event_count": 1,
        "names": ["authored_cpu", "authored_cuda"], "device_types": ["DeviceType.CPU", "DeviceType.CUDA"],
        "event_columns": reader.OPERATOR_COLUMNS,
        "events": [[0, 0, 0, -1, 7, 0.0, 3.0, 3.0, 2.0, 0.0, 0.0],
                   [1, 1, 1, 0, 0, 0.5, 2.5, 0.0, 0.0, 2.0, 2.0]],
        "aggregate_columns": ["name_id", "device_type_id", "count", "cpu_total_us", "cpu_self_us", "device_total_us", "device_self_us"],
        "aggregates": [[0, 0, 1, 3.0, 2.0, 0.0, 0.0], [1, 1, 1, 0.0, 0.0, 2.0, 2.0]]}


class GuardCostOrdinaryControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = load_reader()

    def setUp(self):
        self.profile, self.sources, self.observation = python_fixture(self.reader)
        self.native = operator_fixture(self.reader)

    def refuses_python(self, mutate):
        mutate(self.profile)
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.reader._python_profile(self.profile, self.sources, self.observation)

    def refuses_native(self, mutate):
        mutate(self.native)
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.reader._operator_trace(self.native, expected_pid=1234)

    def test_authored_complete_selected_tree(self):
        result = self.reader._python_profile(self.profile, self.sources, self.observation)
        self.assertEqual(result["manual_wall_ns"], 100)
        self.assertEqual(result["raw_span_count"], 4)

    def test_native_aggregates_independently_recomputed(self):
        self.assertEqual(self.reader._operator_trace(self.native, expected_pid=1234)["native_cuda_event_count"], 1)

    def test_inclusive_cost_tamper(self):
        self.refuses_python(lambda p: p["spans"][1].__setitem__(8, 61))

    def test_exclusive_cost_tamper(self):
        self.refuses_python(lambda p: p["spans"][0].__setitem__(9, 41))

    def test_thread_cpu_arithmetic_tamper(self):
        self.refuses_python(lambda p: p["spans"][2].__setitem__(10, 11))

    def test_aggregate_tamper(self):
        self.refuses_python(lambda p: p["aggregates"][0].__setitem__(3, 61))

    def test_unbound_source_hash(self):
        self.refuses_python(lambda p: p["registry"][0].__setitem__("code_sha256", "0" * 64))

    def test_wrong_code_first_line(self):
        self.refuses_python(lambda p: p["registry"][0].__setitem__("firstlineno", 2))

    def test_same_code_registry_alias(self):
        self.refuses_python(lambda p: p["registry"].append({**p["registry"][0], "id": 6}))

    def test_equal_code_fingerprints_in_distinct_source_roles(self):
        # Authored static sources can produce equal bytecode/qualname/line;
        # source role remains part of their ordinary-byte identity.
        self.sources["owned_tensor_value_guard"] = self.sources["benchmark"]
        self.profile["registry"].append({**self.profile["registry"][0], "id": 6,
            "source_role": "owned_tensor_value_guard", "label": "second_current_source"})
        self.assertEqual(self.reader._python_profile(self.profile, self.sources, self.observation)["raw_span_count"], 4)

    def test_c_call_wrong_selected_caller(self):
        self.refuses_python(lambda p: p["spans"][3].__setitem__(1, 2))

    def test_c_call_outside_builtin_allowlist(self):
        self.refuses_python(lambda p: p["registry"][3].__setitem__("function_qualname", "os.unlink"))

    def test_cross_thread_parent(self):
        def mutate(p):
            p["threads"].append({"thread_id": 8, "scope": "owned_background"})
            p["spans"][1][2] = 8
        self.refuses_python(mutate)

    def test_parent_cycle(self):
        self.refuses_python(lambda p: p["spans"][1].__setitem__(1, 3))

    def test_unknown_parent(self):
        self.refuses_python(lambda p: p["spans"][1].__setitem__(1, 999))

    def test_inline_main_cannot_be_censored(self):
        self.refuses_python(lambda p: p["censored_background"].append({"edge": "entered_before_window", "thread_id": 7,
            "registry_id": 0, "return_event": "return", "observed_wall_ns": 50}))

    def test_background_partial_is_excluded_and_parent_joined(self):
        self.profile["threads"].append({"thread_id": 8, "scope": "owned_background"})
        self.profile["censored_background"] = [{"edge": "unfinished_at_window_end", "thread_id": 8, "id": 5,
            "parent_id": 0, "registry_id": 1, "start_wall_ns": 11, "start_thread_cpu_ns": 5}]
        self.profile["spans"].append([6, 5, 8, 3, 20, 30, 10, 15, 10, 10, 5, 5, "c_return"])
        self.profile["aggregates"].insert(0, ["owned_background", 3, 1, 10, 10, 5, 5, 0])
        self.profile["aggregates"].sort(key=lambda r: (r[0], r[1]))
        result = self.reader._python_profile(self.profile, self.sources, self.observation)
        self.assertEqual(result["manual_wall_ns"], 100)
        self.assertEqual(result["observed_thread_count"], 2)

    def test_duplicate_span(self):
        self.refuses_python(lambda p: p["spans"].append(p["spans"][1]))

    def test_missing_complete_root(self):
        self.refuses_python(lambda p: p["registry"][2].__setitem__("kind", "python"))

    def test_wrong_public_return_cost_join(self):
        self.observation["instrumented_public_call_wall_ns"] = 99
        with self.assertRaises(ValueError):
            self.reader._python_profile(self.profile, self.sources, self.observation)

    def test_overflow_hook_scope_refusals(self):
        for key, value in (("overflow", True), ("unsupported_thread_observed", True), ("hooks_restored", False),
                           ("performance_qualified", True), ("observer_overhead_scope", "overhead_subtracted")):
            with self.subTest(key=key):
                profile = deepcopy(self.profile)
                profile[key] = value
                with self.assertRaises(ValueError):
                    self.reader._python_profile(profile, self.sources, self.observation)

    def test_boolean_integer_bounds_refused(self):
        self.refuses_python(lambda p: p["bounds"].__setitem__("max_events", True))

    def test_original_callback_budget_cannot_be_relaxed(self):
        self.refuses_python(lambda p: p["bounds"].__setitem__("max_events", 4000000))

    def test_original_budget_cannot_claim_adapter_policy(self):
        with self.assertRaises(ValueError):
            self.reader._budget_policy({"schema": self.reader.DIMENSION_SCHEMA,
                "callback_limit_policy": {}}, {})

    def test_native_aggregate_forgery(self):
        self.refuses_native(lambda p: p["aggregates"][1].__setitem__(5, 99.0))

    def test_native_event_id_alias(self):
        self.refuses_native(lambda p: p["events"][1].__setitem__(0, 0))

    def test_native_nonfinite(self):
        self.refuses_native(lambda p: p["events"][0].__setitem__(7, float("inf")))

    def test_native_cuda_count_forgery(self):
        self.refuses_native(lambda p: p.__setitem__("cuda_event_count", 0))

    def test_native_tracebuffer_enforcement_claim(self):
        self.refuses_native(lambda p: p.__setitem__("collection_bound_scope", "allocator_enforced"))

    def test_native_clock_alignment_claim(self):
        self.refuses_native(lambda p: p.__setitem__("clock", "aligned_to_python"))

    def test_native_event_bound_before_iteration(self):
        self.refuses_native(lambda p: p.__setitem__("postcollection_event_limit", 1))

    def test_helper_fd_source_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reader.py"
            path.write_bytes(b"x=1\n")
            path.chmod(0o444)
            with self.assertRaises(ValueError):
                self.reader._helper_bytes(path, 4, "0" * 64)

    def test_helper_symlink_hardlink_writable_refusals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reader.py"
            raw = b"x=1\n"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                self.reader._helper_bytes(path, 4, digest)
            path.chmod(0o444)
            alias = path.with_name("alias.py")
            os.link(path, alias)
            with self.assertRaises(ValueError):
                self.reader._helper_bytes(path, 4, digest)
            alias.unlink()
            alias.symlink_to(path)
            with self.assertRaises((ValueError, OSError)):
                self.reader._helper_bytes(alias, 4, digest)

    def test_external_result_hash_refusal_is_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_bytes(b"{}")
            path.chmod(0o444)
            result = self.reader.audit(Path(directory), "0" * 64)
            self.assertFalse(result["qualified"])
            self.assertFalse(result["closed_artifacts_consistent"])
            self.assertFalse(result["model_executed"])

    def test_json_duplicates_nonfinite_and_depth_bound(self):
        helper = self.reader._base()
        for raw in (b'{"x":1,"x":2}', b'{"x":1e999}', b'{"x":NaN}', b'[' * 65 + b'0' + b']' * 65):
            with self.subTest(raw=raw[:32]):
                with self.assertRaises(ValueError):
                    helper._json(raw)

    def test_recursive_authority_refusal(self):
        helper = self.reader._base()
        with self.assertRaises(ValueError):
            helper._authority({"nested": [{"proof_authority": True}]})

    def test_bounded_inventory_symlink(self):
        helper = self.reader._base()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "leaf.json"
            path.symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                helper._inventory(Path(directory))

    def test_cli_other_basename_refused(self):
        with patch("sys.argv", [str(SOURCE), "--result", "/fictional/unrelated.json", "--expected-result-sha256", "0" * 64]):
            with self.assertRaises(ValueError):
                self.reader.main()

    def formula_panel(self):
        """Tiny fictional report data exercises joins, not an archive/model."""
        helper = self.reader._base()
        shas = {name: hashlib.sha256(name.encode()).hexdigest() for name in
            ("modal_latent_formula", "modal_latent_formula_device_inference", "modal_latent_formula_inference",
             "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin")}
        checkpoint = {"binding": {"dimension": 8}, "projection_id": "fictional_projection",
            "implementation": {"files": {name + ".py": shas[name] for name in
                ("modal_latent_formula", "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin")}}}
        inputs = {"rows": [{"id": "fictional_row", "source_text": "actor acts", "latent": [0.0] * 8}]}
        profile = {"schema": "modal-latent-formula-device-inference/v1", "dimension": 8, "optimized": False,
            "dtype": "float32", "cuda_selected": False, "device": "cpu", "cuda_executed": False,
            "actual_forward_executed": True, "actual_forward_calls": {"projection_down": 1, "projection_up": 1, "output": 1},
            "source_sha256": shas["modal_latent_formula_device_inference"],
            "parent": {"schema": "modal-latent-formula-inference-implementation/v1",
                "source_sha256": shas["modal_latent_formula_inference"]}}
        report = {"checkpoint_sha256": hashlib.sha256(helper._wire(checkpoint)).hexdigest(), "binding": checkpoint["binding"],
            "rows": [{"id": "fictional_row", "projection_id": "fictional_projection", "status": "abstained",
                "source_sha256": hashlib.sha256(b"actor acts").hexdigest(),
                "latent_sha256": hashlib.sha256(helper._wire([0.0] * 8)).hexdigest(),
                "syntax_scope": "canonical_rule_schema_and_decoder_grammar", "minimum_decision_logit_margin": None}],
            "decoded_count": 0, "status": "abstained", "proof_authority": False, "inference_implementation": profile}
        vectors, canonical = [[0.0] * 8], helper._decisions(report)
        observed = {"result": {"path": "fictional-result.json"}, "projected_vectors": {"path": "fictional-projected-vectors.json"},
            "instrumented": False, "cpu_cuda_rng_unchanged": True, "canonical_matches_original_cpu": True,
            "complete_projection_max_abs_error": 0.0}
        class Panels:
            def value(self, pin, *, name, unique):
                if pin["path"] != name or not unique:
                    raise ValueError("fictional panel alias")
                return report if name.endswith("-result.json") else vectors
        def consume():
            return self.reader._formula_observation(helper, Panels(), observed, "fictional", "original_cpu_reference", 1,
                checkpoint, inputs, shas, {}, None, "cuda:0", {}, canonical=canonical, numeric=[[0.0] * 8])
        return consume, observed, report, vectors

    def test_authored_public_projection_join(self):
        consume, _, _, _ = self.formula_panel()
        self.assertEqual(consume()[1], [[0.0] * 8])

    def test_public_decision_corruption(self):
        consume, _, report, _ = self.formula_panel()
        report["rows"][0]["reason"] = "forged_new_decision"
        with self.assertRaises(ValueError):
            consume()

    def test_public_input_hash_corruption(self):
        consume, _, report, _ = self.formula_panel()
        report["rows"][0]["latent_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            consume()

    def test_public_complete_numeric_tolerance(self):
        consume, _, _, vectors = self.formula_panel()
        vectors[0][-1] = 0.5
        with self.assertRaises(ValueError):
            consume()

    def test_public_projection_error_forgery(self):
        consume, observed, _, _ = self.formula_panel()
        observed["complete_projection_max_abs_error"] = 0.1
        with self.assertRaises(ValueError):
            consume()

    def test_public_phase_scope_corruption(self):
        consume, observed, _, _ = self.formula_panel()
        observed["instrumented"] = True
        with self.assertRaises(ValueError):
            consume()

    def test_public_panel_alias(self):
        consume, observed, _, _ = self.formula_panel()
        observed["projected_vectors"]["path"] = "other-projected-vectors.json"
        with self.assertRaises(ValueError):
            consume()

    def test_public_forward_device_token_and_precision_refusals(self):
        profile = {"profile_id": "native-768-source-span-device-strict-cuda-float32/v2", "scoped_cudnn": True,
            "effective_policy": {"cudnn": {"allow_tf32": False}}, "synchronized_before_restore": True,
            "ambient_flags_restored": True}
        forward = {"rows": 1, "source_tokens": [5], "native_input_dimension": 768, "input_device": "cuda:0",
            "output_devices": {name: "cuda:0" for name in ("modality", "presence", "start", "end")},
            "output_dtype": "float32", "gru_executed": True, "gru_precision": profile}
        self.reader._forward_scope([forward], [5], "cuda:0", 768, True)
        for field, replacement in (("input_device", "cpu"), ("source_tokens", [6]), ("native_input_dimension", 384)):
            with self.subTest(field=field):
                changed = deepcopy(forward)
                changed[field] = replacement
                with self.assertRaises(ValueError):
                    self.reader._forward_scope([changed], [5], "cuda:0", 768, True)
        changed = deepcopy(forward)
        changed["gru_precision"]["ambient_flags_restored"] = False
        with self.assertRaises(ValueError):
            self.reader._forward_scope([changed], [5], "cuda:0", 768, True)

    def test_raw_trace_nested_authority_refusals(self):
        for family in ("python", "operator"):
            with self.subTest(family=family):
                if family == "python":
                    self.profile["nested"] = {"proof_authority": True}
                    with self.assertRaises(ValueError):
                        self.reader._python_profile(self.profile, self.sources, self.observation)
                else:
                    self.native["nested"] = {"execution_attestation": True}
                    with self.assertRaises(ValueError):
                        self.reader._operator_trace(self.native, expected_pid=1234)

    def test_censored_ids_must_be_plain_integers(self):
        self.profile["threads"].append({"thread_id": 1, "scope": "owned_background"})
        edge = {"edge": "entered_before_window", "thread_id": 1, "registry_id": 0,
            "return_event": "return", "observed_wall_ns": 50}
        for field in ("thread_id", "registry_id"):
            with self.subTest(field=field):
                profile = deepcopy(self.profile)
                profile["censored_background"] = [{**edge, field: field == "thread_id"}]
                with self.assertRaises(ValueError):
                    self.reader._python_profile(profile, self.sources, self.observation)


    def test_native_cpu_pid_exact_join(self):
        self.native["events"][0][3] = 1234
        self.assertEqual(self.reader._operator_trace(self.native, expected_pid=1234)["native_event_count"], 2)

    def test_native_cpu_pid_and_type_refusals(self):
        for index in (False, 0.0, 0, 1235, 2**31):
            with self.subTest(index=index):
                value = deepcopy(self.native)
                value["events"][0][3] = index
                with self.assertRaises(ValueError):
                    self.reader._operator_trace(value, expected_pid=1234)
        with self.assertRaises(ValueError):
            self.reader._operator_trace(self.native, expected_pid=True)

    def test_native_cuda_ordinal_boundary_and_cpu_cross_alias(self):
        self.native["events"][1][3] = 63
        self.assertEqual(self.reader._operator_trace(self.native, expected_pid=1234)["native_cuda_event_count"], 1)
        for index in (-1, 64, 1234, True):
            with self.subTest(index=index):
                value = deepcopy(self.native)
                value["events"][1][3] = index
                with self.assertRaises(ValueError):
                    self.reader._operator_trace(value, expected_pid=1234)
        value = deepcopy(self.native)
        value["device_types"][0] = "DeviceType.UNKNOWN"
        with self.assertRaises(ValueError):
            self.reader._operator_trace(value, expected_pid=1234)

    def progress_fixture(self, dimension=768):
        parent = {"progress": {"epochs_completed": 1, "optimizer_steps": 3, "row_cursor": 2}}
        parent_sha = hashlib.sha256(self.reader._wire(parent)).hexdigest() if dimension == 768 else None
        checkpoint = {"progress": deepcopy(self.reader.RETAINED_DIMENSION_PROGRESS[dimension]),
            "source_parent_checkpoint": parent if dimension == 768 else None,
            "source_parent_checkpoint_sha256": parent_sha,
            "source_parent_optimizer_steps": 3 if dimension == 768 else 0}
        checkpoint_sha = hashlib.sha256(self.reader._wire(checkpoint)).hexdigest()
        return checkpoint, checkpoint_sha, parent_sha

    def test_retained_progress_child_parent_content_only(self):
        for dimension in (768, 4096):
            with self.subTest(dimension=dimension):
                checkpoint, digest, parent_digest = self.progress_fixture(dimension)
                value = self.reader._progress_binding(checkpoint, dimension, digest, parent_digest)
                self.assertEqual(value["checkpoint_progress"]["optimizer_steps"], 1 if dimension == 768 else 0)
                self.assertFalse(value["training_execution_authenticated"])
                self.assertFalse(value["new_training_execution_claimed"])

    def test_retained_progress_mutation_and_numeric_alias_refusals(self):
        for field, replacement in (("optimizer_steps", 30), ("optimizer_steps", True), ("row_cursor", 2.0)):
            with self.subTest(field=field, replacement=replacement):
                checkpoint, _, parent_digest = self.progress_fixture()
                checkpoint["progress"][field] = replacement
                digest = hashlib.sha256(self.reader._wire(checkpoint)).hexdigest()
                with self.assertRaises(ValueError):
                    self.reader._progress_binding(checkpoint, 768, digest, parent_digest)
        checkpoint, digest, parent_digest = self.progress_fixture()
        with self.assertRaises(ValueError):
            self.reader._progress_binding(checkpoint, 768, digest, "0" * 64)
        checkpoint["source_parent_checkpoint"]["progress"]["optimizer_steps"] = 2
        checkpoint["source_parent_checkpoint_sha256"] = hashlib.sha256(self.reader._wire(checkpoint["source_parent_checkpoint"])).hexdigest()
        digest = hashlib.sha256(self.reader._wire(checkpoint)).hexdigest()
        with self.assertRaises(ValueError):
            self.reader._progress_binding(checkpoint, 768, digest, checkpoint["source_parent_checkpoint_sha256"])

    def dimension_budget_fixture(self, schema):
        large4096 = schema == self.reader.DIMENSION_SCHEMA_V6
        maximum = 8000000 if large4096 else 4000000
        newest = schema in (self.reader.DIMENSION_SCHEMA_V3, self.reader.DIMENSION_SCHEMA_V4, self.reader.DIMENSION_SCHEMA_V5,
                            self.reader.DIMENSION_SCHEMA_V6)
        base_sha = self.reader.FORMULA_PRODUCER_V2_SHA if newest else self.reader.FORMULA_PRODUCER_SHA
        producer_sha = (self.reader.DIMENSION_PRODUCER_V6_SHA if large4096 else
                        self.reader.DIMENSION_PRODUCER_V5_SHA if schema == self.reader.DIMENSION_SCHEMA_V5 else
                        self.reader.DIMENSION_PRODUCER_V4_SHA if schema == self.reader.DIMENSION_SCHEMA_V4 else
                        self.reader.DIMENSION_PRODUCER_V3_SHA if newest else self.reader.DIMENSION_PRODUCER_V2_SHA)
        adapter = {"schema": "guard-cost-observer-callback-budget/" + ("v4" if large4096 else "v3" if newest else "v2"),
            "all_profile_callback_cap": maximum, "base_observer_callback_cap": 1000000, "selected_span_cap": 20000,
            "thread_cap": 32, "native_operator_cap": 50000, "base_source_sha256": base_sha,
            "scope": "owned_instance_limit_only_all_callbacks_counted_guards_unchanged",
            "overflow_scope": "diagnostic_refusal_after_operation_without_interrupting_guards",
            "base_module_or_class_mutated": False, "performance_qualified": False}
        if newest:
            adapter["registry_binding"] = self.reader.IDENTITY_POLICY
        value = {"schema": schema, "callback_limit_policy": {"schema": "dimension-guard-cost-callback-budget/" + ("v3" if large4096 else "v2"),
            "max_callback_events": maximum, "scope": "all_python_and_c_callbacks_including_unselected_recursive_guard_atoms",
            "selected_span_limit": 20000, "native_operator_postcollection_limit":
                50000 if schema in (self.reader.DIMENSION_SCHEMA_V4, self.reader.DIMENSION_SCHEMA_V5, self.reader.DIMENSION_SCHEMA_V6) else 15000,
            "global_observer_limits_changed": False, "producer_checks_changed": False},
            "observer_budget_adapter_policy": adapter}
        shas = {"benchmark": producer_sha, "cost_profiler": base_sha, "cost_observer_budget":
            self.reader.COST_OBSERVER_BUDGET_V4_SHA if large4096 else
            self.reader.COST_OBSERVER_BUDGET_V3_SHA if newest else self.reader.COST_OBSERVER_BUDGET_SHA}
        if large4096:
            value["dimension"] = 4096
        return value, shas

    def test_new_native_postcollection_policy_is_exact_source_bound(self):
        value, shas = self.dimension_budget_fixture(self.reader.DIMENSION_SCHEMA_V4)
        self.assertEqual(self.reader._budget_policy(value, shas), 4000000)
        for role in ("benchmark", "cost_profiler", "cost_observer_budget"):
            with self.subTest(role=role):
                forged = {**shas, role: "0" * 64}
                with self.assertRaises(ValueError):
                    self.reader._budget_policy(value, forged)
        value["callback_limit_policy"]["native_operator_postcollection_limit"] = 15000
        with self.assertRaises(ValueError):
            self.reader._budget_policy(value, shas)

    def test_historical_native_postcollection_policy_cannot_be_promoted(self):
        value, shas = self.dimension_budget_fixture(self.reader.DIMENSION_SCHEMA_V3)
        self.assertEqual(self.reader._budget_policy(value, shas), 4000000)
        value["callback_limit_policy"]["native_operator_postcollection_limit"] = 50000
        with self.assertRaises(ValueError):
            self.reader._budget_policy(value, shas)

    def representative_panel(self, count):
        observed = {"operators": {"path": "fictional-operators.json"} if count == 1 else None,
            "native_operator_profiled": count == 1,
            "native_operator_not_collected_scope": None if count == 1 else
                "outside_fixed_representative_native_trace_counts_python_observer_only"}
        calls, native = [], deepcopy(self.native)
        class Panels:
            def value(self, pin, *, name, unique):
                if pin != {"path": "fictional-operators.json"} or name != "fictional-operators.json" or not unique:
                    raise ValueError("fictional native panel alias")
                calls.append(name)
                return native
        def consume():
            return self.reader._dimension_native_panel(Panels(), observed, "fictional", count, profiling_pid=1234,
                native_event_limit=50000, representative_counts=(1,))
        return consume, observed, calls

    def test_representative_one_row_native_trace_is_joined(self):
        consume, _, calls = self.representative_panel(1)
        self.assertEqual(consume()["native_cuda_event_count"], 1)
        self.assertEqual(calls, ["fictional-operators.json"])

    def test_large_batch_python_only_native_absence_is_explicit(self):
        for count in (16, 32):
            with self.subTest(count=count):
                consume, _, calls = self.representative_panel(count)
                self.assertIsNone(consume())
                self.assertEqual(calls, [])

    def test_large_batch_cannot_acquire_native_coverage(self):
        for field, replacement in (("operators", {"path": "fictional-operators.json"}),
                                   ("native_operator_profiled", True),
                                   ("native_operator_not_collected_scope", None)):
            with self.subTest(field=field):
                consume, observed, calls = self.representative_panel(32)
                observed[field] = replacement
                with self.assertRaises(ValueError):
                    consume()
                self.assertEqual(calls, [])

    def test_representative_native_policy_count_and_source_refusals(self):
        value = {"schema": self.reader.DIMENSION_SCHEMA_V5, "native_operator_counts": [1],
            "native_operator_profiled_return_count": 2,
            "native_operator_profile_scope": "representative_cuda_count1_only_larger_counts_python_source_costs_only"}
        shas = {"benchmark": self.reader.DIMENSION_PRODUCER_V5_SHA}
        self.assertEqual(self.reader._dimension_native_policy(value, shas, 2), (1,))
        for field, replacement in (("native_operator_counts", [True]), ("native_operator_counts", [1, 16, 32]),
                                   ("native_operator_profiled_return_count", 6),
                                   ("native_operator_profile_scope", "complete_all_cuda_count_traces")):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.reader._dimension_native_policy({**value, field: replacement}, shas, 2)
        with self.assertRaises(ValueError):
            self.reader._dimension_native_policy(value, {"benchmark": "0" * 64}, 2)
        policy, exact_shas = self.dimension_budget_fixture(self.reader.DIMENSION_SCHEMA_V5)
        self.assertEqual(self.reader._budget_policy(policy, exact_shas), 4000000)

    def test_historical_full_native_policy_cannot_be_relabelled_partial(self):
        with self.assertRaises(ValueError):
            self.reader._dimension_native_policy({"schema": self.reader.DIMENSION_SCHEMA_V4,
                "native_operator_counts": [1]}, {}, 2)
        consume, observed, _ = self.representative_panel(1)
        observed["operators"] = None
        with self.assertRaises(ValueError):
            consume()

    def test_eight_million_callbacks_exact_plain_integer_boundary(self):
        self.profile["bounds"]["max_events"] = 8000000
        self.profile["callback_events_observed"] = 8000000
        value = self.reader._python_profile(self.profile, self.sources, self.observation, max_callback_events=8000000)
        self.assertEqual(value["raw_span_count"], 4)
        for callbacks in (8000001, True, 8000000.0):
            with self.subTest(callbacks=callbacks):
                profile = deepcopy(self.profile)
                profile["callback_events_observed"] = callbacks
                with self.assertRaises(ValueError):
                    self.reader._python_profile(profile, self.sources, self.observation, max_callback_events=8000000)
        for limit in (8000001, True):
            with self.subTest(limit=limit):
                profile = deepcopy(self.profile)
                profile["bounds"]["max_events"] = limit
                with self.assertRaises(ValueError):
                    self.reader._python_profile(profile, self.sources, self.observation, max_callback_events=8000000)

    def test_eight_million_callback_policy_exact_source_and_dimension(self):
        policy, shas = self.dimension_budget_fixture(self.reader.DIMENSION_SCHEMA_V6)
        self.assertEqual(self.reader._budget_policy(policy, shas), 8000000)
        for dimension in (768, True, 4096.0):
            with self.subTest(dimension=dimension):
                with self.assertRaises(ValueError):
                    self.reader._budget_policy({**policy, "dimension": dimension}, shas)
        for role in ("benchmark", "cost_profiler", "cost_observer_budget"):
            with self.subTest(role=role):
                with self.assertRaises(ValueError):
                    self.reader._budget_policy(policy, {**shas, role: "0" * 64})

    def test_callback_caps_cannot_cross_versions(self):
        for schema in (self.reader.DIMENSION_SCHEMA_V5, self.reader.DIMENSION_SCHEMA_V6):
            with self.subTest(schema=schema):
                policy, shas = self.dimension_budget_fixture(schema)
                policy["callback_limit_policy"]["max_callback_events"] = 4000000 if schema == self.reader.DIMENSION_SCHEMA_V6 else 8000000
                with self.assertRaises(ValueError):
                    self.reader._budget_policy(policy, shas)
        self.profile["bounds"]["max_events"] = 8000000
        with self.assertRaises(ValueError):
            self.reader._python_profile(self.profile, self.sources, self.observation, max_callback_events=4000000)
        self.profile["bounds"]["max_events"] = True
        with self.assertRaises(ValueError):
            self.reader._python_profile(self.profile, self.sources, self.observation, max_callback_events=8000000)

if __name__ == "__main__":
    unittest.main()
