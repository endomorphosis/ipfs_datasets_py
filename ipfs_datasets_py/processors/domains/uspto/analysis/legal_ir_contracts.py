"""Exact USPTO span, authority, fact, and Legal IR boundary contracts (PATLAW-122).

Versioned, immutable mapping contracts between USPTO extraction/authority
records and Legal IR inputs. These contracts:

* preserve exact source identity and temporal/disclosure metadata on round trip;
* reject or mark unknown any invalid or ambiguous mapping;
* distinguish quoted text, deterministic normalization, model candidates,
  human findings, and proven conclusions as mutually exclusive assertion kinds.

This module owns the versioned boundary only. It does not invoke the shared
Legal IR compiler or proof engine, infer missing source spans, or promote
guidance to binding authority.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json,
    requires_quarantine,
)

LEGAL_IR_CONTRACTS_SCHEMA_VERSION: Final = "uspto.legal-ir-contracts.v1"
LEGAL_IR_CONTRACTS_INTERFACE: Final = "UsptoLegalIRContracts@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_DATE_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?\Z"
)

# Authority ranks that may never stand alone as binding for proven conclusions.
_NON_BINDING_AUTHORITY_RANKS: Final[frozenset[str]] = frozenset(
    {
        "guidance",
        "candidate",
        "unknown",
        "unofficial-current",
    }
)

# Assertion kinds that are never proof-grade without an explicit proof receipt.
_NON_PROVEN_ASSERTION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "quoted_text",
        "deterministic_normalization",
        "model_candidate",
        "human_finding",
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AssertionKind(str, Enum):
    """Mutually exclusive provenance class for a Legal IR-bound assertion.

    Schemas must keep these kinds distinct so consumers never treat model
    output as quoted government text, or quoted text as a proved conclusion.
    """

    QUOTED_TEXT = "quoted_text"
    DETERMINISTIC_NORMALIZATION = "deterministic_normalization"
    MODEL_CANDIDATE = "model_candidate"
    HUMAN_FINDING = "human_finding"
    PROVEN_CONCLUSION = "proven_conclusion"


class MappingStatus(str, Enum):
    """Outcome of validating one USPTO→Legal IR mapping."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class TriStateOutcome(str, Enum):
    """Fail-closed tri-state result for obligations and assessments."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


class LegalModality(str, Enum):
    """Deontic / definitional force of a normalized proposition."""

    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    POWER = "power"
    EXCEPTION = "exception"
    DEFINITION = "definition"
    ASSERTION = "assertion"
    UNKNOWN = "unknown"


class ActorRole(str, Enum):
    """Role of an actor referenced by a proposition or fact."""

    EXAMINER = "examiner"
    APPLICANT = "applicant"
    USPTO = "uspto"
    COURT = "court"
    THIRD_PARTY = "third_party"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class AuthorityRank(str, Enum):
    """Authority weight for a citation or snapshot (independent of relevance).

    Guidance and candidates are never binding authority. Official base and
    official change may support binding conclusions only when fully resolved.
    """

    OFFICIAL_BASE = "official-base"
    OFFICIAL_CHANGE = "official-change"
    UNOFFICIAL_CURRENT = "unofficial-current"
    GUIDANCE = "guidance"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"


class AuthorityResolutionState(str, Enum):
    """Resolution state for temporal/authority lookup."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"
    STALE = "stale"
    UNKNOWN = "unknown"


class MappingReasonCode(str, Enum):
    """Stable machine-readable reason codes for mapping decisions."""

    VALID_MAPPING = "valid_mapping"
    MISSING_SOURCE_SPAN = "missing_source_span"
    INVALID_SOURCE_SPAN = "invalid_source_span"
    MISSING_SOURCE_IDENTITY = "missing_source_identity"
    MISSING_TEMPORAL_METADATA = "missing_temporal_metadata"
    AMBIGUOUS_AUTHORITY = "ambiguous_authority"
    UNRESOLVED_AUTHORITY = "unresolved_authority"
    GUIDANCE_NOT_BINDING = "guidance_not_binding"
    MODEL_CANDIDATE_NOT_PROVEN = "model_candidate_not_proven"
    PROOF_RECEIPT_REQUIRED = "proof_receipt_required"
    PROOF_RECEIPT_MISSING = "proof_receipt_missing"
    ASSERTION_KIND_MISMATCH = "assertion_kind_mismatch"
    QUOTE_DIGEST_REQUIRED = "quote_digest_required"
    NORMALIZER_IDENTITY_REQUIRED = "normalizer_identity_required"
    REVIEWER_IDENTITY_REQUIRED = "reviewer_identity_required"
    DISCLOSURE_QUARANTINE = "disclosure_quarantine"
    UNKNOWN_FIELDS = "unknown_fields"
    INVALID_ENUM = "invalid_enum"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    COUNTER_EVIDENCE_RECORDED = "counter_evidence_recorded"
    ASSUMPTION_RECORDED = "assumption_recorded"
    DEADLINE_AMBIGUOUS = "deadline_ambiguous"
    CONDITION_UNRESOLVED = "condition_unresolved"
    DUPLICATE_MAPPING_ID = "duplicate_mapping_id"
    FACT_SPAN_UNRESOLVED = "fact_span_unresolved"
    CITATION_UNRESOLVED = "citation_unresolved"


