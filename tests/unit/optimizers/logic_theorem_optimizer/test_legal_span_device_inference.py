"""Small synthetic protocol controls; no fitting, encoders, or model downloads.

Saved positive step counts below deliberately construct structurally valid test
fixtures. They are not training evidence or qualified native768 embeddings.
"""
from copy import deepcopy
import hashlib
import json
import threading
import weakref

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_inference as device
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLane, ResourceSchedulerConfig)


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def moments(state):
    return {"schema": "adam-default-betas-eps/v1", "parameters": {
        name: {"step": 1, "exp_avg": torch.zeros_like(torch.tensor(value)).tolist(),
               "exp_avg_sq": torch.zeros_like(torch.tensor(value)).tolist()}
        for name, value in state.items()}}


@pytest.fixture(scope="module")
def checkpoint():
    base_config = span._config(latent_dimension=0, latent_enabled=False, learning_rate=.003,
        batch_size=1, seed=1729, hidden_size=8, embedding_dim=4, projection_width=4, residual_scale=.25)
    base_model = device._fresh_model(torch, base_config)
    base_state = {name: value.detach().tolist() for name, value in base_model.state_dict().items()}
    parent = {"schema": span.SCHEMA, "lineage_id": span.LINEAGE_ID, "config": base_config,
        "implementation": span._implementation(), "training_manifest_sha256": "a" * 64,
        "training_count": 1, "tuning_manifest_sha256": "b" * 64, "tuning_count": 0,
        "model_state": base_state, "optimizer_state": moments(base_state),
        "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
        "parent_checkpoint_sha256": "c" * 64, **span.FALSE}
    config = dims._config(latent_dimension=768, latent_enabled=True, learning_rate=.003,
        batch_size=1, seed=1729, hidden_size=8, embedding_dim=4, projection_width=4, residual_scale=.25)
    model = device._fresh_model(torch, config)
    state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    state.update(deepcopy(base_state))
    context = {"dimension": 768, "representation_id": "synthetic-native768-test-only",
               "producer_sha256": "d" * 64, "training_index_sha256": "e" * 64}
    return {"schema": dims.SCHEMA, "lineage_id": dims.LINEAGE_ID,
        "implementation": dims._implementation(), "initialization": deepcopy(dims._INITIALIZATION),
        "config": config, "context_contract": context,
        "context_contract_sha256": span.checkpoint_digest(context), "source_parent_checkpoint": parent,
        "source_parent_checkpoint_sha256": span.checkpoint_digest(parent), "source_parent_optimizer_steps": 1,
        "initial_source_model_sha256": span.checkpoint_digest(dims._source_state(state)),
        "initial_model_state_sha256": span.checkpoint_digest(state),
        "training_manifest_sha256": "f" * 64, "training_count": 1,
        "tuning_manifest_sha256": "a" * 64, "tuning_count": 0,
        "model_state": state, "optimizer_state": moments(state),
        "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
        "parent_checkpoint_sha256": "b" * 64, **span.FALSE}


@pytest.fixture
def scheduler(tmp_path):
    return GlobalResourceScheduler(ResourceSchedulerConfig(state_path=tmp_path / "resource.json",
        total_cpu_slots=2, total_memory_mb=4096, total_gpu_memory_mb=2048,
        total_unified_memory_mb=4096, lane_reservations={}, auto_renew_leases=False,
        resource_pressure_sampler=lambda: {"gpu_telemetry_available": True,
            "cuda_available": True, "gpu_device_count": 1, "gpu_memory_percent": 0.}))


def open_cpu(checkpoint, scheduler, **kwargs):
    return device.DeviceDimensionalSpanSession(checkpoint,
        expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), optimized=False,
        scheduler=scheduler, **kwargs)


