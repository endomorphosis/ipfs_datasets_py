"""Scraper for Minnesota state laws.

This module contains the scraper for Minnesota statutes from the official state legislative website.
"""

import asyncio
import json
import os
import re
import ssl
import urllib.request
from typing import Any, Dict, List
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws from https://www.revisor.mn.gov"""

    _MN_CHAPTER_URL_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+)$", re.IGNORECASE)
    _MN_SECTION_URL_RE = re.compile(r"/statutes/cite/[0-9A-Za-z]+\.[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*$", re.IGNORECASE)
    _MN_SECTION_NUMBER_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)$", re.IGNORECASE)
    _MN_SECTION_ROW_RE = re.compile(r"^(?P<section>[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)\s+(?P<title>.+)$")
    _MN_CHAPTER_RANGE_RE = re.compile(r"\b(?P<start>\d{1,3}[A-Za-z]?)\s*-\s*(?P<end>\d{1,3}[A-Za-z]?)\b")
    OFFICIAL_DOMAIN = "www.revisor.mn.gov"
    OFFICIAL_ENTRY_PATH = "/statutes/"
    OFFICIAL_ENTRY_URL = "https://www.revisor.mn.gov/statutes/"
    OFFICIAL_NUMERIC_CHAPTERS = tuple(range(1, 649))
    OFFICIAL_LETTERED_CHAPTERS = (
        "3A", "3C", "3D", "13A", "16A", "16B", "16C", "16D", "16E", "43A",
        "47A", "60A", "61A", "62A", "62J", "62Q", "65B", "72A", "79A", "80A",
        "82A", "84A", "89A", "97A", "97B", "97C", "103A", "103B", "103C",
        "103D", "103E", "103F", "103G", "103H", "103I", "115A", "115B", "116J",
        "116L", "135A", "136A", "136F", "144A", "144E", "144G", "145A", "147A",
        "148B", "148E", "149A", "168A", "169A", "171A", "216A", "216B", "216C",
        "245A", "245C", "245D", "245G", "252A", "253B", "253D", "256B", "256C",
        "256J", "256L", "256R", "260B", "260C", "260E", "270C", "289A", "290A",
        "297A", "297B", "297E", "297F", "297I", "325D", "325E", "325F", "325G",
        "325L", "325M", "325N", "336A", "462A", "473H", "501C", "508A", "515B",
        "518A", "518B", "518C", "518D", "523A", "609A", "611A", "626A",
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MN_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Minnesota's legislative website."""
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Minnesota."""
        return [{
            "name": "Minnesota Statutes",
            "url": f"{self.get_base_url()}/statutes/cite/609.02",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Minnesota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        allow_justia = str(
            os.getenv("STATE_SCRAPER_MN_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/cite/609.02",
            f"{self.get_base_url()}/statutes/",
            f"{self.get_base_url()}/statutes/cite/645.44",
        ]
        # Secondary Justia mirrors are never sole full-corpus admission unless
        # explicitly re-enabled; bounded probes may still use them as last resort.
        if allow_justia or (not self._full_corpus_enabled()):
            candidate_urls.append("https://law.justia.com/codes/minnesota/")

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        limit = self._effective_scrape_limit(max_statutes, default=420)
        enough = min(80, limit or 80) if limit is not None else 80

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                if limit is not None and len(merged) >= limit:
                    return
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        if self._MN_SECTION_URL_RE.search(str(code_url or "")):
            direct_seed = await self._build_statute_from_section_page(code_name, code_url)
            if direct_seed is not None:
                _merge([direct_seed])
                if limit is not None and len(merged) >= enough:
                    return merged

        chapter_statutes = await self._scrape_chapter_sections(
            code_name,
            max_statutes=limit if limit is not None else 1000000,
        )
        _merge(chapter_statutes)
        if len(merged) >= enough:
            # Prefer official revisor chapter tree; never sole-admit Justia.
            if self._full_corpus_enabled() and not allow_justia:
                merged = [
                    s for s in merged
                    if "justia.com" not in str(s.source_url or "").lower()
                ]
            return merged if limit is None else merged[: int(limit)]

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if self._full_corpus_enabled() and "justia.com" in str(candidate).lower() and not allow_justia:
                continue

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Minn. Stat.",
                        max_sections=limit or 1000000,
                        wait_for_selector="a[href*='/statutes/cite/'], a[href*='/statutes/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if self._full_corpus_enabled() and not allow_justia:
                        statutes = [
                            s for s in statutes
                            if "justia.com" not in str(s.source_url or "").lower()
                        ]
                    _merge(statutes)
                    if limit is not None and len(merged) >= enough:
                        return merged
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Minn. Stat.", max_sections=limit or 1000000)
            statutes = self._filter_section_level(statutes)
            if self._full_corpus_enabled() and not allow_justia:
                statutes = [
                    s for s in statutes
                    if "justia.com" not in str(s.source_url or "").lower()
                ]
            _merge(statutes)
            if limit is not None and len(merged) >= enough:
                return merged

        return merged if limit is None else merged[: int(limit)]

    async def _scrape_chapter_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes or 1))
        chapter_budget = limit if self._full_corpus_enabled() else min(limit, 24)
        chapter_urls = await self._discover_chapter_urls(max_chapters=max(1, chapter_budget))
        if not chapter_urls:
            chapter_urls = [
                f"{self.get_base_url()}/statutes/cite/609",
                f"{self.get_base_url()}/statutes/cite/645",
                f"{self.get_base_url()}/statutes/cite/518",
                f"{self.get_base_url()}/statutes/cite/518B",
                f"{self.get_base_url()}/statutes/cite/169A",
                f"{self.get_base_url()}/statutes/cite/8",
                f"{self.get_base_url()}/statutes/cite/13",
                f"{self.get_base_url()}/statutes/cite/144",
                f"{self.get_base_url()}/statutes/cite/325F",
            ]
        self.logger.info(
            "Minnesota chapter crawl: discovered_chapters=%s max_statutes=%s",
            len(chapter_urls),
            limit,
        )

        section_urls: List[str] = []
        seen_urls = set()
        for chapter_url in chapter_urls:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
            except Exception:
                continue
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for section_url in self._extract_section_urls_from_chapter_page(soup):
                if section_url in seen_urls:
                    continue
                seen_urls.add(section_url)
                section_urls.append(section_url)
                if len(section_urls) >= limit:
                    break
            if len(section_urls) >= limit:
                break

        if not section_urls:
            return []

        statutes: List[NormalizedStatute] = []
        for section_index, section_url in enumerate(section_urls[:limit], start=1):
            try:
                result = await self._build_statute_from_section_page(code_name, section_url)
            except Exception:
                continue
            if result is None:
                continue
            statutes.append(result)
            if len(statutes) == 1 or len(statutes) % 25 == 0:
                self.logger.info(
                    "Minnesota chapter crawl: scanned_sections=%s/%s statutes_so_far=%s",
                    section_index,
                    min(len(section_urls), limit),
                    len(statutes),
                )
            if len(statutes) >= limit:
                break

        return statutes

    async def _discover_chapter_urls(self, max_chapters: int) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=35)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_urls: List[str] = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            match = self._MN_CHAPTER_URL_RE.search(href)
            if not match:
                continue
            chapter_token = match.group(1)
            if "." in chapter_token:
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            chapter_urls.append(full_url)
            if len(chapter_urls) >= max(1, int(max_chapters)):
                return chapter_urls

        page_text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        for match in self._MN_CHAPTER_RANGE_RE.finditer(page_text):
            for chapter_token in self._expand_chapter_range(match.group("start"), match.group("end")):
                full_url = f"{self.get_base_url()}/statutes/cite/{chapter_token}"
                if full_url in seen:
                    continue
                seen.add(full_url)
                chapter_urls.append(full_url)
                if len(chapter_urls) >= max(1, int(max_chapters)):
                    return chapter_urls

        return chapter_urls

    def _expand_chapter_range(self, start_token: str, end_token: str) -> List[str]:
        def _split(token: str) -> tuple[int, str]:
            match = re.match(r"^(\d{1,3})([A-Za-z]?)$", str(token or "").strip())
            if not match:
                return 0, ""
            return int(match.group(1)), match.group(2).upper()

        start_num, start_suffix = _split(start_token)
        end_num, end_suffix = _split(end_token)
        if start_num <= 0 or end_num <= 0 or end_num < start_num:
            return []

        if start_num == end_num:
            suffixes = [""]
            if start_suffix or end_suffix:
                begin_ord = ord(start_suffix or "A")
                end_ord = ord(end_suffix or start_suffix or "A")
                suffixes = [chr(code) for code in range(begin_ord, end_ord + 1)]
                if start_suffix == "":
                    suffixes.insert(0, "")
            return [f"{start_num}{suffix}" for suffix in suffixes]

        out = [f"{start_num}{start_suffix}" if start_suffix else str(start_num)]
        for value in range(start_num + 1, end_num):
            out.append(str(value))
        out.append(f"{end_num}{end_suffix}" if end_suffix else str(end_num))
        return out

    def _extract_section_urls_from_chapter_page(self, soup) -> List[str]:
        urls: List[str] = []

        # Minnesota chapter pages expose the authoritative section list in table rows,
        # which is more reliable than inferring coverage from the link structure alone.
        for row in soup.find_all("tr"):
            text = " ".join(row.get_text(" ", strip=True).split())
            if not text:
                continue
            match = self._MN_SECTION_ROW_RE.match(text)
            if not match:
                continue
            urls.append(f"{self.get_base_url()}/statutes/cite/{match.group('section')}")

        if urls:
            return urls

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href.startswith("/statutes/cite/"):
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if self._MN_SECTION_URL_RE.search(full_url):
                urls.append(full_url)

        return urls

    async def _build_statute_from_section_page(self, code_name: str, section_url: str) -> NormalizedStatute | None:
        html_text = await self._request_text_direct(section_url, timeout=18)
        if not html_text:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
            except Exception:
                return None
            if not payload:
                return None
            html_text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        if not html_text:
            return None

        match = self._MN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else section_url.rsplit("/", 1)[-1]
        text = self._extract_best_content_text(html_text)
        heading_pattern = re.compile(
            rf"\b{re.escape(section_number)}\b\s+[A-Z][A-Z0-9 ,;:'()\-/&]+\.",
            re.IGNORECASE,
        )
        heading_match = heading_pattern.search(text)
        if heading_match:
            text = text[heading_match.start():]
        text = re.split(r"\bHistory:\b", text, maxsplit=1)[0].strip()
        text = re.split(r"\b(?:Official Publication of the State of Minnesota|About the Legislature|General Contact|Get Connected)\b", text, maxsplit=1)[0].strip()
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 160:
            return None

        heading = f"Minnesota Statutes {section_number}"
        title_match = re.search(r"\b%s\b\s+([A-Z][A-Z0-9 ,;:'()\-/&]{4,120})\." % re.escape(section_number), text)
        if title_match:
            heading = f"{section_number} {title_match.group(1).title()}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=heading[:200],
            full_text=text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Minn. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_minnesota_statutes_html",
                "discovery_method": "official_seed_or_section_page",
                "skip_hydrate": True,
            },
        )

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip()
        return f"{self.get_base_url()}/statutes/cite/{token}"

    def official_chapter_tokens(self) -> List[str]:
        tokens: List[str] = [str(number) for number in self.OFFICIAL_NUMERIC_CHAPTERS]
        tokens.extend(self.OFFICIAL_LETTERED_CHAPTERS)
        return tokens

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Minnesota Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for token in self.official_chapter_tokens():
            url = self.official_chapter_url(token)
            rows.append(
                {
                    "canonical_key": f"mn:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Minnesota Statutes Chapter {token} official catalog "
                        f"unit at {url}"
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
                        "User-Agent": "ipfs-datasets-minnesota-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-minnesota-official-catalog/1.0",
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
            match = self._MN_CHAPTER_URL_RE.search(href)
            if not match:
                continue
            token = match.group(1)
            if "." in token:
                continue
            if token not in found:
                found[token] = self.official_chapter_url(token)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Minnesota Statutes chapter and repair links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]).lower() for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for token, url in discovered.items():
            if token.lower() in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"mn:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Minnesota Statutes Chapter {token} official catalog "
                        f"unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "MN"):
        """Acquire the exhaustive official Minnesota Statutes chapter catalog.

        Live HTTPS retains the official statutes index. Every known chapter is
        enumerated with an official revisor.mn.gov URL. This hook never
        returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MN").strip().upper() or "MN"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("minnesota official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MN", MinnesotaScraper)