class LegalIRContractError(ValueError):
    """Bounded contract violation with a stable machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str | MappingReasonCode = MappingReasonCode.INVALID_ENUM,
    ) -> None:
        super().__init__(message)
        if isinstance(code, MappingReasonCode):
            self.code = code.value
        else:
            self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        # Never include document body text.
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise LegalIRContractError(
            f"{label} has unknown fields: {', '.join(extra)}",
            code=MappingReasonCode.UNKNOWN_FIELDS,
        )


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
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256_hex(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    return _sha256_hex(text, field)


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _optional_nonneg_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _nonneg_int(value, field)


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    number = float(value)
    if number != number or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise LegalIRContractError(
                f"invalid {field}: {value!r}",
                code=MappingReasonCode.INVALID_ENUM,
            ) from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise LegalIRContractError(
                f"unknown disclosure classification: {value!r}",
                code=MappingReasonCode.INVALID_ENUM,
            ) from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, got {type(value).__name__}"
    )


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        out.append(_require_str(item, f"{field}[{i}]", max_len=2048))
    return tuple(out)


def _tuple_of_identifiers(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of identifiers")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        out.append(_identifier(item, f"{field}[{i}]"))
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
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


def _optional_temporal_token(value: Any, field: str) -> str | None:
    """Validate an optional ISO-8601 date or datetime token (opaque string)."""
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 date or datetime, got {text!r}")
    return text


def is_binding_authority_rank(rank: AuthorityRank | str) -> bool:
    """Return True only for official base/change ranks (never guidance)."""
    coerced = _coerce_enum(AuthorityRank, rank, "authority_rank")
    assert isinstance(coerced, AuthorityRank)
    return coerced.value not in _NON_BINDING_AUTHORITY_RANKS


def assertion_kind_may_be_proven(kind: AssertionKind | str) -> bool:
    """Return True only for the proven_conclusion assertion kind."""
    coerced = _coerce_enum(AssertionKind, kind, "assertion_kind")
    assert isinstance(coerced, AssertionKind)
    return coerced.value not in _NON_PROVEN_ASSERTION_KINDS


# ---------------------------------------------------------------------------
# Core identity and metadata records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Exact, content-addressed identity of a USPTO source artifact.

    Round trips must preserve every field so Legal IR consumers can re-bind
    to the same bytes without inference.
    """

    schema_version: str
    artifact_id: str
    content_digest: str
    media_type: str | None
    private_cid: str | None
    public_cid: str | None
    parser_version: str | None
    source_receipt_id: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"SourceIdentity.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "media_type",
            _optional_str(self.media_type, "media_type", max_len=128),
        )
        object.__setattr__(
            self,
            "private_cid",
            _optional_str(self.private_cid, "private_cid", max_len=128),
        )
        object.__setattr__(
            self,
            "public_cid",
            _optional_str(self.public_cid, "public_cid", max_len=128),
        )
        object.__setattr__(
            self,
            "parser_version",
            _optional_str(self.parser_version, "parser_version", max_len=128),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "labels": dict(self.labels),
            "media_type": self.media_type,
            "parser_version": self.parser_version,
            "private_cid": self.private_cid,
            "public_cid": self.public_cid,
            "schema_version": self.schema_version,
            "source_receipt_id": self.source_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceIdentity":
        value = _mapping(value, "SourceIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "artifact_id",
                    "content_digest",
                    "media_type",
                    "private_cid",
                    "public_cid",
                    "parser_version",
                    "source_receipt_id",
                    "labels",
                }
            ),
            "SourceIdentity",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            artifact_id=value.get("artifact_id", ""),
            content_digest=value.get("content_digest", ""),
            media_type=value.get("media_type"),
            private_cid=value.get("private_cid"),
            public_cid=value.get("public_cid"),
            parser_version=value.get("parser_version"),
            source_receipt_id=value.get("source_receipt_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class TemporalMetadata:
    """Time-versioned metadata that must survive Legal IR round trips."""

    schema_version: str
    as_of: str | None
    effective_start: str | None
    effective_end: str | None
    retrieval_utc: str | None
    edition_or_version: str | None
    release_point: str | None
    jurisdiction: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"TemporalMetadata.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(self, "as_of", _optional_temporal_token(self.as_of, "as_of"))
        object.__setattr__(
            self,
            "effective_start",
            _optional_temporal_token(self.effective_start, "effective_start"),
        )
        object.__setattr__(
            self,
            "effective_end",
            _optional_temporal_token(self.effective_end, "effective_end"),
        )
        object.__setattr__(
            self,
            "retrieval_utc",
            _optional_temporal_token(self.retrieval_utc, "retrieval_utc"),
        )
        edition = _optional_str(
            self.edition_or_version, "edition_or_version", max_len=128
        )
        if edition is not None and edition.strip().lower() == "latest":
            raise LegalIRContractError(
                "edition_or_version must not be the hard-coded token 'latest'",
                code=MappingReasonCode.MISSING_TEMPORAL_METADATA,
            )
        object.__setattr__(self, "edition_or_version", edition)
        object.__setattr__(
            self,
            "release_point",
            _optional_str(self.release_point, "release_point", max_len=128),
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _optional_str(self.jurisdiction, "jurisdiction", max_len=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        if (
            self.effective_start is not None
            and self.effective_end is not None
            and self.effective_end < self.effective_start
        ):
            raise ValueError("effective_end must be >= effective_start")

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.as_of,
                self.effective_start,
                self.effective_end,
                self.retrieval_utc,
                self.edition_or_version,
                self.release_point,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "edition_or_version": self.edition_or_version,
            "effective_end": self.effective_end,
            "effective_start": self.effective_start,
            "jurisdiction": self.jurisdiction,
            "labels": dict(self.labels),
            "release_point": self.release_point,
            "retrieval_utc": self.retrieval_utc,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TemporalMetadata":
        value = _mapping(value, "TemporalMetadata")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "as_of",
                    "effective_start",
                    "effective_end",
                    "retrieval_utc",
                    "edition_or_version",
                    "release_point",
                    "jurisdiction",
                    "labels",
                }
            ),
            "TemporalMetadata",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            as_of=value.get("as_of"),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            retrieval_utc=value.get("retrieval_utc"),
            edition_or_version=value.get("edition_or_version"),
            release_point=value.get("release_point"),
            jurisdiction=value.get("jurisdiction"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DisclosureMetadata:
    """Disclosure / quarantine metadata preserved across the Legal IR boundary."""

    schema_version: str
    classification: DisclosureClassification
    quarantine_required: bool
    redaction_policy_id: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"DisclosureMetadata.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        classification = _coerce_classification(self.classification)
        object.__setattr__(self, "classification", classification)
        # Fail closed: unknown classification always requires quarantine.
        must_quarantine = requires_quarantine(classification)
        if not isinstance(self.quarantine_required, bool):
            raise TypeError("quarantine_required must be bool")
        if must_quarantine and not self.quarantine_required:
            object.__setattr__(self, "quarantine_required", True)
        object.__setattr__(
            self,
            "redaction_policy_id",
            _optional_identifier(self.redaction_policy_id, "redaction_policy_id"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "labels": dict(self.labels),
            "quarantine_required": self.quarantine_required,
            "redaction_policy_id": self.redaction_policy_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DisclosureMetadata":
        value = _mapping(value, "DisclosureMetadata")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "classification",
                    "quarantine_required",
                    "redaction_policy_id",
                    "labels",
                }
            ),
            "DisclosureMetadata",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            quarantine_required=bool(value.get("quarantine_required", False)),
            redaction_policy_id=value.get("redaction_policy_id"),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Span, citation, authority, proposition, fact records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsptoSpanRef:
    """Exact span anchor for Legal IR binding (identifiers and digests only).

    Document body text is intentionally excluded. Quoted content is bound by
    ``text_digest`` plus ``SourceIdentity`` / ``TemporalMetadata``.
    """

    schema_version: str
    span_id: str
    artifact_id: str
    page_index: int | None
    char_start: int | None
    char_end: int | None
    text_digest: str | None
    image_digest: str | None
    reading_order: int | None
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"UsptoSpanRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "page_index", _optional_nonneg_int(self.page_index, "page_index")
        )
        object.__setattr__(
            self, "char_start", _optional_nonneg_int(self.char_start, "char_start")
        )
        object.__setattr__(
            self, "char_end", _optional_nonneg_int(self.char_end, "char_end")
        )
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be >= char_start")
        object.__setattr__(
            self, "text_digest", _optional_sha256_hex(self.text_digest, "text_digest")
        )
        object.__setattr__(
            self,
            "image_digest",
            _optional_sha256_hex(self.image_digest, "image_digest"),
        )
        object.__setattr__(
            self,
            "reading_order",
            _optional_nonneg_int(self.reading_order, "reading_order"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "char_end": self.char_end,
            "char_start": self.char_start,
            "classification": self.classification.value,
            "image_digest": self.image_digest,
            "page_index": self.page_index,
            "reading_order": self.reading_order,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UsptoSpanRef":
        value = _mapping(value, "UsptoSpanRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "span_id",
                    "artifact_id",
                    "page_index",
                    "char_start",
                    "char_end",
                    "text_digest",
                    "image_digest",
                    "reading_order",
                    "classification",
                }
            ),
            "UsptoSpanRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            page_index=value.get("page_index"),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
            text_digest=value.get("text_digest"),
            image_digest=value.get("image_digest"),
            reading_order=value.get("reading_order"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class CitationRef:
    """Citation surface bound to authority rank and temporal edition identity."""

    schema_version: str
    citation_id: str
    surface: str
    citation_key: str | None
    authority_rank: AuthorityRank
    family: str | None
    edition_or_version: str | None
    node_id: str | None
    quote_text_digest: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"CitationRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "citation_id", _identifier(self.citation_id, "citation_id")
        )
        object.__setattr__(
            self, "surface", _require_str(self.surface, "surface", max_len=512)
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self,
            "authority_rank",
            _coerce_enum(AuthorityRank, self.authority_rank, "authority_rank"),
        )
        object.__setattr__(
            self, "family", _optional_str(self.family, "family", max_len=64)
        )
        edition = _optional_str(
            self.edition_or_version, "edition_or_version", max_len=128
        )
        if edition is not None and edition.strip().lower() == "latest":
            raise LegalIRContractError(
                "edition_or_version must not be the hard-coded token 'latest'",
                code=MappingReasonCode.MISSING_TEMPORAL_METADATA,
            )
        object.__setattr__(self, "edition_or_version", edition)
        object.__setattr__(
            self, "node_id", _optional_identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "quote_text_digest",
            _optional_sha256_hex(self.quote_text_digest, "quote_text_digest"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_rank": self.authority_rank.value,
            "citation_id": self.citation_id,
            "citation_key": self.citation_key,
            "edition_or_version": self.edition_or_version,
            "family": self.family,
            "labels": dict(self.labels),
            "node_id": self.node_id,
            "quote_text_digest": self.quote_text_digest,
            "schema_version": self.schema_version,
            "surface": self.surface,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CitationRef":
        value = _mapping(value, "CitationRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "citation_id",
                    "surface",
                    "citation_key",
                    "authority_rank",
                    "family",
                    "edition_or_version",
                    "node_id",
                    "quote_text_digest",
                    "labels",
                }
            ),
            "CitationRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            citation_id=value.get("citation_id", ""),
            surface=value.get("surface", ""),
            citation_key=value.get("citation_key"),
            authority_rank=value.get("authority_rank", AuthorityRank.UNKNOWN.value),
            family=value.get("family"),
            edition_or_version=value.get("edition_or_version"),
            node_id=value.get("node_id"),
            quote_text_digest=value.get("quote_text_digest"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class AuthorityBinding:
    """Resolved (or explicitly unresolved) authority for a mapping."""

    schema_version: str
    binding_id: str
    state: AuthorityResolutionState
    authority_rank: AuthorityRank
    temporal: TemporalMetadata
    citation_ids: tuple[str, ...]
    selected_node_ids: tuple[str, ...]
    selected_versions: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"AuthorityBinding.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self, "state", _coerce_enum(AuthorityResolutionState, self.state, "state")
        )
        object.__setattr__(
            self,
            "authority_rank",
            _coerce_enum(AuthorityRank, self.authority_rank, "authority_rank"),
        )
        if not isinstance(self.temporal, TemporalMetadata):
            raise TypeError("temporal must be TemporalMetadata")
        object.__setattr__(
            self,
            "citation_ids",
            _tuple_of_identifiers(self.citation_ids, "citation_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "selected_node_ids",
            _tuple_of_identifiers(
                self.selected_node_ids, "selected_node_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "selected_versions",
            _tuple_of_str(self.selected_versions, "selected_versions", max_items=64),
        )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=32)
        )
        # Guidance is never binding even if state is RESOLVED.
        if (
            self.state is AuthorityResolutionState.RESOLVED
            and not is_binding_authority_rank(self.authority_rank)
        ):
            # Keep the declared rank; consumers consult is_binding.
            pass

    @property
    def is_binding(self) -> bool:
        return (
            self.state is AuthorityResolutionState.RESOLVED
            and is_binding_authority_rank(self.authority_rank)
        )

    @property
    def is_unknown_or_ambiguous(self) -> bool:
        return self.state in (
            AuthorityResolutionState.AMBIGUOUS,
            AuthorityResolutionState.UNRESOLVED,
            AuthorityResolutionState.CONFLICT,
            AuthorityResolutionState.UNKNOWN,
            AuthorityResolutionState.STALE,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_rank": self.authority_rank.value,
            "binding_id": self.binding_id,
            "citation_ids": list(self.citation_ids),
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "selected_node_ids": list(self.selected_node_ids),
            "selected_versions": list(self.selected_versions),
            "state": self.state.value,
            "temporal": self.temporal.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityBinding":
        value = _mapping(value, "AuthorityBinding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "binding_id",
                    "state",
                    "authority_rank",
                    "temporal",
                    "citation_ids",
                    "selected_node_ids",
                    "selected_versions",
                    "reasons",
                }
            ),
            "AuthorityBinding",
        )
        temporal_raw = value.get("temporal") or {}
        if not isinstance(temporal_raw, Mapping):
            raise TypeError("temporal must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            binding_id=value.get("binding_id", ""),
            state=value.get("state", AuthorityResolutionState.UNKNOWN.value),
            authority_rank=value.get("authority_rank", AuthorityRank.UNKNOWN.value),
            temporal=TemporalMetadata.from_dict(temporal_raw),
            citation_ids=tuple(value.get("citation_ids") or ()),
            selected_node_ids=tuple(value.get("selected_node_ids") or ()),
            selected_versions=tuple(value.get("selected_versions") or ()),
            reasons=tuple(value.get("reasons") or ()),
        )


@dataclass(frozen=True, slots=True)
class NormalizedProposition:
    """Lossless normalized proposition ready for Legal IR compilation.

    Actors, modalities, conditions, deadlines, and exceptions are explicit.
    The proposition carries digests and identifiers only — never free-form
    government body text as a substitute for spans.
    """

    schema_version: str
    proposition_id: str
    assertion_kind: AssertionKind
    modality: LegalModality
    actor_role: ActorRole
    predicate: str
    subject: str | None
    object_ref: str | None
    condition_ids: tuple[str, ...]
    exception_ids: tuple[str, ...]
    deadline_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    source_span_ids: tuple[str, ...]
    normalizer_id: str | None
    normalizer_version: str | None
    proposition_digest: str
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"NormalizedProposition.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self,
            "proposition_id",
            _identifier(self.proposition_id, "proposition_id"),
        )
        object.__setattr__(
            self,
            "assertion_kind",
            _coerce_enum(AssertionKind, self.assertion_kind, "assertion_kind"),
        )
        object.__setattr__(
            self, "modality", _coerce_enum(LegalModality, self.modality, "modality")
        )
        object.__setattr__(
            self, "actor_role", _coerce_enum(ActorRole, self.actor_role, "actor_role")
        )
        object.__setattr__(
            self, "predicate", _require_str(self.predicate, "predicate", max_len=256)
        )
        object.__setattr__(
            self, "subject", _optional_str(self.subject, "subject", max_len=256)
        )
        object.__setattr__(
            self,
            "object_ref",
            _optional_str(self.object_ref, "object_ref", max_len=256),
        )
        object.__setattr__(
            self,
            "condition_ids",
            _tuple_of_identifiers(self.condition_ids, "condition_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "exception_ids",
            _tuple_of_identifiers(self.exception_ids, "exception_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "deadline_ids",
            _tuple_of_identifiers(self.deadline_ids, "deadline_ids", max_items=32),
        )
        object.__setattr__(
            self,
            "citation_ids",
            _tuple_of_identifiers(self.citation_ids, "citation_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _tuple_of_identifiers(
                self.source_span_ids, "source_span_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "normalizer_id",
            _optional_identifier(self.normalizer_id, "normalizer_id"),
        )
        object.__setattr__(
            self,
            "normalizer_version",
            _optional_str(self.normalizer_version, "normalizer_version", max_len=64),
        )
        object.__setattr__(
            self,
            "proposition_digest",
            _sha256_hex(self.proposition_digest, "proposition_digest"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        # Deterministic normalization must carry normalizer identity.
        if self.assertion_kind is AssertionKind.DETERMINISTIC_NORMALIZATION:
            if not self.normalizer_id or not self.normalizer_version:
                raise LegalIRContractError(
                    "deterministic_normalization requires normalizer_id and normalizer_version",
                    code=MappingReasonCode.NORMALIZER_IDENTITY_REQUIRED,
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_role": self.actor_role.value,
            "assertion_kind": self.assertion_kind.value,
            "citation_ids": list(self.citation_ids),
            "condition_ids": list(self.condition_ids),
            "deadline_ids": list(self.deadline_ids),
            "exception_ids": list(self.exception_ids),
            "labels": dict(self.labels),
            "modality": self.modality.value,
            "normalizer_id": self.normalizer_id,
            "normalizer_version": self.normalizer_version,
            "object_ref": self.object_ref,
            "predicate": self.predicate,
            "proposition_digest": self.proposition_digest,
            "proposition_id": self.proposition_id,
            "schema_version": self.schema_version,
            "source_span_ids": list(self.source_span_ids),
            "subject": self.subject,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedProposition":
        value = _mapping(value, "NormalizedProposition")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "proposition_id",
                    "assertion_kind",
                    "modality",
                    "actor_role",
                    "predicate",
                    "subject",
                    "object_ref",
                    "condition_ids",
                    "exception_ids",
                    "deadline_ids",
                    "citation_ids",
                    "source_span_ids",
                    "normalizer_id",
                    "normalizer_version",
                    "proposition_digest",
                    "labels",
                }
            ),
            "NormalizedProposition",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            proposition_id=value.get("proposition_id", ""),
            assertion_kind=value.get(
                "assertion_kind", AssertionKind.MODEL_CANDIDATE.value
            ),
            modality=value.get("modality", LegalModality.UNKNOWN.value),
            actor_role=value.get("actor_role", ActorRole.UNKNOWN.value),
            predicate=value.get("predicate", ""),
            subject=value.get("subject"),
            object_ref=value.get("object_ref"),
            condition_ids=tuple(value.get("condition_ids") or ()),
            exception_ids=tuple(value.get("exception_ids") or ()),
            deadline_ids=tuple(value.get("deadline_ids") or ()),
            citation_ids=tuple(value.get("citation_ids") or ()),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            normalizer_id=value.get("normalizer_id"),
            normalizer_version=value.get("normalizer_version"),
            proposition_digest=value.get("proposition_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ConditionRef:
    """Applicability condition referenced by a proposition."""

    schema_version: str
    condition_id: str
    description_digest: str
    source_span_ids: tuple[str, ...]
    resolved: bool
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"ConditionRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "condition_id", _identifier(self.condition_id, "condition_id")
        )
        object.__setattr__(
            self,
            "description_digest",
            _sha256_hex(self.description_digest, "description_digest"),
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _tuple_of_identifiers(
                self.source_span_ids, "source_span_ids", max_items=32
            ),
        )
        if not isinstance(self.resolved, bool):
            raise TypeError("resolved must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "description_digest": self.description_digest,
            "labels": dict(self.labels),
            "resolved": self.resolved,
            "schema_version": self.schema_version,
            "source_span_ids": list(self.source_span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConditionRef":
        value = _mapping(value, "ConditionRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "condition_id",
                    "description_digest",
                    "source_span_ids",
                    "resolved",
                    "labels",
                }
            ),
            "ConditionRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            condition_id=value.get("condition_id", ""),
            description_digest=value.get("description_digest", ""),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            resolved=bool(value.get("resolved", False)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ExceptionRef:
    """Exception / carve-out referenced by a proposition."""

    schema_version: str
    exception_id: str
    description_digest: str
    source_span_ids: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"ExceptionRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "exception_id", _identifier(self.exception_id, "exception_id")
        )
        object.__setattr__(
            self,
            "description_digest",
            _sha256_hex(self.description_digest, "description_digest"),
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _tuple_of_identifiers(
                self.source_span_ids, "source_span_ids", max_items=32
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description_digest": self.description_digest,
            "exception_id": self.exception_id,
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
            "source_span_ids": list(self.source_span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExceptionRef":
        value = _mapping(value, "ExceptionRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "exception_id",
                    "description_digest",
                    "source_span_ids",
                    "labels",
                }
            ),
            "ExceptionRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            exception_id=value.get("exception_id", ""),
            description_digest=value.get("description_digest", ""),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DeadlineRef:
    """Candidate or computed deadline with explicit uncertainty."""

    schema_version: str
    deadline_id: str
    candidate_utc: str | None
    rule_chain: tuple[str, ...]
    uncertainty: str | None
    source_span_ids: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"DeadlineRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "deadline_id", _identifier(self.deadline_id, "deadline_id")
        )
        object.__setattr__(
            self,
            "candidate_utc",
            _optional_temporal_token(self.candidate_utc, "candidate_utc"),
        )
        object.__setattr__(
            self, "rule_chain", _tuple_of_str(self.rule_chain, "rule_chain", max_items=32)
        )
        object.__setattr__(
            self,
            "uncertainty",
            _optional_str(self.uncertainty, "uncertainty", max_len=256),
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _tuple_of_identifiers(
                self.source_span_ids, "source_span_ids", max_items=32
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.uncertainty) or self.candidate_utc is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_utc": self.candidate_utc,
            "deadline_id": self.deadline_id,
            "labels": dict(self.labels),
            "rule_chain": list(self.rule_chain),
            "schema_version": self.schema_version,
            "source_span_ids": list(self.source_span_ids),
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeadlineRef":
        value = _mapping(value, "DeadlineRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "deadline_id",
                    "candidate_utc",
                    "rule_chain",
                    "uncertainty",
                    "source_span_ids",
                    "labels",
                }
            ),
            "DeadlineRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            deadline_id=value.get("deadline_id", ""),
            candidate_utc=value.get("candidate_utc"),
            rule_chain=tuple(value.get("rule_chain") or ()),
            uncertainty=value.get("uncertainty"),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SubmissionFactRef:
    """Submission fact bound to exact evidence span identity for Legal IR."""

    schema_version: str
    fact_id: str
    fact_type: str
    evidence_span_id: str
    affected_claims: tuple[str, ...]
    version: str
    extraction_status: str
    classification: DisclosureClassification
    assertion_kind: AssertionKind
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"SubmissionFactRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(
            self, "fact_type", _require_str(self.fact_type, "fact_type", max_len=128)
        )
        object.__setattr__(
            self,
            "evidence_span_id",
            _identifier(self.evidence_span_id, "evidence_span_id"),
        )
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        object.__setattr__(
            self, "version", _require_str(self.version, "version", max_len=64)
        )
        object.__setattr__(
            self,
            "extraction_status",
            _require_str(self.extraction_status, "extraction_status", max_len=64),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "assertion_kind",
            _coerce_enum(AssertionKind, self.assertion_kind, "assertion_kind"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        # Facts themselves are never proven conclusions.
        if self.assertion_kind is AssertionKind.PROVEN_CONCLUSION:
            raise LegalIRContractError(
                "submission facts cannot carry assertion_kind proven_conclusion",
                code=MappingReasonCode.ASSERTION_KIND_MISMATCH,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_claims": list(self.affected_claims),
            "assertion_kind": self.assertion_kind.value,
            "classification": self.classification.value,
            "evidence_span_id": self.evidence_span_id,
            "extraction_status": self.extraction_status,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionFactRef":
        value = _mapping(value, "SubmissionFactRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "fact_id",
                    "fact_type",
                    "evidence_span_id",
                    "affected_claims",
                    "version",
                    "extraction_status",
                    "classification",
                    "assertion_kind",
                    "labels",
                }
            ),
            "SubmissionFactRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            fact_id=value.get("fact_id", ""),
            fact_type=value.get("fact_type", ""),
            evidence_span_id=value.get("evidence_span_id", ""),
            affected_claims=tuple(value.get("affected_claims") or ()),
            version=value.get("version", "1"),
            extraction_status=value.get("extraction_status", "unknown"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            assertion_kind=value.get(
                "assertion_kind", AssertionKind.DETERMINISTIC_NORMALIZATION.value
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """Obligation that must be proved (or return unknown) for a mapping."""

    schema_version: str
    obligation_id: str
    proposition_id: str
    required_outcome: TriStateOutcome
    premise_proposition_ids: tuple[str, ...]
    premise_fact_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    proof_receipt_id: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"ProofObligation.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "proposition_id",
            _identifier(self.proposition_id, "proposition_id"),
        )
        object.__setattr__(
            self,
            "required_outcome",
            _coerce_enum(TriStateOutcome, self.required_outcome, "required_outcome"),
        )
        object.__setattr__(
            self,
            "premise_proposition_ids",
            _tuple_of_identifiers(
                self.premise_proposition_ids,
                "premise_proposition_ids",
                max_items=128,
            ),
        )
        object.__setattr__(
            self,
            "premise_fact_ids",
            _tuple_of_identifiers(
                self.premise_fact_ids, "premise_fact_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _tuple_of_identifiers(
                self.assumption_ids, "assumption_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "proof_receipt_id",
            _optional_identifier(self.proof_receipt_id, "proof_receipt_id"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "labels": dict(self.labels),
            "obligation_id": self.obligation_id,
            "premise_fact_ids": list(self.premise_fact_ids),
            "premise_proposition_ids": list(self.premise_proposition_ids),
            "proof_receipt_id": self.proof_receipt_id,
            "proposition_id": self.proposition_id,
            "required_outcome": self.required_outcome.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofObligation":
        value = _mapping(value, "ProofObligation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "obligation_id",
                    "proposition_id",
                    "required_outcome",
                    "premise_proposition_ids",
                    "premise_fact_ids",
                    "assumption_ids",
                    "proof_receipt_id",
                    "labels",
                }
            ),
            "ProofObligation",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            obligation_id=value.get("obligation_id", ""),
            proposition_id=value.get("proposition_id", ""),
            required_outcome=value.get(
                "required_outcome", TriStateOutcome.UNKNOWN.value
            ),
            premise_proposition_ids=tuple(value.get("premise_proposition_ids") or ()),
            premise_fact_ids=tuple(value.get("premise_fact_ids") or ()),
            assumption_ids=tuple(value.get("assumption_ids") or ()),
            proof_receipt_id=value.get("proof_receipt_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class AssumptionRef:
    """Explicit assumption that must not be silently dropped."""

    schema_version: str
    assumption_id: str
    description_digest: str
    asserted_by: ActorRole
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"AssumptionRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "assumption_id", _identifier(self.assumption_id, "assumption_id")
        )
        object.__setattr__(
            self,
            "description_digest",
            _sha256_hex(self.description_digest, "description_digest"),
        )
        object.__setattr__(
            self,
            "asserted_by",
            _coerce_enum(ActorRole, self.asserted_by, "asserted_by"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asserted_by": self.asserted_by.value,
            "assumption_id": self.assumption_id,
            "description_digest": self.description_digest,
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssumptionRef":
        value = _mapping(value, "AssumptionRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "assumption_id",
                    "description_digest",
                    "asserted_by",
                    "labels",
                }
            ),
            "AssumptionRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            assumption_id=value.get("assumption_id", ""),
            description_digest=value.get("description_digest", ""),
            asserted_by=value.get("asserted_by", ActorRole.SYSTEM.value),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class CounterEvidenceRef:
    """Counter-evidence span/fact binding that must remain first-class."""

    schema_version: str
    counter_id: str
    span_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"CounterEvidenceRef.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "counter_id", _identifier(self.counter_id, "counter_id")
        )
        object.__setattr__(
            self,
            "span_ids",
            _tuple_of_identifiers(self.span_ids, "span_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "fact_ids",
            _tuple_of_identifiers(self.fact_ids, "fact_ids", max_items=64),
        )
        if not self.span_ids and not self.fact_ids:
            raise ValueError("CounterEvidenceRef requires at least one span_id or fact_id")
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "counter_id": self.counter_id,
            "fact_ids": list(self.fact_ids),
            "labels": dict(self.labels),
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterEvidenceRef":
        value = _mapping(value, "CounterEvidenceRef")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "counter_id",
                    "span_ids",
                    "fact_ids",
                    "reason_codes",
                    "labels",
                }
            ),
            "CounterEvidenceRef",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            counter_id=value.get("counter_id", ""),
            span_ids=tuple(value.get("span_ids") or ()),
            fact_ids=tuple(value.get("fact_ids") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Top-level mapping and bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalIRMapping:
    """One validated USPTO→Legal IR mapping with full provenance.

    Invalid or ambiguous inputs are never silently accepted as
    ``MappingStatus.ACCEPTED``; they must be rejected or marked unknown.
    """

    schema_version: str
    mapping_id: str
    assertion_kind: AssertionKind
    status: MappingStatus
    outcome: TriStateOutcome
    source_identity: SourceIdentity
    temporal: TemporalMetadata
    disclosure: DisclosureMetadata
    source_spans: tuple[UsptoSpanRef, ...]
    citations: tuple[CitationRef, ...]
    authority: AuthorityBinding | None
    proposition: NormalizedProposition | None
    facts: tuple[SubmissionFactRef, ...]
    conditions: tuple[ConditionRef, ...]
    exceptions: tuple[ExceptionRef, ...]
    deadlines: tuple[DeadlineRef, ...]
    proof_obligation: ProofObligation | None
    assumptions: tuple[AssumptionRef, ...]
    counter_evidence: tuple[CounterEvidenceRef, ...]
    reason_codes: tuple[str, ...]
    reviewer_id: str | None
    proof_receipt_id: str | None
    confidence: float | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"LegalIRMapping.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "mapping_id", _identifier(self.mapping_id, "mapping_id")
        )
        object.__setattr__(
            self,
            "assertion_kind",
            _coerce_enum(AssertionKind, self.assertion_kind, "assertion_kind"),
        )
        object.__setattr__(
            self, "status", _coerce_enum(MappingStatus, self.status, "status")
        )
        object.__setattr__(
            self, "outcome", _coerce_enum(TriStateOutcome, self.outcome, "outcome")
        )
        if not isinstance(self.source_identity, SourceIdentity):
            raise TypeError("source_identity must be SourceIdentity")
        if not isinstance(self.temporal, TemporalMetadata):
            raise TypeError("temporal must be TemporalMetadata")
        if not isinstance(self.disclosure, DisclosureMetadata):
            raise TypeError("disclosure must be DisclosureMetadata")
        object.__setattr__(
            self,
            "source_spans",
            _tuple_of_records(self.source_spans, UsptoSpanRef, "source_spans"),
        )
        object.__setattr__(
            self,
            "citations",
            _tuple_of_records(self.citations, CitationRef, "citations"),
        )
        if self.authority is not None and not isinstance(
            self.authority, AuthorityBinding
        ):
            raise TypeError("authority must be AuthorityBinding or None")
        if self.proposition is not None and not isinstance(
            self.proposition, NormalizedProposition
        ):
            raise TypeError("proposition must be NormalizedProposition or None")
        object.__setattr__(
            self, "facts", _tuple_of_records(self.facts, SubmissionFactRef, "facts")
        )
        object.__setattr__(
            self,
            "conditions",
            _tuple_of_records(self.conditions, ConditionRef, "conditions"),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_records(self.exceptions, ExceptionRef, "exceptions"),
        )
        object.__setattr__(
            self,
            "deadlines",
            _tuple_of_records(self.deadlines, DeadlineRef, "deadlines"),
        )
        if self.proof_obligation is not None and not isinstance(
            self.proof_obligation, ProofObligation
        ):
            raise TypeError("proof_obligation must be ProofObligation or None")
        object.__setattr__(
            self,
            "assumptions",
            _tuple_of_records(self.assumptions, AssumptionRef, "assumptions"),
        )
        object.__setattr__(
            self,
            "counter_evidence",
            _tuple_of_records(
                self.counter_evidence, CounterEvidenceRef, "counter_evidence"
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "reviewer_id",
            _optional_identifier(self.reviewer_id, "reviewer_id"),
        )
        object.__setattr__(
            self,
            "proof_receipt_id",
            _optional_identifier(self.proof_receipt_id, "proof_receipt_id"),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        # Enforce invariant: accepted proven conclusions need a proof receipt.
        if (
            self.status is MappingStatus.ACCEPTED
            and self.assertion_kind is AssertionKind.PROVEN_CONCLUSION
            and not self.proof_receipt_id
        ):
            raise LegalIRContractError(
                "accepted proven_conclusion requires proof_receipt_id",
                code=MappingReasonCode.PROOF_RECEIPT_REQUIRED,
            )
        # Human findings require a reviewer identity when accepted.
        if (
            self.status is MappingStatus.ACCEPTED
            and self.assertion_kind is AssertionKind.HUMAN_FINDING
            and not self.reviewer_id
        ):
            raise LegalIRContractError(
                "accepted human_finding requires reviewer_id",
                code=MappingReasonCode.REVIEWER_IDENTITY_REQUIRED,
            )
        # Quoted text must have at least one span with a text digest.
        if (
            self.status is MappingStatus.ACCEPTED
            and self.assertion_kind is AssertionKind.QUOTED_TEXT
        ):
            if not self.source_spans or not any(
                span.text_digest for span in self.source_spans
            ):
                raise LegalIRContractError(
                    "accepted quoted_text requires source span with text_digest",
                    code=MappingReasonCode.QUOTE_DIGEST_REQUIRED,
                )
        # Accepted positive outcomes cannot rest on guidance-only authority.
        if (
            self.status is MappingStatus.ACCEPTED
            and self.outcome is TriStateOutcome.SATISFIED
            and self.authority is not None
            and not self.authority.is_binding
        ):
            raise LegalIRContractError(
                "satisfied outcome cannot rest on non-binding authority",
                code=MappingReasonCode.GUIDANCE_NOT_BINDING,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_kind": self.assertion_kind.value,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "authority": self.authority.to_dict() if self.authority else None,
            "citations": [item.to_dict() for item in self.citations],
            "conditions": [item.to_dict() for item in self.conditions],
            "confidence": self.confidence,
            "counter_evidence": [item.to_dict() for item in self.counter_evidence],
            "deadlines": [item.to_dict() for item in self.deadlines],
            "disclosure": self.disclosure.to_dict(),
            "exceptions": [item.to_dict() for item in self.exceptions],
            "facts": [item.to_dict() for item in self.facts],
            "labels": dict(self.labels),
            "mapping_id": self.mapping_id,
            "outcome": self.outcome.value,
            "proof_obligation": (
                self.proof_obligation.to_dict() if self.proof_obligation else None
            ),
            "proof_receipt_id": self.proof_receipt_id,
            "proposition": self.proposition.to_dict() if self.proposition else None,
            "reason_codes": list(self.reason_codes),
            "reviewer_id": self.reviewer_id,
            "schema_version": self.schema_version,
            "source_identity": self.source_identity.to_dict(),
            "source_spans": [item.to_dict() for item in self.source_spans],
            "status": self.status.value,
            "temporal": self.temporal.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalIRMapping":
        value = _mapping(value, "LegalIRMapping")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "mapping_id",
                    "assertion_kind",
                    "status",
                    "outcome",
                    "source_identity",
                    "temporal",
                    "disclosure",
                    "source_spans",
                    "citations",
                    "authority",
                    "proposition",
                    "facts",
                    "conditions",
                    "exceptions",
                    "deadlines",
                    "proof_obligation",
                    "assumptions",
                    "counter_evidence",
                    "reason_codes",
                    "reviewer_id",
                    "proof_receipt_id",
                    "confidence",
                    "labels",
                }
            ),
            "LegalIRMapping",
        )
        authority_raw = value.get("authority")
        proposition_raw = value.get("proposition")
        obligation_raw = value.get("proof_obligation")
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            mapping_id=value.get("mapping_id", ""),
            assertion_kind=value.get(
                "assertion_kind", AssertionKind.MODEL_CANDIDATE.value
            ),
            status=value.get("status", MappingStatus.UNKNOWN.value),
            outcome=value.get("outcome", TriStateOutcome.UNKNOWN.value),
            source_identity=SourceIdentity.from_dict(
                value.get("source_identity") or {}
            ),
            temporal=TemporalMetadata.from_dict(value.get("temporal") or {}),
            disclosure=DisclosureMetadata.from_dict(value.get("disclosure") or {}),
            source_spans=tuple(
                UsptoSpanRef.from_dict(item)
                for item in (value.get("source_spans") or ())
            ),
            citations=tuple(
                CitationRef.from_dict(item) for item in (value.get("citations") or ())
            ),
            authority=(
                AuthorityBinding.from_dict(authority_raw)
                if isinstance(authority_raw, Mapping)
                else None
            ),
            proposition=(
                NormalizedProposition.from_dict(proposition_raw)
                if isinstance(proposition_raw, Mapping)
                else None
            ),
            facts=tuple(
                SubmissionFactRef.from_dict(item) for item in (value.get("facts") or ())
            ),
            conditions=tuple(
                ConditionRef.from_dict(item)
                for item in (value.get("conditions") or ())
            ),
            exceptions=tuple(
                ExceptionRef.from_dict(item)
                for item in (value.get("exceptions") or ())
            ),
            deadlines=tuple(
                DeadlineRef.from_dict(item) for item in (value.get("deadlines") or ())
            ),
            proof_obligation=(
                ProofObligation.from_dict(obligation_raw)
                if isinstance(obligation_raw, Mapping)
                else None
            ),
            assumptions=tuple(
                AssumptionRef.from_dict(item)
                for item in (value.get("assumptions") or ())
            ),
            counter_evidence=tuple(
                CounterEvidenceRef.from_dict(item)
                for item in (value.get("counter_evidence") or ())
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            reviewer_id=value.get("reviewer_id"),
            proof_receipt_id=value.get("proof_receipt_id"),
            confidence=value.get("confidence"),
            labels=value.get("labels") or {},
        )


def _tuple_of_records(
    value: Any, record_cls: type, field: str, *, max_items: int = 256
) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of {record_cls.__name__}")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[Any] = []
    for i, item in enumerate(value):
        if not isinstance(item, record_cls):
            raise TypeError(
                f"{field}[{i}] must be {record_cls.__name__}, got {type(item).__name__}"
            )
        out.append(item)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class LegalIRContractBundle:
    """Deterministic collection of USPTO→Legal IR mappings."""

    schema_version: str
    bundle_id: str
    mappings: tuple[LegalIRMapping, ...]
    parser_version: str
    ruleset_version: str
    classification: DisclosureClassification
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != LEGAL_IR_CONTRACTS_SCHEMA_VERSION:
            raise LegalIRContractError(
                f"LegalIRContractBundle.schema_version must be {LEGAL_IR_CONTRACTS_SCHEMA_VERSION}",
                code=MappingReasonCode.SCHEMA_VERSION_MISMATCH,
            )
        object.__setattr__(
            self, "bundle_id", _identifier(self.bundle_id, "bundle_id")
        )
        object.__setattr__(
            self,
            "mappings",
            _tuple_of_records(self.mappings, LegalIRMapping, "mappings", max_items=4096),
        )
        seen: set[str] = set()
        for mapping in self.mappings:
            if mapping.mapping_id in seen:
                raise LegalIRContractError(
                    f"duplicate mapping_id: {mapping.mapping_id}",
                    code=MappingReasonCode.DUPLICATE_MAPPING_ID,
                )
            seen.add(mapping.mapping_id)
        object.__setattr__(
            self,
            "parser_version",
            _require_str(self.parser_version, "parser_version", max_len=128),
        )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "labels": dict(self.labels),
            "mappings": [item.to_dict() for item in self.mappings],
            "parser_version": self.parser_version,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalIRContractBundle":
        value = _mapping(value, "LegalIRContractBundle")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "bundle_id",
                    "mappings",
                    "parser_version",
                    "ruleset_version",
                    "classification",
                    "labels",
                }
            ),
            "LegalIRContractBundle",
        )
        return cls(
            schema_version=value.get(
                "schema_version", LEGAL_IR_CONTRACTS_SCHEMA_VERSION
            ),
            bundle_id=value.get("bundle_id", ""),
            mappings=tuple(
                LegalIRMapping.from_dict(item)
                for item in (value.get("mappings") or ())
            ),
            parser_version=value.get("parser_version", ""),
            ruleset_version=value.get("ruleset_version", ""),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Mapping construction / validation API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappingValidationIssue:
    """One deterministic validation issue for a candidate mapping."""

    code: MappingReasonCode
    message: str
    field_path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "field_path": self.field_path,
            "message": self.message[:256],
        }


def validate_mapping_candidate(
    *,
    assertion_kind: AssertionKind | str,
    source_identity: SourceIdentity | None,
    temporal: TemporalMetadata | None,
    disclosure: DisclosureMetadata | None,
    source_spans: Sequence[UsptoSpanRef] | None = None,
    authority: AuthorityBinding | None = None,
    proposition: NormalizedProposition | None = None,
    proof_receipt_id: str | None = None,
    reviewer_id: str | None = None,
    desired_outcome: TriStateOutcome | str = TriStateOutcome.UNKNOWN,
) -> tuple[MappingStatus, TriStateOutcome, tuple[MappingValidationIssue, ...]]:
    """Validate a candidate mapping without constructing a full record.

    Returns ``(status, outcome, issues)``. Invalid or ambiguous inputs yield
    ``REJECTED``, ``UNKNOWN``, or ``AMBIGUOUS`` — never a silent accept.
    """
    issues: list[MappingValidationIssue] = []
    kind = _coerce_enum(AssertionKind, assertion_kind, "assertion_kind")
    assert isinstance(kind, AssertionKind)
    outcome = _coerce_enum(TriStateOutcome, desired_outcome, "desired_outcome")
    assert isinstance(outcome, TriStateOutcome)

    if source_identity is None:
        issues.append(
            MappingValidationIssue(
                code=MappingReasonCode.MISSING_SOURCE_IDENTITY,
                message="source identity is required",
                field_path="source_identity",
            )
        )
    if temporal is None or temporal.is_empty:
        issues.append(
            MappingValidationIssue(
                code=MappingReasonCode.MISSING_TEMPORAL_METADATA,
                message="temporal metadata is required (as_of, edition, or effective interval)",
                field_path="temporal",
            )
        )
    if disclosure is None:
        issues.append(
            MappingValidationIssue(
                code=MappingReasonCode.DISCLOSURE_QUARANTINE,
                message="disclosure metadata is required",
                field_path="disclosure",
            )
        )
    elif disclosure.quarantine_required or requires_quarantine(disclosure.classification):
        # Quarantine does not reject the mapping schema, but forces unknown outcome.
        issues.append(
            MappingValidationIssue(
                code=MappingReasonCode.DISCLOSURE_QUARANTINE,
                message="disclosure requires quarantine; outcome marked unknown",
                field_path="disclosure.classification",
            )
        )
        outcome = TriStateOutcome.UNKNOWN

    spans = tuple(source_spans or ())
    if kind is AssertionKind.QUOTED_TEXT:
        if not spans:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.MISSING_SOURCE_SPAN,
                    message="quoted_text requires at least one source span",
                    field_path="source_spans",
                )
            )
        elif not any(span.text_digest for span in spans):
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.QUOTE_DIGEST_REQUIRED,
                    message="quoted_text requires a span text_digest",
                    field_path="source_spans.text_digest",
                )
            )
    elif kind is AssertionKind.DETERMINISTIC_NORMALIZATION:
        if proposition is None or not proposition.normalizer_id:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.NORMALIZER_IDENTITY_REQUIRED,
                    message="deterministic_normalization requires normalizer identity",
                    field_path="proposition.normalizer_id",
                )
            )
        if not spans and (proposition is None or not proposition.source_span_ids):
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.MISSING_SOURCE_SPAN,
                    message="normalization must retain source span identity",
                    field_path="source_spans",
                )
            )
    elif kind is AssertionKind.MODEL_CANDIDATE:
        # Model candidates are never proven; force non-proven outcome if satisfied requested.
        if outcome is TriStateOutcome.SATISFIED:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.MODEL_CANDIDATE_NOT_PROVEN,
                    message="model_candidate cannot yield satisfied without proof promotion",
                    field_path="assertion_kind",
                )
            )
            outcome = TriStateOutcome.UNKNOWN
    elif kind is AssertionKind.HUMAN_FINDING:
        if not reviewer_id:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.REVIEWER_IDENTITY_REQUIRED,
                    message="human_finding requires reviewer_id",
                    field_path="reviewer_id",
                )
            )
    elif kind is AssertionKind.PROVEN_CONCLUSION:
        if not proof_receipt_id:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.PROOF_RECEIPT_MISSING,
                    message="proven_conclusion requires proof_receipt_id",
                    field_path="proof_receipt_id",
                )
            )
        if authority is None or authority.is_unknown_or_ambiguous:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.UNRESOLVED_AUTHORITY,
                    message="proven_conclusion requires resolved binding authority",
                    field_path="authority",
                )
            )
        elif not authority.is_binding:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.GUIDANCE_NOT_BINDING,
                    message="guidance/candidate authority cannot support proven_conclusion",
                    field_path="authority.authority_rank",
                )
            )

    if authority is not None:
        if authority.state is AuthorityResolutionState.AMBIGUOUS:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.AMBIGUOUS_AUTHORITY,
                    message="authority resolution is ambiguous",
                    field_path="authority.state",
                )
            )
        elif authority.state is AuthorityResolutionState.UNRESOLVED:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.UNRESOLVED_AUTHORITY,
                    message="authority is unresolved",
                    field_path="authority.state",
                )
            )
        elif authority.state is AuthorityResolutionState.CONFLICT:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.AMBIGUOUS_AUTHORITY,
                    message="authority resolution conflict",
                    field_path="authority.state",
                )
            )
        # Guidance/candidates never support a satisfied outcome (any assertion kind).
        if (
            outcome is TriStateOutcome.SATISFIED
            and not authority.is_binding
            and kind is not AssertionKind.MODEL_CANDIDATE
        ):
            # Model candidates already force unknown above; avoid double-coding.
            if not authority.is_unknown_or_ambiguous:
                issues.append(
                    MappingValidationIssue(
                        code=MappingReasonCode.GUIDANCE_NOT_BINDING,
                        message="satisfied outcome cannot rest on non-binding authority",
                        field_path="authority.authority_rank",
                    )
                )
                outcome = TriStateOutcome.UNKNOWN

    # Classify status from issues (fail-closed).
    hard_reject_codes = {
        MappingReasonCode.MISSING_SOURCE_IDENTITY,
        MappingReasonCode.QUOTE_DIGEST_REQUIRED,
        MappingReasonCode.NORMALIZER_IDENTITY_REQUIRED,
        MappingReasonCode.PROOF_RECEIPT_MISSING,
        MappingReasonCode.REVIEWER_IDENTITY_REQUIRED,
        MappingReasonCode.GUIDANCE_NOT_BINDING,
        MappingReasonCode.ASSERTION_KIND_MISMATCH,
        MappingReasonCode.MODEL_CANDIDATE_NOT_PROVEN,
    }
    ambiguous_codes = {
        MappingReasonCode.AMBIGUOUS_AUTHORITY,
        MappingReasonCode.DEADLINE_AMBIGUOUS,
    }
    unknown_codes = {
        MappingReasonCode.MISSING_SOURCE_SPAN,
        MappingReasonCode.MISSING_TEMPORAL_METADATA,
        MappingReasonCode.UNRESOLVED_AUTHORITY,
        MappingReasonCode.DISCLOSURE_QUARANTINE,
        MappingReasonCode.CONDITION_UNRESOLVED,
        MappingReasonCode.CITATION_UNRESOLVED,
        MappingReasonCode.FACT_SPAN_UNRESOLVED,
    }

    codes = {issue.code for issue in issues}
    if codes & hard_reject_codes:
        status = MappingStatus.REJECTED
        if outcome is TriStateOutcome.SATISFIED:
            outcome = TriStateOutcome.UNKNOWN
    elif codes & ambiguous_codes:
        status = MappingStatus.AMBIGUOUS
        outcome = TriStateOutcome.UNKNOWN
    elif codes & unknown_codes:
        status = MappingStatus.UNKNOWN
        outcome = TriStateOutcome.UNKNOWN
    elif issues:
        status = MappingStatus.UNKNOWN
        outcome = TriStateOutcome.UNKNOWN
    else:
        status = MappingStatus.ACCEPTED
        if not issues:
            issues.append(
                MappingValidationIssue(
                    code=MappingReasonCode.VALID_MAPPING,
                    message="mapping accepted",
                )
            )

    return status, outcome, tuple(issues)


