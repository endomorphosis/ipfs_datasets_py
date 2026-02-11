"""Shared constants/helpers for the libp2p task queue protocol."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


PROTOCOL_V1 = "/ipfs-datasets/task-queue/1.0.0"


def get_shared_token() -> Optional[str]:
    token = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_TOKEN", "").strip()
    return token or None


def auth_ok(message: Dict[str, Any]) -> bool:
    expected = get_shared_token()
    if not expected:
        return True
    provided = (message.get("token") or "")
    return isinstance(provided, str) and provided == expected
