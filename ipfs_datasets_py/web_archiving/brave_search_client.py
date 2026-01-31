"""Brave Search API Client with Caching and Advanced Features.

This module provides a standalone Brave Search client extracted and improved from
the common_crawl_search_engine submodule. It includes:

- Disk-based caching with TTL and LRU eviction
- File locking for concurrent access safety
- IPFS/libp2p content-addressed distributed caching
- Pagination metadata support
- Cache statistics and management
- Both sync and async interfaces

The client can be used by any web archiving tool in the package, not just Common Crawl.

Caching Strategy:
1. Check local file cache (fast)
2. Check IPFS cache if enabled (distributed)
3. Make API request if cache miss
4. Store in both local and IPFS cache
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal

logger = logging.getLogger(__name__)

# Try to import IPFS cache module
try:
    from .brave_search_ipfs_cache import BraveSearchIPFSCache
    HAVE_IPFS_CACHE = True
except ImportError:
    HAVE_IPFS_CACHE = False
    BraveSearchIPFSCache = None


def brave_web_search_max_count() -> int:
    """Return the maximum per-request result count supported by Brave web search.
    
    Brave enforces a server-side limit (commonly 20 for web search). This can be
    overridden via the BRAVE_SEARCH_MAX_COUNT environment variable.
    
    Returns:
        Maximum number of results per request (default: 20)
    """
    try:
        v = int((os.environ.get("BRAVE_SEARCH_MAX_COUNT") or "20").strip() or "20")
    except Exception:
        v = 20
    return max(1, int(v))


def _clamp_brave_count(count: int) -> int:
    """Clamp count to valid range for Brave Search API."""
    mx = brave_web_search_max_count()
    try:
        n = int(count)
    except Exception:
        n = mx
    if n < 1:
        return 1
    if n > mx:
        return mx
    return n


def _clamp_brave_offset(offset: int) -> int:
    """Clamp offset to valid range (non-negative)."""
    try:
        n = int(offset)
    except Exception:
        n = 0
    return 0 if n < 0 else n


def _brave_cache_path() -> Path:
    """Get the path to the Brave Search cache file.
    
    Priority:
    1. BRAVE_SEARCH_CACHE_PATH environment variable
    2. <state_dir>/brave_search_cache.json
    
    Returns:
        Path to cache file
    """
    # Prefer explicit override for testability and advanced use
    p = (os.environ.get("BRAVE_SEARCH_CACHE_PATH") or "").strip()
    if p:
        return Path(p).expanduser().resolve()
    
    # Default to state directory
    state_dir = Path((os.environ.get("CCINDEX_STATE_DIR") or "state").strip() or "state")
    return state_dir / "brave_search_cache.json"


def brave_search_cache_path() -> Path:
    """Return the on-disk Brave Search cache file path.
    
    Returns:
        Path to cache file
    """
    return _brave_cache_path()


def brave_search_cache_stats() -> Dict[str, Any]:
    """Return best-effort stats about the Brave Search on-disk cache.
    
    Returns:
        Dict containing:
            - path: Cache file path
            - exists: Whether cache file exists
            - entries: Number of cached queries
            - bytes: Cache file size in bytes
            - oldest_ts: Timestamp of oldest entry
            - newest_ts: Timestamp of newest entry
            - ttl_s: Cache TTL in seconds
            - disabled: Whether caching is disabled
    """
    path = _brave_cache_path()
    exists = path.exists() and path.is_file()
    size_bytes = int(path.stat().st_size) if exists else 0
    
    entries = 0
    newest_ts = None
    oldest_ts = None
    
    if exists:
        try:
            raw = path.read_text(encoding="utf-8").strip()
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                entries = len(data)
                for v in data.values():
                    if not isinstance(v, dict):
                        continue
                    ts = v.get("ts")
                    if not isinstance(ts, (int, float)):
                        continue
                    newest_ts = float(ts) if newest_ts is None else max(float(ts), float(newest_ts))
                    oldest_ts = float(ts) if oldest_ts is None else min(float(ts), float(oldest_ts))
        except Exception:
            pass
    
    return {
        "path": str(path),
        "exists": bool(exists),
        "entries": int(entries),
        "bytes": int(size_bytes),
        "oldest_ts": oldest_ts,
        "newest_ts": newest_ts,
        "ttl_s": int((os.environ.get("BRAVE_SEARCH_CACHE_TTL_S") or "86400").strip() or "86400"),
        "disabled": (os.environ.get("BRAVE_SEARCH_CACHE_DISABLE") or "").strip().lower()
        in {"1", "true", "yes", "on"},
    }


def clear_brave_search_cache() -> Dict[str, Any]:
    """Delete the Brave Search cache file if present.
    
    Returns:
        Dict containing:
            - deleted: Whether file was deleted
            - freed_bytes: Bytes freed
            - path: Cache file path
            - truncated: Whether file was truncated instead of deleted
    """
    path = _brave_cache_path()
    try:
        if path.exists() and path.is_file():
            try:
                freed = int(path.stat().st_size)
            except Exception:
                freed = 0
            try:
                path.unlink()
                return {"deleted": True, "freed_bytes": freed, "path": str(path)}
            except Exception:
                # Fallback: truncate
                try:
                    path.write_text("{}\n", encoding="utf-8")
                    return {"deleted": False, "freed_bytes": freed, "path": str(path), "truncated": True}
                except Exception:
                    return {"deleted": False, "freed_bytes": 0, "path": str(path)}
        return {"deleted": False, "freed_bytes": 0, "path": str(path)}
    except Exception:
        return {"deleted": False, "freed_bytes": 0, "path": str(path)}


def _brave_cache_key(*, q: str, count: int, offset: int, country: str, safesearch: str) -> str:
    """Generate a cache key for a Brave Search query.
    
    Args:
        q: Query string
        count: Number of results
        offset: Pagination offset
        country: Country code
        safesearch: Safesearch level
        
    Returns:
        SHA256 hash of the query parameters
    """
    payload = {
        "q": q,
        "count": int(count),
        "offset": int(offset),
        "country": str(country),
        "safesearch": str(safesearch),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _locked_cache_file(path: Path):
    """Context manager for locked cache file access.
    
    Uses fcntl file locking on Unix systems for concurrent access safety.
    Falls back to best-effort locking if fcntl is unavailable.
    
    Args:
        path: Path to cache file
        
    Yields:
        Open file handle
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Best-effort lock; if unavailable, proceed without locking
            pass
        yield f
    finally:
        try:
            f.close()
        except Exception:
            pass


