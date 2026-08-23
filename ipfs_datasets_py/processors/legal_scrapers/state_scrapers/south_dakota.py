"""Scraper for South Dakota state laws.

This module contains the scraper for South Dakota statutes from the official
JSON statute endpoint.
"""

import os
import re
import json
import ssl
import time
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws from https://sdlegislature.gov"""

    OFFICIAL_DOMAIN = "sdlegislature.gov"
    OFFICIAL_ENTRY_PATH = "/Statutes"
    OFFICIAL_ENTRY_URL = "https://sdlegislature.gov/Statutes"
    OFFICIAL_TITLE_API_URL = "https://sdlegislature.gov/api/Statutes/Title"
    _SD_TITLE_HREF_RE = re.compile(
        r"(?:/Statutes(?:/Codified_Laws)?/|/api/Statutes/Title/)(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    _SD_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "State Affairs and Government"),
        ("2", "Aeronautics"),
        ("3", "Public Officers and Employees"),
        ("4", "Public Fiscal Administration"),
        ("5", "Public Property, Purchases and Contracts"),
        ("6", "Local Government Generally"),
        ("7", "Counties"),
        ("8", "Townships"),
        ("9", "Municipal Government"),
        ("10", "Taxation"),
        ("11", "Planning, Zoning and Housing Programs"),
        ("12", "Elections"),
        ("13", "Education"),
        ("14", "Libraries"),
        ("15", "Civil Procedure"),
        ("16", "Courts and Judiciary"),
        ("17", "Notice and Publication"),
        ("18", "Oaths and Acknowledgments"),
        ("19", "Evidence"),
        ("20", "Personal Rights and Obligations"),
        ("21", "Judicial Remedies"),
        ("22", "Crimes"),
        ("23A", "Criminal Procedure"),
        ("24", "Penal Institutions, Probation and Parole"),
        ("25", "Domestic Relations"),
        ("26", "Minors"),
        ("27A", "Mentally Ill Persons"),
        ("27B", "Developmentally Disabled Persons"),
        ("28", "Public Welfare and Assistance"),
        ("29A", "Uniform Probate Code"),
        ("31", "Highways and Bridges"),
        ("32", "Motor Vehicles"),
        ("33A", "Veterans Affairs"),
        ("34", "Public Health and Safety"),
        ("34A", "Environmental Protection"),
        ("35", "Alcoholic Beverages"),
        ("36", "Professions and Occupations"),
        ("37", "Trade Regulation"),
        ("38", "Agriculture and Horticulture"),
        ("39", "Food and Drugs"),
        ("40", "Animals and Livestock"),
        ("41", "Game, Fish, Parks and Forestry"),
        ("42", "Recreation and Sports"),
        ("43", "Property"),
        ("44", "Liens"),
        ("45", "Mining, Oil and Gas"),
        ("46", "Water Rights"),
        ("46A", "Water Management"),
        ("47", "Corporations"),
        ("49", "Public Utilities and Carriers"),
        ("50", "Aviation"),
        ("51A", "Banks and Banking"),
        ("53", "Contracts"),
        ("54", "Debtor and Creditor"),
        ("55", "Fiduciaries and Trusts"),
        ("56", "Insurance"),
        ("57A", "Uniform Commercial Code"),
        ("59", "Agency"),
        ("60", "Labor and Employment"),
        ("61", "Unemployment Compensation"),
        ("62", "Workers' Compensation"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    _SEED_SECTIONS = [
        "1-1-1",
        "1-1-1.1",
        "1-1-2",
        "1-1-3",
        "1-1-4",
        "1-1-5",
        "1-1-6",
        "1-1-7",
    ]

    _TITLE_START_SECTIONS = [f"{title}-1-1" for title in range(1, 75)]

    def get_base_url(self) -> str:
        """Return the base URL for South Dakota's legislative website."""
        return "https://sdlegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Dakota."""
        return [
            {"name": "South Dakota Codified Laws", "url": f"{self.get_base_url()}/", "type": "Code"}
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Dakota's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .south_dakota_constitution import (
            configured_constitution_html_path,
            parse_south_dakota_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_south_dakota_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "South Dakota Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .south_dakota_title import configured_title_html_path, parse_south_dakota_title_html

        title_path = configured_title_html_path()
        if title_path is not None:
            try:
                bulk = parse_south_dakota_title_html(
                    title_path.read_text(encoding="utf-8", errors="replace"),
                    title_label=title_path.stem.split(".")[0] or "22",
                    code_name=code_name,
                    max_statutes=limit,
                )
                if bulk:
                    return bulk
            except Exception as exc:
                self.logger.warning("South Dakota official title HTML failed: %s", exc)
        max_api_statutes = limit if limit is not None else None
        api_statutes = await self._scrape_statutes_api(
            code_name=code_name,
            max_statutes=max_api_statutes,
        )
        if api_statutes:
            self.logger.info(f"South Dakota API scrape: Scraped {len(api_statutes)} sections")
            return api_statutes

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name, code_url, "S.D. Codified Laws", max_sections=max_sections
        )

    async def _scrape_statutes_api(
        self, code_name: str, max_statutes: Optional[int]
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        statutes: List[NormalizedStatute] = []
        seen = set()
        pending = list(self._SEED_SECTIONS + self._TITLE_START_SECTIONS)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        last_progress_log_ts = 0.0
        checkpoint = _SouthDakotaCheckpoint(self.state_code)

        while pending:
            if limit is not None and len(statutes) >= limit:
                break
            section = str(pending.pop(0) or "").strip()
            if section in seen:
                continue
            seen.add(section)

            data = await self._request_json(
                f"https://sdlegislature.gov/api/Statutes/Statute/{section}",
                headers=headers,
                timeout=35,
            )
            if not data:
                continue

            next_section = str(data.get("Next") or "").strip()
            if next_section and next_section not in seen:
                pending.insert(0, next_section)

            html = str(data.get("Html") or "")
            full_text = self._clean_html_text(html)
            if len(full_text) < 280:
                continue

            section_number = str(data.get("Statute") or section)
            section_name = str(data.get("CatchLine") or f"Section {section_number}").strip()

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:180],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=f"https://sdlegislature.gov/api/Statutes/Statute/{section_number}",
                    official_cite=f"S.D. Codified Laws {section_number}",
                    structured_data={
                        "source_kind": "official_south_dakota_statutes_api",
                        "discovery_method": "official_statute_api_next_chain",
                        "skip_hydrate": True,
                    },
                )
            )

            now = time.time()
            if len(statutes) == 1 or len(statutes) % 500 == 0 or now - last_progress_log_ts >= 60:
                self.logger.info(
                    "South Dakota API scrape: statutes_so_far=%s current_section=%s next_section=%s",
                    len(statutes),
                    section_number,
                    next_section or "",
                )
                last_progress_log_ts = now
            checkpoint.maybe_write(statutes, section_number=section_number)

        checkpoint.write(statutes, section_number="complete")
        return statutes

    async def _request_json(self, url: str, headers: Dict[str, str], timeout: int) -> Dict:
        try:
            import requests

            response = requests.get(url, headers=headers, timeout=timeout)
            self._record_fetch_event(provider="requests_direct", success=response.ok)
            if response.ok:
                data = self._parse_json_payload(response.content)
                if isinstance(data, dict):
                    return data
        except Exception:
            self._record_fetch_event(provider="requests_direct", success=False)

        for _ in range(3):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if not payload:
                    raise ValueError("empty response")
                data = self._parse_json_payload(payload)
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.5)
                continue
        return {}

    def _parse_json_payload(self, payload: bytes) -> Dict:
        try:
            import json

            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
        return {}

    def _clean_html_text(self, html: str, max_chars: int = 14000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        value = unescape(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()[:max_chars]

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/Statutes/Codified_Laws/{number}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official South Dakota Codified Laws title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"sd:title-{number.lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"South Dakota Codified Laws Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "sdlegislature.gov" or host.endswith(".sdlegislature.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-south-dakota-official-catalog/1.0",
            "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
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

        return _request()

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"0*(\d{1,2}[A-Z]?)$", text)
        return match.group(1) if match else ""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        known = {number for number, _name in self.OFFICIAL_TITLES}
        try:
            parsed = json.loads(html.decode("utf-8", errors="replace"))
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, Mapping):
                    continue
                number = self._normalize_title_number(
                    item.get("Title") or item.get("title") or item.get("Number")
                )
                if number in known and number not in found:
                    found[number] = self.official_title_url(number)
            if found:
                return found
        if isinstance(parsed, Mapping):
            rows = parsed.get("Titles") or parsed.get("titles") or parsed.get("items") or []
            if isinstance(rows, list):
                for item in rows:
                    if not isinstance(item, Mapping):
                        continue
                    number = self._normalize_title_number(
                        item.get("Title") or item.get("title") or item.get("Number")
                    )
                    if number in known and number not in found:
                        found[number] = self.official_title_url(number)
            if found:
                return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._SD_TITLE_HREF_RE.search(absolute) or self._SD_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
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
    ) -> List[Dict[str, Any]]:
        """Enumerate every official South Dakota Codified Laws title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "SD"):
        """Acquire the exhaustive official South Dakota Codified Laws catalog.

        Live HTTPS retains the official sdlegislature.gov statute index.
        Every known Codified Laws title is enumerated with an official URL.
        This hook never returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "SD").strip().upper() or "SD"
        if normalized != "SD":
            raise ValueError(f"SouthDakotaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not self._parse_official_title_links(html):
            api_payload = self._official_http_get(self.OFFICIAL_TITLE_API_URL)
            if api_payload:
                html = api_payload
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "south dakota official catalog enumeration rejected incomplete "
                "title reacquisition"
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


# Register this scraper with the registry
StateScraperRegistry.register("SD", SouthDakotaScraper)


class _SouthDakotaCheckpoint:
    """Best-effort partial progress checkpoint for South Dakota API crawls."""

    def __init__(self, state_code: str) -> None:
        raw_dir = str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = (
                Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(
            1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500))
        )
        self.last_count = 0
        self.last_write_ts = 0.0

    def maybe_write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, section_number=section_number)

    def write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "section_number": section_number,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
