"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from archived official
Indiana General Assembly static-document chapter PDFs.
"""

import re
import subprocess
import os
from urllib.parse import quote, urljoin
from typing import Dict, List, Optional

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws from archived iga.in.gov sources."""

    _ARCHIVE_CHAPTER_PDFS = [
        "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
        "http://web.archive.org/web/20170127104730/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20200213045523/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20201111174818/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20170125194211/http://iga.in.gov/static-documents/0/0/6/f/006f3b19/SB0465.05.ENRS.pdf",
        "http://web.archive.org/web/20161229103815/http://iga.in.gov/static-documents/0/0/7/3/0073b205/SB0374.03.ENGS.pdf",
    ]
    _TITLE_ARTICLE_CHAPTER_RE = re.compile(
        r"TITLE(?P<title>\d+)_AR(?P<article>[0-9.]+)_ch(?P<chapter>\d+)\.pdf$",
        re.IGNORECASE,
    )
    _JUSTIA_TITLE_RE = re.compile(r"title\s*(\d+(?:\.\d+)?)", re.IGNORECASE)

    def get_base_url(self) -> str:
        """Return the base URL for Indiana's legislative website."""
        return "http://iga.in.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Indiana."""
        return [
            {
                "name": "Indiana Code",
                "url": "http://web.archive.org/web/20231201000000/http://iga.in.gov/legislative/laws/2023/ic/titles/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Indiana code statutes.

        Indiana's live site is currently SPA-only in headless contexts.
        We prefer stable Wayback chapter PDFs that contain substantial text.
        """
        return_threshold = self._bounded_return_threshold(30)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        if return_threshold < 30 and max_statutes is None:
            seed_pdfs = await self._scrape_seed_archive_pdfs(
                code_name=code_name,
                max_statutes=return_threshold,
            )
            if seed_pdfs:
                return seed_pdfs

        archival = await self._scrape_archived_chapter_pdfs(code_name=code_name, max_statutes=max(10, return_threshold))
        justia_titles: List[NormalizedStatute] = []
        title_page_statutes: List[NormalizedStatute] = []
        full_corpus = self._full_corpus_enabled()
        bounded_probe = max_statutes is not None
        justia_enabled = full_corpus or bounded_probe or self._env_flag("INDIANA_JUSTIA_ENABLE")
        title_pages_enabled = full_corpus or bounded_probe or self._env_flag("INDIANA_ARCHIVED_TITLE_PAGES_ENABLE")
        if justia_enabled:
            justia_titles = await self._scrape_archived_justia_titles(code_name=code_name, max_statutes=max(10, return_threshold))
        if title_pages_enabled:
            title_page_statutes = await self._scrape_archived_title_pages(code_name=code_name, max_statutes=max(10, return_threshold))

        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(archival)
        _merge(justia_titles)
        _merge(title_page_statutes)

        min_full_corpus_records = int(os.getenv("INDIANA_FULL_CORPUS_MIN_RECORDS", "30") or "30")
        if merged and (not full_corpus or len(merged) >= min_full_corpus_records):
            self.logger.info(f"Indiana archival fallback: Scraped {len(merged)} sections")
            return merged

        if full_corpus and merged:
            self.logger.warning(
                "Indiana archive/title recovery found only %s sections in full-corpus mode; trying generic recovery before accepting partial corpus",
                len(merged),
            )

        if full_corpus or self._env_flag("INDIANA_GENERIC_FALLBACK"):
            generic = await self._generic_scrape(code_name, code_url, "Ind. Code")
            _merge(generic)
            if merged:
                self.logger.info(f"Indiana recovery fallback: Scraped {len(merged)} sections")
                return merged

        self.logger.warning("Indiana official/archive direct crawl returned no statutes; skipping search/generic recovery fallback")
        return []

    async def _scrape_seed_archive_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        seen_ids = set()
        for pdf_url in self._ARCHIVE_CHAPTER_PDFS[: max(1, int(max_statutes or 1))]:
            statute = await self._build_statute_from_pdf_url(
                code_name=code_name,
                pdf_url=pdf_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if statute is None or statute.statute_id in seen_ids:
                continue
            seen_ids.add(statute.statute_id)
            statutes.append(statute)
        return statutes

    async def _scrape_archived_justia_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = "https://web.archive.org/web/20241203192652/https://law.justia.com/codes/indiana/2010/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(root_url, timeout_seconds=35)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        title_links: List[tuple[str, str]] = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            text = " ".join(link.get_text(" ", strip=True).split())
            if "TITLE" not in text.upper():
                continue
            if "/codes/indiana/2010/title" not in href:
                continue
            full_url = href if href.startswith("http") else f"https://web.archive.org{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            title_links.append((text, full_url))
            if len(title_links) >= max_statutes:
                break

        if title_links:
            link_graph_rows = await self._crawl_archived_justia_link_graph(
                code_name=code_name,
                seed_urls=[url for _, url in title_links],
                max_statutes=max_statutes,
            )
            if link_graph_rows:
                return link_graph_rows[:max_statutes]

        statutes: List[NormalizedStatute] = []
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")
        for title_text, title_url in title_links:
            if self._full_corpus_enabled() and crawl_limit <= 0:
                page_text = (
                    f"{title_text}. Archived Indiana Code title index discovered from the Justia 2010 Indiana Code root. "
                    "Deep article/chapter traversal is deferred for the targeted Indiana enrichment crawl."
                )
            else:
                try:
                    title_payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
                except Exception:
                    continue
                if not title_payload:
                    continue
                title_soup = BeautifulSoup(title_payload, "html.parser")
                page_text = " ".join(title_soup.get_text(" ", strip=True).split())
                if len(page_text) < 300:
                    continue
            match = self._JUSTIA_TITLE_RE.search(title_text)
            title_no = match.group(1) if match else title_text[:40]
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_no}",
                    code_name=code_name,
                    section_number=f"Title {title_no}",
                    section_name=title_text[:200],
                    full_text=page_text[:14000],
                    legal_area=self._identify_legal_area(title_text),
                    source_url=title_url,
                    official_cite=f"Ind. Code Title {title_no}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "archived_justia_indiana_title_index",
                        "discovery_method": "wayback_justia_root",
                        "record_type": "archived_justia_title_index",
                        "skip_hydrate": bool(self._full_corpus_enabled() and crawl_limit <= 0),
                    },
                )
            )
            if len(statutes) >= max_statutes:
                break

        if self._full_corpus_enabled() and crawl_limit > 0 and len(statutes) < max_statutes:
            remaining = max(0, int(max_statutes) - len(statutes))
            statutes.extend(
                await self._crawl_archived_justia_link_graph(
                    code_name=code_name,
                    seed_urls=[url for _, url in title_links],
                    max_statutes=remaining,
                )
            )

        return statutes

    async def _crawl_archived_justia_link_graph(
        self,
        *,
        code_name: str,
        seed_urls: List[str],
        max_statutes: int,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        seen_records = set()
        seen_pages = set()
        queue = list(seed_urls)
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")

        while queue and len(out) < max_statutes and len(seen_pages) < crawl_limit:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            if len(seen_pages) == 1 or len(seen_pages) % 25 == 0:
                self.logger.info(
                    "Indiana Justia link graph crawl progress: pages=%s queued=%s records=%s cap=%s",
                    len(seen_pages),
                    len(queue),
                    len(out),
                    crawl_limit,
                )
            try:
                payload = await self._fetch_page_content_with_archival_fallback(page_url, timeout_seconds=35)
            except Exception:
                payload = b""
            if not payload:
                continue

            soup = BeautifulSoup(payload, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = self._normalize_legal_text(link.get_text(" ", strip=True))
                if not href or not label:
                    continue

                abs_url = href if href.startswith("http") else urljoin(page_url, href)
                abs_url = self._canonicalize_statute_url(abs_url)
                lower_url = abs_url.lower()
                lower_label = label.lower()
                if "accounts.justia.com" in lower_url or "/signin" in lower_url:
                    continue
                if "*" in abs_url:
                    continue
                if "/codes/indiana/2010/" not in lower_url:
                    continue

                is_index = any(part in lower_url for part in ("/title", "/ar", "/ch")) and (
                    lower_url.endswith("/")
                    or lower_url.endswith("/index.html")
                    or lower_url.endswith(".html")
                )
                if is_index and abs_url not in seen_pages and len(seen_pages) + len(queue) < crawl_limit:
                    queue.append(abs_url)

                looks_statutory = (
                    self._is_probable_statute_link(label, abs_url, page_url)
                    or "article" in lower_label
                    or "chapter" in lower_label
                    or re.search(r"\b(?:ic|sec\.|section)\s*\d", lower_label, re.IGNORECASE)
                )
                if not looks_statutory:
                    continue

                section_number = self._extract_section_number(label)
                if not section_number:
                    section_number = self._derive_section_number_from_url(abs_url)
                if not section_number:
                    section_number = f"Justia-{len(out) + 1}"

                key = f"{section_number}|{abs_url}".lower()
                if key in seen_records:
                    continue
                seen_records.add(key)
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=label[:200],
                        full_text=f"Section {section_number}: {label}",
                        legal_area=self._identify_legal_area(label),
                        source_url=abs_url,
                        official_cite=f"Ind. Code § {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "archived_justia_indiana_code",
                            "discovery_method": "wayback_justia_link_graph",
                            "record_type": "archived_justia_link",
                        },
                    )
                )
                if len(out) >= max_statutes:
                    break

        return out

    async def _scrape_archived_title_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        discovery_limit = 5000 if self._full_corpus_enabled() else 420
        title_urls = await self._discover_archived_title_urls(limit=discovery_limit)
        out: List[NormalizedStatute] = []
        seen = set()
        queued = set()
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")

        for title_url in title_urls:
            if len(out) >= max_statutes:
                break
            queue = [title_url]
            queued.add(title_url)
            pages_seen = 0
            while queue and len(out) < max_statutes and pages_seen < crawl_limit:
                page_url = queue.pop(0)
                pages_seen += 1
                try:
                    payload = await self._fetch_page_content_with_archival_fallback(page_url, timeout_seconds=35)
                except Exception:
                    payload = b""
                if not payload:
                    continue

                try:
                    from bs4 import BeautifulSoup
                except ImportError:
                    return out

                soup = BeautifulSoup(payload, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    label = self._normalize_legal_text(link.get_text(" ", strip=True))
                    if not href or not label:
                        continue

                    abs_url = href if href.startswith("http") else urljoin(page_url, href)
                    abs_url = self._canonicalize_statute_url(abs_url)
                    lower_url = abs_url.lower()
                    lower_label = label.lower()
                    if "accounts.justia.com" in lower_url or "/signin" in lower_url:
                        continue
                    if "/codes/indiana/2010/" not in lower_url:
                        continue

                    is_index = any(part in lower_url for part in ("/title", "/ar", "/ch")) and (
                        lower_url.endswith("/")
                        or lower_url.endswith("/index.html")
                        or lower_url.endswith(".html")
                    )
                    if is_index and abs_url not in queued and len(queued) < crawl_limit:
                        queued.add(abs_url)
                        queue.append(abs_url)

                    looks_statutory = (
                        self._is_probable_statute_link(label, abs_url, page_url)
                        or "article" in lower_label
                        or "chapter" in lower_label
                        or re.search(r"\b(?:ic|sec\.|section)\s*\d", lower_label, re.IGNORECASE)
                    )
                if not looks_statutory:
                    continue

                section_number = self._extract_section_number(label)
                if not section_number:
                    section_number = self._derive_section_number_from_url(abs_url)
                if not section_number:
                    continue

                if lower_label.startswith("article ") or lower_label.startswith("title "):
                    continue

                key = f"{section_number}|{abs_url}".lower()
                if key in seen:
                    continue
                statute = await self._build_archived_justia_link_statute(
                    code_name=code_name,
                    section_number=section_number,
                    label=label,
                    source_url=abs_url,
                )
                if statute is None:
                    continue
                seen.add(key)
                out.append(statute)
                if len(out) >= max_statutes:
                    break

        return out

    async def _build_archived_justia_link_statute(
        self,
        *,
        code_name: str,
        section_number: str,
        label: str,
        source_url: str,
    ) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=35)
        except Exception:
            payload = b""
        if not payload:
            return None

        soup = BeautifulSoup(payload, "html.parser")
        content_text = self._normalize_legal_text(self._extract_best_content_text(str(soup)))
        content_text = re.split(r"\bDisclaimer:\b", content_text, maxsplit=1)[0].strip()
        content_text = re.split(r"\bAsk a Lawyer\b", content_text, maxsplit=1)[0].strip()
        content_text = re.sub(r"\s+", " ", content_text).strip()
        if len(content_text) < 240:
            return None

        heading = ""
        heading_node = soup.select_one("h1") or soup.select_one("title")
        if heading_node is not None:
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or label or f"Section {section_number}")[:200],
            full_text=content_text[:14000],
            legal_area=self._identify_legal_area(heading or label),
            source_url=source_url,
            official_cite=f"Ind. Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "archived_justia_indiana_code",
                "discovery_method": "wayback_justia_link_graph",
                "record_type": "archived_justia_link",
                "skip_hydrate": True,
            },
        )

    async def _discover_archived_title_urls(self, limit: int = 160) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/legislative/laws/*/ic/titles/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._request_bytes_direct(cdx_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    async def _scrape_archived_chapter_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_ids = set()

        candidate_urls = list(self._ARCHIVE_CHAPTER_PDFS)
        for discovered_url in await self._discover_archived_pdf_urls(limit=max(max_statutes * 8, 200)):
            if discovered_url not in candidate_urls:
                candidate_urls.append(discovered_url)

        for pdf_url in candidate_urls:
            if len(statutes) >= max_statutes:
                break

            statute = await self._build_statute_from_pdf_url(code_name=code_name, pdf_url=pdf_url, headers=headers)
            if statute is None:
                continue
            if statute.statute_id in seen_ids:
                continue

            seen_ids.add(statute.statute_id)
            statutes.append(statute)

        return statutes

    async def _discover_archived_pdf_urls(self, limit: int = 240) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/static-documents/*.pdf"
            "&output=json"
            "&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original or not original.lower().endswith(".pdf"):
                continue
            if not self._TITLE_ARTICLE_CHAPTER_RE.search(original):
                continue
            out.append(f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}")

        return out

    async def _build_statute_from_pdf_url(
        self,
        code_name: str,
        pdf_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        doc_id = self._extract_doc_id(pdf_url)
        if not doc_id:
            return None

        pdf_bytes = await self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=45)
        if not pdf_bytes:
            return None

        full_text = self._extract_pdf_text(pdf_bytes, max_chars=14000)
        if len(full_text) < 280:
            # Preserve discoverable archived statute PDFs even when extraction is partial.
            full_text = (
                f"Archived Indiana Code document for {doc_id}. "
                "Source PDF was reachable but full text extraction was limited in this run."
            )

        section_name = f"Indiana Code {doc_id}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {doc_id}",
            code_name=code_name,
            section_number=doc_id,
            section_name=section_name,
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=pdf_url,
            official_cite=f"Ind. Code {doc_id}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_indiana_archived_chapter_pdf",
                "discovery_method": "wayback_static_document_pdf",
                "skip_hydrate": True,
            },
        )

    def _extract_doc_id(self, pdf_url: str) -> str:
        match = self._TITLE_ARTICLE_CHAPTER_RE.search(str(pdf_url or ""))
        if match:
            title = str(int(match.group("title")))
            article = match.group("article")
            chapter = str(int(match.group("chapter")))
            return f"tit. {title}, art. {article}, ch. {chapter}"

        filename = str(pdf_url or "").rsplit("/", 1)[-1]
        filename = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        filename = re.sub(r"[^A-Za-z0-9._-]+", " ", filename).strip()
        return filename[:80] if filename else "archived-pdf"

    async def _request_bytes(self, pdf_url: str, headers: Dict[str, str], timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        # Wayback often serves an HTML shell unless we request iframe/raw replay.
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                payload = await self._request_bytes_direct(candidate, headers=headers, timeout=timeout)
                if payload and self._looks_like_pdf_bytes(payload):
                    return payload
            except Exception:
                continue

        return b""

    @staticmethod
    def _env_flag(name: str) -> bool:
        return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}

    async def _request_bytes_direct(self, url: str, headers: Dict[str, str], timeout: int) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers=headers or {"User-Agent": "Mozilla/5.0"},
                    timeout=(min(5, max(1, timeout)), max(1, timeout)),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=max(2, timeout + 2))
        except TimeoutError:
            payload = b""
        except Exception:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload

    def _to_wayback_iframe_url(self, url: str) -> str:
        if not url or "web.archive.org/web/" not in url:
            return ""

        if "/if_/" in url:
            return url

        return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", url, count=1)

    @staticmethod
    def _looks_like_pdf_bytes(payload: bytes) -> bool:
        return bool(re.match(rb"^\s*%PDF-", bytes(payload or b"")[:512], re.IGNORECASE))

    def _extract_pdf_text(self, pdf_bytes: bytes, max_chars: int) -> str:
        """Extract text using pdftotext if available in the runtime."""
        if not self._looks_like_pdf_bytes(pdf_bytes):
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
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]


# Register this scraper with the registry
StateScraperRegistry.register("IN", IndianaScraper)
