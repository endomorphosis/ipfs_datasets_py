"""Scraper for Oklahoma state laws.

This module contains the scraper for Oklahoma statutes using OSCN's
DeliverDocument statute pages.
"""

import json
from ipfs_datasets_py.utils import anyio_compat as asyncio
import os
import re
import time
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class OklahomaScraper(BaseStateScraper):
    """Scraper for Oklahoma state laws from http://www.oklegislature.gov"""

    _SEED_INDEX_URLS = [
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69380",
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69782&Title=74",
        "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=438588",
        "https://www.oscn.net/applications/oscn/Index.asp?ftdb=STOKST74",
        "https://www.oscn.net/applications/oscn/index.asp?level=1&ftdb=STOKST",
    ]
    _ANTI_BOT_RE = re.compile(
        r"why am i seeing this\?|verify (?:you are|you're) human|automated traffic|cf-browser-verification|just a moment",
        re.IGNORECASE,
    )
    _CASELAW_RE = re.compile(
        r"court of (?:criminal|civil) appeals cases|oklahoma (?:supreme|court of criminal appeals|court of civil appeals)|case number:\s*[A-Z0-9\-]+|v\.\s+state",
        re.IGNORECASE,
    )
    _NON_STATUTE_RE = re.compile(
        r"oklahoma attorney general'?s opinions|oklahoma jury instructions|uniform jury instructions|ag\s+\d{2,4}\s*[- ]\s*\d+|question submitted by:|previous case\s+top of index\s+this point in index",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_wayback_url(url: str) -> str:
        value = str(url or "").strip()
        if value.startswith("http://web.archive.org/"):
            return "https://" + value[len("http://"):]
        return value
    
    def get_base_url(self) -> str:
        """Return the base URL for Oklahoma's legislative website."""
        return "http://www.oklegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Oklahoma."""
        return [{
            "name": "Oklahoma Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Oklahoma's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        if not self._full_corpus_enabled() and max_statutes is None:
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        checkpoint = _OklahomaCheckpoint(self.state_code)
        seed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=max(10, return_threshold),
        )
        # Bootstrap with a tiny direct OSCN sample even in full-corpus mode so
        # long candidate-discovery phases still show early real progress.
        bootstrap_seed_target_raw = str(os.getenv("STATE_SCRAPER_OK_BOOTSTRAP_SEED_COUNT", "") or "").strip()
        try:
            bootstrap_seed_target = int(bootstrap_seed_target_raw) if bootstrap_seed_target_raw else 2
        except Exception:
            bootstrap_seed_target = 2
        bootstrap_seed_target = max(1, min(8, bootstrap_seed_target))
        try:
            direct_seed = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=bootstrap_seed_target,
            )
        except Exception:
            direct_seed = []
        if direct_seed:
            seed_statutes = list(seed_statutes) + list(direct_seed)
            self.logger.info(
                "Oklahoma OSCN bootstrap: statutes_so_far=%s direct_seed_sections=%s",
                len(direct_seed),
                len(direct_seed),
            )
        best_archival: List[NormalizedStatute] = []
        for attempt in range(3):
            archival = await self._scrape_oscn_documents(
                code_name=code_name,
                max_statutes=max(10, return_threshold),
                seed_statutes=seed_statutes if attempt == 0 else best_archival,
                checkpoint=checkpoint,
            )
            if len(archival) > len(best_archival):
                best_archival = archival
            if best_archival:
                self.logger.info(
                    "Oklahoma OSCN archival fallback: scraped %s sections on attempt %s",
                    len(best_archival),
                    attempt + 1,
                )
                if not self._full_corpus_enabled() or max_statutes is not None:
                    return best_archival
            await asyncio.sleep(0.4 * (attempt + 1))

        # If OSCN blocks automated access, use a broader fallback index to avoid zero-state output.
        fallback_urls = [
            code_url,
            "https://law.justia.com/codes/oklahoma/",
        ]
        best: List[NormalizedStatute] = []
        for candidate in fallback_urls:
            try:
                statutes = await self._generic_scrape(
                    code_name,
                    candidate,
                    "Okla. Stat.",
                    max_sections=max(10, return_threshold),
                )
            except Exception:
                statutes = []
            if len(statutes) > len(best):
                best = statutes

        if len(best) > len(best_archival):
            return best
        return list(best_archival)

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        seeds = [
            "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=69380",
            "https://www.oscn.net/applications/oscn/DeliverDocument.asp?CiteID=436720",
        ]
        headers = {"User-Agent": "Mozilla/5.0"}
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            statute = await self._build_statute_from_jina_reader(
                code_name=code_name,
                document_url=url,
            )
            if statute is None:
                statute = await self._build_statute_from_document_url(
                    code_name=code_name,
                    document_url=url,
                    headers=headers,
                )
            if statute is None:
                continue
            structured = dict(statute.structured_data or {})
            structured.setdefault("source_kind", "official_oklahoma_oscn_html")
            structured.setdefault("discovery_method", "official_seed_document")
            structured["skip_hydrate"] = True
            statute.structured_data = structured
            if statute.metadata is None:
                statute.metadata = StatuteMetadata()
            out.append(statute)
        return out

    async def _build_statute_from_jina_reader(
        self,
        code_name: str,
        document_url: str,
    ) -> NormalizedStatute | None:
        reader_url = f"https://r.jina.ai/http://{document_url}"

        def _fetch() -> str:
            try:
                import urllib.request

                request = urllib.request.Request(reader_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            markdown = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=24)
        except Exception:
            return None
        if not markdown:
            return None

        section_match = re.search(r"Section\s+([0-9A-Za-z.\-]+)\s+-\s*([^\n*]+)", markdown, flags=re.IGNORECASE)
        cite_match = re.search(r"Cite as:\s*([0-9]+\s+O\.S\.\s*§\s*[0-9A-Za-z.\-]+)", markdown, flags=re.IGNORECASE)
        body_start = cite_match.end() if cite_match else -1
        if body_start < 0 and section_match:
            body_start = section_match.end()
        if body_start < 0:
            return None

        tail = markdown[body_start:]
        end = len(tail)
        for marker in ("Historical Data", "Citationizer", "Oklahoma Attorney General", "Court of Criminal Appeals"):
            idx = tail.find(marker)
            if idx >= 0:
                end = min(end, idx)
        body = self._normalize_legal_text(tail[:end])
        body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
        body = self._normalize_legal_text(body)
        if len(body) < 120:
            return None

        section_number = section_match.group(1).strip() if section_match else self._extract_cite_id(document_url)
        section_name = section_match.group(2).strip()[:180] if section_match else f"Section {section_number}"
        official_cite = cite_match.group(1).strip() if cite_match else f"Okla. Stat. § {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=body[:14000],
            legal_area=self._identify_legal_area(body),
            source_url=document_url,
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_oklahoma_oscn",
                "discovery_method": "official_seed_document_reader",
                "reader_url": reader_url,
                "skip_hydrate": True,
            },
        )

    async def _scrape_oscn_documents(
        self,
        code_name: str,
        max_statutes: int,
        *,
        seed_statutes: Optional[List[NormalizedStatute]] = None,
        checkpoint: Optional["_OklahomaCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_statutes: Set[str] = set()
        seen_candidate_urls: Set[str] = set()

        for statute in list(seed_statutes or []):
            dedupe_key = _statute_dedupe_key(statute)
            if not dedupe_key or dedupe_key in seen_statutes:
                continue
            seen_statutes.add(dedupe_key)
            statutes.append(statute)
            source_url = str(statute.source_url or "").strip().lower()
            if source_url:
                seen_candidate_urls.add(source_url)

        candidate_urls = await self._collect_candidate_document_urls(headers=headers)
        candidate_timeout_raw = str(os.getenv("STATE_SCRAPER_OK_CANDIDATE_TIMEOUT_SECONDS", "") or "").strip()
        try:
            candidate_timeout_seconds = int(candidate_timeout_raw) if candidate_timeout_raw else 75
        except Exception:
            candidate_timeout_seconds = 75
        candidate_timeout_seconds = max(20, min(240, candidate_timeout_seconds))
        heartbeat_raw = str(os.getenv("STATE_SCRAPER_OK_SCAN_HEARTBEAT_SECONDS", "") or "").strip()
        try:
            scan_heartbeat_seconds = int(heartbeat_raw) if heartbeat_raw else 30
        except Exception:
            scan_heartbeat_seconds = 30
        scan_heartbeat_seconds = max(10, min(180, scan_heartbeat_seconds))
        heartbeat_every_raw = str(os.getenv("STATE_SCRAPER_OK_SCAN_HEARTBEAT_EVERY", "") or "").strip()
        try:
            scan_heartbeat_every = int(heartbeat_every_raw) if heartbeat_every_raw else 200
        except Exception:
            scan_heartbeat_every = 200
        scan_heartbeat_every = max(25, min(1000, scan_heartbeat_every))
        self.logger.info(
            "Oklahoma OSCN crawl: discovered_candidate_urls=%s max_statutes=%s",
            len(candidate_urls),
            max_statutes,
        )
        crawl_started_at = time.time()
        last_scan_heartbeat_at = crawl_started_at
        timeout_count = 0
        error_count = 0
        for link in candidate_urls:
            if len(statutes) >= max_statutes:
                break
            dedupe_key = str(link or "").strip().lower()
            if dedupe_key in seen_candidate_urls:
                continue
            seen_candidate_urls.add(dedupe_key)
            scanned_candidates = len(seen_candidate_urls)

            now = time.time()
            if (
                scanned_candidates == 1
                or scanned_candidates % scan_heartbeat_every == 0
                or now - last_scan_heartbeat_at >= scan_heartbeat_seconds
            ):
                elapsed = max(1.0, now - crawl_started_at)
                scan_rate_per_min = (float(scanned_candidates) / elapsed) * 60.0
                self.logger.info(
                    "Oklahoma OSCN crawl: scanned_candidates=%s statutes_so_far=%s discovered_candidates=%s scan_rate_per_min=%.2f",
                    scanned_candidates,
                    len(statutes),
                    len(candidate_urls),
                    scan_rate_per_min,
                )
                if checkpoint is not None and statutes:
                    checkpoint.write(
                        statutes,
                        code_name=code_name,
                        scanned_candidates=scanned_candidates,
                        discovered_candidates=len(candidate_urls),
                    )
                last_scan_heartbeat_at = now

            try:
                statute = await asyncio.wait_for(
                    self._build_statute_from_document_url(
                        code_name=code_name,
                        document_url=link,
                        headers=headers,
                    ),
                    timeout=float(candidate_timeout_seconds),
                )
            except asyncio.TimeoutError:
                timeout_count += 1
                self.logger.warning(
                    "Oklahoma OSCN crawl: candidate_timeout scanned_candidates=%s timeout_seconds=%s url=%s",
                    scanned_candidates,
                    candidate_timeout_seconds,
                    link,
                )
                continue
            except Exception as exc:
                error_count += 1
                self.logger.warning(
                    "Oklahoma OSCN crawl: candidate_error scanned_candidates=%s url=%s error=%s",
                    scanned_candidates,
                    link,
                    exc,
                )
                continue
            if statute is None:
                continue
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_statutes:
                continue
            if statute_key:
                seen_statutes.add(statute_key)
            statutes.append(statute)
            if checkpoint is not None:
                checkpoint.maybe_write(
                    statutes,
                    code_name=code_name,
                    scanned_candidates=len(seen_candidate_urls),
                    discovered_candidates=len(candidate_urls),
                )
            if len(statutes) == 1 or len(statutes) % 25 == 0:
                self.logger.info(
                    "Oklahoma OSCN crawl: statutes_so_far=%s scanned_candidates=%s",
                    len(statutes),
                    len(seen_candidate_urls),
                )

        self.logger.info(
            "Oklahoma OSCN crawl: completed statutes=%s scanned_candidates=%s discovered_candidates=%s timeout_count=%s error_count=%s",
            len(statutes),
            len(seen_candidate_urls),
            len(candidate_urls),
            timeout_count,
            error_count,
        )
        if checkpoint is not None:
            checkpoint.write(
                statutes,
                code_name=code_name,
                scanned_candidates=len(seen_candidate_urls),
                discovered_candidates=len(candidate_urls),
            )
        return statutes

    async def _collect_candidate_document_urls(self, headers: Dict[str, str]) -> List[str]:
        candidates: List[str] = []
        seen: Set[str] = set()

        def _add(url_value: str) -> None:
            normalized = str(url_value or "").strip()
            if not normalized:
                return
            if "deliverdocument.asp?citeid=" not in normalized.lower():
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        bounded_limit = self._bounded_return_threshold(0)
        bounded_direct_only = str(os.getenv("STATE_SCRAPER_BOUNDED_DIRECT_ONLY", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if bounded_limit > 0 and bounded_direct_only:
            for seed_url in self._SEED_INDEX_URLS:
                _add(seed_url)
                if len(candidates) >= max(1, bounded_limit):
                    self.logger.info(
                        "Oklahoma OSCN discovery: bounded_direct_only candidates=%s",
                        len(candidates),
                    )
                    return candidates
            self.logger.info(
                "Oklahoma OSCN discovery: bounded_direct_only candidates=%s",
                len(candidates),
            )
            return candidates

        self.logger.info(
            "Oklahoma OSCN discovery: seed_scan_start seed_count=%s full_corpus=%s",
            len(self._SEED_INDEX_URLS),
            self._full_corpus_enabled(),
        )
        for seed_url in self._SEED_INDEX_URLS:
            self.logger.info(
                "Oklahoma OSCN discovery: scanning_seed_url=%s candidates_so_far=%s",
                seed_url,
                len(candidates),
            )
            _add(seed_url)
            html = await self._request_text(seed_url, headers=headers, timeout=45)
            if not html:
                for archived_link in await self._discover_links_from_archived_seed(seed_url=seed_url, headers=headers):
                    _add(archived_link)
                continue
            for live_link in self._extract_deliver_document_links(seed_url=seed_url, html=html):
                _add(live_link)

        # Archive-driven URL discovery helps when live index pages are sparse.
        self.logger.info(
            "Oklahoma OSCN discovery: cdx_scan_start candidates_so_far=%s",
            len(candidates),
        )
        for archive_url in await self._discover_oscn_document_urls_via_cdx(headers=headers):
            _add(archive_url)
        self.logger.info(
            "Oklahoma OSCN discovery: cdx_scan_complete candidates_so_far=%s",
            len(candidates),
        )

        self.logger.info(
            "Oklahoma OSCN discovery: total_candidates=%s",
            len(candidates),
        )
        return candidates

    def _extract_deliver_document_links(self, *, seed_url: str, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            full_url = urljoin(seed_url, href)
            if "deliverdocument.asp?citeid=" not in full_url.lower():
                continue
            links.append(full_url)
        return links

    async def _discover_links_from_archived_seed(self, *, seed_url: str, headers: Dict[str, str]) -> List[str]:
        seed_citeid = self._extract_cite_id(seed_url)
        if not seed_citeid:
            return []

        capture_limit = 50 if self._full_corpus_enabled() else 8
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.oscn.net/applications/oscn/DeliverDocument.asp"
            f"?CiteID={seed_citeid}&output=json"
            f"&fl=timestamp,original,statuscode&filter=statuscode:200&limit={capture_limit}"
        )
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                cdx_url,
                timeout_seconds=30,
            )
            if not payload:
                return []
            rows = json.loads(payload.decode("utf-8", errors="replace"))
        except Exception:
            return []

        if not isinstance(rows, list) or len(rows) <= 1:
            return []

        discovered: List[str] = []
        # Prefer latest captures first.
        for row in reversed(rows[1:]):
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = str(row[0] or "").strip()
            original = str(row[1] or "").strip()
            if not ts or not original:
                continue
            replay_url = self._normalize_wayback_url(f"https://web.archive.org/web/{ts}id_/{original}")
            html = await self._request_text(replay_url, headers=headers, timeout=35)
            if not html:
                continue
            for link in self._extract_deliver_document_links(seed_url=replay_url, html=html):
                discovered.append(link)
            discovery_limit = 5000 if self._full_corpus_enabled() else 400
            if len(discovered) >= discovery_limit:
                break

        return discovered

    async def _discover_oscn_document_urls_via_cdx(self, headers: Dict[str, str]) -> List[str]:
        cdx_limit = 10000 if self._full_corpus_enabled() else 1200
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.oscn.net/applications/oscn/DeliverDocument.asp*"
            f"&output=json&filter=statuscode:200&limit={cdx_limit}"
        )
        try:
            raw = await asyncio.wait_for(
                self._fetch_page_content_with_archival_fallback(
                    cdx_url,
                    timeout_seconds=35,
                ),
                timeout=55,
            )
            if not raw:
                self.logger.info("Oklahoma OSCN CDX discovery: no payload")
                return []
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except asyncio.TimeoutError:
            self.logger.warning("Oklahoma OSCN CDX discovery timed out after 55s")
            return []
        except Exception:
            return []

        urls: List[str] = []
        if not isinstance(payload, list) or len(payload) <= 1:
            return urls

        for row in payload[1:]:
            if not isinstance(row, list) or len(row) < 3:
                continue
            timestamp = str(row[1] or "").strip() if len(row) > 1 else ""
            original = str(row[2] or "").strip()
            if "deliverdocument.asp?citeid=" not in original.lower():
                continue
            if timestamp:
                replay = self._normalize_wayback_url(f"https://web.archive.org/web/{timestamp}id_/{original}")
                urls.append(replay)
            urls.append(original)
        return urls

    def _extract_document_body_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        selectors = [
            "#oscn-content",
            "#content",
            "#body",
            "main",
            "article",
            "div.document",
            "div#doc",
        ]

        candidates: List[str] = []
        for selector in selectors:
            for node in soup.select(selector):
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                if len(text) >= 300:
                    candidates.append(text)

        if not candidates:
            body = soup.find("body")
            if body is not None:
                text = self._normalize_legal_text(body.get_text(" ", strip=True))
                if text:
                    candidates.append(text)

        if not candidates:
            return ""

        text = max(candidates, key=len)
        # Drop OSCN global navigation noise that often prefixes archived pages.
        text = re.sub(r"^\s*OSCN\s+navigation\s+.*?\bHelp\b\s*", "", text, flags=re.IGNORECASE)
        text = re.split(r"\bCitationizer\s+©\s+Summary\s+of\s+Documents\s+Citing\s+This\s+Document\b", text, maxsplit=1)[0]
        return self._normalize_legal_text(text)

    async def _build_statute_from_document_url(
        self,
        code_name: str,
        document_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        html = await self._request_text(document_url, headers=headers, timeout=45)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        text = self._extract_document_body_text(soup)
        if len(text) < 280:
            return None

        if self._ANTI_BOT_RE.search(text):
            return None

        document_lead = text[:1200]

        has_statute_signal = bool(
            re.search(r"\b\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+", text)
            or re.search(r"\bTitle\s+\d+.*?\bSection\s+[0-9A-Za-z.\-]+", text, flags=re.IGNORECASE)
        )

        if self._CASELAW_RE.search(document_lead) and not has_statute_signal:
            return None

        if self._NON_STATUTE_RE.search(document_lead) and not has_statute_signal:
            return None

        # Ignore obvious navigation/event pages that happen to be long.
        if self._looks_like_navigation_text(text) and not self._contains_statute_signals(text):
            return None

        section_number = self._extract_section_number(text) or self._extract_cite_id(document_url)
        if not section_number:
            section_number = "unknown"

        section_name_match = re.search(r"Section\s+[0-9A-Za-z.\-]+\s*-\s*([^\n\r]+)", text, flags=re.IGNORECASE)
        section_name = section_name_match.group(1).strip()[:180] if section_name_match else f"Section {section_number}"

        official_cite_match = (
            re.search(r"\bCite\s+as:\s*(\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+)", text, flags=re.IGNORECASE)
            or re.search(r"\b\d+\s+O\.S\.\s*§?\s*[0-9A-Za-z.\-]+\b", text)
        )
        official_cite = (
            official_cite_match.group(1) if official_cite_match and official_cite_match.lastindex else official_cite_match.group(0)
        ) if official_cite_match else f"Okla. Stat. {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name,
            full_text=text[:14000],
            legal_area=self._identify_legal_area(text),
            source_url=document_url,
            official_cite=official_cite,
        )

    def _extract_cite_id(self, url: str) -> str:
        match = re.search(r"[?&]CiteID=(\d+)", str(url or ""), flags=re.IGNORECASE)
        return match.group(1) if match else ""

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        direct_oscn_text = await self._request_live_oscn_text(url, headers=headers, timeout=timeout)
        if direct_oscn_text:
            return direct_oscn_text

        try:
            request_url = self._normalize_wayback_url(url)
            content = await self._fetch_page_content_with_archival_fallback(
                request_url,
                timeout_seconds=max(20, int(timeout)),
            )
            if not content:
                return ""
            text = content.decode("utf-8", errors="replace")
            if self._ANTI_BOT_RE.search(str(text or "")):
                return ""
            return text
        except Exception:
            return ""

    async def _request_live_oscn_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        """Fetch live OSCN statute pages without invoking broader archival recovery.

        OSCN DeliverDocument pages are ordinary HTML, but the generic fetch
        stack can spend its bounded-run budget trying Wayback/Common Crawl
        fallbacks first. This narrow fast path keeps Oklahoma health checks
        from stalling when the live official page is already reachable.
        """
        normalized_url = str(url or "").strip()
        if "oscn.net/applications/oscn/deliverdocument.asp" not in normalized_url.lower():
            return ""
        if normalized_url.lower().startswith(("https://web.archive.org/", "http://web.archive.org/")):
            return ""

        def _fetch() -> str:
            try:
                import requests

                request_headers = {
                    "User-Agent": str(headers.get("User-Agent") or "Mozilla/5.0"),
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                }
                response = requests.get(
                    normalized_url,
                    headers=request_headers,
                    timeout=max(1, min(int(timeout or 12), 12)),
                )
                if int(getattr(response, "status_code", 0) or 0) != 200:
                    return ""
                return str(getattr(response, "text", "") or "")
            except Exception:
                return ""

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_fetch),
                timeout=max(2, min(int(timeout or 12) + 1, 14)),
            )
        except Exception:
            return ""

        if not text or self._ANTI_BOT_RE.search(text):
            return ""
        self._record_fetch_event(provider="requests_oscn_direct", success=True)
        return text


