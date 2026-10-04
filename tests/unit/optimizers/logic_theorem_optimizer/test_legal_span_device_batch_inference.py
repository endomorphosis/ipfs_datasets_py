"""Synthetic no-fit controls for complete batched native768 span inference.

The imported saved-state fixture is synthetic protocol data with no optimizer
execution or encoder call. Numeric/canonical batching does not qualify logic.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import threading

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_inference as resident
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_batch_inference as batch

_fixture_spec = importlib.util.spec_from_file_location("_native768_batch_protocol_fixture",
    Path(__file__).with_name("test_legal_span_device_inference.py"))
if _fixture_spec is None or _fixture_spec.loader is None:
    raise RuntimeError("native768 synthetic protocol fixture is unavailable")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
checkpoint, scheduler, one_thread = (_fixture_module.checkpoint, _fixture_module.scheduler,
                                     _fixture_module.one_thread)
receipt, cpu_reference = _fixture_module.receipt, _fixture_module.cpu_reference


@pytest.fixture
def contextual_checkpoint(checkpoint):
    cp = deepcopy(checkpoint)
    # A nonzero synthetic FiLM boundary makes zero/rotate/disabled controls
    # traverse genuinely different numerical inputs. No training takes place.
    cp["model_state"]["latent_up.weight"] = torch.full((16, 4), .04, dtype=torch.float32).tolist()
    cp["model_state"]["latent_up.bias"] = torch.full((16,), .03, dtype=torch.float32).tolist()
    return cp


def open_batch(cp, scheduler, monkeypatch, *, optimized=True, **kwargs):
    # CPU tests qualify neither GPU availability nor actual CUDA execution.
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return batch.DeviceBatchedDimensionalSpanSession(cp,
        expected_checkpoint_sha256=span.checkpoint_digest(cp), optimized=optimized,
        scheduler=scheduler, **kwargs)


def decisions(rows):
    keys = ("source_sha256", "latent_sha256", "status", "reason", "detail", "canonical_ir",
            "formula_text", "formal_outputs", "family_syntax_checked", "latent_input_enabled")
    return [{name: row.get(name) for name in keys} for row in rows]


def inputs():
    return (["Lark must retain books.", "Wren may publish the new records next Tuesday.",
             "Finch must not destroy files unless a court grants leave."],
            [[.1] * 768, [.2] * 768, [.3] * 768])


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_variable_length_canonical_decisions_and_single_forward(contextual_checkpoint, scheduler, monkeypatch, ablation):
    texts, vectors = inputs()
    before = span._raw(contextual_checkpoint)
    rng = torch.get_rng_state().clone()
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors, latent_ablation=ablation)
        reference = cpu_reference(contextual_checkpoint, texts, vectors, ablation)
        assert decisions(actual["rows"]) == decisions(reference)
        assert actual["schema"] == batch.SCHEMA
        assert actual["valid_source_count"] == 3
        assert len(actual["actual_forward_batches"]) == 1
        assert actual["actual_forward_batches"][0]["rows"] == 3
        assert actual["actual_forward_batches"][0]["source_tokens"] == [len(span.tokenize_source(t)) for t in texts]
        assert actual["canonical_decision_device"] == "cpu"
        assert actual["cpu_head_output_materializations"] == 4
        assert actual["device_to_cpu_head_transfers"] == 0
        assert actual["cuda_executed"] is False
        assert actual["execution_profile"]["numerical_batching"] == "one_complete_valid_source_batch"
        assert actual["execution_profile"]["singleton_numeric_bitwise_parity_claimed"] is False
        for name in span.FALSE:
            assert actual[name] is False
        assert session.checkpoint == contextual_checkpoint
        assert torch.equal(rng, torch.get_rng_state())
    assert span._raw(contextual_checkpoint) == before
    assert scheduler.active_leases() == []


@pytest.mark.parametrize("enabled", [True, False])
def test_all_four_batched_logits_match_native_singletons(contextual_checkpoint, scheduler, monkeypatch, enabled):
    texts, vectors = inputs()
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        records = [{"tokens": span.tokenize_source(text), "latent": vector}
                   for text, vector in zip(texts, vectors)]
        native = resident._restore(torch, deepcopy(contextual_checkpoint)).eval()
        with torch.inference_mode():
            combined = session._model(*span._batch(session._tensor_factory, records), enabled=enabled)
            for i, record in enumerate(records):
                singleton = native(*span._batch(torch, [record]), enabled=enabled)
                trimmed = batch._row_output(combined, i, len(record["tokens"]))
                assert set(trimmed) == {"modality", "presence", "start", "end"}
                assert all(torch.isfinite(value).all() for value in trimmed.values())
                assert all(torch.allclose(trimmed[name], singleton[name], atol=2e-6, rtol=1e-5) for name in trimmed)


def test_opt_out_retains_exact_singleton_cpu_kernel(contextual_checkpoint, scheduler, monkeypatch):
    texts, vectors = inputs()
    with open_batch(contextual_checkpoint, scheduler, monkeypatch, optimized=False) as session:
        actual = session.infer(texts, vectors)
        assert actual["rows"] == cpu_reference(contextual_checkpoint, texts, vectors)
        assert actual["numerical_batching"] is False
        assert actual["execution_profile"]["numerical_batching"] == "singleton_cpu_opt_out"
        assert len(actual["actual_forward_batches"]) == 3
        assert actual["cpu_head_output_materializations"] == actual["device_to_cpu_head_transfers"] == 0


def test_invalid_sources_preserve_inherited_reasons_and_order(contextual_checkpoint, scheduler, monkeypatch):
    texts = ["", "Lark must retain books.", "word " * 257, "Wren may publish records.",
             "x" * 16385, "é" * 2049, " "]
    vectors = [[(i + 1) / 10.] * 768 for i in range(len(texts))]
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors)
        reference = cpu_reference(contextual_checkpoint, texts, vectors)
        assert decisions(actual["rows"]) == decisions(reference)
        assert [row["source_sha256"] for row in actual["rows"]] == [row["source_sha256"] for row in reference]
        assert actual["valid_source_count"] == 2
        assert actual["actual_forward_batches"][0]["rows"] == 2
        assert len(actual["actual_forward_batches"]) == 1


def test_all_invalid_sources_execute_no_forward(contextual_checkpoint, scheduler, monkeypatch):
    texts, vectors = ["", " "], [[.1] * 768, [.2] * 768]
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors)
        assert decisions(actual["rows"]) == decisions(cpu_reference(contextual_checkpoint, texts, vectors))
        assert actual["actual_forward_batches"] == []
        assert actual["valid_source_count"] == 0
        assert actual["cpu_head_output_materializations"] == actual["device_to_cpu_head_transfers"] == 0
        assert actual["cuda_executed"] is False


def test_target_argument_and_dimension_relabeling_are_rejected(contextual_checkpoint, scheduler, monkeypatch):
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        with pytest.raises(TypeError):
            session.infer(["Source."], [[.1] * 768], canonical_ir={"rules": []})
        with pytest.raises(ValueError, match="dimension"):
            session.infer(["Source."], [[.1] * 4096])
        assert session._observations == []


def test_over_budget_complete_batch_refuses_before_padded_allocation(contextual_checkpoint, scheduler, monkeypatch):
    text = "a" * 2048 + " x" * 255
    assert len(span.tokenize_source(text)) == 256
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        with pytest.raises(ValueError, match="reserved host memory"):
            session.infer([text] * 128, [[.1] * 768 for _ in range(128)])
        assert session._observations == []
        assert session._active is False
    assert scheduler.active_leases() == []


def test_gpu_memory_bound_refuses_when_host_reservation_is_large(contextual_checkpoint, scheduler, monkeypatch):
    text = "a" * 2048 + " x" * 255
    records = [{"tokens": span.tokenize_source(text), "latent": [.1] * 768} for _ in range(128)]
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        # This inert admission control never performs a CUDA operation. A large
        # host reservation isolates the GPU bound's receiving branch.
        session._lease.memory_mb = 65536
        session._device = "cuda:0"
        try:
            with pytest.raises(ValueError, match="reserved GPU memory"):
                session._admit_batch_memory(records)
        finally:
            session._device = "cpu"


def test_memory_bound_accounts_actual_padding_without_allocating_tensors():
    short = [{"tokens": [{"byte_ids": [1, 2, 3]}], "latent": [0.] * 768}]
    larger = short * 16
    config = {"embedding_dim": 4, "hidden_size": 8}
    a = batch._batch_memory_bound(short, config, parameter_bytes=100, checkpoint_bytes=1000)
    b = batch._batch_memory_bound(larger, config, parameter_bytes=100, checkpoint_bytes=1000)
    assert b["gpu_working_set_bytes"] > a["gpu_working_set_bytes"]
    assert b["host_working_set_bytes"] > b["gpu_working_set_bytes"]


def make_cache():
    text, vector = "Lark must retain books.", [.1] * 768
    tokens = span.tokenize_source(text)
    length = len(tokens)
    output = {"modality": torch.zeros((1, 3)), "presence": torch.zeros((1, 4, 2)),
              "start": torch.zeros((1, 6, length)), "end": torch.zeros((1, 6, length))}
    return batch._CachedOutput(torch, text=text, vector=vector, tokens=tokens,
                               output=output, enabled=True), text, vector, tokens


@pytest.mark.parametrize("fault", ["text_case", "offsets", "vector", "token_tensor", "length_tensor", "gate", "cache", "binding", "repeat"])
def test_cached_outputs_require_exact_source_tokens_native_input_and_single_use(fault):
    cache, text, vector, tokens = make_cache()
    args = list(span._batch(torch, [{"tokens": tokens, "latent": vector}]))
    with pytest.raises(ValueError):
        if fault == "text_case":
            cache.bind(text.lower(), vector)
        elif fault == "offsets":
            cache.bind(" " + text, vector)
        elif fault == "vector":
            cache.bind(text, [.2] * 768)
        else:
            if fault == "token_tensor":
                args[0][0, 0, 0] += 1
            elif fault == "length_tensor":
                args[2][0] -= 1
            elif fault == "cache":
                cache._output["modality"][0, 0] = 1.
            elif fault == "binding":
                cache._binding["tokens"][0]["start"] = 100
            elif fault == "repeat":
                cache(*args, enabled=True)
            cache(*args, enabled=fault != "gate")


@pytest.mark.parametrize("fault", ["keys", "shape", "dtype", "nonfinite"])
def test_cached_outputs_reject_closed_shape_dtype_nonfinite_faults(fault):
    text, vector, tokens = "Lark must retain books.", [.1] * 768, span.tokenize_source("Lark must retain books.")
    output = {"modality": torch.zeros((1, 3)), "presence": torch.zeros((1, 4, 2)),
              "start": torch.zeros((1, 6, len(tokens))), "end": torch.zeros((1, 6, len(tokens)))}
    if fault == "keys":
        output["target"] = torch.zeros((1,))
    elif fault == "shape":
        output["start"] = torch.zeros((1, 6, len(tokens) + 1))
    elif fault == "dtype":
        output["modality"] = output["modality"].to(torch.float64)
    else:
        output["modality"][0, 0] = float("nan")
    with pytest.raises(ValueError, match="cached"):
        batch._CachedOutput(torch, text=text, vector=vector, tokens=tokens, output=output, enabled=True)


def test_pointer_padding_is_trimmed_before_canonical_candidates():
    output = {"modality": torch.zeros((2, 3)), "presence": torch.zeros((2, 4, 2)),
              "start": torch.zeros((2, 6, 10)), "end": torch.zeros((2, 6, 10))}
    output["start"][0, :, 4:] = 1e8
    output["end"][0, :, 4:] = 1e8
    row = batch._row_output(output, 0, 4)
    assert tuple(row["start"].shape) == tuple(row["end"].shape) == (1, 6, 4)
    assert torch.count_nonzero(row["start"]) == torch.count_nonzero(row["end"]) == 0


def test_no_fit_or_optimizer_during_batched_inference(contextual_checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("fitting/optimizer construction during batch inference")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(resident.dimensional, "train_decoder", forbidden)
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        texts, vectors = inputs()
        assert session.infer(texts, vectors)["training_executed"] is False


def test_new_receipts_and_source_pin_are_checked_before_batch(contextual_checkpoint, scheduler, monkeypatch):
    text, vector = "Lark must retain books.", [1.] + [0.] * 767
    rec = receipt(text, vector, True)
    with open_batch(contextual_checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer([text], [vector], embedding_receipts=[rec],
                              expected_receipt_sha256s=[span.checkpoint_digest(rec)])
        assert actual["input_receipts"]["native_encoder_inputs_authenticated"] is True
        assert actual["proof_authority"] is False
        rec["profile_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="receipt"):
            session.infer([text], [vector], embedding_receipts=[rec],
                          expected_receipt_sha256s=[span.checkpoint_digest(rec)])
        assert session._observations == []
        monkeypatch.setattr(batch, "_SOURCE_AT_IMPORT", "0" * 64)
        with pytest.raises(ValueError, match="producer"):
            session.infer([text], [vector])


@pytest.mark.parametrize("fault", ["authored_text", "authored_vector", "checkpoint", "parameter", "cancel"])
def test_post_forward_source_material_or_model_mutations_refuse(contextual_checkpoint, scheduler, monkeypatch, fault):
    texts, vectors = inputs()
    session = open_batch(contextual_checkpoint, scheduler, monkeypatch)
    class Signal:
        fired = False
        def is_set(self):
            if session._observations and not self.fired:
                self.fired = True
                if fault == "authored_text":
                    texts[0] = "Altered original source."
                elif fault == "authored_vector":
                    vectors[0][0] += .1
                elif fault == "checkpoint":
                    session._checkpoint["optimizer_state"]["parameters"]["modality.bias"]["exp_avg"][0] = 1.
                elif fault == "parameter":
                    session._model.modality.bias.data.add_(1.)
            return fault == "cancel" and self.fired
    signal = Signal()
    session._cancel = signal
    try:
        with pytest.raises((ValueError, RuntimeError)):
            session.infer(texts, vectors)
        assert signal.fired
        assert session._observations == []
    finally:
        session._cancel = None
        session.close()
    assert scheduler.active_leases() == []


def test_callback_reentry_and_cross_thread_operations_keep_owner_lease(contextual_checkpoint, scheduler, monkeypatch):
    texts, vectors = inputs()
    session = open_batch(contextual_checkpoint, scheduler, monkeypatch)
    class Signal:
        def is_set(self):
            session.infer(texts, vectors)
            return False
    session._cancel = Signal()
    with pytest.raises(ValueError, match="already active"):
        session.infer(texts, vectors)
    session._cancel = None
    errors = []
    def other_thread():
        try:
            session.infer(texts, vectors)
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=other_thread)
    worker.start()
    worker.join(5.)
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert len(scheduler.active_leases()) == 1
    session.close()
    assert scheduler.active_leases() == []
