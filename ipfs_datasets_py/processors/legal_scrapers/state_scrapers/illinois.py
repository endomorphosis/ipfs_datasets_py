"""Scraper for Illinois state laws.

This module contains the scraper for Illinois statutes from the official
Illinois General Assembly website.
"""

from html import unescape
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IllinoisScraper(BaseStateScraper):
    """Scraper for Illinois state laws from https://www.ilga.gov."""

    _CHAPTER_LINK_RE = re.compile(r"/Legislation/ILCS/Acts\?", re.IGNORECASE)
    _ACT_LINK_RE = re.compile(r"/Legislation/ILCS/Articles\?", re.IGNORECASE)
    _FULL_ACT_LINK_RE = re.compile(r"/legislation/ILCS/details\?.*ChapAct=FullText", re.IGNORECASE)
    _CITE_RE = re.compile(r"\((?P<cite>\d+\s+ILCS\s+[^)]+?)\)")
    _SECTION_CITE_RE = re.compile(r"^(?P<chapter>\d+)\s+ILCS\s+(?P<act>[^/\s]+(?:/[^/\s]+)*)/(?P<section>[^)\s]+)$")

    def get_base_url(self) -> str:
        """Return the base URL for Illinois's legislative website."""
        return "https://www.ilga.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Illinois."""
        return [
            {
                "name": "Illinois Compiled Statutes",
                "url": f"{self.get_base_url()}/Legislation/ILCS/Chapters",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Illinois statutes through official Chapters -> Acts -> FullText pages."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []

        chapter_links = await self._discover_chapter_links(code_url)
        self.logger.info("Illinois official index: discovered %s chapter links", len(chapter_links))

        for chapter_index, chapter in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            act_links = await self._discover_act_links(chapter["url"])
            self.logger.info(
                "Illinois official index: chapter=%s index=%s/%s acts=%s statutes_so_far=%s",
                chapter.get("chapter_number") or chapter.get("label") or chapter["url"],
                chapter_index,
                len(chapter_links),
                len(act_links),
                len(statutes),
            )

            for act_index, act in enumerate(act_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                parsed = await self._parse_full_act(
                    code_name=code_name,
                    chapter=chapter,
                    act=act,
                    max_statutes=remaining,
                )
                statutes.extend(parsed)
                if act_index % 50 == 0:
                    self.logger.info(
                        "Illinois official index: chapter=%s acts_processed=%s/%s statutes_so_far=%s",
                        chapter.get("chapter_number") or chapter.get("label") or chapter["url"],
                        act_index,
                        len(act_links),
                        len(statutes),
                    )

        if not statutes:
            self.logger.warning("Illinois official direct crawl returned no statutes; skipping generic recovery fallback")
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_il_html(self, url: str, timeout_seconds: int = 20) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 20))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-illinois-statutes-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=(min(5, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
            return payload.decode("utf-8", errors="replace")
        return ""

    async def _discover_chapter_links(self, code_url: str) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = code_url or f"{self.get_base_url()}/Legislation/ILCS/Chapters"
        html = await self._fetch_official_il_html(index_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._CHAPTER_LINK_RE.search(href):
                continue
            full_url = self._canonical_ilga_url(urljoin(index_url, href))
            if full_url in seen:
                continue
            seen.add(full_url)
            label = self._clean_label(anchor.get_text(" ", strip=True))
            query = parse_qs(urlparse(full_url).query)
            out.append(
                {
                    "url": full_url,
                    "label": label,
                    "chapter_id": self._first_query(query, "ChapterID"),
                    "chapter_number": self._first_query(query, "ChapterNumber"),
                    "chapter_name": self._first_query(query, "Chapter") or self._chapter_name_from_label(label),
                    "major_topic": self._first_query(query, "MajorTopic"),
                }
            )
        return out

    async def _discover_act_links(self, chapter_url: str) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_il_html(chapter_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._ACT_LINK_RE.search(href):
                continue
            full_url = self._canonical_ilga_url(urljoin(chapter_url, href))
            if full_url in seen:
                continue
            seen.add(full_url)
            label = self._clean_label(anchor.get_text(" ", strip=True))
            query = parse_qs(urlparse(full_url).query)
            chap_act, act_name = self._split_act_label(label)
            out.append(
                {
                    "url": full_url,
                    "label": label,
                    "act_id": self._first_query(query, "ActID"),
                    "chapter_id": self._first_query(query, "ChapterID"),
                    "chap_act": chap_act,
                    "act_name": act_name,
                }
            )
        return out

    async def _parse_full_act(
        self,
        *,
        code_name: str,
        chapter: Dict[str, str],
        act: Dict[str, str],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        full_url = await self._full_act_url(act["url"])
        if not full_url:
            return []
        html = await self._fetch_official_il_html(full_url, timeout_seconds=35)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript", "form", "nav", "footer", "header"]):
            node.decompose()
        text = self._normalize_legal_text(unescape(soup.get_text("\n", strip=True)))
        if not text:
            return []

        matches = list(self._CITE_RE.finditer(text))
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for idx, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            cite = self._normalize_legal_text(match.group("cite"))
            if " heading" in cite.lower():
                continue
            cite_match = self._SECTION_CITE_RE.match(cite)
            if not cite_match:
                continue

            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section_text = self._normalize_legal_text(text[start:end])
            if len(section_text) < 60:
                continue

            chapter_number = cite_match.group("chapter")
            act_number = cite_match.group("act")
            section_number = cite_match.group("section")
            section_key = f"{chapter_number} ILCS {act_number}/{section_number}"
            if section_key in seen_sections:
                continue
            seen_sections.add(section_key)

            section_name = self._section_name_from_text(section_text, section_number)
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"IL-{chapter_number}-{act_number}-{section_number}".replace("/", "-"),
                    code_name=code_name,
                    title_number=chapter_number,
                    title_name=chapter.get("major_topic") or None,
                    chapter_number=chapter_number,
                    chapter_name=chapter.get("chapter_name") or None,
                    section_number=f"{act_number}/{section_number}",
                    section_name=section_name or f"Section {section_number}",
                    short_title=section_name or None,
                    full_text=section_text,
                    legal_area=self._identify_legal_area(
                        " ".join(
                            part
                            for part in [
                                section_name,
                                act.get("act_name"),
                                chapter.get("chapter_name"),
                                chapter.get("major_topic"),
                            ]
                            if part
                        )
                    ),
                    source_url=full_url,
                    official_cite=f"{chapter_number} ILCS {act_number}/{section_number}",
                    structured_data={
                        "source_kind": "official_illinois_ilga_full_act_html",
                        "discovery_method": "official_chapter_act_fulltext_index",
                        "chapter_url": chapter.get("url"),
                        "act_url": act.get("url"),
                        "act_id": act.get("act_id"),
                        "act_name": act.get("act_name"),
                        "chap_act": act.get("chap_act") or f"{chapter_number} ILCS {act_number}/",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _full_act_url(self, act_url: str) -> str:
        html = await self._fetch_official_il_html(act_url)
        if not html:
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if self._FULL_ACT_LINK_RE.search(href):
                return self._canonical_ilga_url(urljoin(act_url, href))
        query = parse_qs(urlparse(act_url).query)
        act_id = self._first_query(query, "ActID")
        chapter_id = self._first_query(query, "ChapterID")
        if not act_id or not chapter_id:
            return ""
        params = {
            "ActID": act_id,
            "ChapterID": chapter_id,
            "SeqStart": "",
            "ChapAct": "FullText",
        }
        return f"{self.get_base_url()}/legislation/ILCS/details?{urlencode(params)}"

    @staticmethod
    def _first_query(query: Dict[str, List[str]], key: str) -> str:
        values = query.get(key) or []
        return unescape(values[0]).strip() if values else ""

    @staticmethod
    def _clean_label(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(str(value or "").replace("\xa0", " "))).strip()

    @staticmethod
    def _chapter_name_from_label(label: str) -> str:
        match = re.match(r"CHAPTER\s+\d+\s+(.+)$", label, flags=re.IGNORECASE)
        return match.group(1).strip() if match else label

    @classmethod
    def _split_act_label(cls, label: str) -> Tuple[str, str]:
        cleaned = cls._clean_label(label)
        match = re.match(r"(?P<chap_act>\d+\s+ILCS\s+[^/]+/)\s*(?P<name>.*)$", cleaned, flags=re.IGNORECASE)
        if match:
            return cls._clean_label(match.group("chap_act")), cls._clean_label(match.group("name"))
        return "", cleaned

    def _section_name_from_text(self, section_text: str, section_number: str) -> str:
        pattern = re.compile(
            rf"\bSec\.\s*{re.escape(section_number)}\.\s*(?P<name>.*?)(?:\s+\([a-z0-9]+\)|\s+\(Source:|\s+[A-Z][a-z]+ actions|\s+The\s|\s+This\s|$)",
            re.IGNORECASE,
        )
        match = pattern.search(section_text)
        if match:
            name = self._normalize_legal_text(match.group("name"))
            if name and len(name) <= 180:
                return name.rstrip(".")
        generic = re.search(r"\bSec\.\s*[\w.-]+\.\s*(?P<name>[^.]{3,160})\.", section_text, flags=re.IGNORECASE)
        if generic:
            return self._normalize_legal_text(generic.group("name")).rstrip(".")
        return ""

    @staticmethod
    def _canonical_ilga_url(url: str) -> str:
        parsed = urlparse(url)
        scheme = "https"
        netloc = "www.ilga.gov"
        path = parsed.path
        return urlunparse((scheme, netloc, path, "", parsed.query, ""))


# Register this scraper with the registry
StateScraperRegistry.register("IL", IllinoisScraper)
