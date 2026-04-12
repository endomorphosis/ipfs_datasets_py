"""CourtListener docket ingestion helpers for docket datasets."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
from io import BytesIO
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

try:
    from ..legal_scrapers.shared_fetch_cache import SharedFetchCache
except Exception:  # pragma: no cover
    SharedFetchCache = None  # type: ignore[assignment]

COURTLISTENER_API_ROOT = "https://www.courtlistener.com/api/rest/v4/"

__all__ = [
    "COURTLISTENER_API_ROOT",
    "CourtListenerIngestionError",
    "fetch_courtlistener_docket",
    "find_rich_courtlistener_docket",
    "fetch_random_courtlistener_docket",
    "sample_random_courtlistener_dockets_batch",
    "resolve_courtlistener_api_token",
]


class CourtListenerIngestionError(RuntimeError):
    """Raised when CourtListener docket ingestion fails."""


def _format_stage_timings(stage_timings: Dict[str, float]) -> str:
    if not stage_timings:
        return ""
    parts = [f"{key}={value:.4f}s" for key, value in stage_timings.items()]
    return ", ".join(parts)


def resolve_courtlistener_api_token(api_token: str | None = None) -> str | None:
    """Resolve a CourtListener API token from explicit input, env, or token file."""

    if api_token:
        return api_token.strip() or None

    env_token = str(os.environ.get("COURTLISTENER_API_TOKEN") or "").strip()
    if env_token:
        return env_token

    shared_secret_token = _load_shared_secret_value("COURTLISTENER_API_TOKEN")
    if shared_secret_token:
        return shared_secret_token

    token_path = Path.home() / ".config" / "courtlistener" / "token"
    try:
        token_text = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token_text = ""
    return token_text or None


def fetch_courtlistener_docket(
    identifier: str,
    *,
    api_token: str | None = None,
    include_recap_documents: bool = True,
    include_document_text: bool = True,
    enable_pdf_text_backfill: bool = True,
    enable_rendered_page_enrichment: bool = False,
    max_documents: int | None = None,
    page_size: int = 100,
    request_timeout_seconds: float = 30.0,
    requests_module: Any | None = None,
    shared_fetch_cache: Any | None = None,
) -> Dict[str, Any]:
    """Fetch and normalize a CourtListener docket into the docket dataset input shape."""

    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError(
                "CourtListener ingestion requires the 'requests' package."
            ) from exc

    fetch_cache = _resolve_fetch_cache(shared_fetch_cache)
    docket_id = _extract_docket_id(identifier)
    if not docket_id:
        raise CourtListenerIngestionError(f"Unable to determine CourtListener docket id from {identifier!r}")

    token = resolve_courtlistener_api_token(api_token)
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"

    docket_url = urljoin(COURTLISTENER_API_ROOT, f"dockets/{docket_id}/")
    docket_data = _get_json(
        docket_url,
        headers=headers,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
        fetch_cache=fetch_cache,
        cache_namespace="courtlistener_json",
        cache_payload_name=f"courtlistener_docket_{docket_id}",
    )
    docket_entries = _safe_list_fetch(
        urljoin(COURTLISTENER_API_ROOT, f"docket-entries/?docket={docket_id}&page_size={max(1, min(int(page_size or 100), 100))}"),
        headers=headers,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
        fetch_cache=fetch_cache,
        cache_namespace="courtlistener_json",
    )
    parties = _safe_list_fetch(
        urljoin(COURTLISTENER_API_ROOT, f"parties/?docket={docket_id}&page_size={max(1, min(int(page_size or 100), 100))}"),
        headers=headers,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
        fetch_cache=fetch_cache,
        cache_namespace="courtlistener_json",
    )
    recap_documents_error = ""

    documents: List[Dict[str, Any]] = []
    seen_document_ids: set[str] = set()

    summary_document = _build_docket_summary_document(docket_id, docket_data)
    documents.append(summary_document)
    seen_document_ids.add(str(summary_document.get("id") or ""))

    for entry_document in _build_docket_entry_documents(docket_id, docket_entries or docket_data.get("docket_entries") or docket_data.get("entries") or []):
        entry_id = str(entry_document.get("id") or "")
        if not entry_id or entry_id in seen_document_ids:
            continue
        documents.append(entry_document)
        seen_document_ids.add(entry_id)

    if include_recap_documents:
        try:
            recap_documents = list(
                _iter_recap_documents(
                    docket_id,
                    headers=headers,
                    requests_module=requests_module,
                    page_size=page_size,
                    max_documents=max_documents,
                    request_timeout_seconds=request_timeout_seconds,
                    fetch_cache=fetch_cache,
                )
            )
        except CourtListenerIngestionError as exc:
            if not _is_throttled_courtlistener_error(exc):
                raise
            recap_documents = []
            recap_documents_error = str(exc)
        for recap_document in recap_documents:
            document_id = str(recap_document.get("id") or "")
            if not document_id or document_id in seen_document_ids:
                continue
            normalized = _normalize_recap_document(docket_id, recap_document)
            raw_text = str(
                recap_document.get("plain_text")
                or recap_document.get("text")
                or ""
            ).strip()
            if include_document_text and not raw_text:
                detail_url = urljoin(COURTLISTENER_API_ROOT, f"recap-documents/{document_id}/")
                detail_data = _get_json(
                    detail_url,
                    headers=headers,
                    requests_module=requests_module,
                    request_timeout_seconds=request_timeout_seconds,
                    fetch_cache=fetch_cache,
                    cache_namespace="courtlistener_json",
                    cache_payload_name=f"courtlistener_recap_{document_id}",
                )
                normalized = _normalize_recap_document(docket_id, detail_data)
                if enable_pdf_text_backfill:
                    normalized = _enrich_recap_text_from_pdf(
                        normalized,
                        headers=headers,
                        requests_module=requests_module,
                        request_timeout_seconds=request_timeout_seconds,
                        fetch_cache=fetch_cache,
                    )
            documents.append(normalized)
            seen_document_ids.add(document_id)

    plaintiff_docket, defendant_docket = _build_party_dockets(parties or docket_data.get("parties") or docket_data.get("party_details") or [])
    absolute_url = _absolute_courtlistener_url(
        docket_data.get("absolute_url")
        or docket_data.get("docket_absolute_url")
        or docket_data.get("url")
        or ""
    )
    case_name = str(
        docket_data.get("case_name")
        or docket_data.get("caseName")
        or docket_data.get("short_case_name")
        or docket_id
    ).strip()
    court = str(
        docket_data.get("court")
        or docket_data.get("court_id")
        or docket_data.get("court_full_name")
        or docket_data.get("court_name")
        or ""
    ).strip()
    rendered_page_summary: Dict[str, Any] | None = None
    if enable_rendered_page_enrichment and absolute_url:
        try:
            rendered_page_summary = _fetch_rendered_courtlistener_docket_summary(absolute_url)
        except Exception:
            rendered_page_summary = None
    if rendered_page_summary:
        documents = _merge_rendered_docket_rows_into_documents(
            docket_id,
            documents,
            rendered_page_summary=rendered_page_summary,
            docket_url=absolute_url or docket_url,
        )

    payload = {
        "docket_id": str(docket_data.get("id") or docket_id),
        "case_name": case_name,
        "court": court,
        "documents": documents,
        "plaintiff_docket": plaintiff_docket,
        "defendant_docket": defendant_docket,
        "authorities": [],
        "source_type": "courtlistener",
        "source_path": docket_url,
        "source_url": absolute_url or docket_url,
        "metadata": {
            "source": "courtlistener",
            "courtlistener_api_root": COURTLISTENER_API_ROOT,
            "courtlistener_docket_url": absolute_url or docket_url,
            "recap_document_count": max(0, len(documents) - 1),
            **({"courtlistener_recap_documents_error": recap_documents_error} if recap_documents_error else {}),
            **({"rendered_docket_page": rendered_page_summary} if rendered_page_summary else {}),
        },
    }
    _record_known_courtlistener_docket_id(fetch_cache, str(payload.get("docket_id") or docket_id))
    return payload


def fetch_random_courtlistener_docket(
    *,
    api_token: str | None = None,
    seed: int | None = None,
    sample_pages: int = 5,
    page_size: int = 20,
    requests_module: Any | None = None,
    include_recap_documents: bool = True,
    include_document_text: bool = True,
    enable_pdf_text_backfill: bool = False,
    minimum_entry_count: int = 1,
    minimum_recap_document_count: int = 0,
    minimum_downloaded_document_count: int = 3,
    minimum_text_document_count: int = 2,
    strict_content_requirements: bool = True,
    request_timeout_seconds: float = 20.0,
    shared_fetch_cache: Any | None = None,
    fallback_docket_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Fetch a pseudo-random CourtListener docket from recent docket listings."""

    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError as exc:  # pragma: no cover
            raise CourtListenerIngestionError(
                "CourtListener ingestion requires the 'requests' package."
            ) from exc

    token = resolve_courtlistener_api_token(api_token)
    headers = {}
    if token:
        headers["Authorization"] = f"Token {token}"
    fetch_cache = _resolve_fetch_cache(shared_fetch_cache)

    rng = random.Random(seed)
    candidate_ids: List[str] = []
    used_cached_candidates = False
    listing_errors: List[str] = []
    stage_timings: Dict[str, float] = {}
    max_pages = max(1, int(sample_pages or 1))
    per_page = max(1, min(int(page_size or 20), 100))
    listing_started = time.monotonic()
    for page_number in range(1, max_pages + 1):
        url = urljoin(COURTLISTENER_API_ROOT, f"dockets/?page={page_number}&page_size={per_page}")
        try:
            payload = _get_json(
                url,
                headers=headers,
                requests_module=requests_module,
                request_timeout_seconds=request_timeout_seconds,
                fetch_cache=fetch_cache,
                cache_namespace="courtlistener_json",
            )
        except CourtListenerIngestionError as exc:
            listing_errors.append(str(exc))
            if _is_throttled_courtlistener_error(exc):
                break
            continue
        for item in list(payload.get("results") or []):
            if not isinstance(item, dict):
                continue
            docket_id = str(item.get("id") or "").strip()
            if docket_id:
                candidate_ids.append(docket_id)
    stage_timings["sample_listing_seconds"] = round(time.monotonic() - listing_started, 4)
    if not candidate_ids:
        cached_ids = _collect_known_courtlistener_docket_ids(fetch_cache, fallback_docket_ids=fallback_docket_ids)
        if cached_ids:
            candidate_ids.extend(cached_ids)
            used_cached_candidates = True
            stage_timings["cached_candidate_count"] = float(len(cached_ids))

    if not candidate_ids:
        timing_detail = _format_stage_timings(stage_timings)
        if any(_is_throttled_courtlistener_error(error) for error in listing_errors):
            detail = next(
                (error for error in listing_errors if _is_throttled_courtlistener_error(error)),
                "",
            )
            raise CourtListenerIngestionError(
                "CourtListener random sampling was throttled while listing dockets."
                + (f" timings: {timing_detail}" if timing_detail else "")
                + (f" detail: {detail}" if detail else "")
            )
        raise CourtListenerIngestionError(
            "Unable to sample any CourtListener dockets for random selection."
            + (f" timings: {timing_detail}" if timing_detail else "")
            + (f" listing_errors: {listing_errors[:2]}" if listing_errors else "")
        )
    shuffled_ids = list(candidate_ids)
    rng.shuffle(shuffled_ids)
    selected_id = ""
    best_payload: Dict[str, Any] | None = None
    best_score = (-1, -1, -1)
    min_entries = max(0, int(minimum_entry_count or 0))
    min_recap_documents = max(0, int(minimum_recap_document_count or 0))
    min_downloaded_documents = max(1, int(minimum_downloaded_document_count or 1))
    min_text_documents = max(0, int(minimum_text_document_count or 0))
    count_checks_started = time.monotonic()
    count_checks = 0
    docket_fetch_started = 0.0
    docket_fetches = 0
    for candidate_id in shuffled_ids:
        try:
            entry_count = _count_list_endpoint(
                urljoin(COURTLISTENER_API_ROOT, f"docket-entries/?docket={candidate_id}&page_size=1"),
                headers=headers,
                requests_module=requests_module,
                request_timeout_seconds=request_timeout_seconds,
            )
            count_checks += 1
            recap_count = 0
            if include_recap_documents:
                recap_count = _count_list_endpoint(
                    urljoin(COURTLISTENER_API_ROOT, f"recap-documents/?docket_entry__docket={candidate_id}&page_size=1"),
                    headers=headers,
                    requests_module=requests_module,
                    request_timeout_seconds=request_timeout_seconds,
                )
                count_checks += 1
        except CourtListenerIngestionError as exc:
            if not _is_throttled_courtlistener_error(exc) or not used_cached_candidates:
                raise
            stage_timings["count_throttle_count"] = float(int(stage_timings.get("count_throttle_count", 0.0)) + 1)
            entry_count = min_entries
            recap_count = min_recap_documents
        if entry_count < min_entries or recap_count < min_recap_documents:
            continue
        try:
            if docket_fetch_started == 0.0:
                docket_fetch_started = time.monotonic()
            payload = fetch_courtlistener_docket(
                candidate_id,
                api_token=token,
                include_recap_documents=include_recap_documents,
                include_document_text=include_document_text,
                enable_pdf_text_backfill=enable_pdf_text_backfill,
                page_size=page_size,
                request_timeout_seconds=request_timeout_seconds,
                requests_module=requests_module,
                shared_fetch_cache=fetch_cache,
            )
            docket_fetches += 1
        except CourtListenerIngestionError:
            continue
        documents = list(payload.get("documents") or [])
        document_count = len(documents)
        text_document_count = sum(1 for item in documents if _document_has_substantive_text(item))
        score = (document_count, text_document_count, entry_count + recap_count)
        if score > best_score:
            best_score = score
            best_payload = payload
        if document_count >= min_downloaded_documents and text_document_count >= min_text_documents:
            stage_timings["count_check_seconds"] = round(time.monotonic() - count_checks_started, 4)
            stage_timings["count_check_calls"] = float(count_checks)
            if docket_fetch_started:
                stage_timings["docket_fetch_seconds"] = round(time.monotonic() - docket_fetch_started, 4)
                stage_timings["docket_fetch_count"] = float(docket_fetches)
            payload_metadata = dict(payload.get("metadata") or {})
            payload_metadata["courtlistener_sampling_stage_timings"] = dict(stage_timings)
            payload["metadata"] = payload_metadata
            return payload
        selected_id = candidate_id
    if strict_content_requirements:
        stage_timings["count_check_seconds"] = round(time.monotonic() - count_checks_started, 4)
        stage_timings["count_check_calls"] = float(count_checks)
        if docket_fetch_started:
            stage_timings["docket_fetch_seconds"] = round(time.monotonic() - docket_fetch_started, 4)
            stage_timings["docket_fetch_count"] = float(docket_fetches)
        timing_detail = _format_stage_timings(stage_timings)
        raise CourtListenerIngestionError(
            "Unable to find a sampled CourtListener docket meeting the minimum downloaded/text document requirements."
            + (f" timings: {timing_detail}" if timing_detail else "")
        )
    if best_payload is not None:
        stage_timings["count_check_seconds"] = round(time.monotonic() - count_checks_started, 4)
        stage_timings["count_check_calls"] = float(count_checks)
        if docket_fetch_started:
            stage_timings["docket_fetch_seconds"] = round(time.monotonic() - docket_fetch_started, 4)
            stage_timings["docket_fetch_count"] = float(docket_fetches)
        payload_metadata = dict(best_payload.get("metadata") or {})
        payload_metadata["courtlistener_sampling_stage_timings"] = dict(stage_timings)
        best_payload["metadata"] = payload_metadata
        return best_payload
    if not selected_id:
        selected_id = shuffled_ids[0]
    payload = fetch_courtlistener_docket(
        selected_id,
        api_token=token,
        include_recap_documents=include_recap_documents,
        include_document_text=include_document_text,
        enable_pdf_text_backfill=enable_pdf_text_backfill,
        page_size=page_size,
        request_timeout_seconds=request_timeout_seconds,
        requests_module=requests_module,
        shared_fetch_cache=fetch_cache,
    )
    stage_timings["count_check_seconds"] = round(time.monotonic() - count_checks_started, 4)
    stage_timings["count_check_calls"] = float(count_checks)
    payload_metadata = dict(payload.get("metadata") or {})
    payload_metadata["courtlistener_sampling_stage_timings"] = dict(stage_timings)
    payload["metadata"] = payload_metadata
    return payload