def _load_cache_dict(f) -> Dict[str, dict]:
    """Load cache dictionary from file handle.
    
    Args:
        f: Open file handle positioned at start
        
    Returns:
        Cache dictionary
    """
    try:
        f.seek(0)
        raw = f.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache_dict(f, data: Dict[str, dict]) -> None:
    """Save cache dictionary to file handle.
    
    Args:
        f: Open file handle
        data: Cache dictionary to save
    """
    f.seek(0)
    f.truncate()
    json.dump(data, f, sort_keys=True, indent=2)
    f.write("\n")
    try:
        f.flush()
        os.fsync(f.fileno())
    except Exception:
        pass


def brave_web_search(
    query: str,
    *,
    api_key: Optional[str] = None,
    count: int = 10,
    offset: int = 0,
    country: str = "us",
    safesearch: str = "moderate",
) -> List[Dict[str, str]]:
    """Search the web using Brave Search API (synchronous version with caching).
    
    This is the core synchronous search function with disk-based caching support.
    
    Args:
        query: Search query string
        api_key: Brave Search API key (defaults to BRAVE_SEARCH_API_KEY env var)
        count: Number of results to return (1-20, default 10)
        offset: Pagination offset (default 0)
        country: Country code for search results (default "us")
        safesearch: Safe search filter level (default "moderate")
        
    Returns:
        List of dicts with keys: title, url, description
        
    Raises:
        RuntimeError: If API key is missing or API request fails
        
    Environment Variables:
        BRAVE_SEARCH_API_KEY: API key (required if not passed as parameter)
        BRAVE_SEARCH_CACHE_DISABLE: Set to "1"/"true" to disable caching
        BRAVE_SEARCH_CACHE_TTL_S: Cache TTL in seconds (default: 86400)
        BRAVE_SEARCH_CACHE_MAX_ENTRIES: Max cache entries (default: 1000)
        BRAVE_SEARCH_CACHE_PATH: Custom cache file path
    """
    token = (api_key or os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not token:
        raise RuntimeError("Missing BRAVE_SEARCH_API_KEY (set env var or pass api_key)")
    
    q = (query or "").strip()
    if not q:
        return []
    
    count = _clamp_brave_count(int(count))
    offset = _clamp_brave_offset(int(offset))
    
    # Check cache configuration
    cache_disable = (os.environ.get("BRAVE_SEARCH_CACHE_DISABLE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    ttl_s = int((os.environ.get("BRAVE_SEARCH_CACHE_TTL_S") or "86400").strip() or "86400")
    max_entries = int((os.environ.get("BRAVE_SEARCH_CACHE_MAX_ENTRIES") or "1000").strip() or "1000")
    cache_key = _brave_cache_key(q=q, count=int(count), offset=int(offset), country=str(country), safesearch=str(safesearch))
    
    # IPFS cache configuration
    ipfs_cache_enabled = (os.environ.get("BRAVE_SEARCH_IPFS_CACHE") or "").strip().lower() in {
        "1", "true", "yes", "on"
    } and HAVE_IPFS_CACHE
    ipfs_cache = None
    if ipfs_cache_enabled:
        try:
            ipfs_cache = BraveSearchIPFSCache()
            if not ipfs_cache.is_available():
                ipfs_cache = None
                logger.debug("IPFS cache not available, falling back to local cache only")
        except Exception as e:
            logger.debug(f"Failed to initialize IPFS cache: {e}")
            ipfs_cache = None
    
    # Try to retrieve from local cache first (fastest)
    if not cache_disable and ttl_s > 0:
        try:
            cache_path = _brave_cache_path()
            with _locked_cache_file(cache_path) as f:
                cache = _load_cache_dict(f)
                ent = cache.get(cache_key)
                if isinstance(ent, dict):
                    ts = ent.get("ts")
                    items = ent.get("items")
                    if isinstance(ts, (int, float)) and isinstance(items, list):
                        if (time.time() - float(ts)) <= float(ttl_s):
                            out_cached: List[Dict[str, str]] = []
                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                out_cached.append({
                                    "title": str(it.get("title") or ""),
                                    "url": str(it.get("url") or ""),
                                    "description": str(it.get("description") or ""),
                                })
                            logger.debug(f"Brave Search cache hit for query: {q}")
                            return out_cached
        except Exception as e:
            # Cache is best-effort; fall back to live request
            logger.debug(f"Local cache retrieval failed: {e}")
            pass
    
    # Try IPFS cache if local cache missed
    if ipfs_cache and not cache_disable:
        try:
            ipfs_result = ipfs_cache.retrieve(
                query=q,
                count=count,
                offset=offset,
                country=country,
                safesearch=safesearch
            )
            if ipfs_result:
                logger.info(f"Brave Search IPFS cache hit for query: {q}")
                return ipfs_result["results"]
        except Exception as e:
            logger.debug(f"IPFS cache retrieval failed: {e}")
            pass
    
    # Make live API request
    try:
        import requests
    except Exception as e:
        raise RuntimeError(
            "requests is required for Brave Search. Install with: pip install requests"
        ) from e
    
    url = "https://api.search.brave.com/res/v1/web/search"
    params = {
        "q": q,
        "count": int(count),
        "offset": int(offset),
        "country": str(country),
        "safesearch": str(safesearch),
    }
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": token,
    }
    
    logger.debug(f"Making Brave Search API request for query: {q}")
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Brave Search HTTP {resp.status_code}: {resp.text[:500]}")
    
    data = resp.json() if resp.content else {}
    web = data.get("web") if isinstance(data, dict) else None
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        return []
    
    out: List[Dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "title": str(it.get("title") or ""),
            "url": str(it.get("url") or ""),
            "description": str(it.get("description") or ""),
        })
    
    # Save to local cache
    if not cache_disable and ttl_s > 0:
        try:
            cache_path = _brave_cache_path()
            with _locked_cache_file(cache_path) as f:
                cache = _load_cache_dict(f)
                cache[cache_key] = {"ts": time.time(), "items": out}
                
                # LRU eviction if cache is too large
                if max_entries > 0 and len(cache) > max_entries:
                    def _ts(kv) -> float:
                        v = kv[1]
                        if isinstance(v, dict) and isinstance(v.get("ts"), (int, float)):
                            return float(v["ts"])
                        return 0.0
                    
                    keep = dict(sorted(cache.items(), key=_ts, reverse=True)[:int(max_entries)])
                    cache = keep
                
                _save_cache_dict(f, cache)
                logger.debug(f"Cached Brave Search results for query: {q}")
        except Exception as e:
            logger.debug(f"Failed to cache results: {e}")
            pass
    
    # Save to IPFS cache if enabled
    if ipfs_cache and not cache_disable:
        try:
            cid = ipfs_cache.store(
                query=q,
                results=out,
                count=count,
                offset=offset,
                country=country,
                safesearch=safesearch
            )
            if cid:
                logger.debug(f"Stored Brave Search results in IPFS: {cid}")
        except Exception as e:
            logger.debug(f"Failed to store in IPFS cache: {e}")
            pass
    
    return out


def brave_web_search_page(
    query: str,
    *,
    api_key: Optional[str] = None,
    count: int = 10,
    offset: int = 0,
    country: str = "us",
    safesearch: str = "moderate",
) -> Dict[str, Any]:
    """Brave web search that also returns pagination metadata.
    
    This is useful for implementing pagination in UI or knowing total result counts.
    
    Args:
        query: Search query string
        api_key: Brave Search API key
        count: Number of results to return (1-20)
        offset: Pagination offset
        country: Country code
        safesearch: Safe search filter level
        
    Returns:
        Dict containing:
            - items: List of search results (same format as brave_web_search)
            - meta: Pagination metadata with keys:
                - count: Requested count
                - offset: Requested offset
                - total: Total number of results (if available from API)
                - max_count: Maximum results per request
                - cached: Whether results came from cache
                - cache_age_s: Age of cached data in seconds (if cached)
    """
    token = (api_key or os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not token:
        raise RuntimeError("Missing BRAVE_SEARCH_API_KEY (set env var or pass api_key)")
    
    q = (query or "").strip()
    if not q:
        return {
            "items": [],
            "meta": {"count": 0, "offset": 0, "total": 0, "max_count": brave_web_search_max_count(), "cached": True},
        }
    
    count = _clamp_brave_count(int(count))
    offset = _clamp_brave_offset(int(offset))
    
    # Cache configuration
    cache_disable = (os.environ.get("BRAVE_SEARCH_CACHE_DISABLE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    ttl_s = int((os.environ.get("BRAVE_SEARCH_CACHE_TTL_S") or "86400").strip() or "86400")
    max_entries = int((os.environ.get("BRAVE_SEARCH_CACHE_MAX_ENTRIES") or "1000").strip() or "1000")
    cache_key = _brave_cache_key(q=q, count=int(count), offset=int(offset), country=str(country), safesearch=str(safesearch))
    
    # Try cache
    if not cache_disable and ttl_s > 0:
        try:
            cache_path = _brave_cache_path()
            with _locked_cache_file(cache_path) as f:
                cache = _load_cache_dict(f)
                ent = cache.get(cache_key)
                if isinstance(ent, dict):
                    ts = ent.get("ts")
                    items = ent.get("items")
                    meta = ent.get("meta")
                    if isinstance(ts, (int, float)) and isinstance(items, list):
                        if (time.time() - float(ts)) <= float(ttl_s):
                            out_cached: List[Dict[str, str]] = []
                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                out_cached.append({
                                    "title": str(it.get("title") or ""),
                                    "url": str(it.get("url") or ""),
                                    "description": str(it.get("description") or ""),
                                })
                            out_meta = meta if isinstance(meta, dict) else {}
                            total = out_meta.get("total")
                            total_int = int(total) if isinstance(total, (int, float)) else None
                            age_s = time.time() - float(ts)
                            return {
                                "items": out_cached,
                                "meta": {
                                    "count": int(count),
                                    "offset": int(offset),
                                    "total": total_int,
                                    "max_count": brave_web_search_max_count(),
                                    "cached": True,
                                    "cache_age_s": float(age_s),
                                },
                            }
        except Exception:
            pass
    
    # Make live API request
    try:
        import requests
    except Exception as e:
        raise RuntimeError(
            "requests is required for Brave Search. Install with: pip install requests"
        ) from e
    
    url = "https://api.search.brave.com/res/v1/web/search"
    params = {
        "q": q,
        "count": int(count),
        "offset": int(offset),
        "country": str(country),
        "safesearch": str(safesearch),
    }
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": token,
    }
    
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Brave Search HTTP {resp.status_code}: {resp.text[:500]}")
    
    data = resp.json() if resp.content else {}
    web = data.get("web") if isinstance(data, dict) else None
    
    # Extract total results if available
    total_int = None
    if isinstance(web, dict):
        # Brave's schema may expose totals under different keys
        for k in ("total", "total_results", "totalResults"):
            v = web.get(k)
            if isinstance(v, (int, float)):
                total_int = int(v)
                break
    
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        out_items: List[Dict[str, str]] = []
    else:
        out_items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out_items.append({
                "title": str(it.get("title") or ""),
                "url": str(it.get("url") or ""),
                "description": str(it.get("description") or ""),
            })
    
    # Save to cache
    if not cache_disable and ttl_s > 0:
        try:
            cache_path = _brave_cache_path()
            with _locked_cache_file(cache_path) as f:
                cache = _load_cache_dict(f)
                cache[cache_key] = {"ts": time.time(), "items": out_items, "meta": {"total": total_int}}
                
                # LRU eviction
                if max_entries > 0 and len(cache) > max_entries:
                    def _ts(kv) -> float:
                        v = kv[1]
                        if isinstance(v, dict) and isinstance(v.get("ts"), (int, float)):
                            return float(v["ts"])
                        return 0.0
                    
                    keep = dict(sorted(cache.items(), key=_ts, reverse=True)[:int(max_entries)])
                    cache = keep
                
                _save_cache_dict(f, cache)
        except Exception:
            pass
    
    return {
        "items": out_items,
        "meta": {
            "count": int(count),
            "offset": int(offset),
            "total": total_int,
            "max_count": brave_web_search_max_count(),
            "cached": False,
        },
    }


class BraveSearchClient:
    """High-level Brave Search client with configuration and state management.
    
    This class provides a more object-oriented interface to Brave Search with:
    - Configuration management
    - API key handling
    - Cache management
    - Queue support for batch operations
    
    Example:
        >>> client = BraveSearchClient(api_key="your-key")
        >>> results = client.search("python programming", count=20)
        >>> for result in results:
        ...     print(result['title'], result['url'])
        
        >>> # With pagination metadata
        >>> page = client.search_page("data science", count=10, offset=20)
        >>> print(f"Total results: {page['meta']['total']}")
        >>> print(f"Showing results {page['meta']['offset']} to {page['meta']['offset'] + len(page['items'])}")
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Brave Search client.
        
        Args:
            api_key: Brave Search API key (can use BRAVE_SEARCH_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self.config = {
            "country": "us",
            "safesearch": "moderate",
            "default_count": 10,
        }
        
        # Initialize IPFS cache if enabled
        self.ipfs_cache = None
        if HAVE_IPFS_CACHE:
            ipfs_cache_enabled = (os.environ.get("BRAVE_SEARCH_IPFS_CACHE") or "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if ipfs_cache_enabled:
                try:
                    self.ipfs_cache = BraveSearchIPFSCache()
                    if not self.ipfs_cache.is_available():
                        self.ipfs_cache = None
                except Exception:
                    self.ipfs_cache = None
    
    def search(
        self,
        query: str,
        count: Optional[int] = None,
        offset: int = 0,
        country: Optional[str] = None,
        safesearch: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Search the web using Brave Search API.
        
        Args:
            query: Search query string
            count: Number of results (defaults to configured default_count)
            offset: Pagination offset
            country: Country code (defaults to configured country)
            safesearch: Safesearch level (defaults to configured safesearch)
            
        Returns:
            List of search results
        """
        return brave_web_search(
            query,
            api_key=self.api_key,
            count=count or self.config["default_count"],
            offset=offset,
            country=country or self.config["country"],
            safesearch=safesearch or self.config["safesearch"],
        )
    
    def search_page(
        self,
        query: str,
        count: Optional[int] = None,
        offset: int = 0,
        country: Optional[str] = None,
        safesearch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search with pagination metadata.
        
        Args:
            query: Search query string
            count: Number of results
            offset: Pagination offset
            country: Country code
            safesearch: Safesearch level
            
        Returns:
            Dict with 'items' and 'meta' keys
        """
        return brave_web_search_page(
            query,
            api_key=self.api_key,
            count=count or self.config["default_count"],
            offset=offset,
            country=country or self.config["country"],
            safesearch=safesearch or self.config["safesearch"],
        )
    
    def configure(self, **kwargs) -> Dict[str, Any]:
        """Update client configuration.
        
        Args:
            **kwargs: Configuration options (country, safesearch, default_count, api_key)
            
        Returns:
            Current configuration
        """
        valid_keys = ["country", "safesearch", "default_count"]
        for key, value in kwargs.items():
            if key in valid_keys:
                self.config[key] = value
            elif key == "api_key":
                self.api_key = value
        
        return {
            "status": "success",
            "configuration": self.config,
            "api_key_set": bool(self.api_key),
        }
    
    def cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Cache statistics dict
        """
        return brave_search_cache_stats()
    
    def clear_cache(self) -> Dict[str, Any]:
        """Clear the search cache.
        
        Returns:
            Cache clearing result
        """
        return clear_brave_search_cache()
    
    def ipfs_cache_stats(self) -> Dict[str, Any]:
        """Get IPFS cache statistics.
        
        Returns:
            IPFS cache statistics dict
        """
        if self.ipfs_cache:
            return self.ipfs_cache.stats()
        else:
            return {
                "available": False,
                "message": "IPFS cache not enabled. Set BRAVE_SEARCH_IPFS_CACHE=1"
            }
    
    def ipfs_cache_clear_index(self) -> Dict[str, Any]:
        """Clear IPFS cache CID index.
        
        Returns:
            Clear result
        """
        if self.ipfs_cache:
            return self.ipfs_cache.clear_index()
        else:
            return {
                "status": "unavailable",
                "message": "IPFS cache not enabled"
            }
    
    def ipfs_cache_gc(self) -> Dict[str, Any]:
        """Garbage collect IPFS cache.
        
        Returns:
            GC result
        """
        if self.ipfs_cache:
            return self.ipfs_cache.gc()
        else:
            return {
                "status": "unavailable",
                "message": "IPFS cache not enabled"
            }
    
    def ipfs_cache_pin(self, cid: str) -> Dict[str, Any]:
        """Pin an IPFS cache entry.
        
        Args:
            cid: IPFS CID to pin
            
        Returns:
            Pin result
        """
        if self.ipfs_cache:
            return self.ipfs_cache.pin_entry(cid)
        else:
            return {
                "status": "unavailable",
                "message": "IPFS cache not enabled"
            }
    
    def ipfs_cache_unpin(self, cid: str) -> Dict[str, Any]:
        """Unpin an IPFS cache entry.
        
        Args:
            cid: IPFS CID to unpin
            
        Returns:
            Unpin result
        """
        if self.ipfs_cache:
            return self.ipfs_cache.unpin_entry(cid)
        else:
            return {
                "status": "unavailable",
                "message": "IPFS cache not enabled"
            }
    
    def ipfs_cache_list_pins(self) -> Dict[str, Any]:
        """List pinned IPFS cache entries.
        
        Returns:
            List of pinned CIDs
        """
        if self.ipfs_cache:
            return self.ipfs_cache.list_pins()
        else:
            return {
                "status": "unavailable",
                "message": "IPFS cache not enabled"
            }


__all__ = [
    "BraveSearchClient",
    "brave_web_search",
    "brave_web_search_page",
    "brave_search_cache_path",
    "brave_search_cache_stats",
    "clear_brave_search_cache",
    "brave_web_search_max_count",
]
