from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.caching import cache as cache_module
from ipfs_datasets_py.caching import distributed_cache as distributed_cache_module
from ipfs_datasets_py.caching import task_p2p_cache as task_p2p_cache_module
from ipfs_datasets_py.ml.accelerate_integration import p2p_task_client


def test_github_cache_global_p2p_defaults_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CACHE_ENABLE_P2P", raising=False)
    monkeypatch.setattr(cache_module, "_global_cache", None)

    cache = cache_module.get_global_cache(cache_dir=str(tmp_path), enable_persistence=False)

    assert cache.enable_p2p is False


def test_github_cache_explicit_p2p_requires_encryption(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cache_module, "HAVE_LIBP2P", True)
    monkeypatch.setattr(cache_module, "HAVE_CRYPTO", True)
    monkeypatch.setattr(
        cache_module.GitHubAPICache,
        "_init_encryption",
        lambda self: (_ for _ in ()).throw(RuntimeError("missing shared secret")),
    )

    def _fail_if_started(self) -> None:
        raise AssertionError("custom cache p2p must not start without encryption")

    monkeypatch.setattr(cache_module.GitHubAPICache, "_init_p2p", _fail_if_started)

    cache = cache_module.GitHubAPICache(
        cache_dir=str(tmp_path),
        enable_persistence=False,
        enable_p2p=True,
    )

    assert cache.enable_p2p is False


def test_github_cache_refuses_plaintext_p2p_messages(tmp_path) -> None:
    cache = cache_module.GitHubAPICache(
        cache_dir=str(tmp_path),
        enable_persistence=False,
        enable_p2p=False,
    )

    with pytest.raises(RuntimeError, match="refusing plaintext"):
        cache._encrypt_message({"key": "value"})
    assert cache._decrypt_message(b'{"key": "value"}') is None


def test_distributed_cache_p2p_defaults_local_only(tmp_path) -> None:
    cache = distributed_cache_module.DistributedGitHubCache(cache_dir=tmp_path)

    assert cache.libp2p_enabled is False


