"""Reconcile imported agent history with reconstructed repository truth (EAAEF-023).

Compare referenced commits, files, patches, and tests from imported agent
history against a quarantined reconstructed repository.  Each referenced
item is classified as present, stale, missing, or history-only and carries
content-addressed provenance for both the claim and the reconstructed match.

Imported history is never authority.  A present classification is an
identity match against reconstructed truth; it does not admit completion,
merge, mutation, or provider selection.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Final, TypeVar

CONTRACT_VERSION: Final[int] = 1
SCHEMA_VERSION: Final[int] = CONTRACT_VERSION

REFERENCED_WORK_INTERFACE: Final[str] = "ReferencedWork@1"
RECONSTRUCTED_TRUTH_INTERFACE: Final[str] = "ReconstructedTruth@1"
WORK_PROVENANCE_INTERFACE: Final[str] = "WorkProvenance@1"
WORK_CLASSIFICATION_RECORD_INTERFACE: Final[str] = "WorkClassificationRecord@1"
AGENT_HISTORY_RECONCILIATION_REPORT_INTERFACE: Final[str] = (
    "AgentHistoryReconciliationReport@1"
)

REFERENCED_WORK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/referenced-work@1"
)
RECONSTRUCTED_TRUTH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/reconstructed-truth@1"
)
WORK_PROVENANCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/work-provenance@1"
)
WORK_CLASSIFICATION_RECORD_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/work-classification-record@1"
)
AGENT_HISTORY_RECONCILIATION_REPORT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/agent-history-reconciliation-report@1"
)

ABSOLUTE_MAX_ITEMS: Final[int] = 4_096
ABSOLUTE_MAX_PATHS: Final[int] = 512
ABSOLUTE_MAX_ID_BYTES: Final[int] = 256
ABSOLUTE_MAX_TEXT_BYTES: Final[int] = 1_024
ABSOLUTE_MAX_RECORD_BYTES: Final[int] = 1_048_576
ABSOLUTE_MAX_DEPTH: Final[int] = 8

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_CIDV1_RE: Final[re.Pattern[str]] = re.compile(r"^b[a-z2-7]{20,}$")
_REF_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:HEAD|refs/(?:heads|tags|remotes)/[A-Za-z0-9._/\-]+|[A-Za-z0-9._/\-]+)$"
)

_HIDDEN_CHAIN_OF_THOUGHT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "chain_of_thought",
        "cot",
        "hidden_chain_of_thought",
        "hidden_cot",
        "hidden_reasoning",
        "private_reasoning",
        "scratchpad",
    }
)
_PRIVATE_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "witness",
    }
)

T = TypeVar("T")


class HistoryReconciliationError(ValueError):
    """Typed failure for invalid reconciliation inputs or records."""


class HistoryReconciliationBoundsError(HistoryReconciliationError):
    """A sequence, path, or payload exceeded its admitted bound."""


class HistoryReconciliationIdentityError(HistoryReconciliationError):
    """A claimed identity was missing, malformed, or contradictory."""


class WorkKind(str, Enum):
    """Referenced or reconstructed work discriminators."""

    COMMIT = "commit"
    FILE = "file"
    PATCH = "patch"
    TEST = "test"


class WorkClassification(str, Enum):
    """Closed classification of referenced work against reconstructed truth."""

    PRESENT = "present"
    STALE = "stale"
    MISSING = "missing"
    HISTORY_ONLY = "history_only"


class FileSurface(str, Enum):
    """Where a reconstructed file identity was observed."""

    HEAD_TREE = "head_tree"
    INDEX = "index"
    WORKTREE = "worktree"
    UNTRACKED = "untracked"
    HISTORY = "history"


class ComparisonMethod(str, Enum):
    """How a referenced identity was compared to reconstructed truth."""

    EXACT_IDENTITY = "exact_identity"
    LOCATOR_DIVERGENCE = "locator_divergence"
    HISTORY_OBJECT = "history_object"
    RELOCATED_IDENTITY = "relocated_identity"
    ABSENT = "absent"


class ClassificationReason(str, Enum):
    """Closed reasons recorded on each classification."""

    CURRENT_HEAD_IDENTITY_MATCH = "current_head_identity_match"
    CURRENT_REF_IDENTITY_MATCH = "current_ref_identity_match"
    CURRENT_OVERLAY_IDENTITY_MATCH = "current_overlay_identity_match"
    CURRENT_RELOCATED_IDENTITY_MATCH = "current_relocated_identity_match"
    CURRENT_LOCATOR_IDENTITY_DIVERGED = "current_locator_identity_diverged"
    CURRENT_REF_IDENTITY_DIVERGED = "current_ref_identity_diverged"
    HISTORY_IDENTITY_MATCH = "history_identity_match"
    REFERENCED_IDENTITY_ABSENT = "referenced_identity_absent"


class ProvenanceDomain(str, Enum):
    """Which plane produced a provenance record."""

    IMPORTED_HISTORY = "imported_history"
    RECONSTRUCTED_TRUTH = "reconstructed_truth"


class TrustClass(str, Enum):
    """Trust assigned to a claim or reconstructed observation."""

    IMPORTED_UNVERIFIED = "imported_unverified"
    IMPORTED_EXPORTABLE = "imported_exportable"
    LOCALLY_REVERIFIED = "locally_reverified"
    INDEPENDENTLY_ADMITTED = "independently_admitted"
    RECONSTRUCTED_TRUTH = "reconstructed_truth"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"

    @property
    def may_satisfy_completion(self) -> bool:
        return self in {
            TrustClass.LOCALLY_REVERIFIED,
            TrustClass.INDEPENDENTLY_ADMITTED,
        }

    @property
    def imported(self) -> bool:
        return self in {
            TrustClass.IMPORTED_UNVERIFIED,
            TrustClass.IMPORTED_EXPORTABLE,
            TrustClass.REJECTED,
            TrustClass.QUARANTINED,
        }


_CURRENT_FILE_SURFACES: Final[frozenset[FileSurface]] = frozenset(
    {
        FileSurface.HEAD_TREE,
        FileSurface.INDEX,
        FileSurface.WORKTREE,
        FileSurface.UNTRACKED,
    }
)
_SURFACE_PRECEDENCE: Final[Mapping[FileSurface, int]] = MappingProxyType(
    {
        FileSurface.UNTRACKED: 4,
        FileSurface.WORKTREE: 3,
        FileSurface.INDEX: 2,
        FileSurface.HEAD_TREE: 1,
        FileSurface.HISTORY: 0,
    }
)


def _canonical_value(value: Any, *, depth: int = 0) -> Any:
    if depth > ABSOLUTE_MAX_DEPTH:
        raise HistoryReconciliationBoundsError("canonical payload exceeds depth bound")
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        raise HistoryReconciliationError("canonical records must not contain floats")
    if isinstance(value, Enum):
        return _canonical_value(value.value, depth=depth + 1)
    if isinstance(value, _CanonicalRecord):
        return value.to_dict()
    if isinstance(value, Mapping):
        if not all(isinstance(raw_key, str) for raw_key in value):
            raise HistoryReconciliationError("canonical object keys must be strings")
        return {
            raw_key: _canonical_value(value[raw_key], depth=depth + 1)
            for raw_key in sorted(value)
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, depth=depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item, depth=depth + 1) for item in value]
        return sorted(items, key=canonical_json_bytes)
    raise HistoryReconciliationError(
        "unsupported canonical value: %s" % type(value).__name__
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode deterministic DAG-JSON-compatible UTF-8 bytes."""

    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """Return a sha256 content identity for a canonical payload."""

    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return "sha256:" + digest


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _key_is_forbidden(key: str) -> str | None:
    normalized = _normalize_key(key)
    if normalized in _HIDDEN_CHAIN_OF_THOUGHT_KEYS:
        return "hidden_chain_of_thought"
    if any(
        normalized == marker or normalized.endswith("_" + marker) or marker in normalized
        for marker in _PRIVATE_FIELD_MARKERS
    ):
        return "private_material"
    return None


