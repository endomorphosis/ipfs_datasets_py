"""Utilities for extracting legislative history citations from statute text.

Designed for reuse across state parsing pipelines.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

TRAILING_BRACKET_RE = re.compile(r"\[(?P<body>[^\[\]]+)\]\s*$")
LAW_HISTORY_CITE_RE = re.compile(
    r"^\s*(?P<year>\d{4})(?:\s+(?P<session>[A-Za-z.]+))?\s+c\.\s*(?P<chapter>[0-9A-Za-z]+)(?:\s+(?P<section>[0-9A-Za-z\-\.]+))?\s*$",
    re.IGNORECASE,
)


def normalize_space(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_history_citation(raw_citation: str) -> Dict[str, Any]:
    citation = normalize_space(raw_citation)
    parsed: Dict[str, Any] = {"raw": citation}
    match = LAW_HISTORY_CITE_RE.match(citation)
    if not match:
        return parsed

    parsed["year"] = int(match.group("year"))
    if match.group("session"):
        parsed["session"] = match.group("session")
    parsed["chapter"] = match.group("chapter")
    if match.group("section"):
        parsed["section"] = match.group("section")
    return parsed


def extract_trailing_history_citations(text: str) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """Extract trailing legislative history citations from bracket blocks.

    Example tail block:
      [1977 c.647 2; 1979 c.420 1]

    Returns:
      - cleaned text (without parsed trailing blocks)
      - raw trailing history block bodies (ordered as they appeared)
      - parsed citation dictionaries
    """
    cleaned = normalize_space(text)
    raw_blocks: List[str] = []
    parsed: List[Dict[str, Any]] = []

    while True:
        match = TRAILING_BRACKET_RE.search(cleaned)
        if not match:
            break

        body = normalize_space(match.group("body"))
        if not body:
            break

        parts = [normalize_space(part) for part in body.split(";") if normalize_space(part)]
        if not parts:
            break

        if not any(LAW_HISTORY_CITE_RE.match(part) for part in parts):
            break

        raw_blocks.insert(0, body)
        for part in parts:
            parsed.append(parse_history_citation(part))

        cleaned = normalize_space(cleaned[:match.start()])

    return cleaned, raw_blocks, parsed
