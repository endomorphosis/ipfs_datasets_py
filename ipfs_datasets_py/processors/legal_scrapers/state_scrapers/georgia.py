"""Scraper for Georgia state laws.

This module contains the scraper for Georgia statutes from the official state legislative website.
"""

import re
import subprocess
import tempfile
import os
from urllib.parse import urljoin
from typing import List, Dict, Optional

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from ...playwright_limiter import acquire_playwright_slot

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from http://www.legis.ga.gov"""

    _GA_JUSTIA_TITLE_RE = re.compile(r"/codes/georgia/(?:\d{4}/)?title-[^/]+/?$", re.IGNORECASE)
    _GA_JUSTIA_INTERMEDIATE_RE = re.compile(r"/codes/georgia/(?:\d{4}/)?title-[^/]+/(?!.*section-)[^?#]+/?$", re.IGNORECASE)
    _GA_JUSTIA_SECTION_RE = re.compile(r"/codes/georgia/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$", re.IGNORECASE)
    _GA_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            allow_justia_section = bool(self._GA_JUSTIA_SECTION_RE.search(url))
            allow_summary_pdf = url.endswith("25sumdoc.pdf") or "general-statutes-summary-pdf.pdf" in url
            if any(
                hint in url
                for hint in [
                    "dds.georgia.gov",
                    "dol.georgia.gov",
                    "lexisnexis.com/hottopics/gacode",
                ]
            ):
                continue
            if "temporary error. please try again" in text or "complete the security check before continuing" in text:
                continue
            if "law.justia.com" in url and not allow_justia_section:
                continue
            if "legis.ga.gov" in url and not allow_summary_pdf and "/api/document/docs/" not in url:
                continue
            out.append(statute)
        return out
    
    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "http://www.legis.ga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [{
            "name": "Official Code of Georgia",
            "url": f"{self.get_base_url()}/legislation/laws.html",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Georgia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            "https://www.legis.ga.gov/legislation/georgia-code",
            "https://law.justia.com/codes/georgia/",
        ]

        limit = self._effective_scrape_limit(max_statutes, default=60)
        return_threshold = limit if limit is not None else 1000000
        if return_threshold < 60:
            summary_pdf_statutes = await self._scrape_general_statute_summary_pdfs(code_name)
            if summary_pdf_statutes:
                return summary_pdf_statutes[:return_threshold]

        justia_statutes: List[NormalizedStatute] = []
        if self._env_enabled("GEORGIA_JUSTIA_ENABLE", default=False) or self._env_enabled(
            "LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL",
            default=False,
        ):
            justia_statutes = await self._scrape_justia_year(
                code_name,
                year="2024",
                max_statutes=max(10, return_threshold),
            )
            justia_statutes = self._filter_non_code_results(justia_statutes)
            if len(justia_statutes) >= return_threshold:
                return justia_statutes
        else:
            self.logger.warning(
                "Georgia Justia scrape disabled for bulk run; enable GEORGIA_JUSTIA_ENABLE=1 "
                "or LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL=1 to attempt Cloudflare/Common-Crawl recovery"
            )

        best_statutes: List[NormalizedStatute] = []
        if len(justia_statutes) > len(best_statutes):
            best_statutes = justia_statutes
        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if PLAYWRIGHT_AVAILABLE and self._env_enabled("GEORGIA_PLAYWRIGHT_ENABLE", default=False):
                self.logger.info("Georgia: Using Playwright for JavaScript rendering")
                try:
                    result = await self._scrape_with_playwright(code_name, candidate, "Ga. Code Ann.")
                    result = self._filter_non_code_results(result)
                    if len(result) > len(best_statutes):
                        best_statutes = result
                    if len(result) >= return_threshold:
                        return result[:return_threshold]
                except Exception as e:
                    self.logger.warning(f"Georgia Playwright failed: {e}, falling back")

            if self._env_enabled("GEORGIA_GENERIC_FALLBACK", default=False):
                generic = await self._custom_scrape_georgia(code_name, candidate, "Ga. Code Ann.")
                generic = self._filter_non_code_results(generic)
                if len(generic) > len(best_statutes):
                    best_statutes = generic
                if len(generic) >= return_threshold:
                    return generic[:return_threshold]

        if best_statutes:
            return best_statutes

        # Last resort: return summary records so the state is at least represented.
        summary_pdf_statutes = await self._scrape_general_statute_summary_pdfs(code_name)
        if summary_pdf_statutes:
            return summary_pdf_statutes[:return_threshold]

        return []

    @staticmethod
    def _env_enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    async def _scrape_justia_year(self, code_name: str, year: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        year_url = f"https://law.justia.com/codes/georgia/{year}/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(year_url, timeout_seconds=40)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        title_urls: List[str] = []
        seen_titles = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(year_url, str(anchor.get("href") or "").strip())
            if not self._GA_JUSTIA_TITLE_RE.search(href):
                continue
            if href in seen_titles:
                continue
            seen_titles.add(href)
            title_urls.append(href)
            if len(title_urls) >= 40:
                break

        section_urls: List[str] = []
        intermediate_urls: List[str] = []
        seen_intermediate = set()
        seen_sections = set()
        for title_url in title_urls:
            try:
                title_payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
            except Exception:
                continue
            if not title_payload:
                continue
            title_soup = BeautifulSoup(title_payload, "html.parser")
            for anchor in title_soup.find_all("a", href=True):
                href = urljoin(title_url, str(anchor.get("href") or "").strip())
                if not self._GA_JUSTIA_SECTION_RE.search(href):
                    if self._GA_JUSTIA_INTERMEDIATE_RE.search(href) and href not in seen_intermediate and href != title_url:
                        seen_intermediate.add(href)
                        intermediate_urls.append(href)
                    continue
                if href not in seen_sections:
                    seen_sections.add(href)
                    section_urls.append(href)
                if len(section_urls) >= max(1, int(max_statutes * 4)):
                    break
            if len(section_urls) >= max(1, int(max_statutes * 4)):
                break

        for page_url in intermediate_urls[: max(1, int(max_statutes * 2))]:
            try:
                page_payload = await self._fetch_page_content_with_archival_fallback(page_url, timeout_seconds=35)
            except Exception:
                continue
            if not page_payload:
                continue
            page_soup = BeautifulSoup(page_payload, "html.parser")
            for anchor in page_soup.find_all("a", href=True):
                href = urljoin(page_url, str(anchor.get("href") or "").strip())
                if not self._GA_JUSTIA_SECTION_RE.search(href):
                    continue
                if href in seen_sections:
                    continue
                seen_sections.add(href)
                section_urls.append(href)
                if len(section_urls) >= max(1, int(max_statutes * 4)):
                    break
            if len(section_urls) >= max(1, int(max_statutes * 4)):
                break

        statutes: List[NormalizedStatute] = []
        for index, section_url in enumerate(section_urls[: max(1, int(max_statutes * 4))], start=1):
            statute = await self._build_justia_statute(code_name=code_name, section_url=section_url, fallback_number=str(index))
            if statute is None:
                continue
            statutes.append(statute)
            if len(statutes) >= max_statutes:
                break

        return statutes

    async def _build_justia_statute(self, *, code_name: str, section_url: str, fallback_number: str) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
        except Exception:
            return None
        if not payload:
            return None

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if content_node is None:
            return None

        full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer:\b", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) < 280:
            return None

        heading_node = soup.select_one("h1") or soup.select_one("title")
        heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
        match = self._GA_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or f"Georgia Code {section_number}")[:200],
            full_text=full_text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Ga. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
        )

    async def _scrape_general_statute_summary_pdfs(self, code_name: str) -> List[NormalizedStatute]:
        """Use official GA-hosted General Statutes summary PDFs as strict-safe fallback."""
        candidate_docs = [
            (
                "2025",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/25sumdoc.pdf?sfvrsn=95973fc9_4",
            ),
            (
                "2024",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/2024-general-statutes-summary-pdf.pdf?sfvrsn=38862f9_8",
            ),
        ]

        statutes: List[NormalizedStatute] = []
        for year, pdf_url in candidate_docs:
            text = ""
            for _ in range(2):
                text = await self._extract_pdf_text_summary(pdf_url)
                if len(text) >= 280:
                    break
            if len(text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § Summary-{year}",
                code_name=code_name,
                section_number=year,
                section_name=f"Summary of {year} General Statutes",
                full_text=text,
                legal_area="general",
                source_url=pdf_url,
                official_cite=f"Ga. Gen. Stat. Summary ({year})",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_summary_pdf",
                    "skip_hydrate": True,
                    "coverage_note": "summary_fallback_not_full_code_corpus",
                },
            )
            statutes.append(statute)

        if statutes:
            self.logger.info(f"Georgia summary PDF fallback: Scraped {len(statutes)} records")
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 12000) -> str:
        """Download PDF and extract normalized text via pdftotext."""
        try:
            payload = await self._fetch_pdf_bytes_direct(pdf_url, timeout_seconds=45)
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug(f"Georgia PDF download failed for {pdf_url}: {exc}")
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="ga_sum_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "summary.pdf"
                txt_path = Path(tmpdir) / "summary.txt"
                pdf_path.write_bytes(payload)

                result = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "12", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except Exception as exc:
            self.logger.debug(f"Georgia PDF extraction failed for {pdf_url}: {exc}")
            return ""

    async def _fetch_pdf_bytes_direct(self, url: str, timeout_seconds: int = 45) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        timeout = max(5, int(timeout_seconds or 45))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-georgia-code-scraper/2.0",
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                    timeout=(min(10, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                payload = bytes(response.content or b"")
                if not payload.startswith(b"%PDF"):
                    return b""
                return payload
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 140
    ) -> List[NormalizedStatute]:
        """Scrape Georgia using Playwright for JavaScript rendering."""
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
                    for link in links:
                        if section_count >= max_sections:
                            break

                        link_text = link.get_text(strip=True)
                        link_href = link.get('href', '')

                        if len(link_text) < 5:
                            continue

                        keywords = ['title', 'chapter', 'code', 'statute']
                        if not any(k in link_text.lower() for k in keywords):
                            continue

                        full_url = urljoin(code_url, link_href)
                        section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"

                        statute = NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § {section_number}",
                            code_name=code_name,
                            section_number=section_number,
                            section_name=link_text[:200],
                            full_text=f"Section {section_number}: {link_text}",
                            legal_area=self._identify_legal_area(link_text),
                            source_url=full_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata()
                        )

                        statutes.append(statute)
                        section_count += 1

                    self.logger.info(f"Georgia Playwright: Scraped {len(statutes)} sections")

                finally:
                    try:
                        await page.close()
                    finally:
                        await browser.close()
        
        return statutes
    
    async def _custom_scrape_georgia(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 320
    ) -> List[NormalizedStatute]:
        """Custom scraper for Georgia's legislative website.
        
        Georgia's website is a JavaScript SPA (Single Page Application).
        For better results, consider:
        1. Using Playwright to render JavaScript
        2. Accessing alternative sources like LexisNexis or Internet Archive
        3. Using the Georgia Code API if available
        """
        # Try alternative URLs first
        alternative_urls = [
            "https://advance.lexis.com/container?config=014CJAAyZGVmYXVsdHM6OTU5ZDJjOGYtMGZjMC00MGI0LWIzYzEtNmVhYTZmYzJmY2RhKgxYmRQzkSm9zOIGXjY8",  # LexisNexis
            "http://web.archive.org/web/*/www.legis.ga.gov/legislation/laws.html"  # Internet Archive
        ]
        
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                raise RuntimeError(f"empty response for {code_url}")

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
                
                # Georgia Code patterns - relaxed matching
                keywords_ga = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'ga.']
                if not any(keyword in link_text.lower() for keyword in keywords_ga):
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
            
            self.logger.info(f"Georgia custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.warning("Georgia custom scraper found no data - site uses JavaScript")
                self.logger.info("For Georgia, consider using:")
                self.logger.info("  1. Playwright for JavaScript rendering: pip install playwright && playwright install")
                self.logger.info("  2. Alternative source: Internet Archive")
                self.logger.info("  3. API access if available from GA General Assembly")
                if self._env_enabled("GEORGIA_GENERIC_FALLBACK", default=False):
                    return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
                return []
            
        except Exception as e:
            self.logger.error(f"Georgia custom scraper failed: {e}")
            self.logger.info("Note: Georgia's site requires JavaScript. Consider using Playwright.")
            if self._env_enabled("GEORGIA_GENERIC_FALLBACK", default=False):
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            return []
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("GA", GeorgiaScraper)
