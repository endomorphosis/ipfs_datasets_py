"""Scraper for Maryland state laws.

This module contains the scraper for Maryland statutes from the official state
legislative website.
"""

import asyncio
import json
import re
from typing import Dict, List
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
        return [{
            "name": "Maryland Code",
            "url": f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
            "type": "Code"
        }]

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

    async def _fetch_text_direct(self, url: str, timeout: int = 45) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout)
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="ignore")
            if payload:
                return str(payload)
            return ""

    async def _scrape_api_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        articles_url = f"{self.get_base_url()}/mgawebsite/api/Laws/GetArticles?enactments=false"
        articles_payload = await self._fetch_json(articles_url)
        if not isinstance(articles_payload, list):
            return []

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        sem = asyncio.Semaphore(8)

        async def _build_one(*, article_display: str, section_label: str, section_code: str, section_url: str) -> NormalizedStatute | None:
            async with sem:
                return await self._build_statute_from_section_page(
                    code_name=code_name,
                    article_label=article_display,
                    section_label=section_label,
                    section_number=section_code,
                    section_url=section_url,
                )

        for article in articles_payload:
            if len(statutes) >= max_statutes:
                break
            if not isinstance(article, dict):
                continue

            article_display = str(article.get("DisplayText") or "").strip()
            article_value = str(article.get("Value") or "").strip()
            article_code = self._extract_article_code(article_display, article_value)
            if not article_code:
                continue

            sections_url = (
                f"{self.get_base_url()}/mgawebsite/api/Laws/GetSections"
                f"?articleCode={article_value or article_code.lower()}&enactments=false"
            )
            sections_payload = await self._fetch_json(sections_url)
            if not isinstance(sections_payload, list):
                continue

            section_jobs = []
            remaining = max_statutes - len(statutes)
            budget = min(len(sections_payload), max(remaining * 4, 80))
            for section in sections_payload[:budget]:
                if not isinstance(section, dict):
                    continue

                section_label = str(section.get("DisplayText") or "").strip()
                section_code = self._normalize_section_code(
                    section_label or str(section.get("Value") or "")
                )
                if not section_code:
                    continue

                section_url = (
                    f"{self.get_base_url()}/mgawebsite/Laws/StatuteText"
                    f"?article={article_code}&section={section_code}&enactments=false"
                )
                if section_url in seen_urls:
                    continue

                seen_urls.add(section_url)
                section_jobs.append(
                    _build_one(
                        article_display=article_display,
                        section_label=section_label,
                        section_code=section_code,
                        section_url=section_url,
                    )
                )

            for statute in await asyncio.gather(*section_jobs, return_exceptions=True):
                if isinstance(statute, Exception):
                    continue
                if statute is None:
                    continue
                if not self._is_maryland_api_record(statute) and self._is_low_quality_statute_record(statute):
                    continue

                statutes.append(statute)
                if len(statutes) >= max_statutes:
                    break

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
        display_label = str(section_label or normalized_section).strip()
        section_name = f"{article_name} § {display_label}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {normalized_section}",
            code_name=code_name,
            section_number=normalized_section,
            section_name=section_name[:200],
            full_text=text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(article_name),
            official_cite=f"Md. Code § {normalized_section}",
            metadata=StatuteMetadata(),
            structured_data={"skip_hydrate": True, "record_type": "maryland_api_section"},
        )
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Maryland's legislative website.
        
        Maryland uses JavaScript for statute search, so we use Playwright.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(80)
        api_statutes = await self._scrape_api_sections(code_name, max_statutes=max(10, return_threshold))
        if len(api_statutes) >= return_threshold:
            return api_statutes

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/mgawebsite/Laws/Statutes",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GSG&section=1-101&enactments=false",
            f"{self.get_base_url()}/mgawebsite/Laws/StatuteText?article=GCR&section=1-101&enactments=false",
            "https://law.justia.com/codes/maryland/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                if not self._is_maryland_api_record(statute) and self._is_low_quality_statute_record(statute):
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(api_statutes)
        if len(merged) >= return_threshold:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            try:
                statutes = await self._playwright_scrape(
                    code_name,
                    candidate,
                    "Md. Code Ann.",
                    wait_for_selector="a[href*='statute'], a[href*='laws'], .article-link",
                    timeout=45000,
                        wait_until="domcontentloaded",
                    max_sections=520,
                )
            except Exception:
                statutes = []

            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

            try:
                generic = await self._generic_scrape(code_name, candidate, "Md. Code Ann.", max_sections=520)
            except Exception:
                generic = []

            _merge(generic)
            if len(merged) >= return_threshold:
                return merged

        return merged


# Register this scraper with the registry
StateScraperRegistry.register("MD", MarylandScraper)