def _reject_forbidden_keys(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            reason = _key_is_forbidden(str(raw_key))
            if reason == "hidden_chain_of_thought":
                raise HistoryReconciliationError(
                    f"{name} must not represent hidden chain-of-thought"
                )
            if reason == "private_material":
                raise HistoryReconciliationError(
                    f"{name} must not contain private material"
                )
            _reject_forbidden_keys(item, name=name)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_forbidden_keys(item, name=name)


def _text(
    value: Any,
    name: str,
    *,
    required: bool = True,
    max_bytes: int = ABSOLUTE_MAX_TEXT_BYTES,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise HistoryReconciliationError(f"{name} must be a string")
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise HistoryReconciliationBoundsError(f"{name} exceeds its byte limit")
    if required and not text:
        raise HistoryReconciliationError(f"{name} is required")
    return text


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoryReconciliationError(f"{name} must be a nonnegative integer")
    if value < 0:
        raise HistoryReconciliationError(f"{name} must be a nonnegative integer")
    return value


def _enum(value: Any, enum_cls: type[T], name: str) -> T:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise HistoryReconciliationError(
                f"{name} must be a {enum_cls.__name__} value"
            ) from exc
    raise HistoryReconciliationError(f"{name} must be a {enum_cls.__name__} value")


def _content_ref(value: Any, name: str, *, required: bool = True) -> str:
    text = _text(value, name, required=required, max_bytes=ABSOLUTE_MAX_ID_BYTES)
    if not text:
        return ""
    if _SHA256_RE.fullmatch(text) or _GIT_OBJECT_RE.fullmatch(text) or _CIDV1_RE.fullmatch(text):
        return text
    raise HistoryReconciliationIdentityError(
        f"{name} must be a sha256, git object, or CIDv1 identity"
    )


def _relative_path(value: Any, name: str, *, required: bool = True) -> str:
    text = _text(value, name, required=required, max_bytes=ABSOLUTE_MAX_ID_BYTES * 4)
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or (candidate.parts and candidate.parts[0].endswith(":"))
    ):
        raise HistoryReconciliationError(f"{name} must be repository-relative")
    path = candidate.as_posix().removeprefix("./")
    if path in ("", "."):
        raise HistoryReconciliationError(f"{name} must not be empty")
    return path


def _relative_paths(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, (str, bytes, bytearray, memoryview)) or not isinstance(
        values, Sequence
    ):
        raise HistoryReconciliationError(f"{name} must be a sequence of paths")
    else:
        items = values
    if len(items) > ABSOLUTE_MAX_PATHS:
        raise HistoryReconciliationBoundsError(f"{name} exceeds its item-count limit")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        path = _relative_path(item, name)
        if path in seen:
            raise HistoryReconciliationError(f"{name} must not contain duplicate paths")
        seen.add(path)
        result.append(path)
    return tuple(result)


def _ref_name(value: Any, name: str, *, required: bool = False) -> str:
    text = _text(value, name, required=required, max_bytes=ABSOLUTE_MAX_ID_BYTES)
    if not text:
        return ""
    if not _REF_NAME_RE.fullmatch(text):
        raise HistoryReconciliationError(f"{name} must be a git ref name")
    return text


def _bounded_sequence(values: Any, name: str) -> tuple[Any, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, (str, bytes, bytearray, memoryview)) or not isinstance(
        values, Sequence
    ):
        raise HistoryReconciliationError(f"{name} must be a sequence")
    else:
        items = values
    if len(items) > ABSOLUTE_MAX_ITEMS:
        raise HistoryReconciliationBoundsError(f"{name} exceeds its item-count limit")
    return tuple(items)


def _string_identity_map(values: Any, name: str) -> Mapping[str, str]:
    if values is None:
        mapping: Mapping[Any, Any] = {}
    elif not isinstance(values, Mapping):
        raise HistoryReconciliationError(f"{name} must be an object")
    else:
        mapping = values
    if len(mapping) > ABSOLUTE_MAX_PATHS:
        raise HistoryReconciliationBoundsError(f"{name} exceeds its item-count limit")
    result: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _relative_path(raw_key, f"{name} key")
        if key in result:
            raise HistoryReconciliationError(f"{name} must not contain duplicate paths")
        result[key] = _content_ref(raw_value, f"{name}[{key}]")
    return MappingProxyType(dict(sorted(result.items())))


def _require_record_bound(record: "_CanonicalRecord", *, artifact_name: str) -> None:
    encoded = canonical_json_bytes(record.to_dict())
    if len(encoded) > ABSOLUTE_MAX_RECORD_BYTES:
        raise HistoryReconciliationBoundsError(
            f"{artifact_name} exceeds its serialized-byte limit"
        )


def _unique_sorted(items: Iterable[T], keyfn: Any) -> tuple[T, ...]:
    ordered = sorted(items, key=keyfn)
    seen: set[Any] = set()
    result: list[T] = []
    for item in ordered:
        key = keyfn(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


class _CanonicalRecord:
    SCHEMA: ClassVar[str]
    INTERFACE: ClassVar[str]

    def _payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self._payload())
        payload.setdefault("schema", self.SCHEMA)
        payload.setdefault("interface", self.INTERFACE)
        payload.setdefault("contract_version", CONTRACT_VERSION)
        _reject_forbidden_keys(payload, name=self.INTERFACE)
        return _canonical_value(payload)

    def record_content_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True)
