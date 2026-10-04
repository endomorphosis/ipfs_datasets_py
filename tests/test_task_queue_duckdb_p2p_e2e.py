from __future__ import annotations

import json
import os
import socket
import time
import importlib.util

import pytest


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@pytest.mark.skipif(
    not _truthy_env("IPFS_DATASETS_PY_RUN_P2P_E2E_TESTS"),
    reason="Set IPFS_DATASETS_PY_RUN_P2P_E2E_TESTS=1 to run libp2p end-to-end tests",
)
@pytest.mark.skipif(
    not _truthy_env("IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS"),
    reason="Set IPFS_DATASETS_PY_RUN_HF_INTEGRATION_TESTS=1 to run HF/accelerate integration tests",
)
@pytest.mark.skipif(
    importlib.util.find_spec("libp2p") is None,
    reason="libp2p not installed; install with ipfs_datasets_py[p2p]",
)
def test_duckdb_task_queue_p2p_end_to_end(tmp_path, monkeypatch) -> None:
    """End-to-end over libp2p: remote submit -> local worker -> remote wait."""

    queue_path = tmp_path / "task_queue.duckdb"
    announce_path = tmp_path / "announce.json"
    listen_port = _free_tcp_port()

    # Configure service announce for test.
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_PUBLIC_IP", "127.0.0.1")
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_LISTEN_PORT", str(listen_port))
    monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_ANNOUNCE_FILE", str(announce_path))

    from ipfs_datasets_py.ml.accelerate_integration.p2p_task_service import serve_task_queue

    import anyio

    async def _run() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(serve_task_queue, queue_path=str(queue_path), listen_port=listen_port)

            # Wait for announce file.
            deadline = time.time() + 10.0
            while not announce_path.exists() and time.time() < deadline:
                await anyio.sleep(0.05)

            assert announce_path.exists(), "p2p service did not announce in time"
            info = json.loads(announce_path.read_text(encoding="utf-8"))
            multiaddr = str(info.get("multiaddr") or "")
            assert "/p2p/" in multiaddr

            # Configure llm_router to submit/wait via this remote service.
            monkeypatch.setenv("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", multiaddr)

            from ipfs_datasets_py import llm_router
            from ipfs_datasets_py.ml.accelerate_integration.worker import run_worker

            task_id = llm_router.submit_task(
                prompt="Return the word 'hello'.",
                model_name=os.environ.get("IPFS_DATASETS_PY_LLM_MODEL", "gpt2"),
                max_new_tokens=16,
                temperature=0.2,
            )

            # Process the task locally (worker reads the same DuckDB queue file).
            rc = run_worker(queue_path=str(queue_path), worker_id="worker-test", once=True)
            assert rc == 0

            # Wait remotely for completion.
            task = llm_router.wait_task(task_id, timeout_s=30.0)
            assert isinstance(task, dict)
            assert task.get("status") == "completed"
            result = task.get("result")
            assert isinstance(result, dict)
            assert isinstance(result.get("text"), str)
            assert result.get("text")

            tg.cancel_scope.cancel()

    anyio.run(_run)