def find_rich_courtlistener_docket(
    *,
    api_token: str | None = None,
    seed: int | None = None,
    attempts: int = 6,
    sample_pages: int = 5,
    page_size: int = 20,
    include_recap_documents: bool = True,
    include_document_text: bool = True,
    enable_pdf_text_backfill: bool = False,
    minimum_entry_count: int = 5,
    minimum_recap_document_count: int = 3,
    minimum_downloaded_document_count: int = 6,
    minimum_text_document_count: int = 4,
    minimum_substantive_text_document_count: int = 1,
    minimum_citation_count: int = 0,
    minimum_temporal_formula_count: int = 5,
    minimum_proof_count: int = 5,
    allow_partial_fallback: bool = False,
    use_fast_final_diagnostics: bool = False,
    request_timeout_seconds: float = 20.0,
    requests_module: Any | None = None,
    shared_fetch_cache: Any | None = None,
    fallback_docket_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Sample CourtListener dockets until one yields meaningful formal enrichment."""

    base_seed = 0 if seed is None else int(seed)
    best_candidate: Dict[str, Any] | None = None
    best_score = (-1, -1, -1, -1, -1)
    best_fast_candidate: Dict[str, Any] | None = None
    best_fast_score = (-1, -1)
    failures: List[str] = []

    for attempt_index in range(max(1, int(attempts or 1))):
        attempt_seed = base_seed + attempt_index
        try:
            docket_payload = fetch_random_courtlistener_docket(
                api_token=api_token,
                seed=attempt_seed,
                sample_pages=sample_pages,
                page_size=page_size,
                requests_module=requests_module,
                include_recap_documents=include_recap_documents,
                include_document_text=include_document_text,
                enable_pdf_text_backfill=enable_pdf_text_backfill,
                minimum_entry_count=minimum_entry_count,
                minimum_recap_document_count=minimum_recap_document_count,
                minimum_downloaded_document_count=minimum_downloaded_document_count,
                minimum_text_document_count=minimum_text_document_count,
                request_timeout_seconds=request_timeout_seconds,
                strict_content_requirements=not bool(allow_partial_fallback),
                shared_fetch_cache=shared_fetch_cache,
                fallback_docket_ids=fallback_docket_ids,
            )
        except CourtListenerIngestionError as exc:
            failures.append(str(exc))
            continue

        if allow_partial_fallback:
            fast_diagnostics = _evaluate_docket_fast_richness(docket_payload)
            fast_score = (
                int(fast_diagnostics.get("substantive_text_document_count") or 0),
                int(fast_diagnostics.get("document_count") or 0),
            )
            if fast_score > best_fast_score:
                best_fast_score = fast_score
                best_fast_candidate = {
                    "docket": docket_payload,
                    "diagnostics": fast_diagnostics,
                }
            continue

        formal_diagnostics = _evaluate_docket_formal_richness(docket_payload)
        score = (
            int(formal_diagnostics.get("citation_count") or 0),
            int(formal_diagnostics.get("substantive_text_document_count") or 0),
            int(
                formal_diagnostics.get("substantive_temporal_formula_count")
                or formal_diagnostics.get("temporal_formula_count")
                or 0
            ),
            int(formal_diagnostics.get("substantive_proof_count") or formal_diagnostics.get("proof_count") or 0),
            int(formal_diagnostics.get("deontic_statement_count") or 0),
        )
        if score > best_score:
            best_score = score
            best_candidate = {
                "docket": docket_payload,
                "diagnostics": formal_diagnostics,
            }
        if (
            int(formal_diagnostics.get("citation_count") or 0)
            >= max(0, int(minimum_citation_count or 0))
            and int(formal_diagnostics.get("substantive_text_document_count") or 0)
            >= max(0, int(minimum_substantive_text_document_count or 0))
            and
            int(
                formal_diagnostics.get("substantive_temporal_formula_count")
                or formal_diagnostics.get("temporal_formula_count")
                or 0
            ) >= max(0, int(minimum_temporal_formula_count or 0))
            and int(formal_diagnostics.get("substantive_proof_count") or formal_diagnostics.get("proof_count") or 0)
            >= max(0, int(minimum_proof_count or 0))
        ):
            return {
                "docket": docket_payload,
                "diagnostics": formal_diagnostics,
                "attempt_count": attempt_index + 1,
                "status": "success",
            }

    if allow_partial_fallback and best_fast_candidate is not None:
        if use_fast_final_diagnostics:
            return {
                "docket": best_fast_candidate["docket"],
                "diagnostics": best_fast_candidate["diagnostics"],
                "attempt_count": max(1, int(attempts or 1)),
                "status": "best_effort",
                "failures": failures,
                "selection_mode": "fast_prefilter_fast_final",
            }
        formal_diagnostics = _evaluate_docket_formal_richness(best_fast_candidate["docket"])
        score = (
            int(formal_diagnostics.get("citation_count") or 0),
            int(formal_diagnostics.get("substantive_text_document_count") or 0),
            int(
                formal_diagnostics.get("substantive_temporal_formula_count")
                or formal_diagnostics.get("temporal_formula_count")
                or 0
            ),
            int(formal_diagnostics.get("substantive_proof_count") or formal_diagnostics.get("proof_count") or 0),
            int(formal_diagnostics.get("deontic_statement_count") or 0),
        )
        best_candidate = {
            "docket": best_fast_candidate["docket"],
            "diagnostics": formal_diagnostics,
        }
        if score > best_score:
            best_score = score
        if (
            int(formal_diagnostics.get("citation_count") or 0)
            >= max(0, int(minimum_citation_count or 0))
            and int(formal_diagnostics.get("substantive_text_document_count") or 0)
            >= max(0, int(minimum_substantive_text_document_count or 0))
            and
            int(
                formal_diagnostics.get("substantive_temporal_formula_count")
                or formal_diagnostics.get("temporal_formula_count")
                or 0
            ) >= max(0, int(minimum_temporal_formula_count or 0))
            and int(formal_diagnostics.get("substantive_proof_count") or formal_diagnostics.get("proof_count") or 0)
            >= max(0, int(minimum_proof_count or 0))
        ):
            return {
                "docket": best_fast_candidate["docket"],
                "diagnostics": formal_diagnostics,
                "attempt_count": max(1, int(attempts or 1)),
                "status": "success",
                "selection_mode": "fast_prefilter_partial_fallback",
            }

    if best_candidate is not None:
        return {
            **best_candidate,
            "attempt_count": max(1, int(attempts or 1)),
            "status": "best_effort",
            "failures": failures,
            **({"selection_mode": "fast_prefilter_partial_fallback"} if allow_partial_fallback else {}),
        }

    raise CourtListenerIngestionError(
        "Unable to find a CourtListener docket that satisfies the requested downloaded/text/formal richness thresholds."
    )


def sample_random_courtlistener_dockets_batch(
    *,
    api_token: str | None = None,
    base_seed: int | None = None,
    batch_size: int = 8,
    max_workers: int = 4,
    sample_pages: int = 5,
    page_size: int = 20,
    include_recap_documents: bool = True,
    include_document_text: bool = True,
    enable_pdf_text_backfill: bool = False,
    minimum_entry_count: int = 1,
    minimum_recap_document_count: int = 0,
    minimum_downloaded_document_count: int = 3,
    minimum_text_document_count: int = 2,
    use_fast_diagnostics: bool = False,
    allow_partial_fallback: bool = False,
    request_timeout_seconds: float = 20.0,
    sample_timeout_seconds: float = 45.0,
    requests_module: Any | None = None,
    shared_fetch_cache: Any | None = None,
    fallback_docket_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Sample a batch of pseudo-random CourtListener dockets in parallel and collect diagnostics."""

    seeds = [int(base_seed or 0) + offset for offset in range(max(1, int(batch_size or 1)))]
    worker_count = max(1, min(int(max_workers or 1), len(seeds)))

    def _sample(seed_value: int) -> Dict[str, Any]:
        stage_timings: Dict[str, float] = {}
        try:
            started = time.monotonic()
            docket_payload = fetch_random_courtlistener_docket(
                api_token=api_token,
                seed=seed_value,
                sample_pages=sample_pages,
                page_size=page_size,
                requests_module=requests_module,
                include_recap_documents=include_recap_documents,
                include_document_text=include_document_text,
                enable_pdf_text_backfill=enable_pdf_text_backfill,
                minimum_entry_count=minimum_entry_count,
                minimum_recap_document_count=minimum_recap_document_count,
                minimum_downloaded_document_count=minimum_downloaded_document_count,
                minimum_text_document_count=minimum_text_document_count,
                request_timeout_seconds=request_timeout_seconds,
                strict_content_requirements=not bool(allow_partial_fallback),
                shared_fetch_cache=shared_fetch_cache,
                fallback_docket_ids=fallback_docket_ids,
            )
            stage_timings["fetch_random_docket_seconds"] = round(time.monotonic() - started, 4)
            diagnostics_started = time.monotonic()
            if use_fast_diagnostics:
                diagnostics = _evaluate_docket_fast_richness(docket_payload)
            else:
                diagnostics = _evaluate_docket_formal_richness(docket_payload)
            stage_timings["diagnostics_seconds"] = round(time.monotonic() - diagnostics_started, 4)
            return {
                "seed": seed_value,
                "status": "success",
                "docket": {
                    "docket_id": str(docket_payload.get("docket_id") or ""),
                    "case_name": str(docket_payload.get("case_name") or ""),
                    "court": str(docket_payload.get("court") or ""),
                },
                "diagnostics": diagnostics,
                "stage_timings": stage_timings,
            }
        except Exception as exc:
            return {
                "seed": seed_value,
                "status": "failed",
                "error": str(exc),
                "stage_timings": stage_timings,
            }

    samples: List[Dict[str, Any]] = []
    executor = ThreadPoolExecutor(max_workers=worker_count)
    try:
        futures = {executor.submit(_sample, seed): seed for seed in seeds}
        done, not_done = wait(futures, timeout=max(1.0, float(sample_timeout_seconds or 45.0)))
        for future in done:
            samples.append(future.result())
        for future in not_done:
            seed_value = futures[future]
            future.cancel()
            samples.append(
                {
                    "seed": seed_value,
                    "status": "failed",
                    "error": f"sample_timeout_after_{float(sample_timeout_seconds or 45.0):.1f}s",
                }
            )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    samples.sort(key=lambda item: int(item.get("seed") or 0))
    successful = [item for item in samples if item.get("status") == "success"]
    failed = [item for item in samples if item.get("status") != "success"]
    citation_bearing = [
        item for item in successful if int(dict(item.get("diagnostics") or {}).get("citation_count") or 0) > 0
    ]
    substantive_text = [
        item
        for item in successful
        if int(dict(item.get("diagnostics") or {}).get("substantive_text_document_count") or 0) > 0
    ]
    best_sample = None
    if successful:
        best_sample = max(
            successful,
            key=lambda item: (
                int(dict(item.get("diagnostics") or {}).get("citation_count") or 0),
                int(dict(item.get("diagnostics") or {}).get("substantive_text_document_count") or 0),
                int(dict(item.get("diagnostics") or {}).get("document_count") or 0),
            ),
        )

    return {
        "status": "success",
        "batch_size": len(seeds),
        "success_count": len(successful),
        "failure_count": len(failed),
        "citation_bearing_count": len(citation_bearing),
        "substantive_text_count": len(substantive_text),
        "selected": best_sample,
        "samples": samples,
        "timed_out_count": sum(1 for item in failed if "sample_timeout_after_" in str(item.get("error") or "")),
        "source": "courtlistener_random_batch_sampling",
    }


def _evaluate_docket_fast_richness(docket_payload: Dict[str, Any]) -> Dict[str, Any]:
    documents = list(docket_payload.get("documents") or [])
    return {
        "docket_id": str(docket_payload.get("docket_id") or ""),
        "case_name": str(docket_payload.get("case_name") or ""),
        "document_count": len(documents),
        "text_document_count": sum(1 for item in documents if str(dict(item).get("text") or "").strip()),
        "substantive_text_document_count": sum(
            1 for item in documents if _document_has_substantive_text(item)
        ),
        "citation_count": 0,
        "matched_citation_count": 0,
        "unmatched_citation_count": 0,
        "documents_with_citations": 0,
        "temporal_formula_count": 0,
        "substantive_temporal_formula_count": 0,
        "document_temporal_formula_count": 0,
        "proof_count": 0,
        "substantive_proof_count": 0,
        "dcec_formula_count": 0,
        "frame_count": 0,
        "document_frame_count": 0,
        "deontic_statement_count": 0,
        "knowledge_graph_entity_count": 0,
        "knowledge_graph_relationship_count": 0,
        "proof_store_present": False,
        "diagnostic_mode": "fast",
    }


def _evaluate_docket_formal_richness(docket_payload: Dict[str, Any]) -> Dict[str, Any]:
    from .docket_dataset import DocketDatasetBuilder
    from .docket_dataset import audit_docket_dataset_citation_sources

    dataset = DocketDatasetBuilder(router_max_documents=1).build_from_docket(docket_payload)
    proof_assistant = dict(dataset.proof_assistant or {})
    formal_summary = dict((dataset.metadata.get("artifact_provenance") or {}).get("formal_logic") or {})
    documents = list(dataset.documents or [])
    citation_audit = audit_docket_dataset_citation_sources(dataset)
    return {
        "dataset_id": dataset.dataset_id,
        "docket_id": dataset.docket_id,
        "case_name": dataset.case_name,
        "document_count": len(documents),
        "text_document_count": sum(1 for item in documents if str(item.text or "").strip()),
        "substantive_text_document_count": sum(
            1
            for item in documents
            if _document_has_substantive_text(
                {
                    "text": item.text,
                    "title": item.title,
                    "metadata": item.metadata,
                }
            )
        ),
        "citation_count": int(citation_audit.get("citation_count") or 0),
        "matched_citation_count": int(citation_audit.get("matched_citation_count") or 0),
        "unmatched_citation_count": int(citation_audit.get("unmatched_citation_count") or 0),
        "documents_with_citations": int(citation_audit.get("documents_with_citations") or 0),
        "temporal_formula_count": int(formal_summary.get("temporal_formula_count") or 0),
        "substantive_temporal_formula_count": int(formal_summary.get("temporal_formula_count") or 0),
        "document_temporal_formula_count": int(formal_summary.get("document_temporal_formula_count") or 0),
        "proof_count": int(formal_summary.get("proof_count") or 0),
        "substantive_proof_count": int(formal_summary.get("proof_count") or 0),
        "dcec_formula_count": int(formal_summary.get("dcec_formula_count") or 0),
        "frame_count": int(formal_summary.get("frame_count") or 0),
        "document_frame_count": int(formal_summary.get("document_frame_count") or 0),
        "deontic_statement_count": int(formal_summary.get("deontic_statement_count") or 0),
        "knowledge_graph_entity_count": len(list((dataset.knowledge_graph or {}).get("entities") or [])),
        "knowledge_graph_relationship_count": len(list((dataset.knowledge_graph or {}).get("relationships") or [])),
        "proof_store_present": bool(proof_assistant.get("proof_store")),
    }


def _count_list_endpoint(
    url: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 30.0,
) -> int:
    try:
        payload = _get_json(
            url,
            headers=headers,
            requests_module=requests_module,
            request_timeout_seconds=request_timeout_seconds,
        )
    except CourtListenerIngestionError as exc:
        if _is_throttled_courtlistener_error(exc):
            raise
        return 0
    try:
        return max(0, int(payload.get("count") or 0))
    except Exception:
        return len(list(payload.get("results") or []))


def _extract_docket_id(identifier: str) -> str:
    text = str(identifier or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return text
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        for index, part in enumerate(parts):
            if part == "dockets" and index + 1 < len(parts):
                return parts[index + 1]
        return parts[-1] if parts else ""
    return text


def _shared_secret_paths() -> List[Path]:
    configured = str(os.environ.get("IPFS_DATASETS_SECRETS_FILE") or "").strip()
    candidates = [
        configured,
        str(Path.home() / ".config" / "ipfs_datasets_py" / "secrets.json"),
        "/etc/github-runner-secrets/secrets.json",
        "/var/lib/github-runner/secrets.json",
    ]
    paths: List[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path not in paths:
            paths.append(path)
    return paths


def _load_shared_secret_value(key: str) -> str | None:
    secret_key = str(key or "").strip()
    if not secret_key:
        return None
    for path in _shared_secret_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        value = str(payload.get(secret_key) or "").strip()
        if value:
            return value
    return None


def _is_throttled_courtlistener_error(error: Exception | str) -> bool:
    message = str(error or "").lower()
    return "429" in message or "throttled" in message or "too many requests" in message


def _fetch_rendered_courtlistener_docket_summary(url: str) -> Dict[str, Any]:
    return asyncio.run(_fetch_rendered_courtlistener_docket_summary_async(url))


async def _fetch_rendered_courtlistener_docket_summary_async(url: str) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise CourtListenerIngestionError("Playwright is required for rendered CourtListener docket enrichment.") from exc

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1400, "height": 1000},
                locale="en-US",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            body_text = await page.locator("body").inner_text()
            return _summarize_rendered_docket_text(body_text, url=url)
        finally:
            await browser.close()


def _summarize_rendered_docket_text(body_text: str, *, url: str) -> Dict[str, Any]:
    normalized = "\n".join(line.strip() for line in str(body_text or "").replace("\u00ad", "").splitlines() if line.strip())
    row_pattern = re.compile(
        r"(?P<number>\d+)\n(?P<date>[A-Z][a-z]{2} \d{1,2}, \d{4})\n(?P<kind>Main Document)\n(?P<title>.+?)\nBuy on PACER",
        re.DOTALL,
    )
    rows: List[Dict[str, Any]] = []
    for match in row_pattern.finditer(normalized):
        title = " ".join(str(match.group("title") or "").split())
        rows.append(
            {
                "document_number": str(match.group("number") or "").strip(),
                "date_filed": str(match.group("date") or "").strip(),
                "kind": str(match.group("kind") or "").strip(),
                "title": title,
                "pacer_available": True,
            }
        )
    if not rows:
        lines = [line.strip().replace("\u00ad", "") for line in normalized.splitlines() if line.strip()]
        marker_index = next(
            (index for index, line in enumerate(lines) if line.lower() == "document number"),
            -1,
        )
        if marker_index >= 0:
            cursor = marker_index + 3
            while cursor < len(lines):
                line = lines[cursor]
                if line.lower() in {"newsletter", "about", "help & faq", "donate"}:
                    break
                document_number = ""
                if re.fullmatch(r"\d+", line):
                    document_number = line
                    cursor += 1
                    if cursor >= len(lines):
                        break
                    line = lines[cursor]
                if not re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", line):
                    cursor += 1
                    continue
                date_filed = line
                cursor += 1
                if cursor >= len(lines):
                    break
                kind = lines[cursor]
                cursor += 1
                if cursor >= len(lines):
                    break
                title = lines[cursor]
                pacer_available = False
                if cursor + 1 < len(lines) and lines[cursor + 1] == "Buy on PACER":
                    pacer_available = True
                    cursor += 2
                    while cursor < len(lines) and re.fullmatch(r"\d+\s*🙏?", lines[cursor]):
                        cursor += 1
                else:
                    cursor += 1
                rows.append(
                    {
                        "document_number": document_number,
                        "date_filed": date_filed,
                        "kind": kind,
                        "title": title,
                        "pacer_available": pacer_available,
                    }
                )
    return {
        "url": url,
        "row_count": len(rows),
        "rows": rows[:50],
        "contains_pacer_purchase_links": "buy on pacer" in normalized.lower(),
        "body_text_preview": normalized[:1200],
    }


def _merge_rendered_docket_rows_into_documents(
    docket_id: str,
    documents: List[Dict[str, Any]],
    *,
    rendered_page_summary: Dict[str, Any],
    docket_url: str,
) -> List[Dict[str, Any]]:
    rows = [dict(item) for item in list(rendered_page_summary.get("rows") or []) if isinstance(item, dict)]
    if not rows:
        return documents

    updated_documents: List[Dict[str, Any]] = [dict(item) for item in documents]
    matched_row_indexes: set[int] = set()

    for index, document in enumerate(updated_documents):
        document_number = str(document.get("document_number") or "").strip()
        title = _normalize_rendered_title(document.get("title") or "")
        best_row_index: int | None = None
        for row_index, row in enumerate(rows):
            row_number = str(row.get("document_number") or "").strip()
            row_title = _normalize_rendered_title(row.get("title") or "")
            if document_number and row_number and document_number == row_number:
                best_row_index = row_index
                break
            if title and row_title and title == row_title:
                best_row_index = row_index
                break
        if best_row_index is None:
            continue
        matched_row_indexes.add(best_row_index)
        row = rows[best_row_index]
        metadata = dict(document.get("metadata") or {})
        metadata["rendered_docket_row"] = dict(row)
        acquisition_candidates = list(metadata.get("acquisition_candidates") or [])
        acquisition_candidates.append(
            {
                "source": "courtlistener_rendered_docket_page",
                "docket_url": docket_url,
                "pacer_available": bool(row.get("pacer_available")),
                "document_number": str(row.get("document_number") or ""),
                "title": str(row.get("title") or ""),
            }
        )
        metadata["acquisition_candidates"] = acquisition_candidates
        document["metadata"] = metadata
        updated_documents[index] = document

    for row_index, row in enumerate(rows):
        if row_index in matched_row_indexes:
            continue
        synthetic_id = f"{docket_id}_rendered_row_{str(row.get('document_number') or row_index + 1).strip() or row_index + 1}"
        title = str(row.get("title") or "Rendered docket row").strip()
        document_number = str(row.get("document_number") or "").strip()
        date_filed = str(row.get("date_filed") or "").strip()
        kind = str(row.get("kind") or "").strip()
        text_lines = [
            "Rendered CourtListener docket row",
            f"Document number: {document_number}" if document_number else "",
            f"Date filed: {date_filed}" if date_filed else "",
            f"Kind: {kind}" if kind else "",
            f"Description: {title}" if title else "",
            "PACER purchase link available" if bool(row.get("pacer_available")) else "",
        ]
        updated_documents.append(
            {
                "id": synthetic_id,
                "title": title,
                "text": "\n".join(line for line in text_lines if line),
                "date_filed": date_filed,
                "document_number": document_number,
                "source_url": docket_url,
                "document_type": "courtlistener_rendered_docket_row",
                "metadata": {
                    "rendered_docket_row": dict(row),
                    "acquisition_candidates": [
                        {
                            "source": "courtlistener_rendered_docket_page",
                            "docket_url": docket_url,
                            "pacer_available": bool(row.get("pacer_available")),
                            "document_number": document_number,
                            "title": title,
                        }
                    ],
                    "text_extraction": {"source": "courtlistener_rendered_docket"},
                },
            }
        )
    return updated_documents


def _normalize_rendered_title(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00ad", "").split()).strip().lower()


def _collect_known_courtlistener_docket_ids(
    fetch_cache: Any | None,
    *,
    fallback_docket_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    seen: set[str] = set()
    collected: List[str] = []
    for raw_value in list(fallback_docket_ids or []):
        docket_id = str(raw_value or "").strip()
        if docket_id and docket_id not in seen:
            seen.add(docket_id)
            collected.append(docket_id)
    if fetch_cache is None:
        return collected
    payload = _load_cached_json(
        fetch_cache,
        namespace="courtlistener_state",
        url="courtlistener_known_docket_ids",
    ) or {}
    for raw_value in list(payload.get("docket_ids") or []):
        docket_id = str(raw_value or "").strip()
        if docket_id and docket_id not in seen:
            seen.add(docket_id)
            collected.append(docket_id)
    return collected


def _record_known_courtlistener_docket_id(fetch_cache: Any | None, docket_id: str) -> None:
    normalized = str(docket_id or "").strip()
    if not normalized or fetch_cache is None:
        return
    existing = _load_cached_json(
        fetch_cache,
        namespace="courtlistener_state",
        url="courtlistener_known_docket_ids",
    ) or {}
    known_ids = [str(item or "").strip() for item in list(existing.get("docket_ids") or []) if str(item or "").strip()]
    if normalized in known_ids:
        return
    known_ids.append(normalized)
    known_ids = known_ids[-200:]
    _save_cached_json(
        fetch_cache,
        namespace="courtlistener_state",
        url="courtlistener_known_docket_ids",
        payload={"docket_ids": known_ids, "updated_at": time.time()},
        payload_name="courtlistener_known_docket_ids",
    )


def _get_json(
    url: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 30.0,
    fetch_cache: Any | None = None,
    cache_namespace: str = "courtlistener_json",
    cache_payload_name: str | None = None,
) -> Dict[str, Any]:
    normalized_url = _normalize_cache_url(url)
    cached_payload = _load_cached_json(fetch_cache, namespace=cache_namespace, url=normalized_url)
    if cached_payload is not None:
        return cached_payload
    response = requests_module.get(url, headers=headers, timeout=max(1.0, float(request_timeout_seconds or 30.0)))
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        body = ""
        try:
            body = str(getattr(response, "text", "") or "")[:300]
        except Exception:
            body = ""
        raise CourtListenerIngestionError(f"CourtListener request failed ({status_code}) for {url}: {body}")
    data = response.json()
    if not isinstance(data, dict):
        raise CourtListenerIngestionError(f"Expected JSON object from CourtListener for {url}")
    _save_cached_json(
        fetch_cache,
        namespace=cache_namespace,
        url=normalized_url,
        payload=data,
        payload_name=cache_payload_name or _cache_payload_name_from_url(url),
    )
    return data


def _get_binary(
    url: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 60.0,
    fetch_cache: Any | None = None,
) -> bytes:
    normalized_url = _normalize_cache_url(url)
    cached_blob = _load_cached_binary(fetch_cache, namespace="courtlistener_binary", url=normalized_url)
    if cached_blob:
        return cached_blob
    response = requests_module.get(url, headers=headers, timeout=max(1.0, float(request_timeout_seconds or 60.0)))
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        return b""
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        blob = content
    else:
        blob = bytes(content or b"")
    _save_cached_binary(
        fetch_cache,
        namespace="courtlistener_binary",
        url=normalized_url,
        payload=blob,
        payload_name=_cache_payload_name_from_url(url),
    )
    return blob


def _iter_paginated_results(
    url: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 30.0,
    fetch_cache: Any | None = None,
    cache_namespace: str = "courtlistener_json",
) -> Iterable[Dict[str, Any]]:
    next_url: str | None = url
    while next_url:
        payload = _get_json(
            next_url,
            headers=headers,
            requests_module=requests_module,
            request_timeout_seconds=request_timeout_seconds,
            fetch_cache=fetch_cache,
            cache_namespace=cache_namespace,
        )
        results = payload.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    yield item
        next_candidate = payload.get("next")
        if not next_candidate:
            break
        next_url = urljoin(next_url, str(next_candidate))


def _iter_recap_documents(
    docket_id: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    page_size: int,
    max_documents: int | None,
    request_timeout_seconds: float = 30.0,
    fetch_cache: Any | None = None,
) -> Iterable[Dict[str, Any]]:
    page_size = max(1, min(int(page_size or 100), 100))
    url = urljoin(COURTLISTENER_API_ROOT, f"recap-documents/?docket_entry__docket={docket_id}&page_size={page_size}")
    count = 0
    for item in _iter_paginated_results(
        url,
        headers=headers,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
        fetch_cache=fetch_cache,
    ):
        yield item
        count += 1
        if max_documents is not None and count >= max(0, int(max_documents)):
            break


def _safe_list_fetch(
    url: str,
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 30.0,
    fetch_cache: Any | None = None,
    cache_namespace: str = "courtlistener_json",
) -> List[Dict[str, Any]]:
    try:
        return list(
            _iter_paginated_results(
                url,
                headers=headers,
                requests_module=requests_module,
                request_timeout_seconds=request_timeout_seconds,
                fetch_cache=fetch_cache,
                cache_namespace=cache_namespace,
            )
        )
    except Exception:
        return []


def _build_party_dockets(party_items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    plaintiffs: List[Dict[str, Any]] = []
    defendants: List[Dict[str, Any]] = []
    for index, party in enumerate(list(party_items), start=1):
        if not isinstance(party, dict):
            continue
        name = str(
            party.get("name")
            or party.get("party_name")
            or party.get("slug")
            or f"Party {index}"
        ).strip()
        role_names = [
            str(role_item.get("name") or "").strip()
            for role_item in list(party.get("party_types") or [])
            if isinstance(role_item, dict) and str(role_item.get("name") or "").strip()
        ]
        role = str(
            party.get("role")
            or party.get("party_type")
            or party.get("party_type_label")
            or party.get("type")
            or ", ".join(role_names)
            or ""
        ).strip()
        text = f"{role or 'Party'} listed on CourtListener docket: {name}"
        payload = {
            "id": str(party.get("id") or f"party_{index}"),
            "title": name,
            "text": text,
            "role": role,
            "metadata": {"raw": dict(party), "role_names": role_names},
        }
        normalized_role = role.lower()
        if "plaintiff" in normalized_role or normalized_role.startswith("petitioner"):
            plaintiffs.append(payload)
        elif "defendant" in normalized_role or normalized_role.startswith("respondent"):
            defendants.append(payload)
    return plaintiffs, defendants


def _build_docket_summary_document(docket_id: str, docket_data: Dict[str, Any]) -> Dict[str, Any]:
    lines = [
        f"Case name: {docket_data.get('case_name') or docket_data.get('caseName') or docket_id}",
        f"Court: {docket_data.get('court_full_name') or docket_data.get('court_name') or docket_data.get('court') or docket_data.get('court_id') or ''}",
        f"Docket number: {docket_data.get('docket_number') or docket_data.get('docketNumber') or ''}",
        f"Date filed: {docket_data.get('date_filed') or docket_data.get('dateFiled') or ''}",
        f"Date terminated: {docket_data.get('date_terminated') or docket_data.get('dateTerminated') or ''}",
        f"Assigned to: {docket_data.get('assigned_to') or docket_data.get('assignedTo') or ''}",
        f"Cause: {docket_data.get('cause') or ''}",
        f"Nature of suit: {docket_data.get('nature_of_suit') or docket_data.get('natureOfSuit') or ''}",
        f"Jury demand: {docket_data.get('jury_demand') or docket_data.get('juryDemand') or ''}",
    ]
    party_names = []
    for party in list(docket_data.get("parties") or []):
        if isinstance(party, dict):
            name = str(party.get("name") or party.get("party_name") or "").strip()
            role = str(party.get("role") or party.get("party_type") or "").strip()
            if name:
                party_names.append(f"{name} ({role})" if role else name)
    if party_names:
        lines.append(f"Parties: {', '.join(party_names)}")

    absolute_url = _absolute_courtlistener_url(
        docket_data.get("absolute_url")
        or docket_data.get("docket_absolute_url")
        or docket_data.get("url")
        or ""
    )
    return {
        "id": f"{docket_id}_summary",
        "title": "CourtListener docket summary",
        "text": "\n".join(line for line in lines if line.split(":", 1)[-1].strip()),
        "date_filed": str(docket_data.get("date_filed") or docket_data.get("dateFiled") or ""),
        "document_number": str(docket_data.get("docket_number") or docket_data.get("docketNumber") or ""),
        "source_url": absolute_url,
        "document_type": "courtlistener_docket_summary",
        "metadata": {"raw": dict(docket_data), "text_extraction": {"source": "courtlistener_summary_metadata"}},
    }


def _build_docket_entry_documents(docket_id: str, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, entry in enumerate(list(entries), start=1):
        if not isinstance(entry, dict):
            continue
        title = str(
            entry.get("description")
            or entry.get("short_description")
            or entry.get("title")
            or f"Docket entry {index}"
        ).strip()
        text_lines = [
            f"Entry number: {entry.get('entry_number') or entry.get('document_number') or index}",
            f"Date filed: {entry.get('date_filed') or entry.get('dateFiled') or ''}",
            f"Description: {entry.get('description') or entry.get('short_description') or title}",
        ]
        normalized.append(
            {
                "id": str(entry.get("id") or f"{docket_id}_entry_{index}"),
                "title": title,
                "text": "\n".join(line for line in text_lines if line.split(":", 1)[-1].strip()),
                "date_filed": str(entry.get("date_filed") or entry.get("dateFiled") or ""),
                "document_number": str(entry.get("entry_number") or entry.get("document_number") or index),
                "source_url": _absolute_courtlistener_url(entry.get("absolute_url") or entry.get("url") or ""),
                "document_type": "courtlistener_docket_entry",
                "metadata": {"raw": dict(entry), "text_extraction": {"source": "courtlistener_entry_metadata"}},
            }
        )
    return normalized


def _normalize_recap_document(docket_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    document_id = str(item.get("id") or item.get("document_id") or "")
    title = str(
        item.get("description")
        or item.get("document_type")
        or item.get("short_description")
        or f"RECAP document {document_id or 'unknown'}"
    ).strip()
    source_url = _absolute_courtlistener_url(
        item.get("filepath_local")
        or item.get("download_url")
        or item.get("absolute_url")
        or item.get("url")
        or ""
    )
    plain_text = str(item.get("plain_text") or item.get("text") or "").strip()
    metadata_text = str(item.get("description") or item.get("snippet") or "").strip()
    text = plain_text if _looks_like_substantive_courtlistener_text(plain_text, title=title) else ""
    extraction_source = "courtlistener_plain_text" if text else "courtlistener_metadata_only"
    extraction_meta: Dict[str, Any] = {"source": extraction_source}
    if not text and metadata_text:
        extraction_meta["metadata_text_preview"] = metadata_text[:240]
    return {
        "id": document_id or f"{docket_id}_recap",
        "title": title,
        "text": text,
        "date_filed": str(item.get("date_filed") or item.get("dateFiled") or ""),
        "document_number": str(item.get("document_number") or item.get("entry_number") or ""),
        "source_url": source_url,
        "document_type": str(item.get("document_type") or "recap_document"),
        "metadata": {"raw": dict(item), "text_extraction": extraction_meta},
    }


def _absolute_courtlistener_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return urljoin("https://www.courtlistener.com", text)


def _enrich_recap_text_from_pdf(
    document: Dict[str, Any],
    *,
    headers: Dict[str, str],
    requests_module: Any,
    request_timeout_seconds: float = 60.0,
    fetch_cache: Any | None = None,
) -> Dict[str, Any]:
    updated = dict(document)
    metadata = dict(updated.get("metadata") or {})
    extraction_meta = dict(metadata.get("text_extraction") or {})
    source_url = str(updated.get("source_url") or "").strip()
    if not source_url or not source_url.lower().endswith(".pdf"):
        extraction_meta.setdefault("source", "courtlistener_metadata_only")
        metadata["text_extraction"] = extraction_meta
        updated["metadata"] = metadata
        return updated

    pdf_bytes = _get_binary(
        source_url,
        headers=headers,
        requests_module=requests_module,
        request_timeout_seconds=request_timeout_seconds,
        fetch_cache=fetch_cache,
    )
    if not pdf_bytes:
        extraction_meta.update({"source": extraction_meta.get("source") or "courtlistener_metadata_only", "pdf_fetch_failed": True})
        metadata["text_extraction"] = extraction_meta
        updated["metadata"] = metadata
        return updated
    extraction_meta["pdf_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    binary_cache_entry = _load_cached_binary_metadata(fetch_cache, namespace="courtlistener_binary", url=_normalize_cache_url(source_url))
    if binary_cache_entry:
        extraction_meta["ipfs_cid"] = binary_cache_entry.get("ipfs_cid")

    extracted_text, extraction_source = _extract_text_from_pdf_bytes(pdf_bytes)
    if extracted_text:
        updated["text"] = extracted_text
        extraction_meta["source"] = extraction_source
        extraction_meta["text_length"] = len(extracted_text)
    else:
        extraction_meta.setdefault("source", "courtlistener_metadata_only")
        extraction_meta["pdf_text_unavailable"] = True
    metadata["text_extraction"] = extraction_meta
    updated["metadata"] = metadata
    return updated


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> tuple[str, str]:
    direct_text = _extract_text_from_pdf_bytes_direct(pdf_bytes)
    if _looks_like_useful_text(direct_text):
        return direct_text, "pdf_text"

    ocr_text = _extract_text_from_pdf_bytes_ocr(pdf_bytes)
    if _looks_like_useful_text(ocr_text):
        return ocr_text, "pdf_ocr"
    return "", ""


def _looks_like_substantive_courtlistener_text(text: str, *, title: str = "") -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    normalized = " ".join(candidate.split())
    normalized_title = " ".join(str(title or "").split()).strip()
    if normalized_title and normalized.lower() == normalized_title.lower():
        return False
    if len(normalized) < 80 and normalized.count(" ") < 8:
        return False
    return True


def _document_has_substantive_text(document: Dict[str, Any]) -> bool:
    metadata = dict(document.get("metadata") or {})
    extraction_meta = dict(metadata.get("text_extraction") or {})
    source = str(extraction_meta.get("source") or "").strip().lower()
    if source in {
        "courtlistener_metadata_only",
        "courtlistener_entry_metadata",
        "courtlistener_summary_metadata",
    }:
        return False
    text = str(document.get("text") or "").strip()
    if not text:
        return False
    return _looks_like_substantive_courtlistener_text(text, title=str(document.get("title") or ""))


def _extract_text_from_pdf_bytes_direct(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        text_parts = []
        for page in list(reader.pages):
            page_text = str(page.extract_text() or "").strip()
            if page_text:
                text_parts.append(page_text)
        return "\n\n".join(text_parts).strip()
    except Exception:
        return ""


def _extract_text_from_pdf_bytes_ocr(pdf_bytes: bytes) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except Exception:
        return ""

    try:
        text_parts: List[str] = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_num in range(min(len(doc), 10)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                image = Image.open(BytesIO(pix.tobytes("png")))
                page_text = str(pytesseract.image_to_string(image) or "").strip()
                if page_text:
                    text_parts.append(f"[Page {page_num + 1} OCR]\n{page_text}")
        return "\n\n".join(text_parts).strip()
    except Exception:
        return ""


def _looks_like_useful_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if len(normalized) < 80:
        return False
    alpha_count = sum(1 for ch in normalized if ch.isalpha())
    return alpha_count >= 40


def _resolve_fetch_cache(fetch_cache: Any | None) -> Any | None:
    if fetch_cache is not None:
        return fetch_cache
    if SharedFetchCache is None:
        return None
    try:
        return SharedFetchCache.from_env()
    except Exception:
        return None


def _normalize_cache_url(url: str) -> str:
    if SharedFetchCache is not None:
        try:
            return SharedFetchCache.normalize_url(url)
        except Exception:
            pass
    return str(url or "").strip()


def _cache_payload_name_from_url(url: str) -> str:
    normalized = _normalize_cache_url(url)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"courtlistener_{digest}"


def _load_cached_json(fetch_cache: Any | None, *, namespace: str, url: str) -> Dict[str, Any] | None:
    if fetch_cache is None or not hasattr(fetch_cache, "load"):
        return None
    try:
        payload = fetch_cache.load(namespace=namespace, url=url)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _save_cached_json(
    fetch_cache: Any | None,
    *,
    namespace: str,
    url: str,
    payload: Dict[str, Any],
    payload_name: str,
) -> None:
    if fetch_cache is None or not hasattr(fetch_cache, "save"):
        return
    try:
        fetch_cache.save(namespace=namespace, url=url, payload=payload, payload_name=payload_name)
    except Exception:
        return


def _load_cached_binary(fetch_cache: Any | None, *, namespace: str, url: str) -> bytes:
    payload = _load_cached_json(fetch_cache, namespace=namespace, url=url)
    if not payload:
        return b""
    encoded = str(payload.get("content_base64") or "").strip()
    if not encoded:
        return b""
    try:
        return base64.b64decode(encoded)
    except Exception:
        return b""


def _load_cached_binary_metadata(fetch_cache: Any | None, *, namespace: str, url: str) -> Dict[str, Any] | None:
    payload = _load_cached_json(fetch_cache, namespace=namespace, url=url)
    if not payload:
        return None
    cache_meta = payload.get("_cache")
    return dict(cache_meta) if isinstance(cache_meta, dict) else {}


def _save_cached_binary(
    fetch_cache: Any | None,
    *,
    namespace: str,
    url: str,
    payload: bytes,
    payload_name: str,
) -> None:
    if not payload:
        return
    encoded_payload = {
        "url": url,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }
    _save_cached_json(
        fetch_cache,
        namespace=namespace,
        url=url,
        payload=encoded_payload,
        payload_name=payload_name,
    )
