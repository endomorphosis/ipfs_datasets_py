"""Fallback recovery workflow for unresolved legal citations.

This module ties together the existing legal search, archive, and Hugging Face
publish infrastructure so unresolved legal citations can be tracked back to
candidate official sources and recorded in a canonical recovery manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol
from urllib.parse import urlparse
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
    if result.get("source") == "common_crawl_indexes":
        score += 1
    return score


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
        from ..legal_scrapers.legal_web_archive_search import LegalWebArchiveSearch

        return LegalWebArchiveSearch(auto_archive=False, use_hf_indexes=False)

    def _archiver_instance(self) -> Any:
        if self._archiver is not None:
            return self._archiver
        from .parallel_web_archiver import ParallelWebArchiver

        return ParallelWebArchiver()

    def _publisher(self) -> Callable[..., Dict[str, Any]]:
        if self._publish_func is not None:
            return self._publish_func
        from scripts.repair.publish_parquet_to_hf import publish

        return publish

    def _fetch_api_instance(self) -> Any:
        if self._fetch_api is not None:
            return self._fetch_api
        from ..web_archiving.unified_api import UnifiedWebArchivingAPI

        return UnifiedWebArchivingAPI()

    def _patch_manager_instance(self, *, manifest_dir: Path) -> Any:
        if self._patch_manager is not None:
            return self._patch_manager
        from ...optimizers.agentic.patch_control import PatchManager

        return PatchManager(patches_dir=manifest_dir / "patches", enable_cache=False)

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
        from .multi_engine_legal_search import multi_engine_legal_search

        return await multi_engine_legal_search(
            query=query,
            engines=engines,
            max_results=max_results,
            brave_api_key=(os.getenv("BRAVE_API_KEY") or os.getenv("BRAVE_SEARCH_API_KEY") or None),
        )

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
        live_results: List[Dict[str, Any]] = []
        archived_results: List[Dict[str, Any]] = []
        backend_status = self._search_backend_status()
        backend_status["archive_search_error"] = ""
        backend_status["live_search_error"] = ""
        backend_status["multi_engine_error"] = ""
        backend_status["multi_engine_used"] = False
        backend_status["engines_attempted"] = []

        effective_live_searcher = self._live_searcher or getattr(searcher, "legal_searcher", None)
        if effective_live_searcher is not None:
            try:
                live_payload = effective_live_searcher.search(query=query, max_results=max_candidates)
                live_results = list((live_payload or {}).get("results", []) or [])
            except Exception:
                live_results = []
                backend_status["live_search_error"] = "live_search_failed"

        if not live_results:
            try:
                engines: List[str] = []
                if backend_status["brave_configured"]:
                    engines.append("brave")
                if backend_status["duckduckgo_configured"]:
                    engines.append("duckduckgo")
                backend_status["engines_attempted"] = list(engines)
                if engines:
                    multi_engine_payload = await self._multi_engine_search(
                        query=query,
                        engines=engines,
                        max_results=max_candidates,
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
            except Exception as exc:
                backend_status["multi_engine_error"] = str(exc)

        effective_archive_searcher = self._archive_searcher or searcher
        if effective_archive_searcher is not None and hasattr(effective_archive_searcher, "search_with_indexes"):
            try:
                archive_payload = effective_archive_searcher.search_with_indexes(
                    query=query,
                    jurisdiction_type=jurisdiction_type,
                    state_code=state_code,
                    max_results=max_candidates,
                )
                archived_results = list((archive_payload or {}).get("results", []) or [])
            except Exception as exc:
                archived_results = []
                backend_status["archive_search_error"] = str(exc)

        merged_results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for source_type, rows in (("current", live_results), ("archived", archived_results)):
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
            archive_results = await archiver.archive_urls_parallel(
                [item.url for item in candidates[:archive_top_k]],
                jurisdiction=jurisdiction_type,
                state_code=state_code,
            )
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
        )

        if self._enable_candidate_file_fetch:
            candidate_files = self._materialize_candidate_file_artifacts(
                manifest_dir=manifest_dir,
                candidate_files=candidate_files,
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
                "allow_patterns": ["*.json"],
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
    ) -> int:
        score = 0
        domain = urlparse(url).netloc.lower()
        hay = f"{url} {title or ''} {content_type or ''}".lower()
        ext = Path(urlparse(url).path).suffix.lower()
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
        if not cls._is_downloadable_legal_file(url=normalized_url, title=title, content_type=content_type):
            return
        score = cls._candidate_file_score(
            url=normalized_url,
            title=title,
            content_type=content_type,
            state_code=state_code,
        )
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

    def _discover_candidate_files(
        self,
        *,
        candidates: Iterable[LegalSourceCandidate],
        corpus_key: Optional[str],
        state_code: Optional[str],
    ) -> List[RecoveredCandidateFile]:
        del corpus_key
        fetch_api = self._fetch_api_instance()
        discovered: Dict[str, RecoveredCandidateFile] = {}

        for candidate in list(candidates)[:4]:
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
                fetch_response = fetch_api.fetch(
                    candidate.url,
                    domain="legal",
                    metadata={"title_hint": candidate.title or ""},
                )
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

            for link in list(document_metadata.get("links") or [])[:50]:
                if not isinstance(link, dict):
                    continue
                self._register_candidate_file(
                    storage=discovered,
                    url=str(link.get("url") or ""),
                    title=str(link.get("text") or "") or None,
                    discovered_from_url=candidate.url,
                    source=candidate.source,
                    source_type=candidate.source_type,
                    content_type=None,
                    state_code=state_code,
                )

        files = list(discovered.values())
        files.sort(key=lambda item: (-item.score, item.url))
        return files[:8]

    @staticmethod
    def _artifact_suffix(*, url: str, content_type: Optional[str], has_bytes: bool) -> str:
        ext = Path(urlparse(url).path).suffix.lower()
        if ext:
            return ext
        lowered = str(content_type or "").split(";", 1)[0].strip().lower()
        if lowered in DOWNLOADABLE_CONTENT_TYPE_SUFFIXES:
            return DOWNLOADABLE_CONTENT_TYPE_SUFFIXES[lowered]
        if has_bytes:
            return ".bin"
        return ".txt"

    @staticmethod
    def _safe_metadata_excerpt(text: str, *, limit: int = 1200) -> str:
        cleaned = " ".join(str(text or "").split())
        return cleaned[:limit]

    def _materialize_candidate_file_artifacts(
        self,
        *,
        manifest_dir: Path,
        candidate_files: Iterable[RecoveredCandidateFile],
    ) -> List[RecoveredCandidateFile]:
        fetch_api = self._fetch_api_instance()
        artifacts_dir = manifest_dir / "candidate_files"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        materialized: List[RecoveredCandidateFile] = []
        for index, item in enumerate(list(candidate_files)[:3], start=1):
            updated = RecoveredCandidateFile(**asdict(item))
            try:
                fetch_response = fetch_api.fetch(
                    updated.url,
                    domain="legal",
                    metadata={"title_hint": updated.title or ""},
                )
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

            metadata = dict(getattr(document, "metadata", {}) or {})
            content_type = str(getattr(document, "content_type", "") or metadata.get("content_type") or "").strip() or None
            raw_bytes = metadata.get("raw_bytes")
            has_bytes = isinstance(raw_bytes, (bytes, bytearray)) and len(raw_bytes) > 0
            suffix = self._artifact_suffix(url=updated.url, content_type=content_type, has_bytes=has_bytes)
            artifact_base = f"{index:02d}_{_slugify(updated.title or Path(urlparse(updated.url).path).stem or 'candidate-file', limit=48)}"
            artifact_path = artifacts_dir / f"{artifact_base}{suffix}"

            if has_bytes:
                artifact_path.write_bytes(bytes(raw_bytes))
            else:
                artifact_text = str(getattr(document, "text", "") or getattr(document, "html", "") or "")
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
                "text_excerpt": self._safe_metadata_excerpt(getattr(document, "text", "") or ""),
                "extraction_provenance": dict(getattr(document, "extraction_provenance", {}) or {}),
            }
            metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")

            updated.fetch_success = True
            updated.content_type = content_type
            updated.file_extension = suffix
            updated.artifact_path = str(artifact_path)
            updated.metadata_path = str(metadata_path)
            materialized.append(updated)

        return materialized + list(candidate_files)[3:]

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
        source_url = primary_file.url if primary_file is not None else (primary_candidate.url if primary_candidate is not None else "")
        if not source_url:
            return None

        host = urlparse(source_url).netloc.lower() or None
        from ...optimizers.agentic.patch_control import Patch

        patch_id = f"recovery-{_slugify(normalized_citation, limit=40)}-{_slugify(host or 'host', limit=24)}"
        diff_content = self._build_scraper_patch_diff(
            target_file=target_file,
            citation_text=citation_text,
            source_url=source_url,
            discovered_from_url=getattr(primary_file, "discovered_from_url", None),
            host=host,
        )
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
            },
        )

        patch_manager = self._patch_manager_instance(manifest_dir=manifest_dir)
        patch_path = patch_manager.save_patch(patch, manifest_dir / "patches" / f"{patch_id}.patch")
        return RecoveryScraperPatch(
            patch_path=str(patch_path),
            target_file=target_file,
            host=host,
            rationale="Host-specific recovery scaffold generated from discovered candidate file.",
        )

    @staticmethod
    def _build_scraper_patch_diff(
        *,
        target_file: str,
        citation_text: str,
        source_url: str,
        discovered_from_url: Optional[str],
        host: Optional[str],
    ) -> str:
        discovered_line = f"# discovered_from: {discovered_from_url}\n" if discovered_from_url else ""
        return (
            f"diff --git a/{target_file} b/{target_file}\n"
            f"--- a/{target_file}\n"
            f"+++ b/{target_file}\n"
            "@@\n"
            "+# TODO(recovery): add host-specific file retrieval using UnifiedWebArchivingAPI or UnifiedWebScraper.\n"
            f"+# citation: {citation_text}\n"
            f"+# host: {host or ''}\n"
            f"+# candidate_url: {source_url}\n"
            f"+{discovered_line}"
            "+# preferred_fetch_path: UnifiedWebArchivingAPI.fetch(url, domain=\"legal\")\n"
            "+# fallback_fetch_path: UnifiedWebScraper.scrape_sync(url)\n"
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
) -> Dict[str, Any]:
    workflow = LegalSourceRecoveryWorkflow(enable_candidate_file_fetch=True)
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
