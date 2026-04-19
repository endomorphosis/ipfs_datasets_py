"""Scraper for Kansas state laws from the official legislature website."""

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class KansasScraper(BaseStateScraper):
    """Scraper for Kansas state laws from https://www.kslegislature.gov."""

    _CHAPTER_RE = re.compile(r"/statute/[0-9a-z]{3,4}_000_0000_chapter/?$", re.IGNORECASE)
    _ARTICLE_RE = re.compile(r"/[0-9a-z]{3,4}_000_0000_chapter/[0-9a-z]{3,4}_[0-9a-z]{3,4}_0000_article/?$", re.IGNORECASE)
    _SECTION_RE = re.compile(
        r"/[0-9a-z]{3,4}_000_0000_chapter/[0-9a-z]{3,4}_[0-9a-z]{3,4}_0000_article/"
        r"[0-9a-z]{3,4}_[0-9a-z]{3,4}_[0-9a-z]{4}_section/[0-9a-z]{3,4}_[0-9a-z]{3,4}_[0-9a-z]{4}_k/?$",
        re.IGNORECASE,
    )

    def get_base_url(self) -> str:
        """Return the base URL for Kansas's legislative website."""
        return "https://www.kslegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kansas."""
        return [
            {
                "name": "Kansas Statutes",
                "url": f"{self.get_base_url()}/li/b2025_26/statute/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Kansas statutes directly from official chapter/article/section pages."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []
        chapter_links = await self._discover_chapter_links(code_url)
        self.logger.info("Kansas official index: discovered %s chapter links", len(chapter_links))

        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            article_links = await self._discover_article_links(chapter_url)
            self.logger.info(
                "Kansas official index: chapter=%s index=%s/%s articles=%s statutes_so_far=%s",
                chapter_label,
                chapter_index,
                len(chapter_links),
                len(article_links),
                len(statutes),
            )
            for article_url, article_label in article_links:
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(article_url)
                for section_url, section_label in section_links:
                    if limit is not None and len(statutes) >= limit:
                        break
                    statute = await self._parse_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        chapter_label=chapter_label,
                        article_label=article_label,
                    )
                    if statute is not None:
                        statutes.append(statute)

        if not statutes:
            self.logger.warning("Kansas official direct crawl returned no statutes; skipping generic recovery fallback")
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_ks_html(self, url: str, timeout_seconds: int = 18) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 18))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-kansas-statutes-scraper/2.0",
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

    async def _discover_chapter_links(self, code_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(code_url, self._CHAPTER_RE)

    async def _discover_article_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(chapter_url, self._ARTICLE_RE)

    async def _discover_section_links(self, article_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(article_url, self._SECTION_RE)

    async def _discover_links(self, page_url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_ks_html(page_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            normalized = href.rstrip("/") + "/"
            if not pattern.search(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    async def _parse_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        chapter_label: str,
        article_label: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_ks_html(section_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        # Kansas renders the statute body in paragraph nodes outside an often-empty
        # #main container, so anchor parsing on the statute-specific classes.
        number = self._text_or_empty(soup.select_one(".stat_5f_number")).rstrip(".")
        caption = self._text_or_empty(soup.select_one(".stat_5f_caption"))
        statute_paragraphs = [
            self._text_or_empty(node)
            for node in soup.select("p.p_pt")
            if self._text_or_empty(node)
        ]
        if statute_paragraphs:
            body = self._normalize_legal_text(" ".join(statute_paragraphs))
        else:
            main = soup.select_one("#main")
            main_text = self._text_or_empty(main) if main is not None else ""
            body = self._normalize_legal_text(main_text or soup.get_text(" ", strip=True))
        if not number:
            match = re.search(r"\b(\d+[a-z]?(?:-\d+[a-z]?)?)\b", section_label)
            number = match.group(1) if match else ""
        if not number or len(body) < 80:
            return None

        chapter_number = self._chapter_number_from_label(chapter_label) or number.split("-", 1)[0]
        article_number = self._article_number_from_label(article_label)
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"KS-{number}",
            code_name=code_name,
            title_number=chapter_number,
            title_name=chapter_label or None,
            chapter_number=chapter_number,
            chapter_name=chapter_label or None,
            section_number=number,
            section_name=caption or section_label or f"Section {number}",
            short_title=caption or None,
            full_text=body,
            legal_area=self._identify_legal_area(" ".join([caption, chapter_label, article_label])),
            source_url=section_url,
            official_cite=f"K.S.A. {number}",
            structured_data={
                "source_kind": "official_kansas_statutes_html",
                "discovery_method": "official_chapter_article_section_index",
                "article_number": article_number,
                "article_label": article_label,
                "skip_hydrate": True,
            },
        )

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _chapter_number_from_label(label: str) -> str:
        match = re.search(r"\bChapter\s+([0-9a-z]+)", str(label or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _article_number_from_label(label: str) -> str:
        match = re.search(r"\bArticle\s+([0-9a-z]+)", str(label or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""


# Register this scraper with the registry
StateScraperRegistry.register("KS", KansasScraper)
