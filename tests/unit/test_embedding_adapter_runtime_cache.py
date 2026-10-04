from __future__ import annotations

from ipfs_datasets_py.utils import embedding_adapter


def test_get_or_create_hf_runtime_caches_model_and_tokenizer() -> None:
    embedding_adapter._HF_RUNTIME_CACHE.clear()

    calls = {"tokenizer": 0, "model": 0}

    class _FakeTokenizer:
        @classmethod
        def from_pretrained(cls, model_name):
            _ = model_name
            calls["tokenizer"] += 1
            return object()

    class _FakeModelObj:
        def to(self, device):
            _ = device
            return self

        def eval(self):
            return self

    class _FakeModel:
        @classmethod
        def from_pretrained(cls, model_name):
            _ = model_name
            calls["model"] += 1
            return _FakeModelObj()

    class _FakeTransformers:
        AutoTokenizer = _FakeTokenizer
        AutoModel = _FakeModel

    fake_torch = object()

    first = embedding_adapter._get_or_create_hf_runtime(
        model_name="thenlper/gte-small",
        device="cuda",
        torch=fake_torch,
        transformers=_FakeTransformers,
    )
    second = embedding_adapter._get_or_create_hf_runtime(
        model_name="thenlper/gte-small",
        device="cuda",
        torch=fake_torch,
        transformers=_FakeTransformers,
    )

    assert first is second
    assert calls["tokenizer"] == 1
    assert calls["model"] == 1
