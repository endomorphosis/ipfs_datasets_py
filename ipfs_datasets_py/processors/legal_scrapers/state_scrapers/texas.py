"""Texas state law scraper.

Scrapes laws from the Texas Legislature Online website
(https://statutes.capitol.texas.gov/).
"""

import io
import json
from typing import List, Dict, Optional
import re
import zipfile
from html import unescape
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


_TAC_SECTION_RE = re.compile(r"(?:§\s*)?([0-9]+\.[0-9]+)")
_META_REFRESH_URL_RE = re.compile(r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+content=[\"'][^\"']*url=([^\"'>]+)", re.IGNORECASE)
_TEXAS_SECTION_START_RE = re.compile(r"(?m)\bSec\.\s+([0-9A-Za-z.:-]+)\.\s+([A-Z0-9][^\n]{0,220})")


def _norm_space(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_meta_refresh_target(html: str) -> Optional[str]:
    match = _META_REFRESH_URL_RE.search(str(html or ""))
    if not match:
        return None
    value = _norm_space(match.group(1))
    return value or None


class TexasScraper(BaseStateScraper):
    """Scraper for Texas state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for Texas statutes."""
        return "https://statutes.capitol.texas.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Texas codes.
        
        Texas organizes its laws into codes.
        """
        base_url = self.get_base_url()
        
        codes = [
            {
                "name": "Texas Administrative Code",
                "url": "https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
                "type": "Regulation",
            },
            {"name": "Agriculture Code", "url": f"{base_url}/Docs/AG/htm/AG.1.htm", "type": "AG"},
            {"name": "Alcoholic Beverage Code", "url": f"{base_url}/Docs/AL/htm/AL.1.htm", "type": "AL"},
            {"name": "Business and Commerce Code", "url": f"{base_url}/Docs/BC/htm/BC.1.htm", "type": "BC"},
            {"name": "Civil Practice and Remedies Code", "url": f"{base_url}/Docs/CP/htm/CP.1.htm", "type": "CP"},
            {"name": "Code of Criminal Procedure", "url": f"{base_url}/Docs/CR/htm/CR.1.htm", "type": "CR"},
            {"name": "Education Code", "url": f"{base_url}/Docs/ED/htm/ED.1.htm", "type": "ED"},
            {"name": "Election Code", "url": f"{base_url}/Docs/EL/htm/EL.1.htm", "type": "EL"},
            {"name": "Family Code", "url": f"{base_url}/Docs/FA/htm/FA.1.htm", "type": "FA"},
            {"name": "Finance Code", "url": f"{base_url}/Docs/FI/htm/FI.1.htm", "type": "FI"},
            {"name": "Government Code", "url": f"{base_url}/Docs/GV/htm/GV.1.htm", "type": "GV"},
            {"name": "Health and Safety Code", "url": f"{base_url}/Docs/HS/htm/HS.1.htm", "type": "HS"},
            {"name": "Human Resources Code", "url": f"{base_url}/Docs/HR/htm/HR.1.htm", "type": "HR"},
            {"name": "Insurance Code", "url": f"{base_url}/Docs/IN/htm/IN.1.htm", "type": "IN"},
            {"name": "Labor Code", "url": f"{base_url}/Docs/LA/htm/LA.1.htm", "type": "LA"},
            {"name": "Local Government Code", "url": f"{base_url}/Docs/LG/htm/LG.1.htm", "type": "LG"},
            {"name": "Natural Resources Code", "url": f"{base_url}/Docs/NR/htm/NR.1.htm", "type": "NR"},
            {"name": "Occupations Code", "url": f"{base_url}/Docs/OC/htm/OC.1.htm", "type": "OC"},
            {"name": "Parks and Wildlife Code", "url": f"{base_url}/Docs/PW/htm/PW.1.htm", "type": "PW"},
            {"name": "Penal Code", "url": f"{base_url}/Docs/PE/htm/PE.1.htm", "type": "PE"},
            {"name": "Property Code", "url": f"{base_url}/Docs/PR/htm/PR.1.htm", "type": "PR"},
            {"name": "Tax Code", "url": f"{base_url}/Docs/TX/htm/TX.1.htm", "type": "TX"},
            {"name": "Transportation Code", "url": f"{base_url}/Docs/TN/htm/TN.1.htm", "type": "TN"},
            {"name": "Utilities Code", "url": f"{base_url}/Docs/UT/htm/UT.1.htm", "type": "UT"},
            {"name": "Water Code", "url": f"{base_url}/Docs/WA/htm/WA.1.htm", "type": "WA"},
        ]
        
        return codes
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific Texas code.
        
        Args:
            code_name: Name of the code
            code_url: URL to the code
            
        Returns:
            List of normalized statutes
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            lower_name = str(code_name or "").lower()
            lower_url = str(code_url or "").lower()
            limit = self._effective_scrape_limit(max_statutes, default=120)
            if "administrative" in lower_name or "readtac" in lower_url:
                return await self._scrape_texas_admin_code(
                    code_name=code_name,
                    code_url=code_url,
                    max_statutes=limit,
                )

            bundled_statutes = await self._scrape_statute_html_zip(
                code_name=code_name,
                code_url=code_url,
                max_statutes=limit,
            )
            if bundled_statutes:
                self.logger.info(f"Scraped {len(bundled_statutes)} sections from official Texas HTML zip for {code_name}")
                return bundled_statutes

            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                raise RuntimeError(f"empty response for {code_url}")

            page_html = page_bytes.decode("utf-8", errors="replace")
            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Parse Texas Legislature's structure
            # Texas uses a specific HTML structure for their statutes
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)
            
            # Find section links
            section_links = soup.find_all('a', href=re.compile(r'.*\.htm', re.IGNORECASE))
            if not section_links:
                # Try finding any links
                fallback_link_limit = None if limit is None else 100
                section_links = soup.find_all('a', href=True, limit=fallback_link_limit)

            page_full_text = self._extract_text_from_html(page_html)
            seen_section_numbers = set()
            
            scan_links = section_links if limit is None else section_links[: max(120, int(limit) * 5)]
            for i, link in enumerate(scan_links):
                if limit is not None and len(statutes) >= int(limit):
                    break
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    from urllib.parse import urljoin
                    section_url = urljoin(code_url, section_url)
                
                # Extract section number
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    section_number = f"{i+1}"

                if section_number in seen_section_numbers:
                    continue

                section_full_text = await self._fetch_section_text(section_url=section_url, fallback_text=page_full_text)
                if len(section_full_text) < 280:
                    continue

                seen_section_numbers.add(section_number)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=section_full_text,
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"Tex. {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)

            # Fallback: emit a code-level record if section links are sparse.
            if not statutes and len(page_full_text) >= 280:
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § 1",
                        code_name=code_name,
                        section_number="1",
                        section_name=f"{code_name} (code-level)",
                        full_text=page_full_text,
                        source_url=code_url,
                        legal_area=legal_area,
                        official_cite=f"Tex. {code_name}",
                        metadata=StatuteMetadata(),
                    )
                )
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes

    async def _scrape_statute_html_zip(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        code_abbrev = self._derive_code_abbrev(code_name=code_name, code_url=code_url)
        if not code_abbrev:
            return []

        zip_url = await self._resolve_code_html_zip_url(code_abbrev)
        if not zip_url:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(zip_url, timeout_seconds=90)
        if not payload or not zipfile.is_zipfile(io.BytesIO(payload)):
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = sorted(
                name for name in archive.namelist()
                if name.lower().endswith((".htm", ".html")) and not name.endswith("/")
            )
            for file_index, member_name in enumerate(names, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                try:
                    html = archive.read(member_name).decode("utf-8-sig", errors="replace")
                except Exception:
                    continue
                chapter_statutes = self._parse_texas_chapter_html(
                    html=html,
                    code_name=code_name,
                    code_abbrev=code_abbrev,
                    member_name=member_name,
                    zip_url=zip_url,
                    seen_sections=seen_sections,
                    remaining=None if limit is None else max(0, limit - len(statutes)),
                )
                statutes.extend(chapter_statutes)
                if len(statutes) == 1 or len(statutes) % 500 == 0 or file_index == len(names):
                    self.logger.info(
                        "Texas official zip scrape: code=%s chapters=%s/%s statutes_so_far=%s",
                        code_abbrev,
                        file_index,
                        len(names),
                        len(statutes),
                    )

        return statutes[:limit] if limit is not None else statutes

    async def _resolve_code_html_zip_url(self, code_abbrev: str) -> str:
        default_url = f"https://tcss.legis.texas.gov/resources/Zips/{code_abbrev}.htm.zip"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                "https://statutes.capitol.texas.gov/assets/StatuteCodeDownloads.json",
                timeout_seconds=30,
            )
            data = json.loads(payload.decode("utf-8-sig", errors="replace")) if payload else {}
        except Exception:
            data = {}
        rows = data.get("StatuteCode") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("code") or "").upper() != code_abbrev.upper():
                    continue
                html_path = str(row.get("Html") or "").strip()
                if html_path:
                    return "https://tcss.legis.texas.gov/resources/" + html_path.lstrip("/")
        return default_url

    def _parse_texas_chapter_html(
        self,
        *,
        html: str,
        code_name: str,
        code_abbrev: str,
        member_name: str,
        zip_url: str,
        seen_sections: set[str],
        remaining: Optional[int],
    ) -> List[NormalizedStatute]:
        text = self._extract_text_from_html(html, max_chars=1_000_000)
        if len(text) < 280:
            return []

        title_match = re.search(r"\bTITLE\s+([0-9A-Za-z.-]+)\.\s+([^\n]+)", text)
        chapter_match = re.search(r"\bCHAPTER\s+([0-9A-Za-z.-]+)\.\s+([^\n]+)", text)
        title_number = title_match.group(1) if title_match else None
        title_name = _norm_space(title_match.group(2))[:200] if title_match else None
        chapter_number = chapter_match.group(1) if chapter_match else self._derive_chapter_number_from_member(member_name)
        chapter_name = _norm_space(chapter_match.group(2))[:200] if chapter_match else None

        matches = list(_TEXAS_SECTION_START_RE.finditer(text))
        statutes: List[NormalizedStatute] = []
        for index, match in enumerate(matches):
            if remaining is not None and len(statutes) >= remaining:
                break
            section_number = match.group(1).strip().rstrip(".")
            if not section_number or section_number in seen_sections:
                continue
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section_text = _norm_space(text[start:end])
            if len(section_text) < 120:
                continue
            section_name = _norm_space(match.group(2)).rstrip(".")[:200]
            seen_sections.add(section_number)
            official_member = re.sub(
                rf"^{re.escape(code_abbrev.lower())}\.",
                f"{code_abbrev}.",
                member_name,
                flags=re.IGNORECASE,
            )
            source_url = f"https://statutes.capitol.texas.gov/Docs/{code_abbrev}/htm/{official_member}#{section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name,
                    chapter_number=chapter_number,
                    chapter_name=chapter_name,
                    section_number=section_number,
                    section_name=section_name,
                    short_title=section_name,
                    full_text=section_text[:14000],
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_name or section_text),
                    official_cite=f"Tex. {code_name} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_texas_statutes_html_zip",
                        "zip_url": zip_url,
                        "zip_member": member_name,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _derive_code_abbrev(self, *, code_name: str, code_url: str) -> str:
        url_match = re.search(r"/Docs/([A-Z0-9]{2})/", str(code_url or ""), re.IGNORECASE)
        if url_match:
            return url_match.group(1).upper()
        normalized_name = _norm_space(code_name).lower()
        for row in self.get_code_list():
            if _norm_space(row.get("name", "")).lower() == normalized_name:
                value = str(row.get("type") or "").strip().upper()
                if value and value != "REGULATION":
                    return value
        return ""

    def _derive_chapter_number_from_member(self, member_name: str) -> Optional[str]:
        match = re.search(r"\.([0-9A-Za-z.-]+)\.html?$", str(member_name or ""), re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    async def _scrape_texas_admin_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes: List[NormalizedStatute] = []
        seen_urls = set()

        try:
            index_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=40,
            )
            if not index_bytes:
                return []

            index_html = index_bytes.decode("utf-8", errors="replace")
            original_index_html = index_html
            fetch_url = code_url
            migrated_url = _extract_meta_refresh_target(index_html)
            if migrated_url:
                migrated_bytes = await self._fetch_page_content_with_archival_fallback(
                    migrated_url,
                    timeout_seconds=45,
                )
                if migrated_bytes:
                    index_html = migrated_bytes.decode("utf-8", errors="replace")
                    fetch_url = migrated_url

            index_soup = BeautifulSoup(index_html, "html.parser")

            candidate_links: List[tuple[str, str]] = []
            for anchor in index_soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                href_lower = href.lower()
                if "readtac" not in href_lower and "rules-and-meetings" not in href_lower and "interface=" not in href_lower:
                    continue
                absolute_url = urljoin(fetch_url, href)
                link_text = _norm_space(anchor.get_text(" ", strip=True))
                if not link_text:
                    link_text = "Texas Administrative Code"
                candidate_links.append((link_text, absolute_url))

            if not candidate_links:
                self.logger.info(
                    "Texas Administrative Code landing page exposed no direct rule links; returning no substantive sections"
                )
                return []

            limit = max_statutes if max_statutes is not None else len(candidate_links)
            for idx, (link_text, link_url) in enumerate(candidate_links[: max(1, int(limit))], start=1):
                if link_url in seen_urls:
                    continue
                seen_urls.add(link_url)

                payload = await self._fetch_page_content_with_archival_fallback(
                    link_url,
                    timeout_seconds=35,
                )
                if not payload:
                    continue
                html = payload.decode("utf-8", errors="replace")
                full_text = self._extract_text_from_html(html)
                if len(full_text) < 280:
                    continue

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    match = _TAC_SECTION_RE.search(link_text)
                    section_number = match.group(1) if match else f"{idx}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=str(section_number),
                        section_name=link_text[:200],
                        full_text=full_text,
                        source_url=link_url,
                        legal_area="administrative",
                        official_cite=f"Tex. Admin. Code § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

            if not statutes:
                self.logger.info(
                    "Texas Administrative Code bootstrap produced no substantive sections from %s",
                    fetch_url,
                )

            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            return statutes

        except Exception as exc:
            self.logger.error(f"Failed to scrape Texas Administrative Code: {exc}")
            return []

    async def _fetch_section_text(self, section_url: str, fallback_text: str) -> str:
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                section_url,
                timeout_seconds=25,
            )
            if not payload:
                return fallback_text
            text = self._extract_text_from_html(payload.decode("utf-8", errors="replace"))
            if len(text) >= 280:
                return text
        except Exception:
            pass

        return fallback_text

    def _extract_text_from_html(self, html: str, max_chars: int = 14000) -> str:
        value = str(html or "")
        value = re.sub(r'(?is)<script[^>]*>.*?</script>', ' ', value)
        value = re.sub(r'(?is)<style[^>]*>.*?</style>', ' ', value)
        value = re.sub(r'(?is)<br\s*/?>', '\n', value)
        value = re.sub(r'(?is)</p>', '\n', value)
        value = re.sub(r'(?is)<[^>]+>', ' ', value)
        value = unescape(value).replace('\xa0', ' ')
        value = re.sub(r'[ \t]+', ' ', value)
        value = re.sub(r'\s*\n\s*', '\n', value)
        value = re.sub(r'\n{3,}', '\n\n', value)
        return value.strip()[:max_chars]


# Register the scraper
StateScraperRegistry.register("TX", TexasScraper)
