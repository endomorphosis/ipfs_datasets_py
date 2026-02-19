"""P2P TaskQueue + cache service integration for the MCP server.

This module integrates the Trio/libp2p TaskQueue service (from ipfs_accelerate_py)
into the anyio-based MCP server runtime.

Enhanced with MCP++ integration for:
- P2P Workflow Scheduler (distributed workflow execution)
- Peer Registry (peer discovery and connection management)
- Bootstrap (network initialization and bootstrap nodes)

Design:
- Keep stdio MCP transport as the primary interface.
- Run the Trio/libp2p service in-process using the existing background-thread
  runner provided by ipfs_accelerate_py.p2p_tasks.runtime.
- Integrate MCP++ workflow scheduler, peer registry, and bootstrap capabilities
- Gracefully degrade when MCP++ module unavailable
- Expose local status via lightweight helper methods; tooling is exposed in
  mcp_server/tools/p2p_tools.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .exceptions import (
    P2PServiceError,
    P2PConnectionError,
    P2PAuthenticationError,
    ConfigurationError,
)

logger = logging.getLogger(__name__)


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
    # MCP++ enhanced state
    workflow_scheduler_available: bool = False
    peer_registry_available: bool = False
    bootstrap_available: bool = False
    connected_peers: int = 0
    active_workflows: int = 0


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
        # MCP++ enhanced options
        enable_workflow_scheduler: bool = True,
        enable_peer_registry: bool = True,
        enable_bootstrap: bool = True,
        bootstrap_nodes: Optional[List[str]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.queue_path = str(queue_path or _DEFAULT_QUEUE_PATH)
        self.listen_port = int(listen_port) if listen_port is not None else None
        self.enable_tools = bool(enable_tools)
        self.enable_cache = bool(enable_cache)
        self.auth_mode = str(auth_mode or "mcp_token")
        self.startup_timeout_s = float(startup_timeout_s)

        # MCP++ enhanced options
        self.enable_workflow_scheduler = bool(enable_workflow_scheduler)
        self.enable_peer_registry = bool(enable_peer_registry)
        self.enable_bootstrap = bool(enable_bootstrap)
        self.bootstrap_nodes = bootstrap_nodes or []

        self._runtime = None
        self._handle = None

        # Track environment variables we set so we can restore them on stop.
        # This avoids contaminating unrelated tests and subprocesses.
        self._env_restore: dict[str, Optional[str]] = {}

        # MCP++ integration components (initialized on demand)
        self._workflow_scheduler = None
        self._peer_registry = None
        self._mcplusplus_available = False

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
            except ConfigurationError as e:
                logger.warning(f"Configuration error restoring environment variable {key}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error restoring environment variable {key}: {e}", exc_info=True)
        self._env_restore.clear()

    def start(self, *, accelerate_instance: Any | None = None) -> bool:
        """Start the libp2p TaskQueue service (best-effort).
        
        Also initializes MCP++ enhanced features if enabled:
        - Workflow scheduler
        - Peer registry
        - Bootstrap
        """

        if not self.enabled:
            return False

        self._apply_env()

        _ensure_ipfs_accelerate_on_path()

        try:
            from ipfs_accelerate_py.p2p_tasks.runtime import TaskQueueP2PServiceRuntime
        except ImportError as e:
            logger.warning(f"ipfs_accelerate_py not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error importing TaskQueueP2PServiceRuntime: {e}", exc_info=True)
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
        except P2PConnectionError as e:
            logger.error(f"P2P connection error during startup: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error waiting for P2P startup: {e}", exc_info=True)

        # Initialize MCP++ enhanced features
        self._initialize_mcplusplus_features()

        return bool(getattr(self._runtime, "running", False))

    def stop(self) -> bool:
        """Stop the P2P service and cleanup MCP++ features."""
        if not self._runtime:
            return True
        
        # Cleanup MCP++ features first
        self._cleanup_mcplusplus_features()
        
        try:
            ok = bool(self._runtime.stop(timeout_s=2.0))
            self._restore_env()
            return ok
        except P2PServiceError as e:
            logger.error(f"P2P service error during stop: {e}")
            self._restore_env()
            return False
        except Exception as e:
            logger.error(f"Unexpected error stopping P2P service: {e}", exc_info=True)
            self._restore_env()
            return False

    def state(self) -> P2PServiceState:
        """Return best-effort local P2P service state including MCP++ features."""

        last_error = ""
        try:
            last_error = str(getattr(self._runtime, "last_error", "") or "") if self._runtime else ""
        except P2PServiceError as e:
            logger.warning(f"P2P service error getting last error: {e}")
            last_error = str(e)
        except Exception as e:
            logger.warning(f"Unexpected error getting last error: {e}", exc_info=True)
            last_error = str(e)

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
        except P2PServiceError as e:
            logger.warning(f"P2P service error getting state: {e}")
            # Fallback: infer from runtime thread.
            try:
                running = bool(getattr(self._runtime, "running", False))
            except Exception:
                running = False
            started_at = time.time() if running else 0.0
        except Exception as e:
            logger.warning(f"Unexpected error getting service state: {e}", exc_info=True)
            # Fallback: infer from runtime thread.
            try:
                running = bool(getattr(self._runtime, "running", False))
            except Exception:
                running = False
            started_at = time.time() if running else 0.0

        # Get MCP++ enhanced state
        workflow_scheduler_available = self._workflow_scheduler is not None
        peer_registry_available = self._peer_registry is not None
        bootstrap_available = self._mcplusplus_available and self.enable_bootstrap
        
        connected_peers = 0
        active_workflows = 0
        
        # Best-effort connected peer count.
        # Prefer using the p2p_tasks service state if available (works even
        # when MCP++ peer registry is not present).
        try:
            from ipfs_accelerate_py.p2p_tasks.service import list_known_peers

            peers = list_known_peers(alive_only=True, limit=1000)
            if isinstance(peers, list):
                connected_peers = len(peers)
        except Exception:
            pass
        
        # Try to get active workflows count
        if self._workflow_scheduler is not None:
            try:
                # This would be implemented by the workflow scheduler
                active_workflows = 0  # TODO: Get from workflow scheduler
            except Exception:
                pass

        return P2PServiceState(
            running=running,
            peer_id=peer_id,
            listen_port=listen_port,
            started_at=started_at,
            last_error=last_error,
            workflow_scheduler_available=workflow_scheduler_available,
            peer_registry_available=peer_registry_available,
            bootstrap_available=bootstrap_available,
            connected_peers=connected_peers,
            active_workflows=active_workflows,
        )

    # MCP++ Integration Methods

    def _initialize_mcplusplus_features(self) -> None:
        """Initialize MCP++ enhanced features (workflow scheduler, peer registry, bootstrap)."""
        try:
            # Try to import MCP++ modules
            from ipfs_datasets_py.mcp_server import mcplusplus
            
            self._mcplusplus_available = mcplusplus.HAVE_MCPLUSPLUS
            
            if not self._mcplusplus_available:
                logger.info("MCP++ module not available - running with basic P2P only")
                return
            
            # Initialize workflow scheduler
            if self.enable_workflow_scheduler and mcplusplus.HAVE_WORKFLOW_SCHEDULER:
                try:
                    self._workflow_scheduler = mcplusplus.get_scheduler()
                    if self._workflow_scheduler:
                        logger.info("P2P workflow scheduler initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize workflow scheduler: {e}")
            
            # Initialize peer registry
            if self.enable_peer_registry and mcplusplus.HAVE_PEER_REGISTRY:
                try:
                    self._peer_registry = mcplusplus.create_peer_registry(
                        bootstrap_nodes=self.bootstrap_nodes
                    )
                    if self._peer_registry and self._peer_registry.available:
                        logger.info("P2P peer registry initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize peer registry: {e}")
            
            # Perform bootstrap if enabled
            if self.enable_bootstrap and mcplusplus.HAVE_BOOTSTRAP:
                try:
                    # Bootstrap will be performed asynchronously
                    logger.info("P2P bootstrap enabled (will connect on demand)")
                except Exception as e:
                    logger.warning(f"Failed to initialize bootstrap: {e}")
                    
        except Exception as e:
            logger.warning(f"Failed to initialize MCP++ features: {e}")
            self._mcplusplus_available = False

    def _cleanup_mcplusplus_features(self) -> None:
        """Cleanup MCP++ features on shutdown."""
        try:
            # Reset workflow scheduler
            if self._workflow_scheduler is not None:
                try:
                    from ipfs_datasets_py.mcp_server import mcplusplus
                    mcplusplus.reset_scheduler()
                except Exception:
                    pass
                self._workflow_scheduler = None
            
            # Cleanup peer registry
            self._peer_registry = None
            self._mcplusplus_available = False
            
        except Exception as e:
            logger.warning(f"Error during MCP++ cleanup: {e}")

    def get_workflow_scheduler(self) -> Optional[Any]:
        """Get the workflow scheduler instance if available.
        
        Returns:
            P2P workflow scheduler or None if not available
        """
        return self._workflow_scheduler

    def get_peer_registry(self) -> Optional[Any]:
        """Get the peer registry instance if available.
        
        Returns:
            Peer registry wrapper or None if not available
        """
        return self._peer_registry

    def has_advanced_features(self) -> bool:
        """Check if advanced MCP++ features are available.
        
        Returns:
            True if MCP++ features are available and initialized
        """
        return self._mcplusplus_available

    def get_capabilities(self) -> Dict[str, Any]:
        """Get capabilities of this P2P service manager.
        
        Returns:
            Dictionary with capability information
        """
        return {
            "p2p_enabled": self.enabled,
            "mcplusplus_available": self._mcplusplus_available,
            "workflow_scheduler": self._workflow_scheduler is not None,
            "peer_registry": self._peer_registry is not None,
            "bootstrap": self.enable_bootstrap and self._mcplusplus_available,
            "tools_enabled": self.enable_tools,
            "cache_enabled": self.enable_cache,
        }
