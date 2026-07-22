"""Incremental, mutation-tracked identities for modal autoencoder state.

The operational revision in this module answers "did this object mutate?" while
the deterministic digest answers "does this object contain the same persisted
state?".  Keeping those concepts separate makes save/reload identities stable
without allowing an asynchronous result to validate itself after its source
object has moved to a later revision.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence


MODAL_AUTOENCODER_STATE_IDENTITY_SCHEMA_VERSION = (
    "modal-autoencoder-incremental-state-identity-v1"
)


class StaleStateResultError(RuntimeError):
    """Raised when work produced for an older state revision is consumed."""


def _canonical_value(value: Any) -> Any:
    """Return a deterministic, strict-JSON representation of ``value``."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("state identity cannot contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_canonical_value(item) for item in value]
    if is_dataclass(value):
        return _canonical_value(asdict(value))
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _canonical_value(to_dict())
    raise TypeError(f"unsupported state identity value: {type(value).__name__}")


def canonical_digest(value: Any) -> str:
    """Hash a value using the repository's canonical strict-JSON convention."""

    payload = json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _TrackedDict(dict):
    """A normal dict whose successful mutations invalidate one component."""

    def __init__(self, value: Mapping[Any, Any], callback: Callable[[], None]) -> None:
        self._callback = callback
        dict.__init__(
            self,
            ((key, _tracked_value(item, callback)) for key, item in value.items()),
        )

    def __deepcopy__(self, memo: Dict[int, Any]) -> Dict[Any, Any]:
        return {
            copy.deepcopy(key, memo): copy.deepcopy(value, memo)
            for key, value in self.items()
        }

    def __setitem__(self, key: Any, value: Any) -> None:
        dict.__setitem__(self, key, _tracked_value(value, self._callback))
        self._callback()

    def __delitem__(self, key: Any) -> None:
        dict.__delitem__(self, key)
        self._callback()

    def clear(self) -> None:
        if self:
            dict.clear(self)
            self._callback()

    def pop(self, key: Any, *default: Any) -> Any:
        existed = key in self
        result = dict.pop(self, key, *default)
        if existed:
            self._callback()
        return result

    def popitem(self) -> tuple[Any, Any]:
        result = dict.popitem(self)
        self._callback()
        return result

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return dict.__getitem__(self, key)
        value = _tracked_value(default, self._callback)
        dict.__setitem__(self, key, value)
        self._callback()
        return value

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        if not incoming:
            return
        for key, value in incoming.items():
            dict.__setitem__(self, key, _tracked_value(value, self._callback))
        self._callback()

    def __ior__(self, other: Mapping[Any, Any]) -> "_TrackedDict":
        self.update(other)
        return self


class _TrackedList(list):
    """A normal list whose successful mutations invalidate one component."""

    def __init__(self, value: Iterable[Any], callback: Callable[[], None]) -> None:
        self._callback = callback
        list.__init__(self, (_tracked_value(item, callback) for item in value))

    def __deepcopy__(self, memo: Dict[int, Any]) -> list[Any]:
        return [copy.deepcopy(value, memo) for value in self]

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice):
            wrapped = [_tracked_value(item, self._callback) for item in value]
        else:
            wrapped = _tracked_value(value, self._callback)
        list.__setitem__(self, index, wrapped)
        self._callback()

    def __delitem__(self, index: Any) -> None:
        list.__delitem__(self, index)
        self._callback()

    def append(self, value: Any) -> None:
        list.append(self, _tracked_value(value, self._callback))
        self._callback()

    def extend(self, values: Iterable[Any]) -> None:
        wrapped = [_tracked_value(value, self._callback) for value in values]
        if wrapped:
            list.extend(self, wrapped)
            self._callback()

    def insert(self, index: int, value: Any) -> None:
        list.insert(self, index, _tracked_value(value, self._callback))
        self._callback()

    def pop(self, index: int = -1) -> Any:
        result = list.pop(self, index)
        self._callback()
        return result

    def remove(self, value: Any) -> None:
        list.remove(self, value)
        self._callback()

    def clear(self) -> None:
        if self:
            list.clear(self)
            self._callback()

    def reverse(self) -> None:
        if len(self) > 1:
            list.reverse(self)
            self._callback()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        if len(self) > 1:
            list.sort(self, *args, **kwargs)
            self._callback()

    def __iadd__(self, values: Iterable[Any]) -> "_TrackedList":
        self.extend(values)
        return self

    def __imul__(self, count: int) -> "_TrackedList":
        before = list(self)
        list.__imul__(self, count)
        if list(self) != before:
            self._callback()
        return self


def _tracked_value(value: Any, callback: Callable[[], None]) -> Any:
    if isinstance(value, Mapping):
        return _TrackedDict(value, callback)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return _TrackedList(value, callback)
    return value


@dataclass(frozen=True, slots=True)
class StateIdentity:
    """A deterministic state identity plus its object-local revision."""

    digest: str
    revision: int
    schema_version: str
    state_schema_version: str
    metric_lineage_digest: str
    component_digests: Mapping[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_digests": dict(sorted(self.component_digests.items())),
            "digest": self.digest,
            "metric_lineage_digest": self.metric_lineage_digest,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "state_schema_version": self.state_schema_version,
        }


@dataclass(frozen=True, slots=True)
class StateRevisionToken:
    """A token used to reject results from an earlier object revision."""

    revision: int
    digest: str
    state_schema_version: str
    metric_lineage_digest: str


