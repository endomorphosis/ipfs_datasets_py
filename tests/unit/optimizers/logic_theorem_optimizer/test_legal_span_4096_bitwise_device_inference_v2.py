"""CPU no-fit custody and verifier-call controls for the separate v2 session."""
import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_device_inference as inherited
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_bitwise_device_inference_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_bitwise_guard as bitwise_guard
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig)


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    examples = [{"id": "explicit-synthetic-bitwise-v2-4096-control", "source_text": "Lark must retain books.",
        "latent": [.1] * 4096,
        "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O", "action": "retain", "object": "books",
                                   "conditions": [], "exceptions": [], "temporal": []}]}}]
    context = {"dimension": 4096, "representation_id": "synthetic-4096-untrained-architecture-control",
               "producer_sha256": "a" * 64, "training_index_sha256": "b" * 64}
    return head.build_synthetic_fixture(examples, context_contract=context, hidden_size=8,
        embedding_dim=4, projection_width=4, batch_size=1, seed=1729)


@pytest.fixture
def scheduler(tmp_path):
    return GlobalResourceScheduler(ResourceSchedulerConfig(state_path=tmp_path / "resource.json",
        total_cpu_slots=2, total_memory_mb=4096, total_gpu_memory_mb=2048,
        total_unified_memory_mb=4096, lane_reservations={}, auto_renew_leases=False,
        resource_pressure_sampler=lambda: {"gpu_telemetry_available": True,
            "cuda_available": True, "gpu_device_count": 1, "gpu_memory_percent": 0.}))


def open_cpu(checkpoint, scheduler, monkeypatch, *, optimized=True, **kwargs):
    if optimized:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return subject.BitwiseDeviceLeanstral4096SpanSession(checkpoint,
        expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), optimized=optimized,
        synthetic_unreceipted=True, scheduler=scheduler, **kwargs)


def inputs():
    return ["Lark must retain books.", "Wren may publish records."], [[.1] * 4096, [.2] * 4096]


@pytest.mark.parametrize("method,original_calls", [("_check", 1), ("_pure_check", 0), ("_description", 1)])
def test_real_verifier_call_counts_have_no_duplicate_transitive_check(checkpoint, scheduler, monkeypatch, method, original_calls):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        codes = {inherited._implementation.__code__: "original",
                 bitwise_guard.inference_implementation.__code__: "comparison"}
        calls = {"original": 0, "comparison": 0}
        previous = sys.getprofile()

        def trace(frame, event, arg):
            if event == "call" and frame.f_code in codes:
                calls[codes[frame.f_code]] += 1

        try:
            sys.setprofile(trace)
            getattr(session, method)()
        finally:
            sys.setprofile(previous)
        assert calls == {"original": original_calls, "comparison": 1}


def test_independent_implementation_verifies_both_sources_once():
    codes = {inherited._implementation.__code__: "original",
             bitwise_guard.inference_implementation.__code__: "comparison"}
    calls, previous = {"original": 0, "comparison": 0}, sys.getprofile()

    def trace(frame, event, arg):
        if event == "call" and frame.f_code in codes:
            calls[codes[frame.f_code]] += 1

    try:
        sys.setprofile(trace)
        actual = subject._implementation()
    finally:
        sys.setprofile(previous)
    assert calls == {"original": 1, "comparison": 1}
    assert actual["schema"] == "native-4096-bitwise-device-session-implementation/v2"
    assert not actual["source_verification_success_cached"]
    assert not actual["duplicate_transitive_verification_in_pure_check"]


def test_original_custody_guard_ast_differs_only_in_comparator_and_own_binding_check():
    def method(path):
        tree = ast.parse(Path(path).read_text())
        return next(item for cls in tree.body if isinstance(cls, ast.ClassDef)
                    for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "_pure_check")

    original, candidate = method(inherited.__file__), method(subject.__file__)
    first = candidate.body.pop(0)
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name) and first.value.func.id == "_check_bindings"

    class Normalize(ast.NodeTransformer):
        def visit_Attribute(self, node):
            node = self.generic_visit(node)
            if isinstance(node.value, ast.Name) and node.value.id == "inherited" and node.attr == "resident":
                return ast.Name(id="resident", ctx=ast.Load())
            return node

        def visit_Name(self, node):
            if node.id == "_BITWISE_CHECK_AT_IMPORT":
                node.id = "_VALUE_GUARD_AT_IMPORT"
            return node

    assert ast.dump(original, include_attributes=False) == ast.dump(Normalize().visit(candidate), include_attributes=False)


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_cpu_batches_preserve_exact_original_decisions(checkpoint, scheduler, monkeypatch, ablation):
    texts, vectors = inputs()
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors, latent_ablation=ablation)
        with inherited.DeviceLeanstral4096SpanSession(checkpoint,
                expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), optimized=True,
                synthetic_unreceipted=True, scheduler=scheduler) as baseline:
            expected = baseline.infer(texts, vectors, latent_ablation=ablation)
        assert actual["rows"] == expected["rows"]
        assert actual["actual_forward_batches"] == expected["actual_forward_batches"]
        assert actual["schema"] == inherited.SCHEMA and actual["input_dimension"] == 4096
        profile = actual["execution_profile"]
        assert profile["profile_id"] == profile["session_profile_id"] == subject.PROFILE
        assert profile["inherited_profile_id"] == inherited.PROFILE
        assert profile["strict_cuda_gru_profile_id"] == inherited.CUDA_GRU_PROFILE
        assert profile["owned_tensor_currentness"]["schema"] == bitwise_guard.SCHEMA
        assert not profile["boundary_consolidation_performed"]
        assert not actual["production_admission"] and not actual["training_executed"]
        assert torch.equal(rng, torch.get_rng_state())
    assert span._raw(checkpoint) == before and scheduler.active_leases() == []


