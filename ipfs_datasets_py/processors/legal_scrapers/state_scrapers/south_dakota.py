"""Scraper for South Dakota state laws.

This module contains the scraper for South Dakota statutes from the official
JSON statute endpoint.
"""

import os
import re
import json
import time
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class SouthDakotaScraper(BaseStateScraper):
    """Scraper for South Dakota state laws from https://sdlegislature.gov"""

    _SEED_SECTIONS = [
        "1-1-1",
        "1-1-1.1",
        "1-1-2",
        "1-1-3",
        "1-1-4",
        "1-1-5",
        "1-1-6",
        "1-1-7",
    ]

    _TITLE_START_SECTIONS = [f"{title}-1-1" for title in range(1, 75)]
    
    def get_base_url(self) -> str:
        """Return the base URL for South Dakota's legislative website."""
        return "https://sdlegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for South Dakota."""
        return [{
            "name": "South Dakota Codified Laws",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from South Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=160)
        max_api_statutes = limit if limit is not None else None
        api_statutes = await self._scrape_statutes_api(
            code_name=code_name,
            max_statutes=max_api_statutes,
        )
        if api_statutes:
            self.logger.info(f"South Dakota API scrape: Scraped {len(api_statutes)} sections")
            return api_statutes

        max_sections = limit if limit is not None else 1000000
        return await self._generic_scrape(code_name, code_url, "S.D. Codified Laws", max_sections=max_sections)

    async def _scrape_statutes_api(self, code_name: str, max_statutes: Optional[int]) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        statutes: List[NormalizedStatute] = []
        seen = set()
        pending = list(self._SEED_SECTIONS + self._TITLE_START_SECTIONS)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        last_progress_log_ts = 0.0
        checkpoint = _SouthDakotaCheckpoint(self.state_code)

        while pending:
            if limit is not None and len(statutes) >= limit:
                break
            section = str(pending.pop(0) or "").strip()
            if section in seen:
                continue
            seen.add(section)

            data = await self._request_json(
                f"https://sdlegislature.gov/api/Statutes/Statute/{section}",
                headers=headers,
                timeout=35,
            )
            if not data:
                continue

            next_section = str(data.get("Next") or "").strip()
            if next_section and next_section not in seen:
                pending.insert(0, next_section)

            html = str(data.get("Html") or "")
            full_text = self._clean_html_text(html)
            if len(full_text) < 280:
                continue

            section_number = str(data.get("Statute") or section)
            section_name = str(data.get("CatchLine") or f"Section {section_number}").strip()

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:180],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(full_text),
                    source_url=f"https://sdlegislature.gov/api/Statutes/Statute/{section_number}",
                    official_cite=f"S.D. Codified Laws {section_number}",
                )
            )

            now = time.time()
            if len(statutes) == 1 or len(statutes) % 500 == 0 or now - last_progress_log_ts >= 60:
                self.logger.info(
                    "South Dakota API scrape: statutes_so_far=%s current_section=%s next_section=%s",
                    len(statutes),
                    section_number,
                    next_section or "",
                )
                last_progress_log_ts = now
            checkpoint.maybe_write(statutes, section_number=section_number)

        checkpoint.write(statutes, section_number="complete")
        return statutes

    async def _request_json(self, url: str, headers: Dict[str, str], timeout: int) -> Dict:
        try:
            import requests

            response = requests.get(url, headers=headers, timeout=timeout)
            self._record_fetch_event(provider="requests_direct", success=response.ok)
            if response.ok:
                data = self._parse_json_payload(response.content)
                if isinstance(data, dict):
                    return data
        except Exception:
            self._record_fetch_event(provider="requests_direct", success=False)

        for _ in range(3):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    url,
                    timeout_seconds=timeout,
                )
                if not payload:
                    raise ValueError("empty response")
                data = self._parse_json_payload(payload)
                if isinstance(data, dict):
                    return data
            except Exception:
                time.sleep(0.5)
                continue
        return {}

    def _parse_json_payload(self, payload: bytes) -> Dict:
        try:
            import json

            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
        return {}

    def _clean_html_text(self, html: str, max_chars: int = 14000) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        value = unescape(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()[:max_chars]


# Register this scraper with the registry
StateScraperRegistry.register("SD", SouthDakotaScraper)


class _SouthDakotaCheckpoint:
    """Best-effort partial progress checkpoint for South Dakota API crawls."""

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

    def maybe_write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        count = len(statutes)
        if not self.path or count <= 0:
            return
        if count - self.last_count < self.interval and time.time() - self.last_write_ts < 120:
            return
        self.write(statutes, section_number=section_number)

    def write(self, statutes: List[NormalizedStatute], *, section_number: str) -> None:
        if not self.path or not statutes:
            return
        payload = {
            "state_code": self.state_code,
            "updated_at": time.time(),
            "statutes_count": len(statutes),
            "section_number": section_number,
            "statutes": [statute.to_dict() for statute in statutes],
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)
        self.last_count = len(statutes)
        self.last_write_ts = time.time()
