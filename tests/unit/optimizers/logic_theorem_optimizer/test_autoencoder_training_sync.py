"""Qualification and session boundaries for optional gradient synchronization."""

from dataclasses import dataclass, replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import (
    GradientBackendCapabilities,
    GradientBackendUnavailable,
    GradientBucketSpec,
    GradientReduction,
    GradientReductionRequest,
    TrainingMode,
    TrainingRoundBinding,
    TrainingSyncController,
    TrainingSyncError,
)


@dataclass
class Tensor:
    shape: tuple[int, ...] = (2, 8)
    dtype: str = "float32"


class RecordingBackend:
    def __init__(self):
        self.calls = []
        self.output = Tensor()
        self.failure = None
        self.declared = GradientBackendCapabilities(
            "qualified-test-backend", (GradientReduction.SUM, GradientReduction.MEAN),
            ("float32",), True, True,
        )

    def capabilities(self):
        return self.declared

    def join(self, binding, participant_id):
        self.calls.append(("join", binding, participant_id))

    def reduce_gradients(self, reduction_request, gradients):
        self.calls.append(("reduce_gradients", reduction_request, gradients))
        if self.failure:
            raise self.failure
        return self.output

    def barrier(self, binding, participant_id, operation_id, deadline_unix_s):
        self.calls.append(("barrier", binding, participant_id, operation_id, deadline_unix_s))

    def abort(self, binding, reason):
        self.calls.append(("abort", binding, reason))

    def close(self, binding):
        self.calls.append(("close", binding))


@pytest.fixture
def binding():
    return TrainingRoundBinding(
        "legal-run", "round-7", "a" * 64, "b" * 64, "local-sgd/v1", 3,
        ("worker-a", "worker-b"),
    )


@pytest.fixture
def reduction_request(binding):
    return GradientReductionRequest(
        binding, "worker-a", 5, GradientBucketSpec("encoder", (2, 8), "float32"),
        GradientReduction.MEAN, 0.5, 120.0, "step-5-encoder-worker-a",
    )


def synchronized(backend=None, clock=lambda: 100.0):
    backend = backend or RecordingBackend()
    return TrainingSyncController(
        mode=TrainingMode.GRADIENT_SYNCHRONIZED, backend=backend,
        verify_backend=lambda selected, capabilities: selected is backend,
        clock=clock,
    ), backend


def test_federated_default_does_not_advertise_gradient_sync(binding):
    controller = TrainingSyncController()
    assert controller.mode is TrainingMode.FEDERATED
    assert controller.supported_modes == (TrainingMode.FEDERATED,)
    with pytest.raises(GradientBackendUnavailable):
        controller.join(binding, "worker-a")
    controller.close()


@pytest.mark.parametrize("options", [
    {}, {"backend": RecordingBackend()},
    {"verify_backend": lambda *_: True},
    {"backend": RecordingBackend(), "verify_backend": lambda *_: False},
    {"backend": RecordingBackend(), "verify_backend": lambda *_: 1},
    {"backend": object(), "verify_backend": lambda *_: True},
])
def test_sync_requires_independently_qualified_backend(options):
    with pytest.raises(GradientBackendUnavailable):
        TrainingSyncController(mode=TrainingMode.GRADIENT_SYNCHRONIZED, **options)


def test_bad_capability_object_and_verifier_failure_are_unavailable():
    backend = RecordingBackend()
    backend.declared = {"complete_membership": True}
    with pytest.raises(GradientBackendUnavailable, match="invalid capabilities"):
        synchronized(backend)
    backend = RecordingBackend()
    def broken_verifier(*_):
        raise RuntimeError("qualification service unavailable")
    with pytest.raises(GradientBackendUnavailable, match="qualification failed"):
        TrainingSyncController(
            mode=TrainingMode.GRADIENT_SYNCHRONIZED, backend=backend,
            verify_backend=broken_verifier,
        )


