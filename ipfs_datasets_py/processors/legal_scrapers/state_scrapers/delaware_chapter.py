"""Official Delaware Code chapter HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeDE.py`` (Apache-2.0).
Sections are ``div.Section``; body is direct ``<p>`` children; leftover
non-paragraph nodes are history and are dropped. Mojibake is undone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://delcode.delaware.gov"
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z\-]+)\.\s*(?P<head>.+)", re.IGNORECASE)
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€", "Â")


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    value = _fix_encoding((text or "").replace("\xa0", " ").replace("\u2002", " "))
    return _WS.sub(" ", value).strip()


def parse_delaware_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Delaware Code",
    title_number: str = "",
    chapter_number: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    title_match = re.search(r"/title(\d+)/", source_url, re.IGNORECASE)
    chapter_match = re.search(r"/c(\d+)/", source_url, re.IGNORECASE)
    title_number = title_number or (title_match.group(1) if title_match else "")
    chapter_number = chapter_number or (
        (chapter_match.group(1).lstrip("0") or "0") if chapter_match else ""
    )
    statutes: List[NormalizedStatute] = []
    for div in soup.find_all("div", class_="Section"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        head = div.find("div", class_="SectionHead")
        if head is None:
            continue
        heading = _clean(head.get_text(" "))
        if _RESERVED.search(heading):
            continue
        match = _HEAD_RE.search(heading)
        number = str(head.get("id") or (match.group("num") if match else "")).replace(",", "-").rstrip(".")
        name = match.group("head").strip() if match else heading
        paras: List[str] = []
        for child in div.find_all(recursive=False):
            classes = child.get("class") or []
            if "SectionHead" in classes:
                continue
            text = _clean(child.get_text(" "))
            if not text:
                continue
            if child.name == "p":
                paras.append(text)
        body = _clean(" ".join(paras))
        if not number or len(body) < 40:
            continue
        link = source_url or BASE
        if number:
            link = f"{link.split('#')[0]}#{number}"
        statutes.append(
            NormalizedStatute(
                state_code="DE",
                state_name="Delaware",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title_number or None,
                chapter_number=chapter_number or None,
                section_number=number,
                section_name=name[:200],
                full_text=body[:14000],
                source_url=link,
                official_cite=f"{title_number} Del. C. § {number}".strip(),
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_delaware_section_html",
                    "source_authority_class": "official",
                    "discovery_method": "delcode_section_div",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("DELAWARE_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_title_links_html_path() -> Optional[Path]:
    raw = str(os.environ.get("DELAWARE_TITLE_LINKS_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_title_links_html() -> List[Dict[str, str]]:
    path = configured_title_links_html_path()
    if path is None:
        return []
    return title_link_rows(path.read_text(encoding="utf-8", errors="replace"))


def title_link_rows(html: str, *, base_url: str = BASE) -> List[Dict[str, str]]:
    """Structure rows from Vaquill ``div.title-links`` containers."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, str]] = []
    seen = set()
    for container in soup.find_all("div", class_="title-links"):
        anchor = container.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(base_url.rstrip("/") + "/", href.replace("../", ""))
        name = _clean(anchor.get_text(" "))
        if not name:
            continue
        parts = name.split()
        classifier = parts[0].lower() if parts else ""
        number = parts[1].rstrip(".") if len(parts) > 1 else ""
        if url in seen or not number:
            continue
        seen.add(url)
        out.append(
            {
                "url": url,
                "name": name,
                "classifier": classifier,
                "number": number,
            }
        )
    return out


_TITLE_SECTION_RE = re.compile(
    r"^§\s*(?P<num>[0-9A-Za-z\-]+)\.\s+(?P<head>.+)$"
)
_HISTORY_LINE_RE = re.compile(
    r"^\d+\s+Del\.\s+Laws",
    re.IGNORECASE,
)


def parse_delaware_title_text(
    text: str,
    *,
    title_number: str = "",
    code_name: str = "Delaware Code",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse an authenticated title PDF extract (never auto-downloaded)."""

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    statutes: List[NormalizedStatute] = []
    current: Optional[dict] = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        heading = current["name"]
        body = _clean(" ".join(current["body"]))
        if _RESERVED.search(heading) or len(body) < 40:
            current = None
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current = None
            return
        number = current["number"]
        title = title_number or ""
        link = source_url or (f"{BASE}/title{title}/title{title}.pdf" if title else BASE)
        statutes.append(
            NormalizedStatute(
                state_code="DE",
                state_name="Delaware",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title or None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=link,
                official_cite=f"{title} Del. C. § {number}".strip(),
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_delaware_title_pdf_text",
                    "source_authority_class": "official",
                    "discovery_method": "delcode_authenticated_title_pdf",
                    "skip_hydrate": True,
                },
            )
        )
        current = None

    for raw in lines:
        match = _TITLE_SECTION_RE.match(_fix_encoding(raw))
        if match:
            flush()
            current = {
                "number": match.group("num").replace(",", "-").rstrip("."),
                "name": _clean(match.group("head")),
                "body": [],
            }
            continue
        if current is None:
            continue
        cleaned = _clean(raw)
        if not cleaned or _HISTORY_LINE_RE.match(cleaned):
            continue
        current["body"].append(cleaned)
    flush()
    return statutes


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


def parse_delaware_title_pdf(
    pdf_path: Path,
    *,
    title_number: str = "",
    code_name: str = "Delaware Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []
    match = re.search(r"title(\d+)", pdf_path.stem, re.IGNORECASE)
    number = title_number or (match.group(1) if match else "")
    return parse_delaware_title_text(
        text,
        title_number=number,
        code_name=code_name,
        source_url=f"{BASE}/title{number}/title{number}.pdf" if number else BASE,
        max_statutes=max_statutes,
    )


def configured_title_dump_path() -> Optional[Path]:
    for key in ("DELAWARE_TITLE_TEXT", "DELAWARE_TITLE_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def parse_configured_delaware_title(
    *,
    code_name: str = "Delaware Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_title_dump_path()
    if path is None:
        return []
    if path.suffix.lower() == ".pdf":
        return parse_delaware_title_pdf(path, code_name=code_name, max_statutes=max_statutes)
    match = re.search(r"title(\d+)", path.stem, re.IGNORECASE)
    title = match.group(1) if match else ""
    return parse_delaware_title_text(
        path.read_text(encoding="utf-8", errors="replace"),
        title_number=title,
        code_name=code_name,
        source_url=f"{BASE}/title{title}/title{title}.pdf" if title else BASE,
        max_statutes=max_statutes,
    )
