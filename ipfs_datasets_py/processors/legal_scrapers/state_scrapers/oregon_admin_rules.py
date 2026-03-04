"""Oregon Administrative Rules (OAR) scraper helpers.

This module provides a focused scraper for Oregon Administrative Rules pages
served by the Oregon Secretary of State OARD system.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

try:
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

_OAR_RULE_RE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")
_ORS_CITATION_RE = re.compile(r"\b\d{1,3}\.\d{3}[a-z]?\b", re.IGNORECASE)
_CHAPTER_ID_RE = re.compile(r"selectedChapter=([0-9]+)")
_DIVISION_URL_RE = re.compile(r"displayDivisionRules\.action[^\"'\s>]*selectedDivision=[0-9]+", re.IGNORECASE)


def _norm_space(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = _norm_space(item)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


class OregonAdministrativeRulesScraper:
    """Scrapes Oregon Administrative Rules from OARD chapter/division pages."""

    OARD_BASE = "https://secure.sos.state.or.us/oard"
    CDX_CHAPTER_QUERY = (
        "http://web.archive.org/cdx/search/cdx"
        "?url=secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=*"
        "&output=json&fl=original&filter=statuscode:200&collapse=urlkey&limit=100000"
    )

    def __init__(self, parent_scraper: Any):
        self.parent = parent_scraper
        self.logger = getattr(parent_scraper, "logger", None)

    @staticmethod
    def seed_chapter_url() -> str:
        # A stable, currently available chapter page used for bootstrap fallback.
        return "https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137"

    @staticmethod
    def extract_chapter_ids_from_cdx(cdx_payload: Any) -> List[int]:
        ids: List[int] = []
        if not isinstance(cdx_payload, list):
            return ids

        for row in cdx_payload:
            if not isinstance(row, (list, tuple)) or not row:
                continue
            value = str(row[0] or "")
            if value.lower() == "original":
                continue
            match = _CHAPTER_ID_RE.search(value)
            if not match:
                continue
            try:
                ids.append(int(match.group(1)))
            except Exception:
                continue

        return sorted(set(ids))

    async def _discover_chapter_urls_from_cdx(self) -> List[str]:
        if not REQUESTS_AVAILABLE:
            return []

        try:
            payload_bytes = await self.parent._fetch_page_content_with_archival_fallback(
                self.CDX_CHAPTER_QUERY,
                timeout_seconds=45,
            )
            if not payload_bytes:
                return []
            payload = self._decode_json(payload_bytes)
            chapter_ids = self.extract_chapter_ids_from_cdx(payload)
            return [f"{self.OARD_BASE}/displayChapterRules.action?selectedChapter={cid}" for cid in chapter_ids]
        except Exception:
            return []

    def _decode_json(self, payload: bytes) -> Any:
        import json

        try:
            return json.loads(payload.decode("utf-8", errors="replace"))
        except Exception:
            return []

    async def _discover_chapter_urls_from_seed(self, seed_url: str) -> List[str]:
        chapter_urls: List[str] = []
        page_bytes = await self.parent._fetch_page_content_with_archival_fallback(seed_url, timeout_seconds=90)
        if not page_bytes:
            return []

        try:
            soup = BeautifulSoup(page_bytes, "html.parser")
        except Exception:
            return []

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            absolute = urljoin(seed_url, href)
            if "displayChapterRules.action" in absolute and "selectedChapter=" in absolute:
                chapter_urls.append(self._normalize_oard_url(absolute))
        return _dedupe_keep_order(chapter_urls)

    def _normalize_oard_url(self, url: str) -> str:
        cleaned = str(url or "")
        cleaned = re.sub(r";JSESSIONID_[^?]+", "", cleaned)
        if cleaned.startswith("/"):
            cleaned = f"{self.OARD_BASE}{cleaned}"
        if cleaned.startswith("http://"):
            cleaned = "https://" + cleaned[len("http://") :]
        return cleaned

    async def discover_chapter_urls(self) -> List[str]:
        urls: List[str] = []

        seed_urls = [self.seed_chapter_url()]
        for seed in seed_urls:
            urls.extend(await self._discover_chapter_urls_from_seed(seed))

        urls.extend(await self._discover_chapter_urls_from_cdx())
        urls = _dedupe_keep_order(self._normalize_oard_url(url) for url in urls)

        # Optional limit for faster debug/iteration.
        limit_raw = os.getenv("OREGON_OAR_MAX_CHAPTERS", "").strip()
        if limit_raw:
            try:
                limit = max(1, int(limit_raw))
                urls = urls[:limit]
            except Exception:
                pass

        return urls

    def _parse_chapter_heading(self, html: str) -> Dict[str, str]:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return {"agency_name": "", "chapter_number": "", "chapter_title": ""}

        h1 = _norm_space(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
        h2 = _norm_space(soup.find("h2").get_text(" ", strip=True) if soup.find("h2") else "")
        chapter_num = ""
        m = re.search(r"chapter\s+([0-9]+)", h2, flags=re.IGNORECASE)
        if m:
            chapter_num = m.group(1)

        return {
            "agency_name": h1,
            "chapter_number": chapter_num,
            "chapter_title": h2,
        }

    def _parse_division_urls(self, chapter_url: str, chapter_html: str) -> List[str]:
        urls: List[str] = []
        try:
            soup = BeautifulSoup(chapter_html, "html.parser")
        except Exception:
            return []

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if "displayDivisionRules.action" not in href:
                continue
            absolute = urljoin(chapter_url, href)
            urls.append(self._normalize_oard_url(absolute))

        if not urls:
            for match in _DIVISION_URL_RE.findall(chapter_html or ""):
                urls.append(self._normalize_oard_url(urljoin(chapter_url, match)))

        return _dedupe_keep_order(urls)

    def _extract_rule_title(self, rule_div: "BeautifulSoup", rule_number: str) -> str:
        strong_nodes = rule_div.find_all("strong")
        for node in strong_nodes:
            text = _norm_space(node.get_text(" ", strip=True))
            if not text:
                continue
            if text == rule_number:
                continue
            if re.fullmatch(r"[0-9\-]+", text):
                continue
            return text
        return f"OAR {rule_number}"

    def _extract_rule_body_and_meta(self, lines: Sequence[str], rule_title: str) -> Dict[str, Any]:
        authority = ""
        implemented = ""
        history_lines: List[str] = []
        body_lines: List[str] = []
        in_history = False

        for raw_line in lines:
            line = _norm_space(raw_line)
            if not line:
                continue

            if line.lower().startswith("statutory/other authority:"):
                authority = _norm_space(line.split(":", 1)[1] if ":" in line else "")
                in_history = False
                continue
            if line.lower().startswith("statutes/other implemented:"):
                implemented = _norm_space(line.split(":", 1)[1] if ":" in line else "")
                in_history = False
                continue
            if line.lower().startswith("history:"):
                suffix = _norm_space(line.split(":", 1)[1] if ":" in line else "")
                if suffix:
                    history_lines.append(suffix)
                in_history = True
                continue

            if in_history:
                history_lines.append(line)
                continue

            if line == rule_title:
                continue
            body_lines.append(line)

        body_text = _norm_space("\n".join(body_lines))
        return {
            "body_text": body_text,
            "authority": authority,
            "implemented": implemented,
            "history_lines": _dedupe_keep_order(history_lines),
        }

    def _build_rule_statute(
        self,
        *,
        code_name: str,
        legal_area: str,
        chapter_meta: Dict[str, str],
        division_url: str,
        rule_div: "BeautifulSoup",
    ) -> Optional[NormalizedStatute]:
        anchor = rule_div.find("a", href=True)
        if not anchor:
            return None

        rule_number = _norm_space(anchor.get_text(" ", strip=True))
        if not _OAR_RULE_RE.search(rule_number):
            return None

        rule_url = self._normalize_oard_url(urljoin(division_url, str(anchor.get("href") or "")))
        rule_title = self._extract_rule_title(rule_div, rule_number)

        rule_text = _norm_space(rule_div.get_text("\n", strip=True))
        lines = [line for line in rule_text.splitlines() if _norm_space(line)]
        if lines and lines[0] == rule_number:
            lines = lines[1:]

        extracted = self._extract_rule_body_and_meta(lines, rule_title)
        body_text = extracted["body_text"]
        if not body_text:
            return None

        citations = self.parent._extract_citations_from_text(
            rule_text,
            body_text,
            extra_patterns={
                "oar_citations": _OAR_RULE_RE,
                "ors_citations": _ORS_CITATION_RE,
            },
        )
        preamble = self.parent._extract_preamble(body_text, max_chars=600)
        subsections = self.parent._parse_subsections(body_text)
        parser_warnings = self.parent._validate_subsection_tree(subsections)

        metadata = StatuteMetadata(history=extracted["history_lines"])
        structured_data: Dict[str, Any] = {
            "citations": citations,
            "preamble": preamble,
            "subsections": subsections,
            "parser_warnings": parser_warnings,
            "authority": extracted["authority"],
            "implemented": extracted["implemented"],
            "history_lines": extracted["history_lines"],
            "chapter": chapter_meta,
            "rule_url": rule_url,
        }

        statute = NormalizedStatute(
            state_code=self.parent.state_code,
            state_name=self.parent.state_name,
            statute_id=f"OAR {rule_number}",
            code_name=code_name,
            title_number=chapter_meta.get("chapter_number") or None,
            title_name=chapter_meta.get("agency_name") or chapter_meta.get("chapter_title") or None,
            chapter_number=chapter_meta.get("chapter_number") or None,
            chapter_name=chapter_meta.get("agency_name") or None,
            section_number=rule_number,
            section_name=rule_title,
            short_title=rule_title,
            full_text=body_text,
            summary=preamble,
            legal_area=legal_area,
            keywords=_dedupe_keep_order(
                [
                    *(citations.get("oar_citations") or []),
                    *(citations.get("ors_citations") or []),
                    extracted["authority"],
                    extracted["implemented"],
                ]
            )[:200],
            source_url=rule_url,
            official_cite=f"OAR {rule_number}",
            metadata=metadata,
            structured_data=structured_data,
        )
        statute.structured_data["jsonld"] = self.parent._build_state_jsonld(
            statute,
            text=body_text,
            preamble=preamble,
            citations=citations,
            legislative_history={"history_lines": extracted["history_lines"]},
            subsections=subsections,
            parser_warnings=parser_warnings,
        )
        return statute

    async def scrape(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        legal_area = "administrative"
        chapter_urls = await self.discover_chapter_urls()
        if not chapter_urls:
            chapter_urls = [code_url]

        statutes: List[NormalizedStatute] = []
        max_rules_raw = os.getenv("OREGON_OAR_MAX_RULES", "").strip()
        max_rules = 0
        if max_rules_raw:
            try:
                max_rules = max(1, int(max_rules_raw))
            except Exception:
                max_rules = 0

        for chapter_url in chapter_urls:
            chapter_bytes = await self.parent._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=90)
            if not chapter_bytes:
                continue

            chapter_html = chapter_bytes.decode("utf-8", errors="replace")
            chapter_meta = self._parse_chapter_heading(chapter_html)
            division_urls = self._parse_division_urls(chapter_url, chapter_html)
            if not division_urls:
                continue

            for division_url in division_urls:
                division_bytes = await self.parent._fetch_page_content_with_archival_fallback(division_url, timeout_seconds=90)
                if not division_bytes:
                    continue

                try:
                    division_html = division_bytes.decode("utf-8", errors="replace")
                    soup = BeautifulSoup(division_html, "html.parser")
                except Exception:
                    continue

                for rule_div in soup.find_all("div", class_="rule_div"):
                    statute = self._build_rule_statute(
                        code_name=code_name,
                        legal_area=legal_area,
                        chapter_meta=chapter_meta,
                        division_url=division_url,
                        rule_div=rule_div,
                    )
                    if statute is None:
                        continue
                    statutes.append(statute)

                    if max_rules > 0 and len(statutes) >= max_rules:
                        return statutes

        # Deduplicate by citation while preserving best (longest text) entry.
        by_id: Dict[str, NormalizedStatute] = {}
        for statute in statutes:
            key = str(statute.section_number or statute.statute_id)
            prev = by_id.get(key)
            if prev is None or len(str(statute.full_text or "")) > len(str(prev.full_text or "")):
                by_id[key] = statute

        ordered = sorted(by_id.values(), key=lambda row: str(row.section_number or row.statute_id))
        return ordered


__all__ = ["OregonAdministrativeRulesScraper"]
