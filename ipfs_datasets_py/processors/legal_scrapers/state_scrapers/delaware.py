"""Scraper for Delaware state laws.

Delaware Code Online uses heavy JavaScript rendering.
"""

from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from ...playwright_limiter import acquire_playwright_slot

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class DelawareScraper(BaseStateScraper):
    """Scraper for Delaware state laws from https://delcode.delaware.gov
    
    NOTE: Delaware's website is heavily JavaScript-rendered.
    This scraper requires Playwright or returns limited results.
    """

    _DE_CHAPTER_URL_RE = re.compile(r"/title\d+/c\d+/index\.html$", re.IGNORECASE)
    _DE_TITLE_URL_RE = re.compile(r"/title\d+/index\.html$", re.IGNORECASE)
    _DE_TITLE_NUMBER_RE = re.compile(r"/title(\d+)/", re.IGNORECASE)
    _DE_CHAPTER_NUMBER_RE = re.compile(r"/c(\d+)/", re.IGNORECASE)
    _DE_SECTION_HEAD_RE = re.compile(r"§\s*([0-9A-Za-z\-]+)\.\s*(.+)", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            name = str(statute.section_name or "")
            source = str(statute.source_url or "")
            if source.lower().endswith('.pdf'):
                continue
            # Accept real section captures and skip title-level landing pages.
            if re.search(r"§\s*\d", name, re.IGNORECASE) or re.search(r"\b\d+\.[0-9A-Za-z\-]*", name):
                filtered.append(statute)
                continue
            if re.search(r"#\d+[A-Za-z\-]*$", source):
                filtered.append(statute)
                continue
            if self._DE_CHAPTER_URL_RE.search(source) and re.search(r"^Chapter\s+\d+", name, re.IGNORECASE):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(r"Chapter\s+(\d+[A-Za-z\-]*)", name, re.IGNORECASE)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
                continue
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Delaware's legislative website."""
        return "https://delcode.delaware.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Delaware."""
        return [{
            "name": "Delaware Code",
            "url": f"{self.get_base_url()}/index.html",
            "type": "Code"
        }]
    
    async def _fetch_official_de_html(self, url: str, timeout_seconds: int = 6) -> str:
        timeout = max(1, int(timeout_seconds or 6))

        def _request() -> str:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-delaware-code-scraper/2.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return ""
                return bytes(response.content or b"").decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            html = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            html = ""
        self._record_fetch_event(provider="requests_direct", success=bool(html))
        return html

    def _title_number_from_url(self, url: str) -> str:
        match = self._DE_TITLE_NUMBER_RE.search(str(url or ""))
        return match.group(1) if match else ""

    def _chapter_number_from_url(self, url: str) -> str:
        match = self._DE_CHAPTER_NUMBER_RE.search(str(url or ""))
        if not match:
            return ""
        value = match.group(1).lstrip("0")
        return value or "0"

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/index.html"
        html = await self._fetch_official_de_html(index_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._DE_TITLE_URL_RE.search(href):
                continue
            if not label.lower().startswith("title "):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append((href, label))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_de_html(title_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._DE_CHAPTER_URL_RE.search(href):
                continue
            if not label.lower().startswith("chapter "):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append((href, label))
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_de_html(chapter_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")

        title_number = self._title_number_from_url(chapter_url)
        chapter_number = self._chapter_number_from_url(chapter_url)
        title_head = soup.select_one("#TitleHead")
        title_name = ""
        if title_head is not None:
            headings = [re.sub(r"\s+", " ", h.get_text(" ", strip=True) or "").strip() for h in title_head.find_all(["h1", "h2", "h3", "h4"])]
            title_name = " ".join([h for h in headings if h and not h.upper().startswith("TITLE ") and not h.upper().startswith("CHAPTER ")])[:200]

        statutes: List[NormalizedStatute] = []
        for section in soup.select("div.Section"):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            head = section.select_one(".SectionHead")
            if head is None:
                continue
            head_text = re.sub(r"\s+", " ", head.get_text(" ", strip=True) or "").strip()
            match = self._DE_SECTION_HEAD_RE.search(head_text)
            if not match:
                continue
            section_number = match.group(1).strip()
            section_name = match.group(2).strip()
            section_id = str(head.get("id") or section_number).strip()
            full_url = f"{chapter_url}#{section_id}"
            full_text = self._normalize_legal_text(section.get_text(" ", strip=True))
            if len(full_text) < 80:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"DE-{title_number}-{section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name or None,
                    chapter_number=chapter_number,
                    chapter_name=chapter_label,
                    section_number=section_number,
                    section_name=section_name[:200],
                    short_title=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=full_url,
                    official_cite=f"{title_number} Del. C. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_delaware_code_html",
                        "discovery_method": "official_title_chapter_index",
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )

        return statutes

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape Delaware Code.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []
        title_links = await self._discover_title_links()
        if not title_links and self._DE_CHAPTER_URL_RE.search(str(code_url or "")):
            title_links = [(urljoin(code_url, "../../index.html"), "")]

        for title_url, _title_label in title_links:
            if limit is not None and len(statutes) >= limit:
                break
            for chapter_url, chapter_label in await self._discover_chapter_links(title_url):
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                statutes.extend(
                    await self._parse_chapter_sections(
                        code_name=code_name,
                        chapter_url=chapter_url,
                        chapter_label=chapter_label,
                        max_statutes=remaining,
                    )
                )

        return statutes[:limit] if limit is not None else statutes
    
    async def _scrape_with_playwright(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 120
    ) -> List[NormalizedStatute]:
        """Scrape Delaware using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        async with acquire_playwright_slot():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    self.logger.info(f"Delaware: Loading {code_url}")
                    await page.goto(code_url, wait_until='networkidle', timeout=60000)
                    await page.wait_for_selector('a[href*="title"], div.title-links', timeout=10000)

                    content = await page.content()
                    soup = BeautifulSoup(content, 'html.parser')

                    links = soup.find_all('a', href=True)
                    title_links = [
                        l for l in links
                        if not l.get('href', '').lower().endswith('.pdf')
                        and (
                            self._DE_CHAPTER_URL_RE.search(l.get('href', ''))
                            or '§' in l.get_text(strip=True)
                            or re.search(r"\b\d+\.[0-9A-Za-z\-]*", l.get_text(strip=True))
                        )
                    ][:40]

                    self.logger.info(f"Delaware: Found {len(title_links)} title links")

                    section_count = 0
                    for link in title_links:
                        if section_count >= max_sections:
                            break

                        link_text = link.get_text(strip=True)
                        link_href = link.get('href', '')

                        if len(link_text) < 3:
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
                            full_text=f"Title {section_number}: {link_text}",
                            legal_area=legal_area,
                            source_url=full_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata()
                        )

                        statutes.append(statute)
                        section_count += 1

                    self.logger.info(f"Delaware Playwright: Scraped {len(statutes)} sections")

                finally:
                    try:
                        await page.close()
                    finally:
                        await browser.close()
        
        return statutes
    
    async def _custom_scrape_delaware(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Delaware (basic fallback without Playwright)."""
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
                return []

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Delaware uses JavaScript rendering, so this will find few/no links
            links = soup.find_all('a', href=True)
            self.logger.info(f"Delaware: Found {len(links)} links (JS-rendered page - likely incomplete)")
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5 or link_href.endswith('.pdf'):
                    continue
                
                # Accept chapter/index and section-like entries, but skip PDFs.
                if link_href.lower().endswith('.pdf'):
                    continue
                is_candidate = bool(self._DE_CHAPTER_URL_RE.search(link_href)) or ('§' in link_text) or bool(re.search(r"\b\d+\.[0-9A-Za-z\-]*", link_text))
                if not is_candidate:
                    continue
                
                full_url = urljoin(code_url, link_href)
                
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = f"Section-{section_count + 1}"
                
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
            
            self.logger.info(f"Delaware custom scraper: Scraped {len(statutes)} sections (JavaScript rendering required for full results)")
            
        except Exception as e:
            self.logger.error(f"Delaware custom scraper failed: {e}")
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("DE", DelawareScraper)