def build_legal_ir_mapping(
    *,
    mapping_id: str,
    assertion_kind: AssertionKind | str,
    source_identity: SourceIdentity,
    temporal: TemporalMetadata,
    disclosure: DisclosureMetadata,
    source_spans: Sequence[UsptoSpanRef] = (),
    citations: Sequence[CitationRef] = (),
    authority: AuthorityBinding | None = None,
    proposition: NormalizedProposition | None = None,
    facts: Sequence[SubmissionFactRef] = (),
    conditions: Sequence[ConditionRef] = (),
    exceptions: Sequence[ExceptionRef] = (),
    deadlines: Sequence[DeadlineRef] = (),
    proof_obligation: ProofObligation | None = None,
    assumptions: Sequence[AssumptionRef] = (),
    counter_evidence: Sequence[CounterEvidenceRef] = (),
    reviewer_id: str | None = None,
    proof_receipt_id: str | None = None,
    desired_outcome: TriStateOutcome | str = TriStateOutcome.UNKNOWN,
    confidence: float | None = None,
    labels: Mapping[str, str] | None = None,
    force_status: MappingStatus | str | None = None,
) -> LegalIRMapping:
    """Build a mapping after fail-closed validation.

    By default, status and outcome come from ``validate_mapping_candidate``.
    Pass ``force_status`` only for reconstructing already-validated records
    (e.g. from storage); invalid forced accepts for proven conclusions still
    raise via ``LegalIRMapping`` invariants.
    """
    status, outcome, issues = validate_mapping_candidate(
        assertion_kind=assertion_kind,
        source_identity=source_identity,
        temporal=temporal,
        disclosure=disclosure,
        source_spans=source_spans,
        authority=authority,
        proposition=proposition,
        proof_receipt_id=proof_receipt_id,
        reviewer_id=reviewer_id,
        desired_outcome=desired_outcome,
    )
    if force_status is not None:
        status = _coerce_enum(MappingStatus, force_status, "force_status")  # type: ignore[assignment]
        assert isinstance(status, MappingStatus)

    reason_codes = tuple(issue.code.value for issue in issues)
    # Promote deadline ambiguity into reason codes when present.
    for deadline in deadlines:
        if deadline.is_ambiguous:
            reason_codes = reason_codes + (MappingReasonCode.DEADLINE_AMBIGUOUS.value,)
            if status is MappingStatus.ACCEPTED:
                status = MappingStatus.AMBIGUOUS
                outcome = TriStateOutcome.UNKNOWN
            break
    for condition in conditions:
        if not condition.resolved:
            reason_codes = reason_codes + (MappingReasonCode.CONDITION_UNRESOLVED.value,)
            if status is MappingStatus.ACCEPTED and outcome is TriStateOutcome.SATISFIED:
                status = MappingStatus.UNKNOWN
                outcome = TriStateOutcome.UNKNOWN
            break

    return LegalIRMapping(
        schema_version=LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
        mapping_id=mapping_id,
        assertion_kind=assertion_kind,
        status=status,
        outcome=outcome,
        source_identity=source_identity,
        temporal=temporal,
        disclosure=disclosure,
        source_spans=tuple(source_spans),
        citations=tuple(citations),
        authority=authority,
        proposition=proposition,
        facts=tuple(facts),
        conditions=tuple(conditions),
        exceptions=tuple(exceptions),
        deadlines=tuple(deadlines),
        proof_obligation=proof_obligation,
        assumptions=tuple(assumptions),
        counter_evidence=tuple(counter_evidence),
        reason_codes=reason_codes,
        reviewer_id=reviewer_id,
        proof_receipt_id=proof_receipt_id,
        confidence=confidence,
        labels=labels or {},
    )


