"""Format checker: validates the ``bluebook_citation`` string against Bluebook Rule 12.9.

Deferred feature #27 fix: validates the full citation STRING, not individual
title/url/section fields.
"""

from __future__ import annotations

import re
from typing import Optional

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

# Official Bluebook state abbreviations (Rule 10.2.2 / Table T10).
_BLUEBOOK_STATE_ABBREVS: frozenset[str] = frozenset([
    "Ala.", "Alaska", "Ariz.", "Ark.", "Cal.", "Colo.", "Conn.", "Del.",
    "Fla.", "Ga.", "Haw.", "Idaho", "Ill.", "Ind.", "Iowa", "Kan.", "Ky.",
    "La.", "Me.", "Md.", "Mass.", "Mich.", "Minn.", "Miss.", "Mo.", "Mont.",
    "Neb.", "Nev.", "N.H.", "N.J.", "N.M.", "N.Y.", "N.C.", "N.D.", "Ohio",
    "Okla.", "Or.", "Pa.", "R.I.", "S.C.", "S.D.", "Tenn.", "Tex.", "Utah",
    "Vt.", "Va.", "Wash.", "W. Va.", "Wis.", "Wyo.", "D.C.",
])

_MIN_YEAR = 1776
_MAX_YEAR = 2025


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
    if state_abbrev not in _BLUEBOOK_STATE_ABBREVS:
        return (
            f"Unrecognised Bluebook state abbreviation '{state_abbrev}' "
            f"in bluebook_citation: {text!r}"
        )

    year = int(m.group("year"))
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return (
            f"Year {year} in bluebook_citation is outside the valid range "
            f"({_MIN_YEAR}–{_MAX_YEAR}): {text!r}"
        )

    return None  # valid
