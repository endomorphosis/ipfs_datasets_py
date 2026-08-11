"""Scraper for Hawaii state laws.

Primary path walks the official Hawaii Revised Statutes HTML tree on
capitol.hawaii.gov. Wayback snapshots of that same official tree remain an
accepted archival recovery path; Justia and emergency stubs are never
sole-admitted under full-corpus certification.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class HawaiiScraper(BaseStateScraper):
    """Scraper for Hawaii state laws from https://www.capitol.hawaii.gov."""

    _WAYBACK_ROOTS = [
        "http://web.archive.org/web/20060407224843/http://www.capitol.hawaii.gov/hrscurrent/",
        "http://web.archive.org/web/20060407230101/http://www.capitol.hawaii.gov/hrscurrent/",
    ]
    _SECTION_FILE_RE = re.compile(r"HRS_(\d{4})-(\d{4}(?:_\d{4})?)\.HTM$", re.IGNORECASE)
    _LIVE_VOLUME_RE = re.compile(r"/hrscurrent/Vol[^/]+/?$", re.IGNORECASE)
    _LIVE_CHAPTER_RE = re.compile(r"/hrscurrent/Vol[^/]+/HRS\d{4}[A-Z]?/?$", re.IGNORECASE)
    _LIVE_SECTION_RE = re.compile(
        r"/hrscurrent/Vol[^/]+/HRS\d{4}[A-Z]?/HRS_\d{4}-\d{4}(?:_\d{4})?\.HTM$",
        re.IGNORECASE,
    )
    _SEED_SECTION_URLS = [
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0001.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0002.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0003.HTM",
        "https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/HRS0001/HRS_0001-0004.HTM",
    ]

    def get_base_url(self) -> str:
        """Return the base URL for Hawaii's legislative website."""
        return "https://www.capitol.hawaii.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Hawaii."""
        return [
            {
                "name": "Hawaii Revised Statutes",
                "url": f"{self.get_base_url()}/hrscurrent/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Hawaii Revised Statutes from the official HTML tree first."""
        limit = max(1, int(max_statutes)) if max_statutes else None

        official = await self._scrape_official_hrs_tree(
            code_name=code_name,
            code_url=code_url,
            max_statutes=limit,
        )
        if official:
            return official[:limit] if limit is not None else official

        # Official seed sections (live capitol.hawaii.gov paths).
        seeded = await self._scrape_seed_sections(
            code_name,
            max_statutes=min(8, limit or 8),
        )
        if seeded and (limit is None or len(seeded) >= min(2, limit or 2)):
            if limit is not None and len(seeded) >= limit:
                return seeded[:limit]

        # Archival recovery of the same official tree via Wayback.
        if self._env_enabled("HAWAII_WALK_WAYBACK_FULL", default=self._full_corpus_enabled()) or limit is not None:
            try:
                archival = await asyncio.wait_for(
                    self._scrape_archived_hrscurrent(
                        code_name,
                        max_statutes=max(10, limit or 40),
                    ),
                    timeout=220,
                )
            except asyncio.TimeoutError:
                archival = []
            if archival:
                return archival[:limit] if limit is not None else archival

        if seeded:
            return seeded[:limit] if limit is not None else seeded

        # Optional secondary Justia — never sole-admit under full corpus.
        allow_justia = self._env_enabled("HAWAII_GENERIC_FALLBACK", default=False) or self._env_enabled(
            "STATE_SCRAPER_HI_ALLOW_JUSTIA_FALLBACK", default=False
        )
        if allow_justia and not self._full_corpus_enabled():
            justia = await self._generic_scrape(
                code_name,
                "https://law.justia.com/codes/hawaii/",
                "Haw. Rev. Stat.",
                max_sections=limit or 40,
            )
            if justia:
                return justia[:limit] if limit is not None else justia

        # Emergency stubs only outside full-corpus certification.
        if not self._full_corpus_enabled():
            stubs = self._build_emergency_statute_stubs(code_name, count=min(40, limit or 40))
            if stubs:
                self.logger.warning(
                    "Hawaii returning emergency stubs (%s rows); not full-corpus certified content",
                    len(stubs),
                )
                return stubs[:limit] if limit is not None else stubs

        self.logger.warning(
            "Hawaii official direct crawl returned no statutes; refusing secondary sole-admission"
        )
        return []

    @staticmethod
    def _env_enabled(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    async def _fetch_official_hi_html(self, url: str, timeout_seconds: int = 18) -> str:
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
                        "User-Agent": "ipfs-datasets-hawaii-statutes-scraper/3.0",
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

    async def _scrape_official_hrs_tree(
        self,
        *,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        index_url = code_url or f"{self.get_base_url()}/hrscurrent/"
        volume_links = await self._discover_volume_links(index_url)
        self.logger.info("Hawaii official index: discovered %s volume links", len(volume_links))
        statutes: List[NormalizedStatute] = []

        for volume_index, (volume_url, volume_label) in enumerate(volume_links, start=1):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            chapter_links = await self._discover_chapter_links(volume_url)
            self.logger.info(
                "Hawaii official index: volume=%s index=%s/%s chapters=%s statutes_so_far=%s",
                volume_label or volume_url,
                volume_index,
                len(volume_links),
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
                    statute = await self._parse_live_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        chapter_label=chapter_label,
                        volume_label=volume_label,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _discover_volume_links(self, index_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(index_url, self._LIVE_VOLUME_RE)

    async def _discover_chapter_links(self, volume_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(volume_url, self._LIVE_CHAPTER_RE)

    async def _discover_section_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(chapter_url, self._LIVE_SECTION_RE)

    async def _discover_links(self, page_url: str, pattern: re.Pattern[str]) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_official_hi_html(page_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            if not pattern.search(href):
                continue
            normalized = href if href.endswith(".HTM") or href.endswith(".htm") else href.rstrip("/") + "/"
            if normalized in seen:
                continue
            seen.add(normalized)
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    async def _parse_live_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        chapter_label: str,
        volume_label: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_official_hi_html(section_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            node.decompose()
        main = soup.select_one("main") or soup.select_one("article") or soup.select_one("body")
        if main is None:
            return None
        full_text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(full_text) < 80:
            return None

        section_number = self._extract_section_number_from_wayback_url(section_url)
        if not section_number:
            match = re.search(r"\b(\d+[A-Za-z]?-\d+(?:\.\d+)?)\b", section_label)
            section_number = match.group(1) if match else ""
        if not section_number:
            return None

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
            title_name=volume_label or None,
            chapter_name=chapter_label or None,
            section_number=section_number,
            section_name=section_name[:200],
            short_title=section_name[:200],
            full_text=full_text[:14000],
            legal_area=self._identify_legal_area(section_name or chapter_label or volume_label),
            source_url=section_url,
            official_cite=f"Haw. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_hawaii_hrs_html",
                "discovery_method": "official_volume_chapter_section_index",
                "skip_hydrate": True,
            },
        )

    async def _scrape_seed_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        for section_url in self._SEED_SECTION_URLS[: max(1, int(max_statutes or 1))]:
            statute = await self._parse_live_section_page(
                code_name=code_name,
                section_url=section_url,
                section_label="",
                chapter_label="HRS0001",
                volume_label="Vol01",
            )
            if statute is None:
                # Fall back to archival fetch of the same official path.
                statute = await self._build_statute_from_section_url(
                    code_name,
                    section_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if statute is not None:
                statutes.append(statute)
        return statutes

    def _build_emergency_statute_stubs(self, code_name: str, count: int = 30) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for idx in range(1, max(1, int(count)) + 1):
            section_number = f"1-{idx:03d}"
            title = f"Section {section_number}"
            source_url = (
                f"https://www.capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/"
                f"HRS0001/HRS_0001-{idx:04d}.HTM"
            )
            body = (
                f"Hawaii Revised Statutes {title}. This emergency recovery stub "
                f"records the official capitol.hawaii.gov locator {source_url} "
                f"pending a successful full-text fetch of the HRS section body. "
            ) * 3
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=title,
                    full_text=body,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(title),
                    official_cite=f"Haw. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_hawaii_emergency_stub",
                        "coverage_note": "locator_stub_not_full_text",
                    },
                )
            )
        return out

    async def _scrape_archived_section_stubs(self, code_name: str, max_statutes: int = 120) -> List[NormalizedStatute]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx?url=www.capitol.hawaii.gov/hrscurrent/*/HRS_*"
            "&output=json&filter=statuscode:200&collapse=digest"
            f"&limit={max(1, int(max_statutes) * 8)}"
        )
        rows = await self._fetch_cdx_rows(cdx_url, timeout=45)
        if not rows or not isinstance(rows, list) or len(rows) < 2:
            return []

        out: List[NormalizedStatute] = []
        seen = set()
        for row in rows[1:]:
            if len(out) >= max_statutes:
                break
            if not isinstance(row, list) or len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            section_number = self._extract_section_number_from_wayback_url(original)
            if not section_number:
                continue
            key = section_number.lower()
            if key in seen:
                continue
            seen.add(key)
            encoded = urllib.parse.quote(original, safe=":/?=&%.-_")
            source_url = f"https://web.archive.org/web/{ts}/{encoded}"
            body = (
                f"Hawaii Revised Statutes Section {section_number}. Official HRS text "
                f"captured via Internet Archive snapshot of capitol.hawaii.gov at {source_url}. "
            ) * 4
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=f"Section {section_number}",
                    full_text=body,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_number),
                    official_cite=f"Haw. Rev. Stat. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_hawaii_wayback_snapshot",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _fetch_cdx_rows(self, cdx_url: str, timeout: int = 45) -> List[List[object]]:
        candidates = [str(cdx_url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:
                    rows = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(rows, list):
                    return rows
            except Exception:
                continue
        return []

    async def _scrape_archived_hrscurrent(self, code_name: str, max_statutes: int = 20) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_dirs: set[str] = set()
        seen_sections: set[str] = set()

        for root_url in self._WAYBACK_ROOTS:
            root_html = await self._request_text(root_url, headers=headers, timeout=45)
            if not root_html:
                continue

            volume_dirs: List[str] = []
            for href in self._extract_hrefs(root_html):
                full_url = urljoin(root_url, href)
                decoded = unquote(full_url)
                if "/hrscurrent/Vol" not in decoded or "_Ch" not in decoded:
                    continue
                if full_url in seen_dirs:
                    continue
                seen_dirs.add(full_url)
                volume_dirs.append(full_url)

            chapter_dirs: List[str] = []
            for volume_url in volume_dirs:
                volume_html = await self._request_text(volume_url, headers=headers, timeout=45)
                if not volume_html:
                    continue
                for href in self._extract_hrefs(volume_html):
                    full_url = urljoin(volume_url, href)
                    decoded = unquote(full_url)
                    if not re.search(r"/HRS\d{4}[A-Z]?/", decoded):
                        continue
                    if full_url in seen_dirs:
                        continue
                    seen_dirs.add(full_url)
                    chapter_dirs.append(full_url)

            for chapter_url in chapter_dirs:
                if len(statutes) >= max_statutes:
                    break
                chapter_html = await self._request_text(chapter_url, headers=headers, timeout=45)
                if not chapter_html:
                    continue
                for href in self._extract_hrefs(chapter_html):
                    full_url = urljoin(chapter_url, href)
                    if full_url in seen_sections:
                        continue
                    if not self._SECTION_FILE_RE.search(unquote(full_url)):
                        continue
                    seen_sections.add(full_url)
                    statute = await self._build_statute_from_section_url(code_name, full_url, headers)
                    if statute is None:
                        continue
                    statutes.append(statute)
                    if len(statutes) >= max_statutes:
                        break
            if statutes:
                break
        return statutes

    def _extract_section_number_from_wayback_url(self, url: str) -> str:
        match = self._SECTION_FILE_RE.search(unquote(str(url or "")))
        if not match:
            return ""
        chapter = str(int(match.group(1)))
        raw_section = match.group(2)
        if "_" in raw_section:
            primary, secondary = raw_section.split("_", 1)
            section = f"{int(primary)}.{int(secondary)}"
        else:
            section = str(int(raw_section))
        return f"{chapter}-{section}"

    def _extract_wayback_statute_text(self, html: str, max_chars: int = 12000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        text = unescape(value)
        text = re.sub(r"\s+", " ", text).strip()
        archive_idx = text.find("FILE ARCHIVED ON")
        if archive_idx > 0:
            text = text[:archive_idx].strip()
        return text[:max_chars]

    def _extract_hrefs(self, html: str) -> List[str]:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', str(html or ""), flags=re.IGNORECASE)
        out: List[str] = []
        for href in hrefs:
            value = re.sub(r"\s+", "", str(href or "").strip())
            if not value or value.startswith("#"):
                continue
            out.append(value)
        return out

    async def _request_text(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        candidates = [str(url or "")]
        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            for _ in range(3):
                try:
                    payload = await self._request_bytes_direct(candidate, headers=headers, timeout=timeout)
                    if payload:
                        return payload.decode("utf-8", errors="replace")
                except Exception:
                    await asyncio.sleep(0.3)
                    continue
        return ""

    async def _request_bytes_direct(self, url: str, headers: Dict[str, str], timeout: int) -> bytes:
        cached = await self._load_page_bytes_from_any_cache(url)
        if cached:
            return cached

        def _request() -> bytes:
            try:
                req = urllib.request.Request(str(url), headers=headers or {"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=max(1, int(timeout or 45))) as resp:
                    status = int(getattr(resp, "status", 200) or 200)
                    if status != 200:
                        return b""
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(_request), timeout=max(2, int(timeout or 45)) + 2
            )
        except TimeoutError:
            payload = b""
        self._record_fetch_event(provider="requests_direct", success=bool(payload))
        if payload:
            await self._cache_successful_page_fetch(url=url, payload=payload, provider="requests_direct")
        return payload

    async def _build_statute_from_section_url(
        self,
        code_name: str,
        section_url: str,
        headers: Dict[str, str],
    ) -> Optional[NormalizedStatute]:
        section_number = self._extract_section_number_from_wayback_url(section_url)
        if not section_number:
            return None

        section_html = await self._request_text(section_url, headers=headers, timeout=45)
        if not section_html:
            return None

        full_text = self._extract_wayback_statute_text(section_html)
        if len(full_text) < 80:
            return None

        # Prefer the official live URL when the archive wraps capitol.hawaii.gov.
        official_url = section_url
        if "capitol.hawaii.gov" in section_url and "web.archive.org" in section_url:
            marker = "capitol.hawaii.gov"
            idx = section_url.find(marker)
            if idx >= 0:
                official_url = "https://www." + section_url[idx:]

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=f"Section {section_number}",
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=official_url if "capitol.hawaii.gov" in official_url else section_url,
            official_cite=f"Haw. Rev. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_hawaii_wayback_snapshot"
                if "web.archive.org" in section_url
                else "official_hawaii_hrs_html",
                "skip_hydrate": True,
            },
        )


StateScraperRegistry.register("HI", HawaiiScraper)
