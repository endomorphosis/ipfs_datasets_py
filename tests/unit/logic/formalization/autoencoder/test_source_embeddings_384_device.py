"""Device selection preserves asset validation and bounded source inference."""
from contextlib import nullcontext
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer


@pytest.fixture(autouse=True)
def isolated_encoder_cache():
    subject.clear_embedding_cache()
    yield
    subject.clear_embedding_cache()


@pytest.mark.parametrize("cuda", [False, True])
def test_device_selection_after_cpu_validation(monkeypatch, cuda):
    events = []
    model = SimpleNamespace(
        eval=lambda: events.append("eval"),
        to=lambda device: events.append(device),
        tokenizer=lambda *args, **kwargs: {"input_ids": [1, 2]},
        encode=lambda texts, **kwargs: SimpleNamespace(tolist=lambda: [[0.] * 384]),
    )
    def load(path, **options):
        assert options == dict(local_files_only=True, trust_remote_code=False, device="cpu")
        events.append("load")
        return model
    monkeypatch.setattr(producer, "_snapshot_assets", lambda path: (path, []))
    monkeypatch.setattr(producer, "_validate_model", lambda *args: events.append("validate"))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=load))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        random=SimpleNamespace(fork_rng=lambda **kwargs: nullcontext()),
        cuda=SimpleNamespace(is_available=lambda: cuda, current_device=lambda: 0),
        inference_mode=nullcontext,
    ))
    assert len(subject.embed_texts(["The agency shall report."])[0]) == 384
    assert events == ["load", "eval", "validate"] + (["cuda:0"] if cuda else [])
    # Warm calls reuse the model, but still verify all pinned asset hashes.
    verified = []
    monkeypatch.setattr(producer, "_snapshot_assets", lambda path: (verified.append(path) or path, []))
    assert len(subject.embed_texts(["Another report."])[0]) == 384
    assert verified == [producer.DEFAULT_SNAPSHOT_PATH]
    assert events.count("load") == 1
    model.tokenizer = lambda *args, **kwargs: {"input_ids": [1] * 513}
    model.encode = lambda *args, **kwargs: pytest.fail("overlong input must not encode")
    with pytest.raises(ValueError, match="512-token limit"):
        subject.embed_texts(["overlong"])
    # An altered asset must fail even when the encoder is already resident.
    def reject(path):
        raise producer.EmbeddingRuntimeError("model asset SHA-256 does not match pinned bytes")
    monkeypatch.setattr(producer, "_snapshot_assets", reject)
    with pytest.raises(producer.EmbeddingRuntimeError, match="SHA-256"):
        subject.embed_texts(["The agency shall report."])


def test_cache_is_bounded_and_separates_process_device_and_snapshot(monkeypatch):
    loads = []
    def load(path, **options):
        loads.append(path)
        return SimpleNamespace(eval=lambda: None, to=lambda device: None)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=load))
    torch = SimpleNamespace(random=SimpleNamespace(fork_rng=lambda **kwargs: nullcontext()))
    validator = SimpleNamespace(_validate_model=lambda *args: None)
    first = subject._cached_model("snapshot-a", "cpu", torch, validator)
    assert subject._cached_model("snapshot-a", "cpu", torch, validator) is first
    assert subject._cached_model("snapshot-a", "cuda:0", torch, validator) is not first
    subject._cached_model("snapshot-b", "cpu", torch, validator)
    assert len(subject._MODEL_CACHE) == 2
    assert subject._cached_model("snapshot-a", "cpu", torch, validator) is not first
    monkeypatch.setattr(subject.os, "getpid", lambda: -1)
    subject._cached_model("snapshot-a", "cpu", torch, validator)
    assert len(subject._MODEL_CACHE) == 1
    assert len(loads) == 5
