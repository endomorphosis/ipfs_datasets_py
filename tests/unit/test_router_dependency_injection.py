import importlib
import os
import sys
import types


def _purge_modules(prefix: str) -> None:
    for name in list(sys.modules.keys()):
        if name == prefix or name.startswith(prefix + "."):
            del sys.modules[name]


def test_router_deps_reuse_and_caching(monkeypatch):
    # Force hermetic package import for the test.
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "1")

    # Ensure a clean import state.
    _purge_modules("ipfs_datasets_py")

    # Import routers and deps under minimal-import mode.
    router_deps = importlib.import_module("ipfs_datasets_py.router_deps")
    llm_router = importlib.import_module("ipfs_datasets_py.llm_router")
    embeddings_router = importlib.import_module("ipfs_datasets_py.embeddings_router")
    ipfs_backend_router = importlib.import_module("ipfs_datasets_py.ipfs_backend_router")

    # Stub accelerate integration to avoid heavy optional dependencies.
    fake_mod = types.ModuleType("ipfs_datasets_py.accelerate_integration")

    class FakeManager:
        instances = 0

        def __init__(self, *args, **kwargs):
            FakeManager.instances += 1

        def run_inference(self, model_name, payload, task_type):
            if task_type == "text-generation":
                return {"text": "ok"}
            if task_type == "embedding":
                texts = payload.get("texts") or []
                return {"embeddings": [[0.0] for _ in list(texts)]}
            return {}

    def is_accelerate_available():
        return True

    fake_mod.AccelerateManager = FakeManager
    fake_mod.is_accelerate_available = is_accelerate_available

    sys.modules["ipfs_datasets_py.accelerate_integration"] = fake_mod

    deps = router_deps.RouterDeps()

    # RouterDeps caches AccelerateManager per purpose.
    m1 = deps.get_accelerate_manager(purpose="llm_router")
    m2 = deps.get_accelerate_manager(purpose="llm_router")
    assert m1 is m2
    assert FakeManager.instances == 1

    # Routers cache provider instances on injected deps.
    p1 = llm_router.get_llm_provider(deps=deps)
    p2 = llm_router.get_llm_provider(deps=deps)
    assert p1 is p2
    assert llm_router.generate_text("hi", deps=deps) == "ok"

    e1 = embeddings_router.get_embeddings_provider(deps=deps)
    e2 = embeddings_router.get_embeddings_provider(deps=deps)
    assert e1 is e2
    assert embeddings_router.embed_texts(["a", "b"], deps=deps) == [[0.0], [0.0]]

    # IPFS backend router stores resolved backend on deps.
    b1 = ipfs_backend_router.get_ipfs_backend(deps=deps)
    b2 = ipfs_backend_router.get_ipfs_backend(deps=deps)
    assert b1 is b2
