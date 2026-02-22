"""Shared constants for the Bluebook citation validator.

Centralises the Bluebook state abbreviation table and citation-year range so
that any future updates only need to be made in one place.
"""

from __future__ import annotations

# Official Bluebook state abbreviations — Rule 10.2.2 / Table T10 (21st ed. 2020).
# Extracted here so they can be imported by checkers, tests, and documentation.
BLUEBOOK_STATE_ABBREVS: frozenset[str] = frozenset([
    "Ala.", "Alaska", "Ariz.", "Ark.", "Cal.", "Colo.", "Conn.", "Del.",
    "Fla.", "Ga.", "Haw.", "Idaho", "Ill.", "Ind.", "Iowa", "Kan.", "Ky.",
    "La.", "Me.", "Md.", "Mass.", "Mich.", "Minn.", "Miss.", "Mo.", "Mont.",
    "Neb.", "Nev.", "N.H.", "N.J.", "N.M.", "N.Y.", "N.C.", "N.D.", "Ohio",
    "Okla.", "Or.", "Pa.", "R.I.", "S.C.", "S.D.", "Tenn.", "Tex.", "Utah",
    "Vt.", "Va.", "Wash.", "W. Va.", "Wis.", "Wyo.", "D.C.",
])

# Valid citation year range per the PRD success criteria.
MIN_CITATION_YEAR: int = 1776
MAX_CITATION_YEAR: int = 2025

# GNIS class_code → code type mappings (per PRD success_criteria_part1_definitions.md).
MUNICIPAL_CLASS_CODES: frozenset[str] = frozenset({"C1", "C2", "C3", "C4", "C5", "C6", "C7"})
COUNTY_CLASS_CODES: frozenset[str] = frozenset({"H1", "H4", "H5", "H6"})
CONSOLIDATED_CLASS_CODES: frozenset[str] = frozenset({"C8"})
