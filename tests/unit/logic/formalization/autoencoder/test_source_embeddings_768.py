"""Synthetic backend checks; these do not qualify real GTE weights or vectors."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py"
SPEC = importlib.util.spec_from_file_location("gte768_producer_under_test", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def arguments(tmp_path):
    return dict(manifest_path=tmp_path / "assets.json", expected_manifest_sha256=None,
                model_directory=tmp_path / "model", code_directory=tmp_path / "code")


def rows():
    return [{"id": "one", "source_text": "Exact source text."}]


def admit(monkeypatch, tmp_path):
    assets = {"status": "available", "profile_id": subject.PROFILE_ID,
              "manifest_sha256": "a" * 64, "model_directory": str(tmp_path / "model"),
              "code_directory": str(tmp_path / "code"), "files": []}
    monkeypatch.setattr(subject._PROFILE, "inspect_local_assets", lambda *a, **k: dict(assets))
    return assets


def test_missing_assets_returns_no_vectors_without_loading_a_backend(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("missing assets must not load a numerical backend")
    monkeypatch.setattr(subject, "_load_backend", forbidden)
    result = subject.embed_rows(rows(), **arguments(tmp_path))
    assert result["status"] == "unavailable"
    assert result["receipts"] == []
    assert result["model_inference_executed"] is False
    assert result["assets"]["unavailable_reasons"] == ["missing_manifest"]


@pytest.mark.parametrize("bad", [[], [{"id": "x", "source_text": "ok", "target": {}}],
    [{"id": "x", "source_text": " "}], [{"id": "x", "source_text": "a\x00b"}],
    [{"id": "x", "source_text": "\ud800"}], [{"id": "\ud800", "source_text": "ok"}],
    [{"id": "x", "source_text": "a" * 65537}],
    [{"id": "x", "source_text": "ok"}, {"id": "x", "source_text": "more"}],
    [{"id": "x" * 257, "source_text": "ok"}]])
def test_source_admission_is_closed_and_bounded(bad, tmp_path, monkeypatch):
    monkeypatch.setattr(subject._PROFILE, "inspect_local_assets", lambda *a, **k: pytest.fail("admit inputs first"))
    with pytest.raises(ValueError):
        subject.embed_rows(bad, **arguments(tmp_path))


@pytest.mark.parametrize("batch_size", [True, 0, 17, 1.0, "1"])
def test_batch_size_is_explicit(tmp_path, batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        subject.embed_rows(rows(), batch_size=batch_size, **arguments(tmp_path))


def test_request_source_bytes_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "MAX_TOTAL_SOURCE_BYTES", 2)
    with pytest.raises(ValueError, match="total UTF8"):
        subject.embed_rows(rows(), **arguments(tmp_path))


class Tokenizer:
    padding_side = "right"
    def __init__(self, torch, lengths=None):
        self.torch = torch
        self.lengths = lengths or {}
        self.calls = []
    def encode(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is True and truncation is False
        self.calls.append(text)
        return [1] + [2] * (self.lengths.get(text, 3) - 2) + [3]
    def pad(self, batch, *, padding, return_tensors):
        assert padding is True and return_tensors == "pt"
        width = max(len(item["input_ids"]) for item in batch)
        return {key: self.torch.tensor([item[key] + [0] * (width - len(item[key]))
                                       for item in batch], dtype=self.torch.int64)
                for key in ("input_ids", "attention_mask")}


class Model:
    config = SimpleNamespace(vocab_size=20)
    def __init__(self, torch, defect=None):
        self.torch, self.defect, self.calls = torch, defect, 0
    def __call__(self, **inputs):
        self.calls += 1
        batch, width = inputs["input_ids"].shape
        hidden = self.torch.zeros((batch, width, 768), dtype=self.torch.float32)
        hidden[:, 0, 0] = 3
        hidden[:, 0, 1] = 4
        if width > 1:
            hidden[:, 1:, :] = 100
        if self.defect == "zero": hidden[:, 0, :] = 0
        if self.defect == "nan": hidden[:, 0, 0] = float("nan")
        if self.defect == "inf": hidden[:, 0, 0] = float("inf")
        if self.defect == "width": hidden = hidden[:, :, :384]
        if self.defect == "dtype": hidden = hidden.to(self.torch.float64)
        return SimpleNamespace(last_hidden_state=hidden, pooler_output="unused")


@pytest.fixture
def torch():
    return pytest.importorskip("torch")


def backend(monkeypatch, tmp_path, torch, *, lengths=None, defect=None):
    admit(monkeypatch, tmp_path)
    tokenizer, model = Tokenizer(torch, lengths), Model(torch, defect)
    monkeypatch.setattr(subject, "_load_backend", lambda assets: (torch, tokenizer, model))
    return tokenizer, model


def test_cls_l2_receipts_bind_exact_sources_and_ignore_other_token_positions(tmp_path, monkeypatch, torch):
    tokenizer, model = backend(monkeypatch, tmp_path, torch, lengths={"second": 2})
    inputs = rows() + [{"id": "two", "source_text": "second"}]
    result = subject.embed_rows(inputs, batch_size=2, **arguments(tmp_path))
    assert model.calls == 1
    assert result["status"] == "completed"
    assert result["runtime_compatibility_verified"] is True
    assert result["maximum_context_numerics_verified"] is False
    assert result["ir_decoder_executed"] is False
    first, second = result["receipts"]
    assert first["embedding"][:2] == pytest.approx([0.6, 0.8])
    assert first["embedding"][2:] == [0.0] * 766
    assert second["token_count_including_special_tokens"] == 2
    assert first["source_sha256"] == hashlib.sha256(inputs[0]["source_text"].encode()).hexdigest()
    assert first["token_input_sha256"] == subject._digest([1, 2, 3])
    assert first["truncated"] is False and first["normalized"] is True
    assert len(first["embedding"]) == 768
    assert inputs == rows() + [{"id": "two", "source_text": "second"}]


def test_8192_including_special_tokens_admitted_in_synthetic_backend(tmp_path, monkeypatch, torch):
    backend(monkeypatch, tmp_path, torch, lengths={rows()[0]["source_text"]: 8192})
    monkeypatch.setattr(subject, "_vectors", lambda *a: [[1.0] + [0.0] * 767])
    result = subject.embed_rows(rows(), **arguments(tmp_path))
    assert result["receipts"][0]["token_count_including_special_tokens"] == 8192
    assert result["maximum_context_numerics_verified"] is False


def test_all_rows_token_checked_before_any_forward(tmp_path, monkeypatch, torch):
    _, model = backend(monkeypatch, tmp_path, torch, lengths={"overlong": 8193})
    with pytest.raises(ValueError, match="8192 tokens including"):
        subject.embed_rows(rows() + [{"id": "late", "source_text": "overlong"}], **arguments(tmp_path))
    assert model.calls == 0


def test_total_token_budget_before_any_forward(tmp_path, monkeypatch, torch):
    _, model = backend(monkeypatch, tmp_path, torch)
    monkeypatch.setattr(subject, "MAX_TOTAL_TOKENS", 2)
    with pytest.raises(ValueError, match="total token budget"):
        subject.embed_rows(rows(), **arguments(tmp_path))
    assert model.calls == 0


@pytest.mark.parametrize("defect", ["zero", "nan", "inf", "width", "dtype"])
def test_invalid_model_output_never_returns_receipts(tmp_path, monkeypatch, torch, defect):
    backend(monkeypatch, tmp_path, torch, defect=defect)
    with pytest.raises(ValueError):
        subject.embed_rows(rows(), **arguments(tmp_path))


@pytest.mark.parametrize("bad", [[True], [20], [-1], [1.0]])
def test_token_ids_must_be_real_vocabulary_integers(tmp_path, monkeypatch, torch, bad):
    tokenizer, model = backend(monkeypatch, tmp_path, torch)
    tokenizer.encode = lambda *a, **k: bad
    with pytest.raises(ValueError, match="model vocabulary"):
        subject.embed_rows(rows(), **arguments(tmp_path))
    assert model.calls == 0


def test_padding_must_preserve_exact_active_tokens(tmp_path, monkeypatch, torch):
    tokenizer, _ = backend(monkeypatch, tmp_path, torch)
    original = tokenizer.pad
    def changed(*a, **k):
        result = original(*a, **k)
        result["input_ids"][0, 0] = 4
        return result
    tokenizer.pad = changed
    with pytest.raises(ValueError, match="active token IDs"):
        subject.embed_rows(rows(), **arguments(tmp_path))


def test_asset_drift_after_inference_rejects_publication(tmp_path, monkeypatch, torch):
    _, model = backend(monkeypatch, tmp_path, torch)
    original = subject._PROFILE.inspect_local_assets
    calls = []
    def changed(*a, **k):
        receipt = original(*a, **k)
        calls.append(1)
        if len(calls) == 3:
            receipt["manifest_sha256"] = "b" * 64
        return receipt
    monkeypatch.setattr(subject._PROFILE, "inspect_local_assets", changed)
    with pytest.raises(ValueError, match="changed during"):
        subject.embed_rows(rows(), **arguments(tmp_path))
    assert model.calls == 1

