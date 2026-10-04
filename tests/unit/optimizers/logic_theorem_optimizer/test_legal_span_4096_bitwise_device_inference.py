"""CPU-only no-fit controls for the separate native4096 bitwise session."""
from copy import deepcopy
from dataclasses import replace
import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_device_inference as inherited
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_bitwise_device_inference as subject
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
    examples = [{"id": "explicit-synthetic-bitwise-4096-control", "source_text": "Lark must retain books.",
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


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_separate_cpu_batched_session_preserves_baseline_decisions_and_checkpoint(checkpoint, scheduler, monkeypatch, ablation):
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    texts, vectors = inputs()
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors, latent_ablation=ablation)
        with inherited.DeviceLeanstral4096SpanSession(checkpoint,
                expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), optimized=True,
                synthetic_unreceipted=True, scheduler=scheduler) as baseline:
            expected = baseline.infer(texts, vectors, latent_ablation=ablation)
        assert actual["rows"] == expected["rows"]
        assert actual["schema"] == inherited.SCHEMA == subject.SCHEMA
        assert actual["input_dimension"] == session._model.latent_down.in_features == 4096
        assert actual["actual_forward_batches"] == expected["actual_forward_batches"]
        assert actual["execution_profile"]["session_profile_id"] == subject.PROFILE
        assert actual["execution_profile"]["profile_id"] == subject.PROFILE
        assert actual["execution_profile"]["inherited_profile_id"] == inherited.PROFILE
        assert actual["execution_profile"]["strict_cuda_gru_profile_id"] == inherited.CUDA_GRU_PROFILE
        assert actual["execution_profile"]["owned_tensor_guard_path"] == "inherited_numeric_reference_checks"
        assert actual["execution_profile"]["owned_tensor_currentness"]["schema"] == bitwise_guard.SCHEMA
        assert not actual["execution_profile"]["boundary_consolidation_performed"]
        assert not actual["execution_profile"]["bitwise_session_performance_qualified"]
        assert not actual["production_admission"] and not actual["native_leanstral_head_qualified"]
        assert session.checkpoint == checkpoint
        assert torch.equal(rng, torch.get_rng_state())
    assert before == span._raw(checkpoint) and scheduler.active_leases() == []


def test_cpu_opt_out_preserves_inherited_profile_and_never_queries_cuda(checkpoint, scheduler, monkeypatch):
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
        assert actual["rows"] == expected["rows"]
        profile = actual["execution_profile"]
        assert profile["profile_id"] == profile["inherited_profile_id"] == inherited.PROFILE
        assert profile["session_profile_id"] == subject.PROFILE
        assert profile["numerical_batching"] == "singleton_cpu_opt_out"
        assert profile["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert profile["owned_tensor_guard_path"] == "inherited_numeric_reference_checks"
        assert len(actual["actual_forward_batches"]) == 2 and not actual["numerical_batching"]


@pytest.mark.parametrize("fault", ["weight", "reference", "paired_finite", "paired_signed_zero", "pointer",
    "anchor", "checkpoint", "training", "gradient", "hook", "decoder", "lease"])
def test_separate_session_retains_complete_custody_refusals(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        parameter = session._model.latent_up.bias
        initial, retained = parameter.detach().clone(), session._reference["latent_up.bias"].clone()
        original_pointers, original_anchor = deepcopy(session._pointers), session._reference_anchor
        original_checkpoint = deepcopy(session._checkpoint)
        original_decoder, original_memory = session._decoder.model, session._lease.memory_mb
        handle = None
        try:
            if fault == "weight":
                parameter.data[0] = .125
            elif fault == "reference":
                session._reference["latent_up.bias"].data[0] = .125
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
            elif fault == "decoder":
                session._decoder.model = None
            else:
                session._lease.memory_mb += 1
            with pytest.raises(ValueError):
                session.infer(*inputs())
            assert session._observations == [] and not session._active
        finally:
            parameter.data.copy_(initial)
            session._reference["latent_up.bias"].data.copy_(retained)
            session._pointers, session._reference_anchor = original_pointers, original_anchor
            session._checkpoint.clear()
            session._checkpoint.update(original_checkpoint)
            session._decoder.model, session._lease.memory_mb = original_decoder, original_memory
            parameter.grad = None
            session._model.eval()
            if handle is not None:
                handle.remove()


@pytest.mark.parametrize("mutation", ["finite", "signed_zero"])
def test_paired_reference_mutation_after_forward_retains_exit_refusal(checkpoint, scheduler, monkeypatch, mutation):
    class MutatingCancellation:
        session, changed = None, False
        def is_set(self):
            if self.session is not None and self.session._observations and not self.changed:
                parameter = self.session._model.latent_up.bias
                reference = self.session._reference["latent_up.bias"]
                parameter.data[0] = reference.data[0] = .125 if mutation == "finite" else -.0
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
            assert cancellation.changed and session._observations == [] and not session._active
        finally:
            parameter.data.copy_(initial)
            session._reference["latent_up.bias"].data.copy_(retained)


@pytest.mark.parametrize("fault", ["inherited_class", "inherited_check", "inherited_description", "new_guard", "source"])
def test_original_class_method_and_new_guard_source_bindings_refuse(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        if fault == "inherited_class":
            monkeypatch.setattr(inherited, "DeviceLeanstral4096SpanSession", object)
        elif fault == "inherited_check":
            monkeypatch.setattr(inherited.DeviceLeanstral4096SpanSession, "_pure_check", lambda self: None)
        elif fault == "inherited_description":
            monkeypatch.setattr(inherited.DeviceLeanstral4096SpanSession, "_description", lambda self: {})
        elif fault == "new_guard":
            monkeypatch.setattr(bitwise_guard, "check_owned_tensor_bytes", lambda *args, **kwargs: {})
        else:
            monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
        with pytest.raises(ValueError, match="changed"):
            session.describe()


def test_default_keeps_synthetic_and_native_owner_admission_closed(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with subject.BitwiseDeviceLeanstral4096SpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler) as session:
        assert session.describe()["optimized"] is True
        assert not session.describe()["synthetic_unreceipted_enabled"]
        with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
            session.infer(*inputs())
    assert scheduler.active_leases() == []


def test_inference_never_constructs_optimizer_or_fits(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("inference attempted optimizer construction or fitting")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(head, "train_decoder", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(*inputs())
        assert not actual["training_executed"] and actual["model_state_unchanged"]


def test_late_input_callback_mutation_still_refuses_before_return(checkpoint, scheduler, monkeypatch):
    texts, vectors = inputs()
    class MutatingCancellation:
        armed = False
        def is_set(self):
            if self.armed:
                vectors[0][0] = .9
                self.armed = False
            return False
    cancellation = MutatingCancellation()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancellation) as session:
        cancellation.armed = True
        with pytest.raises(ValueError, match="content changed"):
            session.infer(texts, vectors)
        assert session._observations == [] and not session._active