class WorkProvenance(_CanonicalRecord):
    """Provenance for one imported claim or reconstructed observation."""

    SCHEMA: ClassVar[str] = WORK_PROVENANCE_SCHEMA
    INTERFACE: ClassVar[str] = WORK_PROVENANCE_INTERFACE

    domain: ProvenanceDomain
    trust_class: TrustClass
    origin_record_id: str = ""
    source_family: str = ""
    adapter_id: str = ""
    captured_at_ms: int = 0
    quarantine_receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain", _enum(self.domain, ProvenanceDomain, "domain")
        )
        object.__setattr__(
            self, "trust_class", _enum(self.trust_class, TrustClass, "trust_class")
        )
        object.__setattr__(
            self,
            "origin_record_id",
            _content_ref(self.origin_record_id, "origin_record_id", required=False),
        )
        object.__setattr__(
            self,
            "source_family",
            _text(self.source_family, "source_family", required=False, max_bytes=ABSOLUTE_MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "adapter_id",
            _text(self.adapter_id, "adapter_id", required=False, max_bytes=ABSOLUTE_MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "captured_at_ms",
            _nonnegative_int(self.captured_at_ms, "captured_at_ms"),
        )
        object.__setattr__(
            self,
            "quarantine_receipt_id",
            _content_ref(
                self.quarantine_receipt_id, "quarantine_receipt_id", required=False
            ),
        )
        if self.domain is ProvenanceDomain.IMPORTED_HISTORY and self.trust_class not in {
            TrustClass.IMPORTED_UNVERIFIED,
            TrustClass.IMPORTED_EXPORTABLE,
            TrustClass.LOCALLY_REVERIFIED,
            TrustClass.INDEPENDENTLY_ADMITTED,
            TrustClass.REJECTED,
            TrustClass.QUARANTINED,
        }:
            raise HistoryReconciliationError(
                "imported provenance must use an imported or independently checked trust class"
            )
        if (
            self.domain is ProvenanceDomain.RECONSTRUCTED_TRUTH
            and self.trust_class is not TrustClass.RECONSTRUCTED_TRUTH
        ):
            raise HistoryReconciliationError(
                "reconstructed provenance must use reconstructed_truth trust"
            )
        if self.trust_class.imported and self.trust_class.may_satisfy_completion:
            raise HistoryReconciliationError(
                "imported trust classes cannot satisfy completion"
            )
        _require_record_bound(self, artifact_name="work provenance")

    def _payload(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "trust_class": self.trust_class.value,
            "origin_record_id": self.origin_record_id,
            "source_family": self.source_family,
            "adapter_id": self.adapter_id,
            "captured_at_ms": self.captured_at_ms,
            "quarantine_receipt_id": self.quarantine_receipt_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | WorkProvenance) -> "WorkProvenance":
        if isinstance(payload, WorkProvenance):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("work provenance must be an object")
        _reject_forbidden_keys(payload, name="work provenance")
        return cls(
            domain=payload.get("domain", ProvenanceDomain.IMPORTED_HISTORY),
            trust_class=payload.get("trust_class", TrustClass.IMPORTED_UNVERIFIED),
            origin_record_id=payload.get("origin_record_id", ""),
            source_family=payload.get("source_family", ""),
            adapter_id=payload.get("adapter_id", ""),
            captured_at_ms=payload.get("captured_at_ms", 0),
            quarantine_receipt_id=payload.get("quarantine_receipt_id", ""),
        )


def imported_provenance(
    *,
    origin_record_id: str = "",
    source_family: str = "",
    adapter_id: str = "",
    captured_at_ms: int = 0,
    trust_class: TrustClass = TrustClass.IMPORTED_UNVERIFIED,
) -> WorkProvenance:
    return WorkProvenance(
        domain=ProvenanceDomain.IMPORTED_HISTORY,
        trust_class=trust_class,
        origin_record_id=origin_record_id,
        source_family=source_family,
        adapter_id=adapter_id,
        captured_at_ms=captured_at_ms,
    )


def reconstructed_provenance(*, quarantine_receipt_id: str = "") -> WorkProvenance:
    return WorkProvenance(
        domain=ProvenanceDomain.RECONSTRUCTED_TRUTH,
        trust_class=TrustClass.RECONSTRUCTED_TRUTH,
        quarantine_receipt_id=quarantine_receipt_id,
    )


@dataclass(frozen=True)
class ReferencedCommit(_CanonicalRecord):
    """A commit claimed by imported agent history."""

    SCHEMA: ClassVar[str] = REFERENCED_WORK_SCHEMA
    INTERFACE: ClassVar[str] = REFERENCED_WORK_INTERFACE

    commit_id: str
    provenance: WorkProvenance
    ref_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit_id", _content_ref(self.commit_id, "commit_id"))
        object.__setattr__(self, "ref_name", _ref_name(self.ref_name, "ref_name"))
        object.__setattr__(self, "provenance", WorkProvenance.from_dict(self.provenance))
        if self.provenance.domain is not ProvenanceDomain.IMPORTED_HISTORY:
            raise HistoryReconciliationError(
                "referenced commits must carry imported-history provenance"
            )
        _require_record_bound(self, artifact_name="referenced commit")

    @property
    def work_kind(self) -> WorkKind:
        return WorkKind.COMMIT

    @property
    def locator(self) -> str:
        return self.ref_name or self.commit_id

    @property
    def identity(self) -> str:
        return self.commit_id

    def _payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind.value,
            "commit_id": self.commit_id,
            "ref_name": self.ref_name,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReferencedCommit) -> "ReferencedCommit":
        if isinstance(payload, ReferencedCommit):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("referenced commit must be an object")
        _reject_forbidden_keys(payload, name="referenced commit")
        return cls(
            commit_id=payload.get("commit_id", ""),
            ref_name=payload.get("ref_name", ""),
            provenance=payload.get("provenance") or imported_provenance(),
        )


@dataclass(frozen=True)
class ReferencedFile(_CanonicalRecord):
    """A file claimed by imported agent history."""

    SCHEMA: ClassVar[str] = REFERENCED_WORK_SCHEMA
    INTERFACE: ClassVar[str] = REFERENCED_WORK_INTERFACE

    path: str
    content_id: str
    provenance: WorkProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path, "path"))
        object.__setattr__(
            self, "content_id", _content_ref(self.content_id, "content_id")
        )
        object.__setattr__(self, "provenance", WorkProvenance.from_dict(self.provenance))
        if self.provenance.domain is not ProvenanceDomain.IMPORTED_HISTORY:
            raise HistoryReconciliationError(
                "referenced files must carry imported-history provenance"
            )
        _require_record_bound(self, artifact_name="referenced file")

    @property
    def work_kind(self) -> WorkKind:
        return WorkKind.FILE

    @property
    def locator(self) -> str:
        return self.path

    @property
    def identity(self) -> str:
        return self.content_id

    def _payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind.value,
            "path": self.path,
            "content_id": self.content_id,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReferencedFile) -> "ReferencedFile":
        if isinstance(payload, ReferencedFile):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("referenced file must be an object")
        _reject_forbidden_keys(payload, name="referenced file")
        return cls(
            path=payload.get("path", ""),
            content_id=payload.get("content_id", ""),
            provenance=payload.get("provenance") or imported_provenance(),
        )


@dataclass(frozen=True)
class ReferencedPatch(_CanonicalRecord):
    """A patch claimed by imported agent history.  Claimed application is untrusted."""

    SCHEMA: ClassVar[str] = REFERENCED_WORK_SCHEMA
    INTERFACE: ClassVar[str] = REFERENCED_WORK_INTERFACE

    patch_id: str
    provenance: WorkProvenance
    paths: tuple[str, ...] = ()
    result_file_ids: Mapping[str, str] = MappingProxyType({})
    claimed_applied: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_id", _content_ref(self.patch_id, "patch_id"))
        object.__setattr__(self, "paths", _relative_paths(self.paths, "paths"))
        object.__setattr__(
            self,
            "result_file_ids",
            _string_identity_map(self.result_file_ids, "result_file_ids"),
        )
        if not isinstance(self.claimed_applied, bool):
            raise HistoryReconciliationError("claimed_applied must be a boolean")
        object.__setattr__(self, "claimed_applied", self.claimed_applied)
        object.__setattr__(self, "provenance", WorkProvenance.from_dict(self.provenance))
        extra_result_paths = set(self.result_file_ids).difference(self.paths)
        if extra_result_paths:
            raise HistoryReconciliationError(
                "result_file_ids paths must be listed in paths"
            )
        if self.provenance.domain is not ProvenanceDomain.IMPORTED_HISTORY:
            raise HistoryReconciliationError(
                "referenced patches must carry imported-history provenance"
            )
        _require_record_bound(self, artifact_name="referenced patch")

    @property
    def work_kind(self) -> WorkKind:
        return WorkKind.PATCH

    @property
    def locator(self) -> str:
        return self.patch_id

    @property
    def identity(self) -> str:
        return self.patch_id

    def _payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind.value,
            "patch_id": self.patch_id,
            "paths": list(self.paths),
            "result_file_ids": dict(self.result_file_ids),
            "claimed_applied": self.claimed_applied,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReferencedPatch) -> "ReferencedPatch":
        if isinstance(payload, ReferencedPatch):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("referenced patch must be an object")
        _reject_forbidden_keys(payload, name="referenced patch")
        return cls(
            patch_id=payload.get("patch_id", ""),
            paths=payload.get("paths", ()),
            result_file_ids=payload.get("result_file_ids", {}),
            claimed_applied=payload.get("claimed_applied", False),
            provenance=payload.get("provenance") or imported_provenance(),
        )


