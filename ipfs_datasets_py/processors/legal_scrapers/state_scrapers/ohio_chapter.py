"""Official Ohio Revised Code chapter-page parser.

Adapted from Vaquill-AI/open-us-law ``ingest_oh_statutes.py`` (Apache-2.0).
``codes.ohio.gov`` renders every section inline on the chapter page; one
fetch per chapter is the official bulk path, not a secondary mirror.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

OH_BASE = "https://codes.ohio.gov"

_SECTION_RE = re.compile(
    r"\nSection\s+(\d+(?:\.\d+(?:\.\d+)?)?[A-Za-z]?)\s*\|\s*([^\n]+?)\n",
    re.MULTILINE,
)
_RESERVED_PAT = re.compile(
    r"\[(repealed|expired|reserved|renumbered|amended)\b",
    re.IGNORECASE,
)
def chapter_url(chapter_num: str) -> str:
    """Official chapter page that carries every inline section."""

    return f"{OH_BASE}/ohio-revised-code/chapter-{chapter_num}"


def section_url(section_num: str) -> str:
    return f"{OH_BASE}/ohio-revised-code/section-{section_num}"


def strip_ohio_section_metadata(body: str) -> str:
    """Drop Effective / Latest Legislation / PDF trailers from one section."""

    text = str(body or "")
    text = re.sub(
        r"Effective:[^\n]*\nLatest Legislation:[^\n]*\nPDF:[^\n]*\nDownload Authenticated PDF\n",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"Effective:[^\n]*\n", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Latest Legislation:[^\n]*\n", "", text, flags=re.IGNORECASE)
    text = re.sub(r"PDF:\s*Download Authenticated PDF\s*", "", text, flags=re.IGNORECASE)
    for trail in ("\nView ", "\nLast updated"):
        idx = text.find(trail)
        if idx > 0:
            text = text[:idx]
            break
    return re.sub(r"\s+", " ", text).strip()


def parse_ohio_chapter_html(
    html: str | bytes,
    *,
    title_num: str = "",
    chapter_num: str = "",
    code_name: str = "Ohio Revised Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse inline ``Section NNN.NN | heading`` blocks from one chapter page."""

    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    text = "\n" + soup.get_text("\n", strip=True)

    chap_name = ""
    if chapter_num:
        match = re.search(
            rf"\nChapter\s+{re.escape(str(chapter_num))}\s*\|\s*([^\n]+?)\n",
            text,
        )
        if match:
            chap_name = match.group(1).strip()

    matches = list(_SECTION_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        section_num = match.group(1).strip()
        heading = match.group(2).strip().rstrip(".")
        if _RESERVED_PAT.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = strip_ohio_section_metadata(text[start:end])
        if len(body) < 30:
            continue
        statutes.append(
            NormalizedStatute(
                state_code="OH",
                state_name="Ohio",
                statute_id=f"{code_name} § {section_num}",
                code_name=code_name,
                title_number=str(title_num or "") or None,
                chapter_number=str(chapter_num or "") or None,
                chapter_name=chap_name or None,
                section_number=section_num,
                section_name=f"§ {section_num}. {heading}"[:220],
                full_text=body[:14000],
                source_url=section_url(section_num),
                official_cite=f"Ohio Rev. Code Ann. § {section_num}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_ohio_chapter_inline",
                    "source_authority_class": "official",
                    "discovery_method": "codes_ohio_gov_chapter_inline",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes
