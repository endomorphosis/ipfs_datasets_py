"""Verified persistence for incremental semantic-index records.

The local implementation deliberately composes :class:`ImmutableCAS` rather
than reimplementing content publication.  Only the mutable current-root ref is
kept outside the CAS; it is a small canonical record updated under a process
lock with expected-old compare-and-swap semantics.

``IpfsKitSemanticIndexStore`` has no import-time dependency on ipfs_kit_py.
It accepts an already-created, capability-bearing backend and verifies every
block returned by it against the software-contract CID profile.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Final, Iterator, Mapping, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.cache import (
    CacheIntegrityError,
    ImmutableCAS,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    InvalidationPlan,
    RepositoryState,
    RepositoryStateDelta,
    SEMANTIC_INDEX_SCHEMA,
    SemanticIndexModelError,
)

try:  # pragma: no cover - fcntl is unavailable on a few supported platforms.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


PERSISTENCE_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-index-persistence@1"
ROOT_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-index-root@1"


class SemanticIndexPersistenceError(RuntimeError):
    """Base class for semantic-index persistence failures."""


class RootConflictError(SemanticIndexPersistenceError):
    """A root compare-and-swap expected a different current state."""


class BackendCapabilityError(SemanticIndexPersistenceError):
    """An injected optional backend lacks a required explicit capability."""


@runtime_checkable
class SemanticIndexStore(Protocol):
    """Durable interface for state, delta, plan, and current-root records."""

    def store_state(self, state: RepositoryState) -> str: ...
    def load_state(self, state_cid: str) -> RepositoryState: ...
    def store_delta(self, delta: RepositoryStateDelta) -> str: ...
    def load_delta(self, delta_cid: str) -> RepositoryStateDelta: ...
    def store_plan(self, plan: InvalidationPlan) -> str: ...
    def load_plan(self, plan_cid: str) -> InvalidationPlan: ...
    def current_root(self, repository_id: str) -> str | None: ...
    def compare_and_swap_root(
        self, repository_id: str, expected_old_cid: str | None, new_cid: str
    ) -> str: ...


def _repository_id(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("repository_id must be a nonempty trimmed string")
    return value


def _structured_cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value, codecs={STRUCTURED_CODEC})
    except (ContentIdentityError, TypeError, ValueError) as exc:
        raise SemanticIndexPersistenceError(f"{name} must be a structured CID") from exc


def _decode_record(cid: str, payload: bytes) -> Mapping[str, Any]:
    """Decode canonical DAG-JSON and recompute its authoritative CID."""
    try:
        value = json.loads(payload.decode("utf-8"))
        if payload != canonical_dag_json_bytes(value):
            raise SemanticIndexPersistenceError("stored structured object is not canonical")
        decode_and_recompute_structured(cid, value)
    except SemanticIndexPersistenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ContentIdentityError, TypeError, ValueError) as exc:
        raise SemanticIndexPersistenceError("stored structured object is invalid") from exc
    if not isinstance(value, Mapping):
        raise SemanticIndexPersistenceError("stored structured object must be an object")
    return value


class _RecordStore(ABC):
    """Common verified typed-record operations for local and injected stores."""

    @abstractmethod
    def _put_record(self, value: Mapping[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def _get_record(self, cid: str) -> Mapping[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _store(value: Any, expected_type: type[Any], cid_attribute: str, put: Any) -> str:
        if not isinstance(value, expected_type):
            raise TypeError(f"value must be {expected_type.__name__}")
        # The model CID is deliberately over this payload, not its convenient
        # ``to_dict`` form which repeats the claimed CID for interchange.
        cid = put(value.identity_payload())
        if cid != getattr(value, cid_attribute):
            raise SemanticIndexPersistenceError("stored object CID does not match model identity")
        return cid

    @staticmethod
    def _load(cid: str, parser: Any, cid_attribute: str, get: Any, *, state: bool = False) -> Any:
        cid = _structured_cid(cid, "cid")
        try:
            raw = dict(get(cid))
            if state:
                # RepositoryState's interchange envelope has the outer
                # semantic-index schema; its CID payload has STATE_SCHEMA.
                raw["schema"] = SEMANTIC_INDEX_SCHEMA
                raw.pop("semantic_index_schema", None)
                raw["state_cid"] = cid
            else:
                raw[f"{cid_attribute.removesuffix('_cid')}_cid"] = cid
            value = parser(raw)
        except (SemanticIndexModelError, CacheIntegrityError, KeyError, TypeError, ValueError) as exc:
            raise SemanticIndexPersistenceError("stored semantic-index record is invalid") from exc
        if getattr(value, cid_attribute) != cid:
            raise SemanticIndexPersistenceError("stored semantic-index record CID mismatch")
        return value

    def store_state(self, state: RepositoryState) -> str:
        return self._store(state, RepositoryState, "state_cid", self._put_record)

    put_state = store_state

    def load_state(self, state_cid: str) -> RepositoryState:
        return self._load(state_cid, RepositoryState.from_dict, "state_cid", self._get_record, state=True)

    get_state = load_state

    def store_delta(self, delta: RepositoryStateDelta) -> str:
        return self._store(delta, RepositoryStateDelta, "delta_cid", self._put_record)

    put_delta = store_delta

    def load_delta(self, delta_cid: str) -> RepositoryStateDelta:
        return self._load(delta_cid, RepositoryStateDelta.from_dict, "delta_cid", self._get_record)

    get_delta = load_delta

    def store_plan(self, plan: InvalidationPlan) -> str:
        return self._store(plan, InvalidationPlan, "plan_cid", self._put_record)

    put_plan = store_plan

    def load_plan(self, plan_cid: str) -> InvalidationPlan:
        return self._load(plan_cid, InvalidationPlan.from_dict, "plan_cid", self._get_record)

    get_plan = load_plan


class LocalSemanticIndexStore(_RecordStore):
    """Hermetic filesystem persistence with a verified root CAS ref."""

    def __init__(self, root: Path | str, *, max_object_bytes: int = 16 * 1024 * 1024) -> None:
        self.root = Path(root)
        self.cas = ImmutableCAS(self.root / "cas", max_object_bytes=max_object_bytes)
        self.roots_root = self.root / "roots"
        self.roots_root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._lock_path = self.root / ".roots.lock"

    def _put_record(self, value: Mapping[str, Any]) -> str:
        return self.cas.put(dict(value))

    def _get_record(self, cid: str) -> Mapping[str, Any]:
        try:
            value = self.cas.get(cid)
        except (CacheIntegrityError, FileNotFoundError, ValueError) as exc:
            raise SemanticIndexPersistenceError("semantic-index object is unavailable or corrupt") from exc
        if not isinstance(value, Mapping):
            raise SemanticIndexPersistenceError("semantic-index object must be an object")
        return value

    def _root_path(self, repository_id: str) -> Path:
        repository_id = _repository_id(repository_id)
        # The filename is an identity of the repository label, never the label itself.
        return self.roots_root / f"{cid_for_structured({'repository_id': repository_id})}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+b") as stream:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read_root_unlocked(self, repository_id: str) -> str | None:
        path = self._root_path(repository_id)
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SemanticIndexPersistenceError("cannot read semantic-index root") from exc
        try:
            record = _decode_record(cid_for_structured(json.loads(payload.decode("utf-8"))), payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, SemanticIndexPersistenceError) as exc:
            raise SemanticIndexPersistenceError("semantic-index root is invalid") from exc
        if set(record) != {"schema", "repository_id", "state_cid"} or record.get("schema") != ROOT_SCHEMA or record.get("repository_id") != repository_id:
            raise SemanticIndexPersistenceError("semantic-index root membership is invalid")
        state_cid = _structured_cid(record.get("state_cid"), "root state_cid")
        # A root is authoritative only if its referenced immutable state verifies.
        self.load_state(state_cid)
        return state_cid

    def _replace_root(self, path: Path, payload: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".root-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            self._fsync_directory(path.parent)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def current_root(self, repository_id: str) -> str | None:
        with self._locked():
            return self._read_root_unlocked(_repository_id(repository_id))

    get_current_root = current_root

    def compare_and_swap_root(self, repository_id: str, expected_old_cid: str | None, new_cid: str) -> str:
        repository_id = _repository_id(repository_id)
        if expected_old_cid is not None:
            expected_old_cid = _structured_cid(expected_old_cid, "expected_old_cid")
        new_cid = _structured_cid(new_cid, "new_cid")
        self.load_state(new_cid)
        with self._locked():
            current = self._read_root_unlocked(repository_id)
            # Repeated identical publication is intentionally idempotent.
            if current == new_cid:
                return new_cid
            if current != expected_old_cid:
                raise RootConflictError(
                    f"root conflict for {repository_id!r}: expected {expected_old_cid!r}, found {current!r}"
                )
            payload = canonical_dag_json_bytes({"schema": ROOT_SCHEMA, "repository_id": repository_id, "state_cid": new_cid})
            self._replace_root(self._root_path(repository_id), payload)
            return new_cid

    cas_root = compare_and_swap_root

    def recover(self, repository_id: str | None = None) -> tuple[Path, ...]:
        """Validate roots first, then remove only recognized abandoned root temps."""
        with self._locked():
            if repository_id is not None:
                self._read_root_unlocked(_repository_id(repository_id))
            else:
                for path in sorted(self.roots_root.glob("*.json")):
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        self._read_root_unlocked(_repository_id(payload.get("repository_id")))
                    except (OSError, TypeError, ValueError, SemanticIndexPersistenceError) as exc:
                        raise SemanticIndexPersistenceError("cannot safely recover an invalid root") from exc
            removed: list[Path] = []
            for path in sorted(self.roots_root.glob(".root-*")):
                if path.is_file():
                    path.unlink()
                    removed.append(path)
            self._fsync_directory(self.roots_root)
            return tuple(removed)


class IpfsKitSemanticIndexStore(_RecordStore):
    """Optional injected DAG-JSON block backend; no daemon or import required."""

    def __init__(self, backend: Any) -> None:
        if backend is None:
            raise BackendCapabilityError("an injected backend is required")
        self.backend = backend

    @staticmethod
    def _returned_cid(value: Any) -> str:
        if isinstance(value, Mapping):
            value = value.get("cid", value.get("Cid", value.get("Hash")))
        return _structured_cid(value, "backend CID")

    def _put_record(self, value: Mapping[str, Any]) -> str:
        payload = canonical_dag_json_bytes(value)
        expected = cid_for_structured(value)
        method = next((getattr(self.backend, name, None) for name in ("put_bytes", "add_bytes", "add", "put") if callable(getattr(self.backend, name, None))), None)
        if method is None:
            raise BackendCapabilityError("backend does not provide a block put capability")
        actual = self._returned_cid(method(payload))
        if actual != expected:
            raise SemanticIndexPersistenceError("backend CID does not match software-contract identity")
        return actual

    def _get_record(self, cid: str) -> Mapping[str, Any]:
        cid = _structured_cid(cid, "cid")
        method = next((getattr(self.backend, name, None) for name in ("get_bytes", "cat", "get") if callable(getattr(self.backend, name, None))), None)
        if method is None:
            raise BackendCapabilityError("backend does not provide a block get capability")
        payload = method(cid)
        if isinstance(payload, Mapping):
            payload = payload.get("data", payload.get("Data"))
        if type(payload) is not bytes:
            raise SemanticIndexPersistenceError("backend did not return exact bytes")
        return _decode_record(cid, payload)

    def current_root(self, repository_id: str) -> str | None:
        method = getattr(self.backend, "get_root", None)
        if not callable(method):
            raise BackendCapabilityError("backend does not provide explicit root reads")
        value = method(_repository_id(repository_id))
        if value is None:
            return None
        state_cid = _structured_cid(value, "backend root CID")
        self.load_state(state_cid)
        return state_cid

    get_current_root = current_root

    def compare_and_swap_root(self, repository_id: str, expected_old_cid: str | None, new_cid: str) -> str:
        method = getattr(self.backend, "compare_and_swap_root", None)
        if not callable(method):
            raise BackendCapabilityError("backend does not provide explicit root compare-and-swap")
        repository_id = _repository_id(repository_id)
        if expected_old_cid is not None:
            expected_old_cid = _structured_cid(expected_old_cid, "expected_old_cid")
        new_cid = _structured_cid(new_cid, "new_cid")
        self.load_state(new_cid)
        try:
            result = method(repository_id, expected_old_cid, new_cid)
        except RootConflictError:
            raise
        if result is False:
            raise RootConflictError("backend rejected root compare-and-swap")
        actual = new_cid if result in (None, True) else self._returned_cid(result)
        if actual != new_cid:
            raise SemanticIndexPersistenceError("backend root CAS returned a different CID")
        return new_cid

    cas_root = compare_and_swap_root
