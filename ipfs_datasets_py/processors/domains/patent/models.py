"""Strict public-patent value models for publication and prior-art records.

Canonical serialization boundary for public patent / publication data under
``processors.domains.patent``. Private application-status and matter-ledger
concerns live under ``processors.domains.uspto`` and are not modeled here.

Design rules
------------
* Stable record IDs are content-addressed from semantic identity only.
  Retrieval time, local path, access tokens, and mutable request URLs are
  never part of the identity payload.
* Unknown or non-public disclosure classifications fail closed: public-patent
  records reject them at construction time rather than defaulting to public.
* Models are pure value objects: no network I/O, storage backends, or secret
  resolution on import or construction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    is_public_classification,
    requires_quarantine,
)

MODELS_SCHEMA_VERSION: Final = "public-patent.models.v1"
MODELS_INTERFACE: Final = "PublicPatentModels@1"
CANONICAL_IDENTITY_VERSION: Final = "public-patent-canonical-identity-v1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_URN_ID_RE = re.compile(
    r"\Aurn:public-patent:[a-z][a-z0-9_-]*:sha256:[0-9a-f]{64}\Z"
)

# Observation / transport fields that must never influence stable identity.
_VOLATILE_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "auth_token",
        "authorization",
        "bearer_token",
        "cache_key",
        "downloaded_at",
        "local_path",
        "mutable_url",
        "path",
        "query_string",
        "request_url",
        "retrieved_at",
        "retrieval_path",
        "retrieval_utc",
        "session_token",
        "source_path",
        "storage_path",
        "token",
        "url",
    }
)


class PatentRecordKind(str, Enum):
    """Kinds of public-patent domain records."""

    PATENT = "patent"
    APPLICATION = "application"
    DOCUMENT = "document"
    CLAIM = "claim"
    PROSECUTION = "prosecution"
    REJECTION = "rejection"
    CITATION = "citation"


class ClaimKind(str, Enum):
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    UNKNOWN = "unknown"


class CitationKind(str, Enum):
    PATENT = "patent"
    PUBLICATION = "publication"
    NPL = "npl"
    UNKNOWN = "unknown"


class RejectionBasis(str, Enum):
    SECTION_101 = "101"
    SECTION_102 = "102"
    SECTION_103 = "103"
    SECTION_112 = "112"
    DOUBLE_PATENTING = "double_patenting"
    OTHER = "other"
    UNKNOWN = "unknown"


class CanonicalEncodingError(ValueError):
    """Raised when a value cannot be represented by the public-patent JSON profile."""


class DisclosurePolicyError(ValueError):
    """Raised when disclosure classification fails closed for public-patent models."""


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def content_digest(value: Any) -> str:
    """Return a tagged SHA-256 digest of a canonical JSON value."""
    return f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"


def deterministic_id(record_type: str, identity: Mapping[str, Any]) -> str:
    """Build a stable ID from semantic public-patent coordinates.

    Callers must omit observations such as retrieval time, filesystem path,
    access tokens, and mutable request URLs from *identity*.
    """
    if not record_type or not str(record_type).strip():
        raise CanonicalEncodingError("record_type must not be empty")
    cleaned = _strip_volatile_keys(dict(identity))
    payload = {
        "identity": cleaned,
        "identity_schema": CANONICAL_IDENTITY_VERSION,
        "record_type": record_type,
    }
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    return f"urn:public-patent:{record_type}:sha256:{digest}"


def _strip_volatile_keys(value: Any) -> Any:
    """Recursively drop transport/observation keys from identity payloads."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError("identity mapping keys must be strings")
            if key in _VOLATILE_IDENTITY_KEYS or key.lower() in _VOLATILE_IDENTITY_KEYS:
                continue
            out[key] = _strip_volatile_keys(item)
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_strip_volatile_keys(item) for item in value]
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"{label} has unknown fields: {', '.join(extra)}")


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _nonneg_int(value, field)


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=4096) for i, item in enumerate(value))


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise DisclosurePolicyError(
                f"unknown disclosure classification: {value!r}; "
                f"public-patent models fail closed and require an explicit "
                f"{DisclosureClassification.UNKNOWN.value!r} or public class"
            ) from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, got {type(value).__name__}"
    )


