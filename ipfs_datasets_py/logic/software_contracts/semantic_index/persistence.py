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
import stat
import tempfile
import threading
from typing import Any, Callable, Final, Iterator, Mapping, Protocol, runtime_checkable

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
TRANSITION_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-index-root-transition@1"


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

    def __init__(
        self,
        root: Path | str,
        *,
        max_object_bytes: int = 16 * 1024 * 1024,
        interruption_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.cas = ImmutableCAS(self.root / "cas", max_object_bytes=max_object_bytes)
        self.roots_root = self.root / "roots"
        self.roots_root.mkdir(parents=True, exist_ok=True)
        self.transitions_root = self.root / "transitions"
        self.transitions_root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._lock_path = self.root / ".roots.lock"
        self._interruption_hook = interruption_hook

    def _put_record(self, value: Mapping[str, Any]) -> str:
        self._interrupt("before_object_write")
        cid = self.cas.put(dict(value))
        self._interrupt("after_object_write")
        return cid

    def _interrupt(self, point: str) -> None:
        """Invoke the optional crash-injection hook after durable boundaries.

        The hook is intentionally supplied by callers/tests rather than being
        controlled by environment state.  Raising from it models abrupt
        termination while retaining every preceding durable write.
        """
        if self._interruption_hook is not None:
            self._interruption_hook(point)

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

    def _transition_path(self, repository_id: str) -> Path:
        repository_id = _repository_id(repository_id)
        return self.transitions_root / f"{cid_for_structured({'repository_id': repository_id})}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            if fcntl is None:
                raise SemanticIndexPersistenceError(
                    "process-safe root CAS requires an interprocess file lock"
                )
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+b") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
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
        # A root is authoritative only if its referenced immutable state
        # verifies and is for precisely the repository named by the root.
        if self.load_state(state_cid).repository_id != repository_id:
            raise SemanticIndexPersistenceError("semantic-index root state belongs to another repository")
        return state_cid

    def _replace_root(self, path: Path, payload: bytes) -> None:
        temporary: Path | None = None
        try:
            prefix = ".transition-" if path.parent == self.transitions_root else ".root-"
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=prefix, delete=False) as stream:
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

    def _write_transition(self, repository_id: str, expected_old_cid: str | None, new_cid: str) -> Path:
        record = {
            "schema": TRANSITION_SCHEMA,
            "repository_id": repository_id,
            "expected_old_cid": expected_old_cid,
            "new_cid": new_cid,
        }
        path = self._transition_path(repository_id)
        self._replace_root(path, canonical_dag_json_bytes(record))
        return path

    def _read_transition(self, path: Path) -> tuple[str, str | None, str]:
        try:
            payload = path.read_bytes()
            record = _decode_record(cid_for_structured(json.loads(payload.decode("utf-8"))), payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, SemanticIndexPersistenceError) as exc:
            raise SemanticIndexPersistenceError("semantic-index transition is invalid") from exc
        if set(record) != {"schema", "repository_id", "expected_old_cid", "new_cid"} or record.get("schema") != TRANSITION_SCHEMA:
            raise SemanticIndexPersistenceError("semantic-index transition membership is invalid")
        try:
            repository_id = _repository_id(record.get("repository_id"))
            expected = record.get("expected_old_cid")
            if expected is not None:
                expected = _structured_cid(expected, "transition expected_old_cid")
            new_cid = _structured_cid(record.get("new_cid"), "transition new_cid")
        except (TypeError, ValueError, SemanticIndexPersistenceError) as exc:
            raise SemanticIndexPersistenceError("semantic-index transition is invalid") from exc
        if path != self._transition_path(repository_id):
            raise SemanticIndexPersistenceError("semantic-index transition filename is invalid")
        if self.load_state(new_cid).repository_id != repository_id:
            raise SemanticIndexPersistenceError("semantic-index transition state belongs to another repository")
        return repository_id, expected, new_cid

    def _recover_unlocked(
        self, repository_id: str | None = None, *, cleanup_temps: bool = False
    ) -> tuple[Path, ...]:
        """Finish journal reconciliation without ever manufacturing a root."""
        # Validate every authoritative root before deleting anything during a
        # whole-store recovery.  A repository-scoped operation intentionally
        # remains scoped to that repository, as it is used by root CAS.
        if repository_id is not None:
            repository_id = _repository_id(repository_id)
            self._read_root_unlocked(repository_id)
        else:
            for path in sorted(self.roots_root.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    root_repository = _repository_id(payload.get("repository_id"))
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise SemanticIndexPersistenceError("cannot safely recover an invalid root") from exc
                if path != self._root_path(root_repository):
                    raise SemanticIndexPersistenceError("semantic-index root filename is invalid")
                self._read_root_unlocked(root_repository)

        transitions = sorted(self.transitions_root.glob("*.json"))
        removed: list[Path] = []
        affected_directories: set[Path] = set()
        for path in transitions:
            transition_repository, expected, new_cid = self._read_transition(path)
            current = self._read_root_unlocked(transition_repository)
            if current not in (expected, new_cid):
                raise SemanticIndexPersistenceError("semantic-index transition does not match current root")
            # The replacement is atomic: either the old root or the new root
            # was fully visible at the crash boundary.  Never replay a journal
            # entry, because doing so could turn a non-visible write into one.
            path.unlink()
            removed.append(path)
            affected_directories.add(path.parent)
        if cleanup_temps:
            # ``.root-`` was the original replacement prefix.  ISI-037 added
            # the narrower ``.transition-`` prefix, but old installations can
            # have either form in either bounded publication directory.
            for directory in (self.roots_root, self.transitions_root):
                for prefix in (".root-*", ".transition-*"):
                    for path in sorted(directory.glob(prefix)):
                        try:
                            mode = path.stat(follow_symlinks=False).st_mode
                        except FileNotFoundError:
                            continue
                        except OSError as exc:
                            raise SemanticIndexPersistenceError(
                                "cannot inspect semantic-index temporary"
                            ) from exc
                        # ``Path.is_file`` follows symlinks; never let a
                        # symlink (including a dangling one) qualify for
                        # cleanup merely because its name has our prefix.
                        if stat.S_ISREG(mode):
                            path.unlink()
                            removed.append(path)
                            affected_directories.add(directory)
        for directory in sorted(affected_directories):
            self._fsync_directory(directory)
        return tuple(removed)

    def current_root(self, repository_id: str) -> str | None:
        with self._locked():
            repository_id = _repository_id(repository_id)
            self._recover_unlocked(repository_id)
            return self._read_root_unlocked(repository_id)

    get_current_root = current_root

    def compare_and_swap_root(self, repository_id: str, expected_old_cid: str | None, new_cid: str) -> str:
        repository_id = _repository_id(repository_id)
        if expected_old_cid is not None:
            expected_old_cid = _structured_cid(expected_old_cid, "expected_old_cid")
        new_cid = _structured_cid(new_cid, "new_cid")
        if self.load_state(new_cid).repository_id != repository_id:
            raise SemanticIndexPersistenceError("new root state belongs to another repository")
        with self._locked():
            self._recover_unlocked(repository_id)
            # Revalidate under the publication lock: a damaged immutable block
            # must not become root authority after the initial preflight.
            if self.load_state(new_cid).repository_id != repository_id:
                raise SemanticIndexPersistenceError("new root state belongs to another repository")
            current = self._read_root_unlocked(repository_id)
            # Repeated identical publication is intentionally idempotent.
            if current == new_cid:
                return new_cid
            if current != expected_old_cid:
                raise RootConflictError(
                    f"root conflict for {repository_id!r}: expected {expected_old_cid!r}, found {current!r}"
                )
            self._interrupt("before_transition_write")
            transition = self._write_transition(repository_id, expected_old_cid, new_cid)
            self._interrupt("after_transition_write")
            payload = canonical_dag_json_bytes({"schema": ROOT_SCHEMA, "repository_id": repository_id, "state_cid": new_cid})
            self._interrupt("before_root_replace")
            self._replace_root(self._root_path(repository_id), payload)
            self._interrupt("after_root_replace")
            transition.unlink()
            self._fsync_directory(self.transitions_root)
            return new_cid

    cas_root = compare_and_swap_root

    def recover(self, repository_id: str | None = None) -> tuple[Path, ...]:
        """Validate roots first, then remove only recognized abandoned root temps."""
        with self._locked():
            return self._recover_unlocked(repository_id, cleanup_temps=True)


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
        if self.load_state(state_cid).repository_id != repository_id:
            raise SemanticIndexPersistenceError("backend root state belongs to another repository")
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
        if self.load_state(new_cid).repository_id != repository_id:
            raise SemanticIndexPersistenceError("new backend root state belongs to another repository")
        # Root reads are required for CAS too.  Besides detecting a stale
        # expected value early, this ensures an already-installed foreign
        # state is never silently accepted by a backend CAS implementation.
        current = self.current_root(repository_id)
        if current == new_cid:
            return new_cid
        if current != expected_old_cid:
            raise RootConflictError(
                f"root conflict for {repository_id!r}: expected {expected_old_cid!r}, found {current!r}"
            )
        try:
            result = method(repository_id, expected_old_cid, new_cid)
        except RootConflictError:
            raise
        if result is False:
            raise RootConflictError("backend rejected root compare-and-swap")
        actual = new_cid if result in (None, True) else self._returned_cid(result)
        if actual != new_cid:
            raise SemanticIndexPersistenceError("backend root CAS returned a different CID")
        if self.current_root(repository_id) != new_cid:
            raise SemanticIndexPersistenceError("backend root CAS did not publish the requested root")
        return new_cid

    cas_root = compare_and_swap_root
