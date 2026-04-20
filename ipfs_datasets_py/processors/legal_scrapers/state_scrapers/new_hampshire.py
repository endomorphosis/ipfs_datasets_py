"""Scraper for New Hampshire state laws.

This module contains the scraper for New Hampshire statutes from the official state legislative website.
"""

import asyncio
from typing import List, Dict, Optional
import json
import re
import urllib.request
from urllib.parse import quote, urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewHampshireScraper(BaseStateScraper):
    """Scraper for New Hampshire state laws from gencourt/gc.nh.gov sources."""

    _NH_STATUTE_URL_RE = re.compile(
        r"/rsa/html/(?:NHTOC/[^/?#]+\.htm|(?:[^/?#]+/)+[^/?#]+\.htm)$",
        re.IGNORECASE,
    )
    _NH_TITLE_TEXT_RE = re.compile(r"^TITLE\s+([A-Z0-9-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_CHAPTER_TEXT_RE = re.compile(r"^CHAPTER\s+([0-9A-Z-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_SECTION_LINK_RE = re.compile(r"^Section\s+([0-9A-Z:.-]+)\s+(.+)$", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Return the base URL for New Hampshire's legislative website."""
        return "https://www.gencourt.state.nh.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Hampshire."""
        return [{
            "name": "New Hampshire Revised Statutes",
            "url": f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = self._normalize_wayback_like_url(str(statute.source_url or ""))
            statute.source_url = source
            if self._NH_STATUTE_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Hampshire's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            f"{self.get_base_url()}/rsa/html/",
            "https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://gc.nh.gov/rsa/html/",
            "http://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "http://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
        ]
        return_threshold = self._bounded_return_threshold(40)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_archived_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]
        # Keep archive discovery bounded so state-level scrape timeouts are not exhausted.
        for archived in await self._discover_archived_rsa_urls(limit=max(10, return_threshold)):
            if archived not in candidate_urls:
                candidate_urls.append(archived)

        archived_title_stubs = await self._scrape_archived_title_stubs(code_name, max_statutes=max(10, return_threshold))

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(archived_title_stubs)
        if len(merged) >= return_threshold:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "N.H. Rev. Stat.",
                max_sections=max(10, return_threshold),
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged

    async def _scrape_direct_archived_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            (
                "1:1",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
            ),
            (
                "1:2",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-2.htm",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 160:
                continue
            title_match = re.search(rf"\b{re.escape(section_number)}\s+([^–-]{{4,180}})", text)
            section_name = title_match.group(1).strip() if title_match else f"Section {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.H. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_hampshire_rsa_wayback_html",
                        "discovery_method": "wayback_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 20) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    async def _scrape_archived_title_stubs(self, code_name: str, max_statutes: int = 100) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"

        try:
            payload = await self._fetch_page_content_with_archival_fallback(root_url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        title_urls: List[str] = []
        seen_titles = set()
        title_stubs: List[NormalizedStatute] = []
        for a in soup.find_all("a", href=True):
            text = str(a.get_text(" ", strip=True) or "").strip()
            title_match = self._NH_TITLE_TEXT_RE.match(text)
            href = str(a.get("href") or "").strip()
            full_url = self._normalize_wayback_like_url(urljoin(root_url, href))
            if "/rsa/html/nhtoc/" not in full_url.lower():
                continue
            if full_url in seen_titles:
                continue
            seen_titles.add(full_url)
            title_urls.append(full_url)
            if title_match and len(title_stubs) < max_statutes:
                title_no = title_match.group(1).upper()
                title_name = title_match.group(2).strip()
                title_stubs.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_no}",
                        code_name=code_name,
                        section_number=f"Title {title_no}",
                        section_name=text[:200],
                        full_text=f"New Hampshire Revised Statutes {text}",
                        source_url=full_url,
                        legal_area=self._identify_legal_area(title_name),
                        official_cite=f"N.H. Rev. Stat. Title {title_no}",
                        metadata=StatuteMetadata(),
                        structured_data={"skip_hydrate": True, "record_type": "archived_title_stub"},
                    )
                )
            if len(title_urls) >= 12:
                break

        out: List[NormalizedStatute] = list(title_stubs)
        seen_sections = set()
        chapter_urls: List[tuple[str, str, str]] = []

        for title_url in title_urls:
            if len(out) >= max_statutes:
                break
            try:
                title_payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
                if not title_payload:
                    continue
            except Exception:
                continue

            title_soup = BeautifulSoup(title_payload, "html.parser")
            for a in title_soup.find_all("a", href=True):
                if len(out) >= max_statutes:
                    break
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_CHAPTER_TEXT_RE.match(text)
                if not match:
                    continue
                chapter_id = match.group(1).upper()
                key = chapter_id.lower()
                if key in seen_sections:
                    continue
                seen_sections.add(key)

                source_url = self._normalize_wayback_like_url(urljoin(title_url, href))
                chapter_name = text[:200] if text else f"Chapter {chapter_id}"
                chapter_urls.append((chapter_id, chapter_name, source_url))
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Chapter {chapter_id}",
                        code_name=code_name,
                        section_number=f"Chapter {chapter_id}",
                        section_name=chapter_name,
                        full_text=f"New Hampshire Revised Statutes {chapter_name}: {source_url}",
                        source_url=source_url,
                        legal_area=self._identify_legal_area(chapter_name),
                        official_cite=f"N.H. Rev. Stat. ch. {chapter_id}",
                        metadata=StatuteMetadata(),
                        structured_data={"skip_hydrate": True, "record_type": "archived_chapter_stub"},
                    )
                )

        if len(out) >= max_statutes:
            return out[:max_statutes]

        async def _fetch_chapter_sections(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            try:
                chapter_payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
                if not chapter_payload:
                    return []
            except Exception:
                return []

            chapter_soup = BeautifulSoup(chapter_payload, "html.parser")
            section_links: List[tuple[str, str, str]] = []
            seen_local = set()
            for a in chapter_soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_SECTION_LINK_RE.match(text)
                if not match:
                    continue
                section_number = match.group(1).strip()
                section_title = match.group(2).strip().rstrip(".")
                section_key = section_number.lower()
                if section_key in seen_local:
                    continue
                seen_local.add(section_key)
                section_links.append(
                    (
                        section_number,
                        section_title,
                        self._normalize_wayback_like_url(urljoin(chapter_url, href)),
                    )
                )

            section_statutes: List[NormalizedStatute] = []
            for section_number, section_title, section_url in section_links:
                try:
                    section_payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
                except Exception:
                    continue
                section_text = self._extract_statute_text(section_payload)
                if len(section_text) < 160:
                    continue
                section_name = f"Section {section_number} {section_title}".strip()
                section_statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=section_text,
                        source_url=section_url,
                        legal_area=self._identify_legal_area(section_name or chapter_name),
                        official_cite=f"N.H. Rev. Stat. § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )
                if len(section_statutes) >= max_statutes:
                    break
            return section_statutes

        sem = asyncio.Semaphore(4)

        async def _bounded_fetch(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            async with sem:
                return await _fetch_chapter_sections(chapter_id, chapter_name, chapter_url)

        chapters_to_fetch = chapter_urls if self._full_corpus_enabled() else chapter_urls[:8]
        for section_batch in await asyncio.gather(
            *[
                _bounded_fetch(chapter_id, chapter_name, chapter_url)
                for chapter_id, chapter_name, chapter_url in chapters_to_fetch
            ],
            return_exceptions=True,
        ):
            if isinstance(section_batch, Exception):
                continue
            for statute in section_batch:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                out.append(statute)
                if len(out) >= max_statutes:
                    return out[:max_statutes]

        return out

    def _extract_statute_text(self, payload: bytes) -> str:
        if not payload:
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""

        soup = BeautifulSoup(payload, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        match = re.search(
            r"(Section\s+[0-9A-Z:.-]+.*?Source\.[^\n]*?(?:\d{4}[^\n]*)?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)[:4000]
        return text[:4000]

    async def _discover_archived_rsa_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.gencourt.state.nh.us/rsa/html/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/rsa/html/" not in lower_original:
                continue
            replay = self._normalize_wayback_like_url(
                f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            )
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    def _normalize_wayback_like_url(self, value: str) -> str:
        url = str(value or "").strip()
        if not url:
            return url
        url = re.sub(r"(web\.archive\.org/web/\d+/https?):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        url = re.sub(r"(web\.archive\.org/web/\d+/http):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        return url

    def _parse_json_rows(self, payload: bytes) -> List[List[object]]:
        if not payload:
            return []
        try:
            parsed = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed[1:] if isinstance(row, list)]


# Register this scraper with the registry
StateScraperRegistry.register("NH", NewHampshireScraper)
