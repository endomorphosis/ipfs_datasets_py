from __future__ import annotations

import importlib
from pathlib import Path


def test_accelerate_provider_accepts_generated_text_shape(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

    llm_router = importlib.import_module("ipfs_datasets_py.llm_router")
    manager_module = importlib.import_module("ipfs_datasets_py.ml.accelerate_integration.manager")

    class _FakeManager:
        def run_inference(self, model_name, payload, task_type=None):
            _ = (model_name, payload, task_type)
            return {"status": "success", "result": [{"generated_text": "ok from accelerate"}]}

    monkeypatch.setattr(manager_module, "AccelerateManager", lambda: _FakeManager())

    provider = llm_router._get_accelerate_provider(llm_router.RouterDeps())

    assert provider is not None
    assert provider.generate("hello") == "ok from accelerate"


def test_accelerate_provider_accepts_multimodal_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

    llm_router = importlib.import_module("ipfs_datasets_py.llm_router")
    manager_module = importlib.import_module("ipfs_datasets_py.ml.accelerate_integration.manager")

    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class _FakeManager:
        def __init__(self) -> None:
            self.calls = []

        def run_inference(self, model_name, payload, task_type=None, **kwargs):
            self.calls.append(
                {
                    "model_name": model_name,
                    "payload": payload,
                    "task_type": task_type,
                    "kwargs": kwargs,
                }
            )
            return {"status": "success", "text": "ok from accelerate vision"}

    fake_manager = _FakeManager()
    monkeypatch.setattr(manager_module, "AccelerateManager", lambda: fake_manager)

    provider = llm_router._get_accelerate_provider(llm_router.RouterDeps())

    assert provider is not None
    result = provider.generate_multimodal(
        "review this UI",
        model_name="codex_cli",
        image_paths=[str(image_path)],
        system_prompt="be concrete",
        additional_text_blocks=["check mobile fit"],
        image_detail="high",
    )

    assert result == "ok from accelerate vision"
    assert fake_manager.calls
    call = fake_manager.calls[0]
    assert call["model_name"] == "codex_cli"
    assert call["task_type"] == "multimodal-generation"
    assert call["payload"]["prompt"] == "review this UI"
    assert call["payload"]["system_prompt"] == "be concrete"
    assert call["payload"]["additional_text_blocks"] == ["check mobile fit"]
    assert call["payload"]["image_detail"] == "high"
    assert call["payload"]["image_data_urls"][0].startswith("data:image/png;base64,")
