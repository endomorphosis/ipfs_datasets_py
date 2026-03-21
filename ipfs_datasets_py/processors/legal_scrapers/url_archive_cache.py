"""Durable URL-level cache for agentic legal web archiving."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urldefrag

logger = logging.getLogger(__name__)


@dataclass
class CachedArchiveEntry:
    """One cached URL capture."""

    url: str
    normalized_url: str
    content: str
    source: str
    cached_at: str
    cid: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class URLArchiveCache:
    """Local-first URL cache with optional IPFS persistence."""

    def __init__(
        self,
        *,
        metadata_dir: Optional[str] = None,
        persist_to_ipfs: bool = True,
    ) -> None:
        default_dir = Path.home() / ".cache" / "ipfs_datasets_py" / "legal_url_archive_cache"
        self.metadata_dir = Path(metadata_dir or default_dir).expanduser().resolve()
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.persist_to_ipfs = bool(persist_to_ipfs)

    @staticmethod
    def normalize_url(url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        value, _fragment = urldefrag(value)
        return value.strip()

    def _key_for_url(self, url: str) -> str:
        normalized = self.normalize_url(url)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        return self.metadata_dir / f"{key}.json"

    def get(self, url: str) -> Optional[CachedArchiveEntry]:
        normalized = self.normalize_url(url)
        if not normalized:
            return None

        path = self._path_for_key(self._key_for_url(normalized))
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed reading archive cache entry for %s: %s", normalized, exc)
            return None

        content = str(payload.get("content") or "")
        if not content:
            return None

        return CachedArchiveEntry(
            url=str(payload.get("url") or normalized),
            normalized_url=str(payload.get("normalized_url") or normalized),
            content=content,
            source=str(payload.get("source") or "cache"),
            cached_at=str(payload.get("cached_at") or ""),
            cid=str(payload.get("cid") or "") or None,
            metadata=dict(payload.get("metadata") or {}),
        )

    async def put(
        self,
        *,
        url: str,
        content: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized = self.normalize_url(url)
        text = str(content or "")
        if not normalized or not text:
            return {"status": "skipped", "reason": "empty-url-or-content"}

        payload: Dict[str, Any] = {
            "url": str(url or normalized),
            "normalized_url": normalized,
            "content": text,
            "source": str(source or "unknown"),
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }

        if self.persist_to_ipfs:
            try:
                from .ipfs_storage_integration import IPFSStorageManager

                manager = IPFSStorageManager(metadata_dir=str(self.metadata_dir / "ipfs_metadata"))
                ipfs_result = await manager.add_dataset(
                    name=f"url_archive_{self._key_for_url(normalized)}",
                    data=payload,
                    metadata={
                        "normalized_url": normalized,
                        "source": str(source or "unknown"),
                    },
                    format="json",
                    pin=False,
                )
                if ipfs_result.get("status") == "success":
                    payload["cid"] = ipfs_result.get("cid")
                else:
                    payload["ipfs_status"] = ipfs_result
            except Exception as exc:
                payload["ipfs_status"] = {"status": "error", "error": str(exc)}

        path = self._path_for_key(self._key_for_url(normalized))
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "status": "success",
            "path": str(path),
            "cid": payload.get("cid"),
        }
