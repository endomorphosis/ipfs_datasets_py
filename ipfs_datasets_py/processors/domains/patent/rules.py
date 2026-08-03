"""Bind prior-art and current-rule review to filing preflight (PATLAW-095).

Produces a fail-closed **decision-support** checklist that merges:

* a dated prior-art search report (PATLAW-094), and
* current-rule / authority source review anchored to an official authority
  view, as-of timestamp, and effective interval,

for use by filing preflight. Forms, fees, and guidance are **separately
labelled** and never elevated above official authority.

Design invariants
-----------------
* Checklist item statuses are ``pass`` / ``fail`` / ``review`` / ``unknown``.
* Conflicts, missing sources, and stale sources **block readiness**.
* Every checklist item cites source CID, span, version, and time.
* The checklist is decision support, not legal advice, not a filing
  authorization, and not a substitute for practitioner judgment.
* Preflight **cannot claim** prior-art search complete without both a dated
  prior-art report and an explicit human coverage acknowledgment bound to
  that report's digest.
* No permanent "latest" year/edition is encoded; as-of is always explicit.
* This module never signs, pays, files, submits an IDS, or decides legal
  strategy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .prior_art import (
    PRIOR_ART_SCHEMA_VERSION,
    PriorArtReport,
    PriorArtSearchPlan,
    content_digest as prior_art_content_digest,
)
from .retrieval_contracts import (
    SourceLink,
    SourceSpan,
)

# ---------------------------------------------------------------------------
# Versions / interface / disclaimers
# ---------------------------------------------------------------------------

RULES_SCHEMA_VERSION: Final = "patent.rules.v1"
RULES_INTERFACE: Final = "PriorArtRuleChecklist@1"
RULES_RULESET_VERSION: Final = "prior-art-rules-preflight@1"

OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST: Final = "prior_art_rule_checklist"
OUTPUT_KIND_FILING_PREFLIGHT_READINESS: Final = "filing_preflight_readiness"

RULES_DISCLAIMER: Final = (
    "This artifact is a filing-preflight decision-support checklist that "
    "binds a dated prior-art report and current-rule source review. Item "
    "statuses (pass/fail/review/unknown) flag readiness blockers for human "
    "review. Forms, fees, and guidance are labelled separately and are not "
    "elevated above official authority. This output is not legal advice, not "
    "a patentability determination, not a filing authorization, not an IDS "
    "submission, and not a substitute for practitioner judgment. A named "
    "human must acknowledge prior-art search coverage before preflight may "
    "claim that a prior-art search is complete."
)

# Forbidden advice / strategy / action language in checklist free text.
_FORBIDDEN_ADVICE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "legal_advice",
        "legal_opinion",
        "patentability",
        "patentability_conclusion",
        "novelty_conclusion",
        "obviousness_conclusion",
        "file_now",
        "should_file",
        "must_file",
        "sign_and_file",
        "submit_ids",
        "auto_ids",
        "legal_strategy",
    }
)

_FORBIDDEN_ADVICE_PHRASES: Final[tuple[str, ...]] = (
    "legal advice",
    "legal opinion",
    "you should file",
    "must file now",
    "sign and file",
    "submit an ids",
    "file an ids",
    "is patentable",
    "is unpatentable",
    "is novel",
    "is obvious",
    "recommend filing",
    "recommended strategy",
)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_LATEST_TOKEN_RE = re.compile(r"\A\s*latest\s*\Z", re.IGNORECASE)

DEFAULT_MAX_ITEMS: Final = 512
DEFAULT_MAX_CITATIONS_PER_ITEM: Final = 32
DEFAULT_MAX_REASON_CODES: Final = 64
DEFAULT_STALE_MAX_AGE_SECONDS: Final = 30 * 24 * 60 * 60  # 30 days

# Machine-readable reason codes that block readiness.
REASON_MISSING_SOURCE: Final = "missing_source"
REASON_STALE_SOURCE: Final = "stale_source"
REASON_CONFLICTING_SOURCES: Final = "conflicting_sources"
REASON_MISSING_CITATION: Final = "missing_citation"
REASON_MISSING_SPAN: Final = "missing_span"
REASON_MISSING_VERSION: Final = "missing_version"
REASON_MISSING_TIME: Final = "missing_time"
REASON_MISSING_PRIOR_ART_REPORT: Final = "missing_prior_art_report"
REASON_MISSING_SEARCH_DATE: Final = "missing_search_date"
REASON_MISSING_HUMAN_COVERAGE_ACK: Final = "missing_human_coverage_acknowledgment"
REASON_ACK_REPORT_MISMATCH: Final = "coverage_ack_report_mismatch"
REASON_COVERAGE_GAPS_UNACKNOWLEDGED: Final = "coverage_gaps_unacknowledged"
REASON_UNKNOWN_ITEM: Final = "unknown_checklist_item"
REASON_FAIL_ITEM: Final = "fail_checklist_item"
REASON_REVIEW_REQUIRED: Final = "review_required"
REASON_OUTSIDE_EFFECTIVE_INTERVAL: Final = "outside_effective_interval"
REASON_HARD_CODED_LATEST: Final = "hard_coded_latest_edition"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RulesError(ValueError):
    """Base error for prior-art / current-rule preflight checklist failures."""

    def __init__(self, message: str, *, code: str = "rules_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class ChecklistCitationError(RulesError):
    """Raised when a checklist item lacks required source/span/version/time."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="checklist_citation_error")


class ReadinessBlockError(RulesError):
    """Raised when readiness is asserted despite blocking conditions."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="readiness_block_error")


class PriorArtSearchCompleteError(RulesError):
    """Raised when prior-art search complete is claimed without prerequisites."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="prior_art_search_complete_error")


class AdviceContentError(RulesError):
    """Raised when checklist content elevates advice or legal strategy."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="advice_content_error")


class HardCodedLatestError(RulesError):
    """Raised when a permanent 'latest' edition/year token is encoded."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="hard_coded_latest_error")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ChecklistStatus(str, Enum):
    """Per-item checklist status (decision support vocabulary)."""

    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    UNKNOWN = "unknown"


class AuthorityLabel(str, Enum):
    """Separately labelled authority surfaces (never conflated)."""

    OFFICIAL = "official"
    FORMS = "forms"
    FEES = "fees"
    GUIDANCE = "guidance"
    PRIOR_ART = "prior_art"
    OTHER = "other"


class ChecklistItemKind(str, Enum):
    """Kinds of checklist entries produced for preflight."""

    OFFICIAL_AUTHORITY = "official_authority"
    FORMS = "forms"
    FEES = "fees"
    GUIDANCE = "guidance"
    PRIOR_ART_REPORT = "prior_art_report"
    PRIOR_ART_COVERAGE = "prior_art_coverage"
    SOURCE_FRESHNESS = "source_freshness"
    SOURCE_CONFLICT = "source_conflict"
    SOURCE_PRESENCE = "source_presence"
    HUMAN_COVERAGE_ACK = "human_coverage_acknowledgment"
    EFFECTIVE_INTERVAL = "effective_interval"
    OTHER = "other"


class SourceHealth(str, Enum):
    """Health of a rule/authority source relative to as-of review."""

    OK = "ok"
    MISSING = "missing"
    STALE = "stale"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class AuthorityViewKind(str, Enum):
    """Which identity surface the current-rule review prefers."""

    OFFICIAL = "official"
    DERIVED = "derived"
    BOTH_SEPARATE = "both_separate"


class ReadinessDisposition(str, Enum):
    """Top-level filing-preflight readiness (fail-closed)."""

    READY = "ready"
    NOT_READY = "not_ready"
    REVIEW_REQUIRED = "review_required"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON (no ``sha256:`` prefix)."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
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


