"""Authored byte/report controls; no Torch, models, CUDA or owners execute.

The positive archives below are explicitly controlled fictional reports. A
successful audit proves their byte/report consistency, never their execution.
"""
from copy import deepcopy
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

_PATH = Path(__file__).absolute().parents[4] / "benchmarks/audit_synthetic_4096_head_device.py"
_SPEC = importlib.util.spec_from_file_location("synthetic4096_closed_auditor_controls", _PATH)
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def zeros(shape):
    return [zeros(shape[1:]) for _ in range(shape[0])] if shape else 0.0


class AuthoredArchive:
    def __init__(self, base):
        self.root, self.current = base / "archive", base / "current"
        self.root.mkdir()
        self.current.mkdir()
        (self.root / "producers").mkdir()
        self.paths = {role: self.current / path.name for role, path in module._source_paths().items()}
        self.report = {"schema": "native4096-synthetic-head-device-qualification/v2",
            "scope": "controlled fictional report; no runtime executed", "architecture_fixture_qualified": True,
            "head_numerical_fixture_qualified": True, "optional_bitwise_primitive_enabled": True,
            "native_leanstral_qualified": False, "production_qualified": False, "proof_authority": False,
            "execution_attestation": False, "kernel_resource_enforcement": False, "error": None,
            "source_pins": [], "source_bytes_unchanged": True, "encoder_calls": 0, "optimizer_steps": 0,
            "training_calls": 0, "optimizer_construction_attempts": 0, "foreign_process_actions": False,
            "persistent_precision_policy_mutated": False, "checkpoint_unchanged": True, "adam_unchanged": True,
            "latent_adapter_shape": [4, 4096], "zero_output_adapter": True, "latent_conditioning_trained": False,
            "own_root_lease_released": True, "guard_child_lease_released": True, "cpu_threads_restored": True,
            "root_release_does_not_force_child_release": True, "gpu_allocated_before_owned_sessions_bytes": 0,
            "gpu_allocated_after_owned_sessions_closed_bytes": 32, "gpu_allocated_after_framework_workspace_clear_bytes": 0,
            "framework_cuda_workspace_clear_supported": True, "cuda_cleanup_status": "owned_allocations_restored_to_baseline",
            "gpu_allocated_after_producer_imports_bytes": 0, "producer_imports_preserved_zero_cuda_allocation": True,
            "actual_initial_cuda_kernel": True, "initial_cuda_kernel_output": [4.0], "module_import_context_diagnostics": [],
            "hardware": {"device_index": 0, "device": "controlled fictional device", "torch": "not imported"}, "pid": 999,
            "resources_after": {"active_lease_count": 0, "active_child_lease_count": 0, "active_root_lease_count": 0,
                "allocated_child_process_slots": 0, "allocated_gpu_memory_mb": 0, "allocated_unified_memory_mb": 0,
                "allocated": {"cpu_slots": 0, "memory_mb": 0}},
            "admission": {"lease_id": "controlled-root", "owner_pid": 999, "parent_lease_id": None,
                "requires_gpu": True, "memory_mb": 2048, "gpu_memory_mb": 512, "unified_memory_mb": 2560},
            "cpu_reference_numeric_profile": {"device": "cpu", "dtype": "float32",
                "numeric_batching": "actual_singleton_forwards_concatenated", "equal_fixture_token_width_required": True,
                "used_for_four_logit_parity": True}, "cpu_reference_results": {}, "cpu_reference_logits": {},
            "cpu_reference_decision_projections": {}, "lanes": {}, "qualification_refusals": []}
        for role, path in self.paths.items():
            if role == "bitwise_device_session":
                continue
            raw = ("# controlled source bytes for " + role).encode()
            path.write_bytes(raw)
            retained = self.root / "producers" / (role + "-" + path.name)
            retained.write_bytes(raw)
            item = {"role": role, "current": pin(path), "retained_copy": pin(retained)}
            self.report["source_pins"].append(item)
            if role in {"benchmark", "configuration", "cuda_cleanup"}:
                self.report[role] = item["current"]
        self.source_pins = {item["role"]: item["current"] for item in self.report["source_pins"]}
        self.rows = []
        for index in range(32):
            vector = [0.0001] * 4096
            vector[-1] = (index + 1) / 32
            text = "Lark must retain books." if index == 0 else f"Worker{index} may publish records."
            self.rows.append({"id": f"synthetic4096-{index}", "source_text": text, "latent": vector})
        self.report["rows"] = self.write("synthetic-inputs.json", self.rows)
        shapes = {"byte_embedding.weight": (257, 4), "token_projection.weight": (8, 13), "token_projection.bias": (8,),
                  "latent_down.weight": (4, 4096), "latent_down.bias": (4,), "latent_up.weight": (16, 4), "latent_up.bias": (16,)}
        for suffix in ("", "_reverse"):
            for name in ("weight_ih_l0", "weight_hh_l0"):
                shapes["encoder." + name + suffix] = (24, 8)
            for name in ("bias_ih_l0", "bias_hh_l0"):
                shapes["encoder." + name + suffix] = (24,)
        for name, width in (("modality", 3), ("presence", 8), ("start", 6), ("end", 6)):
            shapes[name + ".weight"], shapes[name + ".bias"] = (width, 16), (width,)
        state = {name: zeros(shape) for name, shape in shapes.items()}
        source = {name: value for name, value in state.items() if not name.startswith(("latent_down.", "latent_up."))}
        training = [{**self.rows[0], "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O", "action": "retain",
            "object": "books", "conditions": [], "exceptions": [], "temporal": []}]}}]
        context = {"dimension": 4096, "representation_id": "synthetic-4096-untrained-architecture-control",
                   "producer_sha256": hashlib.sha256(b"authored synthetic vectors; no encoder").hexdigest(),
                   "training_index_sha256": module._digest(training)}
        self.checkpoint = {"schema": "native-4096-source-span-checkpoint/v1", "lineage_id": "native_4096_source_span_v1",
            **{name: False for name in module.FALSE_FLAGS},
            "config": {"architecture": "utf8-byte-bidirectional-gru-native-4096-film-spans/v1", "latent_dimension": 4096,
                "latent_enabled": True, "device": "cpu", "dtype": "float32", "hidden_size": 8, "embedding_dim": 4,
                "projection_width": 4, "batch_size": 1, "seed": 1729, "residual_scale": 0.25,
                "max_source_characters": 16384, "max_source_tokens": 256, "max_token_bytes": 2048},
            "model_state": state, "initial_model_state_sha256": module._digest(state),
            "initial_source_model_sha256": module._digest(source), "progress": {"epochs_completed": 0, "optimizer_steps": 0, "row_cursor": 0},
            "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}}, "source_parent_checkpoint": None,
            "source_parent_checkpoint_sha256": None, "source_parent_optimizer_steps": 0, "parent_checkpoint_sha256": None,
            "provenance": {"schema": "native-4096-source-span-provenance/v1", "kind": "synthetic_untrained_architecture_control",
                "synthetic_embeddings": True, "trusted_native_owner_verified": False},
            "training_manifest_sha256": module._digest(training), "tuning_manifest_sha256": module._digest([]),
            "training_count": 1, "tuning_count": 0, "context_contract": context, "context_contract_sha256": module._digest(context),
            "implementation": {"native4096_sha256": self.source_pins["head"]["sha256"],
                "base_span": {name: self.source_pins[name]["sha256"] for name in ("span", "codec", "grammar", "canonical")}}}
        self.report["checkpoint"] = self.write("synthetic-untrained-checkpoint.json", self.checkpoint)
        self.cp_sha, self.adam_sha = module._digest(self.checkpoint), module._digest(self.checkpoint["optimizer_state"])
        self.reference_bytes = 4 * sum(self._elements(shape) for shape in shapes.values())
        self.anchor_sha = hashlib.sha256(bytes(self.reference_bytes)).hexdigest()
        self.ambient = {"cudnn": {"enabled": True, "allow_tf32": True}, "cuda_matmul_allow_tf32": False,
                        "float32_matmul_precision": "highest"}
        self.report["precision_policy_before"] = deepcopy(self.ambient)
        self.report["precision_policy_after"] = deepcopy(self.ambient)
        references = {}
        for count in module.COUNTS:
            key = str(count)
            reference = self.public(count, "cpu", reference=True)
            references[key] = reference
            self.report["cpu_reference_results"][key] = self.write(f"head-cpu-reference-batch{count}.json", reference)
            self.report["cpu_reference_logits"][key] = self.write(f"head-cpu-singleton-reference-batch{count}-logits.json", self.logits(count))
            self.report["cpu_reference_decision_projections"][key] = self.write(
                f"head-cpu-reference-batch{count}-canonical-projection.json", module._projection(reference))
        for lane in ("cpu", "cuda_batched"):
            profile = self.profile(lane)
            entry = {"profile": deepcopy(profile), "final_profile": deepcopy(profile), "constructor_seconds": 0.01,
                     "own_child_lease_released": True, "batches": {}, "paired_reference_corruption_refusals": [
                         {"corruption": name, "refused": True, "entry_refused_before_forward": True,
                          "refusal": "immutable reference byte anchor changed" if name == "anchor_object_replacement"
                                     else "reference bytes changed from admitted checkpoint"}
                         for name in ("paired_finite_value", "paired_signed_zero", "anchor_object_replacement")],
                     "model_only_subnormal_control": {"corruption": "model_only_smallest_positive_float32_subnormal",
                        "actual_float32_bits_int32": 1, "refused": True, "entry_refused_before_forward": True,
                        "refusal": "owned tensor values, signed zeros or finite profile changed"}}
            for count in module.COUNTS:
                key = str(count)
                actual = self.public(count, lane)
                batch = {**self.timing(1.0 if lane == "cpu" else 0.5, 1), "canonical_rows_match_cpu": True,
                         "result": self.write(f"head-{lane}-batch{count}.json", actual),
                         "logits": self.write(f"head-{lane}-batch{count}-logits.json", self.logits(count)),
                         "four_logit_max_abs_errors": {name: 0.0 for name in module.OUTPUTS},
                         "canonical_projection": self.write(f"head-{lane}-batch{count}-canonical-projection.json", module._projection(actual)),
                         "canonical_reference_projection": self.report["cpu_reference_decision_projections"][key],
                         "numeric_scope": {"scope": "benchmark_only_checked_private_forward",
                            "entry_and_exit_owned_session_checks": True, "public_cpu_opt_out_still_uses_singletons": True,
                            "observations": [self.observation(count, lane)]}}
                entry["batches"][key] = batch
            self.report["lanes"][lane] = entry
        self.report["head_warm_speedups_cpu_over_cuda_batched"] = {str(count): 2.0 for count in module.COUNTS}
        guard = {"tensor_shapes": {"adapter": [128, 4096], "gru": [128, 128]},
                 "timing_includes_complete_current_value_and_source_checks": True,
                 "lane_integrity_qualified": {}, "native_corruption_refusals": [],
                 "native_guard_primitive_qualified": True, "native_bitwise_guard_primitive_qualified": True,
                 "speedup_reference_over_combined": 2.0, "speedup_reference_over_bitwise_candidate": 4.0,
                 "speedup_combined_over_bitwise_candidate": 2.0}
        bits = {"changed_value": 1065353216, "signed_zero": -2147483648,
                "smallest_positive_float32_subnormal": 1, "nan": 2143289344, "inf": 2139095040}
        for index, lane in enumerate(("cuda_reference", "cuda_combined", "cuda_bitwise_candidate")):
            role = "bitwise_primitive_candidate" if lane == "cuda_bitwise_candidate" else "tensor_guard"
            guard[lane] = {**self.timing(1.0 / 2**index, 8), "receipt": {
                "schema": "owned-tensor-bitwise-value-guard/v1" if index == 2 else "owned-tensor-value-guard/v1",
                "mode": "cuda_reference_checks" if index == 0 else "cuda_single_host_decision" if index == 1 else "cuda_bitwise_single_host_decision",
                "implementation": {"source_sha256": self.source_pins[role]["sha256"],
                    "schema": "owned-tensor-bitwise-guard-implementation/v1" if index == 2 else "owned-tensor-value-guard-implementation/v1",
                    "comparison": "finite-float32-exact-bits-with-reference-finiteness/v1" if index == 2 else "finite-float32-exact-values-and-signed-zero/v1"},
                "comparison_device": "cuda:0",
                "tensor_count": 2, "state_and_reference_bytes": 2 * 4 * (128 * 4096 + 128 * 128),
                "host_decision_count": 8 if index == 0 else 1, "finite_values_checked": True,
                "signed_zero_checked": True, "all_current_values_checked": True}}
            guard["lane_integrity_qualified"][lane] = True
            for owner in ("state", "reference"):
                for corruption, value in bits.items():
                    guard["native_corruption_refusals"].append({"lane": lane, "owner": owner,
                        "corruption": corruption, "actual_float32_bits_int32": value, "optimized": index != 0,
                        "refused": True, "refusal": "controlled authored refusal"})
        self.report["guard"] = guard
        self.commit()

    def _elements(self, shape):
        result = 1
        for width in shape:
            result *= width
        return result

    def write(self, name, value):
        path = self.root / name
        path.write_bytes(module._wire(value))
        return pin(path)

    def commit(self):
        self.result_pin = self.write("result.json", self.report)
        return self.result_pin["sha256"]

    def timing(self, median, repetitions):
        return {"sample_count": 3, "repetitions_per_sample": repetitions,
                "samples_seconds_per_call": [median / 2, median, median * 2], "median_seconds": median}

    def logits(self, count):
        return {"modality": zeros((count, 3)), "presence": zeros((count, 4, 2)),
                "start": zeros((count, 6, 5)), "end": zeros((count, 6, 5))}

    def profile(self, lane):
        cpu = lane == "cpu"
        device = "cpu" if cpu else "cuda:0"
        return {**{name: False for name in module.FALSE_FLAGS}, "profile_id": module.SESSION_PROFILE,
            "strict_cuda_gru_profile_id": module.GRU_PROFILE, "dimension": 4096, "device": device, "dtype": "float32",
            "optimized": not cpu, "numerical_batching": "singleton_cpu_opt_out" if cpu else "one_complete_valid_source_batch",
            "checkpoint_sha256": self.cp_sha, "optimizer_state_sha256": self.adam_sha, "stored_checkpoint_device": "cpu",
            "checkpoint_conversion_performed": False, "inference_only": True, "synthetic_unreceipted_enabled": True,
            "canonical_decision_device": "cpu", "precision_policy": {"ambient_at_admission": None if cpu else deepcopy(self.ambient),
                "persistent_flags_mutated": False, "cuda_gru_allow_tf32": None if cpu else False},
            "reference_byte_currentness": {"schema": "native-4096-owned-reference-byte-currentness/v1",
                "checkpoint_sha256": self.cp_sha, "anchor_sha256": self.anchor_sha, "reference_bytes": self.reference_bytes,
                "reference_device": device, "origin": "independently_restored_validated_cpu_checkpoint_model",
                "comparison": "complete_immutable_float32_bytes_including_signed_zero", "device_to_cpu_reference_transfers": int(not cpu),
                "cpu_byte_materializations": 1, "anchor_identity_checked": True, "metadata_and_reservation_checked_before_allocation": True},
            "owned_tensor_currentness": {"schema": "owned-tensor-value-guard/v1",
                "mode": "cpu_reference_checks" if cpu else "cuda_single_host_decision",
                "implementation": {"source_sha256": self.source_pins["tensor_guard"]["sha256"],
                    "schema": "owned-tensor-value-guard-implementation/v1", "comparison": "finite-float32-exact-values-and-signed-zero/v1"},
                "comparison_device": device, "tensor_count": 23, "state_and_reference_bytes": 2 * self.reference_bytes,
                "host_decision_count": 92 if cpu else 1, "finite_values_checked": True, "signed_zero_checked": True,
                "all_current_values_checked": True},
            "implementation": {"source_sha256": self.source_pins["device_session"]["sha256"],
                "native4096_checkpoint_producer": deepcopy(self.checkpoint["implementation"]),
                "owned_tensor_value_guard_sha256": self.source_pins["tensor_guard"]["sha256"]},
            "resource_lease": {"parent_lease_id": "controlled-root", "owner_pid": 999, "requires_gpu": not cpu,
                "memory_mb": 1024, "gpu_memory_mb": 0 if cpu else 256}}

    def observation(self, count, lane):
        cpu = lane == "cpu"
        device = "cpu" if cpu else "cuda:0"
        precision = {"device": device, "persistent_flags_mutated": False,
                     "profile_id": module.SESSION_PROFILE if cpu else module.GRU_PROFILE, "scoped_cudnn": not cpu}
        if not cpu:
            precision.update(ambient_policy=deepcopy(self.ambient),
                effective_policy={**deepcopy(self.ambient), "cudnn": {**self.ambient["cudnn"], "allow_tf32": False}},
                synchronized_before_restore=True, ambient_flags_restored=True,
                requires_owned_process_without_unrelated_concurrent_cudnn=True)
        return {"rows": count, "source_tokens": [5] * count, "input_device": device, "native_input_dimension": 4096,
                "output_devices": {name: device for name in module.OUTPUTS}, "output_dtype": "float32",
                "gru_executed": True, "gru_precision": precision}

    def public(self, count, lane, reference=False):
        rows = []
        for source in self.rows[:count]:
            rows.append({**{name: False for name in module.FALSE_FLAGS}, "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(),
                "latent_sha256": module._digest(source["latent"]), "latent_input_enabled": True,
                "status": "abstained", "reason": "controlled authored report", "canonical_ir": None,
                "formal_outputs": [], "formula_text": None, "family_syntax_checked": False,
                "target_access": False, "teacher_forcing": False, "training_executed": False,
                "span_diagnostics": {"tokens": [{"text": match.group(), "start": match.start(), "end": match.end()}
                    for match in module._TOKEN.finditer(source["source_text"])], "modality_logits": [0.0, 0.0, 0.0], "facets": {}}})
        result = {**{name: False for name in module.FALSE_FLAGS}, "lineage_id": "native_4096_source_span_v1",
            "checkpoint_sha256": self.cp_sha, "context_contract_sha256": self.checkpoint["context_contract_sha256"],
            "input_dimension": 4096, "decoded_count": 0, "status": "abstained", "latent_ablation": "none",
            "target_access": False, "teacher_forcing": False, "training_executed": False,
            "model_state_unchanged": True, "rows": rows}
        if reference:
            return {**result, "schema": "native-4096-source-span-inference/v1", "synthetic_architecture_control": True}
        cpu = lane == "cpu"
        return {**result, "schema": "native-4096-source-span-device-inference/v1", "cuda_executed": not cpu,
            "numerical_batching": not cpu, "valid_source_count": count, "synthetic_embeddings": True,
            "execution_profile": self.profile(lane), "device_to_cpu_head_transfers": 0 if cpu else 4,
            "cpu_head_output_materializations": 0 if cpu else 4,
            "actual_forward_batches": [self.observation(1, lane) for _ in range(count)] if cpu else [self.observation(count, lane)]}

    def sequel(self, version=1):
        """Author four-lane reports without executing any retained implementation."""
        schema = "native4096-synthetic-bitwise-session-device-qualification/v" + str(version)
        self.report["schema"] = schema
        paths = module._report_source_paths(schema)
        helper = next(item for item in self.report["source_pins"] if item["role"] == "benchmark")
        raw = Path(helper["retained_copy"]["path"]).read_bytes()
        helper["role"] = "qualified_v2_helpers"
        helper["retained_copy"] = self.write_source("qualified_v2_helpers", paths["qualified_v2_helpers"], raw)
        self.report["qualified_v2_helpers"] = helper["current"]
        self.source_pins["qualified_v2_helpers"] = helper["current"]
        for role in ("benchmark", "bitwise_device_session"):
            path = paths[role]
            raw = ("# controlled sequel source " + role + str(version)).encode()
            path.write_bytes(raw)
            item = {"role": role, "current": pin(path), "retained_copy": self.write_source(role, path, raw)}
            self.report["source_pins"].append(item)
            self.source_pins[role] = item["current"]
            if role == "benchmark":
                self.report[role] = item["current"]
        for lane in ("cuda_batched", "bitwise_cpu", "bitwise_cuda_batched"):
            original = "cpu" if lane == "bitwise_cpu" else "cuda_batched"
            value = deepcopy(self.report["lanes"][original])
            value["comparator_changed_only"] = lane.startswith("bitwise_")
            if lane.startswith("bitwise_"):
                for key in ("profile", "final_profile"):
                    value[key] = self.bitwise_profile(value[key], lane, version)
            for count in module.COUNTS:
                key = str(count)
                batch = value["batches"][key]
                public = self.public(count, original)
                if lane.startswith("bitwise_"):
                    public["execution_profile"] = self.bitwise_profile(public["execution_profile"], lane, version)
                median = 1.25 if lane == "bitwise_cpu" else 0.625 if lane == "bitwise_cuda_batched" else 0.5
                batch.update(self.timing(median, 1))
                if lane != "bitwise_cpu":
                    batch.update(sample_count=4, samples_seconds_per_call=[median / 2, median, median, median * 2])
                batch["result"] = self.write(f"head-{lane}-batch{count}.json", public)
                batch["logits"] = self.write(f"head-{lane}-batch{count}-logits.json", self.logits(count))
                batch["canonical_projection"] = self.write(f"head-{lane}-batch{count}-canonical-projection.json", module._projection(public))
            self.report["lanes"][lane] = value
        self.report.update(bitwise_full_session_fixture_qualified=True, complete_gpu_session_speedups_qualified=True,
            bitwise_full_session_faster_batches=[], bitwise_full_session_speedup_demonstrated=False,
            cuda_pair_timing_profile={"sample_count_per_lane_per_batch": 4, "each_lane_first_per_batch": 2,
                "native_forwards_overlap": False, "source_guard_or_anchor_boundary_removed": False, "batches": {}})
        labels = ["cuda_batched", "bitwise_cuda_batched"]
        for position, count in enumerate(module.COUNTS):
            self.report["cuda_pair_timing_profile"]["batches"][str(count)] = {"completed_call_orders": [
                labels[::-1] if (bool(trial % 2) != bool(position % 2)) else labels for trial in range(4)]}
        for field, ratio in (("full_session_speedups_v2_cuda_over_bitwise_cuda", 0.8),
                ("full_session_speedups_v2_cpu_over_bitwise_cpu", 0.8),
                ("head_warm_speedups_cpu_over_bitwise_cuda_batched", 1.6),
                ("head_warm_speedups_bitwise_cpu_over_bitwise_cuda_batched", 2.0)):
            self.report[field] = {str(count): ratio for count in module.COUNTS}
        guard = self.report["guard"]
        guard.update(candidate_integrated_into_timed_head_session=True,
            integration_scope=["bitwise_cpu", "bitwise_cuda_batched"], native_equal_nonfinite_pair_refusals=[])
        for lane in ("cuda_reference", "cuda_combined", "cuda_bitwise_candidate"):
            for corruption, bits in (("paired_equal_nan_bits", 2143289344), ("paired_equal_inf_bits", 2139095040)):
                guard["native_equal_nonfinite_pair_refusals"].append({"lane": lane, "corruption": corruption,
                    "optimized": lane != "cuda_reference", "state_float32_bits_int32": bits,
                    "reference_float32_bits_int32": bits, "refused": True, "refusal": "controlled nonfinite reference refused"})

    def write_source(self, role, path, raw):
        retained = self.root / "producers" / (role + "-" + path.name)
        retained.write_bytes(raw)
        return pin(retained)

    def bitwise_profile(self, original, lane, version):
        result = deepcopy(original)
        variant = module.BITWISE_PROFILE if version == 1 else module.BITWISE_PROFILE_V2
        result.update(session_profile_id=variant, inherited_profile_id=module.SESSION_PROFILE,
            boundary_consolidation_performed=False, native_bitwise_session_cuda_qualified=False,
            bitwise_session_performance_qualified=False)
        if lane == "bitwise_cuda_batched":
            result["profile_id"] = variant
        result["owned_tensor_currentness"].update(schema="owned-tensor-bitwise-value-guard/v1",
            mode="cuda_bitwise_single_host_decision" if lane == "bitwise_cuda_batched" else "cpu_reference_checks",
            implementation={"schema": "owned-tensor-bitwise-guard-implementation/v1",
                "comparison": "finite-float32-exact-bits-with-reference-finiteness/v1",
                "source_sha256": self.source_pins["bitwise_primitive_candidate"]["sha256"]})
        result["implementation"] = {"source_sha256": self.source_pins["bitwise_device_session"]["sha256"],
            "bitwise_guard_source_sha256": self.source_pins["bitwise_primitive_candidate"]["sha256"],
            "inherited_session_source_sha256": self.source_pins["device_session"]["sha256"],
            "inherited_session_implementation": result["implementation"]}
        return result

    def decoded_rows(self, *, forbidden_nested_flag=None, forbidden_row_flag=None, malformed_facets=False):
        """Install controlled copied-span decisions in every matching report."""
        for count in module.COUNTS:
            key = str(count)
            for lane in (None, "cpu", "cuda_batched"):
                value = self.public(count, "cpu" if lane is None else lane, reference=lane is None)
                row = value["rows"][0]
                output = {"schema": "controlled-fictional-formal-output/v1", "formula": "must(Lark,retain,books)",
                          **{name: False for name in module.FALSE_FLAGS}, "target_access": False,
                          "teacher_forcing": False, "training_executed": False}
                row.update(status="decoded", reason=None, formula_text="must(Lark,retain,books)",
                    formal_outputs=[output], canonical_ir={"rules": [{"actor": "Lark", "modality": "O",
                        "action": "retain", "object": "books", "conditions": [], "exceptions": [], "temporal": []}]})
                row["span_diagnostics"]["facets"] = {"actor": {"present": True, "token_start": 0,
                    "token_end_inclusive": 0, "char_start": 0, "char_end": 4, "text": "Lark",
                    "presence_logit_margin": 0.0, "span_logit_margin": 0.0}}
                if forbidden_nested_flag is not None:
                    output[forbidden_nested_flag] = True
                if forbidden_row_flag is not None:
                    row[forbidden_row_flag] = True
                projection = module._projection(value)
                if malformed_facets:
                    row["span_diagnostics"]["facets"] = []
                value.update(decoded_count=1, status="decoded" if count == 1 else "partial")
                projection.update(decoded_count=1, status=value["status"])
                if lane is None:
                    self.report["cpu_reference_results"][key] = self.write(f"head-cpu-reference-batch{count}.json", value)
                    self.report["cpu_reference_decision_projections"][key] = self.write(
                        f"head-cpu-reference-batch{count}-canonical-projection.json", projection)
                else:
                    batch = self.report["lanes"][lane]["batches"][key]
                    batch["result"] = self.write(f"head-{lane}-batch{count}.json", value)
                    batch["canonical_projection"] = self.write(f"head-{lane}-batch{count}-canonical-projection.json", projection)
                    batch["canonical_reference_projection"] = self.report["cpu_reference_decision_projections"][key]


