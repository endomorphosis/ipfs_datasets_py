"""Versioned protected ODP application-status vocabulary (PATLAW-124).

Only codes listed in the protected vocabulary are treated as **known**.
Unknown numeric codes (and other unrecognized tokens) return
``unknown`` / ``quarantine`` recognition rather than being accepted as
known solely because they fall in a broad integer range.

Raw upstream codes and description text are always retained by callers;
this module never rewrites or drops them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    ApplicationLifecyclePhase,
    RejectionDisposition,
)

STATUS_VOCABULARY_SCHEMA_VERSION: Final = "uspto.odp.status-vocabulary.v1"
STATUS_VOCABULARY_INTERFACE: Final = "OdpStatusVocabulary@1"


class StatusCodeRecognition(str, Enum):
    """Whether a status code is admitted by the protected vocabulary."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    QUARANTINE = "quarantine"


@dataclass(frozen=True, slots=True)
class StatusVocabularyEntry:
    """One protected vocabulary row."""

    code: str
    description: str
    lifecycle_phase: ApplicationLifecyclePhase
    rejection_disposition: RejectionDisposition = RejectionDisposition.NONE
    is_pending: bool | None = True
    is_abandoned: bool | None = False
    is_allowed: bool | None = False
    is_patented: bool | None = False
    is_appealed: bool | None = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "is_abandoned": self.is_abandoned,
            "is_allowed": self.is_allowed,
            "is_appealed": self.is_appealed,
            "is_patented": self.is_patented,
            "is_pending": self.is_pending,
            "lifecycle_phase": self.lifecycle_phase.value,
            "notes": list(self.notes),
            "rejection_disposition": self.rejection_disposition.value,
        }


@dataclass(frozen=True, slots=True)
class StatusCodeClassification:
    """Result of classifying an upstream application status code."""

    schema_version: str
    raw_code: str | None
    normalized_code: str | None
    recognition: StatusCodeRecognition
    entry: StatusVocabularyEntry | None
    quarantine: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": None if self.entry is None else self.entry.to_dict(),
            "normalized_code": self.normalized_code,
            "notes": list(self.notes),
            "quarantine": self.quarantine,
            "raw_code": self.raw_code,
            "recognition": self.recognition.value,
            "schema_version": self.schema_version,
        }

    @property
    def is_known(self) -> bool:
        return self.recognition is StatusCodeRecognition.KNOWN


def _entry(
    code: str,
    description: str,
    phase: ApplicationLifecyclePhase,
    *,
    rejection: RejectionDisposition = RejectionDisposition.NONE,
    pending: bool | None = True,
    abandoned: bool | None = False,
    allowed: bool | None = False,
    patented: bool | None = False,
    appealed: bool | None = False,
    notes: Sequence[str] = (),
) -> StatusVocabularyEntry:
    return StatusVocabularyEntry(
        code=str(code),
        description=description,
        lifecycle_phase=phase,
        rejection_disposition=rejection,
        is_pending=pending,
        is_abandoned=abandoned,
        is_allowed=allowed,
        is_patented=patented,
        is_appealed=appealed,
        notes=tuple(notes),
    )


# Protected, versioned vocabulary. Numeric codes outside this map are NOT known.
# Curated from public ODP / Patent Center status labels used in fixtures and
# common prosecution states — intentionally incomplete rather than over-broad.
_PROTECTED_ENTRIES: tuple[StatusVocabularyEntry, ...] = (
    _entry(
        "20",
        "Application Undergoing Preexam Processing",
        ApplicationLifecyclePhase.PRE_EXAMINATION,
    ),
    _entry(
        "30",
        "Docketed New Case - Ready for Examination",
        ApplicationLifecyclePhase.PRE_EXAMINATION,
    ),
    _entry(
        "40",
        "Non Final Action Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "50",
        "Final Rejection Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.FINAL,
    ),
    _entry(
        "60",
        "Response after Non-Final Action Received",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "70",
        "Response after Final Action Received",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.FINAL,
    ),
    _entry(
        "80",
        "Notice of Allowance Mailed",
        ApplicationLifecyclePhase.ALLOWANCE,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        allowed=True,
        pending=True,
    ),
    _entry(
        "90",
        "Patented Case",
        ApplicationLifecyclePhase.GRANT,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        pending=False,
        patented=True,
        allowed=True,
    ),
    _entry(
        "150",
        "Docketed New Case - Ready for Examination",
        ApplicationLifecyclePhase.PRE_EXAMINATION,
    ),
    _entry(
        "151",
        "Docketed New Case - Ready for Examination",
        ApplicationLifecyclePhase.PRE_EXAMINATION,
    ),
    _entry(
        "160",
        "Non Final Action Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "161",
        "Non Final Action Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "170",
        "Final Rejection Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.FINAL,
    ),
    _entry(
        "180",
        "Response after Non-Final Action Entered",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "190",
        "Response after Final Action Entered",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.FINAL,
    ),
    _entry(
        "200",
        "Advisory Action Mailed",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.ADVISORY,
    ),
    _entry(
        "250",
        "Notice of Allowance Mailed -- Application Received in Office of Publications",
        ApplicationLifecyclePhase.ALLOWANCE,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        allowed=True,
    ),
    _entry(
        "360",
        "Abandoned -- Failure to Respond to an Office Action",
        ApplicationLifecyclePhase.ABANDONMENT,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        pending=False,
        abandoned=True,
    ),
    _entry(
        "560",
        "Abandoned -- Incomplete Application",
        ApplicationLifecyclePhase.ABANDONMENT,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        pending=False,
        abandoned=True,
    ),
    _entry(
        "DOCKETED",
        "Docketed",
        ApplicationLifecyclePhase.PRE_EXAMINATION,
    ),
    _entry(
        "PENDING",
        "Pending",
        ApplicationLifecyclePhase.EXAMINATION,
    ),
    _entry(
        "ABANDONED",
        "Abandoned",
        ApplicationLifecyclePhase.ABANDONMENT,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        pending=False,
        abandoned=True,
    ),
    _entry(
        "ALLOWED",
        "Allowed",
        ApplicationLifecyclePhase.ALLOWANCE,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        allowed=True,
    ),
    _entry(
        "PATENTED",
        "Patented",
        ApplicationLifecyclePhase.GRANT,
        rejection=RejectionDisposition.NOT_APPLICABLE,
        pending=False,
        patented=True,
        allowed=True,
    ),
    _entry(
        "CTNF",
        "Non-Final Rejection",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.NONFINAL,
    ),
    _entry(
        "CTFR",
        "Final Rejection",
        ApplicationLifecyclePhase.EXAMINATION,
        rejection=RejectionDisposition.FINAL,
    ),
)

