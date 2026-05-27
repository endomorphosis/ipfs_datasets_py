"""Scraper for Mississippi state laws.

This module contains the scraper for Mississippi statutes from the official state legislative website.
"""

import asyncio
import inspect
import json
import os
import re
import ssl
import time
from dataclasses import fields as dataclass_fields
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin
import urllib.request

from bs4 import BeautifulSoup

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MississippiScraper(BaseStateScraper):
    """Scraper for Mississippi state laws from http://www.legislature.ms.gov"""

    _ARCHIVE_INDEX_URLS = [
        "https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
        "https://web.archive.org/web/20001009002301/http://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
        "https://web.archive.org/web/20240414234245/https://billstatus.ls.state.ms.us/1997/all_measures/allmsrs.htm",
    ]
    _INSECURE_TLS_RETRY_DOMAINS = ("legislature.ms.gov", "billstatus.ls.state.ms.us")
    _DIRECT_FETCH_HOST_MARKERS = (
        "web.archive.org/web/",
        "billstatus.ls.state.ms.us/",
        "www.ls.state.ms.us/",
        "legislature.ms.gov/",
    )
    _JUSTIA_INDEX_URLS = (
        "https://law.justia.com/codes/mississippi/2024/",
        "https://law.justia.com/codes/mississippi/2025/",
    )
    _JUSTIA_SECTION_URL_RE = re.compile(
        r"/codes/mississippi/(?:\d{4}/)?title-[^/]+(?:/[^/]+)*/section-[^/]+/?$",
        re.IGNORECASE,
    )
    _JUSTIA_CHAPTER_URL_RE = re.compile(
        r"/codes/mississippi/(?:\d{4}/)?title-[^/]+/(?:chapter-[^/]+|article-[^/]+|part-[^/]+|subpart-[^/]+|general-provisions)/?$",
        re.IGNORECASE,
    )
    _JUSTIA_TITLE_URL_RE = re.compile(
        r"/codes/mississippi/(?:\d{4}/)?title-[^/]+/?$",
        re.IGNORECASE,
    )
    _JUSTIA_WAYBACK_CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
    _JUSTIA_WAYBACK_FETCH_ROOT = "https://web.archive.org/web/"
    _JUSTIA_WAYBACK_INDEX_FALLBACKS: Dict[str, tuple[str, ...]] = {
        "https://law.justia.com/codes/mississippi/2024/": (
            "https://web.archive.org/web/20260408190043/https://law.justia.com/codes/mississippi/2024/",
            "https://web.archive.org/web/20250329184729/https://law.justia.com/codes/mississippi/2024/",
            "https://web.archive.org/web/20241231055808/https://law.justia.com/codes/mississippi/2024/",
        ),
        "https://law.justia.com/codes/mississippi/2025/": (
            "https://web.archive.org/web/20260412022508/https://law.justia.com/codes/mississippi/2025/",
        ),
    }
    _JUSTIA_BLOCKED_TEXT_RE = re.compile(
        r"(performing security verification|this website uses a security service|just a moment\.\.\.|target url returned error 403)",
        re.IGNORECASE,
    )
    _JUSTIA_READER_LINK_RE = re.compile(
        r"\((https?://law\.justia\.com/codes/mississippi/[^)\s]+)\)",
        re.IGNORECASE,
    )
    _JUSTIA_READER_RAW_LINK_RE = re.compile(
        r"https?://law\.justia\.com/codes/mississippi/[^\s)]+",
        re.IGNORECASE,
    )
    _UNICOURT_ROOT_URL = "https://unicourt.github.io/cic-code-ms/"
    _UNICOURT_TITLE_LINK_RE = re.compile(
        r"/transforms/ms/ocms/(?P<release>r\d+)/gov\.ms\.code\.title\.(?P<title>\d{2}|\d+)\.html$",
        re.IGNORECASE,
    )
    _UNICOURT_SECTION_HEADING_RE = re.compile(r"§+\s*([0-9A-Za-z.\-]+)")
    
    def get_base_url(self) -> str:
        """Return the base URL for Mississippi's legislative website."""
        return "http://www.legislature.ms.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Mississippi."""
        return [{
            "name": "Mississippi Code",
            "url": "https://www.legislature.ms.gov/legislation/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Mississippi's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        full_corpus_unbounded = self._full_corpus_enabled() and max_statutes is None

        common_crawl_timeout_raw = str(
            os.getenv("STATE_SCRAPER_MS_COMMON_CRAWL_TIMEOUT_SECONDS", "45") or "45"
        ).strip()
        try:
            common_crawl_timeout = float(common_crawl_timeout_raw) if common_crawl_timeout_raw else 45.0
        except Exception:
            common_crawl_timeout = 45.0
        common_crawl_timeout = max(0.0, min(300.0, common_crawl_timeout))

        async def _run_common_crawl_seed(max_rows: int) -> List[NormalizedStatute]:
            target_rows = max(1, int(max_rows or 1))
            try:
                if common_crawl_timeout > 0:
                    return await asyncio.wait_for(
                        self._scrape_common_crawl_code_sections(
                            code_name=code_name,
                            max_statutes=target_rows,
                        ),
                        timeout=common_crawl_timeout,
                    )
                return await self._scrape_common_crawl_code_sections(
                    code_name=code_name,
                    max_statutes=target_rows,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Mississippi common-crawl seed timed out after %.1fs (target=%s); continuing with alternate paths",
                    common_crawl_timeout,
                    target_rows,
                )
                return []
            except Exception as exc:
                self.logger.warning(
                    "Mississippi common-crawl seed failed (%s); continuing with alternate paths",
                    exc,
                )
                return []

        phase_timeout_defaults = {
            "justia_html": 300.0 if full_corpus_unbounded else 180.0,
            "justia_wayback": 0.0 if full_corpus_unbounded else 180.0,
            "justia_reader": 0.0 if full_corpus_unbounded else 240.0,
            "unicourt": 0.0 if full_corpus_unbounded else 300.0,
        }

        def _phase_timeout_seconds(phase_name: str) -> float:
            env_name = f"STATE_SCRAPER_MS_{phase_name.upper()}_TIMEOUT_SECONDS"
            raw_value = str(
                os.getenv(env_name, str(phase_timeout_defaults.get(phase_name, 180.0)))
                or str(phase_timeout_defaults.get(phase_name, 180.0))
            ).strip()
            try:
                value = float(raw_value) if raw_value else float(phase_timeout_defaults.get(phase_name, 180.0))
            except Exception:
                value = float(phase_timeout_defaults.get(phase_name, 180.0))
            return max(0.0, min(900.0, value))

        async def _run_phase(
            phase_name: str,
            coro: Any,
        ) -> List[NormalizedStatute]:
            timeout_seconds = _phase_timeout_seconds(phase_name)
            try:
                if timeout_seconds > 0:
                    return await asyncio.wait_for(coro, timeout=timeout_seconds)
                return await coro
            except asyncio.TimeoutError:
                self.logger.warning(
                    "Mississippi %s phase timed out after %.1fs; continuing with alternate paths",
                    phase_name,
                    timeout_seconds,
                )
                return []
            except Exception as exc:
                self.logger.warning(
                    "Mississippi %s phase failed (%s); continuing with alternate paths",
                    phase_name,
                    exc,
                )
                return []

        allow_archive_full_corpus = str(
            os.getenv("STATE_SCRAPER_MS_ENABLE_ARCHIVE_BILL_HISTORY_FULL_CORPUS", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

        if not self._full_corpus_enabled():
            common_crawl = await _run_common_crawl_seed(limit or 5)
            if common_crawl:
                return common_crawl[:limit] if limit is not None else common_crawl

            recovery = await self._scrape_jina_justia_seed_sections(code_name=code_name, max_statutes=limit or 1)
            if recovery:
                return recovery[:limit] if limit is not None else recovery

            use_unicourt_bounded_fallback = str(
                os.getenv("STATE_SCRAPER_MS_ENABLE_UNICOURT_BOUNDED_FALLBACK", "1")
            ).strip().lower() not in {"0", "false", "no", "off"}
            if use_unicourt_bounded_fallback:
                unicourt_rows = await _run_phase(
                    "unicourt",
                    self._scrape_unicourt_code_sections(
                        code_name=code_name,
                        max_statutes=max(1, int(limit or 1)),
                        checkpoint=None,
                    ),
                )
                if unicourt_rows:
                    self.logger.info(
                        "Mississippi bounded fallback via Unicourt: statutes_so_far=%s",
                        len(unicourt_rows),
                    )
                    return unicourt_rows[:limit] if limit is not None else unicourt_rows

        checkpoint = _MississippiCheckpoint(self.state_code)
        seed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=(limit or 1000000),
        )
        checkpoint.write_progress(
            statutes=seed_statutes,
            code_name=code_name,
            stage_label="mississippi:scrape_code:start",
            scanned_history_urls=len(seed_statutes),
            discovered_history_urls=len(seed_statutes),
            extra_progress={
                "codes_total": 1,
                "codes_completed": 0,
            },
        )
        if self._full_corpus_enabled():
            use_common_crawl_seed = str(
                os.getenv("STATE_SCRAPER_MS_COMMON_CRAWL_FULL_CORPUS_SEEDS_ENABLED", "1")
            ).strip().lower() not in {"0", "false", "no", "off"}
            common_crawl_seed_target_raw = str(
                os.getenv("STATE_SCRAPER_MS_COMMON_CRAWL_SEED_TARGET", "") or ""
            ).strip()
            try:
                common_crawl_seed_target = int(common_crawl_seed_target_raw) if common_crawl_seed_target_raw else 600
            except Exception:
                common_crawl_seed_target = 600
            common_crawl_seed_target = max(25, min(2000, common_crawl_seed_target))
            if use_common_crawl_seed:
                common_crawl_seed = await _run_common_crawl_seed(common_crawl_seed_target)
                if common_crawl_seed:
                    merged_seed: List[NormalizedStatute] = []
                    seen_seed_keys = set()
                    for statute in list(seed_statutes) + list(common_crawl_seed):
                        statute_key = _statute_dedupe_key(statute)
                        if statute_key and statute_key in seen_seed_keys:
                            continue
                        if statute_key:
                            seen_seed_keys.add(statute_key)
                        merged_seed.append(statute)
                    seed_statutes = merged_seed[: (limit or 1000000)]
                    checkpoint.maybe_write(
                        seed_statutes,
                        code_name=code_name,
                        stage_label="mississippi:seed:common_crawl",
                        scanned_history_urls=len(seed_statutes),
                        discovered_history_urls=len(seed_statutes),
                    )
                    self.logger.info(
                        "Mississippi full-corpus common-crawl seeds: statutes_so_far=%s target=%s",
                        len(seed_statutes),
                        common_crawl_seed_target,
                    )
            else:
                self.logger.info(
                    "Mississippi full-corpus common-crawl seeds disabled by env STATE_SCRAPER_MS_COMMON_CRAWL_FULL_CORPUS_SEEDS_ENABLED"
                )

            if not seed_statutes:
                reader_seed_limit_raw = str(
                    os.getenv("STATE_SCRAPER_MS_READER_SEED_TARGET", "") or ""
                ).strip()
                try:
                    reader_seed_limit = int(reader_seed_limit_raw) if reader_seed_limit_raw else 2
                except Exception:
                    reader_seed_limit = 2
                reader_seed_limit = max(1, min(8, reader_seed_limit))
                reader_seed = await self._scrape_jina_justia_seed_sections(
                    code_name=code_name,
                    max_statutes=reader_seed_limit,
                )
                if reader_seed:
                    seed_statutes = list(reader_seed)
                    checkpoint.maybe_write(
                        seed_statutes,
                        code_name=code_name,
                        stage_label="mississippi:seed:jina",
                        scanned_history_urls=0,
                        discovered_history_urls=0,
                    )
                    self.logger.info(
                        "Mississippi full-corpus bootstrap via non-throttled reader seeds: statutes_so_far=%s",
                        len(seed_statutes),
                    )

            justia_target_raw = str(os.getenv("STATE_SCRAPER_MS_JUSTIA_TARGET", "30000") or "30000").strip()
            try:
                justia_target = int(justia_target_raw) if justia_target_raw else 30000
            except Exception:
                justia_target = 30000
            justia_target = max(500, min(80000, justia_target))
            justia_statutes = await _run_phase(
                "justia_html",
                self._scrape_justia_code_sections(
                    code_name=code_name,
                    max_statutes=justia_target,
                    checkpoint=checkpoint,
                ),
            )
            self.logger.info(
                "Mississippi full-corpus Justia HTML phase: statutes=%s target=%s",
                len(justia_statutes),
                justia_target,
            )
            if justia_statutes:
                checkpoint.write_progress(
                    statutes=justia_statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia:complete",
                    scanned_history_urls=len(justia_statutes),
                    discovered_history_urls=len(justia_statutes),
                    extra_progress={
                        "codes_total": 1,
                        "codes_completed": 1,
                    },
                )
                self.logger.info(
                    "Mississippi full-corpus Justia path: statutes_so_far=%s",
                    len(justia_statutes),
                )
                return justia_statutes[:limit] if limit is not None else justia_statutes

            wayback_statutes = await _run_phase(
                "justia_wayback",
                self._scrape_justia_wayback_code_sections(
                    code_name=code_name,
                    max_statutes=justia_target,
                ),
            )
            self.logger.info(
                "Mississippi full-corpus Justia Wayback phase: statutes=%s target=%s",
                len(wayback_statutes),
                justia_target,
            )
            if wayback_statutes:
                checkpoint.write_progress(
                    statutes=wayback_statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia-wayback:complete",
                    scanned_history_urls=len(wayback_statutes),
                    discovered_history_urls=len(wayback_statutes),
                    extra_progress={
                        "codes_total": 1,
                        "codes_completed": 1,
                    },
                )
                self.logger.info(
                    "Mississippi full-corpus Justia Wayback path: statutes_so_far=%s",
                    len(wayback_statutes),
                )
                return wayback_statutes[:limit] if limit is not None else wayback_statutes

            reader_statutes = await _run_phase(
                "justia_reader",
                self._scrape_jina_justia_code_sections(
                    code_name=code_name,
                    max_statutes=justia_target,
                    checkpoint=checkpoint,
                ),
            )
            self.logger.info(
                "Mississippi full-corpus Justia reader phase: statutes=%s target=%s",
                len(reader_statutes),
                justia_target,
            )
            if reader_statutes:
                checkpoint.write_progress(
                    statutes=reader_statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia-reader:complete",
                    scanned_history_urls=len(reader_statutes),
                    discovered_history_urls=len(reader_statutes),
                    extra_progress={
                        "codes_total": 1,
                        "codes_completed": 1,
                    },
                )
                self.logger.info(
                    "Mississippi full-corpus Justia reader path: statutes_so_far=%s",
                    len(reader_statutes),
                )
                return reader_statutes[:limit] if limit is not None else reader_statutes

            use_unicourt_fallback = str(
                os.getenv("STATE_SCRAPER_MS_ENABLE_UNICOURT_FALLBACK", "1")
            ).strip().lower() not in {"0", "false", "no", "off"}
            if use_unicourt_fallback:
                unicourt_target_raw = str(
                    os.getenv("STATE_SCRAPER_MS_UNICOURT_TARGET", "50000") or "50000"
                ).strip()
                try:
                    unicourt_target = int(unicourt_target_raw) if unicourt_target_raw else 50000
                except Exception:
                    unicourt_target = 50000
                unicourt_target = max(1000, min(120000, unicourt_target))
                unicourt_statutes = await _run_phase(
                    "unicourt",
                    self._scrape_unicourt_code_sections(
                        code_name=code_name,
                        max_statutes=unicourt_target,
                        checkpoint=checkpoint,
                    ),
                )
                self.logger.info(
                    "Mississippi full-corpus Unicourt phase: statutes=%s target=%s",
                    len(unicourt_statutes),
                    unicourt_target,
                )
                if unicourt_statutes:
                    checkpoint.write_progress(
                        statutes=unicourt_statutes,
                        code_name=code_name,
                        stage_label="mississippi:unicourt:complete",
                        scanned_history_urls=len(unicourt_statutes),
                        discovered_history_urls=len(unicourt_statutes),
                        extra_progress={
                            "codes_total": 1,
                            "codes_completed": 1,
                        },
                    )
                    self.logger.info(
                        "Mississippi full-corpus Unicourt fallback path: statutes_so_far=%s",
                        len(unicourt_statutes),
                    )
                    return unicourt_statutes[:limit] if limit is not None else unicourt_statutes
            else:
                self.logger.info(
                    "Mississippi full-corpus Unicourt fallback disabled by env STATE_SCRAPER_MS_ENABLE_UNICOURT_FALLBACK"
                )

            enable_legacy_generic_full_corpus_fallback = str(
                os.getenv("STATE_SCRAPER_MS_ENABLE_LEGACY_GENERIC_FULL_CORPUS_FALLBACK", "0") or "0"
            ).strip().lower() in {"1", "true", "yes", "on"}
            if not enable_legacy_generic_full_corpus_fallback and not allow_archive_full_corpus:
                checkpoint.write_progress(
                    statutes=seed_statutes,
                    code_name=code_name,
                    stage_label="mississippi:full-corpus:no-recovery-path",
                    scanned_history_urls=len(seed_statutes),
                    discovered_history_urls=len(seed_statutes),
                    extra_progress={
                        "codes_total": 1,
                        "codes_completed": 0,
                    },
                )
                raise RuntimeError(
                    "Mississippi full-corpus recovery paths (justia/wayback/reader/unicourt) produced no statutes"
                )

        archival_kwargs: Dict[str, Any] = {}
        try:
            archival_params = inspect.signature(self._scrape_archived_bill_history).parameters
        except Exception:
            archival_params = {}
        if "seed_statutes" in archival_params:
            archival_kwargs["seed_statutes"] = seed_statutes
        if "checkpoint" in archival_params:
            archival_kwargs["checkpoint"] = checkpoint
        checkpoint.write_progress(
            statutes=seed_statutes,
            code_name=code_name,
            stage_label="mississippi:archive:start",
            scanned_history_urls=len(seed_statutes),
            discovered_history_urls=len(seed_statutes),
            extra_progress={
                "codes_total": 1,
                "codes_completed": 0,
            },
        )
        run_archive_fallback = (
            not self._full_corpus_enabled()
            or max_statutes is not None
            or allow_archive_full_corpus
        )
        if run_archive_fallback:
            archival = await self._scrape_archived_bill_history(
                code_name=code_name,
                max_statutes=limit or 1000000,
                **archival_kwargs,
            )
        else:
            archival = []
            self.logger.info(
                "Mississippi full-corpus archive bill-history fallback disabled "
                "(set STATE_SCRAPER_MS_ENABLE_ARCHIVE_BILL_HISTORY_FULL_CORPUS=1 to re-enable)."
            )
        if archival and (not self._full_corpus_enabled() or max_statutes is not None):
            checkpoint.write_progress(
                statutes=archival,
                code_name=code_name,
                stage_label="mississippi:archive:complete",
                scanned_history_urls=len(archival),
                discovered_history_urls=len(archival),
                extra_progress={
                    "codes_total": 1,
                    "codes_completed": 1,
                },
            )
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            return archival[:limit] if limit is not None else archival

        candidate_urls = [
            code_url,
            "https://www.legislature.ms.gov/legislation/",
            "http://www.legislature.ms.gov/legislation/",
            # Archive fallback candidate when live pathing changes.
            "https://web.archive.org/web/20251017000000/https://www.legislature.ms.gov/legislation/",
        ]
        checkpoint.write_progress(
            statutes=archival,
            code_name=code_name,
            stage_label="mississippi:live-fallback:start",
            scanned_history_urls=len(archival),
            discovered_history_urls=len(archival),
            extra_progress={
                "codes_total": 1,
                "codes_completed": 0,
                "candidates_total": len(candidate_urls),
                "candidates_scanned": 0,
            },
        )

        seen = set()
        for candidate_index, candidate in enumerate(candidate_urls, start=1):
            if candidate in seen:
                continue
            seen.add(candidate)
            checkpoint.write_progress(
                statutes=archival,
                code_name=code_name,
                stage_label="mississippi:live-fallback:candidate",
                scanned_history_urls=len(archival),
                discovered_history_urls=len(archival),
                extra_progress={
                    "codes_total": 1,
                    "codes_completed": 0,
                    "candidates_total": len(candidate_urls),
                    "candidates_scanned": int(candidate_index),
                    "candidate_url": candidate,
                },
            )

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Miss. Code Ann.",
                        max_sections=limit,
                        wait_for_selector="a[href*='statute'], a[href*='code'], a[href*='title'], a[href*='chapter']",
                        timeout=45000,
                    )
                    if statutes:
                        checkpoint.write_progress(
                            statutes=statutes,
                            code_name=code_name,
                            stage_label="mississippi:live-fallback:playwright-complete",
                            scanned_history_urls=len(statutes),
                            discovered_history_urls=len(statutes),
                            extra_progress={
                                "codes_total": 1,
                                "codes_completed": 1,
                                "candidates_total": len(candidate_urls),
                                "candidates_scanned": int(candidate_index),
                            },
                        )
                        return statutes[:limit]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Miss. Code Ann.", max_sections=limit)
            if statutes:
                checkpoint.write_progress(
                    statutes=statutes,
                    code_name=code_name,
                    stage_label="mississippi:live-fallback:generic-complete",
                    scanned_history_urls=len(statutes),
                    discovered_history_urls=len(statutes),
                    extra_progress={
                        "codes_total": 1,
                        "codes_completed": 1,
                        "candidates_total": len(candidate_urls),
                        "candidates_scanned": int(candidate_index),
                    },
                )
                return statutes[:limit]

        if archival:
            checkpoint.write_progress(
                statutes=archival,
                code_name=code_name,
                stage_label="mississippi:complete:archive",
                scanned_history_urls=len(archival),
                discovered_history_urls=len(archival),
                extra_progress={
                    "codes_total": 1,
                    "codes_completed": 1,
                },
            )
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            if limit is not None:
                return archival[:limit]
            return list(archival)
        checkpoint.write_progress(
            statutes=[],
            code_name=code_name,
            stage_label="mississippi:complete:zero",
            scanned_history_urls=0,
            discovered_history_urls=0,
            extra_progress={
                "codes_total": 1,
                "codes_completed": 1,
                "candidates_total": len(candidate_urls),
                "candidates_scanned": len(candidate_urls),
            },
        )
        return []

    async def _discover_unicourt_title_urls(self) -> List[tuple[int, str, str]]:
        """Discover Unicourt Mississippi title pages from the public index."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_html = await self._request_text_direct(self._UNICOURT_ROOT_URL, timeout=35)
        if not root_html:
            return []
        soup = BeautifulSoup(root_html, "html.parser")

        release_to_titles: Dict[str, Dict[int, str]] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            full_url = urljoin(self._UNICOURT_ROOT_URL, href)
            match = self._UNICOURT_TITLE_LINK_RE.search(full_url)
            if not match:
                continue
            release = str(match.group("release") or "").lower()
            try:
                title_number = int(str(match.group("title") or "0"), 10)
            except Exception:
                continue
            if title_number <= 0:
                continue
            release_bucket = release_to_titles.setdefault(release, {})
            release_bucket[title_number] = full_url

        if not release_to_titles:
            return []

        def _release_rank(value: str) -> int:
            try:
                return int(str(value).lstrip("rR"))
            except Exception:
                return -1

        ordered_releases = sorted(
            release_to_titles.items(),
            key=lambda item: (_release_rank(item[0]), len(item[1])),
            reverse=True,
        )

        best_release, best_map = ordered_releases[0]
        ordered_titles = sorted(best_map.items(), key=lambda item: item[0])
        out: List[tuple[int, str, str]] = []
        for title_number, title_url in ordered_titles:
            out.append((title_number, title_url, best_release))
        return out

    async def _scrape_unicourt_code_sections(
        self,
        code_name: str,
        max_statutes: int = 50000,
        checkpoint: Optional["_MississippiCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Mississippi code sections from the public Unicourt mirror."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        target = max(1, int(max_statutes or 1))
        title_rows = await self._discover_unicourt_title_urls()
        if not title_rows:
            return []

        self.logger.info(
            "Mississippi Unicourt discovery: release=%s titles=%s target=%s",
            title_rows[0][2] if title_rows else "",
            len(title_rows),
            target,
        )

        statutes: List[NormalizedStatute] = []
        seen_keys: set[str] = set()

        for title_index, (title_number, title_url, release_name) in enumerate(title_rows, start=1):
            if len(statutes) >= target:
                break
            html = await self._request_text_direct(title_url, timeout=45)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            title_label = f"Title {title_number}"
            section_nodes = list(soup.find_all("h3"))
            discovered_sections = 0

            for section_node in section_nodes:
                heading_text = self._normalize_legal_text(section_node.get_text(" ", strip=True))
                if not heading_text:
                    continue
                section_match = self._UNICOURT_SECTION_HEADING_RE.search(heading_text)
                if not section_match:
                    continue
                section_number = str(section_match.group(1) or "").strip().rstrip(".")
                if not section_number:
                    continue
                discovered_sections += 1
                section_name = re.sub(r"^§+\s*[0-9A-Za-z.\-]+\s*\.?\s*", "", heading_text).strip()
                section_name = section_name or f"Section {section_number}"

                text_parts = [heading_text]
                sibling = section_node.next_sibling
                while sibling is not None:
                    name = getattr(sibling, "name", None)
                    if name == "h3":
                        break
                    if name in {"script", "style", "nav", "header", "footer"}:
                        sibling = sibling.next_sibling
                        continue
                    if name:
                        piece = self._normalize_legal_text(getattr(sibling, "get_text", lambda *_a, **_k: "")(" ", strip=True))
                    else:
                        piece = self._normalize_legal_text(str(sibling).strip())
                    if piece:
                        text_parts.append(piece)
                    sibling = sibling.next_sibling

                full_text = self._normalize_legal_text(" ".join(text_parts))
                if len(full_text) < 120:
                    continue
                statute_id = f"{code_name} § {section_number}"
                statute_key = statute_id.strip().lower()
                if statute_key in seen_keys:
                    continue
                seen_keys.add(statute_key)
                source_fragment = str(section_node.get("id") or "").strip()
                source_url = title_url if not source_fragment else f"{title_url}#{source_fragment}"
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=statute_id,
                        code_name=code_name,
                        title_number=str(title_number),
                        section_number=section_number,
                        section_name=section_name[:200],
                        full_text=full_text[:14000],
                        legal_area=self._identify_legal_area(f"{section_name} {full_text[:1200]}"),
                        source_url=source_url,
                        official_cite=f"Miss. Code Ann. § {section_number}",
                        structured_data={
                            "source_kind": "unicourt_mississippi_code_html",
                            "discovery_method": "unicourt_title_html",
                            "release": release_name,
                            "skip_hydrate": True,
                        },
                    )
                )
                if len(statutes) >= target:
                    break

            if checkpoint is not None:
                checkpoint.maybe_write(
                    statutes,
                    code_name=code_name,
                    stage_label=f"mississippi:unicourt:title:{title_number}",
                    scanned_history_urls=int(len(statutes)),
                    discovered_history_urls=int(len(statutes)),
                )
            if title_index == 1 or title_index % 5 == 0 or title_index == len(title_rows):
                self.logger.info(
                    "Mississippi Unicourt crawl: title=%s/%s discovered_sections=%s statutes_so_far=%s",
                    title_index,
                    len(title_rows),
                    discovered_sections,
                    len(statutes),
                )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="mississippi:unicourt:title-scan",
                extra={
                    "codes_total": 1,
                    "codes_completed": 0,
                    "titles_scanned": int(title_index),
                    "discovered_titles": int(len(title_rows)),
                    "sections_scanned": int(len(statutes)),
                    "discovered_sections": int(len(statutes)),
                    "unicourt_release": str(title_rows[0][2] if title_rows else ""),
                },
            )

        if statutes:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="mississippi:unicourt:complete",
                force=True,
                extra={
                    "codes_total": 1,
                    "codes_completed": 1,
                    "titles_scanned": int(len(title_rows)),
                    "discovered_titles": int(len(title_rows)),
                    "sections_scanned": int(len(statutes)),
                    "discovered_sections": int(len(statutes)),
                    "unicourt_release": str(title_rows[0][2] if title_rows else ""),
                },
            )
        return statutes[:target]

    def _extract_ms_section_number_from_justia_url(self, url: str) -> str:
        value = str(url or "")
        match = re.search(
            r"/section-(\d+)-(\d+)-([0-9a-z_]+)",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        title_raw, chapter_raw, section_raw = match.groups()
        section_token = str(section_raw or "").strip().lower().replace("_", ".")
        section_token = section_token.lstrip("0") or "0"
        try:
            title_part = str(int(title_raw))
        except Exception:
            title_part = str(title_raw).lstrip("0") or "0"
        try:
            chapter_part = str(int(chapter_raw))
        except Exception:
            chapter_part = str(chapter_raw).lstrip("0") or "0"
        return f"{title_part}-{chapter_part}-{section_token}"

    async def _scrape_justia_code_sections(
        self,
        code_name: str,
        max_statutes: int = 30000,
        checkpoint: Optional["_MississippiCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        target = max(1, int(max_statutes or 1))
        title_urls: List[str] = []
        chapter_urls: List[str] = []
        section_urls: List[str] = []

        seen_title_urls: set[str] = set()
        seen_chapter_urls: set[str] = set()
        seen_section_urls: set[str] = set()

        def _add_title(url: str) -> None:
            value = str(url or "").strip()
            if not value or value in seen_title_urls:
                return
            seen_title_urls.add(value)
            title_urls.append(value)

        def _add_chapter(url: str) -> None:
            value = str(url or "").strip()
            if not value or value in seen_chapter_urls:
                return
            seen_chapter_urls.add(value)
            chapter_urls.append(value)

        def _add_section(url: str) -> None:
            value = str(url or "").strip()
            if not value or value in seen_section_urls:
                return
            if not self._JUSTIA_SECTION_URL_RE.search(value):
                return
            seen_section_urls.add(value)
            section_urls.append(value)

        for index_url in self._JUSTIA_INDEX_URLS:
            html = await self._request_text_direct(index_url, timeout=30)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                full_url = urljoin(index_url, href)
                lower = full_url.lower()
                if "/codes/mississippi/" not in lower:
                    continue
                if "/title-" in lower and "/chapter-" not in lower:
                    _add_title(full_url)
                if "/chapter-" in lower and "/section-" not in lower:
                    _add_chapter(full_url)
                if "/section-" in lower:
                    _add_section(full_url)

        if not title_urls and not chapter_urls and not section_urls:
            return []

        for title_url in list(title_urls):
            html = await self._request_text_direct(title_url, timeout=30)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                full_url = urljoin(title_url, href)
                lower = full_url.lower()
                if "/codes/mississippi/" not in lower:
                    continue
                if "/chapter-" in lower and "/section-" not in lower:
                    _add_chapter(full_url)
                if "/section-" in lower:
                    _add_section(full_url)

        for chapter_url in list(chapter_urls):
            if len(section_urls) >= target * 3:
                break
            html = await self._request_text_direct(chapter_url, timeout=30)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                full_url = urljoin(chapter_url, href)
                _add_section(full_url)

        if not section_urls:
            return []

        html_scan_cap_default = max(target * 3, 1500)
        if self._full_corpus_enabled():
            html_scan_cap_default = max(6000, min(30000, html_scan_cap_default))
        html_scan_cap_raw = str(
            os.getenv("STATE_SCRAPER_MS_JUSTIA_SECTION_SCAN_CAP", str(html_scan_cap_default))
            or str(html_scan_cap_default)
        ).strip()
        try:
            section_scan_cap = int(html_scan_cap_raw) if html_scan_cap_raw else html_scan_cap_default
        except Exception:
            section_scan_cap = html_scan_cap_default
        section_scan_cap = max(500, min(120000, section_scan_cap))
        if len(section_urls) > section_scan_cap:
            section_urls = list(section_urls[:section_scan_cap])

        self.logger.info(
            "Mississippi Justia crawl: discovered_titles=%s discovered_chapters=%s discovered_sections=%s scan_cap=%s",
            len(title_urls),
            len(chapter_urls),
            len(section_urls),
            section_scan_cap,
        )
        self._write_partial_checkpoint(
            [],
            code_name=code_name,
            stage_label="mississippi:justia:section-discovery",
            extra={
                "codes_total": 1,
                "codes_completed": 0,
                "discovered_titles": int(len(title_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "discovered_sections": int(len(section_urls)),
                "sections_scanned": 0,
            },
        )

        statutes: List[NormalizedStatute] = []
        seen_statute_keys: set[str] = set()
        section_concurrency = max(
            1,
            int(os.getenv("STATE_SCRAPER_MS_JUSTIA_SECTION_CONCURRENCY", "8") or "8"),
        )
        section_sem = asyncio.Semaphore(section_concurrency)

        async def _fetch_section(section_url: str) -> Optional[NormalizedStatute]:
            async with section_sem:
                html = await self._request_text_direct(section_url, timeout=35)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            content_node = (
                soup.select_one("div#codes-content")
                or soup.select_one("div[itemprop='articleBody']")
                or soup.select_one("article")
                or soup.select_one("main")
                or soup.body
            )
            if content_node is None:
                return None
            text = self._normalize_legal_text(content_node.get_text(" ", strip=True))
            if len(text) < 140:
                return None
            section_number = self._extract_ms_section_number_from_justia_url(section_url)
            if not section_number:
                section_number = self._extract_section_number(text) or ""
            if not section_number:
                return None
            heading = ""
            heading_node = soup.find(["h1", "h2"])
            if heading_node is not None:
                heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))
            section_name = heading or f"Section {section_number}"
            return NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name[:200],
                full_text=text[:14000],
                legal_area=self._identify_legal_area(f"{section_name} {text[:800]}"),
                source_url=section_url,
                official_cite=f"Miss. Code Ann. § {section_number}",
                structured_data={
                    "source_kind": "justia_mississippi_code_html",
                    "discovery_method": "justia_title_chapter_section",
                    "skip_hydrate": True,
                },
            )

        tasks = [asyncio.create_task(_fetch_section(url)) for url in section_urls]
        scanned = 0
        for task in asyncio.as_completed(tasks):
            scanned += 1
            statute = await task
            if statute is None:
                if (
                    scanned == 1
                    or scanned % 500 == 0
                    or scanned == len(section_urls)
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="mississippi:justia:section-scan",
                        extra={
                            "codes_total": 1,
                            "codes_completed": 0,
                            "discovered_titles": int(len(title_urls)),
                            "discovered_chapters": int(len(chapter_urls)),
                            "discovered_sections": int(len(section_urls)),
                            "sections_scanned": int(scanned),
                        },
                    )
                continue
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_statute_keys:
                continue
            if statute_key:
                seen_statute_keys.add(statute_key)
            statutes.append(statute)
            if len(statutes) == 1 or len(statutes) % 100 == 0:
                self.logger.info(
                    "Mississippi Justia crawl: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned,
                    len(section_urls),
                    len(statutes),
                )
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia:section-scan",
                    extra={
                        "codes_total": 1,
                        "codes_completed": 0,
                        "discovered_titles": int(len(title_urls)),
                        "discovered_chapters": int(len(chapter_urls)),
                        "discovered_sections": int(len(section_urls)),
                        "sections_scanned": int(scanned),
                    },
                )
            if len(statutes) >= target:
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                break
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="mississippi:justia:complete",
            force=True,
            extra={
                "codes_total": 1,
                "codes_completed": 1 if statutes else 0,
                "discovered_titles": int(len(title_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "discovered_sections": int(len(section_urls)),
                "sections_scanned": int(min(scanned, len(section_urls))),
            },
        )
        if checkpoint is not None:
            checkpoint.write_progress(
                statutes=statutes,
                code_name=code_name,
                stage_label="mississippi:justia:complete",
                scanned_history_urls=len(statutes),
                discovered_history_urls=len(statutes),
                extra_progress={
                    "codes_total": 1,
                    "codes_completed": 1 if statutes else 0,
                },
            )
        return statutes[:target]

    def _extract_original_justia_url_from_wayback(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        lower = value.lower()
        if "web.archive.org" not in lower or "/web/" not in lower:
            return value
        _, _, tail = value.partition("/web/")
        if not tail:
            return value
        _, sep, remainder = tail.partition("/")
        if not sep or not remainder:
            return value
        remainder = remainder.strip()
        if remainder.startswith("http://") or remainder.startswith("https://"):
            return remainder
        return value

    def _is_justia_blocked_payload(self, html: str) -> bool:
        hay = str(html or "")
        if not hay:
            return True
        lower = hay.lower()
        if "law.justia.com" not in lower:
            return False
        return bool(self._JUSTIA_BLOCKED_TEXT_RE.search(hay))

    async def _request_text_direct_with_retries(
        self,
        url: str,
        *,
        timeout: int = 30,
        attempts: int = 3,
    ) -> str:
        attempts_n = max(1, int(attempts or 1))
        for attempt in range(attempts_n):
            text = await self._request_text_direct(url, timeout=timeout)
            if text:
                return text
            if attempt + 1 < attempts_n:
                await asyncio.sleep(min(1.5, 0.35 * float(attempt + 1)))
        return ""

    async def _discover_justia_wayback_snapshot_urls(
        self,
        original_url: str,
        *,
        max_snapshots: int = 2,
    ) -> List[str]:
        params = [
            ("url", str(original_url or "").strip()),
            ("output", "json"),
            ("fl", "timestamp,original,statuscode,mimetype"),
            ("filter", "statuscode:200"),
            ("filter", "mimetype:text/html"),
            ("limit", "24"),
        ]
        cdx_url = f"{self._JUSTIA_WAYBACK_CDX_ENDPOINT}?{urlencode(params, doseq=True)}"
        payload = await self._request_text_direct_with_retries(
            cdx_url,
            timeout=35,
            attempts=3,
        )
        if not payload:
            return []
        try:
            rows = json.loads(payload)
        except Exception:
            return []
        if not isinstance(rows, list):
            return []

        snapshots: List[str] = []
        seen = set()
        for row in reversed(rows[1:] if rows else []):
            if not isinstance(row, list) or len(row) < 2:
                continue
            timestamp = str(row[0] or "").strip()
            archived_original = str(row[1] or "").strip()
            if not timestamp or not archived_original:
                continue
            snapshot_url = f"{self._JUSTIA_WAYBACK_FETCH_ROOT}{timestamp}/{archived_original}"
            if snapshot_url in seen:
                continue
            seen.add(snapshot_url)
            snapshots.append(snapshot_url)
            if len(snapshots) >= max(1, int(max_snapshots or 1)):
                break
        return snapshots

    async def _scrape_justia_wayback_code_sections(
        self,
        code_name: str,
        max_statutes: int = 30000,
    ) -> List[NormalizedStatute]:
        target = max(1, int(max_statutes or 1))
        snapshot_indexes: List[str] = []
        seen_snapshot_indexes: set[str] = set()
        for index_url in self._JUSTIA_INDEX_URLS:
            discovered = await self._discover_justia_wayback_snapshot_urls(
                index_url,
                max_snapshots=8,
            )
            for snapshot_url in discovered:
                value = str(snapshot_url or "").strip()
                if not value or value in seen_snapshot_indexes:
                    continue
                seen_snapshot_indexes.add(value)
                snapshot_indexes.append(value)
            if not discovered:
                for fallback_snapshot_url in self._JUSTIA_WAYBACK_INDEX_FALLBACKS.get(index_url, ()):
                    value = str(fallback_snapshot_url or "").strip()
                    if not value or value in seen_snapshot_indexes:
                        continue
                    seen_snapshot_indexes.add(value)
                    snapshot_indexes.append(value)

        if not snapshot_indexes:
            return []

        title_fetch_urls: List[str] = []
        chapter_fetch_urls: List[str] = []
        section_fetch_urls: List[str] = []
        title_original_url_by_fetch_url: Dict[str, str] = {}
        chapter_original_url_by_fetch_url: Dict[str, str] = {}
        section_original_url_by_fetch_url: Dict[str, str] = {}

        seen_title_original_urls: set[str] = set()
        seen_chapter_original_urls: set[str] = set()
        seen_section_original_urls: set[str] = set()
        seen_section_fetch_urls: set[str] = set()

        def _classify_link(base_url: str, href: str) -> tuple[str, str]:
            full_url = urljoin(str(base_url or ""), str(href or "").strip()).split("#", 1)[0].strip()
            if not full_url:
                return "", ""
            if "/web/" in full_url and "*/" in full_url:
                return "", ""
            original_url = self._extract_original_justia_url_from_wayback(full_url).split("#", 1)[0].strip()
            if not original_url:
                return "", ""
            if "/codes/mississippi/" not in original_url.lower():
                return "", ""
            return full_url, original_url

        def _add_title(fetch_url: str, original_url: str) -> None:
            original_value = str(original_url or "").strip()
            fetch_value = str(fetch_url or "").strip()
            if not original_value or original_value in seen_title_original_urls:
                return
            seen_title_original_urls.add(original_value)
            if not fetch_value:
                return
            title_fetch_urls.append(fetch_value)
            title_original_url_by_fetch_url[fetch_value] = original_value

        def _add_chapter(fetch_url: str, original_url: str) -> None:
            original_value = str(original_url or "").strip()
            fetch_value = str(fetch_url or "").strip()
            if not original_value or original_value in seen_chapter_original_urls:
                return
            seen_chapter_original_urls.add(original_value)
            if not fetch_value:
                return
            chapter_fetch_urls.append(fetch_value)
            chapter_original_url_by_fetch_url[fetch_value] = original_value

        def _add_section(fetch_url: str, original_url: str) -> None:
            original_value = str(original_url or "").strip()
            fetch_value = str(fetch_url or "").strip()
            if not original_value or not fetch_value:
                return
            if not self._JUSTIA_SECTION_URL_RE.search(original_value):
                return
            if original_value in seen_section_original_urls:
                return
            seen_section_original_urls.add(original_value)
            if fetch_value in seen_section_fetch_urls:
                return
            seen_section_fetch_urls.add(fetch_value)
            section_fetch_urls.append(fetch_value)
            section_original_url_by_fetch_url[fetch_value] = original_value

        for snapshot_index_url in snapshot_indexes:
            html = await self._request_text_direct_with_retries(
                snapshot_index_url,
                timeout=45,
                attempts=3,
            )
            if not html or self._is_justia_blocked_payload(html):
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                fetch_url, original_url = _classify_link(snapshot_index_url, str(anchor.get("href") or ""))
                if not fetch_url or not original_url:
                    continue
                lower = original_url.lower()
                if self._JUSTIA_SECTION_URL_RE.search(original_url):
                    _add_section(fetch_url, original_url)
                elif self._JUSTIA_CHAPTER_URL_RE.search(original_url):
                    _add_chapter(fetch_url, original_url)
                elif self._JUSTIA_TITLE_URL_RE.search(original_url):
                    _add_title(fetch_url, original_url)
                elif "/title-" in lower and "/section-" not in lower and "/chapter-" not in lower:
                    _add_title(fetch_url, original_url)

        if not title_fetch_urls and not chapter_fetch_urls and not section_fetch_urls:
            return []

        wayback_scan_cap_default = max(target * 3, 1500)
        if self._full_corpus_enabled():
            wayback_scan_cap_default = max(12000, min(45000, wayback_scan_cap_default))
        wayback_scan_cap_raw = str(
            os.getenv("STATE_SCRAPER_MS_WAYBACK_SECTION_SCAN_CAP", str(wayback_scan_cap_default))
            or str(wayback_scan_cap_default)
        ).strip()
        try:
            section_scan_cap = int(wayback_scan_cap_raw) if wayback_scan_cap_raw else wayback_scan_cap_default
        except Exception:
            section_scan_cap = wayback_scan_cap_default
        section_scan_cap = max(500, min(120000, section_scan_cap))
        page_snapshot_candidates_cache: Dict[str, List[str]] = {}

        def _wayback_raw_variant(snapshot_url: str) -> str:
            value = str(snapshot_url or "").strip()
            if not value or "/web/" not in value:
                return ""
            prefix, _, tail = value.partition("/web/")
            if not tail:
                return ""
            timestamp, sep, remainder = tail.partition("/")
            if not sep or not timestamp or not remainder:
                return ""
            if timestamp.endswith("id_"):
                return ""
            return f"{prefix}/web/{timestamp}id_/{remainder}"

        async def _fetch_wayback_html_with_snapshot_fallback(
            fetch_url: str,
            original_url: str,
            *,
            timeout: int = 45,
            attempts: int = 3,
            max_snapshots: int = 4,
        ) -> tuple[str, str]:
            fetch_value = str(fetch_url or "").strip()
            original_value = str(original_url or "").strip() or fetch_value
            candidate_fetch_urls: List[str] = [fetch_value]
            seen_candidates: set[str] = {fetch_value}

            if original_value:
                cached_candidates = page_snapshot_candidates_cache.get(original_value)
                if cached_candidates is None:
                    discovered_snapshot_urls = await self._discover_justia_wayback_snapshot_urls(
                        original_value,
                        max_snapshots=max(2, int(max_snapshots or 2)),
                    )
                    expanded_snapshot_urls: List[str] = []
                    seen_snapshot_candidates: set[str] = set()
                    for snapshot_url in discovered_snapshot_urls:
                        snapshot_value = str(snapshot_url or "").strip()
                        if not snapshot_value:
                            continue
                        if snapshot_value not in seen_snapshot_candidates:
                            seen_snapshot_candidates.add(snapshot_value)
                            expanded_snapshot_urls.append(snapshot_value)
                        raw_variant = _wayback_raw_variant(snapshot_value)
                        if raw_variant and raw_variant not in seen_snapshot_candidates:
                            seen_snapshot_candidates.add(raw_variant)
                            expanded_snapshot_urls.append(raw_variant)
                    cached_candidates = expanded_snapshot_urls
                    page_snapshot_candidates_cache[original_value] = cached_candidates
                for snapshot_candidate in cached_candidates:
                    candidate_value = str(snapshot_candidate or "").strip()
                    if not candidate_value or candidate_value in seen_candidates:
                        continue
                    seen_candidates.add(candidate_value)
                    candidate_fetch_urls.append(candidate_value)

            for candidate_fetch_url in candidate_fetch_urls:
                html = await self._request_text_direct_with_retries(
                    candidate_fetch_url,
                    timeout=timeout,
                    attempts=attempts,
                )
                if not html or self._is_justia_blocked_payload(html):
                    continue
                return html, candidate_fetch_url
            return "", fetch_value

        for title_fetch_url in list(title_fetch_urls):
            title_original_url = (
                title_original_url_by_fetch_url.get(title_fetch_url)
                or self._extract_original_justia_url_from_wayback(title_fetch_url)
            )
            html, resolved_title_fetch_url = await _fetch_wayback_html_with_snapshot_fallback(
                title_fetch_url,
                title_original_url,
                timeout=45,
                attempts=3,
                max_snapshots=4,
            )
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                fetch_url, original_url = _classify_link(resolved_title_fetch_url, str(anchor.get("href") or ""))
                if not fetch_url or not original_url:
                    continue
                if self._JUSTIA_SECTION_URL_RE.search(original_url):
                    _add_section(fetch_url, original_url)
                elif self._JUSTIA_CHAPTER_URL_RE.search(original_url):
                    _add_chapter(fetch_url, original_url)

        for chapter_fetch_url in list(chapter_fetch_urls):
            if len(section_fetch_urls) >= section_scan_cap:
                break
            chapter_original_url = (
                chapter_original_url_by_fetch_url.get(chapter_fetch_url)
                or self._extract_original_justia_url_from_wayback(chapter_fetch_url)
            )
            html, resolved_chapter_fetch_url = await _fetch_wayback_html_with_snapshot_fallback(
                chapter_fetch_url,
                chapter_original_url,
                timeout=45,
                attempts=3,
                max_snapshots=4,
            )
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                fetch_url, original_url = _classify_link(resolved_chapter_fetch_url, str(anchor.get("href") or ""))
                if not fetch_url or not original_url:
                    continue
                _add_section(fetch_url, original_url)

        if len(section_fetch_urls) > section_scan_cap:
            section_fetch_urls = list(section_fetch_urls[:section_scan_cap])
            section_original_url_by_fetch_url = {
                fetch_url: section_original_url_by_fetch_url.get(fetch_url, fetch_url)
                for fetch_url in section_fetch_urls
            }

        if not section_fetch_urls:
            return []

        self.logger.info(
            "Mississippi Justia Wayback crawl: discovered_titles=%s discovered_chapters=%s discovered_sections=%s scan_cap=%s",
            len(title_fetch_urls),
            len(chapter_fetch_urls),
            len(section_fetch_urls),
            section_scan_cap,
        )
        self._write_partial_checkpoint(
            [],
            code_name=code_name,
            stage_label="mississippi:justia-wayback:section-discovery",
            extra={
                "codes_total": 1,
                "codes_completed": 0,
                "discovered_titles": int(len(title_fetch_urls)),
                "discovered_chapters": int(len(chapter_fetch_urls)),
                "discovered_sections": int(len(section_fetch_urls)),
                "sections_scanned": 0,
            },
        )

        statutes: List[NormalizedStatute] = []
        seen_statute_keys: set[str] = set()
        wayback_concurrency_default = str(
            os.getenv(
                "STATE_SCRAPER_MS_WAYBACK_SECTION_CONCURRENCY",
                os.getenv(
                    "STATE_SCRAPER_MS_JUSTIA_SECTION_CONCURRENCY",
                    "12" if self._full_corpus_enabled() else "4",
                ),
            )
            or ("12" if self._full_corpus_enabled() else "4")
        )
        section_concurrency = max(
            1,
            int(wayback_concurrency_default),
        )
        section_sem = asyncio.Semaphore(section_concurrency)

        async def _fetch_section(fetch_url: str) -> Optional[NormalizedStatute]:
            source_url = section_original_url_by_fetch_url.get(fetch_url) or fetch_url
            async with section_sem:
                html, resolved_archive_url = await _fetch_wayback_html_with_snapshot_fallback(
                    fetch_url,
                    source_url,
                    timeout=45,
                    attempts=3,
                    max_snapshots=3,
                )

            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            content_node = (
                soup.select_one("div#codes-content")
                or soup.select_one("div[itemprop='articleBody']")
                or soup.select_one("article")
                or soup.select_one("main")
                or soup.body
            )
            if content_node is None:
                return None
            text = self._normalize_legal_text(content_node.get_text(" ", strip=True))
            if len(text) < 140:
                return None
            section_number = self._extract_ms_section_number_from_justia_url(source_url)
            if not section_number:
                section_number = self._extract_section_number(text) or ""
            if not section_number:
                return None
            heading = ""
            heading_node = soup.find(["h1", "h2"])
            if heading_node is not None:
                heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))
            section_name = heading or f"Section {section_number}"
            return NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name[:200],
                full_text=text[:14000],
                legal_area=self._identify_legal_area(f"{section_name} {text[:800]}"),
                source_url=source_url,
                official_cite=f"Miss. Code Ann. § {section_number}",
                structured_data={
                    "source_kind": "wayback_justia_mississippi_code_html",
                    "discovery_method": "justia_wayback_title_chapter_section",
                    "archive_url": resolved_archive_url,
                    "skip_hydrate": True,
                },
            )

        tasks = [asyncio.create_task(_fetch_section(url)) for url in section_fetch_urls]
        scanned = 0
        for task in asyncio.as_completed(tasks):
            scanned += 1
            statute = await task
            if statute is None:
                if (
                    scanned == 1
                    or scanned % 400 == 0
                    or scanned == len(section_fetch_urls)
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="mississippi:justia-wayback:section-scan",
                        extra={
                            "codes_total": 1,
                            "codes_completed": 0,
                            "discovered_titles": int(len(title_fetch_urls)),
                            "discovered_chapters": int(len(chapter_fetch_urls)),
                            "discovered_sections": int(len(section_fetch_urls)),
                            "sections_scanned": int(scanned),
                        },
                    )
                continue
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_statute_keys:
                continue
            if statute_key:
                seen_statute_keys.add(statute_key)
            statutes.append(statute)
            if (
                len(statutes) == 1
                or len(statutes) % 100 == 0
                or scanned == len(section_fetch_urls)
            ):
                self.logger.info(
                    "Mississippi Justia Wayback crawl: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned,
                    len(section_fetch_urls),
                    len(statutes),
                )
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia-wayback:section-scan",
                    extra={
                        "codes_total": 1,
                        "codes_completed": 0,
                        "discovered_titles": int(len(title_fetch_urls)),
                        "discovered_chapters": int(len(chapter_fetch_urls)),
                        "discovered_sections": int(len(section_fetch_urls)),
                        "sections_scanned": int(scanned),
                    },
                )
            if len(statutes) >= target:
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                break
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="mississippi:justia-wayback:complete",
            force=True,
            extra={
                "codes_total": 1,
                "codes_completed": 1 if statutes else 0,
                "discovered_titles": int(len(title_fetch_urls)),
                "discovered_chapters": int(len(chapter_fetch_urls)),
                "discovered_sections": int(len(section_fetch_urls)),
                "sections_scanned": int(min(scanned, len(section_fetch_urls))),
            },
        )
        return statutes[:target]

    async def _scrape_jina_justia_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            (
                "97-3-7",
                "https://law.justia.com/codes/mississippi/2024/title-97/chapter-3/section-97-3-7/",
            ),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_page in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{source_page}"
            text = await self._request_text_direct(reader_url, timeout=30)
            text = self._clean_jina_markdown(text)
            if len(text) < 280:
                continue
            title_match = re.search(rf"Mississippi Code §\s*{re.escape(section_number)}\s*\(2024\)\s*-\s*(.+)", text)
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
                    source_url=source_page,
                    official_cite=f"Miss. Code Ann. § {section_number}",
                    structured_data={
                        "source_kind": "jina_reader_justia_mississippi_code",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_jina_justia_code_sections(
        self,
        code_name: str,
        max_statutes: int = 30000,
        checkpoint: Optional["_MississippiCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        target = max(1, int(max_statutes or 1))
        title_urls: List[str] = []
        chapter_urls: List[str] = []
        section_urls: List[str] = []
        seen_title_urls: set[str] = set()
        seen_chapter_urls: set[str] = set()
        seen_section_urls: set[str] = set()

        def _add_url(bucket: List[str], seen: set[str], url: str) -> None:
            value = str(url or "").strip()
            if not value:
                return
            value = self._normalize_justia_corpus_url(value)
            if not value or value in seen:
                return
            seen.add(value)
            bucket.append(value)

        def _classify_reader_links(markdown: str) -> None:
            for link in self._extract_justia_links_from_reader_markdown(markdown):
                lower = link.lower()
                if self._JUSTIA_SECTION_URL_RE.search(link):
                    _add_url(section_urls, seen_section_urls, link)
                elif self._JUSTIA_CHAPTER_URL_RE.search(link):
                    _add_url(chapter_urls, seen_chapter_urls, link)
                elif self._JUSTIA_TITLE_URL_RE.search(link):
                    _add_url(title_urls, seen_title_urls, link)
                elif "/title-" in lower and "/section-" not in lower and "/chapter-" not in lower:
                    _add_url(title_urls, seen_title_urls, link)

        for index_url in self._JUSTIA_INDEX_URLS:
            markdown = await self._fetch_justia_reader_markdown(index_url, timeout=40)
            if not markdown:
                continue
            _classify_reader_links(markdown)

        for title_url in list(title_urls):
            if len(section_urls) >= target * 3:
                break
            markdown = await self._fetch_justia_reader_markdown(title_url, timeout=40)
            if not markdown:
                continue
            _classify_reader_links(markdown)

        for chapter_url in list(chapter_urls):
            if len(section_urls) >= target * 3:
                break
            markdown = await self._fetch_justia_reader_markdown(chapter_url, timeout=40)
            if not markdown:
                continue
            _classify_reader_links(markdown)

        if not section_urls:
            return []

        reader_scan_cap_default = max(target * 3, 1500)
        if self._full_corpus_enabled():
            reader_scan_cap_default = max(6000, min(30000, reader_scan_cap_default))
        reader_scan_cap_raw = str(
            os.getenv("STATE_SCRAPER_MS_READER_SECTION_SCAN_CAP", str(reader_scan_cap_default))
            or str(reader_scan_cap_default)
        ).strip()
        try:
            reader_scan_cap = int(reader_scan_cap_raw) if reader_scan_cap_raw else reader_scan_cap_default
        except Exception:
            reader_scan_cap = reader_scan_cap_default
        reader_scan_cap = max(500, min(120000, reader_scan_cap))
        if len(section_urls) > reader_scan_cap:
            section_urls = list(section_urls[:reader_scan_cap])

        self.logger.info(
            "Mississippi Justia reader crawl: discovered_titles=%s discovered_chapters=%s discovered_sections=%s scan_cap=%s",
            len(title_urls),
            len(chapter_urls),
            len(section_urls),
            reader_scan_cap,
        )
        self._write_partial_checkpoint(
            [],
            code_name=code_name,
            stage_label="mississippi:justia-reader:section-discovery",
            extra={
                "codes_total": 1,
                "codes_completed": 0,
                "discovered_titles": int(len(title_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "discovered_sections": int(len(section_urls)),
                "sections_scanned": 0,
            },
        )

        statutes: List[NormalizedStatute] = []
        seen_keys: set[str] = set()
        section_concurrency = max(
            1,
            int(
                os.getenv(
                    "STATE_SCRAPER_MS_READER_SECTION_CONCURRENCY",
                    "10" if self._full_corpus_enabled() else "6",
                )
                or ("10" if self._full_corpus_enabled() else "6")
            ),
        )
        section_sem = asyncio.Semaphore(section_concurrency)

        async def _fetch_reader_statute(section_url: str) -> Optional[NormalizedStatute]:
            async with section_sem:
                markdown = await self._fetch_justia_reader_markdown(section_url, timeout=45)
            if not markdown:
                return None
            cleaned = self._clean_jina_markdown(markdown)
            if len(cleaned) < 220:
                return None
            section_number = self._extract_ms_section_number_from_justia_url(section_url)
            if not section_number:
                section_number = self._extract_ms_reader_section_number(cleaned) or self._extract_section_number(cleaned) or ""
            if not section_number:
                return None
            section_name = self._extract_ms_reader_section_name(cleaned, section_number)
            return NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                section_number=section_number,
                section_name=section_name[:200],
                full_text=cleaned[:14000],
                legal_area=self._identify_legal_area(f"{section_name} {cleaned[:900]}"),
                source_url=section_url,
                official_cite=f"Miss. Code Ann. § {section_number}",
                structured_data={
                    "source_kind": "jina_reader_justia_mississippi_code",
                    "discovery_method": "justia_reader_title_chapter_section",
                    "reader_url": f"https://r.jina.ai/http://{section_url}",
                    "skip_hydrate": True,
                },
            )

        tasks = [asyncio.create_task(_fetch_reader_statute(url)) for url in section_urls]
        scanned = 0
        for task in asyncio.as_completed(tasks):
            scanned += 1
            statute = await task
            if statute is None:
                if (
                    scanned == 1
                    or scanned % 500 == 0
                    or scanned == len(section_urls)
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="mississippi:justia-reader:section-scan",
                        extra={
                            "codes_total": 1,
                            "codes_completed": 0,
                            "discovered_titles": int(len(title_urls)),
                            "discovered_chapters": int(len(chapter_urls)),
                            "discovered_sections": int(len(section_urls)),
                            "sections_scanned": int(scanned),
                        },
                    )
                continue
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_keys:
                continue
            if statute_key:
                seen_keys.add(statute_key)
            statutes.append(statute)
            if len(statutes) == 1 or len(statutes) % 100 == 0:
                self.logger.info(
                    "Mississippi Justia reader crawl: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned,
                    len(section_urls),
                    len(statutes),
                )
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="mississippi:justia-reader:section-scan",
                    extra={
                        "codes_total": 1,
                        "codes_completed": 0,
                        "discovered_titles": int(len(title_urls)),
                        "discovered_chapters": int(len(chapter_urls)),
                        "discovered_sections": int(len(section_urls)),
                        "sections_scanned": int(scanned),
                    },
                )
            if len(statutes) >= target:
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                break
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="mississippi:justia-reader:complete",
            force=True,
            extra={
                "codes_total": 1,
                "codes_completed": 1 if statutes else 0,
                "discovered_titles": int(len(title_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "discovered_sections": int(len(section_urls)),
                "sections_scanned": int(min(scanned, len(section_urls))),
            },
        )
        if checkpoint is not None:
            checkpoint.write_progress(
                statutes=statutes,
                code_name=code_name,
                stage_label="mississippi:justia-reader:complete",
                scanned_history_urls=len(statutes),
                discovered_history_urls=len(statutes),
                extra_progress={
                    "codes_total": 1,
                    "codes_completed": 1 if statutes else 0,
                },
            )
        return statutes[:target]

    async def _fetch_justia_reader_markdown(self, url: str, *, timeout: int = 40) -> str:
        source_url = str(url or "").strip()
        if not source_url:
            return ""
        reader_url = f"https://r.jina.ai/http://{source_url}"
        text = await self._request_text_direct(reader_url, timeout=max(5, int(timeout or 40)))
        return str(text or "")

    def _extract_justia_links_from_reader_markdown(self, markdown: str) -> List[str]:
        text = str(markdown or "")
        if not text:
            return []
        out: List[str] = []
        seen: set[str] = set()
        for pattern in (self._JUSTIA_READER_LINK_RE, self._JUSTIA_READER_RAW_LINK_RE):
            for match in pattern.finditer(text):
                try:
                    value = match.group(1) if match.lastindex else match.group(0)
                except Exception:
                    value = match.group(0)
                candidate = self._normalize_justia_corpus_url(str(value or "").strip().rstrip(".,;"))
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                out.append(candidate)
        return out

    def _normalize_justia_corpus_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        value = value.split("#", 1)[0].strip()
        if "/codes/mississippi/" not in value.lower():
            return ""
        if not value.startswith("http://") and not value.startswith("https://"):
            return ""
        if value.endswith("/") and "/section-" not in value:
            return value
        return value.rstrip("/") + "/"

    def _extract_ms_reader_section_number(self, text: str) -> str:
        value = str(text or "")
        patterns = [
            r"Mississippi Code §\s*([0-9]+-[0-9]+-[0-9A-Za-z._-]+)",
            r"Section\s+([0-9]+-[0-9]+-[0-9A-Za-z._-]+)",
            r"§\s*([0-9]+-[0-9]+-[0-9A-Za-z._-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return str(match.group(1) or "").strip().replace("_", ".")
        return ""

    def _extract_ms_reader_section_name(self, text: str, section_number: str) -> str:
        value = str(text or "")
        patterns = [
            rf"Mississippi Code §\s*{re.escape(section_number)}\s*\(\d{{4}}\)\s*-\s*(.+?)(?:\s*::|\n|$)",
            rf"Section\s+{re.escape(section_number)}\s*-\s*(.+?)(?:\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return self._normalize_legal_text(match.group(1))[:200]
        return f"Section {section_number}"

    def _clean_jina_markdown(self, text: str) -> str:
        value = str(text or "")
        marker = "Markdown Content:"
        if marker in value:
            value = value.split(marker, 1)[-1]
        value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", value)
        value = re.sub(r"#+\s*", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    async def _request_text_direct(self, url: str, timeout: int = 30) -> str:
        target_url = str(url or "").strip()
        if not target_url:
            return ""

        def _request() -> str:
            try:
                req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            direct_text = await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
            if direct_text:
                return direct_text
        except Exception:
            pass

        insecure_text = await self._request_text_with_insecure_tls_retry(
            url=target_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=max(5, int(timeout or 30)),
        )
        if insecure_text:
            return insecure_text

        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                target_url,
                timeout_seconds=max(5, int(timeout or 30)),
            )
            if payload:
                return payload.decode("utf-8", errors="replace")
        except Exception:
            pass
        return ""

    async def _scrape_archived_bill_history(
        self,
        code_name: str,
        max_statutes: int,
        *,
        seed_statutes: Optional[List[NormalizedStatute]] = None,
        checkpoint: Optional["_MississippiCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        archive_target_cap = max(
            100,
            int(
                os.getenv("STATE_SCRAPER_MS_ARCHIVE_TARGET", "25000")
                or "25000"
            ),
        )
        if self._full_corpus_enabled():
            max_statutes = min(max(1, int(max_statutes)), archive_target_cap)
        else:
            max_statutes = max(1, int(max_statutes))
        headers = {"User-Agent": "Mozilla/5.0"}
        bounded_scrape = max_statutes <= 10
        if bounded_scrape:
            headers["X-Bounded-Scrape"] = "1"
        statutes: List[NormalizedStatute] = []
        seen_history_urls = set()
        seen_statute_keys = set()
        history_concurrency = max(
            1,
            int(
                os.getenv(
                    "STATE_SCRAPER_MS_HISTORY_CONCURRENCY",
                    "8" if self._full_corpus_enabled() else "4",
                )
                or ("8" if self._full_corpus_enabled() else "4")
            ),
        )
        history_batch_size = max(
            history_concurrency,
            min(
                400,
                int(
                    os.getenv(
                        "STATE_SCRAPER_MS_HISTORY_BATCH_SIZE",
                        str(history_concurrency * 20),
                    )
                    or str(history_concurrency * 20)
                ),
            ),
        )

        for statute in list(seed_statutes or []):
            statute_key = _statute_dedupe_key(statute)
            if statute_key and statute_key in seen_statute_keys:
                continue
            if statute_key:
                seen_statute_keys.add(statute_key)
            statutes.append(statute)
            source_url = str(statute.source_url or "").strip()
            if source_url:
                seen_history_urls.add(source_url)

        for index_url in self._ARCHIVE_INDEX_URLS:
            if len(statutes) >= max_statutes:
                break

            html = await self._request_text(
                index_url,
                headers=headers,
                timeout=30 if max_statutes <= 10 else 60,
                attempts=2 if max_statutes <= 10 else 3,
            )
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            history_urls: List[str] = []
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if "/history/" not in href.lower() or not href.lower().endswith(".htm"):
                    continue
                history_urls.append(urljoin(index_url, href))

            self.logger.info(
                "Mississippi archive history: index_url=%s discovered_history_urls=%s statutes_so_far=%s",
                index_url,
                len(history_urls),
                len(statutes),
            )

            candidate_history_urls: List[str] = []
            for history_url in history_urls:
                if history_url in seen_history_urls:
                    continue
                seen_history_urls.add(history_url)
                candidate_history_urls.append(history_url)
            if not candidate_history_urls:
                continue

            sem = asyncio.Semaphore(history_concurrency)

            async def _fetch_history(history_url: str) -> Optional[NormalizedStatute]:
                async with sem:
                    return await self._build_statute_from_history_url(
                        code_name=code_name,
                        history_url=history_url,
                        headers=headers,
                    )

            scanned_from_index = 0
            cancelled_early = False
            for batch_start in range(0, len(candidate_history_urls), history_batch_size):
                if len(statutes) >= max_statutes:
                    cancelled_early = True
                    break
                batch_urls = candidate_history_urls[batch_start : batch_start + history_batch_size]
                tasks = [asyncio.create_task(_fetch_history(history_url)) for history_url in batch_urls]
                for task in asyncio.as_completed(tasks):
                    scanned_from_index += 1
                    statute = await task
                    if statute is None:
                        if scanned_from_index == 1 or scanned_from_index % 100 == 0:
                            self.logger.info(
                                "Mississippi archive history: scanned=%s/%s statutes_so_far=%s",
                                scanned_from_index,
                                len(candidate_history_urls),
                                len(statutes),
                            )
                        continue
                    statute_key = _statute_dedupe_key(statute)
                    if statute_key and statute_key in seen_statute_keys:
                        continue
                    if statute_key:
                        seen_statute_keys.add(statute_key)
                    statutes.append(statute)
                    if checkpoint is not None:
                        checkpoint.maybe_write(
                            statutes,
                            code_name=code_name,
                            scanned_history_urls=len(seen_history_urls),
                            discovered_history_urls=len(history_urls),
                        )
                    if len(statutes) == 1 or len(statutes) % 25 == 0:
                        self.logger.info(
                            "Mississippi archive history: scanned=%s/%s statutes_so_far=%s",
                            scanned_from_index,
                            len(candidate_history_urls),
                            len(statutes),
                        )
                    if len(statutes) >= max_statutes:
                        cancelled_early = True
                        for pending in tasks:
                            if not pending.done():
                                pending.cancel()
                        break
                if cancelled_early:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break

            # In bounded probes, stop as soon as one index yields usable statutes.
            if statutes and not self._full_corpus_enabled():
                break

        if checkpoint is not None:
            checkpoint.write(
                statutes,
                code_name=code_name,
                scanned_history_urls=len(seen_history_urls),
                discovered_history_urls=len(seen_history_urls),
            )
        return statutes

    async def _scrape_common_crawl_code_sections(
        self,
        code_name: str,
        max_statutes: int = 5,
    ) -> List[NormalizedStatute]:
        candidates = await self._scrape_state_common_crawl_candidates(
            domain_terms=["legislature.ms.gov", "billstatus.ls.state.ms.us"],
            url_terms=["/code_sections/", "/legislation/", "/statutes/", "/code/"],
            mime_terms=["html"],
            max_results=max(10, int(max_statutes or 5) * 4),
        )
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for candidate in candidates:
            if len(statutes) >= max_statutes:
                break
            source_url = str(candidate.get("url") or "")
            text = self._normalize_legal_text(candidate.get("text") or "")
            if len(text) < 120:
                continue
            section_number = self._extract_ms_common_crawl_section_number(source_url, text)
            if not section_number or section_number in seen_sections:
                continue
            seen_sections.add(section_number)
            section_name = self._extract_ms_common_crawl_section_name(text, section_number)
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name or text[:600]),
                    source_url=source_url,
                    official_cite=f"Miss. Code Ann. § {section_number}",
                    structured_data={
                        "source_kind": "common_crawl_state_index_warc",
                        "discovery_method": "hf_state_index_warc_backup",
                        "collection": candidate.get("collection"),
                        "timestamp": candidate.get("timestamp"),
                    },
                )
            )
            if len(statutes) == 1 or len(statutes) % 50 == 0:
                self.logger.info(
                    "Mississippi common-crawl recovery: statutes_so_far=%s candidates_scanned=%s",
                    len(statutes),
                    len(candidates),
                )
        return statutes

    def _extract_ms_common_crawl_section_number(self, source_url: str, text: str) -> str:
        text_value = str(text or "")
        url_match = re.search(r"/code_sections/\d+/(\d{3})-(\d{4})-(\d{4}(?:_\d+)?)", source_url, re.IGNORECASE)
        if not url_match:
            url_match = re.search(r"/code_sections/\d+/(\d{3})/(\d{4})(\d{4}(?:_\d+)?)\.(?:xml|htm|html)$", source_url, re.IGNORECASE)
        if url_match:
            if len(url_match.groups()) == 3:
                title, chapter, section = url_match.groups()
                section = section.replace("_", ".")
                return f"{int(title)}-{int(chapter)}-{section.lstrip('0') or '0'}"

        text_match = re.search(r"Code Section\s+(\d{3})[- ](\d{4})[- ](\d{4}(?:_\d+)?)", text_value, re.IGNORECASE)
        if text_match:
            title, chapter, section = text_match.groups()
            section = section.replace("_", ".")
            return f"{int(title)}-{int(chapter)}-{section.lstrip('0') or '0'}"

        generic = self._extract_section_number(text_value)
        return generic or ""

    def _extract_ms_common_crawl_section_name(self, text: str, section_number: str) -> str:
        text_value = str(text or "")
        title_match = re.search(r"HB\s+\d+\s+(.+?)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+\d{2}/\d{2}", text_value)
        if title_match:
            return self._normalize_legal_text(title_match.group(1))[:200]
        section_match = re.search(rf"{re.escape(section_number)}\s*[-.:]\s*(.+)", text_value)
        if section_match:
            return self._normalize_legal_text(section_match.group(1))[:200]
        return f"Section {section_number}"

    async def _build_statute_from_history_url(
        self,
        code_name: str,
        history_url: str,
        headers: Dict[str, str],
    ) -> Optional[NormalizedStatute]:
        html = await self._request_text(
            history_url,
            headers=headers,
            timeout=30 if headers.get("X-Bounded-Scrape") == "1" else 60,
            attempts=2 if headers.get("X-Bounded-Scrape") == "1" else 3,
        )
        if not html:
            return None

        if "Got an HTTP 404 response at crawl time" in html:
            return None

        text = self._clean_html_text(html)
        if len(text) < 280 or "History of Actions" not in text:
            return None

        bill_id = self._extract_bill_id(text=text, url=history_url)
        if not bill_id:
            return None

        section_number = self._extract_section_number(text) or bill_id
        description = self._extract_description(text)
        section_name = description or f"Bill history {bill_id}"
        official_cite = f"Miss. Bill History {bill_id}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text[:14000],
            legal_area=self._identify_legal_area(f"{description} {text[:1200]}"),
            source_url=history_url,
            official_cite=official_cite,
        )

    def _extract_bill_id(self, text: str, url: str) -> str:
        match = re.search(r"\b(House|Senate)\s+Bill\s+([0-9]{1,4})\b", text, flags=re.IGNORECASE)
        if match:
            chamber = "HB" if match.group(1).lower().startswith("house") else "SB"
            return f"{chamber}{int(match.group(2)):04d}"

        url_match = re.search(r"/(HB|SB)(\d{4})\.htm", str(url or ""), flags=re.IGNORECASE)
        if url_match:
            return f"{url_match.group(1).upper()}{url_match.group(2)}"

        return ""

    def _extract_description(self, text: str) -> str:
        match = re.search(
            r"Description:\s*(.+?)(?:History of Actions:|Background Information:|Title:)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        value = re.sub(r"\s+", " ", match.group(1)).strip(" ;")
        return value

    def _clean_html_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        text = unescape(text).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def _request_text(
        self,
        url: str,
        headers: Dict[str, str],
        timeout: int,
        attempts: int = 3,
    ) -> str:
        prefer_direct_only = self._should_prefer_direct_only_fetch(url)
        direct_first = await self._request_text_direct(url, timeout=max(5, int(timeout or 30)))
        if direct_first:
            return direct_first
        if prefer_direct_only:
            insecure_retry = await self._request_text_with_insecure_tls_retry(
                url=url,
                headers=headers,
                timeout=timeout,
            )
            if insecure_retry:
                return insecure_retry
            return ""

        for _ in range(max(1, int(attempts))):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if payload:
                    return payload.decode("utf-8", errors="replace")
            except Exception:
                await asyncio.sleep(0.7)
                continue
            insecure_retry = await self._request_text_with_insecure_tls_retry(
                url=url,
                headers=headers,
                timeout=timeout,
            )
            if insecure_retry:
                return insecure_retry
            await asyncio.sleep(0.7)
        return ""

    def _should_prefer_direct_only_fetch(self, url: str) -> bool:
        value = str(url or "").strip().lower()
        if not value:
            return False
        return any(marker in value for marker in self._DIRECT_FETCH_HOST_MARKERS)

    def _needs_insecure_tls_retry(self, url: str) -> bool:
        value = str(url or "").lower()
        return any(domain in value for domain in self._INSECURE_TLS_RETRY_DOMAINS)

    async def _request_text_with_insecure_tls_retry(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        timeout: int,
    ) -> str:
        if not self._needs_insecure_tls_retry(url):
            return ""

        def _request_insecure() -> str:
            req_headers = {"User-Agent": "Mozilla/5.0"}
            req_headers.update(dict(headers or {}))
            request = urllib.request.Request(url, headers=req_headers)
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(
                request,
                timeout=max(1, int(timeout or 30)),
                context=ssl_context,
            ) as response:
                payload = response.read()
            return payload.decode("utf-8", errors="replace")

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_request_insecure),
                timeout=max(2, int(timeout or 30)) + 3,
            )
        except Exception:
            return ""
        if text:
            self.logger.info(
                "Mississippi TLS fallback succeeded for host with invalid cert: %s",
                url,
            )
        return text


# Register this scraper with the registry
StateScraperRegistry.register("MS", MississippiScraper)


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


class _MississippiCheckpoint:
    """Best-effort partial progress checkpoint for Mississippi archive crawls."""

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
        stage_label: str = "mississippi:progress",
        scanned_history_urls: int,
        discovered_history_urls: int,
    ) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(
            statutes,
            code_name=code_name,
            stage_label=stage_label,
            scanned_history_urls=scanned_history_urls,
            discovered_history_urls=discovered_history_urls,
        )

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        stage_label: str = "mississippi:complete",
        scanned_history_urls: int,
        discovered_history_urls: int,
    ) -> None:
        self.write_progress(
            statutes=statutes,
            code_name=code_name,
            stage_label=stage_label,
            scanned_history_urls=scanned_history_urls,
            discovered_history_urls=discovered_history_urls,
            extra_progress=None,
        )

    def write_progress(
        self,
        *,
        statutes: List[NormalizedStatute],
        code_name: str,
        stage_label: str,
        scanned_history_urls: int,
        discovered_history_urls: int,
        extra_progress: Optional[Dict[str, Any]],
    ) -> None:
        if not self.path:
            return
        statutes = list(statutes or [])
        existing_rows: List[Dict[str, Any]] = []
        existing_progress: Dict[str, Any] = {}
        if self.path.exists():
            try:
                existing_payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                existing_payload = {}
            if isinstance(existing_payload, dict):
                raw_rows = existing_payload.get("statutes")
                if isinstance(raw_rows, list):
                    existing_rows = [row for row in raw_rows if isinstance(row, dict)]
                raw_progress = existing_payload.get("progress")
                if isinstance(raw_progress, dict):
                    existing_progress = dict(raw_progress)

        serialized_rows = [statute.to_dict() for statute in statutes if isinstance(statute, NormalizedStatute)]
        if not serialized_rows and existing_rows:
            serialized_rows = list(existing_rows)
        elif serialized_rows and existing_rows and len(serialized_rows) < len(existing_rows):
            merged_rows = list(existing_rows)
            seen_keys = set()
            for row in merged_rows:
                statute_id = str(row.get("statute_id") or "").strip().lower()
                source_url = str(row.get("source_url") or "").strip().lower()
                if statute_id:
                    seen_keys.add(f"id:{statute_id}")
                if source_url:
                    seen_keys.add(f"url:{source_url}")
            for row in serialized_rows:
                statute_id = str(row.get("statute_id") or "").strip().lower()
                source_url = str(row.get("source_url") or "").strip().lower()
                key_id = f"id:{statute_id}" if statute_id else ""
                key_url = f"url:{source_url}" if source_url else ""
                if (key_id and key_id in seen_keys) or (key_url and key_url in seen_keys):
                    continue
                if key_id:
                    seen_keys.add(key_id)
                if key_url:
                    seen_keys.add(key_url)
                merged_rows.append(row)
            serialized_rows = merged_rows

        progress_payload: Dict[str, Any] = {
            "scanned_history_urls": int(scanned_history_urls),
            "discovered_history_urls": int(discovered_history_urls),
        }
        if isinstance(extra_progress, dict):
            for key, value in extra_progress.items():
                progress_payload[str(key)] = value
        if existing_progress:
            merged_progress = dict(existing_progress)
            merged_progress.update(progress_payload)
            progress_payload = merged_progress

        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(serialized_rows),
            "code_name": code_name,
            "stage_label": str(stage_label or "").strip() or "mississippi:progress",
            "scanned_history_urls": int(scanned_history_urls),
            "discovered_history_urls": int(discovered_history_urls),
            "progress": progress_payload,
            "statutes": serialized_rows,
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(serialized_rows)
        self.last_write_ts = time.time()
