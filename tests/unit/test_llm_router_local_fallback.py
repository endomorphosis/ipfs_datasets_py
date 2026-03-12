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