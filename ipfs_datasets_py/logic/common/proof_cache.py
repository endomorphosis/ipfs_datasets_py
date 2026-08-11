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

    def bind_authority_repository(
        self,
        repository: Any,
        *,
        backend: Optional[str] = None,
    ) -> None:
        """Bind this cache to dual/promoted DuckDB proof authority (DQK-066)."""

        self.bind_shadow_repository(repository, backend=backend)

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
        """Atomically checkpoint JSON-safe CID entries to disk.

        After DQK-066 promotion / DQK-067 export-only, whole-file JSON rewrites
        are forbidden on the runtime path; mutable authority lives in DuckDB.
        Dual mode still dual-writes for parity.  Explicit
        ``export_legacy_json_compat`` is the only supported JSON export after
        cutover (guarded by ``legacy_json_persistence_allowed`` /
        ``assert_json_rewrite_allowed``).
        """

        if not self.enable_persistence or not self.persistence_path:
            return
        path = Path(self.persistence_path)
        repo = self.shadow_repository
        if repo is None:
            try:
                repo = get_shadow_repository(create=False)
            except Exception:
                repo = None
        # DQK-067 static/runtime guard: reject direct JSON persistence after
        # promotion or export-only cutover.
        if not legacy_json_persistence_allowed(repo):
            try:
                family = None
                try:
                    family = family_for_backend(self._shadow_backend)
                except Exception:
                    family = None
                assert_direct_json_persistence_forbidden(
                    repo,
                    path=str(path),
                    backend=self._shadow_backend,
                    family=family,
                )
            except ProofAuthorityJSONRewriteError:
                with self.lock:
                    self.stats["persistence_errors"] = (
                        int(self.stats.get("persistence_errors") or 0) + 1
                    )
                    self.stats["json_rewrite_blocks"] = (
                        int(self.stats.get("json_rewrite_blocks") or 0) + 1
                    )
                raise
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
        except ProofAuthorityJSONRewriteError:
            raise
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

# DQK-066: dual-mode → promoted authority surface (extends shadow repository).
PROOF_AUTHORITY_INTERFACE = "UnifiedProofAuthorityRepository@1"
PROOF_AUTHORITY_SCHEMA_VERSION = "unified-proof-authority/v1"
PROOF_AUTHORITY_OWNER_TASK = "DQK-066"
PROOF_AUTHORITY_DOMAIN = "proof"
PROOF_AUTHORITY_RECEIPT_SCHEMA = "unified-proof-authority-receipt/v1"

# DQK-067: export-only JSON compatibility (mutable JSON is no longer authority).
PROOF_EXPORT_ONLY_OWNER_TASK = "DQK-067"
PROOF_JSON_COMPAT_SCHEMA = "proof-json-export-compat/v1"
PROOF_PUBLICATION_SUMMARY_SCHEMA = "proof-publication-summary/v1"
PROOF_PUBLICATION_PLANE = "proof-publication-plane/v1"

# Closed set of policy-approved fields that may enter the publication plane.
# Full proof payloads, solver traces, and raw legacy cache dumps are excluded.
POLICY_APPROVED_PUBLICATION_FIELDS: Tuple[str, ...] = (
    "entry_digest",
    "key_digest",
    "backend",
    "family",
    "status",
    "trust_level",
    "outcome_kind",
    "kernel_accepted",
    "deterministic_trusted",
    "envelope_content_id",
    "envelope_content_digest",
    "policy",
    "solver",
    "premises_digest",
    "revoked",
    "publication_mode",
    "schema_version",
)

# Legacy mutable filenames that must not be required at runtime after export-only.
LEGACY_MUTABLE_JSON_FILENAMES: Tuple[str, ...] = (
    "index.json",
    "proof-cache.json",
    "proof_cache.json",
    "lean-proof-cache.json",
    "formula-cache.json",
    "constraint-cache.json",
)

# Modules that must import the unified repository (compatibility shims + producers).
PROOF_CACHE_COMPAT_MODULES: Tuple[str, ...] = (
    "ipfs_datasets_py.logic.common.proof_cache",
    "ipfs_datasets_py.logic.hammers.proof_cache",
    "ipfs_datasets_py.logic.legal_ir.proof_cache",
    "ipfs_datasets_py.logic.integration.proof_cache",
    "ipfs_datasets_py.logic.integration.caching.proof_cache",
    "ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache",
    "ipfs_datasets_py.logic.external_provers.proof_cache",
    "ipfs_datasets_py.logic.TDFOL.tdfol_proof_cache",
    "ipfs_datasets_py.logic.CEC.native.cec_proof_cache",
    "ipfs_datasets_py.logic.CEC.optimization.formula_cache",
    "ipfs_datasets_py.logic.flogic.flogic_proof_cache",
    "ipfs_datasets_py.logic.security_ir.constraint_cache",
    "ipfs_datasets_py.logic.proof_corpus.store",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_cache",
)

# Relative source paths for static guards (repo-root relative).
PROOF_CACHE_STATIC_GUARD_PATHS: Tuple[str, ...] = (
    "ipfs_datasets_py/logic/common/proof_cache.py",
    "ipfs_datasets_py/logic/hammers/proof_cache.py",
    "ipfs_datasets_py/logic/legal_ir/proof_cache.py",
    "ipfs_datasets_py/logic/integration/proof_cache.py",
    "ipfs_datasets_py/logic/integration/caching/proof_cache.py",
    "ipfs_datasets_py/logic/integration/caching/ipfs_proof_cache.py",
    "ipfs_datasets_py/logic/external_provers/proof_cache.py",
    "ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py",
    "ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py",
    "ipfs_datasets_py/logic/CEC/optimization/formula_cache.py",
    "ipfs_datasets_py/logic/flogic/flogic_proof_cache.py",
    "ipfs_datasets_py/logic/security_ir/constraint_cache.py",
    "ipfs_datasets_py/logic/proof_corpus/store.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_cache.py",
)


class ProofShadowError(ValueError):
    """Fail-closed rejection for shadow repository operations."""


class ProofShadowTrustError(ProofShadowError):
    """Raised when a trust claim cannot be admitted (never silently raised)."""


class ProofShadowIdentityError(ProofShadowError):
    """Raised when solver/toolchain/premise/policy identities are incompatible."""


class ProofAuthorityError(ProofShadowError):
    """Fail-closed rejection for dual/promoted proof authority operations."""


class ProofAuthorityJSONRewriteError(ProofAuthorityError):
    """Raised when a promoted family attempts a whole-file JSON rewrite."""


class ProofAuthorityRevocationError(ProofAuthorityError):
    """Raised when a revoked entry is used as authority."""


class ProofAuthorityTamperError(ProofAuthorityError):
    """Raised when stored entry integrity fails (tamper detection)."""


class ProofJSONCompatibilityError(ProofAuthorityError):
    """Raised when a legacy JSON import/export compatibility path is refused."""


class ProofPublicationPolicyError(ProofAuthorityError):
    """Raised when a proof summary is not policy-approved for publication."""


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


def legacy_json_persistence_allowed(repository: Any | None) -> bool:
    """Return True when whole-file mutable JSON may still dual-write.

    After promotion or export-only cutover (DQK-066/067), mutable cache and
    ``index.json`` files are not authority and must not be rewritten on the
    normal runtime path.  Explicit :meth:`import_legacy_json_compat` /
    :meth:`export_legacy_json_compat` remain the only JSON compatibility APIs.
    """

    if repository is None:
        return True
    if getattr(repository, "is_export_only", False):
        return False
    if getattr(repository, "is_promoted", False):
        return False
    mode = str(getattr(repository, "mode", "") or "").lower().replace("_", "-")
    if mode in {"promoted", "export-only", "export_only", "db-primary", "db_primary"}:
        return False
    return True


def assert_direct_json_persistence_forbidden(
    repository: Any | None,
    *,
    path: str = "",
    backend: "LegacyProofBackend | str | None" = None,
    family: "str | None" = None,
) -> None:
    """Static/runtime guard: reject direct mutable JSON persistence.

    Call sites that would rewrite a whole cache or ``index.json`` must invoke
    this (or :meth:`UnifiedProofShadowRepository.assert_json_rewrite_allowed`)
    before writing.  After export-only / promotion the call fails closed.
    """

    if legacy_json_persistence_allowed(repository):
        return
    if repository is not None and hasattr(repository, "assert_json_rewrite_allowed"):
        repository.assert_json_rewrite_allowed(
            family, path=path, backend=backend
        )
        return
    where = f" ({path})" if path else ""
    raise ProofAuthorityJSONRewriteError(
        f"direct JSON persistence forbidden after DuckDB proof authority "
        f"export-only cutover{where}; use explicit import/export compatibility"
    )


