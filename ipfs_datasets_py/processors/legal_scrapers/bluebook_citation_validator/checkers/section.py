"""Section checker: validates that the cited section exists in source HTML documents.

Bug #23 fix: correct signature is ``(citation: dict, documents: list[dict])``,
**not** ``(citation_section: str, html_body: str)``.
"""

from __future__ import annotations

import re
from typing import Optional


def _extract_section_number(citation: dict) -> Optional[str]:
    """Extract a bare section number from the citation dict.

    Tries (in order):
    1. ``citation['title_num']`` — explicit section field.
    2. The section captured from ``citation['bluebook_citation']`` via the
       ``§<section>`` pattern.

    Returns the number string (e.g. ``"14-75"``) or ``None``.
    """
    title_num = citation.get("title_num") or citation.get("section")
    if title_num:
        # Strip any leading §/S whitespace.
        cleaned = re.sub(r"^[§S]\s*", "", str(title_num).strip())
        if cleaned:
            return cleaned

    bluebook = citation.get("bluebook_citation", "")
    # Pattern: §14-75 or § 14-75 in the citation string
    m = re.search(r"§\s*([\d]+(?:[-.][\d]+)*)", bluebook)
    if m:
        return m.group(1)

    return None


def check_section(citation: dict, documents: list[dict]) -> Optional[str]:
    """Validate that the section referenced in the citation exists in the source HTML.

    Args:
        citation: Citation dict.  Section is extracted from ``title_num`` or
            ``bluebook_citation``.
        documents: List of document dicts, each containing ``html_body`` or
            ``content`` text.

    Returns:
        ``None`` when the section is found; an error string otherwise.
    """
    section_number = _extract_section_number(citation)
    if not section_number:
        return "Could not extract section number from citation"

    if not documents:
        return f"No documents provided; cannot verify section {section_number}"

    escaped = re.escape(section_number)
    patterns = [
        re.compile(rf"§\s*{escaped}\b", re.IGNORECASE),
        re.compile(rf"\bsection\s+{escaped}\b", re.IGNORECASE),
        re.compile(rf"\bsec\.\s*{escaped}\b", re.IGNORECASE),
        re.compile(rf"\bs\s+{escaped}\b", re.IGNORECASE),
    ]

    for doc in documents:
        body = doc.get("html_body") or doc.get("content") or ""
        if not body:
            continue
        for pattern in patterns:
            if pattern.search(body):
                return None  # found — valid

    return f"Section {section_number} not found in any source document"