_BY_CODE: Mapping[str, StatusVocabularyEntry] = MappingProxyType(
    {entry.code.upper(): entry for entry in _PROTECTED_ENTRIES}
)


def normalize_status_code_token(code: str | int | None) -> str | None:
    """Normalize a raw code to a vocabulary lookup token."""

    if code is None:
        return None
    text = str(code).strip()
    if not text:
        return None
    # Numeric forms: strip leading zeros but keep "0" as empty → None.
    if text.isdigit():
        return str(int(text))
    return text.upper()


def is_status_code_known(code: str | int | None) -> bool:
    """Return True only for codes in the protected vocabulary."""

    return classify_status_code(code).is_known


def classify_status_code(code: str | int | None) -> StatusCodeClassification:
    """Classify *code* against the protected vocabulary.

    Unknown **numeric** codes are marked ``quarantine`` (and ``unknown``)
    so consumers do not treat them as admitted known statuses. Unknown
    non-numeric tokens are ``unknown`` without automatic quarantine unless
    they look like future numeric invention codes.
    """

    raw = None if code is None else str(code).strip() or None
    normalized = normalize_status_code_token(code)
    if normalized is None:
        return StatusCodeClassification(
            schema_version=STATUS_VOCABULARY_SCHEMA_VERSION,
            raw_code=raw,
            normalized_code=None,
            recognition=StatusCodeRecognition.UNKNOWN,
            entry=None,
            quarantine=False,
            notes=("status code absent",),
        )

    entry = _BY_CODE.get(normalized.upper())
    if entry is not None:
        return StatusCodeClassification(
            schema_version=STATUS_VOCABULARY_SCHEMA_VERSION,
            raw_code=raw,
            normalized_code=entry.code,
            recognition=StatusCodeRecognition.KNOWN,
            entry=entry,
            quarantine=False,
            notes=(),
        )

    # Unknown numeric → quarantine (acceptance: not "known").
    if normalized.isdigit():
        return StatusCodeClassification(
            schema_version=STATUS_VOCABULARY_SCHEMA_VERSION,
            raw_code=raw,
            normalized_code=normalized,
            recognition=StatusCodeRecognition.QUARANTINE,
            entry=None,
            quarantine=True,
            notes=(
                f"unknown numeric status code {normalized!r} not in protected "
                f"vocabulary {STATUS_VOCABULARY_SCHEMA_VERSION}; quarantine",
            ),
        )

    return StatusCodeClassification(
        schema_version=STATUS_VOCABULARY_SCHEMA_VERSION,
        raw_code=raw,
        normalized_code=normalized,
        recognition=StatusCodeRecognition.UNKNOWN,
        entry=None,
        quarantine=False,
        notes=(
            f"unknown status token {normalized!r} not in protected vocabulary "
            f"{STATUS_VOCABULARY_SCHEMA_VERSION}",
        ),
    )


def lookup_status_code(code: str | int | None) -> StatusVocabularyEntry | None:
    """Return the protected entry for a known code, else None."""

    classification = classify_status_code(code)
    return classification.entry


def protected_status_codes() -> frozenset[str]:
    """Return the set of protected vocabulary codes (uppercase tokens)."""

    return frozenset(_BY_CODE.keys())


def vocabulary_manifest() -> dict[str, Any]:
    """Serializable vocabulary identity for receipts and diagnostics."""

    return {
        "code_count": len(_BY_CODE),
        "codes": sorted(_BY_CODE.keys()),
        "interface": STATUS_VOCABULARY_INTERFACE,
        "schema_version": STATUS_VOCABULARY_SCHEMA_VERSION,
    }


__all__ = [
    "STATUS_VOCABULARY_INTERFACE",
    "STATUS_VOCABULARY_SCHEMA_VERSION",
    "StatusCodeClassification",
    "StatusCodeRecognition",
    "StatusVocabularyEntry",
    "classify_status_code",
    "is_status_code_known",
    "lookup_status_code",
    "normalize_status_code_token",
    "protected_status_codes",
    "vocabulary_manifest",
]
