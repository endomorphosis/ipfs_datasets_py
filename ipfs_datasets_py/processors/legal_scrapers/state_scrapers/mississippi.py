"""Scraper for Mississippi state laws.

This module contains the scraper for Mississippi statutes from the official state legislative website.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import re
from html import unescape
from typing import Dict, List, Optional
from urllib.parse import urljoin
import urllib.request

from bs4 import BeautifulSoup

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MississippiScraper(BaseStateScraper):
    """Scraper for Mississippi state laws from http://www.legislature.ms.gov"""

    _ARCHIVE_INDEX_URLS = [
        "https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
        "https://web.archive.org/web/20001009002301/http://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
        "https://web.archive.org/web/20240414234245/https://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
    ]
    
    def get_base_url(self) -> str:
        """Return the base URL for Mississippi's legislative website."""
        return "http://www.legislature.ms.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Mississippi."""
        return [{
            "name": "Mississippi Code",
            "url": "https://www.legislature.ms.gov/legislation/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Mississippi's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=40)
        if not self._full_corpus_enabled() or max_statutes is not None:
            recovery = await self._scrape_jina_justia_seed_sections(code_name=code_name, max_statutes=limit or 1)
            if recovery:
                return recovery[:limit] if limit is not None else recovery

        archival = await self._scrape_archived_bill_history(code_name=code_name, max_statutes=limit or 1000000)
        if archival and (not self._full_corpus_enabled() or max_statutes is not None):
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            return archival[:limit] if limit is not None else archival

        candidate_urls = [
            code_url,
            "https://www.legislature.ms.gov/legislation/",
            "http://www.legislature.ms.gov/legislation/",
            # Archive fallback candidate when live pathing changes.
            "https://web.archive.org/web/20251017000000/https://www.legislature.ms.gov/legislation/",
        ]

        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Miss. Code Ann.",
                        max_sections=limit,
                        wait_for_selector="a[href*='statute'], a[href*='code'], a[href*='title'], a[href*='chapter']",
                        timeout=45000,
                    )
                    if statutes:
                        return statutes[:limit]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Miss. Code Ann.", max_sections=limit)
            if statutes:
                return statutes[:limit]

        if archival:
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            return archival[:limit] if limit is not None else archival
        return []

    async def _scrape_jina_justia_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            (
                "97-3-7",
                "https://law.justia.com/codes/mississippi/2024/title-97/chapter-3/section-97-3-7/",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_page in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{source_page}"
            text = await self._request_text_direct(reader_url, timeout=30)
            text = self._clean_jina_markdown(text)
            if len(text) < 280:
                continue
            title_match = re.search(rf"Mississippi Code §\s*{re.escape(section_number)}\s*\(2024\)\s*-\s*(.+)", text)
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
                    source_url=source_page,
                    official_cite=f"Miss. Code Ann. § {section_number}",
                    structured_data={
                        "source_kind": "jina_reader_justia_mississippi_code",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _clean_jina_markdown(self, text: str) -> str:
        value = str(text or "")
        marker = "Markdown Content:"
        if marker in value:
            value = value.split(marker, 1)[-1]
        value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", value)
        value = re.sub(r"#+\s*", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    async def _request_text_direct(self, url: str, timeout: int = 30) -> str:
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

    async def _scrape_archived_bill_history(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        bounded_scrape = max_statutes <= 10
        if bounded_scrape:
            headers["X-Bounded-Scrape"] = "1"
        statutes: List[NormalizedStatute] = []
        seen_history_urls = set()

        for index_url in self._ARCHIVE_INDEX_URLS:
            if len(statutes) >= max_statutes:
                break

            html = await self._request_text(
                index_url,
                headers=headers,
                timeout=15 if max_statutes <= 10 else 60,
                attempts=1 if max_statutes <= 10 else 3,
            )
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            history_urls: List[str] = []
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if "/history/" not in href.lower() or not href.lower().endswith(".htm"):
                    continue
                history_urls.append(urljoin(index_url, href))

            for history_url in history_urls:
                if len(statutes) >= max_statutes:
                    break
                if history_url in seen_history_urls:
                    continue
                seen_history_urls.add(history_url)

                statute = await self._build_statute_from_history_url(
                    code_name=code_name,
                    history_url=history_url,
                    headers=headers,
                )
                if statute is None:
                    continue
                statutes.append(statute)

            if statutes:
                break

        return statutes

    async def _build_statute_from_history_url(
        self,
        code_name: str,
        history_url: str,
        headers: Dict[str, str],
    ) -> Optional[NormalizedStatute]:
        html = await self._request_text(
            history_url,
            headers=headers,
            timeout=15 if headers.get("X-Bounded-Scrape") == "1" else 60,
            attempts=1 if headers.get("X-Bounded-Scrape") == "1" else 3,
        )
        if not html:
            return None

        if "Got an HTTP 404 response at crawl time" in html:
            return None

        text = self._clean_html_text(html)
        if len(text) < 280 or "History of Actions" not in text:
            return None

        bill_id = self._extract_bill_id(text=text, url=history_url)
        if not bill_id:
            return None

        section_number = self._extract_section_number(text) or bill_id
        description = self._extract_description(text)
        section_name = description or f"Bill history {bill_id}"
        official_cite = f"Miss. Bill History {bill_id}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text[:14000],
            legal_area=self._identify_legal_area(f"{description} {text[:1200]}"),
            source_url=history_url,
            official_cite=official_cite,
        )

    def _extract_bill_id(self, text: str, url: str) -> str:
        match = re.search(r"\b(House|Senate)\s+Bill\s+([0-9]{1,4})\b", text, flags=re.IGNORECASE)
        if match:
            chamber = "HB" if match.group(1).lower().startswith("house") else "SB"
            return f"{chamber}{int(match.group(2)):04d}"

        url_match = re.search(r"/(HB|SB)(\d{4})\.htm", str(url or ""), flags=re.IGNORECASE)
        if url_match:
            return f"{url_match.group(1).upper()}{url_match.group(2)}"

        return ""

    def _extract_description(self, text: str) -> str:
        match = re.search(
            r"Description:\s*(.+?)(?:History of Actions:|Background Information:|Title:)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        value = re.sub(r"\s+", " ", match.group(1)).strip(" ;")
        return value

    def _clean_html_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        text = unescape(text).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def _request_text(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: int,
        attempts: int = 3,
    ) -> str:
        for _ in range(max(1, int(attempts))):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if payload:
                    return payload.decode("utf-8", errors="replace")
            except Exception:
                await asyncio.sleep(0.7)
                continue
        return ""


# Register this scraper with the registry
StateScraperRegistry.register("MS", MississippiScraper)
