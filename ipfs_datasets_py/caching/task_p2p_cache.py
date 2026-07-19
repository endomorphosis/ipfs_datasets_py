"""MCP++ TaskQueue cache adapter.

This module is the safe distributed-cache path for datasets cache code. It uses
the TaskQueue cache RPCs exposed by ipfs_accelerate_py and never creates a raw
libp2p host or stream handler itself.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    HAVE_CRYPTO = True
except Exception:  # pragma: no cover - optional dependency
    Fernet = None  # type: ignore[assignment]
    PBKDF2HMAC = None  # type: ignore[assignment]
    default_backend = None  # type: ignore[assignment]
    hashes = None  # type: ignore[assignment]
    HAVE_CRYPTO = False


logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _falsy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "n", "off"}


class TaskP2PCacheAdapter:
    """Encrypted client for MCP++ TaskQueue cache RPCs."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        namespace: str = "ipfs-datasets-cache",
        shared_secret: Optional[str] = None,
        timeout_s: float = 10.0,
        wrap_namespace: bool = True,
    ) -> None:
        self.namespace = str(namespace or "ipfs-datasets-cache")
        self.timeout_s = float(timeout_s)
        self.wrap_namespace = bool(wrap_namespace)
        self.disabled_reason = ""
        self._cipher = None

        if enabled is None:
            disabled_raw = (
                os.environ.get("IPFS_DATASETS_PY_CACHE_DISABLE_TASK_P2P")
                or os.environ.get("IPFS_ACCELERATE_PY_CACHE_DISABLE_TASK_P2P")
                or os.environ.get("IPFS_DATASETS_PY_GITHUB_CACHE_DISABLE_TASK_P2P")
                or os.environ.get("IPFS_ACCELERATE_PY_GITHUB_CACHE_DISABLE_TASK_P2P")
            )
            requested = not _truthy(disabled_raw)
        else:
            requested = bool(enabled)

        self.requested = bool(requested)
        self.enabled = False
        if not self.requested:
            self.disabled_reason = "disabled"
            return

        if not HAVE_CRYPTO or Fernet is None or PBKDF2HMAC is None or hashes is None:
            self.disabled_reason = "missing_cryptography"
            return

        secret = (shared_secret or self._get_shared_secret()).strip()
        if not secret:
            self.disabled_reason = "missing_shared_secret"
            return

        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"github-task-p2p-cache",
                iterations=100_000,
                backend=default_backend(),
            )
            key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
            self._cipher = Fernet(key)
            self.enabled = True
        except Exception as exc:
            self.disabled_reason = f"encryption_init_failed:{type(exc).__name__}"

    def _get_shared_secret(self) -> str:
        token = (
            os.environ.get("IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET")
            or os.environ.get("IPFS_ACCELERATE_PY_CACHE_P2P_SHARED_SECRET")
            or os.environ.get("CACHE_P2P_SHARED_SECRET")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or ""
        ).strip()
        if token:
            return token

        try:
            import subprocess

            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return str(result.stdout or "").strip()
        except Exception:
            pass
        return ""

    @property
    def transport(self) -> str:
        return "mcpplusplus-taskqueue-cache" if self.enabled else "local-only"

    def mode(self) -> str:
        if not self.enabled:
            return self.disabled_reason or "disabled"
        if self._has_explicit_remote():
            return "explicit"
        if self._discovery_enabled():
            return "discovery"
        return "unconfigured"

    def _has_explicit_remote(self) -> bool:
        return bool(
            (
                os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR")
                or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR")
                or os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID")
                or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID")
                or ""
            ).strip()
        )

    def _discovery_enabled(self) -> bool:
        raw = (
            os.environ.get("IPFS_DATASETS_PY_GITHUB_CACHE_TASK_P2P_DISCOVERY")
            or os.environ.get("IPFS_ACCELERATE_PY_GITHUB_CACHE_TASK_P2P_DISCOVERY")
            or os.environ.get("IPFS_DATASETS_PY_TASK_P2P_DISCOVERY")
            or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_DISCOVERY")
            or ""
        )
        return _truthy(raw) and not _falsy(raw)

    def _remote(self):
        if not self.enabled:
            return None
        remote_peer_id = (
            os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID")
            or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID")
            or ""
        ).strip()
        remote_multiaddr = (
            os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR")
            or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR")
            or ""
        ).strip()
        if not remote_peer_id and not remote_multiaddr and not self._discovery_enabled():
            return None

        from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import RemoteQueue

        return RemoteQueue(peer_id=remote_peer_id, multiaddr=remote_multiaddr)

    def encrypt_value(self, value: Any) -> dict[str, Any]:
        if not self.enabled or self._cipher is None:
            raise RuntimeError("Task P2P cache encryption is not configured")
        payload = {"namespace": self.namespace, "value": value} if self.wrap_namespace else value
        plaintext = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return {"enc": "fernet-v1", "ct": self._cipher.encrypt(plaintext).decode("ascii")}

    def decrypt_value(self, wrapped: Any) -> Any | None:
        if not isinstance(wrapped, dict) or wrapped.get("enc") != "fernet-v1":
            return None
        ct = wrapped.get("ct")
        if not isinstance(ct, str) or not ct or self._cipher is None:
            return None
        try:
            plaintext = self._cipher.decrypt(ct.encode("ascii"))
            payload = json.loads(plaintext.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if not self.wrap_namespace:
            return payload
        if payload.get("namespace") != self.namespace:
            return None
        return payload.get("value")

    def get(self, key: str) -> Any | None:
        remote = self._remote()
        if remote is None or not key:
            return None
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_get_sync

            resp = cache_get_sync(remote=remote, key=str(key), timeout_s=float(self.timeout_s))
            if not isinstance(resp, dict) or not resp.get("ok") or not resp.get("hit"):
                return None
            return self.decrypt_value(resp.get("value"))
        except Exception:
            return None

    async def get_async(self, key: str) -> Any | None:
        remote = self._remote()
        if remote is None or not key:
            return None
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_get

            resp = await cache_get(remote=remote, key=str(key), timeout_s=float(self.timeout_s))
            if not isinstance(resp, dict) or not resp.get("ok") or not resp.get("hit"):
                return None
            return self.decrypt_value(resp.get("value"))
        except Exception:
            return None

    def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        remote = self._remote()
        if remote is None or not key:
            return
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_set_sync

            cache_set_sync(
                remote=remote,
                key=str(key),
                value=self.encrypt_value(value),
                ttl_s=ttl_s,
                timeout_s=float(self.timeout_s),
            )
        except Exception:
            return

    async def set_async(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        remote = self._remote()
        if remote is None or not key:
            return
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_set

            await cache_set(
                remote=remote,
                key=str(key),
                value=self.encrypt_value(value),
                ttl_s=ttl_s,
                timeout_s=float(self.timeout_s),
            )
        except Exception:
            return


__all__ = ["TaskP2PCacheAdapter"]
