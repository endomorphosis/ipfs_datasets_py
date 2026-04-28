"""Scraper for Alabama state laws."""

import asyncio
import hashlib
import json
import re
import time
from typing import List, Dict, Any

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class AlabamaScraper(BaseStateScraper):
    """Scraper for Alabama state laws from the public ALISON GraphQL API."""

    GRAPHQL_URL = "https://alison.legislature.state.al.us/graphql"
    CODE_URL = "https://alison.legislature.state.al.us/code-of-alabama"
    
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
        statutes = await self._scrape_alison_graphql(code_name, limit or 1000000)
        if statutes:
            return statutes

        self.logger.warning(
            "Alabama GraphQL returned no statutes; falling back to archival/custom scrape path"
        )
        return await self._custom_scrape_alabama(
            code_name,
            code_url or self.CODE_URL,
            "Ala. Code",
            max_sections=limit or 1000000,
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

    def _parse_scaffold_section_parent_ids(self, scaffold: str, limit: int) -> List[str]:
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
            if len(parent_ids) >= max(1, limit):
                break
        return parent_ids

    async def _scrape_alison_graphql(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        self.logger.info("Alabama GraphQL: fetching scaffold")
        scaffold_data = await self._graphql("query codeOfAlabamaScaffold { scaffold: codeOfAlabamaScaffold }")
        parent_ids = self._parse_scaffold_section_parent_ids(str(scaffold_data.get("scaffold") or ""), max_statutes)
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
        heartbeat_seconds = max(15.0, float(self._env_int("STATE_SCRAPER_HEARTBEAT_SECONDS", default=60)))
        last_heartbeat = time.monotonic()
        for offset in range(0, len(parent_ids), batch_size):
            data = await self._graphql(query, {"parentId": parent_ids[offset : offset + batch_size]})
            rows = ((data.get("codeItems") or {}).get("data") or [])
            for row in rows:
                if len(statutes) >= max_statutes:
                    return statutes
                if not row.get("isContentNode") or str(row.get("type") or "").lower() != "section":
                    continue
                display_id = str(row.get("displayId") or "").strip()
                content = str(row.get("content") or "")
                history = str(row.get("history") or "")
                text_parts = []
                if content:
                    text_parts.append(BeautifulSoup(content, "html.parser").get_text(" ", strip=True))
                if history:
                    history_text = BeautifulSoup(history, "html.parser").get_text(" ", strip=True)
                    if history_text:
                        text_parts.append(f"History: {history_text}")
                full_text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
                if not display_id or len(full_text) < 80:
                    continue
                title = re.sub(r"\s+", " ", str(row.get("title") or f"Section {display_id}")).strip()
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
                )
                statute.structured_data = {
                    "source_kind": "official_alison_graphql",
                    "skip_hydrate": True,
                    "code_id": row.get("codeId"),
                    "parent_id": row.get("parentId"),
                }
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


# Register this scraper with the registry
StateScraperRegistry.register("AL", AlabamaScraper)
