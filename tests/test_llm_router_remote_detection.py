import os
from typing import Any

import pytest


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def test_remote_inference_detected_via_libp2p_backend_manager(monkeypatch):
    """Integration-ish test for detecting *remote* inference execution.

    This test only runs when a libp2p/P2P backend is registered in the
    ipfs_accelerate_py backend manager.
    """

    if not _truthy(os.getenv("IPFS_DATASETS_PY_RUN_REMOTE_INTEGRATION_TESTS")):
        pytest.skip("Set IPFS_DATASETS_PY_RUN_REMOTE_INTEGRATION_TESTS=1 to run remote inference tests")

    monkeypatch.setenv("IPFS_ACCELERATE_PY_ENABLE_BACKEND_MANAGER", "1")

    try:
        from ipfs_accelerate_py.inference_backend_manager import BackendType, get_backend_manager
    except Exception:
        pytest.skip("ipfs_accelerate_py backend manager not available")

    manager = get_backend_manager()

    p2p_backends = [
        b
        for b in manager.list_backends(task="text-generation")
        if getattr(b, "backend_type", None) == BackendType.P2P
        and "libp2p" in set(getattr(getattr(b, "capabilities", None), "protocols", set()) or set())
    ]
    if not p2p_backends:
        pytest.skip(
            "No libp2p/P2P text-generation backends registered. "
            "Start a remote inference node and register it with InferenceBackendManager "
            "(backend_type='p2p', protocols include 'libp2p')."
        )

    selected: dict[str, Any] = {"backend": None}
    original_select = manager.select_backend_for_task

    def _wrapped_select_backend_for_task(*args: Any, **kwargs: Any):
        backend = original_select(*args, **kwargs)
        selected["backend"] = backend
        return backend

    manager.select_backend_for_task = _wrapped_select_backend_for_task  # type: ignore[assignment]

    # Exercise the backend-manager provider path.
    from ipfs_accelerate_py import llm_router as accel_llm_router
    from ipfs_accelerate_py.router_deps import RouterDeps

    deps = RouterDeps()

    out = accel_llm_router.generate_text(
        "ping",
        provider="backend_manager",
        model_name=os.getenv("IPFS_DATASETS_PY_TEST_REMOTE_MODEL", "gpt2"),
        deps=deps,
        max_new_tokens=4,
    )

    assert isinstance(out, str) and out.strip()

    backend = selected.get("backend")
    assert backend is not None, "backend selection was not observed"
    assert getattr(backend, "backend_type", None) == BackendType.P2P
    assert "libp2p" in set(getattr(getattr(backend, "capabilities", None), "protocols", set()) or set())
