"""Synthetic encoder-reader controls; no model, owner or native inference.

Unit vectors and authored timings test byte/protocol checks. Actual producer text
is retained inertly so fixed source integrity can be checked without running it.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).parent
encoder = _load("encoder_closed_reader_controls", HERE / "audit_native_768_encoder.py")
fixture_module = _load("native768_synthetic_archive_fixture", HERE / "test_audit_native_768_device.py")


class EncoderOnlyFixture(fixture_module.SyntheticArchive):
    def __init__(self, root):
        super().__init__(root)
        self.report.update(qualified=False, error={"type": "ValueError", "message": "controlled synthetic head refusal"})
        self.report["encoder_reference"].update(elapsed_seconds=6., repetitions=1, profile_id=encoder.shared.REFERENCE_PROFILE)
        self.report["encoder_warm_speedups_cpu_over_cuda"] = {str(count): 1. for count in (1, 16, 32)}
        self.report["encoder_resident_cpu_speedup_over_single_reload_reference"] = 3.
        for index, expected in enumerate(encoder.ENCODER_SOURCE_PINS, 1):
            path = HERE.parent / expected["path"]
            raw = path.read_bytes()
            assert len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"]
            copy = encoder.ENCODER_COPIES[index-1]
            self.write_raw(copy, raw)
            self.report["source_pins"][index] = {**expected, "path": str(path), "copy": copy}
        def reference(value):
            value.update(implementation={key: pin for key, pin in encoder.IMPLEMENTATION.items() if key != "device_session"},
                model_inference_executed=True, download_executed=False,
                execution_profile={"attention_implementation": "eager", "batch_size": 16, "device": "cpu", "dtype": "float32",
                    "max_tokens_including_special_tokens": 8192, "normalization": "l2", "overlength_policy": "reject",
                    "padding_side": "right", "pooling": "cls"})
        self.mutate_pinned("encoder-reference.json", reference)
        for lane in ("cpu", "cuda"):
            value = self.report["encoder"][lane]
            value["cold_admission_seconds"] = 1.
            profile = value["profile"]
            profile["implementation"] = deepcopy(encoder.IMPLEMENTATION)
            profile["profile_sha256"] = encoder.shared._digest({key: part for key, part in profile.items() if key != "profile_sha256"})
            def resident(actual):
                actual["profile"] = deepcopy(profile)
                for receipt in actual["receipts"]:
                    receipt["profile_sha256"] = profile["profile_sha256"]
            for suffix in ("warmup", "batch1", "batch16", "batch32"):
                self.mutate_pinned(f"encoder-{lane}-{suffix}.json", resident)
        # No head/checkpoint/training or other producer file is available. The
        # encoder audit must succeed without requesting any of those paths.
        for path in root.rglob("*"):
            if path.is_file() and str(path.relative_to(root)) not in encoder.ENCODER_JSON_FILES | set(encoder.ENCODER_COPIES):
                path.unlink()
        self.save_report()


class EncoderClosedReaderControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = EncoderOnlyFixture(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def audit(self):
        return encoder.audit_encoder(self.root, expected_result_sha256=self.fixture.save_report())

    def reject(self):
        result = self.audit()
        self.assertFalse(result["qualified"], result)
        self.assertFalse(result["native_combined_qualified"])
        self.assertFalse(result["encoder_artifacts_consistent"])
        self.assertIsNotNone(result["error"])
        return result

    def test_encoder_subset_passes_while_failed_combined_and_head_stay_unqualified(self):
        result = self.audit()
        self.assertTrue(result["qualified"], result)
        self.assertTrue(result["encoder_artifacts_consistent"])
        self.assertFalse(result["reported_native_combined_qualified"])
        self.assertEqual(len(result["retained_pins"]), len(encoder.ENCODER_JSON_FILES) + 4)
        self.assertEqual(len(result["checks"]["current_source_pins"]), 4)
        self.assertEqual(result["checks"]["warm_speedups_cpu_over_cuda"], {"1": 1., "16": 1., "32": 1.})
        for flag in ("native_combined_qualified", "head_artifacts_checked", "head_qualified", "models_loaded",
                     "native_execution_attested", "resource_enforcement_attested", "process_cleanup_attested",
                     "model_quality_qualified", "proof_authority", "source_semantics_verified", "leanstral4096_qualified"):
            self.assertIs(result[flag], False)

    def test_external_sha_and_missing_encoder_evidence_are_refused(self):
        self.assertFalse(encoder.audit_encoder(self.root, expected_result_sha256="0" * 64)["qualified"])
        self.assertFalse(encoder.audit_encoder(self.root, expected_result_sha256=True)["qualified"])
        (self.root / "encoder-cuda-batch32.json").unlink()
        self.reject()

    def test_encoder_reader_refuses_all_head_or_arbitrary_file_paths(self):
        owned = encoder._EncoderReader(self.root)
        try:
            for path in ("head-native-reference.json", "diagnostic-native768-head.json", "producers/00-qualify_native_768_device.py", "/etc/passwd"):
                with self.subTest(path=path), self.assertRaises(encoder.shared.AuditError):
                    owned.read(path)
        finally:
            owned.close()

    def test_actual_device_and_cuda_flags_are_required_at_every_batch(self):
        for count in (1, 16, 32):
            name = f"encoder-cuda-batch{count}.json"
            original = self.fixture.files[name]
            changes = (lambda x: x["actual_forward_batches"][0].update(output_device="cpu"),
                       lambda x: x.update(cuda_executed=False))
            for change in changes:
                with self.subTest(count=count, change=change):
                    self.fixture.mutate_pinned(name, change)
                    self.reject()
                    self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_cpu_optout_dtype_and_complete_profile_sha_are_required(self):
        name, original = "encoder-cpu-batch1.json", self.fixture.files["encoder-cpu-batch1.json"]
        for change in (lambda x: x["actual_forward_batches"][0].update(output_dtype="torch.float16"),
                       lambda x: x["profile"].update(profile_sha256="0" * 64),
                       lambda x: x.update(cuda_executed=True)):
            with self.subTest(change=change):
                self.fixture.mutate_pinned(name, change)
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_unit_vector_drift_above_numeric_tolerance_refused(self):
        def drift(value):
            vector = value["vectors"][0]
            vector[0], vector[1] = (1.-1e-6)**.5, .001
            value["receipts"][0]["embedding"] = vector
            value["receipts"][0]["embedding_sha256"] = encoder.shared._digest(vector)
        self.fixture.mutate_pinned("encoder-cuda-batch16.json", drift)
        self.reject()

    def test_vector_dimension_normalization_and_boolean_values_refused(self):
        name, original = "encoder-cpu-batch1.json", self.fixture.files["encoder-cpu-batch1.json"]
        for vector in ([1.] + [0.] * 383, [2.] + [0.] * 767, [True] + [0.] * 767):
            with self.subTest(width=len(vector)):
                self.fixture.mutate_pinned(name, lambda x: x["vectors"].__setitem__(0, vector))
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_token_ids_and_independent_receipt_parity_refused_when_changed(self):
        def changed(value):
            value["tokens"][0]["input_ids"][1] += 1
            value["receipts"][0]["token_input_sha256"] = encoder.shared._digest(value["tokens"][0]["input_ids"])
        self.fixture.mutate_pinned("encoder-cpu-batch32.json", changed)
        self.reject()

    def test_source_id_hash_and_truncation_join_are_required(self):
        name, original = "encoder-cuda-batch1.json", self.fixture.files["encoder-cuda-batch1.json"]
        for change in (lambda x: x["receipts"][0].update(id="forged"),
                       lambda x: x["receipts"][0].update(source_sha256="0" * 64),
                       lambda x: x["receipts"][0].update(truncated=True)):
            with self.subTest(change=change):
                self.fixture.mutate_pinned(name, change)
                self.reject()
                self.fixture.mutate_pinned(name, lambda x: x.update(json.loads(original)))

    def test_source_copy_and_report_implementation_must_match_fixed_pins(self):
        path = self.root / encoder.ENCODER_COPIES[0]
        raw = path.read_bytes()
        path.write_bytes(raw + b"# changed\n")
        self.reject()
        path.write_bytes(raw)
        self.fixture.report["encoder"]["cpu"]["profile"]["implementation"]["device_session"] = "0" * 64
        self.reject()

    def test_three_warm_samples_single_reference_and_derived_ratios_required(self):
        for change in (lambda r: r["encoder_warm_speedups_cpu_over_cuda"].update({"32": 10.7}),
                       lambda r: r["encoder_reference"].update(repetitions=3),
                       lambda r: r["encoder"]["cpu"]["batches"]["1"].update(samples_seconds=[1., 2.])):
            with self.subTest(change=change):
                original = deepcopy(self.fixture.report)
                change(self.fixture.report)
                self.reject()
                self.fixture.report = original

    def test_late_current_source_or_retained_artifact_mutation_refused(self):
        original = encoder._current_source
        counts = {}
        def changed(reader, source, expected):
            pin, identity = original(reader, source, expected)
            counts[source] = counts.get(source, 0) + 1
            return pin, (*identity[:-1], identity[-1] + 1) if counts[source] == 2 else identity
        with mock.patch.object(encoder, "_current_source", changed):
            self.reject()
        check = encoder.shared._Reader.final_check
        def mutate(owned):
            path = self.root / "encoder-cpu-batch1.json"
            path.write_bytes(path.read_bytes() + b" ")
            check(owned)
        with mock.patch.object(encoder.shared._Reader, "final_check", mutate):
            self.reject()

    def test_symlink_duplicate_nonfinite_and_unlisted_pin_paths_refused(self):
        path = self.root / "encoder-reference.json"
        raw = path.read_bytes()
        path.unlink()
        path.symlink_to("source-rows.json")
        self.reject()
        path.unlink()
        path.write_bytes(raw)
        self.fixture.report["encoder_reference"]["result"]["path"] = "/etc/passwd"
        self.reject()
        for raw in (b'{"qualified":false,"qualified":false}', b'{"value":NaN}'):
            (self.root / "result.json").write_bytes(raw)
            self.assertFalse(encoder.audit_encoder(self.root, expected_result_sha256=hashlib.sha256(raw).hexdigest())["qualified"])


if __name__ == "__main__":
    unittest.main()