def round_trip_mapping(mapping: LegalIRMapping) -> LegalIRMapping:
    """Serialize and restore a mapping; used to prove identity preservation."""
    restored = LegalIRMapping.from_dict(mapping.to_dict())
    if canonical_json(mapping.to_dict()) != canonical_json(restored.to_dict()):
        raise LegalIRContractError(
            "round trip lost identity or metadata",
            code=MappingReasonCode.INVALID_ENUM,
        )
    return restored


def assertion_kinds() -> tuple[str, ...]:
    """Return the closed set of assertion kinds (stable order)."""
    return tuple(kind.value for kind in AssertionKind)


__all__ = [
    "LEGAL_IR_CONTRACTS_INTERFACE",
    "LEGAL_IR_CONTRACTS_SCHEMA_VERSION",
    "ActorRole",
    "AssertionKind",
    "AssumptionRef",
    "AuthorityBinding",
    "AuthorityRank",
    "AuthorityResolutionState",
    "CitationRef",
    "ConditionRef",
    "CounterEvidenceRef",
    "DeadlineRef",
    "DisclosureMetadata",
    "ExceptionRef",
    "LegalIRContractBundle",
    "LegalIRContractError",
    "LegalIRMapping",
    "LegalModality",
    "MappingReasonCode",
    "MappingStatus",
    "MappingValidationIssue",
    "NormalizedProposition",
    "ProofObligation",
    "SourceIdentity",
    "SubmissionFactRef",
    "TemporalMetadata",
    "TriStateOutcome",
    "UsptoSpanRef",
    "assertion_kind_may_be_proven",
    "assertion_kinds",
    "build_legal_ir_mapping",
    "canonical_json",
    "is_binding_authority_rank",
    "round_trip_mapping",
    "validate_mapping_candidate",
]