def enforce_public_disclosure(classification: DisclosureClassification | str) -> DisclosureClassification:
    """Fail closed unless *classification* is an allowed public class.

    Unknown (and any private class) is rejected so public-patent records never
    silently treat ambiguous content as publishable.
    """
    coerced = _coerce_classification(classification)
    if requires_quarantine(coerced):
        raise DisclosurePolicyError(
            "unknown disclosure classification fails closed; quarantine required "
            "before public-patent materialization"
        )
    if not is_public_classification(coerced):
        raise DisclosurePolicyError(
            f"non-public disclosure classification {coerced.value!r} is not "
            "permitted on public-patent models"
        )
    return coerced


def _validate_stable_id(value: str, record_type: str) -> str:
    text = _require_str(value, "stable_id", max_len=160)
    if not _URN_ID_RE.match(text):
        raise ValueError(f"stable_id is not a public-patent URN: {text!r}")
    expected_prefix = f"urn:public-patent:{record_type}:sha256:"
    if not text.startswith(expected_prefix):
        raise ValueError(
            f"stable_id record type mismatch: expected prefix {expected_prefix!r}"
        )
    return text


def _assert_schema(schema_version: str, label: str) -> str:
    text = _require_str(schema_version, "schema_version", max_len=64)
    if text != MODELS_SCHEMA_VERSION:
        raise ValueError(f"{label}.schema_version must be {MODELS_SCHEMA_VERSION}")
    return text


