"""Nominative reporter names, parallel U.S. cites, and law journals.

Dallas Reports are printed as ``1 Dall. 1`` and also ``1 Dallas 1``. Early
United States Reports use ``4 U.S. (4 Dall.) 1``. Law journals use
``10 Wayne L Rev 381``, ``123 Yale L.J. 456``, ``98 Cornell L.Q. 12``,
``50 Am. J. Int'l L. 1``, and ``98 Harvard Law Review 12``.
"""

from __future__ import annotations

import re

# Folded letters of a reporter name -> the abbreviation the cite index uses.
NOMINATIVE_ALIASES = {
    "dallas": "Dall.",
    "dall": "Dall.",
    "wheaton": "Wheat.",
    "wheat": "Wheat.",
    "wallace": "Wall.",
    "wall": "Wall.",
    "howard": "How.",
    "how": "How.",
    "peters": "Pet.",
    "pet": "Pet.",
    "cranch": "Cranch",
    "black": "Black",
    "njlaw": "N.J.L.",
}


def canonical_reporter(reporter: str) -> str | None:
    """Return the cite-index abbreviation for a spelled nominative, if any."""
    folded = "".join(char for char in reporter.lower() if char.isalpha())
    return NOMINATIVE_ALIASES.get(folded)


# Full nominative names and "N. J. Law". The abbreviated forms stay in
# citation_reporters so "1 Dall. 1" and "1 Dallas 1" are not the same match.
_SPELLED = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,4})\s+"
    r"(Dallas|Wheaton|Wallace|Howard|Peters|Black|N\.?\s*J\.?\s+Law)"
    r"(?:\s*,\s*|\s+)(\d{1,6})(?!\d)"
)

# 4 U.S. (4 Dall.) 1. The page is after the parenthetical, not the 4 inside it.
_PARALLEL = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,4})\s+(U\.?\s*S\.?)\s*"
    r"\(\s*(\d{1,4})\s+([A-Z][A-Za-z.]*)\.?\s*\)\s*"
    r"(\d{1,6})(?!\d)"
)

# A journal word, including "Wm. & Mary" and "N.Y.U."
_JWORD = r"[A-Z][A-Za-z.']*(?:\s*&\s*[A-Z][A-Za-z.']*)*"
# L. Rev. / L.J. / L.Q. and the spelled Law Review / Journal / Quarterly.
# "U.L. Rev." keeps the period glued to the L. "Ohio L.R." is not a journal:
# the review token is the letters Rev, not a bare R.
_JOURNAL = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,4})\s+"
    r"(?P<journal>"
    rf"(?:{_JWORD}\s+){{1,6}}L\.?\s*Rev\.?"
    rf"|(?:{_JWORD}\s+){{1,6}}{_JWORD}\.?L\.?\s*Rev\.?"
    rf"|(?:{_JWORD}\s+){{1,6}}L\.?\s*J\.?"
    rf"|(?:{_JWORD}\s+){{1,6}}L\.?\s*Q\.?"
    rf"|(?:{_JWORD}\s+){{0,5}}J\.?\s+Int['’]l\.?\s+L\.?"
    rf"|(?:{_JWORD}\s+){{0,5}}Law\s+Q\.?\s*Rev\.?"
    rf"|(?:{_JWORD}\s+){{0,5}}Law\s+(?:Review|Journal|Quarterly)"
    r")"
    r"(?:\s*,\s*|\s+)(\d{1,6})(?!\d)"
)


def iter_spelled_reporter_spans(text: str):
    """Yield start, end, volume, canonical reporter, page for spelled names."""
    for match in _SPELLED.finditer(text):
        canonical = canonical_reporter(match.group(2))
        if canonical is None:
            continue
        yield match.start(), match.end(), match.group(1), canonical, match.group(3)


def iter_parallel_reporter_spans(text: str):
    """Yield the U.S. cite and the nominative cite inside ``4 U.S. (4 Dall.) 1``."""
    for match in _PARALLEL.finditer(text):
        volume, reporter, parallel_volume, parallel_reporter, page = match.groups()
        canonical = canonical_reporter(parallel_reporter)
        if canonical is None:
            continue
        yield match.start(), match.end(), volume, "U.S.", page
        yield match.start(), match.end(), parallel_volume, canonical, page


def iter_journal_spans(text: str):
    """Yield start, end, volume, journal, page. The journal name keeps its capitals."""
    for match in _JOURNAL.finditer(text):
        yield match.start(), match.end(), match.group(1), match.group("journal").strip(), match.group(3)
