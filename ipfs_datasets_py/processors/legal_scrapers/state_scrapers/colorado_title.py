"""Official Colorado Revised Statutes title SGML/HTM parser.

OLLS publishes personal-use HTM/PDF/DOCX title downloads. The authenticated
SGML zip is request-only under 2-5-118 C.R.S.; this adapter never auto-fetches
it. Set ``COLORADO_CRS_SGML``, ``COLORADO_CRS_SGML_ZIP``, or
``COLORADO_TITLE_HTML`` to a local file.

Adapted from the Vaquill-AI/open-us-law CRS title layout (Apache-2.0).
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

from .base_scraper import NormalizedStatute, StatuteMetadata

CONTENT_BASE = "https://content.leg.colorado.gov"
_SECTION_NUM_RE = re.compile(r"\b(\d{1,2}-\d{1,3}-\d{1,4}(?:\.\d+)?)\b")
_HEADING_RE = re.compile(
    r"(?m)^\s*(?P<num>\d{1,2}-\d{1,3}-\d{1,4}(?:\.\d+)?)\.\s*(?P<head>[^\n]+)"
)
_RESERVED = re.compile(
    r"\b(repealed|reserved|expired|renumbered|transferred)\b",
    re.IGNORECASE,
)
_SOURCE_RE = re.compile(r"^\s*(source|history|annotation|cross references)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_LOCAL_TAG = re.compile(r"\{[^}]*\}")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def title_search_url(number: str) -> str:
    token = str(number or "").strip().replace(".", "-")
    return f"{CONTENT_BASE}/publication-search?search_api_fulltext=crs%20title%20{token}"


def publication_rows(html: str) -> List[Tuple[str, str, str]]:
    """OLLS ``.views-row`` CRS publications. PDFs are never auto-downloaded."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in soup.select(".views-row"):
        row_text = _clean(row.get_text(" "))
        if "C.R.S." not in row_text and "Colorado Revised Statutes" not in row_text:
            continue
        detail_url = ""
        pdf_url = ""
        title = ""
        for link in row.select("a[href]"):
            href = str(link.get("href") or "").strip()
            text = _clean(link.get_text(" "))
            if not href:
                continue
            absolute = urljoin(CONTENT_BASE + "/", href)
            if "/publications/" in href and not title:
                detail_url = absolute
                title = text or row_text[:240]
            if href.lower().endswith(".pdf"):
                pdf_url = absolute
        if not detail_url and not pdf_url:
            continue
        match = _SECTION_NUM_RE.search(title or row_text)
        number = match.group(1) if match else ""
        if not number:
            title_match = re.search(r"\bTitle\s+(\d{1,2}(?:\.\d+)?)\b", title or row_text, re.I)
            number = title_match.group(1) if title_match else ""
        if not number:
            continue
        key = detail_url or pdf_url
        if key in seen:
            continue
        seen.add(key)
        out.append((number, title or row_text[:240], detail_url or pdf_url))
    return out


def crs_zip_member_names(zip_path: Path) -> List[str]:
    """Local zip namelist only. Never downloads the authenticated SGML zip."""

    path = Path(zip_path)
    if not path.is_file():
        return []
    with zipfile.ZipFile(path) as archive:
        return [
            name
            for name in archive.namelist()
            if name.lower().endswith((".htm", ".html", ".sgm", ".sgml", ".xml"))
            and not name.endswith("/")
        ]


def _local(tag: str) -> str:
    return _LOCAL_TAG.sub("", tag or "").lower()


def _is_reserved(text: str) -> bool:
    return bool(_RESERVED.search(text or ""))


def _statute(
    *,
    number: str,
    heading: str,
    body: str,
    code_name: str,
    source_kind: str,
    source_url: str,
) -> Optional[NormalizedStatute]:
    if _is_reserved(heading) or len(body) < 40:
        return None
    parts = number.split("-")
    return NormalizedStatute(
        state_code="CO",
        state_name="Colorado",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=parts[0] if parts else None,
        chapter_number=parts[1] if len(parts) > 1 else None,
        section_number=number,
        section_name=heading[:200] or f"Section {number}",
        full_text=body[:14000],
        source_url=source_url,
        official_cite=f"Colo. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": source_kind,
            "source_authority_class": "official",
            "discovery_method": "olls_crs_title_sgml_htm",
            "skip_hydrate": True,
        },
    )


