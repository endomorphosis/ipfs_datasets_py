"""Scraper for Idaho state laws.

This module contains the scraper for Idaho statutes from the official state legislative website.
"""

from typing import List, Dict, Optional, Tuple
import re
import os
import time
import json
from pathlib import Path
from urllib.parse import urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IdahoScraper(BaseStateScraper):
    """Scraper for Idaho state laws from https://legislature.idaho.gov"""

    _ID_SECTION_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/t\d+ch\d+/sect\d+[\-\.0-9A-Za-z]*$", re.IGNORECASE)
    _ID_TITLE_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/?$", re.IGNORECASE)
    _ID_CHAPTER_URL_RE = re.compile(r"/statutesrules/idstat/title\d+/t\d+ch\d+/?$", re.IGNORECASE)
    _ID_SECTION_NUM_RE = re.compile(r"/sect([0-9A-Za-z.-]+)/?$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ID_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Idaho's legislative website."""
        return "https://legislature.idaho.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Idaho."""
        return [{
            "name": "Idaho Statutes",
            "url": f"{self.get_base_url()}/statutesrules/idstat/",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str, max_statutes: int | None = None) -> List[NormalizedStatute]:
        """Scrape a specific code from Idaho's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = max(1, int(max_statutes)) if max_statutes else None
        statutes: List[NormalizedStatute] = []
        checkpoint = _IdahoCheckpoint(self.state_code)
        title_links = await self._discover_title_links(code_url)
        self.logger.info("Idaho official index: discovered %s title links", len(title_links))

        for title_index, (title_url, title_label) in enumerate(title_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = await self._discover_chapter_links(title_url)
            self.logger.info(
                "Idaho official index: title=%s index=%s/%s chapters=%s statutes_so_far=%s",
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
                        "Idaho official index: title=%s chapter=%s/%s sections=%s statutes_so_far=%s",
                        title_label or title_url,
                        chapter_index,
                        len(chapter_links),
                        len(section_links),
                        len(statutes),
                    )
                for section_url, section_label in section_links:
                    if limit is not None and len(statutes) >= limit:
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
                        checkpoint.maybe_write(statutes, title_label=title_label, chapter_label=chapter_label)

        if statutes:
            checkpoint.write(statutes, title_label="complete", chapter_label="complete")
            return statutes[:limit] if limit is not None else statutes

        self.logger.warning("Idaho official direct crawl returned no statutes; skipping generic recovery fallback")
        return []

    async def _fetch_official_id_html(self, url: str, timeout_seconds: int = 15) -> str:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached.decode("utf-8", errors="replace")

        timeout = max(1, int(timeout_seconds or 15))

        def _request() -> bytes:
            try:
                import requests

                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-idaho-statutes-scraper/2.0",
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

    async def _discover_title_links(self, code_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = code_url or f"{self.get_base_url()}/statutesrules/idstat/"
        html = await self._fetch_official_id_html(index_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._ID_TITLE_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rsplit("/title", 1)[-1].rstrip("/")))
        return out

    async def _discover_chapter_links(self, title_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_id_html(title_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._ID_CHAPTER_URL_RE.search(href):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rsplit("/", 2)[-2]))
        return out

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_id_html(chapter_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(chapter_url, str(anchor.get("href") or "").strip())
            if not self._ID_SECTION_URL_RE.search(href.rstrip("/")):
                continue
            normalized = href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label))
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

        html = await self._fetch_official_id_html(section_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        for node in soup(["script", "style", "noscript", "form", "nav", "footer", "header"]):
            node.decompose()

        main_node = soup.select_one("section.parallax-fix .wpb_column") or soup.select_one("body")
        if main_node is None:
            return None

        full_text = self._normalize_legal_text(main_node.get_text(" ", strip=True))
        marker_match = re.search(r"\b(\d+[A-Za-z]?\-\d+[A-Za-z0-9.-]*)\.\s+", full_text)
        if marker_match:
            full_text = full_text[marker_match.start() :]
        full_text = re.split(r"\bHow current is this law\?", full_text, maxsplit=1)[0].strip()
        if len(full_text) < 80:
            return None

        url_match = self._ID_SECTION_NUM_RE.search(section_url)
        section_number = (url_match.group(1) if url_match else section_label).upper()
        section_number = section_number.replace(".", "-")
        heading_match = re.match(r"([0-9A-Z.-]+)\.\s+(.+?)(?:\s+The\b|\s+History:|$)", full_text)
        section_name = ""
        if heading_match:
            section_name = heading_match.group(2).strip(" .")
        section_name = section_name or section_label or f"Section {section_number}"

        title_number_match = re.search(r"title(\d+)", section_url, re.IGNORECASE)
        chapter_number_match = re.search(r"t\d+ch(\d+)", section_url, re.IGNORECASE)

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number_match.group(1) if title_number_match else None,
            title_name=title_label or None,
            chapter_number=chapter_number_match.group(1) if chapter_number_match else None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text[:14000],
            legal_area=self._identify_legal_area(section_name or chapter_label or title_label),
            source_url=section_url,
            official_cite=f"Idaho Code § {section_number}",
            structured_data={
                "source_kind": "official_idaho_statutes_html",
                "discovery_method": "official_title_chapter_section_index",
                "skip_hydrate": True,
            },
        )


# Register this scraper with the registry
StateScraperRegistry.register("ID", IdahoScraper)


class _IdahoCheckpoint:
    """Best-effort partial progress checkpoint for Idaho's large corpus crawl."""

    def __init__(self, state_code: str) -> None:
        raw_dir = str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
        if not raw_dir:
            self.path: Optional[Path] = None
        else:
            self.path = Path(raw_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
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
        if not self.path:
            return
        payload = {
            "state_code": "ID",
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