def test_distributed_cache_explicit_p2p_requires_encryption(monkeypatch, tmp_path) -> None:
    def _fail_if_configured(*args, **kwargs) -> bool:
        raise AssertionError("distributed cache must not configure libp2p without encryption")

    monkeypatch.delenv("CACHE_P2P_SHARED_SECRET", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET", raising=False)
    monkeypatch.delenv("IPFS_ACCELERATE_PY_CACHE_P2P_SHARED_SECRET", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(distributed_cache_module, "configure_libp2p", _fail_if_configured)

    cache = distributed_cache_module.DistributedGitHubCache(
        cache_dir=tmp_path,
        enable_p2p=True,
    )

    assert cache.libp2p_enabled is False


def test_distributed_cache_refuses_plaintext_p2p_messages(tmp_path) -> None:
    cache = distributed_cache_module.DistributedGitHubCache(cache_dir=tmp_path)

    with pytest.raises(RuntimeError, match="encryption is not configured"):
        cache._encode_p2p_message({"type": "cache_entry"})
    assert cache._decode_p2p_message(b'{"type": "cache_entry"}') is None


def test_distributed_cache_p2p_messages_are_encrypted(tmp_path) -> None:
    cache = distributed_cache_module.DistributedGitHubCache(
        cache_dir=tmp_path,
        enable_p2p=True,
        p2p_shared_secret="secret",
    )

    assert cache.libp2p_enabled is False

    payload = {"type": "cache_request", "key": "abc"}
    encoded = cache._encode_p2p_message(payload)

    assert encoded != b'{"type":"cache_request","key":"abc"}'
    assert cache._decode_p2p_message(encoded) == payload


def test_github_cache_task_p2p_remote_hit_populates_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "/ip4/127.0.0.1/tcp/9999/p2p/test")

    remote_store = {}

    def fake_cache_get_sync(*, remote, key, timeout_s=10.0):
        return {"ok": True, "hit": key in remote_store, "value": remote_store.get(key)}

    monkeypatch.setattr(p2p_task_client, "cache_get_sync", fake_cache_get_sync)

    cache = cache_module.GitHubAPICache(
        cache_dir=str(tmp_path),
        enable_persistence=False,
        enable_task_p2p_cache=True,
        default_ttl=60,
    )
    cache_key = cache._make_cache_key("op", "a", x=1)
    remote_store[cache_key] = cache._task_p2p_cache.encrypt_value(
        {
            "cache_key": cache_key,
            "data": {"ok": True},
            "timestamp": time.time(),
            "ttl": 60,
            "content_hash": None,
            "validation_fields": None,
        }
    )

    assert cache.get("op", "a", x=1) == {"ok": True}
    stats = cache.get_stats()
    assert stats["peer_hits"] == 1
    assert stats["api_calls_saved"] == 1
    assert stats["p2p_transport"] == "mcpplusplus-taskqueue-cache"
    assert stats["task_p2p_cache_enabled"] is True


def test_github_cache_task_p2p_write_through_is_encrypted(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "/ip4/127.0.0.1/tcp/9999/p2p/test")

    remote_store = {}

    def fake_cache_set_sync(*, remote, key, value, ttl_s=None, timeout_s=10.0):
        remote_store[key] = value
        return {"ok": True}

    monkeypatch.setattr(p2p_task_client, "cache_set_sync", fake_cache_set_sync)

    cache = cache_module.GitHubAPICache(
        cache_dir=str(tmp_path),
        enable_persistence=False,
        enable_task_p2p_cache=True,
        default_ttl=60,
    )

    cache.put("op2", {"v": 1}, ttl=30, k="z")

    cache_key = cache._make_cache_key("op2", k="z")
    wrapped = remote_store[cache_key]
    assert wrapped.get("enc") == "fernet-v1"
    assert cache._task_p2p_cache.decrypt_value(wrapped)["data"] == {"v": 1}


def test_distributed_cache_task_p2p_remote_hit_populates_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "/ip4/127.0.0.1/tcp/9999/p2p/test")

    remote_store = {}

    def fake_cache_get_sync(*, remote, key, timeout_s=10.0):
        return {"ok": True, "hit": key in remote_store, "value": remote_store.get(key)}

    monkeypatch.setattr(p2p_task_client, "cache_get_sync", fake_cache_get_sync)

    cache = distributed_cache_module.DistributedGitHubCache(
        cache_dir=tmp_path,
        enable_task_p2p_cache=True,
        p2p_shared_secret="secret",
        default_ttl=60,
    )
    entry = distributed_cache_module.CacheEntry(
        key="abc",
        data={"ok": True},
        timestamp=time.time(),
        ttl=60,
        content_hash=distributed_cache_module.ContentHasher.hash_content({"ok": True}),
    )
    remote_store["abc"] = cache._task_p2p_cache.encrypt_value({"entry": entry.to_dict()})

    assert cache.get("abc") == {"ok": True}
    assert "abc" in cache.local_cache
    stats = cache.get_stats()
    assert stats["peer_hits"] == 1
    assert stats["api_calls_saved"] == 1
    assert stats["p2p_transport"] == "mcpplusplus-taskqueue-cache"


def test_distributed_cache_task_p2p_async_write_through_is_encrypted(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "/ip4/127.0.0.1/tcp/9999/p2p/test")

    remote_store = {}

    async def fake_cache_set(*, remote, key, value, ttl_s=None, timeout_s=10.0):
        remote_store[key] = value
        return {"ok": True}

    monkeypatch.setattr(p2p_task_client, "cache_set", fake_cache_set)

    cache = distributed_cache_module.DistributedGitHubCache(
        cache_dir=tmp_path,
        enable_task_p2p_cache=True,
        p2p_shared_secret="secret",
        default_ttl=60,
    )

    asyncio.run(cache.set("abc", {"v": 2}, ttl=30))

    wrapped = remote_store["abc"]
    assert wrapped.get("enc") == "fernet-v1"
    assert cache._task_p2p_cache.decrypt_value(wrapped)["entry"]["data"] == {"v": 2}


def test_cache_modules_use_no_legacy_raw_stream_protocols() -> None:
    forbidden = [
        "set_stream_handler",
        "new_stream(",
        "stream.read(",
        "stream.write(",
        "new_libp2p_host",
        "peerinfo_from_multiaddr",
    ]

    offenders = {}
    for module in (cache_module, distributed_cache_module, task_p2p_cache_module):
        text = Path(module.__file__).read_text(encoding="utf-8")
        hits = [pattern for pattern in forbidden if pattern in text]
        if hits:
            offenders[module.__name__] = hits

    assert offenders == {}
