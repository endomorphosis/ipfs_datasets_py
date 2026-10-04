"""CPU numerical controls and CPU-backed CUDA bit-view protocol controls.

Protocol labels count complete chunk work and host decisions. They establish
no native CUDA, timing, model, execution, production or proof qualification.
"""
import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_bitwise_guard as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_value_guard as reference_guard


class ProtocolDevice:
    def __init__(self, label):
        self.label, self.type = label, label.split(":")[0]

    def __str__(self):
        return self.label


class ProtocolTensor:
    def __init__(self, runtime, value, device="cuda:0"):
        self.runtime, self.value, self.device = runtime, value, ProtocolDevice(device)

    @property
    def dtype(self):
        return self.value.dtype

    @property
    def shape(self):
        return self.value.shape

    @property
    def layout(self):
        return self.value.layout

    def numel(self):
        return self.value.numel()

    def element_size(self):
        return self.value.element_size()

    def is_contiguous(self):
        return self.value.is_contiguous()

    def is_conj(self):
        return self.value.is_conj()

    def is_neg(self):
        return self.value.is_neg()

    def untyped_storage(self):
        return self.value.untyped_storage()

    def reshape(self, *shape):
        self.runtime.calls.append("reshape")
        return ProtocolTensor(self.runtime, self.value.reshape(*shape), str(self.device))

    def __getitem__(self, item):
        self.runtime.calls.append("slice")
        return ProtocolTensor(self.runtime, self.value[item], str(self.device))

    def view(self, dtype):
        self.runtime.calls.append("view")
        assert dtype is torch.int32, "CUDA comparison must reinterpret float32 as int32"
        viewed = self.value.view(dtype)
        assert viewed.untyped_storage().data_ptr() == self.value.untyped_storage().data_ptr()
        return ProtocolTensor(self.runtime, viewed, str(self.device))

    def logical_and_(self, other):
        self.runtime.calls.append("logical_and")
        self.value.logical_and_(other.value)
        return self

    def all(self):
        self.runtime.calls.append("all")
        return ProtocolTensor(self.runtime, self.value.all(), str(self.device))

    def __bool__(self):
        self.runtime.host_decisions += 1
        assert self.value.numel() == 1, "only scalar decisions may reach the host"
        return bool(self.value)


class ProtocolTorch:
    Tensor, float32, int32, strided = ProtocolTensor, torch.float32, torch.int32, torch.strided

    def __init__(self):
        self.calls, self.host_decisions, self.equal_calls, self.eq_elements = [], 0, 0, []

    def wrap(self, value, device="cuda:0"):
        return ProtocolTensor(self, value, device)

    def eq(self, left, right):
        self.calls.append("eq")
        assert left.dtype is right.dtype is torch.int32
        self.eq_elements.append(left.numel())
        return self.wrap(torch.eq(left.value, right.value), str(left.device))

    def signbit(self, value):
        self.calls.append("signbit")
        return self.wrap(torch.signbit(value.value), str(value.device))

    def isfinite(self, value):
        self.calls.append("isfinite")
        assert value.dtype is torch.float32
        return self.wrap(torch.isfinite(value.value), str(value.device))

    def stack(self, values):
        self.calls.append("stack")
        return self.wrap(torch.stack([value.value for value in values]), str(values[0].device))

    def equal(self, left, right):
        self.calls.append("equal")
        self.equal_calls += 1
        self.host_decisions += 1
        return torch.equal(left.value, right.value)

    @property
    def cuda(self):
        raise AssertionError("guard must not inspect or initialize CUDA APIs")

    def is_autocast_enabled(self, *args, **kwargs):
        raise AssertionError("exact checks must not consult autocast")


def from_bits(bits):
    signed = [item if item < 2**31 else item - 2**32 for item in bits]
    return torch.tensor(signed, dtype=torch.int32).view(torch.float32)


