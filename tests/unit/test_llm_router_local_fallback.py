import pytest

from ipfs_datasets_py import llm_router


def test_generate_text_can_disable_local_fallback(monkeypatch):
    class _FailingProvider:
        def generate(self, prompt, *, model_name=None, **kwargs):
            raise RuntimeError("primary failed")

    class _LocalProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, model_name=None, **kwargs):
            self.calls += 1
            return "local"

    local_provider = _LocalProvider()

    monkeypatch.setattr(llm_router, "get_llm_provider", lambda provider=None, deps=None: _FailingProvider())
    monkeypatch.setattr(llm_router, "_get_local_hf_provider", lambda deps=None: local_provider)

    with pytest.raises(RuntimeError, match="primary failed"):
        llm_router.generate_text("hello", allow_local_fallback=False)

    assert local_provider.calls == 0


def test_generate_text_auto_falls_back_to_remote_provider_before_local(monkeypatch):
    llm_router.clear_llm_router_caches()

    class _FailingProvider:
        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, model_name, kwargs)
            raise RuntimeError("accelerate empty")

    class _RemoteProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, model_name, kwargs)
            self.calls += 1
            return "remote"

    class _LocalProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, model_name, kwargs)
            self.calls += 1
            return "local"

    remote_provider = _RemoteProvider()
    local_provider = _LocalProvider()

    monkeypatch.setattr(llm_router, "get_llm_provider", lambda provider=None, deps=None: _FailingProvider())
    monkeypatch.setattr(
        llm_router,
        "_iter_unpinned_optional_providers",
        lambda: [("hf_inference_api", remote_provider)],
    )
    monkeypatch.setattr(llm_router, "_get_local_hf_provider", lambda deps=None: local_provider)

    assert llm_router.generate_text("hello", allow_local_fallback=False) == "remote"
    assert remote_provider.calls == 1
    assert local_provider.calls == 0


def test_generate_text_auto_falls_back_to_hf_with_model_retry(monkeypatch):
    llm_router.clear_llm_router_caches()

    class _FailingProvider:
        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, model_name, kwargs)
            raise RuntimeError("Accelerate not available, using local fallback")

    class _FakeHFProvider:
        def __init__(self):
            self.calls = []

        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, kwargs)
            self.calls.append(model_name)
            if model_name == "fallback-llm":
                return "hf remote"
            raise RuntimeError("HF Inference API HTTP 404: Not Found")

    class _LocalProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, model_name=None, **kwargs):
            _ = (prompt, model_name, kwargs)
            self.calls += 1
            return "local"

    hf_provider = _FakeHFProvider()
    local_provider = _LocalProvider()

    monkeypatch.setattr(llm_router, "get_llm_provider", lambda provider=None, deps=None: _FailingProvider())
    monkeypatch.setattr(
        llm_router,
        "_iter_unpinned_optional_providers",
        lambda: [("hf_inference_api", hf_provider)],
    )
    monkeypatch.setattr(llm_router, "_hf_llm_fallback_models", lambda kwargs=None: ["fallback-llm"])
    monkeypatch.setattr(llm_router, "_get_local_hf_provider", lambda deps=None: local_provider)

    assert llm_router.generate_text("hello", allow_local_fallback=False) == "hf remote"
    assert hf_provider.calls == [None, "fallback-llm"]
    assert local_provider.calls == 0