"""Authored fictional byte/math controls; no producer, model or tensor execution."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

READER = Path(__file__).absolute().parents[4] / "benchmarks/audit_formula_guard_coordinator_v3.py"
EXPECTED_READER_SHA = "f38e215b5052242b682ad2e6a5b2e2631588a8f98957c75e8b3f3137a9475c53"
assert hashlib.sha256(READER.read_bytes()).hexdigest() == EXPECTED_READER_SHA, "checked current reader source differs"
spec = importlib.util.spec_from_file_location("_formula_coordinator_v3_authored_reader_controls", READER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _write(path, value):
    path = Path(path)
    raw = value if type(value) is bytes else _wire(value)
    path.write_bytes(raw)
    path.chmod(0o444)
    return {"path": str(path.absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _archive(root, files):
    pins = [_write(root / name, value) for name, value in files.items()]
    metadata = {"evidence_files_except_result": pins, "evidence_bytes_except_result": sum(pin["bytes"] for pin in pins),
        "evidence_limits": {"max_files": reader.MAX_FILES, "max_file_bytes": reader.MAX_FILE_BYTES,
            "max_total_bytes": reader.MAX_TOTAL_BYTES, "result_included_in_limits": True}}
    _write(root / "result.json", metadata)
    return reader.Archive(root, metadata), pins


def _checkpoint():
    # Small invented arithmetic parameters, never called a trained model.
    names = ("condition.bias", "condition.weight", "decoder.bias_hh_l0", "decoder.bias_ih_l0",
        "decoder.weight_hh_l0", "decoder.weight_ih_l0", "output.bias", "output.weight", "target_embedding.weight")
    model = {name: [0.0] for name in names}
    model.update({"projection_down.weight": [[0.5] + [0.0] * 7], "projection_down.bias": [0.0],
        "projection_up.weight": [[0.25] for _ in range(8)], "projection_up.bias": [0.0] * 8})
    sources = {name: hashlib.sha256(name.encode()).hexdigest() for name in
        ("modal_latent_formula", "modal_latent_formula_inference", "modal_latent_formula_device_inference",
         "modal_latent_formula_bitwise_device_inference", "modal_latent_formula_bitwise_device_inference_v2",
         "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin",
         "owned_tensor_bitwise_guard", "checkpoint_content_guard", "resource_scheduler")}
    cp = {"model_state": model, "binding": {"dimension": 8, "lineage_id": "authored_fictional"},
        "projection_id": "authored_projection", "implementation": {"files":
            {name + ".py": sources[name] for name in
             ("modal_latent_formula", "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin")}}}
    return cp, sources


def _profile(cp, sources, *, bitwise=False, version2=False, cuda=False):
    inherited = {"schema": "modal-latent-formula-device-inference/v1",
        "source_sha256": sources["modal_latent_formula_device_inference"],
        "parent": {"schema": "modal-latent-formula-inference-implementation/v1",
            "source_sha256": sources["modal_latent_formula_inference"]}}
    profile = {**inherited, "dimension": 8, "optimized": cuda, "dtype": "float32", "cuda_selected": cuda,
        "cuda_executed": cuda, "actual_forward_executed": True, "device": "cuda:0" if cuda else "cpu",
        "actual_forward_calls": {"projection_down": 1, "projection_up": 1, "output": 1}}
    if not bitwise:
        return profile
    version = "v2" if version2 else "v1"
    byte_plan = reader._model_bytes(cp)
    role = "modal_latent_formula_bitwise_device_inference" + ("_v2" if version2 else "")
    profile.update({"schema": "modal-latent-formula-bitwise-device-implementation/" + version,
        "profile_id": "modal-latent-formula-bitwise-owned-device-float32/" + version,
        "source_sha256": sources[role], "inherited_device_implementation": inherited,
        "native_checkpoint_implementation": cp["implementation"],
        "checkpoint_guard_source_sha256": sources["checkpoint_content_guard"],
        "resource_scheduler_source_sha256": sources["resource_scheduler"],
        "bitwise_guard_implementation": {"source_sha256": sources["owned_tensor_bitwise_guard"]},
        "lineage_id": cp["binding"]["lineage_id"], "adam_restoration_performed": True,
        "adam_restore_count": 1, "optimizer_steps_executed": 0,
        "owned_tensor_currentness": {"schema": "owned-tensor-bitwise-value-guard/v1",
            "mode": "cuda_bitwise_single_host_decision" if cuda else "cpu_reference_checks",
            "implementation": {"source_sha256": sources["owned_tensor_bitwise_guard"],
                "comparison": "finite-float32-exact-bits-with-reference-finiteness/v1"},
            "all_current_values_checked": True, "finite_values_checked": True, "signed_zero_checked": True,
            "tensor_count": 13, "state_and_reference_bytes": 2 * byte_plan["bytes"],
            "comparison_device": "cuda:0" if cuda else "cpu"},
        "reference_byte_currentness": {"schema": "modal-formula-owned-reference-byte-currentness/v1",
            "checkpoint_sha256": hashlib.sha256(_wire(cp)).hexdigest(),
            "origin": "validated_cpu_checkpoint_model_before_reference_clone_and_upload",
            "anchor_sha256": byte_plan["sha256"], "reference_bytes": byte_plan["bytes"],
            "comparison": "complete_immutable_float32_bytes_including_signed_zero",
            "anchor_identity_checked": True, "independent_of_mutable_reference_storage": True,
            "metadata_and_reservation_checked_before_allocation": True,
            "reference_device": "cuda:0" if cuda else "cpu", "cpu_byte_materializations": 1,
            "device_to_cpu_reference_transfers": int(cuda)}})
    if version2:
        profile.update({"inherited_owner_source_sha256": sources["modal_latent_formula_bitwise_device_inference"],
            "source_verification_success_cached": False, "boundary_consolidation_performed": False,
            "duplicate_native_source_verification_in_boundary": False,
            "checkpoint_matches_method_identity_checked": True, "native_source_verifications_per_boundary": 1,
            "owned_content_guard_object_and_snapshot_identities_checked": True,
            "owned_content_guard_identity_policy": "fixed_after_source_bound_constructor_guard_creation",
            "outer_discarded_receipt_construction_avoided": True,
            "public_receipt_boundary_scope": "inherited_exit_receipt_with_fresh_outer_exit_guard_and_no_outer_receipt"})
    return profile


def _public(cp, sources):
    latent, text = [0.1] + [0.0] * 7, "Authored fixture only."
    inputs = {"rows": [{"id": "fictional-0", "source_text": text, "latent": latent}]}
    row = {"id": "fictional-0", "projection_id": cp["projection_id"],
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "latent_sha256": hashlib.sha256(_wire(latent)).hexdigest(), "status": "decoded",
        "syntax_scope": "canonical_rule_schema_and_decoder_grammar", "minimum_decision_logit_margin": 1.0,
        "generated_token_ids": [1, 2], "proof_authority": False,
        "formal_outputs": [{"qualified": False, "semantic_correctness_verified": False}]}
    report = {"checkpoint_sha256": hashlib.sha256(_wire(cp)).hexdigest(), "binding": cp["binding"],
        "rows": [row], "decoded_count": 1, "status": "decoded", "proof_authority": False,
        "inference_implementation": _profile(cp, sources)}
    numeric = reader._projection_algebra(cp, [latent])
    return report, numeric, inputs


def _scope_header():
    return {"cpu_reference_scope": "one_call_per_route_count_no_repeatability_claim",
        "cuda_timing_scope": "complete_guarded_public_inference_and_completion_sync_uninstrumented_input_copy_before_interval_three_way_balanced",
        "counter_observation_scope": "source_bound_python_calls_during_constructors_cpu_references_cuda_warmups_and_controls_only"}


def _controls():
    labels = ("paired_finite_data_mutation", "paired_signed_zero_data_mutation", "equal_content_anchor_identity_replacement",
        "model_only_positive_subnormal_bits", "paired_finite_after_actual_forward_poll", "authored_input_mutation_after_forward_poll",
        "cancel_before_forward")
    result = []
    for name in labels:
        callback = name.endswith("after_actual_forward_poll") or name.endswith("after_forward_poll")
        entry = {"control": name, "refused": True, "refusal": "authored cancel refusal" if name == "cancel_before_forward" else "authored refusal",
            "post_forward_callback_executed": callback, "before_forward_refusal": not callback,
            "actual_model_forward_calls": 1 if callback else 0}
        if name == "paired_signed_zero_data_mutation":
            entry.update(actual_admitted_zero_tensor="target_embedding.weight", actual_admitted_zero_index=0,
                         original_float32_bits_int32=0)
        result.append(entry)
    return result


class TestFormulaCoordinatorOrdinaryPrimitives(unittest.TestCase):
    def test_current_scheduler_source_matches_reviewed_fixed_pin(self):
        scheduler = READER.parent.parent / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py"
        raw = reader._read(scheduler, readonly=False)
        self.assertEqual(len(raw), 97272)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), reader.FIXED_SOURCES["resource_scheduler"])
        self.assertEqual(reader.FIXED_SOURCES["resource_scheduler"],
                         "f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa")

    def test_json_positive_preserves_plain_values(self):
        self.assertEqual(reader._json(b'{"value":[1,1.25,false,null]}'), {"value": [1, 1.25, False, None]})

    def test_json_duplicate_nonfinite_exponent_and_depth_refusals(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
                    b"[" * 66 + b"0" + b"]" * 66, b"1" * 81):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises((ValueError, RecursionError)):
                    reader._json(raw)

    def test_plain_integer_refuses_boolean_float_and_negative(self):
        for value in (False, True, 0.0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    reader._integer(value)

    def test_malformed_failed_family_containers_return_structured_refusal(self):
        for families in ([], None, "formula8", {"unknown": {}}, {"formula8": []}):
            with self.subTest(families=families), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = _write(root / "result.json", {"schema": reader.SCHEMA, "qualified": False,
                    "families": families, **_scope_header()})
                report = reader.audit(root, pin["sha256"])
                self.assertIs(report["closed_artifacts_consistent"], False)
                self.assertEqual(report["error"]["type"], "ValueError")
                self.assertIn("family map", report["error"]["detail"])

    def test_existing_timing_scopes_cannot_claim_kernel_only_or_profiled_intervals(self):
        header = _scope_header()
        reader._scopes(header)
        for name in header:
            for value in ("kernel_only", "profilers_attached_during_timed_calls", False):
                with self.subTest(name=name, value=value):
                    changed = deepcopy(header)
                    changed[name] = value
                    with self.assertRaises(ValueError):
                        reader._scopes(changed)

    def test_partial_family_authority_still_returns_structured_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = _write(root / "result.json", {"schema": reader.SCHEMA, "qualified": False,
                "families": {"formula8": {"proof_authority": True}}, **_scope_header()})
            report = reader.audit(root, pin["sha256"])
            self.assertIs(report["closed_artifacts_consistent"], False)
            self.assertIn("authority", report["error"]["detail"])

    def test_cli_refuses_unrelated_result_basename_before_auditing_sibling(self):
        with patch.object(sys, "argv", ["reader", "--result", "/tmp/unrelated.json", "--expected-result-sha256", "0" * 64]):
            with patch.object(reader, "audit") as forbidden:
                with self.assertRaisesRegex(ValueError, "result.json CLI"):
                    reader.main()
                forbidden.assert_not_called()

    def test_read_only_single_link_custody_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ordinary.json"
            _write(path, {"value": 1})
            self.assertEqual(reader._read(path), b'{"value":1}')

    def test_read_refuses_writable_symlink_hardlink_and_parent_symlink(self):
        for kind in ("writable", "symlink", "hardlink", "parent_symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "ordinary.json"
                _write(path, {"value": 1})
                if kind == "writable":
                    path.chmod(0o644)
                elif kind == "symlink":
                    original = root / "original.json"
                    path.rename(original)
                    path.symlink_to(original)
                elif kind == "hardlink":
                    os.link(path, root / "duplicate.json")
                else:
                    linked = root / "linked"
                    linked.symlink_to(root, target_is_directory=True)
                    path = linked / path.name
                with self.assertRaises((ValueError, OSError)):
                    reader._read(path)

    def test_inventory_refuses_unknown_depth_and_budget_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unknown").mkdir()
            with self.assertRaises(ValueError):
                reader._inventory(root)
            (root / "unknown").rmdir()
            for index in range(3):
                _write(root / f"{index}.json", {"i": index})
            with patch.object(reader, "MAX_FILES", 1):
                with self.assertRaisesRegex(ValueError, "bounded archive"):
                    reader._inventory(root)

    def test_archive_rejects_unmanifested_leaf_and_changed_pin(self):
        for kind in ("unmanifested", "changed_pin", "duplicate_pin"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive, pins = _archive(root, {"one.json": {"i": 1}})
                metadata = reader._json((root / "result.json").read_bytes())
                if kind == "unmanifested":
                    _write(root / "extra.json", {"i": 2})
                elif kind == "changed_pin":
                    metadata["evidence_files_except_result"][0]["sha256"] = "0" * 64
                else:
                    metadata["evidence_files_except_result"].append(deepcopy(pins[0]))
                with self.assertRaises(ValueError):
                    reader.Archive(root, metadata)

    def test_archive_panel_uniqueness_and_filename_join(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, pins = _archive(root, {"formula8-original_cpu_reference-1-result.json": {"i": 1}})
            archive.raw(pins[0], name="formula8-original_cpu_reference-1-result.json", unique=True)
            with self.assertRaisesRegex(ValueError, "reused"):
                archive.raw(pins[0], name="formula8-original_cpu_reference-1-result.json", unique=True)
            with self.assertRaisesRegex(ValueError, "filename"):
                archive.raw(pins[0], name="formula8-1-trial00-original_cuda-result.json")
            archive.finish()

    def test_recursive_authority_is_plain_false(self):
        reader._authority({"rows": [{"formal_outputs": [{"proof_authority": False}]}]})
        for flag in ("proof_authority", "native_cuda_qualified", "semantic_correctness_verified", "qualified", "training_executed"):
            for value in (True, 0):
                with self.subTest(flag=flag, value=value):
                    with self.assertRaises(ValueError):
                        reader._authority({"rows": [{"formal_outputs": [{flag: value}]}]})

    def test_float32_refuses_nonrepresentable_and_nonfinite_numbers(self):
        self.assertEqual(reader._float32(-0.0), b"\0\0\0\x80")
        for value in (0.1, 1, True, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    reader._float32(value)

    def test_model_anchor_covers_sorted_float32_bytes_and_signed_zero(self):
        cp, _ = _checkpoint()
        before = reader._model_bytes(cp)
        cp["model_state"]["condition.bias"][0] = -0.0
        after = reader._model_bytes(cp)
        self.assertEqual(before["bytes"], after["bytes"])
        self.assertEqual(before["tensor_count"], 13)
        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_native_signed_zero_receipt_joins_actual_checkpoint_element(self):
        cp, _ = _checkpoint()
        reader._controls(_controls(), cp)

    def test_signed_zero_not_applicable_contradicts_zeros_in_fixed_model(self):
        cp, _ = _checkpoint()
        controls = _controls()
        controls[1] = {"control": "paired_signed_zero_data_mutation", "applicable": False,
                       "reason": "no actual admitted signed zero tensor element"}
        with self.assertRaisesRegex(ValueError, "contradicts fixed checkpoint"):
            reader._controls(controls, cp)

    def test_signed_zero_control_refuses_forged_tensor_index_bits_and_boolean(self):
        cp, _ = _checkpoint()
        for field, value in (("actual_admitted_zero_tensor", "missing"), ("actual_admitted_zero_index", 1),
                             ("actual_admitted_zero_index", False), ("original_float32_bits_int32", -2147483648),
                             ("original_float32_bits_int32", False)):
            with self.subTest(field=field):
                controls = _controls()
                controls[1][field] = value
                with self.assertRaises(ValueError):
                    reader._controls(controls, cp)

    def test_projection_algebra_rounds_input_and_detects_coherent_zero_panels(self):
        cp, _ = _checkpoint()
        output = reader._projection_algebra(cp, [[0.1] + [0.0] * 7])
        reader._shape(output, (1, 8))
        self.assertGreater(output[0][0], 0.1)
        with self.assertRaisesRegex(ValueError, "parity exceeded"):
            reader._numeric(output, [[0.0] * 8])

    def test_numeric_tolerance_checks_every_value_and_shape(self):
        self.assertEqual(reader._numeric([[0.0, 1.0]], [[0.0, 1.0]]), 0.0)
        for actual in ([[0.0]], [[0.0, 1.25]], [[0.0, 1]]):
            with self.subTest(actual=actual):
                with self.assertRaises(ValueError):
                    reader._numeric([[0.0, 1.0]], actual)

    def test_profile_all_three_cpu_cuda_routes_join_sources_and_anchors(self):
        cp, sources = _checkpoint()
        for cuda in (False, True):
            for variant in (0, 1, 2):
                label = ((reader.CUDA_LANES if cuda else reader.CPU_LANES)[variant])
                profile = _profile(cp, sources, bitwise=variant > 0, version2=variant == 2, cuda=cuda)
                with self.subTest(label=label):
                    reader._source_profile(profile, label, cp, sources, reader._model_bytes(cp))

    def test_profile_cuda_device_is_bound_to_declared_hardware_index(self):
        cp, sources = _checkpoint()
        profile = _profile(cp, sources, bitwise=True, version2=True, cuda=True)
        profile["device"] = profile["owned_tensor_currentness"]["comparison_device"] = "cuda:3"
        profile["reference_byte_currentness"]["reference_device"] = "cuda:3"
        reader._source_profile(profile, "bitwise_v2_cuda", cp, sources, reader._model_bytes(cp), cuda_device="cuda:3")
        with self.assertRaises(ValueError):
            reader._source_profile(profile, "bitwise_v2_cuda", cp, sources, reader._model_bytes(cp), cuda_device="cuda:0")

    def test_profile_device_source_anchor_and_cached_boundary_forgery_refused(self):
        cp, sources = _checkpoint()
        mutations = (("device", "cpu"), ("source_sha256", "0" * 64), ("inherited_owner_source_sha256", "0" * 64),
                     ("source_verification_success_cached", True), ("boundary_consolidation_performed", True),
                     ("owned_content_guard_object_and_snapshot_identities_checked", False),
                     ("owned_content_guard_identity_policy", "uncaptured"))
        for field, value in mutations:
            with self.subTest(field=field):
                profile = _profile(cp, sources, bitwise=True, version2=True, cuda=True)
                profile[field] = value
                with self.assertRaises(ValueError):
                    reader._source_profile(profile, "bitwise_v2_cuda", cp, sources, reader._model_bytes(cp))
        for field, value in (("anchor_sha256", "0" * 64), ("reference_bytes", 1), ("reference_bytes", False),
                             ("independent_of_mutable_reference_storage", False)):
            with self.subTest(field=field):
                profile = _profile(cp, sources, bitwise=True, version2=True, cuda=True)
                profile["reference_byte_currentness"][field] = value
                with self.assertRaises(ValueError):
                    reader._source_profile(profile, "bitwise_v2_cuda", cp, sources, reader._model_bytes(cp))

    def test_public_rows_bind_input_hashes_ids_status_and_finite_margin(self):
        cp, sources = _checkpoint()
        report, _, inputs = _public(cp, sources)
        reader._row_inputs(report, inputs, 1, cp)
        for field, value in (("source_sha256", "0" * 64), ("latent_sha256", "0" * 64), ("id", "other"),
                             ("minimum_decision_logit_margin", float("inf")), ("minimum_decision_logit_margin", 0.0)):
            with self.subTest(field=field):
                changed = deepcopy(report)
                changed["rows"][0][field] = value
                with self.assertRaises(ValueError):
                    reader._row_inputs(changed, inputs, 1, cp)

    def test_actual_public_observation_joins_unique_report_and_numeric_return(self):
        cp, sources = _checkpoint()
        report, numeric, inputs = _public(cp, sources)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "formula8-original_cpu_reference-1"
            archive, pins = _archive(root, {name + "-result.json": report, name + "-projected-vectors.json": numeric})
            observation = {"result": pins[0], "projected_vectors": pins[1], "elapsed_seconds": 0.25,
                "cpu_cuda_rng_unchanged": True, "included_in_paired_timing": False,
                "python_call_profiler_attached_during_timing": True}
            canonical, returned = reader._observation(archive, observation, name=name,
                label="original_cpu_reference", count=1, checkpoint=cp, inputs=inputs, source_shas=sources,
                byte_plan=reader._model_bytes(cp))
            self.assertEqual(returned, numeric)
            self.assertNotIn("inference_implementation", canonical)
            with self.assertRaises(ValueError):
                reader._observation(archive, observation, name=name, label="original_cpu_reference", count=1,
                    checkpoint=cp, inputs=inputs, source_shas=sources, byte_plan=reader._model_bytes(cp))
            archive.finish()

    def test_three_way_timing_positive_recomputes_full_order_and_ratios(self):
        self._timing_case()

    def test_three_way_timing_refuses_forged_order_medians_ratios_and_missing_routes(self):
        for mutation in ("order", "trial", "median", "ratio", "paired", "missing_route", "boolean_positions"):
            with self.subTest(mutation=mutation):
                with self.assertRaises((ValueError, KeyError)):
                    self._timing_case(mutation)

    def _timing_case(self, mutation=None):
        trials, samples = [], {lane: [] for lane in reader.CUDA_LANES}
        for index in range(12):
            observations = {lane: {"elapsed_seconds": float(position + 1) + index / 100.0}
                            for position, lane in enumerate(reader.CUDA_LANES)}
            trials.append({"trial": index, "order": list(reader.ORDERS[index % 6]), "observations": observations})
            for lane, observation in observations.items():
                samples[lane].append(observation["elapsed_seconds"])
        medians = {lane: reader.statistics.median(values) for lane, values in samples.items()}
        entry = {"trials": trials, "samples_seconds": samples, "median_seconds": medians,
            "sample_count_each_route": 12, "order_schedule": "all_six_permutations_repeated_twice",
            "first_position_each_route": 4, "second_position_each_route": 4, "third_position_each_route": 4,
            "median_original_over_v1_ratio": medians["original_cuda"] / medians["bitwise_v1_cuda"],
            "median_original_over_v2_ratio": medians["original_cuda"] / medians["bitwise_v2_cuda"],
            "median_v1_over_v2_ratio": medians["bitwise_v1_cuda"] / medians["bitwise_v2_cuda"],
            "paired_v1_over_v2_ratios": [a / b for a, b in zip(samples["bitwise_v1_cuda"], samples["bitwise_v2_cuda"])],
            "interpretation": "descriptive_same_fixture_guarded_complete_calls_no_universal_gain_claim"}
        if mutation == "order":
            trials[0]["order"] = list(reader.ORDERS[1])
        elif mutation == "trial":
            trials[0]["trial"] = False
        elif mutation == "median":
            medians["original_cuda"] += 1.0
        elif mutation == "ratio":
            entry["median_v1_over_v2_ratio"] = 1.0
        elif mutation == "paired":
            entry["paired_v1_over_v2_ratios"][0] = 1.0
        elif mutation == "missing_route":
            del trials[0]["observations"]["bitwise_v2_cuda"]
        elif mutation == "boolean_positions":
            entry["first_position_each_route"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, pins = _archive(root, {"formula8-1-raw-three-way-timings.json":
                {name: entry[name] for name in ("trials", "samples_seconds", "median_seconds")}})
            entry["raw_timing_evidence"] = pins[0]
            seen = []
            actual_samples, actual_medians, positions = reader._timings(archive, "formula8", 1, entry,
                lambda lane, observation, name: seen.append(name))
            self.assertEqual(actual_samples, samples)
            self.assertEqual(actual_medians, medians)
            self.assertEqual(len(set(seen)), 36)
            self.assertEqual(list(positions.values()), [[4, 4, 4]] * 3)
            archive.finish()

    def test_cleanup_zero_resources_refuses_boolean_or_live_allocation(self):
        result = {"qualified": False, "owned_children": [], "families": {}, "optimizer_constructor_calls": 0,
            "root_release_observed": False, "own_root_lease_released": False,
            "resources_after": {"active_lease_count": 0, "active_root_lease_count": 0,
                "active_child_lease_count": 0, "waiting_request_count": 0,
                "allocated": {"cpu_slots": 0, "memory_mb": 0},
                "allocated_gpu_memory_mb": 0, "allocated_unified_memory_mb": 0}}
        self.assertEqual(reader._cleanup(result), (False, {}))
        for key in ("active_lease_count", "active_root_lease_count", "active_child_lease_count", "waiting_request_count",
                    "allocated_gpu_memory_mb", "allocated_unified_memory_mb"):
            for value in (False, 1):
                with self.subTest(key=key, value=value):
                    changed = deepcopy(result)
                    changed["resources_after"][key] = value
                    with self.assertRaises(ValueError):
                        reader._cleanup(changed)

    def test_constructor_journal_retains_real_restore_completion_after_owner_failure(self):
        receipt = {"dimension": 8, "route": "original_cuda", "checkpoint_sha256": reader.FIXTURES["formula8_checkpoint"],
            "started": True, "completed": False, "observation_scope": "constructor_only_source_bound_python_call_observer",
            "adam_restore_attempts": 1, "adam_restore_completions": 1, "elapsed_seconds": 0.125}
        result = {"constructor_observations": [receipt], "optimizer_restore_attempts": 1, "optimizer_constructor_calls": 1}
        self.assertEqual(reader._constructor_journal(result), [receipt])

    def test_constructor_journal_refuses_duplicate_route_wrong_checkpoint_or_invented_completion(self):
        receipt = {"dimension": 8, "route": "original_cuda", "checkpoint_sha256": reader.FIXTURES["formula8_checkpoint"],
            "started": True, "completed": True, "observation_scope": "constructor_only_source_bound_python_call_observer",
            "adam_restore_attempts": 1, "adam_restore_completions": 1, "elapsed_seconds": 0.125}
        for mutation in ("duplicate", "checkpoint", "boolean_attempt", "missing_completion", "total"):
            with self.subTest(mutation=mutation):
                result = {"constructor_observations": [deepcopy(receipt)], "optimizer_restore_attempts": 1, "optimizer_constructor_calls": 1}
                if mutation == "duplicate":
                    result["constructor_observations"].append(deepcopy(receipt))
                elif mutation == "checkpoint":
                    result["constructor_observations"][0]["checkpoint_sha256"] = "0" * 64
                elif mutation == "boolean_attempt":
                    result["constructor_observations"][0]["adam_restore_attempts"] = True
                elif mutation == "missing_completion":
                    result["constructor_observations"][0]["adam_restore_completions"] = 0
                else:
                    result["optimizer_constructor_calls"] = 0
                with self.assertRaises(ValueError):
                    reader._constructor_journal(result)

    def test_unjoined_partial_refuses_arbitrary_file_and_never_grants_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, _ = _archive(root, {"unexpected-proof.json": {"proof_authority": False}})
            with self.assertRaises(ValueError):
                archive.finish(partial=True)

    def test_unjoined_partial_accepts_named_plain_return_only_in_failed_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, pins = _archive(root, {"formula8-1-trial00-original_cuda-result.json": {"proof_authority": False}})
            self.assertEqual(archive.finish(partial=True), pins)

    def test_external_result_sha_and_parse_refusals_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = _write(root / "result.json", {"schema": "fictional_control_only"})
            for expected in ("0" * 64, "F" * 64, False, pin["sha256"]):
                with self.subTest(expected=expected):
                    result = reader.audit(root, expected)
                    self.assertIs(result["qualified"], False)
                    self.assertIs(result["closed_artifacts_consistent"], False)
                    self.assertIsNotNone(result["error"])
                    self.assertIs(result["model_executed"], False)


if __name__ == "__main__":
    unittest.main()
