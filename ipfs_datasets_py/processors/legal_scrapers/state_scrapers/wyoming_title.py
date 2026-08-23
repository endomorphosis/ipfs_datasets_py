"""Official Wyoming title PDF/text parser.

Wyoming publishes deterministic title PDFs at
``https://www.wyoleg.gov/statutes/compress/titleN.pdf``. This parser splits
``N-N-N. heading`` blocks and drops History/Source trailers.

Local dumps: ``WYOMING_TITLE_TEXT``, ``WYOMING_TITLE_PDF``. PDFs are never
auto-downloaded here; live harvest uses ``WyomingScraper`` separately.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

COMPRESS = "https://www.wyoleg.gov/statutes/compress"
_SECTION_HEADER_RE = re.compile(
    r"(?m)^\s*(?P<num>\d{1,2}-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?)\.\s+(?P<head>.+)$"
)
_HISTORY_RE = re.compile(r"^\s*(History|Source|Laws|Cross references)\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_wyoming_title_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Wyoming Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    matches = list(_SECTION_HEADER_RE.finditer(text or ""))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        paras = []
        for line in text[start:end].splitlines():
            line = line.strip()
            if not line or _HISTORY_RE.match(line):
                continue
            paras.append(line)
        body = _clean(" ".join(paras))
        if len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="WY",
                state_name="Wyoming",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=source_url or f"{COMPRESS}/title{parts[0] if parts else '1'}.pdf",
                official_cite=f"Wyo. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wyoming_title_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "wyoleg_compress_title_text",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def title_pdf_url(number: str) -> str:
    token = str(number or "").strip()
    return f"{COMPRESS}/title{token}.pdf"


def title_pdf_links(html: str) -> List[Tuple[str, str, str]]:
    """Index ``title6.pdf`` rows. PDFs are never auto-downloaded."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = re.search(r"title(\d+)\.pdf$", href, re.IGNORECASE)
        if not match:
            continue
        number = str(int(match.group(1)))
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Title {number}"
        out.append((number, name, title_pdf_url(number)))
    return out


def configured_title_text_path() -> Optional[Path]:
    for key in ("WYOMING_TITLE_TEXT", "WYOMING_TITLE_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        try:
            lines: List[str] = []
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages:
                    lines.append(page.extract_text() or "")
            return "\n".join(lines)
        except Exception:
            pass
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def parse_wyoming_title_pdf(
    pdf_path: Path,
    *,
    code_name: str = "Wyoming Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []
    match = re.search(r"title(\d+)", pdf_path.stem, re.IGNORECASE)
    title = match.group(1) if match else "6"
    return parse_wyoming_title_text(
        text,
        source_url=f"{COMPRESS}/title{title}.pdf",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def parse_configured_wyoming_title(
    *,
    code_name: str = "Wyoming Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_title_text_path()
    if path is None:
        return []
    if path.suffix.lower() == ".pdf":
        return parse_wyoming_title_pdf(path, code_name=code_name, max_statutes=max_statutes)
    match = re.search(r"title(\d+)", path.stem, re.IGNORECASE)
    title = match.group(1) if match else "6"
    return parse_wyoming_title_text(
        path.read_text(encoding="utf-8", errors="replace"),
        source_url=f"{COMPRESS}/title{title}.pdf",
        code_name=code_name,
        max_statutes=max_statutes,
    )