class Synthetic4096ClosedAuditControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = AuthoredArchive(Path(self.temporary.name))
        self.patches = [patch.object(module, "_source_paths", return_value=self.fixture.paths),
                        patch.object(module, "CONFIG_SHA", self.fixture.source_pins["configuration"]["sha256"]),
                        patch.object(module, "CLEANUP_SHA", self.fixture.source_pins["cuda_cleanup"]["sha256"]),
                        patch.object(module, "HELPERS_SHA", self.fixture.source_pins["benchmark"]["sha256"])]
        for control in self.patches:
            control.start()

    def tearDown(self):
        for control in reversed(self.patches):
            control.stop()
        self.temporary.cleanup()

    def audit(self, current=True):
        return module.audit(self.fixture.root, expected_result_sha256=self.fixture.commit(), check_current_sources=current)

    def assert_rejected(self, value):
        self.assertFalse(value["qualified"])
        self.assertFalse(value["closed_artifacts_consistent"])
        self.assertIsNotNone(value["error"])
        self.assertFalse(value["native_execution_attested"])

    def test_complete_authored_report_has_byte_consistency_and_no_execution_authority(self):
        value = self.audit()
        self.assertTrue(value["qualified"], value["error"])
        self.assertTrue(value["closed_artifacts_consistent"])
        self.assertTrue(value["checks"]["numeric_report_checked"])
        self.assertFalse(value["native_execution_attested"])
        self.assertFalse(value["native_leanstral_outputs_qualified"])
        self.assertFalse(value["production_qualified"])
        self.assertFalse(value["proof_authority"])

    def test_four_lane_authored_sequel_preserves_negative_full_session_performance(self):
        self.fixture.sequel()
        value = self.audit()
        self.assertTrue(value["qualified"], value["error"])
        self.assertTrue(value["checks"]["bitwise_full_session_fixture_qualified"])
        self.assertFalse(value["checks"]["bitwise_full_session_speedup_demonstrated"])
        self.assertEqual(value["checks"]["full_session_speedups_v2_cuda_over_bitwise_cuda"], {"1": 0.8, "16": 0.8, "32": 0.8})
        self.assertFalse(value["native_execution_attested"])

    def test_explicit_v2_sequel_uses_separate_profile_and_source(self):
        self.fixture.sequel(version=2)
        value = self.audit()
        self.assertTrue(value["qualified"], value["error"])
        public = json.loads((self.fixture.root / "head-bitwise_cpu-batch1.json").read_bytes())
        self.assertEqual(public["execution_profile"]["profile_id"], module.SESSION_PROFILE)
        self.assertEqual(public["execution_profile"]["session_profile_id"], module.BITWISE_PROFILE_V2)

    def test_primitive_speedup_cannot_promote_slower_complete_session(self):
        self.fixture.sequel()
        self.fixture.report["bitwise_full_session_speedup_demonstrated"] = True
        self.assert_rejected(self.audit())

    def test_complete_session_ratio_cannot_be_replaced_with_guard_ratio(self):
        self.fixture.sequel()
        self.fixture.report["full_session_speedups_v2_cuda_over_bitwise_cuda"]["32"] = 2.0
        self.assert_rejected(self.audit())

    def test_gpu_pair_requires_four_samples_and_each_lane_first_twice(self):
        self.fixture.sequel()
        batches = self.fixture.report["cuda_pair_timing_profile"]["batches"]
        batches["16"]["completed_call_orders"] = [["cuda_batched", "bitwise_cuda_batched"]] * 4
        self.assert_rejected(self.audit())

    def test_bitwise_gpu_timing_three_sample_claim_refuses(self):
        self.fixture.sequel()
        self.fixture.report["lanes"]["bitwise_cuda_batched"]["batches"]["1"].update(self.fixture.timing(0.625, 1))
        self.assert_rejected(self.audit())

    def test_bitwise_cpu_must_retain_inherited_numerical_profile(self):
        self.fixture.sequel()
        self.fixture.report["lanes"]["bitwise_cpu"]["profile"]["profile_id"] = module.BITWISE_PROFILE
        self.assert_rejected(self.audit())

    def test_four_lane_session_requires_complete_pinned_helper_bundle(self):
        self.fixture.sequel()
        self.fixture.report["source_pins"] = [item for item in self.fixture.report["source_pins"] if item["role"] != "qualified_v2_helpers"]
        self.assert_rejected(self.audit())

    def test_same_bit_nonfinite_pair_cannot_claim_refusal_without_real_bits(self):
        self.fixture.sequel()
        self.fixture.report["guard"]["native_equal_nonfinite_pair_refusals"][0]["reference_float32_bits_int32"] = 0
        self.assert_rejected(self.audit())

    def test_equal_nonfinite_pair_all_three_lanes_must_refuse(self):
        self.fixture.sequel()
        self.fixture.report["guard"]["native_equal_nonfinite_pair_refusals"].pop()
        self.assert_rejected(self.audit())

    def test_session_fixture_qualification_is_separate_from_demonstrated_speedup(self):
        self.fixture.sequel()
        self.fixture.report["complete_gpu_session_speedups_qualified"] = False
        self.assert_rejected(self.audit())

    def test_matching_reference_and_private_rows_cannot_claim_admission(self):
        count = 1
        reference = self.fixture.public(count, "cpu", reference=True)
        reference["rows"][0]["admitted"] = True
        self.fixture.report["cpu_reference_results"]["1"] = self.fixture.write("head-cpu-reference-batch1.json", reference)
        self.fixture.report["cpu_reference_decision_projections"]["1"] = self.fixture.write(
            "head-cpu-reference-batch1-canonical-projection.json", module._projection(reference))
        for lane in ("cpu", "cuda_batched"):
            public = self.fixture.public(count, lane)
            public["rows"][0]["admitted"] = True
            batch = self.fixture.report["lanes"][lane]["batches"]["1"]
            batch["result"] = self.fixture.write(f"head-{lane}-batch1.json", public)
            batch["canonical_projection"] = self.fixture.write(f"head-{lane}-batch1-canonical-projection.json", module._projection(public))
            batch["canonical_reference_projection"] = self.fixture.report["cpu_reference_decision_projections"]["1"]
        self.assert_rejected(self.audit())

    def test_authored_decoded_rows_validate_nonempty_copied_facets_without_authority(self):
        self.fixture.decoded_rows()
        value = self.audit()
        self.assertTrue(value["qualified"], value["error"])
        self.assertFalse(value["proof_authority"])
        self.assertFalse(value["native_execution_attested"])

    def test_matching_nested_formal_outputs_cannot_widen_generic_authority(self):
        for name in ("qualified", "admitted", "formalized", "roundtrip_ok", "target_access", "teacher_forcing", "training_executed"):
            with self.subTest(flag=name):
                self.fixture.decoded_rows(forbidden_nested_flag=name)
                self.assert_rejected(self.audit())

    def test_matching_rows_cannot_claim_target_training_or_teacher_access(self):
        for name in ("target_access", "teacher_forcing", "training_executed"):
            with self.subTest(flag=name):
                self.fixture.decoded_rows(forbidden_row_flag=name)
                self.assert_rejected(self.audit())

    def test_original_session_receipt_cannot_claim_reference_cuda_mode(self):
        self.fixture.report["lanes"]["cuda_batched"]["profile"]["owned_tensor_currentness"]["mode"] = "cuda_reference_checks"
        self.assert_rejected(self.audit())

    def test_guard_receipt_schema_and_comparison_must_match_pinned_comparator(self):
        guard = self.fixture.report["guard"]
        original = deepcopy(guard)
        for lane, part, field, changed in (("cuda_reference", None, "mode", "cpu_reference_checks"),
                ("cuda_combined", None, "schema", "owned-tensor-bitwise-value-guard/v1"),
                ("cuda_bitwise_candidate", "implementation", "comparison", "finite-float32-exact-values-and-signed-zero/v1"),
                ("cuda_bitwise_candidate", "implementation", "schema", "owned-tensor-value-guard-implementation/v1")):
            with self.subTest(lane=lane, field=field):
                self.fixture.report["guard"] = deepcopy(original)
                receipt = self.fixture.report["guard"][lane]["receipt"]
                target = receipt if part is None else receipt[part]
                target[field] = changed
                self.assert_rejected(self.audit())

    def test_bitwise_session_receipt_requires_distinct_cuda_mode(self):
        self.fixture.sequel()
        self.fixture.report["lanes"]["bitwise_cuda_batched"]["profile"]["owned_tensor_currentness"]["mode"] = "cuda_single_host_decision"
        self.assert_rejected(self.audit())

    def test_malformed_resource_container_returns_structured_refusal(self):
        self.fixture.report["resources_after"] = []
        value = self.audit()
        self.assert_rejected(value)
        self.assertEqual(value["error"]["type"], "AuditError")

    def test_malformed_nonempty_facet_container_returns_structured_refusal(self):
        self.fixture.decoded_rows(malformed_facets=True)
        value = self.audit()
        self.assert_rejected(value)
        self.assertEqual(value["error"]["type"], "AuditError")

    def test_other_malformed_nested_containers_fail_closed(self):
        originals = deepcopy(self.fixture.report)
        for key, invalid in (("source_pins", {}), ("lanes", []), ("guard", []),
                ("admission", []), ("hardware", []), ("module_import_context_diagnostics", [None])):
            with self.subTest(key=key):
                self.fixture.report = deepcopy(originals)
                self.fixture.report[key] = invalid
                self.assert_rejected(self.audit())

    def test_external_pin_is_required_and_cannot_be_derived_from_report_claim(self):
        value = module.audit(self.fixture.root, expected_result_sha256="0" * 64)
        self.assert_rejected(value)
        with self.assertRaises(TypeError):
            module.audit(self.fixture.root)

    def test_duplicate_json_keys_and_nonfinite_exponent_refuse(self):
        for raw in (b'{"schema":"x","schema":"y"}', b'{"x":NaN}', b'{"x":1e999}'):
            path = self.fixture.root / "result.json"
            path.write_bytes(raw)
            value = module.audit(self.fixture.root, expected_result_sha256=pin(path)["sha256"])
            self.assert_rejected(value)

    def test_failed_empty_report_stays_unqualified_without_requiring_fixture_data(self):
        self.fixture.report.update(architecture_fixture_qualified=False, head_numerical_fixture_qualified=False,
                                   error={"type": "LeaseTimeoutError", "message": "controlled admission refusal"})
        self.fixture.report.pop("checkpoint")
        self.fixture.report.pop("rows")
        value = self.audit()
        self.assertTrue(value["closed_artifacts_consistent"], value["error"])
        self.assertFalse(value["qualified"])
        self.assertFalse(value["checks"]["numeric_report_checked"])

    def test_failed_report_cannot_claim_complete_qualified_fixture(self):
        self.fixture.report["error"] = {"type": "ValueError", "message": "controlled failed forward"}
        self.assert_rejected(self.audit())

    def test_current_source_drift_refuses_but_retained_only_audit_remains_explicit(self):
        self.fixture.paths["head"].write_bytes(b"# changed controlled source")
        self.assert_rejected(self.audit(current=True))
        value = self.audit(current=False)
        self.assertTrue(value["qualified"], value["error"])
        self.assertEqual(value["current_source_pins"], [])

    def test_retained_source_drift_cannot_be_hidden_by_unchanged_source_claim(self):
        path = self.fixture.root / "producers" / ("head-" + self.fixture.paths["head"].name)
        path.write_bytes(b"# changed controlled retained copy")
        self.assert_rejected(self.audit())

    def test_fixed_source_paths_refuse_foreign_byte_identical_sources(self):
        self.fixture.report["source_pins"][0]["current"]["path"] = "/another/qualifier.py"
        self.assert_rejected(self.audit())

    def test_retained_root_and_file_symlinks_are_refused(self):
        result = self.fixture.root / "result.json"
        copy = self.fixture.root / "saved-result.json"
        result.rename(copy)
        result.symlink_to(copy)
        value = module.audit(self.fixture.root, expected_result_sha256=pin(copy)["sha256"])
        self.assert_rejected(value)
        alias = Path(self.temporary.name) / "alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        self.assert_rejected(module.audit(alias, expected_result_sha256=pin(copy)["sha256"]))

    def test_hardlinked_retained_file_refuses_before_parsing(self):
        path = self.fixture.root / "result.json"
        os.link(path, self.fixture.root / "alias.json")
        self.assert_rejected(module.audit(self.fixture.root, expected_result_sha256=pin(path)["sha256"]))

    def test_reader_byte_budget_is_enforced_before_reading_larger_data(self):
        with patch.object(module, "MAX_TOTAL_BYTES", 128):
            self.assert_rejected(self.audit())

    def test_postread_retained_path_replacement_refuses_closure(self):
        reader = module._Reader(self.fixture.root)
        try:
            reader.read("result.json")
            path = self.fixture.root / "result.json"
            path.unlink()
            path.write_bytes(b"{}")
            with self.assertRaises(module.AuditError):
                reader.final_check()
        finally:
            reader.close()

    def test_claimed_logit_error_cannot_replace_recomputed_arrays(self):
        self.fixture.report["lanes"]["cuda_batched"]["batches"]["16"]["four_logit_max_abs_errors"]["end"] = 1e-9
        self.assert_rejected(self.audit())

    def test_changed_saved_logit_value_refuses_even_when_pin_is_updated(self):
        name = "head-cuda_batched-batch16-logits.json"
        value = json.loads((self.fixture.root / name).read_bytes())
        value["presence"][0][0][0] = 0.5
        self.fixture.report["lanes"]["cuda_batched"]["batches"]["16"]["logits"] = self.fixture.write(name, value)
        self.assert_rejected(self.audit())

    def test_logit_error_uses_float32_subtraction_rounding(self):
        reference, actual = self.fixture.logits(1), self.fixture.logits(1)
        left = module._float32(0.1)
        right = module._float32(0.100001)
        reference["modality"][0][0], actual["modality"][0][0] = left, right
        errors = module._logits(reference, actual, 1)
        self.assertEqual(errors["modality"], abs(module._float32(left - right)))

    def test_non_float32_serialized_logits_refuse(self):
        reference = self.fixture.logits(1)
        actual = deepcopy(reference)
        actual["modality"][0][0] = 0.1
        with self.assertRaises(module.AuditError):
            module._logits(reference, actual, 1)

    def test_reported_median_ratio_or_repetition_lies_refuse(self):
        for mutate in (lambda: self.fixture.report["head_warm_speedups_cpu_over_cuda_batched"].update({"32": 100.0}),
                       lambda: self.fixture.report["lanes"]["cpu"]["batches"]["1"].update(median_seconds=100.0),
                       lambda: self.fixture.report["guard"]["cuda_combined"].update(repetitions_per_sample=1)):
            saved = deepcopy(self.fixture.report)
            mutate()
            self.assert_rejected(self.audit())
            self.fixture.report = saved

    def test_cleanup_allocation_and_child_release_lies_refuse(self):
        for mutate in (lambda: self.fixture.report.update(gpu_allocated_after_framework_workspace_clear_bytes=1),
                       lambda: self.fixture.report.update(own_root_lease_released=False),
                       lambda: self.fixture.report["resources_after"].update(active_child_lease_count=1),
                       lambda: self.fixture.report["lanes"]["cuda_batched"].update(own_child_lease_released=False)):
            saved = deepcopy(self.fixture.report)
            mutate()
            self.assert_rejected(self.audit())
            self.fixture.report = saved

    def test_missing_corruption_or_lying_integrity_flags_refuse(self):
        self.fixture.report["guard"]["native_corruption_refusals"].pop()
        self.assert_rejected(self.audit())

    def test_accepted_subnormal_cannot_retain_qualified_guard_aggregate(self):
        item = next(item for item in self.fixture.report["guard"]["native_corruption_refusals"]
                    if item["corruption"] == "smallest_positive_float32_subnormal")
        item.update(refused=False, refusal=None)
        self.assert_rejected(self.audit())

    def test_actual_signed_zero_bits_cannot_be_relabelled_as_positive_zero(self):
        item = next(item for item in self.fixture.report["guard"]["native_corruption_refusals"] if item["corruption"] == "signed_zero")
        item["actual_float32_bits_int32"] = 0
        self.assert_rejected(self.audit())

    def test_guard_host_decision_or_full_tensor_coverage_lies_refuse(self):
        self.fixture.report["guard"]["cuda_combined"]["receipt"]["host_decision_count"] = 8
        self.assert_rejected(self.audit())

    def test_paired_reference_mutation_or_anchor_replacement_refusal_lies_refuse(self):
        self.fixture.report["lanes"]["cuda_batched"]["paired_reference_corruption_refusals"][2]["refused"] = False
        self.assert_rejected(self.audit())

    def test_positive_head_cannot_accept_model_only_subnormal(self):
        self.fixture.report["lanes"]["cuda_batched"]["model_only_subnormal_control"].update(refused=False,
            entry_refused_before_forward=False, refusal=None)
        self.assert_rejected(self.audit())

    def test_checkpoint_anchor_digest_cannot_be_replaced_by_mutable_reference_claim(self):
        self.fixture.report["lanes"]["cuda_batched"]["profile"]["reference_byte_currentness"]["anchor_sha256"] = "0" * 64
        self.assert_rejected(self.audit())

    def test_positive_report_cannot_contain_fit_optimizer_or_encoder_work(self):
        for key in ("encoder_calls", "optimizer_steps", "training_calls", "optimizer_construction_attempts"):
            self.fixture.report[key] = 1
            self.assert_rejected(self.audit())
            self.fixture.report[key] = 0

    def test_precision_restoration_claim_cannot_mask_changed_effective_gru_scope(self):
        self.fixture.report["lanes"]["cuda_batched"]["batches"]["1"]["numeric_scope"]["observations"][0]["gru_precision"]["effective_policy"]["cudnn"]["allow_tf32"] = True
        self.assert_rejected(self.audit())

    def test_projection_cannot_discard_unknown_row_fields_or_token_offsets(self):
        actual = self.fixture.public(1, "cpu")
        expected = module._projection(actual)
        actual["rows"][0]["unknown_decision_field"] = "must be retained"
        self.assertNotEqual(module._projection(actual), expected)
        actual = self.fixture.public(1, "cpu")
        actual["rows"][0]["span_diagnostics"]["tokens"][0]["end"] += 1
        self.assertNotEqual(module._projection(actual), expected)

    def test_projection_preserves_numeric_presence_none_type_and_modality_width(self):
        actual = self.fixture.public(1, "cpu")
        actual["rows"][0]["minimum_decision_logit_margin"] = None
        one = module._projection(actual)
        actual["rows"][0]["minimum_decision_logit_margin"] = 0.1
        self.assertNotEqual(module._projection(actual), one)
        actual["rows"][0]["minimum_decision_logit_margin"] = 1
        with self.assertRaises(module.AuditError):
            module._projection(actual)
        actual["rows"][0].pop("minimum_decision_logit_margin")
        actual["rows"][0]["span_diagnostics"]["modality_logits"] = [0.0, 0.0]
        with self.assertRaises(module.AuditError):
            module._projection(actual)

    def test_updated_projection_pin_cannot_hide_different_public_rows(self):
        name = "head-cuda_batched-batch1-canonical-projection.json"
        value = json.loads((self.fixture.root / name).read_bytes())
        value["rows"][0]["reason"] = "invented replacement"
        self.fixture.report["lanes"]["cuda_batched"]["batches"]["1"]["canonical_projection"] = self.fixture.write(name, value)
        self.assert_rejected(self.audit())

    def test_false_or_production_authority_widening_refuses(self):
        self.fixture.report["production_qualified"] = True
        self.assert_rejected(self.audit())

    def test_no_torch_import_or_retained_python_execution_is_needed(self):
        import builtins
        original = builtins.__import__
        def forbid(name, *args, **kwargs):
            if name == "torch" or name.startswith("torch."):
                raise AssertionError("reader must not import Torch")
            return original(name, *args, **kwargs)
        with patch.object(builtins, "__import__", side_effect=forbid):
            value = self.audit()
        self.assertTrue(value["closed_artifacts_consistent"], value["error"])


if __name__ == "__main__":
    unittest.main()