class IncrementalStateIdentity:
    """Track component mutations and recompute only dirty component digests."""

    def __init__(
        self,
        *,
        schema_version: str,
        metric_lineage: Any,
        components: Optional[Mapping[str, Any]] = None,
        component_normalizers: Optional[Mapping[str, Callable[[Any], Any]]] = None,
    ) -> None:
        if not str(schema_version or "").strip():
            raise ValueError("schema_version must be non-empty")
        self._state_schema_version = str(schema_version)
        self._metric_lineage = copy.deepcopy(metric_lineage)
        self._normalizers = dict(component_normalizers or {})
        self._components: Dict[str, Any] = {}
        self._component_digests: Dict[str, str] = {}
        self._dirty: set[str] = set()
        self._identity_cache: Dict[str, StateIdentity] = {}
        self._revision = 0
        self._component_recomputations = 0
        self._component_compute_counts: Dict[str, int] = {}
        self._identity_recomputations = 0
        self._lock = threading.RLock()
        for name, value in (components or {}).items():
            self._install(str(name), value, mutation=False)

    def _callback(self, name: str) -> Callable[[], None]:
        return lambda: self.dirty(name)

    def _install(self, name: str, value: Any, *, mutation: bool) -> Any:
        wrapped = _tracked_value(value, self._callback(name))
        with self._lock:
            self._components[name] = wrapped
            self._dirty.add(name)
            self._identity_cache.clear()
            if mutation:
                self._revision += 1
        return wrapped

    def track_component(self, name: str, value: Any, *, mutation: bool = True) -> Any:
        """Install and return a recursively tracked component value."""

        return self._install(str(name), value, mutation=mutation)

    def dirty(self, name: str, *, mutation: bool = True) -> None:
        with self._lock:
            if name not in self._components:
                raise KeyError(f"unknown state component: {name}")
            if mutation:
                self._revision += 1
            self._dirty.add(name)
            self._identity_cache.clear()

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def set_lineage(self, metric_lineage: Any) -> None:
        with self._lock:
            self._metric_lineage = copy.deepcopy(metric_lineage)
            self._identity_cache.clear()

    def _lineage(self, metric_lineage: Any) -> tuple[Any, str]:
        value = {
            "bound_metric_lineage": self._metric_lineage,
            "requested_metric_lineage": (
                self._metric_lineage if metric_lineage is None else metric_lineage
            ),
        }
        return value, canonical_digest(value)

    def component_digests(self) -> Dict[str, str]:
        with self._lock:
            dirty = tuple(sorted(self._dirty))
            for name in dirty:
                value = self._components[name]
                normalizer = self._normalizers.get(name)
                if normalizer is not None:
                    value = normalizer(value)
                self._component_digests[name] = canonical_digest(value)
                self._component_recomputations += 1
                self._component_compute_counts[name] = (
                    self._component_compute_counts.get(name, 0) + 1
                )
            self._dirty.difference_update(dirty)
            return dict(sorted(self._component_digests.items()))

    def identity(self, *, metric_lineage: Any = None) -> StateIdentity:
        lineage, lineage_digest = self._lineage(metric_lineage)
        with self._lock:
            cached = self._identity_cache.get(lineage_digest)
            if cached is not None and not self._dirty:
                return cached
            component_digests = self.component_digests()
            envelope = {
                "component_digests": component_digests,
                "identity_schema_version": MODAL_AUTOENCODER_STATE_IDENTITY_SCHEMA_VERSION,
                "metric_lineage": _canonical_value(lineage),
                "state_schema_version": self._state_schema_version,
            }
            identity = StateIdentity(
                digest=canonical_digest(envelope),
                revision=self._revision,
                schema_version=MODAL_AUTOENCODER_STATE_IDENTITY_SCHEMA_VERSION,
                state_schema_version=self._state_schema_version,
                metric_lineage_digest=lineage_digest,
                component_digests=component_digests,
            )
            self._identity_cache[lineage_digest] = identity
            self._identity_recomputations += 1
            return identity

    def digest(self, *, metric_lineage: Any = None) -> str:
        return self.identity(metric_lineage=metric_lineage).digest

    def token(self, *, metric_lineage: Any = None) -> StateRevisionToken:
        identity = self.identity(metric_lineage=metric_lineage)
        return StateRevisionToken(
            revision=identity.revision,
            digest=identity.digest,
            state_schema_version=identity.state_schema_version,
            metric_lineage_digest=identity.metric_lineage_digest,
        )

    def matches(self, token: StateRevisionToken, *, metric_lineage: Any = None) -> bool:
        if metric_lineage is None:
            with self._lock:
                if token.revision != self._revision or self._dirty:
                    return False
                cached = self._identity_cache.get(token.metric_lineage_digest)
                return bool(cached is not None and cached.digest == token.digest)
        current = self.token(metric_lineage=metric_lineage)
        return current == token

    def assert_current(
        self, token: StateRevisionToken, *, metric_lineage: Any = None
    ) -> None:
        if not self.matches(token, metric_lineage=metric_lineage):
            current_revision = self.revision
            raise StaleStateResultError(
                "state result is stale: "
                f"current revision {current_revision}, "
                f"received revision {token.revision} ({token.digest})"
            )

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "component_count": len(self._components),
                "component_digest_compute_count": self._component_recomputations,
                "component_digest_compute_counts": dict(
                    sorted(self._component_compute_counts.items())
                ),
                "component_recomputations": self._component_recomputations,
                "dirty_component_count": len(self._dirty),
                "identity_recomputations": self._identity_recomputations,
                "revision": self._revision,
            }


__all__ = [
    "IncrementalStateIdentity",
    "MODAL_AUTOENCODER_STATE_IDENTITY_SCHEMA_VERSION",
    "StaleStateResultError",
    "StateIdentity",
    "StateRevisionToken",
    "canonical_digest",
]