@pytest.mark.parametrize("field,value", [
    ("run_id", ""), ("round_id", " padded "), ("base_sha256", "A" * 64),
    ("layout_sha256", "sha256:" + "b" * 64), ("optimizer_profile", "\n"),
    ("membership_epoch", True), ("membership_epoch", -1),
    ("participant_ids", ["worker-a"]), ("participant_ids", ()),
    ("participant_ids", ("worker-a", "worker-a")),
])
def test_strict_immutable_round_binding(binding, field, value):
    with pytest.raises(TrainingSyncError):
        replace(binding, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("participant_id", "unknown"), ("step", True), ("step", -1),
    ("scale", True), ("scale", float("nan")), ("scale", float("inf")),
    ("scale", 10 ** 1000), ("scale", 0), ("deadline_unix_s", -1),
    ("reduction", "mean"), ("operation_id", ""),
])
def test_strict_reduction_request(reduction_request, field, value):
    with pytest.raises(TrainingSyncError):
        replace(reduction_request, **{field: value})


@pytest.mark.parametrize("shape,dtype", [
    ((0, 8), "float32"), ((True, 8), "float32"), ([2, 8], "float32"),
    ((2, 8), "int64"), ((2, 8), "torch.float32"),
])
def test_bucket_requires_canonical_shape_dtype(shape, dtype):
    with pytest.raises(TrainingSyncError):
        GradientBucketSpec("encoder", shape, dtype)


@pytest.mark.parametrize("field,value", [
    ("complete_membership", False), ("idempotent_operations", 1),
    ("reductions", ("mean",)), ("dtypes", ("int64",)),
])
def test_backend_capabilities_require_collective_contract(field, value):
    original = RecordingBackend().declared
    with pytest.raises(TrainingSyncError):
        replace(original, **{field: value})


def test_forwarding_preserves_tensor_request_and_scaling_contract(binding, reduction_request):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    gradients = Tensor(dtype="torch.float32")
    result = controller.reduce_gradients(reduction_request, gradients)
    assert result is backend.output
    assert backend.calls[-1][1] == reduction_request
    assert backend.calls[-1][1] is not reduction_request
    assert backend.calls[-1][2] is gradients
    assert reduction_request.reduction is GradientReduction.MEAN and reduction_request.scale == 0.5
    assert binding.world_size == 2
    controller.barrier(binding, operation_id="step-5-done", deadline_unix_s=120.0)
    assert backend.calls[-1] == ("barrier", binding, "worker-a", "step-5-done", 120.0)
    controller.close()
    assert backend.calls[-1] == ("close", binding)
    assert controller.binding is None


@pytest.mark.parametrize("field,value", [
    ("membership_epoch", 2), ("layout_sha256", "c" * 64),
    ("base_sha256", "c" * 64), ("optimizer_profile", "other/v1"),
    ("round_id", "round-6"), ("participant_ids", ("worker-a", "worker-c")),
])
def test_stale_or_incompatible_round_never_reaches_backend(binding, reduction_request, field, value):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    bad_request = replace(reduction_request, binding=replace(binding, **{field: value}))
    with pytest.raises(TrainingSyncError, match="joined round binding"):
        controller.reduce_gradients(bad_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


@pytest.mark.parametrize("tensor", [Tensor((2, 384)), Tensor(dtype="float64"), object()])
def test_wrong_tensor_rejected_before_collective(binding, reduction_request, tensor):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError):
        controller.reduce_gradients(reduction_request, tensor)
    assert [call[0] for call in backend.calls] == ["join"]


