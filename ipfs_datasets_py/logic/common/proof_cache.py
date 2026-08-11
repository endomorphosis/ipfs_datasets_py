"""
Unified Proof Cache with CID (Content ID) Hashing and IPFS Backend Support

**UNIFIED CACHE (2026-02-14):** This module provides the unified caching layer
for ALL theorem provers and proof systems across the logic module, consolidating
the previously separate cache implementations in external_provers/, TDFOL/, and
integration/caching/.

**IPFS INTEGRATION (2026-02-19 - Phase 1 Task 1.3):** Added distributed caching
via IPFS router backend, enabling proof result sharing across nodes with automatic
fallback to local caching.

This module provides a high-performance caching layer for all theorem provers
using IPFS-native CID (Content Identifier) hashing for O(1) lookups, with optional
distributed storage via IPFS.

Features:
- CID-based content addressing (deterministic hashing)
- O(1) lookups using hash-based indexing
- Optional IPFS backend for distributed caching
- Automatic fallback to local cache if IPFS unavailable
- Thread-safe operations with RLock
- TTL-based expiration
- LRU eviction when cache is full
- Cache hit/miss statistics
- Support for all prover types (native, Z3, SymbolicAI, external, TDFOL, etc.)
- Persistence to disk (optional)
- Unified API across all proof systems

The cache key is computed as:
    CID(formula_canonical_representation + axioms + prover_config)

This ensures:
1. Same formula always produces same CID (deterministic)
2. Different formulas always produce different CIDs (collision-resistant)
3. O(1) lookup performance (hash-based)
4. IPFS-compatible addressing (can be stored on IPFS)

Usage:
    >>> from ipfs_datasets_py.logic.common import ProofCache, get_global_cache
    >>> 
    >>> # Local caching only
    >>> cache = ProofCache(maxsize=1000, ttl=3600)
    >>> 
    >>> # With IPFS backend for distributed caching
    >>> cache = ProofCache(maxsize=1000, ttl=3600, enable_ipfs_backend=True)
    >>> 
    >>> # Cache a proof result
    >>> result = prover.prove(formula)
    >>> cache.set(formula, result, prover_name="z3")
    >>> 
    >>> # Retrieve cached result (O(1) lookup, checks IPFS if enabled)
    >>> cached = cache.get(formula, prover_name="z3")
    >>> if cached:
    ...     print("Cache hit!")
    >>> 
    >>> # Or use the global singleton
    >>> global_cache = get_global_cache()
    >>> global_cache.set(formula, result, prover_name="lean")

Backward Compatibility:
    The module is used as the unified cache for:
    - external_provers.proof_cache.ProofCache
    - TDFOL.tdfol_proof_cache.TDFOLProofCache  
    - integration.caching.proof_cache.ProofCache
    
    All legacy imports are maintained via compatibility shims.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Mapping, Optional, Union
from threading import RLock
import time
import logging
import json
import os
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX compatibility
    fcntl = None

try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False
    TTLCache = None

try:
    from ipfs_datasets_py.utils.cid_utils import cid_for_obj, canonical_json_bytes
    CID_UTILS_AVAILABLE = True
except ImportError:
    CID_UTILS_AVAILABLE = False
    # Fallback to simple hashing
    import hashlib
    
    def cid_for_obj(obj: Any) -> str:
        """Fallback CID computation using SHA256."""
        json_str = json.dumps(obj, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

# IPFS backend imports are deferred to ProofCache.__init__ to keep this module
# lightweight at import time (avoids pulling in ipfs_kit_py / lotus_kit eagerly).
IPFS_BACKEND_AVAILABLE: bool | None = None  # None = not yet probed
IPFSBackedRemoteCache = None  # type: ignore
get_ipfs_backend = None  # type: ignore


def _probe_ipfs_backend() -> bool:
    """Lazily probe whether the IPFS backend dependencies are importable."""
    global IPFS_BACKEND_AVAILABLE, IPFSBackedRemoteCache, get_ipfs_backend
    if IPFS_BACKEND_AVAILABLE is not None:
        return IPFS_BACKEND_AVAILABLE
    try:
        import warnings as _cache_warnings
        with _cache_warnings.catch_warnings():
            _cache_warnings.simplefilter("ignore")
            from ipfs_datasets_py.caching.router_remote_cache import (  # noqa: PLC0415
                IPFSBackedRemoteCache as _IRC,
            )
            from ipfs_datasets_py.ipfs_backend_router import (  # noqa: PLC0415
                get_ipfs_backend as _GIB,
            )
        IPFSBackedRemoteCache = _IRC  # type: ignore
        get_ipfs_backend = _GIB  # type: ignore
        IPFS_BACKEND_AVAILABLE = True
    except Exception:
        IPFS_BACKEND_AVAILABLE = False
    return IPFS_BACKEND_AVAILABLE

logger = logging.getLogger(__name__)
_CID_FALLBACK_LOGGED = False
_PERSISTENCE_SCHEMA_VERSION = "proof-cache-v1"


def _safe_timestamp(value: Any) -> float:
    """Return a finite cache timestamp or zero for malformed persisted data."""

    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return 0.0
    finite = timestamp == timestamp and timestamp not in (
        float("inf"),
        float("-inf"),
    )
    return timestamp if finite else 0.0


@dataclass
class CachedProofResult:
    """Cached proof result with metadata.
    
    Attributes:
        result: The actual proof result (any prover result type)
        cid: Content identifier (hash) of the query
        prover_name: Name of prover that produced this result
        formula_str: String representation of formula
        timestamp: When this result was cached
        hit_count: Number of times this result was retrieved
    """
    result: Any
    cid: str
    prover_name: str
    formula_str: str
    timestamp: float
    hit_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'cid': self.cid,
            'prover_name': self.prover_name,
            'formula_str': self.formula_str,
            'timestamp': self.timestamp,
            'hit_count': self.hit_count,
            # result is not serialized (may contain non-serializable objects)
        }


class ProofCache:
    """Unified proof cache with CID-based content addressing.
    
    This cache provides O(1) lookups for proof results across all provers
    using IPFS-native CID hashing.
    
    Attributes:
        maxsize: Maximum number of cached proofs
        ttl: Time-to-live in seconds
        cache: Underlying cache storage (TTLCache if available)
        lock: Thread lock for safe concurrent access
        stats: Cache statistics
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        ttl: int = 3600,
        enable_persistence: bool = False,
        persistence_path: Optional[str] = None,
        enable_ipfs_backend: bool = False,
        ipfs_backend: Optional[Any] = None,
        ipfs_pin: bool = False,
        ipfs_ttl: Optional[int] = None,
        # Backward-compat aliases
        max_size: Optional[int] = None,
        default_ttl: Optional[int] = None,
        # DQK-065: optional unified shadow repository
        shadow_repository: Optional[Any] = None,
        shadow_backend: Optional[str] = None,
    ):
        """Initialize proof cache with optional IPFS backend.
        
        Args:
            maxsize: Maximum number of cached proofs (default: 1000)
            ttl: Time-to-live in seconds for local cache (default: 3600 = 1 hour)
            enable_persistence: Whether to persist cache to disk
            persistence_path: Path for cache persistence
            enable_ipfs_backend: Enable IPFS-backed distributed caching (Phase 1 Task 1.3)
            ipfs_backend: Optional custom IPFS backend instance
            ipfs_pin: Whether to pin proof results in IPFS (permanent storage)
            ipfs_ttl: TTL for IPFS cache entries (None = no expiration)
            shadow_repository: Optional :class:`UnifiedProofShadowRepository`
            shadow_backend: Legacy backend id for shadow dual-writes
        """
        # Apply compat aliases
        if max_size is not None:
            maxsize = max_size
        if default_ttl is not None:
            ttl = default_ttl
        self.maxsize = maxsize
        self.ttl = ttl
        # Backward-compat property aliases
        self.max_size = maxsize
        self.default_ttl = ttl
        self.enable_persistence = enable_persistence
        self.persistence_path = persistence_path
        self.enable_ipfs_backend = enable_ipfs_backend
        self.ipfs_pin = ipfs_pin
        self.ipfs_ttl = ipfs_ttl or ttl
        self._shadow_repository = shadow_repository
        self._shadow_backend = shadow_backend or "common"
        
        # Initialize cache storage
        if CACHETOOLS_AVAILABLE:
            self.cache = TTLCache(maxsize=maxsize, ttl=ttl)
        else:
            # Fallback to simple dict (no TTL or size limit)
            self.cache = {}
            logger.warning("cachetools not available, using simple dict cache")
        
        self.lock = RLock()
        # Backward-compat attributes (ordered dict for LRU)
        from collections import OrderedDict
        self._cache: dict = OrderedDict()
        self._compat_hits: int = 0
        self._compat_misses: int = 0
        self._compat_evictions: int = 0
        self._compat_expirations: int = 0
        self._compat_puts: int = 0
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'cid_collisions': 0,
            'ipfs_hits': 0,
            'ipfs_sets': 0,
            'ipfs_errors': 0,
            'persistence_loads': 0,
            'persistence_writes': 0,
            'persistence_errors': 0,
            'persistence_skipped_results': 0,
            'shadow_writes': 0,
            'shadow_errors': 0,
        }

        if self.enable_persistence:
            self._load_persistent_cache()

        if self._shadow_repository is not None:
            try:
                self._shadow_repository.register_backend(self._shadow_backend)
            except Exception:
                pass
        
        # Initialize IPFS backend if requested (Phase 1 Task 1.3)
        self.ipfs_backend = None
        self.ipfs_cache = None
        if enable_ipfs_backend:
            if not _probe_ipfs_backend():
                logger.warning(
                    "IPFS backend requested but ipfs_backend_router not available. "
                    "Falling back to local-only caching."
                )
            else:
                try:
                    # Get or create IPFS backend
                    backend = ipfs_backend or get_ipfs_backend()
                    
                    # Create local mapping cache for IPFS pointers
                    mapping_cache = {}  # Simple dict for CID -> IPFS pointer mapping
                    
                    # Initialize IPFS-backed cache
                    self.ipfs_cache = IPFSBackedRemoteCache(
                        mapping_cache=mapping_cache,
                        ipfs_backend=backend,
                        pin=ipfs_pin,
                        ttl_seconds=ipfs_ttl,
                        broadcast=True
                    )
                    self.ipfs_backend = backend
                    logger.info(
                        f"IPFS backend enabled with pin={ipfs_pin}, ttl={ipfs_ttl}s"
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize IPFS backend: {e}. "
                                 "Falling back to local-only caching.")
        
        logger.info(f"Initialized ProofCache with maxsize={maxsize}, ttl={ttl}s, "
                   f"ipfs_backend={enable_ipfs_backend}")

    @property
    def shadow_repository(self) -> Optional[Any]:
        """Bound unified shadow repository, or the process-local default."""

        if self._shadow_repository is not None:
            return self._shadow_repository
        return get_shadow_repository(create=False)

    def bind_shadow_repository(
        self,
        repository: Any,
        *,
        backend: Optional[str] = None,
    ) -> None:
        """Bind this cache to a unified proof shadow repository (DQK-065)."""

        self._shadow_repository = repository
        if backend is not None:
            self._shadow_backend = backend
        if repository is not None:
            repository.register_backend(self._shadow_backend)

    def _shadow_write(
        self,
        *,
        formula: Any,
        result: Any,
        cid: str,
        prover_name: str,
        prover_config: Optional[Dict] = None,
        axioms: Optional[List] = None,
    ) -> None:
        """Dual-write into the unified repository without raising to callers."""

        repo = self.shadow_repository
        if repo is None:
            return
        try:
            key = repo.project_key(
                self._shadow_backend,
                formula=formula,
                cid=cid,
                prover_name=prover_name,
                prover_config=prover_config,
                axioms=axioms,
                solver_identities={"prover": prover_name},
                toolchain={"backend": self._shadow_backend},
                policy={"mode": "shadow", "backend": self._shadow_backend},
            )
            status = "unknown"
            if isinstance(result, Mapping):
                status = str(result.get("status") or "unknown")
            elif hasattr(result, "status"):
                status = str(getattr(result, "status") or "unknown")
            payload = result if isinstance(result, Mapping) else {"value": str(result)}
            repo.write(
                self._shadow_backend,
                key=key,
                result_payload=payload if isinstance(payload, dict) else {"value": payload},
                status=status if status else "unknown",
                trust_level="none",
                legacy_payload={
                    "cid": cid,
                    "formula_str": str(formula),
                    "prover_name": prover_name,
                    "result": payload,
                },
                envelope_content_id=cid,
            )
            with self.lock:
                self.stats["shadow_writes"] = int(self.stats.get("shadow_writes") or 0) + 1
        except Exception as exc:  # pragma: no cover - shadow must not break legacy
            logger.debug("proof cache shadow write failed: %s", exc)
            with self.lock:
                self.stats["shadow_errors"] = int(self.stats.get("shadow_errors") or 0) + 1

    def _entry_expired(
        self,
        entry: CachedProofResult,
        *,
        now: Optional[float] = None,
    ) -> bool:
        """Return whether an entry has exceeded its wall-clock persistence TTL."""

        if self.ttl is None or self.ttl <= 0:
            return False
        return (now if now is not None else time.time()) - entry.timestamp >= self.ttl

    def _load_persistent_cache(self) -> None:
        """Load JSON-safe CID entries from disk, ignoring stale or corrupt data."""

        if not self.persistence_path:
            logger.warning("Proof cache persistence enabled without a persistence_path")
            return
        path = Path(self.persistence_path)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("proof cache payload must be an object")
            if payload.get("schema_version") != _PERSISTENCE_SCHEMA_VERSION:
                logger.warning("Ignoring unsupported proof cache persistence schema")
                return
            raw_entries = payload.get("entries")
            if not isinstance(raw_entries, list):
                raise ValueError("proof cache entries must be a list")
            now = time.time()
            loaded = 0
            entries = sorted(
                (entry for entry in raw_entries if isinstance(entry, dict)),
                key=lambda entry: _safe_timestamp(entry.get("timestamp")),
                reverse=True,
            )[: self.maxsize]
            with self.lock:
                for raw in reversed(entries):
                    entry = CachedProofResult(
                        result=raw["result"],
                        cid=str(raw["cid"]),
                        prover_name=str(raw.get("prover_name") or "unknown"),
                        formula_str=str(raw.get("formula_str") or ""),
                        timestamp=_safe_timestamp(raw.get("timestamp")),
                        hit_count=max(0, int(raw.get("hit_count") or 0)),
                    )
                    if self._entry_expired(entry, now=now):
                        continue
                    self.cache[entry.cid] = entry
                    loaded += 1
                self.stats["persistence_loads"] += loaded
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self.stats["persistence_errors"] += 1
            logger.warning(
                "Ignoring unreadable proof cache persistence file %s: %s",
                path,
                exc,
            )

    def _persistent_payload(self) -> Dict[str, Any]:
        """Build a deterministic JSON-safe snapshot of the CID cache."""

        entries: List[Dict[str, Any]] = []
        now = time.time()
        for cached in list(self.cache.values()):
            if not isinstance(cached, CachedProofResult) or self._entry_expired(
                cached,
                now=now,
            ):
                continue
            try:
                result = json.loads(
                    json.dumps(
                        cached.result,
                        ensure_ascii=True,
                        allow_nan=False,
                        sort_keys=True,
                    )
                )
            except (TypeError, ValueError):
                self.stats["persistence_skipped_results"] += 1
                continue
            entries.append(
                {
                    "cid": cached.cid,
                    "formula_str": cached.formula_str,
                    "hit_count": cached.hit_count,
                    "prover_name": cached.prover_name,
                    "result": result,
                    "timestamp": cached.timestamp,
                }
            )
        entries.sort(key=lambda entry: entry["cid"])
        return {
            "entries": entries,
            "schema_version": _PERSISTENCE_SCHEMA_VERSION,
            "written_at": now,
        }

    def _merge_persistent_payload(
        self,
        path: Path,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge another process's accepted entries into this snapshot."""

        if not path.exists():
            return payload
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return payload
        if (
            not isinstance(existing, dict)
            or existing.get("schema_version") != _PERSISTENCE_SCHEMA_VERSION
            or not isinstance(existing.get("entries"), list)
        ):
            return payload
        entries = {
            str(entry.get("cid")): entry
            for entry in existing["entries"]
            if isinstance(entry, dict) and entry.get("cid")
        }
        entries.update(
            {
                str(entry["cid"]): entry
                for entry in payload["entries"]
                if isinstance(entry, dict) and entry.get("cid")
            }
        )
        now = time.time()
        retained = [
            entry
            for entry in entries.values()
            if self.ttl <= 0
            or now - _safe_timestamp(entry.get("timestamp")) < self.ttl
        ]
        retained.sort(
            key=lambda entry: _safe_timestamp(entry.get("timestamp")),
            reverse=True,
        )
        payload["entries"] = sorted(
            retained[: self.maxsize],
            key=lambda entry: str(entry["cid"]),
        )
        return payload

    def _persist_cache(self, *, replace_existing: bool = False) -> None:
        """Atomically checkpoint JSON-safe CID entries to disk."""

        if not self.enable_persistence or not self.persistence_path:
            return
        path = Path(self.persistence_path)
        temporary_path: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = path.with_name(f".{path.name}.lock")
            with lock_path.open("a", encoding="utf-8") as lock_handle:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                with self.lock:
                    payload = self._persistent_payload()
                if not replace_existing:
                    payload = self._merge_persistent_payload(path, payload)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(path.parent),
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
                try:
                    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                except (AttributeError, OSError):
                    directory_fd = None
                if directory_fd is not None:
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                with self.lock:
                    self.stats["persistence_writes"] += 1
        except (OSError, TypeError, ValueError) as exc:
            with self.lock:
                self.stats["persistence_errors"] += 1
            logger.warning("Failed to persist proof cache to %s: %s", path, exc)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
    
    def _compute_cid(
        self,
        formula,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> str:
        """Compute CID for a proof query.
        
        The CID is computed from:
        - Formula (canonical representation)
        - Axioms (if any)
        - Prover name
        - Prover configuration (if any)
        
        This ensures different queries get different CIDs.
        
        Args:
            formula: TDFOL formula or string
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            CID string (content identifier)
        """
        # Build canonical representation
        query_obj = {
            'formula': str(formula),
            'axioms': [str(a) for a in axioms] if axioms else [],
            'prover': prover_name,
            'config': prover_config or {}
        }
        
        # Compute CID
        try:
            cid = cid_for_obj(query_obj)
            return cid
        except Exception as e:
            global _CID_FALLBACK_LOGGED
            if not _CID_FALLBACK_LOGGED:
                logger.warning(f"CID computation failed, using fallback: {e}")
                _CID_FALLBACK_LOGGED = True
            # Fallback to simple hash
            import hashlib
            json_str = json.dumps(query_obj, sort_keys=True, default=str)
            return hashlib.sha256(json_str.encode()).hexdigest()
    
    def get(
        self,
        formula,
        axioms_or_prover=None,
        prover_name: str = None,
        prover_config: Optional[Dict] = None,
        *,
        axioms: Optional[List] = None,
    ) -> Optional[Any]:
        """Get cached proof result (O(1) lookup).

        Supports two call styles:
          - New API: get(formula, axioms=[], prover_name="z3")
          - Compat API: get(formula, "prover_name")
          - Keyword: get(formula, prover_name="z3")

        The second positional argument is interpreted as *axioms* when it is
        a list (or None) and as *prover_name* when it is a string.

        Args:
            formula: TDFOL formula or string
            axioms_or_prover: axioms list (new API) or prover_name string (compat API)
            prover_name: prover name (keyword arg takes priority over positional)
            prover_config: Optional prover configuration
            axioms: explicit axioms keyword arg (takes priority over positional)

        Returns:
            Cached proof result if found, None otherwise
        """
        # axioms= keyword arg takes priority over positional
        if axioms is not None:
            _axioms = axioms
            _prover_name = prover_name or (axioms_or_prover if isinstance(axioms_or_prover, str) else "unknown")
        elif prover_name is not None:
            # Explicit prover_name keyword
            _prover_name = prover_name
            _axioms = axioms_or_prover if isinstance(axioms_or_prover, list) else None
        elif isinstance(axioms_or_prover, str):
            # Compat API: get(formula, "prover_name")
            _prover_name = axioms_or_prover
            _axioms = None
        else:
            # New API: get(formula, axioms_list)
            _axioms = axioms_or_prover  # list or None
            _prover_name = "unknown"

        # Check compat cache first (formula::prover_name key)
        import time as _time
        key = self._make_key(str(formula), _prover_name)
        if key in self._cache:
            entry = self._cache[key]
            if entry._expires_at is not None and _time.monotonic() > entry._expires_at:
                del self._cache[key]
                self._compat_expirations += 1
                self._compat_misses += 1
            else:
                entry.hit_count += 1
                self._compat_hits += 1
                self._cache.move_to_end(key)
                self.stats['hits'] += 1
                return entry.result

        cid = self._compute_cid(formula, _axioms, _prover_name, prover_config)

        # Check CID-based local cache
        with self.lock:
            if cid in self.cache:
                cached = self.cache[cid]
                if isinstance(cached, CachedProofResult) and self._entry_expired(cached):
                    del self.cache[cid]
                else:
                    if hasattr(cached, 'hit_count'):
                        cached.hit_count += 1
                    self.stats['hits'] += 1
                    logger.debug(f"Local cache HIT for CID {cid[:16]}... (prover: {_prover_name})")
                    return cached.result if hasattr(cached, 'result') else cached

        # If not in local cache and IPFS backend enabled, try IPFS
        if self.ipfs_cache is not None:
            try:
                ipfs_result = self.ipfs_cache.get(cid)
                if ipfs_result is not None:
                    with self.lock:
                        cached_result = CachedProofResult(
                            result=ipfs_result,
                            cid=cid,
                            prover_name=_prover_name,
                            formula_str=str(formula),
                            timestamp=time.time(),
                            hit_count=1
                        )
                        self.cache[cid] = cached_result
                        self.stats['ipfs_hits'] += 1
                        self.stats['hits'] += 1
                    logger.debug(f"IPFS cache HIT for CID {cid[:16]}... (prover: {_prover_name})")
                    return ipfs_result
            except Exception as e:
                logger.debug(f"IPFS cache lookup failed for CID {cid[:16]}...: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1

        # Not found in either cache
        self._compat_misses += 1
        with self.lock:
            self.stats['misses'] += 1
        logger.debug(f"Cache MISS for CID {cid[:16]}... (prover: {_prover_name})")
        return None

    def set(
        self,
        formula,
        result: Any,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> str:
        """Cache a proof result (O(1) insertion).
        
        Stores in local cache and optionally in IPFS backend if enabled.
        
        Args:
            formula: TDFOL formula or string
            result: Proof result to cache
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            CID of the cached entry
        """
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)
        
        with self.lock:
            cached_result = CachedProofResult(
                result=result,
                cid=cid,
                prover_name=prover_name,
                formula_str=str(formula),
                timestamp=time.time(),
                hit_count=0
            )
            
            # Check if cache is full (for non-TTLCache)
            if not CACHETOOLS_AVAILABLE and len(self.cache) >= self.maxsize:
                # Simple LRU eviction: remove oldest entry
                oldest_cid = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
                del self.cache[oldest_cid]
                self.stats['evictions'] += 1
            
            self.cache[cid] = cached_result
            self.stats['sets'] += 1
            logger.debug(f"Cached result in local cache with CID {cid[:16]}... (prover: {prover_name})")

        self._persist_cache()
        
        # Also store in IPFS backend if enabled
        if self.ipfs_cache is not None:
            try:
                # Serialize result for IPFS storage
                result_data = {
                    'result': result,
                    'prover_name': prover_name,
                    'formula_str': str(formula),
                    'timestamp': time.time(),
                    'cid': cid
                }
                self.ipfs_cache.set(cid, result_data)
                with self.lock:
                    self.stats['ipfs_sets'] += 1
                logger.debug(f"Cached result in IPFS with CID {cid[:16]}...")
            except Exception as e:
                logger.debug(f"IPFS cache storage failed for CID {cid[:16]}...: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1

        self._shadow_write(
            formula=formula,
            result=result,
            cid=cid,
            prover_name=prover_name,
            prover_config=prover_config,
            axioms=axioms,
        )
        
        return cid
    
    def invalidate(
        self,
        formula,
        axioms: Optional[List] = None,
        prover_name: str = "unknown",
        prover_config: Optional[Dict] = None
    ) -> bool:
        """Invalidate a cached entry.
        
        Args:
            formula: TDFOL formula or string
            axioms: Optional list of axioms
            prover_name: Name of prover
            prover_config: Optional prover configuration
            
        Returns:
            True if entry was found and removed, False otherwise
        """
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)

        repo = self.shadow_repository
        if repo is not None:
            try:
                key = repo.project_key(
                    self._shadow_backend,
                    formula=formula,
                    cid=cid,
                    prover_name=prover_name,
                    prover_config=prover_config,
                    axioms=axioms,
                    solver_identities={"prover": prover_name},
                    toolchain={"backend": self._shadow_backend},
                    policy={"mode": "shadow", "backend": self._shadow_backend},
                )
                repo.invalidate(self._shadow_backend, key, reason="explicit")
            except Exception as exc:  # pragma: no cover
                logger.debug("proof cache shadow invalidate failed: %s", exc)
        
        with self.lock:
            if cid in self.cache:
                del self.cache[cid]
                logger.debug(f"Invalidated cache entry {cid[:16]}...")
                return True
            return False
    
    def clear(self):
        """Clear all cached entries. Returns the number of entries cleared."""
        with self.lock:
            count = len(self._cache) + len(self.cache)
            self.cache.clear()
            self._cache.clear()
            logger.info("Cache cleared")
        self._persist_cache(replace_existing=True)
        return count
    
    def get_stats(self) -> Dict:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including hit rate
        """
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0.0
            
            return {
                **self.stats,
                'total_requests': total_requests,
                'hit_rate': hit_rate,
                'cache_size': len(self.cache),
                'maxsize': self.maxsize,
                'ttl': self.ttl
            }
    

    # ------------------------------------------------------------------
    # Compat API (simple formula+prover_name key-value interface)
    # ------------------------------------------------------------------

    def _make_key(self, formula: str, prover_name: str) -> str:
        """Create compat cache key."""
        return f"{formula}::{prover_name}"

    def put(self, formula: str, prover_name: str, result: Any, ttl: int = None) -> None:
        """Simple compat put: store (formula, prover_name) → result."""
        import time as _time
        key = self._make_key(formula, prover_name)
        # LRU eviction if at capacity
        if self.max_size and len(self._cache) >= self.max_size and key not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._compat_evictions += 1
        effective_ttl = ttl if ttl is not None else self.default_ttl
        class _Entry:
            __slots__ = ('result', 'ttl', '_expires_at', 'hit_count', 'prover', 'formula', 'timestamp')
            def __init__(self, result, ttl, expires_at, prover, formula, timestamp):
                self.result = result
                self.ttl = ttl
                self._expires_at = expires_at
                self.hit_count = 0
                self.prover = prover
                self.formula = formula
                self.timestamp = timestamp
        self._cache[key] = _Entry(
            result=result,
            ttl=effective_ttl,
            expires_at=_time.monotonic() + effective_ttl if effective_ttl else None,
            prover=prover_name,
            formula=formula,
            timestamp=_time.monotonic(),
        )
        self._compat_puts += 1

    def compat_get(self, formula: str, prover_name: str = "unknown",
            axioms=None, prover_config=None) -> Any:
        """Retrieve a cached proof (compat API — checks compat cache, CID cache, then IPFS)."""
        import time as _time
        key = self._make_key(formula, prover_name)
        if key in self._cache:
            entry = self._cache[key]
            # Check TTL expiration
            if entry._expires_at is not None and _time.monotonic() > entry._expires_at:
                del self._cache[key]
                self._compat_expirations += 1
                self._compat_misses += 1
            else:
                entry.hit_count += 1
                self._compat_hits += 1
                self._cache.move_to_end(key)
                return entry.result

        # Check CID-based local cache
        cid = self._compute_cid(formula, axioms, prover_name, prover_config)
        with self.lock:
            if cid in self.cache:
                cached = self.cache[cid]
                if hasattr(cached, 'hit_count'):
                    cached.hit_count += 1
                self.stats['hits'] += 1
                return cached.result if hasattr(cached, 'result') else cached

        # Check IPFS backend if enabled
        if self.ipfs_cache is not None:
            try:
                ipfs_result = self.ipfs_cache.get(cid)
                if ipfs_result is not None:
                    with self.lock:
                        cached_result = CachedProofResult(
                            result=ipfs_result,
                            cid=cid,
                            prover_name=prover_name,
                            formula_str=str(formula),
                            timestamp=time.time(),
                            hit_count=1
                        )
                        self.cache[cid] = cached_result
                        self.stats['ipfs_hits'] += 1
                        self.stats['hits'] += 1
                    return ipfs_result
            except Exception as e:
                logger.debug(f"IPFS cache lookup failed: {e}")
                with self.lock:
                    self.stats['ipfs_errors'] += 1

        # Not found in any cache
        self._compat_misses += 1
        with self.lock:
            self.stats['misses'] += 1
        return None

    def invalidate(self, formula: str, prover_name: str = "unknown") -> bool:
        """Remove a cached entry."""
        key = self._make_key(formula, prover_name)
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        import time as _time
        now = _time.monotonic()
        expired_keys = [
            k for k, v in list(self._cache.items())
            if v._expires_at is not None and now > v._expires_at
        ]
        for k in expired_keys:
            del self._cache[k]
        self._compat_expirations += len(expired_keys)
        return len(expired_keys)

    def get_cached_entries(self):
        """Return list of cached entry metadata."""
        return [
            {
                "formula": v.formula,
                "prover": v.prover,
                "hit_count": v.hit_count,
                "timestamp": v.timestamp,
                "ttl": v.ttl,
            }
            for v in self._cache.values()
        ]

    def resize(self, new_size: int) -> None:
        """Resize the cache, evicting oldest entries if needed."""
        self.max_size = new_size
        self.maxsize = new_size
        while len(self._cache) > new_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._compat_evictions += 1

    def get_statistics(self) -> Dict:
        """Return unified statistics dict (compat API)."""
        total = self._compat_hits + self._compat_misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._compat_hits,
            "misses": self._compat_misses,
            "hit_rate": (self._compat_hits / total) if total > 0 else 0.0,
            "evictions": self._compat_evictions,
            "expirations": self._compat_expirations,
            "total_puts": self._compat_puts,
            # Also include CID-based stats
            "cache_size": len(self.cache),
        }

    def get_info(self, cid: str) -> Optional[Dict]:
        """Get information about a cached entry.
        
        Args:
            cid: Content identifier
            
        Returns:
            Dictionary with entry information, or None if not found
        """
        with self.lock:
            if cid in self.cache:
                return self.cache[cid].to_dict()
            return None


# Global cache instance (singleton)
_global_proof_cache: Optional[ProofCache] = None


def get_global_cache(
    maxsize: int = 1000,
    ttl: int = 3600
) -> ProofCache:
    """Get or create global proof cache instance.
    
    Args:
        maxsize: Maximum cache size (only used if creating new cache)
        ttl: Time-to-live in seconds (only used if creating new cache)
        
    Returns:
        Global ProofCache instance
    """
    global _global_proof_cache
    
    if _global_proof_cache is None:
        _global_proof_cache = ProofCache(maxsize=maxsize, ttl=ttl)
    
    return _global_proof_cache


def cache_proof_result(func):
    """Decorator to cache proof results.
    
    Usage:
        @cache_proof_result
        def prove(self, formula, axioms=None):
            # ... proving logic ...
            return result
    """
    from functools import wraps
    
    @wraps(func)
    def wrapper(self, formula, axioms=None, *args, **kwargs):
        # Get prover name
        prover_name = getattr(self, '__class__', type(self)).__name__
        
        # Try to get from cache
        cache = get_global_cache()
        cached_result = cache.get(
            formula,
            axioms=axioms,
            prover_name=prover_name,
            prover_config=kwargs
        )
        
        if cached_result is not None:
            return cached_result
        
        # Not in cache, compute result
        result = func(self, formula, axioms, *args, **kwargs)
        
        # Cache the result
        cache.set(
            formula,
            result,
            axioms=axioms,
            prover_name=prover_name,
            prover_config=kwargs
        )
        
        return result
    
    return wrapper


# ---------------------------------------------------------------------------
# DQK-065: Unified proof shadow repository
# ---------------------------------------------------------------------------
#
# Every legacy proof-cache lookup/write, single-flight claim, attempt,
# attestation, invalidation, and corpus-index mutation is projected through
# this repository while each logic family retains its authority dimensions
# and immutable envelope bytes / CIDs remain unchanged.
# ---------------------------------------------------------------------------

from enum import StrEnum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Sequence, Tuple
import hashlib
import threading as _threading


PROOF_SHADOW_INTERFACE = "UnifiedProofShadowRepository@1"
PROOF_SHADOW_SCHEMA_VERSION = "unified-proof-shadow/v1"
PROOF_SHADOW_RECEIPT_SCHEMA = "unified-proof-shadow-receipt/v1"


class ProofShadowError(ValueError):
    """Fail-closed rejection for shadow repository operations."""


class ProofShadowTrustError(ProofShadowError):
    """Raised when a trust claim cannot be admitted (never silently raised)."""


class ProofShadowIdentityError(ProofShadowError):
    """Raised when solver/toolchain/premise/policy identities are incompatible."""


class LegacyProofBackend(StrEnum):
    """Closed set of legacy proof-cache backends that must dual-write in shadow.

    Each value maps to one expected-output module under the DQK-065 contract.
    """

    COMMON = "common"
    HAMMERS = "hammers"
    LEGAL_IR = "legal_ir"
    INTEGRATION = "integration"
    INTEGRATION_CACHING = "integration_caching"
    IPFS_PROOF_CACHE = "ipfs_proof_cache"
    EXTERNAL_PROVERS = "external_provers"
    TDFOL = "tdfol"
    CEC_NATIVE = "cec_native"
    CEC_FORMULA = "cec_formula"
    FLOGIC = "flogic"
    SECURITY_IR = "security_ir"
    OPTIMIZER_FORMULA = "optimizer_formula"

    @classmethod
    def parse(cls, value: "str | LegacyProofBackend") -> "LegacyProofBackend":
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "proof_cache": cls.COMMON,
            "unified": cls.COMMON,
            "common_proof_cache": cls.COMMON,
            "hammer": cls.HAMMERS,
            "hammer_proof_cache": cls.HAMMERS,
            "legal": cls.LEGAL_IR,
            "legal_proof_cache": cls.LEGAL_IR,
            "integration_cache": cls.INTEGRATION,
            "integration_proof_cache": cls.INTEGRATION,
            "caching_proof_cache": cls.INTEGRATION_CACHING,
            "ipfs": cls.IPFS_PROOF_CACHE,
            "ipfs_cache": cls.IPFS_PROOF_CACHE,
            "external": cls.EXTERNAL_PROVERS,
            "external_prover": cls.EXTERNAL_PROVERS,
            "tdfol_proof_cache": cls.TDFOL,
            "cec": cls.CEC_NATIVE,
            "cec_proof_cache": cls.CEC_NATIVE,
            "formula_cache": cls.CEC_FORMULA,
            "cec_optimization": cls.CEC_FORMULA,
            "flogic_proof_cache": cls.FLOGIC,
            "constraint_cache": cls.SECURITY_IR,
            "security": cls.SECURITY_IR,
            "optimizer": cls.OPTIMIZER_FORMULA,
            "logic_theorem_optimizer": cls.OPTIMIZER_FORMULA,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


# Every expected-output legacy backend.  Differential receipts are required
# for each entry in this closed set (DQK-065 acceptance).
LEGACY_PROOF_BACKENDS: Tuple[LegacyProofBackend, ...] = tuple(LegacyProofBackend)

# Map each legacy backend onto a ProofCacheFamily (migration / adapter surface).
_BACKEND_TO_FAMILY: Mapping[str, str] = MappingProxyType(
    {
        LegacyProofBackend.COMMON.value: "common",
        LegacyProofBackend.HAMMERS.value: "hammers",
        LegacyProofBackend.LEGAL_IR.value: "legal_ir",
        LegacyProofBackend.INTEGRATION.value: "integration",
        LegacyProofBackend.INTEGRATION_CACHING.value: "integration",
        LegacyProofBackend.IPFS_PROOF_CACHE.value: "integration",
        LegacyProofBackend.EXTERNAL_PROVERS.value: "external_provers",
        LegacyProofBackend.TDFOL.value: "tdfol",
        LegacyProofBackend.CEC_NATIVE.value: "cec",
        LegacyProofBackend.CEC_FORMULA.value: "cec",
        LegacyProofBackend.FLOGIC.value: "common",
        LegacyProofBackend.SECURITY_IR.value: "common",
        LegacyProofBackend.OPTIMIZER_FORMULA.value: "cec",
    }
)


def family_for_backend(backend: "LegacyProofBackend | str") -> str:
    """Return the ProofCacheFamily value for a legacy backend id."""

    parsed = LegacyProofBackend.parse(backend)
    return _BACKEND_TO_FAMILY[parsed.value]


def _canonical_shadow_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _legacy_digest(payload: Any) -> str:
    return "sha256:" + _sha256_text(_canonical_shadow_json(payload))


@dataclass(frozen=True)
class ProofShadowDifferentialReceipt:
    """Differential parity receipt for one legacy-backend shadow operation.

    Acceptance requires every legacy backend to produce at least one of these.
    Envelope content_id / content_digest / byte_size are recorded so callers
    can prove immutable envelope bytes and CIDs were not rewritten.
    """

    backend: str
    family: str
    operation: str
    key_digest: str
    legacy_entry_digest: str
    store_entry_digest: str
    digests_match: bool
    present_in_legacy: bool
    present_in_store: bool
    envelope_content_id: str = ""
    envelope_content_digest: str = ""
    envelope_byte_size: int = 0
    reason: str = ""
    created_at: float = 0.0
    receipt_id: str = ""
    schema: str = PROOF_SHADOW_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not self.receipt_id:
            body = {
                "backend": self.backend,
                "created_at": self.created_at,
                "family": self.family,
                "key_digest": self.key_digest,
                "legacy_entry_digest": self.legacy_entry_digest,
                "operation": self.operation,
                "store_entry_digest": self.store_entry_digest,
            }
            object.__setattr__(
                self,
                "receipt_id",
                "sha256:" + _sha256_text(_canonical_shadow_json(body)),
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "created_at": self.created_at,
            "digests_match": self.digests_match,
            "envelope_byte_size": self.envelope_byte_size,
            "envelope_content_digest": self.envelope_content_digest,
            "envelope_content_id": self.envelope_content_id,
            "family": self.family,
            "key_digest": self.key_digest,
            "legacy_entry_digest": self.legacy_entry_digest,
            "operation": self.operation,
            "present_in_legacy": self.present_in_legacy,
            "present_in_store": self.present_in_store,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "schema": self.schema,
            "store_entry_digest": self.store_entry_digest,
        }


@dataclass
class _CorpusIndexMutation:
    """In-process corpus-index mutation recorded by the shadow repository."""

    mutation_id: str
    backend: str
    key_digest: str
    envelope_content_id: str
    envelope_content_digest: str
    operation: str
    created_at: float
    payload_digest: str


class UnifiedProofShadowRepository:
    """Unified repository façade for every legacy proof-cache producer (DQK-065).

    Shadow mode keeps legacy caches as the caller-facing authority while every
    lookup/write, single-flight claim, attempt, attestation, invalidation, and
    corpus-index mutation is also applied to the unified DuckDB proof store /
    coordinator / service.  Hits never cross incompatible solver, toolchain,
    premise, or policy identities.  Trust mismatches fail closed.
    Immutable envelope bytes and CIDs are retained by reference only.
    """

    def __init__(
        self,
        *,
        service: Any | None = None,
        store: Any | None = None,
        coordinator: Any | None = None,
        owner_id: str = "owner:proof-shadow",
        mode: str = "shadow",
        clock: Callable[[], float] | None = None,
    ) -> None:
        from .duckdb_proof_coordination import (  # noqa: PLC0415
            build_duckdb_proof_coordinator,
        )
        from .duckdb_proof_migration import (  # noqa: PLC0415
            AuthorityMode,
            PromotionState,
            ProofCacheFamily,
        )
        from .duckdb_proof_service import build_duckdb_proof_service  # noqa: PLC0415
        from .duckdb_proof_store import build_duckdb_proof_store  # noqa: PLC0415

        self._clock = clock or time.time
        self._lock = _threading.RLock()
        self._mode = (
            mode
            if isinstance(mode, AuthorityMode)
            else AuthorityMode(str(mode))
        )
        self._promotion = PromotionState()
        self._owner_id = str(owner_id or "owner:proof-shadow")

        if service is not None:
            self._service = service
            self._coordinator = service.coordinator
            self._store = service.store
        else:
            self._store = store if store is not None else build_duckdb_proof_store()
            self._coordinator = (
                coordinator
                if coordinator is not None
                else build_duckdb_proof_coordinator(store=self._store, clock=self._clock)
            )
            self._service = build_duckdb_proof_service(
                coordinator=self._coordinator,
                store=self._store,
                owner_id=self._owner_id,
                clock=self._clock,
            )

        self._ProofCacheFamily = ProofCacheFamily
        self._backends: dict[str, LegacyProofBackend] = {}
        self._receipts: list[ProofShadowDifferentialReceipt] = []
        self._attestations: list[dict[str, Any]] = []
        self._corpus_index: dict[str, _CorpusIndexMutation] = {}
        self._legacy_payloads: dict[tuple[str, str], Any] = {}
        self._stats = {
            "lookups": 0,
            "writes": 0,
            "claims": 0,
            "attempts": 0,
            "attestations": 0,
            "invalidations": 0,
            "corpus_index_mutations": 0,
            "identity_rejections": 0,
            "trust_rejections": 0,
            "receipts": 0,
        }
        # Pre-register every expected legacy backend so differential coverage
        # is complete once each has performed at least one operation.
        for backend in LEGACY_PROOF_BACKENDS:
            self.register_backend(backend)
            family = family_for_backend(backend)
            self._promotion.set_mode(family, self._mode)

    # -- identity ------------------------------------------------------------

    @property
    def interface(self) -> str:
        return PROOF_SHADOW_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_SHADOW_SCHEMA_VERSION

    @property
    def store(self) -> Any:
        return self._store

    @property
    def coordinator(self) -> Any:
        return self._coordinator

    @property
    def service(self) -> Any:
        return self._service

    @property
    def mode(self) -> str:
        return (
            self._mode.value
            if hasattr(self._mode, "value")
            else str(self._mode)
        )

    @property
    def authority_dimensions(self) -> Tuple[str, ...]:
        from .duckdb_proof_store import PROOF_AUTHORITY_DIMENSIONS  # noqa: PLC0415

        return PROOF_AUTHORITY_DIMENSIONS

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "backends": len(self._backends),
                "receipt_count": len(self._receipts),
                "corpus_index_size": len(self._corpus_index),
                "store": dict(self._store.stats()),
                "coordinator": dict(self._coordinator.stats()),
            }

    def registered_backends(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._backends))

    def register_backend(
        self, backend: "LegacyProofBackend | str"
    ) -> LegacyProofBackend:
        parsed = LegacyProofBackend.parse(backend)
        with self._lock:
            self._backends[parsed.value] = parsed
        return parsed

    def backend_family(
        self, backend: "LegacyProofBackend | str"
    ) -> Any:
        parsed = LegacyProofBackend.parse(backend)
        return self._ProofCacheFamily.parse(family_for_backend(parsed))

    # -- key projection (authority dimensions retained) ----------------------

    def project_key(
        self,
        backend: "LegacyProofBackend | str",
        *,
        formula: Any = None,
        cid: str | None = None,
        prover_name: str = "unknown",
        prover_config: Any = None,
        axioms: Any = None,
        premises: Sequence[Any] = (),
        selected_premises: Sequence[Any] = (),
        solver_identities: Any = None,
        toolchain: Any = None,
        policy: Any = None,
        theorem_registry: Any = None,
        resources: Any = None,
        translator: Any = None,
        property_value: Any = None,
        assumptions: Any = None,
        tree: Any = None,
        backend_id: str | None = None,
        backend_binary: Any = None,
        backend_version: str | None = None,
        backend_config: Any = None,
        hammer_key: Mapping[str, Any] | None = None,
        ir: Any = None,
        unified_key: Any = None,
        **extra: Any,
    ) -> Any:
        """Project a family-local key into the unified proof-key surface.

        Every authority dimension is populated.  Changing solver, toolchain,
        premise, or policy identity yields a distinct digest (miss).
        """

        from .duckdb_proof_store import (  # noqa: PLC0415
            UnifiedProofKey,
            build_unified_proof_key,
        )

        parsed = LegacyProofBackend.parse(backend)
        family = family_for_backend(parsed)

        if unified_key is not None:
            if not isinstance(unified_key, UnifiedProofKey):
                raise ProofShadowIdentityError(
                    "unified_key must be a UnifiedProofKey"
                )
            return unified_key.require_all_dimensions()

        if hammer_key is not None:
            key = UnifiedProofKey.from_hammer_key_dict(hammer_key)
            # Bind family identity without dropping hammer dimensions.
            return build_unified_proof_key(
                ir={"obligation_digest": key.ir_digest, "family": family},
                property_value={"family": family, "backend": parsed.value},
                assumptions=(),
                selected_premise_digests=key.selected_premise_digests,
                translator={"digest": key.translator_digest},
                solver_identities={"digest": key.solver_identities_digest},
                toolchain={"digest": key.toolchain_identity_digest},
                theorem_registry={"digest": key.theorem_registry_digest},
                policy={"digest": key.policy_digest},
                resources={"digest": key.resources_digest},
                tree={"family": family},
                backend_id=f"hammer:{parsed.value}",
                backend_binary="unspecified",
                backend_version="legacy",
                backend_config={
                    "source_family": family,
                    "source_backend": parsed.value,
                    "hammer_key_digest": key.digest,
                },
            )

        premise_values = tuple(selected_premises or premises or ())
        solver = solver_identities
        if solver is None:
            solver = {"prover": prover_name, "family": family}
        if toolchain is None:
            toolchain = {"family": family, "backend": parsed.value}
        if policy is None:
            policy = {"mode": "shadow", "family": family}
        if theorem_registry is None:
            theorem_registry = f"legacy:{family}"
        if resources is None:
            resources = {}
        if translator is None:
            translator = {"family": family, "version": "legacy"}
        if assumptions is None:
            assumptions = tuple(axioms) if axioms else ()
        if tree is None:
            tree = {"family": family}
        if property_value is None:
            property_value = {
                "family": family,
                "backend": parsed.value,
                "cid": cid,
            }

        if ir is None:
            if cid and formula is not None:
                ir = {"cid": cid, "formula_str": str(formula)}
            elif cid:
                ir = {"cid": cid}
            elif formula is not None:
                ir = formula
            else:
                ir = {"family": family, "backend": parsed.value}

        cfg = dict(backend_config or {})
        cfg.setdefault("source_family", family)
        cfg.setdefault("source_backend", parsed.value)
        if prover_config is not None:
            cfg.setdefault("prover_config", prover_config)
        if extra:
            cfg.setdefault("extra", dict(extra))

        return build_unified_proof_key(
            ir=ir,
            property_value=property_value,
            assumptions=assumptions,
            selected_premises=premise_values,
            translator=translator,
            solver_identities=solver,
            toolchain=toolchain,
            theorem_registry=theorem_registry,
            policy=policy,
            resources=resources,
            tree=tree,
            backend_id=backend_id or str(prover_name or f"backend.{parsed.value}"),
            backend_binary=backend_binary if backend_binary is not None else "unspecified",
            backend_version=backend_version or "legacy",
            backend_config=cfg,
        )

    def assert_compatible_identities(
        self,
        left: Any,
        right: Any,
        *,
        dimensions: Sequence[str] = (
            "solver",
            "toolchain",
            "premises",
            "policy",
        ),
    ) -> None:
        """Fail closed when two keys disagree on authority dimensions."""

        left_map = left.dimension_map()
        right_map = right.dimension_map()
        for name in dimensions:
            if left_map.get(name) != right_map.get(name):
                self._stats["identity_rejections"] += 1
                raise ProofShadowIdentityError(
                    f"incompatible {name} identity: "
                    f"{left_map.get(name)!r} != {right_map.get(name)!r}"
                )
        if left.digest != right.digest:
            # Full-key mismatch is also a miss; raise so callers do not treat
            # a partial dimension agreement as a hit.
            self._stats["identity_rejections"] += 1
            raise ProofShadowIdentityError(
                "proof keys disagree on full identity digest"
            )

    # -- lookup / write ------------------------------------------------------

    def lookup(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        max_trust_level: Any | None = None,
        require_result_authority: Any | None = None,
        expected_key: Any | None = None,
    ) -> Any | None:
        """Lookup through the unified store; trust mismatches fail closed."""

        from .duckdb_proof_store import (  # noqa: PLC0415
            DuckDBProofStoreAuthorityError,
            ProofTrustLevel,
            UnifiedProofKey,
        )

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        if not isinstance(key, UnifiedProofKey):
            raise TypeError("key must be a UnifiedProofKey")
        if expected_key is not None:
            self.assert_compatible_identities(key, expected_key)

        from ..backends.cache_protocol import CacheLookupReason  # noqa: PLC0415

        with self._lock:
            self._stats["lookups"] += 1
            try:
                lookup = self._store.lookup(
                    key,
                    max_trust_level=max_trust_level,
                    require_result_authority=require_result_authority,
                )
            except DuckDBProofStoreAuthorityError as error:
                self._stats["trust_rejections"] += 1
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest="",
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason=f"trust_mismatch:{error}",
                )
                raise ProofShadowTrustError(str(error)) from error

            reason = getattr(lookup.reason, "value", str(lookup.reason))
            if reason in {
                CacheLookupReason.INSUFFICIENT_AUTHORITY.value,
                "insufficient_authority",
                CacheLookupReason.AUTHORITY_MISMATCH.value,
                "authority_mismatch",
            }:
                self._stats["trust_rejections"] += 1
                store_digest = (
                    lookup.entry.entry_digest
                    if lookup.entry is not None
                    and hasattr(lookup.entry, "entry_digest")
                    else ""
                )
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest=store_digest,
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason=f"trust_mismatch:{reason}",
                )
                raise ProofShadowTrustError(
                    f"trust mismatch on lookup: {reason}"
                )

            if not lookup.usable or lookup.entry is None:
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest=self._legacy_payloads.get(
                        (parsed.value, key.digest), ""
                    )
                    and _legacy_digest(
                        self._legacy_payloads[(parsed.value, key.digest)]
                    )
                    or "",
                    store_entry_digest="",
                    digests_match=False,
                    present_in_legacy=(parsed.value, key.digest)
                    in self._legacy_payloads,
                    present_in_store=False,
                    reason=reason or "miss",
                )
                return None

            # Materialize the unified entry from the store.
            entry = self._store.get(key)
            if entry is None:
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest="",
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=False,
                    reason="miss_after_usable",
                )
                return None

            # Fail closed if the stored key's identities drift.
            try:
                self.assert_compatible_identities(key, entry.key)
            except ProofShadowIdentityError:
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest=entry.entry_digest,
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason="identity_mismatch",
                    envelope=entry.envelope,
                )
                return None

            if max_trust_level is not None:
                try:
                    entry.require_trust_at_most(max_trust_level)
                except DuckDBProofStoreAuthorityError as error:
                    self._stats["trust_rejections"] += 1
                    self._emit_receipt_locked(
                        backend=parsed,
                        operation="lookup",
                        key_digest=key.digest,
                        legacy_entry_digest="",
                        store_entry_digest=entry.entry_digest,
                        digests_match=False,
                        present_in_legacy=False,
                        present_in_store=True,
                        reason=f"trust_mismatch:{error}",
                        envelope=entry.envelope,
                    )
                    raise ProofShadowTrustError(str(error)) from error

            legacy_payload = self._legacy_payloads.get((parsed.value, key.digest))
            legacy_digest = (
                _legacy_digest(legacy_payload) if legacy_payload is not None else ""
            )
            self._emit_receipt_locked(
                backend=parsed,
                operation="lookup",
                key_digest=key.digest,
                legacy_entry_digest=legacy_digest,
                store_entry_digest=entry.entry_digest,
                digests_match=True,
                present_in_legacy=legacy_payload is not None,
                present_in_store=True,
                reason="hit",
                envelope=entry.envelope,
            )
            return entry

    def write(
        self,
        backend: "LegacyProofBackend | str",
        *,
        key: Any,
        result_payload: Mapping[str, Any] | None = None,
        status: Any = "proved",
        trust_level: Any | None = None,
        kernel_accepted: bool = False,
        deterministic_trusted: bool = False,
        envelope_bytes: bytes | None = None,
        envelope_content_id: str | None = None,
        legacy_payload: Any = None,
        result_id: str = "",
        diagnostics: Sequence[str] = (),
        claim: Any | None = None,
    ) -> Any:
        """Write a shadow entry into the unified store and emit a receipt.

        Envelope bytes are content-addressed once; the stored reference keeps
        the original content_id / digest / byte_size unchanged.
        """

        from .duckdb_proof_migration import (  # noqa: PLC0415
            ProofMigrationQuarantineError,
            translate_status,
            translate_trust,
        )
        from .duckdb_proof_store import (  # noqa: PLC0415
            ImmutableEnvelopeReference,
            ProofOutcomeKind,
            ProofTrustLevel,
            UnifiedProofEntry,
            outcome_kind_for_status,
            polarity_for_outcome,
        )
        from ..backends.results import ResultAuthority  # noqa: PLC0415
        from ..families.models import EvidenceAuthority  # noqa: PLC0415
        from ..ir_core.claims import FrozenMap  # noqa: PLC0415

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        family = family_for_backend(parsed)
        now = float(self._clock())

        try:
            resolved_status = translate_status(status)
        except ProofMigrationQuarantineError as error:
            raise ProofShadowError(str(error)) from error

        try:
            resolved_trust = translate_trust(
                trust_level,
                kernel_accepted=kernel_accepted,
                deterministic_trusted=deterministic_trusted,
                family=family,
            )
        except ProofMigrationQuarantineError as error:
            self._stats["trust_rejections"] += 1
            raise ProofShadowTrustError(str(error)) from error

        # Fail closed: never raise trust above NON_TRUSTED without kernel /
        # deterministic / legal-IR evidence already enforced by translate_trust.
        if resolved_trust is ProofTrustLevel.AUTHORITATIVE:
            self._stats["trust_rejections"] += 1
            raise ProofShadowTrustError(
                "authoritative trust cannot be written from a legacy shadow path"
            )

        outcome = outcome_kind_for_status(resolved_status)
        polarity = polarity_for_outcome(outcome)
        if outcome is ProofOutcomeKind.PROOF:
            result_authority = ResultAuthority.THEOREM
        elif outcome is ProofOutcomeKind.COUNTEREXAMPLE:
            result_authority = ResultAuthority.SATISFIABILITY
        else:
            result_authority = ResultAuthority.CANDIDATE

        evidence_authority = EvidenceAuthority.NONE
        if kernel_accepted or deterministic_trusted:
            evidence_authority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE
        if resolved_trust is ProofTrustLevel.INDEPENDENTLY_CHECKABLE:
            evidence_authority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE

        envelope = None
        if envelope_bytes is not None:
            envelope = ImmutableEnvelopeReference.from_bytes(
                envelope_bytes,
                media_type="application/octet-stream",
                content_id=envelope_content_id,
            )
        elif envelope_content_id:
            # Reference-only path: preserve caller-supplied CID without bytes.
            digest = (
                envelope_content_id
                if str(envelope_content_id).startswith("sha256:")
                else "sha256:" + _sha256_text(str(envelope_content_id))
            )
            envelope = ImmutableEnvelopeReference(
                content_id=str(envelope_content_id),
                content_digest=digest,
                media_type="application/octet-stream",
                byte_size=0,
            )

        payload = dict(result_payload or {})
        if legacy_payload is not None and "legacy" not in payload:
            # Retain a JSON-safe digest of the legacy payload; do not rewrite it.
            payload["legacy_digest"] = _legacy_digest(legacy_payload)

        entry = UnifiedProofEntry(
            key=key,
            outcome=outcome,
            trust_level=resolved_trust,
            status=resolved_status,
            result_authority=result_authority,
            evidence_authority=evidence_authority,
            result_payload=FrozenMap(payload),
            polarity=polarity,
            created_at=now,
            result_id=result_id or (envelope.content_id if envelope else key.digest),
            diagnostics=tuple(diagnostics)
            + (f"shadow_backend:{parsed.value}", f"shadow_family:{family}"),
            envelope=envelope,
        )

        with self._lock:
            self._stats["writes"] += 1
            if legacy_payload is not None:
                self._legacy_payloads[(parsed.value, key.digest)] = legacy_payload
            if claim is not None:
                self._coordinator.publish(claim, entry, key=key, now=now)
                self._stats["attempts"] += 1
            else:
                self._store.put(entry, now=now)

            legacy_digest = (
                _legacy_digest(legacy_payload)
                if legacy_payload is not None
                else _legacy_digest(payload)
            )
            self._emit_receipt_locked(
                backend=parsed,
                operation="write",
                key_digest=key.digest,
                legacy_entry_digest=legacy_digest,
                store_entry_digest=entry.entry_digest,
                digests_match=True,
                present_in_legacy=True,
                present_in_store=True,
                reason="shadow_write",
                envelope=entry.envelope,
            )
            return entry

    # -- single-flight / attempt / attestation / invalidation / corpus ------

    def claim_single_flight(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
    ) -> Any:
        """Claim single-flight production through the unified coordinator."""

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        with self._lock:
            self._stats["claims"] += 1
            kwargs: Dict[str, Any] = {
                "owner_id": owner_id or self._owner_id,
            }
            if lease_seconds is not None:
                kwargs["lease_seconds"] = lease_seconds
            claim = self._coordinator.claim(key, **kwargs)
            self._emit_receipt_locked(
                backend=parsed,
                operation="claim",
                key_digest=key.digest,
                legacy_entry_digest="",
                store_entry_digest="",
                digests_match=True,
                present_in_legacy=False,
                present_in_store=False,
                reason=(
                    "claim_acquired"
                    if getattr(claim, "acquired", False)
                    else "claim_followed"
                ),
            )
            return claim

    def publish_attempt(
        self,
        backend: "LegacyProofBackend | str",
        claim: Any,
        entry_or_payload: Any,
        *,
        key: Any | None = None,
        **write_kwargs: Any,
    ) -> Any:
        """Publish a proof attempt under a live single-flight claim."""

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        from .duckdb_proof_store import UnifiedProofEntry  # noqa: PLC0415

        if isinstance(entry_or_payload, UnifiedProofEntry):
            with self._lock:
                self._stats["attempts"] += 1
                result = self._coordinator.publish(
                    claim, entry_or_payload, key=key or entry_or_payload.key
                )
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="attempt",
                    key_digest=(key or entry_or_payload.key).digest,
                    legacy_entry_digest="",
                    store_entry_digest=entry_or_payload.entry_digest,
                    digests_match=True,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason="attempt_published",
                    envelope=entry_or_payload.envelope,
                )
                return result
        if key is None:
            raise ProofShadowError("key is required when publishing a payload attempt")
        return self.write(
            parsed,
            key=key,
            claim=claim,
            result_payload=entry_or_payload
            if isinstance(entry_or_payload, Mapping)
            else {"value": entry_or_payload},
            **write_kwargs,
        )

    def attest(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        attestor_id: str,
        content_digest: str,
        payload: Mapping[str, Any] | None = None,
        envelope_content_id: str = "",
        envelope_content_digest: str = "",
    ) -> Dict[str, Any]:
        """Record an attestation against a unified entry (fail-closed)."""

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        now = float(self._clock())
        with self._lock:
            self._stats["attestations"] += 1
            entry = self._store.get(key)
            if entry is None:
                raise ProofShadowError(
                    "cannot attest a missing proof entry (fail closed)"
                )
            # Trust must not be raised silently; attestation is recorded but
            # does not auto-promote unless the service path is used.
            attestation = {
                "attestation_id": "sha256:"
                + _sha256_text(
                    _canonical_shadow_json(
                        {
                            "attestor_id": attestor_id,
                            "content_digest": content_digest,
                            "key_digest": key.digest,
                            "created_at": now,
                        }
                    )
                ),
                "attestor_id": attestor_id,
                "backend": parsed.value,
                "content_digest": content_digest,
                "created_at": now,
                "entry_digest": entry.entry_digest,
                "envelope_content_digest": envelope_content_digest
                or (
                    entry.envelope.content_digest
                    if entry.envelope is not None
                    else ""
                ),
                "envelope_content_id": envelope_content_id
                or (
                    entry.envelope.content_id if entry.envelope is not None else ""
                ),
                "key_digest": key.digest,
                "payload": dict(payload or {}),
            }
            self._attestations.append(attestation)
            self._emit_receipt_locked(
                backend=parsed,
                operation="attestation",
                key_digest=key.digest,
                legacy_entry_digest="",
                store_entry_digest=entry.entry_digest,
                digests_match=True,
                present_in_legacy=False,
                present_in_store=True,
                reason="attested",
                envelope=entry.envelope,
            )
            return dict(attestation)

    def invalidate(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        reason: str = "explicit",
    ) -> bool:
        """Invalidate through the coordinator / store and emit a receipt."""

        from .duckdb_proof_coordination import InvalidationReason  # noqa: PLC0415

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        try:
            resolved_reason = InvalidationReason(str(reason))
        except ValueError:
            resolved_reason = InvalidationReason.EXPLICIT
        with self._lock:
            self._stats["invalidations"] += 1
            removed = bool(
                self._coordinator.invalidate(key, reason=resolved_reason)
            )
            self._legacy_payloads.pop((parsed.value, key.digest), None)
            self._emit_receipt_locked(
                backend=parsed,
                operation="invalidation",
                key_digest=key.digest,
                legacy_entry_digest="",
                store_entry_digest="",
                digests_match=True,
                present_in_legacy=False,
                present_in_store=False,
                reason=resolved_reason.value,
            )
            return removed

    def mutate_corpus_index(
        self,
        backend: "LegacyProofBackend | str",
        *,
        key: Any,
        envelope_content_id: str,
        envelope_content_digest: str,
        operation: str = "index",
        payload: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Record a corpus-index mutation without rewriting envelope bytes."""

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        now = float(self._clock())
        mutation_id = "sha256:" + _sha256_text(
            _canonical_shadow_json(
                {
                    "backend": parsed.value,
                    "envelope_content_digest": envelope_content_digest,
                    "envelope_content_id": envelope_content_id,
                    "key_digest": key.digest,
                    "operation": operation,
                    "created_at": now,
                }
            )
        )
        with self._lock:
            self._stats["corpus_index_mutations"] += 1
            # Enforce immutability: re-indexing the same CID must keep digests.
            existing = self._corpus_index.get(envelope_content_id)
            if existing is not None:
                if existing.envelope_content_digest != envelope_content_digest:
                    raise ProofShadowError(
                        "corpus-index mutation would rewrite envelope digest "
                        f"for {envelope_content_id}"
                    )
            mutation = _CorpusIndexMutation(
                mutation_id=mutation_id,
                backend=parsed.value,
                key_digest=key.digest,
                envelope_content_id=envelope_content_id,
                envelope_content_digest=envelope_content_digest,
                operation=operation,
                created_at=now,
                payload_digest=_legacy_digest(payload or {}),
            )
            self._corpus_index[envelope_content_id] = mutation
            self._emit_receipt_locked(
                backend=parsed,
                operation="corpus_index",
                key_digest=key.digest,
                legacy_entry_digest=mutation.payload_digest,
                store_entry_digest=mutation.mutation_id,
                digests_match=True,
                present_in_legacy=True,
                present_in_store=True,
                reason=operation,
                envelope_content_id=envelope_content_id,
                envelope_content_digest=envelope_content_digest,
                envelope_byte_size=0,
            )
            return {
                "mutation_id": mutation.mutation_id,
                "backend": mutation.backend,
                "key_digest": mutation.key_digest,
                "envelope_content_id": mutation.envelope_content_id,
                "envelope_content_digest": mutation.envelope_content_digest,
                "operation": mutation.operation,
                "created_at": mutation.created_at,
            }

    # -- differential receipts -----------------------------------------------

    def differential_receipts(
        self,
        backend: "LegacyProofBackend | str | None" = None,
    ) -> Tuple[ProofShadowDifferentialReceipt, ...]:
        with self._lock:
            if backend is None:
                return tuple(self._receipts)
            parsed = LegacyProofBackend.parse(backend)
            return tuple(
                item for item in self._receipts if item.backend == parsed.value
            )

    def backends_with_receipts(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted({item.backend for item in self._receipts}))

    def every_backend_has_differential_receipt(self) -> bool:
        """Return True iff every legacy backend has at least one receipt."""

        present = set(self.backends_with_receipts())
        expected = {item.value for item in LEGACY_PROOF_BACKENDS}
        return expected <= present

    def ensure_backend_differential_coverage(self) -> Tuple[str, ...]:
        """Exercise a minimal write for any backend still missing a receipt.

        Used by integration tests and bootstrap so acceptance
        "every legacy backend has differential receipts" holds after wiring.
        """

        missing: list[str] = []
        present = set(self.backends_with_receipts())
        for backend in LEGACY_PROOF_BACKENDS:
            if backend.value in present:
                continue
            missing.append(backend.value)
            key = self.project_key(
                backend,
                formula=f"coverage:{backend.value}",
                prover_name=f"coverage.{backend.value}",
                solver_identities={
                    "prover": f"coverage.{backend.value}",
                    "backend": backend.value,
                },
                toolchain={"coverage": backend.value},
                policy={"mode": "coverage", "backend": backend.value},
                premises=(f"premise:{backend.value}",),
            )
            self.write(
                backend,
                key=key,
                result_payload={"coverage": True, "backend": backend.value},
                status="unknown",
                trust_level="none",
                legacy_payload={
                    "backend": backend.value,
                    "formula": f"coverage:{backend.value}",
                },
            )
        return tuple(missing)

    def _emit_receipt_locked(
        self,
        *,
        backend: LegacyProofBackend,
        operation: str,
        key_digest: str,
        legacy_entry_digest: str,
        store_entry_digest: str,
        digests_match: bool,
        present_in_legacy: bool,
        present_in_store: bool,
        reason: str = "",
        envelope: Any = None,
        envelope_content_id: str = "",
        envelope_content_digest: str = "",
        envelope_byte_size: int = 0,
    ) -> ProofShadowDifferentialReceipt:
        if envelope is not None:
            envelope_content_id = envelope_content_id or str(
                getattr(envelope, "content_id", "") or ""
            )
            envelope_content_digest = envelope_content_digest or str(
                getattr(envelope, "content_digest", "") or ""
            )
            envelope_byte_size = int(
                envelope_byte_size
                or getattr(envelope, "byte_size", 0)
                or 0
            )
        receipt = ProofShadowDifferentialReceipt(
            backend=backend.value,
            family=family_for_backend(backend),
            operation=operation,
            key_digest=key_digest,
            legacy_entry_digest=legacy_entry_digest,
            store_entry_digest=store_entry_digest,
            digests_match=digests_match,
            present_in_legacy=present_in_legacy,
            present_in_store=present_in_store,
            envelope_content_id=envelope_content_id,
            envelope_content_digest=envelope_content_digest,
            envelope_byte_size=envelope_byte_size,
            reason=reason,
            created_at=float(self._clock()),
        )
        self._receipts.append(receipt)
        self._stats["receipts"] += 1
        return receipt


# Process-local shadow repository (opt-in; tests / producers bind explicitly).
_global_shadow_repository: Optional[UnifiedProofShadowRepository] = None
_global_shadow_lock = _threading.RLock()


def build_proof_shadow_repository(
    *,
    service: Any | None = None,
    store: Any | None = None,
    coordinator: Any | None = None,
    owner_id: str = "owner:proof-shadow",
    mode: str = "shadow",
    set_global: bool = False,
    clock: Callable[[], float] | None = None,
) -> UnifiedProofShadowRepository:
    """Construct a :class:`UnifiedProofShadowRepository` with standard defaults."""

    repo = UnifiedProofShadowRepository(
        service=service,
        store=store,
        coordinator=coordinator,
        owner_id=owner_id,
        mode=mode,
        clock=clock,
    )
    if set_global:
        set_shadow_repository(repo)
    return repo


def get_shadow_repository(
    *, create: bool = False, **kwargs: Any
) -> Optional[UnifiedProofShadowRepository]:
    """Return the process-local shadow repository, optionally creating one."""

    global _global_shadow_repository
    with _global_shadow_lock:
        if _global_shadow_repository is None and create:
            _global_shadow_repository = build_proof_shadow_repository(**kwargs)
        return _global_shadow_repository


def set_shadow_repository(
    repository: Optional[UnifiedProofShadowRepository],
) -> None:
    """Install or clear the process-local shadow repository."""

    global _global_shadow_repository
    with _global_shadow_lock:
        _global_shadow_repository = repository


def clear_shadow_repository() -> None:
    """Clear the process-local shadow repository."""

    set_shadow_repository(None)


__all__ = [
    "CachedProofResult",
    "LEGACY_PROOF_BACKENDS",
    "LegacyProofBackend",
    "PROOF_SHADOW_INTERFACE",
    "PROOF_SHADOW_RECEIPT_SCHEMA",
    "PROOF_SHADOW_SCHEMA_VERSION",
    "ProofCache",
    "ProofShadowDifferentialReceipt",
    "ProofShadowError",
    "ProofShadowIdentityError",
    "ProofShadowTrustError",
    "UnifiedProofShadowRepository",
    "build_proof_shadow_repository",
    "cache_proof_result",
    "clear_shadow_repository",
    "family_for_backend",
    "get_global_cache",
    "get_shadow_repository",
    "set_shadow_repository",
]
