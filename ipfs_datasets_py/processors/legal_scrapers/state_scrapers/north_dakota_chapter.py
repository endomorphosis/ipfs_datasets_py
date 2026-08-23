"""Official North Dakota Century Code chapter PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``scrapeND.py`` (Apache-2.0).
Chapter PDFs at ``ndlegis.gov/cencode/tNNcNN.pdf`` are never auto-downloaded.
Set ``NORTH_DAKOTA_CHAPTER_TEXT`` or ``NORTH_DAKOTA_CHAPTER_PDF``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

CENCODE = "https://ndlegis.gov/cencode"
BASE = "https://ndlegis.gov"
_SEC_HEADER_RE = re.compile(r"^(\d[\d.]*(?:-[\d.]+)+)\.\s+(.+)$")
_PAGE_FOOTER_RE = re.compile(r"^Page No\.\s+\d+\s*$", re.IGNORECASE)
_RUNNING_HEADER_RE = re.compile(
    r"^(?:CHAPTER\s+\d[\d.\-]*|TITLE\s+\d[\d.]*|TABLE OF CONTENTS)\s*$",
    re.IGNORECASE,
)
_HISTORY_START_RE = re.compile(
    r"^(Source:|History:|S\.L\.\s+\d{4}|Amended\s+by\s+S\.L\.)", re.IGNORECASE
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("‑", "-")).strip()


def _find_body_start(lines: List[str]) -> int:
    for index, line in enumerate(lines):
        if not _SEC_HEADER_RE.match(line):
            continue
        for nxt in lines[index + 1 : index + 6]:
            token = nxt.strip()
            if not token:
                continue
            if _SEC_HEADER_RE.match(token):
                break
            return index
    return 0


def parse_north_dakota_chapter_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    raw_lines = [_clean(line) for line in str(text or "").splitlines()]
    lines = [
        line
        for line in raw_lines
        if line and not _PAGE_FOOTER_RE.match(line) and not _RUNNING_HEADER_RE.match(line)
    ]
    start = _find_body_start(lines)
    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    current_body: List[str] = []
    in_history = False

    def flush() -> None:
        nonlocal current_number, current_name, current_body, in_history
        if not current_number:
            return
        body = _clean(" ".join(current_body))
        heading = current_name
        if _RESERVED.search(heading) or len(body) < 40:
            current_number = ""
            current_name = ""
            current_body = []
            in_history = False
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_number = ""
            return
        parts = current_number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="ND",
                state_name="North Dakota",
                statute_id=f"{code_name} § {current_number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number="-".join(parts[:2]) if len(parts) > 1 else None,
                section_number=current_number,
                section_name=heading[:200] or f"Section {current_number}",
                full_text=body[:14000],
                source_url=source_url or f"{CENCODE}/",
                official_cite=f"N.D. Cent. Code § {current_number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_north_dakota_chapter_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "ndlegis_cencode_chapter_pdf",
                    "skip_hydrate": True,
                },
            )
        )
        current_number = ""
        current_name = ""
        current_body = []
        in_history = False

    for line in lines[start:]:
        match = _SEC_HEADER_RE.match(line)
        if match:
            flush()
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            current_number = match.group(1)
            current_name = _clean(match.group(2).rstrip("."))
            current_body = []
            in_history = False
            continue
        if not current_number:
            continue
        if _HISTORY_START_RE.match(line):
            in_history = True
            continue
        if not in_history:
            current_body.append(line)
    flush()
    return statutes


def parse_north_dakota_chapter_pdf(
    pdf_path: Path,
    *,
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        import pdfplumber
    except ImportError:
        return []
    lines: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            lines.extend(page_text.splitlines())
    return parse_north_dakota_chapter_text(
        "\n".join(lines),
        source_url=f"{CENCODE}/{pdf_path.name}",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_chapter_path() -> Optional[Path]:
    for key in ("NORTH_DAKOTA_CHAPTER_TEXT", "NORTH_DAKOTA_CHAPTER_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def parse_configured_north_dakota_chapter(
    *,
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_chapter_path()
    if path is None:
        return []
    if path.suffix.lower() == ".pdf":
        return parse_north_dakota_chapter_pdf(path, code_name=code_name, max_statutes=max_statutes)
    return parse_north_dakota_chapter_text(
        path.read_text(encoding="utf-8", errors="replace"),
        code_name=code_name,
        max_statutes=max_statutes,
    )


def title_items(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """``.titles-grid .title-item`` rows from classic.html."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    grid = soup.find(class_="titles-grid") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in grid.find_all(class_="title-item"):
        number_node = item.find(class_=re.compile(r"title-number"))
        anchor = item.find("a", href=True)
        if number_node is None or anchor is None:
            continue
        number = _clean(number_node.get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        name = _clean(item.get_text(" "))
        out.append((number, name or f"Title {number}", urljoin(base_url, str(anchor.get("href") or ""))))
    return out


def chapter_table_rows(html: str, *, base_url: str = CENCODE) -> List[Tuple[str, str, str]]:
    """Title-page chapter table (number | link | name)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    field = soup.find(class_=re.compile(r"field--name-field-pwv-custom-content")) or soup
    table = field.find("table") if field is not None else None
    if table is None:
        return []
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        number = _clean(cells[0].get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        link = cells[1].find("a", href=True)
        name_cell = cells[2] if len(cells) > 2 else cells[1]
        name = _clean(name_cell.get_text(" "))
        url = urljoin(base_url.rstrip("/") + "/", str(link.get("href") or "")) if link else ""
        out.append((number, name, url))
    return out


def section_meta_rows(html: str) -> List[Tuple[str, str]]:
    """Chapter HTML section list ``{number, name}``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    field = soup.find(class_=re.compile(r"field--name-field-pwv-custom-content")) or soup
    table = field.find("table") if field is not None else None
    if table is None:
        return []
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        if link is None:
            continue
        number = _clean(link.get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(cells[1].get_text(" "))))
    return out
