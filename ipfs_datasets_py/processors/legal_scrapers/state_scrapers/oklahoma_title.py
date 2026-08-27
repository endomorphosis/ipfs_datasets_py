"""Official Oklahoma complete-title PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``scrapeOK.py`` (Apache-2.0).
Local fixtures may be supplied with ``OKLAHOMA_TITLE_TEXT`` or
``OKLAHOMA_TITLE_PDF``.  Live acquisition is owned by ``OklahomaScraper`` so it
can reuse the shared state-law cache and web-archiving transports.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

COMPLETE_TITLE_BASE = "https://www.oklegislature.gov/OK_Statutes/CompleteTitles"
TITLES_HTML_URL = "https://www.oklegislature.gov/osstatuestitle.html"
EXPECTED_TITLE_COUNT = 89
_OS_PDF_RE = re.compile(r"/os(\d+[A-Ea-e]?)\.pdf$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(
    r"^§\s*(?P<title>[0-9]+[A-Za-z]?)\s*[-‑]\s*"
    r"(?P<section>[0-9A-Za-z][0-9A-Za-z.\-]*?)\s+(?P<name>.*)$"
)
_RULE_HEADING_RE = re.compile(
    r"^Rule\s+(?P<number>\d+(?:\.\d+)+)\.?\s*(?P<name>.*)$",
    re.IGNORECASE,
)
_HISTORY_START_RE = re.compile(
    r"^(R\.L\.\d{4}|Laws\s+\d{4}|Added\s+by\s+Laws|Amended\s+by\s+Laws|"
    r"Renumbered\s+(?:by|from)\s+Laws|Repealed\s+by\s+Laws|Transferred\s+by\s+Laws|"
    r"Promulgated\s+by|Amendment\s+promulgated\s+by)",
    re.IGNORECASE,
)
_TOC_DOTS_RE = re.compile(r"\.\s*\.\s*\.\s*\.\s*\.")
_VERSION_INDEX_HEADING_RE = re.compile(
    r"^See\s+the\s+following\s+versions:?$",
    re.IGNORECASE,
)
_RESERVED = re.compile(
    r"\((?:reserved|repealed|expired|renumbered|deleted)\)\s*\.?\s*$",
    re.IGNORECASE,
)
_INACTIVE_HEADING_RE = re.compile(
    r"^(?:reserved|repealed|renumbered|transferred|expired|deleted)"
    r"(?=\s*(?:$|[().,;:\-]|\b(?:as|by|effective|from|to)\b))",
    re.IGNORECASE,
)
_INACTIVE_BODY_RE = re.compile(
    r"^\(?(?:reserved|repealed|renumbered|transferred|expired|deleted)\)?(?:[.,;]|$)",
    re.IGNORECASE,
)
_PAGE_CHROME_RE = re.compile(
    r"^Oklahoma\s+Statutes\s*-\s*Title\b.*\bPage\s+\d+\s*$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class OklahomaInactiveTitleFrontier:
    """Byte-bound proof that one official complete-title PDF has no current law."""

    schema_version: str
    jurisdiction_code: str
    code_name: str
    title_number: str
    source_url: str
    official_source: bool
    frontier_closed: bool
    disposition: str
    expected_statute_count: int
    inactive_section_count: int
    content_sha256: str
    observed_at: str
    transport_receipt: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("‑", "-")).strip()


def _is_table_of_contents_page(lines: List[str]) -> bool:
    """Identify an official PDF table-of-contents page from local layout evidence."""

    section_rows = 0
    dot_leader_rows = 0
    for raw in lines:
        line = str(raw or "").strip().replace("‑", "-")
        if not line:
            continue
        if _SECTION_HEADING_RE.match(line):
            section_rows += 1
        if _TOC_DOTS_RE.search(line):
            dot_leader_rows += 1
    # Opening TOC pages contain dense section locators and repeated dot
    # leaders.  Operative pages can contain several adjacent repealed section
    # headings, so neither signal is sufficient on its own.
    return section_rows >= 2 and dot_leader_rows >= 2


def _statutory_lines_from_pdf_page(lines: List[str]) -> List[str]:
    """Keep statutory text, including a suffix sharing a page with the TOC.

    Oklahoma Title 33 is a one-page publication: four dot-leader inventory
    entries are followed by the four official repealed section headings.  A
    whole-page TOC exclusion would erase that closed inactive frontier.  On a
    dense TOC page, retain only a suffix after the final dot leader when that
    suffix independently starts another section sequence; otherwise exclude
    the page as navigation.
    """

    normalized = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not _is_table_of_contents_page(normalized):
        return normalized
    dot_leader_offsets = [
        index
        for index, line in enumerate(normalized)
        if _TOC_DOTS_RE.search(line.replace("‑", "-"))
    ]
    if not dot_leader_offsets:
        return []
    suffix = normalized[dot_leader_offsets[-1] + 1 :]
    if not any(
        _SECTION_HEADING_RE.match(line.replace("‑", "-")) for line in suffix
    ):
        return []
    return suffix


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
    statutes_by_id: dict[str, NormalizedStatute] = {}
    current: Optional[dict] = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        # Wrapped entries in the official PDFs' opening tables of contents can
        # begin with a section-shaped line and put the dot leader/page number
        # only on a continuation line.  That dot leader is byte-local proof
        # that the candidate is navigation, not statutory text.
        if current.get("toc_evidence") is True:
            current = None
            return
        heading = current["name"]
        body = _clean(" ".join(current["body"]))
        if (
            _VERSION_INDEX_HEADING_RE.fullmatch(heading)
            or
            _RESERVED.search(heading)
            or _INACTIVE_HEADING_RE.search(heading)
            or _INACTIVE_BODY_RE.search(body)
            or len(body) < 40
        ):
            current = None
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current = None
            return
        number = current["number"]
        title = str(current.get("title") or number.split("-", 1)[0])
        link = source_url or f"{COMPLETE_TITLE_BASE}/os{title}.pdf"
        candidate = NormalizedStatute(
                state_code="OK",
                state_name="Oklahoma",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title,
                section_number=number,
                section_name=heading[:200] or f"Section {number}",
                full_text=body,
                source_url=link,
                official_cite=str(
                    current.get("official_cite")
                    or f"Okla. Stat. tit. {title}, § {number}"
                ),
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_oklahoma_complete_title",
                    "source_authority_class": "official",
                    "discovery_method": "oklegislature_complete_title_pdf",
                    "skip_hydrate": True,
                },
        )
        prior = statutes_by_id.get(candidate.statute_id)
        if prior is not None:
            prior_identity = (
                prior.code_name,
                prior.title_number,
                prior.section_number,
                prior.section_name,
                prior.full_text,
                prior.source_url,
                prior.official_cite,
            )
            candidate_identity = (
                candidate.code_name,
                candidate.title_number,
                candidate.section_number,
                candidate.section_name,
                candidate.full_text,
                candidate.source_url,
                candidate.official_cite,
            )
            if candidate_identity != prior_identity:
                raise ValueError(
                    "Oklahoma official title contains conflicting duplicate "
                    f"section identity: {candidate.statute_id}"
                )
            occurrences = int(
                prior.structured_data.get("source_duplicate_occurrence_count", 1)
            )
            prior.structured_data["source_duplicate_occurrence_count"] = occurrences + 1
            prior.structured_data["source_duplicate_disposition"] = (
                "collapsed_exact_normalized_official_duplicate"
            )
            current = None
            return
        statutes.append(candidate)
        statutes_by_id[candidate.statute_id] = candidate
        current = None

    expected = title_number.upper()
    for raw in lines:
        line = raw.replace("‑", "-")
        if _TOC_DOTS_RE.search(line):
            if current is not None:
                current["toc_evidence"] = True
            continue
        match = _SECTION_HEADING_RE.match(line)
        if match:
            matched_title = match.group("title").upper()
            if expected and matched_title != expected:
                continue
            flush()
            section = match.group("section").rstrip(".")
            if not section:
                continue
            current = {
                "number": f"{matched_title}-{section}",
                "name": _clean(match.group("name").rstrip(". ")),
                "body": [],
                "in_history": False,
                "title": matched_title,
                "toc_evidence": False,
            }
            continue
        rule_match = _RULE_HEADING_RE.match(line)
        if rule_match:
            if expected and expected != "74E":
                continue
            flush()
            rule_number = rule_match.group("number")
            current = {
                "number": f"74E-Rule-{rule_number}",
                "name": _clean(rule_match.group("name").rstrip(". ")),
                "body": [],
                "in_history": False,
                "title": "74E",
                "toc_evidence": False,
                "official_cite": (
                    "Okla. Stat. tit. 74, app. I, Ethics Comm'n R. "
                    f"{rule_number}"
                ),
            }
            continue
        if current is None:
            continue
        cleaned = _clean(line)
        if not cleaned:
            continue
        if _PAGE_CHROME_RE.match(cleaned):
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
    text = extract_oklahoma_title_pdf_text(pdf_path.read_bytes())
    match = re.search(r"os(\d+[A-Ea-e]?)\.pdf$", pdf_path.name, re.IGNORECASE)
    number = title_number or (match.group(1).upper() if match else "")
    return parse_oklahoma_title_text(
        text,
        title_number=number,
        code_name=code_name,
        source_url=f"{COMPLETE_TITLE_BASE}/os{number}.pdf" if number else COMPLETE_TITLE_BASE,
        max_statutes=max_statutes,
    )


def extract_oklahoma_title_pdf_text(payload: bytes) -> str:
    """Extract official PDF text while excluding page-bound TOC material.

    The production scraper already owns the retained PDF bytes.  Keeping page
    boundaries here is essential: flattening the whole document before the
    Oklahoma parser runs makes opening table-of-contents entries collide with
    their operative sections later in the publication.
    """

    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("Oklahoma page-aware PDF extraction requires pdfplumber")
    raw = bytes(payload or b"")
    if not raw:
        raise ValueError("Oklahoma complete-title PDF payload is empty")
    lines: List[str] = []
    with pdfplumber.open(BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            page_lines = [line.strip() for line in text.splitlines() if line.strip()]
            lines.extend(_statutory_lines_from_pdf_page(page_lines))
    return "\n".join(lines).strip()


def title_pdf_url(number: str) -> str:
    token = str(number or "").strip().upper()
    # The Legislature TOC spells Title 37A's filename with a lower-case suffix.
    # Preserve that exact case because the official document locator is part of
    # the provenance contract, not merely a display URL.
    filename_token = "37a" if token == "37A" else token
    return f"{COMPLETE_TITLE_BASE}/os{filename_token}.pdf"


def title_number_from_pdf_url(url: str) -> str:
    match = _OS_PDF_RE.search(str(url or "").strip())
    return match.group(1).upper() if match else ""


def title_pdf_links(html: str) -> List[Tuple[str, str, str]]:
    """Return unique complete-title members from the official Legislature TOC."""

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
        absolute = urljoin(TITLES_HTML_URL, href)
        parsed = urlparse(absolute)
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower()
            not in {"oklegislature.gov", "www.oklegislature.gov"}
            or not parsed.path.lower().startswith(
                "/ok_statutes/completetitles/os"
            )
            or parsed.username is not None
            or parsed.password is not None
        ):
            continue
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Title {number}"
        out.append((number, name, absolute))
    return out


def inactive_title_frontier_from_text(
    text: str,
    *,
    title_number: str,
    code_name: str,
    source_url: str,
    content_sha256: str,
    observed_at: str,
    transport_receipt: Mapping[str, Any],
) -> Optional[OklahomaInactiveTitleFrontier]:
    """Prove that every section heading in an official title is inactive."""

    title = str(title_number or "").strip().upper()
    if not title or title_number_from_pdf_url(source_url) != title:
        return None
    digest = str(content_sha256 or "").strip().lower()
    if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_at or "").strip())
    except ValueError:
        return None
    if observed.tzinfo is None or observed.utcoffset() is None:
        return None
    if not isinstance(transport_receipt, Mapping):
        return None

    headings: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip().replace("‑", "-")
        if not line or _TOC_DOTS_RE.search(line):
            continue
        match = _SECTION_HEADING_RE.match(line)
        if match is None or match.group(1).upper() != title:
            continue
        headings.setdefault(
            f"{match.group(1).upper()}-{match.group(2)}",
            _clean(match.group(3)),
        )
    if not headings or any(
        _INACTIVE_HEADING_RE.search(heading) is None for heading in headings.values()
    ):
        return None

    disposition = (
        "repealed"
        if all(heading.lower().startswith("repealed") for heading in headings.values())
        else "inactive"
    )
    return OklahomaInactiveTitleFrontier(
        schema_version="oklahoma-inactive-title-frontier/v1",
        jurisdiction_code="OK",
        code_name=str(code_name or "").strip(),
        title_number=title,
        source_url=str(source_url or "").strip(),
        official_source=True,
        frontier_closed=True,
        disposition=disposition,
        expected_statute_count=0,
        inactive_section_count=len(headings),
        content_sha256=digest,
        observed_at=str(observed_at or "").strip(),
        transport_receipt=dict(transport_receipt),
    )


def configured_title_path() -> Optional[Path]:
    for key in ("OKLAHOMA_TITLE_TEXT", "OKLAHOMA_TITLE_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def configured_titles_html_path() -> Optional[Path]:
    raw = str(os.environ.get("OKLAHOMA_TITLES_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_titles_html() -> List[Tuple[str, str, str]]:
    """Parse a local ``osstatuestitle.html`` dump without network access."""

    path = configured_titles_html_path()
    if path is None:
        return []
    return title_pdf_links(path.read_text(encoding="utf-8", errors="replace"))


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
