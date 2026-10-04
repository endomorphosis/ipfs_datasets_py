def test_ipfs_datasets_accepts_injected_cross_package_deps():
    from ipfs_datasets_py.ipfs_datasets import ipfs_datasets_py

    class DummyKit:
        pass

    class DummyAccelerate:
        pass

    deps = object()
    kit = DummyKit()
    accel = DummyAccelerate()

    resources = {"deps": deps}
    manager = ipfs_datasets_py(resources=resources, deps=deps, ipfs_kit=kit, ipfs_accelerate=accel)

    assert manager.deps is deps
    assert manager.ipfs_kit is kit
    assert manager.ipfs_accelerate is accel

    # Ensure the resources dict retains injected references for downstream reuse.
    assert resources["deps"] is deps
    assert resources["ipfs_kit"] is kit
    assert resources["ipfs_accelerate"] is accel
