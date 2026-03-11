import pytest


@pytest.mark.asyncio
async def test_ipfs_storage_manager_router_add_bytes_supports_pin_kwarg(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import ipfs_storage_integration as storage_module

    captured = {}

    def _fake_add_bytes(data: bytes, *, pin: bool = True) -> str:
        captured["data"] = data
        captured["pin"] = pin
        return "bafytestcid"

    monkeypatch.setattr(storage_module, "IPFS_AVAILABLE", True)
    monkeypatch.setattr(storage_module.ipfs_router, "add_bytes", _fake_add_bytes)

    manager = storage_module.IPFSStorageManager(metadata_dir=str(tmp_path))
    result = await manager.add_dataset("router-review", {"hello": "world"}, format="json", pin=False)

    assert result["status"] == "success"
    assert result["cid"] == "bafytestcid"
    assert result["pinned"] is False
    assert captured["pin"] is False
    assert b'"hello": "world"' in captured["data"]