@dataclass(frozen=True)
class ReferencedTest(_CanonicalRecord):
    """A test claimed by imported agent history.  Historical claims are not current."""

    SCHEMA: ClassVar[str] = REFERENCED_WORK_SCHEMA
    INTERFACE: ClassVar[str] = REFERENCED_WORK_INTERFACE

    test_id: str
    path: str
    content_id: str
    provenance: WorkProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "test_id",
            _text(self.test_id, "test_id", max_bytes=ABSOLUTE_MAX_ID_BYTES),
        )
        object.__setattr__(self, "path", _relative_path(self.path, "path"))
        object.__setattr__(
            self, "content_id", _content_ref(self.content_id, "content_id")
        )
        object.__setattr__(self, "provenance", WorkProvenance.from_dict(self.provenance))
        if self.provenance.domain is not ProvenanceDomain.IMPORTED_HISTORY:
            raise HistoryReconciliationError(
                "referenced tests must carry imported-history provenance"
            )
        _require_record_bound(self, artifact_name="referenced test")

    @property
    def work_kind(self) -> WorkKind:
        return WorkKind.TEST

    @property
    def locator(self) -> str:
        return self.test_id

    @property
    def identity(self) -> str:
        return self.content_id

    def _payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind.value,
            "test_id": self.test_id,
            "path": self.path,
            "content_id": self.content_id,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReferencedTest) -> "ReferencedTest":
        if isinstance(payload, ReferencedTest):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("referenced test must be an object")
        _reject_forbidden_keys(payload, name="referenced test")
        return cls(
            test_id=payload.get("test_id", ""),
            path=payload.get("path", ""),
            content_id=payload.get("content_id", ""),
            provenance=payload.get("provenance") or imported_provenance(),
        )


@dataclass(frozen=True)
class ImportedHistory(_CanonicalRecord):
    """Referenced commits, files, patches, and tests from imported history."""

    SCHEMA: ClassVar[str] = REFERENCED_WORK_SCHEMA
    INTERFACE: ClassVar[str] = REFERENCED_WORK_INTERFACE

    session_id: str
    commits: tuple[ReferencedCommit, ...] = ()
    files: tuple[ReferencedFile, ...] = ()
    patches: tuple[ReferencedPatch, ...] = ()
    tests: tuple[ReferencedTest, ...] = ()
    stream_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "session_id", _content_ref(self.session_id, "session_id")
        )
        object.__setattr__(
            self, "stream_id", _content_ref(self.stream_id, "stream_id", required=False)
        )
        commits = tuple(
            ReferencedCommit.from_dict(item)
            for item in _bounded_sequence(self.commits, "commits")
        )
        files = tuple(
            ReferencedFile.from_dict(item) for item in _bounded_sequence(self.files, "files")
        )
        patches = tuple(
            ReferencedPatch.from_dict(item)
            for item in _bounded_sequence(self.patches, "patches")
        )
        tests = tuple(
            ReferencedTest.from_dict(item) for item in _bounded_sequence(self.tests, "tests")
        )
        total = len(commits) + len(files) + len(patches) + len(tests)
        if total > ABSOLUTE_MAX_ITEMS:
            raise HistoryReconciliationBoundsError(
                "imported history exceeds its item-count limit"
            )
        object.__setattr__(
            self,
            "commits",
            _unique_sorted(commits, lambda item: (item.locator, item.identity)),
        )
        object.__setattr__(
            self,
            "files",
            _unique_sorted(files, lambda item: (item.locator, item.identity)),
        )
        object.__setattr__(
            self,
            "patches",
            _unique_sorted(patches, lambda item: (item.locator, item.identity)),
        )
        object.__setattr__(
            self,
            "tests",
            _unique_sorted(tests, lambda item: (item.locator, item.identity)),
        )
        _require_record_bound(self, artifact_name="imported history")

    @property
    def content_id(self) -> str:
        return self.record_content_id()

    def referenced_items(
        self,
    ) -> tuple[ReferencedCommit | ReferencedFile | ReferencedPatch | ReferencedTest, ...]:
        return self.commits + self.files + self.patches + self.tests

    def _payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stream_id": self.stream_id,
            "commits": [item.to_dict() for item in self.commits],
            "files": [item.to_dict() for item in self.files],
            "patches": [item.to_dict() for item in self.patches],
            "tests": [item.to_dict() for item in self.tests],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ImportedHistory) -> "ImportedHistory":
        if isinstance(payload, ImportedHistory):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("imported history must be an object")
        _reject_forbidden_keys(payload, name="imported history")
        return cls(
            session_id=payload.get("session_id", ""),
            stream_id=payload.get("stream_id", ""),
            commits=payload.get("commits", ()),
            files=payload.get("files", ()),
            patches=payload.get("patches", ()),
            tests=payload.get("tests", ()),
        )


@dataclass(frozen=True)
class ReconstructedCommit(_CanonicalRecord):
    """A commit present in reconstructed repository objects."""

    SCHEMA: ClassVar[str] = RECONSTRUCTED_TRUTH_SCHEMA
    INTERFACE: ClassVar[str] = RECONSTRUCTED_TRUTH_INTERFACE

    commit_id: str
    tree_id: str = ""
    parent_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit_id", _content_ref(self.commit_id, "commit_id"))
        object.__setattr__(
            self, "tree_id", _content_ref(self.tree_id, "tree_id", required=False)
        )
        parents = tuple(
            _content_ref(item, "parent_ids")
            for item in _bounded_sequence(self.parent_ids, "parent_ids")
        )
        object.__setattr__(self, "parent_ids", parents)

    def _payload(self) -> dict[str, Any]:
        return {
            "commit_id": self.commit_id,
            "tree_id": self.tree_id,
            "parent_ids": list(self.parent_ids),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any] | ReconstructedCommit | str
    ) -> "ReconstructedCommit":
        if isinstance(payload, ReconstructedCommit):
            return payload
        if isinstance(payload, str):
            return cls(commit_id=payload)
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("reconstructed commit must be an object")
        _reject_forbidden_keys(payload, name="reconstructed commit")
        return cls(
            commit_id=payload.get("commit_id", ""),
            tree_id=payload.get("tree_id", ""),
            parent_ids=payload.get("parent_ids", ()),
        )


@dataclass(frozen=True)
class ReconstructedFile(_CanonicalRecord):
    """A file identity observed on one reconstructed surface."""

    SCHEMA: ClassVar[str] = RECONSTRUCTED_TRUTH_SCHEMA
    INTERFACE: ClassVar[str] = RECONSTRUCTED_TRUTH_INTERFACE

    path: str
    content_id: str
    surface: FileSurface
    commit_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path, "path"))
        object.__setattr__(
            self, "content_id", _content_ref(self.content_id, "content_id")
        )
        object.__setattr__(self, "surface", _enum(self.surface, FileSurface, "surface"))
        object.__setattr__(
            self, "commit_id", _content_ref(self.commit_id, "commit_id", required=False)
        )

    @property
    def is_current(self) -> bool:
        return self.surface in _CURRENT_FILE_SURFACES

    def _payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_id": self.content_id,
            "surface": self.surface.value,
            "commit_id": self.commit_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReconstructedFile) -> "ReconstructedFile":
        if isinstance(payload, ReconstructedFile):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("reconstructed file must be an object")
        _reject_forbidden_keys(payload, name="reconstructed file")
        return cls(
            path=payload.get("path", ""),
            content_id=payload.get("content_id", ""),
            surface=payload.get("surface", FileSurface.HEAD_TREE),
            commit_id=payload.get("commit_id", ""),
        )


@dataclass(frozen=True)
class ReconstructedPatch(_CanonicalRecord):
    """A patch identity observed in reconstructed overlay or history."""

    SCHEMA: ClassVar[str] = RECONSTRUCTED_TRUTH_SCHEMA
    INTERFACE: ClassVar[str] = RECONSTRUCTED_TRUTH_INTERFACE

    patch_id: str
    current: bool
    paths: tuple[str, ...] = ()
    result_file_ids: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_id", _content_ref(self.patch_id, "patch_id"))
        if not isinstance(self.current, bool):
            raise HistoryReconciliationError("current must be a boolean")
        object.__setattr__(self, "paths", _relative_paths(self.paths, "paths"))
        object.__setattr__(
            self,
            "result_file_ids",
            _string_identity_map(self.result_file_ids, "result_file_ids"),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "current": self.current,
            "paths": list(self.paths),
            "result_file_ids": dict(self.result_file_ids),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any] | ReconstructedPatch
    ) -> "ReconstructedPatch":
        if isinstance(payload, ReconstructedPatch):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("reconstructed patch must be an object")
        _reject_forbidden_keys(payload, name="reconstructed patch")
        return cls(
            patch_id=payload.get("patch_id", ""),
            current=payload.get("current", False),
            paths=payload.get("paths", ()),
            result_file_ids=payload.get("result_file_ids", {}),
        )


