"""New York state law scraper.

Scrapes laws from the New York State Senate website
(https://www.nysenate.gov/).
"""

from typing import List, Dict, Optional
import re
import urllib.request
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewYorkScraper(BaseStateScraper):
    """Scraper for New York state laws."""
    _NY_PUBLIC_LAW_LINK_RE = re.compile(r"https://newyork\.public\.law/laws/n\.y\._[^\s)`]+", re.IGNORECASE)
    _NY_PUBLIC_LAW_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://newyork\.public\.law/laws/[^)]+)\)", re.IGNORECASE)
    _NY_SENATE_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.nysenate\.gov/legislation/laws/[^)]+)\)", re.IGNORECASE)
    
    def get_base_url(self) -> str:
        """Get base URL for NY Senate."""
        return "https://www.nysenate.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of New York consolidated law sources.

        In this environment, direct per-code NY Senate endpoints are often blocked.
        Use a single consolidated entry and let scrape_code choose the best source.
        """
        base_url = self.get_base_url()

        return [
            {
                "name": "New York Consolidated Laws",
                "url": f"{base_url}/legislation/laws",
                "type": "NY-LAWS",
            }
        ]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific New York law.
        
        Args:
            code_name: Name of the law
            code_url: URL to the law
            
        Returns:
            List of normalized statutes
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else self._bounded_return_threshold(160)
        public_law_structured = await self._scrape_public_law_structured(code_name, max_sections=max(10, limit))
        if public_law_structured:
            return public_law_structured[:limit]
        if not self._full_corpus_enabled():
            direct = await self._scrape_jina_senate_seed_sections(code_name, max_statutes=limit)
            if direct:
                statutes.extend(direct[:limit])
        if statutes:
            return statutes[:limit]
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                self.logger.warning(f"NY direct request returned empty content for {code_name}; using public.law fallback")
                return (await self._scrape_public_law_updates(code_name))[:limit]

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)

            # Find section/article links from the index page if available.
            section_href_re = re.compile(r".*/legislation/laws/[A-Za-z0-9\-.]+/[A-Za-z0-9\-.]+$", re.IGNORECASE)
            section_links = soup.find_all('a', href=section_href_re)
            
            seen_sections = set()
            for link in section_links[:limit]:
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    section_url = urljoin(code_url, section_url)
                
                # Extract section number
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    tail = section_url.rstrip('/').split('/')[-1]
                    section_number = tail if re.search(r"\d", tail) else ""
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=f"Section {section_number}: {section_text}",  # Added full_text
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"NY {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")

            if statutes:
                return statutes

            self.logger.warning("NY primary source returned no sections; using public.law fallback")
            return await self._scrape_public_law_updates(code_name)
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
            return await self._scrape_public_law_updates(code_name)

    async def _scrape_jina_senate_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            ("PEN 125.25", "https://www.nysenate.gov/legislation/laws/PEN/125.25"),
            ("CVP 101", "https://www.nysenate.gov/legislation/laws/CVP/101"),
        ]
        statutes: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{source_url}"
            text = await self._request_text_direct(reader_url, timeout=24)
            text = self._clean_jina_markdown(text)
            if len(text) < 280:
                continue
            title_match = re.search(r"§\s*([0-9A-Za-z.]+)\s+([^.\n]+)", text)
            display_section = title_match.group(1) if title_match else section_number
            section_name = title_match.group(2).strip() if title_match else section_number
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {display_section}",
                    code_name=code_name,
                    section_number=display_section,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_name),
                    official_cite=f"N.Y. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_nysenate_laws",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _clean_jina_markdown(self, text: str) -> str:
        value = str(text or "")
        marker = "Markdown Content:"
        if marker in value:
            value = value.split(marker, 1)[-1]
        value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"#+\s*", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    async def _request_text_direct(self, url: str, timeout: int = 24) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    async def _scrape_public_law_updates(
        self,
        code_name: str,
        max_sections: int = 120,
    ) -> List[NormalizedStatute]:
        """Fallback scraper using the newyork.public.law latest-updates index.

        This source is accessible in environments where NY Senate pages are blocked.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        base = "https://newyork.public.law"
        seed_pages = [
            f"{base}/laws/latest-updates",
            f"{base}/laws/latest-updates?page=2",
            f"{base}/laws/latest-updates?page=3",
            f"{base}/laws/latest-updates?page=4",
        ]

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        legal_area = self._identify_legal_area(code_name)
        section_url_re = re.compile(r"/laws/n\.y\._[a-z0-9_'.\-,]+_(section|article|title)_[a-z0-9\-.]+$", re.IGNORECASE)

        for page_url in seed_pages:
            if len(statutes) >= max_sections:
                break
            try:
                page_bytes = await self._fetch_page_content_with_archival_fallback(
                    page_url,
                    timeout_seconds=30,
                )
                if not page_bytes:
                    raise RuntimeError("empty response")
            except Exception as exc:
                self.logger.warning(f"NY fallback page failed {page_url}: {exc}")
                continue

            soup = BeautifulSoup(page_bytes, 'html.parser')
            for link in soup.find_all('a', href=True):
                if len(statutes) >= max_sections:
                    break

                href = link.get('href', '').strip()
                if not href:
                    continue

                full_url = urljoin(base, href)
                if full_url in seen_urls:
                    continue
                if not section_url_re.search(full_url):
                    continue
                seen_urls.add(full_url)

                link_text = link.get_text(' ', strip=True)
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    tail = full_url.rstrip('/').split('/')[-1]
                    # Keep the terminal identifier as a stable fallback.
                    section_number = re.sub(r"^.*_(section|article|title)_", "", tail, flags=re.IGNORECASE)

                section_name = link_text[:200] if link_text else f"Section {section_number}"
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name,
                        full_text=f"Section {section_number}: {section_name}",
                        source_url=full_url,
                        legal_area=legal_area,
                        official_cite=f"NY {code_name} § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info(f"NY fallback scraper collected {len(statutes)} sections")
        return statutes

    async def _scrape_public_law_structured(
        self,
        code_name: str,
        max_sections: int = 120,
    ) -> List[NormalizedStatute]:
        base = "https://newyork.public.law"
        legal_area = self._identify_legal_area(code_name)
        root_markdown = await self._request_text_direct(f"https://r.jina.ai/http://{base}/laws", timeout=30)
        if not root_markdown:
            return []

        law_links = self._extract_markdown_links(root_markdown, self._NY_PUBLIC_LAW_MARKDOWN_LINK_RE)
        if not law_links:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        for law_label, law_url in law_links:
            if len(statutes) >= max_sections:
                break
            if law_url.rstrip("/").endswith("/laws") or law_url.endswith("/latest-updates"):
                continue
            container_links = await self._crawl_public_law_sections(law_url, max_sections=max_sections * 2)
            for section_label, section_url in container_links:
                if len(statutes) >= max_sections:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_public_law_section_statute(
                    code_name,
                    law_label or code_name,
                    section_label,
                    section_url,
                    legal_area,
                )
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _crawl_public_law_sections(
        self,
        law_url: str,
        max_sections: int = 200,
    ) -> List[tuple[str, str]]:
        queue = [law_url]
        visited = set()
        sections: List[tuple[str, str]] = []
        seen_sections = set()

        while queue and len(sections) < max_sections:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            markdown = await self._request_text_direct(f"https://r.jina.ai/http://{current}", timeout=30)
            if not markdown:
                continue
            links = self._extract_markdown_links(markdown, self._NY_PUBLIC_LAW_MARKDOWN_LINK_RE)
            for label, url in links:
                if len(sections) >= max_sections:
                    break
                if "_section_" in url.lower():
                    if url not in seen_sections:
                        seen_sections.add(url)
                        sections.append((label, url))
                    continue
                if any(token in url.lower() for token in ["_article_", "_part_", "_title_"]) and url not in visited and url not in queue:
                    queue.append(url)
        return sections

    async def _build_public_law_section_statute(
        self,
        code_name: str,
        law_label: str,
        section_label: str,
        section_url: str,
        legal_area: str,
    ) -> Optional[NormalizedStatute]:
        markdown = await self._request_text_direct(f"https://r.jina.ai/http://{section_url}", timeout=30)
        markdown = self._clean_jina_markdown(markdown)
        if len(markdown) < 160:
            return None

        section_number = self._extract_section_number(section_label)
        if not section_number:
            tail = section_url.rstrip("/").split("/")[-1]
            section_number = re.sub(r"^.*_section_", "", tail, flags=re.IGNORECASE)

        section_name = str(section_label or "").strip()
        section_name = re.sub(r"^(SECTION|§)\s*", "", section_name, flags=re.IGNORECASE).strip()
        if section_number and section_name.lower().startswith(section_number.lower()):
            section_name = section_name[len(section_number):].strip(" -:\u00a0")
        if not section_name:
            heading_match = re.search(r"#\s+(.+)", markdown)
            section_name = heading_match.group(1).strip() if heading_match else f"Section {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=law_label or code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=markdown[:14000],
            source_url=section_url,
            legal_area=legal_area,
            official_cite=f"N.Y. {law_label or code_name} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "public_law_structured_markdown",
                "discovery_method": "public_law_hierarchical_crawl",
                "skip_hydrate": True,
            },
        )

    def _extract_markdown_links(self, markdown: str, pattern: re.Pattern) -> List[tuple[str, str]]:
        found: List[tuple[str, str]] = []
        seen = set()
        for label, url in pattern.findall(str(markdown or "")):
            clean_label = self._normalize_legal_text(label)
            clean_url = str(url or "").strip().rstrip("`")
            if not clean_url or clean_url in seen:
                continue
            seen.add(clean_url)
            found.append((clean_label, clean_url))
        return found


# Register the scraper
StateScraperRegistry.register("NY", NewYorkScraper)
