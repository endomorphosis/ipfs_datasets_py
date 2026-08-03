"""USPTO identifier parsing and normalization.

Parse and normalize application, publication, patent, confirmation, and
customer identifiers without conflating kinds. Ambiguous or invalid values
are rejected (strict mode) or returned unresolved. Display and compact
formatting round-trip through a single canonical representation.

These helpers build on :class:`ApplicationIdentity` from contracts but own
kind-specific parsing, check-digit validation where applicable, and
unresolved-ambiguity signaling. No provider I/O or storage backends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ApplicationIdentity,
    canonical_json,
)

IDENTIFIERS_SCHEMA_VERSION: Final = "uspto.identifiers.v1"
IDENTIFIERS_INTERFACE: Final = "UsptoIdentifiers@1"

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Series (2 digits) / serial (6 digits), optional commas in serial.
_APP_DISPLAY_RE = re.compile(
    r"\A\s*(?P<series>\d{2})\s*/\s*(?P<serial>\d{1,3}(?:,\d{3}){0,1}|\d{6})\s*"
    r"(?:[\-/]?(?P<check>\d))?\s*\Z"
)
# Compact 8-digit application (+ optional check digit).
_APP_COMPACT_RE = re.compile(r"\A\s*(?P<body>\d{8})(?P<check>\d)?\s*\Z")

# US publication: US YYYY/NNNNNNN kind, or compact USYYYYNNNNNNNkind.
_PUB_DISPLAY_RE = re.compile(
    r"\A\s*(?:US\s*)?(?P<year>\d{4})\s*/\s*(?P<seq>\d{1,3}(?:,\d{3}){1,2}|\d{7})\s*"
    r"(?P<kind>[A-Z]\d)?\s*\Z",
    re.IGNORECASE,
)
_PUB_COMPACT_RE = re.compile(
    r"\A\s*(?:US)?(?P<year>\d{4})(?P<seq>\d{7})(?P<kind>[A-Z]\d)?\s*\Z",
    re.IGNORECASE,
)

# Utility patent digits (with optional commas); design/plant/reissue prefixes.
_PATENT_UTILITY_RE = re.compile(
    r"\A\s*(?P<body>\d{1,3}(?:,\d{3})+|\d{4,8})\s*\Z"
)
_PATENT_PREFIXED_RE = re.compile(
    r"\A\s*(?P<prefix>D|PP|RE|X|H|T|AI)\s*(?P<body>\d{1,3}(?:,\d{3})*|\d{1,8})\s*\Z",
    re.IGNORECASE,
)

_CONFIRMATION_RE = re.compile(r"\A\s*(?P<body>\d{4})\s*\Z")
_CUSTOMER_RE = re.compile(r"\A\s*(?P<body>\d{3,6})\s*\Z")

# Strip common noise for pre-classification.
_NOISE_RE = re.compile(r"[\s\u00a0]+")


class IdentifierKind(str, Enum):
    """Distinct USPTO identifier families — never conflated."""

    APPLICATION = "application"
    PUBLICATION = "publication"
    PATENT = "patent"
    CONFIRMATION = "confirmation"
    CUSTOMER = "customer"


class IdentifierStatus(str, Enum):
    """Resolution outcome for a parse attempt."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


class IdentifierError(ValueError):
    """Raised when a strict parse rejects an identifier."""

    def __init__(
        self,
        message: str,
        *,
        kind: IdentifierKind | str | None = None,
        raw: str | None = None,
        code: str = "identifier_rejected",
    ) -> None:
        super().__init__(message)
        self.kind = kind.value if isinstance(kind, IdentifierKind) else kind
        self.raw = raw
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"code": self.code, "message": str(self)}
        if self.kind is not None:
            out["kind"] = self.kind
        if self.raw is not None:
            # Bound length; raw identifiers are not private document text.
            out["raw"] = self.raw[:128]
        return out