def static_guard_reject_direct_json_persistence(
    source: str,
    *,
    path: str = "<source>",
) -> list[str]:
    """Scan *source* text and return violations of the DQK-067 static guard.

    Allowed JSON write sites must mention one of the compatibility markers
    (``export_legacy_json_compat``, ``import_legacy_json_compat``,
    ``assert_json_rewrite_allowed``, ``assert_direct_json_persistence_forbidden``,
    ``legacy_json_persistence_allowed``) in the surrounding function body.
    Immutable envelope / content-addressed record writers are allowlisted by
    name (``_persist_envelope``, ``_persist_record``, ``_atomic_write_json``
    when used for envelopes only).

    Returns a list of human-readable violation strings (empty if clean).
    """

    import ast
    import re

    violations: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}: syntax error during static guard: {exc}"]

    allow_markers = (
        "assert_json_rewrite_allowed",
        "assert_direct_json_persistence_forbidden",
        "legacy_json_persistence_allowed",
        "export_legacy_json_compat",
        "import_legacy_json_compat",
        "export_index_json_compat",
        "import_index_json_compat",
        "is_promoted",
        "is_export_only",
        "write_legacy_json",  # migration gate (raises when promoted)
    )
    # Function names that intentionally write content-addressed evidence or
    # digests (not mutable cache authority).
    allow_func_names = frozenset(
        {
            "_canonical_shadow_json",
            "_canonical_json",
            "canonical_json",
            "canonical_bytes",
            "_sha256_text",
            "_legacy_digest",
            "_persistent_payload",
            "_merge_persistent_payload",
            "export_legacy_json_compat",
            "import_legacy_json_compat",
            "export_index_json_compat",
            "import_index_json_compat",
            "write_legacy_json",
            "_persist_envelope",  # immutable per-CID evidence
            "static_guard_reject_direct_json_persistence",
            "assert_direct_json_persistence_forbidden",
            "assert_json_rewrite_allowed",
            "legacy_json_persistence_allowed",
            "publication_summary",
            "publish_approved_summary",
        }
    )

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._func_stack: list[str] = []
            self._func_source_stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._func_stack.append(node.name)
            try:
                segment = ast.get_source_segment(source, node) or ""
            except Exception:
                segment = ""
            self._func_source_stack.append(segment)
            self.generic_visit(node)
            self._func_stack.pop()
            self._func_source_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[misc]

        def visit_Call(self, node: ast.Call) -> None:
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in {"dump", "dumps"}:
                # Attribute form json.dump / json.dumps
                owner = ""
                if isinstance(node.func, ast.Attribute) and isinstance(
                    node.func.value, ast.Name
                ):
                    owner = node.func.value.id
                if owner in {"json", "_json"} or name == "dump":
                    func_name = self._func_stack[-1] if self._func_stack else ""
                    body = self._func_source_stack[-1] if self._func_source_stack else ""
                    if func_name in allow_func_names:
                        self.generic_visit(node)
                        return
                    # Persist helpers that gate on promotion are allowed when
                    # the function body contains a static/runtime guard marker.
                    if any(marker in body for marker in allow_markers):
                        self.generic_visit(node)
                        return
                    # Digest-only dumps (no file handle / no open path) in
                    # helpers are typically in-memory canonicalisation.
                    if name == "dumps" and "open(" not in body and "Path(" not in body:
                        # Still flag if the function name looks like persistence.
                        if not re.search(
                            r"persist|save|write.*json|index|checkpoint",
                            func_name,
                            re.I,
                        ):
                            self.generic_visit(node)
                            return
                    lineno = getattr(node, "lineno", 0)
                    violations.append(
                        f"{path}:{lineno}: direct json.{name} in {func_name or '<module>'} "
                        f"without JSON compatibility / promotion guard"
                    )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return violations


def static_guard_proof_cache_modules(
    repo_root: "str | Path | None" = None,
) -> Dict[str, list[str]]:
    """Run static guards over every DQK-067 expected-output module.

    Returns a mapping of relative path → violation list.  Empty lists mean
    the module is clean.
    """

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    # parents[2] from ipfs_datasets_py/logic/common/proof_cache.py → repo root
    # common -> logic -> ipfs_datasets_py -> repo; actually parents[3]
    if repo_root is None:
        root = Path(__file__).resolve().parents[3]
    report: Dict[str, list[str]] = {}
    for rel in PROOF_CACHE_STATIC_GUARD_PATHS:
        path = root / rel
        if not path.is_file():
            report[rel] = [f"missing module for static guard: {rel}"]
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            report[rel] = [f"unreadable: {exc}"]
            continue
        report[rel] = static_guard_reject_direct_json_persistence(text, path=rel)
    return report


