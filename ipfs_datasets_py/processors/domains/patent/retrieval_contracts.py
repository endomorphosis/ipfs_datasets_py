"""Source-linked BM25, vector, graph, and fusion retrieval contracts.

These records freeze the serialization boundary for patent hybrid retrieval
(PATLAW-090). They intentionally contain no index builders, embedding I/O,
graph engines, or package-level re-exports. Schema changes must be additive
and versioned.

Design invariants:

* Every index row, node, edge, and ranked hit joins to at least one source
  CID and optional exact span.
* Disclosure, tenant, and as-of filters are mandatory *before* scoring.
* Generated summaries and candidate (LLM/parser-proposed) edges may not claim
  source authority; only source-derived material may.
* Serialization is deterministic via ``to_dict`` / ``from_dict`` and
  ``canonical_json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

RETRIEVAL_CONTRACTS_SCHEMA_VERSION: Final = "patent.retrieval.contracts.v1"
RETRIEVAL_CONTRACTS_INTERFACE: Final = "PatentRetrievalContracts@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class RetrievalContractsError(ValueError):
    """Base error for patent retrieval contract violations."""


class MissingPreRankingFiltersError(RetrievalContractsError):
    """Raised when scoring is attempted without mandatory pre-ranking filters."""


class SourceAuthorityClaimError(RetrievalContractsError):
    """Raised when non-source material claims source authority."""


class PreRankingFilterViolation(RetrievalContractsError):
    """Raised when a candidate fails disclosure/tenant/as-of admission."""


class RetrievalFamily(str, Enum):
    """Retrieval modality / index family."""

    BM25 = "bm25"
    VECTOR = "vector"
    GRAPH = "graph"
    FUSION = "fusion"


class IndexField(str, Enum):
    """Fielded lexical index fields for patent/legal documents."""

    TITLE = "title"
    ABSTRACT = "abstract"
    CLAIMS = "claims"
    DESCRIPTION = "description"
    CPC = "cpc"
    IPC = "ipc"
    CITATIONS = "citations"
    NUMBERS = "numbers"
    LEGAL_BASES = "legal_bases"


class EdgeKind(str, Enum):
    """Deterministic graph edge relation kinds (projection-side)."""

    CITES = "cites"
    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    DEPENDS_ON = "depends_on"
    CLASSIFIES = "classifies"
    REFERENCES_AUTHORITY = "references_authority"
    CONTINUATION = "continuation"
    PRIORITY = "priority"
    REJECTS = "rejects"
    RESPONDS_TO = "responds_to"
    OTHER = "other"


class EdgeProvenance(str, Enum):
    """How an edge or summary was produced."""

    SOURCE_DERIVED = "source_derived"
    CANDIDATE = "candidate"
    GENERATED_SUMMARY = "generated_summary"


class AuthorityClaim(str, Enum):
    """Whether a record may be treated as source-authoritative evidence.

    Only ``SOURCE_BOUND`` material may ground dispositive retrieval results.
    Generated summaries and candidate edges are forced to ``NONE`` or
    ``REVIEW_ONLY`` and never ``SOURCE_BOUND``.
    """

    SOURCE_BOUND = "source_bound"
    REVIEW_ONLY = "review_only"
    NONE = "none"


class DisclosureClass(str, Enum):
    """Disclosure classification for retrieval admission (fail-closed)."""

    PUBLIC_OFFICIAL = "public_official"
    PUBLIC_USER = "public_user"
    CONFIDENTIAL_APPLICATION = "confidential_application"
    PRIVILEGED_WORK_PRODUCT = "privileged_work_product"
    RESTRICTED_EXPORT_REVIEW = "restricted_export_review"
    CREDENTIAL_OR_PAYMENT = "credential_or_payment"
    UNKNOWN = "unknown"


_PUBLIC_DISCLOSURE: Final[frozenset[DisclosureClass]] = frozenset(
    {
        DisclosureClass.PUBLIC_OFFICIAL,
        DisclosureClass.PUBLIC_USER,
    }
)

_PRIVATE_DISCLOSURE: Final[frozenset[DisclosureClass]] = frozenset(
    {
        DisclosureClass.CONFIDENTIAL_APPLICATION,
        DisclosureClass.PRIVILEGED_WORK_PRODUCT,
        DisclosureClass.RESTRICTED_EXPORT_REVIEW,
        DisclosureClass.CREDENTIAL_OR_PAYMENT,
    }
)

# Default field weights for fielded BM25 (relative; not probabilities).
DEFAULT_FIELD_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        IndexField.TITLE.value: 3.0,
        IndexField.ABSTRACT.value: 2.0,
        IndexField.CLAIMS.value: 4.0,
        IndexField.DESCRIPTION.value: 1.0,
        IndexField.CPC.value: 2.5,
        IndexField.IPC.value: 2.5,
        IndexField.CITATIONS.value: 2.0,
        IndexField.NUMBERS.value: 1.5,
        IndexField.LEGAL_BASES.value: 3.0,
    }
)


def is_public_disclosure(value: DisclosureClass | str) -> bool:
    return _coerce_disclosure(value) in _PUBLIC_DISCLOSURE


def is_private_disclosure(value: DisclosureClass | str) -> bool:
    return _coerce_disclosure(value) in _PRIVATE_DISCLOSURE


def requires_quarantine(value: DisclosureClass | str) -> bool:
    return _coerce_disclosure(value) is DisclosureClass.UNKNOWN


def claims_source_authority(claim: AuthorityClaim | str) -> bool:
    return _coerce_enum(AuthorityClaim, claim, "authority_claim") is AuthorityClaim.SOURCE_BOUND


def allow_source_authority_for(provenance: EdgeProvenance | str) -> bool:
    """Return True only when provenance may legally claim source authority."""
    kind = _coerce_enum(EdgeProvenance, provenance, "provenance")
    return kind is EdgeProvenance.SOURCE_DERIVED


def assert_authority_claim_allowed(
    provenance: EdgeProvenance | str,
    authority_claim: AuthorityClaim | str,
) -> AuthorityClaim:
    """Fail closed if generated summaries/candidates claim source authority.

    Returns the (possibly coerced) claim that is safe to store.
    """
    kind = _coerce_enum(EdgeProvenance, provenance, "provenance")
    claim = _coerce_enum(AuthorityClaim, authority_claim, "authority_claim")
    if kind is EdgeProvenance.SOURCE_DERIVED:
        return claim
    if claim is AuthorityClaim.SOURCE_BOUND:
        raise SourceAuthorityClaimError(
            f"{kind.value} material cannot claim source authority "
            f"({AuthorityClaim.SOURCE_BOUND.value}); use "
            f"{AuthorityClaim.NONE.value} or {AuthorityClaim.REVIEW_ONLY.value}"
        )
    return claim


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for contract round-trip equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _cid(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _CID_RE.match(text):
        raise ValueError(f"{field} is not a valid content identifier: {text!r}")
    return text


def _optional_cid(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    return _cid(text, field)


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


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    return _iso_utc(text, field)


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _positive_int(value: Any, field: str) -> int:
    number = _nonneg_int(value, field)
    if number < 1:
        raise ValueError(f"{field} must be >= 1")
    return number


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float, got {type(value).__name__}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be a finite float")
    return number


def _nonneg_float(value: Any, field: str) -> float:
    number = _finite_float(value, field)
    if number < 0.0:
        raise ValueError(f"{field} must be >= 0")
    return number


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    number = _finite_float(value, field)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _coerce_disclosure(value: Any) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClass(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure class: {value!r}") from exc
    raise TypeError(
        f"disclosure must be DisclosureClass or str, got {type(value).__name__}"
    )


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


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


def _schema_pinned(value: Any, expected: str, label: str) -> str:
    text = _require_str(value, f"{label}.schema_version", max_len=64)
    if text != expected:
        raise ValueError(f"{label}.schema_version must be {expected}, got {text!r}")
    return text


# ---------------------------------------------------------------------------
# Core source-link and field-weight contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Exact character or token span within a source artifact."""

    start: int
    end: int
    unit: str = "char"

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _nonneg_int(self.start, "start"))
        object.__setattr__(self, "end", _nonneg_int(self.end, "end"))
        if self.end < self.start:
            raise ValueError("SourceSpan.end must be >= start")
        object.__setattr__(
            self, "unit", _require_str(self.unit, "unit", max_len=32)
        )
        if self.unit not in {"char", "token", "page", "byte"}:
            raise ValueError(f"unsupported span unit: {self.unit!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"end": self.end, "start": self.start, "unit": self.unit}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSpan":
        value = _mapping(value, "SourceSpan")
        _reject_unknown(value, frozenset({"start", "end", "unit"}), "SourceSpan")
        return cls(
            start=value.get("start", 0),
            end=value.get("end", 0),
            unit=value.get("unit", "char"),
        )


@dataclass(frozen=True, slots=True)
class SourceLink:
    """Join from an index/graph element to an immutable source artifact."""

    source_cid: str
    artifact_id: str
    span: SourceSpan | None = None
    source_receipt_id: str | None = None
    authority_tier: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if self.span is not None and not isinstance(self.span, SourceSpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
            else:
                raise TypeError("span must be SourceSpan, mapping, or None")
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_str(self.source_receipt_id, "source_receipt_id", max_len=256),
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_tier": self.authority_tier,
            "source_cid": self.source_cid,
            "source_receipt_id": self.source_receipt_id,
            "span": None if self.span is None else self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceLink":
        value = _mapping(value, "SourceLink")
        _reject_unknown(
            value,
            frozenset(
                {
                    "source_cid",
                    "artifact_id",
                    "span",
                    "source_receipt_id",
                    "authority_tier",
                }
            ),
            "SourceLink",
        )
        span_raw = value.get("span")
        span = None if span_raw is None else SourceSpan.from_dict(span_raw)
        return cls(
            source_cid=value.get("source_cid", ""),
            artifact_id=value.get("artifact_id", ""),
            span=span,
            source_receipt_id=value.get("source_receipt_id"),
            authority_tier=value.get("authority_tier"),
        )


def _tuple_of_source_links(
    value: Any, field: str, *, max_items: int = 64, require_nonempty: bool = True
) -> tuple[SourceLink, ...]:
    if value is None:
        links: tuple[SourceLink, ...] = ()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) > max_items:
            raise ValueError(f"{field} exceeds max items {max_items}")
        out: list[SourceLink] = []
        for i, item in enumerate(value):
            if isinstance(item, SourceLink):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(SourceLink.from_dict(item))
            else:
                raise TypeError(f"{field}[{i}] must be SourceLink or mapping")
        links = tuple(out)
    else:
        raise TypeError(f"{field} must be a sequence of SourceLink")
    if require_nonempty and not links:
        raise ValueError(f"{field} must contain at least one source link")
    return links


@dataclass(frozen=True, slots=True)
class FieldWeight:
    """Relative BM25 weight for a single fielded index field."""

    field: IndexField
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "field", _coerce_enum(IndexField, self.field, "field")
        )
        object.__setattr__(self, "weight", _nonneg_float(self.weight, "weight"))

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field.value, "weight": self.weight}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FieldWeight":
        value = _mapping(value, "FieldWeight")
        _reject_unknown(value, frozenset({"field", "weight"}), "FieldWeight")
        return cls(field=value.get("field", ""), weight=value.get("weight", 0.0))