@dataclass(frozen=True, slots=True)
class NormalizedIdentifier:
    """Canonical form of a single-kind USPTO identifier.

    ``compact`` and ``display`` are empty when ``status`` is not RESOLVED.
    Check-digit validity is ``None`` when no check digit was supplied or the
    kind has no check-digit rule.
    """

    schema_version: str
    kind: IdentifierKind
    raw_input: str
    status: IdentifierStatus
    compact: str
    display: str
    components: Mapping[str, str]
    check_digit_valid: bool | None
    confidence: float | None
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != IDENTIFIERS_SCHEMA_VERSION:
            raise ValueError(
                f"NormalizedIdentifier.schema_version must be {IDENTIFIERS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "kind", _coerce_enum(IdentifierKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "raw_input", _require_str(self.raw_input, "raw_input", max_len=128)
        )
        object.__setattr__(
            self, "status", _coerce_enum(IdentifierStatus, self.status, "status")
        )
        object.__setattr__(
            self, "compact", _require_str_allow_empty(self.compact, "compact", max_len=64)
        )
        object.__setattr__(
            self, "display", _require_str_allow_empty(self.display, "display", max_len=64)
        )
        object.__setattr__(
            self,
            "components",
            _frozen_str_map(self.components, "components", max_items=16),
        )
        if self.check_digit_valid is not None and not isinstance(
            self.check_digit_valid, bool
        ):
            raise TypeError("check_digit_valid must be bool or None")
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )
        if self.status is IdentifierStatus.RESOLVED:
            if not self.compact or not self.display:
                raise ValueError("resolved identifiers require compact and display forms")
        else:
            if self.compact or self.display:
                raise ValueError(
                    "unresolved/invalid identifiers must not carry compact/display forms"
                )

    @property
    def is_resolved(self) -> bool:
        return self.status is IdentifierStatus.RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_digit_valid": self.check_digit_valid,
            "compact": self.compact,
            "components": dict(self.components),
            "confidence": self.confidence,
            "display": self.display,
            "kind": self.kind.value,
            "notes": list(self.notes),
            "raw_input": self.raw_input,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedIdentifier":
        value = _mapping(value, "NormalizedIdentifier")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "raw_input",
                    "status",
                    "compact",
                    "display",
                    "components",
                    "check_digit_valid",
                    "confidence",
                    "notes",
                }
            ),
            "NormalizedIdentifier",
        )
        return cls(
            schema_version=value.get("schema_version", IDENTIFIERS_SCHEMA_VERSION),
            kind=value.get("kind", IdentifierKind.APPLICATION.value),
            raw_input=value.get("raw_input", ""),
            status=value.get("status", IdentifierStatus.INVALID.value),
            compact=value.get("compact", ""),
            display=value.get("display", ""),
            components=value.get("components") or {},
            check_digit_valid=value.get("check_digit_valid"),
            confidence=value.get("confidence"),
            notes=tuple(value.get("notes") or ()),
        )


# ---------------------------------------------------------------------------
# Public parse / format API
# ---------------------------------------------------------------------------


def application_check_digit(eight_digit_body: str) -> str:
    """Return the USPTO-style check digit for an 8-digit application body.

    Weights digits left-to-right by 1..8; check digit is the sum modulo 10.
    """
    digits = _digits_only(eight_digit_body)
    if len(digits) != 8 or not digits.isdigit():
        raise IdentifierError(
            "application check digit requires exactly 8 digits",
            kind=IdentifierKind.APPLICATION,
            raw=eight_digit_body,
            code="check_digit_input_invalid",
        )
    total = sum(int(d) * (i + 1) for i, d in enumerate(digits))
    return str(total % 10)


