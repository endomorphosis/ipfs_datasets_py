import os


def test_llm_router_response_cache_uses_cid_keys(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py import llm_router

    class FakeProvider:
        calls = 0

        def generate(self, prompt: str, *, model_name=None, **kwargs):
            FakeProvider.calls += 1
            return f"out:{prompt}:{model_name}:{kwargs.get('temperature', None)}"

    deps = RouterDeps()
    provider = FakeProvider()

    out1 = llm_router.generate_text(
        "hello",
        model_name="m",
        provider="fake",
        provider_instance=provider,
        deps=deps,
        temperature=0.0,
    )
    out2 = llm_router.generate_text(
        "hello",
        model_name="m",
        provider="fake",
        provider_instance=provider,
        deps=deps,
        temperature=0.0,
    )

    assert out1 == out2
    assert FakeProvider.calls == 1

    # Ensure a CID-style key is present in cache.
    keys = list(deps.router_cache.keys())
    assert any(k.startswith("llm_response_cid::b") for k in keys)


def test_llm_router_response_cache_is_model_sensitive(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py import llm_router

    class FakeProvider:
        calls = 0

        def generate(self, prompt: str, *, model_name=None, **kwargs):
            FakeProvider.calls += 1
            return f"out:{prompt}:{model_name}"

    deps = RouterDeps()
    provider = FakeProvider()

    out1 = llm_router.generate_text(
        "hello",
        model_name="m1",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )
    out2 = llm_router.generate_text(
        "hello",
        model_name="m2",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )

    assert out1 != out2
    assert FakeProvider.calls == 2


def test_embeddings_router_response_cache_uses_cid_keys(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py import embeddings_router

    class FakeProvider:
        calls = 0

        def embed_texts(self, texts, *, model_name=None, device=None, **kwargs):
            FakeProvider.calls += 1
            # deterministic vectors
            return [[float(len(t))] for t in list(texts)]

    deps = RouterDeps()
    provider = FakeProvider()

    out1 = embeddings_router.embed_texts(
        ["a", "bb"],
        model_name="e",
        device="cpu",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )
    out2 = embeddings_router.embed_texts(
        ["a", "bb"],
        model_name="e",
        device="cpu",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )

    assert out1 == out2
    assert FakeProvider.calls == 1

    keys = list(deps.router_cache.keys())
    assert any(k.startswith("embeddings_response_cid::b") for k in keys)


def test_embeddings_router_response_cache_is_model_sensitive(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py import embeddings_router

    class FakeProvider:
        calls = 0

        def embed_texts(self, texts, *, model_name=None, device=None, **kwargs):
            FakeProvider.calls += 1
            # include model in output so collisions are detectable
            model_sig = float(sum(ord(c) for c in str(model_name or "")))
            return [[float(len(t)), model_sig] for t in list(texts)]

    deps = RouterDeps()
    provider = FakeProvider()

    out1 = embeddings_router.embed_texts(
        ["a"],
        model_name="e1",
        device="cpu",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )
    out2 = embeddings_router.embed_texts(
        ["a"],
        model_name="e2",
        device="cpu",
        provider="fake",
        provider_instance=provider,
        deps=deps,
    )

    assert out1 != out2
    assert FakeProvider.calls == 2

    keys = list(deps.router_cache.keys())
    assert len([k for k in keys if k.startswith("embeddings_response_cid::")]) == 2
