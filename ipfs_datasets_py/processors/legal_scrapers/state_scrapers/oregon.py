"""Scraper for Oregon state laws.

This implementation parses Oregon Revised Statutes (ORS) chapter pages and
builds section-level records with rich structure, including:
- preambles
- subsection trees
- citation extraction
- trailing legislative history extraction
- per-section JSON-LD (US Code style fields)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .citation_history import extract_trailing_history_citations
from .registry import StateScraperRegistry

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

ORS_LINK_RE = re.compile(r"ors(\d{3}[a-z]?)\.html$", re.IGNORECASE)
SUBSEC_TOKEN_RE = re.compile(r"\(([0-9]+|[A-Za-z]{1,6})\)")
ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_UPPER_RE = re.compile(r"^[IVXLCDM]+$")
COMMON_ROMAN_LOWER = {
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
}
COMMON_ROMAN_UPPER = {token.upper() for token in COMMON_ROMAN_LOWER}

ORS_CITATION_RE = re.compile(r"\b\d{1,3}\.\d{3}[a-z]?\b", re.IGNORECASE)
OR_LAWS_CITATION_RE = re.compile(r"\bOr\.?\s+Laws\s+\d{4},\s+c\.?\s*\d+\b", re.IGNORECASE)
USC_CITATION_RE = re.compile(r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*)?\d[\w\-.()]*", re.IGNORECASE)
SECTION_REF_RE = re.compile(
    r"\b(?:section|sec\.?|§{1,2})\s+[\w\-.(),\sand]+(?:\s+of\s+(?:this\s+chapter|ORS\s+chapter\s+\d+))?\b",
    re.IGNORECASE,
)


def _norm_space(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe_keep_order(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = _norm_space(str(item or ""))
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _lineify(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = _norm_space(raw_line)
        if line:
            lines.append(line)
    return lines


def _chapter_slug_from_url(url: str) -> Optional[str]:
    match = ORS_LINK_RE.search(str(url or ""))
    if not match:
        return None
    return match.group(1).lower()


def _chapter_number_display(chapter_slug: str) -> str:
    digits = "".join(ch for ch in chapter_slug if ch.isdigit())
    suffix = "".join(ch for ch in chapter_slug if ch.isalpha())
    if not digits:
        return chapter_slug
    return f"{int(digits)}{suffix}"


def _extract_chapter_title(lines: Sequence[str], chapter_display: str) -> str:
    pattern = re.compile(
        rf"^chapter\s+{re.escape(chapter_display)}\b\s*[\-\u2013\u2014\u00ad\u00a0\s:]*\s*(.*)$",
        re.IGNORECASE,
    )
    for line in lines[:200]:
        match = pattern.match(line)
        if match:
            value = _norm_space(match.group(1))
            if value:
                return value
    return ""


def _extract_edition_year(lines: Sequence[str]) -> Optional[int]:
    for line in lines[:300]:
        match = re.search(r"\b(20\d{2})\s+edition\b", line, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _section_start_regex(chapter_display: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*({re.escape(chapter_display)}\.\d{{3}}[a-z]?)\b\s*(.*)$", re.IGNORECASE)


def _classify_subsec_kind(token: str, prev_kind: Optional[str]) -> str:
    if token.isdigit():
        return "numeric"

    if token.islower():
        if token in COMMON_ROMAN_LOWER and prev_kind in {"alpha_upper", "roman_lower", "roman_upper"}:
            return "roman_lower"
        if len(token) > 1 and ROMAN_LOWER_RE.match(token):
            return "roman_lower"
        return "alpha_lower"

    if token.isupper():
        if token in COMMON_ROMAN_UPPER and prev_kind in {"roman_lower", "roman_upper"}:
            return "roman_upper"
        if len(token) > 1 and ROMAN_UPPER_RE.match(token):
            return "roman_upper"
        return "alpha_upper"

    return "other"


def _subsec_level(kind: str) -> int:
    order = {
        "numeric": 1,
        "alpha_lower": 2,
        "alpha_upper": 3,
        "roman_lower": 4,
        "roman_upper": 5,
        "other": 6,
    }
    return int(order.get(kind, 6))


def _find_subsec_markers(text: str) -> List[Tuple[int, int, str]]:
    markers: List[Tuple[int, int, str]] = []
    for match in SUBSEC_TOKEN_RE.finditer(text):
        start = int(match.start())
        end = int(match.end())
        token = str(match.group(1))

        if len(token) > 6:
            continue
        if token.isdigit() and len(token) > 3:
            continue
        if token.isalpha():
            if not (token.islower() or token.isupper()):
                continue
            if len(token) > 1:
                if token.islower() and not ROMAN_LOWER_RE.match(token):
                    continue
                if token.isupper() and not ROMAN_UPPER_RE.match(token):
                    continue

        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[end] if end < len(text) else ""

        valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.(["
        valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
        if not (valid_left and valid_right):
            continue

        markers.append((start, end, token))
    return markers


def _parse_subsections(text: str) -> List[Dict[str, Any]]:
    text = _norm_space(text)
    markers = _find_subsec_markers(text)
    if not markers:
        return []

    items: List[Dict[str, Any]] = []
    prev_kind: Optional[str] = None
    for idx, (start, end, token) in enumerate(markers):
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        body = _norm_space(text[end:next_start])
        kind = _classify_subsec_kind(token, prev_kind)
        prev_kind = kind
        items.append(
            {
                "label": f"({token})",
                "token": token,
                "kind": kind,
                "level": _subsec_level(kind),
                "text": body,
                "subsections": [],
            }
        )

    roots: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []

    for item in items:
        level = int(item["level"])
        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()

        parent_subsections = roots if not stack else stack[-1]["subsections"]

        existing_node: Optional[Dict[str, Any]] = None
        for sibling in reversed(parent_subsections):
            if sibling.get("label") == item["label"]:
                existing_node = sibling
                break

        if existing_node is None:
            node = {
                "label": item["label"],
                "token": item["token"],
                "kind": item["kind"],
                "text": item["text"],
                "subsections": [],
            }
            parent_subsections.append(node)
        else:
            node = existing_node
            new_text = _norm_space(str(item.get("text") or ""))
            old_text = _norm_space(str(node.get("text") or ""))
            if new_text:
                if not old_text:
                    node["text"] = new_text
                elif new_text not in old_text:
                    node["text"] = f"{old_text} {new_text}".strip()

        stack.append({"level": level, "subsections": node["subsections"]})

    return roots


def _validate_subsection_tree(nodes: Sequence[Dict[str, Any]], *, max_depth: int = 6) -> List[str]:
    issues: List[str] = []

    def walk(siblings: Sequence[Dict[str, Any]], depth: int, path: str) -> None:
        if depth > max_depth:
            issues.append(f"depth>{max_depth} at {path or 'root'}")

        seen_labels: Dict[str, int] = {}
        for index, node in enumerate(siblings, start=1):
            label = str(node.get("label", ""))
            kind = str(node.get("kind", ""))
            text = _norm_space(str(node.get("text", "")))
            children = node.get("subsections", [])

            if label:
                seen_labels[label] = seen_labels.get(label, 0) + 1
                if seen_labels[label] > 1:
                    issues.append(f"duplicate sibling label {label} at {path or 'root'}")

            if not text and not children:
                issues.append(f"empty leaf node {label or '#'+str(index)} at {path or 'root'}")

            if kind not in {"numeric", "alpha_lower", "alpha_upper", "roman_lower", "roman_upper", "other"}:
                issues.append(f"unknown kind {kind} for {label or '#'+str(index)}")

            child_path = f"{path}/{label}" if path else label
            if isinstance(children, list) and children:
                walk(children, depth + 1, child_path)

    walk(nodes, depth=1, path="")
    return sorted(set(issues))


def _extract_preamble(text: str) -> str:
    source = _norm_space(text)
    if not source:
        return ""

    markers = _find_subsec_markers(source)
    if markers and markers[0][0] > 0:
        return _norm_space(source[: markers[0][0]])[:600]

    sentence_match = re.match(r"(.{1,600}?[\.;:])(\s|$)", source)
    if sentence_match:
        return _norm_space(sentence_match.group(1))

    return _norm_space(source[:600])


def _extract_citations(full_text: str, core_text: str = "") -> Dict[str, List[str]]:
    base = str(full_text or "")
    core = str(core_text or "") or base
    return {
        "ors_citations": _dedupe_keep_order(ORS_CITATION_RE.findall(core)),
        "session_laws": _dedupe_keep_order(OR_LAWS_CITATION_RE.findall(base)),
        "usc_citations": _dedupe_keep_order(USC_CITATION_RE.findall(core)),
        "section_references": _dedupe_keep_order(SECTION_REF_RE.findall(core)),
    }


def _extract_legislative_history(full_text: str) -> Dict[str, Any]:
    cleaned_text, raw_blocks, citations = extract_trailing_history_citations(full_text)
    return {
        "cleaned_text": cleaned_text,
        "enactment_citation_blocks": raw_blocks,
        "history_citations": citations,
    }


def _section_sort_key(section_id: str) -> Tuple[int, str]:
    match = re.match(r"^([0-9]+)\.([0-9]+)([a-z]?)$", str(section_id or ""), flags=re.IGNORECASE)
    if not match:
        return (10**9, str(section_id or ""))
    return (int(match.group(2)), (match.group(3) or "").lower())


def _build_section_jsonld(section: Dict[str, Any]) -> Dict[str, Any]:
    chapter_number = str(section.get("chapter_number") or "")
    chapter_title = str(section.get("chapter_title") or "")
    section_number = str(section.get("section_number") or "")
    section_name = str(section.get("section_name") or "")
    source_url = str(section.get("source_url") or "")
    year_value = section.get("year")
    text = str(section.get("text") or "")
    preamble = str(section.get("preamble") or "")
    citations = section.get("citations") or {}
    legislative_history = section.get("legislative_history") or {}
    subsections = section.get("subsections") or []
    parser_warnings = section.get("parser_warnings") or []

    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "ors": "https://www.oregonlegislature.gov/bills_laws/ors/",
            "chapterNumber": "ors:chapterNumber",
            "sectionNumber": "ors:sectionNumber",
            "sourceUrl": "ors:sourceUrl",
        },
        "@type": "Legislation",
        "@id": f"urn:ors:chapter:{chapter_number}:section:{section_number}:year:{year_value or 'unknown'}",
        "name": section_name or f"ORS {section_number}",
        "isPartOf": {
            "@type": "CreativeWork",
            "name": f"Oregon Revised Statutes Chapter {chapter_number}",
            "identifier": f"ORS-{chapter_number}",
        },
        "legislationType": "statute",
        "titleName": "Oregon Revised Statutes",
        "chapterNumber": chapter_number,
        "chapterName": chapter_title,
        "sectionNumber": section_number,
        "dateModified": str(year_value) if year_value is not None else None,
        "sourceUrl": source_url,
        "preamble": preamble,
        "citations": citations,
        "legislativeHistory": legislative_history,
        "text": text,
        "subsections": subsections,
        "parser_warnings": parser_warnings,
    }


class OregonScraper(BaseStateScraper):
    """Scraper for Oregon state laws from https://www.oregonlegislature.gov"""