def cpu_reference(checkpoint, texts, vectors, ablation="none"):
    # Restore through the new CPU-only construction seam, then use the genuine
    # inherited CPU decision method without its CUDA-seeding constructor.
    native = span.SpanLegalFormulaDecoder.__new__(span.SpanLegalFormulaDecoder)
    native.torch, native.model = torch, device._restore(torch, deepcopy(checkpoint)).eval()
    native.checkpoint, native.checkpoint_sha256 = deepcopy(checkpoint), span.checkpoint_digest(checkpoint)
    if ablation == "zero":
        vectors = [[0.] * 768 for _ in vectors]
    elif ablation == "rotate":
        vectors = vectors[1:] + vectors[:1]
    return [span.SpanLegalFormulaDecoder._decode(native, text, vector, enabled=ablation != "disabled")
            for text, vector in zip(texts, vectors)]


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_exact_cpu_canonical_decisions_preserve_checkpoint_adam_and_rng(checkpoint, scheduler, ablation):
    texts = ["Lark must retain the books.", "Wren may publish records."]
    vectors = [[.1] * 768, [.2] * 768]
    before = span._raw(checkpoint)
    rng = torch.get_rng_state().clone()
    with open_cpu(checkpoint, scheduler) as session:
        assert torch.equal(torch.get_rng_state(), rng)
        result = session.infer(texts, vectors, latent_ablation=ablation)
        assert result["rows"] == cpu_reference(checkpoint, texts, vectors, ablation)
        assert result["input_dimension"] == 768
        assert result["execution_profile"]["device"] == "cpu"
        assert result["execution_profile"]["stored_checkpoint_device"] == "cpu"
        assert result["execution_profile"]["checkpoint_conversion_performed"] is False
        assert result["execution_profile"]["optimizer_state_sha256"] == span.checkpoint_digest(checkpoint["optimizer_state"])
        assert result["input_receipts"]["native_encoder_inputs_authenticated"] is False
        assert result["cuda_executed"] is False
        assert len(result["actual_forward_batches"]) == 2
        assert all(row["input_device"] == "cpu" and row["gru_executed"] for row in result["actual_forward_batches"])
        assert all(result[name] is False for name in span.FALSE)
        assert session.checkpoint == checkpoint
        assert torch.equal(torch.get_rng_state(), rng)
    assert span._raw(checkpoint) == before
    assert scheduler.active_leases() == []


