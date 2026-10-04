"""No-fit synthetic architecture controls for private actual4096 head inference.

No model weights, encoder, network, native CUDA, or training execution is used.
Saved fixtures explicitly declare untrained synthetic architecture provenance.
"""
from copy import deepcopy
from collections import OrderedDict
from dataclasses import replace
import threading
import weakref

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_device_inference as device
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_batch_inference as batched
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig)


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def examples():
    return [{"id": "explicit-synthetic-4096-fixture", "source_text": "Lark must retain books.",
        "latent": [.1] * 4096,
        "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O", "action": "retain", "object": "books",
                                   "conditions": [], "exceptions": [], "temporal": []}]}}]


def context():
    return {"dimension": 4096, "representation_id": "synthetic-4096-untrained-architecture-control",
            "producer_sha256": "a" * 64, "training_index_sha256": "b" * 64}


@pytest.fixture(scope="module")
def checkpoint():
    return head.build_synthetic_fixture(examples(), context_contract=context(), hidden_size=8,
        embedding_dim=4, projection_width=4, batch_size=1, seed=1729)


@pytest.fixture
def scheduler(tmp_path):
    return GlobalResourceScheduler(ResourceSchedulerConfig(state_path=tmp_path / "resource.json",
        total_cpu_slots=2, total_memory_mb=4096, total_gpu_memory_mb=2048,
        total_unified_memory_mb=4096, lane_reservations={}, auto_renew_leases=False,
        resource_pressure_sampler=lambda: {"gpu_telemetry_available": True,
            "cuda_available": True, "gpu_device_count": 1, "gpu_memory_percent": 0.}))


def open_cpu(cp, scheduler, monkeypatch, *, optimized=True, **kwargs):
    if optimized:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return device.DeviceLeanstral4096SpanSession(cp,
        expected_checkpoint_sha256=span.checkpoint_digest(cp), optimized=optimized,
        synthetic_unreceipted=True, scheduler=scheduler, **kwargs)


def inputs():
    return (["Lark must retain books.", "Wren may publish the new records next Tuesday.",
             "Finch must not destroy files unless a court grants leave."],
            [[.1] * 4096, [.2] * 4096, [.3] * 4096])


def decisions(rows):
    keys = ("source_sha256", "latent_sha256", "status", "reason", "detail", "canonical_ir",
            "formula_text", "formal_outputs", "family_syntax_checked", "latent_input_enabled")
    return [{name: row.get(name) for name in keys} for row in rows]


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_batched_native4096_decisions_match_unchanged_cpu_kernel(checkpoint, scheduler, monkeypatch, ablation):
    texts, vectors = inputs()
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors, latent_ablation=ablation)
        expected = head.Leanstral4096SpanDecoder(checkpoint).decode_formal_logic(texts, vectors, latent_ablation=ablation)
        assert decisions(actual["rows"]) == decisions(expected["rows"])
        assert actual["schema"] == device.SCHEMA and actual["lineage_id"] == head.LINEAGE_ID
        assert actual["input_dimension"] == session._model.latent_down.in_features == 4096
        assert actual["numerical_batching"] is True
        assert actual["valid_source_count"] == 3
        assert len(actual["actual_forward_batches"]) == 1
        forward = actual["actual_forward_batches"][0]
        assert forward["rows"] == 3 and forward["native_input_dimension"] == 4096
        assert forward["input_device"] == "cpu" and forward["output_dtype"] == "float32"
        assert forward["source_tokens"] == [len(span.tokenize_source(text)) for text in texts]
        assert set(forward["output_devices"].values()) == {"cpu"}
        assert actual["cpu_head_output_materializations"] == 4
        assert actual["device_to_cpu_head_transfers"] == 0 and actual["cuda_executed"] is False
        assert actual["input_receipts"]["native_encoder_inputs_authenticated"] is False
        assert actual["input_receipts"]["synthetic_embeddings"] is True
        assert actual["production_admission"] is actual["native_leanstral_head_qualified"] is False
        assert all(actual[name] is False for name in span.FALSE)
        assert session.checkpoint == checkpoint
        assert session.describe()["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert torch.equal(rng, torch.get_rng_state())
    assert span._raw(checkpoint) == before and scheduler.active_leases() == []


@pytest.mark.parametrize("enabled", [True, False])
def test_all_four_actual4096_batch_logits_match_singletons(checkpoint, scheduler, monkeypatch, enabled):
    texts, vectors = inputs()
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        records = [{"tokens": span.tokenize_source(text), "latent": vector} for text, vector in zip(texts, vectors)]
        native = head._restore_for_inference(torch, deepcopy(checkpoint)).eval()
        with torch.inference_mode():
            together = session._model(*span._batch(session._tensor_factory, records), enabled=enabled)
            for i, record in enumerate(records):
                singleton = native(*span._batch(torch, [record]), enabled=enabled)
                row = batched._row_output(together, i, len(record["tokens"]))
                assert set(row) == {"modality", "presence", "start", "end"}
                assert all(torch.allclose(row[name], singleton[name], atol=2e-6, rtol=1e-5) for name in row)


def test_cpu_opt_out_uses_exact_singletons_and_never_probes_cuda(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU opt-out touched CUDA/global seeding")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", forbidden)
    monkeypatch.setattr(torch, "manual_seed", forbidden)
    texts, vectors = inputs()
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=False) as session:
        actual = session.infer(texts, vectors)
        expected = head.Leanstral4096SpanDecoder(checkpoint).decode_formal_logic(texts, vectors)
        assert actual["rows"] == expected["rows"]
        assert actual["numerical_batching"] is False
        assert len(actual["actual_forward_batches"]) == 3
        assert actual["cpu_head_output_materializations"] == actual["device_to_cpu_head_transfers"] == 0
        assert actual["execution_profile"]["numerical_batching"] == "singleton_cpu_opt_out"


