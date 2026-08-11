"""Scraper for Georgia state laws.

Official-source path walks the Georgia General Assembly HTML tree on
legis.ga.gov. Secondary Justia mirrors are never sole-admitted for full-corpus
certification unless explicitly allowed by environment flag.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from https://www.legis.ga.gov."""

    _GA_TITLE_RE = re.compile(r"/legislation/georgia-code/title-([0-9A-Za-z-]+)/?$", re.IGNORECASE)
    _GA_CHAPTER_RE = re.compile(
        r"/legislation/georgia-code/title-[0-9A-Za-z-]+/chapter-([0-9A-Za-z-]+)/?$",
        re.IGNORECASE,
    )
    _GA_SECTION_RE = re.compile(
        r"/legislation/georgia-code/title-[0-9A-Za-z-]+/chapter-[0-9A-Za-z-]+/"
        r"section-([0-9A-Za-z.-]+)/?$",
        re.IGNORECASE,
    )
    _GA_JUSTIA_SECTION_RE = re.compile(
        r"/codes/georgia/(?:\d{4}/)?title-[^/]+/.*/section-[^/]+/?$",
        re.IGNORECASE,
    )
    _GA_SECTION_NUMBER_RE = re.compile(r"/section-([^/]+)/?$", re.IGNORECASE)

    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "https://www.legis.ga.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [
            {
                "name": "Official Code of Georgia",
                "url": f"{self.get_base_url()}/legislation/georgia-code",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Georgia code from the official General Assembly HTML tree first."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        official = await self._scrape_official_georgia_code(
            code_name=code_name,
            code_url=code_url,
            max_statutes=limit,
        )
        if official:
            return official[:limit] if limit is not None else official

        # Bounded recovery: official summary PDFs (not secondary mirrors).
        if not self._full_corpus_enabled() or self._env_enabled(
            "GEORGIA_SUMMARY_PDF_FALLBACK", default=False
        ):
            summary = await self._scrape_general_statute_summary_pdfs(code_name)
            if summary:
                return summary[:limit] if limit is not None else summary

        # Optional secondary Justia path — never sole-admit under full corpus.
        allow_justia = self._env_enabled("GEORGIA_JUSTIA_ENABLE", default=False) or self._env_enabled(
            "STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK", default=False
        )
        if allow_justia and not self._full_corpus_enabled():
            justia = await self._scrape_justia_year(
                code_name,
                year="2024",
                max_statutes=max(10, limit or 40),
            )
            justia = self._filter_non_code_results(justia)
            if justia:
                return justia[:limit] if limit is not None else justia

        self.logger.warning(
            "Georgia official direct crawl returned no statutes; refusing secondary sole-admission"
        )
        return []

    @staticmethod
    def _env_enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            allow_justia_section = bool(self._GA_JUSTIA_SECTION_RE.search(url))
            allow_summary_pdf = url.endswith("25sumdoc.pdf") or "general-statutes-summary-pdf.pdf" in url
            allow_official_section = bool(self._GA_SECTION_RE.search(url))
            if any(
                hint in url
                for hint in [
                    "dds.georgia.gov",
                    "dol.georgia.gov",
                    "lexisnexis.com/hottopics/gacode",
                ]
            ):
                continue
            if "temporary error. please try again" in text or "complete the security check before continuing" in text:
                continue
            if "law.justia.com" in url and not allow_justia_section:
                continue
            if "legis.ga.gov" in url and not (
                allow_summary_pdf or allow_official_section or "/api/document/docs/" in url
            ):
                continue
            out.append(statute)
        return out

    async def _fetch_official_ga_html(self, url: str, timeout_seconds: int = 18) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 18))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-georgia-code-scraper/3.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=(min(5, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                return bytes(response.content or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
            return payload.decode("utf-8", errors="replace")
        return ""

    async def _scrape_official_georgia_code(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        index_url = code_url or f"{self.get_base_url()}/legislation/georgia-code"
        title_links = await self._discover_title_links(index_url)
        self.logger.info("Georgia official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Georgia official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_url, chapter_label in chapter_links:
                if max_statutes is not None and len(statutes) >= max_statutes:
                    break
                section_links = await self._discover_section_links(chapter_url)
                for section_url, section_label in section_links:
                    if max_statutes is not None and len(statutes) >= max_statutes:
                        break
                    statute = await self._parse_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        title_label=title_label,
                        chapter_label=chapter_label,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _discover_title_links(self, index_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(index_url, self._GA_TITLE_RE)

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(title_url, self._GA_CHAPTER_RE)

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(chapter_url, self._GA_SECTION_RE)

    async def _discover_links(self, page_url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_ga_html(page_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            if not pattern.search(href.rstrip("/")):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    async def _parse_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        title_label: str,
        chapter_label: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_ga_html(section_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            node.decompose()

        main = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one(".statute-content")
            or soup.select_one("body")
        )
        if main is None:
            return None
        full_text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(full_text) < 80:
            return None

        match = self._GA_SECTION_RE.search(section_url.rstrip("/"))
        section_number = match.group(1) if match else ""
        if not section_number:
            match = re.search(r"\b(\d+[A-Za-z]?-\d+[A-Za-z0-9.-]*)\b", section_label)
            section_number = match.group(1) if match else section_label
        section_number = str(section_number or "").strip()
        if not section_number:
            return None

        title_match = self._GA_TITLE_RE.search(section_url)
        chapter_match = self._GA_CHAPTER_RE.search(section_url)
        heading = self._normalize_legal_text(
            (soup.select_one("h1") or soup.select_one("h2") or soup.select_one("title") or main).get_text(
                " ", strip=True
            )
        )
        section_name = section_label or heading or f"Section {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_match.group(1) if title_match else None,
            title_name=title_label or None,
            chapter_number=chapter_match.group(1) if chapter_match else None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text[:14000],
            legal_area=self._identify_legal_area(section_name or chapter_label or title_label),
            source_url=section_url.rstrip("/") + "/",
            official_cite=f"Ga. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_georgia_code_html",
                "discovery_method": "official_title_chapter_section_index",
                "skip_hydrate": True,
            },
        )

    async def _scrape_justia_year(self, code_name: str, year: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        year_url = f"https://law.justia.com/codes/georgia/{year}/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(year_url, timeout_seconds=40)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        section_urls: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(year_url, str(anchor.get("href") or "").strip())
            if not self._GA_JUSTIA_SECTION_RE.search(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            section_urls.append(href)
            if len(section_urls) >= max(1, int(max_statutes) * 4):
                break

        statutes: List[NormalizedStatute] = []
        for index, section_url in enumerate(section_urls, start=1):
            statute = await self._build_justia_statute(
                code_name=code_name,
                section_url=section_url,
                fallback_number=str(index),
            )
            if statute is None:
                continue
            statutes.append(statute)
            if len(statutes) >= max_statutes:
                break
        return statutes

    async def _build_justia_statute(
        self, *, code_name: str, section_url: str, fallback_number: str
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
        except Exception:
            return None
        if not payload:
            return None

        html = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        soup = BeautifulSoup(html, "html.parser")
        content_node = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if content_node is None:
            return None

        full_text = self._extract_best_content_text(str(content_node))
        full_text = re.split(r"\bDisclaimer:\b", full_text, maxsplit=1)[0].strip()
        full_text = re.split(r"\bAsk a Lawyer\b", full_text, maxsplit=1)[0].strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) < 280:
            return None

        heading_node = soup.select_one("h1") or soup.select_one("title")
        heading = " ".join((heading_node.get_text(" ", strip=True) if heading_node else "").split())
        match = self._GA_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else fallback_number

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or f"Georgia Code {section_number}")[:200],
            full_text=full_text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Ga. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={"source_kind": "secondary_justia_georgia"},
        )

    async def _scrape_general_statute_summary_pdfs(self, code_name: str) -> List[NormalizedStatute]:
        """Use official GA-hosted General Statutes summary PDFs as strict-safe fallback."""
        candidate_docs = [
            (
                "2025",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/25sumdoc.pdf?sfvrsn=95973fc9_4",
            ),
            (
                "2024",
                "https://www.legis.ga.gov/api/document/docs/default-source/legislative-counsel-document-library/2024-general-statutes-summary-pdf.pdf?sfvrsn=38862f9_8",
            ),
        ]

        statutes: List[NormalizedStatute] = []
        for year, pdf_url in candidate_docs:
            text = ""
            for _ in range(2):
                text = await self._extract_pdf_text_summary(pdf_url)
                if len(text) >= 280:
                    break
            if len(text) < 280:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § Summary-{year}",
                code_name=code_name,
                section_number=year,
                section_name=f"Summary of {year} General Statutes",
                full_text=text,
                legal_area="general",
                source_url=pdf_url,
                official_cite=f"Ga. Gen. Stat. Summary ({year})",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_summary_pdf",
                    "skip_hydrate": True,
                    "coverage_note": "summary_fallback_not_full_code_corpus",
                },
            )
            statutes.append(statute)

        if statutes:
            self.logger.info("Georgia summary PDF fallback: Scraped %s records", len(statutes))
        return statutes

    async def _extract_pdf_text_summary(self, pdf_url: str, max_chars: int = 12000) -> str:
        try:
            payload = await self._fetch_pdf_bytes_direct(pdf_url, timeout_seconds=45)
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug("Georgia PDF download failed for %s: %s", pdf_url, exc)
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="ga_sum_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "summary.pdf"
                txt_path = Path(tmpdir) / "summary.txt"
                pdf_path.write_bytes(payload)

                result = subprocess.run(
                    ["pdftotext", "-f", "1", "-l", "12", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except Exception as exc:
            self.logger.debug("Georgia PDF extraction failed for %s: %s", pdf_url, exc)
            return ""

    async def _fetch_pdf_bytes_direct(self, url: str, timeout_seconds: int = 45) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        timeout = max(5, int(timeout_seconds or 45))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-georgia-code-scraper/3.0",
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                    timeout=(min(10, timeout), timeout),
                )
                if int(response.status_code or 0) != 200:
                    return b""
                payload = bytes(response.content or b"")
                if not payload.startswith(b"%PDF"):
                    return b""
                return payload
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except TimeoutError:
            payload = b""

        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload


StateScraperRegistry.register("GA", GeorgiaScraper)
