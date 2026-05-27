"""Scraper for New Hampshire state laws.

This module contains the scraper for New Hampshire statutes from the official state legislative website.
"""

import asyncio
import inspect
import os
import time
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any, List, Dict, Optional
import json
import re
import urllib.request
from urllib.parse import quote, urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewHampshireScraper(BaseStateScraper):
    """Scraper for New Hampshire state laws from gencourt/gc.nh.gov sources."""

    _NH_STATUTE_URL_RE = re.compile(
        r"/rsa/html/(?:NHTOC/[^/?#]+\.htm|(?:[^/?#]+/)+[^/?#]+\.htm)$",
        re.IGNORECASE,
    )
    _NH_TITLE_TEXT_RE = re.compile(r"^TITLE\s+([A-Z0-9-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_CHAPTER_TEXT_RE = re.compile(r"^CHAPTER\s+([0-9A-Z-]+)\s*:\s*(.+)$", re.IGNORECASE)
    _NH_SECTION_LINK_RE = re.compile(r"^Section\s+([0-9A-Z:.-]+)\s+(.+)$", re.IGNORECASE)

    _DIRECT_FETCH_HOST_MARKERS = (
        "web.archive.org/web/",
        "www.gencourt.state.nh.us/",
        "gc.nh.gov/",
    )
    _NH_SECTIONISH_ARCHIVE_RE = re.compile(
        r"/rsa/html/(?!nhtoc/)(?:[ivxlcdm0-9a-z-]+/){2,}[0-9a-z:.-]+\.htm$",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for New Hampshire's legislative website."""
        return "https://www.gencourt.state.nh.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for New Hampshire."""
        return [{
            "name": "New Hampshire Revised Statutes",
            "url": f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            "type": "Code"
        }]

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = self._normalize_wayback_like_url(str(statute.source_url or ""))
            statute.source_url = source
            if self._NH_STATUTE_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from New Hampshire's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/rsa/html/NHTOC.htm",
            f"{self.get_base_url()}/rsa/html/",
            "https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://gc.nh.gov/rsa/html/",
            "http://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "http://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm",
            "https://web.archive.org/web/20250101000000/https://gc.nh.gov/rsa/html/NHTOC.htm",
        ]
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        full_corpus_unbounded = self._full_corpus_enabled() and max_statutes is None
        checkpoint = _NewHampshireCheckpoint(self.state_code)

        # Keep archive discovery bounded so full-corpus runs do not request an
        # effectively unbounded CDX window.
        if full_corpus_unbounded:
            full_corpus_discovery_limit_raw = str(
                os.getenv("STATE_SCRAPER_NH_ARCHIVE_DISCOVERY_LIMIT", "1200") or "1200"
            ).strip()
            try:
                discovery_limit = int(full_corpus_discovery_limit_raw) if full_corpus_discovery_limit_raw else 1200
            except Exception:
                discovery_limit = 1200
            discovery_limit = max(120, min(2500, discovery_limit))
        else:
            discovery_limit = max(10, return_threshold)
        discovered_archive_candidates = await self._discover_archived_rsa_urls(limit=discovery_limit)
        full_corpus_max_candidates_raw = str(
            os.getenv("STATE_SCRAPER_NH_FULL_CORPUS_MAX_CANDIDATES", "120") or "120"
        ).strip()
        try:
            full_corpus_max_candidates = int(full_corpus_max_candidates_raw) if full_corpus_max_candidates_raw else 120
        except Exception:
            full_corpus_max_candidates = 120
        full_corpus_max_candidates = max(12, min(800, full_corpus_max_candidates))
        for archived in discovered_archive_candidates:
            normalized_archived = self._normalize_wayback_like_url(str(archived or ""))
            if not normalized_archived:
                continue
            if full_corpus_unbounded and not self._is_archived_index_candidate(normalized_archived):
                continue
            if normalized_archived not in candidate_urls:
                candidate_urls.append(normalized_archived)
            if full_corpus_unbounded and len(candidate_urls) >= full_corpus_max_candidates:
                break

        resumed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=None if full_corpus_unbounded else max(20, return_threshold * 4),
        )

        archived_title_kwargs: Dict[str, Any] = {
            "max_statutes": None if full_corpus_unbounded else max(10, return_threshold),
        }
        if "checkpoint" in inspect.signature(self._scrape_archived_title_stubs).parameters:
            archived_title_kwargs["checkpoint"] = checkpoint
        archived_title_stubs = await self._scrape_archived_title_stubs(
            code_name,
            **archived_title_kwargs,
        )

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(resumed_statutes)
        if resumed_statutes:
            checkpoint.maybe_write(merged, code_name=code_name, stage_label="resume-seed")

        _merge(archived_title_stubs)
        if archived_title_stubs:
            checkpoint.maybe_write(merged, code_name=code_name, stage_label="archived-title-stubs")
            if full_corpus_unbounded:
                checkpoint.write(
                    merged,
                    code_name=code_name,
                    stage_label="complete",
                    progress={
                        "codes_completed": 1,
                        "codes_total": 1,
                    },
                )
                self.logger.info(
                    "New Hampshire full-corpus archived crawl: statutes=%s; skipping generic fallback sweep",
                    len(merged),
                )
                return merged
        if not full_corpus_unbounded and len(merged) >= return_threshold:
            return merged

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_archived_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        full_corpus_stagnation_cap_raw = str(
            os.getenv("STATE_SCRAPER_NH_MAX_STAGNANT_CANDIDATES", "20") or "20"
        ).strip()
        try:
            full_corpus_stagnation_cap = int(full_corpus_stagnation_cap_raw) if full_corpus_stagnation_cap_raw else 20
        except Exception:
            full_corpus_stagnation_cap = 20
        full_corpus_stagnation_cap = max(4, min(200, full_corpus_stagnation_cap))
        stagnant_candidates = 0

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            merged_before = len(merged)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "N.H. Rev. Stat.",
                max_sections=max(10, return_threshold),
            )
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if statutes:
                checkpoint.maybe_write(merged, code_name=code_name, stage_label=f"candidate:{candidate}")
            if not full_corpus_unbounded and len(merged) >= return_threshold:
                return merged
            if full_corpus_unbounded:
                if len(merged) <= merged_before:
                    stagnant_candidates += 1
                    if stagnant_candidates >= full_corpus_stagnation_cap:
                        self.logger.info(
                            "New Hampshire full-corpus fallback: stopping after %s stagnant candidates with statutes_so_far=%s",
                            stagnant_candidates,
                            len(merged),
                        )
                        break
                else:
                    stagnant_candidates = 0

        checkpoint.write(merged, code_name=code_name, stage_label="complete")
        return merged

    async def _scrape_direct_archived_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            (
                "1:1",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-1.htm",
            ),
            (
                "1:2",
                "https://web.archive.org/web/20250101000000/https://www.gencourt.state.nh.us/rsa/html/I/1/1-2.htm",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 160:
                continue
            title_match = re.search(rf"\b{re.escape(section_number)}\s+([^–-]{{4,180}})", text)
            section_name = title_match.group(1).strip() if title_match else f"Section {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.H. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_hampshire_rsa_wayback_html",
                        "discovery_method": "wayback_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _request_text_direct(self, url: str, timeout: int = 20) -> str:
        canonical = self._normalize_wayback_like_url(url)

        def _request() -> str:
            try:
                req = urllib.request.Request(canonical, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            direct_text = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
            if direct_text:
                return direct_text
        except Exception:
            direct_text = ""

        # Avoid expensive archival/search fallbacks for known NH/Wayback URLs.
        # These paths are best served by direct fetch + replay variants.
        if self._should_prefer_direct_only_fetch(canonical):
            return direct_text or ""

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
        return ""

    async def _fetch_known_rsa_page(self, url: str, timeout_seconds: int = 35) -> bytes:
        # Known official/Wayback RSA pages should be fetched directly before invoking
        # the heavier archival/search fallback stack.
        normalized_url = self._normalize_wayback_like_url(url)
        lower_url = str(normalized_url or "").lower()
        is_known_rsa = "/rsa/html/" in lower_url and (
            "gencourt.state.nh.us/" in lower_url
            or "gc.nh.gov/" in lower_url
            or "web.archive.org/web/" in lower_url
        )
        if is_known_rsa:
            wayback_candidates = self._wayback_replay_candidates(normalized_url)
            ordered_candidates: List[str] = []
            for candidate in wayback_candidates:
                candidate_text = str(candidate or "").strip()
                if candidate_text and candidate_text not in ordered_candidates:
                    ordered_candidates.append(candidate_text)
            for candidate in ordered_candidates:
                direct = await self._request_text_direct(candidate, timeout=max(5, timeout_seconds))
                if direct:
                    return direct.encode("utf-8", errors="replace")
            # Avoid expensive archival/search fallback loops for known RSA/Wayback
            # URLs when direct replay fetches miss.
            return b""
        return await self._fetch_page_content_with_archival_fallback(normalized_url, timeout_seconds=timeout_seconds)

    def _should_prefer_direct_only_fetch(self, url: str) -> bool:
        value = str(url or "").strip().lower()
        if not value:
            return False
        if "/rsa/html/" not in value:
            return False
        return any(marker in value for marker in self._DIRECT_FETCH_HOST_MARKERS)

    def _derive_direct_rsa_candidates(self, value: str) -> List[str]:
        url = str(value or "").strip()
        if not url:
            return []
        out: List[str] = []
        if "web.archive.org/web/" in url.lower():
            match = re.search(
                r"/web/\d+(?:if_|id_)?/(https?://.+)$",
                url,
                flags=re.IGNORECASE,
            )
            if match:
                out.append(self._normalize_wayback_like_url(match.group(1)))
        lower_candidates = [str(candidate or "").strip().lower() for candidate in out]
        if any("www.gencourt.state.nh.us/" in candidate for candidate in lower_candidates):
            out.append(
                re.sub(
                    r"^https?://www\.gencourt\.state\.nh\.us/",
                    "https://gc.nh.gov/",
                    out[0],
                    flags=re.IGNORECASE,
                )
            )
        elif any("gc.nh.gov/" in candidate for candidate in lower_candidates):
            out.append(
                re.sub(
                    r"^https?://gc\.nh\.gov/",
                    "https://www.gencourt.state.nh.us/",
                    out[0],
                    flags=re.IGNORECASE,
                )
            )
        deduped: List[str] = []
        for candidate in out:
            text = str(candidate or "").strip()
            if text and text not in deduped:
                deduped.append(text)
        return deduped

    def _derive_section_number_from_href(self, *, chapter_id: str, section_url: str, href_text: str) -> str:
        chapter = str(chapter_id or "").strip()
        if not chapter:
            return ""
        normalized_url = self._normalize_wayback_like_url(section_url)
        lower_url = normalized_url.lower()
        if "/rsa/html/" not in lower_url:
            return ""
        try:
            path_part = normalized_url.split("://", 1)[-1].split("/", 1)[-1]
        except Exception:
            path_part = normalized_url
        if not path_part:
            return ""
        basename = PurePosixPath(path_part).name
        if not basename.lower().endswith(".htm"):
            return ""
        stem = basename[:-4].strip()
        if not stem:
            return ""
        stem = re.sub(r"[^0-9A-Za-z:-]", "", stem)
        if not stem:
            return ""
        chapter_lower = chapter.lower()
        stem_lower = stem.lower()
        if stem_lower.startswith(chapter_lower + "-"):
            suffix = stem[len(chapter) + 1 :].strip()
            if suffix:
                return f"{chapter}:{suffix}"
        if stem_lower.startswith(chapter_lower + ":"):
            suffix = stem[len(chapter) + 1 :].strip()
            if suffix:
                return f"{chapter}:{suffix}"
        if stem_lower == chapter_lower:
            fallback_match = re.search(r"\b([0-9A-Za-z:.-]{2,})\b", str(href_text or ""))
            if fallback_match:
                candidate = fallback_match.group(1).strip()
                if candidate and candidate.lower() != chapter_lower:
                    return candidate
            return ""
        if ":" in stem:
            return stem
        # Last-resort: treat `<chapter>-<suffix>` as `<chapter>:<suffix>` when possible.
        suffix_match = re.match(rf"^{re.escape(chapter_lower)}-([0-9A-Za-z.-]+)$", stem_lower)
        if suffix_match:
            suffix = str(suffix_match.group(1) or "").strip()
            if suffix:
                return f"{chapter}:{suffix}"
        return ""

    async def _scrape_archived_title_stubs(
        self,
        code_name: str,
        max_statutes: Optional[int] = 100,
        checkpoint: Optional["_NewHampshireCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = "https://web.archive.org/web/20250124114611/https://www.gencourt.state.nh.us/rsa/html/NHTOC.htm"

        try:
            payload = await self._fetch_known_rsa_page(root_url, timeout_seconds=35)
            if not payload:
                if checkpoint is not None:
                    checkpoint.write(
                        [],
                        code_name=code_name,
                        stage_label="root-unavailable",
                        progress={
                            "titles_scanned": 0,
                            "discovered_titles": 0,
                            "chapters_scanned": 0,
                            "discovered_chapters": 0,
                            "codes_completed": 0,
                            "codes_total": 1,
                            "fetch_status": "root_unavailable",
                        },
                    )
                return []
        except Exception:
            if checkpoint is not None:
                checkpoint.write(
                    [],
                    code_name=code_name,
                    stage_label="root-fetch-error",
                    progress={
                        "titles_scanned": 0,
                        "discovered_titles": 0,
                        "chapters_scanned": 0,
                        "discovered_chapters": 0,
                        "codes_completed": 0,
                        "codes_total": 1,
                        "fetch_status": "root_fetch_error",
                    },
                )
            return []

        soup = BeautifulSoup(payload, "html.parser")
        full_corpus_mode = self._full_corpus_enabled()

        def _limit_reached(size: int) -> bool:
            return max_statutes is not None and size >= max_statutes

        title_urls: List[str] = []
        seen_titles = set()
        title_stubs: List[NormalizedStatute] = []
        title_url_limit = max_statutes if max_statutes is not None else None
        if not full_corpus_mode and title_url_limit is not None:
            title_url_limit = min(title_url_limit, 12)
        for a in soup.find_all("a", href=True):
            text = str(a.get_text(" ", strip=True) or "").strip()
            title_match = self._NH_TITLE_TEXT_RE.match(text)
            href = str(a.get("href") or "").strip()
            full_url = self._normalize_wayback_like_url(urljoin(root_url, href))
            if "/rsa/html/nhtoc/" not in full_url.lower():
                continue
            if full_url in seen_titles:
                continue
            seen_titles.add(full_url)
            title_urls.append(full_url)
            if title_match and not full_corpus_mode and not _limit_reached(len(title_stubs)):
                title_no = title_match.group(1).upper()
                title_name = title_match.group(2).strip()
                title_stubs.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_no}",
                        code_name=code_name,
                        section_number=f"Title {title_no}",
                        section_name=text[:200],
                        full_text=f"New Hampshire Revised Statutes {text}",
                        source_url=full_url,
                        legal_area=self._identify_legal_area(title_name),
                        official_cite=f"N.H. Rev. Stat. Title {title_no}",
                        metadata=StatuteMetadata(),
                        structured_data={"skip_hydrate": True, "record_type": "archived_title_stub"},
                    )
                )
                if checkpoint is not None:
                    checkpoint.maybe_write(title_stubs, code_name=code_name, stage_label=f"title:{title_no}")
            if title_url_limit is not None and len(title_urls) >= title_url_limit:
                break

        if checkpoint is not None and not title_urls:
            checkpoint.write(
                title_stubs,
                code_name=code_name,
                stage_label="title-discovery-empty",
                progress={
                    "titles_scanned": 0,
                    "discovered_titles": 0,
                    "chapters_scanned": 0,
                    "discovered_chapters": 0,
                    "codes_completed": 0,
                    "codes_total": 1,
                    "fetch_status": "no_titles_discovered",
                },
            )

        if title_urls:
            self.logger.info(
                "New Hampshire archived index: discovered_titles=%s full_corpus=%s",
                len(title_urls),
                self._full_corpus_enabled(),
            )

        out: List[NormalizedStatute] = list(title_stubs)
        seen_output_keys: set[str] = set()
        for statute in out:
            statute_id_key = str(statute.statute_id or "").strip().lower()
            source_key = str(statute.source_url or "").strip().lower()
            if statute_id_key:
                seen_output_keys.add(statute_id_key)
            if source_key:
                seen_output_keys.add(source_key)
        seen_chapters = set()
        chapter_urls: List[tuple[str, str, str]] = []

        chapter_fetch_limit = None if max_statutes is None else max(8, int(max_statutes) * 4)

        total_titles = len(title_urls)
        for title_index, title_url in enumerate(title_urls, start=1):
            if _limit_reached(len(out)):
                break
            if chapter_fetch_limit is not None and len(chapter_urls) >= chapter_fetch_limit:
                break
            try:
                title_payload = await self._fetch_known_rsa_page(title_url, timeout_seconds=35)
                if not title_payload:
                    continue
            except Exception:
                continue

            title_soup = BeautifulSoup(title_payload, "html.parser")
            for a in title_soup.find_all("a", href=True):
                if _limit_reached(len(out)):
                    break
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_CHAPTER_TEXT_RE.match(text)
                if not match:
                    continue
                chapter_id = match.group(1).upper()
                key = chapter_id.lower()
                if key in seen_chapters:
                    continue
                seen_chapters.add(key)

                source_url = self._normalize_wayback_like_url(urljoin(title_url, href))
                chapter_name = text[:200] if text else f"Chapter {chapter_id}"
                chapter_urls.append((chapter_id, chapter_name, source_url))
                if not full_corpus_mode:
                    out.append(
                        NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § Chapter {chapter_id}",
                            code_name=code_name,
                            section_number=f"Chapter {chapter_id}",
                            section_name=chapter_name,
                            full_text=f"New Hampshire Revised Statutes {chapter_name}: {source_url}",
                            source_url=source_url,
                            legal_area=self._identify_legal_area(chapter_name),
                            official_cite=f"N.H. Rev. Stat. ch. {chapter_id}",
                            metadata=StatuteMetadata(),
                            structured_data={"skip_hydrate": True, "record_type": "archived_chapter_stub"},
                        )
                    )
                    if checkpoint is not None:
                        checkpoint.maybe_write(out, code_name=code_name, stage_label=f"chapter-stub:{chapter_id}")

            if title_index == 1 or title_index % 5 == 0:
                self.logger.info(
                    "New Hampshire archived index: titles_scanned=%s/%s sections=%s statutes_so_far=%s",
                    title_index,
                    total_titles,
                    len(chapter_urls),
                    len(out),
                )
                if checkpoint is not None:
                    checkpoint.maybe_write(
                        out,
                        code_name=code_name,
                        stage_label=f"title-scan:{title_index}",
                        progress={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(total_titles),
                            "discovered_chapters": int(len(chapter_urls)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )

        if _limit_reached(len(out)):
            return out[:max_statutes]

        section_concurrency = max(
            1,
            int(os.getenv("STATE_SCRAPER_NH_SECTION_CONCURRENCY", "6") or "6"),
        )
        section_sem = asyncio.Semaphore(section_concurrency)

        async def _fetch_chapter_sections(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            try:
                chapter_payload = await self._fetch_known_rsa_page(chapter_url, timeout_seconds=35)
                if not chapter_payload:
                    return []
            except Exception:
                return []

            chapter_soup = BeautifulSoup(chapter_payload, "html.parser")
            section_links: List[tuple[str, str, str]] = []
            seen_local = set()
            for a in chapter_soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                text = str(a.get_text(" ", strip=True) or "").strip()
                if not href.endswith(".htm"):
                    continue
                match = self._NH_SECTION_LINK_RE.match(text)
                section_url = self._normalize_wayback_like_url(urljoin(chapter_url, href))
                section_number = ""
                section_title = ""
                if match:
                    section_number = match.group(1).strip()
                    section_title = match.group(2).strip().rstrip(".")
                else:
                    section_number = self._derive_section_number_from_href(
                        chapter_id=chapter_id,
                        section_url=section_url,
                        href_text=text,
                    )
                    if not section_number:
                        continue
                    section_title = text.strip().rstrip(".")
                if not section_title:
                    section_title = f"Section {section_number}"
                section_key = section_number.lower()
                if section_key in seen_local:
                    continue
                seen_local.add(section_key)
                statute_id_key = f"{code_name} § {section_number}".strip().lower()
                source_key = str(section_url or "").strip().lower()
                if statute_id_key in seen_output_keys or source_key in seen_output_keys:
                    continue
                section_links.append(
                    (
                        section_number,
                        section_title,
                        section_url,
                    )
                )

            section_statutes: List[NormalizedStatute] = []
            seen_local_statute_keys: set[str] = set()

            async def _fetch_section(
                section_number: str,
                section_title: str,
                section_url: str,
            ) -> Optional[NormalizedStatute]:
                async with section_sem:
                    try:
                        section_payload = await self._fetch_known_rsa_page(section_url, timeout_seconds=35)
                    except Exception:
                        return None
                    section_text = self._extract_statute_text(section_payload)
                    if len(section_text) < 160:
                        return None
                    section_name = f"Section {section_number} {section_title}".strip()
                    return NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=section_text,
                        source_url=section_url,
                        legal_area=self._identify_legal_area(section_name or chapter_name),
                        official_cite=f"N.H. Rev. Stat. § {section_number}",
                        metadata=StatuteMetadata(),
                    )

            tasks = [
                asyncio.create_task(_fetch_section(section_number, section_title, section_url))
                for section_number, section_title, section_url in section_links
            ]
            scanned_sections = 0
            for task in asyncio.as_completed(tasks):
                scanned_sections += 1
                statute = await task
                if statute is None:
                    continue
                local_key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if local_key and local_key in seen_local_statute_keys:
                    continue
                if local_key:
                    seen_local_statute_keys.add(local_key)
                section_statutes.append(statute)
                if len(section_statutes) == 1 or len(section_statutes) % 40 == 0:
                    self.logger.info(
                        "New Hampshire archived index: chapter=%s scanned_sections=%s/%s statutes_so_far=%s",
                        chapter_id,
                        len(section_statutes),
                        len(section_links),
                        len(section_statutes),
                    )
                if checkpoint is not None and (
                    scanned_sections == 1
                    or scanned_sections % 200 == 0
                    or scanned_sections == len(section_links)
                ):
                    checkpoint.maybe_write(
                        [],
                        code_name=code_name,
                        stage_label=f"chapter-progress:{chapter_id}:{scanned_sections}",
                        progress={
                            "titles_scanned": int(total_titles),
                            "discovered_titles": int(total_titles),
                            "chapters_scanned": 0,
                            "discovered_chapters": int(len(chapter_urls)),
                            "chapter_id": str(chapter_id),
                            "sections_scanned": int(scanned_sections),
                            "discovered_sections": int(len(section_links)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
                if _limit_reached(len(section_statutes)):
                    break
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if section_links:
                self.logger.info(
                    "New Hampshire archived index: chapter=%s scanned_sections=%s/%s statutes_so_far=%s",
                    chapter_id,
                    len(section_statutes),
                    len(section_links),
                    len(section_statutes),
                )
            return section_statutes

        sem = asyncio.Semaphore(4)

        async def _bounded_fetch(chapter_id: str, chapter_name: str, chapter_url: str) -> List[NormalizedStatute]:
            async with sem:
                return await _fetch_chapter_sections(chapter_id, chapter_name, chapter_url)

        if self._full_corpus_enabled():
            chapters_to_fetch = chapter_urls if max_statutes is None else chapter_urls[: chapter_fetch_limit or len(chapter_urls)]
        else:
            chapters_to_fetch = chapter_urls[:8]
        if chapter_urls:
            self.logger.info(
                "New Hampshire archived index: discovered_chapters=%s fetched_chapters=%s",
                len(chapter_urls),
                len(chapters_to_fetch),
            )
            if checkpoint is not None:
                checkpoint.maybe_write(
                    out,
                    code_name=code_name,
                    stage_label="chapter-discovery",
                    progress={
                        "titles_scanned": int(total_titles),
                        "discovered_titles": int(total_titles),
                        "chapters_scanned": 0,
                        "discovered_chapters": int(len(chapters_to_fetch)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
        async def _bounded_fetch_with_meta(
            chapter_id: str,
            chapter_name: str,
            chapter_url: str,
        ) -> tuple[str, list[NormalizedStatute], Optional[Exception]]:
            try:
                section_batch = await _bounded_fetch(chapter_id, chapter_name, chapter_url)
                return chapter_id, section_batch, None
            except Exception as exc:  # pragma: no cover - defensive guard
                return chapter_id, [], exc

        chapter_tasks = [
            asyncio.create_task(_bounded_fetch_with_meta(chapter_id, chapter_name, chapter_url))
            for chapter_id, chapter_name, chapter_url in chapters_to_fetch
        ]
        completed_chapters = 0
        for completed_task in asyncio.as_completed(chapter_tasks):
            chapter_id, section_batch, section_error = await completed_task
            completed_chapters += 1
            chapter_index = completed_chapters
            if section_error is not None:
                continue
            if checkpoint is not None and (
                chapter_index == 1
                or chapter_index % 20 == 0
                or chapter_index == len(chapters_to_fetch)
            ):
                checkpoint.maybe_write(
                    out,
                    code_name=code_name,
                    stage_label=f"chapter-scan:{chapter_index}",
                    progress={
                        "titles_scanned": int(total_titles),
                        "discovered_titles": int(total_titles),
                        "chapters_scanned": int(chapter_index),
                        "discovered_chapters": int(len(chapters_to_fetch)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
            for statute in section_batch:
                statute_id_key = str(statute.statute_id or "").strip().lower()
                source_key = str(statute.source_url or "").strip().lower()
                if (statute_id_key and statute_id_key in seen_output_keys) or (
                    source_key and source_key in seen_output_keys
                ):
                    continue
                if statute_id_key:
                    seen_output_keys.add(statute_id_key)
                if source_key:
                    seen_output_keys.add(source_key)
                out.append(statute)
                if checkpoint is not None and (len(out) == 1 or len(out) % 40 == 0):
                    checkpoint.maybe_write(
                        out,
                        code_name=code_name,
                        stage_label=f"chapter:{chapter_id}",
                        progress={
                            "titles_scanned": int(total_titles),
                            "discovered_titles": int(total_titles),
                            "chapters_scanned": int(chapter_index),
                            "discovered_chapters": int(len(chapters_to_fetch)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
                if len(out) == 1 or len(out) % 40 == 0:
                    self.logger.info(
                        "New Hampshire archived index: global_total_statutes_so_far=%s chapter=%s",
                        len(out),
                        chapter_id,
                    )
                if _limit_reached(len(out)):
                    if checkpoint is not None:
                        checkpoint.write(
                            out,
                            code_name=code_name,
                            stage_label=f"limit:{chapter_id}",
                            progress={
                                "titles_scanned": int(total_titles),
                                "discovered_titles": int(total_titles),
                                "chapters_scanned": int(chapter_index),
                                "discovered_chapters": int(len(chapters_to_fetch)),
                                "codes_completed": 1,
                                "codes_total": 1,
                            },
                        )
                    return out[:max_statutes]

        if checkpoint is not None:
            checkpoint.write(
                out,
                code_name=code_name,
                stage_label="archived-title-stubs-complete",
                progress={
                    "titles_scanned": int(total_titles),
                    "discovered_titles": int(total_titles),
                    "chapters_scanned": int(len(chapters_to_fetch)),
                    "discovered_chapters": int(len(chapters_to_fetch)),
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
        return out

    def _extract_statute_text(self, payload: bytes) -> str:
        if not payload:
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""

        soup = BeautifulSoup(payload, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        match = re.search(
            r"(Section\s+[0-9A-Z:.-]+.*?Source\.[^\n]*?(?:\d{4}[^\n]*)?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)[:4000]
        return text[:4000]

    async def _discover_archived_rsa_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=www.gencourt.state.nh.us/rsa/html/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._request_text_direct(cdx_url, timeout=35)
            if not payload:
                payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
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
            lower_original = original.lower()
            if "/rsa/html/" not in lower_original:
                continue
            replay = self._normalize_wayback_like_url(
                f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            )
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    def _normalize_wayback_like_url(self, value: str) -> str:
        url = str(value or "").strip()
        if not url:
            return url
        url = re.sub(r"(web\.archive\.org/web/\d+/https?):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        url = re.sub(r"(web\.archive\.org/web/\d+/http):/([^/])", r"\1://\2", url, flags=re.IGNORECASE)
        return url

    def _parse_json_rows(self, payload: bytes) -> List[List[object]]:
        if not payload:
            return []
        try:
            parsed = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed[1:] if isinstance(row, list)]

    def _is_archived_index_candidate(self, url: str) -> bool:
        value = self._normalize_wayback_like_url(str(url or ""))
        lower = value.lower()
        if "/rsa/html/" not in lower:
            return False
        if "/rsa/html/nhtoc" in lower:
            return True
        if lower.endswith("/rsa/html") or lower.endswith("/rsa/html/"):
            return True
        if self._NH_SECTIONISH_ARCHIVE_RE.search(lower):
            return False
        return lower.endswith(".htm")


_NORMALIZED_STATUTE_FIELD_NAMES = {field.name for field in dataclass_fields(NormalizedStatute)}
_STATUTE_METADATA_FIELD_NAMES = {field.name for field in dataclass_fields(StatuteMetadata)}


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


class _NewHampshireCheckpoint:
    """Best-effort partial progress checkpoint for New Hampshire archive crawls."""

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
        self.last_stage_label = ""

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
        seen_keys = set()
        for row in rows:
            statute = _statute_from_checkpoint_row(
                row,
                default_state_code=self.state_code,
                default_state_name=default_state_name,
                default_code_name=default_code_name,
            )
            if statute is None:
                continue
            key = str(statute.statute_id or statute.source_url or "").strip().lower()
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
        stage_label: str,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        count = len(statutes)
        has_progress = isinstance(progress, dict) and bool(progress)
        current_stage_label = str(stage_label or "").strip()
        if not self.path:
            return
        if count <= 0 and not has_progress:
            return
        now_ts = time.time()
        stage_changed = bool(current_stage_label) and current_stage_label != self.last_stage_label
        min_seconds = 30 if has_progress else 120
        if (
            not stage_changed
            and count - self.last_count < self.interval
            and now_ts - self.last_write_ts < min_seconds
        ):
            return
        self.write(statutes, code_name=code_name, stage_label=stage_label, progress=progress)

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        stage_label: str,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.path:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "code_name": code_name,
            "stage_label": stage_label,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        if isinstance(progress, dict) and progress:
            payload["progress"] = dict(progress)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
        self.last_stage_label = str(stage_label or "").strip()


# Register this scraper with the registry
StateScraperRegistry.register("NH", NewHampshireScraper)