@dataclass(frozen=True, slots=True)
class PublicPatent:
    """Granted public patent publication record."""

    schema_version: str
    stable_id: str
    patent_number: str
    title: str
    classification: DisclosureClassification
    abstract: str | None = None
    grant_date: str | None = None
    application_number: str | None = None
    filing_date: str | None = None
    inventors: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    cpc_classifications: tuple[str, ...] = ()
    ipc_classifications: tuple[str, ...] = ()
    content_sha256: str | None = None
    # Observation-only fields (never identity):
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "application_number": self.application_number,
            "assignees": list(self.assignees),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "cpc_classifications": list(self.cpc_classifications),
            "filing_date": self.filing_date,
            "grant_date": self.grant_date,
            "inventors": list(self.inventors),
            "ipc_classifications": list(self.ipc_classifications),
            "patent_number": self.patent_number,
            "schema_version": self.schema_version,
            "title": self.title,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _assert_schema(self.schema_version, "PublicPatent")
        )
        object.__setattr__(
            self, "patent_number", _require_str(self.patent_number, "patent_number", max_len=64)
        )
        object.__setattr__(self, "title", _require_str(self.title, "title", max_len=2048))
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self, "abstract", _optional_str(self.abstract, "abstract", max_len=100_000)
        )
        object.__setattr__(
            self, "grant_date", _optional_str(self.grant_date, "grant_date", max_len=32)
        )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self, "filing_date", _optional_str(self.filing_date, "filing_date", max_len=32)
        )
        object.__setattr__(
            self, "inventors", _tuple_of_str(self.inventors, "inventors", max_items=512)
        )
        object.__setattr__(
            self, "assignees", _tuple_of_str(self.assignees, "assignees", max_items=128)
        )
        object.__setattr__(
            self,
            "cpc_classifications",
            _tuple_of_str(self.cpc_classifications, "cpc_classifications", max_items=256),
        )
        object.__setattr__(
            self,
            "ipc_classifications",
            _tuple_of_str(self.ipc_classifications, "ipc_classifications", max_items=256),
        )
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(PatentRecordKind.PATENT.value, self.identity_dict())
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.PATENT.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "access_token": self.access_token,
            "application_number": self.application_number,
            "assignees": list(self.assignees),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "cpc_classifications": list(self.cpc_classifications),
            "filing_date": self.filing_date,
            "grant_date": self.grant_date,
            "inventors": list(self.inventors),
            "ipc_classifications": list(self.ipc_classifications),
            "labels": dict(self.labels),
            "patent_number": self.patent_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicPatent":
        value = _mapping(value, "PublicPatent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "patent_number",
                    "title",
                    "classification",
                    "abstract",
                    "grant_date",
                    "application_number",
                    "filing_date",
                    "inventors",
                    "assignees",
                    "cpc_classifications",
                    "ipc_classifications",
                    "content_sha256",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "PublicPatent",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            patent_number=value.get("patent_number", ""),
            title=value.get("title", ""),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            abstract=value.get("abstract"),
            grant_date=value.get("grant_date"),
            application_number=value.get("application_number"),
            filing_date=value.get("filing_date"),
            inventors=tuple(value.get("inventors") or ()),
            assignees=tuple(value.get("assignees") or ()),
            cpc_classifications=tuple(value.get("cpc_classifications") or ()),
            ipc_classifications=tuple(value.get("ipc_classifications") or ()),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        patent_number: str,
        title: str,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        abstract: str | None = None,
        grant_date: str | None = None,
        application_number: str | None = None,
        filing_date: str | None = None,
        inventors: Sequence[str] = (),
        assignees: Sequence[str] = (),
        cpc_classifications: Sequence[str] = (),
        ipc_classifications: Sequence[str] = (),
        content_sha256: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "PublicPatent":
        """Construct a record with a content-derived stable_id."""
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",  # filled in __post_init__
            patent_number=patent_number,
            title=title,
            classification=classification,  # type: ignore[arg-type]
            abstract=abstract,
            grant_date=grant_date,
            application_number=application_number,
            filing_date=filing_date,
            inventors=tuple(inventors),
            assignees=tuple(assignees),
            cpc_classifications=tuple(cpc_classifications),
            ipc_classifications=tuple(ipc_classifications),
            content_sha256=content_sha256,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class PublicApplication:
    """Published patent application (pre-grant public disclosure)."""

    schema_version: str
    stable_id: str
    application_number: str
    title: str
    classification: DisclosureClassification
    publication_number: str | None = None
    publication_date: str | None = None
    filing_date: str | None = None
    abstract: str | None = None
    inventors: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    content_sha256: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "application_number": self.application_number,
            "assignees": list(self.assignees),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "filing_date": self.filing_date,
            "inventors": list(self.inventors),
            "publication_date": self.publication_date,
            "publication_number": self.publication_number,
            "schema_version": self.schema_version,
            "title": self.title,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _assert_schema(self.schema_version, "PublicApplication"),
        )
        object.__setattr__(
            self,
            "application_number",
            _require_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(self, "title", _require_str(self.title, "title", max_len=2048))
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "publication_number",
            _optional_str(self.publication_number, "publication_number", max_len=64),
        )
        object.__setattr__(
            self,
            "publication_date",
            _optional_str(self.publication_date, "publication_date", max_len=32),
        )
        object.__setattr__(
            self, "filing_date", _optional_str(self.filing_date, "filing_date", max_len=32)
        )
        object.__setattr__(
            self, "abstract", _optional_str(self.abstract, "abstract", max_len=100_000)
        )
        object.__setattr__(
            self, "inventors", _tuple_of_str(self.inventors, "inventors", max_items=512)
        )
        object.__setattr__(
            self, "assignees", _tuple_of_str(self.assignees, "assignees", max_items=128)
        )
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(
            PatentRecordKind.APPLICATION.value, self.identity_dict()
        )
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.APPLICATION.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "access_token": self.access_token,
            "application_number": self.application_number,
            "assignees": list(self.assignees),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "filing_date": self.filing_date,
            "inventors": list(self.inventors),
            "labels": dict(self.labels),
            "publication_date": self.publication_date,
            "publication_number": self.publication_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicApplication":
        value = _mapping(value, "PublicApplication")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "application_number",
                    "title",
                    "classification",
                    "publication_number",
                    "publication_date",
                    "filing_date",
                    "abstract",
                    "inventors",
                    "assignees",
                    "content_sha256",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "PublicApplication",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            application_number=value.get("application_number", ""),
            title=value.get("title", ""),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            publication_number=value.get("publication_number"),
            publication_date=value.get("publication_date"),
            filing_date=value.get("filing_date"),
            abstract=value.get("abstract"),
            inventors=tuple(value.get("inventors") or ()),
            assignees=tuple(value.get("assignees") or ()),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        application_number: str,
        title: str,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        publication_number: str | None = None,
        publication_date: str | None = None,
        filing_date: str | None = None,
        abstract: str | None = None,
        inventors: Sequence[str] = (),
        assignees: Sequence[str] = (),
        content_sha256: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "PublicApplication":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            application_number=application_number,
            title=title,
            classification=classification,  # type: ignore[arg-type]
            publication_number=publication_number,
            publication_date=publication_date,
            filing_date=filing_date,
            abstract=abstract,
            inventors=tuple(inventors),
            assignees=tuple(assignees),
            content_sha256=content_sha256,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class PatentDocument:
    """Public document belonging to a patent or published application."""

    schema_version: str
    stable_id: str
    document_code: str
    document_title: str
    classification: DisclosureClassification
    parent_patent_number: str | None = None
    parent_application_number: str | None = None
    media_type: str | None = None
    page_count: int | None = None
    content_sha256: str | None = None
    official_date: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "document_code": self.document_code,
            "document_title": self.document_title,
            "media_type": self.media_type,
            "official_date": self.official_date,
            "page_count": self.page_count,
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "schema_version": self.schema_version,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _assert_schema(self.schema_version, "PatentDocument")
        )
        object.__setattr__(
            self, "document_code", _require_str(self.document_code, "document_code", max_len=64)
        )
        object.__setattr__(
            self,
            "document_title",
            _require_str(self.document_title, "document_title", max_len=2048),
        )
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "parent_patent_number",
            _optional_str(self.parent_patent_number, "parent_patent_number", max_len=64),
        )
        object.__setattr__(
            self,
            "parent_application_number",
            _optional_str(
                self.parent_application_number, "parent_application_number", max_len=64
            ),
        )
        if not any((self.parent_patent_number, self.parent_application_number)):
            raise ValueError(
                "PatentDocument requires parent_patent_number or parent_application_number"
            )
        object.__setattr__(
            self, "media_type", _optional_str(self.media_type, "media_type", max_len=256)
        )
        object.__setattr__(self, "page_count", _optional_int(self.page_count, "page_count"))
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "official_date", _optional_str(self.official_date, "official_date", max_len=32)
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(PatentRecordKind.DOCUMENT.value, self.identity_dict())
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.DOCUMENT.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "document_code": self.document_code,
            "document_title": self.document_title,
            "labels": dict(self.labels),
            "media_type": self.media_type,
            "official_date": self.official_date,
            "page_count": self.page_count,
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentDocument":
        value = _mapping(value, "PatentDocument")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "document_code",
                    "document_title",
                    "classification",
                    "parent_patent_number",
                    "parent_application_number",
                    "media_type",
                    "page_count",
                    "content_sha256",
                    "official_date",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "PatentDocument",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            document_code=value.get("document_code", ""),
            document_title=value.get("document_title", ""),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            parent_patent_number=value.get("parent_patent_number"),
            parent_application_number=value.get("parent_application_number"),
            media_type=value.get("media_type"),
            page_count=value.get("page_count"),
            content_sha256=value.get("content_sha256"),
            official_date=value.get("official_date"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        document_code: str,
        document_title: str,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        parent_patent_number: str | None = None,
        parent_application_number: str | None = None,
        media_type: str | None = None,
        page_count: int | None = None,
        content_sha256: str | None = None,
        official_date: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "PatentDocument":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            document_code=document_code,
            document_title=document_title,
            classification=classification,  # type: ignore[arg-type]
            parent_patent_number=parent_patent_number,
            parent_application_number=parent_application_number,
            media_type=media_type,
            page_count=page_count,
            content_sha256=content_sha256,
            official_date=official_date,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class PatentClaim:
    """Single claim of a public patent or published application."""

    schema_version: str
    stable_id: str
    claim_number: int
    claim_text: str
    claim_kind: ClaimKind
    classification: DisclosureClassification
    parent_patent_number: str | None = None
    parent_application_number: str | None = None
    depends_on: tuple[int, ...] = ()
    content_sha256: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "claim_kind": self.claim_kind.value,
            "claim_number": self.claim_number,
            "claim_text": self.claim_text,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "depends_on": list(self.depends_on),
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "schema_version": self.schema_version,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _assert_schema(self.schema_version, "PatentClaim")
        )
        object.__setattr__(
            self, "claim_number", _nonneg_int(self.claim_number, "claim_number")
        )
        if self.claim_number < 1:
            raise ValueError("claim_number must be >= 1")
        object.__setattr__(
            self, "claim_text", _require_str(self.claim_text, "claim_text", max_len=200_000)
        )
        object.__setattr__(
            self, "claim_kind", _coerce_enum(ClaimKind, self.claim_kind, "claim_kind")
        )
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "parent_patent_number",
            _optional_str(self.parent_patent_number, "parent_patent_number", max_len=64),
        )
        object.__setattr__(
            self,
            "parent_application_number",
            _optional_str(
                self.parent_application_number, "parent_application_number", max_len=64
            ),
        )
        if not any((self.parent_patent_number, self.parent_application_number)):
            raise ValueError(
                "PatentClaim requires parent_patent_number or parent_application_number"
            )
        if self.depends_on is None:
            deps: tuple[int, ...] = ()
        else:
            if not isinstance(self.depends_on, Sequence) or isinstance(
                self.depends_on, (str, bytes)
            ):
                raise TypeError("depends_on must be a sequence of ints")
            deps = tuple(_nonneg_int(x, f"depends_on[{i}]") for i, x in enumerate(self.depends_on))
            if any(d < 1 for d in deps):
                raise ValueError("depends_on entries must be >= 1")
        object.__setattr__(self, "depends_on", deps)
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(PatentRecordKind.CLAIM.value, self.identity_dict())
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.CLAIM.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "claim_kind": self.claim_kind.value,
            "claim_number": self.claim_number,
            "claim_text": self.claim_text,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "depends_on": list(self.depends_on),
            "labels": dict(self.labels),
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentClaim":
        value = _mapping(value, "PatentClaim")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "claim_number",
                    "claim_text",
                    "claim_kind",
                    "classification",
                    "parent_patent_number",
                    "parent_application_number",
                    "depends_on",
                    "content_sha256",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "PatentClaim",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            claim_number=value.get("claim_number", 0),
            claim_text=value.get("claim_text", ""),
            claim_kind=value.get("claim_kind", ClaimKind.UNKNOWN.value),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            parent_patent_number=value.get("parent_patent_number"),
            parent_application_number=value.get("parent_application_number"),
            depends_on=tuple(value.get("depends_on") or ()),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        claim_number: int,
        claim_text: str,
        claim_kind: ClaimKind | str = ClaimKind.UNKNOWN,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        parent_patent_number: str | None = None,
        parent_application_number: str | None = None,
        depends_on: Sequence[int] = (),
        content_sha256: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "PatentClaim":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            claim_number=claim_number,
            claim_text=claim_text,
            claim_kind=claim_kind,  # type: ignore[arg-type]
            classification=classification,  # type: ignore[arg-type]
            parent_patent_number=parent_patent_number,
            parent_application_number=parent_application_number,
            depends_on=tuple(depends_on),
            content_sha256=content_sha256,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class ProsecutionEvent:
    """Public prosecution timeline event for a patent matter."""

    schema_version: str
    stable_id: str
    event_code: str
    event_description: str
    event_date: str
    classification: DisclosureClassification
    parent_patent_number: str | None = None
    parent_application_number: str | None = None
    sequence: int | None = None
    content_sha256: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "event_code": self.event_code,
            "event_date": self.event_date,
            "event_description": self.event_description,
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _assert_schema(self.schema_version, "ProsecutionEvent"),
        )
        object.__setattr__(
            self, "event_code", _require_str(self.event_code, "event_code", max_len=64)
        )
        object.__setattr__(
            self,
            "event_description",
            _require_str(self.event_description, "event_description", max_len=4096),
        )
        object.__setattr__(
            self, "event_date", _require_str(self.event_date, "event_date", max_len=32)
        )
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "parent_patent_number",
            _optional_str(self.parent_patent_number, "parent_patent_number", max_len=64),
        )
        object.__setattr__(
            self,
            "parent_application_number",
            _optional_str(
                self.parent_application_number, "parent_application_number", max_len=64
            ),
        )
        if not any((self.parent_patent_number, self.parent_application_number)):
            raise ValueError(
                "ProsecutionEvent requires parent_patent_number or parent_application_number"
            )
        object.__setattr__(self, "sequence", _optional_int(self.sequence, "sequence"))
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(
            PatentRecordKind.PROSECUTION.value, self.identity_dict()
        )
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.PROSECUTION.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "event_code": self.event_code,
            "event_date": self.event_date,
            "event_description": self.event_description,
            "labels": dict(self.labels),
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProsecutionEvent":
        value = _mapping(value, "ProsecutionEvent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "event_code",
                    "event_description",
                    "event_date",
                    "classification",
                    "parent_patent_number",
                    "parent_application_number",
                    "sequence",
                    "content_sha256",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "ProsecutionEvent",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            event_code=value.get("event_code", ""),
            event_description=value.get("event_description", ""),
            event_date=value.get("event_date", ""),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            parent_patent_number=value.get("parent_patent_number"),
            parent_application_number=value.get("parent_application_number"),
            sequence=value.get("sequence"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        event_code: str,
        event_description: str,
        event_date: str,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        parent_patent_number: str | None = None,
        parent_application_number: str | None = None,
        sequence: int | None = None,
        content_sha256: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "ProsecutionEvent":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            event_code=event_code,
            event_description=event_description,
            event_date=event_date,
            classification=classification,  # type: ignore[arg-type]
            parent_patent_number=parent_patent_number,
            parent_application_number=parent_application_number,
            sequence=sequence,
            content_sha256=content_sha256,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class Rejection:
    """Public office-action rejection reference."""

    schema_version: str
    stable_id: str
    basis: RejectionBasis
    claim_numbers: tuple[int, ...]
    classification: DisclosureClassification
    parent_patent_number: str | None = None
    parent_application_number: str | None = None
    description: str | None = None
    cited_references: tuple[str, ...] = ()
    content_sha256: str | None = None
    official_date: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis.value,
            "cited_references": list(self.cited_references),
            "claim_numbers": list(self.claim_numbers),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "description": self.description,
            "official_date": self.official_date,
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "schema_version": self.schema_version,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _assert_schema(self.schema_version, "Rejection")
        )
        object.__setattr__(
            self, "basis", _coerce_enum(RejectionBasis, self.basis, "basis")
        )
        if self.claim_numbers is None:
            claims: tuple[int, ...] = ()
        else:
            if not isinstance(self.claim_numbers, Sequence) or isinstance(
                self.claim_numbers, (str, bytes)
            ):
                raise TypeError("claim_numbers must be a sequence of ints")
            claims = tuple(
                _nonneg_int(x, f"claim_numbers[{i}]")
                for i, x in enumerate(self.claim_numbers)
            )
            if any(c < 1 for c in claims):
                raise ValueError("claim_numbers entries must be >= 1")
        object.__setattr__(self, "claim_numbers", claims)
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "parent_patent_number",
            _optional_str(self.parent_patent_number, "parent_patent_number", max_len=64),
        )
        object.__setattr__(
            self,
            "parent_application_number",
            _optional_str(
                self.parent_application_number, "parent_application_number", max_len=64
            ),
        )
        if not any((self.parent_patent_number, self.parent_application_number)):
            raise ValueError(
                "Rejection requires parent_patent_number or parent_application_number"
            )
        object.__setattr__(
            self, "description", _optional_str(self.description, "description", max_len=20_000)
        )
        object.__setattr__(
            self,
            "cited_references",
            _tuple_of_str(self.cited_references, "cited_references", max_items=512),
        )
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "official_date", _optional_str(self.official_date, "official_date", max_len=32)
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(PatentRecordKind.REJECTION.value, self.identity_dict())
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.REJECTION.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "basis": self.basis.value,
            "cited_references": list(self.cited_references),
            "claim_numbers": list(self.claim_numbers),
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "description": self.description,
            "labels": dict(self.labels),
            "official_date": self.official_date,
            "parent_application_number": self.parent_application_number,
            "parent_patent_number": self.parent_patent_number,
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Rejection":
        value = _mapping(value, "Rejection")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "basis",
                    "claim_numbers",
                    "classification",
                    "parent_patent_number",
                    "parent_application_number",
                    "description",
                    "cited_references",
                    "content_sha256",
                    "official_date",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "Rejection",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            basis=value.get("basis", RejectionBasis.UNKNOWN.value),
            claim_numbers=tuple(value.get("claim_numbers") or ()),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            parent_patent_number=value.get("parent_patent_number"),
            parent_application_number=value.get("parent_application_number"),
            description=value.get("description"),
            cited_references=tuple(value.get("cited_references") or ()),
            content_sha256=value.get("content_sha256"),
            official_date=value.get("official_date"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        basis: RejectionBasis | str,
        claim_numbers: Sequence[int],
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        parent_patent_number: str | None = None,
        parent_application_number: str | None = None,
        description: str | None = None,
        cited_references: Sequence[str] = (),
        content_sha256: str | None = None,
        official_date: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "Rejection":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            basis=basis,  # type: ignore[arg-type]
            claim_numbers=tuple(claim_numbers),
            classification=classification,  # type: ignore[arg-type]
            parent_patent_number=parent_patent_number,
            parent_application_number=parent_application_number,
            description=description,
            cited_references=tuple(cited_references),
            content_sha256=content_sha256,
            official_date=official_date,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class Citation:
    """Prior-art or backward/forward citation on a public patent record."""

    schema_version: str
    stable_id: str
    citation_kind: CitationKind
    cited_id: str
    classification: DisclosureClassification
    citing_patent_number: str | None = None
    citing_application_number: str | None = None
    cited_title: str | None = None
    category: str | None = None
    content_sha256: str | None = None
    retrieved_at: str | None = None
    source_path: str | None = None
    request_url: str | None = None
    access_token: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def identity_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "citation_kind": self.citation_kind.value,
            "cited_id": self.cited_id,
            "cited_title": self.cited_title,
            "citing_application_number": self.citing_application_number,
            "citing_patent_number": self.citing_patent_number,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "schema_version": self.schema_version,
        }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _assert_schema(self.schema_version, "Citation")
        )
        object.__setattr__(
            self,
            "citation_kind",
            _coerce_enum(CitationKind, self.citation_kind, "citation_kind"),
        )
        object.__setattr__(
            self, "cited_id", _require_str(self.cited_id, "cited_id", max_len=256)
        )
        object.__setattr__(
            self, "classification", enforce_public_disclosure(self.classification)
        )
        object.__setattr__(
            self,
            "citing_patent_number",
            _optional_str(self.citing_patent_number, "citing_patent_number", max_len=64),
        )
        object.__setattr__(
            self,
            "citing_application_number",
            _optional_str(
                self.citing_application_number, "citing_application_number", max_len=64
            ),
        )
        if not any((self.citing_patent_number, self.citing_application_number)):
            raise ValueError(
                "Citation requires citing_patent_number or citing_application_number"
            )
        object.__setattr__(
            self, "cited_title", _optional_str(self.cited_title, "cited_title", max_len=2048)
        )
        object.__setattr__(
            self, "category", _optional_str(self.category, "category", max_len=64)
        )
        object.__setattr__(
            self, "content_sha256", _sha256_hex(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "retrieved_at", _optional_str(self.retrieved_at, "retrieved_at", max_len=64)
        )
        object.__setattr__(
            self, "source_path", _optional_str(self.source_path, "source_path", max_len=4096)
        )
        object.__setattr__(
            self, "request_url", _optional_str(self.request_url, "request_url", max_len=4096)
        )
        object.__setattr__(
            self, "access_token", _optional_str(self.access_token, "access_token", max_len=4096)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

        expected = deterministic_id(PatentRecordKind.CITATION.value, self.identity_dict())
        provided = _optional_str(self.stable_id, "stable_id", max_len=160)
        if provided is None:
            object.__setattr__(self, "stable_id", expected)
        else:
            validated = _validate_stable_id(provided, PatentRecordKind.CITATION.value)
            if validated != expected:
                raise ValueError(
                    "stable_id does not match content identity; "
                    "retrieval metadata must not alter public-patent IDs"
                )
            object.__setattr__(self, "stable_id", validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "category": self.category,
            "citation_kind": self.citation_kind.value,
            "cited_id": self.cited_id,
            "cited_title": self.cited_title,
            "citing_application_number": self.citing_application_number,
            "citing_patent_number": self.citing_patent_number,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "labels": dict(self.labels),
            "request_url": self.request_url,
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "stable_id": self.stable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Citation":
        value = _mapping(value, "Citation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "stable_id",
                    "citation_kind",
                    "cited_id",
                    "classification",
                    "citing_patent_number",
                    "citing_application_number",
                    "cited_title",
                    "category",
                    "content_sha256",
                    "retrieved_at",
                    "source_path",
                    "request_url",
                    "access_token",
                    "labels",
                }
            ),
            "Citation",
        )
        return cls(
            schema_version=value.get("schema_version", MODELS_SCHEMA_VERSION),
            stable_id=value.get("stable_id") or "",
            citation_kind=value.get("citation_kind", CitationKind.UNKNOWN.value),
            cited_id=value.get("cited_id", ""),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_OFFICIAL.value
            ),
            citing_patent_number=value.get("citing_patent_number"),
            citing_application_number=value.get("citing_application_number"),
            cited_title=value.get("cited_title"),
            category=value.get("category"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            source_path=value.get("source_path"),
            request_url=value.get("request_url"),
            access_token=value.get("access_token"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def build(
        cls,
        *,
        citation_kind: CitationKind | str,
        cited_id: str,
        classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_OFFICIAL,
        citing_patent_number: str | None = None,
        citing_application_number: str | None = None,
        cited_title: str | None = None,
        category: str | None = None,
        content_sha256: str | None = None,
        retrieved_at: str | None = None,
        source_path: str | None = None,
        request_url: str | None = None,
        access_token: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "Citation":
        return cls(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="",
            citation_kind=citation_kind,  # type: ignore[arg-type]
            cited_id=cited_id,
            classification=classification,  # type: ignore[arg-type]
            citing_patent_number=citing_patent_number,
            citing_application_number=citing_application_number,
            cited_title=cited_title,
            category=category,
            content_sha256=content_sha256,
            retrieved_at=retrieved_at,
            source_path=source_path,
            request_url=request_url,
            access_token=access_token,
            labels=labels or {},
        )


__all__ = [
    "CANONICAL_IDENTITY_VERSION",
    "MODELS_INTERFACE",
    "MODELS_SCHEMA_VERSION",
    "CanonicalEncodingError",
    "Citation",
    "CitationKind",
    "ClaimKind",
    "DisclosureClassification",
    "DisclosurePolicyError",
    "PatentClaim",
    "PatentDocument",
    "PatentRecordKind",
    "ProsecutionEvent",
    "PublicApplication",
    "PublicPatent",
    "Rejection",
    "RejectionBasis",
    "canonical_json",
    "canonical_json_bytes",
    "content_digest",
    "deterministic_id",
    "enforce_public_disclosure",
]