def test_default_optimization_selects_cpu_when_cuda_unavailable(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with device.DeviceLeanstral4096SpanSession(checkpoint,
            expected_checkpoint_sha256=span.checkpoint_digest(checkpoint),
            synthetic_unreceipted=True, scheduler=scheduler) as session:
        assert session.describe()["optimized"] is True
        assert session.describe()["device"] == "cpu"


@pytest.mark.parametrize("optimized,available,initialized,index,expected", [
    (False, True, False, 0, "cpu"),
    (True, False, False, 0, "cpu"),
    (True, True, False, 0, "cuda:0"),
    (True, True, True, 2, "cuda:2"),
])
def test_device_selection_does_not_initialize_cuda_before_admission(optimized, available, initialized, index, expected):
    calls = []
    class InertCuda:
        def is_available(self):
            calls.append("available")
            return available
        def is_initialized(self):
            calls.append("initialized")
            return initialized
        def current_device(self):
            assert initialized, "selection initialized an unadmitted CUDA context"
            calls.append("current")
            return index
    class InertTorch:
        cuda = InertCuda()
    assert device._select_device(InertTorch(), optimized) == expected
    if not optimized:
        assert calls == []
    if not initialized:
        assert "current" not in calls


def test_real_ordered_torch_state_dict_keeps_named_tensors_and_custody(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session._model.state_dict()
        assert type(actual) is OrderedDict
        assert set(actual) == set(checkpoint["model_state"]) == set(session._reference)
        assert all(value.data_ptr() == session._pointers[name] for name, value in actual.items())
        assert session.describe()["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert session.infer(["Lark must retain books."], [[.1] * 4096])["model_state_unchanged"] is True


def test_inference_never_constructs_optimizer_or_trains(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("inference attempted optimizer/fitting")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(head, "train_decoder", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        assert session.infer(["Lark must retain books."], [[.1] * 4096])["training_executed"] is False


@pytest.mark.parametrize("receipt_kind", ["self_pinned_json", "empty_lists", "one_missing_argument"])
def test_production_receipts_cannot_self_authenticate(checkpoint, scheduler, monkeypatch, receipt_kind):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        receipt = {"schema": "leanstral-native-embedding-receipt/v1", "dimension": 4096,
                   "embedding": [.1] * 4096, "trusted_native_owner_verified": True}
        kwargs = ({"embedding_receipts": [receipt], "expected_receipt_sha256s": [span.checkpoint_digest(receipt)]}
            if receipt_kind == "self_pinned_json" else {"embedding_receipts": [], "expected_receipt_sha256s": []}
            if receipt_kind == "empty_lists" else {"embedding_receipts": [receipt]})
        with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
            session.infer(["Lark must retain books."], [[.1] * 4096], **kwargs)
        assert session._observations == []


def test_unreceipted_synthetic_inference_requires_explicit_opt_in(checkpoint, scheduler, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with device.DeviceLeanstral4096SpanSession(checkpoint, expected_checkpoint_sha256=span.checkpoint_digest(checkpoint),
                                             scheduler=scheduler) as session:
        with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
            session.infer(["Lark must retain books."], [[.1] * 4096])
        assert session._observations == []


def test_caller_native_vectors_cannot_be_promoted_by_synthetic_flag(scheduler, monkeypatch):
    native = head.build_checkpoint(examples(), context_contract=context(), hidden_size=8,
                                  embedding_dim=4, projection_width=4, batch_size=1)
    with pytest.raises(ValueError, match="synthetic untrained checkpoint provenance"):
        open_cpu(native, scheduler, monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with device.DeviceLeanstral4096SpanSession(native, expected_checkpoint_sha256=span.checkpoint_digest(native),
                                             scheduler=scheduler) as session:
        with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
            session.infer(["Lark must retain books."], [[.1] * 4096])
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("dimension", [8, 384, 768, 4095, 4097])
def test_complete_actual4096_vectors_reject_padding_or_relabeling(checkpoint, scheduler, monkeypatch, dimension):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        with pytest.raises(ValueError, match="dimension"):
            session.infer(["Lark must retain books."], [[.1] * dimension])
        assert session._observations == []


def test_target_argument_is_not_an_inference_input(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        with pytest.raises(TypeError):
            session.infer(["Source."], [[.1] * 4096], canonical_ir={"rules": []})


def test_invalid_sources_keep_cpu_abstention_reasons_and_order(checkpoint, scheduler, monkeypatch):
    texts = ["", "Lark must retain books.", "word " * 257, "Wren may publish records.", "x" * 16385, "é" * 2049, " "]
    vectors = [[(i + 1) / 10.] * 4096 for i in range(len(texts))]
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors)
        expected = head.Leanstral4096SpanDecoder(checkpoint).decode_formal_logic(texts, vectors)
        assert decisions(actual["rows"]) == decisions(expected["rows"])
        assert actual["valid_source_count"] == actual["actual_forward_batches"][0]["rows"] == 2


def test_all_invalid_sources_perform_no_numerical_forward(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(["", " "], [[.1] * 4096, [.2] * 4096])
        assert actual["actual_forward_batches"] == [] and actual["valid_source_count"] == 0
        assert actual["cpu_head_output_materializations"] == 0 and actual["cuda_executed"] is False


def test_over_budget_complete_batch_refuses_before_padded_tensors(checkpoint, scheduler, monkeypatch):
    text = "a" * 2048 + " x" * 255
    assert len(span.tokenize_source(text)) == 256
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        with pytest.raises(ValueError, match="reserved host memory"):
            session.infer([text] * 128, [[.1] * 4096 for _ in range(128)])
        assert session._observations == [] and session._active is False


@pytest.mark.parametrize("mutation", [
    lambda cp: cp.update(schema="native-dimensional-source-span-checkpoint/v1"),
    lambda cp: cp["config"].update(latent_dimension=768),
    lambda cp: cp["context_contract"].update(dimension=768),
    lambda cp: cp["optimizer_state"]["parameters"].update(extra={"step": 1, "exp_avg": [], "exp_avg_sq": []}),
    lambda cp: cp["progress"].update(optimizer_steps=True),
    lambda cp: cp["provenance"].update(trusted_native_owner_verified=True),
    lambda cp: cp.update(initial_model_state_sha256="0" * 64),
    lambda cp: cp.update(proof_authority=True),
])
def test_corrupt_checkpoint_refuses_and_releases_own_lease(checkpoint, scheduler, monkeypatch, mutation):
    cp = deepcopy(checkpoint)
    mutation(cp)
    with pytest.raises(ValueError):
        open_cpu(cp, scheduler, monkeypatch)
    assert scheduler.active_leases() == []


def test_external_checkpoint_pin_is_required_before_admission(checkpoint, scheduler):
    with pytest.raises(ValueError, match="SHA"):
        device.DeviceLeanstral4096SpanSession(checkpoint, expected_checkpoint_sha256="0" * 64,
                                             optimized=False, scheduler=scheduler)
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("fault", ["weight_data", "equal_storage_replacement", "reference", "signed_zero", "nan", "hook", "training", "decoder_binding", "policy", "lease_memory", "paired_finite_data", "paired_signed_zero", "anchor_replacement", "anchor_payload_replacement"])
def test_private_model_custody_and_full_values_are_checked(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        parameter = session._model.latent_up.bias
        original_data, original_value = parameter.data, parameter.detach().clone()
        original_ref, original_policy = session._reference["latent_up.bias"].clone(), session._optimized
        original_memory, original_decoder = session._lease.memory_mb, session._decoder.model
        original_anchor, original_payload = session._reference_anchor, session._reference_anchor.payload
        handle = None
        try:
            if fault == "weight_data":
                parameter.data[0] += .1
            elif fault == "equal_storage_replacement":
                parameter.data = parameter.data.clone()
            elif fault == "reference":
                session._reference["latent_up.bias"][0] += .1
            elif fault == "signed_zero":
                parameter.data[0] = -.0
            elif fault == "nan":
                parameter.data[0] = float("nan")
            elif fault == "hook":
                handle = session._model.register_forward_hook(lambda *args: None)
            elif fault == "training":
                session._model.train()
            elif fault == "decoder_binding":
                session._decoder.model = None
            elif fault == "policy":
                session._optimized = False
            elif fault == "lease_memory":
                session._lease.memory_mb += 1
            elif fault == "paired_finite_data":
                parameter.data[0] = .125
                session._reference["latent_up.bias"].data[0] = .125
                assert torch.equal(parameter, session._reference["latent_up.bias"])
                assert torch.equal(torch.signbit(parameter), torch.signbit(session._reference["latent_up.bias"]))
            elif fault == "paired_signed_zero":
                parameter.data[0] = -.0
                session._reference["latent_up.bias"].data[0] = -.0
                assert torch.equal(parameter, session._reference["latent_up.bias"])
                assert torch.equal(torch.signbit(parameter), torch.signbit(session._reference["latent_up.bias"]))
                assert torch.signbit(parameter[0])
            elif fault == "anchor_replacement":
                session._reference_anchor = replace(original_anchor)
                assert session._reference_anchor == original_anchor and session._reference_anchor is not original_anchor
            else:
                replacement = bytes(bytearray(original_payload))
                assert replacement == original_payload and replacement is not original_payload
                object.__setattr__(original_anchor, "payload", replacement)
            with pytest.raises(ValueError):
                session.infer(["Lark must retain books."], [[.1] * 4096])
            assert session._observations == []
        finally:
            parameter.data = original_data
            parameter.data.copy_(original_value)
            session._reference["latent_up.bias"].copy_(original_ref)
            session._optimized = original_policy
            session._lease.memory_mb, session._decoder.model = original_memory, original_decoder
            session._reference_anchor = original_anchor
            object.__setattr__(original_anchor, "payload", original_payload)
            session._model.eval()
            if handle:
                handle.remove()


@pytest.mark.parametrize("mutation", ["finite", "signed_zero"])
def test_paired_model_and_reference_mutation_after_forward_is_refused_at_exit(checkpoint, scheduler, monkeypatch, mutation):
    class LatePairedMutation:
        session, executed = None, False
        def is_set(self):
            if self.session is not None and self.session._observations and not self.executed:
                parameter = self.session._model.latent_up.bias
                reference = self.session._reference["latent_up.bias"]
                value = .125 if mutation == "finite" else -.0
                parameter.data[0] = reference.data[0] = value
                assert torch.equal(parameter, reference)
                assert torch.equal(torch.signbit(parameter), torch.signbit(reference))
                self.executed = True
            return False
    cancellation = LatePairedMutation()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancellation) as session:
        parameter = session._model.latent_up.bias
        original_value, original_ref = parameter.detach().clone(), session._reference["latent_up.bias"].clone()
        cancellation.session = session
        try:
            with pytest.raises(ValueError, match="reference bytes changed from admitted checkpoint"):
                session.infer(["Lark must retain books."], [[.1] * 4096])
            assert cancellation.executed and session._observations == [] and session._active is False
        finally:
            parameter.data.copy_(original_value)
            session._reference["latent_up.bias"].data.copy_(original_ref)


def test_reference_anchor_is_exact_cpu_checkpoint_bytes_without_weight_json(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        original = head._restore_for_inference(torch, checkpoint)
        state = dict(original.state_dict())
        expected = torch.cat([state[name].detach().reshape(-1).view(torch.uint8)
                              for name in sorted(state)]).numpy().tobytes()
        assert type(session._reference_anchor.payload) is bytes
        assert session._reference_anchor.payload == expected
        assert session._reference_anchor.checkpoint_sha256 == span.checkpoint_digest(checkpoint)
        profile = session.describe()
        assert profile["profile_id"].endswith("/v2")
        assert profile["reference_byte_currentness"]["reference_bytes"] == len(expected)
        assert profile["reference_byte_currentness"]["device_to_cpu_reference_transfers"] == 0
        assert profile["reference_byte_currentness"]["metadata_and_reservation_checked_before_allocation"] is True


def test_reference_anchor_reservation_refuses_before_concatenation(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        original_memory = session._lease.memory_mb
        def forbidden(*args, **kwargs):
            raise AssertionError("reference bytes allocated before reservation admission")
        try:
            session._lease.memory_mb = 1
            with monkeypatch.context() as patch:
                patch.setattr(torch, "cat", forbidden)
                with pytest.raises(ValueError, match="reference anchor exceeds reserved host memory"):
                    session._reference_byte_plan(session._reference, expected_device="cpu")
        finally:
            session._lease.memory_mb = original_memory


def test_implementation_primitive_replacement_refuses(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        with monkeypatch.context() as m:
            m.setattr(device.resident, "_strict_cuda_gru", lambda *args: None)
            with pytest.raises(ValueError, match="primitive identity/source"):
                session.infer(["Lark must retain books."], [[.1] * 4096])


def test_cpu_autocast_refuses_before_forward(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        with torch.autocast("cpu", dtype=torch.bfloat16):
            with pytest.raises(ValueError, match="autocast"):
                session.infer(["Lark must retain books."], [[.1] * 4096])
        assert session._observations == []


def test_cancellation_deadline_and_revoked_lease_refuse_before_forward(checkpoint, scheduler, monkeypatch):
    cancelled = threading.Event()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancelled) as session:
        cancelled.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            session.infer(["Source."], [[.1] * 4096])
        assert session._observations == []
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        session._deadline = 0
        with pytest.raises(TimeoutError, match="deadline"):
            session.infer(["Source."], [[.1] * 4096])
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        session._lease.cancel()
        with pytest.raises(RuntimeError, match="revoked"):
            session.infer(["Source."], [[.1] * 4096])
    assert scheduler.active_leases() == []


def test_foreign_thread_and_nested_operation_cannot_use_or_close_session(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        errors = []
        def foreign():
            for operation in (session.describe, session.close):
                try:
                    operation()
                except ValueError as error:
                    errors.append(str(error))
        thread = threading.Thread(target=foreign)
        thread.start()
        thread.join()
        assert len(errors) == 2 and not session._lease.released
        with session._operation():
            with pytest.raises(ValueError, match="already active"):
                session.describe()
            with pytest.raises(ValueError, match="already active"):
                session.close()


def test_late_input_mutation_cannot_escape_exit_guard(checkpoint, scheduler, monkeypatch):
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
        assert session._active is False and session._observations == []


def test_close_drops_owned_tensors_and_is_idempotent(checkpoint, scheduler, monkeypatch):
    session = open_cpu(checkpoint, scheduler, monkeypatch)
    model = weakref.ref(session._model)
    session.close()
    session.close()
    assert model() is None and session._reference == {} and session._pointers == {}
    assert scheduler.active_leases() == []
    with pytest.raises(ValueError, match="closed"):
        session.describe()
