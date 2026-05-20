"""Scraper for Mississippi state laws.

This module contains the scraper for Mississippi statutes from the official state legislative website.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import json
import os
import re
import time
from dataclasses import fields as dataclass_fields
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
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
        if not self._full_corpus_enabled():
            common_crawl = await self._scrape_common_crawl_code_sections(
                code_name=code_name,
                max_statutes=limit or 5,
            )
            if common_crawl:
                return common_crawl[:limit] if limit is not None else common_crawl

            recovery = await self._scrape_jina_justia_seed_sections(code_name=code_name, max_statutes=limit or 1)
            if recovery:
                return recovery[:limit] if limit is not None else recovery

        checkpoint = _MississippiCheckpoint(self.state_code)
        seed_statutes = checkpoint.load(
            default_state_name=self.state_name,
            default_code_name=code_name,
            max_statutes=(limit or 1000000),
        )

        archival = await self._scrape_archived_bill_history(
            code_name=code_name,
            max_statutes=limit or 1000000,
            seed_statutes=seed_statutes,
            checkpoint=checkpoint,
        )
        if archival and (not self._full_corpus_enabled() or max_statutes is not None):
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            return archival[:limit] if limit is not None else archival

        candidate_urls = [
            code_url,
            "https://www.legislature.ms.gov/legislation/",
            "http://www.legislature.ms.gov/legislation/",
            # Archive fallback candidate when live pathing changes.
            "https://web.archive.org/web/20251017000000/https://www.legislature.ms.gov/legislation/",
        ]

        seen = set()
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

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
                        return statutes[:limit]
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Miss. Code Ann.", max_sections=limit)
            if statutes:
                return statutes[:limit]

        if archival:
            self.logger.info(f"Mississippi archive history fallback: Scraped {len(archival)} records")
            if limit is not None:
                return archival[:limit]
            return list(archival)
        return []

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
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

    async def _scrape_archived_bill_history(
        self,
        code_name: str,
        max_statutes: int,
        *,
        seed_statutes: Optional[List[NormalizedStatute]] = None,
        checkpoint: Optional["_MississippiCheckpoint"] = None,
    ) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        bounded_scrape = max_statutes <= 10
        if bounded_scrape:
            headers["X-Bounded-Scrape"] = "1"
        statutes: List[NormalizedStatute] = []
        seen_history_urls = set()
        seen_statute_keys = set()

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
                timeout=15 if max_statutes <= 10 else 60,
                attempts=1 if max_statutes <= 10 else 3,
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

            for history_index, history_url in enumerate(history_urls, start=1):
                if len(statutes) >= max_statutes:
                    break
                if history_url in seen_history_urls:
                    continue
                seen_history_urls.add(history_url)

                statute = await self._build_statute_from_history_url(
                    code_name=code_name,
                    history_url=history_url,
                    headers=headers,
                )
                if statute is None:
                    if history_index == 1 or history_index % 100 == 0:
                        self.logger.info(
                            "Mississippi archive history: scanned=%s/%s statutes_so_far=%s",
                            history_index,
                            len(history_urls),
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
                        history_index,
                        len(history_urls),
                        len(statutes),
                    )

            if statutes:
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
            timeout=15 if headers.get("X-Bounded-Scrape") == "1" else 60,
            attempts=1 if headers.get("X-Bounded-Scrape") == "1" else 3,
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
        return ""


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
            scanned_history_urls=scanned_history_urls,
            discovered_history_urls=discovered_history_urls,
        )

    def write(
        self,
        statutes: List[NormalizedStatute],
        *,
        code_name: str,
        scanned_history_urls: int,
        discovered_history_urls: int,
    ) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "code_name": code_name,
            "scanned_history_urls": int(scanned_history_urls),
            "discovered_history_urls": int(discovered_history_urls),
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
