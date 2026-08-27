"""Scraper for Colorado state laws.

This module contains the scraper for Colorado statutes from the official state legislative website.
"""

import json
import re
import ssl
import subprocess
import tempfile
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class ColoradoScraper(BaseStateScraper):
    """Scraper for Colorado state laws from https://leg.colorado.gov"""

    _CO_SECTION_NUMBER_RE = re.compile(
        r"\b(\d{1,2}(?:\.\d+)?-\d{1,3}-\d{1,4}(?:\.\d+)?)\b"
    )
    OFFICIAL_DOMAIN = "leg.colorado.gov"
    CONTENT_DOMAIN = "content.leg.colorado.gov"
    OLLS_DOMAIN = "olls.info"
    OFFICIAL_CRS_TITLES_DOWNLOAD_URL = (
        "https://content.leg.colorado.gov/agencies/office-legislative-legal-services/"
        "2026-crs-titles-download"
    )
    OFFICIAL_ENTRY_PATH = (
        "/agencies/office-legislative-legal-services/2026-crs-titles-download"
    )
    OFFICIAL_ENTRY_URL = OFFICIAL_CRS_TITLES_DOWNLOAD_URL
    OFFICIAL_CRS_TITLES = (
        (1, "Elections"),
        (2, "Legislative"),
        (3, "United States"),
        (4, "Uniform Commercial Code"),
        (5, "Consumer Credit Code"),
        (6, "Consumer and Commercial Affairs"),
        (7, "Corporations and Associations"),
        (8, "Labor and Industry"),
        (9, "Safety - Industrial and Commercial"),
        (10, "Insurance"),
        (11, "Financial Institutions"),
        (12, "Professions and Occupations"),
        (13, "Courts and Court Procedure"),
        (14, "Domestic Matters"),
        (15, "Probate, Trusts, and Fiduciaries"),
        (16, "Criminal Proceedings"),
        (17, "Corrections"),
        (18, "Criminal Code"),
        (19, "Children's Code"),
        (20, "District Attorneys"),
        (21, "State Public Defender"),
        (22, "Education"),
        (23, "Postsecondary Education"),
        (24, "Government - State"),
        (25, "Public Health and Environment"),
        (25.5, "Health Care Policy and Financing"),
        (26, "Human Services Code"),
        (26.5, "Early Childhood"),
        (27, "Behavioral Health"),
        (28, "Military and Veterans"),
        (29, "Government - Local"),
        (30, "Government - County"),
        (31, "Government - Municipal"),
        (32, "Special Districts"),
        (33, "Parks and Wildlife"),
        (34, "Mineral Resources"),
        (35, "Agriculture"),
        (36, "Natural Resources - General"),
        (37, "Water and Irrigation"),
        (38, "Property - Real and Personal"),
        (39, "Taxation"),
        (40, "Utilities"),
        (41, "Aeronautics: Aircraft and Airports"),
        (42, "Vehicles and Traffic"),
        (43, "Transportation"),
        (44, "Revenue - Regulation of Activities"),
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Colorado's legislative website."""
        return "https://leg.colorado.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Colorado."""
        return [{
            "name": "Colorado Revised Statutes",
            "url": self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Colorado's legislative website.

        Full-corpus mode with ``max_statutes=None`` closes the exact title-file
        frontier referred by the official Office of Legislative Legal Services
        page. Secondary generic recovery is intentionally skipped so a partial
        publication-search result cannot sole-admit a sealed full-corpus run.
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .colorado_constitution import (
            configured_constitution_text_path,
            parse_colorado_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_colorado_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Colorado Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .colorado_title import parse_configured_colorado_crs

        local_rows = parse_configured_colorado_crs(code_name=code_name, max_statutes=limit)
        if local_rows:
            if limit is None:
                self._assert_full_title_coverage(
                    local_rows,
                    context="configured Colorado CRS input",
                )
            return local_rows if limit is None else local_rows[: int(limit)]
        # Keep the former official publication-search adapter available for
        # explicitly bounded probes that still pass its legacy URL.  It is not
        # a full-corpus source and is never consulted for an unbounded run.
        legacy_bounded = limit is not None and "publication-search" in str(code_url or "")
        if legacy_bounded:
            statutes = await self._scrape_crs_pdfs(code_name, max_statutes=limit)
            if statutes:
                return statutes[: int(limit)]
        statutes = await self._scrape_crs_title_downloads(
            code_name,
            max_statutes=limit,
        )
        if statutes:
            return statutes if limit is None else statutes[: int(limit)]
        if limit is None:
            raise RuntimeError(
                "Colorado full-corpus acquisition did not enumerate the official CRS title files"
            )
        statutes = [] if legacy_bounded else await self._scrape_crs_pdfs(
            code_name,
            max_statutes=limit,
        )
        if statutes:
            return statutes if limit is None else statutes[: int(limit)]
        self.logger.warning(
            "Colorado CRS direct PDF scrape returned no usable statutes; "
            "skipping generic recovery fallback"
        )
        return []

    def _expected_title_numbers(self) -> set[str]:
        return {str(number) for number, _name in self.OFFICIAL_CRS_TITLES}

    def _assert_full_title_coverage(
        self,
        statutes: List[NormalizedStatute],
        *,
        context: str,
    ) -> None:
        expected = self._expected_title_numbers()
        observed = {str(row.title_number or "").lstrip("0") or "0" for row in statutes}
        missing = sorted(expected - observed, key=lambda value: float(value))
        unexpected = sorted(observed - expected, key=lambda value: float(value))
        if missing or unexpected:
            raise RuntimeError(
                f"{context} did not close the official title frontier: "
                f"missing_titles={missing} unexpected_titles={unexpected} rows={len(statutes)}"
            )

    async def _scrape_crs_title_downloads(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Acquire each whole-title HTM referred by the official OLLS page."""

        from .colorado_title import parse_colorado_title_html, title_download_rows

        limit = self._effective_scrape_limit(max_statutes, default=160)
        page_payload = await self._request_bytes_direct(
            self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
            timeout_seconds=60,
        )
        if not page_payload:
            if limit is None:
                raise RuntimeError("Colorado official CRS title-download page was unavailable")
            return []
        page_html = page_payload.decode("utf-8", errors="replace")
        downloads = title_download_rows(
            page_html,
            page_url=self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
        )
        if limit is None:
            expected = self._expected_title_numbers()
            discovered = {number for number, _name, _url, _edition in downloads}
            editions = {edition for _number, _name, _url, edition in downloads}
            missing = sorted(expected - discovered, key=lambda value: float(value))
            unexpected = sorted(discovered - expected, key=lambda value: float(value))
            if missing or unexpected or len(editions) != 1:
                raise RuntimeError(
                    "Colorado official CRS title enumeration is partial or inconsistent: "
                    f"missing_titles={missing} unexpected_titles={unexpected} "
                    f"editions={sorted(editions)}"
                )

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        completed_titles: set[str] = set()
        title_payload_by_url: Dict[str, bytes] = {}
        if limit is None:
            title_urls = [title_url for _number, _name, title_url, _edition in downloads]
            if len(set(title_urls)) != len(title_urls):
                raise RuntimeError("Colorado official title frontier contains duplicate URLs")
            batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                title_urls,
                residual_retry_attempts=1,
                timeout_seconds=180,
                headers={
                    "User-Agent": "ipfs-datasets-colorado-code-scraper/2.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                },
                content_validator=lambda payload: (
                    b"<" in payload[:8192] and b">" in payload[:8192]
                ),
                media_type="text/html",
                max_concurrency=8,
                prefer_direct=True,
                wayback_prefix_inventory=True,
            )
            if list(batch.urls) != title_urls or any(
                len(vector) != len(title_urls)
                for vector in (
                    batch.payloads,
                    batch.errors,
                    batch.transport_receipts,
                    batch.parser_input_envelopes,
                )
            ):
                raise RuntimeError(
                    "Colorado official title frontier returned unaligned acquisition rows"
                )
            failures = [
                {"url": url, "error": error or "empty parser input"}
                for url, payload, error in zip(
                    batch.urls, batch.payloads, batch.errors, strict=True
                )
                if error is not None or not payload
            ]
            if failures:
                raise RuntimeError(
                    "Colorado official title frontier is incomplete; "
                    f"unresolved exact URLs: {failures}"
                )
            title_payload_by_url = {
                url: bytes(payload)
                for url, payload in zip(batch.urls, batch.payloads, strict=True)
            }
        for title_number, _title_name, title_url, edition in downloads:
            if limit is not None and len(statutes) >= int(limit):
                break
            payload = title_payload_by_url.get(title_url)
            if payload is None:
                payload = await self._request_bytes_direct(title_url, timeout_seconds=180)
            if not payload:
                if limit is None:
                    raise RuntimeError(
                        f"Colorado official CRS Title {title_number} HTM was unavailable"
                    )
                continue
            remaining = None if limit is None else max(0, int(limit) - len(statutes))
            title_rows = parse_colorado_title_html(
                payload.decode("cp1252", errors="replace"),
                code_name=code_name,
                source_url=title_url,
                max_statutes=remaining,
            )
            valid_title_rows = [
                row
                for row in title_rows
                if (str(row.title_number or "").lstrip("0") or "0") == title_number
            ]
            if limit is None and not valid_title_rows:
                raise RuntimeError(
                    f"Colorado official CRS Title {title_number} HTM yielded no active statutes"
                )
            for row in valid_title_rows:
                section_number = str(row.section_number or "")
                if section_number in seen_sections:
                    if limit is None:
                        raise RuntimeError(
                            f"Colorado duplicate section {section_number} across title downloads"
                        )
                    continue
                seen_sections.add(section_number)
                structured = dict(row.structured_data or {})
                structured.update(
                    {
                        "source_authority_class": "official",
                        "official_referral_url": self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
                        "delegated_download_host": self.OLLS_DOMAIN,
                        "edition": edition,
                    }
                )
                row.structured_data = structured
                statutes.append(row)
            if valid_title_rows:
                completed_titles.add(title_number)

        if limit is None:
            expected = self._expected_title_numbers()
            missing_downloads = sorted(expected - completed_titles, key=lambda value: float(value))
            if missing_downloads:
                raise RuntimeError(
                    "Colorado full-corpus HTM parsing left title downloads incomplete: "
                    f"missing_titles={missing_downloads}"
                )
            self._assert_full_title_coverage(
                statutes,
                context="Colorado official CRS HTM acquisition",
            )
        self.logger.info(
            "Scraped %s Colorado CRS statutes from %s official title HTM files",
            len(statutes),
            len(completed_titles),
        )
        return statutes

    async def _scrape_crs_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape CRS-related publications discoverable from the official publication search."""
        limit = self._effective_scrape_limit(max_statutes, default=160)
        discovered = await self._discover_crs_publications(limit=max(8, int(limit or 20) * 3))
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()

        for publication in discovered:
            if limit is not None and len(statutes) >= int(limit):
                break
            title = str(publication.get("title") or "").strip()
            detail_url = str(publication.get("detail_url") or "").strip()
            pdf_url = str(publication.get("pdf_url") or "").strip()
            section_number = self._extract_section_number(title) or self._extract_section_number_from_pdf_path(pdf_url)
            if not section_number:
                continue
            if section_number in seen_sections:
                continue
            seen_sections.add(section_number)

            section_name = title or f"Section {section_number}"
            full_text = ""
            source_kind = "official_colorado_pdf"

            if detail_url:
                detail_text = await self._extract_publication_detail_text(detail_url)
                if len(detail_text or "") >= 220:
                    full_text = detail_text
                    source_kind = "official_colorado_publication_html"

            if len(full_text or "") < 220 and pdf_url:
                pdf_text = await self._extract_pdf_text_summary(pdf_url)
                if len(pdf_text or "") >= len(full_text or ""):
                    full_text = pdf_text
                    source_kind = "official_colorado_pdf"

            if len(full_text or "") < 220:
                continue

            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name,
                full_text=full_text,
                source_url=detail_url or pdf_url,
                legal_area=self._identify_legal_area(code_name),
                official_cite=f"Colo. Rev. Stat. § {section_number}",
            )
            statute.structured_data = {
                "source_kind": source_kind,
                "discovery_method": "official_crs_publication_search",
                "detail_url": detail_url or None,
                "pdf_url": pdf_url or None,
                "skip_hydrate": True,
            }
            statutes.append(statute)

        self.logger.info(f"Scraped {len(statutes)} Colorado CRS PDF statutes")
        return statutes

    async def _discover_crs_publications(self, limit: int = 60) -> List[Dict[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[Dict[str, str]] = []
        seen: set[str] = set()

        for page in range(0, 8):
            search_url = f"https://content.leg.colorado.gov/publication-search?search_api_fulltext=crs&page={page}"
            try:
                page_bytes = await self._request_bytes_direct(search_url, timeout_seconds=45)
            except Exception:
                continue
            if not page_bytes:
                continue

            soup = BeautifulSoup(page_bytes, "html.parser")
            rows = soup.select(".views-row")
            if not rows:
                break

            for row in rows:
                row_text = " ".join(row.get_text(" ", strip=True).split())
                if "C.R.S." not in row_text and "Colorado Revised Statutes" not in row_text:
                    continue
                detail_url = ""
                pdf_url = ""
                title = ""
                for link in row.select("a[href]"):
                    href = str(link.get("href") or "").strip()
                    text = " ".join(link.get_text(" ", strip=True).split())
                    if not href:
                        continue
                    absolute = urljoin(search_url, href)
                    if "/publications/" in href and not title:
                        detail_url = absolute
                        title = text or row_text[:240]
                    if href.lower().endswith(".pdf"):
                        pdf_url = absolute
                if not detail_url and not pdf_url:
                    continue
                section_number = self._extract_section_number(title or row_text) or self._extract_section_number_from_pdf_path(pdf_url)
                if not section_number:
                    continue
                key = detail_url or pdf_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "title": title or row_text[:240],
                        "detail_url": detail_url,
                        "pdf_url": pdf_url,
                        "section_number": section_number,
                    }
                )
                if len(out) >= limit:
                    return out
        return out

    async def _extract_publication_detail_text(
        self,
        detail_url: str,
        max_chars: Optional[int] = None,
    ) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""

        payload = await self._request_bytes_direct(detail_url, timeout_seconds=45)
        if not payload:
            return ""
        html_text = payload.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html_text, "html.parser")
        article = soup.select_one("article")
        if article is None:
            return ""
        text = " ".join(article.get_text(" ", strip=True).split())
        text = re.sub(r"\bShare:\b.*$", "", text, flags=re.IGNORECASE).strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def _extract_section_number(self, text: str) -> str:
        match = self._CO_SECTION_NUMBER_RE.search(str(text or ""))
        return match.group(1) if match else ""

    def _extract_section_number_from_pdf_path(self, path: str) -> str:
        """Extract section number from CRS-style PDF filenames."""
        decoded_path = unquote(path)
        file_name = decoded_path.rsplit("/", 1)[-1]
        match = re.match(r"(\d{1,2}-\d{1,3}-\d{1,4})", file_name)
        if not match:
            return ""
        return match.group(1)

    def _fallback_section_id_from_pdf_path(self, path: str) -> str:
        decoded_path = unquote(path)
        file_name = decoded_path.rsplit("/", 1)[-1]
        file_name = re.sub(r"\.pdf$", "", file_name, flags=re.IGNORECASE)
        file_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name).strip("-")
        return file_name[:80]

    async def _extract_pdf_text_summary(
        self,
        pdf_url: str,
        max_chars: Optional[int] = None,
    ) -> str:
        """Download a PDF and extract its complete normalized text using pdftotext."""
        try:
            self.logger.info("Colorado CRS: fetching PDF %s", pdf_url)
            payload = await self._request_bytes_direct(
                pdf_url,
                timeout_seconds=60,
            )
            if not payload:
                return ""
        except Exception as exc:
            self.logger.debug(f"Colorado PDF download failed for {pdf_url}: {exc}")
            return ""

        try:
            with tempfile.TemporaryDirectory(prefix="co_crs_pdf_") as tmpdir:
                from pathlib import Path

                pdf_path = Path(tmpdir) / "section.pdf"
                txt_path = Path(tmpdir) / "section.txt"
                pdf_path.write_bytes(payload)

                result = subprocess.run(
                    [trusted_pdftotext_executable(), str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if int(result.returncode) != 0 or not txt_path.exists():
                    return ""

                text = txt_path.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                if max_chars is not None:
                    return text[: max(1, int(max_chars))]
                return text
        except Exception as exc:
            self.logger.debug(f"Colorado PDF text extraction failed for {pdf_url}: {exc}")
            return ""

    async def _request_bytes_direct(self, url: str, timeout_seconds: int = 45) -> bytes:
        timeout = max(5, int(timeout_seconds or 45))
        is_pdf = urlparse(str(url or "")).path.lower().endswith(".pdf")
        return await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-colorado-code-scraper/2.0",
                "Accept": "application/pdf,*/*;q=0.8"
                if is_pdf
                else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            content_validator=(
                (lambda payload: payload.startswith(b"%PDF"))
                if is_pdf
                else (lambda payload: b"<" in payload[:8192] and b">" in payload[:8192])
            ),
            allow_archival_fallback=True,
            media_type="application/pdf" if is_pdf else "text/html",
            provider="requests_direct",
        )

    def official_title_url(self, title_number: Any) -> str:
        title = str(title_number).replace(".", "-")
        return (
            "https://content.leg.colorado.gov/publication-search"
            f"?search_api_fulltext=crs%20title%20{title}"
        )

    def official_crs_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Colorado Revised Statutes title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_CRS_TITLES:
            key = str(number).replace(".", "-")
            rows.append(
                {
                    "canonical_key": f"co:title-{key}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": self.official_title_url(number),
                    "source_link_disposition": "official",
                    "text": (
                        f"Colorado Revised Statutes Title {number} ({name}) official "
                        f"catalog unit at {self.official_title_url(number)}"
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
                        "User-Agent": "ipfs-datasets-colorado-official-catalog/1.0",
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
                            "User-Agent": "ipfs-datasets-colorado-official-catalog/1.0",
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

    def fetch_official(self, code: str = "CO"):
        """Acquire the exhaustive official Colorado CRS title catalog.

        Live HTTPS retains and parses the exact General Assembly referral page
        used by the body scraper.  Its delegated ``olls.info`` HTM links form
        the closed 2026 title-file frontier; a static or publication-search
        approximation is never promoted as that observation.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "CO").strip().upper() or "CO"
        from .colorado_title import title_download_rows

        html = self._official_http_get(self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL)
        if not html:
            raise RuntimeError("colorado official title-download page is unavailable")
        downloads = title_download_rows(
            html.decode("utf-8", errors="replace"),
            page_url=self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
        )
        expected = self._expected_title_numbers()
        discovered = {number for number, _name, _url, _edition in downloads}
        editions = {edition for _number, _name, _url, edition in downloads}
        if discovered != expected or len(downloads) != len(expected) or len(editions) != 1:
            raise RuntimeError(
                "colorado official title-download frontier is incomplete or inconsistent: "
                f"missing={sorted(expected - discovered)} "
                f"unexpected={sorted(discovered - expected)} "
                f"editions={sorted(editions)}"
            )
        rows = tuple(
            {
                "canonical_key": f"co:title-{number.replace('.', '-')}",
                "title_number": number,
                "name": name,
                "source_url": title_url,
                "edition": edition,
                "source_link_disposition": "official_delegated",
                "text": (
                    f"Colorado Revised Statutes Title {number} ({name}) "
                    f"official HTM download at {title_url}"
                ),
            }
            for number, name, title_url, edition in downloads
        )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.CONTENT_DOMAIN}\n"
        ).encode("utf-8")
        edition = next(iter(editions))
        frontier = {
            "bundle_closed": True,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "bundle",
            "pagination_closed": False,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=html,
            body_bytes=html,
            source_domain=self.CONTENT_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            edition=edition,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("CO", ColoradoScraper)
