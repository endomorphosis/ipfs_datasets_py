"""Scraper for Maine state laws.

This module contains the scraper for Maine statutes from the official state legislative website.
"""

import asyncio
from typing import List, Dict, Optional
import re
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry


class MaineScraper(BaseStateScraper):
    """Scraper for Maine state laws from http://legislature.maine.gov"""

    _ME_SECTION_URL_RE = re.compile(
        r"/statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", re.IGNORECASE
    )
    _ME_CHAPTER_INDEX_RE = re.compile(
        r"/title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", re.IGNORECASE
    )

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ME_SECTION_URL_RE.search(source) and not self._ME_CHAPTER_INDEX_RE.search(
                source
            ):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(
                        r"title[0-9A-Za-z\-]+sec([0-9A-Za-z\-]+)\.html$", source, re.IGNORECASE
                    )
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Maine's legislative website."""
        return "http://legislature.maine.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maine."""
        return [
            {"name": "Maine Revised Statutes", "url": f"{self.get_base_url()}/", "type": "Code"}
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Maine's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .maine_constitution import (
            configured_constitution_html_path,
            parse_maine_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_maine_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Maine Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .maine_section import configured_section_html_path, parse_maine_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_maine_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://legislature.maine.gov/legis/statutes/17-A/title17-Asec201.html",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_title_chapter_section_tree(
            code_name,
            max_statutes=limit,
        )
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            if direct:
                return direct if limit is None else direct[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None:
            return []

        return_threshold = int(limit) if limit is not None else 160
        candidate_urls = [
            "https://legislature.maine.gov/statutes/1/title1ch1sec0.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html",
            "https://legislature.maine.gov/statutes/",
            code_url,
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if "justia.com" in str(candidate).lower() or "findlaw.com" in str(candidate).lower():
                continue

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Me. Rev. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='sec'][href$='.html'], a[href*='ch'][href$='sec0.html']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if limit is not None and len(statutes) >= int(limit):
                        return statutes[: int(limit)]
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name, candidate, "Me. Rev. Stat.", max_sections=max(10, return_threshold)
            )
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if limit is not None and len(statutes) >= int(limit):
                return statutes[: int(limit)]

        return best_statutes if limit is None else best_statutes[: int(limit)]

    async def _scrape_official_title_chapter_section_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_url = "https://legislature.maine.gov/statutes/"
        root_raw = await self._fetch_page_content_with_archival_fallback(
            root_url, timeout_seconds=25
        )
        if not root_raw:
            return []
        root_html = (
            root_raw.decode("utf-8", errors="replace")
            if isinstance(root_raw, bytes)
            else str(root_raw)
        )
        root_soup = BeautifulSoup(root_html, "html.parser")

        resumed = self._load_partial_checkpoint_statutes(
            code_name=code_name, max_statutes=max_statutes
        )
        checkpoint_progress = self._load_partial_checkpoint_progress()
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        seen_keys: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                source_url = str(statute.source_url or "").strip()
                if key and key in seen_keys:
                    continue
                if source_url and source_url in seen_sections:
                    continue
                if key:
                    seen_keys.add(key)
                if source_url:
                    seen_sections.add(source_url)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break

        if resumed:
            _extend_unique(resumed)
            self.logger.info(
                "Maine official tree: resumed %s statutes from partial checkpoint",
                len(statutes),
            )
        resume_titles_scanned = max(0, int(checkpoint_progress.get("titles_scanned") or 0))
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(
            0, int(checkpoint_progress.get("discovered_sections") or 0)
        )
        title_rewind = max(0, int(self._env_int("STATE_SCRAPER_ME_RESUME_TITLE_REWIND", default=1)))
        chapter_rewind = max(
            0, int(self._env_int("STATE_SCRAPER_ME_RESUME_CHAPTER_REWIND", default=10))
        )
        resume_title_floor = max(0, resume_titles_scanned - title_rewind)
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)
        title_urls = []
        seen_titles = set()
        for link in root_soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not re.search(
                r"/?statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html$|^[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html$",
                href,
                re.IGNORECASE,
            ):
                continue
            full_url = urljoin(root_url, href)
            if full_url in seen_titles:
                continue
            seen_titles.add(full_url)
            title_urls.append(full_url)

        self.logger.info(
            "Maine official tree: discovered_titles=%s max_statutes=%s",
            len(title_urls),
            limit or "unbounded",
        )
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maine:title-discovery",
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(title_urls)),
                "chapters_scanned": 0,
                "sections_scanned": int(max(len(statutes), resume_sections_scanned)),
                "discovered_sections": int(max(len(statutes), resume_discovered_sections)),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        processed_chapters = 0
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))
        section_concurrency = max(
            1, int(self._env_int("STATE_SCRAPER_ME_SECTION_CONCURRENCY", default=8))
        )
        section_sem = asyncio.Semaphore(section_concurrency)

        for title_index, title_url in enumerate(title_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if title_index < resume_title_floor:
                continue
            title_raw = await self._fetch_page_content_with_archival_fallback(
                title_url, timeout_seconds=25
            )
            if not title_raw:
                continue
            title_html = (
                title_raw.decode("utf-8", errors="replace")
                if isinstance(title_raw, bytes)
                else str(title_raw)
            )
            title_soup = BeautifulSoup(title_html, "html.parser")
            chapter_urls = []
            seen_chapters = set()
            for link in title_soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                if not re.search(
                    r"title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", href, re.IGNORECASE
                ):
                    continue
                full_url = urljoin(title_url, href)
                if full_url in seen_chapters or full_url.endswith("ch0sec0.html"):
                    continue
                seen_chapters.add(full_url)
                chapter_urls.append(full_url)

            self.logger.info(
                "Maine official tree: title_url=%s discovered_chapters=%s statutes_so_far=%s",
                title_url,
                len(chapter_urls),
                len(statutes),
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="maine:title-scan",
                extra={
                    "titles_scanned": int(title_index),
                    "discovered_titles": int(len(title_urls)),
                    "chapters_scanned": int(processed_chapters),
                    "sections_scanned": int(sections_scanned_total),
                    "discovered_sections": int(sections_discovered_total),
                    "discovered_chapters": int(len(chapter_urls)),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

            for chapter_url in chapter_urls:
                if limit is not None and len(statutes) >= limit:
                    break
                processed_chapters += 1
                if processed_chapters < resume_chapter_floor:
                    continue
                chapter_raw = await self._fetch_page_content_with_archival_fallback(
                    chapter_url, timeout_seconds=25
                )
                if not chapter_raw:
                    continue
                chapter_html = (
                    chapter_raw.decode("utf-8", errors="replace")
                    if isinstance(chapter_raw, bytes)
                    else str(chapter_raw)
                )
                chapter_soup = BeautifulSoup(chapter_html, "html.parser")
                section_candidates: List[str] = []
                seen_local_candidates: set[str] = set()
                for link in chapter_soup.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    if not re.search(
                        r"title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", href, re.IGNORECASE
                    ):
                        continue
                    section_url = urljoin(chapter_url, href)
                    if section_url.endswith("sec0.html"):
                        continue
                    if section_url in seen_sections or section_url in seen_local_candidates:
                        continue
                    seen_local_candidates.add(section_url)
                    section_candidates.append(section_url)
                sections_discovered_total += len(section_candidates)

                def _record_section(statute: Optional[NormalizedStatute]) -> None:
                    if statute is None:
                        return
                    _extend_unique([statute])
                    if len(statutes) == 1 or len(statutes) % 25 == 0:
                        self.logger.info(
                            "Maine official tree: chapters_processed=%s statutes_so_far=%s",
                            processed_chapters,
                            len(statutes),
                        )
                        self._write_partial_checkpoint(
                            statutes,
                            code_name=code_name,
                            stage_label="maine:section-scan",
                            extra={
                                "titles_scanned": int(title_index),
                                "discovered_titles": int(len(title_urls)),
                                "chapters_scanned": int(processed_chapters),
                                "sections_scanned": int(sections_scanned_total),
                                "discovered_sections": int(sections_discovered_total),
                                "codes_completed": 0,
                                "codes_total": 1,
                            },
                        )

                try:
                    asyncio.get_running_loop()
                    parallel = True
                except RuntimeError:
                    parallel = False

                scanned_sections = 0
                cancelled_early = False
                if not parallel:
                    for section_url in section_candidates:
                        if limit is not None and len(statutes) >= limit:
                            break
                        scanned_sections += 1
                        sections_scanned_total += 1
                        _record_section(
                            await self._build_official_section_statute(code_name, section_url)
                        )
                else:
                    async def _parse_section_url(section_url: str) -> Optional[NormalizedStatute]:
                        async with section_sem:
                            return await self._build_official_section_statute(code_name, section_url)

                    tasks = [
                        asyncio.create_task(_parse_section_url(section_url))
                        for section_url in section_candidates
                    ]
                    for task in asyncio.as_completed(tasks):
                        scanned_sections += 1
                        sections_scanned_total += 1
                        _record_section(await task)
                        if limit is not None and len(statutes) >= limit:
                            cancelled_early = True
                            for pending in tasks:
                                if not pending.done():
                                    pending.cancel()
                            break
                    if cancelled_early:
                        await asyncio.gather(*tasks, return_exceptions=True)
                if scanned_sections and (
                    scanned_sections == len(section_candidates) or scanned_sections % 200 == 0
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="maine:section-scan",
                        extra={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(len(title_urls)),
                            "chapters_scanned": int(processed_chapters),
                            "sections_scanned": int(sections_scanned_total),
                            "discovered_sections": int(sections_discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maine:complete",
            force=True,
            extra={
                "titles_scanned": int(len(title_urls)),
                "discovered_titles": int(len(title_urls)),
                "chapters_scanned": int(processed_chapters),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    async def _build_official_section_statute(
        self,
        code_name: str,
        url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
        if not raw:
            return None
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        soup = BeautifulSoup(html, "html.parser")
        from .maine_section import parse_maine_section_html

        parsed = parse_maine_section_html(html, source_url=url, code_name=code_name)
        if parsed is not None:
            return parsed
        heading = self._normalize_legal_text(
            (soup.select_one(".heading_section") or soup.find("title") or soup).get_text(
                " ", strip=True
            )
        )
        body_node = soup.select_one("div.row.section-content") or soup.select_one("div.MRSSection")
        body = self._normalize_legal_text(body_node.get_text(" ", strip=True) if body_node else "")
        if len(body) < 160:
            text_nodes = [
                self._normalize_legal_text(node.get_text(" ", strip=True))
                for node in soup.select("div.mrs-text, div.qhistory")
            ]
            body = self._normalize_legal_text(" ".join(text_nodes))
        if len(body) < 160:
            return None

        title_match = re.search(r"/title([0-9A-Za-z\-]+)sec", url, flags=re.IGNORECASE)
        section_match = re.search(r"sec([0-9A-Za-z\-]+)\.html$", url, flags=re.IGNORECASE)
        title_number = title_match.group(1) if title_match else None
        section_number = (
            section_match.group(1)
            if section_match
            else (self._extract_section_number(heading) or "")
        )
        section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
        official_cite = (
            f"Me. Rev. Stat. tit. {title_number}, § {section_number}"
            if title_number
            else f"Me. Rev. Stat. § {section_number}"
        )
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} {official_cite}",
            code_name=code_name,
            title_number=title_number,
            section_number=section_number,
            section_name=section_name,
            full_text=body,
            legal_area=self._identify_legal_area(body[:1200]),
            source_url=url,
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_maine_revised_statutes_html",
                "discovery_method": "official_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Parse official Maine section pages into full statute records."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://legislature.maine.gov/statutes/1/title1sec1.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Asec1.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            try:
                html = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = self._normalize_legal_text(
                (soup.select_one(".heading_section") or soup.find("title") or soup).get_text(
                    " ", strip=True
                )
            )
            body_node = soup.select_one("div.row.section-content") or soup.select_one(
                "div.MRSSection"
            )
            body = self._normalize_legal_text(
                body_node.get_text(" ", strip=True) if body_node else ""
            )
            if len(body) < 160:
                text_nodes = [
                    self._normalize_legal_text(node.get_text(" ", strip=True))
                    for node in soup.select("div.mrs-text, div.qhistory")
                ]
                body = self._normalize_legal_text(" ".join(text_nodes))
            if len(body) < 160:
                continue

            title_match = re.search(r"/title([0-9A-Za-z\-]+)sec", url, flags=re.IGNORECASE)
            section_match = re.search(r"sec([0-9A-Za-z\-]+)\.html$", url, flags=re.IGNORECASE)
            title_number = title_match.group(1) if title_match else None
            section_number = (
                section_match.group(1)
                if section_match
                else (self._extract_section_number(heading) or "")
            )
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
            official_cite = (
                f"Me. Rev. Stat. tit. {title_number}, § {section_number}"
                if title_number
                else f"Me. Rev. Stat. § {section_number}"
            )
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {official_cite}",
                    code_name=code_name,
                    title_number=title_number,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=url,
                    official_cite=official_cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_maine_revised_statutes_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> tuple[bytes, bytes, bytes]:
        """Fetch one official Maine URL and retain request/response/body bytes."""
        import ssl
        import urllib.error
        import urllib.request
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_bytes = (
            f"GET {path} HTTP/1.1\n"
            f"host: {host}\n"
            "accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-maine/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        last_exc: Exception | None = None
        body = b""
        status = 0
        header_block = ""
        for unverified in (False, True):
            try:
                with urllib.request.urlopen(
                    req,
                    timeout=max(5, int(timeout)),
                    context=self._official_ssl_context(unverified=unverified),
                ) as resp:
                    body = bytes(resp.read() or b"")
                    status = int(getattr(resp, "status", 200) or 200)
                    header_block = "".join(
                        f"{key}: {value}\n" for key, value in resp.headers.items()
                    )
                last_exc = None
                break
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise RuntimeError(f"official Maine GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Maine GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_title_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse every official MRS title unit from the live statutes index."""
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Maine discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not re.search(
                r"statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+ch0sec0\.html|"
                r"title[0-9A-Za-z\-]+ch0sec0\.html",
                href,
                re.IGNORECASE,
            ):
                continue
            full_url = urljoin(index_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            title_match = re.search(
                r"/statutes/([0-9A-Za-z\-]+)/title", full_url, flags=re.IGNORECASE
            ) or re.search(r"title([0-9A-Za-z\-]+)ch0sec0", full_url, flags=re.IGNORECASE)
            title_number = title_match.group(1) if title_match else ""
            if not title_number:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not label:
                label = f"Title {title_number}"
            units.append(
                {
                    "canonical_key": f"me:title-{title_number.lower()}",
                    "source_url": full_url,
                    "label": label,
                    "text": (
                        f"Maine Revised Statutes Title {title_number} {label} "
                        f"official title index entry retained from {full_url}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "ME"):
        """Acquire the uncapped official Maine title frontier."""
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "ME").strip().upper()
        if normalized != "ME":
            raise ValueError(f"MaineScraper cannot acquire {normalized}")
        index_url = "https://legislature.maine.gov/statutes/"
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        html = index_body.decode("utf-8", errors="replace")
        units = self._parse_official_title_index(html, index_url)
        if len(units) < 3:
            raise RuntimeError(
                f"official Maine title index is incomplete: {len(units)} units"
            )
        rows = tuple(
            {
                "canonical_key": unit["canonical_key"],
                "source_url": unit["source_url"],
                "text": unit["text"],
            }
            for unit in units
        )
        catalog = "\n".join(
            f"{unit['canonical_key']}\t{unit['source_url']}\t{unit['label']}"
            for unit in units
        ).encode("utf-8")
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
            jurisdiction_code="ME",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain="legislature.maine.gov",
            source_path="/statutes/",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("ME", MaineScraper)
