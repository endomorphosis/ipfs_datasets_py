"""Offline producer boundaries using explicit diagnostic tensors, never weights."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan


class FixtureModel:
    """A conspicuous diagnostic model; it never enters the native constructor."""
    def __init__(self, *, drift=False, dtype=torch.float32, nonfinite=False):
        self.calls = []
        self.drift = drift
        self.dtype = dtype
        self.nonfinite = nonfinite

    def tokenizer(self, text, **kwargs):
        assert kwargs["truncation"] is False
        assert kwargs["add_special_tokens"] is True
        assert kwargs["padding"] is False
        ids = [101] + [1000 + sum(word.encode()) % 1000 for word in text.split()] + [102]
        return {"input_ids": ids, "attention_mask": [1] * len(ids), "token_type_ids": [0] * len(ids)}

    def tokenize(self, texts):
        rows = [self.tokenizer(text, truncation=False, add_special_tokens=True, padding=False) for text in texts]
        width = max(len(row["input_ids"]) for row in rows)
        result = {key: torch.tensor([row[key] + [0] * (width - len(row[key])) for row in rows], dtype=torch.long)
                  for key in ("input_ids", "attention_mask", "token_type_ids")}
        if self.drift:
            result["input_ids"][0, 1] += 1
        return {**result, "modality": "text"}

    def __call__(self, features):
        assert torch.is_inference_mode_enabled()
        self.calls.append(features["input_ids"].clone())
        vectors = torch.zeros((len(features["input_ids"]), 384), dtype=self.dtype)
        vectors[:, 0] = float("nan") if self.nonfinite else 1.0
        return {**features, "sentence_embedding": vectors}


def _inputs(tmp_path, texts):
    result, paths = [], {}
    for index, text in enumerate(texts):
        raw = text.encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = tmp_path / str(index)
        path.write_bytes(raw)
        paths[digest] = path
        source = SourceSpan(SourceArtifact(digest, len(raw)), "us_code", "fixture-release",
                            f"fixture-{index}", "en", f"1 USC {index + 1}", 0, len(raw))
        result.append(codec.EmbeddingInput(source, "1", str(index + 1), text, source.citation))
    return result, lambda ref: paths[ref["sha256"]]


def _results(inputs, model, batch_size=2):
    return runtime._produce_results(inputs, model, torch, batch_size=batch_size,
                                    token_input_digest=codec.token_input_digest)


def test_guard_restores_environment_sockets_and_bytecode_after_failure(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "original")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    originals = (socket.create_connection, socket.socket.connect, sys.dont_write_bytecode)
    with pytest.raises(RuntimeError, match="fixture stop"):
        with runtime._offline_guard():
            assert os.environ["HF_HUB_OFFLINE"] == "1"
            assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
            assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
            assert sys.dont_write_bytecode is True
            with pytest.raises(runtime.EmbeddingRuntimeError, match="network"):
                socket.create_connection(("127.0.0.1", 9))
            with socket.socket() as sock:
                with pytest.raises(runtime.EmbeddingRuntimeError, match="network"):
                    sock.connect(("127.0.0.1", 9))
            raise RuntimeError("fixture stop")
    assert os.environ["HF_HUB_OFFLINE"] == "original"
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    assert (socket.create_connection, socket.socket.connect, sys.dont_write_bytecode) == originals


def test_exact_token_boundary_and_batch_forward_keep_input_order(tmp_path):
    inputs, _ = _inputs(tmp_path, ["law " * 510, "law " * 511, "Short rule.", "Last rule here."])
    model = FixtureModel()
    results = _results(inputs, model)
    assert [row["input_id"] for row in results] == [item.input_id for item in inputs]
    assert [row["status"] for row in results] == ["embedded", "token_limit_exceeded", "embedded", "embedded"]
    assert [tuple(batch.shape) for batch in model.calls] == [(2, 512), (1, 5)]
    assert len(results[0]["tokens"]["input_ids"]) == 512
    assert results[1]["tokens"]["token_count"] == 513
    assert results[1]["vector"] is None
    assert len(results[2]["tokens"]["input_ids"]) == 4
    assert results[2]["tokens"]["attention_mask"] == [1, 1, 1, 1]


def test_oversized_whole_text_never_enters_forward(tmp_path):
    inputs, _ = _inputs(tmp_path, ["law " * 600])
    model = FixtureModel()
    result = _results(inputs, model)[0]
    assert model.calls == []
    assert result["status"] == "token_limit_exceeded"
    assert result["tokens"] == codec.token_input_digest(model.tokenizer(
        inputs[0].text, truncation=False, add_special_tokens=True, padding=False))


def test_hidden_tokenization_change_fails_before_forward(tmp_path):
    inputs, _ = _inputs(tmp_path, ["Exact untouched words."])
    model = FixtureModel(drift=True)
    with pytest.raises(runtime.EmbeddingRuntimeError, match="differ from untruncated"):
        _results(inputs, model)
    assert model.calls == []


@pytest.mark.parametrize("options", [{"dtype": torch.float64}, {"nonfinite": True}])
def test_wrong_precision_or_nonfinite_output_is_rejected(tmp_path, options):
    inputs, _ = _inputs(tmp_path, ["Exact words."])
    with pytest.raises(runtime.EmbeddingRuntimeError, match="finite CPU float32"):
        _results(inputs, FixtureModel(**options))


def test_lower_existing_context_ceiling_is_rejected_without_raising_it():
    model = SimpleNamespace(max_seq_length=256)
    with pytest.raises(runtime.EmbeddingRuntimeError, match="already be exactly 512"):
        runtime._validate_model(model, torch)
    assert model.max_seq_length == 256


def test_lower_tokenizer_ceiling_is_rejected_without_raising_it():
    model = SimpleNamespace(max_seq_length=512, tokenizer=SimpleNamespace(model_max_length=256))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="must not be below 512"):
        runtime._validate_model(model, torch)
    assert model.tokenizer.model_max_length == 256


def _snapshot(tmp_path, monkeypatch):
    snapshot = tmp_path / "models--thenlper--gte-small" / "snapshots" / runtime.PINNED_REVISION
    manifest = {}
    for name in runtime._PINNED_ASSETS:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("diagnostic fixture " + name).encode()
        path.write_bytes(raw)
        manifest[name] = (len(raw), hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(runtime, "_PINNED_ASSETS", manifest)
    return snapshot


def test_asset_manifest_detects_changed_bytes_and_unknown_configs(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path, monkeypatch)
    _, manifest = runtime._snapshot_assets(snapshot)
    assert len(manifest) == 9
    assert [row["name"] for row in manifest] == sorted(runtime._PINNED_ASSETS)
    weight = snapshot / "model.safetensors"
    original = weight.read_bytes()
    weight.write_bytes(b"x" * len(original))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="SHA-256"):
        runtime._snapshot_assets(snapshot)
    weight.write_bytes(original)
    (snapshot / "config_sentence_transformers.json").write_text("{}")
    with pytest.raises(runtime.EmbeddingRuntimeError, match="unexpected"):
        runtime._snapshot_assets(snapshot)


def test_assets_allow_cache_blob_links_but_reject_external_targets(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path, monkeypatch)
    weight = snapshot / "model.safetensors"
    raw = weight.read_bytes()
    blob = snapshot.parent.parent / "blobs" / "fixture"
    blob.parent.mkdir()
    blob.write_bytes(raw)
    weight.unlink()
    weight.symlink_to(blob)
    runtime._snapshot_assets(snapshot)
    external = tmp_path / "untrusted"
    external.write_bytes(raw)
    weight.unlink()
    weight.symlink_to(external)
    with pytest.raises(runtime.EmbeddingRuntimeError, match="inside the pinned model cache"):
        runtime._snapshot_assets(snapshot)


def test_source_verification_precedes_any_model_loading(tmp_path, monkeypatch):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    resolver({"sha256": inputs[0].source.artifact.sha256}).write_text("Changed bytes.")
    monkeypatch.setattr(runtime, "_snapshot_assets", lambda *args: pytest.fail("model assets accessed before source verification"))
    with pytest.raises(codec.EmbeddingProductionError, match="source bytes"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver)


def test_fixture_tensor_receipt_cannot_be_converted_to_native_corpus(tmp_path):
    inputs, resolver = _inputs(tmp_path, ["An exact diagnostic source."])
    rows = _results(inputs, FixtureModel())
    receipt = codec.build_embedding_production_receipt(
        inputs, results=rows, execution={**codec.native_execution_profile(), "kind": "injected_fixture"},
        model_assets=[{"name": name, "bytes": size, "sha256": digest}
                      for name, (size, digest) in sorted(runtime._PINNED_ASSETS.items())],
        producer={"code_sha256": "a" * 64, "runtime_versions": {
            "python": "fixture", "torch": "fixture", "transformers": "fixture", "tokenizers": "fixture",
            "sentence_transformers": "fixture"}},
        resolver=resolver)
    assert receipt.status_counts["embedded"] == 1
    assert receipt.native_execution_profile is False
    with pytest.raises(codec.EmbeddingProductionError, match="injected fixtures"):
        receipt.to_corpus_records(resolver=resolver)


def test_native_api_has_no_model_factory_escape_hatch(tmp_path):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    with pytest.raises(TypeError, match="model_factory"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver, model_factory=FixtureModel)


def test_resident_producer_source_drift_blocks_before_loading(tmp_path, monkeypatch):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    monkeypatch.setattr(runtime, "_LOADED_PRODUCER_SHA256", "0" * 64)
    monkeypatch.setattr(runtime, "_snapshot_assets", lambda *args: pytest.fail("model loaded after producer source drift"))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="source changed"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver)


@pytest.mark.parametrize("batch_size", [True, 0, 17])
def test_native_batch_bound_is_checked_before_loading(batch_size):
    with pytest.raises(runtime.EmbeddingRuntimeError, match="batch_size"):
        runtime.produce_native_embedding_receipt([], resolver=lambda _: None, batch_size=batch_size)
