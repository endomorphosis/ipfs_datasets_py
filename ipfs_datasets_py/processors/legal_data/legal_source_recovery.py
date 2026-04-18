"""Fallback recovery workflow for unresolved legal citations.

This module ties together the existing legal search, archive, and Hugging Face
publish infrastructure so unresolved legal citations can be tracked back to
candidate official sources and recorded in a canonical recovery manifest.
"""

from __future__ import annotations

import asyncio
import anyio
import io
import types
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue as queue_module
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol
from urllib.parse import urljoin, urlparse
import importlib

from .canonical_legal_corpora import get_canonical_legal_corpus
from .legal_source_recovery_promotion import (
    build_recovery_manifest_promotion_row,
    build_recovery_manifest_release_plan,
)


STATE_NAMES = {
    "AK": "Alaska",
    "AL": "Alabama",
    "AR": "Arkansas",
    "AZ": "Arizona",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DC": "District of Columbia",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "MA": "Massachusetts",
    "MD": "Maryland",
    "ME": "Maine",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "MS": "Mississippi",
    "MT": "Montana",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "NE": "Nebraska",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NV": "Nevada",
    "NY": "New York",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VA": "Virginia",
    "VT": "Vermont",
    "WA": "Washington",
    "WI": "Wisconsin",
    "WV": "West Virginia",
    "WY": "Wyoming",
}

DOWNLOADABLE_LEGAL_FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".rtf",
    ".txt",
    ".xml",
    ".json",
    ".csv",
    ".zip",
}

DOWNLOADABLE_CONTENT_TYPE_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/json": ".json",
    "text/json": ".json",
    "text/csv": ".csv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "text/plain": ".txt",
}

LEGAL_FILE_HINT_TERMS = (
    "statute",
    "statutes",
    "code",
    "rule",
    "rules",
    "regulation",
    "regulations",
    "register",
    "appendix",
    "opinion",
    "order",
    "decision",
    "notice",
    "chapter",
)

