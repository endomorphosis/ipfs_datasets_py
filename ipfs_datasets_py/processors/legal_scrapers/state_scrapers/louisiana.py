"""Scraper for Louisiana state laws.

This module contains the scraper for Louisiana statutes from the official state legislative website.
"""

import re
from html import unescape
from typing import List, Dict

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class LouisianaScraper(BaseStateScraper):
    """Scraper for Louisiana state laws from http://www.legis.la.gov"""

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
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Louisiana's legislative website.

        Louisiana live endpoints can be brittle in automation contexts.
        Prefer archived Law.aspx pages with direct statute body HTML.
        """
        archival = await self._scrape_archived_law_pages(code_name=code_name, max_statutes=20)
        if archival:
            self.logger.info(f"Louisiana archival fallback: Scraped {len(archival)} sections")
            return archival

        return await self._playwright_scrape(
            code_name,
            code_url,
            "La. Rev. Stat.",
            wait_for_selector="a[href*='RS'], .law-link",
            timeout=45000,
        )

    async def _scrape_archived_law_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_sections = set()

        for law_url in self._ARCHIVE_LAW_URLS:
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
