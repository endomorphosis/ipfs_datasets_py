"""Scraper for Pennsylvania state laws.

This module contains the scraper for Pennsylvania statutes from the
official Pennsylvania General Assembly statutes portal.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import re
import subprocess
import urllib.parse
import urllib.request
from typing import List, Dict, Optional, Tuple
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class PennsylvaniaScraper(BaseStateScraper):
    """Scraper for Pennsylvania state laws from https://www.legis.state.pa.us"""

    _SECTION_HEADER_RE = re.compile(r"(?m)^\s*§\s*([0-9A-Za-z.-]+)\.\s+(.+)$")
    
    def get_base_url(self) -> str:
        """Return the base URL for Pennsylvania's legislative website."""
        return "https://www.palegis.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Pennsylvania."""
        return [{
            "name": "Pennsylvania Consolidated Statutes",
            "url": f"{self.get_base_url()}/statutes/consolidated",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Pennsylvania's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        return_threshold = limit if limit is not None else 1000000

        official_pdf_sections = await self._scrape_consolidated_title_pdfs(
            code_name=code_name,
            max_statutes=return_threshold,
        )
        if official_pdf_sections:
            return official_pdf_sections[:return_threshold]

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/consolidated",
            "https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://law.justia.com/codes/pennsylvania/",
            "https://web.archive.org/web/20250201000000/https://www.palegis.us/statutes/consolidated",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        if not self._full_corpus_enabled():
            direct_statutes = await self._scrape_direct_titles(
                code_name,
                max_statutes=return_threshold,
            )
            if direct_statutes:
                if limit is not None:
                    return direct_statutes[:limit]
                return direct_statutes

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(
                code_name,
                candidate,
                "Pa. Cons. Stat.",
                max_sections=return_threshold,
            )
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged[:return_threshold]

        return merged

    async def _scrape_consolidated_title_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        discovered = await self._discover_consolidated_title_pdfs(limit=max(4, int(max_statutes or 1)))
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections: set[Tuple[str, str]] = set()
        for title_number, title_name, pdf_url in discovered:
            if len(statutes) >= max_statutes:
                break
            pdf_bytes = await self._request_pdf_bytes(pdf_url, timeout=60)
            if not pdf_bytes:
                continue
            title_text = self._extract_pdf_text_preserve_layout(pdf_bytes=pdf_bytes, max_chars=900000)
            if len(title_text) < 500:
                continue
            split_sections = self._split_title_pdf_into_sections(
                code_name=code_name,
                title_number=title_number,
                title_name=title_name,
                title_text=title_text,
                source_url=pdf_url,
            )
            for statute in split_sections:
                section_number = str(statute.section_number or "").strip()
                key = (str(title_number or "").strip(), section_number)
                if not section_number or key in seen_sections:
                    continue
                seen_sections.add(key)
                statutes.append(statute)
                if len(statutes) >= max_statutes:
                    break
        return statutes

    async def _discover_consolidated_title_pdfs(self, limit: int = 120) -> List[Tuple[str, str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/consolidated"
        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=45)
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        discovered: List[Tuple[str, str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            text = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if not href or not text:
                continue
            if text.lower() in {"html", "pdf", "microsoft word"}:
                continue
            if "/statutes/consolidated/view-statute?" not in href or "txtType=HTM" not in href:
                continue

            absolute = urllib.parse.urljoin(index_url, href)
            parsed = urllib.parse.urlparse(absolute)
            query = urllib.parse.parse_qs(parsed.query)
            title_number = str((query.get("ttl") or [""])[0]).strip()
            if not title_number or title_number == "0" or title_number in seen:
                continue
            seen.add(title_number)
            pdf_query = dict((k, v[-1] if isinstance(v, list) else v) for k, v in query.items())
            pdf_query["txtType"] = "PDF"
            pdf_url = urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(pdf_query, doseq=False))
            )
            discovered.append((title_number, text[:240], pdf_url))
            if len(discovered) >= limit:
                break
        return discovered

    async def _request_pdf_bytes(self, url: str, timeout: int = 45) -> bytes:
        def _request() -> bytes:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return bytes(resp.read() or b"")
            except Exception:
                return b""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 5)
        except Exception:
            return b""

    def _extract_pdf_text_preserve_layout(self, pdf_bytes: bytes, max_chars: int) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""

        if proc.returncode != 0 or not proc.stdout:
            return ""
        return proc.stdout.decode("utf-8", errors="ignore")[:max_chars]

    def _split_title_pdf_into_sections(
        self,
        code_name: str,
        title_number: str,
        title_name: str,
        title_text: str,
        source_url: str,
    ) -> List[NormalizedStatute]:
        matches = list(self._SECTION_HEADER_RE.finditer(title_text or ""))
        if not matches:
            return []

        # The title PDFs begin with a table of contents, so prefer the second
        # appearance of the earliest repeated section number when present.
        starts_by_section: Dict[str, List[re.Match[str]]] = {}
        for match in matches:
            starts_by_section.setdefault(match.group(1), []).append(match)

        body_start = 0
        for match in matches:
            repeats = starts_by_section.get(match.group(1)) or []
            if len(repeats) >= 2:
                body_start = repeats[1].start()
                break

        body_matches = [match for match in matches if match.start() >= body_start]
        if not body_matches:
            body_matches = matches

        statutes: List[NormalizedStatute] = []
        for index, match in enumerate(body_matches):
            section_number = str(match.group(1) or "").strip()
            section_name = re.sub(r"\s+", " ", str(match.group(2) or "").strip()).strip(" .")
            end = body_matches[index + 1].start() if index + 1 < len(body_matches) else len(title_text)
            raw_block = title_text[match.start():end]
            normalized = self._normalize_legal_text(raw_block)
            if len(normalized) < 60:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} tit. {title_number} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:240] or f"Section {section_number}",
                    full_text=normalized[:24000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(f"{title_name} {section_name}"),
                    official_cite=f"Pa. Cons. Stat. tit. {title_number} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_pennsylvania_title_pdf",
                        "discovery_method": "official_consolidated_title_pdf_index",
                        "title_number": title_number,
                        "title_name": title_name,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _scrape_direct_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        urls = [
            "https://www.palegis.us/statutes/consolidated/view-statute?txtType=PDF&ttl=01",
            "https://www.palegis.us/statutes/consolidated/view-statute?txtType=PDF&ttl=18",
        ]
        out: List[NormalizedStatute] = []
        for source_url in urls[: max(1, int(max_statutes or 1))]:
            payload = await self._request_pdf_bytes(source_url, timeout=18)
            text = self._extract_pdf_text_preserve_layout(payload, max_chars=22000)
            text = self._normalize_legal_text(text)
            if len(text) < 280:
                continue
            title_match = re.search(r"\bTITLE\s+(\d+)\b", text, re.IGNORECASE)
            title_number = title_match.group(1) if title_match else str(len(out) + 1)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=f"Title {title_number}",
                    full_text=text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(text[:1200]),
                    official_cite=f"Pa. Cons. Stat. tit. {title_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_title", "skip_hydrate": True},
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("PA", PennsylvaniaScraper)
