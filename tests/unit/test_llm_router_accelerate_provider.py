from __future__ import annotations

import importlib


def test_accelerate_provider_accepts_generated_text_shape(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

    llm_router = importlib.import_module("ipfs_datasets_py.llm_router")

    class _FakeManager:
        def run_inference(self, model_name, payload, task_type):
            _ = (model_name, payload, task_type)
            return {"status": "success", "result": [{"generated_text": "ok from accelerate"}]}

    class _FakeDeps:
        def get_accelerate_manager(self, **kwargs):
            _ = kwargs
            return _FakeManager()

    monkeypatch.setattr(llm_router.importlib.util, "find_spec", lambda name: object() if name == "ipfs_accelerate_py" else None)

    provider = llm_router._get_accelerate_provider(_FakeDeps())

    assert provider is not None
    assert provider.generate("hello") == "ok from accelerate"