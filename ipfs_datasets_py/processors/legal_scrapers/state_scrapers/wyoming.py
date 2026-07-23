"""Scraper for Wyoming state laws.

This module contains the scraper for Wyoming statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from ...playwright_limiter import acquire_playwright_slot

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WyomingScraper(BaseStateScraper):
    """Scraper for Wyoming state laws from https://www.wyoleg.gov"""

    _SECTION_HEADER_RE = re.compile(
        r"(?m)^\s*(\d{1,2}-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?)\.\s+(.+)$"
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Wyoming's legislative website."""
        return "https://www.wyoleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wyoming."""
        return [{
            "name": "Wyoming Statutes",
            "url": f"{self.get_base_url()}/stateStatutes/StatutesDownload",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wyoming's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        max_sections = self._effective_scrape_limit(max_statutes, default=160)
        max_sections_value = int(max_sections or 1000000)

        # The official download catalog has stable title PDFs. Prefer it over
        # the JS page so full-corpus runs do not depend on rendered link order.
        deterministic = await self._scrape_deterministic_title_pdfs(
            code_name,
            "Wyo. Stat.",
            max_sections=max_sections_value,
        )
        if deterministic:
            return deterministic[:max_sections_value]

        if PLAYWRIGHT_AVAILABLE:
            self.logger.info("Wyoming: Using Playwright for JavaScript rendering")
            try:
                result = await self._scrape_with_playwright(
                    code_name,
                    code_url,
                    "Wyo. Stat.",
                    max_sections=max_sections_value,
                )
                if result:
                    return result[:max_sections_value]
            except Exception as e:
                self.logger.warning(f"Wyoming Playwright failed: {e}, falling back")
        
        result = await self._custom_scrape_wyoming(
            code_name,
            code_url,
            "Wyo. Stat.",
            max_sections=max_sections_value,
        )
        return result[:max_sections_value]
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 60
    ) -> List[NormalizedStatute]:
        """Scrape Wyoming using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError:
            return []
        
        statutes = []
        
        async with acquire_playwright_slot():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(code_url, wait_until='networkidle', timeout=60000)
                    await page.wait_for_selector('a', timeout=10000)

                    content = await page.content()
                    soup = BeautifulSoup(content, 'html.parser')
                    links = soup.find_all('a', href=True)

                    section_count = 0
                    seen_urls = set()
                    for link in links:
                        if section_count >= max_sections:
                            break

                        link_text = link.get_text(strip=True)
                        link_href = link.get('href', '')

                        if len(link_text) < 5:
                            continue
                        full_url = urljoin(code_url, link_href)
                        full_url_l = full_url.lower()
                        # Focus on authoritative downloadable title PDFs instead of nav links.
                        if not (full_url_l.endswith('.pdf') and '/statutes/compress/title' in full_url_l):
                            continue
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                        m = re.search(r"\btitle\s+(\d+(?:\.\d+)?)", link_text, re.IGNORECASE)
                        if m:
                            section_number = m.group(1)

                        full_text = await self._extract_pdf_text_summary(full_url)
                        if len(full_text.strip()) < 80:
                            full_text = (
                                f"Wyoming Statutes Title {section_number}: {link_text}. "
                                f"Official source PDF: {full_url}."
                            )

                        statute = NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § {section_number}",
                            code_name=code_name,
                            section_number=section_number,
                            section_name=link_text[:200],
                            full_text=full_text,
                            legal_area=self._identify_legal_area(link_text),
                            source_url=full_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata()
                        )

                        statutes.append(statute)
                        section_count += 1

                    self.logger.info(f"Wyoming Playwright: Scraped {len(statutes)} sections")

                finally:
                    try:
                        await page.close()
                    finally:
                        await browser.close()
        
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        """Extract statute text from a PDF using system `pdftotext`.

        This keeps Wyoming strict-mode scraping resilient without adding heavy PDF
        parser dependencies to the Python environment.
        """
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                pdf_url,
                timeout_seconds=45,
            )
            if not payload:
                return ""

            with tempfile.TemporaryDirectory(prefix="wy_statute_pdf_") as td:
                pdf_path = Path(td) / "input.pdf"
                txt_path = Path(td) / "output.txt"
                pdf_path.write_bytes(payload)

                command = ["pdftotext"]
                if not self._full_corpus_enabled():
                    command.extend(["-f", "1", "-l", "3"])
                command.extend([str(pdf_path), str(txt_path)])

                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=180 if self._full_corpus_enabled() else 60,
                    check=False,
                )
                if proc.returncode != 0 or not txt_path.exists():
                    return ""

                raw = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", raw).strip()
                if max_chars is None:
                    max_chars = 250000 if self._full_corpus_enabled() else 6000
                return text[: int(max_chars)]
        except Exception as e:
            self.logger.debug(f"Wyoming PDF text extraction failed for {pdf_url}: {e}")
            return ""

    async def _extract_pdf_text_layout(self, pdf_url: str, max_chars: Optional[int] = None) -> str:
        """Extract layout-preserving PDF text so section headers survive splitting."""
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                pdf_url,
                timeout_seconds=45,
            )
            if not payload:
                return ""

            with tempfile.TemporaryDirectory(prefix="wy_statute_pdf_layout_") as td:
                pdf_path = Path(td) / "input.pdf"
                txt_path = Path(td) / "output.txt"
                pdf_path.write_bytes(payload)

                command = ["pdftotext", "-layout"]
                if not self._full_corpus_enabled():
                    command.extend(["-f", "1", "-l", "12"])
                command.extend([str(pdf_path), str(txt_path)])

                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=300 if self._full_corpus_enabled() else 90,
                    check=False,
                )
                if proc.returncode != 0 or not txt_path.exists():
                    return ""

                raw = txt_path.read_text(encoding="utf-8", errors="ignore")
                if max_chars is None:
                    max_chars = 900000 if self._full_corpus_enabled() else 90000
                return raw[: int(max_chars)]
        except Exception as e:
            self.logger.debug(f"Wyoming layout PDF extraction failed for {pdf_url}: {e}")
            return ""

    def _split_title_pdf_into_sections(
        self,
        *,
        code_name: str,
        title_number: str,
        title_name: str,
        title_text: str,
        source_url: str,
        citation_format: str,
    ) -> List[NormalizedStatute]:
        matches = list(self._SECTION_HEADER_RE.finditer(title_text or ""))
        if not matches:
            return []

        starts_by_section: dict[str, list[re.Match[str]]] = {}
        for match in matches:
            starts_by_section.setdefault(match.group(1), []).append(match)

        body_start = 0
        for match in matches:
            repeats = starts_by_section.get(match.group(1)) or []
            if len(repeats) >= 2:
                body_start = repeats[1].start()
                break

        body_matches = [match for match in matches if match.start() >= body_start] or matches

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for index, match in enumerate(body_matches):
            section_number = str(match.group(1) or "").strip()
            if not section_number or section_number in seen_sections:
                continue
            seen_sections.add(section_number)
            section_name = re.sub(r"\s+", " ", str(match.group(2) or "").strip()).strip(" .")
            end = body_matches[index + 1].start() if index + 1 < len(body_matches) else len(title_text)
            raw_block = title_text[match.start():end]
            normalized = self._normalize_legal_text(raw_block)
            if len(normalized) < 40:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:240] or f"Section {section_number}",
                    full_text=normalized[:24000],
                    legal_area=self._identify_legal_area(f"{title_name} {section_name}"),
                    source_url=source_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wyoming_title_pdf",
                        "discovery_method": "deterministic_title_pdf_catalog_sections",
                        "title_number": title_number,
                        "title_name": title_name,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_deterministic_title_pdfs(
        self,
        code_name: str,
        citation_format: str,
        max_sections: int,
    ) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        for section_number, section_name, full_url in self._build_deterministic_title_catalog()[:max_sections]:
            # Avoid the constitution pseudo-title for bounded health checks; the
            # full corpus run still includes it after statutory titles.
            if not self._full_corpus_enabled() and section_number in {"97", "99"}:
                continue
            layout_text = await self._extract_pdf_text_layout(full_url)
            split_sections = self._split_title_pdf_into_sections(
                code_name=code_name,
                title_number=section_number,
                title_name=section_name,
                title_text=layout_text,
                source_url=full_url,
                citation_format=citation_format,
            )
            for statute in split_sections:
                statutes.append(statute)
                if len(statutes) >= max_sections:
                    break
            if len(statutes) >= max_sections:
                break
            if split_sections:
                continue

            full_text = await self._extract_pdf_text_summary(full_url)
            if len(full_text.strip()) < 80:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wyoming_title_pdf",
                        "discovery_method": "deterministic_title_pdf_catalog",
                        "skip_hydrate": True,
                    },
                )
            )

        if statutes:
            self.logger.info(
                "Wyoming deterministic title PDF scraper: Scraped %s title PDFs",
                len(statutes),
            )
        return statutes
    
    async def _custom_scrape_wyoming(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Wyoming's legislative website.
        
        Wyoming's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative static pages
        3. Using Internet Archive snapshots
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []

        # Wyoming's statutes download page is JS-rendered, but title PDFs are
        # stable and predictable. Build that catalog directly as a non-JS fallback.
        deterministic_catalog = await self._scrape_deterministic_title_pdfs(
            code_name,
            citation_format,
            max_sections=max_sections,
        )
        if deterministic_catalog:
            return deterministic_catalog
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)

            soup = BeautifulSoup(page_bytes, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5:
                    continue
                
                # Wyoming patterns - relaxed matching
                keywords_wy = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'wyo.']
                if not any(keyword in link_text.lower() for keyword in keywords_wy):
                    continue
                
                full_url = urljoin(code_url, link_href)
                section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
                legal_area = self._identify_legal_area(link_text)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Wyoming custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Wyoming custom scraper found no data - site uses JavaScript")
                if PLAYWRIGHT_AVAILABLE:
                    self.logger.info("Wyoming custom scraper retrying with Playwright StatutesDownload page")
                    pw_statutes = await self._scrape_with_playwright(
                        code_name,
                        f"{self.get_base_url()}/stateStatutes/StatutesDownload",
                        citation_format,
                        max_sections=max_sections,
                    )
                    if pw_statutes:
                        return pw_statutes
                self.logger.info("For Wyoming, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering")
                self.logger.info("  2. Alternative URL: https://wyoleg.gov/statutes/compress/")
                self.logger.info("  3. Internet Archive snapshots")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Wyoming custom scraper failed: {e}")
            self.logger.info("Note: Wyoming's site requires JavaScript. Consider using Playwright.")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes

    def _build_deterministic_title_catalog(self) -> List[tuple[str, str, str]]:
        """Build stable Wyoming statutes title PDF URLs when JS links are unavailable."""
        catalog: List[tuple[str, str, str]] = []
        for title_num in range(1, 43):
            title_code = f"{title_num:02d}"
            section_number = str(title_num)
            section_name = f"Title {section_number}"
            pdf_url = f"{self.get_base_url()}/statutes/compress/title{title_code}.pdf"
            catalog.append((section_number, section_name, pdf_url))

        # Extra Wyoming title IDs exposed by the official download page.
        catalog.append(("34.1", "Title 34.1", f"{self.get_base_url()}/statutes/compress/title34.1.pdf"))
        catalog.append(("97", "Wyoming Constitution", f"{self.get_base_url()}/statutes/compress/title97.pdf"))
        catalog.append(("99", "Title 99", f"{self.get_base_url()}/statutes/compress/title99.pdf"))
        return catalog


# Register this scraper with the registry
StateScraperRegistry.register("WY", WyomingScraper)
