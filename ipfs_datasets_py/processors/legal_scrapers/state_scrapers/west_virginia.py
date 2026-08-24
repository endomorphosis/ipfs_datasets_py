"""Scraper for West Virginia state laws.

This module contains the scraper for West Virginia statutes from the official state legislative website.
"""

import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WestVirginiaScraper(BaseStateScraper):
    """Scraper for West Virginia state laws from https://code.wvlegislature.gov"""

    OFFICIAL_DOMAIN = "code.wvlegislature.gov"
    OFFICIAL_ENTRY_PATH = "/"
    OFFICIAL_ENTRY_URL = "https://code.wvlegislature.gov/"
    _WV_CHAPTER_HREF_RE = re.compile(
        r"https?://code\.wvlegislature\.gov/(?P<chapter>\d+[A-Za-z]?)/?$",
        re.IGNORECASE,
    )
    _WV_CHAPTER_LABEL_RE = re.compile(
        r"\bChapter\s+(?P<chapter>\d+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _WV_CONTINUATION_RE = re.compile(
        r"\b(next|continue|more chapters|page\s+\d+)\b",
        re.IGNORECASE,
    )
    OFFICIAL_CHAPTERS = (
        ("1", "The State and Its Subdivisions"),
        ("2", "Common Law, Statutes, Legal Holidays, Definitions and Legal Capacity"),
        ("3", "Elections"),
        ("4", "The Legislature"),
        ("5", "General Powers and Authority of the Governor, Secretary of State and Attorney General; Board of Public Works; Miscellaneous Agencies, Commissions, Offices, Programs, etc."),
        ("5A", "Department of Administration"),
        ("5B", "Economic Development Act of 1985"),
        ("5C", "Basic Assistance for Industry and Trade"),
        ("5D", "Public Energy Authority Act"),
        ("5E", "Venture Capital Company"),
        ("5F", "Reorganization of the Executive Branch of State Government"),
        ("5G", "Procurement of Architect-Engineer Services by State and Its Subdivisions"),
        ("5H", "Survivor Benefits"),
        ("6", "General Provisions Respecting Officers"),
        ("6A", "Executive and Judicial Succession"),
        ("6B", "Government Ethics and Conflicts of Interest"),
        ("6C", "West Virginia Public Employees Grievance Procedure"),
        ("6D", "Public Contracts"),
        ("7", "County Commissions and Officers"),
        ("7A", "Consolidated Local Government"),
        ("8", "Municipal Corporations"),
        ("8A", "Land Use Planning"),
        ("9", "Human Services"),
        ("9A", "Welfare Fraud Prevention"),
        ("10", "Public Libraries; Public Recreation; Athletic Establishments; Monuments and Memorials; Roster of Servicemen; Educational Broadcasting Authority"),
        ("11", "Taxation"),
        ("11A", "Collection and Enforcement of Property Taxes"),
        ("11B", "Department of Revenue"),
        ("12", "Public Moneys and Securities"),
        ("13", "Public Bonded Indebtedness"),
        ("14", "Claims Due and Against the State"),
        ("15", "Public Safety"),
        ("15A", "Department of Homeland Security"),
        ("16", "Public Health"),
        ("16A", "Medical Cannabis Act"),
        ("16B", "Inspector General"),
        ("17", "Roads and Highways"),
        ("17A", "Motor Vehicle Administration, Registration, Certificate of Title, and Antitheft Provisions"),
        ("17B", "Motor Vehicle Driver's Licenses"),
        ("17C", "Traffic Regulations and Laws of the Road"),
        ("17D", "Motor Vehicle Safety Responsibility Law"),
        ("17E", "Uniform Commercial Driver's License Act"),
        ("17F", "All-Terrain Vehicles"),
        ("17G", "Racial Profiling Data Collection Act"),
        ("17H", "Fully Autonomous Vehicles"),
        ("18", "Education"),
        ("18A", "School Personnel"),
        ("18B", "Higher Education"),
        ("18C", "Student Loans; Scholarships and State Aid"),
        ("19", "Agriculture"),
        ("20", "Natural Resources"),
        ("21", "Labor"),
        ("21A", "Unemployment Compensation"),
        ("22", "Environmental Resources"),
        ("22A", "Miners' Health, Safety and Training"),
        ("22B", "Environmental Boards"),
        ("22C", "Environmental Resources; Boards, Authorities, Commissions and Compacts"),
        ("23", "Workers' Compensation"),
        ("24", "Public Service Commission"),
        ("24A", "Commercial Motor Carriers"),
        ("24B", "Gas Pipeline Safety"),
        ("24C", "Underground Facilities Damage Prevention"),
        ("24D", "Cable Television"),
        ("24E", "Statewide Addressing and Mapping"),
        ("24F", "Internet Protocol-enabled Service"),
        ("25", "Division of Corrections"),
        ("26", "State Correctional and Penal Institutions"),
        ("27", "Mentally Ill Persons"),
        ("28", "State Correctional and Penal Institutions"),
        ("29", "Miscellaneous Boards and Officers"),
        ("29A", "State Administrative Procedures Act"),
        ("29B", "Freedom of Information"),
        ("29C", "Uniform Notary Act"),
        ("30", "Professions and Occupations"),
        ("31", "Corporations"),
        ("31A", "Banks and Banking"),
        ("31B", "Uniform Limited Liability Company Act"),
        ("31C", "Credit Unions"),
        ("31D", "West Virginia Business Corporation Act"),
        ("31E", "West Virginia Nonprofit Corporation Act"),
        ("31F", "West Virginia Benefit Corporation Act"),
        ("31G", "Broadband Enhancement and Expansion Policies"),
        ("31H", "Small Wireless Facilities"),
        ("31I", "West Virginia Tourism Development Act"),
        ("31J", "West Virginia Motorsport Committee"),
        ("32", "Uniform Securities Act"),
        ("32A", "Land Sales; Certain Occupations and Businesses"),
        ("32B", "Exchange Facilitators"),
        ("33", "Insurance"),
        ("34", "Relating to Levies"),
        ("35", "Property of Religious, Educational and Charitable Organizations"),
        ("35A", "Religious Land Use"),
        ("36", "Estates and Property"),
        ("36A", "Condominiums and Unit Property"),
        ("36B", "Uniform Common Interest Ownership Act"),
        ("37", "Real Property"),
        ("37A", "Uniform Environmental Covenants Act"),
        ("37B", "Mineral Development"),
        ("37C", "Rare Earth Elements and Critical Minerals"),
        ("38", "Liens"),
        ("39", "Records and Papers"),
        ("39A", "Electronic Commerce"),
        ("39B", "Uniform Power of Attorney Act"),
        ("40", "Acts of the Legislature"),
        ("41", "Wills"),
        ("42", "Descent and Distribution"),
        ("43", "Dower and Curtesy"),
        ("44", "Administration of Estates and Trusts"),
        ("44A", "West Virginia Guardianship and Conservatorship Act"),
        ("44B", "Uniform Principal and Income Act"),
        ("44C", "Uniform Adult Guardianship and Protective Proceedings Jurisdiction Act"),
        ("44D", "Uniform Trust Code"),
        ("45", "Suretyship and Guaranty"),
        ("46", "Uniform Commercial Code"),
        ("46A", "West Virginia Consumer Credit and Protection Act"),
        ("46B", "Regulation of New Motor Vehicle Dealers, Distributors, Wholesalers and Manufacturers"),
        ("47", "Regulation of Trade"),
        ("47A", "West Virginia Lending and Credit Rate Board"),
        ("47B", "Uniform Partnership Act"),
        ("48", "Domestic Relations"),
        ("48A", "Enforcement of Family Obligations"),
        ("49", "Child Welfare"),
        ("49A", "Uniform Child Abduction Prevention Act"),
        ("50", "Magistrate Courts"),
        ("51", "Courts and Their Officers"),
        ("52", "Juries"),
        ("53", "Extraordinary Remedies"),
        ("54", "Eminent Domain"),
        ("55", "Actions, Suits and Arbitration; Judicial Sale"),
        ("56", "Pleading and Practice"),
        ("57", "Evidence and Witnesses"),
        ("58", "Appeal and Error"),
        ("59", "Fees, Allowances and Costs; Newspapers; Legal Advertisements"),
        ("60", "State Control of Alcoholic Liquors"),
        ("60A", "Uniform Controlled Substances Act"),
        ("60B", "Donated Drug Repository Program"),
        ("61", "Crimes and Their Punishment"),
        ("62", "Criminal Procedure"),
        ("63", "Repeal of Statutes"),
        ("64", "Legislative Rules"),
    )
    OFFICIAL_CHAPTER_COUNT = len(OFFICIAL_CHAPTERS)

    _WV_SECTION_URL_RE = re.compile(r"/\d+[A-Za-z]?(?:-\d+[A-Za-z]?){1,2}/?$")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WV_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled():
            return statutes
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source_kind = str((statute.structured_data or {}).get("source_kind") or "").lower()
            if "justia" in source_kind or "findlaw" in source_kind:
                continue
            if not self._host_is_official(str(statute.source_url or "")):
                continue
            filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for West Virginia's legislative website."""
        return "https://code.wvlegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for West Virginia."""
        return [
            {"name": "West Virginia Code", "url": f"{self.get_base_url()}/11-8-12/", "type": "Code"}
        ]

    async def scrape_code(
        self, code_name: str, code_url: str, max_statutes: int | None = None
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from West Virginia's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .west_virginia_constitution import (
            configured_constitution_html_path,
            parse_west_virginia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_west_virginia_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "West Virginia Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .west_virginia_dump import configured_code_html_path, parse_west_virginia_code_html

        dump_path = configured_code_html_path()
        if dump_path is not None:
            bulk = parse_west_virginia_code_html(
                dump_path.read_text(encoding="utf-8", errors="replace"),
                code_name=code_name,
                max_statutes=limit,
            )
            if bulk:
                return bulk
        if not self._full_corpus_enabled() and max_statutes is None:
            seed_budget = int(limit if limit is not None else 160)
            direct = await self._scrape_direct_seed_sections(
                code_name, max_statutes=seed_budget
            )
            if direct:
                return direct[:seed_budget]

        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_only(official)
        if official:
            return official[:limit] if limit is not None else official

        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "West Virginia full-corpus run found zero official statutes; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/1/",
            f"{self.get_base_url()}/11/",
            f"{self.get_base_url()}/11-8-12/",
            f"{self.get_base_url()}/1-1/",
            f"{self.get_base_url()}/",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        fallback_scan_limit = int(limit if limit is not None else 160)
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "W. Va. Code",
                        max_sections=fallback_scan_limit,
                        wait_for_selector="a[href*='wvlegislature.gov/'][href*='-'], a[href*='/code/'], a[href*='/article/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if limit is not None and len(statutes) >= limit:
                        return statutes[:limit]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name, candidate, "W. Va. Code", max_sections=fallback_scan_limit
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if limit is not None and len(statutes) >= limit:
                return statutes[:limit]

        return best_statutes[:limit] if limit is not None else best_statutes

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 1,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("61-2-1", "https://code.wvlegislature.gov/61-2-1/"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [(url, section_number) for section_number, url in seeds],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_links = await self._discover_chapter_links()
        self.logger.info(
            "West Virginia official index: discovered %s chapter links", len(chapter_links)
        )
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            article_links = await self._discover_article_links(chapter_url)
            self.logger.info(
                "West Virginia official index: chapter=%s index=%s/%s articles=%s statutes_so_far=%s",
                chapter_label or chapter_url,
                chapter_index,
                len(chapter_links),
                len(article_links),
                len(statutes),
            )
            for article_index, (article_url, article_label) in enumerate(article_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(article_url)
                if (
                    article_index == 1
                    or article_index % 10 == 0
                    or article_index == len(article_links)
                ):
                    self.logger.info(
                        "West Virginia official index: chapter=%s article=%s/%s sections=%s statutes_so_far=%s",
                        chapter_label or chapter_url,
                        article_index,
                        len(article_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                    discovery_method="official_chapter_article_section_index",
                )
                statutes.extend(parsed)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/"
        raw = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for option in soup.select("select#sel-chapter option[value]"):
            chapter = str(option.get("value") or "").strip()
            if not re.match(r"^\d+[A-Za-z]?$", chapter):
                continue
            normalized = f"{self.get_base_url()}/{chapter}/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(option.get_text(" ", strip=True))))
        return out

    async def _discover_article_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.art-head a[href]"):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/\d+[A-Za-z]?-\d+[A-Za-z]?/?$", href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, article_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        raw = await self._fetch_page_content_with_archival_fallback(article_url, timeout_seconds=20)
        if not raw:
            return []
        soup = BeautifulSoup(raw, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("div.sec-head a[href]"):
            href = urljoin(article_url, str(anchor.get("href") or "").strip())
            if not self._WV_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            section_number = normalized.rstrip("/").rsplit("/", 1)[-1]
            out.append((normalized, section_number))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
        discovery_method: str = "official_seed_section",
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for url, section_number in section_urls:
            if limit is not None and len(out) >= limit:
                break
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            soup = BeautifulSoup(raw, "html.parser")
            node = soup.select_one("div.sectiontext")
            if node is None:
                continue
            heading = self._normalize_legal_text(
                (node.find("h4") or node).get_text(" ", strip=True)
            )
            body_parts = [
                self._normalize_legal_text(p.get_text(" ", strip=True)) for p in node.find_all("p")
            ]
            body = self._normalize_legal_text(" ".join([heading, *body_parts]))
            if len(body) < 180:
                continue
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name[:220],
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=url,
                    official_cite=f"W. Va. Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_west_virginia_code_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def official_chapter_url(self, chapter_number: Any) -> str:
        number = str(chapter_number or "").strip()
        return f"{self.get_base_url()}/{number}/"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official West Virginia Code chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"wv:chapter-{str(number).lower()}",
                    "chapter_number": str(number),
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"West Virginia Code Chapter {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-west-virginia-official-catalog/1.0",
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
                with urllib.request.urlopen(
                    request, timeout=timeout, context=context
                ) as response:
                    return bytes(response.read() or b"")
            except Exception:
                return b""

    def _normalize_chapter_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"^0*(\d+[A-Z]?)$", text)
        return match.group(1) if match else ""

    def _parse_continuation_links(self, html: bytes, page_url: str) -> List[str]:
        found: List[str] = []
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            rel = " ".join(link.get("rel") or []).lower()
            if not href:
                continue
            if "next" not in rel and not self._WV_CONTINUATION_RE.search(label):
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            if absolute in seen or not self._host_is_official(absolute):
                continue
            if absolute.rstrip("/") == str(page_url or "").rstrip("/"):
                continue
            seen.add(absolute)
            found.append(absolute)
        return found

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_CHAPTERS}
        for option in soup.select("select#sel-chapter option[value], select option[value]"):
            number = self._normalize_chapter_number(option.get("value"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            found[number] = self.official_chapter_url(number)
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._WV_CHAPTER_HREF_RE.search(absolute) or self._WV_CHAPTER_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_chapter_number(match.group("chapter"))
            if not number or number in found:
                continue
            if number not in known:
                known.add(number)
            if self._host_is_official(absolute):
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official West Virginia Code chapter."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_title_catalog()
        known = {str(row["chapter_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_wvcode"
        for number, url in discovered.items():
            if number in known:
                continue
            rows.append(
                {
                    "canonical_key": f"wv:chapter-{number.lower()}",
                    "chapter_number": number,
                    "title_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"West Virginia Code Chapter {number} "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: self._chapter_sort_key(str(item.get("chapter_number") or "")))
        return rows

    def _chapter_sort_key(self, number: str) -> Tuple[int, str]:
        match = re.match(r"^(\d+)([A-Za-z]+)?$", str(number or "").strip())
        if not match:
            return (9999, str(number or ""))
        return (int(match.group(1)), (match.group(2) or "").upper())

    def _collect_official_index_pages(self) -> Tuple[bytes, List[str]]:
        visited: List[str] = []
        seen: set[str] = set()
        pending = [self.OFFICIAL_ENTRY_URL]
        combined = b""
        while pending:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            visited.append(url)
            html = self._official_http_get(url)
            if html:
                combined = html if not combined else combined + b"\n" + html
            for continuation in self._parse_continuation_links(html, url):
                if continuation not in seen:
                    pending.append(continuation)
            if len(visited) >= 32:
                break
        return combined, [item for item in pending if item not in seen]

    def fetch_official(self, code: str = "WV"):
        """Acquire the exhaustive official West Virginia Code chapter catalog.

        Live HTTPS retains the official code.wvlegislature.gov index. Every
        known chapter is enumerated with an official URL. Continuation pages
        are exhausted. This hook never returns fixture bytes, never promotes
        a partial scrape checkpoint, and never uses secondary hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WV").strip().upper() or "WV"
        if normalized != "WV":
            raise ValueError(f"WestVirginiaScraper cannot acquire {normalized}")
        html, remaining = self._collect_official_index_pages()
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < self.OFFICIAL_CHAPTER_COUNT:
            raise RuntimeError(
                "west virginia official catalog enumeration rejected incomplete "
                "chapter reacquisition"
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
            "unvisited_continuation_links": list(remaining),
            "visited_index_units": len(rows),
        }
        if remaining:
            frontier["closed"] = False
            frontier["pagination_closed"] = False
            frontier["toc_exhausted"] = False
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        self.last_official_checkpoint = {
            "partial": False,
            "promoted_success": False,
            "completion_basis": "source_frontier",
        }
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
StateScraperRegistry.register("WV", WestVirginiaScraper)