def test_cpu_opt_out_keeps_profile_singletons_and_never_queries_cuda(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU opt-out touched CUDA or global seeding")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", forbidden)
    monkeypatch.setattr(torch, "manual_seed", forbidden)
    texts, vectors = inputs()
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=False) as session:
        actual = session.infer(texts, vectors)
        expected = head.Leanstral4096SpanDecoder(checkpoint).decode_formal_logic(texts, vectors)
        assert actual["rows"] == expected["rows"] and not actual["numerical_batching"]
        assert len(actual["actual_forward_batches"]) == 2
        assert actual["execution_profile"]["profile_id"] == inherited.PROFILE
        assert actual["execution_profile"]["session_profile_id"] == subject.PROFILE
        assert actual["execution_profile"]["owned_tensor_guard_path"] == "inherited_numeric_reference_checks"


@pytest.mark.parametrize("fault", ["own_source", "original_method", "helper_function", "helper_source", "original_dependency"])
def test_public_entry_refuses_current_source_or_callable_drift(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        if fault == "own_source":
            monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
        elif fault == "original_method":
            monkeypatch.setattr(inherited.DeviceLeanstral4096SpanSession, "_pure_check", lambda self: None)
        elif fault == "helper_function":
            monkeypatch.setattr(bitwise_guard, "check_owned_tensor_bytes", lambda *args, **kwargs: {})
        elif fault == "helper_source":
            monkeypatch.setattr(bitwise_guard, "_source_sha256", lambda: "0" * 64)
        else:
            monkeypatch.setattr(inherited.head, "_implementation", lambda: {})
        with pytest.raises(ValueError, match="changed"):
            session.infer(*inputs())
        assert session._observations == [] and not session._active


@pytest.mark.parametrize("fault", ["weight", "paired_finite", "paired_signed_zero", "pointer", "anchor", "checkpoint",
    "training", "gradient", "hook", "lease"])
def test_all_original_custody_refusals_remain(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        parameter = session._model.latent_up.bias
        initial, retained = parameter.detach().clone(), session._reference["latent_up.bias"].clone()
        original_pointer, original_anchor = session._pointers["latent_up.bias"], session._reference_anchor
        original_checkpoint, original_memory = deepcopy(session._checkpoint), session._lease.memory_mb
        handle = None
        try:
            if fault == "weight":
                parameter.data[0] = .125
            elif fault == "paired_finite":
                parameter.data[0] = session._reference["latent_up.bias"].data[0] = .125
            elif fault == "paired_signed_zero":
                parameter.data[0] = session._reference["latent_up.bias"].data[0] = -.0
            elif fault == "pointer":
                session._pointers["latent_up.bias"] += 4
            elif fault == "anchor":
                session._reference_anchor = replace(original_anchor)
            elif fault == "checkpoint":
                session._checkpoint["config"]["seed"] += 1
            elif fault == "training":
                session._model.train()
            elif fault == "gradient":
                parameter.grad = torch.zeros_like(parameter)
            elif fault == "hook":
                handle = session._model.register_forward_hook(lambda *_: None)
            else:
                session._lease.memory_mb += 1
            with pytest.raises(ValueError):
                session.infer(*inputs())
            assert session._observations == [] and not session._active
        finally:
            parameter.data.copy_(initial)
            session._reference["latent_up.bias"].data.copy_(retained)
            session._pointers["latent_up.bias"], session._reference_anchor = original_pointer, original_anchor
            session._checkpoint.clear()
            session._checkpoint.update(original_checkpoint)
            session._lease.memory_mb, parameter.grad = original_memory, None
            session._model.eval()
            if handle is not None:
                handle.remove()


def test_post_forward_paired_reference_mutation_still_refuses(checkpoint, scheduler, monkeypatch):
    class MutatingCancellation:
        session, changed = None, False
        def is_set(self):
            if self.session is not None and self.session._observations and not self.changed:
                self.session._model.latent_up.bias.data[0] = .125
                self.session._reference["latent_up.bias"].data[0] = .125
                self.changed = True
            return False
    cancellation = MutatingCancellation()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancellation) as session:
        parameter = session._model.latent_up.bias
        initial, retained = parameter.detach().clone(), session._reference["latent_up.bias"].clone()
        cancellation.session = session
        try:
            with pytest.raises(ValueError, match="reference bytes changed from admitted checkpoint"):
                session.infer(*inputs())
            assert cancellation.changed and session._observations == []
        finally:
            parameter.data.copy_(initial)
            session._reference["latent_up.bias"].data.copy_(retained)


def test_default_preserves_native_owner_refusal(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with subject.BitwiseDeviceLeanstral4096SpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler) as session:
        assert session.describe()["optimized"] is True
        assert not session.describe()["synthetic_unreceipted_enabled"]
        with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
            session.infer(*inputs())
    assert scheduler.active_leases() == []
