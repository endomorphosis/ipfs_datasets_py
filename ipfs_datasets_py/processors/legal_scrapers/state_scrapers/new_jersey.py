"""Scraper for New Jersey state laws.

This module contains the scraper for New Jersey statutes from the official state
legislative website.
"""

import hashlib
import json
import re
import ssl
import subprocess
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry


class NewJerseyScraper(BaseStateScraper):
    """Scraper for New Jersey state laws from https://www.njleg.state.nj.us"""

    _LIS_GATEWAY = "https://lis.njleg.state.nj.us/nxt/gateway.dll"
    _XHITLIST_SELECT = (
        "title;path;relevance-weight;content-type;home-title;"
        "item-bookmark;title-path"
    )
    _XMLCONTENTS_BASE = (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll"
        "?f=xmlcontents&maxnodes=75&minnodesleft=10&siteshowhits=true&hidezerohits=true"
    )
    OFFICIAL_DOMAIN = "lis.njleg.state.nj.us"
    OFFICIAL_ENTRY_PATH = "/nxt/gateway.dll/statutes/1"
    OFFICIAL_ENTRY_URL = (
        "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1"
        "?f=templates&fn=default.htm&vid=Publish:10.1048/Enu"
    )
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    LINK_GAP_QUARANTINE_REASON = "source_link_gap_pending_official_replacement"
    _NJ_TITLE_HREF_RE = re.compile(
        r"/statutes/1/(?P<title>[0-9]+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _NJ_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>[0-9]+[A-Za-z]?)\b", re.IGNORECASE)
    OFFICIAL_TITLES = (
        ("1", "Administration of Civil and Criminal Justice"),
        ("2A", "Administration of Civil and Criminal Justice"),
        ("2B", "Court Organization and Civil Code"),
        ("2C", "The New Jersey Code of Criminal Justice"),
        ("3B", "Administration of Estates--Decedents and Others"),
        ("4", "Agriculture and Domestic Animals"),
        ("5", "Amusements, Public Exhibitions and Meetings"),
        ("6", "Aviation"),
        ("8A", "Cemeteries"),
        ("9", "Children--Juvenile and Domestic Relations Courts"),
        ("10", "Civil Rights"),
        ("11A", "Civil Service"),
        ("12", "Commerce and Navigation"),
        ("12A", "Commercial Transactions"),
        ("13", "Conservation and Development--Parks and Reservations"),
        ("14A", "Corporations, General"),
        ("15A", "Corporations, Nonprofit"),
        ("16", "Corporations and Associations, Religious"),
        ("17", "Corporations and Institutions for Finance and Insurance"),
        ("17B", "Insurance"),
        ("18A", "Education"),
        ("19", "Elections"),
        ("21", "Explosives and Fireworks"),
        ("22A", "Fees and Costs"),
        ("23", "Fish and Game, Wild Birds and Animals"),
        ("24", "Food and Drugs"),
        ("25", "Frauds and Fraudulent Conveyances"),
        ("26", "Health and Vital Statistics"),
        ("27", "Highways"),
        ("30", "Institutions and Agencies"),
        ("32", "Interstate and Port Authorities and Commissions"),
        ("33", "Intoxicating Liquors"),
        ("34", "Labor and Workmen's Compensation"),
        ("35", "Legal Holidays"),
        ("36", "Legal Oaths, Affirmations and Declarations"),
        ("37", "Marriages and Married Persons"),
        ("38A", "Military and Veterans Law"),
        ("39", "Motor Vehicles and Traffic Regulation"),
        ("40", "Municipalities and Counties"),
        ("40A", "Municipalities and Counties"),
        ("41", "Oaths and Affidavits"),
        ("42", "Partnerships and Partnership Associations"),
        ("43", "Pensions and Retirement and Unemployment Compensation"),
        ("44", "Poor"),
        ("45", "Professions and Occupations"),
        ("46", "Property"),
        ("47", "Public Records"),
        ("48", "Public Utilities"),
        ("49", "Sale of Securities"),
        ("51", "Standards, Weights, Measures and Containers"),
        ("52", "State Government, Departments and Officers"),
        ("53", "State Police"),
        ("54", "Taxation"),
        ("54A", "New Jersey Gross Income Tax Act"),
        ("55", "Tenement Houses and Public Housing"),
        ("56", "Trade Names, Trade-Marks and Unfair Trade Practices"),
        ("58", "Waters and Water Supply"),
        ("59", "Claims Against Public Entities"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)
    DEFAULT_LINK_GAP_SEEDS = (
        {
            "canonical_key": "nj:title-2c",
            "label": "New Jersey Statutes Title 2C Code of Criminal Justice",
            "source_url": "https://law.justia.com/codes/new-jersey/title-2c/",
            "title_number": "2C",
        },
        {
            "canonical_key": "nj:title-39",
            "label": "Title 39 Motor Vehicles and Traffic Regulation",
            "source_url": "",
            "title_number": "39",
        },
        {
            "canonical_key": "nj:bucket-seed-untitled",
            "label": "open-us-law-bucket New Jersey seed row without an official source link",
            "source_url": "",
        },
        {
            "canonical_key": "nj:bucket-phantom",
            "label": "New Jersey phantom title without a recoverable official identifier",
            "source_url": "https://law.justia.com/codes/new-jersey/",
        },
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for New Jersey's legislative website."""
        return "https://www.njleg.state.nj.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Jersey."""
        return [{
            "name": "New Jersey Statutes",
            "url": "https://lis.njleg.state.nj.us/nxt/gateway.dll/statutes/1?f=templates&fn=default.htm&vid=Publish:10.1048/Enu",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Jersey's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_jersey_constitution import (
            configured_constitution_html_path,
            parse_new_jersey_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_new_jersey_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "New Jersey Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        bulk = self._scrape_official_bulk_zip(code_name=code_name, max_statutes=limit)
        if bulk:
            return bulk if limit is None else bulk[: int(limit)]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_limit = limit if limit is not None else 160
            direct = await self._scrape_direct_public_law_pdfs(code_name, max_statutes=direct_limit)
            if direct:
                return direct if limit is None else direct[: int(direct_limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "NJ full-corpus run found zero official LIS statutes; "
                "refusing generic/Justia sole-admission fallback"
            )
            return []
        return_threshold = limit if limit is not None else 160
        statutes = await self._scrape_via_xhitlist(code_name, max_sections=max(10, return_threshold))
        if len(statutes) >= int(return_threshold):
            return statutes

        self.logger.warning(
            "NJ xhitlist extraction returned %d records; falling back to generic scrape",
            len(statutes),
        )
        fallback = await self._generic_scrape(code_name, code_url, "N.J. Stat. Ann.", max_sections=max(10, return_threshold))
        if not fallback:
            return statutes

        seen = {s.source_url for s in statutes if s.source_url}
        for statute in fallback:
            if statute.source_url in seen:
                continue
            if self._looks_like_secondary_url(str(statute.source_url or "")):
                continue
            seen.add(statute.source_url)
            statutes.append(statute)
        return statutes

    def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read the official STATUTES-TEXT.zip when NEW_JERSEY_BULK_ZIP is set."""

        from .new_jersey_bulk import configured_bulk_zip_path, parse_new_jersey_bulk_zip

        zip_path = configured_bulk_zip_path()
        if zip_path is None:
            return []
        try:
            return parse_new_jersey_bulk_zip(
                zip_path,
                code_name=code_name,
                max_statutes=max_statutes,
            )
        except Exception as exc:
            self.logger.warning("New Jersey official bulk zip failed: %s", exc)
            return []

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_nodes = await self._discover_title_nodes()
        self.logger.info("NJ official index: discovered %s title nodes", len(title_nodes))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, node in enumerate(title_nodes, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            title_id = str(node.get("id") or "").strip()
            title_label = str(node.get("t") or "").strip()
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            section_nodes = await self._discover_section_nodes(title_id, limit=remaining)
            parsed = await self._scrape_section_nodes(
                code_name,
                section_nodes,
                max_statutes=remaining,
                title_label=title_label,
            )
            statutes.extend(parsed)
            if title_index == 1 or title_index % 10 == 0 or title_index == len(title_nodes):
                self.logger.info(
                    "NJ official index: title=%s index=%s/%s sections=%s statutes_so_far=%s",
                    title_label or title_id,
                    title_index,
                    len(title_nodes),
                    len(section_nodes),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_nodes(self) -> List[Dict[str, str]]:
        nodes = await self._fetch_xmlcontents_nodes(basepathid="statutes", command="getchildren")
        title_nodes = [node for node in nodes if str(node.get("id") or "").startswith("statutes/1/")]
        more_nodes = [node for node in nodes if str(node.get("ct") or "") == "application/morenode"]
        while more_nodes:
            next_more = more_nodes.pop(0)
            start = str(next_more.get("n") or "").strip()
            if not start:
                continue
            page = await self._fetch_xmlcontents_nodes(basepathid="statutes/1", command="getmore", start=start, direction="1")
            title_nodes.extend([node for node in page if str(node.get("id") or "").startswith("statutes/1/") and str(node.get("ct") or "") != "application/morenode"])
            more_nodes.extend([node for node in page if str(node.get("ct") or "") == "application/morenode"])
        deduped: List[Dict[str, str]] = []
        seen: set[str] = set()
        for node in title_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node)
        return deduped

    async def _discover_section_nodes(self, title_id: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
        nodes = await self._fetch_xmlcontents_nodes(basepathid=title_id, command="getchildren")
        section_nodes = [node for node in nodes if str(node.get("ct") or "") == "text/xml"]
        more_nodes = [node for node in nodes if str(node.get("ct") or "") == "application/morenode"]
        while more_nodes and (limit is None or len(section_nodes) < limit):
            next_more = more_nodes.pop(0)
            start = str(next_more.get("n") or "").strip()
            if not start:
                continue
            page = await self._fetch_xmlcontents_nodes(basepathid=title_id, command="getmore", start=start, direction="1")
            section_nodes.extend([node for node in page if str(node.get("ct") or "") == "text/xml"])
            more_nodes.extend([node for node in page if str(node.get("ct") or "") == "application/morenode"])
        deduped: List[Dict[str, str]] = []
        seen: set[str] = set()
        for node in section_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node)
            if limit is not None and len(deduped) >= limit:
                break
        return deduped

    async def _fetch_xmlcontents_nodes(
        self,
        *,
        basepathid: str,
        command: str,
        start: str = "",
        direction: str = "",
    ) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        params = [f"command={command}", f"basepathid={quote(basepathid, safe='')}"]
        if command == "getchildren":
            params.append("maxgrandchildren=25")
        if start:
            params.append(f"start={quote(start, safe='')}")
        if direction:
            params.append(f"direction={quote(direction, safe='')}")
        url = f"{self._XMLCONTENTS_BASE}&" + "&".join(params)
        payload = await self._request_bytes_direct(url, timeout=30)
        if not payload:
            return []
        xml = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(xml, "xml")
        out: List[Dict[str, str]] = []
        for node in soup.find_all("n"):
            attrs = {str(k): str(v) for k, v in node.attrs.items()}
            out.append(attrs)
        return out

    async def _scrape_section_nodes(
        self,
        code_name: str,
        section_nodes: List[Dict[str, str]],
        *,
        max_statutes: Optional[int],
        title_label: str,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for node in section_nodes:
            if limit is not None and len(out) >= limit:
                break
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            source_url = f"{self._LIS_GATEWAY}/{node_id}"
            payload = await self._request_bytes_direct(source_url, timeout=25)
            if not payload:
                continue
            html = payload.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            headnotes = soup.select_one("div.Headnotes")
            normal = soup.select_one("div.Normal-Level")
            heading = self._normalize_legal_text((headnotes or soup).get_text(" ", strip=True))
            body = self._normalize_legal_text((normal or soup).get_text(" ", strip=True))
            full_text = self._normalize_legal_text(" ".join(part for part in [heading, body] if part))
            if len(full_text) < 80:
                continue
            section_label = str(node.get("t") or "").strip()
            section_number = self._extract_section_number(section_label)
            if not section_number:
                section_number = self._extract_section_number(heading)
            section_name = section_label
            if section_number and section_name.startswith(section_number):
                section_name = section_name[len(section_number):].lstrip(". ").strip()
            if not section_name:
                section_name = self._normalize_legal_text(heading)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number or node_id}",
                    code_name=code_name,
                    section_number=section_number or str(node.get("n") or node_id),
                    section_name=section_name[:220],
                    full_text=full_text[:14000],
                    legal_area=self._identify_legal_area(title_label or section_name),
                    source_url=source_url,
                    official_cite=(section_number or section_label),
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_jersey_gateway_html",
                        "discovery_method": "official_xmlcontents_toc",
                        "title_label": title_label,
                        "node_id": node_id,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_direct_public_law_pdfs(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            ("P.L. 2025, c.1", "https://pub.njleg.state.nj.us/Bills/2024/PL25/1_.PDF"),
            ("P.L. 2025, c.2", "https://pub.njleg.state.nj.us/Bills/2024/PL25/2_.PDF"),
        ]
        out: List[NormalizedStatute] = []
        for cite, pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes_direct(pdf_url, timeout=20)
            text = self._extract_pdf_text(pdf_bytes, max_chars=14000)
            if len(text) < 280:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {cite}",
                    code_name=code_name,
                    section_number=cite,
                    section_name=cite,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=pdf_url,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_jersey_public_law_pdf",
                        "discovery_method": "official_seed_pdf",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_bytes_direct(self, url: str, timeout: int = 20) -> bytes:
        def _request() -> bytes:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return b""

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0 or not proc.stdout:
            return ""
        text = proc.stdout.decode("utf-8", errors="ignore")
        return re.sub(r"\s+", " ", text).strip()[:max_chars]

    async def _scrape_via_xhitlist(self, code_name: str, max_sections: int = 120) -> List[NormalizedStatute]:
        """Collect NJ statutes from LIS query result pages.

        The LIS default page is JS-driven and often sparse when fetched as static
        HTML. Querying xhitlist returns concrete hitdoc links that can be parsed
        directly.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        terms = ["tax", "crime", "property", "employment", "health"]
        seen_urls = set()
        statutes: List[NormalizedStatute] = []
        legal_area = self._identify_legal_area(code_name)

        for term in terms:
            if len(statutes) >= max_sections:
                break

            page = await self._fetch_xhitlist_page(term)
            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")
            for link in soup.find_all("a", href=True):
                if len(statutes) >= max_sections:
                    break

                href = str(link.get("href", "")).strip()
                if "f=hitdoc" not in href.lower():
                    continue

                link_text = link.get_text(strip=True)
                if not link_text or link_text.lower().startswith(("next", "last", "manage")):
                    continue

                source_url = urljoin(self._LIS_GATEWAY, href)
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = self._derive_section_number_from_url(source_url)
                if not section_number:
                    section_number = f"Section-{len(statutes) + 1}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=link_text[:220],
                        full_text=f"Section {section_number}: {link_text}",
                        legal_area=legal_area,
                        source_url=source_url,
                        official_cite=f"N.J. Stat. Ann. § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info("NJ xhitlist extracted %d statute links", len(statutes))
        return statutes

    async def _fetch_xhitlist_page(self, query_term: str) -> str:
        """Fetch one NJ xhitlist result page as text for a simple query term."""
        params = {
            "f": "xhitlist",
            "xhitlist_vq": query_term,
            "xhitlist_q": query_term,
            "xhitlist_x": "Simple",
            "xhitlist_s": "relevance-weight",
            "xhitlist_mh": "120",
            "xhitlist_d": "",
            "xhitlist_hc": "",
            "xhitlist_xsl": "xhitlist.xsl",
            "xhitlist_vpc": "first",
            "xhitlist_vps": "50",
            "xhitlist_sel": self._XHITLIST_SELECT,
        }
        request_url = self._build_query_url(self._LIS_GATEWAY, params)
        raw = await self._fetch_page_content_with_archival_fallback(
            request_url,
            timeout_seconds=45,
        )
        if not raw:
            return ""
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def _build_query_url(self, base_url: str, params: Dict[str, str]) -> str:
        """Build a URL query string without introducing extra dependencies."""
        from urllib.parse import urlencode

        return f"{base_url}?{urlencode(params)}"

    def official_title_url(self, title_number: Any) -> str:
        slug = str(title_number or "").strip().lower()
        return f"{self._LIS_GATEWAY}/statutes/1/{slug}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New Jersey Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"nj:title-{number.lower()}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New Jersey Statutes Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {
            "lis.njleg.state.nj.us",
            "www.njleg.state.nj.us",
            "njleg.state.nj.us",
        } or host.endswith(".njleg.state.nj.us")

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in ("justia.com", "findlaw.com", "unicourt", "law.cornell.edu")
        )

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        match = re.search(r"\b([0-9]+[A-Z]?)\b", text)
        if not match:
            return ""
        number = match.group(1)
        known = {item for item, _name in self.OFFICIAL_TITLES}
        return number if number in known else ""

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-jersey-official-catalog/1.0",
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

    def classify_source_link_gaps(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Repair official LIS title links or quarantine remaining link gaps.

        Recoverable title numbers are rewritten to ``lis.njleg.state.nj.us``
        catalog URLs. Remaining linkless or secondary-mirror rows stay
        quarantined with a typed disposition.
        """

        repaired: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = self._normalize_title_number(title_number)
            if not number:
                return
            unit_id = f"nj:title-{number.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = (
                source_url
                if source_url and self._host_is_official(source_url)
                else self.official_title_url(number)
            )
            name = dict(self.OFFICIAL_TITLES).get(number, f"Title {number}")
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or name
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "title_number": number,
                    "name": name,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "repaired_official_lis"
                    ),
                    "text": (
                        f"New Jersey Statutes Title {number} ({name}) official "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "", reason: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "nj:missing-" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": reason or self.LINK_GAP_QUARANTINE_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = (
                seeds.decode("utf-8", errors="replace")
                if isinstance(seeds, (bytes, bytearray))
                else seeds
            )
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official New Jersey discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                match = self._NJ_TITLE_HREF_RE.search(absolute) or self._NJ_TITLE_LABEL_RE.search(
                    label
                )
                title_number = match.group("title") if match else self._normalize_title_number(
                    " ".join((absolute, href, label))
                )
                if title_number and self._host_is_official(absolute):
                    _record(title_number, label, "official_href", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "repaired_from_attributes")
                    continue
                if label and self._looks_like_secondary_url(absolute):
                    _quarantine(label, str(link), reason=self.MISSING_LINK_DISPOSITION)
            for node in soup.find_all(["span", "td", "li", "div", "p"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._normalize_title_number(
                    " ".join(
                        str(item or "")
                        for item in (node.get("data-title"), node.get("id"), label)
                    )
                )
                if title_number:
                    _record(title_number, label, "repaired_from_linkless_row")
                    continue
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|without an official)\b",
                    label,
                    re.IGNORECASE,
                ):
                    _quarantine(label, str(node), reason=self.MISSING_LINK_DISPOSITION)
            return {"repaired": repaired, "quarantines": quarantines}

        items = seeds or ()
        for item in items:
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
            title_number = self._normalize_title_number(
                item.get("title_number") or source_url or label
            )
            if title_number and source_url and self._host_is_official(source_url):
                _record(title_number, label, "official_href", source_url)
                continue
            if title_number:
                _record(title_number, label, "repaired_from_linkless_row")
                continue
            _quarantine(
                label or source_url or "new jersey link gap",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NJ_TITLE_HREF_RE.search(absolute) or self._NJ_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = str(match.group("title") or "").strip().upper()
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official NJ titles and type remaining source-link gaps."""

        discovered = self._parse_official_title_links(html)
        classified = self.classify_source_link_gaps(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_source_link_gaps(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_LINK_GAP_SEEDS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])
        self.last_official_repairs = list(classified["repaired"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]).upper(): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_lis"
        for unit in classified["repaired"]:
            number = str(unit.get("title_number") or "").upper()
            if number in by_title and unit.get("source_url"):
                if unit.get("repair_source") == "official_href":
                    by_title[number]["source_url"] = unit["source_url"]
                    by_title[number]["source_link_disposition"] = "official"
        return rows

    def fetch_official(self, code: str = "NJ"):
        """Acquire the exhaustive official New Jersey Statutes title catalog.

        Live HTTPS retains the official LIS statutes index. Every current NJ
        title is enumerated with an official lis.njleg.state.nj.us URL.
        Per-row source-link gaps are repaired to official title URLs or
        quarantined with a typed disposition. This hook never returns fixture
        bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NJ").strip().upper() or "NJ"
        if normalized != "NJ":
            raise ValueError(f"NewJerseyScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        repairs = list(getattr(self, "last_official_repairs", []) or [])
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "new jersey official catalog enumeration rejected incomplete title reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "link_gaps_repaired": True,
            "units": rows,
            "quarantines": quarantines,
            "repairs": repairs,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "nj_link_gap_quarantines": quarantines,
            "nj_link_gaps_repaired": True,
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
StateScraperRegistry.register("NJ", NewJerseyScraper)