def normalize_application_number(
    raw: str,
    *,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Normalize a U.S. application number (series/serial).

    Accepts ``16/123,456``, ``16/123456``, ``16123456``, and optional trailing
    check digit. Invalid structure → INVALID (or raises if ``strict``).
    """
    text = _prep(raw)
    if not text:
        return _finish_invalid(
            IdentifierKind.APPLICATION, raw, "empty_application_number", strict=strict
        )

    series: str | None = None
    serial: str | None = None
    check: str | None = None
    notes: list[str] = []

    m = _APP_DISPLAY_RE.match(text)
    if m:
        series = m.group("series")
        serial = _digits_only(m.group("serial"))
        check = m.group("check")
    else:
        m2 = _APP_COMPACT_RE.match(text)
        if m2:
            body = m2.group("body")
            series, serial = body[:2], body[2:]
            check = m2.group("check")
        else:
            return _finish_invalid(
                IdentifierKind.APPLICATION,
                raw,
                "unrecognized_application_number_format",
                strict=strict,
            )

    # Require a full six-digit serial; do not left-pad short fragments.
    if len(serial) != 6:
        return _finish_invalid(
            IdentifierKind.APPLICATION,
            raw,
            "application_serial_must_be_six_digits",
            strict=strict,
        )

    body = f"{series}{serial}"
    check_valid: bool | None = None
    if check is not None:
        expected = application_check_digit(body)
        check_valid = check == expected
        if not check_valid:
            if strict:
                raise IdentifierError(
                    f"application check digit mismatch: got {check}, expected {expected}",
                    kind=IdentifierKind.APPLICATION,
                    raw=str(raw),
                    code="check_digit_mismatch",
                )
            return NormalizedIdentifier(
                schema_version=IDENTIFIERS_SCHEMA_VERSION,
                kind=IdentifierKind.APPLICATION,
                raw_input=str(raw),
                status=IdentifierStatus.INVALID,
                compact="",
                display="",
                components={
                    "series": series,
                    "serial": serial,
                    "check_digit_supplied": check,
                    "check_digit_expected": expected,
                },
                check_digit_valid=False,
                confidence=0.0,
                notes=("check_digit_mismatch",),
            )
        notes.append("check_digit_verified")

    display = f"{series}/{serial[:3]},{serial[3:]}"
    components = {"series": series, "serial": serial}
    if check is not None:
        components["check_digit"] = check

    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=IdentifierKind.APPLICATION,
        raw_input=str(raw),
        status=IdentifierStatus.RESOLVED,
        compact=body,
        display=display,
        components=components,
        check_digit_valid=check_valid,
        confidence=1.0 if check_valid is not False else 0.0,
        notes=tuple(notes) if notes else ("normalized",),
    )


def normalize_publication_number(
    raw: str,
    *,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Normalize a U.S. pre-grant publication number."""
    text = _prep(raw)
    if not text:
        return _finish_invalid(
            IdentifierKind.PUBLICATION, raw, "empty_publication_number", strict=strict
        )

    # Prefer explicit US marker handling: strip leading US for regexes that
    # already treat it as optional.
    m = _PUB_DISPLAY_RE.match(text)
    year: str
    seq: str
    kind_code: str | None
    if m:
        year = m.group("year")
        seq = _digits_only(m.group("seq")).zfill(7)
        kind_code = (m.group("kind") or "").upper() or None
    else:
        m2 = _PUB_COMPACT_RE.match(text)
        if not m2:
            return _finish_invalid(
                IdentifierKind.PUBLICATION,
                raw,
                "unrecognized_publication_number_format",
                strict=strict,
            )
        year = m2.group("year")
        seq = m2.group("seq")
        kind_code = (m2.group("kind") or "").upper() or None

    if len(seq) != 7:
        return _finish_invalid(
            IdentifierKind.PUBLICATION,
            raw,
            "publication_sequence_must_be_seven_digits",
            strict=strict,
        )
    if not (2001 <= int(year) <= 2100):
        # Pre-2001 US pre-grant publications do not exist under this scheme.
        return _finish_invalid(
            IdentifierKind.PUBLICATION,
            raw,
            "publication_year_out_of_range",
            strict=strict,
        )

    compact = f"US{year}{seq}" + (kind_code or "")
    # Display: US YYYY/N,NNN,NNN [kind] — keep all seven sequence digits.
    seq_disp = f"{seq[0]},{seq[1:4]},{seq[4:7]}"
    display = f"US {year}/{seq_disp}"
    if kind_code:
        display = f"{display} {kind_code}"

    components: dict[str, str] = {"year": year, "sequence": seq}
    if kind_code:
        components["kind_code"] = kind_code

    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=IdentifierKind.PUBLICATION,
        raw_input=str(raw),
        status=IdentifierStatus.RESOLVED,
        compact=compact,
        display=display,
        components=components,
        check_digit_valid=None,
        confidence=1.0,
        notes=("normalized",),
    )


