"""P2P TaskQueue + cache service integration for the MCP server.

This module integrates the Trio/libp2p TaskQueue service (from ipfs_accelerate_py)
into the anyio-based MCP server runtime.

Design:
- Keep stdio MCP transport as the primary interface.
- Run the Trio/libp2p service in-process using the existing background-thread
  runner provided by ipfs_accelerate_py.p2p_tasks.runtime.
- Expose local status via lightweight helper methods; tooling is exposed in
  mcp_server/tools/p2p_tools.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _ensure_ipfs_accelerate_on_path() -> None:
        """Make the nested ipfs_accelerate_py submodule importable.

        In this workspace, ipfs_accelerate_py is checked out at:
            ipfs_datasets_py/ipfs_accelerate_py/ipfs_accelerate_py/
        which is not on sys.path when running from the mono-repo root.
        """

        try:
                import sys

                # This file lives at: <root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/...
                # The submodule root is: <root>/ipfs_datasets_py
                submodule_root = Path(__file__).resolve().parents[2]
                candidate = submodule_root / "ipfs_accelerate_py"
                if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))
        except Exception:
                pass


_DEFAULT_QUEUE_PATH = os.path.join(os.path.expanduser("~"), ".cache", "ipfs_datasets_py", "task_queue.duckdb")


@dataclass
class P2PServiceState:
    running: bool
    peer_id: str
    listen_port: Optional[int]
    started_at: float
    last_error: str = ""


class P2PServiceManager:
    def __init__(
        self,
        *,
        enabled: bool,
        queue_path: str = _DEFAULT_QUEUE_PATH,
        listen_port: Optional[int] = None,
        enable_tools: bool = True,
        enable_cache: bool = True,
        auth_mode: str = "mcp_token",
        startup_timeout_s: float = 2.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.queue_path = str(queue_path or _DEFAULT_QUEUE_PATH)
        self.listen_port = int(listen_port) if listen_port is not None else None
        self.enable_tools = bool(enable_tools)
        self.enable_cache = bool(enable_cache)
        self.auth_mode = str(auth_mode or "mcp_token")
        self.startup_timeout_s = float(startup_timeout_s)

        self._runtime = None
        self._handle = None

        # Track environment variables we set so we can restore them on stop.
        # This avoids contaminating unrelated tests and subprocesses.
        self._env_restore: dict[str, Optional[str]] = {}

    def _setdefault_env(self, key: str, value: str) -> None:
        if key not in os.environ:
            self._env_restore.setdefault(key, None)
            os.environ[key] = value

    def _apply_env(self) -> None:
        self._setdefault_env("IPFS_ACCELERATE_PY_TASK_QUEUE_PATH", self.queue_path)
        self._setdefault_env("IPFS_DATASETS_PY_TASK_QUEUE_PATH", self.queue_path)
        self._setdefault_env(
            "IPFS_ACCELERATE_PY_TASK_P2P_ENABLE_TOOLS",
            "1" if self.enable_tools else "0",
        )
        self._setdefault_env(
            "IPFS_ACCELERATE_PY_TASK_P2P_ENABLE_CACHE",
            "1" if self.enable_cache else "0",
        )
        self._setdefault_env("IPFS_DATASETS_PY_TASK_P2P_ENABLE_CACHE", "1" if self.enable_cache else "0")

        # Let the service know it is being run as part of an MCP server process.
        self._setdefault_env("IPFS_ACCELERATE_PY_MCP_P2P_SERVICE", "1")

        # Auth routing hint used by the service handler fallback.
        self._setdefault_env("IPFS_DATASETS_PY_TASK_P2P_AUTH_MODE", self.auth_mode)
        self._setdefault_env("IPFS_ACCELERATE_PY_TASK_P2P_AUTH_MODE", self.auth_mode)

    def _restore_env(self) -> None:
        for key, prior in list(self._env_restore.items()):
            try:
                if prior is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prior
            except Exception:
                pass
        self._env_restore.clear()

    def start(self, *, accelerate_instance: Any | None = None) -> bool:
        """Start the libp2p TaskQueue service (best-effort)."""

        if not self.enabled:
            return False

        self._apply_env()

        _ensure_ipfs_accelerate_on_path()

        try:
            from ipfs_accelerate_py.p2p_tasks.runtime import TaskQueueP2PServiceRuntime
        except Exception:
            # ipfs_accelerate_py may not be importable in some deployments.
            return False

        if self._runtime is None:
            self._runtime = TaskQueueP2PServiceRuntime()

        self._handle = self._runtime.start(
            queue_path=self.queue_path,
            listen_port=self.listen_port,
            accelerate_instance=accelerate_instance,
        )

        # Best-effort wait for startup.
        try:
            self._handle.started.wait(timeout=max(0.0, self.startup_timeout_s))
        except Exception:
            pass

        return bool(getattr(self._runtime, "running", False))

    def stop(self) -> bool:
        if not self._runtime:
            return True
        try:
            ok = bool(self._runtime.stop(timeout_s=2.0))
            self._restore_env()
            return ok
        except Exception:
            self._restore_env()
            return False

    def state(self) -> P2PServiceState:
        """Return best-effort local P2P service state."""

        last_error = ""
        try:
            last_error = str(getattr(self._runtime, "last_error", "") or "") if self._runtime else ""
        except Exception:
            last_error = ""

        running = False
        peer_id = ""
        listen_port: Optional[int] = None
        started_at = 0.0

        _ensure_ipfs_accelerate_on_path()

        try:
            from ipfs_accelerate_py.p2p_tasks.service import get_local_service_state

            st = get_local_service_state() or {}
            running = bool(st.get("running"))
            peer_id = str(st.get("peer_id") or "")
            listen_port = st.get("listen_port") if isinstance(st.get("listen_port"), int) else None
            started_at = float(st.get("started_at") or 0.0)
        except Exception:
            # Fallback: infer from runtime thread.
            try:
                running = bool(getattr(self._runtime, "running", False))
            except Exception:
                running = False
            started_at = time.time() if running else 0.0

        return P2PServiceState(
            running=running,
            peer_id=peer_id,
            listen_port=listen_port,
            started_at=started_at,
            last_error=last_error,
        )