def cpu_pair():
    value = from_bits([0, 0x80000000, 1, 0x80000001, 0x00800000, 0x80800000,
                       0x3F800000, 0xBF800000, 0x7F7FFFFF, 0xFF7FFFFF])
    state = {"weight": value.reshape(2, 5), "bias": torch.tensor(.5), "empty": torch.empty(0)}
    return state, {name: item.detach().clone() for name, item in state.items()}


def protocol_pair(*, elements=64, device="cuda:0"):
    runtime = ProtocolTorch()
    value = torch.arange(elements, dtype=torch.float32)
    return runtime, {"weight": runtime.wrap(value, device)}, {"weight": runtime.wrap(value.clone(), device)}


@pytest.mark.parametrize("optimized", [True, False])
def test_cpu_reference_semantics_preserve_values_bits_rng_and_grad_mode(optimized):
    state, retained = cpu_pair()
    original = {name: value.clone() for name, value in state.items()}
    pointers = {name: value.data_ptr() for name, value in state.items()}
    rng, grad = torch.get_rng_state().clone(), torch.is_grad_enabled()
    actual = subject.check_owned_tensor_bytes(torch, state, retained, optimized=optimized)
    old = reference_guard.check_owned_tensor_values(torch, state, retained, optimized=optimized)
    assert actual["mode"] == old["mode"] == "cpu_reference_checks"
    assert actual["host_decision_count"] == old["host_decision_count"] == 12
    assert actual["comparison_temporary_bound_bytes"] == old["comparison_temporary_bound_bytes"]
    assert actual["state_and_reference_bytes"] == 88
    assert actual["finite_values_checked"] and actual["signed_zero_checked"]
    assert actual["all_current_values_checked"] and not actual["cuda_integer_view_equality"]
    assert not actual["native_cuda_qualified"] and not actual["performance_qualified"]
    assert not actual["mutation_revision_authority"] and not actual["proof_authority"]
    assert torch.equal(rng, torch.get_rng_state()) and torch.is_grad_enabled() == grad
    assert all(value.data_ptr() == pointers[name]
               and torch.equal(value.reshape(-1).view(torch.int32), original[name].reshape(-1).view(torch.int32))
               for name, value in state.items())


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("bad", [0., .125, float("nan"), float("inf"), -float("inf")])
def test_cpu_direct_data_mutation_refuses_without_version_authority(optimized, bad):
    state, retained = cpu_pair()
    before = state["weight"]._version
    state["weight"].data[0, 1] = bad
    assert state["weight"]._version == before
    with pytest.raises(ValueError, match="values, signed zeros or finite"):
        subject.check_owned_tensor_bytes(torch, state, retained, optimized=optimized)


@pytest.mark.parametrize("bits", [0x7FC00001, 0xFFC00001, 0x7F800000, 0xFF800000])
def test_cpu_matching_nonfinite_state_and_reference_refuse(bits):
    value = from_bits([bits])
    with pytest.raises(ValueError, match="finite"):
        subject.check_owned_tensor_bytes(torch, {"weight": value}, {"weight": value.clone()})


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("current_bits,retained_bits", [
    (1, 2), (0x80000001, 0x80000002), (1, 0), (0x80000001, 0x80000000)])
def test_cpu_smallest_subnormal_changes_preserve_numeric_reference_semantics(optimized, current_bits, retained_bits):
    current, retained = from_bits([current_bits]), from_bits([retained_bits])
    assert current.view(torch.int32).item() != retained.view(torch.int32).item()
    state, reference = {"weight": current}, {"weight": retained}

    def accepts(check):
        try:
            check(torch, state, reference, optimized=optimized)
        except ValueError:
            return False
        return True

    # The CPU/opt-out contract preserves numeric comparisons, including the
    # caller's denormal policy. Do not assume that host flushing is disabled.
    assert accepts(subject.check_owned_tensor_bytes) == accepts(reference_guard.check_owned_tensor_values)


