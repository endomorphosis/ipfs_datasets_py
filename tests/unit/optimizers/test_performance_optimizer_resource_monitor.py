import types

import pytest


@pytest.mark.anyio
async def test_monitor_resources_returns_expected_keys(monkeypatch):
    from ipfs_datasets_py.optimizers import performance_optimizer

    # Patch psutil readings to avoid depending on the real machine.
    monkeypatch.setattr(performance_optimizer.psutil, "cpu_percent", lambda interval=1: 12.5)
    monkeypatch.setattr(
        performance_optimizer.psutil,
        "virtual_memory",
        lambda: types.SimpleNamespace(percent=34.0, available=8 * (1024**3)),
    )
    monkeypatch.setattr(
        performance_optimizer.psutil,
        "disk_usage",
        lambda path="/": types.SimpleNamespace(percent=56.0, free=100 * (1024**3)),
    )
    monkeypatch.setattr(performance_optimizer.os, "getloadavg", lambda: (1.0, 2.0, 3.0))

    optimizer = performance_optimizer.WebsiteProcessingOptimizer()
    resources = await optimizer.monitor_resources()

    assert resources["cpu_percent"] == 12.5
    assert resources["memory_percent"] == 34.0
    assert resources["available_memory_gb"] == 8.0
    assert resources["memory_available_gb"] == 8.0
    assert resources["disk_usage_percent"] == 56.0
    assert resources["disk_percent"] == 56.0
    assert resources["disk_free_gb"] == 100.0
    assert resources["load_average"] == (1.0, 2.0, 3.0)
    assert isinstance(resources["timestamp"], str)


@pytest.mark.anyio
async def test_monitor_resources_returns_fallback_on_typed_runtime_error(monkeypatch):
    from ipfs_datasets_py.optimizers import performance_optimizer

    optimizer = performance_optimizer.WebsiteProcessingOptimizer()
    monkeypatch.setattr(
        optimizer.resource_monitor,
        "get_current_resources",
        lambda: (_ for _ in ()).throw(RuntimeError("monitor failed")),
    )

    resources = await optimizer.monitor_resources()
    assert resources["cpu_percent"] == 0.0
    assert resources["memory_percent"] == 0.0
    assert resources["error"] == "monitor failed"


@pytest.mark.anyio
async def test_monitor_resources_does_not_swallow_keyboard_interrupt(monkeypatch):
    from ipfs_datasets_py.optimizers import performance_optimizer

    optimizer = performance_optimizer.WebsiteProcessingOptimizer()
    monkeypatch.setattr(
        optimizer.resource_monitor,
        "get_current_resources",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        await optimizer.monitor_resources()
