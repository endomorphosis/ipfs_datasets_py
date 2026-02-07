import hashlib


def test_llm_router_can_read_through_remote_cache(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py.caching.router_remote_cache import IPFSBackedRemoteCache
    from ipfs_datasets_py import llm_router

    class FakeIPFSBackend:
        def __init__(self):
            self.store = {}

        def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
            _ = pin
            cid = "cidv1-" + hashlib.sha256(data).hexdigest()
            self.store[cid] = data
            return cid

        def cat(self, cid: str) -> bytes:
            return self.store[str(cid)]

    class InMemoryAsyncMappingCache:
        def __init__(self):
            self.data = {}

        def get(self, key: str):
            return self.data.get(key)

        async def set(self, key: str, value, ttl=None, broadcast=True):
            _ = (ttl, broadcast)
            self.data[key] = value
            return "ok"

    class FakeProvider:
        calls = 0

        def generate(self, prompt: str, *, model_name=None, **kwargs):
            FakeProvider.calls += 1
            return f"out:{prompt}:{model_name}:{kwargs.get('temperature', None)}"

    mapping_cache = InMemoryAsyncMappingCache()
    ipfs_backend = FakeIPFSBackend()

    remote_cache = IPFSBackedRemoteCache(mapping_cache=mapping_cache, ipfs_backend=ipfs_backend)

    deps1 = RouterDeps(ipfs_backend=ipfs_backend, remote_cache=remote_cache)
    provider1 = FakeProvider()

    out1 = llm_router.generate_text(
        "hello",
        model_name="m",
        provider="fake",
        provider_instance=provider1,
        deps=deps1,
        temperature=0.0,
    )
    assert FakeProvider.calls == 1

    # Fresh deps w/ empty local cache but same remote mapping+ipfs content.
    deps2 = RouterDeps(ipfs_backend=ipfs_backend, remote_cache=remote_cache)
    provider2 = FakeProvider()

    out2 = llm_router.generate_text(
        "hello",
        model_name="m",
        provider="fake",
        provider_instance=provider2,
        deps=deps2,
        temperature=0.0,
    )

    assert out1 == out2
    # Second call should have hit remote cache (no new provider call).
    assert FakeProvider.calls == 1


def test_embeddings_router_can_read_through_remote_cache(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py.caching.router_remote_cache import IPFSBackedRemoteCache
    from ipfs_datasets_py import embeddings_router

    class FakeIPFSBackend:
        def __init__(self):
            self.store = {}

        def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
            _ = pin
            cid = "cidv1-" + hashlib.sha256(data).hexdigest()
            self.store[cid] = data
            return cid

        def cat(self, cid: str) -> bytes:
            return self.store[str(cid)]

    class InMemoryAsyncMappingCache:
        def __init__(self):
            self.data = {}

        def get(self, key: str):
            return self.data.get(key)

        async def set(self, key: str, value, ttl=None, broadcast=True):
            _ = (ttl, broadcast)
            self.data[key] = value
            return "ok"

    class FakeProvider:
        calls = 0

        def embed_texts(self, texts, *, model_name=None, device=None, **kwargs):
            _ = (device, kwargs)
            FakeProvider.calls += 1
            return [[float(len(t))] for t in list(texts)]

    mapping_cache = InMemoryAsyncMappingCache()
    ipfs_backend = FakeIPFSBackend()

    remote_cache = IPFSBackedRemoteCache(mapping_cache=mapping_cache, ipfs_backend=ipfs_backend)

    deps1 = RouterDeps(ipfs_backend=ipfs_backend, remote_cache=remote_cache)
    provider1 = FakeProvider()

    out1 = embeddings_router.embed_texts(
        ["a", "bb"],
        model_name="e",
        device="cpu",
        provider="fake",
        provider_instance=provider1,
        deps=deps1,
    )
    assert FakeProvider.calls == 1

    deps2 = RouterDeps(ipfs_backend=ipfs_backend, remote_cache=remote_cache)
    provider2 = FakeProvider()

    out2 = embeddings_router.embed_texts(
        ["a", "bb"],
        model_name="e",
        device="cpu",
        provider="fake",
        provider_instance=provider2,
        deps=deps2,
    )

    assert out1 == out2
    assert FakeProvider.calls == 1
