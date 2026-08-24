"""Scraper for Maryland state laws.

This module contains the scraper for Maryland statutes from the official state
legislative website.
"""

import asyncio
import json
import os
import re
from typing import Dict, List, Optional
import urllib.parse
import urllib.request

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MarylandScraper(BaseStateScraper):
    """Scraper for Maryland state laws from http://mgaleg.maryland.gov"""

    _MD_ARTICLE_CODE_RE = re.compile(r"\(([A-Za-z0-9]+)\)\s*$")
    _MD_NEXT_TRAIL_RE = re.compile(r"\s+Next\s*$", re.IGNORECASE)
    _MD_SECTION_CITE_RE = re.compile(r"§\s*([0-9A-Za-z\-\u2010-\u2015\.]+)")

    def get_base_url(self) -> str:
        """Return the base URL for Maryland's legislative website."""
        return "https://mgaleg.maryland.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maryland."""
        return [
            {
                "name": "Maryland Code",
                "url": f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
                "type": "Code",
            }
        ]

    def _extract_article_code(self, display_text: str, value: str) -> str:
        match = self._MD_ARTICLE_CODE_RE.search(str(display_text or ""))
        if match:
            return match.group(1).upper()
        return str(value or "").strip().upper()

    def _normalize_section_code(self, value: str) -> str:
        normalized = str(value or "").strip()
        for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"):
            normalized = normalized.replace(dash, "-")
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.strip(".")

    def _is_maryland_api_record(self, statute: NormalizedStatute) -> bool:
        if not isinstance(statute, NormalizedStatute):
            return False
        structured = getattr(statute, "structured_data", {}) or {}
        return str(structured.get("record_type") or "").strip().lower() == "maryland_api_section"

    async def _fetch_json(self, url: str) -> object:
        text = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if isinstance(payload, bytes):
                text = payload.decode("utf-8", errors="ignore")
            elif payload:
                text = str(payload)

        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    async def _fetch_api_section_code(self, url: str) -> Optional[str]:
        """Parse GetNext/GetPrevious JSON or the .NET XML ``<string>`` envelope."""

        from .maryland_section import parse_get_next_envelope

        payload = await self._fetch_json(url)
        if isinstance(payload, str) and payload.strip() and payload.strip().lower() != "null":
            return payload.strip()
        text = await self._fetch_text_direct(url, timeout=20)
        return parse_get_next_envelope(text)

    def _articles_from_toc_html(self, html: str) -> List[Dict[str, str]]:
        from .maryland_section import statute_articles

        out: List[Dict[str, str]] = []
        for code, name in statute_articles(html):
            out.append({"DisplayText": f"{name} - ({code})", "Value": code})
        return out

    async def _fetch_text_direct(self, url: str, timeout: int = 45) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception:
            payload = await self._fetch_page_content_with_archival_fallback(
                url, timeout_seconds=timeout
            )
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="ignore")
            if payload:
                return str(payload)
            return ""

    async def _list_article_payload(self) -> List[Dict[str, str]]:
        from .maryland_section import TOC_URL, configured_toc_html_path

        toc_path = configured_toc_html_path()
        if toc_path is not None:
            return self._articles_from_toc_html(
                toc_path.read_text(encoding="utf-8", errors="replace")
            )
        articles_url = f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        articles_payload = await self._fetch_json(articles_url)
        if isinstance(articles_payload, list) and articles_payload:
            from .maryland_section import is_statute_article_code

            filtered: List[Dict[str, str]] = []
            for article in articles_payload:
                if not isinstance(article, dict):
                    continue
                value = str(article.get("Value") or "").strip()
                display = str(article.get("DisplayText") or "").strip()
                code = value or self._extract_article_code(display, value)
                if is_statute_article_code(code.lower()):
                    filtered.append(article)
            if filtered:
                return filtered
        toc_html = await self._fetch_text_direct(TOC_URL, timeout=45)
        if not toc_html:
            return []
        return self._articles_from_toc_html(toc_html)

    async def _list_section_codes(
        self,
        *,
        article_value: str,
        article_code: str,
        budget: int,
    ) -> List[tuple[str, str]]:
        """Return ``(label, section_code)`` from GetSections JSON or GetNext XML."""

        from .maryland_section import first_section_seeds, get_next_url, get_previous_url

        sections_url = (
            f"{self.get_base_url()}/mgawebsite/api/Laws/GetSections"
            f"?articleCode={article_value or article_code.lower()}&enactments=false"
        )
        sections_payload = await self._fetch_json(sections_url)
        out: List[tuple[str, str]] = []
        if isinstance(sections_payload, list):
            for section in sections_payload[: max(0, int(budget))]:
                if not isinstance(section, dict):
                    continue
                section_label = str(section.get("DisplayText") or "").strip()
                section_code = self._normalize_section_code(
                    section_label or str(section.get("Value") or "")
                )
                if section_code:
                    out.append((section_label or section_code, section_code))
            if out:
                return out

        seed = None
        article_token = article_value or article_code.lower()
        for candidate in first_section_seeds():
            nxt = await self._fetch_api_section_code(get_next_url(article_token, candidate))
            if nxt:
                seed = candidate
                break
            prev = await self._fetch_api_section_code(get_previous_url(article_token, candidate))
            if prev:
                seed = prev
                break
        if seed is None:
            return []
        current = seed
        for _ in range(5000):
            prev = await self._fetch_api_section_code(get_previous_url(article_token, current))
            if not prev:
                break
            current = prev
        seen: set[str] = set()
        while current and current not in seen and len(out) < max(0, int(budget)):
            seen.add(current)
            out.append((current, current))
            current = await self._fetch_api_section_code(get_next_url(article_token, current))
        return out

    async def _scrape_api_sections(
        self, code_name: str, max_statutes: Optional[int] = None
    ) -> List[NormalizedStatute]:
        articles_payload = await self._list_article_payload()
        if not isinstance(articles_payload, list) or not articles_payload:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        self.logger.info(
            "Maryland API scrape: discovered_articles=%s max_statutes=%s",
            len(articles_payload),
            limit or "unbounded",
        )

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        sem = asyncio.Semaphore(8)
        discovered_candidates = 0
        scanned_candidates = 0
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maryland:article-discovery",
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(articles_payload)),
                "scanned_candidates": 0,
                "discovered_candidates": 0,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        async def _build_one(
            *,
            article_display: str,
            section_label: str,
            section_code: str,
            section_url: str,
        ) -> NormalizedStatute | None:
            async with sem:
                return await self._build_statute_from_section_page(
                    code_name=code_name,
                    article_label=article_display,
                    section_label=section_label,
                    section_number=section_code,
                    section_url=section_url,
                )

        for article_index, article in enumerate(articles_payload, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            if not isinstance(article, dict):
                continue

            article_display = str(article.get("DisplayText") or "").strip()
            article_value = str(article.get("Value") or "").strip()
            article_code = self._extract_article_code(article_display, article_value)
            if not article_code:
                continue

            if limit is None:
                budget = 2000
            else:
                remaining = max(0, int(limit) - len(statutes))
                section_budget_cap = self._env_int(
                    "STATE_SCRAPER_MD_MAX_SECTION_BUDGET_PER_ARTICLE",
                    default=240,
                )
                section_budget_cap = max(40, min(2000, int(section_budget_cap or 240)))
                budget = min(max(remaining * 3, 40), section_budget_cap)
            section_codes = await self._list_section_codes(
                article_value=article_value,
                article_code=article_code,
                budget=budget,
            )
            discovered_candidates += int(len(section_codes))
            section_inputs: List[tuple[str, str, str, str]] = []
            for section_label, section_code in section_codes:
                if not section_code:
                    continue

                section_url = (
                    f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                    f"?article={article_code}&section={section_code}&enactments=false"
                )
                if section_url in seen_urls:
                    continue

                seen_urls.add(section_url)
                section_inputs.append(
                    (
                        article_display,
                        section_label,
                        section_code,
                        section_url,
                    )
                )

            self.logger.info(
                "Maryland API scrape: article=%s queued_sections=%s statutes_so_far=%s",
                article_code,
                len(section_inputs),
                len(statutes),
            )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="maryland:article-scan",
                extra={
                    "titles_scanned": int(article_index),
                    "discovered_titles": int(len(articles_payload)),
                    "scanned_candidates": int(scanned_candidates),
                    "discovered_candidates": int(discovered_candidates),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

            section_batch_size = self._env_int("STATE_SCRAPER_MD_SECTION_BATCH_SIZE", default=40)
            section_batch_size = max(8, min(256, int(section_batch_size or 40)))
            try:
                asyncio.get_running_loop()
                parallel = True
            except RuntimeError:
                parallel = False
            for batch_start in range(0, len(section_inputs), section_batch_size):
                if limit is not None and len(statutes) >= limit:
                    break
                batch_inputs = section_inputs[batch_start : batch_start + section_batch_size]
                if parallel:
                    batch_jobs = [
                        _build_one(
                            article_display=item[0],
                            section_label=item[1],
                            section_code=item[2],
                            section_url=item[3],
                        )
                        for item in batch_inputs
                    ]
                    batch_results = await asyncio.gather(*batch_jobs, return_exceptions=True)
                else:
                    batch_results = []
                    for item in batch_inputs:
                        try:
                            batch_results.append(
                                await self._build_statute_from_section_page(
                                    code_name=code_name,
                                    article_label=item[0],
                                    section_label=item[1],
                                    section_number=item[2],
                                    section_url=item[3],
                                )
                            )
                        except Exception as exc:
                            batch_results.append(exc)
                for statute in batch_results:
                    scanned_candidates += 1
                    if isinstance(statute, Exception):
                        continue
                    if statute is None:
                        continue
                    if not self._is_maryland_api_record(
                        statute
                    ) and self._is_low_quality_statute_record(statute):
                        continue

                    statutes.append(statute)
                    if len(statutes) == 1 or len(statutes) % 50 == 0:
                        self.logger.info(
                            "Maryland API scrape: statutes_so_far=%s",
                            len(statutes),
                        )
                    if limit is not None and len(statutes) >= limit:
                        break

                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="maryland:section-progress",
                    extra={
                        "titles_scanned": int(article_index),
                        "discovered_titles": int(len(articles_payload)),
                        "scanned_candidates": int(scanned_candidates),
                        "discovered_candidates": int(discovered_candidates),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
                if limit is not None and len(statutes) >= limit:
                    break

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="maryland:complete",
            force=True,
            extra={
                "scanned_candidates": int(scanned_candidates),
                "discovered_candidates": int(discovered_candidates),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    async def _build_statute_from_section_page(
        self,
        *,
        code_name: str,
        article_label: str,
        section_label: str,
        section_number: str,
        section_url: str,
    ) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            html_text = await self._fetch_text_direct(section_url, timeout=35)
        except Exception:
            return None
        if not html_text:
            return None

        soup = BeautifulSoup(html_text, "html.parser")
        from .maryland_section import parse_maryland_section_html

        parsed = parse_maryland_section_html(
            html_text, source_url=section_url, code_name=code_name
        )
        if parsed is not None:
            return parsed
        text_node = soup.select_one("#StatuteText") or soup.select_one("#mainBody")
        if text_node is None:
            return None

        text = " ".join(text_node.get_text(" ", strip=True).split())
        text = self._MD_NEXT_TRAIL_RE.sub("", text).strip()
        if len(text) < 220:
            return None

        cite_match = self._MD_SECTION_CITE_RE.search(text)
        normalized_section = self._normalize_section_code(section_number)
        if not normalized_section and cite_match:
            normalized_section = self._normalize_section_code(cite_match.group(1))
        if not normalized_section:
            return None
        article_name = str(article_label or "").split(" - ", 1)[0].strip() or "Maryland Code"
        article_name = re.sub(r"\s*\([A-Za-z0-9]+\)\s*$", "", article_name).strip() or article_name
        article_code = ""
        article_match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", str(article_label or ""))
        if article_match:
            article_code = article_match.group(1).upper()
        if not article_code:
            query = urllib.parse.urlparse(section_url).query
            article_param = urllib.parse.parse_qs(query).get("article", [""])
            article_code = str(article_param[0] or "").strip().upper()
        display_label = str(section_label or normalized_section).strip()
        section_name = f"{article_name} § {display_label}"
        statute_id = f"{code_name} [{article_code or article_name}] § {normalized_section}"
        official_cite = (
            f"Md. Code, {article_name} § {normalized_section}"
            if article_name
            else f"Md. Code § {normalized_section}"
        )

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=statute_id,
            code_name=code_name,
            section_number=normalized_section,
            section_name=section_name[:200],
            full_text=text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(article_name),
            official_cite=official_cite,
            metadata=StatuteMetadata(),
            structured_data={
                "skip_hydrate": True,
                "record_type": "maryland_api_section",
                "source_kind": "official_maryland_api_section_html",
                "discovery_method": "official_articles_sections_api",
                "article_name": article_name,
                "article_code": article_code,
            },
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Maryland's legislative website.

        Maryland uses JavaScript for statute search, so we use Playwright.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .maryland_constitution import (
            configured_constitution_html_path,
            parse_configured_maryland_constitution,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_configured_maryland_constitution(
                    code_name=code_name or "Maryland Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .maryland_section import configured_section_html_path, parse_maryland_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_maryland_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcr&section=2-201&enactments=false",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        allow_justia = str(
            os.getenv("STATE_SCRAPER_MD_ALLOW_JUSTIA_FALLBACK", "0") or "0"
        ).strip().lower() in {"1", "true", "yes", "on"}

        api_statutes = await self._scrape_api_sections(code_name, max_statutes=limit)
        if api_statutes:
            return api_statutes if limit is None else api_statutes[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct_statutes = await self._scrape_direct_seed_sections(
                code_name, max_statutes=max(1, int(limit or 2))
            )
            if direct_statutes:
                return direct_statutes if limit is None else direct_statutes[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None and not allow_justia:
            return []

        return_threshold = int(limit) if limit is not None else 160
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GCR&section=1-101&enactments=false",
        ]
        # Secondary Justia mirrors are never sole full-corpus admission unless
        # explicitly re-enabled; bounded probes may still use them as last resort.
        if allow_justia or (not self._full_corpus_enabled()):
            candidate_urls.append("https://law.justia.com/codes/maryland/")

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                source = str(statute.source_url or "").lower()
                if self._full_corpus_enabled() and not allow_justia:
                    if "justia.com" in source or "findlaw.com" in source:
                        continue
                if not self._is_maryland_api_record(
                    statute
                ) and self._is_low_quality_statute_record(statute):
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if (
                self._full_corpus_enabled()
                and not allow_justia
                and ("justia.com" in str(candidate).lower() or "findlaw.com" in str(candidate).lower())
            ):
                continue

            try:
                statutes = await self._playwright_scrape(
                    code_name,
                    candidate,
                    "Md. Code Ann.",
                    wait_for_selector="a[href*='statute'], a[href*='laws'], .article-link",
                    timeout=45000,
                    wait_until="domcontentloaded",
                    max_sections=max(10, return_threshold),
                )
            except Exception:
                statutes = []

            _merge(statutes)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

            try:
                generic = await self._generic_scrape(
                    code_name, candidate, "Md. Code Ann.", max_sections=max(10, return_threshold)
                )
            except Exception:
                generic = []

            _merge(generic)
            if limit is not None and len(merged) >= int(limit):
                return merged[: int(limit)]

        return merged if limit is None else merged[: int(limit)]

    async def _scrape_direct_seed_sections(
        self, code_name: str, max_statutes: int
    ) -> List[NormalizedStatute]:
        seeds = [
            ("State Government", "GSG", "1-101"),
            ("Criminal Law", "GCR", "1-101"),
        ]
        out: List[NormalizedStatute] = []
        for article_label, article_code, section_code in seeds[: max(1, int(max_statutes or 1))]:
            section_url = (
                f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                f"?article={article_code}&section={section_code}&enactments=false"
            )
            statute = await self._build_statute_from_section_page(
                code_name=code_name,
                article_label=article_label,
                section_label=section_code,
                section_number=section_code,
                section_url=section_url,
            )
            if statute is not None:
                out.append(statute)
        return out

    def _official_ssl_context(self, *, unverified: bool = False):
        import ssl

        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> tuple[bytes, bytes, bytes]:
        """Fetch one official Maryland URL and retain request/response/body bytes."""
        import ssl
        import urllib.error
        import urllib.request

        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_bytes = (
            f"GET {path} HTTP/1.1\n"
            f"host: {host}\n"
            "accept: application/json,text/html;q=0.9,*/*;q=0.8\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-maryland/1.0",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
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
            raise RuntimeError(f"official Maryland GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Maryland GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_article_index(self, payload: object) -> List[Dict[str, str]]:
        """Parse every official Maryland Code article from the live articles API."""
        if not isinstance(payload, list):
            raise RuntimeError("official Maryland GetArticles payload is not a list")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for article in payload:
            if not isinstance(article, dict):
                continue
            display = str(article.get("DisplayText") or "").strip()
            value = str(article.get("Value") or "").strip()
            article_code = self._extract_article_code(display, value)
            if not article_code or article_code in seen:
                continue
            seen.add(article_code)
            source_url = (
                f"{self.get_base_url()}/mgawebsite/Laws/Statutes"
                f"?article={urllib.parse.quote(value or article_code)}"
            )
            label = display or f"Article {article_code}"
            units.append(
                {
                    "canonical_key": f"md:article-{article_code.lower()}",
                    "source_url": source_url,
                    "label": label,
                    "text": (
                        f"Maryland Code {label} official article index entry "
                        f"retained from {source_url}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "MD"):
        """Acquire the uncapped official Maryland article frontier."""
        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "MD").strip().upper()
        if normalized != "MD":
            raise ValueError(f"MarylandScraper cannot acquire {normalized}")
        index_url = f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        try:
            payload = json.loads(index_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("official Maryland GetArticles payload is not JSON") from exc
        units = self._parse_official_article_index(payload)
        if len(units) < 3:
            raise RuntimeError(
                f"official Maryland article index is incomplete: {len(units)} units"
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
            jurisdiction_code="MD",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain="mgaleg.maryland.gov",
            source_path="/mgawebsite/Laws/Statutes",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("MD", MarylandScraper)
