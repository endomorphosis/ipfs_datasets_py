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

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "candidates": [asdict(item) for item in self.candidates],
            "archived_sources": [asdict(item) for item in self.archived_sources],
        }


class LegalSourceRecoveryWorkflow:
    def __init__(
        self,
        *,
        archive_searcher: Optional[_ArchiveSearcher] = None,
        live_searcher: Optional[_LiveSearcher] = None,
        archiver: Any = None,
        publish_func: Optional[Callable[..., Dict[str, Any]]] = None,
        now_factory: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._archive_searcher = archive_searcher
        self._live_searcher = live_searcher
        self._archiver = archiver
        self._publish_func = publish_func
        self._now_factory = now_factory or datetime.utcnow

    def _searcher(self) -> Any:
        if self._archive_searcher is not None or self._live_searcher is not None:
            return None
        from .legal_web_archive_search import LegalWebArchiveSearch

        return LegalWebArchiveSearch(auto_archive=False, use_hf_indexes=True)

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
        if (not live_results) and effective_archive_searcher is not None and hasattr(effective_archive_searcher, "search_with_indexes"):
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

        manifest_dir, manifest_path = self._write_manifest(
            citation_text=citation_text,
            normalized_citation=normalized_citation or citation_text,
            corpus=corpus,
            state_code=state_code,
            query=query,
            candidates=candidates,
            archived_sources=archived_sources,
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
        )

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
    workflow = LegalSourceRecoveryWorkflow()
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