@dataclass(frozen=True)
class ReconstructedTest(_CanonicalRecord):
    """A test identity observed in reconstructed overlay or history."""

    SCHEMA: ClassVar[str] = RECONSTRUCTED_TRUTH_SCHEMA
    INTERFACE: ClassVar[str] = RECONSTRUCTED_TRUTH_INTERFACE

    test_id: str
    path: str
    content_id: str
    current: bool
    commit_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "test_id",
            _text(self.test_id, "test_id", max_bytes=ABSOLUTE_MAX_ID_BYTES),
        )
        object.__setattr__(self, "path", _relative_path(self.path, "path"))
        object.__setattr__(
            self, "content_id", _content_ref(self.content_id, "content_id")
        )
        if not isinstance(self.current, bool):
            raise HistoryReconciliationError("current must be a boolean")
        object.__setattr__(
            self, "commit_id", _content_ref(self.commit_id, "commit_id", required=False)
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "path": self.path,
            "content_id": self.content_id,
            "current": self.current,
            "commit_id": self.commit_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | ReconstructedTest) -> "ReconstructedTest":
        if isinstance(payload, ReconstructedTest):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("reconstructed test must be an object")
        _reject_forbidden_keys(payload, name="reconstructed test")
        return cls(
            test_id=payload.get("test_id", ""),
            path=payload.get("path", ""),
            content_id=payload.get("content_id", ""),
            current=payload.get("current", False),
            commit_id=payload.get("commit_id", ""),
        )


def _overlay_files(
    files: Sequence[ReconstructedFile],
) -> Mapping[str, ReconstructedFile]:
    overlay: dict[str, ReconstructedFile] = {}
    for record in files:
        if not record.is_current:
            continue
        existing = overlay.get(record.path)
        if existing is None:
            overlay[record.path] = record
            continue
        existing_rank = _SURFACE_PRECEDENCE[existing.surface]
        incoming_rank = _SURFACE_PRECEDENCE[record.surface]
        if incoming_rank > existing_rank:
            overlay[record.path] = record
            continue
        if incoming_rank == existing_rank and existing.content_id != record.content_id:
            raise HistoryReconciliationIdentityError(
                f"reconstructed truth has conflicting identities for {record.path}"
            )
    return MappingProxyType(dict(sorted(overlay.items())))


@dataclass(frozen=True)
class ReconstructedTruth(_CanonicalRecord):
    """Quarantined reconstructed repository truth used as the comparison plane."""

    SCHEMA: ClassVar[str] = RECONSTRUCTED_TRUTH_SCHEMA
    INTERFACE: ClassVar[str] = RECONSTRUCTED_TRUTH_INTERFACE

    quarantine_receipt_id: str
    head_commit_id: str
    refs: Mapping[str, str] = MappingProxyType({})
    commits: tuple[ReconstructedCommit, ...] = ()
    files: tuple[ReconstructedFile, ...] = ()
    patches: tuple[ReconstructedPatch, ...] = ()
    tests: tuple[ReconstructedTest, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "quarantine_receipt_id",
            _content_ref(self.quarantine_receipt_id, "quarantine_receipt_id"),
        )
        object.__setattr__(
            self,
            "head_commit_id",
            _content_ref(self.head_commit_id, "head_commit_id", required=False),
        )
        refs_raw = self.refs if self.refs is not None else {}
        if not isinstance(refs_raw, Mapping):
            raise HistoryReconciliationError("refs must be an object")
        if len(refs_raw) > ABSOLUTE_MAX_PATHS:
            raise HistoryReconciliationBoundsError("refs exceeds its item-count limit")
        refs: dict[str, str] = {}
        for raw_key, raw_value in refs_raw.items():
            key = _ref_name(raw_key, "refs key", required=True)
            refs[key] = _content_ref(raw_value, f"refs[{key}]")
        object.__setattr__(self, "refs", MappingProxyType(dict(sorted(refs.items()))))
        commits = tuple(
            ReconstructedCommit.from_dict(item)
            for item in _bounded_sequence(self.commits, "commits")
        )
        object.__setattr__(
            self,
            "commits",
            _unique_sorted(commits, lambda item: item.commit_id),
        )
        files = tuple(
            ReconstructedFile.from_dict(item)
            for item in _bounded_sequence(self.files, "files")
        )
        object.__setattr__(
            self,
            "files",
            _unique_sorted(
                files, lambda item: (item.path, item.content_id, item.surface.value)
            ),
        )
        patches = tuple(
            ReconstructedPatch.from_dict(item)
            for item in _bounded_sequence(self.patches, "patches")
        )
        object.__setattr__(
            self,
            "patches",
            _unique_sorted(patches, lambda item: (item.patch_id, item.current)),
        )
        tests = tuple(
            ReconstructedTest.from_dict(item)
            for item in _bounded_sequence(self.tests, "tests")
        )
        object.__setattr__(
            self,
            "tests",
            _unique_sorted(tests, lambda item: (item.test_id, item.content_id, item.current)),
        )
        commit_ids = {item.commit_id for item in self.commits}
        if self.head_commit_id and self.head_commit_id not in commit_ids:
            raise HistoryReconciliationIdentityError(
                "head_commit_id must exist in reconstructed commits"
            )
        for ref_name, commit_id in self.refs.items():
            if commit_id not in commit_ids:
                raise HistoryReconciliationIdentityError(
                    f"ref {ref_name} must exist in reconstructed commits"
                )
        _overlay_files(self.files)
        _require_record_bound(self, artifact_name="reconstructed truth")

    @property
    def content_id(self) -> str:
        return self.record_content_id()

    @property
    def commit_ids(self) -> frozenset[str]:
        return frozenset(item.commit_id for item in self.commits)

    @property
    def current_ref_tips(self) -> frozenset[str]:
        tips = set(self.refs.values())
        if self.head_commit_id:
            tips.add(self.head_commit_id)
        return frozenset(tips)

    @property
    def overlay_files(self) -> Mapping[str, ReconstructedFile]:
        return _overlay_files(self.files)

    @property
    def historical_files(self) -> tuple[ReconstructedFile, ...]:
        return tuple(item for item in self.files if item.surface is FileSurface.HISTORY)

    @property
    def current_patches(self) -> Mapping[str, ReconstructedPatch]:
        return MappingProxyType(
            {item.patch_id: item for item in self.patches if item.current}
        )

    @property
    def historical_patches(self) -> Mapping[str, ReconstructedPatch]:
        return MappingProxyType(
            {item.patch_id: item for item in self.patches if not item.current}
        )

    @property
    def current_tests(self) -> Mapping[str, ReconstructedTest]:
        return MappingProxyType({item.test_id: item for item in self.tests if item.current})

    @property
    def historical_tests(self) -> Mapping[str, ReconstructedTest]:
        return MappingProxyType(
            {item.test_id: item for item in self.tests if not item.current}
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "quarantine_receipt_id": self.quarantine_receipt_id,
            "head_commit_id": self.head_commit_id,
            "refs": dict(self.refs),
            "commits": [item.to_dict() for item in self.commits],
            "files": [item.to_dict() for item in self.files],
            "patches": [item.to_dict() for item in self.patches],
            "tests": [item.to_dict() for item in self.tests],
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any] | ReconstructedTruth
    ) -> "ReconstructedTruth":
        if isinstance(payload, ReconstructedTruth):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError("reconstructed truth must be an object")
        _reject_forbidden_keys(payload, name="reconstructed truth")
        return cls(
            quarantine_receipt_id=payload.get("quarantine_receipt_id", ""),
            head_commit_id=payload.get("head_commit_id", ""),
            refs=payload.get("refs", {}),
            commits=payload.get("commits", ()),
            files=payload.get("files", ()),
            patches=payload.get("patches", ()),
            tests=payload.get("tests", ()),
        )