_SEARCH_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("LEGAL_SOURCE_RECOVERY_SEARCH_TIMEOUT_SECONDS", "12")),
)
_ARCHIVE_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("LEGAL_SOURCE_RECOVERY_ARCHIVE_TIMEOUT_SECONDS", "20")),
)
_FETCH_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("LEGAL_SOURCE_RECOVERY_FETCH_TIMEOUT_SECONDS", "8")),
)
_COMMON_CRAWL_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_TIMEOUT_SECONDS", str(_SEARCH_TIMEOUT_SECONDS))),
)
_MAX_COMMON_CRAWL_DOMAINS = max(
    1,
    int(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MAX_DOMAINS", "4")),
)
_MAX_CANDIDATE_DISCOVERY_PAGES = max(
    1,
    int(os.getenv("LEGAL_SOURCE_RECOVERY_MAX_CANDIDATE_DISCOVERY_PAGES", "3")),
)
_MAX_CANDIDATE_FETCHES = max(
    1,
    int(os.getenv("LEGAL_SOURCE_RECOVERY_MAX_CANDIDATE_FETCHES", "2")),
)


def build_missing_citation_recovery_query(
    citation_text: str,
    *,
    corpus_key: Optional[str],
    state_code: Optional[str] = None,
) -> str:
    citation = str(citation_text or "").strip()
    corpus = str(corpus_key or "").strip().lower()
    state = str(state_code or "").strip().upper()

    if corpus == "us_code":
        return f"{citation} site:uscode.house.gov OR site:govinfo.gov OR site:law.cornell.edu"
    if corpus == "federal_register":
        return f"{citation} site:federalregister.gov OR site:govinfo.gov"
    if corpus == "state_admin_rules":
        state_hint = f" {state}" if state else ""
        return f"{citation}{state_hint} administrative rules site:.gov OR site:.us"
    if corpus == "state_court_rules":
        state_hint = f" {state}" if state else ""
        return f"{citation}{state_hint} court rules site:.gov OR site:.us"
    if corpus == "state_laws":
        state_name = STATE_NAMES.get(state, "")
        state_hint = f" {state}" if state else ""
        name_hint = f" {state_name}" if state_name else ""
        return f"{citation}{state_hint}{name_hint} official statutes code legislature site:.gov OR site:.us"
    if corpus == "caselaw_access_project":
        return f"{citation} site:courtlistener.com OR site:law.justia.com OR site:.gov"
    return citation


def infer_recovery_corpus_key(*, corpus_key: Optional[str], metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    normalized = str(corpus_key or "").strip().lower()
    if normalized:
        return normalized
    metadata = metadata or {}
    candidates = metadata.get("candidate_corpora") or []
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if value:
            return value
    return None


def _slugify(value: str, *, limit: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text[:limit] or "citation"


def _jurisdiction_type_for_corpus(corpus_key: Optional[str]) -> Optional[str]:
    if corpus_key in {"us_code", "federal_register"}:
        return "federal"
    if corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"}:
        return "state"
    return None


def _score_candidate(result: Dict[str, Any], *, corpus_key: Optional[str], state_code: Optional[str]) -> int:
    url = str(result.get("url") or "")
    domain = urlparse(url).netloc.lower()
    title = str(result.get("title") or "")
    snippet = str(result.get("snippet") or result.get("description") or "")
    combined = f"{title} {url} {snippet}".lower()
    score = 0
    if domain.endswith(".gov") or ".gov" in domain:
        score += 5
    if domain.endswith(".us") or ".state." in domain:
        score += 4
    if corpus_key == "federal_register" and "federalregister.gov" in domain:
        score += 5
    if corpus_key == "us_code" and "uscode.house.gov" in domain:
        score += 5
    if corpus_key == "caselaw_access_project" and "courtlistener.com" in domain:
        score += 4
    if state_code and state_code.lower() in domain:
        score += 2
    state_name = STATE_NAMES.get(str(state_code or "").upper(), "")
    if state_name and state_name.lower() in combined:
        score += 4
    if corpus_key == "state_laws":
        if "statute" in combined or "statutes" in combined or "code" in combined:
            score += 3
            if "/statute" in url.lower() or "/statutes" in url.lower() or "/basis/statutes" in url.lower():
                score += 4
        elif "legislature" in combined:
            score -= 2
        if "bill" in combined or "introduced" in combined or "committee" in combined:
            score -= 3
        if domain.endswith("akleg.gov") or ".akleg.gov" in domain:
            score += 5
        other_state_hits = [
            name for code, name in STATE_NAMES.items()
            if state_code and code != str(state_code).upper() and name.lower() in combined
        ]
        if other_state_hits and not (state_name and state_name.lower() in combined):
            score -= 5
    if result.get("source_type") == "current":
        score += 1
    if result.get("source") == "citation_url_hint":
        score += 10
    if result.get("source") == "common_crawl_indexes":
        score += 1
    return score


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _common_crawl_domain_worker(
    queue: Any,
    *,
    domain: str,
    max_matches: int,
    query: str,
    jurisdiction_type: Optional[str],
    state_code: Optional[str],
    mode: str,
    mcp_endpoint: Optional[str],
    timeout_seconds: float,
) -> None:
    try:
        from ..web_archiving.common_crawl_integration import CommonCrawlSearchEngine

        engine = CommonCrawlSearchEngine(
            mode=mode,
            mcp_endpoint=mcp_endpoint,
            mcp_timeout=timeout_seconds,
        )
        if not engine.is_available():
            queue.put({"results": [], "error": "common_crawl_unavailable"})
            return
        rows = engine.search_domain(
            domain,
            max_matches=max(1, int(max_matches)),
            query=query,
            jurisdiction_type=jurisdiction_type,
            state_code=state_code,
        )
        queue.put({"results": list(rows or []), "error": ""})
    except Exception as exc:
        queue.put({"results": [], "error": str(exc)})


def _blocked_fetch_escalation_worker(
    queue: Any,
    *,
    url: str,
    title_hint: Optional[str],
    methods: List[str],
    timeout_seconds: float,
) -> None:
    try:
        errors: List[str] = []
        if "jina_reader" in {str(method or "").strip().lower() for method in list(methods or [])}:
            try:
                import requests

                reader_url = f"https://r.jina.ai/http://{url}"
                response = requests.get(
                    reader_url,
                    timeout=max(1.0, float(timeout_seconds)),
                    headers={
                        "User-Agent": "ipfs-datasets-legal-source-recovery/1.0",
                        "Accept": "text/markdown,text/plain,*/*;q=0.8",
                    },
                )
                if 200 <= int(response.status_code) < 400 and str(response.text or "").strip():
                    queue.put(
                        {
                            "success": True,
                            "document": {
                                "title": str(title_hint or ""),
                                "text": str(response.text or ""),
                                "html": "",
                                "content_type": str(response.headers.get("content-type") or "text/markdown"),
                                "metadata": {
                                    "content_type": str(response.headers.get("content-type") or "text/markdown"),
                                    "reader_url": reader_url,
                                    "source_url": url,
                                },
                                "extraction_provenance": {
                                    "method": "blocked_fetch_escalation",
                                    "scraper_method": "jina_reader",
                                    "status_code": int(response.status_code),
                                },
                            },
                            "errors": [],
                        }
                    )
                    return
                errors.append(f"jina_reader_http_status_{int(response.status_code)}")
            except Exception as exc:
                errors.append(f"jina_reader_error: {exc}")

        from ..web_archiving.unified_web_scraper import ScraperConfig, ScraperMethod, UnifiedWebScraper

        parsed_methods: List[ScraperMethod] = []
        for method_name in list(methods or []):
            if str(method_name or "").strip().lower() == "jina_reader":
                continue
            try:
                parsed_methods.append(ScraperMethod(str(method_name).strip().lower()))
            except Exception:
                continue
        if not parsed_methods:
            queue.put({"success": False, "errors": errors or ["no blocked fetch methods configured"]})
            return

        scraper = UnifiedWebScraper(
            ScraperConfig(
                timeout=max(1, int(timeout_seconds)),
                max_retries=1,
                retry_delay=0.1,
                preferred_methods=parsed_methods,
                fallback_enabled=True,
                playwright_hydration_wait_ms=max(
                    500,
                    int(os.getenv("LEGAL_SOURCE_RECOVERY_PLAYWRIGHT_HYDRATION_WAIT_MS", "1500")),
                ),
                playwright_shell_retry_wait_ms=max(
                    500,
                    int(os.getenv("LEGAL_SOURCE_RECOVERY_PLAYWRIGHT_SHELL_RETRY_WAIT_MS", "2500")),
                ),
                archive_is_submit_on_miss=False,
                archive_is_submit_wait=False,
            )
        )
        result = scraper.scrape_sync(url)
        if result is None or not getattr(result, "success", False):
            payload_errors = (
                list(getattr(result, "errors", []) or ["blocked_fetch_escalation_failed"])
                if result is not None
                else ["blocked_fetch_escalation_returned_no_result"]
            )
            queue.put(
                {
                    "success": False,
                    "errors": errors + payload_errors,
                }
            )
            return

        metadata = dict(getattr(result, "metadata", {}) or {})
        links = list(getattr(result, "links", []) or [])
        if links:
            metadata.setdefault("links", links)
        queue.put(
            {
                "success": True,
                "document": {
                    "title": str(getattr(result, "title", "") or title_hint or ""),
                    "text": str(getattr(result, "text", "") or getattr(result, "content", "") or ""),
                    "html": str(getattr(result, "html", "") or ""),
                    "content_type": str(metadata.get("content_type") or ""),
                    "metadata": metadata,
                    "extraction_provenance": {
                        "method": "blocked_fetch_escalation",
                        "scraper_method": str(
                            getattr(getattr(result, "method_used", None), "value", getattr(result, "method_used", ""))
                            or ""
                        ),
                        "errors": list(getattr(result, "errors", []) or []),
                    },
                },
                "errors": [],
            }
        )
    except Exception as exc:
        queue.put({"success": False, "errors": [str(exc)]})


class _LiveSearcher(Protocol):
    def search(self, query: str, max_results: int = 20, **kwargs: Any) -> Dict[str, Any]:
        ...


class _ArchiveSearcher(Protocol):
    def search_with_indexes(
        self,
        query: str,
        jurisdiction_type: Optional[str] = None,
        state_code: Optional[str] = None,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        ...


@dataclass
class LegalSourceCandidate:
    url: str
    title: Optional[str] = None
    source_type: Optional[str] = None
    source: Optional[str] = None
    score: int = 0


@dataclass
class ArchivedSourceRecord:
    url: str
    success: bool
    source: Optional[str] = None
    error: Optional[str] = None
    archived_at: Optional[str] = None


@dataclass
class RecoveredCandidateFile:
    url: str
    title: Optional[str] = None
    discovered_from_url: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    score: int = 0
    content_type: Optional[str] = None
    file_extension: Optional[str] = None
    fetch_success: bool = False
    artifact_path: Optional[str] = None
    metadata_path: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class RecoveryScraperPatch:
    patch_path: str
    target_file: Optional[str] = None
    host: Optional[str] = None
    rationale: Optional[str] = None
    extraction_recipe_path: Optional[str] = None


@dataclass
class _FallbackPatch:
    patch_id: str
    agent_id: str
    task_id: str
    description: str
    diff_content: str
    target_files: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    parent_patches: List[str] = field(default_factory=list)
    ipfs_cid: Optional[str] = None
    worktree_path: Optional[str] = None
    validated: bool = False
    applied: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


class _FallbackPatchManager:
    def __init__(self, *, patches_dir: Path) -> None:
        self.patches_dir = Path(patches_dir)

    def save_patch(self, patch: _FallbackPatch, output_path: Optional[Path] = None) -> Path:
        target = Path(output_path or (self.patches_dir / f"{patch.patch_id}.patch"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(patch.diff_content or ""), encoding="utf-8")
        target.with_suffix(".json").write_text(json.dumps(patch.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return target


@dataclass
class LegalSourceRecoveryResult:
    status: str
    citation_text: str
    normalized_citation: str
    corpus_key: Optional[str]
    hf_dataset_id: Optional[str]
    state_code: Optional[str]
    search_query: str
    candidate_count: int
    archived_count: int
    candidates: List[LegalSourceCandidate] = field(default_factory=list)
    archived_sources: List[ArchivedSourceRecord] = field(default_factory=list)
    manifest_path: Optional[str] = None
    manifest_directory: Optional[str] = None
    publish_report: Optional[Dict[str, Any]] = None
    publish_plan: Optional[Dict[str, Any]] = None
    promotion_preview: Optional[Dict[str, Any]] = None
    release_plan_preview: Optional[Dict[str, Any]] = None
    feedback_entry: Optional[Dict[str, Any]] = None
    search_backend_status: Optional[Dict[str, Any]] = None
    candidate_files: List[RecoveredCandidateFile] = field(default_factory=list)
    scraper_patch: Optional[RecoveryScraperPatch] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "candidates": [asdict(item) for item in self.candidates],
            "archived_sources": [asdict(item) for item in self.archived_sources],
            "candidate_files": [asdict(item) for item in self.candidate_files],
            "scraper_patch": asdict(self.scraper_patch) if self.scraper_patch is not None else None,
        }


class LegalSourceRecoveryWorkflow:
    def __init__(
        self,
        *,
        archive_searcher: Optional[_ArchiveSearcher] = None,
        live_searcher: Optional[_LiveSearcher] = None,
        archiver: Any = None,
        fetch_api: Any = None,
        patch_manager: Any = None,
        enable_candidate_file_fetch: bool = False,
        publish_func: Optional[Callable[..., Dict[str, Any]]] = None,
        now_factory: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._archive_searcher = archive_searcher
        self._live_searcher = live_searcher
        self._archiver = archiver
        self._fetch_api = fetch_api
        self._patch_manager = patch_manager
        self._enable_candidate_file_fetch = bool(enable_candidate_file_fetch)
        self._publish_func = publish_func
        self._now_factory = now_factory or datetime.utcnow

    def _searcher(self) -> Any:
        if self._archive_searcher is not None or self._live_searcher is not None:
            return None
        if str(os.getenv("LEGAL_SOURCE_RECOVERY_USE_LEGACY_SEARCHER") or "").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return None
        from ..legal_scrapers.legal_web_archive_search import LegalWebArchiveSearch

        return LegalWebArchiveSearch(auto_archive=False, use_hf_indexes=False)

    def _archiver_instance(self) -> Any:
        if self._archiver is not None:
            return self._archiver
        from ..legal_scrapers.parallel_web_archiver import ParallelWebArchiver

        enable_warc_pointers = _env_flag("LEGAL_SOURCE_RECOVERY_ENABLE_WARC_POINTERS", default=False)
        fallback_priority = ["wayback", "web_archive"]
        if enable_warc_pointers:
            fallback_priority.insert(0, "warc")
        return ParallelWebArchiver(
            use_warc_pointers=enable_warc_pointers,
            timeout=max(1, int(_ARCHIVE_TIMEOUT_SECONDS)),
            fallback_priority=fallback_priority,
        )

    def _publisher(self) -> Callable[..., Dict[str, Any]]:
        if self._publish_func is not None:
            return self._publish_func
        try:
            from scripts.repair.publish_parquet_to_hf import publish

            return publish
        except ModuleNotFoundError as exc:
            if exc.name not in {"scripts", "scripts.repair", "scripts.repair.publish_parquet_to_hf"}:
                raise
        module_path = Path(__file__).resolve().parents[3] / "scripts" / "repair" / "publish_parquet_to_hf.py"
        spec = importlib.util.spec_from_file_location("ipfs_datasets_py_publish_parquet_to_hf", module_path)
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError(f"Unable to load Hugging Face publisher from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.publish

    def _fetch_api_instance(self) -> Any:
        if self._fetch_api is not None:
            return self._fetch_api
        from ..web_archiving.unified_api import UnifiedWebArchivingAPI
        from ..web_archiving.unified_web_scraper import ScraperConfig, ScraperMethod, UnifiedWebScraper

        scraper = UnifiedWebScraper(
            ScraperConfig(
                timeout=max(1, int(_FETCH_TIMEOUT_SECONDS)),
                max_retries=1,
                retry_delay=0.1,
                preferred_methods=[ScraperMethod.REQUESTS_ONLY],
                fallback_enabled=False,
                playwright_hydration_wait_ms=500,
                playwright_shell_retry_wait_ms=500,
                archive_is_submit_on_miss=False,
                archive_is_submit_wait=False,
            )
        )
        return UnifiedWebArchivingAPI(scraper=scraper)

    @staticmethod
    def _lightweight_fetch_url(url: str, *, title_hint: Optional[str] = None) -> Any:
        """Fetch candidate evidence with requests-only socket timeouts."""
        try:
            import requests
            from bs4 import BeautifulSoup
            from requests.exceptions import SSLError
        except Exception as exc:
            return types.SimpleNamespace(success=False, document=None, errors=[exc])

        tls_verify = True
        try:
            response = requests.get(
                str(url),
                timeout=max(1.0, float(_FETCH_TIMEOUT_SECONDS)),
                headers={
                    "User-Agent": "ipfs-datasets-legal-source-recovery/1.0",
                    "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8",
                },
                allow_redirects=True,
            )
        except SSLError as exc:
            if not _env_flag("LEGAL_SOURCE_RECOVERY_RETRY_INSECURE_TLS", default=True):
                return types.SimpleNamespace(success=False, document=None, errors=[exc])
            try:
                response = requests.get(
                    str(url),
                    timeout=max(1.0, float(_FETCH_TIMEOUT_SECONDS)),
                    headers={
                        "User-Agent": "ipfs-datasets-legal-source-recovery/1.0",
                        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8",
                    },
                    allow_redirects=True,
                    verify=False,
                )
                tls_verify = False
            except Exception as retry_exc:
                return types.SimpleNamespace(success=False, document=None, errors=[retry_exc])
        except Exception as exc:
            return types.SimpleNamespace(success=False, document=None, errors=[exc])

        content_type = str(response.headers.get("content-type") or "").strip()
        raw_bytes = bytes(response.content or b"")
        text = ""
        html = ""
        links: List[Dict[str, str]] = []
        if "text" in content_type or "html" in content_type or not content_type:
            response.encoding = response.encoding or "utf-8"
            text = str(response.text or "")
            if "html" in content_type or "<html" in text.lower():
                html = text
                try:
                    soup = BeautifulSoup(html, "html.parser")
                    title_node = soup.find("title")
                    if not title_hint and title_node:
                        title_hint = title_node.get_text(" ", strip=True)
                    for anchor in soup.find_all("a", href=True)[:100]:
                        href = str(anchor.get("href") or "").strip()
                        if not href:
                            continue
                        links.append(
                            {
                                "url": urljoin(str(response.url or url), href),
                                "text": anchor.get_text(" ", strip=True),
                            }
                        )
                except Exception:
                    pass

        document = types.SimpleNamespace(
            title=title_hint or "",
            text=text,
            html=html,
            content_type=content_type,
            metadata={
                "content_type": content_type,
                "html": html,
                "links": links,
                "raw_bytes": raw_bytes if raw_bytes and "text" not in content_type and "html" not in content_type else b"",
            },
            extraction_provenance={"method": "requests_lightweight", "status_code": int(response.status_code), "tls_verify": tls_verify},
        )
        success = 200 <= int(response.status_code) < 400
        errors = [] if success else [types.SimpleNamespace(message=f"http_status_{int(response.status_code)}")]
        return types.SimpleNamespace(success=success, document=document, errors=errors)

    @staticmethod
    def _fetch_response_error_text(fetch_response: Any) -> str:
        errors = getattr(fetch_response, "errors", None) or []
        parts: List[str] = []
        for error in errors:
            if hasattr(error, "message"):
                parts.append(str(getattr(error, "message") or ""))
            else:
                parts.append(str(error or ""))
        return " ".join(part for part in parts if part).lower()

    @classmethod
    def _should_escalate_fetch_response(cls, fetch_response: Any) -> bool:
        if getattr(fetch_response, "success", False):
            document = getattr(fetch_response, "document", None)
            if document is None:
                return True
            return cls._looks_like_blocked_page(
                " ".join(
                    str(value or "")
                    for value in (
                        getattr(document, "title", ""),
                        getattr(document, "text", ""),
                        getattr(document, "html", ""),
                    )
                ),
                content_type=str(getattr(document, "content_type", "") or ""),
            )
        error_text = cls._fetch_response_error_text(fetch_response)
        return any(
            marker in error_text
            for marker in (
                "http_status_403",
                "http_status_429",
                "http_status_503",
                "cloudflare",
                "captcha",
                "access denied",
                "remote end closed connection",
                "connection aborted",
            )
        )

    @staticmethod
    def _blocked_fetch_method_order() -> List[str]:
        raw = str(os.getenv("LEGAL_SOURCE_RECOVERY_BLOCKED_FETCH_METHODS") or "").strip()
        if not raw:
            raw = "jina_reader,playwright,common_crawl,cloudflare_browser_rendering,wayback_machine"
        return [item.strip() for item in raw.split(",") if item.strip()]

    @classmethod
    def _escalated_fetch_url(cls, url: str, *, title_hint: Optional[str] = None) -> Any:
        timeout_seconds = max(
            1.0,
            float(os.getenv("LEGAL_SOURCE_RECOVERY_BLOCKED_FETCH_TIMEOUT_SECONDS", str(max(12.0, float(_FETCH_TIMEOUT_SECONDS))))),
        )
        methods = cls._blocked_fetch_method_order()

        def _payload_to_response(payload: Dict[str, Any]) -> Any:
            if not payload.get("success"):
                return types.SimpleNamespace(success=False, document=None, errors=list(payload.get("errors") or []))
            document_payload = dict(payload.get("document") or {})
            return types.SimpleNamespace(
                success=True,
                document=types.SimpleNamespace(
                    title=str(document_payload.get("title") or ""),
                    text=str(document_payload.get("text") or ""),
                    html=str(document_payload.get("html") or ""),
                    content_type=str(document_payload.get("content_type") or ""),
                    metadata=dict(document_payload.get("metadata") or {}),
                    extraction_provenance=dict(document_payload.get("extraction_provenance") or {}),
                ),
                errors=list(payload.get("errors") or []),
            )

        if not _env_flag("LEGAL_SOURCE_RECOVERY_BLOCKED_FETCH_USE_PROCESS", default=True):
            queue: Any = mp.Queue(maxsize=1)
            _blocked_fetch_escalation_worker(
                queue,
                url=url,
                title_hint=title_hint,
                methods=methods,
                timeout_seconds=timeout_seconds,
            )
            try:
                return _payload_to_response(dict(queue.get_nowait()))
            except Exception as exc:
                return types.SimpleNamespace(success=False, document=None, errors=[exc])

        start_method = str(os.getenv("LEGAL_SOURCE_RECOVERY_BLOCKED_FETCH_PROCESS_START_METHOD") or "").strip()
        if start_method:
            context = mp.get_context(start_method)
        else:
            available = set(mp.get_all_start_methods())
            context = mp.get_context("fork" if "fork" in available else "spawn")
        queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_blocked_fetch_escalation_worker,
            kwargs={
                "queue": queue,
                "url": url,
                "title_hint": title_hint,
                "methods": methods,
                "timeout_seconds": timeout_seconds,
            },
        )
        process.start()
        deadline = datetime.now().timestamp() + timeout_seconds
        while datetime.now().timestamp() < deadline:
            try:
                payload = dict(queue.get(timeout=min(0.2, max(0.01, deadline - datetime.now().timestamp()))))
                process.join(1)
                return _payload_to_response(payload)
            except queue_module.Empty:
                if not process.is_alive():
                    break
            except Exception:
                break

        process.join(max(0.0, deadline - datetime.now().timestamp()))
        if process.is_alive():
            process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
            return types.SimpleNamespace(success=False, document=None, errors=["blocked_fetch_escalation_timeout"])
        try:
            return _payload_to_response(dict(queue.get_nowait()))
        except Exception:
            return types.SimpleNamespace(success=False, document=None, errors=[f"blocked_fetch_escalation_exit_{process.exitcode}"])

    def _candidate_fetch_response(self, url: str, *, title_hint: Optional[str] = None) -> Any:
        fetch_factory = getattr(type(self), "_fetch_api_instance", None)
        fetch_factory_name = str(getattr(fetch_factory, "__name__", ""))
        if self._fetch_api is not None or fetch_factory_name != "_fetch_api_instance":
            return self._fetch_api_instance().fetch(
                url,
                domain="legal",
                metadata={
                    "title_hint": title_hint or "",
                    "suppress_relocation_search": True,
                },
            )
        response = self._lightweight_fetch_url(url, title_hint=title_hint)
        if (
            _env_flag("LEGAL_SOURCE_RECOVERY_ESCALATE_BLOCKED_FETCH", default=True)
            and self._should_escalate_fetch_response(response)
        ):
            escalated = self._escalated_fetch_url(url, title_hint=title_hint)
            if getattr(escalated, "success", False):
                return escalated
            original_errors = list(getattr(response, "errors", []) or [])
            original_errors.extend(getattr(escalated, "errors", []) or [])
            response.errors = original_errors
        return response

    def _patch_manager_instance(self, *, manifest_dir: Path) -> Any:
        if self._patch_manager is not None:
            return self._patch_manager
        try:
            from ...optimizers.agentic.patch_control import PatchManager

            return PatchManager(patches_dir=manifest_dir / "patches", enable_cache=False)
        except Exception:
            return _FallbackPatchManager(patches_dir=manifest_dir / "patches")

    def _search_backend_status(self) -> Dict[str, Any]:
        brave_api_key = str(
            os.getenv("BRAVE_API_KEY")
            or os.getenv("BRAVE_SEARCH_API_KEY")
            or ""
        ).strip()
        duckduckgo_available = False
        try:
            from ..web_archiving.search_engines.duckduckgo_adapter import HAVE_DDGS

            duckduckgo_available = bool(HAVE_DDGS)
        except Exception:
            duckduckgo_available = False

        datasets_available = False
        try:
            datasets_module = importlib.import_module("datasets")
            datasets_available = bool(getattr(datasets_module, "load_dataset", None))
        except Exception:
            datasets_available = False
        return {
            "brave_configured": bool(brave_api_key),
            "duckduckgo_configured": duckduckgo_available,
            "archive_search_available": bool(self._archive_searcher is not None),
            "live_search_available": bool(self._live_searcher is not None),
            "brave_api_key_env": "BRAVE_API_KEY" if os.getenv("BRAVE_API_KEY") else ("BRAVE_SEARCH_API_KEY" if os.getenv("BRAVE_SEARCH_API_KEY") else ""),
            "datasets_available": datasets_available,
        }

    async def _multi_engine_search(
        self,
        *,
        query: str,
        engines: List[str],
        max_results: int,
    ) -> Dict[str, Any]:
        from ..legal_scrapers.multi_engine_legal_search import multi_engine_legal_search

        return await multi_engine_legal_search(
            query=query,
            engines=engines,
            max_results=max_results,
            brave_api_key=(os.getenv("BRAVE_API_KEY") or os.getenv("BRAVE_SEARCH_API_KEY") or None),
        )

    @staticmethod
    def _official_hint_domains(*, corpus_key: Optional[str], state_code: Optional[str]) -> List[str]:
        corpus = str(corpus_key or "").strip().lower()
        state = str(state_code or "").strip().upper()
        if corpus == "us_code":
            return ["uscode.house.gov", "govinfo.gov", "law.cornell.edu"]
        if corpus == "federal_register":
            return ["federalregister.gov", "govinfo.gov"]
        if corpus == "caselaw_access_project":
            return ["courtlistener.com", "law.justia.com"]
        state_domains = {
            "AK": ["akleg.gov"],
            "AZ": ["azleg.gov"],
            "CA": ["leginfo.legislature.ca.gov", "courts.ca.gov"],
            "DC": ["code.dccouncil.gov"],
            "ID": ["legislature.idaho.gov"],
            "IA": ["legis.iowa.gov"],
            "KS": ["ksrevisor.gov"],
            "ME": ["mainelegislature.org"],
            "MI": ["legislature.mi.gov"],
            "MO": ["revisor.mo.gov"],
            "NC": ["ncleg.gov"],
            "NE": ["nebraskalegislature.gov"],
            "NV": ["leg.state.nv.us"],
            "NY": ["nysenate.gov", "nyassembly.gov", "dos.ny.gov", "nycourts.gov"],
            "OH": ["codes.ohio.gov"],
            "SD": ["sdlegislature.gov"],
            "TX": ["statutes.capitol.texas.gov", "texreg.sos.state.tx.us", "txcourts.gov"],
            "UT": ["le.utah.gov"],
            "WA": ["app.leg.wa.gov"],
            "WI": ["docs.legis.wisconsin.gov"],
            "WV": ["code.wvlegislature.gov"],
            "FL": ["leg.state.fl.us", "flrules.org", "flcourts.gov"],
            "GA": ["legis.ga.gov", "rules.sos.ga.gov", "georgiacourts.gov"],
            "IL": ["ilga.gov", "ilsos.gov", "illinoiscourts.gov"],
            "MA": ["malegislature.gov"],
            "MN": ["revisor.mn.gov", "mncourts.gov"],
            "OR": ["oregonlegislature.gov", "oregon.public.law", "courts.oregon.gov"],
            "PA": ["legis.state.pa.us", "pacodeandbulletin.gov", "pacourts.us"],
            "RI": ["webserver.rilegislature.gov"],
        }
        if corpus in {"state_laws", "state_admin_rules", "state_court_rules"}:
            return list(state_domains.get(state, []))
        return []

    @staticmethod
    def _citation_url_hint_results(
        *,
        citation_text: str,
        normalized_citation: Optional[str],
        corpus_key: Optional[str],
        state_code: Optional[str],
    ) -> List[Dict[str, Any]]:
        corpus = str(corpus_key or "").strip().lower()
        state = str(state_code or "").strip().upper()
        text = f"{citation_text or ''} {normalized_citation or ''}"
        rows: List[Dict[str, Any]] = []

        if corpus == "us_code":
            from ..legal_scrapers.federal_scrapers.us_code_scraper import build_public_law_url, build_uscode_section_url

            usc_match = re.search(r"\b([0-9]+)\s+U\.?S\.?C\.?(?:A\.?)?\s+(?:§|section|sec\.?)?\s*([0-9A-Za-z][\w\-]*(?:\([a-z0-9]+\))*)", text, re.IGNORECASE)
            if usc_match:
                title, section = usc_match.groups()
                rows.append(
                    {
                        "url": build_uscode_section_url(title, section),
                        "title": f"{title} U.S.C. section {section}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived official U.S. Code section URL.",
                    }
                )
            public_law_match = re.search(r"(?:Pub\.?\s+L\.?|P\.L\.?|Public\s+Law)\s+(?:No\.?\s*)?([0-9]+)-([0-9]+)", text, re.IGNORECASE)
            if public_law_match:
                congress, law_number = public_law_match.groups()
                rows.append(
                    {
                        "url": build_public_law_url(congress, law_number),
                        "title": f"Public Law {congress}-{law_number}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived Congress.gov public law URL.",
                    }
                )
            return rows

        if corpus == "federal_register":
            from ..legal_scrapers.federal_scrapers.federal_register_scraper import (
                build_ecfr_section_url,
                build_federal_register_citation_url,
            )

            cfr_match = re.search(r"\b([0-9]+)\s+C\.?F\.?R\.?\s+(?:§|section|sec\.?)?\s*([0-9]+(?:\.[\w-]+)*(?:\([a-z0-9]+\))*)", text, re.IGNORECASE)
            if cfr_match:
                title, section = cfr_match.groups()
                rows.append(
                    {
                        "url": build_ecfr_section_url(title, section),
                        "title": f"{title} C.F.R. section {section}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived official eCFR section URL.",
                    }
                )
            fr_match = re.search(r"\b([0-9]+)\s+(?:FR|Fed\.?\s+Reg\.?|Fed\.?\s+Register|Federal\s+Register)\s+([0-9]+)", text, re.IGNORECASE)
            if fr_match:
                volume, page = fr_match.groups()
                rows.append(
                    {
                        "url": build_federal_register_citation_url(volume, page),
                        "title": f"{volume} FR {page}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived Federal Register citation URL.",
                    }
                )
            return rows

        if corpus == "caselaw_access_project":
            try:
                from .citation_extraction import CitationExtractor

                for citation in CitationExtractor().extract_citations(text):
                    if citation.type != "case" or not citation.url:
                        continue
                    rows.append(
                        {
                            "url": citation.url,
                            "title": citation.text,
                            "source": "citation_url_hint",
                            "source_type": "current",
                            "snippet": "Citation-derived CourtListener-style case URL.",
                        }
                    )
            except Exception:
                return []
            return rows

        if corpus != "state_laws":
            return []

        section_patterns = [
            (
                "generic",
                r"\b(?:Minn\.\s+Stat\.|Minnesota\s+Statutes|ORS|Cal\.\s+[A-Za-z.\s]+Code|N\.Y\.\s+[A-Za-z.\s]+(?:Law|Act)|Tex\.\s+[A-Za-z.\s]+Code|Fla\.\s+Stat\.|Florida\s+Statutes)"
                r"\s*(?:§|section|sec\.?)?\s*(?P<section>[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)",
            ),
            (
                "ilcs",
                r"\b(?P<il_title>[0-9]+)\s+ILCS\s+(?P<il_act>[0-9]+)/(?P<section>[0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)",
            ),
            (
                "pa_cs",
                r"\b(?P<pa_title>[0-9]+)\s+Pa\.?\s*C\.?S\.?(?:A\.?)?\s*(?:§|section|sec\.?)?\s*(?P<section>[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)",
            ),
        ]
        section_match = None
        section_kind = ""
        extracted_state = state
        extracted_code_name = ""
        extracted_section = ""
        try:
            from .citation_extraction import CitationExtractor

            for citation in CitationExtractor().extract_citations(text):
                if citation.type != "state_statute":
                    continue
                citation_state = str(citation.jurisdiction or "").strip().upper()
                if state and citation_state and citation_state != state:
                    continue
                extracted_state = citation_state or state
                extracted_code_name = str((citation.metadata or {}).get("code_name") or citation.title or "").strip()
                extracted_section = str(citation.section or "").strip().strip(".")
                break
        except Exception:
            pass
        for candidate_kind, candidate_pattern in section_patterns:
            section_match = re.search(candidate_pattern, text, re.IGNORECASE)
            if section_match:
                section_kind = candidate_kind
                break
        if not section_match and extracted_section:
            section_kind = "extracted"
        if not section_match and not extracted_section:
            return []

        section = section_match.group("section").strip(".") if section_match else extracted_section
        from ..legal_scrapers.state_laws_scraper import build_state_law_section_url

        if state == "MN" or re.search(r"\b(?:Minn\.\s+Stat\.|Minnesota\s+Statutes)", text, re.IGNORECASE):
            rows.append(
                {
                    "url": build_state_law_section_url("MN", section, code_name="Stat."),
                    "title": f"Minnesota Statutes section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official Minnesota Revisor statute URL.",
                }
            )
        if state == "OR" or re.search(r"\bORS\b", text, re.IGNORECASE):
            chapter = section.split(".", 1)[0]
            rows.extend(
                [
                    {
                        "url": build_state_law_section_url("OR", section, code_name="ORS"),
                        "title": f"Oregon Revised Statutes {section}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived Oregon statute URL.",
                    },
                    {
                        "url": f"https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter}.html",
                        "title": f"Oregon Revised Statutes chapter {chapter}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived official Oregon Legislature chapter URL.",
                    },
                ]
            )
        if state == "CA" or re.search(r"\bCal\.", text, re.IGNORECASE):
            law_code = "FAM"
            code_name = "Fam. Code"
            if re.search(r"\bPenal\s+Code\b", text, re.IGNORECASE):
                law_code = "PEN"
                code_name = "Penal Code"
            elif re.search(r"\bCiv\.\s+Code\b", text, re.IGNORECASE):
                law_code = "CIV"
                code_name = "Civ. Code"
            rows.append(
                {
                    "url": build_state_law_section_url("CA", section, code_name=code_name),
                    "title": f"California {law_code} section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official California Legislature section URL.",
                }
            )
        if state == "NY" or re.search(r"\bN\.Y\.", text, re.IGNORECASE):
            law_code = "FCT" if re.search(r"\bFam\.\s+Ct\.\s+Act\b", text, re.IGNORECASE) else "DOM"
            code_name = "Fam. Ct. Act" if law_code == "FCT" else "Domestic Relations Law"
            rows.append(
                {
                    "url": build_state_law_section_url("NY", section, code_name=code_name),
                    "title": f"New York {law_code} section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official New York Senate legislation URL.",
                }
            )
        if state == "TX" or re.search(r"\bTex\.", text, re.IGNORECASE):
            law_code = "FA"
            code_name = "Fam. Code"
            if re.search(r"\bPenal\s+Code\b", text, re.IGNORECASE):
                law_code = "PE"
                code_name = "Penal Code"
            rows.append(
                {
                    "url": build_state_law_section_url("TX", section, code_name=code_name),
                    "title": f"Texas {law_code} section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official Texas Statutes section URL.",
                }
            )
        if state == "FL" or re.search(r"\b(?:Fla\.\s+Stat\.|Florida\s+Statutes)", text, re.IGNORECASE):
            rows.append(
                {
                    "url": build_state_law_section_url("FL", section, code_name="Fla. Stat."),
                    "title": f"Florida Statutes section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official Florida Legislature statute URL.",
                }
            )
        if state == "IL" or section_kind == "ilcs" or re.search(r"\bILCS\b", text, re.IGNORECASE):
            il_title = section_match.groupdict().get("il_title") or "750"
            il_act = section_match.groupdict().get("il_act") or "5"
            rows.append(
                {
                    "url": build_state_law_section_url("IL", section, code_name=f"{il_title} ILCS {il_act}"),
                    "title": f"Illinois Compiled Statutes {il_title} ILCS {il_act}/{section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official Illinois General Assembly ILCS URL.",
                }
            )
        if state == "PA" or section_kind == "pa_cs" or re.search(r"\bPa\.?\s*C\.?S\.?", text, re.IGNORECASE):
            pa_title = section_match.groupdict().get("pa_title") or "23"
            rows.append(
                {
                    "url": build_state_law_section_url("PA", section, code_name=f"{pa_title} Pa.C.S."),
                    "title": f"Pennsylvania Consolidated Statutes {pa_title} Pa.C.S. section {section}",
                    "source": "citation_url_hint",
                    "source_type": "current",
                    "snippet": "Citation-derived official Pennsylvania General Assembly consolidated statute URL.",
                }
            )
        if not rows and extracted_state:
            generic_url = build_state_law_section_url(extracted_state, section, code_name=extracted_code_name)
            if generic_url:
                rows.append(
                    {
                        "url": generic_url,
                        "title": f"{extracted_state} statute section {section}",
                        "source": "citation_url_hint",
                        "source_type": "current",
                        "snippet": "Citation-derived official state statute URL.",
                    }
                )
        return rows

    @staticmethod
    def _candidate_domains(*rows: Iterable[Dict[str, Any]]) -> List[str]:
        domains: List[str] = []
        seen: set[str] = set()
        for group in rows:
            for row in list(group or []):
                host = urlparse(str(row.get("url") or "")).netloc.lower()
                if not host or host in seen:
                    continue
                seen.add(host)
                domains.append(host)
        return domains

    async def _common_crawl_fallback_results(
        self,
        *,
        query: str,
        corpus_key: Optional[str],
        state_code: Optional[str],
        live_results: Iterable[Dict[str, Any]],
        archived_results: Iterable[Dict[str, Any]],
        max_candidates: int,
        backend_status: Dict[str, Any],
        citation_hint_results: Iterable[Dict[str, Any]] = (),
    ) -> List[Dict[str, Any]]:
        backend_status["common_crawl_available"] = False
        backend_status["common_crawl_domains"] = []
        backend_status["common_crawl_domain_count"] = 0
        backend_status["common_crawl_result_count"] = 0
        if not _env_flag("LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL", default=False):
            backend_status["common_crawl_error"] = "common_crawl_disabled"
            return []

        live_rows = list(live_results or [])
        archived_rows = list(archived_results or [])
        citation_hint_rows = list(citation_hint_results or [])
        should_search = (
            _env_flag("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_ALWAYS", default=False)
            or not live_rows
            or not archived_rows
        )
        if not should_search:
            return []

        domains: List[str] = []
        seen: set[str] = set()
        for domain in [
            *self._candidate_domains(citation_hint_rows),
            *self._official_hint_domains(corpus_key=corpus_key, state_code=state_code),
            *self._candidate_domains(live_rows, archived_rows),
        ]:
            normalized = str(domain or "").strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            domains.append(normalized)
            if len(domains) >= _MAX_COMMON_CRAWL_DOMAINS:
                break

        backend_status["common_crawl_domains"] = list(domains)
        backend_status["common_crawl_domain_count"] = len(domains)
        if not domains:
            backend_status["common_crawl_error"] = "no_common_crawl_domains"
            return []

        def _search_domain_hard_timeout(domain: str) -> Dict[str, Any]:
            start_method = str(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_PROCESS_START_METHOD") or "").strip()
            if start_method:
                context = mp.get_context(start_method)
            else:
                available = set(mp.get_all_start_methods())
                context = mp.get_context("fork" if "fork" in available else "spawn")
            queue = context.Queue(maxsize=1)
            process = context.Process(
                target=_common_crawl_domain_worker,
                kwargs={
                    "queue": queue,
                    "domain": domain,
                    "max_matches": max_candidates,
                    "query": query,
                    "jurisdiction_type": _jurisdiction_type_for_corpus(corpus_key),
                    "state_code": state_code,
                    "mode": str(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MODE") or "local").strip() or "local",
                    "mcp_endpoint": os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MCP_ENDPOINT") or None,
                    "timeout_seconds": _COMMON_CRAWL_TIMEOUT_SECONDS,
                },
            )
            process.start()
            process.join(_COMMON_CRAWL_TIMEOUT_SECONDS)
            if process.is_alive():
                process.terminate()
                process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join(1)
                return {"results": [], "error": "common_crawl_domain_timeout"}
            try:
                return dict(queue.get_nowait())
            except Exception:
                return {"results": [], "error": f"common_crawl_domain_exit_{process.exitcode}"}

        def _normalize_common_crawl_rows(domain: str, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
            normalized_rows: List[Dict[str, Any]] = []
            for row in list(rows or []):
                url = str(
                    row.get("url")
                    or row.get("archive_url")
                    or row.get("wayback_url")
                    or row.get("target_url")
                    or ""
                ).strip()
                if not url:
                    continue
                normalized_rows.append(
                    {
                        "url": url,
                        "title": str(row.get("title") or f"Common Crawl match for {domain}"),
                        "source": "common_crawl_indexes",
                        "source_type": "archived",
                        "search_domain": domain,
                        "snippet": str(row.get("snippet") or row.get("mime") or row.get("status") or ""),
                        "common_crawl_record": {
                            key: value
                            for key, value in row.items()
                            if key in {"timestamp", "collection", "mime", "status", "digest", "filename", "offset", "length"}
                        },
                    }
                )
            return normalized_rows

        def _search_domains() -> List[Dict[str, Any]]:
            results: List[Dict[str, Any]] = []
            domain_errors: Dict[str, str] = {}
            for domain in domains:
                if _env_flag("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_USE_PROCESS", default=True):
                    domain_payload = _search_domain_hard_timeout(domain)
                    rows = list(domain_payload.get("results") or [])
                    error = str(domain_payload.get("error") or "").strip()
                    if error:
                        domain_errors[domain] = error
                    results.extend(_normalize_common_crawl_rows(domain, rows))
                    continue

                from ..web_archiving.common_crawl_integration import CommonCrawlSearchEngine

                try:
                    engine = CommonCrawlSearchEngine(
                        mode=str(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MODE") or "local").strip() or "local",
                        mcp_endpoint=os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MCP_ENDPOINT") or None,
                        mcp_timeout=_COMMON_CRAWL_TIMEOUT_SECONDS,
                    )
                    if not engine.is_available():
                        domain_errors[domain] = "common_crawl_unavailable"
                        continue
                    rows = engine.search_domain(
                        domain,
                        max_matches=max(1, max_candidates),
                        query=query,
                        jurisdiction_type=_jurisdiction_type_for_corpus(corpus_key),
                        state_code=state_code,
                        year=os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_YEAR") or None,
                        max_parquet_files=int(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_MAX_PARQUET_FILES", "8")),
                        per_parquet_limit=int(os.getenv("LEGAL_SOURCE_RECOVERY_COMMON_CRAWL_PER_PARQUET_LIMIT", "200")),
                    )
                    results.extend(_normalize_common_crawl_rows(domain, rows))
                except Exception as exc:
                    domain_errors[domain] = str(exc)
                    continue
            if domain_errors:
                backend_status["common_crawl_domain_errors"] = dict(domain_errors)
            return results

        try:
            payload = await self._run_sync_with_timeout(
                _search_domains,
                timeout_seconds=(_COMMON_CRAWL_TIMEOUT_SECONDS * max(1, len(domains))) + 2.0,
            )
        except asyncio.TimeoutError:
            backend_status["common_crawl_error"] = "common_crawl_timeout"
            return []
        except Exception as exc:
            backend_status["common_crawl_error"] = str(exc)
            return []

        results = list(payload or [])
        backend_status["common_crawl_used"] = True
        backend_status["common_crawl_available"] = bool(results)
        backend_status["common_crawl_result_count"] = len(results)
        if not results and not backend_status.get("common_crawl_error"):
            backend_status["common_crawl_error"] = "common_crawl_no_results"
        return results

    async def _run_sync_with_timeout(
        self,
        func: Callable[..., Any],
        *,
        timeout_seconds: float,
        **kwargs: Any,
    ) -> Any:
        with anyio.fail_after(max(0.001, float(timeout_seconds))):
            return await anyio.to_thread.run_sync(lambda: func(**kwargs), abandon_on_cancel=True)

    async def _await_with_timeout(self, awaitable: Any, *, timeout_seconds: float) -> Any:
        try:
            with anyio.fail_after(max(0.001, float(timeout_seconds))):
                return await awaitable
        except RuntimeError as exc:
            if "no running event loop" in str(exc):
                raise TimeoutError("awaitable requires an asyncio event loop") from exc
            raise

    async def recover_unresolved_citation(
        self,
        *,
        citation_text: str,
        normalized_citation: Optional[str] = None,
        corpus_key: Optional[str],
        state_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
    ) -> LegalSourceRecoveryResult:
        recovery_corpus_key = infer_recovery_corpus_key(corpus_key=corpus_key, metadata=metadata)
        corpus = get_canonical_legal_corpus(recovery_corpus_key) if recovery_corpus_key else None
        query = build_missing_citation_recovery_query(
            citation_text,
            corpus_key=recovery_corpus_key,
            state_code=state_code,
        )
        jurisdiction_type = _jurisdiction_type_for_corpus(recovery_corpus_key)

        searcher = self._searcher()
        citation_hint_results = self._citation_url_hint_results(
            citation_text=citation_text,
            normalized_citation=normalized_citation,
            corpus_key=recovery_corpus_key,
            state_code=state_code,
        )
        live_results: List[Dict[str, Any]] = []
        archived_results: List[Dict[str, Any]] = []
        backend_status = self._search_backend_status()
        backend_status["archive_search_error"] = ""
        backend_status["live_search_error"] = ""
        backend_status["multi_engine_error"] = ""
        backend_status["common_crawl_error"] = ""
        backend_status["multi_engine_used"] = False
        backend_status["common_crawl_used"] = False
        backend_status["engines_attempted"] = []
        skip_live_search = _env_flag("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH", default=False)
        backend_status["live_search_skipped"] = bool(skip_live_search)

        effective_live_searcher = self._live_searcher or getattr(searcher, "legal_searcher", None)
        if skip_live_search:
            backend_status["live_search_error"] = "live_search_skipped"
            backend_status["multi_engine_error"] = "multi_engine_skipped"
        elif effective_live_searcher is not None:
            try:
                live_payload = await self._run_sync_with_timeout(
                    effective_live_searcher.search,
                    timeout_seconds=_SEARCH_TIMEOUT_SECONDS,
                    query=query,
                    max_results=max_candidates,
                )
                live_results = list((live_payload or {}).get("results", []) or [])
            except asyncio.TimeoutError:
                live_results = []
                backend_status["live_search_error"] = "live_search_timeout"
            except Exception:
                live_results = []
                backend_status["live_search_error"] = "live_search_failed"

        if not live_results and not skip_live_search:
            try:
                engines: List[str] = []
                # Avoid immediately reusing Brave in the multi-engine fallback if the
                # primary live search path already exercised the Brave-backed stack.
                if backend_status["brave_configured"] and effective_live_searcher is None:
                    engines.append("brave")
                if backend_status["duckduckgo_configured"]:
                    engines.append("duckduckgo")
                backend_status["engines_attempted"] = list(engines)
                if engines:
                    multi_engine_payload = await self._await_with_timeout(
                        self._multi_engine_search(
                            query=query,
                            engines=engines,
                            max_results=max_candidates,
                        ),
                        timeout_seconds=_SEARCH_TIMEOUT_SECONDS,
                    )
                    backend_status["multi_engine_used"] = True
                    if str(multi_engine_payload.get("status") or "").lower() == "success":
                        live_results = [
                            {
                                "title": str(item.get("title") or ""),
                                "url": str(item.get("url") or ""),
                                "source": str(item.get("source") or item.get("engine") or "multi_engine"),
                                "source_type": "current",
                            }
                            for item in list(multi_engine_payload.get("results") or [])
                            if str(item.get("url") or "").strip()
                        ]
                    else:
                        backend_status["multi_engine_error"] = str(multi_engine_payload.get("message") or "multi_engine_search_failed")
                else:
                    backend_status["multi_engine_error"] = "no_search_engines_available"
            except asyncio.TimeoutError:
                backend_status["multi_engine_error"] = "multi_engine_timeout"
            except Exception as exc:
                backend_status["multi_engine_error"] = str(exc)

        effective_archive_searcher = self._archive_searcher or searcher
        if int(archive_top_k or 0) <= 0:
            backend_status["archive_search_error"] = "archive_search_skipped"
        elif effective_archive_searcher is not None and hasattr(effective_archive_searcher, "search_with_indexes"):
            try:
                archive_payload = await self._run_sync_with_timeout(
                    effective_archive_searcher.search_with_indexes,
                    timeout_seconds=_SEARCH_TIMEOUT_SECONDS,
                    query=query,
                    jurisdiction_type=jurisdiction_type,
                    state_code=state_code,
                    max_results=max_candidates,
                )
                archived_results = list((archive_payload or {}).get("results", []) or [])
            except asyncio.TimeoutError:
                archived_results = []
                backend_status["archive_search_error"] = "archive_search_timeout"
            except Exception as exc:
                archived_results = []
                backend_status["archive_search_error"] = str(exc)

        common_crawl_results = await self._common_crawl_fallback_results(
            query=query,
            corpus_key=recovery_corpus_key,
            state_code=state_code,
            citation_hint_results=citation_hint_results,
            live_results=live_results,
            archived_results=archived_results,
            max_candidates=max_candidates,
            backend_status=backend_status,
        )

        merged_results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for source_type, rows in (("current", citation_hint_results), ("current", live_results), ("archived", archived_results), ("common_crawl", common_crawl_results)):
            for row in rows:
                url = str(row.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged_results.append({**row, "source_type": row.get("source_type") or source_type})

        candidates = [
            LegalSourceCandidate(
                url=str(row.get("url") or ""),
                title=str(row.get("title") or "") or None,
                source_type=str(row.get("source_type") or "") or None,
                source=str(row.get("source") or row.get("search_domain") or "") or None,
                score=_score_candidate(row, corpus_key=recovery_corpus_key, state_code=state_code),
            )
            for row in merged_results
        ]
        candidates.sort(key=lambda item: (-item.score, item.url))

        archived_sources: List[ArchivedSourceRecord] = []
        if candidates and archive_top_k > 0:
            archiver = self._archiver_instance()
            try:
                archive_results = await self._await_with_timeout(
                    archiver.archive_urls_parallel(
                        [item.url for item in candidates[:archive_top_k]],
                        jurisdiction=jurisdiction_type,
                        state_code=state_code,
                    ),
                    timeout_seconds=_ARCHIVE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                backend_status["archive_search_error"] = (
                    f"{backend_status['archive_search_error']};archiver_timeout"
                    if backend_status["archive_search_error"]
                    else "archiver_timeout"
                )
                archive_results = []
            for item in archive_results:
                archived_sources.append(
                    ArchivedSourceRecord(
                        url=str(getattr(item, "url", "") or ""),
                        success=bool(getattr(item, "success", False)),
                        source=str(getattr(item, "source", "") or "") or None,
                        error=str(getattr(item, "error", "") or "") or None,
                        archived_at=getattr(item, "timestamp", None).isoformat() if getattr(item, "timestamp", None) else None,
                    )
                )

        candidate_files: List[RecoveredCandidateFile] = []
        scraper_patch: Optional[RecoveryScraperPatch] = None
        if self._enable_candidate_file_fetch:
            candidate_files = self._discover_candidate_files(
                candidates=candidates,
                corpus_key=recovery_corpus_key,
                state_code=state_code,
            )

        manifest_dir, manifest_path = self._write_manifest(
            citation_text=citation_text,
            normalized_citation=normalized_citation or citation_text,
            corpus=corpus,
            state_code=state_code,
            query=query,
            candidates=candidates,
            archived_sources=archived_sources,
            candidate_files=candidate_files,
            search_backend_status=backend_status,
        )

        if self._enable_candidate_file_fetch:
            candidate_files = self._materialize_candidate_file_artifacts(
                manifest_dir=manifest_dir,
                candidate_files=candidate_files,
                citation_text=citation_text,
                normalized_citation=normalized_citation or citation_text,
            )
        scraper_patch = self._write_scraper_patch_scaffold(
            manifest_dir=manifest_dir,
            citation_text=citation_text,
            normalized_citation=normalized_citation or citation_text,
            corpus_key=recovery_corpus_key,
            candidates=candidates,
            candidate_files=candidate_files,
        )
        self._rewrite_manifest_with_artifacts(
            manifest_path=manifest_path,
            candidate_files=candidate_files,
            scraper_patch=scraper_patch,
        )

        publish_plan = None
        publish_report = None
        promotion_preview = None
        release_plan_preview = None
        if corpus is not None:
            publish_plan = {
                "repo_id": corpus.hf_dataset_id,
                "local_dir": str(manifest_dir),
                "path_in_repo": f"source_recovery/{manifest_dir.name}",
                "allow_patterns": [
                    "*.json",
                    "candidate_files/*",
                    "patches/*",
                ],
                "cid_column": corpus.cid_field,
                "publish_command": (
                    f"python scripts/repair/publish_parquet_to_hf.py --local-dir {manifest_dir} "
                    f"--repo-id {corpus.hf_dataset_id} --path-in-repo source_recovery/{manifest_dir.name}"
                ),
            }
            if publish_to_hf:
                publish_report = self._publisher()(
                    local_dir=manifest_dir,
                    repo_id=corpus.hf_dataset_id,
                    commit_message=f"Track missing legal source for {normalized_citation or citation_text}",
                    create_repo=False,
                    token=hf_token,
                    path_in_repo=publish_plan["path_in_repo"],
                    allow_patterns=publish_plan["allow_patterns"],
                    do_verify=False,
                    cid_column=corpus.cid_field,
                )
        try:
            promotion_preview = build_recovery_manifest_promotion_row(str(manifest_path))
        except Exception:
            promotion_preview = None
        try:
            release_plan_preview = build_recovery_manifest_release_plan(str(manifest_path))
        except Exception:
            release_plan_preview = None

        return LegalSourceRecoveryResult(
            status="tracked_and_published" if publish_report else "tracked",
            citation_text=citation_text,
            normalized_citation=normalized_citation or citation_text,
            corpus_key=recovery_corpus_key,
            hf_dataset_id=corpus.hf_dataset_id if corpus is not None else None,
            state_code=state_code,
            search_query=query,
            candidate_count=len(candidates),
            archived_count=sum(1 for item in archived_sources if item.success),
            candidates=candidates,
            archived_sources=archived_sources,
            manifest_path=str(manifest_path),
            manifest_directory=str(manifest_dir),
            publish_report=publish_report,
            publish_plan=publish_plan,
            promotion_preview=promotion_preview,
            release_plan_preview=release_plan_preview,
            feedback_entry={
                "citation_text": citation_text,
                "normalized_citation": normalized_citation or citation_text,
                "corpus_key": recovery_corpus_key,
                "state_code": state_code,
                "candidate_corpora": list((metadata or {}).get("candidate_corpora") or []),
            },
            search_backend_status=backend_status,
            candidate_files=candidate_files,
            scraper_patch=scraper_patch,
        )

    @staticmethod
    def _file_extension_from_url(url: str) -> Optional[str]:
        suffix = Path(urlparse(str(url or "")).path).suffix.lower()
        return suffix or None

    @staticmethod
    def _content_type_matches_downloadable(content_type: Optional[str]) -> bool:
        lowered = str(content_type or "").split(";", 1)[0].strip().lower()
        return lowered in DOWNLOADABLE_CONTENT_TYPE_SUFFIXES

    @classmethod
    def _is_downloadable_legal_file(
        cls,
        *,
        url: str,
        title: Optional[str],
        content_type: Optional[str] = None,
    ) -> bool:
        ext = cls._file_extension_from_url(url)
        if ext in DOWNLOADABLE_LEGAL_FILE_EXTENSIONS:
            return True
        if cls._content_type_matches_downloadable(content_type):
            return True
        hay = f"{url} {title or ''}".lower()
        return ("download" in hay or "document" in hay) and any(term in hay for term in LEGAL_FILE_HINT_TERMS)

    @staticmethod
    def _candidate_file_score(
        *,
        url: str,
        title: Optional[str],
        content_type: Optional[str],
        state_code: Optional[str],
        discovered_from_url: Optional[str] = None,
    ) -> int:
        score = 0
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        hay = f"{url} {title or ''} {content_type or ''}".lower()
        ext = Path(parsed.path).suffix.lower()
        discovered = str(discovered_from_url or "").strip()
        if discovered:
            discovered_parsed = urlparse(discovered)
            if url == discovered:
                score += 4
            elif domain == discovered_parsed.netloc.lower() and parsed.path == discovered_parsed.path:
                score += 2
        if domain.endswith(".gov") or ".gov" in domain:
            score += 4
        if domain.endswith(".us") or ".state." in domain:
            score += 3
        if ext == ".pdf":
            score += 5
        elif ext in {".xml", ".json", ".docx", ".doc", ".rtf", ".zip"}:
            score += 3
        if content_type and LegalSourceRecoveryWorkflow._content_type_matches_downloadable(content_type):
            score += 3
        if state_code and state_code.lower() in hay:
            score += 2
        if any(term in hay for term in LEGAL_FILE_HINT_TERMS):
            score += 3
        return score

    @classmethod
    def _register_candidate_file(
        cls,
        *,
        storage: Dict[str, RecoveredCandidateFile],
        url: str,
        title: Optional[str],
        discovered_from_url: Optional[str],
        source: Optional[str],
        source_type: Optional[str],
        content_type: Optional[str],
        state_code: Optional[str],
    ) -> None:
        normalized_url = str(url or "").strip()
        if not normalized_url:
            return
        is_downloadable = cls._is_downloadable_legal_file(url=normalized_url, title=title, content_type=content_type)
        if not is_downloadable and source != "citation_url_hint":
            return
        score = cls._candidate_file_score(
            url=normalized_url,
            title=title,
            content_type=content_type,
            state_code=state_code,
            discovered_from_url=discovered_from_url,
        )
        if source == "citation_url_hint":
            score += 10
        existing = storage.get(normalized_url)
        if existing is None:
            storage[normalized_url] = RecoveredCandidateFile(
                url=normalized_url,
                title=title or None,
                discovered_from_url=discovered_from_url,
                source=source,
                source_type=source_type,
                score=score,
                content_type=content_type or None,
                file_extension=cls._file_extension_from_url(normalized_url),
            )
            return
        if title and not existing.title:
            existing.title = title
        if discovered_from_url and not existing.discovered_from_url:
            existing.discovered_from_url = discovered_from_url
        if source and not existing.source:
            existing.source = source
        if source_type and not existing.source_type:
            existing.source_type = source_type
        if content_type and not existing.content_type:
            existing.content_type = content_type
        existing.score = max(existing.score, score)

    @classmethod
    def _linked_candidate_matches_citation_hint(
        cls,
        *,
        parent_candidate: LegalSourceCandidate,
        link_url: str,
        link_title: str,
    ) -> bool:
        fragments = cls._citation_validation_fragments(
            citation_text=str(parent_candidate.title or ""),
            normalized_citation=str(parent_candidate.title or ""),
        )
        hay = f"{link_url or ''} {link_title or ''}"
        return any(fragment and cls._fragment_in_text(fragment, hay) for fragment in fragments)

    def _discover_candidate_files(
        self,
        *,
        candidates: Iterable[LegalSourceCandidate],
        corpus_key: Optional[str],
        state_code: Optional[str],
    ) -> List[RecoveredCandidateFile]:
        del corpus_key
        discovered: Dict[str, RecoveredCandidateFile] = {}

        for candidate in list(candidates)[:_MAX_CANDIDATE_DISCOVERY_PAGES]:
            self._register_candidate_file(
                storage=discovered,
                url=candidate.url,
                title=candidate.title,
                discovered_from_url=candidate.url,
                source=candidate.source,
                source_type=candidate.source_type,
                content_type=None,
                state_code=state_code,
            )

            try:
                fetch_response = self._candidate_fetch_response(candidate.url, title_hint=candidate.title)
            except Exception:
                continue

            document = getattr(fetch_response, "document", None)
            if not getattr(fetch_response, "success", False) or document is None:
                continue

            document_metadata = dict(getattr(document, "metadata", {}) or {})
            document_content_type = str(
                getattr(document, "content_type", "")
                or document_metadata.get("content_type")
                or ""
            ).strip()
            self._register_candidate_file(
                storage=discovered,
                url=candidate.url,
                title=candidate.title or getattr(document, "title", "") or None,
                discovered_from_url=candidate.url,
                source=candidate.source,
                source_type=candidate.source_type,
                content_type=document_content_type or None,
                state_code=state_code,
            )

            for link in list(document_metadata.get("links") or [])[:12]:
                if not isinstance(link, dict):
                    continue
                link_url = str(link.get("url") or "")
                link_title = str(link.get("text") or "")
                if (
                    candidate.source == "citation_url_hint"
                    and not self._linked_candidate_matches_citation_hint(
                        parent_candidate=candidate,
                        link_url=link_url,
                        link_title=link_title,
                    )
                ):
                    continue
                self._register_candidate_file(
                    storage=discovered,
                    url=link_url,
                    title=link_title or None,
                    discovered_from_url=candidate.url,
                    source=candidate.source,
                    source_type=candidate.source_type,
                    content_type=None,
                    state_code=state_code,
                )

        files = list(discovered.values())
        files.sort(key=lambda item: (-item.score, item.url))
        return files[:_MAX_CANDIDATE_FETCHES]

    @staticmethod
    def _artifact_suffix(*, url: str, content_type: Optional[str], has_bytes: bool) -> str:
        ext = Path(urlparse(url).path).suffix.lower()
        lowered = str(content_type or "").split(";", 1)[0].strip().lower()
        if "html" in lowered and (not ext or not ext.lstrip(".").isalpha()):
            return ".html"
        if ext and (ext in DOWNLOADABLE_LEGAL_FILE_EXTENSIONS or ext.lstrip(".").isalpha()):
            return ext
        if lowered in DOWNLOADABLE_CONTENT_TYPE_SUFFIXES:
            return DOWNLOADABLE_CONTENT_TYPE_SUFFIXES[lowered]
        if has_bytes:
            return ".bin"
        return ".txt"

    @staticmethod
    def _safe_metadata_excerpt(text: str, *, limit: int = 1200) -> str:
        cleaned = " ".join(str(text or "").split())
        return cleaned[:limit]

    @staticmethod
    def _extract_pdf_text(raw_bytes: Any) -> str:
        if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
            return ""
        max_pages = max(1, int(os.getenv("LEGAL_SOURCE_RECOVERY_PDF_VALIDATION_MAX_PAGES", "64")))
        max_chars = max(1000, int(os.getenv("LEGAL_SOURCE_RECOVERY_PDF_VALIDATION_MAX_CHARS", "200000")))
        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except Exception:
                return ""

        try:
            reader = PdfReader(io.BytesIO(bytes(raw_bytes)))
            chunks: List[str] = []
            for page in list(getattr(reader, "pages", []) or [])[:max_pages]:
                try:
                    chunks.append(str(page.extract_text() or ""))
                except Exception:
                    continue
                if sum(len(chunk) for chunk in chunks) >= max_chars:
                    break
            return "\n".join(chunks)[:max_chars]
        except Exception:
            return ""

    @staticmethod
    def _citation_validation_fragments(*, citation_text: str, normalized_citation: str) -> List[str]:
        text = f"{citation_text or ''} {normalized_citation or ''}"
        fragments: List[str] = []
        for value in (citation_text, normalized_citation):
            cleaned = " ".join(str(value or "").split()).strip()
            if cleaned and cleaned not in fragments:
                fragments.append(cleaned)
        section_matches = re.findall(r"(?:§|section|sec\.?)\s*([0-9A-Za-z][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)", text, flags=re.IGNORECASE)
        for section in section_matches:
            cleaned_section = str(section or "").strip().strip(".")
            if cleaned_section and cleaned_section not in fragments:
                fragments.append(cleaned_section)
        numeric_sections = re.findall(
            r"\b[0-9][0-9A-Za-z]*(?:[.:\-][0-9A-Za-z]*[0-9][0-9A-Za-z]*)+(?:\([a-z0-9]+\))*\b",
            text,
            flags=re.IGNORECASE,
        )
        for section in numeric_sections:
            cleaned_section = str(section or "").strip().strip(".")
            if cleaned_section and cleaned_section not in fragments:
                fragments.append(cleaned_section)
            tail = re.split(r"[.:\-]", cleaned_section)[-1]
            if len(tail) >= 3 and tail != cleaned_section and tail not in fragments:
                fragments.append(tail)
        usc_match = re.search(r"\b([0-9]+)\s+U\.?S\.?C\.?(?:A\.?)?\s+§?\s*([0-9A-Za-z][\w.\-]*)", text, flags=re.IGNORECASE)
        if usc_match:
            for fragment in (usc_match.group(1), usc_match.group(2), f"{usc_match.group(1)} {usc_match.group(2)}"):
                if fragment and fragment not in fragments:
                    fragments.append(fragment)
        return fragments[:8]

    @staticmethod
    def _fragment_in_text(fragment: str, text: str) -> bool:
        fragment = str(fragment or "").strip().lower()
        hay = str(text or "").lower()
        if not fragment or not hay:
            return False
        if fragment in hay:
            return True
        compact_fragment = re.sub(r"[^a-z0-9]+", "", fragment)
        if len(compact_fragment) < 3:
            return False
        compact_hay = re.sub(r"[^a-z0-9]+", "", hay)
        return compact_fragment in compact_hay

    @staticmethod
    def _has_legal_body_signal(text: str) -> bool:
        cleaned = " ".join(re.sub(r"<[^>]+>", " ", str(text or "")).split()).lower()
        if len(cleaned) < 120:
            return False
        signals = re.findall(
            r"\b(shall|must|may|means|defined|subsection|paragraph|chapter|article|"
            r"offense|penalty|violation|commits|guilty|liability|prohibited|"
            r"effective|amended|enacted|statute|code|section|person|injury)\b",
            cleaned,
        )
        return len(signals) >= 2

    @classmethod
    def _validate_candidate_content(
        cls,
        *,
        citation_text: str,
        normalized_citation: str,
        url: str,
        title: Optional[str],
        content_type: Optional[str],
        text: str,
        html: str,
    ) -> Dict[str, Any]:
        source_text = " ".join(str(value or "") for value in (text, html))
        hay = re.sub(r"\s+", " ", source_text).lower()
        title_url_text = f"{title or ''} {url or ''}"
        fragments = cls._citation_validation_fragments(
            citation_text=citation_text,
            normalized_citation=normalized_citation,
        )
        matched_fragments = [
            fragment
            for fragment in fragments
            if fragment and cls._fragment_in_text(fragment, hay)
        ]
        title_url_matched_fragments = [
            fragment
            for fragment in fragments
            if fragment and cls._fragment_in_text(fragment, title_url_text)
        ]
        no_result_markers = (
            "no matches",
            "no results",
            "page not found",
            "file not found",
            "does not exist",
            "invalid section",
            "unable to locate",
            "search returned no",
            "there are no",
            "no law information found",
            "your search did not match",
        )
        no_result_marker_present = any(marker in hay for marker in no_result_markers)
        exact_citation_present = any(
            str(value or "").strip() and cls._fragment_in_text(str(value or ""), hay)
            for value in (citation_text, normalized_citation)
        )
        section_fragment_present = any(
            fragment for fragment in matched_fragments if re.search(r"\d", fragment)
        )
        title_url_section_fragment_present = any(
            fragment for fragment in title_url_matched_fragments if re.search(r"\d", fragment)
        )
        multi_fragment_present = len(set(matched_fragments)) >= 2
        legal_body_signal = cls._has_legal_body_signal(source_text)
        no_result_detected = bool(no_result_marker_present and not (section_fragment_present and legal_body_signal))
        confirmed = bool(
            not no_result_detected
            and (
                exact_citation_present
                or (
                    section_fragment_present
                    and legal_body_signal
                    and (multi_fragment_present or title_url_section_fragment_present)
                )
            )
        )
        confidence = 0.0
        if exact_citation_present:
            confidence += 0.7
        if section_fragment_present and multi_fragment_present:
            confidence += 0.2
        if section_fragment_present and title_url_section_fragment_present:
            confidence += 0.25
        if legal_body_signal:
            confidence += 0.15
        if no_result_detected:
            confidence -= 0.6
        if cls._looks_like_blocked_page(source_text, content_type=content_type):
            confidence -= 0.4
        confidence = max(0.0, min(1.0, confidence))
        return {
            "citation_text": citation_text,
            "normalized_citation": normalized_citation,
            "checked_fragments": fragments,
            "matched_fragments": matched_fragments,
            "title_url_matched_fragments": title_url_matched_fragments,
            "exact_citation_present": exact_citation_present,
            "section_fragment_present": section_fragment_present,
            "title_url_section_fragment_present": title_url_section_fragment_present,
            "multi_fragment_present": multi_fragment_present,
            "legal_body_signal": legal_body_signal,
            "no_result_marker_present": no_result_marker_present,
            "no_result_detected": no_result_detected,
            "content_type": content_type,
            "confirmed": confirmed,
            "confidence": confidence,
        }

    @staticmethod
    def _looks_like_blocked_page(text: str, *, content_type: Optional[str] = None) -> bool:
        hay = f"{content_type or ''} {text or ''}".lower()
        blocked_markers = (
            "attention required",
            "cloudflare",
            "enable javascript",
            "checking your browser",
            "access denied",
            "request blocked",
            "request access",
            "captcha",
            "please verify you are human",
        )
        return any(marker in hay for marker in blocked_markers)

    @staticmethod
    def _recommended_parser_kind(*, url: str, content_type: Optional[str], has_bytes: bool) -> str:
        suffix = Path(urlparse(url).path).suffix.lower()
        lowered = str(content_type or "").split(";", 1)[0].strip().lower()
        if suffix == ".pdf" or lowered == "application/pdf":
            return "pdf"
        if suffix in {".xml", ".json", ".csv"} or lowered in {"application/xml", "text/xml", "application/json", "text/json", "text/csv"}:
            return suffix.lstrip(".") or lowered
        if "html" in lowered:
            return "html"
        if lowered.startswith("text/"):
            return "text"
        if has_bytes:
            return "binary"
        return "html_or_text"

    @classmethod
    def _build_extraction_recipe(
        cls,
        *,
        url: str,
        title: Optional[str],
        content_type: Optional[str],
        text: str,
        html: str,
        has_bytes: bool,
    ) -> Dict[str, Any]:
        host = urlparse(str(url or "")).netloc.lower()
        parser_kind = cls._recommended_parser_kind(url=url, content_type=content_type, has_bytes=has_bytes)
        source_text = text or html
        return {
            "host": host,
            "candidate_url": url,
            "title": title,
            "content_type": content_type,
            "parser_kind": parser_kind,
            "blocked_signals_detected": cls._looks_like_blocked_page(source_text, content_type=content_type),
            "preferred_fetch_path": "UnifiedWebArchivingAPI.fetch(url, domain=\"legal\")",
            "fallback_fetch_paths": [
                "UnifiedWebScraper.scrape_sync(url)",
                "CommonCrawlSearchEngine.search_domain(host, query=citation_query)",
                "HuggingFace Common Crawl fallback when local Common Crawl indexes are unavailable",
            ],
            "html_selectors": [
                "main",
                "article",
                "#content",
                ".content",
                ".main-content",
                ".document",
                ".statute",
                ".law",
                "pre",
            ],
            "text_excerpt": cls._safe_metadata_excerpt(source_text),
            "recommended_scraper_function": f"_extract_recovered_{_slugify(host or 'host', limit=32).replace('-', '_')}_text",
        }

    def _materialize_candidate_file_artifacts(
        self,
        *,
        manifest_dir: Path,
        candidate_files: Iterable[RecoveredCandidateFile],
        citation_text: str,
        normalized_citation: str,
    ) -> List[RecoveredCandidateFile]:
        artifacts_dir = manifest_dir / "candidate_files"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        materialized: List[RecoveredCandidateFile] = []
        candidate_file_list = list(candidate_files)
        for index, item in enumerate(candidate_file_list[:_MAX_CANDIDATE_FETCHES], start=1):
            updated = RecoveredCandidateFile(**asdict(item))
            escalation_errors: List[str] = []
            try:
                fetch_response = self._candidate_fetch_response(updated.url, title_hint=updated.title)
            except Exception as exc:
                updated.fetch_success = False
                updated.notes = f"fetch_exception: {exc}"
                materialized.append(updated)
                continue

            document = getattr(fetch_response, "document", None)
            if not getattr(fetch_response, "success", False) or document is None:
                updated.fetch_success = False
                errors = getattr(fetch_response, "errors", None) or []
                updated.notes = "; ".join(str(getattr(err, "message", err)) for err in errors) or "fetch_failed"
                materialized.append(updated)
                continue

            def _unpack_document(candidate_document: Any) -> tuple[Dict[str, Any], Optional[str], Any, bool, str, str]:
                candidate_metadata = dict(getattr(candidate_document, "metadata", {}) or {})
                candidate_content_type = (
                    str(getattr(candidate_document, "content_type", "") or candidate_metadata.get("content_type") or "").strip()
                    or None
                )
                candidate_raw_bytes = candidate_metadata.get("raw_bytes")
                candidate_has_bytes = isinstance(candidate_raw_bytes, (bytes, bytearray)) and len(candidate_raw_bytes) > 0
                candidate_text = str(getattr(candidate_document, "text", "") or "")
                candidate_html = str(getattr(candidate_document, "html", "") or candidate_metadata.get("html", "") or "")
                if (
                    candidate_has_bytes
                    and not candidate_text
                    and str(candidate_content_type or "").split(";", 1)[0].strip().lower() == "application/pdf"
                ):
                    candidate_text = self._extract_pdf_text(candidate_raw_bytes)
                return (
                    candidate_metadata,
                    candidate_content_type,
                    candidate_raw_bytes,
                    candidate_has_bytes,
                    candidate_text,
                    candidate_html,
                )

            metadata, content_type, raw_bytes, has_bytes, document_text, document_html = _unpack_document(document)

            extraction_recipe = self._build_extraction_recipe(
                url=updated.url,
                title=updated.title,
                content_type=content_type,
                text=document_text,
                html=document_html,
                has_bytes=has_bytes,
            )
            candidate_validation = self._validate_candidate_content(
                citation_text=citation_text,
                normalized_citation=normalized_citation,
                url=updated.url,
                title=updated.title,
                content_type=content_type,
                text=document_text,
                html=document_html,
            )
            provenance = dict(getattr(document, "extraction_provenance", {}) or {})
            if (
                not candidate_validation.get("confirmed")
                and _env_flag("LEGAL_SOURCE_RECOVERY_ESCALATE_UNCONFIRMED_FETCH", default=True)
                and provenance.get("method") != "blocked_fetch_escalation"
            ):
                escalated_response = self._escalated_fetch_url(updated.url, title_hint=updated.title)
                escalated_document = getattr(escalated_response, "document", None)
                if getattr(escalated_response, "success", False) and escalated_document is not None:
                    (
                        escalated_metadata,
                        escalated_content_type,
                        escalated_raw_bytes,
                        escalated_has_bytes,
                        escalated_text,
                        escalated_html,
                    ) = _unpack_document(escalated_document)
                    escalated_validation = self._validate_candidate_content(
                        citation_text=citation_text,
                        normalized_citation=normalized_citation,
                        url=updated.url,
                        title=updated.title,
                        content_type=escalated_content_type,
                        text=escalated_text,
                        html=escalated_html,
                    )
                    if escalated_validation.get("confirmed"):
                        document = escalated_document
                        metadata = escalated_metadata
                        content_type = escalated_content_type
                        raw_bytes = escalated_raw_bytes
                        has_bytes = escalated_has_bytes
                        document_text = escalated_text
                        document_html = escalated_html
                        candidate_validation = escalated_validation
                        extraction_recipe = self._build_extraction_recipe(
                            url=updated.url,
                            title=updated.title,
                            content_type=content_type,
                            text=document_text,
                            html=document_html,
                            has_bytes=has_bytes,
                        )
                else:
                    escalation_errors = [
                        str(getattr(error, "message", error))
                        for error in (getattr(escalated_response, "errors", None) or [])
                    ]

            suffix = self._artifact_suffix(url=updated.url, content_type=content_type, has_bytes=has_bytes)
            artifact_base = f"{index:02d}_{_slugify(updated.title or Path(urlparse(updated.url).path).stem or 'candidate-file', limit=48)}"
            artifact_path = artifacts_dir / f"{artifact_base}{suffix}"

            if has_bytes:
                artifact_path.write_bytes(bytes(raw_bytes))
            else:
                artifact_text = document_text or document_html
                artifact_path.write_text(artifact_text, encoding="utf-8")

            metadata_path = artifacts_dir / f"{artifact_base}.json"
            metadata_payload = {
                "url": updated.url,
                "title": updated.title,
                "discovered_from_url": updated.discovered_from_url,
                "source": updated.source,
                "source_type": updated.source_type,
                "content_type": content_type,
                "artifact_path": str(artifact_path),
                "artifact_size": artifact_path.stat().st_size if artifact_path.exists() else 0,
                "fetch_success": True,
                "text_excerpt": self._safe_metadata_excerpt(document_text or document_html),
                "extraction_provenance": dict(getattr(document, "extraction_provenance", {}) or {}),
                "extraction_recipe": extraction_recipe,
                "candidate_validation": candidate_validation,
                "escalation_errors": escalation_errors,
            }
            metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")

            updated.fetch_success = True
            updated.content_type = content_type
            updated.file_extension = suffix
            updated.artifact_path = str(artifact_path)
            updated.metadata_path = str(metadata_path)
            notes: List[str] = []
            if extraction_recipe.get("blocked_signals_detected"):
                notes.append("blocked_page_detected")
            if not candidate_validation.get("confirmed"):
                notes.append("citation_anchor_not_confirmed")
            if candidate_validation.get("no_result_detected"):
                notes.append("no_result_marker_detected")
            updated.notes = ";".join(notes) if notes else None
            materialized.append(updated)

        return materialized + candidate_file_list[_MAX_CANDIDATE_FETCHES:]

    @staticmethod
    def _target_scraper_file_for_corpus(corpus_key: Optional[str]) -> Optional[str]:
        mapping = {
            "state_laws": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            "state_admin_rules": "ipfs_datasets_py/processors/legal_scrapers/state_admin_rules_scraper.py",
            "state_court_rules": "ipfs_datasets_py/processors/legal_scrapers/state_procedure_rules_scraper.py",
            "federal_register": "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/federal_register_scraper.py",
            "us_code": "ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/us_code_scraper.py",
        }
        return mapping.get(str(corpus_key or "").strip().lower())

    def _write_scraper_patch_scaffold(
        self,
        *,
        manifest_dir: Path,
        citation_text: str,
        normalized_citation: str,
        corpus_key: Optional[str],
        candidates: Iterable[LegalSourceCandidate],
        candidate_files: Iterable[RecoveredCandidateFile],
    ) -> Optional[RecoveryScraperPatch]:
        target_file = self._target_scraper_file_for_corpus(corpus_key)
        if not target_file:
            return None

        primary_file = next((item for item in candidate_files if item.url), None)
        primary_candidate = next((item for item in candidates if item.url), None)
        source_url = self._preferred_scraper_patch_source_url(
            primary_file=primary_file,
            primary_candidate=primary_candidate,
        )
        if not source_url:
            return None

        host = urlparse(source_url).netloc.lower() or None
        try:
            from ...optimizers.agentic.patch_control import Patch
        except Exception:
            Patch = _FallbackPatch

        patch_id = f"recovery-{_slugify(normalized_citation, limit=40)}-{_slugify(host or 'host', limit=24)}"
        diff_content = self._build_scraper_patch_diff(
            target_file=target_file,
            citation_text=citation_text,
            source_url=source_url,
            discovered_from_url=getattr(primary_file, "discovered_from_url", None),
            host=host,
        )
        extraction_recipe_path = manifest_dir / "patches" / f"{patch_id}_extraction_recipe.json"
        extraction_recipe_path.parent.mkdir(parents=True, exist_ok=True)
        extraction_recipe = {
            "citation_text": citation_text,
            "normalized_citation": normalized_citation,
            "target_file": target_file,
            "host": host,
            "source_url": source_url,
            "candidate_files": [asdict(item) for item in candidate_files],
            "patch_intent": "Add host-specific extraction/fetch support for a legal source recovered after a Hugging Face lookup miss.",
            "common_crawl_fallback": "Use CommonCrawlSearchEngine.search_domain(host, query=search_query) when direct fetch is blocked by Cloudflare or similar anti-bot pages.",
        }
        extraction_recipe_path.write_text(json.dumps(extraction_recipe, indent=2, sort_keys=True), encoding="utf-8")
        patch = Patch(
            patch_id=patch_id,
            agent_id="legal_source_recovery",
            task_id=f"citation-recovery:{_slugify(normalized_citation, limit=48)}",
            description=f"Scraper scaffold for recovered source host {host or 'unknown'}",
            diff_content=diff_content,
            target_files=[target_file],
            metadata={
                "citation_text": citation_text,
                "normalized_citation": normalized_citation,
                "host": host,
                "candidate_url": source_url,
                "extraction_recipe_path": str(extraction_recipe_path),
            },
        )

        patch_manager = self._patch_manager_instance(manifest_dir=manifest_dir)
        patch_path = patch_manager.save_patch(patch, manifest_dir / "patches" / f"{patch_id}.patch")
        return RecoveryScraperPatch(
            patch_path=str(patch_path),
            target_file=target_file,
            host=host,
            rationale="Host-specific recovery scaffold generated from discovered candidate file.",
            extraction_recipe_path=str(extraction_recipe_path),
        )

    @staticmethod
    def _preferred_scraper_patch_source_url(
        *,
        primary_file: Optional[RecoveredCandidateFile],
        primary_candidate: Optional[LegalSourceCandidate],
    ) -> str:
        file_url = str(getattr(primary_file, "url", "") or "").strip()
        candidate_url = str(getattr(primary_candidate, "url", "") or "").strip()
        file_host = urlparse(file_url).netloc.lower()
        if candidate_url and (
            not file_url
            or file_host.startswith("unblock.")
            or "unblock.federalregister.gov" in file_host
        ):
            return candidate_url
        return file_url or candidate_url

    @staticmethod
    def _build_scraper_patch_diff(
        *,
        target_file: str,
        citation_text: str,
        source_url: str,
        discovered_from_url: Optional[str],
        host: Optional[str],
    ) -> str:
        function_name = f"_extract_recovered_{_slugify(host or 'host', limit=32).replace('-', '_')}_text"
        discovered_line = f"+# discovered_from: {discovered_from_url}\n" if discovered_from_url else ""
        return (
            f"diff --git a/{target_file} b/{target_file}\n"
            f"--- a/{target_file}\n"
            f"+++ b/{target_file}\n"
            "@@\n"
            "+from typing import Any\n"
            "+\n"
            f"+def {function_name}(document: Any) -> str:\n"
            "+    \"\"\"Extract text from a recovered legal source candidate.\n"
            "+\n"
            "+    Generated by the Bluebook self-healing recovery workflow after a\n"
            "+    Hugging Face corpus miss. Keep this host-specific and promote it into\n"
            "+    the surrounding scraper once validated against related corpus pages.\n"
            "+    \"\"\"\n"
            "+    metadata = dict(getattr(document, \"metadata\", {}) or {})\n"
            "+    text = str(getattr(document, \"text\", \"\") or \"\").strip()\n"
            "+    if text:\n"
            "+        return text\n"
            "+    html = str(getattr(document, \"html\", \"\") or metadata.get(\"html\", \"\") or \"\")\n"
            "+    if not html.strip():\n"
            "+        return \"\"\n"
            "+    try:\n"
            "+        from bs4 import BeautifulSoup\n"
            "+    except Exception:\n"
            "+        return html\n"
            "+    soup = BeautifulSoup(html, \"html.parser\")\n"
            "+    for selector in (\"main\", \"article\", \"#content\", \".content\", \".main-content\", \".document\", \".statute\", \".law\", \"pre\"):\n"
            "+        node = soup.select_one(selector)\n"
            "+        if node:\n"
            "+            extracted = node.get_text(\"\\n\", strip=True)\n"
            "+            if extracted:\n"
            "+                return extracted\n"
            "+    return soup.get_text(\"\\n\", strip=True)\n"
            "+\n"
            "+# Recovery notes for the scraper maintainer:\n"
            f"+# citation: {citation_text}\n"
            f"+# host: {host or ''}\n"
            f"+# candidate_url: {source_url}\n"
            f"{discovered_line}"
            "+# preferred_fetch_path: UnifiedWebArchivingAPI.fetch(url, domain=\"legal\")\n"
            "+# fallback_fetch_path: UnifiedWebScraper.scrape_sync(url)\n"
            "+# blocked_fetch_fallback: CommonCrawlSearchEngine.search_domain(host, query=search_query)\n"
            "+# hf_common_crawl_fallback: Common Crawl integration falls back to Hugging Face indexes when local CC assets are unavailable.\n"
        )

    @staticmethod
    def _rewrite_manifest_with_artifacts(
        *,
        manifest_path: Path,
        candidate_files: Iterable[RecoveredCandidateFile],
        scraper_patch: Optional[RecoveryScraperPatch],
    ) -> None:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["candidate_files"] = [asdict(item) for item in candidate_files]
        payload["scraper_patch"] = asdict(scraper_patch) if scraper_patch is not None else None
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _write_manifest(
        self,
        *,
        citation_text: str,
        normalized_citation: str,
        corpus: Any,
        state_code: Optional[str],
        query: str,
        candidates: Iterable[LegalSourceCandidate],
        archived_sources: Iterable[ArchivedSourceRecord],
        candidate_files: Iterable[RecoveredCandidateFile],
        search_backend_status: Optional[Dict[str, Any]] = None,
    ) -> tuple[Path, Path]:
        now = self._now_factory()
        corpus_root = Path.cwd() / "source_recovery"
        if corpus is not None:
            corpus_root = corpus.default_local_root() / "source_recovery"
        slug = _slugify(normalized_citation)
        stamp = now.strftime("%Y%m%d_%H%M%S")
        manifest_dir = corpus_root / f"{stamp}_{slug}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "recovery_manifest.json"
        payload = {
            "citation_text": citation_text,
            "normalized_citation": normalized_citation,
            "corpus_key": corpus.key if corpus is not None else None,
            "hf_dataset_id": corpus.hf_dataset_id if corpus is not None else None,
            "state_code": state_code,
            "search_query": query,
            "generated_at": now.isoformat(),
            "candidates": [asdict(item) for item in candidates],
            "archived_sources": [asdict(item) for item in archived_sources],
            "candidate_files": [asdict(item) for item in candidate_files],
            "scraper_patch": None,
            "search_backend_status": dict(search_backend_status or {}),
        }
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return manifest_dir, manifest_path


async def recover_missing_legal_citation_source(
    *,
    citation_text: str,
    normalized_citation: Optional[str] = None,
    corpus_key: Optional[str],
    state_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    enable_candidate_file_fetch: Optional[bool] = None,
) -> Dict[str, Any]:
    if enable_candidate_file_fetch is None:
        enable_candidate_file_fetch = _env_flag("LEGAL_SOURCE_RECOVERY_ENABLE_CANDIDATE_FILE_FETCH", default=False)
    workflow = LegalSourceRecoveryWorkflow(enable_candidate_file_fetch=bool(enable_candidate_file_fetch))
    result = await workflow.recover_unresolved_citation(
        citation_text=citation_text,
        normalized_citation=normalized_citation,
        corpus_key=corpus_key,
        state_code=state_code,
        metadata=metadata,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
    )
    return result.to_dict()


def build_recovery_feedback_entries_from_citation_audit(
    audit_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for document in list(audit_payload.get("unresolved_documents") or []):
        document_id = str(document.get("document_id") or "")
        document_title = str(document.get("document_title") or "")
        for citation in list(document.get("unmatched_citations") or []):
            if not isinstance(citation, dict):
                continue
            metadata = dict(citation.get("metadata") or {})
            entry = {
                "citation_text": str(citation.get("citation_text") or ""),
                "normalized_citation": str(citation.get("normalized_citation") or citation.get("citation_text") or ""),
                "citation_type": str(citation.get("citation_type") or ""),
                "corpus_key": str(citation.get("corpus_key") or metadata.get("recovery_corpus_key") or ""),
                "state_code": str(metadata.get("state_code") or ""),
                "candidate_corpora": [str(item) for item in list(metadata.get("candidate_corpora") or []) if str(item).strip()],
                "preferred_dataset_ids": [str(item) for item in list(metadata.get("preferred_dataset_ids") or []) if str(item).strip()],
                "preferred_parquet_files": [str(item) for item in list(metadata.get("preferred_parquet_files") or []) if str(item).strip()],
                "recovery_query": str(metadata.get("recovery_query") or ""),
                "document_id": document_id,
                "document_title": document_title,
            }
            dedupe_key = (
                entry["normalized_citation"],
                entry["corpus_key"],
                entry["state_code"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entries.append(entry)
    return entries


async def recover_citation_feedback_entries(
    feedback_entries: Iterable[Dict[str, Any]],
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
    workflow: Optional[LegalSourceRecoveryWorkflow] = None,
) -> Dict[str, Any]:
    active_workflow = workflow or LegalSourceRecoveryWorkflow()
    entries = [dict(item) for item in feedback_entries if isinstance(item, dict)]
    recoveries: List[Dict[str, Any]] = []
    for entry in entries:
        result = await active_workflow.recover_unresolved_citation(
            citation_text=str(entry.get("citation_text") or ""),
            normalized_citation=str(entry.get("normalized_citation") or entry.get("citation_text") or ""),
            corpus_key=str(entry.get("corpus_key") or "") or None,
            state_code=str(entry.get("state_code") or "") or None,
            metadata={
                "candidate_corpora": list(entry.get("candidate_corpora") or []),
            },
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
        )
        result_dict = result.to_dict()
        result_dict["feedback_entry"] = {
            **dict(result_dict.get("feedback_entry") or {}),
            "document_id": str(entry.get("document_id") or ""),
            "document_title": str(entry.get("document_title") or ""),
            "preferred_dataset_ids": list(entry.get("preferred_dataset_ids") or []),
            "preferred_parquet_files": list(entry.get("preferred_parquet_files") or []),
            "recovery_query": str(entry.get("recovery_query") or ""),
        }
        recoveries.append(result_dict)

    return {
        "status": "success",
        "feedback_entry_count": len(entries),
        "recovery_count": len(recoveries),
        "recoveries": recoveries,
        "publish_to_hf": bool(publish_to_hf),
        "source": "citation_feedback_recovery",
    }


async def recover_citation_audit_feedback(
    audit_payload: Dict[str, Any],
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
    workflow: Optional[LegalSourceRecoveryWorkflow] = None,
) -> Dict[str, Any]:
    entries = build_recovery_feedback_entries_from_citation_audit(audit_payload)
    result = await recover_citation_feedback_entries(
        entries,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
        workflow=workflow,
    )
    result["audit_document_count"] = int(audit_payload.get("document_count") or 0)
    result["audit_unmatched_citation_count"] = int(audit_payload.get("unmatched_citation_count") or 0)
    result["source"] = "citation_audit_feedback_recovery"
    return result
