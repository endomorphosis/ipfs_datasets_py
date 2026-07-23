"""Persistent shared fetch cache for legal web scraping workflows.

This cache stores URL-keyed payloads locally and can optionally mirror them
through the IPFS backend router so repeated scraping attempts can reuse prior
results instead of refetching the same pages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_BINARY_JSON_MARKER = "__ipfs_datasets_py_binary_v1__"


def encode_cache_json_value(value: Any) -> Any:
    """Convert cache payload values into JSON-safe equivalents."""
    if isinstance(value, bytes):
        return {
            _BINARY_JSON_MARKER: True,
            "encoding": "base64",
            "length": len(value),
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, bytearray):
        return encode_cache_json_value(bytes(value))
    if isinstance(value, dict):
        return {str(key): encode_cache_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode_cache_json_value(item) for item in value]
    return value


def decode_cache_json_value(value: Any) -> Any:
    """Restore binary values encoded by encode_cache_json_value."""
    if isinstance(value, dict):
        if value.get(_BINARY_JSON_MARKER) is True and value.get("encoding") == "base64":
            try:
                return base64.b64decode(str(value.get("data") or "").encode("ascii"))
            except Exception:
                return b""
        return {key: decode_cache_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_cache_json_value(item) for item in value]
    return value


class SharedFetchCache:
    """URL-addressed cache with optional IPFS mirroring."""

    def __init__(
        self,
        *,
        cache_dir: Optional[str] = None,
        enable_ipfs_mirroring: bool = False,
    ) -> None:
        self.cache_dir = Path(
            cache_dir
            or os.environ.get("IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR")
            or os.environ.get("LEGAL_SCRAPER_FETCH_CACHE_DIR")
            or (Path.home() / ".cache" / "ipfs_datasets_py" / "legal_fetch_cache")
        ).expanduser().resolve()
        self.enable_ipfs_mirroring = bool(enable_ipfs_mirroring)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Optional["SharedFetchCache"]:
        enabled = cls._env_bool(
            "IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED",
            "LEGAL_SCRAPER_FETCH_CACHE_ENABLED",
        )
        if enabled is False:
            return None

        mirror = cls._env_bool(
            "IPFS_DATASETS_LEGAL_FETCH_CACHE_IPFS_MIRROR",
            "LEGAL_SCRAPER_FETCH_CACHE_IPFS_MIRROR",
        )
        return cls(enable_ipfs_mirroring=bool(mirror))

    @staticmethod
    def _env_bool(*names: str) -> Optional[bool]:
        for name in names:
            raw = str(os.environ.get(name) or "").strip().lower()
            if not raw:
                continue
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
        return None

    @staticmethod
    def normalize_url(url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""

        split = urlsplit(value)
        scheme = (split.scheme or "https").lower()
        netloc = split.netloc.lower()
        path = split.path or "/"
        query_pairs = parse_qsl(split.query, keep_blank_values=True)
        query = urlencode(sorted(query_pairs))
        return urlunsplit((scheme, netloc, path, query, ""))

    def _cache_key(self, *, namespace: str, url: str) -> str:
        normalized_url = self.normalize_url(url)
        digest = hashlib.sha256(f"{namespace}\n{normalized_url}".encode("utf-8")).hexdigest()
        return digest

    def _index_path(self, *, namespace: str, key: str) -> Path:
        return self.cache_dir / namespace / "index" / f"{key}.json"

    def _payload_path(self, *, namespace: str, key: str) -> Path:
        return self.cache_dir / namespace / "payload" / f"{key}.json"

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def load(self, *, namespace: str, url: str) -> Optional[Dict[str, Any]]:
        key = self._cache_key(namespace=namespace, url=url)
        index_path = self._index_path(namespace=namespace, key=key)
        payload_path = self._payload_path(namespace=namespace, key=key)

        try:
            if not index_path.exists() or not payload_path.exists():
                return None

            with index_path.open("r", encoding="utf-8") as handle:
                index_payload = json.load(handle)
            with payload_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if not isinstance(index_payload, dict) or not isinstance(payload, dict):
                return None

            payload = decode_cache_json_value(payload)
            payload["_cache"] = {
                "namespace": namespace,
                "cache_key": key,
                "cached_at": index_payload.get("cached_at"),
                "ipfs_cid": index_payload.get("ipfs_cid"),
                "normalized_url": index_payload.get("normalized_url"),
            }
            return payload
        except Exception as exc:
            logger.warning("Shared fetch cache read failed for %s: %s", url, exc)
            return None

    def save(
        self,
        *,
        namespace: str,
        url: str,
        payload: Dict[str, Any],
        payload_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = self._cache_key(namespace=namespace, url=url)
        index_path = self._index_path(namespace=namespace, key=key)
        payload_path = self._payload_path(namespace=namespace, key=key)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.parent.mkdir(parents=True, exist_ok=True)

        normalized_url = self.normalize_url(url)
        cached_at = datetime.now(timezone.utc).isoformat()
        serializable_payload = encode_cache_json_value(dict(payload))
        serializable_payload.pop("_cache", None)

        self._write_json_atomic(payload_path, serializable_payload)

        ipfs_cid = None
        if self.enable_ipfs_mirroring:
            ipfs_cid = self._mirror_payload_to_ipfs(
                namespace=namespace,
                key=key,
                payload=serializable_payload,
                payload_name=payload_name,
            )

        index_payload = {
            "namespace": namespace,
            "cache_key": key,
            "url": url,
            "normalized_url": normalized_url,
            "cached_at": cached_at,
            "payload_path": str(payload_path),
            "ipfs_cid": ipfs_cid,
        }
        self._write_json_atomic(index_path, index_payload)

        return index_payload

    def _mirror_payload_to_ipfs(
        self,
        *,
        namespace: str,
        key: str,
        payload: Dict[str, Any],
        payload_name: Optional[str],
    ) -> Optional[str]:
        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router

            data = json.dumps(
                {
                    "name": payload_name or f"{namespace}_{key[:16]}",
                    "namespace": namespace,
                    "cache_key": key,
                    "payload": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            cid = str(ipfs_router.add_bytes(data, pin=True) or "").strip()
            return cid or None
        except Exception as exc:
            logger.warning("Shared fetch cache IPFS mirror failed for %s/%s: %s", namespace, key, exc)
        return None
