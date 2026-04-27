"""Scraper for Louisiana state laws.

This module contains the scraper for Louisiana statutes from the official state legislative website.
"""

import re
import json
import urllib.request
import urllib.parse
from html import unescape
from typing import List, Dict, Optional

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class LouisianaScraper(BaseStateScraper):
    """Scraper for Louisiana state laws from http://www.legis.la.gov"""

    _TOC_TITLE_POSTBACK_RE = re.compile(
        r"__doPostBack\('([^']*ListViewTOC1\$ctrl\d+\$LinkButton1a)'",
        re.IGNORECASE,
    )
    _LAW_LINK_RE = re.compile(r"Law\.aspx\?d=\d+", re.IGNORECASE)

    _ARCHIVE_LAW_URLS = [
        "http://web.archive.org/web/20240407200045/https://legis.la.gov/Legis/law.aspx?d=100114",
        "http://web.archive.org/web/20250523231945/https://legis.la.gov/Legis/Law.aspx?d=100115",
        "http://web.archive.org/web/20250501013708/https://legis.la.gov/Legis/Law.aspx?d=100117",
        "http://web.archive.org/web/20230825044518/http://legis.la.gov/legis/Law.aspx?d=100122",
        "http://web.archive.org/web/20250501064333/https://legis.la.gov/Legis/Law.aspx?d=100124",
        "http://web.archive.org/web/20240809002954/https://legis.la.gov/Legis/Law.aspx?d=100148",
    ]
    
    def get_base_url(self) -> str:
        """Return the base URL for Louisiana's legislative website."""
        return "https://legis.la.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Louisiana."""
        return [{
            "name": "Louisiana Revised Statutes",
            "url": f"{self.get_base_url()}/legis/Laws.aspx",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Louisiana's legislative website.

        Louisiana live endpoints can be brittle in automation contexts.
        Prefer archived Law.aspx pages with direct statute body HTML.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        return_threshold = limit if limit is not None else 1000000
        toc = await self._scrape_live_toc_pages(code_name=code_name, max_statutes=return_threshold)
        if toc:
            return toc[:limit] if limit is not None else toc
        if not self._full_corpus_enabled() or max_statutes is not None:
            live = await self._scrape_live_law_pages(code_name=code_name, max_statutes=return_threshold)
            if live:
                return live

        archival = await self._scrape_archived_law_pages(code_name=code_name, max_statutes=max(10, return_threshold))
        if archival and (not self._full_corpus_enabled() or max_statutes is not None):
            self.logger.info(f"Louisiana archival fallback: Scraped {len(archival)} sections")
            return archival

        playwright = await self._playwright_scrape(
            code_name,
            code_url,
            "La. Rev. Stat.",
            wait_for_selector="a[href*='RS'], .law-link",
            timeout=45000,
            max_sections=max(10, return_threshold),
        )
        if playwright:
            return playwright
        if archival:
            self.logger.info(f"Louisiana archival fallback: Scraped {len(archival)} sections")
            if limit is None:
                return list(archival)
            return list(archival)
        return []

    async def _scrape_live_toc_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        title_pages = await self._discover_live_toc_title_pages(limit=max_statutes)
        if not title_pages:
            return []
        return await self._scrape_law_page_urls(
            code_name=code_name,
            law_urls=title_pages,
            max_statutes=max_statutes,
            source_kind="official_louisiana_toc_law_page",
            discovery_method="live_toc_postback",
        )

    async def _scrape_live_law_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        for live_url in [
            "https://legis.la.gov/Legis/Law.aspx?d=100114",
            "https://legis.la.gov/Legis/Law.aspx?d=100115",
        ][: max(1, int(max_statutes or 1))]:
            law_html = await self._request_text(law_url=live_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            if not law_html:
                continue
            section_number = self._extract_section_number(law_html)
            body_html = self._extract_law_body_html(law_html)
            full_text = self._clean_html_text(body_html)
            if not section_number or len(full_text) < 280:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=f"RS {section_number}",
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=live_url,
                    official_cite=f"La. Rev. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_live_law_page", "skip_hydrate": True},
                )
            )
        return statutes

    async def _scrape_archived_law_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_sections = set()

        candidate_urls = list(self._ARCHIVE_LAW_URLS)
        discovered = await self._discover_archived_law_urls(
            limit=2000 if self._full_corpus_enabled() else 160
        )
        for url in discovered:
            if url not in candidate_urls:
                candidate_urls.append(url)

        for law_url in candidate_urls:
            if len(statutes) >= max_statutes:
                break

            law_html = await self._request_text(law_url=law_url, headers=headers, timeout=45)
            if not law_html:
                continue

            section_number = self._extract_section_number(law_html)
            if not section_number or section_number in seen_sections:
                continue

            body_html = self._extract_law_body_html(law_html)
            if not body_html:
                continue

            full_text = self._clean_html_text(body_html)
            if len(full_text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=f"RS {section_number}",
                full_text=full_text,
                legal_area=self._identify_legal_area(full_text),
                source_url=law_url,
                official_cite=f"La. Rev. Stat. {section_number}",
            )
            statutes.append(statute)
            seen_sections.add(section_number)

        return statutes

    async def _scrape_law_page_urls(
        self,
        *,
        code_name: str,
        law_urls: List[str],
        max_statutes: int,
        source_kind: str,
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_sections = set()

        for law_url in law_urls:
            if len(statutes) >= max_statutes:
                break

            law_html = await self._request_text(law_url=law_url, headers=headers, timeout=45)
            if not law_html:
                continue

            section_number = self._extract_section_number(law_html)
            if not section_number or section_number in seen_sections:
                continue

            body_html = self._extract_law_body_html(law_html)
            if not body_html:
                continue

            full_text = self._clean_html_text(body_html)
            if len(full_text) < 280:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=f"RS {section_number}",
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=law_url,
                    official_cite=f"La. Rev. Stat. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": source_kind,
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
            seen_sections.add(section_number)

        return statutes

    async def _discover_live_toc_title_pages(self, limit: int) -> List[str]:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = f"{self.get_base_url()}/legis/Laws_Toc.aspx?folder=75&level=Parent"

        def _crawl() -> List[str]:
            session = requests.Session()
            response = session.get(root_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            base_payload = {}
            for inp in soup.select("input[name]"):
                name = inp.get("name")
                if name:
                    base_payload[name] = inp.get("value") or ""

            event_targets: List[str] = []
            seen_targets = set()
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                match = self._TOC_TITLE_POSTBACK_RE.search(href)
                if not match:
                    continue
                target = match.group(1)
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                event_targets.append(target)

            law_urls: List[str] = []
            seen_laws = set()
            title_limit = len(event_targets) if self._full_corpus_enabled() and limit >= 1000000 else min(len(event_targets), max(1, limit))
            for target in event_targets[:title_limit]:
                payload = dict(base_payload)
                payload["__EVENTTARGET"] = target
                payload["__EVENTARGUMENT"] = ""
                post = session.post(
                    root_url,
                    data=payload,
                    timeout=45,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                post.raise_for_status()
                page = BeautifulSoup(post.text, "html.parser")
                for anchor in page.find_all("a", href=True):
                    href = str(anchor.get("href") or "").strip()
                    if not self._LAW_LINK_RE.search(href):
                        continue
                    full_url = urllib.parse.urljoin(root_url, href)
                    if full_url in seen_laws:
                        continue
                    seen_laws.add(full_url)
                    law_urls.append(full_url)
            return law_urls

        try:
            law_urls = await asyncio.to_thread(_crawl)
        except Exception as exc:
            self.logger.debug(f"Louisiana live TOC discovery failed: {exc}")
            return []

        self.logger.info("Louisiana live TOC: discovered %s law pages", len(law_urls))
        return law_urls

    async def _discover_archived_law_urls(self, limit: int = 120) -> List[str]:
        """Discover additional archived Law.aspx pages via Wayback CDX."""
        cdx_url = (
            "http://web.archive.org/cdx/search/cdx?url=legis.la.gov/Legis/Law.aspx?d=*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(limit))}"
        )

        try:
            req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
            rows = json.loads(payload)
            if not isinstance(rows, list) or len(rows) < 2:
                return []

            discovered: List[str] = []
            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
                discovered.append(f"http://web.archive.org/web/{ts}/{encoded}")
            return discovered
        except Exception as exc:
            self.logger.debug(f"Louisiana CDX discovery failed: {exc}")
            return []

    def _extract_law_body_html(self, html: str) -> str:
        marker = re.search(
            r'<span[^>]+id=["\']ctl00_PageBody_LabelDocument["\'][^>]*>(.*?)</span>',
            str(html or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        return marker.group(1) if marker else ""

    def _extract_section_number(self, html: str) -> str:
        marker = re.search(
            r'<span[^>]+id=["\']ctl00_PageBody_LabelName["\'][^>]*>(.*?)</span>',
            str(html or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not marker:
            return ""

        text = self._clean_html_text(marker.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _clean_html_text(self, html: str, max_chars: int = 12000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)

        text = unescape(value)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()[:max_chars]

    async def _request_text(self, law_url: str, headers: Dict[str, str], timeout: int) -> str:
        candidates = [str(law_url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    candidate,
                    timeout_seconds=timeout,
                )
                if not payload:
                    continue
                return payload.decode("utf-8", errors="replace")
            except Exception:
                continue
        return ""


# Register this scraper with the registry
StateScraperRegistry.register("LA", LouisianaScraper)
