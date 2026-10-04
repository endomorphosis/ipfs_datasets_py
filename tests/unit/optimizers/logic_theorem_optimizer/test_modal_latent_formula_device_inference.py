"""Real CPU formula profiles and strict device guard controls; no mock qualification."""
from copy import deepcopy
from functools import lru_cache
import os

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula_device_inference import (
    DeviceLatentFormulaDecoder,
)


@pytest.fixture(autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@lru_cache(maxsize=2)
def checkpoint(dimension=8):
    rows = [dict(id="native-authored", source_text="The agency must disclose records.",
                 latent=[.5] + [0.] * (dimension - 1),
                 embedding=[.3] + [0.] * (dimension - 1),
                 canonical_ir={"rules": [dict(modality="O", actor="agency", action="disclose",
                     object="records", conditions=[], exceptions=[], temporal=[])]})]
    binding = dict(domain="legal_ir", lineage_id="legacy_hub_v1" if dimension == 8 else "current_legal_v2",
                   dimension=dimension, runtime_profile="authored-device-test/v1", core_sha256="a" * 64)
    initial = native.build_checkpoint(binding, rows, [], hidden_size=8, token_embedding_dim=8,
                                      projection_width=2, batch_size=1)
    trained = native.train(initial, rows, [], epochs=1, max_seconds=30)["checkpoint"]
    return trained, [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]


@pytest.mark.parametrize("dimension", [8, 384])
@pytest.mark.parametrize("size", [1, 17])
def test_cpu_opt_out_keeps_checkpoint_and_original_decisions(dimension, size):
    trained, source = checkpoint(dimension)
    before = deepcopy(trained)
    rows = [{**source[0], "id": "inference-" + str(index)} for index in range(size)]
    decoder = DeviceLatentFormulaDecoder(trained, optimized=False)
    report, vectors = decoder.infer_with_projection(rows)
    reference = native.LatentFormulaDecoder(trained).infer(rows)
    assert trained == before and report["checkpoint_sha256"] == native.checkpoint_digest(trained)
    assert [row["canonical_ir"] for row in report["rows"]] == [row["canonical_ir"] for row in reference["rows"]]
    assert [row["generated_token_ids"] for row in report["rows"]] == [row["generated_token_ids"] for row in reference["rows"]]
    assert len(vectors) == size and all(len(vector) == dimension for vector in vectors)
    assert report["inference_implementation"]["device"] == "cpu"
    assert report["inference_implementation"]["cuda_executed"] is False
    assert report["inference_implementation"]["actual_forward_executed"] is True
    assert "cuda_executed" not in decoder.inference_implementation
    assert report["training_executed"] is False and all(report[key] is False for key in native.FALSE)


@pytest.mark.parametrize("change", ["weights", "checkpoint", "factory", "device", "fork"])
def test_private_device_guards_reject_late_changes(change):
    trained, rows = checkpoint()
    decoder = DeviceLatentFormulaDecoder(trained, optimized=False)
    if change == "weights":
        next(decoder.model.parameters()).data.flatten()[0] += .25
    elif change == "checkpoint":
        decoder._checkpoint["progress"]["optimizer_steps"] += 1
    elif change == "factory":
        decoder.torch = torch
    elif change == "device":
        decoder.torch._device = "cuda:0"
    else:
        decoder._process = os.getpid() + 1
    with pytest.raises(ValueError):
        decoder.infer(rows)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_opt_out_requires_explicit_boolean(value):
    with pytest.raises(ValueError, match="boolean"):
        DeviceLatentFormulaDecoder({}, optimized=value)


def test_unknown_fields_and_targets_are_rejected_before_decoding():
    trained, rows = checkpoint()
    decoder = DeviceLatentFormulaDecoder(trained, optimized=False)
    with pytest.raises(ValueError, match="closed latent row"):
        decoder.infer([{**rows[0], "canonical_ir": {"rules": []}}])


def test_inference_propagates_device_failure_without_fallback(monkeypatch):
    trained, rows = checkpoint()
    decoder = DeviceLatentFormulaDecoder(trained, optimized=False)
    def broken(*args, **kwargs):
        raise RuntimeError("actual device operation failed")
    monkeypatch.setattr(decoder.model, "project", broken)
    with pytest.raises(RuntimeError, match="actual device operation failed"):
        decoder.infer(rows)
    assert decoder._device == "cpu"


def test_no_forward_reports_selection_without_execution():
    trained, rows = checkpoint()
    decoder = DeviceLatentFormulaDecoder(trained, optimized=False)
    value = decoder.infer(rows, projection_id="unsupported-projection")
    profile = value["inference_implementation"]
    assert profile["cuda_selected"] is False and profile["cuda_executed"] is False
    assert profile["actual_forward_executed"] is False
    assert sum(profile["actual_forward_calls"].values()) == 0
    assert not any(module._forward_hooks for module in decoder.model.modules())
