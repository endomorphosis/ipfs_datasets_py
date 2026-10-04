"""No-fit CPU controls for the new owned8D/384D formula adapter.

Authored native checkpoints have zero training/Adam steps. These controls run
real CPU model projections, preserve source/lineage bindings, and exercise
ownership refusals. CUDA availability mocks test selection only and never
qualify CUDA execution, performance, trained semantics or proof authority.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import threading
import time

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_inference as batched
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_device_inference as inherited
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_bitwise_device_inference as subject
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
