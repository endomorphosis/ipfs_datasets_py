"""Controlled synthetic archive tests; these confer no native qualification.

Fixtures use authored unit vectors, zero logit tensors and inert producer text.
They exercise the ordinary closed-reader protocol without models or owners.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_PATH = Path(__file__).with_name("audit_native_768_device.py")
_SPEC = importlib.util.spec_from_file_location("native768_closed_reader_controls", _PATH)
reader = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reader)


def _tensor(shape):
    return [_tensor(shape[1:]) for _ in range(shape[0])] if shape else 0.


def _checkpoint(steps, dimension):
    shapes = {"byte_embedding.weight": (257, 4), "token_projection.weight": (8, 13), "token_projection.bias": (8,)}
    for suffix in ("", "_reverse"):
        for name in ("weight_ih_l0", "weight_hh_l0"):
            shapes[f"encoder.{name}{suffix}"] = (24, 8)
        for name in ("bias_ih_l0", "bias_hh_l0"):
            shapes[f"encoder.{name}{suffix}"] = (24,)
    for name, width in (("modality", 3), ("presence", 8), ("start", 6), ("end", 6)):
        shapes[name + ".weight"], shapes[name + ".bias"] = (width, 16), (width,)
    if dimension:
        shapes.update({"latent_down.weight": (4, 768), "latent_down.bias": (4,),
                       "latent_up.weight": (16, 4), "latent_up.bias": (16,)})
    return {"config": {"latent_dimension": dimension, "latent_enabled": bool(dimension), "device": "cpu",
            "hidden_size": 8, "embedding_dim": 4, "projection_width": 4, "batch_size": 2},
            "progress": {"optimizer_steps": steps}, "model_state": {name: _tensor(shape) for name, shape in shapes.items()},
            "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {
                name: {"step": steps, "exp_avg": _tensor(shape), "exp_avg_sq": _tensor(shape)} for name, shape in shapes.items()}},
            "proof_authority": False}


class SyntheticArchive:
    """Every positive here is protocol evidence, never a native run."""
    def __init__(self, root):
        self.root, self.files = root, {}
        texts = ["Lark must retain books.", "Wren may publish records.", "Finch must not destroy files.",
                 *[f"def compare_{i}(a: int, b: int) -> bool:\n    return a < b\n" for i in range(29)]]
        rows = [{"id": f"native768-{i}", "source_text": text} for i, text in enumerate(texts)]
        vectors = [[1., *[0.] * 767] for _ in rows]
        tokens = [{"input_ids": [0, i+4, 2], "attention_mask": [1, 1, 1]} for i in range(32)]
        self.write("source-rows.json", rows)
        baseline = {"schema": "gte-complete-native-embedding-production/v1", "status": "completed",
            "profile_id": reader.REFERENCE_PROFILE, "input_row_count": 32, "receipt_count": 32,
            "training_executed": False, "execution_profile": {"device": "cpu", "dtype": "float32"}, "receipts": []}
        for source, vector, token in zip(rows, vectors, tokens):
            baseline["receipts"].append({"schema": "gte-multilingual-embedding-receipt/v1", "id": source["id"],
                "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(), "dimension": 768,
                "embedding": vector, "profile_id": reader.REFERENCE_PROFILE,
                "asset_manifest_sha256": reader.MANIFEST_SHA256, "normalized": True, "truncated": False,
                "token_count_including_special_tokens": 3, "token_input_sha256": reader._digest(token["input_ids"])})
        report = {"schema": "native768-device-qualification/v1", "qualified": True, "error": None,
            "production_model_quality_qualified": False, "codebase768_scan_qualified": False,
            "leanstral4096_qualified": False, "proof_authority": False, "source_semantics_verified": False,
            "execution_attestation": False, "kernel_resource_enforcement": False,
            "setup_training_calls": 2, "inference_training_calls": 0, "own_root_lease_released": True,
            "gpu_allocated_before_owned_sessions_bytes": 0, "gpu_allocated_after_owned_sessions_closed_bytes": 0,
            "framework_cuda_workspace_clear_supported": True, "gpu_allocated_after_framework_workspace_clear_bytes": 0,
            "gpu_reserved_after_cache_release_bytes": 0, "hardware": {"actual_initial_cuda_kernel": True, "device_index": 0},
            "checkpoint_unchanged": True, "adam_unchanged": True, "head_canonical_decision_parity": True,
            "source_pins": [], "encoder": {}, "head": {}}
        repo = _PATH.parent.parent
        for index, (source, copy) in enumerate(zip(reader.SOURCE_FILES, reader.PRODUCER_COPIES)):
            raw = f"# controlled synthetic source {index}; never executed\n".encode()
            self.write_raw(copy, raw)
            report["source_pins"].append({"path": str(repo / source), "copy": copy,
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        report["encoder_reference"] = {"result": self.write("encoder-reference.json", baseline)}
        cuda_receipts = None
        for lane in ("cpu", "cuda"):
            device = "cpu" if lane == "cpu" else "cuda:0"
            profile = {"schema": "source-embedding-device-768/v1", "dimension": 768,
                "model_id": reader.MODEL_ID, "model_revision": reader.MODEL_REVISION, "code_revision": reader.CODE_REVISION,
                "device": device, "optimized": lane == "cuda", "dtype": "float32", "pooling": "cls", "normalization": "l2",
                "attention_implementation": "eager", "overlength_policy": "reject", "max_tokens_including_special_tokens": 8192,
                "asset_manifest_sha256": reader.MANIFEST_SHA256, "precision": {"controlled_synthetic": True}}
            profile["profile_id"] = (f"{reader.MODEL_ID}@{reader.MODEL_REVISION}:code={reader.CODE_REVISION}:d768:pool=cls:norm=l2:"
                f"{lane}:float32:eager:tokens8192:reject_overlength:precision={reader._digest(profile['precision'])}:device-session-v1")
            profile["profile_sha256"] = reader._digest(profile)
            receipts = [{**deepcopy(receipt), "schema": "gte-native-device-embedding-receipt/v1",
                "profile_id": profile["profile_id"], "profile_sha256": profile["profile_sha256"],
                "embedding_sha256": reader._digest(vector), "device": device, "dtype": "float32",
                "proof_authority": False, "source_semantics_verified": False} for receipt, vector in zip(baseline["receipts"], vectors)]
            value = {"profile": profile, "batches": {}, "reference_max_abs_error": 0., "token_parity_with_reference": True}
            for count in (32, 1, 16, 32):
                warmup = "warmup" not in value
                actual = {"schema": "gte-native-device-embedding-production/v1", "status": "completed",
                    "profile": profile, "profile_id": profile["profile_id"], "input_row_count": count, "receipt_count": count,
                    "receipts": receipts[:count], "vectors": vectors[:count], "tokens": tokens[:count],
                    "cuda_executed": lane == "cuda", "model_inference_executed": True, "training_executed": False,
                    "dense_path_verification": {"bitwise_equal": True, "native_forward_calls": 2,
                        "input_device": device, "output_device": device} if warmup else None,
                    "actual_forward_batches": [{"rows": min(16, count-start), "tokens_per_row": 3,
                        "input_device": device, "output_device": device, "output_dtype": "torch.float32",
                        "output_shape": [min(16, count-start), 3, 768], "native_forward_calls": 1} for start in range(0, count, 16)]}
                pin = self.write(f"encoder-{lane}-warmup.json" if warmup else f"encoder-{lane}-batch{count}.json", actual)
                if warmup:
                    value["warmup"] = pin
                else:
                    value["batches"][str(count)] = {"result": pin, "reference_max_abs_error": 0.,
                        "samples_seconds": [1., 2., 3.], "median_seconds": 2.}
            report["encoder"][lane] = value
            if lane == "cuda":
                cuda_receipts = receipts
        training = [{**rows[i], "latent": vectors[i], "canonical_ir": {"rules": [{"actor": "synthetic", "modality": "O"}]}}
                    for i in range(3)]
        training_pin = self.write("diagnostic-training-index.json", training)
        source_training = [{key: value for key, value in row.items() if key != "latent"} for row in training]
        source_training_pin = self.write("diagnostic-source-training-index.json", source_training)
        parent = _checkpoint(3, 0)
        parent["training_manifest_sha256"] = reader._digest(source_training)
        parent_hash = reader._digest(parent)
        context = {"dimension": 768, "representation_id": report["encoder"]["cuda"]["profile"]["profile_id"],
            "producer_sha256": report["encoder"]["cuda"]["profile"]["profile_sha256"], "training_index_sha256": training_pin["sha256"]}
        child = {**_checkpoint(1, 768), "source_parent_checkpoint": parent, "source_parent_checkpoint_sha256": parent_hash,
            "source_parent_optimizer_steps": 3, "context_contract": context, "context_contract_sha256": reader._digest(context),
            "training_manifest_sha256": reader._digest(training)}
        child_hash = reader._digest(child)
        setup = {"source_parent": self.write("diagnostic-source-parent.json", parent),
            "child": self.write("diagnostic-native768-head.json", child), "context": context,
            "parent_optimizer_steps": 3, "child_optimizer_steps": 1, "production_selected": False,
            "source_training_index": source_training_pin}
        for label, steps, checkpoint_hash in (("parent", 3, parent_hash), ("child", 1, child_hash)):
            fit = {"schema": "span-legal-formula-training/v1" if label == "parent" else "native-dimensional-source-span-training/v1",
                "optimizer_steps": steps, "checkpoint_sha256": checkpoint_hash, "training_executed": True,
                "batch_losses": [1.] * steps, "stopped_reason": "step_limit"}
            if label == "child":
                fit.update(source_parent_checkpoint_sha256=parent_hash, source_parent_optimizer_steps=3, new_optimizer_steps_total=1)
            setup[f"{label}_fit_report"] = self.write(f"diagnostic-{label}-fit-report.json", fit)
        report["head_setup"] = setup
        decisions = [{"source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(), "latent_sha256": reader._digest(vector),
            "status": "abstained", "reason": "controlled_synthetic_abstention", "detail": None, "canonical_ir": None,
            "formula_text": None, "formal_outputs": None, "family_syntax_checked": False, "latent_input_enabled": True}
            for row, vector in zip(rows, vectors)]
        native = {"schema": "native-dimensional-source-span-inference/v1", "checkpoint_sha256": child_hash,
            "input_dimension": 768, "training_executed": False, "model_state_unchanged": True,
            "rows": decisions, "decoded_count": 0, "status": "abstained"}
        report["head_native_reference"] = self.write("head-native-reference.json", native)
        logits = {"modality": _tensor((16, 3)), "presence": _tensor((16, 4, 2)),
                  "start": _tensor((16, 6, 20)), "end": _tensor((16, 6, 20))}
        report["head_native_reference_logits"] = self.write("head-native-reference-logits.json", logits)
        for lane in ("cpu", "cuda", "cuda_batched"):
            device = "cpu" if lane == "cpu" else "cuda:0"
            profile_id = ("native-768-source-span-device-float32/v1" if lane == "cpu" else
                          "native-768-source-span-device-strict-cuda-float32/v2" if lane == "cuda" else
                          "native-768-source-span-batched-device-float32-cpu-decisions/v1")
            ambient = {"cudnn": {"enabled": True, "benchmark": False, "benchmark_limit": 10,
                "deterministic": False, "allow_tf32": True}, "cuda_matmul_allow_tf32": False,
                "float32_matmul_precision": "highest"}
            policy = {"persistent_flags_mutated": False}
            if lane != "cpu":
                policy.update(ambient_at_admission=ambient, cuda_gru_allow_tf32=False, cuda_matmul_allow_tf32=False,
                    float32_matmul_precision="highest", requires_owned_process_without_unrelated_concurrent_cudnn=True)
            profile = {"profile_id": profile_id, "dimension": 768,
                "device": device, "optimized": lane != "cpu", "dtype": "float32", "checkpoint_sha256": child_hash,
                "optimizer_state_sha256": reader._digest(child["optimizer_state"]), "stored_checkpoint_device": "cpu",
                "checkpoint_conversion_performed": False, "inference_only": True, "precision_policy": policy}
            precision = ({"profile_id": "native-768-source-span-device-float32/v1", "scoped_cudnn": False,
                "persistent_flags_mutated": False, "device": "cpu"} if lane == "cpu" else
                {"profile_id": "native-768-source-span-device-strict-cuda-float32/v2", "device": device,
                "scoped_cudnn": True, "ambient_policy": ambient,
                "effective_policy": {**ambient, "cudnn": {**ambient["cudnn"], "allow_tf32": False}},
                "synchronized_before_restore": True, "ambient_flags_restored": True, "persistent_flags_mutated": False,
                "requires_owned_process_without_unrelated_concurrent_cudnn": True})
            if lane == "cuda_batched":
                profile.update(canonical_decision_device="cpu", output_transfer_policy="four_complete_head_tensors_once_per_request",
                    request_local_numerical_cache=True, kernel_resource_enforcement=False)
            value = {"profile": profile, "batches": {}, "checkpoint_unchanged": True, "decisions": decisions,
                "native_logits": self.write(f"head-{lane}-logits.json", logits),
                "native_logit_max_abs_errors": {key: 0. for key in logits}}
            for count in (1, 16, 32):
                actual = {**native, "schema": ("native-768-source-span-batched-device-inference/v1" if lane == "cuda_batched"
                                               else "native-768-source-span-device-inference/v1"), "rows": decisions[:count],
                    "source_parent_checkpoint_sha256": parent_hash, "context_contract_sha256": reader._digest(context),
                    "cuda_executed": lane != "cpu", "target_access": False, "teacher_forcing": False, "latent_ablation": "none",
                    "execution_profile": profile, "input_receipts": {"status": "externally_content_pinned",
                        "native_encoder_inputs_authenticated": True, "receipt_sha256s": [reader._digest(x) for x in cuda_receipts[:count]],
                        "context_producer_sha256": context["producer_sha256"],
                        "profile_sha256s": [x["profile_sha256"] for x in cuda_receipts[:count]],
                        "signature_verified": False, "semantic_qualification": False},
                    "actual_forward_batches": [{"rows": 1, "source_tokens": [len(reader.re.findall(r"\w+|[^\w\s]", row["source_text"]))],
                        "input_device": device, "native_input_dimension": 768, "output_dtype": "float32", "gru_executed": True,
                        "output_devices": {key: device for key in logits}, "gru_precision": precision} for row in rows[:count]]}
                if lane == "cuda_batched":
                    actual["actual_forward_batches"] = [{**actual["actual_forward_batches"][0], "rows": count,
                        "source_tokens": [len(reader.re.findall(r"\w+|[^\w\s]", row["source_text"])) for row in rows[:count]]}]
                    actual.update(numerical_batching=True, valid_source_count=count, cpu_head_output_materializations=4,
                        device_to_cpu_head_transfers=4, canonical_decision_device="cpu")
                value["batches"][str(count)] = {"result": self.write(f"head-{lane}-batch{count}.json", actual),
                    "samples_seconds": [1., 2., 3.], "median_seconds": 2.}
            report["head"][lane] = value
        self.report = report
        self.save_report()

    def write_raw(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.files[name] = raw
        return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def write(self, name, value):
        return self.write_raw(name, reader._wire(value))

    def save_report(self):
        return self.write("result.json", self.report)["sha256"]

    def mutate_pinned(self, name, mutate):
        value = json.loads(self.files[name])
        mutate(value)
        pin = self.write(name, value)
        def replace(part):
            if type(part) is dict:
                if set(part) == {"path", "bytes", "sha256"} and part["path"] == str(self.root / name):
                    part.update(pin)
                else:
                    for child in part.values():
                        replace(child)
            elif type(part) is list:
                for child in part:
                    replace(child)
        replace(self.report)
        return self.save_report()


class ClosedReaderControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = SyntheticArchive(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def audit(self):
        return reader.audit(self.root, expected_result_sha256=self.fixture.save_report())

    def reject(self):
        actual = self.audit()
        self.assertFalse(actual["qualified"], actual)
        self.assertFalse(actual["closed_artifacts_consistent"])
        self.assertIsNotNone(actual["error"])
        return actual

    def test_controlled_protocol_accepts_without_native_or_proof_authority(self):
        actual = self.audit()
        self.assertTrue(actual["qualified"], actual)
        self.assertEqual(actual["checks"]["encoder_batches"], [1, 16, 32])
        self.assertEqual(actual["checks"]["head_batches"], [1, 16, 32])
        self.assertEqual(len(actual["retained_pins"]), len(reader.FIXED_JSON_FILES) - 1 + 12)
        for flag in ("native_execution_attested", "resource_enforcement_attested", "model_quality_qualified",
                     "proof_authority", "source_semantics_verified", "leanstral4096_qualified"):
            self.assertIs(actual[flag], False)

    def test_external_result_hash_required(self):
        for pin in (None, True, "F" * 64, "0" * 64):
            with self.subTest(pin=pin):
                self.assertFalse(reader.audit(self.root, expected_result_sha256=pin)["qualified"])

    def test_failed_native_preserves_error_without_positive_files(self):
        self.fixture.report = {"schema": "native768-device-qualification/v1", "qualified": False,
            "error": {"type": "ValueError", "message": "head logit parity exceeds5e-5"},
            "cuda_cleanup_error": {"message": "retained GPU workspace"}}
        (self.root / "encoder-reference.json").unlink()
        actual = self.reject()
        self.assertEqual(actual["native_report_error"]["message"], "head logit parity exceeds5e-5")
        self.assertEqual(len(actual["retained_pins"]), 1)

    def test_forged_encoder_device_is_rejected_at_each_batch(self):
        for count in (1, 16, 32):
            with self.subTest(count=count):
                name = f"encoder-cuda-batch{count}.json"
                original = self.fixture.files[name]
                self.fixture.mutate_pinned(name, lambda x: x["actual_forward_batches"][0].update(input_device="cpu"))
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_forged_head_device_dtype_and_cuda_flag_are_rejected(self):
        name = "head-cuda-batch16.json"
        original = self.fixture.files[name]
        changes = [lambda x: x.update(cuda_executed=False),
                   lambda x: x["actual_forward_batches"][0].update(output_dtype="float16"),
                   lambda x: x["actual_forward_batches"][0]["output_devices"].update(modality="cpu")]
        for change in changes:
            with self.subTest(change=change):
                self.fixture.mutate_pinned(name, change)
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_unit_vector_numeric_drift_cannot_hide_behind_self_report(self):
        def change(value):
            vector = value["vectors"][0]
            vector[0], vector[1] = (1. - 1e-6) ** .5, .001
            value["receipts"][0]["embedding"] = vector
            value["receipts"][0]["embedding_sha256"] = reader._digest(vector)
        self.fixture.mutate_pinned("encoder-cuda-batch1.json", change)
        self.reject()

    def test_padded_wrong_dimension_and_nonunit_vectors_are_rejected(self):
        name, original = "encoder-cpu-batch1.json", self.fixture.files["encoder-cpu-batch1.json"]
        for vector in ([1.] + [0.] * 383, [2.] + [0.] * 767, [True] + [0.] * 767):
            with self.subTest(width=len(vector)):
                self.fixture.mutate_pinned(name, lambda x: x["vectors"].__setitem__(0, vector))
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_retained_token_input_and_reference_hash_must_both_match(self):
        def change(value):
            value["tokens"][0]["input_ids"][1] += 1
            value["receipts"][0]["token_input_sha256"] = reader._digest(value["tokens"][0]["input_ids"])
        self.fixture.mutate_pinned("encoder-cpu-batch16.json", change)
        self.reject()

    def test_truncated_receipt_and_source_join_are_rejected(self):
        name, original = "encoder-cuda-batch32.json", self.fixture.files["encoder-cuda-batch32.json"]
        for change in (lambda x: x["receipts"][0].update(truncated=True),
                       lambda x: x["receipts"][0].update(source_sha256="0" * 64),
                       lambda x: x["receipts"][1].update(id=x["receipts"][0]["id"])):
            with self.subTest(change=change):
                self.fixture.mutate_pinned(name, change)
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_canonical_decision_drift_from_native_reference_rejected_all_batches(self):
        for count in (1, 16, 32):
            with self.subTest(count=count):
                name, original = f"head-cpu-batch{count}.json", self.fixture.files[f"head-cpu-batch{count}.json"]
                self.fixture.mutate_pinned(name, lambda x: x["rows"][0].update(canonical_ir={"rules": [{"actor": "forged"}]}))
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_identical_cpu_cuda_head_bug_still_fails_native_reference(self):
        for lane in ("cpu", "cuda"):
            self.fixture.mutate_pinned(f"head-{lane}-batch32.json", lambda x: x["rows"][0].update(reason="same forged decision"))
        self.reject()

    def test_numeric_head_logits_must_match_unchanged_native_reference(self):
        self.fixture.mutate_pinned("head-cuda-logits.json", lambda x: x["modality"][0].__setitem__(0, .001))
        self.fixture.report["head"]["cuda"]["native_logit_max_abs_errors"]["modality"] = .001
        self.reject()

    def test_head_encoder_content_pins_are_recomputed(self):
        self.fixture.mutate_pinned("head-cuda-batch1.json", lambda x: x["input_receipts"]["receipt_sha256s"].__setitem__(0, "0" * 64))
        self.reject()

    def test_setup_actual_step_reports_and_counts_are_required(self):
        for key, value in (("setup_training_calls", 1), ("inference_training_calls", 1), ("inference_training_calls", False)):
            with self.subTest(key=key, value=value):
                previous = self.fixture.report[key]
                self.fixture.report[key] = value
                self.reject()
                self.fixture.report[key] = previous
        self.fixture.mutate_pinned("diagnostic-parent-fit-report.json", lambda x: x.update(optimizer_steps=2))
        self.reject()

    def test_head_real_768_weight_shape_and_complete_adam_are_required(self):
        self.fixture.mutate_pinned("diagnostic-native768-head.json", lambda x: x["model_state"]["latent_down.weight"].__setitem__(0, [0.] * 8))
        self.reject()

    def test_cleanup_release_allocation_and_errors_are_required(self):
        for key, value in (("own_root_lease_released", False), ("gpu_allocated_after_framework_workspace_clear_bytes", 1),
                           ("cuda_cleanup_error", {"message": "synchronize failed"})):
            with self.subTest(key=key):
                exists, previous = key in self.fixture.report, self.fixture.report.get(key)
                self.fixture.report[key] = value
                self.reject()
                if exists:
                    self.fixture.report[key] = previous
                else:
                    del self.fixture.report[key]

    def test_retained_source_copy_must_match_exact_source_pin(self):
        path = self.root / reader.PRODUCER_COPIES[0]
        path.write_bytes(path.read_bytes() + b"# mutation\n")
        self.reject()

    def test_reported_framework_workspace_can_be_cleared_to_baseline(self):
        self.fixture.report["gpu_allocated_after_owned_sessions_closed_bytes"] = 32 * 1024**2
        actual = self.audit()
        self.assertTrue(actual["qualified"], actual)
        self.assertEqual(actual["checks"]["reported_postclose_gpu_allocated_bytes"], 32 * 1024**2)
        self.fixture.report["framework_cuda_workspace_clear_supported"] = False
        self.reject()

    def test_inherited_setup_has_zero_current_fits_and_exact_retained_reports(self):
        inherited = deepcopy(self.fixture.report)
        inherited["qualified"] = False
        inherited["error"] = {"message": "prior CUDA parity refused"}
        pin = self.fixture.write("inherited-head-source-result.json", inherited)
        self.fixture.report.update(setup_training_calls=0, inherited_setup_training_calls=2, inherited_head_source_result=pin)
        actual = self.audit()
        self.assertTrue(actual["qualified"], actual)
        self.assertEqual(actual["checks"]["reported_current_setup_fits"], 0)
        self.assertEqual(actual["checks"]["reported_inherited_setup_fits"], 2)
        self.fixture.mutate_pinned("inherited-head-source-result.json", lambda x: x["head_setup"]["child"].update(sha256="0" * 64))
        self.reject()

    def test_batched_forward_transfer_coverage_and_precision_are_required(self):
        name = "head-cuda_batched-batch16.json"
        original = self.fixture.files[name]
        changes = [lambda x: x.update(device_to_cpu_head_transfers=16),
                   lambda x: x.update(canonical_decision_device="cuda:0"),
                   lambda x: x["actual_forward_batches"][0].update(rows=1),
                   lambda x: x["actual_forward_batches"][0]["gru_precision"].update(ambient_flags_restored=False),
                   lambda x: x["actual_forward_batches"][0]["gru_precision"]["effective_policy"]["cudnn"].update(allow_tf32=True)]
        for change in changes:
            with self.subTest(change=change):
                self.fixture.mutate_pinned(name, change)
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_optional_current_sources_read_only_fixed_paths(self):
        actual = reader.audit(self.root, expected_result_sha256=self.fixture.save_report(), check_current_sources=True)
        self.assertFalse(actual["qualified"])
        self.assertIn("current producer", actual["error"]["message"])

    def test_arbitrary_report_paths_are_never_opened(self):
        self.fixture.report["encoder_reference"]["result"]["path"] = "/etc/passwd"
        actual = self.reject()
        self.assertIn("fixed path", actual["error"]["message"])
        self.fixture.report["source_pins"][0]["copy"] = "../../etc/passwd"
        self.reject()

    def test_symlink_file_directory_root_and_hardlink_refused(self):
        name = "encoder-reference.json"
        raw = self.fixture.files[name]
        path = self.root / name
        path.unlink()
        path.symlink_to("source-rows.json")
        self.reject()
        path.unlink()
        path.write_bytes(raw)
        alias = self.root / "alias.json"
        os.link(path, alias)
        self.reject()
        alias.unlink()
        actual = reader.audit(self.root / "producers" / "..", expected_result_sha256=self.fixture.save_report())
        self.assertFalse(actual["qualified"])
        moved = self.root / "producer-files"
        (self.root / "producers").rename(moved)
        (self.root / "producers").symlink_to(moved, target_is_directory=True)
        self.reject()

    def test_duplicate_nonfinite_json_and_file_byte_bound_refused(self):
        path, raw = self.root / "result.json", self.fixture.files["result.json"]
        for bad in (b'{"qualified":true,"qualified":true}', b'{"number":NaN}', b'{"number":1e9999}'):
            with self.subTest(raw=bad):
                path.write_bytes(bad)
                actual = reader.audit(self.root, expected_result_sha256=hashlib.sha256(bad).hexdigest())
                self.assertFalse(actual["qualified"])
        path.write_bytes(raw)
        with mock.patch.object(reader, "MAX_FILE_BYTES", 4):
            actual = reader.audit(self.root, expected_result_sha256=hashlib.sha256(raw).hexdigest())
            self.assertFalse(actual["qualified"])

    def test_late_retained_mutation_and_missing_file_refused(self):
        original = reader._Reader.final_check
        def mutate(owned):
            path = self.root / "encoder-cpu-batch1.json"
            path.write_bytes(path.read_bytes() + b" ")
            original(owned)
        with mock.patch.object(reader._Reader, "final_check", mutate):
            self.reject()
        self.fixture.write_raw("encoder-cpu-batch1.json", self.fixture.files["encoder-cpu-batch1.json"])
        (self.root / "head-cuda-batch16.json").unlink()
        self.reject()

    def test_proof_or_4096_authority_widening_rejected(self):
        self.fixture.report["leanstral4096_qualified"] = True
        self.reject()
        self.fixture.report["leanstral4096_qualified"] = False
        self.fixture.mutate_pinned("head-cpu-batch1.json", lambda x: x.update(proof_authority=True))
        self.reject()


if __name__ == "__main__":
    unittest.main()
