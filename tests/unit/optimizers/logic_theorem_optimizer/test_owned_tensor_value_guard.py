"""Exact CPU checks and protocol-only CUDA host-decision instrumentation.

Every numerical tensor lives on CPU. The protocol runtime labels those tensors
as CUDA solely to count scalar decisions and inspect bounded comparison work;
it supplies no native CUDA, model, checkpoint, inference or proof evidence.
"""
import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_value_guard as subject


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

    def untyped_storage(self):
        return self.value.untyped_storage()

    def reshape(self, *shape):
        self.runtime.calls.append("reshape")
        return ProtocolTensor(self.runtime, self.value.reshape(*shape), str(self.device))

    def __getitem__(self, item):
        self.runtime.calls.append("slice")
        return ProtocolTensor(self.runtime, self.value[item], str(self.device))

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
    Tensor, float32, strided = ProtocolTensor, torch.float32, torch.strided

    def __init__(self):
        self.calls, self.host_decisions, self.equal_calls, self.eq_elements = [], 0, 0, []

    def wrap(self, value, device="cuda:0"):
        return ProtocolTensor(self, value, device)

    def eq(self, left, right):
        self.calls.append("eq")
        self.eq_elements.append(left.numel())
        return self.wrap(torch.eq(left.value, right.value), str(left.device))

    def signbit(self, value):
        self.calls.append("signbit")
        return self.wrap(torch.signbit(value.value), str(value.device))

    def isfinite(self, value):
        self.calls.append("isfinite")
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
        raise AssertionError("exact elementwise checks must not consult autocast")


def cpu_pair():
    state = {"weight": torch.tensor([[1., -0., 3.], [4., 5., 6.]], dtype=torch.float32),
             "bias": torch.tensor(.5, dtype=torch.float32),
             "empty": torch.empty(0, dtype=torch.float32)}
    return state, {name: value.detach().clone() for name, value in state.items()}


def protocol_pair(*, elements=16, device="cuda:0"):
    runtime = ProtocolTorch()
    value = torch.arange(elements, dtype=torch.float32)
    return runtime, {"weight": runtime.wrap(value, device)}, {"weight": runtime.wrap(value.clone(), device)}


@pytest.mark.parametrize("optimized", [True, False])
def test_real_cpu_exact_success_preserves_inputs_rng_and_grad_mode(optimized):
    state, retained = cpu_pair()
    originals = {name: value.clone() for name, value in state.items()}
    pointers = {name: value.data_ptr() for name, value in state.items()}
    rng, grad = torch.get_rng_state().clone(), torch.is_grad_enabled()
    actual = subject.check_owned_tensor_values(torch, state, retained, optimized=optimized)
    assert actual["mode"] == "cpu_reference_checks"
    assert actual["host_decision_count"] == 12
    assert actual["state_and_reference_bytes"] == 56
    assert actual["finite_values_checked"] and actual["signed_zero_checked"]
    assert actual["all_current_values_checked"]
    assert not actual["mutation_revision_authority"]
    assert not actual["autocast_configuration_consulted"]
    assert not actual["proof_authority"] and not actual["native_cuda_qualified"]
    assert torch.equal(rng, torch.get_rng_state()) and torch.is_grad_enabled() == grad
    assert all(value.data_ptr() == pointers[name] and torch.equal(value, originals[name])
               and torch.equal(torch.signbit(value), torch.signbit(originals[name]))
               for name, value in state.items())


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("mutation", ["value", "signed_zero", "nan", "positive_inf", "negative_inf"])
def test_real_cpu_direct_data_mutation_refuses_without_revision_authority(optimized, mutation):
    state, retained = cpu_pair()
    before = state["weight"]._version
    replacement = {"value": 7., "signed_zero": 0., "nan": float("nan"),
                   "positive_inf": float("inf"), "negative_inf": -float("inf")}[mutation]
    state["weight"].data[0, 1] = replacement
    assert state["weight"]._version == before
    with pytest.raises(ValueError, match="values, signed zeros or finite"):
        subject.check_owned_tensor_values(torch, state, retained, optimized=optimized)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_real_cpu_matching_corrupt_reference_is_not_authority(bad):
    value = torch.tensor([bad], dtype=torch.float32)
    with pytest.raises(ValueError, match="finite"):
        subject.check_owned_tensor_values(torch, {"weight": value}, {"weight": value.clone()})


def test_protocol_cuda_all_values_and_chunks_make_exactly_one_host_decision():
    runtime, state, retained = protocol_pair(elements=64)
    actual = subject.check_owned_tensor_values(runtime, state, retained, max_temporary_bytes=128)
    assert actual["mode"] == "cuda_single_host_decision"
    assert actual["host_decision_count"] == runtime.host_decisions == 1
    assert runtime.equal_calls == 0
    assert actual["comparison_chunk_elements"] == 8
    assert actual["comparison_reduction_scalars"] == 8
    assert actual["comparison_temporary_bound_bytes"] <= 128
    assert len(runtime.eq_elements) == 16 and max(runtime.eq_elements) == 8
    assert runtime.calls.count("stack") == 1
    assert actual["comparison_device"] == "cuda:0"
    assert not actual["native_cuda_qualified"]