def test_protocol_every_chunk_reinterprets_bits_and_makes_one_host_decision():
    runtime, state, retained = protocol_pair()
    actual = subject.check_owned_tensor_bytes(runtime, state, retained, max_temporary_bytes=128)
    assert actual["mode"] == "cuda_bitwise_single_host_decision"
    assert actual["host_decision_count"] == runtime.host_decisions == 1
    assert runtime.equal_calls == 0 and "signbit" not in runtime.calls
    assert runtime.eq_elements == [8] * 8
    assert runtime.calls.count("view") == 16
    assert runtime.calls.count("isfinite") == runtime.calls.count("logical_and") == 8
    assert runtime.calls.count("stack") == 1
    assert actual["comparison_chunk_elements"] == 8
    assert actual["comparison_reduction_scalars"] == 8
    assert actual["comparison_temporary_bound_bytes"] == 96
    assert actual["cuda_current_finiteness_implied_by_reference_bits"]
    assert not actual["native_cuda_qualified"] and not actual["performance_qualified"]


@pytest.mark.parametrize("position", [0, 7, 8, 31, 63])
@pytest.mark.parametrize("bad", [999., float("nan"), float("inf"), -float("inf")])
def test_protocol_changed_bits_in_any_chunk_refuse_after_all_chunks(position, bad):
    runtime, state, retained = protocol_pair()
    state["weight"].value.data[position] = bad
    with pytest.raises(ValueError, match="values, signed zeros or finite"):
        subject.check_owned_tensor_bytes(runtime, state, retained, max_temporary_bytes=128)
    assert runtime.eq_elements == [8] * 8
    assert runtime.host_decisions == 1 and runtime.equal_calls == 0


@pytest.mark.parametrize("state_bits,reference_bits", [
    (0, 0x80000000), (0x80000000, 0), (1, 2), (0x80000001, 0x80000002),
    (0x3F800000, 0x3F800001), (0xBF800000, 0xBF800001),
    (0x7FC00001, 0x7FC00001), (0x7FC00001, 0x7FC00002),
    (0xFFC00001, 0xFFC00001), (0x7F800000, 0x7F800000),
    (0xFF800000, 0xFF800000), (0x7F800000, 0xFF800000)])
def test_protocol_exact_zero_subnormal_finite_and_nonfinite_bit_refusals(state_bits, reference_bits):
    runtime = ProtocolTorch()
    state = {"weight": runtime.wrap(from_bits([state_bits]))}
    retained = {"weight": runtime.wrap(from_bits([reference_bits]))}
    with pytest.raises(ValueError, match="values, signed zeros or finite"):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.host_decisions == 1 and runtime.eq_elements == [1]


def test_protocol_matching_finite_extreme_bits_and_multiple_shapes_succeed():
    runtime = ProtocolTorch()
    cpu_state, cpu_reference = cpu_pair()
    state = {name: runtime.wrap(value) for name, value in cpu_state.items()}
    retained = {name: runtime.wrap(value) for name, value in cpu_reference.items()}
    actual = subject.check_owned_tensor_bytes(runtime, state, retained)
    assert actual["tensor_count"] == actual["comparison_reduction_scalars"] == 3
    assert actual["state_and_reference_bytes"] == 88
    assert runtime.eq_elements == [10, 1, 0] and runtime.host_decisions == 1


def test_protocol_finite_reference_mutation_and_paired_nonfinite_mutation_refuse():
    runtime, state, retained = protocol_pair()
    retained["weight"].value.data[-1] = .125
    with pytest.raises(ValueError, match="values"):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.host_decisions == 1
    runtime, state, retained = protocol_pair()
    state["weight"].value.data[-1] = retained["weight"].value.data[-1] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.host_decisions == 1


@pytest.mark.parametrize("device,optimized,mode", [
    ("cuda:0", False, "cuda_reference_checks"),
    ("cpu", False, "cpu_reference_checks"), ("cpu", True, "cpu_reference_checks")])
def test_protocol_cpu_or_optout_preserves_numeric_reference_path(device, optimized, mode):
    runtime, state, retained = protocol_pair(device=device)
    actual = subject.check_owned_tensor_bytes(runtime, state, retained, optimized=optimized)
    assert actual["mode"] == mode
    assert runtime.equal_calls == 2 and runtime.host_decisions == actual["host_decision_count"] == 4
    assert "view" not in runtime.calls and "eq" not in runtime.calls and "stack" not in runtime.calls


