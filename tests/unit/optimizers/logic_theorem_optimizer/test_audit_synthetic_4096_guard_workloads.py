"""Authored ordinary-byte controls, explicitly fictional and never executed.

No producer, Torch, model, native kernel or resource owner is imported. Fictional
zero-step archives exercise the full397-file/270-return reader contract and
negative mutations; accepted consistency never represents device execution.
"""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_REPO = Path(__file__).absolute().parents[4]
_PATH = _REPO / "benchmarks/audit_synthetic_4096_guard_workloads.py"
_SPEC = importlib.util.spec_from_file_location("authored_4096_workload_closed_reader", _PATH)
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)
_OLD = Path(__file__).with_name("test_audit_synthetic_4096_head_device.py")
_require_old_sha = "f23293e03d5ea2fccf459665f66d220f996629d5299204ca966c4606fa799045"
if hashlib.sha256(_OLD.read_bytes()).hexdigest() != _require_old_sha:
    raise ValueError("current authored ordinary-control helper pin differs")
_OLD_SPEC = importlib.util.spec_from_file_location("current_authored_4096_byte_controls", _OLD)
ordinary_controls = importlib.util.module_from_spec(_OLD_SPEC)
_OLD_SPEC.loader.exec_module(ordinary_controls)


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class AuthoredWorkloadArchive(ordinary_controls.AuthoredArchive):
    """Fictional source/weights/receipts, built solely with ordinary Python."""
    def __init__(self, directory, *, candidate_seconds=1.01):
        self.current_width = 5
        super().__init__(directory)
        for child in list(self.root.iterdir()):
            if child.name not in {"synthetic-inputs.json", "synthetic-untrained-checkpoint.json", "producers"}:
                child.unlink()
        for child in (self.root / "producers").iterdir():
            child.unlink()
        self.paths = {role: self.current / path.name for role, path in module._source_paths().items()}
        self.report["source_pins"] = []
        self.source_pins = {}
        for role, path in self.paths.items():
            raw = ("# explicitly fictional ordinary source bytes: " + role).encode()
            path.write_bytes(raw)
            retained = self.root / "producers" / (role + "-" + path.name)
            retained.write_bytes(raw)
            retained.chmod(0o444)
            source = {"role": role, "current": pin(path), "retained_copy": pin(retained)}
            self.report["source_pins"].append(source)
            self.source_pins[role] = source["current"]
            if role in {"benchmark", "configuration", "cuda_cleanup", "qualified_v2_helpers", "qualified_quad_v2"}:
                self.report[role] = source["current"]
        self.checkpoint["implementation"] = {"native4096_sha256": self.source_pins["head"]["sha256"],
            "base_span": {role: self.source_pins[role]["sha256"] for role in ("span", "codec", "grammar", "canonical")}}
        self.report["checkpoint"] = self.write("synthetic-untrained-checkpoint.json", self.checkpoint)
        self.cp_sha = module._digest(self.checkpoint)
        self.report.update(schema=module.SCHEMA, scope="explicitly fictional authored byte controls; no execution",
            bitwise_full_session_fixture_qualified=True, complete_gpu_session_speedups_qualified=True,
            conservative_complete_call_gain_observed=False, selected_product_route_changed=False,
            future_repeatability_claimed=False, workload_budget_seconds=120,
            admitted_work_budget_completed=True, admitted_work_seconds_before_cleanup=10.0,
            work_budget_started_after_root_admission=True, admission_timeout_seconds=30,
            paired_observations_per_workload=12, cpu_observations_per_workload=3,
            all_timed_return_bytes_and_projections_retained=True,
            binding_check_optimization_does_not_remove_original_boundaries=True,
            all_workload_shape_preflights_match_producer_before_first_cuda_tensor=True,
            cpu_reference_numeric_profile={"device": "cpu", "dtype": "float32",
                "numeric_batching": "actual_singleton_forwards_concatenated",
                "equal_fixture_token_width_required_per_workload": True, "used_for_four_logit_parity": True},
            cuda_pair_timing_profile={"sample_count_per_lane_per_workload":12,
                "each_lane_first_per_workload":6, "native_forwards_overlap":False,
                "source_guard_or_anchor_boundary_removed":False,
                "all_timed_returns_retained_before_comparison":True,
                "serialization_outside_measured_call":True, "warmup_calls_per_lane_per_workload":1},
            expected_timed_return_count=270, timed_return_count=270)
        for key in ("cpu_reference_results", "cpu_reference_logits", "cpu_reference_decision_projections",
                    "head_warm_speedups_cpu_over_cuda_batched"):
            self.report.pop(key, None)
        self.report["lanes"] = {}
        for label in module.LABELS:
            profile = self.profile(label)
            self.report["lanes"][label] = {"profile":deepcopy(profile), "final_profile":deepcopy(profile),
                "constructor_seconds":0.01, "own_child_lease_released":True,
                "paired_reference_corruption_refusals":[{"corruption":name,"refused":True,
                    "entry_refused_before_forward":True,
                    "refusal":"immutable reference byte anchor changed" if name=="anchor_object_replacement"
                         else "reference bytes changed from admitted checkpoint"}
                    for name in ("paired_finite_value","paired_signed_zero","anchor_object_replacement")],
                "model_only_subnormal_control":{"corruption":"model_only_smallest_positive_float32_subnormal",
                    "actual_float32_bits_int32":1, "refused":True, "entry_refused_before_forward":True,
                    "refusal":"owned tensor values, signed zeros or finite profile changed"}}
        guard = self.report["guard"]
        guard.update(candidate_integrated_into_timed_head_session=True,
            integration_scope=["bitwise_cpu","bitwise_cuda_batched"], native_equal_nonfinite_pair_refusals=[])
        for label in ("cuda_reference","cuda_combined","cuda_bitwise_candidate"):
            role="bitwise_primitive_candidate" if label=="cuda_bitwise_candidate" else "tensor_guard"
            guard[label]["receipt"]["implementation"]["source_sha256"]=self.source_pins[role]["sha256"]
            for corruption,bits in (("paired_equal_nan_bits",2143289344),("paired_equal_inf_bits",2139095040)):
                guard["native_equal_nonfinite_pair_refusals"].append({"lane":label,"corruption":corruption,
                    "optimized":label!="cuda_reference","state_float32_bits_int32":bits,
                    "reference_float32_bits_int32":bits,"refused":True,"refusal":"authored paired nonfinite refusal"})
        inputs=module._authored_inputs()
        self.report["workload_inputs"]=self.write("authored-workloads.json",inputs)
        self.report["workloads"]=[]
        (self.root/"workloads").mkdir()
        original_rows=self.rows
        for position,case in enumerate(inputs):
            count=case["row_count"]
            self.current_width=module.WIDTHS[case["family"]]
            self.rows=[{**row,"source_text":text} for row,text in zip(original_rows[:count],case["texts"])]
            prefix="workloads/"+case["id"]+"/"
            (self.root/prefix).mkdir()
            reference=self.public(count,"cpu",reference=True)
            projection=module.base._projection(reference)
            entry={"id":case["id"],"family":case["family"],"row_count":count,
                "shape_preflight":case["shape_preflight"],"fixture_qualified":True,
                "paired_measurement_complete":True,"lanes":{},"cuda_pairs":[],
                "cpu_reference_result":self.write(prefix+"cpu-singleton-reference.json",reference),
                "cpu_reference_decision_projection":self.write(prefix+"cpu-singleton-reference-canonical-projection.json",projection),
                "cpu_reference_logits":self.write(prefix+"cpu-singleton-reference-logits.json",self.logits(count))}
            for label in module.LABELS:
                seconds=2.0 if label=="cpu" else 3.0 if label=="bitwise_cpu" else 1.0 if label=="cuda_batched" else candidate_seconds
                samples,bundle=[],[]
                for index in range(module.PAIRS if label in module.GPU_LABELS else module.CPU_SAMPLES):
                    actual=self.public(count,label)
                    value=module.base._projection(actual)
                    samples.append({"sample_index":index,"seconds_per_completed_public_call":seconds,
                        "result":self.write(prefix+f"{label}-sample{index:02d}.json",actual),
                        "canonical_projection":{"bytes":len(module._wire(value)),"sha256":module._digest(value),"bundle_index":index},
                        "canonical_rows_match_cpu":True,"public_profile_checked":True,
                        "canonical_projection_profile_id":"native4096-exact-decisions-separate-numeric-diagnostics/v1"})
                    bundle.append({"sample_index":index,"canonical_projection":value})
                entry["lanes"][label]={"samples":samples,"samples_seconds_per_call":[seconds]*len(samples),
                    "sample_count":len(samples),"median_seconds":seconds,"repetitions_per_sample":1,
                    "canonical_projection_bundle":self.write(prefix+label+"-canonical-projections.json",bundle),
                    "logits":self.write(prefix+label+"-logits.json",self.logits(count)),
                    "four_logit_max_abs_errors":{name:0.0 for name in module.base.OUTPUTS},
                    "numeric_scope":{"scope":"benchmark_only_checked_private_forward",
                        "entry_and_exit_owned_session_checks":True,"public_cpu_opt_out_still_uses_singletons":True,
                        "observations":[self.observation(count,label)],
                        "batch_memory_bound":self.memory_bound(count)}}
            for index in range(12):
                order=list(module.GPU_LABELS[::-1] if (bool(index%2)!=bool(position%2)) else module.GPU_LABELS)
                entry["cuda_pairs"].append({"pair_index":index,"completed_call_order":order,
                    "seconds":{label:entry["lanes"][label]["samples"][index]["seconds_per_completed_public_call"] for label in module.GPU_LABELS},
                    "sample_results":{label:entry["lanes"][label]["samples"][index]["result"] for label in module.GPU_LABELS}})
            entry["paired_ratio_analysis"]=module._ratio_analysis(entry["cuda_pairs"])
            entry["full_session_speedup_original_cuda_over_bitwise_cuda"]=1.0/candidate_seconds
            entry["full_session_speedup_original_cpu_over_bitwise_cpu"]=2.0/3.0
            entry["original_cpu_over_original_cuda"]=2.0
            self.report["workloads"].append(entry)
        self.rows=original_rows
        self.report["full_session_speedups_v2_cuda_over_bitwise_cuda"]={case["id"]:case["full_session_speedup_original_cuda_over_bitwise_cuda"] for case in self.report["workloads"]}
        gains=[case["id"] for case in self.report["workloads"] if case["paired_ratio_analysis"]["conservative_empirical_gain_observed"]]
        self.report["workloads_with_conservative_empirical_gain"]=gains
        self.report["suite_empirical_gain_criteria_met"]=len(gains)==9
        self.report["conservative_complete_call_gain_observed"]=len(gains)==9
        self.commit()

    def profile(self,label):
        result=super().profile("cpu" if label in module.CPU_LABELS else "cuda_batched")
        return self.bitwise_profile(result,label,2) if label.startswith("bitwise_") else result

    def observation(self,count,label):
        result=super().observation(count,"cpu" if label in module.CPU_LABELS else "cuda_batched")
        result["source_tokens"]=[self.current_width]*count
        return result

    def logits(self,count):
        return {"modality":ordinary_controls.zeros((count,3)),"presence":ordinary_controls.zeros((count,4,2)),
                "start":ordinary_controls.zeros((count,6,self.current_width)),"end":ordinary_controls.zeros((count,6,self.current_width))}

    def memory_bound(self,count):
        case=next(case for case in module._authored_inputs() if module.WIDTHS[case["family"]]==self.current_width)
        return module._memory_bound(count,self.current_width,case["shape_preflight"]["maximum_casefold_token_utf8_bytes"],self.checkpoint,
            {"reference_bytes":self.reference_bytes})

    def public(self,count,label,reference=False):
        value=super().public(count,"cpu" if label in module.CPU_LABELS else "cuda_batched",reference=reference)
        if not reference:
            value["execution_profile"]=self.profile(label)
            value["batch_memory_bound"]=self.memory_bound(count if label in module.GPU_LABELS else 1)
        return value

    def write(self,name,value):
        path=self.root/name
        if path.exists():
            path.chmod(0o600)
        path.write_bytes(module._wire(value))
        path.chmod(0o444)
        return pin(path)

    def commit(self):
        files=[path for path in self.root.rglob("*") if path.is_file() and path.name!="result.json"]
        self.report["retained_file_count_before_result"]=len(files)
        self.report["retained_total_bytes_before_result"]=sum(path.stat().st_size for path in files)
        self.report["retained_namespace_within_bounds_before_result"]=True
        self.result_pin=self.write("result.json",self.report)
        return self.result_pin["sha256"]


class GuardWorkloadClosedControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.fixture=AuthoredWorkloadArchive(Path(self.temporary.name))
        self.patches=[patch.object(module,"_source_paths",return_value=self.fixture.paths),
            patch.object(module,"EXPECTED_SOURCE_SHA",{role:value["sha256"] for role,value in self.fixture.source_pins.items()}),
            patch.object(module,"EXPECTED_CHECKPOINT_SHA",self.fixture.cp_sha),
            patch.object(module,"EXPECTED_ANCHOR_SHA",self.fixture.anchor_sha)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def audit(self,current=True):
        return module.audit(self.fixture.root,expected_result_sha256=self.fixture.commit(),check_current_sources=current)

    def reject(self,value):
        self.assertFalse(value["qualified"])
        self.assertFalse(value["closed_artifacts_consistent"])
        self.assertIsNotNone(value["error"])
        self.assertFalse(value["native_execution_attested"])

    def test_full397_files270_returns_are_consistent_without_performance_or_execution_authority(self):
        value=self.audit()
        self.assertTrue(value["closed_artifacts_consistent"],value["error"])
        self.assertTrue(value["qualified"],value["error"])
        self.assertEqual(value["checks"]["timed_returns_checked"],270)
        self.assertEqual(len(value["retained_pins"]),397)
        self.assertFalse(value["conservative_complete_call_gain_observed"])
        self.assertFalse(value["native_execution_attested"])

    def test_candidate_slower_than_original_cannot_forge_positive_suite_gain(self):
        self.fixture.report["conservative_complete_call_gain_observed"]=True
        self.reject(self.audit())

    def test_forged_case_ratio_and_bootstrap_interval_refuse(self):
        self.fixture.report["workloads"][0]["paired_ratio_analysis"]["bootstrap"]["descriptive_percentile_95_interval"]=[2.0,3.0]
        self.reject(self.audit())

    def test_every_timed_return_is_checked_including_last_pair(self):
        case=self.fixture.report["workloads"][-1]
        sample=case["lanes"]["bitwise_cuda_batched"]["samples"][-1]
        raw=json.loads(Path(sample["result"]["path"]).read_bytes())
        raw["rows"][-1]["reason"]="last measured return silently changed"
        sample["result"]=self.fixture.write("workloads/long-rows32/bitwise_cuda_batched-sample11.json",raw)
        case["cuda_pairs"][-1]["sample_results"]["bitwise_cuda_batched"]=sample["result"]
        self.reject(self.audit())

    def test_missing_sample_and_missing_file_cannot_claim270(self):
        self.fixture.report["workloads"][0]["lanes"]["cpu"]["samples"].pop()
        self.reject(self.audit())

    def test_balanced_but_non_alternating_pair_order_refuses(self):
        pairs=self.fixture.report["workloads"][0]["cuda_pairs"]
        pairs[0]["completed_call_order"],pairs[1]["completed_call_order"]=pairs[1]["completed_call_order"],pairs[0]["completed_call_order"]
        self.reject(self.audit())

    def test_pair_seconds_cannot_disagree_with_raw_sample(self):
        self.fixture.report["workloads"][0]["cuda_pairs"][0]["seconds"]["cuda_batched"]=2.0
        self.reject(self.audit())

    def test_projection_bundle_cannot_hide_changed_unknown_row_field(self):
        case=self.fixture.report["workloads"][0]
        lane=case["lanes"]["cpu"]
        values=json.loads(Path(lane["canonical_projection_bundle"]["path"]).read_bytes())
        values[0]["canonical_projection"]["rows"][0]["unknown_decision"]="must remain exact"
        lane["canonical_projection_bundle"]=self.fixture.write("workloads/short-rows8/cpu-canonical-projections.json",values)
        self.reject(self.audit())

    def test_variable_width_pointer_array_cannot_use_short_shape(self):
        lane=self.fixture.report["workloads"][-1]["lanes"]["cpu"]
        values=json.loads(Path(lane["logits"]["path"]).read_bytes())
        values["end"][0][0]=values["end"][0][0][:5]
        lane["logits"]=self.fixture.write("workloads/long-rows32/cpu-logits.json",values)
        self.reject(self.audit())

    def test_logit_error_above_tolerance_refuses(self):
        lane=self.fixture.report["workloads"][0]["lanes"]["cuda_batched"]
        values=json.loads(Path(lane["logits"]["path"]).read_bytes())
        values["modality"][0][0]=module.base._float32(0.001)
        lane["logits"]=self.fixture.write("workloads/short-rows8/cuda_batched-logits.json",values)
        self.reject(self.audit())

    def test_claimed_finite_logit_must_be_genuine_float32(self):
        with self.assertRaises(module.AuditError):
            module._logits({name:ordinary_controls.zeros((1,3)) for name in module.base.OUTPUTS},{},1,5)
        with self.assertRaises(module.AuditError):
            module.base._float32(1e300)

    def test_proof_and_execution_flags_cannot_be_forged(self):
        for field in ("proof_authority","execution_attestation","production_qualified","kernel_resource_enforcement"):
            with self.subTest(field=field):
                self.fixture.report[field]=True
                self.reject(self.audit())
                self.fixture.report[field]=False

    def test_missing_cleanup_cannot_qualify(self):
        self.fixture.report.pop("own_root_lease_released")
        self.reject(self.audit())

    def test_nonzero_allocator_and_open_child_refuse(self):
        self.fixture.report["gpu_allocated_after_framework_workspace_clear_bytes"]=1
        self.reject(self.audit())

    def test_equal_nan_reference_refusal_must_be_preserved(self):
        self.fixture.report["guard"]["native_equal_nonfinite_pair_refusals"][0].update(refused=False,refusal=None)
        self.reject(self.audit())

    def test_session_reference_anchor_cannot_be_replaced_by_matching_claim(self):
        self.fixture.report["lanes"]["bitwise_cuda_batched"]["profile"]["reference_byte_currentness"]["anchor_sha256"]="0"*64
        self.reject(self.audit())

    def test_strict_cuda_scope_is_checked_for_each_return(self):
        lane=self.fixture.report["workloads"][0]["lanes"]["cuda_batched"]
        sample=lane["samples"][0]
        raw=json.loads(Path(sample["result"]["path"]).read_bytes())
        raw["actual_forward_batches"][0]["gru_precision"]["effective_policy"]["cudnn"]["allow_tf32"]=True
        sample["result"]=self.fixture.write("workloads/short-rows8/cuda_batched-sample00.json",raw)
        self.fixture.report["workloads"][0]["cuda_pairs"][0]["sample_results"]["cuda_batched"]=sample["result"]
        self.reject(self.audit())

    def test_source_currentness_is_opt_in_but_retained_join_is_required(self):
        path=self.fixture.paths["span"]
        path.write_bytes(b"replaced current source")
        self.reject(self.audit(current=True))
        value=self.audit(current=False)
        self.assertTrue(value["closed_artifacts_consistent"],value["error"])

    def test_retained_source_replacement_cannot_keep_old_pin(self):
        source=self.fixture.report["source_pins"][0]
        path=Path(source["retained_copy"]["path"])
        path.chmod(0o600)
        path.write_bytes(b"replaced retained source")
        path.chmod(0o444)
        self.reject(self.audit())

    def test_external_result_pin_is_required(self):
        value=module.audit(self.fixture.root,expected_result_sha256="0"*64)
        self.reject(value)

    def test_path_escape_and_symlink_directory_are_refused(self):
        self.fixture.report["workloads"][0]["lanes"]["cpu"]["samples"][0]["result"]["path"]="/tmp/escape.json"
        self.reject(self.audit())

    def test_unlisted_namespace_file_is_refused(self):
        self.fixture.write("unlisted.json",{"proof_authority":False})
        self.reject(self.audit())

    def test_symlink_and_hardlinked_ordinary_files_are_refused(self):
        name=self.fixture.root/"workloads/short-rows8/cpu-sample00.json"
        backup=self.fixture.current/"backup.json"
        shutil.copyfile(name,backup)
        name.unlink()
        name.symlink_to(backup)
        self.reject(self.audit())

    def test_hardlinked_retained_member_is_refused(self):
        name=self.fixture.root/"workloads/short-rows8/cpu-sample00.json"
        os.link(name,self.fixture.current/"second-owner.json")
        self.reject(self.audit())

    def test_symlink_workload_directory_is_refused(self):
        directory=self.fixture.root/"workloads/short-rows8"
        replacement=self.fixture.current/"private-case-directory"
        directory.rename(replacement)
        directory.symlink_to(replacement,target_is_directory=True)
        self.reject(self.audit())

    def test_directory_replacement_after_read_is_refused(self):
        reader=module._Reader(self.fixture.root)
        try:
            reader.read("workloads/short-rows8/cpu-sample00.json")
            folder=self.fixture.root/"workloads/short-rows8"
            replacement=self.fixture.current/"replacement"
            shutil.copytree(folder,replacement)
            shutil.rmtree(folder)
            shutil.copytree(replacement,folder)
            with self.assertRaises(module.AuditError):
                reader.final_check()
        finally:
            reader.close()

    def test_duplicate_nonfinite_deep_and_boolean_integer_json_are_refused(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'['*66+b'0'+b']'*66):
            with self.subTest(raw=raw):
                with self.assertRaises((module.AuditError,ValueError,RecursionError)):
                    module._json(raw)
        with self.assertRaises(module.AuditError):
            module._integer(True)

    def test_native_partial_archive_remains_unqualified_with_missing_evidence(self):
        self.fixture.report.update(architecture_fixture_qualified=False,bitwise_full_session_fixture_qualified=False,
            complete_gpu_session_speedups_qualified=False,head_numerical_fixture_qualified=False,
            conservative_complete_call_gain_observed=False,error={"type":"TimeoutError","message":"fictional partial run"})
        folder=self.fixture.root/"workloads"
        shutil.rmtree(folder)
        self.fixture.report["workloads"]=[]
        value=self.audit()
        self.assertTrue(value["closed_artifacts_consistent"],value["error"])
        self.assertFalse(value["qualified"])
        self.assertFalse(value["checks"]["numeric_report_checked"])
        self.assertEqual(value["scope"],"failed_partial_archive_ordinary_byte_consistency_only")

    def test_partial_archive_with_stale_sample_pin_is_not_consistent(self):
        self.fixture.report.update(architecture_fixture_qualified=False,bitwise_full_session_fixture_qualified=False,
            complete_gpu_session_speedups_qualified=False,head_numerical_fixture_qualified=False,
            conservative_complete_call_gain_observed=False,error={"type":"TimeoutError","message":"fictional partial"})
        (self.fixture.root/"workloads/short-rows8/cpu-sample00.json").unlink()
        self.reject(self.audit())

    def test_no_torch_or_retained_python_import_is_needed(self):
        original=builtins.__import__
        def forbid(name,*args,**kwargs):
            if name=="torch" or name.startswith("torch.") or name.startswith("ipfs_datasets_py"):
                raise AssertionError("ordinary closed reader must not import models/producers")
            return original(name,*args,**kwargs)
        with patch.object(builtins,"__import__",side_effect=forbid):
            value=self.audit(current=False)
        self.assertTrue(value["closed_artifacts_consistent"],value["error"])

    def test_standardlib_ratio_analysis_has_no_global_repeatability_claim(self):
        analysis=self.fixture.report["workloads"][0]["paired_ratio_analysis"]
        self.assertLess(analysis["paired_ratio_median"],1.0)
        self.assertFalse(analysis["conservative_empirical_gain_observed"])
        self.assertFalse(analysis["nominal_coverage_assumptions_established"])
        self.assertFalse(analysis["bootstrap"]["simultaneous_family_or_future_repeatability_confidence_claimed"])


if __name__=="__main__":
    unittest.main()
