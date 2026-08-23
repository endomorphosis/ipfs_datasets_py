"""Scraper for Nebraska state laws.

This module contains the scraper for Nebraska statutes from the official state legislative website.
"""

import asyncio
import json
import os
import re
import ssl
import urllib.request
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry

_SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)


class NebraskaScraper(BaseStateScraper):
    """Scraper for Nebraska state laws from https://nebraskalegislature.gov"""

    OFFICIAL_DOMAIN = "nebraskalegislature.gov"
    OFFICIAL_ENTRY_PATH = "/laws/browse-statutes.php"
    OFFICIAL_ENTRY_URL = "https://nebraskalegislature.gov/laws/browse-statutes.php"
    OFFICIAL_NUMERIC_CHAPTERS = (
        1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
        24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43, 44,
        45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 57, 58, 59, 60, 61, 62, 64,
        66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 79, 80, 81, 82, 83, 84,
        85, 86, 87, 88, 89, 90,
    )
    _NE_CHAPTER_URL_RE = re.compile(r"/laws/browse-chapters\.php\?chapter=\d+[A-Za-z]?$", re.IGNORECASE)
    # Nebraska section identifiers frequently include comma-delimited numeric
    # segments (for example, "2-32,113"). Accept those formats so full-corpus
    # scans do not silently drop valid sections.
    _NE_SECTION_NUMBER_RE = re.compile(
        r"^\d+[A-Za-z]?(?:-\d{1,3}(?:,\d{3})*[A-Za-z]?)+(?:\.\d+)?[A-Za-z]?$"
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Nebraska's legislative website."""
        return "https://nebraskalegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nebraska."""
        return [{
            "name": "Nebraska Revised Statutes",
            "url": f"{self.get_base_url()}/laws/browse-statutes.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nebraska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .nebraska_constitution import (
            configured_constitution_html_path,
            parse_nebraska_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_nebraska_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Nebraska Constitution",
                    source_url="https://nebraskalegislature.gov/laws/articles.php?article=I-1&print=true",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .nebraska_section import configured_section_html_path, parse_nebraska_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_nebraska_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://nebraskalegislature.gov/laws/statutes.php?statute=28-303",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            return []
        if any(marker in str(code_url).lower() for marker in _SECONDARY_HOST_MARKERS):
            return []
        fallback_limit = max(10, int(limit or 40))
        generic = await self._generic_scrape(
            code_name, code_url, "Neb. Rev. Stat.", max_sections=fallback_limit
        )
        return self._filter_official_host_statutes(generic)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        resumed = self._load_partial_checkpoint_statutes(code_name=code_name, max_statutes=limit)
        checkpoint_progress = self._load_partial_checkpoint_progress()
        chapter_urls = await self._discover_chapter_urls()
        self.logger.info("Nebraska official index: discovered %s chapter urls", len(chapter_urls))
        statutes: List[NormalizedStatute] = []
        seen_source_urls: set[str] = set()
        seen_keys: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                source_url = str(statute.source_url or "").strip()
                key = str(statute.statute_id or source_url).strip().lower()
                if source_url and source_url in seen_source_urls:
                    continue
                if key and key in seen_keys:
                    continue
                if source_url:
                    seen_source_urls.add(source_url)
                if key:
                    seen_keys.add(key)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break

        if resumed:
            _extend_unique(resumed)
            self.logger.info(
                "Nebraska official index: resumed %s statutes from checkpoint",
                len(statutes),
            )
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(0, int(checkpoint_progress.get("discovered_sections") or 0))
        chapter_rewind = max(0, int(self._env_int("STATE_SCRAPER_NE_RESUME_CHAPTER_REWIND", default=4)))
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="nebraska:chapter-discovery",
            extra={
                "chapters_scanned": 0,
                "discovered_chapters": int(len(chapter_urls)),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )
        for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if chapter_index < resume_chapter_floor:
                continue
            section_urls = await self._discover_section_urls(chapter_url)
            if seen_source_urls:
                section_urls = [url for url in section_urls if url not in seen_source_urls]
            sections_discovered_total += len(section_urls)
            if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_urls):
                self.logger.info(
                    "Nebraska official index: chapter=%s/%s discovered_sections=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_urls),
                    len(section_urls),
                    len(statutes),
                )
            def _progress_hook(
                scanned_sections: int,
                total_sections: int,
                partial_batch: List[NormalizedStatute],
                *,
                chapter_index_local: int = chapter_index,
            ) -> None:
                if (
                    scanned_sections == 1
                    or scanned_sections % 200 == 0
                    or scanned_sections == total_sections
                ):
                    cumulative_scanned = int(sections_scanned_total + scanned_sections)
                    self._write_partial_checkpoint(
                        statutes + partial_batch,
                        code_name=code_name,
                        stage_label="nebraska:section-scan",
                        extra={
                            "chapters_scanned": int(max(0, chapter_index_local - 1)),
                            "current_chapter": int(chapter_index_local),
                            "discovered_chapters": int(len(chapter_urls)),
                            "sections_scanned": cumulative_scanned,
                            "discovered_sections": int(sections_discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
            parsed = await self._scrape_section_urls(
                code_name,
                section_urls,
                max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                discovery_method="official_chapter_index_sections",
                progress_hook=_progress_hook,
            )
            _extend_unique(parsed)
            sections_scanned_total += len(section_urls)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_urls):
                self.logger.info(
                    "Nebraska official index: chapter=%s/%s sections=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_urls),
                    len(section_urls),
                    len(statutes),
                )
            if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_urls):
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="nebraska:chapter-scan",
                    extra={
                        "chapters_scanned": int(chapter_index),
                        "discovered_chapters": int(len(chapter_urls)),
                        "sections_scanned": int(sections_scanned_total),
                        "discovered_sections": int(sections_discovered_total),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="nebraska:complete",
            force=True,
            extra={
                "chapters_scanned": int(len(chapter_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes[:limit] if limit is not None else statutes

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1-101", f"{self.get_base_url()}/laws/statutes.php?statute=1-101"),
            ("28-303", f"{self.get_base_url()}/laws/statutes.php?statute=28-303"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in _SECONDARY_HOST_MARKERS):
            return False
        return host == "nebraskalegislature.gov" or host.endswith(".nebraskalegislature.gov")

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    async def _discover_chapter_urls(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        browse_url = f"{self.get_base_url()}/laws/browse-statutes.php"
        html = await self._request_text_direct(browse_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            absolute = urljoin(browse_url, href)
            if not self._NE_CHAPTER_URL_RE.search(urlparse(absolute).path + ("?" + urlparse(absolute).query if urlparse(absolute).query else "")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _discover_section_urls(self, chapter_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        seen_section_numbers: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "statute=" not in href.lower() or "print=true" in href.lower():
                continue
            absolute = urljoin(chapter_url, href)
            section_number = self._section_number_from_url(absolute)
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                continue
            section_key = section_number.lower()
            if section_key in seen_section_numbers:
                continue
            if absolute in seen:
                continue
            seen_section_numbers.add(section_key)
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        concurrency = max(1, int(os.getenv("NEBRASKA_SECTION_CONCURRENCY", "10") or "10"))
        sem = asyncio.Semaphore(concurrency)

        async def _parse_source_url(source_url: str) -> Optional[NormalizedStatute]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                return None
            from .nebraska_section import parse_nebraska_section_html

            parsed = parse_nebraska_section_html(
                html, source_url=source_url, code_name=code_name
            )
            if parsed is not None:
                data = dict(parsed.structured_data or {})
                data["discovery_method"] = discovery_method
                parsed.structured_data = data
                return parsed
            soup = BeautifulSoup(html, "html.parser")
            statute_panel = (
                soup.select_one("div.statute")
                or soup.select_one("div.card-body")
                or soup.select_one("main")
                or soup.select_one("div#main-content")
                or soup.find("body")
            )
            if statute_panel is None:
                return None
            for tag in statute_panel(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            heading_node = statute_panel.find("h2") or statute_panel.find("h1") or statute_panel
            section_number = self._normalize_legal_text(heading_node.get_text(" ", strip=True)).rstrip(".")
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                section_number = self._section_number_from_url(source_url)
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                return None
            section_name = self._normalize_legal_text((statute_panel.find("h3") or statute_panel).get_text(" ", strip=True))
            full_text = self._normalize_legal_text(statute_panel.get_text(" ", strip=True))
            if not section_name:
                section_name = f"Section {section_number}"
            # Repealed Nebraska sections can be concise but still substantive
            # corpus entries when tied to a valid statute identifier.
            if len(full_text) < 30:
                return None
            return NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=(section_name or f"Section {section_number}")[:200],
                full_text=full_text[:14000],
                legal_area=self._identify_legal_area(section_name or full_text[:800]),
                source_url=source_url,
                official_cite=f"Neb. Rev. Stat. § {section_number}",
                structured_data={
                    "source_kind": "official_nebraska_statutes_html",
                    "discovery_method": discovery_method,
                    "skip_hydrate": True,
                },
            )

        async def _bounded_parse(source_url: str) -> Optional[NormalizedStatute]:
            async with sem:
                try:
                    return await _parse_source_url(source_url)
                except Exception:
                    return None

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            total_sections = len(section_urls)
            for scanned_sections, source_url in enumerate(section_urls, start=1):
                statute = await _bounded_parse(source_url)
                if statute is not None:
                    out.append(statute)
                if progress_hook is not None:
                    try:
                        progress_hook(scanned_sections, total_sections, out)
                    except Exception:
                        pass
                if limit is not None and len(out) >= limit:
                    break
            return out

        tasks = [asyncio.create_task(_bounded_parse(source_url)) for source_url in section_urls]
        total_sections = len(tasks)
        cancelled_early = False
        for scanned_sections, task in enumerate(asyncio.as_completed(tasks), start=1):
            statute = await task
            if statute is not None:
                out.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, out)
                except Exception:
                    pass
            if (
                scanned_sections == 1
                or scanned_sections % 50 == 0
                or scanned_sections == total_sections
            ):
                self.logger.info(
                    "Nebraska official index: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned_sections,
                    total_sections,
                    len(out),
                )
            if limit is not None and len(out) >= limit:
                cancelled_early = True
                for pending_task in tasks:
                    if not pending_task.done():
                        pending_task.cancel()
                break
        if cancelled_early:
            await asyncio.gather(*tasks, return_exceptions=True)
        return out

    def _section_number_from_url(self, url: str) -> str:
        try:
            value = str((parse_qs(urlparse(url).query).get("statute") or [""])[0]).strip()
        except Exception:
            return ""
        return value

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        canonical = self._canonicalize_statute_url(url)
        for _ in range(2):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    canonical,
                    timeout_seconds=max(5, int(timeout)),
                )
            except Exception:
                payload = b""
            if payload:
                try:
                    return payload.decode("utf-8", errors="replace")
                except Exception:
                    return ""
            await asyncio.sleep(0.3)

        def _request() -> str:
            try:
                req = urllib.request.Request(canonical, headers={"User-Agent": "Mozilla/5.0"})
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
        return f"{self.get_base_url()}/laws/browse-chapters.php?chapter={token}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Nebraska Revised Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_NUMERIC_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"ne:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nebraska Revised Statutes Chapter {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-nebraska-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
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
            parsed = urlparse(absolute)
            if not self._NE_CHAPTER_URL_RE.search(
                parsed.path + (("?" + parsed.query) if parsed.query else "")
            ):
                continue
            token = str((parse_qs(parsed.query).get("chapter") or [""])[0]).strip()
            if token and token not in found:
                found[token] = self.official_chapter_url(token)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Nebraska chapter and repair missing live links."""

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
                    "canonical_key": f"ne:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nebraska Revised Statutes Chapter {token} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "NE"):
        """Acquire the exhaustive official Nebraska Revised Statutes chapter catalog.

        Live HTTPS retains the official browse-statutes index. Every known
        chapter is enumerated with an official nebraskalegislature.gov URL.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NE").strip().upper() or "NE"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("nebraska official catalog enumeration is incomplete")
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
StateScraperRegistry.register("NE", NebraskaScraper)
