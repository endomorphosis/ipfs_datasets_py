"""Format checker: validates the ``bluebook_citation`` string against Bluebook Rule 12.9.

Deferred feature #27 fix: validates the full citation STRING, not individual
title/url/section fields.
"""

from __future__ import annotations

import re
from typing import Optional

from ..constants import BLUEBOOK_STATE_ABBREVS, MIN_CITATION_YEAR, MAX_CITATION_YEAR

# ---------------------------------------------------------------------------
# Bluebook Rule 12.9 pattern
# Format: "Place, State Abbrev., Code Type, §Section (Year)"
# Example: "Garland, Ark., County Code, §14-75 (2007)"
# ---------------------------------------------------------------------------
_BLUEBOOK_PATTERN = re.compile(
    r"^(?P<place>[^,]+),\s+"
    # State abbreviation: handles all Bluebook forms:
    #   single-word  e.g. "Ala." "Alaska" "Ohio"
    #   all-caps     e.g. "N.H."  "D.C."  "S.C."
    #   two-word     e.g. "W. Va."
    r"(?P<state>[A-Z][A-Za-z.]*\.?(?:\s[A-Z][a-z]+\.?)?),\s+"
    r"(?P<code_type>(?:Municipal|County|City)\s+Code),\s+"
    r"§(?P<section>[\d]+(?:[-.][\d]+)*)\s+"
    r"\((?P<year>\d{4})\)$"
)


def check_format(citation: dict) -> Optional[str]:
    """Validate the ``bluebook_citation`` string against Bluebook Rule 12.9 format.

    Args:
        citation: Citation dict containing a ``bluebook_citation`` field.

    Returns:
        ``None`` when the format is valid; a descriptive error string otherwise.
    """
    raw = citation.get("bluebook_citation")
    if not raw:
        return "Missing bluebook_citation field"

    text = raw.strip()
    m = _BLUEBOOK_PATTERN.match(text)
    if not m:
        return (
            f"bluebook_citation does not match Bluebook Rule 12.9 format "
            f"'Place, State, Code Type, §Section (Year)': {text!r}"
        )

    state_abbrev = m.group("state")
    if state_abbrev not in BLUEBOOK_STATE_ABBREVS:
        return (
            f"Unrecognised Bluebook state abbreviation '{state_abbrev}' "
            f"in bluebook_citation: {text!r}"
        )

    year = int(m.group("year"))
    if not (MIN_CITATION_YEAR <= year <= MAX_CITATION_YEAR):
        return (
            f"Year {year} in bluebook_citation is outside the valid range "
            f"({MIN_CITATION_YEAR}–{MAX_CITATION_YEAR}): {text!r}"
        )

    return None  # valid
