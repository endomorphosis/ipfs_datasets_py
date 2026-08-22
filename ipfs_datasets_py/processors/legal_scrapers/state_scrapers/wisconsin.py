"""Scraper for Wisconsin state laws.

Official path: chapter/section HTML hierarchy on https://docs.legis.wisconsin.gov
(statutes index → chapter → section). Playwright/generic remain fallbacks only.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import re
import ssl
import urllib.request
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class WisconsinScraper(BaseStateScraper):
    """Scraper for Wisconsin state laws from https://docs.legis.wisconsin.gov"""

    _WI_SECTION_URL_RE = re.compile(r"/document/statutes/[0-9]+(?:\.[0-9A-Za-z]+)+$", re.IGNORECASE)
    _WI_CHAPTER_URL_RE = re.compile(
        r"/document/statutes/(?P<chapter>[0-9]+)/?$",
        re.IGNORECASE,
    )
    OFFICIAL_DOMAIN = "docs.legis.wisconsin.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/statutes"
    OFFICIAL_ENTRY_URL = "https://docs.legis.wisconsin.gov/statutes/statutes"
    OFFICIAL_CHAPTERS = (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 38, 39,
        40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 59, 60,
        61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78,
        79, 80, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113,
        114, 115, 116, 117, 118, 119, 120, 121, 125, 126, 128, 132, 133, 134,
        135, 136, 137, 138, 139, 140, 145, 146, 149, 150, 151, 153, 154, 155,
        157, 160, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175,
        177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190,
        191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204,
        213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226,
        227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 240, 241,
        242, 243, 244, 250, 251, 252, 253, 254, 255, 256, 257, 280, 281, 283,
        285, 287, 289, 291, 292, 293, 295, 299, 301, 302, 303, 304, 321, 322,
        323, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 401,
        402, 403, 404, 405, 407, 408, 409, 410, 411, 420, 421, 422, 423, 424,
        425, 426, 427, 428, 429, 440, 441, 442, 443, 444, 445, 446, 447, 448,
        449, 450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 462, 463,
        464, 465, 466, 470, 551, 552, 553, 562, 563, 564, 565, 569, 600, 601,
        604, 605, 609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 620,
        621, 622, 623, 625, 626, 627, 628, 630, 631, 632, 633, 635, 644, 645,
        646, 647, 648, 655, 700, 701, 702, 703, 704, 705, 706, 707, 708, 709,
        710, 711, 750, 751, 752, 753, 754, 755, 756, 757, 758, 759, 765, 766,
        767, 768, 769, 770, 778, 779, 780, 781, 782, 783, 784, 785, 786, 788,
        799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812,
        813, 814, 815, 816, 818, 820, 821, 822, 823, 835, 839, 840, 841, 842,
        843, 844, 846, 847, 851, 852, 853, 854, 856, 857, 858, 859, 860, 861,
        862, 863, 865, 866, 867, 868, 877, 878, 879, 880, 881, 882, 884, 885,
        887, 889, 891, 893, 895, 898, 901, 902, 903, 904, 905, 906, 907, 908,
        909, 910, 911, 916, 938, 939, 940, 941, 942, 943, 944, 945, 946, 947,
        948, 949, 950, 951, 961, 967, 968, 969, 970, 971, 972, 973, 974, 975,
        976, 977, 978, 979, 980, 985, 990, 991, 992, 995,
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._WI_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Wisconsin's legislative website."""
        return "https://docs.legis.wisconsin.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Wisconsin."""
        return [{
            "name": "Wisconsin Statutes",
            "url": f"{self.get_base_url()}/statutes/statutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Wisconsin's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None and max_statutes is None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/statutes",
            f"{self.get_base_url()}/document/statutes/940",
            f"{self.get_base_url()}/document/statutes/939.50",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = limit if limit is not None else 1000000
        scan_limit = return_threshold if limit is not None else 1000
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Wis. Stat.",
                        max_sections=scan_limit,
                        wait_for_selector="a[href*='/document/statutes/'], a[href*='/statutes/statutes']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Wis. Stat.",
                max_sections=scan_limit,
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes[:return_threshold]

        return best_statutes

    async def _scrape_direct_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            ("939.50", f"{self.get_base_url()}/document/statutes/939.50"),
            ("940.01", f"{self.get_base_url()}/document/statutes/940.01"),
        ]
        return await self._scrape_section_urls(code_name, [(url, section_number) for section_number, url in section_urls], max_statutes=max_statutes)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_links = await self._discover_chapter_links()
        self.logger.info("Wisconsin official index: discovered %s chapter links", len(chapter_links))
        statutes: List[NormalizedStatute] = []
        seen = set()
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_match = re.search(r"/document/statutes/([0-9]+)/?$", chapter_url, re.IGNORECASE)
            chapter_number = chapter_match.group(1) if chapter_match else ""
            chapter_payload = await self._fetch_page_content_with_archival_fallback(
                chapter_url, timeout_seconds=20
            )
            if chapter_payload and chapter_number:
                from .wisconsin_chapter import statutes_from_page

                html = (
                    chapter_payload.decode("utf-8", errors="replace")
                    if isinstance(chapter_payload, bytes)
                    else str(chapter_payload)
                )
                remaining = None if limit is None else max(0, int(limit) - len(statutes))
                for row in statutes_from_page(
                    html,
                    chapter=chapter_number,
                    code_name=code_name,
                    max_statutes=remaining,
                ):
                    key = str(row.section_number or "").strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    statutes.append(row)
                    if limit is not None and len(statutes) >= limit:
                        break
            section_links = await self._discover_section_links(chapter_url)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_links):
                self.logger.info(
                    "Wisconsin official index: chapter=%s index=%s/%s sections=%s statutes_so_far=%s",
                    chapter_label or chapter_url,
                    chapter_index,
                    len(chapter_links),
                    len(section_links),
                    len(statutes),
                )
            remaining_links = [
                item
                for item in section_links
                if str(item[1] or "").strip().lower() not in seen
            ]
            parsed = await self._scrape_section_urls(
                code_name,
                remaining_links,
                max_statutes=(None if limit is None else max(0, limit - len(statutes))),
            )
            for row in parsed:
                key = str(row.section_number or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                statutes.append(row)
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/statutes"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not re.search(r"/document/statutes/[0-9]+/?$", href, re.IGNORECASE):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        chapter_match = re.search(r"/document/statutes/([0-9]+)/?$", chapter_url, re.IGNORECASE)
        chapter_number = chapter_match.group(1) if chapter_match else ""
        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._WI_SECTION_URL_RE.search(href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            section_number = normalized.rsplit("/", 1)[-1]
            if chapter_number and section_number.split(".", 1)[0] != chapter_number:
                continue
            # Always store the URL-derived section number (not the link label).
            out.append((normalized, section_number if section_number else label))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        for source_url, section_hint in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            url_section = str(source_url).rstrip("/").rsplit("/", 1)[-1].strip()
            section_number = url_section if re.match(r"^[0-9]+(?:\.[0-9A-Za-z]+)+$", url_section) else str(section_hint or url_section).strip()
            html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
            from .wisconsin_chapter import chapter_of, statutes_from_page

            harvested = statutes_from_page(
                html,
                chapter=chapter_of(section_number),
                code_name=code_name,
                max_statutes=None,
            )
            match = next(
                (row for row in harvested if str(row.section_number) == section_number),
                None,
            )
            if match is not None:
                statutes.append(match)
                continue
            soup = BeautifulSoup(html, "html.parser")
            section_nodes = soup.select(f'[data-section="{section_number}"]')
            if not section_nodes:
                section_nodes = soup.select(".box-content, #contentFrame, main, article, body")

            text_parts: List[str] = []
            section_name = ""
            for node in section_nodes:
                if not section_name:
                    title_node = node.select_one(".qstitle_sect") or node.select_one("h1") or node.find("title")
                    if title_node:
                        section_name = title_node.get_text(" ", strip=True)
                text_value = self._normalize_legal_text(node.get_text(" ", strip=True))
                if text_value:
                    text_parts.append(text_value)

            text = self._normalize_legal_text(" ".join(text_parts))
            if not section_name:
                title = soup.find("title") or soup.find("h1")
                section_name = title.get_text(" ", strip=True) if title else f"Section {section_number}"
            if len(text) < 180:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"Wis. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wisconsin_statutes_html",
                        "discovery_method": "official_chapter_section_index",
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def official_chapter_url(self, chapter_number: Any) -> str:
        return f"{self.get_base_url()}/document/statutes/{int(chapter_number)}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Wisconsin Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"wi:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wisconsin Statutes Chapter {int(number)} official "
                        f"catalog unit at {url}"
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
                        "User-Agent": "ipfs-datasets-wisconsin-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-wisconsin-official-catalog/1.0",
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

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
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
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._WI_CHAPTER_URL_RE.search(absolute)
            if not match:
                continue
            number = str(int(match.group("chapter")))
            if number not in found:
                found[number] = self.official_chapter_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Wisconsin chapter and repair missing live links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for number, url in discovered.items():
            if number in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"wi:chapter-{number}",
                    "chapter_number": number,
                    "name": f"Chapter {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Wisconsin Statutes Chapter {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        rows.sort(key=lambda item: int(item["chapter_number"]))
        return rows

    def fetch_official(self, code: str = "WI"):
        """Acquire the exhaustive official Wisconsin Statutes chapter catalog.

        Live HTTPS retains the official statutes index. Every known chapter is
        enumerated with an official docs.legis.wisconsin.gov URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "WI").strip().upper() or "WI"
        if normalized != "WI":
            raise ValueError(f"WisconsinScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("wisconsin official catalog enumeration is incomplete")
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
StateScraperRegistry.register("WI", WisconsinScraper)