def test_no_optimizer_or_training_object_is_constructed(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("inference attempted fitting/optimizer construction")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(dims, "train_decoder", forbidden)
    with open_cpu(checkpoint, scheduler) as session:
        assert session.infer(["Source only."], [[.1] * 768])["training_executed"] is False


def test_cpu_opt_out_does_not_probe_or_seed_cuda(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU opt-out touched CUDA or global seeding")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", forbidden)
    monkeypatch.setattr(torch, "manual_seed", forbidden)
    with open_cpu(checkpoint, scheduler) as session:
        assert session.infer(["Lark must retain books."], [[.1] * 768])["cuda_executed"] is False


def test_default_cpu_when_cuda_unavailable(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with device.DeviceDimensionalSpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler) as session:
        assert session.describe()["optimized"] is True
        assert session.describe()["device"] == "cpu"


@pytest.mark.parametrize("mutation,match", [
    (lambda cp: cp.update(qualified=True), "closed"),
    (lambda cp: cp["context_contract"].update(dimension=384), "dimension"),
    (lambda cp: cp["source_parent_checkpoint"]["optimizer_state"]["parameters"]["modality.bias"].update(step=2), "optimizer step"),
    (lambda cp: cp["optimizer_state"]["parameters"]["modality.bias"].update(step=2), "optimizer step"),
    (lambda cp: cp["optimizer_state"]["parameters"]["modality.bias"]["exp_avg_sq"].__setitem__(0, -1.), "finite"),
    (lambda cp: cp.update(initial_source_model_sha256="0" * 64), "boundary"),
    (lambda cp: cp["implementation"].update(dimensions_sha256="0" * 64), "implementation"),
    (lambda cp: cp["model_state"].update(extra=[0.]), "keys"),
    (lambda cp: cp["progress"].update(optimizer_steps=True), "progress"),
    (lambda cp: cp["model_state"]["modality.bias"].__setitem__(0, .123456789), "serialization"),
])
def test_corrupted_checkpoint_closes_lease_before_any_inference(checkpoint, scheduler, mutation, match):
    cp = deepcopy(checkpoint)
    mutation(cp)
    with pytest.raises(ValueError, match=match):
        open_cpu(cp, scheduler)
    assert scheduler.active_leases() == []


def test_exact_external_checkpoint_pin_is_required(checkpoint, scheduler):
    with pytest.raises(ValueError, match="SHA"):
        device.DeviceDimensionalSpanSession(checkpoint, expected_checkpoint_sha256="0" * 64,
                                           optimized=False, scheduler=scheduler)
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("fault", ["parameter", "signed_zero", "storage", "gradient", "mode", "checkpoint", "torch", "forward", "nested_forward", "hook"])
def test_private_mutation_fences_before_next_forward(checkpoint, scheduler, fault):
    session = open_cpu(checkpoint, scheduler)
    if fault == "parameter":
        session._model.modality.bias.data.add_(1.)
    elif fault == "signed_zero":
        session._model.latent_up.bias.data[0] = -0.
    elif fault == "storage":
        session._model.modality.bias.data = session._model.modality.bias.data.clone()
    elif fault == "gradient":
        session._model.modality.bias.grad = torch.zeros_like(session._model.modality.bias)
    elif fault == "mode":
        session._model.encoder.train()
    elif fault == "checkpoint":
        session._checkpoint["optimizer_state"]["parameters"]["modality.bias"]["exp_avg"][0] = 1.
    elif fault == "torch":
        session._tensor_factory._device = "cuda:99"
    elif fault == "forward":
        session._model.forward = lambda *args, **kwargs: {}
    elif fault == "nested_forward":
        session._model.encoder.forward = lambda *args, **kwargs: None
    else:
        session._model.modality.register_forward_hook(lambda *args: None)
    try:
        with pytest.raises((ValueError, AttributeError)):
            session.infer(["Lark must retain books."], [[.1] * 768])
        assert session._observations == []
    finally:
        session.close()
    assert scheduler.active_leases() == []


def test_caller_checkpoint_mutation_cannot_change_resident_session(checkpoint, scheduler):
    cp = deepcopy(checkpoint)
    with open_cpu(cp, scheduler) as session:
        expected = session.infer(["Lark must retain books."], [[.1] * 768])
        cp["config"]["latent_enabled"] = False
        cp["optimizer_state"]["parameters"]["modality.bias"]["exp_avg"][0] = 1.
        assert session.infer(["Lark must retain books."], [[.1] * 768])["rows"] == expected["rows"]


def receipt(text, vector, device_profile=False):
    result = {"schema": "gte-multilingual-embedding-receipt/v1", "id": "synthetic-0",
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "profile_id": "synthetic-native768-test-only", "dimension": 768, "embedding": list(vector),
        "token_count_including_special_tokens": 8, "token_input_sha256": "a" * 64,
        "truncated": False, "normalized": True, "asset_manifest_sha256": "b" * 64}
    if device_profile:
        result.update(schema="gte-native-device-embedding-receipt/v1", device="cuda:0", dtype="float32",
            profile_sha256="d" * 64,
            embedding_sha256=hashlib.sha256(json.dumps(vector, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
            proof_authority=False, source_semantics_verified=False)
    return result


@pytest.mark.parametrize("device_profile", [False, True])
def test_externally_pinned_source_receipts_are_content_binding_only(checkpoint, scheduler, device_profile):
    text, vector = "Lark must retain books.", [1.] + [0.] * 767
    rec = receipt(text, vector, device_profile)
    with open_cpu(checkpoint, scheduler) as session:
        result = session.infer([text], [vector], embedding_receipts=[rec],
                               expected_receipt_sha256s=[span.checkpoint_digest(rec)])
    assert result["input_receipts"]["native_encoder_inputs_authenticated"] is True
    assert result["input_receipts"]["signature_verified"] is False
    assert result["proof_authority"] is result["semantic_correctness_verified"] is False


@pytest.mark.parametrize("mutation", [
    lambda rec: rec.update(source_sha256="c" * 64), lambda rec: rec.update(dimension=True),
    lambda rec: rec.update(profile_id="old-profile-relabelled"), lambda rec: rec.update(truncated=True),
    lambda rec: rec.update(normalized=False), lambda rec: rec.update(token_count_including_special_tokens=True),
    lambda rec: rec.update(token_input_sha256="bad"), lambda rec: rec.update(extra_target={}),
    lambda rec: rec["embedding"].__setitem__(0, .5), lambda rec: rec.update(proof_authority=True),
    lambda rec: rec.update(device="cuda:arbitrary"), lambda rec: rec.update(dtype="float16"),
    lambda rec: rec.update(embedding_sha256="0" * 64),
    lambda rec: rec.update(profile_sha256="not-a-profile-hash"),
    lambda rec: rec.update(profile_sha256="0" * 64),
])
def test_coherently_rehashed_wrong_receipts_do_not_execute(checkpoint, scheduler, mutation):
    text, vector = "Lark must retain books.", [1.] + [0.] * 767
    rec = receipt(text, vector, True)
    mutation(rec)
    with open_cpu(checkpoint, scheduler) as session:
        with pytest.raises(ValueError):
            session.infer([text], [vector], embedding_receipts=[rec],
                          expected_receipt_sha256s=[span.checkpoint_digest(rec)])
        assert session._observations == []


def test_receipt_wrong_external_pin_and_unmatched_pin_presence_fail(checkpoint, scheduler):
    text, vector = "Lark must retain books.", [1.] + [0.] * 767
    with open_cpu(checkpoint, scheduler) as session:
        with pytest.raises(ValueError, match="pin differs"):
            session.infer([text], [vector], embedding_receipts=[receipt(text, vector)],
                          expected_receipt_sha256s=["0" * 64])
        with pytest.raises(ValueError, match="complete"):
            session.infer([text], [vector], expected_receipt_sha256s=["0" * 64])


def test_pre_and_late_cancellation_and_deadline(checkpoint, scheduler, monkeypatch):
    signal = threading.Event()
    signal.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        open_cpu(checkpoint, scheduler, cancel_event=signal)
    assert scheduler.active_leases() == []
    signal.clear()
    session = open_cpu(checkpoint, scheduler, cancel_event=signal)
    signal.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        session.infer(["Source."], [[.1] * 768])
    session.close()
    session = open_cpu(checkpoint, scheduler)
    session._deadline = 0.
    with pytest.raises(TimeoutError, match="deadline"):
        session.infer(["Source."], [[.1] * 768])
    session.close()
    assert scheduler.active_leases() == []


def test_revoked_parent_refuses_child_and_close_does_not_release_foreign_parent(checkpoint, scheduler):
    parent = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=2048)
    session = open_cpu(checkpoint, scheduler, parent_lease=parent)
    assert len(scheduler.active_leases()) == 2
    session.close()
    assert len(scheduler.active_leases()) == 1 and not parent.released
    parent.cancel()
    with pytest.raises(Exception):
        open_cpu(checkpoint, scheduler, parent_lease=parent, admission_timeout_seconds=.01)
    parent.release()
    assert scheduler.active_leases() == []


def test_close_releases_private_tensors_and_is_idempotent(checkpoint, scheduler):
    session = open_cpu(checkpoint, scheduler)
    model = weakref.ref(session._model)
    session.close()
    assert model() is None
    session.close()
    with pytest.raises(ValueError, match="closed"):
        session.infer(["Source."], [[.1] * 768])
    assert scheduler.active_leases() == []


def test_late_source_callback_mutation_fails_after_forward(checkpoint, scheduler):
    session = open_cpu(checkpoint, scheduler)
    class Signal:
        calls = 0
        def is_set(self):
            self.calls += 1
            if self.calls == 4:
                session._checkpoint["optimizer_state"]["parameters"]["modality.bias"]["exp_avg"][0] = 1.
            return False
    session._cancel = Signal()
    try:
        with pytest.raises(ValueError, match="checkpoint"):
            session.infer(["Lark must retain books."], [[.1] * 768])
    finally:
        session.close()
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("operation", ["infer", "describe", "checkpoint", "close"])
def test_cross_thread_operations_refuse_and_retain_owner_lease(checkpoint, scheduler, operation):
    session = open_cpu(checkpoint, scheduler)
    errors = []
    def foreign():
        try:
            if operation == "infer":
                session.infer(["Source."], [[.1] * 768])
            elif operation == "checkpoint":
                _ = session.checkpoint
            else:
                getattr(session, operation)()
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=foreign)
    worker.start()
    worker.join(5.)
    assert not worker.is_alive() and len(errors) == 1
    assert isinstance(errors[0], ValueError) and "thread" in str(errors[0])
    assert len(scheduler.active_leases()) == 1
    assert session.infer(["Source."], [[.1] * 768])["training_executed"] is False
    session.close()
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("operation", ["infer", "describe", "checkpoint", "close"])
def test_cancellation_callback_reentry_refuses_before_nested_forward(checkpoint, scheduler, operation):
    session = open_cpu(checkpoint, scheduler)
    class Signal:
        attempted = False
        def is_set(self):
            self.attempted = True
            if operation == "infer":
                session.infer(["Nested source."], [[.1] * 768])
            elif operation == "checkpoint":
                _ = session.checkpoint
            else:
                getattr(session, operation)()
            return False
    signal = Signal()
    session._cancel = signal
    try:
        with pytest.raises(ValueError, match="already active"):
            session.infer(["Source."], [[.1] * 768])
        assert signal.attempted and session._observations == []
        assert len(scheduler.active_leases()) == 1
    finally:
        session._cancel = None
        session.close()
    assert scheduler.active_leases() == []


def test_checkpoint_subclasses_refuse_without_callbacks(checkpoint, scheduler):
    class Malicious(dict):
        called = False
        def __deepcopy__(self, memo):
            self.called = True
            raise AssertionError("custom deepcopy executed")
    cp = Malicious(checkpoint)
    with pytest.raises(ValueError, match="plain"):
        open_cpu(cp, scheduler)
    assert not cp.called and scheduler.active_leases() == []


@pytest.mark.parametrize("kwargs", [{"optimized": 1}, {"max_seconds": True}, {"max_seconds": 601},
    {"memory_mb": 1023}, {"gpu_memory_mb": True}, {"unified_memory_mb": -1},
    {"admission_timeout_seconds": 0}])
def test_exact_control_types(checkpoint, scheduler, kwargs):
    options = {"optimized": False, **kwargs}
    with pytest.raises(ValueError):
        device.DeviceDimensionalSpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler, **options)
    assert scheduler.active_leases() == []


def test_actual_cuda_refuses_unknown_telemetry_before_model_allocation(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "current_device", lambda: 0)
    scheduler.config.resource_pressure_sampler = lambda: {"gpu_telemetry_available": False, "cuda_available": False}
    def forbidden(*args, **kwargs):
        raise AssertionError("unadmitted GPU request constructed model")
    monkeypatch.setattr(device, "_restore", forbidden)
    monkeypatch.setattr(device.DeviceDimensionalSpanSession, "_synchronize", lambda self: None)
    with pytest.raises(Exception):
        device.DeviceDimensionalSpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler,
            admission_timeout_seconds=.01)
    assert scheduler.active_leases() == []
