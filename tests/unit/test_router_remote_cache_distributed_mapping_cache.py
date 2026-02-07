import hashlib


def test_make_ipfs_remote_cache_uses_distributed_mapping_cache_local_only(monkeypatch, tmp_path):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "cid")

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py.caching.router_remote_cache import make_ipfs_remote_cache
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

    class FakeProvider:
        calls = 0

        def generate(self, prompt: str, *, model_name=None, **kwargs):
            FakeProvider.calls += 1
            return f"out:{prompt}:{model_name}:{kwargs.get('temperature', None)}"

    ipfs_backend = FakeIPFSBackend()

    # First deps creates and writes remote cache (mapping stored via DistributedGitHubCache to disk).
    deps1 = RouterDeps(ipfs_backend=ipfs_backend)
    remote1 = make_ipfs_remote_cache(deps=deps1, ipfs_backend=ipfs_backend, ttl_seconds=3600, broadcast=False)
    deps1.remote_cache = remote1

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

    # Second deps uses same mapping cache instance to simulate pointer sharing.
    deps2 = RouterDeps(ipfs_backend=ipfs_backend)
    deps2.remote_cache = remote1

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
    assert FakeProvider.calls == 1
