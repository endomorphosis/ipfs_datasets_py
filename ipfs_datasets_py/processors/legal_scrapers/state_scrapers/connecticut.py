"""Scraper for Connecticut state laws.

This module contains the scraper for Connecticut statutes from the official state legislative website.
"""

import hashlib
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup, Tag
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class ConnecticutScraper(BaseStateScraper):
    """Scraper for Connecticut state laws from https://www.cga.ct.gov"""

    _CHAPTER_LINK_RE = re.compile(r"chap_[0-9a-z]+\.htm$", re.IGNORECASE)
    _TITLE_LINK_RE = re.compile(r"title_[0-9a-z]+\.htm$", re.IGNORECASE)
    _TITLE_NUMBER_RE = re.compile(r"title[_-]?([0-9a-z]+)\.htm$", re.IGNORECASE)
    OFFICIAL_DOMAIN = "www.cga.ct.gov"
    OFFICIAL_ENTRY_PATH = "/current/pub/titles.htm"
    OFFICIAL_ENTRY_URL = "https://www.cga.ct.gov/current/pub/titles.htm"
    # Ordered logical title units in the official ``titles.htm`` frontier.
    # Lettered titles are distinct units; Titles 2a and 2b are explicit
    # linkless reserved rows.  This baseline is used only to verify a freshly
    # parsed official index and is never projected into synthetic catalog
    # rows when the index is unavailable.
    OFFICIAL_TITLE_NUMBERS = (
        "1", "2", "2a", "2b", "2c", "3", "4", "4a", "4b", "4c", "4d", "4e",
        "5", "6", "7", "8", "9", "10", "10a", "11", "12", "13", "13a",
        "13b", "14", "15", "16", "16a", "17", "17a", "17b", "18", "19",
        "19a", "20", "21", "21a", "22", "22a", "23", "24", "25", "26",
        "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "36a",
        "36b", "37", "38", "38a", "39", "40", "41", "42", "42a", "42b",
        "43", "44", "45", "45a", "46", "46a", "46b", "47", "47a", "48",
        "49", "50", "50a", "51", "52", "53", "53a", "54", "55",
    )
    OFFICIAL_RESERVED_TITLE_NUMBERS = ("2a", "2b")
    OFFICIAL_INACTIVE_TITLE_NUMBERS = (
        "4c", "13", "17", "19", "36", "38", "39", "45", "46",
    )
    OFFICIAL_SUPPLEMENT_ENTRY_PATH = "/2026/sup/titles.htm"
    OFFICIAL_SUPPLEMENT_ENTRY_URL = (
        "https://www.cga.ct.gov/2026/sup/titles.htm"
    )
    OFFICIAL_BASE_REVISION_DATE = "January 1, 2025"
    OFFICIAL_SUPPLEMENT_REVISION_DATE = "January 1, 2026"
    OFFICIAL_CURRENT_AS_OF = "2026-01-01"
    OFFICIAL_SUPPLEMENT_TITLE_NUMBERS = (
        "1", "2", "3", "4", "4a", "4b", "4d", "4e", "5", "6", "7",
        "8", "9", "10", "10a", "11", "12", "13a", "13b", "14", "15",
        "16", "16a", "17a", "17b", "18", "19a", "20", "21", "21a",
        "22", "22a", "23", "25", "26", "27", "28", "29", "30", "31",
        "32", "34", "36a", "36b", "38a", "42", "42a", "45a", "46a",
        "46b", "47", "47a", "48", "49", "51", "52", "53", "53a",
        "54",
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLE_NUMBERS)
    # The 2026 supplement publishes these four repeals as grouped frontier
    # units, while the closed 2025 base publishes each affected section as an
    # individual unit.  Expansion is deliberately limited to the exact
    # retained official page URL and body digest; this is evidence
    # reconciliation, not a generic legal-citation range parser.
    _OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        "10-511_and_10-511a": {
            "chapter_url": "https://www.cga.ct.gov/2026/sup/chap_184c.htm",
            "content_sha256": (
                "6f8f882153cdcaa1c2d10cec5bcc0b87f40759269924e6c6df991ebf39c7d6f1"
            ),
            "base_chapter_url": (
                "https://www.cga.ct.gov/current/pub/chap_184c.htm"
            ),
            "sections": ("10-511", "10-511a"),
        },
        "20-341s_to_20-341bb": {
            "chapter_url": "https://www.cga.ct.gov/2026/sup/chap_393b.htm",
            "content_sha256": (
                "5815bf39f5060586b272bfabcafaf5d4312c797a7f26aa7cdc81480d269332a5"
            ),
            "base_chapter_url": (
                "https://www.cga.ct.gov/current/pub/chap_393b.htm"
            ),
            "sections": (
                "20-341s",
                "20-341t",
                "20-341u",
                "20-341v",
                "20-341w",
                "20-341x",
                "20-341y",
                "20-341z",
                "20-341aa",
                "20-341bb",
            ),
        },
        "22a-27s_and_22a-27t": {
            "chapter_url": "https://www.cga.ct.gov/2026/sup/chap_439.htm",
            "content_sha256": (
                "2c23bded0f4099f354d177e3feb54023dcccade2e2c24cf229c9d5cd0f28175b"
            ),
            "base_chapter_url": "https://www.cga.ct.gov/current/pub/chap_439.htm",
            "sections": ("22a-27s", "22a-27t"),
        },
        "22a-449c_to_22a-449g": {
            "chapter_url": "https://www.cga.ct.gov/2026/sup/chap_446k.htm",
            "content_sha256": (
                "e47d22982b46173caec8fe43d2dcc426bdc2ee22fa24dec734348b054b60a34e"
            ),
            "base_chapter_url": (
                "https://www.cga.ct.gov/current/pub/chap_446k.htm"
            ),
            "sections": (
                "22a-449c",
                "22a-449d",
                "22a-449e",
                "22a-449f",
                "22a-449g",
            ),
        },
    }
    
    def get_base_url(self) -> str:
        """Return the base URL for Connecticut's legislative website."""
        return "https://www.cga.ct.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Connecticut."""
        return [{
            "name": "Connecticut General Statutes",
            # Prefer the live endpoint; the shared archival fetch client now
            # falls back to insecure TLS when certificate chains fail.
            "url": "https://www.cga.ct.gov/current/pub/titles.htm",
            "type": "Code"
        }]
    
    def _justia_fallback_allowed(self) -> bool:
        return str(
            os.getenv("STATE_SCRAPER_CT_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _is_justia_url(self, url: str) -> bool:
        return "justia.com" in str(url or "").lower()

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled() or self._justia_fallback_allowed():
            return statutes
        return [
            s
            for s in statutes
            if not self._is_justia_url(str(s.source_url or ""))
            and "justia" not in str((s.structured_data or {}).get("source_kind") or "").lower()
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Connecticut's legislative website.

        Full-corpus mode with ``max_statutes=None`` remains uncapped. Secondary
        Justia mirrors are never sole full-corpus admission unless explicitly
        re-enabled via ``STATE_SCRAPER_CT_ALLOW_JUSTIA_FALLBACK``.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        self._connecticut_strict_full_run = bool(
            self._full_corpus_enabled() and limit is None
        )
        # Strict base and supplement catalogs are a single known same-domain
        # frontier.  The first strict catalog traversal fills this cache via
        # one plural acquisition and both traversals consume the retained rows.
        self._connecticut_catalog_root_records: Dict[str, Dict[str, Any]] = {}
        self._last_connecticut_full_frontier = {
            "closed": False,
            "catalog_units_discovered": 0,
            "active_title_units": 0,
            "inactive_title_units": 0,
            "reserved_title_units": [],
            "title_pages_requested": 0,
            "title_pages_fetched": 0,
            "title_pages_excluded": 0,
            "title_pages_failed": [],
            "chapter_pages_discovered": 0,
            "chapter_pages_requested": 0,
            "chapter_pages_fetched": 0,
            "chapter_pages_excluded": 0,
            "chapter_pages_failed": [],
            "active_sections_discovered": 0,
            "inactive_sections_excluded": 0,
            "sections_emitted": 0,
            "base_revision_date": self.OFFICIAL_BASE_REVISION_DATE,
            "base_frontier_closed": False,
            "supplement_catalog_units_discovered": 0,
            "supplement_title_pages_requested": 0,
            "supplement_title_pages_fetched": 0,
            "supplement_chapter_pages_discovered": 0,
            "supplement_chapter_pages_requested": 0,
            "supplement_chapter_pages_fetched": 0,
            "supplement_active_sections_discovered": 0,
            "supplement_tombstones_discovered": 0,
            "supplement_sections_emitted": 0,
            "supplement_revision_date": self.OFFICIAL_SUPPLEMENT_REVISION_DATE,
            "supplement_frontier_closed": False,
            "current_as_of": None,
            "currentness_closed": False,
            "failures": [],
        }
        self._last_full_corpus_frontier = self._last_connecticut_full_frontier
        return_threshold = limit if limit is not None else 1000000
        allow_justia = self._justia_fallback_allowed()

        from .connecticut_constitution import (
            configured_constitution_html_path,
            parse_connecticut_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_connecticut_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Connecticut Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .connecticut_chapter import configured_chapter_html_path, parse_connecticut_chapter_html

        local_chapter = configured_chapter_html_path()
        if local_chapter is not None:
            local_rows = parse_connecticut_chapter_html(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                chapter_url="https://www.cga.ct.gov/current/pub/chap_952.htm",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return local_rows if limit is None else local_rows[: int(limit)]

        if self._connecticut_strict_full_run:
            base_rows = await self._custom_scrape_connecticut(
                code_name,
                self.OFFICIAL_ENTRY_URL,
                "Conn. Gen. Stat.",
                max_sections=return_threshold,
                _catalog_kind="base",
            )
            supplement_rows = await self._custom_scrape_connecticut(
                code_name,
                self.OFFICIAL_SUPPLEMENT_ENTRY_URL,
                "Conn. Gen. Stat.",
                max_sections=return_threshold,
                _catalog_kind="supplement",
            )
            return self._overlay_connecticut_supplement(
                base_rows,
                supplement_rows,
                tombstones=list(
                    getattr(self, "_last_connecticut_supplement_tombstones", [])
                    or []
                ),
            )

        # Prefer official CGA title/chapter HTML tree first.
        official_candidates = [
            code_url,
            "https://www.cga.ct.gov/current/pub/titles.htm",
        ]
        best: List[NormalizedStatute] = []
        seen = set()
        for candidate in official_candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if self._is_justia_url(candidate) and not allow_justia:
                continue

            statutes = self._filter_official_only(
                await self._custom_scrape_connecticut(
                    code_name,
                    candidate,
                    "Conn. Gen. Stat.",
                    max_sections=return_threshold,
                )
            )
            if len(statutes) > len(best):
                best = statutes
            if limit is not None and len(statutes) >= int(limit):
                return statutes[: int(limit)]
            if limit is None and statutes:
                return statutes

        # Bounded probes may use direct chapter seeds.
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_budget = limit if limit is not None else max(1, int(return_threshold))
            direct_sections = await self._scrape_direct_chapters(
                code_name,
                max_statutes=max(1, int(direct_budget)),
            )
            if direct_sections and len(direct_sections) > len(best):
                best = direct_sections
            if limit is not None and len(best) >= int(limit):
                return best[: int(limit)]

        # Secondary Justia mirrors are never sole full-corpus admission unless
        # explicitly re-enabled; bounded probes may still use them as last resort.
        secondary_urls: List[str] = []
        if allow_justia or (not self._full_corpus_enabled()):
            secondary_urls = [
                "https://law.justia.com/codes/connecticut/",
                "http://web.archive.org/web/20250101000000/https://law.justia.com/codes/connecticut/",
            ]

        for candidate in secondary_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if self._full_corpus_enabled() and not allow_justia:
                continue

            statutes = await self._custom_scrape_connecticut(
                code_name,
                candidate,
                "Conn. Gen. Stat.",
                max_sections=return_threshold if limit is not None else 260,
            )
            statutes = self._filter_official_only(statutes) if self._full_corpus_enabled() else statutes
            if len(statutes) > len(best):
                best = statutes
            if limit is not None and len(statutes) >= int(limit):
                return statutes[: int(limit)]

            generic = await self._generic_scrape(
                code_name,
                candidate,
                "Conn. Gen. Stat.",
                max_sections=return_threshold if limit is not None else 260,
            )
            generic = self._filter_official_only(generic) if self._full_corpus_enabled() else generic
            if len(generic) > len(best):
                best = generic
            if limit is not None and len(generic) >= int(limit):
                return generic[: int(limit)]

        # Full corpus: refuse Justia-only admission.
        if self._full_corpus_enabled() and not allow_justia:
            best = self._filter_official_only(best)
            if not best:
                return []

        if not best and (not self._full_corpus_enabled() or max_statutes is not None):
            live_stubs = await self._scrape_live_title_stubs(
                code_name,
                max_statutes=max(10, int(return_threshold) if limit is not None else 120),
            )
            if len(live_stubs) > len(best):
                best = live_stubs
            archival_stubs = await self._scrape_archived_chapter_stubs(
                code_name,
                max_statutes=max(10, int(return_threshold) if limit is not None else 120),
            )
            if len(archival_stubs) > len(best):
                best = archival_stubs

        return best if limit is None else best[: int(limit)]

    async def _scrape_direct_chapters(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        """Fetch official CGA chapter pages directly, tolerating their TLS chain."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        chapter_urls = [
            "https://www.cga.ct.gov/current/pub/chap_001.htm",
            "https://www.cga.ct.gov/current/pub/chap_002.htm",
        ]
        out: List[NormalizedStatute] = []
        for source_url in chapter_urls[: max(1, int(max_statutes or 1))]:
            try:
                payload = await self._fetch_parser_input_with_transport(
                    source_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout_seconds=12,
                    allow_archival_fallback=True,
                    verify_tls=False,
                    media_type="text/html",
                    provider="connecticut_direct_chapter",
                )
            except Exception:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 280:
                continue
            title = text.split(" Table of Contents", 1)[0][:200] or "Connecticut General Statutes"
            chapter_match = re.search(r"\bChapter\s+([0-9A-Za-z]+)\b", text, re.IGNORECASE)
            chapter = chapter_match.group(1) if chapter_match else str(len(out) + 1)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Chapter {chapter}",
                    code_name=code_name,
                    section_number=f"Chapter {chapter}",
                    section_name=title,
                    full_text=text,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Conn. Gen. Stat. ch. {chapter}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_connecticut_direct_chapter",
                        "discovery_method": "official_seed_chapter",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []

        url = "https://www.cga.ct.gov/current/pub/titles.htm"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            if not href or not text:
                continue
            if "chap" not in href.lower() and "title" not in text.lower() and "chapter" not in text.lower():
                continue
            full_url = urljoin(url, href)
            section_number = self._extract_section_number(text) or str(len(out) + 1)
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)

            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=text[:200],
                    full_text=f"Connecticut General Statutes {text}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(text),
                    official_cite=f"Conn. Gen. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                )
            )
        return out

    async def _scrape_archived_chapter_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.cga.ct.gov/current/pub/*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 6)}"
        )
        rows = await self._fetch_wayback_cdx_rows(
            cdx_url,
            timeout_seconds=45,
        )

        if not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue

            m = re.search(r"/(?:chap|chapter)([0-9A-Za-z]+)\.(?:htm|html)$", original, flags=re.IGNORECASE)
            chapter = m.group(1) if m else ""
            if not chapter:
                continue
            key = chapter.lower()
            if key in seen:
                continue
            seen.add(key)

            encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            title = f"Chapter {chapter}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter}",
                    code_name=code_name,
                    section_number=chapter,
                    section_name=title,
                    full_text=f"Connecticut General Statutes {title}: {source_url}",
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Conn. Gen. Stat. ch. {chapter}",
                    metadata=StatuteMetadata(),
                )
            )

        return out
    
    async def _custom_scrape_connecticut(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100,
        *,
        _catalog_kind: str = "base",
    ) -> List[NormalizedStatute]:
        """Custom scraper for Connecticut's legislative website.
        
        Connecticut organizes statutes by titles with chapters underneath.
        """
        if _catalog_kind not in {"base", "supplement"}:
            raise ValueError("Connecticut catalog kind must be base or supplement")
        is_supplement = _catalog_kind == "supplement"
        strict_full = bool(getattr(self, "_connecticut_strict_full_run", False))
        try:
            chapter_urls = await self._discover_chapter_urls(
                code_url,
                limit=max(max_sections * 3, 20),
                catalog_kind=_catalog_kind,
            )
            statutes: List[NormalizedStatute] = []
            seen_sections: Dict[str, str] = {}
            tombstones: Dict[str, Dict[str, Any]] = {}
            if is_supplement:
                self._last_connecticut_supplement_tombstones = []
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label=f"connecticut:{_catalog_kind}:chapter-discovery",
                extra={
                    "chapters_scanned": 0,
                    "discovered_chapters": int(len(chapter_urls)),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )
            if chapter_urls:
                self.logger.info(
                    "Connecticut chapter crawl: discovered_chapters=%s",
                    len(chapter_urls),
                )
            chapter_records = await self._fetch_connecticut_frontier_pages(
                chapter_urls,
                purpose=("supplement_chapters" if is_supplement else "chapters"),
                timeout_seconds=35,
            )
            failed_chapters: List[str] = []
            excluded_chapters = 0
            active_sections_discovered = 0
            inactive_sections_excluded = 0
            for chapter_index, record in enumerate(chapter_records, start=1):
                if not strict_full and len(statutes) >= max_sections:
                    break
                chapter_url = str(record.get("url") or "")
                payload = bytes(record.get("payload") or b"")
                if not payload:
                    failed_chapters.append(chapter_url)
                    continue
                try:
                    provenance = self._connecticut_record_provenance(
                        record,
                        required=strict_full,
                    )
                except RuntimeError:
                    failed_chapters.append(chapter_url)
                    if strict_full:
                        raise
                    continue
                chapter_statutes = self._parse_connecticut_chapter_payload(
                    payload,
                    code_name=code_name,
                    chapter_url=chapter_url,
                    citation_format=citation_format,
                    provenance=provenance,
                )
                parity = dict(
                    getattr(self, "_last_connecticut_chapter_parity", {}) or {}
                )
                active_sections_discovered += int(
                    parity.get("active_section_count") or 0
                )
                inactive_sections_excluded += int(
                    parity.get("inactive_section_count") or 0
                )
                if int(parity.get("active_section_count") or 0) == 0:
                    excluded_chapters += 1
                if is_supplement:
                    for section_number in parity.get("inactive_sections") or []:
                        identity = str(section_number or "").strip().casefold()
                        if not identity:
                            continue
                        if identity in tombstones and strict_full:
                            raise RuntimeError(
                                "connecticut supplement emitted a duplicate tombstone: "
                                f"section={identity} first={tombstones[identity]['chapter_url']} "
                                f"second={chapter_url}"
                            )
                        tombstones[identity] = {
                            "section_number": identity,
                            "chapter_url": chapter_url,
                            **dict(provenance or {}),
                        }
                for statute in chapter_statutes:
                    section_number = str(statute.section_number or "").strip().lower()
                    if not section_number:
                        continue
                    if section_number in seen_sections:
                        if strict_full:
                            raise RuntimeError(
                                "connecticut official chapter frontier emitted a duplicate "
                                f"section: section={section_number} first={seen_sections[section_number]} "
                                f"second={chapter_url}"
                            )
                        continue
                    seen_sections[section_number] = chapter_url
                    data = dict(statute.structured_data or {})
                    data["connecticut_catalog_kind"] = _catalog_kind
                    statute.structured_data = data
                    statutes.append(statute)
                    if not strict_full and len(statutes) >= max_sections:
                        break
                if chapter_index == 1 or chapter_index % 5 == 0:
                    self.logger.info(
                        "Connecticut chapter crawl: chapter=%s/%s statutes_so_far=%s",
                        chapter_index,
                        len(chapter_urls),
                        len(statutes),
                    )
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label=f"connecticut:{_catalog_kind}:chapter-scan",
                        extra={
                            "chapters_scanned": int(chapter_index),
                            "discovered_chapters": int(len(chapter_urls)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )

            frontier = dict(
                getattr(self, "_last_connecticut_full_frontier", {}) or {}
            )
            if is_supplement:
                frontier.update(
                    {
                        "supplement_chapter_pages_discovered": len(chapter_urls),
                        "supplement_chapter_pages_requested": len(chapter_urls),
                        "supplement_chapter_pages_fetched": sum(
                            bool(record.get("payload")) for record in chapter_records
                        ),
                        "supplement_chapter_pages_excluded": excluded_chapters,
                        "supplement_chapter_pages_failed": failed_chapters,
                        "supplement_active_sections_discovered": active_sections_discovered,
                        "supplement_tombstones_discovered": len(tombstones),
                        "supplement_sections_emitted": len(statutes),
                    }
                )
                self._last_connecticut_supplement_tombstones = list(
                    tombstones.values()
                )
            else:
                frontier.update({
                    "chapter_pages_discovered": len(chapter_urls),
                    "chapter_pages_requested": len(chapter_urls),
                    "chapter_pages_fetched": sum(
                        bool(record.get("payload")) for record in chapter_records
                    ),
                    "chapter_pages_excluded": excluded_chapters,
                    "chapter_pages_failed": failed_chapters,
                    "active_sections_discovered": active_sections_discovered,
                    "inactive_sections_excluded": inactive_sections_excluded,
                    "sections_emitted": len(statutes),
                })
            self._last_connecticut_full_frontier = frontier
            self._last_full_corpus_frontier = frontier

            if strict_full:
                failures: List[str] = []
                if len(chapter_records) != len(chapter_urls):
                    failures.append("chapter_batch_alignment")
                if failed_chapters:
                    failures.append("chapter_pages_failed")
                if active_sections_discovered != len(statutes):
                    failures.append("section_frontier_parser_parity")
                overlap = sorted(set(seen_sections) & set(tombstones))
                if overlap:
                    failures.append("supplement_active_tombstone_overlap")
                if not statutes and not tombstones:
                    failures.append("empty_official_corpus")
                if is_supplement:
                    frontier["supplement_frontier_closed"] = not failures
                else:
                    frontier["base_frontier_closed"] = not failures
                frontier["closed"] = False
                frontier["currentness_closed"] = False
                frontier["failures"] = list(frontier.get("failures") or []) + [
                    f"{_catalog_kind}:{failure}" for failure in failures
                ]
                self._last_connecticut_full_frontier = frontier
                self._last_full_corpus_frontier = frontier
                if failures:
                    raise RuntimeError(
                        "connecticut official full-corpus frontier did not close: "
                        f"failures={failures} failed_chapters={failed_chapters} "
                        f"active={active_sections_discovered} emitted={len(statutes)}"
                    )
                for statute in statutes:
                    data = dict(statute.structured_data or {})
                    data.update(
                        {
                            f"official_{_catalog_kind}_frontier_closed": True,
                            "official_catalog_units_discovered": int(
                                frontier.get(
                                    "supplement_catalog_units_discovered"
                                    if is_supplement
                                    else "catalog_units_discovered"
                                )
                                or 0
                            ),
                            "official_chapter_pages_fetched": int(
                                frontier.get(
                                    "supplement_chapter_pages_fetched"
                                    if is_supplement
                                    else "chapter_pages_fetched"
                                )
                                or 0
                            ),
                        }
                    )
                    statute.structured_data = data

            self.logger.info(f"Connecticut custom scraper: Scraped {len(statutes)} sections")
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label=f"connecticut:{_catalog_kind}:complete",
                force=True,
                extra={
                    "chapters_scanned": int(len(chapter_urls)),
                    "discovered_chapters": int(len(chapter_urls)),
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
            
            # Fallback to generic scraper if no data found
            if not statutes:
                if strict_full and not (is_supplement and tombstones):
                    raise RuntimeError(
                        "connecticut strict official traversal emitted no statutes"
                    )
                if strict_full:
                    return []
                self.logger.info("Connecticut custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Connecticut custom scraper failed: {e}")
            frontier = dict(
                getattr(self, "_last_connecticut_full_frontier", {}) or {}
            )
            failures = list(frontier.get("failures") or [])
            detail = f"{type(e).__name__}: {e}"
            if detail not in failures:
                failures.append(detail)
            frontier.update({"closed": False, "failures": failures})
            self._last_connecticut_full_frontier = frontier
            self._last_full_corpus_frontier = frontier
            if strict_full:
                raise
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes

    async def _fetch_connecticut_frontier_pages(
        self,
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int = 35,
    ) -> List[Dict[str, Any]]:
        """Fetch a Connecticut page frontier through shared WARC-aware batches."""

        requested = list(dict.fromkeys(str(url or "").strip() for url in urls if url))
        if not requested:
            return []
        try:
            configured_chunk_size = int(
                os.getenv("STATE_SCRAPER_CT_BATCH_SIZE", "128") or "128"
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "STATE_SCRAPER_CT_BATCH_SIZE must be an integer"
            ) from exc
        chunk_size = max(
            1,
            min(
                256,
                configured_chunk_size,
            ),
        )
        if purpose == "catalog_roots":
            # These two required roots are known before either hierarchy is
            # parsed.  Never allow a legacy chunk-size override to split them
            # back into per-root archive discovery requests.
            chunk_size = len(requested)
        records: List[Dict[str, Any]] = []
        batch_stats: List[Dict[str, Any]] = []
        for offset in range(0, len(requested), chunk_size):
            chunk = requested[offset : offset + chunk_size]
            batch = await self._fetch_page_contents_with_archival_fallback(
                chunk,
                timeout_seconds=timeout_seconds,
                media_type="text/html",
                max_concurrency=min(12, len(chunk)),
                prefer_direct=True,
                common_crawl_domain_terms=[self.OFFICIAL_DOMAIN],
                common_crawl_mime_terms=["html"],
            )
            aligned_lengths = {
                len(batch.urls),
                len(batch.payloads),
                len(batch.errors),
                len(batch.transport_receipts),
                len(batch.parser_input_envelopes),
            }
            if aligned_lengths != {len(chunk)}:
                raise RuntimeError(
                    "connecticut archival batch returned unaligned acquisition rows"
                )
            expected_chunk = [self._canonical_fetch_url(url) for url in chunk]
            if list(batch.urls) != expected_chunk:
                raise RuntimeError(
                    "connecticut archival batch changed URL order or identity"
                )
            batch_stats.append(dict(batch.stats or {}))
            for url, payload, error, receipt in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                batch.transport_receipts,
                strict=True,
            ):
                transport_receipt = dict(receipt or {})
                records.append(
                    {
                        "url": url,
                        "payload": bytes(payload or b""),
                        "error": str(error or ""),
                        "transport_receipt": transport_receipt,
                        "content_sha256": str(
                            transport_receipt.get("content_sha256") or ""
                        ),
                    }
                )
        observed_urls = [str(record["url"]) for record in records]
        expected_urls = [self._canonical_fetch_url(url) for url in requested]
        if observed_urls != expected_urls:
            raise RuntimeError(
                "connecticut archival batch did not preserve the requested frontier order"
            )
        all_stats = dict(getattr(self, "_last_connecticut_batch_stats", {}) or {})
        all_stats[purpose] = {
            "batch_count": len(batch_stats),
            "failed_pages": sum(not record["payload"] for record in records),
            "fetched_pages": sum(bool(record["payload"]) for record in records),
            "requested_pages": len(requested),
            "shared_batch_stats": batch_stats,
        }
        self._last_connecticut_batch_stats = all_stats
        return records

    async def _connecticut_catalog_root_record(
        self,
        code_url: str,
    ) -> Dict[str, Any]:
        """Return one retained root from the strict base/supplement batch."""

        requested_roots = [
            self._canonical_fetch_url(self.OFFICIAL_ENTRY_URL),
            self._canonical_fetch_url(self.OFFICIAL_SUPPLEMENT_ENTRY_URL),
        ]
        requested_url = self._canonical_fetch_url(code_url)
        cached = dict(
            getattr(self, "_connecticut_catalog_root_records", {}) or {}
        )
        if not all(url in cached for url in requested_roots):
            records = await self._fetch_connecticut_frontier_pages(
                requested_roots,
                purpose="catalog_roots",
                timeout_seconds=35,
            )
            if len(records) != len(requested_roots):
                raise RuntimeError(
                    "connecticut strict catalog-root frontier returned "
                    "unaligned acquisition rows"
                )
            observed_urls = [
                self._canonical_fetch_url(str(record.get("url") or ""))
                for record in records
            ]
            if observed_urls != requested_roots:
                raise RuntimeError(
                    "connecticut strict catalog-root frontier changed URL "
                    "order or identity"
                )
            prefetched: Dict[str, Dict[str, Any]] = {}
            for expected_url, record in zip(
                requested_roots,
                records,
                strict=True,
            ):
                payload = bytes(record.get("payload") or b"")
                error = str(record.get("error") or "").strip()
                if error or not payload:
                    raise RuntimeError(
                        "connecticut strict catalog-root frontier is incomplete: "
                        f"{expected_url}: {error or 'empty parser input'}"
                    )
                self._connecticut_record_provenance(record, required=True)
                prefetched[expected_url] = dict(record)
            self._connecticut_catalog_root_records = prefetched
            cached = prefetched
        record = cached.get(requested_url)
        if record is None:
            raise RuntimeError(
                "connecticut strict traversal requested an unbatched catalog root: "
                f"{requested_url}"
            )
        return dict(record)

    def _connecticut_record_provenance(
        self,
        record: Mapping[str, Any],
        *,
        required: bool,
    ) -> Dict[str, Any]:
        """Verify and project the shared retained-response byte binding."""

        payload = bytes(record.get("payload") or b"")
        url = self._canonical_fetch_url(str(record.get("url") or ""))
        receipt_value = record.get("transport_receipt")
        receipt = dict(receipt_value) if isinstance(receipt_value, Mapping) else {}
        digest = str(
            record.get("content_sha256") or receipt.get("content_sha256") or ""
        ).strip().lower()
        receipt_url = self._canonical_fetch_url(
            str(receipt.get("official_url") or "")
        )
        observed_digest = hashlib.sha256(payload).hexdigest() if payload else ""
        valid = bool(
            payload
            and re.fullmatch(r"[a-f0-9]{64}", digest)
            and digest == observed_digest
            and receipt_url == url
            and str(receipt.get("source_transport") or "").strip()
        )
        if not valid:
            if required:
                raise RuntimeError(
                    "connecticut retained parser input lacked an exact transport binding: "
                    f"url={url} digest={digest or '<missing>'}"
                )
            return {}
        receipt["content_sha256"] = digest
        receipt["official_url"] = url
        return {
            "content_sha256": digest,
            "transport_receipt": receipt,
        }

    async def _discover_chapter_urls(
        self,
        code_url: str,
        limit: int = 120,
        *,
        catalog_kind: str = "base",
    ) -> List[str]:
        if catalog_kind not in {"base", "supplement"}:
            raise ValueError("Connecticut catalog kind must be base or supplement")
        is_supplement = catalog_kind == "supplement"
        strict_full = bool(getattr(self, "_connecticut_strict_full_run", False))
        catalog_provenance: Dict[str, Any] = {}
        if strict_full:
            catalog_record = await self._connecticut_catalog_root_record(code_url)
            payload = bytes(catalog_record.get("payload") or b"")
            catalog_provenance = self._connecticut_record_provenance(
                catalog_record,
                required=True,
            )
        else:
            payload = await self._fetch_connecticut_page(
                code_url,
                timeout_seconds=35,
            )
        if not payload:
            return []

        seen: set[str] = set()
        out: List[str] = []
        html_text = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        from .connecticut_chapter import chapters_from_title

        catalog_rows = self.enumerate_official_title_catalog(
            payload,
            page_url=code_url,
        )
        if strict_full:
            if is_supplement:
                self._assert_connecticut_supplement_catalog_closed(
                    catalog_rows,
                    html_text=html_text,
                    page_url=code_url,
                )
                reserved: set[str] = set()
            else:
                reserved = self._assert_connecticut_title_catalog_closed(
                    catalog_rows
                )
                self._assert_connecticut_base_revision_gate(
                    html_text,
                    page_url=code_url,
                )
        else:
            reserved = {
                str(row.get("title_number") or "")
                for row in catalog_rows
                if row.get("unit_disposition") == "reserved"
            }
        inactive = {
            str(row.get("title_number") or "")
            for row in catalog_rows
            if row.get("unit_disposition") == "inactive"
        }
        active = {
            str(row.get("title_number") or "")
            for row in catalog_rows
            if row.get("unit_disposition") == "active"
        }
        title_urls = [
            str(row.get("source_url") or "")
            for row in catalog_rows
            if row.get("official_link_present") is True
        ]
        catalog_by_url = {
            str(row.get("source_url") or ""): row
            for row in catalog_rows
            if row.get("official_link_present") is True
        }
        frontier = dict(getattr(self, "_last_connecticut_full_frontier", {}) or {})
        if is_supplement:
            frontier.update(
                {
                    "supplement_catalog_units_discovered": len(catalog_rows),
                    "supplement_catalog_content_sha256": catalog_provenance.get(
                        "content_sha256"
                    ),
                    "supplement_active_title_units": len(active),
                    "supplement_title_pages_requested": len(title_urls),
                }
            )
        else:
            frontier.update({
                "catalog_units_discovered": len(catalog_rows),
                "base_catalog_content_sha256": catalog_provenance.get(
                    "content_sha256"
                ),
                "reserved_title_units": sorted(reserved),
                "inactive_title_units": len(inactive),
                "active_title_units": len(active),
                "title_units_excluded": len(reserved) + len(inactive),
                "title_pages_requested": len(title_urls),
                "title_pages_excluded": len(inactive),
            })
        self._last_connecticut_full_frontier = frontier

        for href, _number in chapters_from_title(html_text, base_url=code_url):
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
            if len(out) >= limit:
                return out
        title_records = await self._fetch_connecticut_frontier_pages(
            title_urls,
            purpose=("supplement_titles" if is_supplement else "titles"),
            timeout_seconds=35,
        )
        failed_titles: List[str] = []
        inactive_without_chapters: List[str] = []
        duplicate_chapter_urls: List[str] = []
        for record in title_records:
            title_url = str(record["url"])
            title_payload = bytes(record["payload"])
            if not title_payload:
                failed_titles.append(title_url)
                continue
            try:
                self._connecticut_record_provenance(
                    record,
                    required=strict_full,
                )
            except RuntimeError:
                failed_titles.append(title_url)
                if strict_full:
                    raise
                continue
            title_html = title_payload.decode("utf-8", errors="replace")
            chapters = chapters_from_title(title_html, base_url=title_url)
            catalog_row = catalog_by_url.get(title_url, {})
            if catalog_row.get("unit_disposition") == "inactive":
                inactive_without_chapters.append(
                    str(catalog_row.get("title_number") or title_url)
                )
                continue
            elif strict_full and not chapters:
                failed_titles.append(title_url)
                continue
            for chapter_url, _number in chapters:
                if chapter_url in seen:
                    duplicate_chapter_urls.append(chapter_url)
                    continue
                seen.add(chapter_url)
                out.append(chapter_url)
                if not strict_full and len(out) >= limit:
                    break
            if not strict_full and len(out) >= limit:
                break
        frontier = dict(getattr(self, "_last_connecticut_full_frontier", {}) or {})
        if is_supplement:
            frontier.update(
                {
                    "supplement_title_pages_fetched": sum(
                        bool(row["payload"]) for row in title_records
                    ),
                    "supplement_title_pages_failed": failed_titles,
                    "supplement_duplicate_chapter_urls": duplicate_chapter_urls,
                    "supplement_chapter_pages_discovered": len(out),
                }
            )
        else:
            frontier.update({
                "title_pages_fetched": sum(bool(row["payload"]) for row in title_records),
                "title_pages_failed": failed_titles,
                "duplicate_chapter_urls": duplicate_chapter_urls,
                "inactive_title_units_excluded": inactive_without_chapters,
                "chapter_pages_discovered": len(out),
            })
        self._last_connecticut_full_frontier = frontier
        if strict_full and (
            failed_titles
            or duplicate_chapter_urls
            or len(title_records) != len(title_urls)
        ):
            raise RuntimeError(
                "connecticut official title-page frontier did not close: "
                f"failed={failed_titles} duplicates={duplicate_chapter_urls} "
                f"requested={len(title_urls)} observed={len(title_records)}"
            )
        if strict_full and not out:
            raise RuntimeError("connecticut official title pages exposed no chapters")
        return out

    async def _extract_chapter_sections(
        self,
        code_name: str,
        chapter_url: str,
        citation_format: str,
    ) -> List[NormalizedStatute]:
        payload = await self._fetch_connecticut_page(chapter_url, timeout_seconds=35)
        if not payload:
            return []
        return self._parse_connecticut_chapter_payload(
            payload,
            code_name=code_name,
            chapter_url=chapter_url,
            citation_format=citation_format,
            provenance=self._last_parser_input_row_provenance(),
        )

    def _parse_connecticut_chapter_payload(
        self,
        payload: bytes,
        *,
        code_name: str,
        chapter_url: str,
        citation_format: str,
        provenance: Optional[Mapping[str, Any]] = None,
    ) -> List[NormalizedStatute]:
        """Parse one already retained official chapter response."""

        html_text = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload)
        )
        strict_full = bool(getattr(self, "_connecticut_strict_full_run", False))
        if strict_full:
            supplied = dict(provenance or {})
            provenance = self._connecticut_record_provenance(
                {
                    "url": chapter_url,
                    "payload": bytes(payload),
                    "content_sha256": supplied.get("content_sha256"),
                    "transport_receipt": supplied.get("transport_receipt"),
                },
                required=True,
            )
        soup = BeautifulSoup(payload, "html.parser")
        from .connecticut_chapter import parse_connecticut_chapter_html

        parsed = parse_connecticut_chapter_html(
            html_text,
            chapter_url=chapter_url,
            code_name=code_name,
        )
        if parsed:
            for row in parsed:
                row.official_cite = f"{citation_format} § {row.section_number}"
                data = dict(row.structured_data or {})
                data["discovery_method"] = "official_title_chapter_section_html"
                data.update(dict(provenance or {}))
                row.structured_data = data

        chapter_title = ""
        title_node = soup.find("title")
        if title_node:
            chapter_title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip()

        sections: List[NormalizedStatute] = list(parsed)
        for catchln in soup.select("span.catchln[id^='sec_']") if not parsed and not strict_full else []:
            section_number = self._extract_section_number(catchln.get_text(" ", strip=True))
            if not section_number:
                continue
            section_name = self._extract_connecticut_section_name(catchln.get_text(" ", strip=True), section_number)
            full_text = self._collect_connecticut_section_text(catchln)
            normalized = self._normalize_legal_text(full_text)
            if len(normalized) < 120:
                continue
            sections.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or chapter_title or f"Section {section_number}")[:240],
                    full_text=normalized,
                    legal_area=self._identify_legal_area(f"{chapter_title} {section_name}"),
                    source_url=f"{chapter_url}#sec_{section_number.lower()}",
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_connecticut_chapter_html",
                        "source_authority_class": "official",
                        "discovery_method": "official_title_chapter_section_html",
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                        **dict(provenance or {}),
                    },
                )
            )
        parity = self._connecticut_chapter_parity(
            html_text,
            sections,
            chapter_url=chapter_url,
        )
        self._last_connecticut_chapter_parity = parity
        if strict_full and int(parity["frontier_section_count"]) == 0:
            raise RuntimeError(
                "connecticut official chapter exposed no section frontier: "
                f"chapter_url={chapter_url}"
            )
        if strict_full and (
            parity["missing_sections"] or parity["unexpected_sections"]
        ):
            raise RuntimeError(
                "connecticut official chapter parser/frontier identity diverged: "
                f"chapter_url={chapter_url} "
                f"missing={parity['missing_sections']} "
                f"unexpected={parity['unexpected_sections']}"
            )
        return sections

    def _connecticut_chapter_parity(
        self,
        html_text: str,
        statutes: Sequence[NormalizedStatute],
        *,
        chapter_url: str = "",
    ) -> Dict[str, Any]:
        """Compare parser output with the exact frontier used by the parser."""

        from .connecticut_chapter import connecticut_section_frontier

        frontier = connecticut_section_frontier(
            html_text,
            chapter_url=chapter_url,
        )
        active = {
            str(row.get("section_number") or "").strip().casefold()
            for row in frontier
            if row.get("disposition") == "active"
            and str(row.get("section_number") or "").strip()
        }
        inactive = {
            str(row.get("section_number") or "").strip().casefold()
            for row in frontier
            if row.get("disposition") == "inactive"
            and str(row.get("section_number") or "").strip()
        }
        parsed = {
            str(row.section_number or "").strip().casefold()
            for row in statutes
            if str(row.section_number or "").strip()
        }
        return {
            "frontier_section_count": len(active) + len(inactive),
            "active_section_count": len(active),
            "active_sections": sorted(active),
            "inactive_section_count": len(inactive),
            "inactive_sections": sorted(inactive),
            "parsed_section_count": len(parsed),
            "parsed_sections": sorted(parsed),
            "missing_sections": sorted(active - parsed),
            "unexpected_sections": sorted(parsed - active),
        }

    def _overlay_connecticut_supplement(
        self,
        base_rows: Sequence[NormalizedStatute],
        supplement_rows: Sequence[NormalizedStatute],
        *,
        tombstones: Sequence[Mapping[str, Any]],
    ) -> List[NormalizedStatute]:
        """Overlay the dated official supplement on the dated base edition."""

        frontier = dict(
            getattr(self, "_last_connecticut_full_frontier", {}) or {}
        )
        if frontier.get("base_frontier_closed") is not True:
            raise RuntimeError("connecticut base frontier was not closed before overlay")
        if frontier.get("supplement_frontier_closed") is not True:
            raise RuntimeError(
                "connecticut supplement frontier was not closed before overlay"
            )

        def _identity(value: object) -> str:
            return str(value or "").strip().casefold()

        base_by_number: Dict[str, NormalizedStatute] = {}
        base_order: List[str] = []
        for row in base_rows:
            number = _identity(row.section_number)
            if not number or number in base_by_number:
                raise RuntimeError(
                    "connecticut base overlay input had a blank or duplicate section"
                )
            base_by_number[number] = row
            base_order.append(number)

        supplement_by_number: Dict[str, NormalizedStatute] = {}
        supplement_order: List[str] = []
        for row in supplement_rows:
            number = _identity(row.section_number)
            if not number or number in supplement_by_number:
                raise RuntimeError(
                    "connecticut supplement overlay input had a blank or duplicate section"
                )
            supplement_by_number[number] = row
            supplement_order.append(number)

        tombstone_by_number: Dict[str, Dict[str, Any]] = {}
        grouped_tombstone_notices_applied = 0
        grouped_tombstone_sections_applied = 0
        for value in tombstones:
            tombstone = dict(value)
            number = _identity(tombstone.get("section_number"))
            receipt = tombstone.get("transport_receipt")
            digest = str(tombstone.get("content_sha256") or "").strip().lower()
            if (
                not number
                or number in tombstone_by_number
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not isinstance(receipt, Mapping)
                or str(receipt.get("content_sha256") or "").strip().lower()
                != digest
            ):
                raise RuntimeError(
                    "connecticut supplement tombstone lacked unique retained provenance"
                )
            expansion = self._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS.get(
                number
            )
            if expansion is not None:
                chapter_url = str(tombstone.get("chapter_url") or "").strip()
                receipt_url = str(receipt.get("official_url") or "").strip()
                expected_chapter_url = str(expansion["chapter_url"])
                expected_digest = str(expansion["content_sha256"])
                if (
                    chapter_url != expected_chapter_url
                    or receipt_url != expected_chapter_url
                    or digest != expected_digest
                ):
                    raise RuntimeError(
                        "connecticut grouped supplement tombstone did not match "
                        "exact retained official evidence: "
                        f"section={number} chapter_url={chapter_url} "
                        f"content_sha256={digest}"
                    )
                concrete_sections = tuple(
                    _identity(section) for section in expansion["sections"]
                )
                missing = sorted(
                    section
                    for section in concrete_sections
                    if section not in base_by_number
                )
                expected_base_url = str(expansion["base_chapter_url"])
                wrong_base_sources = sorted(
                    section
                    for section in concrete_sections
                    if section in base_by_number
                    and str(base_by_number[section].source_url or "").split(
                        "#", 1
                    )[0]
                    != expected_base_url
                )
                if missing or wrong_base_sources:
                    raise RuntimeError(
                        "connecticut grouped supplement tombstone did not match "
                        "the exact closed base sections: "
                        f"section={number} missing={missing} "
                        f"wrong_base_sources={wrong_base_sources}"
                    )
                for section in concrete_sections:
                    if section in tombstone_by_number:
                        raise RuntimeError(
                            "connecticut supplement tombstone lacked unique "
                            "retained provenance"
                        )
                    expanded_tombstone = dict(tombstone)
                    expanded_tombstone.update(
                        {
                            "section_number": section,
                            "connecticut_group_tombstone": number,
                        }
                    )
                    tombstone_by_number[section] = expanded_tombstone
                grouped_tombstone_notices_applied += 1
                grouped_tombstone_sections_applied += len(concrete_sections)
                continue
            tombstone_by_number[number] = tombstone

        overlap = sorted(set(supplement_by_number) & set(tombstone_by_number))
        if overlap:
            raise RuntimeError(
                "connecticut supplement marked sections both active and inactive: "
                f"sections={overlap}"
            )
        unmatched_tombstones = sorted(set(tombstone_by_number) - set(base_by_number))
        if unmatched_tombstones:
            raise RuntimeError(
                "connecticut supplement tombstones did not match the closed base: "
                f"sections={unmatched_tombstones}"
            )

        merged: List[NormalizedStatute] = []
        replacements = 0
        additions = 0
        emitted_supplement: set[str] = set()
        for number in base_order:
            if number in tombstone_by_number:
                continue
            replacement = supplement_by_number.get(number)
            if replacement is None:
                row = base_by_number[number]
                data = dict(row.structured_data or {})
                data["connecticut_overlay_action"] = "base_unchanged"
                row.structured_data = data
                merged.append(row)
                continue
            base_row = base_by_number[number]
            base_data = dict(base_row.structured_data or {})
            replacement_data = dict(replacement.structured_data or {})
            replacement_data.update(
                {
                    "connecticut_overlay_action": "supplement_replacement",
                    "connecticut_superseded_base_provenance": {
                        "content_sha256": base_data.get("content_sha256"),
                        "source_url": base_row.source_url,
                        "transport_receipt": base_data.get("transport_receipt"),
                    },
                }
            )
            replacement.structured_data = replacement_data
            merged.append(replacement)
            emitted_supplement.add(number)
            replacements += 1

        for number in supplement_order:
            if number in emitted_supplement:
                continue
            row = supplement_by_number[number]
            data = dict(row.structured_data or {})
            data["connecticut_overlay_action"] = "supplement_addition"
            row.structured_data = data
            merged.append(row)
            additions += 1

        expected_count = (
            len(base_rows)
            - len(tombstone_by_number)
            + additions
        )
        if not merged or len(merged) != expected_count:
            raise RuntimeError(
                "connecticut deterministic supplement overlay count did not close"
            )
        frontier.update(
            {
                "base_sections_emitted": len(base_rows),
                "base_active_sections_discovered": int(
                    frontier.get("active_sections_discovered") or 0
                ),
                "supplement_replacements_applied": replacements,
                "supplement_additions_applied": additions,
                "supplement_tombstones_applied": len(tombstone_by_number),
                "supplement_group_tombstone_notices_applied": (
                    grouped_tombstone_notices_applied
                ),
                "supplement_group_tombstone_sections_applied": (
                    grouped_tombstone_sections_applied
                ),
                "combined_sections_emitted": len(merged),
                "sections_emitted": len(merged),
                "active_sections_discovered": len(merged),
                "combined_catalog_observations": int(
                    frontier.get("catalog_units_discovered") or 0
                )
                + int(frontier.get("supplement_catalog_units_discovered") or 0),
                "combined_chapter_pages_fetched": int(
                    frontier.get("chapter_pages_fetched") or 0
                )
                + int(frontier.get("supplement_chapter_pages_fetched") or 0),
                "current_as_of": self.OFFICIAL_CURRENT_AS_OF,
                "currentness_closed": True,
                "closed": True,
                "failures": [],
            }
        )
        self._last_connecticut_full_frontier = frontier
        self._last_full_corpus_frontier = frontier
        for row in merged:
            data = dict(row.structured_data or {})
            data.update(
                {
                    "official_frontier_closed": True,
                    "connecticut_currentness_closed": True,
                    "connecticut_current_as_of": self.OFFICIAL_CURRENT_AS_OF,
                    "connecticut_base_revision_date": self.OFFICIAL_BASE_REVISION_DATE,
                    "connecticut_supplement_revision_date": (
                        self.OFFICIAL_SUPPLEMENT_REVISION_DATE
                    ),
                }
            )
            row.structured_data = data
        return merged

    def _extract_connecticut_section_name(self, heading: str, section_number: str) -> str:
        heading_text = re.sub(r"\s+", " ", str(heading or "").strip())
        match = re.match(
            rf"Sec\.\s*{re.escape(section_number)}\.\s*(.+)$",
            heading_text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" .")
        return heading_text[:240]

    def _collect_connecticut_section_text(self, catchln: Tag) -> str:
        parent = catchln.parent
        if parent is None:
            return catchln.get_text(" ", strip=True)

        pieces: List[str] = []
        node = parent
        while isinstance(node, Tag):
            if node.name == "table" and "nav_tbl" in (node.get("class") or []):
                break
            if node.name == "hr":
                break
            text = node.get_text(" ", strip=True)
            if text:
                pieces.append(text)
            node = node.find_next_sibling()
        return "\n".join(pieces)

    async def _fetch_connecticut_page(self, url: str, timeout_seconds: int = 35) -> bytes:
        return await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=timeout_seconds,
            allow_archival_fallback=True,
            verify_tls=False,
            media_type="text/html",
            provider="connecticut_direct_page",
        )

    def official_title_url(self, title_number: object) -> str:
        token = str(title_number or "").strip().lower()
        if not re.fullmatch(r"[0-9]+[a-z]?", token):
            raise ValueError("Connecticut title number must be numeric or letter-suffixed")
        numeric, suffix = re.fullmatch(r"([0-9]+)([a-z]?)", token).groups()
        return (
            "https://www.cga.ct.gov/current/pub/title_"
            f"{int(numeric):02d}{suffix}.htm"
        )

    def official_supplement_title_url(self, title_number: object) -> str:
        token = str(title_number or "").strip().lower()
        if not re.fullmatch(r"[0-9]+[a-z]?", token):
            raise ValueError("Connecticut title number must be numeric or letter-suffixed")
        numeric, suffix = re.fullmatch(r"([0-9]+)([a-z]?)", token).groups()
        return (
            "https://www.cga.ct.gov/2026/sup/title_"
            f"{int(numeric):02d}{suffix}.htm"
        )

    @staticmethod
    def _connecticut_catalog_text(node: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            node.get_text(" ", strip=True) if node is not None else "",
        ).strip()

    def enumerate_official_title_catalog(
        self,
        html: bytes | str,
        *,
        page_url: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """Parse logical title rows from the official Connecticut index."""

        source_page = str(page_url or self.OFFICIAL_ENTRY_URL)
        soup = BeautifulSoup(html or b"", "html.parser")
        rows: List[Dict[str, object]] = []
        seen: set[str] = set()
        designations = list(soup.select("span.toc_ttl_desig"))
        if designations:
            candidates: Sequence[Any] = designations
        else:
            # Compact official test captures may omit the presentation spans.
            candidates = [
                anchor
                for anchor in soup.find_all("a", href=True)
                if self._TITLE_NUMBER_RE.search(str(anchor.get("href") or ""))
            ]

        for designation in candidates:
            designation_text = self._connecticut_catalog_text(designation)
            label_match = re.search(
                r"\bTitle\s+([0-9]+[a-z]?)\b",
                designation_text,
                re.IGNORECASE,
            )
            anchor = (
                designation
                if getattr(designation, "name", "") == "a"
                else designation.find_parent("a", href=True)
            )
            href_match = self._TITLE_NUMBER_RE.search(
                str(anchor.get("href") or "") if anchor is not None else ""
            )
            token = str(
                (label_match.group(1) if label_match else "")
                or (href_match.group(1) if href_match else "")
            ).lower()
            token = token.lstrip("0") or "0"
            if not token or token in seen:
                continue

            container = designation.find_parent("tr") or designation.parent
            context = self._connecticut_catalog_text(container)
            name_node = container.select_one(".toc_ttl_name") if container else None
            title_name = self._connecticut_catalog_text(name_node)
            lowered_context = context.casefold()
            reserved = "reserved for future use" in lowered_context
            inactive = bool(
                re.search(
                    r"\ball sections (?:transferred, )?repealed or obsolete\b|"
                    r"\ball sections transferred or repealed\b|"
                    r"\ball sections repealed(?: or obsolete)?\b",
                    context,
                    re.IGNORECASE,
                )
            )
            if anchor is not None:
                source_url = urllib.parse.urljoin(
                    source_page,
                    str(anchor.get("href") or "").strip(),
                )
                link_present = True
            else:
                source_url = source_page
                link_present = False
            disposition = "reserved" if reserved else ("inactive" if inactive else "active")
            seen.add(token)
            rows.append(
                {
                    "canonical_key": f"ct:title-{token}",
                    "title_number": token,
                    "name": title_name or f"Title {token}",
                    "source_url": source_url,
                    "source_link_disposition": "official",
                    "official_link_present": link_present,
                    "unit_disposition": disposition,
                    "text": context or f"Connecticut General Statutes Title {token}",
                }
            )
        return rows

    def official_title_catalog(
        self,
        html: bytes | str = b"",
        *,
        page_url: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """Return only title units actually parsed from official index bytes."""

        return self.enumerate_official_title_catalog(
            html,
            page_url=page_url,
        )

    def _assert_connecticut_title_catalog_closed(
        self,
        rows: Sequence[Dict[str, object]],
    ) -> set[str]:
        observed_numbers = tuple(str(row["title_number"]) for row in rows)
        if observed_numbers != self.OFFICIAL_TITLE_NUMBERS:
            missing = sorted(set(self.OFFICIAL_TITLE_NUMBERS) - set(observed_numbers))
            unexpected = sorted(set(observed_numbers) - set(self.OFFICIAL_TITLE_NUMBERS))
            raise RuntimeError(
                "connecticut official catalog enumeration did not close: "
                f"observed={len(observed_numbers)} expected={self.OFFICIAL_TITLE_COUNT} "
                f"missing={missing} unexpected={unexpected}"
            )
        reserved = {
            str(row["title_number"])
            for row in rows
            if row.get("unit_disposition") == "reserved"
            and row.get("official_link_present") is False
        }
        if reserved != set(self.OFFICIAL_RESERVED_TITLE_NUMBERS):
            raise RuntimeError(
                "connecticut official reserved-title frontier did not close"
            )
        inactive = {
            str(row["title_number"])
            for row in rows
            if row.get("unit_disposition") == "inactive"
            and row.get("official_link_present") is True
        }
        if inactive != set(self.OFFICIAL_INACTIVE_TITLE_NUMBERS):
            raise RuntimeError(
                "connecticut official inactive-title frontier did not close: "
                f"observed={sorted(inactive)} "
                f"expected={sorted(self.OFFICIAL_INACTIVE_TITLE_NUMBERS)}"
            )
        active = set(self.OFFICIAL_TITLE_NUMBERS) - reserved - inactive
        observed_active = {
            str(row["title_number"])
            for row in rows
            if row.get("unit_disposition") == "active"
            and row.get("official_link_present") is True
        }
        if observed_active != active:
            raise RuntimeError(
                "connecticut official active-title frontier did not close"
            )
        for row in rows:
            title_number = str(row["title_number"])
            if title_number in reserved:
                if str(row.get("source_url") or "") != self.OFFICIAL_ENTRY_URL:
                    raise RuntimeError(
                        "connecticut reserved title unexpectedly exposed a locator"
                    )
                continue
            expected_url = self.official_title_url(title_number)
            if self._canonical_fetch_url(str(row.get("source_url") or "")) != expected_url:
                raise RuntimeError(
                    "connecticut official title locator did not match its designation: "
                    f"title={title_number} expected={expected_url} "
                    f"observed={row.get('source_url')}"
                )
        return reserved

    def _assert_connecticut_base_revision_gate(
        self,
        html_text: str,
        *,
        page_url: str,
    ) -> None:
        """Bind the base catalog to its dated supplement dependency."""

        if self._canonical_fetch_url(page_url) != self.OFFICIAL_ENTRY_URL:
            raise RuntimeError("connecticut base catalog used an unexpected locator")
        soup = BeautifulSoup(html_text or "", "html.parser")
        text = self._connecticut_catalog_text(soup)
        if f"Revised to {self.OFFICIAL_BASE_REVISION_DATE}" not in text:
            raise RuntimeError("connecticut base revision date did not close")
        supplement_links = {
            self._canonical_fetch_url(
                urllib.parse.urljoin(page_url, str(anchor.get("href") or ""))
            )
            for anchor in soup.find_all("a", href=True)
            if "supplement" in self._connecticut_catalog_text(anchor).casefold()
        }
        if supplement_links != {self.OFFICIAL_SUPPLEMENT_ENTRY_URL}:
            raise RuntimeError(
                "connecticut base catalog did not expose its exact current supplement"
            )

    def _assert_connecticut_supplement_catalog_closed(
        self,
        rows: Sequence[Dict[str, object]],
        *,
        html_text: str,
        page_url: str,
    ) -> None:
        """Verify the exact official 2026 supplement title frontier."""

        if self._canonical_fetch_url(page_url) != self.OFFICIAL_SUPPLEMENT_ENTRY_URL:
            raise RuntimeError("connecticut supplement catalog used an unexpected locator")
        observed = tuple(str(row.get("title_number") or "") for row in rows)
        if observed != self.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS:
            missing = sorted(set(self.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS) - set(observed))
            unexpected = sorted(set(observed) - set(self.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS))
            raise RuntimeError(
                "connecticut supplement catalog enumeration did not close: "
                f"observed={len(observed)} "
                f"expected={len(self.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS)} "
                f"missing={missing} unexpected={unexpected}"
            )
        for row in rows:
            token = str(row.get("title_number") or "")
            if (
                row.get("unit_disposition") != "active"
                or row.get("official_link_present") is not True
                or self._canonical_fetch_url(str(row.get("source_url") or ""))
                != self.official_supplement_title_url(token)
            ):
                raise RuntimeError(
                    "connecticut supplement title locator/disposition diverged: "
                    f"title={token}"
                )
        soup = BeautifulSoup(html_text or "", "html.parser")
        text = self._connecticut_catalog_text(soup)
        if f"Revised to {self.OFFICIAL_SUPPLEMENT_REVISION_DATE}" not in text:
            raise RuntimeError("connecticut supplement revision date did not close")
        base_links = {
            self._canonical_fetch_url(
                urllib.parse.urljoin(page_url, str(anchor.get("href") or ""))
            )
            for anchor in soup.find_all("a", href=True)
            if "in conjunction with" in self._connecticut_catalog_text(anchor).casefold()
        }
        if base_links != {self.OFFICIAL_ENTRY_URL}:
            raise RuntimeError(
                "connecticut supplement did not bind its exact base edition"
            )

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-connecticut-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-connecticut-official-catalog/1.0",
                            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def fetch_official(self, code: str = "CT"):
        """Acquire the exhaustive official Connecticut title catalog.

        Live HTTPS retains the official titles index. Every General Statutes
        title is enumerated with an official CGA URL. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "CT").strip().upper() or "CT"
        base_html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not base_html:
            raise RuntimeError("connecticut official title index was unavailable")
        rows = self.official_title_catalog(
            base_html,
            page_url=self.OFFICIAL_ENTRY_URL,
        )
        reserved = self._assert_connecticut_title_catalog_closed(rows)
        self._assert_connecticut_base_revision_gate(
            base_html.decode("utf-8", errors="replace"),
            page_url=self.OFFICIAL_ENTRY_URL,
        )
        supplement_html = self._official_http_get(
            self.OFFICIAL_SUPPLEMENT_ENTRY_URL
        )
        if not supplement_html:
            raise RuntimeError("connecticut official supplement index was unavailable")
        supplement_rows = self.official_title_catalog(
            supplement_html,
            page_url=self.OFFICIAL_SUPPLEMENT_ENTRY_URL,
        )
        self._assert_connecticut_supplement_catalog_closed(
            supplement_rows,
            html_text=supplement_html.decode("utf-8", errors="replace"),
            page_url=self.OFFICIAL_SUPPLEMENT_ENTRY_URL,
        )
        supplement_by_title = {
            str(row["title_number"]): row for row in supplement_rows
        }
        combined_rows: List[Dict[str, object]] = []
        for value in rows:
            row = dict(value)
            title_number = str(row["title_number"])
            supplement_row = supplement_by_title.get(title_number)
            row["current_as_of"] = self.OFFICIAL_CURRENT_AS_OF
            row["edition_disposition"] = (
                "base_plus_2026_supplement"
                if supplement_row is not None
                else "base_unchanged_by_2026_supplement"
            )
            if supplement_row is not None:
                row["supplement_source_url"] = supplement_row["source_url"]
            combined_rows.append(row)
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
            f"GET {self.OFFICIAL_SUPPLEMENT_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "supplement_entry_url": self.OFFICIAL_SUPPLEMENT_ENTRY_URL,
            "current_as_of": self.OFFICIAL_CURRENT_AS_OF,
            "units": combined_rows,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = (
            len(base_html).to_bytes(8, "big")
            + base_html
            + len(supplement_html).to_bytes(8, "big")
            + supplement_html
        )
        frontier = {
            "bundle_closed": True,
            "closed": True,
            "currentness_closed": True,
            "current_as_of": self.OFFICIAL_CURRENT_AS_OF,
            "enumerator_closed": True,
            "expected_index_units": len(combined_rows),
            "base_index_units": len(rows),
            "supplement_index_units": len(supplement_rows),
            "method": "dated_base_plus_supplement",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(combined_rows),
            "linkless_reserved_units": sorted(reserved),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(combined_rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(combined_rows[0]["canonical_key"]),
            last_hierarchy_unit=str(combined_rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("CT", ConnecticutScraper)