def normalize_patent_number(
    raw: str,
    *,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Normalize a U.S. patent number (utility, design, plant, reissue, …)."""
    text = _prep(raw)
    if not text:
        return _finish_invalid(
            IdentifierKind.PATENT, raw, "empty_patent_number", strict=strict
        )

    prefix = ""
    body_digits: str

    m = _PATENT_PREFIXED_RE.match(text)
    if m:
        raw_prefix = m.group("prefix").upper()
        if raw_prefix in {"D", "X", "H", "T", "PP", "RE", "AI"}:
            prefix = raw_prefix
        else:
            return _finish_invalid(
                IdentifierKind.PATENT,
                raw,
                "unrecognized_patent_prefix",
                strict=strict,
            )
        body_digits = _digits_only(m.group("body"))
    else:
        m2 = _PATENT_UTILITY_RE.match(text)
        if not m2:
            return _finish_invalid(
                IdentifierKind.PATENT,
                raw,
                "unrecognized_patent_number_format",
                strict=strict,
            )
        prefix = ""
        body_digits = _digits_only(m2.group("body"))

    if not body_digits or len(body_digits) > 8:
        return _finish_invalid(
            IdentifierKind.PATENT,
            raw,
            "patent_number_digit_length_invalid",
            strict=strict,
        )
    # Utility patents are at least 1 digit historically; reject leading-zero-only
    # noise for unprefixed numbers that are too short to be meaningful alone
    # when they look like confirmation/customer (handled by disambiguation).
    if not prefix and len(body_digits) < 4:
        return _finish_invalid(
            IdentifierKind.PATENT,
            raw,
            "utility_patent_number_too_short",
            strict=strict,
        )

    compact = f"{prefix}{body_digits}"
    if prefix:
        display = f"{prefix}{int(body_digits):,}"
    else:
        display = f"{int(body_digits):,}"

    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=IdentifierKind.PATENT,
        raw_input=str(raw),
        status=IdentifierStatus.RESOLVED,
        compact=compact,
        display=display,
        components={"prefix": prefix, "number": body_digits},
        check_digit_valid=None,
        confidence=1.0,
        notes=("normalized",),
    )


def normalize_confirmation_number(
    raw: str,
    *,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Normalize a 4-digit USPTO confirmation number."""
    text = _prep(raw)
    if not text:
        return _finish_invalid(
            IdentifierKind.CONFIRMATION, raw, "empty_confirmation_number", strict=strict
        )
    m = _CONFIRMATION_RE.match(text)
    if not m:
        return _finish_invalid(
            IdentifierKind.CONFIRMATION,
            raw,
            "confirmation_number_must_be_four_digits",
            strict=strict,
        )
    body = m.group("body")
    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=IdentifierKind.CONFIRMATION,
        raw_input=str(raw),
        status=IdentifierStatus.RESOLVED,
        compact=body,
        display=body,
        components={"number": body},
        check_digit_valid=None,
        confidence=1.0,
        notes=("normalized",),
    )


