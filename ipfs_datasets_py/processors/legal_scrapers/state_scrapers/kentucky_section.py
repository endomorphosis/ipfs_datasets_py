"""Official Kentucky KRS statute PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``scrapeKY.py`` (Apache-2.0).
``statute.aspx?id=N`` returns a PDF. First line is ``N.NN heading``;
``Effective:`` / ``History:`` starts the dropped addendum.
Set ``KENTUCKY_SECTION_TEXT`` or ``KENTUCKY_SECTION_PDF``. PDFs are never
auto-downloaded.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://apps.legislature.ky.gov/law/statutes"
_FIRST_LINE_RE = re.compile(r"^(\d[\dA-Za-z]*\.\d+)\s+(.+)$")
_HISTORY_START_RE = re.compile(r"^(Effective:|History:|HISTORY:|EFFECTIVE:)", re.IGNORECASE)
_RESERVED = re.compile(
    r"\b(not yet utilized|repealed|reserved|superseded|expired|renumbered)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("–", "-").replace("—", "-")).strip()


def parse_kentucky_section_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Kentucky Revised Statutes",
) -> Optional[NormalizedStatute]:
    lines = [_clean(line) for line in str(text or "").splitlines() if _clean(line)]
    if not lines:
        return None
    number = ""
    heading = ""
    body: list[str] = []
    in_history = False
    for line in lines:
        if _HISTORY_START_RE.match(line):
            in_history = True
            continue
        if in_history:
            continue
        match = _FIRST_LINE_RE.match(line)
        if match and not number:
            number = match.group(1)
            heading = _clean(match.group(2).rstrip("."))
            continue
        body.append(line)
    full = _clean(" ".join(body))
    if not number or len(full) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(full[:160]):
        return None
    return NormalizedStatute(
        state_code="KY",
        state_name="Kentucky",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=number.split(".", 1)[0],
        section_number=number,
        section_name=heading[:200] or f"Section {number}",
        full_text=full,
        source_url=source_url or f"{BASE}/",
        official_cite=f"KRS § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_kentucky_statute_pdf",
            "source_authority_class": "official",
            "discovery_method": "krs_statute_aspx_pdf",
            "skip_hydrate": True,
        },
    )


def parse_kentucky_section_pdf(
    pdf_path: Path,
    *,
    source_url: str = "",
    code_name: str = "Kentucky Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        import pdfplumber
    except ImportError:
        return None
    lines: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            lines.extend(page_text.splitlines())
    return parse_kentucky_section_text(
        "\n".join(lines), source_url=source_url, code_name=code_name
    )


def configured_section_path() -> Optional[Path]:
    for key in ("KENTUCKY_SECTION_TEXT", "KENTUCKY_SECTION_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("KENTUCKY_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_spans(path.read_text(encoding="utf-8", errors="replace"))


def title_spans(html: str) -> List[Tuple[str, str]]:
    """``#Panel1 span#title`` Roman-numeral title labels."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for span in soup.find_all("span", id="title"):
        raw = _clean(span.get_text(" "))
        parts = raw.split(None, 2)
        number = parts[1] if len(parts) >= 2 else raw
        if not number or number in seen:
            continue
        seen.add(number)
        out.append((number, raw or f"Title {number}"))
    return out


def chapter_links(html: str, *, base_url: str = f"{BASE}/") -> List[Tuple[str, str, str]]:
    """``a.chapter`` rows (``chapter.aspx?id=N``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", class_="chapter", href=True):
        raw = _clean(anchor.get_text(" "))
        parts = raw.split(None, 2)
        number = parts[1].rstrip(".") if len(parts) >= 2 else ""
        if not number or number in seen:
            continue
        seen.add(number)
        href = str(anchor.get("href") or "").strip()
        out.append((number, raw or f"Chapter {number}", urljoin(base_url, href)))
    return out


def statute_links(
    html: str, *, chapter_number: str, base_url: str = f"{BASE}/"
) -> List[Tuple[str, str, str]]:
    """``a.statute`` rows; ``.100`` becomes ``{chapter}.100``. PDFs stay env-gated."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    panel = soup.find(id="Panel1") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in panel.find_all("a", class_="statute", href=True):
        raw = _clean(anchor.get_text(" "))
        number = ""
        dotted = re.match(r"^\.(\d[\w]*)\s", raw)
        if dotted:
            number = f"{chapter_number}.{dotted.group(1)}"
        else:
            prefixed = re.match(r"^(\d[\w]*\.\d+)\s", raw)
            if prefixed:
                number = prefixed.group(1)
        if not number or number in seen:
            continue
        seen.add(number)
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        out.append((number, raw or f"Section {number}", urljoin(base_url, href)))
    return out


def parse_configured_kentucky_section(
    *,
    code_name: str = "Kentucky Revised Statutes",
) -> Optional[NormalizedStatute]:
    path = configured_section_path()
    if path is None:
        return None
    if path.suffix.lower() == ".pdf":
        return parse_kentucky_section_pdf(path, code_name=code_name)
    return parse_kentucky_section_text(
        path.read_text(encoding="utf-8", errors="replace"), code_name=code_name
    )
