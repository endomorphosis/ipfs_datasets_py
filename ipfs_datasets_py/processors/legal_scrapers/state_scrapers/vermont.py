"""Scraper for Vermont state laws.

This module contains the scraper for Vermont statutes from the official state legislative website.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class VermontScraper(BaseStateScraper):
    """Scraper for Vermont state laws from https://legislature.vermont.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Vermont's legislative website."""
        return "https://legislature.vermont.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Vermont."""
        return [{
            "name": "Vermont Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Vermont's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=2)
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        if official:
            return official[:limit] if limit is not None else official

        if limit is not None:
            direct = await self._scrape_direct_sections(code_name, max_statutes=limit)
            if direct:
                return direct[:limit]

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(
            code_name,
            code_url,
            "Vt. Stat. Ann.",
            max_sections=max_sections,
        )

    async def _scrape_direct_sections(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        section_urls = [
            f"{self.get_base_url()}/statutes/section/01/001/00001",
            f"{self.get_base_url()}/statutes/section/13/053/02301",
        ]
        return await self._scrape_section_urls(code_name, [(url, "") for url in section_urls], max_statutes=max_statutes)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        title_links = await self._discover_title_links()
        self.logger.info("Vermont official index: discovered %s title links", len(title_links))
        statutes: List[NormalizedStatute] = []
        checkpoint = _VermontCheckpoint(self.state_code)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Vermont official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
                title_label or title_url,
                title_index,
                len(title_links),
                len(chapter_links),
                len(statutes),
            )
            for chapter_index, (chapter_url, chapter_label) in enumerate(chapter_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(chapter_url)
                if chapter_index == 1 or chapter_index % 10 == 0 or chapter_index == len(chapter_links):
                    self.logger.info(
                        "Vermont official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                parsed = await self._scrape_section_urls(
                    code_name,
                    section_links,
                    max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                )
                statutes.extend(parsed)
                checkpoint.maybe_write(statutes, title_label=title_label or title_url, chapter_label=chapter_label or chapter_url)
        checkpoint.write(statutes, title_label="complete", chapter_label="complete")
        return statutes[:limit] if limit is not None else statutes

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/title/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/chapter/[0-9A-Za-z]+/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=20)
        if not payload:
            return []
        soup = BeautifulSoup(payload, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(f"{self.get_base_url()}/", str(anchor.get("href") or "").strip())
            if not re.search(r"/statutes/section/[0-9A-Za-z]+/[0-9A-Za-z]+/[0-9A-Za-z]+/?$", href):
                continue
            normalized = href.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append((normalized, self._normalize_legal_text(anchor.get_text(" ", strip=True))))
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[Tuple[str, str]],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for source_url, section_label in section_urls:
            if limit is not None and len(statutes) >= limit:
                break
            payload = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=15)
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            main = soup.find(id="main-content") or soup
            for tag in main(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = self._normalize_legal_text(main.get_text(" ", strip=True))
            match = re.search(r"\bCite as:\s*([0-9A-Za-z.]+)\s+V\.S\.A\.\s+§\s*([0-9A-Za-z.-]+)", text)
            title_number = match.group(1) if match else ""
            section_number = match.group(2) if match else self._derive_section_number_from_url(source_url)
            heading = main.find(["h1", "h2", "h3"]) or soup.find(["h1", "h2", "h3"])
            section_name = heading.get_text(" ", strip=True) if heading else (section_label or f"Section {section_number}")
            bold = main.find("b")
            if bold:
                section_name = bold.get_text(" ", strip=True)
            if len(text) < 240 or not section_number:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number or None,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text,
                    legal_area=self._identify_legal_area(section_name or text),
                    source_url=source_url,
                    official_cite=f"{title_number} V.S.A. § {section_number}" if title_number else f"Vt. Stat. Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_vermont_statutes_html", "skip_hydrate": True},
                )
            )
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("VT", VermontScraper)


class _VermontCheckpoint:
    """Best-effort partial progress checkpoint for Vermont's long corpus crawl."""

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

    def maybe_write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, title_label=title_label, chapter_label=chapter_label)

    def write(self, statutes: List[NormalizedStatute], *, title_label: str, chapter_label: str) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "title_label": title_label,
            "chapter_label": chapter_label,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