# Register this scraper with the registry
StateScraperRegistry.register("OK", OklahomaScraper)


_NORMALIZED_STATUTE_FIELD_NAMES = {field.name for field in dataclass_fields(NormalizedStatute)}
_STATUTE_METADATA_FIELD_NAMES = {field.name for field in dataclass_fields(StatuteMetadata)}


def _statute_dedupe_key(statute: NormalizedStatute) -> str:
    primary = str(statute.statute_id or "").strip().lower()
    if primary:
        return primary
    source = str(statute.source_url or "").strip().lower()
    if source:
        return source
    return ""


def _statute_from_checkpoint_row(
    row: Dict[str, Any],
    *,
    default_state_code: str,
    default_state_name: str,
    default_code_name: str,
) -> Optional[NormalizedStatute]:
    if not isinstance(row, dict):
        return None
    kwargs: Dict[str, Any] = {}
    for name in _NORMALIZED_STATUTE_FIELD_NAMES:
        if name in row:
            kwargs[name] = row.get(name)
    metadata_payload = kwargs.get("metadata")
    if isinstance(metadata_payload, dict):
        metadata_kwargs = {
            key: metadata_payload.get(key)
            for key in _STATUTE_METADATA_FIELD_NAMES
            if key in metadata_payload
        }
        history = metadata_kwargs.get("history")
        if history is None:
            metadata_kwargs["history"] = []
        elif not isinstance(history, list):
            metadata_kwargs["history"] = [str(history)]
        kwargs["metadata"] = StatuteMetadata(**metadata_kwargs)
    elif not isinstance(metadata_payload, StatuteMetadata):
        kwargs["metadata"] = None

    kwargs["state_code"] = str(kwargs.get("state_code") or default_state_code).upper()
    kwargs["state_name"] = str(kwargs.get("state_name") or default_state_name).strip() or default_state_name
    kwargs["code_name"] = str(kwargs.get("code_name") or default_code_name).strip() or default_code_name
    kwargs["statute_id"] = str(kwargs.get("statute_id") or "").strip()
    if not kwargs["statute_id"]:
        return None
    kwargs["source_url"] = str(kwargs.get("source_url") or "").strip()
    kwargs["scraped_at"] = str(kwargs.get("scraped_at") or datetime.now().isoformat())
    kwargs["scraper_version"] = str(kwargs.get("scraper_version") or "1.0")
    kwargs["structured_data"] = dict(kwargs.get("structured_data") or {})
    return NormalizedStatute(**kwargs)


