"""Real host backend flag controls with protocol-only CUDA synchronization.

These tests exercise Torch's CPU-host CuDNN configuration contexts. A recorder
stands in for CUDA synchronization; no CUDA tensors or kernels are executed.
The optional native CPU session uses an authored tiny checkpoint, not training
evidence or qualified published embeddings.
"""
from types import SimpleNamespace

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_inference as subject
from test_legal_span_device_inference import checkpoint, scheduler, one_thread, open_cpu


CUDNN_FIELDS = ("enabled", "benchmark", "benchmark_limit", "deterministic", "allow_tf32")


def backend_state():
    cudnn = {name: getattr(torch.backends.cudnn, name) for name in CUDNN_FIELDS}
    for name in ("fp32_precision", "depthwise_kernel"):
        if hasattr(torch.backends.cudnn, name):
            cudnn[name] = getattr(torch.backends.cudnn, name)
    return {"cudnn": cudnn,
            "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "float32_matmul_precision": torch.get_float32_matmul_precision()}


@pytest.fixture(autouse=True)
def preserve_host_backend_settings():
    """Restore every configuration field even after an intentional fault."""
    original = backend_state()
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    try:
        yield
    finally:
        for name, value in original["cudnn"].items():
            setattr(torch.backends.cudnn, name, value)
        torch.set_float32_matmul_precision(original["float32_matmul_precision"])
        torch.backends.cuda.matmul.allow_tf32 = original["cuda_matmul_allow_tf32"]
        assert backend_state() == original


def authored_ambient_flags():
    # Deliberately nondefault values catch a context that silently resets other
    # settings while temporarily disabling recurrent CuDNN TF32.
    values = {"enabled": False, "benchmark": True, "benchmark_limit": 7,
              "deterministic": True, "allow_tf32": True}
    for name, value in values.items():
        setattr(torch.backends.cudnn, name, value)
    return values


class ProtocolCudaTorch:
    """Delegate real backend state; replace only CUDA synchronization."""
    def __init__(self, synchronize):
        self.cuda = SimpleNamespace(synchronize=synchronize)

    def __getattr__(self, name):
        return getattr(torch, name)


def test_protocol_cuda_context_preserves_real_host_flags_and_syncs_before_restoration():
    authored_ambient_flags()
    before = backend_state()
    synchronization = []
    runtime = ProtocolCudaTorch(lambda device: synchronization.append((device, backend_state())))
    ambient = subject._precision_policy(runtime)
    with subject._strict_cuda_gru(runtime, "cuda:3", ambient) as actual:
        inside = backend_state()
        assert inside == {**before, "cudnn": {**before["cudnn"], "allow_tf32": False}}
        assert actual == {
            "profile_id": subject.CUDA_GRU_PROFILE, "device": "cuda:3", "scoped_cudnn": True,
            "ambient_policy": before, "effective_policy": inside,
            "synchronized_before_restore": False, "ambient_flags_restored": False,
            "persistent_flags_mutated": False,
            "requires_owned_process_without_unrelated_concurrent_cudnn": True}
        assert actual["effective_policy"] == subject._precision_policy(runtime)
        assert synchronization == []
    assert synchronization == [("cuda:3", inside)]
    assert backend_state() == before
    assert actual["synchronized_before_restore"] is True
    assert actual["ambient_flags_restored"] is True
    assert ambient == before


def test_optional_native_cudnn_fields_are_preserved_by_explicit_skip_kwargs(monkeypatch):
    authored_ambient_flags()
    optional = {name: getattr(torch.backends.cudnn, name)
                for name in ("fp32_precision", "depthwise_kernel")
                if hasattr(torch.backends.cudnn, name)}
    assert optional, "this Torch profile must expose optional native CuDNN settings"
    # The installed Python API delegates valid depthwise values to native code.
    # Use admitted current values rather than inventing an unverified enum.
    for name, value in optional.items():
        setattr(torch.backends.cudnn, name, value)
    before = backend_state()
    context_calls, synchronization = [], []
    original_flags = torch.backends.cudnn.flags
    def record_flags(**kwargs):
        context_calls.append(dict(kwargs))
        return original_flags(**kwargs)
    monkeypatch.setattr(torch.backends.cudnn, "flags", record_flags)
    runtime = ProtocolCudaTorch(lambda device: synchronization.append((device, backend_state())))
    ambient = subject._precision_policy(runtime)
    with subject._strict_cuda_gru(runtime, "cuda:3", ambient) as actual:
        expected = {**before, "cudnn": {**before["cudnn"], "allow_tf32": False}}
        assert backend_state() == expected
        assert actual["effective_policy"] == expected
        assert {name: actual["effective_policy"]["cudnn"][name] for name in optional} == optional
    assert context_calls == [{**before["cudnn"], "allow_tf32": False,
                              **{name: None for name in optional}}]
    assert synchronization == [("cuda:3", expected)]
    assert backend_state() == before
    assert actual["synchronized_before_restore"] is True
    assert actual["ambient_flags_restored"] is True


def test_protocol_cuda_forward_error_still_syncs_inside_context_and_restores_flags():
    authored_ambient_flags()
    before = backend_state()
    synchronization = []
    runtime = ProtocolCudaTorch(lambda device: synchronization.append((device, backend_state())))
    ambient = subject._precision_policy(runtime)
    original = RuntimeError("authored forward failure")
    with pytest.raises(RuntimeError) as observed:
        with subject._strict_cuda_gru(runtime, "cuda:3", ambient) as actual:
            raise original
    assert observed.value is original
    assert synchronization == [("cuda:3", {**before,
        "cudnn": {**before["cudnn"], "allow_tf32": False}})]
    assert backend_state() == before
    assert actual["synchronized_before_restore"] is True
    assert actual["ambient_flags_restored"] is True


def test_protocol_cuda_synchronization_error_cannot_leave_host_flags_modified():
    authored_ambient_flags()
    before = backend_state()
    synchronization = []
    original = RuntimeError("authored synchronization failure")
    def fail(device):
        synchronization.append((device, backend_state()))
        raise original
    runtime = ProtocolCudaTorch(fail)
    with pytest.raises(RuntimeError) as observed:
        with subject._strict_cuda_gru(runtime, "cuda:3", subject._precision_policy(runtime)) as actual:
            pass
    assert observed.value is original
    assert synchronization == [("cuda:3", {**before,
        "cudnn": {**before["cudnn"], "allow_tf32": False}})]
    assert backend_state() == before
    assert actual["synchronized_before_restore"] is False
    assert actual["ambient_flags_restored"] is True


@pytest.mark.parametrize("field", CUDNN_FIELDS)
def test_changed_ambient_cudnn_flags_refuse_before_protocol_cuda_context(field):
    authored_ambient_flags()
    synchronization = []
    runtime = ProtocolCudaTorch(lambda device: synchronization.append(device))
    ambient = subject._precision_policy(runtime)
    value = getattr(torch.backends.cudnn, field)
    setattr(torch.backends.cudnn, field, value + 1 if type(value) is int else not value)
    changed = backend_state()
    with pytest.raises(ValueError):
        with subject._strict_cuda_gru(runtime, "cuda:3", ambient):
            pytest.fail("changed ambient policy reached the forward body")
    assert synchronization == []
    assert backend_state() == changed


@pytest.mark.parametrize("field", CUDNN_FIELDS)
def test_cudnn_policy_mutation_during_protocol_cuda_context_is_detected_and_restored(field):
    authored_ambient_flags()
    before = backend_state()
    synchronization = []
    runtime = ProtocolCudaTorch(lambda device: synchronization.append((device, backend_state())))
    ambient = subject._precision_policy(runtime)
    with pytest.raises(ValueError):
        with subject._strict_cuda_gru(runtime, "cuda:3", ambient):
            value = getattr(torch.backends.cudnn, field)
            setattr(torch.backends.cudnn, field, value + 1 if type(value) is int else not value)
    assert len(synchronization) == 1 and synchronization[0][0] == "cuda:3"
    assert backend_state() == before


@pytest.mark.parametrize("fault", ["matmul_tf32", "matmul_precision", "cuda_autocast"])
def test_strict_float32_policy_changes_during_protocol_cuda_context_are_rejected(fault):
    authored_ambient_flags()
    before = backend_state()
    synchronization = []
    runtime = ProtocolCudaTorch(lambda device: synchronization.append((device, backend_state())))
    autocast = {"active": False}
    runtime.is_autocast_enabled = lambda device: device == "cuda" and autocast["active"]
    ambient = subject._precision_policy(runtime)
    with pytest.raises(ValueError):
        with subject._strict_cuda_gru(runtime, "cuda:3", ambient):
            if fault == "matmul_tf32":
                torch.backends.cuda.matmul.allow_tf32 = True
            elif fault == "matmul_precision":
                torch.set_float32_matmul_precision("high")
            else:
                autocast["active"] = True
    assert len(synchronization) == 1 and synchronization[0][0] == "cuda:3"
    assert synchronization[0][1]["cudnn"] == {**before["cudnn"], "allow_tf32": False}
    assert backend_state()["cudnn"] == before["cudnn"]


def test_strict_cuda_float32_policy_rejects_real_matmul_tf32():
    torch.backends.cuda.matmul.allow_tf32 = True
    with pytest.raises(ValueError):
        subject._cuda_float32_policy(torch)


@pytest.mark.parametrize("precision", ["high", "medium"])
def test_strict_cuda_float32_policy_rejects_reduced_real_matmul_precision(precision):
    torch.set_float32_matmul_precision(precision)
    with pytest.raises(ValueError):
        subject._cuda_float32_policy(torch)


def test_strict_cuda_float32_policy_rejects_real_cpu_autocast():
    with torch.autocast("cpu", dtype=torch.bfloat16):
        assert torch.is_autocast_enabled("cpu")
        with pytest.raises(ValueError):
            subject._cuda_float32_policy(torch)


def test_strict_cuda_float32_policy_rejects_protocol_cuda_autocast_only(monkeypatch):
    runtime = ProtocolCudaTorch(lambda device: pytest.fail("autocast guard synchronized"))
    monkeypatch.setattr(runtime, "is_autocast_enabled", lambda device: device == "cuda", raising=False)
    with pytest.raises(ValueError):
        subject._cuda_float32_policy(runtime)


def test_cpu_context_preserves_permissive_ambient_policy_without_flags_or_cuda(monkeypatch):
    authored_ambient_flags()
    torch.set_float32_matmul_precision("high")
    before = backend_state()
    assert before["float32_matmul_precision"] == "high"
    assert before["cuda_matmul_allow_tf32"] is True
    runtime = ProtocolCudaTorch(lambda device: pytest.fail("CPU context synchronized CUDA"))
    ambient = subject._precision_policy(runtime)
    monkeypatch.setattr(torch.backends.cudnn, "flags",
                        lambda **kwargs: pytest.fail("CPU context changed CuDNN flags"))
    with subject._strict_cuda_gru(runtime, "cpu", ambient) as actual:
        assert actual == {"profile_id": subject.PROFILE, "scoped_cudnn": False,
                          "persistent_flags_mutated": False, "device": "cpu"}
        assert backend_state() == before
    assert backend_state() == before


def test_tiny_cpu_session_keeps_opt_out_and_reports_actual_gru_policy(checkpoint, scheduler, monkeypatch):
    authored_ambient_flags()
    torch.set_float32_matmul_precision("high")
    before = backend_state()
    assert before["float32_matmul_precision"] == "high"
    assert before["cuda_matmul_allow_tf32"] is True
    def forbidden(*args, **kwargs):
        pytest.fail("CPU opt-out touched CUDA or the CuDNN flag context")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.cuda, "synchronize", forbidden)
    monkeypatch.setattr(torch.backends.cudnn, "flags", forbidden)
    with open_cpu(checkpoint, scheduler) as session:
        description = session.describe()
        assert description["profile_id"] == subject.PROFILE
        assert description["device"] == "cpu" and description["optimized"] is False
        assert description["precision_policy"] == {
            "ambient_at_admission": None, "cuda_gru_allow_tf32": None,
            "cuda_matmul_allow_tf32": None, "float32_matmul_precision": None,
            "persistent_flags_mutated": False,
            "requires_owned_process_without_unrelated_concurrent_cudnn": False}
        result = session.infer(["Lark must retain books."], [[.1] * 768])
        assert result["cuda_executed"] is False
        assert len(result["actual_forward_batches"]) == 1
        forward = result["actual_forward_batches"][0]
        assert forward["input_device"] == "cpu" and forward["gru_executed"] is True
        assert forward["gru_precision"] == {
            "profile_id": subject.PROFILE, "scoped_cudnn": False,
            "persistent_flags_mutated": False, "device": "cpu"}
        assert backend_state() == before
    assert backend_state() == before
    assert scheduler.active_leases() == []


def test_tiny_cpu_opt_out_does_not_query_cuda_matmul_precision(checkpoint, scheduler, monkeypatch):
    torch.set_float32_matmul_precision("high")
    def forbidden(*args, **kwargs):
        pytest.fail("CPU opt-out queried CUDA matmul precision")
    with monkeypatch.context() as local:
        local.setattr(torch, "get_float32_matmul_precision", forbidden)
        with open_cpu(checkpoint, scheduler) as session:
            assert session.describe()["precision_policy"]["ambient_at_admission"] is None
            result = session.infer(["Lark must retain books."], [[.1] * 768])
            assert result["cuda_executed"] is False
            assert len(result["actual_forward_batches"]) == 1
            assert result["actual_forward_batches"][0]["gru_precision"] == {
                "profile_id": subject.PROFILE, "scoped_cudnn": False,
                "persistent_flags_mutated": False, "device": "cpu"}
    assert scheduler.active_leases() == []