@dataclass(frozen=True)
class WorkClassificationRecord(_CanonicalRecord):
    """One referenced-work classification against reconstructed truth."""

    SCHEMA: ClassVar[str] = WORK_CLASSIFICATION_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = WORK_CLASSIFICATION_RECORD_INTERFACE

    work_kind: WorkKind
    locator: str
    referenced_identity: str
    classification: WorkClassification
    comparison: ComparisonMethod
    reason: ClassificationReason
    claim_provenance: WorkProvenance
    reconstructed_identity: str = ""
    reconstructed_surfaces: tuple[str, ...] = ()
    relocated_path: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "work_kind", _enum(self.work_kind, WorkKind, "work_kind")
        )
        object.__setattr__(
            self,
            "locator",
            _text(self.locator, "locator", max_bytes=ABSOLUTE_MAX_ID_BYTES * 4),
        )
        object.__setattr__(
            self,
            "referenced_identity",
            _content_ref(self.referenced_identity, "referenced_identity"),
        )
        object.__setattr__(
            self,
            "classification",
            _enum(self.classification, WorkClassification, "classification"),
        )
        object.__setattr__(
            self, "comparison", _enum(self.comparison, ComparisonMethod, "comparison")
        )
        object.__setattr__(
            self, "reason", _enum(self.reason, ClassificationReason, "reason")
        )
        object.__setattr__(
            self, "claim_provenance", WorkProvenance.from_dict(self.claim_provenance)
        )
        object.__setattr__(
            self,
            "reconstructed_identity",
            _content_ref(
                self.reconstructed_identity, "reconstructed_identity", required=False
            ),
        )
        surfaces = tuple(
            _text(item, "reconstructed_surfaces", max_bytes=ABSOLUTE_MAX_ID_BYTES)
            for item in _bounded_sequence(
                self.reconstructed_surfaces, "reconstructed_surfaces"
            )
        )
        object.__setattr__(self, "reconstructed_surfaces", surfaces)
        object.__setattr__(
            self,
            "relocated_path",
            _relative_path(self.relocated_path, "relocated_path", required=False),
        )
        if (
            self.classification is WorkClassification.MISSING
            and self.reconstructed_identity
        ):
            raise HistoryReconciliationIdentityError(
                "missing work must not carry a reconstructed identity"
            )
        if (
            self.classification is not WorkClassification.MISSING
            and not self.reconstructed_identity
        ):
            raise HistoryReconciliationIdentityError(
                "classified work other than missing must bind a reconstructed identity"
            )
        _require_record_bound(self, artifact_name="work classification record")

    @property
    def may_satisfy_completion(self) -> bool:
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind.value,
            "locator": self.locator,
            "referenced_identity": self.referenced_identity,
            "classification": self.classification.value,
            "comparison": self.comparison.value,
            "reason": self.reason.value,
            "claim_provenance": self.claim_provenance.to_dict(),
            "reconstructed_identity": self.reconstructed_identity,
            "reconstructed_surfaces": list(self.reconstructed_surfaces),
            "relocated_path": self.relocated_path,
            "may_satisfy_completion": False,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any] | WorkClassificationRecord
    ) -> "WorkClassificationRecord":
        if isinstance(payload, WorkClassificationRecord):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError(
                "work classification record must be an object"
            )
        _reject_forbidden_keys(payload, name="work classification record")
        if payload.get("may_satisfy_completion") not in (None, False):
            raise HistoryReconciliationError(
                "classification records cannot satisfy completion"
            )
        return cls(
            work_kind=payload.get("work_kind", WorkKind.FILE),
            locator=payload.get("locator", ""),
            referenced_identity=payload.get("referenced_identity", ""),
            classification=payload.get("classification", WorkClassification.MISSING),
            comparison=payload.get("comparison", ComparisonMethod.ABSENT),
            reason=payload.get("reason", ClassificationReason.REFERENCED_IDENTITY_ABSENT),
            claim_provenance=payload.get("claim_provenance") or imported_provenance(),
            reconstructed_identity=payload.get("reconstructed_identity", ""),
            reconstructed_surfaces=payload.get("reconstructed_surfaces", ()),
            relocated_path=payload.get("relocated_path", ""),
        )


def _record(
    *,
    work_kind: WorkKind,
    locator: str,
    referenced_identity: str,
    classification: WorkClassification,
    comparison: ComparisonMethod,
    reason: ClassificationReason,
    claim_provenance: WorkProvenance,
    reconstructed_identity: str = "",
    reconstructed_surfaces: Sequence[str] = (),
    relocated_path: str = "",
) -> WorkClassificationRecord:
    return WorkClassificationRecord(
        work_kind=work_kind,
        locator=locator,
        referenced_identity=referenced_identity,
        classification=classification,
        comparison=comparison,
        reason=reason,
        claim_provenance=claim_provenance,
        reconstructed_identity=reconstructed_identity,
        reconstructed_surfaces=tuple(reconstructed_surfaces),
        relocated_path=relocated_path,
    )


def _classify_commit(
    referenced: ReferencedCommit, truth: ReconstructedTruth
) -> WorkClassificationRecord:
    commit_id = referenced.commit_id
    if referenced.ref_name:
        current_tip = truth.refs.get(referenced.ref_name)
        if current_tip == commit_id:
            return _record(
                work_kind=WorkKind.COMMIT,
                locator=referenced.locator,
                referenced_identity=commit_id,
                classification=WorkClassification.PRESENT,
                comparison=ComparisonMethod.EXACT_IDENTITY,
                reason=ClassificationReason.CURRENT_REF_IDENTITY_MATCH,
                claim_provenance=referenced.provenance,
                reconstructed_identity=current_tip,
                reconstructed_surfaces=("refs/" + referenced.ref_name,),
            )
        if current_tip:
            return _record(
                work_kind=WorkKind.COMMIT,
                locator=referenced.locator,
                referenced_identity=commit_id,
                classification=WorkClassification.STALE,
                comparison=ComparisonMethod.LOCATOR_DIVERGENCE,
                reason=ClassificationReason.CURRENT_REF_IDENTITY_DIVERGED,
                claim_provenance=referenced.provenance,
                reconstructed_identity=current_tip,
                reconstructed_surfaces=("refs/" + referenced.ref_name,),
            )
    if truth.head_commit_id == commit_id:
        return _record(
            work_kind=WorkKind.COMMIT,
            locator=referenced.locator,
            referenced_identity=commit_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_HEAD_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=commit_id,
            reconstructed_surfaces=("HEAD",),
        )
    if commit_id in truth.current_ref_tips:
        matching_refs = tuple(
            sorted(
                name
                for name, value in truth.refs.items()
                if value == commit_id
            )
        )
        return _record(
            work_kind=WorkKind.COMMIT,
            locator=referenced.locator,
            referenced_identity=commit_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_REF_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=commit_id,
            reconstructed_surfaces=matching_refs or ("refs",),
        )
    if commit_id in truth.commit_ids:
        return _record(
            work_kind=WorkKind.COMMIT,
            locator=referenced.locator,
            referenced_identity=commit_id,
            classification=WorkClassification.HISTORY_ONLY,
            comparison=ComparisonMethod.HISTORY_OBJECT,
            reason=ClassificationReason.HISTORY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=commit_id,
            reconstructed_surfaces=("history",),
        )
    return _record(
        work_kind=WorkKind.COMMIT,
        locator=referenced.locator,
        referenced_identity=commit_id,
        classification=WorkClassification.MISSING,
        comparison=ComparisonMethod.ABSENT,
        reason=ClassificationReason.REFERENCED_IDENTITY_ABSENT,
        claim_provenance=referenced.provenance,
    )