@dataclass(frozen=True, slots=True)
class FieldWeightConfig:
    """Complete field-weight map for fielded BM25 builds."""

    schema_version: str
    weights: tuple[FieldWeight, ...]
    config_cid: str | None = None
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "FieldWeightConfig",
            ),
        )
        if not isinstance(self.weights, Sequence) or isinstance(
            self.weights, (str, bytes)
        ):
            raise TypeError("weights must be a sequence of FieldWeight")
        normalized: list[FieldWeight] = []
        seen: set[IndexField] = set()
        for i, item in enumerate(self.weights):
            if isinstance(item, FieldWeight):
                fw = item
            elif isinstance(item, Mapping):
                fw = FieldWeight.from_dict(item)
            else:
                raise TypeError(f"weights[{i}] must be FieldWeight or mapping")
            if fw.field in seen:
                raise ValueError(f"duplicate field weight for {fw.field.value}")
            seen.add(fw.field)
            normalized.append(fw)
        if not normalized:
            raise ValueError("FieldWeightConfig.weights must be non-empty")
        object.__setattr__(
            self,
            "weights",
            tuple(sorted(normalized, key=lambda w: w.field.value)),
        )
        object.__setattr__(
            self, "config_cid", _optional_cid(self.config_cid, "config_cid")
        )
        object.__setattr__(self, "k1", _nonneg_float(self.k1, "k1"))
        object.__setattr__(self, "b", _nonneg_float(self.b, "b"))
        if self.b > 1.0:
            raise ValueError("b must be in [0.0, 1.0]")

    def weight_for(self, field: IndexField | str) -> float:
        target = _coerce_enum(IndexField, field, "field")
        for item in self.weights:
            if item.field is target:
                return item.weight
        raise KeyError(f"no weight configured for field {target.value}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "b": self.b,
            "config_cid": self.config_cid,
            "k1": self.k1,
            "schema_version": self.schema_version,
            "weights": [w.to_dict() for w in self.weights],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FieldWeightConfig":
        value = _mapping(value, "FieldWeightConfig")
        _reject_unknown(
            value,
            frozenset({"schema_version", "weights", "config_cid", "k1", "b"}),
            "FieldWeightConfig",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            weights=tuple(value.get("weights") or ()),
            config_cid=value.get("config_cid"),
            k1=value.get("k1", 1.5),
            b=value.get("b", 0.75),
        )

    @classmethod
    def default(cls, *, config_cid: str | None = None) -> "FieldWeightConfig":
        weights = tuple(
            FieldWeight(field=IndexField(name), weight=weight)
            for name, weight in DEFAULT_FIELD_WEIGHTS.items()
        )
        return cls(
            schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
            weights=weights,
            config_cid=config_cid,
        )


# ---------------------------------------------------------------------------
# Index rows: BM25, vector, graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceLinkedIndexRow:
    """One source-linked lexical (BM25) or shared index document row."""

    schema_version: str
    row_id: str
    document_id: str
    family: RetrievalFamily
    field_values: Mapping[str, str]
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    content_digest: str
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    publication_utc: str | None = None
    field_weights_config_cid: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "SourceLinkedIndexRow",
            ),
        )
        object.__setattr__(self, "row_id", _identifier(self.row_id, "row_id"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "family", _coerce_enum(RetrievalFamily, self.family, "family")
        )
        if self.family not in (
            RetrievalFamily.BM25,
            RetrievalFamily.VECTOR,
            RetrievalFamily.GRAPH,
        ):
            raise ValueError(
                "SourceLinkedIndexRow.family must be bm25, vector, or graph"
            )
        if not isinstance(self.field_values, Mapping):
            raise TypeError("field_values must be a mapping")
        fields_out: dict[str, str] = {}
        for key, raw in self.field_values.items():
            field_name = _require_str(key, "field_values.key", max_len=64)
            # Allow known IndexField values plus free-form extensions.
            fields_out[field_name] = _require_str(
                raw, f"field_values[{field_name}]", max_len=1_000_000
            )
        if not fields_out and self.family is RetrievalFamily.BM25:
            raise ValueError("BM25 SourceLinkedIndexRow requires field_values")
        object.__setattr__(
            self, "field_values", MappingProxyType(dict(sorted(fields_out.items())))
        )
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(self.source_links, "source_links"),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self, "content_digest", _sha256_hex(self.content_digest, "content_digest")
        )
        object.__setattr__(
            self,
            "effective_from_utc",
            _optional_iso_utc(self.effective_from_utc, "effective_from_utc"),
        )
        object.__setattr__(
            self,
            "effective_to_utc",
            _optional_iso_utc(self.effective_to_utc, "effective_to_utc"),
        )
        if (
            self.effective_from_utc
            and self.effective_to_utc
            and self.effective_to_utc < self.effective_from_utc
        ):
            raise ValueError("effective_to_utc must be >= effective_from_utc")
        object.__setattr__(
            self,
            "publication_utc",
            _optional_iso_utc(self.publication_utc, "publication_utc"),
        )
        object.__setattr__(
            self,
            "field_weights_config_cid",
            _optional_cid(self.field_weights_config_cid, "field_weights_config_cid"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "family": self.family.value,
            "field_values": dict(self.field_values),
            "field_weights_config_cid": self.field_weights_config_cid,
            "metadata": dict(self.metadata),
            "publication_utc": self.publication_utc,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceLinkedIndexRow":
        value = _mapping(value, "SourceLinkedIndexRow")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "row_id",
                    "document_id",
                    "family",
                    "field_values",
                    "source_links",
                    "disclosure",
                    "tenant_id",
                    "content_digest",
                    "effective_from_utc",
                    "effective_to_utc",
                    "publication_utc",
                    "field_weights_config_cid",
                    "metadata",
                }
            ),
            "SourceLinkedIndexRow",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            row_id=value.get("row_id", ""),
            document_id=value.get("document_id", ""),
            family=value.get("family", RetrievalFamily.BM25.value),
            field_values=value.get("field_values") or {},
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            content_digest=value.get("content_digest", ""),
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
            publication_utc=value.get("publication_utc"),
            field_weights_config_cid=value.get("field_weights_config_cid"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Pinned embedding provider/model/config identity for vector rows."""

    schema_version: str
    provider: str
    model_id: str
    model_version: str
    dimension: int
    config_cid: str
    model_cid: str | None = None
    backend: str = "pinned"
    normalize: bool = True
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "EmbeddingIdentity",
            ),
        )
        object.__setattr__(
            self, "provider", _require_str(self.provider, "provider", max_len=128)
        )
        object.__setattr__(
            self, "model_id", _require_str(self.model_id, "model_id", max_len=256)
        )
        object.__setattr__(
            self,
            "model_version",
            _require_str(self.model_version, "model_version", max_len=128),
        )
        object.__setattr__(self, "dimension", _positive_int(self.dimension, "dimension"))
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(
            self, "model_cid", _optional_cid(self.model_cid, "model_cid")
        )
        object.__setattr__(
            self, "backend", _require_str(self.backend, "backend", max_len=64)
        )
        if not isinstance(self.normalize, bool):
            raise TypeError("normalize must be bool")
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "config_cid": self.config_cid,
            "dimension": self.dimension,
            "metadata": dict(self.metadata),
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "normalize": self.normalize,
            "provider": self.provider,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EmbeddingIdentity":
        value = _mapping(value, "EmbeddingIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "provider",
                    "model_id",
                    "model_version",
                    "dimension",
                    "config_cid",
                    "model_cid",
                    "backend",
                    "normalize",
                    "metadata",
                }
            ),
            "EmbeddingIdentity",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            provider=value.get("provider", ""),
            model_id=value.get("model_id", ""),
            model_version=value.get("model_version", ""),
            dimension=value.get("dimension", 0),
            config_cid=value.get("config_cid", ""),
            model_cid=value.get("model_cid"),
            backend=value.get("backend", "pinned"),
            normalize=bool(value.get("normalize", True)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class VectorIndexRow:
    """Pinned vector row bound to embedding identity and source links."""

    schema_version: str
    row_id: str
    document_id: str
    embedding: EmbeddingIdentity
    vector_digest: str
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    content_digest: str
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "VectorIndexRow",
            ),
        )
        object.__setattr__(self, "row_id", _identifier(self.row_id, "row_id"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        if isinstance(self.embedding, Mapping):
            object.__setattr__(
                self, "embedding", EmbeddingIdentity.from_dict(self.embedding)
            )
        elif not isinstance(self.embedding, EmbeddingIdentity):
            raise TypeError("embedding must be EmbeddingIdentity or mapping")
        object.__setattr__(
            self, "vector_digest", _sha256_hex(self.vector_digest, "vector_digest")
        )
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(self.source_links, "source_links"),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self, "content_digest", _sha256_hex(self.content_digest, "content_digest")
        )
        object.__setattr__(
            self,
            "effective_from_utc",
            _optional_iso_utc(self.effective_from_utc, "effective_from_utc"),
        )
        object.__setattr__(
            self,
            "effective_to_utc",
            _optional_iso_utc(self.effective_to_utc, "effective_to_utc"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "embedding": self.embedding.to_dict(),
            "metadata": dict(self.metadata),
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
            "vector_digest": self.vector_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VectorIndexRow":
        value = _mapping(value, "VectorIndexRow")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "row_id",
                    "document_id",
                    "embedding",
                    "vector_digest",
                    "source_links",
                    "disclosure",
                    "tenant_id",
                    "content_digest",
                    "effective_from_utc",
                    "effective_to_utc",
                    "metadata",
                }
            ),
            "VectorIndexRow",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            row_id=value.get("row_id", ""),
            document_id=value.get("document_id", ""),
            embedding=value.get("embedding") or {},
            vector_digest=value.get("vector_digest", ""),
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            content_digest=value.get("content_digest", ""),
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """Provenance-bound graph edge; candidates cannot claim source authority."""

    schema_version: str
    edge_id: str
    subject_id: str
    object_id: str
    kind: EdgeKind
    provenance: EdgeProvenance
    authority_claim: AuthorityClaim
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    weight: float = 1.0
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, RETRIEVAL_CONTRACTS_SCHEMA_VERSION, "GraphEdge"
            ),
        )
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "object_id", _identifier(self.object_id, "object_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(EdgeKind, self.kind, "kind"))
        object.__setattr__(
            self,
            "provenance",
            _coerce_enum(EdgeProvenance, self.provenance, "provenance"),
        )
        claim = assert_authority_claim_allowed(self.provenance, self.authority_claim)
        object.__setattr__(self, "authority_claim", claim)
        # Source-derived edges must carry source links; candidates may be empty
        # only when authority is NONE/REVIEW_ONLY (already enforced above).
        require_links = self.provenance is EdgeProvenance.SOURCE_DERIVED
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(
                self.source_links,
                "source_links",
                require_nonempty=require_links,
            ),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "weight", _nonneg_float(self.weight, "weight"))
        object.__setattr__(
            self,
            "effective_from_utc",
            _optional_iso_utc(self.effective_from_utc, "effective_from_utc"),
        )
        object.__setattr__(
            self,
            "effective_to_utc",
            _optional_iso_utc(self.effective_to_utc, "effective_to_utc"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "disclosure": self.disclosure.value,
            "edge_id": self.edge_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "object_id": self.object_id,
            "provenance": self.provenance.value,
            "schema_version": self.schema_version,
            "source_links": [link.to_dict() for link in self.source_links],
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphEdge":
        value = _mapping(value, "GraphEdge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "edge_id",
                    "subject_id",
                    "object_id",
                    "kind",
                    "provenance",
                    "authority_claim",
                    "source_links",
                    "disclosure",
                    "tenant_id",
                    "weight",
                    "effective_from_utc",
                    "effective_to_utc",
                    "metadata",
                }
            ),
            "GraphEdge",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            edge_id=value.get("edge_id", ""),
            subject_id=value.get("subject_id", ""),
            object_id=value.get("object_id", ""),
            kind=value.get("kind", EdgeKind.OTHER.value),
            provenance=value.get("provenance", EdgeProvenance.SOURCE_DERIVED.value),
            authority_claim=value.get(
                "authority_claim", AuthorityClaim.SOURCE_BOUND.value
            ),
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            weight=value.get("weight", 1.0),
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GeneratedSummary:
    """Model-generated summary that can never claim source authority."""

    schema_version: str
    summary_id: str
    document_id: str
    text_digest: str
    provenance: EdgeProvenance
    authority_claim: AuthorityClaim
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    model_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "GeneratedSummary",
            ),
        )
        object.__setattr__(
            self, "summary_id", _identifier(self.summary_id, "summary_id")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "text_digest", _sha256_hex(self.text_digest, "text_digest")
        )
        object.__setattr__(
            self,
            "provenance",
            _coerce_enum(EdgeProvenance, self.provenance, "provenance"),
        )
        if self.provenance is not EdgeProvenance.GENERATED_SUMMARY:
            raise ValueError(
                "GeneratedSummary.provenance must be generated_summary"
            )
        claim = assert_authority_claim_allowed(self.provenance, self.authority_claim)
        object.__setattr__(self, "authority_claim", claim)
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(
                self.source_links, "source_links", require_nonempty=False
            ),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self, "model_id", _optional_str(self.model_id, "model_id", max_len=256)
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "metadata": dict(self.metadata),
            "model_id": self.model_id,
            "provenance": self.provenance.value,
            "schema_version": self.schema_version,
            "source_links": [link.to_dict() for link in self.source_links],
            "summary_id": self.summary_id,
            "tenant_id": self.tenant_id,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GeneratedSummary":
        value = _mapping(value, "GeneratedSummary")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "summary_id",
                    "document_id",
                    "text_digest",
                    "provenance",
                    "authority_claim",
                    "source_links",
                    "disclosure",
                    "tenant_id",
                    "model_id",
                    "metadata",
                }
            ),
            "GeneratedSummary",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            summary_id=value.get("summary_id", ""),
            document_id=value.get("document_id", ""),
            text_digest=value.get("text_digest", ""),
            provenance=value.get(
                "provenance", EdgeProvenance.GENERATED_SUMMARY.value
            ),
            authority_claim=value.get("authority_claim", AuthorityClaim.NONE.value),
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            model_id=value.get("model_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GraphRankHit:
    """One graph-expansion rank hit with provenance-bound path."""

    node_id: str
    document_id: str
    score: float
    rank: int
    path_edge_ids: tuple[str, ...]
    source_links: tuple[SourceLink, ...]
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(
            self,
            "path_edge_ids",
            _tuple_of_str(self.path_edge_ids, "path_edge_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(self.source_links, "source_links"),
        )
        claim = _coerce_enum(AuthorityClaim, self.authority_claim, "authority_claim")
        object.__setattr__(self, "authority_claim", claim)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "document_id": self.document_id,
            "node_id": self.node_id,
            "path_edge_ids": list(self.path_edge_ids),
            "rank": self.rank,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphRankHit":
        value = _mapping(value, "GraphRankHit")
        _reject_unknown(
            value,
            frozenset(
                {
                    "node_id",
                    "document_id",
                    "score",
                    "rank",
                    "path_edge_ids",
                    "source_links",
                    "authority_claim",
                }
            ),
            "GraphRankHit",
        )
        return cls(
            node_id=value.get("node_id", ""),
            document_id=value.get("document_id", ""),
            score=value.get("score", 0.0),
            rank=value.get("rank", 1),
            path_edge_ids=tuple(value.get("path_edge_ids") or ()),
            source_links=tuple(value.get("source_links") or ()),
            authority_claim=value.get(
                "authority_claim", AuthorityClaim.SOURCE_BOUND.value
            ),
        )


# ---------------------------------------------------------------------------
# Pre-ranking filters (mandatory before scoring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreRankingFilters:
    """Mandatory disclosure / tenant / as-of admission gate before scoring.

    Scoring and fusion APIs refuse to run unless an instance of this type is
    supplied and marked applied.
    """

    schema_version: str
    tenant_id: str
    as_of_utc: str
    allowed_disclosures: tuple[DisclosureClass, ...]
    applied: bool = False
    denied_provider_call_count: int = 0
    filter_receipt_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                "PreRankingFilters",
            ),
        )
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "as_of_utc", _iso_utc(self.as_of_utc, "as_of_utc"))
        if not isinstance(self.allowed_disclosures, Sequence) or isinstance(
            self.allowed_disclosures, (str, bytes)
        ):
            raise TypeError("allowed_disclosures must be a sequence")
        if not self.allowed_disclosures:
            raise ValueError("allowed_disclosures must be non-empty")
        disclosures: list[DisclosureClass] = []
        seen: set[DisclosureClass] = set()
        for i, raw in enumerate(self.allowed_disclosures):
            item = _coerce_disclosure(raw)
            if item is DisclosureClass.UNKNOWN:
                raise ValueError(
                    "allowed_disclosures must not include unknown "
                    "(unknown always quarantines)"
                )
            if item not in seen:
                seen.add(item)
                disclosures.append(item)
        object.__setattr__(self, "allowed_disclosures", tuple(disclosures))
        if not isinstance(self.applied, bool):
            raise TypeError("applied must be bool")
        object.__setattr__(
            self,
            "denied_provider_call_count",
            _nonneg_int(self.denied_provider_call_count, "denied_provider_call_count"),
        )
        object.__setattr__(
            self,
            "filter_receipt_id",
            _optional_str(self.filter_receipt_id, "filter_receipt_id", max_len=256),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def mark_applied(self, *, filter_receipt_id: str | None = None) -> "PreRankingFilters":
        """Return a copy with ``applied=True`` (filters already executed)."""
        return PreRankingFilters(
            schema_version=self.schema_version,
            tenant_id=self.tenant_id,
            as_of_utc=self.as_of_utc,
            allowed_disclosures=self.allowed_disclosures,
            applied=True,
            denied_provider_call_count=self.denied_provider_call_count,
            filter_receipt_id=filter_receipt_id or self.filter_receipt_id,
            metadata=dict(self.metadata),
        )

    def admits_disclosure(self, disclosure: DisclosureClass | str) -> bool:
        return _coerce_disclosure(disclosure) in self.allowed_disclosures

    def admits_tenant(self, tenant_id: str) -> bool:
        return _identifier(tenant_id, "tenant_id") == self.tenant_id

    def admits_as_of(
        self,
        *,
        effective_from_utc: str | None,
        effective_to_utc: str | None,
    ) -> bool:
        """True when the row's effective interval covers the query as-of time."""
        as_of = self.as_of_utc
        if effective_from_utc is not None:
            start = _iso_utc(effective_from_utc, "effective_from_utc")
            if as_of < start:
                return False
        if effective_to_utc is not None:
            end = _iso_utc(effective_to_utc, "effective_to_utc")
            if as_of > end:
                return False
        return True

    def admit_row(
        self,
        *,
        disclosure: DisclosureClass | str,
        tenant_id: str,
        effective_from_utc: str | None = None,
        effective_to_utc: str | None = None,
    ) -> None:
        """Raise :class:`PreRankingFilterViolation` if the row is inadmissible."""
        if not self.admits_disclosure(disclosure):
            raise PreRankingFilterViolation(
                f"disclosure {disclosure!r} not in allowed set"
            )
        if not self.admits_tenant(tenant_id):
            raise PreRankingFilterViolation(
                f"tenant {tenant_id!r} does not match filter tenant {self.tenant_id!r}"
            )
        if not self.admits_as_of(
            effective_from_utc=effective_from_utc,
            effective_to_utc=effective_to_utc,
        ):
            raise PreRankingFilterViolation(
                f"as-of {self.as_of_utc!r} outside effective interval "
                f"[{effective_from_utc!r}, {effective_to_utc!r}]"
            )

    def require_applied(self) -> None:
        if not self.applied:
            raise MissingPreRankingFiltersError(
                "disclosure/tenant/as-of filters must be applied before scoring"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_disclosures": [d.value for d in self.allowed_disclosures],
            "applied": self.applied,
            "as_of_utc": self.as_of_utc,
            "denied_provider_call_count": self.denied_provider_call_count,
            "filter_receipt_id": self.filter_receipt_id,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreRankingFilters":
        value = _mapping(value, "PreRankingFilters")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "tenant_id",
                    "as_of_utc",
                    "allowed_disclosures",
                    "applied",
                    "denied_provider_call_count",
                    "filter_receipt_id",
                    "metadata",
                }
            ),
            "PreRankingFilters",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            tenant_id=value.get("tenant_id", ""),
            as_of_utc=value.get("as_of_utc", ""),
            allowed_disclosures=tuple(value.get("allowed_disclosures") or ()),
            applied=bool(value.get("applied", False)),
            denied_provider_call_count=int(
                value.get("denied_provider_call_count", 0) or 0
            ),
            filter_receipt_id=value.get("filter_receipt_id"),
            metadata=value.get("metadata") or {},
        )


