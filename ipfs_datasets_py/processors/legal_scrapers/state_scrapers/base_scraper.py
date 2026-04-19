"""Base scraper class and normalized schema for state law scrapers.

This module provides:
1. A normalized schema for state laws across all states
2. A base scraper class that all state-specific scrapers inherit from
3. Common utilities for parsing and normalizing state law data
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
from abc import ABC, abstractmethod
from pathlib import Path
import hashlib
import inspect
from io import BytesIO
import json
import logging
import os
import re
from urllib.parse import urlparse, parse_qs, unquote

from .citation_history import extract_trailing_history_citations
from ...playwright_limiter import acquire_playwright_slot

logger = logging.getLogger(__name__)

SUBSEC_TOKEN_RE = re.compile(r"\(([0-9]+|[A-Za-z]{1,6})\)")
ROMAN_LOWER_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_UPPER_RE = re.compile(r"^[IVXLCDM]+$")
COMMON_ROMAN_LOWER = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"
}
COMMON_ROMAN_UPPER = {token.upper() for token in COMMON_ROMAN_LOWER}

USC_CITATION_RE = re.compile(r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*|sec(?:tion)?\.?\s*)?\d[\w\-\.()]*", re.IGNORECASE)
PUBLIC_LAW_CITATION_RE = re.compile(r"Pub\.?\s*L\.?\s*(?:No\.?\s*)?\d+\s*[–—−‑-]\s*\d+", re.IGNORECASE)
STAT_CITATION_RE = re.compile(r"\b\d+\s+Stat\.?\s+\d+\b", re.IGNORECASE)
SECTION_REF_RE = re.compile(r"\b(?:section|sec\.?|§{1,2})\s+[\w\-.(),\sand]+\b", re.IGNORECASE)

# Generic quality filters to reduce navigation/event link pollution.
_NAV_LABEL_HINTS = (
    "home",
    "about",
    "contact",
    "staff",
    "members",
    "member roster",
    "committee",
    "committees",
    "senate",
    "house",
    "legislature",
    "legislative council",
    "agencies",
    "agency",
    "session",
    "calendar",
    "schedule",
    "events",
    "live proceedings",
    "archived meetings",
    "search",
    "login",
    "portal",
    "news",
    "media",
    "press",
    "privacy",
    "accessibility",
    "skip to",
    "footer",
)

_STATUTE_URL_HINTS = (
    "/statute",
    "/statutes",
    "/code",
    "/codes",
    "/laws",
    "/law",
    "/chapter",
    "/title",
    "/article",
    "docname=",
    "section=",
)

_NON_HTML_DOC_RE = re.compile(r"\.(?:pdf|rtf|docx?|xlsx?|pptx?)(?:$|[?#])", re.IGNORECASE)
_PDF_HEADER_RE = re.compile(rb"^\s*%PDF-", re.IGNORECASE)
_RTF_HEADER_RE = re.compile(rb"^\s*\{\\rtf", re.IGNORECASE)
_SCAFFOLD_SECTION_TEXT_RE = re.compile(r"^\s*section\s+section-\d+\s*:", re.IGNORECASE)
_OBJECT_MOVED_HTML_RE = re.compile(
    r"<title>\s*document moved\s*</title>|<h1>\s*object moved\s*</h1>",
    re.IGNORECASE,
)
_NAV_URL_HINTS = (
    "/calendar",
    "/meeting",
    "/roster",
    "/blog",
    "/news",
    "/jobs",
    "/photos",
    "/contact",
    "/bulletin",
    "/live",
)


def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(str(os.getenv(name, "") or default))
    except Exception:
        return float(default)


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(str(os.getenv(name, "") or default))
    except Exception:
        return int(default)


@dataclass
class StatuteMetadata:
    """Metadata for a statute."""
    effective_date: Optional[str] = None
    last_amended: Optional[str] = None
    enacted_year: Optional[str] = None
    repealed: bool = False
    superseded_by: Optional[str] = None
    legislative_session: Optional[str] = None
    bill_number: Optional[str] = None
    history: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class NormalizedStatute:
    """Normalized representation of a state statute.
    
    This schema is consistent across all states, allowing for easy
    comparison and analysis of laws from different jurisdictions.
    """
    # Identification
    state_code: str  # e.g., "CA", "NY"
    state_name: str  # e.g., "California", "New York"
    statute_id: str  # Unique identifier within the state (e.g., "Penal Code § 187")
    
    # Hierarchy (for organizing statutes)
    code_name: Optional[str] = None  # e.g., "Penal Code", "Vehicle Code"
    title_number: Optional[str] = None  # Title or Part number
    title_name: Optional[str] = None  # Title or Part name
    chapter_number: Optional[str] = None
    chapter_name: Optional[str] = None
    section_number: Optional[str] = None
    section_name: Optional[str] = None
    
    # Content
    short_title: Optional[str] = None
    full_text: Optional[str] = None  # The actual text of the statute
    summary: Optional[str] = None
    
    # Classification
    legal_area: Optional[str] = None  # e.g., "criminal", "civil", "family"
    topics: List[str] = field(default_factory=list)  # e.g., ["murder", "homicide"]
    keywords: List[str] = field(default_factory=list)
    
    # Source information
    source_url: str = ""  # URL to official source
    official_cite: Optional[str] = None  # Official citation format
    
    # Metadata
    metadata: Optional[StatuteMetadata] = None
    structured_data: Dict[str, Any] = field(default_factory=dict)
    
    # Scraping metadata
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    scraper_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.metadata:
            data['metadata'] = self.metadata.to_dict()
        return data

    def __getitem__(self, key: str) -> Any:
        """Provide dict-like access for backward compatibility.

        Some legacy tests/scripts treat scraper results as dictionaries.
        """
        if hasattr(self, key):
            return getattr(self, key)

        legacy_key_map = {
            "id": "statute_id",
            "title": "short_title",
            "name": "short_title",
            "url": "source_url",
            "text": "full_text",
            "summary": "summary",
            "jsonld": "structured_data",
        }
        mapped = legacy_key_map.get(key)
        if mapped and hasattr(self, mapped):
            value = getattr(self, mapped)
            if value is not None:
                return value

        # Fallbacks for common legacy keys
        if key == "title":
            return self.short_title or self.section_name or self.statute_id
        if key == "url":
            return self.source_url
        if key in {"subsections", "preamble", "citations", "legislative_history", "parser_warnings"}:
            return (self.structured_data or {}).get(key)

        raise KeyError(key)
    
    def get_citation(self) -> str:
        """Get a standardized citation for this statute."""
        parts = []
        if self.state_code:
            parts.append(self.state_code)
        if self.code_name:
            parts.append(self.code_name)
        if self.section_number:
            parts.append(f"§ {self.section_number}")
        return " ".join(parts) if parts else self.statute_id


class BaseStateScraper(ABC):
    """Base class for state-specific law scrapers.
    
    Each state scraper inherits from this class and implements
    state-specific parsing logic while outputting normalized data.
    """
    
    def __init__(self, state_code: str, state_name: str):
        """Initialize the scraper.
        
        Args:
            state_code: Two-letter state code (e.g., "CA")
            state_name: Full state name (e.g., "California")
        """
        self.state_code = state_code
        self.state_name = state_name
        self.logger = logging.getLogger(f"{__name__}.{state_code}")
        self._fetch_analytics: Dict[str, Any] = {
            "attempted": 0,
            "success": 0,
            "providers": {},
            "fallback_count": 0,
            "cache_hits": 0,
            "cache_writes": 0,
            "fetch_cache_hits": 0,
            "fetch_cache_writes": 0,
            "last_error": None,
        }
        self._fetch_cache_enabled = self._env_bool(
            "LEGAL_SCRAPER_FETCH_CACHE_ENABLED",
            default=False,
        )
        self._fetch_cache_ttl_seconds = self._env_int(
            "LEGAL_SCRAPER_FETCH_CACHE_TTL_SECONDS",
            default=60 * 60 * 24 * 30,
        )
        self._fetch_cache_dir = Path(
            os.environ.get("LEGAL_SCRAPER_FETCH_CACHE_DIR")
            or os.environ.get("IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR")
            or (Path.home() / ".ipfs_datasets" / "legal_fetch_cache")
        )
        if self._fetch_cache_enabled:
            self._fetch_cache_dir.mkdir(parents=True, exist_ok=True)
            (self._fetch_cache_dir / "objects").mkdir(parents=True, exist_ok=True)
        self._ipfs_page_cache_enabled = self._env_bool(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED",
            default=True,
        )
        self._ipfs_page_cache_pin = self._env_bool(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN",
            default=False,
        )
        self._ipfs_page_cache_ttl_seconds = self._env_int(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_TTL_SECONDS",
            default=60 * 60 * 24 * 30,
        )
        self._ipfs_page_cache_timeout_seconds = self._env_int(
            "LEGAL_SCRAPER_IPFS_PAGE_CACHE_TIMEOUT_SECONDS",
            default=5,
        )
        self._ipfs_page_cache_metadata_dir = Path(
            os.environ.get("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR")
            or (Path.home() / ".ipfs_datasets" / "legal_page_cache")
        )
        self._ipfs_page_cache_metadata_dir.mkdir(parents=True, exist_ok=True)
        self._ipfs_page_cache_index_path = self._ipfs_page_cache_metadata_dir / "index.json"
        self._ipfs_page_cache_index = self._load_ipfs_page_cache_index()

    @staticmethod
    def _env_bool(name: str, *, default: bool) -> bool:
        raw = str(os.environ.get(name) or "").strip().lower()
        if not raw:
            return bool(default)
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(name: str, *, default: int) -> int:
        raw = str(os.environ.get(name) or "").strip()
        if not raw:
            return int(default)
        try:
            return int(raw)
        except Exception:
            return int(default)

    def _bounded_return_threshold(self, default: int) -> int:
        """Return the success threshold for candidate-loop scrapers.

        Legacy state scrapers often try several candidate URLs and only return
        early after finding a large number of section links. Bounded daemon
        probes set STATE_SCRAPER_MAX_STATUTES, so those scrapers should return
        as soon as they have the requested number of real records.
        """
        bounded = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded > 0:
            return max(1, min(int(default), bounded))
        if str(os.getenv("STATE_SCRAPER_FULL_CORPUS", "")).strip().lower() in {"1", "true", "yes", "on"}:
            return 1000000
        return int(default)

    def _full_corpus_enabled(self) -> bool:
        return str(os.getenv("STATE_SCRAPER_FULL_CORPUS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _effective_scrape_limit(
        self,
        max_statutes: Optional[int],
        *,
        default: Optional[int],
    ) -> Optional[int]:
        """Resolve a scraper limit without confusing sampling with full corpus.

        Historically many state scrapers treated ``max_statutes=None`` as a
        small sample default. That is useful for unit tests and probes, but it
        silently truncates daemon full-corpus runs. Full-corpus mode makes an
        omitted max genuinely unbounded while bounded runs keep their caps.
        """
        if max_statutes is not None:
            try:
                value = int(max_statutes)
            except Exception:
                value = 0
            if value > 0:
                return max(1, value)
        if self._full_corpus_enabled():
            return None
        if default is None:
            return None
        return max(1, int(default))

    def _load_ipfs_page_cache_index(self) -> Dict[str, Dict[str, Any]]:
        if not self._ipfs_page_cache_index_path.exists():
            return {}
        try:
            raw = self._ipfs_page_cache_index_path.read_text(encoding="utf-8").strip()
            payload = json.loads(raw) if raw else {}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_ipfs_page_cache_index(self) -> None:
        try:
            self._ipfs_page_cache_index_path.parent.mkdir(parents=True, exist_ok=True)
            self._ipfs_page_cache_index_path.write_text(
                json.dumps(self._ipfs_page_cache_index, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.logger.debug("Failed to save IPFS page cache index: %s", exc)

    @staticmethod
    def _ipfs_page_cache_key(url: str) -> str:
        normalized = str(url or "").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _fetch_cache_paths(self, url: str) -> tuple[Path, Path]:
        cache_key = self._ipfs_page_cache_key(url)
        object_path = self._fetch_cache_dir / "objects" / f"{cache_key}.bin"
        meta_path = self._fetch_cache_dir / "objects" / f"{cache_key}.json"
        return object_path, meta_path

    async def _load_page_bytes_from_fetch_cache(self, url: str) -> bytes:
        if not self._fetch_cache_enabled:
            return b""
        object_path, meta_path = self._fetch_cache_paths(url)
        if not object_path.exists() or not meta_path.exists():
            return b""
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return b""
        cached_at = float(meta.get("cached_at", 0.0) or 0.0)
        ttl_seconds = max(0, int(self._fetch_cache_ttl_seconds or 0))
        if ttl_seconds > 0 and cached_at > 0:
            age_seconds = max(0.0, datetime.now().timestamp() - cached_at)
            if age_seconds > float(ttl_seconds):
                return b""
        try:
            data = object_path.read_bytes()
        except Exception as exc:
            self.logger.debug("Fetch cache read failed for %s: %s", url, exc)
            return b""
        if data:
            self._fetch_analytics["fetch_cache_hits"] = int(self._fetch_analytics.get("fetch_cache_hits", 0) or 0) + 1
            self._fetch_analytics["cache_hits"] = int(self._fetch_analytics.get("cache_hits", 0) or 0) + 1
            return data
        return b""

    async def _store_page_bytes_in_fetch_cache(self, *, url: str, payload: bytes, provider: str) -> None:
        if not self._fetch_cache_enabled or not payload:
            return
        object_path, meta_path = self._fetch_cache_paths(url)
        try:
            object_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = object_path.with_suffix(".bin.tmp")
            tmp_path.write_bytes(payload)
            tmp_path.replace(object_path)
            meta_path.write_text(
                json.dumps(
                    {
                        "url": str(url),
                        "provider": str(provider or ""),
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "cached_at": datetime.now().timestamp(),
                        "state_code": self.state_code,
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self._fetch_analytics["fetch_cache_writes"] = int(self._fetch_analytics.get("fetch_cache_writes", 0) or 0) + 1
            self._fetch_analytics["cache_writes"] = int(self._fetch_analytics.get("cache_writes", 0) or 0) + 1
        except Exception as exc:
            self.logger.debug("Fetch cache write failed for %s: %s", url, exc)

    async def _cache_successful_page_fetch(self, *, url: str, payload: bytes, provider: str) -> None:
        await self._store_page_bytes_in_fetch_cache(url=url, payload=payload, provider=provider)
        await self._store_page_bytes_in_ipfs_cache(url=url, payload=payload, provider=provider)

    async def _load_page_bytes_from_any_cache(self, url: str) -> bytes:
        cached_bytes = await self._load_page_bytes_from_fetch_cache(url)
        if cached_bytes:
            self._record_fetch_event(provider="fetch_cache", success=True)
            return cached_bytes
        cached_bytes = await self._load_page_bytes_from_ipfs_cache(url)
        if cached_bytes:
            self._record_fetch_event(provider="ipfs_page_cache", success=True)
            await self._store_page_bytes_in_fetch_cache(url=url, payload=cached_bytes, provider="ipfs_page_cache")
            return cached_bytes
        return b""

    async def _load_page_bytes_from_ipfs_cache(self, url: str) -> bytes:
        if not self._ipfs_page_cache_enabled:
            return b""

        cache_key = self._ipfs_page_cache_key(url)
        entry = self._ipfs_page_cache_index.get(cache_key) or {}
        cid = str(entry.get("cid") or "").strip()
        if not cid:
            return b""

        cached_at = float(entry.get("cached_at", 0.0) or 0.0)
        ttl_seconds = max(0, int(self._ipfs_page_cache_ttl_seconds or 0))
        if ttl_seconds > 0 and cached_at > 0:
            age_seconds = max(0.0, datetime.now().timestamp() - cached_at)
            if age_seconds > float(ttl_seconds):
                return b""

        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router
        except Exception:
            return b""

        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(ipfs_router.cat, cid),
                timeout=max(1, int(self._ipfs_page_cache_timeout_seconds or 5)),
            )
        except asyncio.TimeoutError:
            self.logger.debug("IPFS page cache read timed out for %s", url)
            return b""
        except Exception as exc:
            self.logger.debug("IPFS page cache read failed for %s: %s", url, exc)
            return b""

        if isinstance(data, bytes) and data:
            self._fetch_analytics["cache_hits"] = int(self._fetch_analytics.get("cache_hits", 0) or 0) + 1
            return data
        return b""

    async def _store_page_bytes_in_ipfs_cache(
        self,
        *,
        url: str,
        payload: bytes,
        provider: str,
    ) -> Optional[str]:
        if not self._ipfs_page_cache_enabled or not payload:
            return None

        try:
            from ipfs_datasets_py import ipfs_backend_router as ipfs_router
        except Exception:
            return None

        try:
            cid = await asyncio.wait_for(
                asyncio.to_thread(ipfs_router.add_bytes, payload, pin=self._ipfs_page_cache_pin),
                timeout=max(1, int(self._ipfs_page_cache_timeout_seconds or 5)),
            )
        except asyncio.TimeoutError:
            self.logger.debug("IPFS page cache write timed out for %s", url)
            return None
        except Exception as exc:
            self.logger.debug("IPFS page cache write failed for %s: %s", url, exc)
            return None

        if not cid:
            return None

        cache_key = self._ipfs_page_cache_key(url)
        self._ipfs_page_cache_index[cache_key] = {
            "cid": str(cid),
            "url": str(url),
            "provider": str(provider or ""),
            "size": len(payload),
            "cached_at": datetime.now().timestamp(),
            "state_code": self.state_code,
        }
        self._save_ipfs_page_cache_index()
        self._fetch_analytics["cache_writes"] = int(self._fetch_analytics.get("cache_writes", 0) or 0) + 1
        return str(cid)
    
    @abstractmethod
    def get_base_url(self) -> str:
        """Get the base URL for the state's legislative website.
        
        Returns:
            Base URL string
        """
        pass
    
    @abstractmethod
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of available codes/titles for this state.
        
        Returns:
            List of dicts with 'name', 'url', and optionally 'code_type' keys
        """
        pass
    
    @abstractmethod
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code (e.g., Penal Code, Vehicle Code).
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL to the code
            
        Returns:
            List of NormalizedStatute objects
        """
        pass
    
    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0,
        hydrate_statute_text: bool = True,
    ) -> List[NormalizedStatute]:
        """Scrape all available codes for this state.
        
        Args:
            legal_areas: Filter by legal areas
            max_statutes: Maximum number of statutes to scrape
            rate_limit_delay: Delay between requests in seconds
            
        Returns:
            List of NormalizedStatute objects
        """
        import time
        
        all_statutes = []
        codes = self.get_code_list()
        
        self.logger.info(f"Scraping {len(codes)} codes for {self.state_name}")
        
        for code_info in codes:
            if max_statutes and len(all_statutes) >= max_statutes:
                break
            
            code_name = code_info['name']
            code_url = code_info['url']
            
            # Filter by legal area if specified
            if legal_areas:
                code_area = self._identify_legal_area(code_name)
                if code_area not in legal_areas:
                    continue
            
            try:
                self.logger.info(f"Scraping {code_name}...")
                if max_statutes:
                    remaining = max_statutes - len(all_statutes)
                    if remaining <= 0:
                        break
                else:
                    remaining = None
                scrape_code_params = inspect.signature(self.scrape_code).parameters
                if remaining is not None and "max_statutes" in scrape_code_params:
                    scrape_task = self.scrape_code(code_name, code_url, max_statutes=remaining)
                else:
                    scrape_task = self.scrape_code(code_name, code_url)
                code_timeout = _env_float("STATE_SCRAPER_CODE_TIMEOUT_SECONDS", 0.0)
                if code_timeout > 0:
                    try:
                        statutes = await asyncio.wait_for(scrape_task, timeout=code_timeout)
                    except TimeoutError:
                        self.logger.error(
                            "Timed out scraping %s after %.1f seconds",
                            code_name,
                            code_timeout,
                        )
                        statutes = []
                else:
                    statutes = await scrape_task
                if max_statutes:
                    statutes = statutes[:remaining]
                enriched_statutes: List[NormalizedStatute] = []
                for statute in statutes:
                    if isinstance(statute, NormalizedStatute):
                        if hydrate_statute_text:
                            await self._hydrate_statute_text_if_needed(statute)
                        if self._is_low_quality_statute_record(statute):
                            continue
                        enriched_statutes.append(self._enrich_statute_structure(statute))
                statutes = enriched_statutes
                
                all_statutes.extend(statutes)
                self.logger.info(f"Scraped {len(statutes)} statutes from {code_name}")
                
            except Exception as e:
                self.logger.error(f"Failed to scrape {code_name}: {e}")
            
            # Rate limiting
            time.sleep(rate_limit_delay)
        
        return all_statutes
    
    def _identify_legal_area(self, text: str) -> str:
        """Identify legal area from text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Legal area string
        """
        text_lower = text.lower()
        
        area_keywords = {
            "administrative": [
                "administrative",
                "regulation",
                "regulatory",
                "code of regulations",
                "admin code",
                "agency rule",
                "oar",
                "aac",
                "arc",
                "nmac",
            ],
            "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
            "civil": ["civil", "tort", "liability", "damages"],
            "family": ["family", "marriage", "divorce", "custody", "child"],
            "employment": ["employment", "labor", "worker", "wage"],
            "environmental": ["environmental", "pollution", "conservation"],
            "business": ["business", "corporation", "commercial", "contract"],
            "property": ["property", "real estate", "land"],
            "tax": ["tax", "revenue", "assessment"],
            "health": ["health", "medical", "healthcare"],
            "education": ["education", "school"],
            "traffic": ["traffic", "vehicle", "motor", "driving"],
            "probate": ["probate", "estate", "will", "trust"],
        }
        
        for area, keywords in area_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return area
        
        return "general"
    
    def _extract_section_number(self, text: str) -> Optional[str]:
        """Extract section number from text.
        
        Args:
            text: Text containing section reference
            
        Returns:
            Section number or None
        """
        import re
        
        # Common patterns: "Section 123", "§ 123", "§123", "Sec. 123"
        # Also support chapter/title labels and dot-prefixed identifiers (e.g., ".010").
        patterns = [
            r'§\s*(\d+[\.\-\w]*)',
            r'Section\s+(\d+[\.\-\w]*)',
            r'Sec\.\s*(\d+[\.\-\w]*)',
            r'^\s*\.(\d+[\.\-\w]*)\b',
            r'\b(\d+\-\d+[A-Za-z]?(?:\.\d+)*)\b',
            r'Title\s+(\d+[A-Za-z]?(?:\.\d+)?)\b',
            r'Chapter\s+(\d+[A-Za-z]?(?:\.\d+)?)\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return str(match.group(1)).strip().rstrip('.')
        
        return None

    def _extract_legislative_history(self, text: str) -> Dict[str, Any]:
        """Extract trailing legislative history citations from statute text.

        Returns a dictionary containing cleaned text and structured citation data.
        """
        cleaned_text, raw_blocks, citations = extract_trailing_history_citations(text)
        return {
            "cleaned_text": cleaned_text,
            "history_citation_blocks": raw_blocks,
            "history_citations": citations,
        }

    def _looks_like_shallow_stub_text(self, text: str) -> bool:
        normalized = self._normalize_legal_text(text)
        if not normalized:
            return True

        if len(normalized) < 220:
            return True

        # Many state scrapers currently seed text as "Section X: <link text>".
        if re.match(r"^(section|sec\.?|title|chapter)\s+[\w\-.]+\s*:\s*", normalized, flags=re.IGNORECASE):
            return True

        return False

    def _contains_statute_signals(self, text: str) -> bool:
        value = self._normalize_legal_text(text).lower()
        if not value:
            return False

        patterns = [
            r"\b§\s*\d",
            r"\bsec(?:tion)?\.?\s+\d",
            r"\btitle\s+\d",
            r"\bchapter\s+\d",
            r"\barticle\s+\d",
            r"\b\d+[\-\.]\d+[a-z]?\b",
        ]
        return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)

    def _looks_like_navigation_text(self, text: str) -> bool:
        value = self._normalize_legal_text(text).lower()
        if not value:
            return True

        return any(hint in value for hint in _NAV_LABEL_HINTS)

    def _is_probable_statute_link(self, link_text: str, link_url: str, code_url: str = "") -> bool:
        text = self._normalize_legal_text(link_text)
        if len(text) < 3:
            return False

        url_value = str(link_url or "").strip().lower()
        parsed = urlparse(url_value) if url_value else None
        path = (parsed.path if parsed else "") or ""

        if url_value.startswith(("mailto:", "tel:", "javascript:")):
            return False

        # Skip obvious binary/document links that cannot hydrate into statute text.
        if _NON_HTML_DOC_RE.search(url_value):
            return False

        if self._looks_like_navigation_text(text) and not self._contains_statute_signals(text):
            return False

        if parsed and path in {"", "/"} and not parsed.query:
            return False

        if code_url:
            base = urlparse(str(code_url).strip())
            same_target = (
                parsed is not None
                and parsed.scheme == base.scheme
                and parsed.netloc == base.netloc
                and parsed.path == base.path
                and parsed.query == base.query
            )
            if same_target and not self._contains_statute_signals(text):
                return False

        if self._contains_statute_signals(text):
            return True

        if any(hint in url_value for hint in _STATUTE_URL_HINTS):
            # Avoid broad index/category links (e.g., /laws, /statutes, /code)
            # unless they contain section-like signals in URL structure.
            tail = path.rstrip("/").split("/")[-1] if path else ""
            generic_tails = {
                "law", "laws", "statute", "statutes", "code", "codes",
                "constitution", "rules", "home", "index", "default.aspx",
            }
            has_structured_query = any(token in url_value for token in ("section=", "sec=", "cite=", "docname=", "law.aspx?d="))
            has_numeric_path = bool(re.search(r"\d", path or ""))
            path_depth = len([part for part in (path or "").split("/") if part])

            if (tail in generic_tails) and not (has_structured_query or has_numeric_path or path_depth >= 4):
                return False
            return True

        return False

    def _is_low_quality_statute_record(self, statute: NormalizedStatute) -> bool:
        if not isinstance(statute, NormalizedStatute):
            return False

        section_name = self._normalize_legal_text(str(statute.section_name or ""))
        full_text = self._normalize_legal_text(str(statute.full_text or ""))
        source_url = str(statute.source_url or "").strip()
        section_number = str(statute.section_number or "").strip()

        fallback_section = bool(re.match(r"^Section-\d+$", section_number, flags=re.IGNORECASE))
        has_statute_signal = (
            self._contains_statute_signals(section_name)
            or self._contains_statute_signals(full_text)
            or any(hint in source_url.lower() for hint in _STATUTE_URL_HINTS)
        )
        nav_like = self._looks_like_navigation_text(section_name) or self._looks_like_navigation_text(full_text)
        nav_url_like = any(hint in source_url.lower() for hint in _NAV_URL_HINTS)

        if _SCAFFOLD_SECTION_TEXT_RE.match(full_text):
            return True

        if fallback_section and nav_like and not has_statute_signal:
            return True

        if nav_url_like and not has_statute_signal:
            return True

        if nav_like and not has_statute_signal and len(full_text) < 400:
            return True

        return False

    def _canonicalize_statute_url(self, link_url: str) -> str:
        """Normalize wrapped document links to direct statute URLs when possible."""
        raw = str(link_url or "").strip()
        if not raw:
            return raw

        try:
            parsed = urlparse(raw)
            query = parse_qs(parsed.query or "")
            doc_name_values = query.get("docName") or query.get("docname")
            if doc_name_values:
                candidate = unquote(str(doc_name_values[0] or "")).strip()
                if candidate.startswith(("http://", "https://")):
                    return candidate
        except Exception:
            return raw

        return raw

    def _derive_section_number_from_url(self, link_url: str) -> Optional[str]:
        """Best-effort section number extraction from statute URL patterns."""
        url_value = str(link_url or "").strip()
        if not url_value:
            return None

        lowered = url_value.lower()
        az_match = re.search(r"/ars/(\d+)/(\d{5})(?:-(\d{2}))?\.htm", lowered)
        if az_match:
            title_num = str(int(az_match.group(1)))
            base_num = str(int(az_match.group(2)))
            suffix = az_match.group(3)
            if suffix:
                return f"{title_num}-{base_num}.{suffix}"
            return f"{title_num}-{base_num}"

        parsed = urlparse(url_value)
        query = parse_qs(parsed.query or "")
        section_values = query.get("section") or query.get("sec")
        if section_values:
            candidate = self._normalize_legal_text(str(section_values[0]))
            if candidate:
                return candidate

        cite_values = query.get("cite")
        if cite_values:
            candidate = self._normalize_legal_text(str(cite_values[0]))
            if re.match(r"^\d+[A-Za-z]?\.\d+\.\d+[A-Za-z]?$", candidate):
                return candidate

        wi_match = re.search(r"/document/statutes/([0-9]+(?:\.[0-9A-Za-z]+)+)$", parsed.path, flags=re.IGNORECASE)
        if wi_match:
            return wi_match.group(1)

        mn_match = re.search(r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)$", parsed.path, flags=re.IGNORECASE)
        if mn_match:
            return mn_match.group(1)

        wv_match = re.search(r"/(\d+[A-Za-z]?(?:-\d+[A-Za-z]?){2,})/?$", parsed.path)
        if wv_match:
            return wv_match.group(1)

        mt_match = re.search(r"/(\d{4}-\d{4}-\d{4}-\d{4})\.html$", parsed.path, flags=re.IGNORECASE)
        if mt_match:
            return mt_match.group(1)

        return None

    def _extract_best_content_text(self, html_text: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return self._normalize_legal_text(html_text)

        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
            tag.decompose()

        candidates = []
        selectors = [
            "main",
            "article",
            "section",
            "div#content",
            "div.content",
            "div#main-content",
            "div.main-content",
            "div.statute",
            "div.law-content",
        ]

        for selector in selectors:
            for node in soup.select(selector):
                text = self._normalize_legal_text(node.get_text(" ", strip=True))
                if len(text) >= 200:
                    candidates.append(text)

        if not candidates:
            body = soup.find("body")
            if body is not None:
                text = self._normalize_legal_text(body.get_text(" ", strip=True))
                if text:
                    candidates.append(text)

        if not candidates:
            fallback = self._normalize_legal_text(soup.get_text(" ", strip=True))
            return fallback

        # Prefer the longest candidate as a simple heuristic for statute body text.
        return max(candidates, key=len)

    def _trim_to_section_context(self, text: str, statute: NormalizedStatute) -> str:
        value = self._normalize_legal_text(text)
        if not value:
            return value

        section_number = self._normalize_legal_text(str(statute.section_number or ""))
        section_name = self._normalize_legal_text(str(statute.section_name or ""))

        anchors: List[str] = []
        if section_number:
            anchors.extend([
                f"section {section_number}",
                f"§ {section_number}",
                section_number,
            ])
        if section_name and section_name != section_number and len(section_name) >= 6:
            anchors.append(section_name)

        lower_value = value.lower()
        best_idx: Optional[int] = None
        for anchor in anchors:
            idx = lower_value.find(anchor.lower())
            if idx >= 0:
                best_idx = idx if best_idx is None else min(best_idx, idx)

        if best_idx is None:
            trimmed = value
        else:
            # Keep a little left context for headings, but drop bulky site navigation.
            start = max(0, best_idx - 24)
            trimmed = self._normalize_legal_text(value[start:]) or value

        # Drop trailing site chrome/footer content that often follows statutes.
        footer_markers = [
            "Legislative questions or comments",
            "Call the Legislative Hotline",
            "TTY for deaf/hard of hearing",
            "Back to top",
            "Privacy notice",
        ]
        lowered = trimmed.lower()
        cut_index: Optional[int] = None
        for marker in footer_markers:
            idx = lowered.find(marker.lower())
            if idx >= 0:
                cut_index = idx if cut_index is None else min(cut_index, idx)

        if cut_index is not None and cut_index > 80:
            trimmed = self._normalize_legal_text(trimmed[:cut_index])

        return trimmed or value

    async def _fetch_page_content_with_archival_fallback(self, url: str, timeout_seconds: int = 25) -> bytes:
        """Fetch HTML bytes using direct + archival fallback chain.

        This keeps Common Crawl/Wayback/Archive.is logic inside state scrapers,
        mirroring Oregon archival workflow for all states.
        """
        original_timeout_seconds = timeout_seconds
        bounded_fetch_timeout = _env_float("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS", 0.0)
        if bounded_fetch_timeout > 0:
            timeout_seconds = max(1, int(min(float(timeout_seconds), bounded_fetch_timeout)))

        async def _try_requests_direct() -> bytes:
            try:
                from urllib.request import Request, urlopen

                headers = {
                    "User-Agent": "ipfs-datasets-state-scraper/2.0",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                }
                for candidate_url in self._wayback_replay_candidates(url):
                    try:
                        request = Request(candidate_url, headers=headers)
                        with urlopen(request, timeout=max(1, int(timeout_seconds or 25))) as response:
                            status_code = int(getattr(response, "status", 200) or 200)
                            content = bytes(response.read() or b"")
                        if status_code != 200 or not content:
                            continue
                        self._record_fetch_event(provider="requests_direct", success=True)
                        await self._cache_successful_page_fetch(
                            url=url,
                            payload=content,
                            provider="requests_direct",
                        )
                        return content
                    except Exception:
                        continue

                self._record_fetch_event(provider="requests_direct", success=False)
                return b""
            except Exception as exc:
                self._record_fetch_event(provider="requests_direct", success=False, error=str(exc))
                return b""

        cached_bytes = await self._load_page_bytes_from_any_cache(url)
        if cached_bytes:
            return cached_bytes

        # Prefer the live official page before expensive rescue paths. The
        # archival/search chain is a recovery mechanism; letting it run before
        # a healthy official fetch makes full-corpus daemon sweeps look stalled
        # and can multiply RAM/network work across thousands of statute pages.
        direct_first = str(os.getenv("STATE_SCRAPER_DIRECT_FIRST", "1")).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if direct_first or bounded_fetch_timeout > 0:
            direct_bytes = await _try_requests_direct()
            if direct_bytes:
                return direct_bytes
            direct_only = str(os.getenv("STATE_SCRAPER_BOUNDED_DIRECT_ONLY", "")).strip().lower()
            if direct_only in {"1", "true", "yes", "on"}:
                return b""

        unified_enabled = str(os.getenv("STATE_SCRAPER_UNIFIED_FETCH_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
        # Very small hydration timeouts are usually smoke-test budgets. Avoid
        # non-cancellable background fetch workers in that mode.
        if original_timeout_seconds <= 5 and bounded_fetch_timeout <= 0:
            unified_enabled = False
        if unified_enabled:
            for candidate_url in self._wayback_replay_candidates(url):
                unified_bytes = await self._fetch_page_content_with_unified_api(
                    url=candidate_url,
                    timeout_seconds=timeout_seconds,
                )
                if self._is_object_moved_placeholder(unified_bytes):
                    unified_bytes = b""
                if unified_bytes:
                    await self._cache_successful_page_fetch(
                        url=url,
                        payload=unified_bytes,
                        provider="unified_api",
                    )
                    return unified_bytes

        archival_enabled = str(os.getenv("STATE_SCRAPER_ARCHIVAL_FETCH_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
        if original_timeout_seconds <= 5 and bounded_fetch_timeout <= 0:
            archival_enabled = False
        if archival_enabled:
            try:
                from .state_archival_fetch import ArchivalFetchClient

                client = ArchivalFetchClient(
                    request_timeout_seconds=timeout_seconds,
                    delay_seconds=0.0,
                )
                fetched = await client.fetch_with_fallback(url)
                self._record_fetch_event(
                    provider=str(getattr(fetched, "source", "archival_fallback") or "archival_fallback"),
                    success=bool(getattr(fetched, "content", b"")),
                )
                content = bytes(fetched.content or b"")
                if content:
                    await self._cache_successful_page_fetch(
                        url=url,
                        payload=content,
                        provider=str(getattr(fetched, "source", "archival_fallback") or "archival_fallback"),
                    )
                    return content
            except Exception as exc:
                self._record_fetch_event(provider="archival_fallback", success=False, error=str(exc))
                pass

        return await _try_requests_direct()

    @staticmethod
    def _is_object_moved_placeholder(payload: bytes) -> bool:
        if not payload or len(payload) > 2048:
            return False
        try:
            text = payload.decode("utf-8", errors="replace")
        except Exception:
            return False
        return bool(_OBJECT_MOVED_HTML_RE.search(text))

    def _wayback_replay_candidates(self, url: str) -> List[str]:
        value = str(url or "").strip()
        if not value:
            return []

        out: List[str] = []

        def _add(candidate: str) -> None:
            c = str(candidate or "").strip()
            if c and c not in out:
                out.append(c)

        _add(value)

        if "web.archive.org/web/" in value:
            if "/if_/" not in value:
                _add(re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", value, count=1))
            if "/id_/" not in value:
                _add(re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1id_/\2", value, count=1))

        # Try scheme-alternate variants last for flaky mirrors.
        seed = list(out)
        for candidate in seed:
            if candidate.startswith("https://"):
                _add("http://" + candidate[8:])
            elif candidate.startswith("http://"):
                _add("https://" + candidate[7:])

        return out

    async def _fetch_page_content_with_unified_api(self, url: str, timeout_seconds: int = 25) -> bytes:
        try:
            from ....web_archiving.contracts import OperationMode, UnifiedFetchRequest
            from ....web_archiving.unified_api import UnifiedWebArchivingAPI
        except Exception:
            try:
                from ipfs_datasets_py.processors.web_archiving.contracts import (
                    OperationMode,
                    UnifiedFetchRequest,
                )
                from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI
            except Exception:
                return b""

        try:
            api = UnifiedWebArchivingAPI()
            request = UnifiedFetchRequest(
                url=url,
                mode=OperationMode.MAX_QUALITY,
                timeout_seconds=max(1, int(timeout_seconds or 25)),
                domain="legal",
                metadata={"pipeline": "state_laws"},
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(api.fetch, request),
                timeout=max(1, int(timeout_seconds or 25)),
            )
        except asyncio.TimeoutError:
            self._record_fetch_event(provider="unified_api", success=False, error="unified_api_fetch_timeout")
            return b""
        except Exception as exc:
            self._record_fetch_event(provider="unified_api", success=False, error=str(exc))
            return b""

        trace = getattr(response, "trace", None)
        provider = str(getattr(trace, "provider_selected", None) or "unified_api")
        if trace is not None:
            try:
                self._fetch_analytics["fallback_count"] = int(self._fetch_analytics.get("fallback_count", 0) or 0) + int(
                    getattr(trace, "fallback_count", 0) or 0
                )
            except Exception:
                pass

        if not bool(getattr(response, "success", False)):
            message = None
            errors = getattr(response, "errors", []) or []
            if errors:
                message = str(getattr(errors[0], "message", "")) or "unified_api_fetch_failed"
            self._record_fetch_event(provider=provider, success=False, error=message)
            return b""

        document = getattr(response, "document", None)
        if document is None:
            self._record_fetch_event(provider=provider, success=False)
            return b""

        metadata = getattr(document, "metadata", {}) or {}
        raw_bytes = metadata.get("raw_bytes") if isinstance(metadata, dict) else None
        if isinstance(raw_bytes, bytes) and raw_bytes:
            self._record_fetch_event(provider=provider, success=True)
            return raw_bytes

        html = str(getattr(document, "html", "") or "")
        if html.strip():
            self._record_fetch_event(provider=provider, success=True)
            return html.encode("utf-8", errors="replace")

        text = str(getattr(document, "text", "") or "")
        if text.strip():
            self._record_fetch_event(provider=provider, success=True)
            return text.encode("utf-8", errors="replace")

        self._record_fetch_event(provider=provider, success=False)
        return b""

    def _record_fetch_event(self, *, provider: str, success: bool, error: Optional[str] = None) -> None:
        self._fetch_analytics["attempted"] = int(self._fetch_analytics.get("attempted", 0) or 0) + 1
        if success:
            self._fetch_analytics["success"] = int(self._fetch_analytics.get("success", 0) or 0) + 1

        providers = self._fetch_analytics.get("providers")
        if not isinstance(providers, dict):
            providers = {}
            self._fetch_analytics["providers"] = providers
        providers[provider] = int(providers.get(provider, 0) or 0) + 1

        if error:
            self._fetch_analytics["last_error"] = str(error)

    def get_fetch_analytics_snapshot(self) -> Dict[str, Any]:
        providers = self._fetch_analytics.get("providers")
        attempted = int(self._fetch_analytics.get("attempted", 0) or 0)
        success = int(self._fetch_analytics.get("success", 0) or 0)
        fallback_count = int(self._fetch_analytics.get("fallback_count", 0) or 0)
        cache_hits = int(self._fetch_analytics.get("cache_hits", 0) or 0)
        cache_writes = int(self._fetch_analytics.get("cache_writes", 0) or 0)
        fetch_cache_hits = int(self._fetch_analytics.get("fetch_cache_hits", 0) or 0)
        fetch_cache_writes = int(self._fetch_analytics.get("fetch_cache_writes", 0) or 0)
        return {
            "attempted": attempted,
            "success": success,
            "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
            "providers": dict(providers) if isinstance(providers, dict) else {},
            "fallback_count": fallback_count,
            "cache_hits": cache_hits,
            "cache_writes": cache_writes,
            "fetch_cache_hits": fetch_cache_hits,
            "fetch_cache_writes": fetch_cache_writes,
            "last_error": self._fetch_analytics.get("last_error"),
        }

    async def _hydrate_statute_text_if_needed(self, statute: NormalizedStatute) -> None:
        structured = statute.structured_data if isinstance(statute.structured_data, dict) else {}
        if bool(structured.get("skip_hydrate")):
            return

        source_url = self._canonicalize_statute_url(str(statute.source_url or "").strip())
        if source_url and source_url != str(statute.source_url or "").strip():
            statute.source_url = source_url
        if not source_url:
            return

        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"}:
            return

        base_text = str(statute.full_text or statute.summary or "")
        if not self._looks_like_shallow_stub_text(base_text):
            return

        hydrate_timeout = max(1, int(float(os.getenv("STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS", "25") or 25)))
        raw_bytes = await self._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=hydrate_timeout)
        if not raw_bytes:
            return

        # For PDF/RTF statute URLs, route bytes through document processors first.
        document_extraction = await self._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if isinstance(document_extraction, dict):
            fetched_text = self._normalize_legal_text(str(document_extraction.get("text") or ""))
            fetched_text = self._trim_to_section_context(fetched_text, statute)
            if len(fetched_text) >= 160:
                statute.full_text = fetched_text
                if not statute.section_name:
                    statute.section_name = fetched_text[:200]
                structured_update = statute.structured_data if isinstance(statute.structured_data, dict) else {}
                structured_update = dict(structured_update)
                structured_update["method_used"] = str(document_extraction.get("method") or "document_processor")
                structured_update["source_content_type"] = str(document_extraction.get("content_type") or "")
                statute.structured_data = structured_update
                return

        try:
            html_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            return

        fetched_text = self._extract_best_content_text(html_text)
        fetched_text = self._normalize_legal_text(fetched_text)
        fetched_text = self._trim_to_section_context(fetched_text, statute)
        if len(fetched_text) < 160:
            return

        # Avoid replacing stub text with navigation/event boilerplate content.
        if self._looks_like_navigation_text(fetched_text) and not self._contains_statute_signals(fetched_text):
            return

        statute.full_text = fetched_text
        if not statute.section_name:
            statute.section_name = fetched_text[:200]

    async def _extract_text_from_document_bytes(
        self,
        *,
        source_url: str,
        raw_bytes: bytes,
    ) -> Optional[Dict[str, str]]:
        if not raw_bytes:
            return None

        lowered_url = str(source_url or "").strip().lower()
        pdf_candidate = lowered_url.endswith(".pdf") or ".pdf?" in lowered_url or bool(_PDF_HEADER_RE.search(raw_bytes[:16]))
        rtf_candidate = lowered_url.endswith(".rtf") or ".rtf?" in lowered_url or bool(_RTF_HEADER_RE.search(raw_bytes[:32]))
        if not (pdf_candidate or rtf_candidate):
            return None

        if pdf_candidate:
            # Fast path for text-native PDFs so we can avoid expensive OCR/model bootstrap.
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(BytesIO(raw_bytes))
                pages = [str(page.extract_text() or "") for page in reader.pages]
                extracted = self._normalize_legal_text("\n".join(pages))
            except Exception:
                extracted = ""
            if extracted:
                return {
                    "text": extracted,
                    "method": "pypdf_fast_path",
                    "content_type": "application/pdf",
                }

            try:
                from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import UnifiedWebScraper
            except Exception:
                return None

            try:
                extracted = await UnifiedWebScraper._extract_pdf_text(raw_bytes)
            except Exception:
                extracted = ""
            extracted = str(extracted or "").strip()
            if extracted:
                return {
                    "text": extracted,
                    "method": "pdf_processor",
                    "content_type": "application/pdf",
                }

        if rtf_candidate:
            try:
                from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import UnifiedWebScraper
            except Exception:
                return None

            try:
                extracted = await UnifiedWebScraper._extract_rtf_text(raw_bytes)
            except Exception:
                extracted = ""
            extracted = str(extracted or "").strip()
            if extracted:
                return {
                    "text": extracted,
                    "method": "rtf_processor",
                    "content_type": "application/rtf",
                }

        return None

    def _normalize_legal_text(self, text: str) -> str:
        """Normalize whitespace and punctuation for legal-text parsing."""
        value = str(text or "")
        value = value.replace("\u00a0", " ")
        value = value.replace("\ufeff", "")
        value = value.replace("\u2019", "'")
        value = value.replace("\u201c", '"').replace("\u201d", '"')
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for item in items:
            value = self._normalize_legal_text(item)
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
        return out

    def _classify_subsec_kind(self, token: str, prev_kind: Optional[str]) -> str:
        if token.isdigit():
            return "numeric"

        if token.islower():
            if token in COMMON_ROMAN_LOWER and prev_kind in {"alpha_upper", "roman_lower", "roman_upper"}:
                return "roman_lower"
            if len(token) > 1 and ROMAN_LOWER_RE.match(token):
                return "roman_lower"
            return "alpha_lower"

        if token.isupper():
            if token in COMMON_ROMAN_UPPER and prev_kind in {"roman_lower", "roman_upper"}:
                return "roman_upper"
            if len(token) > 1 and ROMAN_UPPER_RE.match(token):
                return "roman_upper"
            return "alpha_upper"

        return "other"

    def _subsec_level(self, kind: str) -> int:
        order = {
            "numeric": 1,
            "alpha_lower": 2,
            "alpha_upper": 3,
            "roman_lower": 4,
            "roman_upper": 5,
            "other": 6,
        }
        return int(order.get(kind, 6))

    def _find_subsec_markers(self, text: str) -> List[tuple[int, int, str]]:
        markers: List[tuple[int, int, str]] = []
        for match in SUBSEC_TOKEN_RE.finditer(text):
            start = int(match.start())
            end = int(match.end())
            token = str(match.group(1))

            if len(token) > 6:
                continue
            if token.isdigit() and len(token) > 3:
                continue
            if token.isalpha():
                if not (token.islower() or token.isupper()):
                    continue
                if len(token) > 1:
                    if token.islower() and not ROMAN_LOWER_RE.match(token):
                        continue
                    if token.isupper() and not ROMAN_UPPER_RE.match(token):
                        continue

            prev_ch = text[start - 1] if start > 0 else ""
            next_ch = text[end] if end < len(text) else ""

            valid_left = (start == 0) or prev_ch.isspace() or prev_ch in ";:.(["
            valid_right = (end == len(text)) or next_ch.isspace() or next_ch in "(),;:.]"
            if not (valid_left and valid_right):
                continue

            markers.append((start, end, token))
        return markers

    def _parse_subsections(self, text: str) -> List[Dict[str, Any]]:
        normalized = self._normalize_legal_text(text)
        markers = self._find_subsec_markers(normalized)
        if not markers:
            return []

        items: List[Dict[str, Any]] = []
        prev_kind: Optional[str] = None
        for idx, (start, end, token) in enumerate(markers):
            next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(normalized)
            body = self._normalize_legal_text(normalized[end:next_start])
            kind = self._classify_subsec_kind(token, prev_kind)
            prev_kind = kind
            items.append(
                {
                    "label": f"({token})",
                    "token": token,
                    "kind": kind,
                    "level": self._subsec_level(kind),
                    "text": body,
                    "subsections": [],
                }
            )

        roots: List[Dict[str, Any]] = []
        stack: List[Dict[str, Any]] = []

        for item in items:
            level = int(item["level"])
            while stack and int(stack[-1]["level"]) >= level:
                stack.pop()

            parent_subsections = roots if not stack else stack[-1]["subsections"]

            existing_node: Optional[Dict[str, Any]] = None
            for sibling in reversed(parent_subsections):
                if sibling.get("label") == item["label"]:
                    existing_node = sibling
                    break

            if existing_node is None:
                node = {
                    "label": item["label"],
                    "token": item["token"],
                    "kind": item["kind"],
                    "text": item["text"],
                    "subsections": [],
                }
                parent_subsections.append(node)
            else:
                node = existing_node
                new_text = self._normalize_legal_text(str(item.get("text") or ""))
                old_text = self._normalize_legal_text(str(node.get("text") or ""))
                if new_text:
                    if not old_text:
                        node["text"] = new_text
                    elif new_text not in old_text:
                        node["text"] = f"{old_text} {new_text}".strip()

            stack.append({"level": level, "subsections": node["subsections"]})

        return roots

    def _fallback_subsections_from_text(self, text: str, *, max_nodes: int = 8) -> List[Dict[str, Any]]:
        """Build coarse subsection nodes when marker parsing yields nothing.

        Some state sources flatten formatting and omit explicit `(a)`/`(1)` labels.
        This fallback preserves useful structure by chunking long clause-like text.
        """
        normalized = self._normalize_legal_text(text)
        if len(normalized) < 120:
            return []

        # Prefer semicolon-delimited legal clauses.
        clauses = [self._normalize_legal_text(part) for part in re.split(r";\s+", normalized)]
        clauses = [part for part in clauses if len(part) >= 40]

        # If semicolon clauses are sparse, split on sentence boundaries.
        if len(clauses) < 2:
            clauses = [
                self._normalize_legal_text(part)
                for part in re.split(r"(?<=[\.!?])\s+(?=[A-Z0-9])", normalized)
            ]
            clauses = [part for part in clauses if len(part) >= 60]

        if not clauses:
            # Last resort: represent long narrative text as a single subsection.
            return [{
                "label": "(1)",
                "token": "1",
                "kind": "numeric",
                "text": normalized,
                "subsections": [],
            }]

        nodes: List[Dict[str, Any]] = []
        for index, clause in enumerate(clauses[:max_nodes], start=1):
            nodes.append(
                {
                    "label": f"({index})",
                    "token": str(index),
                    "kind": "numeric",
                    "text": clause,
                    "subsections": [],
                }
            )
        return nodes

    def _extract_preamble(self, text: str, max_chars: int = 500) -> str:
        source = self._normalize_legal_text(text)
        if not source:
            return ""

        markers = self._find_subsec_markers(source)
        if markers and markers[0][0] > 0:
            return self._normalize_legal_text(source[: markers[0][0]])[:max_chars]

        sentence_match = re.match(rf"(.{{1,{int(max_chars)}}}?[\.;:])(\s|$)", source)
        if sentence_match:
            return self._normalize_legal_text(sentence_match.group(1))

        return self._normalize_legal_text(source[:max_chars])

    def _extract_citations_from_text(
        self,
        full_text: str,
        core_text: str = "",
        extra_patterns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[str]]:
        base = str(full_text or "")
        core = str(core_text or "") or base

        citations: Dict[str, List[str]] = {
            "usc_citations": self._dedupe_keep_order(USC_CITATION_RE.findall(core)),
            "public_laws": self._dedupe_keep_order(PUBLIC_LAW_CITATION_RE.findall(base)),
            "statutes_at_large": self._dedupe_keep_order(STAT_CITATION_RE.findall(base)),
            "section_references": self._dedupe_keep_order(SECTION_REF_RE.findall(core)),
        }

        for key, pattern in (extra_patterns or {}).items():
            try:
                if hasattr(pattern, "findall"):
                    matches = pattern.findall(core)
                else:
                    matches = re.findall(str(pattern), core, flags=re.IGNORECASE)
            except Exception:
                matches = []
            citations[str(key)] = self._dedupe_keep_order([str(item) for item in matches])

        return citations

    def _validate_subsection_tree(self, nodes: List[Dict[str, Any]], *, max_depth: int = 6) -> List[str]:
        issues: List[str] = []

        def walk(siblings: List[Dict[str, Any]], depth: int, path: str) -> None:
            if depth > max_depth:
                issues.append(f"depth>{max_depth} at {path or 'root'}")

            seen_labels: Dict[str, int] = {}
            for index, node in enumerate(siblings, start=1):
                label = str(node.get("label", ""))
                kind = str(node.get("kind", ""))
                text = self._normalize_legal_text(str(node.get("text", "")))
                children = node.get("subsections", [])

                if label:
                    seen_labels[label] = seen_labels.get(label, 0) + 1
                    if seen_labels[label] > 1:
                        issues.append(f"duplicate sibling label {label} at {path or 'root'}")

                if not text and not children:
                    issues.append(f"empty leaf node {label or '#'+str(index)} at {path or 'root'}")

                if kind not in {"numeric", "alpha_lower", "alpha_upper", "roman_lower", "roman_upper", "other"}:
                    issues.append(f"unknown kind {kind} for {label or '#'+str(index)}")

                child_path = f"{path}/{label}" if path else label
                if isinstance(children, list) and children:
                    walk(children, depth + 1, child_path)

        walk(nodes, depth=1, path="")
        return sorted(set(issues))

    def _build_state_jsonld(
        self,
        statute: NormalizedStatute,
        *,
        text: str,
        preamble: str,
        citations: Dict[str, Any],
        legislative_history: Dict[str, Any],
        subsections: List[Dict[str, Any]],
        parser_warnings: List[str],
    ) -> Dict[str, Any]:
        title_number = str(statute.title_number or "")
        chapter_number = str(statute.chapter_number or "")
        section_number = str(statute.section_number or "")
        year_value = getattr(statute.metadata, "enacted_year", None) if statute.metadata else None
        chapter_obj = {
            "chapter_label": statute.chapter_number or statute.title_number or statute.code_name or "",
            "chapter_name": statute.chapter_name or statute.title_name or statute.code_name or "",
            "chapter_inferred": True,
        }

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "state": f"https://www.usa.gov/states/{self.state_code.lower()}",
                "stateCode": "state:code",
                "sectionNumber": "state:sectionNumber",
                "sourceUrl": "state:sourceUrl",
            },
            "@type": "Legislation",
            "@id": f"urn:state:{self.state_code.lower()}:statute:{statute.statute_id}",
            "name": statute.section_name or statute.short_title or statute.statute_id,
            "isPartOf": {
                "@type": "CreativeWork",
                "name": statute.code_name or f"{self.state_name} Statutes",
                "identifier": f"{self.state_code}-{title_number or chapter_number or 'code'}",
            },
            "legislationType": "statute",
            "stateCode": self.state_code,
            "stateName": self.state_name,
            "titleNumber": title_number or None,
            "titleName": statute.title_name,
            "chapterNumber": chapter_number or None,
            "chapterName": statute.chapter_name,
            "sectionNumber": section_number or None,
            "sectionName": statute.section_name,
            "dateModified": str(year_value) if year_value is not None else None,
            "sourceUrl": statute.source_url,
            "chapter": chapter_obj,
            "preamble": preamble,
            "citations": citations,
            "legislativeHistory": legislative_history,
            "text": text,
            "subsections": subsections,
            "parser_warnings": parser_warnings,
        }

    def _enrich_statute_structure(self, statute: NormalizedStatute) -> NormalizedStatute:
        """Attach US Code-style structured parsing and JSON-LD to a statute."""
        if not isinstance(statute, NormalizedStatute):
            return statute

        source_text = str(statute.full_text or statute.summary or statute.short_title or "")
        existing = dict(statute.structured_data or {})
        if not source_text and existing:
            return statute

        legislative_history = existing.get("legislative_history")
        if not isinstance(legislative_history, dict):
            legislative_history = self._extract_legislative_history(source_text)

        cleaned_text = self._normalize_legal_text(str(legislative_history.get("cleaned_text") or source_text))
        preamble = existing.get("preamble")
        if not isinstance(preamble, str):
            preamble = self._extract_preamble(cleaned_text)

        subsections = existing.get("subsections")
        if not isinstance(subsections, list):
            subsections = self._parse_subsections(cleaned_text)
        if isinstance(subsections, list) and not subsections:
            subsections = self._fallback_subsections_from_text(cleaned_text)

        parser_warnings = existing.get("parser_warnings")
        if not isinstance(parser_warnings, list):
            parser_warnings = self._validate_subsection_tree(subsections)

        citations = existing.get("citations")
        if not isinstance(citations, dict):
            citations = self._extract_citations_from_text(source_text, cleaned_text)

        jsonld_payload = existing.get("jsonld")
        if not isinstance(jsonld_payload, dict):
            jsonld_payload = self._build_state_jsonld(
                statute,
                text=cleaned_text,
                preamble=str(preamble or ""),
                citations=citations,
                legislative_history=legislative_history,
                subsections=subsections,
                parser_warnings=parser_warnings,
            )

        statute.structured_data = {
            **existing,
            "preamble": preamble,
            "citations": citations,
            "legislative_history": legislative_history,
            "subsections": subsections,
            "parser_warnings": parser_warnings,
            "jsonld": jsonld_payload,
        }
        return statute
    
    async def _generic_scrape(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Generic scraper implementation that can be used by most states.
        
        This method provides a common scraping pattern that works for many
        state legislative websites. Individual scrapers can override scrape_code()
        for more sophisticated parsing.
        
        Args:
            code_name: Name of the code (e.g., "Penal Code")
            code_url: URL to scrape
            citation_format: Citation format (e.g., "Cal. Penal Code")
            max_sections: Maximum number of sections to scrape
            
        Returns:
            List of NormalizedStatute objects
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        bounded_max_sections = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded_max_sections > 0:
            scan_limit = max(bounded_max_sections, min(int(max_sections or bounded_max_sections), bounded_max_sections * 10))
            max_sections = max(1, scan_limit)
        elif self._full_corpus_enabled():
            max_sections = None
        
        statutes = []
        seen_source_urls = set()

        def _extract_statutes_from_soup(soup, page_url: str) -> int:
            """Extract probable statute anchors from one page soup into `statutes`."""
            section_links = soup.find_all('a', href=True)
            section_count = 0

            for link in section_links:
                if max_sections is not None and len(statutes) >= max_sections:
                    break

                link_text = link.get_text(strip=True)
                link_url = link.get('href', '')

                if not link_text or len(link_text) < 3:
                    continue

                if not link_url.startswith('http'):
                    from urllib.parse import urljoin
                    link_url = urljoin(page_url, link_url)
                if not link_url.startswith('http'):
                    continue

                link_url = self._canonicalize_statute_url(link_url)

                if not self._is_probable_statute_link(link_text, link_url, page_url):
                    continue

                if link_url in seen_source_urls:
                    continue

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = self._derive_section_number_from_url(link_url)
                if not section_number:
                    section_number = f"Section-{len(statutes) + 1}"

                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=link_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )

                statutes.append(statute)
                seen_source_urls.add(link_url)
                section_count += 1

            return section_count
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(code_url, timeout_seconds=45)
            if not page_bytes:
                raise RuntimeError(f"Failed to retrieve code page: {code_url}")

            soup = BeautifulSoup(page_bytes, 'html.parser')

            # Extract legal area from code name
            legal_area = self._identify_legal_area(code_name)

            section_count = _extract_statutes_from_soup(soup, code_url)

            # If the landing page yields very few statute links, try one-hop discovery
            # pages that look like code/statute indexes.
            if len(statutes) < min(10, max_sections or 10):
                discovery_urls = []
                discovery_seen = set()
                discovery_keywords = (
                    "statute", "statutes", "code", "codes", "law", "laws",
                    "title", "chapter", "revised", "consolidated", "constitution"
                )

                for link in soup.find_all('a', href=True):
                    if len(discovery_urls) >= 8:
                        break
                    link_text = (link.get_text(" ", strip=True) or "").lower()
                    href = str(link.get('href', '') or '')
                    href_l = href.lower()
                    if not any(k in link_text or k in href_l for k in discovery_keywords):
                        continue
                    from urllib.parse import urljoin
                    abs_url = urljoin(code_url, href)
                    abs_url = self._canonicalize_statute_url(abs_url)
                    if not abs_url.startswith("http"):
                        continue
                    if abs_url in discovery_seen:
                        continue
                    discovery_seen.add(abs_url)
                    discovery_urls.append(abs_url)

                for discovery_url in discovery_urls:
                    if max_sections is not None and len(statutes) >= max_sections:
                        break
                    try:
                        discovery_bytes = await self._fetch_page_content_with_archival_fallback(
                            discovery_url,
                            timeout_seconds=35,
                        )
                        if not discovery_bytes:
                            continue
                        discovery_soup = BeautifulSoup(discovery_bytes, 'html.parser')
                        section_count += _extract_statutes_from_soup(discovery_soup, discovery_url)
                    except Exception:
                        continue
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes
    
    def has_playwright(self) -> bool:
        """Check if Playwright is available."""
        try:
            from playwright.async_api import async_playwright
            return True
        except ImportError:
            return False
    
    async def _playwright_scrape(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100,
        wait_for_selector: str = "a",
        timeout: int = 30000,
        wait_until: str = "networkidle",
    ) -> List[NormalizedStatute]:
        """Scrape using Playwright for JavaScript-rendered content.
        
        This method uses Playwright to render JavaScript content before scraping.
        It's useful for states with dynamic/modern web interfaces.
        
        Args:
            code_name: Name of the code being scraped
            code_url: URL of the code index page
            citation_format: Format string for citations
            max_sections: Maximum number of sections to scrape
            wait_for_selector: CSS selector to wait for before scraping
            timeout: Timeout in milliseconds (default: 30000)
            wait_until: Playwright navigation completion mode (e.g.,
                "networkidle", "domcontentloaded", "load")
            
        Returns:
            List of NormalizedStatute objects
        """
        from urllib.parse import urljoin

        bounded_max_sections = _env_int("STATE_SCRAPER_MAX_STATUTES", 0)
        if bounded_max_sections > 0:
            scan_limit = max(bounded_max_sections, min(int(max_sections or bounded_max_sections), bounded_max_sections * 10))
            max_sections = max(1, scan_limit)
        elif self._full_corpus_enabled():
            max_sections = None
        
        if not self.has_playwright():
            self.logger.warning(f"Playwright not available, falling back to generic scrape for {code_name}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        try:
            from playwright.async_api import async_playwright
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        statutes = []
        
        try:
            async with acquire_playwright_slot():
                async with async_playwright() as p:
                    # Launch browser
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                
                    try:
                        # Navigate to page
                        await page.goto(code_url, wait_until=wait_until, timeout=timeout)

                        # Wait for specific content
                        try:
                            await page.wait_for_selector(wait_for_selector, timeout=timeout)
                        except Exception:
                            self.logger.warning(f"Timeout waiting for selector '{wait_for_selector}' on {code_url}")

                        # Get page content after JavaScript execution
                        content = await page.content()

                        # Parse with BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')

                        # Extract legal area
                        legal_area = self._identify_legal_area(code_name)

                        # Scan all anchors, then stop once enough probable statute links are collected.
                        section_links = soup.find_all('a', href=True)

                        section_count = 0
                        for link in section_links:
                            if max_sections is not None and section_count >= max_sections:
                                break

                            link_text = link.get_text(strip=True)
                            link_url = link.get('href', '')

                            # Skip if link doesn't look useful
                            if not link_text or len(link_text) < 3:
                                continue

                            # Make URL absolute (handles '/x' and 'x/y').
                            if not link_url.startswith('http'):
                                link_url = urljoin(code_url, link_url)
                            if not link_url.startswith('http'):
                                continue

                            link_url = self._canonicalize_statute_url(link_url)

                            if not self._is_probable_statute_link(link_text, link_url, code_url):
                                continue

                            # Extract section number
                            section_number = self._extract_section_number(link_text)
                            if not section_number:
                                section_number = self._derive_section_number_from_url(link_url)
                            if not section_number:
                                section_number = f"Section-{section_count + 1}"

                            # Create normalized statute
                            statute = NormalizedStatute(
                                state_code=self.state_code,
                                state_name=self.state_name,
                                statute_id=f"{code_name} § {section_number}",
                                code_name=code_name,
                                section_number=section_number,
                                section_name=link_text[:200],
                                full_text=f"Section {section_number}: {link_text}",
                                legal_area=legal_area,
                                source_url=link_url,
                                official_cite=f"{citation_format} § {section_number}",
                                metadata=StatuteMetadata()
                            )

                            statutes.append(statute)
                            section_count += 1

                        self.logger.info(f"Scraped {len(statutes)} sections using Playwright from {code_name}")

                    finally:
                        try:
                            await page.close()
                        finally:
                            await browser.close()
            
        except Exception as e:
            self.logger.error(f"Error in Playwright scrape for {code_name}: {str(e)}")
            # Try fallback to generic scrape
            self.logger.info(f"Falling back to generic scrape for {code_name}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes
    
    # ========================================================================
    # Common Crawl Integration Methods (Phase 11 Task 11.3)
    # ========================================================================
    
    async def scrape_from_common_crawl(
        self,
        url: str,
        dataset_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Scrape content from Common Crawl archives via HuggingFace datasets.
        
        This method queries Common Crawl indexes to find archived versions
        of legal websites, then fetches the content from WARC files.
        
        Args:
            url: URL to scrape from Common Crawl
            dataset_name: HuggingFace dataset name (e.g., "endomorphosis/common_crawl_state_index")
            
        Returns:
            Scraped content or None if not found
            
        Example:
            content = await scraper.scrape_from_common_crawl(
                "https://legislature.example.gov/code.html",
                dataset_name="endomorphosis/common_crawl_state_index"
            )
        """
        try:
            # Import Common Crawl scraper
            from ..common_crawl_scraper import CommonCrawlLegalScraper
            
            # Create scraper instance
            cc_scraper = CommonCrawlLegalScraper()
            
            # Scrape the URL using Common Crawl
            result = await cc_scraper.scrape_url(
                url,
                extract_rules=False,  # Just get content
                feed_to_logic=False
            )
            
            if result.success and result.content:
                self.logger.info(f"Retrieved content from Common Crawl for: {url}")
                return result.content
            else:
                self.logger.warning(f"No Common Crawl content found for: {url}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error scraping from Common Crawl: {e}")
            return None
    
    async def query_warc_file(
        self,
        warc_url: str,
        offset: int,
        length: int
    ) -> Optional[str]:
        """
        Query a WARC file directly using offset and range.
        
        This method retrieves content from a Common Crawl WARC file
        using byte offset and length for efficient partial file access.
        
        Args:
            warc_url: S3 URL to WARC file
            offset: Byte offset in file
            length: Number of bytes to read
            
        Returns:
            WARC record content or None
            
        Example:
            content = await scraper.query_warc_file(
                "s3://commoncrawl/crawl-data/CC-MAIN-2024-10/segments/.../warc.gz",
                offset=123456,
                length=5000
            )
        """
        try:
            from ...web_archiving.common_crawl_integration import CommonCrawlSearchEngine
            from urllib.parse import urlparse
            
            # Create engine instance
            engine = CommonCrawlSearchEngine()
            
            parsed = urlparse(str(warc_url or ""))
            warc_filename = parsed.path.lstrip("/") if parsed.scheme else str(warc_url or "")

            # Support the current fetch_warc_record API and older fetch_warc_segment variants.
            if hasattr(engine, "fetch_warc_record"):
                raw_content = engine.fetch_warc_record(
                    warc_filename=warc_filename,
                    warc_offset=offset,
                    warc_length=length,
                )
                if isinstance(raw_content, (bytes, bytearray)):
                    content = bytes(raw_content).decode("utf-8", errors="replace")
                else:
                    content = str(raw_content or "")
            else:
                fetch_warc_segment = getattr(engine, "fetch_warc_segment")
                content = await fetch_warc_segment(
                    warc_url=warc_url,
                    offset=offset,
                    length=length
                )
            
            if content:
                self.logger.info(f"Retrieved WARC content (offset={offset}, length={length})")
                return content
            else:
                self.logger.warning("Empty WARC content retrieved")
                return None
                
        except Exception as e:
            self.logger.error(f"Error querying WARC file: {e}")
            return None
    
    async def extract_with_graphrag(
        self,
        content: str,
        extract_rules: bool = True
    ) -> Dict[str, Any]:
        """
        Extract structured data from legal content using GraphRAG.
        
        This method uses GraphRAG to extract entities, relationships,
        and legal rules from raw legal text content.
        
        Args:
            content: Raw HTML or text content
            extract_rules: Whether to extract legal rules
            
        Returns:
            Dictionary with extracted data (entities, relationships, rules)
            
        Example:
            results = await scraper.extract_with_graphrag(
                html_content,
                extract_rules=True
            )
            rules = results.get('rules', [])
        """
        try:
            from ...specialized.graphrag import UnifiedGraphRAGProcessor
            
            # Create GraphRAG processor
            graphrag = UnifiedGraphRAGProcessor()
            
            # Use process_website which is the primary API
            # We pass the content as if it's from a URL
            extraction_result = await graphrag.process_website(
                url="inline://content",  # Dummy URL for inline content
                content_override=content  # Pass content directly
            )
            
            result = {
                'entities': extraction_result.entities if hasattr(extraction_result, 'entities') else [],
                'relationships': extraction_result.relationships if hasattr(extraction_result, 'relationships') else [],
                'rules': []
            }
            
            # Extract legal rules from knowledge graph if available
            if extract_rules and hasattr(extraction_result, 'knowledge_graph'):
                # Simple rule extraction: look for entities that represent rules/statutes
                kg = extraction_result.knowledge_graph
                if kg and hasattr(kg, 'entities'):
                    for entity in kg.entities.values():
                        if entity.type.lower() in ['rule', 'statute', 'law', 'regulation']:
                            result['rules'].append({
                                'text': entity.name,
                                'type': entity.type,
                                'attributes': entity.attributes if hasattr(entity, 'attributes') else {}
                            })
            
            self.logger.info(
                f"Extracted {len(result['entities'])} entities, "
                f"{len(result['relationships'])} relationships, "
                f"{len(result['rules'])} rules"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error extracting with GraphRAG: {e}")
            return {'entities': [], 'relationships': [], 'rules': []}
    
    async def scrape_with_fallbacks(
        self,
        url: str,
        use_common_crawl: bool = True,
        use_graphrag: bool = False
    ) -> Optional[NormalizedStatute]:
        """
        Scrape a statute with graceful fallbacks through multiple methods.
        
        This method attempts to scrape using the following fallback chain:
        1. Common Crawl (if enabled)
        2. Direct HTTP request
        3. Playwright (if available)
        
        Args:
            url: URL to scrape
            use_common_crawl: Whether to try Common Crawl first
            use_graphrag: Whether to use GraphRAG for extraction
            
        Returns:
            NormalizedStatute or None
            
        Example:
            statute = await scraper.scrape_with_fallbacks(
                "https://legislature.example.gov/statute.html",
                use_common_crawl=True,
                use_graphrag=True
            )
        """
        content = None
        method_used = None
        
        # Try 1: Common Crawl
        if use_common_crawl:
            try:
                content = await self.scrape_from_common_crawl(url)
                if content:
                    method_used = "common_crawl"
            except Exception as e:
                self.logger.warning(f"Common Crawl failed: {e}")
        
        # Try 2: Direct HTTP
        if not content:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        content = response.text
                        method_used = "http"
            except Exception as e:
                self.logger.warning(f"HTTP request failed: {e}")
        
        # Try 3: Playwright (if available)
        if not content:
            try:
                from playwright.async_api import async_playwright
                async with acquire_playwright_slot():
                    async with async_playwright() as p:
                        browser = await p.chromium.launch()
                        page = await browser.new_page()
                        try:
                            await page.goto(url, wait_until="networkidle")
                            content = await page.content()
                            method_used = "playwright"
                        finally:
                            try:
                                await page.close()
                            finally:
                                await browser.close()
            except Exception as e:
                self.logger.warning(f"Playwright failed: {e}")
        
        if not content:
            self.logger.error(f"All fallback methods failed for: {url}")
            return None
        
        # Extract with GraphRAG if requested
        extracted_data = {}
        if use_graphrag:
            extracted_data = await self.extract_with_graphrag(content)
        
        # Parse content to create NormalizedStatute
        # This is a simplified parser - real implementation would be more sophisticated
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract basic information
        title = soup.find('title')
        title_text = title.get_text().strip() if title else "Unknown"
        
        # Try to extract section number from URL or title
        section_number = self._extract_section_number(url) or self._extract_section_number(title_text)
        
        # Create normalized statute
        statute = NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=section_number or url.split('/')[-1],
            section_number=section_number,
            short_title=title_text,
            full_text=soup.get_text()[:10000],  # Limit text length
            source_url=url,
            legal_area=self._identify_legal_area(title_text),
            metadata=StatuteMetadata()
        )
        
        self.logger.info(f"Scraped statute using {method_used}: {statute.statute_id}")

        return self._enrich_statute_structure(statute)
