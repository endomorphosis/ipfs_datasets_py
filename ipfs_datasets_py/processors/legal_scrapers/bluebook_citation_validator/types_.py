"""Shared types for the Bluebook citation validator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


# Opaque placeholder for DB connection objects (DuckDB or mysql-connector).
DatabaseConnection = Any


@dataclass
class CheckResult:
    """Result of a single citation validation check.

    Attributes:
        valid: ``True`` when the check passed.
        error_type: Short identifier for the class of failure (``None`` when valid).
        message: Human-readable description of the failure (``None`` when valid).
    """

    valid: bool = True
    error_type: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "error_type": self.error_type, "message": self.message}


@dataclass
class ErrorRecord:
    """A fully-populated error row ready for database insertion.

    The ``cid`` field is intentionally left ``None`` at construction time; it
    should be set by calling :func:`~database.make_cid` over the concatenated
    string values of the other fields before the row is written to the DB.

    Attributes:
        citation_cid: CID of the citation that triggered the error.
        gnis: GNIS identifier of the geographic place.
        geography_error: Geography-check error message, or ``None``.
        type_error: Code-type-check error message, or ``None``.
        section_error: Section-check error message, or ``None``.
        date_error: Date-check error message, or ``None``.
        format_error: Format-check error message, or ``None``.
        severity: 1–5 (5 = critical).
        error_message: Semicolon-joined summary of all errors.
        created_at: ISO-8601 timestamp (auto-populated).
        cid: Content-addressed identifier (set after construction).
    """

    citation_cid: str
    gnis: int
    geography_error: Optional[str] = None
    type_error: Optional[str] = None
    section_error: Optional[str] = None
    date_error: Optional[str] = None
    format_error: Optional[str] = None
    severity: int = 1
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    cid: Optional[str] = None

    def __post_init__(self) -> None:
        if not (1 <= self.severity <= 5):
            raise ValueError("severity must be between 1 and 5")
