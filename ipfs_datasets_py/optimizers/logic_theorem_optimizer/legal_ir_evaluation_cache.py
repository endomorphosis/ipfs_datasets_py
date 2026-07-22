"""Typed, immutable cache for reusable LegalIR evaluation artifacts.

The daemon evaluates the same statutory sample in several roles (baseline,
guided, train, validation, and individual LegalIR views).  This module keeps
the expensive, role-independent compiler and embedding result behind one
content-addressed boundary.  Entries are JSON rather than pickle so an
untrusted or damaged cache file can never instantiate arbitrary Python
objects.

Both the cache key and the on-disk envelope are deliberately versioned.  A
cache entry is accepted only when its key, schema, payload checksum, and typed
shape all validate.  Anything else is a miss (fail closed) and is replaced by
a fresh computation.  Threads coalesce through an in-memory future and
processes coalesce through a per-key advisory file lock.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, TypeVar

try:  # pragma: no cover - exercised on POSIX in normal daemon deployments.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback still single-flights threads.
    fcntl = None  # type: ignore[assignment]


LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION: Final = "legal-ir-evaluation-cache-v1"
LEGAL_IR_EVALUATION_ARTIFACT_SCHEMA_VERSION: Final = "legal-ir-evaluation-artifact-v1"
LEGAL_IR_EVALUATION_RESULT_SCHEMA_VERSION: Final = "legal-ir-evaluation-result-v1"
DETERMINISTIC_COMPILER_STATE_HASH: Final = "deterministic-compiler-state-independent-v1"
DEFAULT_MAX_ENTRY_BYTES: Final = 8 * 1024 * 1024

_T = TypeVar("_T")


class EvaluationCacheError(RuntimeError):
    """Base error for invalid cache inputs or computed artifacts."""


class InvalidEvaluationArtifactError(EvaluationCacheError, ValueError):
    """Raised when a producer returns an artifact that cannot be trusted."""


def compiler_artifact_state_hash(state_hash: str, *, state_dependent: bool) -> str:
    """Return the state identity appropriate for a compiler artifact.

    Unguided compiler output is a pure function of the sample, compiler build,
    and compiler configuration.  Binding it to the changing autoencoder state
    defeats content-addressed reuse.  Guided output remains state-dependent and
    therefore fails closed when a caller omits its state identity.
    """

    if not state_dependent:
        return DETERMINISTIC_COMPILER_STATE_HASH
    resolved = str(state_hash or "").strip()
    if not resolved:
        raise ValueError("state-dependent compiler artifacts require a state hash")
    return resolved


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def stable_digest(value: Any) -> str:
    """Return a deterministic SHA-256 digest for JSON-compatible input."""

    return hashlib.sha256(_canonical_json(_json_value(value)).encode("utf-8")).hexdigest()


def sample_content_hash(sample: Any) -> str:
    """Hash the immutable sample inputs without retaining source text in the key."""

    if isinstance(sample, (str, bytes, bytearray)):
        raw = sample.encode("utf-8") if isinstance(sample, str) else bytes(sample)
        return hashlib.sha256(raw).hexdigest()
    if isinstance(sample, Mapping):
        payload = dict(sample)
    else:
        payload = {
            name: getattr(sample, name, None)
            for name in (
                "sample_id",
                "text",
                "normalized_text",
                "citation",
                "source",
                "title",
                "section",
                "embedding_model",
                "embedding_vector",
            )
            if hasattr(sample, name)
        }
    return stable_digest(payload)


def configuration_digest(configuration: Any) -> str:
    """Return the stable configuration component used by evaluation keys."""

    return stable_digest(configuration)


def _json_value(value: Any) -> Any:
    """Convert supported values to a finite, deterministic JSON tree."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidEvaluationArtifactError("artifact contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if hasattr(value, "__dict__"):
        return _json_value(
            {
                key: item
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        )
    raise InvalidEvaluationArtifactError(
        f"artifact value of type {type(value).__name__} is not JSON-compatible"
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidEvaluationArtifactError(f"{name} must be a mapping")
    return _freeze(_json_value(value))


@dataclass(frozen=True, slots=True)
class LegalIREvaluationCacheKey:
    """Complete identity of an immutable evaluation computation."""

    sample_hash: str
    compiler_commit: str
    state_hash: str
    metric_schema: str
    config_hash: str

    def __post_init__(self) -> None:
        for name in (
            "sample_hash",
            "compiler_commit",
            "state_hash",
            "metric_schema",
            "config_hash",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            if len(value) > 512 or any(character in value for character in "\r\n\0"):
                raise ValueError(f"{name} is not a valid cache-key component")
            object.__setattr__(self, name, value)

    @classmethod
    def for_sample(
        cls,
        sample: Any,
        *,
        compiler_commit: str,
        state_hash: str,
        metric_schema: str,
        configuration: Any,
    ) -> "LegalIREvaluationCacheKey":
        return cls(
            sample_hash=sample_content_hash(sample),
            compiler_commit=compiler_commit,
            state_hash=state_hash,
            metric_schema=metric_schema,
            config_hash=configuration_digest(configuration),
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "sample_hash": self.sample_hash,
            "compiler_commit": self.compiler_commit,
            "state_hash": self.state_hash,
            "metric_schema": self.metric_schema,
            "config_hash": self.config_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LegalIREvaluationCacheKey":
        return cls(
            sample_hash=str(payload.get("sample_hash") or ""),
            compiler_commit=str(payload.get("compiler_commit") or ""),
            state_hash=str(payload.get("state_hash") or ""),
            metric_schema=str(payload.get("metric_schema") or ""),
            config_hash=str(payload.get("config_hash") or ""),
        )


@dataclass(frozen=True, slots=True)
class LegalIREvaluationArtifact:
    """Role-independent compiler, embedding, and metric data for one sample."""

    key: LegalIREvaluationCacheKey
    compiler_artifact: Mapping[str, Any]
    embedding: tuple[float, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    per_view_metrics: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    compilation_seconds: float = 0.0
    embedding_seconds: float = 0.0
    metric_seconds: float = 0.0
    created_at: str = field(default_factory=_utc_now)
    schema_version: str = LEGAL_IR_EVALUATION_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.key, LegalIREvaluationCacheKey):
            raise InvalidEvaluationArtifactError("artifact key has the wrong type")
        if self.schema_version != LEGAL_IR_EVALUATION_ARTIFACT_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("artifact schema version is stale")
        object.__setattr__(
            self,
            "compiler_artifact",
            _mapping(self.compiler_artifact, name="compiler_artifact"),
        )
        object.__setattr__(self, "metrics", _mapping(self.metrics, name="metrics"))
        object.__setattr__(
            self,
            "per_view_metrics",
            _mapping(self.per_view_metrics, name="per_view_metrics"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, name="metadata"))
        try:
            embedding = tuple(float(value) for value in self.embedding)
        except (TypeError, ValueError) as exc:
            raise InvalidEvaluationArtifactError("embedding must be numeric") from exc
        if any(not math.isfinite(value) for value in embedding):
            raise InvalidEvaluationArtifactError("embedding contains a non-finite value")
        object.__setattr__(self, "embedding", embedding)
        for name in ("compilation_seconds", "embedding_seconds", "metric_seconds"):
            try:
                seconds = float(getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise InvalidEvaluationArtifactError(f"{name} must be numeric") from exc
            if not math.isfinite(seconds) or seconds < 0.0:
                raise InvalidEvaluationArtifactError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, seconds)
        try:
            datetime.fromisoformat(str(self.created_at).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise InvalidEvaluationArtifactError("created_at must be ISO-8601") from exc

    @property
    def computation_seconds(self) -> float:
        return self.compilation_seconds + self.embedding_seconds + self.metric_seconds

    @property
    def compiled_ir(self) -> Mapping[str, Any]:
        """Compatibility alias describing the compiler artifact."""

        return self.compiler_artifact

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "key": self.key.to_dict(),
            "compiler_artifact": _json_value(self.compiler_artifact),
            "embedding": list(self.embedding),
            "metrics": _json_value(self.metrics),
            "per_view_metrics": _json_value(self.per_view_metrics),
            "metadata": _json_value(self.metadata),
            "compilation_seconds": self.compilation_seconds,
            "embedding_seconds": self.embedding_seconds,
            "metric_seconds": self.metric_seconds,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LegalIREvaluationArtifact":
        if payload.get("schema_version") != LEGAL_IR_EVALUATION_ARTIFACT_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("artifact schema version is stale")
        raw_key = payload.get("key")
        if not isinstance(raw_key, Mapping):
            raise InvalidEvaluationArtifactError("artifact key is missing")
        return cls(
            key=LegalIREvaluationCacheKey.from_dict(raw_key),
            compiler_artifact=payload.get("compiler_artifact", {}),
            embedding=tuple(payload.get("embedding", ()) or ()),
            metrics=payload.get("metrics", {}),
            per_view_metrics=payload.get("per_view_metrics", {}),
            metadata=payload.get("metadata", {}),
            compilation_seconds=payload.get("compilation_seconds", 0.0),
            embedding_seconds=payload.get("embedding_seconds", 0.0),
            metric_seconds=payload.get("metric_seconds", 0.0),
            created_at=str(payload.get("created_at") or ""),
            schema_version=str(payload.get("schema_version") or ""),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResultLineage:
    """Exact identity of a reusable aggregate autoencoder evaluation."""

    state_hash: str
    samples_hash: str
    evaluator_hash: str
    metric_schema: str

    def __post_init__(self) -> None:
        for name in ("state_hash", "samples_hash", "evaluator_hash", "metric_schema"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            if len(value) > 512 or any(character in value for character in "\r\n\0"):
                raise ValueError(f"{name} is not a valid evaluation-lineage component")
            object.__setattr__(self, name, value)

    @classmethod
    def for_samples(
        cls,
        samples: Sequence[Any],
        *,
        state_hash: str,
        evaluator_configuration: Any,
        metric_schema: str,
    ) -> "EvaluationResultLineage":
        """Build order-sensitive lineage without retaining source samples."""

        return cls(
            state_hash=state_hash,
            samples_hash=stable_digest(
                [sample_content_hash(sample) for sample in samples]
            ),
            evaluator_hash=configuration_digest(evaluator_configuration),
            metric_schema=metric_schema,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "state_hash": self.state_hash,
            "samples_hash": self.samples_hash,
            "evaluator_hash": self.evaluator_hash,
            "metric_schema": self.metric_schema,
        }


@dataclass(frozen=True, slots=True)
class ImmutableEvaluationResult:
    """Deeply immutable, checksum-protected evaluation result for cycle reuse."""

    lineage: EvaluationResultLineage
    payload: Mapping[str, Any]
    source_role: str
    source_cycle: int
    computation_seconds: float = 0.0
    schema_version: str = LEGAL_IR_EVALUATION_RESULT_SCHEMA_VERSION
    payload_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, EvaluationResultLineage):
            raise InvalidEvaluationArtifactError("result lineage has the wrong type")
        if self.schema_version != LEGAL_IR_EVALUATION_RESULT_SCHEMA_VERSION:
            raise InvalidEvaluationArtifactError("evaluation result schema version is stale")
        role = str(self.source_role or "").strip()
        if not role:
            raise InvalidEvaluationArtifactError("source_role must be non-empty")
        object.__setattr__(self, "source_role", role)
        cycle = int(self.source_cycle)
        if cycle < 0:
            raise InvalidEvaluationArtifactError("source_cycle must be non-negative")
        object.__setattr__(self, "source_cycle", cycle)
        seconds = float(self.computation_seconds)
        if not math.isfinite(seconds) or seconds < 0.0:
            raise InvalidEvaluationArtifactError(
                "computation_seconds must be finite and non-negative"
            )
        object.__setattr__(self, "computation_seconds", seconds)
        payload = _mapping(self.payload, name="payload")
        object.__setattr__(self, "payload", payload)
        digest = stable_digest(payload)
        requested_digest = str(self.payload_digest or "").strip()
        if requested_digest and requested_digest != digest:
            raise InvalidEvaluationArtifactError("evaluation result payload checksum mismatch")
        object.__setattr__(self, "payload_digest", digest)

    @classmethod
    def from_result(
        cls,
        lineage: EvaluationResultLineage,
        result: Any,
        *,
        source_role: str,
        source_cycle: int,
        computation_seconds: float = 0.0,
    ) -> "ImmutableEvaluationResult":
        if hasattr(result, "to_dict") and callable(result.to_dict):
            payload = result.to_dict()
        elif isinstance(result, Mapping):
            payload = result
        else:
            raise InvalidEvaluationArtifactError(
                "reusable evaluation result must be a mapping or provide to_dict()"
            )
        return cls(
            lineage=lineage,
            payload=payload,
            source_role=source_role,
            source_cycle=source_cycle,
            computation_seconds=computation_seconds,
        )

    def materialize(self, factory: Callable[..., _T]) -> _T:
        """Create a detached mutable value after rechecking immutable contents."""

        payload = _json_value(self.payload)
        if stable_digest(payload) != self.payload_digest:
            raise InvalidEvaluationArtifactError("evaluation result payload checksum mismatch")
        return factory(**payload)


class LegalIREvaluationResultCache:
    """Bounded in-process cache for exact after-to-before result reuse.

    This cache intentionally does not persist aggregate learned-state results.
    Their useful lifetime is the next cycle boundary, while compiler artifacts
    use :class:`LegalIREvaluationCache` for durable content-addressed reuse.
    """

    def __init__(self, *, max_entries: int = 16) -> None:
        if int(max_entries) <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = int(max_entries)
        self._entries: OrderedDict[str, ImmutableEvaluationResult] = OrderedDict()
        self._lock = threading.RLock()
        self._stats: Counter[str] = Counter()

    def put_after(
        self,
        lineage: EvaluationResultLineage,
        result: Any,
        *,
        role: str,
        cycle: int,
        computation_seconds: float = 0.0,
    ) -> ImmutableEvaluationResult:
        normalized_role = str(role or "").strip()
        if not normalized_role.startswith("after_"):
            raise ValueError("only after-evaluations may seed before-evaluation reuse")
        artifact = ImmutableEvaluationResult.from_result(
            lineage,
            result,
            source_role=normalized_role,
            source_cycle=cycle,
            computation_seconds=computation_seconds,
        )
        with self._lock:
            self._entries[lineage.digest] = artifact
            self._entries.move_to_end(lineage.digest)
            self._stats["writes"] += 1
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._stats["evictions"] += 1
        return artifact

    def get_before(
        self,
        lineage: EvaluationResultLineage,
        factory: Callable[..., _T],
        *,
        role: str,
        current_cycle: int,
    ) -> Optional[_T]:
        """Return an exact prior-cycle result, never same/future-cycle evidence."""

        normalized_role = str(role or "before_unspecified").strip()
        with self._lock:
            self._stats["lookups"] += 1
            artifact = self._entries.get(lineage.digest)
            if artifact is None:
                self._stats["misses"] += 1
                return None
            if artifact.lineage != lineage or artifact.source_cycle >= int(current_cycle):
                self._stats["lineage_rejections"] += 1
                self._stats["misses"] += 1
                return None
            self._entries.move_to_end(lineage.digest)
        try:
            result = artifact.materialize(factory)
        except (TypeError, ValueError, InvalidEvaluationArtifactError):
            with self._lock:
                self._stats["integrity_rejections"] += 1
                self._stats["misses"] += 1
                self._entries.pop(lineage.digest, None)
            return None
        with self._lock:
            self._stats["hits"] += 1
            self._stats[f"role_hits:{normalized_role}"] += 1
            self._stats["saved_wall_time_milliseconds"] += int(
                round(artifact.computation_seconds * 1000.0)
            )
        return result

    def summary(self) -> dict[str, Any]:
        with self._lock:
            lookups = int(self._stats.get("lookups", 0))
            hits = int(self._stats.get("hits", 0))
            return {
                "schema_version": LEGAL_IR_EVALUATION_RESULT_SCHEMA_VERSION,
                "entry_count": len(self._entries),
                "lookups": lookups,
                "hits": hits,
                "misses": int(self._stats.get("misses", 0)),
                "hit_rate": round(hits / lookups, 9) if lookups else 0.0,
                "writes": int(self._stats.get("writes", 0)),
                "evictions": int(self._stats.get("evictions", 0)),
                "lineage_rejections": int(
                    self._stats.get("lineage_rejections", 0)
                ),
                "integrity_rejections": int(
                    self._stats.get("integrity_rejections", 0)
                ),
                "saved_wall_time_seconds": round(
                    int(self._stats.get("saved_wall_time_milliseconds", 0)) / 1000.0,
                    3,
                ),
                "role_hits": {
                    key.split(":", 1)[1]: int(value)
                    for key, value in sorted(self._stats.items())
                    if key.startswith("role_hits:")
                },
            }


class LegalIREvaluationCache:
    """Thread- and process-safe persistent cache of typed evaluation artifacts."""

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        memory_entries: int = 256,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
        max_age_seconds: Optional[float] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.memory_entries = max(0, int(memory_entries))
        self.max_entry_bytes = max(1024, int(max_entry_bytes))
        self.max_age_seconds = (
            None if max_age_seconds is None else max(0.0, float(max_age_seconds))
        )
        self._lock = threading.RLock()
        self._memory: OrderedDict[str, LegalIREvaluationArtifact] = OrderedDict()
        self._flights: dict[str, Future[LegalIREvaluationArtifact]] = {}
        self._stats: Counter[str] = Counter()
        self._role_requests: Counter[str] = Counter()
        self._role_hits: Counter[str] = Counter()
        self._saved_wall_time_seconds = 0.0

    def entry_path(self, key: LegalIREvaluationCacheKey) -> Path:
        digest = key.digest
        return self.cache_dir / digest[:2] / f"{digest}.json"

    def _lock_path(self, key: LegalIREvaluationCacheKey) -> Path:
        return self.cache_dir / ".locks" / f"{key.digest}.lock"

    def _record_request(self, role: str) -> None:
        normalized = str(role or "unspecified").strip() or "unspecified"
        with self._lock:
            self._stats["lookups"] += 1
            self._role_requests[normalized] += 1

    def _record_hit(self, artifact: LegalIREvaluationArtifact, role: str, kind: str) -> None:
        normalized = str(role or "unspecified").strip() or "unspecified"
        with self._lock:
            self._stats["hits"] += 1
            self._stats[f"{kind}_hits"] += 1
            self._stats["avoided_recompilations"] += 1
            self._saved_wall_time_seconds += artifact.computation_seconds
            self._role_hits[normalized] += 1

    def _memory_get(self, digest: str) -> Optional[LegalIREvaluationArtifact]:
        with self._lock:
            artifact = self._memory.get(digest)
            if artifact is not None:
                if self._artifact_expired(artifact):
                    self._memory.pop(digest, None)
                    self._stats["stale_entries"] += 1
                    return None
                self._memory.move_to_end(digest)
            return artifact

    def _memory_put(self, artifact: LegalIREvaluationArtifact) -> None:
        if self.memory_entries <= 0:
            return
        digest = artifact.key.digest
        with self._lock:
            self._memory[digest] = artifact
            self._memory.move_to_end(digest)
            while len(self._memory) > self.memory_entries:
                self._memory.popitem(last=False)
                self._stats["memory_evictions"] += 1

    def get(
        self,
        key: LegalIREvaluationCacheKey,
        *,
        role: str = "unspecified",
    ) -> Optional[LegalIREvaluationArtifact]:
        """Return a validated artifact or ``None`` for missing/unsafe data."""

        if not isinstance(key, LegalIREvaluationCacheKey):
            raise TypeError("key must be LegalIREvaluationCacheKey")
        self._record_request(role)
        artifact = self._memory_get(key.digest)
        if artifact is not None:
            self._record_hit(artifact, role, "memory")
            return artifact
        artifact = self._read_disk(key)
        if artifact is None:
            with self._lock:
                self._stats["misses"] += 1
            return None
        self._memory_put(artifact)
        self._record_hit(artifact, role, "disk")
        return artifact

    def put(self, artifact: LegalIREvaluationArtifact) -> None:
        """Atomically persist a fully validated artifact."""

        if not isinstance(artifact, LegalIREvaluationArtifact):
            raise TypeError("artifact must be LegalIREvaluationArtifact")
        payload = artifact.to_dict()
        envelope = {
            "schema_version": LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION,
            "key_digest": artifact.key.digest,
            "key": artifact.key.to_dict(),
            "artifact": payload,
            "payload_sha256": stable_digest(payload),
        }
        encoded = (_canonical_json(envelope) + "\n").encode("utf-8")
        if len(encoded) > self.max_entry_bytes:
            raise InvalidEvaluationArtifactError("artifact exceeds maximum cache entry size")
        path = self.entry_path(artifact.key)
        temporary: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp"
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            with self._lock:
                self._stats["write_failures"] += 1
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        self._memory_put(artifact)
        with self._lock:
            self._stats["writes"] += 1

    def get_or_compute(
        self,
        key: LegalIREvaluationCacheKey,
        compute: Callable[[], LegalIREvaluationArtifact],
        *,
        role: str = "unspecified",
    ) -> LegalIREvaluationArtifact:
        """Get an artifact, coalescing all concurrent misses into one computation."""

        cached = self.get(key, role=role)
        if cached is not None:
            return cached
        digest = key.digest
        with self._lock:
            future = self._flights.get(digest)
            owner = future is None
            if owner:
                future = Future()
                self._flights[digest] = future
            else:
                self._stats["coalesced_waiters"] += 1
        assert future is not None
        if not owner:
            artifact = future.result()
            self._record_hit(artifact, role, "coalesced")
            return artifact

        try:
            with self._process_lock(key):
                # Another process may have populated the entry while this caller
                # waited for the advisory lock.  Avoid counting this as a new
                # user-visible lookup, but do account for the reuse.
                artifact = self._memory_get(digest) or self._read_disk(key)
                if artifact is not None:
                    self._memory_put(artifact)
                    self._record_hit(artifact, role, "process_coalesced")
                else:
                    started = time.monotonic()
                    artifact = compute()
                    elapsed = max(0.0, time.monotonic() - started)
                    if not isinstance(artifact, LegalIREvaluationArtifact):
                        raise InvalidEvaluationArtifactError(
                            "compute callback must return LegalIREvaluationArtifact"
                        )
                    if artifact.key != key:
                        raise InvalidEvaluationArtifactError(
                            "computed artifact key does not match requested key"
                        )
                    if artifact.computation_seconds <= 0.0:
                        artifact = replace(artifact, metric_seconds=elapsed)
                    self.put(artifact)
                    with self._lock:
                        self._stats["computations"] += 1
                        self._stats["computed_wall_time_milliseconds"] += int(
                            round(elapsed * 1000.0)
                        )
            future.set_result(artifact)
            return artifact
        except BaseException as exc:
            future.set_exception(exc)
            # Marking a Future exception as retrieved prevents a noisy warning
            # when there were no concurrent waiters.
            future.exception()
            raise
        finally:
            with self._lock:
                self._flights.pop(digest, None)

    def summary(self) -> dict[str, Any]:
        """Return source-free reuse and integrity accounting for daemon summaries."""

        with self._lock:
            stats = dict(self._stats)
            lookups = int(stats.get("lookups", 0))
            hits = int(stats.get("hits", 0))
            return {
                "schema_version": LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION,
                "lookups": lookups,
                "hits": hits,
                "misses": int(stats.get("misses", 0)),
                "hit_rate": round(hits / lookups, 9) if lookups else 0.0,
                "memory_hits": int(stats.get("memory_hits", 0)),
                "disk_hits": int(stats.get("disk_hits", 0)),
                "coalesced_hits": int(stats.get("coalesced_hits", 0)),
                "process_coalesced_hits": int(stats.get("process_coalesced_hits", 0)),
                "coalesced_waiters": int(stats.get("coalesced_waiters", 0)),
                "computations": int(stats.get("computations", 0)),
                "writes": int(stats.get("writes", 0)),
                "write_failures": int(stats.get("write_failures", 0)),
                "corrupt_entries": int(stats.get("corrupt_entries", 0)),
                "stale_entries": int(stats.get("stale_entries", 0)),
                "oversize_entries": int(stats.get("oversize_entries", 0)),
                "memory_evictions": int(stats.get("memory_evictions", 0)),
                "avoided_recompilations": int(stats.get("avoided_recompilations", 0)),
                "saved_wall_time_seconds": round(self._saved_wall_time_seconds, 9),
                "computed_wall_time_seconds": round(
                    int(stats.get("computed_wall_time_milliseconds", 0)) / 1000.0, 3
                ),
                "role_requests": dict(sorted(self._role_requests.items())),
                "role_hits": dict(sorted(self._role_hits.items())),
                "memory_entry_count": len(self._memory),
            }

    stats = summary

    def clear_memory(self) -> None:
        """Drop only the process-local LRU; persistent artifacts remain intact."""

        with self._lock:
            self._memory.clear()

    def _read_disk(
        self, key: LegalIREvaluationCacheKey
    ) -> Optional[LegalIREvaluationArtifact]:
        path = self.entry_path(key)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return None
        except OSError:
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if size <= 0 or size > self.max_entry_bytes:
            with self._lock:
                self._stats["oversize_entries"] += int(size > self.max_entry_bytes)
                self._stats["corrupt_entries"] += 1
            return None
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if not isinstance(envelope, Mapping):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if envelope.get("schema_version") != LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION:
            with self._lock:
                self._stats["stale_entries"] += 1
            return None
        raw_key = envelope.get("key")
        if not isinstance(raw_key, Mapping):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        try:
            stored_key = LegalIREvaluationCacheKey.from_dict(raw_key)
        except (TypeError, ValueError):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if stored_key != key or envelope.get("key_digest") != key.digest:
            with self._lock:
                self._stats["stale_entries"] += 1
            return None
        payload = envelope.get("artifact")
        if not isinstance(payload, Mapping):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        try:
            checksum = stable_digest(payload)
        except (TypeError, ValueError, InvalidEvaluationArtifactError):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if envelope.get("payload_sha256") != checksum:
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        try:
            artifact = LegalIREvaluationArtifact.from_dict(payload)
        except (TypeError, ValueError, InvalidEvaluationArtifactError):
            with self._lock:
                self._stats["corrupt_entries"] += 1
            return None
        if artifact.key != key:
            with self._lock:
                self._stats["stale_entries"] += 1
            return None
        if self._artifact_expired(artifact):
            with self._lock:
                self._stats["stale_entries"] += 1
            return None
        return artifact

    def _artifact_expired(self, artifact: LegalIREvaluationArtifact) -> bool:
        if self.max_age_seconds is None:
            return False
        try:
            created = datetime.fromisoformat(artifact.created_at.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc).timestamp() - created.timestamp()
        except (TypeError, ValueError):
            return True
        return age > self.max_age_seconds

    @contextmanager
    def _process_lock(self, key: LegalIREvaluationCacheKey) -> Iterator[None]:
        if fcntl is None:
            yield
            return
        path = self._lock_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# Concise aliases for callers that already carry a LegalIR namespace.
EvaluationCacheKey = LegalIREvaluationCacheKey
EvaluationArtifact = LegalIREvaluationArtifact
LegalIREvaluationArtifactCache = LegalIREvaluationCache


__all__ = [
    "DETERMINISTIC_COMPILER_STATE_HASH",
    "DEFAULT_MAX_ENTRY_BYTES",
    "EvaluationArtifact",
    "EvaluationCacheError",
    "EvaluationCacheKey",
    "EvaluationResultLineage",
    "ImmutableEvaluationResult",
    "InvalidEvaluationArtifactError",
    "LEGAL_IR_EVALUATION_ARTIFACT_SCHEMA_VERSION",
    "LEGAL_IR_EVALUATION_CACHE_SCHEMA_VERSION",
    "LEGAL_IR_EVALUATION_RESULT_SCHEMA_VERSION",
    "LegalIREvaluationArtifact",
    "LegalIREvaluationArtifactCache",
    "LegalIREvaluationCache",
    "LegalIREvaluationCacheKey",
    "LegalIREvaluationResultCache",
    "compiler_artifact_state_hash",
    "configuration_digest",
    "sample_content_hash",
    "stable_digest",
]