class OregonScraper(BaseStateScraper):
    """Scraper for Oregon state laws from https://www.oregonlegislature.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Oregon's legislative website."""
        return "https://www.oregonlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Oregon."""
        return [{
            "name": "Oregon Revised Statutes",
            "url": f"{self.get_base_url()}/bills_laws/ors/ors001.html",
            "type": "Code"
        }]

    def _make_session(self) -> "requests.Session":
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "ipfs-datasets-oregon-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            }
        )
        return session

    def _discover_chapter_urls(self, session: "requests.Session", seed_url: str) -> List[str]:
        try:
            response = session.get(seed_url, timeout=60)
            if int(response.status_code) != 200:
                self.logger.warning(f"Oregon seed request failed ({response.status_code}): {seed_url}")
                return [seed_url]
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception as exc:
            self.logger.warning(f"Oregon chapter discovery failed: {exc}")
            return [seed_url]

        chapter_urls: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            absolute = urljoin(seed_url, href)
            if ORS_LINK_RE.search(absolute):
                chapter_urls.append(absolute)

        chapter_urls = _dedupe_keep_order(chapter_urls)
        if seed_url not in chapter_urls and ORS_LINK_RE.search(seed_url):
            chapter_urls.append(seed_url)

        return sorted(chapter_urls, key=lambda url: _chapter_sort_key(_chapter_slug_from_url(url) or ""))

    def _parse_chapter_html(
        self,
        *,
        html: str,
        chapter_url: str,
        code_name: str,
        citation_format: str,
        legal_area: str,
    ) -> List[NormalizedStatute]:
        lines = _lineify(html)
        if not lines:
            return []

        chapter_slug = _chapter_slug_from_url(chapter_url)
        if not chapter_slug:
            return []

        chapter_display = _chapter_number_display(chapter_slug)
        chapter_title = _extract_chapter_title(lines, chapter_display)
        year_value = _extract_edition_year(lines)
        start_re = _section_start_regex(chapter_display)

        sections_raw: List[Dict[str, Any]] = []
        current_id: Optional[str] = None
        current_title: str = ""
        buffer: List[str] = []

        def flush() -> None:
            nonlocal current_id, current_title, buffer
            if not current_id:
                return

            full_text = _norm_space("\n".join(buffer))
            legislative_history = _extract_legislative_history(full_text)
            clean_text = _norm_space(str(legislative_history.get("cleaned_text") or full_text))
            preamble = _extract_preamble(clean_text)
            subsections = _parse_subsections(clean_text)
            parser_warnings = _validate_subsection_tree(subsections)
            citations = _extract_citations(full_text, clean_text)

            section_number = current_id.lower()
            section_name = _norm_space(current_title) or f"ORS {section_number}"

            section_row = {
                "chapter_number": chapter_display,
                "chapter_title": chapter_title,
                "section_number": section_number,
                "section_name": section_name,
                "text": clean_text,
                "preamble": preamble,
                "citations": citations,
                "legislative_history": {
                    "enactment_citation_blocks": legislative_history.get("enactment_citation_blocks", []),
                    "history_citations": legislative_history.get("history_citations", []),
                },
                "subsections": subsections,
                "parser_warnings": parser_warnings,
                "year": year_value,
                "source_url": f"{chapter_url}#section-{section_number}",
            }
            section_row["jsonld"] = _build_section_jsonld(section_row)
            sections_raw.append(section_row)

            current_id = None
            current_title = ""
            buffer = []

        for line in lines:
            match = start_re.match(line)
            if match:
                flush()
                current_id = match.group(1)
                current_title = match.group(2) or ""
                buffer = []
                continue
            if current_id:
                buffer.append(line)

        flush()

        by_section_id: Dict[str, Dict[str, Any]] = {}
        for row in sections_raw:
            sec_id = str(row.get("section_number") or "")
            prev = by_section_id.get(sec_id)
            if prev is None or len(str(row.get("text") or "")) > len(str(prev.get("text") or "")):
                by_section_id[sec_id] = row

        statutes: List[NormalizedStatute] = []
        for section_id in sorted(by_section_id.keys(), key=_section_sort_key):
            row = by_section_id[section_id]
            history_citations = row.get("legislative_history", {}).get("history_citations") or []
            metadata = StatuteMetadata(
                enacted_year=str(row.get("year")) if row.get("year") is not None else None,
                history=[str(item) for item in row.get("legislative_history", {}).get("enactment_citation_blocks") or []],
            )

            structured_data = {
                "preamble": row.get("preamble"),
                "citations": row.get("citations"),
                "legislative_history": row.get("legislative_history"),
                "subsections": row.get("subsections"),
                "parser_warnings": row.get("parser_warnings"),
                "jsonld": row.get("jsonld"),
                "history_citations": history_citations,
            }

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"ORS {section_id}",
                    code_name=code_name,
                    title_number=chapter_display,
                    title_name=chapter_title or f"ORS Chapter {chapter_display}",
                    chapter_number=chapter_display,
                    chapter_name=chapter_title or None,
                    section_number=section_id,
                    section_name=str(row.get("section_name") or ""),
                    short_title=str(row.get("section_name") or ""),
                    full_text=str(row.get("text") or ""),
                    summary=str(row.get("preamble") or ""),
                    legal_area=legal_area,
                    keywords=_dedupe_keep_order(
                        [
                            *(row.get("citations", {}).get("ors_citations") or []),
                            *(row.get("citations", {}).get("section_references") or []),
                        ]
                    )[:200],
                    source_url=str(row.get("source_url") or chapter_url),
                    official_cite=f"{citation_format} § {section_id}",
                    metadata=metadata,
                    structured_data=structured_data,
                )
            )

        return statutes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Oregon's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        citation_format = "Or. Rev. Stat."
        if not REQUESTS_AVAILABLE:
            self.logger.warning("requests/bs4 unavailable for Oregon parser; falling back to Playwright link scrape")
            return await self._playwright_scrape(
                code_name,
                code_url,
                citation_format,
                wait_for_selector="a[href*='ors']",
                timeout=45000,
                max_sections=250,
            )

        legal_area = self._identify_legal_area(code_name)
        statutes: List[NormalizedStatute] = []

        try:
            session = self._make_session()
            chapter_urls = self._discover_chapter_urls(session, code_url)
            self.logger.info(f"Oregon: discovered {len(chapter_urls)} ORS chapter pages")

            for chapter_url in chapter_urls:
                try:
                    response = session.get(chapter_url, timeout=90)
                    if int(response.status_code) != 200:
                        self.logger.warning(f"Oregon chapter fetch failed ({response.status_code}): {chapter_url}")
                        continue
                    statutes.extend(
                        self._parse_chapter_html(
                            html=response.text,
                            chapter_url=chapter_url,
                            code_name=code_name,
                            citation_format=citation_format,
                            legal_area=legal_area,
                        )
                    )
                except Exception as chapter_exc:
                    self.logger.warning(f"Oregon chapter parse error for {chapter_url}: {chapter_exc}")
                    continue
        except Exception as exc:
            self.logger.error(f"Oregon scrape failed: {exc}")

        if statutes:
            self.logger.info(f"Oregon: parsed {len(statutes)} structured ORS sections")
            return statutes

        self.logger.warning("Oregon parser produced no structured sections; using Playwright fallback")
        return await self._playwright_scrape(
            code_name,
            code_url,
            citation_format,
            wait_for_selector="a[href*='ors']",
            timeout=45000,
            max_sections=250,
        )


def _chapter_sort_key(chapter_slug: str) -> Tuple[int, str]:
    digits = "".join(ch for ch in str(chapter_slug or "") if ch.isdigit())
    suffix = "".join(ch for ch in str(chapter_slug or "") if ch.isalpha()).lower()
    try:
        return (int(digits), suffix)
    except Exception:
        return (10**9, str(chapter_slug or ""))


# Register this scraper with the registry
StateScraperRegistry.register("OR", OregonScraper)