def require_pre_ranking_filters(filters: PreRankingFilters | None) -> PreRankingFilters:
    """Fail closed when filters are missing or not yet applied."""
    if filters is None:
        raise MissingPreRankingFiltersError(
            "disclosure/tenant/as-of PreRankingFilters are mandatory before scoring"
        )
    if not isinstance(filters, PreRankingFilters):
        raise TypeError("filters must be PreRankingFilters")
    filters.require_applied()
    return filters


# ---------------------------------------------------------------------------
# Ranked hits and fusion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedHit:
    """One ranked retrieval hit joined to source links."""

    document_id: str
    score: float
    rank: int
    family: RetrievalFamily
    source_links: tuple[SourceLink, ...]
    row_id: str | None = None
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND
    matched_fields: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(
            self, "family", _coerce_enum(RetrievalFamily, self.family, "family")
        )
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(self.source_links, "source_links"),
        )
        object.__setattr__(
            self, "row_id", _optional_str(self.row_id, "row_id", max_len=256)
        )
        object.__setattr__(
            self,
            "authority_claim",
            _coerce_enum(AuthorityClaim, self.authority_claim, "authority_claim"),
        )
        object.__setattr__(
            self,
            "matched_fields",
            _tuple_of_str(self.matched_fields, "matched_fields", max_items=32),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "document_id": self.document_id,
            "family": self.family.value,
            "matched_fields": list(self.matched_fields),
            "metadata": dict(self.metadata),
            "rank": self.rank,
            "row_id": self.row_id,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RankedHit":
        value = _mapping(value, "RankedHit")
        _reject_unknown(
            value,
            frozenset(
                {
                    "document_id",
                    "score",
                    "rank",
                    "family",
                    "source_links",
                    "row_id",
                    "authority_claim",
                    "matched_fields",
                    "metadata",
                }
            ),
            "RankedHit",
        )
        return cls(
            document_id=value.get("document_id", ""),
            score=value.get("score", 0.0),
            rank=value.get("rank", 1),
            family=value.get("family", RetrievalFamily.BM25.value),
            source_links=tuple(value.get("source_links") or ()),
            row_id=value.get("row_id"),
            authority_claim=value.get(
                "authority_claim", AuthorityClaim.SOURCE_BOUND.value
            ),
            matched_fields=tuple(value.get("matched_fields") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class FusionWeights:
    """Relative family weights for three-way fusion."""

    bm25: float = 1.0
    vector: float = 1.0
    graph: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "bm25", _nonneg_float(self.bm25, "bm25"))
        object.__setattr__(self, "vector", _nonneg_float(self.vector, "vector"))
        object.__setattr__(self, "graph", _nonneg_float(self.graph, "graph"))
        if self.bm25 + self.vector + self.graph <= 0.0:
            raise ValueError("at least one fusion weight must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return {"bm25": self.bm25, "graph": self.graph, "vector": self.vector}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FusionWeights":
        value = _mapping(value, "FusionWeights")
        _reject_unknown(value, frozenset({"bm25", "vector", "graph"}), "FusionWeights")
        return cls(
            bm25=value.get("bm25", 1.0),
            vector=value.get("vector", 1.0),
            graph=value.get("graph", 1.0),
        )


@dataclass(frozen=True, slots=True)
class FusionResult:
    """Three-way fusion output with mandatory applied pre-ranking filters."""

    schema_version: str
    query_id: str
    filters: PreRankingFilters
    bm25_hits: tuple[RankedHit, ...]
    vector_hits: tuple[RankedHit, ...]
    graph_hits: tuple[RankedHit, ...]
    fused_hits: tuple[RankedHit, ...]
    fusion_weights: FusionWeights
    corpus_cid: str
    config_cid: str
    model_cid: str | None = None
    index_cids: Mapping[str, str] = MappingProxyType({})
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, RETRIEVAL_CONTRACTS_SCHEMA_VERSION, "FusionResult"
            ),
        )
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        if isinstance(self.filters, Mapping):
            object.__setattr__(
                self, "filters", PreRankingFilters.from_dict(self.filters)
            )
        elif not isinstance(self.filters, PreRankingFilters):
            raise TypeError("filters must be PreRankingFilters or mapping")
        # Fusion results may only be constructed after filters ran.
        require_pre_ranking_filters(self.filters)
        object.__setattr__(
            self, "bm25_hits", _tuple_of_ranked_hits(self.bm25_hits, "bm25_hits")
        )
        object.__setattr__(
            self, "vector_hits", _tuple_of_ranked_hits(self.vector_hits, "vector_hits")
        )
        object.__setattr__(
            self, "graph_hits", _tuple_of_ranked_hits(self.graph_hits, "graph_hits")
        )
        object.__setattr__(
            self, "fused_hits", _tuple_of_ranked_hits(self.fused_hits, "fused_hits")
        )
        if isinstance(self.fusion_weights, Mapping):
            object.__setattr__(
                self, "fusion_weights", FusionWeights.from_dict(self.fusion_weights)
            )
        elif not isinstance(self.fusion_weights, FusionWeights):
            raise TypeError("fusion_weights must be FusionWeights or mapping")
        object.__setattr__(self, "corpus_cid", _cid(self.corpus_cid, "corpus_cid"))
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(
            self, "model_cid", _optional_cid(self.model_cid, "model_cid")
        )
        object.__setattr__(
            self,
            "index_cids",
            _frozen_str_map(self.index_cids, "index_cids", max_items=16),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_hits": [h.to_dict() for h in self.bm25_hits],
            "config_cid": self.config_cid,
            "corpus_cid": self.corpus_cid,
            "filters": self.filters.to_dict(),
            "fused_hits": [h.to_dict() for h in self.fused_hits],
            "fusion_weights": self.fusion_weights.to_dict(),
            "graph_hits": [h.to_dict() for h in self.graph_hits],
            "index_cids": dict(self.index_cids),
            "metadata": dict(self.metadata),
            "model_cid": self.model_cid,
            "query_id": self.query_id,
            "schema_version": self.schema_version,
            "vector_hits": [h.to_dict() for h in self.vector_hits],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FusionResult":
        value = _mapping(value, "FusionResult")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "query_id",
                    "filters",
                    "bm25_hits",
                    "vector_hits",
                    "graph_hits",
                    "fused_hits",
                    "fusion_weights",
                    "corpus_cid",
                    "config_cid",
                    "model_cid",
                    "index_cids",
                    "metadata",
                }
            ),
            "FusionResult",
        )
        return cls(
            schema_version=value.get(
                "schema_version", RETRIEVAL_CONTRACTS_SCHEMA_VERSION
            ),
            query_id=value.get("query_id", ""),
            filters=value.get("filters") or {},
            bm25_hits=tuple(value.get("bm25_hits") or ()),
            vector_hits=tuple(value.get("vector_hits") or ()),
            graph_hits=tuple(value.get("graph_hits") or ()),
            fused_hits=tuple(value.get("fused_hits") or ()),
            fusion_weights=value.get("fusion_weights") or {},
            corpus_cid=value.get("corpus_cid", ""),
            config_cid=value.get("config_cid", ""),
            model_cid=value.get("model_cid"),
            index_cids=value.get("index_cids") or {},
            metadata=value.get("metadata") or {},
        )


def _tuple_of_ranked_hits(
    value: Any, field: str, *, max_items: int = 512
) -> tuple[RankedHit, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of RankedHit")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[RankedHit] = []
    for i, item in enumerate(value):
        if isinstance(item, RankedHit):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(RankedHit.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be RankedHit or mapping")
    return tuple(out)


def filter_index_rows(
    rows: Iterable[SourceLinkedIndexRow],
    filters: PreRankingFilters,
) -> tuple[SourceLinkedIndexRow, ...]:
    """Admit only rows that pass disclosure/tenant/as-of; filters must be applied."""
    require_pre_ranking_filters(filters)
    admitted: list[SourceLinkedIndexRow] = []
    for row in rows:
        if not isinstance(row, SourceLinkedIndexRow):
            raise TypeError("rows must contain SourceLinkedIndexRow instances")
        try:
            filters.admit_row(
                disclosure=row.disclosure,
                tenant_id=row.tenant_id,
                effective_from_utc=row.effective_from_utc,
                effective_to_utc=row.effective_to_utc,
            )
        except PreRankingFilterViolation:
            continue
        admitted.append(row)
    return tuple(admitted)


def fuse_ranked_hits(
    *,
    query_id: str,
    filters: PreRankingFilters,
    bm25_hits: Sequence[RankedHit] = (),
    vector_hits: Sequence[RankedHit] = (),
    graph_hits: Sequence[RankedHit] = (),
    fusion_weights: FusionWeights | Mapping[str, float] | None = None,
    corpus_cid: str,
    config_cid: str,
    model_cid: str | None = None,
    index_cids: Mapping[str, str] | None = None,
    top_k: int = 20,
) -> FusionResult:
    """Deterministic weighted-sum fusion after mandatory pre-ranking filters.

    Scores from each family are min-max normalized within the family (when
    more than one hit is present), multiplied by family weights, then summed
    per ``document_id``. Ties break on document_id ascending.
    """
    require_pre_ranking_filters(filters)
    if isinstance(fusion_weights, Mapping) or fusion_weights is None:
        weights = FusionWeights.from_dict(fusion_weights or {})
    else:
        weights = fusion_weights
    top_k = _positive_int(top_k, "top_k")

    def _normalize(hits: Sequence[RankedHit]) -> dict[str, float]:
        if not hits:
            return {}
        scores = {h.document_id: h.score for h in hits}
        values = list(scores.values())
        lo, hi = min(values), max(values)
        span = hi - lo
        if span <= 0.0:
            return {doc: 1.0 for doc in scores}
        return {doc: (score - lo) / span for doc, score in scores.items()}

    bm25_n = _normalize(bm25_hits)
    vector_n = _normalize(vector_hits)
    graph_n = _normalize(graph_hits)
    docs = set(bm25_n) | set(vector_n) | set(graph_n)

    # Preserve first-seen source links / authority from highest-priority family.
    link_bank: dict[str, tuple[SourceLink, ...]] = {}
    claim_bank: dict[str, AuthorityClaim] = {}
    for family_hits in (bm25_hits, vector_hits, graph_hits):
        for hit in family_hits:
            link_bank.setdefault(hit.document_id, hit.source_links)
            claim_bank.setdefault(hit.document_id, hit.authority_claim)

    combined: list[tuple[str, float]] = []
    for doc in docs:
        score = (
            weights.bm25 * bm25_n.get(doc, 0.0)
            + weights.vector * vector_n.get(doc, 0.0)
            + weights.graph * graph_n.get(doc, 0.0)
        )
        combined.append((doc, score))
    combined.sort(key=lambda item: (-item[1], item[0]))

    fused: list[RankedHit] = []
    for rank, (doc, score) in enumerate(combined[:top_k], start=1):
        fused.append(
            RankedHit(
                document_id=doc,
                score=score,
                rank=rank,
                family=RetrievalFamily.FUSION,
                source_links=link_bank[doc],
                authority_claim=claim_bank[doc],
            )
        )

    return FusionResult(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        query_id=query_id,
        filters=filters,
        bm25_hits=tuple(bm25_hits),
        vector_hits=tuple(vector_hits),
        graph_hits=tuple(graph_hits),
        fused_hits=tuple(fused),
        fusion_weights=weights,
        corpus_cid=corpus_cid,
        config_cid=config_cid,
        model_cid=model_cid,
        index_cids=index_cids or {},
    )


__all__ = [
    "RETRIEVAL_CONTRACTS_INTERFACE",
    "RETRIEVAL_CONTRACTS_SCHEMA_VERSION",
    "DEFAULT_FIELD_WEIGHTS",
    "AuthorityClaim",
    "DisclosureClass",
    "EdgeKind",
    "EdgeProvenance",
    "EmbeddingIdentity",
    "FieldWeight",
    "FieldWeightConfig",
    "FusionResult",
    "FusionWeights",
    "GeneratedSummary",
    "GraphEdge",
    "GraphRankHit",
    "IndexField",
    "MissingPreRankingFiltersError",
    "PreRankingFilterViolation",
    "PreRankingFilters",
    "RankedHit",
    "RetrievalContractsError",
    "RetrievalFamily",
    "SourceAuthorityClaimError",
    "SourceLink",
    "SourceLinkedIndexRow",
    "SourceSpan",
    "VectorIndexRow",
    "allow_source_authority_for",
    "assert_authority_claim_allowed",
    "canonical_json",
    "claims_source_authority",
    "filter_index_rows",
    "fuse_ranked_hits",
    "is_private_disclosure",
    "is_public_disclosure",
    "require_pre_ranking_filters",
    "requires_quarantine",
]