class _OklahomaCheckpoint:
    """Best-effort partial progress checkpoint for Oklahoma's long crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_code = state_code.upper()
        self.interval = max(1, int(float(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_INTERVAL", "500") or 500)))
        self.last_count = 0
        self.last_write_ts = 0.0

    def load(
        self,
        *,
        default_state_name: str,
        default_code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        if not self.path or not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = payload.get("statutes") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        loaded: List[NormalizedStatute] = []
        seen_keys: Set[str] = set()
        for row in rows:
            statute = _statute_from_checkpoint_row(
                row,
                default_state_code=self.state_code,
                default_state_name=default_state_name,
                default_code_name=default_code_name,
            )
            if statute is None:
                continue
            key = _statute_dedupe_key(statute)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            loaded.append(statute)
            if max_statutes is not None and len(loaded) >= int(max_statutes):
                break
        self.last_count = len(loaded)
        return loaded

    def maybe_write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        scanned_candidates: int,
        discovered_candidates: int,
    ) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(
            statutes,
            code_name=code_name,
            scanned_candidates=scanned_candidates,
            discovered_candidates=discovered_candidates,
        )

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        scanned_candidates: int,
        discovered_candidates: int,
    ) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "code_name": code_name,
            "scanned_candidates": int(scanned_candidates),
            "discovered_candidates": int(discovered_candidates),
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
