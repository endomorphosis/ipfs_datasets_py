"""System Status MCP Tool.

This tool is intentionally best-effort and should never return fabricated
operational values.

We only report values we can actually observe in-process (e.g., env vars, file
existence, current PID, optional dependency availability). For external services
(IPFS daemon, swarm peer count, vector DB health), we return None/"unknown"
unless we can verify them.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _file_status(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "last_modified": None}
    try:
        return {
            "exists": True,
            "last_modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }
    except Exception:
        return {"exists": True, "last_modified": None}


async def system_status() -> Dict[str, Any]:
    """Get comprehensive system status information.

    Returns a structured dict describing what can be observed from within this
    process. External service health is reported as unknown unless verified.
    """

    try:
        timestamp = datetime.now().isoformat()

        ipfs_path = Path(os.environ.get("IPFS_PATH", str(Path.home() / ".ipfs")))

        services: Dict[str, Any] = {
            "ipfs_daemon": {
                "status": "unknown",
                "binary_found": bool(shutil.which("ipfs")),
                "ipfs_path": str(ipfs_path),
                "ipfs_path_exists": ipfs_path.exists(),
            },
            "mcp_server": {
                "status": "unknown",
                "current_process_pid": os.getpid(),
                "tools_loaded": None,
            },
        }

        # Optional dependency availability (proxy for feature support)
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
                ELASTICSEARCH_AVAILABLE,
                FAISS_AVAILABLE,
                QDRANT_AVAILABLE,
            )
        except Exception:
            ELASTICSEARCH_AVAILABLE = False
            FAISS_AVAILABLE = False
            QDRANT_AVAILABLE = False

        services["vector_stores"] = {
            "faiss": {"available": bool(FAISS_AVAILABLE)},
            "qdrant": {"available": bool(QDRANT_AVAILABLE)},
            "elasticsearch": {"available": bool(ELASTICSEARCH_AVAILABLE)},
        }

        configuration = {
            "config_files": {
                "configs.yaml": _file_status(Path("configs.yaml")),
                "config.yaml": _file_status(Path("config.yaml")),
                "pyproject.toml": _file_status(Path("pyproject.toml")),
            },
            "environment": {
                "IPFS_PATH": str(ipfs_path),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "virtual_env": os.environ.get("VIRTUAL_ENV", ""),
            },
        }

        databases = {
            "metadata_db": {"status": "unknown"},
            "audit_db": {"status": "unknown"},
        }

        network = {
            "ipfs_swarm": {
                "connected_peers": None,
                "listening_addresses": None,
            },
            "api_endpoints": {
                "mcp_server": {
                    "status": "unknown",
                    "endpoint": "stdio",
                    "tools_count": None,
                },
            },
        }

        resources = {
            "datasets": {"total_count": None, "total_size_bytes": None},
            "vector_indices": {"total_count": None, "total_size_bytes": None},
            "cache": {"hit_rate": None, "size_bytes": None},
        }

        security = {
            "authentication": {"status": "unknown"},
            "encryption": {"status": "unknown"},
            "access_control": {"status": "unknown"},
        }

        return {
            "success": True,
            "timestamp": timestamp,
            "overall_status": "unknown",
            "system_info": {
                "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "working_directory": os.getcwd(),
            },
            "services": services,
            "configuration": configuration,
            "databases": databases,
            "network": network,
            "resources": resources,
            "security": security,
            "issues": [],
            "warnings": [],
            "status_details": [],
        }

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
            "overall_status": "error",
        }