def test_wrong_participant_and_expired_deadline_rejected(binding, reduction_request):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="participant differs"):
        controller.reduce_gradients(replace(reduction_request, participant_id="worker-b"), Tensor())
    with pytest.raises(TrainingSyncError, match="expired"):
        controller.reduce_gradients(replace(reduction_request, deadline_unix_s=100), Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


def test_unsupported_dtype_and_reduction_rejected(binding, reduction_request):
    controller, backend = synchronized()
    backend.declared = replace(backend.declared, reductions=(GradientReduction.SUM,))
    # Configure again so the independently qualified declaration is the new one.
    controller, backend = synchronized(backend)
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="does not support"):
        controller.reduce_gradients(reduction_request, Tensor())
    with pytest.raises(TrainingSyncError, match="does not support"):
        controller.reduce_gradients(
            replace(reduction_request, bucket=replace(reduction_request.bucket, dtype="float64")),
            Tensor(dtype="float64"),
        )
    assert [call[0] for call in backend.calls] == ["join"]


@pytest.mark.parametrize("failure", [RuntimeError("collective failed"), None])
def test_backend_failure_or_invalid_result_aborts_without_fallback(binding, reduction_request, failure):
    controller, backend = synchronized()
    backend.failure = failure
    backend.output = Tensor((2, 384))
    controller.join(binding, "worker-a")
    with pytest.raises((RuntimeError, TrainingSyncError)):
        controller.reduce_gradients(reduction_request, Tensor())
    assert backend.calls[-1] == ("abort", binding, "backend_operation_failed")
    with pytest.raises(TrainingSyncError, match="session failed"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert controller.supported_modes == (TrainingMode.GRADIENT_SYNCHRONIZED,)
    controller.close()
    assert backend.calls[-1] == ("close", binding)


def test_session_abort_is_terminal_and_cleanup_remains_available(binding):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    controller.abort(reason="membership_changed")
    with pytest.raises(TrainingSyncError, match="session failed"):
        controller.barrier(binding, operation_id="barrier", deadline_unix_s=120)
    controller.close()
    assert [call[0] for call in backend.calls] == ["join", "abort", "close"]


def test_384_shape_is_forwarded_without_tensor_conversion(binding, reduction_request):
    controller, backend = synchronized()
    tensor = Tensor((4, 384))
    backend.output = tensor
    reduction_request = replace(reduction_request, bucket=replace(reduction_request.bucket, shape=(4, 384)))
    controller.join(binding, "worker-a")
    assert controller.reduce_gradients(reduction_request, tensor) is tensor


def test_federated_backend_and_string_modes_cannot_enable_sync():
    with pytest.raises(TrainingSyncError):
        TrainingSyncController(backend=RecordingBackend())
    with pytest.raises(TrainingSyncError):
        TrainingSyncController(mode="gradient_synchronized")


def test_failed_join_aborts_and_can_still_close_resources(binding):
    backend = RecordingBackend()
    def fail_join(*_):
        raise RuntimeError("failed rendezvous")
    backend.join = fail_join
    controller, backend = synchronized(backend)
    with pytest.raises(RuntimeError, match="failed rendezvous"):
        controller.join(binding, "worker-a")
    controller.close()
    assert backend.calls == [
        ("abort", binding, "backend_operation_failed"), ("close", binding),
    ]


def test_late_collective_result_is_rejected_and_aborted(binding, reduction_request):
    ticks = iter((100.0, 121.0))
    controller, backend = synchronized(clock=lambda: next(ticks))
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="expired"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert backend.calls[-1] == ("abort", binding, "backend_operation_failed")


@pytest.mark.parametrize("clock", [lambda: True, lambda: float("nan"), lambda: 10 ** 1000])
def test_invalid_clock_rejects_operation_before_backend(binding, reduction_request, clock):
    controller, backend = synchronized(clock=clock)
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="invalid timestamp"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


def test_membership_join_and_single_active_round(binding):
    controller, backend = synchronized()
    with pytest.raises(TrainingSyncError, match="outside"):
        controller.join(binding, "unknown")
    assert backend.calls == []
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="close the joined round"):
        controller.join(replace(binding, membership_epoch=4), "worker-a")
    controller.close()
    new_binding = replace(binding, membership_epoch=4)
    controller.join(new_binding, "worker-a")
    assert controller.binding == new_binding