@pytest.mark.parametrize("position", [0, 7, 8, 31, 63])
@pytest.mark.parametrize("bad", [999., float("nan"), float("inf"), -float("inf")])
def test_protocol_cuda_mutation_in_any_chunk_refuses_with_one_host_decision(position, bad):
    runtime, state, retained = protocol_pair(elements=64)
    state["weight"].value.data[position] = bad
    with pytest.raises(ValueError, match="values, signed zeros or finite"):
        subject.check_owned_tensor_values(runtime, state, retained, max_temporary_bytes=128)
    assert runtime.host_decisions == 1 and runtime.equal_calls == 0
    assert runtime.calls.count("stack") == 1


def test_protocol_cuda_signed_zero_and_retained_reference_mutation_refuse():
    runtime, state, retained = protocol_pair()
    state["weight"].value.data[0] = -0.
    with pytest.raises(ValueError, match="signed zeros"):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.host_decisions == 1
    runtime, state, retained = protocol_pair()
    retained["weight"].value.data[-1] = -123.
    with pytest.raises(ValueError, match="values"):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.host_decisions == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_protocol_cuda_matching_corrupt_state_and_reference_refuse(bad):
    runtime, state, retained = protocol_pair()
    state["weight"].value.data[-1] = retained["weight"].value.data[-1] = bad
    with pytest.raises(ValueError, match="finite"):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.host_decisions == 1


def test_protocol_cuda_multiple_shapes_and_empty_tensor_are_covered():
    runtime = ProtocolTorch()
    values = {"matrix": torch.arange(12, dtype=torch.float32).reshape(3, 4),
              "scalar": torch.tensor(-0., dtype=torch.float32), "empty": torch.empty(0)}
    state = {name: runtime.wrap(value) for name, value in values.items()}
    retained = {name: runtime.wrap(value.clone()) for name, value in values.items()}
    actual = subject.check_owned_tensor_values(runtime, state, retained)
    assert actual["tensor_count"] == 3 and actual["state_and_reference_bytes"] == 104
    assert actual["comparison_reduction_scalars"] == 3
    assert runtime.host_decisions == 1


@pytest.mark.parametrize("device,optimized,mode", [
    ("cuda:0", False, "cuda_reference_checks"),
    ("cpu", False, "cpu_reference_checks"),
    ("cpu", True, "cpu_reference_checks")])
def test_protocol_optout_or_cpu_retains_equal_and_signbit_reference_path(device, optimized, mode):
    runtime, state, retained = protocol_pair(device=device)
    actual = subject.check_owned_tensor_values(runtime, state, retained, optimized=optimized)
    assert actual["mode"] == mode
    assert runtime.equal_calls == 2 and runtime.host_decisions == actual["host_decision_count"] == 4
    assert "eq" not in runtime.calls and "stack" not in runtime.calls


@pytest.mark.parametrize("kwargs", [
    {"optimized": 1}, {"max_tensors": True}, {"max_tensors": 0},
    {"max_tensors": subject.MAX_TENSORS + 1}, {"max_total_bytes": 0},
    {"max_total_bytes": 127}, {"max_total_bytes": subject.MAX_STATE_BYTES + 1},
    {"max_temporary_bytes": 0}, {"max_temporary_bytes": 1},
    {"max_temporary_bytes": subject.MAX_TEMPORARY_BYTES + 1}])
def test_protocol_invalid_limits_refuse_before_any_comparison_or_flatten(kwargs):
    runtime, state, retained = protocol_pair()
    with pytest.raises(ValueError):
        subject.check_owned_tensor_values(runtime, state, retained, **kwargs)
    assert runtime.calls == [] and runtime.host_decisions == 0


@pytest.mark.parametrize("fault", ["empty_state", "missing_key", "nonstring_key", "not_tensor",
    "mixed_devices", "unsupported_device", "wrong_dtype", "wrong_shape", "noncontiguous", "alias"])
def test_protocol_unsupported_metadata_refuses_before_intermediates(fault):
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
        retained["weight"].value = retained["weight"].value.reshape(4, 4)
    elif fault == "noncontiguous":
        state["weight"].value = torch.arange(32, dtype=torch.float32)[::2]
        retained["weight"].value = torch.arange(32, dtype=torch.float32)[::2]
    elif fault == "alias":
        retained["weight"].value = state["weight"].value.view(-1)
    with pytest.raises(ValueError):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0


def test_late_bad_metadata_prevents_even_earlier_valid_tensor_comparison():
    runtime, state, retained = protocol_pair()
    state["late"] = runtime.wrap(torch.ones(1))
    retained["late"] = runtime.wrap(torch.ones(1, dtype=torch.float64))
    with pytest.raises(ValueError, match="float32"):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0


def test_cpu_reference_temporary_bound_is_checked_before_operations(monkeypatch):
    state, retained = cpu_pair()
    monkeypatch.setattr(torch, "isfinite", lambda value: pytest.fail("premature comparison"))
    with pytest.raises(ValueError, match="temporary"):
        subject.check_owned_tensor_values(torch, state, retained, max_temporary_bytes=32)


def test_source_drift_refuses_before_tensor_operation(monkeypatch):
    runtime, state, retained = protocol_pair()
    monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
    with pytest.raises(ValueError, match="source changed"):
        subject.check_owned_tensor_values(runtime, state, retained)
    assert runtime.calls == [] and runtime.host_decisions == 0
