"""Immutable content-addressed cache for software-contract analysis.

Reusable shard identities bind the source and its dependency closure to every
analysis input that can change the result.  They intentionally do not bind the
global repository-tree CID.  Aggregate snapshot receipts provide that separate
binding without destroying cross-snapshot shard reuse.

The immutable store is fail closed:

* structured objects and source blobs use the CID profile from ``content``;
* publication is write/fsync/link (never replacement of an existing object);
* every read parses, validates, canonicalizes, and recomputes the claimed CID;
* replaceable index records are conveniences and carry no independent trust.

This module is the cache authority for DSCON-G100.  Older proof caches may be
adapted to this interface, but their permissive keying and serialization rules
are not authoritative for contract-analysis results.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Iterator, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError,
    SOURCE_CODEC,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_source,
    decode_and_recompute_structured,
    validate_cid,
)

try:  # pragma: no cover - exercised on POSIX, optional elsewhere
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


GOAL_ID: Final[str] = "DSCON-G100"
PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contract-analysis-cache-profile.v1"
)
KEY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contract-analysis-cache-key.v1"
)
RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contract-analysis-cache-receipt.v1"
)
SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contract-analysis-snapshot-receipt.v1"
)
INDEX_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contract-analysis-cache-index.v1"
)

OUTCOME_PROVED: Final[str] = "PROVED_WITHIN_MODEL"
OUTCOME_VIOLATED: Final[str] = "VIOLATED_WITH_COUNTEREXAMPLE"
OUTCOME_NEGATIVE: Final[str] = "NEGATIVE"
OUTCOME_UNKNOWN: Final[str] = "UNKNOWN"
OUTCOME_UNSUPPORTED: Final[str] = "UNSUPPORTED"
OUTCOME_INCOMPLETE: Final[str] = "INCOMPLETE_SCAN"
OUTCOME_STALE: Final[str] = "STALE"
OUTCOME_ERROR: Final[str] = "ERROR"
ALL_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        OUTCOME_PROVED,
        OUTCOME_VIOLATED,
        OUTCOME_NEGATIVE,
        OUTCOME_UNKNOWN,
        OUTCOME_UNSUPPORTED,
        OUTCOME_INCOMPLETE,
        OUTCOME_STALE,
        OUTCOME_ERROR,
    }
)
LEASED_OUTCOMES: Final[frozenset[str]] = ALL_OUTCOMES - {OUTCOME_PROVED}

DEFAULT_MAX_LEASE_SECONDS: Final[int] = 60 * 60
DEFAULT_MAX_OBJECT_BYTES: Final[int] = 16 * 1024 * 1024

_KEY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "source_cid",
        "dependency_cids",
        "analyzer_cid",
        "configuration_cid",
        "semantics_cid",
        "policy_cid",
        "solver_cid",
        "toolchain_cid",
        "result_schema",
    }
)
_RECEIPT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "key",
        "key_cid",
        "result_cid",
        "result_schema",
        "outcome",
        "created_at",
        "lease_expires_at",
    }
)
_SNAPSHOT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "repository_tree_cid",
        "shard_receipt_cids",
        "created_at",
    }
)


class AnalysisCacheError(RuntimeError):
    """Base class for cache failures."""


class CacheIntegrityError(AnalysisCacheError, ValueError):
    """Stored content, identity, membership, or schema is invalid."""


class CacheKeyError(AnalysisCacheError, ValueError):
    """A reusable shard key is incomplete or unsafe."""


class CacheLeaseError(AnalysisCacheError, ValueError):
    """A non-completion result has an absent or unbounded lease."""


def _nonempty(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise CacheKeyError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CacheKeyError(f"{name} must not have surrounding whitespace")
    return value


def _source_cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value, codecs={SOURCE_CODEC})
    except (ContentIdentityError, TypeError, ValueError) as exc:
        raise CacheKeyError(f"{name} must be a raw source CID") from exc


def _structured_cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value, codecs={STRUCTURED_CODEC})
    except (ContentIdentityError, TypeError, ValueError) as exc:
        raise CacheKeyError(f"{name} must be a dag-json structured CID") from exc


def _closed_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    name: str,
) -> None:
    if any(type(field) is not str for field in value):
        raise CacheIntegrityError(f"{name} fields must be strings")
    fields = set(value)
    missing = sorted(expected - fields)
    extra = sorted(fields - expected)
    if missing or extra:
        raise CacheIntegrityError(
            f"{name} fields are closed (missing={missing}, extra={extra})"
        )


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CacheIntegrityError(f"{name} must be an integer >= {minimum}")
    return value


def cache_profile_descriptor() -> dict[str, Any]:
    """Return the stable machine-readable DSCON-G100 cache profile."""

    return {
        "schema": PROFILE_SCHEMA,
        "goal_id": GOAL_ID,
        "key_schema": KEY_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "index_schema": INDEX_SCHEMA,
        "global_tree_in_reusable_key": False,
        "global_tree_in_snapshot_receipt": True,
        "read_integrity": "decode-and-recompute",
        "immutable_publication": "fsync-then-link-no-replace",
        "completion_outcome": OUTCOME_PROVED,
        "leased_outcomes": sorted(LEASED_OUTCOMES),
    }


@dataclass(frozen=True)
class AnalysisCacheKey:
    """Identity of one reusable analysis shard.

    ``dependency_cids`` is the complete transitive source dependency closure,
    sorted and deduplicated.  The repository-tree CID is deliberately absent.
    """

    source_cid: str
    dependency_cids: tuple[str, ...]
    analyzer_cid: str
    configuration_cid: str
    semantics_cid: str
    policy_cid: str
    solver_cid: str
    toolchain_cid: str
    result_schema: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_cid",
            _source_cid(self.source_cid, "source_cid"),
        )
        if isinstance(self.dependency_cids, (str, bytes, bytearray)):
            raise CacheKeyError("dependency_cids must be a sequence of CIDs")
        dependencies = tuple(
            _source_cid(item, f"dependency_cids[{index}]")
            for index, item in enumerate(self.dependency_cids)
        )
        if self.source_cid in dependencies:
            raise CacheKeyError("dependency_cids must not repeat source_cid")
        if len(set(dependencies)) != len(dependencies):
            raise CacheKeyError("dependency_cids must be unique")
        object.__setattr__(self, "dependency_cids", tuple(sorted(dependencies)))
        for name in (
            "analyzer_cid",
            "configuration_cid",
            "semantics_cid",
            "policy_cid",
            "solver_cid",
            "toolchain_cid",
        ):
            object.__setattr__(self, name, _structured_cid(getattr(self, name), name))
        object.__setattr__(
            self, "result_schema", _nonempty(self.result_schema, "result_schema")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": KEY_SCHEMA,
            "source_cid": self.source_cid,
            "dependency_cids": list(self.dependency_cids),
            "analyzer_cid": self.analyzer_cid,
            "configuration_cid": self.configuration_cid,
            "semantics_cid": self.semantics_cid,
            "policy_cid": self.policy_cid,
            "solver_cid": self.solver_cid,
            "toolchain_cid": self.toolchain_cid,
            "result_schema": self.result_schema,
        }

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def key_cid(self) -> str:
        return self.cid

    @property
    def source_closure(self) -> tuple[str, ...]:
        return (self.source_cid, *self.dependency_cids)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisCacheKey":
        if not isinstance(value, Mapping):
            raise CacheIntegrityError("cache key must be an object")
        _closed_fields(value, _KEY_FIELDS, "cache key")
        if value.get("schema") != KEY_SCHEMA:
            raise CacheIntegrityError("unsupported cache-key schema")
        dependencies = value.get("dependency_cids")
        if not isinstance(dependencies, list):
            raise CacheIntegrityError("dependency_cids must be an array")
        try:
            return cls(
                source_cid=value["source_cid"],
                dependency_cids=tuple(dependencies),
                analyzer_cid=value["analyzer_cid"],
                configuration_cid=value["configuration_cid"],
                semantics_cid=value["semantics_cid"],
                policy_cid=value["policy_cid"],
                solver_cid=value["solver_cid"],
                toolchain_cid=value["toolchain_cid"],
                result_schema=value["result_schema"],
            )
        except (KeyError, CacheKeyError) as exc:
            raise CacheIntegrityError("invalid cache key") from exc


@dataclass(frozen=True)
class CacheReceipt:
    """Immutable binding from a complete shard key to one result CID."""

    key: AnalysisCacheKey
    result_cid: str
    outcome: str
    created_at: int
    lease_expires_at: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, AnalysisCacheKey):
            raise CacheIntegrityError("receipt key must be AnalysisCacheKey")
        object.__setattr__(
            self, "result_cid", _structured_cid(self.result_cid, "result_cid")
        )
        if self.outcome not in ALL_OUTCOMES:
            raise CacheIntegrityError(f"unsupported cache outcome {self.outcome!r}")
        _integer(self.created_at, "created_at")
        if self.outcome in LEASED_OUTCOMES:
            if self.lease_expires_at is None:
                raise CacheLeaseError(f"{self.outcome} requires a bounded lease")
            expires = _integer(
                self.lease_expires_at, "lease_expires_at", minimum=self.created_at + 1
            )
            object.__setattr__(self, "lease_expires_at", expires)
        elif self.lease_expires_at is not None:
            raise CacheLeaseError("proved results must not carry a lease")

    @property
    def key_cid(self) -> str:
        return self.key.cid

    @property
    def result_schema(self) -> str:
        return self.key.result_schema

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    def is_fresh(self, now: int) -> bool:
        _integer(now, "now")
        return self.lease_expires_at is None or now < self.lease_expires_at

    def satisfies_completion(self, now: int) -> bool:
        return self.outcome == OUTCOME_PROVED and self.is_fresh(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "key": self.key.to_dict(),
            "key_cid": self.key_cid,
            "result_cid": self.result_cid,
            "result_schema": self.result_schema,
            "outcome": self.outcome,
            "created_at": self.created_at,
            "lease_expires_at": self.lease_expires_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CacheReceipt":
        if not isinstance(value, Mapping):
            raise CacheIntegrityError("cache receipt must be an object")
        _closed_fields(value, _RECEIPT_FIELDS, "cache receipt")
        if value.get("schema") != RECEIPT_SCHEMA:
            raise CacheIntegrityError("unsupported cache-receipt schema")
        key = AnalysisCacheKey.from_dict(value["key"])
        if value.get("key_cid") != key.cid:
            raise CacheIntegrityError("cache receipt key CID does not recompute")
        if value.get("result_schema") != key.result_schema:
            raise CacheIntegrityError("cache receipt result schema disagrees with key")
        return cls(
            key=key,
            result_cid=value["result_cid"],
            outcome=value["outcome"],
            created_at=value["created_at"],
            lease_expires_at=value["lease_expires_at"],
        )


@dataclass(frozen=True)
class AggregateSnapshotReceipt:
    """Bind reusable shard receipts to one exact repository-tree identity."""

    repository_tree_cid: str
    shard_receipt_cids: tuple[str, ...]
    created_at: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_tree_cid",
            _structured_cid(self.repository_tree_cid, "repository_tree_cid"),
        )
        if isinstance(self.shard_receipt_cids, (str, bytes, bytearray)):
            raise CacheIntegrityError("shard_receipt_cids must be an array")
        receipts = tuple(
            _structured_cid(item, f"shard_receipt_cids[{index}]")
            for index, item in enumerate(self.shard_receipt_cids)
        )
        if not receipts or len(set(receipts)) != len(receipts):
            raise CacheIntegrityError(
                "shard_receipt_cids must be non-empty and unique"
            )
        object.__setattr__(self, "shard_receipt_cids", tuple(sorted(receipts)))
        _integer(self.created_at, "created_at")

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "repository_tree_cid": self.repository_tree_cid,
            "shard_receipt_cids": list(self.shard_receipt_cids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AggregateSnapshotReceipt":
        if not isinstance(value, Mapping):
            raise CacheIntegrityError("snapshot receipt must be an object")
        _closed_fields(value, _SNAPSHOT_FIELDS, "snapshot receipt")
        if value.get("schema") != SNAPSHOT_SCHEMA:
            raise CacheIntegrityError("unsupported snapshot-receipt schema")
        receipts = value.get("shard_receipt_cids")
        if not isinstance(receipts, list):
            raise CacheIntegrityError("shard_receipt_cids must be an array")
        return cls(
            repository_tree_cid=value["repository_tree_cid"],
            shard_receipt_cids=tuple(receipts),
            created_at=value["created_at"],
        )


class ImmutableCAS:
    """Filesystem CAS with immutable atomic publication and verified reads."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
    ) -> None:
        self.root = Path(root)
        if type(max_object_bytes) is not int or max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be a positive integer")
        self.max_object_bytes = max_object_bytes
        self.structured_root = self.root / "structured"
        self.source_root = self.root / "source"
        self.structured_root.mkdir(parents=True, exist_ok=True)
        self.source_root.mkdir(parents=True, exist_ok=True)

    def path_for(self, cid: str, *, source: bool = False) -> Path:
        canonical = validate_cid(
            cid, codecs={SOURCE_CODEC if source else STRUCTURED_CODEC}
        )
        base = self.source_root if source else self.structured_root
        return base / canonical[:4] / canonical

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

    def _publish(self, target: Path, payload: bytes) -> None:
        if len(payload) > self.max_object_bytes:
            raise AnalysisCacheError("CAS object exceeds max_object_bytes")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=".publish-",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Hard-link publication is atomic and fails if target exists.
                os.link(temporary, target)
                self._fsync_directory(target.parent)
            except FileExistsError:
                # An identical concurrent writer is benign; callers verify it.
                pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def put(self, value: Any) -> str:
        payload = canonical_dag_json_bytes(value)
        cid = cid_for_structured(value)
        target = self.path_for(cid)
        self._publish(target, payload)
        self.get(cid)
        return cid

    put_structured = put

    def get(self, cid: str, *, expected_schema: str | None = None) -> Any:
        target = self.path_for(cid)
        try:
            payload = target.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise CacheIntegrityError(f"cannot read CAS object {cid}") from exc
        if len(payload) > self.max_object_bytes:
            raise CacheIntegrityError("stored CAS object exceeds max_object_bytes")
        try:
            value = json.loads(payload.decode("utf-8"))
            canonical = canonical_dag_json_bytes(value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CacheIntegrityError("stored structured object is invalid") from exc
        if payload != canonical:
            raise CacheIntegrityError("stored structured object is not canonical")
        try:
            decode_and_recompute_structured(cid, value)
        except (ContentIdentityError, TypeError, ValueError) as exc:
            raise CacheIntegrityError("stored structured object CID mismatch") from exc
        if expected_schema is not None:
            if not isinstance(value, dict) or value.get("schema") != expected_schema:
                raise CacheIntegrityError(
                    f"stored object schema is not {expected_schema!r}"
                )
        return value

    read = get
    get_structured = get

    def put_bytes(self, payload: bytes) -> str:
        if type(payload) is not bytes:
            raise TypeError("payload must be exact bytes")
        cid = cid_for_bytes(payload)
        target = self.path_for(cid, source=True)
        self._publish(target, payload)
        self.get_bytes(cid)
        return cid

    def get_bytes(self, cid: str) -> bytes:
        target = self.path_for(cid, source=True)
        try:
            payload = target.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise CacheIntegrityError(f"cannot read source CAS object {cid}") from exc
        if len(payload) > self.max_object_bytes:
            raise CacheIntegrityError("stored source object exceeds max_object_bytes")
        try:
            decode_and_recompute_source(cid, payload)
        except (ContentIdentityError, TypeError, ValueError) as exc:
            raise CacheIntegrityError("stored source object CID mismatch") from exc
        return payload


@dataclass(frozen=True)
class CacheLookup:
    """Result of a cache lookup; misses never carry completion authority."""

    hit: bool
    reason: str
    result: Any | None = None
    receipt: CacheReceipt | None = None

    @property
    def satisfies_completion(self) -> bool:
        return bool(
            self.hit
            and self.receipt is not None
            and self.receipt.outcome == OUTCOME_PROVED
        )


class AnalysisCache:
    """Immutable result/receipt CAS plus replaceable exact-key indexes."""

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], int | float] = time.time,
        max_lease_seconds: int = DEFAULT_MAX_LEASE_SECONDS,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
    ) -> None:
        self.root = Path(root)
        self.cas = ImmutableCAS(
            self.root / "cas", max_object_bytes=max_object_bytes
        )
        self.index_root = self.root / "index"
        self.index_root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".index.lock"
        self.clock = clock
        if type(max_lease_seconds) is not int or max_lease_seconds <= 0:
            raise ValueError("max_lease_seconds must be a positive integer")
        self.max_lease_seconds = max_lease_seconds
        self._thread_lock = threading.RLock()

    def _now(self) -> int:
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisCacheError("clock must return a numeric epoch")
        if value < 0 or value != value or value in (float("inf"), float("-inf")):
            raise AnalysisCacheError("clock must return a finite non-negative epoch")
        return int(value)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as stream:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _index_path(self, key_cid: str) -> Path:
        validate_cid(key_cid, codecs={STRUCTURED_CODEC})
        return self.index_root / key_cid[:4] / f"{key_cid}.json"

    @staticmethod
    def _replace_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=".index-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            ImmutableCAS._fsync_directory(path.parent)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _write_index(self, key_cid: str, receipt_cid: str) -> None:
        record = {
            "schema": INDEX_SCHEMA,
            "key_cid": key_cid,
            "receipt_cid": receipt_cid,
        }
        self._replace_atomic(
            self._index_path(key_cid), canonical_dag_json_bytes(record)
        )

    def _read_index(self, key_cid: str) -> str | None:
        path = self._index_path(key_cid)
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            record = json.loads(payload.decode("utf-8"))
            if payload != canonical_dag_json_bytes(record):
                raise CacheIntegrityError("cache index record is not canonical")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CacheIntegrityError("cache index record is invalid") from exc
        if (
            not isinstance(record, dict)
            or set(record) != {"schema", "key_cid", "receipt_cid"}
            or record.get("schema") != INDEX_SCHEMA
            or record.get("key_cid") != key_cid
        ):
            raise CacheIntegrityError("cache index membership is invalid")
        try:
            return validate_cid(
                record.get("receipt_cid"), codecs={STRUCTURED_CODEC}
            )
        except (ContentIdentityError, TypeError, ValueError) as exc:
            raise CacheIntegrityError("cache index receipt CID is invalid") from exc

    def put(
        self,
        key: AnalysisCacheKey,
        result: Mapping[str, Any],
        *,
        outcome: str = OUTCOME_PROVED,
        lease_seconds: int | None = None,
    ) -> CacheReceipt:
        if not isinstance(key, AnalysisCacheKey):
            raise TypeError("key must be AnalysisCacheKey")
        if not isinstance(result, Mapping) or result.get("schema") != key.result_schema:
            raise CacheIntegrityError(
                f"result must be an object with schema {key.result_schema!r}"
            )
        now = self._now()
        expires: int | None = None
        if outcome in LEASED_OUTCOMES:
            if (
                type(lease_seconds) is not int
                or lease_seconds <= 0
                or lease_seconds > self.max_lease_seconds
            ):
                raise CacheLeaseError(
                    "non-completion results require lease_seconds within "
                    f"1..{self.max_lease_seconds}"
                )
            expires = now + lease_seconds
        elif outcome == OUTCOME_PROVED:
            if lease_seconds is not None:
                raise CacheLeaseError("proved results do not use a lease")
        else:
            raise CacheIntegrityError(f"unsupported cache outcome {outcome!r}")

        result_cid = self.cas.put(dict(result))
        receipt = CacheReceipt(
            key=key,
            result_cid=result_cid,
            outcome=outcome,
            created_at=now,
            lease_expires_at=expires,
        )
        receipt_cid = self.cas.put(receipt.to_dict())
        with self._locked():
            self._write_index(key.cid, receipt_cid)
        return receipt

    store = put

    def lookup(self, key: AnalysisCacheKey) -> CacheLookup:
        if not isinstance(key, AnalysisCacheKey):
            raise TypeError("key must be AnalysisCacheKey")
        receipt_cid = self._read_index(key.cid)
        if receipt_cid is None:
            return CacheLookup(hit=False, reason="miss")
        raw_receipt = self.cas.get(receipt_cid, expected_schema=RECEIPT_SCHEMA)
        receipt = CacheReceipt.from_dict(raw_receipt)
        if receipt.key_cid != key.cid or receipt.key != key:
            raise CacheIntegrityError("cache index points to the wrong shard key")
        now = self._now()
        if not receipt.is_fresh(now):
            with self._locked():
                self._index_path(key.cid).unlink(missing_ok=True)
            return CacheLookup(hit=False, reason="expired")
        result = self.cas.get(
            receipt.result_cid, expected_schema=key.result_schema
        )
        return CacheLookup(
            hit=True, reason="hit", result=result, receipt=receipt
        )

    def get(self, key: AnalysisCacheKey) -> Any | None:
        return self.lookup(key).result

    def invalidate_source_closure(
        self, changed_cids: str | Sequence[str]
    ) -> tuple[str, ...]:
        """Drop only indexes whose source closure intersects ``changed_cids``.

        Immutable CAS objects are retained.  Keys must already contain their
        transitive dependency closure, so no global tree identity is required.
        """

        if isinstance(changed_cids, str):
            changed = {_source_cid(changed_cids, "changed_cids")}
        else:
            changed = {
                _source_cid(item, f"changed_cids[{index}]")
                for index, item in enumerate(changed_cids)
            }
        invalidated: list[str] = []
        with self._locked():
            for path in sorted(self.index_root.glob("*/*.json")):
                key_cid = path.stem
                try:
                    receipt_cid = self._read_index(key_cid)
                    if receipt_cid is None:
                        continue
                    raw = self.cas.get(
                        receipt_cid, expected_schema=RECEIPT_SCHEMA
                    )
                    receipt = CacheReceipt.from_dict(raw)
                except (AnalysisCacheError, ContentIdentityError, ValueError):
                    # Corrupt indexes cannot safely remain reusable.
                    path.unlink(missing_ok=True)
                    invalidated.append(key_cid)
                    continue
                if changed.intersection(receipt.key.source_closure):
                    path.unlink(missing_ok=True)
                    invalidated.append(key_cid)
        return tuple(sorted(invalidated))

    invalidate_dependencies = invalidate_source_closure

    def create_snapshot_receipt(
        self,
        repository_tree_cid: str,
        shard_receipts: Sequence[CacheReceipt | str],
    ) -> AggregateSnapshotReceipt:
        receipt_cids: list[str] = []
        for index, item in enumerate(shard_receipts):
            cid = item.cid if isinstance(item, CacheReceipt) else item
            cid = _structured_cid(cid, f"shard_receipts[{index}]")
            raw = self.cas.get(cid, expected_schema=RECEIPT_SCHEMA)
            CacheReceipt.from_dict(raw)
            receipt_cids.append(cid)
        snapshot = AggregateSnapshotReceipt(
            repository_tree_cid=repository_tree_cid,
            shard_receipt_cids=tuple(receipt_cids),
            created_at=self._now(),
        )
        self.cas.put(snapshot.to_dict())
        return snapshot

    def read_snapshot_receipt(
        self,
        snapshot_cid: str,
        *,
        expected_repository_tree_cid: str | None = None,
        expected_key_cids: Sequence[str] | None = None,
    ) -> AggregateSnapshotReceipt:
        raw = self.cas.get(snapshot_cid, expected_schema=SNAPSHOT_SCHEMA)
        snapshot = AggregateSnapshotReceipt.from_dict(raw)
        if (
            expected_repository_tree_cid is not None
            and snapshot.repository_tree_cid
            != _structured_cid(
                expected_repository_tree_cid, "expected_repository_tree_cid"
            )
        ):
            raise CacheIntegrityError("snapshot repository-tree membership mismatch")
        actual_keys: set[str] = set()
        for receipt_cid in snapshot.shard_receipt_cids:
            receipt = CacheReceipt.from_dict(
                self.cas.get(receipt_cid, expected_schema=RECEIPT_SCHEMA)
            )
            actual_keys.add(receipt.key_cid)
        if expected_key_cids is not None:
            expected = {
                _structured_cid(item, f"expected_key_cids[{index}]")
                for index, item in enumerate(expected_key_cids)
            }
            if actual_keys != expected:
                raise CacheIntegrityError("snapshot shard membership mismatch")
        return snapshot


class FormalVerificationCache(AnalysisCache):
    """Contract-analysis cache spelling used by supervisor proof integration."""


ProofCache = FormalVerificationCache


__all__ = [
    "ALL_OUTCOMES",
    "AggregateSnapshotReceipt",
    "AnalysisCache",
    "AnalysisCacheError",
    "AnalysisCacheKey",
    "CacheIntegrityError",
    "CacheKeyError",
    "CacheLeaseError",
    "CacheLookup",
    "CacheReceipt",
    "DEFAULT_MAX_LEASE_SECONDS",
    "FormalVerificationCache",
    "GOAL_ID",
    "INDEX_SCHEMA",
    "ImmutableCAS",
    "KEY_SCHEMA",
    "LEASED_OUTCOMES",
    "OUTCOME_ERROR",
    "OUTCOME_INCOMPLETE",
    "OUTCOME_NEGATIVE",
    "OUTCOME_PROVED",
    "OUTCOME_STALE",
    "OUTCOME_UNKNOWN",
    "OUTCOME_UNSUPPORTED",
    "OUTCOME_VIOLATED",
    "PROFILE_SCHEMA",
    "ProofCache",
    "RECEIPT_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "cache_profile_descriptor",
]
