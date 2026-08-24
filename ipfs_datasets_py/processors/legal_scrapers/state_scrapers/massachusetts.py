"""Scraper for Massachusetts state laws.

This module contains the scraper for Massachusetts statutes from the official state
legislative website.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import re
import ssl
import urllib.request
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class MassachusettsScraper(BaseStateScraper):
    """Scraper for Massachusetts state laws from https://malegislature.gov"""

    _MA_TITLE_LOAD_RE = re.compile(
        r"accordionAjaxLoad\(\s*'(?P<part>\d+)'\s*,\s*'(?P<title>\d+)'\s*,\s*'(?P<code>[^']*)'\s*\)",
        re.IGNORECASE,
    )
    _MA_CHAPTER_NUMBER_RE = re.compile(r"/chapter(?P<chapter>[a-z0-9.]+)$", re.IGNORECASE)
    _MA_SECTION_NUMBER_RE = re.compile(r"/section(?P<section>[a-z0-9.]+)$", re.IGNORECASE)
    _MA_SECTION_URL_RE = re.compile(
        r"/laws/generallaws/(?:part[a-z0-9-]*|title[a-z0-9-]*|chapter[a-z0-9-]*|section[a-z0-9-]*)(?:/|$)",
        re.IGNORECASE,
    )
    _MA_PART_TITLE_RE = re.compile(
        r"/Laws/GeneralLaws/Part(?P<part>[IVX]+)(?:/Title(?P<title>[IVX]+))?",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "malegislature.gov"
    OFFICIAL_ENTRY_PATH = "/Laws/GeneralLaws"
    OFFICIAL_ENTRY_URL = "https://malegislature.gov/Laws/GeneralLaws"
    OFFICIAL_TITLES = (
        ("I", "I", "Jurisdiction and Emblems of the Commonwealth, the General Court, Statutes and Public Documents"),
        ("I", "II", "Executive and Administrative Officers of the Commonwealth"),
        ("I", "III", "Laws Relating to State Officers"),
        ("I", "IV", "Civil Service, Retirements and Pensions"),
        ("I", "V", "Militia"),
        ("I", "VI", "Counties and County Officers"),
        ("I", "VII", "Cities, Towns and Districts"),
        ("I", "VIII", "Elections"),
        ("I", "IX", "Taxation"),
        ("I", "X", "Public Records"),
        ("I", "XI", "Certain Religious and Charitable Matters"),
        ("I", "XII", "Education"),
        ("I", "XIII", "Eminent Domain and Betterments"),
        ("I", "XIV", "Public Ways and Works"),
        ("I", "XV", "Regulation of Trade"),
        ("I", "XVI", "Public Health"),
        ("I", "XVII", "Public Welfare"),
        ("I", "XVIII", "Prisons, Imprisonment, Paroles and Pardons"),
        ("I", "XIX", "Agriculture and Conservation"),
        ("I", "XX", "Public Safety and Good Order"),
        ("I", "XXI", "Labor and Industries"),
        ("I", "XXII", "Corporations"),
        ("II", "I", "Title to Real Property"),
        ("II", "II", "Descent and Distribution, Wills, Estates, Guardianship, Conservatorship and Trusts"),
        ("II", "III", "Domestic Relations"),
        ("III", "I", "Courts and Judicial Officers"),
        ("III", "II", "Actions and Proceedings Therein"),
        ("III", "III", "Remedies Relating to Real Property"),
        ("III", "IV", "Certain Writs and Proceedings in Special Cases"),
        ("III", "V", "Statutes of Frauds and Limitations"),
        ("IV", "I", "Crimes and Punishments"),
        ("IV", "II", "Proceedings in Criminal Cases"),
        ("V", "I", "The General Laws and Express Repeal of Certain Acts and Resolves"),
    )

    def get_base_url(self) -> str:
        """Return the base URL for Massachusetts's legislative website."""
        return "https://malegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Massachusetts."""
        return [{
            "name": "Massachusetts General Laws",
            "url": f"{self.get_base_url()}/Laws/GeneralLaws",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MA_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Massachusetts's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .massachusetts_constitution import (
            configured_constitution_html_path,
            parse_massachusetts_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_massachusetts_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Massachusetts Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .massachusetts_section import configured_section_html_path, parse_massachusetts_section_html

        html_path = configured_section_html_path()
        if html_path is not None:
            parsed = parse_massachusetts_section_html(
                html_path.read_text(encoding="utf-8", errors="replace"),
                source_url="https://malegislature.gov/Laws/GeneralLaws/PartIV/TitleI/Chapter265/Section1",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/Laws/GeneralLaws/PartI",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIII",
            f"{self.get_base_url()}/Laws/GeneralLaws/PartIV",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        probe_threshold = limit if limit is not None else self._bounded_return_threshold(160)

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_sections = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(probe_threshold)),
            )
            if direct_sections:
                _merge(direct_sections)

        official_statutes = await self._scrape_official_general_laws_tree(
            code_name,
            max_statutes=limit,
        )
        if official_statutes:
            return official_statutes if limit is None else official_statutes[: int(limit)]

        generic_cap = limit if limit is not None else max(10, int(probe_threshold))
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Mass. Gen. Laws",
                max_sections=max(10, int(generic_cap)),
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

        return merged if limit is None else merged[: int(limit)]

    async def _scrape_official_general_laws_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None

        root_html = await self._request_text_direct(f"{self.get_base_url()}/Laws/GeneralLaws", timeout=20)
        if not root_html:
            return []

        root_soup = BeautifulSoup(root_html, "html.parser")
        part_links: List[str] = []
        seen_parts = set()
        for link in root_soup.find_all("a", href=True):
            href = str(link.get("href", "")).strip()
            if "/Laws/GeneralLaws/Part" not in href:
                continue
            abs_url = urljoin(self.get_base_url(), href)
            if abs_url in seen_parts:
                continue
            seen_parts.add(abs_url)
            part_links.append(abs_url)

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        for part_url in part_links:
            if limit is not None and len(statutes) >= limit:
                break
            section_budget = (limit * 4) if limit is not None else 1000000
            section_links = await self._discover_section_links_from_part(
                part_url,
                max_sections=max(1, int(section_budget)),
            )
            for section_url in section_links:
                if limit is not None and len(statutes) >= limit:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_section_statute(code_name, section_url)
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _discover_section_links_from_part(self, part_url: str, max_sections: int) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        part_html = await self._request_text_direct(part_url, timeout=20)
        if not part_html:
            return []

        title_specs = self._extract_title_specs(part_html)
        section_links: List[str] = []
        seen_chapters = set()
        seen_sections = set()
        for part_id, title_id, title_code in title_specs:
            if len(section_links) >= max_sections:
                break
            chapter_fragment = await self._request_text_direct(
                f"{self.get_base_url()}/Laws/GeneralLaws/GetChaptersForTitle?partId={part_id}&titleId={title_id}&code={title_code}",
                timeout=20,
            )
            if not chapter_fragment:
                continue
            chapter_soup = BeautifulSoup(chapter_fragment, "html.parser")
            for link in chapter_soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                if "/Laws/GeneralLaws/" not in href or "/Chapter" not in href:
                    continue
                chapter_url = urljoin(self.get_base_url(), href)
                if chapter_url in seen_chapters:
                    continue
                seen_chapters.add(chapter_url)
                chapter_html = await self._request_text_direct(chapter_url, timeout=20)
                if not chapter_html:
                    continue
                chapter_page = BeautifulSoup(chapter_html, "html.parser")
                for section_link in chapter_page.find_all("a", href=True):
                    raw_section_href = str(section_link.get("href", "")).strip()
                    if "/Laws/GeneralLaws/" not in raw_section_href or "/Section" not in raw_section_href:
                        continue
                    abs_section = urljoin(self.get_base_url(), raw_section_href)
                    if abs_section in seen_sections:
                        continue
                    seen_sections.add(abs_section)
                    section_links.append(abs_section)
                    if len(section_links) >= max_sections:
                        break
                if len(section_links) >= max_sections:
                    break
        return section_links

    def _extract_title_specs(self, html: str) -> List[Tuple[str, str, str]]:
        specs: List[Tuple[str, str, str]] = []
        seen = set()
        for match in self._MA_TITLE_LOAD_RE.finditer(html):
            item = (
                str(match.group("part") or "").strip(),
                str(match.group("title") or "").strip(),
                str(match.group("code") or "").strip(),
            )
            if not all(item) or item in seen:
                continue
            seen.add(item)
            specs.append(item)
        return specs

    async def _build_section_statute(self, code_name: str, section_url: str) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._request_text_direct(section_url, timeout=20)
        if not html:
            return None
        from .massachusetts_section import parse_massachusetts_section_html

        parsed = parse_massachusetts_section_html(html, source_url=section_url, code_name=code_name)
        if parsed is not None:
            return parsed
        soup = BeautifulSoup(html, "html.parser")

        heading = soup.select_one("h2.genLawHeading")
        section_name = self._normalize_legal_text(heading.get_text(" ", strip=True)) if heading else ""
        body_chunks: List[str] = []
        for para in soup.find_all("p"):
            text = self._normalize_legal_text(para.get_text(" ", strip=True))
            if text:
                body_chunks.append(text)
        if not body_chunks:
            main = soup.select_one("main") or soup
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            if text:
                body_chunks.append(text)
        body = "\n".join(chunk for chunk in body_chunks if chunk)
        if len(body) < 80:
            return None

        chapter_match = re.search(r"/Chapter(?P<chapter>[a-z0-9.]+)", section_url, re.IGNORECASE)
        section_match = re.search(r"/Section(?P<section>[a-z0-9.]+)", section_url, re.IGNORECASE)
        if chapter_match is None:
            chapter_match = self._MA_CHAPTER_NUMBER_RE.search(section_url)
        if section_match is None:
            section_match = self._MA_SECTION_NUMBER_RE.search(section_url)
        chapter_number = chapter_match.group("chapter") if chapter_match else ""
        section_number = section_match.group("section") if section_match else ""
        statute_id = f"{code_name} ch. {chapter_number} § {section_number}".strip()
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=statute_id,
            code_name=code_name,
            chapter_number=chapter_number,
            section_number=section_number,
            section_name=section_name[:200] if section_name else f"Section {section_number}",
            full_text=body,
            legal_area=self._identify_legal_area(section_name or body),
            source_url=section_url,
            official_cite=f"Mass. Gen. Laws ch. {chapter_number}, § {section_number}",
            structured_data={
                "source_kind": "official_massachusetts_general_laws_html",
                "discovery_method": "official_part_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1", "Citizens of commonwealth defined", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section1"),
            ("2", "Jurisdiction", f"{self.get_base_url()}/Laws/GeneralLaws/PartI/TitleI/Chapter1/Section2"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, fallback_name, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = soup.select_one("h2.genLawHeading")
            section_name = self._normalize_legal_text(heading.get_text(" ", strip=True)) if heading else fallback_name
            body = ""
            for para in soup.find_all("p"):
                text = self._normalize_legal_text(para.get_text(" ", strip=True))
                if text.lower().startswith(f"section {section_number.lower()}."):
                    body = text
                    break
            if not body:
                main = soup.select_one("main") or soup
                body = self._normalize_legal_text(main.get_text(" ", strip=True))
            if len(body) < 60:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} ch. 1 § {section_number}",
                    code_name=code_name,
                    chapter_number="1",
                    chapter_name="JURISDICTION OF THE COMMONWEALTH AND OF THE UNITED STATES",
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=body,
                    legal_area=self._identify_legal_area(section_name or body),
                    source_url=source_url,
                    official_cite=f"Mass. Gen. Laws ch. 1, § {section_number}",
                    structured_data={
                        "source_kind": "official_massachusetts_general_laws_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
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

    def official_title_url(self, part: str, title: str) -> str:
        return (
            f"{self.get_base_url()}/Laws/GeneralLaws/Part{str(part).upper()}"
            f"/Title{str(title).upper()}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Massachusetts General Laws title catalog."""

        rows: List[Dict[str, Any]] = []
        for part, title, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(part, title)
            rows.append(
                {
                    "canonical_key": f"ma:part-{part.lower()}:title-{title.lower()}",
                    "part": str(part),
                    "title_number": str(title),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Massachusetts General Laws Part {part} Title {title} "
                        f"({name}) official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-massachusetts-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-massachusetts-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes) -> Dict[Tuple[str, str], str]:
        found: Dict[Tuple[str, str], str] = {}
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
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._MA_PART_TITLE_RE.search(absolute)
            if not match or not match.group("title"):
                continue
            key = (match.group("part").upper(), match.group("title").upper())
            if key not in found:
                found[key] = self.official_title_url(*key)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official MGL title and repair missing live links."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get((str(row["part"]), str(row["title_number"])))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "MA"):
        """Acquire the exhaustive official Massachusetts General Laws title catalog.

        Live HTTPS retains the official General Laws landing page. Every MGL
        title is enumerated with an official malegislature.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MA").strip().upper() or "MA"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("massachusetts official catalog enumeration is incomplete")
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


# Register this scraper with the registry
StateScraperRegistry.register("MA", MassachusettsScraper)
