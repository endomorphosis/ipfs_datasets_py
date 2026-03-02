"""Unit tests for Hugging Face Inference API integration in llm_router."""

from __future__ import annotations

import json
import types

from ipfs_datasets_py import llm_router


class _FakeHTTPResponse:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_hf_inference_api_generate_builds_expected_request(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_INFERENCE_BASE_URL", "https://example.invalid/models")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeHTTPResponse([{"generated_text": "ok from hf"}])

    monkeypatch.setattr(llm_router.urllib.request, "urlopen", fake_urlopen)

    text = llm_router.generate_text(
        "hello",
        provider="hf_inference_api",
        model_name="tiiuae/falcon-7b-instruct",
        max_new_tokens=12,
        temperature=0.1,
        timeout=7,
        top_p=0.9,
    )

    assert text == "ok from hf"
    assert captured["url"] == "https://example.invalid/models/tiiuae/falcon-7b-instruct"
    assert captured["auth"] == "Bearer test-token"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == 7.0

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["inputs"] == "hello"
    assert body["parameters"]["max_new_tokens"] == 12
    assert body["parameters"]["temperature"] == 0.1
    assert body["parameters"]["top_p"] == 0.9


def test_hf_inference_api_sets_bill_to_header_from_env(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_BILL_TO", "Publicus")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["bill_to"] = req.get_header("X-hf-bill-to")
        return _FakeHTTPResponse({"generated_text": "ok"})

    monkeypatch.setattr(llm_router.urllib.request, "urlopen", fake_urlopen)

    _ = llm_router.generate_text("hello", provider="hf_inference_api")
    assert captured["bill_to"] == "Publicus"


def test_hf_inference_api_kwargs_bill_to_overrides_env(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_BILL_TO", "Personal")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["bill_to"] = req.get_header("X-hf-bill-to")
        return _FakeHTTPResponse({"generated_text": "ok"})

    monkeypatch.setattr(llm_router.urllib.request, "urlopen", fake_urlopen)

    _ = llm_router.generate_text("hello", provider="hf_inference_api", hf_bill_to="Publicus")
    assert captured["bill_to"] == "Publicus"


def test_hf_inference_api_alias_uses_env_default_model(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_API_TOKEN", "token-2")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_INFERENCE_MODEL", "google/flan-t5-small")

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        return _FakeHTTPResponse({"generated_text": "alias path"})

    monkeypatch.setattr(llm_router.urllib.request, "urlopen", fake_urlopen)

    text = llm_router.generate_text("hi", provider="hf_api")

    assert text == "alias path"
    assert captured["url"] == "https://router.huggingface.co/hf-inference/models/google/flan-t5-small"


def test_hf_inference_api_uses_hub_cached_token(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.delenv("IPFS_DATASETS_PY_HF_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    fake_hub = types.SimpleNamespace(get_token=lambda: "cached-token")

    original_import_module = llm_router.importlib.import_module

    def fake_import_module(name: str, package=None):
        if name == "huggingface_hub":
            return fake_hub
        return original_import_module(name, package)

    monkeypatch.setattr(llm_router.importlib, "import_module", fake_import_module)

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        _ = timeout
        captured["auth"] = req.get_header("Authorization")
        return _FakeHTTPResponse({"generated_text": "from cache"})

    monkeypatch.setattr(llm_router.urllib.request, "urlopen", fake_urlopen)

    text = llm_router.generate_text("hello", provider="hf_inference_api")

    assert text == "from cache"
    assert captured["auth"] == "Bearer cached-token"


def test_hf_inference_api_retries_with_fallback_models(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()

    calls: list[str | None] = []

    class _FakeHFProvider:
        def generate(self, prompt: str, *, model_name=None, **kwargs):
            _ = (prompt, kwargs)
            calls.append(model_name)
            if model_name == "fallback-llm":
                return "ok via fallback"
            raise RuntimeError("HF Inference API HTTP 404: Not Found")

    text = llm_router.generate_text(
        "hello",
        provider="hf_inference_api",
        provider_instance=_FakeHFProvider(),
        model_name="bad-model",
        hf_model_fallbacks="fallback-llm",
    )

    assert text == "ok via fallback"
    assert calls == ["bad-model", None, "fallback-llm"]


def test_hf_inference_api_retries_with_discovered_models(monkeypatch) -> None:
    llm_router.clear_llm_router_caches()
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_DYNAMIC_MODEL_DISCOVERY", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_LLM_DISCOVERY_TAGS", "text-generation")
    monkeypatch.setenv("IPFS_DATASETS_PY_HF_LLM_DISCOVERY_LIMIT", "5")

    class _FakeHfApi:
        def list_models(self, **kwargs):
            _ = kwargs
            return [types.SimpleNamespace(id="discovered-llm")]

    fake_hub = types.SimpleNamespace(HfApi=_FakeHfApi, get_token=lambda: None)
    original_import_module = llm_router.importlib.import_module

    def fake_import_module(name: str, package=None):
        if name == "huggingface_hub":
            return fake_hub
        return original_import_module(name, package)

    monkeypatch.setattr(llm_router.importlib, "import_module", fake_import_module)

    calls: list[str | None] = []

    class _FakeHFProvider:
        def generate(self, prompt: str, *, model_name=None, **kwargs):
            _ = (prompt, kwargs)
            calls.append(model_name)
            if model_name == "discovered-llm":
                return "ok via discovered"
            raise RuntimeError("HF Inference API HTTP 404: Not Found")

    text = llm_router.generate_text(
        "hello",
        provider="hf_inference_api",
        provider_instance=_FakeHFProvider(),
        model_name="bad-model",
    )

    assert text == "ok via discovered"
    assert calls == ["bad-model", None, "discovered-llm"]