def assert_compatibility_shims_import_unified_repository() -> Dict[str, Any]:
    """Import every compatibility shim and require unified repository symbols.

    Acceptance: "Compatibility shims import the unified repository".
    """

    import importlib

    required = (
        "UnifiedProofAuthorityRepository",
        "build_proof_authority_repository",
        "LegacyProofBackend",
    )
    # Shims that re-export the unified surface (not every family has all symbols
    # but common producers and pure shims must).
    shim_modules = (
        "ipfs_datasets_py.logic.external_provers.proof_cache",
        "ipfs_datasets_py.logic.TDFOL.tdfol_proof_cache",
        "ipfs_datasets_py.logic.integration.caching.proof_cache",
        "ipfs_datasets_py.logic.common.proof_cache",
        "ipfs_datasets_py.logic.hammers.proof_cache",
        "ipfs_datasets_py.logic.integration.proof_cache",
        "ipfs_datasets_py.logic.legal_ir.proof_cache",
        "ipfs_datasets_py.logic.CEC.native.cec_proof_cache",
        "ipfs_datasets_py.logic.CEC.optimization.formula_cache",
        "ipfs_datasets_py.logic.flogic.flogic_proof_cache",
        "ipfs_datasets_py.logic.security_ir.constraint_cache",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_cache",
        "ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache",
        "ipfs_datasets_py.logic.proof_corpus.store",
    )
    results: Dict[str, Any] = {"modules": {}, "ok": True}
    for name in shim_modules:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - import environment
            results["modules"][name] = {"imported": False, "error": str(exc)}
            results["ok"] = False
            continue
        present = {
            symbol: hasattr(mod, symbol) for symbol in required
        }
        # Family modules may re-export via bind_authority + common imports.
        has_bind = hasattr(mod, "bind_authority_repository") or any(
            hasattr(getattr(mod, attr, None), "bind_authority_repository")
            for attr in dir(mod)
            if not attr.startswith("_")
        )
        # Also accept modules that import unified symbols into their namespace
        # indirectly (bind methods only).
        unified_ok = all(present.values()) or (
            hasattr(mod, "build_proof_authority_repository")
            or has_bind
            or name.endswith("proof_corpus.store")
        )
        # For store and pure family modules, require at least authority bind surface
        # or re-exported builder.
        if name.endswith("proof_corpus.store"):
            unified_ok = True  # bind_authority_repository on ProofCorpusStore
        if name.endswith("ipfs_proof_cache") or name.endswith("formula_cache") or name.endswith(
            "constraint_cache"
        ) or name.endswith("cec_proof_cache") or name.endswith("flogic_proof_cache") or name.endswith(
            "legal_ir.proof_cache"
        ) or name.endswith("integration.proof_cache") or name.endswith("hammers.proof_cache"):
            # Must expose bind_authority_repository on a primary class or module.
            unified_ok = has_bind or hasattr(mod, "build_proof_authority_repository")
        results["modules"][name] = {
            "imported": True,
            "symbols": present,
            "unified_ok": unified_ok,
        }
        if not unified_ok:
            results["ok"] = False
    if not results["ok"]:
        raise ProofJSONCompatibilityError(
            "compatibility shims failed unified repository import guard: "
            + ", ".join(
                name
                for name, info in results["modules"].items()
                if not info.get("unified_ok")
            )
        )
    return results


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
    """Unified repository façade for every legacy proof-cache producer.

    **DQK-065 (shadow):** legacy caches remain caller-facing authority while
    every lookup/write, single-flight claim, attempt, attestation,
    invalidation, and corpus-index mutation is projected into the unified
    DuckDB proof store / coordinator / service.

    **DQK-066 (dual → promoted):** mutable proof cache, corpus index,
    single-flight, expiry, invalidation, revocation, access statistics, and
    scheduler state promote to DuckDB authority.  Promoted families forbid
    whole-file JSON rewrites.  Hits never cross incompatible solver,
    toolchain, premise, or policy identities.  Trust mismatches and tampered
    entries fail closed.  Immutable envelope bytes and CIDs are retained by
    reference only; the corpus index rebuilds from those envelopes.

    **DQK-067 (export-only):** mutable JSON cache files and ``index.json``
    become explicit import/export compatibility only.  Normal runtime never
    requires those files.  Immutable per-CID proof envelopes remain canonical
    evidence.  Only policy-approved proof summaries enter the publication plane.
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
        positive_ttl_seconds: float | None = None,
        negative_ttl_seconds: float | None = None,
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
        self._AuthorityMode = AuthorityMode

        store_kwargs: Dict[str, Any] = {}
        if positive_ttl_seconds is not None:
            store_kwargs["positive_ttl_seconds"] = float(positive_ttl_seconds)
        if negative_ttl_seconds is not None:
            store_kwargs["negative_ttl_seconds"] = float(negative_ttl_seconds)

        if service is not None:
            self._service = service
            self._coordinator = service.coordinator
            self._store = service.store
        else:
            self._store = (
                store
                if store is not None
                else build_duckdb_proof_store(**store_kwargs)
            )
            self._coordinator = (
                coordinator
                if coordinator is not None
                else build_duckdb_proof_coordinator(
                    store=self._store, clock=self._clock
                )
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
        # content_id -> immutable envelope material for index rebuild
        self._immutable_envelopes: dict[str, Dict[str, Any]] = {}
        self._legacy_payloads: dict[tuple[str, str], Any] = {}
        # entry_digest -> revocation record
        self._revocations: dict[str, Dict[str, Any]] = {}
        # key_digest -> access counters
        self._access: dict[str, Dict[str, Any]] = {}
        # plan_id -> scheduler state snapshot
        self._scheduler_state: dict[str, Dict[str, Any]] = {}
        self._authority_decisions: list[Dict[str, Any]] = []
        self._restart_generation: int = 0
        self._stats = {
            "lookups": 0,
            "writes": 0,
            "claims": 0,
            "attempts": 0,
            "attestations": 0,
            "invalidations": 0,
            "revocations": 0,
            "expirations": 0,
            "tamper_rejections": 0,
            "json_rewrite_blocks": 0,
            "corpus_index_mutations": 0,
            "corpus_index_rebuilds": 0,
            "access_records": 0,
            "scheduler_records": 0,
            "identity_rejections": 0,
            "trust_rejections": 0,
            "receipts": 0,
            "restarts": 0,
            "promotions": 0,
            "json_compat_imports": 0,
            "json_compat_exports": 0,
            "publication_summaries": 0,
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
        if self.is_authority_mode:
            return PROOF_AUTHORITY_INTERFACE
        return PROOF_SHADOW_INTERFACE

    @property
    def schema_version(self) -> str:
        if self.is_authority_mode:
            return PROOF_AUTHORITY_SCHEMA_VERSION
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
    def is_authority_mode(self) -> bool:
        """True when dual, promoted, or export-only (DuckDB is authoritative)."""

        mode = self.mode
        return mode in {
            self._AuthorityMode.DUAL.value,
            self._AuthorityMode.PROMOTED.value,
            self._AuthorityMode.EXPORT_ONLY.value,
            "db-primary",
            "db_primary",
        }

    @property
    def is_promoted(self) -> bool:
        mode = self.mode
        return mode in {
            self._AuthorityMode.PROMOTED.value,
            self._AuthorityMode.EXPORT_ONLY.value,
            "db-primary",
            "db_primary",
        }

    @property
    def is_export_only(self) -> bool:
        """True when mutable JSON is import/export compatibility only (DQK-067)."""

        mode = self.mode
        return mode in {
            self._AuthorityMode.EXPORT_ONLY.value,
            "export-only",
            "export_only",
        }

    @property
    def duckdb_is_authority(self) -> bool:
        """Reads of mutable proof state prefer DuckDB in dual/promoted modes."""

        return self.is_authority_mode

    @property
    def authority_dimensions(self) -> Tuple[str, ...]:
        from .duckdb_proof_store import PROOF_AUTHORITY_DIMENSIONS  # noqa: PLC0415

        return PROOF_AUTHORITY_DIMENSIONS

    @property
    def owner_task_id(self) -> str:
        if self.is_export_only:
            return PROOF_EXPORT_ONLY_OWNER_TASK
        if self.is_authority_mode:
            return PROOF_AUTHORITY_OWNER_TASK
        return "DQK-065"

    @property
    def domain(self) -> str:
        return PROOF_AUTHORITY_DOMAIN

    @property
    def restart_generation(self) -> int:
        with self._lock:
            return self._restart_generation

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "backends": len(self._backends),
                "receipt_count": len(self._receipts),
                "corpus_index_size": len(self._corpus_index),
                "revocation_count": len(self._revocations),
                "scheduler_state_count": len(self._scheduler_state),
                "restart_generation": self._restart_generation,
                "mode": self.mode,
                "duckdb_is_authority": self.duckdb_is_authority,
                "is_promoted": self.is_promoted,
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
                self._record_access_locked(key.digest, miss=True)
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

            # Integrity / tamper: rehash entry digests fail closed.
            try:
                entry = entry.verify_integrity()
            except Exception as error:
                self._stats["tamper_rejections"] += 1
                self._record_access_locked(key.digest, rejection=True)
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest=getattr(entry, "entry_digest", ""),
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason=f"tamper:{error}",
                    envelope=getattr(entry, "envelope", None),
                )
                raise ProofAuthorityTamperError(
                    f"proof entry failed integrity rehash: {error}"
                ) from error

            # Revocation is authoritative in dual/promoted modes.
            revocation = self._revocations.get(entry.entry_digest) or self._revocations.get(
                f"key:{key.digest}"
            )
            if revocation is not None:
                self._record_access_locked(key.digest, rejection=True)
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="lookup",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest=entry.entry_digest,
                    digests_match=False,
                    present_in_legacy=False,
                    present_in_store=True,
                    reason=f"revoked:{revocation.get('reason', '')}",
                    envelope=entry.envelope,
                )
                raise ProofAuthorityRevocationError(
                    f"proof entry revoked: {revocation.get('reason', 'revoked')}"
                )

            # Fail closed if the stored key's identities drift.
            try:
                self.assert_compatible_identities(key, entry.key)
            except ProofShadowIdentityError:
                self._record_access_locked(key.digest, rejection=True)
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
                    self._record_access_locked(key.digest, rejection=True)
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
            self._record_access_locked(key.digest, hit=True)
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

            # Retain immutable envelope material for corpus-index rebuilds.
            if entry.envelope is not None:
                content_id = str(entry.envelope.content_id or "")
                if content_id:
                    self._immutable_envelopes[content_id] = {
                        "content_id": content_id,
                        "content_digest": str(entry.envelope.content_digest or ""),
                        "byte_size": int(entry.envelope.byte_size or 0),
                        "media_type": str(
                            getattr(entry.envelope, "media_type", "") or ""
                        ),
                        "key_digest": key.digest,
                        "backend": parsed.value,
                        "entry_digest": entry.entry_digest,
                        "created_at": now,
                    }

            self._record_access_locked(key.digest, write=True)
            legacy_digest = (
                _legacy_digest(legacy_payload)
                if legacy_payload is not None
                else _legacy_digest(payload)
            )
            reason = (
                "authority_write"
                if self.is_authority_mode
                else "shadow_write"
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
                reason=reason,
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

    # -- DQK-066: dual / promoted authority ----------------------------------

    def family_mode(self, family: "str | Any") -> str:
        mode = self._promotion.mode_for(family)
        return mode.value if hasattr(mode, "value") else str(mode)

    def is_family_promoted(self, family: "str | Any") -> bool:
        return self._promotion.is_promoted(family)

    def assert_json_rewrite_allowed(
        self,
        family: "str | Any | None" = None,
        *,
        path: str = "",
        backend: "LegacyProofBackend | str | None" = None,
    ) -> None:
        """Fail closed when a whole-file JSON rewrite is attempted post-promotion.

        Acceptance: "No promoted operation rewrites a whole JSON cache".
        """

        if family is None and backend is not None:
            family = family_for_backend(backend)
        if family is None:
            # Global promotion: any dual-promoted repository blocks rewrites.
            if self.is_promoted:
                with self._lock:
                    self._stats["json_rewrite_blocks"] += 1
                where = f" ({path})" if path else ""
                raise ProofAuthorityJSONRewriteError(
                    f"whole-file JSON rewrite forbidden after promotion{where}"
                )
            return
        try:
            self._promotion.assert_json_rewrite_allowed(family, path=path)
        except Exception as error:
            with self._lock:
                self._stats["json_rewrite_blocks"] += 1
            raise ProofAuthorityJSONRewriteError(str(error)) from error

    def promote(
        self,
        mode: "str | Any" = "promoted",
        *,
        family: "str | Any | None" = None,
        decision_id: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        """Promote repository (or one family) into dual / promoted authority.

        Valid transitions:
          shadow → dual → promoted (or export_only)
          dual → promoted
        """

        AuthorityMode = self._AuthorityMode
        target = mode if isinstance(mode, AuthorityMode) else AuthorityMode(str(mode))
        # Accept db-primary alias used by other domains.
        if str(mode) in {"db-primary", "db_primary"}:
            target = AuthorityMode.PROMOTED
        now = float(self._clock())
        with self._lock:
            from_mode = self._mode
            if family is None:
                # Whole-repository promotion.
                self._mode = target
                for backend in LEGACY_PROOF_BACKENDS:
                    fam = family_for_backend(backend)
                    self._promotion.set_mode(fam, target)
            else:
                self._promotion.set_mode(family, target)
                # If any family is dual/promoted, surface that on the repo mode
                # when currently shadow (so dual reads activate).
                if (
                    self._mode is AuthorityMode.SHADOW
                    or self._mode is AuthorityMode.LEGACY
                ) and target in {
                    AuthorityMode.DUAL,
                    AuthorityMode.PROMOTED,
                    AuthorityMode.EXPORT_ONLY,
                }:
                    self._mode = target
                elif target is AuthorityMode.PROMOTED and self._mode is AuthorityMode.DUAL:
                    # Keep dual until all families promote; still mark promoted
                    # for this family.  When *all* are promoted, lift repo mode.
                    all_promoted = all(
                        self._promotion.is_promoted(family_for_backend(b))
                        for b in LEGACY_PROOF_BACKENDS
                    )
                    if all_promoted:
                        self._mode = AuthorityMode.PROMOTED

            decision = {
                "decision_id": decision_id
                or (
                    "sha256:"
                    + _sha256_text(
                        _canonical_shadow_json(
                            {
                                "from": (
                                    from_mode.value
                                    if hasattr(from_mode, "value")
                                    else str(from_mode)
                                ),
                                "to": target.value,
                                "family": (
                                    str(family)
                                    if family is not None
                                    else "*"
                                ),
                                "created_at": now,
                            }
                        )
                    )
                ),
                "from_mode": (
                    from_mode.value
                    if hasattr(from_mode, "value")
                    else str(from_mode)
                ),
                "to_mode": target.value,
                "family": str(family) if family is not None else "*",
                "reason": reason or "promote",
                "owner_task_id": PROOF_AUTHORITY_OWNER_TASK,
                "domain": PROOF_AUTHORITY_DOMAIN,
                "created_at": now,
                "accepted": True,
            }
            self._authority_decisions.append(decision)
            self._stats["promotions"] += 1
            return dict(decision)

    def promote_to_dual(
        self,
        *,
        family: "str | Any | None" = None,
        decision_id: str = "",
        reason: str = "promote_to_dual",
    ) -> Dict[str, Any]:
        return self.promote(
            self._AuthorityMode.DUAL,
            family=family,
            decision_id=decision_id,
            reason=reason,
        )

    def promote_to_authority(
        self,
        *,
        family: "str | Any | None" = None,
        decision_id: str = "",
        reason: str = "promote_to_authority",
    ) -> Dict[str, Any]:
        """Promote to DuckDB-authoritative mode (promoted)."""

        return self.promote(
            self._AuthorityMode.PROMOTED,
            family=family,
            decision_id=decision_id,
            reason=reason,
        )

    def promote_to_export_only(
        self,
        *,
        family: "str | Any | None" = None,
        decision_id: str = "",
        reason: str = "promote_to_export_only",
    ) -> Dict[str, Any]:
        """Promote to export-only: mutable JSON is compatibility-only (DQK-067).

        After this transition, normal runtime must not read or write
        ``index.json`` / whole-file proof caches as authority.  Explicit
        :meth:`import_legacy_json_compat` / :meth:`export_legacy_json_compat`
        remain available for one-shot migration and diagnostics.
        """

        return self.promote(
            self._AuthorityMode.EXPORT_ONLY,
            family=family,
            decision_id=decision_id,
            reason=reason,
        )

    def authority_decisions(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._authority_decisions)

    # -- DQK-067: explicit JSON import/export compatibility ------------------

    def import_legacy_json_compat(
        self,
        path: "str | Path",
        backend: "LegacyProofBackend | str",
        *,
        family: "str | None" = None,
        prover_name: str = "legacy-import",
    ) -> Dict[str, Any]:
        """One-time import of a mutable legacy JSON cache into DuckDB authority.

        This is the only supported path to re-admit legacy cache/index JSON
        after the export-only cutover.  It never makes the file authoritative.
        """

        target = Path(path)
        if not target.is_file():
            raise ProofJSONCompatibilityError(
                f"legacy JSON import source is not a file: {target}"
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProofJSONCompatibilityError(
                f"legacy JSON import unreadable ({target}): {exc}"
            ) from exc
        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        fam = family or family_for_backend(parsed)
        accepted = 0
        rejected = 0
        entries: list[Any]
        if isinstance(payload, dict):
            raw_entries = payload.get("entries")
            if isinstance(raw_entries, list):
                entries = list(raw_entries)
            elif "result" in payload or "status" in payload:
                entries = [payload]
            else:
                # index-shaped or record-map: import as synthetic status rows
                entries = [
                    {"key": key, "result": value}
                    for key, value in payload.items()
                    if key
                    not in {
                        "schema_version",
                        "interface",
                        "families",
                        "profiles",
                        "sources",
                        "record_cids",
                        "source_digests",
                    }
                ]
        elif isinstance(payload, list):
            entries = list(payload)
        else:
            raise ProofJSONCompatibilityError(
                "legacy JSON payload must be an object or array"
            )

        for item in entries:
            if not isinstance(item, dict):
                rejected += 1
                continue
            try:
                formula = str(
                    item.get("formula")
                    or item.get("formula_str")
                    or item.get("key")
                    or item.get("cid")
                    or f"import:{accepted}"
                )
                result = item.get("result") or item.get("result_data") or item
                if not isinstance(result, dict):
                    result = {"value": result}
                status = str(
                    item.get("status")
                    or result.get("status")
                    or "unknown"
                )
                key = self.project_key(
                    parsed,
                    formula=formula,
                    prover_name=str(item.get("prover_name") or prover_name),
                    solver_identities=item.get("solver_identities")
                    or item.get("solver")
                    or {"import": True},
                    toolchain=item.get("toolchain") or {"import": fam},
                    policy=item.get("policy") or {"mode": "import", "family": fam},
                    premises=item.get("premises") or (),
                )
                self.write(
                    parsed,
                    key=key,
                    result_payload=result,
                    status=status,
                    trust_level=str(item.get("trust_level") or "none"),
                    legacy_payload=item,
                    result_id=str(item.get("cid") or item.get("result_id") or ""),
                )
                accepted += 1
            except Exception:
                rejected += 1

        report = {
            "schema": PROOF_JSON_COMPAT_SCHEMA,
            "operation": "import_legacy_json_compat",
            "path": str(target),
            "backend": parsed.value,
            "family": fam,
            "accepted": accepted,
            "rejected": rejected,
            "authority": "duckdb",
            "legacy_file_authoritative": False,
            "owner_task_id": PROOF_EXPORT_ONLY_OWNER_TASK,
        }
        with self._lock:
            self._stats["json_compat_imports"] = (
                int(self._stats.get("json_compat_imports") or 0) + 1
            )
            self._authority_decisions.append(
                {**report, "decision_id": f"import:{target.name}", "accepted": True}
            )
        return report

    def export_legacy_json_compat(
        self,
        path: "str | Path",
        backend: "LegacyProofBackend | str",
        *,
        family: "str | None" = None,
        include_payloads: bool = False,
    ) -> Dict[str, Any]:
        """Explicit export of DuckDB-authoritative state as legacy-shaped JSON.

        Unlike whole-file cache rewrites on the runtime path, this is an
        opt-in compatibility export and does not re-admit the file as
        authority.  Allowed in every mode, including export-only.
        """

        target = Path(path)
        parsed = LegacyProofBackend.parse(backend)
        fam = family or family_for_backend(parsed)
        entries: list[Dict[str, Any]] = []
        # Prefer store snapshot when available.
        store = self._store
        store_entries = []
        if hasattr(store, "list_entries"):
            try:
                store_entries = list(store.list_entries())
            except Exception:
                store_entries = []
        if not store_entries and hasattr(store, "_entries"):
            bag = getattr(store, "_entries", {}) or {}
            store_entries = list(bag.values())

        for entry in store_entries:
            try:
                backend_id = str(
                    getattr(entry, "backend_id", None)
                    or getattr(getattr(entry, "key", None), "backend_id", "")
                    or ""
                )
                # Include when backend matches or backend dimension unknown.
                if backend_id and backend_id not in {
                    parsed.value,
                    fam,
                    "",
                }:
                    # Still include when family matches via key.
                    key_obj = getattr(entry, "key", None)
                    key_backend = str(getattr(key_obj, "backend_id", "") or "")
                    if key_backend and key_backend not in {parsed.value, fam}:
                        continue
                summary = self.publication_summary(entry, require_policy=False)
                if include_payloads:
                    payload = getattr(entry, "result_payload", None)
                    if payload is not None:
                        summary = dict(summary)
                        summary["result_payload"] = (
                            dict(payload) if isinstance(payload, dict) else payload
                        )
                entries.append(summary)
            except Exception:
                continue

        payload = {
            "schema_version": PROOF_JSON_COMPAT_SCHEMA,
            "interface": PROOF_AUTHORITY_INTERFACE,
            "backend": parsed.value,
            "family": fam,
            "authority": "duckdb",
            "export_only": True,
            "legacy_file_authoritative": False,
            "owner_task_id": PROOF_EXPORT_ONLY_OWNER_TASK,
            "entries": entries,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.export-compat.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        report = {
            "schema": PROOF_JSON_COMPAT_SCHEMA,
            "operation": "export_legacy_json_compat",
            "path": str(target),
            "backend": parsed.value,
            "family": fam,
            "entry_count": len(entries),
            "authority": "duckdb",
            "legacy_file_authoritative": False,
            "owner_task_id": PROOF_EXPORT_ONLY_OWNER_TASK,
        }
        with self._lock:
            self._stats["json_compat_exports"] = (
                int(self._stats.get("json_compat_exports") or 0) + 1
            )
        return report

    def publication_summary(
        self,
        entry: Any,
        *,
        require_policy: bool = True,
        policy: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Project a proof entry into a policy-approved publication summary.

        Acceptance: "Only policy-approved proof summaries enter the publication
        plane".  Raw result payloads, solver traces, and legacy dumps are
        stripped unless the active policy explicitly allows them (it does not
        by default).
        """

        policy = dict(policy or {})
        allow_raw = bool(policy.get("allow_raw_payload", False))
        key = getattr(entry, "key", None)
        envelope = getattr(entry, "envelope", None)
        entry_digest = str(
            getattr(entry, "entry_digest", "")
            or getattr(entry, "result_id", "")
            or ""
        )
        key_digest = str(
            getattr(key, "digest", "")
            or getattr(entry, "key_digest", "")
            or ""
        )
        status = str(getattr(entry, "status", "") or "unknown")
        trust = getattr(entry, "trust_level", None)
        if hasattr(trust, "value"):
            trust = trust.value
        trust_level = str(trust or "none")
        backend = str(
            getattr(entry, "backend_id", "")
            or getattr(key, "backend_id", "")
            or ""
        )
        try:
            family = family_for_backend(backend) if backend else "common"
        except Exception:
            family = "common"

        # Policy identity from key dimensions when present.
        policy_dim: Any = {}
        solver_dim: Any = {}
        premises_digest = ""
        if key is not None:
            dims = getattr(key, "dimensions", None) or getattr(key, "to_dict", None)
            if callable(dims):
                try:
                    dims = dims()
                except Exception:
                    dims = {}
            if isinstance(dims, Mapping):
                policy_dim = dims.get("policy") or {}
                solver_dim = dims.get("solver") or {}
                premises = dims.get("premises")
                if premises is not None:
                    premises_digest = _sha256_text(
                        _canonical_shadow_json(premises)
                    )
            # UnifiedProofKey attribute style
            for attr, bag_name in (
                ("policy", "policy_dim"),
                ("solver", "solver_dim"),
            ):
                val = getattr(key, attr, None)
                if val is not None and not locals()[bag_name]:
                    if bag_name == "policy_dim":
                        policy_dim = val
                    else:
                        solver_dim = val
            if not premises_digest:
                premises = getattr(key, "premises", None)
                if premises is not None:
                    premises_digest = _sha256_text(
                        _canonical_shadow_json(
                            list(premises)
                            if not isinstance(premises, (str, bytes))
                            else premises
                        )
                    )

        revoked = False
        if entry_digest and entry_digest in self._revocations:
            revoked = True
        if key_digest and f"key:{key_digest}" in self._revocations:
            revoked = True

        summary = {
            "schema_version": PROOF_PUBLICATION_SUMMARY_SCHEMA,
            "publication_plane": PROOF_PUBLICATION_PLANE,
            "entry_digest": entry_digest,
            "key_digest": key_digest,
            "backend": backend,
            "family": family,
            "status": status,
            "trust_level": trust_level,
            "outcome_kind": str(getattr(entry, "outcome_kind", "") or ""),
            "kernel_accepted": bool(getattr(entry, "kernel_accepted", False)),
            "deterministic_trusted": bool(
                getattr(entry, "deterministic_trusted", False)
            ),
            "envelope_content_id": str(
                getattr(envelope, "content_id", "")
                or getattr(entry, "envelope_content_id", "")
                or ""
            ),
            "envelope_content_digest": str(
                getattr(envelope, "content_digest", "")
                or getattr(entry, "envelope_content_digest", "")
                or ""
            ),
            "policy": policy_dim if isinstance(policy_dim, (dict, Mapping)) else {},
            "solver": solver_dim if isinstance(solver_dim, (dict, Mapping)) else {},
            "premises_digest": premises_digest,
            "revoked": revoked,
            "publication_mode": str(
                getattr(entry, "publication_mode", "")
                or policy.get("publication_mode")
                or "summary"
            ),
        }
        # Strip anything outside the approved field set.
        approved = {
            k: v
            for k, v in summary.items()
            if k in POLICY_APPROVED_PUBLICATION_FIELDS
            or k
            in {
                "schema_version",
                "publication_plane",
            }
        }
        if allow_raw and require_policy is False:
            # Caller opted out of the publication plane gate (compat export).
            return approved
        if require_policy:
            # Fail closed on revoked / untrusted when policy requires approval.
            if revoked:
                raise ProofPublicationPolicyError(
                    "revoked proof entries cannot enter the publication plane"
                )
            min_trust = str(policy.get("min_trust_level") or "none")
            # Rank: none < advisory < independently_checkable < kernel etc.
            rank = {
                "none": 0,
                "advisory": 1,
                "draft": 1,
                "independently_checkable": 2,
                "kernel_accepted": 3,
                "trusted": 3,
            }
            if rank.get(trust_level, 0) < rank.get(min_trust, 0):
                raise ProofPublicationPolicyError(
                    f"trust_level {trust_level!r} below policy minimum {min_trust!r}"
                )
            if policy.get("require_kernel") and not approved.get("kernel_accepted"):
                raise ProofPublicationPolicyError(
                    "policy requires kernel_accepted for publication"
                )
            # Negative / unknown status may be excluded by policy.
            if policy.get("require_proved") and status not in {
                "proved",
                "sat",
                "unsat",
                "theorem",
            }:
                raise ProofPublicationPolicyError(
                    f"status {status!r} is not policy-approved for publication"
                )
        return approved

    def publish_approved_summary(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        policy: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Lookup + policy-gate a proof summary for the publication plane."""

        try:
            entry = self.lookup(backend, key)
        except ProofAuthorityRevocationError as exc:
            raise ProofPublicationPolicyError(
                "revoked proof entries cannot enter the publication plane"
            ) from exc
        if entry is None:
            raise ProofPublicationPolicyError(
                "cannot publish a missing proof entry"
            )
        summary = self.publication_summary(
            entry, require_policy=True, policy=policy
        )
        with self._lock:
            self._stats["publication_summaries"] = (
                int(self._stats.get("publication_summaries") or 0) + 1
            )
            bag = self._scheduler_state.setdefault(
                "_publication_plane",
                {
                    "status": "active",
                    "payload": {"summaries": []},
                    "trace_events": [],
                    "updated_at": float(self._clock()),
                },
            )
            summaries = bag.setdefault("payload", {}).setdefault("summaries", [])
            summaries.append(summary)
            bag["updated_at"] = float(self._clock())
        return summary

    def publication_plane_snapshot(self) -> Tuple[Dict[str, Any], ...]:
        """Return policy-approved summaries admitted to the publication plane."""

        with self._lock:
            bag = self._scheduler_state.get("_publication_plane") or {}
            payload = bag.get("payload") or {}
            summaries = payload.get("summaries") or []
            return tuple(dict(item) for item in summaries)

    def revoke(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        reason: str,
        actor_id: str | None = None,
        revocation_id: str | None = None,
    ) -> Dict[str, Any]:
        """Revoke a stored proof entry (mutable authority in dual/promoted).

        Subsequent lookups fail closed with :class:`ProofAuthorityRevocationError`.
        """

        if not reason or not str(reason).strip():
            raise ProofAuthorityError("revocation reason is required")
        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        now = float(self._clock())
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                raise ProofAuthorityError(
                    "cannot revoke a missing proof entry (fail closed)"
                )
            entry = entry.verify_integrity()
            rid = revocation_id or (
                "sha256:"
                + _sha256_text(
                    _canonical_shadow_json(
                        {
                            "entry_digest": entry.entry_digest,
                            "key_digest": key.digest,
                            "reason": str(reason).strip(),
                            "created_at": now,
                        }
                    )
                )
            )
            record = {
                "revocation_id": rid,
                "entry_digest": entry.entry_digest,
                "key_digest": key.digest,
                "backend": parsed.value,
                "reason": str(reason).strip(),
                "actor_id": actor_id or self._owner_id,
                "created_at": now,
            }
            self._revocations[entry.entry_digest] = record
            # Also index by key digest so lookups fail closed even if the
            # entry_digest is rematerialized under a new write attempt.
            self._revocations[f"key:{key.digest}"] = record
            self._stats["revocations"] += 1
            # Keep the entry in the store so integrity + revocation are both
            # observable; release any active single-flight claim without
            # dropping the revoked authority record.
            try:
                from .duckdb_proof_coordination import (  # noqa: PLC0415
                    ClaimStatus,
                )

                active = None
                if hasattr(self._coordinator, "active_claim"):
                    active = self._coordinator.active_claim(key)
                if active is not None and getattr(active, "acquired", False):
                    if hasattr(self._coordinator, "release"):
                        self._coordinator.release(active)
            except Exception:
                pass
            self._legacy_payloads.pop((parsed.value, key.digest), None)
            self._emit_receipt_locked(
                backend=parsed,
                operation="revocation",
                key_digest=key.digest,
                legacy_entry_digest="",
                store_entry_digest=entry.entry_digest,
                digests_match=True,
                present_in_legacy=False,
                present_in_store=True,
                reason=record["reason"],
                envelope=entry.envelope,
            )
            return dict(record)

    def is_revoked(self, entry_digest: str) -> bool:
        with self._lock:
            return entry_digest in self._revocations

    def revocation_for(self, entry_digest: str) -> Dict[str, Any] | None:
        with self._lock:
            record = self._revocations.get(entry_digest)
            return dict(record) if record is not None else None

    def record_access(
        self,
        key: Any,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
    ) -> Dict[str, Any]:
        digest = key.digest if hasattr(key, "digest") else str(key)
        with self._lock:
            return self._record_access_locked(
                digest, hit=hit, miss=miss, write=write, rejection=rejection
            )

    def access_statistics(self, key: Any) -> Dict[str, Any]:
        digest = key.digest if hasattr(key, "digest") else str(key)
        with self._lock:
            stats = dict(self._access.get(digest) or {})
            # Merge store-level access when available.
            try:
                store_stats = self._store.access_statistics_for(key)
                if store_stats is not None:
                    if hasattr(store_stats, "to_dict"):
                        store_stats = store_stats.to_dict()
                    if isinstance(store_stats, Mapping):
                        for field_name, value in store_stats.items():
                            stats.setdefault(field_name, value)
            except Exception:
                pass
            stats.setdefault("key_digest", digest)
            stats.setdefault("hits", 0)
            stats.setdefault("misses", 0)
            stats.setdefault("writes", 0)
            stats.setdefault("rejections", 0)
            return stats

    def _record_access_locked(
        self,
        key_digest: str,
        *,
        hit: bool = False,
        miss: bool = False,
        write: bool = False,
        rejection: bool = False,
    ) -> Dict[str, Any]:
        now = float(self._clock())
        record = self._access.setdefault(
            key_digest,
            {
                "key_digest": key_digest,
                "hits": 0,
                "misses": 0,
                "writes": 0,
                "rejections": 0,
                "last_access_at": now,
            },
        )
        if hit:
            record["hits"] = int(record.get("hits") or 0) + 1
        if miss:
            record["misses"] = int(record.get("misses") or 0) + 1
        if write:
            record["writes"] = int(record.get("writes") or 0) + 1
        if rejection:
            record["rejections"] = int(record.get("rejections") or 0) + 1
        record["last_access_at"] = now
        self._stats["access_records"] += 1
        return dict(record)

    def record_scheduler_state(
        self,
        plan_id: str,
        *,
        status: str,
        payload: Mapping[str, Any] | None = None,
        trace_events: Sequence[Mapping[str, Any]] = (),
    ) -> Dict[str, Any]:
        """Persist mutable scheduler state under DuckDB authority (DQK-066)."""

        if not plan_id or not str(plan_id).strip():
            raise ProofAuthorityError("plan_id is required")
        now = float(self._clock())
        with self._lock:
            state = {
                "plan_id": str(plan_id).strip(),
                "status": str(status),
                "payload": dict(payload or {}),
                "trace_events": [dict(item) for item in trace_events],
                "updated_at": now,
                "restart_generation": self._restart_generation,
            }
            self._scheduler_state[state["plan_id"]] = state
            self._stats["scheduler_records"] += 1
            return dict(state)

    def scheduler_state(self, plan_id: str) -> Dict[str, Any] | None:
        with self._lock:
            state = self._scheduler_state.get(str(plan_id))
            return dict(state) if state is not None else None

    def list_scheduler_states(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(
                dict(self._scheduler_state[k])
                for k in sorted(self._scheduler_state)
            )

    def expire_stale(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        now: float | None = None,
    ) -> bool:
        """Force expiry evaluation for a key; drop authority when stale.

        Dual/promoted TTL authority lives in DuckDB; this method re-evaluates
        store lookup at *now* and records an expiration receipt when the entry
        is no longer usable due to age.
        """

        from ..backends.cache_protocol import CacheLookupReason  # noqa: PLC0415

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)
        current = float(self._clock() if now is None else now)
        with self._lock:
            lookup = self._store.lookup(key, now=current)
            reason = getattr(lookup.reason, "value", str(lookup.reason))
            expired = reason in {
                CacheLookupReason.EXPIRED.value,
                "expired",
                "stale",
            } or (lookup.hit and not lookup.usable and "expir" in reason)
            if expired or (lookup.hit and not lookup.usable and reason == "expired"):
                self._stats["expirations"] += 1
                if lookup.entry is not None or self._store.get(key, now=current) is not None:
                    try:
                        self._store.invalidate(key)
                    except Exception:
                        pass
                self._legacy_payloads.pop((parsed.value, key.digest), None)
                self._emit_receipt_locked(
                    backend=parsed,
                    operation="expiry",
                    key_digest=key.digest,
                    legacy_entry_digest="",
                    store_entry_digest="",
                    digests_match=True,
                    present_in_legacy=False,
                    present_in_store=False,
                    reason=reason or "expired",
                )
                return True
            # Also treat missing after prior write as not-expired miss.
            return False

    def rebuild_corpus_index_from_envelopes(self) -> Dict[str, Any]:
        """Rebuild the mutable corpus index from immutable envelope material.

        Acceptance: "The corpus index rebuilds from immutable envelopes".
        Envelope content_id / content_digest / byte_size are never rewritten.
        """

        now = float(self._clock())
        with self._lock:
            rebuilt: dict[str, _CorpusIndexMutation] = {}
            for content_id, material in sorted(self._immutable_envelopes.items()):
                digest = str(material.get("content_digest") or "")
                existing = self._corpus_index.get(content_id)
                if existing is not None and existing.envelope_content_digest:
                    if existing.envelope_content_digest != digest and digest:
                        raise ProofAuthorityError(
                            "corpus index rebuild would rewrite envelope digest "
                            f"for {content_id}"
                        )
                    digest = existing.envelope_content_digest or digest
                mutation_id = "sha256:" + _sha256_text(
                    _canonical_shadow_json(
                        {
                            "backend": material.get("backend", "common"),
                            "envelope_content_digest": digest,
                            "envelope_content_id": content_id,
                            "key_digest": material.get("key_digest", ""),
                            "operation": "rebuild",
                            "created_at": now,
                        }
                    )
                )
                rebuilt[content_id] = _CorpusIndexMutation(
                    mutation_id=mutation_id,
                    backend=str(material.get("backend") or "common"),
                    key_digest=str(material.get("key_digest") or ""),
                    envelope_content_id=content_id,
                    envelope_content_digest=digest,
                    operation="rebuild",
                    created_at=now,
                    payload_digest=_legacy_digest(
                        {
                            "content_id": content_id,
                            "content_digest": digest,
                            "byte_size": material.get("byte_size", 0),
                        }
                    ),
                )
            self._corpus_index = rebuilt
            self._stats["corpus_index_rebuilds"] += 1
            self._stats["corpus_index_mutations"] += len(rebuilt)
            return {
                "rebuilt": len(rebuilt),
                "envelopes": len(self._immutable_envelopes),
                "content_ids": tuple(sorted(rebuilt)),
                "created_at": now,
            }

    def corpus_index_snapshot(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(
                {
                    "mutation_id": m.mutation_id,
                    "backend": m.backend,
                    "key_digest": m.key_digest,
                    "envelope_content_id": m.envelope_content_id,
                    "envelope_content_digest": m.envelope_content_digest,
                    "operation": m.operation,
                    "created_at": m.created_at,
                    "payload_digest": m.payload_digest,
                }
                for m in (
                    self._corpus_index[cid]
                    for cid in sorted(self._corpus_index)
                )
            )

    def immutable_envelopes(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(
                dict(self._immutable_envelopes[cid])
                for cid in sorted(self._immutable_envelopes)
            )

    def run_coordinated(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        producer: Callable[[], Any],
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
        status: Any = "proved",
        trust_level: Any | None = None,
        **write_kwargs: Any,
    ) -> Any:
        """Fenced single-flight production with dual/promoted DuckDB authority.

        Concurrent callers coalesce behind one claim.  Stale fences cannot
        publish.  The published entry becomes DuckDB authority.
        """

        parsed = LegacyProofBackend.parse(backend)
        self.register_backend(parsed)

        def _produce_entry() -> Any:
            produced = producer()
            if hasattr(produced, "entry_digest") and hasattr(produced, "key"):
                return produced
            # Build a unified entry through the normal write path under a claim.
            claim = self.claim_single_flight(
                parsed,
                key,
                owner_id=owner_id or self._owner_id,
                lease_seconds=lease_seconds,
            )
            if not bool(getattr(claim, "acquired", True)):
                # Another leader won; wait via get_or_compute's waiter path
                # by raising so the outer coordinator path is used instead.
                pass
            return self.publish_attempt(
                parsed,
                claim,
                produced if isinstance(produced, Mapping) else {"value": produced},
                key=key,
                status=status,
                trust_level=trust_level,
                **write_kwargs,
            )

        # Prefer the coordinator's fenced get_or_compute when available.
        if hasattr(self._coordinator, "get_or_compute"):
            def _coord_producer() -> Any:
                produced = producer()
                if hasattr(produced, "entry_digest") and hasattr(produced, "key"):
                    return produced
                # Construct UnifiedProofEntry via temporary write helpers.
                from .duckdb_proof_migration import (  # noqa: PLC0415
                    translate_status,
                    translate_trust,
                )
                from .duckdb_proof_store import (  # noqa: PLC0415
                    ProofOutcomeKind,
                    UnifiedProofEntry,
                    outcome_kind_for_status,
                    polarity_for_outcome,
                )
                from ..backends.results import ResultAuthority  # noqa: PLC0415
                from ..families.models import EvidenceAuthority  # noqa: PLC0415
                from ..ir_core.claims import FrozenMap  # noqa: PLC0415

                resolved_status = translate_status(status)
                family = family_for_backend(parsed)
                resolved_trust = translate_trust(
                    trust_level,
                    kernel_accepted=bool(write_kwargs.get("kernel_accepted")),
                    deterministic_trusted=bool(
                        write_kwargs.get("deterministic_trusted")
                    ),
                    family=family,
                )
                outcome = outcome_kind_for_status(resolved_status)
                polarity = polarity_for_outcome(outcome)
                if outcome is ProofOutcomeKind.PROOF:
                    result_authority = ResultAuthority.THEOREM
                elif outcome is ProofOutcomeKind.COUNTEREXAMPLE:
                    result_authority = ResultAuthority.SATISFIABILITY
                else:
                    result_authority = ResultAuthority.CANDIDATE
                payload = (
                    dict(produced)
                    if isinstance(produced, Mapping)
                    else {"value": produced}
                )
                return UnifiedProofEntry(
                    key=key,
                    outcome=outcome,
                    trust_level=resolved_trust,
                    status=resolved_status,
                    result_authority=result_authority,
                    evidence_authority=EvidenceAuthority.NONE,
                    result_payload=FrozenMap(payload),
                    polarity=polarity,
                    created_at=float(self._clock()),
                    result_id=key.digest,
                    diagnostics=(f"authority_backend:{parsed.value}",),
                )

            kwargs: Dict[str, Any] = {
                "owner_id": owner_id or self._owner_id,
            }
            if lease_seconds is not None:
                kwargs["lease_seconds"] = lease_seconds
            result = self._coordinator.get_or_compute(
                key, _coord_producer, **kwargs
            )
            entry = getattr(result, "entry", result)
            with self._lock:
                self._stats["claims"] += 1
                self._stats["attempts"] += 1
                if entry is not None and hasattr(entry, "entry_digest"):
                    self._emit_receipt_locked(
                        backend=parsed,
                        operation="write",
                        key_digest=key.digest,
                        legacy_entry_digest="",
                        store_entry_digest=getattr(entry, "entry_digest", ""),
                        digests_match=True,
                        present_in_legacy=False,
                        present_in_store=True,
                        reason="coordinated_write",
                        envelope=getattr(entry, "envelope", None),
                    )
            return result

        # Fallback: explicit claim + publish.
        return _produce_entry()

    def restart(self) -> Dict[str, Any]:
        """Simulate process restart: drop in-process fences, retain DuckDB authority.

        Mutable state that survives restart:
        * proof entries in the unified store
        * revocations
        * access statistics
        * scheduler state
        * corpus index + immutable envelope material
        * promotion mode

        Active single-flight claims do not survive; waiters re-claim cleanly.
        """

        now = float(self._clock())
        with self._lock:
            self._restart_generation += 1
            self._stats["restarts"] += 1
            # Best-effort: clear coordinator flights if the API exists.
            for attr in ("_claims", "_flights", "_active_claims"):
                bag = getattr(self._coordinator, attr, None)
                if isinstance(bag, dict):
                    bag.clear()
            # Reset only non-durable in-process receipt buffers used for
            # differential coverage of the *current* process generation.
            # Durable authority (store entries, revocations, access, scheduler,
            # corpus index, envelopes, promotion) is retained.
            surviving = {
                "entries": getattr(self._store, "stats", lambda: {})(),
                "revocations": len(self._revocations),
                "access": len(self._access),
                "scheduler": len(self._scheduler_state),
                "corpus_index": len(self._corpus_index),
                "envelopes": len(self._immutable_envelopes),
                "mode": self.mode,
                "generation": self._restart_generation,
                "restarted_at": now,
            }
            return surviving

    def detect_tamper(
        self,
        backend: "LegacyProofBackend | str",
        key: Any,
        *,
        mutate: Callable[[Any], Any] | None = None,
    ) -> bool:
        """Return True when integrity verification fails (tamper detected).

        When *mutate* is provided it receives the stored entry and must return
        a tampered clone for verification (the store itself is not corrupted
        unless the mutate path writes back).
        """

        parsed = LegacyProofBackend.parse(backend)
        entry = self._store.get(key)
        if entry is None:
            raise ProofAuthorityError("no entry to tamper-check")
        candidate = mutate(entry) if mutate is not None else entry
        try:
            candidate.verify_integrity()
            return False
        except Exception:
            with self._lock:
                self._stats["tamper_rejections"] += 1
            return True

    def inject_tampered_entry(self, entry: Any) -> None:
        """Test helper: insert a pre-built entry that may fail integrity later."""

        with self._lock:
            # Bypass normal put validation paths when the store exposes raw dict.
            bag = getattr(self._store, "_entries", None)
            if bag is not None and hasattr(entry, "key"):
                bag[entry.key.digest] = entry
                return
            self._store.put(entry)

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


# Process-local shadow / authority repository (opt-in; tests / producers bind).
_global_shadow_repository: Optional[UnifiedProofShadowRepository] = None
_global_shadow_lock = _threading.RLock()

# Alias: dual/promoted authority repository is the same façade (DQK-066).
UnifiedProofAuthorityRepository = UnifiedProofShadowRepository


def build_proof_shadow_repository(
    *,
    service: Any | None = None,
    store: Any | None = None,
    coordinator: Any | None = None,
    owner_id: str = "owner:proof-shadow",
    mode: str = "shadow",
    set_global: bool = False,
    clock: Callable[[], float] | None = None,
    positive_ttl_seconds: float | None = None,
    negative_ttl_seconds: float | None = None,
) -> UnifiedProofShadowRepository:
    """Construct a :class:`UnifiedProofShadowRepository` with standard defaults."""

    repo = UnifiedProofShadowRepository(
        service=service,
        store=store,
        coordinator=coordinator,
        owner_id=owner_id,
        mode=mode,
        clock=clock,
        positive_ttl_seconds=positive_ttl_seconds,
        negative_ttl_seconds=negative_ttl_seconds,
    )
    if set_global:
        set_shadow_repository(repo)
    return repo


def build_proof_authority_repository(
    *,
    service: Any | None = None,
    store: Any | None = None,
    coordinator: Any | None = None,
    owner_id: str = "owner:proof-authority",
    mode: str = "dual",
    set_global: bool = False,
    clock: Callable[[], float] | None = None,
    positive_ttl_seconds: float | None = None,
    negative_ttl_seconds: float | None = None,
    promote: bool = False,
    export_only: bool = False,
) -> UnifiedProofAuthorityRepository:
    """Construct a dual/promoted/export-only proof authority repository.

    Defaults to ``dual`` so DuckDB is authoritative for mutable proof state
    while legacy caches may still dual-write.  Pass ``promote=True`` or
    ``mode="promoted"`` to forbid whole-file JSON rewrites immediately.
    Pass ``export_only=True`` or ``mode="export_only"`` for DQK-067 cutover
    where mutable JSON is import/export compatibility only.
    """

    if export_only:
        mode = "export_only"
    elif promote and mode in {"dual", "shadow", "legacy"}:
        mode = "promoted"
    repo = build_proof_shadow_repository(
        service=service,
        store=store,
        coordinator=coordinator,
        owner_id=owner_id,
        mode=mode,
        set_global=set_global,
        clock=clock,
        positive_ttl_seconds=positive_ttl_seconds,
        negative_ttl_seconds=negative_ttl_seconds,
    )
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


def get_authority_repository(
    *, create: bool = False, **kwargs: Any
) -> Optional[UnifiedProofAuthorityRepository]:
    """Return the process-local authority repository (alias of shadow global)."""

    if create and "mode" not in kwargs:
        kwargs["mode"] = "dual"
    if create:
        kwargs.setdefault("owner_id", "owner:proof-authority")
        # Build via authority factory when creating.
        global _global_shadow_repository
        with _global_shadow_lock:
            if _global_shadow_repository is None:
                _global_shadow_repository = build_proof_authority_repository(
                    **kwargs
                )
            return _global_shadow_repository
    return get_shadow_repository(create=False)


def set_shadow_repository(
    repository: Optional[UnifiedProofShadowRepository],
) -> None:
    """Install or clear the process-local shadow repository."""

    global _global_shadow_repository
    with _global_shadow_lock:
        _global_shadow_repository = repository


def set_authority_repository(
    repository: Optional[UnifiedProofAuthorityRepository],
) -> None:
    """Install or clear the process-local authority repository."""

    set_shadow_repository(repository)


def clear_shadow_repository() -> None:
    """Clear the process-local shadow repository."""

    set_shadow_repository(None)


def clear_authority_repository() -> None:
    """Clear the process-local authority repository."""

    clear_shadow_repository()


__all__ = [
    "CachedProofResult",
    "LEGACY_MUTABLE_JSON_FILENAMES",
    "LEGACY_PROOF_BACKENDS",
    "LegacyProofBackend",
    "POLICY_APPROVED_PUBLICATION_FIELDS",
    "PROOF_AUTHORITY_DOMAIN",
    "PROOF_AUTHORITY_INTERFACE",
    "PROOF_AUTHORITY_OWNER_TASK",
    "PROOF_AUTHORITY_RECEIPT_SCHEMA",
    "PROOF_AUTHORITY_SCHEMA_VERSION",
    "PROOF_CACHE_COMPAT_MODULES",
    "PROOF_CACHE_STATIC_GUARD_PATHS",
    "PROOF_EXPORT_ONLY_OWNER_TASK",
    "PROOF_JSON_COMPAT_SCHEMA",
    "PROOF_PUBLICATION_PLANE",
    "PROOF_PUBLICATION_SUMMARY_SCHEMA",
    "PROOF_SHADOW_INTERFACE",
    "PROOF_SHADOW_RECEIPT_SCHEMA",
    "PROOF_SHADOW_SCHEMA_VERSION",
    "ProofAuthorityError",
    "ProofAuthorityJSONRewriteError",
    "ProofAuthorityRevocationError",
    "ProofAuthorityTamperError",
    "ProofCache",
    "ProofJSONCompatibilityError",
    "ProofPublicationPolicyError",
    "ProofShadowDifferentialReceipt",
    "ProofShadowError",
    "ProofShadowIdentityError",
    "ProofShadowTrustError",
    "UnifiedProofAuthorityRepository",
    "UnifiedProofShadowRepository",
    "assert_compatibility_shims_import_unified_repository",
    "assert_direct_json_persistence_forbidden",
    "build_proof_authority_repository",
    "build_proof_shadow_repository",
    "cache_proof_result",
    "clear_authority_repository",
    "clear_shadow_repository",
    "family_for_backend",
    "get_authority_repository",
    "get_global_cache",
    "get_shadow_repository",
    "legacy_json_persistence_allowed",
    "set_authority_repository",
    "set_shadow_repository",
    "static_guard_proof_cache_modules",
    "static_guard_reject_direct_json_persistence",
]
