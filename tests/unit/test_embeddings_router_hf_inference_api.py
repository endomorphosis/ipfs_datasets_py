"""Unit tests for Hugging Face Inference API integration in embeddings_router."""

from __future__ import annotations

import json
import types

from ipfs_datasets_py import embeddings_router


class _FakeHTTPResponse:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_hf_embeddings_provider_builds_expected_request(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()
    monkeypatch.setenv("HF_TOKEN", "embed-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_INFERENCE_BASE_URL", "https://example.invalid/hf")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeHTTPResponse([[0.1, 0.2], [0.3, 0.4]])

    monkeypatch.setattr(embeddings_router.urllib.request, "urlopen", fake_urlopen)

    vectors = embeddings_router.embed_texts(
        ["alpha", "beta"],
        provider="hf_inference_api",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        timeout=9,
        truncate=True,
    )

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"] == "https://example.invalid/hf/sentence-transformers/all-MiniLM-L6-v2"
    assert captured["auth"] == "Bearer embed-token"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == 9.0

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["inputs"] == ["alpha", "beta"]
    assert body["options"]["wait_for_model"] is True
    assert body["options"]["use_cache"] is True
    assert body["truncate"] is True


def test_hf_embeddings_alias_uses_env_default_model(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_API_TOKEN", "embed-token-2")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_EMBEDDINGS_MODEL", "intfloat/e5-small-v2")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        _ = timeout
        return _FakeHTTPResponse([{"embedding": [0.9, 0.8, 0.7]}])

    monkeypatch.setattr(embeddings_router.urllib.request, "urlopen", fake_urlopen)

    vector = embeddings_router.embed_text("hello", provider="hf_api")

    assert vector == [0.9, 0.8, 0.7]
    assert captured["url"] == "https://router.huggingface.co/hf-inference/models/intfloat/e5-small-v2"


def test_hf_embeddings_sets_bill_to_header_from_env(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()
    monkeypatch.setenv("HF_TOKEN", "embed-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_BILL_TO", "Publicus")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["bill_to"] = req.get_header("X-hf-bill-to")
        return _FakeHTTPResponse([[0.1, 0.2]])

    monkeypatch.setattr(embeddings_router.urllib.request, "urlopen", fake_urlopen)

    _ = embeddings_router.embed_text("hello", provider="hf_inference_api")
    assert captured["bill_to"] == "Publicus"


def test_hf_embeddings_kwargs_bill_to_overrides_env(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()
    monkeypatch.setenv("HF_TOKEN", "embed-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_BILL_TO", "Personal")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["bill_to"] = req.get_header("X-hf-bill-to")
        return _FakeHTTPResponse([[0.1, 0.2]])

    monkeypatch.setattr(embeddings_router.urllib.request, "urlopen", fake_urlopen)

    _ = embeddings_router.embed_text("hello", provider="hf_inference_api", hf_bill_to="Publicus")
    assert captured["bill_to"] == "Publicus"


def test_hf_embeddings_uses_hub_cached_token(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()
    monkeypatch.delenv("IPFS_DATASETS_PY_HF_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    fake_hub = types.SimpleNamespace(get_token=lambda: "cached-embed-token")

    original_import_module = embeddings_router.importlib.import_module

    def fake_import_module(name: str, package=None):
        if name == "huggingface_hub":
            return fake_hub
        return original_import_module(name, package)

    monkeypatch.setattr(embeddings_router.importlib, "import_module", fake_import_module)

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["auth"] = req.get_header("Authorization")
        return _FakeHTTPResponse([[0.42, 0.24]])

    monkeypatch.setattr(embeddings_router.urllib.request, "urlopen", fake_urlopen)

    vector = embeddings_router.embed_text("token fallback", provider="hf_inference_api")

    assert vector == [0.42, 0.24]
    assert captured["auth"] == "Bearer cached-embed-token"


def test_hf_embeddings_retries_with_fallback_models(monkeypatch) -> None:
    embeddings_router.clear_embeddings_router_caches()

    calls: list[str | None] = []

    class _FakeHFEmbeddingsProvider:
        def embed_texts(self, texts, *, model_name=None, device=None, **kwargs):
            _ = (texts, device, kwargs)
            calls.append(model_name)
            if model_name == "fallback-embed":
                return [[0.11, 0.22]]
            raise RuntimeError("HF Inference API HTTP 404: Not Found")

    vector = embeddings_router.embed_text(
        "hello",
        provider="hf_inference_api",
        provider_instance=_FakeHFEmbeddingsProvider(),
        model_name="bad-embed-model",
        hf_model_fallbacks="fallback-embed",
    )

    assert vector == [0.11, 0.22]
    assert calls == ["bad-embed-model", "fallback-embed"]
