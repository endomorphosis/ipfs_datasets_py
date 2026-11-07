"""Placement of an atom that has no structural locator.

A placement is not a section, article, chapter, part, or title number.
Retrieval can group the atom under its instrument without counting it as
located. The closed set is:

- ``whole_instrument``: the law name is known and the body does not split
  into two provisions.
- ``unsplit_multi``: the body still contains two or more provisions, and
  the atom stayed one row so its entry id did not change.
- ``enabling_instrument``: the text adopts or applies a named section. It
  is not that section.
- ``unresolved``: no law name was found.

``short_siblings`` from the admission splitter, a second numbered heading
that is too short to become its own row, is ``unsplit_multi``. A lone
parenthetical subsection stays ``whole_instrument``.
"""

from __future__ import annotations

import re

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.profiles import (
    latin_split_allowed,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    MIN_UNIT_CHARS,
    segment_exclusive,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    _coalesce_subsections,
)

PLACEMENTS = frozenset(
    {
        "whole_instrument",
        "unsplit_multi",
        "enabling_instrument",
        "unresolved",
    }
)
LISTED_PLACEMENTS = frozenset(
    {
        "whole_instrument",
        "unsplit_multi",
        "enabling_instrument",
    }
)
_LEVELS = (
    frozenset({"article", "section"}),
    frozenset({"chapter"}),
    frozenset({"part"}),
    frozenset({"title"}),
)
_ENABLING = re.compile(
    r"(?i)hereby adopt|under subsection|this instrument applies|for section\s+[0-9]"
)


def classify_placement(
    text: str,
    language: str,
    *,
    status: str,
    instrument: str,
) -> str:
    """Return one placement label. A structural atom returns an empty string."""

    if status == "structural":
        return ""
    if status == "unresolved" or not instrument.strip():
        return "unresolved"
    if status != "instrument_only":
        return "unresolved"
    if _ENABLING.search(text or ""):
        return "enabling_instrument"
    if _span(text or "", language or "") == "multi":
        return "unsplit_multi"
    return "whole_instrument"


def _span(text: str, language: str) -> str:
    """``multi`` when the admission splitter still sees two provisions."""

    if len(text) < 16:
        return "single"
    internal = segment_exclusive(text, language=language)
    multi = None
    single_kinds: frozenset[str] | None = None
    for kinds in _LEVELS:
        got = _take(internal, kinds, language)
        if len(got) >= 2:
            multi = got
            single_kinds = None
            break
        if len(got) == 1 and single_kinds is None:
            single_kinds = kinds
    if multi is not None:
        coalesced = _coalesce_subsections(multi)
        if len(coalesced) >= 2:
            return "multi"
        return "single"
    if single_kinds is None:
        return "single"
    raw = [unit for unit in internal if unit.kind in single_kinds and unit.number]
    if len(raw) >= 2:
        return "multi"
    return "single"


def _take(internal: list, kinds: frozenset[str], language: str) -> list:
    out = []
    for unit in internal:
        if unit.kind not in kinds:
            continue
        min_len = 16 if unit.number else MIN_UNIT_CHARS
        if language and not latin_split_allowed(language):
            min_len = 16
        if len(unit.body.strip()) >= min_len:
            out.append(unit)
    return out
