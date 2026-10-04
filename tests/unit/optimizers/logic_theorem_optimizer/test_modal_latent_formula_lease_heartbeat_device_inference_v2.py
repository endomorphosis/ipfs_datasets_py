"""No-fit successor controls observing the actual formula project return.

The frozen first suite is preserved. The paired helper substitution control
uses an exact model-project code observation for both public APIs; inference
forward counters are not assumed to exist for the project-only path.

Authored native checkpoints have zero training/Adam steps. These controls run
real CPU model projections, preserve source/lineage bindings, and exercise
ownership refusals. CUDA availability mocks test selection only and never
qualify CUDA execution, performance, trained semantics or proof authority.
"""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import threading
import time

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_inference as batched
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_device_inference as inherited
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_lease_heartbeat_device_inference as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_bitwise_device_inference as qualified_v1
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_bitwise_device_inference_v2 as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authenticated_lease_heartbeat as heartbeat
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_bitwise_guard as bitwise_guard
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import checkpoint_content_guard as checkpoint_guard
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


@pytest.fixture(scope="module", autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module", params=[8, 384])
def authored_checkpoint(request):
    dimension = request.param
    rows = [{"id": "authored-zero-fit", "source_text": "The agency must disclose café records.",
        "latent": [.5] + [0.] * (dimension - 1), "embedding": [.3] + [0.] * (dimension - 1),
        "canonical_ir": {"rules": [{"actor": "agency", "modality": "O", "action": "disclose", "object": "records",
                                   "conditions": [], "exceptions": [], "temporal": []}]}}]
    binding = {"domain": "legal_ir", "lineage_id": "legacy_hub_v1" if dimension == 8 else "current_legal_v2",
               "dimension": dimension, "runtime_profile": "authored-bitwise-formula-zero-fit/v1", "core_sha256": "a" * 64}
    checkpoint = native.build_checkpoint(binding, rows, [], hidden_size=8, token_embedding_dim=8,
                                          projection_width=2, batch_size=1, seed=1729)
    assert checkpoint["progress"]["optimizer_steps"] == 0
    assert checkpoint["optimizer_state"]["parameters"] == {}
    return checkpoint


@pytest.fixture
def scheduler(tmp_path):
    return GlobalResourceScheduler(ResourceSchedulerConfig(state_path=tmp_path / "resources.json",
        total_cpu_slots=2, total_memory_mb=4096, total_gpu_memory_mb=1024, total_unified_memory_mb=4096,
        lane_reservations={}, auto_renew_leases=False,
        resource_pressure_sampler=lambda: {"gpu_telemetry_available": True, "cuda_available": False,
            "gpu_device_count": 0, "gpu_memory_percent": 0.}))


def inputs(checkpoint, count=1):
    dimension = checkpoint["binding"]["dimension"]
    return [{"id": "infer-" + str(index), "source_text": "The agency must disclose café records.",
             "latent": [.5] + [0.] * (dimension - 1)} for index in range(count)]


def open_cpu(checkpoint, scheduler, **options):
    return subject.BitwiseDeviceLatentFormulaDecoder(checkpoint,
        expected_checkpoint_sha256=native.checkpoint_digest(checkpoint), optimized=False,
        scheduler=scheduler, **options)


@pytest.mark.parametrize("count", [1, 16, 17, 32])
def test_cpu_opt_out_preserves_original_projection_decisions_and_native_checkpoint(authored_checkpoint, scheduler, count):
    checkpoint = authored_checkpoint
    before, rng = native._raw(checkpoint), torch.get_rng_state().clone()
    rows = inputs(checkpoint, count)
    with open_cpu(checkpoint, scheduler) as decoder:
        actual, vectors = decoder.infer_with_projection(rows)
        expected, expected_vectors = inherited.DeviceLatentFormulaDecoder(checkpoint, optimized=False).infer_with_projection(rows)
        assert actual["rows"] == expected["rows"]
        assert actual["binding"] == checkpoint["binding"]
        assert actual["schema"] == expected["schema"] == subject.SCHEMA
        assert vectors == expected_vectors and all(len(vector) == checkpoint["binding"]["dimension"] for vector in vectors)
        assert actual["checkpoint_sha256"] == native.checkpoint_digest(checkpoint)
        profile = actual["inference_implementation"]
        assert profile["profile_id"] == subject.PROFILE and profile["device"] == "cpu"
        assert profile["dimension"] == checkpoint["binding"]["dimension"]
        assert profile["lineage_id"] == checkpoint["binding"]["lineage_id"]
        assert profile["execution"] == ("scalar" if count <= 16 else "batched")
        assert profile["actual_forward_calls"] == expected["inference_implementation"]["actual_forward_calls"]
        assert profile["actual_forward_executed"] and not profile["cuda_executed"]
        assert profile["owned_tensor_currentness"]["schema"] == bitwise_guard.SCHEMA
        assert profile["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert profile["cpu_model_byte_currentness_checked"]
        assert profile["adam_restoration_performed"] and profile["adam_restore_count"] == 1
        assert profile["optimizer_steps_executed"] == 0 and profile["training_executed"] is False
        anchor = profile["reference_byte_currentness"]
        assert anchor["origin"] == "validated_cpu_checkpoint_model_before_reference_clone_and_upload"
        assert anchor["independent_of_mutable_reference_storage"]
        assert anchor["anchor_sha256"] == hashlib.sha256(decoder._reference_anchor.payload).hexdigest()
        assert anchor["reference_bytes"] == sum(value.numel() * 4 for value in decoder.model.state_dict().values())
        assert anchor["device_to_cpu_reference_transfers"] == 0
        assert decoder.checkpoint == checkpoint and not any(module._forward_hooks for module in decoder.model.modules())
        assert all(actual[name] is False for name in native.FALSE)
        assert not profile["native_cuda_qualified"] and not profile["performance_qualified"] and not profile["proof_authority"]
    assert scheduler.active_leases() == [] and native._raw(checkpoint) == before and torch.equal(rng, torch.get_rng_state())


def test_default_optimization_uses_available_policy_with_explicit_cpu_fallback_only(authored_checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with subject.BitwiseDeviceLatentFormulaDecoder(authored_checkpoint,
            expected_checkpoint_sha256=native.checkpoint_digest(authored_checkpoint), scheduler=scheduler) as decoder:
        profile = decoder.describe()
        assert profile["optimized"] is True and profile["device"] == "cpu"
        assert profile["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert not profile["cuda_selected"] and not profile["native_cuda_qualified"]


def test_cpu_opt_out_never_queries_device_selection(authored_checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU opt-out queried CUDA selection")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        assert decoder.project([inputs(authored_checkpoint)[0]["latent"]])


def test_inference_validates_adam_without_any_optimizer_step_or_training(authored_checkpoint, scheduler, monkeypatch):
    before = native._raw(authored_checkpoint)
    def forbidden(*args, **kwargs):
        raise AssertionError("inference executed an optimizer step")
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        report, _ = decoder.infer_with_projection(inputs(authored_checkpoint, 17))
        assert not report["training_executed"]
        assert decoder._checkpoint["optimizer_state"] == authored_checkpoint["optimizer_state"]
    assert native._raw(authored_checkpoint) == before


@pytest.mark.parametrize("mutation", ["finite", "signed_zero", "subnormal", "nan", "inf"])
@pytest.mark.parametrize("owner", ["model", "reference", "paired"])
def test_all_value_and_independent_reference_anchor_refusals(authored_checkpoint, scheduler, mutation, owner):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        parameter = decoder.model.target_embedding.weight
        reference = decoder._reference_weights["target_embedding.weight"]
        current, retained = parameter.detach().clone(), reference.clone()
        assert parameter[0, 0].item() == reference[0, 0].item() == 0.0
        try:
            bits = {"finite": 1065353216, "signed_zero": -2147483648, "subnormal": 1,
                    "nan": 2143289344, "inf": 2139095040}[mutation]
            if owner in ("model", "paired"):
                parameter.data.view(torch.int32)[0, 0] = bits
            if owner in ("reference", "paired"):
                reference.data.view(torch.int32)[0, 0] = bits
            with pytest.raises(ValueError, match="bytes changed|finite profile changed"):
                decoder.infer(inputs(authored_checkpoint))
            assert not decoder._active and not any(module._forward_hooks for module in decoder.model.modules())
        finally:
            parameter.data.copy_(current)
            reference.data.copy_(retained)


@pytest.mark.parametrize("fault", ["anchor_object", "payload", "reference_object", "model_storage", "buffer", "noncontiguous", "double", "training", "gradient", "foreign_hook", "factory", "checkpoint", "lease"])
def test_metadata_modes_and_ownership_refuse_before_forward(authored_checkpoint, scheduler, fault):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        saved_anchor = decoder._reference_anchor
        saved_payload = decoder._reference_payload_identity
        saved_reference = decoder._reference_weights
        parameter = decoder.model.target_embedding.weight
        original_data = parameter.data
        reference = decoder._reference_weights["target_embedding.weight"]
        original_reference_data = reference.data
        original_checkpoint = deepcopy(decoder._checkpoint)
        memory = decoder._lease.memory_mb
        factory = decoder.torch
        handle = None
        try:
            if fault == "anchor_object":
                decoder._reference_anchor = replace(saved_anchor)
            elif fault == "payload":
                decoder._reference_payload_identity = bytes(bytearray(saved_payload))
            elif fault == "reference_object":
                decoder._reference_weights = dict(saved_reference)
            elif fault == "model_storage":
                parameter.data = parameter.detach().clone()
            elif fault == "buffer":
                decoder.model.register_buffer("nonfloat_control", torch.tensor([1], dtype=torch.int64))
            elif fault == "noncontiguous":
                reference.data = reference.T
            elif fault == "double":
                reference.data = reference.double()
            elif fault == "training":
                decoder.model.train()
            elif fault == "gradient":
                parameter.grad = torch.zeros_like(parameter)
            elif fault == "foreign_hook":
                handle = decoder.model.projection_down.register_forward_hook(lambda *_: None)
            elif fault == "factory":
                decoder.torch = torch
            elif fault == "checkpoint":
                decoder._checkpoint["progress"]["optimizer_steps"] += 1
            else:
                decoder._lease.memory_mb += 1
            with pytest.raises(ValueError):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert not decoder._active
        finally:
            decoder._reference_anchor, decoder._reference_payload_identity = saved_anchor, saved_payload
            decoder._reference_weights = saved_reference
            parameter.data, reference.data = original_data, original_reference_data
            if "nonfloat_control" in decoder.model._buffers:
                del decoder.model._buffers["nonfloat_control"]
            decoder.model.eval()
            parameter.grad = None
            decoder.torch, decoder._lease.memory_mb = factory, memory
            decoder._checkpoint.clear()
            decoder._checkpoint.update(original_checkpoint)
            decoder._codec = decoder._checkpoint["codec"]
            if handle is not None:
                handle.remove()


@pytest.mark.parametrize("fault", ["original_class", "original_check", "batched_decode", "restore", "guard", "codec", "factory_class", "own_source", "own_implementation", "own_validator", "checkpoint_comparator", "lease_cancel"])
def test_original_class_function_method_and_comparator_bindings_stay_live(authored_checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        if fault == "original_class":
            monkeypatch.setattr(inherited, "DeviceLatentFormulaDecoder", object)
        elif fault == "original_check":
            monkeypatch.setattr(inherited.DeviceLatentFormulaDecoder, "_check", lambda self: {})
        elif fault == "batched_decode":
            monkeypatch.setattr(batched.BatchedLatentFormulaDecoder, "_decode_scalar", lambda *_: {})
        elif fault == "restore":
            monkeypatch.setattr(native, "_restore", lambda *_: None)
        elif fault == "guard":
            monkeypatch.setattr(bitwise_guard, "check_owned_tensor_bytes", lambda *_: {})
        elif fault == "codec":
            monkeypatch.setattr(native.codec_module, "decode_target", lambda *_: {})
        elif fault == "factory_class":
            monkeypatch.setattr(inherited, "_DeviceTorch", object)
        elif fault == "own_source":
            monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
        elif fault == "own_implementation":
            monkeypatch.setattr(subject, "inference_implementation", lambda: {})
        elif fault == "own_validator":
            monkeypatch.setattr(subject, "_strict_json", lambda *_: None)
        elif fault == "checkpoint_comparator":
            monkeypatch.setattr(checkpoint_guard, "_matches", lambda *_: True)
        else:
            monkeypatch.setattr(GlobalResourceScheduler, "is_cancelled", lambda *_args, **_kwargs: False)
        with pytest.raises(ValueError, match="changed"):
            decoder.infer(inputs(authored_checkpoint))


@pytest.mark.parametrize("mutation", ["finite", "signed_zero", "input"])
def test_exit_checks_refuse_mutations_after_real_projection(authored_checkpoint, scheduler, mutation):
    rows = inputs(authored_checkpoint)
    class MutatingCancellation:
        decoder, changed = None, False
        def is_set(self):
            decoder = self.decoder
            if decoder is not None and decoder._active_observer is not None and sum(decoder._active_observer.values()) and not self.changed:
                if mutation == "input":
                    rows[0]["latent"][0] = .75
                else:
                    bits = 1065353216 if mutation == "finite" else -2147483648
                    decoder.model.target_embedding.weight.data.view(torch.int32)[0, 0] = bits
                    decoder._reference_weights["target_embedding.weight"].data.view(torch.int32)[0, 0] = bits
                self.changed = True
            return False
    cancellation = MutatingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        current = decoder.model.target_embedding.weight.detach().clone()
        retained = decoder._reference_weights["target_embedding.weight"].clone()
        try:
            with pytest.raises(ValueError):
                decoder.infer_with_projection(rows)
            assert cancellation.changed and not decoder._active
            assert not any(module._forward_hooks for module in decoder.model.modules())
        finally:
            decoder.model.target_embedding.weight.data.copy_(current)
            decoder._reference_weights["target_embedding.weight"].data.copy_(retained)


def test_parent_admission_and_own_close_never_force_release_parent(authored_checkpoint, scheduler):
    with scheduler.acquire("snapshot_evaluation", cpu_slots=2, memory_mb=2048) as parent:
        decoder = open_cpu(authored_checkpoint, scheduler, parent_lease=parent)
        assert decoder.describe()["resource_lease"]["parent_lease_id"] == parent.lease_id
        decoder.close()
        decoder.close()
        assert decoder._lease.released and not parent.released
        assert len(scheduler.active_leases()) == 1
        with pytest.raises(ValueError, match="closed"):
            decoder.infer(inputs(authored_checkpoint))
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("cancel_source", ["external", "lease", "deadline"])
def test_cancel_and_deadline_boundaries_leave_close_available(authored_checkpoint, scheduler, cancel_source):
    external = threading.Event()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=external) as decoder:
        if cancel_source == "external":
            external.set()
        elif cancel_source == "lease":
            decoder._lease.cancel()
        else:
            decoder._deadline = time.monotonic() - 1
        with pytest.raises((TimeoutError, ValueError)):
            decoder.infer(inputs(authored_checkpoint))
        assert not decoder._active
    assert scheduler.active_leases() == []


def test_cancelled_constructor_creates_no_model_or_lease(authored_checkpoint, scheduler):
    external = threading.Event()
    external.set()
    with pytest.raises(TimeoutError, match="cancelled"):
        open_cpu(authored_checkpoint, scheduler, cancel_event=external)
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("dimension", [0, 8, 384, 768, 4096, True])
def test_crosswidth_or_changed_binding_is_never_averaged_or_admitted(authored_checkpoint, scheduler, dimension):
    changed = deepcopy(authored_checkpoint)
    changed["binding"]["dimension"] = dimension
    if dimension == authored_checkpoint["binding"]["dimension"]:
        changed["binding"]["lineage_id"] = "current_legal_v2" if dimension == 8 else "legacy_hub_v1"
    with pytest.raises(ValueError, match="lineage"):
        open_cpu(changed, scheduler)
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_default_optimization_flag_requires_plain_boolean(value, scheduler):
    with pytest.raises(ValueError, match="boolean"):
        subject.BitwiseDeviceLatentFormulaDecoder({}, expected_checkpoint_sha256="a" * 64, optimized=value, scheduler=scheduler)


def test_external_checkpoint_pin_is_required_and_checked_before_admission(authored_checkpoint, scheduler):
    with pytest.raises(TypeError):
        subject.BitwiseDeviceLatentFormulaDecoder(authored_checkpoint, optimized=False, scheduler=scheduler)
    with pytest.raises(ValueError):
        subject.BitwiseDeviceLatentFormulaDecoder(authored_checkpoint, expected_checkpoint_sha256="b" * 64, optimized=False, scheduler=scheduler)
    assert scheduler.active_leases() == []


def test_wrong_expected_binding_refuses_and_closes_owned_admission(authored_checkpoint, scheduler):
    wrong = {**authored_checkpoint["binding"], "core_sha256": "b" * 64}
    with pytest.raises(ValueError, match="binding differs"):
        open_cpu(authored_checkpoint, scheduler, expected_binding=wrong)
    assert scheduler.active_leases() == []


def test_targets_unicode_and_wrong_latent_width_retain_original_input_protocol(authored_checkpoint, scheduler):
    rows = inputs(authored_checkpoint)
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        result = decoder.infer(rows)
        assert result["rows"][0]["source_sha256"] == hashlib.sha256(rows[0]["source_text"].encode()).hexdigest()
        with pytest.raises(ValueError, match="closed latent row"):
            decoder.infer([{**rows[0], "canonical_ir": {"rules": []}}])
        with pytest.raises(ValueError, match="width"):
            decoder.infer([{**rows[0], "latent": rows[0]["latent"][:-1]}])
        with pytest.raises(ValueError, match="inference rows"):
            decoder.infer(rows * 129)


def test_unsupported_projection_reports_selection_without_any_model_forward(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        report = decoder.infer(inputs(authored_checkpoint), projection_id="unsupported_formula_projection")
        profile = report["inference_implementation"]
        assert profile["actual_forward_executed"] is False and profile["cuda_executed"] is False
        assert sum(profile["actual_forward_calls"].values()) == 0
        assert not any(module._forward_hooks for module in decoder.model.modules())


def test_numerical_method_replacement_refuses_without_silent_device_fallback(authored_checkpoint, scheduler, monkeypatch):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        def broken(*args, **kwargs):
            raise RuntimeError("private replacement must never run")
        monkeypatch.setattr(decoder.model, "project", broken)
        with pytest.raises(ValueError, match="model method changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert decoder._device == "cpu"


def test_model_only_subnormal_still_refuses_under_cpu_flush_to_zero(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        parameter = decoder.model.target_embedding.weight
        original = parameter.detach().clone()
        probe = torch.tensor([1], dtype=torch.int32).view(torch.float32)
        previous_flushed = (probe * 1.).view(torch.int32).item() == 0
        try:
            torch.set_flush_denormal(True)
            parameter.data.view(torch.int32)[0, 0] = 1
            with pytest.raises(ValueError, match="CPU model bytes changed"):
                decoder.describe()
        finally:
            parameter.data.copy_(original)
            torch.set_flush_denormal(previous_flushed)


def test_checkpoint_byte_layout_survives_contiguous_packed_storage_offsets(authored_checkpoint, scheduler):
    # This real CPU transport control represents CUDA GRU storage packing;
    # it does not assert CUDA execution. Logical values remain identical.
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        ordinary = torch.arange(6, dtype=torch.float32).reshape(2, 3)
        packed = torch.empty(23, dtype=torch.float32)[17:].reshape(2, 3)
        packed.copy_(ordinary)
        original_state, packed_state = {"packed_weight": ordinary}, {"packed_weight": packed}
        original_layout, original_count = decoder._byte_plan(original_state, expected_device="cpu")
        packed_layout, packed_count = decoder._byte_plan(packed_state, expected_device="cpu")
        assert ordinary.storage_offset() == 0 and packed.storage_offset() == 17
        assert original_layout == packed_layout == (("packed_weight", (2, 3), 6),)
        assert original_count == packed_count == 24
        assert decoder._state_bytes(original_state, original_layout, original_count) == decoder._state_bytes(packed_state, packed_layout, packed_count)
        assert decoder._storage_layout(original_state) != decoder._storage_layout(packed_state)
        state = dict(decoder.model.state_dict())
        assert decoder._storage_layout(state) == decoder._state_storage_layout
        assert decoder._storage_layout(decoder._reference_weights) == decoder._reference_storage_layout
        assert decoder._state_bytes(state, decoder._reference_anchor.layout, len(decoder._reference_anchor.payload)) == decoder._reference_anchor.payload
        decoder.describe()


def test_physical_stride_change_is_independent_of_logical_bytes_and_pointer(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        ordinary = torch.arange(3, dtype=torch.float32).reshape(1, 3)
        restaged = ordinary.as_strided((1, 3), (27, 1))
        assert ordinary.is_contiguous() and restaged.is_contiguous()
        assert ordinary.data_ptr() == restaged.data_ptr()
        assert ordinary.storage_offset() == restaged.storage_offset() == 0
        first, second = {"singleton_weight": ordinary}, {"singleton_weight": restaged}
        first_layout, first_count = decoder._byte_plan(first, expected_device="cpu")
        second_layout, second_count = decoder._byte_plan(second, expected_device="cpu")
        assert first_layout == second_layout and first_count == second_count
        assert decoder._state_bytes(first, first_layout, first_count) == decoder._state_bytes(second, second_layout, second_count)
        assert decoder._storage_layout(first) != decoder._storage_layout(second)
        original = decoder._state_storage_layout
        try:
            name, device, stride, offset, pointer = original[0]
            decoder._state_storage_layout = ((name, device, stride, offset + 1, pointer),) + original[1:]
            with pytest.raises(ValueError, match="metadata or storage changed"):
                decoder.describe()
        finally:
            decoder._state_storage_layout = original
        decoder.describe()


@contextmanager
def observed_calls():
    """Observe original code objects without replacing a guarded callable."""
    counts = {name: 0 for name in ("native_implementation", "native_pins", "pure", "poll", "check",
                                  "receipt", "direct_receipt_deepcopies", "restore", "adam")}
    codes = {
        "native_implementation": {native._implementation.__code__},
        "native_pins": {native._pins.__code__},
        "pure": {qualified_v1.BitwiseDeviceLatentFormulaDecoder._pure_check.__code__},
        "poll": {qualified_v1.BitwiseDeviceLatentFormulaDecoder._poll.__code__, subject.BitwiseDeviceLatentFormulaDecoder._poll.__code__},
        "check": {qualified_v1.BitwiseDeviceLatentFormulaDecoder._check.__code__, subject.BitwiseDeviceLatentFormulaDecoder._check.__code__},
        "receipt": {qualified_v1.inference_implementation.__code__, subject._implementation_receipt.__code__},
        "restore": {native._restore.__code__},
        "adam": {torch.optim.Adam.__init__.__code__},
    }
    receipt_callers = {qualified_v1.inference_implementation.__code__,
        qualified_v1.BitwiseDeviceLatentFormulaDecoder._check.__code__, subject._implementation_receipt.__code__,
        subject.BitwiseDeviceLatentFormulaDecoder._check.__code__, coordinator._implementation_receipt.__code__}
    def observe(frame, event, arg):
        if event == "call":
            for name, choices in codes.items():
                if frame.f_code in choices:
                    counts[name] += 1
            if frame.f_code is deepcopy.__code__ and frame.f_back is not None and frame.f_back.f_code in receipt_callers:
                counts["direct_receipt_deepcopies"] += 1
    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        yield counts
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize("operation", ["infer", "infer_with_projection", "project"])
def test_all_four_boundaries_remain_fresh_while_only_receipt_work_is_reduced(authored_checkpoint, scheduler, operation):
    def call(decoder):
        if operation == "project":
            return decoder.project([inputs(authored_checkpoint)[0]["latent"]])
        return getattr(decoder, operation)(inputs(authored_checkpoint))
    with qualified_v1.BitwiseDeviceLatentFormulaDecoder(authored_checkpoint,
            expected_checkpoint_sha256=native.checkpoint_digest(authored_checkpoint),
            optimized=False, scheduler=scheduler) as original:
        with observed_calls() as old_counts:
            old_result = call(original)
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        with observed_calls() as new_counts:
            new_result = call(decoder)
        with observed_calls() as repeated_counts:
            repeated = call(decoder)
    for counts in (old_counts, new_counts, repeated_counts):
        assert counts["pure"] == counts["poll"] == counts["check"] == 4
        assert counts["restore"] == counts["adam"] == 0
    assert old_counts["native_implementation"] == old_counts["native_pins"] == 8
    assert old_counts["receipt"] == 4 and old_counts["direct_receipt_deepcopies"] == 20
    for counts in (new_counts, repeated_counts):
        assert counts["native_implementation"] == counts["native_pins"] == 4
        assert counts["receipt"] == 2 and counts["direct_receipt_deepcopies"] == 8
    if operation == "project":
        assert new_result == repeated == old_result
    else:
        old_report = old_result[0] if operation == "infer_with_projection" else old_result
        new_report = new_result[0] if operation == "infer_with_projection" else new_result
        assert new_report["rows"] == old_report["rows"]
        assert new_report["inference_implementation"]["public_receipt_boundary_scope"] == (
            "inherited_exit_receipt_with_fresh_outer_exit_guard_and_no_outer_receipt")
        if operation == "infer_with_projection":
            assert new_result[1] == repeated[1] == old_result[1]
    assert scheduler.active_leases() == []


def test_matches_override_before_constructor_refuses_before_restore_or_adam(authored_checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(checkpoint_guard.CheckpointContentGuard, "matches", lambda *_: True)
    with observed_calls() as counts:
        with pytest.raises(ValueError, match="matches method changed"):
            open_cpu(authored_checkpoint, scheduler)
    assert counts["restore"] == counts["adam"] == counts["pure"] == 0
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_matches_override_in_live_session_refuses_at_each_boundary(authored_checkpoint, scheduler, monkeypatch, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def is_set(self):
            if (when == "after_forward" and self.decoder is not None
                    and self.decoder._active_observer is not None and sum(self.decoder._active_observer.values())
                    and not self.changed):
                monkeypatch.setattr(checkpoint_guard.CheckpointContentGuard, "matches", lambda *_: True)
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        if when == "entry":
            monkeypatch.setattr(checkpoint_guard.CheckpointContentGuard, "matches", lambda *_: True)
        with pytest.raises(ValueError, match="matches method changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert not decoder._active and not any(module._forward_hooks for module in decoder.model.modules())
        assert cancellation.changed is (when == "after_forward")


@pytest.mark.parametrize("name", ["v1", "_BASE_CLASS", "_PARENT_PURE_CHECK", "_DEVICE_INFER", "_PROJECT",
                                  "_CHECKPOINT_GUARD", "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION", "_GETFRAME"])
def test_live_v2_kernel_guard_and_metadata_aliases_refuse_before_dispatch(authored_checkpoint, scheduler, monkeypatch, name):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        def foreign(*args, **kwargs):
            raise AssertionError("foreign v2 dispatch must never execute")
        monkeypatch.setattr(subject, name, foreign)
        with pytest.raises(ValueError, match="alias changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert not decoder._active


@pytest.mark.parametrize("name", ["v1", "_BASE_CLASS", "_DEVICE_INFER", "_PROJECT", "_CHECKPOINT_GUARD",
                                  "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION", "_GETFRAME"])
def test_live_v2_alias_changes_after_actual_forward_refuse_before_return(authored_checkpoint, scheduler, monkeypatch, name):
    class ChangingCancellation:
        decoder, changed = None, False
        def is_set(self):
            if (self.decoder is not None and self.decoder._active_observer is not None
                    and sum(self.decoder._active_observer.values()) and not self.changed):
                def foreign(*args, **kwargs):
                    raise AssertionError("foreign post-forward v2 dispatch must never execute")
                monkeypatch.setattr(subject, name, foreign)
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        with pytest.raises(ValueError, match="alias changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert cancellation.changed and not decoder._active
        assert not any(module._forward_hooks for module in decoder.model.modules())


@pytest.mark.parametrize("name,value", [("PROFILE", "foreign/v1"), ("SCHEMA", "foreign/v1"),
                                       ("LINEAGES", {"legacy_hub_v1": 8.0, "current_legal_v2": 384})])
def test_profile_schema_and_plain_exact_lineage_metadata_remain_bound(authored_checkpoint, scheduler, monkeypatch, name, value):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        monkeypatch.setattr(subject, name, value)
        with pytest.raises(ValueError, match="lineage declaration changed"):
            decoder.describe()


@pytest.mark.parametrize("fault", ["v1_constructor", "v1_implementation", "v2_inherited_pure_resolution"])
def test_qualified_parent_guards_and_inherited_resolution_remain_live(authored_checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        if fault == "v1_constructor":
            monkeypatch.setattr(qualified_v1.BitwiseDeviceLatentFormulaDecoder, "__init__", lambda *_args, **_kw: None)
        elif fault == "v1_implementation":
            monkeypatch.setattr(qualified_v1, "inference_implementation", lambda: {})
        else:
            monkeypatch.setattr(subject.BitwiseDeviceLatentFormulaDecoder, "_pure_check", lambda *_: None)
        with pytest.raises(ValueError, match="changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))


def test_discarded_receipt_checks_still_refuse_value_and_metadata_changes(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        assert decoder._check(materialize_receipt=False) is None
        parameter = decoder.model.target_embedding.weight
        saved = parameter.detach().clone()
        try:
            parameter.data.view(torch.int32)[0, 0] = 1
            with pytest.raises(ValueError, match="CPU model bytes changed"):
                decoder._check(materialize_receipt=False)
        finally:
            parameter.data.copy_(saved)
        with pytest.raises(ValueError, match="selection must be boolean"):
            decoder._check(materialize_receipt=0)
        receipt = decoder.describe()
        assert receipt["profile_id"] == subject.PROFILE
        assert receipt["inherited_owner_source_sha256"] == hashlib.sha256(Path(qualified_v1.__file__).read_bytes()).hexdigest()
        assert receipt["source_verification_success_cached"] is False
        assert receipt["boundary_consolidation_performed"] is False


def test_report_metadata_has_no_mutable_alias_to_checkpoint_or_currentness(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        first = decoder.describe()
        first["native_checkpoint_implementation"]["files"].clear()
        first["bitwise_guard_implementation"]["source_sha256"] = "0" * 64
        first["reference_byte_currentness"]["anchor_sha256"] = "0" * 64
        first["owned_tensor_currentness"]["implementation"]["source_sha256"] = "0" * 64
        second = decoder.describe()
        assert second["native_checkpoint_implementation"] == authored_checkpoint["implementation"]
        assert second["bitwise_guard_implementation"]["source_sha256"] != "0" * 64
        assert second["reference_byte_currentness"]["anchor_sha256"] == hashlib.sha256(decoder._reference_anchor.payload).hexdigest()
        assert second["owned_tensor_currentness"]["implementation"]["source_sha256"] == bitwise_guard.inference_implementation()["source_sha256"]


@pytest.mark.parametrize("guard_name", ["_checkpoint_guard", "_policy_guard", "_lease_guard"])
@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_new_sameclass_guards_cannot_readmit_changed_owned_values(authored_checkpoint, scheduler, monkeypatch, guard_name, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def change(self):
            decoder = self.decoder
            if guard_name == "_checkpoint_guard":
                decoder._checkpoint["codec"]["target_vocabulary"][1] += "-changed"
                content = decoder._checkpoint
            elif guard_name == "_policy_guard":
                decoder._deadline += 1.
                content = decoder._policy()
            else:
                decoder._lease.memory_mb += 1
                content = decoder._lease_binding()
            setattr(decoder, guard_name, checkpoint_guard.CheckpointContentGuard(content))
            self.changed = True
        def is_set(self):
            if (when == "after_forward" and self.decoder is not None
                    and self.decoder._active_observer is not None and sum(self.decoder._active_observer.values())
                    and not self.changed):
                self.change()
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        original_guard = getattr(decoder, guard_name)
        original_checkpoint = deepcopy(decoder._checkpoint)
        original_deadline, original_memory = decoder._deadline, decoder._lease.memory_mb
        try:
            if when == "entry":
                cancellation.change()
            with pytest.raises(ValueError, match="guard object or immutable snapshot changed|lease object or immutable binding changed"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.changed and not decoder._active
            assert not any(module._forward_hooks for module in decoder.model.modules())
        finally:
            setattr(decoder, guard_name, original_guard)
            decoder._checkpoint.clear()
            decoder._checkpoint.update(original_checkpoint)
            decoder._codec = decoder._checkpoint["codec"]
            decoder._deadline, decoder._lease.memory_mb = original_deadline, original_memory
        decoder.describe()


@pytest.mark.parametrize("guard_name", ["_checkpoint_guard", "_policy_guard", "_lease_guard"])
@pytest.mark.parametrize("field", ["_canonical_bytes", "_reference"])
def test_owned_guard_frozen_snapshot_identity_cannot_be_replaced(authored_checkpoint, scheduler, guard_name, field):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        guard = getattr(decoder, guard_name)
        original = getattr(guard, field)
        replacement = bytes(bytearray(original)) if field == "_canonical_bytes" else deepcopy(original)
        assert replacement == original and replacement is not original
        try:
            object.__setattr__(guard, field, replacement)
            with pytest.raises(ValueError, match="guard object or immutable snapshot changed|lease object or immutable binding changed"):
                decoder._check(materialize_receipt=False)
        finally:
            object.__setattr__(guard, field, original)
        decoder.describe()


@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_resetting_both_guard_binding_markers_cannot_reopen_constructor_bootstrap(authored_checkpoint, scheduler, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def change(self):
            decoder = self.decoder
            decoder._deadline += 1.
            decoder._policy_guard = checkpoint_guard.CheckpointContentGuard(decoder._policy())
            decoder._owned_guard_bindings = decoder._owned_guard_bindings_identity = None
            self.changed = True
        def is_set(self):
            if (when == "after_forward" and self.decoder is not None
                    and self.decoder._active_observer is not None and sum(self.decoder._active_observer.values())
                    and not self.changed):
                self.change()
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        original_guard, original_deadline = decoder._policy_guard, decoder._deadline
        original_bindings, original_identity = decoder._owned_guard_bindings, decoder._owned_guard_bindings_identity
        try:
            if when == "entry":
                cancellation.change()
            with pytest.raises(ValueError, match="bootstrap outside inherited constructor"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.changed and not decoder._active
            assert not any(module._forward_hooks for module in decoder.model.modules())
        finally:
            decoder._policy_guard, decoder._deadline = original_guard, original_deadline
            decoder._owned_guard_bindings, decoder._owned_guard_bindings_identity = original_bindings, original_identity
        decoder.describe()


@pytest.mark.parametrize("when", ["constructor", "after_forward"])
def test_checkpoint_sha256_property_binding_cannot_be_overridden(authored_checkpoint, scheduler, monkeypatch, when):
    if when == "constructor":
        monkeypatch.setattr(checkpoint_guard.CheckpointContentGuard, "sha256", property(lambda self: "a" * 64))
        with observed_calls() as counts:
            with pytest.raises(ValueError, match="SHA256 property changed"):
                open_cpu(authored_checkpoint, scheduler)
        assert counts["restore"] == counts["adam"] == 0
        assert scheduler.active_leases() == []
        return
    class ChangingCancellation:
        decoder, changed = None, False
        def is_set(self):
            if (self.decoder is not None and self.decoder._active_observer is not None
                    and sum(self.decoder._active_observer.values()) and not self.changed):
                monkeypatch.setattr(checkpoint_guard.CheckpointContentGuard, "sha256", property(lambda self: "a" * 64))
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        with pytest.raises(ValueError, match="SHA256 property changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert cancellation.changed and not decoder._active
        assert not any(module._forward_hooks for module in decoder.model.modules())


@contextmanager
def heartbeat_observations():
    """Observe fresh helper calls and actual C durability without patches."""
    previous, counts = sys.getprofile(), {"check": 0, "read": 0, "renewed": 0, "nondue": 0,
                                          "fsync": 0, "replace": 0, "forward": 0}
    check_code = heartbeat.AuthenticatedLeaseHeartbeat.check.__code__
    read_code = heartbeat.AuthenticatedLeaseHeartbeat._read_current.__code__
    def observe(frame, event, arg):
        if event == "call":
            if frame.f_code is check_code:
                counts["check"] += 1
            if frame.f_code is read_code:
                counts["read"] += 1
        elif event == "return" and frame.f_code is check_code:
            if arg is True:
                counts["renewed"] += 1
            elif arg is False:
                counts["nondue"] += 1
        elif event == "c_call":
            if arg is heartbeat.resources.os.fsync:
                counts["fsync"] += 1
            elif arg is heartbeat.resources.os.replace:
                counts["replace"] += 1
        if previous is not None:
            previous(frame, event, arg)
    try:
        sys.setprofile(observe)
        yield counts
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize("operation", ["infer", "infer_with_projection", "project"])
def test_every_public_boundary_authenticates_nondue_without_durable_writes(authored_checkpoint, scheduler, operation):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        before = scheduler.state_path.read_bytes()
        helper, snapshot = decoder._heartbeat_owner, decoder._heartbeat_snapshot
        for _ in range(2):
            with heartbeat_observations() as seen:
                if operation == "project":
                    result = decoder.project([inputs(authored_checkpoint)[0]["latent"]])
                else:
                    result = getattr(decoder, operation)(inputs(authored_checkpoint))
            assert seen["check"] == seen["read"] == seen["nondue"] == 4
            assert seen["renewed"] == seen["fsync"] == seen["replace"] == 0
            assert scheduler.state_path.read_bytes() == before
            assert decoder._heartbeat_owner is helper and decoder._heartbeat_snapshot is snapshot
            if operation != "project":
                report = result[0] if operation == "infer_with_projection" else result
                profile = report["inference_implementation"]
                assert profile["lease_currentness"] == {
                    "schema": "modal-latent-formula-authenticated-lease-currentness/v1",
                    "fresh_authenticated_read_completed": True, "renewed_at_receipt_boundary": False,
                    "boundary_scope": "this_checked_boundary_only_no_whole_call_or_execution_attestation"}
                assert profile["authenticated_lease_heartbeat_object_and_snapshot_identities_checked"] is True
                assert profile["input_guard_substitution_performed"] is False
                assert profile["lease_currentness_success_cached"] is False
                assert profile["existing_scheduler_or_auto_heartbeat_modified"] is False


@pytest.mark.parametrize("field", subject._HEARTBEAT_FIELDS)
@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_helper_frozen_field_identity_changes_refuse_each_boundary(authored_checkpoint, scheduler, field, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def change(self):
            helper = self.decoder._heartbeat_owner
            value = getattr(helper, field)
            replacement = (tuple(list(value)) if type(value) is tuple else value + 1
                           if type(value) in (int, float) else object())
            assert replacement is not value
            object.__setattr__(helper, field, replacement)
            self.changed = True
        def is_set(self):
            if (when == "after_forward" and self.decoder is not None and self.decoder._active_observer is not None
                    and sum(self.decoder._active_observer.values()) and not self.changed):
                self.change()
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        helper, value = decoder._heartbeat_owner, getattr(decoder._heartbeat_owner, field)
        try:
            if when == "entry":
                cancellation.change()
            with pytest.raises(ValueError, match="helper object or immutable snapshot changed"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.changed and not decoder._active
            assert not any(module._forward_hooks for module in decoder.model.modules())
        finally:
            object.__setattr__(helper, field, value)
        decoder.describe()


@pytest.mark.parametrize("fault", ["helper", "snapshot", "identity_marker", "both_none"])
@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_owned_helper_and_snapshot_markers_cannot_be_replaced_or_reset(authored_checkpoint, scheduler, fault, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def change(self):
            decoder = self.decoder
            if fault == "helper":
                decoder._heartbeat_owner = heartbeat.AuthenticatedLeaseHeartbeat(decoder._lease)
            elif fault == "snapshot":
                decoder._heartbeat_snapshot = tuple(list(decoder._heartbeat_snapshot))
            elif fault == "identity_marker":
                decoder._heartbeat_snapshot_identity = tuple(list(decoder._heartbeat_snapshot))
            else:
                decoder._heartbeat_owner = decoder._heartbeat_snapshot = decoder._heartbeat_snapshot_identity = None
            self.changed = True
        def is_set(self):
            if (when == "after_forward" and self.decoder is not None and self.decoder._active_observer is not None
                    and sum(self.decoder._active_observer.values()) and not self.changed):
                self.change()
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        saved = decoder._heartbeat_owner, decoder._heartbeat_snapshot, decoder._heartbeat_snapshot_identity
        try:
            if when == "entry":
                cancellation.change()
            with pytest.raises(ValueError, match="snapshot changed|bootstrap outside inherited constructor"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.changed and not decoder._active
        finally:
            decoder._heartbeat_owner, decoder._heartbeat_snapshot, decoder._heartbeat_snapshot_identity = saved
        decoder.describe()


@pytest.mark.parametrize("operation", ["infer_with_projection", "project"])
def test_callback_cannot_replace_helper_and_both_markers_together(authored_checkpoint, scheduler, operation):
    class ChangingCancellation:
        decoder, changed, projection_returned = None, False, False
        def is_set(self):
            decoder = self.decoder
            if (decoder is not None and self.projection_returned and not self.changed):
                helper = heartbeat.AuthenticatedLeaseHeartbeat(decoder._lease)
                snapshot = (helper, *(getattr(helper, name) for name in subject._HEARTBEAT_FIELDS))
                decoder._heartbeat_owner = helper
                decoder._heartbeat_snapshot = decoder._heartbeat_snapshot_identity = snapshot
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        saved = decoder._heartbeat_owner, decoder._heartbeat_snapshot, decoder._heartbeat_snapshot_identity
        project_code = decoder.model.project.__func__.__code__
        previous = sys.getprofile()
        def observe_project_return(frame, event, arg):
            if event == "return" and frame.f_code is project_code and arg is not None:
                cancellation.projection_returned = True
            if previous is not None:
                previous(frame, event, arg)
        try:
            sys.setprofile(observe_project_return)
            with pytest.raises(ValueError, match="helper object or immutable snapshot changed"):
                if operation == "project":
                    decoder.project([inputs(authored_checkpoint)[0]["latent"]])
                else:
                    decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.projection_returned and cancellation.changed and not decoder._active
        finally:
            sys.setprofile(previous)
            decoder._heartbeat_owner, decoder._heartbeat_snapshot, decoder._heartbeat_snapshot_identity = saved


@pytest.mark.parametrize("fault", ["helper_class", "helper_check", "helper_check_code", "helper_constructor_defaults",
                                    "helper_implementation", "owner_helper_alias", "clock", "frame", "coordinator_check"])
@pytest.mark.parametrize("when", ["constructor", "after_forward"])
def test_helper_and_owner_live_bindings_refuse_before_dispatch(authored_checkpoint, scheduler, monkeypatch, fault, when):
    def change():
        foreign = lambda *_args, **_kwargs: False
        if fault == "helper_class":
            monkeypatch.setattr(heartbeat, "AuthenticatedLeaseHeartbeat", object)
        elif fault == "helper_check":
            monkeypatch.setattr(heartbeat.AuthenticatedLeaseHeartbeat, "check", foreign)
        elif fault == "helper_check_code":
            def replacement(self):
                return False
            monkeypatch.setattr(heartbeat.AuthenticatedLeaseHeartbeat.check, "__code__", replacement.__code__)
        elif fault == "helper_constructor_defaults":
            monkeypatch.setattr(heartbeat.AuthenticatedLeaseHeartbeat.__init__, "__kwdefaults__", {"renewal_fraction": .5})
        elif fault == "helper_implementation":
            monkeypatch.setattr(heartbeat, "inference_implementation", lambda: {})
        elif fault == "owner_helper_alias":
            monkeypatch.setattr(subject, "_HEARTBEAT", foreign)
        elif fault == "clock":
            monkeypatch.setattr(subject, "_MONOTONIC", lambda: 0.)
        elif fault == "frame":
            monkeypatch.setattr(subject, "_GETFRAME", foreign)
        else:
            monkeypatch.setattr(coordinator, "_check_bindings", lambda: None)
    if when == "constructor":
        change()
        with observed_calls() as counts:
            with pytest.raises(ValueError, match="changed"):
                open_cpu(authored_checkpoint, scheduler)
        assert counts["restore"] == counts["adam"] == 0
        assert scheduler.active_leases() == []
        return
    class ChangingCancellation:
        decoder, changed = None, False
        def is_set(self):
            if (self.decoder is not None and self.decoder._active_observer is not None
                    and sum(self.decoder._active_observer.values()) and not self.changed):
                change()
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        with pytest.raises(ValueError, match="changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert cancellation.changed and not decoder._active
        assert not any(module._forward_hooks for module in decoder.model.modules())


@pytest.mark.parametrize("fault", ["own_key", "own_cancel", "own_expiry", "parent_cancel", "parent_expiry", "missing_parent"])
def test_fresh_shared_authority_and_ancestry_refuse_before_real_forward(authored_checkpoint, scheduler, fault):
    with scheduler.acquire("snapshot_evaluation", cpu_slots=2, memory_mb=2048) as parent:
        with open_cpu(authored_checkpoint, scheduler, parent_lease=parent) as decoder:
            with scheduler._locked_state(persist=False) as state:
                original = deepcopy(state)
            try:
                with scheduler._locked_state() as state:
                    own, ancestor = state["leases"][decoder._lease.lease_id], state["leases"][parent.lease_id]
                    if fault == "own_key":
                        own["lease_key"] = "foreign-authority"
                    elif fault == "own_cancel":
                        own["cancelled"] = True
                    elif fault == "own_expiry":
                        own["expires_at"] = time.time() - 1
                    elif fault == "parent_cancel":
                        ancestor["cancelled"] = True
                    elif fault == "parent_expiry":
                        ancestor["expires_at"] = time.time() - 1
                    else:
                        del state["leases"][parent.lease_id]
                with observed_calls() as counts:
                    with pytest.raises(ValueError):
                        decoder.infer_with_projection(inputs(authored_checkpoint))
                assert counts["pure"] == 0 and not decoder._active
            finally:
                with scheduler._locked_state() as state:
                    state.clear()
                    state.update(original)
            decoder.describe()
        assert not parent.released and len(scheduler.active_leases()) == 1


@pytest.mark.parametrize("mutation", ["local_key", "local_scheduler"])
def test_local_lease_authority_substitution_refuses_and_ordinary_close_survives(authored_checkpoint, scheduler, mutation):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        original_key, original_scheduler = decoder._lease.lease_key, decoder._lease._scheduler
        try:
            if mutation == "local_key":
                decoder._lease.lease_key = "foreign-authority"
            else:
                decoder._lease._scheduler = object()
            with pytest.raises(ValueError, match="binding changed|snapshot changed"):
                decoder.infer(inputs(authored_checkpoint))
        finally:
            decoder._lease.lease_key, decoder._lease._scheduler = original_key, original_scheduler
        decoder.describe()
    assert scheduler.active_leases() == []


def test_constructor_callback_cannot_inject_helper_before_owned_admission(authored_checkpoint, scheduler):
    class InjectingCancellation:
        changed = False
        def is_set(self):
            frame = sys._getframe(1)
            try:
                if frame.f_code is subject.BitwiseDeviceLatentFormulaDecoder._poll.__code__:
                    decoder = frame.f_locals["self"]
                    assert decoder._lease is None
                    decoder._heartbeat_owner = object()
                    self.changed = True
            finally:
                del frame
            return False
    cancellation = InjectingCancellation()
    with observed_calls() as counts:
        with pytest.raises(ValueError, match="pre-admission callback changed helper"):
            open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation)
    assert cancellation.changed and counts["restore"] == counts["adam"] == 0
    assert scheduler.active_leases() == []


def test_cancellation_after_actual_projection_keeps_child_charged_until_close(authored_checkpoint, scheduler):
    class Cancelling:
        decoder, cancelled = None, False
        def is_set(self):
            decoder = self.decoder
            if (decoder is not None and decoder._active_observer is not None
                    and sum(decoder._active_observer.values()) and not self.cancelled):
                decoder._lease.cancel()
                self.cancelled = True
            return False
    with scheduler.acquire("snapshot_evaluation", cpu_slots=2, memory_mb=2048) as parent:
        cancellation = Cancelling()
        decoder = open_cpu(authored_checkpoint, scheduler, parent_lease=parent, cancel_event=cancellation)
        cancellation.decoder = decoder
        with pytest.raises(ValueError, match="expired, cancelled or changed"):
            decoder.infer_with_projection(inputs(authored_checkpoint))
        assert cancellation.cancelled and not decoder._active
        assert not decoder._lease.released and not parent.released
        assert decoder._lease.lease_id in {lease["lease_id"] for lease in scheduler.active_leases()}
        decoder.close()
        assert decoder._lease.released and not parent.released
        assert len(scheduler.active_leases()) == 1


def test_standalone_metadata_grants_no_live_poll_or_production_authority():
    description = subject.inference_implementation()
    assert description["profile_id"] == subject.PROFILE
    assert description["inherited_coordinator_source_sha256"] == hashlib.sha256(Path(coordinator.__file__).read_bytes()).hexdigest()
    assert "lease_currentness" not in description
    assert "authenticated_lease_heartbeat_object_and_snapshot_identities_checked" not in description
    assert description["authenticated_lease_heartbeat_implementation"] == heartbeat.inference_implementation()
    for name in ("native_cuda_qualified", "performance_qualified", "semantic_qualification", "production_admission", "proof_authority",
                 "lease_currentness_success_cached", "input_guard_substitution_performed", "existing_scheduler_or_auto_heartbeat_modified"):
        assert description[name] is False


def test_returned_heartbeat_metadata_has_no_alias_to_future_receipts(authored_checkpoint, scheduler):
    with open_cpu(authored_checkpoint, scheduler) as decoder:
        description = decoder.describe()
        description["authenticated_lease_heartbeat_implementation"]["source_sha256"] = "0" * 64
        description["lease_currentness"]["fresh_authenticated_read_completed"] = False
        fresh = decoder.describe()
        assert fresh["authenticated_lease_heartbeat_implementation"] == heartbeat.inference_implementation()
        assert fresh["lease_currentness"]["fresh_authenticated_read_completed"] is True


@pytest.mark.parametrize("field", ["_process", "_thread"])
@pytest.mark.parametrize("when", ["entry", "after_forward"])
def test_process_thread_ownership_still_refuses_each_public_boundary(authored_checkpoint, scheduler, field, when):
    class ChangingCancellation:
        decoder, changed = None, False
        def is_set(self):
            decoder = self.decoder
            if (when == "after_forward" and decoder is not None and decoder._active_observer is not None
                    and sum(decoder._active_observer.values()) and not self.changed):
                setattr(decoder, field, getattr(decoder, field) + 1)
                self.changed = True
            return False
    cancellation = ChangingCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        previous = getattr(decoder, field)
        try:
            if when == "entry":
                setattr(decoder, field, previous + 1)
            with pytest.raises(ValueError, match="process/thread|callback lease changed|foreign or closed"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert not decoder._active
        finally:
            setattr(decoder, field, previous)
        decoder.describe()


def test_post_forward_deadline_is_checked_before_authentication_or_return(authored_checkpoint, scheduler):
    class ExpiringCancellation:
        decoder, changed = None, False
        def is_set(self):
            decoder = self.decoder
            if (decoder is not None and decoder._active_observer is not None
                    and sum(decoder._active_observer.values()) and not self.changed):
                decoder._deadline = time.monotonic() - 1
                self.changed = True
            return False
    cancellation = ExpiringCancellation()
    with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
        cancellation.decoder = decoder
        deadline = decoder._deadline
        try:
            with pytest.raises(TimeoutError, match="deadline expired"):
                decoder.infer_with_projection(inputs(authored_checkpoint))
            assert cancellation.changed and not decoder._active
        finally:
            decoder._deadline = deadline
        decoder.describe()


@pytest.mark.parametrize("when", ["constructor", "after_forward"])
@pytest.mark.parametrize("outcome", ["false", "true", "raises"])
def test_callback_lease_injection_never_transfers_cleanup_to_another_owner(authored_checkpoint, scheduler, when, outcome):
    class InjectingCancellation:
        decoder, changed = None, False
        def is_set(self):
            frame = sys._getframe(1)
            try:
                if frame.f_code is subject.BitwiseDeviceLatentFormulaDecoder._poll.__code__:
                    decoder = frame.f_locals["self"]
                    ready = decoder._lease is None if when == "constructor" else (
                        decoder._active_observer is not None and sum(decoder._active_observer.values()))
                    if ready and not self.changed:
                        decoder._lease = separate
                        self.changed = True
                        if outcome == "raises":
                            raise RuntimeError("injected callback error")
                        return outcome == "true"
            finally:
                del frame
            return False
    with scheduler.acquire("snapshot_evaluation", cpu_slots=1, memory_mb=128) as separate:
        cancellation = InjectingCancellation()
        if when == "constructor":
            with observed_calls() as counts:
                with pytest.raises(ValueError, match="callback lease changed"):
                    open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation)
            assert counts["restore"] == counts["adam"] == 0
        else:
            with open_cpu(authored_checkpoint, scheduler, cancel_event=cancellation) as decoder:
                owned = decoder._lease
                with pytest.raises(ValueError, match="callback lease changed"):
                    decoder.infer_with_projection(inputs(authored_checkpoint))
                assert decoder._lease is owned and not separate.released
            assert owned.released
        assert cancellation.changed and not separate.released
        assert {lease["lease_id"] for lease in scheduler.active_leases()} == {separate.lease_id}
    assert scheduler.active_leases() == []