def normalize_customer_number(
    raw: str,
    *,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Normalize a USPTO customer number (3–6 digits)."""
    text = _prep(raw)
    if not text:
        return _finish_invalid(
            IdentifierKind.CUSTOMER, raw, "empty_customer_number", strict=strict
        )
    m = _CUSTOMER_RE.match(text)
    if not m:
        return _finish_invalid(
            IdentifierKind.CUSTOMER,
            raw,
            "customer_number_must_be_three_to_six_digits",
            strict=strict,
        )
    body = m.group("body")
    # Preserve significant leading zeros only if originally present with fixed width.
    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=IdentifierKind.CUSTOMER,
        raw_input=str(raw),
        status=IdentifierStatus.RESOLVED,
        compact=body,
        display=body,
        components={"number": body},
        check_digit_valid=None,
        confidence=1.0,
        notes=("normalized",),
    )


_KIND_NORMALIZERS = {
    IdentifierKind.APPLICATION: normalize_application_number,
    IdentifierKind.PUBLICATION: normalize_publication_number,
    IdentifierKind.PATENT: normalize_patent_number,
    IdentifierKind.CONFIRMATION: normalize_confirmation_number,
    IdentifierKind.CUSTOMER: normalize_customer_number,
}


def parse_identifier(
    raw: str,
    *,
    kind: IdentifierKind | str | None = None,
    strict: bool = False,
) -> NormalizedIdentifier:
    """Parse ``raw`` as ``kind``, or attempt disambiguation when kind is omitted.

    When ``kind`` is omitted and more than one family matches with equal
    confidence, returns UNRESOLVED rather than guessing. Invalid input for a
    declared kind returns INVALID (or raises if ``strict``).
    """
    if kind is not None:
        coerced = _coerce_enum(IdentifierKind, kind, "kind")
        return _KIND_NORMALIZERS[coerced](raw, strict=strict)

    text = _prep(raw)
    if not text:
        return NormalizedIdentifier(
            schema_version=IDENTIFIERS_SCHEMA_VERSION,
            kind=IdentifierKind.APPLICATION,
            raw_input=str(raw) if raw is not None else "",
            status=IdentifierStatus.INVALID,
            compact="",
            display="",
            components={},
            check_digit_valid=None,
            confidence=0.0,
            notes=("empty_identifier",),
        )

    candidates: list[NormalizedIdentifier] = []
    # Order: highly distinctive formats first.
    for k in (
        IdentifierKind.PUBLICATION,
        IdentifierKind.APPLICATION,
        IdentifierKind.PATENT,
        IdentifierKind.CONFIRMATION,
        IdentifierKind.CUSTOMER,
    ):
        result = _KIND_NORMALIZERS[k](raw, strict=False)
        if result.status is IdentifierStatus.RESOLVED:
            candidates.append(result)

    if not candidates:
        if strict:
            raise IdentifierError(
                "identifier did not match any known USPTO family",
                raw=str(raw),
                code="unrecognized_identifier",
            )
        return NormalizedIdentifier(
            schema_version=IDENTIFIERS_SCHEMA_VERSION,
            kind=IdentifierKind.APPLICATION,
            raw_input=str(raw),
            status=IdentifierStatus.INVALID,
            compact="",
            display="",
            components={},
            check_digit_valid=None,
            confidence=0.0,
            notes=("unrecognized_identifier",),
        )

    if len(candidates) == 1:
        return candidates[0]

    # Prefer more distinctive kinds when multiple parsers succeed.
    # Application with slash is distinctive vs patent digits.
    distinctive = [
        c
        for c in candidates
        if c.kind in (IdentifierKind.PUBLICATION, IdentifierKind.APPLICATION)
        and ("/" in text or c.kind is IdentifierKind.PUBLICATION and text.upper().startswith("US"))
    ]
    # Prefixed patents (D/PP/RE) are distinctive.
    prefixed_patent = [
        c
        for c in candidates
        if c.kind is IdentifierKind.PATENT and c.components.get("prefix")
    ]
    if len(distinctive) == 1 and not prefixed_patent:
        return distinctive[0]
    if len(prefixed_patent) == 1 and not distinctive:
        return prefixed_patent[0]

    # Digit-only collisions: application compact vs patent vs customer vs confirmation.
    kinds = tuple(sorted({c.kind.value for c in candidates}))
    if strict:
        raise IdentifierError(
            f"ambiguous identifier matches multiple kinds: {kinds}",
            raw=str(raw),
            code="ambiguous_identifier",
        )
    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=candidates[0].kind,
        raw_input=str(raw),
        status=IdentifierStatus.UNRESOLVED,
        compact="",
        display="",
        components={"candidate_kinds": ",".join(kinds)},
        check_digit_valid=None,
        confidence=None,
        notes=("ambiguous_identifier", f"candidates={','.join(kinds)}"),
    )


def format_identifier(
    value: NormalizedIdentifier | Mapping[str, Any],
    *,
    style: str = "display",
) -> str:
    """Return display or compact formatting; round-trips with parse for RESOLVED."""
    if isinstance(value, Mapping):
        value = NormalizedIdentifier.from_dict(value)
    if not isinstance(value, NormalizedIdentifier):
        raise TypeError("value must be NormalizedIdentifier or mapping")
    if value.status is not IdentifierStatus.RESOLVED:
        raise IdentifierError(
            "cannot format unresolved or invalid identifier",
            kind=value.kind,
            raw=value.raw_input,
            code="format_unresolved",
        )
    if style == "display":
        return value.display
    if style == "compact":
        return value.compact
    raise ValueError(f"unknown format style: {style!r}")


def build_application_identity(
    *,
    application: str | NormalizedIdentifier | None = None,
    publication: str | NormalizedIdentifier | None = None,
    patent: str | NormalizedIdentifier | None = None,
    confirmation: str | NormalizedIdentifier | None = None,
    customer: str | NormalizedIdentifier | None = None,
    source: str,
    confidence: float | None = None,
    strict: bool = False,
    extra_notes: Sequence[str] = (),
) -> ApplicationIdentity:
    """Build an :class:`ApplicationIdentity` from raw or normalized parts.

    Confirmation and customer numbers are recorded in ``notes`` (the contract
    identity record does not yet have dedicated fields) and never overwrite
    application/publication/patent slots. Any UNRESOLVED component sets
    ``unresolved_ambiguity``; INVALID components raise when ``strict`` else
    contribute unresolved ambiguity and notes.
    """
    notes: list[str] = list(extra_notes)
    unresolved = False
    app_num: str | None = None
    pub_num: str | None = None
    pat_num: str | None = None
    confidences: list[float] = []

    def _resolve(
        raw: str | NormalizedIdentifier | None,
        kind: IdentifierKind,
        normalizer,
    ) -> NormalizedIdentifier | None:
        nonlocal unresolved
        if raw is None:
            return None
        if isinstance(raw, NormalizedIdentifier):
            ident = raw
            if ident.kind is not kind and ident.status is IdentifierStatus.RESOLVED:
                raise IdentifierError(
                    f"identifier kind {ident.kind.value} cannot fill {kind.value} slot",
                    kind=kind,
                    raw=ident.raw_input,
                    code="kind_slot_mismatch",
                )
        else:
            ident = normalizer(raw, strict=strict)
        if ident.status is IdentifierStatus.RESOLVED:
            if ident.confidence is not None:
                confidences.append(ident.confidence)
            return ident
        if ident.status is IdentifierStatus.UNRESOLVED:
            unresolved = True
            notes.append(f"{kind.value}:unresolved")
            notes.extend(ident.notes)
            return ident
        # INVALID
        if strict:
            raise IdentifierError(
                f"invalid {kind.value} identifier",
                kind=kind,
                raw=str(raw) if not isinstance(raw, NormalizedIdentifier) else raw.raw_input,
                code="invalid_component",
            )
        unresolved = True
        notes.append(f"{kind.value}:invalid")
        notes.extend(ident.notes)
        return ident

    app_ident = _resolve(application, IdentifierKind.APPLICATION, normalize_application_number)
    pub_ident = _resolve(publication, IdentifierKind.PUBLICATION, normalize_publication_number)
    pat_ident = _resolve(patent, IdentifierKind.PATENT, normalize_patent_number)
    conf_ident = _resolve(
        confirmation, IdentifierKind.CONFIRMATION, normalize_confirmation_number
    )
    cust_ident = _resolve(customer, IdentifierKind.CUSTOMER, normalize_customer_number)

    if app_ident and app_ident.is_resolved:
        app_num = app_ident.display
    if pub_ident and pub_ident.is_resolved:
        pub_num = pub_ident.display
    if pat_ident and pat_ident.is_resolved:
        pat_num = pat_ident.display
    if conf_ident and conf_ident.is_resolved:
        notes.append(f"confirmation:{conf_ident.compact}")
    if cust_ident and cust_ident.is_resolved:
        notes.append(f"customer:{cust_ident.compact}")

    if not any((app_num, pub_num, pat_num)):
        if strict:
            raise IdentifierError(
                "ApplicationIdentity requires at least one resolved application, "
                "publication, or patent number",
                code="identity_incomplete",
            )
        # Still cannot construct ApplicationIdentity without a core number.
        # Surface as unresolved by using a placeholder only when we refuse —
        # raise a soft IdentifierError that callers can catch, matching
        # "rejected or returned unresolved".
        raise IdentifierError(
            "no resolved application/publication/patent identifier",
            code="identity_incomplete",
        )

    if confidence is None and confidences:
        confidence = min(confidences)
    if unresolved and confidence is not None:
        confidence = min(confidence, 0.5)

    return ApplicationIdentity(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        application_number=app_num,
        publication_number=pub_num,
        patent_number=pat_num,
        source=source,
        confidence=confidence,
        unresolved_ambiguity=unresolved,
        notes=tuple(dict.fromkeys(notes)),  # stable de-dupe, preserve order
    )


def round_trip_identifier(
    raw: str,
    *,
    kind: IdentifierKind | str,
    style: str = "display",
) -> NormalizedIdentifier:
    """Parse, format, re-parse; returns the second parse (must match first)."""
    first = parse_identifier(raw, kind=kind, strict=True)
    formatted = format_identifier(first, style=style)
    second = parse_identifier(formatted, kind=kind, strict=True)
    if first.compact != second.compact or first.display != second.display:
        raise IdentifierError(
            "identifier formatting failed to round-trip",
            kind=kind,
            raw=str(raw),
            code="round_trip_mismatch",
        )
    return second


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prep(raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise TypeError(f"identifier raw must be str, got {type(raw).__name__}")
    return _NOISE_RE.sub(" ", raw).strip()


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _finish_invalid(
    kind: IdentifierKind,
    raw: Any,
    code: str,
    *,
    strict: bool,
) -> NormalizedIdentifier:
    if strict:
        raise IdentifierError(
            code.replace("_", " "),
            kind=kind,
            raw=str(raw) if raw is not None else "",
            code=code,
        )
    return NormalizedIdentifier(
        schema_version=IDENTIFIERS_SCHEMA_VERSION,
        kind=kind,
        raw_input=str(raw) if raw is not None else "",
        status=IdentifierStatus.INVALID,
        compact="",
        display="",
        components={},
        check_digit_valid=None,
        confidence=0.0,
        notes=(code,),
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


def _require_str_allow_empty(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return number


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(str(key), f"{field}.key", max_len=128)
        if not isinstance(raw, str):
            raw = str(raw)
        if len(raw) > 2048:
            raise ValueError(f"{field}[{k}] exceeds max length 2048")
        out[k] = raw
    return MappingProxyType(dict(sorted(out.items())))


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")


__all__ = [
    "IDENTIFIERS_INTERFACE",
    "IDENTIFIERS_SCHEMA_VERSION",
    "IdentifierError",
    "IdentifierKind",
    "IdentifierStatus",
    "NormalizedIdentifier",
    "application_check_digit",
    "build_application_identity",
    "canonical_json",
    "format_identifier",
    "normalize_application_number",
    "normalize_confirmation_number",
    "normalize_customer_number",
    "normalize_patent_number",
    "normalize_publication_number",
    "parse_identifier",
    "round_trip_identifier",
]