def test_contract_objects_and_selected_mode_are_immutable(binding, reduction_request):
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        binding.layout_sha256 = "c" * 64
    with pytest.raises(FrozenInstanceError):
        reduction_request.scale = 1
    with pytest.raises(AttributeError):
        TrainingSyncController().mode = TrainingMode.GRADIENT_SYNCHRONIZED


@pytest.mark.parametrize("field,value", [
    ("membership_epoch", 0), ("layout_sha256", "c" * 64),
    ("participant_ids", ("worker-a", "worker-c")),
])
def test_join_owns_snapshot_when_original_binding_is_unsafely_mutated(
    binding, reduction_request, field, value,
):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    object.__setattr__(binding, field, value)
    with pytest.raises(TrainingSyncError, match="joined round binding"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


@pytest.mark.parametrize("field,value", [
    ("step", -1), ("participant_id", "unknown"), ("scale", float("nan")),
    ("operation_id", ""), ("deadline_unix_s", True), ("reduction", "mean"),
])
def test_reduction_revalidates_unsafely_mutated_requests(binding, reduction_request, field, value):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    object.__setattr__(reduction_request, field, value)
    with pytest.raises(TrainingSyncError):
        controller.reduce_gradients(reduction_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


@pytest.mark.parametrize("field,value", [("shape", (True, 8)), ("dtype", "int64")])
def test_reduction_revalidates_unsafely_mutated_nested_bucket(
    binding, reduction_request, field, value,
):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    object.__setattr__(reduction_request.bucket, field, value)
    with pytest.raises(TrainingSyncError):
        controller.reduce_gradients(reduction_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join"]


def test_public_binding_and_backend_join_input_do_not_alias_session(binding, reduction_request):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    exposed = controller.binding
    backend_binding = backend.calls[0][1]
    assert exposed == backend_binding == binding
    assert exposed is not backend_binding and exposed is not binding
    object.__setattr__(exposed, "layout_sha256", "c" * 64)
    object.__setattr__(backend_binding, "membership_epoch", 0)
    assert controller.reduce_gradients(reduction_request, Tensor()) is backend.output
    assert controller.binding == binding


@pytest.mark.parametrize("target", ["verifier_input", "backend_declaration"])
def test_capabilities_mutated_during_qualification_are_rejected(target):
    backend = RecordingBackend()
    def mutating_verifier(selected, declared):
        value = declared if target == "verifier_input" else selected.declared
        object.__setattr__(value, "dtypes", ("float64",))
        return True
    with pytest.raises(GradientBackendUnavailable, match="changed during"):
        TrainingSyncController(
            mode=TrainingMode.GRADIENT_SYNCHRONIZED, backend=backend,
            verify_backend=mutating_verifier,
        )


def test_capabilities_changed_after_qualification_invalidate_session(binding, reduction_request):
    controller, backend = synchronized()
    controller.join(binding, "worker-a")
    object.__setattr__(backend.declared, "complete_membership", False)
    with pytest.raises(GradientBackendUnavailable, match="no longer qualified"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert [call[0] for call in backend.calls] == ["join", "abort"]
    controller.close()
    assert backend.calls[-1] == ("close", binding)


def test_backend_request_mutation_cannot_change_result_validation(binding, reduction_request):
    backend = RecordingBackend()
    def malicious_reduction(dispatched, tensor):
        object.__setattr__(dispatched.bucket, "shape", (2, 384))
        object.__setattr__(dispatched, "deadline_unix_s", 99999999)
        return Tensor((2, 384))
    backend.reduce_gradients = malicious_reduction
    controller, backend = synchronized(backend)
    controller.join(binding, "worker-a")
    with pytest.raises(TrainingSyncError, match="shape differs"):
        controller.reduce_gradients(reduction_request, Tensor())
    assert reduction_request.bucket.shape == (2, 8)
    assert reduction_request.deadline_unix_s == 120.0
    assert backend.calls[-1] == ("abort", binding, "backend_operation_failed")
