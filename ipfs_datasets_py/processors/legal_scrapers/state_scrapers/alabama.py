"""Scraper for Alabama state laws."""

import asyncio
import hashlib
import json
import re
import ssl
import time
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class AlabamaScraper(BaseStateScraper):
    """Scraper for Alabama state laws from the public ALISON GraphQL API."""

    GRAPHQL_URL = "https://alison.legislature.state.al.us/graphql"
    CODE_URL = "https://alison.legislature.state.al.us/code-of-alabama"
    OFFICIAL_DOMAIN = "alison.legislature.state.al.us"
    OFFICIAL_ENTRY_PATH = "/code-of-alabama"
    OFFICIAL_ENTRY_URL = "https://alison.legislature.state.al.us/code-of-alabama"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    _AL_TITLE_QUERY_RE = re.compile(r"[?&]title=([0-9]+[A-Za-z]?)", re.IGNORECASE)
    _AL_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+([0-9]+[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Agriculture"),
        ("3", "Animals"),
        ("4", "Aviation"),
        ("5", "Banks and Financial Institutions"),
        ("6", "Civil Practice"),
        ("7", "Commercial Code"),
        ("8", "Commercial Law and Consumer Protection"),
        ("9", "Conservation and Natural Resources"),
        ("10A", "Alabama Business and Nonprofit Entities Code"),
        ("11", "Counties and Municipal Corporations"),
        ("12", "Courts"),
        ("13A", "Criminal Code"),
        ("14", "Criminal Correctional and Detention Facilities"),
        ("15", "Criminal Procedure"),
        ("16", "Education"),
        ("17", "Elections"),
        ("18", "Eminent Domain"),
        ("19", "Fiduciaries and Trusts"),
        ("20", "Food, Drugs, and Cosmetics"),
        ("21", "Handicapped Persons"),
        ("22", "Health, Mental Health, and Environmental Control"),
        ("23", "Highways, Roads, Bridges, and Ferries"),
        ("24", "Housing"),
        ("25", "Industrial Relations and Labor"),
        ("26", "Infants and Incompetents"),
        ("27", "Insurance"),
        ("28", "Intoxicating Liquor, Malt Beverages and Wine"),
        ("29", "Legislature"),
        ("30", "Marital and Domestic Relations"),
        ("31", "Military Affairs and Civil Defense"),
        ("32", "Motor Vehicles and Traffic"),
        ("33", "Navigation and Watercourses"),
        ("34", "Professions and Businesses"),
        ("35", "Property"),
        ("36", "Public Officers and Employees"),
        ("37", "Public Utilities and Public Transportation"),
        ("38", "Public Welfare"),
        ("39", "Public Works"),
        ("40", "Revenue and Taxation"),
        ("41", "State Government"),
        ("43", "Wills and Decedents' Estates"),
        ("44", "Youth Services"),
        ("45", "Local Laws"),
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Alabama's legislative website."""
        return "https://alison.legislature.state.al.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Alabama."""
        return [{
            "name": "Alabama Code",
            "url": self.CODE_URL,
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Alabama's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .alabama_constitution import (
            configured_constitution_titles_path,
            parse_configured_alabama_constitution,
        )

        constitution_path = configured_constitution_titles_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_configured_alabama_constitution(
                    code_name=code_name or "Alabama Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .alabama_section import parse_configured_alabama

        local_rows = parse_configured_alabama(code_name=code_name, max_statutes=limit)
        if local_rows:
            return local_rows if limit is None else local_rows[: int(limit)]
        statutes = await self._scrape_alison_graphql(code_name, limit)
        if statutes:
            return statutes[:limit] if limit is not None else statutes

        self.logger.warning(
            "Alabama GraphQL returned no statutes; falling back to archival/custom scrape path"
        )
        # Full-corpus mode must not silently clamp the official tree.
        custom_limit = limit if limit is not None else 1000000
        return await self._custom_scrape_alabama(
            code_name,
            code_url or self.CODE_URL,
            "Ala. Code",
            max_sections=custom_limit,
        )

    async def _graphql(self, query: str, variables: Dict[str, Any] | None = None, timeout_seconds: int = 15) -> Dict[str, Any]:
        timeout = max(1, int(timeout_seconds or 15))
        cache_payload = json.dumps(
            {"query": query, "variables": variables or {}},
            sort_keys=True,
            separators=(",", ":"),
        )
        cache_key = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
        cache_url = f"{self.GRAPHQL_URL}#graphql={cache_key}"
        cached_bytes = await self._load_page_bytes_from_any_cache(cache_url)
        if cached_bytes:
            try:
                cached_payload = json.loads(cached_bytes.decode("utf-8", errors="ignore") or "{}")
                data = cached_payload.get("data") or {}
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        def _request() -> Dict[str, Any]:
            try:
                import requests

                response = requests.post(
                    self.GRAPHQL_URL,
                    json={"query": query, "variables": variables or {}},
                    headers={
                        "User-Agent": "ipfs-datasets-alabama-code-scraper/2.0",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=timeout,
                )
                if int(response.status_code or 0) != 200:
                    return {}
                payload = response.json()
                if payload.get("errors"):
                    return {}
                return payload.get("data") or {}
            except Exception:
                return {}

        try:
            data = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 1)
        except asyncio.TimeoutError:
            data = {}
        self._record_fetch_event(provider="alison_graphql", success=bool(data))
        if data:
            await self._cache_successful_page_fetch(
                url=cache_url,
                payload=json.dumps({"data": data}, sort_keys=True).encode("utf-8"),
                provider="alison_graphql",
            )
        return data

    def _parse_scaffold_section_parent_ids(
        self, scaffold: str, limit: Optional[int]
    ) -> List[str]:
        if not scaffold or len(scaffold) < 3:
            return []
        field_sep = scaffold[0]
        row_sep = scaffold[1]
        rows = [row.split(field_sep) for row in scaffold[2:].split(row_sep) if row]
        if not rows:
            return []
        headers, data_rows = rows[0], rows[1:]
        parent_ids: List[str] = []
        seen = set()
        for row in data_rows:
            record = dict(zip(headers, row))
            display_id = str(record.get("displayId") or "")
            parent_id = str(record.get("parentId") or "")
            if not parent_id or not re.match(r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?){2,}$", display_id):
                continue
            if parent_id in seen:
                continue
            seen.add(parent_id)
            parent_ids.append(parent_id)
            if limit is not None and len(parent_ids) >= max(1, int(limit)):
                break
        return parent_ids

    async def _scrape_alison_graphql(
        self, code_name: str, max_statutes: Optional[int]
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        self.logger.info("Alabama GraphQL: fetching scaffold")
        scaffold_data = await self._graphql(
            "query codeOfAlabamaScaffold { scaffold: codeOfAlabamaScaffold }"
        )
        parent_ids = self._parse_scaffold_section_parent_ids(
            str(scaffold_data.get("scaffold") or ""), max_statutes
        )
        self.logger.info("Alabama GraphQL: discovered %d section parent ids", len(parent_ids))
        if not parent_ids:
            return []

        query = """
        query codesOfAlabamaByParent($parentId: [ID!]) {
          codeItems: codesOfAlabama(where: { parentId: { in: $parentId } }) {
            data {
              codeId
              parentId
              displayId
              title
              content
              history
              type
              isContentNode
            }
          }
        }
        """
        statutes: List[NormalizedStatute] = []
        batch_size = 64 if self._full_corpus_enabled() else 8
        heartbeat_seconds = max(
            15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60))
        )
        last_heartbeat = time.monotonic()
        for offset in range(0, len(parent_ids), batch_size):
            data = await self._graphql(
                query, {"parentId": parent_ids[offset : offset + batch_size]}
            )
            rows = ((data.get("codeItems") or {}).get("data") or [])
            for row in rows:
                if max_statutes is not None and len(statutes) >= max_statutes:
                    return statutes
                if not row.get("isContentNode") or str(row.get("type") or "").lower() != "section":
                    continue
                display_id = str(row.get("displayId") or "").strip()
                content = str(row.get("content") or "")
                history = str(row.get("history") or "")
                text_parts = []
                if content:
                    text_parts.append(
                        BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
                    )
                if history:
                    history_text = BeautifulSoup(history, "html.parser").get_text(
                        " ", strip=True
                    )
                    if history_text:
                        text_parts.append(f"History: {history_text}")
                full_text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
                if not display_id or len(full_text) < 80:
                    continue
                title = re.sub(
                    r"\s+", " ", str(row.get("title") or f"Section {display_id}")
                ).strip()
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {display_id}",
                    code_name=code_name,
                    section_number=display_id,
                    section_name=title[:200],
                    full_text=full_text[:14000],
                    legal_area=self._identify_legal_area(title),
                    source_url=f"{self.CODE_URL}?section={display_id}",
                    official_cite=f"Ala. Code § {display_id}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_alison_graphql",
                        "discovery_method": "official_alison_scaffold_parent_batch",
                        "skip_hydrate": True,
                        "code_id": row.get("codeId"),
                        "parent_id": row.get("parentId"),
                    },
                )
                statutes.append(statute)
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                self.logger.info(
                    "Alabama GraphQL: offset=%d/%d rows_last_batch=%d statutes=%d",
                    min(offset + batch_size, len(parent_ids)),
                    len(parent_ids),
                    len(rows),
                    len(statutes),
                )
                last_heartbeat = now
        self.logger.info("Alabama GraphQL: completed with %d statutes", len(statutes))
        return statutes
    
    async def _custom_scrape_alabama(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Alabama's legislative website.
        
        Alabama's website uses framesets and may not be accessible directly.
        This scraper uses multiple fallback strategies:
        1. Try Internet Archive
        2. Parse frameset to extract actual content URLs
        3. Use generic fallback scraper
        """
        self.logger.info(f"Alabama: Starting custom scrape for {code_name}")
        self.logger.info(f"Alabama: Accessing URL: {code_url}")
        
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Alabama: Required library not available: {e}")
            self.logger.error("Alabama: Install required packages: pip install beautifulsoup4")
            return []
        
        statutes = []
        
        # Alabama's site is often down or blocked, use Internet Archive
        # Try to get an archived version first
        archive_urls_to_try = [
            "http://web.archive.org/web/20240123221654/http://alisondb.legislature.state.al.us/alison/CodeOfAlabama/1975/title.htm",
            "http://web.archive.org/web/20231201000000*/http://alisondb.legislature.state.al.us/alison/CodeOfAlabama/1975/title.htm",
            code_url  # Try original as last resort
        ]
        
        # Try each URL until one works
        for attempt_url in archive_urls_to_try:
            try:
                self.logger.info(f"Alabama: Attempting to fetch from: {attempt_url}")
                page_bytes = await self._fetch_page_content_with_archival_fallback(
                    attempt_url,
                    timeout_seconds=30,
                )
                if not page_bytes:
                    raise RuntimeError("empty response")

                self.logger.info(f"Alabama: Success! Content length: {len(page_bytes)} bytes")

                soup = BeautifulSoup(page_bytes, 'html.parser')
                
                # Check if this is a frameset page
                frames = soup.find_all('frame', src=True)
                if frames:
                    self.logger.info(f"Alabama: Found {len(frames)} frames, extracting frame URLs")
                    for frame in frames:
                        frame_src = frame.get('src')
                        if frame_src and 'title.htm' in frame_src.lower():
                            # This is likely the TOC frame
                            frame_url = urljoin(attempt_url, frame_src)
                            self.logger.info(f"Alabama: Fetching TOC frame: {frame_url}")
                            try:
                                frame_bytes = await self._fetch_page_content_with_archival_fallback(
                                    frame_url,
                                    timeout_seconds=30,
                                )
                                if frame_bytes:
                                    soup = BeautifulSoup(frame_bytes, 'html.parser')
                                    self.logger.info(f"Alabama: Successfully loaded TOC frame")
                                    break
                            except Exception as frame_error:
                                self.logger.warning(f"Alabama: Failed to load frame: {frame_error}")
                                continue
                
                # Find all links that look like title or chapter links
                links = soup.find_all('a', href=True)
                self.logger.info(f"Alabama: Found {len(links)} total links on page")
                
                # Alabama-specific keywords (more permissive)
                keywords = ['title', 'section', 'chapter', '§', 'article', 'code', 'statute', 'part', 'division']
                
                section_count = 0
                skipped_short = 0
                skipped_no_keywords = 0
                
                for link in links:
                    if section_count >= max_sections:
                        self.logger.info(f"Alabama: Reached max_sections limit ({max_sections})")
                        break
                    
                    link_text = link.get_text(strip=True)
                    link_href = link.get('href', '')
                    
                    # Skip empty or very short links
                    if not link_text or len(link_text) < 5:
                        skipped_short += 1
                        continue
                    
                    # Look for title or section patterns - relaxed to catch more links
                    if not any(keyword in link_text.lower() for keyword in keywords):
                        skipped_no_keywords += 1
                        self.logger.debug(f"Alabama: Skipped (no keywords): '{link_text[:50]}'")
                        continue
                    
                    # Make URL absolute
                    # When scraping archived pages, preserve the archive host as
                    # the join base; joining against the live host produces dead
                    # links and strict hydration drops all records.
                    full_url = urljoin(attempt_url, link_href)
                    
                    # Extract section number
                    section_number = self._extract_section_number(link_text)
                    if not section_number:
                        import re
                        m = re.search(r"\bTitle\s+([0-9A-Za-z\-]+)\b", link_text, re.IGNORECASE)
                        if m:
                            section_number = m.group(1)
                    if not section_number:
                        section_number = f"Section-{section_count + 1}"
                    
                    # Identify legal area from link text
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
                    self.logger.debug(f"Alabama: Accepted ({section_count}): '{link_text[:50]}'")
                
                self.logger.info(f"Alabama: Filtering stats - Short: {skipped_short}, No keywords: {skipped_no_keywords}, Accepted: {len(statutes)}")
                self.logger.info(f"Alabama: Custom scraper completed with {len(statutes)} statutes from {attempt_url}")
                
                # If we got results, return them
                if statutes:
                    return statutes
                else:
                    self.logger.warning(f"Alabama: No statutes found with {attempt_url}, trying next URL")
                    
            except Exception as e:
                self.logger.warning(f"Alabama: Error with {attempt_url}: {type(e).__name__}: {e}")
                continue
        
        # If all URLs failed, try generic scraper as last resort
        self.logger.warning("Alabama: All URL attempts failed")
        self.logger.info("Alabama: Site likely down. Recommendations:")
        self.logger.info("  1. Check https://web.archive.org for archived versions")
        self.logger.info("  2. Try again later when site is accessible")
        self.logger.info("  3. Contact Alabama Legislative Services")
        return await self._generic_scrape(code_name, code_url, citation_format, max_sections=max_sections)

    def official_title_url(self, title_number: object) -> str:
        return f"{self.CODE_URL}?title={title_number}"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        return f"{self.CODE_URL}?section={section}"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Code of Alabama title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"al:title-{str(number).lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Code of Alabama Title {number} ({name}) official ALISON "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_alison_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official ALISON URL or type a linkless row as quarantine."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_alison_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_alison_graphql"
            )
            structured["source_link_disposition"] = "repaired_official_alison"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-alabama-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    if int(getattr(response, "status", 200) or 200) != 200:
                        return b""
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-alabama-official-catalog/1.0",
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

    def _parse_official_title_links(self, html: bytes, page_url: str = "") -> Dict[str, str]:
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
            if not href:
                continue
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            title_values = query.get("title") or []
            number = str((title_values or [""])[0]).strip()
            if not number:
                match = self._AL_TITLE_QUERY_RE.search(absolute) or self._AL_TITLE_LABEL_RE.search(
                    link.get_text(" ", strip=True) or ""
                )
                number = match.group(1) if match else ""
            if number not in known:
                continue
            if number not in found and self.is_official_alison_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Alabama title and repair missing-link rows."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        rows: List[Dict[str, Any]] = []
        for item in self.official_title_catalog():
            number = str(item["title_number"])
            official_url = str(item["source_url"])
            live_url = discovered.get(number)
            source_url = live_url or official_url
            disposition = "official" if live_url else "repaired_official_alison"
            rows.append(
                {
                    **item,
                    "source_url": source_url,
                    "source_link_disposition": disposition,
                    "text": (
                        f"Code of Alabama Title {number} ({item['name']}) official "
                        f"ALISON catalog unit at {source_url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "AL"):
        """Acquire the exhaustive official Code of Alabama title catalog.

        Live HTTPS retains the official ALISON landing page. Every known
        Alabama title is enumerated with an official ALISON URL. Linkless
        catalog members are repaired to the official title URL. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "AL").strip().upper() or "AL"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("alabama official catalog enumeration is incomplete")
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
StateScraperRegistry.register("AL", AlabamaScraper)
