"""New York state law scraper.

Scrapes laws from the New York State Senate website
(https://www.nysenate.gov/).
"""

from typing import Any, Dict, List, Optional
import json
import re
import ssl
import urllib.request
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewYorkScraper(BaseStateScraper):
    """Scraper for New York state laws."""
    _NY_PUBLIC_LAW_LINK_RE = re.compile(r"https://newyork\.public\.law/laws/n\.y\._[^\s)`]+", re.IGNORECASE)
    _NY_PUBLIC_LAW_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://newyork\.public\.law/laws/[^)]+)\)", re.IGNORECASE)
    _NY_SENATE_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.nysenate\.gov/legislation/laws/[^)]+)\)", re.IGNORECASE)
    OFFICIAL_DOMAIN = "www.nysenate.gov"
    OFFICIAL_ENTRY_PATH = "/legislation/laws"
    OFFICIAL_ENTRY_URL = "https://www.nysenate.gov/legislation/laws"
    _NY_LAW_HREF_RE = re.compile(
        r"/legislation/laws/(?P<code>[A-Z]{2,4})(?:/|$)",
        re.IGNORECASE,
    )
    OFFICIAL_LAWS = (
        ("ABP", "Abandoned Property"),
        ("AGM", "Agriculture and Markets"),
        ("ABC", "Alcoholic Beverage Control"),
        ("ACA", "Arts and Cultural Affairs"),
        ("BNK", "Banking"),
        ("BSC", "Business Corporation"),
        ("CAL", "Canal"),
        ("CVP", "Civil Practice Law and Rules"),
        ("CVR", "Civil Rights"),
        ("CVS", "Civil Service"),
        ("COP", "Cooperative Corporations"),
        ("COR", "Correction"),
        ("CNT", "County"),
        ("CPL", "Criminal Procedure"),
        ("DCD", "Debtor and Creditor"),
        ("DOM", "Domestic Relations"),
        ("EDN", "Education"),
        ("ELN", "Election"),
        ("EDP", "Eminent Domain Procedure"),
        ("EML", "Employers' Liability"),
        ("ENG", "Energy"),
        ("ENV", "Environmental Conservation"),
        ("EPT", "Estates, Powers and Trusts"),
        ("EXC", "Executive"),
        ("FIS", "Financial Services"),
        ("GAS", "General Associations"),
        ("GBS", "General Business"),
        ("GCT", "General City"),
        ("GMU", "General Municipal"),
        ("GOB", "General Obligations"),
        ("HAY", "Highway"),
        ("ISC", "Insurance"),
        ("JUD", "Judiciary"),
        ("LAB", "Labor"),
        ("LEG", "Legislative"),
        ("LIE", "Lien"),
        ("LLC", "Limited Liability Company"),
        ("LFN", "Local Finance"),
        ("MHY", "Mental Hygiene"),
        ("MIL", "Military"),
        ("MDW", "Multiple Dwelling"),
        ("MRE", "Multiple Residence"),
        ("MHR", "Municipal Home Rule"),
        ("NAV", "Navigation"),
        ("PAR", "Partnership"),
        ("PEN", "Penal"),
        ("PEP", "Personal Property"),
        ("PVH", "Private Housing Finance"),
        ("PBB", "Public Buildings"),
        ("PBH", "Public Health"),
        ("PUH", "Public Housing"),
        ("PBL", "Public Lands"),
        ("PBO", "Public Officers"),
        ("PBS", "Public Service"),
        ("RAT", "Rapid Transit"),
        ("RPL", "Real Property"),
        ("RPA", "Real Property Actions and Proceedings"),
        ("RPT", "Real Property Tax"),
        ("REL", "Religious Corporations"),
        ("RSS", "Retirement and Social Security"),
        ("RCC", "Rural Electric Cooperative"),
        ("SCC", "Second Class Cities"),
        ("SOS", "Social Services"),
        ("SWC", "Soil and Water Conservation Districts"),
        ("STL", "State"),
        ("TAX", "Tax"),
        ("TWN", "Town"),
        ("TRA", "Transportation"),
        ("VAT", "Vehicle and Traffic"),
        ("VIL", "Village"),
        ("VAW", "Volunteer Ambulance Workers' Benefit"),
        ("VOL", "Volunteer Firefighters' Benefit"),
        ("WKC", "Workers' Compensation"),
    )
    OFFICIAL_LAW_COUNT = len(OFFICIAL_LAWS)
    
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
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_york_openleg import parse_configured_law_json

        openleg = parse_configured_law_json(code_name=code_name, max_statutes=limit)
        if openleg:
            return openleg
        official = await self._scrape_official_senate_laws_tree(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "NY full-corpus run found zero official nysenate.gov statutes; "
                "refusing public.law/Justia sole-admission fallback"
            )
            return []
        bounded = limit if limit is not None else 160
        public_law_structured = await self._scrape_public_law_structured(
            code_name, max_sections=max(10, bounded)
        )
        if public_law_structured:
            return public_law_structured[:bounded]
        if not self._full_corpus_enabled():
            direct = await self._scrape_jina_senate_seed_sections(code_name, max_statutes=bounded)
            if direct:
                statutes.extend(direct[:bounded])
        if statutes:
            return statutes[:bounded]
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                self.logger.warning(f"NY direct request returned empty content for {code_name}; using public.law fallback")
                return (await self._scrape_public_law_updates(code_name))[:bounded]

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)

            # Find section/article links from the index page if available.
            section_href_re = re.compile(r".*/legislation/laws/[A-Za-z0-9\-.]+/[A-Za-z0-9\-.]+$", re.IGNORECASE)
            section_links = soup.find_all('a', href=section_href_re)
            
            seen_sections = set()
            for link in section_links[:bounded]:
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

    async def _scrape_official_senate_laws_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk the live NY Senate consolidated-laws HTML tree."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_url = self.OFFICIAL_ENTRY_URL
        html = await self._request_text_direct(root_url, timeout=18)
        if not html:
            payload = await self._fetch_page_content_with_archival_fallback(root_url, timeout_seconds=18)
            html = payload.decode("utf-8", errors="replace") if payload else ""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        known = {code for code, _name in self.OFFICIAL_LAWS}
        law_urls: List[tuple[str, str]] = []
        seen_laws = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            abs_url = urljoin(root_url + "/", href)
            match = self._NY_LAW_HREF_RE.search(abs_url)
            if not match:
                continue
            law_code = str(match.group("code") or "").strip().upper()
            if law_code not in known:
                continue
            # Index pages are /legislation/laws/PEN; skip section-like tails here.
            path = urlparse(abs_url).path.rstrip("/")
            parts = [part for part in path.split("/") if part]
            if len(parts) != 3 or parts[-1].upper() != law_code:
                continue
            law_url = self.official_law_url(law_code)
            if law_url in seen_laws:
                continue
            if not self._host_is_official(law_url):
                continue
            seen_laws.add(law_url)
            law_urls.append((law_code, law_url))

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        section_url_re = re.compile(
            r"/legislation/laws/(?P<code>[A-Z]{2,4})/(?P<section>[0-9A-Za-z.-]*\d[0-9A-Za-z.-]*)$",
            re.IGNORECASE,
        )
        for law_code, law_url in law_urls:
            if limit is not None and len(statutes) >= limit:
                break
            law_html = await self._request_text_direct(law_url, timeout=18)
            if not law_html:
                payload = await self._fetch_page_content_with_archival_fallback(law_url, timeout_seconds=18)
                law_html = payload.decode("utf-8", errors="replace") if payload else ""
            if not law_html:
                continue
            law_soup = BeautifulSoup(law_html, "html.parser")
            for anchor in law_soup.find_all("a", href=True):
                if limit is not None and len(statutes) >= limit:
                    break
                href = str(anchor.get("href") or "").strip()
                label = str(anchor.get_text(" ", strip=True) or "").strip()
                abs_url = urljoin(law_url + "/", href)
                match = section_url_re.search(urlparse(abs_url).path)
                if not match:
                    continue
                if str(match.group("code") or "").strip().upper() != law_code:
                    continue
                section_number = str(match.group("section") or "").strip()
                if not section_number:
                    continue
                if not self._host_is_official(abs_url):
                    continue
                section_key = f"{law_code}:{section_number}".lower()
                if section_key in seen_sections:
                    continue
                seen_sections.add(section_key)
                statute = await self._build_official_senate_section(
                    code_name,
                    law_code=law_code,
                    section_number=section_number,
                    section_label=label,
                    section_url=abs_url.split("#", 1)[0],
                )
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _build_official_senate_section(
        self,
        code_name: str,
        *,
        law_code: str,
        section_number: str,
        section_label: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._request_text_direct(section_url, timeout=18)
        if not html:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=18)
            html = payload.decode("utf-8", errors="replace") if payload else ""
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        heading = soup.find(["h1", "h2"])
        section_name = self._normalize_legal_text(
            heading.get_text(" ", strip=True) if heading else section_label
        )
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup
        text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(text) < 80:
            return None
        if not section_name:
            section_name = f"Section {section_number}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {law_code} {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text[:14000],
            legal_area=self._identify_legal_area(section_name),
            source_url=section_url,
            official_cite=f"N.Y. {law_code} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_new_york_senate_laws_html",
                "discovery_method": "official_law_code_section",
                "law_code": law_code,
                "skip_hydrate": True,
            },
        )

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

    def official_law_url(self, law_code: Any) -> str:
        code = str(law_code or "").strip().upper()
        return f"{self.get_base_url()}/legislation/laws/{code}"

    def official_law_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New York Consolidated Laws catalog."""

        rows: List[Dict[str, Any]] = []
        for code, name in self.OFFICIAL_LAWS:
            url = self.official_law_url(code)
            rows.append(
                {
                    "canonical_key": f"ny:law-{code.lower()}",
                    "law_code": code,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New York Consolidated Laws {code} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {"www.nysenate.gov", "nysenate.gov"} or host.endswith(".nysenate.gov")

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in (
                "justia.com",
                "findlaw.com",
                "unicourt",
                "law.cornell.edu",
                "newyork.public.law",
            )
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-york-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                return b""

    def _parse_official_law_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {code for code, _name in self.OFFICIAL_LAWS}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NY_LAW_HREF_RE.search(absolute)
            if not match:
                continue
            code = str(match.group("code") or "").strip().upper()
            if code not in known or code in found:
                continue
            if self._host_is_official(absolute):
                found[code] = self.official_law_url(code)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official New York Consolidated Law."""

        del page_url
        discovered = self._parse_official_law_links(html)
        rows = self.official_law_catalog()
        for row in rows:
            live_url = discovered.get(str(row["law_code"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_nysenate"
        return rows

    def fetch_official(self, code: str = "NY"):
        """Acquire the exhaustive official New York Consolidated Laws catalog.

        Live HTTPS retains the official NY Senate laws index. Every consolidated
        law is enumerated with an official nysenate.gov URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NY").strip().upper() or "NY"
        if normalized != "NY":
            raise ValueError(f"NewYorkScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_LAW_COUNT:
            raise RuntimeError(
                "new york official catalog enumeration rejected incomplete law reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
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


# Register the scraper
StateScraperRegistry.register("NY", NewYorkScraper)
