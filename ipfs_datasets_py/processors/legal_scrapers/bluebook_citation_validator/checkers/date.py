"""Date checker: validates the citation year is reasonable and consistent.

Fixes:
- Bug #9: returns ``None`` (not the string ``'Date check passed'``) on success.
- Deferred feature #26: implements document date cross-reference check.
"""

from __future__ import annotations

import re
from typing import Optional

_YEAR_PATTERN = re.compile(r"\b(1[7-9]\d{2}|20[0-2]\d)\b")
_CITATION_YEAR_PATTERN = re.compile(r"\((\d{4})\)$")

_MIN_YEAR = 1776
_MAX_YEAR = 2025


def _extract_year_from_string(text: str) -> Optional[int]:
    """Return the first plausible 4-digit year found in *text*, or ``None``."""
    m = _YEAR_PATTERN.search(str(text))
    return int(m.group(1)) if m else None


def check_date(citation: dict, documents: Optional[list[dict]] = None) -> Optional[str]:
    """Validate the citation year.

    Checks (in order):
    1. Range check: year must be in ``[1776, 2025]``.
    2. Metadata cross-reference: year extracted from ``bluebook_citation`` must
       match the year from the ``date`` / ``year`` field (if both are present).
    3. Document cross-reference: the year must appear in at least one document
       (if documents are provided).  This implements the previously deferred
       TODO in the original code.

    Args:
        citation: Citation dict.  Year is read from ``bluebook_citation`` (trailing
            ``(YYYY)`` pattern) and/or the ``date`` / ``year`` field.
        documents: Optional list of document dicts with ``html_body`` or ``content``.

    Returns:
        ``None`` when all checks pass; an error string otherwise.
    """
    # --- Extract year from bluebook_citation string ---
    citation_year: Optional[int] = None
    bluebook = citation.get("bluebook_citation", "")
    if bluebook:
        m = _CITATION_YEAR_PATTERN.search(bluebook.strip())
        if m:
            citation_year = int(m.group(1))

    # --- Extract year from metadata field ---
    metadata_year: Optional[int] = None
    raw_date = citation.get("date") or citation.get("year")
    if raw_date is not None:
        if isinstance(raw_date, int):
            metadata_year = raw_date
        else:
            metadata_year = _extract_year_from_string(str(raw_date))

    # Decide which year to use for range checking (prefer citation string).
    year = citation_year if citation_year is not None else metadata_year

    if year is None:
        return "Could not extract a valid year from citation or metadata"

    # 1. Range check.
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return f"Year {year} is outside the valid range ({_MIN_YEAR}–{_MAX_YEAR})"

    # 2. Metadata cross-reference.
    if citation_year is not None and metadata_year is not None:
        if citation_year != metadata_year:
            return (
                f"Year mismatch: bluebook_citation says {citation_year}, "
                f"metadata date says {metadata_year}"
            )

    # 3. Document cross-reference (deferred feature now implemented).
    if documents:
        year_str = str(year)
        found_in_doc = any(
            year_str in (doc.get("html_body") or doc.get("content") or "")
            for doc in documents
        )
        if not found_in_doc:
            return f"Year {year} not found in any source document"

    return None  # all checks passed
