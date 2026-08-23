"""Official Oklahoma complete-title PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``scrapeOK.py`` (Apache-2.0).
Complete-title PDFs at ``oklegislature.gov/OK_Statutes/CompleteTitles/os{N}.pdf``
are never auto-downloaded. Set ``OKLAHOMA_TITLE_TEXT`` or ``OKLAHOMA_TITLE_PDF``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

COMPLETE_TITLE_BASE = "https://www.oklegislature.gov/OK_Statutes/CompleteTitles"
TITLES_HTML_URL = "https://www.oklegislature.gov/osStatuesTitle.html"
_OS_PDF_RE = re.compile(r"/os(\d+[A-Ea-e]?)\.pdf$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(
    r"^§\s*([0-9]+[A-Za-z]?)\s*[-‑]\s*([0-9][0-9A-Za-z.\-]*)\s*\.\s*(.*)$"
)
_HISTORY_START_RE = re.compile(
    r"^(R\.L\.\d{4}|Laws\s+\d{4}|Added\s+by\s+Laws|Amended\s+by\s+Laws|"
    r"Renumbered\s+(?:by|from)\s+Laws|Repealed\s+by\s+Laws|Transferred\s+by\s+Laws)",
    re.IGNORECASE,
)
_TOC_DOTS_RE = re.compile(r"\.\s*\.\s*\.\s*\.\s*\.")
_RESERVED = re.compile(r"\((?:reserved|repealed|expired|renumbered|deleted)\)", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("‑", "-")).strip()


def parse_oklahoma_title_text(
    text: str,
    *,
    title_number: str = "",
    code_name: str = "Oklahoma Statutes",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    statutes: List[NormalizedStatute] = []
    current: Optional[dict] = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        heading = current["name"]
        body = _clean(" ".join(current["body"]))
        if _RESERVED.search(heading) or _RESERVED.search(body[:160]) or len(body) < 40:
            current = None
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current = None
            return
        number = current["number"]
        title = number.split("-", 1)[0]
        link = source_url or f"{COMPLETE_TITLE_BASE}/os{title}.pdf"
        statutes.append(
            NormalizedStatute(
                state_code="OK",
                state_name="Oklahoma",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title,
                section_number=number,
                section_name=heading[:200] or f"Section {number}",
                full_text=body[:14000],
                source_url=link,
                official_cite=f"Okla. Stat. tit. {title}, § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_oklahoma_complete_title",
                    "source_authority_class": "official",
                    "discovery_method": "oklegislature_complete_title_pdf",
                    "skip_hydrate": True,
                },
            )
        )
        current = None

    expected = title_number.upper()
    for raw in lines:
        line = raw.replace("‑", "-")
        if _TOC_DOTS_RE.search(line):
            continue
        match = _SECTION_HEADING_RE.match(line)
        if match:
            if expected and match.group(1).upper() != expected:
                continue
            flush()
            current = {
                "number": f"{match.group(1).upper()}-{match.group(2)}",
                "name": _clean(match.group(3).rstrip(". ")),
                "body": [],
                "in_history": False,
            }
            continue
        if current is None:
            continue
        cleaned = _clean(line)
        if not cleaned:
            continue
        if _HISTORY_START_RE.match(cleaned):
            current["in_history"] = True
            continue
        if not current["in_history"]:
            current["body"].append(cleaned)
    flush()
    return statutes


def parse_oklahoma_title_pdf(
    pdf_path: Path,
    *,
    title_number: str = "",
    code_name: str = "Oklahoma Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        import pdfplumber
    except ImportError:
        return []
    lines: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    match = re.search(r"os(\d+[A-Ea-e]?)\.pdf$", pdf_path.name, re.IGNORECASE)
    number = title_number or (match.group(1).upper() if match else "")
    return parse_oklahoma_title_text(
        "\n".join(lines),
        title_number=number,
        code_name=code_name,
        source_url=f"{COMPLETE_TITLE_BASE}/os{number}.pdf" if number else COMPLETE_TITLE_BASE,
        max_statutes=max_statutes,
    )


def title_pdf_url(number: str) -> str:
    token = str(number or "").strip().upper()
    return f"{COMPLETE_TITLE_BASE}/os{token}.pdf"


def title_pdf_links(html: str) -> List[Tuple[str, str, str]]:
    """TOC ``/os21.pdf`` rows. PDFs are never auto-downloaded."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _OS_PDF_RE.search(href)
        if not match:
            continue
        number = match.group(1).upper()
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Title {number}"
        out.append((number, name, title_pdf_url(number)))
    return out


def configured_title_path() -> Optional[Path]:
    for key in ("OKLAHOMA_TITLE_TEXT", "OKLAHOMA_TITLE_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def parse_configured_oklahoma_title(
    *,
    code_name: str = "Oklahoma Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_title_path()
    if path is None:
        return []
    if path.suffix.lower() == ".pdf":
        return parse_oklahoma_title_pdf(path, code_name=code_name, max_statutes=max_statutes)
    return parse_oklahoma_title_text(
        path.read_text(encoding="utf-8", errors="replace"),
        code_name=code_name,
        max_statutes=max_statutes,
    )