def _iso_date(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=32)
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be ISO calendar date YYYY-MM-DD, got {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _optional_iso_date(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _iso_date(value, field)


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _iso_utc(value, field)


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a lowercase 64-char hex SHA-256")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _sha256_hex(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        try:
            return enum_cls(normalized)
        except ValueError:
            # Accept enum names and underscore/hyphen variants.
            alt = normalized.lower().replace("-", "_")
            for member in enum_cls:
                if member.value == normalized or member.value.replace("-", "_") == alt:
                    return member
                if member.name.lower() == alt:
                    return member
            raise ValueError(f"invalid {field}: {value!r}") from None
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


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


def _schema_pinned(value: Any, expected: str, label: str) -> str:
    text = _require_str(value, f"{label}.schema_version", max_len=64)
    if text != expected:
        raise ValueError(f"{label}.schema_version must be {expected}, got {text!r}")
    return text


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(
        _require_str(item, f"{field}[{i}]", max_len=256)
        for i, item in enumerate(value)
    )


def _reject_hard_coded_latest(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, str) and _LATEST_TOKEN_RE.match(value):
        raise HardCodedLatestError(
            f"{field_name} must not be the hard-coded token 'latest'; "
            "record a concrete edition/version and explicit as-of"
        )


def _parse_utc_to_epoch(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).timestamp()


def _date_from_iso(value: str) -> date:
    return date.fromisoformat(value[:10])


def assert_no_advice_content(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if checklist content elevates advice or legal strategy."""
    if not isinstance(payload, Mapping):
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()  # type: ignore[assignment]
        else:
            raise TypeError("payload must be a mapping or expose to_dict()")
    assert isinstance(payload, Mapping)

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_s = str(key)
                lowered = key_s.lower()
                if lowered in _FORBIDDEN_ADVICE_KEYS:
                    raise AdviceContentError(
                        f"forbidden advice/strategy field at {path}/{key_s}"
                    )
                if isinstance(value, str):
                    lower_val = value.lower()
                    for phrase in _FORBIDDEN_ADVICE_PHRASES:
                        if phrase in lower_val:
                            # Allow the fixed disclaimer to state "not legal advice".
                            if "not legal advice" in lower_val or "not a" in lower_val:
                                if phrase in (
                                    "legal advice",
                                    "legal opinion",
                                    "is patentable",
                                    "is unpatentable",
                                    "is novel",
                                    "is obvious",
                                ) and (
                                    "not legal advice" in lower_val
                                    or "not a patentability" in lower_val
                                    or "not legal opinion" in lower_val
                                ):
                                    continue
                                if (
                                    phrase.startswith("is ")
                                    and f"not {phrase}" in lower_val
                                ):
                                    continue
                            if "not " + phrase in lower_val:
                                continue
                            # Disclaimer may mention the forbidden concepts as negations.
                            if "not " in lower_val and phrase in lower_val:
                                # Conservative: only skip when "not" appears before phrase.
                                idx = lower_val.find(phrase)
                                window = lower_val[max(0, idx - 24) : idx]
                                if "not " in window or "never " in window:
                                    continue
                            raise AdviceContentError(
                                f"forbidden advice phrase {phrase!r} at {path}/{key_s}"
                            )
                _walk(value, f"{path}/{key_s}")
        elif isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray)
        ):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "$")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCitation:
    """Required citation for every checklist item: source/span/version/time.

    ``source_cid`` + exact ``span`` join the item to an immutable artifact.
    ``version`` records edition/release/revision (never ``latest``).
    ``as_of_utc`` and/or ``retrieved_at_utc`` provide the temporal anchor.
    ``effective_start`` / ``effective_end`` capture the official effective
    interval when applicable.
    """

    source_cid: str
    artifact_id: str
    span: SourceSpan
    version: str
    as_of_utc: str
    authority_label: AuthorityLabel = AuthorityLabel.OFFICIAL
    authority_view: AuthorityViewKind = AuthorityViewKind.OFFICIAL
    authority_tier: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None
    retrieved_at_utc: str | None = None
    source_receipt_id: str | None = None
    citation_key: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_cid", _cid(self.source_cid, "source_cid")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.span, SourceSpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
            else:
                raise TypeError("span must be SourceSpan or mapping")
        version = _require_str(self.version, "version", max_len=128)
        _reject_hard_coded_latest(version, field_name="version")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "as_of_utc", _iso_utc(self.as_of_utc, "as_of_utc"))
        object.__setattr__(
            self,
            "authority_label",
            _coerce_enum(AuthorityLabel, self.authority_label, "authority_label"),
        )
        object.__setattr__(
            self,
            "authority_view",
            _coerce_enum(AuthorityViewKind, self.authority_view, "authority_view"),
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )
        object.__setattr__(
            self,
            "effective_start",
            _optional_iso_date(self.effective_start, "effective_start"),
        )
        object.__setattr__(
            self,
            "effective_end",
            _optional_iso_date(self.effective_end, "effective_end"),
        )
        if (
            self.effective_start is not None
            and self.effective_end is not None
            and self.effective_end < self.effective_start
        ):
            raise ValueError("effective_end must be on or after effective_start")
        object.__setattr__(
            self,
            "retrieved_at_utc",
            _optional_iso_utc(self.retrieved_at_utc, "retrieved_at_utc"),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_str(self.source_receipt_id, "source_receipt_id", max_len=256),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        for key in self.metadata:
            _reject_hard_coded_latest(self.metadata[key], field_name=f"metadata[{key}]")

    @property
    def time_anchor_utc(self) -> str:
        """Primary temporal citation (as-of, else retrieved)."""
        return self.as_of_utc

    def to_source_link(self) -> SourceLink:
        return SourceLink(
            source_cid=self.source_cid,
            artifact_id=self.artifact_id,
            span=self.span,
            source_receipt_id=self.source_receipt_id,
            authority_tier=self.authority_tier,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "as_of_utc": self.as_of_utc,
            "authority_label": self.authority_label.value,
            "authority_tier": self.authority_tier,
            "authority_view": self.authority_view.value,
            "citation_key": self.citation_key,
            "effective_end": self.effective_end,
            "effective_start": self.effective_start,
            "metadata": dict(self.metadata),
            "retrieved_at_utc": self.retrieved_at_utc,
            "source_cid": self.source_cid,
            "source_receipt_id": self.source_receipt_id,
            "span": self.span.to_dict(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceCitation":
        value = _mapping(value, "SourceCitation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_id",
                    "as_of_utc",
                    "authority_label",
                    "authority_tier",
                    "authority_view",
                    "citation_key",
                    "effective_end",
                    "effective_start",
                    "metadata",
                    "retrieved_at_utc",
                    "source_cid",
                    "source_receipt_id",
                    "span",
                    "version",
                }
            ),
            "SourceCitation",
        )
        return cls(
            source_cid=value.get("source_cid", ""),
            artifact_id=value.get("artifact_id", ""),
            span=value.get("span") or {},
            version=value.get("version", ""),
            as_of_utc=value.get("as_of_utc", ""),
            authority_label=value.get(
                "authority_label", AuthorityLabel.OFFICIAL.value
            ),
            authority_view=value.get(
                "authority_view", AuthorityViewKind.OFFICIAL.value
            ),
            authority_tier=value.get("authority_tier"),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            retrieved_at_utc=value.get("retrieved_at_utc"),
            source_receipt_id=value.get("source_receipt_id"),
            citation_key=value.get("citation_key"),
            metadata=value.get("metadata") or {},
        )


def _coerce_citations(
    value: Any, field: str, *, max_items: int = DEFAULT_MAX_CITATIONS_PER_ITEM
) -> tuple[SourceCitation, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of SourceCitation/mappings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[SourceCitation] = []
    for i, item in enumerate(value):
        if isinstance(item, SourceCitation):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(SourceCitation.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be SourceCitation or mapping")
    return tuple(out)


def assert_citation_complete(citation: SourceCitation, *, label: str) -> None:
    """Every citation must expose source, span, version, and time."""
    if not citation.source_cid:
        raise ChecklistCitationError(f"{label} missing source_cid")
    if citation.span is None:
        raise ChecklistCitationError(f"{label} missing span")
    if not citation.version:
        raise ChecklistCitationError(f"{label} missing version")
    if not citation.as_of_utc and not citation.retrieved_at_utc:
        raise ChecklistCitationError(f"{label} missing time (as_of_utc/retrieved_at_utc)")


@dataclass(frozen=True, slots=True)
class RuleChecklistItem:
    """One pass/fail/review/unknown checklist entry for filing preflight."""

    item_id: str
    kind: ChecklistItemKind
    status: ChecklistStatus
    authority_label: AuthorityLabel
    title: str
    summary: str
    citations: tuple[SourceCitation, ...]
    blocks_readiness: bool = False
    reason_codes: tuple[str, ...] = ()
    source_health: SourceHealth = SourceHealth.OK
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(ChecklistItemKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "status", _coerce_enum(ChecklistStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "authority_label",
            _coerce_enum(AuthorityLabel, self.authority_label, "authority_label"),
        )
        object.__setattr__(
            self, "title", _require_str(self.title, "title", max_len=512)
        )
        object.__setattr__(
            self, "summary", _require_str(self.summary, "summary", max_len=4096)
        )
        citations = _coerce_citations(self.citations, "citations")
        if not citations:
            raise ChecklistCitationError(
                f"checklist item {self.item_id!r} must cite at least one source"
            )
        for i, citation in enumerate(citations):
            assert_citation_complete(
                citation, label=f"item {self.item_id} citation[{i}]"
            )
        object.__setattr__(self, "citations", citations)
        if not isinstance(self.blocks_readiness, bool):
            raise TypeError("blocks_readiness must be bool")
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=DEFAULT_MAX_REASON_CODES),
        )
        object.__setattr__(
            self,
            "source_health",
            _coerce_enum(SourceHealth, self.source_health, "source_health"),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        # Fail/unknown with unhealthy sources must block readiness.
        if self.source_health in (
            SourceHealth.MISSING,
            SourceHealth.STALE,
            SourceHealth.CONFLICT,
        ):
            if not self.blocks_readiness:
                object.__setattr__(self, "blocks_readiness", True)
        if self.status is ChecklistStatus.FAIL and not self.blocks_readiness:
            # Fail always blocks readiness for preflight decision support.
            object.__setattr__(self, "blocks_readiness", True)
        assert_no_advice_content(
            {
                "title": self.title,
                "summary": self.summary,
                "metadata": dict(self.metadata),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_label": self.authority_label.value,
            "blocks_readiness": self.blocks_readiness,
            "citations": [c.to_dict() for c in self.citations],
            "item_id": self.item_id,
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "reason_codes": list(self.reason_codes),
            "source_health": self.source_health.value,
            "status": self.status.value,
            "summary": self.summary,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleChecklistItem":
        value = _mapping(value, "RuleChecklistItem")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority_label",
                    "blocks_readiness",
                    "citations",
                    "item_id",
                    "kind",
                    "metadata",
                    "reason_codes",
                    "source_health",
                    "status",
                    "summary",
                    "title",
                }
            ),
            "RuleChecklistItem",
        )
        return cls(
            item_id=value.get("item_id", ""),
            kind=value.get("kind", ChecklistItemKind.OTHER.value),
            status=value.get("status", ChecklistStatus.UNKNOWN.value),
            authority_label=value.get(
                "authority_label", AuthorityLabel.OTHER.value
            ),
            title=value.get("title", ""),
            summary=value.get("summary", ""),
            citations=tuple(value.get("citations") or ()),
            blocks_readiness=bool(value.get("blocks_readiness", False)),
            reason_codes=tuple(value.get("reason_codes") or ()),
            source_health=value.get("source_health", SourceHealth.OK.value),
            metadata=value.get("metadata") or {},
        )


def _coerce_items(
    value: Any, field: str, *, max_items: int = DEFAULT_MAX_ITEMS
) -> tuple[RuleChecklistItem, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of RuleChecklistItem/mappings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[RuleChecklistItem] = []
    for i, item in enumerate(value):
        if isinstance(item, RuleChecklistItem):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(RuleChecklistItem.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be RuleChecklistItem or mapping")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class HumanCoverageAcknowledgment:
    """Explicit human acknowledgment of prior-art search coverage scope.

    Required (with a dated prior-art report) before preflight may claim that
    a prior-art search is complete. Bound to the report digest so a changed
    report invalidates the acknowledgment.
    """

    acknowledger_name: str
    acknowledged_at_utc: str
    report_id: str
    report_digest: str
    coverage_scope_text: str
    acknowledges_gaps_visible: bool
    statement: str
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "acknowledger_name",
            _require_str(self.acknowledger_name, "acknowledger_name", max_len=256),
        )
        object.__setattr__(
            self,
            "acknowledged_at_utc",
            _iso_utc(self.acknowledged_at_utc, "acknowledged_at_utc"),
        )
        object.__setattr__(
            self, "report_id", _identifier(self.report_id, "report_id")
        )
        object.__setattr__(
            self, "report_digest", _sha256_hex(self.report_digest, "report_digest")
        )
        object.__setattr__(
            self,
            "coverage_scope_text",
            _require_str(
                self.coverage_scope_text, "coverage_scope_text", max_len=8192
            ),
        )
        if not isinstance(self.acknowledges_gaps_visible, bool):
            raise TypeError("acknowledges_gaps_visible must be bool")
        if not self.acknowledges_gaps_visible:
            raise ValueError(
                "acknowledges_gaps_visible must be True: human must acknowledge "
                "that coverage gaps remain visible"
            )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=4096),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        assert_no_advice_content(
            {
                "coverage_scope_text": self.coverage_scope_text,
                "statement": self.statement,
                "metadata": dict(self.metadata),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledged_at_utc": self.acknowledged_at_utc,
            "acknowledger_name": self.acknowledger_name,
            "acknowledges_gaps_visible": True,
            "coverage_scope_text": self.coverage_scope_text,
            "metadata": dict(self.metadata),
            "report_digest": self.report_digest,
            "report_id": self.report_id,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanCoverageAcknowledgment":
        value = _mapping(value, "HumanCoverageAcknowledgment")
        _reject_unknown(
            value,
            frozenset(
                {
                    "acknowledged_at_utc",
                    "acknowledger_name",
                    "acknowledges_gaps_visible",
                    "coverage_scope_text",
                    "metadata",
                    "report_digest",
                    "report_id",
                    "statement",
                }
            ),
            "HumanCoverageAcknowledgment",
        )
        return cls(
            acknowledger_name=value.get("acknowledger_name", ""),
            acknowledged_at_utc=value.get("acknowledged_at_utc", ""),
            report_id=value.get("report_id", ""),
            report_digest=value.get("report_digest", ""),
            coverage_scope_text=value.get("coverage_scope_text", ""),
            acknowledges_gaps_visible=bool(
                value.get("acknowledges_gaps_visible", False)
            ),
            statement=value.get("statement", ""),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CurrentRuleSourceInput:
    """Input description of one current-rule / authority source under review.

    Callers supply concrete edition/version and identity; this module never
    invents a permanent latest year.
    """

    source_id: str
    source_cid: str
    artifact_id: str
    span: SourceSpan | Mapping[str, Any]
    version: str
    authority_label: AuthorityLabel | str
    as_of_utc: str
    authority_view: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL
    authority_tier: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None
    retrieved_at_utc: str | None = None
    citation_key: str | None = None
    title: str | None = None
    health: SourceHealth | str = SourceHealth.OK
    conflict_group: str | None = None
    source_receipt_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        # Allow empty CID for deliberately missing sources (health=missing).
        health = _coerce_enum(SourceHealth, self.health, "health")
        object.__setattr__(self, "health", health)
        if health is SourceHealth.MISSING:
            cid = _optional_str(self.source_cid, "source_cid", max_len=256) or (
                "missing-source-placeholder-00000000"
            )
            # Keep a placeholder that still passes CID shape for citation
            # completeness when the item must still cite *something* for the gap.
            if not _CID_RE.match(cid):
                cid = "missing-source-placeholder-00000000"
            object.__setattr__(self, "source_cid", cid)
        else:
            object.__setattr__(
                self, "source_cid", _cid(self.source_cid, "source_cid")
            )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.span, SourceSpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
            else:
                raise TypeError("span must be SourceSpan or mapping")
        version = _require_str(self.version, "version", max_len=128)
        _reject_hard_coded_latest(version, field_name="version")
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "authority_label",
            _coerce_enum(AuthorityLabel, self.authority_label, "authority_label"),
        )
        object.__setattr__(self, "as_of_utc", _iso_utc(self.as_of_utc, "as_of_utc"))
        object.__setattr__(
            self,
            "authority_view",
            _coerce_enum(AuthorityViewKind, self.authority_view, "authority_view"),
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )
        object.__setattr__(
            self,
            "effective_start",
            _optional_iso_date(self.effective_start, "effective_start"),
        )
        object.__setattr__(
            self,
            "effective_end",
            _optional_iso_date(self.effective_end, "effective_end"),
        )
        object.__setattr__(
            self,
            "retrieved_at_utc",
            _optional_iso_utc(self.retrieved_at_utc, "retrieved_at_utc"),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self, "title", _optional_str(self.title, "title", max_len=512)
        )
        object.__setattr__(
            self,
            "conflict_group",
            _optional_str(self.conflict_group, "conflict_group", max_len=128),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_str(self.source_receipt_id, "source_receipt_id", max_len=256),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))

    def to_citation(self) -> SourceCitation:
        return SourceCitation(
            source_cid=self.source_cid,
            artifact_id=self.artifact_id,
            span=self.span if isinstance(self.span, SourceSpan) else SourceSpan.from_dict(self.span),
            version=self.version,
            as_of_utc=self.as_of_utc,
            authority_label=self.authority_label,  # type: ignore[arg-type]
            authority_view=self.authority_view,  # type: ignore[arg-type]
            authority_tier=self.authority_tier,
            effective_start=self.effective_start,
            effective_end=self.effective_end,
            retrieved_at_utc=self.retrieved_at_utc,
            source_receipt_id=self.source_receipt_id,
            citation_key=self.citation_key,
            metadata=self.metadata,
        )


@dataclass(frozen=True, slots=True)
class PriorArtRuleChecklist:
    """Filing-preflight checklist binding prior-art + current-rule review.

    ``prior_art_search_complete`` is **never** True unless both a dated
    prior-art report and a matching human coverage acknowledgment are present.
    Conflicts / missing / stale sources force ``readiness`` away from READY.
    """

    schema_version: str
    checklist_id: str
    subject_id: str
    as_of_utc: str
    authority_view: AuthorityViewKind
    items: tuple[RuleChecklistItem, ...]
    readiness: ReadinessDisposition
    prior_art_search_complete: bool
    blocking_reason_codes: tuple[str, ...]
    output_kind: str = OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST
    disclaimer: str = RULES_DISCLAIMER
    ruleset_version: str = RULES_RULESET_VERSION
    prior_art_report_id: str | None = None
    prior_art_report_digest: str | None = None
    prior_art_search_date_utc: str | None = None
    human_coverage_acknowledgment: HumanCoverageAcknowledgment | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, RULES_SCHEMA_VERSION, "PriorArtRuleChecklist"
            ),
        )
        object.__setattr__(
            self, "checklist_id", _identifier(self.checklist_id, "checklist_id")
        )
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(self, "as_of_utc", _iso_utc(self.as_of_utc, "as_of_utc"))
        object.__setattr__(
            self,
            "authority_view",
            _coerce_enum(AuthorityViewKind, self.authority_view, "authority_view"),
        )
        items = _coerce_items(self.items, "items")
        object.__setattr__(self, "items", items)
        object.__setattr__(
            self,
            "readiness",
            _coerce_enum(ReadinessDisposition, self.readiness, "readiness"),
        )
        if not isinstance(self.prior_art_search_complete, bool):
            raise TypeError("prior_art_search_complete must be bool")
        object.__setattr__(
            self,
            "blocking_reason_codes",
            _tuple_of_str(
                self.blocking_reason_codes,
                "blocking_reason_codes",
                max_items=DEFAULT_MAX_REASON_CODES,
            ),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        lower_disc = self.disclaimer.lower()
        if "decision support" not in lower_disc and "decision-support" not in lower_disc:
            raise ValueError("disclaimer must state that this is decision support")
        if "not legal advice" not in lower_disc:
            raise ValueError("disclaimer must state that this is not legal advice")
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self,
            "prior_art_report_id",
            _optional_str(self.prior_art_report_id, "prior_art_report_id", max_len=256),
        )
        object.__setattr__(
            self,
            "prior_art_report_digest",
            _optional_sha256(
                self.prior_art_report_digest, "prior_art_report_digest"
            ),
        )
        object.__setattr__(
            self,
            "prior_art_search_date_utc",
            _optional_iso_utc(
                self.prior_art_search_date_utc, "prior_art_search_date_utc"
            ),
        )
        if self.human_coverage_acknowledgment is not None:
            if isinstance(self.human_coverage_acknowledgment, Mapping):
                object.__setattr__(
                    self,
                    "human_coverage_acknowledgment",
                    HumanCoverageAcknowledgment.from_dict(
                        self.human_coverage_acknowledgment
                    ),
                )
            elif not isinstance(
                self.human_coverage_acknowledgment, HumanCoverageAcknowledgment
            ):
                raise TypeError(
                    "human_coverage_acknowledgment must be "
                    "HumanCoverageAcknowledgment, mapping, or None"
                )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))

        # Gate: prior_art_search_complete requires dated report + human ack.
        if self.prior_art_search_complete:
            _assert_prior_art_search_complete_prerequisites(
                report_id=self.prior_art_report_id,
                report_digest=self.prior_art_report_digest,
                search_date_utc=self.prior_art_search_date_utc,
                human_ack=self.human_coverage_acknowledgment,
            )

        # Gate: READY is incompatible with blocking items / reason codes.
        if self.readiness is ReadinessDisposition.READY:
            blocking_items = [i for i in items if i.blocks_readiness]
            if blocking_items:
                raise ReadinessBlockError(
                    "readiness cannot be ready while blocking checklist items "
                    f"present: {[i.item_id for i in blocking_items[:8]]}"
                )
            if self.blocking_reason_codes:
                raise ReadinessBlockError(
                    "readiness cannot be ready while blocking_reason_codes "
                    f"are non-empty: {list(self.blocking_reason_codes)[:8]}"
                )
            # Conflicts / missing / stale always block (defense in depth).
            for item in items:
                if item.source_health in (
                    SourceHealth.MISSING,
                    SourceHealth.STALE,
                    SourceHealth.CONFLICT,
                ):
                    raise ReadinessBlockError(
                        f"readiness cannot be ready: item {item.item_id} has "
                        f"source_health={item.source_health.value}"
                    )

        # Every item must cite source/span/version/time (re-assert).
        assert_checklist_items_cite_sources(items)
        assert_no_advice_content(self.to_dict())

    @property
    def is_ready(self) -> bool:
        return self.readiness is ReadinessDisposition.READY

    @property
    def blocking_items(self) -> tuple[RuleChecklistItem, ...]:
        return tuple(i for i in self.items if i.blocks_readiness)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_utc": self.as_of_utc,
            "authority_view": self.authority_view.value,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "checklist_id": self.checklist_id,
            "disclaimer": self.disclaimer,
            "human_coverage_acknowledgment": (
                None
                if self.human_coverage_acknowledgment is None
                else self.human_coverage_acknowledgment.to_dict()
            ),
            "items": [i.to_dict() for i in self.items],
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "prior_art_report_digest": self.prior_art_report_digest,
            "prior_art_report_id": self.prior_art_report_id,
            "prior_art_search_complete": self.prior_art_search_complete,
            "prior_art_search_date_utc": self.prior_art_search_date_utc,
            "readiness": self.readiness.value,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PriorArtRuleChecklist":
        value = _mapping(value, "PriorArtRuleChecklist")
        _reject_unknown(
            value,
            frozenset(
                {
                    "as_of_utc",
                    "authority_view",
                    "blocking_reason_codes",
                    "checklist_id",
                    "disclaimer",
                    "human_coverage_acknowledgment",
                    "items",
                    "metadata",
                    "output_kind",
                    "prior_art_report_digest",
                    "prior_art_report_id",
                    "prior_art_search_complete",
                    "prior_art_search_date_utc",
                    "readiness",
                    "ruleset_version",
                    "schema_version",
                    "subject_id",
                }
            ),
            "PriorArtRuleChecklist",
        )
        return cls(
            schema_version=value.get("schema_version", RULES_SCHEMA_VERSION),
            checklist_id=value.get("checklist_id", ""),
            subject_id=value.get("subject_id", ""),
            as_of_utc=value.get("as_of_utc", ""),
            authority_view=value.get(
                "authority_view", AuthorityViewKind.OFFICIAL.value
            ),
            items=tuple(value.get("items") or ()),
            readiness=value.get(
                "readiness", ReadinessDisposition.NOT_READY.value
            ),
            prior_art_search_complete=bool(
                value.get("prior_art_search_complete", False)
            ),
            blocking_reason_codes=tuple(value.get("blocking_reason_codes") or ()),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST
            ),
            disclaimer=value.get("disclaimer", RULES_DISCLAIMER),
            ruleset_version=value.get("ruleset_version", RULES_RULESET_VERSION),
            prior_art_report_id=value.get("prior_art_report_id"),
            prior_art_report_digest=value.get("prior_art_report_digest"),
            prior_art_search_date_utc=value.get("prior_art_search_date_utc"),
            human_coverage_acknowledgment=value.get(
                "human_coverage_acknowledgment"
            ),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class FilingPreflightReadiness:
    """Compact readiness projection for workflow / preflight consumers."""

    schema_version: str
    readiness_id: str
    checklist_id: str
    subject_id: str
    readiness: ReadinessDisposition
    prior_art_search_complete: bool
    blocking_reason_codes: tuple[str, ...]
    blocking_item_ids: tuple[str, ...]
    as_of_utc: str
    output_kind: str = OUTPUT_KIND_FILING_PREFLIGHT_READINESS
    disclaimer: str = RULES_DISCLAIMER
    checklist_digest: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, RULES_SCHEMA_VERSION, "FilingPreflightReadiness"
            ),
        )
        object.__setattr__(
            self, "readiness_id", _identifier(self.readiness_id, "readiness_id")
        )
        object.__setattr__(
            self, "checklist_id", _identifier(self.checklist_id, "checklist_id")
        )
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self,
            "readiness",
            _coerce_enum(ReadinessDisposition, self.readiness, "readiness"),
        )
        if not isinstance(self.prior_art_search_complete, bool):
            raise TypeError("prior_art_search_complete must be bool")
        if self.prior_art_search_complete and self.readiness is ReadinessDisposition.READY:
            # Still decision support — READY does not authorize filing.
            pass
        object.__setattr__(
            self,
            "blocking_reason_codes",
            _tuple_of_str(
                self.blocking_reason_codes,
                "blocking_reason_codes",
                max_items=DEFAULT_MAX_REASON_CODES,
            ),
        )
        object.__setattr__(
            self,
            "blocking_item_ids",
            _tuple_of_str(
                self.blocking_item_ids, "blocking_item_ids", max_items=DEFAULT_MAX_ITEMS
            ),
        )
        object.__setattr__(self, "as_of_utc", _iso_utc(self.as_of_utc, "as_of_utc"))
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_FILING_PREFLIGHT_READINESS:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_FILING_PREFLIGHT_READINESS!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self,
            "checklist_digest",
            _optional_sha256(self.checklist_digest, "checklist_digest"),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        if (
            self.readiness is ReadinessDisposition.READY
            and self.blocking_reason_codes
        ):
            raise ReadinessBlockError(
                "FilingPreflightReadiness cannot be ready with blocking codes"
            )
        if self.readiness is ReadinessDisposition.READY and self.blocking_item_ids:
            raise ReadinessBlockError(
                "FilingPreflightReadiness cannot be ready with blocking items"
            )
        assert_no_advice_content(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_utc": self.as_of_utc,
            "blocking_item_ids": list(self.blocking_item_ids),
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "checklist_digest": self.checklist_digest,
            "checklist_id": self.checklist_id,
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "prior_art_search_complete": self.prior_art_search_complete,
            "readiness": self.readiness.value,
            "readiness_id": self.readiness_id,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingPreflightReadiness":
        value = _mapping(value, "FilingPreflightReadiness")
        _reject_unknown(
            value,
            frozenset(
                {
                    "as_of_utc",
                    "blocking_item_ids",
                    "blocking_reason_codes",
                    "checklist_digest",
                    "checklist_id",
                    "disclaimer",
                    "metadata",
                    "output_kind",
                    "prior_art_search_complete",
                    "readiness",
                    "readiness_id",
                    "schema_version",
                    "subject_id",
                }
            ),
            "FilingPreflightReadiness",
        )
        return cls(
            schema_version=value.get("schema_version", RULES_SCHEMA_VERSION),
            readiness_id=value.get("readiness_id", ""),
            checklist_id=value.get("checklist_id", ""),
            subject_id=value.get("subject_id", ""),
            readiness=value.get(
                "readiness", ReadinessDisposition.NOT_READY.value
            ),
            prior_art_search_complete=bool(
                value.get("prior_art_search_complete", False)
            ),
            blocking_reason_codes=tuple(value.get("blocking_reason_codes") or ()),
            blocking_item_ids=tuple(value.get("blocking_item_ids") or ()),
            as_of_utc=value.get("as_of_utc", ""),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_FILING_PREFLIGHT_READINESS
            ),
            disclaimer=value.get("disclaimer", RULES_DISCLAIMER),
            checklist_digest=value.get("checklist_digest"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------


def evaluate_source_health(
    source: CurrentRuleSourceInput,
    *,
    as_of_utc: str,
    stale_max_age_seconds: int = DEFAULT_STALE_MAX_AGE_SECONDS,
    conflict_members: Sequence[str] = (),
) -> SourceHealth:
    """Derive source health from missing / conflict / staleness signals."""
    if source.health is SourceHealth.MISSING:
        return SourceHealth.MISSING
    if source.health is SourceHealth.CONFLICT:
        return SourceHealth.CONFLICT
    if conflict_members and source.conflict_group:
        if len(set(conflict_members)) > 1:
            return SourceHealth.CONFLICT
    # Explicit stale flag wins.
    if source.health is SourceHealth.STALE:
        return SourceHealth.STALE
    # Effective-interval check against as-of calendar date.
    as_of_date = _date_from_iso(as_of_utc)
    if source.effective_start is not None:
        start = _date_from_iso(source.effective_start)
        if as_of_date < start:
            return SourceHealth.UNKNOWN
    if source.effective_end is not None:
        end = _date_from_iso(source.effective_end)
        if as_of_date > end:
            return SourceHealth.STALE
    # Retrieval age vs as-of.
    if source.retrieved_at_utc is not None:
        age = _parse_utc_to_epoch(as_of_utc) - _parse_utc_to_epoch(
            source.retrieved_at_utc
        )
        if age > stale_max_age_seconds:
            return SourceHealth.STALE
        if age < 0:
            # Future retrieval relative to as-of is unknown.
            return SourceHealth.UNKNOWN
    if source.health is SourceHealth.UNKNOWN:
        return SourceHealth.UNKNOWN
    return SourceHealth.OK


def _kind_for_label(label: AuthorityLabel) -> ChecklistItemKind:
    if label is AuthorityLabel.OFFICIAL:
        return ChecklistItemKind.OFFICIAL_AUTHORITY
    if label is AuthorityLabel.FORMS:
        return ChecklistItemKind.FORMS
    if label is AuthorityLabel.FEES:
        return ChecklistItemKind.FEES
    if label is AuthorityLabel.GUIDANCE:
        return ChecklistItemKind.GUIDANCE
    if label is AuthorityLabel.PRIOR_ART:
        return ChecklistItemKind.PRIOR_ART_REPORT
    return ChecklistItemKind.OTHER


def _status_for_health(health: SourceHealth) -> ChecklistStatus:
    if health is SourceHealth.OK:
        return ChecklistStatus.PASS
    if health is SourceHealth.MISSING:
        return ChecklistStatus.FAIL
    if health is SourceHealth.STALE:
        return ChecklistStatus.FAIL
    if health is SourceHealth.CONFLICT:
        return ChecklistStatus.FAIL
    return ChecklistStatus.UNKNOWN


def _reason_for_health(health: SourceHealth) -> str | None:
    if health is SourceHealth.MISSING:
        return REASON_MISSING_SOURCE
    if health is SourceHealth.STALE:
        return REASON_STALE_SOURCE
    if health is SourceHealth.CONFLICT:
        return REASON_CONFLICTING_SOURCES
    if health is SourceHealth.UNKNOWN:
        return REASON_UNKNOWN_ITEM
    return None


def build_rule_checklist_item_from_source(
    source: CurrentRuleSourceInput,
    *,
    as_of_utc: str,
    stale_max_age_seconds: int = DEFAULT_STALE_MAX_AGE_SECONDS,
    conflict_members: Sequence[str] = (),
    item_id: str | None = None,
) -> RuleChecklistItem:
    """Project one current-rule source into a cited checklist item."""
    health = evaluate_source_health(
        source,
        as_of_utc=as_of_utc,
        stale_max_age_seconds=stale_max_age_seconds,
        conflict_members=conflict_members,
    )
    label = source.authority_label  # type: ignore[assignment]
    assert isinstance(label, AuthorityLabel)
    status = _status_for_health(health)
    reason = _reason_for_health(health)
    reasons: list[str] = []
    if reason:
        reasons.append(reason)
    # Outside effective interval (future) is review/unknown, not pass.
    as_of_date = _date_from_iso(as_of_utc)
    if source.effective_start is not None and as_of_date < _date_from_iso(
        source.effective_start
    ):
        reasons.append(REASON_OUTSIDE_EFFECTIVE_INTERVAL)
        if status is ChecklistStatus.PASS:
            status = ChecklistStatus.UNKNOWN
    blocks = health in (
        SourceHealth.MISSING,
        SourceHealth.STALE,
        SourceHealth.CONFLICT,
    ) or status in (ChecklistStatus.FAIL, ChecklistStatus.UNKNOWN)
    # Pass guidance/forms/fees never block by themselves when healthy.
    if status is ChecklistStatus.PASS and health is SourceHealth.OK:
        blocks = False
    title = source.title or source.citation_key or source.source_id
    summary = (
        f"Current-rule source {source.source_id} labelled {label.value} "
        f"with health={health.value} under authority_view="
        f"{source.authority_view.value if isinstance(source.authority_view, AuthorityViewKind) else source.authority_view} "
        f"as_of={as_of_utc}; effective_interval="
        f"[{source.effective_start or 'open'}, {source.effective_end or 'open'}]; "
        f"version={source.version}."
    )
    return RuleChecklistItem(
        item_id=item_id or f"item:source:{source.source_id}",
        kind=_kind_for_label(label),
        status=status,
        authority_label=label,
        title=title,
        summary=summary,
        citations=(source.to_citation(),),
        blocks_readiness=blocks,
        reason_codes=tuple(reasons),
        source_health=health,
        metadata={
            "source_id": source.source_id,
            **(
                {"conflict_group": source.conflict_group}
                if source.conflict_group
                else {}
            ),
        },
    )


def _assert_prior_art_search_complete_prerequisites(
    *,
    report_id: str | None,
    report_digest: str | None,
    search_date_utc: str | None,
    human_ack: HumanCoverageAcknowledgment | None,
) -> None:
    if not report_id:
        raise PriorArtSearchCompleteError(
            "prior_art_search_complete requires a dated prior-art report_id"
        )
    if not report_digest:
        raise PriorArtSearchCompleteError(
            "prior_art_search_complete requires prior_art_report_digest"
        )
    if not search_date_utc:
        raise PriorArtSearchCompleteError(
            "prior_art_search_complete requires prior_art_search_date_utc "
            "(dated report)"
        )
    if human_ack is None:
        raise PriorArtSearchCompleteError(
            "prior_art_search_complete requires explicit human coverage "
            "acknowledgment"
        )
    if human_ack.report_id != report_id:
        raise PriorArtSearchCompleteError(
            "human coverage acknowledgment report_id must match the prior-art "
            "report"
        )
    if human_ack.report_digest != report_digest:
        raise PriorArtSearchCompleteError(
            "human coverage acknowledgment report_digest must match the "
            "prior-art report digest"
        )
    if not human_ack.acknowledges_gaps_visible:
        raise PriorArtSearchCompleteError(
            "human coverage acknowledgment must acknowledge that coverage gaps "
            "remain visible"
        )


def prior_art_search_complete_allowed(
    *,
    report: PriorArtReport | None,
    report_digest: str | None,
    human_ack: HumanCoverageAcknowledgment | None,
) -> bool:
    """Return whether preflight may claim prior-art search complete.

    Requires a dated prior-art report and an explicit human coverage
    acknowledgment bound to that report's digest. Never raises; use
    :func:`assert_prior_art_search_complete_allowed` to fail closed.
    """
    try:
        assert_prior_art_search_complete_allowed(
            report=report,
            report_digest=report_digest,
            human_ack=human_ack,
        )
        return True
    except PriorArtSearchCompleteError:
        return False


def assert_prior_art_search_complete_allowed(
    *,
    report: PriorArtReport | None,
    report_digest: str | None,
    human_ack: HumanCoverageAcknowledgment | None,
) -> None:
    """Fail closed if prior-art search complete is claimed without prerequisites."""
    if report is None:
        raise PriorArtSearchCompleteError(
            "prior_art_search_complete requires a dated PriorArtReport"
        )
    search_date = report.search_date_utc
    digest = report_digest or content_digest(report.to_dict())
    _assert_prior_art_search_complete_prerequisites(
        report_id=report.report_id,
        report_digest=digest,
        search_date_utc=search_date,
        human_ack=human_ack,
    )


def assert_checklist_items_cite_sources(
    items: Sequence[RuleChecklistItem],
) -> None:
    """Every item must cite source CID, span, version, and time."""
    if not items:
        raise ChecklistCitationError(
            "checklist must contain at least one cited item for preflight"
        )
    for item in items:
        if not item.citations:
            raise ChecklistCitationError(
                f"item {item.item_id} missing citations (source/span/version/time)"
            )
        for i, citation in enumerate(item.citations):
            assert_citation_complete(
                citation, label=f"item {item.item_id} citation[{i}]"
            )


def compute_readiness(
    items: Sequence[RuleChecklistItem],
    *,
    prior_art_search_complete: bool = False,
) -> tuple[ReadinessDisposition, tuple[str, ...]]:
    """Derive readiness disposition and blocking reason codes from items.

    Conflicts / missing / stale sources always contribute blocking codes.
    Ready is only returned when no item blocks readiness.
    """
    codes: list[str] = []
    has_fail = False
    has_review = False
    has_unknown = False
    for item in items:
        if item.source_health is SourceHealth.MISSING:
            codes.append(REASON_MISSING_SOURCE)
            has_fail = True
        if item.source_health is SourceHealth.STALE:
            codes.append(REASON_STALE_SOURCE)
            has_fail = True
        if item.source_health is SourceHealth.CONFLICT:
            codes.append(REASON_CONFLICTING_SOURCES)
            has_fail = True
        if item.status is ChecklistStatus.FAIL:
            has_fail = True
            if REASON_FAIL_ITEM not in codes:
                codes.append(REASON_FAIL_ITEM)
        if item.status is ChecklistStatus.REVIEW:
            has_review = True
            if REASON_REVIEW_REQUIRED not in codes:
                codes.append(REASON_REVIEW_REQUIRED)
        if item.status is ChecklistStatus.UNKNOWN:
            has_unknown = True
            if REASON_UNKNOWN_ITEM not in codes:
                codes.append(REASON_UNKNOWN_ITEM)
        for code in item.reason_codes:
            if code not in codes and item.blocks_readiness:
                codes.append(code)
    blocking = [i for i in items if i.blocks_readiness]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)

    if blocking or has_fail:
        return ReadinessDisposition.NOT_READY, tuple(ordered)
    if has_review or has_unknown:
        if REASON_REVIEW_REQUIRED not in ordered:
            ordered.append(REASON_REVIEW_REQUIRED)
        return ReadinessDisposition.REVIEW_REQUIRED, tuple(ordered)
    # Even when items pass, prior_art_search_complete is independent.
    _ = prior_art_search_complete
    return ReadinessDisposition.READY, tuple(ordered)


def _prior_art_report_items(
    report: PriorArtReport | None,
    *,
    as_of_utc: str,
    report_digest: str | None,
    human_ack: HumanCoverageAcknowledgment | None,
    report_source_cid: str | None = None,
    report_artifact_id: str | None = None,
) -> list[RuleChecklistItem]:
    """Build checklist items covering the prior-art report binding."""
    items: list[RuleChecklistItem] = []
    # Synthetic span for the report artifact binding (byte range of digest).
    report_span = SourceSpan(start=0, end=64, unit="byte")
    cid = report_source_cid or (
        f"bafybeipriorartreport{ (report.report_id if report else 'missing').replace(':', '')[:24].ljust(24, '0') }"
    )
    # Ensure CID shape.
    if not _CID_RE.match(cid):
        cid = "bafybeipriorartreport0000000000000000000000"
    artifact = report_artifact_id or (
        f"artifact:prior-art-report:{(report.report_id if report else 'none')}"
    )
    if not _NONEMPTY_ID_RE.match(artifact):
        artifact = "artifact:prior-art-report:none"

    if report is None:
        citation = SourceCitation(
            source_cid=cid,
            artifact_id=artifact,
            span=report_span,
            version="absent",
            as_of_utc=as_of_utc,
            authority_label=AuthorityLabel.PRIOR_ART,
            authority_view=AuthorityViewKind.OFFICIAL,
            authority_tier="candidate",
            retrieved_at_utc=as_of_utc,
            citation_key="prior-art-report:missing",
        )
        items.append(
            RuleChecklistItem(
                item_id="item:prior-art-report:missing",
                kind=ChecklistItemKind.PRIOR_ART_REPORT,
                status=ChecklistStatus.FAIL,
                authority_label=AuthorityLabel.PRIOR_ART,
                title="Prior-art report missing",
                summary=(
                    "No dated prior-art report is bound to this preflight "
                    "checklist; prior-art search cannot be claimed complete."
                ),
                citations=(citation,),
                blocks_readiness=True,
                reason_codes=(REASON_MISSING_PRIOR_ART_REPORT,),
                source_health=SourceHealth.MISSING,
            )
        )
        return items

    digest = report_digest or content_digest(report.to_dict())
    version = report.schema_version or PRIOR_ART_SCHEMA_VERSION
    citation = SourceCitation(
        source_cid=cid,
        artifact_id=artifact,
        span=report_span,
        version=version,
        as_of_utc=as_of_utc,
        authority_label=AuthorityLabel.PRIOR_ART,
        authority_view=AuthorityViewKind.OFFICIAL,
        authority_tier="candidate",
        retrieved_at_utc=report.search_date_utc,
        citation_key=report.report_id,
        metadata={
            "report_id": report.report_id,
            "report_digest": digest,
            "search_date_utc": report.search_date_utc,
            "filing_date": report.filing_date,
            "priority_date": report.priority_date,
        },
    )
    items.append(
        RuleChecklistItem(
            item_id=f"item:prior-art-report:{report.report_id}",
            kind=ChecklistItemKind.PRIOR_ART_REPORT,
            status=ChecklistStatus.PASS,
            authority_label=AuthorityLabel.PRIOR_ART,
            title="Dated prior-art report bound",
            summary=(
                f"Prior-art report {report.report_id} dated "
                f"{report.search_date_utc} is bound for preflight review "
                f"(digest={digest[:16]}…)."
            ),
            citations=(citation,),
            blocks_readiness=False,
            reason_codes=(),
            source_health=SourceHealth.OK,
            metadata={"report_digest": digest},
        )
    )

    # Coverage gaps remain visible — always produce a review item.
    gap_kinds = sorted({g.kind.value for g in report.coverage_gaps})
    gap_summary = (
        "Prior-art coverage gaps remain visible for human review: "
        + (", ".join(gap_kinds) if gap_kinds else "none recorded")
        + ". Gaps are decision-support signals only."
    )
    items.append(
        RuleChecklistItem(
            item_id=f"item:prior-art-coverage:{report.report_id}",
            kind=ChecklistItemKind.PRIOR_ART_COVERAGE,
            status=ChecklistStatus.REVIEW,
            authority_label=AuthorityLabel.PRIOR_ART,
            title="Prior-art coverage gaps visible",
            summary=gap_summary,
            citations=(citation,),
            blocks_readiness=True,  # human must review search scope
            reason_codes=(REASON_REVIEW_REQUIRED,),
            source_health=SourceHealth.OK,
            metadata={"gap_kinds": ",".join(gap_kinds) if gap_kinds else "none"},
        )
    )

    # Human coverage acknowledgment item.
    if human_ack is None:
        items.append(
            RuleChecklistItem(
                item_id="item:human-coverage-ack:missing",
                kind=ChecklistItemKind.HUMAN_COVERAGE_ACK,
                status=ChecklistStatus.FAIL,
                authority_label=AuthorityLabel.PRIOR_ART,
                title="Human coverage acknowledgment missing",
                summary=(
                    "Explicit human acknowledgment of prior-art search coverage "
                    "scope is required before preflight may claim the search "
                    "complete."
                ),
                citations=(citation,),
                blocks_readiness=True,
                reason_codes=(REASON_MISSING_HUMAN_COVERAGE_ACK,),
                source_health=SourceHealth.MISSING,
            )
        )
    else:
        ack_ok = (
            human_ack.report_id == report.report_id
            and human_ack.report_digest == digest
            and human_ack.acknowledges_gaps_visible
        )
        reasons: list[str] = []
        if human_ack.report_id != report.report_id or human_ack.report_digest != digest:
            reasons.append(REASON_ACK_REPORT_MISMATCH)
        if not human_ack.acknowledges_gaps_visible:
            reasons.append(REASON_COVERAGE_GAPS_UNACKNOWLEDGED)
        ack_slug = re.sub(
            r"[^A-Za-z0-9._:/=+\-]+",
            "-",
            human_ack.acknowledger_name.strip(),
        ).strip("-") or "human"
        items.append(
            RuleChecklistItem(
                item_id=f"item:human-coverage-ack:{ack_slug}",
                kind=ChecklistItemKind.HUMAN_COVERAGE_ACK,
                status=ChecklistStatus.PASS if ack_ok else ChecklistStatus.FAIL,
                authority_label=AuthorityLabel.PRIOR_ART,
                title="Human coverage acknowledgment",
                summary=(
                    f"Human {human_ack.acknowledger_name} acknowledged coverage "
                    f"at {human_ack.acknowledged_at_utc} for report "
                    f"{human_ack.report_id}."
                ),
                citations=(citation,),
                blocks_readiness=not ack_ok,
                reason_codes=tuple(reasons),
                source_health=SourceHealth.OK if ack_ok else SourceHealth.CONFLICT,
                metadata={
                    "acknowledger_name": human_ack.acknowledger_name,
                    "report_digest": human_ack.report_digest,
                },
            )
        )
        # When human has acknowledged gaps, coverage is recorded as PASS for
        # readiness (gaps remain visible in metadata/summary) so preflight can
        # become READY once conflicts/missing/stale sources are cleared.
        if ack_ok:
            items = [
                (
                    RuleChecklistItem(
                        item_id=it.item_id,
                        kind=it.kind,
                        status=ChecklistStatus.PASS,
                        authority_label=it.authority_label,
                        title=it.title,
                        summary=(
                            it.summary
                            + " Human coverage acknowledgment recorded; gaps "
                            "remain visible as decision-support context."
                        ),
                        citations=it.citations,
                        blocks_readiness=False,
                        reason_codes=(),
                        source_health=it.source_health,
                        metadata=it.metadata,
                    )
                    if it.kind is ChecklistItemKind.PRIOR_ART_COVERAGE
                    else it
                )
                for it in items
            ]
    return items


def build_prior_art_rule_checklist(
    *,
    subject_id: str,
    as_of_utc: str,
    authority_sources: Sequence[CurrentRuleSourceInput] = (),
    prior_art_report: PriorArtReport | None = None,
    prior_art_report_digest: str | None = None,
    human_coverage_acknowledgment: HumanCoverageAcknowledgment | None = None,
    authority_view: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
    checklist_id: str | None = None,
    stale_max_age_seconds: int = DEFAULT_STALE_MAX_AGE_SECONDS,
    report_source_cid: str | None = None,
    report_artifact_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
    claim_prior_art_search_complete: bool | None = None,
) -> PriorArtRuleChecklist:
    """Build the prior-art + current-rule preflight checklist.

    Parameters
    ----------
    subject_id:
        Matter / application subject identifier.
    as_of_utc:
        Explicit as-of timestamp for current-rule review (never implicit latest).
    authority_sources:
        Official / forms / fees / guidance sources under review.
    prior_art_report:
        Optional dated prior-art report (PATLAW-094).
    human_coverage_acknowledgment:
        Explicit human acknowledgment of search coverage scope.
    claim_prior_art_search_complete:
        If True, fail closed unless report + human ack prerequisites hold.
        If None (default), compute automatically from prerequisites.
        If False, force the claim off.
    """
    as_of = _iso_utc(as_of_utc, "as_of_utc")
    view = _coerce_enum(AuthorityViewKind, authority_view, "authority_view")
    assert isinstance(view, AuthorityViewKind)

    report_digest: str | None = None
    report_id: str | None = None
    search_date: str | None = None
    if prior_art_report is not None:
        if not isinstance(prior_art_report, PriorArtReport):
            if isinstance(prior_art_report, Mapping):
                prior_art_report = PriorArtReport.from_dict(prior_art_report)
            else:
                raise TypeError(
                    "prior_art_report must be PriorArtReport, mapping, or None"
                )
        report_id = prior_art_report.report_id
        report_digest = prior_art_report_digest or content_digest(
            prior_art_report.to_dict()
        )
        search_date = prior_art_report.search_date_utc

    if human_coverage_acknowledgment is not None and isinstance(
        human_coverage_acknowledgment, Mapping
    ):
        human_coverage_acknowledgment = HumanCoverageAcknowledgment.from_dict(
            human_coverage_acknowledgment
        )

    items: list[RuleChecklistItem] = []

    # Conflict groups: multiple distinct CIDs/versions under same group.
    group_members: dict[str, list[str]] = {}
    for src in authority_sources:
        if not isinstance(src, CurrentRuleSourceInput):
            raise TypeError(
                "authority_sources must contain CurrentRuleSourceInput instances"
            )
        if src.conflict_group:
            group_members.setdefault(src.conflict_group, []).append(
                f"{src.source_cid}|{src.version}"
            )

    for src in authority_sources:
        members = group_members.get(src.conflict_group or "", ())
        items.append(
            build_rule_checklist_item_from_source(
                src,
                as_of_utc=as_of,
                stale_max_age_seconds=stale_max_age_seconds,
                conflict_members=members,
            )
        )

    items.extend(
        _prior_art_report_items(
            prior_art_report,
            as_of_utc=as_of,
            report_digest=report_digest,
            human_ack=human_coverage_acknowledgment,
            report_source_cid=report_source_cid,
            report_artifact_id=report_artifact_id,
        )
    )

    if claim_prior_art_search_complete is False:
        complete = False
    elif claim_prior_art_search_complete is True:
        assert_prior_art_search_complete_allowed(
            report=prior_art_report,
            report_digest=report_digest,
            human_ack=human_coverage_acknowledgment,
        )
        complete = True
    else:
        complete = prior_art_search_complete_allowed(
            report=prior_art_report,
            report_digest=report_digest,
            human_ack=human_coverage_acknowledgment,
        )

    readiness, blocking_codes = compute_readiness(
        items, prior_art_search_complete=complete
    )

    # If complete is False because ack/report missing, ensure codes present.
    if not complete:
        if prior_art_report is None and REASON_MISSING_PRIOR_ART_REPORT not in blocking_codes:
            blocking_codes = blocking_codes + (REASON_MISSING_PRIOR_ART_REPORT,)
        if (
            human_coverage_acknowledgment is None
            and REASON_MISSING_HUMAN_COVERAGE_ACK not in blocking_codes
        ):
            blocking_codes = blocking_codes + (REASON_MISSING_HUMAN_COVERAGE_ACK,)

    digest_short = content_digest(
        {
            "subject_id": subject_id,
            "as_of_utc": as_of,
            "item_ids": [i.item_id for i in items],
            "report_id": report_id,
        }
    )[:16]
    resolved_id = checklist_id or f"checklist:preflight:{digest_short}"

    return PriorArtRuleChecklist(
        schema_version=RULES_SCHEMA_VERSION,
        checklist_id=resolved_id,
        subject_id=subject_id,
        as_of_utc=as_of,
        authority_view=view,
        items=tuple(items),
        readiness=readiness,
        prior_art_search_complete=complete,
        blocking_reason_codes=blocking_codes,
        prior_art_report_id=report_id,
        prior_art_report_digest=report_digest,
        prior_art_search_date_utc=search_date,
        human_coverage_acknowledgment=human_coverage_acknowledgment,
        metadata=metadata or {},
    )


def project_filing_preflight_readiness(
    checklist: PriorArtRuleChecklist,
    *,
    readiness_id: str | None = None,
) -> FilingPreflightReadiness:
    """Project a compact readiness record from a full checklist."""
    if not isinstance(checklist, PriorArtRuleChecklist):
        if isinstance(checklist, Mapping):
            checklist = PriorArtRuleChecklist.from_dict(checklist)
        else:
            raise TypeError("checklist must be PriorArtRuleChecklist or mapping")
    digest = content_digest(checklist.to_dict())
    rid = readiness_id or f"readiness:{checklist.checklist_id}"
    return FilingPreflightReadiness(
        schema_version=RULES_SCHEMA_VERSION,
        readiness_id=rid,
        checklist_id=checklist.checklist_id,
        subject_id=checklist.subject_id,
        readiness=checklist.readiness,
        prior_art_search_complete=checklist.prior_art_search_complete,
        blocking_reason_codes=checklist.blocking_reason_codes,
        blocking_item_ids=tuple(i.item_id for i in checklist.blocking_items),
        as_of_utc=checklist.as_of_utc,
        checklist_digest=digest,
    )


def build_human_coverage_acknowledgment(
    *,
    acknowledger_name: str,
    acknowledged_at_utc: str,
    report: PriorArtReport,
    coverage_scope_text: str,
    statement: str | None = None,
    report_digest: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> HumanCoverageAcknowledgment:
    """Build a human coverage acknowledgment bound to a dated report."""
    if not isinstance(report, PriorArtReport):
        if isinstance(report, Mapping):
            report = PriorArtReport.from_dict(report)
        else:
            raise TypeError("report must be PriorArtReport or mapping")
    digest = report_digest or content_digest(report.to_dict())
    default_statement = (
        f"I, {acknowledger_name}, reviewed the prior-art search scope and "
        f"visible coverage gaps for report {report.report_id} dated "
        f"{report.search_date_utc}. Coverage gaps remain visible. This is a "
        f"coverage acknowledgment for decision support only, not legal advice."
    )
    return HumanCoverageAcknowledgment(
        acknowledger_name=acknowledger_name,
        acknowledged_at_utc=acknowledged_at_utc,
        report_id=report.report_id,
        report_digest=digest,
        coverage_scope_text=coverage_scope_text,
        acknowledges_gaps_visible=True,
        statement=statement or default_statement,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "RULES_DISCLAIMER",
    "RULES_INTERFACE",
    "RULES_RULESET_VERSION",
    "RULES_SCHEMA_VERSION",
    "OUTPUT_KIND_FILING_PREFLIGHT_READINESS",
    "OUTPUT_KIND_PRIOR_ART_RULE_CHECKLIST",
    "DEFAULT_STALE_MAX_AGE_SECONDS",
    "REASON_ACK_REPORT_MISMATCH",
    "REASON_CONFLICTING_SOURCES",
    "REASON_COVERAGE_GAPS_UNACKNOWLEDGED",
    "REASON_FAIL_ITEM",
    "REASON_HARD_CODED_LATEST",
    "REASON_MISSING_CITATION",
    "REASON_MISSING_HUMAN_COVERAGE_ACK",
    "REASON_MISSING_PRIOR_ART_REPORT",
    "REASON_MISSING_SEARCH_DATE",
    "REASON_MISSING_SOURCE",
    "REASON_MISSING_SPAN",
    "REASON_MISSING_TIME",
    "REASON_MISSING_VERSION",
    "REASON_OUTSIDE_EFFECTIVE_INTERVAL",
    "REASON_REVIEW_REQUIRED",
    "REASON_STALE_SOURCE",
    "REASON_UNKNOWN_ITEM",
    "AdviceContentError",
    "AuthorityLabel",
    "AuthorityViewKind",
    "ChecklistCitationError",
    "ChecklistItemKind",
    "ChecklistStatus",
    "CurrentRuleSourceInput",
    "FilingPreflightReadiness",
    "HardCodedLatestError",
    "HumanCoverageAcknowledgment",
    "PriorArtRuleChecklist",
    "PriorArtSearchCompleteError",
    "ReadinessBlockError",
    "ReadinessDisposition",
    "RuleChecklistItem",
    "RulesError",
    "SourceCitation",
    "SourceHealth",
    "assert_checklist_items_cite_sources",
    "assert_citation_complete",
    "assert_no_advice_content",
    "assert_prior_art_search_complete_allowed",
    "build_human_coverage_acknowledgment",
    "build_prior_art_rule_checklist",
    "build_rule_checklist_item_from_source",
    "canonical_json",
    "compute_readiness",
    "content_digest",
    "evaluate_source_health",
    "prior_art_search_complete_allowed",
    "project_filing_preflight_readiness",
    # re-export useful prior-art types for integration tests
    "PriorArtReport",
    "PriorArtSearchPlan",
    "prior_art_content_digest",
    "SourceLink",
    "SourceSpan",
]
