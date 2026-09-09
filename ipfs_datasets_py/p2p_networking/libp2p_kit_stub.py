"""LibP2P integration stub (explicit testing alias).

PCPR-011: effectful methods return typed Unavailable unless the caller
explicitly selects simulation. Simulated results are never represented as
live, and this stub never claims a successful transport effect.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any


LIBP2P_AVAILABLE = False


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _explicit_simulation(kwargs: dict[str, Any]) -> bool:
    if _truthy(kwargs.get("explicit_simulation")):
        return True
    return _truthy(os.environ.get("IPFS_DATASETS_EXPLICIT_SIMULATION"))


def _unavailable(operation: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "outcome": "Unavailable",
        "code": "libp2p_stub_unavailable",
        "message": message,
        "operation": operation,
        "ok": False,
        "disposition": "non_success",
        "live": False,
        "simulated": False,
        "simulated_represented_as_live": False,
        "durable_effect": False,
        "backend": "libp2p",
    }


def _simulated(operation: str, message: str) -> dict[str, Any]:
    return {
        "status": "simulated",
        "outcome": "Simulated",
        "code": "explicit_simulation",
        "message": message,
        "operation": operation,
        "ok": False,
        "disposition": "non_success",
        "live": False,
        "simulated": True,
        "simulated_represented_as_live": False,
        "durable_effect": False,
        "backend": "libp2p",
    }


class NodeRole(Enum):
    """Role of the node in the distributed network."""

    COORDINATOR = "coordinator"
    WORKER = "worker"
    HYBRID = "hybrid"
    CLIENT = "client"


class LibP2PNotAvailableError(Exception):
    """Raised when libp2p dependencies are not available."""


class P2PError(Exception):
    """Raised when P2P operations fail."""


class DistributedDatasetManager:
    """Unavailable libp2p manager unless explicit simulation is selected."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.explicit_simulation = _explicit_simulation(dict(kwargs))
        self.libp2p_available = False
        self.live = False
        self.shard_manager = (
            MockShardManager() if self.explicit_simulation else None
        )

    def create_distributed_dataset(self, *args: object, **kwargs: object) -> dict[str, Any]:
        if self.explicit_simulation or _explicit_simulation(dict(kwargs)):
            return _simulated(
                "create_distributed_dataset",
                "Explicit simulation of DistributedDatasetManager; not a live transport effect.",
            )
        return _unavailable(
            "create_distributed_dataset",
            "libp2p transport is unavailable; this stub does not create a distributed dataset.",
        )


class MockShardManager:
    """Simulation-only shard manager. Ordinary runtime must not treat it as live."""

    def get_dataset(self, dataset_id: str) -> "MockDataset":
        return MockDataset(dataset_id)


class MockDataset:
    """Simulation-only dataset handle. Save is Simulated or Unavailable, never success."""

    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id
        self.format = "json"

    async def save_async(self, *args: object, **kwargs: object) -> dict[str, Any]:
        if _explicit_simulation(dict(kwargs)):
            return _simulated(
                "save",
                "Explicit simulation of shard save; no durable bytes written.",
            )
        return _unavailable(
            "save",
            "libp2p shard save is unavailable; this stub writes no bytes.",
        )


__all__ = [
    "LIBP2P_AVAILABLE",
    "NodeRole",
    "LibP2PNotAvailableError",
    "P2PError",
    "DistributedDatasetManager",
]
