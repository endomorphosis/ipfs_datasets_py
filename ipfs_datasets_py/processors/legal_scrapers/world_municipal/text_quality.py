"""Extraction-usability gate for harvested document text.

Ported from the Italy pilot (2026-10-14, the Levico Terme incident): a
regolamento PDF with no ToUnicode maps made PyMuPDF return ~59k chars of
73%-control-char glyph garbage and pdfplumber return ~397k chars of
literal ``(cid:N)`` tokens. Both passed length/non-empty checks and
``schema.validate_table``; only a manual pre-publish spot-check caught
it. The pilot harvester's fix was an extraction-usability gate: a
digital extraction counts as extracted ONLY if the text is plausibly
real prose. Otherwise the document is treated as NOT extracted, so the
builder's chain falls through to the next method — ultimately OCR,
which renders pixels and is immune to font-encoding garbage — or the
document is deferred.

This module is that gate, shared. Thresholds are the pilot's, unchanged:

- minimum length: 300 non-whitespace chars;
- control/replacement-char ratio <= 2% (Levico's garbage was 73%);
- ``(cid:`` glyph-token density: at most 1 token per 2000 chars;
- letter share >= 45% of all chars (legal prose runs ~55-70%; the rest
  is whitespace, digits and punctuation).

Granularity is the DOCUMENT (the full extracted text of one PDF/page
set, before article splitting) — the same granularity the pilot applied
it at. Do NOT apply it per-row: short legitimate article rows would
fail the length leg. ``validate_table`` is deliberately unchanged;
this gate lives at the extraction layer, upstream of row building.

Typical builder use::

    text, method = "", "none"
    for name, candidate in (("pymupdf", t1), ("pdfplumber", t2),
                            ("pdftotext", t3)):
        if is_usable_text(candidate):
            text, method = candidate, name
            break
    if not text:
        text, method = ocr(pdf_path)  # or defer the document

or, equivalently, ``first_usable_extraction(candidates)``.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "MIN_TEXT_CHARS",
    "MAX_CONTROL_RATIO",
    "CID_TOKEN_CHAR_BUDGET",
    "MIN_LETTER_SHARE",
    "garble_ratio",
    "letter_share",
    "cid_token_count",
    "usability_failures",
    "is_usable_text",
    "assert_usable_text",
    "first_usable_extraction",
]

#: Minimum stripped length for an extraction to count as real text.
MIN_TEXT_CHARS = 300

#: Maximum share of control/replacement chars (pilot: Levico was 0.73).
MAX_CONTROL_RATIO = 0.02

#: A ``(cid:`` glyph token is tolerated at most once per this many chars
#: (pilot rule: ``count > len(text) / 2000`` fails).
CID_TOKEN_CHAR_BUDGET = 2000

#: Minimum share of alphabetic chars over the whole text.
MIN_LETTER_SHARE = 0.45

# Control chars (excluding \t and \n, which are legitimate in extracted
# text) plus C1 controls and the U+FFFD replacement char — the pilot's set.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f�]")


def garble_ratio(text: str) -> float:
    """Share of control/replacement chars in ``text``.

    Catches PDFs whose embedded font encoding makes digital extraction
    return glyph garbage. Empty text is maximally garbled (1.0).
    """
    if not text:
        return 1.0
    return len(_CONTROL_RE.findall(text)) / len(text)


def letter_share(text: str) -> float:
    """Share of alphabetic chars in ``text`` (0.0 for empty text)."""
    if not text:
        return 0.0
    return sum(1 for ch in text if ch.isalpha()) / len(text)


def cid_token_count(text: str) -> int:
    """Number of literal ``(cid:`` glyph tokens (no-ToUnicode symptom)."""
    return text.count("(cid:") if text else 0


def usability_failures(text: str) -> List[str]:
    """Human-readable reasons ``text`` is not usable extracted text.

    An empty list means the text passes the gate. Reasons mirror the
    pilot's ``_usable`` legs exactly (length, garble ratio, cid-token
    density, letter share), evaluated on the full unstripped text
    except length, which the pilot measured on the stripped text.
    """
    if not text or not text.strip():
        return ["empty text"]
    failures: List[str] = []
    stripped_len = len(text.strip())
    if stripped_len < MIN_TEXT_CHARS:
        failures.append(
            f"text too short: {stripped_len} chars < {MIN_TEXT_CHARS} minimum"
        )
    ratio = garble_ratio(text)
    if ratio > MAX_CONTROL_RATIO:
        failures.append(
            f"control/replacement char ratio {ratio:.3f} > {MAX_CONTROL_RATIO}"
        )
    tokens = cid_token_count(text)
    if tokens > len(text) / CID_TOKEN_CHAR_BUDGET:
        failures.append(
            f"(cid: glyph-token density too high: {tokens} tokens in "
            f"{len(text)} chars (cap 1 per {CID_TOKEN_CHAR_BUDGET})"
        )
    share = letter_share(text)
    if share < MIN_LETTER_SHARE:
        failures.append(f"letter share {share:.3f} < {MIN_LETTER_SHARE}")
    return failures


def is_usable_text(text: str) -> bool:
    """True iff ``text`` passes every leg of the usability gate."""
    return not usability_failures(text)


def assert_usable_text(text: str, *, context: str = "") -> str:
    """Fail-closed variant: return ``text`` or raise ``ValueError``.

    For builders that would rather abort a document than thread a
    boolean through their extraction chain.
    """
    failures = usability_failures(text)
    if failures:
        where = f" for {context}" if context else ""
        raise ValueError(
            f"extraction-usability gate failed{where}:\n- " + "\n- ".join(failures)
        )
    return text


def first_usable_extraction(
    candidates: Sequence[Tuple[str, str]],
) -> Optional[Tuple[str, str]]:
    """First ``(method, text)`` candidate passing the gate, else None.

    Encodes the pilot's extraction-chain semantics: a candidate that
    fails usability is treated as NOT extracted, and the chain falls
    through to the next method (ultimately OCR, or deferral when this
    returns None).
    """
    for method, text in candidates:
        if text and is_usable_text(text):
            return method, text
    return None
