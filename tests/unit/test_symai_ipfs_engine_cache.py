import importlib
import os
import types

import pytest


class _Prop:
    def __init__(self, prepared_input: str, *, response_format=None, payload=None):
        self.prepared_input = prepared_input
        self.response_format = response_format
        self.payload = payload


class _Arg:
    def __init__(self, prepared_input: str, *, response_format=None, payload=None):
        self.prop = _Prop(prepared_input, response_format=response_format, payload=payload)


@pytest.mark.unit
def test_symai_ipfs_engine_uses_routerdeps_cache(monkeypatch):
    # Skip if symai isn't installed in the test environment.
    pytest.importorskip("symai")

    monkeypatch.setenv("IPFS_DATASETS_PY_SYMAI_ROUTER_CACHE", "1")
    monkeypatch.delenv("IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_SYMAI_REMOTE_CACHE", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK", raising=False)

    symai_ipfs_engine = importlib.import_module("ipfs_datasets_py.utils.symai_ipfs_engine")
    router_deps = importlib.import_module("ipfs_datasets_py.router_deps")

    deps = router_deps.RouterDeps()
    router_deps.set_default_router_deps(deps)

    # Ensure the engine config routes through the IPFS engine router.
    symai_ipfs_engine.SYMAI_CONFIG["SEARCH_ENGINE_MODEL"] = "ipfs:default"

    calls = {"n": 0}

    def fake_generate_text(prompt: str, model_name: str):
        calls["n"] += 1
        return (f"answer:{prompt}", {"backend": "fake"})

    monkeypatch.setattr(symai_ipfs_engine, "_generate_text", fake_generate_text)

    engine = symai_ipfs_engine.IPFSSyMAIEngine("search", "SEARCH_ENGINE_MODEL")

    arg = _Arg("What is 1+1? Answer with just the number.")
    out1, meta1 = engine.forward(arg)
    out2, meta2 = engine.forward(arg)

    assert out1 == out2
    assert calls["n"] == 1
    assert meta1.get("cache") == "miss"
    assert meta2.get("cache") == "hit"
    assert meta2.get("backend") == "cache"


@pytest.mark.unit
def test_symai_ipfs_engine_cache_key_separates_json_vs_text(monkeypatch):
    pytest.importorskip("symai")

    monkeypatch.setenv("IPFS_DATASETS_PY_SYMAI_ROUTER_CACHE", "1")
    monkeypatch.delenv("IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN", raising=False)

    symai_ipfs_engine = importlib.import_module("ipfs_datasets_py.utils.symai_ipfs_engine")
    router_deps = importlib.import_module("ipfs_datasets_py.router_deps")

    deps = router_deps.RouterDeps()
    router_deps.set_default_router_deps(deps)

    symai_ipfs_engine.SYMAI_CONFIG["SEARCH_ENGINE_MODEL"] = "ipfs:default"

    calls = {"n": 0}

    def fake_generate_text(prompt: str, model_name: str):
        calls["n"] += 1
        # Return different bodies to make collisions obvious.
        if "json" in prompt.lower():
            return ("{\"status\": \"ok\"}", {"backend": "fake"})
        return ("ok", {"backend": "fake"})

    monkeypatch.setattr(symai_ipfs_engine, "_generate_text", fake_generate_text)

    engine = symai_ipfs_engine.IPFSSyMAIEngine("search", "SEARCH_ENGINE_MODEL")

    # Use a prompt that *doesn't* itself ask for JSON so that the
    # wants_json decision is driven by response_format.
    prompt = "Reply with OK only."
    text_arg = _Arg(prompt, response_format=None)
    json_arg = _Arg(prompt, response_format={"type": "json_object"})

    out_text, meta_text = engine.forward(text_arg)
    out_json, meta_json = engine.forward(json_arg)

    assert calls["n"] == 2
    assert meta_text.get("cache") == "miss"
    assert meta_json.get("cache") == "miss"
    assert meta_text.get("cache_key")
    assert meta_json.get("cache_key")
    assert meta_text.get("cache_key") != meta_json.get("cache_key")

    # Output may be identical for different formats; the key separation is what matters.
    assert isinstance(out_text, list)
    assert isinstance(out_json, list)
