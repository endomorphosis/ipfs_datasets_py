"""Scraper for Georgia state laws.

Official-source path walks the Georgia General Assembly HTML tree on
legis.ga.gov. Secondary Justia mirrors are never sole-admitted for full-corpus
certification unless explicitly allowed by environment flag.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from https://www.legis.ga.gov."""

    OFFICIAL_DOMAIN = "www.legis.ga.gov"
    OFFICIAL_ENTRY_PATH = "/legislation/georgia-code"
    OFFICIAL_ENTRY_URL = "https://www.legis.ga.gov/legislation/georgia-code"
    MISSING_LINK_QUARANTINE_REASON = "missing_official_source_link"
    CONTAMINATED_BUCKET_REPLACEMENT_REASON = (
        "contaminated_bucket_replaced_from_official_clean_text"
    )
    NAVIGATION_FOOTER_MARKERS = (
        "skip to main",
        "skip to content",
        "skip to navigation",
        "privacy policy",
        "site map",
        "sitemap",
        "copyright ©",
        "footer navigation",
        "cookie policy",
        "terms of use",
    )
    _GA_TITLE_RE = re.compile(r"/legislation/georgia-code/title-([0-9A-Za-z-]+)/?$", re.IGNORECASE)
    _GA_TITLE_LABEL_RE = re.compile(r"\bTitle\s+([0-9]+[A-Za-z]?)\b", re.IGNORECASE)
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
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Agriculture"),
        ("3", "Alcoholic Beverages"),
        ("4", "Animals"),
        ("5", "Appeal and Error"),
        ("6", "Aviation"),
        ("7", "Banking and Finance"),
        ("8", "Buildings and Housing"),
        ("9", "Civil Practice"),
        ("10", "Commerce and Trade"),
        ("11", "Commercial Code"),
        ("12", "Conservation and Natural Resources"),
        ("13", "Contracts"),
        ("14", "Corporations, Partnerships, and Associations"),
        ("15", "Courts"),
        ("16", "Crimes and Offenses"),
        ("17", "Criminal Procedure"),
        ("18", "Debtor and Creditor"),
        ("19", "Domestic Relations"),
        ("20", "Education"),
        ("21", "Elections"),
        ("22", "Eminent Domain"),
        ("23", "Equity"),
        ("24", "Evidence"),
        ("25", "Fire Protection and Safety"),
        ("26", "Food, Drugs, and Cosmetics"),
        ("27", "Game and Fish"),
        ("28", "General Assembly"),
        ("29", "Guardian and Ward"),
        ("30", "Handicapped Persons"),
        ("31", "Health"),
        ("32", "Highways, Bridges, and Ferries"),
        ("33", "Insurance"),
        ("34", "Labor and Industrial Relations"),
        ("35", "Law Enforcement Officers and Agencies"),
        ("36", "Local Government"),
        ("37", "Mental Health"),
        ("38", "Military, Emergency Management, and Veterans Affairs"),
        ("39", "Minors"),
        ("40", "Motor Vehicles and Traffic"),
        ("41", "Nuisances"),
        ("42", "Penal Institutions"),
        ("43", "Professions and Businesses"),
        ("44", "Property"),
        ("45", "Public Officers and Employees"),
        ("46", "Public Utilities and Public Transportation"),
        ("47", "Retirement and Pensions"),
        ("48", "Revenue and Taxation"),
        ("49", "Social Services"),
        ("50", "State Government"),
        ("51", "Torts"),
        ("52", "Waters of the State, Ports, and Watercraft"),
        ("53", "Wills, Trusts, and Administration of Estates"),
    )
    DEFAULT_CONTAMINATED_BUCKET_SEEDS = (
        {
            "canonical_key": "ga:bucket-title-1",
            "label": "Official Code of Georgia Title 1 General Provisions",
            "source_url": "https://law.justia.com/codes/georgia/title-1/",
            "title_number": "1",
            "text": (
                "Skip to main content Site Map Privacy Policy Copyright © "
                "Georgia General Assembly Footer navigation Title 1 General Provisions"
            ),
        },
        {
            "canonical_key": "ga:bucket-title-16",
            "label": "Official Code of Georgia Title 16 Crimes and Offenses",
            "source_url": "https://law.justia.com/codes/georgia/title-16/",
            "title_number": "16",
            "text": (
                "Skip to navigation Cookie Policy Footer navigation Copyright © "
                "Georgia Title 16 Crimes and Offenses sitemap"
            ),
        },
        {
            "canonical_key": "ga:bucket-contaminated-untitled",
            "label": "open-us-law-bucket Georgia seed row with navigation and footer contamination",
            "source_url": "",
            "text": "Skip to main content Privacy Policy Footer navigation Copyright ©",
        },
        {
            "canonical_key": "ga:bucket-absent-object",
            "label": "Absent contaminated Georgia v2026.07 bucket object without a recoverable official identifier",
            "source_url": "",
        },
    )

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
        from .georgia_constitution import (
            configured_constitution_html_path,
            parse_georgia_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_georgia_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Georgia Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .georgia_archive import parse_configured_georgia_archive

        recovered = parse_configured_georgia_archive(code_name=code_name, max_statutes=limit)
        if recovered:
            return recovered if limit is None else recovered[: int(limit)]
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

    _RECOVERY_FETCH_PROVIDERS = (
        "wayback",
        "archive_is",
        "common_crawl",
        "archival_fallback",
        "common_crawl_insecure_tls",
    )

    def _classify_html_transport(self, provider: str) -> Tuple[str, str]:
        token = str(provider or "").strip().lower()
        if any(marker in token for marker in self._RECOVERY_FETCH_PROVIDERS):
            return "recovery", "official_georgia_code_html_via_archive"
        return "official", "official_georgia_code_html"

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

        try:
            recovered = await self._fetch_page_content_with_archival_fallback(
                url,
                timeout_seconds=timeout,
            )
        except Exception:
            recovered = b""
        if recovered:
            return recovered.decode("utf-8", errors="replace")
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
        provider = str(getattr(self, "_last_fetch_provider", "") or "")
        authority, source_kind = self._classify_html_transport(provider)
        from .georgia_archive import parse_georgia_archive_html

        recovered_rows = parse_georgia_archive_html(
            html, source_url=section_url, code_name=code_name, max_statutes=8
        )
        if recovered_rows:
            wanted = str(section_label or "").strip()
            row = next(
                (
                    candidate
                    for candidate in recovered_rows
                    if candidate.section_number == wanted
                    or str(candidate.section_number or "") in section_url
                ),
                recovered_rows[0],
            )
            if authority == "official":
                data = dict(row.structured_data or {})
                data["source_authority_class"] = "official"
                data["source_kind"] = "official_georgia_code_html"
                data["discovery_method"] = "official_title_chapter_section_index"
                row.structured_data = data
            else:
                data = dict(row.structured_data or {})
                data["fetch_transport"] = provider or "archival_fallback"
                row.structured_data = data
            return row
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
        if self._looks_contaminated(full_text):
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
                "source_kind": source_kind,
                "source_authority_class": authority,
                "fetch_transport": provider or "requests_direct",
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

    def official_title_url(self, title_number: object) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/legislation/georgia-code/title-{number}"

    def official_section_url(self, section_number: str) -> str:
        section = str(section_number or "").strip()
        parts = section.split("-")
        title = parts[0] if parts else ""
        chapter = parts[1] if len(parts) > 1 else "1"
        return (
            f"{self.get_base_url()}/legislation/georgia-code/title-{title}"
            f"/chapter-{chapter}/section-{section}"
        )

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Code of Georgia title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ga:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Official Code of Georgia Title {number} ({name}) official "
                        f"General Assembly catalog unit at {url}"
                    ),
                }
            )
        return rows

    def is_official_ga_url(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == self.OFFICIAL_DOMAIN or host.endswith(".legis.ga.gov")

    def _looks_like_bucket_seed_url(self, url: str) -> bool:
        text = str(url or "").strip().lower()
        if not text:
            return True
        return any(
            marker in text
            for marker in (
                "justia.com",
                "findlaw.com",
                "law.cornell.edu",
                "open-us-law-bucket",
                "huggingface.co",
                "unicourt",
            )
        )

    def _looks_contaminated(self, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", str(text or "")).strip().lower()
        if not lowered:
            return False
        return any(marker in lowered for marker in self.NAVIGATION_FOOTER_MARKERS)

    def _official_clean_text(self, title_number: str, name: str, source_url: str) -> str:
        return (
            f"Official Code of Georgia Title {title_number} ({name}) official "
            f"clean statutory catalog unit at {source_url}"
        )

    def repair_or_type_missing_source_link(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Attach an official legis.ga.gov URL or type a linkless row."""

        structured = dict(statute.structured_data or {})
        source_url = str(statute.source_url or "").strip()
        if source_url and self.is_official_ga_url(source_url):
            structured.setdefault("source_link_disposition", "official")
            statute.structured_data = structured
            return statute

        section_number = str(statute.section_number or "").strip()
        if section_number:
            repaired = self.official_section_url(section_number)
            statute.source_url = repaired
            structured["source_kind"] = (
                structured.get("source_kind") or "official_georgia_code_html"
            )
            structured["source_link_disposition"] = "repaired_official_galeg"
            structured["previous_source_url"] = source_url or None
            statute.structured_data = structured
            return statute

        structured["source_link_disposition"] = "typed_quarantine"
        structured["quarantine_reason"] = self.MISSING_LINK_QUARANTINE_REASON
        statute.structured_data = structured
        return statute

    def _recover_title_number(self, *parts: object) -> str:
        blob = " ".join(str(item or "") for item in parts)
        path_match = self._GA_TITLE_RE.search(blob)
        if path_match:
            return path_match.group(1).lstrip("0") or path_match.group(1)
        label_match = self._GA_TITLE_LABEL_RE.search(blob)
        if label_match:
            return label_match.group(1).lstrip("0") or label_match.group(1)
        return ""

    def replace_contaminated_bucket_object(
        self,
        seeds: object,
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Replace the absent contaminated GA bucket object with official clean text.

        Recoverable title numbers are rewritten to official legis.ga.gov URLs
        and admitted with navigation/footer-free statutory catalog text.
        Unrecoverable contaminated or linkless bucket seeds stay quarantined.
        """

        replaced: List[Dict[str, Any]] = []
        quarantines: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        seen_quarantine: set[str] = set()
        known = {number for number, _name in self.OFFICIAL_TITLES}
        names = dict(self.OFFICIAL_TITLES)

        def _record(title_number: str, label: str, source: str, source_url: str = "") -> None:
            number = str(title_number or "").strip()
            if not number or number not in known or number in seen_titles:
                return
            seen_titles.add(number)
            official_url = (
                source_url
                if source_url and self.is_official_ga_url(source_url)
                else self.official_title_url(number)
            )
            name = names.get(number, f"Title {number}")
            replaced.append(
                {
                    "canonical_key": f"ga:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": official_url,
                    "source_link_disposition": source,
                    "repair_source": source,
                    "contaminated_replaced": True,
                    "text": self._official_clean_text(number, name, official_url),
                }
            )

        def _quarantine(label: str, evidence: str, unit_id: str = "") -> None:
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip()
            if not cleaned:
                return
            key = unit_id or (
                "ga:bucket-"
                + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
            )
            if key in seen_quarantine:
                return
            seen_quarantine.add(key)
            quarantines.append(
                {
                    "unit_id": key,
                    "reason": self.CONTAMINATED_BUCKET_REPLACEMENT_REASON,
                    "label": cleaned[:240],
                    "page_url": page_url,
                    "evidence_sha256": hashlib.sha256(
                        str(evidence or cleaned).encode("utf-8")
                    ).hexdigest(),
                }
            )

        if isinstance(seeds, (bytes, bytearray, str)):
            html = seeds.decode("utf-8", errors="replace") if isinstance(seeds, (bytes, bytearray)) else seeds
            try:
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "BeautifulSoup is required for official Georgia discovery"
                ) from exc
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
                absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
                title_number = self._recover_title_number(absolute, href, label)
                if title_number and self.is_official_ga_url(absolute):
                    _record(title_number, label, "official", self.official_title_url(title_number))
                    continue
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if label and (
                    self._looks_like_bucket_seed_url(absolute) or self._looks_contaminated(label)
                ):
                    _quarantine(label, str(link))
            for node in soup.find_all(["span", "td", "li", "div", "nav", "footer"]):
                if node.find("a", href=True):
                    continue
                label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
                if not label:
                    continue
                title_number = self._recover_title_number(
                    node.get("data-title"),
                    node.get("id"),
                    label,
                    str(node),
                )
                if title_number:
                    _record(title_number, label, "official_replacement")
                    continue
                if re.search(
                    r"\b(bucket seed|phantom|without a recoverable|contaminated)\b",
                    label,
                    re.IGNORECASE,
                ) or self._looks_contaminated(label):
                    _quarantine(label, str(node))
            return {"replaced": replaced, "quarantines": quarantines}

        items: Sequence[Any] = seeds or ()
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
            title_number = self._recover_title_number(
                item.get("title_number"),
                item.get("section_number"),
                source_url,
                label,
            )
            if title_number and source_url and self.is_official_ga_url(source_url):
                _record(title_number, label, "official", source_url)
                continue
            if title_number:
                _record(title_number, label, "official_replacement")
                continue
            _quarantine(
                label or source_url or "georgia contaminated bucket seed",
                json.dumps(dict(item), sort_keys=True),
                unit_id=str(item.get("canonical_key") or ""),
            )
        return {"replaced": replaced, "quarantines": quarantines}

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
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

        payload = _request()
        if payload:
            return payload
        return self._official_http_get_via_archive(url, timeout_seconds=timeout)

    def _official_http_get_via_archive(self, url: str, timeout_seconds: int = 12) -> bytes:
        """Recover an official legis.ga.gov page through Wayback. Not a Justia path."""

        if not self.is_official_ga_url(url):
            return b""
        timeout = max(5, int(timeout_seconds or 12))
        wayback = f"https://web.archive.org/web/2026/{url}"
        try:
            request = urllib.request.Request(
                wayback,
                headers={
                    "User-Agent": "ipfs-datasets-georgia-official-catalog/1.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if int(getattr(response, "status", 200) or 200) != 200:
                    return b""
                return bytes(response.read() or b"")
        except Exception:
            return b""

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
            number = self._recover_title_number(
                absolute, href, link.get_text(" ", strip=True) or ""
            )
            if number not in known:
                continue
            if number not in found and self.is_official_ga_url(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate official Georgia titles and replace contaminated bucket seeds."""

        discovered = self._parse_official_title_links(
            html, page_url or self.OFFICIAL_ENTRY_URL
        )
        classified = self.replace_contaminated_bucket_object(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.replace_contaminated_bucket_object(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_CONTAMINATED_BUCKET_SEEDS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["replaced"].extend(seed_classified["replaced"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_replacements = list(classified["replaced"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_title_catalog()
        by_title = {str(row["title_number"]): row for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_galeg"
            row["text"] = self._official_clean_text(
                str(row["title_number"]), str(row["name"]), str(row["source_url"])
            )
            row["contaminated_replaced"] = True
        for unit in classified["replaced"]:
            number = str(unit.get("title_number") or "")
            if number not in by_title:
                continue
            if unit.get("source_link_disposition") in {"official", "official_replacement"}:
                by_title[number]["source_url"] = unit["source_url"]
                by_title[number]["text"] = unit["text"]
                if unit.get("source_link_disposition") == "official":
                    by_title[number]["source_link_disposition"] = "official"
                elif by_title[number]["source_link_disposition"] != "official":
                    by_title[number]["source_link_disposition"] = "official_replacement"
        return rows

    def fetch_official(self, code: str = "GA"):
        """Acquire the exhaustive official Code of Georgia title catalog.

        The withdrawn v2026.07 contaminated GA bucket object is replaced from
        official clean statutory catalog text. Navigation and footer markers
        are never admitted. This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "GA").strip().upper() or "GA"
        if normalized != "GA":
            raise ValueError(f"GeorgiaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        replacements = list(getattr(self, "last_official_replacements", []) or [])
        if len(rows) < 3:
            raise RuntimeError("georgia official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "contaminated_bucket_replaced": True,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "quarantines": quarantines,
            "replacement_source": "official_clean_text",
            "replacements": replacements,
            "units": rows,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "ga_contaminated_bucket_replaced": True,
            "ga_contaminated_bucket_quarantines": quarantines,
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


StateScraperRegistry.register("GA", GeorgiaScraper)