def _classify_file(
    referenced: ReferencedFile, truth: ReconstructedTruth
) -> WorkClassificationRecord:
    overlay = truth.overlay_files
    current = overlay.get(referenced.path)
    if current is not None and current.content_id == referenced.content_id:
        return _record(
            work_kind=WorkKind.FILE,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=current.content_id,
            reconstructed_surfaces=(current.surface.value,),
        )
    if current is not None:
        return _record(
            work_kind=WorkKind.FILE,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.STALE,
            comparison=ComparisonMethod.LOCATOR_DIVERGENCE,
            reason=ClassificationReason.CURRENT_LOCATOR_IDENTITY_DIVERGED,
            claim_provenance=referenced.provenance,
            reconstructed_identity=current.content_id,
            reconstructed_surfaces=(current.surface.value,),
        )
    relocated = next(
        (
            item
            for item in overlay.values()
            if item.content_id == referenced.content_id
        ),
        None,
    )
    if relocated is not None:
        return _record(
            work_kind=WorkKind.FILE,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.RELOCATED_IDENTITY,
            reason=ClassificationReason.CURRENT_RELOCATED_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=relocated.content_id,
            reconstructed_surfaces=(relocated.surface.value,),
            relocated_path=relocated.path,
        )
    historical = next(
        (
            item
            for item in truth.historical_files
            if item.content_id == referenced.content_id
        ),
        None,
    )
    if historical is not None:
        return _record(
            work_kind=WorkKind.FILE,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.HISTORY_ONLY,
            comparison=ComparisonMethod.HISTORY_OBJECT,
            reason=ClassificationReason.HISTORY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=historical.content_id,
            reconstructed_surfaces=(FileSurface.HISTORY.value,),
            relocated_path="" if historical.path == referenced.path else historical.path,
        )
    return _record(
        work_kind=WorkKind.FILE,
        locator=referenced.locator,
        referenced_identity=referenced.content_id,
        classification=WorkClassification.MISSING,
        comparison=ComparisonMethod.ABSENT,
        reason=ClassificationReason.REFERENCED_IDENTITY_ABSENT,
        claim_provenance=referenced.provenance,
    )


def _patch_results_match_overlay(
    referenced: ReferencedPatch, overlay: Mapping[str, ReconstructedFile]
) -> bool:
    if not referenced.result_file_ids:
        return False
    for path, content_id in referenced.result_file_ids.items():
        current = overlay.get(path)
        if current is None or current.content_id != content_id:
            return False
    return True


def _patch_results_diverge(
    referenced: ReferencedPatch, overlay: Mapping[str, ReconstructedFile]
) -> ReconstructedFile | None:
    if not referenced.result_file_ids:
        return None
    for path, expected in referenced.result_file_ids.items():
        current = overlay.get(path)
        if current is not None and current.content_id != expected:
            return current
    return None


def _classify_patch(
    referenced: ReferencedPatch, truth: ReconstructedTruth
) -> WorkClassificationRecord:
    overlay = truth.overlay_files
    current_patch = truth.current_patches.get(referenced.patch_id)
    if current_patch is not None:
        if referenced.result_file_ids and not _patch_results_match_overlay(
            referenced, overlay
        ):
            diverged = _patch_results_diverge(referenced, overlay)
            return _record(
                work_kind=WorkKind.PATCH,
                locator=referenced.locator,
                referenced_identity=referenced.patch_id,
                classification=WorkClassification.STALE,
                comparison=ComparisonMethod.LOCATOR_DIVERGENCE,
                reason=ClassificationReason.CURRENT_LOCATOR_IDENTITY_DIVERGED,
                claim_provenance=referenced.provenance,
                reconstructed_identity=(
                    diverged.content_id if diverged is not None else current_patch.patch_id
                ),
                reconstructed_surfaces=("overlay_patch",),
            )
        return _record(
            work_kind=WorkKind.PATCH,
            locator=referenced.locator,
            referenced_identity=referenced.patch_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=current_patch.patch_id,
            reconstructed_surfaces=("overlay_patch",),
        )
    if _patch_results_match_overlay(referenced, overlay):
        return _record(
            work_kind=WorkKind.PATCH,
            locator=referenced.locator,
            referenced_identity=referenced.patch_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=next(iter(referenced.result_file_ids.values())),
            reconstructed_surfaces=("overlay",),
        )
    diverged = _patch_results_diverge(referenced, overlay)
    if diverged is not None:
        return _record(
            work_kind=WorkKind.PATCH,
            locator=referenced.locator,
            referenced_identity=referenced.patch_id,
            classification=WorkClassification.STALE,
            comparison=ComparisonMethod.LOCATOR_DIVERGENCE,
            reason=ClassificationReason.CURRENT_LOCATOR_IDENTITY_DIVERGED,
            claim_provenance=referenced.provenance,
            reconstructed_identity=diverged.content_id,
            reconstructed_surfaces=(diverged.surface.value,),
        )
    historical = truth.historical_patches.get(referenced.patch_id)
    if historical is None:
        historical_file = next(
            (
                item
                for item in truth.historical_files
                if item.content_id in set(referenced.result_file_ids.values())
                or item.content_id == referenced.patch_id
            ),
            None,
        )
        if historical_file is not None:
            return _record(
                work_kind=WorkKind.PATCH,
                locator=referenced.locator,
                referenced_identity=referenced.patch_id,
                classification=WorkClassification.HISTORY_ONLY,
                comparison=ComparisonMethod.HISTORY_OBJECT,
                reason=ClassificationReason.HISTORY_IDENTITY_MATCH,
                claim_provenance=referenced.provenance,
                reconstructed_identity=historical_file.content_id,
                reconstructed_surfaces=(FileSurface.HISTORY.value,),
            )
    if historical is not None:
        return _record(
            work_kind=WorkKind.PATCH,
            locator=referenced.locator,
            referenced_identity=referenced.patch_id,
            classification=WorkClassification.HISTORY_ONLY,
            comparison=ComparisonMethod.HISTORY_OBJECT,
            reason=ClassificationReason.HISTORY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=historical.patch_id,
            reconstructed_surfaces=("history",),
        )
    return _record(
        work_kind=WorkKind.PATCH,
        locator=referenced.locator,
        referenced_identity=referenced.patch_id,
        classification=WorkClassification.MISSING,
        comparison=ComparisonMethod.ABSENT,
        reason=ClassificationReason.REFERENCED_IDENTITY_ABSENT,
        claim_provenance=referenced.provenance,
    )


def _classify_test(
    referenced: ReferencedTest, truth: ReconstructedTruth
) -> WorkClassificationRecord:
    current = truth.current_tests.get(referenced.test_id)
    if current is None:
        current = next(
            (
                item
                for item in truth.current_tests.values()
                if item.path == referenced.path
            ),
            None,
        )
    if current is not None and current.content_id == referenced.content_id:
        return _record(
            work_kind=WorkKind.TEST,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.PRESENT,
            comparison=ComparisonMethod.EXACT_IDENTITY,
            reason=ClassificationReason.CURRENT_OVERLAY_IDENTITY_MATCH,
            claim_provenance=referenced.provenance,
            reconstructed_identity=current.content_id,
            reconstructed_surfaces=("current_test",),
        )
    if current is not None:
        return _record(
            work_kind=WorkKind.TEST,
            locator=referenced.locator,
            referenced_identity=referenced.content_id,
            classification=WorkClassification.STALE,
            comparison=ComparisonMethod.LOCATOR_DIVERGENCE,
            reason=ClassificationReason.CURRENT_LOCATOR_IDENTITY_DIVERGED,
            claim_provenance=referenced.provenance,
            reconstructed_identity=current.content_id,
            reconstructed_surfaces=("current_test",),
        )
    historical = truth.historical_tests.get(referenced.test_id)
    if historical is None:
        historical = next(
            (
                item
                for item in truth.historical_tests.values()
                if item.content_id == referenced.content_id or item.path == referenced.path
            ),
            None,
        )
    if historical is not None and (
        historical.content_id == referenced.content_id
        or historical.test_id == referenced.test_id
    ):
        if historical.content_id == referenced.content_id:
            return _record(
                work_kind=WorkKind.TEST,
                locator=referenced.locator,
                referenced_identity=referenced.content_id,
                classification=WorkClassification.HISTORY_ONLY,
                comparison=ComparisonMethod.HISTORY_OBJECT,
                reason=ClassificationReason.HISTORY_IDENTITY_MATCH,
                claim_provenance=referenced.provenance,
                reconstructed_identity=historical.content_id,
                reconstructed_surfaces=("history",),
            )
    return _record(
        work_kind=WorkKind.TEST,
        locator=referenced.locator,
        referenced_identity=referenced.content_id,
        classification=WorkClassification.MISSING,
        comparison=ComparisonMethod.ABSENT,
        reason=ClassificationReason.REFERENCED_IDENTITY_ABSENT,
        claim_provenance=referenced.provenance,
    )