@pytest.mark.parametrize("kwargs", [
    {"optimized": 1}, {"max_tensors": True}, {"max_tensors": 0},
    {"max_tensors": subject.MAX_TENSORS + 1}, {"max_total_bytes": 0},
    {"max_total_bytes": 511}, {"max_total_bytes": subject.MAX_STATE_BYTES + 1},
    {"max_temporary_bytes": 0}, {"max_temporary_bytes": 1},
    {"max_temporary_bytes": subject.MAX_TEMPORARY_BYTES + 1}])
def test_invalid_limits_refuse_before_any_views_or_comparison(kwargs):
    runtime, state, retained = protocol_pair()
    with pytest.raises(ValueError):
        subject.check_owned_tensor_bytes(runtime, state, retained, **kwargs)
    assert runtime.calls == [] and runtime.host_decisions == 0


@pytest.mark.parametrize("fault", ["empty_state", "missing_key", "nonstring_key", "not_tensor",
    "mixed_devices", "unsupported_device", "wrong_dtype", "wrong_shape", "noncontiguous", "alias", "lazy_negative"])
def test_unsupported_metadata_refuses_before_any_views_or_comparison(fault):
    runtime, state, retained = protocol_pair()
    if fault == "empty_state":
        state, retained = {}, {}
    elif fault == "missing_key":
        retained = {"other": retained["weight"]}
    elif fault == "nonstring_key":
        state, retained = {1: state["weight"]}, {1: retained["weight"]}
    elif fault == "not_tensor":
        state["weight"] = 123
    elif fault == "mixed_devices":
        state["second"] = runtime.wrap(torch.ones(1), "cuda:1")
        retained["second"] = runtime.wrap(torch.ones(1), "cuda:1")
    elif fault == "unsupported_device":
        state["weight"].device = retained["weight"].device = ProtocolDevice("mps")
    elif fault == "wrong_dtype":
        retained["weight"].value = retained["weight"].value.double()
    elif fault == "wrong_shape":
        retained["weight"].value = retained["weight"].value.reshape(8, 8)
    elif fault == "noncontiguous":
        state["weight"].value = torch.arange(128, dtype=torch.float32)[::2]
        retained["weight"].value = torch.arange(128, dtype=torch.float32)[::2]
    elif fault == "alias":
        retained["weight"].value = state["weight"].value.view(-1)
    else:
        state["weight"].value = torch._neg_view(state["weight"].value)
        retained["weight"].value = torch._neg_view(retained["weight"].value)
    with pytest.raises(ValueError):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0


def test_late_bad_metadata_prevents_earlier_valid_tensor_views():
    runtime, state, retained = protocol_pair()
    state["late"] = runtime.wrap(torch.ones(1))
    retained["late"] = runtime.wrap(torch.ones(1, dtype=torch.float64))
    with pytest.raises(ValueError, match="float32"):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0


def test_cpu_reference_temporary_bound_refuses_before_predicates(monkeypatch):
    state, retained = cpu_pair()
    monkeypatch.setattr(torch, "isfinite", lambda value: pytest.fail("premature comparison"))
    with pytest.raises(ValueError, match="temporary"):
        subject.check_owned_tensor_bytes(torch, state, retained, max_temporary_bytes=32)


def test_reduction_scalar_limit_refuses_before_views_or_comparison():
    runtime, state, retained = protocol_pair(elements=subject.MAX_REDUCTION_SCALARS + 1)
    with pytest.raises(ValueError, match="temporary"):
        subject.check_owned_tensor_bytes(runtime, state, retained, max_temporary_bytes=16)
    assert runtime.calls == [] and runtime.host_decisions == 0


def test_source_drift_refuses_before_any_tensor_operation(monkeypatch):
    runtime, state, retained = protocol_pair()
    monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
    with pytest.raises(ValueError, match="source changed"):
        subject.check_owned_tensor_bytes(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0