def parse_colorado_sgml(
    xml_text: str,
    *,
    code_name: str = "Colorado Revised Statutes",
    source_url: str = CONTENT_BASE,
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse CRS ``<section>`` / ``<catchline>`` SGML or XML."""

    text = str(xml_text or "").strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        wrapped = f"<crs>{text}</crs>"
        try:
            root = ET.fromstring(wrapped)
        except ET.ParseError:
            return []

    statutes: List[NormalizedStatute] = []
    for node in root.iter():
        if _local(node.tag) != "section":
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = ""
        for key, value in (node.attrib or {}).items():
            if _local(key) in {"n", "num", "number", "id"} and _SECTION_NUM_RE.search(value or ""):
                number = _SECTION_NUM_RE.search(value).group(1)
                break
        heading = ""
        body_parts: List[str] = []
        for child in list(node):
            local = _local(child.tag)
            child_text = _clean(" ".join(child.itertext()))
            if local in {"catchline", "heading", "title", "sectno", "num"}:
                if local in {"sectno", "num"} and not number:
                    match = _SECTION_NUM_RE.search(child_text)
                    number = match.group(1) if match else child_text
                elif local in {"catchline", "heading", "title"}:
                    heading = child_text
            elif local in {"source", "history", "annotation", "notes"}:
                continue
            elif child_text:
                body_parts.append(child_text)
        if not number:
            match = _SECTION_NUM_RE.search(_clean(" ".join(node.itertext())))
            if match:
                number = match.group(1)
        if not number:
            continue
        body = _clean(" ".join(body_parts)) or _clean(
            " ".join(
                part
                for part in (_clean(node.text or ""),)
                if part and not _SOURCE_RE.match(part)
            )
        )
        row = _statute(
            number=number,
            heading=heading or f"Section {number}",
            body=body,
            code_name=code_name,
            source_kind="official_colorado_crs_sgml",
            source_url=source_url,
        )
        if row is not None:
            statutes.append(row)
    return statutes


def parse_colorado_title_html(
    html: str,
    *,
    code_name: str = "Colorado Revised Statutes",
    source_url: str = CONTENT_BASE,
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse OLLS personal-use title HTM (``N-N-N. heading`` then body)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text = html or ""
    else:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    matches = list(_HEADING_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end]
        paras = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line or _SOURCE_RE.match(line):
                continue
            paras.append(line)
        body = _clean(" ".join(paras))
        row = _statute(
            number=number,
            heading=heading,
            body=body,
            code_name=code_name,
            source_kind="official_colorado_title_htm",
            source_url=source_url,
        )
        if row is not None:
            statutes.append(row)
    return statutes


def parse_colorado_crs(
    payload: str | bytes,
    *,
    filename: str = "",
    code_name: str = "Colorado Revised Statutes",
    source_url: str = CONTENT_BASE,
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    name = filename.lower()
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload or "")
    if name.endswith((".sgm", ".sgml", ".xml")) or "<section" in text.lower():
        rows = parse_colorado_sgml(
            text, code_name=code_name, source_url=source_url, max_statutes=max_statutes
        )
        if rows:
            return rows
    return parse_colorado_title_html(
        text, code_name=code_name, source_url=source_url, max_statutes=max_statutes
    )


def parse_colorado_crs_zip(
    zip_path: Path,
    *,
    code_name: str = "Colorado Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith((".htm", ".html", ".sgm", ".sgml", ".xml"))
            and not name.endswith("/")
        )
        for member in names:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            try:
                payload = archive.read(member)
            except Exception:
                continue
            remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
            statutes.extend(
                parse_colorado_crs(
                    payload,
                    filename=member,
                    code_name=code_name,
                    source_url=f"{CONTENT_BASE}#{member}",
                    max_statutes=remaining,
                )
            )
    return statutes


def configured_crs_path() -> Optional[Path]:
    for key in ("COLORADO_CRS_SGML", "COLORADO_TITLE_HTML", "COLORADO_CRS_SGML_ZIP"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def configured_publication_html_path() -> Optional[Path]:
    raw = str(os.environ.get("COLORADO_PUBLICATION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_publication_html() -> List[Tuple[str, str, str]]:
    """Local OLLS publication-search dump. PDFs are never auto-downloaded."""

    path = configured_publication_html_path()
    if path is None:
        return []
    return publication_rows(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_colorado_crs(
    *,
    code_name: str = "Colorado Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_crs_path()
    if path is None:
        return []
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        return parse_colorado_crs_zip(path, code_name=code_name, max_statutes=max_statutes)
    return parse_colorado_crs(
        path.read_text(encoding="utf-8", errors="replace"),
        filename=path.name,
        code_name=code_name,
        max_statutes=max_statutes,
    )