def classify_referenced_work(
    referenced: ReferencedCommit | ReferencedFile | ReferencedPatch | ReferencedTest,
    truth: ReconstructedTruth,
) -> WorkClassificationRecord:
    """Classify one referenced item against reconstructed truth."""

    if isinstance(referenced, ReferencedCommit):
        return _classify_commit(referenced, truth)
    if isinstance(referenced, ReferencedFile):
        return _classify_file(referenced, truth)
    if isinstance(referenced, ReferencedPatch):
        return _classify_patch(referenced, truth)
    if isinstance(referenced, ReferencedTest):
        return _classify_test(referenced, truth)
    raise HistoryReconciliationError("unsupported referenced work")


@dataclass(frozen=True)
class HistoryReconciliationReport(_CanonicalRecord):
    """Deterministic classification of imported history against reconstructed truth."""

    SCHEMA: ClassVar[str] = AGENT_HISTORY_RECONCILIATION_REPORT_SCHEMA
    INTERFACE: ClassVar[str] = AGENT_HISTORY_RECONCILIATION_REPORT_INTERFACE

    imported_history_id: str
    reconstructed_truth_id: str
    quarantine_receipt_id: str
    records: tuple[WorkClassificationRecord, ...]
    counts: Mapping[str, int] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "imported_history_id",
            _content_ref(self.imported_history_id, "imported_history_id"),
        )
        object.__setattr__(
            self,
            "reconstructed_truth_id",
            _content_ref(self.reconstructed_truth_id, "reconstructed_truth_id"),
        )
        object.__setattr__(
            self,
            "quarantine_receipt_id",
            _content_ref(self.quarantine_receipt_id, "quarantine_receipt_id"),
        )
        records = tuple(
            WorkClassificationRecord.from_dict(item)
            for item in _bounded_sequence(self.records, "records")
        )
        object.__setattr__(
            self,
            "records",
            _unique_sorted(
                records,
                lambda item: (
                    item.work_kind.value,
                    item.locator,
                    item.referenced_identity,
                ),
            ),
        )
        expected_counts = {
            WorkClassification.PRESENT.value: 0,
            WorkClassification.STALE.value: 0,
            WorkClassification.MISSING.value: 0,
            WorkClassification.HISTORY_ONLY.value: 0,
        }
        for record in self.records:
            expected_counts[record.classification.value] += 1
        supplied = self.counts if self.counts else expected_counts
        if not isinstance(supplied, Mapping):
            raise HistoryReconciliationError("counts must be an object")
        normalized_counts = {
            key: _nonnegative_int(supplied.get(key, 0), f"counts[{key}]")
            for key in expected_counts
        }
        if normalized_counts != expected_counts:
            raise HistoryReconciliationIdentityError(
                "counts must match classified records"
            )
        object.__setattr__(self, "counts", MappingProxyType(normalized_counts))
        if any(record.may_satisfy_completion for record in self.records):
            raise HistoryReconciliationError(
                "reconciliation records cannot satisfy completion"
            )
        _require_record_bound(self, artifact_name="history reconciliation report")

    @property
    def content_id(self) -> str:
        return self.record_content_id()

    @property
    def may_satisfy_completion(self) -> bool:
        return False

    @property
    def imported_history_is_authority(self) -> bool:
        return False

    def records_for(
        self, classification: WorkClassification
    ) -> tuple[WorkClassificationRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.classification is classification
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "imported_history_id": self.imported_history_id,
            "reconstructed_truth_id": self.reconstructed_truth_id,
            "quarantine_receipt_id": self.quarantine_receipt_id,
            "records": [item.to_dict() for item in self.records],
            "counts": dict(self.counts),
            "may_satisfy_completion": False,
            "imported_history_is_authority": False,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any] | HistoryReconciliationReport
    ) -> "HistoryReconciliationReport":
        if isinstance(payload, HistoryReconciliationReport):
            return payload
        if not isinstance(payload, Mapping):
            raise HistoryReconciliationError(
                "history reconciliation report must be an object"
            )
        _reject_forbidden_keys(payload, name="history reconciliation report")
        if payload.get("may_satisfy_completion") not in (None, False):
            raise HistoryReconciliationError(
                "history reconciliation cannot satisfy completion"
            )
        if payload.get("imported_history_is_authority") not in (None, False):
            raise HistoryReconciliationError("imported history cannot be authority")
        return cls(
            imported_history_id=payload.get("imported_history_id", ""),
            reconstructed_truth_id=payload.get("reconstructed_truth_id", ""),
            quarantine_receipt_id=payload.get("quarantine_receipt_id", ""),
            records=payload.get("records", ()),
            counts=payload.get("counts", {}),
        )


def reconcile_agent_history(
    imported: ImportedHistory | Mapping[str, Any],
    reconstructed: ReconstructedTruth | Mapping[str, Any],
) -> HistoryReconciliationReport:
    """Compare referenced work to reconstructed truth and classify each item.

    Classification is mutually exclusive per referenced identity:

    * present — exact identity in current reconstructed HEAD, refs, or overlay
    * stale — same locator in current reconstructed truth, different identity
    * history_only — identity exists only in reconstructed git history
    * missing — identity is absent from reconstructed current and history

    Stale takes precedence over history-only when a current locator still
    exists.  Present classifications are identity matches only; they never
    admit completion.
    """

    history = ImportedHistory.from_dict(imported)
    truth = ReconstructedTruth.from_dict(reconstructed)
    records = tuple(
        classify_referenced_work(item, truth) for item in history.referenced_items()
    )
    return HistoryReconciliationReport(
        imported_history_id=history.content_id,
        reconstructed_truth_id=truth.content_id,
        quarantine_receipt_id=truth.quarantine_receipt_id,
        records=records,
    )


__all__ = [
    "AGENT_HISTORY_RECONCILIATION_REPORT_INTERFACE",
    "AGENT_HISTORY_RECONCILIATION_REPORT_SCHEMA",
    "CONTRACT_VERSION",
    "SCHEMA_VERSION",
    "ClassificationReason",
    "ComparisonMethod",
    "FileSurface",
    "HistoryReconciliationBoundsError",
    "HistoryReconciliationError",
    "HistoryReconciliationIdentityError",
    "HistoryReconciliationReport",
    "ImportedHistory",
    "ProvenanceDomain",
    "ReconstructedCommit",
    "ReconstructedFile",
    "ReconstructedPatch",
    "ReconstructedTest",
    "ReconstructedTruth",
    "ReferencedCommit",
    "ReferencedFile",
    "ReferencedPatch",
    "ReferencedTest",
    "TrustClass",
    "WorkClassification",
    "WorkClassificationRecord",
    "WorkKind",
    "WorkProvenance",
    "canonical_json_bytes",
    "classify_referenced_work",
    "content_identity",
    "imported_provenance",
    "reconcile_agent_history",
    "reconstructed_provenance",
]
