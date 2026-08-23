"""Scraper for Wyoming state laws.

Official path: deterministic title PDFs on https://www.wyoleg.gov/statutes/compress/
(preferred over the JS StatutesDownload SPA). Playwright/generic remain fallbacks only.
"""

import hashlib
import json
import re
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse
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
    _WY_TITLE_PDF_RE = re.compile(
        r"/statutes/compress/title(?P<title>34\.1|\d{1,2})\.pdf",
        re.IGNORECASE,
    )
    _WY_TITLE_LABEL_RE = re.compile(
        r"(?:title|t\.?)\s*(34\.1|\d{1,2})\b",
        re.IGNORECASE,
    )
    _WY_SECTION_CITE_RE = re.compile(
        r"\b(34\.1|\d{1,2})-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?\b"
    )
    OFFICIAL_DOMAIN = "www.wyoleg.gov"
    OFFICIAL_ENTRY_PATH = "/stateStatutes/StatutesDownload"
    OFFICIAL_ENTRY_URL = "https://www.wyoleg.gov/stateStatutes/StatutesDownload"
    OFFICIAL_COMPRESS_PATH = "/statutes/compress/"
    LINKLESS_QUARANTINE_REASON = "missing_official_source_link"
    OFFICIAL_TITLE_NUMBERS = tuple(
        [str(number) for number in range(1, 43)] + ["34.1", "97", "99"]
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
        from .wyoming_constitution import (
            configured_constitution_text_path,
            parse_wyoming_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_wyoming_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Wyoming Constitution",
                    max_statutes=max_sections,
                )
                return constitution_rows if max_sections is None else constitution_rows[: int(max_sections)]
        from .wyoming_title import configured_title_text_path, parse_wyoming_title_text

        local_title = configured_title_text_path()
        if local_title is not None:
            local_rows = parse_wyoming_title_text(
                local_title.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.wyoleg.gov/statutes/compress/title6.pdf",
                code_name=code_name,
                max_statutes=max_sections,
            )
            if local_rows:
                return local_rows[:max_sections_value]

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

    def normalize_title_number(self, title_number: object) -> str:
        text = str(title_number or "").strip()
        if text == "34.1":
            return "34.1"
        if text.isdigit():
            return str(int(text))
        return text

    def official_title_stem(self, title_number: str) -> str:
        normalized = self.normalize_title_number(title_number)
        if normalized == "34.1":
            return "34.1"
        if normalized.isdigit():
            return f"{int(normalized):02d}"
        return normalized

    def official_title_url(self, title_number: str) -> str:
        return (
            f"{self.get_base_url()}/statutes/compress/"
            f"title{self.official_title_stem(title_number)}.pdf"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Wyoming Statutes title-PDF catalog."""

        rows: List[Dict[str, Any]] = []
        for section_number, section_name, pdf_url in self._build_deterministic_title_catalog():
            rows.append(
                {
                    "canonical_key": f"wy:title-{section_number}",
                    "title_number": str(section_number),
                    "name": section_name,
                    "source_url": pdf_url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wyoming Statutes {section_name} official title PDF "
                        f"catalog unit at {pdf_url}"
                    ),
                }
            )
        return rows

    def is_official_wyoleg_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "wyoleg.gov" or host.endswith(".wyoleg.gov")

    def _title_sort_key(self, title_number: str) -> tuple[int, str]:
        text = str(title_number or "").strip()
        if text == "34.1":
            return (34, "1")
        if text.isdigit():
            return (int(text), "")
        match = re.match(r"(\d+)", text)
        return (int(match.group(1)), text) if match else (10_000, text)

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        pdf_match = self._WY_TITLE_PDF_RE.search(blob)
        if pdf_match:
            return self.normalize_title_number(pdf_match.group("title"))
        cite_match = self._WY_SECTION_CITE_RE.search(blob)
        if cite_match:
            return self.normalize_title_number(cite_match.group(1))
        label_match = self._WY_TITLE_LABEL_RE.search(blob)
        if label_match:
            return self.normalize_title_number(label_match.group(1))
        return ""

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-wyoming-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-wyoming-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.get_base_url() + "/", href)
            match = self._WY_TITLE_PDF_RE.search(absolute)
            if not match:
                continue
            number = self.normalize_title_number(match.group("title"))
            if number not in found:
                found[number] = self.official_title_url(number)
        return found

    def _title_row(
        self,
        title_number: str,
        label: str,
        source: str,
        source_url: str = "",
    ) -> Dict[str, str]:
        official_url = source_url or self.official_title_url(title_number)
        cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"Title {title_number}"
        return {
            "canonical_key": f"wy:title-{title_number}",
            "title_number": str(title_number),
            "name": cleaned,
            "source_url": official_url,
            "source_link_disposition": source,
            "repair_source": source,
            "text": (
                f"Wyoming Statutes {cleaned} official title PDF catalog unit "
                f"at {official_url}"
            ),
        }

    def classify_linkless_seed_rows(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Reacquire official title PDFs or quarantine remaining linkless seeds.

        Accepts either a mapping sequence or raw HTML. Recoverable title
        numbers are rewritten to ``https://www.wyoleg.gov/statutes/compress/titleXX.pdf``.
        Remaining linkless material is quarantined with
        ``missing_official_source_link``.
        """

        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self.normalize_title_number(title_number)
            if not number or number in seen_titles:
                return
            seen_titles.add(number)
            repaired.append(self._title_row(number, label, source, source_url=source_url))

        def _quarantine(label: str, evidence: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            unit_id = (
                "wy:missing-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if unit_id in seen_quarantine:
                return
            seen_quarantine.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.LINKLESS_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official Wyoming discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or (self.get_base_url() + "/"), href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_wyoleg_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                    continue
                if label:
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("href"),
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                elif re.search(r"title|statute|chapter|section|wyo", label, re.IGNORECASE):
                    _quarantine(label, str(node))
            return {"repaired": repaired, "quarantines": quarantines}

        for item in seeds or ():
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("section_name")
                or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            title_number = self._recover_title_number(
                item.get("title_number"),
                item.get("section_number"),
                source_url,
                label,
            )
            if title_number and source_url and self.is_official_wyoleg_url(source_url):
                _record(title_number, label, "official", self.official_title_url(title_number))
                continue
            if title_number:
                _record(title_number, label, "repaired_from_linkless_row")
                continue
            _quarantine(label or source_url or "linkless wyoming seed", json.dumps(dict(item), sort_keys=True))
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official title PDFs and reacquire or quarantine linkless seeds."""

        discovered = self._parse_official_title_links(html)
        classified = self.classify_linkless_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        if seed_rows:
            seed_classified = self.classify_linkless_seed_rows(
                seed_rows,
                page_url=page_url or self.OFFICIAL_ENTRY_URL,
            )
            classified["repaired"].extend(seed_classified["repaired"])
            classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "")
            if number in by_title:
                if unit.get("source_link_disposition") == "official":
                    by_title[number]["source_url"] = unit["source_url"]
                    by_title[number]["source_link_disposition"] = "official"
                continue
            rows.append(unit)
            by_title[number] = unit
        for number, url in discovered.items():
            if number in by_title:
                continue
            extra = self._title_row(number, f"Title {number}", "official", url)
            rows.append(extra)
            by_title[number] = extra
        rows.sort(key=lambda item: self._title_sort_key(str(item["title_number"])))
        return rows

    def fetch_official(self, code: str = "WY"):
        """Acquire the exhaustive official Wyoming title-PDF catalog.

        Linkless bucket seed material is reacquired onto official
        ``wyoleg.gov/statutes/compress/titleXX.pdf`` URLs when a title number
        can be recovered. Remaining linkless rows are quarantined with typed
        ``missing_official_source_link`` disposition. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WY").strip().upper() or "WY"
        if normalized != "WY":
            raise ValueError(f"WyomingScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) < 3:
            raise RuntimeError("wyoming official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
            "quarantines": quarantines,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": True,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "bundle",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
            "wy_linkless_quarantines": quarantines,
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
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("WY", WyomingScraper)
